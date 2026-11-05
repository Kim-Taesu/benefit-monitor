"""Publish only hash-approved topic drafts; recheck current facts and fallback."""
from copy import deepcopy
import hashlib
from datetime import datetime
from pathlib import Path

from .ai_contract import validate
from .daily_topics import fallback
from .official_reader import project_path
from .public_topics import approved_snapshot,content_hash
from .store import load,save
from .topic_semantics import review


def policy_hash(root):
    package=Path(__file__).resolve().parent
    names=('topic_semantics.py','topic_publication.py','public_topics.py','daily_topics.py','ai_contract.py','publish.py','public_snapshot.py')
    parts=[(package/name).read_bytes() for name in names]
    parts.append((package.parent/'frontend/src/topic-titles.json').read_bytes())
    parts.append(project_path(root,'public/topic-basis.json').read_bytes())
    return hashlib.sha256(b'\n'.join(parts)).hexdigest()


def cards(root,now):
    root=Path(root).resolve()
    try:approval=load(project_path(root,'public/topic-publication.json'),{})
    except (OSError,ValueError):return None
    if not isinstance(approval,dict) or approval.get('approved') is not True:return None
    try:
        expires=datetime.fromisoformat(approval['expires_at'])
        if expires.tzinfo is None or now>=expires:return None
        standing=approval.get('mode')=='reviewed_policy'
        if standing and approval.get('policy_sha256')!=policy_hash(root):return None
        draft=load(project_path(root,'cache/ai_topics/draft.json'),None)
        cached=False
        if draft is None or (not standing and content_hash(draft)!=approval.get('draft_sha256')):
            draft=load(project_path(root,'cache/ai_topics/last_published.json'),None)
            cached=True
        if draft is None or (not standing and content_hash(draft)!=approval.get('draft_sha256')):return None
        generated=datetime.fromisoformat(draft['generated_at'])
        if generated.tzinfo is None or generated>now:return None
        host=approved_snapshot(root,now,[])
        valid_cards=fallback(draft['topics'],host)
        # Fallback only removes links/relative titles; it cannot approve new facts.
        result={'schema_version':'trial-result-v1','mode':'api_agent','status':'completed',
                'errors':[],'topics':valid_cards,'excluded_items':[]}
        if not validate(result,host,'topic')['valid'] or not review(result,host)['valid']:return None
        facts={c['item_id']:c['value'] for c in host['approved_claims']}
        public=[]
        for topic in valid_cards:
            public.append({'id':topic['topic_id'],'title':topic['title'],
                           'items':[{'source':facts[l['item_id']]['source'],'url':facts[l['item_id']]['url'],
                                     'facts':deepcopy(facts[l['item_id']])} for l in topic['item_links']]})
        if not cached:
            save(project_path(root,'cache/ai_topics/last_published.json'),draft)
        return {'schema_version':1,'generated_at':draft['generated_at'],'valid_until':expires.isoformat(),
                'used_fallback':cached or draft['used_fallback'],'topics':public}
    except (OSError,ValueError,KeyError,TypeError):
        return None


def from_bundle(root,bundle,public_data,now):
    """Recheck a public-only bundle in a clean deployment checkout, without keys."""
    try:
        approval=load(project_path(root,'public/topic-publication.json'),{})
        if (not isinstance(approval,dict) or approval.get('approved') is not True
                or approval.get('mode')!='reviewed_policy'
                or approval.get('policy_sha256')!=policy_hash(root)):
            return None
        expires=datetime.fromisoformat(approval['expires_at'])
        if expires.tzinfo is None or now>=expires:return None
        if not isinstance(bundle,dict) or set(bundle)!={'schema_version','generated_at','valid_until','used_fallback','topics'}:
            return None
        generated=datetime.fromisoformat(bundle['generated_at']);until=datetime.fromisoformat(bundle['valid_until'])
        if (bundle['schema_version']!=1 or type(bundle['used_fallback'])is not bool or generated.tzinfo is None
                or until.tzinfo is None or generated>now or not now<until<=expires
                or not isinstance(bundle['topics'],list) or len(bundle['topics'])>13):
            return None
        host=approved_snapshot(root,now,[],public_data=public_data)
        facts={(c['value']['source'],c['value']['url']):(c['item_id'],c['id'],c['value']) for c in host['approved_claims']}
        internal=[];exported=[]
        for topic in bundle['topics']:
            if not isinstance(topic,dict) or set(topic)!={'id','title','items'} or not isinstance(topic['items'],list):return None
            links=[];references=[]
            for ref in topic['items']:
                if not isinstance(ref,dict) or set(ref)!={'source','url','facts'}:return None
                current=facts.get((ref['source'],ref['url']))
                if current is None:continue
                item_id,claim_id,value=current
                if ref['facts']!=value:return None
                links.append({'item_id':item_id,'evidence_claim_ids':[claim_id],'reason':'승인된 공개 사실과 편집 근거 대조','match_type':'explicit'})
                references.append(deepcopy(ref))
            if not links:continue
            internal.append({'schema_version':'topic-draft-v1','topic_id':topic['id'],'title':topic['title'],
                             'item_links':links,'profile_conditions':[],'excluded_items':[],
                             'snapshot_id':host['snapshot_id'],'audit':None})
            exported.append({'id':topic['id'],'title':topic['title'],'items':references})
        result={'schema_version':'trial-result-v1','mode':'api_agent','status':'completed','errors':[],
                'topics':internal,'excluded_items':[]}
        if not validate(result,host,'topic')['valid'] or not review(result,host)['valid']:return None
        return {'schema_version':1,'generated_at':bundle['generated_at'],'valid_until':bundle['valid_until'],
                'used_fallback':bundle['used_fallback'],'topics':exported}
    except (OSError,ValueError,KeyError,TypeError):
        return None
