import copy
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from collections import Counter
from pathlib import Path

from benefit_monitor import grocery_baselines, groceries

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'tests' / 'fixtures' / 'grocery_baselines'


def repo_source():
    return json.loads((ROOT / 'sources' / 'groceries.json').read_text(encoding='utf-8'))['collect']


class BasketTests(unittest.TestCase):
    def test_basket_accepts_repo_config(self):
        items = grocery_baselines.basket(repo_source())
        self.assertEqual(len(items), 25)
        groups = Counter(i['group'] for i in items)
        self.assertEqual((groups['고기·알'], groups['채소'], groups['기타']), (7, 12, 6))
        for item in items:
            self.assertEqual(len({'kamis', 'ekape'} & item.keys()), 1)

    def test_basket_required_aliases(self):
        by_id = {i['id']: i for i in grocery_baselines.basket(repo_source())}
        self.assertTrue({'계란', '달걀'} <= set(by_id['egg_tray']['aliases']))
        self.assertTrue({'대파', '파'} <= set(by_id['green_onion']['aliases']))
        self.assertTrue({'애호박', '호박'} <= set(by_id['zucchini']['aliases']))
        self.assertTrue({'오징어', '물오징어'} <= set(by_id['squid']['aliases']))
        self.assertTrue({'한우', '등심', '소고기'} <= set(by_id['hanwoo_sirloin']['aliases']))
        self.assertTrue({'갈비살', '소갈비살'} <= set(by_id['us_short_rib']['aliases']))
        self.assertTrue({'닭', '생닭', '닭고기'} <= set(by_id['chicken']['aliases']))

    def test_basket_rejects_duplicate_id(self):
        source = copy.deepcopy(repo_source())
        source['basket'][1]['id'] = source['basket'][0]['id']
        with self.assertRaises(ValueError):
            grocery_baselines.basket(source)

    def test_basket_rejects_both_kamis_and_ekape(self):
        source = copy.deepcopy(repo_source())
        source['basket'][0]['kamis'] = copy.deepcopy(source['basket'][-1]['kamis'])
        with self.assertRaises(ValueError):
            grocery_baselines.basket(source)

    def test_basket_rejects_26_items(self):
        source = copy.deepcopy(repo_source())
        extra = copy.deepcopy(source['basket'][0])
        extra['id'] = 'extra_item'
        source['basket'].append(extra)
        with self.assertRaises(ValueError):
            grocery_baselines.basket(source)

    def test_basket_rejects_bad_fields(self):
        for mutate in (lambda i: i.update(id='Bad1'), lambda i: i.update(aliases=[]),
                       lambda i: i.update(aliases=['a'] * 6), lambda i: i.update(group='과일'),
                       lambda i: i['row'].update(kind='fish'), lambda i: i.update(extra=1)):
            source = copy.deepcopy(repo_source())
            mutate(source['basket'][0])
            with self.assertRaises(ValueError):
                grocery_baselines.basket(source)

    def test_basket_rows_exist_in_fixture_bundle(self):
        ids = set(json.loads((FIXTURES / 'row_ids.json').read_text(encoding='utf-8'))['ids'])
        for item in grocery_baselines.basket(repo_source()):
            self.assertIn(item['row']['id'], ids)

    def test_meat_row_matches_ekape_code_and_label(self):
        for item in grocery_baselines.basket(repo_source()):
            if 'ekape' in item:
                e = item['ekape']
                self.assertEqual(item['row'], {'kind': 'meat', 'id': '%s-%s-%s' % (e['species'], e['part'], e['label'])})
            else:
                self.assertEqual(item['row']['kind'], 'produce')

class PeriodFixtureTests(unittest.TestCase):
    # kamis_monthly_*.html (쌀, 감자, 고등어 월별 표 발췌)는 Task 2의 월별 파서가 쓴다.
    CUT = dict(species='4304', part='27', name='돼지 삼겹살')

    def national(self, name, day=None):
        page = (FIXTURES / name).read_text(encoding='utf-8')
        rows = groceries.parse_meat(page, self.CUT, day)
        self.assertEqual([r['label'] for r in rows], ['삼겹살'])
        return rows[0]['national']

    def test_ekape_range_equals_calendar_day_mean(self):
        days = ['2026-11-08', '2026-11-07', '2026-11-06']
        daily = [self.national('ekape_day_pork_belly_%s.html' % d, d) for d in days]
        self.assertEqual(daily, [2768, 2768, 2716])
        ranged = self.national('ekape_range_pork_belly.html')
        self.assertLessEqual(abs(ranged - round(sum(daily) / len(daily))), 1)
        self.assertEqual(ranged, 2751)


def fixture(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


def blank(page, *values):
    for v in values:
        assert page.count('>%s<' % v) == 1, v
        page = page.replace('>%s<' % v, '>-<')
    return page


class KamisMonthlyTests(unittest.TestCase):
    TODAY = date(2026, 11, 10)
    # 2025-11 ~ 2026-10 of the rice fixture (2025 column Nov/Dec, 2026 column Jan~Oct)
    RICE = [63797, 62384, 63034, 62923, 62802, 62516, 62411, 62387, 61458, 61411, 61528, 63706]

    def rice(self):
        return fixture('kamis_monthly_rice.html')

    def test_kamis_monthly_rice_last_12_complete_months(self):
        got = grocery_baselines.parse_kamis_monthly(self.rice(), self.TODAY)
        self.assertEqual(got, {'avg': round(sum(self.RICE) / 12), 'months': 12, 'from': '2025-11', 'to': '2026-10',
                               'unit': '20kg', 'kind': '전체(쌀20KG)', 'grade': '상품'})

    def test_kamis_monthly_page_text_unit_kind_grade(self):
        got = grocery_baselines.parse_kamis_monthly(fixture('kamis_monthly_potato0.html'), self.TODAY)
        self.assertEqual((got['unit'], got['kind'], got['grade'], got['months']), ('100g', '수미(노지)', '상품', 12))
        got = grocery_baselines.parse_kamis_monthly(fixture('kamis_monthly_mackerel0.html'), self.TODAY)
        self.assertEqual((got['unit'], got['kind'], got['grade'], got['months']), ('1마리', '국산(신선 냉장)', '大', 12))
        self.assertEqual(got['avg'], round(sum([4554, 4478, 4477, 4657, 4541, 4505, 4824, 4604, 4488, 4396, 4254, 4283]) / 12))

    def test_kamis_monthly_skips_dash_months(self):
        page = blank(self.rice(), '62,387', '62,384')  # 2026-06 and 2025-12
        got = grocery_baselines.parse_kamis_monthly(page, self.TODAY)
        rest = [v for v in self.RICE if v not in (62387, 62384)]
        self.assertEqual((got['months'], got['from'], got['to'], got['avg']),
                         (10, '2025-11', '2026-10', round(sum(rest) / 10)))
        got = grocery_baselines.parse_kamis_monthly(blank(self.rice(), '63,797', '62,384'), self.TODAY)
        self.assertEqual((got['months'], got['from']), (10, '2026-01'))

    def test_kamis_monthly_excludes_current_month(self):
        # the fixture holds 2026-11 = 63,503; it must never enter the average
        got = grocery_baselines.parse_kamis_monthly(self.rice(), self.TODAY)
        self.assertEqual(got['to'], '2026-10')
        self.assertNotEqual(got['avg'], round((sum(self.RICE) - 63797 + 63503) / 12))
        # in January the window is the previous calendar year
        got = grocery_baselines.parse_kamis_monthly(self.rice(), date(2026, 1, 5))
        self.assertEqual((got['from'], got['to'], got['months']), ('2025-01', '2025-12', 12))

    def test_kamis_monthly_rejects_changed_header(self):
        page = self.rice().replace('구분', '항목', 1)
        self.assertIsNone(grocery_baselines.parse_kamis_monthly(page, self.TODAY))
        self.assertIsNone(grocery_baselines.parse_kamis_monthly('<html></html>', self.TODAY))

    def test_kamis_monthly_none_without_year_columns(self):
        page = self.rice()
        for y in ('2026', '2025', '2024', '2023'):
            page = page.replace('>%s년<' % y, '>%s분기<' % y)
        self.assertIsNone(grocery_baselines.parse_kamis_monthly(page, self.TODAY))

    def test_kamis_monthly_rejects_odd_price_cell(self):
        page = self.rice().replace('>62,411<', '>6x,411<')
        self.assertIsNone(grocery_baselines.parse_kamis_monthly(page, self.TODAY))

    def test_kamis_monthly_none_when_zero_months(self):
        self.assertIsNone(grocery_baselines.parse_kamis_monthly(self.rice(), date(2022, 3, 1)))


class EkapeRangeTests(unittest.TestCase):
    START, END = date(2026, 7, 1), date(2026, 11, 7)

    def page(self, start='2026-07-01', end='2026-11-07'):
        return (fixture('ekape_range_pork_belly.html').replace('value="2026-11-06"', 'value="%s"' % start)
                .replace('value="2026-11-08"', 'value="%s"' % end))

    def test_ekape_range_rejects_echoed_date_mismatch(self):
        raw = fixture('ekape_range_pork_belly.html')  # echoes 11-06..11-08, not the asked range
        self.assertIsNone(grocery_baselines.parse_ekape_range(raw, '삼겹살', self.START, self.END))
        for page in (self.page(start='2026-07-02'), self.page(end='2026-11-06'),
                     self.page().replace('id="searchEndDate"', 'id="other"')):
            self.assertIsNone(grocery_baselines.parse_ekape_range(page, '삼겹살', self.START, self.END))

    def test_ekape_range_national_average(self):
        got = grocery_baselines.parse_ekape_range(self.page(), '삼겹살', self.START, self.END)
        self.assertEqual(got, {'avg': 2751, 'months': 4, 'from': '2026-07', 'to': '2026-11', 'unit': '원/100g',
                               'kind': None, 'grade': None})

    def test_ekape_range_missing_label_none(self):
        self.assertIsNone(grocery_baselines.parse_ekape_range(self.page(), '삼겹살 1등급', self.START, self.END))

    def test_ekape_range_rejects_short_range(self):
        self.assertIsNone(grocery_baselines.parse_ekape_range(self.page(), '삼겹살', self.END, self.END))

    def test_ekape_range_reuses_price_guard(self):
        page = self.page()
        national = '2,751'
        self.assertIn(national, page)
        for bad in ('10,000,001', '27x1'):
            self.assertIsNone(grocery_baselines.parse_ekape_range(page.replace(national, bad), '삼겹살', self.START, self.END))


KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 10, 9, 0, tzinfo=KST)
ROBOTS = b'User-agent: *\nAllow: /\n'


class FakeWeb:
    """Routes collect()'s requests to fixtures and records every URL."""

    def __init__(self, survey_days=None, fail=None, exhaust_after=None, kamis_page=None):
        self.urls, self.fail, self.exhaust_after = [], fail or {}, exhaust_after
        self.survey_days = survey_days  # ISO end dates that have a page; None = all
        self.kamis_page = kamis_page or {}

    def __call__(self, url, domains):
        if self.exhaust_after is not None and len(self.urls) >= self.exhaust_after:
            raise RuntimeError('Public HTTP request budget exhausted; stop until next run')
        self.urls.append(url)
        if url.endswith('/robots.txt'):
            return ROBOTS
        query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        if 'itemcode' in query:
            code = query['itemcode']
            if code in self.fail:
                raise self.fail[code]
            if code in self.kamis_page:
                return self.kamis_page[code].encode('utf-8')
            name = {'111': 'kamis_monthly_rice.html', '152': 'kamis_monthly_potato0.html',
                    '611': 'kamis_monthly_mackerel0.html'}.get(code)
            return fixture(name).encode('utf-8') if name else b'<html></html>'
        start, end = query['searchStartDate'], query['searchEndDate']
        if self.survey_days is not None and end not in self.survey_days:
            return b'<html></html>'
        page = (fixture('ekape_range_pork_belly.html').replace('value="2026-11-06"', 'value="%s"' % start)
                .replace('value="2026-11-08"', 'value="%s"' % end))
        return page.encode('utf-8')

    def items(self):
        return [u for u in self.urls if not u.endswith('/robots.txt')]


def run_collect(web, previous=None, now=NOW):
    with mock.patch.object(groceries, 'fetch', web):
        return grocery_baselines.collect(repo_source(), now, previous)


def by_id(bundle):
    return {i['id']: i for i in bundle['items']}


def good(avg=100, checked_at='2026-11-01'):
    return {'avg': avg, 'months': 12, 'from': '2025-10', 'to': '2026-09', 'unit': '1kg', 'kind': None,
            'grade': None, 'checked_at': checked_at}


def previous_bundle(baseline):
    items = [dict(i, baseline=dict(baseline) if baseline else None)
             for i in run_collect(FakeWeb())['items']]
    return {'schema_version': 1, 'source': 'grocery_baselines', 'fetched_at': NOW.isoformat(), 'items': items}


class CollectTests(unittest.TestCase):
    def test_collect_one_request_per_item_plus_robots(self):
        web = FakeWeb()
        bundle = run_collect(web)
        robots = [u for u in web.urls if u.endswith('/robots.txt')]
        self.assertEqual(len(robots), 2)
        self.assertEqual(len(web.items()), 25)  # survey day found on the first try: no extra requests
        self.assertLessEqual(len(web.urls), 29)
        self.assertLessEqual(len(web.urls), grocery_baselines.MAX_REQUESTS)
        self.assertEqual(len(bundle['items']), 25)
        self.assertEqual(bundle['source'], 'grocery_baselines')
        self.assertEqual(bundle['schema_version'], 1)
        self.assertIsNotNone(grocery_baselines.sanitize(bundle, NOW))

    def test_collect_values_and_checked_at(self):
        got = by_id(run_collect(FakeWeb()))
        rice = got['rice']['baseline']
        self.assertEqual((rice['months'], rice['unit'], rice['checked_at']), (12, '20kg', '2026-11-10'))
        self.assertEqual(got['pork_belly']['baseline']['avg'], 2751)
        self.assertEqual(got['pork_belly']['baseline']['to'], '2026-11')
        self.assertIsNone(got['tofu']['baseline'])  # page without a table: None, no crash
        # checked_at is the KST date even when now is given in UTC
        utc = datetime(2026, 11, 9, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(by_id(run_collect(FakeWeb(), now=utc))['rice']['baseline']['checked_at'], '2026-11-10')

    def test_collect_urls(self):
        web = FakeWeb()
        run_collect(web)
        kamis = [u for u in web.items() if 'itemcode=111' in u][0]
        for part in ('action=monthly', 'yyyy=2026', 'period=3', 'convert_kg_yn=N', 'itemcategorycode=100',
                     'kindcode=EE', 'productrankcode=0'):
            self.assertIn(part, kamis)
        ekape = [u for u in web.items() if 'searchStartDate' in u][0]
        for part in ('searchStartDate=2026-07-01', 'searchEndDate=2026-11-09', 'searchCondition1=4304',
                     'searchCondition2=27'):
            self.assertIn(part, ekape)

    def test_collect_survey_day_lookback_is_found_once(self):
        web = FakeWeb(survey_days={'2026-11-07'})
        bundle = run_collect(web)
        ekape = [u for u in web.items() if 'searchStartDate' in u]
        self.assertEqual(len(ekape), 7 + 2)  # two empty days for the first item, then one request per item
        self.assertEqual(sum('searchEndDate=2026-11-07' in u for u in ekape), 7)
        self.assertLessEqual(len(web.urls), 29)
        self.assertEqual(by_id(bundle)['pork_belly']['baseline']['to'], '2026-11')

    def test_collect_no_survey_day_keeps_previous_meat(self):
        previous = previous_bundle(good())
        web = FakeWeb(survey_days=set())
        got = by_id(run_collect(web, previous))
        self.assertEqual(len([u for u in web.items() if 'searchStartDate' in u]), 3)
        self.assertEqual(got['pork_belly']['baseline'], good())
        self.assertEqual(got['chicken']['baseline'], good())

    def test_collect_keeps_previous_on_item_failure(self):
        previous = previous_bundle(good())
        web = FakeWeb(fail={'111': OSError('boom')})
        got = by_id(run_collect(web, previous))
        self.assertEqual(got['rice']['baseline'], good())  # previous value and previous checked_at
        self.assertEqual(got['potato']['baseline']['checked_at'], '2026-11-10')

    def test_collect_robots_disallow_raises(self):
        def web(url, domains):
            if url.endswith('/robots.txt'):
                return b'User-agent: *\nDisallow: /\n'
            raise AssertionError('no item request after robots refusal')
        with mock.patch.object(groceries, 'fetch', web):
            with self.assertRaises(ValueError):
                grocery_baselines.collect(repo_source(), NOW, None)

    def test_collect_stops_at_budget_keeps_previous(self):
        previous = previous_bundle(good())
        web = FakeWeb(exhaust_after=2 + 5)  # robots 2 + five item requests
        got = by_id(run_collect(web, previous))
        self.assertEqual(len(web.items()), 5)
        self.assertEqual(got['rice']['baseline'], good())  # a later item: previous kept
        self.assertEqual(got['pork_belly']['baseline']['avg'], 2751)  # meat came first in the basket
        self.assertEqual(got['tofu']['baseline'], good())

    def test_collect_unit_mismatch_is_none_not_previous(self):
        previous = previous_bundle(good())
        wrong = fixture('kamis_monthly_rice.html').replace('단위 : 20kg', '단위 : 10kg')
        self.assertNotEqual(wrong, fixture('kamis_monthly_rice.html'))
        got = by_id(run_collect(FakeWeb(kamis_page={'111': wrong}), previous))
        self.assertIsNone(got['rice']['baseline'])

    def test_collect_row_match_accepts_rice_kind_containing_unit(self):
        got = by_id(run_collect(FakeWeb()))['rice']['baseline']
        self.assertEqual(got['kind'], '전체(쌀20KG)')  # row kind '20kg' is contained after lowercasing

    def test_collect_grade_mismatch_is_none(self):
        wrong = fixture('kamis_monthly_rice.html').replace('등급 : 상품', '등급 : 중품')
        self.assertNotEqual(wrong, fixture('kamis_monthly_rice.html'))
        got = by_id(run_collect(FakeWeb(kamis_page={'111': wrong})))
        self.assertIsNone(got['rice']['baseline'])

    def test_collect_request_cap(self):
        web = FakeWeb()
        with mock.patch.object(grocery_baselines, 'MAX_REQUESTS', 10):
            bundle = run_collect(web)
        self.assertLessEqual(len(web.urls), 10)
        self.assertEqual(len(bundle['items']), 25)


class SanitizeTests(unittest.TestCase):
    def bundle(self, baseline=None):
        return previous_bundle(baseline or good())

    def test_sanitize_accepts_fresh_bundle(self):
        got = grocery_baselines.sanitize(self.bundle(), NOW)
        self.assertEqual(got['items'][0]['baseline'], good())

    def test_sanitize_drops_baseline_older_than_30_days(self):
        old = good(checked_at=(NOW.date() - timedelta(days=31)).isoformat())
        edge = good(checked_at=(NOW.date() - timedelta(days=30)).isoformat())
        self.assertTrue(all(i['baseline'] is None for i in grocery_baselines.sanitize(self.bundle(old), NOW)['items']))
        self.assertTrue(all(i['baseline'] == edge for i in grocery_baselines.sanitize(self.bundle(edge), NOW)['items']))

    def test_sanitize_rejects_unknown_keys_and_bad_types(self):
        def mutations():
            yield lambda b: b.update(extra=1)
            yield lambda b: b['items'][0].update(extra=1)
            yield lambda b: b['items'][0]['baseline'].update(extra=1)
            yield lambda b: b['items'][0]['baseline'].update(avg='100')
            yield lambda b: b['items'][0]['baseline'].update(avg=True)
            yield lambda b: b['items'][0]['baseline'].update(months=13)
            yield lambda b: b['items'][0]['baseline'].update(checked_at='yesterday')
            yield lambda b: b['items'][0]['baseline'].update(**{'from': '2026-13'})
            yield lambda b: b['items'][0].update(group='과일')
            yield lambda b: b['items'][0]['row'].update(kind='fish')
            yield lambda b: b['items'][0].update(aliases='쌀')
            yield lambda b: b.update(items=b['items'] + [dict(b['items'][0], id='extra_item')] * 1 + b['items'])
            yield lambda b: b.update(fetched_at='nope')
        for mutate in mutations():
            bundle = self.bundle()
            mutate(bundle)
            self.assertIsNone(grocery_baselines.sanitize(bundle, NOW))

    def test_sanitize_none_for_wrong_schema(self):
        for bad in (None, [], 'x', {}, dict(self.bundle(), schema_version=2), dict(self.bundle(), source='groceries')):
            self.assertIsNone(grocery_baselines.sanitize(bad, NOW))


if __name__ == '__main__':
    unittest.main()


class MainTests(unittest.TestCase):
    def run_main(self, get, put, bundle):
        import shutil
        import tempfile
        from benefit_monitor import mirror
        with tempfile.TemporaryDirectory() as directory:
            shutil.copy(ROOT / 'sources.yaml', directory)
            with mock.patch.object(mirror, '_get', side_effect=get) as g, mock.patch.object(mirror, '_put', side_effect=put) as p, \
                    mock.patch.object(grocery_baselines, 'collect', return_value=bundle) as c:
                code = grocery_baselines.main(['--repository', 'o/r', '--root', directory], now=NOW)
        return code, g, p, c

    def test_main_reads_previous_and_puts_result(self):
        prev = previous_bundle(good())
        bundle = previous_bundle(good())
        code, g, p, c = self.run_main([(prev, 'sha1')], [True], bundle)
        self.assertEqual(code, 0)
        self.assertEqual(c.call_args[0][2], prev)
        self.assertEqual(c.call_args[0][0]['id'], 'groceries')
        self.assertEqual(p.call_args[0][:2], ('o/r', 'grocery-baselines.json'))
        self.assertEqual(p.call_args[0][3], 'sha1')
        self.assertEqual(p.call_args[0][2]['source'], 'grocery_baselines')

    def test_main_retries_once_on_stale_sha_then_fails(self):
        bundle = previous_bundle(good())
        code, g, p, c = self.run_main([(None, None), (None, 'sha2'), (None, 'sha3')], [False, True], bundle)
        self.assertEqual(code, 0)
        self.assertEqual(p.call_args_list[1][0][3], 'sha2')
        self.assertEqual(c.call_count, 1)
        code, g, p, c = self.run_main([(None, 's1'), (None, 's2'), (None, 's3')], [False, False, True], bundle)
        self.assertEqual(code, 1)
        self.assertEqual(p.call_count, 2)

    def test_main_skips_put_when_sanitize_fails(self):
        code, g, p, c = self.run_main([(None, None)], [True], {'schema_version': 2})
        self.assertEqual(code, 1)
        p.assert_not_called()
