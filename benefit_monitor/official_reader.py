"""Official bodies for AI review, sharing the existing public HTTP budget."""
from datetime import date, timedelta
import hashlib
import json
import re
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from html.parser import HTMLParser
from urllib.parse import quote, urljoin, urlsplit, urldefrag
from urllib.request import Request, build_opener

from . import cost_policy
from .collectors.body import extract_body, stable_text
from .collectors.rss import AGENT, LIMIT
from .research_probe import NoRedirect
from .robots import allowed, crawl_delay
from .store import load, save
from . import observability as obs
from .validation import official


HOST_FAILURES_BEFORE_COOLDOWN=3


def transient(error):
    """Network-level or server-side failures that say nothing about the page itself."""
    if isinstance(error,HTTPError):return error.code==429 or error.code>=500
    return isinstance(error,(URLError,TimeoutError,ConnectionError))


def request_url(url):
    """Percent-encode non-ASCII characters (e.g. Korean query values) without touching escapes."""
    return quote(url,safe=":/?#[]@!$&'()*+,;=%~")


def project_path(root, relative):
    root=Path(root).resolve()
    path=(root/relative).resolve()
    if not root.is_relative_to(Path(__file__).resolve().parents[1]) or not path.is_relative_to(root):
        raise ValueError('path outside permitted project')
    return path


def network_open(request):
    return build_opener(NoRedirect()).open(request,timeout=15)


_VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
_CHROME={'header','nav','footer','aside'}


class _Anchors(HTMLParser):
    """Collect links from the content region only; site chrome is ignored."""
    def __init__(self):
        super().__init__();self.stack=[];self.items=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':
            href=dict(attrs).get('href')
            if href:
                names=[t for t in self.stack]
                if not _CHROME&set(names):self.items.append((href,'main' in names,'article' in names))
        if tag not in _VOID:self.stack.append(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i]==tag:del self.stack[i:];break
    @property
    def hrefs(self):
        for idx in (1,2):
            scoped=[i[0] for i in self.items if i[idx]]
            if scoped:return scoped
        return [i[0] for i in self.items]


# Page header posting dates that code (not the model) reads; checked 2026-11-09 on live pages.
PAGE_DATES={'mediahub.seoul.go.kr':re.compile(r'<p class="date">\s*발행일\s*<span class="num">\s*(\d{4})\.(\d{1,2})\.(\d{1,2})\.')}


def page_published(html,url):
    """ISO date of the official page header posting date, or None for other hosts or unreadable dates."""
    pattern=PAGE_DATES.get(urlsplit(url).hostname or '')
    found=pattern.search(html) if pattern else None
    if not found:return None
    try:return date(*map(int,found.groups())).isoformat()
    except ValueError:return None


def extract_links(html,base,limit=50):
    parser=_Anchors()
    try:parser.feed(html)
    except Exception:pass
    out=[]
    for href in parser.hrefs:
        url=urldefrag(urljoin(base,href.strip()))[0]
        parts=urlsplit(url)
        if parts.scheme not in ('http','https') or parts.path in ('','/'):continue
        if url not in out:out.append(url)
        if len(out)>=limit:break
    return out


class OfficialReader:
    def __init__(self,root,now):
        if now.tzinfo is None:raise ValueError('timezone required')
        self.root,self.now=Path(root).resolve(),now
        self.request_budget=None
        config=load(project_path(root,'sources.yaml'),None)
        cost_policy.require_free(config)
        self.sources={s['id']:s for s in config['sources']}
        self.path=project_path(root,'cache/ai_review/http.json')
        self.state=load(self.path,{'hosts':{},'pages':{}})

    def _fetch(self,url,domains,host_state):
        """One retry for transient network errors; page-level errors are not retried."""
        for attempt in (0,1):
            try:
                return self._fetch_once(url,domains,host_state)
            except Exception as error:
                if attempt or not transient(error):raise

    def _fetch_once(self,url,domains,host_state):
        if not official(url,domains):raise ValueError('unapproved official URL')
        delay=crawl_delay(host_state.get('robots',''),AGENT)
        remaining=delay-(time.time()-host_state.get('last_request_epoch',0))
        if remaining>15:raise ValueError('crawl-delay requires deferred fetch')
        if remaining>0:time.sleep(remaining)
        if self.request_budget is not None:self.request_budget.consume()
        cost_policy.budget.consume()
        host_state['last_request_epoch']=time.time()
        try:
            with network_open(Request(request_url(url),headers={'User-Agent':AGENT})) as response:
                body=response.read(LIMIT+1)
                content_type=response.headers.get('Content-Type','').lower()
            if len(body)>LIMIT:raise ValueError('response exceeds 2 MiB')
            return body,content_type
        except HTTPError as error:
            error.close()
            raise
        finally:
            save(self.path,self.state)

    @obs.timed('read','official_read')
    def read(self,candidate,cooldown_on_failure=True):
        source=self.sources[candidate['source']]
        url=candidate['url']
        if not official(url,source['domains']):raise ValueError('unapproved official URL')
        host=urlsplit(url).netloc
        hs=self.state['hosts'].setdefault(host,{})
        stamp=self.now.timestamp()
        if stamp<hs.get('failure_until',0):raise ValueError('source failure cooldown')
        key=hashlib.sha256(url.encode()).hexdigest()
        cached=self.state['pages'].get(key)
        if cached and 0<=stamp-cached['at']<21600:
            return load(project_path(self.root,cached['file']),None)
        try:
            if stamp>=hs.get('robots_until',0):
                try:
                    robot,_=self._fetch('https://'+host+'/robots.txt',source['domains'],hs)
                    robot=robot.decode('utf-8','strict')
                except HTTPError as error:
                    error.close()
                    if error.code!=404:raise
                    robot=''
                hs.update(robots=robot,robots_until=stamp+21600)
                save(self.path,self.state)
            if not allowed(hs['robots'],url,AGENT):raise ValueError('robots denies URL')
            raw,content_type=self._fetch(url,source['domains'],hs)
            if 'text/html' not in content_type:raise ValueError('unsupported body content type')
            html=raw.decode('utf-8','strict')
            text,mode=extract_body(html,url)
            # Visit counters are not page content: with them every reread looked like an edited page.
            text=stable_text(text)
            if len(text)<80:raise ValueError('insufficient official body')
            digest=hashlib.sha256(text.encode()).hexdigest()
            doc=dict(id='doc-'+digest[:24],requested_url=url,final_url=url,source_id=source['id'],
                     document_role='notice',publisher_type='unknown',retrieved_at=self.now.isoformat(),published_at=page_published(html,url),
                     body_hash=digest,hash_algorithm='sha256-utf8-exact',extraction_scope='collectors.body:'+mode,
                     fetch_status='ok',body=text,links=extract_links(html,url))
            relative='cache/ai_review/documents/'+key+'-'+digest+'.json'
            save(project_path(self.root,relative),doc)
            self.state['pages'][key]={'at':stamp,'file':relative}
            hs.pop('failure_until',None);hs.pop('transient_failures',None)
            save(self.path,self.state)
            return doc
        except Exception as error:
            # Only repeated host-level failures cool the whole host down; a single timeout or a
            # page-specific problem (404, short body, PDF) must not block other candidates.
            if cooldown_on_failure and transient(error):
                hs['transient_failures']=hs.get('transient_failures',0)+1
                if hs['transient_failures']>=HOST_FAILURES_BEFORE_COOLDOWN:hs['failure_until']=stamp+900
            save(self.path,self.state)
            raise
