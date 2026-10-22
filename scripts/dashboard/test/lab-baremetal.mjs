// A controller installed bare metal, and the wall around its own node,
// walked on a real machine (roadmap R90 step 9): for each system, a VM made
// on a real VM host, the controller installed in it from a ref of the
// repository with nodes/install-controller.sh, its own node enrolled; then
// what a session there may not reach, each tried and each refused: the
// state, the env file, the secrets stash, the deploy-key agent, the docker
// socket and the controller's loopback terminal port, from the session
// account and the job account outside a view, and from inside a session's
// view built by bb-session; then the wall broken on purpose, and bb-session
// refusing to start a session until it is mended. The VM is removed after.
//
//   BB_LAB_CONTROLLER  the dashboard that makes the VMs, e.g. http://192.168.1.16:7680
//   BB_LAB_TOKEN       "user:password" for an administrator there (the lab's own)
//   BB_LAB_VMHOST      the node with VM host installed that makes the VMs
//   BB_LAB_KEY         an ssh public key for each VM's own account
//   BB_LAB_SSH         the private half's path ON THE VM HOST, readable by its
//                      job account: the walk reaches a VM through jobs there
//   BB_LAB_REF         the ref of github.com/aquilaelabs/builderbot to install
//                      (the branch under test, pushed)
//   BB_LAB_PROJECT     a project there to make the VMs in (hello)
//   BB_LAB_SYSTEMS     the catalog's OS ids, comma-separated (ubuntu-24.04)
//
// Skipped in one line without them, like every lab suite. Slow by nature:
// an install is the image's packages and tools, ten to twenty minutes.
import { ok, done, sleep } from './lib.mjs';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const CTL = (process.env.BB_LAB_CONTROLLER || '').replace(/\/$/, '');
const CRED = process.env.BB_LAB_TOKEN || '';
const HOST = process.env.BB_LAB_VMHOST || '';
const KEY = process.env.BB_LAB_KEY || '';
const SSH = process.env.BB_LAB_SSH || '';
const REF = process.env.BB_LAB_REF || '';
if (!CTL || !CRED || !HOST || !KEY || !SSH || !REF){
  console.log('SKIP  lab-baremetal: BB_LAB_CONTROLLER, BB_LAB_TOKEN, BB_LAB_VMHOST, BB_LAB_KEY, BB_LAB_SSH and BB_LAB_REF are not all set');
  process.exit(0);
}
const PROJECT = process.env.BB_LAB_PROJECT || 'hello';
const SYSTEMS = (process.env.BB_LAB_SYSTEMS || 'ubuntu-24.04').split(',').map(s => s.trim()).filter(Boolean);
// The VM's own account: not builder, which is the node's session account.
const OWNER = 'labowner';
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
const host = ((await api('/api/v1/nodes')).nodes || []).find(n => n.id === HOST || n.name === HOST);
ok(host && host.reported?.features?.vmhost?.installed, `the VM host named is enrolled with VM host installed (${host ? host.name : 'no node called ' + HOST})`);
if (!host){ await done(null); process.exit(0); }

// One job on the VM host, waited for: {state, log}.
const exec = async argv => {
  const r = await api('/api/v1/nodes', { action: 'exec', id: host.id, argv });
  if (!r.job) return { state: 'refused', log: JSON.stringify(r).slice(0, 200) };
  const j = await wait(async () => {
    const s = await api(`/api/v1/jobs?id=${r.job}`);
    return ['succeeded', 'failed', 'canceled'].includes(s.state) ? s : null;
  }, 300000, 3000);
  const log = (await api(`/api/v1/jobs?id=${r.job}&log=1`)).log || '';
  return { state: j?.state || 'timeout', log: Array.isArray(log) ? log.join('\n') : String(log) };
};
// A command as root in the VM, through ssh from the VM host: its output.
const inVm = async (ip, script) => {
  const b64 = Buffer.from(script).toString('base64');
  const r = await exec(['ssh', '-i', SSH, '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
                        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', `${OWNER}@${ip}`,
                        `echo ${b64} | base64 -d | sudo bash -s`]);
  return r.log;
};

// The VM's half, in a shell file of its own: tries(), covers(), outside
// WHO and inside, run by name.
const SH = readFileSync(fileURLToPath(new globalThis.URL('./lab-baremetal.sh', import.meta.url)), 'utf8');

for (const os of SYSTEMS){
  const name = `lab-bm-${os.replace(/[^a-z0-9]+/g, '-')}`.slice(0, 31).replace(/-+$/, '');
  const made = await api('/api/vms', { action: 'new', project: PROJECT, name, os, vcpus: 2, mem_mb: 4096, disk_gb: 24,
                                       keys: [KEY], user: OWNER, node: host.id });
  ok(made.ok, `[${os}] a VM made for a bare-metal controller (${made.error || made.domain})`);
  if (!made.ok) continue;
  try {
    const vm = await wait(async () => ((await api('/api/vms')).vms || []).find(v => v.name === name && v.ip), 15 * 60000);
    ok(vm, `[${os}] it takes an address (${vm?.ip || 'none in 15 minutes: its Screen on the VMs page says why'})`);
    if (!vm) continue;
    const ip = vm.ip;
    const sshUp = await wait(async () => /^up$/m.test(await inVm(ip, 'echo up')), 10 * 60000, 20000);
    ok(sshUp, `[${os}] its own account answers ssh from the VM host`);
    if (!sshUp) continue;

    // The install, from the ref's archive, in the background in the VM, and
    // waited on by its exit file.
    await inVm(ip, SH + '\nstart_install ' + REF + '\n');
    const rc = await wait(async () => {
      const out = await inVm(ip, 'cat /root/install.rc 2>/dev/null || true');
      return /^\d+$/m.test(out) ? out.match(/^(\d+)$/m)[1] : null;
    }, 45 * 60000, 30000);
    const tail = await inVm(ip, 'cat /root/check.rc; tail -25 /root/install.log');
    ok(rc === '0', `[${os}] install-controller.sh --install finishes (exit ${rc ?? 'none in 45 minutes'}): ${tail.slice(-600)}`);
    if (rc !== '0') continue;

    const up = await inVm(ip, SH + '\nstatus\n');
    ok(/^(200|302)$/m.test(up) && /^active$/m.test(up), `[${os}] the controller answers on its port, under its service (${up.replace(/\n/g, ' | ').slice(0, 300)})`);
    ok(/online/.test(up), `[${os}] its own machine is a node of it, online`);

    // The wall: bb-session's own word, once the node has set its sessions'
    // network up (its first hellos).
    const check = await wait(async () => {
      const out = await inVm(ip, '/usr/local/sbin/bb-session check 2>&1; echo "rc=$?"');
      return /rc=0/.test(out) ? out : null;
    }, 10 * 60000, 30000);
    ok(check, `[${os}] bb-session check passes there: the wall holds (${(check || await inVm(ip, '/usr/local/sbin/bb-session check 2>&1')).slice(0, 300)})`);
    const walls = await inVm(ip, 'cat /etc/bb-session.wall; nft list table inet builderbot_wall >/dev/null && echo guard-up');
    ok(/^COVER=.*\/var\/lib\/builderbot-controller/m.test(walls) && /guard-up/.test(walls),
       `[${os}] the wall names the controller's folders and its ports' table is up`);

    // Outside a view: the session account and the job account, each refused
    // every one.
    for (const who of ['builder', 'bb']){
      const out = await inVm(ip, SH + '\noutside ' + who + '\n');
      const reached = out.split('\n').filter(l => l.startsWith('REACHED'));
      const refused = out.split('\n').filter(l => l.startsWith('refused')).length;
      ok(refused >= 10 && !reached.length, `[${os}] as ${who}, outside a view: ${refused} refused, reached ${JSON.stringify(reached)}`);
    }

    // Inside a session's view, built the way a session's is.
    const view = await inVm(ip, SH + '\ninside\n');
    const reachedIn = view.split('\n').filter(l => l.startsWith('REACHED'));
    const refusedIn = view.split('\n').filter(l => l.startsWith('refused')).length;
    ok(refusedIn >= 12 && !reachedIn.length && !/enter-rc=/.test(view),
       `[${os}] inside a session's view: ${refusedIn} refused, reached ${JSON.stringify(reachedIn)} (${view.slice(-300)})`);

    // Broken on purpose: the job account in the docker group, and no
    // session starts until it is out again.
    const broken = await inVm(ip, 'usermod -aG docker bb; /usr/local/sbin/bb-session check 2>&1; echo "rc=$?"; gpasswd -d bb docker >/dev/null; /usr/local/sbin/bb-session check >/dev/null 2>&1; echo "mended=$?"');
    ok(/rc=2/.test(broken) && /job account \(bb\) is in the docker group/.test(broken) && /mended=0/.test(broken),
       `[${os}] the wall broken, bb-session refuses and says why; mended, it starts sessions again (${broken.replace(/\n/g, ' | ').slice(0, 300)})`);
  } finally {
    await api('/api/vms', { action: 'remove', project: PROJECT, name });
  }
}
await done(null);
