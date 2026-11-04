import unittest
import tempfile
from pathlib import Path
from datetime import timedelta
from dataclasses import replace
from benefit_monitor.validation import validate
from benefit_monitor.diff import classify
from benefit_monitor.cli import run
from benefit_monitor.store import save
from test_pipeline import benefit, SOURCES, SOURCE, NOW, ROOT

class ReviewStatesTests(unittest.TestCase):
    def test_ongoing_verified_without_invented_end_date(self):
        item=benefit(valid_until=None,validity_kind="ongoing")
        validate(item.data(),SOURCES,NOW)
        self.assertEqual(len(classify({}, {item.id:item},NOW)["new"]),1)
        self.assertIsNone(item.valid_until)

    def test_ongoing_stales_and_does_not_bypass_pending(self):
        for item in [benefit(valid_until=None,validity_kind="ongoing",needs_recheck=True),
                     benefit(valid_until=None,validity_kind="ongoing",verified_at="2026-10-01T08:00:00+09:00")]:
            self.assertEqual(len(classify({}, {item.id:item},NOW)["needs_recheck"]),1)

    def test_ongoing_cannot_hide_fixed_end(self):
        with self.assertRaises(ValueError):
            validate(benefit(validity_kind="ongoing").data(),SOURCES,NOW)

    def test_deadline_expires_during_day(self):
        item=benefit(valid_until="2026-10-26",deadline_at="2026-10-26T17:00:00+09:00")
        validate(item.data(),SOURCES,NOW)
        r=classify({}, {item.id:item},NOW.replace(hour=18))
        self.assertEqual(len(r["expired"]),1)
        self.assertFalse(r["expiring"])

    def test_deadline_requires_timezone_and_matching_date(self):
        for value in ["2026-11-30T17:00:00","2026-10-26T17:00:00+09:00"]:
            with self.assertRaises(ValueError):
                validate(benefit(deadline_at=value).data(),SOURCES,NOW)

    def test_excluded_evidence_is_required(self):
        with self.assertRaises(ValueError):
            validate(benefit(excluded_reason="duplicate",evidence="").data(),SOURCES,NOW)

    def test_excluded_not_recommended(self):
        item=benefit(excluded_reason="Duplicate of canonical record")
        r=classify({}, {item.id:item},NOW)
        self.assertEqual(len(r["excluded"]),1)
        self.assertFalse(r["new"])
        self.assertFalse(r["expiring"])

    def test_changed_title_reopens_excluded_for_review(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            save(root/"sources.yaml",dict(sources=[SOURCE]))
            old=benefit(excluded_reason="Duplicate")
            save(root/"input.json",[old.data()])
            run(root,root/"input.json",now=NOW)
            save(root/"input.json",[dict(source=old.source,url=old.url,title="New program",summary="Discovery")])
            r=run(root,root/"input.json",now=NOW)
            self.assertFalse(r["excluded"])
            self.assertEqual(len(r["needs_recheck"]),1)
            self.assertIsNone(r["needs_recheck"][0]["valid_until"])

    def test_unchanged_discovery_does_not_revive_expired(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            save(root/"sources.yaml",dict(sources=[SOURCE]))
            old=benefit(valid_until="2026-10-01")
            save(root/"input.json",[old.data()])
            run(root,root/"input.json",now=NOW)
            save(root/"input.json",[dict(source=old.source,url=old.url,title=old.title,summary="Discovery")])
            r=run(root,root/"input.json",now=NOW)
            self.assertEqual(len(r["expired"]),1)
            self.assertFalse(r["needs_recheck"])
