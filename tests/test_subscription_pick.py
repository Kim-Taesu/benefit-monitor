import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import subscription_pick as sp
from benefit_monitor.subscriptions import FILE, sanitize
from benefit_monitor.store import load, save

NOW = datetime.fromisoformat('2026-11-18T09:00:00+09:00')
# Five real complexes from the 2026-11-18 public bundle (two share one name: an apartment and an officetel).
RAW = json.loads((Path(__file__).parent / 'fixtures/subscriptions/bundle-2026-11-18.json').read_text())
BUNDLE = sanitize(RAW, NOW)
DH, JH, BC, BU, JO = '2026940256', '2026000497', '2026940260', '2026000457', '2026950090'
SUMMARY = ('서초구 디에이치 신반포에스테라는 임의공급 단지예요. 중랑구 중화역 라온프라이빗 센트로는 '
           '신혼부부·다자녀가구 특별공급과 1순위 접수가 있어요.')
HOST = sp.host(BUNDLE, NOW)


def draft(summary=SUMMARY, picks=None):
    return dict(summary=summary, picks=picks if picks is not None else [
        dict(id=DH, line='서초구 임의공급'), dict(id=JH, line='신혼부부·신생아 특별공급')])


def one(cid, line):
    # The summary names 서울 and 경기, so the second pick is a Gyeonggi complex (or a Seoul one for BU).
    other = dict(id=DH, line='서초구 임의공급') if cid == BU else dict(id=BU, line='경기 부천 공공분양')
    return draft(summary='서울과 경기에서 접수하는 단지 몇 곳을 골라 보았어요. 조건은 모집공고문에서 확인하세요.',
                 picks=[dict(id=cid, line=line), other])


def stored(day='2026-11-18', generated=NOW, source='ai', summary=SUMMARY, picks=None):
    if picks is None:
        picks = draft()['picks'] if source == 'ai' else [dict(id=DH, line=None)]
    return dict(schema_version=1, generated_at=generated.isoformat(), day=day, source=source,
                summary=summary if source == 'ai' else None, picks=picks)


class HostTests(unittest.TestCase):
    def test_bundle_fixture_is_valid(self):
        self.assertEqual(len(BUNDLE['items']), 5)

    def test_host_orders_by_next_receipt(self):
        # JH's 1순위 receipt is still open on 11-18, so it comes before DH's receipt that starts that day.
        self.assertEqual((HOST['schema_version'], HOST['mode'], HOST['synthetic'], HOST['day']),
                         ('subscription-input-v1', 'api_agent', False, '2026-11-18'))
        self.assertEqual([c['id'] for c in HOST['candidates']], [JH, DH, BC, BU, JO])
        first = HOST['candidates'][0]
        self.assertEqual(set(first), {'id', 'name', 'area', 'district', 'supply', 'steps', 'units', 'special', 'regulation'})
        self.assertEqual((first['area'], first['district'], first['supply']), ('서울', '중랑구', '아파트 분양'))
        self.assertEqual(first['special'][:2], ['신혼부부', '다자녀가구'])
        self.assertEqual(first['regulation'], ['투기과열지구', '청약과열지역'])
        self.assertEqual(first['steps'][0], {'label': '특별공급', 'start': '2026-11-16', 'end': '2026-11-16'})

    def test_host_none_below_minimum(self):
        self.assertIsNone(sp.host(dict(BUNDLE, items=BUNDLE['items'][:1]), NOW))
        self.assertIsNone(sp.host(None, NOW))


class ReviewTests(unittest.TestCase):
    def test_review_ok(self):
        self.assertEqual(sp.review(draft(), HOST), [])

    def test_names_with_digits_may_be_written_whole(self):
        ok = draft(summary='성남시 분당구 더샵 분당센트로(7차)는 임의공급으로 다시 접수를 받아요. 조건은 공고문에서 확인하세요.',
                   picks=[dict(id=BC, line='분당구 임의공급')])
        self.assertEqual(sp.review(ok, HOST), [])

    def test_no_numbers(self):
        for line in ('전용 84㎡', '5세대 모집', '11/18 접수', '２세대'):
            self.assertIn('number', sp.review(one(DH, line), HOST), line)
        self.assertIn('number', sp.review(draft(summary=SUMMARY + ' 총 113세대예요.'), HOST))

    def test_ranked_rounds_are_facts_not_numbers(self):
        self.assertEqual(sp.review(one(JH, '특별공급 다음 1순위·2순위'), HOST), [])
        self.assertIn('fact', sp.review(one(DH, '1순위 접수'), HOST))  # an 임의공급 has no 1순위 step

    def test_relative_time_rejected(self):
        for line in ('곧 마감', '오늘 접수', '이번 주 접수', '마감 임박', '서둘러요', '내일까지'):
            self.assertIn('relative', sp.review(one(DH, line), HOST), line)

    def test_no_eligibility_odds_or_price_judgement(self):
        for line in ('당첨 확률이 높아요', '시세차익 기대', '청약통장 없이 신청', '누구나 접수', '분양가가 저렴해요', '경쟁률 낮음',
                     '로또 청약', '투자하기 좋아요', '줍줍 기회', '신청할 수 있어요', '가격이 싸요', '무조건 넣어 보세요'):
            self.assertIn('claim', sp.review(one(DH, line), HOST), line)

    def test_summary_names_unpicked_complex(self):
        bad = draft(summary=SUMMARY + ' 부천대장 하우스토리 디센트도 있어요.')
        self.assertIn('summary_item', sp.review(bad, HOST))
        bad = draft(summary='디에이치 신반포에스테라와 더샵 분당센트로는 임의공급으로 접수를 받는 단지예요.',
                    picks=[dict(id=DH, line='서초구 임의공급')])
        self.assertIn('summary_item', sp.review(bad, HOST))

    def test_region_and_supply_words_must_belong_to_the_picks(self):
        self.assertIn('fact', sp.review(one(DH, '서초구 특별공급'), HOST))         # DH has no 특별공급
        self.assertIn('fact', sp.review(one(DH, '분당구 임의공급'), HOST))          # DH is in 서초구
        self.assertIn('fact', sp.review(one(DH, '투기과열지구 단지'), HOST))
        only_seoul = draft(summary='경기 서초구 디에이치 신반포에스테라는 임의공급 단지예요. 조건은 공고문에서 확인하세요.',
                           picks=[dict(id=DH, line='서초구 임의공급')])
        self.assertIn('fact', sp.review(only_seoul, HOST))
        self.assertEqual(sp.review(one(BU, '분양가상한제 공공분양'), HOST), [])

    def test_short_place_and_special_names_are_checked_too(self):
        # 2026-11-18 review: models write 분당 for 성남시 분당구 and 다자녀 for 다자녀가구.
        self.assertEqual(sp.review(one(DH, '서초 임의공급'), HOST), [])
        self.assertEqual(sp.review(one(JH, '다자녀·노부모 특별공급'), HOST), [])
        for line in ('분당 임의공급', '중랑 임의공급', '다자녀 대상'):
            self.assertIn('fact', sp.review(one(DH, line), HOST), line)
        only_dh = draft(summary='분당에서는 디에이치 신반포에스테라가 임의공급으로 접수를 받아요. 조건은 공고문에서 확인하세요.',
                        picks=[dict(id=DH, line='서초구 임의공급')])
        self.assertIn('fact', sp.review(only_dh, HOST))

    def test_more_eligibility_wordings(self):
        # 2026-11-18 PR #67 review.
        for line in ('무주택이면 신청 가능', '청약 가능해요', '청약통장이 없어도 돼요', '통장 없어도 접수', '자격이 돼요'):
            self.assertIn('claim', sp.review(one(DH, line), HOST), line)
        self.assertEqual(sp.review(one(DH, '서초구 임의공급, 조건은 공고문 확인'), HOST), [])

    def test_summary_facts_follow_the_complex_named_in_the_same_clause(self):
        swapped = draft(summary='중랑구 중화역 라온프라이빗 센트로는 임의공급, 서초구 디에이치 신반포에스테라는 신혼부부 특별공급을 받아요.')
        self.assertIn('fact', sp.review(swapped, HOST))
        # A clause that names no complex may use any picked complex's facts.
        ok = draft(summary='서울 서초구와 중랑구에서 접수가 열려요. 임의공급과 특별공급이 함께 있어요. 조건은 공고문에서 확인하세요.')
        self.assertEqual(sp.review(ok, HOST), [])

    def test_unpicked_name_containing_a_picked_name_is_caught(self):
        rows = [dict(c) for c in HOST['candidates']]
        longer = dict(rows[1], id='2026999001', name=rows[1]['name'] + ' 센트럴')
        host = dict(HOST, candidates=rows + [longer])
        bad = draft(summary='서초구 디에이치 신반포에스테라 센트럴은 임의공급 단지예요. 조건은 공고문에서 확인하세요.',
                    picks=[dict(id=DH, line='서초구 임의공급')])
        self.assertIn('summary_item', sp.review(bad, host))
        good = dict(bad, summary='서초구 디에이치 신반포에스테라는 임의공급 단지예요. 조건은 공고문에서 확인하세요.')
        self.assertEqual(sp.review(good, host), [])

    def test_shape_counts_lengths_markup(self):
        self.assertEqual(sp.review({'summary': SUMMARY}, HOST), ['draft_shape'])
        self.assertEqual(sp.review(draft(picks=[dict(id=DH, line='x', extra=1)]), HOST), ['draft_shape'])
        self.assertIn('picks_count', sp.review(draft(picks=[]), HOST))
        self.assertIn('picks_unknown', sp.review(one('999', '단지'), HOST))
        self.assertIn('picks_duplicate', sp.review(draft(picks=[dict(id=DH, line='서초구 임의공급')] * 2), HOST))
        self.assertIn('line_length', sp.review(one(DH, '가' * 41), HOST))
        self.assertIn('summary_length', sp.review(draft(summary='짧아요'), HOST))
        self.assertIn('markup', sp.review(one(DH, '서초구 <b>'), HOST))
        self.assertIn('markup', sp.review(one(DH, 'https://x.kr'), HOST))


class PublicTests(unittest.TestCase):
    def test_rule_pick(self):
        pick = sp.rule_pick(HOST, NOW)
        self.assertEqual((pick['source'], pick['summary']), ('rule', None))
        self.assertEqual([p['id'] for p in pick['picks']], [JH, DH, BC])

    def test_public_keeps_a_valid_ai_pick(self):
        pick = sp.public(stored(), BUNDLE, [], NOW)
        self.assertEqual((pick['source'], pick['summary']), ('ai', SUMMARY))

    def test_public_rejects_bad_or_old_picks(self):
        self.assertIsNone(sp.public(dict(stored(), extra=1), BUNDLE, [], NOW))
        self.assertIsNone(sp.public(stored(generated=NOW + timedelta(hours=1)), BUNDLE, [], NOW))
        self.assertIsNone(sp.public(stored(), None, [], NOW))
        self.assertEqual(sp.public(stored(generated=NOW - timedelta(hours=40)), BUNDLE, [], NOW)['source'], 'rule')
        bad = stored(picks=[dict(id=DH, line='당첨 확률 높음')])
        self.assertEqual(sp.public(bad, BUNDLE, [], NOW)['source'], 'rule')
        self.assertEqual(sp.public(stored(source='rule'), BUNDLE, [], NOW), sp.rule_pick(sp.host(BUNDLE, NOW), NOW))

    def test_public_drops_ended_complex_and_its_summary(self):
        later = datetime.fromisoformat('2026-11-20T09:00:00+09:00')
        three = stored(generated=later - timedelta(hours=1), summary='서울과 경기에서 접수하는 단지 몇 곳을 골라 보았어요. 조건은 공고문에서 확인하세요.',
                       picks=[dict(id=DH, line='서초구 임의공급'), dict(id=BC, line='분당구 임의공급'), dict(id=BU, line='부천 공공분양'),
                              dict(id=JO, line='중랑구 오피스텔')])
        pick = sp.public(three, sanitize(RAW, later, allow_stale=True), [], later)
        self.assertEqual(([p['id'] for p in pick['picks']], pick['summary']), ([BC, BU, JO], None))

    def test_admin_mute_gives_rule_card(self):
        mute = [dict(kind=sp.TAKEDOWN_KIND, day='2026-11-18')]
        self.assertEqual(sp.public(stored(), BUNDLE, mute, NOW)['source'], 'rule')
        self.assertEqual(sp.public(stored(), BUNDLE, [dict(kind='festival_pick_text', day='2026-11-18')], NOW)['source'], 'ai')


class RefreshTests(unittest.TestCase):
    def run_refresh(self, invoke_result=None, model=None, execute=True, root=None, raw=RAW):
        if root is None:
            tmp = tempfile.TemporaryDirectory(dir=Path(sp.__file__).resolve().parents[1])
            self.addCleanup(tmp.cleanup)
            root = Path(tmp.name)
        save(root / FILE, raw)
        calls = []

        def invoke(r, kind, path):
            calls.append((kind, json.loads(Path(path).read_text())))
            self.assertEqual(load(root / 'cache/subscription_pick/days.json', {})['days']['2026-11-18']['status'], 'attempted')
            if model is not None:
                save(root / '.tools/claude-trial/live/runs/run1/result.json', model)
            return invoke_result or {'status': 'validated_draft', 'run_id': 'run1'}
        with patch.object(sp, 'invoke', side_effect=invoke), patch.object(sp, 'TRIAL_RUNS', root / '.tools/claude-trial/live/runs'):
            result = sp.refresh(root, NOW, execute=execute)
        return result, calls, load(root / 'cache/subscription_pick/pick.json', None), root

    def test_valid_draft_becomes_ai_pick_once_a_day(self):
        result, calls, pick, root = self.run_refresh(model=draft())
        self.assertEqual([k for k, _ in calls], ['subscription'])
        self.assertEqual(calls[0][1], HOST)
        self.assertEqual((pick['source'], pick['summary'], result['source']), ('ai', SUMMARY, 'ai'))
        _, calls, pick, _ = self.run_refresh(root=root, model=draft())
        self.assertEqual((calls, pick['source']), ([], 'ai'))

    def test_rejected_or_failing_draft_gives_rule(self):
        _, calls, pick, _ = self.run_refresh(invoke_result={'status': 'rejected_draft', 'run_id': None})
        self.assertEqual((pick['source'], len(calls)), ('rule', 1))
        result, _, pick, _ = self.run_refresh(model=one(DH, '당첨 확률 높음'))
        self.assertEqual(pick['source'], 'rule')
        self.assertIn('claim', result['errors'])

    def test_no_spend_without_execute(self):
        _, calls, pick, _ = self.run_refresh(execute=False)
        self.assertEqual((calls, pick['source']), ([], 'rule'))

    def test_missing_bundle_means_no_card_and_no_call(self):
        result, calls, pick, _ = self.run_refresh(raw=None)
        self.assertEqual((result['status'], calls, pick), ('no_candidates', [], None))
        few = deepcopy(RAW)
        few['items'] = few['items'][:1]
        result, calls, pick, _ = self.run_refresh(raw=few)
        self.assertEqual((result['status'], calls, pick['source']), ('completed', [], 'rule'))


if __name__ == '__main__':
    unittest.main()
