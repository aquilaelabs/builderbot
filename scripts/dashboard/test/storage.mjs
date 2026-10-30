#!/usr/bin/env node
// The Storage tab (R169): what every node's disks hold, by project. The
// harness's fixture node is enrolled by hand with a walk in its census; the
// tab lists it with its filesystems as meters, its stores, and its projects
// largest first; Measure now queues the agent's storage job.
import { URL, launch, newPage, ok, done, ready } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const base = URL.replace(/\/$/, '');
const api = async (path, body) => (await fetch(base + path, body === undefined
  ? { headers: H } : { method: 'POST', headers: H, body: JSON.stringify(body) })).json();

// A node with a walk in its census.
const minted = await api('/api/v1/nodes', { action: 'enroll', name: 'diskbox' });
const shipped = (await api('/api/v1/nodes')).agent || {};
const WALK = { at: Math.floor(Date.now() / 1000) - 600, took_s: 4,
  filesystems: [{ path: '/', source: '/dev/vda2', type: 'ext4', ro: false, total_mb: 128000, used_mb: 96000, free_mb: 32000, also: [] },
                { path: '/mnt/share', source: 'nas:/export', type: 'nfs', ro: false, total_mb: 50000000, used_mb: 38000000, free_mb: 12000000, also: [] }],
  stores: { cache: { path: '/var/lib/builderbot/cache', fs: '/', used_mb: 4200 }, artifacts: { path: '/var/lib/builderbot/artifacts', fs: '/', used_mb: 900 } },
  projects: { alpha: { workspace: 300, cache: 4000, builds: 2100 }, beta: { cache: 200, artifacts: 900 } },
  workspace: { path: '/workspace', fs: '/' }, homes: { path: '/home/bb', mb: 2500, fs: '/' },
  docker: { kinds: [{ kind: 'Images', count: 3, mb: 1500, reclaimable_mb: 400 }, { kind: 'Build Cache', count: 9, mb: 700, reclaimable_mb: 650 }],
            root: '/var/lib/docker', fs: '/' }, slow: [],
  // Each project's phones (R123): one idle, one running.
  phones: [{ project: 'alpha', uid: '', name: 'builderbot-36', mb: 4096, running: false },
           { project: 'alpha', uid: '', name: 'builderbot-35', mb: 2048, running: true }] };
const en = await (await fetch(base + '/api/v1/agent/enroll', { method: 'POST',
  headers: { Authorization: 'Bearer ' + minted.token, 'Content-Type': 'application/json' },
  body: JSON.stringify({ census: { cpu: 4, mem_mb: 8192, system: 'linux', arch: 'x86_64', storage: WALK },
                         version: shipped.version, digest: shipped.digest, user: 'bb' }) })).json();
ok(en.ok, `a node enrolled with a walk of its disks in its census (${en.error || 'ok'})`);

ok(await page.evaluate(() => railGroups().some(g => g.key === 'machines' && g.tools.some(([k]) => k === 'storage')) && railAllows('storage')), 'the rail offers Storage under Machines');
await page.evaluate(() => openStorageTab());
await page.waitForSelector('.storagetab [data-stnode]', { timeout: 15000 });
const row = await page.evaluate(() => (storageList || []).find(n => n.name === 'diskbox'));
ok(row && row.measured && row.projects.map(p => p.name).join() === 'alpha,beta' && row.projects[0].total === 6400 && !row.other,
   `the tab lists the node with its projects largest first, every one named for an administrator (${JSON.stringify(row?.projects)})`);
// One node at a time, picked in the bar like Toolchains (the operator, 11 Oct).
await page.waitForFunction(() => [...document.querySelectorAll('.pane .bar select#ndPick option')].some(o => o.textContent === 'diskbox'), null, { timeout: 15000 });
ok(await page.$eval('.pane .bar label.pick select#ndPick', s => [...s.options].some(o => o.textContent === 'diskbox')),
   'the bar picks the node, as Toolchains does');
await page.selectOption('.pane .bar #ndPick', minted.id);
const sect = `.storagetab [data-stnode="${minted.id}"]`;
await page.waitForSelector(sect, { timeout: 10000 });
const drawn = await page.$eval(sect, s => ({ status: 'measured ' + ([...s.querySelectorAll('.toolstate .fact')].find(f => f.querySelector('dt')?.textContent === 'Measured')?.querySelector('dd')?.textContent.trim() || ''),
  // Each filesystem a card titled by its mount (R218 step 47), its meter "used".
  meters: [...s.querySelectorAll('details[data-sect^="storage:fs:"] > summary .t')].map(l => l.textContent),
  used: [...s.querySelectorAll('.ndmeter .lbl')].every(l => l.textContent === 'used'),
  vals: [...s.querySelectorAll('.ndmeter .val')].map(v => v.textContent),
  stores: /cache store/.test(s.textContent) && /Docker/.test(s.textContent) && /reclaimable/.test(s.textContent),
  proj: [...s.querySelectorAll('.stproj:not(.sthead) .name')].map(n => n.textContent.trim()),
  // Measure now on the head's action row under its facts, as a node's
  // buttons are on the Nodes page (the operator, 29 Oct), and no Refresh
  // (17 Oct): the walk lands with the census the page follows.
  measure: !!document.querySelector('.storagetab .pghead .actbar [data-stmeasure]') && !document.querySelector('.storagetab .docbarrow [data-stmeasure]') && !document.querySelector('#stReload'),
  // Each meter's block: what BuilderBot holds on that disk, largest first (R203).
  disks: [...s.querySelectorAll('.stdisk')].map(d => { const rows = []; let e = d.nextElementSibling;
    while (e && e.classList.contains('row')){ rows.push(e.querySelector('.name, .sub').textContent.trim().split(' ·')[0]); e = e.nextElementSibling; }
    return `${d.closest('details').querySelector('summary .t').textContent}: ${rows.join(', ')}`; }) }));
ok(/measured 10 min ago/.test(drawn.status) && drawn.meters.join() === '/,/mnt/share' && drawn.used && /93\.8 GB \/ 125 GB/.test(drawn.vals[0])
   && drawn.stores && drawn.proj.join('|') === 'alpha|beta' && drawn.measure,
   `...the node: each filesystem a meter, the stores and Docker's share, the projects in rows, Measure now under the head's facts (${JSON.stringify(drawn)})`);
ok(drawn.disks.join(' | ') === '/: cache store, the accounts\' homes, Docker, artifacts store, synced copies | /mnt/share: ',
   `...and under each meter what BuilderBot holds on that disk, largest first, the share with nothing on it bare (${JSON.stringify(drawn.disks)})`);
// The meters are one stack: every track the same width, the values one column.
const stack = await page.$$eval(`${sect} .ndmeter .track`, ts => new Set(ts.map(t => Math.round(t.getBoundingClientRect().width))).size);
ok(stack === 1, 'every meter in the stack has the same track width');
await page.click(`.storagetab .pghead [data-stmeasure="${minted.id}"]`);
const job = await (async () => { for (let i = 0; i < 40; i++){
  const js = (await api('/api/v1/jobs?active=1')).jobs || [];
  const j = js.find(x => x.type === 'storage' && x.node === minted.id);
  if (j) return j;
  await new Promise(r => setTimeout(r, 250));
} return null; })();
ok(job && job.type === 'storage', `Measure now queues the agent's storage job on that node (${job?.id})`);
// ...and the button comes back once the press is answered: the bar's markup
// is the same after it, and a repaint that skipped it left Asking for good.
const back = await page.waitForFunction(id => {
  const b = document.querySelector(`.storagetab .pghead [data-stmeasure="${id}"]`);
  return b && !b.disabled && b.textContent.trim() === 'Measure now';
}, minted.id, { timeout: 15000 }).then(() => true, () => false);
ok(back, 'Measure now reads Measure now again once its press is answered, not Asking');
if (job) await api('/api/v1/jobs', { action: 'cancel', id: job.id });

// The page measures, and each thing is freed on the page that manages it
// (the operator, 23 Oct): its phones are listed here with a link to the
// Emulator page, where each has its Remove, refused while one runs; no
// prune and no clear is pressed here.
{
  const seen = await page.evaluate(() => {
    const s = document.querySelector('.storagetab details[data-sect="storage:phones"]');
    return { rows: [...(s?.querySelectorAll('.stphone') || [])].map(r => r.textContent.replace(/\s+/g, ' ').trim()),
             buttons: document.querySelectorAll('.storagetab [data-stavd], .storagetab [data-stclear], .storagetab [data-stdprune]').length,
             link: /Emulator page/.test(s?.textContent || '') };
  });
  ok(seen.rows.length === 2 && /builderbot-36/.test(seen.rows[0]) && /running/.test(seen.rows[1]) && seen.buttons === 0 && seen.link,
     `Storage lists each phone, largest first, with no button of its own and the way to the Emulator page (${JSON.stringify(seen)})`);
  await page.evaluate(id => { emuNode = id; openEmulator(); }, minted.id);
  await page.waitForSelector('.emutab details[data-sect="emulator:phones"] .emphone', { timeout: 15000 });
  const em = await page.evaluate(() => {
    const s = document.querySelector('.emutab details[data-sect="emulator:phones"]');
    return { rows: s.querySelectorAll('.emphone').length, removes: s.querySelectorAll('[data-emuphone]').length };
  });
  ok(em.rows === 2 && em.removes === 1, `the Emulator page lists the node's phones, and only the one not running has a Remove (${JSON.stringify(em)})`);
  page.answers.push(0);
  await page.click('.emutab [data-emuphone="alpha"]');
  const avd = await (async () => { for (let i = 0; i < 40; i++){
    const js = (await api('/api/v1/jobs?active=1')).jobs || [];
    const j = js.find(x => x.type === 'avd-remove' && x.node === minted.id);
    if (j) return j;
    await new Promise(r => setTimeout(r, 250));
  } return null; })();
  ok(avd && avd.spec?.name === 'builderbot-36' && avd.spec?.project === 'alpha',
     `Remove asks, then queues the phone's removal on that node (${JSON.stringify(avd?.spec || null)})`);
  if (avd) await api('/api/v1/jobs', { action: 'cancel', id: avd.id });
  const refused = await api('/api/emulator', { action: 'phone-remove', node: minted.id, project: 'alpha', uid: '', name: 'builderbot-35' });
  ok(/running/.test(refused.error || ''), `a running phone is refused by the server too (${refused.error})`);
}
await api('/api/v1/nodes', { action: 'retire', id: minted.id });

await done(browser);
