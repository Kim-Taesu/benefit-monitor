"""Encrypted GitHub control with file leases; never initializes missing state."""
import base64
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError,URLError
from urllib.request import Request,build_opener

from .age_state import AgeState,pack_runtime,restore_runtime
from .research_probe import NoRedirect
from .store import save,load
from .briefing import SEOUL
from .trial_budget import TrialBudget,secure_open,MONTHLY_CAP
from scripts.install_age import safe_path

REPOSITORY='Kim-Taesu/benefit-monitor'
BRANCH='briefing-data'
# The ledger grows without a request/day limit now; sized for the 8 MiB ledger file cap.
MAX_CIPHER=8*1024*1024
MAX_RESPONSE=16*1024*1024
OBJECT_MEDIA='application/vnd.github.object+json'
FILES={'control':'ai-control.age','runtime':'ai-runtime.age','collection':'ai-collection.age'}
CONTEXT='.tools/cloud-state/context.json'
BUDGET='.tools/claude-trial/live/budget.json'
# Upper bound for pre-revision (limit_revision < 2) controls only; revision 2 has no expiry.
MAX_EXPIRY=datetime.fromisoformat('2026-11-19T13:09:12.753468+09:00')
# 2: monthly $15 cap, no request/day limit, no expiry (user-approved 2026-11-07).
LIMIT_REVISION=2


def requests_digest(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def snapshot_digest(data):
    return requests_digest({k:data[k] for k in ('trial_id','expires_at','recipient','api_key_sha256','budget','days','runtime_sha')})


def _blob_sha(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def validate_control(root,data):
    try:
        policy=load(safe_path(root,'public/ai-cloud-trial.json'),{})
        if (policy.get('schema_version')!=1 or policy.get('approved') is not True
                or policy.get('baseline_requests')!=30 or data['schema_version']!=1
                or data['trial_id']!=policy['trial_id'] or type(data['active'])is not bool
                or type(data['generation'])is not int or not 0<=data['generation']<=1_000_000
                or data['recipient']!=policy['recipient']
                or not re.fullmatch('[0-9a-f]{64}',data['api_key_sha256'])):raise ValueError
        revision=data.get('limit_revision',0)
        if data['expires_at'] is not None:
            expiry=datetime.fromisoformat(data['expires_at'])
            if expiry.tzinfo is None:raise ValueError
            if policy['expires_at'] is not None:
                bound=datetime.fromisoformat(policy['expires_at'])
                if bound.tzinfo is None or not expiry<=bound<=MAX_EXPIRY:raise ValueError
        elif revision!=LIMIT_REVISION:raise ValueError
        budget=data['budget'];TrialBudget(safe_path(root,BUDGET))._validate(budget)
        if (policy['model']!='claude-haiku-5-5' or budget['model']!=policy['model']
                or len(budget['requests'])<30 or requests_digest(budget['requests'][:30])!=policy['baseline_requests_sha256']
                or TrialBudget._exposure(budget)<policy['baseline_exposure_microdollars']):raise ValueError
        if revision not in (0,1,LIMIT_REVISION):raise ValueError
        if revision==LIMIT_REVISION and TrialBudget.is_legacy(budget):raise ValueError
        if revision==1 and budget.get('max_requests')!=200:raise ValueError
        if not isinstance(data['days'],dict):raise ValueError
        for day,row in data['days'].items():
            if datetime.fromisoformat(day).date().isoformat()!=day or row.get('status') not in ('attempted','failed','completed'):raise ValueError
        if policy['baseline_days'].get('2026-11-05')!='completed':raise ValueError
        for day,status in policy['baseline_days'].items():
            if data['days'].get(day,{}).get('status')!=status:raise ValueError
        if data['runtime_sha'] is not None and not re.fullmatch('[0-9a-f]{40}',data['runtime_sha']):raise ValueError
        if data['active'] and data['runtime_sha'] is None:raise ValueError
    except (KeyError,TypeError,AttributeError,ValueError):
        raise ValueError('invalid cloud control; do not reset') from None
    return data


class GitHubStateStore:
    def __init__(self,root,token,crypto,opener=None):
        self.root=Path(root).resolve();safe_path(self.root,CONTEXT)
        if not isinstance(token,str) or not re.fullmatch(r'[\x21-\x7e]{1,4096}',token):raise ValueError('GitHub token required')
        self.token,self.crypto=token,crypto
        self.opener=opener or (lambda request:build_opener(NoRedirect()).open(request,timeout=40))

    def _api(self,path,body=None,accept='application/vnd.github+json'):
        payload=json.dumps(body,separators=(',',':')).encode() if body is not None else None
        request=Request('https://api.github.com/repos/'+REPOSITORY+('/'+path if path else ''),data=payload,
                        headers={'Authorization':'Bearer '+self.token,'Accept':accept,
                                 'Content-Type':'application/json','User-Agent':'BenefitMonitor-AI-State/1.0'},
                        method='PUT' if body is not None else 'GET')
        try:
            with self.opener(request) as response:raw=response.read(MAX_RESPONSE+1)
            if len(raw)>MAX_RESPONSE:raise ValueError('GitHub state response too large')
            return json.loads(raw)
        except HTTPError as error:
            code=error.code;error.close();raise ValueError('GitHub state request failed: http_'+str(code)) from None
        except (OSError,URLError,json.JSONDecodeError):raise ValueError('GitHub state request unavailable') from None

    def lease(self,kind):
        """Current blob sha of a state file without downloading it (works past the 1 MB contents limit)."""
        if kind not in FILES:raise ValueError('unknown cloud state file')
        meta=self._api('contents/'+FILES[kind]+'?ref='+BRANCH,accept=OBJECT_MEDIA)
        try:
            sha=meta['sha']
            if meta.get('type','file')!='file' or not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError
        except (KeyError,TypeError,ValueError):raise ValueError('invalid encrypted GitHub state') from None
        return sha,meta

    def _cipher(self,kind,ref=None):
        if kind not in FILES:raise ValueError('unknown cloud state file')
        if ref is not None:
            if kind!='runtime' or not re.fullmatch('[0-9a-f]{40}',ref):raise ValueError('immutable runtime blob required')
            data=self._api('git/blobs/'+ref)
        else:
            # The contents API inlines only files up to 1 MB (larger ones come back with
            # encoding "none"); those are read by their blob sha, which handles up to 100 MB.
            sha,data=self.lease(kind)
            if data.get('encoding')!='base64' or not data.get('content'):
                ref=sha;data=self._api('git/blobs/'+sha)
        try:
            if data['encoding']!='base64':raise ValueError
            raw=base64.b64decode(''.join(data['content'].split()),validate=True)
            sha=_blob_sha(raw)
            if len(raw)>MAX_CIPHER or data['sha']!=sha or ref is not None and ref!=sha:raise ValueError
        except (KeyError,TypeError,ValueError):raise ValueError('invalid encrypted GitHub state') from None
        return raw,sha

    def read(self,kind,ref=None):
        raw,sha=self._cipher(kind,ref)
        return self.crypto.decrypt(raw),sha

    def write(self,kind,raw,expected_sha):
        if kind not in FILES or expected_sha is not None and not re.fullmatch('[0-9a-f]{40}',expected_sha):
            raise ValueError('invalid cloud state file lease')
        cipher=self.crypto.encrypt(raw)
        if len(cipher)>MAX_CIPHER:raise ValueError('encrypted state exceeds 8 MiB')
        body={'message':'Update encrypted AI '+kind,'branch':BRANCH,'content':base64.b64encode(cipher).decode()}
        if expected_sha is not None:body['sha']=expected_sha
        result=self._api('contents/'+FILES[kind],body)
        try:
            sha=result['content']['sha']
            if sha!=_blob_sha(cipher):raise ValueError
        except (KeyError,TypeError,ValueError):raise ValueError('cloud state write not confirmed') from None
        confirmed,actual=self._cipher(kind)
        if actual!=sha or confirmed!=cipher:raise ValueError('cloud state lease changed after write')
        return sha


class CloudSession:
    def __init__(self,root,store,control,sha):
        self.root,self.store=Path(root).resolve(),store
        self.context=safe_path(self.root,CONTEXT)
        self.control,self.sha=validate_control(self.root,control),sha
        if self.control['recipient']!=store.crypto.recipient:raise ValueError('cloud identity differs from approved recipient')

    @classmethod
    def read_control(cls,root,store):
        raw,sha=store.read('control')
        try:data=json.loads(raw)
        except (ValueError,TypeError):raise ValueError('invalid cloud control JSON') from None
        return cls(root,store,data,sha)

    @classmethod
    def restore(cls,root,store,*,allow_unresolved=False):
        result=cls.read_control(root,store);data=result.control
        if not allow_unresolved and (data['budget']['halted'] or any(row['status']=='reserved' for row in data['budget']['requests'])):
            raise ValueError('unresolved cloud budget requires manual review')
        if data['runtime_sha'] is not None:
            runtime,_=store.read('runtime',data['runtime_sha']);restore_runtime(result.root,runtime)
        save(safe_path(result.root,BUDGET),data['budget'])
        save(safe_path(result.root,'cache/ai_daily/days.json'),{'days':data['days']})
        result._save_context()
        return result

    @classmethod
    def from_context(cls,root,store):
        path=safe_path(root,CONTEXT)
        with os.fdopen(secure_open(path,os.O_RDONLY)) as stream:raw=stream.read(MAX_RESPONSE+1)
        if len(raw)>MAX_RESPONSE:raise ValueError('cloud context too large')
        try:data=json.loads(raw);return cls(root,store,data['control'],data['sha'])
        except (KeyError,TypeError,ValueError):raise ValueError('invalid cloud context') from None

    def _save_context(self):save(self.context,{'control':self.control,'sha':self.sha})

    def _reload(self):
        fresh=self.from_context(self.root,self.store);self.control,self.sha=fresh.control,fresh.sha

    def _commit(self,data):
        data['generation']=self.control['generation']+1;validate_control(self.root,data)
        sha=self.store.write('control',json.dumps(data,ensure_ascii=False,separators=(',',':')).encode(),self.sha)
        self.control,self.sha=data,sha;self._save_context()

    def apply_limit_revision(self):
        """One-way upgrade of limits only: request rows, reservations, halts and days stay as they are."""
        if self.control.get('limit_revision',0)==LIMIT_REVISION:return False
        policy=load(safe_path(self.root,'public/ai-cloud-trial.json'),{})
        if policy.get('limit_revision')!=LIMIT_REVISION:return False
        data=deepcopy(self.control)
        budget=data['budget'];budget.pop('max_requests',None)
        budget['cap_microdollars']=MONTHLY_CAP;budget['cap_kind']='monthly'
        data['expires_at']=policy['expires_at'];data['limit_revision']=LIMIT_REVISION
        self._commit(data);return True

    def resume_after_review(self,now):
        """Human-dispatched halt release; every failed row and reserved dollar stays in the ledger."""
        data=deepcopy(self.control);budget=data['budget']
        if not budget['halted']:return False
        if any(row['status']=='reserved' for row in budget['requests']) or TrialBudget.exhausted(budget,now):
            raise ValueError('unresolved inflight request or exhausted budget')
        budget['halted']=False
        budget.setdefault('manual_reviews',[]).append(now.astimezone(timezone.utc).isoformat())
        self._commit(data);return True

    def retry_rejected_day(self,day,now):
        """One human-dispatched retry of a day whose every request was rejected unbilled (HTTP 4xx).

        The day keeps its slot and its original outcome under `retry_of`; ledger rows stay."""
        self._reload();data=deepcopy(self.control);row=data['days'].get(day)
        if not row or row['status'] not in ('completed','failed') or 'retry_of' in row:
            raise ValueError('day is not eligible for a rejected-request retry')
        same=[r for r in data['budget']['requests']
              if datetime.fromisoformat(r['started_at']).astimezone(SEOUL).date().isoformat()==day]
        if not same or any(r['status']!='failed' or r['charged_microdollars']!=0
                           or not re.fullmatch('http_4[0-9]{2}',r.get('error_code','')) for r in same):
            raise ValueError('only days whose requests were all rejected unbilled can be retried')
        data['days'][day]={'status':'attempted','retry_of':{'status':row['status'],'request_ids':[r['id'] for r in same],
                                                            'retried_at':now.isoformat()}}
        self._commit(data);return True

    def checkpoint_budget(self,budget):
        self._reload();old=self.control['budget'];rows=budget['requests'];previous=old['requests']
        if len(rows)<len(previous) or len(rows)>len(previous)+1:raise ValueError('cloud budget history cannot be replaced')
        for before,after in zip(previous,rows):
            if before['id']!=after['id'] or before['status']!='reserved' and before!=after:
                raise ValueError('settled cloud reservation cannot change')
            if before['status']=='reserved' and any(before.get(key)!=after.get(key) for key in ('reserved_microdollars','started_at')):
                raise ValueError('cloud reservation amount cannot change')
        if len(rows)>len(previous) and any(row['status']=='reserved' for row in previous):
            raise ValueError('prior cloud reservation is unresolved')
        data=deepcopy(self.control);data['budget']=deepcopy(budget);self._commit(data)

    def mark_day(self,day):
        self._reload()
        if day in self.control['days']:raise ValueError('cloud daily attempt already used')
        data=deepcopy(self.control);data['days'][day]={'status':'attempted'};self._commit(data)

    def finish(self,day,status):
        self._reload()
        if status not in ('completed','failed') or self.control['days'].get(day,{}).get('status')!='attempted':
            raise ValueError('invalid cloud daily completion')
        data=deepcopy(self.control);data['days'][day]['status']=status;self._commit(data)

    def save_runtime(self):
        self._reload()
        lease,_=self.store.lease('runtime')
        sha=self.store.write('runtime',pack_runtime(self.root),lease)
        data=deepcopy(self.control);data['runtime_sha']=sha;self._commit(data)


def budget_checkpoint_from_environment(root):
    if os.environ.get('BENEFIT_AI_CLOUD')!='1':return None
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('GITHUB_REPOSITORY')!=REPOSITORY:
        raise ValueError('cloud budget requires the approved Actions repository')
    root=Path(root).resolve();identity=safe_path(root,'.tools/cloud-state/identity.txt')
    token=os.environ.get('GH_TOKEN','')
    store=GitHubStateStore(root,token,AgeState(root,identity))
    return CloudSession.from_context(root,store).checkpoint_budget
