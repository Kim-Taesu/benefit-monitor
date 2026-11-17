import {test,expect} from '@playwright/test';
import {snapshot,NOW} from '../fixtures';

const APT='https://www.applyhome.co.kr/ai/aia/selectAPTLttotPblancDetail.do?houseManageNo=2026000497&pblancNo=2026000497';
const CAL='https://www.applyhome.co.kr/ai/aib/selectSubscrptCalenderView.do';
const sub=(over:Record<string,unknown>={})=>({id:'2026000497',name:'[테스트] 중화역 센트로',area:'서울',district:'중랑구',kind:'apt',units:113,
 area_min:45.02,area_max:126.81,price_min:65800,price_max:202100,move_in:'2029-02',regulation:['투기과열지구'],
 steps:[{label:'특별공급',start:'2026-11-03',end:'2026-11-03'},{label:'1순위',start:'2026-11-04',end:'2026-11-05'},{label:'2순위',start:'2026-11-06',end:'2026-11-06'}],
 announce:'2026-11-12',contract_start:'2026-11-24',contract_end:'2026-11-26',url:APT,detail:'checked',checked_at:'2026-11-04T00:12:00+09:00',
 supply:'아파트 분양',notice_date:'2026-10-27',types:[],special_kinds:[],notice_pdf:null,trade_status:'unavailable',...over});
const bundle=(items:unknown[])=>({schema_version:1,source:'subscriptions',fetched_at:'2026-11-04T00:12:00+09:00',window_days:14,notice:'[테스트] 청약홈',items});
const ITEMS=[sub(),
 sub({id:'2026910275',name:'[테스트] 분당 무순위',area:'경기',district:'성남시 분당구',kind:'remain',units:null,area_min:null,area_max:null,price_min:null,price_max:null,
  move_in:null,regulation:[],steps:[{label:'무순위 접수',start:'2026-11-05',end:'2026-11-05'}],announce:null,contract_start:null,contract_end:null,url:CAL,detail:'failed',checked_at:null}),
 sub({id:'2026950090',name:'[테스트] 오피스텔',kind:'officetel',district:'관악구',steps:[{label:'청약 접수',start:'2026-11-10',end:'2026-11-11'}],url:CAL})];

async function open(page:import('@playwright/test').Page,raw:unknown){
 await page.clock.install({time:new Date(NOW)});
 const origin=new URL(String(test.info().project.use.baseURL)).origin,requests:string[]=[];
 await page.route('**/*',route=>{
  const u=new URL(route.request().url());requests.push(u.origin);
  if(u.origin!==origin)return route.abort();
  if(u.pathname.endsWith('/briefing.json'))return route.fulfill({json:raw});
  return route.continue();
 });
 await page.goto('./');
 return requests;
}

for(const width of [360,1280])test(`청약 tab shows Seoul·Gyeonggi schedule cards grouped by day ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 const requests=await open(page,snapshot(undefined,{subscriptions:bundle(ITEMS)}));
 const tab=page.getByRole('tab',{name:/청약/});
 await expect(tab).toContainText('3');
 await expect(page.getByRole('button',{name:/청약 일정/})).toHaveCount(0);  // 혜택 탭 칩은 없앴다
 await tab.click();
 await expect(page).toHaveURL(/#subscriptions$/);
 await expect(tab).toHaveAttribute('aria-selected','true');
 const section=page.locator('section.subs');
 await expect(section.locator('h2')).toContainText('3곳');
 await expect(section.locator('.subs-day')).toHaveText([/오늘 · 11\/4\(수\)/,/내일 · 11\/5\(목\)/,/다음 주/]);
 const first=section.locator('.subs-card').first();
 await expect(first).toContainText('1순위 접수 중 · 11/5까지');
 await expect(first).toContainText('서울 중랑구');
 await expect(first).toContainText('113세대 · 전용 45~127㎡ · 6.6억~20.2억*');
 await expect(first.locator('.subs-steps li.now')).toHaveText(/1순위 11\/4~5/);
 await expect(first.locator('.subs-steps li.done')).toHaveText(/특별공급 11\/3/);
 await expect(first.locator('.subs-steps li')).toHaveCount(5);
 await expect(first.getByRole('link',{name:/청약홈 공고 보기/})).toHaveAttribute('href',APT);
 const remain=section.locator('.subs-card').nth(1);
 await expect(remain).toContainText('무순위 내일 접수');
 await expect(remain).toContainText('세대수·면적·금액은 공고에서 확인하세요');
 await expect(remain.getByRole('link',{name:/청약홈 달력에서 보기/})).toHaveAttribute('href',CAL);
 // 지역·종류 칩
 await section.getByRole('button',{name:/^경기/}).click();
 await expect(section.locator('.subs-card')).toHaveCount(1);
 await section.getByRole('button',{name:/^경기/}).click();
 await section.getByRole('button',{name:/오피스텔·임대/}).click();
 await expect(section.locator('.subs-card')).toHaveCount(1);
 await expect(section.locator('.subs-card')).toContainText('[테스트] 오피스텔');
 await section.getByRole('button',{name:/오피스텔·임대/}).click();
 // 용어 풀이는 접혀 있다가 열린다
 await expect(section.locator('.subs-glossary dl')).toBeHidden();
 await section.getByText('특별공급·1순위·무순위가 뭐예요?').click();
 await expect(section.locator('.subs-glossary dl')).toBeVisible();
 if(width===360)await section.locator('.subs-card').first().scrollIntoViewIfNeeded();
 await page.screenshot({path:`../.ax/plans/shots/subscriptions-${width}.png`,fullPage:width===1280});
 // 혜택 탭으로 돌아가면 혜택 목록
 await page.getByRole('tab',{name:/혜택/}).click();
 await expect(section).toBeHidden();
 await expect(page.locator('.card-grid')).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
 expect(requests.every(x=>x===origin(page))).toBe(true);
});
const origin=(page:import('@playwright/test').Page)=>new URL(page.url()).origin;

test('내 지역 complex goes first and is flagged; search narrows complexes',async({page})=>{
 const requests=await open(page,snapshot(undefined,{subscriptions:bundle([sub({id:'2026000001',name:'[테스트] 가 관악',district:'관악구'}),sub()])}));
 await page.locator('#region').selectOption('중랑구');  // 혜택 탭의 내 지역이 청약 탭에도 이어진다
 await page.getByRole('tab',{name:/청약/}).click();
 await expect(page.locator('#subs-region')).toHaveValue('중랑구');
 const cards=page.locator('.subs-card');
 await expect(cards.first()).toContainText('중화역');
 await expect(cards.first()).toContainText('📍 내 지역');
 await expect(cards.nth(1)).not.toContainText('📍 내 지역');
 await page.locator('#subs-q').fill('관악');
 await expect(cards).toHaveCount(1);
 expect(requests.length).toBeGreaterThan(0);
});

test('stale bundle shows a calendar link instead of cards',async({page})=>{
 await open(page,snapshot(undefined,{subscriptions:{...bundle(ITEMS),fetched_at:'2026-11-02T00:12:00+09:00'}}));
 await page.getByRole('tab',{name:/청약/}).click();
 await expect(page.locator('#panel-subscriptions')).toContainText('청약 일정을 가져오지 못했어요');
 await expect(page.locator('#panel-subscriptions').getByRole('link',{name:/청약홈 달력 보기/})).toHaveAttribute('href',CAL);
 await expect(page.locator('section.subs')).toHaveCount(0);
});

test('empty window shows the calendar link',async({page})=>{
 await open(page,snapshot(undefined,{subscriptions:bundle([])}));
 await page.getByRole('tab',{name:/청약/}).click();
 await expect(page.locator('section.subs .empty-state')).toContainText('앞으로 14일 안에 서울·경기 접수 일정이 없어요');
 await expect(page.locator('section.subs .empty-state').getByRole('link',{name:/청약홈 달력 보기/})).toHaveAttribute('href',CAL);
});

test('cards are removed when the bundle goes stale while the page is open',async({page})=>{
 await open(page,snapshot(undefined,{subscriptions:bundle(ITEMS)}));
 await page.getByRole('tab',{name:/청약/}).click();
 await expect(page.locator('section.subs')).toHaveCount(1);
 // 수집 00:12 + 30시간 = 다음 날 06:12. NOW(12:00)에서 19시간 뒤면 지난다.
 await page.clock.fastForward('19:00:00');
 await expect(page.locator('section.subs')).toHaveCount(0);
 await expect(page.locator('#panel-subscriptions')).toContainText('청약 일정을 가져오지 못했어요');
});

const PDF='https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026930045&pblancNo=2026930045&atchmnflSeqNo=2023023&atchmnflSn=9';
for(const width of [360,1280])test(`card shows per-type table, supply type and notice PDF ${width}`,async({page})=>{
 await page.setViewportSize({width,height:900});
 const jamsil=sub({id:'2026930045',name:'[테스트] 잠실 재공급',district:'송파구',kind:'remain',supply:'계약취소 재공급',units:3,trade_status:'checked',
  steps:[{label:'특별공급',start:'2026-11-05',end:'2026-11-05'},{label:'일반공급',start:'2026-11-06',end:'2026-11-06'}],notice_date:'2026-11-04',notice_pdf:PDF,url:CAL,
  types:[{label:'43',area:43.73,pyeong:20,general:1,special:0,price:110548,trade:{amount:238000,month:'2026-06',kind:'입주권'}},{label:'59A',area:59.47,pyeong:26,general:1,special:0,price:157939,trade:{amount:327000,month:'2026-04',kind:'입주권'}},
   {label:'84D',area:84.96,pyeong:34,general:0,special:1,price:185607,trade:{amount:430000,month:'2026-07',kind:'입주권'}},{label:'99',area:99.1,pyeong:40,general:1,special:0,price:null,trade:null}],
  special_kinds:[{name:'신혼부부',count:1}]});
 await open(page,snapshot(undefined,{subscriptions:bundle([jamsil])}));
 await page.getByRole('tab',{name:/청약/}).click();
 const card=page.locator('.subs-card').first();
 await expect(card).toContainText('계약취소 재공급');
 await expect(card).toContainText('총 3세대 · 공고 11/4');
 const rows=card.locator('.subs-types tbody tr');
 await expect(rows).toHaveCount(3);
 await expect(rows.nth(0)).toContainText(/일반 1.*43.*20평.*11\.1억/);
 await expect(rows.nth(0).locator('td.trade')).toHaveText(/23\.8억\s*입주권 26\.06/);
 await expect(rows.nth(2).locator('td.trade')).toHaveText(/43\.0억|43억/);
 await expect(rows.nth(2)).toContainText(/특공 1.*84D.*34평.*18\.6억/);
 await card.getByRole('button',{name:'주택형 1개 더 보기'}).click();
 await expect(rows).toHaveCount(4);
 await expect(rows.nth(3)).toContainText('문의');
 await expect(card).toContainText('특공 1세대: 신혼부부 1');
 await expect(card.locator('.subs-steps')).toContainText('일반공급 11/6');
 await expect(card.getByRole('link',{name:/모집공고문 PDF/})).toHaveAttribute('href',PDF);
 await card.scrollIntoViewIfNeeded();
 await page.screenshot({path:`../.ax/plans/shots/subscriptions-card-${width}.png`});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
});
