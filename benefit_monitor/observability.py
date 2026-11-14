"""Bounded private stage timings. Never logs inputs, model text, secrets or exception messages.

A trace is process-local; model subprocess wall time is measured by its parent invoke.
Records use unique span IDs with a shared attempt ID. They are not end-to-end billing.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import re
import sys
import time
import uuid

from .store import load, save, lock

ROOT=Path(__file__).resolve().parents[1]
FILE='cache/ai_daily/observations.json'
MAX_ROWS=1000
CURRENT=ContextVar('benefit_observations',default=None)


def flush(trace):
    root=trace['root']
    path=root/FILE
    lock_path=path.parent/'.lock-observations'
    if not root.resolve().is_relative_to(ROOT):raise ValueError('observation root outside project')
    for p in (path,lock_path):
        if p.is_symlink() or not p.resolve().is_relative_to(root):raise ValueError('observation path escapes root')
    if not trace['rows']:return
    with lock(lock_path):
        if path.exists() and path.stat().st_size>1024*1024:raise ValueError('oversized observations')
        previous=load(path,[])
        if not isinstance(previous,list):raise ValueError('invalid observations')
        save(path,(previous+trace['rows'])[-MAX_ROWS:])


def entry(function):
    @wraps(function)
    def wrapped(*args,**kwargs):
        if CURRENT.get() is not None:return function(*args,**kwargs)
        root=Path(kwargs.get('root',args[0] if args else ROOT)).resolve()
        trace={'root':root,'attempt_id':uuid.uuid4().hex,'rows':[],'sequence':0}
        token=CURRENT.set(trace)
        try:return function(*args,**kwargs)
        finally:
            CURRENT.reset(token)
            try:flush(trace)
            except (OSError,ValueError,TypeError):
                try:print('evaluation observations unavailable',file=sys.stderr)
                except (OSError,ValueError):pass
    return wrapped


class Observation:
    def __init__(self,stage,operation,trace):
        self.trace=trace
        self.started=time.perf_counter() if trace is not None else None
        self.row={'stage':stage,'operation':operation,'status':'ok','reason':None,
                  'cost_usd':None if stage=='extraction' else 0}

    def set_status(self,status,reason=None):
        self.row.update(status=status,reason=reason)

    def result(self,value):
        if isinstance(value,tuple) and len(value)==2 and isinstance(value[1],dict):
            if value[1].get('valid') is False:self.set_status('failed','validation_rejected')
        if not isinstance(value,dict):return
        if value.get('publish') is False:self.set_status('held','publication_held')
        status=value.get('status')
        if status in ('failed','rejected_draft','credit_exhausted','stopped_before_result'):
            self.set_status('failed',status)
        elif status in ('not_requested','insufficient_candidates','no_candidates','no_bundle','already_attempted_today','skipped') or value.get('skipped'):
            self.set_status('skipped','not_requested')
        elif value.get('used_fallback') is True or value.get('source')=='rule':
            self.set_status('held','rule_fallback')
        request_id=value.get('run_id')
        if isinstance(request_id,str) and re.fullmatch('[0-9a-f]{64}',request_id):
            self.row['request_id']=request_id

    def finish(self):
        if self.trace is None:return
        self.trace['sequence']+=1
        self.row.update(run_id=f"{self.trace['attempt_id']}-{self.trace['sequence']}",
                        attempt_id=self.trace['attempt_id'],
                        measured_at=datetime.now(timezone.utc).isoformat(),
                        duration_ms=round(max(0,time.perf_counter()-self.started)*1000,3))
        self.trace['rows'].append(self.row)
        # Bound memory too, not only persisted history.
        self.trace['rows']=self.trace['rows'][-MAX_ROWS:]


@contextmanager
def span(stage,operation):
    observation=Observation(stage,operation,CURRENT.get())
    try:yield observation
    except BaseException:
        observation.set_status('failed','operation_failed')
        raise
    finally:observation.finish()


def call(stage,operation,function,*args,**kwargs):
    with span(stage,operation) as observation:
        result=function(*args,**kwargs)
        observation.result(result)
        return result


def timed(stage,operation):
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):return call(stage,operation,function,*args,**kwargs)
        return wrapped
    return decorate
