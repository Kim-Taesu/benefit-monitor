"""Same-complex real transaction prices for the 청약 tab (approved 2026-11-17).

Source: 공공데이터포털 국토교통부 실거래가 API (keyed, free): 아파트 분양권전매(분양권·입주권) and 아파트 매매.
The key comes only from the REAL_ESTATE_TRANSACTION environment variable (GitHub Actions Secret) and never
appears in logs, exceptions, files or published data. rt.molit.go.kr itself forbids automated collection, so it
is not used.

Only trades of the *same complex* (name match inside the same 시·군·구) and the *same exclusive area*
(whole ㎡) are shown, newest first, cancelled trades excluded. Nearby complexes are never substituted:
a new-build vs. old-build comparison would mislead more than it informs.
"""
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from threading import Lock
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import re
import xml.etree.ElementTree as ET

from . import cost_policy
from .collectors.rss import fetch

ENV = "REAL_ESTATE_TRANSACTION"
NAME = "subscription-trades.json"
FILE = "cache/subscription_trades.json"
SEOUL = ZoneInfo("Asia/Seoul")
APIS = {"silv": "https://apis.data.go.kr/1613000/RTMSDataSvcSilvTrade/getRTMSDataSvcSilvTrade",
        "apt": "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"}
MAX_REQUESTS = 300  # 승인된 실거래 전용 상한(하루), 청약 수집 50회와 따로 센다
MONTHS = 12
OLD_REFRESH_DAYS = 3  # 지난달 이전 자료는 사흘에 한 번만 다시 받는다
ROWS = 1000
MAX_PAGES = 5
OWNERSHIP = {"입": "입주권", "분": "분양권"}

# 법정동코드 앞 5자리. 2026-11-17 매매 API로 코드마다 한 번씩 조회해 법정동 이름과 맞는지 확인했다.
# 부천(2024 구 부활)·화성특례시(2026-02 구 신설)는 새 코드만 동작한다(옛 41190·41590은 0건).
SEOUL_CODES = {"종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200", "광진구": "11215",
               "동대문구": "11230", "중랑구": "11260", "성북구": "11290", "강북구": "11305", "도봉구": "11320",
               "노원구": "11350", "은평구": "11380", "서대문구": "11410", "마포구": "11440", "양천구": "11470",
               "강서구": "11500", "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
               "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710", "강동구": "11740"}
GYEONGGI_CODES = {"수원시 장안구": "41111", "수원시 권선구": "41113", "수원시 팔달구": "41115", "수원시 영통구": "41117",
                  "성남시 수정구": "41131", "성남시 중원구": "41133", "성남시 분당구": "41135", "의정부시": "41150",
                  "안양시 만안구": "41171", "안양시 동안구": "41173", "부천시 원미구": "41192", "부천시 소사구": "41194",
                  "부천시 오정구": "41196", "광명시": "41210", "평택시": "41220", "동두천시": "41250",
                  "안산시 상록구": "41271", "안산시 단원구": "41273", "고양시 덕양구": "41281", "고양시 일산동구": "41285",
                  "고양시 일산서구": "41287", "과천시": "41290", "구리시": "41310", "남양주시": "41360", "오산시": "41370",
                  "시흥시": "41390", "군포시": "41410", "의왕시": "41430", "하남시": "41450", "용인시 처인구": "41461",
                  "용인시 기흥구": "41463", "용인시 수지구": "41465", "파주시": "41480", "이천시": "41500", "안성시": "41550",
                  "김포시": "41570", "화성시 만세구": "41591", "화성시 효행구": "41593", "화성시 병점구": "41595",
                  "화성시 동탄구": "41597", "광주시": "41610", "양주시": "41630", "포천시": "41650", "여주시": "41670",
                  "연천군": "41800", "가평군": "41820", "양평군": "41830"}


def lawd(area, district):
    if not district:
        return None
    if area == "서울":
        return SEOUL_CODES.get(district)
    if area == "경기":
        return GYEONGGI_CODES.get(district.replace("특례시", "시"))
    return None


def norm(name):
    """Complex name for matching: no parenthesised suffixes, no spaces."""
    return re.sub(r"\s+", "", re.sub(r"\([^)]*\)", "", str(name or "")))


def months(today):
    first = today.replace(day=1)
    out = []
    for _ in range(MONTHS):
        out.append(first.strftime("%Y%m"))
        first = (first - timedelta(days=1)).replace(day=1)
    return out


class _Budget:
    def __init__(self, limit):
        self.limit, self.used, self.lock = limit, 0, Lock()

    def consume(self):
        with self.lock:
            if self.used >= self.limit:
                raise RuntimeError("Real-trade request budget exhausted; stop until next run")
            self.used += 1


@contextmanager
def _own_budget(limit):
    """A separate approved budget; the 청약 collection budget is untouched and restored."""
    previous = cost_policy.budget
    cost_policy.budget = _Budget(limit)
    try:
        yield cost_policy.budget
    finally:
        cost_policy.budget = previous


def parse(body, api):
    """(totalCount, {"name|area": [amount 만원, 'YYYY-MM-DD', kind]}) keeping the newest trade per key."""
    root = ET.fromstring(body)
    code = (root.findtext(".//resultCode") or "").strip()
    if code not in ("000", "00"):
        raise ValueError("Real-trade API returned result code " + re.sub(r"[^0-9A-Za-z_]", "", code)[:10])
    latest = {}
    for item in root.iter("item"):
        get = lambda tag: (item.findtext(tag) or "").strip()
        if get("cdealType"):  # 해제된 거래
            continue
        try:
            amount = int(get("dealAmount").replace(",", ""))
            area = int(float(get("excluUseAr")))
            day = date(int(get("dealYear")), int(get("dealMonth")), int(get("dealDay"))).isoformat()
        except ValueError:
            continue
        kind = OWNERSHIP.get(get("ownershipGbn"), "분양권") if api == "silv" else "매매"
        key = f"{norm(get('aptNm'))}|{area}"
        if key not in latest or day > latest[key][1]:
            latest[key] = [amount, day, kind]
    total = int((root.findtext(".//totalCount") or "0").strip() or 0)
    return total, latest


def _due(entry, ym, today, recent):
    if not entry:
        return True
    fetched = datetime.fromisoformat(entry["fetched_at"]).astimezone(SEOUL).date()
    if ym in recent:
        return fetched < today
    return (today - fetched).days >= OLD_REFRESH_DAYS


def update(items, now, previous, key, domains, fetch=fetch):
    """Refresh the private cache for every district that has a complex. Returns (cache, requests used).
    A failed month keeps its previous entry; budget exhaustion stops the run. Never raises for network errors."""
    today = now.astimezone(SEOUL).date()
    window = months(today)
    codes = sorted({c for c in (lawd(i.get("area"), i.get("district")) for i in items) if c})
    old = (previous or {}).get("entries", {}) if isinstance(previous, dict) else {}
    wanted = {f"{api}|{c}|{ym}" for api in APIS for c in codes for ym in window}
    entries = {k: v for k, v in old.items() if k in wanted and isinstance(v, dict) and "fetched_at" in v and "latest" in v}
    used = 0
    if not key or not codes:
        return {"schema_version": 1, "entries": entries}, used
    with _own_budget(MAX_REQUESTS) as budget:
        try:
            for code in codes:
                for api, url in APIS.items():
                    for ym in window:
                        name = f"{api}|{code}|{ym}"
                        if not _due(entries.get(name), ym, today, window[:2]):
                            continue
                        try:
                            merged, page, total = {}, 1, 1
                            while (page - 1) * ROWS < total and page <= MAX_PAGES:
                                query = urlencode(dict(serviceKey=key, LAWD_CD=code, DEAL_YMD=ym, numOfRows=ROWS, pageNo=page))
                                total, latest = parse(fetch(url + "?" + query, domains), api)
                                for k, v in latest.items():
                                    if k not in merged or v[1] > merged[k][1]:
                                        merged[k] = v
                                page += 1
                            entries[name] = {"fetched_at": now.isoformat(), "latest": merged}
                        except RuntimeError:
                            raise
                        except Exception:
                            pass  # 그 달은 이전 기록을 그대로 둔다. 예외 문구에는 키가 든 주소가 있을 수 있어 남기지 않는다.
        except RuntimeError:
            pass  # 하루 상한 도달: 남은 달은 다음 실행에서
        used = budget.used
    return {"schema_version": 1, "entries": entries}, used


def attach(items, cache, now):
    """Put the newest same-complex, same-area trade on each type row; mark whether the district was looked up."""
    today = now.astimezone(SEOUL).date()
    window = set(months(today))
    entries = (cache or {}).get("entries", {}) if isinstance(cache, dict) else {}
    by_code = {}
    for name, entry in entries.items():
        api, code, ym = name.split("|")
        if ym not in window:
            continue
        bucket = by_code.setdefault(code, {})
        for key, value in entry.get("latest", {}).items():
            if key not in bucket or value[1] > bucket[key][1]:
                bucket[key] = value
    for item in items:
        code = lawd(item.get("area"), item.get("district"))
        bucket = by_code.get(code) if code else None
        item["trade_status"] = "checked" if bucket is not None else "unavailable"
        for row in item.get("types", []):
            hit = bucket.get(f"{norm(item['name'])}|{int(row['area'])}") if bucket else None
            row["trade"] = dict(amount=hit[0], month=hit[1][:7], kind=hit[2]) if hit else None
    return items
