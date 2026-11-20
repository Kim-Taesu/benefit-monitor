"""Monthly $30 cap and 50 web searches a Seoul day (user-approved 2026-11-20)."""
from copy import deepcopy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_cloud_state as state_fixture
from benefit_monitor.claude_trial import ClaudeClient, TrialError, server_searches, web_search_uses
from benefit_monitor.store import load, save
from benefit_monitor.trial_budget import (DAILY_WEB_SEARCH_LIMIT, MONTHLY_CAP, PREVIOUS_MONTHLY_CAP,
                                          WEB_SEARCH_MICRODOLLARS, TrialBudget)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-11-21T03:50:00+09:00')
SEARCH = {'type': 'web_search_20250305', 'name': 'web_search', 'max_uses': 2}


def searched(n, started, used):
    return {'id': f'{n:064x}', 'status': 'completed', 'reserved_microdollars': 50_000,
            'charged_microdollars': 30_000, 'started_at': started, 'web_search_max_uses': 2,
            'usage': {'input_tokens': 1000, 'output_tokens': 10, 'server_tool_use': {'web_search_requests': used}}}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'budget.json'
        self.budget = TrialBudget.initialize(self.path, 'claude-haiku-5-5', '0.10', '0.50')

    def seed(self, rows=(), **extra):
        state = load(self.path, {})
        state['requests'] = list(rows)
        state.update(extra)
        save(self.path, state)

    def test_constants(self):
        self.assertEqual((MONTHLY_CAP, PREVIOUS_MONTHLY_CAP, DAILY_WEB_SEARCH_LIMIT, WEB_SEARCH_MICRODOLLARS),
                         (30_000_000, 15_000_000, 50, 10_000))

    def test_a_15_dollar_ledger_stays_valid_and_keeps_its_own_cap(self):
        self.seed([{'id': '1' * 64, 'status': 'completed', 'reserved_microdollars': 14_999_000,
                    'charged_microdollars': 14_999_000, 'started_at': '2026-11-02T01:00:00+00:00'}],
                  cap_microdollars=PREVIOUS_MONTHLY_CAP)
        with self.assertRaisesRegex(ValueError, 'monthly budget exhausted'):
            self.budget.reserve('a' * 64, 2_000, now=NOW)

    def test_a_15_dollar_ledger_refuses_web_search(self):
        self.seed(cap_microdollars=PREVIOUS_MONTHLY_CAP)
        with self.assertRaisesRegex(ValueError, 'limit revision'):
            self.budget.reserve('a' * 64, 50_000, now=NOW, web_search_uses=2)

    def test_other_caps_are_invalid(self):
        self.seed(cap_microdollars=20_000_000)
        with self.assertRaisesRegex(ValueError, 'do not reset'):
            self.budget.summary()

    def test_daily_search_limit_counts_settled_use_and_reserved_maximum(self):
        rows = [searched(i + 1, '2026-11-20T19:00:00+00:00', 2) for i in range(23)]  # 46 used today (KST)
        rows.append(searched(99, '2026-11-20T14:00:00+00:00', 2))  # 2026-11-20 23:00 KST: yesterday
        self.seed(rows)
        self.assertEqual(TrialBudget.day_web_searches(load(self.path, {}), NOW), 46)
        self.budget.reserve('a' * 64, 50_000, now=NOW, web_search_uses=2)  # reserved maximum: 48
        state = load(self.path, {})
        self.assertEqual(state['requests'][-1]['web_search_max_uses'], 2)
        self.assertEqual(TrialBudget.day_web_searches(state, NOW), 48)
        with self.assertRaisesRegex(ValueError, 'daily web search limit'):
            self.budget.reserve('b' * 64, 50_000, now=NOW, web_search_uses=3)
        self.budget.reserve('c' * 64, 50_000, now=NOW, web_search_uses=2)  # exactly 50
        with self.assertRaisesRegex(ValueError, 'daily web search limit'):
            self.budget.reserve('d' * 64, 50_000, now=NOW, web_search_uses=1)
        # A reservation without search still goes through, and the next Seoul day starts fresh.
        self.budget.reserve('e' * 64, 1_000, now=NOW)
        self.budget.reserve('f' * 64, 50_000, now=NOW + timedelta(days=1), web_search_uses=2)

    def test_a_failed_search_request_keeps_its_maximum(self):
        self.budget.reserve('a' * 64, 50_000, now=NOW, web_search_uses=2)
        self.budget.fail('a' * 64, 'http_500', halt=False)
        self.assertEqual(TrialBudget.day_web_searches(load(self.path, {}), NOW), 2)

    def test_invalid_search_uses(self):
        for uses in (-1, 11, True, 1.5, '2'):
            with self.subTest(uses=uses), self.assertRaisesRegex(ValueError, 'invalid reservation'):
                self.budget.reserve('a' * 64, 1_000, now=NOW, web_search_uses=uses)
        state = load(self.path, {})
        state['requests'] = [dict(searched(1, NOW.isoformat(), 1), web_search_max_uses=11)]
        save(self.path, state)
        with self.assertRaisesRegex(ValueError, 'do not reset'):
            self.budget.summary()


class RequestTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tools').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.tools')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.budget = TrialBudget.initialize(self.root / 'budget.json', 'claude-haiku-5-5', '0.10', '0.50')

    def payload(self, tools):
        return {'model': 'claude-haiku-5-5', 'max_tokens': 1000, 'tools': tools,
                'messages': [{'role': 'user', 'content': 'find the official page'}]}

    def response(self, usage):
        body = {'id': 'msg_test', 'model': 'claude-haiku-5-5', 'type': 'message', 'stop_reason': 'end_turn',
                'content': [{'type': 'text', 'text': 'ok'}], 'usage': usage}
        return io.BytesIO(json.dumps(body).encode())

    def test_tool_parsing(self):
        self.assertEqual(web_search_uses({'messages': []}), 0)
        self.assertEqual(web_search_uses(self.payload([{'name': 'record', 'input_schema': {}}])), 0)
        self.assertEqual(web_search_uses(self.payload([SEARCH])), 2)
        for tools in ([dict(SEARCH, max_uses=None)], [dict(SEARCH, max_uses=11)], [dict(SEARCH, max_uses=0)],
                      [SEARCH, SEARCH], [dict(SEARCH, type='web_search_20260209')],
                      [SEARCH, {'type': 'web_fetch_20250910', 'name': 'web_fetch'}],
                      [{'type': 'code_execution_20260120', 'name': 'code_execution'}]):
            with self.subTest(tools=tools), self.assertRaises(ValueError):
                web_search_uses(self.payload(tools))

    def test_billing_parsing(self):
        self.assertEqual(server_searches({}, 0), 0)
        self.assertEqual(server_searches({'server_tool_use': {'web_search_requests': 2}}, 2), 2)
        for usage, allowed in (({'server_tool_use': {'web_search_requests': 1}}, 0),
                               ({'server_tool_use': {'web_search_requests': 3}}, 2),
                               ({'server_tool_use': {'web_fetch_requests': 1}}, 2),
                               ({'server_tool_use': {'web_search_requests': True}}, 2),
                               ({'server_tool_use': ['x']}, 2)):
            with self.subTest(usage=usage), self.assertRaises(ValueError):
                server_searches(usage, allowed)

    def test_search_cost_is_reserved_and_settled(self):
        client = ClaudeClient(self.root, self.budget, 'fake-secret-for-tests')
        usage = {'input_tokens': 20_000, 'output_tokens': 400, 'server_tool_use': {'web_search_requests': 2}}
        with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(usage)):
            client._request('/v1/messages', self.payload([SEARCH]))
        row = self.budget.summary()['requests'][0]
        self.assertEqual(row['web_search_max_uses'], 2)
        self.assertGreaterEqual(row['reserved_microdollars'], 2 * WEB_SEARCH_MICRODOLLARS + 2 * 30_000 * 0.10 * 2)
        self.assertEqual(row['charged_microdollars'], 20_000 // 10 + 400 // 2 + 2 * WEB_SEARCH_MICRODOLLARS)
        self.assertEqual(row['status'], 'completed')

    def test_search_billing_without_a_search_tool_is_held(self):
        client = ClaudeClient(self.root, self.budget, 'fake-secret-for-tests')
        usage = {'input_tokens': 1000, 'output_tokens': 10, 'server_tool_use': {'web_search_requests': 1}}
        with patch('benefit_monitor.claude_trial.network_open', return_value=self.response(usage)):
            with self.assertRaises(TrialError):
                client._request('/v1/messages', self.payload([]))
        # Held like other unexpected pricing: the reservation stays exposed, nothing is confirmed, the trial halts.
        state = self.budget.summary()
        self.assertTrue(state['halted'])
        self.assertEqual(state['confirmed_microdollars'], 0)
        self.assertGreater(state['exposure_microdollars'], 0)

    def test_daily_limit_stops_before_sending(self):
        rows = [searched(i + 1, datetime.now().astimezone().isoformat(), 2) for i in range(25)]
        state = load(self.root / 'budget.json', {})
        state['requests'] = rows
        save(self.root / 'budget.json', state)
        client = ClaudeClient(self.root, self.budget, 'fake-secret-for-tests')
        with patch('benefit_monitor.claude_trial.network_open', side_effect=AssertionError('must not send')):
            with self.assertRaisesRegex(TrialError, 'persistent budget'):
                client._request('/v1/messages', self.payload([SEARCH]))


class RevisionTests(unittest.TestCase):
    def fixture(self, revision, cap):
        fixture = state_fixture.CloudStateTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.control['budget']['cap_microdollars'] = cap
        fixture.control.update(expires_at=None, limit_revision=revision)
        save(fixture.root / 'public/ai-cloud-trial.json', dict(fixture.policy, expires_at=None, limit_revision=revision))
        return fixture

    def test_revision_2_at_15_dollars_upgrades_once_to_revision_3_at_30(self):
        fixture = self.fixture(2, PREVIOUS_MONTHLY_CAP)
        session = fixture.session()
        before = deepcopy(session.control['budget']['requests'])
        save(fixture.root / 'public/ai-cloud-trial.json', dict(fixture.policy, expires_at=None, limit_revision=3))
        self.assertTrue(session.apply_limit_revision())
        self.assertFalse(session.apply_limit_revision())
        control = json.loads(fixture.store().read('control')[0])
        self.assertEqual((control['limit_revision'], control['budget']['cap_microdollars']), (3, MONTHLY_CAP))
        self.assertEqual(control['budget']['requests'], before)

    def test_revision_and_cap_must_match(self):
        from benefit_monitor.cloud_state import validate_control
        for revision, cap in ((2, MONTHLY_CAP), (3, PREVIOUS_MONTHLY_CAP)):
            with self.subTest(revision=revision):
                fixture = self.fixture(revision, cap)
                with self.assertRaisesRegex(ValueError, 'do not reset'):
                    validate_control(fixture.root, fixture.control)

    def test_repository_policy_records_the_approval(self):
        policy = json.loads((ROOT / 'public/ai-cloud-trial.json').read_text())
        approval = policy['limit_revision_approval']
        self.assertEqual((policy['limit_revision'], approval['approved_at'], approval['monthly_cap_microdollars'],
                          approval['daily_web_search_limit']), (3, '2026-11-20', MONTHLY_CAP, DAILY_WEB_SEARCH_LIMIT))
        self.assertEqual(policy['prior_limit_revision_approvals'][0]['monthly_cap_microdollars'], PREVIOUS_MONTHLY_CAP)


if __name__ == '__main__':
    unittest.main()
