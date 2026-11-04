import unittest
from unittest.mock import patch
from benefit_monitor.robots import allowed
from benefit_monitor.collectors.rss import collect

URL="https://official.example"
class RobotsTests(unittest.TestCase):
    def test_longer_allow_survives_global_disallow(self):
        text="User-agent: *\nDisallow: /\nAllow: /plus/web/service/notice"
        self.assertTrue(allowed(text,URL+"/plus/web/service/notice/12"))
        self.assertFalse(allowed(text,URL+"/plus/web/login"))

    def test_longer_disallow_and_allow_tie(self):
        self.assertFalse(allowed("User-agent: *\nAllow: /\nDisallow: /private",URL+"/private/a"))
        self.assertTrue(allowed("User-agent: *\nDisallow: /same\nAllow: /same",URL+"/same"))

    def test_specific_agent_group_not_google_exception(self):
        text="User-agent: *\nDisallow: /\nUser-agent: Googlebot\nAllow: /"
        self.assertFalse(allowed(text,URL))
        self.assertTrue(allowed(text,URL,agent="Googlebot/1.0"))

    def test_same_agent_groups_are_combined(self):
        text="User-agent: *\nDisallow: /\nUser-agent: *\nAllow: /public"
        self.assertTrue(allowed(text,URL+"/public"))

    def test_comments_whitespace_empty_rules(self):
        text="User-Agent : *\nDisallow : /private # comment\nAllow: /public\nDisallow:"
        self.assertTrue(allowed(text,URL+"/public"))
        self.assertFalse(allowed(text,URL+"/private"))

    def test_wildcard_end_anchor_and_query(self):
        text="User-agent: *\nDisallow: /*.pdf$\nDisallow: /*?secret="
        self.assertFalse(allowed(text,URL+"/file.pdf"))
        self.assertTrue(allowed(text,URL+"/file.pdf?download=1"))
        self.assertFalse(allowed(text,URL+"/page?secret=yes"))

    def test_percent_encoded_unreserved_matches(self):
        self.assertFalse(allowed("User-agent: *\nDisallow: /private",URL+"/%70rivate"))
        self.assertTrue(allowed("User-agent: *\nDisallow: /a/b",URL+"/a%2Fb"))

    def test_html_robots_fails_closed(self):
        with self.assertRaises(ValueError):
            allowed("<html>Access denied</html>",URL)

    def test_collect_allowed_feed_and_keeps_other_paths_denied(self):
        source=dict(id="test",feed_url=URL+"/public/feed",domains=["official.example"])
        robots=b"User-agent: *\nDisallow: /\nAllow: /public"
        body=b"<rss><item><title>Offer</title><link>https://official.example/public/1</link></item></rss>"
        with patch("benefit_monitor.collectors.rss.fetch",side_effect=[robots,body]):
            self.assertEqual(len(collect(source)),1)
