import unittest
from benefit_monitor.collectors.html import ArticleLinks

class CoverageTests(unittest.TestCase):
    def test_title_keyword_does_not_match_unrelated_article_body(self):
        parser = ArticleLinks('https://www.korea.kr/', ['www.korea.kr'], r'/news/policyNewsView.do', ['지원'])
        parser.feed('<a href="/news/policyNewsView.do?newsId=1"><strong>경제 동향</strong><span>지원 정책 배경 설명</span></a>')
        self.assertEqual(parser.items, {})

    def test_feed_filters_unrelated_news_when_keywords_configured(self):
        from benefit_monitor.collectors.rss import parse
        source = dict(id='news', domains=['official.example'], keywords=['할인'])
        body = b'<rss><channel><item><title>General news</title><link>https://official.example/a</link></item></channel></rss>'
        self.assertEqual(parse(body, source), [])

    def test_transient_service_error_retries_then_returns_body(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from io import BytesIO
        from benefit_monitor.collectors.rss import fetch
        from benefit_monitor import cost_policy
        cost_policy.reset(3)
        class Opener:
            attempts = 0
            def open(self, request, timeout):
                self.attempts += 1
                if self.attempts == 1:
                    raise HTTPError(request.full_url, 503, 'Unavailable', {}, None)
                return BytesIO(b'current official response')
        with patch('urllib.request.build_opener', return_value=Opener()), patch('time.sleep'):
            self.assertEqual(fetch('https://official.example/a', ['official.example']), b'current official response')

    def test_government_tracking_links_do_not_duplicate_candidates(self):
        parser = ArticleLinks('https://www.korea.kr/', ['www.korea.kr'], r'/news/policyNewsView.do', ['할인'])
        parser.feed('<a href="/news/policyNewsView.do?newsId=1">할인</a><a href="/news/policyNewsView.do?newsId=1&amp;pWise=sub&amp;pWiseSub=R2">할인</a>')
        self.assertEqual(list(parser.items), ['https://www.korea.kr/news/policyNewsView.do?newsId=1'])

    def test_wrapped_timeout_retries_but_tls_errors_do_not(self):
        from unittest.mock import patch
        from urllib.error import URLError
        from io import BytesIO
        import ssl
        from benefit_monitor.collectors.rss import fetch
        from benefit_monitor import cost_policy
        for reason, retry in [(TimeoutError('timeout'), True), (ssl.SSLError('TLS failure'), False)]:
            cost_policy.reset(3)
            class Opener:
                attempts = 0
                def open(self, request, timeout):
                    self.attempts += 1
                    if self.attempts == 1:
                        raise URLError(reason)
                    return BytesIO(b'ok')
            with patch('urllib.request.build_opener', return_value=Opener()), patch('time.sleep'):
                if retry:
                    self.assertEqual(fetch('https://official.example/a', ['official.example']), b'ok')
                else:
                    with self.assertRaises(URLError):
                        fetch('https://official.example/a', ['official.example'])
