import json
import unittest
from pathlib import Path
from unittest.mock import patch
from benefit_monitor.collectors.html import ArticleLinks, collect

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/mof_press"
LIST_URL = "https://www.mof.go.kr/doc/ko/selectDocList.do?menuSeq=971&bbsSeq=10"
DETAIL = "https://www.mof.go.kr/doc/ko/selectDoc.do?docSeq=%s&menuSeq=971&bbsSeq=10"
WORDS = ["할인", "세일", "수산대전", "농할", "할인지원", "소비촉진", "반값", "특별판매"]
TARGETS = ["농축산물", "농산물", "축산물", "한우", "한돈", "수산물", "수산식품", "김장", "성수품", "수산대전", "농할"]


def mof_source():
    definition = json.loads((ROOT / "sources/mof_press.json").read_text(encoding="utf-8"))
    return dict(id=definition["id"], **definition["collect"])


def parse(name, **kwargs):
    parser = ArticleLinks(LIST_URL, ["www.mof.go.kr"], "/doc/ko/selectDoc.do", WORDS, **kwargs)
    parser.feed((FIXTURES / name).read_text(encoding="utf-8"))
    return parser


class MofPressTests(unittest.TestCase):
    def test_mof_fn_selectdoc_link_becomes_detail_url(self):
        parser = parse("list.html", require_any=None)
        parser_all = ArticleLinks(LIST_URL, ["www.mof.go.kr"], "/doc/ko/selectDoc.do", ["*"])
        parser_all.feed((FIXTURES / "list.html").read_text(encoding="utf-8"))
        self.assertIn(DETAIL % "69292", parser_all.items)
        self.assertEqual(parser_all.items[DETAIL % "69292"], "어촌뉴딜 3.0 신규 대상지 40개소 선정...  사업 구조도 개편한다".replace("  ", " "))
        self.assertEqual(parser.items, {})

    def test_mof_keeps_only_food_discount_titles(self):
        parser = parse("list_with_event.html", require_any=TARGETS)
        self.assertEqual(parser.items, {DETAIL % "69292": "국산 수산물 할인 행사 안내"})
        real = parse("list.html", require_any=TARGETS)
        self.assertEqual(real.items, {})

    def test_mof_discount_title_without_food_target_is_dropped(self):
        parser = ArticleLinks(LIST_URL, ["www.mof.go.kr"], "/doc/ko/selectDoc.do", WORDS, require_any=TARGETS)
        parser.feed("<a href=\"#none\" onclick=\"fn_selectDoc('1')\" title=\"[게시글 바로가기] 선박 할인 제도 안내\">x</a>")
        self.assertEqual(parser.items, {})

    def test_food_event_names_alone_become_candidates(self):
        parser = ArticleLinks(LIST_URL, ["www.mof.go.kr"], "/doc/ko/selectDoc.do", WORDS, require_any=mof_source()["require_any"])
        parser.feed("<a href=\"#none\" onclick=\"fn_selectDoc('1')\" title=\"[게시글 바로가기] 2026 대한민국 수산대전 개막\">x</a>"
                    "<a href=\"#none\" onclick=\"fn_selectDoc('2')\" title=\"[게시글 바로가기] 농할상품권 판매\">x</a>")
        self.assertEqual(list(parser.items.values()), ["2026 대한민국 수산대전 개막", "농할상품권 판매"])

    def test_require_any_absent_keeps_old_behavior(self):
        parser = ArticleLinks("https://official.example/", ["official.example"], r"/archives/\d+", ["할인"])
        parser.feed('<a href="/archives/1">정책 할인 안내</a><a href="/archives/2">설명</a>')
        self.assertEqual(parser.items, {"https://official.example/archives/1": "정책 할인 안내"})
        # fn_selectDoc translation is limited to the MOF list page.
        other = ArticleLinks("https://official.example/", ["official.example"], r"/doc/ko/selectDoc.do", ["*"])
        other.feed("<a href=\"#none\" onclick=\"fn_selectDoc('5')\">제목</a>")
        self.assertEqual(other.items, {})

    def test_mof_press_source_order_before_groceries(self):
        order = json.loads((ROOT / "sources/_config.json").read_text(encoding="utf-8"))["source_order"]
        self.assertEqual(order.index("mof_press") + 1, order.index("groceries"))

    def test_mof_source_definition(self):
        source = mof_source()
        self.assertEqual(source["html_url"], LIST_URL)
        self.assertEqual(source["keywords"], WORDS)
        self.assertEqual(source["require_any"], TARGETS)

    def test_empty_day_is_success_but_broken_page_fails(self):
        source = mof_source()
        robots = b"User-agent: *\nAllow: /"
        page = (FIXTURES / "list.html").read_bytes()
        with patch("benefit_monitor.collectors.html.fetch", side_effect=[robots, page]):
            self.assertEqual(collect(source), [])
        with patch("benefit_monitor.collectors.html.fetch", side_effect=[robots, b"<html/>"]):
            with self.assertRaises(ValueError):
                collect(source)
        event = (FIXTURES / "list_with_event.html").read_bytes()
        with patch("benefit_monitor.collectors.html.fetch", side_effect=[robots, event]):
            result = collect(source)
        self.assertEqual([i["url"] for i in result], [DETAIL % "69292"])

    def test_allow_empty_absent_still_fails_without_match(self):
        source = dict(mof_source())
        source.pop("allow_empty", None)
        with patch("benefit_monitor.collectors.html.fetch", side_effect=[b"User-agent: *\nAllow: /", (FIXTURES / "list.html").read_bytes()]):
            with self.assertRaises(ValueError):
                collect(source)
