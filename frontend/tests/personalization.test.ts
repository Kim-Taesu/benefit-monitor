import test from 'node:test';
import assert from 'node:assert/strict';
import {adapt} from '../src/benefits.ts';
import {emptyBeta,loadBeta,saveBeta,BETA_KEY,topicsFor,rememberItems,itemFreshness,recentSeen,recordEvent,hasPersonalization} from '../src/beta.ts';
import {publishedTopics} from '../src/published-topics.ts';
import {item,snapshot,NOW} from './fixtures.ts';
const data=()=>adapt(snapshot([
 item({title:'야간 전시',summary:'야간 전시',districts:['은평구']}),
 item({url:'https://mediahub.seoul.go.kr/archives/2',title:'편의점 할인',summary:'편의점 할인',districts:['강서구'],labels:{category:'할인·적립'}}),
 item({url:'https://mediahub.seoul.go.kr/archives/3',title:'가족 공원 체험',summary:'가족 공원 체험',districts:['마포구']})
]),NOW).items;
const store=()=>{const values=new Map<string,string>();return {getItem:(key:string)=>values.get(key)??null,setItem:(key:string,value:string)=>{values.set(key,value);},removeItem:(key:string)=>{values.delete(key);}};};

test('three contrasting profiles rank the same candidates by declared interests, not eligibility or fees',()=>{
 const rows=data(),before=JSON.stringify(rows);
 for(const interest of ['night','convenience','family'] as const){
  const state=emptyBeta();state.profile.interests=[interest];
  const ranked=topicsFor(rows,state.profile,[],NOW);
  assert.equal(ranked[0].id,interest);assert.match(ranked[0].reason,/직접 선택|확인/);
  assert.ok(ranked[0].items.every(i=>i.fee_status==='paid'));
 }
 assert.equal(JSON.stringify(rows),before);
});
test('explicit exclusion wins over pins and removes overlapping items from other recommendations',()=>{
 const state=emptyBeta();state.profile.interests=['family'];state.profile.excludedTopics=['family'];
 const topics=topicsFor(data(),state.profile,[],NOW);
 assert.ok(!topics.some(t=>t.id==='family'));
 assert.ok(topics.every(t=>t.items.every(i=>!i.summary.includes('가족'))));
 assert.equal(data().length,3); // The unfiltered discovery collection is not mutated.
});
test('published semantic membership also blocks overlapping items with no keyword match',()=>{
 const row=item({title:'공식 프로그램',summary:'공식 프로그램'});
 const raw=snapshot([row],{topic_cards:{schema_version:1,generated_at:'2026-11-04T08:00:00+09:00',valid_until:'2026-11-04T18:00:00+09:00',topics:['culture','family'].map(id=>({id,title:id==='culture'?'문화·체험':'가족과 함께',items:[{source:row.source,url:row.url,facts:row}]}))}});
 const state=emptyBeta();state.profile.excludedTopics=['family'];
 assert.deepEqual(publishedTopics(raw,adapt(raw,NOW).items,state.profile,NOW),[]);
});
test('v1 migration preserves profile and consent, rejects unknown fields and does not invent history',()=>{
 const storage=store(),profile={residence:'은평구',areas:[],age:20,carrier:'KT',interests:['night']};
 storage.setItem(BETA_KEY,JSON.stringify({version:1,profile,consent:true,events:[]}));
 const loaded=loadBeta(storage,NOW);assert.equal(loaded.version,2);assert.equal(loaded.profile.residence,'은평구');
 assert.deepEqual(loaded.profile.excludedTopics,[]);assert.deepEqual(loaded.seen,[]);assert.equal(saveBeta(storage,loaded),true);
 storage.setItem(BETA_KEY,JSON.stringify({version:1,profile:{...profile,secret:'bad'},consent:true,events:[]}));
 assert.deepEqual(loadBeta(storage,NOW),emptyBeta());
});
test('explicit feedback works immediately; withdrawing consent removes its ranking effect',()=>{
 const rows=data();let state=emptyBeta();state.consent=true;
 state=recordEvent(state,'family','like',NOW);
 assert.equal(topicsFor(rows,state.profile,state.events,NOW)[0].id,'family');
 const storage=store();saveBeta(storage,{...state,consent:false});state=loadBeta(storage,NOW);
 assert.deepEqual(state.events,[]);assert.equal(topicsFor(rows,state.profile,state.events,NOW)[0].id,'night');
});
test('seen and changed are consent-bound, content-based, private, bounded and expire',()=>{
 const row=data()[0];let state=emptyBeta();
 assert.equal(itemFreshness(row,state,NOW),'unknown');assert.deepEqual(rememberItems(state,[row],NOW).seen,[]);
 state.consent=true;assert.equal(itemFreshness(row,state,NOW),'new');state=rememberItems(state,[row],NOW);
 assert.equal(itemFreshness(row,state,NOW),'seen');
 assert.equal(itemFreshness({...row,verified_at:'2026-11-04T09:00:00+09:00',display_until:'2026-11-07T18:00:00+09:00'},state,NOW),'seen');
 for(const change of [{summary:'내용 수정'},{conditions:'새 조건'},{valid_until:'2026-11-08'},{fee_status:'free'}])assert.equal(itemFreshness({...row,...change},state,NOW),'changed');
 assert.equal(itemFreshness(row,state,NOW+31*86400000),'new');
 assert.deepEqual(recentSeen(state.seen,NOW-1),[]);
 assert.ok(!JSON.stringify(state.seen).includes(row.url));assert.ok(!JSON.stringify(state.seen).includes(row.summary));
 state=rememberItems(state,Array.from({length:510},(_,n)=>({...row,url:row.url+'/'+n})),NOW);
 assert.equal(state.seen.length,500);
 const storage=store();saveBeta(storage,{...state,consent:false});assert.deepEqual(loadBeta(storage,NOW).seen,[]);
});
test('malformed history never enters storage, including payload text and future timestamps on load',()=>{
 const storage=store();let state=emptyBeta();state.consent=true;state=rememberItems(state,data(),NOW+1);saveBeta(storage,state);
 assert.deepEqual(loadBeta(storage,NOW).seen,[]);
 (state.seen[0] as any).body='unexpected text';assert.equal(saveBeta(storage,state),false);
});

test('twenty passive impressions count as personalization for both recommendation surfaces',()=>{
 let state=emptyBeta();state.consent=true;
 for(let n=0;n<20;n++)state=recordEvent(state,'night','view',NOW-20+n);
 assert.equal(hasPersonalization(state,NOW),true);
 assert.ok(topicsFor(data(),state.profile,state.events,NOW).find(t=>t.id==='night')!.score<0);
 assert.equal(hasPersonalization({...state,consent:false},NOW),false);
 assert.equal(hasPersonalization(state,NOW+31*86400000),false);
});
