import copy
import json
import unittest
from datetime import date
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

    def test_kamis_monthly_rejects_odd_price_cell(self):
        page = self.rice().replace('>62,411<', '>6x,411<')
        self.assertIsNone(grocery_baselines.parse_kamis_monthly(page, self.TODAY))

    def test_kamis_monthly_none_when_zero_months(self):
        self.assertIsNone(grocery_baselines.parse_kamis_monthly(self.rice(), date(2022, 3, 1)))


class EkapeRangeTests(unittest.TestCase):
    START, END = date(2026, 7, 1), date(2026, 11, 7)

    def page(self):
        return fixture('ekape_range_pork_belly.html')

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


if __name__ == '__main__':
    unittest.main()
