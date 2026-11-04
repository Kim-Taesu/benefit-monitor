import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from unittest.mock import patch
from benefit_monitor.collectors.html import ArticleLinks, collect
from benefit_monitor.publish import coverage
from benefit_monitor.store import save

class CoreSourcesTests(unittest.TestCase):
    def test_missing_robots_404_allows_public_links_but_server_error_does_not(self):
        source=dict(id='cu',html_url='https://official.example/',domains=['official.example'],article_path_pattern='/offer',keywords=['할인'])
        for code in (404,403,503):
            with self.subTest(code=code), patch('benefit_monitor.collectors.html.fetch',side_effect=[HTTPError('https://official.example/robots.txt',code,'error',{},None),'<a href="/offer">할인</a>'.encode()]):
                if code==404:
                    result=collect(source)
                    self.assertEqual(result[0]['url'],'https://official.example/offer')
                    self.assertTrue(result[0]['needs_recheck'])
                else:
                    with self.assertRaises(HTTPError):collect(source)

    def test_image_link_title_and_newsroom_title_do_not_include_unrelated_excerpt(self):
        p=ArticleLinks('https://official.example/',['official.example'],r'/[a-z]+', ['할인'])
        p.feed('<a href="/image" title="제휴 할인"><img alt="관리자 이미지"></a><a href="/news"><div class="title">기업 경영</div><div>할인 배경 설명</div></a>')
        self.assertEqual(p.items,{'https://official.example/image':'제휴 할인'})

    def test_district_source_uses_actual_coverage_and_shared_verified_items(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            root=Path(d);save(root/'districts.json',dict(districts=[]))
            config=dict(sources=[dict(id='gangseo',name='강서구',district_feed='강서구',collection_scope='서울시 자치구 뉴스')])
            items=[dict(source='seoul',districts=['강서구'])]
            for status,mode,want in [('checked','live','checked'),('checked','cached','cached'),('failed','live','failed')]:
                report=dict(district_coverage=[dict(district='강서구',status=status,mode=mode)],collection={})
                result=coverage(root,config,report,items)['sources'][0]
                self.assertEqual(result['status'],want)
                self.assertEqual(result['verified_count'],1)
                self.assertEqual(result['scope'],'서울시 자치구 뉴스')
            self.assertEqual(coverage(root,config,{},items)['sources'][0]['status'],'not_checked')

    def test_district_connection_reuses_collected_items_without_duplicates(self):
        from benefit_monitor.cli import run
        from test_pipeline import NOW
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as d:
            root=Path(d)
            seoul=dict(id='seoul',domains=['mediahub.seoul.go.kr'],routes=['https://mediahub.seoul.go.kr/'])
            district=dict(id='gangseo',domains=['mediahub.seoul.go.kr'],routes=['https://mediahub.seoul.go.kr/'],district_feed='강서구')
            save(root/'sources.yaml',dict(sources=[seoul,district],seoul_district_coverage=True))
            candidate=dict(source='seoul',url='https://mediahub.seoul.go.kr/archives/1',title='무료 전시',summary='확인 필요',districts=['강서구'])
            for state in ('checked','failed'):
                rows=[dict(district='강서구',status=state,mode='live')]
                with patch('benefit_monitor.cli.collect_districts',return_value=([candidate],rows)):
                    report=run(root,online=True,now=NOW)
                self.assertEqual('gangseo' in report['collection']['successful_sources'],state=='checked')
                self.assertEqual(len(report['needs_recheck']),1)

    def test_same_document_fragment_is_not_a_second_candidate(self):
        p=ArticleLinks('https://official.example/offer',['official.example'],r'/offer',['제휴'])
        p.feed('<a href="/offer">제휴 멤버십</a><a href="#none">제휴 문의</a>')
        self.assertEqual(p.items,{'https://official.example/offer':'제휴 멤버십'})
