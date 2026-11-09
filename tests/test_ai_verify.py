"""AI verification (kind verify): wire contract and host checks. Synthetic inputs only; no API."""
from datetime import datetime, timedelta
import hashlib
import unittest
from zoneinfo import ZoneInfo

from benefit_monitor import wire_format as w
from benefit_monitor import verify_contract as vc

KST = ZoneInfo('Asia/Seoul')
NOW = datetime(2026, 11, 9, 9, tzinfo=KST)
BODY = ('이마트24 제휴 서비스 안내.\nKT멤버십 VVIP / VIP 1,000원당 100원 차감 할인.\n'
        'GOLD / SILVER / WHITE / 일반 1,000원당 50원 차감 할인.\n일 1회 이용 가능합니다.')
ENDED = '2026 서울안전한마당 안내.\n기간 : 2026년 9월 17일~9월 19일\n행사가 종료되었습니다.'
CURRENT = '한강 배달존 특별 이벤트.\n기간 : 2026년 10월 1일~11월 30일\n2만 5,000원 이상 주문 시 할인.'


def doc(body, url='https://emart24.co.kr/service/alliance', source='emart24'):
    return dict(id='doc-1', source_id=source, requested_url=url, final_url=url, publisher_type='unknown',
                document_role='notice', retrieved_at=(NOW - timedelta(minutes=5)).isoformat(), published_at=None,
                body_hash=hashlib.sha256(body.encode()).hexdigest(), hash_algorithm='sha256-utf8-exact',
                extraction_scope='test', fetch_status='ok', body=body)


def audit_host(body=BODY, claims=None):
    claims = claims or [dict(claim_id='c1', field='conditions', text='VVIP·VIP·GOLD는 1천 원당 100원'),
                        dict(claim_id='c2', field='conditions', text='하루 1회')]
    return dict(schema_version=vc.INPUT, mode='api_agent', synthetic=False, now=NOW.isoformat(), purpose='audit',
                item=dict(item_id='a'*24, source_id='emart24', title='제휴 서비스', claims=claims), documents=[doc(body)])


def triage_host(body):
    return dict(schema_version=vc.INPUT, mode='api_agent', synthetic=False, now=NOW.isoformat(), purpose='triage',
                item=dict(item_id='b'*24, source_id='seoul', title='행사', claims=[]),
                documents=[doc(body, 'https://mediahub.seoul.go.kr/archives/1', 'seoul')])


def wire(status='unclear', status_ids=(), claims=()):
    return dict(wire_version=vc.WIRE, item_status=status, status_segment_ids=list(status_ids),
                claims=[dict(claim_id=c, verdict=v, segment_ids=list(ids), official_text=t) for c, v, ids, t in claims])


class WireTests(unittest.TestCase):
    def test_schema_fits_grammar_limits(self):
        found = w.check_limits(vc.wire_schema())
        self.assertEqual((found['unions'], found['patterns'], found['unsupported']), (0, 0, []))

    def test_model_sees_numbered_segments_not_hashes(self):
        model = vc.model_input(audit_host())
        self.assertNotIn('body', model['documents'][0])
        self.assertEqual(model['documents'][0]['segments'][1]['id'], 'd1s2')
        self.assertEqual([c['claim_id'] for c in model['item']['claims']], ['c1', 'c2'])

    def test_quotes_come_from_the_document_never_the_model(self):
        result = vc.from_wire(wire(claims=[('c1', 'contradicted', ['d1s3'], 'GOLD 50원'),
                                           ('c2', 'supported', ['d1s4'], '')]), audit_host())
        c1 = result['claims'][0]
        self.assertEqual(c1['quotes'], ['GOLD / SILVER / WHITE / 일반 1,000원당 50원 차감 할인.'])
        self.assertEqual(c1['claim_text'], 'VVIP·VIP·GOLD는 1천 원당 100원')

    def test_unknown_segment_missing_or_extra_claim_is_rejected(self):
        for bad in (wire(claims=[('c1', 'supported', ['d9s9'], ''), ('c2', 'supported', ['d1s4'], '')]),
                    wire(claims=[('c1', 'supported', ['d1s3'], '')]),
                    wire(claims=[('c1', 'supported', ['d1s3'], ''), ('c2', 'supported', ['d1s4'], ''),
                                 ('c3', 'supported', ['d1s4'], '')]),
                    wire(claims=[('c1', 'contradicted', [], 'x'), ('c2', 'supported', ['d1s4'], '')]),
                    dict(wire(), wire_version='other')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                vc.from_wire(bad, audit_host())


class DecisionTests(unittest.TestCase):
    def decide(self, host, draft):
        return vc.decide(vc.from_wire(draft, host), host, NOW)

    def test_cited_contradiction_holds_the_public_item(self):
        result = self.decide(audit_host(), wire(claims=[('c1', 'contradicted', ['d1s3'], 'GOLD 50원'),
                                                        ('c2', 'supported', ['d1s4'], '')]))
        self.assertEqual(result['action'], 'hold')
        self.assertEqual([f['claim_id'] for f in result['findings']], ['c1'])

    def test_supported_or_not_found_never_holds(self):
        result = self.decide(audit_host(), wire(claims=[('c1', 'not_found', [], ''), ('c2', 'supported', ['d1s4'], '')]))
        self.assertEqual(result['action'], 'none')

    def test_ended_needs_a_past_year_dated_end_or_ending_words(self):
        result = self.decide(triage_host(ENDED), wire('ended', ['d1s2']))
        self.assertEqual(result['action'], 'dismiss')
        self.assertEqual(result['reason'], 'ended')

    def test_ended_claim_on_a_current_notice_is_ignored(self):
        result = self.decide(triage_host(CURRENT), wire('ended', ['d1s2']))
        self.assertEqual(result['action'], 'none')

    def test_ended_without_a_year_or_cited_segment_is_ignored(self):
        body = '행사 안내.\n9월 19일까지 열렸습니다.\n많은 참여 바랍니다.'
        self.assertEqual(self.decide(triage_host(body), wire('ended', ['d1s2']))['action'], 'none')
        self.assertEqual(self.decide(triage_host(ENDED), wire('ended', []))['action'], 'none')

    def test_document_with_a_later_current_date_is_never_dismissed_as_ended(self):
        body = ENDED + '\n다음 회차는 2026년 12월 5일까지 신청을 받습니다.'
        self.assertEqual(self.decide(triage_host(body), wire('ended', ['d1s3']))['action'], 'none')

    def test_not_benefit_needs_a_cited_segment(self):
        body = '시청 인사 발령 안내.\n과장급 인사 발령 명단입니다.\n문의는 총무과로 합니다.'
        self.assertEqual(self.decide(triage_host(body), wire('not_benefit', ['d1s2']))['action'], 'dismiss')
        self.assertEqual(self.decide(triage_host(body), wire('not_benefit', []))['action'], 'none')

    def test_ongoing_is_a_priority_mark_only(self):
        result = self.decide(triage_host(CURRENT), wire('ongoing', ['d1s2']))
        self.assertEqual((result['action'], result['reason']), ('prioritize', 'ongoing'))


if __name__ == '__main__':
    unittest.main()


import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import cost_policy

ROOT = Path(__file__).resolve().parents[1]


class Response(io.BytesIO):
    headers = {'Content-Type': 'text/html; charset=utf-8'}


class PipelineTests(unittest.TestCase):
    """cli.run(ai_review=True): verification runs before observe, so a hold applies the same run."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'sources.yaml').write_text(json.dumps({'sources': [
            {'id': 'seoul', 'domains': ['www.seoul.go.kr'], 'routes': [], 'feed_url': 'https://www.seoul.go.kr/feed'}]}))
        for name in ('README.md', 'research.md', 'research-extraction.md', 'schemas/research-extraction-v3.schema.json'):
            path = self.root/'docs/ai'/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('테스트용 지침')
        self.approved = dict(source='seoul', url='https://www.seoul.go.kr/news/1', title='제휴 할인', summary='KT 할인',
                             conditions='GOLD는 1천 원당 100원 할인. 하루 1회.', needs_recheck=False,
                             verified_at=(NOW - timedelta(days=3)).isoformat(), valid_until='2026-11-30', evidence='승인 근거')
        self.candidate = dict(source='seoul', url='https://www.seoul.go.kr/news/2', title='지난 행사', summary='검토 대기', needs_recheck=True)
        (self.root/'inputs').mkdir(); (self.root/'inputs/items.json').write_text(json.dumps([self.approved], ensure_ascii=False))
        self.page = '<html><main>공식 안내 본문입니다. 제휴 멤버십 할인 조건을 안내합니다. GOLD 1,000원당 50원 차감 할인. 행사는 2026년 9월 19일 종료되었습니다. 자세한 사항은 고객센터로 문의하시기 바랍니다.</main></html>'.encode()
        cost_policy.reset(60)

    def transport(self, request):
        return Response(b'User-agent: *\nAllow: /' if request.full_url.endswith('/robots.txt') else self.page)

    def run_ai(self, decisions, now=NOW):
        from benefit_monitor import cli
        calls = []
        def fake_invoke(root, kind, path):
            host = json.loads(Path(path).read_text())
            calls.append((kind, host['purpose']))
            return {'status': 'validated_draft', 'run_id': host['purpose']}
        def fake_result(run_id):
            return decisions[run_id]
        with patch('benefit_monitor.official_reader.network_open', side_effect=self.transport), \
             patch('benefit_monitor.cli.collect', return_value=[self.candidate]), \
             patch('benefit_monitor.ai_verify.invoke', side_effect=fake_invoke), \
             patch('benefit_monitor.ai_verify._result', side_effect=fake_result), \
             patch('benefit_monitor.ai_review.invoke', side_effect=AssertionError('no research call')):
            report = cli.run(self.root, self.root/'inputs/items.json', True, now, ai_review=True,
                             ai_execute=True, ai_max_candidates=1, ai_max_verify=5)
        return report, calls

    def contradiction(self):
        return dict(schema_version='verify-result-v1', purpose='audit', item_id='x', item_status='ongoing', status_quotes=[],
                    claims=[dict(claim_id='c1', field='summary', claim_text='KT 할인', verdict='supported', quotes=['q'], official_text=''),
                            dict(claim_id='c2', field='conditions', claim_text='GOLD는 1천 원당 100원 할인.', verdict='contradicted',
                                 quotes=['GOLD 1,000원당 50원 차감 할인.'], official_text='GOLD 50원'),
                            dict(claim_id='c3', field='conditions', claim_text='하루 1회.', verdict='not_found', quotes=[], official_text=''),
                            dict(claim_id='c4', field='period', claim_text='기간 ~2026-11-30', verdict='not_found', quotes=[], official_text='')])

    def ended(self):
        return dict(schema_version='verify-result-v1', purpose='triage', item_id='y', item_status='ended',
                    status_quotes=['행사는 2026년 9월 19일 종료되었습니다.'], claims=[])

    def test_contradiction_withholds_the_public_item_and_ended_candidate_leaves_queue(self):
        report, calls = self.run_ai({'audit': self.contradiction(), 'triage': self.ended()})
        self.assertEqual(sorted(calls), [('verify', 'audit'), ('verify', 'triage')])
        self.assertEqual(report['ai_verify']['held'], 1)
        self.assertEqual(report['ai_verify']['dismissed'], 1)
        self.assertEqual([i['url'] for i in report['needs_recheck'] if i.get('verified_at')], [self.approved['url']])
        reasons = {r['reason'] for r in report['review_queue']}
        self.assertEqual(reasons, {'ai_contradicted'})
        findings = json.loads((self.root/'cache/ai_verify/findings.json').read_text())
        self.assertEqual(list(findings.values())[0]['claims'][0]['official_quotes'], ['GOLD 1,000원당 50원 차감 할인.'])

    def test_public_quality_summary_has_no_model_text(self):
        from benefit_monitor.publish import ai_quality
        from benefit_monitor.store import load
        report, _ = self.run_ai({'audit': self.contradiction(), 'triage': self.ended()})
        summary = ai_quality(self.root, report, load(self.root/'cache/operational_state.json', {}))
        self.assertEqual((summary['held'], summary['dismissed'], summary['last_run_checked']), (1, 1, 2))
        self.assertEqual(summary['findings'][0]['claims'],
                         [{'claim': 'GOLD는 1천 원당 100원 할인.', 'official_quotes': ['GOLD 1,000원당 50원 차감 할인.']}])
        self.assertNotIn('GOLD 50원', json.dumps(summary, ensure_ascii=False).replace('GOLD 1,000원당 50원', ''))

    def test_same_body_is_not_paid_for_again_and_dismissed_candidate_is_not_researched(self):
        self.run_ai({'audit': self.contradiction(), 'triage': self.ended()})
        report, calls = self.run_ai({}, NOW + timedelta(days=AUDIT_DAYS_PLUS))
        self.assertEqual(calls, [])  # audit within 7 days unchanged; dismissed candidate never triaged or researched
        self.assertEqual(report['ai_verify']['unchanged'], 0)

    def test_three_calls_without_result_stop_the_day(self):
        from benefit_monitor import cli
        more = [dict(self.candidate, url=f'https://www.seoul.go.kr/news/{n}') for n in range(3, 9)]
        calls = []
        def stopped(root, kind, path):
            calls.append(kind); return {'status': 'stopped_before_result', 'run_id': None}
        with patch('benefit_monitor.official_reader.network_open', side_effect=self.transport), \
             patch('benefit_monitor.cli.collect', return_value=[self.candidate] + more), \
             patch('benefit_monitor.ai_verify.invoke', side_effect=stopped), \
             patch('benefit_monitor.ai_review.invoke', return_value={'status': 'rejected_draft', 'run_id': None}):
            report = cli.run(self.root, self.root/'inputs/items.json', True, NOW, ai_review=True,
                             ai_execute=True, ai_max_candidates=1, ai_max_verify=8)
        self.assertEqual((len(calls), report['ai_verify']['stopped']), (3, 'no_results'))

    def test_without_verify_budget_nothing_is_checked(self):
        from benefit_monitor import cli
        with patch('benefit_monitor.official_reader.network_open', side_effect=AssertionError('no fetch')), \
             patch('benefit_monitor.cli.collect', return_value=[]), \
             patch('benefit_monitor.ai_review.invoke', side_effect=AssertionError('no call')):
            report = cli.run(self.root, self.root/'inputs/items.json', True, NOW, ai_review=True, ai_execute=True, ai_max_candidates=1)
        self.assertEqual(report['ai_verify']['checked'], 0)


AUDIT_DAYS_PLUS = 1
