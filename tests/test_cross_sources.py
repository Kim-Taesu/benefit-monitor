import io
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from benefit_monitor import cost_policy
from benefit_monitor.cross_sources import allowed_domains, related_urls

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,11,7,12,tzinfo=ZoneInfo('Asia/Seoul'))
DOMAINS={'www.seoul.go.kr','news.seoul.go.kr'}
OWN='https://www.seoul.go.kr/news/1'


class Response(io.BytesIO):
    headers={'Content-Type':'text/html; charset=utf-8'}


class RelatedUrlTests(unittest.TestCase):
    def cand(self,title='어르신 10% 할인 시니어 동행상점',url=OWN):
        return {'source':'seoul','url':url,'title':title}

    def test_links_inside_body_on_allowlisted_domains_only(self):
        doc={'links':['https://news.seoul.go.kr/x','https://blog.example/y',OWN]}
        self.assertEqual(related_urls(doc,self.cand(),[],DOMAINS),['https://news.seoul.go.kr/x'])

    def test_peer_titles_ranked_by_similarity(self):
        peers=[self.cand('시니어 동행상점 90곳 어디?','https://www.seoul.go.kr/news/2'),
               self.cand('청년 면접실','https://www.seoul.go.kr/news/3')]
        self.assertEqual(related_urls({'links':[]},self.cand(),peers,DOMAINS),['https://www.seoul.go.kr/news/2'])

    def test_limit_and_dedup(self):
        links=['https://news.seoul.go.kr/%d'%i for i in range(5)]+['https://news.seoul.go.kr/0']
        out=related_urls({'links':links},self.cand(),[],DOMAINS)
        self.assertEqual(len(out),3);self.assertEqual(len(set(out)),3)

    def test_non_fetchable_links_and_short_titles(self):
        doc={'links':['https://news.seoul.go.kr/a.pdf','https://news.seoul.go.kr/fileDown?id=1','https://news.seoul.go.kr/ok']}
        self.assertEqual(related_urls(doc,self.cand(),[],DOMAINS),['https://news.seoul.go.kr/ok'])
        peers=[self.cand('공지','https://www.seoul.go.kr/news/9')]
        self.assertEqual(related_urls({'links':[]},self.cand('공지'),peers,DOMAINS),[])

    def test_allowed_domains(self):
        self.assertEqual(allowed_domains({'a':{'domains':['x.kr']},'b':{'domains':['y.kr','x.kr']}}),{'x.kr','y.kr'})


class HostDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        config={'sources':[{'id':'seoul','domains':['www.seoul.go.kr','news.seoul.go.kr'],'routes':[],'feed_url':None}]}
        (self.root/'sources.yaml').write_text(json.dumps(config))
        for name in ('README.md','research.md','research-extraction.md','schemas/research-extraction-v3.schema.json'):
            path=self.root/'docs/ai'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('테스트')
        self.candidate={'source':'seoul','url':OWN,'title':'공식 프로그램','summary':'x','needs_recheck':True}
        self.pages={}
        cost_policy.reset(100)

    def body(self,text):
        return ('<html><main>'+text+' Program application and verified official details for a public benefit. Full conditions and deadlines.</main></html>')

    def transport(self,request):
        url=request.full_url
        self.requested=getattr(self,'requested',[])+[url]
        if url.endswith('/robots.txt'):return Response(b'User-agent: *\nAllow: /')
        return Response(self.pages[url].encode())

    def run_review(self,limit=None):
        from benefit_monitor.ai_review import review_candidates
        if limit:cost_policy.reset(limit)
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport):
            return review_candidates(self.root,[self.candidate],NOW,2,False)

    def staged(self):
        return json.loads(next((self.root/'.tools/ai-inputs').glob('*.json')).read_text())

    def test_host_documents_dedup_by_body_hash(self):
        same=self.body('same')
        self.pages={OWN:same.replace('</main>','<a href="https://news.seoul.go.kr/dup">x</a></main>'),
                    'https://news.seoul.go.kr/dup':same.replace('</main>','<a href="https://news.seoul.go.kr/dup">x</a></main>')}
        self.run_review()
        host=self.staged()
        self.assertEqual(len(host['documents']),1)

    def test_related_documents_collected_and_unverified_recorded(self):
        self.pages={OWN:self.body('A <a href="https://news.seoul.go.kr/b">b</a> <a href="https://blog.example/y">y</a>'),
                    'https://news.seoul.go.kr/b':self.body('B different')}
        self.run_review()
        host=self.staged()
        self.assertEqual(len(host['documents']),2)
        self.assertEqual(host['documents'][0]['requested_url'],OWN)
        self.assertEqual(host['candidates'][0]['document_ids'],[d['id'] for d in host['documents']])
        self.assertEqual(host['unverified_links'],['https://blog.example/y'])
        self.run_review()  # staged multi-document input is accepted again

    def test_nav_links_ignored_and_failed_related_does_not_block_host(self):
        from benefit_monitor.official_reader import extract_links
        html=('<nav><a href="https://news.seoul.go.kr/menu">m</a></nav><header><a href="/h/x">h</a></header>'
              '<main><a href="/in/body">b</a><a href="/">home</a></main><footer><a href="/f/y">f</a></footer>')
        self.assertEqual(extract_links(html,OWN),['https://www.seoul.go.kr/in/body'])
        other='https://www.seoul.go.kr/news/2'
        self.candidate_b={'source':'seoul','url':other,'title':'다른 프로그램','summary':'x','needs_recheck':True}
        self.pages={OWN:self.body('A <a href="https://news.seoul.go.kr/bad">bad</a> <a href="https://news.seoul.go.kr/good">g</a>'),
                    'https://news.seoul.go.kr/good':self.body('G other'),other:self.body('Second candidate')}
        from benefit_monitor.ai_review import review_candidates
        import urllib.error
        def transport(request):
            if request.full_url.endswith('/bad'):
                raise urllib.error.HTTPError(request.full_url,404,'nf',{},None)
            return self.transport(request)
        with patch('benefit_monitor.official_reader.network_open',side_effect=transport):
            result=review_candidates(self.root,[self.candidate,self.candidate_b],NOW,2,False)
        self.assertEqual(result['queued'],2)
        self.assertEqual([f['code'] for f in result['failures']],['related_fetch_failed'])
        self.assertEqual(result['failures'][0]['url'],'https://news.seoul.go.kr/bad')
        docs=[json.loads(f.read_text())['documents'] for f in (self.root/'.tools/ai-inputs').glob('*.json')]
        self.assertIn(2,[len(d) for d in docs])  # next link (good) was still tried

    def test_http_budget_exhaustion_keeps_original_only(self):
        self.pages={OWN:self.body('A <a href="https://news.seoul.go.kr/b">b</a>'),
                    'https://news.seoul.go.kr/b':self.body('B different')}
        result=self.run_review(limit=2)  # robots + original only
        self.assertEqual(len(self.staged()['documents']),1)
        self.assertGreaterEqual(len(result['failures']),1)
        self.assertEqual(result['queued'],1)


if __name__=='__main__':
    unittest.main()
