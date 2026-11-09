"""Daily AI quality check of collected data (kind verify). Runs before research in the AI run.

1. audit: human-approved public items, least recently checked first (each at most every
   AUDIT_DAYS). A code-confirmed contradiction holds the item (hold_reason ai_contradicted) until a
   human re-verifies it; nothing is edited. A changed official body is reported in changed_ids.
2. triage: review candidates never triaged, or not for TRIAGE_DAYS. Code-confirmed ended or
   not_benefit takes the candidate out of the review queue (ai_dismissed, keyed to the body hash);
   ongoing/upcoming raise its queue priority (ai_triage).

Only the operational state's metadata changes (reason codes, hashes, times). The private findings
(claim, official quotes) stay in the encrypted runtime and in the public quality summary.
"""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from . import cost_policy
from .ai_review import invoke, TRIAL_RUNS
from .models import Benefit
from .official_reader import OfficialReader, project_path
from .store import load, save, lock
from . import verify_contract as vc

AUDIT_DAYS = 7
TRIAGE_DAYS = 7
# A dismissed candidate still listed is re-read this often; only a changed body is triaged again.
DISMISSED_DAYS = 30
STATE = 'cache/ai_verify/state.json'
FINDINGS = 'cache/ai_verify/findings.json'
SENTENCE = re.compile(r'[^.。]+[.。]?')


def fingerprint():
    root = Path(__file__).resolve().parents[1]
    names = ('docs/ai/prompts/verify-system.md', 'benefit_monitor/verify_contract.py')
    return hashlib.sha256(b'\n'.join((root/p).read_bytes() for p in names)).hexdigest()


def claims_of(item):
    """Short checkable claims from a human-approved item (summary, condition sentences, dates)."""
    rows = [('summary', item.summary)]
    rows += [('conditions', s.strip()) for s in SENTENCE.findall(item.conditions or '') if len(s.strip()) >= 6]
    if item.valid_from or item.valid_until:
        rows.append(('period', f"기간 {item.valid_from or ''}~{item.valid_until or ''}".strip()))
    if item.deadline_at:
        rows.append(('deadline', f'신청 마감 {item.deadline_at}'))
    rows = [(f, t[:vc.MAX_CLAIM_TEXT]) for f, t in rows if t and t.strip()][:vc.MAX_CLAIMS]
    return [dict(claim_id=f'c{i}', field=f, text=t) for i, (f, t) in enumerate(rows, 1)]


def _due(row, days, now):
    try:
        return now - datetime.fromisoformat(row['last_checked_at']) >= timedelta(days=days)
    except (KeyError, TypeError, ValueError):
        return True


def _result(run_id):
    folder = TRIAL_RUNS/run_id
    if not re.fullmatch('[0-9a-f]{64}', run_id or '') or not folder.resolve().is_relative_to(TRIAL_RUNS.resolve()):
        raise ValueError('invalid verify run id')
    return json.loads((folder/'result.json').read_text())


def run(root, approved, candidates, state, sources, now, max_items=0, execute=False):
    """Check up to max_items within the run's HTTP budget; mutates state['items'] metadata."""
    root = Path(root).resolve()
    out = dict(checked=0, held=0, dismissed=0, prioritized=0, unchanged=0, changed_ids=[], failures=[],
               credit_exhausted=False)
    if max_items <= 0:
        return out
    records = state.setdefault('items', {})
    allowed = lambda source: sources.get(source, {}).get('ai_review', True)
    today = now.date().isoformat()
    approved_ids = {i.id for i in approved}
    with lock(project_path(root, 'cache/ai_verify/.lock')):
        vstate = load(project_path(root, STATE), {'items': {}})
        findings = load(project_path(root, FINDINGS), {})
        work = []
        for item in approved:
            if allowed(item.source) and (not item.valid_until or item.valid_until >= today):
                if _due(vstate['items'].get(item.id, {}), AUDIT_DAYS, now):
                    work.append(('audit', item.id, item.data(), claims_of(item)))
        for data in candidates:
            item = Benefit(**{k: v for k, v in data.items() if k in Benefit.__dataclass_fields__})
            if item.id in approved_ids or not allowed(item.source):
                continue
            days = DISMISSED_DAYS if records.get(item.id, {}).get('ai_dismissed') else TRIAGE_DAYS
            if _due(vstate['items'].get(item.id, {}), days, now):
                work.append(('triage', item.id, data, []))
        # Least recently checked first; audits before triage at equal age.
        work.sort(key=lambda w: (vstate['items'].get(w[1], {}).get('last_checked_at', ''), w[0] != 'audit'))
        reader = OfficialReader(root, now)
        prompt = fingerprint()
        misses = 0  # Consecutive calls without a result (e.g. a rejected grammar probe): stop for today.
        for purpose, iid, data, claims in work[:max_items]:
            try:
                doc = reader.read({'source': data['source'], 'url': data['url'], 'title': data.get('title', '')})
            except Exception as error:
                out['failures'].append({'item_id': iid, 'code': 'official_fetch_failed', 'error_type': type(error).__name__})
                if cost_policy.budget.used >= cost_policy.budget.limit:
                    break  # This run's public HTTP budget is spent; the rest waits for tomorrow.
                continue
            previous = vstate['items'].get(iid, {})
            if purpose == 'audit' and previous.get('body_hash') and previous['body_hash'] != doc['body_hash']:
                out['changed_ids'].append(iid)
            doc = {k: v for k, v in doc.items() if k != 'links'}
            host = dict(schema_version=vc.INPUT, mode='api_agent', synthetic=False, now=now.isoformat(), purpose=purpose,
                        item=dict(item_id=iid, source_id=data['source'], title=data.get('title', ''), claims=claims),
                        documents=[doc])
            signature = hashlib.sha256(json.dumps([purpose, iid, doc['body_hash'], claims, prompt],
                                                  ensure_ascii=False).encode()).hexdigest()
            row = dict(purpose=purpose, body_hash=doc['body_hash'], signature=signature, last_checked_at=now.isoformat())
            fresh = False
            if previous.get('signature') == signature and previous.get('decision'):
                decision = previous['decision']
                out['unchanged'] += 1
            else:
                if not execute:
                    # No paid call: still remember the body so a later change is reported.
                    vstate['items'][iid] = dict(row, decision=None)
                    continue
                path = project_path(root, '.tools/ai-inputs/verify-' + signature + '.json')
                save(path, host)
                model = invoke(root, 'verify', path)
                path.unlink(missing_ok=True)  # The run folder keeps its own copy of the input.
                if model['status'] == 'credit_exhausted':
                    out['credit_exhausted'] = True
                    break
                if model['status'] != 'validated_draft':
                    out['failures'].append({'item_id': iid, 'code': model['status']})
                    vstate['items'][iid] = dict(row, decision=None, run_id=model['run_id'])
                    misses += 1
                    if misses >= 3:
                        out['stopped'] = 'no_results'
                        break
                    continue
                misses = 0
                try:
                    decision = vc.decide(_result(model['run_id']), host, now)
                except (OSError, ValueError, KeyError, TypeError):
                    # Never crash after a paid call; the run folder stays for inspection.
                    out['failures'].append({'item_id': iid, 'code': 'unreadable_result'})
                    vstate['items'][iid] = dict(row, decision=None, run_id=model['run_id'])
                    continue
                row['run_id'] = model['run_id']
                out['checked'] += 1
                fresh = True
            vstate['items'][iid] = dict(row, decision=decision)
            target = records.setdefault(iid, dict(source=data['source'], first_seen_at=now.isoformat()))
            if decision['action'] != 'dismiss' and target.get('ai_dismissed'):
                target.pop('ai_dismissed')  # The official body changed and is no longer ended / not a benefit.
            # Only a fresh judgment holds: a human who re-verified the same body overrides a cached one.
            if decision['action'] == 'hold' and fresh and not target.get('hold_at'):
                target.update(hold_at=now.isoformat(), hold_reason='ai_contradicted')
                findings[iid] = dict(url=data['url'], title=data.get('title', ''), at=now.isoformat(),
                                     claims=[dict(claim=f['claim_text'], official_quotes=f['quotes']) for f in decision['findings']])
                out['held'] += 1
            elif decision['action'] == 'dismiss':
                target['ai_dismissed'] = dict(reason=decision['reason'], body_hash=doc['body_hash'], at=now.isoformat())
                target.pop('pending_reason', None); target.pop('pending_deadline', None)
                out['dismissed'] += 1
            elif decision['action'] == 'prioritize':
                target['ai_triage'] = decision['reason']
                out['prioritized'] += 1
        save(project_path(root, STATE), vstate)
        save(project_path(root, FINDINGS), findings)
    return out
