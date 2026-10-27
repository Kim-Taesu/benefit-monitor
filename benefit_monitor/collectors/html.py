"""Official HTML links are candidates, never automatically verified benefits."""
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlsplit
from .rss import AGENT, fetch
from ..validation import official
from ..robots import allowed

class ArticleLinks(HTMLParser):
    def __init__(self, route, domains, pattern, keywords):
        super().__init__()
        self.route, self.domains = route, domains
        self.pattern, self.keywords = re.compile(pattern), keywords
        self.href, self.parts, self.items = None, [], {}
        self.title_parts, self.title_tag = [], None
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.parts = dict(attrs).get("href"), []
            self.title_parts, self.title_tag = [], None
        if self.href and (tag in ("h1", "h2", "h3") or "tit" in dict(attrs).get("class", "").split()):
            self.title_tag = tag
    def handle_data(self, data):
        if self.href:
            self.parts.append(data)
            if self.title_tag:
                self.title_parts.append(data)
    def handle_endtag(self, tag):
        if tag == self.title_tag:
            self.title_tag = None
        if tag != "a" or not self.href:
            return
        url = urljoin(self.route, self.href)
        title = re.sub(r"^\d{1,2}\s+", "", " ".join(" ".join(self.title_parts or self.parts).split()))
        if (title and official(url, self.domains) and self.pattern.fullmatch(urlsplit(url).path)
                and any(word in title for word in self.keywords)):
            self.items.setdefault(url, title[:240])
        self.href = None

def collect(source):
    route = source["html_url"]
    u = urlsplit(route)
    robot = fetch(f"{u.scheme}://{u.netloc}/robots.txt", source["domains"]).decode("utf-8")
    if not allowed(robot, route, AGENT):
        raise ValueError("robots disallows HTML collection")
    parser = ArticleLinks(route, source["domains"], source["article_path_pattern"], source["keywords"])
    parser.feed(fetch(route, source["domains"]).decode("utf-8"))
    result = []
    for url, title in parser.items.items():
        if allowed(robot, url, AGENT):
            result.append(dict(source=source["id"], url=url, title=title,
                               summary="공식 서울시 페이지에서 발견한 후보. 상세 조건 검증 필요.", needs_recheck=True))
    if not result:
        raise ValueError("No matching official articles; manual review required")
    return result
