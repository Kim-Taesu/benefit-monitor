import { test } from 'node:test';
import assert from 'node:assert/strict';
import { plan } from '../src/plan.js';

// 2026-11-20 KST times as UTC instants
const at = (hhmm) => new Date(`2026-11-20T${hhmm}:00+09:00`);
const run = (created, extra = {}) => ({ created_at: at(created).toISOString(), status: 'completed', conclusion: 'success', ...extra });

test('idle outside 03:20-04:50 KST', () => {
  assert.equal(plan({}, at('03:10')).action, 'idle');
  assert.equal(plan({}, at('04:51')).action, 'idle');
});

test('health first, then 청약, then the benefit collection', () => {
  assert.deepEqual(plan({}, at('03:20')), { action: 'dispatch', workflow: 'health-notices.yml' });
  const health = [run('03:20')];
  assert.deepEqual(plan({ 'health-notices.yml': health }, at('03:30')), { action: 'dispatch', workflow: 'subscriptions.yml' });
  const subs = [run('03:30')];
  assert.deepEqual(plan({ 'health-notices.yml': health, 'subscriptions.yml': subs }, at('03:40')),
    { action: 'dispatch', workflow: 'briefing-pages.yml' });
});

test('never dispatches while any shared-group run is queued or running', () => {
  const busy = [run('03:30', { status: 'in_progress', conclusion: null })];
  assert.equal(plan({ 'health-notices.yml': [run('03:20')], 'subscriptions.yml': busy }, at('03:40')).action, 'wait');
  // a snapshot deploy (not a collection) still occupies the group
  const deploy = [run('04:15', { status: 'queued', conclusion: null, display_title: '승인 스냅샷 게시' })];
  assert.equal(plan({ 'briefing-pages.yml': deploy }, at('04:20')).action, 'wait');
});

test('only collection runs count for the benefit step; yesterday is ignored', () => {
  const ok = { 'health-notices.yml': [run('03:20')], 'subscriptions.yml': [run('03:30')] };
  const yesterday = { created_at: '2026-11-19T10:00:00Z', status: 'completed', conclusion: 'success', display_title: '수집' };
  const deploy = run('03:35', { display_title: '승인 스냅샷 게시' });
  assert.equal(plan({ ...ok, 'briefing-pages.yml': [deploy, yesterday] }, at('03:50')).workflow, 'briefing-pages.yml');
  assert.equal(plan({ ...ok, 'briefing-pages.yml': [run('03:40', { display_title: '수집' })] }, at('04:00')).action, 'idle');
});

test('a failure is retried once, then the next step goes ahead', () => {
  const failed = (t) => run(t, { conclusion: 'failure' });
  assert.equal(plan({ 'health-notices.yml': [failed('03:20')] }, at('03:30')).workflow, 'health-notices.yml');
  assert.equal(plan({ 'health-notices.yml': [failed('03:20'), failed('03:30')] }, at('03:40')).workflow, 'subscriptions.yml');
  const ok = { 'health-notices.yml': [run('03:20')], 'subscriptions.yml': [run('03:30')] };
  const twice = [failed('03:40'), failed('03:50')].map((r) => ({ ...r, display_title: '수집' }));
  assert.equal(plan({ ...ok, 'briefing-pages.yml': twice }, at('04:00')).action, 'idle');
});
