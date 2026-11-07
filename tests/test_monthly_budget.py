"""Monthly $15 cap ledger (user-approved 2026-11-07); legacy rows are never rewritten."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

import test_cloud_state as state_fixture
from benefit_monitor.store import save, load
from benefit_monitor.trial_budget import TrialBudget, MONTHLY_CAP

ROOT = Path(__file__).resolve().parents[1]
OCT = '2026-10-20T01:00:00+00:00'
NOV = datetime.fromisoformat('2026-11-07T10:00:00+09:00')
NOW_KST = NOV


def row(n, started, amount=14_999_000):
    return {'id': f'{n:064x}', 'status': 'completed', 'reserved_microdollars': amount,
            'charged_microdollars': amount, 'started_at': started}


class MonthlyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'budget.json'
        self.budget = TrialBudget.initialize(self.path, 'claude-haiku-5-5', '0.10', '0.50')

    def seed(self, rows, **extra):
        state = load(self.path, {})
        state['requests'] = rows
        state.update(extra)
        save(self.path, state)

    def test_constants_and_new_ledger_shape(self):
        state = load(self.path, {})
        self.assertEqual(MONTHLY_CAP, 15_000_000)
        self.assertEqual((state['cap_microdollars'], state['cap_kind']), (MONTHLY_CAP, 'monthly'))
        self.assertNotIn('max_requests', state)

    def test_reserve_blocks_only_when_month_cap_exceeded(self):
        self.seed([row(1, OCT)])
        self.budget.reserve('a' * 64, 2_000, now=NOV)  # October spend does not count in November
        self.path.unlink()
        self.budget = TrialBudget.initialize(self.path, 'claude-haiku-5-5', '0.10', '0.50')
        self.seed([row(1, '2026-11-02T01:00:00+00:00')])
        with self.assertRaisesRegex(ValueError, 'monthly budget exhausted'):
            self.budget.reserve('b' * 64, 2_000, now=NOV)

    def test_month_boundary_uses_seoul_calendar(self):
        # 2026-10-31T16:00Z is already 2026-11-01 01:00 KST.
        rows = [row(1, '2026-10-31T16:00:00+00:00')]
        self.assertEqual(TrialBudget.month_exposure({'requests': rows}, NOV), 14_999_000)
        rows = [row(1, '2026-10-31T14:59:00+00:00')]
        self.assertEqual(TrialBudget.month_exposure({'requests': rows}, NOV), 0)

    def test_summary_reports_month_figures(self):
        now = datetime.now(timezone.utc).isoformat()
        self.seed([row(1, now, 1_000)])
        summary = self.budget.summary()
        self.assertEqual(summary['month_exposure_microdollars'], 1_000)
        self.assertEqual(summary['month_remaining_microdollars'], MONTHLY_CAP - 1_000)

    def test_more_than_200_rows_valid(self):
        self.seed([row(i + 1, OCT, 10) for i in range(250)])
        self.assertEqual(self.budget.summary()['request_count'], 250)

    def test_halted_still_blocks(self):
        self.seed([], halted=True)
        with self.assertRaisesRegex(ValueError, 'halted'):
            self.budget.reserve('c' * 64, 10, now=NOV)

    def test_legacy_ledger_keeps_legacy_rules_until_revised(self):
        rows = [row(i + 1, '2026-11-05T01:00:00+00:00', 100) for i in range(36)]
        self.seed(rows, cap_microdollars=5_000_000, max_requests=200)
        state = load(self.path, {})
        state.pop('cap_kind')
        save(self.path, state)
        self.assertEqual(self.budget.summary()['request_count'], 36)
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            self.budget.reserve('d' * 64, 5_000_000, now=NOV)

    def test_legacy_ledger_upgrades_without_rewriting_rows(self):
        fixture = state_fixture.CloudStateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        legacy = deepcopy(fixture.control['budget'])
        legacy['requests'] += [{'id': f'{i + 100:064x}', 'status': 'failed', 'reserved_microdollars': 1000,
                                'charged_microdollars': 0, 'started_at': '2026-11-06T01:00:00+00:00'}
                               for i in range(6)]
        legacy.update(cap_microdollars=5_000_000, max_requests=200)
        legacy.pop('cap_kind')
        self.assertEqual(len(legacy['requests']), 36)
        fixture.control['budget'] = legacy
        session = fixture.session()
        before = json.dumps(session.control['budget']['requests'], sort_keys=True)
        save(fixture.root / 'public/ai-cloud-trial.json', dict(fixture.policy, expires_at=None, limit_revision=2))
        self.assertTrue(session.apply_limit_revision())
        self.assertFalse(session.apply_limit_revision())
        control = json.loads(fixture.store().read('control')[0])
        self.assertEqual(json.dumps(control['budget']['requests'], sort_keys=True), before)
        self.assertEqual((control['budget']['cap_kind'], control['budget']['cap_microdollars'], control['limit_revision']),
                         ('monthly', MONTHLY_CAP, 2))
        self.assertNotIn('max_requests', control['budget'])
        self.assertIsNone(control['expires_at'])

    def test_past_month_overrun_does_not_block_next_month_resume(self):
        self.seed([row(1, OCT, 15_100_000)], halted=True)
        self.assertTrue(self.budget.summary()['halted'])
        self.budget.resume_after_review()
        self.assertFalse(self.budget.summary()['halted'])
        self.budget.reserve('e' * 64, 1_000, now=NOV)

    def test_cloud_resume_after_past_month_overrun(self):
        fixture = state_fixture.CloudStateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        save(fixture.root / 'public/ai-cloud-trial.json', dict(fixture.policy, expires_at=None, limit_revision=2))
        fixture.control.update(expires_at=None, limit_revision=2)
        fixture.session()
        from benefit_monitor.cloud_state import CloudSession
        control = json.loads(fixture.store().read('control')[0])
        control['budget']['requests'].append(row(500, OCT, 15_100_000))
        control['budget']['halted'] = True
        _, sha = fixture.store().read('control')
        fixture.store().write('control', json.dumps(control).encode(), sha)
        session = CloudSession.read_control(fixture.root, fixture.store())
        self.assertTrue(session.resume_after_review(NOW_KST))
        control = json.loads(fixture.store().read('control')[0])
        self.assertFalse(control['budget']['halted'])
        from benefit_monitor.cloud_state import validate_control
        validate_control(fixture.root, control)

    def test_no_run_day_limit(self):
        fixture = state_fixture.CloudStateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        save(fixture.root / 'public/ai-cloud-trial.json', dict(fixture.policy, expires_at=None, limit_revision=2))
        fixture.control.update(expires_at=None, limit_revision=2)
        fixture.control['days'].update({f'2026-10-{n:02d}': {'status': 'completed'} for n in range(1, 31)})
        self.assertGreater(len(fixture.control['days']), 30)
        session = fixture.session()
        from benefit_monitor.cloud_state import validate_control
        validate_control(fixture.root, session.control)
        session.mark_day('2026-11-07')
        self.assertEqual(session.control['days']['2026-11-07']['status'], 'attempted')


if __name__ == '__main__':
    unittest.main()
