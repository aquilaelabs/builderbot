// Help on the rail (R258, the operator 16 Oct): BuilderBot's own docs read in
// the dashboard. The page lists them in docs/README.md's groups beside the
// article, opens a long one on its contents box, follows a link between docs
// in place with an address per doc, and searches them all as the bar's field
// is typed, a result opening its doc at its section.
import { URL, launch, newPage, ok, done, ready, sleep } from './lib.mjs';

const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const base = URL.replace(/\/$/, '');
const get = async path => (await fetch(base + path, { headers: auth })).json();

// ---- the server's half ------------------------------------------------------
{
  const idx = await get('/api/help');
  const names = (idx.groups || []).flatMap(g => g.docs.map(d => d.name));
  ok(idx.home === 'README' && idx.groups?.length >= 3 && names.includes('install') && names.includes('how-it-works'),
     `the docs are listed in README's groups (${(idx.groups || []).map(g => g.group).join(' / ')})`);
  const one = await get('/api/help?doc=install');
  ok(one.title && /# /.test(one.text || ''), `...one is read by its name (${one.title})`);
  const bad = await get('/api/help?doc=' + encodeURIComponent('../README'));
  ok(!!bad.error, `...and nothing else reaches the disk (${bad.error})`);
  const hits = await get('/api/help?q=' + encodeURIComponent('session token'));
  // The line as shown is cut at 240 characters, so it may have lost one of
  // the words the whole line held; each still shows one.
  ok(hits.results?.length > 0 && hits.results.every(r => r.doc && r.title && /session|token/i.test(r.text)),
     `a search finds the lines that say every word, each with its doc (${hits.results?.length})`);
}

const browser = await launch();
for (const [W, H] of [[1280, 900], [393, 852]]){
  const page = await newPage(browser, W < 900 ? { viewport: { width: W, height: H }, isMobile: true, hasTouch: true } : { viewport: { width: W, height: H } });
  await page.goto(URL);
  await ready(page);
  const at = W < 900 ? 'on a phone' : 'at a desk';
  // On the rail at a desk, under More on a phone.
  const where = await page.evaluate(() => [...document.querySelectorAll('#rail [data-rail="help"], #railmore [data-rail="help"]')].length);
  ok(where > 0, `${at}: Help is on the rail${W < 900 ? ", under More" : ""}`);
  await page.evaluate(() => railGo('help'));
  await page.waitForSelector('.helptab .wkarticle .wkpage', { timeout: 15000 });
  const land = await page.evaluate(() => ({ hash: location.hash, title: document.querySelector('.helptab .wktitle')?.textContent,
    nav: document.querySelectorAll('.helptab .wknav a[data-page]').length, pick: document.querySelectorAll('#helpPick option').length,
    bar: [...document.querySelectorAll('#pane0 > .bar .subnav button')].map(b => b.textContent) }));
  ok(land.hash === '#/help' && land.title && land.pick > 5 && (W < 900 || land.nav > 5) && land.bar.join() === 'Help',
     `${at}: it opens on the docs' index, every doc listed beside it or in its picker (${JSON.stringify(land)})`);
  // A link between docs opens the other one here, with its own address.
  await page.click('.helptab .wkpage a.wklink[data-page="install"]');
  await page.waitForFunction(() => location.hash === '#/help/install' && document.querySelector('.helptab .wkarticle[data-name="install"] .wktoc'), null, { timeout: 10000 });
  ok(true, `${at}: a link to another doc opens it in place, at #/help/install, on its contents box`);
  // The contents box scrolls to its section.
  const before = await page.evaluate(() => document.querySelector('.doc.on').scrollTop);
  await page.click('.helptab .wktoc li:nth-child(4) a');
  await sleep(900);
  ok(await page.evaluate(b => document.querySelector('.doc.on').scrollTop > b, before), `${at}: a line of the contents scrolls to its section`);
  // The search, as it is typed: results in the article's place, a result
  // opening its doc at its section.
  await page.fill('#helpQ', 'session token');
  await page.waitForSelector('.helptab .helphit', { timeout: 10000 });
  const res = await page.evaluate(() => ({ n: document.querySelectorAll('.helphit').length, mark: document.querySelectorAll('.helphit mark').length }));
  ok(res.n > 0 && res.mark > 0, `${at}: searching shows the lines found, the words marked (${JSON.stringify(res)})`);
  const target = await page.$eval('.helphit[data-anchor]:not([data-anchor=""])', b => b.dataset.hit);
  await page.click('.helphit[data-anchor]:not([data-anchor=""])');
  await page.waitForFunction(t => location.hash.startsWith('#/help') && document.querySelector(`.helptab .wkarticle[data-name="${t}"]`), target, { timeout: 10000 });
  ok(await page.$eval('#helpQ', q => q.value === '') && !(await page.$('.helphit')), `${at}: a result opens its doc and the search clears`);
  // Back walks the docs read.
  await page.goBack();
  await page.waitForFunction(() => location.hash === '#/help/install' || location.hash === '#/help', null, { timeout: 10000 });
  ok(true, `${at}: Back returns to the doc before (${await page.evaluate(() => location.hash)})`);
  ok(page.errors.length === 0, `${at}: zero console errors (${page.errors.join(' | ').slice(0, 200)})`);
  await page.close();
}
await done(browser);
