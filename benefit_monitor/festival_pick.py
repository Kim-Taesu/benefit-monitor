"""Weekly festival pick: Haiku writes a short summary over code-chosen festivals; code checks every word that matters.

Approved 2026-11-14 (same exception as grocery_pick): the model's summary and one-line notes may be published with an
"AI 작성" label, only after review() confirms every number belongs to the festival it describes, every named festival
is a candidate, "무료" matches the listed fee status and no guarantee or sale claim appears. Names, dates, regions and
fees on the page always come from the festivals bundle. Any failure falls back to rule_pick(): no model text.
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

WINDOW_DAYS = 9
MAX_PICKS = 5
MIN_CANDIDATES = 2
MAX_AGE_HOURS = 36
TAKEDOWN_KIND = 'festival_pick_text'
METRO = ('서울특별시', '경기도', '인천광역시')
SUMMARY_MIN, SUMMARY_MAX = 20, 200
LINE_MIN, LINE_MAX = 1, 40
MARKUP = re.compile(r'[<>\x00-\x1f]|https?:|www\.')  # control chars too: the page rejects them
# The page shows each festival's dates, so text never says when (2026-11-14 review).
RELATIVE = re.compile(r'오늘|내일|모레|어제|이번\s?주|다음\s?주|주말|평일|마지막\s?날|막바지|곧|임박|서두르|서둘러')
FORBIDDEN = ('보장', '무조건', '최저가', '확실', '선착순', '매진', '완판', '100%')
PICK_FIELDS = {'schema_version', 'generated_at', 'day', 'source', 'summary', 'picks'}


def _candidates(bundle, now):
    """Festivals still running or starting within WINDOW_DAYS, metro first, then by start date."""
    today = now.date().isoformat()
    last = (now.date() + timedelta(days=WINDOW_DAYS)).isoformat()
    rows = []
    for row in (bundle or {}).get('items', []):
        if row['end'] >= today and row['start'] <= last:
            rows.append(dict(id=row['id'], name=row['name'], start=row['start'], end=row['end'], region=row['region'],
                             metro=row['region'].startswith(METRO), fee_status=row['fee_status'],
                             fee_text=row['fee_text'][:60], programs=row['programs'][:120]))
    rows.sort(key=lambda c: (not c['metro'], c['start'], c['name']))
    return rows


def _input(rows, now):
    return dict(schema_version='festival-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                day=now.date().isoformat(), candidates=rows)


def host(bundle, now):
    """Model input, or None when there are too few festivals to be worth a paid call."""
    rows = _candidates(bundle, now)
    return _input(rows, now) if len(rows) >= MIN_CANDIDATES else None


def known_names(bundle):
    """Every festival name in the bundle, so a summary cannot name one that is not a candidate."""
    return {row['name'] for row in (bundle or {}).get('items', []) if row.get('name')}


DATE = re.compile(r'(\d{1,2})\s*/\s*(\d{1,2})(?:\s*~\s*(?:(\d{1,2})\s*/\s*)?(\d{1,2}))?'
                  r'|(\d{1,2})월\s*(\d{1,2})일(?:\s*~\s*(?:(\d{1,2})월\s*)?(\d{1,2})일)?')
AMOUNT = re.compile(r'(\d[\d,]*)\s*(%|[가-힣])?')
FREE_WORDS = ('무료', '공짜', '무상', '입장료 없', '0원')
FREE = re.compile('|'.join(r'(?<![\d,])0원' if w == '0원' else w for w in FREE_WORDS))
NOT_PAID = re.compile(r'유료(?!.{0,4}아[님니])')
NEGATED = re.compile(r'[무유]료.{0,4}아[님니]')  # '무료 아님', '일부 유료가 아니에요'


def _mentions(text, rows):
    """[(end, candidate)] for every occurrence of a candidate name, in text order."""
    found = []
    for c in rows:
        for m in re.finditer(re.escape(c['name']), text):
            found.append((m.end(), len(c['name']), c))
    return [(end, c) for end, _, c in sorted(found, key=lambda f: (f[0], f[1]))]


def _owner_before(mentions, pos):
    named = [c for end, c in mentions if end <= pos]
    return named[-1] if named else None


def _fee_norm(text):
    return re.sub(r'(\d)\s+(%|[가-힣])', r'\1\2', re.sub(r'(?<=\d),(?=\d)', '', text))


def _numbers_ok(text, rows, fixed=None):
    """Dates must equal the owning festival's start or end; any other number needs its unit verbatim in its fee_text.

    Owner: `fixed` (a line is about one festival), else the nearest candidate name before the number."""
    mentions = [] if fixed else _mentions(text, rows)
    for m in DATE.finditer(text):
        c = fixed or _owner_before(mentions, m.start())
        if c is None:
            return False
        g = m.groups()
        month, day = (g[0], g[1]) if g[0] else (g[4], g[5])
        end_month, end_day = ((g[2] or month, g[3]) if g[0] else (g[6] or month, g[7]))
        pairs = [(int(month), int(day))] + ([(int(end_month), int(end_day))] if end_day else [])
        dates = {key: tuple(int(v) for v in c[key].split('-')[1:]) for key in ('start', 'end')}
        if any(pair not in dates.values() for pair in pairs):
            return False
        after = text[m.end():m.end() + 2]
        if len(pairs) == 1 and ((after == '까지' and pairs[0] != dates['end'])
                                or (after == '부터' and pairs[0] != dates['start'])):
            return False
    rest = DATE.sub(lambda m: ' ' * (m.end() - m.start()), text)
    for m in AMOUNT.finditer(rest):
        c = fixed or _owner_before(mentions, m.start())
        token = m.group(1).replace(',', '') + (m.group(2) or '')
        if c is None or not re.search(r'(?<!\d)' + re.escape(token) + r'(?!\d)', _fee_norm(c['fee_text'])):
            return False
    return True


def _free_ok(candidate, text):
    """A festival may be called free when its status is free, or mixed and the same line or summary sentence
    says part of it is paid."""
    if candidate['fee_status'] == 'free':
        return True
    if candidate['fee_status'] != 'mixed':
        return False
    return '일부' in text and bool(NOT_PAID.search(text))


def _sentence(text, pos):
    start = max(text.rfind(ch, 0, pos) for ch in '.!?') + 1
    ends = [i for i in (text.find(ch, pos) for ch in '.!?') if i >= 0]
    return text[start:min(ends) if ends else len(text)]


def _check(summary, picks, host, known):
    """Error codes for picks (and the summary when not None); picks must already have the right shape."""
    errors = []
    by_id = {c['id']: c for c in host['candidates']}
    ids = [p['id'] for p in picks]
    if not 1 <= len(ids) <= min(MAX_PICKS, len(by_id)):
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
    if any(word in t for t in texts for word in FORBIDDEN):
        errors.append('claim')
    if any(RELATIVE.search(t) for t in texts):
        errors.append('relative')
    if summary is not None:
        rest = summary
        for name in sorted((c['name'] for c in host['candidates']), key=len, reverse=True):
            rest = rest.replace(name, ' ')
        if any(n in rest for n in known if isinstance(n, str) and n):
            errors.append('summary_item')
    if any(not _numbers_ok(p['line'], [], by_id[p['id']]) for p in picks if p['id'] in by_id) \
            or (summary is not None and not _numbers_ok(summary, host['candidates'])):
        errors.append('number')
    free_bad = any(FREE.search(p['line']) and not _free_ok(by_id[p['id']], p['line'])
                   for p in picks if p['id'] in by_id)
    if summary is not None:
        mentions = _mentions(summary, host['candidates'])
        for m in FREE.finditer(summary):
            owner = _owner_before(mentions, m.start())
            if owner is None or not _free_ok(owner, _sentence(summary, m.start())):
                free_bad = True
    if any(NEGATED.search(t) for t in texts):
        free_bad = True
    if free_bad:
        errors.append('free')
    return errors


def review(draft, host, known_names=()):
    """Error codes; empty means the draft may be published. known_names: every festival name in the bundle."""
    if not isinstance(draft, dict) or set(draft) != {'summary', 'picks'} or not isinstance(draft['summary'], str) \
            or not isinstance(draft['picks'], list) \
            or not all(isinstance(p, dict) and set(p) == {'id', 'line'} and isinstance(p['id'], str)
                       and isinstance(p['line'], str) for p in draft['picks']):
        return ['draft_shape']
    return _check(draft['summary'], draft['picks'], host, known_names)


def rule_pick(host, now):
    """No model text: metro first, then the soonest start."""
    return dict(schema_version=1, generated_at=now.isoformat(), day=host['day'], source='rule', summary=None,
                picks=[dict(id=c['id'], line=None) for c in host['candidates'][:MAX_PICKS]])


def muted(takedowns, day):
    return any(isinstance(t, dict) and t.get('kind') == TAKEDOWN_KIND and t.get('day') == day for t in takedowns or [])


def apply_mute(pick, bundle, takedowns, now=None):
    """Admin mute for that day: the same rule card on every publish path (no model text)."""
    if not isinstance(pick, dict) or pick.get('source') != 'ai' or not muted(takedowns, pick.get('day')):
        return pick
    try:
        at = now or datetime.fromisoformat(pick['generated_at'])
        rows = _candidates(bundle, at)
        return rule_pick(_input(rows, at), at) if rows else None
    except (KeyError, TypeError, ValueError):
        return None


def public(pick, bundle, takedowns, now):
    """Re-check a stored pick against the same festivals bundle; None when it cannot be shown today."""
    try:
        if not isinstance(pick, dict) or set(pick) != PICK_FIELDS or pick['schema_version'] != 1 \
                or pick['source'] not in ('ai', 'rule') or not isinstance(pick['picks'], list) \
                or not isinstance(pick['day'], str):
            return None
        generated = datetime.fromisoformat(pick['generated_at'])
        if generated.tzinfo is None or generated > now:
            return None
        rows = _candidates(bundle, now)
        if not rows:
            return None
        current = _input(rows, now)
        if len(rows) < MIN_CANDIDATES:
            return rule_pick(current, now)  # Too few for a paid call, but the survivors still make a rule card.
        ids = {c['id'] for c in rows}
        if not all(isinstance(p, dict) and set(p) == {'id', 'line'} and isinstance(p['id'], str) for p in pick['picks']):
            return rule_pick(current, now)
        if pick['source'] == 'rule':
            return rule_pick(current, now)  # No model text: always today's candidates.
        if not (pick['summary'] is None or isinstance(pick['summary'], str)) \
                or any(not isinstance(p['line'], str) for p in pick['picks']) \
                or now - generated > timedelta(hours=MAX_AGE_HOURS):
            return rule_pick(current, now)
        kept = [dict(p) for p in pick['picks'] if p['id'] in ids]
        dropped = len(kept) < len(pick['picks'])
        if dropped and len(kept) < min(3, len(pick['picks'])) or not kept:
            return rule_pick(current, now)
        summary = None if dropped else pick['summary']  # None already: an earlier re-check dropped a line.
        if _check(summary, kept, current, known_names(bundle)):
            return rule_pick(current, now)
        return apply_mute(dict(pick, summary=summary, picks=kept), bundle, takedowns, now)
    except (KeyError, TypeError, ValueError):
        return None


def refresh(root, now, execute=False):
    """At most one paid call a day; writes cache/festival_pick/pick.json (AI pick, rule pick or None)."""
    from .festivals import sanitize
    root = Path(root).resolve()
    with lock(project_path(root, 'cache/festival_pick/.lock')):
        bundle = sanitize(load(project_path(root, 'cache/festivals.json'), None), now)
        rows = _candidates(bundle, now)
        out = project_path(root, 'cache/festival_pick/pick.json')
        current = host(bundle, now)
        if not rows:
            save(out, None)
            return {'status': 'no_candidates', 'source': None, 'model': None, 'errors': []}
        state = load(project_path(root, 'cache/festival_pick/days.json'), {'days': {}})
        day = now.date().isoformat()
        previous = load(out, None)
        pick, model, errors = None, {'status': 'not_requested', 'run_id': None}, []
        if current is not None and execute and day not in state['days']:
            digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            input_path = project_path(root, f'.tools/ai-festival-inputs/{day}-{digest}.json')
            save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
            # Persist before calling: a crash cannot open another paid attempt today.
            state['days'][day] = {'status': 'attempted', 'input_file': str(input_path.relative_to(root))}
            save(project_path(root, 'cache/festival_pick/days.json'), state)
            model = invoke(root, 'festival', input_path)
            if model['status'] == 'validated_draft':
                try:
                    draft = load(TRIAL_RUNS / model['run_id'] / 'result.json', None)
                    errors = review(draft, current, known_names(bundle))
                    if not errors:
                        pick = dict(schema_version=1, generated_at=now.isoformat(), day=day, source='ai',
                                    summary=draft['summary'], picks=draft['picks'])
                except (OSError, ValueError, KeyError, TypeError):
                    errors = ['draft_unreadable']
            state['days'][day].update(model)
            save(project_path(root, 'cache/festival_pick/days.json'), state)
        elif isinstance(previous, dict) and _keep(previous, day, now):
            pick = previous  # Publication re-checks it against the live bundle.
        pick = pick or rule_pick(_input(rows, now), now)
        save(out, pick)
        return {'status': 'completed', 'source': pick['source'], 'model': model, 'errors': errors}


def _keep(previous, day, now):
    try:
        if previous.get('day') == day:
            return True
        return previous.get('source') == 'ai' \
            and now - datetime.fromisoformat(previous['generated_at']) <= timedelta(hours=MAX_AGE_HOURS)
    except (KeyError, TypeError, ValueError):
        return False
