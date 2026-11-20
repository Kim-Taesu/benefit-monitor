"""Stage 2 checks for the festival and health-notice tabs (four-stage pipeline, approved 2026-11-20).

One daily step runs both under a shared cap of MAX_PER_DAY paid requests, after the benefit verification and
before the recommendation cards. The public result goes into `briefing.json` as `tab_checks`:
  {"schema_version": 1, "notices": [{url, title, reason}], "festivals": [{id, note, quote}]}
Every publication path re-checks it against the bundles it actually publishes; failures drop rows, never the page.
"""
from pathlib import Path

from . import festival_check, notice_triage
from .official_reader import project_path
from .store import load, save

MAX_PER_DAY = 20
DAYS = 'cache/tab_checks/days.json'
KEY = 'tab_checks'
TRIAL_RUNS = Path(__file__).resolve().parents[1] / '.tools/claude-trial/live/runs'


def refresh(root, now, execute=False):
    from .ai_review import invoke
    root = Path(root).resolve()
    day = now.date().isoformat()
    days = load(project_path(root, DAYS), {})
    if not isinstance(days, dict):
        days = {}
    used = days.get(day, 0) if isinstance(days.get(day, 0), int) else MAX_PER_DAY
    report = {}

    def spend(n):
        nonlocal used
        used += n
        save(project_path(root, DAYS), {day: used})

    # Festivals first: few requests, each covers a whole card. Notices take what is left.
    n, report['festivals'] = festival_check.refresh(root, now, execute, invoke, TRIAL_RUNS, MAX_PER_DAY - used)
    spend(n)
    if report['festivals'].get('status') != 'credit_exhausted':
        n, report['notices'] = notice_triage.refresh(root, now, execute, invoke, TRIAL_RUNS, MAX_PER_DAY - used)
        spend(n)
    exhausted = any(r.get('status') == 'credit_exhausted' for r in report.values())
    save(project_path(root, PUBLIC), build(root, now, []))
    return dict(report, status='credit_exhausted' if exhausted else 'completed', requested=used)


PUBLIC = 'cache/tab_checks/public.json'  # mirrored to briefing-data/ai-tab-checks.json


def build(root, now, takedowns):
    """Public rows from the private state (AI run) and today's private bundles."""
    from .festivals import sanitize as festivals
    from .health_notices import FILE, sanitize as health
    root = Path(root)
    try:
        notice_rows = notice_triage.public(load(root / notice_triage.STATE, None),
                                           health(load(root / FILE, None), now, private=True), takedowns)
    except Exception:
        notice_rows = []
    try:
        festival_rows = festival_check.public(load(root / festival_check.STATE, None),
                                              festivals(load(root / festival_check.FILE, None), now))
    except Exception:
        festival_rows = []
    return {'schema_version': 1, 'notices': notice_rows, 'festivals': festival_rows}


def attach(root, data, now, takedowns):
    """Publication: the AI run builds from its private state; a collection-only run uses the restored public copy.
    Either way the rows are re-checked against the bundles in `data`."""
    root = Path(root)
    private = (root / notice_triage.STATE).exists() or (root / festival_check.STATE).exists()
    checks = build(root, now, takedowns) if private else load(root / PUBLIC, None)
    apply(data, checks, takedowns)


def apply(data, checks, takedowns):
    """Keep only rows that still match the bundles in `data`; drop the key when nothing is left."""
    data.pop(KEY, None)
    if not isinstance(checks, dict) or checks.get('schema_version') != 1:
        return
    notices = notice_triage.recheck(checks.get('notices'), data.get('health_notices'), takedowns) \
        if isinstance(data.get('health_notices'), dict) else []
    festivals = festival_check.recheck(checks.get('festivals'), data.get('festivals')) \
        if isinstance(data.get('festivals'), dict) else []
    if notices or festivals:
        data[KEY] = {'schema_version': 1, 'notices': notices, 'festivals': festivals}
