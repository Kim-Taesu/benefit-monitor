"""Project-local personal-account handoff. Never enables local and cloud together."""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from benefit_monitor.age_state import AgeState,pack_runtime
from benefit_monitor.claude_trial import configured_key
from benefit_monitor.cloud_state import CloudSession,GitHubStateStore,REPOSITORY,BUDGET,MAX_EXPIRY,requests_digest,validate_control,snapshot_digest
from benefit_monitor.remote_delivery import github_environment
from benefit_monitor.store import load,save
from benefit_monitor.trial_budget import TrialBudget,secure_open
from scripts.install_age import safe_path,verify_installation

IDENTITY='.tools/cloud-state/identity.txt'
RECEIPT='.tools/cloud-state/handoff.json'
POLICY='public/ai-cloud-trial.json'
JOB='gui/501/com.benefit-monitor.ai-daily'


def capture_control(root,crypto):
    budget=load(safe_path(root,BUDGET),None)
    TrialBudget(safe_path(root,BUDGET))._validate(budget)
    if budget['halted'] or any(row['status']=='reserved' for row in budget['requests']):
        raise ValueError('unresolved local reservation; handoff refused')
    days=load(safe_path(root,'cache/ai_daily/days.json'),{})['days']
    if any(row.get('status')=='attempted' for row in days.values()):raise ValueError('local daily work is unfinished')
    policy=load(safe_path(root,POLICY),{})
    result={'schema_version':1,'trial_id':policy['trial_id'],'active':False,'generation':0,
            'expires_at':policy['expires_at'],'recipient':crypto.recipient,
            'api_key_sha256':hashlib.sha256(configured_key(root).encode()).hexdigest(),
            'budget':budget,'days':days,'runtime_sha':None}
    validate_control(root,result)
    return result


def _optional_control(store):
    # Only explicit prepare may bootstrap; 404 alone means absent, all other failures stop.
    try:return store.read('control')
    except ValueError as error:
        if str(error)=='GitHub state request failed: http_404':return None,None
        raise


def prepare_state(root,store):
    raw,lease=_optional_control(store)
    old=json.loads(raw) if raw is not None else None
    if old is not None and old['active']:raise ValueError('cloud already active; do not replace')
    data=capture_control(root,store.crypto)
    if old is not None:
        validate_control(root,old)
        if old['budget']['requests']!=data['budget']['requests'][:len(old['budget']['requests'])]:
            raise ValueError('local and remote ledgers diverged')
        data['generation']=old['generation']+1
        _,runtime_lease=store._cipher('runtime')
    else:
        try:_,runtime_lease=store._cipher('runtime')
        except ValueError as error:
            if str(error)!='GitHub state request failed: http_404':raise
            runtime_lease=None
    data['runtime_sha']=store.write('runtime',pack_runtime(root),runtime_lease)
    sha=store.write('control',json.dumps(data,ensure_ascii=False).encode(),lease)
    save(safe_path(root,RECEIPT),{'phase':'prepared','snapshot_sha256':snapshot_digest(data),'control_sha':sha})
    return {'status':'prepared_inactive','requests':len(data['budget']['requests'])}


def local_loaded(root):
    # This is the single user-authorized job; no other launchd/global settings.
    result=subprocess.run(['/bin/launchctl','print',JOB],capture_output=True,text=True,timeout=15)
    if result.returncode==0:return True
    if 'Could not find service' in result.stderr:return False
    raise ValueError('cannot determine local scheduler state')


def stop_local(root):
    result=subprocess.run(['/bin/launchctl','print',JOB],capture_output=True,text=True,timeout=15)
    if result.returncode==0:
        if 'state = running' in result.stdout:raise ValueError('local job is running; wait before handoff')
        stopped=subprocess.run(['/bin/launchctl','bootout',JOB],capture_output=True,text=True,timeout=15)
        if stopped.returncode:raise ValueError('local scheduler stop failed')
    elif 'Could not find service' not in result.stderr:raise ValueError('cannot inspect local scheduler')
    if local_loaded(root):raise ValueError('local scheduler remains loaded')
    policy=load(safe_path(root,'ai-automation.json'),{})
    policy['enabled']=False;save(safe_path(root,'ai-automation.json'),policy)


def stage_activation(root,store,main_sha):
    raw,_=store.read('control');old=validate_control(root,json.loads(raw))
    if old['active']:raise ValueError('cloud is already active')
    stop_local(root)  # Must precede the fresh capture/upload; failure leaves cloud inactive.
    result=prepare_state(root,store)
    receipt=load(safe_path(root,RECEIPT),{});receipt.update(phase='staged',main_sha=main_sha)
    save(safe_path(root,RECEIPT),receipt)
    return dict(result,status='staged_requires_main_check')


def activate_checked(root,store,main_sha):
    if local_loaded(root) or load(safe_path(root,'ai-automation.json'),{}).get('enabled') is not False:
        raise ValueError('local writer must be stopped first')
    receipt=load(safe_path(root,RECEIPT),{})
    raw,sha=store.read('control');data=validate_control(root,json.loads(raw));check=data.get('check',{})
    if (receipt.get('phase')!='staged' or receipt.get('main_sha')!=main_sha or data['active']
            or snapshot_digest(data)!=receipt.get('snapshot_sha256')
            or check.get('snapshot_sha256')!=snapshot_digest(data)
            or check.get('ref')!='refs/heads/main' or check.get('code_sha')!=main_sha):
        raise ValueError('latest staged main cloud validation required')
    # A local mutation after staging must never be silently discarded.
    if (load(safe_path(root,BUDGET),None)!=data['budget']
            or load(safe_path(root,'cache/ai_daily/days.json'),{}).get('days')!=data['days']):
        raise ValueError('local state changed since staging')
    if data['budget']['halted'] or any(row['status']=='reserved' for row in data['budget']['requests']):
        raise ValueError('unresolved budget cannot activate')
    session=CloudSession(root,store,data,sha);data=deepcopy(data);data['active']=True;session._commit(data)
    receipt['phase']='active';save(safe_path(root,RECEIPT),receipt)
    return {'status':'cloud_active','requests':len(data['budget']['requests'])}


def setup_identity(root,env):
    path=safe_path(root,IDENTITY);binary=verify_installation(root)
    if binary is None:raise ValueError('install pinned age first')
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True)
        process=subprocess.run([str(binary.with_name('age-keygen')),'-o',str(path)],capture_output=True,
                               env={k:v for k,v in env.items() if k in ('PATH','LANG','LC_ALL','TMPDIR')},timeout=30)
        if process.returncode:raise ValueError('identity generation failed')
        path.chmod(0o600)
    crypto=AgeState(root,path)
    with os.fdopen(secure_open(path,os.O_RDONLY)) as stream:identity=stream.read()
    result=subprocess.run(['gh','secret','set','BENEFIT_AI_STATE_IDENTITY','--repo',REPOSITORY],input=identity,
                          capture_output=True,text=True,env=env,timeout=45)
    if result.returncode:raise ValueError('identity Secret registration failed')
    return crypto


def setup_policy(root,crypto):
    path=safe_path(root,POLICY)
    if path.exists():
        policy=load(path,{})
        if policy['recipient']!=crypto.recipient:raise ValueError('existing policy identity mismatch')
        return
    budget=load(safe_path(root,BUDGET),None);TrialBudget(safe_path(root,BUDGET))._validate(budget)
    if len(budget['requests'])<30:raise ValueError('missing original 30 requests')
    baseline=deepcopy(budget);baseline['requests']=baseline['requests'][:30]
    save(path,{'schema_version':1,'approved':True,'trial_id':'claude-2026-11-05-actions',
         'expires_at':MAX_EXPIRY.isoformat(),'model':'claude-haiku-5-5','recipient':crypto.recipient,
         'baseline_requests':30,'baseline_requests_sha256':requests_digest(baseline['requests']),
         'baseline_exposure_microdollars':TrialBudget._exposure(baseline),'baseline_days':{'2026-11-05':'completed'}})


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','check','activate','restore'))
    args=parser.parse_args();root=ROOT
    try:
        env=github_environment(root)
        def api(path):
            process=subprocess.run(['gh','api','repos/'+REPOSITORY+('/'+path if path else '')],env=env,capture_output=True,text=True,timeout=45)
            if process.returncode:raise ValueError('personal repository check failed')
            return json.loads(process.stdout)
        metadata=api('')
        if metadata.get('private') is not False or metadata.get('full_name')!=REPOSITORY:raise ValueError('public personal repository required')
        if args.command=='prepare':
            crypto=setup_identity(root,env);setup_policy(root,crypto)
        else:crypto=AgeState(root,safe_path(root,IDENTITY))
        store=GitHubStateStore(root,env['GH_TOKEN'],crypto)
        if args.command=='prepare':result=prepare_state(root,store)
        elif args.command=='check':
            raw,_=store.read('control');data=validate_control(root,json.loads(raw))
            result={'status':'control_valid','active':data['active'],'requests':len(data['budget']['requests'])}
        elif args.command=='restore':
            if local_loaded(root) or load(safe_path(root,'ai-automation.json'),{}).get('enabled') is not False:
                raise ValueError('stop local writer before restore; never auto-resume')
            session=CloudSession.restore(root,store);result={'status':'restored_local_still_disabled','requests':len(session.control['budget']['requests'])}
        else:
            main_sha=api('branches/main')['commit']['sha']
            head=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
            if head!=main_sha:raise ValueError('checkout must match user-merged main before handoff')
            receipt=load(safe_path(root,RECEIPT),{})
            result=activate_checked(root,store,main_sha) if receipt.get('phase')=='staged' else stage_activation(root,store,main_sha)
        print(json.dumps(result,sort_keys=True));return 0
    except Exception:
        print('handoff_stopped_requires_review');return 1


if __name__=='__main__':raise SystemExit(main())
