import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import festival_pick as fp
from benefit_monitor.festivals import DETAIL
from benefit_monitor.store import load, save

NOW = datetime.fromisoformat('2026-11-14T07:00:00+09:00')

APPLE, JINAN, BUSAN, POHANG, GAME = 'fa981ab3-f799-409f-9c3e-7e1131936640', '6f06d9ff-2f4a-4c99-ac44-92d831c88e77', '5baa5877-b11e-4673-949e-abe21b3b3d62', '1a7b7f32-e5a4-47b1-9e35-4a87499eccd8', 'c25775aa-a6ec-4a31-a836-966860c49da5'

# Real 2026-11-14 rows from briefing-data (trimmed text): 16 items, 9 inside the window.
ROWS = [
    ('ae25ca2d-4aab-4b5d-9ecb-bedebdf2b037', '단풍나무숲길 힐링축제', '2026-10-15', '2026-11-15', '충청남도 천안시', 'free', '무료', '단풍나무숲길 야간개장'),
    ('a27063ab-b3cc-4b61-91a4-5ba82187220c', '코리아 그랜드 페스티벌', '2026-10-29', '2026-11-15', '경상북도 안동시', 'free', '무료', '소상공인 제품 특별판매전'),
    (APPLE, '영주 사과축제', '2026-11-13', '2026-11-15', '서울특별시 중구', 'mixed', '무료(일부 체험프로그램 유료)', '영주사과 판매 및 시식'),
    (JINAN, '진안고원 김치보쌈축제', '2026-11-14', '2026-11-15', '전북특별자치도 진안군', 'mixed',
     '무료 (일부 체험 프로그램 유료 - 우리집 김장담그기 체험)', '개막행사 무대 이벤트 김장골든벨'),
    (BUSAN, '부산종합민속예술제', '2026-11-15', '2026-11-15', '부산광역시 부산진구', 'free', '무료', '풍류마당 솜씨마당 잔치마당'),
    (POHANG, '포항국제불빛축제', '2026-11-19', '2026-11-21', '경상북도 포항시', 'free', '무료', '국제불꽃쇼 미디어파사드'),
    (GAME, '게임문화축제', '2026-11-19', '2026-11-22', '부산광역시 해운대구', 'free', '무료', '게임 IP 전시 체험관'),
    ('47cc094e-78e5-4ebc-a7d5-f65430621719', '무안 YD 페스티벌', '2026-11-20', '2026-11-22', '전남광주통합특별시 무안군', 'mixed', '무료(일부 프로그램 유료)', '개막퍼레이드'),
    ('870226d8-7912-4405-b4f6-8fadba5ddff0', '순창 KOREA 떡볶이 페스타', '2026-11-21', '2026-11-22', '전북특별자치도 순창군', 'mixed',
     '입장료 무료 (일부 프로그램 유료)', '떡볶이 연구소'),
    ('b3b7a23c-c7f6-45db-930a-b139e4d8cd9f', '해운대 빛축제', '2026-11-28', '2027-01-10', '부산광역시 해운대구', 'free', '무료', '빛 조형물 전시'),
    ('06c85b3f-b302-4025-9cc5-27ec77b3a5ff', '포천펫스타', '2026-11-29', '2026-11-29', '경기도 포천시', 'paid', '유료(아트밸리 입장료 참고)', '미션 멍-파서블'),
    ('8e3215e7-02ad-488a-997d-979b2b8b682f', '청계천의 빛', '2026-12-11', '2026-12-31', '서울특별시 중구', 'free', '무료', '점등식'),
    ('bcd79254-697d-47f5-a408-e022f0e9f7fd', '서울빛초롱축제', '2026-12-11', '2027-01-31', '서울특별시 중구', 'free', '무료', '빛 조형물 전시'),
    ('e79ad504-4e44-46d4-950c-cff9292665c1', '평창송어축제', '2027-01-01', '2027-01-31', '강원특별자치도 평창군', 'paid', '유료', '얼음낚시'),
    ('02a1c2ab-bce7-404a-9c8f-4eb4ac69acb3', '얼음나라화천 산천어축제', '2027-01-09', '2027-01-31', '강원특별자치도 화천군', 'paid', '유료 (자세한 사항은 홈페이지 참조.)', '얼음낚시'),
    ('e545101d-5bed-4a95-85c2-9ad0b15a84a6', '철원 한탄강 얼음트레킹 축제', '2027-01-16', '2027-02-14', '강원특별자치도 철원군', 'paid',
     '10,000원 (철원사랑상품권 5,000원 환급) *물윗길트레킹 요금과 연계', '한탄강 얼음트레킹'),
]


def item(i, name, start, end, region, fee, fee_text, programs):
    return dict(id=i, name=name, start=start, end=end, region=region, place='장소', organizer='주최', fee_status=fee,
                fee_text=fee_text, discount='', summary='소개', programs=programs, homepage='', culture_tourism=False,
                url=DETAIL + i, modified=None)


def make_bundle(rows=ROWS):
    return dict(schema_version=1, source='kfes', fetched_at='2026-11-14T06:00:00+09:00', notice='x',
                items=[item(*r) for r in rows])


BUNDLE = make_bundle()
SUMMARY = '서울 중구 영주 사과축제는 무료이고 일부 체험만 유료예요. 포항국제불빛축제에선 밤 불빛 행사를 볼 수 있어요.'


def draft(summary=SUMMARY, picks=None):
    return dict(summary=summary, picks=picks if picks is not None else [
        dict(id=APPLE, line='무료, 일부 체험 유료'), dict(id=POHANG, line='무료, 밤 불빛 행사')])


def stored(day='2026-11-14', generated=NOW, source='ai', summary=SUMMARY, picks=None):
    if picks is None:
        picks = draft()['picks'] if source == 'ai' else [dict(id=APPLE, line=None)]
    return dict(schema_version=1, generated_at=generated.isoformat(), day=day, source=source,
                summary=summary if source == 'ai' else None, picks=picks)


class HostTests(unittest.TestCase):
    def test_host_window_and_metro_first(self):
        host = fp.host(BUNDLE, NOW)
        names = [c['name'] for c in host['candidates']]
        self.assertEqual(len(names), 9)
        self.assertEqual(names[0], '영주 사과축제')
        self.assertTrue(host['candidates'][0]['metro'])
        self.assertNotIn('해운대 빛축제', names)
        self.assertEqual((host['schema_version'], host['mode'], host['synthetic'], host['day']),
                         ('festival-input-v1', 'api_agent', False, '2026-11-14'))
        self.assertTrue(all(not c['metro'] for c in host['candidates'][1:]))
        rest = [(c['start'], c['name']) for c in host['candidates'][1:]]
        self.assertEqual(rest, sorted(rest))

    def test_host_none_below_minimum(self):
        one = make_bundle([ROWS[2], ROWS[9]])
        self.assertIsNone(fp.host(one, NOW))
        self.assertIsNone(fp.host(None, NOW))

    def test_fee_text_and_programs_are_truncated(self):
        row = list(ROWS[2])
        row[6], row[7] = '무료' + '가' * 100, '나' * 300
        host = fp.host(make_bundle([tuple(row), ROWS[5]]), NOW)
        self.assertEqual((len(host['candidates'][0]['fee_text']), len(host['candidates'][0]['programs'])), (60, 120))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.host = fp.host(BUNDLE, NOW)
        self.known = fp.known_names(BUNDLE)

    def errors(self, d):
        return fp.review(d, self.host, self.known)

    def test_review_ok(self):
        self.assertEqual(self.errors(draft()), [])

    def test_mixed_free_needs_partial(self):
        d = draft(picks=[dict(id=APPLE, line='무료'), dict(id=POHANG, line='무료, 밤 불빛 행사')])
        self.assertEqual(self.errors(d), ['free'])

    def test_free_on_paid_festival_rejected(self):
        host = fp.host(BUNDLE, datetime.fromisoformat('2026-11-20T07:00:00+09:00'))
        d = draft(summary='이번 주말 포천 펫스타에서 반려견과 함께 나들이를 즐겨 보세요. 아트밸리를 둘러봐요.',
                  picks=[dict(id='06c85b3f-b302-4025-9cc5-27ec77b3a5ff', line='무료로 즐겨요'), dict(id=GAME, line='게임 전시')])
        self.assertIn('free', fp.review(d, host, fp.known_names(BUNDLE)))

    def test_unknown_number(self):
        d = draft(picks=[dict(id=APPLE, line='체험 5,000원, 일부 유료'), dict(id=POHANG, line='무료')])
        self.assertIn('number', self.errors(d))

    def test_date_must_match(self):
        d = draft(summary='이번 주말 서울 영주 사과축제는 11/16까지 열리고 포항 축제가 이어져요 가볍게 다녀오세요.')
        self.assertIn('number', self.errors(d))

    def test_dates_and_fee_numbers_from_the_festival_are_allowed(self):
        d = draft(summary='영주 사과축제는 11월 15일까지, 포항국제불빛축제는 11/19부터 열려요. 가족 나들이로 좋아요.',
                  picks=[dict(id=APPLE, line='11/13~15, 일부 유료'), dict(id=POHANG, line='11/19~21 무료')])
        self.assertEqual(self.errors(d), [])
        host = fp.host(BUNDLE, datetime.fromisoformat('2027-01-20T07:00:00+09:00'))
        known = fp.known_names(BUNDLE)
        ok = draft(summary='철원 한탄강 얼음트레킹 축제는 10,000원이고 5,000원이 환급돼요. 겨울 나들이로 좋아요.',
                   picks=[dict(id='e545101d-5bed-4a95-85c2-9ad0b15a84a6', line='10,000원 중 5,000원 환급')])
        self.assertEqual(fp.review(ok, host, known), [])

    def test_number_bypasses_are_rejected(self):
        def one(summary=SUMMARY, apple='무료, 일부 체험 유료'):
            return self.errors(draft(summary=summary, picks=[dict(id=APPLE, line=apple),
                                                             dict(id=POHANG, line='무료, 밤 불빛 행사')]))
        self.assertIn('number', one(apple='15% 할인, 일부 유료'))
        self.assertIn('number', one(apple='11/13까지, 일부 유료'))   # 11/13 is the start, not the end
        self.assertIn('number', one(apple='11/14~15, 일부 유료'))
        self.assertIn('number', one(apple='3시간 체험, 일부 유료'))
        self.assertIn('number', one(summary='영주 사과축제는 11/19까지 열리고 포항 축제가 이어져요 주말 나들이로 좋아요.'))
        self.assertIn('number', one(summary='11/15까지 영주 사과축제가 열리고 포항 축제가 이어져요 주말 나들이로 좋아요.'))
        self.assertEqual(one(apple='11/13~15, 일부 유료'), [])
        self.assertEqual(self.errors(draft(picks=[dict(id=POHANG, line='11/19~21 무료')])), [])

    def test_fee_amount_needs_unit_verbatim(self):
        host = fp.host(BUNDLE, datetime.fromisoformat('2027-01-20T07:00:00+09:00'))
        known = fp.known_names(BUNDLE)
        def line(text):
            return fp.review(draft(summary='철원 한탄강 얼음트레킹 축제로 겨울 나들이를 떠나 보세요. 얼음 위를 걸어요.',
                                   picks=[dict(id='e545101d-5bed-4a95-85c2-9ad0b15a84a6', line=text)]), host, known)
        self.assertEqual(line('10,000원 중 5,000원 환급'), [])
        self.assertIn('number', line('10,000명 방문'))
        self.assertIn('number', line('5,000 환급'))
        self.assertIn('number', line('50%'))

    def test_free_synonyms_need_free_status(self):
        host = fp.host(BUNDLE, datetime.fromisoformat('2026-11-20T07:00:00+09:00'))
        known = fp.known_names(BUNDLE)
        paid = '06c85b3f-b302-4025-9cc5-27ec77b3a5ff'
        def line(i, text):
            return fp.review(draft(summary='나들이로 갈 만한 축제를 골랐어요. 가볍게 다녀오세요.',
                                   picks=[dict(id=i, line=text)]), host, known)
        for word in ('공짜로 즐겨요', '입장료 없음', '무상 관람', '0원 입장', '무료'):
            self.assertIn('free', line(paid, word), word)
        self.assertEqual(line(POHANG, '공짜로 즐겨요'), [])
        self.assertIn('free', line('47cc094e-78e5-4ebc-a7d5-f65430621719', '무료'))
        self.assertIn('free', line('47cc094e-78e5-4ebc-a7d5-f65430621719', '무료, 유료 아님'))
        self.assertIn('free', line('47cc094e-78e5-4ebc-a7d5-f65430621719', '일부 입장료 없음'))
        self.assertEqual(line('47cc094e-78e5-4ebc-a7d5-f65430621719', '무료, 일부 체험 유료'), [])
        self.assertNotIn('free', line(POHANG, '10,000원'))  # '0원' inside 10,000원 is not a free word

    def test_summary_free_is_attributed_to_the_named_festival(self):
        host = fp.host(BUNDLE, datetime.fromisoformat('2026-11-20T07:00:00+09:00'))
        known = fp.known_names(BUNDLE)
        picks = [dict(id=POHANG, line='불꽃쇼 구경'), dict(id='06c85b3f-b302-4025-9cc5-27ec77b3a5ff', line='반려견과 함께')]
        bad = '포항국제불빛축제는 무료이고 포천펫스타도 모두 무료예요. 주말 나들이로 좋아요.'
        self.assertIn('free', fp.review(draft(summary=bad, picks=picks), host, known))
        self.assertIn('free', fp.review(draft(summary='이번 주말은 무료로 즐길 축제가 많아요. 가볍게 다녀오세요.', picks=picks), host, known))
        ok = '포항국제불빛축제는 무료예요. 포천펫스타는 유료이니 입장료를 확인하세요.'
        self.assertEqual(fp.review(draft(summary=ok, picks=picks), host, known), [])

    def test_summary_names_non_candidate(self):
        d = draft(summary='이번 주말 영주 사과축제를 즐기고 다음 달 해운대 빛축제도 기대해 보세요.')
        self.assertIn('summary_item', self.errors(d))

    def test_shape_ids_lengths_and_markup(self):
        self.assertEqual(self.errors({'summary': SUMMARY}), ['draft_shape'])
        self.assertEqual(self.errors(draft(picks=[dict(id=APPLE, menu='x')])), ['draft_shape'])
        self.assertIn('picks_count', self.errors(draft(picks=[])))
        self.assertIn('picks_unknown', self.errors(draft(picks=[dict(id='nope', line='가볼 만해요')])))
        self.assertIn('picks_duplicate', self.errors(draft(picks=[dict(id=POHANG, line='가')] * 2)))
        self.assertIn('line_length', self.errors(draft(picks=[dict(id=POHANG, line='')])))
        self.assertIn('line_length', self.errors(draft(picks=[dict(id=POHANG, line='가' * 41)])))
        self.assertIn('summary_length', self.errors(draft(summary='짧아요')))
        self.assertIn('summary_length', self.errors(draft(summary='가' * 201)))
        self.assertIn('markup', self.errors(draft(picks=[dict(id=POHANG, line='https://x.kr')])))
        self.assertIn('markup', self.errors(draft(summary=SUMMARY + '<b>')))
        six = [dict(id=c['id'], line='가볼 만해요') for c in self.host['candidates'][:6]]
        self.assertIn('picks_count', self.errors(draft(picks=six)))

    def test_relative_time_words_rejected(self):
        # The page shows each festival's dates; text says what and where, never when (2026-11-14 review).
        for word in ('오늘', '내일', '모레', '어제', '이번 주', '이번주', '다음 주', '주말', '평일', '마지막 날', '마지막날',
                     '막바지', '곧', '임박', '서두르세요', '서둘러 가요'):
            self.assertIn('relative', self.errors(draft(picks=[dict(id=POHANG, line=f'{word} 불빛 행사')])), word)
        self.assertIn('relative', self.errors(draft(summary='이번 주말 포항국제불빛축제가 열려요. 밤 불빛 행사를 즐겨 보세요.')))
        self.assertIn('relative', self.errors(draft(picks=[dict(id=APPLE, line='오늘 마지막 날이에요, 일부 유료')])))
        self.assertEqual(self.errors(draft()), [])

    def test_summary_free_on_mixed_needs_partial_paid_in_the_same_sentence(self):
        bad = ('영주 사과축제는 모두 무료로 즐길 수 있어요. 포항국제불빛축제도 열려요.',
               '영주 사과축제는 무료예요. 일부 체험은 유료예요.',
               '영주 사과축제는 무료이고 일부 체험도 유료가 아니에요.')
        for summary in bad:
            self.assertIn('free', self.errors(draft(summary=summary)), summary)
        self.assertEqual(self.errors(draft(summary='영주 사과축제는 무료이고 일부 체험만 유료예요. 포항 쪽 행사도 있어요.')), [])

    def test_negated_free_or_paid_rejected(self):
        mixed = '47cc094e-78e5-4ebc-a7d5-f65430621719'
        for i, line in ((POHANG, '무료 아님'), (POHANG, '무료가 아니에요'), (APPLE, '무료, 일부 유료가 아님'),
                        (APPLE, '무료, 일부 유료 아니에요')):
            self.assertIn('free', self.errors(draft(picks=[dict(id=i, line=line), dict(id=mixed, line='무료, 일부 유료')])), line)
        self.assertIn('free', self.errors(draft(summary='포항국제불빛축제는 무료가 아니에요. 밤 불빛 행사를 보러 가요.')))

    def test_control_characters_are_markup(self):
        for ch in ('\t', '\x00', '\x1f', '\x0b'):
            self.assertIn('markup', self.errors(draft(picks=[dict(id=POHANG, line=f'무료{ch}불빛')])), repr(ch))
        self.assertIn('markup', self.errors(draft(summary=SUMMARY + '\t')))

    def test_claim_words(self):
        for word in ('보장', '무조건', '최저가', '확실', '선착순', '매진', '완판', '100%'):
            self.assertIn('claim', self.errors(draft(picks=[dict(id=POHANG, line=f'{word} 추천')])), word)
        self.assertIn('claim', self.errors(draft(summary=SUMMARY + ' 선착순이에요')))


class PublicTests(unittest.TestCase):
    def test_public_keeps_valid_ai_pick(self):
        pick = fp.public(stored(), BUNDLE, [], NOW)
        self.assertEqual((pick['source'], pick['summary']), ('ai', SUMMARY))

    def test_public_drops_ended_festival(self):
        later = datetime.fromisoformat('2026-11-16T07:00:00+09:00')
        three = [dict(id=BUSAN, line='하루 무료 공연'), dict(id=POHANG, line='무료, 밤 불빛 행사'), dict(id=GAME, line='무료 전시')]
        pick = fp.public(stored(picks=three, summary='오늘 부산종합민속예술제와 포항 불빛축제가 열려요. 게임문화축제도 있어요.',
                                generated=later - timedelta(hours=1)), BUNDLE, [], later)
        self.assertEqual(pick['source'], 'rule')
        self.assertIsNone(pick['summary'])

    def test_public_removes_one_line_and_summary_keeps_enough_lines(self):
        later = datetime.fromisoformat('2026-11-16T07:00:00+09:00')
        four = [dict(id=BUSAN, line='하루 무료 공연'), dict(id=POHANG, line='무료, 밤 불빛 행사'),
                dict(id=GAME, line='무료 전시'), dict(id='47cc094e-78e5-4ebc-a7d5-f65430621719', line='무료, 일부 유료')]
        pick = fp.public(stored(picks=four, generated=later - timedelta(hours=1)), BUNDLE, [], later)
        self.assertEqual(pick['source'], 'ai')
        self.assertIsNone(pick['summary'])
        self.assertEqual([p['id'] for p in pick['picks']], [POHANG, GAME, '47cc094e-78e5-4ebc-a7d5-f65430621719'])

    def test_public_stale_36h(self):
        old = NOW - timedelta(hours=37)
        pick = fp.public(stored(generated=old), BUNDLE, [], NOW)
        self.assertEqual(pick['source'], 'rule')
        self.assertIsNone(pick['summary'])

    def test_public_rejects_bad_shape_and_future(self):
        self.assertIsNone(fp.public(None, BUNDLE, [], NOW))
        self.assertIsNone(fp.public(dict(stored(), extra=1), BUNDLE, [], NOW))
        self.assertIsNone(fp.public(stored(generated=NOW + timedelta(hours=1)), BUNDLE, [], NOW))

    def test_public_rereviews_against_current_bundle(self):
        changed = make_bundle([r if r[0] != POHANG else r[:5] + ('paid', '유료', r[7]) for r in ROWS])
        pick = fp.public(stored(), changed, [], NOW)
        self.assertEqual(pick['source'], 'rule')

    def test_mute_gives_rule(self):
        mute = [{'kind': 'festival_pick_text', 'day': '2026-11-14'}]
        pick = fp.public(stored(), BUNDLE, mute, NOW)
        self.assertEqual((pick['source'], pick['summary']), ('rule', None))
        other = [{'kind': 'festival_pick_text', 'day': '2026-11-13'}]
        self.assertEqual(fp.public(stored(), BUNDLE, other, NOW)['source'], 'ai')
        self.assertEqual(fp.apply_mute(stored(), BUNDLE, mute, NOW)['source'], 'rule')

    def test_rule_pick_order_and_size(self):
        host = fp.host(BUNDLE, NOW)
        rule = fp.rule_pick(host, NOW)
        self.assertEqual((rule['source'], rule['summary'], rule['day']), ('rule', None, '2026-11-14'))
        self.assertEqual(len(rule['picks']), 5)
        self.assertEqual(rule['picks'][0], dict(id=APPLE, line=None))

    def test_single_remaining_candidate_gives_rule_card(self):
        # 11/16: only one festival left in the window -> host is None, but a rule card still shows it.
        bundle = make_bundle([ROWS[5], ROWS[9]])
        day = datetime.fromisoformat('2026-11-16T07:00:00+09:00')
        self.assertIsNone(fp.host(bundle, day))
        pick = fp.public(stored(picks=[dict(id=POHANG, line='무료')], summary=None, source='ai') | dict(summary=SUMMARY),
                         bundle, [], day)
        self.assertEqual((pick['source'], [p['id'] for p in pick['picks']]), ('rule', [POHANG]))
        none = fp.public(stored(), make_bundle([ROWS[9]]), [], day)
        self.assertIsNone(none)

    def test_public_is_idempotent_after_a_dropped_line(self):
        later = datetime.fromisoformat('2026-11-16T07:00:00+09:00')
        four = [dict(id=BUSAN, line='하루 무료 공연'), dict(id=POHANG, line='무료, 밤 불빛 행사'),
                dict(id=GAME, line='무료 전시'), dict(id='47cc094e-78e5-4ebc-a7d5-f65430621719', line='무료, 일부 유료')]
        first = fp.public(stored(picks=four, generated=later - timedelta(hours=1)), BUNDLE, [], later)
        self.assertEqual((first['source'], first['summary']), ('ai', None))
        again = fp.public(first, BUNDLE, [], later)
        self.assertEqual(again, first)
        bad = dict(first, picks=[dict(p, line='무료 아님') for p in first['picks']])
        self.assertEqual(fp.public(bad, BUNDLE, [], later)['source'], 'rule')  # lines are still re-checked

    def test_old_rule_pick_is_rebuilt_from_current_candidates(self):
        weeks = datetime.fromisoformat('2026-12-05T07:00:00+09:00')
        old = stored(source='rule', picks=[dict(id=APPLE, line=None), dict(id=POHANG, line=None),
                                           dict(id='b3b7a23c-c7f6-45db-930a-b139e4d8cd9f', line=None)])
        pick = fp.public(old, BUNDLE, [], weeks)
        self.assertEqual(pick, fp.rule_pick(fp.host(BUNDLE, weeks), weeks))
        self.assertEqual(pick['day'], '2026-12-05')

    def test_rule_source_ids_must_be_current(self):
        later = datetime.fromisoformat('2026-11-16T07:00:00+09:00')
        pick = fp.public(stored(source='rule'), BUNDLE, [], later)
        self.assertEqual(pick['source'], 'rule')
        self.assertNotIn(APPLE, [p['id'] for p in pick['picks']])


class RefreshTests(unittest.TestCase):
    def run_refresh(self, invoke_result=None, model=None, execute=True, days=None, root=None, bundle=BUNDLE):
        if root is None:
            tmp = tempfile.TemporaryDirectory(dir=Path(fp.__file__).resolve().parents[1])
            self.addCleanup(tmp.cleanup)
            root = Path(tmp.name)
        save(root / 'cache/festivals.json', bundle)
        if days:
            save(root / 'cache/festival_pick/days.json', days)
        calls = []

        def invoke(r, kind, path):
            calls.append((kind, json.loads(Path(path).read_text())))
            self.assertEqual(load(root / 'cache/festival_pick/days.json', {})['days']['2026-11-14']['status'], 'attempted')
            if model is not None:
                save(root / '.tools/claude-trial/live/runs/run1/result.json', model)
            return invoke_result or {'status': 'validated_draft', 'run_id': 'run1'}
        with patch.object(fp, 'invoke', side_effect=invoke), patch.object(fp, 'TRIAL_RUNS', root / '.tools/claude-trial/live/runs'):
            result = fp.refresh(root, NOW, execute=execute)
        return result, calls, load(root / 'cache/festival_pick/pick.json', None), root

    def test_valid_draft_becomes_ai_pick(self):
        result, calls, pick, _ = self.run_refresh(model=draft())
        self.assertEqual([k for k, _ in calls], ['festival'])
        self.assertEqual(calls[0][1], fp.host(BUNDLE, NOW))
        self.assertEqual((pick['source'], pick['summary'], pick['day']), ('ai', SUMMARY, '2026-11-14'))
        self.assertEqual(result['source'], 'ai')

    def test_refresh_rule_on_rejected(self):
        result, calls, pick, root = self.run_refresh(invoke_result={'status': 'rejected_draft', 'run_id': None})
        self.assertEqual((pick['source'], len(calls)), ('rule', 1))
        self.assertEqual(result['model']['status'], 'rejected_draft')
        _, calls, pick, _ = self.run_refresh(root=root)
        self.assertEqual((calls, pick['source']), ([], 'rule'))

    def test_review_failure_after_trial_falls_back(self):
        bad = draft(summary='이번 주말 영주 사과축제를 즐기고 다음 달 해운대 빛축제도 기대해 보세요.')
        result, _, pick, _ = self.run_refresh(model=bad)
        self.assertEqual(pick['source'], 'rule')
        self.assertIn('summary_item', result['errors'])

    def test_no_spend_without_execute_and_no_candidates(self):
        _, calls, pick, _ = self.run_refresh(execute=False)
        self.assertEqual((calls, pick['source']), ([], 'rule'))
        result, calls, pick, _ = self.run_refresh(bundle=make_bundle([ROWS[9]]))
        self.assertEqual((result['status'], calls, pick), ('no_candidates', [], None))


if __name__ == '__main__':
    unittest.main()
