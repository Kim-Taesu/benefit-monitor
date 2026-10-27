import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from dataclasses import replace
from datetime import timedelta
from benefit_monitor import cost_policy
from benefit_monitor.collectors.districts import parse, collect
from benefit_monitor.collectors.html import ArticleLinks
from benefit_monitor.collectors.rss import fetch, Redirect
from benefit_monitor.store import save
from test_pipeline import ROOT, NOW

class CostDistrictTests(unittest.TestCase):
    def tearDown(self):
        cost_policy.reset()
    def test_exactly_25_unique_districts(self):
        districts=json.loads((ROOT/"districts.json").read_text())["districts"]
        self.assertEqual(len({d["name"] for d in districts}),25)
        self.assertEqual(len({d["code"] for d in districts}),25)

    def test_budget_stops_before_network(self):
        cost_policy.reset(1)
        cost_policy.budget.consume()
        with patch("benefit_monitor.collectors.rss.urllib.request.build_opener") as opener:
            with self.assertRaises(RuntimeError):
                fetch("https://official.example/",["official.example"])
            opener.return_value.open.assert_not_called()

    def test_budget_rejects_unbounded_values(self):
        for value in [0,101,-1,True]:
            with self.assertRaises(ValueError):
                cost_policy.reset(value)

    def test_paid_mode_rejected(self):
        with self.assertRaises(ValueError):
            cost_policy.require_free(dict(cost_policy=dict(mode="paid",paid_services_allowed=True)))

    def test_district_filter_and_no_match_are_distinct(self):
        body='<p class="type corres_box"><strong>종로구</strong></p><a href="/archives/12"><h2>무료 전시</h2></a>'
        result=parse(body,"https://mediahub.seoul.go.kr/news/", "종로구",["무료"])
        self.assertEqual(result[0]["districts"],["종로구"])
        self.assertEqual(parse(body,"https://mediahub.seoul.go.kr/news/","종로구",["지원금"]),[])
        with self.assertRaises(ValueError):
            parse(body,"https://mediahub.seoul.go.kr/news/","강남구",["무료"])
        with self.assertRaises(ValueError):
            parse("<html/>","https://mediahub.seoul.go.kr/news/","종로구",["무료"])

    def test_cached_district_does_not_fetch(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            save(root/"districts.json",dict(districts=[dict(code="110",name="종로구")]))
            save(root/"cache/district_candidates.json",{"110":dict(code="110",district="종로구",checked_at=NOW.isoformat(),status="checked",items=[])})
            with patch("benefit_monitor.collectors.districts.fetch") as fetcher:
                items,coverage=collect(root,dict(keywords=["무료"]),NOW+timedelta(hours=1))
            fetcher.assert_not_called()
            self.assertEqual(coverage[0]["mode"],"cached")

    def test_summary_is_not_part_of_title(self):
        p=ArticleLinks("https://mediahub.seoul.go.kr/",["mediahub.seoul.go.kr"],r"/archives/\d+",["혜택"])
        p.feed('<a href="/archives/12"><p class="tit">혜택 안내</p><p class="summary">매일 바뀌는 조회수 설명</p></a>')
        self.assertEqual(p.items,{"https://mediahub.seoul.go.kr/archives/12":"혜택 안내"})

    def test_shared_robots_failure_is_not_repeated_for_each_district(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            save(root/"districts.json",dict(districts=[dict(code="110",name="종로구"),dict(code="230",name="강남구")]))
            with patch("benefit_monitor.collectors.districts.fetch", side_effect=TimeoutError("robots timeout")) as fetcher:
                items,coverage=collect(root,dict(keywords=["무료"]),NOW)
            self.assertEqual(items,[])
            self.assertEqual([c["status"] for c in coverage],["failed","failed"])
            fetcher.assert_called_once_with("https://mediahub.seoul.go.kr/robots.txt",["mediahub.seoul.go.kr"])

