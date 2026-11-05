"""Topic inputs from the existing publication gate; never promotes AI facts."""
from copy import deepcopy
import hashlib
import json

from .daily_topics import snapshot, TITLES
from .models import Benefit
from .official_reader import project_path
from .publish import payload
from .store import load


CATEGORY_TOPICS={'문화·체험':['culture'],'교육·강좌':['learning'],'할인·적립':['shopping']}


def content_hash(item):
    return hashlib.sha256(json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def approved_snapshot(root,now,previous,public_data=None):
    data=payload(root,now=now) if public_data is None else public_data
    basis=load(project_path(root,'public/topic-basis.json'),{'schema_version':1,'items':[]})
    if not isinstance(basis,dict) or basis.get('schema_version')!=1 or not isinstance(basis.get('items'),list):
        raise ValueError('invalid reviewed topic basis')
    if any(not isinstance(row,dict) or not isinstance(row.get('item_id'),str) for row in basis['items']):
        raise ValueError('invalid topic basis entry')
    category_policy=basis.get('category_policy',{})
    if not isinstance(category_policy,dict):raise ValueError('invalid category policy')
    mapping=category_policy.get('mapping',{}) if category_policy.get('approved') is True else {}
    if not isinstance(mapping,dict) or any(k not in CATEGORY_TOPICS or v!=CATEGORY_TOPICS[k] for k,v in mapping.items()):
        raise ValueError('unsupported category to topic mapping')
    by_id={row['item_id']:row for row in basis['items']}
    if len(by_id)!=len(basis['items']):raise ValueError('duplicate topic basis')
    items,claims,excluded=[],[],[]
    for row in data['items']:
        item_id=Benefit(source=row['source'],url=row['url'],title=row['title'],summary=row['summary']).id
        digest=content_hash(row)
        entry=by_id.get(item_id,{})
        category=row.get('labels',{}).get('category')
        if item_id not in by_id and category in mapping:
            entry={'approved':True,'content_sha256':digest,'topic_ids':deepcopy(mapping[category]),'title_facets':[]}
        if entry.get('approved') is not True or entry.get('content_sha256')!=digest:
            excluded.append({'item_id':item_id,'reason':'topic_basis_missing_or_changed'})
            continue
        claim_id='public-'+digest[:24]
        items.append(dict(item_id=item_id,summary=row['summary'],conditions=row['conditions'],claim_ids=[claim_id],
                          display_eligible=True,valid_from=row['valid_from'],valid_until=row['valid_until'],deadline_at=row['deadline_at'],
                          topic_basis={'topic_ids':deepcopy(entry['topic_ids']),'title_facets':deepcopy(entry['title_facets']),
                                       'evidence_claim_ids':[claim_id]}))
        claims.append({'id':claim_id,'item_id':item_id,'field':'public_release_facts','value':deepcopy(row)})
    review_id='public-release:'+content_hash({'items':items,'claims':claims})
    host=snapshot(items,claims,now,review_id,previous)
    host.update(evaluation_only=False,gate_owner='existing-public-release-gate',
                gate_description='기존 공개 승인·검증·기한 게이트와 내용 해시에 묶인 주제 편집 승인을 적용. AI 조사 초안은 포함하지 않음.')
    host['excluded_items'].extend(excluded)
    host['allowed_topic_titles']=dict(TITLES)
    return host
