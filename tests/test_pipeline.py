import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from benefit_monitor.models import Benefit
from benefit_monitor.validation import validate, official
from benefit_monitor.diff import classify
from benefit_monitor.store import save, load
from benefit_monitor.collectors.rss import parse, fetch, Redirect, collect
from benefit_monitor.cli import run

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.fromisoformat("2026-10-26T08:00:00+09:00")
SOURCE = dict(id="test", domains=["official.example"], routes=["https://official.example/"], feed_url=None)
SOURCES = {"test": SOURCE}

def benefit(**kw):
    d = dict(source="test", url="https://official.example/benefit/1", title="테스트 혜택",
             summary="테스트 전용, 실제 혜택 아님", valid_until="2026-11-30",
             verified_at="2026-10-26T07:00:00+09:00", needs_recheck=False, evidence="테스트 문구")
    d.update(kw)
    return Benefit(**d)

class PipelineTests(unittest.TestCase):
    def test_validation_official_only(self):
        for url in ["http://official.example/x", "https://official.example.evil/x", "https://user@official.example/x", "https://official.example:444/x"]:
            with self.assertRaises(ValueError):
                validate(benefit(url=url).data(), SOURCES, NOW)

    def test_validation_evidence_time_interval(self):
        for kw in [dict(evidence=""), dict(verified_at=None), dict(verified_at="2026-10-27T08:00:00+09:00"),
                   dict(verified_at="2026-10-26T07:00:00"), dict(valid_from="2026-12-01"), dict(needs_recheck="false")]:
            with self.assertRaises(ValueError):
                validate(benefit(**kw).data(), SOURCES, NOW)

    def test_new(self):
        i=benefit()
        self.assertEqual(len(classify({}, {i.id:i}, NOW)["new"]), 1)

    def test_changed(self):
        i=benefit()
        changed=replace(i, conditions="추가 조건")
        self.assertEqual(len(classify({i.id:i}, {i.id:changed}, NOW)["changed"]), 1)

    def test_timestamp_only_is_not_change(self):
        i=benefit()
        newer=replace(i, verified_at=NOW.isoformat())
        self.assertEqual(len(classify({i.id:i}, {i.id:newer}, NOW)["still_valid"]), 1)

    def test_deadline_today_and_expired(self):
        today=benefit(valid_until="2026-10-26")
        yesterday=benefit(url="https://official.example/old", valid_until="2026-10-25")
        result=classify({}, {i.id:i for i in [today,yesterday]}, NOW)
        self.assertEqual(len(result["expiring"]),1)
        self.assertEqual(len(result["expired"]),1)

    def test_stale_unknown_and_flagged(self):
        for kw in [dict(verified_at="2026-10-18T08:00:00+09:00"), dict(valid_until=None), dict(needs_recheck=True)]:
            i=benefit(**kw)
            self.assertEqual(len(classify({}, {i.id:i}, NOW)["needs_recheck"]),1)

    def test_upcoming(self):
        i=benefit(valid_from="2026-11-01")
        self.assertEqual(len(classify({}, {i.id:i}, NOW)["upcoming"]),1)

    def test_rss_candidates_not_verified(self):
        items=parse(b"<rss><channel><item><title>Offer</title><link>https://official.example/1</link></item><item><title>Bad</title><link>https://evil.example/</link></item></channel></rss>", SOURCE)
        self.assertEqual(len(items),1)
        self.assertTrue(items[0]["needs_recheck"])

    def test_atom(self):
        body=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Offer</title><link href="https://official.example/1"/></entry></feed>'
        self.assertEqual(len(parse(body,SOURCE)),1)

    def test_empty_feed_is_failure(self):
        with self.assertRaises(ValueError):
            parse(b"<rss/>",SOURCE)

    def test_http_retry(self):
        for status, count in [(502,2),(403,1)]:
            with patch("benefit_monitor.collectors.rss.urllib.request.build_opener") as opener, patch("benefit_monitor.collectors.rss.time.sleep"):
                opener.return_value.open.side_effect=HTTPError("https://official.example/",status,"error",None,None)
                with self.assertRaises(HTTPError):
                    fetch("https://official.example/",SOURCE["domains"])
                self.assertEqual(opener.return_value.open.call_count,count)

    def test_robots_denied(self):
        with patch("benefit_monitor.collectors.rss.fetch",return_value=b"User-agent: *\nDisallow: /"):
            with self.assertRaises(ValueError):
                collect(dict(SOURCE,feed_url="https://official.example/feed"))

    def test_redirect_host(self):
        with self.assertRaises(ValueError):
            Redirect(SOURCE["domains"]).redirect_request(None,None,302,"",{},"https://evil.example/")

    def test_end_to_end_repeat_and_preserve_cache(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            p=Path(directory)
            save(p/"sources.yaml",dict(sources=[SOURCE]))
            save(p/"import.json",[benefit().data()])
            first=run(p,p/"import.json",now=NOW)
            self.assertEqual(len(first["new"]),1)
            second=run(p,now=NOW)
            self.assertEqual(len(second["still_valid"]),1)
            self.assertFalse(second["complete"])
            self.assertEqual(len(load(p/"cache/verified_items.json",[])),1)
            self.assertEqual(len(load(p/"report.json",{})["browser_handoffs"]),1)

    def test_invalid_import_keeps_cache(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            p=Path(directory)
            save(p/"sources.yaml",dict(sources=[SOURCE]))
            save(p/"import.json",[benefit().data()])
            run(p,p/"import.json",now=NOW)
            before=(p/"cache/verified_items.json").read_text()
            save(p/"import.json",[benefit(url="https://evil.example/").data()])
            with self.assertRaises(ValueError):
                run(p,p/"import.json",now=NOW)
            self.assertEqual((p/"cache/verified_items.json").read_text(),before)

    def test_discovery_cannot_erase_verified_facts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            p=Path(directory)
            save(p/"sources.yaml",dict(sources=[SOURCE]))
            save(p/"import.json",[benefit().data()])
            run(p,p/"import.json",now=NOW)
            save(p/"import.json",[dict(source="test",url=benefit().url,title="새 제목",summary="후보")])
            r=run(p,p/"import.json",now=NOW)
            self.assertEqual(len(r["needs_recheck"]),1)
            self.assertEqual(r["needs_recheck"][0]["evidence"],"테스트 문구")

if __name__ == "__main__":
    unittest.main()
