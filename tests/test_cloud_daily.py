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
        legacy['budget']['max_requests']=40;legacy.pop('limit_revision',None)
        _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(legacy).encode(),sha)
        # Without the approved policy revision nothing changes.
        with patch.object(m,'daily',side_effect=AssertionError('must not collect')):
            self.assertFalse(m.cloud_run(self.root,now=NOW,store=self.fixture.store())['limit_revision_applied'])
        self.assertEqual(json.loads(self.fixture.store().read('control')[0])['budget']['max_requests'],40)
        extended='2026-11-19T13:09:12.753468+09:00'
        save(self.root/'public/ai-cloud-trial.json',dict(self.fixture.policy,expires_at=extended,limit_revision=1))
        with patch.object(m,'daily',side_effect=AssertionError('must not collect')):
            first=m.cloud_run(self.root,now=NOW,store=self.fixture.store())
            second=m.cloud_run(self.root,now=NOW,store=self.fixture.store())
        self.assertEqual((first['limit_revision_applied'],first['max_requests'],first['expires_at']),(True,200,extended))
        self.assertFalse(second['limit_revision_applied'])
        control=json.loads(self.fixture.store().read('control')[0])
        self.assertEqual(control['budget']['requests'],legacy['budget']['requests'])
        self.assertEqual((control['days'],control['budget']['halted']),(legacy['days'],legacy['budget']['halted']))
        bad=dict(control);bad['budget']=dict(control['budget'],max_requests=40)
        from benefit_monitor.cloud_state import validate_control
        with self.assertRaises(ValueError):validate_control(self.root,bad)
        with self.assertRaises(ValueError):validate_control(self.root,dict(control,expires_at='2026-11-20T00:00:00+09:00'))

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
            self.assertEqual(m.cloud_run(self.root,now=NOW.replace(day=10),check_only=False,store=self.fixture.store())['status'],'trial_expired');disable.assert_called_once()
            with patch.object(m,'preceding_refresh',return_value=False):
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
        with patch.object(m,'preceding_refresh',return_value=True),patch.object(m,'daily',side_effect=inner):
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
        with patch.object(m,'restore_public',side_effect=restored),patch.object(m,'preceding_refresh',return_value=True),patch.object(m,'daily',side_effect=inner),patch.object(m,'publish_snapshot',return_value={'status':'dispatched_not_yet_verified'}):
            m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())

    def test_expired_unresolved_budget_still_disables_workflow_without_collecting(self):
        m=self.module()
        base=json.loads(self.fixture.store().read('control')[0])
        for kind in ('reserved','halted'):
            data=json.loads(json.dumps(base))
            if kind=='halted':data['budget']['halted']=True
            else:data['budget']['requests'].append({'id':'e'*64,'status':'reserved','reserved_microdollars':100,'charged_microdollars':0})
            _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(data).encode(),sha)
            with self.subTest(kind=kind),patch.object(m,'daily',side_effect=AssertionError('no paid work')),patch.object(m,'disable_workflow') as disable:
                self.assertEqual(m.cloud_run(self.root,now=NOW.replace(day=10),check_only=False,store=self.fixture.store())['status'],'trial_expired')
                disable.assert_called_once()

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

    def test_global_daily_and_request_caps_stop_without_collection(self):
        m=self.module()
        base=json.loads(self.fixture.store().read('control')[0])
        for kind in ('days','requests'):
            data=json.loads(json.dumps(base))
            if kind=='days':
                for n in range(13):data['days'][f'2026-10-{n+10:02d}']={'status':'failed'}
            else:
                data['budget']['requests'] += [{'id':f'{i:064x}','status':'failed','reserved_microdollars':100,'charged_microdollars':0} for i in range(100,270)]
            _,sha=self.fixture.store().read('control');self.fixture.store().write('control',json.dumps(data).encode(),sha)
            with patch.object(m,'disable_workflow') as disable,patch.object(m,'daily',side_effect=AssertionError('cap must stop paid work')):
                self.assertIn(m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())['status'],('trial_run_limit','trial_budget_limit'))
                disable.assert_called_once()

    def test_success_preserves_latest_child_budget_and_dispatch_is_not_deployment(self):
        m=self.module()
        def inner(*args,**kwargs):
            from benefit_monitor.cloud_state import CloudSession
            from benefit_monitor.trial_budget import TrialBudget
            session=CloudSession.from_context(self.root,self.fixture.store())
            budget=TrialBudget(self.fixture.budget_path,checkpoint=session.checkpoint_budget)
            budget.reserve('f'*64,1000);budget.settle('f'*64,100,{'input_tokens':100,'output_tokens':180},'a'*64)
            return {'status':'completed'}
        with patch.object(m,'preceding_refresh',return_value=True),patch.object(m,'daily',side_effect=inner),patch.object(m,'publish_snapshot',return_value={'status':'dispatched_not_yet_verified'}):
            result=m.cloud_run(self.root,now=NOW,check_only=False,store=self.fixture.store())
        remote=json.loads(self.fixture.store().read('control')[0])
        self.assertEqual(len(remote['budget']['requests']),31);self.assertEqual(remote['days']['2026-11-06']['status'],'completed')
        self.assertEqual(result['delivery']['status'],'dispatched_not_yet_verified')

if __name__=='__main__':unittest.main()
