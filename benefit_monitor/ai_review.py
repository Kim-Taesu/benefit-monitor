"""Optional collection → change detection → model → private human-review queue."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from . import cost_policy
from . import auto_publish
from . import auto_release
from .cross_sources import allowed_domains, related_urls
from .models import Benefit
from .official_reader import OfficialReader, project_path
from .validation import official
from .store import load,save,lock


def fingerprint(_runtime_root):
    """Changes when the model prompt or the structured-output wire contract changes."""
    root=Path(__file__).resolve().parents[1]
    names=('docs/ai/prompts/research-system.md','benefit_monitor/wire_format.py',
           'docs/ai/schemas/research-extraction-v3.schema.json')
    return hashlib.sha256(b'\n'.join((Path(root)/p).read_bytes() for p in names)).hexdigest()


def invoke(root,kind,input_path):
    """Only the existing CLI owns API credentials, reservations and response checks."""
    trial_root=Path(__file__).resolve().parents[1]
    input_path=project_path(root,Path(input_path).resolve())
    if not input_path.is_relative_to(trial_root):raise ValueError('AI input outside repository')
    proc=subprocess.run([sys.executable,'-m','benefit_monitor.claude_trial','run','--root',str(trial_root),
                         '--kind',kind,'--input',str(input_path)],cwd=trial_root,capture_output=True,text=True)
    try:
        value=json.loads(proc.stdout)
        if value.get('status')=='credit_exhausted':return {'status':'credit_exhausted','run_id':None}
        if value.get('status') in ('validated_draft','rejected_draft'):
            return {k:value[k] for k in ('status','run_id')}
        if value.get('status')=='stopped' and isinstance(value.get('reason'),str):
            return {'status':'stopped_before_result','run_id':None,'reason':value['reason'][:200]}
    except (ValueError,KeyError,TypeError):
        pass
    return {'status':'stopped_before_result','run_id':None}


TRIAL_RUNS=Path(__file__).resolve().parents[1]/'.tools/claude-trial/live/runs'


def load_run(run_id):
    """Normalized v3 draft and host input that the trial CLI stored for a validated run."""
    if not isinstance(run_id,str) or not run_id or '/' in run_id or run_id.startswith('.'):raise ValueError('invalid run id')
    folder=TRIAL_RUNS/run_id
    if not folder.resolve().is_relative_to(TRIAL_RUNS.resolve()):raise ValueError('run path escapes trial root')
    return (json.loads((folder/'normalized-output.json').read_text()),json.loads((folder/'input.json').read_text()))


def auto_decide(root,run_id,now):
    """Deterministic gate; any unreadable run, bad takedown file or gate error is held as a contract failure."""
    hold={'publish':False,'reasons':['contract'],'record':None}
    try:
        takedowns=load(project_path(root,'cache/ai_publish/takedowns.json'),[])
        if not isinstance(takedowns,list):return hold
        draft,host=load_run(run_id)
        return auto_publish.decide(draft,host,now,[t for t in takedowns if isinstance(t,dict)])
    except Exception:
        # Never crash after a paid request; the private review row still exists.
        return hold


def _load_dict(path,now):
    """(dict, ok). A corrupt file must not crash after a paid call; it is moved aside for review."""
    try:
        value=load(path,{})
        if isinstance(value,dict):return value,True
    except (OSError,ValueError):
        pass
    auto_release.move_aside(path,now)
    return {},False


def _store_decision(root,cid,decision,row,now):
    approved_path=project_path(root,'cache/ai_publish/approved.json')
    decisions_path=project_path(root,'cache/ai_publish/decisions.json')
    approved,approved_ok=_load_dict(approved_path,now);decisions,_=_load_dict(decisions_path,now)
    decisions[cid]=dict(publish=decision['publish'],reasons=decision['reasons'],decided_at=now.isoformat(),
                        run_id=row['run_id'],signature=row['signature'])
    save(decisions_path,decisions)
    if not approved_ok:
        # Never write a list holding only this decision: drop the restore lease so save_ai refuses to
        # upload until the next restore, and keep the decision row only (the item is not published).
        project_path(root,'cache/ai_publish/remote.json').unlink(missing_ok=True)
        return
    # decided_at orders concurrent writers: a newer decision replaces an older withdrawn version.
    if decision['publish']:approved[cid]={**decision['record'],'decided_at':now.isoformat()}
    else:approved.pop(cid,None)
    save(approved_path,approved)


def _withdraw_if_changed(root,cid,body_hash,now):
    """An auto-published page whose original body changed or is gone is withdrawn at once,
    whatever the model then returns (rejected, stopped or credit exhausted). Never on doubt about the file."""
    path=project_path(root,auto_release.APPROVED)
    approved,ok=auto_release._read(path)
    if not ok or not isinstance(approved,dict) or not isinstance(approved.get(cid),dict):return
    review=approved[cid].get('review')
    if not isinstance(review,dict):return
    baseline=review.get('original_body_hash') or next(
        (d.get('body_hash') for d in review.get('documents',[]) if isinstance(d,dict) and d.get('url')==approved[cid].get('url')),None)
    if body_hash is not None and body_hash==baseline:return
    if auto_release.mark_checked(approved,cid,body_hash,now)!='ok':save(path,approved)


def _gone(error):
    from urllib.error import HTTPError
    from .operations import GONE_CODES
    if not isinstance(error,HTTPError):return False
    error.close()
    return error.code in GONE_CODES and not str(error.url or error.filename or '').endswith('/robots.txt')


def _related_docs(reader,cid,candidate,doc,peers,failures):
    domains=allowed_domains(reader.sources)
    docs,seen=[],{doc['body_hash']}
    for url in related_urls(doc,candidate,peers,domains):
        source=next((sid for sid,s in reader.sources.items() if official(url,s['domains'])),None)
        if source is None:continue
        try:other=reader.read({'source':source,'url':url,'title':''},cooldown_on_failure=False)
        except Exception as error:
            failures.append({'candidate_id':cid,'code':'related_fetch_failed','url':url,'error_type':type(error).__name__})
            if isinstance(error,RuntimeError):break
            continue
        if other['body_hash'] in seen:continue
        seen.add(other['body_hash']);docs.append(other)
    return docs


# Daily paid research limit (approved 2026-11-10: 20 -> 40; the monthly USD cap still decides spend).
MAX_RESEARCH=40


def review_candidates(root,candidates,now,max_candidates=2,execute=False):
    root=Path(root).resolve()
    if type(max_candidates) is not int or not 1<=max_candidates<=MAX_RESEARCH:raise ValueError('candidate limit 1..'+str(MAX_RESEARCH))
    project_path(root,'cache/ai_review')
    result=dict(queued=0,rejected=0,awaiting_api=0,skipped_unchanged=0,changed_ids=[],failures=[],rows=[],
                api_spend_requested=execute,cost_scope='cost_policy는 공식 HTTP 수집만 기록. Claude는 별도 누적 원장에 기록.')
    unique={Benefit(**{k:v for k,v in c.items() if k in Benefit.__dataclass_fields__}).id:c for c in candidates}
    with lock(project_path(root,'cache/ai_review/.lock')):
        state=load(project_path(root,'cache/ai_review/state.json'),{'items':{}})
        reader=OfficialReader(root,now)
        prompt=fingerprint(root)
        # Auto-published records withdrawn by the daily body check are researched first.
        try:withdrawn={k for k,r in load(project_path(root,'cache/ai_publish/approved.json'),{}).items()
                       if isinstance(r,dict) and r.get('recheck_priority')}
        except (OSError,ValueError,AttributeError):withdrawn=set()
        ordered=sorted(unique.items(),key=lambda pair:(pair[0] not in withdrawn,state['items'].get(pair[0],{}).get('last_checked_at','')))
        # Only model requests count toward max_candidates; unchanged skips and fetch failures do not
        # (2026-11-10). The run's public HTTP budget still ends the loop.
        attempted=0
        today=now.date().isoformat()
        for cid,candidate in ordered:
            if attempted>=max_candidates or cost_policy.budget.used>=cost_policy.budget.limit:break
            previous_checked=state['items'].get(cid,{}).get('last_checked_at','')
            state['items'].setdefault(cid,{})['last_checked_at']=now.isoformat()
            try:doc=reader.read(candidate)
            except Exception as error:
                result['failures'].append({'candidate_id':cid,'code':'official_fetch_failed','error_type':type(error).__name__})
                if _gone(error):_withdraw_if_changed(root,cid,None,now)
                continue
            _withdraw_if_changed(root,cid,doc['body_hash'],now)
            peers=[c for pid,c in unique.items() if pid!=cid]
            domains=allowed_domains(reader.sources)
            unverified=[u for u in doc.get('links') or [] if not official(u,domains)][:10]
            docs=[doc]+_related_docs(reader,cid,candidate,doc,peers,result['failures'])
            docs=[{**d,'links':[]} for d in docs]
            hashes=','.join(sorted(d['body_hash'] for d in docs))
            signature=hashlib.sha256((cid+'\n'+hashes+'\n'+prompt).encode()).hexdigest()
            previous=state['items'].get(cid,{})
            if previous.get('body_hash') and previous['body_hash']!=doc['body_hash']:result['changed_ids'].append(cid)
            # A rejected answer gets one more try on a later day (same input); then it waits for a body change.
            retry=(previous.get('model_status')=='rejected_draft' and previous.get('attempts',1)<2
                   and previous_checked[:10]<today)
            if previous.get('signature')==signature and previous.get('model_status') in ('validated_draft','rejected_draft','stopped_before_result') and not retry:
                result['skipped_unchanged']+=1
                result['rows'].append({'candidate_id':cid,'status':'unchanged','review_file':previous['review_file']})
                continue
            host=dict(schema_version='research-input-v1',mode='api_agent',synthetic=False,now=now.isoformat(),
                      output_schema_version='research-draft-v1',budget={'http_remaining':max(0,cost_policy.budget.limit-cost_policy.budget.used),'llm_api_remaining':1},
                      candidates=[dict(candidate_id=cid,source_id=candidate['source'],title=candidate['title'],document_ids=[d['id'] for d in docs],
                                       research_reason='공식 원문 여러 곳을 대조해 전체 조건·요약/상세 차이·비용·기간·선정·미확인을 v3로 추출. 사실/공개 승인은 사람 검토.')],documents=docs,unverified_links=unverified)
            input_path=project_path(root,'.tools/ai-inputs/'+signature+'.json')
            if input_path.exists():
                existing=load(input_path,None)
                if (len(existing['candidates'])!=1 or existing['candidates'][0]['candidate_id']!=cid
                        or [(d['id'],d['body_hash'],d['body']) for d in existing['documents']]
                        !=[(d['id'],d['body_hash'],d['body']) for d in docs]):
                    raise ValueError('staged AI input changed; manual review required')
                host=existing
            else:
                save(input_path,host)
            attempted+=1
            model=invoke(root,'research',input_path) if execute else {'status':'awaiting_api_authorization','run_id':None}
            if model['status']=='credit_exhausted':
                # Stop the day's remaining paid research; keep results already received and retry this one later.
                result['credit_exhausted']=True
                state['items'][cid].pop('last_checked_at',None)
                break
            review_file='cache/ai_review/queue/'+signature+'.json'
            row=dict(candidate_id=cid,source=candidate['source'],url=candidate['url'],body_hash=doc['body_hash'],signature=signature,
                     input_file=str(input_path.relative_to(root)),model_status=model['status'],run_id=model['run_id'],
                     review_status='pending_human_review',publication_approved=False,observed_at=now.isoformat())
            if model['status']=='validated_draft':
                decision=auto_decide(root,model['run_id'],now)
                row['auto_publish']={'publish':decision['publish'],'reasons':decision['reasons']}
                _store_decision(root,cid,decision,row,now)
                result['auto_published']=result.get('auto_published',0)+decision['publish']
            save(project_path(root,review_file),row)
            attempts=previous.get('attempts',1)+1 if previous.get('signature')==signature else 1
            state['items'][cid]={**row,'review_file':review_file,'last_checked_at':now.isoformat(),'attempts':attempts}
            result['queued']+=1
            result['rejected']+=model['status']=='rejected_draft'
            result['awaiting_api']+=model['status']=='awaiting_api_authorization'
            result['rows'].append({'candidate_id':cid,'status':model['status'],'review_file':review_file})
        save(project_path(root,'cache/ai_review/state.json'),state)
    return result
