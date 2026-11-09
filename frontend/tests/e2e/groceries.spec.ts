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
  {id:'4301-22-등심 1++등급',cut:'한우 등심',label:'등심 1++등급',unit:'원/100g',national:15645,seoul:16000,min:14000,min_region:'경북',max:17000,max_region:'서울'}]}};

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
 await expect(page.locator('.hero-jump')).toBeVisible();
 // 자주 사는 품목: listed produce and every meat row, without paging; 레몬 waits in the 과일 tab.
 await expect(section.locator('article h3')).toHaveText([/양파/,/파/,/한우 등심/,/돼지 삼겹살/]);
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

test('missing grocery bundle hides the section and the shortcut',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot()}));
 await page.goto('./');
 await expect(page.locator('#results')).toBeVisible();
 await expect(page.locator('#groceries')).toHaveCount(0);
 await expect(page.locator('.hero-jump')).toHaveCount(0);
});
