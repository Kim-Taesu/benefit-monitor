"""Link official discount events (public benefit items) to grocery basket items.

Approved 2026-11-11: a card shows an event only when the event has a confirmed fixed start and end
date, is running today (KST) and names the basket item or a clear item group. Anything vague is not
linked; the event stays in the benefits tab only.
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

_DISCOUNT_PERCENT = re.compile(r"최대\s*\d{1,2}\s*%|\d{1,2}\s*%\s*할인")
_DISCOUNT_WON = re.compile(r"\d+(?:만)?\s*원\s*(?:할인|환급|한도)")
# Words that also start unrelated words: 닭갈비, 한우리 are not the chicken or hanwoo items.
_WORD_PATTERNS = {"닭": r"닭(?:고기)?(?![가-힣])", "닭고기": r"닭고기", "한우": r"한우(?!리)"}
_STORES = re.compile(r"대형마트|SSM|슈퍼|하나로마트|전통시장|온라인몰|온라인")
# "국산" inside 미국산/중국산/외국산 is not a domestic marker.
_DOMESTIC = re.compile(r"(?<![미중외])국산|국내산|우리(?= |$)|한우(?!리)|한돈")


def _has(word, text):
    return re.search(_WORD_PATTERNS.get(word, re.escape(word)), text) is not None


def _public(item):
    """Nationwide government/ministry events only: never retail, district or regional items."""
    labels = item.get("labels")
    region = labels.get("region") if isinstance(labels, dict) else None
    return item.get("source") in GOVERNMENT_SOURCES and not item.get("districts") and region in (None, "전국")


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
        if any(len(w) >= 2 and w not in ORIGIN_ONLY_WORDS and _has(w, text) for w in words):
            found.add(item["id"])
    for words, wanted in GROUP_WORDS:
        if any(_has(w, text) for w in words):
            if wanted is None:
                found |= {b["id"] for b in basket if b["group"] == "채소"}
            else:
                found |= set(wanted) & ids
    if _DOMESTIC.search(text):
        found -= IMPORT_IDS
    return found


def link(items, basket, today):
    """Links for events running on `today`, sorted by basket_id then end date."""
    out, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("validity_kind") != "fixed" or not _public(item):
            continue
        start, end = _date(item.get("valid_from")), _date(item.get("valid_until"))
        url, title = item.get("url"), item.get("title")
        if start is None or end is None or not start <= today <= end \
                or not isinstance(url, str) or not isinstance(title, str):
            continue
        text = " ".join(str(item.get(k) or "") for k in ("title", "summary", "conditions"))
        if not any(w in text for w in DISCOUNT_WORDS):
            continue
        match = _DISCOUNT_PERCENT.search(text) or _DISCOUNT_WON.search(text)
        stores = list(dict.fromkeys(_STORES.findall(text)))[:3]
        for basket_id in _targets(text, basket):
            if (basket_id, url) in seen:
                continue
            seen.add((basket_id, url))
            out.append({"basket_id": basket_id, "title": title, "discount": match.group(0) if match else None,
                        "stores": "·".join(stores) or None, "start": start.isoformat(), "end": end.isoformat(),
                        "url": url})
    out.sort(key=lambda link_: (link_["basket_id"], link_["end"]))
    return out[:MAX_LINKS]


def _short(value, limit):
    return isinstance(value, str) and 0 < len(value) <= limit and not re.search(r"[<>\x00-\x1f]", value)


def sanitize(bundle, now):
    """Bundle without links that are over or not yet started (KST), or None for anything malformed."""
    if not isinstance(bundle, dict) or set(bundle) != BUNDLE_KEYS or bundle["schema_version"] != 1 \
            or bundle["source"] != "grocery_discounts" or not isinstance(bundle["generated_at"], str) \
            or not isinstance(bundle["links"], list) or len(bundle["links"]) > MAX_LINKS:
        return None
    try:
        datetime.fromisoformat(bundle["generated_at"])
    except ValueError:
        return None
    today = _kst_today(now)
    out = []
    for item in bundle["links"]:
        if not isinstance(item, dict) or set(item) != LINK_KEYS:
            return None
        start, end = _date(item["start"]), _date(item["end"])
        if not isinstance(item["basket_id"], str) or not re.fullmatch(r"[a-z_]{2,30}", item["basket_id"]) \
                or not _short(item["title"], 200) or start is None or end is None or start > end \
                or any(item[k] is not None and not _short(item[k], 60) for k in ("discount", "stores")) \
                or not _short(item["url"], 500) or not item["url"].startswith("https://"):
            return None
        if start <= today <= end:
            out.append(dict(item))
    return dict(bundle, links=out)
