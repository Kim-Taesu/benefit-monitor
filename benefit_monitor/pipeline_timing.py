"""Daily refresh timing and the once-a-day gate for scheduled runs (2026-11-20).

GitHub `schedule` runs started 4-8 hours late (00:37 cron, 04:33-08:50 KST starts). A free Cloudflare
Workers cron (approved 2026-11-20) now dispatches the daily runs from 03:20 KST so the page is fresh by
05:00. GitHub's own schedule stays as a backup and skips when today's run already succeeded (`--gate`).

The public `pipeline_timing` lets the home page say how long today's crawl, AI run and publication took.
Times come from GitHub's own step records, never from the model.

    python -m benefit_monitor.pipeline_timing --gate briefing-pages.yml   # writes run=true|false
"""
import argparse
from datetime import timedelta
import json
import os
from urllib.request import Request, urlopen

from .briefing import SEOUL, aware_time

REPOSITORY = 'Kim-Taesu/benefit-monitor'
BRIEFING = 'briefing-pages.yml'
# run-name of briefing-pages collection runs; snapshot deploys, takedowns and push checks use other names.
COLLECT_TITLE = '수집'
# Crawl workflows and the public part names; each collects in one step whose name starts with "Collect".
CRAWLS = {BRIEFING: 'benefits', 'health-notices.yml': 'health', 'subscriptions.yml': 'subscriptions'}
TIMES = ('collect_started_at', 'collect_finished_at', 'ai_started_at', 'ai_finished_at', 'published_at')
MAX_SPAN = timedelta(hours=24)
MAX_RESPONSE = 4 * 1024 * 1024


def _kst(value):
    return aware_time(value.replace('Z', '+00:00')).astimezone(SEOUL)


def todays_runs(get, workflow, now):
    """Main-branch runs of a workflow created on today's Seoul date (newest first, as GitHub lists them)."""
    data = get('actions/workflows/' + workflow + '/runs?branch=main&per_page=30')
    day = now.astimezone(SEOUL).date()
    return [r for r in data.get('workflow_runs', []) if _kst(r['created_at']).date() == day]


def is_collection(workflow, run):
    return workflow != BRIEFING or run.get('display_title') == COLLECT_TITLE


def done_today(workflow, runs, self_id=None):
    """True when another of today's runs already finished successfully (briefing: collection runs only)."""
    return any(str(r.get('id')) != str(self_id) and is_collection(workflow, r)
               and r.get('status') == 'completed' and r.get('conclusion') == 'success' for r in runs)


def crawl_step(jobs):
    """(started, finished) of a run's successful "Collect ..." step, None when it was skipped or failed."""
    for job in jobs.get('jobs', []):
        for step in job.get('steps', []):
            if (str(step.get('name', '')).startswith('Collect') and step.get('conclusion') == 'success'
                    and step.get('started_at') and step.get('completed_at')):
                return _kst(step['started_at']), _kst(step['completed_at'])
    return None


def crawl_window(get, now):
    """Today's crawl: earliest step start, the benefit collection's finish and the summed step seconds.

    The benefit collection is the latest successful one that finished by now; health and 청약 runs count
    only when they finished before it (their data is restored by that collection). None without one."""
    parts = {}
    for workflow, name in CRAWLS.items():
        limit = now if name == 'benefits' else parts.get('benefits', (None, None))[1]
        if limit is None:
            return None
        for run in todays_runs(get, workflow, now):
            if run.get('conclusion') != 'success' or not is_collection(workflow, run):
                continue
            step = crawl_step(get('actions/runs/' + str(run['id']) + '/jobs'))
            if step and step[1] <= limit:
                parts[name] = step
                break
    if 'benefits' not in parts:
        return None
    return {'collect_started_at': min(s for s, _ in parts.values()).isoformat(),
            'collect_finished_at': parts['benefits'][1].isoformat(),
            'collect_seconds': round(sum((f - s).total_seconds() for s, f in parts.values()))}


def sanitize(value, now):
    """Public pipeline_timing or None: aware times in pipeline order, within a day, none in the future."""
    if not isinstance(value, dict) or set(value) - set(TIMES) - {'collect_seconds'}:
        return None
    times = {}
    for key in TIMES:
        if key in value:
            try:
                times[key] = aware_time(value[key]).astimezone(SEOUL)
            except (TypeError, ValueError):
                return None
    if any(key not in times for key in TIMES[:4]):
        return None
    order = [times[k] for k in TIMES if k in times]
    if order != sorted(order) or order[-1] > now or now - order[0] > MAX_SPAN:
        return None
    seconds = value.get('collect_seconds')
    span = (times['collect_finished_at'] - times['collect_started_at']).total_seconds()
    if type(seconds) is not int or not 0 <= seconds <= span + 1:
        return None
    return dict({k: t.isoformat() for k, t in times.items()}, collect_seconds=seconds)


def mark_published(data, now):
    """Adds the publication time to a validated snapshot that carries today's timing."""
    timing = data.get('pipeline_timing')
    if isinstance(timing, dict) and aware_time(timing['ai_finished_at']) <= now:
        data['pipeline_timing'] = dict(timing, published_at=now.astimezone(SEOUL).isoformat())
    return data


def github_get(token):
    def get(path):
        request = Request('https://api.github.com/repos/' + REPOSITORY + '/' + path,
                          headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                                   'User-Agent': 'BenefitMonitor-Gate/1.0'})
        with urlopen(request, timeout=20) as response:
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('GitHub response too large')
        return json.loads(raw)
    return get


def gate(workflow, scheduled, get, now, self_id=None):
    """'true' to run. Only scheduled runs (GitHub cron or the external cron) are skipped, and only after
    another of today's runs succeeded; an unreadable run list runs anyway (twice beats never)."""
    if not scheduled:
        return 'true'
    try:
        return 'false' if done_today(workflow, todays_runs(get, workflow, now), self_id) else 'true'
    except Exception:
        return 'true'


def main():
    from datetime import datetime
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gate', required=True, choices=sorted(CRAWLS))
    args = parser.parse_args()
    result = gate(args.gate, os.environ.get('SCHEDULED') == 'true', github_get(os.environ.get('GH_TOKEN', '')),
                  datetime.now(SEOUL), os.environ.get('GITHUB_RUN_ID'))
    print('run=' + result + (' (today already succeeded; skipped)' if result == 'false' else ''))
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as stream:
            stream.write('run=' + result + '\n')


if __name__ == '__main__':
    main()
