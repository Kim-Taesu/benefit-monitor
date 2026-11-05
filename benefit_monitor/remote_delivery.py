"""Opt-in personal public delivery; no auth switch, billing or main merge."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess

from .briefing import SEOUL
from .mirror import run as mirror
from .official_reader import project_path
from .public_snapshot import REPOSITORY,validate
from .trial_budget import secure_open


def _run(args,**kwargs):
    return subprocess.run(args,check=True,capture_output=True,text=True,**kwargs).stdout.strip()


def personal_token(root,env):
    path=project_path(root,'.tools/personal-gh-auth/token.json')
    if path.exists():
        with os.fdopen(secure_open(path,os.O_RDONLY)) as stream:
            raw=stream.read(4097)
        if len(raw)>4096:raise ValueError('personal credential file too large')
        data=json.loads(raw)
        if data.get('login')!='Kim-Taesu':raise ValueError('personal credential identity mismatch')
        return data['token']
    return _run(['gh','auth','token','--hostname','github.com','--user','Kim-Taesu'],env=env)


def github_environment(root):
    allowed=('PATH','HOME','LANG','LC_ALL','LC_CTYPE','TMPDIR')
    env={k:os.environ[k] for k in allowed if k in os.environ}
    profile=project_path(root,'.tools/personal-gh-auth/hosts.yml')
    if profile.exists():env['GH_CONFIG_DIR']=str(profile.parent)
    token=personal_token(root,env)
    if not token or '\n' in token:raise ValueError('personal GitHub credential unavailable')
    env.update(GH_TOKEN=token,GH_HOST='github.com',GH_NO_UPDATE_NOTIFIER='1',GH_NO_EXTENSION_UPDATE_NOTIFIER='1')
    login=_run(['gh','api','--hostname','github.com','user','--jq','.login'],env=env)
    if login.casefold()!='kim-taesu':raise ValueError('personal GitHub identity mismatch')
    return env


def preceding_refresh(root,now):
    """Wait before spending so the existing main schedule cannot publish last."""
    if now.tzinfo is None:raise ValueError('timezone required')
    env=github_environment(root)
    endpoint='repos/'+REPOSITORY+'/actions/workflows/briefing-pages.yml/runs?event=schedule&branch=main&per_page=10'
    data=json.loads(_run(['gh','api','--hostname','github.com',endpoint],env=env))
    today=now.astimezone(SEOUL).date()
    runs=[row for row in data['workflow_runs']
          if datetime.fromisoformat(row['created_at']).astimezone(SEOUL).date()==today]
    return {'status':'ready' if runs and all(row['status']=='completed' for row in runs) else 'waiting_for_existing_refresh',
            'preceding_run_ids':[row['id'] for row in runs]}


def deliver(root,policy,now=None):
    if policy.get('public_application_approved') is not True or policy.get('remote_delivery_approved') is not True:
        raise ValueError('explicit remote public application approval required')
    repository=policy.get('repository','')
    if repository.casefold()!=REPOSITORY.casefold():raise ValueError('only the personal project repository is permitted')
    ref=policy.get('deploy_ref','')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,180}',ref) or '..' in ref or ref=='main':
        raise ValueError('explicit existing work branch required; main is not used')
    root=Path(root).resolve()
    project_path(root,'delivery/public/briefing.json')
    if _run(['git','status','--porcelain','--untracked-files=normal'],cwd=root):
        raise ValueError('a clean committed checkout is required before public delivery')
    code_sha=_run(['git','rev-parse','HEAD'],cwd=root)
    if not re.fullmatch('[0-9a-f]{40}',code_sha):raise ValueError('invalid code revision')
    raw=json.loads(project_path(root,'delivery/public/briefing.json').read_text())
    clean=validate(root,raw,now or datetime.now(SEOUL))
    # Strip inherited credentials before selecting the named personal account.
    env=github_environment(root)
    metadata=json.loads(_run(['gh','api','--hostname','github.com','repos/'+REPOSITORY],env=env))
    if metadata.get('private') is not False:raise ValueError('public repository required for the existing free workflow')
    content=(json.dumps(clean,ensure_ascii=False,indent=2)+'\n').encode()
    commit=mirror(root,REPOSITORY,env=env,content=content)
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('immutable snapshot commit not returned')
    _run(['gh','workflow','run','briefing-pages.yml','--repo',REPOSITORY,'--ref',ref,
          '-f','deploy_approved_snapshot=true','-f','snapshot_commit='+commit,'-f','expected_code_sha='+code_sha],env=env)
    return {'repository':REPOSITORY,'snapshot_commit':commit,'code_sha':code_sha,'ref':ref,
            'status':'dispatched_not_yet_verified','main_merged':False}
