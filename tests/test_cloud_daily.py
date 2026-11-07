"""Cloud admission checks must stop before collection or provider requests."""
import hashlib
import importlib
import json
import os
from datetime import datetime
from unittest.mock import patch
import unittest

import test_cloud_state as state_fixture
from benefit_monitor.store import load

KEY='fixture-anthropic-key-123456'
ENV={'BENEFIT_AI_CLOUD':'1','GITHUB_ACTIONS':'true','GITHUB_REPOSITORY':'Kim-Taesu/benefit-monitor',
     'GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/main','ANTHROPIC_API_KEY':KEY,'GH_TOKEN':'fixture-token','GITHUB_SHA':'a'*40}
NOW=datetime.fromisoformat('2026-11-06T06:05:00+09:00')

class CloudDailyTests(unittest.TestCase):
    def setUp(self):
        self.fixture=state_fixture.CloudStateTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root=self.fixture.root
        self.fixture.control['api_key_sha256']=hashlib.sha256(KEY.encode()).hexdigest()
        self.fixture.session()
        self.public_restore=patch('benefit_monitor.cloud_daily.restore_public')
        self.public_restore.start();self.addCleanup(self.public_restore.stop)
        self.env=patch.dict(os.environ,ENV,clear=True);self.env.start();self.addCleanup(self.env.stop)

    def module(self):
        try:return importlib.import_module('benefit_monitor.cloud_daily')
        except ModuleNotFoundError:self.fail('cloud 일일 제어가 아직 구현되지 않음')

    def test_cloud_key_is_explicit_and_trusted(self):
        from benefit_monitor import claude_trial
        self.assertTrue(hasattr(claude_trial,'configured_key'),'명시적 cloud key loader 필요')
        self.assertEqual(claude_trial.configured_key(self.root),KEY)
        for field,value in [('GITHUB_EVENT_NAME','pull_request'),('GITHUB_REPOSITORY','other/repo'),('GITHUB_ACTIONS','false'),('ANTHROPIC_API_KEY','')]:
            with self.subTest(field=field),patch.dict(os.environ,{field:value}):
                with self.assertRaises(ValueError):claude_trial.configured_key(self.root)
        with patch.dict(os.environ,{'BENEFIT_AI_CLOUD':'0'}),patch.object(claude_trial,'load_key',return_value='local-key') as local:
            self.assertEqual(claude_trial.configured_key(self.root),'local-key');local.assert_called_once_with(self.root/'.env.claude')

    def test_check_only_and_completed_day_never_collect(self):
        m=self.module()
        with patch.object(m,'daily',side_effect=AssertionError('must not collect')):
            result=m.cloud_run(self.root,now=NOW,store=self.fixture.store())
            self.assertEqual(result['status'],'check_passed');self.assertEqual(result['requests'],30)
            control=json.loads(self.fixture.store().read('control')[0])
            self.assertEqual(control['check']['code_sha'],'a'*40)
            self.assertEqual(control['check']['snapshot_sha256'],m.snapshot_digest(control))
            result=m.cloud_run(self.root,now=datetime.fromisoformat('2026-11-05T22:00:00+09:00'),check_only=False,store=self.fixture.store())
            self.assertEqual(result['status'],'already_completed_today')
        self.assertEqual(len(json.loads(self.fixture.store().read('control')[0])['days']),1)

    def test_limit_revision_upgrades_legacy_control_once_without_touching_rows(self):
        from benefit_monitor.store import save
        m=self.module()
        legacy=json.loads(self.fixture.store().read('control')[0])
        legacy['budget'].update(cap_microdollars=5_000_000,max_requests=200);legacy['budget'].pop('cap_kind',None)
        legacy.update(limit_revision=1)
        _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(legacy).encode(),sha)
        # Without the approved policy revision nothing changes.
        with patch.object(m,'daily',side_effect=AssertionError('must not collect')):
            self.assertFalse(m.cloud_run(self.root,now=NOW,store=self.fixture.store())['limit_revision_applied'])
        self.assertEqual(json.loads(self.fixture.store().read('control')[0])['budget']['max_requests'],200)
        save(self.root/'public/ai-cloud-trial.json',dict(self.fixture.policy,expires_at=None,limit_revision=2))
        with patch.object(m,'daily',side_effect=AssertionError('must not collect')):
            first=m.cloud_run(self.root,now=NOW,store=self.fixture.store())
            second=m.cloud_run(self.root,now=NOW,store=self.fixture.store())
        self.assertEqual((first['limit_revision_applied'],first['cap_kind'],first['expires_at']),(True,'monthly',None))
        self.assertFalse(second['limit_revision_applied'])
        control=json.loads(self.fixture.store().read('control')[0])
        self.assertEqual(control['budget']['requests'],legacy['budget']['requests'])
        self.assertEqual((control['days'],control['budget']['halted']),(legacy['days'],legacy['budget']['halted']))
        from benefit_monitor.cloud_state import validate_control
        bad=dict(control);bad['budget']=dict(control['budget'],max_requests=200)
        with self.assertRaises(ValueError):validate_control(self.root,bad)
        legacy_shape=json.loads(json.dumps(control));legacy_shape['budget'].pop('cap_kind')
        with self.assertRaises(ValueError):validate_control(self.root,legacy_shape)

    def test_bad_fingerprint_unsettled_and_halted_block(self):
        m=self.module()
        for kind in ('key','reserved','halted'):
            control=json.loads(self.fixture.store().read('control')[0])
            if kind=='key':control['api_key_sha256']='0'*64
            if kind=='reserved':control['budget']['requests'].append({'id':'f'*64,'status':'reserved','reserved_microdollars':100,'charged_microdollars':0,'started_at':NOW.isoformat()})
            if kind=='halted':control['budget']['halted']=True
            _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(control).encode(),sha)
            with self.subTest(kind=kind),patch.object(m,'daily',side_effect=AssertionError('no paid work')):
                with self.assertRaises(ValueError):m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())
            # Restore independent fixture baseline, preserving the immutable runtime blob.
            _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(self.fixture.control).encode(),sha)

    def test_inactive_expired_not_due_and_wait_do_not_mark_day(self):
        m=self.module()
        with patch.object(m,'daily',side_effect=AssertionError('no paid work')),patch.object(m,'disable_workflow') as disable:
            self.assertEqual(m.cloud_run(self.root,now=NOW.replace(hour=5),check_only=False,store=self.fixture.store())['status'],'not_due')
            with patch.object(m,'todays_refresh',return_value='running'):
                self.assertEqual(m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())['status'],'waiting_for_existing_refresh')
            data=json.loads(self.fixture.store().read('control')[0]);data['active']=False
            _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(data).encode(),sha)
            self.assertEqual(m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())['status'],'handoff_required')
        self.assertEqual(len(json.loads(self.fixture.store().read('control')[0])['days']),1)

    def test_attempt_is_remote_before_inner_daily_and_failure_cannot_retry(self):
        m=self.module()
        def inner(*args,**kwargs):
            control=json.loads(self.fixture.store().read('control')[0])
            self.assertEqual(control['days']['2026-11-06']['status'],'attempted')
            self.assertNotIn('2026-11-06',load(self.root/'cache/ai_daily/days.json',{})['days'])
            raise RuntimeError('fixture failure')
        with patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=inner):
            with self.assertRaises(RuntimeError):m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())
        with patch.object(m,'daily',side_effect=AssertionError('no retry')):
            self.assertEqual(m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())['status'],'previous_attempt_requires_review')
        self.assertEqual(json.loads(self.fixture.store().read('control')[0])['days']['2026-11-06']['status'],'failed')

    def test_completed_free_refresh_is_imported_before_ai_attempt(self):
        m=self.module();events=[]
        def restored(*args):events.append('public_holds_restored')
        def inner(*args,**kwargs):
            self.assertEqual(events,['public_holds_restored'])
            return {'status':'completed'}
        with patch.object(m,'restore_public',side_effect=restored),patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=inner),patch.object(m,'publish_snapshot',return_value={'status':'dispatched_not_yet_verified'}):
            m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())

    def test_unresolved_budget_blocks_without_collecting_or_disabling(self):
        m=self.module()
        base=json.loads(self.fixture.store().read('control')[0])
        for kind in ('reserved','halted'):
            data=json.loads(json.dumps(base))
            if kind=='halted':data['budget']['halted']=True
            else:data['budget']['requests'].append({'id':'e'*64,'status':'reserved','reserved_microdollars':100,'charged_microdollars':0,'started_at':NOW.isoformat()})
            _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(data).encode(),sha)
            with self.subTest(kind=kind),patch.object(m,'daily',side_effect=AssertionError('no paid work')),patch.object(m,'disable_workflow') as disable:
                with self.assertRaisesRegex(ValueError,'manual review'):
                    m.cloud_run(self.root,now=NOW.replace(day=10),check_only=False,store=self.fixture.store())
                disable.assert_not_called()

    def test_new_public_hold_cannot_be_overwritten_or_dispatched(self):
        import inspect,subprocess
        from benefit_monitor.store import save
        m=self.module();store=self.fixture.store()
        self.assertIn('expected_sha',inspect.signature(m.publish_snapshot).parameters,'초기 공개 파일 lease 전달 필요')
        stale={'status':'ready','items':[{'id':'old-item'}]}
        newer={'status':'ready','items':[],'operational_state':{'items':{'old-item':{'hold_reason':'body_changed'}}}}
        save(self.root/'delivery/public/briefing.json',stale)
        remote={'data':newer}
        original_api=store._api
        def api(path):return {'private':False,'full_name':'Kim-Taesu/benefit-monitor'} if not path else original_api(path)
        def gh(args,**kwargs):
            if 'GET' in args:return subprocess.CompletedProcess(args,0,'b'*40+'\n','')
            import base64
            remote['data']=json.loads(base64.b64decode(json.loads(kwargs['input'])['content']))
            return subprocess.CompletedProcess(args,0,json.dumps({'commit':{'sha':'c'*40}}),'')
        with patch.object(store,'_api',side_effect=api),patch.object(m,'validate',return_value=stale),patch('benefit_monitor.mirror.subprocess.run',side_effect=gh),patch.object(m,'actions_request') as dispatch:
            with self.assertRaises(ValueError):m.publish_snapshot(self.root,store,NOW,KEY,expected_sha='a'*40)
            dispatch.assert_not_called()
        self.assertEqual(remote['data'],newer)

    def test_only_the_monthly_cap_stops_paid_work_and_it_never_disables_the_workflow(self):
        m=self.module()
        data=json.loads(self.fixture.store().read('control')[0])
        for n in range(40):data['days'][f'2026-09-{n%28+1:02d}' if n<28 else f'2026-08-{n-27:02d}']={'status':'failed'}
        data['budget']['requests'] += [{'id':f'{i:064x}','status':'failed','reserved_microdollars':0,'charged_microdollars':0,
                                       'started_at':'2026-11-06T01:00:00+00:00'} for i in range(100,400)]
        _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(data).encode(),sha)
        # 300 extra rows and 40 earlier run days are no limit: the run proceeds to the inner daily.
        with patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=RuntimeError('reached daily')):
            with self.assertRaisesRegex(RuntimeError,'reached daily'):
                m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())
        data=json.loads(self.fixture.store().read('control')[0])
        data['days'].pop('2026-11-06',None)
        data['budget']['requests'].append({'id':'9'*64,'status':'completed','reserved_microdollars':14_997_720,
                                           'charged_microdollars':14_997_720,'started_at':'2026-11-06T02:00:00+00:00'})
        _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(data).encode(),sha)
        with patch.object(m,'disable_workflow') as disable,patch.object(m,'daily',side_effect=AssertionError('cap must stop paid work')):
            self.assertEqual(m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())['status'],'trial_budget_limit')
            disable.assert_not_called()
        # The next Seoul calendar month starts with a fresh allowance.
        with patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=RuntimeError('reached daily')):
            with self.assertRaisesRegex(RuntimeError,'reached daily'):
                m.cloud_run(self.root,now=NOW.replace(month=12,day=1),check_only=False,store=self.fixture.store())

    def test_success_preserves_latest_child_budget_and_dispatch_is_not_deployment(self):
        m=self.module()
        def inner(*args,**kwargs):
            from benefit_monitor.cloud_state import CloudSession
            from benefit_monitor.trial_budget import TrialBudget
            session=CloudSession.from_context(self.root,self.fixture.store())
            budget=TrialBudget(self.fixture.budget_path,checkpoint=session.checkpoint_budget)
            budget.reserve('f'*64,1000);budget.settle('f'*64,100,{'input_tokens':100,'output_tokens':180},'a'*64)
            return {'status':'completed'}
        with patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=inner),patch.object(m,'publish_snapshot',return_value={'status':'dispatched_not_yet_verified'}):
            result=m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())
        remote=json.loads(self.fixture.store().read('control')[0])
        self.assertEqual(len(remote['budget']['requests']),31);self.assertEqual(remote['days']['2026-11-06']['status'],'completed')
        self.assertEqual(result['delivery']['status'],'dispatched_not_yet_verified')

    def test_todays_refresh_counts_collecting_runs_and_ignores_other_days(self):
        m=self.module()
        def store(rows):
            class Fake:
                def _api(self,path):
                    event=path.split('event=')[1].split('&')[0]
                    return {'workflow_runs':[r for r in rows if r['event']==event]}
            return Fake()
        run=lambda event,day,status='completed',conclusion='success':dict(event=event,status=status,conclusion=conclusion,
            created_at=f'2026-11-{day}T00:10:00+09:00')
        self.assertEqual(m.todays_refresh(store([run('schedule','05')]),NOW),'missing')
        self.assertEqual(m.todays_refresh(store([run('workflow_dispatch','06')]),NOW),'ready')
        self.assertEqual(m.todays_refresh(store([run('schedule','06'),run('workflow_dispatch','06','in_progress',None)]),NOW),'running')
        self.assertEqual(m.todays_refresh(store([run('schedule','06',conclusion='failure')]),NOW),'failed')

    def test_missing_refresh_is_dispatched_once_only_after_ten(self):
        m=self.module()
        with patch.object(m,'daily',side_effect=AssertionError('no paid work')),patch.object(m,'todays_refresh',return_value='missing'),\
                patch.object(m,'dispatch_refresh') as dispatch:
            early=m.cloud_run(self.root,now=NOW.replace(hour=9),check_only=False,store=self.fixture.store())
            dispatch.assert_not_called()
            late=m.cloud_run(self.root,now=NOW.replace(hour=10),check_only=False,store=self.fixture.store())
            dispatch.assert_called_once()
        self.assertEqual((early['status'],early['refresh'],late['status']),('waiting_for_existing_refresh','missing','refresh_dispatched'))
        with patch.object(m,'daily',side_effect=AssertionError('no paid work')),patch.object(m,'todays_refresh',return_value='running'),\
                patch.object(m,'dispatch_refresh',side_effect=AssertionError('no second dispatch')):
            self.assertEqual(m.cloud_run(self.root,now=NOW.replace(hour=11),check_only=False,store=self.fixture.store())['status'],
                             'waiting_for_existing_refresh')
        self.assertNotIn('2026-11-06',json.loads(self.fixture.store().read('control')[0])['days'])

    def test_workflow_run_event_is_trusted(self):
        m=self.module()
        with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'workflow_run'}):m.trusted_environment()
        with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'pull_request_target'}),self.assertRaises(ValueError):m.trusted_environment()

    def test_provider_rejection_finishes_day_but_exits_red(self):
        m=self.module()
        def inner(*args,**kwargs):
            from benefit_monitor.cloud_state import CloudSession
            from benefit_monitor.trial_budget import TrialBudget
            session=CloudSession.from_context(self.root,self.fixture.store())
            budget=TrialBudget(self.fixture.budget_path,checkpoint=session.checkpoint_budget)
            budget.reserve('f'*64,1000);budget.fail('f'*64,'http_400','grammar too large')
            return {'status':'completed'}
        with patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=inner),patch.object(m,'publish_snapshot',return_value={'status':'dispatched_not_yet_verified'}):
            result=m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())
        self.assertEqual((result['status'],result['provider_failures'],result['halted']),('completed_with_provider_failure',['http_400'],True))
        self.assertEqual(m.exit_code(result),1)
        self.assertEqual(m.exit_code({'status':'completed'}),0)
        self.assertEqual(json.loads(self.fixture.store().read('control')[0])['days']['2026-11-06']['status'],'completed')

    def test_reviewed_halt_is_released_only_by_manual_dispatch_and_keeps_rows(self):
        m=self.module()
        control=json.loads(self.fixture.store().read('control')[0])
        control['budget']['requests'].append({'id':'f'*64,'status':'failed','reserved_microdollars':100,'charged_microdollars':0,
                                              'started_at':NOW.isoformat(),'error_code':'http_400'})
        control['budget']['halted']=True
        _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(control).encode(),sha)
        with patch.object(m,'daily',side_effect=AssertionError('no paid work')):
            with self.assertRaises(ValueError):m.cloud_run(self.root,now=NOW,store=self.fixture.store())
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'schedule'}),self.assertRaisesRegex(ValueError,'manual'):
                m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store(),resume=True)
            result=m.cloud_run(self.root,now=NOW,store=self.fixture.store(),resume=True)
            again=m.cloud_run(self.root,now=NOW,store=self.fixture.store(),resume=True)
        self.assertEqual((result['status'],result['halt_resumed'],again['halt_resumed']),('check_passed',True,False))
        remote=json.loads(self.fixture.store().read('control')[0])['budget']
        self.assertFalse(remote['halted']);self.assertEqual(remote['requests'],control['budget']['requests'])
        self.assertEqual(len(remote['manual_reviews']),len(control['budget'].get('manual_reviews',[]))+1)
        reserved=json.loads(self.fixture.store().read('control')[0])
        reserved['budget']['halted']=True
        reserved['budget']['requests'].append({'id':'e'*64,'status':'reserved','reserved_microdollars':100,'charged_microdollars':0,'started_at':NOW.isoformat()})
        _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(reserved).encode(),sha)
        with self.assertRaisesRegex(ValueError,'inflight'):m.cloud_run(self.root,now=NOW,store=self.fixture.store(),resume=True)

    def put_control(self,mutate):
        control=json.loads(self.fixture.store().read('control')[0]);mutate(control)
        _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(control).encode(),sha)
        return control

    def rejected_today(self,control,code='http_400',charged=0,status='failed'):
        control['days']['2026-11-06']={'status':'completed'}
        control['budget']['requests'].append({'id':'f'*64,'status':status,'reserved_microdollars':13012,'charged_microdollars':charged,
                                              'started_at':'2026-11-05T23:02:15+00:00','error_code':code})

    def test_rejected_day_is_retried_once_by_manual_dispatch_and_keeps_history(self):
        m=self.module();seen=[]
        before=self.put_control(lambda c:(self.rejected_today(c),c['budget'].update(halted=True)))
        def inner(*args,**kwargs):
            seen.append(load(self.root/'cache/ai_daily/days.json',{})['days'])
            self.assertEqual(json.loads(self.fixture.store().read('control')[0])['days']['2026-11-06']['status'],'attempted')
            return {'status':'completed'}
        with patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=inner),\
                patch.object(m,'publish_snapshot',return_value={'status':'dispatched_not_yet_verified'}):
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'schedule'}),self.assertRaisesRegex(ValueError,'manual'):
                m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store(),retry=True)
            result=m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store(),retry=True,resume=True)
            with self.assertRaisesRegex(ValueError,'not eligible'):
                m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store(),retry=True)
            self.assertEqual(m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())['status'],'already_completed_today')
        self.assertEqual((result['status'],result['retried_day']),('completed',True))
        self.assertFalse(json.loads(self.fixture.store().read('control')[0])['budget']['halted'])
        self.assertNotIn('2026-11-06',seen[0])
        remote=json.loads(self.fixture.store().read('control')[0])
        day=remote['days']['2026-11-06']
        self.assertEqual((day['status'],day['retry_of']['status'],day['retry_of']['request_ids']),('completed','completed',['f'*64]))
        self.assertEqual(remote['budget']['requests'],before['budget']['requests'])
        self.assertEqual(len(remote['days']),len(before['days']))

    def test_retry_refuses_billed_or_non_rejection_days(self):
        m=self.module()
        base=json.loads(self.fixture.store().read('control')[0])
        cases={'billed':dict(charged=5),'server error':dict(code='http_529'),'completed request':dict(status='completed',code='')}
        for name,kwargs in cases.items():
            with self.subTest(name=name):
                self.put_control(lambda c:(c.clear(),c.update(json.loads(json.dumps(base))),self.rejected_today(c,**kwargs)))
                with patch.object(m,'todays_refresh',return_value='ready'),patch.object(m,'daily',side_effect=AssertionError('no paid work')),\
                        self.assertRaisesRegex(ValueError,'rejected unbilled'):
                    m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store(),retry=True)
        self.put_control(lambda c:(c.clear(),c.update(json.loads(json.dumps(base)))))
        with patch.object(m,'todays_refresh',return_value='ready'),self.assertRaisesRegex(ValueError,'not eligible'):
            m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store(),retry=True)

    def test_grammar_probe_only_is_manual_marks_no_day_and_reports_red_on_rejection(self):
        m=self.module();made=[]
        class Fake:
            def __init__(self,folder,budget,key):made.append(budget)
            def grammar_probe(self,schema):
                self.schema=schema;return {'status':outcome[0],'schema_sha256':'0'*64,'cached':False}
        outcome=['passed']
        with patch.object(m,'ClaudeClient',Fake),patch.object(m,'daily',side_effect=AssertionError('no daily')),\
                patch.object(m,'disable_workflow') as disable:
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'schedule'}),self.assertRaisesRegex(ValueError,'manual'):
                m.cloud_run(self.root,now=NOW,store=self.fixture.store(),probe_only=True)
            passed=m.cloud_run(self.root,now=NOW,store=self.fixture.store(),probe_only=True)
            outcome[0]='rejected'
            rejected=m.cloud_run(self.root,now=NOW,store=self.fixture.store(),probe_only=True)
        self.assertEqual((passed['status'],rejected['status']),('probe_passed','probe_rejected'))
        self.assertEqual((m.exit_code(passed),m.exit_code(rejected)),(0,1))
        self.assertEqual(len(made),2);disable.assert_not_called()
        self.assertNotIn('2026-11-06',json.loads(self.fixture.store().read('control')[0])['days'])

if __name__=='__main__':unittest.main()
