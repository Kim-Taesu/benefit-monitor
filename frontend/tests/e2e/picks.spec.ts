import {test,expect} from '@playwright/test';
import {snapshot,item,NOW} from '../fixtures';
import {FESTIVAL_DETAIL} from '../../src/festivals';

const SHOTS='../.superpowers/sdd/2026-11-14-tab-ai-picks-plan/shots';
const fid=(n:number)=>`00000000-0000-4000-8000-00000000000${n}`;
function festival(n:number,over:Record<string,unknown>={}){
 return {id:fid(n),name:`[테스트] 축제 ${n}`,start:'2026-11-07',end:'2026-11-08',region:'경상북도 구미시',place:'역 앞',organizer:'[테스트] 시청',
  fee_status:'free',fee_text:'무료',discount:'',summary:'[테스트] 소개',programs:'[테스트] 공연',homepage:'',culture_tourism:false,url:FESTIVAL_DETAIL+fid(n),modified:null,...over};
}
const festivals={schema_version:1,source:'kfes',fetched_at:'2026-11-04T06:00:00+09:00',notice:'[테스트] 관광공사 게시 정보',items:[festival(1),festival(2,{start:'2026-11-07',end:'2026-11-07',fee_status:'paid',fee_text:'유료'})]};
const festivalPick={schema_version:1,generated_at:'2026-11-04T07:00:00+09:00',day:'2026-11-04',source:'ai',summary:'[테스트] 이번 주말은 두 축제를 둘러보세요.',
 picks:[{id:fid(1),line:'공연이 볼 만해요'},{id:fid(2),line:null}]};

const urls=Array.from({length:7},(_,n)=>`https://mediahub.seoul.go.kr/archives/${n+1}`);
const items=urls.map((url,n)=>item({url,title:`[테스트] 혜택 ${n+1}`,summary:`[테스트] 혜택 ${n+1}`,fee_status:['free','paid','mixed','unknown'][n%4]}));
const benefitPick=(over:Record<string,unknown>={})=>({schema_version:1,generated_at:'2026-11-04T07:00:00+09:00',day:'2026-11-04',source:'ai',summary:'[테스트] 마감이 가까운 혜택을 골랐어요.',
 picks:urls.map((url,n)=>({id:'b'+n,source:'seoul',url,line:n%2?null:'살펴볼 만해요'})),...over});

async function open(page:any,width:number,extra:Record<string,unknown>){
 await page.setViewportSize({width,height:900});
 await page.clock.install({time:new Date(NOW)});
 await page.route('**/briefing.json',(route:any)=>route.fulfill({json:snapshot(items,{festivals,...extra})}));
 await page.goto('./');
}
async function noOverflow(page:any){
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);
}

for(const width of [390,1440])test(`festival picks sit on their cards and the AI summary leads the list ${width}`,async({page})=>{
 await open(page,width,{festival_pick:festivalPick});
 await page.getByRole('tab',{name:'축제'}).click();
 const lead=page.locator('#festivals .festival-pick');
 await expect(lead.locator('.badge')).toHaveText('🤖 AI 작성');
 await expect(lead.locator('.pick-summary')).toHaveText('[테스트] 이번 주말은 두 축제를 둘러보세요.');
 await expect(lead).toContainText('AI가 공개 정보 안에서 쓴 문장이에요.');
 const [c,f]=await Promise.all([lead.boundingBox(),page.locator('.festival-filters').boundingBox()]);
 expect(c!.y).toBeGreaterThan(f!.y);
 expect(c!.y).toBeLessThan((await page.locator('#festivals .card-grid').boundingBox())!.y);
 // 모델 문장이 있는 줄만 "AI 작성", 문장 없이 고른 줄은 "자동 선정". 날짜·지역·요금은 공개 데이터 그대로다.
 const first=page.locator('#festivals article',{hasText:'[테스트] 축제 1'});
 await expect(first.locator('.pick-badge')).toHaveText('AI 작성');await expect(first.locator('.pick-line')).toHaveText('공연이 볼 만해요');
 await expect(first.locator('.bcard-facts')).toHaveText(/경상북도 구미시 · 무료$/);
 await expect(first.getByRole('link',{name:/대한민국 구석구석 안내/})).toHaveAttribute('href',FESTIVAL_DETAIL+fid(1));
 const second=page.locator('#festivals article',{hasText:'[테스트] 축제 2'});
 await expect(second.locator('.pick-badge')).toHaveText('자동 선정');await expect(second.locator('.pick-line')).toHaveCount(0);
 await expect(second.locator('.bcard-facts')).toHaveText(/유료$/);
 // 추천 칩은 고른 축제만 보일 뿐 요금으로 거르거나 순서를 바꾸지 않는다.
 const chip=page.getByRole('button',{name:/이번 주말 추천/});
 expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(44);
 await chip.click();await expect(page.locator('#festivals article h3')).toHaveText(['[테스트] 축제 1','[테스트] 축제 2']);
 await expect(page.locator('#festivals').getByRole('button',{name:'무료'})).toHaveCount(0);
 await noOverflow(page);
 if(width===390)await page.screenshot({path:`${SHOTS}/festival-390.png`,fullPage:false});
});

test('festival rule pick shows the auto badge and no summary',async({page})=>{
 await open(page,390,{festival_pick:{...festivalPick,source:'rule',summary:null,picks:festivalPick.picks.map(p=>({...p,line:null}))}});
 await page.getByRole('tab',{name:'축제'}).click();
 await expect(page.locator('#festivals .festival-pick')).toHaveCount(0);
 await expect(page.locator('#festivals .pick-badge')).toHaveText(['자동 선정','자동 선정']);
 await expect(page.locator('#festivals .pick-line')).toHaveCount(0);await expect(page.locator('#festivals .badge.ai')).toHaveCount(0);
 await expect(page.locator('#festivals .festival-pick-note')).toHaveText('추천 표시는 수도권 먼저, 가까운 날짜 순으로 자동 선정했어요.');
});

for(const width of [390,1440])test(`benefit picks sit on their cards and the AI summary leads the list ${width}`,async({page})=>{
 await open(page,width,{benefit_pick:benefitPick()});
 const lead=page.locator('.benefit-pick');
 await expect(lead.locator('.badge')).toHaveText('🤖 AI 작성');
 await expect(lead.locator('.pick-summary')).toHaveText('[테스트] 마감이 가까운 혜택을 골랐어요.');
 await expect(lead.locator('.fine-print')).toHaveCount(1);
 const [c,d,r]=await Promise.all([lead.boundingBox(),page.locator('.tools').first().boundingBox(),page.locator('#results').boundingBox()]);
 expect(c!.y).toBeGreaterThan(d!.y);expect(c!.y).toBeLessThan(r!.y);
 // 모델 문장이 있는 줄만 "AI 작성", 문장 없이 고른 줄은 "자동 선정"이고 공식 조건 첫 문장을 그대로 보인다.
 const first=page.locator('#results article',{hasText:'[테스트] 혜택 1'}).first();
 await expect(first.locator('.pick-badge')).toHaveText('AI 작성');
 await expect(first.locator('.pick-line')).toHaveText('살펴볼 만해요');
 await expect(first.locator('.bcard-facts')).toContainText('무료');await expect(first.locator('.timing')).toHaveText('신청 마감 2일 남음');
 const second=page.locator('#results article',{hasText:'[테스트] 혜택 2'}).first();
 await expect(second.locator('.pick-badge')).toHaveText('자동 선정');await expect(second.locator('.pick-line')).toHaveCount(0);
 await expect(second.locator('.bcard-facts')).toContainText('유료');
 const chip=page.getByRole('button',{name:/이번 주 추천/});
 await expect(chip).toContainText('7');expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(44);
 await chip.click();await expect(page.locator('#results article')).toHaveCount(7);await expect(lead).toHaveCount(0);
 await noOverflow(page);
 if(width===390)await page.screenshot({path:`${SHOTS}/benefit-390.png`,fullPage:false});
});
test('a rule pick shows 자동 선정 on cards and no model sentence anywhere',async({page})=>{
 await open(page,390,{benefit_pick:benefitPick({source:'rule',summary:null,picks:urls.slice(0,5).map((url,n)=>({id:'b'+n,source:'seoul',url,line:null}))})});
 await expect(page.locator('.benefit-pick')).toHaveCount(0);
 await expect(page.locator('#results .pick-badge')).toHaveText(Array(5).fill('자동 선정'));
 await expect(page.locator('#results .pick-line')).toHaveCount(0);await expect(page.locator('#results .badge.ai')).toHaveCount(0);
});

test('no card without a pick, and an invalid pick is ignored',async({page})=>{
 await open(page,390,{});
 await expect(page.locator('.benefit-pick')).toHaveCount(0);await expect(page.locator('#results .pick-badge')).toHaveCount(0);await expect(page.getByRole('button',{name:/이번 주 추천/})).toHaveCount(0);
 await page.getByRole('tab',{name:'축제'}).click();
 await expect(page.locator('#festivals .festival-pick')).toHaveCount(0);await expect(page.locator('#festivals .pick-badge')).toHaveCount(0);
 await page.unroute('**/briefing.json');
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(items,{festivals,festival_pick:{...festivalPick,schema_version:2},benefit_pick:benefitPick({summary:'<b>x</b>'})})}));
 await page.reload();
 await expect(page.locator('.benefit-pick')).toHaveCount(0);await expect(page.locator('#results .pick-badge')).toHaveCount(0);
 await page.getByRole('tab',{name:'축제'}).click();
 await expect(page.locator('#festivals .festival-pick')).toHaveCount(0);await expect(page.locator('#festivals .pick-badge')).toHaveCount(0);
});
