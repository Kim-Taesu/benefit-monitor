"""Export an explicitly reviewed public briefing; never copy runtime reports."""
import argparse
import html
import json
import re
from datetime import datetime, timedelta, time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from .briefing import SEOUL, FEES, aware_time, build, identity
from .store import load, save, save_text
from .validation import validate

PUBLIC_FIELDS = ("source", "url", "title", "summary", "conditions", "districts",
                 "verified_at", "valid_from", "valid_until", "deadline_at",
                 "validity_kind", "fee_status", "needs_recheck")


def releases(root, config, now):
    sources = {s["id"]: s for s in config["sources"]}
    entries = load(root / "public/verified.json", [])
    if not isinstance(entries, list):
        raise ValueError("Public release must be a list")
    result = {}
    for entry in entries:
        if entry.get("public_release") is not True:
            raise ValueError("Explicit public_release=true required")
        item = validate({k: v for k, v in entry.items() if k != "public_release"}, sources, now)
        data = item.data()
        public = {k: data[k] for k in PUBLIC_FIELDS}
        text = json.dumps(public, ensure_ascii=False)
        # Defense in depth; explicit review is still required for freeform text.
        if re.search(r"생년월일|거주지|집주소|개인조건|비밀키|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)", text):
            raise ValueError("Possible private information in public release")
        if any(re.search(r"token|secret|password|auth|session|api.?key", key, re.I)
               for key, _ in parse_qsl(urlsplit(item.url).query)):
            raise ValueError("Credential-like query parameter in public URL")
        if identity(data) in result:
            raise ValueError("Duplicate public release")
        result[identity(data)] = data
    return result


def prepare_import(root, now=None):
    root = Path(root)
    now = now or datetime.now(SEOUL)
    items = releases(root, load(root / "sources.yaml", None), now)
    path = root / "inputs/public.json"
    save(path, list(items.values()))
    return path


STATUS = {"checked": "목록 수집 성공 · 본문 검증 별도", "cached": "6시간 이내 목록 캐시 · 본문 검증 별도",
          "failed": "이번 수집 실패", "not_connected": "자동 수집 미연결", "not_checked": "이번 실행에서 확인 안 됨"}


def coverage(root, config, report, items):
    success = report.get("collection", {}).get("successful_sources", [])
    sources = []
    observed = {d["district"]: d for d in report.get("district_coverage", []) if "district" in d}
    for source in config["sources"]:
        connected = bool(source.get("feed_url") or source.get("html_url"))
        status = "checked" if source["id"] in success else "failed" if connected else "not_connected"
        district = source.get("district_feed")
        if district:
            record = observed.get(district, {})
            status = record.get("status", "not_checked")
            if status == "checked" and record.get("mode") == "cached":
                status = "cached"
            if status not in STATUS:
                status = "failed"
        sources.append(dict(source=source["id"], name=source.get("name", source["id"]), status=status,
                            scope=source.get("collection_scope", ""),
                            verified_count=sum(i["source"] == source["id"] or
                                               bool(district and district in i["districts"]) for i in items)))
    districts = []
    for district in load(root / "districts.json", {"districts": []})["districts"]:
        name = district["name"]
        record = observed.get(name, {})
        status = record.get("status", "not_checked")
        if status == "checked" and record.get("mode") == "cached":
            status = "cached"
        if status not in STATUS:
            status = "failed"
        districts.append(dict(name=name, status=status, checked_at=record.get("checked_at"),
                              candidates_count=record.get("candidates_count", 0),
                              verified_count=sum(name in i["districts"] for i in items)))
    return dict(sources=sources, districts=districts, scope="서울시 우리동네 뉴스 첫 페이지. 구청 전체 공지 수집과는 다릅니다.")


def page(data):
    esc = lambda value: html.escape(str(value), quote=True)
    cards = []
    for item in data["items"]:
        cards.append(
            '<article><h2>' + esc(item["summary"]) + '</h2><p>요금: ' + FEES[item["fee_status"]]
            + '</p><p>' + esc(item["conditions"]) + '</p><p>공식 확인: ' + esc(item["verified_at"])
            + '</p><p>기간: ' + esc(item["valid_from"] or "공식 안내 확인") + ' ~ '
            + esc(item["deadline_at"] or item["valid_until"] or "상시 안내")
            + '</p><a rel="noopener noreferrer" href="' + esc(item["url"]) + '">공식 안내</a></article>')
    sections = ['<section><h2>분야별 수집 현황</h2><ul>']
    cov = data.get("coverage", {})
    for row in cov.get("sources", []):
        sections.append('<li>' + esc(row["name"]) + ': ' + esc(STATUS[row["status"]]) + ' · 공개 검증 ' + str(row["verified_count"]) + '건' + (' · ' + esc(row.get("scope", "")) if row.get("scope") else '') + '</li>')
    sections.append('</ul><h2>서울 25개 지역구</h2><p>' + esc(cov.get("scope", "")) + '</p><ul>')
    for row in cov.get("districts", []):
        sections.append('<li>' + esc(row["name"]) + ': ' + esc(STATUS[row["status"]]) + ' · 후보 ' + str(row["candidates_count"]) + '건 · 공개 검증 ' + str(row["verified_count"]) + '건</li>')
    sections.append('</ul><p>0건은 혜택이 없다는 뜻이 아닙니다. 미검증 후보는 추천에 포함하지 않습니다.</p></section>')
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>생활 혜택 브리핑</title>
<style>body{font:17px/1.7 system-ui,sans-serif;margin:auto;max-width:850px;padding:32px 20px;background:#f5f6f8;color:#182333}h1{line-height:1.3}article{background:white;border:1px solid #dce1e8;border-radius:14px;padding:20px;margin:20px 0}h2{font-size:21px}a{color:#185acb}#notice{padding:16px;border-left:4px solid #b35d00;background:#fff2de}small{color:#48586e}#offers{display:none}</style></head><body>
<header><small>공식 출처 · 검증된 공개 정보</small><h1>생활 혜택 브리핑</h1></header>
<p>생성: ''' + esc(data["generated_at"]) + '''<br>수집 기준: ''' + esc(data["source_report_at"] or "확인 실패") + '''</p>
<p id="notice">''' + esc(data["message"]) + '''</p>
<p>개인 자격·쿠폰 잔량·잔여석·신청 성공은 확인하지 않았습니다. 비용과 조건은 이용 전 공식 안내에서 확인하세요.</p>
<main id="offers">''' + ''.join(cards) + ''.join(sections) + '''</main>
<noscript>현재 유효성 확인을 위해 JavaScript를 켜세요. 이전 결과를 오늘의 추천으로 표시하지 않습니다.</noscript>
<footer><a href="briefing.json">JSON</a> · <a href="briefing.md">텍스트</a><p>부분 수집이며 미검증 후보는 추천하지 않습니다.</p></footer>
<script>
const until = ''' + json.dumps(data["valid_through"]) + ''';
function refresh() {
  const fresh = until && Date.now() < Date.parse(until);
  document.getElementById('offers').style.display = fresh ? 'block' : 'none';
  if (!fresh && until) document.getElementById('notice').textContent = '최신 결과 확인 필요: 표시 기한이 지났습니다. 이전 파일을 오늘의 브리핑으로 사용하지 마세요.';
}
refresh();setInterval(refresh, 60000);
</script></body></html>'''


def run(root, now=None, failure=False):
    root = Path(root)
    now = now or datetime.now(SEOUL)
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    now = now.astimezone(SEOUL)
    data = dict(schema_version=1, generated_at=now.isoformat(), source_report_at=None,
                valid_through=None, status="collection_failed", items=[], coverage_incomplete=True,
                message="수집 실패 또는 연결 미완료입니다. 이전 결과를 오늘의 브리핑으로 사용하지 않습니다.")
    if not failure:
        report = load(root / "report.json", None)
        if report is None:
            raise ValueError("Missing current report")
        report_time = aware_time(report["verified_at"])
        if report_time.date() != now.date() or not 0 <= (now - report_time).total_seconds() <= 7200:
            raise ValueError("A current online report within two hours is required")
        config = load(root / "sources.yaml", None)
        approved = releases(root, config, now)
        briefing = build(report, config, now)
        collection = report.get("collection", {})
        if collection.get("online") is True and (collection.get("successful_sources") or collection.get("successful_districts", 0)):
            items = {}
            for group in ("top3", "other_verified", "upcoming"):
                for item in briefing[group]:
                    release = approved.get(identity(item))
                    if release and all(item[k] == v for k, v in release.items()):
                        items[identity(item)] = {k: item[k] for k in PUBLIC_FIELDS}
            data.update(source_report_at=report_time.isoformat(), items=list(items.values()),
                        coverage_incomplete=briefing["coverage_incomplete"],
                        withheld=briefing["withheld"],
                        status="partial" if items else "awaiting_verification",
                        message=("공식 확인을 거친 공개 승인 항목입니다. 전체 혜택을 확인한 결과는 아닙니다." if items else
                                 "공개 승인된 검증 항목이 아직 없습니다. 혜택이 없다는 뜻은 아닙니다."))
            data["coverage"] = coverage(root, config, report, data["items"])
            expires = [datetime.combine(now.date() + timedelta(days=1), time.min, SEOUL)]
            for item in data["items"]:
                expires.append(aware_time(item["verified_at"]) + timedelta(days=config.get("max_age_days", 7)))
                if item["deadline_at"]:
                    expires.append(aware_time(item["deadline_at"]))
            data["valid_through"] = min(expires).isoformat()
    output = root / "delivery/public"
    output.mkdir(parents=True, exist_ok=True)
    if any(p.name not in {"briefing.json", "briefing.md", "index.html"} for p in output.iterdir()):
        raise ValueError("Unexpected file in public export directory")
    save(output / "briefing.json", data)
    save_text(output / "index.html", page(data))
    lines = ["# 생활 혜택 브리핑", data["message"],
             "생성: " + data["generated_at"], "수집 기준: " + str(data["source_report_at"]),
             "표시 기한: " + str(data["valid_through"]), "최신성은 briefing.json을 확인하세요."]
    from .briefing import md_text
    for item in data["items"]:
        lines += ["", "## " + md_text(item["summary"]), "요금: " + FEES[item["fee_status"]],
                  md_text(item["conditions"]), "공식 확인: " + item["verified_at"],
                  "시작" + (" 예정: " if item["valid_from"] and item["valid_from"] > now.date().isoformat() else ": ")
                  + (item["valid_from"] or "공식 안내 확인"),
                  "종료/마감: " + (item["deadline_at"] or item["valid_until"] or "상시 안내"), item["url"]]
    cov = data.get("coverage", {})
    for group in ("sources", "districts"):
        if cov.get(group):
            lines += ["", "## " + ("분야별 수집 현황" if group == "sources" else "지역구 수집 현황")]
            for row in cov[group]:
                lines.append("- " + md_text(row["name"]) + ": " + STATUS[row["status"]] + " · 공개 검증 " + str(row["verified_count"]) + "건" + (" · " + md_text(row.get("scope", "")) if row.get("scope") else ""))
    if cov:
        lines.append(cov["scope"])
    save_text(output / "briefing.md", "\n".join(lines) + "\n")
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare-import", action="store_true")
    mode.add_argument("--failure", action="store_true")
    args = parser.parse_args()
    if args.prepare_import:
        prepare_import(args.root)
    else:
        data = run(args.root, failure=args.failure)
        print("Public briefing status:", data["status"])
        if not args.failure and data["status"] == "collection_failed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
