import {test,expect} from '@playwright/test';
import {snapshot,NOW} from '../fixtures';

const item=(n:number,over:Record<string,unknown>={})=>({id:`n-${n}`,title:`[테스트] 공지 ${n}`,url:`https://www.gangseo.seoul.kr/health/ht060701/${n}`,date:'2026-11-03',dept:'보건관리과',hint:false,...over});
const board=(over:Record<string,unknown>={})=>({district:'강서구',name:'강서구보건소',list_url:'https://www.gangseo.seoul.kr/health/ht060701',home_url:'https://www.gangseo.seoul.kr/health',status:'checked',reason:null,checked_at:'2026-11-04T00:07:00+09:00',items:[],...over});

for(const width of [390,1440])test(`health notice tab shows hint notices first and blocked centres ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.clock.install({time:new Date(NOW)});
 const raw=snapshot(undefined,{health_notices:{schema_version:1,source:'health_notices',fetched_at:'2026-11-04T00:07:00+09:00',notice:'[테스트] 보건소 공지',boards:[
  board({items:[item(1,{date:'2026-11-04'}),item(2,{title:'[테스트] 독감 무료 접종 안내',hint:true})]}),
  board({district:'은평구',name:'은평구보건소',list_url:'https://www.ep.go.kr/health/index.do',home_url:'https://www.ep.go.kr/health/index.do',status:'unavailable',reason:'robots가 사이트 전체 수집을 막음',checked_at:null}),
 ]}});
 const origin=new URL(String(test.info().project.use.baseURL)).origin,requests:string[]=[];
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());requests.push(u.origin);
  if(u.origin!==origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 await page.goto('./');
 await page.getByRole('tab',{name:'보건소'}).click();
 await expect(page).toHaveURL(/#health$/);
 const section=page.locator('#health');
 await expect(section.locator('h2')).toContainText('2건');
 await expect(section.locator('.health-row').first()).toContainText('독감 무료 접종 안내');
 await section.getByRole('button',{name:/검진·접종·프로그램만/}).click();
 await expect(section.locator('.health-row')).toHaveCount(1);
 await section.locator('#health-district').selectOption('은평구');
 await expect(section.getByRole('link',{name:/은평구보건소 바로가기/}).first()).toHaveAttribute('href','https://www.ep.go.kr/health/index.do');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(requests.every(x=>x===origin)).toBe(true);
});
