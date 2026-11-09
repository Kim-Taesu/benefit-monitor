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
from .collectors.public import collect as collect_public
from . import cost_policy
from . import festivals
from . import groceries
from . import operations
from . import collection_snapshot
from .models import Benefit
from .briefing import build as build_briefing, write as write_briefing

def run(root, imports=None, online=False, now=None, ai_review=False, ai_execute=False, ai_max_candidates=2, snapshot=None, ai_max_verify=0):
    if ai_review and (type(ai_max_candidates) is not int or not 1<=ai_max_candidates<=20):raise ValueError("AI candidate limit 1..20")
    if ai_execute and not ai_review:raise ValueError("AI spend requires explicit review stage")
    if ai_review and not online:raise ValueError("AI body review requires explicit online collection")
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
        if snapshot is not None:
            # Today's free collection (collection_snapshot): no listing request is repeated.
            incoming, district_coverage, successful_sources, failures, handoffs = collection_snapshot.unpack(root, snapshot)
        else:
            try:
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
                    if online and s.get("collector") == "grocery_prices":
                        # Separate display channel like festivals: official averages only, no review or AI.
                        try:
                            save(root/"cache/groceries.json", groceries.collect(s, now))
                            successful_sources.append(s["id"])
                        except Exception as e:
                            failures.append(dict(source=s["id"], reason=type(e).__name__, **operations.error_info(e)))
                        continue
                    if online and s.get("collector") == "kfes_festivals":
                        # Separate display channel: never review candidates, AI research or topic cards.
                        try:
                            save(root/"cache/festivals.json", festivals.collect(s, now))
                            successful_sources.append(s["id"])
                        except Exception as e:
                            failures.append(dict(source=s["id"], reason=type(e).__name__, **operations.error_info(e)))
                        continue
                    if online and (s.get("feed_url") or s.get("html_url") or s.get("collector")):
                        try:
                            incoming.extend(collect_public(s, now) if s.get("collector") else collect(s) if s.get("feed_url") else collect_html(s))
                            successful_sources.append(s["id"])
                            continue
                        except Exception as e:
                            failures.append(dict(source=s["id"], reason=type(e).__name__, **operations.error_info(e)))
                    handoffs.append(dict(source=s["id"], routes=s["routes"], reason="official_detail_review_required"))
            finally:
                pass
            if online:
                collection_snapshot.capture(root, now, incoming, district_coverage, successful_sources, failures, handoffs)
        # Explicit validated inputs take precedence over discovered candidates.
        explicit_items = [validate(d, sources, now) for d in explicit]
        operational_state = operations.sanitize(load(root/"cache/operational_state.json", {}), set(sources), now)
        verify_result = None
        if ai_review:
            # Quality check of collected data first (public items, then review candidates), so a
            # code-confirmed contradiction already withholds the item in this run's observe().
            from .ai_verify import run as verify
            cost_policy.budget.limit=100
            verify_result = verify(root, [i for i in explicit_items if i.verified_at], incoming, operational_state, sources, now,
                                   max_items=ai_max_verify, execute=ai_execute)
            for cid in verify_result['changed_ids']:
                operational_state.setdefault('items',{}).setdefault(cid,{}).update(
                    hold_at=now.isoformat(),hold_reason='body_changed')
        explicit_items = operations.observe(operational_state, incoming, explicit_items, now)
        ai_result = None
        if ai_review:
            from .ai_review import review_candidates
            # Collection ran under the configured limit; research gets the rest up to the project max of 100.
            cost_policy.budget.limit=100
            # Sources whose details hold conditions only in images are not sent to paid research.
            # Human-approved items are audited by verification instead, and candidates that
            # verification confirmed ended or not a benefit are not researched.
            approved_ids = {i.id for i in explicit_items if i.verified_at}
            records = operational_state.get('items', {})
            def researchable(c):
                cid = Benefit(**{k: v for k, v in c.items() if k in Benefit.__dataclass_fields__}).id
                return (sources.get(c['source'], {}).get('ai_review', True) and cid not in approved_ids
                        and not records.get(cid, {}).get('ai_dismissed'))
            ai_candidates = [c for c in incoming + [i.data() for i in explicit_items if not i.verified_at] if researchable(c)]
            ai_result = review_candidates(root, ai_candidates, now,
                                          max_candidates=ai_max_candidates, execute=ai_execute)
            for cid in ai_result['changed_ids']:
                operational_state.setdefault('items',{}).setdefault(cid,{}).update(
                    hold_at=now.isoformat(),hold_reason='body_changed')
        # AI auto-published records are rechecked here every day, even when the AI run fails.
        from . import auto_release
        auto_approved, auto_takedowns = auto_release.load(root) if online else ({}, [])
        auto_reader = None
        if auto_approved:
            from .official_reader import OfficialReader
            auto_reader = OfficialReader(root, now)
        body_failures = operations.check_bodies(operational_state, explicit_items, sources, now, config.get("body_checks_per_run", 0),
                                                auto=auto_approved, takedowns=auto_takedowns, reader=auto_reader) if online else []
        if auto_approved:
            auto_release.save_approved(root, auto_approved)
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
        if ai_result is not None:report["ai_review"] = ai_result
        if verify_result is not None:report["ai_verify"] = verify_result
        report["body_check_failures"] = body_failures
        report["review_queue"] = operations.queue(report, operational_state, now, config.get("max_age_days", 7), successful_sources)
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
    p.add_argument("--ai-review", action="store_true", help="Stage official bodies for private AI review")
    p.add_argument("--ai-allow-spend", action="store_true", help="Explicit one-run Claude trial authorization")
    p.add_argument("--ai-max-candidates", type=int, default=2)
    a = p.parse_args()
    r = run(a.root, a.import_items, a.online, ai_review=a.ai_review, ai_execute=a.ai_allow_spend, ai_max_candidates=a.ai_max_candidates)
    print(f"Report: {a.root / 'report.json'}; complete={r['complete']}")

if __name__ == "__main__":
    main()

