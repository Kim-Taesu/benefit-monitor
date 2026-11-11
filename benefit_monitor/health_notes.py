"""AI recommendation sentences for health-centre year-round programmes (상시 검진·건강관리).

Approved 2026-11-11 (B안): Haiku reads one programme page's stored main text and writes one natural Korean
sentence ("…무료로 받을 수 있어요. 전화로 예약하고 받아보세요") plus the exact page quotes behind it. Code
publishes the sentence with an "AI 작성" label only when review() confirms every quote is in the page,
every number in the sentence is in a quote, 무료/예산/마감 words are backed by quotes, a page that mentions
마감·중단·예산 소진 gets a caution sentence that tells the reader to check, and no forbidden claim appears.
Remaining budget is never claimed. Anything else publishes nothing (the programme link stays).
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
NOTES = 'cache/ai_publish/health_notes.json'          # private: quotes, run ids, attempts
PUBLIC = 'cache/ai_publish/health_notes_public.json'  # mirrored to briefing-data/ai-health-notes.json
MAX_PER_DAY = 10
REFRESH_DAYS = 14
PROGRAM_STALE_DAYS = 10
SENTENCE_MIN, SENTENCE_MAX = 25, 180
QUOTE_MIN, QUOTE_MAX, QUOTES_MAX = 4, 200, 6
STATUSES = ('ok', 'caution', 'not_free', 'stopped', 'unclear')
TAKEDOWN_KIND = 'health_note_text'
DISTRICTS = ('종로구', '중구', '용산구', '성동구', '광진구', '동대문구', '중랑구', '성북구', '강북구', '도봉구', '노원구',
             '은평구', '서대문구', '마포구', '양천구', '강서구', '구로구', '금천구', '영등포구', '동작구', '관악구',
             '서초구', '강남구', '송파구', '강동구', '성남시')
# 페이지에 이런 말이 있으면 문장은 반드시 '확인'을 권하는 caution이어야 한다.
STOP = re.compile(r'(접수|신청|사업|운영)\s*(이\s*)?(마감|중단|종료|중지)|조기\s*(마감|종료)|예산\s*(소진|범위)|선착순')
FORBIDDEN = ('보장', '확실', '반드시 받', '무조건', '완치', '치료됩니다', '치료해', '효능', '효과가 있', '예방됩니다',
             '예산이 남', '예산 남', '아직 예산', '잔여', '누구나', '100%', '최고', '최저')
MOBILE = re.compile(r'(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)')
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
NOTE_FIELDS = {'url', 'district', 'sentence', 'generated_at', 'text_sha'}


def _norm(text):
    return re.sub(r'\s+', '', text or '')


def host(program, now):
    """Model input for one checked programme with stored main text; None otherwise."""
    if program.get('status') != 'checked' or not program.get('text') or not program.get('text_sha'):
        return None
    return dict(schema_version='health-note-input-v1', mode='api_agent', synthetic=False, now=now.isoformat(),
                district=program['district'], center=program['center'], program=program['name'],
                url=program['url'], text_sha=program['text_sha'], page_text=program['text'])


def review(draft, host):
    """Error codes; empty means the sentence may be published."""
    if not isinstance(draft, dict) or set(draft) != {'status', 'sentence', 'quotes'} or draft['status'] not in STATUSES \
            or not isinstance(draft['sentence'], str) or not isinstance(draft['quotes'], list) \
            or not all(isinstance(q, str) for q in draft['quotes']):
        return ['draft_shape']
    if draft['status'] not in ('ok', 'caution'):
        return ['not_recommendable']
    errors = []
    page = _norm(host['page_text'])
    quotes = draft['quotes']
    if not 1 <= len(quotes) <= QUOTES_MAX or any(not QUOTE_MIN <= len(q) <= QUOTE_MAX for q in quotes):
        errors.append('quotes_shape')
    if any(_norm(q) not in page for q in quotes):
        errors.append('quote_not_in_page')
    quoted = _norm(' '.join(quotes))
    text = draft['sentence']
    errors += sentence_errors(text, host['district'])
    for number in re.findall(r'\d+', text):
        if number not in quoted:
            errors.append('number_not_quoted')
            break
    if '무료' in text and '무료' not in quoted:
        errors.append('free_not_quoted')
    if '예산' in text and '예산' not in quoted:
        errors.append('budget_not_quoted')
    if STOP.search(host['page_text']):
        if draft['status'] != 'caution' or '확인' not in text:
            errors.append('caution_required')
    return errors


def sentence_errors(text, district):
    """Rules that need no page: also re-applied on every publication path."""
    errors = []
    if not isinstance(text, str) or not SENTENCE_MIN <= len(text) <= SENTENCE_MAX:
        return ['sentence_length']
    if re.search(r'[<>\n\r]|https?:|www\.', text) or MOBILE.search(text) or EMAIL.search(text):
        errors.append('sentence_markup')
    if any(word in text for word in FORBIDDEN):
        errors.append('sentence_claim')
    if any(d in text for d in DISTRICTS if d != district):
        errors.append('sentence_other_district')
    return errors


def muted(takedowns, url):
    return any(isinstance(t, dict) and t.get('kind') == TAKEDOWN_KIND and t.get('url') == url for t in takedowns or [])


def public(notes, bundle, takedowns, now):
    """Notes that may be shown today next to the (private) health bundle; [] when nothing qualifies."""
    if not isinstance(notes, list) or not isinstance(bundle, dict):
        return []
    programs = {p['url']: p for p in bundle.get('programs', [])}
    out, seen = [], set()
    for note in notes:
        try:
            if not isinstance(note, dict) or set(note) != NOTE_FIELDS or note['url'] in seen:
                continue
            program = programs.get(note['url'])
            generated = datetime.fromisoformat(note['generated_at'])
            if (program is None or program['status'] != 'checked' or not program.get('checked_at')
                    or program.get('text_sha') != note['text_sha'] or program['district'] != note['district']
                    or generated.tzinfo is None or generated > now + timedelta(minutes=5)
                    or now - generated > timedelta(days=REFRESH_DAYS + 7)
                    or now - datetime.fromisoformat(program['checked_at']) > timedelta(days=PROGRAM_STALE_DAYS)
                    or sentence_errors(note['sentence'], note['district']) or muted(takedowns, note['url'])):
                continue
            seen.add(note['url'])
            out.append({k: note[k] for k in ('url', 'district', 'sentence', 'generated_at')})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def public_light(notes, public_bundle, takedowns, now):
    """Re-check for paths that only hold the public payload (snapshot redeploy, takedown-only deploy)."""
    if not isinstance(notes, list) or not isinstance(public_bundle, dict):
        return []
    checked = {p['url']: p for p in public_bundle.get('programs', []) if p.get('status') == 'checked'}
    out, seen = [], set()
    for note in notes:
        try:
            if not isinstance(note, dict) or set(note) != {'url', 'district', 'sentence', 'generated_at'} or note['url'] in seen:
                continue
            program = checked.get(note['url'])
            generated = datetime.fromisoformat(note['generated_at'])
            if (program is None or program['district'] != note['district'] or generated.tzinfo is None
                    or generated > now + timedelta(minutes=5) or now - generated > timedelta(days=REFRESH_DAYS + 7)
                    or now - datetime.fromisoformat(program['checked_at']) > timedelta(days=PROGRAM_STALE_DAYS)
                    or sentence_errors(note['sentence'], note['district']) or muted(takedowns, note['url'])):
                continue
            seen.add(note['url'])
            out.append(dict(note))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def published_form(notes):
    """Stored public copy: keeps text_sha so every publish path can tie the sentence to the same page text."""
    return [{k: n[k] for k in NOTE_FIELDS} for n in notes.values() if n.get('state') == 'published']


def refresh(root, now, execute=False):
    """Up to MAX_PER_DAY paid calls for programmes whose page text is new, changed or older than 14 days."""
    from .health_notices import FILE, sanitize
    root = Path(root).resolve()
    with lock(project_path(root, 'cache/ai_publish/.health.lock')):
        bundle = sanitize(load(project_path(root, FILE), None), now, private=True)
        notes = load(project_path(root, NOTES), {})
        if not isinstance(notes, dict):
            notes = {}
        if bundle is None:
            return {'status': 'no_bundle', 'requested': 0, 'published': 0, 'model': None}
        day = now.date().isoformat()
        due = []
        for program in bundle['programs']:
            current = host(program, now)
            if current is None:
                continue
            note = notes.get(program['url'], {})
            fresh = note.get('text_sha') == program['text_sha'] and note.get('state') in ('published', 'rejected') \
                and now - datetime.fromisoformat(note['attempted_at']) < timedelta(days=REFRESH_DAYS)
            if not fresh and note.get('attempted_day') != day:
                due.append(current)
        requested, published, model = 0, 0, None
        for current in due[:MAX_PER_DAY] if execute else []:
            digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            input_path = project_path(root, f'.tools/ai-inputs/health-{day}-{digest}.json')
            save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
            # Persist before calling: a crash cannot open another paid attempt for this page today.
            old = notes.get(current['url'], {})
            notes[current['url']] = dict(old, attempted_day=day, attempted_at=now.isoformat())
            save(project_path(root, NOTES), notes)
            model = invoke(root, 'health', input_path)
            requested += 1
            if model['status'] == 'credit_exhausted':
                break
            errors = ['no_draft']
            if model['status'] == 'validated_draft':
                try:
                    draft = load(TRIAL_RUNS / model['run_id'] / 'result.json', None)
                    errors = review(draft, current)
                except (OSError, ValueError, KeyError, TypeError):
                    errors = ['draft_unreadable']
            row = dict(url=current['url'], district=current['district'], text_sha=current['text_sha'],
                       attempted_day=day, attempted_at=now.isoformat(), run_id=model.get('run_id'), errors=errors)
            if not errors:
                row.update(state='published', sentence=draft['sentence'], quotes=draft['quotes'],
                           generated_at=now.isoformat())
                published += 1
            elif old.get('state') == 'published' and old.get('text_sha') == current['text_sha']:
                row.update({k: old[k] for k in ('state', 'sentence', 'quotes', 'generated_at')})  # keep the last good one
            else:
                row.update(state='rejected')
            notes[current['url']] = row
            save(project_path(root, NOTES), notes)
        save(project_path(root, PUBLIC), published_form(notes))
        return {'status': 'credit_exhausted' if (model or {}).get('status') == 'credit_exhausted' else 'completed',
                'due': len(due), 'requested': requested, 'published': published, 'model': model}
