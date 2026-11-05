"""Limited restriction-cue coverage checks; no truth or publication approval."""
import re
import unicodedata

REQUIRED_FIELDS = ('eligibility','event_period','application_period','fee_status','cost_details',
                   'payment_conditions','selection','capacity','application_method','cancellation',
                   'restrictions','availability')
FIELDS = REQUIRED_FIELDS + ('summary','conditions','districts')
RESTRICTION = re.compile(
    r'(?:유아|어린이|아동|성인|청년|가족|주민|회원)[^.!?\n]{0,16}?(?:동반(?:\s*가족)?|대상|한정|전용)'
    r'|대상\s*(?:유아|어린이|아동|성인|청년|가족|주민|회원)'
    r'|(?:만\s*)?\d{1,2}\s*[~～–-]\s*\d{1,2}\s*세')
CALENDAR_QUALIFIER = re.compile(r'주말[·\s]*공휴일\s*제외|센터\s*운영일\s*\(평일\)\s*기준')


def _compact(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text))


def audit(draft, host):
    """Require explicit fields and preserve detected restriction cues.

    This bounded vocabulary can miss other restrictions and can conservatively
    flag irrelevant mentions. A pass still requires human semantic review.
    """
    candidates={c['candidate_id']:c for c in host['candidates']}
    docs={d['id']:d for d in host['documents']}
    findings=[]
    reviewed={r['candidate_id'] for r in draft['records']}
    for cid in sorted(set(candidates)-reviewed):
        findings.append({'candidate_id':cid,'code':'unreviewed_candidate'})
    for record in draft['records']:
        cid=record['candidate_id']
        facts=record['facts']
        names=[f['field'] for f in facts]
        for name in sorted(set(names)-set(FIELDS)):
            findings.append({'candidate_id':cid,'code':'noncanonical_field','field':name})
        for name in REQUIRED_FIELDS:
            if name not in names:
                findings.append({'candidate_id':cid,'code':'missing_required_field','field':name})
        for name in set(names):
            if names.count(name)>1:
                findings.append({'candidate_id':cid,'code':'duplicate_field','field':name})
        eligibility=next((f for f in facts if f['field']=='eligibility'),{})
        value=eligibility.get('value')
        scope=value.get('scope') if isinstance(value,dict) else None
        preserved=' '.join(value.get('required',[])) if isinstance(value,dict) else ''
        # Unknown/not_confirmed is not a preserved confirmed restriction.
        relevant=[f for f in facts if f['field'] in ('eligibility','restrictions') and f['status'] in ('supported','disputed')]
        preserved+=' '+' '.join(f['value'] for f in relevant if f['field']=='restrictions' and isinstance(f['value'],str))
        for did in candidates[cid]['document_ids']:
            doc=docs[did]
            if doc['fetch_status']!='ok':
                findings.append({'candidate_id':cid,'code':'unavailable_document','source_ref':did})
                continue
            cancellation=next((f for f in facts if f['field']=='cancellation'),{})
            for match in CALENDAR_QUALIFIER.finditer(doc['body']):
                cue=match.group()
                value=cancellation.get('value')
                quoted=any(e['source_ref']==did and e['quote'] in doc['body'] and cue in e['quote']
                           for e in cancellation.get('evidence',[]))
                if not isinstance(value,str) or _compact(cue) not in _compact(value) or not quoted:
                    findings.append({'candidate_id':cid,'code':'qualifier_not_preserved','field':'cancellation',
                                     'source_ref':did,'cue':cue,'start':match.start(),'end':match.end()})
            for match in RESTRICTION.finditer(doc['body']):
                cue=match.group()
                common={'candidate_id':cid,'source_ref':did,'cue':cue,'start':match.start(),'end':match.end()}
                if scope=='unrestricted':
                    findings.append(dict(common,code='unrestricted_with_restriction'))
                quoted=any(e['source_ref']==did and e['quote'] in doc['body'] and cue in e['quote']
                           for fact in relevant for e in fact['evidence'])
                if not quoted:
                    findings.append(dict(common,code='restriction_not_quoted'))
                core=re.sub(r'(대상|한정|전용)$','',re.sub(r'^대상\s*','',cue))
                if _compact(core) not in _compact(preserved):
                    findings.append(dict(common,code='restriction_not_preserved'))
    return {'valid':not findings,'findings':findings,'policy':'restriction-cue-coverage-v2',
            'publication_approved':False,'human_semantic_review':'required'}
