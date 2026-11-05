import { test, expect } from '@playwright/test';
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { item, snapshot, NOW } from '../fixtures';
const require=createRequire(import.meta.url);
const axePath=require.resolve('axe-core/axe.min.js');
const shots=process.env.BENEFIT_SCREENSHOT_DIR||'../docs/qa/screenshots';
const items=[
 item(),
 item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'[테스트] 생활지원 신청 안내',labels:{category:'생활지원',region:'은평구',audience:'공고 대상자',action:'신청·예약 필요'},districts:['은평구'],fee_status:'unknown',conditions:'테스트 자료. 자격·소득 조건과 참여 비용은 공식 안내 확인 필요.'}),
 item({url:'https://mediahub.seoul.go.kr/archives/3',summary:'[테스트] 결제 시 할인 안내',labels:{category:'할인·적립',region:'전국',audience:'해당 결제수단 회원',action:'결제 시 적용'},districts:[],fee_status:'paid',payment_terms:{method:'테스트 결제수단',funding_source:'테스트 충전금',excluded_methods:'다른 재원 제외',minimum_spend:'테스트 최소지출',limit:'테스트 한도',evidence_url:'https://mediahub.seoul.go.kr/archives/3'}}),
 item({url:'https://mediahub.seoul.go.kr/archives/4',summary:'[테스트] 평생학습 강좌 안내',labels:{category:'교육·강좌',region:'서울',audience:'서울시민',action:'신청·예약 필요'},districts:[],deadline_at:null,valid_until:null,validity_kind:'ongoing',fee_status:'mixed'}),
 item({url:'https://mediahub.seoul.go.kr/archives/5',summary:'[테스트] 주민 참여 공모 안내',labels:{category:'공모·참여',region:'강서구',audience:'지역 주민',action:'응모'},valid_until:'2026-11-04',deadline_at:'2026-11-04T18:00:00+09:00',fee_status:'free'}),
 item({url:'https://mediahub.seoul.go.kr/archives/6',summary:'[테스트] 다음 주 문화 체험',labels:{category:'문화·체험',region:'서울',audience:'누구나',action:'바로 이용'},districts:[],valid_from:'2026-11-06',deadline_at:null,fee_status:'free'}),
];
async function setup(page,body:unknown=snapshot(items)){
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.origin!==new URL(String(test.info().project.use.baseURL)).origin)return route.abort();
  if(url.pathname.endsWith('/briefing.json'))return route.fulfill({json:body});
  return route.continue();
 });
}
async function capture(page,name:string){mkdirSync(shots,{recursive:true});await page.screenshot({path:`${shots}/${name}.png`,fullPage:true});}
for(const width of [360,390,768,1440])test(`responsive ${width}px, semantics, axe and keyboard`,async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await page.setViewportSize({width,height:width<768?844:900});await setup(page);const started=Date.now();await page.goto('./');
 await expect(page.locator('article')).toHaveCount(6);expect(Date.now()-started).toBeLessThan(10000);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.addScriptTag({path:axePath});
 const accessibility=await page.evaluate(async()=>await (window as any).axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}}));
 expect(accessibility.violations).toEqual([]);
 const topic=await page.locator('.topic-button').first().boundingBox();if(width<768)expect(topic!.y+topic!.height).toBeLessThan(844);
 await capture(page,`home-${width}`);
 await page.keyboard.press('Tab');await expect(page.getByRole('link',{name:'혜택 목록으로 건너뛰기'})).toBeFocused();
 await page.keyboard.press('Enter');await expect(page.locator('#results')).toBeFocused();
 const details=page.locator('article').first().locator('.card-open');await details.focus();await page.keyboard.press('Enter');await expect(page.getByRole('dialog')).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);await expect(details).toBeFocused();
 expect(errors).toEqual([]);
});
test('search, combined filters, sort, URL reload, back and reset',async({page})=>{
 await setup(page);await page.goto('./');
 await page.getByLabel('혜택·조건·지역·기관 검색').fill('문화 회원');
 await page.getByLabel('지역',{exact:true}).selectOption('강서구');

 await page.getByLabel('혜택 정렬').selectOption('verified');
 await expect(page.locator('article')).toHaveCount(2);
 await expect(page).toHaveURL(/q=/);await page.reload();await expect(page.locator('article')).toHaveCount(2);
 await expect(page.getByLabel('혜택 정렬')).toHaveValue('verified');
 await page.getByLabel('혜택 정렬').selectOption('title');await page.goBack();await expect(page.getByLabel('혜택 정렬')).toHaveValue('verified');
 await page.getByRole('button',{name:'필터 초기화',exact:true}).first().click();await expect(page.locator('article')).toHaveCount(6);
 await page.getByRole('button',{name:/마감 임박/}).click();await expect(page.locator('article')).toHaveCount(4);
});
test('official links and complete detail conditions',async({page})=>{
 await setup(page);await page.goto('./');
 const card=page.locator('article').filter({hasText:'[테스트] 결제 시 할인 안내'});
 await card.locator('.card-open').click();await expect(card).toContainText('테스트 충전금');
 for(const link of await card.locator('a').all()){
  await expect(link).toHaveAttribute('rel','noopener noreferrer');await expect(link).toHaveAttribute('href',/^https:\/\/mediahub.seoul.go.kr\//);
 }
 await capture(page,'details');
});
for(const [name,body,title]of [
 ['stale',snapshot(items,{valid_through:'2026-11-04T12:00:00+09:00'}),'최신 브리핑을 기다리고 있어요'],
 ['failed',snapshot(items,{status:'collection_failed'}),'이번 수집을 완료하지 못했습니다'],
 ['awaiting',snapshot(items,{status:'awaiting_verification'}),'검증된 공개 혜택을 준비하고 있어요'],
 ['expired-items',snapshot([item({display_until:'2026-11-04T12:00:00+09:00'})]),'현재 표시 가능한 검증 항목이 없어요'],
 ['unverified',snapshot([item({needs_recheck:true})]),'현재 표시 가능한 검증 항목이 없어요'],
 ['invalid',snapshot(items,{schema_version:99}),'공개 데이터 확인이 필요합니다'],
 ['null-json',null,'공개 데이터 확인이 필요합니다'],
] as const)test(`state ${name}`,async({page})=>{
 await setup(page,body);await page.setViewportSize({width:390,height:844});await page.goto('./');
 await expect(page.locator('article')).toHaveCount(0);
 await expect(page.getByText(name==='stale'?'최신 브리핑을 기다리고 있어요':title,{exact:true})).toBeVisible();
 await capture(page,`state-${name}`);
});
test('empty search, filter reset and partial collection warning',async({page})=>{
 await setup(page);await page.goto('./');await expect(page.getByText(/수집 실패 1곳/)).toBeVisible();
 await page.getByLabel('혜택·조건·지역·기관 검색').fill('존재하지않는검색어');
 await expect(page.locator('article')).toHaveCount(0);await expect(page.getByText('조건에 맞는 검증 항목이 없어요')).toBeVisible();await capture(page,'state-no-results');
 await page.getByRole('button',{name:'필터 초기화',exact:true}).last().click();await expect(page.locator('article')).toHaveCount(6);
});
test('network failure and retry',async({page})=>{
 await setup(page);await page.route('**/briefing.json',route=>route.abort());await page.goto('./');
 await expect(page.getByText('공개 데이터를 불러오지 못했습니다',{exact:true})).toBeVisible();await capture(page,'state-network-error');
 await page.unroute('**/briefing.json');await page.getByRole('button',{name:'다시 불러오기'}).click();await expect(page.locator('article')).toHaveCount(6);
});
test('open tab removes individual and file-expired cards without navigation',async({page})=>{
 await setup(page,snapshot([item({display_until:'2026-11-04T12:00:03+09:00'})]));await page.goto('./');await expect(page.locator('article')).toHaveCount(1);
 await page.clock.fastForward(4000);await expect(page.locator('article')).toHaveCount(0);
});
test('no JavaScript exposes dated text alternative',async({browser})=>{
 const context=await browser.newContext({javaScriptEnabled:false});const page=await context.newPage();await page.goto(String(test.info().project.use.baseURL));
 await expect(page.getByRole('link',{name:'텍스트 브리핑'})).toBeVisible();await context.close();
});
test('open tab gates the whole file when valid_through passes',async({page})=>{
 await setup(page,snapshot(items,{valid_through:'2026-11-04T12:00:03+09:00'}));await page.goto('./');await expect(page.locator('article')).toHaveCount(6);
 await page.clock.fastForward(4000);await expect(page.locator('article')).toHaveCount(0);await expect(page.getByText('최신 브리핑을 기다리고 있어요',{exact:true})).toBeVisible();
});
test('remembered interests persist locally, shared URLs win, and stored defaults can be deleted',async({page})=>{
 await setup(page);await page.goto('./');
 await page.getByLabel('지역',{exact:true}).selectOption('강서구');
 await page.locator('.interest-settings summary').click();await page.getByRole('button',{name:'현재 지역 저장'}).click();
 await expect(page.getByText('이 브라우저에 지역을 저장했습니다.',{exact:true})).toBeVisible();
 await page.goto('./');await expect(page.getByLabel('지역',{exact:true})).toHaveValue('강서구');await expect(page.locator('article')).toHaveCount(2);
 await expect(page).toHaveURL(/region=/);
 await page.goto('./?q=생활지원');await expect(page.getByLabel('지역',{exact:true})).toHaveValue('');await expect(page.locator('article')).toHaveCount(1);
 await page.locator('.interest-settings summary').click();await page.getByRole('button',{name:'저장값 삭제'}).click();
 await expect(page.getByText('저장값을 삭제했습니다. 현재 검색 필터는 유지됩니다.',{exact:true})).toBeVisible();
 await page.goto('./');await expect(page.getByLabel('지역',{exact:true})).toHaveValue('');await expect(page.locator('article')).toHaveCount(6);
});
test('blocked localStorage preserves discovery and announces save failure',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(window,'localStorage',{configurable:true,get(){throw new DOMException('Blocked','SecurityError');}}));
 await setup(page);await page.goto('./');await expect(page.locator('article')).toHaveCount(6);
 await page.locator('.interest-settings summary').click();await page.getByRole('button',{name:'현재 지역 저장'}).click();
 await expect(page.getByText('저장하지 못했습니다.',{exact:false})).toBeVisible();await expect(page.locator('article')).toHaveCount(6);
});

test('corrupt stored preferences can still be explicitly deleted',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('benefit-monitor:interests:v1','broken'));
 await setup(page);await page.goto('./');await expect(page.locator('article')).toHaveCount(6);
 await page.locator('.interest-settings summary').click();await expect(page.getByText('저장한 관심 설정이 없습니다.',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'저장값 삭제'}).click();
 expect(await page.evaluate(()=>localStorage.getItem('benefit-monitor:interests:v1'))).toBeNull();
});
test('favorites persist, remain filterable and return focus after removal',async({page})=>{
 await setup(page);await page.goto('./');const card=page.locator('article').filter({has:page.getByRole('heading',{name:'[테스트] 문화 체험 안내',exact:true})});
 await card.getByRole('button',{name:'[테스트] 문화 체험 안내 즐겨찾기',exact:true}).click();
 await expect(card.getByRole('button',{name:'[테스트] 문화 체험 안내 즐겨찾기',exact:true})).toHaveAttribute('aria-pressed','true');
 await page.reload();await page.getByRole('button',{name:/즐겨찾기만 보기/}).click();await expect(page.locator('article')).toHaveCount(1);
 await page.getByRole('button',{name:'[테스트] 문화 체험 안내 즐겨찾기',exact:true}).click();await expect(page.locator('article')).toHaveCount(0);await expect(page.locator('#results')).toBeFocused();
 await page.getByRole('button',{name:'필터 초기화',exact:true}).last().click();await expect(page.locator('article')).toHaveCount(6);
});
test('saved items disappear when their display cutoff expires',async({page})=>{
 await setup(page,snapshot([item({display_until:'2026-11-04T12:00:03+09:00'})]));await page.goto('./');
 await page.getByRole('button',{name:'[테스트] 문화 체험 안내 즐겨찾기',exact:true}).click();await page.getByRole('button',{name:/즐겨찾기만 보기/}).click();await expect(page.locator('article')).toHaveCount(1);
 await page.clock.fastForward(4000);await expect(page.locator('article')).toHaveCount(0);await expect(page.getByText(/현재 유효성을 확인할 수 없는 저장 항목 1건/)).toBeVisible();
});
test('blocked favorite storage never shows a false saved state',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(window,'localStorage',{configurable:true,get(){throw new DOMException('Blocked','SecurityError');}}));
 await setup(page);await page.goto('./');const button=page.getByRole('button',{name:'[테스트] 문화 체험 안내 즐겨찾기',exact:true});await button.click();
 await expect(button).toHaveAttribute('aria-pressed','false');await expect(page.getByText('저장하지 못했습니다. 최대 200개 한도와 브라우저 저장소 설정을 확인하세요.',{exact:true})).toBeVisible();
});
test('sharing flushes pending search and copies only current search filters',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async(value:string)=>{(window as any).__copiedSearch=value;}}}));
 await setup(page);await page.goto('./?tracking=private#results');await page.getByLabel('혜택·조건·지역·기관 검색').fill('문화 회원');await page.getByRole('button',{name:'검색 조건 공유'}).click();
 await expect(page.getByText('검색 조건 링크를 복사했습니다. 즐겨찾기는 공유되지 않습니다.',{exact:true})).toBeVisible();
 const copied=await page.evaluate(()=>(window as any).__copiedSearch);const url=new URL(copied);expect(url.searchParams.get('q')).toBe('문화 회원');expect(url.searchParams.has('tracking')).toBe(false);expect(url.searchParams.get('sort')).toBe('deadline');expect(url.hash).toBe('');
});
test('clipboard denial leaves a selectable read-only share link',async({page})=>{
 await page.addInitScript(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new DOMException('Denied','NotAllowedError');}}}));
 await setup(page);await page.goto('./');await page.getByRole('button',{name:'검색 조건 공유'}).click();
 await expect(page.getByText('자동 복사를 사용할 수 없습니다. 아래 링크를 선택해 직접 복사하세요.',{exact:true})).toBeVisible();
 const link=page.getByLabel('공유할 검색 링크');await expect(link).toHaveAttribute('readonly','');await link.focus();expect(await link.evaluate((input:HTMLInputElement)=>input.selectionEnd!-input.selectionStart!)).toBe((await link.inputValue()).length);
});
test('all favorites can be cleared even when the stored record is corrupt',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('benefit-monitor:favorites:v1','broken'));await setup(page);await page.goto('./');
 await page.locator('.interest-settings summary').click();await page.getByRole('button',{name:'즐겨찾기 모두 해제'}).click();
 expect(await page.evaluate(()=>localStorage.getItem('benefit-monitor:favorites:v1'))).toBeNull();await expect(page.locator('article')).toHaveCount(6);
});
const reviewedValue={kind:'discount_rate',value:10,qualifier:'up_to',conditions:'[테스트] 최소 결제와 지정 재원 조건을 확인하세요. <img src=x onerror=alert(1)>',evidence_url:'https://mediahub.seoul.go.kr/archives/1',evidence_quote:'최대 10% 할인'};
test('reviewed numerical benefit shows its qualifier, conditions and safely escaped conditions',async({page})=>{
 await page.setViewportSize({width:390,height:844});await setup(page,snapshot([item({benefit_value:reviewedValue})]));await page.goto('./');
 const card=page.locator('article');await expect(card.locator('.benefit-highlight')).toHaveCount(0);await expect(card).toContainText('유료');
 await card.locator('.card-open').click();await expect(card.locator('.value-evidence')).toContainText(reviewedValue.conditions);await expect(card.locator('.value-evidence')).toContainText('<img src=x onerror=alert(1)>');await expect(card.locator('img')).toHaveCount(0);
 const link=card.getByRole('link',{name:'금액 근거 원문 (새 창)',exact:true});await expect(link).toHaveAttribute('href',reviewedValue.evidence_url);await expect(link).toHaveAttribute('rel','noopener noreferrer');
 await page.addScriptTag({path:axePath});const a11y=await page.evaluate(async()=>await (window as any).axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21aa','wcag22aa']}}));expect(a11y.violations).toEqual([]);
 await capture(page,'benefit-value-details');
});
test('invalid or contradictory numerical benefits withhold their card',async({page})=>{
 await setup(page,snapshot([item({benefit_value:{...reviewedValue,value:1000}})]));await page.goto('./');
 await expect(page.getByText('현재 표시 가능한 검증 항목이 없어요',{exact:true})).toBeVisible();await expect(page.locator('article')).toHaveCount(0);await expect(page.locator('.benefit-highlight')).toHaveCount(0);
});
test('numerical highlight disappears with item validity rather than surviving as a saved snapshot',async({page})=>{
 await setup(page,snapshot([item({benefit_value:reviewedValue,display_until:'2026-11-04T12:00:03+09:00'})]));await page.goto('./');
 await page.getByRole('button',{name:'[테스트] 문화 체험 안내 즐겨찾기',exact:true}).click();await page.locator('.card-open').click();await expect(page.locator('.value-evidence strong')).toHaveText('최대 10% 할인');
 await page.clock.fastForward(4000);await expect(page.locator('article')).toHaveCount(0);await expect(page.getByRole('dialog')).toHaveCount(0);expect(await page.evaluate(()=>document.body.style.overflow)).not.toBe('hidden');
});

test('compact header and Seoul-only filters ignore legacy hidden categories',async({page})=>{
 await setup(page);await page.goto('./?region=서울%206개%20야간%20상권&category=문화·체험');
 await expect(page.locator('#region option')).toHaveCount(26);
 await expect(page.locator('#region option').first()).toHaveText('서울시 전체');
 await expect(page.locator('#category')).toHaveCount(0);
 await expect(page.locator('article')).toHaveCount(6);
 await expect(page.locator('header .overview')).toContainText('공개 혜택');
 await expect(page).not.toHaveURL(/category=/);
});

test('card dialog hides conditions until opened and supports close and browser back',async({page})=>{
 await setup(page);await page.goto('./');const card=page.locator('article').first();
 await expect(card.locator('.full-conditions')).not.toBeVisible();await expect(card.locator('.card-conditions')).toHaveCount(0);
 await card.locator('.card-open').click();await expect(page.getByRole('dialog')).toBeVisible();await expect(card.locator('.full-conditions')).toBeVisible();
 await page.getByRole('button',{name:'상세 조건 닫기'}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
 await expect.poll(()=>page.evaluate(()=>history.state?.benefitDialog)).toBeFalsy();
 await card.locator('.card-open').click();await page.goBack();await expect(page.getByRole('dialog')).toHaveCount(0);
 expect(await page.evaluate(()=>document.body.style.overflow)).not.toBe('hidden');
});
