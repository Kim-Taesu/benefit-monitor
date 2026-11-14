"""Bounded, opt-in follow-up research using the existing paid research runner."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import cost_policy, wire_format
from .ai_contract import check_schema
from .claude_trial import evaluate_draft, validate_host
from .official_reader import project_path
from .store import load, save
from . import investigation_contract as contract

ROOT=Path(__file__).resolve().parents[1]


def fingerprint():
    names=('benefit_monitor/investigation_contract.py','docs/ai/prompts/investigation-system.md')
    return hashlib.sha256(b'\n'.join((ROOT/name).read_bytes() for name in names)).hexdigest()


def read_result(run_id,expected_host):
    if not isinstance(run_id,str) or not re.fullmatch('[0-9a-f]{64}',run_id):raise ValueError('invalid investigation run')
    folder=project_path(ROOT,'.tools/claude-trial/live/runs/'+run_id)
    stored=load(folder/'input.json',None)
    if stored!=expected_host:raise ValueError('investigation input mismatch')
    path=project_path(ROOT,folder/'model-output.json')
    if path.stat().st_size>2*1024*1024:raise ValueError('oversized investigation output')
    return load(path,None)


def run(root,host,reader,now,*,execute,max_requests):
    # The caller owns the daily lock and passes its remaining research allowance.
    from .ai_review import invoke
    if type(max_requests) is not int or max_requests<1:raise ValueError('research allowance required')
    limit=min(max_requests,contract.MAX_CALLS)
    host=deepcopy(host);documents=host['documents'];steps=[];calls=0;model={'status':'awaiting_api_authorization','run_id':None}
    initial_http=cost_policy.budget.used
    terminal='awaiting_api_authorization';input_path=None;missing=list(contract.TARGETS)
    for index in range(limit):
        http_remaining=max(0,min(cost_policy.budget.limit-cost_policy.budget.used,
                               reader.request_budget.limit-reader.request_budget.used))
        host['investigation']=contract.context(documents,reader.sources,limit-index,http_remaining)
        host['budget']={'http_remaining':http_remaining,'llm_api_remaining':limit-index}
        host['candidates'][0]['document_ids']=[d['id'] for d in documents]
        validate_host(host,'research',root)
        key=hashlib.sha256(json.dumps(host,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        input_path=project_path(root,'.tools/ai-inputs/investigation-'+key+'.json')
        if input_path.exists() and load(input_path,None)!=host:raise ValueError('staged investigation changed')
        save(input_path,host)
        if not execute:break
        calls+=1
        try:model=invoke(root,'research',input_path)
        except (OSError,ValueError):model={'status':'stopped_before_result','run_id':None}
        step={'round':index+1,'run_id':model.get('run_id'),'input_sha256':key,'document_hashes':[d['body_hash'] for d in documents]}
        steps.append(step)
        if model['status']!='validated_draft':
            terminal='budget_exhausted' if model['status']=='credit_exhausted' else 'model_failed'
            step['status']=terminal;break
        try:
            wire=read_result(model['run_id'],host)
            if check_schema(wire,contract.schema(wire_format.research_wire_schema())):raise ValueError('wire contract')
            draft=wire_format.research_from_wire(wire,host)
            _,report=evaluate_draft(draft,host,'research',required_version='research-extraction-v3')
            if not report['valid']:raise ValueError('local validation failed')
            previous_missing=set(missing)
            missing=contract.missing(draft)
            step['new_supported_fields']=sorted(previous_missing-set(missing))
            action,link=contract.decision(wire,host,draft)
        except (ValueError,TypeError,KeyError,OSError,IndexError):
            terminal='invalid_model_output';step['status']=terminal;break
        step.update(status=action,missing_fields=missing)
        if action!='read':terminal=action;break
        if index+1>=limit or len(documents)>=contract.MAX_DOCUMENTS or http_remaining<=0:
            terminal='budget_exhausted';break
        step['requested_link_id']=link['id']
        try:
            other=reader.read({'source':link['source_id'],'url':link['url'],'title':''})
        except RuntimeError:
            terminal='budget_exhausted';break
        except Exception as error:
            terminal='unsupported_document' if str(error)=='unsupported body content type' else 'access_blocked'
            break
        if isinstance(other,dict) and other.get('body_hash') in {d['body_hash'] for d in documents}:
            terminal='no_new_evidence';break
        try:
            prospective=deepcopy(host);prospective['documents']=[*documents,other]
            prospective['candidates'][0]['document_ids']=[d['id'] for d in prospective['documents']]
            prospective['investigation']=contract.context(prospective['documents'],reader.sources,limit-index-1,http_remaining)
            validate_host(prospective,'research',root)
        except (ValueError,KeyError,TypeError,AttributeError):
            terminal='invalid_document';break
        documents.append(other)
    result={'version':1,'candidate_id':host['candidates'][0]['candidate_id'],'status':terminal,'missing_fields':missing,
            'model_calls':calls,'additional_http_requests':cost_policy.budget.used-initial_http,'http_budget_used':reader.request_budget.used,'steps':steps,
            'source_candidates':contract.source_candidates(documents,reader.sources),
            'followup_supported_fields':sorted({field for step in steps[1:] for field in step.get('new_supported_fields',[]) if field not in missing}),
            'publication_approved':False}
    # The host stored with the last model output must not contain an unread/unprocessed extra page.
    result_path=project_path(root,'cache/ai_review/investigations/'+key+'.json')
    save(result_path,result)
    return {'model':model,'host':host,'input_path':input_path,'report':result,
            'report_file':str(result_path.relative_to(root))}
