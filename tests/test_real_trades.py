import unittest
import unittest.mock
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from benefit_monitor import cost_policy, real_trades as rt

NOW = datetime.fromisoformat('2026-11-17T00:20:00+09:00')
KEY = 'test-key-not-real'
DOMAINS = ['www.applyhome.co.kr', 'apis.data.go.kr']


def item_xml(name, area, amount, y, m, d, own=None, cancel=' '):
    own_tag = f'<ownershipGbn>{own}</ownershipGbn>' if own else ''
    return (f'<item><aptNm>{name}</aptNm><buyerGbn>개인</buyerGbn><cdealType>{cancel}</cdealType>'
            f'<dealAmount>{amount}</dealAmount><dealDay>{d}</dealDay><dealMonth>{m}</dealMonth><dealYear>{y}</dealYear>'
            f'<excluUseAr>{area}</excluUseAr><floor>3</floor>{own_tag}<umdNm>신천동</umdNm></item>')


def response(items, total=None, code='000'):
    return (f'<?xml version="1.0" encoding="UTF-8"?><response><header><resultCode>{code}</resultCode><resultMsg>OK</resultMsg></header>'
            f'<body><items>{"".join(items)}</items><numOfRows>1000</numOfRows><pageNo>1</pageNo>'
            f'<totalCount>{len(items) if total is None else total}</totalCount></body></response>').encode()


SILV_JULY = [item_xml('잠실 래미안아이파크', '84.88', '430,000', 2026, 7, 1, '입'),
             item_xml('잠실래미안아이파크', '84.96', '390,000', 2026, 6, 22, '입', 'O'),  # 해제 거래
             item_xml('잠실 래미안아이파크', '43.73', '238,000', 2026, 6, 25, '입'),
             item_xml('잠실 르엘', '84.83', '440,000', 2026, 7, 20, '입')]


def sub(**over):
    base = dict(id='2026930045', name='잠실 래미안아이파크', area='서울', district='송파구', detail='checked', trade_status='unavailable',
                types=[dict(label='43', area=43.73, pyeong=20, general=1, special=0, price=110548, trade=None),
                       dict(label='59A', area=59.47, pyeong=26, general=1, special=0, price=157939, trade=None),
                       dict(label='84D', area=84.96, pyeong=34, general=0, special=1, price=185607, trade=None)])
    base.update(over)
    return base


def fake_fetch(pages):
    calls = []

    def fetch(url, domains, data=None, headers=None):
        cost_policy.budget.consume()
        q = parse_qs(urlsplit(url).query)
        assert q['serviceKey'] == [KEY]
        api = 'silv' if 'Silv' in url else 'apt'
        key = (api, q['LAWD_CD'][0], q['DEAL_YMD'][0], q['pageNo'][0])
        calls.append(key)
        value = pages.get(key, response([]))
        if isinstance(value, Exception):
            raise value
        return value
    return fetch, calls


class CodeTests(unittest.TestCase):
    def test_district_codes_include_new_gu(self):
        self.assertEqual(rt.lawd('서울', '송파구'), '11710')
        self.assertEqual(rt.lawd('경기', '성남시 분당구'), '41135')
        self.assertEqual(rt.lawd('경기', '화성특례시 효행구'), '41593')
        self.assertEqual(rt.lawd('경기', '부천시 오정구'), '41196')
        self.assertEqual(rt.lawd('경기', '수원특례시 영통구'), '41117')
        self.assertIsNone(rt.lawd('경기', '용인시'))  # 구가 빠지면 정할 수 없다
        self.assertIsNone(rt.lawd('서울', None))

    def test_name_normalization(self):
        self.assertEqual(rt.norm('잠실 래미안아이파크'), rt.norm('잠실래미안아이파크'))
        self.assertEqual(rt.norm('더샵 분당센트로(7차)'), '더샵분당센트로')
        self.assertEqual(rt.norm('용인 양지 서희스타힐스 하이뷰 (조합원 취소분)'), '용인양지서희스타힐스하이뷰')

    def test_twelve_months_back_from_this_month(self):
        months = rt.months(NOW.date())
        self.assertEqual((months[0], months[-1], len(months)), ('202611', '202512', 12))


class ParseTests(unittest.TestCase):
    def test_latest_trade_per_complex_and_area_skipping_cancelled(self):
        total, latest = rt.parse(response(SILV_JULY), 'silv')
        self.assertEqual(total, 4)
        self.assertEqual(latest[rt.norm('잠실 래미안아이파크') + '|84'], [430000, '2026-07-01', '입주권'])
        self.assertEqual(latest[rt.norm('잠실 래미안아이파크') + '|43'], [238000, '2026-06-25', '입주권'])
        self.assertNotIn(rt.norm('잠실 래미안아이파크') + '|84|cancelled', latest)

    def test_apartment_sale_kind(self):
        _, latest = rt.parse(response([item_xml('파크리오', '84.79', '296,000', 2026, 7, 3)]), 'apt')
        self.assertEqual(latest['파크리오|84'], [296000, '2026-07-03', '매매'])

    def test_error_code_raises_without_leaking_anything(self):
        with self.assertRaises(ValueError) as ctx:
            rt.parse(response([], code='30'), 'apt')
        self.assertNotIn(KEY, str(ctx.exception))


class UpdateTests(unittest.TestCase):
    def test_fetches_both_apis_for_twelve_months_once_per_district(self):
        fetch, calls = fake_fetch({('silv', '11710', '202607', '1'): response(SILV_JULY)})
        cache, used = rt.update([sub(), sub(id='2026000001', name='다른 단지')], NOW, None, KEY, DOMAINS, fetch=fetch)
        self.assertEqual(used, 24)  # 같은 구는 한 번만: 2개 API × 12개월
        self.assertEqual(len(calls), 24)
        self.assertEqual(cache['entries']['silv|11710|202607']['latest'][rt.norm('잠실 래미안아이파크') + '|84'][0], 430000)

    def test_old_months_are_reused_and_recent_months_refetched(self):
        fetch, _ = fake_fetch({})
        cache, _ = rt.update([sub()], NOW - timedelta(days=1), None, KEY, DOMAINS, fetch=fetch)
        fetch, calls = fake_fetch({})
        _, used = rt.update([sub()], NOW, cache, KEY, DOMAINS, fetch=fetch)
        # 이번 달·지난달만 다시: 2개 API × 2개월
        self.assertEqual(sorted({c[2] for c in calls}), ['202610', '202611'])
        self.assertEqual(used, 4)

    def test_pages_beyond_first(self):
        fetch, calls = fake_fetch({('apt', '11710', '202611', '1'): response([item_xml('파크리오', '84.79', '296,000', 2026, 11, 3)], total=1500),
                                   ('apt', '11710', '202611', '2'): response([item_xml('파크리오', '84.79', '301,000', 2026, 11, 9)])})
        cache, _ = rt.update([sub()], NOW, None, KEY, DOMAINS, fetch=fetch)
        self.assertIn(('apt', '11710', '202611', '2'), calls)
        self.assertEqual(cache['entries']['apt|11710|202611']['latest']['파크리오|84'][0], 301000)

    def test_budget_cap_stops_and_keeps_previous(self):
        fetch, calls = fake_fetch({})
        with unittest.mock.patch.object(rt, 'MAX_REQUESTS', 5):
            cache, used = rt.update([sub()], NOW, None, KEY, DOMAINS, fetch=fetch)
        self.assertEqual((used, len(calls)), (5, 5))
        self.assertEqual(len(cache['entries']), 5)

    def test_failed_month_keeps_previous_entry_and_error_has_no_key(self):
        fetch, _ = fake_fetch({('silv', '11710', '202611', '1'): response(SILV_JULY)})
        cache, _ = rt.update([sub()], NOW - timedelta(days=1), None, KEY, DOMAINS, fetch=fetch)
        fetch, _ = fake_fetch({('silv', '11710', '202611', '1'): OSError('boom ' + 'https://apis.data.go.kr/?serviceKey=' + KEY)})
        cache2, _ = rt.update([sub()], NOW, cache, KEY, DOMAINS, fetch=fetch)
        self.assertEqual(cache2['entries']['silv|11710|202611']['latest'], cache['entries']['silv|11710|202611']['latest'])
        self.assertNotIn(KEY, repr(cache2))

    def test_no_key_means_no_requests(self):
        fetch, calls = fake_fetch({})
        cache, used = rt.update([sub()], NOW, None, '', DOMAINS, fetch=fetch)
        self.assertEqual((used, calls), (0, []))

    def test_main_budget_is_restored(self):
        cost_policy.reset(50)
        before = cost_policy.budget
        fetch, _ = fake_fetch({})
        rt.update([sub()], NOW, None, KEY, DOMAINS, fetch=fetch)
        self.assertIs(cost_policy.budget, before)
        self.assertEqual(before.used, 0)


class AttachTests(unittest.TestCase):
    def test_same_complex_same_area_latest_trade_goes_on_each_type(self):
        fetch, _ = fake_fetch({('silv', '11710', '202607', '1'): response(SILV_JULY)})
        cache, _ = rt.update([sub()], NOW, None, KEY, DOMAINS, fetch=fetch)
        items = [sub(), sub(id='2026000009', name='없는 단지', district='강동구'), sub(id='2026000010', district=None)]
        rt.attach(items, cache, NOW)
        a = items[0]
        self.assertEqual(a['trade_status'], 'checked')
        self.assertEqual([t['trade'] for t in a['types']], [
            dict(amount=238000, month='2026-06', kind='입주권'), None, dict(amount=430000, month='2026-07', kind='입주권')])
        self.assertEqual(items[1]['trade_status'], 'unavailable')  # 강동구는 이번에 받지 않았다
        self.assertEqual(items[2]['trade_status'], 'unavailable')

    def test_other_complex_with_same_area_is_never_used(self):
        fetch, _ = fake_fetch({('silv', '11710', '202607', '1'): response(SILV_JULY)})
        cache, _ = rt.update([sub()], NOW, None, KEY, DOMAINS, fetch=fetch)
        items = [sub(name='잠실 르엘 아님')]
        rt.attach(items, cache, NOW)
        self.assertEqual([t['trade'] for t in items[0]['types']], [None, None, None])
        self.assertEqual(items[0]['trade_status'], 'checked')


if __name__ == '__main__':
    unittest.main()
