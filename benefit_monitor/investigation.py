"""Bounded, opt-in follow-up research using the existing paid research runner."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import cost_policy, wire_format
from .ai_contract import check_schema
from .claude_trial import evaluate_draft, validate_host
from .official_reader import project_path
from .store import load, save
from . import investigation_contract as contract

ROOT=Path(__file__).resolve().parents[1]
def search_lead(root,host,sources,documents,missing,now,state):
    """Stage 1 follow-up search (2026-11-20): one paid request, provider URLs only. The first URL on a registered
    source that allows AI review and is not read yet becomes the next link; other hosts are source candidates."""
    from .ai_review import invoke_search
    from . import web_search
    from .cross_sources import fetchable
    from .validation import official
    report={'status':'skipped','searches':0,'urls':0}
    # `state` is shared by one review run: after a refused search (web search disabled, daily search cap,
    # credit) the rest of that run does not try again.
    if state.get('off'):return {'report':report,'link':None,'others':[]}
    candidate=host['candidates'][0]
    title=str(candidate.get('title') or '').strip()
    if not title:
        report['status']='no_title';return {'report':report,'link':None,'others':[]}
    organizer=(sources.get(candidate['source_id']) or {}).get('name','')
    query=web_search.build(candidate['candidate_id'],title[:200],str(organizer)[:80],missing,now)
    key=hashlib.sha256(json.dumps(query,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    path=project_path(root,'.tools/ai-inputs/search-'+key+'.json')
    save(path,query)
    found=invoke_search(root,path)
    report.update(status=found['status'],searches=found['searches'],urls=len(found['urls']),run_id=found.get('run_id'))
    if found['status']!='search_done':
        state['off']=True
        return {'report':report,'link':None,'others':[]}
    known={d['requested_url'] for d in documents}|{d['final_url'] for d in documents}
    domains={d for s in sources.values() for d in s['domains']}
    link=None;others=[]
    for url in found['urls']:
        sid=next((sid for sid,s in sources.items() if s.get('ai_review') is not False and official(url,s['domains'])),None)
        if sid is not None:
            if link is None and url not in known and fetchable(url):
                link={'id':'s'+hashlib.sha256(url.encode()).hexdigest()[:16],'source_id':sid,'url':url}
        elif urlsplit(url).hostname not in domains:
            others.append(url)
    report['allowed_link']=link is not None
    return {'report':report,'link':link,'others':others}


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


def run(root,host,reader,now,*,execute,max_requests,search_state=None):
    """search_state: a dict shared across one review run turns on the stage 1 follow-up search; None keeps it off."""
    # The caller owns the daily lock and passes its remaining research allowance.
    from .ai_review import invoke
    if type(max_requests) is not int or max_requests<1:raise ValueError('research allowance required')
    limit=min(max_requests,contract.MAX_CALLS)
    host=deepcopy(host);documents=host['documents'];steps=[];calls=0;model={'status':'awaiting_api_authorization','run_id':None}
    initial_http=cost_policy.budget.used
    terminal='awaiting_api_authorization';input_path=None;missing=list(contract.TARGETS)
    searched=False;search_others=[]
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
        # Links first; only when the model finds no usable official link does one web search look for one.
        if (search_state is not None and action=='no_relevant_links' and missing and not searched and index+1<limit
                and len(documents)<contract.MAX_DOCUMENTS and http_remaining>0):
            searched=True
            lead=search_lead(root,host,reader.sources,documents,missing,now,search_state)
            step['search']=lead['report'];search_others+=lead['others']
            if lead['link'] is not None:action,link='read',lead['link'];step['status']='read_search'
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
            'source_candidates':list(dict.fromkeys(contract.source_candidates(documents,reader.sources)+search_others))[:20],
            'web_searches':sum(s.get('search',{}).get('searches',0) for s in steps),
            'followup_supported_fields':sorted({field for step in steps[1:] for field in step.get('new_supported_fields',[]) if field not in missing}),
            'publication_approved':False}
    # The host stored with the last model output must not contain an unread/unprocessed extra page.
    result_path=project_path(root,'cache/ai_review/investigations/'+key+'.json')
    save(result_path,result)
    return {'model':model,'host':host,'input_path':input_path,'report':result,
            'report_file':str(result_path.relative_to(root))}
