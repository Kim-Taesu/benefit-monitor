"""Export an explicitly reviewed public briefing; never copy runtime reports."""
import argparse
import html
import json
import re
import os
from datetime import datetime, timedelta, time, date, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, quote

from .briefing import SEOUL, FEES, aware_time, build, identity
from .store import load, save, save_text
from .validation import validate, LABEL_CATEGORIES, benefit_value_label
from . import operations
from .models import Benefit

PUBLIC_FIELDS = ("source", "url", "title", "summary", "conditions", "districts",
                 "verified_at", "valid_from", "valid_until", "deadline_at",
                 "validity_kind", "fee_status", "needs_recheck", "payment_terms", "labels", "benefit_value", "review")
HUMAN_REVIEW = {"kind": "human"}
PRIVATE_TEXT = re.compile(r"생년월일|거주지|집주소|개인조건|비밀키|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)")


def fact_fields(data):
    """Public fields of a human-approved fact (benefit_value only when present); review is added on export."""
    return {k: data[k] for k in PUBLIC_FIELDS if k != "review" and (k != "benefit_value" or data[k])}


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
        text = json.dumps(fact_fields(data), ensure_ascii=False)
        # Defense in depth; explicit review is still required for freeform text.
        if PRIVATE_TEXT.search(text):
            raise ValueError("Possible private information in public release")
        urls = [item.url] + [v["evidence_url"] for v in (item.payment_terms, item.benefit_value) if v]
        if any(re.search(r"token|secret|password|auth|session|api.?key", key, re.I)
               for url in urls for key, _ in parse_qsl(urlsplit(url).query)):
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
        connected = bool(source.get("feed_url") or source.get("html_url") or source.get("collector"))
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


def collection_time(workflow=None):
    """Read the single daily UTC cron from the repository workflow."""
    workflow = workflow or Path(__file__).resolve().parents[1] / ".github/workflows/briefing-pages.yml"
    text = Path(workflow).read_text(encoding="utf-8")
    block = re.search(r"(?ms)^  schedule:\n(.*?)(?=^  \S|\Z)", text)
    entries = re.findall(r"(?m)^\s+- cron: (.+)$", block.group(1)) if block else []
    if len(entries) != 1:
        raise ValueError("Exactly one daily workflow schedule is required")
    cron = re.fullmatch(r"['\"](\d{1,2}) (\d{1,2}) \* \* \*['\"]", entries[0].strip())
    if not cron:
        raise ValueError("Expected a fixed daily UTC cron")
    minute, hour = map(int, cron.groups())
    return datetime(2000, 1, 1, hour, minute, tzinfo=timezone.utc).astimezone(SEOUL).time()


def run_context(now, report_time, event):
    expected=datetime.combine(now.astimezone(SEOUL).date(),collection_time(),SEOUL)
    event=event if event in ("schedule","workflow_dispatch","push") else "local_or_unknown"
    status=("unavailable" if report_time is None else "pre_schedule_snapshot" if report_time<expected
            else "scheduled_refresh" if event=="schedule" else "manual_refresh" if event=="workflow_dispatch" else "unknown_trigger")
    return dict(trigger=event,status=status,expected_collection_at=expected.isoformat(),
                scheduled_run_confirmed=status=="scheduled_refresh")


def display_date(value, missing="미확인"):
    if not value:return missing
    if "T" in value:return aware_time(value).strftime("%Y.%m.%d %H:%M (KST)")
    return date.fromisoformat(value).strftime("%Y.%m.%d")


def timing(item, now):
    """Date-only status from official dates; never reflects seats, stock or early closure."""
    now = now.astimezone(SEOUL)
    today = now.date()
    deadline = aware_time(item["deadline_at"]) if item.get("deadline_at") else None
    start = date.fromisoformat(item["valid_from"]) if item.get("valid_from") else None
    end = date.fromisoformat(item["valid_until"]) if item.get("valid_until") else None
    if deadline:
        days = (deadline.date() - today).days
        badge = "오늘 신청 마감" if days <= 0 else f"신청 마감 D-{days}" if days <= 7 else "신청 접수 기간"
        apply_line = "신청 마감: " + display_date(item["deadline_at"]) + (f" (D-{days})" if days > 0 else " (오늘)")
        # valid_until equal to the deadline date usually records the application close, not the use period.
        period = ("이용·운영 기간: " + display_date(item["valid_from"], "시작일 미확인") + " ~ "
                  + (display_date(item["valid_until"]) if end and end != deadline.date() else "종료일은 공식 안내에서 확인"))
        return dict(badge=badge, apply=apply_line, period=period, days=days)
    if start and start > today:
        days = (start - today).days
        badge = f"시작 전 D-{days}"
    elif end:
        days = (end - today).days
        badge = "오늘 종료" if days <= 0 else f"종료 D-{days}" if days <= 7 else "진행 중"
    else:
        days = None
        badge = "상시 운영" if item.get("validity_kind") == "ongoing" else "기간 미확인"
    if end or start:
        period = "기간: " + display_date(item["valid_from"], "시작일 미확인") + " ~ " + display_date(item["valid_until"], "종료일 미확인")
    else:
        period = "기간: 상시 운영" if item.get("validity_kind") == "ongoing" else "기간: 공식 안내에서 확인"
    return dict(badge=badge, apply="", period=period, days=days if end and not (start and start > today) else None)


def page(data):
    esc = lambda value: html.escape(str(value), quote=True)
    context=data.get("run_context",{})
    run_label={"pre_schedule_snapshot":"정기 수집 예정시각 이전의 결과입니다. 오늘 정기 실행 성공을 확인한 자료가 아닙니다.",
               "manual_refresh":"수동 실행으로 갱신한 결과입니다. 정기 실행 성공을 뜻하지 않습니다.",
               "scheduled_refresh":"GitHub 정기 실행에서 생성한 결과입니다.",
               "unknown_trigger":"실행 유형 미확인", "unavailable":"수집 실행 결과 확인 불가"}.get(context.get("status"),"")
    now = aware_time(data["generated_at"])
    cov = data.get("coverage", {})
    source_names = {row["source"]: row["name"] for row in cov.get("sources", [])}
    cards, urgent = [], []
    for index, item in enumerate(data["items"]):
        info = timing(item, now)
        until = esc(item.get("display_until", data["valid_through"]))
        hot = info["days"] is not None and info["days"] <= 7
        if hot:
            urgent.append((info["days"], index, '<li data-valid-until="' + until + '"><a href="#item-' + str(index) + '">'
                           + esc(item["summary"]) + '</a> · <b>' + esc(info["badge"]) + '</b></li>'))
        claim = item.get("benefit_value") or {}
        value_html = ('<p><b>' + esc(benefit_value_label(claim)) + '</b></p><p>' + esc(claim["conditions"])
                      + '</p><p>근거 문구: ' + esc(claim["evidence_quote"]) + '</p><a rel="noopener noreferrer" href="'
                      + esc(claim["evidence_url"]) + '">금액 근거 원문</a>') if claim else ''
        labels = item.get("labels") or {}
        chips = [("출처", source_names.get(item["source"], item["source"]))] + [
            (name, labels[key]) for key, name in (("audience", "대상"), ("region", "지역"), ("action", "이용 방법")) if labels.get(key)]
        cards.append(
            '<article id="item-' + str(index) + '" data-valid-until="' + until + '" data-category="' + esc(labels.get("category", "기타")) + '"><p class="badge' + (' hot' if hot else '') + '">'
            + esc(info["badge"]) + '</p>' + (' <p class="badge">' + esc(labels["category"]) + '</p>' if labels.get("category") else '')
            + '<h2>' + esc(item["summary"]) + '</h2>' + value_html + '<ul class="facts">'
            + ''.join('<li><span>' + esc(n) + '</span> ' + esc(v) + '</li>' for n, v in chips) + '</ul><p>요금: ' + FEES[item["fee_status"]]
            + '</p><p>' + esc(item["conditions"]) + '</p>'
            + ('<p><b>' + esc(info["apply"]) + '</b></p>' if info["apply"] else '')
            + '<p>' + esc(info["period"]) + '</p><p>공식 확인: ' + esc(display_date(item["verified_at"]))
            + '</p><a rel="noopener noreferrer" href="' + esc(item["url"]) + '">공식 안내</a>' + (' · <a rel="noopener noreferrer" href="' + esc(item['payment_terms']['evidence_url']) + '">결제조건 원문</a>' if item.get('payment_terms') else '') + '</article>')
    head = []
    if data["items"]:
        failed = [row["name"] for row in cov.get("sources", []) if row["status"] == "failed"]
        pending = (data.get("withheld") or {}).get("pending", 0)
        head.append('<p class="summary"><b>공개 ' + str(len(data["items"])) + '건</b> · 7일 안 마감 ' + str(len(urgent))
                    + '건 · 재검증 대기 ' + str(pending) + '건' + (' · 수집 실패 ' + esc(', '.join(failed)) if failed else '') + '</p>')
        head.append('<section id="soon"><h2>오늘·7일 안에 마감</h2>')
        if urgent:
            head.append('<ul>' + ''.join(row for _, _, row in sorted(urgent)) + '</ul>')
        else:
            head.append('<p>7일 안에 끝나는 공개 항목이 없습니다.</p>')
        head.append('<p><small>상태는 공식 안내의 날짜로만 계산했습니다. 잔여석·재고·조기 마감은 반영하지 않습니다.</small></p></section><h2>전체 항목</h2>')
        present = [c for c in LABEL_CATEGORIES if any((i.get("labels") or {}).get("category") == c for i in data["items"])]
        if present:
            head.append('<nav id="filters" aria-label="분야 필터"><button type="button" data-filter="" aria-pressed="true">전체</button>'
                        + ''.join('<button type="button" data-filter="' + esc(c) + '" aria-pressed="false">' + esc(c) + '</button>' for c in present) + '</nav>')
    cards = head + cards
    checked = sum(row["status"] in ("checked", "cached") for row in cov.get("sources", []))
    failed_names = [row["name"] for row in cov.get("sources", []) if row["status"] == "failed"]
    districts_ok = sum(row["status"] in ("checked", "cached") for row in cov.get("districts", []))
    sections = ['<section><details><summary>수집 현황: 출처 ' + str(checked) + '/' + str(len(cov.get("sources", []))) + '곳 성공'
                + (' · 실패 ' + esc(', '.join(failed_names)) if failed_names else '')
                + (' · 자동 수집 미연결 ' + str(sum(row["status"] == "not_connected" for row in cov.get("sources", []))) + '곳'
                   if any(row["status"] == "not_connected" for row in cov.get("sources", [])) else '')
                + ' · 서울 자치구 ' + str(districts_ok) + '/' + str(len(cov.get("districts", []))) + '곳 확인</summary><h2>분야별 수집 현황</h2><ul>']
    for row in cov.get("sources", []):
        sections.append('<li>' + esc(row["name"]) + ': ' + esc(STATUS[row["status"]]) + ' · 공개 검증 ' + str(row["verified_count"]) + '건' + (' · ' + esc(row.get("scope", "")) if row.get("scope") else '') + '</li>')
    sections.append('</ul><h2>서울 25개 지역구</h2><p>' + esc(cov.get("scope", "")) + '</p><ul>')
    for row in cov.get("districts", []):
        sections.append('<li>' + esc(row["name"]) + ': ' + esc(STATUS[row["status"]]) + ' · 후보 ' + str(row["candidates_count"]) + '건 · 공개 검증 ' + str(row["verified_count"]) + '건</li>')
    sections.append('</ul><p>0건은 혜택이 없다는 뜻이 아닙니다. 미검증 후보는 추천에 포함하지 않습니다.</p></details></section>')
    if data.get("review_queue"):
        reasons={"title_changed":"제목 변경", "body_changed":"본문 변경", "verification_expired":"검증 유효기간 경과", "manual_review":"조건 확인 필요", "ai_contradicted":"AI 원문 대조 불일치"}
        names={row["source"]:row["name"] for row in cov.get("sources",[])}
        sections.append('<section><details><summary>재검증 대기 '+str(len(data["review_queue"]))+'건</summary><ul>')
        for row in data["review_queue"]:
            sections.append('<li>'+esc(names.get(row["source"],row["source"]))+' · '+esc(reasons.get(row["reason"],"조건 확인 필요"))+' · 마감 '+esc(display_date(row.get("deadline")))+'</li>')
        sections.append('</ul><p>보류 항목은 추천에 포함하지 않습니다. 본문 변경 감지는 사실 검증을 대신하지 않습니다.</p></details></section>')
    if data.get("source_health"):
        sections.append('<section><details><summary>수집 상태 기록</summary><ul>')
        names={row["source"]:row["name"] for row in cov.get("sources",[])}
        for source,row in data["source_health"].items():
            if row.get("consecutive_failures"):
                sections.append('<li>'+esc(names.get(source,source))+' · 연속 실패 '+str(row["consecutive_failures"])+'회 · '+esc(row.get("error_category","other"))+' · 마지막 성공 '+esc(display_date(row.get("last_success_at")))+'</li>')
        sections.append('</ul></details></section>')
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>생활 혜택 브리핑</title>
<style>body{font:17px/1.7 system-ui,sans-serif;margin:auto;max-width:850px;padding:32px 20px;background:#f5f6f8;color:#182333}h1{line-height:1.3}article{background:white;border:1px solid #dce1e8;border-radius:14px;padding:20px;margin:20px 0}h2{font-size:21px}a{color:#185acb}#notice{padding:16px;border-left:4px solid #b35d00;background:#fff2de}.badge{display:inline-block;margin:0;padding:2px 10px;border-radius:999px;background:#e8edf5;font-size:14px}.badge.hot{background:#ffe1d6;color:#8a2400;font-weight:600}#soon{background:white;border:1px solid #dce1e8;border-radius:14px;padding:4px 20px;margin:20px 0}small{color:#48586e}#offers{display:none}.facts{list-style:none;padding:0;margin:8px 0;display:flex;flex-wrap:wrap;gap:6px 14px;font-size:15px}.facts span{color:#5a6a80}.summary{font-size:16px}#filters{display:flex;flex-wrap:wrap;gap:8px}#filters button{font:inherit;font-size:15px;padding:4px 14px;border:1px solid #c5cdd8;border-radius:999px;background:white;cursor:pointer}#filters button[aria-pressed=true]{background:#182333;color:white;border-color:#182333}details summary{cursor:pointer;font-weight:600}</style></head><body>
<header><small>공식 출처 · 검증된 공개 정보</small><h1>생활 혜택 브리핑</h1></header>
<p>생성: ''' + esc(display_date(data["generated_at"])) + '''<br>수집 기준: ''' + esc(display_date(data["source_report_at"], "확인 실패")) + '''</p>
<p>''' + esc(run_label) + '''</p>
<p id="notice">''' + esc(data["message"]) + '''</p>
<p>개인 자격·쿠폰 잔량·잔여석·신청 성공은 확인하지 않았습니다. 비용과 조건은 이용 전 공식 안내에서 확인하세요.</p>
<main id="offers">''' + ''.join(cards) + ''.join(sections) + '''</main>
<noscript>현재 유효성 확인을 위해 JavaScript를 켜세요. 이전 결과를 오늘의 추천으로 표시하지 않습니다.</noscript>
<footer><a href="briefing.json">JSON</a> · <a href="briefing.md">텍스트</a><p>부분 수집이며 미검증 후보는 추천하지 않습니다.</p></footer>
<script>
const until = ''' + json.dumps(data["valid_through"]) + ''';
let filter = '';
function refresh() {
  const fresh = until && Date.now() < Date.parse(until);
  document.getElementById('offers').style.display = fresh ? 'block' : 'none';
  document.querySelectorAll('article[data-valid-until],li[data-valid-until]').forEach(card => {
    card.hidden = !fresh || Date.now() >= Date.parse(card.dataset.validUntil)
      || (card.tagName === 'ARTICLE' && filter !== '' && card.dataset.category !== filter);
  });
  if (!fresh && until) document.getElementById('notice').textContent = '최신 결과 확인 필요: 표시 기한이 지났습니다. 이전 파일을 오늘의 브리핑으로 사용하지 마세요.';
}
document.querySelectorAll('#filters button').forEach(button => button.addEventListener('click', () => {
  filter = button.dataset.filter;
  document.querySelectorAll('#filters button').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
  refresh();
}));
refresh();setInterval(refresh, 60000);
</script></body></html>'''


def payload(root, now=None, failure=False, report=None, state=None, auto=None):
    """auto=(approved, takedowns) overrides the local AI approval files (snapshot path)."""
    from . import auto_release
    root = Path(root)
    now = now or datetime.now(SEOUL)
    if now.tzinfo is None:
        raise ValueError("Timezone required")
    now = now.astimezone(SEOUL)
    data = dict(schema_version=1, generated_at=now.isoformat(), source_report_at=None,
                valid_through=None, status="collection_failed", items=[], coverage_incomplete=True,
                message="수집 실패 또는 연결 미완료입니다. 이전 결과를 오늘의 브리핑으로 사용하지 않습니다.")
    config = load(root / "sources.yaml", None)
    state = operations.sanitize(state if state is not None else load(root / "cache/operational_state.json", {}),
                               {s["id"] for s in config["sources"]}, now)
    if not failure:
        report = report if report is not None else load(root / "report.json", None)
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
                    cid = Benefit(source=item['source'],url=item['url'],title=item['title'],summary=item['summary']).id
                    hold = state['items'].get(cid,{}).get('hold_at')
                    if hold and aware_time(item['verified_at']) <= aware_time(hold):
                        continue
                    if release and all(item[k] == v for k, v in release.items()):
                        items[identity(item)] = dict(fact_fields(item), review=dict(HUMAN_REVIEW))
            # Second approval list; a human release for the same page always wins.
            approved_auto, takedowns = auto if auto is not None else auto_release.load(root)
            for row in auto_release.public_items(approved_auto, takedowns, {s["id"]: s for s in config["sources"]}, now):
                items.setdefault(identity(row), row)
            data.update(source_report_at=report_time.isoformat(), items=list(items.values()),
                        coverage_incomplete=briefing["coverage_incomplete"],
                        withheld=briefing["withheld"],
                        status="partial" if items else "awaiting_verification",
                        message=("공식 확인을 거친 공개 승인 항목입니다. 전체 혜택을 확인한 결과는 아닙니다." if items else
                                 "공개 승인된 검증 항목이 아직 없습니다. 혜택이 없다는 뜻은 아닙니다."))
            data["coverage"] = coverage(root, config, report, data["items"])
            data["valid_through"] = datetime.combine(now.date()+timedelta(days=1), time.min, SEOUL).isoformat()
            for item in data["items"]:
                if auto_release.is_auto(item):
                    continue  # display_until already includes the 30-hour freshness cutoff.
                expires=[aware_time(item["verified_at"])+timedelta(days=config.get("max_age_days",7))]
                if item["deadline_at"]:
                    expires.append(aware_time(item["deadline_at"]))
                if item["valid_until"]:
                    expires.append(datetime.combine(date.fromisoformat(item["valid_until"])+timedelta(days=1),time.min,SEOUL))
                item["display_until"]=min(expires).isoformat()
    status = auto_release.load_status(root)
    if status:
        data["ai_status"] = status
    data["operational_state"] = state
    data["source_health"] = state["sources"]
    data["run_context"] = run_context(now, aware_time(data["source_report_at"]) if data["source_report_at"] else None, os.environ.get("GITHUB_EVENT_NAME", ""))
    data["run_id"] = os.environ.get("GITHUB_RUN_ID", "local-" + now.isoformat())
    data["review_queue"] = operations.queue(report, state, now, config.get("max_age_days", 7)) if not failure and data["source_report_at"] else []
    if "withheld" in data:
        data["withheld"]["pending"] = max(data["withheld"]["pending"],len(data["review_queue"]))
    data["ai_quality"] = ai_quality(root, report, state)
    return data


def ai_quality(root, report, state):
    """Public summary of the AI quality check. Counts come from the operational state (kept by every
    run); details are ours and the official page's words only (claim + official quotes), never model text."""
    items = state.get("items", {})
    held = sorted(k for k, r in items.items() if r.get("hold_reason") == "ai_contradicted" and r.get("hold_at"))
    try:
        findings = load(Path(root) / "cache/ai_verify/findings.json", {})
        findings = findings if isinstance(findings, dict) else {}
    except (OSError, ValueError):
        findings = {}
    run = (report or {}).get("ai_verify") or {}
    return dict(last_run_checked=run.get("checked"), held=len(held),
                dismissed=sum(1 for r in items.values() if r.get("ai_dismissed")),
                prioritized=sum(1 for r in items.values() if r.get("ai_triage")),
                findings=[dict(item_id=k, source=items[k].get("source", ""), url=findings[k]["url"], title=findings[k]["title"],
                               claims=[dict(claim=c["claim"], official_quotes=c["official_quotes"]) for c in findings[k]["claims"]])
                          for k in held if isinstance(findings.get(k), dict)])


def run(root, now=None, failure=False):
    root = Path(root)
    data = payload(root, now=now, failure=failure)
    now = aware_time(data['generated_at'])
    if (root/'public/topic-publication.json').exists():
        from .topic_publication import cards
        approved_cards = cards(root,now)
        if approved_cards is not None:data['topic_cards'] = approved_cards
    if not failure and data['status'] != 'collection_failed':
        from .festivals import sanitize
        bundle = sanitize(load(root/'cache/festivals.json', None), now)
        if bundle is not None:data['festivals'] = bundle
        attach_groceries(root,data,now)
        attach_health_notices(root,data,now)
    return write_export(root,data)


def attach_health_notices(root,data,now):
    """Separate health-centre notice tab (approved 2026-11-11); dropped when stale or malformed."""
    from .health_notices import sanitize, FILE
    private = sanitize(load(Path(root)/FILE, None), now, private=True)
    if private is None:return
    data['health_notices'] = sanitize(private, now)
    # AI sentences for year-round programmes: tied to the same stored page text, never failing publication.
    try:
        from . import auto_release
        from .health_notes import PUBLIC, public
        notes = public(load(Path(root)/PUBLIC, None), private, auto_release.load(root)[1], now)
    except Exception:
        notes = []
    if notes:data['health_notes'] = notes


def attach_groceries(root,data,now):
    """Separate grocery price channel (approved 2026-11-09); dropped when stale or malformed."""
    from .groceries import sanitize
    bundle = sanitize(load(Path(root)/'cache/groceries.json', None), now)
    if bundle is None:return
    data['groceries'] = bundle
    # The weekly pick is re-checked against this exact bundle; an admin mute strips the AI text.
    from . import auto_release
    from .grocery_pick import public
    pick = public(load(Path(root)/'cache/grocery_pick/pick.json', None), bundle, auto_release.load(root)[1], now)
    if pick is not None:data['grocery_pick'] = pick
    attach_grocery_baselines(root,data,now)
    attach_grocery_discounts(root,data,now)


def attach_grocery_discounts(root,data,now):
    """Official discount events linked to basket items (approved 2026-11-11); computed at publish time, never able to fail publishing."""
    if 'groceries' not in data or 'grocery_baselines' not in data:return
    try:
        from .grocery_discounts import link,sanitize,_kst_today
        links = link(data.get('items') or [], data['grocery_baselines']['items'], _kst_today(now))
        bundle = sanitize(dict(schema_version=1, source='grocery_discounts', generated_at=now.isoformat(), links=links), now)
    except Exception:
        return
    if bundle is not None and bundle['links']:data['grocery_discounts'] = bundle


def attach_grocery_baselines(root,data,now):
    """Period-average baselines for the quick check; only beside groceries, never able to fail publishing."""
    if 'groceries' not in data:return
    try:
        from .grocery_baselines import sanitize
        bundle = sanitize(load(Path(root)/'cache/grocery_baselines.json', None), now)
    except Exception:
        return
    if bundle is not None:data['grocery_baselines'] = bundle


def write_export(root,data):
    """Render a payload already checked by the local or snapshot publication gate."""
    root=Path(root)
    now=aware_time(data['generated_at'])
    output = root / "delivery/public"
    output.mkdir(parents=True, exist_ok=True)
    if any(p.name not in {"briefing.json", "briefing.md", "index.html"} for p in output.iterdir()):
        raise ValueError("Unexpected file in public export directory")
    save(output / "briefing.json", data)
    save_text(output / "index.html", page(data))
    lines = ["# 생활 혜택 브리핑", data["message"],
             "생성: " + display_date(data["generated_at"]), "수집 기준: " + display_date(data["source_report_at"]),
             "표시 기한: " + display_date(data["valid_through"]), "최신성과 항목별 마감은 briefing.json을 확인하세요. 종료된 항목은 추천에서 제외해야 합니다."]
    from .briefing import md_text
    for item in data["items"]:
        labels = item.get("labels") or {}
        tag = " · ".join(name + ": " + md_text(labels[key]) for key, name in (("category", "분야"), ("audience", "대상"), ("region", "지역"), ("action", "이용 방법")) if labels.get(key))
        review = item.get("review") or {}
        auto = ["AI 정리 · 공식 원문 " + str(review.get("document_count")) + "곳 대조 (사람 검증 전)"] if review.get("kind") == "ai_auto" else []
        lines += ["", "## " + md_text(item["summary"])] + auto + ([tag] if tag else []) + ["요금: " + FEES[item["fee_status"]],
                  md_text(item["conditions"]), "공식 확인: " + display_date(item["verified_at"]),
                  "시작" + (" 예정: " if item["valid_from"] and item["valid_from"] > now.date().isoformat() else ": ")
                  + display_date(item["valid_from"], "시작일 미확인"),
                  "종료/마감: " + display_date(item["deadline_at"] or item["valid_until"], "상시 안내"), item["url"]]
        claim = item.get("benefit_value") or {}
        if claim:
            lines += ["혜택 수치: " + md_text(benefit_value_label(claim)), "수치 적용 조건: " + md_text(claim["conditions"]),
                      "근거 문구: " + md_text(claim["evidence_quote"]), "금액 근거 원문: " + quote(claim["evidence_url"], safe=":/?&=;%+#")]
    lines += ["", "실행 유형: " + data["run_context"]["trigger"], "정기 실행 확인: " + ("확인" if data["run_context"]["scheduled_run_confirmed"] else "미확인") ]
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
