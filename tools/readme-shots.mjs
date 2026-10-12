// The README's three pictures from a dashboard that is already running,
// for when a lived-in one shows more than tools/readme-shots.sh can stage:
//
//     NODE_PATH="$(bb capture shot --print-node-path)" \
//     README_SHOT_URL=http://HOST:PORT README_SHOT_AUTH=user:password \
//         node tools/readme-shots-live.mjs docs/screenshots
//
// The address and the credential come from the environment and are never
// written here. What keeps a real instance out of the repository: the
// default scheme is set for the shot only, every address on the page is
// rewritten to an example one and the shot is refused while another is
// still there, the terminal is cleared before it is photographed, and
// nothing of the account's is saved (its layout, cards and presence are
// not posted).
import { createRequire } from 'node:module';
// require, not import: ESM resolution ignores NODE_PATH (test/lib.mjs).
const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.README_SHOT_URL, [USER, PASS] = (process.env.README_SHOT_AUTH || ':').split(':');
const OUT = process.argv[2];
if (!BASE || !USER || !OUT){
  console.error('usage: README_SHOT_URL=... README_SHOT_AUTH=user:password node tools/readme-shots-live.mjs DIR');
  process.exit(2);
}
const browser = await chromium.launch();
const scrub = page => page.evaluate(() => {
  const re = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()) if (re.test(n.nodeValue)) n.nodeValue = n.nodeValue.replace(re, 'you@example.com');
  document.querySelectorAll('[title]').forEach(e => { if (re.test(e.title)) e.title = e.title.replace(re, 'you@example.com'); });
  const left = (document.body.innerText.match(re) || []).filter(a => a !== 'you@example.com');
  return left;
});
const open = async (opts, view) => {
  const ctx = await browser.newContext(opts);
  await ctx.addInitScript(() => { try { localStorage.setItem('bb.theme', 'default'); } catch (e) {} });
  const page = await ctx.newPage();
  // Nothing of the account's is changed by taking its picture.
  await page.route(/\/api\/(layout|cards|users|presence)(\?|$)/, r => r.request().method() === 'POST' ? r.abort() : r.continue());
  await page.goto(BASE + '/login');
  await page.fill('#u', USER); await page.fill('#p', PASS);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit]')]);
  await page.waitForFunction(() => typeof state !== 'undefined' && state && !document.body.classList.contains('booting'), null, { timeout: 30000 });
  for (let i = 0; i < 3; i++){ const c = await page.$('.modal:not([hidden]) button:has-text("Close")'); if (!c) break; await c.click(); await page.waitForTimeout(300); }
  if (view) await page.evaluate(v => setView(v), view);
  return { ctx, page };
};
// The shell tab in front, its scrollback cleared and one plain command run,
// so the picture is a terminal at work and not a page of old prompts.
const shell = async (page, tidy, touch) => {
  const t = await page.$('.tab:has-text("sh: workspace")');
  if (t) await t.click();
  await page.waitForTimeout(3500);
  const pane = await page.$('.pane:not(.hidden) iframe, .pane:not(.hidden) .stack');
  const box = pane && await pane.boundingBox();
  if (box && tidy){
    if (touch) await page.touchscreen.tap(box.x + box.width / 2, box.y + box.height / 2);
    else await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.keyboard.type('clear', { delay: 20 }); await page.keyboard.press('Enter');
    await page.waitForTimeout(600);
    await page.keyboard.type(tidy, { delay: 15 }); await page.keyboard.press('Enter');
    await page.waitForTimeout(1500);
  }
};
const shoot = async (page, file) => {
  const left = await scrub(page);
  if (left.length) throw new Error('an address is still on the page: ' + left.join(', '));
  await page.screenshot({ path: `${OUT}/${file}` });
  console.log(file, 'theme:', await page.evaluate(() => document.documentElement.dataset.theme || '(default)'), 'addresses left: 0');
};
{ const { ctx, page } = await open({ viewport: { width: 1440, height: 1180 }, deviceScaleFactor: 1 });
  await shell(page, 'ls /workspace && git -C /workspace/web log --oneline -3'); await shoot(page, 'dashboard.png'); await ctx.close(); }
{ const { ctx, page } = await open({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }, 'dash');
  await page.waitForTimeout(1200); await shoot(page, 'phone-dashboard.png'); await ctx.close(); }
{ const { ctx, page } = await open({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true }, 'terminal');
  await shell(page, 'ls /workspace', true); await shoot(page, 'phone-terminal.png'); await ctx.close(); }
await browser.close();
