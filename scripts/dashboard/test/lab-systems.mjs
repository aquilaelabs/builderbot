// Every Linux system Enroll node offers, walked on a real machine (roadmap
// R97 step 5): for each, a VM made a node on a real VM host, then what a
// node does (toolchains, features, nginx, storage, a project synced, a
// terminal), then Uninstall and the VM gone. What the vetted note in
// systems.py says was walked is what this runs, so a change to the
// provisioner is proved on every system again before a release.
//
//   BB_LAB_CONTROLLER  the dashboard to ask, e.g. http://controller.lan:7680
//   BB_LAB_TOKEN       "user:password" for an administrator there (the lab's own)
//   BB_LAB_VMHOST      the node with VM host installed that makes the VMs
//   BB_LAB_PROJECT     a project there to make them in and to move onto each (hello)
//   BB_LAB_HOME        that project's own node, which it goes back to (the VM host)
//   BB_LAB_KEY         an ssh public key for the VMs' own account
//   BB_LAB_SYSTEMS     the catalog's OS ids, comma-separated (every Linux one)
//
// Skipped in one line without them, like every lab suite. Slow by nature:
// each system boots, provisions itself and walks for ten to twenty minutes.
import { get } from 'node:http';
import { ok, done, sleep } from './lib.mjs';

const CTL = (process.env.BB_LAB_CONTROLLER || '').replace(/\/$/, '');
const CRED = process.env.BB_LAB_TOKEN || '';
const HOST = process.env.BB_LAB_VMHOST || '';
const KEY = process.env.BB_LAB_KEY || '';
if (!CTL || !CRED || !HOST || !KEY){
  console.log('SKIP  lab-systems: BB_LAB_CONTROLLER, BB_LAB_TOKEN, BB_LAB_VMHOST and BB_LAB_KEY are not all set');
  process.exit(0);
}
const PROJECT = process.env.BB_LAB_PROJECT || 'hello';
const auth = 'Basic ' + Buffer.from(CRED).toString('base64');
const api = async (path, body) => {
  const r = await fetch(CTL + path, body === undefined
    ? { headers: { Authorization: auth } }
    : { method: 'POST', headers: { Authorization: auth, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const text = await r.text();
  try { return { status: r.status, ...JSON.parse(text) }; } catch { return { status: r.status, raw: text.slice(0, 300) }; }
};
const wait = async (fn, ms, every = 15000) => {
  const until = Date.now() + ms;
  for (;;){
    try { const got = await fn(); if (got) return got; } catch { /* the controller restarting */ }
    if (Date.now() > until) return null;
    await sleep(every);
  }
};
const nodes = async () => (await api('/api/v1/nodes')).nodes || [];
const host = (await nodes()).find(n => n.id === HOST || n.name === HOST);
ok(host && host.reported?.features?.vmhost?.installed, `the VM host named is enrolled with VM host installed (${host ? host.name : 'no node called ' + HOST})`);
if (!host){ await done(null); process.exit(0); }
const home = process.env.BB_LAB_HOME || host.id;
const catalog = ((await api('/api/vms')).images || []).filter(i => !i.person).map(i => i.id);
const SYSTEMS = (process.env.BB_LAB_SYSTEMS || catalog.join(',')).split(',').map(s => s.trim()).filter(Boolean);

// One job on a node, waited for, its log's end.
const exec = async (nid, argv) => {
  const r = await api('/api/v1/nodes', { action: 'exec', id: nid, argv });
  if (!r.job) return 'exec refused: ' + JSON.stringify(r).slice(0, 200);
  await wait(async () => ['succeeded', 'failed', 'canceled'].includes((await api(`/api/v1/jobs?id=${r.job}`)).state), 180000, 3000);
  return (await api(`/api/v1/jobs?id=${r.job}&log=1`)).log || '';
};

for (const os of SYSTEMS){
  const name = `lab-${os.replace(/[^a-z0-9]+/g, '-')}`.slice(0, 31).replace(/-+$/, '');
  const made = await api('/api/vms', { action: 'new', project: PROJECT, name, os, vcpus: 2, mem_mb: 2560, disk_gb: 16,
                                       keys: [KEY], node: host.id, node_agent: true, ctl: CTL });
  ok(made.ok, `[${os}] a VM made a node (${made.error || made.domain})`);
  if (!made.ok) continue;
  // Failed at once, not after 45 minutes, when the VM never takes an
  // address (R107: Gentoo's image sat at its boot loader, and the walk
  // waited the whole time): its Screen on the VMs page shows why.
  const started = Date.now();
  let stuck = '';
  const row = await wait(async () => {
    const r = (await nodes()).find(n => n.name === `${PROJECT}-${name}` && n.state === 'online');
    if (r) return r;
    if (Date.now() - started > 15 * 60000){
      const v = ((await api('/api/vms')).vms || []).find(x => x.name === name) || {};
      const enrolled = (await nodes()).some(n => n.name === `${PROJECT}-${name}`);
      if (!v.ip && !enrolled){ stuck = 'no address and no enrollment after 15 minutes: its Screen on the VMs page shows where it stopped'; return { stuck }; }
    }
    return null;
  }, 45 * 60000);
  ok(!!row && !row.stuck, `[${os}] it enrolls and dials in on its own address (${row?.stuck ? stuck : row ? row.agent?.addr : 'not online in 45 minutes'})`);
  if (row?.stuck){
    await api('/api/vms', { action: 'remove', project: PROJECT, name });
    await wait(async () => !((await api('/api/vms')).vms || []).some(v => v.name === name), 10 * 60000);
    continue;
  }
  if (row){
    const nid = row.id;
    // Toolchains in and out.
    for (const [action, want] of [['install', true], ['remove', false]]){
      await api('/api/toolchains', { action, names: ['node'], node: nid });
      const d = await wait(async () => { const t = await api(`/api/toolchains?node=${nid}`); return t.job?.running ? null : t; }, 30 * 60000);
      // An item says whether it is installed (B194: it has no state).
      const it = (d?.items || []).find(i => i.name === 'node');
      ok(it?.installed === want, `[${os}] a toolchain ${action}s (${it ? `installed ${it.installed}${it.version ? ` ${it.version}` : ''}` : 'no node item'}${d?.job?.errors ? `; ${JSON.stringify(d.job.errors).slice(0, 200)}` : ''})`);
    }
    // A container from a compose file: nginx, deployed and taken off.
    for (const action of ['deploy', 'remove']){
      const asked = await api('/api/nginx', { action, node: nid });
      if (asked.error){ ok(false, `[${os}] nginx ${action === 'deploy' ? 'runs as a container there' : 'comes off again'} (${asked.error})`); continue; }
      const x = await wait(async () => {
        const n = ((await api('/api/nginx')).nodes || []).find(v => v.node === nid) || {};
        return !(n.state?.job?.running) && (action === 'deploy') === !!n.deployed ? n : null;
      }, 20 * 60000);
      // deployed says the container is this node's; running, that it runs.
      const up = !!x?.state?.running;
      ok(!!x && up === (action === 'deploy'), `[${os}] nginx ${action === 'deploy' ? 'runs as a container there' : 'comes off again'}${x && up !== (action === 'deploy') ? ` (running ${up})` : ''}`);
    }
    // The Features section's installs where they apply (R107 step 3): VM
    // host where the machine has /dev/kvm (a VM made on a host that passes
    // virtualization through), the IOMMU on an Intel or AMD machine, each
    // installed and removed as a system job; the hosting firewall is a
    // hosting-only node's and this one runs sessions, and a GPU driver
    // needs a card, so each of those is said as not applying rather than
    // skipped in silence. A reboot is never asked for here: the IOMMU's
    // line is checked as written, not as booted.
    {
      const feat = async (fid, op) => {
        const r = await api('/api/v1/nodes', { action: 'feature', id: nid, feature: fid, op });
        if (r.error) return { error: r.error };
        const j = await wait(async () => { const x = await api(`/api/v1/jobs?id=${r.job}`); return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null; }, 30 * 60000, 5000);
        const fe = await wait(async () => { const n = (await nodes()).find(x => x.id === nid); const f = n?.reported?.features?.[fid];
          return f && !!f.installed === (op === 'install') ? f : null; }, 5 * 60000, 5000);
        return { state: j?.state, feature: fe };
      };
      const rep = (await nodes()).find(n => n.id === nid)?.reported || {};
      const kvm = !!rep.features?.vmhost?.kvm;
      if (kvm){
        for (const op of ['install', 'remove']){
          const r = await feat('vmhost', op);
          ok(r.state === 'succeeded' && !!r.feature, `[${os}] VM host ${op}s from the Features section (${r.error || r.state}${r.feature?.libvirt ? `, libvirt ${r.feature.libvirt}` : ''})`);
        }
      } else {
        ok(true, `[${os}] VM host does not apply here: no /dev/kvm (its host passes no virtualization through)`);
      }
      if (/^(x86_64|amd64)/.test(rep.arch || '')){
        for (const op of ['install', 'remove']){
          const r = await feat('iommu', op);
          ok(r.state === 'succeeded' && !!r.feature, `[${os}] the IOMMU's kernel line ${op === 'install' ? 'is written' : 'comes off'} from the Features section (${r.error || r.state})`);
        }
      } else {
        ok(true, `[${os}] the IOMMU switch does not apply here: ${rep.arch || 'another architecture'}`);
      }
      ok(true, `[${os}] the hosting firewall does not apply here: this node runs sessions, and a GPU driver needs a card (${rep.gpu_card ? 'one reported' : 'none reported'})`);
    }
    // Its disks measured on the Storage page (R107: storage, as R97's step
    // 2 named): Measure now runs, and the page lists the node's filesystems.
    const meas = await api('/api/v1/nodes', { action: 'storage', id: nid });
    if (meas.job) await wait(async () => ['succeeded', 'failed', 'canceled'].includes((await api(`/api/v1/jobs?id=${meas.job}`)).state), 10 * 60000, 5000);
    const st = await wait(async () => {
      const v = await api('/api/storage');
      const n = (v.nodes || []).find(x => x.id === nid || x.node === nid);
      return n && (n.filesystems || []).length ? n : null;
    }, 5 * 60000, 10000);
    ok(!!st, `[${os}] Storage measures its disks (${st ? (st.filesystems || []).length + ' filesystems' : meas.error || 'nothing measured'})`);
    // A project there: synced, and a terminal through the controller.
    await api('/api/prefs', { project: PROJECT, node: nid });
    const synced = await wait(async () => Object.entries((await nodes()).find(n => n.id === nid)?.reported?.sync || {})
      .some(([k, v]) => k === PROJECT && v?.ready), 20 * 60000);
    ok(!!synced, `[${os}] ${PROJECT} syncs there`);
    ok(/README|\.git/.test(await exec(nid, ['sh', '-c', `ls -a /workspace/${PROJECT}`])), `[${os}] ...and its files are on the machine`);
    // What a terminal there would be, asked plainly: one that opens is told
    // to ask for its websocket. node:http, not fetch (B196).
    const page = await new Promise(res => get(`${CTL}/termws?arg=sh:1:${PROJECT}`, { headers: { Authorization: auth } }, r => {
      let b = ''; r.setEncoding('utf8'); r.on('data', c => { b += c; }); r.on('end', () => res(b)); r.on('error', e => res(String(e)));
    }).on('error', e => res(String(e))));
    ok(/a websocket is asked for here/.test(page), `[${os}] a terminal there opens through the controller (${page.slice(0, 120)})`);
    await api('/api/prefs', { project: PROJECT, node: home, nodes: [home] });
    // Uninstall: the row retired, nothing of BuilderBot's left.
    await api('/api/v1/nodes', { action: 'uninstall', id: nid });
    const gone = await wait(async () => !(await nodes()).some(n => n.id === nid && n.state !== 'retired'), 20 * 60000);
    ok(!!gone, `[${os}] Uninstall takes it off the Nodes page`);
  }
  await api('/api/vms', { action: 'remove', project: PROJECT, name });
  await wait(async () => !((await api('/api/vms')).vms || []).some(v => v.name === name), 10 * 60000);
}
await done(null);
