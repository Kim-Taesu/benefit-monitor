"""Opt-in research follow-up requests. URLs and execution authority stay with the host."""
from copy import deepcopy
import hashlib
from urllib.parse import urlsplit

from .cross_sources import fetchable
from .validation import official
from .ai_contract import check_schema

OBJECTIVE='공식 나들이·문화 안내의 이용 기간, 대상, 비용과 신청 방법을 확인한다. 개인 자격·잔여석은 판단하지 않는다.'
TARGETS=('event_period','eligibility','fee_status','cost_details','application_method')
MAX_DOCUMENTS=4
MAX_CALLS=3
MAX_HTTP=12
STOPS=('sufficient_evidence','no_relevant_links','unsupported_document','access_blocked','unresolved_conflict','budget_exhausted')


def choices(documents,sources):
    known={d['requested_url'] for d in documents}|{d['final_url'] for d in documents}
    links=[];seen=set()
    for doc in documents:
        for url in (doc.get('links') or [])[:50]:
            if not isinstance(url,str) or len(url)>2048 or url in known or url in seen:continue
            seen.add(url)
            sid=next((sid for sid,s in sources.items() if s.get('ai_review') is not False and official(url,s['domains'])),None)
            if sid is None or not fetchable(url):continue
            links.append({'id':'l'+hashlib.sha256((doc['id']+'\n'+url).encode()).hexdigest()[:16],
                          'document_id':doc['id'],'source_id':sid,'url':url})
            if len(links)==12:return links
    return links


def context(documents,sources,remaining_calls,http_remaining):
    return {'version':1,'objective':OBJECTIVE,'target_fields':list(TARGETS),
            'remaining_calls':remaining_calls,'http_remaining':http_remaining,
            'remaining_documents':MAX_DOCUMENTS-len(documents),'links':choices(documents,sources)}


def validate_context(host,sources):
    value=host.get('investigation')
    if not isinstance(value,dict) or set(value)!={'version','objective','target_fields','remaining_calls','http_remaining','remaining_documents','links'}:
        raise ValueError('invalid investigation context')
    if len(host['candidates'])!=1 or not 1<=len(host['documents'])<=MAX_DOCUMENTS:raise ValueError('investigation scope')
    for key,maximum in (('remaining_calls',MAX_CALLS),('http_remaining',100),('remaining_documents',MAX_DOCUMENTS-1)):
        if type(value[key]) is not int or not 0<=value[key]<=maximum:raise ValueError('invalid investigation budget')
    if sources[host['candidates'][0]['source_id']].get('ai_review') is False:raise ValueError('source disallows AI review')
    expected=context(host['documents'],sources,value['remaining_calls'],value['http_remaining'])
    if value!=expected:raise ValueError('investigation context differs from official links')


def schema(base):
    result=deepcopy(base)
    result['properties']['next_step']={'type':'object','additionalProperties':False,
        'properties':{'action':{'enum':['read','stop']},'link_id':{'type':'string'},
                      'missing_fields':{'type':'array','items':{'enum':list(TARGETS)}},'reason':{'enum':[*STOPS,'missing_conditions']}},
        'required':['action','link_id','missing_fields','reason']}
    result['required'].append('next_step')
    return result


def missing(draft):
    facts={f['field']:f for f in draft['records'][0]['facts']}
    return [field for field in TARGETS if facts.get(field,{}).get('status')!='supported']


def decision(wire,host,draft):
    value=wire.get('next_step');shape=schema({'properties':{},'required':[]})['properties']['next_step']
    if check_schema(value,shape):raise ValueError('invalid follow-up action')
    fields=value['missing_fields']
    if len(fields)!=len(set(fields)) or not set(fields)<=set(missing(draft)):raise ValueError('follow-up field already known')
    if any(f['status']=='disputed' for f in draft['records'][0]['facts']):return 'unresolved_conflict',None
    if value['action']=='stop':
        if value['link_id'] or value['reason'] not in STOPS:raise ValueError('invalid stop')
        if value['reason']!='sufficient_evidence':return value['reason'],None
        return ('insufficient_evidence' if missing(draft) else 'sufficient_evidence'),None
    if not fields or value['reason']!='missing_conditions':raise ValueError('read requires missing fields')
    link=next((link for link in host['investigation']['links'] if link['id']==value['link_id']),None)
    if link is None:raise ValueError('unknown follow-up link')
    return 'read',link


def source_candidates(documents,sources):
    domains={d for s in sources.values() for d in s['domains']};result=[]
    for doc in documents:
        for url in (doc.get('links') or [])[:50]:
            if not isinstance(url,str) or len(url)>2048:continue
            try:
                parsed=urlsplit(url)
                if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.port and parsed.hostname not in domains and url not in result:result.append(url)
            except ValueError:continue
    return result[:20]
