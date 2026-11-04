"""Official HTML links are candidates, never automatically verified benefits."""
from html.parser import HTMLParser
from urllib.error import HTTPError
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
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
        self.link_title = ""
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.parts = dict(attrs).get("href"), []
            self.link_title = dict(attrs).get("title", "")
            self.title_parts, self.title_tag = [], None
        if self.href and (tag in ("h1", "h2", "h3", "strong") or set(dict(attrs).get("class", "").split()) & {"tit", "item-title", "title"}):
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
        if self.href.startswith("#"):
            self.href = None
            return
        # Translate only the observed public card-tab links; never execute JS.
        tab = re.fullmatch(r"javascript:\s*fncTab\('([23])'\);?", self.href)
        if tab and urlsplit(self.route).hostname == "www.7-eleven.co.kr" and urlsplit(self.route).path == "/product/cardInfo.asp":
            self.href = "/product/cardInfo.asp?gbn=" + tab.group(1)
        url = urljoin(self.route, self.href)
        parts = urlsplit(url)
        if parts.hostname == "www.7-eleven.co.kr" and parts.path == "/product/cardInfo.asp":
            if parse_qsl(parts.query) not in ([('gbn', '2')], [('gbn', '3')]):
                self.href = None
                return
        if parts.hostname == "www.korea.kr":
            query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                     if k not in ("pWise", "pWiseSub")]
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
        if parts.hostname == "yeyak.seoul.go.kr" and parts.path == "/web/reservation/selectReservView.do":
            query = [(k, v) for k, v in parse_qsl(parts.query) if k != "reSvc"]
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
            if self.link_title.strip():
                self.title_parts = [self.link_title]
        text = " ".join(" ".join(self.title_parts or self.parts).split()) or self.link_title
        title = re.sub(r"^\d{1,2}\s+", "", text)
        if (title and official(url, self.domains) and self.pattern.fullmatch(urlsplit(url).path)
                and any(word in title for word in self.keywords)):
            self.items.setdefault(url, title[:240])
        self.href = None

def collect(source):
    route = source["html_url"]
    u = urlsplit(route)
    try:
        robot = fetch(f"{u.scheme}://{u.netloc}/robots.txt", source["domains"]).decode("utf-8")
    except HTTPError as error:
        # A missing robots file is distinct from an access denial or outage.
        if error.code != 404:
            raise
        robot = ""
    if not allowed(robot, route, AGENT):
        raise ValueError("robots disallows HTML collection")
    parser = ArticleLinks(route, source["domains"], source["article_path_pattern"], source["keywords"])
    parser.feed(fetch(route, source["domains"]).decode("utf-8"))
    result = []
    for url, title in parser.items.items():
        if allowed(robot, url, AGENT):
            result.append(dict(source=source["id"], url=url, title=title,
                               summary="공식 페이지에서 발견한 후보. 상세 조건 검증 필요.", needs_recheck=True))
    if not result:
        raise ValueError("No matching official articles; manual review required")
    return result

