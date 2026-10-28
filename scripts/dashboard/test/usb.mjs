#!/usr/bin/env node
// USB devices to VMs (R116): a VM host's node page gains a USB section that
// lists each device the node reports with what holds it, Give to a VM
// queues the node's usb-give job with the device named by vendor, product,
// serial and port, a device the host boots from offers no Give and says
// why, a VM holding one says so on its row on the VMs page and the section
// offers Take back, the controllers are listed with what hangs off each and
// what shares their IOMMU group, the Features section offers the IOMMU with
// Install, and a session's bb vm usb is held for a person whatever the dial.
import { URL, launch, newPage, ok, done, ready, sleep, openSection, DIR, saveDialog, refreshUntil } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');

// A name of this run's own: on a kept fixture an earlier run's VM record may still be there.
const VMN = 'lab' + Date.now().toString(36).slice(-3);
const KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGJ0ZXN0a2V5Zm9ydGhldm1tYW5hZ2VydGVzdHMx test';
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const base = URL.replace(/\/$/, '');
const call = async (path, body, headers = H) => {
  const r = await fetch(base + path, body === undefined ? { headers } : { method: 'POST', headers, body: JSON.stringify(body) });
  const t = await r.text();
  return { status: r.status, ...(t ? JSON.parse(t) : {}) };
};

// A VM host with two sticks alike (one the host boots from), a receiver,
// and two USB controllers, one sharing its IOMMU group with the LAN.
// On a kept fixture an earlier run's node may still be there: retired first.
for (const n of ((await call('/api/v1/nodes')).nodes || []).filter(n => n.name === 'usbbox' && n.state !== 'retired'))
  await call('/api/v1/nodes', { action: 'retire', id: n.id });
const minted = await call('/api/v1/nodes', { action: 'enroll', name: 'usbbox' });
ok(!!minted.id, `an enroll token for the host (${minted.error || minted.id})`);
const shipped = (await call('/api/v1/nodes')).agent || {};
const STICK = { vendor: '0x0781', product: '0x5583', name: 'SanDisk Ultra Fit', serial: '4C53', port: '1-3', bus: 1, speed: '5000', driver: 'usb-storage', ctl: '0000:00:14.0', use: [] };
const BOOT = { ...STICK, serial: 'BOOT', port: '1-4', use: ['the host boots from it (sda1 is /)'] };
const MOUSE = { vendor: '0x046d', product: '0xc52b', name: 'Logitech Receiver', serial: '', port: '2-1', bus: 2, speed: '12', driver: 'usbhid', ctl: '0000:03:00.0', use: [] };
const VM_HOST = { cpus: [[0, 4], [1, 5]], iommu: true, usb: [STICK, BOOT, MOUSE],
  pci: [{ addr: '0000:00:14.0', class: '0x0c0330', vendor: '0x8086', device: '0x1234', group: '7', driver: 'xhci_hcd', host: 'the host boots from it (sda1 is /)' },
        { addr: '0000:03:00.0', class: '0x0c0330', vendor: '0x1912', device: '0x0014', group: '12', driver: 'xhci_hcd', host: '' },
        { addr: '0000:03:00.1', class: '0x020000', vendor: '0x8086', device: '0x15b8', group: '12', driver: 'e1000e', host: "the host's LAN interface" }] };
const CENSUS = { cpu: 8, mem_mb: 32768, os: 'linux x86_64 Ubuntu', system: 'linux', arch: 'x86_64', sandbox: true, administers: true,
                 features: { vmhost: { installed: true, kvm: true, libvirt: '12.0.0' }, firewall: { installed: false }, iommu: { installed: false, on: true } },
                 vm_pool: { free_mb: 400000, total_mb: 500000 }, vm_host: VM_HOST, vms: [] };
const en = await call('/api/v1/agent/enroll', { census: CENSUS, version: shipped.version, digest: shipped.digest, user: 'bb' },
                      { Authorization: 'Bearer ' + minted.token, 'Content-Type': 'application/json' });
const AH = { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' };
const agent = (verb, body) => call('/api/v1/agent/' + verb, body, AH);
const hello = (vms, extra = {}) => agent('hello', { census: { ...CENSUS, vms, ...extra }, version: shipped.version, digest: shipped.digest });
await hello([]);
ok(en.ok, 'a VM host with USB devices and controllers in its census is enrolled');
await call('/api/prefs', { project: 'alpha', nodes: [minted.id], node: minted.id });

// A VM on it, made and reported stopped.
const made = await call('/api/vms', { action: 'new', project: 'alpha', name: VMN, os: 'debian-13', keys: [KEY], node: minted.id });
ok(made.ok, `a VM is made on it (${made.error || made.job})`);
const took = await agent('work', { running: [], wait: 0 });
await agent('result', { job: took.id, state: 'succeeded', exit: 0 });
const VM = { name: `bbvm-alpha-${VMN}`, state: 'stopped', vcpus: 2, mem_mb: 2048, snapshots: [], autostart: false, hw: { cpuset: [], net: 'project', devices: [] }, usb: [] };
await hello([VM]);

// The node's page: the USB section lists the three, each with what holds
// it; the boot stick offers no Give and says why; the controllers say what
// hangs off each and which shares its group with the LAN.
await page.evaluate(id => openNodesTab(id, 'usb'), minted.id);
await page.waitForSelector(`.ndrow[data-node="${minted.id}"]`, { timeout: 15000 });
const ROW = `.ndrow[data-node="${minted.id}"]`;
await openSection(page, 'nodes:usb', ROW);
await page.waitForFunction(sel => document.querySelectorAll(sel + ' .ndusb').length === 3 && document.querySelector(sel + ' .ndusb [data-usbgive]'), ROW, { timeout: 15000 });
const drawn = await page.evaluate(sel => {
  const rows = [...document.querySelectorAll(sel + ' .ndusb')].map(r => ({ text: r.textContent.replace(/\s+/g, ' ').trim(), give: !!r.querySelector('[data-usbgive]'),
    pick: [...(r.querySelector('[data-usbvm]')?.options || [])].map(o => o.value) }));
  const ctls = [...document.querySelectorAll(sel + ' .ndusbctl')].map(r => r.textContent.replace(/\s+/g, ' ').trim());
  const head = document.querySelector(sel + ' details[data-sect="nodes:usb"] summary')?.textContent.replace(/\s+/g, ' ') || '';
  return { rows, ctls, head };
}, ROW);
ok(drawn.rows.length === 3 && /SanDisk Ultra Fit/.test(drawn.rows[0].text) && /serial 4C53/.test(drawn.rows[0].text) && /port 1-3/.test(drawn.rows[0].text)
   && /5 Gb\/s/.test(drawn.rows[0].text) && /free/.test(drawn.rows[0].text) && drawn.rows[0].give && drawn.rows[0].pick.join() === `alpha/${VMN}`,
   `the section lists a device with its serial, port and speed, free, with Give to a VM and the node's VM to pick (${drawn.rows[0].text.slice(0, 120)})`);
ok(/the host/.test(drawn.rows[1].text) && /boots from it/.test(drawn.rows[1].text) && !drawn.rows[1].give,
   `the stick the host boots from is the host's, says so, and offers no Give (${drawn.rows[1].text.slice(0, 120)})`);
ok(/3 devices/.test(drawn.head), `the section's head counts them (${drawn.head.trim()})`);
ok(drawn.ctls.length === 2 && /0000:00:14\.0/.test(drawn.ctls[0]) && /carries SanDisk Ultra Fit, SanDisk Ultra Fit/.test(drawn.ctls[0]) && /The host needs it/.test(drawn.ctls[0])
   && /0000:03:00\.0/.test(drawn.ctls[1]) && /Shares IOMMU group 12 with 0000:03:00\.1/.test(drawn.ctls[1]) && /LAN/.test(drawn.ctls[1]),
   `the controllers say what hangs off each, and the one sharing its group with the LAN says it stays (${drawn.ctls[1].slice(0, 140)})`);

// Give to a VM queues the node's usb-give job with the device named whole.
await page.click(`${ROW} .ndusb[data-usb="0x0781:0x5583"] [data-usbgive]`);
const job = await (async () => { for (let i = 0; i < 40; i++){
  const j = ((await call('/api/v1/jobs?active=1')).jobs || []).find(x => x.type === 'vm' && x.spec?.action === 'usb-give');
  if (j) return j;
  await sleep(250);
} return null; })();
ok(job && job.spec.domain === `bbvm-alpha-${VMN}` && job.spec.usb.serial === '4C53' && job.spec.usb.port === '1-3' && job.spec.usb.name === 'SanDisk Ultra Fit',
   `Give to a VM queues the node's usb-give job, the device named by vendor, product, serial and port (${JSON.stringify(job?.spec?.usb)})`);
const took2 = await agent('work', { running: [], wait: 0 });
await agent('result', { job: took2.id, state: 'succeeded', exit: 0 });

// The node reports the VM holding it: the row says so and offers Take
// back; the VMs page names it on the VM's row.
await hello([{ ...VM, state: 'running', ip: '10.232.0.12', usb: [{ vendor: '0x0781', product: '0x5583', serial: '4C53', port: '1-3', name: 'SanDisk Ultra Fit' }] }]);
await page.evaluate(async () => { await loadVms(); await loadNodes(); });
await page.waitForFunction(([sel, n]) => new RegExp(`alpha/${n} has it now`).test(document.querySelector(sel + ' .ndusb[data-usb="0x0781:0x5583"]')?.textContent || ''), [ROW, VMN], { timeout: 15000 });
const held = await page.evaluate(sel => { const r = document.querySelector(sel + ' .ndusb[data-usb="0x0781:0x5583"]');
  return { text: r.textContent.replace(/\s+/g, ' '), take: !!r.querySelector('[data-usbtake]'), give: !!r.querySelector('[data-usbgive]') }; }, ROW);
ok(new RegExp(`alpha/${VMN} has it now, and at its next start`).test(held.text) && held.take && !held.give,
   `held by the VM, the row says so with now and at its next start, and offers Take back (${held.text.slice(0, 100)})`);
await page.evaluate(() => openVmsTab());
await page.waitForFunction(k => /USB: SanDisk Ultra Fit/.test(document.querySelector(`.vmtab [data-vm-key="alpha/${k}"]`)?.textContent || ''), VMN, { timeout: 15000 });
ok(true, "the VM's row on the VMs page names the device it holds");

// Take back queues usb-take.
await page.evaluate(id => openNodesTab(id, 'usb'), minted.id);
await openSection(page, 'nodes:usb', ROW);
await page.waitForSelector(`${ROW} .ndusb[data-usb="0x0781:0x5583"] [data-usbtake]`, { timeout: 15000 });
await page.click(`${ROW} .ndusb[data-usb="0x0781:0x5583"] [data-usbtake]`);
const back = await (async () => { for (let i = 0; i < 40; i++){
  const j = ((await call('/api/v1/jobs?active=1')).jobs || []).find(x => x.type === 'vm' && x.spec?.action === 'usb-take');
  if (j) return j;
  await sleep(250);
} return null; })();
ok(back && back.spec.usb.serial === '4C53', `Take back queues the node's usb-take job for that device (${JSON.stringify(back?.spec?.usb)})`);
const took3 = await agent('work', { running: [], wait: 0 });
await agent('result', { job: took3.id, state: 'succeeded', exit: 0 });

// The refusals, on the server: the boot stick, a device not here, a
// device another VM holds, and a user who does not administer.
const r1 = await call('/api/vms', { action: 'usb-give', project: 'alpha', name: VMN, usb: { vendor: '0x0781', product: '0x5583', serial: 'BOOT' } });
ok(/boots from it/.test(r1.error || ''), `a device the host boots from is refused with why (${r1.error})`);
const r2 = await call('/api/vms', { action: 'usb-give', project: 'alpha', name: VMN, usb: { vendor: '0x1111', product: '0x2222' } });
ok(/not plugged into usbbox/.test(r2.error || ''), `a device the node does not list is refused (${r2.error})`);

// The Features section offers the IOMMU with Install, saying it is on
// already here; and reports it installed, not on, as restart wanted.
await openSection(page, 'nodes:features', ROW);
await page.waitForSelector(`${ROW} .ndfeat[data-feat="iommu"]`, { timeout: 15000 });
const io = await page.$eval(`${ROW} .ndfeat[data-feat="iommu"]`, e => ({ text: e.textContent.replace(/\s+/g, ' '), btn: e.querySelector('[data-nd="feature"]')?.textContent }));
ok(/IOMMU/.test(io.text) && /not installed/.test(io.text) && /On already, set outside BuilderBot/.test(io.text) && io.btn === 'Install',
   `the Features section offers the IOMMU with Install and says it is on already (${io.text.slice(0, 140)})`);
await hello([VM], { features: { ...CENSUS.features, iommu: { installed: true, on: false } }, vm_host: { ...VM_HOST, iommu: false } });
await page.evaluate(async () => { await loadNodes(); });
await page.waitForFunction(sel => /restart the machine/.test(document.querySelector(sel + ' .ndfeat[data-feat="iommu"]')?.textContent || ''), ROW, { timeout: 15000 });
ok(true, 'installed and not on yet, the row asks for a restart');

// A session's bb vm usb is held for a person whatever the dial says.
await call('/api/prefs', { project: 'alpha', makevms: 'auto' });
const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const SH = { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' };
const asked = await call('/api/vms', { action: 'usb-give', name: VMN, why: 'the stick', usb: { vendor: '0x0781', product: '0x5583', serial: '4C53' } }, SH);
ok(asked.id && !asked.job, `a session's usb-give is held for a person on the bell even at auto (${JSON.stringify(asked).slice(0, 80)})`);
const bell = await call('/api/phone');
const row = (bell.asks || []).find(a => a.id === asked.id);
ok(row && new RegExp(`vm usb ${VMN} give 0781:5583:4C53`).test((row.argv || row.cmd || []).join ? (row.argv || row.cmd).join(' ') : JSON.stringify(row)),
   `the bell shows it as bb vm usb would say it (${JSON.stringify(row?.argv || row?.cmd || row).slice(0, 80)})`);
await call('/api/prefs', { project: 'alpha', makevms: 'deny' });
// The project's Test node (R151 step 1): the settings dialog offers the
// project's nodes beside the session's own, and saving one writes it.
await page.evaluate(() => { document.querySelectorAll('.modal').forEach(m => { m.hidden = true; }); openProjectsTab(); });
await page.evaluate(n => renameProject(n), 'alpha');
await page.waitForSelector('#rnmodal:not([hidden]) #rnTestNode', { timeout: 10000 });
const tn = await page.$eval('#rnTestNode', e => ({ hidden: e.closest('#rnTestNodeF').hidden, opts: [...e.options].map(o => o.value), words: [...e.options].map(o => o.textContent) }));
ok(!tn.hidden && tn.opts.includes(minted.id) && tn.words.some(w => /usbbox/.test(w)) && tn.opts[0] === '',
   `the settings dialog offers the project's nodes as its test node, the session's own first (${tn.words.join(' | ')})`);
await page.selectOption('#rnTestNode', minted.id);
await saveDialog(page);
await refreshUntil(page, new Function(`return ((state.projects || []).find(p => p.name === 'alpha') || {}).prefs?.test_node === ${JSON.stringify(minted.id)}`), { timeout: 20000 }).catch(() => {});
const kept = await page.evaluate(() => ((state.projects || []).find(p => p.name === 'alpha') || {}).prefs?.test_node || '');
ok(kept === minted.id, `...and saving it writes the setting (${kept || 'nothing'})`);
const refused = await call('/api/prefs', { project: 'alpha', test_node: 'n_00000000' });
ok(/one of the project's nodes/.test(refused.error || ''), `a node outside the project's set is refused (${refused.error})`);
await call('/api/prefs', { project: 'alpha', test_node: '' });
await page.evaluate(() => { document.querySelectorAll('.modal').forEach(m => { m.hidden = true; }); });
await call('/api/v1/nodes', { action: 'retire', id: minted.id });
await done(browser);
