import { test } from 'node:test';
import assert from 'node:assert/strict';
import { adapt } from '../src/benefits.ts';
import { grade, GRADES } from '../src/grade.ts';
import { item, snapshot, NOW } from './fixtures.ts';

const one = (over: Record<string, unknown> = {}, snap: Record<string, unknown> = {}) => {
  const data = adapt(snapshot([item({ valid_until: '2026-11-20', deadline_at: null, display_until: '2026-11-20T00:00:00+09:00', ...over })], snap), NOW);
  assert.equal(data.items.length, 1);
  return grade(data.items[0], data.sourceFailures, NOW);
};

test('A: fixed end, checked within 7 days, healthy source', () => {
  assert.equal(one().grade, 'A');
});
test('B: ongoing items have no official end date', () => {
  const r = one({ validity_kind: 'ongoing', valid_until: null });
  assert.equal(r.grade, 'B'); assert.match(r.reason, /끝나는 날/);
});
test('B: checked 8 or more days ago', () => {
  const r = one({ verified_at: '2026-10-27T06:00:00+09:00' });
  assert.equal(r.grade, 'B'); assert.match(r.reason, /8일/);
});
test('C: source failed 3+ times in a row overrides A', () => {
  const health = { source_health: { seoul: { consecutive_failures: 3 } } };
  const r = one({}, health);
  assert.equal(r.grade, 'C'); assert.match(r.reason, /3회/);
  assert.equal(one({}, { source_health: { seoul: { consecutive_failures: 2 } } }).grade, 'A');
});
test('malformed source health is ignored', () => {
  assert.equal(one({}, { source_health: { seoul: { consecutive_failures: 'x' } } }).grade, 'A');
  assert.equal(one({}, { source_health: [] }).grade, 'A');
});
test('every grade has a help text', () => {
  assert.deepEqual(GRADES.map(g => g.grade), ['A', 'B', 'C']);
  for (const g of GRADES) assert.ok(g.title && g.body);
});
