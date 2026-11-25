"""Stage 1 discovery search (approved 2026-11-25).

The follow-up search (investigation.search_lead) only fills missing fields of candidates the scripts already
listed; an event no listing showed (2026-11-25: 마곡광장 윈터 스케이트장, posted on the district's social
media) could never be found. Once a day this asks the web search tool for each home area's events of the
month and turns the results into ordinary review candidates:

  - the code names the areas (서울시 and the district_feed districts) and the month; nothing else is sent;
  - only URLs from the provider's result blocks are used, never model text;
  - a URL on a registered source that allows AI review becomes a candidate with needs_recheck, so it goes
    through the same research, verification and deterministic publication gate as any listed candidate;
  - any other host is kept privately as a source candidate for a person to register;
  - a lead stays a candidate for LEAD_DAYS, so a page found once is researched even if the search
    does not return it again.

Bounds: one run a day, at most len(areas) <= MAX_AREAS requests, DISCOVERY_MAX_USES searches each, inside
the shared daily search cap (50) and the monthly ledger cap. A refused search ends the run for the day.
"""
from datetime import datetime, timedelta
import hashlib
import json
from urllib.parse import urlsplit

from .official_reader import project_path
from .store import load, save
from . import web_search

STATE = 'cache/discovery_search/state.json'
MAX_AREAS = 3
LEAD_DAYS = 14
MAX_NEW_LEADS = 10
MAX_STORED_LEADS = 60
MAX_SOURCE_CANDIDATES = 100
SUMMARY = 'AI 웹 검색으로 찾은 공식 페이지 후보. 상세 조건 확인 필요.'


def areas(sources):
    """서울시 plus the active district_feed districts, in source order, at most MAX_AREAS."""
    names = ['서울시'] + [s['district_feed'] for s in sources.values()
                         if s.get('district_feed') and s.get('status', 'active') == 'active']
    return [a for a in dict.fromkeys(names) if web_search.AREA.fullmatch(a)][:MAX_AREAS]


def _source_for(url, area, sources):
    """The registered source that may be read for this URL; a district's own source wins on shared hosts."""
    from .validation import official
    from .cross_sources import fetchable
    if not fetchable(url):
        return None
    allowed = [(sid, s) for sid, s in sources.items() if s.get('ai_review') is not False and official(url, s['domains'])]
    allowed.sort(key=lambda pair: pair[1].get('district_feed') != area)
    return allowed[0][0] if allowed else None


def _recent(stamp, now, days):
    try:
        return timedelta(0) <= now - datetime.fromisoformat(stamp) <= timedelta(days=days)
    except (TypeError, ValueError):
        return False


def _candidates(state, now):
    out = []
    for url, lead in state['leads'].items():
        if _recent(lead.get('found_at'), now, LEAD_DAYS):
            out.append({'source': lead['source'], 'url': url, 'title': lead['title'], 'summary': SUMMARY,
                        'districts': [lead['area']] if lead['area'].endswith('구') else [], 'needs_recheck': True})
    return out


def run(root, sources, now, known_urls=(), execute=False, invoke=None):
    """Today's discovery candidates and a report. Searches at most once a day; later calls reuse the leads."""
    if invoke is None:
        from .ai_review import invoke_search as invoke
    path = project_path(root, STATE)
    state = load(path, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault('days', {})
    state.setdefault('leads', {})
    state.setdefault('source_candidates', {})
    day = now.date().isoformat()
    report = {'status': 'reused' if day in state['days'] else 'skipped', 'requests': 0, 'searches': 0,
              'new_leads': 0, 'source_candidates': 0}
    known = set(known_urls)
    if day not in state['days'] and execute:
        report['status'] = 'done'
        for area in areas(sources):
            host = web_search.build_discovery(area, now)
            web_search.validate_discovery(host)
            key = hashlib.sha256(json.dumps(host, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
            input_path = project_path(root, '.tools/ai-inputs/discovery-' + key + '.json')
            save(input_path, host)
            found = invoke(root, input_path)
            report['requests'] += 1
            report['searches'] += found.get('searches') or 0
            if found.get('status') != 'search_done':
                # Search disabled, daily search cap, credit: the rest of the day does not try again.
                report['status'] = found.get('status') or 'search_failed'
                break
            rows = found.get('rows') or [{'url': u, 'title': ''} for u in found.get('urls') or []]
            for row in rows:
                url = row['url']
                if url in known or url in state['leads']:
                    continue
                sid = _source_for(url, area, sources)
                if sid is not None:
                    if report['new_leads'] < MAX_NEW_LEADS:
                        title = row.get('title') or (area + ' 공식 안내')
                        state['leads'][url] = {'source': sid, 'title': title[:200], 'area': area, 'found_at': now.isoformat()}
                        report['new_leads'] += 1
                elif urlsplit(url).hostname not in {d for s in sources.values() for d in s['domains']}:
                    if url not in state['source_candidates']:
                        report['source_candidates'] += 1
                    state['source_candidates'][url] = {'area': area, 'found_at': now.isoformat()}
        state['days'][day] = {k: v for k, v in report.items()}
    # Trim: old days, expired leads and source candidates, then the stored-size bounds (newest kept).
    state['days'] = {d: r for d, r in sorted(state['days'].items())[-14:]}
    leads = sorted(((u, l) for u, l in state['leads'].items() if _recent(l.get('found_at'), now, LEAD_DAYS)),
                   key=lambda pair: pair[1]['found_at'])
    state['leads'] = dict(leads[-MAX_STORED_LEADS:])
    rows = sorted(((u, r) for u, r in state['source_candidates'].items() if _recent(r.get('found_at'), now, 30)),
                  key=lambda pair: pair[1]['found_at'])
    state['source_candidates'] = dict(rows[-MAX_SOURCE_CANDIDATES:])
    save(path, state)
    candidates = [c for c in _candidates(state, now) if c['url'] not in known and c['source'] in sources]
    report['active_leads'] = len(candidates)
    return candidates, report
