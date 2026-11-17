"""Seoul·Gyeonggi housing subscription (청약) schedule — a section of the benefits tab.

Approved 2026-11-17: the user asked to see Seoul/Gyeonggi 청약 dates next to benefits. Source is
청약홈 (Korea Real Estate Board), anonymous and keyless: the calendar page's own JSON lookup
(POST, one per month) and each complex's public 입주자모집공고 summary (GET for apartments,
POST for remaining-unit and officetel pages, exactly as the 청약홈 page itself requests them).
Login, application and certificate paths are never called.

Only facts shown in those pages are kept: dates, district, unit count, area and top-price ranges,
move-in month and regulation flags. Eligibility, competition and win chances are never judged.
Collection runs in its own daily workflow; the daily briefing only restores the stored bundle.
"""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo
import html as htmlmod
import json
import re

from .collectors.rss import AGENT, fetch
from .robots import allowed

SOURCE = "subscriptions"
NAME = "subscriptions.json"
FILE = "cache/subscriptions.json"
SEOUL = ZoneInfo("Asia/Seoul")
HOST = "https://www.applyhome.co.kr"
CALENDAR_URL = HOST + "/ai/aib/selectSubscrptCalender.do"
CALENDAR_PAGE = HOST + "/ai/aib/selectSubscrptCalenderView.do"
DETAIL_APT = HOST + "/ai/aia/selectAPTLttotPblancDetail.do"
DETAIL_REMAIN = HOST + "/ai/aia/selectAPTRemndrLttotPblancDetailView.do"
DETAIL_OTHER = HOST + "/ai/aia/selectPRMOLttotPblancDetailView.do"
JSON_HEADERS = {"Content-Type": "application/json; charset=UTF-8", "X-Requested-With": "XMLHttpRequest",
                "Referer": CALENDAR_PAGE}
FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8", "Referer": CALENDAR_PAGE}
NOTICE = ("청약홈(한국부동산원) 청약 달력과 입주자모집공고 요약을 옮겼습니다. 신청 자격·당첨 가능성·층·호별 금액은 "
          "확인하지 않았으니 신청 전 모집공고문에서 확인하세요.")
AREAS = ("서울", "경기")
WINDOW_DAYS = 14   # 오늘부터 이 기간 안에 접수일이 있는 단지만
DETAIL_DAYS = 3    # 이보다 최근에 읽은 상세 공고는 다시 읽지 않는다
MAX_DETAILS = 40
MAX_REQUESTS = 50  # robots 1 + 달력 2 + 상세 최대 40 (+리다이렉트 여유)
STALE_HOURS = 30
MAX_ITEMS = 120
# 청약홈 달력 페이지 스크립트의 houseSeClass/mbHouseSeClass (2026-11-17 확인).
STEP_LABELS = {"01": "특별공급", "02": "1순위", "03": "2순위", "04": "청약 접수", "05": "청약 접수",
               "06": "무순위 접수", "07": "재공급 접수", "08": "사전청약 특별공급", "09": "사전청약 1순위",
               "10": "사전청약 2순위", "11": "임의공급 접수"}
KIND_BY_CODE = {"01": "apt", "02": "apt", "03": "apt", "08": "apt", "09": "apt", "10": "apt",
                "06": "remain", "07": "remain", "11": "remain", "05": "officetel", "04": "rental"}
KINDS = ("apt", "remain", "officetel", "rental")
# 공급 유형마다 신청 자격이 달라 카드에 따로 보인다(커뮤니티 점검 목록 1순위, 2026-11-17 조사).
SUPPLY_BY_CODE = {"01": "아파트 분양", "02": "아파트 분양", "03": "아파트 분양", "08": "사전청약", "09": "사전청약",
                  "10": "사전청약", "04": "공공지원민간임대", "05": "오피스텔·도시형 등", "06": "무순위(사후접수)",
                  "07": "계약취소 재공급", "11": "임의공급"}
LABELS = set(STEP_LABELS.values()) | {"일반공급"}
PDF_HOST = "static.applyhome.co.kr"
PDF = re.compile(r'href="(https://static\.applyhome\.co\.kr/ai/aia/getAtchmnfl\.do\?[^"<>\s]+)"')
TYPE_KEYS = {"label", "area", "pyeong", "general", "special", "price", "trade"}
TRADE_KINDS = ("입주권", "분양권", "매매")
PYEONG = 3.3058
REGULATIONS = ("투기과열지구", "청약과열지역", "조정대상지역", "분양가상한제")
ITEM_KEYS = {"id", "name", "area", "district", "kind", "supply", "units", "notice_date", "types", "special_kinds", "notice_pdf", "trade_status", "area_min", "area_max", "price_min", "price_max",
             "move_in", "regulation", "steps", "announce", "contract_start", "contract_end", "url", "detail", "checked_at"}
DETAIL_KEYS = ("district", "units", "area_min", "area_max", "price_min", "price_max", "move_in", "regulation",
               "announce", "contract_start", "contract_end", "notice_date", "types", "special_kinds", "notice_pdf")
DATE = re.compile(r"(20\d\d)-(\d\d)-(\d\d)")
AREA = re.compile(r"^(\d{1,3}\.\d{2,4})[A-Z]*$")
MOBILE = re.compile(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)")
SIDO = re.compile(r"(특별시|광역시|특별자치시|특별자치도|도)$")


def _clean(value, limit):
    text = " ".join(str(value or "").split())
    return text[:limit]


def parse_calendar(payload):
    """Calendar JSON → Seoul/Gyeonggi receipt rows. Holidays, other regions and duplicates are dropped."""
    if (not isinstance(payload, dict) or not isinstance(payload.get("schdulList"), list)
            or payload.get("resultCode", 200) != 200):
        raise ValueError("Unexpected calendar payload")
    rows, seen = [], set()
    for x in payload["schdulList"]:
        if not isinstance(x, dict) or x.get("RESTDE_AT") == "Y":
            continue
        hid, pb, code, area = (str(x.get("HOUSE_MANAGE_NO") or ""), str(x.get("PBLANC_NO") or ""),
                               x.get("RCEPT_SE"), x.get("SUBSCRPT_AREA_CODE_NM"))
        name = _clean(x.get("HOUSE_NM"), 80)
        if area not in AREAS or code not in STEP_LABELS or not name or not re.fullmatch(r"\d{6,12}", hid) \
                or not re.fullmatch(r"\d{6,12}", pb):
            continue
        raw = str(x.get("IN_DATE") or "")
        if not re.fullmatch(r"20\d{6}", raw):
            continue
        day = date(int(raw[:4]), int(raw[4:6]), int(raw[6:])).isoformat()
        if (hid, day, code) in seen:
            continue
        seen.add((hid, day, code))
        rows.append(dict(id=hid, pblanc=pb, name=name, area=area, date=day, code=code, secd=str(x.get("HOUSE_SECD") or "")))
    return rows


def _add_step(steps, label, start, end):
    if steps and steps[-1]["label"] == label:
        steps[-1]["end"] = max(steps[-1]["end"], end)
    else:
        steps.append(dict(label=label, start=start, end=end))


def group(rows, today, days=WINDOW_DAYS):
    """One entry per complex (공고번호) with a receipt day in [today, today+days], nearest first."""
    first, last = today.isoformat(), (today + timedelta(days=days)).isoformat()
    by = {}
    for r in sorted(rows, key=lambda r: (r["date"], r["code"])):
        g = by.setdefault(r["id"], dict(id=r["id"], pblanc=r["pblanc"], name=r["name"], area=r["area"], secd=r["secd"],
                                        kind=KIND_BY_CODE[r["code"]], supply=SUPPLY_BY_CODE[r["code"]], steps=[], days=[]))
        g["days"].append(r["date"])
        _add_step(g["steps"], STEP_LABELS[r["code"]], r["date"], r["date"])
    out = []
    for g in by.values():
        upcoming = [d for d in g.pop("days") if first <= d <= last]
        if upcoming:
            out.append(dict(g, next=min(upcoming)))
    return sorted(out, key=lambda g: (g["next"], g["name"]))


def detail_request(item):
    """(url, POST body or None) for a complex's 모집공고 summary, chosen as the 청약홈 calendar page does."""
    query = dict(houseManageNo=item["id"], pblancNo=item["pblanc"])
    if item["secd"] in ("01", "09"):
        return DETAIL_APT + "?" + urlencode(query), None
    url = DETAIL_REMAIN if item["secd"] in ("04", "06", "11") else DETAIL_OTHER
    return url, urlencode(dict(query, houseSecd=item["secd"])).encode()


def public_url(item):
    """Link people can open: apartment summaries open by GET; the others only by POST, so the calendar."""
    url, data = detail_request(item)
    return url if data is None else CALENDAR_PAGE


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.row, self.cell, self.text = [], None, None, []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
            self.tables[-1].append(self.row)
        elif tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None

    def handle_data(self, data):
        self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)


def district(address):
    """'서울특별시 중랑구 …' → '중랑구', '경기도 성남시 분당구 …' → '성남시 분당구'; None when unclear."""
    parts = str(address or "").split()
    if len(parts) < 2 or not SIDO.search(parts[0]) or not re.search(r"[시군구]$", parts[1]):
        return None
    if parts[1].endswith("시") and len(parts) > 2 and parts[2].endswith("구"):
        return parts[1] + " " + parts[2]
    return parts[1]


def parse_detail(body):
    """Facts from one 입주자모집공고 summary page. ValueError when the page is not one."""
    p = _Tables()
    p.feed(body)
    info = {row[0]: row[1] for t in p.tables for row in t if len(row) >= 2}
    if "공급위치" not in info:
        raise ValueError("No supply location: not a notice summary")
    units = re.search(r"([\d,]+)\s*세대", info.get("공급규모", ""))
    steps, announce, contract = [], None, (None, None)
    for t in p.tables:
        for row in t:
            dates = ["-".join(m) for m in DATE.findall(" ".join(row[1:]))]
            if not row or not dates:
                continue
            label = row[0]
            for name in ("특별공급", "1순위", "2순위", "일반공급"):
                if label.startswith(name):
                    _add_step(steps, name, min(dates), max(dates))
            if label == "청약접수":
                _add_step(steps, "청약 접수", min(dates), max(dates))
            elif label.startswith("당첨자 발표"):
                announce = dates[0]
            elif label.startswith("계약일"):
                contract = (dates[0], dates[-1])
    types, keys = [], []
    area_table = next((t for t in p.tables if any(c in ("주택형", "전용면적") for row in t for c in row)), [])
    for row in area_table:
        k = next((n for n, c in enumerate(row) if AREA.match(c)), None)
        if k is None:
            continue
        match = AREA.match(row[k])
        named = row[k - 1] if k and re.fullmatch(r"\d{1,3}[A-Z]{0,4}", row[k - 1]) else None  # 오피스텔 '41OA'
        suffix = row[k][len(match.group(1)):]
        rest, supply = row[k + 1:], None
        if rest and re.fullmatch(r"\d{1,3}\.\d{2,4}", rest[0]):
            supply, rest = float(rest[0]), rest[1:]
        counts = []
        for c in rest:
            if not c.isdigit():
                break
            counts.append(int(c))
        keys.append(named or row[k])
        types.append(dict(label=named or f"{int(float(match.group(1)))}{suffix}", area=round(float(match.group(1)), 2),
                          pyeong=int(supply / PYEONG) if supply else None,
                          general=counts[0] if len(counts) >= 3 else None, special=counts[1] if len(counts) >= 3 else None,
                          price=None))
    prices = []
    for t in p.tables:
        # 가격 표 머리글은 '공급금액' 또는 '공급금액(최고가 기준)'. 무순위 비고의 '공급금액 : 사업주체 문의'는 아니다.
        head = next(((n, row) for n, row in enumerate(t)
                     if any(c == "공급금액" or c.startswith("공급금액(") for c in row)), None)
        if head:
            col = next(i for i, c in enumerate(head[1]) if c == "공급금액" or c.startswith("공급금액("))
            for row in t[head[0] + 1:]:
                if len(row) > col and re.fullmatch(r"\d{1,3}(,\d{3})+|\d{4,}", row[col]):
                    price = int(row[col].replace(",", ""))
                    prices.append(price)
                    for n, key in enumerate(keys):
                        if key in row and types[n]["price"] is None:
                            types[n]["price"] = price
    kinds = {}
    kind_table = next((t for t in p.tables if any("신혼부부" in row for row in t)), [])
    head = next((row for row in kind_table if "신혼부부" in row), [])
    for row in kind_table:
        if row and AREA.match(row[0]):
            for name, value in zip(head, row[1:]):
                if name != "계" and value.isdigit():
                    kinds[name] = kinds.get(name, 0) + int(value)
    order = {name: n for n, name in enumerate(head)}
    special_kinds = [dict(name=k, count=v) for k, v in sorted(kinds.items(), key=lambda kv: (-kv[1], order[kv[0]])) if v]
    pdf = PDF.search(body)
    notice = DATE.search(info.get("모집공고일", ""))
    areas = [x["area"] for x in types]
    text = " ".join(" ".join(p.text).split())
    move = re.search(r"입주예정월\s*:\s*(20\d\d)[.-](\d{1,2})", text)
    special = text[text.find("특이사항"):][:300] if "특이사항" in text else ""
    return dict(district=district(info["공급위치"]),
                units=int(units.group(1).replace(",", "")) if units else None,
                steps=steps, announce=announce, contract_start=contract[0], contract_end=contract[1],
                area_min=min(areas) if areas else None, area_max=max(areas) if areas else None,
                price_min=min(prices) if prices else None, price_max=max(prices) if prices else None,
                move_in=f"{move.group(1)}-{int(move.group(2)):02d}" if move else None,
                regulation=sorted((r for r in REGULATIONS if r in special), key=special.find),
                notice_date="-".join(notice.groups()) if notice else None, types=types[:40], special_kinds=special_kinds[:12],
                notice_pdf=htmlmod.unescape(pdf.group(1)) if pdf else None)


def _robots(domains):
    try:
        return fetch(HOST + "/robots.txt", domains).decode("utf-8", "replace")
    except HTTPError as error:
        if error.code != 404:
            raise
        return ""


def _months(today):
    first = today.replace(day=1)
    following = (first + timedelta(days=32)).replace(day=1)
    return [first.strftime("%Y%m"), following.strftime("%Y%m")]


def collect(source, now, previous=None):
    """Bundle of complexes with receipts in the next two weeks. A calendar failure raises (nothing saved);
    a detail failure keeps the calendar-only card."""
    domains = source["domains"]
    today = now.astimezone(SEOUL).date()
    robot = _robots(domains)
    if not allowed(robot, CALENDAR_URL, AGENT):
        raise PermissionError("robots disallows the 청약 calendar")
    rows = []
    for month in _months(today):
        body = fetch(CALENDAR_URL, domains, data=json.dumps({"inqirePd": month}).encode(), headers=JSON_HEADERS)
        rows += parse_calendar(json.loads(body))
    kept = sanitize(previous, now, allow_stale=True)
    old = {i["id"]: i for i in kept["items"]} if kept else {}
    items, used, exhausted = [], 0, False
    for g in group(rows, today):
        base = dict(id=g["id"], name=g["name"], area=g["area"], kind=g["kind"], supply=g["supply"], steps=g["steps"],
                    url=public_url(g), detail="failed", checked_at=None, **{k: None for k in DETAIL_KEYS})
        base.update(regulation=[], types=[], special_kinds=[], trade_status="unavailable")
        try:
            _check(base)
        except BAD:
            continue  # 달력 행부터 쓸 수 없는 단지(예: 이름에 휴대전화 번호)는 뺀다
        item = dict(base)
        prior = old.get(g["id"])
        if (prior and prior["detail"] == "checked"
                and now - datetime.fromisoformat(prior["checked_at"]) < timedelta(days=DETAIL_DAYS)):
            item.update({k: prior[k] for k in DETAIL_KEYS}, steps=prior["steps"], detail="checked",
                        checked_at=prior["checked_at"])
        elif used < MAX_DETAILS and not exhausted:
            used += 1
            try:
                url, data = detail_request(g)
                if not allowed(robot, url, AGENT):
                    raise PermissionError("robots disallows the notice summary")
                found = parse_detail(fetch(url, domains, data=data, headers=FORM_HEADERS if data else None)
                                     .decode("utf-8", "replace"))
                steps = found.pop("steps") or g["steps"]
                labels = {s["label"] for s in g["steps"]}
                if len(labels) == 1:
                    steps = [dict(s, label=next(iter(labels))) if s["label"] == "청약 접수" else s for s in steps]
                item.update(found, steps=steps, detail="checked", checked_at=now.isoformat())
            except RuntimeError:
                exhausted = True  # 요청 예산 소진: 남은 단지는 달력 정보만
            except Exception:
                pass
        item["types"] = [dict(row, trade=row.get("trade")) for row in item["types"]]
        try:
            _check(item)
        except BAD:
            item = base  # 상세 값 하나가 이상하면 그 단지만 달력 정보로 강등(묶음 전체를 버리지 않는다)
        items.append(item)
    return {"schema_version": 1, "source": SOURCE, "fetched_at": now.isoformat(), "window_days": WINDOW_DAYS,
            "notice": NOTICE, "items": items}


def _day(value, optional=True):
    if value is None and optional:
        return None
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("Bad date")
    return value


def _number(value, low, high, kind):
    if value is None:
        return None
    if type(value) not in kind or not low < value < high:
        raise ValueError("Bad number")
    return value


BAD = (KeyError, TypeError, ValueError, AttributeError)


def _check(item):
    """Raise one of BAD when a single complex is malformed (keys, enums, ranges, dates, link host)."""
    if not isinstance(item, dict) or set(item) != ITEM_KEYS:
        raise ValueError("Bad item keys")
    if (not isinstance(item["id"], str) or not re.fullmatch(r"\d{6,12}", item["id"])
            or not isinstance(item["name"], str) or not 0 < len(item["name"]) <= 80 or MOBILE.search(item["name"])
            or item["area"] not in AREAS or item["kind"] not in KINDS or item["detail"] not in ("checked", "failed")):
        raise ValueError("Bad item")
    if item["district"] is not None and (not isinstance(item["district"], str) or not 0 < len(item["district"]) <= 20):
        raise ValueError("Bad district")
    _number(item["units"], 0, 100000, (int,))
    for key in ("area_min", "area_max"):
        _number(item[key], 0, 1000, (int, float))
    for key in ("price_min", "price_max"):
        _number(item[key], 0, 10 ** 7, (int,))
    if item["move_in"] is not None and not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", str(item["move_in"])):
        raise ValueError("Bad move-in month")
    if not isinstance(item["regulation"], list) or any(r not in REGULATIONS for r in item["regulation"]):
        raise ValueError("Bad regulation")
    if item["supply"] not in SUPPLY_BY_CODE.values():
        raise ValueError("Bad supply type")
    _day(item["notice_date"])
    if not isinstance(item["types"], list) or len(item["types"]) > 40:
        raise ValueError("Bad types")
    for row in item["types"]:
        if (not isinstance(row, dict) or set(row) != TYPE_KEYS or not isinstance(row["label"], str)
                or not re.fullmatch(r"\d{1,3}[A-Z]{0,4}", row["label"])):
            raise ValueError("Bad type row")
        _number(row["area"], 0, 1000, (int, float))
        _number(row["pyeong"], 0, 400, (int,))
        _number(row["price"], 0, 10 ** 7, (int,))
        for key in ("general", "special"):
            if row[key] is not None and (type(row[key]) is not int or not 0 <= row[key] < 100000):
                raise ValueError("Bad count")
        trade = row["trade"]
        if trade is not None:
            if (not isinstance(trade, dict) or set(trade) != {"amount", "month", "kind"} or trade["kind"] not in TRADE_KINDS
                    or not isinstance(trade["month"], str) or not re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", trade["month"])):
                raise ValueError("Bad trade")
            _number(trade["amount"], 0, 10 ** 7, (int,))
    if item["trade_status"] not in ("checked", "unavailable"):
        raise ValueError("Bad trade status")
    if not isinstance(item["special_kinds"], list) or len(item["special_kinds"]) > 12:
        raise ValueError("Bad special kinds")
    for row in item["special_kinds"]:
        if (not isinstance(row, dict) or set(row) != {"name", "count"} or not isinstance(row["name"], str)
                or not 0 < len(row["name"]) <= 10 or MOBILE.search(row["name"])):
            raise ValueError("Bad special kind")
        _number(row["count"], 0, 100000, (int,))
    if item["notice_pdf"] is not None:
        pdf = urlsplit(item["notice_pdf"]) if isinstance(item["notice_pdf"], str) else None
        if not pdf or pdf.scheme != "https" or pdf.hostname != PDF_HOST or pdf.path != "/ai/aia/getAtchmnfl.do" or pdf.username:
            raise ValueError("Bad notice link")
    steps = item["steps"]
    if not isinstance(steps, list) or not 0 < len(steps) <= 12:
        raise ValueError("Bad steps")
    for step in steps:
        if (not isinstance(step, dict) or set(step) != {"label", "start", "end"} or step["label"] not in LABELS
                or _day(step["start"], False) > _day(step["end"], False)):
            raise ValueError("Bad step")
    for key in ("announce", "contract_start", "contract_end"):
        _day(item[key])
    parts = urlsplit(item["url"]) if isinstance(item["url"], str) else None
    if not parts or parts.scheme != "https" or parts.hostname != "www.applyhome.co.kr" or parts.username:
        raise ValueError("Bad link")
    if item["checked_at"] is not None:
        datetime.fromisoformat(item["checked_at"])
    elif item["detail"] == "checked":
        raise ValueError("Checked without time")


def sanitize(bundle, now, allow_stale=False):
    """Field-by-field re-check; drops complexes whose every step has passed. None when unusable."""
    try:
        if (not isinstance(bundle, dict) or bundle.get("schema_version") != 1 or bundle.get("source") != SOURCE
                or not isinstance(bundle.get("items"), list) or len(bundle["items"]) > MAX_ITEMS):
            return None
        fetched = datetime.fromisoformat(bundle["fetched_at"])
        if fetched.tzinfo is None or fetched > now + timedelta(minutes=5):
            return None
        if not allow_stale and now - fetched > timedelta(hours=STALE_HOURS):
            return None
        today = now.astimezone(SEOUL).date().isoformat()
        items, seen = [], set()
        for item in bundle["items"]:
            _check(item)
            if item["id"] in seen:
                return None
            seen.add(item["id"])
            if max(s["end"] for s in item["steps"]) >= today:
                items.append(dict(item, steps=[dict(s) for s in item["steps"]], regulation=list(item["regulation"]),
                                  types=[dict(x, trade=dict(x["trade"]) if x["trade"] else None) for x in item["types"]], special_kinds=[dict(x) for x in item["special_kinds"]]))
        return {"schema_version": 1, "source": SOURCE, "fetched_at": fetched.isoformat(), "window_days": WINDOW_DAYS,
                "notice": NOTICE, "items": items}
    except BAD:
        return None


def main(argv=None, now=None):
    """Daily run: read the last bundle, collect, validate, write back to briefing-data. Exit code 0/1.
    --dry-run collects and prints a summary without reading or writing briefing-data."""
    import argparse
    from pathlib import Path
    from . import cost_policy, mirror
    from .store import load, save
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    if not args.dry_run and not args.repository:
        parser.error("--repository is required unless --dry-run")
    now = (now or datetime.now(SEOUL)).astimezone(SEOUL)
    config = load(args.root / "sources.yaml", None)
    source = next(s for s in config["sources"] if s["id"] == SOURCE)
    cost_policy.reset(MAX_REQUESTS)
    previous, sha = (None, None) if args.dry_run else mirror._get(args.repository, NAME)
    collected = collect(source, now, previous)
    used = cost_policy.budget.used
    # 같은 단지 실거래(2026-11-17 승인, 별도 상한 300회). 키는 환경 변수에서만 읽고 어디에도 남기지 않는다.
    import os
    from . import real_trades
    trade_cache = None
    if not args.dry_run:
        try:
            trade_cache, _ = mirror._get(args.repository, real_trades.NAME)
        except Exception:
            trade_cache = None
    trade_cache, trade_requests = real_trades.update(collected["items"], now, trade_cache, os.environ.get(real_trades.ENV, ""),
                                                     source["domains"])
    real_trades.attach(collected["items"], trade_cache, now)
    bundle = sanitize(collected, now)
    if bundle is None:
        print("Subscription bundle failed validation; nothing saved")
        return 1
    summary = ("complexes", len(bundle["items"]), "details checked", sum(i["detail"] == "checked" for i in bundle["items"]),
               "requests", used, "trade requests", trade_requests,
               "types with trade", sum(bool(r["trade"]) for i in bundle["items"] for r in i["types"]))
    if args.dry_run:
        print("Dry run:", *summary)
        for item in bundle["items"]:
            print(" ", item["steps"][0]["start"], item["area"], item["district"] or "-", item["name"], item["detail"], item["trade_status"],
                  [(r["label"], r["trade"]) for r in item["types"] if r["trade"]])
        return 0
    try:  # 실거래 캐시는 비공개 보조 자료: 저장 실패가 청약 묶음 저장을 막지 않는다
        _, trade_sha = mirror._get(args.repository, real_trades.NAME)
        mirror._put(args.repository, real_trades.NAME, trade_cache, trade_sha)
    except Exception:
        print("Real-trade cache not saved; next run refetches")
    for attempt in range(2):
        if mirror._put(args.repository, NAME, bundle, sha):
            save(args.root / FILE, bundle)
            print("Subscriptions saved;", *summary)
            return 0
        if attempt == 0:
            _, sha = mirror._get(args.repository, NAME)
    print("Subscriptions changed twice during save")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
