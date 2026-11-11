import test from 'node:test';
import assert from 'node:assert/strict';
import {parseGroceries,verdict,parseUnit,compareShelf,guideFor,wikiLink,featuredRows,parsePick,parseBaselines,quickMatch,baselineBadge,parseDiscounts,discountsFor,discountLine,type DiscountLink,type BasketItem,type PriceRow} from '../src/groceries.ts';

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

test('featured view: one 상품 row per listed produce item and one card per meat cut, pork before 한우',()=>{
 const g=parseGroceries(raw({produce:{survey_date:'2026-11-06',items:[
  produce({item:'배추',kind:'가을',unit:'1포기',grade:'중품',today:2500}),produce({item:'배추',kind:'가을',unit:'1포기',grade:'상품',today:2823}),
  produce(),produce({item:'브로콜리',kind:'브로콜리',unit:'1개',grade:'상품'}),produce({item:'레몬',kind:'레몬',unit:'10개',grade:'상품'})]},
  // 레몬 is not a listed item, so it is left to the 과일 tab
  meat:{survey_date:'2026-11-08',items:[
   meat({id:'4301-22-등심 1++등급',cut:'한우 등심',label:'등심 1++등급',national:15645}),
   meat({id:'4301-22-등심 1+등급',cut:'한우 등심',label:'등심 1+등급',national:13676}),
   meat({id:'4301-22-등심 1등급',cut:'한우 등심',label:'등심 1등급',national:12140}),
   meat(),
   meat({id:'9903-23-XL30구 일반란',cut:'계란 특란 30구',label:'XL30구 일반란',unit:'원/30구',national:7354}),
   meat({id:'9903-23-XL30구 동물복지',cut:'계란 특란 30구',label:'XL30구 동물복지',unit:'원/30구',national:10905})],missing:[]}}),NOW)!;
 const rows=featuredRows(g.rows);
 // Before: 한우 등심 1++ / 1+ / 1 as three cards with the same title, ahead of pork.
 assert.deepEqual(rows.map(r=>r.name+(r.kind==='meat'?' '+r.detail:'')),
  ['양파','배추','브로콜리','돼지 삼겹살 ','계란 특란 30구 XL30구 일반란','한우 등심 1+등급']);
 assert.equal(rows[1].current,2823);
 const beef=rows.find(r=>r.name==='한우 등심')!;
 assert.equal(beef.current,13676);
 assert.deepEqual(beef.others,[{detail:'1++등급',current:15645},{detail:'1등급',current:12140}]);
 assert.deepEqual(rows.find(r=>r.name==='계란 특란 30구')!.others,[{detail:'XL30구 동물복지',current:10905}]);
 assert.deepEqual(rows.find(r=>r.name==='돼지 삼겹살')!.others,[]);
 // Without a 1+ row the first official row represents the cut.
 const only=featuredRows(g.rows.filter(r=>r.detail!=='1+등급')).find(r=>r.name==='한우 등심')!;
 assert.equal(only.detail,'1++등급');
 // Other tabs still get every grade: featuredRows does not change the bundle rows.
 assert.equal(g.rows.filter(r=>r.name==='한우 등심').length,3);
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

function bItem(id:string,name:string,aliases:string[],group:BasketItem['group'],row:{kind:string;id:string},baseline:Record<string,unknown>|null){
 return {id,name,aliases,group,row,baseline};
}
const BASE={avg:2880,months:12,from:'2025-11',to:'2026-10',unit:'1kg',kind:null,grade:null,checked_at:'2026-11-09'};
function baselines(over:Record<string,unknown>={},items?:unknown[]){
 return {grocery_baselines:{schema_version:1,source:'grocery_baselines',fetched_at:'2026-11-09T00:40:00+09:00',items:items??[
  bItem('pork_belly','삼겹살',['삼겹살','삼겹','돼지고기'],'고기·알',{kind:'meat',id:'4304-27-삼겹살'},{...BASE,avg:2700,unit:'원/100g'}),
  bItem('pork_neck','목심',['목심','목살'],'고기·알',{kind:'meat',id:'4304-68-목심'},null),
  bItem('egg','계란',['계란','달걀'],'고기·알',{kind:'meat',id:'9903-23-XL30구 일반란'},null),
  bItem('chicken','닭(육계)',['닭','생닭'],'고기·알',{kind:'meat',id:'9901-99-육계(kg)'},null),
  bItem('onion','양파',['양파'],'채소',{kind:'produce',id:'양파|양파|1kg|상품'},BASE),
  bItem('green_onion','대파',['대파','파'],'채소',{kind:'produce',id:'파|대파|1kg|상품'},BASE),
  bItem('rice','쌀',['쌀','백미'],'기타',{kind:'produce',id:'쌀|20kg|20kg|상품'},{...BASE,avg:60000,unit:'20kg'}),
 ],...over}};
}
const basket=parseBaselines(baselines(),NOW);
const byName=(n:string)=>basket.find(i=>i.name===n)!;
function prow(over:Partial<PriceRow>={}):PriceRow{
 return {id:'양파|양파|1kg|상품',kind:'produce',name:'양파',detail:'',unit:'1kg',category:'채소',guideKey:'양파',current:2650,currentLabel:'당일',
  normal:null,yearAgo:null,weekAgo:null,range:null,seoul:null,featured:0,...over};
}

test('parseBaselines keeps basket order, rowKey and baseline freshness',()=>{
 assert.equal(basket.length,7);
 assert.equal(basket[0].rowKey,'meat4304-27-삼겹살');
 assert.equal(byName('양파').baseline!.avg,2880);
 const stale=parseBaselines(baselines({},[bItem('onion','양파',['양파'],'채소',{kind:'produce',id:'양파|양파|1kg|상품'},{...BASE,checked_at:'2026-10-09'})]),NOW);
 assert.equal(stale[0].baseline,null);
 const edge=parseBaselines(baselines({},[bItem('onion','양파',['양파'],'채소',{kind:'produce',id:'양파|양파|1kg|상품'},{...BASE,checked_at:'2026-10-10'})]),NOW);
 assert.equal(edge[0].baseline!.avg,2880);
 const future=parseBaselines(baselines({},[bItem('onion','양파',['양파'],'채소',{kind:'produce',id:'양파|양파|1kg|상품'},{...BASE,checked_at:'2026-11-10'})]),NOW);
 assert.equal(future[0].baseline,null);
 assert.deepEqual(parseBaselines(baselines({schema_version:2}),NOW),[]);
 assert.deepEqual(parseBaselines({},NOW),[]);
 assert.deepEqual(parseBaselines(baselines({items:'x'}),NOW),[]);
});

test('quickMatch ranks exact > prefix > partial and fills others',()=>{
 assert.equal(quickMatch('삼겹',basket)!.best.name,'삼겹살');
 assert.equal(quickMatch(' 대 파 ',basket)!.best.name,'대파');
 assert.equal(quickMatch('달걀',basket)!.best.name,'계란');
 assert.equal(quickMatch('파',basket)!.best.name,'대파');
 assert.equal(quickMatch('QUICK',basket),null);
 assert.equal(quickMatch('없는품목',basket),null);
 assert.equal(quickMatch('',basket),null);
 assert.equal(quickMatch('   ',basket),null);
 const m=quickMatch('파',basket)!;
 assert.ok(m.others.length<=3&&!m.others.includes(m.best));
 assert.equal(m.others[0].name,'양파');
 const all=quickMatch('삼겹',basket)!;
 assert.deepEqual(all.others.map(i=>i.name),['목심','계란','닭(육계)']);
});

test('baselineBadge compares against the multi-month average',()=>{
 const onion=byName('양파');
 assert.deepEqual(baselineBadge(prow(),onion),{level:'normal',pct:-8,label:'▼ 12개월 평균보다 8% 쌈'});
 const cheap=baselineBadge(prow({current:2500}),onion)!;
 assert.equal(cheap.level,'cheap');assert.equal(cheap.pct,-13);
 const pricey=baselineBadge(prow({current:3300}),onion)!;
 assert.equal(pricey.level,'pricey');assert.equal(pricey.label,'▲ 12개월 평균보다 15% 비쌈');
 assert.ok(baselineBadge(prow(),{...onion,baseline:{...BASE,months:4}})!.label.includes('4개월 평균'));
 assert.equal(baselineBadge(prow({current:2880}),onion)!.label,'12개월 평균과 같음');
 assert.ok(baselineBadge(prow(),{...onion,baseline:{...BASE,months:13}})!.label.includes('12개월 평균'));
 assert.equal(baselineBadge(prow(),{...onion,baseline:{...BASE,months:0}}),null);
 // unparseable units need strict equality
 const odd={...onion,baseline:{...BASE,unit:'두부 300g×2'}};
 assert.ok(baselineBadge(prow({unit:'두부 300g×2'}),odd));
 assert.equal(baselineBadge(prow({unit:'두부 300g×2 묶음'}),odd),null);
 assert.equal(baselineBadge(prow(),{...onion,baseline:null}),null);
 assert.equal(baselineBadge(prow({unit:'10개'}),onion),null);
 assert.equal(baselineBadge(prow({id:'다른|행|1kg|상품'}),onion),null);
 assert.equal(baselineBadge(prow({kind:'meat'}),onion),null);
});

test('baselineBadge unit check passes for real produce and meat rows',()=>{
 const rice=baselineBadge(prow({id:'쌀|20kg|20kg|상품',name:'쌀',unit:'20kg',current:63289}),byName('쌀'))!;
 assert.equal(rice.pct,5);assert.equal(rice.level,'normal');
 assert.equal(baselineBadge(prow({id:'쌀|10kg|10kg|상품',unit:'10kg',current:34796}),byName('쌀')),null);
 const pork=baselineBadge(prow({id:'4304-27-삼겹살',kind:'meat',name:'돼지 삼겹살',unit:'원/100g',current:2768}),byName('삼겹살'))!;
 assert.equal(pork.pct,3);
 assert.equal(baselineBadge(prow({id:'4304-27-삼겹살',kind:'meat',unit:'원/kg',current:2768}),byName('삼겹살')),null);
});

// Task 4: official discount links on the quick-check card. NOW is 2026-11-09 09:00 KST.
function link(over:Record<string,unknown>={}){
 return {basket_id:'godeungeo',title:'한국 수산식품 홍보주간',discount:'최대 50%',stores:'대형마트·온라인몰',start:'2026-11-05',end:'2026-11-27',url:'https://www.mof.go.kr/a',...over};
}
function discounts(links:unknown[]){return {grocery_discounts:{schema_version:1,source:'grocery_discounts',generated_at:'2026-11-09T09:00:00+09:00',links}};}
test('discountLine joins title, discount, stores and end date, dropping null pieces',()=>{
 const l=parseDiscounts(discounts([link()]),NOW)[0];
 assert.equal(discountLine(l),'한국 수산식품 홍보주간 최대 50% · 대형마트·온라인몰 · 11/27까지');
 assert.equal(discountLine({...l,discount:null}),'한국 수산식품 홍보주간 · 대형마트·온라인몰 · 11/27까지');
 assert.equal(discountLine({...l,stores:null}),'한국 수산식품 홍보주간 최대 50% · 11/27까지');
 assert.equal(discountLine({...l,discount:null,stores:null}),'한국 수산식품 홍보주간 · 11/27까지');
});
test('parseDiscounts drops links outside today (KST) and non-https urls, and bad shapes give []',()=>{
 const last=parseDiscounts(discounts([link({end:'2026-11-09'})]),NOW);
 assert.equal(last.length,1,'ends today is still shown');
 assert.equal(parseDiscounts(discounts([link({end:'2026-11-08'})]),NOW).length,0,'ended yesterday');
 assert.equal(parseDiscounts(discounts([link({start:'2026-11-10'})]),NOW).length,0,'starts tomorrow');
 assert.equal(parseDiscounts(discounts([link({start:'2026-11-09'})]),NOW).length,1,'starts today');
 // 00:30 KST on 11/10 is still 11/09 in UTC: the KST day must decide.
 const early=Date.parse('2026-11-10T00:30:00+09:00');
 assert.equal(parseDiscounts(discounts([link({end:'2026-11-09'})]),early).length,0);
 assert.equal(parseDiscounts(discounts([link({start:'2026-11-10'})]),early).length,1);
 assert.equal(parseDiscounts(discounts([link({url:'http://www.mof.go.kr/a'})]),NOW).length,0);
 assert.equal(parseDiscounts(discounts([link({url:'javascript:alert(1)'})]),NOW).length,0);
 assert.deepEqual(parseDiscounts({},NOW),[]);
 assert.deepEqual(parseDiscounts({grocery_discounts:{schema_version:2,source:'grocery_discounts',links:[link()]}},NOW),[]);
 assert.deepEqual(parseDiscounts({grocery_discounts:{schema_version:1,source:'x',links:[link()]}},NOW),[]);
 assert.deepEqual(parseDiscounts({grocery_discounts:{schema_version:1,source:'grocery_discounts',links:'x'}},NOW),[]);
 assert.equal(parseDiscounts(discounts([link({title:'<b>x</b>'}),link({discount:5}),link({start:'11/05'}),'x']),NOW).length,0);
});
test('discountsFor shows at most 2 by end date and counts the rest',()=>{
 const links=parseDiscounts(discounts([link({title:'C',end:'2026-12-01'}),link({title:'A',end:'2026-11-20'}),link({title:'B',end:'2026-11-25'}),link({basket_id:'x',title:'Z'})]),NOW);
 const r=discountsFor(links,'godeungeo');
 assert.deepEqual(r.shown.map(l=>l.title),['A','B']);
 assert.equal(r.more,1);
 assert.deepEqual(discountsFor(links,'none'),{shown:[],more:0});
});
test('parseDiscounts rejects impossible calendar dates and drops duplicates',()=>{
 assert.equal(parseDiscounts(discounts([link({start:'2026-02-30'})]),NOW).length,0);
 assert.equal(parseDiscounts(discounts([link({end:'2026-13-01'})]),NOW).length,0);
 assert.equal(parseDiscounts(discounts([link({end:'2026-11-31'})]),NOW).length,0);
 const dup=parseDiscounts(discounts([link(),link(),link({url:'https://www.mof.go.kr/b'}),link({basket_id:'other'})]),NOW);
 assert.equal(dup.length,3);
});
