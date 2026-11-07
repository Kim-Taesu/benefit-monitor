"""Pick related official pages so research can cross-check facts across documents."""
from .validation import official


def allowed_domains(sources):
    return {d for s in sources.values() for d in s.get('domains', [])}


def _grams(text):
    t=''.join(str(text).split())
    return {t[i:i+2] for i in range(len(t)-1)} if len(t)>1 else ({t} if t else set())


def similarity(a,b):
    x,y=_grams(a),_grams(b)
    # Overlap coefficient: Jaccard (0.3) rejects the brief's own adopted example; titles differ in length.
    return len(x&y)/min(len(x),len(y)) if x and y else 0.0


def related_urls(doc,candidate,peers,domains,limit=3):
    own=candidate.get('url')
    found=[]
    def add(url):
        if url and url!=own and url not in found:found.append(url)
    for url in doc.get('links') or []:
        if official(url,domains):add(url)
    scored=[(similarity(candidate.get('title',''),p.get('title','')),i,p) for i,p in enumerate(peers)
            if p.get('source')==candidate.get('source') and official(p.get('url',''),domains)]
    for score,_,p in sorted(scored,key=lambda t:(-t[0],t[1])):
        if score>=0.5:add(p['url'])
    return found[:limit]
