import test from 'node:test';
import assert from 'node:assert/strict';
import {parseHealth,filterHealth,healthKind,firstSentence,weeklyPicks} from '../src/health.ts';

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

test('AI notes attach to fresh checked programmes only',()=>{
 const prog=(over:Record<string,unknown>={})=>({district:'강서구',center:'강서구보건소',name:'대사증후군 관리',url:'https://www.gangseo.seoul.kr/health/ht020103',status:'checked',checked_at:'2026-11-11T00:07:00+09:00',...over});
 const note=(over:Record<string,unknown>={})=>({url:'https://www.gangseo.seoul.kr/health/ht020103',district:'강서구',sentence:'강서구에 살거나 일하는 20~69세라면 대사증후군 검진을 무료로 받아보세요.',generated_at:'2026-11-11T05:00:00+09:00',...over});
 const parse=(notes:unknown[],p=prog())=>{const r=raw([board()],{programs:[p]}) as Record<string,unknown>;r.health_notes=notes;return parseHealth(r,NOW)!.programs[0].note;};
 assert.match(parse([note()])!,/무료로 받아보세요/);
 assert.equal(parse([note({district:'양천구'})]),null);
 assert.equal(parse([note({sentence:'<b>x</b> 짧음 아님 아주 긴 문장 이십오자 넘기기 위한 문장입니다'})]),null);
 assert.equal(parse([note()],prog({checked_at:'2026-10-20T00:07:00+09:00'})),null);
 assert.equal(parse([note({generated_at:'2026-10-01T00:00:00+09:00'})]),null);
});

const gj=()=>board({district:'광진구',name:'광진구보건소',list_url:'https://www.gwangjin.go.kr/health/list',home_url:'https://www.gwangjin.go.kr/health',items:[]});
const gjItem=(over:Record<string,unknown>={})=>item({url:'https://www.gwangjin.go.kr/health/n/1',...over});
const wprog=(name:string,n:number,over:Record<string,unknown>={})=>({district:'강서구',center:'강서구보건소',name,url:'https://www.gangseo.seoul.kr/health/p'+n,status:'checked',checked_at:'2026-11-11T00:07:00+09:00',...over});
const gjProg=(name:string,n:number,over:Record<string,unknown>={})=>wprog(name,100+n,{district:'광진구',center:'광진구보건소',url:'https://www.gwangjin.go.kr/health/p'+n,...over});
const wnote=(p:{url:string;district:string},sentence:string)=>({url:p.url,district:p.district,sentence,generated_at:'2026-11-11T05:00:00+09:00'});
const sent=(t:string)=>t+' 이 문장은 스물다섯 자를 넘기기 위한 문장입니다.';
const bundleOf=(boards:unknown[],programs:Record<string,unknown>[],notes:ReturnType<typeof wnote>[]=[])=>{
 const r=raw(boards,{programs}) as Record<string,unknown>;r.health_notes=notes;return parseHealth(r,NOW)!;
};

test('healthKind classifies by name words, first match wins',()=>{
 const cases:[string,string|null][]=[['대사증후군 관리','metabolic'],['[구로형] 임신 준비 지원','pregnancy'],['예비부부 건강검진','pregnancy'],['1인 청년가구 건강검진','youth'],['마음건강검진 상담지원','mind'],['모바일 헬스케어','mobile'],['금연클리닉','smoking'],['결핵검사','tb'],['B형간염검사','hepatitis'],['골밀도 검사','basic'],['내몸사랑 기초건강검진','basic'],['무료건강검진','basic'],['치매 조기검진',null]];
 for(const [n,k] of cases)assert.equal(healthKind(n),k,n);
});

test('firstSentence cuts at first terminal mark, keeps decimals, falls back when short',()=>{
 assert.equal(firstSentence('만 20세~69세 광진구민이라면 무료로 받아보세요. 평일 09:00~17:00에 예약하세요.'),'만 20세~69세 광진구민이라면 무료로 받아보세요.');
 assert.equal(firstSentence('1.5kg 이하 체중 변화를 확인해요. 전화 02-2600-5933.'),'1.5kg 이하 체중 변화를 확인해요.');
 assert.equal(firstSentence('짧아요. 두 번째 문장이 깁니다.'),'짧아요. 두 번째 문장이 깁니다.');
 assert.equal(firstSentence('마침표 없는 문장입니다 그대로 둡니다'),'마침표 없는 문장입니다 그대로 둡니다');
});

test('weeklyPicks aggregates kinds by district count, skipping failed',()=>{
 const m=wprog('대사증후군 관리',1),h1=wprog('B형간염검사',2),h2=wprog('C형간염검사',3),g=gjProg('대사증후군 관리',1,{status:'failed'});
 const r=weeklyPicks(bundleOf([board(),gj()],[m,h1,h2,g],[wnote({url:m.url,district:'강서구'},sent('대사증후군 검진을 무료로 받아보세요.'))]),'2026-11-11');
 assert.deepEqual(r.kinds,[{key:'metabolic',label:'대사증후군 검진·관리',districts:1},{key:'hepatitis',label:'간염검사',districts:1}]);
 assert.equal(r.hasSummary,true);
});

test('weeklyPicks sorts kinds by district count desc',()=>{
 const r=weeklyPicks(bundleOf([board(),gj()],[wprog('B형간염검사',1),gjProg('B형간염검사',1),gjProg('대사증후군 관리',2)]),'2026-11-11');
 assert.deepEqual(r.kinds.map(k=>[k.key,k.districts]),[['hepatitis',2],['metabolic',1]]);
});

test('weeklyPicks drops stale programmes',()=>{
 const r=weeklyPicks(bundleOf([board()],[wprog('대사증후군 관리',1,{checked_at:'2026-10-31T00:07:00+09:00'})]),'2026-11-11');
 assert.deepEqual(r.districts,[]);
 assert.deepEqual(r.kinds,[]);
});

test('weeklyPicks orders in district: summary first, caps at 3 with more',()=>{
 const ps=[wprog('가 결핵검사',1),wprog('나 대사증후군 관리',2),wprog('다 금연클리닉',3),wprog('라 간염검사',4)];
 const notes=[wnote({url:ps[3].url as string,district:'강서구'},sent('간염검사를 받아보세요.'))];
 const r=weeklyPicks(bundleOf([board()],ps,notes),'2026-11-11');
 const d=r.districts[0];
 assert.deepEqual(d.programs.map(p=>p.name),['라 간염검사','나 대사증후군 관리','다 금연클리닉']);
 assert.equal(d.more,1);
 assert.equal(d.programs[0].summary,'간염검사를 받아보세요.');
 assert.equal(d.programs[1].summary,null);
 assert.deepEqual(d.kinds.sort(),['hepatitis','metabolic','smoking','tb']);
});

test('weeklyPicks keeps districts without sentences, hasSummary false',()=>{
 const r=weeklyPicks(bundleOf([board()],[wprog('치매 조기검진',1)]),'2026-11-11');
 assert.equal(r.districts.length,1);
 assert.equal(r.districts[0].programs[0].summary,null);
 assert.equal(r.districts[0].programs[0].kind,null);
 assert.equal(r.hasSummary,false);
});

test('weeklyPicks counts new hint notices within last 7 days and ranks them first',()=>{
 const gp=gjProg('결핵검사',1),sp=wprog('대사증후군 관리',1);
 const notes=[wnote({url:sp.url as string,district:'강서구'},sent('대사증후군 검진을 받아보세요.'))];
 const gjBoard=board({district:'광진구',name:'광진구보건소',list_url:'https://www.gwangjin.go.kr/health/list',home_url:'https://www.gwangjin.go.kr/health',items:[
  gjItem({id:'a',date:'2026-11-05'}),gjItem({id:'b',date:'2026-11-04'}),gjItem({id:'c',date:'2026-11-12'}),gjItem({id:'d',date:'2026-11-08',hint:false})]});
 const r=weeklyPicks(bundleOf([board({items:[]}),gjBoard],[sp,gp],notes),'2026-11-11');
 assert.deepEqual(r.districts.map(d=>[d.district,d.newNotices]),[['광진구',1],['강서구',0]]);
});
