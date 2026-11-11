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


def event(title, summary="", conditions="", start="2026-11-07", end="2026-11-27", kind="fixed", url="https://www.mof.go.kr/a", **extra):
    return dict(dict(title=title, summary=summary, conditions=conditions, valid_from=start, valid_until=end,
                     validity_kind=kind, url=url, source="mof_press", review={}), **extra)


def ids(links):
    return [x["basket_id"] for x in links]


class LinkTests(unittest.TestCase):
    def test_link_fish_event_to_mackerel_and_squid_only(self):
        links = gd.link([event("한국 수산식품 홍보주간 개최", "최대 50% 할인", "대형마트·온라인몰에서 진행")], basket(), TODAY)
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

    def test_substring_false_positives(self):
        self.assertEqual(gd.link([event("닭갈비 축제 할인")], basket(), TODAY), [])
        self.assertEqual(gd.link([event("한우리 마을 체험 할인")], basket(), TODAY), [])
        self.assertEqual(gd.link([event("미국산 오렌지 할인")], basket(), TODAY), [])
        self.assertEqual(ids(gd.link([event("닭고기 할인")], basket(), TODAY)), ["chicken"])
        self.assertEqual(ids(gd.link([event("계란 할인")], basket(), TODAY)), ["egg_tray"])
        self.assertEqual(ids(gd.link([event("닭·계란 할인")], basket(), TODAY)), ["chicken", "egg_tray"])

    def test_percent_preferred_over_won(self):
        links = gd.link([event("고등어 할인", "1인 최대 2만원 한도, 최대 50% 할인")], basket(), TODAY)
        self.assertEqual(links[0]["discount"], "최대 50%")
        links = gd.link([event("고등어 할인", "1인 최대 2만원 한도")], basket(), TODAY)
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


if __name__ == "__main__":
    unittest.main()
