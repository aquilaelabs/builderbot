// The README's pictures, from a dashboard that is already running (the dev
// instance is the usual one: a lived-in BuilderBot with real nodes, which a
// staged copy could only imitate):
//
//     NODE_PATH="$(bb capture shot --print-node-path)" \
//     README_SHOT_URL=http://HOST:PORT README_SHOT_AUTH=user:password \
//         node tools/readme-shots.mjs docs/screenshots
//
// The address and the credential come from the environment and are never
// written here. What keeps a real instance out of the repository: the
// default scheme is set for the shot only, every mail address and IPv4
// address on the page is rewritten to an example one and the shot is
// refused while another is still there, the terminal is cleared before it
// is photographed, and nothing of the account's is saved (its layout,
// cards and presence are not posted).
//
// A lived-in instance carries more than a picture should: the page's copy
// of the status poll is trimmed on its way in, never the instance itself.
// README_SHOT_PROJECTS (comma-separated) names the projects the Projects
// card shows, all of them when unset; the account's tab strip is cut to its
// one workspace shell, so the account's own layout is untouched and no new
// terminal is left running. README_SHOT_PROJECT names the project the
// notebook picture opens (the first one shown otherwise), README_SHOT_VIEW
// the view it opens on (roadmap otherwise).
import { createRequire } from 'node:module';
// require, not import: ESM resolution ignores NODE_PATH (test/lib.mjs).
const { chromium } = createRequire(import.meta.url)('playwright');
const BASE = process.env.README_SHOT_URL, [USER, PASS] = (process.env.README_SHOT_AUTH || ':').split(':');
const OUT = process.argv[2];
const SHOW = process.env.README_SHOT_PROJECTS ? process.env.README_SHOT_PROJECTS.split(',').map(x => x.trim()) : null;
if (!BASE || !USER || !OUT){
  console.error('usage: README_SHOT_URL=... README_SHOT_AUTH=user:password node tools/readme-shots.mjs DIR');
  process.exit(2);
}
const browser = await chromium.launch();
const scrub = page => page.evaluate(() => {
  const mail = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/g;
  // Every IPv4 address becomes one of the documentation range (RFC 5737),
  // the same real address always the same example one, so a page that names
  // one machine twice still does.
  const ip = /\b(?:\d{1,3}\.){3}\d{1,3}\b/g, seen = new Map();
  const fake = a => a.startsWith('192.0.2.') || a === '127.0.0.1' ? a
    : (seen.has(a) || seen.set(a, `192.0.2.${10 + seen.size}`), seen.get(a));
  const clean = s => s.replace(mail, 'you@example.com').replace(ip, fake);
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = w.nextNode(); n; n = w.nextNode()){ const c = clean(n.nodeValue); if (c !== n.nodeValue) n.nodeValue = c; }
  document.querySelectorAll('[title]').forEach(e => { e.title = clean(e.title); });
  document.querySelectorAll('input, textarea').forEach(e => { e.value = clean(e.value); });
  const text = document.body.innerText;
  return [...(text.match(mail) || []).filter(a => a !== 'you@example.com'),
          ...(text.match(ip) || []).filter(a => !a.startsWith('192.0.2.') && a !== '127.0.0.1')];
});
const open = async (opts, view) => {
  const ctx = await browser.newContext(opts);
  // Marked as this account's own choice, or the page adopts the account's
  // saved scheme over it (adoptTheme, B491).
  await ctx.addInitScript(who => { try { localStorage.setItem('bb.theme', 'default'); localStorage.setItem('bb.theme.who', who); } catch (e) {} }, USER);
  const page = await ctx.newPage();
  // Nothing of the account's is changed by taking its picture.
  await page.route(/\/api\/(layout|cards|users|presence)(\?|$)/, r => r.request().method() === 'POST' ? r.abort() : r.continue());
  await page.route(/\/api\/status(\?|$)/, async r => {
    const res = await r.fetch(), j = await res.json();
    if (SHOW) j.projects = (j.projects || []).filter(p => SHOW.includes(p.name));
    const sh = (j.layout?.tabs || []).find(t => t.kind === 'term' && /^sh:\d+:$/.test(t.arg));
    if (j.layout) j.layout = { ...j.layout, tabs: sh ? [sh] : [], panes: [sh ? sh.id : null, null], active: 0 };
    await r.fulfill({ response: res, json: j });
  });
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
  const t = await page.$('.tab:has-text("sh: ")');
  if (t && await t.isVisible()) await t.click();
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
// A document tab opened in the left pane, given time for its first fetch.
const tab = async (page, open, settle = 4000) => {
  await page.evaluate(open);
  await page.waitForTimeout(settle);
};
const shoot = async (page, file) => {
  const left = await scrub(page);
  if (left.length) throw new Error('an address is still on the page: ' + left.join(', '));
  await page.screenshot({ path: `${OUT}/${file}` });
  console.log(file, 'theme:', await page.evaluate(() => document.documentElement.dataset.theme || '(default)'), 'addresses left: 0');
};
const desk = { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 };
{ const { ctx, page } = await open({ viewport: { width: 1440, height: 1180 }, deviceScaleFactor: 1 });
  await shell(page, 'git -C /workspace/hello log --oneline --no-decorate -5 && ls /workspace/hello'); await shoot(page, 'dashboard.png'); await ctx.close(); }
{ const { ctx, page } = await open(desk);
  const name = process.env.README_SHOT_PROJECT || await page.evaluate(() => (state.projects || [])[0]?.name);
  await tab(page, `openNotebook(${JSON.stringify(name)}, ${JSON.stringify(process.env.README_SHOT_VIEW || "roadmap")})`); await shoot(page, 'notebook.png'); await ctx.close(); }
{ const { ctx, page } = await open(desk);
  await tab(page, 'openNodesTab()', 6000); await shoot(page, 'nodes.png'); await ctx.close(); }
{ const { ctx, page } = await open(desk);
  await tab(page, 'openToolchains()', 6000); await shoot(page, 'toolchains.png'); await ctx.close(); }
{ const { ctx, page } = await open({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true }, 'dash');
  await page.waitForTimeout(1200); await shoot(page, 'phone-dashboard.png'); await ctx.close(); }
{ const { ctx, page } = await open({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true }, 'terminal');
  await shell(page, 'ls /workspace/droid', true); await shoot(page, 'phone-terminal.png'); await ctx.close(); }
await browser.close();
