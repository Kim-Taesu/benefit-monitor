"""Local check and recovery of the cloud AI state. The Mac-to-cloud handoff itself is retired.

The handoff (prepare/activate) finished on 2026-11-05; since the 2026-11-07 ledger revision the cloud
control has no expiry and a monthly cap, which a fresh local capture cannot express. Re-running it
would only fail or try to replace the live ledger, so those commands stop with a clear message.
`check` validates the remote control and `restore` copies it locally without enabling any schedule.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from benefit_monitor.age_state import AgeState
from benefit_monitor.cloud_state import CloudSession,GitHubStateStore,REPOSITORY,validate_control
from benefit_monitor.remote_delivery import github_environment
from benefit_monitor.store import load
from scripts.install_age import safe_path

IDENTITY='.tools/cloud-state/identity.txt'
JOB='gui/501/com.benefit-monitor.ai-daily'
RETIRED=('ai_cloud_handoff prepare/activate is retired: the cloud has been the only AI writer since 2026-11-05 '
         'and its revision-2 control (monthly cap, no expiry) must not be replaced from a local capture. '
         'Use "check" or "restore"; see docs/ai/automation.md.')


def local_loaded(root):
    # This is the single user-authorized job; no other launchd/global settings.
    result=subprocess.run(['/bin/launchctl','print',JOB],capture_output=True,text=True,timeout=15)
    if result.returncode==0:return True
    if 'Could not find service' in result.stderr:return False
    raise ValueError('cannot determine local scheduler state')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('prepare','check','activate','restore'))
    args=parser.parse_args(argv);root=ROOT
    if args.command in ('prepare','activate'):
        print(RETIRED,file=sys.stderr);return 2
    try:
        env=github_environment(root)
        process=subprocess.run(['gh','api','repos/'+REPOSITORY],env=env,capture_output=True,text=True,timeout=45)
        if process.returncode:raise ValueError('personal repository check failed')
        metadata=json.loads(process.stdout)
        if metadata.get('private') is not False or metadata.get('full_name')!=REPOSITORY:raise ValueError('public personal repository required')
        store=GitHubStateStore(root,env['GH_TOKEN'],AgeState(root,safe_path(root,IDENTITY)))
        if args.command=='check':
            raw,_=store.read('control');data=validate_control(root,json.loads(raw))
            result={'status':'control_valid','active':data['active'],'requests':len(data['budget']['requests'])}
        else:
            if local_loaded(root) or load(safe_path(root,'ai-automation.json'),{}).get('enabled') is not False:
                raise ValueError('stop local writer before restore; never auto-resume')
            session=CloudSession.restore(root,store,allow_unresolved=True)
            result={'status':'restored_local_still_disabled','requests':len(session.control['budget']['requests'])}
        print(json.dumps(result,sort_keys=True));return 0
    except Exception:
        print('handoff_stopped_requires_review');return 1


if __name__=='__main__':raise SystemExit(main())
