"""Daily AI operations review of the published briefing (approved 2026-11-25, improvement phase F).

People kept finding what was wrong by reading the page (a 청약 summary naming a step that had ended, a
"29일까지" summary with a 26th display limit, an organisation-only notice shown as a benefit). The rule-based
quality report catches the patterns already known; this asks the model once a day, after publication, to
read the public page as a visitor would and point at what looks wrong.

- Input: a compact view the code builds from the public briefing.json only (no private data, no profile).
- Output: findings of {ref, field, quote, issue}. `quote` must be copied from that entry's field and `issue`
  is one of ISSUES. There is no free text, so no model sentence is published anywhere.
- Use: report only. Findings become warnings in ai-usage.json and the quality report; they never change
  what is published, held or shown.
"""
import hashlib
import json
from pathlib import Path

from .ai_review import invoke
from .official_reader import project_path
from .store import load, save, save_text

TRIAL_RUNS = Path(__file__).resolve().parents[1] / '.tools/claude-trial/live/runs'
FOLDER = 'ops_review'
ISSUES = ('ended_or_stale', 'date_mismatch', 'not_for_individuals', 'contradiction', 'wrong_section',
          'duplicate', 'misleading_text')
MAX_FINDINGS = 10
QUOTE_MIN, QUOTE_MAX = 2, 120
MAX_TEXT = 300
LIMITS = dict(item=40, festival=20, subscription=25, health=30)
PICKS = ('festival_pick', 'benefit_pick', 'subscription_pick', 'grocery_pick')


def _text(value):
    return str(value or '')[:MAX_TEXT]


def host(data, now):
    """Entries the model may point at, each with an id; None when there is nothing to review."""
    entries = []
    for i, row in enumerate((data.get('items') or [])[:LIMITS['item']]):
        entries.append(dict(id=f'item:{i}', kind='혜택', title=_text(row.get('title')), summary=_text(row.get('summary')),
                            conditions=_text(row.get('conditions')), valid_from=_text(row.get('valid_from')),
                            valid_until=_text(row.get('valid_until')), deadline_at=_text(row.get('deadline_at')),
                            fee_status=_text(row.get('fee_status'))))
    for key in PICKS:
        pick = data.get(key)
        if isinstance(pick, dict) and pick.get('source') == 'ai':
            lines = ' / '.join(_text(p.get('line') or p.get('menu')) for p in pick.get('picks') or [])
            entries.append(dict(id=f'pick:{key}', kind='AI 추천', summary=_text(pick.get('summary')), lines=_text(lines)))
    for i, row in enumerate(((data.get('festivals') or {}).get('items') or [])[:LIMITS['festival']]):
        entries.append(dict(id=f'festival:{i}', kind='축제', title=_text(row.get('name')), region=_text(row.get('region')),
                            start=_text(row.get('start')), end=_text(row.get('end')), fee_text=_text(row.get('fee_text'))))
    for i, row in enumerate(((data.get('subscriptions') or {}).get('items') or [])[:LIMITS['subscription']]):
        steps = ' / '.join(f"{s.get('label')} {s.get('start')}~{s.get('end')}" for s in row.get('steps') or [])
        entries.append(dict(id=f'subscription:{i}', kind='청약', title=_text(row.get('name')),
                            district=_text(row.get('district')), steps=_text(steps)))
    for i, row in enumerate((data.get('health_notes') or [])[:LIMITS['health']]):
        entries.append(dict(id=f'health:{i}', kind='보건소', district=_text(row.get('district')), sentence=_text(row.get('sentence'))))
    for i, row in enumerate((data.get('topic_cards') or {}).get('topics') or []):
        entries.append(dict(id=f'topic:{i}', kind='주제 카드', title=_text(row.get('title'))))
    if not entries:
        return None
    return dict(schema_version='ops-review-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                day=now.date().isoformat(), entries=entries)


def model_input(host):
    return {'today': host['day'], 'entries': host['entries']}


def review(draft, host):
    """Error codes; empty means every finding points at a real entry field and quotes it exactly."""
    if not isinstance(draft, dict) or set(draft) != {'findings'} or not isinstance(draft['findings'], list):
        return ['draft_shape']
    findings = draft['findings']
    errors = []
    # Every finding is checked; more than MAX_FINDINGS valid ones are cut to the first MAX_FINDINGS afterwards
    # (2026-11-26: the first run returned more than 10 and the whole answer was thrown away).
    by_id = {e['id']: e for e in host['entries']}
    for f in findings:
        if not isinstance(f, dict) or set(f) != {'ref', 'field', 'quote', 'issue'} \
                or not all(isinstance(f[k], str) for k in f):
            errors.append('finding_shape')
            continue
        entry = by_id.get(f['ref'])
        if entry is None:
            errors.append('unknown_ref')
        elif f['field'] in ('id', 'kind') or f['field'] not in entry:
            errors.append('unknown_field')
        elif not QUOTE_MIN <= len(f['quote']) <= QUOTE_MAX or f['quote'] not in entry[f['field']]:
            errors.append('quote_not_in_field')
        if f['issue'] not in ISSUES:
            errors.append('unknown_issue')
    return list(dict.fromkeys(errors))


def public_findings(draft):
    """The part that may leave the private run: references, enum codes and quotes copied from public data,
    the first MAX_FINDINGS in the model's order (the prompt asks for the surest first)."""
    return [{k: f[k] for k in ('ref', 'field', 'issue', 'quote')} for f in draft['findings'][:MAX_FINDINGS]]


def refresh(root, now, data, execute=True):
    """At most one paid call a day, after publication; the attempt is stored before the call so a crash cannot
    open a second one. Returns a public-safe summary; never raises."""
    try:
        current = host(data, now)
        if current is None:
            return {'status': 'no_entries'}
        if not execute:
            return {'status': 'not_requested'}
        day = now.date().isoformat()
        state_path = project_path(root, f'cache/{FOLDER}/days.json')
        state = load(state_path, {'days': {}})
        if day in state['days']:
            return {'status': 'already_tried'}
        digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
        input_path = project_path(root, f'.tools/ai-{FOLDER}-inputs/{day}-{digest}.json')
        save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
        state['days'][day] = {'status': 'attempted'}
        save(state_path, state)
        model = invoke(root, 'ops_review', input_path)
        result = {'status': model.get('status') or 'failed'}
        if model.get('reason'):
            # 2026-11-27: a stop before any request showed no cause. safe_reason text, exit code or class name only.
            result['reason'] = str(model['reason'])[:120]
        if model.get('status') == 'validated_draft':
            draft = load(TRIAL_RUNS / model['run_id'] / 'result.json', None)
            errors = review(draft, current)
            result = {'status': 'rejected', 'errors': errors} if errors else \
                {'status': 'completed', 'findings': public_findings(draft), 'total': len(draft['findings'])}
        elif model.get('status') == 'rejected_draft':
            result = {'status': 'rejected', 'errors': [str(e)[:80] for e in load(
                TRIAL_RUNS / model['run_id'] / 'validation.json', {}).get('errors', [])][:20]}
        state['days'][day].update(status=result['status'], run_id=model.get('run_id'))
        save(state_path, state)
        return result
    except Exception as error:
        return {'status': 'failed', 'reason': type(error).__name__}


def refresh_from_delivery(root, now, execute=True):
    data = load(project_path(root, 'delivery/public/briefing.json'), None)
    if not isinstance(data, dict):
        return {'status': 'no_public_briefing'}
    return refresh(root, now, data, execute)
