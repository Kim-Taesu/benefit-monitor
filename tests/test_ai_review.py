import io
import json
from pathlib import Path
import tempfile
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
import unittest
from unittest.mock import patch

from benefit_monitor import cost_policy

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,11,5,12,tzinfo=ZoneInfo('Asia/Seoul'))

class Response(io.BytesIO):
    headers={'Content-Type':'text/html; charset=utf-8'}


class AIReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config={'sources':[{'id':'seoul','domains':['www.seoul.go.kr'],'routes':[],'feed_url':None}]}
        (self.root/'sources.yaml').write_text(json.dumps(self.config))
        self.candidate={'source':'seoul','url':'https://www.seoul.go.kr/news/1','title':'공식 프로그램','summary':'검토 대기','needs_recheck':True}
        for name in ('README.md','research.md','research-extraction.md','schemas/research-extraction-v3.schema.json'):
            path=self.root/'docs/ai'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('테스트용 지침')
        self.requests=[]
        self.page=b'<html><main>Program application and verified official details for a public benefit. Full conditions and deadlines require manual review.</main></html>'
        cost_policy.reset(60)

    def transport(self,request):
        self.requests.append(request.full_url)
        return Response(b'User-agent: *\nAllow: /' if request.full_url.endswith('/robots.txt') else self.page)

    def run_review(self,execute=True,now=NOW):
        from benefit_monitor.ai_review import review_candidates
        return review_candidates(self.root,[self.candidate],now,2,execute)

    def test_collection_body_to_model_to_private_review_and_unchanged_skip(self):
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport),patch('benefit_monitor.ai_review.invoke',return_value={'status':'validated_draft','run_id':'a'*64}):
            first=self.run_review();second=self.run_review()
        self.assertEqual(first['queued'],1)
        self.assertEqual(second['skipped_unchanged'],1)
        self.assertEqual(cost_policy.budget.used,2)
        queued=list((self.root/'cache/ai_review/queue').glob('*.json'))
        self.assertEqual(len(queued),1)
        value=json.loads(queued[0].read_text())
        self.assertFalse(value['publication_approved'])
        self.assertEqual(value['review_status'],'pending_human_review')
        self.assertEqual(value['model_status'],'validated_draft')
        self.assertFalse((self.root/'public/verified.json').exists())

    def test_rejected_model_is_queued_and_not_automatically_retried(self):
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport),patch('benefit_monitor.ai_review.invoke',return_value={'status':'rejected_draft','run_id':'b'*64}):
            first=self.run_review();second=self.run_review()
        self.assertEqual(first['rejected'],1)
        self.assertEqual(second['skipped_unchanged'],1)
        entry=json.loads(next((self.root/'cache/ai_review/queue').glob('*.json')).read_text())
        self.assertEqual(entry['model_status'],'rejected_draft')

    def test_no_spend_default_stages_input_then_explicit_execution_works(self):
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport),patch('benefit_monitor.ai_review.invoke',side_effect=AssertionError('no spend')):
            staged=self.run_review(execute=False)
        self.assertEqual(staged['awaiting_api'],1)
        with patch('benefit_monitor.ai_review.invoke',return_value={'status':'rejected_draft','run_id':'c'*64}):
            result=self.run_review(execute=True)
        self.assertEqual(result['rejected'],1)

    def test_changed_body_creates_new_review_and_source_cooldown_survives_restart(self):
        from benefit_monitor.official_reader import OfficialReader
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport),patch('benefit_monitor.ai_review.invoke',return_value={'status':'rejected_draft','run_id':'d'*64}):
            self.run_review()
            self.page=b'<html><main>Changed benefit with new eligibility and new application deadline. The official terms also explain costs and cancellation conditions.</main></html>'
            later=self.run_review(now=NOW+timedelta(hours=7))
        self.assertEqual(len(later['changed_ids']),1)
        self.assertEqual(len(list((self.root/'cache/ai_review/queue').glob('*.json'))),2)
        cost_policy.reset(60)
        with patch('benefit_monitor.official_reader.network_open',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):OfficialReader(self.root,NOW+timedelta(hours=14)).read(self.candidate)
        used=cost_policy.budget.used
        with patch('benefit_monitor.official_reader.network_open',side_effect=AssertionError('cooldown')):
            with self.assertRaisesRegex(ValueError,'cooldown'):OfficialReader(self.root,NOW+timedelta(hours=14,minutes=1)).read(self.candidate)
        self.assertEqual(cost_policy.budget.used,used)

    def test_robots_and_budget_cannot_be_bypassed(self):
        from benefit_monitor.official_reader import OfficialReader
        cost_policy.reset(1)
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport):
            with self.assertRaises(RuntimeError):OfficialReader(self.root,NOW).read(self.candidate)
        self.assertEqual(cost_policy.budget.used,1)
        other=self.root/'other';other.mkdir();(other/'sources.yaml').write_text(json.dumps(self.config))
        cost_policy.reset(60)
        with patch('benefit_monitor.official_reader.network_open',return_value=Response(b'User-agent: *\nDisallow: /')):
            with self.assertRaisesRegex(ValueError,'robots'):OfficialReader(other,NOW).read(self.candidate)
        self.assertEqual(cost_policy.budget.used,1)

    def test_existing_collection_cli_opt_in_shares_budget_and_default_stays_free(self):
        from benefit_monitor.cli import run
        path=self.root/'incoming.json';path.write_text(json.dumps([self.candidate]))
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport),patch('benefit_monitor.ai_review.invoke',side_effect=AssertionError('no API grant')):
            report=run(self.root,path,online=True,now=NOW,ai_review=True,ai_execute=False)
        self.assertEqual(report['ai_review']['awaiting_api'],1)
        self.assertEqual(report['cost_policy']['public_http_requests'],2)
        with patch('benefit_monitor.official_reader.network_open',side_effect=AssertionError('default is offline')):
            normal=run(self.root,path,now=NOW)
        self.assertNotIn('ai_review',normal)

    def test_image_only_event_sources_never_reach_paid_research(self):
        from benefit_monitor.cli import run
        self.config['sources'][0]['ai_review']=False
        (self.root/'sources.yaml').write_text(json.dumps(self.config))
        path=self.root/'incoming.json';path.write_text(json.dumps([self.candidate]))
        with patch('benefit_monitor.official_reader.network_open',side_effect=AssertionError('no body read')),patch('benefit_monitor.ai_review.invoke',side_effect=AssertionError('no model call')):
            report=run(self.root,path,online=True,now=NOW,ai_review=True,ai_execute=True)
        self.assertEqual(report['ai_review']['awaiting_api']+report['ai_review']['queued'],0)
        self.assertEqual(report['ai_review']['rows'],[])

    def test_ai_body_change_holds_previously_approved_facts(self):
        from benefit_monitor.cli import run
        approved=dict(self.candidate,needs_recheck=False,verified_at=NOW.isoformat(),valid_until='2026-11-30',evidence='테스트 승인 근거')
        path=self.root/'incoming.json';path.write_text(json.dumps([approved]))
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport):
            run(self.root,path,online=True,now=NOW,ai_review=True)
            self.page=b'<html><main>Changed conditions and new eligibility require human review before release. All previous terms must be rechecked.</main></html>'
            report=run(self.root,path,online=True,now=NOW+timedelta(hours=7),ai_review=True)
        self.assertEqual(len(report['needs_recheck']),1)
        self.assertTrue(report['needs_recheck'][0]['needs_recheck'])
        self.assertEqual(report['review_queue'][0]['reason'],'body_changed')

    def test_interrupted_review_reuses_identical_input_instead_of_new_timestamp(self):
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport),patch('benefit_monitor.ai_review.invoke',side_effect=SystemExit('interrupted')):
            with self.assertRaises(SystemExit):self.run_review()
        path=next((self.root/'.tools/ai-inputs').glob('*.json'));before=path.read_bytes()
        with patch('benefit_monitor.ai_review.invoke',return_value={'status':'rejected_draft','run_id':'e'*64}):
            self.run_review(now=NOW+timedelta(hours=1))
        self.assertEqual(path.read_bytes(),before)

    def test_identical_body_at_distinct_urls_keeps_source_metadata_separate(self):
        from benefit_monitor.official_reader import OfficialReader
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport):
            first=OfficialReader(self.root,NOW).read(self.candidate)
            other=OfficialReader(self.root,NOW).read(dict(self.candidate,url='https://www.seoul.go.kr/news/2'))
            again=OfficialReader(self.root,NOW).read(self.candidate)
        self.assertEqual(first['final_url'],again['final_url'])
        self.assertNotEqual(first['final_url'],other['final_url'])

    def test_nested_runtime_uses_the_single_repository_api_ledger(self):
        from types import SimpleNamespace
        from benefit_monitor.ai_review import invoke
        observed=[]
        def process(args,**kwargs):
            observed.append((args,kwargs['cwd']))
            return SimpleNamespace(stdout=json.dumps({'status':'rejected_draft','run_id':'a'*64}))
        path=self.root/'staged.json';path.write_text('{}')
        with patch('benefit_monitor.ai_review.subprocess.run',side_effect=process):
            result=invoke(self.root,'research',path)
        self.assertEqual(result['status'],'rejected_draft')
        self.assertEqual(observed[0][0][observed[0][0].index('--root')+1],str(ROOT))
        self.assertEqual(Path(observed[0][1]),ROOT)

    def test_small_daily_limit_rotates_candidates_instead_of_starving_the_rest(self):
        from benefit_monitor.ai_review import review_candidates
        candidates=[self.candidate,dict(self.candidate,url='https://www.seoul.go.kr/news/2')]
        with patch('benefit_monitor.official_reader.network_open',side_effect=self.transport),patch('benefit_monitor.ai_review.invoke',return_value={'status':'rejected_draft','run_id':'f'*64}):
            first=review_candidates(self.root,candidates,NOW,1,True)
            second=review_candidates(self.root,candidates,NOW+timedelta(minutes=1),1,True)
        self.assertEqual(second['queued'],1)
        self.assertNotEqual(first['rows'][0]['candidate_id'],second['rows'][0]['candidate_id'])

    def test_runtime_paths_cannot_escape_the_current_repository(self):
        from benefit_monitor.official_reader import project_path
        with self.assertRaises(ValueError):project_path(ROOT.parent,'cache/ai_review/state.json')
        with self.assertRaises(ValueError):project_path(ROOT,'../outside.json')

    def test_runtime_fingerprint_tracks_the_actual_single_model_prompt(self):
        from benefit_monitor.ai_review import fingerprint
        self.assertEqual(fingerprint(self.root),fingerprint(ROOT))

    def test_http_error_stream_is_closed_before_persisted_cooldown(self):
        from urllib.error import HTTPError
        from benefit_monitor.official_reader import OfficialReader
        stream=io.BytesIO(b'denied')
        error=HTTPError(self.candidate['url'],403,'denied',{},stream)
        with patch('benefit_monitor.official_reader.network_open',side_effect=[Response(b'User-agent: *\nAllow: /'),error]):
            with self.assertRaises(HTTPError):OfficialReader(self.root,NOW).read(self.candidate)
        self.assertTrue(stream.closed)

    def test_collection_reserves_shared_http_budget_for_ai_body_review(self):
        from benefit_monitor.cli import run
        config=dict(self.config,max_http_requests=6)
        config['sources']=[dict(config['sources'][0],feed_url='https://www.seoul.go.kr/feed')]
        (self.root/'sources.yaml').write_text(json.dumps(config))
        def greedy(source):
            while cost_policy.budget.used<cost_policy.budget.limit:cost_policy.budget.consume()
            return [self.candidate]
        with patch('benefit_monitor.cli.collect',side_effect=greedy),patch('benefit_monitor.official_reader.network_open',side_effect=self.transport):
            report=run(self.root,online=True,now=NOW,ai_review=True,ai_execute=False,ai_max_candidates=1)
        self.assertEqual(report['ai_review']['awaiting_api'],1)
        self.assertEqual(report['cost_policy']['public_http_requests'],6)
        self.assertEqual(report['cost_policy']['request_limit'],6)


if __name__=='__main__':unittest.main()
