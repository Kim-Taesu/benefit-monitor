"""Discover only explicitly advertised RSS/Atom feeds on official pages."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo
from .collectors.rss import AGENT, fetch, collect
from .validation import official
from .store import load, save
from .robots import allowed
from . import cost_policy

class FeedLinks(HTMLParser):
    def __init__(self, url, domains):
        super().__init__()
        self.url, self.domains, self.links = url, domains, []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if (tag != "link" or "alternate" not in attrs.get("rel", "").lower().split()
                or attrs.get("type", "").lower() not in ("application/rss+xml", "application/atom+xml")):
            return
        url = urljoin(self.url, attrs.get("href", ""))
        if official(url, self.domains) and url not in self.links:
            self.links.append(url)

def discover(source):
    checks, feeds = [], []
    for route in source["routes"]:
        try:
            u = urlsplit(route)
            robot = fetch(f"{u.scheme}://{u.netloc}/robots.txt", source["domains"]).decode("utf-8")
            if not allowed(robot, route, AGENT):
                raise ValueError("robots disallows discovery page")
            body = fetch(route, source["domains"]).decode("utf-8")
            parser = FeedLinks(route, source["domains"])
            parser.feed(body)
            for url in parser.links:
                try:
                    candidates = collect(dict(source, feed_url=url))
                    feeds.append(dict(url=url, candidates_count=len(candidates)))
                except Exception as error:
                    checks.append(dict(url=url, status="feed_unavailable", error_type=type(error).__name__, detail=str(error)[:240]))
            checks.append(dict(url=route, status="page_checked", advertised_feeds=len(parser.links)))
        except Exception as error:
            checks.append(dict(url=route, status="unavailable", error_type=type(error).__name__, detail=str(error)[:240]))
    return dict(source=source["id"], verified_feeds=feeds, checks=checks,
                status="feed_verified" if feeds else "browser_review_required")

def run(root, selected=None):
    root = Path(root)
    config = load(root/"sources.yaml", None)
    cost_policy.require_free(config)
    cost_policy.reset(config.get("max_http_requests", 60))
    sources = config["sources"]
    if selected:
        unknown = set(selected) - {s["id"] for s in sources}
        if unknown:
            raise ValueError("Unknown sources: " + ", ".join(sorted(unknown)))
        sources = [s for s in sources if s["id"] in selected]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(discover, sources))
    report = dict(checked_at=datetime.now(ZoneInfo("Asia/Seoul")).isoformat(), sources=results, cost_policy=cost_policy.telemetry())
    save(root/"cache/source_probe.json", report)
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--sources", nargs="+")
    args = parser.parse_args()
    report = run(args.root, args.sources)
    for source in report["sources"]:
        print(source["source"], source["status"], len(source["verified_feeds"]))
    print("Saved:", args.root/"cache/source_probe.json")

if __name__ == "__main__":
    main()
