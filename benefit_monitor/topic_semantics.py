"""Conservative host-authored topic/title gate; never grants publication."""
import re

from .daily_topics import TITLES

FACETS = {'family':r'가족|어린이|아이|자녀', 'weekend':r'주말', 'free':r'무료|공짜|0원'}


def review(result, host):
    """Topic basis is host editorial input, never inferred from model reasons.

    Missing basis or an unrecognized title requires review. Passing this limited
    check does not prove semantic truth or replace human approval.
    """
    items = {i['item_id']:i for i in host['approved_items']}
    claims = {c['id']:c for c in host['approved_claims']}
    findings = []
    for card in result['topics']:
        topic, title = card['topic_id'], card['title']
        if card.get('profile_conditions'):
            findings.append({'code':'profile_conditions_require_review','topic_id':topic})
        if title not in TITLES.values() and not re.fullmatch(r'(주말 )?(가족 )?(무료 )?문화 체험', title):
            findings.append({'code':'unreviewed_title','topic_id':topic})
        if re.search(r'이번|오늘|내일|모레', title):
            findings.append({'code':'relative_title_requires_review','topic_id':topic})
        facets = {name for name, pattern in FACETS.items() if re.search(pattern,title)}
        if not card['item_links']:
            findings.append({'code':'empty_topic','topic_id':topic})
        for link in card['item_links']:
            item_id = link['item_id']
            item = items.get(item_id,{})
            basis = item.get('topic_basis')
            common = {'topic_id':topic,'item_id':item_id}
            refs_in_link = link.get('evidence_claim_ids',[])
            if (not item.get('display_eligible') or not refs_in_link
                    or any(not isinstance(c,str) or c not in item.get('claim_ids',[]) or c not in claims
                           or claims[c]['item_id'] != item_id for c in refs_in_link)):
                findings.append(dict(common,code='invalid_link_claim'))
                continue
            if not isinstance(basis,dict):
                findings.append(dict(common,code='missing_topic_basis'))
                continue
            refs = basis.get('evidence_claim_ids')
            if (set(basis) != {'topic_ids','title_facets','evidence_claim_ids'}
                    or not isinstance(refs,list) or not refs
                    or not isinstance(basis.get('topic_ids'),list) or not isinstance(basis.get('title_facets'),list)
                    or any(not isinstance(x,str) or x not in TITLES for x in basis['topic_ids'])
                    or any(not isinstance(x,str) or x not in FACETS for x in basis['title_facets'])
                    or any(not isinstance(c,str) or c not in item.get('claim_ids',[]) or c not in claims or claims[c]['item_id'] != item_id for c in refs)
                    or not set(refs) <= set(link['evidence_claim_ids'])):
                findings.append(dict(common,code='invalid_topic_basis'))
                continue
            if topic not in basis['topic_ids']:
                findings.append(dict(common,code='unsupported_topic'))
            for facet in sorted(facets - set(basis['title_facets'])):
                findings.append(dict(common,code='unsupported_title_facet',facet=facet))
    return {'valid':not findings,'findings':findings,'publication_approved':False,
            'human_semantic_review':'required','policy':'host-topic-basis-v2'}


def require_basis(host):
    """Reject missing host editorial input before any paid topic request."""
    probe={'topics':[{'topic_id':'culture','title':'문화·체험',
                     'item_links':[{'item_id':item['item_id'],'evidence_claim_ids':item.get('claim_ids',[])}
                                   for item in host['approved_items']]}]}
    findings=review(probe,host)['findings']
    if any(f['code'] in ('missing_topic_basis','invalid_topic_basis','invalid_link_claim') for f in findings):
        raise ValueError('valid host topic basis required before API request')
