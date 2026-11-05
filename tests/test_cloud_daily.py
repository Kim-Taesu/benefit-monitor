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
