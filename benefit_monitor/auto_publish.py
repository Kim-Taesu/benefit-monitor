"""Deterministic auto-publish gate for validated research drafts. No I/O except sources.yaml.

Every rule must pass; any doubt holds the item in the private review queue. Model sentences
(unknown_reason, summaries) never decide anything here: only claim status, structured values,
host document bodies/hashes/timestamps and the current time do.
"""
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
PROJECT = Path(__file__).resolve().parents[1]
PAST_SIGNAL = re.compile(r'종료|마감되었|마감됨|결과\s*발표|지난\s*(?:차수|행사)|\d{4}년\s*(?:행사|차)\s*(?:종료|결과)')
# Ongoing items must not hide an ending the model did not report (e.g. year-less "11월 30일까지").
ENDING_DATE = re.compile(r'(?:\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}\s*[./-]\s*\d{1,2}\.?)\s*(?:\([^)]{1,4}\))?\s*'
                         r'(?:\d{1,2}:\d{2}\s*)?(?:까지|마감)'
                         r'|[~～∼]\s*(?:\d{4}\s*[./년-]\s*)?\d{1,2}\s*[./월-]\s*\d{1,2}')
CORE = ('summary', 'conditions', 'fee_status', 'eligibility')
COST = ('cost_details', 'payment_conditions')
PAID = ('paid', 'mixed', 'conditional')
# Public Benefit fee values; 'conditional' is not one (review_desk also leaves it unknown).
PUBLIC_FEE = {'free': 'free', 'paid': 'paid', 'mixed': 'mixed'}
ONGOING_DAYS = 90
PUBLISHED_MAX_DAYS = 365
FRESH_HOURS = 30
BRACKETS = re.compile(r'[()\[\]{}<>（）［］｛｝〈〉《》「」『』【】〔〕]')
YEAR = re.compile(r'(?:19|20)\d{2}\s*년?')


def _norm(text):
    text = unicodedata.normalize('NFKC', text or '').lower()
    return re.sub(r'\s+', '', BRACKETS.sub('', YEAR.sub('', text)))


def title_key(title, organizer):
    """Title + organizer with whitespace, brackets and years removed, lowercased."""
    return _norm(title) + '|' + _norm(organizer)


def takedown_matches(item, takedowns):
    cid, key = item.get('candidate_id'), item.get('title_key')
    return any((cid and t.get('candidate_id') == cid) or (key and t.get('title_key') == key) for t in takedowns)


def _organizer_names():
    try:
        return {s['id']: s.get('name') or s['id'] for s in json.loads((PROJECT/'sources.yaml').read_text())['sources']}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def _end_point(value):
    """(KST date, comparable instant or None) for a canonical date or timestamp string."""
    if 'T' in value:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if moment.tzinfo is None:
            raise ValueError('timestamp without timezone')
        return moment.astimezone(KST).date(), moment
    return date.fromisoformat(value), None


def _hold(reasons):
    return {'publish': False, 'reasons': reasons, 'record': None}


def decide(draft, host, now, takedowns):
    from .claude_trial import evaluate_draft
    if now.tzinfo is None:
        raise ValueError('timezone required')
    try:
        _, report = evaluate_draft(draft, host, 'research', required_version='research-extraction-v3')
        candidate = host['candidates'][0]
        records = draft['records']
        if (not report['valid'] or len(host['candidates']) != 1 or len(records) != 1
                or records[0]['candidate_id'] != candidate['candidate_id']):
            return _hold(['contract'])
    except (ValueError, KeyError, TypeError, IndexError):
        return _hold(['contract'])
    facts = {f['field']: f for f in records[0]['facts']}
    docs = {d['id']: d for d in host['documents']}
    today = now.astimezone(KST).date()

    def supported(field):
        fact = facts.get(field)
        return fact['value'] if fact and fact['status'] == 'supported' else None

    def evidence(*fields):
        return [e for f in fields if supported(f) is not None for e in facts[f]['evidence']]

    def hashes(items):
        return {docs[e['source_ref']]['body_hash'] for e in items}

    reasons = []
    if any(f['status'] == 'disputed' for f in facts.values()):
        reasons.append('disputed')
    if any(supported(f) is None for f in CORE):
        reasons.append('core_missing')
    fee = supported('fee_status')
    if fee in PAID and all(supported(f) is None for f in COST):
        reasons.append('cost_missing')

    # Known endings from the period claims; every known ending must still be current.
    ends = []
    for field in ('event_period', 'application_period'):
        value = supported(field)
        if isinstance(value, dict) and value.get('end'):
            day, moment = _end_point(value['end'])
            quotes = [e['quote'] for e in facts[field]['evidence']]
            ends.append(dict(field=field, raw=value['end'], day=day, moment=moment, quotes=quotes,
                             hashes=hashes(facts[field]['evidence'])))
    period_ok = single_ok = bool(ends)
    year_trap = False
    for end in ends:
        current = end['moment'] > now if end['moment'] else end['day'] >= today
        # The year itself must be written in the cited official text, not only in the model value.
        stated = any(str(end['day'].year) in q for q in end['quotes'])
        period_ok = period_ok and current and stated
        single_ok = single_ok and len(end['hashes']) >= 2
        year_trap = year_trap or end['day'].year not in (today.year, today.year + 1)

    published = supported('published_at')
    published_day = date.fromisoformat(published) if published else None
    host_published = [date.fromisoformat(str(d['published_at'])[:10]) for d in host['documents'] if d.get('published_at')]
    for day in ([published_day] if published_day else []) + host_published:
        if day > today or (today - day).days > PUBLISHED_MAX_DAYS:
            year_trap = True

    operating = evidence('summary', 'conditions')
    if ends:
        kind = 'fixed'
    else:
        kind = 'ongoing'
        two_docs = len(hashes(operating)) >= 2
        hidden_end = any(ENDING_DATE.search(d['body']) for d in host['documents'])
        recent = published_day is not None and today - timedelta(days=ONGOING_DAYS) <= published_day <= today
        period_ok = recent and two_docs and not hidden_end
        single_ok = two_docs
    if not period_ok:
        reasons.append('no_current_evidence')
    if not single_ok:
        reasons.append('single_source')
    if year_trap:
        reasons.append('year_trap')
    if any(PAST_SIGNAL.search(d['body']) for d in host['documents']) or PAST_SIGNAL.search(candidate.get('title', '')):
        reasons.append('past_signal')

    labels = {}  # v3 drafts carry no labels; organizer falls back to the source name.
    organizer = labels.get('organizer') or _organizer_names().get(candidate['source_id'], candidate['source_id'])
    key = title_key(candidate.get('title', ''), organizer)
    if takedown_matches({'candidate_id': candidate['candidate_id'], 'title_key': key}, takedowns):
        reasons.append('taken_down')
    limit = now - timedelta(hours=FRESH_HOURS)
    try:
        stale = any(datetime.fromisoformat(d['retrieved_at']) < limit or datetime.fromisoformat(d['retrieved_at']) > now
                    for d in host['documents'])
    except (KeyError, TypeError, ValueError):
        stale = True
    if stale:
        reasons.append('stale_check')
    if reasons:
        return _hold(reasons)

    # Display until the earliest known ending; a deadline timestamp keeps its exact time.
    valid_until = deadline_at = None
    if ends:
        first = min(ends, key=lambda e: (e['day'], e['field'] != 'application_period'))
        valid_until = first['day'].isoformat()
        if first['field'] == 'application_period' and first['moment']:
            deadline_at = first['raw']
    event = supported('event_period') or {}
    valid_from = event.get('start')
    if valid_from and valid_until and valid_from > valid_until:
        valid_from = None
    cited = {e['source_ref'] for f in facts.values() if f['status'] == 'supported' for e in f['evidence']}
    # Participation cost and payment terms stay visible next to the conditions.
    conditions = '. '.join([supported('conditions')] + [f'{label}: {supported(f)}' for f, label in
                                                         (('cost_details', '비용'), ('payment_conditions', '결제 조건'))
                                                         if supported(f) is not None])
    original = candidate['document_ids'][0]
    documents = [dict(url=d.get('final_url') or d['requested_url'], body_hash=d['body_hash'],
                      title=candidate.get('title', '') if d['id'] == original else '')
                 for d in host['documents'] if d['id'] in cited]
    first_doc = docs[original]
    record = dict(
        schema_version=1, candidate_id=candidate['candidate_id'], source=candidate['source_id'],
        url=first_doc.get('final_url') or first_doc['requested_url'], title=candidate.get('title', ''),
        summary=supported('summary'), conditions=conditions, fee_status=PUBLIC_FEE.get(fee, 'unknown'),
        districts=list(supported('districts') or []), valid_from=valid_from, valid_until=valid_until,
        deadline_at=deadline_at, validity_kind=kind, labels=labels, payment_terms={},
        review=dict(kind='ai_auto', documents=documents, document_count=len({d['body_hash'] for d in documents}),
                    checked_at=now.isoformat(), published_at=published,
                    basis=dict(period_quotes=list(dict.fromkeys(q for e in ends for q in e['quotes'])),
                               operating_quotes=list(dict.fromkeys(e['quote'] for e in operating)))),
        title_key=key)
    return {'publish': True, 'reasons': [], 'record': record}
