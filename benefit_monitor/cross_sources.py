"""Pick related official pages so research can cross-check facts across documents."""
import re
from urllib.parse import urlsplit

from .validation import official

SKIP_EXT=('.pdf','.hwp','.hwpx','.zip','.xlsx','.xls','.docx','.doc','.pptx','.jpg','.jpeg','.png','.gif')


def allowed_domains(sources):
    return {d for s in sources.values() for d in s.get('domains', [])}


def _grams(text):
    t=''.join(str(text).split())
    return {t[i:i+2] for i in range(len(t)-1)} if len(t)>1 else ({t} if t else set())


def similarity(a,b):
    x,y=_grams(a),_grams(b)
    # Overlap coefficient: Jaccard (0.3) rejects the brief's own adopted example; titles differ in length.
    shared=len(x&y)
    return shared/min(len(x),len(y)) if shared>=2 else 0.0


def fetchable(url):
    path=urlsplit(url).path.lower()
    return not path.endswith(SKIP_EXT) and 'download' not in path and 'filedown' not in path and path not in ('','/')


# Approved 2026-11-19 (user "123 진행"): a site's home, login or copyright page names no benefit and was
# never cited as evidence, but its banners change daily, which sent unchanged items to paid research
# again (반려식물병원: yeyak.seoul.go.kr/web/main.do). Listing pages stay: they are cited.
HOME_PAGE=re.compile(r'(?:index|main|doMainView|subMain\d*)\.(?:do|jsp|html?|php|aspx?)',re.I)
SITE_PAGE=re.compile(r'login|copyright|User_Step_\d',re.I)
# An index.do that names one item in its query is that item's page (eshare UprResrcEdu/index.do?rsrc_no=).
ITEM_QUERY=re.compile(r'(?:^|&)(?:rsrc_no|rsv_svc_id|id|no|seq|nttNo|idx|course_id)=',re.I)


def navigation_page(url):
    """A home, login or copyright page: never a document about one benefit."""
    parts=urlsplit(url)
    last=parts.path.rsplit('/',1)[-1]
    if parts.path in ('','/') or SITE_PAGE.search(last):return True
    return bool(HOME_PAGE.fullmatch(last)) and not ITEM_QUERY.search(parts.query)


def related_urls(doc,candidate,peers,domains,limit=3):
    own=candidate.get('url')
    found=[]
    def add(url):
        if url and url!=own and url not in found and fetchable(url) and not navigation_page(url):found.append(url)
    for url in doc.get('links') or []:
        if official(url,domains):add(url)
    scored=[(similarity(candidate.get('title',''),p.get('title','')),i,p) for i,p in enumerate(peers)
            if p.get('source')==candidate.get('source') and official(p.get('url',''),domains)]
    for score,_,p in sorted(scored,key=lambda t:(-t[0],t[1])):
        if score>=0.5:add(p['url'])
    return found[:limit]
