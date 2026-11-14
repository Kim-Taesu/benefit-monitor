"""Nationwide festival listings from the Korea Tourism Organization (대한민국 구석구석 축제).

Approved 2026-11-07 as a separate display channel: official listing fields are
shown as published, labelled "사람 검증 전", and never enter the verified benefit
list, review queue, AI research or topic cards.
"""
from datetime import date, datetime, timedelta
import html as htmlmod
import json
import re
import urllib.request
from urllib.parse import urlencode, urlsplit, quote

from . import cost_policy
from .collectors.rss import AGENT, LIMIT, Redirect, fetch
from .robots import allowed
from .validation import official

BASE = "https://korean.visitkorea.or.kr"
LIST_PAGE = BASE + "/kfes/list/wntyFstvlList.do"
LIST_API = BASE + "/kfes/list/selectWntyFstvlList.do"
DETAIL = BASE + "/kfes/detail/fstvlDetail.do?fstvlCntntsId="
PAGE_SIZE = 12
NOTICE = "한국관광공사 '대한민국 구석구석' 게시 정보입니다. 사람 검증 전이며 일정·요금은 바뀔 수 있으니 공식 안내를 확인하세요."
FEES = ("free", "paid", "mixed", "unknown")
FIELDS = ("id", "name", "start", "end", "region", "place", "organizer", "fee_status", "fee_text",
          "discount", "summary", "programs", "homepage", "culture_tourism", "url", "modified")
LIMITS = {"name": 120, "region": 60, "place": 160, "organizer": 80, "fee_text": 200, "discount": 300,
          "summary": 400, "programs": 400, "homepage": 300}
MOBILE = re.compile(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _text(value, limit):
    value = re.sub(r"<br\s*/?>", " ", str(value or ""), flags=re.I)
    value = " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", value)).split())
    value = EMAIL.sub("", MOBILE.sub("", value)).strip()
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def _date(value):
    match = re.fullmatch(r"(\d{4})\.(\d{2})\.(\d{2})", str(value or "").strip())
    return date(*map(int, match.groups())).isoformat() if match else None


def fee_status(text):
    """Classify only explicit words; anything else stays unknown."""
    free, paid = "무료" in text, bool(re.search(r"유료|\d[\d,]*\s*원|입장료(?!\s*무료)", text))
    if free and paid:
        return "mixed"
    return "free" if free else "paid" if paid else "unknown"


def _homepage(raw):
    match = re.search(r'href=["\']([^"\']+)', str(raw or ""))
    url = htmlmod.unescape(match.group(1) if match else str(raw or "")).strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return ""
    return url if len(url) <= LIMITS["homepage"] else ""


# "10월 31일 운정호수공원 일대에서 개최된다": the one day the text says the festival itself is held on.
HELD = re.compile(r"(\d{1,2})월\s*(\d{1,2})일[^.!?。]*?개최(?:된다|한다|됩니다|합니다|되며|하며)")
MONTH_DAY = re.compile(r"\d{1,2}월\s*\d{1,2}일")
# Ranges, repeats, ceremonies and earlier editions: the sentence is then not a plain one-day statement.
NOT_ONE_DAY = re.compile(r"부터|까지|[~∼～]|동안|매주|매일|개막|폐막|점등|전야|기념식|선포|지난|작년|전년")
# In another sentence, a date together with one of these says the festival itself goes on or returns.
GOES_ON = re.compile(r"축제[는가은이]|열린다|열립니다|열리|이어진|이어집|계속|진행|개최")
SIDE_PROGRAMME_DAYS = 7


def main_day(summary, start, end):
    """True when the listing period runs on for a side programme after a one-day festival.

    Approved 2026-11-14: a fireworks festival held on 10/31 was listed to 12/31 because its light
    garden stays lit, so the card showed it as running and linked to the page of the finished day.
    Only an unmistakable text counts: every "…개최된다" sentence names one date, that date is the
    listed start, no other dated sentence says the festival goes on, and the listing runs at least
    SIDE_PROGRAMME_DAYS past it. Anything else keeps the official period."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if (last - first).days < SIDE_PROGRAMME_DAYS:
        return False
    days = set()
    for sentence in re.split(r"(?<=[.!?。])\s+", summary):
        found = HELD.search(sentence)
        if not found:
            if MONTH_DAY.search(sentence) and GOES_ON.search(sentence):
                return False
            continue
        if NOT_ONE_DAY.search(sentence) or len(MONTH_DAY.findall(sentence)) != 1:
            return False
        days.add((int(found.group(1)), int(found.group(2))))
    return days == {(first.month, first.day)}


def parse(row):
    ident = str(row.get("fstvlCntntsId") or "")
    start, end = _date(row.get("fstvlBgngDe")), _date(row.get("fstvlEndDe"))
    name = _text(row.get("cntntsNm"), LIMITS["name"])
    if not ID.fullmatch(ident) or not name or not start or not end or end < start:
        return None
    fee_text = _text(row.get("fstvlUtztFareInfo"), LIMITS["fee_text"])
    # The whole official text is read here, not the shortened summary shown on the card.
    if main_day(_text(row.get("fstvlOutlCn"), 10 ** 6), start, end):
        end = start
    return {
        "id": ident, "name": name, "start": start, "end": end,
        "region": _text(row.get("areaNm"), LIMITS["region"]),
        "place": _text(row.get("dtadr") or row.get("adres"), LIMITS["place"]),
        "organizer": _text(row.get("fstvlAspcsNm"), LIMITS["organizer"]),
        "fee_status": fee_status(fee_text), "fee_text": fee_text,
        "discount": _text(row.get("fstvlDscntInfo"), LIMITS["discount"]),
        "summary": _text(row.get("fstvlOutlCn"), LIMITS["summary"]),
        "programs": _text(row.get("fstvlCrmnCn"), LIMITS["programs"]),
        "homepage": _homepage(row.get("fstvlHmpgUrl")),
        "culture_tourism": row.get("fstvlClCd") == "MF",
        "url": DETAIL + quote(ident),
        "modified": _date(str(row.get("cntntsMdfcnYmd") or "").replace("-", ".")),
    }


def _post(opener, payload, domains):
    if not official(LIST_API, domains):
        raise ValueError("Unapproved URL")
    cost_policy.budget.consume()
    # The page sends a jQuery form post (application/x-www-form-urlencoded), not a JSON body.
    request = urllib.request.Request(LIST_API, data=urlencode(payload).encode(), headers={
        "User-Agent": AGENT, "Referer": LIST_PAGE,
        "X-Requested-With": "XMLHttpRequest"})
    with opener.open(request, timeout=15) as response:
        body = response.read(LIMIT + 1)
    if len(body) > LIMIT:
        raise ValueError("Response too large")
    data = json.loads(body.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("resultList"), list):
        raise ValueError("Unexpected festival list response")
    return data["resultList"]


def select(rows, now, window_days):
    """Ongoing or starting within the window, soonest first, de-duplicated."""
    today = now.date().isoformat()
    until = (now.date() + timedelta(days=window_days)).isoformat()
    result, seen = [], set()
    for row in rows:
        item = parse(row) if isinstance(row, dict) else None
        if item and item["id"] not in seen and item["end"] >= today and item["start"] <= until:
            seen.add(item["id"])
            result.append(item)
    return sorted(result, key=lambda x: (x["start"], x["end"], x["name"]))


def collect(source, now):
    robot = fetch(BASE + "/robots.txt", source["domains"]).decode("utf-8", "replace")
    for url in (LIST_PAGE, LIST_API):
        if not allowed(robot, url, AGENT):
            raise ValueError("robots disallows collection")
    opener = urllib.request.build_opener(Redirect(source["domains"]))
    pages = source.get("pages", 5)
    if type(pages) is not int or not 1 <= pages <= 10:
        raise ValueError("festival pages must be 1..10")
    rows = []
    # A=개최중, B=개최예정. Together they are the whole current listing (2026-11-07: 24+11).
    for when in ("A", "B"):
        for page in range(pages):
            batch = _post(opener, {"startIdx": page * PAGE_SIZE, "searchType": "A", "searchDate": when,
                                   "searchArea": "", "searchCate": "", "locationx": "undefined",
                                   "locationy": "undefined", "filterExcluded": "true"}, source["domains"])
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
    items = select(rows, now, source.get("window_days", 90))
    if not items:
        raise ValueError("No current festivals in official listing; manual review required")
    return {"schema_version": 1, "source": source["id"], "fetched_at": now.isoformat(), "notice": NOTICE, "items": items}


def sanitize(bundle, now):
    """Re-check a stored or remote bundle field by field; returns None when unusable today."""
    try:
        if (not isinstance(bundle, dict) or bundle.get("schema_version") != 1 or bundle.get("source") != "kfes"
                or not isinstance(bundle.get("items"), list) or len(bundle["items"]) > 200):
            return None
        fetched = datetime.fromisoformat(bundle["fetched_at"])
        if fetched.tzinfo is None or fetched > now or now - fetched > timedelta(hours=30):
            return None
        today = now.date().isoformat()
        items = []
        for row in bundle["items"]:
            if not isinstance(row, dict) or set(row) != set(FIELDS):
                return None
            if (not ID.fullmatch(str(row["id"])) or row["url"] != DETAIL + row["id"] or row["fee_status"] not in FEES
                    or type(row["culture_tourism"]) is not bool
                    or any(not isinstance(row[k], str) or len(row[k]) > n for k, n in LIMITS.items())
                    or any(MOBILE.search(row[k]) or EMAIL.search(row[k]) for k in LIMITS)
                    or (row["homepage"] and _homepage(row["homepage"]) != row["homepage"])):
                return None
            for key in ("start", "end") + (("modified",) if row["modified"] is not None else ()):
                if not isinstance(row[key], str) or date.fromisoformat(row[key]).isoformat() != row[key]:
                    return None
            if not row["name"] or row["end"] < row["start"]:
                return None
            if row["end"] >= today:
                items.append(dict(row))
        return {"schema_version": 1, "source": "kfes", "fetched_at": fetched.isoformat(), "notice": NOTICE, "items": items}
    except (KeyError, TypeError, ValueError):
        return None
