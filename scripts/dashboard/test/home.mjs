// Home (R218 step 5, the design's the-dashboard/home rule): the landing page.
// Tiles across the install, each a link into its page; Attention, the bell's
// own rows; the last ten jobs, each opening its row on the Jobs page; the
// pinned projects at a glance; read whole on open and light when the queue
// moves, never on a timer of its own.
import { URL, launch, newPage, ok, done, ready, sleep } from './lib.mjs';

const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const base = URL.replace(/\/$/, '');
const api = async (path, body) => {
  const r = await fetch(base + path, body === undefined ? { headers: auth }
    : { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.status === 204 ? {} : r.json();
};
const until = async (fn, ms = 20000, step = 200) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ const v = await fn(); if (v) return v; await sleep(step); }
  return null;
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the page, from the rail, at its own address ----------------------------
await page.click('#rail [data-rail="home"]');
await page.waitForSelector('.doc.on .hometiles .tile', { timeout: 20000 });
ok(await page.evaluate(() => tabOf(panes[0])?.kind === 'home' && location.hash === '#/home'),
   'Home is a page of its own on the rail, at #/home');

// ---- the tiles: across the install, and what /api/home says --------------------
{
  const h = await api('/api/home');
  const tiles = await page.$$eval('.doc.on .hometiles .tile', ts => ts.map(t => ({
    key: t.dataset.htile, value: t.querySelector('.tv')?.textContent, label: t.querySelector('.tl')?.textContent })));
  const by = Object.fromEntries(tiles.map(t => [t.key, t]));
  ok(['nodes', 'containers', 'jobs', 'sessions', 'updates', 'ci'].every(k => by[k]) && tiles.length === 6,
     `six tiles: nodes, containers, jobs, sessions, updates and CI (${tiles.map(t => t.key).join(', ')})`);
  ok(h.nodes && by.nodes.value === String(h.nodes.online) && by.jobs.value === String(h.jobs.running),
     `...the machines' and the queue's numbers are /api/home's (${by.nodes.value} of ${h.nodes?.enrolled} nodes, ${by.jobs.value} jobs running)`);
  ok(Array.isArray(h.jobs.last) && h.jobs.last.length <= 10 && typeof h.jobs.failed_today === 'number',
     `...which carries the last ten jobs and the ones failed today (${h.jobs.last.length} rows, ${h.jobs.failed_today} failed)`);
}

// ---- a job that fails shows on Home by itself, through the jobs token ----------
{
  const q = await api('/api/v1/nodes', { action: 'exec', id: 'local', argv: ['sh', '-c', 'echo from home; exit 3'] });
  ok(/^j_/.test(q.job || ''), `a job is queued on the controller (${q.job})`);
  const seen = await until(() => page.evaluate(id => !!document.querySelector(`.doc.on [data-hjob="${id}"] .pill.bad`), q.job), 30000);
  ok(seen, '...and once it has failed, its row is on Last jobs with the failed pill, with nothing pressed');
  ok(await page.$eval('.doc.on .hometiles [data-htile="jobs"]', t => !t.classList.contains('bad')
       && /failed today/.test(t.querySelector('.ts.bad')?.textContent || '')),
     '...and the jobs tile says how many failed today, the line in the bad tone rather than the count running');
  await page.click(`.doc.on [data-hjob="${q.job}"]`);
  await page.waitForFunction(id => tabOf(panes[0])?.kind === 'jobs'
    && document.querySelector(`.jbrow[data-job="${id}"].focus .jblog`), q.job, { timeout: 15000 });
  ok(true, 'a row on Last jobs opens its job on the Jobs page, brought into view with its log open');
}

// ---- a tile is a link into its page ----------------------------------------
{
  await page.click('#rail [data-rail="home"]');
  await page.waitForSelector('.doc.on .hometiles [data-htile="nodes"]', { timeout: 15000 });
  await page.click('.doc.on .hometiles [data-htile="nodes"]');
  await page.waitForFunction(() => tabOf(panes[0])?.kind === 'nodes', null, { timeout: 15000 });
  ok(true, 'the nodes tile opens the Nodes page');
  await page.click('#rail [data-rail="home"]');
  await page.waitForSelector('.doc.on .hometiles [data-htile="containers"]', { timeout: 15000 });
  await page.click('.doc.on .hometiles [data-htile="containers"]');
  await page.waitForFunction(() => tabOf(panes[0])?.kind === 'docker', null, { timeout: 15000 });
  ok(true, '...and the containers tile the Containers page');
  await page.click('#rail [data-rail="home"]');
  await page.waitForSelector('.doc.on .homegrid', { timeout: 15000 });
}

// ---- Attention is the bell's rows, and the pinned projects are at a glance ----
{
  const same = await page.evaluate(() => {
    const card = document.querySelector('.doc.on .homegrid .hcard');
    return { home: card.querySelectorAll('.bnote').length, bell: needsRows().length,
             empty: !!card.querySelector('.empty') };
  });
  ok(same.home === same.bell && (same.bell > 0 || same.empty),
     `Attention carries the bell's own rows (${same.home} of ${same.bell})`);
  await page.evaluate(() => setProjectPinned('alpha', true));
  await until(() => page.evaluate(() => !!document.querySelector('.doc.on .hglance [data-hproj="alpha"]')), 15000);
  ok(await page.$eval('.doc.on .hglance [data-hproj="alpha"]', b => b.closest('.hproj').querySelector('.pstate') !== null),
     'a pinned project is on Projects at a glance, with its session state');
  // In groups, as the Projects page is (R273): the ones in no group first,
  // then each group's name over its cards.
  await page.evaluate(async () => {
    setProjectPinned('beta', true);
    await postJSON('/api/project-group', { name: 'alpha', group: 'Zed' });
    await refresh();
  });
  await until(() => page.evaluate(() => !!document.querySelector('.doc.on .hgroup + .hglance [data-hproj="alpha"]')
    && !!document.querySelector('.doc.on .hglance [data-hproj="beta"]')), 15000);
  const order = await page.$$eval('.doc.on .hsect :is(.hgroup, [data-hproj])',
    els => els.map(e => e.matches('.hgroup') ? '#' + e.firstChild.textContent.trim() : e.dataset.hproj));
  ok(order.slice(-2).join() === '#Zed,alpha' && order.indexOf('beta') < order.indexOf('#Zed'),
     `Projects at a glance is in groups, the Projects page's order (${order.join()})`);
  await page.evaluate(async () => {
    setProjectPinned('beta', false);
    await postJSON('/api/project-group', { name: 'alpha', group: '' });
    await refresh();
  });
  await until(() => page.evaluate(() => !document.querySelector('.doc.on .hgroup')), 15000);
  await page.click('.doc.on .hglance [data-hproj="alpha"]');
  await page.waitForFunction(() => tabOf(panes[0])?.kind === 'notebook' && tabOf(panes[0])?.arg === 'alpha', null, { timeout: 15000 });
  ok(true, '...and its name opens the project\'s page');
  await page.click('#rail [data-rail="home"]');
  await page.waitForSelector('.doc.on .homegrid', { timeout: 15000 });
}

// ---- on a phone the cards stack and nothing scrolls sideways -----------------
{
  await page.setViewportSize({ width: 393, height: 851 });
  await sleep(400);
  const lay = await page.evaluate(() => {
    const [a, b] = [...document.querySelectorAll('.doc.on .homegrid .hcard')].map(c => c.getBoundingClientRect());
    return { stacked: b.top >= a.bottom - 1, over: document.documentElement.scrollWidth - innerWidth,
             tiles: [...document.querySelectorAll('.doc.on .hometiles .tile')].every(t => t.getBoundingClientRect().right <= innerWidth + 1) };
  });
  ok(lay.stacked && lay.over <= 0 && lay.tiles,
     `on a phone Attention and Last jobs stack, and the tiles fit the width (${JSON.stringify(lay)})`);
  await page.setViewportSize({ width: 1280, height: 900 });
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
