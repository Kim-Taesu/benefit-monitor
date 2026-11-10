"""Basket configuration for the grocery "is this cheap?" quick check (period-average baselines)."""
import re

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
