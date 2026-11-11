"""Link official discount events (public benefit items) to grocery basket items.

Approved 2026-11-11: a card shows an event only when the event has a confirmed fixed start and end
date, is running today (KST) and names the basket item or a clear item group. Anything vague is not
linked; the event stays in the benefits tab only.

Clause rule (2026-11-11 review): title, summary and conditions are each split into sentences at a
period/?/! that follows a Hangul character, '%' or ')', at ';' and at line breaks. '·' is NOT a boundary because it
joins lists (한우·수산물, 대형마트·SSM). A basket item links only from the sentences that name it, and the
discount and stores are read from those sentences only (no whole-text fallback: another sentence may
describe another item's stores). If any of those sentences states a month/day other than the item's
start or end date, the item has its own period there and is not linked. Two or more different discount
expressions in them give no discount (the link still shows title and dates). The start month/day must
appear somewhere in the item text, so an unstated start is never trusted. When the text says periods
differ by item (기간이 다르며, 기간 상이, 기간 별도), an item links only if its own sentence states both
the link's start and end month/day (the item's own end, not the display_until-capped one).

Review fixes (2026-11-11): item names/aliases need a left word boundary (배추 is not in 양배추); 수산물
after 농/축 is broad wording; a clause naming pork never links a beef item unless it names beef too;
2026.11.07 is a date but 1.5kg / 11.7% are not; recompute() rebuilds links after a takedown or snapshot
redeploy instead of keeping stored lines.
"""
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

DISCOUNT_WORDS = ("할인", "세일", "수산대전", "농할", "반값", "특별판매")
GROUP_WORDS = (
    (("수산물", "수산식품"), ("mackerel", "squid")),
    (("한우", "소고기"), ("hanwoo_sirloin", "us_short_rib")),
    (("한돈", "돼지고기"), ("pork_belly", "pork_neck", "pork_shoulder")),
    (("닭", "닭고기"), ("chicken",)),
    (("계란", "달걀"), ("egg_tray",)),
    (("채소",), None),  # every basket item whose group is 채소
)
# Broad wording (농축산물, 전 품목, 농산물) is deliberately absent: it is never a target, so an event
# that names only that links to nothing.
GOVERNMENT_SOURCES = frozenset({"government", "mof_press"})
ORIGIN_ONLY_WORDS = frozenset({"미국산", "수입", "수입산", "국산", "국내산", "호주산"})  # never match directly
IMPORT_IDS = frozenset({"us_short_rib", "banana"})
MAX_LINKS = 100
LINK_KEYS = {"basket_id", "title", "discount", "stores", "start", "end", "url"}
BUNDLE_KEYS = {"schema_version", "source", "generated_at", "links"}

# Ranges stay verbatim (20~30% 할인); a leading digit or comma never starts a match (no '000원 할인').
_DISCOUNT_PERCENT = re.compile(r"(?<![\d~])(?:최대\s*\d{1,2}(?:\s*~\s*\d{1,2})?\s*%|\d{1,2}(?:\s*~\s*\d{1,2})?\s*%\s*할인)")
_DISCOUNT_WON = re.compile(r"(?<![\d,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:만)?\s*원\s*(?:할인|환급)")
_LIMIT_WON = re.compile(r"(?<![\d,])(?:\d{1,3}(?:,\d{3})+|\d+)(?:만)?\s*원\s*한도")  # a cap, shown only when no discount
_CLAUSE_SPLIT = re.compile(r"(?<=[가-힣%)])[.!?](?=\s|$)|[;\n]")
# 11월 7일 / 11월2~15일 (day-only end) / 11.7 / 11. 7. / 11/7
_MONTH_DAY = re.compile(r"(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일?(?:\s*~\s*(\d{1,2})\s*일)?")
_VARYING_PERIOD = re.compile(r"기간[이은]?\s*(?:다르|다름|상이|별도)")
# 2026.11.07 / 2026. 11. 7. (year first); read before the short forms and then removed from the text.
_FULL_DAY = re.compile(r"(?<!\d)\d{4}\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})(?!\d)\.?")
# A number followed by a unit or % is a decimal (1.5kg, 2.5배, 11.7%), never a date.
_NUMERIC_DAY = re.compile(r"(?<![\d.,/])(\d{1,2})\s*[./]\s*(\d{1,2})(?![\d,]|\s*(?:kg|g|배|%|원|만|개|마리|리터|L))", re.I)
# Words that also start unrelated words: 닭갈비, 한우리 are not the chicken or hanwoo items.
# 수산물 inside 농수산물/농축수산물 is broad wording (every food), not seafood.
_WORD_PATTERNS = {"닭": r"닭(?:고기)?(?![가-힣])", "닭고기": r"닭고기", "한우": r"한우(?!리)",
                  "수산물": r"(?<![농축])수산물", "수산식품": r"(?<![농축])수산식품"}
# Item names and aliases must start a word: 배추 in 양배추, 호박 in 단호박, 갈비살 in 돼지갈비살 are other items.
_LEFT = r"(?<![가-힣])"
_PORK = re.compile(r"돼지|한돈|돈육")
_BEEF = re.compile(r"한우(?!리)|소고기|쇠고기")
BEEF_IDS = frozenset({"hanwoo_sirloin", "us_short_rib"})
_STORES = re.compile(r"대형마트|SSM|슈퍼|하나로마트|전통시장|온라인몰|온라인")
# "국산" inside 미국산/중국산/외국산 is not a domestic marker.
_DOMESTIC = re.compile(r"(?<![미중외])국산|국내산|우리(?= |$)|한우(?!리)|한돈")


def _has(word, text):
    return re.search(_WORD_PATTERNS.get(word, re.escape(word)), text) is not None


def _public(item):
    """Nationwide government/ministry events only: never retail, district or regional items."""
    labels = item.get("labels")
    region = labels.get("region") if isinstance(labels, dict) else None
    if region is not None and not (isinstance(region, str) and region.startswith("전국")):
        return False  # human items use free text such as '전국 참여 유통업체'
    return item.get("source") in GOVERNMENT_SOURCES and not item.get("districts")


def _clauses(item):
    out = []
    for key in ("title", "summary", "conditions"):
        value = item.get(key)
        if isinstance(value, str):
            out += [c.strip() for c in _CLAUSE_SPLIT.split(value) if c.strip()]
    return out


def _days(text):
    """(month, day) pairs written in text; impossible ones are kept so they still count as 'other'."""
    found = set()
    for m in _FULL_DAY.finditer(text):
        found.add((int(m.group(1)), int(m.group(2))))
    text = _FULL_DAY.sub(" ", text)
    for m in _MONTH_DAY.finditer(text):
        month = int(m.group(1))
        found.add((month, int(m.group(2))))
        if m.group(3):
            found.add((month, int(m.group(3))))
    for m in _NUMERIC_DAY.finditer(text):
        found.add((int(m.group(1)), int(m.group(2))))
    return found


def _discount(clauses):
    """The one discount the clauses state, None when there is none or more than one."""
    joined = " ".join(clauses)
    found = {re.sub(r"\s+", "", m.group(0)): m.group(0)
             for rx in (_DISCOUNT_PERCENT, _DISCOUNT_WON) for m in rx.finditer(joined)}
    if not found:
        found = {re.sub(r"\s+", "", m.group(0)): m.group(0) for m in _LIMIT_WON.finditer(joined)}
    return next(iter(found.values())) if len(found) == 1 else None


def _kst_today(now):
    return (now.astimezone(ZoneInfo("Asia/Seoul")) if now.tzinfo else now).date()


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def _targets(text, basket):
    ids = {b["id"] for b in basket}
    found = set()
    for item in basket:
        words = [item["name"]] + [a for a in item["aliases"]]
        # One-character aliases (무, 파, 쌀) match inside unrelated words, so they never link directly.
        if any(len(w) >= 2 and w not in ORIGIN_ONLY_WORDS
               and re.search(_LEFT + _WORD_PATTERNS.get(w, re.escape(w)), text) for w in words):
            found.add(item["id"])
    for words, wanted in GROUP_WORDS:
        if any(_has(w, text) for w in words):
            if wanted is None:
                found |= {b["id"] for b in basket if b["group"] == "채소"}
            else:
                found |= set(wanted) & ids
    if _DOMESTIC.search(text):
        found -= IMPORT_IDS
    if _PORK.search(text) and not _BEEF.search(text):
        found -= BEEF_IDS  # '돼지 등심', '한돈 갈비살' are pork cuts
    return found


def _until(item):
    """KST date of display_until, None when absent; raises ValueError when it is malformed."""
    value = item.get("display_until")
    if value is None:
        return None
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("naive display_until")
    return _kst_today(moment)


def link(items, basket, today):
    """Links for events running on `today`, sorted by basket_id then end date."""
    out, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("validity_kind") != "fixed" or not _public(item):
            continue
        start, end = _date(item.get("valid_from")), _date(item.get("valid_until"))
        own_end = end
        url, title = item.get("url"), item.get("title")
        try:
            until = _until(item)
        except (TypeError, ValueError):
            continue
        if until is not None and end is not None:
            end = min(end, until)
        if start is None or end is None or not start <= today <= end \
                or not isinstance(url, str) or not _short(title, 200):
            continue  # a title sanitize would reject is skipped here, never rewritten
        text = " ".join(str(item.get(k) or "") for k in ("title", "summary", "conditions"))
        if not any(w in text for w in DISCOUNT_WORDS) or (start.month, start.day) not in _days(text):
            continue
        own_days = {(start.month, start.day), (end.month, end.day), (own_end.month, own_end.day)}
        domestic = _DOMESTIC.search(text) is not None
        varying = _VARYING_PERIOD.search(text) is not None
        # The item's own period, not the display_until-capped end shown on the card.
        link_days = {(start.month, start.day), (own_end.month, own_end.day)}
        clauses = _clauses(item)
        naming = {}
        for clause in clauses:
            for basket_id in _targets(clause, basket):
                naming.setdefault(basket_id, []).append(clause)
        for basket_id, mine in naming.items():
            if (domestic and basket_id in IMPORT_IDS) or (basket_id, url) in seen:
                continue
            if any(_days(c) - own_days for c in mine):
                continue  # this item has its own period in the text: ambiguous
            if varying and not any(link_days <= _days(c) for c in mine):
                continue  # periods differ by item and this item's sentence does not state both dates
            seen.add((basket_id, url))
            stores = list(dict.fromkeys(s_ for c in mine for s_ in _STORES.findall(c)))[:3]
            out.append({"basket_id": basket_id, "title": title, "discount": _discount(mine),
                        "stores": "·".join(stores) or None, "start": start.isoformat(), "end": end.isoformat(),
                        "url": url})
    out.sort(key=lambda link_: (link_["basket_id"], link_["end"]))
    return out[:MAX_LINKS]


def recompute(data, now):
    """Links recomputed from the payload's current public items, or None when nothing links.

    Used when a payload is filtered after publishing (admin takedown, approved-snapshot redeploy): a kept
    link must reflect the item as it is now (moved end date, edited region), so links are never carried
    over from the old bundle. Without baselines there is no basket, so nothing links."""
    baselines = data.get("grocery_baselines")
    basket = baselines.get("items") if isinstance(baselines, dict) else None
    if not isinstance(basket, list):
        return None
    bundle = sanitize(dict(schema_version=1, source="grocery_discounts", generated_at=now.isoformat(),
                           links=link(data.get("items") or [], basket, _kst_today(now))), now)
    return bundle if bundle is not None and bundle["links"] else None


def _short(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit and not re.search(r"[<>\x00-\x1f]", value)


def sanitize(bundle, now):
    """Bundle without malformed links and links that are over or not yet started (KST).

    None when the bundle itself is malformed or every link in it is malformed."""
    if not isinstance(bundle, dict) or set(bundle) != BUNDLE_KEYS or bundle["schema_version"] != 1 \
            or bundle["source"] != "grocery_discounts" or not isinstance(bundle["generated_at"], str) \
            or not isinstance(bundle["links"], list) or len(bundle["links"]) > MAX_LINKS:
        return None
    try:
        datetime.fromisoformat(bundle["generated_at"])
    except ValueError:
        return None
    today = _kst_today(now)
    out, valid = [], 0
    for item in bundle["links"]:
        if not isinstance(item, dict) or set(item) != LINK_KEYS:
            continue
        start, end = _date(item["start"]), _date(item["end"])
        if not isinstance(item["basket_id"], str) or not re.fullmatch(r"[a-z_]{2,30}", item["basket_id"]) \
                or not _short(item["title"], 200) or start is None or end is None or start > end \
                or any(item[k] is not None and not _short(item[k], 60) for k in ("discount", "stores")) \
                or not _short(item["url"], 500) or not item["url"].startswith("https://"):
            continue
        valid += 1
        if start <= today <= end:
            out.append(dict(item))
    if bundle["links"] and not valid:
        return None
    return dict(bundle, links=out)
