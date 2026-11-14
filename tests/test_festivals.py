import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import cost_policy, festivals, publish
from benefit_monitor.store import save
from test_pipeline import benefit, SOURCE

NOW = datetime.fromisoformat('2026-11-07T06:00:00+09:00')
KFES = dict(id='kfes', domains=['korean.visitkorea.or.kr'], collector='kfes_festivals', pages=2, window_days=30)
ID = '5c6f720a-dd3e-4e54-bd2e-0ed7a72147ee'


def row(**over):
    data = dict(fstvlCntntsId=ID, cntntsNm='구미라면 축제', fstvlBgngDe='2026.11.06', fstvlEndDe='2026.11.08',
                areaNm='경상북도 구미시', dtadr='구미역 일원', adres='경상북도 구미시 역전로', fstvlAspcsNm='구미시',
                fstvlUtztFareInfo='무료', fstvlDscntInfo='', fstvlOutlCn='라면<br>축제',
                fstvlCrmnCn='1. 라면 레스토랑<br>문의 010-1234-5678 a@b.com',
                fstvlHmpgUrl='<a href="https://www.gumiramyun.com/" target="_blank">홈</a>', fstvlClCd='MF',
                cntntsMdfcnYmd='2026-10-30')
    data.update(over)
    return data


FIREWORKS = ('운정호수공원 불꽃축제는 2017년 주민들의 손으로 시작된 축제이다. 2026년 제8회를 맞이한 올해 축제의 주제는 ‘다시, 빛’이며, '
             '10월 31일 운정호수공원 일대에서 개최된다. 축제 당일 오후 2시부터 오후 6시 30분까지 거리예술 공연과 체험부스가 운영되며, '
             '오후 7시 30분에는 점등식과 불꽃쇼가 진행된다. 또한 축제 당일부터 12월 31일까지 불빛정원을 운영하여 빛을 활용한 경관을 선보인다.')


class MainDayTests(unittest.TestCase):
    """2026-11-14: the listing ran a one-day fireworks festival to 12/31 (its light garden), so the card
    still showed it two weeks after the day and linked to the page of the finished event."""

    def held(self, summary, start='2026.10.31', end='2026.12.31'):
        return festivals.parse(row(fstvlOutlCn=summary, fstvlBgngDe=start, fstvlEndDe=end))['end']

    def test_single_day_festival_with_a_long_side_programme_ends_on_its_day(self):
        self.assertEqual(self.held(FIREWORKS), '2026-10-31')
        item = festivals.parse(row(fstvlOutlCn=FIREWORKS, fstvlBgngDe='2026.10.31', fstvlEndDe='2026.12.31'))
        self.assertIn('12월 31일까지 불빛정원', item['summary'])  # The official text itself is untouched.
        now = datetime.fromisoformat('2026-11-14T06:00:00+09:00')
        raw = row(fstvlOutlCn=FIREWORKS, fstvlBgngDe='2026.10.31', fstvlEndDe='2026.12.31')
        self.assertEqual(festivals.select([raw], now, 90), [])
        self.assertEqual(len(festivals.select([raw], datetime.fromisoformat('2026-10-31T20:00:00+09:00'), 90)), 1)

    def test_listing_period_is_kept_whenever_the_text_is_not_that_clear(self):
        kept = '2026-12-31'
        for summary in (
                '해운대구는 10월 31일 점등식을 시작으로 12월 31일까지 해운대빛축제를 연다.',            # a range
                '10월 31일부터 12월 31일까지 매주 금, 토, 일 진행되는 힐링축제이다.',                   # a range
                '축제는 12월 31일까지 이어지며, 개막식은 10월 31일 호수공원 일대에서 개최된다.',        # the opening only
                '올해 축제는 10월 31일 개막식과 함께 호수공원에서 개최된다.',                          # the opening only
                '지난해 10월 31일 개최된 축제에는 10만 명이 찾았다.',                                  # not this year's statement
                '11월 7일 호수공원 일대에서 개최된다.',                                                # another day than the start
                '10월 31일 호수공원에서 개최된다. 12월 1일 시민회관에서도 개최된다.',                   # two days
                '빛축제가 10월 31일 호수공원 일대에서 개최된다. 축제는 12월 31일까지 매일 저녁 이어진다.',  # goes on
                '10월 31일 호수공원에서 개최된다. 이후 12월 25일 한 번 더 열린다.',                      # returns
                '10월 31일 호수공원 일대에서 개최된다. ' + '빛의 정원을 거닐어 보자. ' * 40 + '12월 24일 시민회관에서도 개최된다.',  # past the card cut
                '빛으로 물드는 호수공원의 겨울 축제이다.'):
            self.assertEqual(self.held(summary), kept, summary)
        # A short listing is never cut: "개최된다" on the first day of a three-day festival is ordinary.
        self.assertEqual(self.held('10월 31일 호수공원 일대에서 개최된다.', end='2026.11.02'), '2026-11-02')


class FestivalTests(unittest.TestCase):
    def test_parse_keeps_official_fields_and_strips_private_contacts(self):
        item = festivals.parse(row())
        self.assertEqual((item['start'], item['end'], item['region']), ('2026-11-06', '2026-11-08', '경상북도 구미시'))
        self.assertEqual(item['summary'], '라면 축제')
        self.assertNotIn('010', item['programs'])
        self.assertNotIn('@', item['programs'])
        self.assertEqual(item['homepage'], 'https://www.gumiramyun.com/')
        self.assertTrue(item['culture_tourism'])
        self.assertEqual(item['url'], festivals.DETAIL + ID)
        self.assertIsNone(festivals.parse(row(fstvlEndDe='2026.11.01')))
        self.assertIsNone(festivals.parse(row(fstvlCntntsId='../x')))
        self.assertEqual(festivals.parse(row(fstvlHmpgUrl='http://plain.example'))['homepage'], '')

    def test_fee_words_only(self):
        self.assertEqual(festivals.fee_status('무료'), 'free')
        self.assertEqual(festivals.fee_status('입장료 무료'), 'free')
        self.assertEqual(festivals.fee_status('유료 (20% 할인)'), 'paid')
        self.assertEqual(festivals.fee_status('10,000원 (상품권 5,000원 환급)'), 'paid')
        self.assertEqual(festivals.fee_status('무료(일부 체험 유료)'), 'mixed')
        self.assertEqual(festivals.fee_status('홈페이지 참조'), 'unknown')

    def test_select_window_dedup_and_order(self):
        rows = [row(fstvlCntntsId='00000000-0000-4000-8000-00000000000%d' % n, fstvlBgngDe=s, fstvlEndDe=e)
                for n, (s, e) in enumerate([('2026.11.20', '2026.11.21'), ('2026.11.01', '2026.11.06'),
                                            ('2026.12.20', '2026.12.21'), ('2026.11.07', '2026.11.07')])]
        items = festivals.select(rows + [rows[0]], NOW, 30)
        self.assertEqual([(i['start'], i['end']) for i in items], [('2026-11-07', '2026-11-07'), ('2026-11-20', '2026-11-21')])

    def test_collect_posts_form_for_ongoing_and_upcoming_within_budget(self):
        cost_policy.reset(10)
        sent = []
        def post(opener, payload, domains):
            sent.append(dict(payload))
            return [row()] if payload['searchDate'] == 'A' else []
        with patch.object(festivals, 'fetch', return_value=b'User-agent: *\nAllow: /\n'), \
                patch.object(festivals, '_post', side_effect=post):
            bundle = festivals.collect(KFES, NOW)
        self.assertEqual([p['searchDate'] for p in sent], ['A', 'B'])
        self.assertEqual(len(bundle['items']), 1)
        self.assertEqual(festivals.sanitize(bundle, NOW)['items'], bundle['items'])
        with patch.object(festivals, 'fetch', return_value=b'User-agent: *\nDisallow: /kfes/\n'):
            with self.assertRaises(ValueError):
                festivals.collect(KFES, NOW)

    def test_sanitize_rejects_stale_tampered_or_private_bundles(self):
        bundle = dict(schema_version=1, source='kfes', fetched_at=NOW.isoformat(), notice='x', items=[festivals.parse(row())])
        self.assertEqual(festivals.sanitize(bundle, NOW)['notice'], festivals.NOTICE)
        self.assertIsNone(festivals.sanitize(bundle, NOW + timedelta(hours=31)))
        for change in (dict(url='https://evil.example/'), dict(fee_status='cheap'), dict(summary='전화 010-1234-5678'),
                       dict(homepage='javascript:alert(1)'), dict(extra=1)):
            item = dict(bundle['items'][0], **change)
            self.assertIsNone(festivals.sanitize(dict(bundle, items=[item]), NOW), change)
        ended = dict(bundle['items'][0], start='2026-11-01', end='2026-11-06')
        self.assertEqual(festivals.sanitize(dict(bundle, items=[ended]), NOW)['items'], [])


class FestivalPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        item = benefit(fee_status='paid', conditions='입장료 5,000원').data()
        save(self.root / 'sources.yaml', dict(sources=[SOURCE], max_age_days=7))
        save(self.root / 'report.json', dict(verified_at=NOW.isoformat(), complete=False, new=[item], needs_recheck=[],
                                             collection=dict(online=True, successful_sources=['test'], successful_districts=0)))
        save(self.root / 'public/verified.json', [dict(item, public_release=True)])

    def test_export_carries_festivals_separately_from_verified_items(self):
        bundle = dict(schema_version=1, source='kfes', fetched_at=NOW.isoformat(), notice='x', items=[festivals.parse(row())])
        save(self.root / 'cache/festivals.json', bundle)
        data = publish.run(self.root, now=NOW + timedelta(minutes=5))
        self.assertEqual([i['name'] for i in data['festivals']['items']], ['구미라면 축제'])
        self.assertNotIn('kfes', {i['source'] for i in data['items']})
        from benefit_monitor import public_snapshot
        clean = public_snapshot.validate(self.root, data, NOW + timedelta(minutes=10))
        self.assertEqual(clean['festivals'], data['festivals'])
        tampered = dict(data, festivals=dict(data['festivals'], items=[dict(data['festivals']['items'][0], url='https://evil.example/')]))
        self.assertNotIn('festivals', public_snapshot.validate(self.root, tampered, NOW + timedelta(minutes=10)))

    def test_missing_or_stale_cache_publishes_without_festivals(self):
        self.assertNotIn('festivals', publish.run(self.root, now=NOW))
        save(self.root / 'cache/festivals.json', dict(schema_version=1, source='kfes',
                                                      fetched_at=(NOW - timedelta(days=2)).isoformat(), notice='x', items=[]))
        self.assertNotIn('festivals', publish.run(self.root, now=NOW))


if __name__ == '__main__':
    unittest.main()
