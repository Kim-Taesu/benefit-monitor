"""Optional collection → change detection → model → private human-review queue."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from . import cost_policy
from .models import Benefit
from .official_reader import OfficialReader, project_path
from .store import load,save,lock


def fingerprint(_runtime_root):
    root=Path(__file__).resolve().parents[1]
    names=('README.md','research.md','research-extraction.md','schemas/research-extraction-v3.schema.json')
    return hashlib.sha256(b'\n'.join((Path(root)/'docs/ai'/p).read_bytes() for p in names)).hexdigest()


def invoke(root,kind,input_path):
    """Only the existing CLI owns API credentials, reservations and response checks."""
    trial_root=Path(__file__).resolve().parents[1]
    input_path=project_path(root,Path(input_path).resolve())
    if not input_path.is_relative_to(trial_root):raise ValueError('AI input outside repository')
    proc=subprocess.run([sys.executable,'-m','benefit_monitor.claude_trial','run','--root',str(trial_root),
                         '--kind',kind,'--input',str(input_path)],cwd=trial_root,capture_output=True,text=True)
    try:
        value=json.loads(proc.stdout)
        if value.get('status') in ('validated_draft','rejected_draft'):
            return {k:value[k] for k in ('status','run_id')}
    except (ValueError,KeyError,TypeError):
        pass
    return {'status':'stopped_before_result','run_id':None}


def review_candidates(root,candidates,now,max_candidates=2,execute=False):
    root=Path(root).resolve()
    if type(max_candidates) is not int or not 1<=max_candidates<=10:raise ValueError('candidate limit 1..10')
    project_path(root,'cache/ai_review')
    result=dict(queued=0,rejected=0,awaiting_api=0,skipped_unchanged=0,changed_ids=[],failures=[],rows=[],
                api_spend_requested=execute,cost_scope='cost_policy는 공식 HTTP 수집만 기록. Claude는 별도 누적 원장에 기록.')
    unique={Benefit(**{k:v for k,v in c.items() if k in Benefit.__dataclass_fields__}).id:c for c in candidates}
    with lock(project_path(root,'cache/ai_review/.lock')):
        state=load(project_path(root,'cache/ai_review/state.json'),{'items':{}})
        reader=OfficialReader(root,now)
        prompt=fingerprint(root)
        ordered=sorted(unique.items(),key=lambda pair:state['items'].get(pair[0],{}).get('last_checked_at',''))
        for cid,candidate in ordered[:max_candidates]:
            state['items'].setdefault(cid,{})['last_checked_at']=now.isoformat()
            try:doc=reader.read(candidate)
            except Exception as error:
                result['failures'].append({'candidate_id':cid,'code':'official_fetch_failed','error_type':type(error).__name__})
                continue
            signature=hashlib.sha256((cid+'\n'+doc['body_hash']+'\n'+prompt).encode()).hexdigest()
            previous=state['items'].get(cid,{})
            if previous.get('body_hash') and previous['body_hash']!=doc['body_hash']:result['changed_ids'].append(cid)
            if previous.get('signature')==signature and previous.get('model_status') in ('validated_draft','rejected_draft','stopped_before_result'):
                result['skipped_unchanged']+=1
                result['rows'].append({'candidate_id':cid,'status':'unchanged','review_file':previous['review_file']})
                continue
            host=dict(schema_version='research-input-v1',mode='api_agent',synthetic=False,now=now.isoformat(),
                      output_schema_version='research-draft-v1',budget={'http_remaining':max(0,cost_policy.budget.limit-cost_policy.budget.used),'llm_api_remaining':1},
                      candidates=[dict(candidate_id=cid,source_id=candidate['source'],title=candidate['title'],document_ids=[doc['id']],
                                       research_reason='공식 원문 전체 조건·요약/상세 차이·비용·기간·선정·미확인을 v3로 추출. 사실/공개 승인은 사람 검토.')],documents=[doc])
            input_path=project_path(root,'.tools/ai-inputs/'+signature+'.json')
            if input_path.exists():
                existing=load(input_path,None)
                if (len(existing['candidates'])!=1 or existing['candidates'][0]['candidate_id']!=cid
                        or len(existing['documents'])!=1 or existing['documents'][0]['body_hash']!=doc['body_hash']
                        or existing['documents'][0]['body']!=doc['body']):
                    raise ValueError('staged AI input changed; manual review required')
                host=existing
            else:
                save(input_path,host)
            model=invoke(root,'research',input_path) if execute else {'status':'awaiting_api_authorization','run_id':None}
            review_file='cache/ai_review/queue/'+signature+'.json'
            row=dict(candidate_id=cid,source=candidate['source'],url=candidate['url'],body_hash=doc['body_hash'],signature=signature,
                     input_file=str(input_path.relative_to(root)),model_status=model['status'],run_id=model['run_id'],
                     review_status='pending_human_review',publication_approved=False,observed_at=now.isoformat())
            save(project_path(root,review_file),row)
            state['items'][cid]={**row,'review_file':review_file,'last_checked_at':now.isoformat()}
            result['queued']+=1
            result['rejected']+=model['status']=='rejected_draft'
            result['awaiting_api']+=model['status']=='awaiting_api_authorization'
            result['rows'].append({'candidate_id':cid,'status':model['status'],'review_file':review_file})
        save(project_path(root,'cache/ai_review/state.json'),state)
    return result
