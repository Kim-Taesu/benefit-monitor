"""Prepare evaluation-only daily snapshots; no scheduling or publication."""
from copy import deepcopy
from datetime import date, datetime
import hashlib
import json
from zoneinfo import ZoneInfo

TITLES = {'local':'지역별 혜택','carrier':'통신사·멤버십','age':'연령별 혜택',
          'night':'저녁에 이용하기','culture':'문화·체험','learning':'배움·강좌',
          'shopping':'장보기·멤버십','vouchers':'상품권 혜택','convenience':'편의점 혜택',
          'outdoors':'야외 활동','family':'가족과 함께','housing':'주거 지원','career':'취업·진로'}


def snapshot(items, claims, now, review_id, previous):
    if now.tzinfo is None or len({i['item_id'] for i in items}) != len(items):
        raise ValueError('timezone and unique item IDs required')
    if len({c['id'] for c in claims}) != len(claims):
        raise ValueError('unique claim IDs required')
    today = now.astimezone(ZoneInfo('Asia/Seoul')).date()
    visible, excluded = [], []
    for original in items:
        item = deepcopy(original)
        expired = bool(item.get('valid_until') and date.fromisoformat(item['valid_until']) < today)
        if item.get('deadline_at'):
            deadline = datetime.fromisoformat(item['deadline_at'])
            if deadline.tzinfo is None:
                raise ValueError('deadline requires timezone')
            expired |= deadline <= now
        if item.get('valid_from'):
            expired |= date.fromisoformat(item['valid_from']) > today
        if item['display_eligible'] is not True or expired:
            excluded.append({'item_id':item['item_id'],'reason':'closed_or_expired'})
        else:
            visible.append(item)
    ids = {x['item_id'] for x in visible}
    used_claims = [deepcopy(c) for c in claims if c['item_id'] in ids]
    signature = hashlib.sha256(json.dumps({'now':now.isoformat(),'items':visible,'claims':used_claims},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return dict(schema_version='topic-input-v1',mode='api_agent',synthetic=False,evaluation_only=True,
                source_review_id=review_id,gate_owner='user-reviewed-development-replay',
                gate_description='개발 평가용 승인 사실의 날짜별 재생. 실제 공개 승인 또는 미래 조회 성공 아님.',
                now=now.isoformat(),snapshot_id=signature,approved_items=visible,approved_claims=used_claims,
                excluded_items=excluded,allowed_topic_ids=list(TITLES),previous_topics=deepcopy(previous))


def fallback(previous, host):
    """Keep valid references with date-independent rule titles after model failure."""
    from .topic_semantics import review

    ids = {x['item_id'] for x in host['approved_items']}
    eligible_claims = {x['item_id']:set(x['claim_ids']) for x in host['approved_items']}
    cards = []
    for original in previous:
        if original['topic_id'] not in TITLES:
            continue
        card = deepcopy(original)
        card['item_links'] = [x for x in card['item_links'] if x['item_id'] in ids and x['evidence_claim_ids']
                              and set(x['evidence_claim_ids']) <= eligible_claims[x['item_id']]]
        if card['item_links']:
            card.update(title=TITLES[card['topic_id']],snapshot_id=host['snapshot_id'],excluded_items=[])
            card['item_links'] = [link for link in card['item_links']
                                  if review({'topics':[dict(card,item_links=[link])]},host)['valid']]
            if card['item_links']:
                cards.append(card)
    return cards


def basis_cards(host):
    """Deterministic cards from each item's first reviewed topic basis, used only when no model
    or previous cards survive, so the public page never loses topics because a draft was rejected."""
    from .topic_semantics import review

    cards = []
    for topic in TITLES:
        links = []
        for item in host['approved_items']:
            basis = item.get('topic_basis') or {}
            if item.get('display_eligible') is not True or (basis.get('topic_ids') or [None])[0] != topic:
                continue
            link = {'item_id': item['item_id'], 'evidence_claim_ids': list(basis.get('evidence_claim_ids', [])),
                    'reason': '검토된 주제 근거에 따른 기본 분류', 'match_type': 'explicit'}
            card = {'schema_version': 'topic-draft-v1', 'topic_id': topic, 'title': TITLES[topic], 'item_links': [link],
                    'profile_conditions': [], 'excluded_items': [], 'snapshot_id': host['snapshot_id'], 'audit': None}
            if review({'topics': [card]}, host)['valid']:
                links.append(link)
        if links:
            cards.append({'schema_version': 'topic-draft-v1', 'topic_id': topic, 'title': TITLES[topic], 'item_links': links,
                          'profile_conditions': [], 'excluded_items': [], 'snapshot_id': host['snapshot_id'], 'audit': None})
    return cards
