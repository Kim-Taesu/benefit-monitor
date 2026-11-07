import {test,expect,type Page} from '@playwright/test';
import {item,snapshot,NOW} from '../fixtures';

const TOKEN='github_pat_TESTONLY_0123456789abcdef';
const CID='0123456789abcdef01234567';
const REPO='/repos/Kim-Taesu/benefit-monitor';
const auto=item({title:'[테스트] 자동 공개 항목',review:{kind:'ai_auto',document_count:2,checked_at:'2026-11-04T09:00:00+09:00',candidate_id:CID,title_key:'테스트 자동 공개 항목',
 documents:[{url:'https://mediahub.seoul.go.kr/archives/1',title:'[테스트] 원문 1'},{url:'https://mediahub.seoul.go.kr/archives/2',title:'[테스트] 원문 2'}]}});
const human=item({title:'[테스트] 사람 검토 항목',url:'https://mediahub.seoul.go.kr/archives/9'});
const encode=(v:unknown)=>Buffer.from(JSON.stringify(v)).toString('base64');

type Seen={origins:string[];github:{method:string;path:string;auth:string;body:unknown}[]};
async function setup(page:Page,raw:unknown,takedowns:unknown[]=[]):Promise<Seen>{
 const seen:Seen={origins:[],github:[]};
 const site=new URL(String(test.info().project.use.baseURL)).origin;
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/*',async route=>{
  const request=route.request(),u=new URL(request.url());seen.origins.push(u.origin);
  if(u.origin==='https://api.github.com'){
   seen.github.push({method:request.method(),path:u.pathname+u.search,auth:request.headers().authorization||'',body:request.postData()?JSON.parse(request.postData()!):undefined});
   if(request.method()==='GET'&&u.pathname===REPO+'/contents/ai-takedowns.json')return route.fulfill({json:{encoding:'base64',sha:'sha1',content:encode(takedowns)}});
   if(request.method()==='PUT'&&u.pathname===REPO+'/contents/ai-takedowns.json'){takedowns=JSON.parse(Buffer.from(JSON.parse(request.postData()!).content,'base64').toString());return route.fulfill({status:200,json:{}});}
   if(request.method()==='POST'&&u.pathname===REPO+'/actions/workflows/briefing-pages.yml/dispatches')return route.fulfill({status:204,body:''});
   return route.fulfill({status:500,body:''});
  }
  if(u.origin!==site)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 return seen;
}
const allowed=(seen:Seen)=>seen.origins.every(o=>o===new URL(String(test.info().project.use.baseURL)).origin||o==='https://api.github.com');

test('without a token the actions are disabled and nothing is sent to GitHub',async({page})=>{
 const seen=await setup(page,snapshot([auto,human]));
 await page.goto('./admin.html');
 await expect(page.locator('meta[name="robots"]')).toHaveAttribute('content',/noindex/);
 const row=page.locator('[data-candidate]');
 await expect(row).toHaveCount(1);
 await expect(row).toContainText('[테스트] 자동 공개 항목');
 await expect(row.getByRole('link',{name:'[테스트] 원문 1'})).toHaveAttribute('href','https://mediahub.seoul.go.kr/archives/1');
 await expect(row.getByRole('button',{name:'내리기'})).toBeDisabled();
 await expect(page.getByText('내린 항목 목록은 토큰을 넣어야 볼 수 있습니다')).toBeVisible();
 await expect(page.getByText('Kim-Taesu/benefit-monitor')).toBeVisible();
 expect(seen.github).toHaveLength(0);
 expect(allowed(seen)).toBe(true);
});

test('take down with a mocked GitHub API shows the delay notice; restore puts it back',async({page})=>{
 const seen=await setup(page,snapshot([auto]));
 await page.goto('./admin.html');
 await page.getByLabel('GitHub 토큰').fill(TOKEN);
 await page.getByRole('button',{name:'토큰 저장'}).click();
 await expect(page.getByText('내린 항목이 없습니다')).toBeVisible();
 const row=page.locator(`[data-candidate="${CID}"]`);
 await row.getByLabel('메모').fill('기간이 틀림');
 await row.getByRole('button',{name:'내리기'}).click();
 await expect(page.getByRole('status')).toContainText('반영까지 2~3분 걸립니다');
 const put=seen.github.find(c=>c.method==='PUT')!;
 expect(put.body).toMatchObject({branch:'briefing-data',sha:'sha1'});
 const dispatch=seen.github.find(c=>c.method==='POST')!;
 expect(dispatch.body).toEqual({ref:'main',inputs:{apply_takedowns:true}});
 for(const c of seen.github){expect(c.auth).toBe('Bearer '+TOKEN);expect(c.path).not.toContain(TOKEN);}
 const down=page.locator(`[data-taken-down="${CID}"]`);
 await expect(down).toContainText('기간이 틀림');
 await down.getByRole('button',{name:'되살리기'}).click();
 await expect(page.getByRole('status')).toContainText('되살렸습니다');
 await expect(page.getByText('내린 항목이 없습니다')).toBeVisible();
 // Reloading keeps the token in this browser only; deleting it disables the actions again.
 await page.reload();
 await expect(page.getByText('내린 항목이 없습니다')).toBeVisible();
 await page.getByRole('button',{name:'토큰 삭제'}).click();
 await expect(row.getByRole('button',{name:'내리기'})).toBeDisabled();
 expect(await page.evaluate(()=>JSON.stringify(localStorage))).not.toContain(TOKEN);
 expect(allowed(seen)).toBe(true);
});

test('credit exhausted status is shown with the last success day',async({page})=>{
 const seen=await setup(page,snapshot([auto],{ai_status:{state:'credit_exhausted',last_success_day:'2026-11-03',updated_at:'2026-11-04T08:00:00+09:00'}}));
 await page.goto('./admin.html');
 await expect(page.getByText('AI 조사 중지: 크레딧 소진')).toBeVisible();
 await expect(page.locator('[data-ai-status]')).toContainText('2026-11-03');
 expect(allowed(seen)).toBe(true);
});

test('the main page does not link to the admin page',async({page})=>{
 await setup(page,snapshot([auto]));
 await page.goto('./');
 await expect(page.locator('#results article').first()).toBeVisible();
 await expect(page.locator('a[href*="admin"]')).toHaveCount(0);
});
