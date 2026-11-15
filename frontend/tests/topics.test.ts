import test from 'node:test';
import assert from 'node:assert/strict';
import {adapt} from '../src/benefits.ts';
import {item,snapshot,NOW} from './fixtures.ts';
import {DISTRICTS,isSeoulCandidate,matchesHome,ruleTopics,publishedTopics,topicsFor,TOPIC_ICONS,MAJOR_TOPIC_COUNT} from '../src/topics.ts';

function data(){const row=item();return snapshot([row],{topic_cards:{schema_version:1,generated_at:'2026-11-04T08:00:00+09:00',valid_until:'2026-11-04T18:00:00+09:00',used_fallback:false,topics:[{id:'culture',title:'문화·체험',items:[{source:row.source,url:row.url,facts:row}]}]}});}

test('25 districts and every topic has an icon',()=>{
 assert.equal(DISTRICTS.length,25);
 for(const id of ['local','carrier','age','night','culture','learning','shopping','vouchers','convenience','outdoors','family','housing','career'] as const)assert.ok(TOPIC_ICONS[id],id);
 assert.equal(MAJOR_TOPIC_COUNT,2);
});
test('adapter expiry and verification gates cannot be bypassed by topics',()=>{
 assert.deepEqual(ruleTopics(adapt(snapshot([item({summary:'야간',needs_recheck:true})]),NOW).items),[]);
 assert.deepEqual(ruleTopics(adapt(snapshot([item({summary:'야간',display_until:'2026-11-04T11:00:00+09:00'})]),NOW).items),[]);
});
test('real Seoul and nationwide scope labels remain eligible, other cities do not',()=>{
 for(const region of ['전국 참여 유통업체','전국 CU(일부 점포 제외)','전국 이마트24','서울 야간명소·25개 구 코스']){
  const rows=adapt(snapshot([item({summary:'할인 야간',districts:[],labels:{region}})]),NOW).items;
  assert.ok(rows.every(isSeoulCandidate)&&ruleTopics(rows).length>0,region);
 }
 for(const region of ['성남시','서울 근교 성남시','전국 제외 서울불가']){
  const rows=adapt(snapshot([item({summary:'할인 야간',districts:[],labels:{region}})]),NOW).items;
  assert.equal(ruleTopics(rows).length,0,region);
 }
});
test('rule topics are backed by notice subjects, not unrelated eligibility text, and never use a profile',()=>{
 const rows=adapt(snapshot([
  item({summary:'서울사랑상품권 추가 페이백'}),
  item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'CU KT 멤버십 할인'}),
  item({url:'https://mediahub.seoul.go.kr/archives/3',summary:'월드컵경기장역 러너 지원 공간'}),
  item({url:'https://mediahub.seoul.go.kr/archives/4',summary:'어린이 기록체험실 가족 관람'}),
  item({url:'https://mediahub.seoul.go.kr/archives/5',summary:'청년 매입임대 입주자 모집'}),
  item({url:'https://mediahub.seoul.go.kr/archives/6',summary:'청년 화상면접실 이용',conditions:'임대주택 거주자도 가능'}),
 ]),NOW).items;
 const topics=ruleTopics(rows),ids=topics.map(t=>t.id);
 for(const id of ['vouchers','convenience','outdoors','family','housing','career'] as const)assert.ok(ids.includes(id),id);
 assert.equal(topics.find(t=>t.id==='housing')!.items.length,1);
 for(const id of ['local','carrier','age'] as const)assert.ok(!ids.includes(id),id);
});
test('approved topic cards use only currently adapted benefits',()=>{
 const raw=data(),items=adapt(raw,NOW).items;
 const result=publishedTopics(raw,items,NOW);
 assert.equal(result?.[0].title,'문화·체험');assert.equal(result?.[0].items.length,1);
 assert.equal(publishedTopics(raw,[],NOW),null);
});
test('expired, malformed or empty bundles fall back to rules',()=>{
 const raw=data();assert.equal(publishedTopics(raw,adapt(raw,NOW).items,NOW+86400000),null);
 raw.topic_cards.topics[0].title='누구나 무료 보장';assert.equal(publishedTopics(raw,adapt(raw,NOW).items,NOW),null);
 assert.equal(publishedTopics(snapshot(),adapt(snapshot(),NOW).items,NOW),null);
 const empty=data();empty.topic_cards.topics=[];assert.equal(publishedTopics(empty,adapt(empty,NOW).items,NOW),null);
 assert.equal(topicsFor(empty,adapt(empty,NOW).items,NOW)[0].id,'culture');
});
test('changed facts and foreign references cannot be resurrected by a card',()=>{
 const raw=data();raw.items[0]={...raw.items[0],conditions:'가격과 대상이 변경됨'};
 assert.equal(publishedTopics(raw,adapt(raw,NOW).items,NOW),null);
 const fresh=data();fresh.topic_cards.topics[0].items[0].url='https://evil.example/item';
 assert.equal(publishedTopics(fresh,adapt(fresh,NOW).items,NOW),null);
});
test('topics are ordered by how many benefits they hold, never by fee',()=>{
 const rows=adapt(snapshot([
  item({summary:'야간 전시',fee_status:'paid'}),
  item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'전시 체험',fee_status:'paid'}),
  item({url:'https://mediahub.seoul.go.kr/archives/3',summary:'교육 강좌',conditions:'',labels:{category:'교육·강좌'},fee_status:'free'}),
 ]),NOW).items;
 const topics=topicsFor(snapshot(),rows,NOW);
 assert.equal(topics[0].id,'culture');assert.ok(topics[0].items.length>=topics[1].items.length);
});
test('my district shows that district plus notices not tied to any district',()=>{
 const rows=adapt(snapshot([
  item({districts:['강서구'],labels:{region:'강서구'}}),
  item({url:'https://mediahub.seoul.go.kr/archives/2',districts:['은평구'],labels:{region:'은평구'}}),
  item({url:'https://mediahub.seoul.go.kr/archives/3',districts:[],labels:{region:'서울'}}),
  item({url:'https://mediahub.seoul.go.kr/archives/4',districts:[],labels:{region:'전국 이마트24'}}),
 ]),NOW).items;
 assert.deepEqual(rows.filter(i=>matchesHome(i,'강서구')).map(i=>i.url.slice(-1)),['1','3','4']);
 assert.equal(rows.filter(i=>matchesHome(i,'')).length,4);
 assert.deepEqual(rows.filter(i=>matchesHome(i,'도봉구')).map(i=>i.url.slice(-1)),['3','4']);
});
