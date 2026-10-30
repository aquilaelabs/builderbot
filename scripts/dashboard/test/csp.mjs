// The page under its Content-Security-Policy (R158 step 4). Every refusal
// the browser makes is an event on the document; the suite listens from the
// first script, walks the pages and the notebook's views, and says what was
// refused, if anything, and whether a data-style element got its style.
import { URL as BASE, launch, newPage, done, ok, settled } from './lib.mjs';
const browser = await launch();
const page = await newPage(browser);
await page.addInitScript(() => {
  window.__csp = [];
  document.addEventListener('securitypolicyviolation', e => window.__csp.push(
    `${e.violatedDirective} ${e.blockedURI} ${e.sourceFile || ''}:${e.lineNumber || 0} ${(e.sample || '').slice(0, 60)}`));
});
const errs = [];
page.on('console', m => { if (m.type() === 'error') errs.push(m.text().slice(0, 160)); });
await page.goto(BASE);
await page.waitForFunction(() => typeof state !== 'undefined' && state && state.repos);
const walk = [['openHome'], ['openProjectsTab'], ['openDocker'], ['openNodesTab'], ['openSettingsTab'], ['openJobsTab'],
  ['openUsersTab'], ['openKeysTab'], ['openVmsTab'],
  ['openNotebook', 'alpha', 'roadmap'], ['openNotebook', 'alpha', 'bugs'], ['openNotebook', 'alpha', 'git'],
  ['openNotebook', 'alpha', 'design'], ['openNotebook', 'alpha', 'settings'], ['openNotebook', 'alpha', 'history']];
for (const [fn, ...args] of walk){
  await page.evaluate(([fn, args]) => { try { window[fn](...args); } catch (e) { console.error('walk ' + fn + ': ' + e.message); } }, [fn, args]);
  await settled(page);
}
const csp = await page.evaluate(() => window.__csp);
ok(csp.length === 0, `nothing the page draws is refused under its policy${csp.length ? ': ' + csp.slice(0, 6).join(' | ') : ''}`);
const styled = await page.evaluate(() => {
  const els = [...document.querySelectorAll('[data-style]')];
  return { n: els.length, bare: els.filter(e => !e.style.cssText).length };
});
ok(styled.n > 0 && styled.bare === 0, `each data-style element wears its style (${styled.n} drawn, ${styled.bare} bare)`);
ok(errs.filter(e => !/favicon|net::ERR/.test(e)).length === 0, `no console errors on the walk${errs.length ? ': ' + errs.slice(0, 4).join(' | ') : ''}`);
// The login page carries the policy too, and its own script is allowed.
const ctx2 = await browser.newContext();
const p2 = await ctx2.newPage();
await p2.addInitScript(() => { window.__csp = []; document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI)); });
const r = await p2.goto(BASE + '/login');
const h = r.headers()['content-security-policy'] || '';
ok(/script-src 'self' 'sha256-/.test(h) && !/script-src[^;]*unsafe-inline/.test(h), `the login page's policy names its own script by hash (${h.slice(0, 60)})`);
await p2.waitForTimeout(500);
ok((await p2.evaluate(() => window.__csp)).length === 0, 'the login card draws under it');
await done(browser);
