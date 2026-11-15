import {test,expect} from '@playwright/test';
import {item,snapshot,NOW} from '../fixtures';

const older=()=>item({verified_at:'2026-11-03T06:00:00+09:00'});
const added=()=>item({url:'https://mediahub.seoul.go.kr/archives/9',summary:'[테스트] 새로 공개된 안내',districts:[],labels:{category:'생활지원',region:'서울'},verified_at:'2026-11-01T06:00:00+09:00'});
test('first visit explains the service; a later visit marks only newly published items',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 const state={rows:[older()],generated:'2026-11-04T07:00:00+09:00',report:'2026-11-04T06:55:00+09:00',through:'2026-11-05T00:00:00+09:00'};
 const requests:{method:string;body:string|null;origin:string}[]=[];
 await page.route('**/*',route=>{
  const request=route.request(),u=new URL(request.url());requests.push({method:request.method(),body:request.postData(),origin:u.origin});
  if(u.origin!==new URL(String(test.info().project.use.baseURL)).origin)return route.abort();
  return u.pathname.endsWith('/briefing.json')?route.fulfill({json:snapshot(state.rows,{generated_at:state.generated,source_report_at:state.report,valid_through:state.through})}):route.continue();
 });
 await page.goto('./');
 const intro=page.locator('.intro');
 await expect(intro).toContainText('서울에서 챙길 수 있는 생활 혜택을 매일 모아 드려요');
 await expect(page.locator('.since')).toHaveCount(0);await expect(page.locator('.badge.new')).toHaveCount(0);
 await page.reload();await expect(intro).toBeVisible();
 await intro.getByRole('button',{name:'닫기'}).click();await expect(intro).toHaveCount(0);
 await page.reload();await expect(page.locator('#results article')).toHaveCount(1);await expect(intro).toHaveCount(0);
 const stored=await page.evaluate(()=>localStorage.getItem('benefit-monitor:visit:v1'));
 expect(stored).not.toContain('http');expect(stored).not.toContain('seoul');

 // 같은 날 저녁: 예전에 확인된 항목이 새로 공개되고, 기존 항목은 다시 확인만 됐다.
 await page.clock.fastForward(7*3600000);
 state.rows=[{...older(),verified_at:'2026-11-04T18:00:00+09:00'},added()];
 state.generated='2026-11-04T18:30:00+09:00';state.report='2026-11-04T18:25:00+09:00';
 await page.reload();
 await expect(page.locator('#results article')).toHaveCount(2);await expect(intro).toHaveCount(0);
 await expect(page.locator('.since')).toContainText('11월 4일 방문 이후');
 await expect(page.locator('.badge.new')).toHaveCount(1);
 await expect(page.locator('#results article',{hasText:'새로 공개된 안내'}).locator('.badge.new')).toHaveText('새로 올라옴');
 await page.locator('.since').getByRole('button',{name:/새 혜택/}).click();
 await expect(page.locator('#results article')).toHaveCount(1);
 await expect(page.getByRole('button',{name:/새로 올라옴/})).toHaveAttribute('aria-pressed','true');
 await page.reload();await expect(page.locator('.badge.new')).toHaveCount(1);

 await page.getByRole('button',{name:'저장한 것 모두 지우기'}).click();
 expect(await page.evaluate(()=>localStorage.getItem('benefit-monitor:visit:v1'))).toBeNull();
 await expect(page.locator('.badge.new')).toHaveCount(0);
 expect(requests.every(r=>r.method==='GET'&&r.body===null&&r.origin===new URL(String(test.info().project.use.baseURL)).origin)).toBe(true);
});
test('invalid data never starts a visit record',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot([older()],{status:'collection_failed'})}));
 await page.goto('./');await expect(page.getByText('이번 수집을 완료하지 못했습니다',{exact:true})).toBeVisible();
 await expect(page.locator('.intro')).toHaveCount(0);
 expect(await page.evaluate(()=>localStorage.getItem('benefit-monitor:visit:v1'))).toBeNull();
});
