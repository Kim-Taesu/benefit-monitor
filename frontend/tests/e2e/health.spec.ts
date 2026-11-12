import {test,expect} from '@playwright/test';
import {snapshot,NOW} from '../fixtures';

const item=(n:number,over:Record<string,unknown>={})=>({id:`n-${n}`,title:`[테스트] 공지 ${n}`,url:`https://www.gangseo.seoul.kr/health/ht060701/${n}`,date:'2026-11-03',dept:'보건관리과',hint:false,...over});
const board=(over:Record<string,unknown>={})=>({district:'강서구',name:'강서구보건소',list_url:'https://www.gangseo.seoul.kr/health/ht060701',home_url:'https://www.gangseo.seoul.kr/health',status:'checked',reason:null,checked_at:'2026-11-04T00:07:00+09:00',items:[],...over});

for(const width of [390,1440])test(`health notice tab shows hint notices first and blocked centres ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.clock.install({time:new Date(NOW)});
 const raw=snapshot(undefined,{health_notices:{schema_version:1,source:'health_notices',fetched_at:'2026-11-04T00:07:00+09:00',notice:'[테스트] 보건소 공지',programs:[{district:'강서구',center:'강서구보건소',name:'대사증후군 관리',url:'https://www.gangseo.seoul.kr/health/ht020103',status:'checked',checked_at:'2026-11-04T00:07:00+09:00'}],boards:[
  board({items:[item(1,{date:'2026-11-04'}),item(2,{title:'[테스트] 독감 무료 접종 안내',hint:true})]}),
  board({district:'은평구',name:'은평구보건소',list_url:'https://www.ep.go.kr/health/index.do',home_url:'https://www.ep.go.kr/health/index.do',status:'unavailable',reason:'robots가 사이트 전체 수집을 막음',checked_at:null}),
 ]}});
 (raw as Record<string,unknown>).health_notes=[{url:'https://www.gangseo.seoul.kr/health/ht020103',district:'강서구',sentence:'[테스트] 강서구 20~69세라면 대사증후군 검진을 무료로 받을 수 있어요. 전화로 예약하고 받아보세요.',generated_at:'2026-11-04T01:00:00+09:00'}];
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
 await expect(section.locator('.health-programs').getByRole('link',{name:/대사증후군 관리/})).toBeHidden();
 await section.locator('#health-district').selectOption('강서구');
 await expect(section.locator('.health-programs').getByRole('link',{name:/대사증후군 관리/})).toHaveAttribute('href','https://www.gangseo.seoul.kr/health/ht020103');
 await expect(section.locator('.health-programs .health-note')).toContainText('AI 작성');
 await expect(section.locator('.health-programs .health-note')).toContainText('무료로 받을 수 있어요');
 await section.locator('#health-district').selectOption('은평구');
 await expect(section.getByRole('link',{name:/은평구보건소 바로가기/}).first()).toHaveAttribute('href','https://www.ep.go.kr/health/index.do');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 expect(requests.every(x=>x===origin)).toBe(true);
});

const prog=(district:string,name:string,path:string)=>({district,center:`${district}보건소`,name,url:`https://www.example.go.kr/${path}`,status:'checked',checked_at:'2026-11-04T00:07:00+09:00'});
for(const width of [390,1440])test(`health weekly card filters by kind and district ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 await page.clock.install({time:new Date(NOW)});
 const raw=snapshot(undefined,{health_notices:{schema_version:1,source:'health_notices',fetched_at:'2026-11-04T00:07:00+09:00',notice:'[테스트] 보건소 공지',programs:[
  prog('강서구','대사증후군 관리','gs1'),prog('강서구','임신 준비 검사','gs2'),prog('광진구','대사증후군 검진','gj1'),prog('송파구','결핵검사','sp1')],boards:[
  board({items:[]}),
  board({district:'광진구',name:'광진구보건소',items:[item(7,{date:'2026-11-04',hint:true})]}),
  board({district:'송파구',name:'송파구보건소',items:[]}),
 ]}});
 (raw as Record<string,unknown>).health_notes=[{url:'https://www.example.go.kr/gs1',district:'강서구',sentence:'[테스트] 강서구 20~69세라면 대사증후군 검진을 무료로 받을 수 있어요. 전화로 예약하고 받아보세요.',generated_at:'2026-11-04T01:00:00+09:00'}];
 const origin=new URL(String(test.info().project.use.baseURL)).origin;
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.origin!==origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 await page.goto('./');
 await page.getByRole('tab',{name:'보건소'}).click();
 const card=page.locator('section[aria-labelledby="health-weekly-title"]');
 await expect(card).toContainText('이번 주 보건소 추천');
 await expect(card).toContainText('AI 작성');
 await expect(card).toContainText('[테스트] 강서구 20~69세라면 대사증후군 검진을 무료로 받을 수 있어요.');
 await expect(card).not.toContainText('전화로 예약하고');
 await expect(card).toContainText('새 공지 1건');
 await expect(card.locator('.health-weekly-district')).toHaveCount(3);
 const chip=card.getByRole('button',{name:'대사증후군 검진·관리 2개 구'});
 await chip.click();
 await expect(chip).toHaveAttribute('aria-pressed','true');
 await expect(card.locator('.health-weekly-district')).toHaveCount(2);
 await expect(card).not.toContainText('송파구');
 await chip.click();
 await expect(chip).toHaveAttribute('aria-pressed','false');
 await expect(card.locator('.health-weekly-district')).toHaveCount(3);
 await page.locator('#health-district').selectOption('광진구');
 await expect(card.locator('.health-weekly-district')).toHaveCount(1);
 await expect(card).toContainText('광진구');
 await expect(card).not.toContainText('강서구');
 await page.locator('#health-district').selectOption('');
 await card.scrollIntoViewIfNeeded();
 if(width===390){
  await page.screenshot({path:'../.ax/plans/shots/health-weekly-390.png'});
 }
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
});

test('health weekly card hides AI badge when no summaries exist',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 const raw=snapshot(undefined,{health_notices:{schema_version:1,source:'health_notices',fetched_at:'2026-11-04T00:07:00+09:00',notice:'[테스트] 보건소 공지',programs:[prog('강서구','대사증후군 관리','gs1')],boards:[board({items:[]})]}});
 const origin=new URL(String(test.info().project.use.baseURL)).origin;
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.origin!==origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 await page.goto('./');
 await page.getByRole('tab',{name:'보건소'}).click();
 const card=page.locator('section[aria-labelledby="health-weekly-title"]');
 await expect(card).toContainText('이번 주 보건소 추천');
 await expect(card).toContainText('공식 페이지 링크입니다. 대상·기간·비용은 원문에서 확인하세요.');
 await expect(card).not.toContainText('AI 작성');
 await expect(card).not.toContainText('AI가 공식 페이지를 요약했습니다');
});
