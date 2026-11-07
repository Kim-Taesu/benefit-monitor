"""Structured-output wire contracts for Claude requests. No network.

The model writes only what it has to judge. The host keeps candidate IDs, titles,
snapshot IDs, claim references and exact quotes, then rebuilds the unchanged v3 research
and topic contracts so every existing local gate still runs on the result.

Anthropic structured outputs allow at most 16 union-typed parameters and 24 optional
parameters per request and do not support minLength/maxLength/minimum/maximum.
Schemas built here are checked against those limits before any paid request.

Beyond those limits the provider caps the compiled grammar size. On 2026-11-06 the
research schema with 14 unions and 5 regex patterns was rejected with HTTP 400
"The compiled grammar is too large" although count_tokens accepted it. Unions are
documented as exponentially expensive, so both schemas now use zero unions and zero
patterns; the host enforces the removed constraints before rebuilding v3 drafts.

The union-free version was rejected the same way: 15 distinct fact shapes, a 25-name
enum and repeated nested evidence still compiled too large. Research facts are now one
generic slot shape repeated in an array; field-specific value rules are host checks.
A paid grammar probe (claude_trial) verifies each new schema before real requests.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re

from .daily_topics import TITLES
from .research_guard import FIELDS, REQUIRED_FIELDS
from .topic_semantics import FACETS

PROJECT = Path(__file__).resolve().parents[1]
RESEARCH_WIRE = 'research-wire-v1'
TOPIC_WIRE = 'topic-wire-v1'
UNION_LIMIT = 16
OPTIONAL_LIMIT = 24
GRAMMAR_UNION_LIMIT = 0
GRAMMAR_PATTERN_LIMIT = 0
UNSUPPORTED = {'minLength', 'maxLength', 'minimum', 'maximum', 'multipleOf', 'maxItems', 'uniqueItems',
               'exclusiveMinimum', 'exclusiveMaximum', 'not', 'oneOf', 'if', 'then', 'else'}
OPTIONAL_FIELDS = tuple(f for f in FIELDS if f not in REQUIRED_FIELDS)
# Host-side format checks; never sent as schema patterns.
DATE_OR_EMPTY = '^([0-9]{4}-[0-9]{2}-[0-9]{2})?$'
TIMESTAMP_OR_EMPTY = '^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}(:[0-9]{2})?(Z|[+-][0-9]{2}:[0-9]{2}))?$'
FACT_STATUSES = ['supported', 'disputed', 'unknown']
TEXT_FIELDS = ('cost_details', 'payment_conditions', 'selection', 'application_method',
               'cancellation', 'restrictions', 'summary', 'conditions')
SCOPES = ('restricted', 'unrestricted', 'disputed')
FEES = ('free', 'paid', 'conditional')
ERROR_CODES = ['missing_input', 'policy_blocked', 'environment_unavailable', 'tool_failure', 'budget_exhausted']
STATUSES = ['completed', 'partial', 'blocked', 'failed']
SENTENCE = re.compile(r'.+?(?:[.!?。](?=\s|$)|$)')


def _object(properties):
    """Every property is required: optional properties count against the provider limit."""
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def _string():
    return {'type': 'string'}


def _errors():
    return {'type': 'array', 'items': _object({'code': {'enum': ERROR_CODES}, 'message': _string(),
                                               'candidate_id': _string()})}


def limits(schema):
    """Count union-typed parameters, optional parameters and unsupported keywords."""
    counts = {'unions': 0, 'optional': 0, 'patterns': 0, 'unsupported': set()}
    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        counts['unsupported'] |= UNSUPPORTED & set(node)
        if 'anyOf' in node or isinstance(node.get('type'), list):
            counts['unions'] += 1
        if 'pattern' in node:
            counts['patterns'] += 1
        if node.get('type') == 'object':
            if node.get('additionalProperties') is not False:
                counts['unsupported'].add('additionalProperties')
            counts['optional'] += len(set(node.get('properties', {})) - set(node.get('required', [])))
        if node.get('type') == 'array' and node.get('minItems', 0) not in (0, 1):
            counts['unsupported'].add('minItems')
        for key, child in node.items():
            if key in ('properties',):
                walk(list(child.values()))
            elif isinstance(child, (dict, list)):
                walk(child)
    walk(schema)
    counts['unsupported'] = sorted(counts['unsupported'])
    return counts


def check_limits(schema):
    found = limits(schema)
    if (found['unions'] > min(UNION_LIMIT, GRAMMAR_UNION_LIMIT) or found['patterns'] > GRAMMAR_PATTERN_LIMIT
            or found['optional'] > OPTIONAL_LIMIT or found['unsupported']):
        raise ValueError('structured output schema exceeds provider limits: ' + json.dumps(found))
    return found


# ---------------------------------------------------------------- research

def segments(body, prefix):
    """Split a body into sentence-like slices. Every text is an exact substring of body."""
    rows = []
    for line in re.finditer(r'[^\n]+', body):
        for match in SENTENCE.finditer(line.group()):
            text = match.group().strip()
            if text:
                rows.append({'id': f'{prefix}s{len(rows) + 1}', 'text': text})
    return rows


def research_model_input(host):
    """Replace each body with numbered segments; the host input itself is unchanged."""
    wire = deepcopy(host)
    for index, doc in enumerate(wire['documents'], 1):
        doc['segments'] = segments(doc.pop('body'), f'd{index}')
        doc.pop('body_hash', None)
        doc.pop('hash_algorithm', None)
    return wire


def segment_map(host):
    result = {}
    for index, doc in enumerate(host['documents'], 1):
        for row in segments(doc['body'], f'd{index}'):
            result[row['id']] = (doc['id'], row['text'])
    return result


def _districts():
    data = json.loads((PROJECT/'districts.json').read_text())
    return [d['name'] for d in data['districts']]


def research_wire_schema():
    """Static schema: one generic fact shape, no unions, patterns or field-specific branches.

    Slots per field: text fields and fee_status use `text`; eligibility uses text=scope,
    items=required and not_confirmed; periods use start/end; capacity uses number;
    districts use items; published_at uses start (YYYY-MM-DD). Unused slots are empty. research_from_wire enforces all of it.
    """
    text, texts = _string(), {'type': 'array', 'items': _string()}
    fact = _object({'field': {'enum': list(FIELDS)}, 'status': {'enum': FACT_STATUSES}, 'text': text,
                    'items': texts, 'not_confirmed': texts, 'start': text, 'end': text,
                    'number': {'type': 'integer'}, 'segment_ids': texts, 'unknown_reason': text})
    record = _object({'candidate_id': _string(), 'research_status': {'enum': STATUSES},
                      'stop_reason': {'enum': ['sufficient_evidence', 'budget_exhausted', 'access_blocked',
                                               'unsupported_document', 'unresolved_conflict', 'tool_failure']},
                      'facts': {'type': 'array', 'items': fact}})
    schema = _object({'wire_version': {'enum': [RESEARCH_WIRE]}, 'status': {'enum': STATUSES},
                      'errors': _errors(), 'records': {'type': 'array', 'items': record}})
    check_limits(schema)
    return schema


def _fact_value(field, fact):
    """Field-specific value rules that used to live in the grammar."""
    if field in TEXT_FIELDS:
        if not fact['text'].strip():
            raise ValueError('known text fact is empty')
        return fact['text']
    if field == 'fee_status':
        if fact['text'] not in FEES:
            raise ValueError('invalid fee_status')
        return fact['text']
    if field == 'eligibility':
        if fact['text'] not in SCOPES:
            raise ValueError('invalid eligibility scope')
        return {'scope': fact['text'], 'required': list(fact['items']), 'not_confirmed': list(fact['not_confirmed'])}
    if field in ('event_period', 'application_period'):
        pattern = DATE_OR_EMPTY if field == 'event_period' else TIMESTAMP_OR_EMPTY
        if any(not re.fullmatch(pattern, fact[key]) for key in ('start', 'end')):
            raise ValueError('invalid period format')
        return {key: fact[key] or None for key in ('start', 'end')}
    if field == 'published_at':
        if not re.fullmatch(DATE_OR_EMPTY, fact['start']) or not fact['start'] or fact['end']:
            raise ValueError('invalid period format')
        date.fromisoformat(fact['start'])
        return fact['start']
    if field == 'capacity':
        return fact['number']
    if field == 'districts':
        if not fact['items'] or any(name not in _districts() for name in fact['items']):
            raise ValueError('known districts must be non-empty Seoul district names')
        return list(fact['items'])
    raise ValueError('availability may only be unknown')


def research_from_wire(wire, host):
    """Rebuild a v3 compact draft. Unknown evidence segments are rejected, never dropped."""
    if wire.get('wire_version') != RESEARCH_WIRE:
        raise ValueError('research wire version mismatch')
    pieces = segment_map(host)
    records = []
    for record in wire['records']:
        by_field = {}
        for fact in record['facts']:
            if fact['field'] in by_field:
                raise ValueError('duplicate fact field')
            by_field[fact['field']] = fact
        if set(by_field) != set(FIELDS):
            raise ValueError('missing fact field')
        facts = []
        for field in FIELDS:
            fact = by_field[field]
            if fact['status'] == 'unknown':
                if not fact['unknown_reason'].strip():
                    raise ValueError('unknown fact without reason')
                if field in OPTIONAL_FIELDS:
                    continue
                facts.append({'field': field, 'value': None, 'status': 'unknown', 'evidence': [],
                              'unknown_reason': fact['unknown_reason'].strip()})
                continue
            if not fact['segment_ids']:
                raise ValueError('known fact without evidence')
            value = _fact_value(field, fact)
            evidence, seen = [], set()
            for sid in fact['segment_ids']:
                if sid not in pieces:
                    raise ValueError('unknown evidence segment')
                if sid in seen:
                    continue
                seen.add(sid)
                doc_id, text = pieces[sid]
                evidence.append({'source_ref': doc_id, 'quote': text, 'locator': sid})
            facts.append({'field': field, 'value': value, 'status': fact['status'], 'evidence': evidence,
                          'unknown_reason': None})
        records.append({'candidate_id': record['candidate_id'], 'research_status': record['research_status'],
                        'facts': facts, 'stop_reason': record['stop_reason']})
    errors = [dict(e, candidate_id=e['candidate_id'] or None) for e in wire['errors']]
    return {'schema_version': 'research-extraction-v3', 'status': wire['status'], 'errors': errors, 'records': records}


# ---------------------------------------------------------------- topics

def _title_facets(topic):
    return {name for name, pattern in FACETS.items() if re.search(pattern, TITLES[topic])}


def eligible_items(host):
    """Topic -> item IDs whose host editorial basis supports the topic and its fixed title."""
    allowed = [t for t in host.get('allowed_topic_ids', list(TITLES)) if t in TITLES]
    result = {}
    for topic in allowed:
        ids = [item['item_id'] for item in host['approved_items']
               if item.get('display_eligible') is True and isinstance(item.get('topic_basis'), dict)
               and topic in item['topic_basis'].get('topic_ids', [])
               and _title_facets(topic) <= set(item['topic_basis'].get('title_facets', []))]
        if ids:
            result[topic] = ids
    return result


def topic_wire_schema(host):
    """Union-free: topic and item enums are flat; topic_from_wire rejects ineligible pairs."""
    choices = eligible_items(host)
    if not choices:
        raise ValueError('no topic has eligible items; no request needed')
    all_ids = [item['item_id'] for item in host['approved_items']]
    linkable = [i for i in all_ids if any(i in ids for ids in choices.values())]
    defs = {'excluded': {'type': 'array', 'items': _object({'item_id': {'enum': all_ids}, 'reason': _string()})}}
    excluded = {'$ref': '#/$defs/excluded'}
    card = _object({'topic_id': {'enum': list(choices)},
                    'item_links': {'type': 'array', 'minItems': 1,
                                   'items': _object({'item_id': {'enum': linkable}, 'reason': _string(),
                                                     'match_type': {'enum': ['explicit', 'contextual']}})},
                    'excluded_items': excluded})
    schema = _object({'wire_version': {'enum': [TOPIC_WIRE]}, 'status': {'enum': STATUSES}, 'errors': _errors(),
                      'topics': {'type': 'array', 'items': card}, 'excluded_items': excluded})
    schema['$defs'] = defs
    check_limits(schema)
    return schema


def topic_from_wire(wire, host):
    """Attach host-owned title, snapshot and basis claim IDs; then the usual gates run."""
    if wire.get('wire_version') != TOPIC_WIRE:
        raise ValueError('topic wire version mismatch')
    items = {item['item_id']: item for item in host['approved_items']}
    choices = eligible_items(host)
    titles = host.get('allowed_topic_titles') or TITLES
    topics = []
    for card in wire['topics']:
        links = []
        if card['topic_id'] not in choices:
            raise ValueError('topic not eligible')
        for link in card['item_links']:
            if link['item_id'] not in choices[card['topic_id']]:
                raise ValueError('item not eligible for topic')
            basis = items[link['item_id']]['topic_basis']
            links.append({'item_id': link['item_id'], 'evidence_claim_ids': list(basis['evidence_claim_ids']),
                          'reason': link['reason'], 'match_type': link['match_type']})
        topics.append({'schema_version': 'topic-draft-v1', 'topic_id': card['topic_id'],
                       'title': titles[card['topic_id']], 'item_links': links, 'profile_conditions': [],
                       'excluded_items': deepcopy(card['excluded_items']), 'snapshot_id': host['snapshot_id'],
                       'audit': None})
    errors = [dict(e, candidate_id=e['candidate_id'] or None) for e in wire['errors']]
    return {'schema_version': 'trial-result-v1', 'mode': host['mode'], 'status': wire['status'],
            'errors': errors, 'topics': topics, 'excluded_items': deepcopy(wire['excluded_items'])}


def schema_for(kind, host):
    return research_wire_schema() if kind == 'research' else topic_wire_schema(host)


def from_wire(kind, wire, host):
    return research_from_wire(wire, host) if kind == 'research' else topic_from_wire(wire, host)
