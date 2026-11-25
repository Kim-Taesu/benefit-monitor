"""Check a published briefing.json the way a visitor would see it (2026-11-19).

"Deployed" is not "workflow green": a manual approved-snapshot redeploy once published `collection_failed`
with 0 benefits for ~7 minutes and dropped the AI grocery pick. This reads the live (or a saved) briefing.json
and fails on what a visitor would notice. With --before (a copy saved by --save before the change), it also
fails when an AI pick that was showing is gone.

    python3 -m benefit_monitor.live_check                         # live site
    python3 -m benefit_monitor.live_check --save /tmp/before.json # keep a copy before a redeploy
    python3 -m benefit_monitor.live_check --before /tmp/before.json

Exit 0 = no failures (warnings may be printed), 1 = failures or the source could not be read.
"""
import argparse
import json
import sys
import time
import urllib.request
from collections import namedtuple
from datetime import datetime, timezone

from benefit_monitor import tuning
from benefit_monitor.tab_picks import KEYS as TAB_PICK_KEYS

LIVE_URL = 'https://kim-taesu.github.io/benefit-monitor/briefing.json'
PICK_KEYS = tuple(TAB_PICK_KEYS) + ('grocery_pick',)
SOURCE_FAILURE_WARN = tuning.value('live.source_failure_warn')  # config/tuning.json

Result = namedtuple('Result', 'failures warnings facts')


def _has_pick(data, key):
    pick = data.get(key)
    return isinstance(pick, dict) and bool(pick.get('picks'))


def _count(data, *path):
    node = data
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return len(node) if isinstance(node, list) else 0


def check(data, before=None, now=None, max_age_hours=36):
    now = now or datetime.now(timezone.utc)
    failures, warnings, facts = [], [], []

    status = data.get('status')
    items = _count(data, 'items')
    facts.append(f'status={status} · 혜택 {items}건 · generated_at={data.get("generated_at")}')
    if status == 'collection_failed':
        failures.append('status=collection_failed — 방문자에게 "수집 실패" 화면이 보입니다')
    if items == 0:
        failures.append('혜택 0건이 공개돼 있습니다')

    try:
        generated = datetime.fromisoformat(data['generated_at'])
        age = (now - generated).total_seconds() / 3600
        facts.append(f'갱신 {age:.1f}시간 전')
        if age > max_age_hours:
            failures.append(f'갱신이 {age:.1f}시간 전입니다 (기준 {max_age_hours}시간)')
    except (KeyError, TypeError, ValueError):
        failures.append('generated_at 을 읽을 수 없어 갱신 시각을 확인하지 못했습니다')

    produce, meat = _count(data, 'groceries', 'produce', 'items'), _count(data, 'groceries', 'meat', 'items')
    facts.append(f'장보기 농산물 {produce}개 · 축산물 {meat}개')
    if not produce or not meat:
        failures.append(f'장보기 가격이 비었습니다 (농산물 {produce}개 · 축산물 {meat}개)')
    # PR #37: the per-run HTTP budget ran out mid-collection; 7 cuts went missing while the section still showed
    missing = ((data.get('groceries') or {}).get('meat') or {}).get('missing') or []
    if missing:
        names = ', '.join(str(m) for m in missing[:5]) + (' …' if len(missing) > 5 else '')
        warnings.append(f'축산물 {len(missing)}개 부위 가격을 못 가져왔습니다: {names}')

    showing = [k for k in PICK_KEYS if _has_pick(data, k)]
    facts.append('AI 추천 표시: ' + (', '.join(showing) or '없음'))
    for key in PICK_KEYS:
        if key in showing:
            continue
        if before is not None and _has_pick(before, key):
            failures.append(f'{key} 가 변경 전에는 보였는데 지금은 사라졌습니다')
        else:
            warnings.append(f'{key} 가 비어 있습니다')

    if before is not None:
        was = _count(before, 'items')
        if 0 < items < was:
            warnings.append(f'혜택이 줄었습니다: {was}건 → {items}건')

    ai_state = (data.get('ai_status') or {}).get('state')
    if ai_state and ai_state != 'ok':
        warnings.append(f'ai_status.state={ai_state}')
    for name, health in sorted((data.get('source_health') or {}).items()):
        fails = (health or {}).get('consecutive_failures') or 0
        if fails >= SOURCE_FAILURE_WARN:
            warnings.append(f'출처 {name} 연속 실패 {fails}회 ({health.get("error_category", "?")})')
    return Result(failures, warnings, facts)


def _load(source):
    if source.startswith(('http://', 'https://')):
        sep = '&' if '?' in source else '?'
        req = urllib.request.Request(f'{source}{sep}t={int(time.time())}',
                                     headers={'Cache-Control': 'no-cache', 'User-Agent': 'benefit-monitor-live-check'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    with open(source, 'rb') as f:
        return f.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description='공개된 briefing.json 을 방문자 기준으로 확인한다.')
    ap.add_argument('source', nargs='?', default=LIVE_URL, help='URL 또는 파일 (기본: 라이브 사이트)')
    ap.add_argument('--before', help='변경 전에 --save 로 저장한 briefing.json')
    ap.add_argument('--save', help='읽은 briefing.json 을 이 경로에 저장 (다음 --before 용)')
    ap.add_argument('--max-age-hours', type=float, default=36)
    args = ap.parse_args(argv)

    try:
        raw = _load(args.source)
        data = json.loads(raw)
        before = json.loads(_load(args.before)) if args.before else None
    except (OSError, ValueError) as e:
        print(f'FAIL  읽기 실패: {e}')
        return 1
    if args.save:
        with open(args.save, 'wb') as f:
            f.write(raw)

    result = check(data, before=before, max_age_hours=args.max_age_hours)
    print(f'source: {args.source}' + (f' (before: {args.before})' if args.before else ''))
    for line in result.facts:
        print(f'  ·   {line}')
    for line in result.failures:
        print(f'FAIL  {line}')
    for line in result.warnings:
        print(f'WARN  {line}')
    print(f'결과: 실패 {len(result.failures)} · 경고 {len(result.warnings)}')
    return 1 if result.failures else 0


if __name__ == '__main__':
    sys.exit(main())
