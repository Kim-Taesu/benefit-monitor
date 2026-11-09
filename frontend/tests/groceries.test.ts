import test from 'node:test';
import assert from 'node:assert/strict';
import {parseGroceries,verdict,parseUnit,compareShelf,guideFor,wikiLink,featuredRows,parsePick} from '../src/groceries.ts';

const NOW=Date.parse('2026-11-09T09:00:00+09:00');
function produce(over:Record<string,unknown>={}){
 const row={item:'양파',kind:'양파',unit:'1kg',grade:'상품',today:1893,day_ago:2050,week_ago:1890,two_weeks_ago:2165,year_ago:2008,normal:2088,...over};
 return {id:[row.item,row.kind,row.unit,row.grade].join('|'),...row};
}
function meat(over:Record<string,unknown>={}){
 return {id:'4304-27-삼겹살',cut:'돼지 삼겹살',label:'삼겹살',unit:'원/100g',national:2768,seoul:2866,min:2598,min_region:'경남',max:2979,max_region:'전북',...over};
}
function raw(over:Record<string,unknown>={}){
 return {groceries:{schema_version:1,source:'groceries',fetched_at:'2026-11-09T00:40:00+09:00',notice:'전국 평균',
  produce:{survey_date:'2026-11-06',items:[produce()]},meat:{survey_date:'2026-11-08',items:[meat()],missing:['한우 등심']},...over}};
}

test('parses produce and meat with categories and current price',()=>{
 const g=parseGroceries(raw(),NOW)!;
 assert.equal(g.produceDate,'2026-11-06');
 assert.deepEqual(g.missing,['한우 등심']);
 const onion=g.rows.find(r=>r.name==='양파')!;
 assert.equal(onion.category,'채소');
 assert.equal(onion.current,1893);
 const pork=g.rows.find(r=>r.kind==='meat')!;
 assert.equal(pork.category,'육류·계란');
 assert.equal(pork.current,2768);
 assert.equal(pork.name,'돼지 삼겹살');
 assert.equal(pork.detail,'');
 const beef=parseGroceries(raw({meat:{survey_date:'2026-11-08',items:[meat({id:'4301-22-등심 1++등급',cut:'한우 등심',label:'등심 1++등급'}),meat({id:'9903-23-XL30구 일반란',cut:'계란 특란 30구',label:'XL30구 일반란',unit:'원/30구'})],missing:[]}}),NOW)!;
 assert.deepEqual(beef.rows.filter(r=>r.kind==='meat').map(r=>r.detail),['1++등급','XL30구 일반란']);
});

test('falls back to the previous day when today is missing',()=>{
 const g=parseGroceries(raw({produce:{survey_date:'2026-11-06',items:[produce({today:null})]}}),NOW)!;
 const onion=g.rows[0];
 assert.equal(onion.current,2050);
 assert.equal(onion.currentLabel,'1일전');
});

test('rejects stale, tampered or unsafe bundles',()=>{
 assert.equal(parseGroceries({},NOW),null);
 assert.equal(parseGroceries(raw({fetched_at:'2026-11-07T00:00:00+09:00'}),NOW),null);
 assert.equal(parseGroceries(raw({source:'x'}),NOW),null);
 const bad=parseGroceries(raw({produce:{survey_date:'2026-11-06',items:[produce({today:'1893'}),produce({item:'파',kind:'대파'})]}}),NOW)!;
 assert.deepEqual(bad.rows.filter(r=>r.kind==='produce').map(r=>r.name),['파']);
 const badMeat=parseGroceries(raw({meat:{survey_date:'2026-11-08',items:[meat({min_region:'<script>'})],missing:[]}}),NOW)!;
 assert.equal(badMeat.rows.filter(r=>r.kind==='meat').length,0);
 const old=parseGroceries(raw({produce:{survey_date:'2026-10-20',items:[produce()]}}),NOW)!;
 assert.equal(old.rows.filter(r=>r.kind==='produce').length,0);
});

test('verdict compares with 평년 first, then 1년전, at ±10%',()=>{
 assert.deepEqual(verdict(1893,2088,2008),{level:'normal',base:'평년',pct:-9,label:'평년 수준 (9% 쌈)'});
 assert.deepEqual(verdict(1500,2000,null),{level:'cheap',base:'평년',pct:-25,label:'평년보다 25% 쌈'});
 assert.deepEqual(verdict(2400,null,2000),{level:'pricey',base:'1년전',pct:20,label:'1년전보다 20% 비쌈'});
 assert.deepEqual(verdict(2000,2000,null),{level:'normal',base:'평년',pct:0,label:'평년과 같음'});
 assert.equal(verdict(2000,null,null),null);
});

test('parses units for the shelf calculator',()=>{
 assert.deepEqual(parseUnit('1kg'),{amount:1000,base:'g',label:'1kg'});
 assert.deepEqual(parseUnit('100g'),{amount:100,base:'g',label:'100g'});
 assert.deepEqual(parseUnit('원/100g'),{amount:100,base:'g',label:'100g'});
 assert.deepEqual(parseUnit('원/kg'),{amount:1000,base:'g',label:'1kg'});
 assert.deepEqual(parseUnit('10개'),{amount:10,base:'개',label:'10개'});
 assert.deepEqual(parseUnit('원/30구'),{amount:30,base:'구',label:'30구'});
 assert.deepEqual(parseUnit('1포기'),{amount:1,base:'포기',label:'1포기'});
 assert.equal(parseUnit('1.8L'),null);
});

test('compares a shelf price against the reference unit',()=>{
 // 양파 1.5kg 3,500원 -> 1kg당 2,333원, 평년 2,088원보다 12% 비쌈
 const r=compareShelf({unit:'1kg',current:1893,normal:2088,yearAgo:2008},3500,1.5,'kg')!;
 assert.equal(r.perUnit,2333);
 assert.equal(r.vsCurrent,23);
 assert.deepEqual(r.verdict,{level:'pricey',base:'평년',pct:12,label:'평년보다 12% 비쌈'});
 // 삼겹살 600g 15,000원 -> 100g당 2,500원, 전국 평균 2,768원보다 10% 쌈
 const m=compareShelf({unit:'원/100g',current:2768,normal:null,yearAgo:null},15000,600,'g')!;
 assert.equal(m.perUnit,2500);
 assert.equal(m.vsCurrent,-10);
 assert.equal(m.verdict,null);
 // count units must use the same unit
 assert.equal(compareShelf({unit:'10개',current:10000,normal:null,yearAgo:null},5000,500,'g'),null);
 assert.equal(compareShelf({unit:'10개',current:10000,normal:null,yearAgo:null},6000,5,'개')!.perUnit,12000);
 assert.equal(compareShelf({unit:'1kg',current:1893,normal:null,yearAgo:null},0,1,'kg'),null);
});

test('guide lookup: produce by item name, meat by cut prefix',()=>{
 const g=parseGroceries(raw(),NOW)!;
 const onion=guideFor(g.rows.find(r=>r.name==='양파')!)!;
 assert.equal(onion.basis,'kamis_wiki');
 assert.match(onion.good[0],/단단/);
 assert.equal(wikiLink(onion),'https://www.kamis.or.kr/customer/wiki/wiki.do?action=detail&itemSn=24');
 const pork=guideFor(g.rows.find(r=>r.kind==='meat')!)!;
 assert.match(pork.grade!,/1\+/);
 assert.equal(wikiLink(pork),null);
});

test('featured view: one 상품 row per listed produce item and every meat grade, in guide order',()=>{
 const g=parseGroceries(raw({produce:{survey_date:'2026-11-06',items:[
  produce({item:'배추',kind:'가을',unit:'1포기',grade:'중품',today:2500}),produce({item:'배추',kind:'가을',unit:'1포기',grade:'상품',today:2823}),
  produce(),produce({item:'브로콜리',kind:'브로콜리',unit:'1개',grade:'상품'}),produce({item:'레몬',kind:'레몬',unit:'10개',grade:'상품'})]},
  // 레몬 is not a listed item, so it is left to the 과일 tab
  meat:{survey_date:'2026-11-08',items:[meat(),meat({id:'4301-22-등심 1++등급',cut:'한우 등심',label:'등심 1++등급'}),meat({id:'4301-22-등심 1등급',cut:'한우 등심',label:'등심 1등급'})],missing:[]}}),NOW)!;
 const rows=featuredRows(g.rows);
 assert.deepEqual(rows.map(r=>r.name+(r.kind==='meat'?' '+r.detail:'')),['양파','배추','브로콜리','한우 등심 1++등급','한우 등심 1등급','돼지 삼겹살 ']);
 assert.equal(rows[1].current,2823);
});

test('weekly pick links picks to bundle rows and keeps the AI label',()=>{
 const g=parseGroceries(raw(),NOW)!;
 const pickRaw=(over:Record<string,unknown>={})=>({...raw(),grocery_pick:{schema_version:1,generated_at:'2026-11-09T01:30:00+09:00',survey_date:'2026-11-06',
  source:'ai',summary:'양파가 싸요. 양파볶음으로 주말 반찬을 준비해 보세요.',picks:[{id:'양파|양파|1kg|상품',menu:'양파볶음'},{id:'4304-27-삼겹살',menu:'수육'},{id:'없는|품목|1개|상품',menu:'x'}],...over}});
 const pick=parsePick(pickRaw(),g)!;
 assert.equal(pick.source,'ai');
 assert.deepEqual(pick.picks.map(p=>[p.row.name,p.menu]),[['양파','양파볶음'],['돼지 삼겹살','수육']]);
 assert.equal(parsePick(pickRaw({survey_date:'2026-11-05'}),g),null);
 assert.equal(parsePick(pickRaw({summary:'<b>x</b>'}),g),null);
 assert.equal(parsePick(pickRaw({source:'other'}),g),null);
 const rule=parsePick(pickRaw({source:'rule',summary:null,picks:[{id:'양파|양파|1kg|상품',menu:null}]}),g)!;
 assert.deepEqual([rule.source,rule.summary,rule.picks[0].menu],['rule',null,null]);
 assert.equal(parsePick(raw(),g),null);
});
