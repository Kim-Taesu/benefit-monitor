"""Credit exhaustion skips the day without halting; the daily request limit is 20."""
import io
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import test_cloud_daily as cloud_fixture
from benefit_monitor.claude_trial import ClaudeClient, TrialError, is_credit_exhausted
from benefit_monitor.trial_budget import TrialBudget

ROOT = Path(__file__).resolve().parents[1]
CREDIT = {'type': 'error', 'error': {'type': 'invalid_request_error',
          'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}}
OTHER = {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'unsupported temperature'}}


class ClientTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tools').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.budget = TrialBudget.initialize(self.root / 'budget.json', 'claude-haiku-5-5', '0.10', '0.50')

    def fail_with(self, body, code=400):
        error = HTTPError('https://api.anthropic.com/v1/messages', code, 'bad', {}, io.BytesIO(json.dumps(body).encode()))
        with patch('benefit_monitor.claude_trial.network_open', side_effect=error):
            with self.assertRaises(TrialError) as ctx:
                ClaudeClient(self.root, self.budget, 'fake-secret').message('s', 'u')
        return ctx.exception

    def test_detector(self):
        self.assertTrue(is_credit_exhausted(400, json.dumps(CREDIT)))
        self.assertTrue(is_credit_exhausted(400, 'YOUR CREDIT BALANCE is low'))
        self.assertFalse(is_credit_exhausted(401, json.dumps(CREDIT)))
        self.assertFalse(is_credit_exhausted(400, json.dumps(OTHER)))

    def test_credit_error_does_not_halt(self):
        error = self.fail_with(CREDIT)
        self.assertTrue(getattr(error, 'credit_exhausted', False))
        state = self.budget.summary()
        self.assertFalse(state['halted'])
        self.assertEqual(state['requests'][0]['error_code'], 'credit_exhausted')

    def test_other_400_still_halts(self):
        error = self.fail_with(OTHER)
        self.assertFalse(getattr(error, 'credit_exhausted', False))
        self.assertTrue(self.budget.summary()['halted'])

    def test_invoke_reports_credit_exhausted_from_cli(self):
        from benefit_monitor.ai_review import invoke
        done = subprocess.CompletedProcess([], 1, stdout=json.dumps({'status': 'credit_exhausted'}), stderr='')
        with patch('benefit_monitor.ai_review.subprocess.run', return_value=done):
            result = invoke(ROOT, 'research', ROOT / 'sources.yaml')
        self.assertEqual(result['status'], 'credit_exhausted')


class DailyTests(unittest.TestCase):
    def test_daily_candidate_limit_20(self):
        from benefit_monitor.ai_daily import daily
        from benefit_monitor.ai_review import review_candidates
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            now = datetime.fromisoformat('2026-11-07T07:00:00+09:00')
            for limit, ok in ((20, True), (21, False)):
                (root / 'ai-automation.json').write_text(json.dumps({'schema_version': 1, 'enabled': True,
                    'recurring_spend_approved': False, 'public_application_approved': False,
                    'hour_kst': 6, 'minute_kst': 0, 'max_ai_candidates_per_day': limit}))
                with patch('benefit_monitor.ai_daily.collect', return_value={}) as collect, \
                     patch('benefit_monitor.ai_daily.refresh', return_value={'topics': []}):
                    if ok:
                        self.assertEqual(daily(root, now=now, online=True)['status'], 'completed')
                        self.assertEqual(collect.call_args.kwargs['ai_max_candidates'], 20)
                    else:
                        with self.assertRaises(ValueError):daily(root, now=now, online=True)
            with patch('benefit_monitor.ai_review.OfficialReader'):
                self.assertEqual(review_candidates(root, [], now, max_candidates=20)['queued'], 0)
            with self.assertRaises(ValueError):review_candidates(root, [], now, max_candidates=21)

    def test_daily_skips_topic_step_on_credit_exhaustion_but_publishes(self):
        from benefit_monitor.ai_daily import daily
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            (root / 'ai-automation.json').write_text(json.dumps({'schema_version': 1, 'enabled': True,
                'recurring_spend_approved': True, 'public_application_approved': True,
                'hour_kst': 6, 'minute_kst': 0, 'max_ai_candidates_per_day': 20}))
            seen = []
            with patch('benefit_monitor.ai_daily.collect', return_value={'ai_review': {'credit_exhausted': True}}), \
                 patch('benefit_monitor.ai_daily.refresh', side_effect=AssertionError('paid topic call')), \
                 patch('benefit_monitor.ai_daily.publish_briefing', side_effect=lambda *a, **k: seen.append(1) or {'status': 'partial'}):
                result = daily(root, now=datetime.fromisoformat('2026-11-07T07:00:00+09:00'), online=True, allow_spend=True, publish=True)
            self.assertEqual(result['status'], 'credit_exhausted')
            self.assertEqual(seen, [1])
            days = json.loads((root / 'cache/ai_daily/days.json').read_text())['days']
            self.assertEqual(days['2026-11-07']['status'], 'failed')


class CloudTests(cloud_fixture.CloudDailyTests):
    """Reuses the cloud fixture; inherited tests are disabled below to avoid reruns."""

    def test_cloud_run_reports_credit_exhausted_and_next_day_runs(self):
        m = self.module()
        calls = []
        def inner(root, **kw):
            policy = json.loads((Path(root) / 'ai-automation.json').read_text())
            calls.append(policy)
            return {'status': 'credit_exhausted' if len(calls) == 1 else 'completed'}
        with patch.object(m, 'todays_refresh', return_value='ready'), patch.object(m, 'daily', side_effect=inner), \
             patch.object(m, 'publish_snapshot', return_value={'status': 'dispatched_not_yet_verified'}):
            first = m.cloud_run(self.root, now=cloud_fixture.NOW, check_only=False, store=self.fixture.store())
            self.assertEqual((first['status'], first['day']), ('credit_exhausted', '2026-11-06'))
            self.assertEqual(m.exit_code(first), 1)
            control = json.loads(self.fixture.store().read('control')[0])
            self.assertEqual(control['days']['2026-11-06']['status'], 'failed')
            self.assertEqual(calls[0]['max_ai_candidates_per_day'], 20)
            self.assertNotIn('trial_expires_at', calls[0])
            status = json.loads((self.root / 'cache/ai_daily/status.json').read_text())
            self.assertEqual((status['state'], status['last_success_day']), ('credit_exhausted', None))
            second = m.cloud_run(self.root, now=cloud_fixture.NOW + timedelta(days=1), check_only=False, store=self.fixture.store())
        self.assertEqual(second['status'], 'completed')
        status = json.loads((self.root / 'cache/ai_daily/status.json').read_text())
        self.assertEqual((status['state'], status['last_success_day']), ('ok', '2026-11-07'))


for _name in [n for n in dir(cloud_fixture.CloudDailyTests) if n.startswith('test_')]:
    setattr(CloudTests, _name, None)

if __name__ == '__main__':unittest.main()
