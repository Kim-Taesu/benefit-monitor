"""AI verification contract (kind verify): audit public items, triage review candidates. No network.

The model sees the official body as numbered segments and answers with segment IDs only; the
host turns IDs back into exact quotes, so a verdict can never rest on text that is not in the
official page. decide() then applies deterministic rules:

- audit: a claim the model marks contradicted (with cited segments and an official value) holds
  the public item for human re-verification. Nothing is edited.
- triage: ended needs a cited segment with a year-dated past ending or completed-ending words,
  and no current year-dated ending anywhere in the document; not_benefit needs a cited segment.
  Both only take the candidate out of the review queue. ongoing/upcoming only raise priority.
"""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from .auto_publish import ENDING_DATE, FOUR_DIGIT_YEAR, phrase_end
from .validation import official
from .wire_format import _object, _string, check_limits, segments

INPUT = 'verify-input-v1'
WIRE = 'verify-wire-v1'
PURPOSES = ('audit', 'triage')
ITEM_STATUSES = ['ongoing', 'upcoming', 'ended', 'not_benefit', 'unclear']
VERDICTS = ['supported', 'contradicted', 'not_found']
MAX_CLAIMS = 12
MAX_CLAIM_TEXT = 400
# Completed endings only; "소진 시 종료" or "결과 발표 예정" are not endings.
ENDED_WORDS = re.compile(r'종료되었|종료됐|종료된\s*(?:행사|이벤트|사업)|마감되었|마감됐|운영을\s*마쳤')


def wire_schema():
    texts = {'type': 'array', 'items': _string()}
    # Evidence before verdict: generation follows property order, so the model cites, then judges.
    claim = _object({'claim_id': _string(), 'segment_ids': texts, 'official_text': _string(),
                     'verdict': {'enum': VERDICTS}})
    schema = _object({'wire_version': {'enum': [WIRE]}, 'status_segment_ids': texts,
                      'item_status': {'enum': ITEM_STATUSES}, 'claims': {'type': 'array', 'items': claim}})
    check_limits(schema)
    return schema


def validate_host(host, root):
    """Reject fixture, private or forged inputs before a paid request."""
    if set(host) != {'schema_version', 'mode', 'synthetic', 'now', 'purpose', 'item', 'documents'}:
        raise ValueError('unexpected verify host fields; private data must not be sent')
    if host['schema_version'] != INPUT or host['mode'] != 'api_agent' or host['synthetic'] is not False:
        raise ValueError('explicit non-fixture verify input required')
    if datetime.fromisoformat(host['now']).tzinfo is None:
        raise ValueError('host timestamp requires timezone')
    if host['purpose'] not in PURPOSES:
        raise ValueError('unknown verify purpose')
    config = json.loads((Path(root)/'sources.yaml').read_text())
    domains = {s['id']: s['domains'] for s in config['sources']}
    item = host['item']
    if set(item) != {'item_id', 'source_id', 'title', 'claims'} or item['source_id'] not in domains:
        raise ValueError('invalid verify item')
    claims = item['claims']
    if host['purpose'] == 'triage' and claims or host['purpose'] == 'audit' and not claims or len(claims) > MAX_CLAIMS:
        raise ValueError('invalid verify claims')
    ids = [c['claim_id'] for c in claims]
    if len(set(ids)) != len(ids) or any(set(c) != {'claim_id', 'field', 'text'} or not c['text'].strip()
                                        or len(c['text']) > MAX_CLAIM_TEXT for c in claims):
        raise ValueError('invalid verify claims')
    if not 1 <= len(host['documents']) <= 2:
        raise ValueError('invalid verify document count')
    for doc in host['documents']:
        if doc['source_id'] not in domains or not all(official(doc[k], domains[doc['source_id']])
                                                       for k in ('requested_url', 'final_url')):
            raise ValueError('unapproved verify document')
        if doc['hash_algorithm'] != 'sha256-utf8-exact' or hashlib.sha256(doc['body'].encode()).hexdigest() != doc['body_hash']:
            raise ValueError('verify body hash mismatch')
        if datetime.fromisoformat(doc['retrieved_at']).tzinfo is None:
            raise ValueError('source timestamp requires timezone')


def model_input(host):
    wire = deepcopy(host)
    for index, doc in enumerate(wire['documents'], 1):
        doc['segments'] = segments(doc.pop('body'), f'd{index}')
        for key in ('body_hash', 'hash_algorithm', 'links'):
            doc.pop(key, None)
    return wire


def _pieces(host):
    return {row['id']: row['text'] for index, doc in enumerate(host['documents'], 1)
            for row in segments(doc['body'], f'd{index}')}


def _quotes(ids, pieces):
    out = []
    for sid in ids:
        if sid not in pieces:
            raise ValueError('unknown evidence segment')
        if pieces[sid] not in out:
            out.append(pieces[sid])
    return out


def from_wire(wire, host):
    """Normalized result with exact quotes; any unknown segment or claim mismatch is rejected."""
    if wire.get('wire_version') != WIRE or wire.get('item_status') not in ITEM_STATUSES:
        raise ValueError('verify wire version mismatch')
    pieces = _pieces(host)
    expected = {c['claim_id']: c for c in host['item']['claims']}
    got = [c['claim_id'] for c in wire['claims']]
    if sorted(got) != sorted(expected) or len(set(got)) != len(got):
        raise ValueError('verify claims differ from the host claims')
    claims = []
    for row in wire['claims']:
        if row['verdict'] not in VERDICTS:
            raise ValueError('unknown verdict')
        quotes = _quotes(row['segment_ids'], pieces)
        if row['verdict'] == 'contradicted' and (not quotes or not row['official_text'].strip()):
            raise ValueError('contradiction without cited official text')
        if row['verdict'] == 'supported' and not quotes:
            raise ValueError('support without cited official text')
        source = expected[row['claim_id']]
        claims.append(dict(claim_id=row['claim_id'], field=source['field'], claim_text=source['text'],
                           verdict=row['verdict'], quotes=quotes, official_text=row['official_text'].strip()))
    return dict(schema_version='verify-result-v1', purpose=host['purpose'], item_id=host['item']['item_id'],
                item_status=wire['item_status'], status_quotes=_quotes(wire['status_segment_ids'], pieces), claims=claims)


def _ends(text):
    return [phrase_end(m.group()) for m in ENDING_DATE.finditer(text) if FOUR_DIGIT_YEAR.search(m.group())]


def decide(result, host, now):
    """{'action': hold|dismiss|prioritize|none, 'reason', 'findings'}; never edits facts."""
    today = now.date()
    if result['purpose'] == 'audit':
        findings = [c for c in result['claims'] if c['verdict'] == 'contradicted']
        return dict(action='hold' if findings else 'none', reason='ai_contradicted' if findings else '', findings=findings)
    status, quotes = result['item_status'], result['status_quotes']
    if status == 'ended' and quotes:
        cited_past = any(end is not None and end < today for q in quotes for end in _ends(q))
        later = any(end is not None and end >= today for d in host['documents'] for end in _ends(d['body']))
        if (cited_past or any(ENDED_WORDS.search(q) for q in quotes)) and not later:
            return dict(action='dismiss', reason='ended', findings=[])
    elif status == 'not_benefit' and quotes:
        return dict(action='dismiss', reason='not_benefit', findings=[])
    elif status in ('ongoing', 'upcoming') and quotes:
        return dict(action='prioritize', reason=status, findings=[])
    return dict(action='none', reason='', findings=[])
