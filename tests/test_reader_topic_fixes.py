import io
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

from benefit_monitor import cost_policy
from benefit_monitor.official_reader import OfficialReader, request_url
from test_wire_format import topic_host

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 8, 8, tzinfo=ZoneInfo('Asia/Seoul'))
BODY = '<html><main>' + '공식 안내 본문입니다. 신청 방법과 조건, 기간, 비용을 자세히 설명합니다. ' * 4 + '</main></html>'


class Response(io.BytesIO):
    headers = {'Content-Type': 'text/html; charset=utf-8'}


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = {'sources': [{'id': 'seoul', 'domains': ['mediahub.seoul.go.kr'], 'routes': [], 'feed_url': None}]}
        (self.root / 'sources.yaml').write_text(json.dumps(config))
        cost_policy.reset(100)
        self.calls = []

    def read(self, url, transport):
        def opener(request):
            self.calls.append(request.full_url)
            return transport(request.full_url)
        with patch('benefit_monitor.official_reader.network_open', side_effect=opener):
            return OfficialReader(self.root, NOW).read({'source': 'seoul', 'url': url, 'title': 'x'})

    def test_korean_query_is_percent_encoded_once(self):
        url = 'https://mediahub.seoul.go.kr/news/list.do?tagName=서울달빛야장&a=%20b'
        self.assertEqual(request_url(url), 'https://mediahub.seoul.go.kr/news/list.do?tagName=%EC%84%9C%EC%9A%B8%EB%8B%AC%EB%B9%9B%EC%95%BC%EC%9E%A5&a=%20b')
        doc = self.read(url, lambda u: Response(b'User-agent: *\nAllow: /') if u.endswith('robots.txt') else Response(BODY.encode()))
        self.assertEqual(doc['requested_url'], url)
        self.assertTrue(all(u.isascii() for u in self.calls))

    def test_one_transient_error_is_retried(self):
        state = {'n': 0}
        def transport(u):
            if u.endswith('robots.txt'): return Response(b'')
            state['n'] += 1
            if state['n'] == 1: raise URLError('timed out')
            return Response(BODY.encode())
        self.assertEqual(self.read('https://mediahub.seoul.go.kr/a/1', transport)['fetch_status'], 'ok')

    def test_single_host_failure_does_not_block_other_candidates(self):
        def down(u):
            if u.endswith('robots.txt'): return Response(b'')
            raise URLError('connection reset')
        with self.assertRaises(URLError):
            self.read('https://mediahub.seoul.go.kr/a/1', down)
        ok = lambda u: Response(b'') if u.endswith('robots.txt') else Response(BODY.encode())
        self.assertEqual(self.read('https://mediahub.seoul.go.kr/a/2', ok)['fetch_status'], 'ok')

    def test_repeated_host_failures_cool_down_and_page_errors_do_not(self):
        def gone(u):
            if u.endswith('robots.txt'): return Response(b'')
            raise HTTPError(u, 404, 'nf', {}, io.BytesIO())
        for n in range(4):
            with self.assertRaises(HTTPError):
                self.read(f'https://mediahub.seoul.go.kr/g/{n}', gone)
        def down(u):
            if u.endswith('robots.txt'): return Response(b'')
            raise HTTPError(u, 503, 'busy', {}, io.BytesIO())
        for n in range(3):
            with self.assertRaises(HTTPError):
                self.read(f'https://mediahub.seoul.go.kr/d/{n}', down)
        with self.assertRaisesRegex(ValueError, 'cooldown'):
            self.read('https://mediahub.seoul.go.kr/d/9', down)


class BasisCardTests(unittest.TestCase):
    def test_basis_cards_use_first_topic_and_pass_semantic_review(self):
        from benefit_monitor.daily_topics import basis_cards
        from benefit_monitor.topic_semantics import review
        cards = basis_cards(topic_host())
        self.assertEqual({c['topic_id']: [l['item_id'] for l in c['item_links']] for c in cards},
                         {'culture': ['a', 'b'], 'shopping': ['d']})
        self.assertTrue(review({'topics': cards}, topic_host())['valid'])

    def test_refresh_falls_back_to_basis_cards_when_draft_rejected_and_no_previous(self):
        from benefit_monitor import topic_refresh
        host = topic_host()
        with tempfile.TemporaryDirectory(dir=ROOT) as temp, \
                patch.object(topic_refresh, 'approved_snapshot', return_value=host), \
                patch.object(topic_refresh, 'invoke', return_value={'status': 'rejected_draft', 'run_id': 'r'}):
            host['source_review_id'] = 'public-release:x'
            draft = topic_refresh.refresh(temp, now=NOW, execute=True)
        self.assertTrue(draft['used_fallback'])
        self.assertEqual([c['topic_id'] for c in draft['topics']], ['culture', 'shopping'])


if __name__ == '__main__':
    unittest.main()


class PagePublishedDateTests(unittest.TestCase):
    def test_seoul_mediahub_header_date(self):
        from benefit_monitor.official_reader import page_published
        html = ('<div class="info"><p class="date">발행일 <span class="num">2026.10.12. 11:48</span></p>'
                '<p class="date bar">수정일 <span class="num">2026.10.13. 15:47</span></p></div>')
        self.assertEqual(page_published(html, 'https://mediahub.seoul.go.kr/archives/2019606'), '2026-10-12')

    def test_unknown_host_or_bad_date_is_none(self):
        from benefit_monitor.official_reader import page_published
        html = '<p class="date">발행일 <span class="num">2026.10.12.</span></p>'
        self.assertIsNone(page_published(html, 'https://www.seoul.go.kr/news/1'))
        self.assertIsNone(page_published('<p class="date">발행일 <span class="num">2026.13.40.</span></p>',
                                         'https://mediahub.seoul.go.kr/archives/1'))
        self.assertIsNone(page_published('<p>본문</p>', 'https://mediahub.seoul.go.kr/archives/1'))
