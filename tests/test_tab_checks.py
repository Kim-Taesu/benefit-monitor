"""Stage 2 checks (2026-11-20): health-notice triage and festival fee notes; code decides what is hidden or noted."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import festival_check, notice_triage, tab_checks
from benefit_monitor.store import load, save

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat('2026-11-21T03:50:00+09:00')


def notice(n, title, dept='보건행정과'):
    return {'id': f'id{n}', 'title': title, 'url': f'https://www.gwangjin.go.kr/health/bbs/view.do?nttId={n}',
            'date': '2026-11-16', 'dept': dept, 'hint': False}


def health(*items):
    return {'boards': [{'district': '광진구', 'items': list(items)}]}


def festival(fid, fee_status='free', summary='', programs='', discount=''):
    return {'id': fid, 'name': '빛 축제', 'start': '2026-11-19', 'end': '2026-11-21', 'place': '광장',
            'fee_status': fee_status, 'fee_text': '무료' if fee_status == 'free' else '',
            'summary': summary, 'programs': programs, 'discount': discount}


class NoticeTriageTests(unittest.TestCase):
    def test_host_and_review(self):
        batch = notice_triage.notices(health(notice(1, '독감 예방접종 안내'), notice(2, '기간제 근로자 채용 공고')))
        host = notice_triage.host(batch, NOW)
        self.assertEqual([n['id'] for n in host['notices']], ['n0', 'n1'])
        self.assertNotIn('url', notice_triage.model_input(host)['notices'][0])
        ok = {'results': [{'id': 'n0', 'reason': 'service'}, {'id': 'n1', 'reason': 'recruitment'}]}
        self.assertEqual(notice_triage.review(ok, host), [])
        self.assertEqual(notice_triage.review({'results': ok['results'][:1]}, host), ['ids_mismatch'])
        self.assertEqual(notice_triage.review({'results': [{'id': 'n0', 'reason': 'spam'}, ok['results'][1]]}, host),
                         ['result_shape'])
        self.assertIsNone(notice_triage.host([], NOW))
        self.assertIsNone(notice_triage.host(batch * 16, NOW))

    def test_code_hides_only_with_a_supporting_title_word(self):
        self.assertEqual(notice_triage.hidden_reason('보건소 기간제 근로자 채용 공고', 'recruitment'), 'recruitment')
        self.assertEqual(notice_triage.hidden_reason('청소 용역 입찰 공고', 'bid'), 'bid')
        self.assertEqual(notice_triage.hidden_reason('금연 지원 사업 선정 결과 안내', 'result'), 'result')
        self.assertEqual(notice_triage.hidden_reason('공시송달 공고', 'legal'), 'legal')
        self.assertEqual(notice_triage.hidden_reason('급식관리지원센터 직원(계약직) 모집공고', 'recruitment'), 'recruitment')
        # The model said "administrative" but the title has no word for it: it stays visible.
        self.assertIsNone(notice_triage.hidden_reason('금연클리닉 참여자 모집', 'recruitment'))
        self.assertIsNone(notice_triage.hidden_reason('치매 예방 특강', 'personnel'))
        self.assertIsNone(notice_triage.hidden_reason('보건소 기간제 근로자 채용 공고', 'unclear'))

    def test_public_and_recheck_follow_the_current_title_and_unhide(self):
        bundle = health(notice(1, '보건소 기간제 근로자 채용 공고'), notice(2, '독감 예방접종 안내'))
        rows = notice_triage.notices(bundle)
        state = {notice_triage.notice_key(rows[0]['url'], rows[0]['title']): {'reason': 'recruitment'},
                 notice_triage.notice_key(rows[1]['url'], rows[1]['title']): {'reason': 'service'}}
        public = notice_triage.public(state, bundle, [])
        self.assertEqual(public, [{'url': rows[0]['url'], 'title': rows[0]['title'], 'reason': 'recruitment'}])
        self.assertEqual(notice_triage.recheck(public, bundle, []), public)
        # A changed title, a removed notice or an admin unhide drops the row.
        renamed = health(dict(notice(1, '보건소 기간제 근로자 채용 공고(재공고)')))
        self.assertEqual(notice_triage.recheck(public, renamed, []), [])
        self.assertEqual(notice_triage.public(state, renamed, []), [])
        self.assertEqual(notice_triage.recheck(public, bundle, [{'kind': 'notice_unhide', 'url': rows[0]['url']}]), [])
        forged = [dict(public[0], reason='bid')]
        self.assertEqual(notice_triage.recheck(forged, bundle, []), [])


class FestivalCheckTests(unittest.TestCase):
    def host(self, *items):
        return festival_check.host(list(items), NOW)

    def test_review_requires_quotes_from_the_festival_text(self):
        item = festival('a', summary='누구나 무료로 즐긴다.', programs='체험부스(체험비 5,000원)')
        host = self.host(item)
        good = {'results': [{'id': 'a', 'quotes': ['체험부스(체험비 5,000원)'], 'status': 'has_paid'}]}
        self.assertEqual(festival_check.review(good, host), [])
        bad = {'results': [{'id': 'a', 'quotes': ['체험비 3,000원'], 'status': 'has_paid'}]}
        self.assertEqual(festival_check.review(bad, host), ['quote_not_in_text'])
        self.assertEqual(festival_check.review({'results': []}, host), ['ids_mismatch'])
        # The listed fee field is not text a quote may come from.
        listed = festival('b', summary='국화 전시', programs='공연')
        listed['fee_text'] = '입장료 3,000원'
        self.assertEqual(festival_check.review({'results': [{'id': 'b', 'quotes': ['입장료 3,000원'], 'status': 'has_paid'}]},
                                               self.host(listed)), ['quote_not_in_text'])

    def test_notes(self):
        paid = festival('a', 'free', summary='누구나 무료로 즐긴다.', programs='체험부스(체험비 5,000원)')
        self.assertEqual(festival_check.note(paid, 'has_paid', ['체험부스(체험비 5,000원)']),
                         ('partly_paid', '체험부스(체험비 5,000원)'))
        self.assertIsNone(festival_check.note(paid, 'has_paid', ['누구나 무료로 즐긴다.']))  # no price in the quote
        self.assertIsNone(festival_check.note(dict(paid, fee_status='paid'), 'has_paid', ['체험부스(체험비 5,000원)']))
        unknown = festival('b', 'unknown', summary='관람료 무료', programs='')
        self.assertEqual(festival_check.note(unknown, 'free_only', ['관람료 무료']), ('free_found', '관람료 무료'))
        cancelled = festival('c', 'free', summary='올해 축제는 기상 악화로 취소되었습니다.')
        self.assertEqual(festival_check.note(cancelled, 'cancelled', ['올해 축제는 기상 악화로 취소되었습니다.'])[0], 'cancelled')
        self.assertIsNone(festival_check.note(cancelled, 'cancelled', ['기상 악화']))
        self.assertIsNone(festival_check.note(paid, 'no_fee_info', []))

    def test_public_and_recheck(self):
        item = festival('a', 'free', summary='누구나 무료로 즐긴다.', programs='체험부스(체험비 5,000원)')
        bundle = {'items': [item]}
        state = {'a': {'content': festival_check.content_key(item), 'status': 'has_paid',
                       'quotes': ['체험부스(체험비 5,000원)']}}
        rows = festival_check.public(state, bundle)
        self.assertEqual(rows, [{'id': 'a', 'note': 'partly_paid', 'quote': '체험부스(체험비 5,000원)'}])
        self.assertEqual(festival_check.recheck(rows, bundle), rows)
        changed = {'items': [dict(item, programs='체험부스')]}
        self.assertEqual(festival_check.public(state, changed), [])
        self.assertEqual(festival_check.recheck(rows, changed), [])
        self.assertEqual(festival_check.recheck([dict(rows[0], note='fee_found')], bundle), [])


class ApplyTests(unittest.TestCase):
    def test_apply_keeps_matching_rows_and_drops_the_key_when_empty(self):
        bundle = health(notice(1, '보건소 기간제 근로자 채용 공고'))
        url = notice_triage.notices(bundle)[0]['url']
        data = {'health_notices': bundle, 'festivals': {'items': []}}
        checks = {'schema_version': 1, 'notices': [{'url': url, 'title': '보건소 기간제 근로자 채용 공고', 'reason': 'recruitment'}],
                  'festivals': [{'id': 'gone', 'note': 'partly_paid', 'quote': 'x원'}]}
        tab_checks.apply(data, checks, [])
        self.assertEqual(data['tab_checks']['notices'][0]['url'], url)
        self.assertEqual(data['tab_checks']['festivals'], [])
        tab_checks.apply(data, data['tab_checks'], [{'kind': 'notice_unhide', 'url': url}])
        self.assertNotIn('tab_checks', data)
        tab_checks.apply(data, {'schema_version': 2}, [])
        self.assertNotIn('tab_checks', data)


class RefreshTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tools').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / '.tools')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runs = self.root / 'runs'

    def fake_invoke(self, answers):
        calls = []
        def invoke(root, kind, input_path):
            host = json.loads(Path(input_path).read_text())
            calls.append((kind, host))
            run = f'run{len(calls)}'
            save(self.runs / run / 'result.json', answers(kind, host))
            return {'status': 'validated_draft', 'run_id': run}
        return invoke, calls

    def test_notices_are_sent_once_in_batches_within_budget(self):
        items = [notice(i, f'보건소 기간제 근로자 채용 공고 {i}') for i in range(35)]
        bundle = health(*items)
        def answers(kind, host):
            return {'results': [{'id': n['id'], 'reason': 'recruitment'} for n in host['notices']]}
        invoke, calls = self.fake_invoke(answers)
        with patch('benefit_monitor.health_notices.sanitize', return_value=bundle):
            n, report = notice_triage.refresh(self.root, NOW, True, invoke, self.runs, budget=1)
            self.assertEqual((n, len(calls[0][1]['notices']), report['pending']), (1, 30, 5))
            n, report = notice_triage.refresh(self.root, NOW, True, invoke, self.runs, budget=5)
            self.assertEqual((n, len(calls[1][1]['notices'])), (1, 5))
            n, report = notice_triage.refresh(self.root, NOW, True, invoke, self.runs, budget=5)
        self.assertEqual((n, len(calls), report['hidden']), (0, 2, 35))

    def test_execute_false_sends_nothing(self):
        invoke, calls = self.fake_invoke(lambda kind, host: {})
        with patch('benefit_monitor.health_notices.sanitize', return_value=health(notice(1, '채용 공고'))):
            self.assertEqual(notice_triage.refresh(self.root, NOW, False, invoke, self.runs, budget=5)[0], 0)
        self.assertEqual(calls, [])

    def test_shared_daily_cap(self):
        save(self.root / tab_checks.DAYS, {NOW.date().isoformat(): tab_checks.MAX_PER_DAY})
        with patch('benefit_monitor.ai_review.invoke', side_effect=AssertionError('cap reached')), \
                patch('benefit_monitor.health_notices.sanitize', return_value=health(notice(1, '채용 공고'))), \
                patch('benefit_monitor.festivals.sanitize', return_value={'items': [festival('a')]}):
            result = tab_checks.refresh(self.root, NOW, execute=True)
        self.assertEqual((result['status'], result['requested']), ('completed', tab_checks.MAX_PER_DAY))


class HostValidationTests(unittest.TestCase):
    def test_paid_inputs_must_match_stored_data(self):
        from benefit_monitor import claude_trial
        bundle = health(notice(1, '보건소 기간제 근로자 채용 공고'))
        host = notice_triage.host(notice_triage.notices(bundle), NOW)
        with patch('benefit_monitor.health_notices.sanitize', return_value=bundle):
            claude_trial._validate_notice_triage(host, ROOT)
            forged = json.loads(json.dumps(host))
            forged['notices'][0]['title'] = '다른 제목'
            with self.assertRaises(ValueError):
                claude_trial._validate_notice_triage(forged, ROOT)
        item = dict(festival('3f7d1f8e-0000-4000-8000-000000000001'), region='서울', organizer='', homepage='')
        fhost = festival_check.host([item], NOW)
        with patch('benefit_monitor.festivals.sanitize', return_value={'items': [item]}):
            claude_trial._validate_festival_check(fhost, ROOT)
            forged = json.loads(json.dumps(fhost))
            forged['festivals'][0]['summary'] = '입력 조작'
            with self.assertRaises(ValueError):
                claude_trial._validate_festival_check(forged, ROOT)

    def test_kinds_and_schemas_are_registered(self):
        from benefit_monitor import claude_trial, wire_format
        for kind in ('notice_triage', 'festival_check'):
            self.assertIn(kind, claude_trial.KINDS)
            schema = wire_format.schema_for(kind, None)
            wire_format.check_limits(schema)
            self.assertTrue((ROOT / 'docs/ai/prompts' / claude_trial.KINDS[kind].prompt).is_file())


if __name__ == '__main__':
    unittest.main()
