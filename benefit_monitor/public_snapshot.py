"""Validate an immutable public snapshot against this checkout's approvals."""
import argparse
import base64
from datetime import datetime,timedelta,time
import hashlib
import json
from pathlib import Path
import re
import subprocess

from . import operations
from .briefing import SEOUL,aware_time,identity
from .publish import PUBLIC_FIELDS,payload,releases,write_export,STATUS
from .store import load

LIMIT=2*1024*1024
REPOSITORY='Kim-Taesu/benefit-monitor'


def _state(root,data,config,now):
    ids={s['id'] for s in config['sources']}
    remote=operations.sanitize(data.get('operational_state',{}),ids,now)
    local=operations.sanitize(load(Path(root)/'cache/operational_state.json',{}),ids,now)
    for cid,row in local['items'].items():
        if row.get('hold_at'):
            old=remote['items'].get(cid,{})
            if not old.get('hold_at') or aware_time(row['hold_at'])>aware_time(old['hold_at']):
                remote['items'][cid]=row
    return remote


def _coverage(root,data,config):
    raw=data.get('coverage',{})
    ids={s['id'] for s in config['sources']}
    success=[]
    for row in raw.get('sources',[]):
        if row.get('source') not in ids or row.get('status') not in STATUS:raise ValueError('unknown snapshot source status')
        if row['status']=='checked':success.append(row['source'])
    names={d['name'] for d in load(Path(root)/'districts.json',{'districts':[]})['districts']}
    districts=[]
    for row in raw.get('districts',[]):
        if row.get('name') not in names or row.get('status') not in STATUS:raise ValueError('unknown snapshot district status')
        status=row['status']
        districts.append({'district':row['name'],'status':'checked' if status=='cached' else status,
                          'mode':'cached' if status=='cached' else 'live','checked_at':None,
                          'candidates_count':0})
    return {'online':True,'successful_sources':success,
            'successful_districts':sum(d['status']=='checked' and d['mode']=='live' for d in districts)},districts


def validate(root,data,now):
    root=Path(root)
    if now.tzinfo is None:raise ValueError('timezone required')
    now=now.astimezone(SEOUL)
    if not isinstance(data,dict) or data.get('schema_version')!=1 or not isinstance(data.get('items'),list):
        raise ValueError('invalid public snapshot shape')
    generated=aware_time(data['generated_at'])
    if generated.astimezone(SEOUL).date()!=now.date() or not 0<=(now-generated).total_seconds()<=7200:
        raise ValueError('snapshot is stale or future dated')
    config=load(root/'sources.yaml',None)
    state=_state(root,data,config,now)
    status=data.get('status')
    if status=='collection_failed':
        if data['items']:raise ValueError('failure snapshot cannot include recommendations')
        clean=payload(root,now,failure=True,state=state)
    elif status in ('partial','awaiting_verification'):
        through=aware_time(data['valid_through'])
        midnight=datetime.combine(now.date()+timedelta(days=1),time.min,SEOUL)
        if not now<through<=midnight:raise ValueError('invalid snapshot display cutoff')
        approved=releases(root,config,now)
        trusted=[];seen=set()
        fields=set(PUBLIC_FIELDS)|{'display_until'}
        for row in data['items']:
            if not isinstance(row,dict) or set(row)-fields:raise ValueError('unexpected public item field')
            key=identity(row)
            if key in seen:raise ValueError('duplicate snapshot item')
            seen.add(key)
            fact=approved.get(key)
            if fact is None or any(row.get(k)!=fact[k] for k in PUBLIC_FIELDS if k!='benefit_value' or fact[k]):
                raise ValueError('snapshot fact differs from approved public release')
            if not fact.get('benefit_value') and row.get('benefit_value'):raise ValueError('unapproved benefit value')
            trusted.append(fact)
        collection,districts=_coverage(root,data,config)
        if not collection['successful_sources'] and not collection['successful_districts']:
            raise ValueError('snapshot has no successful source observation')
        report={'verified_at':data['source_report_at'],'new':trusted,'needs_recheck':[],
                'collection':collection,'district_coverage':districts,'complete':False}
        clean=payload(root,now,report=report,state=state)
        clean['valid_through']=min(aware_time(clean['valid_through']),through).isoformat()
        active={identity(row):row for row in clean['items']}
        if any(identity(row) in active and row.get('display_until')!=active[identity(row)]['display_until'] for row in data['items']):
            raise ValueError('snapshot extends or changes an item cutoff')
    else:
        raise ValueError('unknown snapshot status')
    clean['generated_at']=data['generated_at']
    clean['run_context']={'trigger':'workflow_dispatch','status':'approved_snapshot','scheduled_run_confirmed':False}
    clean['run_id']='approved-snapshot-'+hashlib.sha256(json.dumps(clean['items'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    if data.get('topic_cards'):
        from .topic_publication import from_bundle
        bundle=from_bundle(root,data['topic_cards'],clean,now)
        if bundle is not None:clean['topic_cards']=bundle
    return clean


def stage(root,data,now):
    clean=validate(root,data,now)
    write_export(root,clean)
    return clean


def import_remote(root,repository,commit,now=None):
    if repository.casefold()!=REPOSITORY.casefold() or not re.fullmatch('[0-9a-f]{40}',commit):
        raise ValueError('personal repository and immutable commit required')
    result=subprocess.run(['gh','api','--hostname','github.com',f'repos/{REPOSITORY}/contents/briefing.json?ref={commit}'],
                          check=True,capture_output=True,text=True)
    if len(result.stdout)>3*LIMIT:raise ValueError('snapshot envelope too large')
    envelope=json.loads(result.stdout)
    if envelope.get('encoding')!='base64':raise ValueError('invalid snapshot encoding')
    raw=base64.b64decode(envelope['content'],validate=False)
    if len(raw)>LIMIT:raise ValueError('snapshot exceeds 2 MiB')
    return stage(root,json.loads(raw),now or datetime.now(SEOUL))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--repository',required=True)
    parser.add_argument('--commit',required=True)
    parser.add_argument('--expected-code-sha',required=True)
    args=parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}',args.expected_code_sha):parser.error('invalid expected code SHA')
    actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=args.root,text=True).strip()
    if actual!=args.expected_code_sha:parser.error('checkout differs from requested code revision')
    result=import_remote(args.root,args.repository,args.commit)
    print('Approved snapshot:',result['status'],'items',len(result['items']))


if __name__=='__main__':main()
