"""Public per-kind AI usage for each AI day (approved 2026-11-24: counts and cost, no text).

The daily AI run adds one row to briefing-data `ai-usage.json`: for each request kind, how many paid
requests it made, how many failed, the ledger charge in USD and web searches, plus the gate corpus
replay counts. The quality report sets these next to what the public page shows from each kind, so a
kind that costs every day and changes nothing visible is easy to see.

Kinds come from each run's metadata; measurement requests (a variant other than baseline) are counted as `<kind>:measure`;
requests without a run folder (web search follow-ups, grammar probes) as `other`.
"""
import base64
from collections import defaultdict
import json
from pathlib import Path

from . import tuning

FILE = 'ai-usage.json'
KEEP_DAYS = tuning.value('usage.keep_days')  # config/tuning.json


def _kind(runs, request_id):
    try:
        meta = json.loads((Path(runs) / request_id / 'metadata.json').read_text())
    except (OSError, ValueError):
        return 'other'
    kind = meta.get('kind') if isinstance(meta.get('kind'), str) else 'other'
    # Every request records its variant; 'baseline' is the regular request (2026-11-25: all were counted as measure),
    # and so is a kind's approved regular setting (benefit adaptive-high, 2026-11-26: it was counted as measure).
    from .pick_common import REGULAR_VARIANTS
    variant = meta.get('variant')
    return kind if variant in (None, 'baseline', REGULAR_VARIANTS.get(kind)) else kind + ':measure'


def _searches(row):
    try:
        return int(((row.get('usage') or {}).get('server_tool_use') or {}).get('web_search_requests') or 0)
    except (TypeError, ValueError):
        return 0


def summarize(rows, runs):
    """{kind: {requests, failed, usd, web_searches}} for ledger rows made today."""
    kinds = defaultdict(lambda: dict(requests=0, failed=0, usd=0.0, web_searches=0))
    for row in rows:
        entry = kinds[_kind(runs, row['id'])]
        entry['requests'] += 1
        entry['failed'] += row['status'] not in ('completed',)
        entry['usd'] += (row.get('charged_microdollars') or 0) / 1_000_000
        entry['web_searches'] += _searches(row)
    return {k: dict(v, usd=round(v['usd'], 6)) for k, v in sorted(kinds.items())}


def add_day(history, day, kinds, corpus=None, review=None, runtime=None):
    days = [d for d in (history or {}).get('days', []) if isinstance(d, dict) and d.get('day') != day]
    row = dict(day=day, kinds=kinds, total_usd=round(sum(k['usd'] for k in kinds.values()), 6),
               total_requests=sum(k['requests'] for k in kinds.values()))
    if corpus is not None:
        row['gate_corpus'] = corpus
    if review is not None:
        row['ops_review'] = review  # phase F: status, error codes, or findings of refs, enum codes and public quotes
    if runtime is not None:
        row['runtime'] = runtime  # 2026-11-27: packed runtime size and its largest allowlist folders
    days.append(row)
    days.sort(key=lambda d: d['day'])
    return dict(schema_version=1, days=days[-KEEP_DAYS:])


def upload(store, day, kinds, corpus=None, review=None, runtime=None):
    """Best effort: read, add today's row and write briefing-data ai-usage.json. Never raises."""
    try:
        try:
            meta = store._api('contents/' + FILE + '?ref=briefing-data')
            sha = meta.get('sha')
            history = json.loads(base64.b64decode(meta.get('content') or ''))
        except ValueError:
            sha, history = None, None  # Not created yet.
        data = add_day(history, day, kinds, corpus, review, runtime)
        body = {'message': 'Update AI usage', 'branch': 'briefing-data',
                'content': base64.b64encode((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode()).decode()}
        if sha:
            body['sha'] = sha
        store._api('contents/' + FILE, body)
        return True
    except Exception:
        return False


def markdown(kinds, corpus=None, review=None, runtime=None):
    lines = ['## AI 사용량', '', '| 종류 | 요청 | 실패 | 비용(USD) | 웹 검색 |', '|---|---|---|---|---|']
    lines += [f'| {k} | {v["requests"]} | {v["failed"]} | {v["usd"]:.4f} | {v["web_searches"]} |' for k, v in kinds.items()]
    if corpus:
        lines += ['', '## 자동 공개 게이트 재생', '']
        if corpus.get('status') != 'ok':
            lines.append(f'- 상태: {corpus.get("status")}')
        else:
            lines.append(f'- 사례 {corpus["records"]}건({corpus["oldest"]}~{corpus["newest"]}), 오늘 추가 {corpus["added"]}, '
                         f'정리 {corpus["dropped"]}')
            lines.append(f'- 지금 코드로 다시 판정: 그대로 {corpus["unchanged"]} · 공개→보류 {corpus["publish_to_held"]} · '
                         f'보류→공개 {corpus["held_to_publish"]} · 사유만 바뀜 {corpus["reasons_changed"]} · 재생 실패 {corpus["replay_failed"]}')
            if corpus.get('reasons_added') or corpus.get('reasons_removed'):
                lines.append(f'- 새로 붙은 사유 {corpus.get("reasons_added")} · 빠진 사유 {corpus.get("reasons_removed")}')
    if review:
        lines += ['', '## AI 공개 화면 점검', '', f'- 상태: {review.get("status")}']
        lines += [f'- `{f["ref"]}` {f["field"]} — {f["issue"]}: “{f["quote"]}”' for f in review.get('findings') or []]
        if review.get('errors'):
            lines.append(f'- 거절 사유: {", ".join(review["errors"])}')
        if review.get('reason'):
            lines.append(f'- 멈춘 이유: {review["reason"]}')
    if runtime:
        lines += ['', '## 실행 상태 파일 구성', '']
        if runtime.get('groups') is None:
            lines.append(f'- 상태: {runtime.get("status")} {runtime.get("reason") or ""}'.rstrip())
        else:
            lines.append(f'- 압축 {runtime["packed"] / 1024 / 1024:.2f} MiB · 파일 {runtime["files"]}개 (상한 8 MiB, 암호화 전)')
            lines += ['', '| 폴더 | 파일 | 원본(KiB) | 압축 추정(KiB) |', '|---|---|---|---|']
            lines += [f'| {g["group"]} | {g["files"]} | {g["bytes"] // 1024} | {g["packed"] // 1024} |' for g in runtime['groups']]
    return '\n'.join(lines) + '\n'
