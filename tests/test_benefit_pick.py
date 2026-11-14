import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import benefit_pick as bp
from benefit_monitor.store import load, save

NOW = datetime.fromisoformat('2026-11-14T07:00:00+09:00')


def row(source, url, title, summary, conditions, fee, valid_from=None, valid_until=None, deadline_at=None, labels=None):
    return dict(source=source, url=url, title=title, summary=summary, conditions=conditions, districts=[],
                verified_at='2026-11-04T20:11:09+09:00', valid_from=valid_from, valid_until=valid_until,
                deadline_at=deadline_at, validity_kind='fixed' if valid_until else 'ongoing', fee_status=fee,
                needs_recheck=False, payment_terms={}, labels=labels or {}, review={'kind': 'human'},
                display_until='2026-11-18T20:11:09+09:00')


# Real 2026-11-14 rows from briefing-data (trimmed to the fields the pick reads).
COGPE = row('seoul', 'https://mediahub.seoul.go.kr/archives/2019868', "최대 15% 할인! 서울사랑상품권 '코.그.페' 행사",
            '서울사랑상품권 결제 추가 5% 페이백',
            '10월29일~11월15일 광역·25개 구 서울사랑상품권 결제액의 추가 5% 페이백. 기존 보유 대상 상품권도 포함. 별도 신청 없이 10월 결제분은 '
            '11월20일, 11월 결제분은 12월20일 상품권 지급 예정. 구매 할인·기존 페이백은 상품권별로 달라 모두 15% 혜택이 아님. 구매비용 발생.',
            'paid', '2026-10-29', '2026-11-15', labels={'category': '할인·적립', 'region': '서울', 'action': '결제 시 적용'})
BUS = row('seoul', 'https://mediahub.seoul.go.kr/archives/2019836', '청계 A01 무료 야간 자율주행버스',
          '평일 저녁 청계광장~광장시장 무료 자율주행버스',
          '평일 19:00~23:50 운행 안내(주말·공휴일 미운행), 청계광장 출발 막차 23:00. 30분 간격 하루9회, 최대8명 탑승.', 'free',
          '2026-10-22', labels={'category': '생활지원', 'region': '서울 청계광장~광장시장', 'action': '바로 이용'})
ROOM = row('seoul', 'https://mediahub.seoul.go.kr/archives/2019121', "완벽 방음에 최신 장비 갖춘 '화상면접실'이 무료! '서울청년센터 성북'",
           '성북청년센터 화상면접실 무료 이용',
           '서울 생활권 19~39세 청년. 공공서비스예약 신청 후 승인 및 신분 확인 필요. 평일10~21시·토10~16시, 월5회·하루1회 최대4시간.', 'free',
           labels={'category': '생활지원', 'region': '서울 성북구', 'action': '신청·예약 필요'})
YOGA = row('eshare', 'https://www.eshare.go.kr/UserPortal/Upv/UprResrcEdu/index.do?rsrc_no=EJ29L5730846&rsrc_dcd=CPS001.006',
           '[공유누리] 요가(오전2반) · 서울 성북구 종암로25길 29 (종암동)', '서울 성북구 종암동 자치회관 요가(오전2반) 강좌, 월·수·금 11:00~12:00',
           '방문시 요금납부; 예약승인 후 공공목적 취소 가능. 비용: 기본요금 25,000원, 강좌 수강료 75,000원(분기). 결제 조건: 방문시 요금납부',
           'paid')
ITEMS = [YOGA, ROOM, BUS, COGPE]
CID, BID, RID, YID = (bp.item_id(r) for r in (COGPE, BUS, ROOM, YOGA))
SUMMARY = '서울사랑상품권 추가 페이백이 11/15에 끝나니 이번 주말 결제를 챙겨 보세요.'


def draft(summary=SUMMARY, picks=None):
    return dict(summary=summary, picks=picks if picks is not None else [
        dict(id=CID, line='결제액 추가 5% 페이백, 상품권 구매 필요'), dict(id=BID, line='무료'), dict(id=RID, line='무료')])


def stored(day='2026-11-14', generated=NOW, source='ai', summary=SUMMARY, picks=None):
    if picks is None:
        picks = draft()['picks'] if source == 'ai' else [dict(id=CID, line=None)]
    return dict(schema_version=1, generated_at=generated.isoformat(), day=day, source=source,
                summary=summary if source == 'ai' else None, picks=picks)


def one(cid, line):
    # The summary names 서울사랑상품권, so it is only checked when that benefit is among the picks.
    return draft(summary=SUMMARY if cid == CID else '이번 주말에는 서울에서 챙겨 볼 만한 혜택 몇 가지를 골라 보았어요.', picks=[dict(id=cid, line=line), dict(id=BID, line='무료'), dict(id=RID, line='무료')])


HOST = bp.host(ITEMS, NOW)


class HostTests(unittest.TestCase):
    def test_item_id(self):
        self.assertEqual(len(CID), 12)
        self.assertEqual(CID, bp.item_id(dict(source='seoul', url=COGPE['url'])))

    def test_host_orders_by_deadline(self):
        self.assertEqual(HOST['candidates'][0]['title'], COGPE['title'])
        self.assertEqual((HOST['schema_version'], HOST['mode'], HOST['synthetic'], HOST['day']),
                         ('benefit-input-v1', 'api_agent', False, '2026-11-14'))
        rest = [c['title'] for c in HOST['candidates'][1:]]
        self.assertEqual(rest, sorted(rest))
        first = HOST['candidates'][0]
        self.assertEqual((first['category'], first['region'], first['fee_status']), ('할인·적립', '서울', 'paid'))
        self.assertLessEqual(len(first['conditions']), 200)

    def test_host_none_below_minimum(self):
        self.assertIsNone(bp.host(ITEMS[:2], NOW))

    def test_ended_items_are_not_candidates(self):
        later = datetime.fromisoformat('2026-11-16T07:00:00+09:00')
        self.assertNotIn(COGPE['title'], [c['title'] for c in bp.host(ITEMS, later)['candidates']] if bp.host(ITEMS, later) else [])


class ReviewTests(unittest.TestCase):
    def test_review_ok(self):
        self.assertEqual(bp.review(draft(), HOST), [])

    def test_max_percent_rejected(self):
        self.assertIn('claim', bp.review(one(CID, '최대 15% 할인'), HOST))

    def test_paid_needs_cost(self):
        self.assertEqual(bp.review(one(CID, '추가 5% 페이백'), HOST), ['cost'])

    def test_free_only_when_free(self):
        self.assertIn('free', bp.review(one(YID, '무료 수업'), HOST))

    def test_free_synonyms_need_free_status(self):
        for word in ('공짜 수업', '무상 수강', '0원 수업', '수강료 0원'):
            self.assertIn('free', bp.review(one(YID, word + ', 결제'), HOST), word)
        self.assertNotIn('free', bp.review(one(YID, '수강료 75,000원, 결제'), HOST))
        self.assertNotIn('free', bp.review(one(CID, '구매 필요 10원'), HOST))

    def test_summary_free_is_attributed_to_the_named_benefit(self):
        ok = bp.review(draft(summary='청계 A01 야간 자율주행버스는 무료로 타 볼 수 있어요. 서울사랑상품권 결제도 챙기세요.'), HOST)
        self.assertNotIn('free', ok)
        bad = bp.review(draft(summary='서울사랑상품권 추가 페이백은 무료로 받아요. 청계 A01 야간 자율주행버스도 있어요.'), HOST)
        self.assertIn('free', bad)
        self.assertIn('free', bp.review(draft(summary='이번 주말에는 무료로 즐길 수 있는 혜택이 여러 가지 있어요 확인하세요.'), HOST))

    def test_eligibility_and_stock_words(self):
        self.assertIn('claim', bp.review(draft(summary='서울사랑상품권 페이백은 누구나 11/15까지 결제하면 되니 챙기세요.'), HOST))
        self.assertIn('claim', bp.review(one(BID, '무료, 받을 수 있어요'), HOST))
        for word in ('남은 자리', '잔여석', '소진 전까지', '자리 있음'):
            self.assertIn('stock', bp.review(one(BID, '무료, ' + word), HOST), word)
        self.assertNotIn('stock', bp.review(one(BID, '무료, 마감 임박'), HOST))

    def test_dates_must_match_the_benefit(self):
        self.assertIn('number', bp.review(one(CID, '11/20까지 결제, 구매 필요'), HOST))
        self.assertEqual(bp.review(one(CID, '11/15까지 결제, 구매 필요'), HOST), [])
        self.assertEqual(bp.review(one(CID, '10월 29일부터 결제, 구매 필요'), HOST), [])
        self.assertIn('number', bp.review(one(CID, '10월 29일까지 결제, 구매 필요'), HOST))
        self.assertIn('number', bp.review(one(CID, '11월 15일부터 결제, 구매 필요'), HOST))
        self.assertEqual(bp.review(one(CID, '10/29~11/15 결제, 구매 필요'), HOST), [])
        self.assertIn('number', bp.review(one(CID, '10/29~11/30 결제, 구매 필요'), HOST))
        self.assertIn('number', bp.review(one(BID, '무료, 10/22 시작, 11/15'), HOST))  # 11/15 is not this benefit's date

    def test_numbers_need_their_unit_verbatim(self):
        self.assertIn('number', bp.review(one(CID, '결제액 15% 페이백, 구매 필요'), HOST))
        self.assertIn('number', bp.review(one(CID, '결제액 추가 50% 페이백, 구매 필요'), HOST))
        self.assertIn('number', bp.review(one(CID, '결제액 추가 5,000원 환급, 구매 필요'), HOST))
        self.assertEqual(bp.review(one(YID, '수강료 75,000원(분기), 결제 필요'), HOST), [])
        self.assertEqual(bp.review(one(YID, '수강료 75000원, 결제 필요'), HOST), [])
        self.assertIn('number', bp.review(one(YID, '수강료 7,500원, 결제 필요'), HOST))
        self.assertIn('number', bp.review(one(BID, '무료, 30명 탑승'), HOST))

    def test_summary_numbers_belong_to_the_named_benefit(self):
        self.assertIn('number', bp.review(draft(summary='청계 A01 야간 자율주행버스는 무료이고 서울사랑상품권은 11/20에 끝나요.'), HOST))
        self.assertIn('number', bp.review(draft(summary='이번 주말 11/15까지 챙길 혜택을 골라 보았으니 확인해 보세요.'), HOST))
        self.assertIn('number', bp.review(draft(summary='서울사랑상품권 페이백이 15%까지 늘어나니 이번 주말 결제를 챙기세요.'), HOST))
        self.assertEqual(bp.review(draft(summary='서울사랑상품권 5% 페이백이 11/15에 끝나니 이번 주말 결제를 챙기세요.'), HOST), [])

    def test_shape_ids_lengths_and_markup(self):
        self.assertEqual(bp.review({'summary': SUMMARY}, HOST), ['draft_shape'])
        self.assertEqual(bp.review(draft(picks=[dict(id=CID, line='x', extra=1)]), HOST), ['draft_shape'])
        self.assertIn('picks_count', bp.review(draft(picks=draft()['picks'][:2]), HOST))
        self.assertIn('picks_unknown', bp.review(one('zzz', '무료'), HOST))
        self.assertIn('picks_duplicate', bp.review(draft(picks=[dict(id=BID, line='무료')] * 3), HOST))
        self.assertIn('line_length', bp.review(one(BID, '무료' * 30), HOST))
        self.assertIn('line_length', bp.review(one(BID, ''), HOST))
        self.assertIn('summary_length', bp.review(draft(summary='짧아요'), HOST))
        self.assertIn('markup', bp.review(one(BID, '무료 <b>'), HOST))
        self.assertIn('markup', bp.review(draft(summary=SUMMARY + ' https://x.kr'), HOST))


class PublicTests(unittest.TestCase):
    def test_public_fills_source_url(self):
        pick = bp.public(stored(), ITEMS, [], NOW)
        self.assertEqual((pick['source'], pick['summary']), ('ai', SUMMARY))
        by_id = {bp.item_id(r): r for r in ITEMS}
        for line in pick['picks']:
            self.assertEqual(set(line), {'id', 'source', 'url', 'line'})
            self.assertEqual((line['source'], line['url']), (by_id[line['id']]['source'], by_id[line['id']]['url']))

    def test_public_drops_missing_items(self):
        pick = bp.public(stored(), [r for r in ITEMS if r is not COGPE], [], NOW)
        self.assertEqual(pick['source'], 'rule')
        self.assertIsNone(pick['summary'])
        self.assertEqual(len(pick['picks']), 3)
        self.assertTrue(all(p['line'] is None for p in pick['picks']))

    def test_public_removes_one_line_and_summary_keeps_enough_lines(self):
        extra = row('seoul', 'https://x.kr/1', '제철 차 학습라운지', '무료 교육 운영', '16개 프로그램 무료 운영', 'free')
        four = draft(picks=draft()['picks'] + [dict(id=bp.item_id(extra), line='무료')])['picks']
        items = [r for r in ITEMS + [extra] if r is not COGPE]
        pick = bp.public(stored(picks=four), items, [], NOW)
        self.assertEqual(pick['source'], 'ai')
        self.assertIsNone(pick['summary'])
        self.assertEqual([p['id'] for p in pick['picks']], [BID, RID, bp.item_id(extra)])

    def test_stale_and_mute(self):
        old = bp.public(stored(generated=NOW - timedelta(hours=37)), ITEMS, [], NOW)
        self.assertEqual((old['source'], old['summary']), ('rule', None))
        mute = [{'kind': 'benefit_pick_text', 'day': '2026-11-14'}]
        pick = bp.public(stored(), ITEMS, mute, NOW)
        self.assertEqual((pick['source'], pick['summary']), ('rule', None))
        self.assertTrue(all(set(p) == {'id', 'source', 'url', 'line'} for p in pick['picks']))
        other = [{'kind': 'benefit_pick_text', 'day': '2026-11-13'}]
        self.assertEqual(bp.public(stored(), ITEMS, other, NOW)['source'], 'ai')
        self.assertEqual(bp.apply_mute(stored(), ITEMS, mute, NOW)['source'], 'rule')

    def test_public_rejects_bad_shape_and_future(self):
        self.assertIsNone(bp.public(None, ITEMS, [], NOW))
        self.assertIsNone(bp.public(dict(stored(), extra=1), ITEMS, [], NOW))
        self.assertIsNone(bp.public(stored(generated=NOW + timedelta(hours=1)), ITEMS, [], NOW))
        self.assertIsNone(bp.public(stored(), [], [], NOW))

    def test_public_rereviews_against_current_items(self):
        changed = [dict(r, fee_status='paid') if r is BUS else r for r in ITEMS]
        self.assertEqual(bp.public(stored(), changed, [], NOW)['source'], 'rule')

    def test_rule_pick_order_and_size(self):
        many = ITEMS + [row('seoul', f'https://x.kr/{i}', f'혜택 번호 {i}', '요약', '조건', 'free') for i in range(5)]
        rule = bp.rule_pick(bp.host(many, NOW), NOW)
        self.assertEqual((rule['source'], rule['summary'], rule['day']), ('rule', None, '2026-11-14'))
        self.assertEqual(len(rule['picks']), 5)
        self.assertEqual(rule['picks'][0], dict(id=CID, line=None))


class RefreshTests(unittest.TestCase):
    def run_refresh(self, invoke_result=None, model=None, execute=True, root=None, items=ITEMS, now=NOW):
        if root is None:
            tmp = tempfile.TemporaryDirectory(dir=Path(bp.__file__).resolve().parents[1])
            self.addCleanup(tmp.cleanup)
            root = Path(tmp.name)
        calls = []

        def invoke(r, kind, path):
            calls.append((kind, json.loads(Path(path).read_text())))
            self.assertEqual(load(root / 'cache/benefit_pick/days.json', {})['days']['2026-11-14']['status'], 'attempted')
            if model is not None:
                save(root / '.tools/claude-trial/live/runs/run1/result.json', model)
            return invoke_result or {'status': 'validated_draft', 'run_id': 'run1'}
        with patch.object(bp, 'invoke', side_effect=invoke), patch.object(bp, 'TRIAL_RUNS', root / '.tools/claude-trial/live/runs'):
            result = bp.refresh(root, now, execute=execute, items=items)
        return result, calls, load(root / 'cache/benefit_pick/pick.json', None), root

    def test_refresh_one_call_a_day(self):
        result, calls, pick, root = self.run_refresh(model=draft())
        self.assertEqual([k for k, _ in calls], ['benefit'])
        self.assertEqual(calls[0][1], HOST)
        self.assertEqual((pick['source'], pick['summary'], result['source']), ('ai', SUMMARY, 'ai'))
        result, calls, pick, _ = self.run_refresh(root=root, model=draft())
        self.assertEqual((calls, pick['source']), ([], 'ai'))

    def test_refresh_rule_on_rejected_and_review_failure(self):
        result, calls, pick, root = self.run_refresh(invoke_result={'status': 'rejected_draft', 'run_id': None})
        self.assertEqual((pick['source'], len(calls)), ('rule', 1))
        _, calls, pick, _ = self.run_refresh(root=root)
        self.assertEqual((calls, pick['source']), ([], 'rule'))
        result, _, pick, _ = self.run_refresh(model=one(CID, '최대 15% 할인'))
        self.assertEqual(pick['source'], 'rule')
        self.assertIn('claim', result['errors'])

    def test_no_spend_without_execute(self):
        _, calls, pick, _ = self.run_refresh(execute=False)
        self.assertEqual((calls, pick['source']), ([], 'rule'))

    def test_few_items_give_no_candidates(self):
        result, calls, pick, _ = self.run_refresh(items=[])
        self.assertEqual((result['status'], calls, pick), ('no_candidates', [], None))
        result, calls, pick, _ = self.run_refresh(items=ITEMS[:2])  # rule card, no paid call
        self.assertEqual((calls, pick['source']), ([], 'rule'))

    def test_missing_report_means_no_candidates_and_no_call(self):
        tmp = tempfile.TemporaryDirectory(dir=Path(bp.__file__).resolve().parents[1])
        self.addCleanup(tmp.cleanup)
        with patch.object(bp, 'invoke') as mocked, patch('benefit_monitor.publish.payload', side_effect=ValueError('no report')):
            result = bp.refresh(Path(tmp.name), NOW, execute=True)
        self.assertEqual(result['status'], 'no_candidates')
        mocked.assert_not_called()


if __name__ == '__main__':
    unittest.main()
