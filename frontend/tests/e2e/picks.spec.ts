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

for(const width of [390,1440])test(`festival pick card sits above the filters ${width}`,async({page})=>{
 await open(page,width,{festival_pick:festivalPick});
 await page.getByRole('tab',{name:'축제'}).click();
 const card=page.locator('#festivals .grocery-pick');
 await expect(card.locator('h3')).toHaveText('이번 주말 나들이 추천');
 await expect(card.locator('.grocery-badge').first()).toHaveText('AI 작성');
 await expect(card).toContainText('[테스트] 이번 주말은 두 축제를 둘러보세요.');
 await expect(card.locator('li')).toHaveText([/\[테스트\] 축제 1 \(11\/7~11\/8 · 경상북도 구미시\).*무료.*→ 공연이 볼 만해요/,/\[테스트\] 축제 2 \(11\/7 · 경상북도 구미시\).*유료/]);
 await expect(card.locator('li').nth(1)).not.toContainText('→');
 await expect(card).toContainText('AI가 공개 정보 안에서 쓴 문장이에요.');
 const [c,f]=await Promise.all([card.boundingBox(),page.locator('.festival-filters').boundingBox()]);
 expect(c!.y).toBeLessThan(f!.y);
 await noOverflow(page);
 if(width===390)await page.screenshot({path:`${SHOTS}/festival-390.png`,fullPage:false});
});

test('festival rule pick shows the auto badge and no summary',async({page})=>{
 await open(page,390,{festival_pick:{...festivalPick,source:'rule',summary:null,picks:festivalPick.picks.map(p=>({...p,line:null}))}});
 await page.getByRole('tab',{name:'축제'}).click();
 const card=page.locator('#festivals .grocery-pick');
 await expect(card.locator('.grocery-badge').first()).toHaveText('자동 선정');
 await expect(card.locator('.grocery-pick-summary')).toHaveCount(0);
 await expect(card.locator('.fine-print')).toHaveText('수도권 먼저, 가까운 날짜 순으로 자동 선정했어요.');
});

for(const width of [390,1440])test(`benefit pick card shows 5 lines then the rest ${width}`,async({page})=>{
 await open(page,width,{benefit_pick:benefitPick()});
 const card=page.locator('.benefit-pick');
 await expect(card.locator('h3')).toHaveText('이번 주 놓치면 아쉬운 혜택');
 await expect(card.locator('.grocery-badge').first()).toHaveText('AI 작성');
 await expect(card.locator('li')).toHaveCount(5);
 const first=card.locator('li').first();
 await expect(first.locator('a')).toHaveAttribute('target','_blank');
 await expect(first.locator('a')).toHaveAttribute('rel','noopener noreferrer');
 await expect(first).toContainText('~11/6');
 await expect(first).toContainText('무료');
 await expect(card.locator('li').nth(1)).toContainText('유료·구매 필요');
 await expect(first).toContainText('→ 살펴볼 만해요');
 const more=card.getByRole('button',{name:'더 보기 (2개 남음)'});
 expect((await more.boundingBox())!.height).toBeGreaterThanOrEqual(44);
 const [c,b]=await Promise.all([card.boundingBox(),page.locator('.beta-panel, #topics, [aria-label*="주제"]').first().boundingBox().catch(()=>null)]);
 if(b)expect(c!.y).toBeLessThan(b.y);
 await noOverflow(page);
 if(width===390)await page.screenshot({path:`${SHOTS}/benefit-390.png`,fullPage:false});
 await more.click();
 await expect(card.locator('li')).toHaveCount(7);
 await expect(more).toHaveCount(0);
 await noOverflow(page);
});

test('no card without a pick, and an invalid pick is ignored',async({page})=>{
 await open(page,390,{});
 await expect(page.locator('.benefit-pick')).toHaveCount(0);
 await page.getByRole('tab',{name:'축제'}).click();
 await expect(page.locator('#festivals .grocery-pick')).toHaveCount(0);
 await page.unroute('**/briefing.json');
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(items,{festivals,festival_pick:{...festivalPick,schema_version:2},benefit_pick:benefitPick({summary:'<b>x</b>'})})}));
 await page.reload();
 await expect(page.locator('.benefit-pick')).toHaveCount(0);
 await page.getByRole('tab',{name:'축제'}).click();
 await expect(page.locator('#festivals .grocery-pick')).toHaveCount(0);
});
