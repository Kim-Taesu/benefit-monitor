import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from benefit_monitor.briefing import build, markdown, run
from benefit_monitor.cli import run as pipeline
from benefit_monitor.store import save
from test_pipeline import benefit, SOURCE, NOW, ROOT

CONFIG = dict(sources=[SOURCE], max_age_days=7, expiring_days=7)

def report(**groups):
    return dict(verified_at=NOW.isoformat(), complete=False, **groups)

def free(number=1, **kwargs):
    values=dict(url=f"https://official.example/offer/{number}", fee_status="free")
    values.update(kwargs)
    return benefit(**values).data()

class BriefingTests(unittest.TestCase):
    def test_top_three_includes_paid_and_unknown_fee_in_deadline_order(self):
        items=[free(i,valid_until=d) for i,d in enumerate(
            ["2026-11-30","2026-10-29","2026-10-27","2026-10-28"])]
        items += [free(9,fee_status="paid",valid_until="2026-10-26"),
                  free(10,fee_status="unknown",valid_until="2026-10-26")]
        b=build(report(still_valid=items),CONFIG,NOW)
        self.assertEqual([i["valid_until"] for i in b["top3"]],
                         ["2026-10-26","2026-10-26","2026-10-27"])
        self.assertEqual(b["eligible_count"],6)

    def test_unknown_fee_can_be_recommended_and_remains_labeled(self):
        b=build(report(still_valid=[free(),free(2,fee_status="unknown")]),CONFIG,NOW)
        self.assertEqual(len(b["top3"]),2)
        self.assertEqual(len(b["other_verified"]),0)
        self.assertIn("요금 미확인",markdown(b))

    def test_blocked_bucket_vetoes_duplicate_eligible(self):
        for group in ("needs_recheck","expired","excluded"):
            item=free()
            b=build(report(still_valid=[item],**{group:[item]}),CONFIG,NOW)
            self.assertFalse(b["top3"])
            self.assertEqual(b["eligible_count"],0)

    def test_expiring_overlap_deduplicates(self):
        item=free(valid_until="2026-10-28")
        b=build(report(still_valid=[item],expiring=[item]),CONFIG,NOW)
        self.assertEqual(b["eligible_count"],1)
        self.assertEqual(len(b["expiring"]),1)

    def test_conflicting_copies_are_suppressed(self):
        item=free()
        conflicting=dict(item,conditions="Different terms")
        b=build(report(still_valid=[item],new=[conflicting]),CONFIG,NOW)
        self.assertEqual(b["eligible_count"],0)
        self.assertEqual(b["withheld"]["invalid_or_conflicting"],1)

    def test_false_verified_and_stale_and_missing_evidence_are_not_recommended(self):
        items=[free(1,needs_recheck=True),
               free(2,verified_at="2026-10-01T08:00:00+09:00"),
               free(3,evidence="")]
        b=build(report(still_valid=items),CONFIG,NOW)
        self.assertFalse(b["top3"])
        self.assertEqual(b["withheld"]["pending"],2)
        self.assertEqual(b["withheld"]["invalid_or_conflicting"],1)

    def test_exact_deadline_rechecked_on_old_report(self):
        item=free(valid_until="2026-10-26",deadline_at="2026-10-26T09:00:00+09:00")
        b=build(report(still_valid=[item]),CONFIG,NOW.replace(hour=10))
        self.assertFalse(b["top3"])
        self.assertEqual(b["withheld"]["expired"],1)

    def test_upcoming_not_today_and_in_deadline_reminders(self):
        item=free(valid_from="2026-10-28",valid_until="2026-10-28")
        b=build(report(upcoming=[item]),CONFIG,NOW)
        self.assertFalse(b["top3"])
        self.assertEqual(len(b["upcoming"]),1)
        self.assertEqual(len(b["expiring"]),1)
        self.assertIn("2026-10-28 시작",markdown(b))

    def test_ongoing_no_fabricated_deadline(self):
        b=build(report(still_valid=[free(valid_until=None,validity_kind="ongoing")]),CONFIG,NOW)
        self.assertEqual(len(b["top3"]),1)
        self.assertIn("상시 운영 안내·종료일 미기재",markdown(b))

    def test_prior_day_changes_not_announced_as_today(self):
        b=build(report(new=[free()]),CONFIG,NOW+timedelta(days=1))
        self.assertTrue(b["report_is_from_previous_date"])
        self.assertFalse(b["new_changed"])

    def test_report_timestamp_guard(self):
        with self.assertRaises(ValueError):
            build(dict(verified_at="2026-10-27T08:00:00+09:00"),CONFIG,NOW)
        with self.assertRaises(ValueError):
            build(dict(verified_at="2026-10-26T08:00:00"),CONFIG,NOW)

    def test_foreign_source_link_rejected(self):
        b=build(report(still_valid=[free(url="https://evil.example/")]),CONFIG,NOW)
        self.assertEqual(b["eligible_count"],0)

    def test_untrusted_markdown_text_is_escaped(self):
        item=free(summary="<script>alert(1)</script> [fake](https://evil.example)\n# heading",
                  conditions="*not an instruction*")
        text=markdown(build(report(still_valid=[item]),CONFIG,NOW))
        self.assertNotIn("<script>",text)
        self.assertNotIn("\n# heading",text)
        self.assertIn("&lt;script&gt;",text)
        self.assertIn("[공식 안내](https://official.example/offer/1)",text)

    def test_empty_input_does_not_invent_items(self):
        b=build(report(),CONFIG,NOW)
        self.assertFalse(b["top3"])
        self.assertEqual(b["eligible_count"],0)
        self.assertIn("추천을 채우지 않습니다",markdown(b))

    def test_pipeline_emits_briefing_without_network(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            save(root/"sources.yaml",CONFIG)
            save(root/"input.json",[free()])
            with patch("urllib.request.OpenerDirector.open",side_effect=AssertionError("No HTTP allowed")):
                pipeline(root,root/"input.json",now=NOW)
            data=json.loads((root/"briefing.json").read_text())
            self.assertEqual(len(data["top3"]),1)
            self.assertIn("생활 혜택 브리핑",(root/"briefing.md").read_text())
            self.assertEqual(data["policy"]["network_requests"],0)

    def test_standalone_preserves_report_and_verification_times(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            save(root/"sources.yaml",CONFIG)
            save(root/"report.json",report(still_valid=[free()]))
            before=(root/"report.json").read_bytes()
            with patch("urllib.request.OpenerDirector.open",side_effect=AssertionError("No HTTP allowed")):
                b=run(root,now=NOW)
                run(root,now=NOW)
            self.assertEqual((root/"report.json").read_bytes(),before)
            self.assertEqual(b["top3"][0]["verified_at"],free()["verified_at"])
            self.assertFalse((root/"cache/verified_items.json").exists())

    def test_missing_report_fails_without_inventing_briefing(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root=Path(directory)
            save(root/"sources.yaml",CONFIG)
            with self.assertRaises(ValueError):
                run(root,now=NOW)
            self.assertFalse((root/"briefing.md").exists())

    def test_operator_notes_do_not_leak_into_participation_terms(self):
        item=free(conditions="만 7세 이상 가족. valid_until은 접수 마감일. 유료 대회와 구분하며 신청·결제는 실행하지 않음. 이메일 발송하지 않음.")
        text=markdown(build(report(still_valid=[item]),CONFIG,NOW))
        self.assertIn("만 7세 이상 가족",text)
        self.assertIn("접수 마감일",text)
        self.assertNotIn("valid_until",text)
        self.assertNotIn("이메일 발송하지 않음",text)
        self.assertNotIn("구분하며",text)
        self.assertIn("구분하세요.",text)

    def test_infrastructure_free_does_not_filter_paid_discounts(self):
        item=free(fee_status="paid",summary="필요한 생필품 50% 할인",conditions="지정 카드로 2만원 이상 구매")
        b=build(report(still_valid=[item]),CONFIG,NOW)
        self.assertEqual(b["top3"][0]["fee_status"],"paid")
        self.assertEqual(b["policy"]["benefit_fee_filter"],"none")
        self.assertFalse(b["policy"]["infrastructure_paid_services_allowed"])
        self.assertFalse(b["policy"]["paid_services_used"])
        text=markdown(b)
        self.assertIn("요금: 유료",text)
        self.assertIn("최소구매액",text)
        self.assertNotIn("무료 프로그램의 조건",text)

    def test_paid_infrastructure_remains_forbidden(self):
        config=dict(CONFIG,cost_policy=dict(mode="paid",paid_services_allowed=True))
        with self.assertRaises(ValueError):
            build(report(still_valid=[free(fee_status="paid")]),config,NOW)

    def test_district_groups_replace_repeated_status_sections(self):
        items = [free(1, districts=["강서구"]), free(2, districts=["은평구"]),
                 free(3, districts=[]), free(4, districts=["종로구", "중구"])]
        text = markdown(build(report(still_valid=items), CONFIG, NOW))
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(headings[:3], ["## 서울시", "## 강서구", "## 은평구"])
        self.assertNotIn("## 마감 임박", headings)
        self.assertEqual(text.count("https://official.example/offer/1)"), 1)
        self.assertEqual(text.count("https://official.example/offer/4)"), 2)
        self.assertIn("서울시민 전체의 이용 자격을 뜻하지 않습니다", text)
