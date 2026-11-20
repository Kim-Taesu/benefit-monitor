"""Stage 1 follow-up search (2026-11-20): links first, one web search only when no official link is usable,
URLs only from the provider's search results, only registered sources are read."""
import copy
import io
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from benefit_monitor import investigation as agent, web_search
from benefit_monitor.claude_trial import ClaudeClient
from benefit_monitor.trial_budget import TrialBudget, WEB_SEARCH_MICRODOLLARS
import test_investigation as base

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-11-21T03:50:00+09:00')
OFFICIAL = 'https://www.seoul.go.kr/news/event-123'


def response(urls=(), searches=1, text='완료', error=False):
    blocks = [{'type': 'server_tool_use', 'id': 'srv1', 'name': 'web_search', 'input': {'query': 'x'}}]
    if error:
        blocks.append({'type': 'web_search_tool_result', 'tool_use_id': 'srv1',
                       'content': {'type': 'web_search_tool_result_error', 'error_code': 'max_uses_exceeded'}})
    else:
        blocks.append({'type': 'web_search_tool_result', 'tool_use_id': 'srv1',
                       'content': [{'type': 'web_search_result', 'url': u, 'title': 't', 'encrypted_content': 'e'} for u in urls]})
    blocks.append({'type': 'text', 'text': text})
    return {'id': 'msg', 'model': 'claude-haiku-5-5', 'type': 'message', 'stop_reason': 'end_turn', 'content': blocks,
            'usage': {'input_tokens': 9000, 'output_tokens': 5, 'server_tool_use': {'web_search_requests': searches}}}


class InputAndParsingTests(unittest.TestCase):
    def test_input_carries_only_title_organizer_and_fields(self):
        host = web_search.build('c1', '한강 야외 영화제', '서울특별시', ['fee_status', 'event_period'], NOW)
        web_search.validate(host)
        self.assertEqual(host['missing_fields'], ['event_period', 'fee_status'])
        self.assertNotIn('url', web_search.user_text(host).lower().replace('<input>', ''))
        for bad in (dict(host, title='https://evil.example'), dict(host, missing_fields=[]),
                    dict(host, missing_fields=['phone']), dict(host, extra=1), dict(host, title=' ')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                web_search.validate(bad)

    def test_urls_come_only_from_search_result_blocks(self):
        result = response([OFFICIAL, OFFICIAL, 'http://plain.example/a', 'https://user:pw@x.example/a',
                           'https://news.example/a'])
        result['content'][-1]['text'] = '공식 페이지는 https://fabricated.example 입니다'
        self.assertEqual(web_search.result_urls(result), [OFFICIAL, 'https://news.example/a'])
        self.assertEqual(web_search.result_urls(response(error=True)), [])
        self.assertEqual(web_search.searches_used(response(searches=2)), 2)


class ClientTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tools').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.tools')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.budget = TrialBudget.initialize(self.root / 'budget.json', 'claude-haiku-5-5', '0.10', '0.50')
        self.client = ClaudeClient(self.root, self.budget, 'fake-secret-for-tests')
        self.host = web_search.build('c1', '한강 야외 영화제', '서울특별시', ['fee_status'], NOW)

    def test_search_request_has_the_tool_no_schema_and_settles_searches(self):
        sent = []
        def fake(request):
            sent.append(json.loads(request.data));return io.BytesIO(json.dumps(response([OFFICIAL], searches=2)).encode())
        with patch('benefit_monitor.claude_trial.network_open', side_effect=fake):
            result = self.client.web_search(self.host)
        self.assertEqual(web_search.result_urls(result), [OFFICIAL])
        self.assertEqual(sent[0]['tools'], [web_search.tool()])
        self.assertNotIn('output_config', sent[0])
        row = self.budget.summary()['requests'][0]
        self.assertEqual((row['status'], row['web_search_max_uses']), ('completed', 2))
        self.assertEqual(row['charged_microdollars'], 9000 // 10 + 3 + 2 * WEB_SEARCH_MICRODOLLARS)

    def test_a_refused_search_does_not_halt_the_trial(self):
        def reject(request):
            raise HTTPError(request.full_url, 400, 'bad', {}, io.BytesIO(b'{"error":{"message":"web search is not enabled"}}'))
        with patch('benefit_monitor.claude_trial.network_open', side_effect=reject):
            with self.assertRaises(ValueError):
                self.client.web_search(self.host)
        state = self.budget.summary()
        self.assertFalse(state['halted'])
        self.assertEqual(state['requests'][0]['error_code'], 'http_400')

    def test_tool_probe_is_cached_and_a_rejection_is_recorded(self):
        with patch('benefit_monitor.claude_trial.network_open', return_value=io.BytesIO(json.dumps(response(searches=0)).encode())):
            first = self.client.web_search_probe()
        with patch('benefit_monitor.claude_trial.network_open', side_effect=AssertionError('cached')):
            second = self.client.web_search_probe()
        self.assertEqual((first['status'], first['cached'], second['cached']), ('passed', False, True))


class LeadTests(unittest.TestCase):
    """The follow-up loop of test_investigation (its fixtures borrowed, not its tests), with search turned on."""
    setUp = base.InvestigationTests.setUp
    document = base.InvestigationTests.document
    read = base.InvestigationTests.read
    output = base.InvestigationTests.output
    invoke = base.InvestigationTests.invoke
    run_agent = base.InvestigationTests.run_agent

    def search(self, urls, status='search_done'):
        calls = []
        def invoke(root, path):
            calls.append(json.loads(Path(path).read_text()))
            return {'status': status, 'urls': list(urls), 'searches': 1 if status == 'search_done' else 0, 'run_id': 'r'}
        return invoke, calls

    def run_search(self, urls, state=None, status='search_done', max_requests=3):
        invoke, calls = self.search(urls, status)
        state = {'off': False} if state is None else state
        self.host['candidates'][0].setdefault('title', '한강 야외 영화제')
        with patch('benefit_monitor.ai_review.invoke', side_effect=self.invoke), \
                patch('benefit_monitor.ai_review.invoke_search', side_effect=invoke), \
                patch.object(agent, 'read_result', side_effect=lambda run, h: self.outputs.pop(0)):
            result = agent.run(self.root, self.host, self.reader, base.NOW, execute=True, max_requests=max_requests,
                               search_state=state)
        return result, calls, state

    def test_no_link_then_search_reads_a_registered_official_page(self):
        self.host['documents'][0]['links'] = []
        self.outputs = [self.output(), self.output(reason='sufficient_evidence', fields=[])]
        result, calls, _ = self.run_search(['https://news.example/a', OFFICIAL])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['title'], self.host['candidates'][0]['title'])
        self.assertEqual([r['url'] for r in self.reads], [OFFICIAL])
        self.assertEqual(result['report']['model_calls'], 2)
        self.assertEqual(result['report']['steps'][0]['status'], 'read_search')
        self.assertEqual(result['report']['web_searches'], 1)
        self.assertIn('https://news.example/a', result['report']['source_candidates'])

    def test_search_off_by_default_and_only_once_per_candidate(self):
        self.host['documents'][0]['links'] = []
        self.outputs = [self.output()]
        result = self.run_agent()
        self.assertEqual((self.reads, result['report'].get('web_searches')), ([], 0))
        self.outputs = [self.output(), self.output()]
        result, calls, _ = self.run_search([OFFICIAL])
        self.assertEqual((len(calls), len(self.reads)), (1, 1))
        self.assertEqual(result['report']['status'], 'no_relevant_links')

    def test_only_foreign_results_read_nothing(self):
        self.host['documents'][0]['links'] = []
        self.outputs = [self.output()]
        result, calls, _ = self.run_search(['https://news.example/a', 'https://www.seoul.go.kr.evil.example/a'])
        self.assertEqual(self.reads, [])
        self.assertEqual(result['report']['steps'][0]['search']['allowed_link'], False)

    def test_a_refused_search_turns_search_off_for_the_run(self):
        self.host['documents'][0]['links'] = []
        self.outputs = [self.output()]
        _, calls, state = self.run_search([], status='search_failed')
        self.assertTrue(state['off'])
        self.outputs = [self.output()]
        _, calls, _ = self.run_search([OFFICIAL], state=state)
        self.assertEqual((calls, self.reads), ([], []))

    def test_no_search_without_room_for_another_round(self):
        self.host['documents'][0]['links'] = []
        self.outputs = [self.output()]
        _, calls, _ = self.run_search([OFFICIAL], max_requests=1)
        self.assertEqual((calls, self.reads), ([], []))


if __name__ == '__main__':
    unittest.main()
