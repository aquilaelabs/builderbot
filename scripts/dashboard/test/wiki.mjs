// The notebook's Wiki view (wiki.py, nb-wiki.js, R112): pages as rows that
// open to be read, New page at the top, Edit on a row, written through with
// no notebook foot; Export as a zip; and bb wiki for a session, under
// Claude may: Write the wiki. Pushing to a forge is wiki.py's unit tier,
// against a repository on disk: the harness has no forge.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const P = 'alpha';
const NB = `.nb:has(#memTitle:text-is("Notebook: ${P}"))`;
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, b ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify(b) } : {});
  const t = await r.text();
  try { return { status: r.status, ...JSON.parse(t) }; } catch { return { status: r.status, raw: t.length }; }
}, [path, body]);

// ---- the view, empty, then a page made from it --------------------------------
await page.evaluate(n => openNotebook(n, 'wiki'), P);
await page.waitForFunction(() => /0 pages/.test(document.querySelector('.nb #wkHint')?.textContent || ''), null, { timeout: 20000 });
ok(!(await page.$(`${NB} .nbview[data-view="wiki"] .sectbar`))
   && await page.$eval(`${NB} #wkExport`, e => e.disabled),
   'the wiki opens empty, with no Save of its own (it writes through) and Export dead until there is a page');
// alpha's fixture has push rights on github.com/owner/alpha: the head names
// where the wiki would go, and Push waits for a page.
ok(/github\.com\/owner\/alpha/.test(await page.$eval(`${NB} #wkNetState`, e => e.textContent))
   && await page.$eval(`${NB} #wkPush`, e => !e.hidden && e.disabled),
   'with push rights the head row names the forge\'s wiki, and Push waits for a page');
await page.click(`${NB} #wkNew`);
ok(await page.$eval(`${NB} #wkNewName`, e => e.value) === 'Home', 'the first New page is Home');
await page.fill(`${NB} #wkNewText`, '# Home\n\n## Welcome\n\nSee [[Build and test]] and **this**.\n\n- one\n- two\n\n## Install\n\ntext\n\n### Detail\n\nmore\n\n<script>bad()</script>');
await page.click(`${NB} #wkNewSave`);
await page.waitForSelector(`${NB} .wkarticle[data-name="Home"] .wkpage`, { timeout: 15000 });
const html = await page.$eval(`${NB} .wkarticle[data-name="Home"] .wkpage`, e => e.innerHTML);
ok(/<h3 id="wk-welcome">Welcome<\/h3>/.test(html) && /<strong>this<\/strong>/.test(html) && /<li>one<\/li>/.test(html)
   && /class="wklink" data-page="Build and test"/.test(html) && !/<script>/.test(html) && /&lt;script&gt;/.test(html),
   `the page opens drawn from its Markdown, a [[link]] a link, and markup in it shown as text (${html.slice(0, 160)})`);
ok(/1 page/.test(await page.$eval(`${NB} #wkHint`, e => e.textContent)), 'the head row counts it');
// Read like an encyclopedia (the operator, 2 Oct): the title over a rule,
// said once though the page opens with it, a Contents box for its
// sections, and the pages listed beside the article.
const art = await page.$eval(`${NB} .wkarticle`, a => ({
  title: a.querySelector('.wktitle')?.textContent, h1s: a.querySelectorAll('.wkpage h3').length,
  toc: [...a.querySelectorAll('.wktoc li')].map(l => l.textContent),
  read: a.querySelector('#wkRead')?.classList.contains('on'),
  serif: getComputedStyle(a.querySelector('.wkpage')).fontFamily }));
ok(art.title === 'Home' && art.h1s === 2 && art.toc.join('|') === 'Welcome|Install|Detail' && art.read && /serif/i.test(art.serif),
   `an article: its title once, its sections in a Contents box, Read on, set in the serif (${JSON.stringify(art)})`);
ok(await page.$eval(`${NB} .wknav`, n => /Home/.test(n.textContent) && getComputedStyle(n).display !== 'none'),
   'the pages are listed beside it on a desktop');
// Its sections are drawn, and Contents goes to one (the operator, 4 Oct): a
// rule hiding every h3 in the notebook hid each ## section, and the links
// pointed at headings nobody could see.
ok(await page.$$eval(`${NB} .wkpage h3`, hs => hs.length === 2 && hs.every(h => h.checkVisibility() && h.getBoundingClientRect().height > 0)),
   'a page\'s ## sections are drawn, not hidden by the notebook\'s own heading rule');
await page.click(`${NB} .wktoc a[data-anchor="wk-install"]`);
await page.waitForFunction(sel => { const h = document.querySelector(sel); const sc = h?.closest('.doc');
  return h && sc && (h.getBoundingClientRect().top >= sc.getBoundingClientRect().top - 2 && h.getBoundingClientRect().bottom <= sc.getBoundingClientRect().bottom); },
  `${NB} #wk-install`, { timeout: 5000 }).catch(() => {});
ok(await page.$eval(`${NB} #wk-install`, h => { const sc = h.closest('.doc');
  return (h.getBoundingClientRect().top >= sc.getBoundingClientRect().top - 2 && h.getBoundingClientRect().bottom <= sc.getBoundingClientRect().bottom); }),
   '...and after a Contents link its section is in view in the pane');

// ---- Edit, and a stale save refused --------------------------------------------
const home = await api(`/api/wiki?project=${P}&page=Home`);
await page.click(`${NB} #wkEditTab`);
await page.fill(`${NB} #wkText`, '# Welcome back');
await page.click(`${NB} #wkSave`);
await page.waitForFunction(() => /Welcome back/.test(document.querySelector('.nb .wkarticle[data-name="Home"] .wkpage')?.textContent || ''),
  null, { timeout: 15000 });
ok(true, 'the Edit tab swaps the editor in and Save writes the page');
const stale = await api('/api/wiki', { project: P, action: 'save', name: 'Home', text: 'old', base: home.rev });
ok(stale.status === 409 && /changed since/.test(stale.error), `a save against an old read is refused (${stale.status} ${stale.error})`);

// ---- Export --------------------------------------------------------------------
const zip = await page.evaluate(async p => {
  const r = await fetch(`/api/wiki-export?project=${p}`);
  const b = new Uint8Array(await r.arrayBuffer());
  return { status: r.status, type: r.headers.get('content-type'), pk: b[0] === 0x50 && b[1] === 0x4b,
           cd: r.headers.get('content-disposition') };
}, P);
ok(zip.status === 200 && zip.pk && /alpha-wiki\.zip/.test(zip.cd), `Export is a zip of the pages (${JSON.stringify(zip)})`);

// ---- a session, through bb wiki, under each setting ------------------------------
const token = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', P, 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const bb = (...a) => execFileSync('bash', [`${REPO}/scripts/bb`, 'wiki', ...a], { encoding: 'utf8',
  env: { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: token, BB_PROJECT: P,
         XDG_CACHE_HOME: `${DIR}/cache-wiki` } });
const bbErr = (...a) => { try { bb(...a); return ''; } catch (e) { return String(e.stderr); } };
const src = `${DIR}/wiki-page.md`;
writeFileSync(src, 'How to build: `bb build`.\n');
ok(/saved Build-and-test/.test(bb('save', 'Build and test', src, '--why', 'how to build')),
   'bb wiki save writes a page under auto');
ok(/Build-and-test/.test(bb()) && bb('show', 'Build and test') === 'How to build: `bb build`.\n',
   'bb wiki lists it and shows it as kept');
await page.waitForFunction(() => /Build and test/.test(document.querySelector('.nb .wknav')?.textContent || ''), null, { timeout: 15000 });
ok(true, 'the open view picks up a session\'s page on the poll');
// A page in the list opens in place of the one on screen.
await page.click(`${NB} .wknav .wklink[data-page="Build-and-test"]`);
await page.waitForSelector(`${NB} .wkarticle[data-name="Build-and-test"] .wkpage`, { timeout: 15000 });
ok(/How to build/.test(await page.$eval(`${NB} .wkarticle .wkpage`, e => e.textContent)), 'a page in the list opens in place');
// On a phone the list gives way to a picker above the article.
await page.setViewportSize({ width: 393, height: 851 });
ok(await page.$eval(`${NB} .wknav`, n => getComputedStyle(n).display === 'none')
   && await page.$eval(`${NB} .wkpick`, n => getComputedStyle(n).display !== 'none'),
   'on a phone the pages are a picker over the article');
await page.setViewportSize({ width: 1280, height: 1000 });
// Rename asks in a box under the article's tabs, not the browser's prompt
// (R256 step 4): the name to change in it, Enter to rename, Escape to leave.
{
  const nd = page.dialogs.length;
  await page.click(`${NB} #wkRename`);
  await page.waitForSelector(`${NB} .askline input`, { timeout: 5000 });
  const was = await page.$eval(`${NB} .askline input`, i => i.value);
  await page.keyboard.press('Escape');
  const gone = !(await page.$(`${NB} .askline`));
  await page.click(`${NB} #wkRename`);
  await page.fill(`${NB} .askline input`, 'Building it');
  await page.keyboard.press('Enter');
  await page.waitForFunction(() => /Building it/.test(document.querySelector('.nb .wkarticle .wktitle')?.textContent || ''), null, { timeout: 15000 });
  ok(was === 'Build and test' && gone && page.dialogs.length === nd,
     `Rename asks in a box in the page with the name to change, Escape leaves it and Enter renames (${was})`);
}
await api('/api/prefs', { project: P, gate: { wiki: 'ask' } });
ok(/held for the operator's approval/.test(bb('save', 'Faq', src)) && /no page called/.test(bbErr('show', 'Faq')),
   'under ask a session\'s page is held, not written');
const pend = await api(`/api/pending?project=${P}`);
const held = (pend.records || pend.pending || []).filter(r => r.kind === 'wiki');
ok(held.length === 1, `...and waits on the notebook for approval (${JSON.stringify(pend).slice(0, 200)})`);
const ap = await api('/api/pending', { project: P, action: 'approve', ids: held.map(r => r.id) });
ok(ap.status === 200 && /How to build/.test(bb('show', 'Faq')), `approved, it lands (${ap.status})`);
await api('/api/prefs', { project: P, gate: { wiki: 'deny' } });
ok(/Write the wiki is deny/.test(bbErr('rm', 'Faq')), 'under deny a session is refused by the setting\'s name');
ok(await page.evaluate(() => gateChoices('wiki').map(c => c[0]).join() === 'auto,ask,deny,hidden'
                        && gateChoices('bugs').map(c => c[0]).join() === 'auto,ask,deny'),
   'the settings offer hidden on the wiki\'s dial and on no other');
const hid = await api('/api/prefs', { project: P, gate: { wiki: 'hidden' } });
ok(hid.status === 200 && hid.gate?.wiki === 'hidden', `the dial takes hidden for the wiki (${hid.status} ${JSON.stringify(hid.gate || hid.error)})`);
const nope = await api('/api/prefs', { project: P, gate: { bugs: 'hidden' } });
ok(nope.status >= 400, `...and for nothing else (${nope.error})`);
ok(/hidden from Claude/.test(bbErr()) && /hidden from Claude/.test(bbErr('show', 'Home'))
   && /hidden from Claude/.test(bbErr('save', 'Other', src)),
   'hidden keeps the wiki from a session: no list, no page, no save');
ok((await api(`/api/wiki?project=${P}`)).pages?.length >= 2, '...while a person still reads it');
await api('/api/prefs', { project: P, gate: { wiki: 'auto' } });
const push = await api('/api/wiki', { project: 'beta', action: 'push' });
ok(push.status >= 400 && /no remote|no push rights|no pages/.test(push.error || ''),
   `a push with nothing to reach is refused with the reason, and the harness never reaches a forge (${push.error})`);
await api('/api/prefs', { project: P, gate: { wiki: 'auto' } });

await done(browser);
