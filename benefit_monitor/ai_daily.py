"""Daily local orchestration. Recurring spend and public application default off."""
import argparse
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .cli import run as collect
from .official_reader import project_path
from .publish import run as publish_briefing, prepare_import
from .store import load,save,lock
from .topic_refresh import refresh
from .grocery_pick import refresh as grocery_refresh
from .remote_delivery import deliver,preceding_refresh


def daily(root,now=None,online=False,allow_spend=False,publish=False,scheduled=False,snapshot=None):
    root=Path(root).resolve()
    now=now or datetime.now(ZoneInfo('Asia/Seoul'))
    if now.tzinfo is None:raise ValueError('timezone required')
    now=now.astimezone(ZoneInfo('Asia/Seoul'))
    policy=load(project_path(root,'ai-automation.json'),{'enabled':False})
    if scheduled:
        if policy.get('enabled') is not True:return {'status':'disabled'}
        hour,minute=policy.get('hour_kst',6),policy.get('minute_kst',0)
        if type(hour)is not int or not 0<=hour<=23 or type(minute)is not int or not 0<=minute<=59:
            raise ValueError('invalid daily time')
        if (now.hour,now.minute)<(hour,minute):return {'status':'not_due'}
        online=True
        allow_spend=policy.get('recurring_spend_approved') is True
        publish=policy.get('public_application_approved') is True
    if allow_spend and policy.get('recurring_spend_approved') is not True:
        raise ValueError('explicit recurring spend approval required')
    if publish and policy.get('public_application_approved') is not True:
        raise ValueError('explicit public application approval required')
    if not online:
        return {'status':'dry_run','recurring_spend_approved':policy.get('recurring_spend_approved') is True,
                'public_application_approved':policy.get('public_application_approved') is True}
    if policy.get('enabled') is not True:raise ValueError('daily pipeline is disabled')
    limit=policy.get('max_ai_candidates_per_day',2)
    if type(limit)is not int or not 1<=limit<=20:raise ValueError('daily candidate limit 1..20')
    verify_limit=policy.get('max_ai_verifications_per_day',0)
    if type(verify_limit)is not int or not 0<=verify_limit<=40:raise ValueError('daily verification limit 0..40')
    day=now.date().isoformat()
    with lock(project_path(root,'cache/ai_daily/.lock')):
        state=load(project_path(root,'cache/ai_daily/days.json'),{'days':{}})
        if day in state['days']:
            previous=state['days'][day]
            return {'status':'already_completed_today' if previous['status']=='completed' else 'previous_attempt_requires_review','day':day}
        if scheduled and publish and policy.get('remote_delivery_approved') is True:
            previous_refresh=preceding_refresh(root,now)
            if previous_refresh['status']!='ready':return previous_refresh
        state['days'][day]={'status':'attempted','started_at':now.isoformat()}
        save(project_path(root,'cache/ai_daily/days.json'),state)
        try:
            imports=prepare_import(root,now) if project_path(root,'public/verified.json').exists() else None
            collection=collect(root,imports=imports,online=True,now=now,ai_review=True,
                               ai_execute=allow_spend,ai_max_candidates=limit,snapshot=snapshot,ai_max_verify=verify_limit)
            exhausted=bool((collection or {}).get('ai_review',{}).get('credit_exhausted'))
            # The topic step is a paid call too; skip it once credit has run out.
            topics=refresh(root,now=now,execute=allow_spend) if not exhausted else {'topics':[],'skipped':'credit_exhausted'}
            exhausted=exhausted or (topics.get('model') or {}).get('status')=='credit_exhausted'
            # One paid grocery pick a day; without credit it still writes the rule pick (no model text).
            try:
                grocery=grocery_refresh(root,now,execute=allow_spend and not exhausted)
            except Exception as error:  # Optional card: never blocks publishing the day's paid results.
                grocery={'status':'failed','error_type':type(error).__name__,'model':None}
            exhausted=exhausted or (grocery.get('model') or {}).get('status')=='credit_exhausted'
            public=publish_briefing(root,now=now) if publish else None
            remote=deliver(root,policy,now=now) if publish and policy.get('remote_delivery_approved') is True else None
            result={'status':'credit_exhausted' if exhausted else 'completed','day':day,'collection':collection,'topics':topics,'grocery':grocery,'public_exported':public is not None,
                    'remote_delivery':remote,'recurring_spend_requested':allow_spend,'public_status':public.get('status') if public else None}
            state['days'][day].update(status='failed' if exhausted else 'completed',finished_at=now.isoformat())
            save(project_path(root,'cache/ai_daily/days.json'),state)
            save(project_path(root,'cache/ai_daily/latest.json'),result)
            return result
        except Exception as error:
            state['days'][day].update(status='failed',error_type=type(error).__name__)
            save(project_path(root,'cache/ai_daily/days.json'),state)
            if publish:
                try:publish_briefing(root,now=now,failure=True)
                except Exception:pass
            raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--online',action='store_true')
    parser.add_argument('--allow-spend',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--scheduled',action='store_true')
    args=parser.parse_args()
    result=daily(args.root,online=args.online,allow_spend=args.allow_spend,publish=args.publish,scheduled=args.scheduled)
    print(result['status'])


if __name__=='__main__':main()
