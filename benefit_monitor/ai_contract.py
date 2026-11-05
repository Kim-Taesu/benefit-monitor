"""Offline, fail-closed AI draft checks. Never publishes or calls a model/network.

Only the JSON Schema keywords used by our bundled schemas are implemented.
Semantic truth and host input authenticity still require human/collector review.
"""
import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMAS = Path(__file__).resolve().parents[1] / 'docs/ai/schemas'


def check_schema(value, schema, path='$'):
    errors = []
    if 'anyOf' in schema:
        return [] if any(not check_schema(value, s, path) for s in schema['anyOf']) else [path + ': no matching shape']
    types = {'object': dict, 'array': list, 'string': str, 'null': type(None), 'integer': int}
    if 'type' in schema:
        names = schema['type'] if isinstance(schema['type'], list) else [schema['type']]
        if not any(type(value) is types[n] for n in names):
            return [path + ': invalid type']
    if 'enum' in schema and value not in schema['enum']:
        errors.append(path + ': invalid enum')
    if isinstance(value, str) and len(value) < schema.get('minLength', 0):
        errors.append(path + ': empty string')
    if isinstance(value, dict) and 'properties' in schema:
        for key in schema.get('required', []):
            if key not in value:
                errors.append(path + ': missing ' + key)
        for key, child in value.items():
            if key not in schema['properties']:
                errors.append(path + ': unexpected ' + key)
            else:
                errors.extend(check_schema(child, schema['properties'][key], path + '.' + key))
    if isinstance(value, list) and 'items' in schema:
        for i, child in enumerate(value):
            errors.extend(check_schema(child, schema['items'], f'{path}[{i}]'))
    return errors


def _index(rows, key):
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError('duplicate ' + key)
    return indexed


def _timestamp(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError('timestamp requires timezone')
    return parsed


def _forbidden(value):
    if isinstance(value, dict):
        return any(k in ('verified_at', 'public_release') or (k == 'needs_recheck' and v is False) or _forbidden(v) for k, v in value.items())
    return isinstance(value, list) and any(_forbidden(v) for v in value)


def validate(result, host, kind):
    """Return errors and host assessment; readiness never authorizes publication."""
    schema = json.loads((SCHEMAS / f'{kind}-result.schema.json').read_text())
    errors = check_schema(result, schema)
    assessments = []
    if _forbidden(result):
        errors.append('forbidden approval field')
    if errors:
        return {'valid': False, 'errors': errors, 'assessments': []}
    try:
        now = _timestamp(host['now'])
        if result['mode'] != host['mode']:
            raise ValueError('mode mismatch')
        if result['mode'] == 'api_agent' and host.get('synthetic') is not False:
            raise ValueError('API mode requires non-fixture host')
        if result['status'] in ('blocked', 'failed') and not result['errors']:
            raise ValueError('blocked/failed requires errors')
        if result['status'] == 'completed' and result['errors']:
            raise ValueError('completed cannot contain errors')
        if kind == 'research':
            if not all(k in host for k in ('budget', 'output_schema_version')):
                raise ValueError('missing_input: budget/output_schema_version')
            if host['output_schema_version'] != 'research-draft-v1':
                raise ValueError('unsupported output contract')
            candidates = _index(host['candidates'], 'candidate_id')
            docs = _index(host['documents'], 'id')
            records = _index(result['records'], 'candidate_id')
            if result['status'] == 'completed' and set(records) != set(candidates):
                raise ValueError('completed must cover all candidates')
            for r in records.values():
                candidate = candidates[r['candidate_id']]
                if r['source_id'] != candidate['source_id']:
                    raise ValueError('candidate source mismatch')
                sources = _index(r['sources'], 'id')
                claims = _index(r['claims'], 'id')
                for sid, source in sources.items():
                    if sid not in candidate['document_ids']:
                        raise ValueError('document belongs to another candidate')
                    doc = docs[sid]
                    if any(value != doc.get(key) for key, value in source.items()):
                        raise ValueError('host source metadata changed')
                    if result['mode'] != 'offline_fixture' and (source['publisher_type'] == 'fixture' or not all(isinstance(source[k], str) and source[k].startswith('https://') for k in ('requested_url','final_url'))):
                        raise ValueError('live source requires HTTPS and non-fixture provenance')
                    if source['fetch_status'] == 'ok':
                        _timestamp(source['retrieved_at'])
                        if doc.get('hash_algorithm') != 'sha256-utf8-exact' or hashlib.sha256(doc['body'].encode()).hexdigest() != source['body_hash']:
                            raise ValueError('body hash mismatch or unsupported algorithm')
                for c in claims.values():
                    if c['status'] == 'unknown' and (c['value'] is not None or c['evidence']):
                        raise ValueError('unknown requires null value and no evidence')
                    if c['status'] != 'unknown' and (not c['evidence'] or (c['status'] == 'supported' and c['value'] is None)):
                        raise ValueError('supported/disputed requires value and evidence')
                    for e in c['evidence']:
                        sid = e['source_ref']
                        if sources[sid]['fetch_status'] != 'ok' or e['quote'] not in docs[sid]['body']:
                            raise ValueError('quote not in successful source')
                    if c['status'] == 'disputed' and (len({(e['source_ref'], e['quote']) for e in c['evidence']}) < 2 or not any(c['id'] in x['claim_ids'] for x in r['conflicts'])):
                        raise ValueError('disputed claim requires conflict and both sides')
                for x in r['conflicts'] + r['supplemental']:
                    if not x['claim_ids'] or not set(x['claim_ids']) <= claims.keys():
                        raise ValueError('unknown/empty claim references')
                p = r['proposed_fields']
                for c in claims.values():
                    if c['status'] != 'supported':
                        continue
                    if c['field'] in p and p[c['field']] is not None and p[c['field']] != c['value']:
                        raise ValueError('proposed field contradicts supported claim')
                    dates = c['value'] if c['field'] == 'event_period' and isinstance(c['value'], dict) else ({'start':c['value'],'end':c['value']} if c['field'] == 'event_date' else {})
                    for target, key in (('valid_from','start'),('valid_until','end')):
                        if p[target] is not None and key in dates and p[target] != dates[key]:
                            raise ValueError('proposed date contradicts event claim')
                for field in ('valid_from','valid_until','published_at'):
                    if p[field] is not None:
                        date.fromisoformat(p[field])
                if p['deadline_at'] is not None:
                    _timestamp(p['deadline_at'])
                if p['valid_from'] and p['valid_until'] and p['valid_from'] > p['valid_until']:
                    raise ValueError('inverted validity dates')
                expired = bool(p['valid_until'] and date.fromisoformat(p['valid_until']) < now.astimezone(timezone(timedelta(hours=9))).date())
                expired |= bool(p['deadline_at'] and _timestamp(p['deadline_at']) < now)
                gaps = (any(q['importance'] == 'critical' for q in r['missing_questions']) or any(x['resolution'] is None for x in r['conflicts']) or any(docs[s]['fetch_status'] != 'ok' for s in candidate['document_ids']) or any(c['status'] == 'disputed' for c in claims.values()) or not any(c['status'] == 'supported' for c in claims.values()) or any(c['status'] == 'unknown' for c in claims.values()) or set(sources) != set(candidate['document_ids']) or not p['valid_until'])
                readiness = 'expired' if expired else ('needs_review' if gaps or r['research_status'] != 'completed' else 'ready_for_human_review')
                assessments.append({'candidate_id':r['candidate_id'], 'execution_status':r['research_status'], 'evidence_readiness':readiness, 'synthetic':result['mode'] == 'offline_fixture'})
        else:
            items = _index(host['approved_items'], 'item_id')
            claims = _index(host['approved_claims'], 'id')
            excluded = _index(host['excluded_items'], 'item_id')
            _index(result['topics'], 'topic_id')
            for t in result['topics']:
                if t['snapshot_id'] != host['snapshot_id'] or t['topic_id'] not in host['allowed_topic_ids']:
                    raise ValueError('unknown snapshot/topic')
                _index(t['item_links'], 'item_id')
                output_excluded = {x['item_id'] for x in result['excluded_items'] + t['excluded_items']}
                if any(x['item_id'] in output_excluded for x in t['item_links']):
                    raise ValueError('item both included and excluded')
                for link in t['item_links']:
                    item = items[link['item_id']]
                    if not item['display_eligible'] or link['item_id'] in excluded or not link['evidence_claim_ids']:
                        raise ValueError('ineligible item or missing claim')
                    for cid in link['evidence_claim_ids']:
                        if cid not in item['claim_ids'] or claims[cid]['item_id'] != link['item_id']:
                            raise ValueError('claim belongs to another item')
                for p in t['profile_conditions']:
                    if p.get('reference_date') is not None:
                        date.fromisoformat(p['reference_date'])
                    if p['operator'] == 'between' and not 0 <= p['min'] <= p['max'] <= 150:
                        raise ValueError('invalid age range')
            for x in result['excluded_items'] + [x for t in result['topics'] for x in t['excluded_items']]:
                if x['item_id'] not in items and x['item_id'] not in excluded:
                    raise ValueError('unknown excluded item')
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        errors.append(str(exc))
    return {'valid':not errors, 'errors':errors, 'assessments':assessments if not errors else []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('research','topic'))
    parser.add_argument('input', type=Path)
    parser.add_argument('result', type=Path)
    args = parser.parse_args()
    report = validate(json.loads(args.result.read_text()), json.loads(args.input.read_text()), args.kind)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
