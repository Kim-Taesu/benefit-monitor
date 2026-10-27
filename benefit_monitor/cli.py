import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import replace
from zoneinfo import ZoneInfo
from .store import load, save, lock
from .validation import validate
from .diff import classify
from .collectors.rss import collect
from .collectors.html import collect as collect_html
from .collectors.districts import collect as collect_districts
from . import cost_policy
from . import operations
from .briefing import build as build_briefing, write as write_briefing

def run(root, imports=None, online=False, now=None):
    root = Path(root)
    now = now or datetime.now(ZoneInfo("Asia/Seoul"))
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    now = now.astimezone(ZoneInfo("Asia/Seoul"))
    config = load(root/"sources.yaml", None)
    cost_policy.require_free(config)
    cost_policy.reset(config.get("max_http_requests", 60))
    sources = {s["id"]: s for s in config["sources"]}
    if len(sources) != len(config["sources"]):
        raise ValueError("Duplicate source")
    with lock(root/"cache/.lock"):
        old = {i.id: i for i in (validate(d, sources, now) for d in load(root/"cache/verified_items.json", []))}
        current = dict(old)
        explicit = load(imports, []) if imports else []
        incoming = []
        handoffs, failures = [], []
        district_coverage = []
        successful_sources = []
        if config.get("seoul_district_coverage"):
            if online:
                district_items, district_coverage = collect_districts(root, sources["seoul"], now)
                incoming.extend(district_items)
            else:
                cached = load(root/"cache/district_candidates.json", {})
                district_coverage = [{k:v for k,v in c.items() if k != "items"} | {"mode":"cached"} for c in cached.values()]
            for d in district_coverage:
                if d["status"] != "checked":
                    failures.append(dict(source="seoul", district=d["district"], reason=d.get("error_type"), category=d.get("category", "other")))

        for s in sources.values():
            if online and s.get("district_feed"):
                record = next((d for d in district_coverage if d["district"] == s["district_feed"]), {})
                if record.get("status") == "checked":
                    successful_sources.append(s["id"])
                    continue
                failures.append(dict(source=s["id"], reason="DistrictFeedUnavailable", detail="Official district feed unavailable"))
            if online and (s.get("feed_url") or s.get("html_url")):
                try:
                    incoming.extend(collect(s) if s.get("feed_url") else collect_html(s))
                    successful_sources.append(s["id"])
                    continue
                except Exception as e:
                    failures.append(dict(source=s["id"], reason=type(e).__name__, **operations.error_info(e)))
            handoffs.append(dict(source=s["id"], routes=s["routes"], reason="official_detail_review_required"))
        # Explicit validated inputs take precedence over discovered candidates.
        explicit_items = [validate(d, sources, now) for d in explicit]
        operational_state = operations.sanitize(load(root/"cache/operational_state.json", {}), set(sources), now)
        explicit_items = operations.observe(operational_state, incoming, explicit_items, now)
        body_failures = operations.check_bodies(operational_state, explicit_items, sources, now, config.get("body_checks_per_run", 0)) if online else []
        explicit_items = operations.observe(operational_state, [], explicit_items, now)
        if len({i.id for i in explicit_items}) != len(explicit_items):
            raise ValueError("Duplicate imported URL")
        merged = {}
        for data in incoming:
            item = validate(data, sources, now)
            if item.id in merged:
                merged[item.id]["districts"] = sorted(set(merged[item.id].get("districts", []) + item.districts))
            else:
                merged[item.id] = item.data()
        merged.update({i.id: i.data() for i in explicit_items})
        seen = set()
        for data in merged.values():
            item = validate(data, sources, now)
            if item.id in seen:
                raise ValueError("Duplicate imported URL")
            seen.add(item.id)
            prev = current.get(item.id)
            if prev and item.districts:
                item = replace(item, districts=sorted(set(item.districts + prev.districts)))
            if prev and item.needs_recheck and not item.verified_at:
                if item.title != prev.title:
                    current[item.id] = replace(prev, title=item.title, needs_recheck=True, excluded_reason="", valid_until=None, valid_from=None, deadline_at=None, validity_kind="fixed", districts=sorted(set(prev.districts + item.districts)))
                elif item.districts:
                    current[item.id] = replace(prev, districts=sorted(set(prev.districts + item.districts)))
                continue
            current[item.id] = item
        report = classify(old, current, now, config.get("expiring_days", 7), config.get("max_age_days", 7))
        operations.health(operational_state, successful_sources, failures, now)
        operations.classify_history(report, operational_state)
        report["body_check_failures"] = body_failures
        report["review_queue"] = operations.queue(report, operational_state, now, config.get("max_age_days", 7))
        save(root/"cache/operational_state.json", operational_state)
        report["district_coverage"] = district_coverage
        report["collection"] = dict(online=online, successful_sources=successful_sources,
                                  successful_districts=sum(d["status"] == "checked" and d.get("mode") == "live" for d in district_coverage))
        report["cost_policy"] = cost_policy.telemetry()
        report["by_district"] = {}
        for key, entries in report.items():
            if key in ("new", "changed", "upcoming", "expiring", "still_valid", "needs_recheck", "expired", "excluded"):
                for entry in entries:
                    for district in entry["districts"]:
                        report["by_district"].setdefault(district, {}).setdefault(key, []).append(entry)
        report.update(verified_at=now.isoformat(), browser_handoffs=handoffs,
                      verification_limits=failures[:3], failures_count=len(failures),
                      complete=not handoffs and not failures and not report["needs_recheck"])
        briefing = build_briefing(report, config, now)
        save(root/"report.json", report)
        save(root/"cache/verified_items.json", [i.data() for i in current.values()])
        save(root/"cache/collection_log.json", failures)
        write_briefing(root, briefing)
        return report

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    p.add_argument("--import-items", type=Path)
    p.add_argument("--online", action="store_true")
    a = p.parse_args()
    r = run(a.root, a.import_items, a.online)
    print(f"Report: {a.root / 'report.json'}; complete={r['complete']}")

if __name__ == "__main__":
    main()

