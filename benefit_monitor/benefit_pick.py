"""Weekly benefit pick: Haiku writes a short summary over published benefits; code checks every word that matters.

Approved 2026-11-14 (same exception as grocery_pick and festival_pick): the model's summary and one-line notes may be
published with an "AI 작성" label, only after review() confirms every date and number belongs to the benefit it
describes and no guarantee, eligibility or stock claim appears. Cost words (free or paid) are allowed since
2026-11-18 (user decision); the page still shows each line's fee_status from the data, so a line may not call a paid
or unknown benefit free. Titles, links and conditions on the page always come from the published items. Any failure falls
back to rule_pick(): no model text. A pick never changes which benefits are published or their order.
"""
from datetime import timedelta
import hashlib
from pathlib import Path
import re

from . import pick_common as common
from .ai_review import invoke
from .official_reader import project_path
from .store import load, lock, save

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
MARKUP = re.compile(r'[<>\x00-\x1f]|https?:|www\.')  # control chars too: the page rejects them
CLAIMS = ('누구나', '받을 수 있', '확실', '보장', '무조건', '100%', '최대', '누구든', '전원', '반드시', '신청하면', '바로 받',
          '모두 받')
STOCK = ('남은', '잔여', '소진 전', '자리 있')
# The page shows the deadline; text never pushes (2026-11-14 review).
URGENCY = re.compile(r'임박|곧\s?끝|곧\s?마감|막바지|서두르|서둘러|마지막|놓치기\s?전')


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


# 2026-11-18: cost words are allowed (user decision). Amounts stay numbers, also when spelled out.
SPELLED = re.compile(r'퍼센트|[천만억]\s*원')
# A line belongs to one benefit and sits beside its fee_status: it may not call a paid or unknown benefit free,
# in any wording (PR #67 review: 'FREE', '비용이 없어요', '돈 안 들어요', '결제 없이').
FREE = re.compile(r'무료|공짜|무상|free|(?:비용|돈)\s*(?:이|은|도)?\s*(?:없|안\s*들|안\s*드)'
                  r'|(?:결제|구매)\s*(?:없이|안\s*해도|하지\s*않아도)', re.IGNORECASE)
DIGITS = re.compile('[0-9\uff10-\uff19]')
# Approved 2026-11-19 (user "123 진행"): a number glued to a word of the benefit's own title names it
# ("5060세대", "9호점") and may be copied. A word starting with a unit (date, time, amount, age, count,
# rank) is a quantity and stays banned even in a title ("60초", "1천만원", "11월", "19세"); a percent too.
TITLE_NUMBER = re.compile(r'(?<![0-9.,])([0-9][0-9,.]*)\s*([가-힣]+)')
UNITS = ('원', '만', '천', '억', '월', '일', '년', '시', '분', '초', '세', '살', '명', '회', '번', '개', '건', '곳', '차', '주',
         '박', '층', '종', '가지', '대', '석', '장', '권', '편', '등', '위', '평', '인', '부', '달', '배', '퍼센트')
# '세대' (generation) starts with the age unit '세' but is a name.
NAME_WORDS = ('세대',)
PARTICLE = re.compile(r'(?:의|은|는|이|가|을|를|에|와|과|도|로|으로|에서|까지|부터)$')
RELATIVE = re.compile(r'오늘|내일|모레|이번\s?주|다음\s?주|주말|월말|연말')
QUOTED = re.compile(r"['\"‘’“”]([^'\"‘’“”]{2,})['\"‘’“”]")
WORD = re.compile(r'[0-9A-Za-z가-힣]+')
NAME_MIN = 2
GENERIC = ('혜택', '행사', '안내', '서비스', '프로그램', '이벤트', '신청', '이용', '운영', '서울', '무료', '공짜', '무상')


def _names(rows):
    """{candidate id: distinctive title parts}: quoted text plus title words of 2+ characters unique to that title."""
    words = {c['id']: {w for w in WORD.findall(c['title']) if len(w) >= NAME_MIN and not any(g in w for g in GENERIC)} for c in rows}
    names = {}
    for c in rows:
        quoted = [q.strip() for q in QUOTED.findall(c['title'])]
        unique = {w for w in words[c['id']] if sum(w in other for other in words.values()) == 1}
        names[c['id']] = set(quoted) | unique or {c['title']}
    return names


def _title_numbers(title):
    """(number, word) pairs of a title where the word is a name, not a unit: ('5060', '세대'), ('9', '호점')."""
    pairs = set()
    for number, word in TITLE_NUMBER.findall(title):
        word = PARTICLE.sub('', word) or word
        if word.startswith(NAME_WORDS) or not word.startswith(UNITS):
            pairs.add((number, word))
    return pairs


def _without_title_numbers(text, titles):
    """text with every title name number ("5060 세대" for title "5060세대의 …") blanked out."""
    for number, word in set().union(*(_title_numbers(t) for t in titles)) if titles else ():
        text = re.sub(r'(?<![0-9.,])' + re.escape(number) + r'\s*' + re.escape(word), ' ', text)
    return text


def _mentions(text, rows):
    """[(end, candidate)] for every occurrence of a distinctive title part, in text order."""
    names = _names(rows)
    found = []
    for c in rows:
        for name in names[c['id']]:
            for m in re.finditer(re.escape(name), text):
                found.append((m.end(), len(name), c))
    return [(end, c) for end, _, c in sorted(found, key=lambda f: (f[0], f[1]))]


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
    if any(URGENCY.search(t) for t in texts):
        errors.append('urgency')
    # Dates, amounts and deadlines are shown by the page from the data, never typed by the model.
    # A line may copy its own benefit's title numbers, the summary those of the picked benefits.
    picked_titles = [by_id[i]['title'] for i in ids if i in by_id]
    scoped = [_without_title_numbers(p['line'], [(by_id.get(p['id']) or {}).get('title', '')]) for p in picks]
    if summary is not None:
        scoped.append(_without_title_numbers(summary, picked_titles))
    if any(DIGITS.search(s) for s in scoped) or any(SPELLED.search(t) or RELATIVE.search(t) for t in texts):
        errors.append('number')
    if any(FREE.search(p['line']) and (by_id.get(p['id']) or {}).get('fee_status') != 'free' for p in picks):
        errors.append('free')
    if summary is not None and any(c['id'] not in ids for _, c in _mentions(summary, host['candidates'])):
        errors.append('summary_item')
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
    return common.muted(takedowns, TAKEDOWN_KIND, day)


def apply_mute(pick, items, takedowns, now):
    """Admin mute for that day: the same rule card on every publish path (no model text)."""
    if not isinstance(pick, dict) or pick.get('source') != 'ai' or not muted(takedowns, pick.get('day')):
        return pick
    rows = _rows(items, now)
    return rule_pick(_input(rows, now), now) if len(rows) >= MIN_CANDIDATES else None


def _fill(pick, items):
    """Public lines: {'id','source','url','line'} taken from the current items."""
    by_id = {item_id(row): row for row in items or []}
    lines = [dict(id=p['id'], source=by_id[p['id']]['source'], url=by_id[p['id']]['url'], line=p['line'])
             for p in pick['picks'] if p['id'] in by_id]
    return dict(pick, picks=lines) if lines else None


def _public(pick, items, takedowns, now):
    generated = common.stored_header(pick, now)
    if generated is None:
        return None
    rows = _rows(items, now)
    if len(rows) < MIN_CANDIDATES:
        return None  # Below the 3-line floor a recommendation adds nothing.
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
    if dropped and len(kept) < min(3, len(pick['picks'])) or not kept:
        return rule_pick(current, now)
    summary = None if dropped else pick['summary']  # None already: an earlier re-check dropped a line.
    if _check(summary, kept, current):
        return rule_pick(current, now)
    return apply_mute(dict(pick, summary=summary, picks=kept), items, takedowns, now)


def _stored_form(pick):
    """A public pick (lines with source/url) back to its stored form, so every publish path can re-check it.
    A line whose source/url does not hash to its id is left as is and fails the shape check (rule card)."""
    if not isinstance(pick, dict) or not isinstance(pick.get('picks'), list):
        return pick
    lines = []
    for p in pick['picks']:
        if isinstance(p, dict) and set(p) == {'id', 'source', 'url', 'line'} \
                and p['id'] == item_id({'source': p['source'], 'url': p['url']}):
            p = {'id': p['id'], 'line': p['line']}
        lines.append(p)
    return dict(pick, picks=lines)


def public(pick, items, takedowns, now):
    """Re-check a stored (or already public) pick against the current items; None when it cannot be shown today."""
    try:
        result = _public(_stored_form(pick), items, takedowns, now)
        return _fill(result, items) if result else None
    except (KeyError, TypeError, ValueError):
        return None


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
        previous = load(out, None)
        pick, model, errors = None, {'status': 'not_requested', 'run_id': None}, []
        if current is not None and execute and not common.already_tried(root, 'benefit_pick', now):
            pick, model, errors = common.daily_draft(root, 'benefit_pick', 'benefit', current,
                                                     lambda draft: review(draft, current), now, invoke, TRIAL_RUNS)
        elif isinstance(previous, dict) and common.keep(previous, now.date().isoformat(), now, MAX_AGE_HOURS):
            pick = previous  # Publication re-checks it against the live items.
        pick = pick or rule_pick(_input(rows, now), now)
        save(out, pick)
        # detail: kept for the run summary's shape (pick_report); price words are no longer a rejection (2026-11-18).
        return {'status': 'completed', 'source': pick['source'], 'model': model, 'errors': errors, 'detail': []}
