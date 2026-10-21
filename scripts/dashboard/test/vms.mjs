#!/usr/bin/env node
// The VMs page (R91): a node with VM host installed, enrolled here by hand
// with its census; New VM queues the node's vm job and the row says so; the
// agent's result and its census make the row running with its address; Stop,
// a snapshot and Remove each a vm job; a session's bb vm is held to its
// project's Make VMs dial (deny refuses, ask goes to the bell, auto does it),
// and a session never makes Windows.
import { URL, launch, newPage, ok, done, ready, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGJ0ZXN0a2V5Zm9ydGhldm1tYW5hZ2VydGVzdHMx test';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const base = URL.replace(/\/$/, '');
const call = async (path, body, headers = H) => {
  const r = await fetch(base + path, body === undefined ? { headers } : { method: 'POST', headers, body: JSON.stringify(body) });
  return { status: r.status, ...(await r.json()) };
};

// The page is a tool of the Containers group, between Containers and nginx.
ok(await page.evaluate(() => railGroups().some(g => g.key === 'containers' && g.tools.map(([k]) => k).join() === 'docker,vms,nginx')),
   'the rail offers VMs in the Containers group, between Containers and nginx');
await page.evaluate(() => openVmsTab());
await page.waitForSelector('.vmtab .vmnone', { timeout: 15000 });
ok(/No node has VM host yet/.test(await page.$eval('.vmtab .vmnone', e => e.textContent)) && await page.$eval('#bVmNew', b => b.disabled),
   'with no VM host anywhere the page says where it is installed, and New VM sleeps');

// A node with VM host installed: enrolled with its census, as an agent would.
const minted = await call('/api/v1/nodes', { action: 'enroll', name: 'kvmbox' });
const shipped = (await call('/api/v1/nodes')).agent || {};
const CENSUS = { cpu: 8, mem_mb: 32768, os: 'linux x86_64 Ubuntu', system: 'linux', arch: 'x86_64', sandbox: true, administers: true,
                 features: { vmhost: { installed: true, kvm: true, libvirt: '12.0.0' }, firewall: { installed: false } },
                 vm_pool: { free_mb: 400000, total_mb: 500000 }, vms: [] };
const en = await call('/api/v1/agent/enroll', { census: CENSUS, version: shipped.version, digest: shipped.digest, user: 'bb' },
                      { Authorization: 'Bearer ' + minted.token, 'Content-Type': 'application/json' });
const AH = { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' };
const agent = (verb, body) => call('/api/v1/agent/' + verb, body, AH);
const hello = vms => agent('hello', { census: { ...CENSUS, vms }, version: shipped.version, digest: shipped.digest });
await hello([]);
ok(en.ok, 'a node with VM host installed is enrolled');
await call('/api/prefs', { project: 'alpha', nodes: [minted.id], node: minted.id });

// New VM, from the page's dialog.
await page.evaluate(async () => { await loadVms(); });
await page.waitForFunction(() => document.querySelector('#bVmNew') && !document.querySelector('#bVmNew').disabled, null, { timeout: 15000 });
await page.click('#bVmNew');
await page.waitForSelector('#vmnewmodal:not([hidden]) #vmName', { timeout: 10000 });
const offered = await page.$$eval('#vmOs option', os => os.map(o => o.value));
ok(offered.includes('debian-13') && offered.includes('ubuntu-24.04') && !offered.includes('windows-11'),
   `New VM offers the catalog's operating systems and not a person's one (${offered.join(', ')})`);
await page.fill('#vmName', 'db');
await page.selectOption('#vmProject', 'alpha');
await page.selectOption('#vmOs', 'debian-13');
await page.fill('#vmKey', KEY);
await page.click('#vmGo');
const job = await (async () => { for (let i = 0; i < 40; i++){
  const j = ((await call('/api/v1/jobs?active=1')).jobs || []).find(x => x.type === 'vm');
  if (j) return j;
  await sleep(250);
} return null; })();
ok(job?.spec?.action === 'create' && job.spec.domain === 'bbvm-alpha-db' && job.spec.image.url.startsWith('https://cloud.debian.org/')
   && job.spec.subnet === '10.232.0.0/24' && job.node === minted.id,
   `Make it queues the node's vm job: create, its domain, the image and the project's network (${JSON.stringify({ a: job?.spec?.action, d: job?.spec?.domain, s: job?.spec?.subnet })})`);
await page.waitForFunction(() => /being made/.test(document.querySelector('.vmtab [data-vm-key="alpha/db"]')?.textContent || ''), null, { timeout: 15000 });
ok(await page.$eval('.vmtab', e => !!e.querySelector('.dmcard .dmgroup') && /alpha/.test(e.querySelector('.dmgroup').textContent)),
   '...and the row stands in its project\'s card, being made');

// The agent takes it, it succeeds, and its census says it runs with an address.
const took = await agent('work', { running: [], wait: 0 });
await agent('result', { job: took.id, state: 'succeeded', exit: 0 });
await hello([{ name: 'bbvm-alpha-db', state: 'running', ip: '10.232.0.12', vcpus: 2, mem_mb: 2048, snapshots: ['clean'] }]);
await page.evaluate(async () => { await loadVms(); });
await page.waitForFunction(() => /10\.232\.0\.12/.test(document.querySelector('.vmtab [data-vm-key="alpha/db"]')?.textContent || ''), null, { timeout: 15000 });
const row = await page.$eval('.vmtab [data-vm-key="alpha/db"]', e => ({ text: e.textContent.replace(/\s+/g, ' '),
  pill: e.querySelector('.dmpill')?.className, stop: !!e.querySelector('[data-vm="stop"]'), con: !!e.querySelector('[data-vmcon]'),
  snap: !!e.querySelector('.vmsnap [data-vm="revert"]') }));
ok(/running/.test(row.text) && /ok/.test(row.pill) && /ssh builder@10\.232\.0\.12/.test(row.text) && /Debian 13/.test(row.text)
   && /kvmbox/.test(row.text) && row.stop && row.con && row.snap,
   `once made it runs: its pill, how to reach it, its OS and node, Stop, Console and its snapshot with Revert (${row.text.slice(0, 120)})`);

// The notebook's VMs view (R96): the project's own VMs, beside Docker in
// its Ship group, drawn from the page's rows, with New VM in its head.
await page.evaluate(() => openNotebook('alpha', 'vms'));
await page.waitForFunction(() => /1 running of 1/.test(document.querySelector('.nbview[data-view="vms"] #nvHint')?.textContent || ''), null, { timeout: 15000 });
const nv = await page.evaluate(() => {
  const v = document.querySelector('.nbview[data-view="vms"]');
  return { ship: [...document.querySelectorAll('.nbsub [data-in="ship"]')].map(b => b.dataset.v).join(),
           row: !!v.querySelector('[data-vm-key="alpha/db"]'), newVm: !v.querySelector('#nvNew').hidden };
});
ok(nv.ship === 'artifacts,docker,vms' && nv.row && nv.newVm,
   `a project's notebook has VMs beside Docker in Ship, its own VM's row and New VM in its head (${JSON.stringify(nv)})`);
await page.evaluate(() => openVmsTab());
await page.waitForSelector('.vmtab [data-vm-key="alpha/db"]', { timeout: 10000 });

// Stop and Revert are vm jobs too; Remove asks first.
page.dialogs.length = 0;
await page.click('.vmtab [data-vm-key="alpha/db"] .dmacts [data-vm="stop"]:not([data-force])');
const stop = await (async () => { for (let i = 0; i < 40; i++){
  const j = ((await call('/api/v1/jobs?active=1')).jobs || []).find(x => x.type === 'vm' && x.spec?.action === 'stop');
  if (j) return j;
  await sleep(250);
} return null; })();
ok(stop && !stop.spec.force, 'Stop queues a shutdown, not a pulled plug');
await call('/api/v1/jobs', { action: 'cancel', id: stop?.id });
await page.evaluate(async () => { await loadVms(); });
await page.waitForSelector('.vmtab [data-vm-key="alpha/db"] .vmsnap [data-vm="revert"]', { timeout: 10000 });
await page.click('.vmtab [data-vm-key="alpha/db"] .vmsnap [data-vm="revert"]');
const rv = await (async () => { for (let i = 0; i < 40; i++){
  const j = ((await call('/api/v1/jobs?active=1')).jobs || []).find(x => x.type === 'vm' && x.spec?.action === 'revert');
  if (j) return j;
  await sleep(250);
} return null; })();
ok(page.dialogs.some(d => /Revert db to clean/.test(d)) && rv?.spec?.snapshot === 'clean',
   `Revert asks, then queues the revert to that snapshot (${rv?.spec?.snapshot})`);
await call('/api/v1/jobs', { action: 'cancel', id: rv?.id });

// A session's bb vm, held to its project's dial.
const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const S = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok };
const denied = await call('/api/vms', { action: 'new', name: 'w1', os: 'debian', keys: [KEY], why: 'a test box' }, S);
ok(denied.status === 403 && /Make VMs is deny/.test(denied.error || ''), `at deny a session's bb vm is refused, naming the setting (${denied.error})`);
await call('/api/prefs', { project: 'alpha', makevms: 'ask' });
const asked = await call('/api/vms', { action: 'new', name: 'w1', os: 'debian', keys: [KEY], why: 'a test box' }, S);
const bell = ((await call('/api/phone')).asks || []).find(a => a.id === asked.id);
ok(asked.id && bell?.kind === 'vm' && /vm new w1 --os debian/.test((bell.cmd || []).join(' ')),
   `at ask it waits on the bell with the verb shown (${(bell?.cmd || []).join(' ')})`);
await call('/api/phone', { action: 'deny', id: asked.id });
await call('/api/prefs', { project: 'alpha', makevms: 'auto' });
const win = await call('/api/vms', { action: 'new', name: 'w2', os: 'windows', keys: [KEY], why: 'x' }, S);
ok(/a person's to do/.test(win.error || ''), `even at auto a session does not make Windows (${win.error})`);
const other = await call('/api/vms', { action: 'new', project: 'beta', name: 'x', os: 'debian', keys: [KEY], why: 'x' }, S);
ok(other.status === 403 && /alpha's VMs alone/.test(other.error || ''), "a session works on its own project's VMs alone");
const madeNow = await call('/api/vms', { action: 'new', name: 'w3', os: 'ubuntu 24.04', keys: [KEY], why: 'x' }, S);
ok(madeNow.ok && madeNow.domain === 'bbvm-alpha-w3', `at auto its own project's VM is made now (${madeNow.domain || madeNow.error})`);
await call('/api/prefs', { project: 'alpha', makevms: 'deny' });

// Remove asks, says what goes, and its job's success takes the record.
page.dialogs.length = 0;
await page.evaluate(async () => { await loadVms(); });
await page.click('.vmtab [data-vm-key="alpha/db"] .actbar .more > button, .vmtab [data-vm-key="alpha/db"] [data-more]').catch(() => {});
const removed = await page.evaluate(async () => (await (await postJSON('/api/vms', { action: 'remove', project: 'alpha', name: 'db' })).json()));
ok(removed.ok, 'Remove queues its vm job');
for (let i = 0; i < 4; i++){
  const w = await agent('work', { running: [], wait: 0 });
  if (!w?.id) break;
  await agent('result', { job: w.id, state: 'succeeded', exit: 0 });
}
const left = (await call('/api/vms')).vms.map(v => v.key);
ok(!left.includes('alpha/db'), `...and once it has run the record is gone (${left.join(', ')})`);
await call('/api/v1/nodes', { action: 'retire', id: minted.id });
await done(browser);
