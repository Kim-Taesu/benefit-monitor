"""Trusted Actions orchestration with durable admission before paid work."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.request import Request
from urllib.error import HTTPError,URLError

from .age_state import AgeState
from .ai_daily import daily
from .briefing import SEOUL
from .claude_trial import configured_key
from .cloud_state import CloudSession,GitHubStateStore,REPOSITORY,BUDGET,snapshot_digest
from .mirror import run as mirror
from .public_snapshot import validate
from .store import load,save
from .trial_budget import TrialBudget
from scripts.install_age import safe_path


def trusted_environment():
    if (os.environ.get('BENEFIT_AI_CLOUD')!='1' or os.environ.get('GITHUB_ACTIONS')!='true'
            or os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY
            or os.environ.get('GITHUB_EVENT_NAME') not in ('schedule','workflow_dispatch')):
        raise ValueError('trusted Actions environment required')


def actions_request(store,path,method='POST',body=None):
    # Callers supply only fixed workflow endpoints; never follow redirects.
    if path not in ('actions/workflows/ai-daily.yml/disable','actions/workflows/briefing-pages.yml/dispatches'):
        raise ValueError('unapproved workflow action')
    raw=json.dumps(body).encode() if body is not None else None
    request=Request('https://api.github.com/repos/'+REPOSITORY+'/'+path,data=raw,method=method,
                    headers={'Authorization':'Bearer '+store.token,'Accept':'application/vnd.github+json',
                             'Content-Type':'application/json','User-Agent':'BenefitMonitor-AI-Cloud/1.0'})
    try:
        with store.opener(request) as response:response.read(1024)
    except HTTPError as error:
        code=error.code;error.close();raise ValueError('workflow action failed: http_'+str(code)) from None
    except (OSError,URLError):raise ValueError('workflow action unavailable') from None


def disable_workflow(store):
    try:actions_request(store,'actions/workflows/ai-daily.yml/disable',method='PUT')
    except ValueError:return False  # Admission gates remain authoritative.
    return True


def preceding_refresh(store,now):
    data=store._api('actions/workflows/briefing-pages.yml/runs?event=schedule&branch=main&per_page=20')
    rows=[row for row in data['workflow_runs']
          if datetime.fromisoformat(row['created_at']).astimezone(SEOUL).date()==now.date()]
    return bool(rows) and all(row['status']=='completed' for row in rows)


def publish_snapshot(root,store,now,key):
    code=os.environ.get('GITHUB_SHA','')
    if os.environ.get('GITHUB_REF')!='refs/heads/main' or not re.fullmatch('[0-9a-f]{40}',code):
        raise ValueError('main code revision required for public delivery')
    meta=store._api('')
    if meta.get('private') is not False or meta.get('full_name')!=REPOSITORY:raise ValueError('personal public repository required')
    data=load(safe_path(root,'delivery/public/briefing.json'),{})
    content=(json.dumps(validate(root,data,now),ensure_ascii=False,indent=2)+'\n').encode()
    if key.encode() in content or b'AGE-SECRET-KEY-' in content:raise ValueError('credential in public payload')
    env={k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env.update(GH_TOKEN=store.token,GH_HOST='github.com',GH_NO_UPDATE_NOTIFIER='1')
    commit=mirror(root,REPOSITORY,env=env,content=content)
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('immutable snapshot commit required')
    actions_request(store,'actions/workflows/briefing-pages.yml/dispatches',body={'ref':'main','inputs':{
        'deploy_approved_snapshot':'true','snapshot_commit':commit,'expected_code_sha':code}})
    return {'status':'dispatched_not_yet_verified','snapshot_commit':commit,'code_sha':code,'ref':'main'}


def cloud_run(root,now=None,check_only=True,store=None):
    trusted_environment()
    root=Path(root).resolve();now=now or datetime.now(SEOUL)
    if now.tzinfo is None:raise ValueError('timezone required')
    now=now.astimezone(SEOUL)
    if not check_only and os.environ.get('GITHUB_REF')!='refs/heads/main':raise ValueError('paid cloud execution requires main')
    key=configured_key(root)
    store=store or GitHubStateStore(root,os.environ.get('GH_TOKEN',''),AgeState(root,safe_path(root,'.tools/cloud-state/identity.txt')))
    session=CloudSession.restore(root,store)
    if hashlib.sha256(key.encode()).hexdigest()!=session.control['api_key_sha256']:
        raise ValueError('API Secret differs from approved local key')
    budget=TrialBudget(safe_path(root,BUDGET)).summary()
    day=now.date().isoformat()
    summary={'requests':len(budget['requests']),'exposure_microdollars':budget['exposure_microdollars'],
             'day_status':session.control['days'].get(day,{}).get('status'),'active':session.control['active']}
    if check_only:
        data=dict(session.control)
        data['check']={'snapshot_sha256':snapshot_digest(data),'ref':os.environ.get('GITHUB_REF',''),
                       'code_sha':os.environ.get('GITHUB_SHA',''),'run_id':os.environ.get('GITHUB_RUN_ID','')}
        session._commit(data)  # Confirms contents:write without day or provider admission.
        return dict(summary,status='check_passed')
    if not session.control['active']:return {'status':'handoff_required'}
    stop=('trial_expired' if now>=datetime.fromisoformat(session.control['expires_at']) else
          'trial_run_limit' if len(session.control['days'])>=4 else
          'trial_budget_limit' if len(budget['requests'])>=40 or budget['exposure_microdollars']>=5_000_000 else None)
    if stop:
        disable_workflow(store);return {'status':stop}
    if now.hour<6:return {'status':'not_due'}
    if day in session.control['days']:
        return {'status':'already_completed_today' if session.control['days'][day]['status']=='completed' else 'previous_attempt_requires_review'}
    if not preceding_refresh(store,now):return {'status':'waiting_for_existing_refresh'}
    session.mark_day(day)
    save(safe_path(root,'ai-automation.json'),{'enabled':True,'recurring_spend_approved':True,
         'public_application_approved':True,'remote_delivery_approved':False,'max_ai_candidates_per_day':2,
         'trial_expires_at':session.control['expires_at']})
    try:
        result=daily(root,now=now,online=True,allow_spend=True,publish=True)
        if result['status']!='completed':raise ValueError('inner daily did not complete')
        session.save_runtime()
        delivery=publish_snapshot(root,store,now,key)
        session.finish(day,'completed')
        return {'status':'completed','delivery':delivery}
    except Exception:
        # Preserve results if possible; unresolved remote reservations still block restarts.
        try:session.save_runtime();session.finish(day,'failed')
        except Exception:pass
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:result=cloud_run(Path(__file__).resolve().parents[1],check_only=not args.execute)
    except Exception:
        print('cloud_stopped_requires_review');return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
