import { test } from 'node:test';
import assert from 'node:assert/strict';
import { adapt, select, timing, readFilters, filterUrl, safeOfficial, regionOptions, categories, categoryLabel, parseTiming, minutesLabel } from '../src/benefits.ts';
import { item, snapshot, NOW } from './fixtures.ts';

test('valid approved paid and free records are preserved without invented amounts', () => {
  const result = adapt(snapshot([item(), item({ url: 'https://mediahub.seoul.go.kr/archives/2', fee_status: 'paid' })]), NOW);
  assert.equal(result.state, 'partial'); assert.equal(result.items.length, 2);
  assert.equal(result.items[0].category, '문화·체험');
});
test('past the file cutoff the previous list stays until the next refresh; item cutoffs still apply (2026-11-20)', () => {
  const late = adapt(snapshot([item(), item({ url: 'https://mediahub.seoul.go.kr/archives/9', display_until: new Date(NOW).toISOString() })], { valid_through: new Date(NOW).toISOString() }), NOW);
  assert.equal(late.state, 'partial'); assert.equal(late.carriedOver, true);
  assert.equal(late.items.length, 1); assert.equal(late.withheldCount, 1);
  assert.equal(adapt(snapshot([item()]), NOW).carriedOver, false);
  const failed = adapt(snapshot([item()], { status: 'collection_failed', valid_through: new Date(NOW).toISOString() }), NOW);
  assert.equal(failed.carriedOver, false); assert.equal(failed.items.length, 0);
});
const TIMING = { collect_started_at: '2026-11-04T03:21:00+09:00', collect_finished_at: '2026-11-04T03:47:00+09:00', collect_seconds: 720,
  ai_started_at: '2026-11-04T03:48:00+09:00', ai_finished_at: '2026-11-04T04:01:00+09:00', published_at: '2026-11-04T04:02:10+09:00' };
test('pipeline timing becomes crawl, AI and publish durations', () => {
  assert.deepEqual(parseTiming(TIMING, NOW), { startedAt: TIMING.collect_started_at, publishedAt: TIMING.published_at, crawlSeconds: 720, aiSeconds: 780, publishSeconds: 70 });
  assert.equal(adapt(snapshot([item()], { pipeline_timing: TIMING }), NOW).timing?.aiSeconds, 780);
  const { published_at: _, ...unpublished } = TIMING;
  assert.equal(parseTiming(unpublished, NOW)?.publishSeconds, null);
  for (const bad of [{ ...TIMING, ai_started_at: '2026-11-04T03:40:00+09:00' }, { ...TIMING, published_at: '2026-11-04T13:00:00+09:00' },
    { ...TIMING, collect_seconds: 99999 }, { ...TIMING, collect_seconds: '720' }, { ...TIMING, ai_finished_at: 'x' }, null, 'x']) {
    assert.equal(parseTiming(bad, NOW), null);
  }
  assert.equal(minutesLabel(40), '1분 미만'); assert.equal(minutesLabel(90), '2분'); assert.equal(minutesLabel(780), '13분');
});
test('failure and awaiting verification never release embedded records', () => {
  for (const status of ['collection_failed', 'awaiting_verification']) {
    const result = adapt(snapshot([item()], { status }), NOW);
    assert.equal(result.state, status); assert.equal(result.items.length, 0);
  }
});
test('unverified, future verified, missing cutoff and invalid URLs are withheld individually', () => {
  const bad = [item({ needs_recheck: true }), item({ needs_recheck: undefined }), item({ verified_at: '2026-11-05T00:00:00+09:00' }), item({ display_until: undefined }), item({ url: 'javascript:alert(1)' }), item({ url: 'https://evil.example/' }), item({ verified_at: '2026-10-01T00:00:00+09:00' })];
  const result = adapt(snapshot(bad), NOW); assert.equal(result.items.length, 0); assert.equal(result.withheldCount, bad.length);
});
test('item and application expiration are inclusive; expired verification is not event closure', () => {
  for (const override of [{display_until: new Date(NOW).toISOString()}, {deadline_at: new Date(NOW).toISOString()}, {valid_until: '2026-11-03'}]) {
    assert.equal(adapt(snapshot([item(override)]), NOW).items.length, 0);
  }
});
test('KST days differ across UTC afternoon; start and application deadline stay distinct', () => {
  const t = Date.parse('2026-11-04T14:59:59Z');
  assert.equal(timing(item({deadline_at: '2026-11-05T18:00:00+09:00'}), t).label, '신청 마감 D-1');
  assert.equal(timing(item({deadline_at: '2026-11-05T18:00:00+09:00'}), t+1000).label, '오늘 신청 마감');
  assert.match(timing(item({valid_from: '2026-11-06',deadline_at: null}), NOW).label, /시작 전/);
  assert.equal(timing(item({valid_from: null,valid_until: null,deadline_at: null,validity_kind: 'ongoing'}), NOW).label, '상시 안내');
});
test('date-only end expires at next KST midnight and never at UTC midnight', () => {
  const s=snapshot([item({valid_until:'2026-11-04',deadline_at:null})]);
  assert.equal(adapt(s,Date.parse('2026-11-04T14:59:59Z')).items.length,1);
  assert.equal(adapt(s,Date.parse('2026-11-04T15:00:00Z')).items.length,0);
});
test('search fields and AND filters; district and nationwide scope never inferred from empty districts', () => {
  const records = adapt(snapshot([item(), item({url:'https://mediahub.seoul.go.kr/archives/2',districts:[],labels:{region:'전국',category:'할인·적립',audience:'멤버십 회원',action:'결제 시 적용'}})]),NOW).items;
  assert.equal(select(records,{q:'문화 회원',region:'강서구',category:'문화·체험',sort:'deadline',status:''},NOW).length,1);
  assert.equal(select(records,{q:'',region:'전국',category:'',sort:'deadline',status:''},NOW).length,1);
  assert.equal(select(records,{q:'',region:'은평구',category:'',sort:'deadline',status:''},NOW).length,0);
  assert.equal(select(adapt(snapshot([item({districts:[],labels:{}})]),NOW).items,{q:'',region:'전국',category:'',sort:'deadline',status:''},NOW).length,0);
});
test('sorting ignores fee status and missing dates go last', () => {
  const rows=adapt(snapshot([item({summary:'가',fee_status:'paid'}),item({summary:'나',url:'https://mediahub.seoul.go.kr/archives/2',valid_until:null,deadline_at:null,validity_kind:'ongoing'})]),NOW).items;
  assert.equal(select(rows,readFilters(''),NOW)[0].summary,'가');
  assert.equal(select(rows,{...readFilters(''),sort:'title'},NOW)[0].summary,'가');
});
test('URL state round trips and preserves unrelated query/hash; invalid sort defaults', () => {
  const f={q:'문화 체험',region:'강서구',category:'문화·체험',sort:'verified',status:'urgent'};
  const url=filterUrl(new URL('https://example.org/benefit-monitor/?x=1#results'),f);
  assert.deepEqual(readFilters(url.search),f); assert.equal(url.hash,'#results');assert.equal(url.searchParams.get('x'),'1');
  assert.equal(readFilters('?sort=evil').sort,'deadline');
});
test('unknown schema, malformed dates and future file timestamps fail closed', () => {
  for (const value of [null, {}, snapshot([],{schema_version:2}),snapshot([],{generated_at:'2099-01-01T00:00:00Z'}),snapshot([],{valid_through:'tomorrow'}),snapshot([],{generated_at:'2026-11-04T06:00:00'})]) assert.throws(()=>adapt(value,NOW));
});
test('official link validation rejects credentials, non-default ports and deceptive hostnames', () => {
  for(const url of ['https://mediahub.seoul.go.kr.evil.example/','https://user@mediahub.seoul.go.kr/','https://mediahub.seoul.go.kr:8443/','http://mediahub.seoul.go.kr/']) assert.equal(safeOfficial(url,'seoul'),false);
  assert.equal(safeOfficial('https://mediahub.seoul.go.kr/archives/1','seoul'),true);
});
test('invalid calendar timestamps and fixed records without end dates are withheld',()=>{
 assert.throws(()=>adapt(snapshot([],{generated_at:'2026-02-30T07:00:00+09:00'}),NOW));
 assert.equal(adapt(snapshot([item({valid_until:null,deadline_at:null,validity_kind:'fixed'})]),NOW).items.length,0);
});
test('recent verification filter is a rolling 24h window; unknown region stays exact',()=>{
 const rows=adapt(snapshot([item({verified_at:'2026-11-03T11:59:59+09:00',labels:{region:'서울·경기'},districts:[]})]),NOW).items;
 assert.equal(select(rows,{...readFilters(''),status:'new'},NOW).length,0);
 assert.equal(select(rows,{...readFilters(''),region:'전국'},NOW).length,0);
 assert.equal(select(rows,{...readFilters(''),region:'서울·경기'},NOW).length,1);
});
test('Seoul aggregate option follows exact Seoul policy rather than any city ending in 구',()=>{
 const rows=adapt(snapshot([item({source:'government',url:'https://www.korea.kr/briefing/pressReleaseView.do?newsId=1',districts:[],labels:{region:'대구'}})]),NOW).items;
 assert.equal(rows.length,1);assert.equal(regionOptions(rows).includes('서울'),false);
 const seoul=adapt(snapshot([item({districts:[],labels:{region:'서울시'}})]),NOW).items;
 assert.equal(regionOptions(seoul).includes('서울'),true);
});

test('alphabetic ordering uses the displayed card headline, not the original official headline',()=>{
 const rows=adapt(snapshot([item({title:'가 원문',summary:'하 카드'}),item({url:'https://mediahub.seoul.go.kr/archives/2',title:'하 원문',summary:'가 카드'})]),NOW).items;
 assert.equal(select(rows,{...readFilters(''),sort:'title'},NOW)[0].summary,'가 카드');
});
const aiReview = (over: Record<string, unknown> = {}) => ({ kind: 'ai_auto', candidate_id: 'c1', title_key: 'k1', document_count: 2, checked_at: '2026-11-04T05:00:00+09:00', documents: [{ url: 'https://mediahub.seoul.go.kr/archives/1', title: '원문 1' }, { url: 'https://www.gangseo.seoul.kr/a', title: '원문 2' }], ...over });
test('review defaults to human and validates ai_auto documents', () => {
  const rows = adapt(snapshot([item(), item({ url: 'https://mediahub.seoul.go.kr/archives/2', review: { kind: 'human' } }), item({ url: 'https://mediahub.seoul.go.kr/archives/3', review: aiReview() })]), NOW);
  assert.equal(rows.withheldCount, 0);
  assert.deepEqual(rows.items[0].review, { kind: 'human' });
  assert.deepEqual(rows.items[1].review, { kind: 'human' });
  assert.deepEqual(rows.items[2].review, { kind: 'ai_auto', documentCount: 2, checkedAt: '2026-11-04T05:00:00+09:00', documents: [{ url: 'https://mediahub.seoul.go.kr/archives/1', title: '원문 1' }, { url: 'https://www.gangseo.seoul.kr/a', title: '원문 2' }] });
});
test('ai_auto with foreign document url is withheld', () => {
  const bad = [
    aiReview({ documents: [{ url: 'https://evil.example/x', title: 'x' }] }),
    aiReview({ documents: [{ url: 'http://mediahub.seoul.go.kr/a', title: 'x' }] }),
    aiReview({ documents: [] }), aiReview({ document_count: 0 }), aiReview({ document_count: 3 }), aiReview({ document_count: 1.5 }), aiReview({ document_count: '2' }),
    aiReview({ checked_at: '2026-11-05T00:00:00+09:00' }), aiReview({ checked_at: 'nope' }),
    { kind: 'robot' }, 'ai_auto',
  ].map((review, n) => item({ url: 'https://mediahub.seoul.go.kr/archives/' + (10 + n), review }));
  const result = adapt(snapshot(bad), NOW);
  assert.equal(result.items.length, 0); assert.equal(result.withheldCount, bad.length);
});
test('ai_auto document_count may be below documents length (distinct bodies) and is what the badge counts', () => {
  const r = adapt(snapshot([item({ review: aiReview({ document_count: 1 }) })]), NOW);
  assert.equal(r.withheldCount, 0);
  const rv = r.items[0].review; assert.equal(rv.kind === 'ai_auto' && rv.documentCount, 1);
  assert.equal(rv.kind === 'ai_auto' && rv.documents.length, 2);
});

test('AI quality summary keeps counts and only official-link findings', () => {
  const ai_quality = { last_run_checked: 12, held: 1, dismissed: 5, prioritized: 3, findings: [
    { item_id: 'a', source: 'seoul', url: 'https://mediahub.seoul.go.kr/archives/9', title: '[테스트] 제휴 할인',
      claims: [{ claim: 'GOLD 100원', official_quotes: ['GOLD 50원'] }] },
    { item_id: 'b', source: 'seoul', url: 'https://evil.example/x', title: '[테스트] 외부', claims: [] }] };
  const q = adapt(snapshot([item()], { ai_quality }), NOW).aiQuality;
  assert.deepEqual([q.checked, q.held, q.dismissed, q.prioritized], [12, 1, 5, 3]);
  assert.deepEqual(q.findings.map(f => f.url), ['https://mediahub.seoul.go.kr/archives/9', '']);
  assert.deepEqual(q.findings[0].claims, [{ claim: 'GOLD 100원', quotes: ['GOLD 50원'] }]);
  assert.deepEqual(adapt(snapshot([item()]), NOW).aiQuality, { checked: null, held: 0, dismissed: 0, prioritized: 0, findings: [] });
});
test('card badge, verified age and header time are short forms of the same dates', async () => {
 const {timingBadge,verifiedAge,updatedLabel}=await import('../src/benefits.ts');
 const one=(o:Record<string,unknown>)=>adapt(snapshot([item(o)]),NOW).items[0];
 assert.deepEqual(timingBadge(one({}),NOW),{label:'신청 마감 2일 남음',urgent:true});
 assert.deepEqual(timingBadge(one({deadline_at:'2026-11-04T18:00:00+09:00',display_until:'2026-11-04T18:00:00+09:00'}),NOW),{label:'오늘 신청 마감',urgent:true});
 assert.deepEqual(timingBadge(one({deadline_at:null,valid_until:'2026-11-04'}),NOW),{label:'오늘 끝남',urgent:true});
 assert.deepEqual(timingBadge(one({deadline_at:null,valid_until:'2026-11-06'}),NOW),{label:'2일 남음',urgent:true});
 assert.deepEqual(timingBadge(one({deadline_at:null,valid_until:'2026-12-31',display_until:'2026-11-10T00:00:00+09:00'}),NOW),{label:'12.31까지',urgent:false});
 assert.deepEqual(timingBadge(one({deadline_at:null,valid_from:null,valid_until:null,validity_kind:'ongoing'}),NOW),{label:'상시',urgent:false});
 assert.equal(verifiedAge(one({}),NOW),'오늘 확인');
 assert.equal(verifiedAge(one({verified_at:'2026-10-25T06:00:00+09:00'}),NOW),'10일 전 확인');
 assert.equal(updatedLabel('2026-11-04T05:08:14+09:00',NOW),'오늘 05:08 갱신');
 assert.equal(updatedLabel('2026-11-03T05:08:14+09:00',NOW),'11.3 05:08 갱신');
 assert.equal(updatedLabel(null,NOW),'');
});

test('every category shows its emoji first', () => {
  assert.deepEqual(categories.map(categoryLabel), ['💸 할인·적립','🤝 생활지원','🎨 문화·체험','📚 교육·강좌','🙋 공모·참여','📌 기타']);
  assert.equal(categoryLabel('알 수 없음'), '📌 알 수 없음');
});
