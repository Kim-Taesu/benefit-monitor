"""Generate a briefing locally, without HTTP requests or paid APIs."""
import argparse
import html
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from . import cost_policy
from .diff import classify
from .store import load, save, save_text, lock
from .validation import validate

SEOUL = ZoneInfo("Asia/Seoul")
ELIGIBLE = ("new", "changed", "still_valid", "upcoming", "expiring")
BLOCKED = ("needs_recheck", "expired", "excluded")
FEES = {"free": "무료(기재 조건 확인)", "paid": "유료",
        "mixed": "유·무료 혼합", "unknown": "요금 미확인"}

def aware_time(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Timezone-aware timestamp required")
    return result.astimezone(SEOUL)

def identity(data):
    return data.get("source"), data.get("url")

def action_for(item):
    summary = item["summary"]
    if "교환권" in summary:
        return "교환권 수령·사용 조건과 휴관일을 확인하고, 유효기간 안의 방문일을 정하세요."
    if any(word in summary for word in ("접수", "신청", "모집")):
        return "본인 대상 여부와 남은 접수·예약 가능 여부를 확인하세요."
    if any(word in summary for word in ("예약", "대여", "면접실")):
        return "이용 자격과 예약 가능한 날짜·시간을 확인하세요."
    if any(word in summary for word in ("할인", "페이백", "환급", "상품권", "쿠폰", "적립")):
        return "구매 전 대상·결제수단·최소구매액·할인한도를 확인하고 원래 필요한 지출에 적용하세요."
    return "이용 비용과 운영시간·참여 조건을 확인한 뒤 이용·방문일을 정하세요."

def build(report, config, now=None):
    """Revalidate recommendations; bucket labels alone are insufficient."""
    cost_policy.require_free(config)
    now = now or datetime.now(SEOUL)
    if now.tzinfo is None:
        raise ValueError("Briefing generation time requires timezone")
    now = now.astimezone(SEOUL)
    report_time = aware_time(report["verified_at"])
    if report_time > now:
        raise ValueError("Source report cannot be from the future")
    sources = {s["id"]: s for s in config["sources"]}
    denied = {identity(d) for group in BLOCKED for d in report.get(group, [])}
    records, conflicts, changes = {}, set(), set()
    for group in ELIGIBLE:
        for data in report.get(group, []):
            key = identity(data)
            if group in ("new", "changed"):
                changes.add(key)
            try:
                item = validate(data, sources, now)
            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                conflicts.add(key)
                continue
            if key in records and records[key].data() != item.data():
                conflicts.add(key)
            records[key] = item
    candidates = {item.id:item for key,item in records.items()
                  if key not in denied and key not in conflicts}
    fresh = classify({}, candidates, now, config.get("expiring_days", 7),
                     config.get("max_age_days", 7))
    current, future = fresh["new"], fresh["upcoming"]
    def priority(item):
        end = date.fromisoformat(item["valid_until"]) if item["valid_until"] else date.max
        exact = aware_time(item["deadline_at"]) if item["deadline_at"] else datetime.max.replace(tzinfo=SEOUL)
        return (end, exact, 0 if identity(item) in changes else 1,
                item["source"], item["url"])
    current.sort(key=priority)
    future.sort(key=lambda i: (i["valid_from"] or "9999-12-31", priority(i)))
    top = [
        dict(i, action=action_for(i), priority_reason="이용료와 무관하게 검증된 현재 항목 중 기한이 가까운 순서")
        for i in current
    ][:3]
    top_keys = {identity(i) for i in top}
    soon = sorted(
        [i for i in current+future if i["valid_until"] and
         0 <= (date.fromisoformat(i["valid_until"])-now.date()).days <= config.get("expiring_days", 7)],
        key=priority)
    same_day_report = report_time.date() == now.date()
    return dict(
        schema_version=1, generated_at=now.isoformat(), source_report_at=report_time.isoformat(),
        top3=top, expiring=soon, upcoming=future,
        other_verified=[i for i in current if identity(i) not in top_keys],
        new_changed=[i for i in current+future if same_day_report and identity(i) in changes],
        eligible_count=len(current)+len(future),
        withheld=dict(
            pending=len(report.get("needs_recheck", []))+len(fresh["needs_recheck"]),
            expired=len(report.get("expired", []))+len(fresh["expired"]),
            excluded=len(report.get("excluded", [])),
            invalid_or_conflicting=len(conflicts)),
        coverage_incomplete=not report.get("complete", False),
        report_is_from_previous_date=not same_day_report,
        policy=dict(top3="verified_current_deadline_first", benefit_fee_filter="none",
                    infrastructure_paid_services_allowed=False, personal_eligibility="unconfirmed",
                    network_requests=0, paid_services_used=False))

def md_text(value):
    value = html.escape(" ".join(str(value).split()), quote=False)
    for char in ("\\", "*", "_", "[", "]", "#", "|"):
        value = value.replace(char, "\\" + char)
    return value

def stamp(value):
    return aware_time(value).strftime("%Y-%m-%d %H:%M KST")

def term(item):
    if item["deadline_at"]:
        return stamp(item["deadline_at"])
    if item["valid_until"]:
        return item["valid_until"] + " (일자 기준)"
    return "상시 운영 안내·종료일 미기재"

def public_conditions(value):
    value = value.replace("구분하며 신청·결제는 실행하지 않음.", "구분하세요.")
    value = value.replace("valid_until", "표시 기한")
    value = value.replace("needs_recheck", "추가 확인 상태")
    for sentence in ("앱 내 유료 구매나 구독은 실행하지 않음.",
                     "신청·결제는 실행하지 않음.", "이메일 발송하지 않음.",
                     "구매·결제하지 않음.", "신청·예약·결제는 실행하지 않음."):
        value = value.replace(sentence, "")
    return value.strip()

def details(item):
    districts = ", ".join(item["districts"]) or "지역 조건은 공식 안내 확인"
    url = quote(item["url"], safe=":/?&=;%+#")
    return [
        f"요금: {FEES[item['fee_status']]} · 기한: {term(item)}",
        f"공식 확인: {stamp(item['verified_at'])} · 지역: {md_text(districts)}",
        f"조건: {md_text(public_conditions(item['conditions']) or '개인 자격·운영일·예약 조건을 공식 안내에서 확인하세요.')}",
        f"[공식 안내]({url})",
    ]

def markdown(briefing):
    day = aware_time(briefing["generated_at"]).date().isoformat()
    lines = [f"# {day} 생활 혜택 브리핑", "",
             f"생성: {stamp(briefing['generated_at'])} · 자료 기준: {stamp(briefing['source_report_at'])}", "",
             "내용은 항목별 공식 확인 시점 기준입니다. 개인 자격·휴관일·잔여석은 이용 전에 확인하세요.",
             "TOP 3는 이용료와 무관하게 검증된 현재 항목을 기한순으로 고른 준비·확인 목록입니다.", ""]
    if briefing["withheld"]["pending"]:
        lines += [f"확인 대기: 추가 확인 {briefing['withheld']['pending']}건은 추천에서 제외했습니다.", ""]
    if briefing["withheld"]["invalid_or_conflicting"]:
        lines += [f"확인 제한: 근거가 부족하거나 정보가 상충하는 {briefing['withheld']['invalid_or_conflicting']}건은 추천에서 제외했습니다.", ""]
    if briefing["coverage_incomplete"]:
        lines += ["일부 출처의 전체 확인이 남아 있어 수집한 범위에서 작성했습니다.", ""]
    if briefing["report_is_from_previous_date"]:
        lines += ["자료가 이전 날짜의 보고서입니다. 생성 시각을 기준으로 검증 유효기간과 마감을 다시 검사했습니다.", ""]
    # Render each offer once per relevant district, rather than repeating status sections.
    items = {}
    for key in ("top3", "other_verified", "upcoming"):
        for item in briefing[key]:
            items.setdefault(identity(item), item)
    upcoming = {identity(i) for i in briefing["upcoming"]}
    expiring = {identity(i) for i in briefing["expiring"]}
    changed = {identity(i) for i in briefing["new_changed"]}
    top = {identity(i): n for n, i in enumerate(briefing["top3"], 1)}
    district_names = ["강서구", "은평구"] + sorted({
        d for item in items.values() for d in item["districts"]
        if d not in ("강서구", "은평구")})
    groups = [("서울시", [i for i in items.values() if not i["districts"]])]
    groups += [(d, [i for i in items.values() if d in i["districts"]])
               for d in district_names]
    lines += ["서울시에는 구가 지정되지 않은 안내를 모았습니다. 서울시민 전체의 이용 자격을 뜻하지 않습니다.",
              "여러 구에 해당하는 안내는 각 구에 표시하며, 오늘 할 일·마감 임박·예정 표시는 항목에 붙였습니다.", ""]
    if not items:
        lines += ["현재 조건에 맞는 검증된 항목이 없습니다. 추가 확인 전에는 추천을 채우지 않습니다.", ""]
    for name, members in groups:
        lines += [f"## {name}", ""]
        if not members:
            lines += ["이번 자료에서 표시할 검증 항목이 없습니다. 혜택이 없다는 뜻은 아닙니다.", ""]
        for item in members:
            key = identity(item)
            labels = []
            if key in top:
                labels.append(f"오늘 할 일 {top[key]}")
            if key in expiring:
                labels.append("마감 임박")
            if key in upcoming:
                labels.append(f"{item['valid_from']} 시작")
            if key in changed:
                labels.append("이번 자료 신규·변경")
            lines += [f"### {md_text(item['summary'])}", ""]
            if labels:
                lines += [" · ".join(labels), ""]
            if key in top:
                lines += ["오늘 할 일: " + md_text(item["action"]), ""]
            lines += ["- " + line for line in details(item)] + [""]
    lines += ["## 확인 범위", "",
              f"검증된 현재·예정 안내 {briefing['eligible_count']}건을 바탕으로 작성했습니다. "
              f"종료 {briefing['withheld']['expired']}건과 제외 {briefing['withheld']['excluded']}건은 추천에 넣지 않았습니다.",
              "조건부 무료는 해당 조건을 충족해야 합니다. 유료·요금 미확인 항목은 무료로 표시하지 않습니다.",
              "생성 과정은 로컬 파일만 사용하며 유료 API·예약·구매를 실행하지 않습니다.", ""]
    return "\n".join(lines)

def write(root, briefing):
    save(root/"briefing.json", briefing)
    save_text(root/"briefing.md", markdown(briefing))

def run(root, now=None):
    root = Path(root)
    with lock(root/"cache/.lock"):
        config = load(root/"sources.yaml", None)
        report = load(root/"report.json", None)
        if report is None:
            raise ValueError("report.json missing: run python -m benefit_monitor.cli first")
        briefing = build(report, config, now)
        write(root, briefing)
        return briefing

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    run(args.root)
    print("Briefing:",args.root/"briefing.md")

if __name__ == "__main__":
    main()
