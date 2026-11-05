import {test,expect} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {item,snapshot,NOW} from '../fixtures';

for(const width of [390,1440])test(`published cards and expiry fallback ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.clock.install({time:new Date(NOW)});
 const row=item(),raw=snapshot([row],{topic_cards:{schema_version:1,generated_at:'2026-11-04T08:00:00+09:00',valid_until:'2026-11-04T13:00:00+09:00',used_fallback:false,topics:[{id:'culture',title:'문화·체험',items:[{source:row.source,url:row.url,facts:row}]}]}});
 const requests:string[]=[];
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());requests.push(u.origin);
  if(u.origin!==new URL(String(test.info().project.use.baseURL)).origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 await page.goto('./');
 await expect(page.locator('[data-topic="culture"]')).toContainText('문화·체험');
 await page.locator('[data-topic="culture"]').click();
 await expect(page.locator('#results article')).toHaveCount(1);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 mkdirSync('../.tools/goal-screenshots',{recursive:true});
 await page.screenshot({path:`../.tools/goal-screenshots/published-${width}.png`,fullPage:true});
 await page.clock.fastForward(2*3600000);
 await expect(page.locator('[data-topic="culture"]')).toContainText('전시·문화 체험');
 await expect(page.locator('#results article')).toHaveCount(1);
 expect(requests.every(x=>x===new URL(String(test.info().project.use.baseURL)).origin)).toBe(true);
});
