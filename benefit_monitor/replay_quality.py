"""Read recorded trial responses and rerun local gates. No keys or network."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .ai_contract import validate
from .claude_trial import parse_draft
from .daily_topics import fallback
from .topic_semantics import review

PROJECT=Path(__file__).resolve().parents[1]


def _local(path, parent):
    path=Path(path).resolve()
    if not path.is_relative_to(parent.resolve()) or not path.is_relative_to(PROJECT):
        raise ValueError('replay path outside permitted directory')
    return path


def _json(path):
    if path.stat().st_size > 2*1024*1024:
        raise ValueError('oversized replay artifact')
    return json.loads(path.read_text())


def _recorded(root, request_id, ledger, kind):
    if not re.fullmatch('[0-9a-f]{64}',request_id):
        raise ValueError('invalid recorded request ID')
    run=_local(root/'live/runs'/request_id,root)
    host=_json(_local(run/'input.json',root))
    metadata=_json(_local(run/'metadata.json',root))
    if metadata['kind'] != kind or metadata['input_sha256'] != hashlib.sha256(json.dumps(host,ensure_ascii=False,sort_keys=True).encode()).hexdigest():
        raise ValueError('recorded input hash mismatch')
    raw=_local(root/'live/responses'/(request_id+'.json'),root).read_bytes()
    row=ledger[request_id]
    if row['status'] != 'completed' or hashlib.sha256(raw).hexdigest() != row['response_sha256']:
        raise ValueError('recorded response hash mismatch')
    response=json.loads(raw)
    if response['stop_reason'] != 'end_turn' or any(c['type'] != 'text' for c in response['content']):
        raise ValueError('recorded response incomplete')
    return host,parse_draft(''.join(c['text'] for c in response['content']))


def _editorial_host(host, basis):
    annotated=deepcopy(host)
    claims={c['id']:c for c in host['approved_claims']}
    for item in annotated['approved_items']:
        entry=basis['items'].get(item['item_id'])
        if entry is None:
            continue
        refs=entry['evidence_claim_ids']
        proofs=entry['evidence_quotes']
        if not proofs or set(refs) != {p['claim_id'] for p in proofs}:
            raise ValueError('editorial basis proof missing')
        for proof in proofs:
            claim=claims[proof['claim_id']]
            value=claim.get('value')
            text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
            if (claim['item_id'] != item['item_id'] or proof['claim_id'] not in item['claim_ids']
                    or not proof['quote'] or proof['quote'] not in text):
                raise ValueError('editorial basis quote mismatch')
        item['topic_basis']={k:deepcopy(entry[k]) for k in ('topic_ids','title_facets','evidence_claim_ids')}
    return annotated


def replay(root, basis):
    root=_local(root,PROJECT)
    state=_json(_local(root/'live/budget.json',root))
    ledger={r['id']:r for r in state['requests']}
    research,topics=[],[]
    for row in _json(_local(root/'core-pilot-results.json',root)):
        rid=row['report']['run_id']
        host,draft=_recorded(root,rid,ledger,'research')
        report=validate(draft,host,'research')
        research.append({'candidate':row['reference_candidate_id'],'request_id':rid,'validation':report})
    for row in _json(_local(root/'daily-replay-results.json',root)):
        rid=row['report']['run_id']
        host,draft=_recorded(root,rid,ledger,'topic')
        structural=validate(draft,host,'topic')
        annotated=_editorial_host(host,basis)
        semantic=review(draft,annotated) if structural['valid'] else {'valid':False,'findings':[{'code':'structural_failure'}]}
        cards=fallback(draft['topics'],annotated) if structural['valid'] else []
        topics.append({'reference_time':row['day'],'request_id':rid,'input_count':len(host['approved_items']),
                       'structural':structural,'semantic':semantic,'fallback_cards':cards})
    return dict(scope='recorded_v1_development_replay',new_api_calls=0,publication_approved=False,
                research=research,topics=topics,research_valid=sum(r['validation']['valid'] for r in research),
                topic_structural_valid=sum(r['structural']['valid'] for r in topics),
                topic_semantic_valid=sum(r['semantic']['valid'] for r in topics),
                extraction_v2_model_quality='not_measured',basis_sha256=hashlib.sha256(json.dumps(basis,ensure_ascii=False,sort_keys=True).encode()).hexdigest())


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot-root',type=Path,default=root/'.tools/claude-trial')
    parser.add_argument('--basis',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=_local(args.output,root)
    if output.is_relative_to(args.pilot_root.resolve()/'live') or output.exists():
        parser.error('output must be new and outside recorded live artifacts')
    basis=_json(_local(args.basis,root))
    report=replay(_local(args.pilot_root,root),basis)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:
        f.write(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('new_api_calls','research_valid','topic_structural_valid','topic_semantic_valid','extraction_v2_model_quality')},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
