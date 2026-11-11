import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import cost_policy, health_notices as h, publish
from benefit_monitor.store import load, save

NOW = datetime.fromisoformat('2026-11-11T00:10:00+09:00')
ROOT = Path(__file__).resolve().parents[1]

TABLE = '''<table><tbody>
<tr><td>2953</td><td><a href="/health/ht060701/325459?curPage=">에볼라 안내</a><!-- new --></td><td>보건관리과</td><td>2026-11-09</td></tr>
<tr><td>2952</td><td><a href="/health/ht060701/325342?curPage=">독감 무료 접종 안내</a></td><td>보건관리과</td><td>2026-11-05</td></tr>
<tr><td>2951</td><td><a href="/health/ht060701/325342?curPage=">독감 무료 접종 안내</a></td><td>보건관리과</td><td>2026-11-05</td></tr>
<tr><td>1</td><td><a href="/health/ht060701/1">아주 오래된 건강교실 모집</a></td><td>건강증진과</td><td>2026-06-01</td></tr>
<tr><td>x</td><td><a href="/health/other/9">다른 게시판</a></td><td>2026-11-01</td></tr>
</tbody></table>'''
LIST = '''<ul><li><div class="s"><a href="/health/bbs/B1/view.do?nttId=7"><span class="tit">&lt;2026. 쿠킹클래스 참여자 모집&gt; NEW</span></a>
<a href="/health/bbs/B1/view.do?nttId=7">첨부</a></div><span class="dept">보건정책과</span><span class="date">2026.10.29</span></li></ul>'''
ONCLICK = '''<table><tr><td><a href="#view" onclick="doBbsFView('275','213769','1');return false;">당뇨 건강교실 수강생 모집</a></td><td>지역보건과</td><td>2026.11.10</td></tr></table>'''

GANGSEO = dict(district='강서구', name='강서구보건소', home_url='https://www.gangseo.seoul.kr/health',
               list_url='https://www.gangseo.seoul.kr/health/ht060701', detail=r'/health/ht060701/\d+')
GWANAK = dict(district='관악구', name='관악구보건소', home_url='https://www.gwanak.go.kr/site/health/main.do',
              list_url='https://www.gwanak.go.kr/site/health/ex/bbs/List.do?cbIdx=275',
              detail=r'/site/health/ex/bbs/View\.do\?cbIdx=275&bcIdx=\d+', onclick=r"doBbsFView\('275','(\d+)'",
              detail_template='https://www.gwanak.go.kr/site/health/ex/bbs/View.do?cbIdx=275&bcIdx={id}')
BLOCKED = dict(district='은평구', name='은평구보건소', home_url='https://www.ep.go.kr/health/index.do',
               unavailable='robots가 사이트 전체 수집을 막음')
SOURCE = dict(id='health_notices', domains=['www.gangseo.seoul.kr', 'www.gwanak.go.kr', 'www.ep.go.kr'],
              collector='health_notices', health_boards=[GANGSEO, GWANAK, BLOCKED])


def fake_fetch(pages):
    calls = []

    def fetch(url, domains):
        calls.append(url)
        cost_policy.budget.consume()
        if url not in pages:
            raise OSError('unexpected ' + url)
        value = pages[url]
        if isinstance(value, Exception):
            raise value
        return value.encode('utf-8')
    return fetch, calls


class ParseTests(unittest.TestCase):
    def test_table_rows_take_title_date_dept_and_skip_duplicates_and_other_boards(self):
        rows = h.parse(TABLE, GANGSEO)
        self.assertEqual([r[1] for r in rows], ['에볼라 안내', '독감 무료 접종 안내', '아주 오래된 건강교실 모집'])
        self.assertEqual(rows[1][0], 'https://www.gangseo.seoul.kr/health/ht060701/325342?curPage=')
        self.assertEqual((rows[1][2], rows[1][3]), ('2026-11-05', '보건관리과'))

    def test_list_layout_keeps_escaped_angle_title_and_drops_new_marker(self):
        board = dict(GANGSEO, list_url='https://www.gwangjin.go.kr/health/bbs/B1/list.do', detail=r'/health/bbs/B1/view\.do\?nttId=\d+')
        (url, title, when, dept), = h.parse(LIST, board)
        self.assertEqual((title, when, dept), ('<2026. 쿠킹클래스 참여자 모집>', '2026-10-29', '보건정책과'))

    def test_onclick_board_builds_public_detail_url_from_post_number(self):
        (url, title, when, _), = h.parse(ONCLICK, GWANAK)
        self.assertEqual(url, 'https://www.gwanak.go.kr/site/health/ex/bbs/View.do?cbIdx=275&bcIdx=213769')
        self.assertEqual(when, '2026-11-10')

    def test_page_without_dated_rows_is_an_error_not_an_empty_board(self):
        with self.assertRaises(ValueError):
            h.parse('<html>점검 중</html>', GANGSEO)

    def test_hint_is_words_only_and_excludes_jobs_results_and_closed(self):
        self.assertTrue(h.hint('독감 무료 접종 안내'))
        self.assertTrue(h.hint('치매 선별 검진 안내'))
        self.assertFalse(h.hint('기간제근로자 채용 공고'))
        self.assertFalse(h.hint('방사능 안전검사 결과 알림'))
        self.assertFalse(h.hint('베이킹 클래스 모집 - 모집완료-'))
        self.assertFalse(h.hint('에볼라 안내'))


class CollectTests(unittest.TestCase):
    def setUp(self):
        cost_policy.reset(40)

    def pages(self, **over):
        pages = {'https://www.gangseo.seoul.kr/robots.txt': 'User-agent: *\nDisallow: /\nAllow: /health\n',
                 GANGSEO['list_url']: TABLE,
                 'https://www.gwanak.go.kr/robots.txt': 'User-agent: *\nAllow: /\n',
                 GWANAK['list_url']: ONCLICK}
        pages.update(over)
        return pages

    def test_collects_boards_and_never_requests_unavailable_ones(self):
        fetch, calls = fake_fetch(self.pages())
        with patch.object(h, 'fetch', fetch):
            bundle = h.collect(SOURCE, NOW)
        self.assertFalse(any('ep.go.kr' in c for c in calls))
        self.assertEqual(len(calls), 4)
        boards = {b['district']: b for b in bundle['boards']}
        self.assertEqual(boards['은평구']['status'], 'unavailable')
        self.assertEqual(boards['은평구']['items'], [])
        self.assertEqual(boards['강서구']['status'], 'checked')
        clean = h.sanitize(bundle, NOW)
        titles = [i['title'] for i in {b['district']: b for b in clean['boards']}['강서구']['items']]
        self.assertNotIn('아주 오래된 건강교실 모집', titles)  # older than 60 days

    def test_robots_refusal_marks_board_failed_and_keeps_previous_items(self):
        fetch, _ = fake_fetch(self.pages())
        with patch.object(h, 'fetch', fetch):
            previous = h.collect(SOURCE, NOW - timedelta(days=1))
        cost_policy.reset(40)
        fetch, calls = fake_fetch(self.pages(**{'https://www.gangseo.seoul.kr/robots.txt': 'User-agent: *\nDisallow: /\n'}))
        with patch.object(h, 'fetch', fetch):
            bundle = h.collect(SOURCE, NOW, previous)
        self.assertNotIn(GANGSEO['list_url'], calls)
        gangseo = next(b for b in bundle['boards'] if b['district'] == '강서구')
        self.assertEqual(gangseo['status'], 'failed')
        self.assertEqual(gangseo['checked_at'], (NOW - timedelta(days=1)).isoformat())
        self.assertTrue(gangseo['items'])

    def test_budget_exhaustion_stops_the_run(self):
        cost_policy.reset(2)
        fetch, _ = fake_fetch(self.pages())
        with patch.object(h, 'fetch', fetch), self.assertRaises(RuntimeError):
            h.collect(SOURCE, NOW)


class SanitizeTests(unittest.TestCase):
    def bundle(self):
        cost_policy.reset(40)
        fetch, _ = fake_fetch(CollectTests.pages(CollectTests()))
        with patch.object(h, 'fetch', fetch):
            return h.collect(SOURCE, NOW)

    def test_stale_bundle_is_dropped_for_display_but_kept_for_carry_over(self):
        bundle = self.bundle()
        later = NOW + timedelta(hours=31)
        self.assertIsNone(h.sanitize(bundle, later))
        self.assertIsNotNone(h.sanitize(bundle, later, allow_stale=True))

    def test_rejects_foreign_host_links_contacts_and_extra_fields(self):
        for mutate in (lambda b: b['boards'][0]['items'][0].update(url='https://evil.example/x'),
                       lambda b: b['boards'][0]['items'][0].update(title='문의 010-1234-5678'),
                       lambda b: b['boards'][0]['items'][0].update(extra=1),
                       lambda b: b['boards'][0].update(status='ok'),
                       lambda b: b['boards'][0].update(home_url='http://plain.example')):
            bundle = self.bundle()
            mutate(bundle)
            self.assertIsNone(h.sanitize(bundle, NOW))

    def test_hint_is_recomputed_not_trusted(self):
        bundle = self.bundle()
        item = bundle['boards'][0]['items'][0]
        item['hint'] = True
        clean = h.sanitize(bundle, NOW)
        self.assertFalse(clean['boards'][0]['items'][0]['hint'])

    def test_candidates_are_recent_hint_titles_with_district(self):
        cands = h.candidates(self.bundle(), NOW)
        self.assertEqual({c['title'] for c in cands}, {'독감 무료 접종 안내', '당뇨 건강교실 수강생 모집'})
        first = next(c for c in cands if c['title'] == '독감 무료 접종 안내')
        self.assertEqual((first['source'], first['districts'], first['needs_recheck']), ('health_notices', ['강서구'], True))


class RepositoryTests(unittest.TestCase):
    def test_repository_definition_is_valid_and_every_listed_board_is_on_the_allowlist(self):
        config = load(ROOT / 'sources.yaml', None)
        source = next(s for s in config['sources'] if s['id'] == 'health_notices')
        boards = h._boards(source)
        self.assertEqual(len({b['district'] for b in boards}), len(boards))
        districts = {d['name'] for d in json.loads((ROOT / 'districts.json').read_text())['districts']}
        self.assertLessEqual(districts, {b['district'] for b in boards})  # 서울 25개 구 모두 상태가 보인다

    def test_publish_attaches_fresh_bundle_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {}
            publish.attach_health_notices(tmp, data, NOW)
            self.assertNotIn('health_notices', data)
            save(Path(tmp) / h.FILE, SanitizeTests.bundle(SanitizeTests()))
            publish.attach_health_notices(tmp, data, NOW)
            self.assertEqual(data['health_notices']['source'], 'health_notices')


if __name__ == '__main__':
    unittest.main()


PROGRAMS = [dict(district='강서구', name='대사증후군 관리', url=f'https://www.gangseo.seoul.kr/health/ht02010{i}') for i in range(3)]
PROGRAM_PAGE = '<html><h2>대사증후군 관리사업</h2><p>무료 검진</p></html>'


class ProgramTests(unittest.TestCase):
    def pages(self, **over):
        pages = CollectTests.pages(CollectTests())
        pages.update({p['url']: PROGRAM_PAGE for p in PROGRAMS})
        pages.update(over)
        return pages

    def run_at(self, now, pages, previous=None, budget=40):
        cost_policy.reset(budget)
        fetch, calls = fake_fetch(pages)
        with patch.object(h, 'fetch', fetch):
            return h.collect(dict(SOURCE, health_programs=PROGRAMS), now, previous), calls

    def test_first_run_checks_all_then_one_third_per_day(self):
        first, calls = self.run_at(NOW, self.pages())
        self.assertEqual([p['status'] for p in first['programs']], ['checked'] * 3)
        self.assertEqual(sum(c in {p['url'] for p in PROGRAMS} for c in calls), 3)
        self.assertEqual(first['programs'][0]['center'], '강서구보건소')
        later = NOW + timedelta(days=1)
        second, calls = self.run_at(later, self.pages(), first)
        self.assertEqual(sum(c in {p['url'] for p in PROGRAMS} for c in calls), 1)
        self.assertEqual(sum(p['checked_at'] == later.isoformat() for p in second['programs']), 1)

    def test_missing_page_fails_and_is_rechecked_next_day(self):
        first, _ = self.run_at(NOW, self.pages(**{PROGRAMS[0]['url']: '<p>요청하신 페이지를 찾을 수 없습니다</p>'}))
        self.assertEqual(first['programs'][0]['status'], 'failed')
        self.assertIsNone(first['programs'][0]['checked_at'])
        second, calls = self.run_at(NOW + timedelta(days=1), self.pages(), first)
        self.assertIn(PROGRAMS[0]['url'], calls)
        self.assertEqual(second['programs'][0]['status'], 'checked')

    def test_page_without_the_programme_name_fails(self):
        with self.assertRaises(ValueError):
            h.check_program('<p>금연 클리닉</p>', '대사증후군 관리')
        h.check_program('<p>대사 증후군</p>', '대사증후군 관리')

    def test_budget_exhaustion_keeps_previous_programme_results(self):
        first, _ = self.run_at(NOW, self.pages())
        second, _ = self.run_at(NOW + timedelta(days=3), self.pages(), first, budget=4)
        self.assertEqual([p['status'] for p in second['programs']], ['checked'] * 3)
        self.assertEqual({p['checked_at'] for p in second['programs']}, {NOW.isoformat()})

    def test_checked_programmes_become_candidates_and_sanitize_validates_them(self):
        bundle, _ = self.run_at(NOW, self.pages())
        titles = {c['title'] for c in h.candidates(bundle, NOW)}
        self.assertIn('강서구보건소 대사증후군 관리', titles)
        bundle['programs'][0]['district'] = '없는구'
        self.assertIsNone(h.sanitize(bundle, NOW))

    def test_old_bundle_without_programmes_is_still_valid(self):
        bundle, _ = self.run_at(NOW, self.pages())
        bundle.pop('programs')
        self.assertEqual(h.sanitize(bundle, NOW)['programs'], [])

    def test_repository_programmes_are_on_the_allowlist_and_collectable_districts(self):
        source = next(s for s in load(ROOT / 'sources.yaml', None)['sources'] if s['id'] == 'health_notices')
        programs = h._programs(source)
        collectable = {b['district'] for b in source['health_boards'] if 'unavailable' not in b}
        self.assertTrue(programs)
        self.assertLessEqual({p['district'] for p in programs}, collectable)
        self.assertIn('https://www.gangseo.seoul.kr/health/ht020103', {p['url'] for p in programs})
