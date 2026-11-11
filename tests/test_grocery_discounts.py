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
        # "품목별·매장별 ... 기간이 다르며": no clause names 수산물 with both dates, so nothing links.
        self.assertEqual(gd.link([KOREA_GRAND_FESTIVAL], basket(), TODAY), [])

    def test_varying_period_phrase_needs_both_dates_in_the_item_clause(self):
        note = "품목별·매장별 가격과 기간이 다르며 모든 상품에 최대 할인율이 적용되지 않음."
        links = gd.link([event("가을 수산물 할인", "고등어는 11월 7일~11월 27일 최대 30%. 오징어도 할인", note)],
                        basket(), TODAY)
        self.assertEqual([(x["basket_id"], x["discount"]) for x in links], [("mackerel", "최대 30%")])
        for phrase in ("기간은 상이", "기간 별도", "기간 다름"):
            with self.subTest(phrase=phrase):
                self.assertEqual(gd.link([event("양파 할인", conditions=phrase)], basket(), TODAY), [])

    def test_without_varying_period_phrase_behavior_unchanged(self):
        links = gd.link([event("가을 수산물 할인", "고등어는 11월 7일~11월 27일 최대 30%. 오징어도 할인")], basket(), TODAY)
        self.assertEqual([(x["basket_id"], x["discount"]) for x in links], [("mackerel", "최대 30%"), ("squid", None)])

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


def real_basket():
    import json
    from pathlib import Path
    from benefit_monitor.grocery_baselines import basket as load_basket
    source = json.loads((Path(__file__).resolve().parents[1] / "sources/groceries.json").read_text(encoding="utf-8"))
    return [{k: b[k] for k in ("id", "name", "aliases", "group", "row")} for b in load_basket(source["collect"])]


class ReviewFixTests(unittest.TestCase):
    """2026-11-11 /code-review findings (ledger .ax/review-ledger-grocery-discount.md)."""

    def test_1_farm_and_fishery_compound_is_broad_not_seafood(self):
        for title in ("농축수산물 전 품목 20% 할인 11월 7일~20일", "농수산물 20% 할인 11월 7일~20일",
                      "농축수산식품 20% 할인 11월 7일~20일"):
            with self.subTest(title=title):
                self.assertEqual(gd.link([event(title, end="2026-11-20", dated=False)], real_basket(), TODAY), [])
        self.assertEqual(ids(gd.link([event("수산물 20% 할인 11월 7일~20일", end="2026-11-20", dated=False)],
                                     real_basket(), TODAY)), ["mackerel", "squid"])

    def test_2_names_need_a_left_boundary_and_pork_clause_is_not_beef(self):
        cases = {"돼지 등심 30% 할인": {"hanwoo_sirloin", "us_short_rib"},
                 "양배추·단호박 20% 할인": {"napa_cabbage", "zucchini"},
                 "돼지갈비살 20% 할인": {"us_short_rib"},
                 "한돈 등심 20% 할인": {"hanwoo_sirloin"},
                 "한돈 갈비살 20% 할인": {"us_short_rib"}}
        for title, wrong in cases.items():
            with self.subTest(title=title):
                found = set(ids(gd.link([event(title)], real_basket(), TODAY)))
                self.assertFalse(found & wrong, found)
        # Still linked: own words with a boundary, and a clause naming beef next to pork.
        self.assertEqual(ids(gd.link([event("배추 20% 할인")], real_basket(), TODAY)), ["napa_cabbage"])
        self.assertIn("hanwoo_sirloin", ids(gd.link([event("한우·한돈 등심 20% 할인")], real_basket(), TODAY)))

    def test_3_bad_title_is_skipped_not_the_whole_bundle(self):
        items = [event("<대한민국 수산대전> 고등어 20% 할인", url="https://www.mof.go.kr/bad"),
                 event("오징어 20% 할인", url="https://www.mof.go.kr/good")]
        links = gd.link(items, real_basket(), TODAY)
        self.assertEqual([(x["basket_id"], x["url"]) for x in links], [("squid", "https://www.mof.go.kr/good")])
        self.assertEqual(gd.link([event("고등어 할인 " + "가" * 200)], real_basket(), TODAY), [])
        self.assertEqual(gd.link([event("고등어\x07 할인")], real_basket(), TODAY), [])
        good = dict(basket_id="squid", title="오징어 20% 할인", discount=None, stores=None, start="2026-11-07",
                    end="2026-11-27", url="https://www.mof.go.kr/good")
        bundle = dict(schema_version=1, source="grocery_discounts", generated_at="2026-11-11T09:00:00+09:00",
                      links=[dict(good, basket_id="mackerel", title="<대한민국 수산대전> 고등어"), good,
                             dict(good, url="http://www.mof.go.kr/x"), dict(good, extra=1)])
        self.assertEqual(gd.sanitize(bundle, NOW)["links"], [good])
        self.assertIsNone(gd.sanitize(dict(bundle, links=bundle["links"][:1]), NOW))

    def test_4_varying_period_check_uses_the_items_own_end(self):
        item = event("가을 수산물 할인", "고등어 11월 7일~20일 30% 할인", "품목별 기간이 다르며 확인 필요.",
                     end="2026-11-20", display_until="2026-11-15T23:59:00+09:00")
        links = gd.link([item], real_basket(), TODAY)
        self.assertEqual([(x["basket_id"], x["end"]) for x in links], [("mackerel", "2026-11-15")])

    def test_6_dotted_full_dates_and_decimals(self):
        links = gd.link([event("2026.11.07~2026.11.20 고등어 20% 할인", end="2026-11-20", dated=False)],
                        real_basket(), TODAY)
        self.assertEqual([(x["basket_id"], x["discount"]) for x in links], [("mackerel", "20% 할인")])
        self.assertEqual(ids(gd.link([event("2026. 11. 7.~2026. 11. 20. 고등어 할인", end="2026-11-20", dated=False)],
                                     real_basket(), TODAY)), ["mackerel"])
        self.assertEqual(gd._days("2026.11.07~2026.11.20"), {(11, 7), (11, 20)})
        for text in ("고등어 1.5kg", "고등어 2.5배", "11.7% 할인", "1.5 kg", "2.5L", "1.2만원"):
            with self.subTest(text=text):
                self.assertEqual(gd._days(text), set())
        self.assertEqual(ids(gd.link([event("고등어 할인", "고등어 1.5kg 20% 할인")], real_basket(), TODAY)), ["mackerel"])
        self.assertEqual(gd._days("11.7.~11.27."), {(11, 7), (11, 27)})

    def test_5_8_recompute_uses_current_item_text(self):
        baselines = dict(schema_version=1, source="grocery_baselines", fetched_at="2026-11-10T08:00:00+09:00",
                         items=[dict(b, baseline=None) for b in real_basket()])
        item = event("고등어 20% 할인", end="2026-11-20")
        data = dict(items=[item], grocery_baselines=baselines, grocery_discounts=dict(
            schema_version=1, source="grocery_discounts", generated_at="2026-11-10T09:00:00+09:00",
            links=[dict(basket_id="mackerel", title=item["title"], discount="20% 할인", stores=None,
                        start="2026-11-07", end="2026-11-20", url=item["url"])]))
        moved = dict(item, valid_until="2026-11-12", conditions="행사 기간 11월 7일~11월 12일.")
        bundle = gd.recompute(dict(data, items=[moved]), NOW)
        self.assertEqual([(x["basket_id"], x["end"]) for x in bundle["links"]], [("mackerel", "2026-11-12")])
        self.assertIsNone(gd.recompute(dict(data, items=[dict(item, labels={"region": "서울"})]), NOW))
        self.assertIsNone(gd.recompute(dict(data, grocery_baselines=None), NOW))
        self.assertIsNone(gd.recompute({k: v for k, v in data.items() if k != "grocery_baselines"}, NOW))


if __name__ == "__main__":
    unittest.main()
