"""Materialize the step-only identity without exposing it in shell commands."""
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from benefit_monitor.cloud_daily import cloud_run,trusted_environment
from benefit_monitor.trial_budget import secure_open
from scripts.install_age import safe_path
import json


def main():
    identity=safe_path(ROOT,'.tools/cloud-state/identity.txt');created=False
    try:
        trusted_environment()
        identity.parent.mkdir(parents=True,exist_ok=True)
        value=os.environ.pop('BENEFIT_AI_STATE_IDENTITY','')
        if not value or len(value)>4096:raise ValueError('state identity Secret required')
        with os.fdopen(secure_open(identity,os.O_WRONLY|os.O_CREAT|os.O_EXCL),'w') as stream:
            created=True;stream.write(value)
        result=cloud_run(ROOT,check_only=os.environ.get('CHECK_ONLY','true')!='false')
        print(json.dumps(result,sort_keys=True));return 0
    except Exception:
        print('cloud_stopped_requires_review');return 1
    finally:
        if created and identity.is_file() and not identity.is_symlink():identity.unlink()


if __name__=='__main__':raise SystemExit(main())
