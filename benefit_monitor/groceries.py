"""Grocery reference prices for the "장보기 시세" section.

Approved 2026-11-09 as a separate display channel, like the festival section: official
average retail prices are shown as published and never enter the verified benefit list,
review queue, AI research or topic cards.

- KAMIS (aT 농산물유통정보) 부류별 일간 소매가격: one page lists produce, grains, fish and
  some processed foods with 당일/1일전/1주일전/2주일전/1년전/평년 columns.
- 축산물품질평가원 지역별 평균 소비자가격: one page per (species, cut); 16 regions and the
  national average. Its survey method changed on 2026-07-01, so there is no 평년 for meat.
"""
from datetime import date, datetime, timedelta
import html as htmlmod
import re
from urllib.parse import urlencode

from .collectors.rss import AGENT, fetch
from .robots import allowed

KAMIS = "https://www.kamis.or.kr"
KAMIS_DAILY = KAMIS + "/customer/price/agricultureRetail/catalogue.do"
EKAPE = "https://www.ekapepia.com"
EKAPE_REGION = EKAPE + "/v3/hereMeat/regionAvgPrice.do"
NOTICE = ("KAMIS(aT)·축산물품질평가원이 조사한 전국 평균 소매가격입니다. 매장·산지·규격에 따라 실제 가격은 다르며, "
          "사람 검증 전 공식 게시값을 그대로 옮겼습니다.")
PRICE_KEYS = ("today", "day_ago", "week_ago", "two_weeks_ago", "year_ago", "normal")
PRODUCE_FIELDS = ("id", "item", "kind", "unit", "grade") + PRICE_KEYS
PRODUCE_LIMITS = {"item": 40, "kind": 60, "unit": 20, "grade": 10}
MEAT_FIELDS = ("id", "cut", "label", "unit", "national", "seoul", "min", "min_region", "max", "max_region")
MEAT_LIMITS = {"cut": 30, "label": 40}
REGIONS = ("서울", "부산", "대구", "인천", "전남광주", "대전", "울산", "세종", "경기", "강원", "충북", "충남",
           "전북", "경북", "경남", "제주")
UNITS = ("원/100g", "원/kg", "원/30구", "원/10구", "원/마리")
MAX_PRICE = 10_000_000
SURVEY_MAX_AGE_DAYS = 7


def _cell(raw):
    return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", raw)).split())


def _price(text):
    """'1,893' -> 1893, '-' -> None, anything else -> ValueError (never guessed)."""
    if text in ("-", ""):
        return None
    if not re.fullmatch(r"\d{1,3}(,\d{3})*|\d+", text):
        raise ValueError("unexpected price cell")
    value = int(text.replace(",", ""))
    if not 0 < value <= MAX_PRICE:
        raise ValueError("price out of range")
    return value


def _rows(table):
    return [[_cell(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, flags=re.S)]
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.S)]


def parse_kamis(page):
    """(survey_date, items) from the KAMIS 부류별 일간 page; (None, []) when no survey that day."""
    match = re.search(r'class="txt_date">\s*(\d{4})\.(\d{2})\.(\d{2})\s*기준', page)
    table = re.search(r'<table[^>]*summary="소매가격전체부류별/일간 가격정보"[^>]*>(.*?)</table>', page, flags=re.S)
    if not match or not table:
        return None, []
    rows = _rows(table.group(1))
    if not rows or rows[0][:4] != ["품목", "품종", "단위", "등급"] or len(rows[0]) != 10 \
            or not rows[0][4].startswith("당일") or rows[0][9] != "평년":
        return None, []
    items, seen = [], set()
    for cells in rows[1:]:
        if len(cells) != 10 or not all(cells[:3]):
            continue
        try:
            prices = dict(zip(PRICE_KEYS, (_price(c) for c in cells[4:])))
        except ValueError:
            continue
        item = dict(zip(("item", "kind", "unit", "grade"), cells[:4]))
        if any(not _text_ok(item[k], n, allow_empty=k == "grade") for k, n in PRODUCE_LIMITS.items()):
            continue
        item["id"] = "|".join(cells[:4])
        if item["id"] in seen or (prices["today"] is None and prices["day_ago"] is None):
            continue
        seen.add(item["id"])
        items.append({k: (item | prices)[k] for k in PRODUCE_FIELDS})
    return date(*map(int, match.groups())).isoformat(), items


def parse_meat(page, cut, day=None):
    """Main rows of the 축평원 regional table; marbling sub rows (근내지방도 7/8/9) are skipped.

    With day, the page must echo that day in its date field, so a default or fallback page is
    never labelled with a survey day it does not show.
    """
    if day is not None:
        echoed = re.search(r'id="searchStartDate"\s+value="(\d{4}-\d{2}-\d{2})"', page)
        if not echoed or echoed.group(1) != day:
            return []
    unit = re.search(r"단위\s*:\s*(원/[^)\s<]+)\)", page)
    table = re.search(r'<table[^>]*summary="지역별 소비자가격 평균 테이블"[^>]*>(.*?)</table>', page, flags=re.S)
    if not unit or not table:
        return []
    unit = unit.group(1).replace("Kg", "kg").replace("KG", "kg")
    rows = _rows(table.group(1))
    if unit not in UNITS or not rows or tuple(rows[0][1:-1]) != REGIONS or rows[0][-1] != "전국 평균":
        return []
    items, seen = [], set()
    for cells in rows[1:]:
        label = cells[0] if cells else ""
        if label in seen:
            continue
        if len(cells) != len(REGIONS) + 2 or not label or label.isdigit() or "지방도" in label \
                or len(label) > MEAT_LIMITS["label"]:
            continue
        try:
            values = [_price(c) for c in cells[1:]]
        except ValueError:
            continue
        regional = [(v, r) for v, r in zip(values[:-1], REGIONS) if v is not None]
        if values[-1] is None or not regional:
            continue
        seen.add(label)
        # Ties go to the first region in the official column order.
        low, high = min(regional, key=lambda x: x[0]), max(regional, key=lambda x: x[0])
        items.append(dict(id=f"{cut['species']}-{cut['part']}-{label}", cut=cut["name"], label=label, unit=unit,
                          national=values[-1], seoul=values[0], min=low[0], min_region=low[1],
                          max=high[0], max_region=high[1]))
    return items


def _robots(base, url, domains):
    text = fetch(base + "/robots.txt", domains).decode("utf-8", "replace")
    if not allowed(text, url, AGENT):
        raise ValueError("robots disallows collection")


def _cuts(source):
    cuts = source.get("cuts", [])
    if not isinstance(cuts, list) or len(cuts) > 20 or any(
            not isinstance(c, dict) or not re.fullmatch(r"\d{4}", str(c.get("species", "")))
            or not re.fullmatch(r"\d{2}", str(c.get("part", ""))) or not isinstance(c.get("name"), str)
            or not 0 < len(c["name"]) <= MEAT_LIMITS["cut"] for c in cuts):
        raise ValueError("grocery cuts must be [{species:'4304', part:'27', name:'...'}]")
    return cuts


def _collect_produce(now, lookback, domains):
    _robots(KAMIS, KAMIS_DAILY, domains)
    # The daily run starts after midnight, so the newest possible survey is yesterday's.
    # Weekends and holidays have no table; step back one day at a time.
    for back in range(1, lookback + 1):
        day = (now.date() - timedelta(days=back)).isoformat()
        page = fetch(KAMIS_DAILY + "?" + urlencode(dict(action="daily", regday=day, convert_kg_yn="N")), domains)
        survey, items = parse_kamis(page.decode("utf-8", "replace"))
        # The page labels its own survey day; a future day or one outside the window is never used.
        if items and day >= survey >= (now.date() - timedelta(days=lookback)).isoformat():
            return dict(survey_date=survey, items=items)
    return None


MEAT_LOOKBACK_DAYS = 3


def _meat_page(cut, day, domains):
    page = fetch(EKAPE_REGION + "?" + urlencode(dict(searchStartDate=day, searchEndDate=day,
                                                      searchCondition1=cut["species"],
                                                      searchCondition2=cut["part"])), domains)
    return parse_meat(page.decode("utf-8", "replace"), cut, day)


def _collect_meat(now, cuts, domains):
    _robots(EKAPE, EKAPE_REGION, domains)
    items, missing, day = [], [], None
    # Find the newest surveyed day with the first cut (holidays can be empty), then use it for all.
    for back in range(1, MEAT_LOOKBACK_DAYS + 1):
        candidate = (now.date() - timedelta(days=back)).isoformat()
        try:
            rows = _meat_page(cuts[0], candidate, domains)
        except RuntimeError:
            raise
        except Exception:
            rows = []
        if rows:
            day = candidate
            items.extend(rows)
            break
    if day is None:
        return None
    for index, cut in enumerate(cuts[1:], start=1):
        try:
            rows = _meat_page(cut, day, domains)
        except RuntimeError:  # budget exhausted: name every remaining cut as missing
            missing.extend(c["name"] for c in cuts[index:])
            break
        except Exception:
            rows = []
        if rows:
            items.extend(rows)
        else:
            missing.append(cut["name"])
    return dict(survey_date=day, items=items, missing=missing)


def collect(source, now):
    domains = source["domains"]
    cuts = _cuts(source)
    lookback = source.get("lookback_days", 5)
    if type(lookback) is not int or not 1 <= lookback <= 7:
        raise ValueError("lookback_days must be 1..7")
    produce, produce_error = None, None
    try:
        produce = _collect_produce(now, lookback, domains)
    except Exception as e:  # KAMIS down or budget exhausted: meat can still be shown
        produce_error = e
    meat = None
    if cuts:
        try:
            meat = _collect_meat(now, cuts, domains)
        except Exception as e:
            if produce is None:
                raise ValueError("No grocery prices in official listings; manual review required") from (produce_error or e)
    if produce is None and meat is None:
        raise ValueError("No grocery prices in official listings; manual review required")
    return dict(schema_version=1, source="groceries", fetched_at=now.isoformat(), notice=NOTICE,
                produce=produce, meat=meat)


def _text_ok(value, limit, allow_empty=False):
    return isinstance(value, str) and (allow_empty or len(value) > 0) and len(value) <= limit \
        and not re.search(r"[<>\x00-\x1f]", value)


def _price_ok(value, required=False):
    if value is None:
        return not required
    return type(value) is int and 0 < value <= MAX_PRICE


def _survey(section, now):
    survey = date.fromisoformat(section["survey_date"])
    if survey.isoformat() != section["survey_date"] or survey > now.date():
        raise ValueError("bad survey date")
    return (now.date() - survey).days <= SURVEY_MAX_AGE_DAYS


def _clean_produce(section, now):
    if section is None:
        return None
    if not isinstance(section, dict) or set(section) != {"survey_date", "items"} or not isinstance(section["items"], list) \
            or not 0 < len(section["items"]) <= 400:
        raise ValueError("bad produce section")
    if not _survey(section, now):
        return None
    for row in section["items"]:
        if not isinstance(row, dict) or set(row) != set(PRODUCE_FIELDS):
            raise ValueError("bad produce row")
        if any(not _text_ok(row[k], n, allow_empty=k == "grade") for k, n in PRODUCE_LIMITS.items()) \
                or row["id"] != "|".join((row["item"], row["kind"], row["unit"], row["grade"])) \
                or not all(_price_ok(row[k]) for k in PRICE_KEYS) or (row["today"] is None and row["day_ago"] is None):
            raise ValueError("bad produce row")
    return dict(survey_date=section["survey_date"], items=[dict(r) for r in section["items"]])


def _clean_meat(section, now):
    if section is None:
        return None
    if not isinstance(section, dict) or set(section) != {"survey_date", "items", "missing"} \
            or not isinstance(section["items"], list) or not 0 < len(section["items"]) <= 100 \
            or not isinstance(section["missing"], list) or len(section["missing"]) > 20 \
            or not all(_text_ok(m, MEAT_LIMITS["cut"]) for m in section["missing"]):
        raise ValueError("bad meat section")
    if not _survey(section, now):
        return None
    for row in section["items"]:
        if not isinstance(row, dict) or set(row) != set(MEAT_FIELDS):
            raise ValueError("bad meat row")
        if any(not _text_ok(row[k], n) for k, n in MEAT_LIMITS.items()) or row["unit"] not in UNITS \
                or row["min_region"] not in REGIONS or row["max_region"] not in REGIONS \
                or not re.fullmatch(r"\d{4}-\d{2}-.+", str(row["id"])) or not row["id"].endswith("-" + row["label"]) \
                or not all(_price_ok(row[k], True) for k in ("national", "min", "max")) or not _price_ok(row["seoul"]) \
                or row["min"] > row["max"]:
            raise ValueError("bad meat row")
    return dict(survey_date=section["survey_date"], items=[dict(r) for r in section["items"]],
                missing=list(section["missing"]))


def sanitize(bundle, now):
    """Re-check a stored or remote bundle field by field; None when unusable today."""
    try:
        if not isinstance(bundle, dict) or bundle.get("schema_version") != 1 or bundle.get("source") != "groceries" \
                or set(bundle) != {"schema_version", "source", "fetched_at", "notice", "produce", "meat"}:
            return None
        fetched = datetime.fromisoformat(bundle["fetched_at"])
        if fetched.tzinfo is None or fetched > now or now - fetched > timedelta(hours=30):
            return None
        produce, meat = _clean_produce(bundle["produce"], now), _clean_meat(bundle["meat"], now)
        if produce is None and meat is None:
            return None
        return dict(schema_version=1, source="groceries", fetched_at=fetched.isoformat(), notice=NOTICE,
                    produce=produce, meat=meat)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
