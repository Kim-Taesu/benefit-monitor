import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from benefit_monitor import auto_publish, auto_release

NOW = datetime(2026, 11, 26, 4, tzinfo=ZoneInfo('Asia/Seoul'))


def record(**over):
    base = dict(candidate_id='c1', source='health_notices', url='https://example.go.kr/1',
                title='2027년 생활숲(마을숲, 학교숲) 조성사업 신청 안내',
                summary='주민과 함께 나무를 심고 가꾸는 2027년 생활숲 조성사업 대상지 신청 안내',
                conditions='사업대상지는 아파트·학교·유치원·어린이집 내 유휴공지이며 관리주체가 신청 가능. 식재가능 면적 50㎡ 이상',
                review=dict(kind='ai_auto', basis=dict(period_quotes=['2026. 12. 31.(목) 18:00까지'], operating_quotes=[])))
    base.update(over)
    return base


class RuleWithdrawalTests(unittest.TestCase):
    def test_organisation_only_record_is_withdrawn_once(self):
        # 2026-11-26: the 11-16 approval stayed public although the 11-24 rule would have held it.
        approved = {'c1': record()}
        self.assertEqual(auto_release.rule_withdrawals(approved, NOW), {'c1': 'not_personal'})
        row = approved['c1']
        self.assertEqual((row['status'], row['withdrawn_reason'], row['recheck_priority']),
                         ('withdrawn', 'rule_not_personal', False))
        self.assertEqual(auto_release.rule_withdrawals(approved, NOW), {})  # already withdrawn

    def test_people_who_apply_keep_the_record(self):
        for conditions in ('관리주체가 신청하거나 주민이 직접 신청할 수 있다', '어린이집 재원 아동 보호자 누구나 신청',
                           '6~7세 유아 대상, 학부모 참여'):
            with self.subTest(conditions=conditions):
                approved = {'c1': record(conditions=conditions)}
                self.assertEqual(auto_release.rule_withdrawals(approved, NOW), {})

    def test_ended_wording_in_title_or_quotes_is_withdrawn(self):
        approved = {'a': record(title='2026 겨울 특강 접수 마감되었습니다', conditions='누구나 참여'),
                    'b': record(title='전시해설 예약', conditions='누구나 참여',
                                review=dict(kind='ai_auto', basis=dict(period_quotes=['행사가 종료되었습니다'])))}
        self.assertEqual(auto_release.rule_withdrawals(approved, NOW), {'a': 'past_signal', 'b': 'past_signal'})

    def test_only_shown_auto_records_are_read(self):
        approved = {'h': record(review=dict(kind='human')), 'w': dict(record(), status='withdrawn'), 'x': 'broken'}
        self.assertEqual(auto_release.rule_withdrawals(approved, NOW), {})
        self.assertNotIn('withdrawn_reason', approved['h'])


class GateAgreesTests(unittest.TestCase):
    def test_new_decisions_hold_the_same_wording(self):
        self.assertTrue(auto_publish.organisation_applies(record()['conditions']))
        self.assertFalse(auto_publish.organisation_applies('관리주체가 신청하거나 주민이 직접 신청할 수 있다'))
        self.assertFalse(auto_publish.organisation_applies('학교 밖 청소년 누구나 이용'))


if __name__ == '__main__':
    unittest.main()
