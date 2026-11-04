"""Official public list pages without keys: SH notices, Sharenuri facilities, heritage events.

Every result is a review candidate (needs_recheck=True). List metadata such as a
title-based status or a "free" filter is never treated as a verified benefit.
Parsing follows the public page structures documented by the MIT-licensed
NomaDamas/k-skill project (sh-notice-search, sharenuri-facility-search,
korean-heritage-search), reimplemented with the standard library.
"""
import html as htmlmod
import re
import urllib.request
import xml.etree.ElementTree as ET
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit, quote

from .rss import AGENT, LIMIT, Redirect, fetch
from ..robots import allowed
from ..validation import official
from .. import cost_policy

CANDIDATE = "공식 목록에서 발견한 후보. 상세 조건 검증 필요."


def _text(fragment):
    fragment = re.sub(r"<[^>]+>", " ", fragment or "")
    return " ".join(htmlmod.unescape(fragment).split())


def _robots(route, domains):
    u = urlsplit(route)
    try:
        return fetch(f"{u.scheme}://{u.netloc}/robots.txt", domains).decode("utf-8", "replace")
    except HTTPError as error:
        if error.code != 404:
            raise
        return ""


def _require_allowed(robot, url):
    if not allowed(robot, url, AGENT):
        raise ValueError("robots disallows collection")


# --- SH (서울주택도시개발공사) notice boards -------------------------------------------------
SH_BASE = "https://www.i-sh.co.kr"
SH_BOARDS = {
    "rent": ("/app/lay2/program/S1T294C297/www/brd/m_247", "2", "주택임대"),
    "sale": ("/app/lay2/program/S1T294C296/www/brd/m_244", "1", "주택분양"),
    "purchase": ("/app/lay2/program/S1T294C3379/www/brd/m_247", "512", "주택매입"),
}
SH_CLOSED = re.compile(r"당첨|발표|마감|계약결과|결과|완료|종료|취소|매입공고|유효기간 연장")
SH_OPEN = re.compile(r"모집|신청|접수|공고")


def sh_list_url(board):
    path, seq, _ = SH_BOARDS[board]
    return f"{SH_BASE}{path}/list.do?multi_itm_seq={seq}&page=1"


def sh_detail_url(board, seq):
    path, item, _ = SH_BOARDS[board]
    return f"{SH_BASE}{path}/view.do?multi_itm_seq={item}&seq={seq}"


def parse_sh_list(page, board):
    area = re.search(r'<div\b[^>]*id=["\']listTb["\'][^>]*>.*?<tbody[^>]*>(.*?)</tbody>', page, re.S | re.I)
    if not area:
        raise ValueError("Unexpected SH list markup")
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", area.group(1), re.S | re.I):
        seq = re.search(r"getDetailView\(\s*['\"]?(\d+)['\"]?\s*\)", row)
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)
        if not seq or len(cells) < 4:
            continue
        title = re.sub(r"^NEW\s*", "", _text(re.sub(r'<span\b[^>]*icoNew[^>]*>.*?</span>', " ", cells[1], flags=re.S)))
        rows.append(dict(seq=seq.group(1), title=title, department=_text(cells[2]), registered=_text(cells[3])))
    return rows


def collect_sh(source):
    boards = source.get("boards", ["rent"])
    robot = _robots(SH_BASE + "/", source["domains"])
    result, seen = [], set()
    for board in boards:
        route = sh_list_url(board)
        _require_allowed(robot, route)
        for row in parse_sh_list(fetch(route, source["domains"]).decode("utf-8", "replace"), board):
            title = row["title"]
            # Title words decide only whether a notice is worth reviewing; status stays unverified.
            # The same notice is cross-posted on several boards; keep the first board's URL.
            if not title or row["seq"] in seen or SH_CLOSED.search(title) or not SH_OPEN.search(title):
                continue
            seen.add(row["seq"])
            url = sh_detail_url(board, row["seq"])
            if official(url, source["domains"]) and allowed(robot, url, AGENT):
                result.append(dict(source=source["id"], url=url, title=f"[SH {SH_BOARDS[board][2]}] {title}"[:240],
                                   summary=CANDIDATE, needs_recheck=True))
    if not result:
        raise ValueError("No open-looking SH notices; manual review required")
    return result


# --- 공유누리 (eshare.go.kr) public resources ---------------------------------------------
ESHARE_BASE = "https://www.eshare.go.kr"
ESHARE_BOOTSTRAP = ESHARE_BASE + "/UserPortal/adv/unifdSearch/UnifiedSearchMainView.do"
ESHARE_SEARCH = ESHARE_BASE + "/UserPortal/adv/unifdSearch/ConditionsSearch.do"
ESHARE_DETAIL_PATHS = {
    "001": "Upv/UprResrcGym", "002": "Upv/UprResrcFacl", "098": "Upv/UprResrcFacl",
    "003": "Upv/UprResrcCamp", "004": "Upv/UprResrcEqp", "005": "Upv/UprResrcGds",
    "006": "Upv/UprResrcEdu", "007": "Upv/UprResrcExpr", "008": "Upv/UprResrcPfm",
    "009": "Upv/UprResrcEvnt",
}


def eshare_detail_url(rsrc_dcd, rsrc_no):
    path = ESHARE_DETAIL_PATHS.get(rsrc_dcd[7:10])
    if not path:
        return None
    return f"{ESHARE_BASE}/UserPortal/{path}/index.do?rsrc_no={quote(rsrc_no)}&rsrc_dcd={quote(rsrc_dcd)}"


def parse_eshare(fragment):
    fragment = fragment.replace("<!HS>", "").replace("<!HE>", "")
    items = []
    for block in re.split(r"<li>\s*<!--\s*이미지영역", fragment)[1:]:
        block = re.sub(r'<span class="sr-only">.*?</span>', "", block, flags=re.S)
        ident = re.search(r"fnNewPageResourceDetail\('([^']+)',\s*'([^']+)'\)", block)
        title = re.search(r'<a class="sbj_txt"[^>]*>(.*?)</a>', block, re.S)
        if not ident or not title:
            continue
        text = _text(block)
        fee = re.search(r"이용 요금\s+(.*?)(?:자원 분류|위치 정보|지도 보기|예약·문의하기|$)", text)
        place = re.search(r"위치 정보\s+(.*?)(?:자원 분류|이용 요금|지도 보기|예약·문의하기|$)", text)
        items.append(dict(rsrc_dcd=ident.group(1), rsrc_no=ident.group(2), title=_text(title.group(1)),
                          fee=fee.group(1).strip() if fee else "", place=place.group(1).strip() if place else ""))
    return items


def _post(opener, url, data, domains, referer):
    if not official(url, domains):
        raise ValueError("Unapproved URL")
    cost_policy.budget.consume()
    request = urllib.request.Request(url, data=urlencode(data).encode(), headers={
        "User-Agent": AGENT, "Referer": referer, "X-Requested-With": "XMLHttpRequest"})
    with opener.open(request, timeout=15) as response:
        body = response.read(LIMIT + 1)
    if len(body) > LIMIT:
        raise ValueError("Response too large")
    return body.decode("utf-8", "replace")


def collect_eshare(source):
    robot = _robots(ESHARE_BASE + "/", source["domains"])
    for url in (ESHARE_BOOTSTRAP, ESHARE_SEARCH):
        _require_allowed(robot, url)
    # The search endpoint requires the session cookie set by the public search page.
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()), Redirect(source["domains"]))
    cost_policy.budget.consume()
    with opener.open(urllib.request.Request(ESHARE_BOOTSTRAP, headers={"User-Agent": AGENT}), timeout=15) as response:
        response.read(LIMIT)
    result = []
    for query in source.get("queries", []):
        payload = dict(searchWrd=query["keyword"], sort="RANK", order="DESC", pageIndex="1",
                       collection="resource_cate1", viewType="UnitPage", ctrd=query.get("ctrd", "11"))
        # Infrastructure is free; resource participation fees do not restrict discovery.
        if query.get("reservable"):
            payload["intnet_rsrv_psbl_yn"] = "Y"
        for row in parse_eshare(_post(opener, ESHARE_SEARCH, payload, source["domains"], ESHARE_BOOTSTRAP)):
            url = eshare_detail_url(row["rsrc_dcd"], row["rsrc_no"])
            if url and official(url, source["domains"]) and allowed(robot, url, AGENT):
                title = row["title"] + (" · " + row["place"] if row["place"] else "")
                result.append(dict(source=source["id"], url=url, title=f"[공유누리] {title}"[:240],
                                   summary=CANDIDATE, needs_recheck=True))
    if not result:
        raise ValueError("No Sharenuri resources found; manual review required")
    return result


# --- 국가유산청 monthly heritage events ---------------------------------------------------
HERITAGE_EVENTS = "https://www.khs.go.kr/cha/openapi/selectEventListOpenapi.do"


def parse_heritage_events(body):
    root = ET.fromstring(body)
    if root.tag.rsplit("}", 1)[-1] != "result":
        raise ValueError("Unexpected heritage event XML")
    rows = []
    for item in root.findall("./item"):
        value = lambda name: _text((item.findtext(name) or "").replace("<br>", " "))
        rows.append(dict(title=value("subTitle"), url=value("subPath"), sido=value("sido"),
                         gugun=value("gugun"), start=value("sDate"), end=value("eDate")))
    return rows


def collect_heritage(source, now):
    robot = _robots(HERITAGE_EVENTS, source["domains"])
    result, seen = [], set()
    months = [(now.year, now.month)]
    if source.get("include_next_month"):
        months.append((now.year + (now.month == 12), now.month % 12 + 1))
    for year, month in months:
        route = f"{HERITAGE_EVENTS}?searchYear={year}&searchMonth={month}"
        _require_allowed(robot, route)
        for row in parse_heritage_events(fetch(route, source["domains"])):
            region = row["sido"] + " " + row["gugun"]
            if source.get("regions") and not any(r in region for r in source["regions"]):
                continue
            # Event links can point to other heritage sites; keep only allow-listed official hosts.
            same_host = urlsplit(row["url"]).hostname == urlsplit(HERITAGE_EVENTS).hostname
            if (row["title"] and official(row["url"], source["domains"]) and row["url"] not in seen
                    and (not same_host or allowed(robot, row["url"], AGENT))):
                seen.add(row["url"])
                result.append(dict(source=source["id"], url=row["url"], title=f"[국가유산] {row['title']}"[:240],
                                   summary=CANDIDATE, needs_recheck=True))
    if not result:
        raise ValueError("No linkable heritage events in configured regions; manual review required")
    return result


def collect(source, now):
    kind = source["collector"]
    if kind == "sh_notice":
        return collect_sh(source)
    if kind == "eshare":
        return collect_eshare(source)
    if kind == "heritage_events":
        return collect_heritage(source, now)
    raise ValueError("Unknown collector")
