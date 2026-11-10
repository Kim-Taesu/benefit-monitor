"""Deterministic auto-publish gate for validated research drafts. No I/O except sources.yaml.

Every rule must pass; any doubt holds the item in the private review queue. Model sentences
(unknown_reason, summaries) never decide anything here: only claim status, structured values,
host document bodies/hashes/timestamps and the current time do.
"""
from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
PROJECT = Path(__file__).resolve().parents[1]
PAST_SIGNAL = re.compile(r'종료|마감되었|마감됨|결과\s*발표|지난\s*(?:차수|행사)|\d{4}년\s*(?:행사|차)\s*(?:종료|결과)')
# Ongoing items must not hide an ending the model did not report (e.g. year-less "11월 30일까지").
_DATE = (r'(?<![\d./-])(?:(?:\d{4}\s*[./년-]\s*)?\d{1,2}\s*[./월-]\s*\d{1,2}\s*일?\.?'
         r'|(?:\d{4}\s*[./년-]\s*)?\d{1,2}\s*월\s*말|\d{1,2}\s*일)')
_TIME = r'(?:\s*\([^)]{1,4}\))?(?:\s*(?:오전|오후)?\s*\d{1,2}\s*(?:시(?:\s*\d{1,2}\s*분)?|:\d{2}))?'
# Deadlines ("…까지/마감") and date ranges ("11.1 - 11.30", "11월 1일 ~ 30일", "~ 11.30"); never "09:00~18:00".
ENDING_DATE = re.compile(_DATE + _TIME + r'\s*(?:까지|마감)'
                         r'|(?:' + _DATE + _TIME + r')?\s*[-–—~～∼]\s*' + _DATE)
FOUR_DIGIT_YEAR = re.compile(r'(?<!\d)\d{4}(?!\d)')
DATE_TOKEN = re.compile(r'(?:(?P<y>\d{4})\s*[./년-]\s*)?(?P<m>\d{1,2})\s*(?:[./-]|월)\s*(?P<d>\d{1,2}|말)|(?P<dd>\d{1,2})\s*일')


def phrase_end(text):
    """Last date of an ENDING_DATE match (deadline or range end); None if it cannot be read.

    Year and month carry forward from earlier dates in the same phrase ("2026.11.1 ~ 11.20",
    "11월 1일 ~ 30일"); "말" is the last day of that month.
    """
    year = month = None
    end = None
    for token in DATE_TOKEN.finditer(text):
        year = int(token['y']) if token['y'] else year
        month = int(token['m']) if token['m'] else month
        day = token['d'] or token['dd']
        if year is None or month is None:
            end = None
            continue
        try:
            if day == '말':
                end = (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1))
            else:
                end = date(year, month, int(day))
        except ValueError:
            return None
    return end
TIME_OF_DAY = re.compile(r'(?:(?P<half>오전|오후)\s*)?(?P<h>\d{1,2})\s*(?:시(?:\s*(?P<m>\d{1,2})\s*분)?|:(?P<mm>\d{2}))')


def phrase_deadline(text):
    """(last date, KST deadline or None) of an ending phrase; (None, None) when it cannot be read.

    A clock time written after the last date ("2026년 11월 8일 18시까지") becomes the deadline;
    digits there that do not read as a time make the whole phrase unreadable.
    """
    end = phrase_end(text)
    if end is None:
        return None, None
    last = list(DATE_TOKEN.finditer(text))[-1]
    rest = re.sub(r'\([^)]{1,4}\)', '', text[last.end():])
    if not re.search(r'\d', rest):
        return end, None
    clock = TIME_OF_DAY.search(rest)
    if clock is None or re.search(r'\d', rest[:clock.start()] + rest[clock.end():]):
        return None, None
    hour, minute = int(clock['h']), int(clock['m'] or clock['mm'] or 0)
    if clock['half'] == '오후' and hour < 12:
        hour += 12
    elif clock['half'] == '오전' and hour == 12:
        hour = 0
    if (hour, minute) == (24, 0):
        return end, None  # The end of that day.
    if hour > 23 or minute > 59:
        return None, None
    return end, datetime.combine(end, time(hour, minute), KST)


def _cutoff(day, moment):
    return moment or datetime.combine(day + timedelta(days=1), time.min, KST)


CORE = ('summary', 'conditions', 'fee_status', 'eligibility')
COST = ('cost_details', 'payment_conditions')
PAID = ('paid', 'mixed', 'conditional')
# Public Benefit fee values; a conditional fee is shown as mixed (ruling R11).
PUBLIC_FEE = {'free': 'free', 'paid': 'paid', 'mixed': 'mixed', 'conditional': 'mixed'}
ONGOING_DAYS = 90
PUBLISHED_MAX_DAYS = 365
FRESH_HOURS = 30
BRACKETS = re.compile(r'[()\[\]{}<>（）［］｛｝〈〉《》「」『』【】〔〕]')
YEAR = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)\s*년?')


def _norm(text):
    text = unicodedata.normalize('NFKC', text or '').lower()
    return re.sub(r'\s+', '', BRACKETS.sub('', YEAR.sub('', text)))


def public_fee(value):
    return PUBLIC_FEE.get(value, 'unknown')


def title_key(title, organizer):
    """Title + organizer with whitespace, brackets and years removed, lowercased."""
    return _norm(title) + '|' + _norm(organizer)


def takedown_matches(item, takedowns):
    cid, key = item.get('candidate_id'), item.get('title_key')
    return any(isinstance(t, dict) and ((cid and t.get('candidate_id') == cid) or (key and t.get('title_key') == key))
               for t in takedowns)


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


def _year_from_same_document(phrase, phrases):
    """Date of a year-less ending phrase, borrowed from the same document; None when unreadable.

    "11월 30일까지" reads as 2026-11-30 only when another phrase of that same document ends on
    11-30 with its year written ("2026년 10월 1일~11월 30일"). Several different years, a day without
    a month ("30일까지") or no such phrase leave it unreadable, which holds as before.
    """
    tokens = [t for t in DATE_TOKEN.finditer(phrase) if t['m']]
    if not tokens or tokens[-1]['d'] in (None, '말'):
        return None
    wanted = (int(tokens[-1]['m']), int(tokens[-1]['d']))
    years = set()
    for other in phrases:
        if FOUR_DIGIT_YEAR.search(other):
            end = phrase_end(other)
            if end is not None and (end.month, end.day) == wanted:
                years.add(end.year)
    if len(years) != 1:
        return None
    try:
        return date(years.pop(), *wanted)
    except ValueError:
        return None


def _period_end_without_year(phrase, ends):
    """A year-less ending phrase equal to the item's own period end, whose year the cited text states.

    Approved 2026-11-10: "11월 30일까지" in one notice and "2026년 10월 1일~11월 30일" quoted from
    another describe the same end, so no new (possibly passed) deadline hides behind it. Any other
    month-day stays unreadable and holds.
    """
    tokens = [t for t in DATE_TOKEN.finditer(phrase) if t['m']]
    if not tokens or tokens[-1]['d'] in (None, '말'):
        return None
    wanted = (int(tokens[-1]['m']), int(tokens[-1]['d']))
    days = {e['day'] for e in ends if (e['day'].month, e['day'].day) == wanted
            and any(str(e['day'].year) in q for q in e['quotes'])}
    return days.pop() if len(days) == 1 else None


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
        # Grade A (approved 2026-11-10): one official document suffices for a fixed period because the
        # year-dated end must itself be quoted from that text and still be current (period_ok above).
        single_ok = single_ok and len(end['hashes']) >= 1
        year_trap = year_trap or end['day'].year not in (today.year, today.year + 1)

    published = supported('published_at')
    published_day = date.fromisoformat(published) if published else None
    # Like period endings, the posting year must be written in the cited official text.
    published_stated = published_day is not None and any(
        str(published_day.year) in e['quote'] for e in facts['published_at']['evidence'])
    host_published = [date.fromisoformat(str(d['published_at'])[:10]) for d in host['documents'] if d.get('published_at')]
    for day in ([published_day] if published_day else []) + host_published:
        if day > today or (today - day).days > PUBLISHED_MAX_DAYS:
            year_trap = True

    operating = evidence('summary', 'conditions')
    body_ends = []
    if ends:
        kind = 'fixed'
        # An unreported application deadline could already have passed. A year-less phrase holds
        # unless the same document writes that month and day with a year (see
        # _year_from_same_document). Year-dated ones are read: a past or unreadable one holds (no_current_evidence); a current
        # one is kept so the item is hidden after the earliest of them (and after its time, if any).
        if supported('application_period') is None:
            for d in host['documents']:
                matches = [m.group() for m in ENDING_DATE.finditer(d['body'])]
                for phrase in matches:
                    if FOUR_DIGIT_YEAR.search(phrase):
                        stated_end, moment = phrase_deadline(phrase)
                    else:
                        stated_end, moment = _year_from_same_document(phrase, matches), None
                        if stated_end is None:
                            stated_end = _period_end_without_year(phrase, ends)
                    if stated_end is None or stated_end < today or (moment is not None and moment <= now):
                        period_ok = False
                    else:
                        body_ends.append((stated_end, moment))
    else:
        kind = 'ongoing'
        two_docs = len(hashes(operating)) >= 2
        hidden_end = any(ENDING_DATE.search(d['body']) for d in host['documents'])
        window = lambda day: today - timedelta(days=ONGOING_DAYS) <= day <= today
        # The official page header date (read by code, never by the model) of a cited document counts too.
        page_days = [date.fromisoformat(str(docs[e['source_ref']]['published_at'])[:10])
                     for e in operating if docs[e['source_ref']].get('published_at')]
        recent = (published_stated and window(published_day)) or any(window(day) for day in page_days)
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
        if body_ends:
            current = _cutoff(first['day'], _end_point(deadline_at)[1] if deadline_at else None)
            day, moment = min(body_ends, key=lambda e: _cutoff(*e))
            if _cutoff(day, moment) < current:
                valid_until, deadline_at = day.isoformat(), moment.isoformat() if moment else None
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
        summary=supported('summary'), conditions=conditions, fee_status=public_fee(fee),
        districts=list(supported('districts') or []), valid_from=valid_from, valid_until=valid_until,
        deadline_at=deadline_at, validity_kind=kind, labels=labels, payment_terms={},
        review=dict(kind='ai_auto', documents=documents, document_count=len({d['body_hash'] for d in documents}),
                    checked_at=now.isoformat(), published_at=published, original_body_hash=first_doc['body_hash'],
                    basis=dict(period_quotes=list(dict.fromkeys(q for e in ends for q in e['quotes'])),
                               operating_quotes=list(dict.fromkeys(e['quote'] for e in operating)))),
        title_key=key)
    return {'publish': True, 'reasons': [], 'record': record}
