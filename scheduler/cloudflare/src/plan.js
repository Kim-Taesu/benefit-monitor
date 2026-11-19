// Which daily run to dispatch on this tick (2026-11-20). Pure: the Worker supplies today's runs.
//
// The three workflows share the `benefit-pages` concurrency group. GitHub keeps only one pending run
// per group and cancels the older pending one, so nothing is dispatched while any of them is queued or
// running: one dispatch per tick, in order, health → 청약 → benefit collection.

export const START_MINUTE = 3 * 60 + 20; // 03:20 KST
export const END_MINUTE = 4 * 60 + 50; // 04:50 KST; the page must be fresh by 05:00
export const MAX_ATTEMPTS = 2;
export const ORDER = [
  { workflow: 'health-notices.yml' },
  { workflow: 'subscriptions.yml' },
  // Collection runs carry this run-name; snapshot deploys and push checks do not.
  { workflow: 'briefing-pages.yml', title: '수집' },
];

const KST_MS = 9 * 3600 * 1000;

export function kstDay(date) {
  return new Date(date.getTime() + KST_MS).toISOString().slice(0, 10);
}

export function kstMinute(date) {
  const k = new Date(date.getTime() + KST_MS);
  return k.getUTCHours() * 60 + k.getUTCMinutes();
}

/** runs: {workflowFile: [GitHub workflow run]}. Returns {action:'dispatch', workflow} or {action:'wait'|'idle', reason}. */
export function plan(runs, now) {
  const minute = kstMinute(now);
  if (minute < START_MINUTE || minute > END_MINUTE) return { action: 'idle', reason: 'outside 03:20-04:50 KST' };
  const day = kstDay(now);
  const today = (list) => (list || []).filter((r) => kstDay(new Date(r.created_at)) === day);
  const all = ORDER.flatMap((w) => today(runs[w.workflow]));
  if (all.some((r) => r.status !== 'completed')) return { action: 'wait', reason: 'a benefit-pages run is queued or running' };
  for (const w of ORDER) {
    const mine = today(runs[w.workflow]).filter((r) => !w.title || r.display_title === w.title);
    if (mine.some((r) => r.conclusion === 'success')) continue;
    if (mine.length >= MAX_ATTEMPTS) continue; // gave up for today; later steps still run
    return { action: 'dispatch', workflow: w.workflow };
  }
  return { action: 'idle', reason: 'today done' };
}
