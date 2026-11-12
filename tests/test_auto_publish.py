"""Deterministic auto-publish gate. Synthetic host/draft fixtures only; no network, no API."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from benefit_monitor import wire_format as w

ROOT = Path(__file__).resolve().parents[1]
KST = ZoneInfo('Asia/Seoul')
NOW = datetime(2026, 11, 8, 12, tzinfo=KST)

D1 = '서울 미술 전시 안내.\n전시 기간은 2026-11-01부터 2026-11-30까지입니다.\n관람료는 무료입니다.\n누구나 관람할 수 있습니다.'
D2 = '시립미술관 전시 소식.\n전시는 2026-11-30까지 열립니다.\n관람료는 무료입니다.'
# Ongoing service: no ending date phrases anywhere.
O1 = '서울 공공 도서 대출 서비스 안내.\n게시일 2026-10-01.\n도서는 상시 대출할 수 있습니다.\n이용료는 무료입니다.'
O2 = '구립도서관 운영 안내.\n도서관은 매일 운영합니다.\n이용료는 무료입니다.'


def doc(index, body, retrieved=NOW - timedelta(hours=1), url=None):
    url = url or f'https://www.seoul.go.kr/news/{index}'
    return dict(id=f'doc-{index}', source_id='seoul', requested_url=url, final_url=url, publisher_type='issuer',
                document_role='notice', retrieved_at=retrieved.isoformat(), published_at=None,
                body_hash=hashlib.sha256(body.encode()).hexdigest(), hash_algorithm='sha256-utf8-exact',
                extraction_scope='test', fetch_status='ok', body=body)


def host(*bodies, title='서울 미술 전시', cid='c1', docs=None):
    docs = docs or [doc(i, b) for i, b in enumerate(bodies, 1)]
    return dict(schema_version='research-input-v1', mode='api_agent', synthetic=False, now=NOW.isoformat(),
                output_schema_version='research-draft-v1', budget={},
                candidates=[dict(candidate_id=cid, source_id='seoul', title=title, document_ids=[d['id'] for d in docs])],
                documents=docs)


def slots(field, given):
    out = dict(field=field, status=given.get('status', 'unknown'), text='', items=[], not_confirmed=[], start='', end='',
               number=0, segment_ids=list(given.get('ev', [])), unknown_reason=given.get('unknown_reason', ''))
    value = given.get('value')
    if value is not None:
        if field == 'eligibility':
            out.update(text=value['scope'], items=value['required'], not_confirmed=value['not_confirmed'])
        elif field in ('event_period', 'application_period'):
            out.update(start=value['start'], end=value['end'])
        elif field == 'published_at':
            out['start'] = value
        elif field == 'capacity':
            out['number'] = value
        elif field == 'districts':
            out['items'] = value
        else:
            out['text'] = value
    return out


def sup(value, *ev):
    return {'status': 'supported', 'value': value, 'ev': ev}


def draft_for(base, **facts):
    rows = [slots(f, facts.get(f, {'unknown_reason': '원문에 없음'})) for f in w.FIELDS]
    wire = dict(wire_version=w.RESEARCH_WIRE, status='completed', errors=[],
                records=[dict(candidate_id=base['candidates'][0]['candidate_id'], research_status='completed',
                              stop_reason='sufficient_evidence', facts=rows)])
    return w.research_from_wire(wire, base)


ANYONE = {'scope': 'unrestricted', 'required': [], 'not_confirmed': []}


def period_facts(**over):
    facts = dict(summary=sup('서울 미술 전시', 'd1s1'), conditions=sup('누구나 관람', 'd1s4'),
                 fee_status=sup('free', 'd1s3', 'd2s3'), eligibility=sup(ANYONE, 'd1s4'),
                 event_period=sup({'start': '2026-11-01', 'end': '2026-11-30'}, 'd1s2', 'd2s2'))
    facts.update(over)
    return facts


def ongoing_facts(**over):
    facts = dict(summary=sup('도서 대출 서비스', 'd1s1'), conditions=sup('매일 운영', 'd2s2'),
                 fee_status=sup('free', 'd1s4', 'd2s3'), eligibility=sup(ANYONE, 'd1s3'),
                 published_at=sup('2026-10-01', 'd1s2'))
    facts.update(over)
    return facts


class AutoPublishTests(unittest.TestCase):
    def decide(self, base, facts, takedowns=(), now=NOW):
        from benefit_monitor.auto_publish import decide
        return decide(draft_for(base, **facts), base, now, list(takedowns))

    def test_period_item_with_two_documents_publishes(self):
        base = host(D1, D2)
        result = self.decide(base, period_facts())
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual(result['reasons'], [])
        record = result['record']
        self.assertEqual(record['review']['document_count'], 2)
        self.assertEqual(record['schema_version'], 1)
        self.assertEqual(record['validity_kind'], 'fixed')
        self.assertEqual(record['valid_until'], '2026-11-30')
        self.assertEqual(record['valid_from'], '2026-11-01')
        self.assertIsNone(record['deadline_at'])
        self.assertEqual(record['fee_status'], 'free')
        self.assertEqual(record['url'], 'https://www.seoul.go.kr/news/1')
        self.assertEqual(record['review']['kind'], 'ai_auto')
        self.assertEqual(record['review']['checked_at'], NOW.isoformat())
        self.assertEqual([d['title'] for d in record['review']['documents']], ['서울 미술 전시', ''])
        self.assertIn('전시는 2026-11-30까지 열립니다.', record['review']['basis']['period_quotes'])
        self.assertEqual(record['title_key'], '서울미술전시|서울시')
        # The record must pass the existing public item validation.
        from benefit_monitor.validation import validate
        sources = {s['id']: s for s in json.loads((ROOT/'sources.yaml').read_text())['sources']}
        public = {k: record[k] for k in ('source', 'url', 'title', 'summary', 'conditions', 'districts', 'valid_from',
                                         'valid_until', 'deadline_at', 'validity_kind', 'fee_status', 'payment_terms', 'labels')}
        validate(public, sources, NOW)

    def test_year_less_date_is_held(self):
        body = '서울 미술 전시 안내.\n전시는 11월 30일까지 열립니다.\n관람료는 무료입니다.\n누구나 관람할 수 있습니다.'
        base = host(body, D2)
        result = self.decide(base, period_facts(event_period={'unknown_reason': '연도 없음'}))
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])
        self.assertIsNone(result['record'])

    def test_year_less_end_date_blocks_ongoing_even_with_recent_post(self):
        body = O1 + '\n신청은 11월 30일까지 받습니다.'
        result = self.decide(host(body, O2), ongoing_facts())
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])

    def test_period_year_must_be_in_the_quote(self):
        body = '서울 미술 전시 안내.\n전시는 11월 30일까지 열립니다.\n관람료는 무료입니다.\n누구나 관람할 수 있습니다.'
        second = '시립미술관 전시 소식.\n전시는 11.30.까지 열립니다.\n관람료는 무료입니다.'
        result = self.decide(host(body, second), period_facts())
        self.assertIn('no_current_evidence', result['reasons'])

    def test_last_year_round_is_held(self):
        b1, b2 = D1.replace('2026', '2025'), D2.replace('2026', '2025')
        result = self.decide(host(b1, b2), period_facts(
            event_period=sup({'start': '2025-11-01', 'end': '2025-11-30'}, 'd1s2', 'd2s2')))
        self.assertFalse(result['publish'])
        self.assertTrue({'no_current_evidence', 'year_trap'} & set(result['reasons']))

    def test_far_future_year_is_a_year_trap(self):
        b1, b2 = D1.replace('2026', '2029'), D2.replace('2026', '2029')
        result = self.decide(host(b1, b2), period_facts(
            event_period=sup({'start': '2029-11-01', 'end': '2029-11-30'}, 'd1s2', 'd2s2')))
        self.assertIn('year_trap', result['reasons'])

    def test_passed_application_deadline_holds_even_if_event_continues(self):
        body = D1 + '\n신청은 2026-11-05 18:00까지입니다.'
        facts = period_facts(application_period=sup({'start': '', 'end': '2026-11-05T18:00+09:00'}, 'd1s5'))
        result = self.decide(host(body, D2), facts)
        self.assertIn('no_current_evidence', result['reasons'])

    def test_future_application_deadline_sets_deadline_at(self):
        body = D1 + '\n신청은 2026-11-20 18:00까지입니다.'
        second = D2 + '\n신청 마감은 2026-11-20 18:00입니다.'
        facts = period_facts(application_period=sup({'start': '', 'end': '2026-11-20T18:00+09:00'}, 'd1s5', 'd2s4'))
        result = self.decide(host(body, second), facts)
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual(result['record']['deadline_at'], '2026-11-20T18:00+09:00')
        self.assertEqual(result['record']['valid_until'], '2026-11-20')

    def test_same_body_two_urls_counts_once(self):
        base = host(docs=[doc(1, D1), doc(2, D1, url='https://www.seoul.go.kr/news/copy')])
        facts = period_facts(fee_status=sup('free', 'd1s3', 'd2s3'), event_period=sup(
            {'start': '2026-11-01', 'end': '2026-11-30'}, 'd1s2', 'd2s2'))
        result = self.decide(base, facts)
        # Grade A (2026-11-10): one official document is enough when its own text states a current, year-dated end.
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual(result['record']['review']['document_count'], 1)

    def test_end_date_from_one_document_publishes_when_year_is_stated(self):
        result = self.decide(host(D1, D2), period_facts(
            event_period=sup({'start': '2026-11-01', 'end': '2026-11-30'}, 'd1s2')))
        self.assertTrue(result['publish'], result['reasons'])

    def test_one_document_still_holds_past_or_ended_items(self):
        past = D1.replace('2026-11-30', '2026-11-05')
        result = self.decide(host(past), period_facts(
            fee_status=sup('free', 'd1s3'), event_period=sup({'start': '2026-11-01', 'end': '2026-11-05'}, 'd1s2')))
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])
        ended = self.decide(host(D1 + '\n지난 행사가 종료되었습니다.'), period_facts(
            fee_status=sup('free', 'd1s3'), event_period=sup({'start': '2026-11-01', 'end': '2026-11-30'}, 'd1s2')))
        self.assertFalse(ended['publish'])
        self.assertIn('past_signal', ended['reasons'])

    def test_one_document_without_year_in_quote_holds(self):
        body = '서울 미술 전시 안내.\n전시는 11월 30일까지입니다.\n관람료는 무료입니다.\n누구나 관람할 수 있습니다.'
        result = self.decide(host(body), period_facts(
            fee_status=sup('free', 'd1s3'), event_period=sup({'start': '', 'end': '2026-11-30'}, 'd1s2')))
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])

    def test_past_signal_in_any_document_holds(self):
        result = self.decide(host(D1, D2 + '\n지난 행사가 종료되었습니다.'), period_facts())
        self.assertFalse(result['publish'])
        self.assertIn('past_signal', result['reasons'])

    def test_past_signal_pattern_is_verbatim(self):
        from benefit_monitor.auto_publish import PAST_SIGNAL
        self.assertEqual(PAST_SIGNAL.pattern,
                         r'종료|마감되었|마감됨|결과\s*발표|지난\s*(?:차수|행사)|\d{4}년\s*(?:행사|차)\s*(?:종료|결과)')

    def test_ongoing_needs_recent_published_and_two_docs(self):
        result = self.decide(host(O1, O2, title='도서 대출'), ongoing_facts())
        self.assertTrue(result['publish'], result['reasons'])
        record = result['record']
        self.assertEqual(record['validity_kind'], 'ongoing')
        self.assertIsNone(record['valid_until'])
        self.assertIsNone(record['deadline_at'])
        self.assertEqual(record['review']['published_at'], '2026-10-01')
        self.assertTrue(record['review']['basis']['operating_quotes'])
        old = O1.replace('2026-10-01', '2026-06-01')
        result = self.decide(host(old, O2), ongoing_facts(published_at=sup('2026-06-01', 'd1s2')))
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])

    def test_ongoing_without_published_or_second_document_holds(self):
        facts = ongoing_facts()
        del facts['published_at']
        self.assertIn('no_current_evidence', self.decide(host(O1, O2), facts)['reasons'])
        one = self.decide(host(O1, O2), ongoing_facts(conditions=sup('상시 대출', 'd1s3')))
        self.assertIn('no_current_evidence', one['reasons'])
        self.assertIn('single_source', one['reasons'])

    def test_published_over_a_year_ago_is_year_trap(self):
        old = O1.replace('2026-10-01', '2025-10-01')
        result = self.decide(host(old, O2), ongoing_facts(published_at=sup('2025-10-01', 'd1s2')))
        self.assertIn('year_trap', result['reasons'])

    def test_takedown_blocks_by_id_and_title_key(self):
        from benefit_monitor.auto_publish import takedown_matches, title_key
        result = self.decide(host(D1, D2), period_facts(),
                             takedowns=[{'candidate_id': 'c1', 'title_key': 'x', 'taken_down_at': NOW.isoformat(), 'note': ''}])
        self.assertIn('taken_down', result['reasons'])
        key = title_key('2026년 서울 미술 전시 (시립)', '서울시')
        self.assertEqual(key, title_key('서울  미술전시[시립]', ' 서울시 '))
        moved = host(D1, D2, title='2026년 서울 미술 전시 (시립)', cid='c-new')
        result = self.decide(moved, period_facts(),
                             takedowns=[{'candidate_id': 'c-old', 'title_key': key, 'taken_down_at': NOW.isoformat(), 'note': ''}])
        self.assertIn('taken_down', result['reasons'])
        self.assertFalse(takedown_matches({'candidate_id': 'c9', 'title_key': 'other'}, [{'candidate_id': 'c1', 'title_key': key}]))
        self.assertFalse(takedown_matches({'candidate_id': 'c9', 'title_key': ''}, [{'candidate_id': 'c1', 'title_key': ''}]))

    def test_disputed_or_missing_core_holds(self):
        disputed = self.decide(host(D1, D2), period_facts(
            conditions={'status': 'disputed', 'value': '누구나 관람', 'ev': ['d1s4', 'd2s1']}))
        self.assertIn('disputed', disputed['reasons'])
        for field in ('summary', 'conditions', 'fee_status', 'eligibility'):
            facts = period_facts(**{field: {'unknown_reason': '원문에 없음'}})
            result = self.decide(host(D1, D2), facts)
            self.assertFalse(result['publish'])
            self.assertIn('core_missing', result['reasons'], field)

    def test_paid_without_cost_holds(self):
        facts = period_facts(fee_status=sup('paid', 'd1s3', 'd2s3'))
        result = self.decide(host(D1, D2), facts)
        self.assertIn('cost_missing', result['reasons'])
        facts['cost_details'] = sup('관람료 안내', 'd1s3')
        result = self.decide(host(D1, D2), facts)
        self.assertNotIn('cost_missing', result['reasons'])
        self.assertEqual(result['record']['fee_status'], 'paid')

    def test_stale_document_holds(self):
        base = host(docs=[doc(1, D1), doc(2, D2, retrieved=NOW - timedelta(hours=31))])
        self.assertIn('stale_check', self.decide(base, period_facts())['reasons'])

    def test_contract_failure_holds(self):
        from benefit_monitor.auto_publish import decide
        base = host(D1, D2)
        draft = draft_for(base, **period_facts())
        draft['records'][0]['facts'][0]['evidence'][0]['quote'] = '원문에 없는 문장'
        result = decide(draft, base, NOW, [])
        self.assertEqual(result, {'publish': False, 'reasons': ['contract'], 'record': None})


    def test_published_at_year_must_be_in_the_quote(self):
        body = O1.replace('게시일 2026-10-01.', '게시일 10.01.')
        result = self.decide(host(body, O2), ongoing_facts())
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])

    def test_ongoing_hidden_ending_phrases_hold(self):
        phrases = ['신청은 11월 30일 오후 6시까지 받습니다.', '신청은 11월 30일 18시까지 받습니다.',
                   '신청은 30일까지 받습니다.', '신청은 11월 말까지 받습니다.', '기간: 11.1 - 11.30',
                   '기간: 11.1 – 11.30', '기간: 11.1 — 11.30', '기간: 11월 1일 ~ 30일',
                   '신청은 11월 30일까지 받습니다.', '기간: ~ 11.30']
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                result = self.decide(host(O1 + '\n' + phrase, O2), ongoing_facts())
                self.assertFalse(result['publish'])
                self.assertIn('no_current_evidence', result['reasons'])

    def test_opening_hours_are_not_an_ending(self):
        from benefit_monitor.auto_publish import ENDING_DATE
        self.assertIsNone(ENDING_DATE.search('운영 시간 09:00~18:00'))
        self.assertIsNone(ENDING_DATE.search(O1 + O2))
        result = self.decide(host(O1 + '\n운영 시간 09:00~18:00', O2), ongoing_facts())
        self.assertTrue(result['publish'], result['reasons'])

    def test_period_item_with_year_less_application_deadline_holds(self):
        result = self.decide(host(D1 + '\n신청은 11월 10일까지 받습니다.', D2), period_facts())
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])

    def test_year_less_deadline_matching_a_current_year_dated_date_publishes(self):
        # 2026-11-09 한강 배달존: "11월 30일까지" beside "2026년 10월 1일~11월 30일" in the same notice.
        for body in (D1 + '\n신청은 11월 30일까지 받습니다.',
                     '서울 미술 전시 안내.\n기간 : 2026년 11월 1일~11월 30일\n관람료는 무료입니다.\n누구나 관람할 수 있습니다.\n11월 30일까지 열립니다.'):
            with self.subTest(body=body):
                result = self.decide(host(body, D2), period_facts())
                self.assertTrue(result['publish'], result['reasons'])

    def test_year_less_deadline_matching_only_another_document_holds(self):
        result = self.decide(host(D1, D2 + '\n신청은 11월 15일까지 받습니다.\n문의 2026-11-15까지'), period_facts())
        self.assertTrue(result['publish'], result['reasons'])
        result = self.decide(host(D1 + '\n신청은 11월 15일까지 받습니다.', D2 + '\n문의 2026-11-15까지'), period_facts())
        self.assertIn('no_current_evidence', result['reasons'])

    def test_year_less_date_equal_to_the_stated_period_end_publishes(self):
        # 2026-11-10 한강 배달존: one notice says "11월 30일까지", the other "2026년 10월 1일~11월 30일".
        body = '서울 미술 전시 안내.\n11월 1일부터 11월 30일까지 열립니다.\n관람료는 무료입니다.\n누구나 관람할 수 있습니다.'
        result = self.decide(host(body, D2), period_facts(event_period=sup(
            {'start': '2026-11-01', 'end': '2026-11-30'}, 'd2s2')))
        self.assertTrue(result['publish'], result['reasons'])
        # A different year-less date (an unrelated, possibly passed deadline) still holds.
        other = body + '\n신청은 11월 5일까지 받습니다.'
        held = self.decide(host(other, D2), period_facts(event_period=sup(
            {'start': '2026-11-01', 'end': '2026-11-30'}, 'd2s2')))
        self.assertIn('no_current_evidence', held['reasons'])

    def test_year_less_deadline_with_day_only_holds(self):
        result = self.decide(host(D1 + '\n신청은 30일까지 받습니다.', D2), period_facts())
        self.assertIn('no_current_evidence', result['reasons'])

    def test_ongoing_item_uses_official_page_posting_date(self):
        # The model left the posting date unknown; the page header date (read by code) decides.
        facts = ongoing_facts(published_at={'unknown_reason': '본문에 없음'})
        for posted, publish in (('2026-10-12', True), ('2026-06-01', False)):
            with self.subTest(posted=posted):
                docs = [doc(1, O1), doc(2, O2)]
                docs[0]['published_at'] = posted
                result = self.decide(host(docs=docs), facts)
                self.assertEqual(result['publish'], publish, result['reasons'])
        result = self.decide(host(O1, O2), facts)
        self.assertIn('no_current_evidence', result['reasons'])

    def test_period_item_with_past_year_dated_deadline_holds(self):
        for phrase in ('신청 2026년 11월 1일까지 받습니다.', '접수는 2026.10.1 ~ 2026.10.31 입니다.',
                       '신청 2026년 10월 말까지 받습니다.', '신청 2026.11.31까지 받습니다.'):
            with self.subTest(phrase=phrase):
                result = self.decide(host(D1 + '\n' + phrase, D2), period_facts())
                self.assertFalse(result['publish'])
                self.assertIn('no_current_evidence', result['reasons'])

    def test_period_item_with_future_year_dated_deadline_publishes(self):
        for phrase in ('신청 2026년 11월 20일까지 받습니다.', '신청 2026년 11월 말까지 받습니다.',
                       '신청 2026년 11월 8일 18시까지 받습니다.', '접수 2026.11.1 ~ 11.20'):
            with self.subTest(phrase=phrase):
                result = self.decide(host(D1 + '\n' + phrase, D2), period_facts())
                self.assertTrue(result['publish'], result['reasons'])

    def test_body_deadline_without_application_period_lowers_the_display_cutoff(self):
        # A future year-dated deadline in the body hides the item after it, not after the event end.
        result = self.decide(host(D1 + '\n신청 2026년 11월 20일까지 받습니다.', D2), period_facts())
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual((result['record']['valid_until'], result['record']['deadline_at']), ('2026-11-20', None))
        result = self.decide(host(D1 + '\n신청 2026년 11월 20일까지, 접수 2026.11.1 ~ 11.15', D2), period_facts())
        self.assertEqual(result['record']['valid_until'], '2026-11-15')
        # A stated time on the deadline day keeps that time (KST).
        result = self.decide(host(D1 + '\n신청 2026년 11월 8일(일) 오후 6시까지 받습니다.', D2), period_facts())
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual((result['record']['valid_until'], result['record']['deadline_at']),
                         ('2026-11-08', '2026-11-08T18:00:00+09:00'))
        from benefit_monitor.validation import validate
        sources = {s['id']: s for s in json.loads((ROOT/'sources.yaml').read_text())['sources']}
        record = result['record']
        validate({k: record[k] for k in ('source', 'url', 'title', 'summary', 'conditions', 'districts', 'valid_from',
                                         'valid_until', 'deadline_at', 'validity_kind', 'fee_status', 'payment_terms',
                                         'labels')}, sources, NOW)

    def test_same_day_body_deadline_past_or_with_an_unreadable_time_holds(self):
        for phrase in ('신청 2026년 11월 8일 오전 10시까지 받습니다.', '신청 2026년 11월 8일 11:30 마감',
                       '신청 2026년 11월 8일 25시까지 받습니다.'):
            with self.subTest(phrase=phrase):
                result = self.decide(host(D1 + '\n' + phrase, D2), period_facts())
                self.assertFalse(result['publish'])
                self.assertIn('no_current_evidence', result['reasons'])

    def test_public_fee_mapping(self):
        from benefit_monitor.auto_publish import public_fee
        self.assertEqual([public_fee(v) for v in ('free', 'paid', 'mixed', 'conditional', 'unknown', None)],
                         ['free', 'paid', 'mixed', 'mixed', 'unknown', 'unknown'])
        facts = period_facts(fee_status=sup('conditional', 'd1s3', 'd2s3'), cost_details=sup('관람료 안내', 'd1s3'))
        result = self.decide(host(D1, D2), facts)
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual(result['record']['fee_status'], 'mixed')

    def test_year_strip_respects_digit_boundaries(self):
        from benefit_monitor.auto_publish import title_key
        self.assertEqual(title_key('제12020회 행사', ''), '제12020회행사|')
        self.assertEqual(title_key('2026년 행사', ''), '행사|')


class AutoPublishIntegrationTests(unittest.TestCase):
    """review_candidates stores the gate result next to the private review queue."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = host(D1, D2)
        (self.root/'sources.yaml').write_text(json.dumps({'sources': [
            {'id': 'seoul', 'name': '서울시', 'domains': ['www.seoul.go.kr'], 'routes': [], 'feed_url': None}]}))

    def run_with(self, base, facts, takedowns=None):
        from benefit_monitor import ai_review
        candidate = {'source': 'seoul', 'url': 'https://www.seoul.go.kr/news/1', 'title': '서울 미술 전시', 'summary': '검토 대기'}
        if takedowns is not None:
            path = self.root/'cache/ai_publish/takedowns.json'; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(takedowns))
        draft = draft_for(base, **facts)
        cid = ai_review.Benefit(**candidate).id
        base = json.loads(json.dumps(base)); base['candidates'][0]['candidate_id'] = cid
        for record in draft['records']:
            record['candidate_id'] = cid
        docs = base['documents']
        with patch.object(ai_review.OfficialReader, 'read', side_effect=lambda c, **k: dict(docs[0], links=[])), \
                patch('benefit_monitor.ai_review._related_docs', return_value=[dict(d, links=[]) for d in docs[1:]]), \
                patch('benefit_monitor.ai_review.invoke', return_value={'status': 'validated_draft', 'run_id': 'e' * 64}), \
                patch('benefit_monitor.ai_review.load_run', return_value=(draft, base)):
            result = ai_review.review_candidates(self.root, [candidate], NOW, 1, True)
        return cid, result

    def test_publish_goes_to_approved_and_hold_records_reasons(self):
        cid, result = self.run_with(self.base, period_facts())
        approved = json.loads((self.root/'cache/ai_publish/approved.json').read_text())
        self.assertEqual(list(approved), [cid])
        self.assertEqual(approved[cid]['review']['document_count'], 2)
        decisions = json.loads((self.root/'cache/ai_publish/decisions.json').read_text())
        self.assertTrue(decisions[cid]['publish'])
        queued = json.loads(next((self.root/'cache/ai_review/queue').glob('*.json')).read_text())
        self.assertEqual(queued['review_status'], 'pending_human_review')
        # Later the same candidate is taken down: it leaves approved and keeps the reasons.
        (self.root/'cache/ai_review/state.json').unlink()
        cid, _ = self.run_with(self.base, period_facts(), takedowns=[{'candidate_id': cid, 'title_key': '', 'taken_down_at': NOW.isoformat(), 'note': ''}])
        self.assertEqual(json.loads((self.root/'cache/ai_publish/approved.json').read_text()), {})
        decisions = json.loads((self.root/'cache/ai_publish/decisions.json').read_text())
        self.assertFalse(decisions[cid]['publish'])
        self.assertIn('taken_down', decisions[cid]['reasons'])

    def test_unchanged_held_draft_is_redecided_without_a_model_call(self):
        # Approved 2026-11-12: a held draft whose pages are byte-identical is decided again by the
        # current gate (free, deterministic). The pages were just re-read, so the freshness clock restarts.
        from benefit_monitor import ai_review
        candidate = {'source': 'seoul', 'url': 'https://www.seoul.go.kr/news/1', 'title': '서울 미술 전시', 'summary': '검토 대기'}
        cid = ai_review.Benefit(**candidate).id
        base = json.loads(json.dumps(self.base)); base['candidates'][0]['candidate_id'] = cid
        docs = base['documents']

        def run(facts, now, model):
            draft = draft_for(base, **facts)
            for record in draft['records']:
                record['candidate_id'] = cid
            with patch.object(ai_review.OfficialReader, 'read', side_effect=lambda c, **k: dict(docs[0], links=[])), \
                    patch('benefit_monitor.ai_review._related_docs', return_value=[dict(d, links=[]) for d in docs[1:]]), \
                    patch('benefit_monitor.ai_review.invoke', return_value={'status': 'validated_draft', 'run_id': 'e' * 64}) as invoke, \
                    patch('benefit_monitor.ai_review.load_run', return_value=(draft, base)):
                result = ai_review.review_candidates(self.root, [candidate], now, 1, True)
            self.assertEqual(invoke.called, model)
            return result

        held = period_facts(conditions={'unknown_reason': '원문에 없음'})
        run(held, NOW, True)
        # A stored run that can no longer be read changes nothing.
        with patch('benefit_monitor.ai_review.auto_decide', return_value={'publish': False, 'reasons': ['contract'], 'record': None}):
            with patch.object(ai_review.OfficialReader, 'read', side_effect=lambda c, **k: dict(docs[0], links=[])), \
                    patch('benefit_monitor.ai_review._related_docs', return_value=[dict(d, links=[]) for d in docs[1:]]), \
                    patch('benefit_monitor.ai_review.invoke') as invoke:
                ai_review.review_candidates(self.root, [candidate], NOW + timedelta(days=1), 1, True)
            self.assertFalse(invoke.called)
        self.assertEqual(json.loads((self.root/'cache/ai_publish/decisions.json').read_text())[cid]['reasons'], ['core_missing'])
        self.assertEqual(json.loads((self.root/'cache/ai_publish/approved.json').read_text()), {})
        later = NOW + timedelta(days=2)
        result = run(period_facts(), later, False)
        approved = json.loads((self.root/'cache/ai_publish/approved.json').read_text())
        self.assertEqual(list(approved), [cid])
        self.assertEqual(approved[cid]['review']['checked_at'], later.isoformat())
        self.assertEqual(result['auto_published'], 1)
        decisions = json.loads((self.root/'cache/ai_publish/decisions.json').read_text())
        self.assertTrue(decisions[cid]['publish'])
        # Already published and unchanged: left alone, no second decision.
        run(held, later + timedelta(hours=1), False)
        self.assertEqual(list(json.loads((self.root/'cache/ai_publish/approved.json').read_text())), [cid])

    def test_held_draft_the_gate_would_now_publish_is_read_before_older_items(self):
        # Approved 2026-11-13: such drafts jump the oldest-checked rotation (local check, no model call).
        from benefit_monitor import ai_review
        older = {'source': 'seoul', 'url': 'https://www.seoul.go.kr/news/2', 'title': '서울 음악회', 'summary': '검토 대기'}
        ready = {'source': 'seoul', 'url': 'https://www.seoul.go.kr/news/1', 'title': '서울 미술 전시', 'summary': '검토 대기'}
        old_id, ready_id = ai_review.Benefit(**older).id, ai_review.Benefit(**ready).id
        path = self.root/'cache/ai_review/state.json'; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'items': {
            old_id: {'model_status': 'validated_draft', 'run_id': 'a' * 64, 'last_checked_at': '2026-11-01T00:00:00+09:00'},
            ready_id: {'model_status': 'validated_draft', 'run_id': 'b' * 64, 'last_checked_at': '2026-11-07T00:00:00+09:00'}}}))
        verdict = {'a' * 64: False, 'b' * 64: True}
        read = []

        def fail(candidate, **k):
            read.append(candidate['url'])
            raise OSError('offline')
        with patch('benefit_monitor.ai_review.auto_decide', side_effect=lambda r, run, n, reread=False: {'publish': verdict[run], 'reasons': [], 'record': None}), \
                patch.object(ai_review.OfficialReader, 'read', side_effect=fail):
            ai_review.review_candidates(self.root, [older, ready], NOW, 1, False)
        self.assertEqual(read, [ready['url'], older['url']])

    def test_corrupt_takedowns_or_decide_crash_hold_without_crashing(self):
        from benefit_monitor import ai_review
        path = self.root/'cache/ai_publish/takedowns.json'; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{not json')
        with patch('benefit_monitor.ai_review.load_run', return_value=(draft_for(self.base, **period_facts()), self.base)):
            self.assertEqual(ai_review.auto_decide(self.root, 'f' * 64, NOW)['reasons'], ['contract'])
            path.write_text(json.dumps(['junk', 3, {'candidate_id': 'zz', 'title_key': ''}]))
            self.assertTrue(ai_review.auto_decide(self.root, 'f' * 64, NOW)['publish'])
            with patch('benefit_monitor.auto_publish.decide', side_effect=RuntimeError('boom')):
                self.assertEqual(ai_review.auto_decide(self.root, 'f' * 64, NOW)['reasons'], ['contract'])
        path.write_text('{not json')
        cid, result = self.run_with(self.base, period_facts())
        decisions = json.loads((self.root/'cache/ai_publish/decisions.json').read_text())
        self.assertEqual(decisions[cid]['reasons'], ['contract'])

    def test_rereading_an_approved_page_that_changed_or_is_gone_withdraws_whatever_the_model_says(self):
        import io
        from urllib.error import HTTPError
        from benefit_monitor import ai_review
        candidate = {'source': 'seoul', 'url': 'https://www.seoul.go.kr/news/1', 'title': '서울 미술 전시', 'summary': '검토 대기'}
        cid = ai_review.Benefit(**candidate).id
        base = json.loads(json.dumps(self.base)); base['candidates'][0]['candidate_id'] = cid
        draft = draft_for(base, **period_facts())
        for record in draft['records']:
            record['candidate_id'] = cid
        published = __import__('benefit_monitor.auto_publish', fromlist=['decide']).decide(draft, base, NOW, [])['record']
        changed = dict(base['documents'][0], body=D1 + '\n신청은 마감되었습니다.', body_hash='9' * 64, links=[])

        def gone(c, **k):
            raise HTTPError(c['url'], 404, 'gone', {}, io.BytesIO())
        for read, model, reason in ((lambda c, **k: changed, 'rejected_draft', 'body_changed'),
                                    (lambda c, **k: changed, 'stopped_before_result', 'body_changed'),
                                    (lambda c, **k: changed, 'credit_exhausted', 'body_changed'),
                                    (gone, None, 'source_gone')):
            with self.subTest(model=model, reason=reason):
                path = self.root/'cache/ai_publish/approved.json'; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({cid: dict(published, decided_at=NOW.isoformat())}))
                (self.root/'cache/ai_review/state.json').unlink(missing_ok=True)
                with patch.object(ai_review.OfficialReader, 'read', side_effect=read), \
                        patch('benefit_monitor.ai_review._related_docs', return_value=[]), \
                        patch('benefit_monitor.ai_review.invoke', return_value={'status': model, 'run_id': None}):
                    ai_review.review_candidates(self.root, [candidate], NOW, 1, True)
                record = json.loads(path.read_text())[cid]
                self.assertEqual((record.get('status'), record.get('withdrawn_reason')), ('withdrawn', reason))
        # An unchanged page is left as it is.
        path.write_text(json.dumps({cid: dict(published, decided_at=NOW.isoformat())}))
        (self.root/'cache/ai_review/state.json').unlink(missing_ok=True)
        with patch.object(ai_review.OfficialReader, 'read', side_effect=lambda c, **k: dict(base['documents'][0], links=[])), \
                patch('benefit_monitor.ai_review._related_docs', return_value=[]), \
                patch('benefit_monitor.ai_review.invoke', return_value={'status': 'rejected_draft', 'run_id': None}):
            ai_review.review_candidates(self.root, [candidate], NOW, 1, True)
        self.assertNotIn('status', json.loads(path.read_text())[cid])

    def test_missing_run_output_is_held_as_contract(self):
        from benefit_monitor import ai_review
        with patch('benefit_monitor.ai_review.load_run', side_effect=FileNotFoundError):
            self.assertEqual(ai_review.auto_decide(self.root, 'f' * 64, NOW)['reasons'], ['contract'])


# Approved 2026-11-12 ("123 진행해"): birth-date ranges, year-less dates read from the official
# page's posting date, and live official reservation listings (eshare).
BIRTH = '대상: 기초생활수급자(1962. 1. 1. ~ 1976. 12. 31. 출생자)'
ESHARE_BOILER = ('※ 평상데크는 5/1 ~ 10/31까지, 9시~당일19시까지만 이용 가능합니다.')
E1 = ('자원 명칭 요가(오전반)\n' + ESHARE_BOILER + '\n예약 방법 온라인 직접 예약\n'
      '종암동 자치회관 프로그램 요가 월,수,금 11:00~12:00\n이용 요금 수강료 75,000원 (분기)\n이용 대상 제한 없음')
E_OTHER = '자원 명칭 노래교실(수요반)\n' + ESHARE_BOILER + '\n노래교실 수 14:00~16:00'


def eshare_host(*bodies, posted=None):
    docs = [doc(i, b, url=f'https://www.eshare.go.kr/UserPortal/Upv/UprResrcEdu/index.do?rsrc_no=E{i}')
            for i, b in enumerate(bodies, 1)]
    for d in docs:
        d['source_id'] = 'eshare'
        d['published_at'] = posted
    base = host(docs=docs, title='[공유누리] 요가(오전반)', cid='e' * 24)
    base['candidates'][0]['source_id'] = 'eshare'
    return base


def eshare_facts(**over):
    facts = dict(summary=sup('자치회관 요가 강좌', 'd1s4'), conditions=sup('온라인 직접 예약', 'd1s3'),
                 fee_status=sup('paid', 'd1s5'), cost_details=sup('수강료 75,000원(분기)', 'd1s5'),
                 eligibility=sup(ANYONE, 'd1s6'))
    facts.update(over)
    return facts


class DateReadingTests(unittest.TestCase):
    def decide(self, base, facts, now=NOW):
        from benefit_monitor.auto_publish import decide
        return decide(draft_for(base, **facts), base, now, [])

    # 1. Eligibility ranges such as birth dates are not deadlines of the item.
    def test_birth_date_range_does_not_hold_period_item(self):
        result = self.decide(host(D1 + '\n' + BIRTH, D2), period_facts())
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual(result['record']['valid_until'], '2026-11-30')

    def test_birth_date_range_does_not_hold_ongoing_item(self):
        result = self.decide(host(O1 + '\n' + BIRTH, O2, title='도서 대출'), ongoing_facts())
        self.assertTrue(result['publish'], result['reasons'])

    def test_range_ending_last_year_still_holds(self):
        # Only ranges ending two or more years back are reference ranges; last year's could be this item's.
        for phrase in ('접수는 2025. 11. 1. ~ 2025. 11. 30. 입니다.', '신청 2025년 12월 31일까지'):
            with self.subTest(phrase=phrase):
                result = self.decide(host(D1 + '\n' + phrase, D2), period_facts())
                self.assertIn('no_current_evidence', result['reasons'])

    # 2. Year-less dates take their year from the official page posting date read by code.
    def year_less(self, posted, end='2026-11-18', body_extra=''):
        d1 = '이마트 와인장터 안내.\n와인장터는 오는 11월 12일(목)부터 18일(수)까지 열립니다.\n관람료는 무료입니다.\n누구나 참여할 수 있습니다.' + body_extra
        docs = [doc(1, d1), doc(2, D2)]
        docs[0]['published_at'] = posted
        facts = period_facts(event_period=sup({'start': '2026-11-12', 'end': end}, 'd1s2'))
        return self.decide(host(docs=docs), facts)

    def test_year_less_period_uses_page_posting_date(self):
        result = self.year_less('2026-11-05')
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual(result['record']['valid_until'], '2026-11-18')

    def test_year_less_period_without_posting_date_holds(self):
        self.assertIn('no_current_evidence', self.year_less(None)['reasons'])

    def test_year_less_period_with_other_year_holds(self):
        # The model's year must equal the year the posting date gives.
        self.assertIn('no_current_evidence', self.year_less('2026-11-05', end='2027-11-18')['reasons'])

    def test_year_less_period_from_old_posting_holds(self):
        # Posted 2025-11-05: "11월 18일" is 2025-11-18, so the model's 2026 claim is not supported.
        result = self.year_less('2025-11-05')
        self.assertFalse(result['publish'])
        self.assertIn('no_current_evidence', result['reasons'])

    def test_year_less_body_deadline_uses_posting_date(self):
        # Current: kept and narrows the display; already past: holds.
        result = self.year_less('2026-11-05', body_extra='\n사전 신청은 11월 15일까지 받습니다.')
        self.assertTrue(result['publish'], result['reasons'])
        self.assertEqual(result['record']['valid_until'], '2026-11-15')
        result = self.year_less('2026-11-05', body_extra='\n사전 신청은 11월 5일까지 받았습니다.')
        self.assertIn('no_current_evidence', result['reasons'])

    def test_day_only_phrase_without_nearby_month_holds(self):
        # The month is borrowed only from a date written just before, in the same sentence.
        for extra in ('\n신청은 17일까지 받습니다.', '\n11월 12일 개막. 신청은 17일까지 받습니다.'):
            with self.subTest(extra=extra):
                self.assertIn('no_current_evidence', self.year_less('2026-11-05', body_extra=extra)['reasons'])

    def test_year_less_date_near_new_year_reads_next_year(self):
        from benefit_monitor.auto_publish import year_from_posting
        from datetime import date
        self.assertEqual(year_from_posting(1, 5, date(2026, 12, 20)), date(2027, 1, 5))
        self.assertEqual(year_from_posting(12, 28, date(2027, 1, 5)), date(2026, 12, 28))
        self.assertEqual(year_from_posting(9, 19, date(2026, 11, 9)), date(2026, 9, 19))
        self.assertIsNone(year_from_posting(5, 20, date(2026, 11, 9)))  # half a year away: unreadable
        self.assertIsNone(year_from_posting(2, 30, date(2026, 11, 9)))

    # 3. Live official reservation listings (eshare) need only their own page.
    def test_eshare_listing_publishes_from_its_own_page(self):
        result = self.decide(eshare_host(E1, E_OTHER), eshare_facts())
        self.assertTrue(result['publish'], result['reasons'])
        record = result['record']
        self.assertEqual(record['validity_kind'], 'ongoing')
        self.assertEqual(record['review']['published_at'], NOW.date().isoformat())
        self.assertEqual(record['review']['document_count'], 1)
        from benefit_monitor.auto_release import candidate, display_until
        sources = {s['id']: s for s in json.loads((ROOT/'sources.yaml').read_text())['sources']}
        item = candidate(record, sources)
        self.assertIsNotNone(item)
        self.assertTrue(display_until(record, item, NOW))

    def test_eshare_listing_with_course_period_holds(self):
        body = E1 + '\n수강 기간 2026. 9. 1. ~ 2026. 11. 30.'
        self.assertIn('no_current_evidence', self.decide(eshare_host(body), eshare_facts())['reasons'])

    def test_eshare_evidence_from_another_resource_holds(self):
        facts = eshare_facts(summary=sup('노래교실', 'd2s3'), conditions=sup('노래교실', 'd2s3'))
        self.assertFalse(self.decide(eshare_host(E1, E_OTHER), facts)['publish'])

    def test_eshare_still_needs_core_facts(self):
        facts = eshare_facts(eligibility={'unknown_reason': '이용 대상 비어 있음'})
        self.assertIn('core_missing', self.decide(eshare_host(E1), facts)['reasons'])

    def test_other_sources_keep_two_documents_for_ongoing(self):
        one = self.decide(host(O1, O2), ongoing_facts(conditions=sup('상시 대출', 'd1s3')))
        self.assertIn('single_source', one['reasons'])


if __name__ == '__main__':
    unittest.main()
