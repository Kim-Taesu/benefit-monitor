"""Weekly grocery pick: Haiku writes a short summary over code-chosen bargains; code checks every word that matters.

Approved 2026-11-09 (B안): the model's summary and menu suggestions may be published with an "AI 작성" label,
only after review() confirms every number belongs to the item named right before it, every named item is a
candidate, and no health or sale claim appears. Prices on the page are always drawn from the groceries bundle.
Any failure falls back to rule_pick(): the biggest discounts, no model text.
"""
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re

from .ai_review import invoke
from .official_reader import project_path
from .store import load, lock, save, save_text

TRIAL_RUNS = Path(__file__).resolve().parents[1] / '.tools/claude-trial/live/runs'

MAX_PRODUCE = 12
MIN_PRODUCE = 3
CHEAP_PCT = -10
MEAT_ORDER = ('돼지 삼겹살', '돼지 목심', '돼지 앞다리', '한우 등심', '한우 양지', '닭(육계)', '계란 특란 30구')
MAX_MEAT = 6
RULE_PICKS = 5
SUMMARY_MIN, SUMMARY_MAX = 20, 220
MENU = re.compile(r'[가-힣][가-힣 ·]{0,15}')
FORBIDDEN = ('효능', '건강', '다이어트', '면역', '질병', '치료', '예방', '항암', '혈압', '당뇨', '최저가', '무조건',
             '보장', '특가', '할인행사', '세일', '쿠폰', '1+1')
PARTICLES = set('은는이가을를와과도로의만랑나까에보부처')
# Generic meat words: a sentence that says 싸다/저렴 may not contain any of them (meat has no 평년).
MEAT_WORDS = ('고기', '돼지', '소고기', '한우', '닭', '계란', '달걀', '삼겹', '목심', '등심', '앞다리', '양지', '갈비', '육계')
QUANTITY_UNITS = ('kg', 'g', '개', '포기', '마리', '구', '손', '봉', '장', '년')
NUMBER = re.compile(r'(\d[\d,]*)\s*(%|원|' + '|'.join(QUANTITY_UNITS) + ')?')
PICK_FIELDS = {'schema_version', 'generated_at', 'survey_date', 'source', 'summary', 'picks'}
TAKEDOWN_KIND = 'grocery_pick_text'


def _hangul(ch):
    return '가' <= ch <= '힣'


def candidates(bundle):
    """(survey_date, candidates) from a sanitized groceries bundle; produce first, by discount."""
    produce = (bundle or {}).get('produce') or {}
    best = {}
    for row in produce.get('items', []):
        prev = best.get(row['item'])
        if prev is None or (row['grade'] == '상품' and prev['grade'] != '상품'):
            best[row['item']] = row
    cheap = []
    for row in best.values():
        price = row['today'] if row['today'] is not None else row['day_ago']
        base, base_price = ('평년', row['normal']) if row['normal'] else ('1년전', row['year_ago'])
        if not price or not base_price:
            continue
        pct = math.floor((price / base_price - 1) * 100 + 0.5)  # half up, like the browser's Math.round
        if pct <= CHEAP_PCT:
            cheap.append(dict(id=row['id'], kind='produce', name=row['item'],
                              detail=row['kind'] if row['kind'] != row['item'] else '', unit=row['unit'],
                              price=price, base=base, base_price=base_price, pct=pct))
    cheap.sort(key=lambda c: (c['pct'], c['name']))
    meats, seen = [], set()
    for row in sorted(((bundle or {}).get('meat') or {}).get('items', []),
                      key=lambda r: MEAT_ORDER.index(r['cut']) if r['cut'] in MEAT_ORDER else len(MEAT_ORDER)):
        if row['cut'] in MEAT_ORDER and row['cut'] not in seen and len(meats) < MAX_MEAT:
            seen.add(row['cut'])
            meats.append(dict(id=row['id'], kind='meat', name=row['cut'], detail=row['label'], unit=row['unit'],
                              price=row['national']))
    return produce.get('survey_date'), cheap[:MAX_PRODUCE] + meats


def host(bundle, now):
    """Model input, or None when there are too few bargains to be worth a paid call."""
    survey, rows = candidates(bundle)
    if not survey or sum(c['kind'] == 'produce' for c in rows) < MIN_PRODUCE:
        return None
    return dict(schema_version='grocery-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                survey_date=survey, candidates=rows)


def _aliases(candidate):
    names = {candidate['name']}
    if candidate['kind'] == 'produce':
        if candidate['detail'] and candidate['name'] in candidate['detail']:
            names.add(candidate['detail'])  # 파 / 대파
    else:
        for token in re.sub(r'\(.*?\)', '', candidate['name']).split():
            if not re.search(r'\d', token) and token not in ('한우', '돼지', '수입', '소'):
                names.add(token)  # 돼지 삼겹살 -> 삼겹살, 닭(육계) -> 닭, 계란 특란 30구 -> 계란
    return names


def _mentions(text, dictionary):
    """[(start, end, name)] by longest match; one-letter names need a word boundary (배 in 배추 is not 배)."""
    names = sorted(dictionary, key=len, reverse=True)
    found, i = [], 0
    while i < len(text):
        for name in names:
            if text.startswith(name, i):
                if len(name) == 1:
                    before = text[i - 1] if i else ' '
                    after = text[i + 1] if i + 1 < len(text) else ' '
                    if _hangul(before) or (_hangul(after) and after not in PARTICLES):
                        continue
                found.append((i, i + len(name), name))
                i += len(name)
                break
        else:
            i += 1
    return found


def review(draft, host, known_names=()):
    """Error codes; empty means the draft may be published. known_names: every item name in the bundle."""
    if not isinstance(draft, dict) or set(draft) != {'summary', 'picks'} or not isinstance(draft['summary'], str) \
            or not isinstance(draft['picks'], list) \
            or not all(isinstance(p, dict) and set(p) == {'id', 'menu'} and isinstance(p['id'], str)
                       and isinstance(p['menu'], str) for p in draft['picks']):
        return ['draft_shape']
    errors = []
    by_id = {c['id']: c for c in host['candidates']}
    ids = [p['id'] for p in draft['picks']]
    if not 3 <= len(ids) <= 5:
        errors.append('picks_count')
    if any(i not in by_id for i in ids):
        errors.append('picks_unknown')
    if len(set(ids)) != len(ids):
        errors.append('picks_duplicate')
    if any(not MENU.fullmatch(p['menu']) or any(w in p['menu'] for w in FORBIDDEN) for p in draft['picks']):
        errors.append('picks_menu')
    if sum(by_id.get(i, {}).get('kind') == 'produce' for i in set(ids)) < 2:
        errors.append('picks_produce')
    text = draft['summary']
    if not SUMMARY_MIN <= len(text) <= SUMMARY_MAX:
        errors.append('summary_length')
    if re.search(r'[<>\n\r]|https?:|www\.', text):
        errors.append('summary_markup')
    if any(word in text for word in FORBIDDEN):
        errors.append('summary_claim')
    owner = {}
    for c in host['candidates']:
        for name in _aliases(c):
            owner[name] = c
    dictionary = set(owner) | {n for n in known_names if isinstance(n, str) and n and not re.search(r'\d', n)}
    mentions = _mentions(text, dictionary)
    if any(name not in owner for _, _, name in mentions):
        errors.append('summary_item')  # Approved rule: only candidate items may be named.
    spans = [(s, e) for s, e, _ in mentions]

    def before(pos):
        named = [owner.get(name) for s, e, name in mentions if e <= pos]
        return named[-1] if named else None

    for match in NUMBER.finditer(text):
        if any(s <= match.start() < e for s, e in spans):
            continue
        item, unit = before(match.start()), match.group(2)
        value = int(match.group(1).replace(',', ''))
        if item is None:
            errors.append('summary_number')
            break
        if unit == '%':
            ok = item['kind'] == 'produce' and value == -item['pct']
        elif unit in (None, '원'):
            ok = value in (item['price'], item.get('base_price'))
        elif unit == '년':
            ok = value == 1 and item.get('base') == '1년전'
        else:
            ok = f'{value}{unit}' == item['unit'].split('/')[-1]
        if not ok:
            errors.append('summary_number')
            break
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        if re.search('싸|저렴', sentence) and any(word in sentence for word in MEAT_WORDS):
            errors.append('summary_cheap_meat')
            break
    return errors


def known_names(bundle):
    """Every item and cut name in the bundle, so a summary cannot name a non-candidate item."""
    names = set()
    for row in ((bundle or {}).get('produce') or {}).get('items', []):
        names.add(row['item'])
        if row['item'] in row['kind']:
            names.add(row['kind'])
    for row in ((bundle or {}).get('meat') or {}).get('items', []):
        names |= _aliases(dict(kind='meat', name=row['cut']))
    return names


def rule_pick(host, now):
    """No model text: the biggest discounts."""
    produce = [c for c in host['candidates'] if c['kind'] == 'produce'][:RULE_PICKS]
    return dict(schema_version=1, generated_at=now.isoformat(), survey_date=host['survey_date'], source='rule',
                summary=None, picks=[dict(id=c['id'], menu=None) for c in produce])


def muted(takedowns, survey_date):
    return any(isinstance(t, dict) and t.get('kind') == TAKEDOWN_KIND and t.get('survey_date') == survey_date
               for t in takedowns or [])


def apply_mute(pick, bundle, takedowns):
    """Admin mute for that survey day: the same rule card on every publish path (no model text, top discounts)."""
    if not isinstance(pick, dict) or pick.get('source') != 'ai' or not muted(takedowns, pick.get('survey_date')):
        return pick
    try:
        generated = datetime.fromisoformat(pick['generated_at'])
        current = host(bundle, generated)
        return rule_pick(current, generated) if current is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def public(pick, bundle, takedowns, now):
    """Re-check a stored pick against the same groceries bundle; None when it cannot be shown today."""
    try:
        current = host(bundle, now)
        if current is None or not isinstance(pick, dict) or set(pick) != PICK_FIELDS or pick['schema_version'] != 1 \
                or pick['survey_date'] != current['survey_date'] or pick['source'] not in ('ai', 'rule'):
            return None
        generated = datetime.fromisoformat(pick['generated_at'])
        if generated.tzinfo is None or generated > now:
            return None
        produce = {c['id'] for c in current['candidates'] if c['kind'] == 'produce'}
        if pick['source'] == 'ai':
            draft = dict(summary=pick['summary'], picks=pick['picks'])
            if review(draft, current, known_names(bundle)):
                return rule_pick(current, generated)
            return apply_mute(dict(pick, picks=[dict(p) for p in pick['picks']]), bundle, takedowns)
        if pick['summary'] is not None or not isinstance(pick['picks'], list) or not 1 <= len(pick['picks']) <= RULE_PICKS \
                or any(not isinstance(p, dict) or set(p) != {'id', 'menu'} or p['menu'] is not None
                       or p['id'] not in produce for p in pick['picks']):
            return rule_pick(current, generated)
        return dict(pick, picks=[dict(p) for p in pick['picks']])
    except (KeyError, TypeError, ValueError):
        return None


def refresh(root, now, execute=False):
    """At most one paid call a day; writes cache/grocery_pick/pick.json (AI pick, rule pick or None)."""
    from .groceries import sanitize
    root = Path(root).resolve()
    with lock(project_path(root, 'cache/grocery_pick/.lock')):
        bundle = sanitize(load(project_path(root, 'cache/groceries.json'), None), now)
        current = host(bundle, now)
        out = project_path(root, 'cache/grocery_pick/pick.json')
        if current is None:
            save(out, None)
            return {'status': 'no_candidates', 'source': None, 'model': None, 'errors': []}
        state = load(project_path(root, 'cache/grocery_pick/days.json'), {'days': {}})
        day = now.date().isoformat()
        previous = load(out, None)
        pick, model, errors = None, {'status': 'not_requested', 'run_id': None}, []
        if execute and day not in state['days']:
            digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            input_path = project_path(root, f'.tools/ai-grocery-inputs/{day}-{digest}.json')
            save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
            # Persist before calling: a crash cannot open another paid attempt today.
            state['days'][day] = {'status': 'attempted', 'input_file': str(input_path.relative_to(root))}
            save(project_path(root, 'cache/grocery_pick/days.json'), state)
            model = invoke(root, 'grocery', input_path)
            if model['status'] == 'validated_draft':
                try:
                    draft = load(TRIAL_RUNS / model['run_id'] / 'result.json', None)
                    errors = review(draft, current, known_names(bundle))
                    if not errors:
                        pick = dict(schema_version=1, generated_at=now.isoformat(), survey_date=current['survey_date'],
                                    source='ai', summary=draft['summary'], picks=draft['picks'])
                except (OSError, ValueError, KeyError, TypeError):
                    errors = ['draft_unreadable']
            state['days'][day].update(model)
            save(project_path(root, 'cache/grocery_pick/days.json'), state)
        elif isinstance(previous, dict) and previous.get('survey_date') == current['survey_date']:
            pick = previous  # Same survey day: keep the earlier pick; publication re-checks it.
        pick = pick or rule_pick(current, now)
        save(out, pick)
        return {'status': 'completed', 'source': pick['source'], 'model': model, 'errors': errors}
