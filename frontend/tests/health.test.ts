import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHealth,filterHealth} from '../src/health.ts';

const NOW=Date.parse('2026-11-11T09:00:00+09:00');
const item=(over:Record<string,unknown>={})=>({id:'health-ht060701-1',title:'독감 무료 접종 안내',url:'https://www.gangseo.seoul.kr/health/ht060701/1',date:'2026-11-05',dept:'보건관리과',hint:true,...over});
const board=(over:Record<string,unknown>={})=>({district:'강서구',name:'강서구보건소',list_url:'https://www.gangseo.seoul.kr/health/ht060701',home_url:'https://www.gangseo.seoul.kr/health',status:'checked',reason:null,checked_at:'2026-11-11T00:07:00+09:00',items:[item()],...over});
const raw=(boards:unknown[],over:Record<string,unknown>={})=>({health_notices:{schema_version:1,source:'health_notices',fetched_at:'2026-11-11T00:07:00+09:00',notice:'보건소 공지',boards,...over}});

test('hint notices first, then newest; unavailable boards kept for status',()=>{
 const plain=item({id:'b',title:'에볼라 안내',date:'2026-11-09',hint:false,url:'https://www.gangseo.seoul.kr/health/ht060701/2'});
 const blocked=board({district:'은평구',name:'은평구보건소',list_url:'https://www.ep.go.kr/health/index.do',home_url:'https://www.ep.go.kr/health/index.do',status:'unavailable',reason:'robots',checked_at:null,items:[]});
 const r=parseHealth(raw([board({items:[plain,item()]}),blocked]),NOW)!;
 assert.deepEqual(r.items.map(i=>i.title),['독감 무료 접종 안내','에볼라 안내']);
 assert.deepEqual(r.boards.map(b=>[b.district,b.status]),[['강서구','checked'],['은평구','unavailable']]);
 assert.deepEqual(filterHealth(r.items,'강서구',true,'').map(i=>i.title),['독감 무료 접종 안내']);
 assert.equal(filterHealth(r.items,'',false,'에볼라').length,1);
});

test('stale, foreign-host or malformed bundles are rejected',()=>{
 assert.equal(parseHealth(raw([board()],{fetched_at:'2026-11-09T00:00:00+09:00'}),NOW),null);
 assert.equal(parseHealth(raw([board({items:[item({url:'https://evil.example/x'})]})]),NOW),null);
 assert.equal(parseHealth(raw([board({items:[item({url:'javascript:alert(1)'})]})]),NOW),null);
 assert.equal(parseHealth(raw([board({status:'ok'})]),NOW),null);
 assert.equal(parseHealth(raw([board(),board()]),NOW),null);
 assert.equal(parseHealth({},NOW),null);
});

test('programmes: kept per known district, stale after 10 days, malformed rejected',()=>{
 const prog=(over:Record<string,unknown>={})=>({district:'강서구',center:'강서구보건소',name:'대사증후군 관리',url:'https://www.gangseo.seoul.kr/health/ht020103',status:'checked',checked_at:'2026-11-11T00:07:00+09:00',...over});
 const r=parseHealth(raw([board()],{programs:[prog(),prog({name:'임신 사전건강관리 지원',url:'https://www.gangseo.seoul.kr/health/ht020231',checked_at:'2026-10-20T00:07:00+09:00'})]}),NOW)!;
 assert.deepEqual(r.programs.map(p=>[p.name,p.stale]),[['대사증후군 관리',false],['임신 사전건강관리 지원',true]]);
 assert.equal(parseHealth(raw([board()]),NOW)!.programs.length,0);
 assert.equal(parseHealth(raw([board()],{programs:[prog({district:'없는구'})]}),NOW),null);
 assert.equal(parseHealth(raw([board()],{programs:[prog({checked_at:null})]}),NOW),null);
 assert.equal(parseHealth(raw([board()],{programs:[prog({url:'javascript:x'})]}),NOW),null);
});
