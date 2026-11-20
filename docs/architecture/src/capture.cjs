// Usage: node capture.cjs <playwright module dir> <out dir>
const path = require('path');
const { chromium } = require(process.argv[2]);
const out = process.argv[3];

(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  // 1) pipeline animation
  const page = await browser.newPage({ viewport: { width: 960, height: 540 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'pipeline.html'));
  const count = await page.evaluate(() => window.STEP_COUNT);
  for (let i = 0; i < count; i++) {
    await page.evaluate((n) => window.setStep(n), i);
    await page.screenshot({ path: path.join(out, 'pipe', `f${String(i).padStart(2, '0')}.png`) });
  }
  await page.close();

  // 2) live site tabs at phone width
  const site = await browser.newPage({ viewport: { width: 390, height: 760 }, deviceScaleFactor: 1, locale: 'ko-KR' });
  await site.goto('https://kim-taesu.github.io/benefit-monitor/', { waitUntil: 'networkidle' });
  await site.waitForTimeout(1500);
  await site.screenshot({ path: path.join(out, 'site', 'a00.png') });
  const close = site.getByRole('button', { name: '닫기' });
  if (await close.count()) { await close.first().click(); await site.waitForTimeout(400); }
  const tabs = ['benefits', 'subscriptions', 'groceries', 'festivals', 'health'];
  let n = 0;
  const shot = async () => site.screenshot({ path: path.join(out, 'site', `f${String(n++).padStart(2, '0')}.png`) });
  for (const id of tabs) {
    await site.click('#tab-' + id);
    await site.waitForTimeout(900);
    await site.evaluate(() => window.scrollTo(0, 0));
    await shot();
    await site.evaluate(() => window.scrollBy(0, 420));
    await site.waitForTimeout(400);
    await shot();
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
