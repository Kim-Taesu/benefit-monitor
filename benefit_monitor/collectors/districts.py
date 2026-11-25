"""Free district coverage through Seoul's public news listing, one page per district.

A district_feed source may ask for a second page (district_pages 2, approved 2026-11-25). That page is
read by collect_more() after every other source, only while the shared HTTP budget still has room, so
it can never take requests from the collection order (groceries are last and need their share)."""
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlencode
from .rss import fetch, AGENT
from .html import ArticleLinks
from ..store import load, save
from ..robots import allowed
from ..operations import error_info
from .. import cost_policy

BASE = "https://mediahub.seoul.go.kr"
DOMAINS = ["mediahub.seoul.go.kr"]

class RegionLabels(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_region, self.strong, self.labels = False, False, []
    def handle_starttag(self, tag, attrs):
        classes = dict(attrs).get("class", "").split()
        if tag == "p":
            self.in_region = "corres_box" in classes and "type" in classes
        if tag == "strong" and self.in_region:
            self.strong = True
    def handle_data(self, data):
        if self.strong and data.strip():
            self.labels.append(data.strip())
    def handle_endtag(self, tag):
        if tag == "strong":
            self.strong = False
        if tag == "p":
            self.in_region = False

def parse(body, route, district, keywords):
    labels = RegionLabels()
    labels.feed(body)
    if not labels.labels or set(labels.labels) != {district}:
        raise ValueError("District response missing or filter mismatch; no coverage claim")
    parser = ArticleLinks(route, DOMAINS, r"/archives/\d+", keywords)
    parser.feed(body)
    return [dict(source="seoul", url=url, title=title,
                 summary="서울시 공식 자치구 뉴스 후보. 상세 조건 확인 필요.",
                 districts=[district], needs_recheck=True) for url, title in parser.items.items()]

def title_words(source):
    """District listings also take life-event titles (개장·축제·공연…) without a 'benefit' word."""
    return list(dict.fromkeys(list(source["keywords"]) + list(source.get("district_keywords") or [])))

def listing_url(code, page):
    return BASE + "/news/newsListAjax.do?" + urlencode(dict(
        search_pageNo=page, search_orderBy="articlePubDt", search_articleArea=code,
        search_isNews="Y", search_isCorresNews="N", newsListType="thumbnail"))

def collect(root, source, now):
    registry = load(root/"districts.json", None)["districts"]
    cache = load(root/"cache/district_candidates.json", {})
    all_items, coverage = [], []
    robot, robot_error = None, None
    for district in registry:
        key, name = district["code"], district["name"]
        previous = cache.get(key)
        if previous:
            age = (now-datetime.fromisoformat(previous["checked_at"])).total_seconds()
            ttl = 21600 if previous["status"] == "checked" else 900
            if 0 <= age < ttl:
                coverage.append({k:v for k,v in previous.items() if k != "items"} | {"mode":"cached"})
                all_items.extend(previous["items"])
                continue
        route = listing_url(key, 1)
        result = dict(district=name, code=key, checked_at=now.isoformat(), url=route,
                      scope="seoul_publications_first_page", status="failed", items=[])
        try:
            if robot_error is not None:
                raise robot_error
            if robot is None:
                try:
                    robot = fetch(BASE+"/robots.txt", DOMAINS).decode("utf-8")
                except Exception as error:
                    # One shared endpoint; its failure must not restart 25 retries.
                    robot_error = error
                    raise
            if not allowed(robot, route, AGENT):
                raise ValueError("robots disallows district listing")
            body = fetch(route, DOMAINS).decode("utf-8")
            try:
                result["items"] = parse(body, route, name, title_words(source))
            except ValueError:
                # A transient HTML/error response may arrive with HTTP 200.
                # Retry once, still requiring an exact district match.
                body = fetch(route, DOMAINS).decode("utf-8")
                result["items"] = parse(body, route, name, title_words(source))
            result.update(status="checked", candidates_count=len(result["items"]))
        except Exception as error:
            result.update(**error_info(error), candidates_count=0)
        cache[key] = result
        all_items.extend(result["items"])
        coverage.append({k:v for k,v in result.items() if k != "items"} | {"mode":"live"})
    save(root/"cache/district_candidates.json", cache)
    return all_items, coverage



# robots (1) + one page per district must fit, so a partial run never reads half the extra pages.
def collect_more(root, source, now, names, page=2):
    """Page `page` of the named districts' listings, only when the remaining HTTP budget covers them all.
    Cached like page 1 (6 h, failures 15 min). Returns (items, rows); rows never count as district coverage."""
    registry = {d["name"]: d["code"] for d in load(root/"districts.json", None)["districts"]}
    names = [n for n in dict.fromkeys(names) if n in registry]
    cache = load(root/"cache/district_more_pages.json", {})
    items, rows, todo = [], [], []
    for name in names:
        key = f"{registry[name]}:p{page}"
        previous = cache.get(key)
        if previous:
            try:
                age = (now-datetime.fromisoformat(previous["checked_at"])).total_seconds()
            except (TypeError, ValueError):
                age = -1
            ttl = 21600 if previous.get("status") == "checked" else 900
            if 0 <= age < ttl:
                rows.append({k:v for k,v in previous.items() if k != "items"} | {"mode":"cached"})
                items.extend(previous.get("items") or [])
                continue
        todo.append(name)
    if not todo:
        return items, rows
    if cost_policy.budget.limit - cost_policy.budget.used < len(todo) + 1:
        rows += [dict(district=n, page=page, status="skipped", reason="http_budget", mode="live") for n in todo]
        return items, rows
    try:
        robot = fetch(BASE+"/robots.txt", DOMAINS).decode("utf-8")
    except Exception as error:
        rows += [dict(district=n, page=page, status="failed", mode="live", **error_info(error)) for n in todo]
        return items, rows
    for name in todo:
        route = listing_url(registry[name], page)
        result = dict(district=name, code=registry[name], page=page, checked_at=now.isoformat(), url=route,
                      scope=f"seoul_publications_page_{page}", status="failed", items=[])
        try:
            if not allowed(robot, route, AGENT):
                raise ValueError("robots disallows district listing")
            result["items"] = parse(fetch(route, DOMAINS).decode("utf-8"), route, name, title_words(source))
            result.update(status="checked", candidates_count=len(result["items"]))
        except Exception as error:
            result.update(**error_info(error), candidates_count=0)
        cache[f"{registry[name]}:p{page}"] = result
        items.extend(result["items"])
        rows.append({k:v for k,v in result.items() if k != "items"} | {"mode":"live"})
    save(root/"cache/district_more_pages.json", cache)
    return items, rows
