import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import health_notes as n, health_notices, publish, wire_format
from benefit_monitor.store import save, load

NOW = datetime.fromisoformat('2026-11-11T09:00:00+09:00')
TEXT = ('대상 20세 ~ 69세 관내 구민, 관내 사업장 근로자 기간 연중 내용 대사증후군 조기발견을 위한 무료검진 '
        '혈압, 허리둘레, 공복혈당 공복(10시간 금식 필요)필수 평일 09:00~11:30 '
        '보건소 2층 대사증후군 전문관리센터 ☎ 02-2600-5933, 5993 (사전예약 필수)')
SHA = hashlib.sha256(TEXT.encode()).hexdigest()
URL = 'https://www.gangseo.seoul.kr/health/ht020103'
PROGRAM = dict(district='강서구', center='강서구보건소', name='대사증후군 관리', url=URL, status='checked',
               checked_at=NOW.isoformat(), text=TEXT, text_sha=SHA)
GOOD = dict(status='ok', sentence='강서구에 살거나 일하는 20~69세라면 혈압·공복혈당 등 대사증후군 검진을 무료로 받을 수 있어요. '
                                  '10시간 금식 후 02-2600-5933으로 예약하고 받아보세요.',
            quotes=['20세 ~ 69세 관내 구민, 관내 사업장 근로자', '대사증후군 조기발견을 위한 무료검진',
                    '공복(10시간 금식 필요)필수', '☎ 02-2600-5933, 5993 (사전예약 필수)'])


def host(text=TEXT):
    return n.host(dict(PROGRAM, text=text, text_sha=hashlib.sha256(text.encode()).hexdigest()), NOW)


class ReviewTests(unittest.TestCase):
    def test_good_sentence_passes(self):
        self.assertEqual(n.review(GOOD, host()), [])

    def test_each_rule(self):
        cases = {
            'quote_not_in_page': dict(GOOD, quotes=GOOD['quotes'] + ['누구든 언제나 무료']),
            'number_not_quoted': dict(GOOD, sentence=GOOD['sentence'].replace('10시간', '12시간')),
            'free_not_quoted': dict(GOOD, quotes=[q for q in GOOD['quotes'] if '무료' not in q]),
            'sentence_claim': dict(GOOD, sentence=GOOD['sentence'] + ' 무조건 좋아요.'),
            'sentence_other_district': dict(GOOD, sentence=GOOD['sentence'].replace('강서구에', '양천구에')),
            'sentence_markup': dict(GOOD, sentence=GOOD['sentence'] + ' https://x.kr'),
            'budget_not_quoted': dict(GOOD, sentence=GOOD['sentence'] + ' 예산 소진 시 마감될 수 있어요.'),
            'not_recommendable': dict(GOOD, status='unclear'),
        }
        for code, draft in cases.items():
            with self.subTest(code=code):
                self.assertIn(code, n.review(draft, host()))
        self.assertEqual(n.review({'status': 'ok'}, host()), ['draft_shape'])

    def test_stop_words_on_page_require_a_caution_that_asks_to_check(self):
        text = TEXT + ' 예산 소진 시 조기 마감될 수 있습니다.'
        self.assertIn('caution_required', n.review(GOOD, host(text)))
        caution = dict(GOOD, status='caution',
                       sentence=GOOD['sentence'] + ' 예산 소진 시 일찍 마감될 수 있으니 전화로 확인하세요.',
                       quotes=GOOD['quotes'] + ['예산 소진 시 조기 마감될 수 있습니다.'])
        self.assertEqual(n.review(caution, host(text)), [])

    def test_never_claims_remaining_budget(self):
        draft = dict(GOOD, sentence=GOOD['sentence'] + ' 아직 예산이 남아 있어요.', quotes=GOOD['quotes'])
        self.assertIn('sentence_claim', n.review(draft, host()))


class PublicTests(unittest.TestCase):
    def note(self, **over):
        return dict(url=URL, district='강서구', sentence=GOOD['sentence'], generated_at=NOW.isoformat(), text_sha=SHA) | over

    def test_note_is_tied_to_the_same_page_text_and_fresh_check(self):
        bundle = dict(programs=[PROGRAM])
        self.assertEqual(len(n.public([self.note()], bundle, [], NOW)), 1)
        self.assertEqual(set(n.public([self.note()], bundle, [], NOW)[0]), {'url', 'district', 'sentence', 'generated_at'})
        self.assertEqual(n.public([self.note(text_sha='0' * 64)], bundle, [], NOW), [])  # page changed
        stale = dict(PROGRAM, checked_at=(NOW - timedelta(days=11)).isoformat())
        self.assertEqual(n.public([self.note()], dict(programs=[stale]), [], NOW), [])
        self.assertEqual(n.public([self.note()], dict(programs=[dict(PROGRAM, status='failed')]), [], NOW), [])
        old = self.note(generated_at=(NOW - timedelta(days=22)).isoformat())
        self.assertEqual(n.public([old], bundle, [], NOW), [])

    def test_admin_mute_hides_the_sentence(self):
        mute = [{'kind': n.TAKEDOWN_KIND, 'url': URL}]
        self.assertEqual(n.public([self.note()], dict(programs=[PROGRAM]), mute, NOW), [])
        public_bundle = dict(programs=[{k: PROGRAM[k] for k in health_notices.PROGRAM_KEYS}])
        light = [{k: v for k, v in self.note().items() if k != 'text_sha'}]
        self.assertEqual(len(n.public_light(light, public_bundle, [], NOW)), 1)
        self.assertEqual(n.public_light(light, public_bundle, mute, NOW), [])


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.tools')
        self.root = Path(self.tmp.name)
        self.bundle_at(NOW)

    def bundle_at(self, when):
        programs = [dict(PROGRAM, url=f'{URL}?p={i}', checked_at=when.isoformat()) for i in range(12)]
        bundle = dict(schema_version=1, source='health_notices', fetched_at=when.isoformat(), notice='x',
                      boards=[dict(district='강서구', name='강서구보건소', list_url=URL, home_url=URL, status='checked',
                                   reason=None, checked_at=when.isoformat(), items=[])], programs=programs)
        save(self.root / health_notices.FILE, bundle)

    def tearDown(self):
        self.tmp.cleanup()

    def run_refresh(self, draft, now=NOW, status='validated_draft'):
        calls = []

        def invoke(root, kind, path):
            calls.append(json.loads(Path(path).read_text()))
            return {'status': status, 'run_id': 'r1'}
        with patch.object(n, 'invoke', invoke), patch.object(n, 'load', lambda p, d: draft if str(p).endswith('result.json') else load(p, d)):
            result = n.refresh(self.root, now, execute=True)
        return result, calls

    def test_ten_a_day_then_no_repeat_until_text_changes_or_two_weeks(self):
        result, calls = self.run_refresh(GOOD)
        self.assertEqual((result['requested'], result['published']), (10, 10))
        self.assertEqual(calls[0]['page_text'], TEXT)
        self.assertEqual(len(load(self.root / n.PUBLIC, None)), 10)
        result, calls = self.run_refresh(GOOD, NOW + timedelta(days=1))
        self.assertEqual(result['requested'], 2)  # only the two not yet written
        result, _ = self.run_refresh(GOOD, NOW + timedelta(days=2))
        self.assertEqual(result['requested'], 0)
        self.bundle_at(NOW + timedelta(days=15))
        result, _ = self.run_refresh(GOOD, NOW + timedelta(days=15))
        self.assertEqual(result['requested'], 10)

    def test_rejected_draft_publishes_nothing_and_keeps_last_good_sentence(self):
        self.run_refresh(GOOD)
        bad = dict(GOOD, sentence=GOOD['sentence'] + ' 무조건 좋아요.')
        self.bundle_at(NOW + timedelta(days=15))
        result, _ = self.run_refresh(bad, NOW + timedelta(days=15))
        self.assertEqual((result['requested'], result['published']), (10, 0))
        self.assertEqual(len(load(self.root / n.PUBLIC, None)), 10)  # unchanged text: last good kept

    def test_no_spend_without_execute_and_credit_exhaustion_stops(self):
        with patch.object(n, 'invoke', side_effect=AssertionError):
            self.assertEqual(n.refresh(self.root, NOW, execute=False)['requested'], 0)
        result, calls = self.run_refresh(GOOD, status='credit_exhausted')
        self.assertEqual((result['status'], len(calls)), ('credit_exhausted', 1))

    def test_publish_attaches_sentences_without_page_text(self):
        self.run_refresh(GOOD)
        data = {}
        with patch('benefit_monitor.auto_release.load', return_value=({}, [])):
            publish.attach_health_notices(self.root, data, NOW)
        self.assertNotIn('text', data['health_notices']['programs'][0])
        self.assertEqual(len(data['health_notes']), 10)
        self.assertNotIn('text_sha', data['health_notes'][0])


class ContractTests(unittest.TestCase):
    def test_wire_round_trip_and_mismatch(self):
        wire = dict(GOOD, wire_version=wire_format.HEALTH_WIRE)
        self.assertEqual(wire_format.from_wire('health', wire, None), GOOD)
        with self.assertRaises(ValueError):
            wire_format.from_wire('health', dict(wire, extra=1), None)
        self.assertEqual(wire_format.schema_for('health', None)['required'], ['wire_version', 'status', 'sentence', 'quotes'])

    def test_paid_input_must_match_the_stored_bundle(self):
        from benefit_monitor.claude_trial import validate_host
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.tools') as tmp:
            root = Path(tmp)
            save(root / health_notices.FILE, dict(schema_version=1, source='health_notices', fetched_at=NOW.isoformat(),
                                                  notice='x', boards=[dict(district='강서구', name='강서구보건소', list_url=URL,
                                                  home_url=URL, status='checked', reason=None, checked_at=NOW.isoformat(),
                                                  items=[])], programs=[PROGRAM]))
            validate_host(host(), 'health', root)
            with self.assertRaises(ValueError):
                validate_host(dict(host(), page_text=TEXT + ' 개인 메모'), 'health', root)
            with self.assertRaises(ValueError):
                validate_host(dict(host(), extra='x'), 'health', root)


if __name__ == '__main__':
    unittest.main()


class TakedownPathTests(unittest.TestCase):
    def test_takedown_only_deploy_removes_muted_sentences(self):
        from benefit_monitor.auto_release import apply_takedowns
        data = {'items': [], 'health_notes': [dict(url=URL, district='강서구', sentence=GOOD['sentence'], generated_at=NOW.isoformat())]}
        self.assertNotIn('health_notes', apply_takedowns(data, [{'kind': n.TAKEDOWN_KIND, 'url': URL}]))
        self.assertEqual(len(apply_takedowns(data, [])['health_notes']), 1)
