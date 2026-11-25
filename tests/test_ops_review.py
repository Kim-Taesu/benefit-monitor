import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import ops_review, quality_report, wire_format
from benefit_monitor.store import load, save

NOW = datetime.fromisoformat('2026-11-24T04:10:00+09:00')
DATA = dict(
    items=[dict(title='트레이더스 개점 16주년 고객 감사제', summary='오는 29일까지 인기 먹거리를 특가 판매한다.',
                conditions='신세계포인트 적립 시 할인', valid_from=None, valid_until='2026-11-26', deadline_at=None,
                fee_status='paid')],
    subscription_pick=dict(source='ai', summary='문래 해링턴 플레이스는 특별공급과 1순위를 열어요.',
                           picks=[dict(id='1', line='영등포구 특별공급·1순위')]),
    benefit_pick=dict(source='rule', summary=None, picks=[dict(id='x', line=None)]),
    subscriptions=dict(items=[dict(name='해링턴 플레이스 문래', district='영등포구',
                                   steps=[dict(label='특별공급', start='2026-11-23', end='2026-11-23')])]),
    topic_cards=dict(topics=[dict(title='문화·체험')]))


class HostTests(unittest.TestCase):
    def test_view_is_built_from_public_fields_only(self):
        host = ops_review.host(DATA, NOW)
        ids = [e['id'] for e in host['entries']]
        self.assertEqual(ids, ['item:0', 'pick:subscription_pick', 'subscription:0', 'topic:0'])  # rule picks have no text
        self.assertEqual(host['entries'][2]['steps'], '특별공급 2026-11-23~2026-11-23')
        self.assertEqual(ops_review.model_input(host)['today'], '2026-11-24')
        self.assertIsNone(ops_review.host({}, NOW))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.host = ops_review.host(DATA, NOW)

    def finding(self, **over):
        return dict(dict(ref='item:0', field='summary', quote='오는 29일까지', issue='date_mismatch'), **over)

    def test_quotes_must_come_from_the_named_field(self):
        self.assertEqual(ops_review.review({'findings': [self.finding()]}, self.host), [])
        self.assertEqual(ops_review.review({'findings': []}, self.host), [])
        cases = {'unknown_ref': self.finding(ref='item:9'), 'unknown_field': self.finding(field='kind'),
                 'quote_not_in_field': self.finding(quote='30일까지'), 'unknown_issue': self.finding(issue='bad'),
                 'finding_shape': dict(self.finding(), note='설명')}
        for code, value in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, ops_review.review({'findings': [value]}, self.host))
        self.assertEqual(ops_review.review({'findings': [self.finding()] * 11}, self.host), ['too_many'])
        self.assertEqual(ops_review.review({'findings': [], 'extra': 1}, self.host), ['draft_shape'])

    def test_wire_round_trip_and_no_free_text(self):
        schema = wire_format.ops_review_wire_schema(None)
        row = schema['properties']['findings']['items']['properties']
        self.assertEqual(list(row), ['ref', 'field', 'quote', 'issue'])  # evidence before the verdict, no note
        wire = dict(wire_version=wire_format.OPS_REVIEW_WIRE, findings=[self.finding()])
        self.assertEqual(wire_format.ops_review_from_wire(wire, self.host), {'findings': [self.finding()]})
        with self.assertRaises(ValueError):
            wire_format.ops_review_from_wire(dict(wire, extra=1), self.host)


class RefreshTests(unittest.TestCase):
    def run_refresh(self, root, model, draft=None):
        calls = []

        def invoke(r, kind, path):
            calls.append(kind)
            self.assertEqual(load(Path(r) / 'cache/ops_review/days.json', {})['days']['2026-11-24']['status'], 'attempted')
            if draft is not None:
                save(Path(r) / 'runs' / 'run1' / 'result.json', draft)
            return model
        with patch.object(ops_review, 'invoke', side_effect=invoke), patch.object(ops_review, 'TRIAL_RUNS', Path(root) / 'runs'):
            result = ops_review.refresh(root, NOW, DATA)
        return result, calls

    def test_one_call_a_day_and_only_public_safe_findings(self):
        with tempfile.TemporaryDirectory(dir=Path(ops_review.__file__).resolve().parents[1]) as tmp:
            good = {'findings': [dict(ref='item:0', field='summary', quote='오는 29일까지', issue='date_mismatch')]}
            result, calls = self.run_refresh(tmp, {'status': 'validated_draft', 'run_id': 'run1'}, good)
            self.assertEqual((calls, result['status']), (['ops_review'], 'completed'))
            self.assertEqual(result['findings'], good['findings'])
            again, calls = self.run_refresh(tmp, {'status': 'validated_draft', 'run_id': 'run1'}, good)
            self.assertEqual((calls, again['status']), ([], 'already_tried'))

    def test_bad_answer_is_rejected_and_failures_never_raise(self):
        with tempfile.TemporaryDirectory(dir=Path(ops_review.__file__).resolve().parents[1]) as tmp:
            bad = {'findings': [dict(ref='item:0', field='summary', quote='지어낸 문장', issue='date_mismatch')]}
            result, _ = self.run_refresh(tmp, {'status': 'validated_draft', 'run_id': 'run1'}, bad)
            self.assertEqual(result, {'status': 'rejected', 'errors': ['quote_not_in_field']})
        with patch.object(ops_review, 'host', side_effect=RuntimeError('boom')):
            self.assertEqual(ops_review.refresh('.', NOW, DATA), {'status': 'failed', 'reason': 'RuntimeError'})


class QualityReportTests(unittest.TestCase):
    def test_findings_are_warnings_only(self):
        usage = dict(days=[dict(day='2026-11-24', kinds={}, total_usd=0, total_requests=1, ops_review=dict(
            status='completed', findings=[dict(ref='item:0', field='summary', issue='date_mismatch', quote='오는 29일까지')]))])
        found, _ = quality_report._ai_value({}, usage)
        self.assertEqual([(f.level, f.section) for f in found], [('warn', 'AI 점검')])
        self.assertIn('오는 29일까지', found[0].message)
        usage['days'][0]['ops_review'] = dict(status='rejected', errors=['quote_not_in_field'])
        found, _ = quality_report._ai_value({}, usage)
        self.assertEqual([f.level for f in found], ['warn'])


if __name__ == '__main__':
    unittest.main()
