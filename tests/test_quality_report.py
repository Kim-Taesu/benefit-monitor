import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from benefit_monitor import quality_report as qr
from benefit_monitor.subscriptions import sanitize

NOW = datetime.fromisoformat('2026-11-24T08:00:00+09:00')
GENERATED = '2026-11-24T03:47:59+09:00'
RAW = json.loads((Path(__file__).parent / 'fixtures/subscriptions/bundle-2026-11-18.json').read_text())


def sections(**over):
    data = dict(generated_at=GENERATED,
                groceries=dict(produce=dict(survey_date='2026-11-23', items=[{}]), meat=dict(survey_date='2026-11-23', items=[{}])),
                festivals=dict(fetched_at='2026-11-24T03:41:00+09:00', items=[]),
                health_notices=dict(fetched_at='2026-11-24T03:21:00+09:00', boards=[{}]),
                subscriptions=dict(fetched_at='2026-11-24T03:31:00+09:00', items=[{}]))
    data.update(over)
    return data


def messages(found):
    return [(f.level, f.message) for f in found]


class SectionTests(unittest.TestCase):
    def test_fresh_sections_pass(self):
        self.assertEqual(qr._sections(sections(), NOW), [])

    def test_monday_produce_survey_must_be_there_on_tuesday(self):
        # 2026-11-24 (Tue): the Monday table was dropped and Friday's 11-20 survey stayed up.
        data = sections(groceries=dict(produce=dict(survey_date='2026-11-20'), meat=dict(survey_date='2026-11-23')))
        self.assertEqual([f.level for f in qr._sections(data, NOW)], ['error'])
        # On Monday the newest survey is Friday's.
        monday = sections(generated_at='2026-11-23T03:46:00+09:00',
                          groceries=dict(produce=dict(survey_date='2026-11-20'), meat=dict(survey_date='2026-11-22')),
                          festivals=dict(fetched_at='2026-11-23T03:41:00+09:00'),
                          health_notices=dict(fetched_at='2026-11-23T03:21:00+09:00', boards=[{}]),
                          subscriptions=dict(fetched_at='2026-11-23T03:31:00+09:00', items=[{}]))
        self.assertEqual(qr._sections(monday, NOW), [])

    def test_missing_or_stale_sections_are_errors(self):
        data = sections(festivals=dict(fetched_at='2026-11-22T03:41:00+09:00'))
        data.pop('subscriptions')
        found = messages(qr._sections(data, NOW))
        self.assertIn(('error', 'festivals 수집이 공개 시각보다 48시간 오래됐습니다'), found)
        self.assertIn(('error', 'subscriptions 섹션이 공개본에 없습니다'), found)


class ItemTests(unittest.TestCase):
    def item(self, **over):
        return dict(dict(title='행사', summary='', valid_until='2026-11-30', deadline_at=None), **over)

    def test_summary_date_disagreeing_with_valid_until(self):
        # 2026-11-24 트레이더스: "29일까지" in the summary, valid_until the 26th.
        data = dict(items=[self.item(summary='오는 29일까지 특가 판매', valid_until='2026-11-26')])
        self.assertEqual([f.level for f in qr._items(data, NOW)], ['warn'])
        same = dict(items=[self.item(summary='11월 30일까지 열립니다')])
        self.assertEqual(qr._items(same, NOW), [])

    def test_expired_items_are_reported(self):
        data = dict(items=[self.item(valid_until='2026-11-23'), self.item(deadline_at='2026-11-24T07:00:00+09:00')])
        self.assertEqual([f.level for f in qr._items(data, NOW)], ['warn', 'warn'])


class PickTests(unittest.TestCase):
    def test_ai_pick_that_no_longer_passes_today_is_an_error(self):
        # Generated on 11-18 naming 특별공급 for 중화역 라온프라이빗 센트로, whose 특별공급 closed on 11-16.
        now = datetime.fromisoformat('2026-11-18T09:00:00+09:00')
        pick = dict(schema_version=1, generated_at='2026-11-18T08:00:00+09:00', day='2026-11-18', source='ai',
                    summary='중랑구 중화역 라온프라이빗 센트로는 신혼부부 특별공급과 1순위 접수가 있어요. 조건은 공고문에서 확인하세요.',
                    picks=[dict(id='2026000497', line='중랑구 1순위'), dict(id='2026940256', line='서초구 임의공급')])
        data = dict(subscriptions=sanitize(RAW, now), subscription_pick=pick)
        self.assertEqual([(f.level, f.section) for f in qr._picks(data, now)], [('error', 'subscription')])
        ok = dict(pick, summary='중랑구 중화역 라온프라이빗 센트로는 1순위와 2순위 접수가 있어요. 조건은 공고문에서 확인하세요.')
        self.assertEqual(qr._picks(dict(data, subscription_pick=ok), now), [])

    def test_rule_fallback_is_a_warning(self):
        data = dict(benefit_pick=dict(source='rule', picks=[{}]))
        self.assertEqual([(f.level, f.section) for f in qr._picks(data, NOW)], [('warn', 'benefit')])


class TopicTests(unittest.TestCase):
    def test_empty_topic_cards_are_an_error(self):
        found = qr._topics_and_festivals(dict(topic_cards=dict(topics=[], used_fallback=True)), NOW)
        self.assertEqual([f.level for f in found], ['error'])
        self.assertEqual(qr._topics_and_festivals(dict(topic_cards=dict(topics=[{}])), NOW), [])


class CommandTests(unittest.TestCase):
    def test_exit_code_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'briefing.json'
            path.write_text(json.dumps(dict(status='collection_failed', generated_at=GENERATED, items=[])))
            self.assertEqual(qr.main(['--briefing', str(path), '--now', NOW.isoformat()]), 1)
            self.assertEqual(qr.main(['--briefing', str(Path(tmp) / 'missing.json')]), 1)

    def test_markdown_lists_errors_first(self):
        text = qr.markdown([qr.Finding('warn', 'a', 'w'), qr.Finding('error', 'b', 'e')], ['fact'])
        self.assertIn('결과: **실패** · 오류 1 · 경고 1', text)
        self.assertLess(text.index('| ❌ 오류 | b | e |'), text.index('| ⚠️ 경고 | a | w |'))


if __name__ == '__main__':
    unittest.main()
