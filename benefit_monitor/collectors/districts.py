"""Free district coverage through Seoul's public news listing, one page per district."""
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlencode
from .rss import fetch, AGENT
from .html import ArticleLinks
from ..store import load, save
from ..robots import allowed

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
        route = BASE + "/news/newsListAjax.do?" + urlencode(dict(
            search_pageNo=1, search_orderBy="articlePubDt", search_articleArea=key,
            search_isNews="Y", search_isCorresNews="N", newsListType="thumbnail"))
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
                result["items"] = parse(body, route, name, source["keywords"])
            except ValueError:
                # A transient HTML/error response may arrive with HTTP 200.
                # Retry once, still requiring an exact district match.
                body = fetch(route, DOMAINS).decode("utf-8")
                result["items"] = parse(body, route, name, source["keywords"])
            result.update(status="checked", candidates_count=len(result["items"]))
        except Exception as error:
            result.update(error_type=type(error).__name__, detail=str(error)[:240], candidates_count=0)
        cache[key] = result
        all_items.extend(result["items"])
        coverage.append({k:v for k,v in result.items() if k != "items"} | {"mode":"live"})
    save(root/"cache/district_candidates.json", cache)
    return all_items, coverage

