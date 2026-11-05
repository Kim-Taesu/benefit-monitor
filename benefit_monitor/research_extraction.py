"""Assemble compact model facts into the unchanged evidence contract. No I/O."""
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path

from .ai_contract import check_schema, validate

SCHEMA = Path(__file__).resolve().parents[1]/'docs/ai/schemas/research-extraction.schema.json'


def assemble(draft, host):
    v3 = draft.get('schema_version') == 'research-extraction-v3'
    schema_path = SCHEMA.parent/'research-extraction-v3.schema.json' if v3 else SCHEMA
    errors = check_schema(draft, json.loads(schema_path.read_text()))
    if errors:
        raise ValueError('invalid extraction contract: ' + '; '.join(errors))
    candidates = {c['candidate_id']:c for c in host['candidates']}
    documents = {d['id']:d for d in host['documents']}
    source_schema = json.loads((SCHEMA.parent/'research-result.schema.json').read_text())['properties']['records']['items']['properties']['sources']['items']
    records, seen = [], set()
    for extracted in draft['records']:
        cid = extracted['candidate_id']
        if cid not in candidates or cid in seen:
            raise ValueError('unknown or duplicate candidate')
        seen.add(cid)
        candidate = candidates[cid]
        proposed = dict.fromkeys(('summary','conditions','valid_from','valid_until','deadline_at','published_at',
                                  'districts','labels','payment_terms','benefit_value'))
        proposed['fee_status'] = 'unknown'
        claims, questions, conflicts, supported = [], [], [], {}
        for index, fact in enumerate(extracted['facts']):
            status, field, value = fact['status'], fact['field'], fact['value']
            if status == 'unknown':
                if not fact['unknown_reason']:
                    raise ValueError('unknown requires reason')
                questions.append({'field':field,'question':field+' 확인 필요','importance':'critical','reason':fact['unknown_reason']})
            elif fact['unknown_reason'] is not None:
                raise ValueError('reason is only for unknown facts')
            if v3 and status != 'unknown':
                if value is None:
                    raise ValueError('supported/disputed fact requires non-null value')
                if field == 'eligibility':
                    if value['scope'] == 'unrestricted' and value['required']:
                        raise ValueError('unrestricted eligibility cannot have required restrictions')
                    if value['scope'] == 'disputed' and status != 'disputed':
                        raise ValueError('disputed eligibility requires disputed status')
                    if value['scope'] == 'restricted' and not value['required']:
                        raise ValueError('restricted eligibility requires explicit conditions')
                if field == 'application_period':
                    from .ai_contract import _timestamp
                    for key in ('start','end'):
                        if value[key] is not None:
                            _timestamp(value[key])
                    if value['start'] and value['end'] and _timestamp(value['start']) > _timestamp(value['end']):
                        raise ValueError('inverted application period')
                if field == 'fee_status' and value == 'unknown':
                    raise ValueError('unknown fee requires null value and unknown status')
                if field == 'event_period':
                    for key in ('start','end'):
                        if value[key] is not None and date.fromisoformat(value[key]).isoformat() != value[key]:
                            raise ValueError('event date requires canonical YYYY-MM-DD')
                if field == 'capacity' and value is not None and value < 0:
                    raise ValueError('invalid capacity')
                if field == 'availability':
                    raise ValueError('remaining inventory requires separate live verification')
            if status == 'supported':
                if field in supported and supported[field] != value:
                    raise ValueError('conflicting supported values require disputed facts')
                supported[field] = deepcopy(value)
                if field in ('event_date','valid_from','valid_until','published_at') and value is not None:
                    date.fromisoformat(value)
                if field == 'event_period' and isinstance(value, dict):
                    for key in ('start','end'):
                        if value.get(key) is not None:
                            date.fromisoformat(value[key])
                if field in proposed:
                    proposed[field] = deepcopy(value)
            signature = json.dumps({'candidate':cid,'index':index,'fact':fact},ensure_ascii=False,sort_keys=True)
            claim_id = 'claim-'+hashlib.sha256(signature.encode()).hexdigest()[:24]
            claims.append({'id':claim_id,'field':field,'value':deepcopy(value),'status':status,'evidence':deepcopy(fact['evidence'])})
            if status == 'disputed':
                conflicts.append({'field':field,'claim_ids':[claim_id],'description':'공식 근거 간 충돌: '+field,'resolution':None})
        sources = [{key:deepcopy(documents[sid][key]) for key in source_schema['properties'] if key in documents[sid]}
                   for sid in candidate['document_ids']]
        records.append(dict(schema_version='research-draft-v1',candidate_id=cid,source_id=candidate['source_id'],
                            research_status=extracted['research_status'],sources=sources,claims=claims,missing_questions=questions,
                            conflicts=conflicts,proposed_fields=proposed,supplemental=[],review_reasons=['추출 초안: 사람의 사실 검토 필요'],
                            stop_reason=extracted['stop_reason'],audit=None))
        if v3 and 'event_period' in supported:
            period = supported['event_period']
            if period['start'] and period['end'] and period['start'] > period['end']:
                raise ValueError('inverted event period')
            proposed.update(valid_from=period['start'],valid_until=period['end'])
        if v3 and 'application_period' in supported:
            proposed['deadline_at'] = supported['application_period']['end']
    full = dict(schema_version='trial-result-v1',mode=host['mode'],status=draft['status'],records=records,errors=deepcopy(draft['errors']))
    report = validate(full, host, 'research')
    if v3:
        from .research_guard import audit
        report['structural_valid'] = report['valid']
        report['publication_approved'] = False
        if report['valid']:
            coverage = audit(draft,host)
            report['coverage'] = coverage
            report['valid'] = coverage['valid']
            if not coverage['valid']:
                report['errors'].append('required fields or restriction coverage requires review')
    return full, report
