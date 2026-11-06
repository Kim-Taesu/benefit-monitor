import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from benefit_monitor.source_check import evaluate

NOW = datetime(2026, 11, 7, 1, 0, tzinfo=ZoneInfo('Asia/Seoul'))


def source(sid, expect='working'):
    return dict(id=sid, status='active', monitoring=dict(expect=expect))


def briefing(statuses, districts=('checked',), at=NOW - timedelta(minutes=20), **extra):
    data = dict(status='partial', source_report_at=at.isoformat(),
                coverage=dict(sources=[dict(source=k, status=v) for k, v in statuses.items()],
                              districts=[dict(name=f'구{i}', status=s) for i, s in enumerate(districts)]),
                source_health={k: dict(consecutive_failures=3, error_category='timeout') for k, v in statuses.items() if v == 'failed'})
    data.update(extra)
    return data


DEFS = [source('seoul'), source('seven', 'known_failing'), source('kt', 'manual')]


class SourceCheckTests(unittest.TestCase):
    def test_expected_failures_and_manual_sources_pass(self):
        errors, warnings, rows = evaluate(DEFS, briefing(dict(seoul='checked', seven='failed', kt='not_connected')), NOW)
        self.assertEqual((errors, warnings), ([], []))
        self.assertEqual([r['status'] for r in rows], ['checked', 'failed', 'not_connected'])

    def test_working_source_failure_breaks_with_category_only(self):
        errors, _, _ = evaluate(DEFS, briefing(dict(seoul='failed', seven='failed', kt='not_connected')), NOW)
        self.assertEqual(errors, ['seoul: expected working, got failed (timeout, 3 in a row)'])

    def test_cached_is_ok_and_missing_source_fails(self):
        errors, _, _ = evaluate(DEFS, briefing(dict(seoul='cached', kt='not_connected')), NOW)
        self.assertEqual(errors, [])
        errors, _, _ = evaluate(DEFS + [source('emart24_events')], briefing(dict(seoul='checked', kt='not_connected')), NOW)
        self.assertEqual(errors, ['emart24_events: expected working, got not_reported'])

    def test_recovered_known_failure_warns(self):
        _, warnings, _ = evaluate(DEFS, briefing(dict(seoul='checked', seven='checked', kt='not_connected')), NOW)
        self.assertEqual(warnings, ['seven: known failure recovered; set monitoring.expect to working'])

    def test_district_failure_and_stale_or_failed_report_break(self):
        errors, _, _ = evaluate(DEFS, briefing(dict(seoul='checked', kt='not_connected'), districts=('checked', 'failed')), NOW)
        self.assertEqual(errors, ['seoul districts not collected: 구1'])
        old = briefing(dict(seoul='checked', kt='not_connected'), at=NOW - timedelta(hours=31))
        self.assertTrue(any('older than 30h' in e for e in evaluate(DEFS, old, NOW)[0]))
        before = briefing(dict(seoul='checked', kt='not_connected'), at=NOW - timedelta(hours=2))
        self.assertTrue(any('predates' in e for e in evaluate(DEFS, before, NOW, started_at=NOW - timedelta(hours=1))[0]))
        failed = briefing({}, status='collection_failed')
        self.assertTrue(any('collection_failed' in e for e in evaluate(DEFS, failed, NOW)[0]))


if __name__ == '__main__':
    unittest.main()
