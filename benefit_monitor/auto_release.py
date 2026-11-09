"""Second approval list: AI auto-published records, rechecked deterministically on every public path.

approved.json only changes when the AI re-decides or the daily body check marks a record, so every
reader re-applies format, allowlist, takedowns, expiry, 30-hour freshness and the 90-day posting
rule here. Any doubt hides the record; nothing here can add a fact that was not approved.
"""
from copy import deepcopy
from datetime import date, datetime, time, timedelta
import json
import os
from pathlib import Path
import re

from .auto_publish import FRESH_HOURS, KST, ONGOING_DAYS, takedown_matches
from .store import save

APPROVED = 'cache/ai_publish/approved.json'
TAKEDOWNS = 'cache/ai_publish/takedowns.json'
STATUS = 'cache/ai_daily/status.json'
RECORD_KEYS = ('schema_version', 'candidate_id', 'source', 'url', 'title', 'summary', 'conditions', 'fee_status',
               'districts', 'valid_from', 'valid_until', 'deadline_at', 'validity_kind', 'labels', 'payment_terms',
               'review', 'title_key', 'decided_at', 'status', 'withdrawn_reason', 'withdrawn_at', 'recheck_priority')
REVIEW_KEYS = ('kind', 'documents', 'document_count', 'checked_at', 'published_at', 'basis', 'original_body_hash')
WITHDRAWN = ('status', 'withdrawn_reason', 'withdrawn_at', 'recheck_priority')
AI_STATES = ('ok', 'credit_exhausted', 'failed')
MAX_RECHECKS = 20
RECHECK_SKIP_HOURS = 6
CID = re.compile('[0-9a-f]{24}')
HASH = re.compile('[0-9a-f]{64}')


def _read(path):
    """(value, ok); a missing file is (None, True), unreadable JSON is (None, False)."""
    try:
        return json.loads(Path(path).read_text()), True
    except FileNotFoundError:
        return None, True
    except (OSError, ValueError):
        return None, False


def load(root):
    """(approved, takedowns). Unreadable takedowns hide every auto record (fail closed)."""
    approved, _ = _read(Path(root) / APPROVED)
    takedowns, ok = _read(Path(root) / TAKEDOWNS)
    if takedowns is None and ok:
        takedowns = []
    if not isinstance(takedowns, list):
        return {}, []
    return (approved if isinstance(approved, dict) else {}), [t for t in takedowns if isinstance(t, dict)]


def save_approved(root, approved):
    save(Path(root) / APPROVED, {cid: public_record(r) for cid, r in approved.items() if isinstance(r, dict)})


def public_record(record):
    """Public-safe projection for the briefing-data file: no host bodies, ledger or review rows."""
    out = {k: deepcopy(record[k]) for k in RECORD_KEYS if k in record}
    review = record.get('review')
    if isinstance(review, dict):
        out['review'] = {k: deepcopy(review[k]) for k in REVIEW_KEYS if k in review}
        docs = review.get('documents')
        if isinstance(docs, list):
            out['review']['documents'] = [{k: d[k] for k in ('url', 'body_hash', 'title') if k in d}
                                          for d in docs if isinstance(d, dict)]
    return out


def ai_status(value):
    """Sanitized public AI run status, or None."""
    try:
        if not isinstance(value, dict) or value.get('state') not in AI_STATES:
            return None
        day = value.get('last_success_day')
        if day is not None and date.fromisoformat(day).isoformat() != day:
            return None
        updated = datetime.fromisoformat(value['updated_at'])
        if updated.tzinfo is None:
            return None
        return {'state': value['state'], 'last_success_day': day, 'updated_at': updated.isoformat()}
    except (KeyError, TypeError, ValueError):
        return None


def load_status(root):
    return ai_status(_read(Path(root) / STATUS)[0])


def _aware(value):
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError('timezone required')
    return moment


def candidate(record, sources):
    """Public item for a well-formed record (no time or takedown rules), else None."""
    from .publish import PRIVATE_TEXT, PUBLIC_FIELDS
    from .validation import official, validate
    try:
        review = record['review']
        documents = review['documents']
        if (record.get('status') not in (None, 'withdrawn') or review['kind'] != 'ai_auto' or not CID.fullmatch(record['candidate_id'])
                or not isinstance(record['title_key'], str) or not isinstance(documents, list) or not documents
                or type(review['document_count']) is not int or not 1 <= review['document_count'] <= len(documents)):
            return None
        domains = {d for s in sources.values() for d in s['domains']}
        public_docs = []
        for doc in documents:
            if (not isinstance(doc.get('url'), str) or not official(doc['url'], domains) or not isinstance(doc.get('title'), str)
                    or not HASH.fullmatch(doc.get('body_hash', ''))):
                return None
            public_docs.append({'url': doc['url'], 'title': doc['title']})
        checked = _aware(review['checked_at']).isoformat()
        if review.get('published_at') is not None:
            date.fromisoformat(review['published_at'])
        evidence = ' '.join(q for quotes in (review.get('basis') or {}).values() for q in quotes) or 'ai_auto'
        item = validate(dict(source=record['source'], url=record['url'], title=record['title'], summary=record['summary'],
                             conditions=record['conditions'], districts=record['districts'], verified_at=checked,
                             valid_from=record['valid_from'], valid_until=record['valid_until'],
                             deadline_at=record['deadline_at'], validity_kind=record['validity_kind'],
                             fee_status=record['fee_status'], needs_recheck=False, payment_terms=record['payment_terms'],
                             labels=record['labels'], evidence=evidence),
                        sources, datetime.max.replace(tzinfo=KST))
        if item.validity_kind == 'fixed' and not item.valid_until:
            return None
        if item.validity_kind == 'ongoing' and not review.get('published_at'):
            return None
        data = item.data()
        public = {k: data[k] for k in PUBLIC_FIELDS if k not in ('benefit_value', 'review')}
        public['review'] = {'kind': 'ai_auto', 'document_count': review['document_count'], 'documents': public_docs,
                            'checked_at': checked, 'candidate_id': record['candidate_id'], 'title_key': record['title_key']}
        if PRIVATE_TEXT.search(json.dumps(public, ensure_ascii=False)):
            return None
        return public
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def display_until(record, item, now, fresh=True):
    """Earliest cutoff (freshness, deadline, end date, ongoing posting age) or None when already past.

    fresh=False leaves out the 30-hour freshness cutoff (used to pick records worth rechecking).
    """
    review = record['review']
    checked = _aware(item['verified_at'])
    if checked > now:
        return None
    cutoffs = [checked + timedelta(hours=FRESH_HOURS)] if fresh else []
    if item['deadline_at']:
        cutoffs.append(_aware(item['deadline_at']))
    if item['valid_until']:
        cutoffs.append(datetime.combine(date.fromisoformat(item['valid_until']) + timedelta(days=1), time.min, KST))
    if item['validity_kind'] == 'ongoing':
        posted = date.fromisoformat(review['published_at'])
        if posted > now.astimezone(KST).date():
            return None
        cutoffs.append(datetime.combine(posted + timedelta(days=ONGOING_DAYS + 1), time.min, KST))
    until = min(cutoffs)
    return until.astimezone(KST).isoformat() if until > now else None


def current_releases(approved, takedowns, sources, now):
    """{identity: (record, item)} of well-formed records and the subset that is public now."""
    if now.tzinfo is None:
        raise ValueError('timezone required')
    formed, public = {}, {}
    for cid, record in (approved.items() if isinstance(approved, dict) else ()):
        if not isinstance(record, dict) or record.get('candidate_id') != cid:
            continue
        item = candidate(record, sources)
        if item is None:
            continue
        key = (item['source'], item['url'])
        if key in formed:  # Two approvals for one page are ambiguous: show neither.
            formed[key] = public[key] = None
            continue
        formed[key] = item
        if record.get('status') == 'withdrawn' or takedown_matches(record, takedowns):
            continue
        until = display_until(record, item, now)
        if until:
            public[key] = dict(item, display_until=until)
    return {k: v for k, v in formed.items() if v}, {k: v for k, v in public.items() if v}


def public_items(approved, takedowns, sources, now):
    return list(current_releases(approved, takedowns, sources, now)[1].values())


def is_auto(row):
    return isinstance(row, dict) and isinstance(row.get('review'), dict) and row['review'].get('kind') == 'ai_auto'


def _still_current(row, current):
    """The row as published now (earliest cutoff kept), or None when it is not the current public release."""
    from .publish import PUBLIC_FIELDS
    fact = current.get((row.get('source'), row.get('url')))
    if fact is None or any(row.get(k) != fact[k] for k in PUBLIC_FIELDS if k in fact):
        return None
    try:
        until = min(_aware(row.get('display_until') or fact['display_until']), _aware(fact['display_until']))
    except (TypeError, ValueError):
        return None
    return dict(row, display_until=until.astimezone(KST).isoformat())


def apply_takedowns(data, takedowns, current=None):
    """Remove taken-down AI items (and their topic links) from an existing public payload; never adds.

    current (the public set from current_releases) also removes every AI item that is not that exact
    release now, so a restored payload never brings back a withdrawn, expired, stale or changed item.
    """
    data = deepcopy(data)
    removed = set()
    kept = []
    for row in data.get('items', []):
        if is_auto(row) and current is not None and not takedown_matches(row['review'], takedowns):
            fresh = _still_current(row, current)
            if fresh is not None:
                kept.append(fresh)
                continue
        if is_auto(row) and (current is not None or takedown_matches(row['review'], takedowns)):
            removed.add((row.get('source'), row.get('url')))
        else:
            kept.append(row)
    data['items'] = kept
    cards = data.get('topic_cards')
    if isinstance(cards, dict) and isinstance(cards.get('topics'), list):
        topics = []
        for topic in cards['topics']:
            refs = [r for r in topic.get('items', []) if (r.get('source'), r.get('url')) not in removed]
            if refs:
                topics.append(dict(topic, items=refs))
        cards['topics'] = topics
    if 'grocery_pick' in data:
        # Admin mute: the same rule card the collection path would publish (no model text).
        from .grocery_pick import apply_mute
        pick = apply_mute(data['grocery_pick'], data.get('groceries'), takedowns)
        if pick is None:
            data.pop('grocery_pick')
        else:
            data['grocery_pick'] = pick
    return data


def mark_checked(approved, candidate_id, body_hash, now):
    """Daily body check: 'ok' renews checked_at; 'changed'/'gone' withdraws until the AI re-decides."""
    record = approved[candidate_id]
    review = record['review']
    baseline = review.get('original_body_hash') or next(
        (d.get('body_hash') for d in review.get('documents', []) if d.get('url') == record.get('url')), None)
    result = 'gone' if body_hash is None else 'ok' if baseline and body_hash == baseline else 'changed'
    if result == 'ok':
        review['checked_at'] = now.isoformat()
    elif record.get('status') != 'withdrawn':
        record.update(status='withdrawn', withdrawn_reason='source_gone' if result == 'gone' else 'body_changed',
                      withdrawn_at=now.isoformat(), recheck_priority=True)
    return result


def recheck_targets(approved, takedowns, sources, now):
    """Up to 20 records that could still be shown (not withdrawn, taken down, ended or past 90 days),
    least recently checked first; ones checked in the last 6 hours are skipped."""
    rows = []
    for cid, record in approved.items():
        if not isinstance(record, dict) or record.get('candidate_id') != cid or record.get('status') == 'withdrawn':
            continue
        item = candidate(record, sources)
        try:
            if (item is None or takedown_matches(record, takedowns) or not display_until(record, item, now, fresh=False)
                    or now - _aware(item['verified_at']) < timedelta(hours=RECHECK_SKIP_HOURS)):
                continue
        except (KeyError, TypeError, ValueError):
            continue
        rows.append((_aware(item['verified_at']), cid))
    return [cid for _, cid in sorted(rows)[:MAX_RECHECKS]]


def _checked(record):
    try:
        return _aware(record['review']['checked_at'])
    except (KeyError, TypeError, ValueError):
        return datetime.min.replace(tzinfo=KST)


def _merge_record(ours, theirs):
    if (ours.get('decided_at') or '') != (theirs.get('decided_at') or ''):
        return deepcopy(max(ours, theirs, key=lambda r: r.get('decided_at') or ''))
    newest = deepcopy(max((theirs, ours), key=_checked))
    withdrawn = next((r for r in (ours, theirs) if r.get('status') == 'withdrawn'), None)
    if withdrawn:
        newest.update({k: withdrawn[k] for k in WITHDRAWN if k in withdrawn})
    return newest


def merge_approved(base, ours, theirs):
    """Three-way merge after a write conflict: withdrawn wins, newer check wins, new ids added, removals kept."""
    merged = {}
    for cid in sorted(set(ours) | set(theirs)):
        mine, other = ours.get(cid), theirs.get(cid)
        if mine is None or other is None:
            if cid in base:  # Removed by one writer since the common read (an AI re-decision held it).
                continue
            merged[cid] = deepcopy(mine or other)
        else:
            merged[cid] = _merge_record(mine, other)
    return merged


def move_aside(path, now):
    """Keep an unreadable file for review instead of overwriting it with a smaller dict."""
    path = Path(path)
    target = path.with_name(path.stem + '.corrupt-' + now.strftime('%Y%m%dT%H%M%S%z') + path.suffix)
    os.replace(path, target)
    return target
