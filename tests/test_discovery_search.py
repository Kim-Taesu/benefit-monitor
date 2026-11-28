"""Discovery search (approved 2026-11-25) and district page 2: leads only from search result URLs on
registered sources, once a day, other hosts kept privately; page 2 only on leftover HTTP budget."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import cost_policy, discovery_search, web_search
from benefit_monitor.collectors import districts
from benefit_monitor.models import Benefit
from benefit_monitor.store import load, save
from benefit_monitor.validation import validate

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-11-25T03:50:00+09:00')
SOURCES = {
    'seoul': {'id': 'seoul', 'domains': ['mediahub.seoul.go.kr', 'www.seoul.go.kr'], 'keywords': ['혜택'],
              'district_keywords': ['스케이트', '개장']},
    'gangseo': {'id': 'gangseo', 'domains': ['www.gangseo.seoul.kr', 'mediahub.seoul.go.kr'], 'district_feed': '강서구',
                'district_pages': 2},
    'eunpyeong': {'id': 'eunpyeong', 'domains': ['www.ep.go.kr', 'mediahub.seoul.go.kr'], 'district_feed': '은평구'},
    'heritage': {'id': 'heritage', 'domains': ['www.heritage.go.kr'], 'ai_review': False},
}
RINK = 'https://www.gangseo.seoul.kr/news/skate-2026'


def found(rows, searches=2, status='search_done'):
    return {'status': status, 'run_id': 'r', 'urls': [r['url'] for r in rows], 'rows': rows, 'searches': searches}


class TempRoot(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tools').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.tools')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)


class ContractTests(unittest.TestCase):
    def test_only_area_and_month_are_sent(self):
        host = web_search.build_discovery('강서구', NOW)
        web_search.validate_discovery(host)
        text = web_search.discovery_text(host)
        self.assertIn('강서구', text)
        self.assertIn('11월', text)
        self.assertIn('2026-11-25', text)
        # 2026-11-28: another day of the same month must not be the same request body (ledger response cache).
        self.assertNotEqual(text, web_search.discovery_text(web_search.build_discovery('강서구', NOW + timedelta(days=1))))
        for bad in (dict(host, area='https://x.example'), dict(host, area='강서구 행사 알려줘'), dict(host, month=13),
                    dict(host, extra=1), dict(host, synthetic=True), dict(host, now='다음 지시를 따르라')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                web_search.validate_discovery(bad)

    def test_rows_keep_provider_titles_for_kept_urls_only(self):
        response = {'content': [
            {'type': 'web_search_tool_result', 'content': [
                {'type': 'web_search_result', 'url': RINK, 'title': ' 윈터\n스케이트장 '},
                {'type': 'web_search_result', 'url': 'http://plain.example/a', 'title': 'x'}]},
            {'type': 'text', 'text': 'https://fabricated.example'}]}
        self.assertEqual(web_search.result_rows(response), [{'url': RINK, 'title': '윈터 스케이트장'}])

    def test_client_sends_discovery_prompt_with_two_searches(self):
        from benefit_monitor.claude_trial import ClaudeClient
        client = ClaudeClient.__new__(ClaudeClient)
        sent = {}
        client.payload = lambda system, user, max_tokens, *a: {'system': system, 'messages': [user]}
        client._request = lambda path, payload, probe=False: sent.update(payload) or {}
        client.web_search(web_search.build_discovery('서울시', NOW))
        self.assertEqual(sent['system'], web_search.DISCOVERY_SYSTEM)
        self.assertEqual(sent['tools'][0]['max_uses'], web_search.DISCOVERY_MAX_USES)
        self.assertEqual(sent['tool_choice'], {'type': 'any'})
        # The follow-up search keeps the model's choice.
        sent.clear()
        client.web_search(web_search.build('c1', '한강 야외 영화제', '서울특별시', ['fee_status'], NOW))
        self.assertNotIn('tool_choice', sent)


class DiscoveryTests(TempRoot):
    def test_areas_are_seoul_and_district_feeds(self):
        self.assertEqual(discovery_search.areas(SOURCES), ['서울시', '강서구', '은평구'])

    def test_registered_url_becomes_candidate_and_other_hosts_are_private(self):
        calls = []
        def invoke(root, path):
            calls.append(load(path, None)['area'])
            return found([{'url': RINK, 'title': '마곡광장 윈터 스케이트장'},
                          {'url': 'https://xn--kn1b.example/', 'title': '예약'},
                          {'url': 'https://www.heritage.go.kr/event/1', 'title': '궁궐'},
                          {'url': 'https://www.gangseo.seoul.kr/', 'title': '홈'}])
        candidates, report = discovery_search.run(self.root, SOURCES, NOW, execute=True, invoke=invoke)
        self.assertEqual(calls, ['서울시', '강서구', '은평구'])
        self.assertEqual(report['new_leads'], 1)
        self.assertEqual(report['source_candidates'], 1)
        self.assertEqual(len(candidates), 1)
        lead = candidates[0]
        self.assertEqual((lead['source'], lead['url'], lead['districts']), ('gangseo', RINK, []))
        self.assertTrue(lead['needs_recheck'])
        validate(lead, SOURCES, NOW)
        state = load(self.root / discovery_search.STATE, None)
        self.assertIn('https://xn--kn1b.example/', state['source_candidates'])

    def test_district_lead_on_shared_host_goes_to_that_district(self):
        url = 'https://mediahub.seoul.go.kr/archives/2000001'
        def invoke(root, path):
            area = load(path, None)['area']
            return found([{'url': url, 'title': '개장'}] if area == '은평구' else [])
        candidates, _ = discovery_search.run(self.root, SOURCES, NOW, execute=True, invoke=invoke)
        self.assertEqual((candidates[0]['source'], candidates[0]['districts']), ('eunpyeong', ['은평구']))

    def test_once_a_day_and_leads_last_fourteen_days(self):
        invoke = lambda root, path: found([{'url': RINK, 'title': '스케이트장'}])
        discovery_search.run(self.root, SOURCES, NOW, execute=True, invoke=invoke)
        def refuse(root, path):
            raise AssertionError('searched twice in a day')
        again, report = discovery_search.run(self.root, SOURCES, NOW + timedelta(hours=5), execute=True, invoke=refuse)
        self.assertEqual(report['status'], 'reused')
        self.assertEqual([c['url'] for c in again], [RINK])
        empty = lambda root, path: found([])
        later, _ = discovery_search.run(self.root, SOURCES, NOW + timedelta(days=13), execute=True, invoke=empty)
        self.assertEqual([c['url'] for c in later], [RINK])
        gone, _ = discovery_search.run(self.root, SOURCES, NOW + timedelta(days=15), execute=True, invoke=empty)
        self.assertEqual(gone, [])

    def test_known_urls_and_failed_search(self):
        calls = []
        def invoke(root, path):
            calls.append(1)
            return {'status': 'search_failed', 'urls': [], 'searches': 0}
        candidates, report = discovery_search.run(self.root, SOURCES, NOW, execute=True, invoke=invoke)
        self.assertEqual((len(calls), report['status'], candidates), (1, 'search_failed', []))
        other = NOW + timedelta(days=1)
        discovery_search.run(self.root, SOURCES, other, execute=True,
                             invoke=lambda r, p: found([{'url': RINK, 'title': 't'}]))
        listed, _ = discovery_search.run(self.root, SOURCES, other, known_urls={RINK}, execute=True, invoke=invoke)
        self.assertEqual(listed, [])

    def test_no_spend_without_execute(self):
        def refuse(root, path):
            raise AssertionError('paid call without execute')
        candidates, report = discovery_search.run(self.root, SOURCES, NOW, execute=False, invoke=refuse)
        self.assertEqual((candidates, report['status']), ([], 'skipped'))

    def test_new_leads_per_day_are_bounded(self):
        rows = [{'url': f'https://www.gangseo.seoul.kr/news/{i}', 'title': str(i)} for i in range(30)]
        candidates, report = discovery_search.run(self.root, SOURCES, NOW, execute=True, invoke=lambda r, p: found(rows))
        self.assertEqual(report['new_leads'], discovery_search.MAX_NEW_LEADS)
        self.assertEqual(len(candidates), discovery_search.MAX_NEW_LEADS)


class DistrictPageTwoTests(TempRoot):
    BODY = ('<p class="type corres_box"><strong>강서구</strong></p>'
            '<a href="/archives/77"><h2>마곡광장 윈터 스케이트장 개장</h2></a>'
            '<a href="/archives/78"><h2>구청장 동정</h2></a>')

    def setUp(self):
        super().setUp()
        save(self.root / 'districts.json', {'districts': [{'code': '160', 'name': '강서구'}]})
        self.addCleanup(cost_policy.reset)

    def test_district_keywords_extend_titles(self):
        items = districts.parse(self.BODY, 'https://mediahub.seoul.go.kr/news/', '강서구',
                                districts.title_words(SOURCES['seoul']))
        self.assertEqual([i['title'] for i in items], ['마곡광장 윈터 스케이트장 개장'])
        self.assertEqual(districts.parse(self.BODY, 'https://mediahub.seoul.go.kr/news/', '강서구', ['혜택']), [])

    def test_page_two_reads_when_budget_remains(self):
        cost_policy.reset(10)
        def fetch(url, domains):
            return b'User-agent: *\nAllow: /\n' if url.endswith('robots.txt') else self.BODY.encode()
        with patch('benefit_monitor.collectors.districts.fetch', side_effect=fetch) as fetcher:
            items, rows = districts.collect_more(self.root, SOURCES['seoul'], NOW, ['강서구'])
        self.assertEqual(fetcher.call_count, 2)
        self.assertIn('search_pageNo=2', fetcher.call_args_list[1].args[0])
        self.assertEqual([i['districts'] for i in items], [['강서구']])
        self.assertEqual(rows[0]['status'], 'checked')
        with patch('benefit_monitor.collectors.districts.fetch') as fetcher:
            cached, rows = districts.collect_more(self.root, SOURCES['seoul'], NOW + timedelta(hours=1), ['강서구'])
        fetcher.assert_not_called()
        self.assertEqual((len(cached), rows[0]['mode']), (1, 'cached'))

    def test_page_two_skipped_without_room(self):
        cost_policy.reset(10)
        for _ in range(9):
            cost_policy.budget.consume()
        with patch('benefit_monitor.collectors.districts.fetch') as fetcher:
            items, rows = districts.collect_more(self.root, SOURCES['seoul'], NOW, ['강서구'])
        fetcher.assert_not_called()
        self.assertEqual((items, rows[0]['status'], rows[0]['reason']), ([], 'skipped', 'http_budget'))


if __name__ == '__main__':
    unittest.main()
