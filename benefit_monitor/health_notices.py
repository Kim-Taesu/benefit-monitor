"""District public health centre (보건소) notice boards — separate tab plus AI research candidates.

Approved 2026-11-11: the user asked for health-centre notices per district because free
screenings and vaccinations "are not announced well and get missed". Only the first list
page of each board is read (anonymous GET, robots, host allowlist). Board titles, dates and
departments are shown as published, labelled "사람 검증 전". Titles that look like a health
benefit (검진·접종·무료 …) also become ordinary review candidates so the existing AI research,
auto-publish gate and human review decide whether they become benefit cards.

Collection runs in its own daily workflow (about 30 requests) because the daily briefing run
is already near its HTTP cap; the daily run only restores the stored bundle.
"""
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
import html as htmlmod
import re
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from .collectors.rss import AGENT, fetch
from .robots import allowed
from .validation import official

SOURCE = "health_notices"
NOTICE = ("각 보건소 공식 공지 게시판 첫 페이지의 제목·날짜를 그대로 옮겼습니다. 사람 검증 전이며 "
          "대상·기간·비용은 원문에서 확인하세요.")
MAX_REQUESTS = 40
KEEP_DAYS = 60       # 공지 날짜가 이보다 오래되면 보이지 않는다
CANDIDATE_DAYS = 45  # AI 조사 후보로 넣는 공지 날짜 범위
STALE_HOURS = 30
MAX_ITEMS = 30       # 게시판 하나에서 보관할 최대 공지 수
STATUSES = ("checked", "failed", "unavailable")
BOARD_KEYS = {"district", "name", "list_url", "home_url", "detail", "onclick", "detail_template", "unavailable"}
OUT_BOARD_KEYS = {"district", "name", "list_url", "home_url", "status", "reason", "checked_at", "items"}
ITEM_KEYS = {"id", "title", "url", "date", "dept", "hint"}
DATE = re.compile(r"(20\d\d)[-./]\s?(\d{1,2})[-./]\s?(\d{1,2})")
MOBILE = re.compile(r"(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
# 건강 혜택처럼 보이는 제목. 단어 일치만 보며, 혜택 여부는 AI 조사·사람 검토가 판단한다.
HINT = re.compile(r"검진|검사|접종|무료|모집|교실|프로그램|체험|대여|상담|지원|선착순|신청|접수|캠페인|이벤트|챌린지|강좌|교육")
NOT_BENEFIT = re.compile(r"채용|입찰|고시|공고|행정처분|재심사|허가사항|위반|소식지|표본감시|회수|판매중지|휴진|결과|과태료|모집\s*완료|마감|종료|합격|명단|취급자|감시원|업소|영업자|의료기관|피해보상")


def hint(title):
    return bool(HINT.search(title)) and not NOT_BENEFIT.search(title)


def _clean(text, limit, markup=True):
    text = str(text or "")
    if markup:
        text = htmlmod.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s*\bNEW\s*$", "", " ".join(text.split()))
    text = EMAIL.sub("", MOBILE.sub("", text)).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _date(text):
    match = DATE.search(text)
    if not match:
        return None
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return None


class Rows(HTMLParser):
    """Detail anchors in document order; each takes the first date that follows it."""

    def __init__(self, base, detail, onclick=None, template=None):
        super().__init__(convert_charrefs=True)
        self.base, self.detail = base, re.compile(detail)
        self.onclick, self.template = (re.compile(onclick), template) if onclick and template else (None, None)
        self.items, self.current, self.anchor = [], None, None

    def _link(self, attrs):
        href = (attrs.get("href") or "").strip()
        if href and not href.lower().startswith("javascript"):
            url = urljoin(self.base, htmlmod.unescape(href))
            if self.detail.search(url):
                return url
        if self.onclick:
            # 상세가 스크립트 이동(onclick)인 게시판: 글 번호만 꺼내 공개 상세 GET 주소를 만든다.
            match = self.onclick.search((attrs.get("onclick") or "") + " " + href)
            if match and match.group(1).isdigit():
                return self.template.replace("{id}", match.group(1))
        return None

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        url = self._link(dict(attrs))
        if url:
            self.anchor = {"url": url, "text": [], "after": []}

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor is not None:
            anchor, self.anchor = self.anchor, None
            title = _clean(" ".join(anchor["text"]), 160, markup=False)  # 이미 풀린 글자: <행사명>을 지우지 않는다
            if not title:
                return
            if self.current and self.current["url"] == anchor["url"]:
                return  # 같은 글의 두 번째 링크(아이콘·첨부)
            self.current = {"url": anchor["url"], "title": title, "after": []}
            self.items.append(self.current)

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor["text"].append(data)
        elif self.current is not None and len(self.current["after"]) < 400:
            self.current["after"].append(data)


def parse(body, board):
    """[(url, title, date, dept)] for one list page; ValueError when no row has a date."""
    rows = Rows(board["list_url"], board["detail"], board.get("onclick"), board.get("detail_template"))
    rows.feed(body)
    out, seen = [], set()
    for row in rows.items:
        tail = [t.strip() for t in row["after"] if t.strip()]
        when = next((d for d in map(_date, tail) if d), None)
        if row["url"] in seen or when is None:
            continue
        seen.add(row["url"])
        dept = next((t for t in tail if re.fullmatch(r"[가-힣·()\s]{2,20}(과|팀|소|센터|지소|실)", t)), "")
        out.append((row["url"], row["title"], when, dept))
    if not out:
        raise ValueError("No dated notice rows; layout changed or wrong page")
    return out[:MAX_ITEMS]


def _item(url, title, when, dept):
    ident = re.sub(r"[^0-9A-Za-z]+", "-", urlsplit(url).path + "?" + urlsplit(url).query).strip("-")[-80:]
    return {"id": ident, "title": title, "url": url, "date": when, "dept": _clean(dept, 30), "hint": hint(title)}


def _boards(source):
    boards = source.get("health_boards")
    if not isinstance(boards, list) or not boards:
        raise ValueError("health_notices needs health_boards")
    for board in boards:
        if not isinstance(board, dict) or not {"district", "name", "home_url"} <= board.keys() or not board.keys() <= BOARD_KEYS:
            raise ValueError("invalid health board entry")
        if "unavailable" not in board and not {"list_url", "detail"} <= board.keys():
            raise ValueError("collectable health board needs list_url and detail")
        for key in ("list_url", "home_url"):
            if key in board and not official(board[key], source["domains"]):
                raise ValueError("health board URL outside allowlist: " + board[key])
    return boards


def collect(source, now, previous=None):
    """Bundle of all boards. A board's fetch failure keeps its previous items (marked failed)."""
    from .operations import error_info
    boards = _boards(source)
    kept = sanitize(previous, now, allow_stale=True)
    prev = {b["district"]: b for b in kept["boards"]} if kept else {}
    robots = {}
    out = []
    for board in boards:
        base = {k: board.get(k) for k in ("district", "name", "home_url")} | {"list_url": board.get("list_url") or board["home_url"]}
        if "unavailable" in board:
            out.append(base | {"status": "unavailable", "reason": board["unavailable"], "checked_at": None, "items": []})
            continue
        url = board["list_url"]
        host = "https://" + urlsplit(url).netloc
        try:
            if host not in robots:
                try:
                    robots[host] = fetch(host + "/robots.txt", source["domains"]).decode("utf-8", "replace")
                except Exception as error:
                    robots[host] = error
            if isinstance(robots[host], Exception):
                raise robots[host]
            if not allowed(robots[host], url, AGENT):
                raise PermissionError("robots disallows health notice list")
            body = fetch(url, source["domains"]).decode("utf-8", "replace")
            items = [_item(*row) for row in parse(body, board)]
            items = [i for i in items if official(i["url"], source["domains"])]
            out.append(base | {"status": "checked", "reason": None, "checked_at": now.isoformat(), "items": items})
        except RuntimeError:
            raise  # budget exhausted: whole run is unreliable
        except Exception as error:
            info = error_info(error)
            old = prev.get(board["district"])
            out.append(base | {"status": "failed", "reason": info.get("category") or type(error).__name__,
                               "checked_at": old["checked_at"] if old else None,
                               "items": old["items"] if old else []})
    return {"schema_version": 1, "source": SOURCE, "fetched_at": now.isoformat(), "notice": NOTICE, "boards": out}


def _https(url):
    parts = urlsplit(url) if isinstance(url, str) else None
    return bool(parts and parts.scheme == "https" and parts.hostname and not parts.username and not parts.password)


def sanitize(bundle, now, allow_stale=False):
    """Field-by-field re-check; drops notices older than KEEP_DAYS. None when unusable."""
    try:
        if (not isinstance(bundle, dict) or bundle.get("schema_version") != 1 or bundle.get("source") != SOURCE
                or not isinstance(bundle.get("boards"), list) or len(bundle["boards"]) > 40):
            return None
        fetched = datetime.fromisoformat(bundle["fetched_at"])
        if fetched.tzinfo is None or fetched > now + timedelta(minutes=5):
            return None
        if not allow_stale and now - fetched > timedelta(hours=STALE_HOURS):
            return None
        oldest = (now.astimezone(ZoneInfo("Asia/Seoul")).date() - timedelta(days=KEEP_DAYS)).isoformat()
        boards, seen = [], set()
        for board in bundle["boards"]:
            if not isinstance(board, dict) or set(board) != OUT_BOARD_KEYS or board["status"] not in STATUSES:
                return None
            if board["district"] in seen or not isinstance(board["district"], str) or not 1 <= len(board["district"]) <= 10:
                return None
            seen.add(board["district"])
            if not isinstance(board["name"], str) or not 1 <= len(board["name"]) <= 30:
                return None
            if not _https(board["list_url"]) or not _https(board["home_url"]):
                return None
            if board["reason"] is not None and (not isinstance(board["reason"], str) or len(board["reason"]) > 120):
                return None
            if board["checked_at"] is not None:
                datetime.fromisoformat(board["checked_at"])
            if not isinstance(board["items"], list) or len(board["items"]) > MAX_ITEMS:
                return None
            items = []
            for item in board["items"]:
                if not isinstance(item, dict) or set(item) != ITEM_KEYS or type(item["hint"]) is not bool:
                    return None
                if (not isinstance(item["title"], str) or not 0 < len(item["title"]) <= 160 or not isinstance(item["dept"], str)
                        or len(item["dept"]) > 30 or not isinstance(item["id"], str) or not 0 < len(item["id"]) <= 80
                        or not _https(item["url"]) or urlsplit(item["url"]).hostname != urlsplit(board["list_url"]).hostname
                        or MOBILE.search(item["title"]) or EMAIL.search(item["title"])):
                    return None
                if date.fromisoformat(item["date"]).isoformat() != item["date"]:
                    return None
                if item["date"] >= oldest:
                    items.append(dict(item, hint=hint(item["title"])))
            boards.append(dict(board, items=items))
        return {"schema_version": 1, "source": SOURCE, "fetched_at": fetched.isoformat(), "notice": NOTICE, "boards": boards}
    except (KeyError, TypeError, ValueError):
        return None


def candidates(bundle, now):
    """Review candidates (same shape as district news) for health-looking notices of the last 45 days."""
    clean = sanitize(bundle, now)
    if clean is None:
        return []
    oldest = (now.astimezone(ZoneInfo("Asia/Seoul")).date() - timedelta(days=CANDIDATE_DAYS)).isoformat()
    out = []
    for board in clean["boards"]:
        for item in board["items"]:
            if item["hint"] and item["date"] >= oldest:
                out.append(dict(source=SOURCE, url=item["url"], title=item["title"],
                                summary=f"{board['name']} 공지({item['date']}) 후보. 대상·기간·비용은 원문 확인 필요.",
                                districts=[board["district"]], needs_recheck=True))
    return out


NAME = "health-notices.json"
FILE = "cache/health_notices.json"


def main(argv=None, now=None):
    """Daily run: read the last bundle, collect, validate, write back to briefing-data. Exit code 0/1."""
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
    source = next(s for s in config["sources"] if s["id"] == SOURCE)
    cost_policy.reset(MAX_REQUESTS)
    previous, sha = mirror._get(args.repository, NAME)
    bundle = sanitize(collect(source, now, previous), now)
    if bundle is None:
        print("Health notice bundle failed validation; nothing saved")
        return 1
    for attempt in range(2):
        if mirror._put(args.repository, NAME, bundle, sha):
            save(args.root / FILE, bundle)
            checked = [b for b in bundle["boards"] if b["status"] == "checked"]
            print("Health notices saved;", len(checked), "of", len(bundle["boards"]), "boards checked;",
                  sum(len(b["items"]) for b in bundle["boards"]), "notices; requests", cost_policy.budget.used)
            return 0 if checked else 1
        if attempt == 0:
            _, sha = mirror._get(args.repository, NAME)
    print("Health notices changed twice during save")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
