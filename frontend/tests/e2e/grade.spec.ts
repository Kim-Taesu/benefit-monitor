import {test,expect} from '@playwright/test';
import {item,snapshot,NOW} from '../fixtures';

test('failing sources warn on the card and the trust grade is explained in the detail sheet',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 const items=[item({valid_until:'2026-11-20',deadline_at:null,display_until:'2026-11-20T00:00:00+09:00'}),
  item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'[테스트] 상시 안내',validity_kind:'ongoing',valid_until:null,deadline_at:null,display_until:'2026-11-20T00:00:00+09:00'}),
  item({source:'seven',url:'https://www.7-eleven.co.kr/product/cardInfo.asp?gbn=2',summary:'[테스트] 편의점 카드',valid_until:'2026-11-20',deadline_at:null,display_until:'2026-11-20T00:00:00+09:00',districts:[]})];
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(items,{source_health:{seven:{consecutive_failures:15}}})}));
 await page.goto('./');
 // 카드에는 재확인이 필요한 항목만 경고를 붙이고, 등급과 설명은 상세 안에 둔다.
 await expect(page.locator('#results .recheck')).toHaveCount(1);
 const failing=page.locator('#results article',{hasText:'편의점 카드'});
 await expect(failing.locator('.recheck')).toHaveText('⚠️ 재확인 필요');
 await failing.locator('.card-open').click();
 const sheet=failing.getByRole('dialog');
 await expect(sheet.locator('.sheet-trust .grade-badge').first()).toHaveText('신뢰도 C');
 await expect(sheet.locator('.sheet-trust')).toContainText('15회 연속 실패');
 await sheet.getByText('신뢰도 등급이란?',{exact:true}).click();
 await expect(sheet.locator('.grade-list dt')).toHaveText([/A\s*기간까지 확인됨/,/B\s*확인됨 · 기간 미정/,/C\s*재확인 필요/]);
 await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);
 const ongoing=page.locator('#results article').filter({has:page.getByRole('heading',{name:'[테스트] 상시 안내',exact:true})});
 await ongoing.locator('.card-open').click();
 await expect(ongoing.getByRole('dialog').locator('.sheet-trust .grade-badge').first()).toHaveText('신뢰도 B');
});
