import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import ai_usage, gate_corpus, quality_report
from test_auto_publish import D1, D2, NOW, draft_for, host, period_facts

RUN_A, RUN_B, RUN_C = 'a' * 64, 'b' * 64, 'c' * 64


def write_run(runs, run_id, base, draft, kind='research', variant=None):
    folder = Path(runs) / run_id
    folder.mkdir(parents=True)
    (folder / 'metadata.json').write_text(json.dumps(dict(kind=kind, variant=variant)))
    (folder / 'input.json').write_text(json.dumps(base, ensure_ascii=False))
    (folder / 'normalized-output.json').write_text(json.dumps(draft, ensure_ascii=False))


class FakeStore:
    def __init__(self, raw=None, error=None):
        self.raw, self.error, self.writes = raw, error, []

    def read(self, kind):
        assert kind == 'corpus'
        if self.error:
            raise ValueError(self.error)
        return self.raw, 'f' * 40

    def write(self, kind, raw, sha):
        self.writes.append((kind, raw, sha))
        self.raw = raw
        return 'e' * 40


class CorpusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self.tmp.name) / 'runs'
        base = host(D1, D2)
        write_run(self.runs, RUN_A, base, draft_for(base, **period_facts()))
        # Same page bodies under another candidate: stored once.
        other = host(D1, D2, cid='c2')
        write_run(self.runs, RUN_B, other, draft_for(other, **period_facts()))
        write_run(self.runs, RUN_C, base, draft_for(base, **period_facts()), kind='festival')

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_keeps_research_runs_with_their_decision_and_one_copy_of_each_body(self):
        corpus = gate_corpus.empty()
        self.assertEqual(gate_corpus.capture(corpus, self.runs, NOW, '1' * 40), 2)
        self.assertEqual(set(corpus['records']), {RUN_A, RUN_B})
        self.assertEqual(len(corpus['bodies']), 2)
        record = corpus['records'][RUN_A]
        self.assertEqual(record['decision'], {'publish': True, 'reasons': []})
        self.assertNotIn('body', record['host']['documents'][0])
        self.assertEqual(gate_corpus.capture(corpus, self.runs, NOW, '1' * 40), 0)  # already there

    def test_replay_reports_only_code_changes(self):
        corpus = gate_corpus.empty()
        gate_corpus.capture(corpus, self.runs, NOW, '1' * 40)
        summary = gate_corpus.replay(corpus)
        self.assertEqual((summary['records'], summary['unchanged'], summary['publish_to_held']), (2, 2, 0))
        # A stricter rule in the current code moves both recorded publications to held.
        real = gate_corpus.auto_publish.decide
        with patch.object(gate_corpus.auto_publish, 'decide',
                          lambda *a: dict(real(*a), publish=False, reasons=['not_personal'])):
            summary = gate_corpus.replay(corpus)
        self.assertEqual((summary['unchanged'], summary['publish_to_held']), (0, 2))
        self.assertEqual(summary['reasons_added'], {'not_personal': 2})
        text = json.dumps(summary, ensure_ascii=False)
        self.assertNotIn('서울 미술', text)  # counts and reason codes only

    def test_trim_drops_oldest_records_and_their_bodies(self):
        corpus = gate_corpus.empty()
        gate_corpus.capture(corpus, self.runs, NOW, '1' * 40)
        corpus['records'][RUN_A]['recorded_at'] = '2026-10-01T00:00:00+09:00'
        size = len(gate_corpus.pack(corpus))
        self.assertEqual(gate_corpus.trim(corpus, limit=size - 1), 1)
        self.assertEqual(list(corpus['records']), [RUN_B])

    def test_daily_creates_saves_and_never_replaces_on_read_failure(self):
        store = FakeStore(error='GitHub state request failed: http_404')
        result = gate_corpus.daily(store, self.runs, NOW, '1' * 40)
        self.assertEqual((result['status'], result['added'], len(store.writes)), ('ok', 2, 1))
        self.assertIsNone(store.writes[0][2])  # created
        again = FakeStore(raw=store.raw)
        self.assertEqual(gate_corpus.daily(again, self.runs, NOW, '1' * 40)['added'], 0)
        self.assertEqual(again.writes, [])  # nothing new, nothing written
        broken = FakeStore(error='GitHub state request unavailable')
        self.assertEqual(gate_corpus.daily(broken, self.runs, NOW, '1' * 40), {'status': 'read_failed'})
        self.assertEqual(broken.writes, [])


class UsageTests(unittest.TestCase):
    def test_summarize_by_kind_with_measurement_and_other(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = host(D1)
            write_run(tmp, RUN_A, base, {}, kind='research', variant='baseline')
            write_run(tmp, RUN_B, base, {}, kind='benefit', variant='adaptive-medium')
            rows = [dict(id=RUN_A, status='completed', charged_microdollars=1500),
                    dict(id=RUN_B, status='completed', charged_microdollars=2500),
                    dict(id=RUN_C, status='failed', charged_microdollars=0,
                         usage={'server_tool_use': {'web_search_requests': 2}})]
            kinds = ai_usage.summarize(rows, tmp)
        self.assertEqual(kinds['research'], dict(requests=1, failed=0, usd=0.0015, web_searches=0))
        self.assertEqual(kinds['benefit:measure']['usd'], 0.0025)
        self.assertEqual(kinds['other'], dict(requests=1, failed=1, usd=0.0, web_searches=2))

    def test_a_kinds_approved_regular_setting_is_not_measurement(self):
        # 2026-11-26: the regular benefit pick runs with adaptive-high (pick_common.REGULAR_VARIANTS).
        with tempfile.TemporaryDirectory() as tmp:
            write_run(tmp, RUN_A, host(D1), {}, kind='benefit', variant='adaptive-high')
            write_run(tmp, RUN_B, host(D1), {}, kind='festival', variant='adaptive-high')
            rows = [dict(id=RUN_A, status='completed', charged_microdollars=3000),
                    dict(id=RUN_B, status='completed', charged_microdollars=3000)]
            self.assertEqual(set(ai_usage.summarize(rows, tmp)), {'benefit', 'festival:measure'})

    def test_history_keeps_one_row_per_day_and_31_days(self):
        history = None
        for day in range(1, 40):
            history = ai_usage.add_day(history, f'2026-10-{day:02d}' if day <= 31 else f'2026-11-{day - 31:02d}',
                                       {'research': dict(requests=1, failed=0, usd=0.01, web_searches=0)})
        history = ai_usage.add_day(history, '2026-11-08', {}, {'status': 'ok'})
        self.assertEqual(len(history['days']), 31)
        self.assertEqual(history['days'][-1], dict(day='2026-11-08', kinds={}, total_usd=0, total_requests=0,
                                                   gate_corpus={'status': 'ok'}))


class QualityValueTests(unittest.TestCase):
    def usage(self, kind, days, corpus=None):
        rows = [dict(day=f'2026-11-{d:02d}', kinds={kind: dict(requests=3, failed=0, usd=0.01, web_searches=0)},
                     total_usd=0.01, total_requests=3) for d in range(10, 10 + days)]
        if corpus:
            rows[-1]['gate_corpus'] = corpus
        return dict(schema_version=1, days=rows)

    def test_idle_kind_for_a_week_is_a_warning(self):
        data = dict(tab_checks=dict(festivals=[], notices=[{}]))
        found, facts = quality_report._ai_value(data, self.usage('festival_check', 7))
        self.assertEqual([f.level for f in found], ['warn'])
        self.assertIn('festival_check', found[0].message)
        found, _ = quality_report._ai_value(data, self.usage('notice_triage', 7))
        self.assertEqual(found, [])  # 1 folded notice is visible
        found, _ = quality_report._ai_value(data, self.usage('festival_check', 6))
        self.assertEqual(found, [])  # not a week yet

    def test_gate_replay_changes_are_a_warning(self):
        corpus = dict(status='ok', records=10, unchanged=8, publish_to_held=2, held_to_publish=0, reasons_added={'not_personal': 2})
        found, facts = quality_report._ai_value({}, self.usage('research', 1, corpus))
        self.assertEqual([f.level for f in found], ['warn'])
        self.assertIn('공개→보류 2', found[0].message)


if __name__ == '__main__':
    unittest.main()
