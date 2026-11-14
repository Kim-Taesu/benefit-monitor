"""Manual measurement of request settings on the day's pick inputs (Phase 5). Never publishes.

Question: does adaptive thinking or a higher effort make the festival and benefit cards pass the
host review more often than the regular request (thinking off), and what does it cost? Those two
kinds discard the whole answer on one broken sentence rule, so they are measured first.

Each measurement sends the input the regular run already sent that day, with one other variant from
claude_trial.VARIANTS, through the same CLI, key, ledger and host review. The answer stays in the
private run folder; pick.json is never written here, so nothing measured can reach the page.

Every measurement is an extra paid request on top of the regular daily calls: at most once per
day, kind and variant (4 a day). Approved 2026-11-14 for MAX_DAYS measured days and no later than
LAST_DAY; after that the daily step sends nothing. Extending it needs a new approval.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .ai_review import invoke
from .official_reader import project_path
from .store import load, lock, save

TRIAL_RUNS = Path(__file__).resolve().parents[1] / '.tools/claude-trial/live/runs'
KINDS = ('festival', 'benefit')
BASELINE = 'baseline'
MEASURED = ('adaptive-medium', 'adaptive-high')
STATE = 'cache/variant_trial/results.json'
MAX_ROWS = 600
MAX_DAYS = 7
LAST_DAY = '2026-11-30'
# Microdollars per token, the ledger's fixed Haiku 5.5 rate card.
INPUT_RATE, OUTPUT_RATE = 0.10, 0.50


def _run_report(run_id):
    """What the host decided about a stored run: review result and token use. No model text."""
    row = {'run_id': run_id, 'valid': None, 'errors': [], 'detail': None, 'stop_reason': None,
           'input_tokens': None, 'output_tokens': None, 'microdollars': None}
    if not isinstance(run_id, str) or not run_id or '/' in run_id or run_id.startswith('.'):
        return row
    folder = TRIAL_RUNS / run_id
    try:
        check = json.loads((folder / 'validation.json').read_text())
        row['valid'] = check.get('valid') is True
        row['errors'] = [str(e)[:80] for e in check.get('errors', [])][:20]
        row['detail'] = check.get('detail')
        row['stop_reason'] = check.get('stop_reason')
    except (OSError, ValueError, AttributeError):
        pass
    try:
        usage = json.loads((folder / 'metadata.json').read_text())['usage']
        row['input_tokens'], row['output_tokens'] = usage['input_tokens'], usage['output_tokens']
        row['microdollars'] = round(usage['input_tokens'] * INPUT_RATE + usage['output_tokens'] * OUTPUT_RATE, 2)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return row


def measure(root, now, kinds=KINDS, variants=MEASURED, execute=False):
    """Rows added for today. Without execute nothing is sent and nothing is stored."""
    root = Path(root).resolve()
    if any(k not in KINDS for k in kinds) or any(v not in MEASURED for v in variants):
        raise ValueError('unknown kind or variant')
    day = now.date().isoformat()
    added = []
    with lock(project_path(root, 'cache/variant_trial/.lock')):
        state = load(project_path(root, STATE), {'schema_version': 1, 'rows': []})
        done = {(r['day'], r['kind'], r['variant']) for r in state['rows']}
        measured_days = {r['day'] for r in state['rows'] if r['variant'] != BASELINE}
        if day > LAST_DAY or (day not in measured_days and len(measured_days) >= MAX_DAYS):
            return [{'day': day, 'kind': None, 'variant': None, 'status': 'window_closed'}]

        def store(row):
            state['rows'] = (state['rows'] + [row])[-MAX_ROWS:]
            save(project_path(root, STATE), state)
            done.add((row['day'], row['kind'], row['variant']))
            added.append(row)

        for kind in kinds:
            regular = load(project_path(root, f'cache/{kind}_pick/days.json'), {'days': {}})['days'].get(day)
            if not isinstance(regular, dict) or not regular.get('input_file') or not regular.get('run_id'):
                # No regular answer to compare with (too few candidates, no credit, stopped run).
                added.append({'day': day, 'kind': kind, 'variant': None, 'status': 'no_baseline'})
                continue
            input_path = project_path(root, regular['input_file'])
            if (day, kind, BASELINE) not in done:
                store(dict(day=day, kind=kind, variant=BASELINE, status=regular.get('status'),
                           input_file=regular['input_file'], measured_at=now.isoformat(), **_run_report(regular['run_id'])))
            for variant in variants:
                if (day, kind, variant) in done:
                    continue
                if not execute:
                    added.append({'day': day, 'kind': kind, 'variant': variant, 'status': 'awaiting_authorization'})
                    continue
                # Persist before calling: a crash cannot open a second paid attempt for this cell.
                row = dict(day=day, kind=kind, variant=variant, status='attempted', input_file=regular['input_file'],
                           measured_at=now.isoformat())
                store(row)
                model = invoke(root, kind, input_path, variant=variant)
                row.update(status=model['status'], **_run_report(model.get('run_id')))
                save(project_path(root, STATE), state)
                if model['status'] == 'credit_exhausted':
                    return added
    return added


def summary(rows):
    """Per kind and variant: how many answers were sent, how many the host review passed, and cost.

    Only days where the regular run and the variant both produced an answer are comparable, so
    each line also counts the days it shares with the baseline."""
    answered = [r for r in rows if r.get('status') in ('validated_draft', 'rejected_draft')]
    base_days = {(r['kind'], r['day']) for r in answered if r['variant'] == BASELINE}
    out = []
    for kind in KINDS:
        for variant in (BASELINE,) + MEASURED:
            cell = [r for r in answered if r['kind'] == kind and r['variant'] == variant and (kind, r['day']) in base_days]
            if not cell:
                continue
            passed = sum(r.get('valid') is True for r in cell)
            tokens = [r['output_tokens'] for r in cell if isinstance(r.get('output_tokens'), int)]
            cost = [r['microdollars'] for r in cell if isinstance(r.get('microdollars'), (int, float))]
            errors = {}
            for r in cell:
                for code in r.get('errors') or ([r['detail']] if r.get('detail') else []):
                    errors[code] = errors.get(code, 0) + 1
            out.append({'kind': kind, 'variant': variant, 'answers': len(cell), 'passed': passed,
                        'pass_rate': round(passed / len(cell), 3),
                        'mean_output_tokens': round(sum(tokens) / len(tokens)) if tokens else None,
                        'usd': round(sum(cost) / 1_000_000, 6) if cost else None,
                        'errors': dict(sorted(errors.items(), key=lambda pair: -pair[1]))})
    return out


def _ledger_ids(root):
    try:
        rows = json.loads((Path(root).resolve() / '.tools/claude-trial/live/budget.json').read_text())['requests']
        return [row['id'] for row in rows]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def daily_step(root, now, execute):
    """The daily run's measurement step: today's cells and the running totals, without model text.

    request_ids: ledger rows this step added, so the caller can keep a refused measurement request
    apart from the day's regular provider failures."""
    before = set(_ledger_ids(root))
    rows = measure(root, now, execute=execute)
    stored = load(project_path(Path(root).resolve(), STATE), {'rows': []})['rows']
    return {'request_ids': [i for i in _ledger_ids(root) if i not in before],
            'today': [{k: r.get(k) for k in ('kind', 'variant', 'status', 'valid', 'errors', 'detail', 'output_tokens')}
                      for r in rows],
            'measured_days': len({r['day'] for r in stored if r['variant'] != BASELINE}),
            'summary': summary(stored)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('measure', 'summary'))
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--execute', action='store_true', help='send the paid measurement requests')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'measure':
        rows = measure(root, datetime.now(ZoneInfo('Asia/Seoul')), execute=args.execute)
        print(json.dumps([{k: r.get(k) for k in ('day', 'kind', 'variant', 'status', 'valid', 'errors')} for r in rows],
                         ensure_ascii=False, indent=2))
        return 0
    rows = load(project_path(root, STATE), {'rows': []})['rows']
    print(json.dumps(summary(rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
