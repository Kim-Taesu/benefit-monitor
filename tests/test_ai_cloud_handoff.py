"""The retired Mac-to-cloud handoff can never replace the live cloud ledger."""
import contextlib
import importlib
import io
from pathlib import Path
from unittest.mock import patch
import unittest

import test_cloud_state as fixtures


class HandoffTests(unittest.TestCase):
    def module(self):
        return importlib.import_module('scripts.ai_cloud_handoff')

    def test_prepare_and_activate_are_retired_before_any_network_or_state_access(self):
        m = self.module()
        for command in ('prepare', 'activate'):
            with self.subTest(command=command), patch.object(m, 'github_environment', side_effect=AssertionError('no network')), \
                    patch.object(m.subprocess, 'run', side_effect=AssertionError('no gh/launchctl')):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    self.assertEqual(m.main([command]), 2)
                self.assertIn('retired', err.getvalue())
        for name in ('prepare_state', 'stage_activation', 'activate_checked', 'capture_control', 'setup_policy'):
            self.assertFalse(hasattr(m, name), name)

    def test_check_and_restore_still_read_a_revision_2_control(self):
        m = self.module()
        f = fixtures.CloudStateTests(); f.setUp(); self.addCleanup(f.doCleanups)
        f.session()
        policy = dict(f.policy, expires_at=None, limit_revision=2)
        from benefit_monitor.store import save, load
        save(f.root / 'public/ai-cloud-trial.json', policy)
        control = f.control
        control.update(expires_at=None, limit_revision=2)
        control['budget'].pop('max_requests', None)
        control['budget'].update(cap_kind='monthly', cap_microdollars=15_000_000)
        import json
        _, sha = f.store().read('control'); f.store().write('control', json.dumps(control).encode(), sha)
        save(f.root / 'ai-automation.json', {'enabled': False})
        meta = type('P', (), {'returncode': 0, 'stdout': json.dumps({'private': False, 'full_name': m.REPOSITORY})})()
        for command, status in (('check', 'control_valid'), ('restore', 'restored_local_still_disabled')):
            with self.subTest(command=command), patch.object(m, 'ROOT', f.root), \
                    patch.object(m, 'github_environment', return_value={'GH_TOKEN': 'fixture-token'}), \
                    patch.object(m.subprocess, 'run', return_value=meta), patch.object(m, 'local_loaded', return_value=False), \
                    patch.object(m, 'AgeState', return_value=f.crypto), \
                    patch.object(m, 'GitHubStateStore', side_effect=lambda root, token, crypto: f.store()):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(m.main([command]), 0, out.getvalue())
                self.assertEqual(json.loads(out.getvalue())['status'], status)
        self.assertFalse(load(f.root / 'ai-automation.json', {})['enabled'])

    def test_runner_failure_never_deletes_existing_identity(self):
        from scripts import run_ai_cloud
        f = fixtures.CloudStateTests(); f.setUp(); self.addCleanup(f.doCleanups)
        identity = f.root / '.tools/cloud-state/identity.txt'
        identity.parent.mkdir(parents=True, exist_ok=True); identity.write_text('existing-fixture-identity')
        with contextlib.redirect_stdout(io.StringIO()), patch.object(run_ai_cloud, 'ROOT', f.root), \
                patch.object(run_ai_cloud, 'trusted_environment', side_effect=ValueError('untrusted')):
            self.assertEqual(run_ai_cloud.main(), 1)
        self.assertTrue(identity.exists())

    def test_workflow_secret_scope_and_serialization(self):
        root = Path(__file__).resolve().parents[1]
        raw = (root / '.github/workflows/ai-daily.yml').read_text()
        self.assertIn("cron: '*/15 0-14,21-23 * * *'", raw)
        self.assertIn('cancel-in-progress: false', raw)
        self.assertNotIn('pull_request', raw)
        self.assertEqual(raw.count('${{ secrets.ANTHROPIC_API_KEY }}'), 1)
        self.assertEqual(raw.count('${{ secrets.BENEFIT_AI_STATE_IDENTITY }}'), 1)
        self.assertLess(raw.index('Install verified project-local age'), raw.index('${{ secrets.ANTHROPIC_API_KEY }}'))


if __name__ == '__main__':
    unittest.main()
