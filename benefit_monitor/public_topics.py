"""Topic inputs from the existing publication gate; never promotes AI facts."""
from copy import deepcopy
import hashlib
import json
import re

from .daily_topics import snapshot, TITLES
from .models import Benefit
from .official_reader import project_path
from .publish import payload
from .store import load


CATEGORY_TOPICS={'문화·체험':['culture'],'교육·강좌':['learning'],'할인·적립':['shopping']}
# Host-owned keyword rules (approved 2026-11-07). They only add candidate topics to
# already public-approved facts; the model still picks which cards to show.
KEYWORD_TEXT_TOPICS=(
    ('night',r'야간|저녁|야장|의 밤'),
    ('outdoors',r'걷기|둘레길|나들이|소풍|한강|공원|러너|산책|등산'),
    ('vouchers',r'상품권'),
    ('carrier',r'KT|T멤버십|SKT|LG ?U\+|통신사'),
    ('family',r'가족|어린이|자녀|육아|키즈|임산부|예비맘'),
    ('career',r'채용|면접|취업|구직|일자리|사무지원'),
    ('housing',r'입주자|사회주택|임대주택 공급|전세|월세'),
)
AGE_PATTERN=r'어르신|시니어|노인|65세|청년|19~39세'
CONVENIENCE_SOURCES=frozenset({'convenience','cu_events','emart24','emart24_events','gs25','seven','seven_events'})


def keyword_topics(row):
    """Extra topic IDs and title facets from fixed host rules over public fields only."""
    text=' '.join(str(row.get(k) or '') for k in ('title','summary'))
    audience=str((row.get('labels') or {}).get('audience') or '')
    topics=[topic for topic,pattern in KEYWORD_TEXT_TOPICS if re.search(pattern,text)]
    if re.search(AGE_PATTERN,text+' '+audience):topics.append('age')
    if row.get('source') in CONVENIENCE_SOURCES:topics.append('convenience')
    return topics,(['family'] if 'family' in topics else [])


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
    keyword_policy=basis.get('keyword_policy',{})
    if not isinstance(keyword_policy,dict):raise ValueError('invalid keyword policy')
    keywords=keyword_policy.get('approved') is True
    by_id={row['item_id']:row for row in basis['items']}
    if len(by_id)!=len(basis['items']):raise ValueError('duplicate topic basis')
    items,claims,excluded=[],[],[]
    for row in data['items']:
        item_id=Benefit(source=row['source'],url=row['url'],title=row['title'],summary=row['summary']).id
        digest=content_hash(row)
        entry=by_id.get(item_id,{})
        category=row.get('labels',{}).get('category')
        if item_id not in by_id:
            topic_ids=list(mapping.get(category,[]));facets=[]
            if keywords:
                extra,facets=keyword_topics(row)
                topic_ids+=[t for t in extra if t not in topic_ids]
            if topic_ids:
                entry={'approved':True,'content_sha256':digest,'topic_ids':topic_ids,'title_facets':facets}
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
