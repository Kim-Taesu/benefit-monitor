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


def _run(args,**kwargs):
    return subprocess.run(args,check=True,capture_output=True,text=True,**kwargs).stdout.strip()


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
    allowed=('PATH','HOME','LANG','LC_ALL','LC_CTYPE','TMPDIR')
    env={k:os.environ[k] for k in allowed if k in os.environ}
    token=_run(['gh','auth','token','--hostname','github.com','--user','Kim-Taesu'],env=env)
    if not token or '\n' in token:raise ValueError('personal GitHub credential unavailable')
    env.update(GH_TOKEN=token,GH_HOST='github.com',GH_NO_UPDATE_NOTIFIER='1',GH_NO_EXTENSION_UPDATE_NOTIFIER='1')
    login=_run(['gh','api','--hostname','github.com','user','--jq','.login'],env=env)
    if login.casefold()!='kim-taesu':raise ValueError('personal GitHub identity mismatch')
    metadata=json.loads(_run(['gh','api','--hostname','github.com','repos/'+REPOSITORY],env=env))
    if metadata.get('private') is not False:raise ValueError('public repository required for the existing free workflow')
    content=(json.dumps(clean,ensure_ascii=False,indent=2)+'\n').encode()
    commit=mirror(root,REPOSITORY,env=env,content=content)
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('immutable snapshot commit not returned')
    _run(['gh','workflow','run','briefing-pages.yml','--repo',REPOSITORY,'--ref',ref,
          '-f','deploy_approved_snapshot=true','-f','snapshot_commit='+commit,'-f','expected_code_sha='+code_sha],env=env)
    return {'repository':REPOSITORY,'snapshot_commit':commit,'code_sha':code_sha,'ref':ref,
            'status':'dispatched_not_yet_verified','main_merged':False}
