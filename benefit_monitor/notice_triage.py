"""Stage 2 of the four-stage pipeline (2026-11-20): sort health-centre notice titles into resident-facing
notices and administrative ones (recruitment, bids, personnel, results, legal notices).

Haiku reads titles only and picks one reason per notice. The model never hides anything by itself: code hides a
notice only when the reason is an administrative one AND the title carries a word for that reason. Hidden
notices stay in the public data with their reason so the page can show them on request and the admin can undo.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import re

from .official_reader import project_path
from .store import load, save, save_text

KEEP = ('service', 'event', 'health_info', 'facility', 'unclear')
HIDE = ('recruitment', 'bid', 'personnel', 'result', 'legal')
REASONS = KEEP + HIDE
# A hide reason counts only when the title itself carries a word for it.
SUPPORT = {
    'recruitment': re.compile(r'채용|구인|(직원|강사|인력|공무직|기간제|근로자|요원|봉사자|지원단)\s*(\([^)]{0,20}\))?\s*(을\s*)?(모집|선발)'),
    'bid': re.compile(r'입찰|계약|용역|견적|수의'),
    'personnel': re.compile(r'인사|위촉|임용|발령|위원\s*(모집|선정|명단)'),
    'result': re.compile(r'합격|당첨|선정\s*(결과|자)|결과\s*(발표|공고|안내)|최종\s*결과|명단\s*(발표|공고)'),
    'legal': re.compile(r'공시송달|행정처분|과태료|정보공개|반송|고시|처분\s*사전\s*통지'),
}
BATCH = 30
STATE = 'cache/tab_checks/notice_triage.json'   # private: per notice reason, run ids
KEEP_DAYS = 60


def notice_key(url, title):
    return hashlib.sha256((url + '\n' + title).encode()).hexdigest()[:24]


def notices(bundle):
    """(url, district, title, dept) for every notice in a sanitized health bundle, in board order."""
    out, seen = [], set()
    for board in (bundle or {}).get('boards', []):
        for item in board.get('items', []):
            if item['url'] in seen:
                continue
            seen.add(item['url'])
            out.append({'url': item['url'], 'district': board['district'], 'title': item['title'], 'dept': item['dept']})
    return out


def host(batch, now):
    """Model input for up to BATCH notices; ids n0.. follow the batch order."""
    if not 1 <= len(batch) <= BATCH:
        return None
    return dict(schema_version='notice-triage-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                notices=[dict(n, id=f'n{i}') for i, n in enumerate(batch)])


def model_input(host):
    return {'today': host['now'][:10],
            'notices': [{k: n[k] for k in ('id', 'district', 'dept', 'title')} for n in host['notices']]}


def review(draft, host):
    """Error codes; empty means every notice got exactly one known reason."""
    if not isinstance(draft, dict) or set(draft) != {'results'} or not isinstance(draft['results'], list):
        return ['draft_shape']
    ids = [n['id'] for n in host['notices']]
    got = []
    for row in draft['results']:
        if not isinstance(row, dict) or set(row) != {'id', 'reason'} or row['reason'] not in REASONS:
            return ['result_shape']
        got.append(row['id'])
    if sorted(got) != sorted(ids):
        return ['ids_mismatch']
    return []


def hidden_reason(title, reason):
    """The public hide reason, or None when the notice stays visible."""
    return reason if reason in HIDE and SUPPORT[reason].search(title) else None


def public(state, bundle, takedowns):
    """[{url, title, reason}] to hide on the page: only notices still in today's bundle with an unchanged title."""
    if not isinstance(state, dict):
        return []
    unhide = {t.get('url') for t in takedowns or [] if isinstance(t, dict) and t.get('kind') == 'notice_unhide'}
    out = []
    for n in notices(bundle):
        row = state.get(notice_key(n['url'], n['title']))
        if not isinstance(row, dict) or n['url'] in unhide:
            continue
        reason = hidden_reason(n['title'], row.get('reason'))
        if reason:
            out.append({'url': n['url'], 'title': n['title'], 'reason': reason})
    return out


def recheck(rows, bundle, takedowns):
    """Re-check stored public rows on paths that only hold the public payload."""
    if not isinstance(rows, list):
        return []
    present = {(n['url'], n['title']) for n in notices(bundle)}
    unhide = {t.get('url') for t in takedowns or [] if isinstance(t, dict) and t.get('kind') == 'notice_unhide'}
    out, seen = [], set()
    for row in rows:
        try:
            if (not isinstance(row, dict) or set(row) != {'url', 'title', 'reason'} or row['url'] in seen
                    or (row['url'], row['title']) not in present or row['url'] in unhide
                    or hidden_reason(row['title'], row['reason']) != row['reason']):
                continue
            seen.add(row['url'])
            out.append(dict(row))
        except (KeyError, TypeError):
            continue
    return out


def refresh(root, now, execute, invoke, runs, budget):
    """Paid calls for notices without a stored reason, at most `budget` requests. Returns (requests, report)."""
    from .health_notices import FILE, sanitize
    root = Path(root).resolve()
    bundle = sanitize(load(project_path(root, FILE), None), now, private=True)
    state = load(project_path(root, STATE), {})
    if not isinstance(state, dict):
        state = {}
    if bundle is None:
        return 0, {'status': 'no_bundle', 'requested': 0, 'hidden': 0}
    day = now.date().isoformat()
    todo = [n for n in notices(bundle) if notice_key(n['url'], n['title']) not in state]
    requested, failures, model = 0, [], None
    for start in range(0, len(todo), BATCH) if execute else []:
        if requested >= budget:
            break
        current = host(todo[start:start + BATCH], now)
        digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        input_path = project_path(root, f'.tools/ai-inputs/notice-triage-{day}-{digest}.json')
        save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
        model = invoke(root, 'notice_triage', input_path)
        requested += 1
        if model['status'] == 'credit_exhausted':
            break
        errors = ['no_draft']
        if model['status'] == 'validated_draft':
            try:
                draft = load(runs / model['run_id'] / 'result.json', None)
                errors = review(draft, current)
            except (OSError, ValueError, KeyError, TypeError):
                errors = ['draft_unreadable']
        if errors:
            failures += errors
            continue
        by_id = {n['id']: n for n in current['notices']}
        for row in draft['results']:
            n = by_id[row['id']]
            state[notice_key(n['url'], n['title'])] = {'reason': row['reason'], 'day': day, 'run_id': model['run_id']}
        save(project_path(root, STATE), state)
    # Forget rows for notices that left the bundle long ago.
    oldest = (now - timedelta(days=KEEP_DAYS)).date().isoformat()
    live = {notice_key(n['url'], n['title']) for n in notices(bundle)}
    state = {k: v for k, v in state.items() if k in live or v.get('day', '') >= oldest}
    save(project_path(root, STATE), state)
    hidden = public(state, bundle, [])
    return requested, {'status': 'credit_exhausted' if (model or {}).get('status') == 'credit_exhausted' else 'completed',
                       'pending': max(0, len(todo) - requested * BATCH), 'requested': requested,
                       'hidden': len(hidden), 'errors': failures[:20]}
