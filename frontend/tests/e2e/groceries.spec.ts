import {test,expect} from '@playwright/test';
import {snapshot,NOW} from '../fixtures';

const day=new Date(NOW+9*3600000);
const kst=(back:number)=>new Date(day.getTime()-back*86400000).toISOString().slice(0,10);
function produce(item:string,kind:string,unit:string,today:number,normal:number){
 return {id:[item,kind,unit,'상품'].join('|'),item,kind,unit,grade:'상품',today,day_ago:today,week_ago:today,two_weeks_ago:today,year_ago:normal,normal};
}
const groceries={schema_version:1,source:'groceries',fetched_at:new Date(NOW-3600000).toISOString(),notice:'[테스트] 전국 평균',
 produce:{survey_date:kst(1),items:[produce('양파','양파','1kg',1893,2088),produce('파','대파','1kg',2597,3164),produce('레몬','레몬','10개',9000,9000)]},
 meat:{survey_date:kst(1),missing:['한우 갈비'],items:[
  {id:'4304-27-삼겹살',cut:'돼지 삼겹살',label:'삼겹살',unit:'원/100g',national:2768,seoul:2866,min:2598,min_region:'경남',max:2979,max_region:'전북'},
  {id:'4301-22-등심 1++등급',cut:'한우 등심',label:'등심 1++등급',unit:'원/100g',national:15645,seoul:16000,min:14000,min_region:'경북',max:17000,max_region:'서울'},
  {id:'4301-22-등심 1+등급',cut:'한우 등심',label:'등심 1+등급',unit:'원/100g',national:13676,seoul:14000,min:12500,min_region:'경북',max:15000,max_region:'서울'},
  {id:'4301-22-등심 1등급',cut:'한우 등심',label:'등심 1등급',unit:'원/100g',national:12140,seoul:12500,min:11000,min_region:'경북',max:13500,max_region:'서울'}]}};

const weekly={schema_version:1,generated_at:new Date(NOW-1800000).toISOString(),survey_date:kst(1),source:'ai',
 summary:'[테스트] 이번 주는 파(2,597원)가 싸요. 파전으로 주말 반찬을 준비해 보세요.',
 picks:[{id:'파|대파|1kg|상품',menu:'파전'},{id:'양파|양파|1kg|상품',menu:'양파볶음'},{id:'4304-27-삼겹살',menu:'수육'}]};

test('weekly pick card shows the AI summary, linked prices and the rule fallback',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 let pick:Record<string,unknown>=weekly;
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries,grocery_pick:pick})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 const card=page.locator('.grocery-pick');
 await expect(card.locator('.grocery-badge').first()).toHaveText('AI 작성');
 await expect(card).toContainText('[테스트] 이번 주는 파(2,597원)가 싸요.');
 await expect(card.locator('li')).toHaveText([/파 2,597원.*파전/,/양파 1,893원.*양파볶음/,/돼지 삼겹살 2,768원.*수육/]);
 pick={...weekly,source:'rule',summary:null,picks:weekly.picks.map(p=>({...p,menu:null}))};
 await page.reload();
 await expect(card.locator('.grocery-badge').first()).toHaveText('자동 선정');
 await expect(card.locator('.grocery-pick-summary')).toHaveCount(0);
 await expect(card.locator('.grocery-pick-menu')).toHaveCount(0);
});

// 2026-11-14: the weekly pick is no longer pinned above the tabs; it shows inside the grocery tab only.
for(const width of [390,1440])test(`weekly pick shows only inside the grocery tab ${width}`,async({page})=>{
 await page.setViewportSize({width,height:844});
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries,grocery_pick:weekly})}));
 await page.goto('./');
 await expect(page.locator('#results')).toBeVisible();
 await expect(page.locator('.pick-teaser')).toHaveCount(0);
 await expect(page.getByText('이번 주 장보기 추천')).toBeHidden();
 await expect(page.locator('#groceries')).toBeHidden();
 // Nothing sits between the page heading and the tabs.
 const [hero,tabs]=await Promise.all([page.locator('.hero').boundingBox(),page.locator('#site-tabs').boundingBox()]);
 expect(tabs!.y-(hero!.y+hero!.height)).toBeLessThan(40);
 await page.getByRole('tab',{name:'장보기'}).click();
 await expect(page.locator('#results')).toBeHidden();
 expect(new URL(page.url()).hash).toBe('#groceries');
 const card=page.locator('.grocery-pick');
 await expect(card).toBeVisible();
 await expect(page.getByText('이번 주 장보기 추천')).toHaveCount(1);
 await expect(card.locator('li')).toHaveText([/파 2,597원.*파전/,/양파 1,893원/,/돼지 삼겹살 2,768원/]);
 // The card is in the top part of the tab: above the category buttons and the price list.
 const [pick,list]=await Promise.all([card.boundingBox(),page.locator('.grocery-tabs').boundingBox()]);
 expect(pick!.y).toBeLessThan(list!.y);
 await page.getByRole('tab',{name:/혜택/}).click();
 await expect(page.locator('#results')).toBeVisible();
 expect(new URL(page.url()).hash).toBe('');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

for(const width of [390,1440])test(`grocery section: featured rows, calculator and guide ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.clock.install({time:new Date(NOW)});
 const raw=snapshot(undefined,{groceries});
 const origin=new URL(String(test.info().project.use.baseURL)).origin,requests:string[]=[];
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());requests.push(u.origin);
  if(u.origin!==origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 await page.goto('./');
 const section=page.locator('#groceries');
 await page.getByRole('tab',{name:'장보기'}).click();
 await expect(section).toBeVisible();
 // 자주 사는 품목: listed produce and one card per meat cut (pork before 한우), without paging; 레몬 waits in the 과일 tab.
 await expect(section.locator('article h3')).toHaveText([/양파/,/파/,/돼지 삼겹살/,/한우 등심\s*1\+등급/]);
 const beef=section.locator('article',{hasText:'한우 등심'});
 await expect(beef.locator('.grocery-price strong')).toHaveText('13,676원');
 await expect(beef.locator('.grocery-others')).toHaveText('다른 등급: 1++등급 15,645원 · 1등급 12,140원');
 await expect(section.locator('article',{hasText:'돼지 삼겹살'}).locator('.grocery-others')).toHaveCount(0);
 // The 육류·계란 tab still lists every grade on its own card.
 await section.getByRole('button',{name:'육류·계란'}).click();
 await expect(section.locator('article h3')).toHaveText([/돼지 삼겹살/,/한우 등심\s*1\+\+등급/,/한우 등심\s*1\+등급/,/한우 등심\s*1등급/]);
 await expect(section.locator('.grocery-others')).toHaveCount(0);
 await section.getByRole('button',{name:'자주 사는 품목'}).click();
 await expect(section).toContainText('일부 품목 미수집: 한우 갈비');
 const onion=section.locator('article',{hasText:'양파'});
 await expect(onion.locator('.grocery-badge')).toHaveText('평년 수준 (9% 쌈)');
 await onion.getByText('이 가격 싼가요?').click();
 await onion.getByLabel('가격(원)').fill('3500');
 await onion.getByLabel('양').fill('1.5');
 await expect(onion.locator('.grocery-calc-result')).toContainText('1kg당 2,333원');
 await expect(onion.locator('.grocery-calc-result')).toContainText('평년보다 12% 비쌈');
 await onion.getByText('좋은 품질 · 고르는 법').click();
 await expect(onion.locator('.grocery-guide')).toContainText('단단');
 await expect(onion.locator('.grocery-guide a')).toHaveAttribute('href',/itemSn=24$/);
 await section.getByRole('button',{name:'과일'}).click();
 await expect(section.locator('article h3')).toHaveText([/레몬/]);
 await section.getByLabel('품목 찾기').fill('삼겹');
 await expect(section.locator('article h3')).toHaveText([/돼지 삼겹살/]);
 expect(new Set(requests)).toEqual(new Set([origin]));
});

test('a bundle collected minutes ago shows right away (not hidden as future data)',async({page})=>{
 // Clock 20 minutes past the hour, data collected 10 minutes past: an hour-rounded "now" would hide it.
 await page.clock.install({time:new Date(NOW+20*60000)});
 const fresh={...groceries,fetched_at:new Date(NOW+10*60000).toISOString()};
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:fresh})}));
 await page.goto('./#groceries');
 await expect(page.getByRole('tab',{name:'장보기'})).toHaveAttribute('aria-selected','true');
 await expect(page.locator('#groceries h2')).toContainText('장보기 시세');
});

test('missing grocery bundle hides the section and the shortcut',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot()}));
 await page.goto('./');
 await expect(page.locator('#results')).toBeVisible();
 await expect(page.locator('#groceries')).toHaveCount(0);
 await expect(page.getByText('이번 주 장보기 추천')).toHaveCount(0);
});

const quickGroceries={...groceries,meat:{...groceries.meat,items:[...groceries.meat.items,
 {id:'4304-28-목살',cut:'돼지 목살',label:'목살',unit:'원/100g',national:2500,seoul:2600,min:2300,min_region:'경남',max:2700,max_region:'전북'}]}};
const baseUnit='원/100g',checked=kst(1);
const bl=(avg:number)=>({avg,months:14,from:'2025-09',to:'2026-10',unit:baseUnit,checked_at:checked});
const grocery_baselines={schema_version:1,source:'grocery_baselines',items:[
 {id:'samgyeop',name:'돼지 삼겹살',aliases:['삼겹살','삼겹'],group:'고기·알',row:{kind:'meat',id:'4304-27-삼겹살'},baseline:{...bl(3000),months:4}},
 {id:'daepae',name:'대패삼겹',aliases:['대패'],group:'고기·알',row:{kind:'meat',id:'9999-0-대패삼겹'},baseline:null},
 {id:'moksal',name:'목살',aliases:['돼지 목살'],group:'고기·알',row:{kind:'meat',id:'4304-28-목살'},baseline:null},
 {id:'apdari',name:'앞다리',aliases:['돼지 앞다리'],group:'고기·알',row:{kind:'meat',id:'9999-1-앞다리'},baseline:null}]};

for(const [width,height] of [[360,800],[390,844]])test(`quick check card answers a basket search above the weekly pick ${width}`,async({page})=>{
 await page.setViewportSize({width,height});
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:quickGroceries,grocery_pick:weekly,grocery_baselines})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 await page.locator('#grocery-q').fill('삼겹');
 const card=page.locator('.grocery-quick');
 await expect(card).toBeInViewport();
 // The answer itself (price and badge) must be fully on the first screen.
 await expect(card.locator('.grocery-quick-price')).toBeInViewport({ratio:1});
 await expect(card.locator('.grocery-badge')).toBeInViewport({ratio:1});
 await expect(card.locator('.grocery-quick-note')).toBeInViewport({ratio:1});
 await expect(page.locator('#groceries [role=status]')).toContainText('돼지 삼겹살 전국 평균 소매가 2,768원 /100g');
 const [c,p]=await Promise.all([card.boundingBox(),page.locator('.grocery-pick').boundingBox()]);
 expect(c!.y).toBeLessThan(p!.y);
 const [m,d]=kst(1).slice(5).split('-').map(Number);
 await expect(card.locator('h3')).toHaveText('돼지 삼겹살 · 전국 평균 소매가');
 await expect(card.locator('.grocery-quick-price')).toHaveText(/2,768원\s*\/100g/);
 await expect(card.locator('.grocery-badge')).toContainText('개월 평균보다');
 await expect(card.locator('.grocery-quick-note')).toHaveText(`조사 방식 변경(7월) 후 4개월 평균 3,000원 · ${m}/${d} 조사`);
 // Items without a row today (대패삼겹, 앞다리) are not offered as links.
 await expect(card.locator('.grocery-quick-links')).toHaveText('목살 ›');
 await expect(card.getByRole('button',{name:'대패삼겹'})).toHaveCount(0);
 await expect(card.getByRole('button',{name:'앞다리'})).toHaveCount(0);
 await page.screenshot({path:`../docs/qa/screenshots/grocery-quick-check-${width}.png`});
 await card.getByRole('button',{name:'목살'}).click();
 await expect(page.locator('#grocery-q')).toHaveValue('목살');
 await expect(page.locator('#grocery-q')).toBeFocused();
 await expect(card.locator('h3')).toHaveText('목살 · 전국 평균 소매가');
 await expect(card.locator('.grocery-badge')).toHaveCount(0);
 await expect(card.locator('.grocery-quick-note')).toHaveText(`${m}/${d} 조사`);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('an alias-only search shows the card without the empty-state block and scrolls once',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:quickGroceries,grocery_pick:weekly,grocery_baselines})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 await page.evaluate(()=>{(window as any).__sc=0;const o=Element.prototype.scrollIntoView;Element.prototype.scrollIntoView=function(...a){if((this as Element).classList.contains('grocery-filters'))(window as any).__sc++;return o.apply(this,a as any);};});
 const input=page.locator('#grocery-q');
 await input.fill('삼겹');
 await expect(page.locator('.grocery-quick h3')).toHaveText('돼지 삼겹살 · 전국 평균 소매가');
 await input.pressSequentially('살');
 await expect(page.locator('.grocery-quick h3')).toHaveText('돼지 삼겹살 · 전국 평균 소매가');
 expect(await page.evaluate(()=>(window as any).__sc)).toBe(1);
 await input.fill('돼지 목살');
 await expect(page.locator('.grocery-quick h3')).toHaveText('목살 · 전국 평균 소매가');
 await expect(page.locator('#groceries .empty-state')).toHaveCount(0);
 expect(await page.evaluate(()=>(window as any).__sc)).toBe(2);
});

test('a search outside the basket explains it and shows no card',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:quickGroceries,grocery_baselines})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 await page.locator('#grocery-q').fill('없는품목');
 await expect(page.locator('.grocery-quick')).toHaveCount(0);
 await expect(page.locator('#groceries .empty-state')).toContainText('아직 자주 사는 품목에 없어요');
});

test('an empty basket never claims the item is missing from it',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:quickGroceries})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 await page.locator('#grocery-q').fill('없는품목');
 await expect(page.locator('#groceries .empty-state')).toBeVisible();
 await expect(page.locator('#groceries .empty-state')).not.toContainText('아직 자주 사는 품목에 없어요');
});

// 할인 줄: 고등어는 오늘 진행 중 2건 + 어제 끝난 1건, 삼겹살은 0건.
const fishGroceries={...quickGroceries,produce:{...quickGroceries.produce,items:[...quickGroceries.produce.items,produce('고등어','고등어','1마리',3000,3000)]}};
const fishBaselines={...grocery_baselines,items:[...grocery_baselines.items,
 {id:'godeungeo',name:'고등어',aliases:[],group:'기타',row:{kind:'produce',id:'고등어|고등어|1마리|상품'},baseline:{...bl(3000),unit:'1마리',months:6}}]};
const deal=(over:Record<string,unknown>)=>({basket_id:'godeungeo',title:'[테스트] 수산 할인',discount:'최대 50%',stores:'대형마트·온라인몰',start:kst(3),end:kst(-10),url:'https://www.mof.go.kr/deal-a',...over});
const grocery_discounts={schema_version:1,source:'grocery_discounts',generated_at:new Date(NOW-1800000).toISOString(),links:[
 deal({title:'[테스트] 어제 끝난 행사',end:kst(1),url:'https://www.mof.go.kr/ended'}),
 deal({title:'[테스트] 진행 행사 A',end:kst(-5),url:'https://www.mof.go.kr/deal-a'}),
 deal({title:'[테스트] 진행 행사 B',discount:null,stores:null,end:kst(-9),url:'https://www.mof.go.kr/deal-b'})]};

for(const [width,height] of [[360,800],[390,844]])test(`discount line sits under the badge and stays on the first screen ${width}`,async({page})=>{
 await page.setViewportSize({width,height});
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:fishGroceries,grocery_pick:weekly,grocery_baselines:fishBaselines,grocery_discounts})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 await page.locator('#grocery-q').fill('고등어');
 const card=page.locator('.grocery-quick');
 const lines=card.locator('.grocery-quick-deals li');
 await expect(lines).toHaveCount(2);
 await expect(card).not.toContainText('어제 끝난 행사');
 await expect(card.locator('.grocery-quick-price')).toBeInViewport({ratio:1});
 await expect(card.locator('.grocery-badge')).toBeInViewport({ratio:1});
 await expect(lines.first()).toBeInViewport({ratio:1});
 const [e1,e2]=kst(-5).slice(5).split('-').map(Number),[f1,f2]=kst(-9).slice(5).split('-').map(Number);
 await expect(lines.nth(0)).toHaveText(`[테스트] 진행 행사 A 최대 50% · 대형마트·온라인몰 · ${e1}/${e2}까지 원문`);
 await expect(lines.nth(1)).toHaveText(`[테스트] 진행 행사 B · ${f1}/${f2}까지 원문`);
 const link=lines.first().getByRole('link',{name:'원문'});
 await expect(link).toHaveAttribute('href','https://www.mof.go.kr/deal-a');
 await expect(link).toHaveAttribute('target','_blank');
 await expect(link).toHaveAttribute('rel','noopener noreferrer');
 // The date piece never splits across lines, and the tap targets are 44px tall.
 for(const nb of await lines.locator('.nb').all())expect(await nb.evaluate(e=>e.getClientRects().length)).toBe(1);
 expect((await link.boundingBox())!.height).toBeGreaterThanOrEqual(44);
 await expect(page.locator('#groceries [role=status]')).toContainText('진행 중인 공식 할인행사 [테스트] 진행 행사 A');
 await page.screenshot({path:`../docs/qa/screenshots/grocery-discount-${width}.png`});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 // No discounts for 삼겹살: no line, and a missing key behaves the same.
 await page.locator('#grocery-q').fill('삼겹');
 await expect(card.locator('h3')).toHaveText('돼지 삼겹살 · 전국 평균 소매가');
 await expect(card.locator('.grocery-quick-deals')).toHaveCount(0);
});

test('외 N건 appears for a third link and opens the benefits tab',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.clock.install({time:new Date(NOW)});
 const more={...grocery_discounts,links:[...grocery_discounts.links,deal({title:'[테스트] 진행 행사 C',end:kst(-12),url:'https://www.mof.go.kr/deal-c'})]};
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:fishGroceries,grocery_baselines:fishBaselines,grocery_discounts:more})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 await page.locator('#grocery-q').fill('고등어');
 await expect(page.locator('.grocery-quick-deals li')).toHaveCount(3);
 expect((await page.getByRole('button',{name:'외 1건'}).boundingBox())!.height).toBeGreaterThanOrEqual(44);
 await page.getByRole('button',{name:'외 1건'}).click();
 await expect(page.getByRole('tab',{name:'혜택'})).toHaveAttribute('aria-selected','true');
 await expect(page.locator('#results')).toBeVisible();
});

test('without a grocery_discounts key the card has no discount line',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(undefined,{groceries:fishGroceries,grocery_baselines:fishBaselines})}));
 await page.goto('./');
 await page.getByRole('tab',{name:'장보기'}).click();
 await page.locator('#grocery-q').fill('고등어');
 await expect(page.locator('.grocery-quick h3')).toContainText('고등어');
 await expect(page.locator('.grocery-quick-deals')).toHaveCount(0);
});
