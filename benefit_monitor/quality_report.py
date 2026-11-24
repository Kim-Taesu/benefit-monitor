"""Product-level quality report for a published briefing.json (2026-11-24).

Until now people found what went wrong by looking at the page: a 청약 summary that named a step that had
ended, a Monday grocery survey silently replaced by Friday's, empty topic cards, a festival pick with no
Seoul-area candidate. Each of those passed every unit test and every publish gate, because the gates fall
back to something safe and say nothing. This report re-reads what visitors get and fails loudly when a
section is stale, empty, fell back, or no longer passes today's checks.

    python3 -m benefit_monitor.quality_report --briefing briefing.json [--previous older.json] [--now ISO]
    python3 -m benefit_monitor.quality_report --git-ref FETCH_HEAD   # briefing-data history

Exit 0 = no errors (warnings are listed), 1 = at least one error or the briefing could not be read.
It reads only public data and calls no model and no network.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import namedtuple
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from zoneinfo import ZoneInfo

from . import live_check
from .tab_picks import TAB_PICKS

KST = ZoneInfo('Asia/Seoul')
Finding = namedtuple('Finding', 'level section message')
SECTION_MAX_AGE_HOURS = 30  # festivals, health notices and subscriptions are fetched daily
MEAT_MAX_AGE_DAYS = 1
DAY_UNTIL = re.compile(r'(?:(?P<m>\d{1,2})\s*월\s*)?(?P<d>\d{1,2})\s*일\s*까지')


def _kst_day(value):
    return datetime.fromisoformat(value).astimezone(KST).date()


def _previous_weekday(day):
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _sections(data, now):
    found = []
    generated = datetime.fromisoformat(data['generated_at'])
    groceries = data.get('groceries') or {}
    produce = (groceries.get('produce') or {}).get('survey_date')
    if produce:
        # KAMIS surveys retail prices on weekdays; the newest one before the run's day must be there.
        # A public holiday makes this a false alarm, which the message says.
        expected = _previous_weekday(generated.astimezone(KST).date())
        if date.fromisoformat(produce) < expected:
            found.append(Finding('error', '장보기', f'농산물 조사일 {produce} — {expected} 조사가 있어야 합니다'
                                                   ' (그날이 공휴일이면 무시)'))
    meat = (groceries.get('meat') or {}).get('survey_date')
    if meat and (generated.astimezone(KST).date() - date.fromisoformat(meat)).days > MEAT_MAX_AGE_DAYS:
        found.append(Finding('warn', '장보기', f'축산물 조사일 {meat}이 {MEAT_MAX_AGE_DAYS}일보다 오래됐습니다'))
    for key, name in (('festivals', '축제'), ('health_notices', '보건소'), ('subscriptions', '청약')):
        section = data.get(key)
        if not isinstance(section, dict):
            found.append(Finding('error', name, f'{key} 섹션이 공개본에 없습니다'))
            continue
        try:
            age = (generated - datetime.fromisoformat(section['fetched_at'])).total_seconds() / 3600
        except (KeyError, TypeError, ValueError):
            found.append(Finding('error', name, f'{key}.fetched_at 을 읽을 수 없습니다'))
            continue
        if age > SECTION_MAX_AGE_HOURS:
            found.append(Finding('error', name, f'{key} 수집이 공개 시각보다 {age:.0f}시간 오래됐습니다'))
    if not ((data.get('health_notices') or {}).get('boards')):
        found.append(Finding('error', '보건소', '보건소 공지 게시판이 0곳입니다'))
    if not ((data.get('subscriptions') or {}).get('items')):
        found.append(Finding('warn', '청약', '청약 단지가 0곳입니다'))
    return found


def _items(data, now):
    found = []
    today = now.astimezone(KST).date()
    for item in data.get('items') or []:
        title = str(item.get('title', ''))[:40]
        until = item.get('valid_until')
        deadline = item.get('deadline_at')
        try:
            if until and date.fromisoformat(until) < today or deadline and datetime.fromisoformat(deadline) <= now:
                found.append(Finding('warn', '혜택', f'지난 항목이 공개 데이터에 남아 있습니다: {title}'))
                continue
        except ValueError:
            found.append(Finding('error', '혜택', f'날짜를 읽을 수 없습니다: {title}'))
            continue
        # 2026-11-24 트레이더스: the summary said "29일까지" while valid_until was the 26th.
        if until:
            end = date.fromisoformat(until)
            for m in DAY_UNTIL.finditer(str(item.get('summary', ''))):
                month = int(m['m']) if m['m'] else end.month
                if month == end.month and int(m['d']) != end.day:
                    found.append(Finding('warn', '혜택', f'요약은 {month}월 {m["d"]}일까지인데 표시 기한은 {until}입니다: {title}'))
                    break
    return found


def _picks(data, now):
    """Every AI pick is checked again as of now, with the same public() the publish paths use."""
    found = []
    today = now.astimezone(KST).date().isoformat()
    kinds = [(k.key, k.module, data.get(k.basis), k.name) for k in TAB_PICKS]
    kinds.append(('grocery_pick', 'grocery_pick', data.get('groceries'), 'grocery'))
    for key, module, basis, name in kinds:
        pick = data.get(key)
        if not isinstance(pick, dict):
            continue  # live_check already warns about a missing pick
        if pick.get('source') == 'rule':
            found.append(Finding('warn', name, f'{key}: AI 문장 없이 기본 카드로 대체됐습니다'))
            continue
        if key != 'grocery_pick' and pick.get('day') != today:
            found.append(Finding('warn', name, f'{key}: {pick.get("day")} 추천이 오늘({today}) 보이고 있습니다'))
        try:
            again = import_module('.' + module, __package__).public(deepcopy(pick), basis, [], now) if basis else None
        except Exception as error:  # report, never crash on one section
            again, reason = None, type(error).__name__
        else:
            reason = None
        if again is None or again.get('source') != 'ai':
            found.append(Finding('error', name, f'{key}: 공개된 AI 문장이 지금 기준 검사를 통과하지 못합니다'
                                                + (f' ({reason})' if reason else '')))
        elif pick.get('summary') and again.get('summary') is None:
            found.append(Finding('error', name, f'{key}: 요약문이 지금 기준 검사에서 빠집니다(끝난 항목을 말함)'))
    return found


def _topics_and_festivals(data, now):
    found = []
    cards = data.get('topic_cards') or {}
    if not cards.get('topics'):
        found.append(Finding('error', '주제', '주제 카드가 0개입니다' + (' (규칙 대체 결과도 비어 있음)' if cards.get('used_fallback') else '')))
    from .festival_pick import host
    festivals = data.get('festivals')
    current = host(festivals, now) if festivals else None
    if festivals and current is None:
        found.append(Finding('warn', '축제', '추천할 축제 후보가 2개 미만입니다'))
    elif current and not any(c['metro'] for c in current['candidates']):
        found.append(Finding('warn', '축제', '축제 추천 후보에 서울·경기·인천 축제가 없습니다'))
    return found


def _known_failing():
    """Source ids whose sources/<id>.json says the failure is already known; their streaks are not news."""
    names = set()
    for path in sorted((Path(__file__).resolve().parents[1] / 'sources').glob('*.json')):
        try:
            if json.loads(path.read_text(encoding='utf-8'))['monitoring']['expect'] == 'known_failing':
                names.add(path.stem)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return names


def report(data, now=None, previous=None):
    """(findings, facts) for a public briefing; findings are Finding(level, section, message)."""
    now = now or datetime.now(timezone.utc)
    base = live_check.check(data, before=previous, now=now)
    known = _known_failing()
    warnings = [w for w in base.warnings if not any(w.startswith(f'출처 {name} ') for name in known)]
    found = [Finding('error', '공개', f) for f in base.failures] + [Finding('warn', '공개', w) for w in warnings]
    for part in (_sections, _items, _picks, _topics_and_festivals):
        try:
            found += part(data, now)
        except Exception as error:
            found.append(Finding('error', '리포트', f'{part.__name__} 검사 실패: {type(error).__name__}'))
    return found, list(base.facts)


def markdown(findings, facts):
    errors = [f for f in findings if f.level == 'error']
    lines = ['## 결과물 품질 리포트', '',
             f'결과: **{"실패" if errors else "통과"}** · 오류 {len(errors)} · 경고 {len(findings) - len(errors)}', '']
    lines += [f'- {fact}' for fact in facts]
    if findings:
        lines += ['', '| 수준 | 영역 | 내용 |', '|---|---|---|']
        lines += [f'| {"❌ 오류" if f.level == "error" else "⚠️ 경고"} | {f.section} | {f.message} |'
                  for f in sorted(findings, key=lambda f: f.level != 'error')]
    return '\n'.join(lines) + '\n'


def _git_json(ref, path='briefing.json'):
    return json.loads(subprocess.run(['git', 'show', f'{ref}:{path}'], check=True, capture_output=True).stdout)


def from_git(ref):
    """The briefing at ref and the newest earlier one from another KST day (None when history is too short)."""
    data = _git_json(ref)
    day = _kst_day(data['generated_at'])
    commits = subprocess.run(['git', 'log', '--format=%H', '-n', '60', ref, '--', 'briefing.json'],
                             check=True, capture_output=True, text=True).stdout.split()
    for commit in commits[1:]:
        try:
            older = _git_json(commit)
            if _kst_day(older['generated_at']) < day:
                return data, older
        except (subprocess.CalledProcessError, KeyError, ValueError):
            continue
    return data, None


def main(argv=None):
    ap = argparse.ArgumentParser(description='공개 briefing.json 결과물 품질 리포트')
    ap.add_argument('--briefing', help='공개 briefing.json 파일')
    ap.add_argument('--previous', help='비교할 이전 공개본 (선택)')
    ap.add_argument('--git-ref', help='briefing-data 커밋(예: FETCH_HEAD); 이전 날짜 공개본을 이력에서 찾는다')
    ap.add_argument('--now', help='기준 시각 ISO (기본: 지금)')
    args = ap.parse_args(argv)
    try:
        if args.git_ref:
            data, previous = from_git(args.git_ref)
        else:
            with open(args.briefing, encoding='utf-8') as f:
                data = json.load(f)
            previous = None
            if args.previous:
                with open(args.previous, encoding='utf-8') as f:
                    previous = json.load(f)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        print(f'briefing 을 읽지 못했습니다: {type(error).__name__}')
        return 1
    now = datetime.fromisoformat(args.now) if args.now else None
    findings, facts = report(data, now, previous)
    text = markdown(findings, facts)
    print(text)
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as f:
            f.write(text)
    return 1 if any(f.level == 'error' for f in findings) else 0


if __name__ == '__main__':
    sys.exit(main())
