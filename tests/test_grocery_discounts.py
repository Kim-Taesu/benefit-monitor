import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from benefit_monitor import grocery_discounts as gd

TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))


def basket():
    rows = [("pork_belly", "삼겹살", ["삼겹살", "삼겹", "돼지고기"], "고기·알"),
            ("pork_neck", "목심", ["목심", "목살"], "고기·알"),
            ("pork_shoulder", "앞다리", ["앞다리"], "고기·알"),
            ("hanwoo_sirloin", "한우 등심 1등급", ["한우", "등심", "소고기"], "고기·알"),
            ("us_short_rib", "미국산 갈비살", ["갈비살", "미국산"], "고기·알"),
            ("chicken", "닭(육계)", ["닭", "닭고기"], "고기·알"),
            ("egg_tray", "계란 30구", ["계란", "달걀"], "고기·알"),
            ("radish", "무", ["무", "가을무"], "채소"),
            ("onion", "양파", ["양파"], "채소"),
            ("green_onion", "대파", ["대파", "파"], "채소"),
            ("banana", "바나나", ["바나나"], "기타"),
            ("mackerel", "고등어", ["고등어", "생선"], "기타"),
            ("squid", "오징어", ["오징어"], "기타")]
    return [dict(id=i, name=n, aliases=a, group=g, row=dict(kind="produce", id=i)) for i, n, a, g in rows]


def _md(value):
    return f"{int(value[5:7])}월 {int(value[8:10])}일"


def event(title, summary="", conditions="", start="2026-11-07", end="2026-11-27", kind="fixed", url="https://www.mof.go.kr/a",
          dated=True, **extra):
    # Real items state their period in a sentence of its own; dated=False leaves the start date out of the text.
    if dated and isinstance(start, str) and isinstance(end, str):
        conditions = " ".join(x for x in (conditions, f"행사 기간 {_md(start)}~{_md(end)}.") if x)
    return dict(dict(title=title, summary=summary, conditions=conditions, valid_from=start, valid_until=end,
                     validity_kind=kind, url=url, source="mof_press", review={}), **extra)


# Copied from public/verified.json (2026-11-11): human-approved, free-text region, per-item periods in conditions.
KOREA_GRAND_FESTIVAL = {
    "source": "government",
    "url": "https://www.korea.kr/news/policyNewsView.do?newsId=148974363",
    "title": "코리아 그랜드 페스티벌 할인 일정",
    "summary": "전국 소비행사: 한우·수산물·상품권 등 품목별 할인 예정",
    "valid_until": "2026-11-15",
    "verified_at": "2026-11-04T10:09:55.303287+09:00",
    "needs_recheck": False,
    "valid_from": "2026-10-29",
    "published_at": None,
    "conditions": "통합 행사 기간 10월29일~11월15일. 한우는 10월28일~11월8일 최대50%, 모바일 농할상품권은 11월2~15일 20% 할인 판매 안내. 품목별·매장별 가격과 기간이 다르며 모든 상품에 최대 할인율이 적용되지 않음. 구매비용 발생. 판매처·한도·결제조건·재고는 개별 공식 행사 안내에서 추가 확인 필요. 자료출처: 대한민국 정책브리핑.",
    "evidence": "공식 원문 본문의 기간 및 참여 조건을 2026-10-27 직접 확인. 개인정보와 이용 실적은 확인하지 않음.",
    "districts": [],
    "review_notes": "2026-11-04 공식 원문 재확인: 일정·대상·요금·조건 대조. 저장된 내용과 차이 없음. 10:00 실행의 본문 변경 보류는 조회수·인기뉴스 등 페이지 부가 영역 변화로 확인. 재수집 원문 본문이 09:59 확인본과 동일하여 재확인.",
    "fee_status": "paid",
    "validity_kind": "fixed",
    "deadline_at": None,
    "excluded_reason": "",
    "public_release": True,
    "labels": {"category": "할인·적립", "region": "전국 참여 유통업체", "action": "결제 시 적용"},
}


def ids(links):
    return [x["basket_id"] for x in links]


class LinkTests(unittest.TestCase):
    def test_link_fish_event_to_mackerel_and_squid_only(self):
        links = gd.link([event("한국 수산식품 홍보주간 개최", "대형마트·온라인몰에서 수산식품 최대 50% 할인")], basket(), TODAY)
        self.assertEqual(ids(links), ["mackerel", "squid"])
        self.assertEqual(links[0]["discount"], "최대 50%")
        self.assertEqual(links[0]["stores"], "대형마트·온라인몰")
        self.assertEqual((links[0]["start"], links[0]["end"], links[0]["url"]),
                         ("2026-11-07", "2026-11-27", "https://www.mof.go.kr/a"))

    def test_link_skips_ended_event(self):
        self.assertEqual(gd.link([event("수산식품 할인", end="2026-11-10")], basket(), TODAY), [])

    def test_link_skips_not_started_event(self):
        self.assertEqual(gd.link([event("수산식품 할인", start="2026-11-12")], basket(), TODAY), [])

    def test_link_requires_fixed_validity_and_both_dates(self):
        self.assertEqual(gd.link([event("수산식품 할인", start=None)], basket(), TODAY), [])
        self.assertEqual(gd.link([event("수산식품 할인", end=None)], basket(), TODAY), [])
        self.assertEqual(gd.link([event("수산식품 할인", kind="approximate")], basket(), TODAY), [])

    def test_link_hanwoo_not_attached_to_pork(self):
        links = gd.link([event("한우세일 개최")], basket(), TODAY)
        self.assertEqual(ids(links), ["hanwoo_sirloin"])

    def test_link_broad_only_not_attached(self):
        self.assertEqual(gd.link([event("농축산물 전 품목 최대 40% 할인")], basket(), TODAY), [])

    def test_link_domestic_excludes_imports(self):
        links = gd.link([event("국산 과일·바나나 할인")], basket(), TODAY)
        self.assertNotIn("banana", ids(links))
        self.assertIn("banana", ids(gd.link([event("바나나 할인")], basket(), TODAY)))
        # 미국산 contains 국산 but is not a domestic marker
        self.assertIn("us_short_rib", ids(gd.link([event("미국산 갈비살 할인")], basket(), TODAY)))

    def test_link_direct_item_name(self):
        self.assertEqual(ids(gd.link([event("양파 할인 공급")], basket(), TODAY)), ["onion"])

    def test_link_vegetables_group_and_no_single_char_alias(self):
        self.assertEqual(ids(gd.link([event("채소 할인")], basket(), TODAY)), ["green_onion", "onion", "radish"])
        self.assertEqual(gd.link([event("무료 체험 할인 행사")], basket(), TODAY), [])

    def test_link_non_discount_item_ignored(self):
        self.assertEqual(gd.link([event("수산식품 홍보주간 개최")], basket(), TODAY), [])

    def test_link_tolerates_missing_segments(self):
        links = gd.link([event("고등어 할인", summary=None, conditions=None)], basket(), TODAY)
        self.assertEqual((links[0]["discount"], links[0]["stores"]), (None, None))


class FixRoundTests(unittest.TestCase):
    def test_only_national_government_sources_link(self):
        base = "양파 할인"
        self.assertEqual(gd.link([event(base, source="retail")], basket(), TODAY), [])
        self.assertEqual(gd.link([event(base, districts=["금천구"])], basket(), TODAY), [])
        self.assertEqual(gd.link([event(base, labels={"region": "서울"})], basket(), TODAY), [])
        self.assertEqual(ids(gd.link([event(base, labels={"region": "전국"}, districts=[])], basket(), TODAY)), ["onion"])
        self.assertEqual(ids(gd.link([event(base, source="government")], basket(), TODAY)), ["onion"])
        # Human-approved items carry free-text regions such as '전국 참여 유통업체'.
        self.assertEqual(ids(gd.link([event(base, labels={"region": "전국 참여 유통업체"})], basket(), TODAY)), ["onion"])
        self.assertEqual(gd.link([event(base, labels={"region": "서울 전국구 시장"})], basket(), TODAY), [])

    def test_substring_false_positives(self):
        self.assertEqual(gd.link([event("닭갈비 축제 할인")], basket(), TODAY), [])
        self.assertEqual(gd.link([event("한우리 마을 체험 할인")], basket(), TODAY), [])
        self.assertEqual(gd.link([event("미국산 오렌지 할인")], basket(), TODAY), [])
        self.assertEqual(ids(gd.link([event("닭고기 할인")], basket(), TODAY)), ["chicken"])
        self.assertEqual(ids(gd.link([event("계란 할인")], basket(), TODAY)), ["egg_tray"])
        self.assertEqual(ids(gd.link([event("닭·계란 할인")], basket(), TODAY)), ["chicken", "egg_tray"])

    def test_percent_preferred_over_won(self):
        links = gd.link([event("고등어 할인", "고등어 1인 최대 2만원 한도, 최대 50% 할인")], basket(), TODAY)
        self.assertEqual(links[0]["discount"], "최대 50%")
        links = gd.link([event("고등어 할인", "고등어 1인 최대 2만원 한도")], basket(), TODAY)
        self.assertEqual(links[0]["discount"], "2만원 한도")

    def test_domestic_woori_needs_word_boundary(self):
        self.assertIn("banana", ids(gd.link([event("우리나라 바나나 할인")], basket(), TODAY)))
        self.assertNotIn("banana", ids(gd.link([event("우리 과일 바나나 할인")], basket(), TODAY)))


class SanitizeTests(unittest.TestCase):
    def bundle(self, **link):
        base = dict(basket_id="squid", title="t", discount=None, stores=None, start="2026-11-07",
                    end="2026-11-27", url="https://www.mof.go.kr/a")
        return dict(schema_version=1, source="grocery_discounts", generated_at="2026-11-11T09:00:00+09:00",
                    links=[dict(base, **link)])

    def test_sanitize_drops_expired_links_at_now(self):
        self.assertEqual(len(gd.sanitize(self.bundle(), NOW)["links"]), 1)
        later = datetime(2026, 11, 28, 0, 30, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertEqual(gd.sanitize(self.bundle(), later)["links"], [])
        early = datetime(2026, 11, 6, 23, 0, tzinfo=ZoneInfo("Asia/Seoul"))
        self.assertEqual(gd.sanitize(self.bundle(), early)["links"], [])

    def test_sanitize_rejects_bad_keys_and_http_url(self):
        self.assertIsNone(gd.sanitize(self.bundle(url="http://www.mof.go.kr/a"), NOW))
        bad = self.bundle()
        bad["links"][0]["extra"] = 1
        self.assertIsNone(gd.sanitize(bad, NOW))
        self.assertIsNone(gd.sanitize(dict(self.bundle(), source="x"), NOW))
        self.assertIsNone(gd.sanitize(self.bundle(end="2026-13-40"), NOW))
        over = self.bundle()
        over["links"] = over["links"] * 101
        self.assertIsNone(gd.sanitize(over, NOW))
        self.assertIsNone(gd.sanitize("x", NOW))


class ClauseTests(unittest.TestCase):
    def test_real_korea_grand_festival_never_links_hanwoo_or_its_50_percent(self):
        links = gd.link([KOREA_GRAND_FESTIVAL], basket(), TODAY)
        self.assertNotIn("hanwoo_sirloin", ids(links))
        self.assertNotIn("us_short_rib", ids(links))
        self.assertTrue(set(ids(links)) <= {"mackerel", "squid"})
        for x in links:
            self.assertNotIn("50", x["discount"] or "")
            self.assertEqual((x["start"], x["end"]), ("2026-10-29", "2026-11-15"))

    def test_clause_with_other_period_is_not_linked(self):
        links = gd.link([event("가을 먹거리 할인", "고등어는 11월 7일~11월 20일 30% 할인. 양파 20% 할인")], basket(), TODAY)
        self.assertEqual(ids(links), ["onion"])
        self.assertEqual(links[0]["discount"], "20% 할인")

    def test_discount_and_stores_come_from_the_naming_clause_only(self):
        links = gd.link([event("가을 먹거리 행사", "양파 할인 공급. 한우 최대 50% 할인, 하나로마트")], basket(), TODAY)
        onion = [x for x in links if x["basket_id"] == "onion"][0]
        self.assertEqual((onion["discount"], onion["stores"]), (None, None))
        hanwoo = [x for x in links if x["basket_id"] == "hanwoo_sirloin"][0]
        self.assertEqual((hanwoo["discount"], hanwoo["stores"]), ("최대 50%", "하나로마트"))

    def test_two_discounts_in_one_clause_give_no_discount(self):
        links = gd.link([event("고등어 할인", "고등어 20% 할인, 1마리당 2,000원 할인")], basket(), TODAY)
        self.assertIsNone(links[0]["discount"])

    def test_won_discount_keeps_full_number(self):
        self.assertEqual(gd.link([event("고등어 할인", "고등어 1마리당 2,000원 할인")], basket(), TODAY)[0]["discount"],
                         "2,000원 할인")
        self.assertEqual(gd.link([event("고등어 할인", "고등어 최대 10,000원 할인")], basket(), TODAY)[0]["discount"],
                         "10,000원 할인")

    def test_percent_range_kept_verbatim(self):
        self.assertEqual(gd.link([event("고등어 20~30% 할인")], basket(), TODAY)[0]["discount"], "20~30% 할인")

    def test_start_date_must_appear_in_text(self):
        self.assertEqual(gd.link([event("양파 할인", dated=False)], basket(), TODAY), [])
        for stated in ("11월 7일부터", "11.7.~11.27.", "11/7~11/27", "11. 7.(금)부터"):
            with self.subTest(stated=stated):
                self.assertEqual(ids(gd.link([event("양파 할인", stated, dated=False)], basket(), TODAY)), ["onion"])

    def test_end_capped_by_display_until_kst_date(self):
        links = gd.link([event("양파 할인", display_until="2026-11-20T23:59:00+00:00")], basket(), TODAY)
        self.assertEqual(links[0]["end"], "2026-11-21")  # 11-20 23:59 UTC is 11-21 in KST
        links = gd.link([event("양파 할인", display_until="2026-11-30T00:00:00+09:00")], basket(), TODAY)
        self.assertEqual(links[0]["end"], "2026-11-27")
        self.assertEqual(gd.link([event("양파 할인", display_until="2026-11-10T12:00:00+09:00")], basket(), TODAY), [])
        self.assertEqual(gd.link([event("양파 할인", display_until="bad")], basket(), TODAY), [])


class KeepPresentTests(unittest.TestCase):
    def bundle(self, *urls):
        return dict(schema_version=1, source="grocery_discounts", generated_at="2026-11-11T09:00:00+09:00",
                    links=[dict(basket_id="onion", title="t", discount=None, stores=None, start="2026-11-07",
                                end="2026-11-27", url=u) for u in urls])

    def test_keeps_only_links_of_present_government_items(self):
        items = [dict(source="mof_press", url="https://a"), dict(source="test", url="https://c")]
        kept = gd.keep_present(self.bundle("https://a", "https://b", "https://c"), items)
        self.assertEqual([x["url"] for x in kept["links"]], ["https://a"])
        self.assertIsNone(gd.keep_present(self.bundle("https://b"), items))
        self.assertIsNone(gd.keep_present("x", items))


if __name__ == "__main__":
    unittest.main()
