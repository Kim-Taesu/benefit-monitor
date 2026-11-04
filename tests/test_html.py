import unittest
from pathlib import Path
from unittest.mock import patch
from benefit_monitor.collectors.html import ArticleLinks, collect

SOURCE=dict(id="seoul",html_url="https://official.example/",domains=["official.example"],
            article_path_pattern=r"/archives/\d+",keywords=["할인","접수"])

class HtmlTests(unittest.TestCase):
    def test_filters_duplicates_navigation_external_and_keywords(self):
        parser=ArticleLinks(SOURCE["html_url"],SOURCE["domains"],SOURCE["article_path_pattern"],SOURCE["keywords"])
        parser.feed('<a href="/archives/12">할인 <b>행사</b></a><a href="/archives/12">할인 행사</a><a href="/archives/13">정책 설명</a><a href="https://evil.example/archives/14">할인</a><a href="/search">접수</a>')
        self.assertEqual(parser.items,{"https://official.example/archives/12":"할인 행사"})

    def test_collect_candidate_only(self):
        with patch("benefit_monitor.collectors.html.fetch",side_effect=[b"User-agent: *\nAllow: /",'<a href="/archives/12">할인 행사</a>'.encode()]):
            result=collect(SOURCE)
        self.assertTrue(result[0]["needs_recheck"])
        self.assertNotIn("verified_at",result[0])

    def test_robots_denies_without_page_fetch(self):
        with patch("benefit_monitor.collectors.html.fetch",return_value=b"User-agent: *\nDisallow: /") as fetch:
            with self.assertRaises(ValueError):
                collect(SOURCE)
            self.assertEqual(fetch.call_count,1)

    def test_no_matching_articles_fails(self):
        with patch("benefit_monitor.collectors.html.fetch",side_effect=[b"User-agent: *\nAllow: /",b"<html/>"]):
            with self.assertRaises(ValueError):
                collect(SOURCE)

    def test_ranking_prefix_is_not_title_change(self):
        p=ArticleLinks(SOURCE["html_url"],SOURCE["domains"],SOURCE["article_path_pattern"],SOURCE["keywords"])
        p.feed('<a href="/archives/12">02 할인 행사</a>')
        self.assertEqual(p.items["https://official.example/archives/12"],"할인 행사")

    def test_online_and_verified_import_merge(self):
        import tempfile
        from benefit_monitor.cli import run
        from benefit_monitor.store import save
        from test_pipeline import ROOT, NOW, benefit, SOURCE as TEST_SOURCE
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            source=dict(TEST_SOURCE,html_url="https://official.example/")
            save(root/"sources.yaml",dict(sources=[source]))
            item=benefit()
            save(root/"input.json",[item.data()])
            candidate=dict(source=item.source,url=item.url,title=item.title,summary="Discovery")
            with patch("benefit_monitor.cli.collect_html",return_value=[candidate]):
                report=run(root,root/"input.json",online=True,now=NOW)
            self.assertEqual(len(report["new"]),1)
            self.assertFalse(report["needs_recheck"])
