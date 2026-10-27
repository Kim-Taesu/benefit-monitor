import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from benefit_monitor.discovery import FeedLinks, discover, run
from benefit_monitor.store import save
from benefit_monitor.cli import run as pipeline
from test_pipeline import SOURCE, NOW, ROOT

class DiscoveryTests(unittest.TestCase):
    def test_only_official_advertised_feeds(self):
        parser=FeedLinks("https://official.example/news/", SOURCE["domains"])
        parser.feed("""<link rel="alternate" type="application/rss+xml" href="/rss">
        <link rel="alternate" type="application/atom+xml" href="https://evil.example/feed">
        <link rel="stylesheet" type="application/rss+xml" href="/wrong">
        <link rel="alternate" type="application/rss+xml" href="/rss">""")
        self.assertEqual(parser.links,["https://official.example/rss"])

    def test_proxy_failure_is_recorded(self):
        with patch("benefit_monitor.discovery.fetch",side_effect=URLError("Tunnel connection failed: 403 Forbidden")):
            result=discover(SOURCE)
        self.assertEqual(result["status"],"browser_review_required")
        self.assertEqual(result["checks"][0]["error_type"],"URLError")

    def test_disallowed_page_not_fetched(self):
        with patch("benefit_monitor.discovery.fetch",return_value=b"User-agent: *\nDisallow: /") as fetch:
            self.assertEqual(discover(SOURCE)["status"],"browser_review_required")
            self.assertEqual(fetch.call_count,1)

    def test_discovery_validates_feed(self):
        page=b'<link rel="alternate" type="application/rss+xml" href="/rss">'
        with patch("benefit_monitor.discovery.fetch",side_effect=[b"User-agent: *\nAllow: /",page]), patch("benefit_monitor.discovery.collect",return_value=[{}]):
            result=discover(SOURCE)
        self.assertEqual(result["verified_feeds"],[{"url":"https://official.example/rss","candidates_count":1}])

    def test_no_feed_is_not_success(self):
        with patch("benefit_monitor.discovery.fetch",side_effect=[b"User-agent: *\nAllow: /",b"<html/>"]):
            self.assertEqual(discover(SOURCE)["status"],"browser_review_required")

    def test_unknown_source_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            save(Path(d)/"sources.yaml",dict(sources=[SOURCE]))
            with self.assertRaises(ValueError):
                run(d,["typo"])

    def test_unverified_feed_candidates_keep_report_incomplete(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as d:
            save(Path(d)/"sources.yaml",dict(sources=[dict(SOURCE,feed_url="https://official.example/rss")]))
            candidate=dict(source="test",url="https://official.example/offer",title="Candidate",summary="Not verified")
            with patch("benefit_monitor.cli.collect",return_value=[candidate]):
                result=pipeline(d,online=True,now=NOW)
            self.assertFalse(result["complete"])
            self.assertEqual(len(result["needs_recheck"]),1)
