"""Request-setting measurement (2026-11-14): manual, once per cell, never published."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import variant_trial as vt
from benefit_monitor.store import load, save

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-11-15T09:00:00+09:00')
DAY = '2026-11-15'


class VariantTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / 'runs'
        patcher = patch.object(vt, 'TRIAL_RUNS', self.runs)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []

    def run_folder(self, run_id, valid, errors=(), output_tokens=100):
        folder = self.runs / run_id
        folder.mkdir(parents=True)
        (folder / 'validation.json').write_text(json.dumps({'valid': valid, 'errors': list(errors)}))
        (folder / 'metadata.json').write_text(json.dumps({'usage': {'input_tokens': 2000, 'output_tokens': output_tokens}}))
        (folder / 'model-output.json').write_text(json.dumps({'summary': '모델 문장'}))

    def regular(self, kind, run_id='a' * 64, status='rejected_draft', valid=False):
        path = f'.tools/ai-{kind}-inputs/{DAY}-0123456789abcdef.json'
        save(self.root / path, {'candidates': []})
        save(self.root / f'cache/{kind}_pick/days.json', {'days': {DAY: {'status': status, 'input_file': path, 'run_id': run_id}}})
        self.run_folder(run_id, valid, ['number'] if not valid else [])

    def invoke(self, root, kind, input_path, variant=None):
        self.calls.append((kind, Path(input_path).name, variant))
        run_id = (kind[0] + variant[-1]) * 32
        self.run_folder(run_id, True, output_tokens=900)
        return {'status': 'validated_draft', 'run_id': run_id}

    def rows(self):
        return load(self.root / vt.STATE, {'rows': []})['rows']

    def test_nothing_is_sent_or_stored_without_execute(self):
        self.regular('festival')
        with patch.object(vt, 'invoke', side_effect=AssertionError('no paid call')):
            added = vt.measure(self.root, NOW, kinds=('festival',))
        self.assertEqual([(r['variant'], r['status']) for r in added],
                         [('baseline', 'rejected_draft'), ('adaptive-medium', 'awaiting_authorization'),
                          ('adaptive-high', 'awaiting_authorization')])
        self.assertEqual([r['variant'] for r in self.rows()], ['baseline'])

    def test_each_cell_is_measured_once_on_the_regular_input(self):
        self.regular('festival')
        with patch.object(vt, 'invoke', side_effect=self.invoke):
            vt.measure(self.root, NOW, kinds=('festival',), execute=True)
            again = vt.measure(self.root, NOW, kinds=('festival',), execute=True)
        self.assertEqual(self.calls, [('festival', f'{DAY}-0123456789abcdef.json', 'adaptive-medium'),
                                      ('festival', f'{DAY}-0123456789abcdef.json', 'adaptive-high')])
        self.assertEqual(again, [])
        rows = {r['variant']: r for r in self.rows()}
        self.assertEqual((rows['baseline']['valid'], rows['baseline']['errors']), (False, ['number']))
        self.assertEqual((rows['adaptive-high']['valid'], rows['adaptive-high']['output_tokens']), (True, 900))
        self.assertEqual(rows['adaptive-high']['microdollars'], 2000 * 0.10 + 900 * 0.50)

    def test_measurement_never_writes_a_pick_or_model_text(self):
        self.regular('festival')
        self.regular('benefit', run_id='c' * 64)
        with patch.object(vt, 'invoke', side_effect=self.invoke):
            vt.measure(self.root, NOW, execute=True)
        for kind in vt.KINDS:
            self.assertFalse((self.root / f'cache/{kind}_pick/pick.json').exists())
        self.assertNotIn('모델 문장', (self.root / vt.STATE).read_text())
        self.assertEqual(len(self.calls), 4)

    def test_a_crash_after_the_request_does_not_open_a_second_attempt(self):
        self.regular('festival')
        with patch.object(vt, 'invoke', side_effect=SystemExit('interrupted')):
            with self.assertRaises(SystemExit):
                vt.measure(self.root, NOW, kinds=('festival',), variants=('adaptive-high',), execute=True)
        with patch.object(vt, 'invoke', side_effect=AssertionError('no second paid call')):
            vt.measure(self.root, NOW, kinds=('festival',), variants=('adaptive-high',), execute=True)
        self.assertEqual([(r['variant'], r['status']) for r in self.rows()],
                         [('baseline', 'rejected_draft'), ('adaptive-high', 'attempted')])

    def test_no_regular_answer_means_no_measurement(self):
        save(self.root / 'cache/festival_pick/days.json', {'days': {DAY: {'status': 'attempted', 'input_file': 'x.json'}}})
        with patch.object(vt, 'invoke', side_effect=AssertionError('no paid call')):
            added = vt.measure(self.root, NOW, execute=True)
        self.assertEqual([(r['kind'], r['status']) for r in added], [('festival', 'no_baseline'), ('benefit', 'no_baseline')])
        self.assertEqual(self.rows(), [])

    def test_credit_exhaustion_stops_the_remaining_cells(self):
        self.regular('festival')
        self.regular('benefit', run_id='c' * 64)
        with patch.object(vt, 'invoke', return_value={'status': 'credit_exhausted', 'run_id': None}) as model:
            vt.measure(self.root, NOW, execute=True)
        self.assertEqual(model.call_count, 1)

    def test_window_closes_after_the_approved_days_and_date(self):
        from datetime import timedelta
        if True:
            for offset in range(vt.MAX_DAYS + 1):
                now = datetime.fromisoformat('2026-11-15T09:00:00+09:00') + timedelta(days=offset)
                day = now.date().isoformat()
                path = f'.tools/ai-festival-inputs/{day}.json'
                save(self.root / path, {})
                run_id = f'{offset:064d}'
                save(self.root / 'cache/festival_pick/days.json', {'days': {day: {'status': 'validated_draft', 'input_file': path, 'run_id': run_id}}})
                self.run_folder(run_id, True)
                self.invoke = lambda root, kind, input_path, variant=None, n=offset: (
                    self.calls.append(n), {'status': 'rejected_draft', 'run_id': None})[1]
                with patch.object(vt, 'invoke', side_effect=self.invoke):
                    last = vt.measure(self.root, now, kinds=('festival',), variants=('adaptive-high',), execute=True)
        self.assertEqual(len(self.calls), vt.MAX_DAYS)
        self.assertEqual(last[0]['status'], 'window_closed')
        self.regular('benefit')
        with patch.object(vt, 'invoke', side_effect=AssertionError('no paid call after the last day')):
            late = vt.measure(self.root, datetime.fromisoformat('2026-12-01T09:00:00+09:00'), execute=True)
        self.assertEqual(late[0]['status'], 'window_closed')

    def test_daily_step_reports_new_ledger_rows_and_no_model_text(self):
        self.regular('festival')
        ledger = self.root / '.tools/claude-trial/live/budget.json'
        save(ledger, {'requests': [{'id': 'regular'}]})
        def invoke(root, kind, input_path, variant=None):
            rows = load(ledger, None)['requests'] + [{'id': 'm-' + variant}]
            save(ledger, {'requests': rows})
            return self.invoke(root, kind, input_path, variant)
        with patch.object(vt, 'invoke', side_effect=invoke):
            step = vt.daily_step(self.root, NOW, execute=True)
        self.assertEqual(step['request_ids'], ['m-adaptive-medium', 'm-adaptive-high'])
        self.assertEqual(step['measured_days'], 1)
        self.assertNotIn('모델 문장', json.dumps(step, ensure_ascii=False))
        self.assertEqual({r['variant'] for r in step['summary']}, {'baseline', 'adaptive-medium', 'adaptive-high'})

    def test_unknown_variant_or_kind_is_refused(self):
        with self.assertRaises(ValueError):
            vt.measure(self.root, NOW, variants=('baseline',), execute=True)
        with self.assertRaises(ValueError):
            vt.measure(self.root, NOW, kinds=('research',), execute=True)

    def test_summary_compares_only_days_shared_with_the_baseline(self):
        def row(day, variant, status, valid, errors=(), tokens=100):
            return dict(day=day, kind='festival', variant=variant, status=status, valid=valid, errors=list(errors),
                        detail=None, output_tokens=tokens, microdollars=200 + tokens * 0.5)
        rows = [row('d1', 'baseline', 'rejected_draft', False, ['number']), row('d1', 'adaptive-high', 'validated_draft', True, tokens=900),
                row('d2', 'baseline', 'validated_draft', True), row('d2', 'adaptive-high', 'rejected_draft', False, ['free'], 800),
                row('d3', 'adaptive-high', 'validated_draft', True), row('d2', 'adaptive-medium', 'attempted', None)]
        result = {r['variant']: r for r in vt.summary(rows)}
        self.assertEqual(set(result), {'baseline', 'adaptive-high'})
        self.assertEqual((result['baseline']['answers'], result['baseline']['passed'], result['baseline']['errors']), (2, 1, {'number': 1}))
        self.assertEqual((result['adaptive-high']['answers'], result['adaptive-high']['pass_rate']), (2, 0.5))
        self.assertEqual(result['adaptive-high']['mean_output_tokens'], 850)


if __name__ == '__main__':
    unittest.main()
