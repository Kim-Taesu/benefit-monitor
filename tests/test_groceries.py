import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import cost_policy, groceries

NOW = datetime.fromisoformat('2026-11-09T00:40:00+09:00')
SOURCE = dict(id='groceries', domains=['www.kamis.or.kr', 'www.ekapepia.com'], collector='grocery_prices',
              lookback_days=5, cuts=[dict(species='4304', part='27', name='돼지 삼겹살'),
                                     dict(species='4301', part='22', name='한우 등심')])

HEAD = ('<tr><th>품목</th><th>품종</th><th>단위</th><th>등급</th><th>당일 (11/06)</th><th>1일전 (11/05)</th>'
        '<th>1주일전 (10/30)</th><th>2주일전 (10/23)</th><th>1년전</th><th>평년</th></tr>')


def kamis_row(item, kind, unit, grade, *values):
    return ('<tr><th scope="row">%s</th><th>%s</th><th>%s</th><th>%s</th>' % (item, kind, unit, grade)
            + ''.join('<td>%s</td>' % v for v in values) + '</tr>')


def kamis_page(rows, date='2026.11.06'):
    return ('<html><h4 class="md_tit"> 전체 <span class="txt_date">%s 기준</span></h4>'
            '<table class="tbl col" id="itemTable_1" summary="소매가격전체부류별/일간 가격정보"><thead>%s</thead>'
            '<tbody>%s</tbody></table></html>' % (date, HEAD, ''.join(rows))).encode()


ONION = kamis_row('양파', '양파', '1kg', '상품', '1,893', '2,050', '1,890', '2,165', '2,008', '2,088')
REGIONS = ['서울', '부산', '대구', '인천', '전남광주', '대전', '울산', '세종', '경기', '강원', '충북', '충남', '전북', '경북', '경남', '제주']


def meat_page(rows, unit='원/100g', day='2026-11-08'):
    head = '<tr><th>부위/규격</th>' + ''.join('<th data-col="x">%s</th>' % r for r in REGIONS) + '<th>전국 평균</th></tr>'
    body = ''.join('<tr><td>%s</td>%s<td>%s</td></tr>' % (label, ''.join('<td>%s</td>' % v for v in vals), nat)
                   for label, vals, nat in rows)
    return ('<html><input type="text" id="searchStartDate" value="%s"" class="datepicker">' % day
            + '<h3>지역별 소비자가격 평균 <small>(단위 : %s)</small></h3>'
            '<table id="table-type1" class="table-type1 small" summary="지역별 소비자가격 평균 테이블">'
            '<thead>%s</thead><tbody>%s</tbody></table></html>' % (unit, head, body)).encode()


PORK = meat_page([('삼겹살', ['2,866', '2,639', '2,630', '2,970', '2,772', '2,758', '2,894', '2,722', '2,814', '2,721',
                              '2,887', '2,724', '2,979', '2,713', '2,598', '2,850'], '2,768')])
BEEF_ROWS = [('등심 1++등급', ['13,000'] * 15 + ['-'], '12,900'),
                  ('근내 지방도', ['7'] + ['1'] * 16, '1'),  # 19-cell sub row with a leading label cell
                  ('8', ['1'] * 16, '1'),  # following sub rows have 18 cells like a main row
                  ('등심 1등급', ['9,000'] * 16, '8,800'),
                  ('등심 1등급', ['9,500'] * 16, '9,300')]  # repeated label: first row wins
BEEF = meat_page(BEEF_ROWS)


class ParseTests(unittest.TestCase):
    def test_kamis_rows_keep_today_year_ago_and_normal(self):
        page = kamis_page([ONION, kamis_row('수박', '수박', '1개', '상품', '-', '-', '-', '-', '25,000', '24,000'),
                           kamis_row('쌀', '20kg', '20kg', '상품', '63,289', '63,298', '-', '63,042', '64,926', '55,692')])
        survey, items = groceries.parse_kamis(page.decode())
        self.assertEqual(survey, '2026-11-06')
        onion = items[0]
        self.assertEqual((onion['item'], onion['kind'], onion['unit'], onion['grade']), ('양파', '양파', '1kg', '상품'))
        self.assertEqual((onion['today'], onion['year_ago'], onion['normal']), (1893, 2008, 2088))
        self.assertEqual(onion['id'], '양파|양파|1kg|상품')
        # Rows with no current price (out of season) are dropped; missing cells stay None, never 0.
        self.assertEqual([i['item'] for i in items], ['양파', '쌀'])
        self.assertIsNone(items[1]['week_ago'])

    def test_kamis_rejects_pages_without_a_dated_table(self):
        self.assertEqual(groceries.parse_kamis('<html>조사 없음</html>'), (None, []))
        bad = kamis_page([kamis_row('양파', '양파', '1kg', '상품', '1,893원', '-', '-', '-', '-', '-')])
        self.assertEqual(groceries.parse_kamis(bad.decode())[1], [])

    def test_meat_rows_national_average_and_regional_range(self):
        items = groceries.parse_meat(PORK.decode(), dict(species='4304', part='27', name='돼지 삼겹살'))
        self.assertEqual(len(items), 1)
        pork = items[0]
        self.assertEqual((pork['cut'], pork['label'], pork['unit']), ('돼지 삼겹살', '삼겹살', '원/100g'))
        self.assertEqual((pork['national'], pork['seoul']), (2768, 2866))
        self.assertEqual((pork['min'], pork['min_region'], pork['max'], pork['max_region']), (2598, '경남', 2979, '전북'))

    def test_meat_skips_marbling_sub_rows_and_handles_missing_regions(self):
        items = groceries.parse_meat(BEEF.decode(), dict(species='4301', part='22', name='한우 등심'))
        self.assertEqual([i['label'] for i in items], ['등심 1++등급', '등심 1등급'])
        self.assertEqual((items[0]['max_region'], items[0]['national']), ('서울', 12900))


class MoreParseTests(unittest.TestCase):
    def test_meat_page_must_echo_the_requested_day(self):
        cut = dict(species='4304', part='27', name='돼지 삼겹살')
        self.assertEqual(groceries.parse_meat(PORK.decode(), cut, '2026-11-07'), [])
        self.assertEqual(len(groceries.parse_meat(PORK.decode(), cut, '2026-11-08')), 1)

    def test_grade_cells_follow_the_same_text_rule_as_other_fields(self):
        page = kamis_page([kamis_row('양파', '양파', '1kg', '&lt;상&gt;', '1,893', '-', '-', '-', '-', '-')])
        self.assertEqual(groceries.parse_kamis(page.decode())[1], [])


class CollectTests(unittest.TestCase):
    def fetches(self, kamis_pages, meat_pages):
        calls = []
        def fetch(url, domains):
            calls.append(url)
            if url.endswith('/robots.txt'):
                return b'User-agent: Googlebot\nDisallow: /customer/common/search.do\n'
            if 'kamis' in url:
                return kamis_pages.pop(0)
            return meat_pages.pop(0)
        return calls, fetch

    def test_collect_backs_off_to_last_survey_day_and_reads_each_cut(self):
        cost_policy.reset(30)
        calls, fetch = self.fetches([b'<html></html>', b'<html></html>', kamis_page([ONION])], [PORK, BEEF])
        with patch.object(groceries, 'fetch', side_effect=fetch):
            bundle = groceries.collect(SOURCE, NOW)
        kamis = [c for c in calls if 'catalogue.do' in c]
        self.assertEqual([c.split('regday=')[1][:10] for c in kamis], ['2026-11-08', '2026-11-07', '2026-11-06'])
        self.assertEqual(bundle['produce']['survey_date'], '2026-11-06')
        self.assertEqual([i['cut'] for i in bundle['meat']['items']], ['돼지 삼겹살', '한우 등심', '한우 등심'])
        self.assertEqual(bundle['meat']['missing'], [])
        self.assertEqual(groceries.sanitize(bundle, NOW)['produce'], bundle['produce'])

    def test_collect_keeps_partial_meat_and_names_the_missing_cut(self):
        cost_policy.reset(30)
        calls, fetch = self.fetches([kamis_page([ONION])], [PORK, b'<html>no table</html>'])
        with patch.object(groceries, 'fetch', side_effect=fetch):
            bundle = groceries.collect(SOURCE, NOW)
        self.assertEqual(bundle['meat']['missing'], ['한우 등심'])
        self.assertEqual(len(bundle['meat']['items']), 1)

    def test_collect_stops_at_budget_and_reports_missing_cuts(self):
        cost_policy.reset(4)  # robots x2 + kamis + one cut
        calls, fetch = self.fetches([kamis_page([ONION])], [PORK, BEEF])
        def guarded(url, domains):
            cost_policy.budget.consume()
            return fetch(url, domains)
        with patch.object(groceries, 'fetch', side_effect=guarded):
            bundle = groceries.collect(SOURCE, NOW)
        self.assertEqual(bundle['meat']['missing'], ['한우 등심'])

    def test_collect_refuses_when_robots_disallows(self):
        cost_policy.reset(10)
        with patch.object(groceries, 'fetch', return_value=b'User-agent: *\nDisallow: /\n'):
            with self.assertRaises(ValueError):
                groceries.collect(SOURCE, NOW)

    def test_collect_fails_when_nothing_was_read(self):
        cost_policy.reset(30)
        calls, fetch = self.fetches([b'<html></html>'] * 5, [b'x', b'x'])
        with patch.object(groceries, 'fetch', side_effect=fetch):
            with self.assertRaises(ValueError):
                groceries.collect(SOURCE, NOW)


class SanitizeTests(unittest.TestCase):
    def bundle(self):
        cost_policy.reset(30)
        pages = [kamis_page([ONION])]
        meats = [PORK, BEEF]
        def fetch(url, domains):
            if url.endswith('/robots.txt'):
                return b''
            return pages.pop(0) if 'kamis' in url else meats.pop(0)
        with patch.object(groceries, 'fetch', side_effect=fetch):
            return groceries.collect(SOURCE, NOW)

    def test_rejects_stale_or_tampered_bundles(self):
        bundle = self.bundle()
        self.assertEqual(groceries.sanitize(bundle, NOW)['notice'], groceries.NOTICE)
        self.assertIsNone(groceries.sanitize(bundle, NOW + timedelta(hours=31)))
        self.assertIsNone(groceries.sanitize(dict(bundle, source='other'), NOW))
        onion = bundle['produce']['items'][0]
        for change in (dict(today=-5), dict(today='1893'), dict(normal=True), dict(item='<b>'*40), dict(extra=1),
                       dict(id='other')):
            produce = dict(bundle['produce'], items=[dict(onion, **change)])
            self.assertIsNone(groceries.sanitize(dict(bundle, produce=produce), NOW), change)
        pork = bundle['meat']['items'][0]
        for change in (dict(min_region='평양'), dict(national=0), dict(unit='원/근')):
            meat = dict(bundle['meat'], items=[dict(pork, **change)])
            self.assertIsNone(groceries.sanitize(dict(bundle, meat=meat), NOW), change)

    def test_old_survey_dates_are_dropped_per_section(self):
        bundle = self.bundle()
        old = dict(bundle, produce=dict(bundle['produce'], survey_date='2026-10-20'))
        clean = groceries.sanitize(old, NOW)
        self.assertIsNone(clean['produce'])
        self.assertIsNotNone(clean['meat'])

    def test_publish_attaches_sanitized_bundle(self):
        from benefit_monitor import publish
        from benefit_monitor.store import save
        bundle = self.bundle()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            save(root/'cache/groceries.json', bundle)
            data = {}
            publish.attach_groceries(root, data, NOW)
            self.assertEqual(data['groceries']['produce'], bundle['produce'])
            save(root/'cache/groceries.json', dict(bundle, schema_version=9))
            data = {}
            publish.attach_groceries(root, data, NOW)
            self.assertNotIn('groceries', data)


if __name__ == '__main__':
    unittest.main()


class ResilienceTests(unittest.TestCase):
    def test_kamis_http_error_keeps_meat(self):
        import urllib.error
        cost_policy.reset(30)
        meats = [PORK, BEEF]
        def fetch(url, domains):
            if url.endswith('/robots.txt'):
                return b''
            if 'kamis' in url:
                raise urllib.error.HTTPError(url, 500, 'err', {}, None)
            return meats.pop(0)
        with patch.object(groceries, 'fetch', side_effect=fetch):
            bundle = groceries.collect(SOURCE, NOW)
        self.assertIsNone(bundle['produce'])
        self.assertEqual(len(bundle['meat']['items']), 3)

    def test_ekape_robots_failure_keeps_produce(self):
        cost_policy.reset(30)
        def fetch(url, domains):
            if 'ekapepia' in url:
                raise OSError('down')
            return b'' if url.endswith('/robots.txt') else kamis_page([ONION])
        with patch.object(groceries, 'fetch', side_effect=fetch):
            bundle = groceries.collect(SOURCE, NOW)
        self.assertIsNone(bundle['meat'])
        self.assertEqual(len(bundle['produce']['items']), 1)

    def test_meat_steps_back_when_yesterday_has_no_survey(self):
        cost_policy.reset(30)
        calls = []
        def fetch(url, domains):
            calls.append(url)
            if url.endswith('/robots.txt'):
                return b''
            if 'kamis' in url:
                return kamis_page([ONION])
            day = url.split('searchStartDate=')[1][:10]
            empty = meat_page([('삼겹살', ['-'] * 16, '-')], day=day)
            if day == '2026-11-08':
                return empty
            return meat_page([('삼겹살', ['2,700'] * 16, '2,700')], day=day) if 'searchCondition1=4304' in url \
                else meat_page(BEEF_ROWS, day=day)
        with patch.object(groceries, 'fetch', side_effect=fetch):
            bundle = groceries.collect(SOURCE, NOW)
        self.assertEqual(bundle['meat']['survey_date'], '2026-11-07')
        self.assertEqual(bundle['meat']['missing'], [])
        meat_days = [c.split('searchStartDate=')[1][:10] for c in calls if 'regionAvgPrice' in c]
        self.assertEqual(meat_days, ['2026-11-08', '2026-11-07', '2026-11-07'])
