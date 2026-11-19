"""Live briefing.json check (2026-11-19): what "deployed and working" means, by data, not by a green workflow.

Incident it guards: a manual approved-snapshot redeploy published `collection_failed` with 0 benefits for ~7
minutes and dropped the AI grocery pick until the next AI run.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from benefit_monitor import live_check
from benefit_monitor.live_check import check, main

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=KST)


def briefing(**over):
    pick = {'picks': [{'title': 'x'}]}
    data = {
        'status': 'partial',
        'generated_at': (NOW - timedelta(hours=4)).isoformat(),
        'items': [{'id': i} for i in range(8)],
        'groceries': {'produce': {'items': [1] * 155}, 'meat': {'items': [1] * 26}},
        'festival_pick': pick, 'benefit_pick': pick, 'subscription_pick': pick, 'grocery_pick': pick,
        'ai_status': {'state': 'ok'},
        'source_health': {'seoul': {'consecutive_failures': 0}},
    }
    data.update(over)
    return data


class LiveCheckTests(unittest.TestCase):
    def test_healthy_briefing_passes(self):
        result = check(briefing(), now=NOW)
        self.assertEqual(result.failures, [])

    def test_collection_failed_fails(self):
        result = check(briefing(status='collection_failed'), now=NOW)
        self.assertTrue(any('collection_failed' in f for f in result.failures))

    def test_zero_benefits_fails(self):
        result = check(briefing(items=[]), now=NOW)
        self.assertTrue(any('혜택 0건' in f for f in result.failures))

    def test_stale_generated_at_fails(self):
        result = check(briefing(generated_at=(NOW - timedelta(hours=37)).isoformat()), now=NOW)
        self.assertTrue(any('갱신' in f for f in result.failures))

    def test_max_age_is_configurable(self):
        old = briefing(generated_at=(NOW - timedelta(hours=37)).isoformat())
        self.assertEqual(check(old, now=NOW, max_age_hours=48).failures, [])

    def test_missing_generated_at_fails(self):
        data = briefing()
        del data['generated_at']
        self.assertTrue(check(data, now=NOW).failures)

    def test_empty_grocery_prices_fail(self):
        data = briefing(groceries={'produce': {'items': []}, 'meat': {'items': [1]}})
        self.assertTrue(any('장보기' in f for f in check(data, now=NOW).failures))

    def test_missing_pick_without_before_is_only_a_warning(self):
        result = check(briefing(grocery_pick=None), now=NOW)
        self.assertEqual(result.failures, [])
        self.assertTrue(any('grocery_pick' in w for w in result.warnings))

    def test_pick_with_no_picks_counts_as_missing(self):
        result = check(briefing(benefit_pick={'picks': []}), now=NOW)
        self.assertTrue(any('benefit_pick' in w for w in result.warnings))

    def test_pick_lost_versus_before_fails(self):
        result = check(briefing(grocery_pick=None), before=briefing(), now=NOW)
        self.assertTrue(any('grocery_pick' in f for f in result.failures))

    def test_pick_absent_before_and_after_is_not_a_loss(self):
        result = check(briefing(grocery_pick=None), before=briefing(grocery_pick=None), now=NOW)
        self.assertEqual(result.failures, [])

    def test_fewer_benefits_than_before_is_a_warning(self):
        result = check(briefing(items=[{'id': 1}]), before=briefing(), now=NOW)
        self.assertEqual(result.failures, [])
        self.assertTrue(any('8건 → 1건' in w for w in result.warnings))

    def test_failing_sources_and_ai_state_are_reported(self):
        data = briefing(source_health={'seven': {'consecutive_failures': 48, 'error_category': 'timeout'}},
                        ai_status={'state': 'credit_exhausted'})
        result = check(data, now=NOW)
        self.assertEqual(result.failures, [])
        self.assertTrue(any('seven' in w for w in result.warnings))
        self.assertTrue(any('credit_exhausted' in w for w in result.warnings))

    def test_every_registered_tab_pick_is_checked(self):
        from benefit_monitor.tab_picks import KEYS
        self.assertTrue(set(KEYS) | {'grocery_pick'} <= set(live_check.PICK_KEYS))


class LiveCheckCliTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data, ensure_ascii=False))
        return str(path)

    def test_exit_code_follows_failures(self):
        fresh = briefing(generated_at=datetime.now(KST).isoformat())
        self.assertEqual(main([self.write('ok.json', fresh)]), 0)
        self.assertEqual(main([self.write('bad.json', {**fresh, 'items': []})]), 1)

    def test_unreadable_source_fails(self):
        self.assertEqual(main([str(self.dir / 'nope.json')]), 1)

    def test_save_keeps_a_copy_for_a_later_before(self):
        fresh = briefing(generated_at=datetime.now(KST).isoformat())
        saved = self.dir / 'before.json'
        self.assertEqual(main([self.write('live.json', fresh), '--save', str(saved)]), 0)
        self.assertEqual(json.loads(saved.read_text())['status'], 'partial')
        lost = {**fresh, 'grocery_pick': None}
        self.assertEqual(main([self.write('after.json', lost), '--before', str(saved)]), 1)


if __name__ == '__main__':
    unittest.main()
