import concurrent.futures
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from benefit_monitor.trial_budget import TrialBudget
from benefit_monitor.claude_trial import ClaudeClient, load_key, TrialError, validate_host, repair_context, parse_draft, input_from_message

ROOT = Path(__file__).resolve().parents[1]

class ClaudeTrialTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tools').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'budget.json'
        self.budget = TrialBudget.initialize(self.path, 'claude-haiku-5-5', '0.10', '0.50')

    def test_reservation_survives_restart_and_cannot_reset(self):
        self.budget.reserve('a'*64, 9_000_000)
        with self.assertRaisesRegex(ValueError, 'monthly budget exhausted'):
            TrialBudget(self.path).reserve('b'*64, 6_000_001)
        self.assertEqual(TrialBudget(self.path).summary()['exposure_microdollars'], 9_000_000)
        with self.assertRaises(FileExistsError):
            TrialBudget.initialize(self.path, 'claude-haiku-5-5', '0.10', '0.50')

    def test_concurrent_reservations_do_not_overspend(self):
        def attempt(key):
            try:
                TrialBudget(self.path).reserve(key*64, 9_000_000)
                return True
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ['a', 'b']))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.budget.summary()['exposure_microdollars'], 9_000_000)

    def test_failure_keeps_reservation(self):
        self.budget.reserve('a'*64, 3_000_000)
        self.budget.fail('a'*64, 'http_500')
        self.assertEqual(self.budget.summary()['exposure_microdollars'], 3_000_000)
        self.assertEqual(self.budget.reserve('a'*64, 1)['status'], 'failed')

    def test_actual_usage_settles_and_overrun_halts(self):
        self.budget.reserve('a'*64, 1000)
        self.budget.settle('a'*64, 250, {'input_tokens':1000,'output_tokens':300}, 'b'*64)
        self.assertEqual(self.budget.summary()['exposure_microdollars'], 250)
        self.budget.reserve('c'*64, 10)
        self.budget.settle('c'*64, 11, {}, 'd'*64)
        with self.assertRaises(ValueError):
            self.budget.reserve('e'*64, 1)

    def test_corrupt_or_invalid_budget_fails_closed(self):
        self.path.write_text('{}')
        with self.assertRaises(ValueError):
            self.budget.summary()

    def test_no_request_count_limit_only_the_monthly_amount_binds(self):
        for i in range(250):
            self.budget.reserve(f'{i:064x}', 0)
        self.assertEqual(self.budget.summary()['request_count'], 250)

    def test_key_file_permissions_and_symlink_and_no_secret_error(self):
        p = self.root / '.env.claude'
        p.write_text('ANTHROPIC_API_KEY=fake-secret-for-tests\n')
        p.chmod(0o600)
        self.assertEqual(load_key(p), 'fake-secret-for-tests')
        p.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'permissions'):
            load_key(p)
        p.chmod(0o600)
        q = self.root / 'link';q.symlink_to(p)
        with self.assertRaises(ValueError):load_key(q)
        p.write_text('ANTHROPIC_API_KEY=bad key secret\n')
        with self.assertRaises(ValueError) as raised:load_key(p)
        self.assertNotIn('bad key secret', str(raised.exception))

    def client(self):
        return ClaudeClient(self.root, self.budget, 'fake-secret-for-tests')

    def response(self, body):
        return io.BytesIO(json.dumps(body).encode())

    def message(self, **changes):
        body = {'id':'msg_test','model':'claude-haiku-5-5','type':'message',
                'content':[{'type':'text','text':'{"ok":true}'}], 'stop_reason':'end_turn',
                'usage':{'input_tokens':1000,'output_tokens':300}}
        body.update(changes)
        return body

    def test_message_records_real_usage_and_reuses_identical_request(self):
        with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(self.message())):
            first = self.client().message('system', 'user', max_tokens=1000)
        self.assertEqual(first['content'][0]['text'], '{"ok":true}')
        self.assertEqual(self.budget.summary()['exposure_microdollars'], 250)
        with patch('benefit_monitor.claude_trial.network_open', side_effect=AssertionError('duplicate paid call')):
            self.assertEqual(self.client().message('system', 'user', max_tokens=1000), first)

    def test_missing_usage_holds_reservation_and_stops(self):
        with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(self.message(usage={}))):
            with self.assertRaises(TrialError):self.client().message('system', 'user')
        before = self.budget.summary()['exposure_microdollars']
        self.assertGreater(before, 0)
        with patch('benefit_monitor.claude_trial.network_open', side_effect=AssertionError('must not retry')):
            with self.assertRaises(TrialError):self.client().message('system', 'user')
        self.assertEqual(self.budget.summary()['exposure_microdollars'], before)

    def test_error_does_not_log_secret_or_retry(self):
        error = HTTPError('https://api.anthropic.com/v1/messages', 401, 'fake-secret-for-tests', {}, io.BytesIO(b'fake-secret-for-tests'))
        with patch('benefit_monitor.claude_trial.network_open', side_effect=error):
            with self.assertRaises(TrialError) as raised:self.client().message('system', 'user')
        self.assertNotIn('fake-secret-for-tests', str(raised.exception))
        self.assertNotIn('fake-secret-for-tests', self.path.read_text())
        self.assertGreater(self.budget.summary()['exposure_microdollars'], 0)
        self.assertTrue(error.fp.closed)

    def test_unexpected_cache_usage_and_oversized_input_rejected(self):
        usage={'input_tokens':100,'output_tokens':10,'cache_creation_input_tokens':100}
        with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(self.message(usage=usage))):
            with self.assertRaises(TrialError):self.client().message('system', 'user')
        with patch('benefit_monitor.claude_trial.network_open', side_effect=AssertionError('input too large')):
            with self.assertRaises(ValueError):self.client().message('s', '가'*100000)

    def test_invalid_usage_not_treated_as_free(self):
        for value in [True,-1,1.5,'100']:
            with self.subTest(value=value):
                self.budget = TrialBudget.initialize(self.root / ('usage-'+str(value)+'.json'), 'claude-haiku-5-5', '0.10', '0.50')
                with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(self.message(usage={'input_tokens':value,'output_tokens':10}))):
                    with self.assertRaises(TrialError):self.client().message('system', 'user'+str(value))

    def test_cached_response_missing_does_not_repeat_charge(self):
        with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(self.message())):
            self.client().message('s', 'u')
        for f in (self.root/'responses').glob('*.json'):f.unlink()
        with patch('benefit_monitor.claude_trial.network_open', side_effect=AssertionError('must not resend')):
            with self.assertRaises(TrialError):self.client().message('s', 'u')

    def test_interleaved_failure_halts_even_if_newer_request_settled(self):
        def fail(request):
            self.budget.reserve('b'*64, 0)
            self.budget.settle('b'*64, 0, {}, 'c'*64)
            raise TimeoutError('fake-secret-for-tests')
        with patch('benefit_monitor.claude_trial.network_open', side_effect=fail):
            with self.assertRaises(TrialError):self.client().message('s', 'u')
        self.assertTrue(self.budget.summary()['halted'])

    def test_response_echoing_secret_is_not_saved(self):
        with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(self.message(content=[{'type':'text','text':'fake-secret-for-tests'}]))):
            with self.assertRaises(TrialError):self.client().message('s', 'u')
        self.assertFalse(list((self.root/'responses').glob('*.json')))

    def host(self):
        import hashlib
        text = '예약 안내: 참가비 5000원. 대상 만19~39세.'
        url = 'https://yeyak.seoul.go.kr/web/main.do'
        doc = dict(id='doc-1',requested_url=url,final_url=url,source_id='culture',
                   publisher_type='issuer',document_role='notice',retrieved_at='2026-11-05T00:00:00+09:00',
                   published_at=None,body_hash=hashlib.sha256(text.encode()).hexdigest(),
                   hash_algorithm='sha256-utf8-exact',extraction_scope='test_public_body',fetch_status='ok',body=text,links=[])
        return dict(schema_version='research-input-v1',mode='api_agent',synthetic=False,
                    now='2026-11-05T01:00:00+09:00',output_schema_version='research-draft-v1',budget={},
                    candidates=[dict(candidate_id='candidate-1',source_id='culture',title='공식 안내',document_ids=['doc-1'],research_reason='missing_conditions')],documents=[doc])

    def test_host_is_checked_before_paid_request(self):
        host=self.host();validate_host(host,'research',ROOT)
        for field,value in [('mode','offline_fixture'),('synthetic',True)]:
            bad=json.loads(json.dumps(host));bad[field]=value
            with self.assertRaises(ValueError):validate_host(bad,'research',ROOT)
        for field,value in [('final_url','https://example.com/private'),('publisher_type','fixture'),('body_hash','a'*64)]:
            bad=json.loads(json.dumps(host));bad['documents'][0][field]=value
            with self.assertRaises(ValueError):validate_host(bad,'research',ROOT)
        bad=json.loads(json.dumps(host));bad['documents'][0]['body']='변조된 본문'
        with self.assertRaises(ValueError):validate_host(bad,'research',ROOT)

    def test_http_error_detail_redacts_key_and_preserves_reason(self):
        message={'error':{'type':'invalid_request_error','message':'unsupported temperature fake-secret-for-tests'}}
        error=HTTPError('https://api.anthropic.com/v1/messages',400,'bad',{},self.response(message))
        with patch('benefit_monitor.claude_trial.network_open',side_effect=error):
            with self.assertRaises(TrialError):self.client().message('s','u')
        row=self.budget.summary()['requests'][0]
        self.assertIn('unsupported temperature',row.get('error_detail',''))
        self.assertNotIn('fake-secret-for-tests',self.path.read_text())

    def test_manual_review_resume_never_refunds_or_resets(self):
        self.budget.reserve('a'*64,9_000_000);self.budget.fail('a'*64,'http_400')
        self.budget.resume_after_review()
        state=self.budget.summary()
        self.assertFalse(state['halted'])
        self.assertEqual(state['exposure_microdollars'],9_000_000)
        self.assertEqual(state['request_count'],1)
        with self.assertRaises(ValueError):self.budget.reserve('b'*64,6_000_001)

    def test_response_directory_cannot_escape_trial_root(self):
        outside=self.root/'other';outside.mkdir()
        local=self.root/'local';local.mkdir();(local/'responses').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):ClaudeClient(local,self.budget,'fake-secret-for-tests')

    def test_explicit_single_retry_keeps_failed_reservation(self):
        error=HTTPError('https://api.anthropic.com/v1/messages',400,'bad',{},io.BytesIO(b'{}'))
        with patch('benefit_monitor.claude_trial.network_open',side_effect=error):
            with self.assertRaises(TrialError):self.client().message('s','u')
        held=self.budget.summary()['exposure_microdollars']
        self.budget.resume_after_review()
        with patch('benefit_monitor.claude_trial.network_open',return_value=self.response(self.message())):
            self.client().message('s','u',retry_failed_once=True)
        self.assertEqual(self.budget.summary()['request_count'],2)
        self.assertEqual(self.budget.summary()['exposure_microdollars'],held+250)
        with patch('benefit_monitor.claude_trial.network_open',side_effect=AssertionError('must use retry cache')):
            self.client().message('s','u',retry_failed_once=True)

    def test_retry_without_failed_400_is_rejected_before_network(self):
        with patch('benefit_monitor.claude_trial.network_open',side_effect=AssertionError('not authorized retry')):
            with self.assertRaises(ValueError):self.client().message('s','u',retry_failed_once=True)
        self.assertEqual(self.budget.summary()['request_count'],0)

    def test_model_request_omits_deprecated_temperature(self):
        def provider(request):
            if 'temperature' in json.loads(request.data):
                body={'error':{'message':'temperature is deprecated'}}
                raise HTTPError(request.full_url,400,'bad',{},self.response(body))
            return self.response(self.message())
        with patch('benefit_monitor.claude_trial.network_open',side_effect=provider):
            result=self.client().message('s','u')
        self.assertEqual(result['stop_reason'],'end_turn')
        self.assertEqual(self.budget.summary()['confirmed_microdollars'],250)

    def test_extraction_request_disables_adaptive_thinking(self):
        def provider(request):
            if json.loads(request.data).get('thinking') != {'type':'disabled'}:
                return self.response(self.message(stop_reason='max_tokens',content=[{'type':'thinking','thinking':'internal'}]))
            return self.response(self.message())
        with patch('benefit_monitor.claude_trial.network_open',side_effect=provider):
            result=self.client().message('s','u')
        self.assertEqual(result['stop_reason'],'end_turn')
        self.assertEqual([x['type'] for x in result['content']],['text'])

    def test_repair_binds_same_input_and_allows_only_one_correction(self):
        import hashlib
        previous=self.root/'previous';previous.mkdir()
        host=self.host();digest=hashlib.sha256(json.dumps(host,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        (previous/'input.json').write_text(json.dumps(host))
        (previous/'metadata.json').write_text(json.dumps({'kind':'research','input_sha256':digest,'repair_of':None}))
        (previous/'validation.json').write_text(json.dumps({'valid':False,'errors':['quote not in successful source']}))
        (previous/'rejected-result.json').write_text(json.dumps({'records':[]}))
        result=repair_context(host,'research',previous)
        self.assertIn('validation_errors',result)
        changed=self.host();changed['now']='2026-11-06T01:00:00+09:00'
        with self.assertRaises(ValueError):repair_context(changed,'research',previous)
        (previous/'metadata.json').write_text(json.dumps({'kind':'research','input_sha256':digest,'repair_of':'a'*64}))
        with self.assertRaises(ValueError):repair_context(host,'research',previous)

    def test_request_identity_includes_generation_settings(self):
        with patch('benefit_monitor.claude_trial.network_open',return_value=self.response(self.message())):
            self.client().message('s','u')
        client=self.client()
        with patch('benefit_monitor.claude_trial.network_open',return_value=self.response(self.message())):
            client.message('s','u',max_tokens=1000)
        self.assertEqual(client.last_request_id,self.budget.summary()['requests'][-1]['id'])
        self.assertEqual(self.budget.summary()['request_count'],2)

    def test_auth_cache_does_not_authenticate_a_different_key(self):
        with patch('benefit_monitor.claude_trial.network_open',return_value=self.response({'data':[{'id':'claude-haiku-5-5'}]})):
            self.client().models()
        different=ClaudeClient(self.root,self.budget,'different-test-secret')
        error=HTTPError('https://api.anthropic.com/v1/models',401,'bad',{},io.BytesIO(b'{}'))
        with patch('benefit_monitor.claude_trial.network_open',side_effect=error):
            with self.assertRaises(TrialError):different.models()
        self.assertEqual(self.budget.summary()['request_count'],2)

    def test_json_transport_wrapper_preserves_object_without_accepting_prose(self):
        self.assertEqual(parse_draft('{"value":1}'),{'value':1})
        self.assertEqual(parse_draft('```json\n{"value":1}\n```'),{'value':1})
        for text in ['answer: {"value":1}','```json\n{"value":1}\n``` extra','{"value":1,"value":2}','{"value":NaN}','[]']:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):parse_draft(text)

    def test_cli_cannot_initialize_a_second_root_budget(self):
        import subprocess,sys
        (self.root/'sources.yaml').write_text('{}')
        proc=subprocess.run([sys.executable,'-m','benefit_monitor.claude_trial','init','--root',str(self.root)],capture_output=True,text=True,cwd=ROOT)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse((self.root/'.tools/claude-trial/live/budget.json').exists())

    def test_cli_run_checks_host_before_message(self):
        from benefit_monitor.claude_trial import main
        host_path=self.root/'invalid-host.json'
        host_path.write_text(json.dumps({'mode':'api_agent','synthetic':True}))
        with patch('sys.argv',['trial','run','--kind','research','--input',str(host_path)]), \
             patch('benefit_monitor.claude_trial.load_key',return_value='fake-secret-for-tests'), \
             patch('benefit_monitor.claude_trial.ClaudeClient') as client:
            with self.assertRaisesRegex(ValueError,'non-fixture'):
                main()
            client.return_value.message.assert_not_called()

    def test_topic_input_rejects_private_fields_and_kst_expiry(self):
        review=json.loads((ROOT/'docs/ai/evaluations/phase234-2026-11-05/human-final-review-result.json').read_text())
        host={'mode':'api_agent','synthetic':False,'now':'2026-11-10T14:59:00+00:00','evaluation_only':True,'source_review_id':review['review_id'],
              'approved_items':[{'item_id':'shopping-05','display_eligible':True,'valid_until':'2026-11-10'}]}
        validate_host(host,'topic',ROOT)
        bad=json.loads(json.dumps(host));bad['user_profile']={'age':30}
        with self.assertRaises(ValueError):validate_host(bad,'topic',ROOT)
        host['now']='2026-11-10T15:00:00+00:00'
        with self.assertRaises(ValueError):validate_host(host,'topic',ROOT)

    def test_key_in_prompt_is_rejected_before_reservation(self):
        with patch('benefit_monitor.claude_trial.network_open',side_effect=AssertionError('secret must not be sent as content')):
            with self.assertRaises(ValueError):self.client().message('s','fake-secret-for-tests')
        self.assertEqual(self.budget.summary()['request_count'],0)

    def test_unexpected_premium_usage_is_held_not_mispriced(self):
        usage={'input_tokens':100,'output_tokens':20,'service_tier':'priority','speed':'fast'}
        with patch('benefit_monitor.claude_trial.network_open',return_value=self.response(self.message(usage=usage))):
            with self.assertRaises(TrialError):self.client().message('s','u')
        state=self.budget.summary()
        self.assertTrue(state['halted'])
        self.assertEqual(state['confirmed_microdollars'],0)
        self.assertGreater(state['exposure_microdollars'],0)

    def test_grammar_probe_rejection_is_recorded_once_without_halting(self):
        from benefit_monitor.wire_format import research_wire_schema
        body={'type':'error','error':{'type':'invalid_request_error','message':'The compiled grammar is too large'}}
        calls=[]
        def reject(request):
            calls.append(json.loads(request.data))
            raise HTTPError(request.full_url,400,'bad',{},self.response(body))
        with patch('benefit_monitor.claude_trial.network_open',side_effect=reject):
            first=self.client().grammar_probe(research_wire_schema())
            second=self.client().grammar_probe(research_wire_schema())
        self.assertEqual((first['status'],first['cached'],second['status'],second['cached']),('rejected',False,'rejected',True))
        self.assertEqual(len(calls),1);self.assertEqual(calls[0]['max_tokens'],16)
        state=self.budget.summary()
        self.assertFalse(state['halted']);self.assertEqual(state['request_count'],1)
        self.assertEqual((state['requests'][0]['status'],state['requests'][0]['error_code']),('failed','http_400'))
        self.assertIn('grammar',first['detail'])

    def test_grammar_probe_pass_is_cached_and_server_errors_still_halt(self):
        from benefit_monitor.wire_format import research_wire_schema
        reply=self.message(content=[{'type':'text','text':'{"w'}],stop_reason='max_tokens',usage={'input_tokens':700,'output_tokens':16})
        with patch('benefit_monitor.claude_trial.network_open',return_value=self.response(reply)) as net:
            self.assertEqual(self.client().grammar_probe(research_wire_schema())['status'],'passed')
            self.assertTrue(self.client().grammar_probe(research_wire_schema())['cached'])
        self.assertEqual(net.call_count,1)
        other={'type':'object','properties':{'a':{'type':'string'}},'required':['a'],'additionalProperties':False}
        def overloaded(request):raise HTTPError(request.full_url,529,'busy',{},self.response({}))
        with patch('benefit_monitor.claude_trial.network_open',side_effect=overloaded),self.assertRaises(TrialError):
            self.client().grammar_probe(other)
        self.assertTrue(self.budget.summary()['halted'])

    def test_cli_structured_wire_response_is_assembled_without_real_network(self):
        import hashlib,shutil
        from contextlib import redirect_stdout
        from benefit_monitor.claude_trial import main
        from benefit_monitor.wire_format import RESEARCH_WIRE, FIELDS, limits
        root=self.root
        (root/'docs/ai/prompts').mkdir(parents=True)
        for name in ('research-system.md','topic-system.md'):
            shutil.copy(ROOT/'docs/ai/prompts'/name,root/'docs/ai/prompts'/name)
        (root/'sources.yaml').write_text(json.dumps({'sources':[{'id':'seoul','domains':['www.seoul.go.kr']}]}))
        live=root/'.tools/claude-trial/live'
        TrialBudget.initialize(live/'budget.json','claude-haiku-5-5','0.10','0.50')
        body='공식 원문 테스트. 관람료는 무료입니다.'
        doc=dict(id='doc',source_id='seoul',requested_url='https://www.seoul.go.kr/example',final_url='https://www.seoul.go.kr/example',
                 publisher_type='issuer',document_role='notice',retrieved_at='2026-11-05T12:00:00+09:00',published_at=None,
                 body_hash=hashlib.sha256(body.encode()).hexdigest(),hash_algorithm='sha256-utf8-exact',extraction_scope='test',fetch_status='ok',body=body)
        host=dict(mode='api_agent',synthetic=False,now='2026-11-05T12:00:00+09:00',output_schema_version='research-draft-v1',budget={},
                  candidates=[dict(candidate_id='candidate',source_id='seoul',document_ids=['doc'])],documents=[doc])
        path=root/'input.json';path.write_text(json.dumps(host))
        blank=dict(text='',items=[],not_confirmed=[],start='',end='',number=0,segment_ids=[])
        facts=[dict(blank,field=field,status='unknown',unknown_reason='조건 미확인') for field in FIELDS]
        facts[FIELDS.index('fee_status')]=dict(blank,field='fee_status',status='supported',text='free',segment_ids=['d1s2'],unknown_reason='')
        wire=dict(wire_version=RESEARCH_WIRE,status='completed',errors=[],records=[dict(candidate_id='candidate',research_status='completed',
                  stop_reason='sufficient_evidence',facts=facts)])
        response=self.message(content=[{'type':'text','text':json.dumps(wire,ensure_ascii=False)}])
        output=io.StringIO()
        sent=[];urls=[]
        def transport(request):
            urls.append(request.full_url)
            sent.append(json.loads(request.data))
            if request.full_url.endswith('/count_tokens'):
                self.assertEqual(TrialBudget(live/'budget.json').summary()['request_count'],1)
                return self.response({'input_tokens':812})
            if sent[-1]['max_tokens']==16:
                return self.response(self.message(content=[{'type':'text','text':'{"wire'}],stop_reason='max_tokens',
                                                  usage={'input_tokens':900,'output_tokens':16}))
            return self.response(response)
        with patch('sys.argv',['trial','run','--root',str(root),'--kind','research','--input',str(path)]), \
             patch('benefit_monitor.claude_trial.__file__',str(root/'benefit_monitor/claude_trial.py')), \
             patch('benefit_monitor.claude_trial.load_key',return_value='fake-secret-for-tests'), \
             patch('benefit_monitor.claude_trial.network_open',side_effect=transport),redirect_stdout(output):
            self.assertEqual(main(),0)
        self.assertEqual(urls,['https://api.anthropic.com/v1/messages','https://api.anthropic.com/v1/messages/count_tokens',
                               'https://api.anthropic.com/v1/messages'])
        self.assertEqual((sent[0]['max_tokens'],sent[0]['messages'][0]['content']),(16,'probe'))
        self.assertNotIn('max_tokens',sent[1])
        self.assertEqual(sent[0]['output_config'],sent[2]['output_config'])
        self.assertEqual(sent[1]['output_config'],sent[2]['output_config'])
        self.assertEqual(json.loads((live/'grammar-probes.json').read_text()).popitem()[1]['status'],'passed')
        request=sent[2]
        self.assertIn('research-system-v1',request['system'])
        self.assertNotIn('Phase',request['system'])
        schema=request['output_config']['format']['schema']
        self.assertEqual(request['output_config']['format']['type'],'json_schema')
        self.assertLessEqual(limits(schema)['unions'],16)
        sent_doc=input_from_message(request['messages'][0]['content'])['documents'][0]
        self.assertNotIn('body',sent_doc)
        self.assertEqual([x['text'] for x in sent_doc['segments']],['공식 원문 테스트.','관람료는 무료입니다.'])
        status=json.loads(output.getvalue())
        self.assertFalse(status['publication_approved'])
        result=json.loads((Path(status['output'])/'result.json').read_text())
        claim=next(c for c in result['records'][0]['claims'] if c['field']=='fee_status')
        self.assertEqual(claim['evidence'][0]['quote'],'관람료는 무료입니다.')
        self.assertEqual(result['records'][0]['sources'][0]['body_hash'],doc['body_hash'])
        self.assertRegex(result['records'][0]['claims'][0]['id'],r'^claim-[0-9a-f]{24}$')
        self.assertEqual(TrialBudget(live/'budget.json').summary()['request_count'],2)  # grammar probe + real request
        metadata=json.loads((Path(status['output'])/'metadata.json').read_text())
        self.assertEqual(metadata['preflight']['input_tokens'],812)
        self.assertFalse(metadata['preflight']['billed'])

    def test_rejection_names_the_host_rule(self):
        from benefit_monitor.claude_trial import rejection
        failure=rejection({'stop_reason':'end_turn','content':[{'type':'text','text':'{}'}]},ValueError('invalid period format'))
        self.assertEqual(failure,{'valid':False,'error':'invalid_or_truncated_model_output','detail':'invalid period format',
                                  'stop_reason':'end_turn','content_types':['text']})

    def test_cli_verify_response_is_validated_without_real_network(self):
        import hashlib,shutil
        from contextlib import redirect_stdout
        from benefit_monitor.claude_trial import main
        root=self.root
        (root/'docs/ai/prompts').mkdir(parents=True)
        shutil.copy(ROOT/'docs/ai/prompts/verify-system.md',root/'docs/ai/prompts/verify-system.md')
        (root/'sources.yaml').write_text(json.dumps({'sources':[{'id':'emart24','domains':['emart24.co.kr']}]}))
        live=root/'.tools/claude-trial/live'
        TrialBudget.initialize(live/'budget.json','claude-haiku-5-5','0.10','0.50')
        body='KT멤버십 안내.\nGOLD / SILVER 1,000원당 50원 차감 할인.'
        doc=dict(id='doc',source_id='emart24',requested_url='https://emart24.co.kr/service/alliance',final_url='https://emart24.co.kr/service/alliance',
                 publisher_type='unknown',document_role='notice',retrieved_at='2026-11-05T12:00:00+09:00',published_at=None,
                 body_hash=hashlib.sha256(body.encode()).hexdigest(),hash_algorithm='sha256-utf8-exact',extraction_scope='test',fetch_status='ok',body=body)
        host=dict(schema_version='verify-input-v1',mode='api_agent',synthetic=False,now='2026-11-05T12:00:00+09:00',purpose='audit',
                  item=dict(item_id='a'*24,source_id='emart24',title='제휴',claims=[dict(claim_id='c1',field='conditions',text='GOLD는 1천 원당 100원')]),
                  documents=[doc])
        path=root/'input.json';path.write_text(json.dumps(host,ensure_ascii=False))
        wire=dict(wire_version='verify-wire-v1',item_status='ongoing',status_segment_ids=['d1s2'],
                  claims=[dict(claim_id='c1',verdict='contradicted',segment_ids=['d1s2'],official_text='GOLD 50원')])
        response=self.message(content=[{'type':'text','text':json.dumps(wire,ensure_ascii=False)}])
        sent=[]
        def transport(request):
            sent.append(json.loads(request.data))
            if request.full_url.endswith('/count_tokens'):return self.response({'input_tokens':500})
            if sent[-1]['max_tokens']==16:
                return self.response(self.message(content=[{'type':'text','text':'{"wire'}],stop_reason='max_tokens',
                                                  usage={'input_tokens':900,'output_tokens':16}))
            return self.response(response)
        output=io.StringIO()
        with patch('sys.argv',['trial','run','--root',str(root),'--kind','verify','--input',str(path)]), \
             patch('benefit_monitor.claude_trial.__file__',str(root/'benefit_monitor/claude_trial.py')), \
             patch('benefit_monitor.claude_trial.load_key',return_value='fake-secret-for-tests'), \
             patch('benefit_monitor.claude_trial.network_open',side_effect=transport),redirect_stdout(output):
            self.assertEqual(main(),0)
        sent_doc=input_from_message(sent[2]['messages'][0]['content'])['documents'][0]
        self.assertNotIn('body',sent_doc)
        self.assertIn('품질 검증자',sent[2]['system'])
        status=json.loads(output.getvalue())
        self.assertEqual(status['status'],'validated_draft')
        result=json.loads((Path(status['output'])/'result.json').read_text())
        self.assertEqual(result['claims'][0]['quotes'],['GOLD / SILVER 1,000원당 50원 차감 할인.'])
        self.assertEqual(json.loads((Path(status['output'])/'metadata.json').read_text())['model_output_contract'],'verify-wire-v1')

    def test_preflight_rejection_stops_before_reservation(self):
        client=ClaudeClient(self.root,self.budget,'fake-secret-for-tests')
        error=HTTPError('https://api.anthropic.com/v1/messages/count_tokens',400,'bad',{},
                        io.BytesIO(b'{"error":{"message":"output_config: Extra inputs are not permitted fake-secret-for-tests"}}'))
        with patch('benefit_monitor.claude_trial.network_open',side_effect=error):
            with self.assertRaisesRegex(TrialError,'preflight rejected before reservation: http_400'):
                client.message('s','u',output_schema={'type':'object','properties':{},'required':[],'additionalProperties':False},preflight=True)
        summary=self.budget.summary()
        self.assertEqual((summary['request_count'],summary['exposure_microdollars']),(0,0))
        failures=json.loads((self.root/'preflight-failures.json').read_text())
        self.assertEqual(failures[-1]['code'],'http_400')
        self.assertNotIn('fake-secret-for-tests',json.dumps(failures))
        with patch('benefit_monitor.claude_trial.network_open',side_effect=OSError('down')):
            with self.assertRaisesRegex(TrialError,'no request reserved'):
                client.message('s','u',preflight=True)
        self.assertEqual(self.budget.summary()['request_count'],0)

    def test_preflight_rejects_odd_token_count(self):
        client=ClaudeClient(self.root,self.budget,'fake-secret-for-tests')
        for body in ({'input_tokens':0},{'input_tokens':'12'},{'tokens':12}):
            with patch('benefit_monitor.claude_trial.network_open',return_value=self.response(body)):
                with self.assertRaises(TrialError):
                    client.message('s','u',preflight=True)
        self.assertEqual(self.budget.summary()['request_count'],0)

    def test_trial_consumer_blocks_structurally_valid_topic_without_basis(self):
        from benefit_monitor.claude_trial import evaluate_draft
        host=json.loads((ROOT/'docs/ai/examples/topic-input.json').read_text())
        draft=json.loads((ROOT/'docs/ai/evaluations/v2/topic-result.json').read_text())
        _,report=evaluate_draft(draft,host,'topic')
        self.assertFalse(report['valid'])
        self.assertTrue(report['structural_valid'])
        self.assertIn('missing_topic_basis',[f['code'] for f in report['semantic_review']['findings']])


    def test_cli_missing_topic_basis_stops_before_reservation(self):
        from benefit_monitor.claude_trial import main
        review=json.loads((ROOT/'docs/ai/evaluations/phase234-2026-11-05/human-final-review-result.json').read_text())
        host=dict(mode='api_agent',synthetic=False,evaluation_only=True,now='2026-11-05T12:00:00+09:00',source_review_id=review['review_id'],
                  approved_items=[dict(item_id='culture-01',claim_ids=['c'],display_eligible=True)],approved_claims=[dict(id='c',item_id='culture-01')])
        path=self.root/'missing-basis.json';path.write_text(json.dumps(host))
        with patch('sys.argv',['trial','run','--kind','topic','--input',str(path)]), \
             patch('benefit_monitor.claude_trial.TrialBudget',return_value=self.budget), \
             patch('benefit_monitor.claude_trial.ClaudeClient',side_effect=lambda _,budget,key: ClaudeClient(self.root/'live',budget,key)), \
             patch('benefit_monitor.claude_trial.load_key',return_value='fake-secret-for-tests'), \
             patch('benefit_monitor.claude_trial.network_open',side_effect=AssertionError('preflight must precede transport')):
            with self.assertRaisesRegex(ValueError,'topic basis'):
                main()
        self.assertEqual(self.budget.summary()['request_count'],0)

    def test_topic_wire_keeps_all_items_conditions_and_separate_payment_terms(self):
        from copy import deepcopy
        from benefit_monitor.claude_trial import topic_model_input
        item={'item_id':'a','summary':'서울 문화 체험','conditions':'19~39세, 공휴일 제외',
              'deadline_at':'2026-11-09T17:00:00+09:00','claim_ids':['ca'],'topic_basis':{'topic_ids':['culture']}}
        value={'summary':item['summary'],'conditions':item['conditions'],'title':'중복 메타데이터',
               'fee_status':'paid','payment_terms':{'minimum_spend':'10000원'},'benefit_value':{'conditions':'앱 결제 한정'}}
        host={'approved_items':[item],'approved_claims':[{'id':'ca','item_id':'a','field':'public_release_facts','value':value}]}
        original=deepcopy(host);wire=topic_model_input(host)
        self.assertEqual(wire['approved_items'],host['approved_items'])
        self.assertEqual(wire['approved_claims'][0]['id'],'ca')
        self.assertEqual(wire['approved_claims'][0]['value']['payment_terms'],value['payment_terms'])
        self.assertEqual(wire['approved_claims'][0]['value']['benefit_value'],value['benefit_value'])
        self.assertEqual(wire['approved_claims'][0]['value']['fee_status'],'paid')
        self.assertNotIn('title',wire['approved_claims'][0]['value'])
        self.assertEqual(host,original)

if __name__=='__main__':unittest.main()
