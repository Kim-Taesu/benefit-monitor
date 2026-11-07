import {test,expect} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {snapshot,NOW} from '../fixtures';
import {FESTIVAL_DETAIL} from '../../src/festivals';

function festival(n:number,over:Record<string,unknown>={}){
 const id=`00000000-0000-4000-8000-00000000000${n}`;
 return {id,name:`[테스트] 축제 ${n}`,start:'2026-11-03',end:'2026-11-05',region:'경상북도 구미시',place:'역 앞 광장',organizer:'[테스트] 시청',
  fee_status:'free',fee_text:'무료',discount:'',summary:'[테스트] 축제 소개',programs:'[테스트] 공연',homepage:'',
  culture_tourism:false,url:FESTIVAL_DETAIL+id,modified:null,...over};
}

for(const width of [390,1440])test(`festival section filters and stays separate ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.clock.install({time:new Date(NOW)});
 const raw=snapshot(undefined,{festivals:{schema_version:1,source:'kfes',fetched_at:'2026-11-04T06:00:00+09:00',notice:'[테스트] 관광공사 게시 정보',items:[
  festival(1,{culture_tourism:true}),
  festival(2,{start:'2026-11-20',end:'2026-11-21',region:'부산광역시 수영구',fee_status:'paid',fee_text:'유료 (20% 할인)',discount:'[테스트] 지역화폐 10% 할인'}),
  festival(3,{start:'2026-10-01',end:'2026-11-01'}),
 ]}});
 const origin=new URL(String(test.info().project.use.baseURL)).origin,requests:string[]=[];
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());requests.push(u.origin);
  if(u.origin!==origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 await page.goto('./');
 const section=page.locator('#festivals');
 await expect(section.locator('h2')).toContainText('2건');
 await expect(section.locator('article').first()).toContainText('문화관광축제');
 await expect(section.locator('article').nth(1)).toContainText('할인: [테스트] 지역화폐 10% 할인');
 await expect(page.locator('#results article')).toHaveCount(1);
 await section.getByRole('button',{name:'개최예정'}).click();
 await expect(section.locator('article')).toHaveCount(1);
 await expect(section.locator('article')).toContainText('16일 후 시작');
 await section.getByRole('button',{name:'개최예정'}).click();
 await section.locator('#festival-region').selectOption('경상북도');
 await expect(section.locator('article')).toHaveCount(1);
 await expect(section.getByRole('link',{name:/대한민국 구석구석 안내/})).toHaveAttribute('href',FESTIVAL_DETAIL+'00000000-0000-4000-8000-000000000001');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 mkdirSync('../.tools/goal-screenshots',{recursive:true});
 await section.screenshot({path:`../.tools/goal-screenshots/festivals-${width}.png`});
 expect(requests.every(x=>x===origin)).toBe(true);
});

test('missing festival bundle hides the section',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot()}));
 await page.goto('./');
 await expect(page.locator('#results article')).toHaveCount(1);
 await expect(page.locator('#festivals')).toHaveCount(0);
});
