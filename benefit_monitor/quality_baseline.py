"""Phase 0 baseline: re-run current local gates on recorded responses. No keys or network.

Classifies every recorded rejection as format, grounding, semantic or transport so later
changes can be compared with the same yardstick. Reads only the private trial folder and
writes a public summary that contains run IDs, codes and counts, never source bodies.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

from .ai_contract import validate
from .claude_trial import evaluate_draft, parse_draft
from .research_guard import REQUIRED_FIELDS

PROJECT = Path(__file__).resolve().parents[1]
TRIAL = PROJECT/'.tools/claude-trial/live'

# Ordered: the first matching pattern decides the category of a rejection reason.
RULES = (
    ('transport', r'invalid_or_truncated_model_output|truncated'),
    ('grounding', r'quote not in successful source|disputed claim requires conflict'),
    ('semantic', r'contradicts|coverage requires review|topic semantics|unrestricted eligibility|'
                 r'restricted eligibility|inverted|conflicting supported'),
    ('format', r'unknown requires|empty claim references|isoformat|invalid extraction contract|'
               r'contract version|reason is only|non-null value|canonical|unknown fee|'
               r'unknown or duplicate|invalid type|invalid enum|missing |unexpected |'
               r"^'[^']+'$|unknown snapshot/topic|claim belongs|ineligible item|duplicate"),
)
CATEGORIES = ('format', 'grounding', 'semantic', 'transport', 'unclassified')


def classify(reason):
    for category, pattern in RULES:
        if re.search(pattern, reason or ''):
            return category
    return 'unclassified'


def _json(path):
    return json.loads(Path(path).read_text())


def _draft(run_id):
    """Prefer the exact provider response; fall back to the saved model output."""
    raw = TRIAL/'responses'/(run_id+'.json')
    if raw.exists():
        response = _json(raw)
        if response.get('stop_reason') != 'end_turn' or any(c.get('type') != 'text' for c in response.get('content', [])):
            return None, 'invalid_or_truncated_model_output'
        return parse_draft(''.join(c['text'] for c in response['content'])), None
    for name in ('model-output.json', 'rejected-result.json', 'result.json'):
        if (TRIAL/'runs'/run_id/name).exists():
            return _json(TRIAL/'runs'/run_id/name), None
    return None, 'response_missing'


def current_gate(kind, draft, host):
    """Apply today's gates. Returns (valid, first_reason, finding_codes)."""
    try:
        if kind == 'research' and draft.get('schema_version') == 'trial-result-v1':
            report = validate(draft, host, 'research')
        else:
            _, report = evaluate_draft(draft, host, kind)
            if report['valid'] and kind == 'research' and 'coverage' not in report:
                # Legacy compact responses get the same restriction coverage gate as v3.
                from .research_guard import audit
                report['coverage'] = audit(draft, host)
                report['valid'] = report['coverage']['valid']
                if not report['valid']:
                    report.setdefault('errors', []).append('required fields or restriction coverage requires review')
    except (ValueError, KeyError, TypeError) as error:
        return False, str(error), []
    findings = [f['code'] for key in ('coverage', 'semantic_review') for f in report.get(key, {}).get('findings', [])]
    errors = report.get('errors') or []
    return report['valid'], (errors[0] if errors else None), sorted(set(findings))


def baseline(trial=TRIAL):
    rows = []
    for run in sorted((trial/'runs').iterdir()):
        if not (run/'input.json').exists():
            continue
        metadata = _json(run/'metadata.json') if (run/'metadata.json').exists() else {}
        host = _json(run/'input.json')
        kind = metadata.get('kind') or ('research' if 'candidates' in host else 'topic')
        history = _json(run/'validation.json') if (run/'validation.json').exists() else {}
        old = history.get('errors') or [history.get('error')]
        draft, problem = _draft(run.name)
        if draft is None:
            valid, reason, findings = False, problem, []
        else:
            valid, reason, findings = current_gate(kind, draft, host)
        usage = metadata.get('usage') or {}
        facts = [f for r in (draft or {}).get('records', []) for f in r.get('facts', []) if isinstance(f, dict)]
        filled = sorted({f['field'] for f in facts if f.get('field') in REQUIRED_FIELDS and f.get('status') in ('supported', 'disputed')})
        rows.append(dict(run_id=run.name, kind=kind, contract=metadata.get('model_output_contract'),
                         input_tokens=usage.get('input_tokens'), output_tokens=usage.get('output_tokens'),
                         filled_required_fields=len(filled) if facts else None,
                         repair=bool(metadata.get('repair_of')), historical_valid=bool(history.get('valid')),
                         historical_reason=next((x for x in old if x), None), current_valid=valid,
                         current_reason=reason, current_findings=findings,
                         category=None if valid else classify(reason)))
    def mean(values):
        values = [v for v in values if isinstance(v, int)]
        return round(sum(values)/len(values), 1) if values else None
    summary = {kind: {'runs': sum(r['kind'] == kind for r in rows),
                      'mean_input_tokens': mean(r['input_tokens'] for r in rows if r['kind'] == kind),
                      'mean_output_tokens': mean(r['output_tokens'] for r in rows if r['kind'] == kind),
                      'mean_filled_required_fields': mean(r['filled_required_fields'] for r in rows if r['kind'] == kind),
                      'current_valid': sum(r['kind'] == kind and r['current_valid'] for r in rows),
                      'categories': dict(Counter(r['category'] for r in rows if r['kind'] == kind and not r['current_valid']))}
               for kind in ('research', 'topic')}
    return {'schema_version': 'quality-baseline-v1', 'network': False, 'runs': rows, 'summary': summary,
            'category_rules': {c: p for c, p in RULES}, 'note': '현재 로컬 검사 재적용 결과이며 사람 의미 검토나 공개 승인이 아니다.'}


def _documents(path):
    try:
        data = _json(path)
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict) or data.get('synthetic') is not False or not isinstance(data.get('documents'), list):
        return []
    return [d for d in data['documents'] if isinstance(d, dict) and isinstance(d.get('body'), str) and d.get('fetch_status') == 'ok']


def evaluation_set(root=PROJECT):
    """Lock dev/holdout split by exact body hash. Holdout = official URLs never sent to a model.

    A URL whose other body version was sent is excluded from holdout: it is not independent.
    The manifest stores hashes and public URLs only; bodies stay in the private .tools folder.
    """
    root = Path(root)
    trial = root/'.tools/claude-trial/live'
    sent = {}
    for path in sorted((trial/'runs').glob('*/input.json')):
        for doc in _documents(path):
            sent.setdefault(hashlib.sha256(doc['body'].encode()).hexdigest(), doc)
    sent_urls = {d['final_url'] for d in sent.values()}
    seen, holdout, variants = set(sent), {}, {}
    for path in sorted((root/'.tools').rglob('*.json')):
        if trial/'runs' in path.parents or trial/'responses' in path.parents:
            continue
        for doc in _documents(path):
            digest = hashlib.sha256(doc['body'].encode()).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            target = variants if doc['final_url'] in sent_urls else holdout
            target[digest] = dict(doc, _path=str(path.relative_to(root)))
    def row(digest, doc, split):
        return dict(split=split, body_sha256=digest, source_id=doc['source_id'], url=doc['final_url'],
                    document_id=doc['id'], retrieved_at=doc.get('retrieved_at'), characters=len(doc['body']),
                    private_path=doc.get('_path'))
    rows = ([row(h, d, 'dev') for h, d in sorted(sent.items())]
            + [row(h, d, 'holdout') for h, d in sorted(holdout.items())]
            + [row(h, d, 'excluded_dev_variant') for h, d in sorted(variants.items())])
    lock = hashlib.sha256('\n'.join(r['split']+':'+r['body_sha256'] for r in rows).encode()).hexdigest()
    counts = Counter(r['split'] for r in rows)
    by_source = {split: dict(Counter(r['source_id'] for r in rows if r['split'] == split)) for split in counts}
    return {'schema_version': 'evaluation-set-v1', 'lock_sha256': lock, 'counts': dict(counts),
            'by_source': by_source, 'documents': rows,
            'rules': ['dev: 이미 모델에 전송한 원문', 'holdout: 같은 URL도 모델에 전송한 적 없는 원문',
                      'excluded_dev_variant: 개발용 URL의 다른 본문 버전이라 독립 표본이 아님',
                      '보류용 원문은 프롬프트·규칙 개발에 사용하지 않는다',
                      '정답 라벨은 사람이 작성하며 이 목록은 라벨을 포함하지 않는다']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--evaluation-set', type=Path)
    args = parser.parse_args()
    if args.evaluation_set:
        manifest = evaluation_set()
        args.evaluation_set.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'lock_sha256': manifest['lock_sha256'], 'counts': manifest['counts']}, ensure_ascii=False))
    data = baseline()
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    print(json.dumps(data['summary'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
