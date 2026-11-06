"""Compare a published briefing's per-source status with sources/<id>.json expectations.

Run by the Source health workflow after each daily collection. A source expected to work
that failed, a missing or stale report, or a failed district list exits 1 so CI turns red.
Known failures pass but stay listed; a known failure that recovers is a warning.
Only identifiers and error categories are printed, never raw errors or URLs.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .source_registry import ROOT, load

OK = ("checked", "cached")


def evaluate(definitions, briefing, now, started_at=None, max_age_hours=30):
    errors, warnings, rows = [], [], []
    coverage = briefing.get("coverage") or {}
    reported = {row["source"]: row for row in coverage.get("sources", [])}
    health = briefing.get("source_health") or {}
    if briefing.get("status") == "collection_failed" or not reported:
        errors.append(f"collection: published status {briefing.get('status')!r} without source coverage")
    stamp = briefing.get("source_report_at")
    observed = datetime.fromisoformat(stamp) if stamp else None
    if observed is None:
        errors.append("collection: source_report_at missing")
    elif started_at and observed < started_at:
        errors.append(f"collection: published report {stamp} predates this collection run")
    elif now - observed > timedelta(hours=max_age_hours):
        errors.append(f"collection: published report {stamp} is older than {max_age_hours}h")
    active = [d for d in definitions if d["status"] == "active"]
    for d in active:
        expect = d["monitoring"]["expect"]
        row = reported.get(d["id"])
        status = row["status"] if row else "not_reported"
        record = health.get(d["id"], {})
        detail = record.get("error_category", "")
        failures = record.get("consecutive_failures")
        rows.append(dict(source=d["id"], expect=expect, status=status, category=detail, consecutive_failures=failures))
        ok = status in OK
        if expect == "working" and not ok:
            errors.append(f"{d['id']}: expected working, got {status}" + (f" ({detail}, {failures} in a row)" if detail else ""))
        elif expect == "known_failing" and ok:
            warnings.append(f"{d['id']}: known failure recovered; set monitoring.expect to working")
        elif expect == "manual" and status != "not_connected":
            warnings.append(f"{d['id']}: manual source reported {status}; review monitoring.expect")
    unknown = sorted(set(reported) - {d["id"] for d in active})
    if unknown:
        warnings.append(f"sources without an active definition: {', '.join(unknown)}")
    seoul = next((d for d in active if d["id"] == "seoul"), None)
    districts = coverage.get("districts", [])
    bad = [row["name"] for row in districts if row.get("status") not in OK]
    if seoul and seoul["monitoring"]["expect"] == "working" and bad:
        errors.append(f"seoul districts not collected: {', '.join(bad)}")
    return errors, warnings, rows


def summary(errors, warnings, rows, districts):
    lines = ["## Source health", "", f"결과: **{'실패' if errors else '정상'}** · 출처 {len(rows)}개 · 구 목록 {districts}개", "",
             "| 출처 | 기대 | 이번 상태 | 오류 분류 | 연속 실패 |", "|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['source']} | {row['expect']} | {row['status']} | {row['category'] or '-'} | {row['consecutive_failures'] if row['consecutive_failures'] is not None else '-'} |")
    for title, items in (("실패", errors), ("경고", warnings)):
        if items:
            lines += ["", f"### {title}"] + [f"- {item}" for item in items]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--briefing", type=Path, required=True)
    parser.add_argument("--started-at", help="ISO time the collection run started; older reports fail")
    parser.add_argument("--max-age-hours", type=int, default=30)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    _, definitions = load(args.root)
    briefing = json.loads(args.briefing.read_text(encoding="utf-8"))
    now = datetime.now().astimezone()
    started = datetime.fromisoformat(args.started_at.replace("Z", "+00:00")) if args.started_at else None
    errors, warnings, rows = evaluate(definitions, briefing, now, started, args.max_age_hours)
    text = summary(errors, warnings, rows, len((briefing.get("coverage") or {}).get("districts", [])))
    print(text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(text)
    for item in warnings:
        print(f"::warning::{item}")
    for item in errors:
        print(f"::error::{item}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
