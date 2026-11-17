import test from 'node:test';
import assert from 'node:assert/strict';
import {parseSubscriptions,groupByDay,timeline,badge,formatPrice,formatArea,filterSubs,isMine} from '../src/subscriptions.ts';

const NOW=Date.parse('2026-11-17T09:00:00+09:00');
const APT='https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000497&pblancNo=2026000497';
const item=(over:Record<string,unknown>={})=>({id:'2026000497',name:'중화역 라온프라이빗 센트로',area:'서울',district:'중랑구',kind:'apt',units:113,
 area_min:45.02,area_max:126.81,price_min:65800,price_max:202100,move_in:'2029-02',regulation:['투기과열지구'],
 steps:[{label:'특별공급',start:'2026-11-16',end:'2026-11-16'},{label:'1순위',start:'2026-11-17',end:'2026-11-18'},{label:'2순위',start:'2026-11-19',end:'2026-11-19'}],
 announce:'2026-11-25',contract_start:'2026-12-07',contract_end:'2026-12-09',url:APT,detail:'checked',checked_at:'2026-11-17T00:12:00+09:00',...over});
const raw=(items:unknown[],over:Record<string,unknown>={})=>({subscriptions:{schema_version:1,source:'subscriptions',fetched_at:'2026-11-17T00:12:00+09:00',window_days:14,notice:'청약홈',items,...over}});
const step=(label:string,start:string,end=start)=>({label,start,end});

test('valid bundle parses; stale, foreign link or bad shape is rejected',()=>{
 const r=parseSubscriptions(raw([item()]),NOW)!;
 assert.equal(r.items[0].priceMax,202100);
 assert.equal(r.items[0].url,APT);
 assert.equal(parseSubscriptions(raw([item()],{fetched_at:'2026-11-15T00:00:00+09:00'}),NOW),null);
 assert.equal(parseSubscriptions(raw([item({url:'https://evil.example/x'})]),NOW),null);
 assert.equal(parseSubscriptions(raw([item({url:'javascript:alert(1)'})]),NOW),null);
 assert.equal(parseSubscriptions(raw([item({kind:'land'})]),NOW),null);
 assert.equal(parseSubscriptions(raw([item({extra:1})]),NOW),null);
 assert.equal(parseSubscriptions(raw([item({steps:[]})]),NOW),null);
 assert.equal(parseSubscriptions({},NOW),null);
});

test('complexes whose receipts all passed are hidden',()=>{
 const past=item({id:'2026000001',steps:[step('무순위 접수','2026-11-10')]});
 assert.deepEqual(parseSubscriptions(raw([item(),past]),NOW)!.items.map(i=>i.id),['2026000497']);
});

test('timeline marks done, today and upcoming, then announcement and contract',()=>{
 const r=parseSubscriptions(raw([item()]),NOW)!;
 assert.deepEqual(timeline(r.items[0],'2026-11-17').map(s=>[s.label,s.state,s.text]),[
  ['특별공급','done','11/16'],['1순위','now','11/17~18'],['2순위','next','11/19'],['당첨 발표','next','11/25'],['계약','next','12/7~9']]);
});

test('badge says what happens next in plain words',()=>{
 const r=(steps:unknown[])=>parseSubscriptions(raw([item({steps})]),NOW)!.items[0];
 assert.deepEqual(badge(r([step('1순위','2026-11-17','2026-11-18')]),'2026-11-17'),{text:'1순위 접수 중 · 11/18까지',tone:'urgent'});
 assert.deepEqual(badge(r([step('2순위','2026-11-17')]),'2026-11-17'),{text:'2순위 오늘 접수',tone:'urgent'});
 assert.deepEqual(badge(r([step('1순위','2026-11-16','2026-11-17')]),'2026-11-17'),{text:'1순위 오늘 마감',tone:'urgent'});
 assert.deepEqual(badge(r([step('특별공급','2026-11-18')]),'2026-11-17'),{text:'특별공급 내일 접수',tone:'soon'});
 assert.deepEqual(badge(r([step('무순위 접수','2026-11-20')]),'2026-11-17'),{text:'무순위 접수 D-3',tone:'plain'});
});

test('groups by the day of the next receipt: today, tomorrow, this week, next week, later',()=>{
 const make=(id:string,start:string)=>item({id,name:'단지'+id,steps:[step('1순위',start)]});
 const r=parseSubscriptions(raw([make('2026000005','2026-11-30'),make('2026000004','2026-11-24'),make('2026000003','2026-11-20'),
  make('2026000002','2026-11-18'),make('2026000001','2026-11-17')]),NOW)!;
 // 2026-11-17은 화요일: 이번 주는 11/23(일)까지.
 assert.deepEqual(groupByDay(r.items,'2026-11-17','').map(g=>[g.label,g.items.map(i=>i.id)]),[
  ['오늘 · 11/17(화)',['2026000001']],['내일 · 11/18(수)',['2026000002']],['이번 주',['2026000003']],['다음 주',['2026000004']],['그 후',['2026000005']]]);
});

test('my district goes first within a group and is flagged',()=>{
 const r=parseSubscriptions(raw([item({id:'2026000002',name:'가',district:'관악구'}),item({id:'2026000001',name:'나'})]),NOW)!;
 const [today]=groupByDay(r.items,'2026-11-17','중랑구');
 assert.deepEqual(today.items.map(i=>i.name),['나','가']);
 assert.equal(isMine(today.items[0],'중랑구'),true);
 assert.equal(isMine(r.items[0],''),false);
 // 경기도 '광주시'는 서울 구 이름과 겹치지 않는다. 서울 단지만 내 지역으로 본다.
 assert.equal(isMine({...today.items[0],area:'경기'},'중랑구'),false);
});

test('price, area and filters',()=>{
 assert.equal(formatPrice(65800,202100),'6.6억~20.2억');
 assert.equal(formatPrice(9500,100000),'9,500만~10억');
 assert.equal(formatPrice(54800,54800),'5.5억');
 assert.equal(formatPrice(null,null),null);
 assert.equal(formatArea(45.02,126.81),'전용 45~127㎡');
 assert.equal(formatArea(84.9,84.9),'전용 85㎡');
 const r=parseSubscriptions(raw([item(),item({id:'2026000002',name:'분당 무순위',area:'경기',district:'성남시 분당구',kind:'remain'}),
  item({id:'2026000003',name:'오피스텔',kind:'officetel'})]),NOW)!;
 assert.deepEqual(filterSubs(r.items,{area:'경기',kind:'',q:''}).map(i=>i.id),['2026000002']);
 assert.deepEqual(filterSubs(r.items,{area:'',kind:'etc',q:''}).map(i=>i.id),['2026000003']);
 assert.deepEqual(filterSubs(r.items,{area:'',kind:'',q:'분당'}).map(i=>i.id),['2026000002']);
});
