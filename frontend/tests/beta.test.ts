import test from 'node:test';
import assert from 'node:assert/strict';
import {adapt} from '../src/benefits.ts';
import {item,snapshot,NOW} from './fixtures.ts';
import {DISTRICTS,emptyBeta,loadBeta,saveBeta,recordEvent,topicsFor,summarizeEvents,searchTopics,BETA_KEY} from '../src/beta.ts';
function storage(){const data=new Map<string,string>();return {getItem:(k:string)=>data.get(k)??null,setItem:(k:string,v:string)=>{data.set(k,v);},removeItem:(k:string)=>{data.delete(k);}};}
const benefits=()=>adapt(snapshot([
 item({summary:'[테스트] 은평 야간 전시',districts:['은평구']}),
 item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'[테스트] KT 멤버십 할인',districts:[],labels:{category:'할인·적립',region:'전국'}}),
 item({url:'https://mediahub.seoul.go.kr/archives/3',summary:'[테스트] 19~24세 청년 교육',districts:['은평구'],conditions:'만 19~24세 대상. 소득 별도 확인.',labels:{category:'교육·강좌'}}),
 item({url:'https://mediahub.seoul.go.kr/archives/4',summary:'[테스트] 성남 야간 행사',districts:['성남시'],labels:{region:'성남시'}})
]),NOW).items;
test('25 districts and strict profile storage, blocked/corrupt storage',()=>{
 assert.equal(new Set(DISTRICTS).size,25);const s=storage(),b=emptyBeta();b.profile.residence='은평구';b.profile.age=20;
 assert.equal(saveBeta(s,b),true);assert.equal(loadBeta(s,NOW).profile.age,20);
 assert.equal(saveBeta(null,b),false);s.setItem(BETA_KEY,'bad');assert.deepEqual(loadBeta(s,NOW),emptyBeta());
 b.profile.residence='성남시';assert.equal(saveBeta(s,b),false);
 b.profile.residence='';b.profile.age=13;assert.equal(saveBeta(s,b),false);
});
test('consent, retention, cap and withdrawal exclude history',()=>{
 let b=emptyBeta();assert.equal(recordEvent(b,'night','click',NOW).events.length,0);
 b.consent=true;b=recordEvent(b,'night','click',NOW);assert.equal(b.events.length,1);
 for(let n=0;n<510;n++) b=recordEvent(b,'culture','view',NOW+n);
 assert.equal(b.events.length,500);assert.equal(loadBeta(null,NOW).consent,false);
 const s=storage();saveBeta(s,b);assert.equal(loadBeta(s,NOW+31*86400000).events.length,0);
 b.consent=false;saveBeta(s,b);assert.equal(loadBeta(s,NOW).events.length,0);
});
test('Seoul candidate cards respect available data, profile interests and carrier',()=>{
 const p=emptyBeta().profile;p.residence='은평구';p.age=20;p.carrier='KT';p.interests=['night'];
 const t=topicsFor(benefits(),p,[],NOW);
 assert.equal(t.find(x=>x.id==='night')?.items.length,1);
 assert.equal(t.find(x=>x.id==='carrier')?.items.length,1);
 assert.equal(t.find(x=>x.id==='age')?.items.length,1);
 assert.ok(t.find(x=>x.id==='night')?.pinned);
 assert.ok(t.every(x=>x.reason.includes('확인')));
 p.age=30;assert.ok(!topicsFor(benefits(),p,[],NOW).some(x=>x.id==='age'));
 assert.deepEqual(topicsFor([],p,[],NOW),[]);
});
test('age range matches are candidates not claims; unsupported ranges are not inferred',()=>{
 const p=emptyBeta().profile;p.age=20;
 const rows=adapt(snapshot([item({conditions:'청년 대상, 세부 연령 미확인'})]),NOW).items;
 assert.ok(!topicsFor(rows,p,[],NOW).some(x=>x.id==='age'));
});
test('interest district is separate from residence and never rewrites profile',()=>{
 const p=emptyBeta().profile;p.residence='강서구';p.areas=['은평구'];
 const t=topicsFor(benefits(),p,[],NOW);
 assert.equal(t.find(x=>x.id==='local')?.items.length,2);assert.equal(p.residence,'강서구');
});
test('search log stores only finite topic enums, never search text',()=>{
 assert.deepEqual(searchTopics('야간 산책 전화번호 010-1234-5678'),['night']);
 assert.deepEqual(searchTopics('홍길동 010-1234-5678'),[]);
});
test('synthetic aggregate distinguishes impressions from clicks; low samples do not replace topics',()=>{
 let b=emptyBeta();b.consent=true;
 for(let n=0;n<3;n++)b=recordEvent(b,'night','view',NOW+n);
 b=recordEvent(b,'night','click',NOW+4);
 const report=summarizeEvents(b.events,NOW+5).find(x=>x.id==='night')!;
 assert.equal(report.views,3);assert.equal(report.clicks,1);assert.equal(report.decision,'자료 부족');
 for(let n=0;n<20;n++)b=recordEvent(b,'night','view',NOW+6+n);
 assert.equal(summarizeEvents(b.events,NOW+30).find(x=>x.id==='night')?.decision,'교체 검토');
 const p=b.profile;p.interests=['night'];assert.ok(topicsFor(benefits(),p,b.events,NOW+30).find(x=>x.id==='night')?.pinned);
});
test('adapter expiry and verification gates cannot be bypassed by recommendations',()=>{
 const p=emptyBeta().profile;p.interests=['night'];
 assert.deepEqual(topicsFor(adapt(snapshot([item({summary:'야간',needs_recheck:true})]),NOW).items,p,[],NOW),[]);
 assert.deepEqual(topicsFor(adapt(snapshot([item({summary:'야간',display_until:'2026-11-04T11:00:00+09:00'})]),NOW).items,p,[],NOW),[]);
});
test('real Seoul and nationwide scope labels remain eligible, other cities do not',()=>{
 const p=emptyBeta().profile;p.interests=['shopping'];
 for(const region of ['전국 참여 유통업체','전국 CU(일부 점포 제외)','전국 이마트24','서울 야간명소·25개 구 코스']){
  const rows=adapt(snapshot([item({summary:'할인 야간',districts:[],labels:{region}})]),NOW).items;
  assert.ok(topicsFor(rows,p,[],NOW).length>0,region);
 }
 for(const region of ['성남시','서울 근교 성남시','전국 제외 서울불가']){
  const rows=adapt(snapshot([item({summary:'할인 야간',districts:[],labels:{region}})]),NOW).items;
  assert.equal(topicsFor(rows,p,[],NOW).length,0,region);
 }
});
