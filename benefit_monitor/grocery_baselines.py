"""Basket configuration for the grocery "is this cheap?" quick check (period-average baselines)."""
import re

from . import groceries

BASKET_MAX = 25
GROUPS = ("고기·알", "채소", "기타")
ITEM_KEYS = {"id", "name", "aliases", "group", "row"}
KAMIS_KEYS = ("itemcategorycode", "itemcode", "kindcode", "productrankcode")
EKAPE_KEYS = ("species", "part", "label")


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
