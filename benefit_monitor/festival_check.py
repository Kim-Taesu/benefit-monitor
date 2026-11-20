"""Stage 2 of the four-stage pipeline (2026-11-20): read each festival's own description (summary, programmes,
discount text) and find what it says about cost or cancellation, independent of the listed fee field.

The model only classifies the text and copies the sentences it used. Code compares that with the listed fee
field and publishes a short note only when a copied sentence is really in the text and backs the note:
  partly_paid  listed as free, but the text names a paid programme or price
  fee_found    listed fee unknown, the text names a price or 유료
  free_found   listed fee unknown, the text says 무료
  cancelled    the text says the festival is cancelled or postponed (the festival is hidden)
The listed fee field itself is never changed.
"""
import hashlib
import json
from pathlib import Path
import re

from .official_reader import project_path
from .store import load, save, save_text

STATUSES = ('free_only', 'has_paid', 'cancelled', 'no_fee_info')
NOTES = ('partly_paid', 'fee_found', 'free_found', 'cancelled')
PAID = re.compile(r'\d[\d,]*\s*원|유료|입장료|참가비|체험비|이용료|관람료')
FREE = re.compile(r'무료')
CANCEL = re.compile(r'취소|연기|잠정\s*중단|개최하지\s*않|열리지\s*않')
FIELDS = ('id', 'name', 'start', 'end', 'place', 'fee_text', 'summary', 'programs', 'discount')
BATCH = 5
QUOTE_MIN, QUOTE_MAX, QUOTES_MAX = 2, 120, 3
STATE = 'cache/tab_checks/festival_check.json'   # private: per festival content hash
FILE = 'cache/festivals.json'


def _norm(text):
    return re.sub(r'\s+', '', text or '')


def content_key(item):
    return hashlib.sha256(json.dumps({k: item[k] for k in FIELDS}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


def body(item):
    """The festival's own description: what quotes must come from (not the listed fee field)."""
    return ' '.join(item.get(k) or '' for k in ('summary', 'programs', 'discount'))


def host(batch, now):
    if not 1 <= len(batch) <= BATCH:
        return None
    return dict(schema_version='festival-check-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                festivals=[{k: item[k] for k in FIELDS} for item in batch])


def model_input(host):
    return {'today': host['now'][:10],
            'festivals': [{k: f[k] for k in ('id', 'name', 'start', 'end', 'summary', 'programs', 'discount')}
                          for f in host['festivals']]}


def review(draft, host):
    """Error codes; empty means every festival got one status and every quote is in its own text."""
    if not isinstance(draft, dict) or set(draft) != {'results'} or not isinstance(draft['results'], list):
        return ['draft_shape']
    texts = {f['id']: _norm(body(f)) for f in host['festivals']}
    got, errors = [], []
    for row in draft['results']:
        if (not isinstance(row, dict) or set(row) != {'id', 'quotes', 'status'} or row['status'] not in STATUSES
                or not isinstance(row['quotes'], list) or not all(isinstance(q, str) for q in row['quotes'])):
            return ['result_shape']
        got.append(row['id'])
        if row['id'] in texts:
            if len(row['quotes']) > QUOTES_MAX or any(not QUOTE_MIN <= len(q) <= QUOTE_MAX for q in row['quotes']):
                errors.append('quotes_shape')
            elif any(_norm(q) not in texts[row['id']] for q in row['quotes']):
                errors.append('quote_not_in_text')
    if sorted(got) != sorted(texts):
        return ['ids_mismatch']
    return sorted(set(errors))


def note(item, status, quotes):
    """(note, quote) to publish for one festival, or None. Every note needs a backing quote from its own text."""
    text = _norm(body(item))
    quotes = [q for q in quotes if isinstance(q, str) and QUOTE_MIN <= len(q) <= QUOTE_MAX and _norm(q) in text]
    def first(pattern):
        return next((q for q in quotes if pattern.search(q)), None)
    if status == 'cancelled':
        quote = first(CANCEL)
        return ('cancelled', quote) if quote else None
    if status == 'has_paid':
        quote = next((q for q in quotes if PAID.search(q) and not re.fullmatch(r'\s*무료\s*', q)), None)
        if quote and item['fee_status'] == 'free':
            return ('partly_paid', quote)
        if quote and item['fee_status'] == 'unknown':
            return ('fee_found', quote)
        return None
    if status == 'free_only' and item['fee_status'] == 'unknown':
        quote = first(FREE)
        return ('free_found', quote) if quote else None
    return None


def public(state, bundle):
    """[{id, note, quote}] for festivals still in today's bundle with unchanged content."""
    if not isinstance(state, dict) or not isinstance(bundle, dict):
        return []
    out = []
    for item in bundle.get('items', []):
        row = state.get(item['id'])
        if not isinstance(row, dict) or row.get('content') != content_key(item):
            continue
        found = note(item, row.get('status'), row.get('quotes') or [])
        if found:
            out.append({'id': item['id'], 'note': found[0], 'quote': found[1]})
    return out


def recheck(rows, bundle):
    """Re-check stored public rows against a public festival bundle (snapshot and takedown deploys)."""
    if not isinstance(rows, list) or not isinstance(bundle, dict):
        return []
    items = {item['id']: item for item in bundle.get('items', [])}
    out, seen = [], set()
    for row in rows:
        try:
            if not isinstance(row, dict) or set(row) != {'id', 'note', 'quote'} or row['id'] in seen \
                    or row['id'] not in items or row['note'] not in NOTES:
                continue
            status = {'cancelled': 'cancelled', 'free_found': 'free_only'}.get(row['note'], 'has_paid')
            if note(items[row['id']], status, [row['quote']]) != (row['note'], row['quote']):
                continue
            seen.add(row['id'])
            out.append(dict(row))
        except (KeyError, TypeError):
            continue
    return out


def refresh(root, now, execute, invoke, runs, budget):
    """Paid calls for festivals whose content is new or changed, at most `budget` requests."""
    from .festivals import sanitize
    root = Path(root).resolve()
    bundle = sanitize(load(project_path(root, FILE), None), now)
    state = load(project_path(root, STATE), {})
    if not isinstance(state, dict):
        state = {}
    if bundle is None:
        return 0, {'status': 'no_bundle', 'requested': 0, 'notes': 0}
    day = now.date().isoformat()
    todo = [item for item in bundle['items'] if (state.get(item['id']) or {}).get('content') != content_key(item)]
    requested, failures, model = 0, [], None
    for start in range(0, len(todo), BATCH) if execute else []:
        if requested >= budget:
            break
        current = host(todo[start:start + BATCH], now)
        digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        input_path = project_path(root, f'.tools/ai-inputs/festival-check-{day}-{digest}.json')
        save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
        model = invoke(root, 'festival_check', input_path)
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
        by_id = {f['id']: f for f in current['festivals']}
        for row in draft['results']:
            state[row['id']] = {'content': content_key(by_id[row['id']]), 'status': row['status'],
                                'quotes': row['quotes'], 'day': day, 'run_id': model['run_id']}
        save(project_path(root, STATE), state)
    live = {item['id'] for item in bundle['items']}
    state = {k: v for k, v in state.items() if k in live}
    save(project_path(root, STATE), state)
    return requested, {'status': 'credit_exhausted' if (model or {}).get('status') == 'credit_exhausted' else 'completed',
                       'pending': max(0, len(todo) - requested * BATCH), 'requested': requested,
                       'notes': len(public(state, bundle)), 'errors': failures[:20]}
