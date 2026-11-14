"""Weekly benefit pick: Haiku writes a short summary over published benefits; code checks every word that matters.

Approved 2026-11-14 (same exception as grocery_pick and festival_pick): the model's summary and one-line notes may be
published with an "AI 작성" label, only after review() confirms every date and number belongs to the benefit it
describes, "무료" matches the benefit's fee status, a paid benefit's line states its cost, and no guarantee, eligibility
or stock claim appears. Titles, links and conditions on the page always come from the published items. Any failure falls
back to rule_pick(): no model text. A pick never changes which benefits are published or their order.
"""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

from .ai_review import invoke
from .official_reader import project_path
from .store import load, lock, save, save_text

TRIAL_RUNS = Path(__file__).resolve().parents[1] / '.tools/claude-trial/live/runs'

MAX_PICKS = 10
MIN_PICKS = 3
MIN_CANDIDATES = 3
RULE_PICKS = 5
MAX_AGE_HOURS = 36
TAKEDOWN_KIND = 'benefit_pick_text'
SUMMARY_MIN, SUMMARY_MAX = 20, 200
LINE_MIN, LINE_MAX = 1, 50
CONDITIONS_MAX = 200
MARKUP = re.compile(r'[<>\n\r]|https?:|www\.')
CLAIMS = ('누구나', '받을 수 있', '확실', '보장', '무조건', '100%', '최대', '누구든', '전원', '반드시', '신청하면', '바로 받',
          '모두 받')
STOCK = ('남은', '잔여', '소진 전', '자리 있')
COST_WORDS = ('구매', '결제', '유료', '비용', '참가비', '수강료')
PICK_FIELDS = {'schema_version', 'generated_at', 'day', 'source', 'summary', 'picks'}


def item_id(row):
    return hashlib.sha256(f"{row['source']}\n{row['url']}".encode()).hexdigest()[:12]


def _end(row):
    return str(row.get('deadline_at') or row.get('valid_until') or '')[:10]


def _rows(items, now):
    """Candidate dicts for published items that have not ended, soonest deadline first (no deadline last)."""
    today = now.date().isoformat()
    rows = []
    for row in items or []:
        end = _end(row)
        if end and end < today:
            continue
        labels = row.get('labels') if isinstance(row.get('labels'), dict) else {}
        rows.append(dict(id=item_id(row), title=row['title'], summary=row.get('summary') or '',
                         conditions=row.get('conditions') or '',
                         valid_from=row.get('valid_from'), valid_until=row.get('valid_until'),
                         deadline_at=row.get('deadline_at'), fee_status=row.get('fee_status'),
                         category=labels.get('category'), region=labels.get('region')))
    rows.sort(key=lambda c: (not _end(c), _end(c), c['title']))
    return rows


def _input(rows, now, trim=False):
    if trim:  # Only the copy sent to the model is shortened.
        rows = [dict(c, conditions=c['conditions'][:CONDITIONS_MAX]) for c in rows]
    return dict(schema_version='benefit-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                day=now.date().isoformat(), candidates=rows)


def host(items, now):
    """Model input, or None when there are too few benefits to be worth a paid call."""
    rows = _rows(items, now)
    return _input(rows, now, trim=True) if len(rows) >= MIN_CANDIDATES else None


FREE_WORDS = ('무료', '공짜', '무상', '0원')
FREE = re.compile('|'.join(r'(?<![\d,])0원' if w == '0원' else w for w in FREE_WORDS))
NO_COST = re.compile(r'(비용|참가비|수강료|구매|결제|유료)\s*(없|안\s*들|아님|아니|부담\s*없)|부담\s*없|공으로|free|반값|절반|\d\+\d',
                     re.IGNORECASE)
DIGITS = re.compile('[0-9\uff10-\uff19]')
RELATIVE = re.compile(r'오늘|내일|모레|이번\s?주|다음\s?주|주말|월말|연말')
QUOTED = re.compile(r"['\"‘’“”]([^'\"‘’“”]{2,})['\"‘’“”]")
WORD = re.compile(r'[0-9A-Za-z가-힣]+')
NAME_MIN = 2
GENERIC = ('혜택', '행사', '안내', '서비스', '프로그램', '이벤트', '신청', '이용', '운영', '서울', '무료') + FREE_WORDS


def _names(rows):
    """{candidate id: distinctive title parts}: quoted text plus title words of 2+ characters unique to that title."""
    words = {c['id']: {w for w in WORD.findall(c['title']) if len(w) >= NAME_MIN and not any(g in w for g in GENERIC)} for c in rows}
    names = {}
    for c in rows:
        quoted = [q.strip() for q in QUOTED.findall(c['title'])]
        unique = {w for w in words[c['id']] if sum(w in other for other in words.values()) == 1}
        names[c['id']] = set(quoted) | unique or {c['title']}
    return names


def _mentions(text, rows):
    """[(end, candidate)] for every occurrence of a distinctive title part, in text order."""
    names = _names(rows)
    found = []
    for c in rows:
        for name in names[c['id']]:
            for m in re.finditer(re.escape(name), text):
                found.append((m.end(), len(name), c))
    return [(end, c) for end, _, c in sorted(found, key=lambda f: (f[0], f[1]))]


def _owner_before(mentions, pos):
    named = [c for end, c in mentions if end <= pos]
    return named[-1] if named else None


def _check(summary, picks, host):
    """Error codes for picks (and the summary when not None); picks must already have the right shape."""
    errors = []
    by_id = {c['id']: c for c in host['candidates']}
    ids = [p['id'] for p in picks]
    if not MIN_PICKS <= len(ids) <= min(MAX_PICKS, len(by_id)):
        errors.append('picks_count')
    if any(i not in by_id for i in ids):
        errors.append('picks_unknown')
    if len(set(ids)) != len(ids):
        errors.append('picks_duplicate')
    if any(not LINE_MIN <= len(p['line']) <= LINE_MAX for p in picks):
        errors.append('line_length')
    texts = [p['line'] for p in picks] + ([summary] if summary is not None else [])
    if summary is not None and not SUMMARY_MIN <= len(summary) <= SUMMARY_MAX:
        errors.append('summary_length')
    if any(MARKUP.search(t) for t in texts):
        errors.append('markup')
    if any(word in t for t in texts for word in CLAIMS):
        errors.append('claim')
    if any(word in t for t in texts for word in STOCK):
        errors.append('stock')
    # Dates, amounts and deadlines are shown by the page from the data, never typed by the model.
    if any(DIGITS.search(t) or RELATIVE.search(t) for t in texts):
        errors.append('number')
    free_bad = any(NO_COST.search(t) for t in texts)
    free_bad = free_bad or any(FREE.search(p['line']) and by_id[p['id']]['fee_status'] != 'free'
                               for p in picks if p['id'] in by_id)
    if summary is not None:
        mentions = _mentions(summary, host['candidates'])
        if any(c['id'] not in ids for _, c in mentions):
            errors.append('summary_item')
        start = 0
        for sentence in re.split(r'(?<=[.!?])', summary):
            local = [(end - start, c) for end, c in mentions if start < end <= start + len(sentence)]
            for m in FREE.finditer(sentence):
                owner = _owner_before(local, m.start())
                if owner is None or owner['fee_status'] != 'free':
                    free_bad = True
            start += len(sentence)
    if free_bad:
        errors.append('free')
    for p in picks:
        if p['id'] in by_id and by_id[p['id']]['fee_status'] == 'paid' \
                and not any(w in NO_COST.sub(' ', p['line']) for w in COST_WORDS):
            errors.append('cost')
            break
    return errors


def review(draft, host):
    """Error codes; empty means the draft may be published."""
    if not isinstance(draft, dict) or set(draft) != {'summary', 'picks'} or not isinstance(draft['summary'], str) \
            or not isinstance(draft['picks'], list) \
            or not all(isinstance(p, dict) and set(p) == {'id', 'line'} and isinstance(p['id'], str)
                       and isinstance(p['line'], str) for p in draft['picks']):
        return ['draft_shape']
    return _check(draft['summary'], draft['picks'], host)


def rule_pick(host, now):
    """No model text: the soonest deadlines first."""
    return dict(schema_version=1, generated_at=now.isoformat(), day=host['day'], source='rule', summary=None,
                picks=[dict(id=c['id'], line=None) for c in host['candidates'][:RULE_PICKS]])


def muted(takedowns, day):
    return any(isinstance(t, dict) and t.get('kind') == TAKEDOWN_KIND and t.get('day') == day for t in takedowns or [])


def apply_mute(pick, items, takedowns, now):
    """Admin mute for that day: the same rule card on every publish path (no model text)."""
    if not isinstance(pick, dict) or pick.get('source') != 'ai' or not muted(takedowns, pick.get('day')):
        return pick
    rows = _rows(items, now)
    return rule_pick(_input(rows, now), now) if len(rows) >= MIN_CANDIDATES else None


def _fill(pick, items, now):
    """Public lines: {'id','source','url','line'} taken from the current items."""
    by_id = {item_id(row): row for row in items or []}
    lines = [dict(id=p['id'], source=by_id[p['id']]['source'], url=by_id[p['id']]['url'], line=p['line'])
             for p in pick['picks'] if p['id'] in by_id]
    return dict(pick, picks=lines) if lines else None


def _public(pick, items, takedowns, now):
    if not isinstance(pick, dict) or set(pick) != PICK_FIELDS or pick['schema_version'] != 1 \
            or pick['source'] not in ('ai', 'rule') or not isinstance(pick['picks'], list) \
            or not isinstance(pick['day'], str):
        return None
    generated = datetime.fromisoformat(pick['generated_at'])
    if generated.tzinfo is None or generated > now:
        return None
    rows = _rows(items, now)
    if len(rows) < MIN_CANDIDATES:
        return None  # Below the 3-line floor a recommendation adds nothing.
    current = _input(rows, now)
    ids = {c['id'] for c in rows}
    if not all(isinstance(p, dict) and set(p) == {'id', 'line'} and isinstance(p['id'], str) for p in pick['picks']):
        return rule_pick(current, now)
    if pick['source'] == 'rule':
        kept = [dict(p) for p in pick['picks'] if p['id'] in ids]
        if pick['summary'] is not None or not 1 <= len(pick['picks']) <= RULE_PICKS \
                or any(p['line'] is not None for p in pick['picks']) or not kept:
            return rule_pick(current, now)
        return dict(pick, picks=kept)
    if not isinstance(pick['summary'], str) or any(not isinstance(p['line'], str) for p in pick['picks']) \
            or now - generated > timedelta(hours=MAX_AGE_HOURS):
        return rule_pick(current, now)
    kept = [dict(p) for p in pick['picks'] if p['id'] in ids]
    dropped = len(kept) < len(pick['picks'])
    if dropped and len(kept) < min(3, len(pick['picks'])) or not kept:
        return rule_pick(current, now)
    summary = None if dropped else pick['summary']
    if _check(summary, kept, current):
        return rule_pick(current, now)
    return apply_mute(dict(pick, summary=summary, picks=kept), items, takedowns, now)


def public(pick, items, takedowns, now):
    """Re-check a stored pick against the current items; None when it cannot be shown today."""
    try:
        result = _public(pick, items, takedowns, now)
        return _fill(result, items, now) if result else None
    except (KeyError, TypeError, ValueError):
        return None


def _keep(previous, day, now):
    try:
        if previous.get('day') == day:
            return True
        return previous.get('source') == 'ai' \
            and now - datetime.fromisoformat(previous['generated_at']) <= timedelta(hours=MAX_AGE_HOURS)
    except (KeyError, TypeError, ValueError):
        return False


def refresh(root, now, execute=False, items=None):
    """At most one paid call a day; writes cache/benefit_pick/pick.json (AI pick, rule pick or None)."""
    root = Path(root).resolve()
    if items is None:
        from . import publish
        try:
            items = publish.payload(root, now)['items']
        except Exception:  # No fresh report: nothing to pick from, and no model call.
            return {'status': 'no_candidates', 'source': None, 'model': None, 'errors': ['items_unavailable']}
    with lock(project_path(root, 'cache/benefit_pick/.lock')):
        rows = _rows(items, now)
        out = project_path(root, 'cache/benefit_pick/pick.json')
        current = host(items, now)
        if len(rows) < MIN_CANDIDATES:
            save(out, None)
            return {'status': 'no_candidates', 'source': None, 'model': None, 'errors': []}
        state = load(project_path(root, 'cache/benefit_pick/days.json'), {'days': {}})
        day = now.date().isoformat()
        previous = load(out, None)
        pick, model, errors = None, {'status': 'not_requested', 'run_id': None}, []
        if current is not None and execute and day not in state['days']:
            digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            input_path = project_path(root, f'.tools/ai-benefit-inputs/{day}-{digest}.json')
            save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
            # Persist before calling: a crash cannot open another paid attempt today.
            state['days'][day] = {'status': 'attempted', 'input_file': str(input_path.relative_to(root))}
            save(project_path(root, 'cache/benefit_pick/days.json'), state)
            model = invoke(root, 'benefit', input_path)
            if model['status'] == 'validated_draft':
                try:
                    draft = load(TRIAL_RUNS / model['run_id'] / 'result.json', None)
                    errors = review(draft, current)
                    if not errors:
                        pick = dict(schema_version=1, generated_at=now.isoformat(), day=day, source='ai',
                                    summary=draft['summary'], picks=draft['picks'])
                except (OSError, ValueError, KeyError, TypeError):
                    errors = ['draft_unreadable']
            state['days'][day].update(model)
            save(project_path(root, 'cache/benefit_pick/days.json'), state)
        elif isinstance(previous, dict) and _keep(previous, day, now):
            pick = previous  # Publication re-checks it against the live items.
        pick = pick or rule_pick(_input(rows, now), now)
        save(out, pick)
        return {'status': 'completed', 'source': pick['source'], 'model': model, 'errors': errors}
