"""Basket configuration for the grocery "is this cheap?" quick check (period-average baselines)."""
import re
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from . import groceries

BASKET_MAX = 25
GROUPS = ("고기·알", "채소", "기타")
ITEM_KEYS = {"id", "name", "aliases", "group", "row"}
KAMIS_KEYS = ("itemcategorycode", "itemcode", "kindcode", "productrankcode")
EKAPE_KEYS = ("species", "part", "label")
MAX_REQUESTS = 30
KEEP_DAYS = 30
EKAPE_START = date(2026, 7, 1)  # 축평원 조사 방식 변경일: 이후 기간만 평균에 쓴다
EKAPE_LOOKBACK_DAYS = 3
BASELINE_KEYS = {"avg", "months", "from", "to", "unit", "kind", "grade", "checked_at"}
BUNDLE_KEYS = {"schema_version", "source", "fetched_at", "items"}
OUT_ITEM_KEYS = ITEM_KEYS | {"baseline"}


def _text(value, limit=60):
    return isinstance(value, str) and 0 < len(value) <= limit and not re.search(r"[<>\x00-\x1f]", value)


def _exact(value, keys):
    return isinstance(value, dict) and set(value) == set(keys)


def _item(item):
    if not isinstance(item, dict) or not ITEM_KEYS <= item.keys() or len(item.keys() & {"kamis", "ekape"}) != 1 \
            or not item.keys() <= ITEM_KEYS | {"kamis", "ekape"}:
        raise ValueError("basket item needs id, name, aliases, group, row and exactly one of kamis or ekape")
    if not isinstance(item["id"], str) or not re.fullmatch(r"[a-z_]{2,30}", item["id"]):
        raise ValueError("basket id must match ^[a-z_]{2,30}$")
    aliases = item["aliases"]
    if not _text(item["name"]) or not isinstance(aliases, list) or not 1 <= len(aliases) <= 5 \
            or not all(_text(a) for a in aliases) or item["group"] not in GROUPS:
        raise ValueError("invalid basket name, aliases or group")
    row = item["row"]
    if not _exact(row, ("kind", "id")) or row["kind"] not in ("produce", "meat") or not _text(row["id"], 120):
        raise ValueError("basket row must be {kind: produce|meat, id}")
    if "kamis" in item:
        kamis = item["kamis"]
        if not _exact(kamis, KAMIS_KEYS) or not all(isinstance(v, str) and re.fullmatch(r"[0-9A-Za-z]+", v)
                                                    for v in kamis.values()):
            raise ValueError("kamis codes must be alphanumeric strings")
    else:
        ekape = item["ekape"]
        if not _exact(ekape, EKAPE_KEYS) or not isinstance(ekape["species"], str) \
                or not re.fullmatch(r"\d{4}", ekape["species"]) or not isinstance(ekape["part"], str) \
                or not re.fullmatch(r"\d{2}", ekape["part"]) or not _text(ekape["label"], 40):
            raise ValueError("ekape needs species (4 digits), part (2 digits) and label")


def basket(source):
    """Validated basket items from the groceries source config; ValueError on any malformed entry."""
    items = source.get("basket") if isinstance(source, dict) else None
    if not isinstance(items, list) or not 0 < len(items) <= BASKET_MAX:
        raise ValueError("basket must be a list of 1..%d items" % BASKET_MAX)
    for item in items:
        _item(item)
    if len({i["id"] for i in items}) != len(items):
        raise ValueError("basket ids must be unique")
    return items


_KAMIS_HEAD = re.compile(r"/\s*[^/,]+/\s*([^,]+?)\s*,\s*등급\s*:\s*(\S+)\s*,\s*단위\s*:\s*(\S+)\s*기준")


def _complete_months(today):
    """The 12 calendar months before today's month, oldest first, as (year, month)."""
    year, month = today.year, today.month
    out = []
    for _ in range(12):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        out.append((year, month))
    return out[::-1]


def parse_kamis_monthly(page, today):
    """Mean of the last 12 complete months from a KAMIS 기간별/월간 page, or None.

    Months shown as '-' are skipped; the current month is never used. unit/kind/grade are the 단위,
    품종 and 등급 printed in the page heading (None when absent) so callers can check them against
    the basket row they price. A malformed price cell makes the whole page None.
    """
    table = re.search(r"<table[^>]*>(.*?)</table>", page, flags=re.S)
    if not table:
        return None
    rows = groceries._rows(table.group(1))
    if not rows or not rows[0] or not rows[0][0].startswith("구분"):
        return None
    years = {}
    for index, head in enumerate(rows[0][1:], start=1):
        match = re.fullmatch(r"(\d{4})년?", head)
        if match:
            years[int(match.group(1))] = index
    if not years:
        return None
    values = {}
    for cells in rows[1:]:
        match = re.fullmatch(r"(\d{1,2})월", cells[0]) if cells else None
        if not match or not 1 <= int(match.group(1)) <= 12:
            continue
        for year, index in years.items():
            if index >= len(cells):
                continue
            try:
                price = groceries._price(cells[index])
            except ValueError:
                return None
            if price is not None:
                values[(year, int(match.group(1)))] = price
    used = [(ym, values[ym]) for ym in _complete_months(today) if ym in values]
    if not used:
        return None
    head = _KAMIS_HEAD.search(" ".join(re.sub(r"<[^>]+>", " ", page[:table.start()]).split()))
    kind, grade, unit = head.groups() if head else (None, None, None)
    return {"avg": round(sum(v for _, v in used) / len(used)), "months": len(used),
            "from": "%04d-%02d" % used[0][0], "to": "%04d-%02d" % used[-1][0],
            "unit": unit, "kind": kind, "grade": grade}


def parse_ekape_range(page, label, start, end):
    """National mean over start..end from a 축평원 regional page fetched for that range, or None.

    The page must echo exactly start/end in its date inputs (a clamped or default page is None).
    The table is the same as the one-day page, so groceries.parse_meat does the cell checks.
    """
    months = (end - start).days // 30
    if months < 1:
        return None
    echoed = [re.search(r'id="%s"\s+value="(\d{4}-\d{2}-\d{2})"' % name, page)
              for name in ("searchStartDate", "searchEndDate")]
    if not all(echoed) or (echoed[0].group(1), echoed[1].group(1)) != (start.isoformat(), end.isoformat()):
        return None
    rows = groceries.parse_meat(page, {"species": "", "part": "", "name": ""})
    row = next((r for r in rows if r["label"] == label), None)
    if row is None:
        return None
    return {"avg": row["national"], "months": months, "from": start.strftime("%Y-%m"),
            "to": end.strftime("%Y-%m"), "unit": row["unit"], "kind": None, "grade": None}


def _kst_today(now):
    return (now.astimezone(ZoneInfo("Asia/Seoul")) if now.tzinfo else now).date()


def _norm(text):
    return re.sub(r"\s+", "", text).lower()


def _produce_matches(row_id, parsed):
    """True when the page's 단위/등급/품종 agree with the basket row it is meant to price."""
    parts = row_id.split("|")
    if len(parts) != 4 or parsed["unit"] != parts[2]:
        return False
    if parsed["grade"] is not None and parsed["grade"] != parts[3]:
        return False
    kind = parsed["kind"]
    return kind is None or kind == parts[1] or _norm(parts[1]) in _norm(kind)


class _Requests:
    """Counts this run's requests and stops at MAX_REQUESTS like an exhausted budget."""

    def __init__(self, domains):
        self.domains, self.used = domains, 0

    def get(self, url):
        if self.used >= MAX_REQUESTS:
            raise RuntimeError("grocery baseline request cap reached")
        self.used += 1
        return groceries.fetch(url, self.domains)


def _kamis_url(item, today):
    return groceries.KAMIS_DAILY + "?" + urlencode(dict(action="monthly", yyyy=today.year, period=3,
                                                         convert_kg_yn="N", **item["kamis"]))


def _ekape_url(item, start, end):
    return groceries.EKAPE_REGION + "?" + urlencode(dict(
        searchStartDate=start.isoformat(), searchEndDate=end.isoformat(),
        searchCondition1=item["ekape"]["species"], searchCondition2=item["ekape"]["part"]))


def collect(source, now, previous):
    """Weekly period-average baselines for the basket. Raises only on robots refusal or a malformed basket.

    A fetch/parse failure or exhausted budget keeps that item's previous baseline (and its checked_at);
    a page whose unit/grade/kind disagrees with the basket row gives None (the config is wrong).
    """
    items = basket(source)
    domains = source["domains"]
    today = _kst_today(now)
    checked = today.isoformat()
    kept = sanitize(previous, now)
    prev = {i["id"]: i["baseline"] for i in kept["items"]} if kept else {}
    requests = _Requests(domains)
    for base, url in ((groceries.KAMIS, groceries.KAMIS_DAILY), (groceries.EKAPE, groceries.EKAPE_REGION)):
        requests.used += 1
        groceries._robots(base, url, domains)
    result = {}
    start = max(EKAPE_START, today - timedelta(days=365))
    ekape_end, day_searched = None, False

    def stamp(parsed):
        return dict(parsed, checked_at=checked)

    for item in items:
        try:
            if "kamis" in item:
                page = requests.get(_kamis_url(item, today)).decode("utf-8", "replace")
                parsed = parse_kamis_monthly(page, today)
                if parsed is not None:
                    result[item["id"]] = stamp(parsed) if _produce_matches(item["row"]["id"], parsed) else None
                continue
            label = item["ekape"]["label"]
            if ekape_end is None:
                if day_searched:
                    continue  # no survey day found: keep previous values
                day_searched = True
                for back in range(1, EKAPE_LOOKBACK_DAYS + 1):
                    candidate = today - timedelta(days=back)
                    try:
                        page = requests.get(_ekape_url(item, start, candidate)).decode("utf-8", "replace")
                        parsed = parse_ekape_range(page, label, start, candidate)
                    except RuntimeError:
                        raise
                    except Exception:
                        parsed = None
                    if parsed is not None:
                        ekape_end = candidate
                        result[item["id"]] = stamp(parsed)
                        break
            else:
                page = requests.get(_ekape_url(item, start, ekape_end)).decode("utf-8", "replace")
                parsed = parse_ekape_range(page, label, start, ekape_end)
                if parsed is not None:
                    result[item["id"]] = stamp(parsed)
        except RuntimeError:
            break  # budget or cap exhausted: remaining items keep their previous baseline
        except Exception:
            pass
    out = []
    for item in items:
        baseline = result[item["id"]] if item["id"] in result else prev.get(item["id"])
        out.append({k: item[k] for k in ("id", "name", "aliases", "group", "row")} | {"baseline": baseline})
    return {"schema_version": 1, "source": "grocery_baselines", "fetched_at": now.isoformat(), "items": out}


def _date_text(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
    except ValueError:
        return None


def _month_text(value):
    return isinstance(value, str) and re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value) is not None


def _baseline_ok(b):
    return (_exact(b, BASELINE_KEYS) and type(b["avg"]) is int and b["avg"] > 0
            and type(b["months"]) is int and 1 <= b["months"] <= 12
            and _month_text(b["from"]) and _month_text(b["to"]) and b["from"] <= b["to"]
            and all(b[k] is None or _text(b[k]) for k in ("unit", "kind", "grade"))
            and _date_text(b["checked_at"]) is not None)


def sanitize(bundle, now):
    """Validated bundle with baselines older than 30 days set to None, or None for anything malformed."""
    if not _exact(bundle, BUNDLE_KEYS) or bundle["schema_version"] != 1 or bundle["source"] != "grocery_baselines" \
            or not isinstance(bundle["fetched_at"], str) or not isinstance(bundle["items"], list) \
            or len(bundle["items"]) > BASKET_MAX:
        return None
    try:
        datetime.fromisoformat(bundle["fetched_at"])
    except ValueError:
        return None
    today = _kst_today(now)
    out, seen = [], set()
    for item in bundle["items"]:
        if not _exact(item, OUT_ITEM_KEYS) or not isinstance(item["id"], str) \
                or not re.fullmatch(r"[a-z_]{2,30}", item["id"]) or item["id"] in seen \
                or not _text(item["name"]) or item["group"] not in GROUPS:
            return None
        aliases, row, baseline = item["aliases"], item["row"], item["baseline"]
        if not isinstance(aliases, list) or not 1 <= len(aliases) <= 5 or not all(_text(a) for a in aliases) \
                or not _exact(row, ("kind", "id")) or row["kind"] not in ("produce", "meat") \
                or not _text(row["id"], 120) or (baseline is not None and not _baseline_ok(baseline)):
            return None
        seen.add(item["id"])
        if baseline is not None:
            age = (today - _date_text(baseline["checked_at"])).days
            if age > KEEP_DAYS or age < -1:
                baseline = None
        out.append(dict(item, baseline=dict(baseline) if baseline else None))
    return dict(bundle, items=out)


BASELINES_NAME = "grocery-baselines.json"


def main(argv=None, now=None):
    """Weekly run: read last bundle, collect, validate, write back to briefing-data. Exit code 0/1."""
    import argparse
    from pathlib import Path
    from . import cost_policy, mirror
    from .store import load, save
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    now = (now or datetime.now(ZoneInfo("Asia/Seoul"))).astimezone(ZoneInfo("Asia/Seoul"))
    config = load(args.root / "sources.yaml", None)
    source = next(s for s in config["sources"] if s["id"] == "groceries")
    cost_policy.reset(MAX_REQUESTS)
    previous, sha = mirror._get(args.repository, BASELINES_NAME)
    bundle = sanitize(collect(source, now, previous), now)
    if bundle is None:
        print("Baseline bundle failed validation; nothing saved")
        return 1
    for attempt in range(2):
        if mirror._put(args.repository, BASELINES_NAME, bundle, sha):
            save(args.root / mirror.BASELINES_FILE, bundle)
            print("Grocery baselines saved;", sum(1 for i in bundle["items"] if i["baseline"]), "of", len(bundle["items"]), "items with a baseline")
            return 0
        if attempt == 0:
            _, sha = mirror._get(args.repository, BASELINES_NAME)
    print("Baselines changed twice during save")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
