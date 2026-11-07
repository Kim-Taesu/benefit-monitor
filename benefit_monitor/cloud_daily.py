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
from .claude_trial import ClaudeClient,configured_key
from .cloud_state import CloudSession,GitHubStateStore,REPOSITORY,BUDGET,snapshot_digest
from .mirror import run as mirror,restore as restore_mirror
from .public_snapshot import validate
from .wire_format import research_wire_schema
from .store import load,save
from .trial_budget import TrialBudget
from scripts.install_age import safe_path


def trusted_environment():
    if (os.environ.get('BENEFIT_AI_CLOUD')!='1' or os.environ.get('GITHUB_ACTIONS')!='true'
            or os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY
            or os.environ.get('GITHUB_EVENT_NAME') not in ('schedule','workflow_dispatch','workflow_run')):
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


# GitHub delayed the 01:00 KST briefing schedule 5.8-10.7h and dropped it on 2026-11-04.
FALLBACK_REFRESH_HOUR=10
ATTENTION={'completed_with_provider_failure','probe_rejected','credit_exhausted'}
# Per-day paid request limits: research 20, topic 1, grammar probe 2.
MAX_DAILY_RESEARCH=20
STATUS_FILE='cache/ai_daily/status.json'


def write_ai_status(root,state,day,now):
    """Public run status; last_success_day carries over until the next ok run."""
    path=safe_path(root,STATUS_FILE)
    previous=load(path,{})
    last=day if state=='ok' else previous.get('last_success_day')
    save(path,{'state':state,'last_success_day':last,'updated_at':now.isoformat()})


def todays_refresh(store,now):
    """Collecting briefing runs created today (schedule or manual dispatch; push runs only deploy)."""
    rows=[]
    for event in ('schedule','workflow_dispatch'):
        data=store._api('actions/workflows/briefing-pages.yml/runs?event='+event+'&branch=main&per_page=20')
        rows+=[row for row in data['workflow_runs']
               if datetime.fromisoformat(row['created_at']).astimezone(SEOUL).date()==now.date()]
    if not rows:return 'missing'
    if any(row['status']!='completed' for row in rows):return 'running'
    return 'ready' if any(row.get('conclusion')=='success' for row in rows) else 'failed'


def dispatch_refresh(store):
    actions_request(store,'actions/workflows/briefing-pages.yml/dispatches',body={'ref':'main'})


def runner_environment(store):
    env={k:os.environ[k] for k in ('PATH','HOME','LANG','LC_ALL','TMPDIR') if k in os.environ}
    env.update(GH_TOKEN=store.token,GH_HOST='github.com',GH_NO_UPDATE_NOTIFIER='1')
    return env


def restore_public(root,store,now):
    # The preceding free run may have observed newer holds than the AI archive.
    sha=restore_mirror(root,REPOSITORY,now=now,env=runner_environment(store))
    if not isinstance(sha,str) or not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('initial public file lease required')
    return sha


def publish_snapshot(root,store,now,key,*,expected_sha):
    if not isinstance(expected_sha,str) or not re.fullmatch('[0-9a-f]{40}',expected_sha):raise ValueError('initial public file lease required')
    code=os.environ.get('GITHUB_SHA','')
    if os.environ.get('GITHUB_REF')!='refs/heads/main' or not re.fullmatch('[0-9a-f]{40}',code):
        raise ValueError('main code revision required for public delivery')
    meta=store._api('')
    if meta.get('private') is not False or meta.get('full_name')!=REPOSITORY:raise ValueError('personal public repository required')
    data=load(safe_path(root,'delivery/public/briefing.json'),{})
    content=(json.dumps(validate(root,data,now),ensure_ascii=False,indent=2)+'\n').encode()
    if key.encode() in content or b'AGE-SECRET-KEY-' in content:raise ValueError('credential in public payload')
    commit=mirror(root,REPOSITORY,env=runner_environment(store),content=content,expected_sha=expected_sha)
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('immutable snapshot commit required')
    actions_request(store,'actions/workflows/briefing-pages.yml/dispatches',body={'ref':'main','inputs':{
        'deploy_approved_snapshot':'true','snapshot_commit':commit,'expected_code_sha':code}})
    return {'status':'dispatched_not_yet_verified','snapshot_commit':commit,'code_sha':code,'ref':'main'}


def cloud_run(root,now=None,check_only=True,store=None,resume=False,retry=False,probe_only=False):
    trusted_environment()
    root=Path(root).resolve();now=now or datetime.now(SEOUL)
    if now.tzinfo is None:raise ValueError('timezone required')
    now=now.astimezone(SEOUL)
    if not check_only and os.environ.get('GITHUB_REF')!='refs/heads/main':raise ValueError('paid cloud execution requires main')
    store=store or GitHubStateStore(root,os.environ.get('GH_TOKEN',''),AgeState(root,safe_path(root,'.tools/cloud-state/identity.txt')))
    preflight=CloudSession.read_control(root,store)
    # Trusted runner applies the approved limit revision once with its short-lived token.
    revised=preflight.apply_limit_revision()
    resumed=False
    if (resume or retry or probe_only) and os.environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch':
        raise ValueError('halt review, day retry and grammar probe require a manual dispatch')
    if resume:
        resumed=preflight.resume_after_review(now)
    if not check_only or probe_only:
        if not preflight.control['active']:return {'status':'handoff_required'}
        control=preflight.control;budget=control['budget']
        # Monthly cap reached: stop for this run only. The workflow stays enabled so the next
        # Seoul calendar month resumes by itself; only the ledger decides.
        if TrialBudget.exhausted(budget,now):return {'status':'trial_budget_limit'}
    session=CloudSession.restore(root,store)
    key=configured_key(root)
    if hashlib.sha256(key.encode()).hexdigest()!=session.control['api_key_sha256']:
        raise ValueError('API Secret differs from approved local key')
    budget=TrialBudget(safe_path(root,BUDGET)).summary()
    day=now.date().isoformat()
    summary={'requests':len(budget['requests']),'exposure_microdollars':budget['exposure_microdollars'],
             'day_status':session.control['days'].get(day,{}).get('status'),'active':session.control['active'],
             'halt_resumed':resumed}
    if probe_only:
        # Paid but tiny; never marks a day. Persists the probe cache and the ledger row.
        client=ClaudeClient(safe_path(root,'.tools/claude-trial/live'),
                            TrialBudget(safe_path(root,BUDGET),checkpoint=session.checkpoint_budget),key)
        probe=client.grammar_probe(research_wire_schema())
        session.save_runtime()
        return dict(summary,status='probe_'+probe['status'],probe=probe)
    if check_only:
        data=dict(session.control)
        data['check']={'snapshot_sha256':snapshot_digest(data),'ref':os.environ.get('GITHUB_REF',''),
                       'code_sha':os.environ.get('GITHUB_SHA',''),'run_id':os.environ.get('GITHUB_RUN_ID','')}
        session._commit(data)  # Confirms contents:write without day or provider admission.
        return dict(summary,status='check_passed',limit_revision_applied=revised,expires_at=data['expires_at'],
                    cap_kind=data['budget'].get('cap_kind'),
                    month_exposure_microdollars=TrialBudget.month_exposure(data['budget'],now))
    if not session.control['active']:return {'status':'handoff_required'}
    if now.hour<6:return {'status':'not_due'}
    retried=False
    if retry:
        if todays_refresh(store,now)!='ready':return {'status':'waiting_for_existing_refresh'}
        retried=session.retry_rejected_day(day,now)
        # The remote row keeps the original outcome; the inner local mirror must not see today.
        save(safe_path(root,'cache/ai_daily/days.json'),{'days':{k:v for k,v in session.control['days'].items() if k!=day}})
    elif day in session.control['days']:
        return {'status':'already_completed_today' if session.control['days'][day]['status']=='completed' else 'previous_attempt_requires_review'}
    refresh=todays_refresh(store,now)
    if refresh=='missing' and now.hour>=FALLBACK_REFRESH_HOUR:
        dispatch_refresh(store);return {'status':'refresh_dispatched'}  # Its completion triggers this workflow.
    if refresh!='ready':return {'status':'waiting_for_existing_refresh','refresh':refresh}
    public_lease=restore_public(root,store,now)
    if not retried:session.mark_day(day)
    save(safe_path(root,'ai-automation.json'),{'enabled':True,'recurring_spend_approved':True,
         'public_application_approved':True,'remote_delivery_approved':False,'max_ai_candidates_per_day':MAX_DAILY_RESEARCH})
    try:
        result=daily(root,now=now,online=True,allow_spend=True,publish=True)
        if result['status'] not in ('completed','credit_exhausted'):raise ValueError('inner daily did not complete')
        session.save_runtime()
        delivery=publish_snapshot(root,store,now,key,expected_sha=public_lease)
        if result['status']=='credit_exhausted':
            # Results already received stay; the day is failed, the trial is not halted, tomorrow runs normally.
            session.finish(day,'failed');write_ai_status(root,'credit_exhausted',day,now)
            return {'status':'credit_exhausted','day':day,'delivery':delivery}
        session.finish(day,'completed')
        after=TrialBudget(safe_path(root,BUDGET)).summary();new=after['requests'][summary['requests']:]
        failures=[row.get('error_code','unknown') for row in new if row['status']!='completed']
        status='completed_with_provider_failure' if failures or after['halted'] else 'completed'
        write_ai_status(root,'ok' if status=='completed' else 'failed',day,now)
        return {'status':status,'delivery':delivery,'new_requests':len(new),'provider_failures':failures,
                'halted':after['halted'],'retried_day':retried}
    except Exception:
        # Preserve results if possible; unresolved remote reservations still block restarts.
        try:session.save_runtime();session.finish(day,'failed')
        except Exception:pass
        try:write_ai_status(root,'failed',day,now)
        except Exception:pass
        raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    try:result=cloud_run(Path(__file__).resolve().parents[1],check_only=not args.execute)
    except Exception:
        print('cloud_stopped_requires_review');return 1
    print(json.dumps(result,sort_keys=True));return exit_code(result)


def exit_code(result):
    """A finished day with provider rejections must not look green in Actions."""
    if result.get('status') in ATTENTION:
        if result['status']=='credit_exhausted':print('::error::Anthropic credit balance exhausted; today skipped, trial not halted, next day runs normally')
        elif result['status']=='probe_rejected':print('::error::grammar probe rejected the research schema; trial not halted')
        else:print('::error::AI provider rejected '+str(len(result.get('provider_failures',[])))+' request(s); trial halted='+str(result.get('halted')))
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
