"""Offline, non-publishing evaluation of fixed contracts and recorded responses.

No credentials, provider calls, or production state mutations. Historical responses are
not a current-model benchmark; synthetic fixtures are only a gate regression suite.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import time

from . import auto_publish, verify_contract, wire_format
from .claude_trial import evaluate_draft, parse_draft, SYSTEM_PROMPTS, system_prompt, TASKS
from .quality_baseline import classify, current_gate

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = Path('/Users/user/personal/benefit-monitor').resolve()
DATA = ROOT/'docs/ai/evaluation'
STAGES = ('collection', 'read', 'extraction', 'validation', 'publication', 'recommendation', 'response')
KINDS = set(SYSTEM_PROMPTS)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def recorded_input_hash(host):
    # Existing claude_trial metadata uses json.dumps' default separators.
    return hashlib.sha256(json.dumps(host, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def local(path, parent):
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(Path(parent).resolve()) or not resolved.is_relative_to(ALLOWED):
        raise ValueError('evaluation path outside permitted directory')
    return resolved


def read_json(path, parent):
    path = local(path, parent)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('oversized evaluation file')
    return json.loads(path.read_text())


def provenance():
    files = list((ROOT/'benefit_monitor').rglob('*.py')) + list((ROOT/'docs/ai/schemas').glob('*.json'))
    files += [ROOT/'sources.yaml']
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(local(p, ROOT).read_bytes()).hexdigest() for p in sorted(files)}
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    return dict(commit=commit, code_sha256=digest(hashes), file_hashes=hashes,
                prompt_sha256={k:digest({'system':system_prompt(ROOT,k),'task':TASKS[k]}) for k in sorted(KINDS)})


def validate_contract(cases, contract):
    for value in (cases, contract):
        if value.get('version') != 1 or not isinstance(value.get('cases'), list) or not value['cases']:
            raise ValueError('invalid evaluation contract')
        ids = [c['id'] for c in value['cases']]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate evaluation case')
    if {c['id'] for c in cases['cases']} != {c['id'] for c in contract['cases']}:
        raise ValueError('case/expectation mismatch')
    for row in contract['cases']:
        expected = row.get('expected')
        if not isinstance(expected, dict) or not expected or not set(expected) <= {'valid','publish','action','reasons','record'}:
            raise ValueError('missing or unsupported expectation')
        if not all(k in row for k in ('description','tags','expected_facts','forbidden_claims','evidence_ids')):
            raise ValueError('incomplete evaluation label')


def observe(case):
    host, draft, kind = case['host'], case['draft'], case['kind']
    now = datetime.fromisoformat(case.get('now') or host.get('now') or '2026-11-14T07:00:00+09:00')
    if now.tzinfo is None:
        raise ValueError('evaluation requires timezone')
    if kind not in KINDS:
        raise ValueError('unsupported evaluation kind')
    try:
        if kind == 'research':
            result = auto_publish.decide(draft, host, now, case.get('takedowns', []))
            record = result.get('record')
            return dict(publish=result['publish'], reasons=result['reasons'],
                        record={k:record.get(k) for k in ('valid_until','deadline_at','fee_status')} if record else None)
        if kind == 'verify':
            parsed = verify_contract.from_wire(draft, host)
            decision = verify_contract.decide(parsed, host, now)
            return dict(valid=True, action=decision['action'], reasons=[decision['reason']] if decision['reason'] else [])
        _, result = evaluate_draft(draft, host, kind)
        return dict(valid=result['valid'], reasons=result.get('errors', []))
    except (ValueError, KeyError, TypeError, IndexError):
        return dict(valid=False, reasons=['contract'])


def matches(actual, expected):
    for key,value in expected.items():
        if key == 'reasons':
            if not set(value) <= set(actual.get('reasons', [])):
                return False
        elif key == 'record':
            if not isinstance(actual.get(key), dict) or not all(actual[key].get(k) == v for k,v in value.items()):
                return False
        elif key not in actual or actual[key] != value:
            return False
    return True


def run_cases(cases_path=DATA/'cases.json', contract_path=DATA/'contract.json'):
    cases, contract = read_json(cases_path, ROOT), read_json(contract_path, ROOT)
    validate_contract(cases, contract)
    labels = {r['id']:r for r in contract['cases']}
    rows=[]
    for case in cases['cases']:
        start=time.perf_counter()
        actual=observe(case)
        label=labels[case['id']]
        rows.append(dict(id=case['id'], kind=case['kind'], tags=label['tags'], input_sha256=digest(case),
                         expected=label['expected'], actual=actual, passed=matches(actual,label['expected']),
                         local_gate_ms=round((time.perf_counter()-start)*1000,3)))
    unsafe=sum((r['expected'].get('publish') is False and r['actual'].get('publish') is True)
               or (r['expected'].get('valid') is False and r['actual'].get('valid') is True) for r in rows)
    missed=sum((r['expected'].get('publish') is True and r['actual'].get('publish') is not True)
               or (r['expected'].get('valid') is True and r['actual'].get('valid') is not True) for r in rows)
    return dict(version=1, scope='synthetic_gate_regression', origin=cases['origin'],
                contract_review=contract.get('review_status'), contract_sha256=digest(contract), cases_sha256=digest(cases),
                generated_at=datetime.now(timezone.utc).isoformat(), provenance=provenance(),
                new_api_calls=0, model_quality='not_measured', rows=rows,
                summary=dict(cases=len(rows), passed=sum(r['passed'] for r in rows), failed=sum(not r['passed'] for r in rows),
                             unsafe_acceptances=unsafe, valid_cases_rejected=missed,
                             pass_rate=sum(r['passed'] for r in rows)/len(rows)))


def summarize_events(events, expected_runs=None):
    """Import measured observations; no timestamps/costs/user responses are invented."""
    seen=set()
    for e in events:
        if (not isinstance(e.get('run_id'),str) or not e['run_id'] or e.get('stage') not in STAGES
                or e.get('status') not in ('ok','failed','held','skipped')
                or (e.get('reason') is not None and not isinstance(e['reason'],str))):
            raise ValueError('invalid stage observation')
        identity=(e['run_id'],e['stage'])
        if identity in seen:raise ValueError('duplicate stage observation')
        seen.add(identity)
        for field in ('duration_ms','cost_usd'):
            value=e.get(field)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
                raise ValueError('invalid observation measurement')
        if e.get('useful') is not None and (e['stage']!='response' or type(e['useful']) is not bool):
            raise ValueError('invalid user response')
    def total(rows, field):
        return sum(r[field] for r in rows) if rows and all(r.get(field) is not None for r in rows) else None
    stages={}
    for stage in STAGES:
        rows=[e for e in events if e['stage']==stage]
        stages[stage]=dict(observations=len(rows), statuses=dict(Counter(r['status'] for r in rows)),
                           reasons=dict(Counter(r['reason'] for r in rows if r.get('reason'))),
                           duration_ms=total(rows,'duration_ms'), cost_usd=total(rows,'cost_usd'))
    observed_runs={e['run_id'] for e in events}
    expected_runs=observed_runs if expected_runs is None else set(expected_runs)
    if not observed_runs<=expected_runs:raise ValueError('observation outside expected runs')
    cost_runs={e['run_id'] for e in events if e['stage']=='extraction' and e.get('cost_usd') is not None}
    missing_cost_runs=sorted(expected_runs-cost_runs)
    cost=total(events,'cost_usd') if expected_runs and not missing_cost_runs else None
    ratings=[e['useful'] for e in events if e['stage']=='response' and type(e.get('useful')) is bool]
    useful=sum(ratings)
    return dict(stages=stages, runs=len(expected_runs), total_cost_usd=cost,
                known_cost_usd=sum(e.get('cost_usd') or 0 for e in events),
                missing_cost_runs=missing_cost_runs, cost_scope='recorded_model_cost_not_provider_invoice',
                rated_recommendations=len(ratings), useful_recommendations=useful if ratings else None,
                cost_per_useful_recommendation_usd=cost/useful if cost is not None and useful else None)


def _saved_draft(root, run, run_id):
    response=root/'responses'/(run_id+'.json')
    if response.exists():
        raw=read_json(response,root)
        if raw.get('stop_reason')!='end_turn' or any(b.get('type')!='text' for b in raw.get('content',[])):
            return None,'incomplete_response'
        return parse_draft(''.join(b['text'] for b in raw['content'])),None
    for name in ('model-output.json','rejected-result.json','result.json'):
        if (run/name).exists():
            return read_json(run/name,root),None
    return None,'missing_response'


def decode_recorded(kind,draft,host):
    if not isinstance(draft,dict):raise ValueError('invalid recorded draft')
    if 'wire_version' in draft:
        return wire_format.from_wire(kind,draft,host)
    # evaluate_draft('verify') assumes from_wire already validated evidence IDs.
    if kind=='verify':raise ValueError('verify replay requires original wire response')
    return draft


def replay(root):
    root=local(root,ALLOWED)
    if not (root/'runs').is_dir():
        raise ValueError('recorded runs directory missing')
    # The local ledger is read only for cost and response integrity; keys are never read.
    ledger = {}
    if (root/'budget.json').exists():
        ledger = {r['id']:r for r in read_json(root/'budget.json',root)['requests']}
    rows=[];events=[]
    for run in sorted(local(root/'runs',root).iterdir()):
        if not re.fullmatch('[0-9a-f]{64}',run.name) or not run.is_dir():
            continue
        local(run,root)
        row=dict(run_id=run.name, status='artifact_invalid', current_valid=False)
        try:
            host=read_json(run/'input.json',root);meta=read_json(run/'metadata.json',root)
            kind=meta.get('kind')
            row.update(kind=kind, model=meta.get('model'), recorded_prompt_sha256=meta.get('prompt_sha256'),
                       input_sha256=recorded_input_hash(host), reference_time=host.get('now'))
            if meta.get('input_sha256') != row['input_sha256']:
                row['status']='input_hash_mismatch'
            elif kind not in KINDS:
                row['status']='unsupported_kind'
            else:
                charge=ledger.get(run.name,{})
                amount=charge.get('charged_microdollars')
                row['recorded_charge_usd']=(amount/1_000_000 if charge.get('status')=='completed'
                                            and type(amount)is int and amount>=0 else None)
                row['ledger_status']=charge.get('status')
                response=root/'responses'/(run.name+'.json')
                recorded_hash=charge.get('response_sha256')
                if response.exists() and recorded_hash and hashlib.sha256(local(response,root).read_bytes()).hexdigest()!=recorded_hash:
                    row['status']='response_hash_mismatch'
                    rows.append(row)
                    continue
                docs=host.get('documents',[])
                if docs:
                    ok=all(d.get('fetch_status')=='ok' for d in docs)
                    events.append(dict(run_id=run.name,stage='read',status='ok' if ok else 'failed',
                                       reason=None if ok else 'fetch_failed',duration_ms=None,cost_usd=0))
                draft,problem=_saved_draft(root,run,run.name)
                if problem:
                    row['status']=problem
                else:
                    row['draft_sha256']=digest(draft)
                    events.append(dict(run_id=run.name,stage='extraction',status='ok',reason=None,
                                       duration_ms=None,cost_usd=row['recorded_charge_usd']))
                    try:
                        draft=decode_recorded(kind,draft,host)
                        valid,reason,findings=current_gate(kind,draft,host)
                    except (ValueError,KeyError,TypeError,IndexError):
                        valid,reason,findings=False,'invalid extraction contract',[]
                    row.update(status='replayed',current_valid=valid,category=None if valid else classify(reason),findings=findings)
                    # Do not export arbitrary provider exception text or source bodies.
                    events.append(dict(run_id=run.name,stage='validation',status='ok' if valid else 'failed',
                                       reason=row['category'],duration_ms=None,cost_usd=0))
                    if kind=='topic':
                        events.append(dict(run_id=run.name,stage='recommendation',status='ok' if valid else 'held',
                                           reason=None if valid else 'validation_rejected',duration_ms=None,cost_usd=0))
                    if kind=='research' and draft.get('schema_version')=='research-extraction-v3':
                        decision=auto_publish.decide(draft,host,datetime.fromisoformat(host['now']),[])
                        row['historical_time_publish']=decision['publish']
                        row['publication_reasons']=decision['reasons']
                        events.append(dict(run_id=run.name,stage='publication',status='ok' if decision['publish'] else 'held',
                                           reason=','.join(decision['reasons']) or None,duration_ms=None,cost_usd=0))
                row['tokens']={k:v for k,v in (meta.get('usage') or {}).items()
                               if k in ('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens') and type(v)is int}
        except (OSError,ValueError,KeyError,TypeError,IndexError):
            row['status']='artifact_invalid'
        rows.append(row)
    return dict(version=1,scope='historical_response_replay',generated_at=datetime.now(timezone.utc).isoformat(),
                provenance=provenance(),new_api_calls=0,model_quality='not_measured',rows=rows,
                summary=dict(runs=len(rows),validated=sum(r['current_valid'] for r in rows),
                             statuses=dict(Counter(r['status'] for r in rows)),kinds=dict(Counter(r.get('kind','unknown') for r in rows)),
                             historical_cost_usd=(sum(r['recorded_charge_usd'] for r in rows)
                                                  if rows and all(r.get('recorded_charge_usd') is not None for r in rows) else None),
                             cost_covered_runs=sum(r.get('recorded_charge_usd') is not None for r in rows),
                             known_recorded_charge_usd=sum(r.get('recorded_charge_usd') or 0 for r in rows)),
                observations=summarize_events(events,expected_runs=[r['run_id'] for r in rows]),
                note='과거 입력 시각으로 재검사. 현재 원문·현재 모델 품질·실제 공개 상태를 확인하지 않음. '
                     '비용은 일치하는 완료 요청의 로컬 원장 기록만 사용하며 실제 청구액이 아님. 미관측 비용·사용자 반응은 null.')


def compare_recorded_topics(root):
    """Compare only replay-valid topic output with the existing rule over the SAME host.

    Packets/keys contain private input; callers store them under .tools, never public docs.
    Coverage and duplicate links are descriptive, not a useful-recommendation score.
    """
    from .daily_topics import basis_cards
    root=local(root,ALLOWED)
    baseline=replay(root)
    packets=[];keys=[];rows=[]
    for row in baseline['rows']:
        if row.get('kind')!='topic':continue
        entry={'run_id':row['run_id'],'status':'not_comparable'}
        if row['status']=='replayed' and row['current_valid']:
            run=root/'runs'/row['run_id']
            host=read_json(run/'input.json',root)
            draft,_=_saved_draft(root,run,row['run_id'])
            draft=decode_recorded('topic',draft,host)
            rule=basis_cards(host)
            if rule:
                packet,key=blind_pair(row['run_id'],host,rule,draft['topics'])
                packets.append(packet);keys.append(key)
                def metrics(cards):
                    ids=[link['item_id'] for card in cards for link in card['item_links']]
                    return dict(cards=len(cards),links=len(ids),unique_items=len(set(ids)),duplicate_links=len(ids)-len(set(ids)))
                entry.update(status='comparable',input_sha256=digest(host),reference_time=host.get('now'),
                             rule=metrics(rule),ai=metrics(draft['topics']),usefulness='not_rated')
        rows.append(entry)
    return dict(scope='historical_topic_comparison',rows=rows,comparable=len(packets),
                useful_rate=None,cost_per_useful_recommendation_usd=None),packets,keys


def blind_arms(case_id):
    return {'A':'rule','B':'ai'} if int(digest(case_id)[0],16)%2 else {'A':'ai','B':'rule'}


def blind_pair(case_id, host, rule, ai):
    arms=blind_arms(case_id)
    outputs={'rule':rule,'ai':ai}
    packet=dict(id=case_id,input_sha256=digest(host),context=host,
                alternatives={arm:outputs[source] for arm,source in arms.items()},
                ratings={arm:dict(useful=None,grounded=None,duplicate=None) for arm in arms})
    key=dict(id=case_id,input_sha256=digest(host),arms=arms,packet_sha256=digest(packet))
    return packet,key


def score_ratings(packet,key,ratings):
    if key['packet_sha256']!=digest(packet) or key['id']!=packet['id'] or key['input_sha256']!=packet['input_sha256']:
        raise ValueError('blind packet mismatch')
    if key['arms']!=blind_arms(packet['id']):raise ValueError('blind mapping mismatch')
    if set(ratings)!=set(key['arms']):
        raise ValueError('rating arm mismatch')
    rows=[]
    for arm,values in ratings.items():
        if set(values)!={'useful','grounded','duplicate'} or any(v is not None and type(v)is not bool for v in values.values()):
            raise ValueError('invalid rating')
        rows.append(dict(source=key['arms'][arm],**values))
    return dict(id=packet['id'],rated_arms=sum(r['useful'] is not None for r in rows),rows=rows)


def score_batch(packets,keys,ratings):
    if (len({p['id'] for p in packets})!=len(packets) or len({k['id'] for k in keys})!=len(keys)
            or {p['id'] for p in packets}!={k['id'] for k in keys}
            or set(ratings)!={p['id'] for p in packets}):
        raise ValueError('comparison batch mismatch')
    lookup={k['id']:k for k in keys}
    rows=[score_ratings(p,lookup[p['id']],ratings[p['id']]) for p in packets]
    def rate(source):
        values=[r['useful'] for item in rows for r in item['rows'] if r['source']==source and r['useful'] is not None]
        return sum(values)/len(values) if values else None
    return dict(rows=rows,rated_arms=sum(r['rated_arms'] for r in rows),
                useful_rate={'rule':rate('rule'),'ai':rate('ai')})


def write_new(path, value):
    path=local(path,ROOT)
    if path.exists():
        raise ValueError('evaluation output already exists')
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:
        f.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['cases','replay','compare','events','blind','score'])
    p.add_argument('--input',type=Path)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--key',type=Path)
    p.add_argument('--ratings',type=Path)
    args=p.parse_args()
    if args.command=='cases':
        result=run_cases()
    elif args.command=='replay':
        if args.input is None:p.error('--input recorded live directory required')
        result=replay(args.input)
    elif args.command=='events':
        if args.input is None:p.error('--input observation array required')
        result=summarize_events(read_json(args.input,ROOT))
    elif args.command=='compare':
        if args.input is None or args.key is None or args.ratings is None:
            p.error('--input live directory, --key key file, --ratings packet file required')
        # Explicit private destinations: comparisons include the original host context.
        targets=[local(args.key,ROOT/'.tools'),local(args.ratings,ROOT/'.tools'),local(args.output,ROOT)]
        if len(set(targets))!=3 or any(t.exists() for t in targets):p.error('distinct new outputs required')
        result,packets,keys=compare_recorded_topics(args.input)
        write_new(args.key,keys);write_new(args.ratings,packets)
    elif args.command=='blind':
        if args.input is None or args.key is None:p.error('--input and --key required')
        data=read_json(args.input,ROOT)
        if args.key.resolve()==args.output.resolve():p.error('key and packet must be separate')
        result,key=blind_pair(data['id'],data['host'],data['rule'],data['ai'])
        # Validate both destinations before writing either file.
        if local(args.output,ROOT).exists() or local(args.key,ROOT).exists():p.error('output already exists')
        write_new(args.key,key)
    else:
        if args.input is None or args.key is None or args.ratings is None:p.error('--input, --key, --ratings required')
        packets=read_json(args.input,ROOT);keys=read_json(args.key,ROOT);ratings=read_json(args.ratings,ROOT)
        result=score_batch(packets,keys,ratings) if isinstance(packets,list) else score_ratings(packets,keys,ratings)
    write_new(args.output,result)
    print(json.dumps(result.get('summary',{'status':'written'}),ensure_ascii=False))
    return 1 if args.command=='cases' and result['summary']['failed'] else 0


if __name__=='__main__':
    raise SystemExit(main())
