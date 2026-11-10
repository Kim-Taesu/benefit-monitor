import {test,expect} from '@playwright/test';
import {item,snapshot,NOW} from '../fixtures';

test('cards show a trust grade and ? opens the grade explanation',async({page})=>{
 await page.clock.install({time:new Date(NOW)});
 const items=[item({valid_until:'2026-11-20',deadline_at:null,display_until:'2026-11-20T00:00:00+09:00'}),
  item({url:'https://mediahub.seoul.go.kr/archives/2',summary:'[테스트] 상시 안내',validity_kind:'ongoing',valid_until:null,deadline_at:null,display_until:'2026-11-20T00:00:00+09:00'}),
  item({source:'seven',url:'https://www.7-eleven.co.kr/product/cardInfo.asp?gbn=2',summary:'[테스트] 편의점 카드',valid_until:'2026-11-20',deadline_at:null,display_until:'2026-11-20T00:00:00+09:00',districts:[]})];
 await page.route('**/briefing.json',route=>route.fulfill({json:snapshot(items,{source_health:{seven:{consecutive_failures:15}}})}));
 await page.goto('./');
 const grades=page.locator('#results .grade-badge');
 await expect(grades).toHaveCount(3);
 await expect(page.locator('#results article',{hasText:'상시 안내'}).locator('.grade-badge')).toHaveText('신뢰도 B');
 await expect(page.locator('#results article',{hasText:'편의점 카드'}).locator('.card-grade')).toContainText('15회 연속 실패');
 await expect(page.locator('#results article',{hasText:'편의점 카드'}).locator('.grade-badge')).toHaveText('신뢰도 C');
 await page.getByRole('button',{name:'신뢰도 등급 설명 보기'}).first().click();
 const modal=page.getByRole('dialog',{name:'신뢰도 등급이란?'});
 await expect(modal).toBeVisible();
 await expect(modal.locator('dt')).toHaveText([/A\s*기간까지 확인됨/,/B\s*확인됨 · 기간 미정/,/C\s*재확인 필요/]);
 await page.keyboard.press('Escape');
 await expect(modal).toBeHidden();
 await expect(page.getByRole('button',{name:'신뢰도 등급 설명 보기'}).first()).toBeFocused();
});
