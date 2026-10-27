import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from benefit_monitor import publish
from benefit_monitor.store import save
from test_pipeline import benefit, SOURCE, NOW


class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.item = benefit(fee_status="paid", conditions="입장료 5,000원").data()
        save(self.root / "sources.yaml", dict(sources=[SOURCE], max_age_days=7))
        self.report = dict(verified_at=NOW.isoformat(), complete=False,
                           new=[self.item], needs_recheck=[],
                           collection=dict(online=True, successful_sources=["test"], successful_districts=0))
        save(self.root / "report.json", self.report)
        self.release(self.item)

    def release(self, *items):
        save(self.root / "public/verified.json",
             [dict(i, public_release=True) for i in items])

    def run_export(self, now=NOW):
        return publish.run(self.root, now=now)

    def test_release_keeps_fees_and_times_but_drops_private_fields(self):
        self.item.update(evidence="internal verification evidence", review_notes="private note")
        self.release(self.item)
        self.report.update(new=[self.item], profile={"birthdate": "1900-01-01"})
        save(self.root / "report.json", self.report)
        result = self.run_export()
        self.assertEqual(result["items"][0]["fee_status"], "paid")
        self.assertEqual(result["items"][0]["conditions"], "입장료 5,000원")
        self.assertEqual(result["source_report_at"], NOW.isoformat())
        self.assertEqual(result["items"][0]["verified_at"], self.item["verified_at"])
        output = (self.root / "delivery/public/briefing.json").read_text()
        for secret in ("private note", "internal verification evidence", "1900-01-01", "profile"):
            self.assertNotIn(secret, output)
        self.assertEqual({p.name for p in (self.root / "delivery/public").iterdir()},
                         {"index.html", "briefing.json", "briefing.md"})

    def test_no_release_does_not_publish_internal_items_or_claim_no_benefits(self):
        self.release()
        result = self.run_export()
        self.assertEqual(result["items"], [])
        self.assertEqual(result["status"], "awaiting_verification")
        self.assertIn("혜택이 없다는 뜻은 아닙니다", result["message"])

    def test_unapproved_release_fails_closed(self):
        save(self.root / "public/verified.json", [self.item])
        with self.assertRaises(ValueError):
            self.run_export()

    def test_release_terms_must_match_verified_report(self):
        self.release(dict(self.item, conditions="무료"))
        self.assertEqual(self.run_export()["items"], [])

    def test_blocked_and_unverified_and_expired_are_withheld(self):
        for updates in (dict(needs_recheck=True), dict(valid_until="2026-10-20"),
                        dict(excluded_reason="ended"), dict(evidence="")):
            item = dict(self.item, **updates)
            self.release(self.item)
            save(self.root / "report.json", dict(self.report, new=[item]))
            self.assertEqual(self.run_export()["items"], [])

    def test_prior_date_or_old_report_is_rejected(self):
        for now in (NOW + timedelta(days=1), NOW + timedelta(hours=3)):
            with self.assertRaises(ValueError):
                self.run_export(now)

    def test_missing_report_is_rejected(self):
        (self.root / "report.json").unlink()
        with self.assertRaises(ValueError):
            self.run_export()

    def test_complete_collection_failure_is_not_an_empty_success(self):
        save(self.root / "report.json", dict(self.report, district_coverage=[
            {"status": "error"}], browser_handoffs=[{"source": "seoul"}],
            verification_limits=[{"source": "seoul"}],
            collection=dict(online=True, successful_sources=[], successful_districts=0)))
        result = self.run_export()
        self.assertEqual(result["status"], "collection_failed")
        self.assertEqual(result["items"], [])

    def test_public_sensitive_strings_and_token_urls_rejected(self):
        for updates in (dict(conditions="생년월일 1900-01-01"),
                        dict(summary="contact secret@example.com"),
                        dict(url="https://official.example/a?token=secret")):
            self.release(dict(self.item, **updates))
            with self.assertRaises(ValueError):
                self.run_export()

    def test_html_escapes_text_and_link_attributes(self):
        item = dict(self.item, summary='<img src=x onerror="alert(1)">')
        self.release(item)
        save(self.root / "report.json", dict(self.report, new=[item]))
        self.run_export()
        page = (self.root / "delivery/public/index.html").read_text()
        self.assertNotIn('<img src=x', page)
        self.assertIn('&lt;img', page)
        self.assertIn("요금: 유료", page)

    def test_failure_page_replaces_previous_recommendations_without_details(self):
        self.run_export()
        publish.run(self.root, now=NOW, failure=True)
        data = json.loads((self.root / "delivery/public/briefing.json").read_text())
        self.assertEqual(data["status"], "collection_failed")
        self.assertIsNone(data["source_report_at"])
        self.assertEqual(data["items"], [])
        self.assertNotIn(self.item["summary"], (self.root / "delivery/public/index.html").read_text())

    def test_prepare_import_removes_release_marker_and_rejects_profile_fields(self):
        path = publish.prepare_import(self.root, NOW)
        self.assertEqual(json.loads(path.read_text()), [self.item])
        self.release(dict(self.item, profile="private"))
        with self.assertRaises((ValueError, TypeError)):
            publish.prepare_import(self.root, NOW)

    def test_offline_report_cannot_be_published_as_a_collection_success(self):
        save(self.root / "report.json", dict(self.report, collection=dict(online=False)))
        self.assertEqual(self.run_export()["status"], "collection_failed")

    def test_online_pipeline_records_actual_source_success(self):
        from unittest.mock import patch
        from benefit_monitor.cli import run
        source = dict(SOURCE, html_url="https://official.example/")
        save(self.root / "sources.yaml", dict(sources=[source], max_age_days=7))
        with patch("benefit_monitor.cli.collect_html", return_value=[]):
            report = run(self.root, online=True, now=NOW)
        self.assertEqual(report["collection"], dict(online=True, successful_sources=["test"], successful_districts=0))
        self.assertEqual(self.run_export()["status"], "awaiting_verification")

    def test_cli_returns_failure_for_offline_collection_status(self):
        import subprocess
        import sys
        from datetime import datetime
        from benefit_monitor.briefing import SEOUL
        now = datetime.now(SEOUL)
        item = dict(self.item, verified_at=now.isoformat(), valid_until=(now + timedelta(days=10)).date().isoformat())
        self.release(item)
        save(self.root / "report.json", dict(self.report, verified_at=now.isoformat(), new=[item], collection=dict(online=False)))
        result = subprocess.run([sys.executable, "-m", "benefit_monitor.publish", "--root", str(self.root)],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        data = json.loads((self.root / "delivery/public/briefing.json").read_text())
        self.assertEqual(data["status"], "collection_failed")

    def test_naive_generation_time_is_rejected(self):
        with self.assertRaises(ValueError):
            self.run_export(NOW.replace(tzinfo=None))

    def test_markdown_keeps_upcoming_start_and_exact_deadline(self):
        item = dict(self.item, valid_from="2026-10-28", valid_until="2026-10-29",
                    deadline_at="2026-10-29T12:00:00+09:00")
        self.release(item)
        save(self.root / "report.json", dict(self.report, new=[item]))
        self.run_export()
        text = (self.root / "delivery/public/briefing.md").read_text()
        for expected in ("시작 예정", "2026-10-28", "2026-10-29T12:00:00+09:00"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
