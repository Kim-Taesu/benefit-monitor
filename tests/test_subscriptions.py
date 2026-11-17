import json
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import cost_policy, subscriptions as s
from benefit_monitor.robots import allowed

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures/subscriptions'
NOW = datetime.fromisoformat('2026-11-17T00:12:00+09:00')
TODAY = NOW.date()
SOURCE = dict(id='subscriptions', domains=['www.applyhome.co.kr'], collector='subscriptions')


def text(name):
    return (FIX / name).read_text(encoding='utf-8')


CALENDAR = json.loads(text('calendar_202611.json'))
EMPTY = {'schdulList': [], 'resultCode': 200}


class CalendarTests(unittest.TestCase):
    def test_rows_skip_holidays_other_regions_and_duplicates(self):
        rows = s.parse_calendar(CALENDAR)
        self.assertNotIn(None, [r['id'] for r in rows])
        self.assertEqual({r['area'] for r in rows}, {'서울', '경기'})
        dups = [(r['id'], r['date'], r['code']) for r in rows]
        self.assertEqual(len(dups), len(set(dups)))
        first = next(r for r in rows if r['id'] == '2026000497' and r['date'] == '2026-11-16')
        self.assertEqual(first, dict(id='2026000497', pblanc='2026000497', name='중화역 라온프라이빗 센트로',
                                     area='서울', date='2026-11-16', code='01', secd='01'))

    def test_unexpected_payload_is_an_error_not_an_empty_month(self):
        with self.assertRaises(ValueError):
            s.parse_calendar({'resultCode': 500})

    def test_error_result_code_is_an_error(self):
        with self.assertRaises(ValueError):
            s.parse_calendar({'resultCode': 500, 'schdulList': []})

    def test_group_merges_days_into_steps_and_keeps_two_week_window(self):
        groups = s.group(s.parse_calendar(CALENDAR), TODAY)
        ids = [g['id'] for g in groups]
        # 대방역(11/1~3)·더샵(11/2)은 지나서 빠지고, 같은 이름이라도 공고번호가 다르면 다른 카드다.
        self.assertEqual(ids, ['2026000497', '2026950090'])
        apt = groups[0]
        self.assertEqual(apt['kind'], 'apt')
        self.assertEqual(apt['steps'], [dict(label='특별공급', start='2026-11-16', end='2026-11-16'),
                                         dict(label='1순위', start='2026-11-17', end='2026-11-18'),
                                         dict(label='2순위', start='2026-11-19', end='2026-11-19')])
        self.assertEqual(groups[1]['kind'], 'officetel')
        self.assertEqual(groups[1]['steps'], [dict(label='청약 접수', start='2026-11-25', end='2026-11-26')])

    def test_window_end_is_inclusive_and_later_complexes_drop(self):
        rows = s.parse_calendar(CALENDAR)
        self.assertEqual([g['id'] for g in s.group(rows, date(2026, 11, 12))], ['2026000497', '2026950090'])
        self.assertEqual([g['id'] for g in s.group(rows, date(2026, 11, 1), days=15)], ['2026950094', '2026910275', '2026000497'])
        self.assertEqual(s.group(rows, date(2026, 11, 27)), [])


class DetailTests(unittest.TestCase):
    def test_apartment_detail_gives_where_how_many_how_much_and_every_step(self):
        d = s.parse_detail(text('detail_apt.html'))
        self.assertEqual(d['district'], '중랑구')
        self.assertEqual(d['units'], 113)
        self.assertEqual(d['steps'][1], dict(label='1순위', start='2026-11-17', end='2026-11-18'))
        self.assertEqual((d['announce'], d['contract_start'], d['contract_end']), ('2026-11-25', '2026-12-07', '2026-12-09'))
        self.assertEqual((d['area_min'], d['area_max']), (45.02, 126.81))
        self.assertEqual((d['price_min'], d['price_max']), (65800, 202100))
        self.assertEqual(d['move_in'], '2029-02')
        self.assertEqual(d['regulation'], ['투기과열지구', '청약과열지역'])

    def test_remaining_units_detail_has_no_price_and_single_receipt_step(self):
        d = s.parse_detail(text('detail_remain.html'))
        self.assertEqual((d['district'], d['units']), ('성남시 분당구', 58))
        self.assertEqual(d['steps'], [dict(label='청약 접수', start='2026-11-02', end='2026-11-02')])
        self.assertEqual((d['price_min'], d['price_max']), (None, None))
        self.assertEqual((d['area_min'], d['area_max']), (74.0, 84.72))
        self.assertEqual(d['regulation'], [])

    def test_officetel_detail_reads_exclusive_area_column(self):
        d = s.parse_detail(text('detail_officetel.html'))
        self.assertEqual((d['units'], d['area_min'], d['area_max']), (74, 20.16, 59.91))
        self.assertEqual((d['price_min'], d['price_max'], d['move_in']), (17800, 54800, '2029-02'))
        self.assertEqual(d['announce'], '2026-12-02')

    def test_resupply_detail_keeps_general_step_and_per_type_rows(self):
        d = s.parse_detail(text('detail_resupply.html'))
        # 이미지(잠실 래미안아이파크)와 같은 값: 43·59 일반, 84 특공, 20·26·34평, 11.1·15.8·18.6억
        self.assertEqual(d['steps'], [dict(label='특별공급', start='2026-11-23', end='2026-11-23'),
                                      dict(label='일반공급', start='2026-11-24', end='2026-11-24')])
        self.assertEqual(d['notice_date'], '2026-11-17')
        self.assertEqual(d['types'], [
            dict(label='43', area=43.73, pyeong=20, general=1, special=0, price=110548),
            dict(label='59A', area=59.47, pyeong=26, general=1, special=0, price=157939),
            dict(label='84D', area=84.96, pyeong=34, general=0, special=1, price=185607)])
        self.assertEqual(d['special_kinds'], [])
        self.assertEqual(d['notice_pdf'], 'https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026930045'
                                          '&pblancNo=2026930045&atchmnflSeqNo=2023023&atchmnflSn=9')

    def test_apartment_special_supply_kinds_are_summed(self):
        d = s.parse_detail(text('detail_apt.html'))
        self.assertEqual(len(d['types']), 10)
        self.assertEqual(d['types'][4], dict(label='73T', area=73.47, pyeong=30, general=1, special=0, price=119200))
        kinds = dict((k['name'], k['count']) for k in d['special_kinds'])
        self.assertEqual(sum(kinds.values()), 60)
        self.assertEqual(d['special_kinds'][0]['name'], '신혼부부')
        self.assertNotIn('계', kinds)

    def test_remain_and_officetel_types_have_totals_only(self):
        r = s.parse_detail(text('detail_remain.html'))
        self.assertEqual(r['types'][0], dict(label='74A', area=74.0, pyeong=None, general=None, special=None, price=None))
        o = s.parse_detail(text('detail_officetel.html'))
        self.assertEqual(o['types'][0], dict(label='20OA', area=20.16, pyeong=None, general=None, special=None, price=17800))
        self.assertEqual([x['label'] for x in o['types']][1:3], ['41OA', '41OB'])

    def test_number_only_type_names_still_get_their_price(self):
        d = s.parse_detail(text('detail_urban.html'))
        self.assertEqual([x['label'] for x in d['types']], ['19A', '19B', '24A', '24B', '29', '34', '59A', '59B'])
        self.assertEqual([x['price'] for x in d['types']], [30510, 29300, 38130, 37360, 45590, 49420, 86700, 95460])

    def test_page_without_location_is_rejected(self):
        with self.assertRaises(ValueError):
            s.parse_detail('<html><body>점검 중</body></html>')

    def test_district_from_address(self):
        self.assertEqual(s.district('경기도 화성시 봉담읍 상리 1'), '화성시')
        self.assertEqual(s.district('서울특별시 강동구 고덕동'), '강동구')
        self.assertEqual(s.district('경기도 가평군 가평읍'), '가평군')
        self.assertIsNone(s.district('주소 미정'))

    def test_request_and_link_per_house_type(self):
        apt = dict(id='1', pblanc='2', secd='01')
        url, data = s.detail_request(apt)
        self.assertEqual(url, 'https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=1&pblancNo=2')
        self.assertIsNone(data)
        self.assertEqual(s.public_url(apt), url)
        remain = dict(id='1', pblanc='2', secd='04')
        url, data = s.detail_request(remain)
        self.assertTrue(url.endswith('/selectAPTRemndrLttotPblancDetailView.do'))
        self.assertEqual(data, b'houseManageNo=1&pblancNo=2&houseSecd=04')
        self.assertEqual(s.public_url(remain), s.CALENDAR_PAGE)
        self.assertTrue(s.detail_request(dict(id='1', pblanc='2', secd='02'))[0].endswith('/selectPRMOLttotPblancDetailView.do'))


def fake_fetch(details=None, calendars=None, robots='The requested URL was not found on this server.<br>'):
    details = details or {}
    calendars = calendars if calendars is not None else {'202611': CALENDAR, '202612': EMPTY}
    calls = []

    def fetch(url, domains, data=None, headers=None):
        calls.append((url, data))
        cost_policy.budget.consume()
        if url.endswith('/robots.txt'):
            return robots.encode()
        if url == s.CALENDAR_URL:
            month = json.loads(data)['inqirePd']
            value = calendars[month]
            if isinstance(value, Exception):
                raise value
            return json.dumps(value).encode()
        from urllib.parse import parse_qs, urlsplit
        key = parse_qs(data.decode() if data else urlsplit(url).query)['houseManageNo'][0]
        value = details.get(key)
        if value is None:
            raise OSError('unexpected ' + key)
        if isinstance(value, Exception):
            raise value
        return value.encode()
    return fetch, calls


class CollectTests(unittest.TestCase):
    def setUp(self):
        cost_policy.reset(s.MAX_REQUESTS)

    def test_collects_two_months_and_enriches_with_details(self):
        fetch, calls = fake_fetch({'2026000497': text('detail_apt.html'), '2026950090': text('detail_officetel.html')})
        with patch.object(s, 'fetch', fetch):
            bundle = s.collect(SOURCE, NOW)
        self.assertEqual([json.loads(d)['inqirePd'] for u, d in calls if u == s.CALENDAR_URL], ['202611', '202612'])
        self.assertEqual(len(calls), 5)  # robots + 달력 2 + 상세 2
        apt, office = bundle['items']
        self.assertEqual((apt['detail'], apt['district'], apt['units'], apt['price_max']), ('checked', '중랑구', 113, 202100))
        self.assertEqual(apt['url'], 'https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000497&pblancNo=2026000497')
        self.assertEqual(office['url'], s.CALENDAR_PAGE)
        # 오피스텔 상세의 "청약접수" 단계는 달력 이름을 쓴다.
        self.assertEqual(office['steps'], [dict(label='청약 접수', start='2026-11-25', end='2026-11-26')])
        self.assertIsNotNone(s.sanitize(bundle, NOW))

    def test_failed_detail_keeps_calendar_card(self):
        fetch, _ = fake_fetch({'2026000497': OSError('timeout'), '2026950090': '<html>점검 중</html>'})
        with patch.object(s, 'fetch', fetch):
            bundle = s.collect(SOURCE, NOW)
        apt = bundle['items'][0]
        self.assertEqual((apt['detail'], apt['units'], apt['district'], apt['checked_at']), ('failed', None, None, None))
        self.assertEqual(apt['steps'][0]['label'], '특별공급')
        self.assertIsNotNone(s.sanitize(bundle, NOW))

    def test_recent_detail_is_reused_and_old_one_refetched(self):
        fetch, _ = fake_fetch({'2026000497': text('detail_apt.html'), '2026950090': text('detail_officetel.html')})
        with patch.object(s, 'fetch', fetch):
            previous = s.collect(SOURCE, NOW - timedelta(days=1))
        fetch, calls = fake_fetch({'2026950090': text('detail_officetel.html')})
        previous['items'][1]['checked_at'] = (NOW - timedelta(days=s.DETAIL_DAYS, minutes=1)).isoformat()
        with patch.object(s, 'fetch', fetch):
            bundle = s.collect(SOURCE, NOW, previous)
        self.assertEqual(len(calls), 4)  # 첫 단지는 하루 전 상세를 다시 씀
        self.assertEqual(bundle['items'][0]['units'], 113)
        self.assertEqual(bundle['items'][1]['checked_at'], NOW.isoformat())

    def test_out_of_range_detail_degrades_only_that_complex(self):
        bad = text('detail_apt.html').replace('65,800', '2,026,000,497')
        fetch, _ = fake_fetch({'2026000497': bad, '2026950090': text('detail_officetel.html')})
        with patch.object(s, 'fetch', fetch):
            bundle = s.collect(SOURCE, NOW)
        apt, office = bundle['items']
        self.assertEqual((apt['detail'], apt['price_max'], apt['units']), ('failed', None, None))
        self.assertEqual(apt['steps'][1]['label'], '1순위')
        self.assertEqual(office['detail'], 'checked')
        self.assertIsNotNone(s.sanitize(bundle, NOW))

    def test_detail_cap_leaves_rest_failed(self):
        fetch, calls = fake_fetch({'2026000497': text('detail_apt.html')})
        with patch.object(s, 'fetch', fetch), patch.object(s, 'MAX_DETAILS', 1):
            bundle = s.collect(SOURCE, NOW)
        self.assertEqual([i['detail'] for i in bundle['items']], ['checked', 'failed'])
        self.assertEqual(len(calls), 4)

    def test_calendar_failure_aborts_so_previous_bundle_stays(self):
        fetch, _ = fake_fetch(calendars={'202611': CALENDAR, '202612': OSError('down')})
        with patch.object(s, 'fetch', fetch), self.assertRaises(OSError):
            s.collect(SOURCE, NOW)

    def test_robots_disallow_stops_collection(self):
        fetch, calls = fake_fetch(robots='User-agent: *\nDisallow: /ai/')
        with patch.object(s, 'fetch', fetch), self.assertRaises(PermissionError):
            s.collect(SOURCE, NOW)
        self.assertEqual(len(calls), 1)

    def test_html_not_found_robots_means_no_rules(self):
        self.assertTrue(allowed('The requested URL was not found on this server.<br><br><br>', s.CALENDAR_URL))


class SanitizeTests(unittest.TestCase):
    def bundle(self):
        cost_policy.reset(s.MAX_REQUESTS)
        fetch, _ = fake_fetch({'2026000497': text('detail_apt.html'), '2026950090': text('detail_officetel.html')})
        with patch.object(s, 'fetch', fetch):
            return s.collect(SOURCE, NOW)

    def test_stale_bundle_is_dropped_unless_allowed(self):
        b = self.bundle()
        later = NOW + timedelta(hours=s.STALE_HOURS, minutes=1)
        self.assertIsNone(s.sanitize(b, later))
        self.assertIsNotNone(s.sanitize(b, later, allow_stale=True))

    def test_items_whose_steps_all_passed_are_dropped_on_read(self):
        b = self.bundle()
        clean = s.sanitize(b, datetime.fromisoformat('2026-11-21T09:00:00+09:00'), allow_stale=True)
        self.assertEqual([i['id'] for i in clean['items']], ['2026950090'])

    def test_rejects_foreign_link_http_link_bad_kind_and_phone_number(self):
        for change in (dict(url='https://evil.example/x'), dict(url='http://www.applyhome.co.kr/x'), dict(kind='land'),
                       dict(name='문의 010-1234-5678'), dict(units=-1), dict(steps=[])):
            b = self.bundle()
            b['items'][0].update(change)
            self.assertIsNone(s.sanitize(b, NOW), change)

    def test_rejects_unknown_keys(self):
        b = self.bundle()
        b['items'][0]['phone'] = '1555-6223'
        self.assertIsNone(s.sanitize(b, NOW))


class PublishTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from benefit_monitor.store import save
        from test_pipeline import benefit, SOURCE as TEST_SOURCE
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        item = benefit().data()
        save(self.root / 'sources.yaml', dict(sources=[TEST_SOURCE], max_age_days=7))
        save(self.root / 'report.json', dict(verified_at=NOW.isoformat(), complete=False, new=[item], needs_recheck=[],
                                             collection=dict(online=True, successful_sources=['test'], successful_districts=0)))
        save(self.root / 'public/verified.json', [dict(item, public_release=True)])
        self.save = save

    def test_export_and_public_snapshot_carry_fresh_bundle_and_drop_tampered_one(self):
        from benefit_monitor import public_snapshot, publish
        self.assertNotIn('subscriptions', publish.run(self.root, now=NOW + timedelta(minutes=5)))
        self.save(self.root / s.FILE, SanitizeTests.bundle(SanitizeTests()))
        data = publish.run(self.root, now=NOW + timedelta(minutes=5))
        self.assertEqual([i['id'] for i in data['subscriptions']['items']], ['2026000497', '2026950090'])
        clean = public_snapshot.validate(self.root, data, NOW + timedelta(minutes=10))
        self.assertEqual(clean['subscriptions'], data['subscriptions'])
        bad = dict(data['subscriptions'], items=[dict(data['subscriptions']['items'][0], url='https://evil.example/')])
        self.assertNotIn('subscriptions', public_snapshot.validate(self.root, dict(data, subscriptions=bad), NOW + timedelta(minutes=10)))

    def test_mirror_restore_keeps_only_a_subscription_bundle(self):
        from benefit_monitor import mirror
        bundle = SanitizeTests.bundle(SanitizeTests())
        with patch.object(mirror, '_get', lambda repo, name, env=None: (bundle, 'sha') if name == s.NAME else (None, None)):
            self.assertTrue(mirror.restore_subscriptions(self.root, 'o/r'))
        self.assertTrue((self.root / s.FILE).exists())
        with patch.object(mirror, '_get', lambda repo, name, env=None: ({'source': 'other'}, 'sha')):
            self.assertFalse(mirror.restore_subscriptions(self.root, 'o/r'))
        self.assertFalse((self.root / s.FILE).exists())

    def test_repository_definition_is_on_the_frontend_allowlist(self):
        from benefit_monitor.store import load
        config = load(ROOT / 'sources.yaml', None)
        source = next(x for x in config['sources'] if x['id'] == 'subscriptions')
        self.assertEqual((source['collector'], source['domains']), ('subscriptions', ['www.applyhome.co.kr']))
        policy = json.loads((ROOT / 'frontend/src/source-policy.json').read_text())
        self.assertIn('www.applyhome.co.kr', json.dumps(policy))


class ProbeTests(unittest.TestCase):
    def test_probe_lists_complexes(self):
        from benefit_monitor import source_registry
        bundle = SanitizeTests.bundle(SanitizeTests())
        seen = []
        with patch.object(s, 'collect', lambda source, now: seen.append(source['id']) or bundle):
            result = source_registry.probe(ROOT, 'subscriptions')
        self.assertEqual(seen, ['subscriptions'])
        self.assertEqual([i['title'] for i in result['items']],
                         ['[서울 중랑구 checked] 2026-11-16 중화역 라온프라이빗 센트로', '[서울 중랑구 checked] 2026-11-25 중화역 라온프라이빗 센트로'])


class FetchPostTests(unittest.TestCase):
    def test_post_body_and_headers_reach_the_request_and_consume_budget(self):
        from benefit_monitor.collectors import rss
        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, n):
                return b'{}'

        class Opener:
            def open(self, request, timeout):
                seen.update(method=request.get_method(), data=request.data, type=request.get_header('Content-type'))
                return Response()

        cost_policy.reset(5)
        with patch.object(rss.urllib.request, 'build_opener', lambda *a: Opener()):
            rss.fetch(s.CALENDAR_URL, ['www.applyhome.co.kr'], data=b'{"a":1}', headers={'Content-Type': 'application/json'})
            self.assertEqual(seen, dict(method='POST', data=b'{"a":1}', type='application/json'))
            rss.fetch('https://www.applyhome.co.kr/x', ['www.applyhome.co.kr'])
            self.assertEqual(seen['method'], 'GET')
        self.assertEqual(cost_policy.budget.used, 2)


if __name__ == '__main__':
    unittest.main()
