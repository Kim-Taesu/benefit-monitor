"""Official HTML links are candidates, never automatically verified benefits."""
from html.parser import HTMLParser
from urllib.error import HTTPError
import re
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from .rss import AGENT, fetch
from ..validation import official
from ..robots import allowed

SEVEN_EVENTS = "/event/eventList.asp"
SEVEN_VIEW = re.compile(r"javascript:\s*fncGoView\('(\d+)',\s*'\d+'\);?")
MOF_HOST, MOF_LIST = "www.mof.go.kr", "/doc/ko/selectDocList.do"
MOF_VIEW = re.compile(r"fn_selectDoc\('(\d+)'\)\s*;?")
MOF_TITLE_PREFIX = "[게시글 바로가기] "
PERIOD_FIRST = re.compile(r"(\d{4}-\d\d-\d\d ~ \d{4}-\d\d-\d\d)\s+(.+)")

class ArticleLinks(HTMLParser):
    def __init__(self, route, domains, pattern, keywords, require_any=None, exclude_any=None):
        super().__init__()
        # Optional second title filter: at least one word must appear in addition to a keyword.
        self.require_any = require_any
        # Optional exclusion: a title containing any of these is dropped (세일 inside 세일즈).
        self.exclude_any = exclude_any
        self.seen = 0
        self.route, self.domains = route, domains
        self.pattern, self.keywords = re.compile(pattern), keywords
        self.href, self.parts, self.items = None, [], {}
        self.title_parts, self.title_tag = [], None
        self.link_title, self.onclick = "", ""
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href, self.parts = dict(attrs).get("href"), []
            self.link_title = dict(attrs).get("title", "")
            self.onclick = dict(attrs).get("onclick") or ""
            self.title_parts, self.title_tag = [], None
        # Seven-Eleven's event list puts the event name only in the thumbnail's alt text.
        if tag == "img" and self.href and SEVEN_VIEW.fullmatch(self.href):
            self.link_title = dict(attrs).get("alt", "")
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
        # The Ministry of Oceans and Fisheries list opens details by JS (href="#none"); translate
        # the observed fn_selectDoc(n) call to its public detail URL without executing anything.
        mof = MOF_VIEW.fullmatch(self.onclick.strip())
        if self.href.startswith("#") and mof and urlsplit(self.route).hostname == MOF_HOST and urlsplit(self.route).path == MOF_LIST:
            self.href = f"/doc/ko/selectDoc.do?docSeq={mof.group(1)}&menuSeq=971&bbsSeq=10"
            # The visible text is truncated with "..."; the title attribute holds the full name.
            if self.link_title.startswith(MOF_TITLE_PREFIX) and self.link_title[len(MOF_TITLE_PREFIX):].strip():
                self.title_parts = [self.link_title[len(MOF_TITLE_PREFIX):]]
        if self.href.startswith("#"):
            self.href = None
            return
        # Translate only the observed public card-tab links; never execute JS.
        tab = re.fullmatch(r"javascript:\s*fncTab\('([23])'\);?", self.href)
        if tab and urlsplit(self.route).hostname == "www.7-eleven.co.kr" and urlsplit(self.route).path == "/product/cardInfo.asp":
            self.href = "/product/cardInfo.asp?gbn=" + tab.group(1)
        # Seven-Eleven event details open only by form POST, so each event keeps the list URL
        # with its sequence number as a fragment. The page is never fetched by that fragment.
        view = SEVEN_VIEW.fullmatch(self.href)
        if view and urlsplit(self.route).hostname == "www.7-eleven.co.kr" and urlsplit(self.route).path == SEVEN_EVENTS:
            self.href = SEVEN_EVENTS + "#seqNo=" + view.group(1)
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
        # emart24 event cards start with the listed period; keep it, after the name.
        period = PERIOD_FIRST.fullmatch(title) if parts.hostname in ("emart24.co.kr", "www.emart24.co.kr") else None
        if period:
            title = f"{period.group(2)} ({period.group(1)})"
        if title and official(url, self.domains) and self.pattern.fullmatch(urlsplit(url).path):
            self.seen += 1
        # "*" is used only by pages that list nothing but ongoing events.
        if (title and official(url, self.domains) and self.pattern.fullmatch(urlsplit(url).path)
                and (("*" in self.keywords and url != self.route) or any(word in title for word in self.keywords))
                and (not self.require_any or any(word in title for word in self.require_any))
                and not any(word in title for word in self.exclude_any or ())):
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
    parser = ArticleLinks(route, source["domains"], source["article_path_pattern"], source["keywords"], source.get("require_any"),
                          source.get("exclude_any"))
    parser.feed(fetch(route, source["domains"]).decode("utf-8"))
    result = []
    for url, title in parser.items.items():
        if allowed(robot, url, AGENT):
            result.append(dict(source=source["id"], url=url, title=title,
                               summary="공식 페이지에서 발견한 후보. 상세 조건 검증 필요.", needs_recheck=True))
    # allow_empty: a day without matching titles is normal, but a page with no article links
    # at all means the structure changed and must still fail, and so do matching titles that
    # robots blocks (nothing was collected although there was something to collect).
    if not result and source.get("allow_empty") and parser.seen and not parser.items:
        return result
    if not result:
        raise ValueError("No matching official articles; manual review required")
    return result

