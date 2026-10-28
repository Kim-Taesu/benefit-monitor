"""Public-safe observations, separate from human-approved benefit facts."""
from hashlib import sha256
from datetime import datetime, timedelta
from dataclasses import replace
from .models import Benefit


def digest(text):
    return sha256(' '.join(text.split()).encode()).hexdigest()


def observe(state, incoming, approved, now):
    stamp=now.isoformat()
    records=state.setdefault('items',{})
    state['schema_version']=1
    for data in incoming:
        item=Benefit(**data)
        row=records.setdefault(item.id,dict(source=item.source,first_seen_at=stamp))
        hashed=digest(item.title)
        if row.get('title_hash') and row['title_hash'] != hashed:
            row.update(hold_at=stamp,hold_reason='title_changed')
        row.update(title_hash=hashed,last_seen_at=stamp)
    result=[]
    for item in approved:
        row=records.setdefault(item.id,dict(source=item.source,first_seen_at=stamp))
        if row.get('hold_at'):
            if item.verified_at and datetime.fromisoformat(item.verified_at)>datetime.fromisoformat(row['hold_at']):
                row.pop('hold_at',None);row.pop('hold_reason',None)
            else:
                item=replace(item,needs_recheck=True)
        result.append(item)
    return result


def queue(report,state,now,max_age=7):
    rows=[]
    records=state.setdefault('items',{})
    for group in ('new','changed','still_valid','upcoming','expired','excluded'):
        for data in report.get(group,[]):
            row=records.get(Benefit(**data).id,{})
            row.pop('pending_reason',None);row.pop('pending_deadline',None)
    for item in report['needs_recheck']:
        key=Benefit(**item).id
        observation=state.get('items',{}).get(key,{})
        reason=observation.get('hold_reason') or ('verification_expired' if item.get('verified_at') and now-datetime.fromisoformat(item['verified_at'])>=timedelta(days=max_age) else 'manual_review')
        deadline=item.get('deadline_at') or item.get('valid_until')
        row=records.setdefault(key,dict(source=item['source'],first_seen_at=now.isoformat()))
        row['pending_reason']=reason
        if deadline:row['pending_deadline']=deadline
        rows.append(dict(id=key,source=item['source'],reason=reason,
                         first_seen_at=observation.get('first_seen_at'),
                         last_seen_at=observation.get('last_seen_at'),deadline=deadline))
    present={row['id'] for row in rows}
    for key,row in records.items():
        if key in present or not row.get('pending_reason'):continue
        deadline=row.get('pending_deadline')
        expired=deadline and (datetime.fromisoformat(deadline)<=now if 'T' in deadline else deadline<now.date().isoformat())
        if expired:
            row.pop('pending_reason',None);row.pop('pending_deadline',None)
            continue
        rows.append(dict(id=key,source=row['source'],reason=row['pending_reason'],
                         first_seen_at=row.get('first_seen_at'),last_seen_at=row.get('last_seen_at'),deadline=deadline))
    rows.sort(key=lambda x:(x['deadline'] or '9999',x['first_seen_at'] or '',x['id']))
    return rows


def check_bodies(state,items,sources,now,limit):
    """Detect text changes only; a successful fetch never renews verification."""
    from html.parser import HTMLParser
    from urllib.parse import urlsplit
    from urllib.error import HTTPError
    from .collectors import rss
    from .robots import allowed
    from . import cost_policy
    class Text(HTMLParser):
        def __init__(self):
            super().__init__();self.skip=0;self.parts=[]
        def handle_starttag(self,tag,attrs):
            if tag in ('script','style','nav','footer','header'): self.skip+=1
        def handle_endtag(self,tag):
            if tag in ('script','style','nav','footer','header'): self.skip=max(0,self.skip-1)
        def handle_data(self,text):
            if not self.skip:self.parts.append(text)
    errors=[]
    if not limit:return errors
    records=state.setdefault('items',{})
    active=[i for i in items if not i.excluded_reason and not i.needs_recheck
            and (not i.valid_until or i.valid_until>=now.date().isoformat())
            and (not i.deadline_at or datetime.fromisoformat(i.deadline_at)>now)]
    ordered=sorted(active,key=lambda i:(records.get(i.id,{}).get('body_attempted_at',''),i.deadline_at or i.valid_until or '9999',i.id))
    for item in ordered[:min(limit,10)]:
        if cost_policy.budget.limit-cost_policy.budget.used<4:break
        row=records.setdefault(item.id,dict(source=item.source,first_seen_at=now.isoformat()))
        row['body_attempted_at']=now.isoformat()
        try:
            source=sources[item.source]
            target=item.payment_terms.get('evidence_url',item.url)
            target_hash=digest(target)
            if row.get('body_target_hash')!=target_hash and (row.get('body_target_hash') or target!=item.url):
                row.pop('body_hash',None)
            row['body_target_hash']=target_hash
            u=urlsplit(target)
            try:robot=rss.fetch(f'{u.scheme}://{u.netloc}/robots.txt',source['domains']).decode('utf-8')
            except HTTPError as e:
                if e.code!=404:raise
                robot=''
            if not allowed(robot,target,rss.AGENT):raise ValueError('robots_denied')
            parser=Text();parser.feed(rss.fetch(target,source['domains']).decode('utf-8'))
            content=' '.join(' '.join(parser.parts).split())
            if len(content)<80:raise ValueError('insufficient_text')
            hashed=digest(content)
            if row.get('body_hash') and row['body_hash']!=hashed:
                row.update(hold_at=now.isoformat(),hold_reason='body_changed')
            row.update(body_hash=hashed,body_checked_at=now.isoformat(),body_status='checked')
        except Exception as error:
            row['body_status']='failed'
            errors.append(dict(source=item.source,item_id=item.id,**error_info(error)))
    return errors


def classify_history(report,state):
    import json
    records=state.setdefault('items',{})
    for group in ('new','changed','still_valid'):
        entries=report[group][:]
        for data in entries:
            item=Benefit(**data);row=records.setdefault(item.id,dict(source=item.source))
            hashed=digest(json.dumps(item.content(),sort_keys=True,ensure_ascii=False))
            previous=row.get('approved_hash')
            if group=='new' and previous:
                report[group].remove(data)
                report['still_valid' if previous==hashed else 'changed'].append(data)
    for group in ('new','changed','still_valid','upcoming'):
        for data in report[group]:
            item=Benefit(**data)
            records.setdefault(item.id,dict(source=item.source))['approved_hash']=digest(json.dumps(item.content(),sort_keys=True,ensure_ascii=False))


def sanitize(state,source_ids,now):
    """Project onto a bounded metadata-only schema; never serialize raw input."""
    import re
    if not state:return dict(schema_version=1,items={},sources={})
    if state.get('schema_version')!=1 or not isinstance(state.get('items'),dict) or len(state['items'])>5000:
        raise ValueError('Invalid operational state')
    clean=dict(schema_version=1,items={},sources={})
    for key,row in state['items'].items():
        if not re.fullmatch('[0-9a-f]{24}',key) or not isinstance(row,dict):raise ValueError('Invalid item state')
        if row.get('source') not in source_ids:continue
        out=dict(source=row['source'])
        for field in ('title_hash','body_hash','approved_hash','body_target_hash'):
            if field in row:
                if not isinstance(row[field],str) or not re.fullmatch('[0-9a-f]{64}',row[field]):raise ValueError('Invalid hash')
                out[field]=row[field]
        for field in ('first_seen_at','last_seen_at','body_attempted_at','body_checked_at','hold_at'):
            if row.get(field):
                date=datetime.fromisoformat(row[field])
                if date.tzinfo is None or date>now:raise ValueError('Invalid observation time')
                out[field]=date.isoformat()
        if row.get('hold_reason') in ('title_changed','body_changed'):out['hold_reason']=row['hold_reason']
        if row.get('body_status') in ('checked','failed'):out['body_status']=row['body_status']
        if row.get('pending_reason') in ('title_changed','body_changed','verification_expired','manual_review'):
            out['pending_reason']=row['pending_reason']
            if row.get('pending_deadline'):
                value=row['pending_deadline']
                parsed=datetime.fromisoformat(value)
                if 'T' in value and parsed.tzinfo is None:raise ValueError('Invalid pending deadline')
                out['pending_deadline']=value

        if bool(out.get('hold_at')) != bool(out.get('hold_reason')):raise ValueError('Incomplete review hold')
        last=out.get('last_seen_at') or out.get('first_seen_at')
        if last and now-datetime.fromisoformat(last)>timedelta(days=90) and not out.get('hold_at'):continue
        clean['items'][key]=out
    for key,row in state.get('sources',{}).items():
        if key not in source_ids:continue
        count=row.get('consecutive_failures',0)
        if type(count) is not int or not 0<=count<=100000:raise ValueError('Invalid failure count')
        out=dict(consecutive_failures=count)
        for field in ('last_attempt_at','last_success_at'):
            if row.get(field):
                stamp=datetime.fromisoformat(row[field])
                if stamp.tzinfo is None or stamp>now:raise ValueError('Invalid health time')
                out[field]=stamp.isoformat()
        category=row.get('error_category','')
        if category in ('dns','tls','timeout','connection','robots_denied','request_budget','parse_or_empty','other') or re.fullmatch('http_[1-5][0-9]{2}',category):
            out['error_category']=category
        clean['sources'][key]=out
    return clean


def error_info(error):
    import socket
    import ssl
    from urllib.error import HTTPError,URLError
    kind=type(error).__name__
    if isinstance(error,HTTPError):category='http_'+str(error.code)
    elif isinstance(error,URLError):return error_info(error.reason) | {'error_type':kind}
    elif isinstance(error,ssl.SSLError):category='tls'
    elif isinstance(error,socket.gaierror):category='dns'
    elif isinstance(error,TimeoutError):category='timeout'
    elif isinstance(error,ConnectionError):category='connection'
    elif 'robots' in str(error).lower():category='robots_denied'
    elif 'budget' in str(error).lower():category='request_budget'
    elif isinstance(error,(ValueError,UnicodeError)):category='parse_or_empty'
    else:category='other'
    return dict(category=category,error_type=kind)


def health(state,successes,failures,now):
    records=state.setdefault('sources',{})
    for source in successes:
        records[source]=dict(last_attempt_at=now.isoformat(),last_success_at=now.isoformat(),consecutive_failures=0)
    for failure in failures:
        if failure.get('district') or failure['source'] in successes:continue
        row=records.setdefault(failure['source'],{})
        row.update(last_attempt_at=now.isoformat(),
                   consecutive_failures=row.get('consecutive_failures',0)+1,
                   error_category=failure.get('category','other'))
