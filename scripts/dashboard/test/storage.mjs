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
  docker: { kinds: [{ kind: 'Images', count: 3, mb: 1500, reclaimable_mb: 400 }], root: '/var/lib/docker', fs: '/' }, slow: [] };
const en = await (await fetch(base + '/api/v1/agent/enroll', { method: 'POST',
  headers: { Authorization: 'Bearer ' + minted.token, 'Content-Type': 'application/json' },
  body: JSON.stringify({ census: { cpu: 4, mem_mb: 8192, system: 'linux', arch: 'x86_64', storage: WALK },
                         version: shipped.version, digest: shipped.digest, user: 'bb' }) })).json();
ok(en.ok, `a node enrolled with a walk of its disks in its census (${en.error || 'ok'})`);

ok(await page.$eval('#bStorage', b => !b.hidden && /Storage/.test(b.textContent)), 'the Tools card offers Storage');
await page.click('#bStorage');
await page.waitForSelector('.storagetab details.sect', { timeout: 15000 });
const row = await page.evaluate(() => (storageList || []).find(n => n.name === 'diskbox'));
ok(row && row.measured && row.projects.map(p => p.name).join() === 'alpha,beta' && row.projects[0].total === 6400 && !row.other,
   `the tab lists the node with its projects largest first, every one named for an administrator (${JSON.stringify(row?.projects)})`);
const sect = `.storagetab details.sect[data-sect="storage:${minted.id}"]`;
const drawn = await page.$eval(sect, s => ({ status: s.querySelector('summary .sst')?.textContent,
  meters: [...s.querySelectorAll('.ndmeter .lbl')].map(l => l.textContent),
  vals: [...s.querySelectorAll('.ndmeter .val')].map(v => v.textContent),
  stores: /cache store/.test(s.textContent) && /Docker/.test(s.textContent) && /reclaimable/.test(s.textContent),
  proj: [...s.querySelectorAll('.stproj:not(.sthead) .name')].map(n => n.textContent.trim()),
  measure: !!s.querySelector('[data-stmeasure]') }));
ok(/measured 10 min ago/.test(drawn.status) && drawn.meters.join() === '/,/mnt/share' && /93\.8 GB \/ 125 GB/.test(drawn.vals[0])
   && drawn.stores && drawn.proj.join('|') === 'alpha|beta' && drawn.measure,
   `...its section: each filesystem a meter, the stores and Docker's share, the projects in rows, Measure now (${JSON.stringify(drawn)})`);
// The meters are one stack: every track the same width, the values one column.
const stack = await page.$$eval(`${sect} .ndmeter .track`, ts => new Set(ts.map(t => Math.round(t.getBoundingClientRect().width))).size);
ok(stack === 1, 'every meter in the stack has the same track width');
await page.click(`${sect} [data-stmeasure]`);
const job = await (async () => { for (let i = 0; i < 40; i++){
  const js = (await api('/api/v1/jobs?active=1')).jobs || [];
  const j = js.find(x => x.type === 'storage' && x.node === minted.id);
  if (j) return j;
  await new Promise(r => setTimeout(r, 250));
} return null; })();
ok(job && job.type === 'storage', `Measure now queues the agent's storage job on that node (${job?.id})`);
if (job) await api('/api/v1/jobs', { action: 'cancel', id: job.id });
await api('/api/v1/nodes', { action: 'retire', id: minted.id });

await done(browser);
