"""No activation from stale state or while the Mac writer is still enabled."""
import importlib
import json
from pathlib import Path
from unittest.mock import patch
import contextlib
import io
import unittest
import test_cloud_state as fixtures
from benefit_monitor.store import load,save

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.CloudStateTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root;self.f.session()
        data=json.loads(self.f.store().read('control')[0]);data['active']=False
        _,sha=self.f.store().read('control');self.f.store().write('control',json.dumps(data).encode(),sha)
        save(self.root/'cache/ai_daily/days.json',{'days':data['days']})
        save(self.root/'ai-automation.json',{'enabled':True})

    def module(self):
        try:return importlib.import_module('scripts.ai_cloud_handoff')
        except ModuleNotFoundError:self.fail('안전한 handoff 도구가 아직 없음')

    def test_prepare_preserves_mac_and_keeps_cloud_inactive(self):
        m=self.module()
        with patch.object(m,'configured_key',return_value='fixture-api-key-123456'):
            result=m.prepare_state(self.root,self.f.store())
        self.assertFalse(json.loads(self.f.store().read('control')[0])['active'])
        self.assertTrue(load(self.root/'ai-automation.json',{})['enabled'])
        self.assertEqual(result['requests'],30)

    def test_stage_stops_local_before_latest_snapshot_and_does_not_activate(self):
        m=self.module();seen=[]
        def stop(root):
            seen.append('stop');save(root/'ai-automation.json',{'enabled':False})
        def capture(*args,**kwargs):
            self.assertEqual(seen,['stop']);return original(*args,**kwargs)
        original=m.capture_control
        with patch.object(m,'stop_local',side_effect=stop),patch.object(m,'capture_control',side_effect=capture),patch.object(m,'configured_key',return_value='fixture-api-key-123456'):
            m.stage_activation(self.root,self.f.store(),'a'*40)
        data=json.loads(self.f.store().read('control')[0]);self.assertFalse(data['active'])
        self.assertFalse(load(self.root/'ai-automation.json',{})['enabled'])

    def stage(self):
        m=self.module()
        with patch.object(m,'stop_local',side_effect=lambda root:save(root/'ai-automation.json',{'enabled':False})),patch.object(m,'configured_key',return_value='fixture-api-key-123456'):
            m.stage_activation(self.root,self.f.store(),'a'*40)
        return m

    def mark_checked(self,m):
        from benefit_monitor.cloud_state import CloudSession
        session=CloudSession.restore(self.root,self.f.store())
        data=session.control.copy();data['check']={'snapshot_sha256':m.snapshot_digest(data),'ref':'refs/heads/main','code_sha':'a'*40}
        session._commit(data)

    def test_activation_requires_fresh_main_cloud_check_and_local_stopped(self):
        m=self.stage()
        with patch.object(m,'local_loaded',return_value=False):
            with self.assertRaises(ValueError):m.activate_checked(self.root,self.f.store(),'a'*40)
            self.mark_checked(m)
            with patch.object(m,'local_loaded',return_value=True):
                with self.assertRaises(ValueError):m.activate_checked(self.root,self.f.store(),'a'*40)
            m.activate_checked(self.root,self.f.store(),'a'*40)
        self.assertTrue(json.loads(self.f.store().read('control')[0])['active'])

    def test_changed_local_ledger_and_reserved_state_cannot_activate(self):
        m=self.stage();self.mark_checked(m)
        data=load(self.f.budget_path,{});data['requests'].append({'id':'e'*64,'status':'reserved','reserved_microdollars':100,'charged_microdollars':0,'started_at':'2026-11-06T00:00:00+09:00'})
        save(self.f.budget_path,data)
        with patch.object(m,'local_loaded',return_value=False):
            with self.assertRaises(ValueError):m.activate_checked(self.root,self.f.store(),'a'*40)
        with patch.object(m,'configured_key',return_value='fixture-api-key-123456'):
            with self.assertRaises(ValueError):m.capture_control(self.root,self.f.crypto)

    def test_runner_failure_never_deletes_existing_identity(self):
        from scripts import run_ai_cloud
        identity=self.root/'.tools/cloud-state/identity.txt'
        identity.parent.mkdir(parents=True,exist_ok=True);identity.write_text('existing-fixture-identity')
        with contextlib.redirect_stdout(io.StringIO()),patch.object(run_ai_cloud,'ROOT',self.root),patch.object(run_ai_cloud,'trusted_environment',side_effect=ValueError('untrusted')):
            self.assertEqual(run_ai_cloud.main(),1)
        self.assertTrue(identity.exists())

    def test_workflow_secret_scope_and_serialization(self):
        self.module()
        root=Path(__file__).resolve().parents[1]
        raw=(root/'.github/workflows/ai-daily.yml').read_text()
        self.assertIn("cron: '*/15 0-14,21-23 * * *'",raw)
        self.assertIn('cancel-in-progress: false',raw)
        self.assertNotIn('pull_request',raw)
        self.assertEqual(raw.count('${{ secrets.ANTHROPIC_API_KEY }}'),1)
        self.assertEqual(raw.count('${{ secrets.BENEFIT_AI_STATE_IDENTITY }}'),1)
        self.assertLess(raw.index('Install verified project-local age'),raw.index('${{ secrets.ANTHROPIC_API_KEY }}'))

if __name__=='__main__':unittest.main()
