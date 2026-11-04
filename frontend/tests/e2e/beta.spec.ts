import {test,expect} from '@playwright/test';
import {createRequire} from 'node:module';
import {mkdirSync} from 'node:fs';
import {item,snapshot,NOW} from '../fixtures';
const require=createRequire(import.meta.url);
async function setup(page){
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.origin!=='http://127.0.0.1:4173')return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:snapshot([
   item({summary:'[테스트] 은평 야간 전시',districts:['은평구']}),
   item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'[테스트] KT 할인',districts:[],labels:{category:'할인·적립',region:'전국'}}),
   item({url:'https://mediahub.seoul.go.kr/archives/3',summary:'[테스트] 성남 야경',districts:['성남시'],labels:{region:'성남시'}})
  ])});return route.continue();
 });
 await page.goto('./');await page.locator('#beta summary').first().click();
}
test('profile and topic navigation, optional local consent, feedback, revoke and reset',async({page})=>{
 await setup(page);
 await expect(page.getByLabel('거주 자치구').locator('option')).toHaveCount(26);
 await page.getByLabel('거주 자치구').selectOption('은평구');
 await page.locator('.beta-areas summary').click();
 await page.getByLabel('관심 자치구 마포구',{exact:true}).check();
 await page.getByLabel('현재 만 나이').fill('20');await page.getByLabel('이용 통신사').selectOption('KT');
 await page.getByLabel('관심사 저녁 산책·야간 문화',{exact:true}).check();
 await page.getByRole('button',{name:'개인화 설정 저장',exact:true}).click();
 await expect(page.locator('#beta')).toContainText('이 브라우저에 설정을 저장했습니다');
 expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('benefit-monitor:beta:v1')!).events)).toEqual([]);
 await page.getByRole('button',{name:/저녁 산책·야간 문화 ·/}).click();
 await expect(page.locator('#beta-related article')).toHaveCount(1);
 await expect(page.locator('#beta-related')).not.toContainText('성남');
 await page.getByLabel('이 기기의 행동 기록에 동의').check();
 await page.getByRole('button',{name:'관심 있어요',exact:true}).click();
 expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('benefit-monitor:beta:v1')!).events.some(e=>e.action==='like'))).toBe(true);
 await page.getByLabel('이 기기의 행동 기록에 동의').uncheck();
 expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('benefit-monitor:beta:v1')!).events)).toEqual([]);
 await page.getByRole('button',{name:'개인화 설정·기록 삭제',exact:true}).click();
 expect(await page.evaluate(()=>localStorage.getItem('benefit-monitor:beta:v1'))).toBeNull();
});
for(const width of [390,1440])test(`beta accessibility and screenshot ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});await setup(page);
 await page.getByRole('button',{name:/저녁 산책·야간 문화 ·/}).click();
 await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
 expect(await page.evaluate(async()=>(await (window as any).axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}})).violations)).toEqual([]);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 mkdirSync('../docs/qa/screenshots',{recursive:true});await page.screenshot({path:`../docs/qa/screenshots/beta-${width}.png`,fullPage:true});
});
test('storage denial and expiry never remove basic discovery or fabricate recommendations',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(window,'localStorage',{get(){throw new Error('blocked');}}));
 await setup(page);await page.getByRole('button',{name:'개인화 설정 저장',exact:true}).click();
 await expect(page.locator('#beta')).toContainText('저장하지 못했습니다');
 await page.getByLabel('이 기기의 행동 기록에 동의').check();await expect(page.getByLabel('이 기기의 행동 기록에 동의')).not.toBeChecked();
 await page.clock.fastForward(13*3600000);
 await expect(page.locator('#beta .topic-button')).toHaveCount(0);
 await expect(page.locator('#beta')).toContainText('현재 표시할 수 있는 주제가 없습니다');
});
test('revocation stops learning even if persistence fails',async({page})=>{
 await setup(page);await page.getByLabel('이 기기의 행동 기록에 동의').check();
 await page.evaluate(()=>{Storage.prototype.setItem=()=>{throw new Error('quota');};Storage.prototype.removeItem=()=>{throw new Error('blocked');};});
 await page.getByLabel('이 기기의 행동 기록에 동의').uncheck();
 await expect(page.getByLabel('이 기기의 행동 기록에 동의')).not.toBeChecked();
 await expect(page.locator('#beta')).toContainText('기록은 중단했지만');
 await page.getByRole('button',{name:/저녁 산책·야간 문화 ·/}).click();
 await page.getByRole('button',{name:'관심 있어요',exact:true}).click();
 await expect(page.locator('#beta')).toContainText('선택 사항인 행동 기록에 동의');
});
test('another tab cannot resurrect withdrawn consent or deleted settings',async({page,context})=>{
 await setup(page);await page.getByLabel('이 기기의 행동 기록에 동의').check();
 const other=await context.newPage();await setup(other);
 await page.getByLabel('이 기기의 행동 기록에 동의').uncheck();
 await expect(other.getByLabel('이 기기의 행동 기록에 동의')).not.toBeChecked();
 await other.getByRole('button',{name:/저녁 산책·야간 문화 ·/}).click();
 expect(await other.evaluate(()=>JSON.parse(localStorage.getItem('benefit-monitor:beta:v1')!).events)).toEqual([]);
 await page.getByRole('button',{name:'개인화 설정·기록 삭제',exact:true}).click();
 await other.getByRole('button',{name:'관심 있어요',exact:true}).click();
 expect(await other.evaluate(()=>localStorage.getItem('benefit-monitor:beta:v1'))).toBeNull();
});
