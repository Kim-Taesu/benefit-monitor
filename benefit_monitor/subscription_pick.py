"""Weekly 청약 pick: Haiku writes a short summary over code-chosen complexes; code checks every word that matters.

Approved 2026-11-18 (same exception as festival_pick and benefit_pick): the model's summary and one-line notes may be
published with an "AI 작성" label, only after review() confirms there is no number, no time word, no eligibility,
odds or price judgement, no complex outside the picks, and that every region, supply type, special-supply kind and
regulation word belongs to the complexes picked. Names, dates, prices and links on the page always come from the
subscriptions bundle. Any failure falls back to rule_pick(): no model text.
"""
from datetime import timedelta
from pathlib import Path
import re

from . import pick_common as common
from .ai_review import invoke
from .official_reader import project_path
from .store import load, lock, save

TRIAL_RUNS = Path(__file__).resolve().parents[1] / '.tools/claude-trial/live/runs'

MAX_PICKS = 5
RULE_PICKS = 3
MIN_CANDIDATES = 2
MAX_AGE_HOURS = 36
TAKEDOWN_KIND = 'subscription_pick_text'
SUMMARY_MIN, SUMMARY_MAX = 20, 200
LINE_MIN, LINE_MAX = 1, 40
MARKUP = re.compile(r'[<>\x00-\x1f]|https?:|www\.')  # control chars too: the page rejects them
DIGITS = re.compile('[0-9０-９]|퍼센트|[천만억]\\s*원')
# The page shows every date with a D-day badge, and a pick stays up to 36 hours.
RELATIVE = re.compile(r'오늘|내일|모레|어제|이번\s?주|다음\s?주|주말|평일|마지막|막바지|곧|임박|마감|서두르|서둘러')
# The page never judges eligibility, odds or price (2026-11-17 approval); neither does the model.
CLAIMS = re.compile(r'당첨|확률|가능성|경쟁|누구나|누구든|보장|무조건|확실|반드시|시세|차익|프리미엄|로또|투자|수익|오를|올라|상승'
                    r'|저렴|싸|이득|줍줍|분양가|가격|금액|통장\s*없|필요\s*없|(?:신청|접수|청약)\s*(?:할|하실)?\s*수\s*있'
                    r'|(?:넣을|받을)\s*수\s*있|(?:신청|청약|접수)\s*가능|통장\S{0,3}\s*없'
                    r'|자격\S{0,2}\s*(?:있|되|돼|됩|충족|갖)|100%')
# Words that say nothing about one complex; every other word taken from the data is a fact checked per pick.
GENERIC = {'아파트', '분양', '접수', '청약', '공급', '일반공급', '등', '기타'}
TOKEN = re.compile(r'[0-9가-힣]+')


# Step and special-supply words are checked even when no candidate still offers them: a step that ended
# (2026-11-24: "특별공급과 1순위·2순위를 열고" the day after 특별공급 closed) is no longer a fact to write.
STEP_WORDS = {'특별공급', '1순위', '2순위', '무순위', '재공급', '임의공급', '사전청약'}
SPECIAL_WORDS = {'신혼부부', '다자녀가구', '다자녀', '노부모부양', '노부모', '생애최초', '기관추천', '신생아'}


def _next_start(item, today):
    return min(s['start'] for s in item['steps'] if s['end'] >= today)


def _candidates(bundle, now):
    """Complexes still taking applications, soonest next receipt first, Seoul before Gyeonggi on the same day.
    Only steps still open today go in; special-supply kinds only while a 특별공급 step is open."""
    today = now.date().isoformat()
    rows = []
    for item in (bundle or {}).get('items', []):
        steps = [dict(label=s['label'], start=s['start'], end=s['end']) for s in item['steps'] if s['end'] >= today]
        if not steps:
            continue
        special_open = any('특별공급' in s['label'] for s in steps)
        rows.append(dict(id=item['id'], name=item['name'], area=item['area'], district=item.get('district') or '',
                         supply=item['supply'], steps=steps, units=item.get('units'),
                         special=[k['name'] for k in item.get('special_kinds') or []] if special_open else [],
                         regulation=list(item.get('regulation') or []), _next=_next_start(item, today)))
    rows.sort(key=lambda c: (c['_next'], c['area'] != '서울', c['name'], c['id']))
    return [{k: v for k, v in c.items() if k != '_next'} for c in rows]


def _input(rows, now):
    return dict(schema_version='subscription-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                day=now.date().isoformat(), candidates=rows)


def host(bundle, now):
    """Model input, or None when there are too few complexes to be worth a paid call."""
    rows = _candidates(bundle, now)
    return _input(rows, now) if len(rows) >= MIN_CANDIDATES else None


def _names(name):
    """The name as published, without its parenthesised parts and up to the first one
    ('부천대장 하우스토리 디센트(부천대장지구 A2BL) 공공분양주택' -> also '부천대장 하우스토리 디센트')."""
    short = re.sub(r'\s+', ' ', re.sub(r'\([^)]*\)', ' ', name)).strip()
    head = name.split('(')[0].strip()
    return {n for n in (name, short, head) if len(n) >= 2}


# Short forms models write (2026-11-18 review): 분당 for 분당구, 화성 for 화성특례시, 다자녀 for 다자녀가구.
SPECIAL_SHORT = {'다자녀가구': '다자녀', '노부모부양': '노부모'}
PLACE_SHORT = re.compile(r'(.{2,}?)(?:특례시|시|군|구)')


def _place_short(token):
    m = None if token.endswith('지구') else PLACE_SHORT.fullmatch(token)
    return m.group(1) if m else None


def _facts(c):
    words = [c['area'], c['district'], c['supply'], *(s['label'] for s in c['steps']), *c['special'], *c['regulation']]
    facts = {t for w in words for t in TOKEN.findall(w or '') if len(t) >= 2 and t not in GENERIC}
    facts |= {_place_short(t) for t in TOKEN.findall(c['district'] or '')} - {None}
    facts |= {SPECIAL_SHORT[k] for k in c['special'] if k in SPECIAL_SHORT}
    return facts


def _strip(text, names):
    for name in sorted(names, key=len, reverse=True):
        text = text.replace(name, ' ')
    return text


def _spans(text, names):
    found = []
    for name in names:
        i = text.find(name)
        while i >= 0:
            found.append((i, i + len(name)))
            i = text.find(name, i + 1)
    return found


def _names_other(text, own, others):
    """Whether text names a complex outside `own`; a match inside an own name ('힐스테이트 OO' within
    '힐스테이트 OO 센트럴') does not count, and an own name inside a longer other name does (PR #67 review)."""
    mine = _spans(text, own)
    return any(not any(a <= i and j <= b for a, b in mine) for i, j in _spans(text, others))


def _scan(text, allowed, vocab, names):
    """Error codes for one text: names are the picked names to remove first, allowed the facts it may use."""
    errors = []
    text = _strip(text, names)
    for word in vocab:
        if word in text:
            if word not in allowed:
                errors.append('fact')
            text = text.replace(word, ' ')
    if DIGITS.search(text):
        errors.append('number')
    if RELATIVE.search(text):
        errors.append('relative')
    if CLAIMS.search(text):
        errors.append('claim')
    return errors


def _check(summary, picks, host):
    """Error codes for picks (and the summary when not None); picks must already have the right shape."""
    errors = []
    rows = host['candidates']
    by_id = {c['id']: c for c in rows}
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
    facts = {c['id']: _facts(c) for c in rows}
    names = {c['id']: _names(c['name']) for c in rows}
    vocab = sorted(set().union(STEP_WORDS, SPECIAL_WORDS, *facts.values()), key=len, reverse=True)
    every_name = set().union(*names.values())
    for p in picks:
        if p['id'] in by_id:
            own = names[p['id']]
            if _names_other(p['line'], own, every_name - own):
                errors.append('line_item')
            errors += _scan(p['line'], facts[p['id']], vocab, own)
    if summary is not None:
        chosen = [i for i in dict.fromkeys(ids) if i in by_id]
        chosen_names = set().union(*(names[i] for i in chosen))
        if _names_other(summary, chosen_names, every_name - chosen_names):
            errors.append('summary_item')
        # A clause's region, supply and special words belong to the complex it names (PR #67 review: swapped facts);
        # a clause naming none may use any picked complex's facts.
        for clause in re.split(r'[.!?,]', summary):
            named = [i for i in chosen if any(n in clause for n in names[i])] or chosen
            errors += _scan(clause, set().union(*(facts[i] for i in named)), vocab, chosen_names)
    return list(dict.fromkeys(errors))


def review(draft, host):
    """Error codes; empty means the draft may be published."""
    if not isinstance(draft, dict) or set(draft) != {'summary', 'picks'} or not isinstance(draft['summary'], str) \
            or not isinstance(draft['picks'], list) \
            or not all(isinstance(p, dict) and set(p) == {'id', 'line'} and isinstance(p['id'], str)
                       and isinstance(p['line'], str) for p in draft['picks']):
        return ['draft_shape']
    return _check(draft['summary'], draft['picks'], host)


def rule_pick(host, now):
    """No model text: the soonest receipts first."""
    return dict(schema_version=1, generated_at=now.isoformat(), day=host['day'], source='rule', summary=None,
                picks=[dict(id=c['id'], line=None) for c in host['candidates'][:RULE_PICKS]])


def muted(takedowns, day):
    return common.muted(takedowns, TAKEDOWN_KIND, day)


def apply_mute(pick, bundle, takedowns, now):
    """Admin mute for that day: the same rule card on every publish path (no model text)."""
    if not isinstance(pick, dict) or pick.get('source') != 'ai' or not muted(takedowns, pick.get('day')):
        return pick
    rows = _candidates(bundle, now)
    return rule_pick(_input(rows, now), now) if rows else None


def public(pick, bundle, takedowns, now):
    """Re-check a stored pick against the same subscriptions bundle; None when it cannot be shown today."""
    try:
        generated = common.stored_header(pick, now)
        if generated is None:
            return None
        rows = _candidates(bundle, now)
        if not rows:
            return None
        current = _input(rows, now)
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
        if not kept:
            return rule_pick(current, now)
        summary = None if dropped else pick['summary']  # The summary may describe a complex that has closed.
        if _check(summary, kept, current):
            return rule_pick(current, now)
        return apply_mute(dict(pick, summary=summary, picks=kept), bundle, takedowns, now)
    except (KeyError, TypeError, ValueError):
        return None


def refresh(root, now, execute=False):
    """At most one paid call a day; writes cache/subscription_pick/pick.json (AI pick, rule pick or None)."""
    from .subscriptions import FILE, sanitize
    root = Path(root).resolve()
    with lock(project_path(root, 'cache/subscription_pick/.lock')):
        bundle = sanitize(load(project_path(root, FILE), None), now)
        rows = _candidates(bundle, now)
        out = project_path(root, 'cache/subscription_pick/pick.json')
        current = host(bundle, now)
        if not rows:
            save(out, None)
            return {'status': 'no_candidates', 'source': None, 'model': None, 'errors': []}
        previous = load(out, None)
        pick, model, errors = None, {'status': 'not_requested', 'run_id': None}, []
        if current is not None and execute and not common.already_tried(root, 'subscription_pick', now):
            pick, model, errors = common.daily_draft(root, 'subscription_pick', 'subscription', current,
                                                     lambda draft: review(draft, current), now, invoke, TRIAL_RUNS)
        elif isinstance(previous, dict) and common.keep(previous, now.date().isoformat(), now, MAX_AGE_HOURS):
            pick = previous  # Publication re-checks it against the live bundle.
        pick = pick or rule_pick(_input(rows, now), now)
        save(out, pick)
        return {'status': 'completed', 'source': pick['source'], 'model': model, 'errors': errors}
