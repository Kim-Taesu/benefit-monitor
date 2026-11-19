import {test,expect} from '@playwright/test';
import {createRequire} from 'node:module';
import {mkdirSync} from 'node:fs';
import {item,snapshot,NOW} from '../fixtures';
const require=createRequire(import.meta.url);
const rows=()=>[
 item({summary:'[테스트] 은평 야간 전시',districts:['은평구'],labels:{category:'문화·체험',region:'은평구'}}),
 item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'[테스트] 야간 전시 둘',districts:[],labels:{category:'문화·체험',region:'서울'}}),
 item({url:'https://mediahub.seoul.go.kr/archives/3',summary:'[테스트] KT 할인',districts:[],labels:{category:'할인·적립',region:'전국'}}),
 item({url:'https://mediahub.seoul.go.kr/archives/4',summary:'[테스트] 성남 야경',districts:['성남시'],labels:{region:'성남시'}}),
];
async function setup(page){
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.origin!==new URL(String(test.info().project.use.baseURL)).origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:snapshot(rows())});return route.continue();
 });
 await page.goto('./');
}
test('topic chips carry an emoji, filter the single list, and one-item topics hide behind 주제 더보기',async({page})=>{
 await setup(page);
 await expect(page.locator('#results article')).toHaveCount(3);
 await expect(page.locator('#results')).not.toContainText('성남');
 const night=page.locator('[data-topic="night"]');
 await expect(night).toHaveText('🌙 저녁에 이용하기2');
 await expect(page.locator('[data-topic="shopping"]')).toHaveCount(0);
 await page.getByRole('button',{name:/주제 더보기/}).click();
 const shopping=page.locator('[data-topic="shopping"]');
 await expect(shopping).toContainText('🛍️ 장보기·멤버십');
 await shopping.click();await expect(page.locator('#results article')).toHaveCount(1);await expect(page.locator('#results')).toContainText('KT 할인');
 await page.getByRole('button',{name:'주제 접기',exact:true}).click();
 await expect(shopping).toHaveCount(0);await expect(page.locator('#results article')).toHaveCount(3);
 await night.click();await expect(page.locator('#results article')).toHaveCount(2);await expect(page.locator('#results-title')).toContainText('저녁에 이용하기');
 const positions=await page.evaluate(()=>({chips:(document.querySelector('.chips') as HTMLElement).offsetTop,results:document.getElementById('results')!.offsetTop,notice:document.getElementById('collection-notice')?.offsetTop??0}));
 expect(positions.chips).toBeLessThan(positions.results);expect(positions.notice).toBeGreaterThan(positions.results);
 await page.getByRole('button',{name:'필터 초기화',exact:true}).click();await expect(page.locator('#results article')).toHaveCount(3);
});
test('my district narrows topic counts together with the list',async({page})=>{
 await setup(page);
 await page.getByLabel('내 지역',{exact:true}).selectOption('강서구');
 await expect(page.locator('#results article')).toHaveCount(2);
 await expect(page.locator('[data-topic="night"]')).toHaveCount(0);
 await page.getByRole('button',{name:/주제 더보기/}).click();
 await expect(page.locator('[data-topic="night"]')).toHaveText('🌙 저녁에 이용하기1');
});
for(const width of [390,1440])test(`topic view accessibility and screenshot ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await setup(page);
 await page.locator('[data-topic="night"]').click();
 await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
 expect(await page.evaluate(async()=>(await (window as any).axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations)).toEqual([]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 for(const chip of await page.locator('.chips .chip').all())expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(44);
 const shots=process.env.BENEFIT_SCREENSHOT_DIR||'../docs/qa/screenshots';mkdirSync(shots,{recursive:true});await page.screenshot({path:`${shots}/topics-${width}.png`,fullPage:true});
});
test('removed personalization leaves no settings and deletes its old stored record',async({page})=>{
 await page.addInitScript(()=>{if(!sessionStorage.getItem('seeded')){sessionStorage.setItem('seeded','1');localStorage.setItem('benefit-monitor:beta:v1',JSON.stringify({version:2,profile:{residence:'은평구',areas:[],age:20,carrier:'KT',interests:['night'],excludedTopics:[]},consent:true,events:[],seen:[]}));}});
 await setup(page);
 await expect(page.locator('#results article')).toHaveCount(3);
 expect(await page.evaluate(()=>localStorage.getItem('benefit-monitor:beta:v1'))).toBeNull();
 for(const label of ['이용 통신사','현재 만 나이','이 기기의 행동 기록에 동의'])await expect(page.getByLabel(label)).toHaveCount(0);
 await expect(page.getByRole('button',{name:'관심 있어요'})).toHaveCount(0);
});
test('storage denial and expiry never remove basic discovery or fabricate topics',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new Error('blocked');}}));
 await setup(page);await expect(page.locator('#results article')).toHaveCount(3);
 // Past the file cutoff the previous list stays (2026-11-20); past every item's own cutoff nothing remains.
 await page.clock.fastForward(13*3600000);
 await expect(page.locator('#results article')).toHaveCount(3);await expect(page.locator('.refresh-line')).toContainText('기준 목록을 보여 드려요');
 await page.clock.fastForward(42*3600000);
 await expect(page.locator('#results article')).toHaveCount(0);
 await expect(page.locator('.topic-chip')).toHaveCount(0);await expect(page.getByRole('button',{name:/주제 더보기/})).toHaveCount(0);
});
for(const width of [390,1290])test(`topic survives every dialog dismissal at ${width}px`,async({page})=>{
 await page.setViewportSize({width,height:900});await setup(page);
 const topic=page.locator('[data-topic="night"]');await topic.click();
 for(const action of ['backdrop','close','escape','back']){
  await page.locator('.card-open').first().click();await expect(page.getByRole('dialog')).toBeVisible();
  if(action==='backdrop')await page.mouse.click(2,2);
  else if(action==='close')await page.getByRole('button',{name:'상세 조건 닫기'}).click();
  else if(action==='escape')await page.keyboard.press('Escape');
  else await page.goBack();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect.poll(()=>page.evaluate(()=>history.state?.benefitDialog)).toBeFalsy();
  await expect(topic).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('#results article')).toHaveCount(2);
  await expect(page.locator('#results-title')).toContainText('저녁에 이용하기');
 }
});
