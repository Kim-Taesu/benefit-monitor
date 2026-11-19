// Free Cloudflare Workers cron that starts the daily runs on time (approved 2026-11-20).
//
// GitHub `schedule` events started 4-8 hours late; `workflow_dispatch` starts at once. This Worker only
// lists runs and dispatches the fixed workflows below. It has no HTTP route (workers_dev = false) and
// its single secret GITHUB_TOKEN is a fine-grained token for this one repository with Actions read/write.
import { plan } from './plan.js';

const REPO = 'Kim-Taesu/benefit-monitor';
const API = `https://api.github.com/repos/${REPO}/actions/workflows/`;
const WORKFLOWS = ['health-notices.yml', 'subscriptions.yml', 'briefing-pages.yml'];

function headers(env) {
  return {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
    'User-Agent': 'benefit-monitor-daily-trigger',
  };
}

async function runs(env, workflow) {
  const response = await fetch(`${API}${workflow}/runs?branch=main&per_page=20`, { headers: headers(env) });
  if (!response.ok) throw new Error(`list ${workflow}: HTTP ${response.status}`);
  return (await response.json()).workflow_runs || [];
}

async function dispatch(env, workflow) {
  const response = await fetch(`${API}${workflow}/dispatches`, {
    method: 'POST',
    headers: { ...headers(env), 'Content-Type': 'application/json' },
    body: JSON.stringify({ ref: 'main', inputs: { external_schedule: 'true' } }),
  });
  if (response.status !== 204) throw new Error(`dispatch ${workflow}: HTTP ${response.status}`);
}

export async function tick(env, now) {
  const listed = {};
  for (const workflow of WORKFLOWS) listed[workflow] = await runs(env, workflow);
  const decision = plan(listed, now);
  if (decision.action === 'dispatch') await dispatch(env, decision.workflow);
  console.log(JSON.stringify({ at: now.toISOString(), ...decision }));
  return decision;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(tick(env, new Date(event.scheduledTime)));
  },
};
