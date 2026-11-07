import test from 'node:test';
import assert from 'node:assert/strict';
import {parseFestivals,festivalStatus,festivalPeriod,provinces,FESTIVAL_DETAIL} from '../src/festivals.ts';

const NOW=Date.parse('2026-11-07T12:00:00+09:00');
const ID='5c6f720a-dd3e-4e54-bd2e-0ed7a72147ee';
function festival(over:Record<string,unknown>={}){
 const id=(over.id as string)??ID;
 return {id,name:'구미라면 축제',start:'2026-11-06',end:'2026-11-08',region:'경상북도 구미시',place:'구미역 일원',organizer:'구미시',
  fee_status:'free',fee_text:'무료',discount:'',summary:'라면 축제',programs:'라면 레스토랑',homepage:'https://www.gumiramyun.com/',
  culture_tourism:true,url:FESTIVAL_DETAIL+id,modified:'2026-10-30',...over};
}
function raw(items:unknown[],over:Record<string,unknown>={}){
 return {festivals:{schema_version:1,source:'kfes',fetched_at:'2026-11-07T06:00:00+09:00',notice:'관광공사 게시 정보',items,...over}};
}

test('valid festivals are kept, ended ones dropped, ongoing sorted by end date',()=>{
 const later=festival({id:'00000000-0000-4000-8000-000000000001',name:'포항국제불빛축제',start:'2026-11-19',end:'2026-11-21',region:'경상북도 포항시'});
 const ended=festival({id:'00000000-0000-4000-8000-000000000002',start:'2026-11-01',end:'2026-11-06'});
 const result=parseFestivals(raw([later,festival(),ended]),NOW);
 assert.deepEqual(result?.items.map(i=>i.name),['구미라면 축제','포항국제불빛축제']);
 assert.equal(result?.items[0].province,'경상북도');
 assert.deepEqual(provinces(result!.items),['경상북도']);
});

test('status and period labels',()=>{
 const [item]=parseFestivals(raw([festival()]),NOW)!.items;
 assert.deepEqual(festivalStatus(item,NOW),{ongoing:true,label:'개최중 · 1일 남음'});
 assert.equal(festivalPeriod(item),'2026.11.06 ~ 2026.11.08');
 const [soon]=parseFestivals(raw([festival({start:'2026-11-13',end:'2026-11-13'})]),NOW)!.items;
 assert.deepEqual(festivalStatus(soon,NOW),{ongoing:false,label:'6일 후 시작'});
 assert.equal(festivalPeriod(soon),'2026.11.13');
});

test('malformed items are skipped and unsafe links rejected',()=>{
 const bad=[festival({url:'https://evil.example/x'}),festival({homepage:'http://plain.example'}),festival({fee_status:'cheap'}),
  festival({extra:1}),festival({start:'2026/11/06'}),festival({name:' '})];
 assert.deepEqual(parseFestivals(raw(bad),NOW)?.items,[]);
});

test('stale, future or foreign bundles are ignored',()=>{
 assert.equal(parseFestivals(raw([festival()],{fetched_at:'2026-11-05T06:00:00+09:00'}),NOW),null);
 assert.equal(parseFestivals(raw([festival()],{fetched_at:'2026-11-08T06:00:00+09:00'}),NOW),null);
 assert.equal(parseFestivals(raw([festival()],{source:'other'}),NOW),null);
 assert.equal(parseFestivals({},NOW),null);
});
