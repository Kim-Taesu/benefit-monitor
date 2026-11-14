import test from 'node:test';
import assert from 'node:assert/strict';
import {parseFestivals,FESTIVAL_DETAIL} from '../src/festivals.ts';
import {parseFestivalPick,parseBenefitPick,festivalLine,benefitDeadline,benefitFeeLabel} from '../src/picks.ts';
import type {Benefit} from '../src/benefits.ts';

const NOW=Date.parse('2026-11-14T09:00:00+09:00');
const fid=(n:number)=>`00000000-0000-4000-8000-00000000000${n}`;
function festival(n:number,over:Record<string,unknown>={}){
 return {id:fid(n),name:`축제 ${n}`,start:'2026-11-15',end:'2026-11-17',region:'경상북도 구미시',place:'역 앞',organizer:'시청',fee_status:'free',fee_text:'무료',discount:'',summary:'소개',programs:'공연',homepage:'',culture_tourism:false,url:FESTIVAL_DETAIL+fid(n),modified:null,...over};
}
const bundle=parseFestivals({festivals:{schema_version:1,source:'kfes',fetched_at:'2026-11-14T06:00:00+09:00',notice:'n',items:[festival(1),festival(2,{start:'2026-11-16',end:'2026-11-16'})]}},NOW)!;
const fraw=(over:Record<string,unknown>={})=>({festival_pick:{schema_version:1,generated_at:'2026-11-14T07:00:00+09:00',day:'2026-11-14',source:'ai',summary:'주말에 가기 좋은 축제예요.',picks:[{id:fid(1),line:'공연이 볼 만해요'},{id:fid(2),line:null},{id:fid(9),line:'없는 축제'}],...over}});

test('festival pick drops unknown ids and keeps lines',()=>{
 const p=parseFestivalPick(fraw(),bundle)!;
 assert.equal(p.source,'ai');
 assert.deepEqual(p.picks.map(x=>[x.festival.id,x.line]),[[fid(1),'공연이 볼 만해요'],[fid(2),null]]);
});
test('festival pick rejects zero lines, bad schema and unsafe text',()=>{
 assert.equal(parseFestivalPick(fraw({picks:[{id:fid(9),line:null}]}),bundle),null);
 assert.equal(parseFestivalPick(fraw({schema_version:2}),bundle),null);
 assert.equal(parseFestivalPick(fraw({source:'x'}),bundle),null);
 assert.equal(parseFestivalPick(fraw({summary:'<b>x</b>'}),bundle),null);
 assert.equal(parseFestivalPick({},bundle),null);
 const bad=parseFestivalPick(fraw({picks:[{id:fid(1),line:'<i>x</i>'},{id:fid(2),line:'ok'}]}),bundle)!;
 assert.deepEqual(bad.picks.map(x=>x.festival.id),[fid(2)]);
});
test('festival rule pick has no summary or lines',()=>{
 const p=parseFestivalPick(fraw({source:'rule',summary:null,picks:[{id:fid(1),line:null}]}),bundle)!;
 assert.deepEqual([p.source,p.summary,p.picks[0].line],['rule',null,null]);
 assert.equal(parseFestivalPick(fraw({source:'rule',summary:'x'}),bundle),null);
});
test('festival line formats period and single day',()=>{
 assert.equal(festivalLine(bundle.items[0]),'축제 1 (11/15~11/17 · 경상북도 구미시)');
 assert.equal(festivalLine(bundle.items[1]),'축제 2 (11/16 · 경상북도 구미시)');
});

function ben(over:Partial<Benefit>={}):Benefit{
 return {source:'seoul',sourceName:'서울시',url:'https://mediahub.seoul.go.kr/archives/1',title:'혜택 A',summary:'',conditions:'',districts:[],regions:[],category:'기타',labels:{},verified_at:'',display_until:'',valid_from:null,valid_until:null,deadline_at:null,validity_kind:'fixed',fee_status:'free',payment_terms:{},benefitValue:null,review:{kind:'human'},...over};
}
const items=[ben(),ben({source:'gangseo',url:'https://www.gangseo.seoul.kr/x',title:'혜택 B',fee_status:'paid',deadline_at:'2026-11-20T18:00:00+09:00'}),ben({url:'https://mediahub.seoul.go.kr/archives/3',title:'혜택 C',fee_status:'unknown',valid_until:'2026-12-01'})];
const braw=(over:Record<string,unknown>={})=>({benefit_pick:{schema_version:1,generated_at:'2026-11-14T07:00:00+09:00',day:'2026-11-14',source:'ai',summary:'놓치기 아까운 혜택이에요.',picks:[
 {id:'b1',source:'gangseo',url:'https://www.gangseo.seoul.kr/x',line:'구민이면 살펴보세요'},
 {id:'b2',source:'seoul',url:'https://mediahub.seoul.go.kr/archives/1',line:null},
 {id:'b3',source:'seoul',url:'https://nope.example/',line:'없는 혜택'},
 {id:'b4',source:'gangseo',url:'https://mediahub.seoul.go.kr/archives/1',line:'소스 불일치'}],...over}});

test('benefit pick matches by source and url',()=>{
 const p=parseBenefitPick(braw(),items)!;
 assert.deepEqual(p.picks.map(x=>[x.item.title,x.line]),[['혜택 B','구민이면 살펴보세요'],['혜택 A',null]]);
});
test('benefit pick rejects zero matches, bad schema and unsafe text',()=>{
 assert.equal(parseBenefitPick(braw({picks:[{id:'x',source:'seoul',url:'https://nope.example/',line:null}]}),items),null);
 assert.equal(parseBenefitPick(braw({schema_version:2}),items),null);
 assert.equal(parseBenefitPick(braw({summary:'<b>'}),items),null);
 assert.equal(parseBenefitPick({},items),null);
 const rule=parseBenefitPick(braw({source:'rule',summary:null,picks:[{id:'b1',source:'seoul',url:items[0].url,line:null}]}),items)!;
 assert.deepEqual([rule.source,rule.summary],['rule',null]);
});
test('benefit deadline and fee label come from data',()=>{
 assert.equal(benefitDeadline(items[1]),'~11/20');
 assert.equal(benefitDeadline(items[2]),'~12/1');
 assert.equal(benefitDeadline(items[0]),'');
 assert.equal(benefitFeeLabel(items[0]),'무료');
 assert.equal(benefitFeeLabel(items[1]),'유료·구매 필요');
 assert.equal(benefitFeeLabel(items[2]),'비용 미확인');
});
