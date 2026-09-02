// Phase 3 of the controller design (docs/nodes.md): the agent, enrollment,
// and the numbers. The REAL agent — scripts/agent/builderbot-agent.py — is run
// here as a child process against the harness server, with its node.json
// pointed into the scratch dir: enroll with a token the tab minted, dial in,
// take an exec job, stream its log, report the result, and be cut off. Every
// assertion is a round trip through the channel, which is the thing phase 3
// exists to prove.
import { URL, launch, newPage, ok, done, ready, sleep, DIR } from './lib.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, existsSync, statSync, writeFileSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const AGENT = `${REPO}/scripts/agent/builderbot-agent.py`;
const NODE_JSON = `${DIR}/node.json`;
const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const api = async (path, body) => {
  const r = await fetch(URL.replace(/\/$/, '') + path, body === undefined
    ? { headers: auth }
    : { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify(body) });
  return r.status === 204 ? {} : r.json();
};
const nodeById = async id => (await api('/api/v1/nodes')).nodes.find(n => n.id === id);
const until = async (fn, ms = 15000, step = 200) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ const v = await fn(); if (v) return v; await sleep(step); }
  return null;
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- minting: a pending row, a one-time token -------------------------------
const minted = await api('/api/v1/nodes', { action: 'enroll', name: 'agentbox',
  capabilities: ['docker-host', 'package-build'], user: 'nobody' });
ok(minted.ok && /^bbe_[A-Za-z0-9_-]{20,}$/.test(minted.token) && /^n_/.test(minted.id),
   `Enroll node mints a bbe_ token bound to a new node id (${minted.id})`);
{
  const n = await nodeById(minted.id);
  ok(n && n.kind === 'agent' && n.state === 'pending' && n.live === false,
     'the row exists first, as pending: the token can only become that node');
  const list = await api('/api/v1/nodes');
  ok(!list.nodes.some(x => JSON.stringify(x).includes(minted.token.slice(4))),
     'the token itself is never on a row — only its hash is stored');
}
// ...and the download the provisioner does, with the enroll token
{
  const r = await fetch(URL.replace(/\/$/, '') + '/api/v1/agent/download',
    { headers: { Authorization: 'Bearer ' + minted.token } });
  const body = await r.text();
  ok(r.status === 200 && body === readFileSync(AGENT, 'utf8')
     && /^sha256:[0-9a-f]{64}$/.test(r.headers.get('x-agent-digest')),
     'the enroll token downloads the agent the controller ships, digest in a header');
  const bad = await fetch(URL.replace(/\/$/, '') + '/api/v1/agent/download',
    { headers: { Authorization: 'Bearer bbe_nonsense' } });
  ok(bad.status === 401, '...and a made-up token gets nothing');
}

// ---- enrolling: the real agent, once ---------------------------------------
// The configuration plane's two tools, stood in for (phase 5): bb-sandbox as
// a JSON list the same verbs edit, and netplan as a log of what was applied.
// Neither needs root; what the agent does with them is what is under test.
const SANDBOX_STATE = `${DIR}/sandbox-mounts.json`;
writeFileSync(`${DIR}/bin/bb-sandbox`, `#!/usr/bin/env python3
import json, os, sys
f = os.environ["BB_SANDBOX_STATE"]
try: ms = json.load(open(f))
except Exception: ms = []
a = sys.argv[1:]
def save(): json.dump(ms, open(f, "w"))
if a[:2] == ["list", "--json"]: print(json.dumps(ms)); sys.exit(0)
if a[0] in ("add-nfs", "add-share"):
    spec = a[1]; ro = spec.endswith(":ro"); spec = spec[:-3] if ro else spec
    if a[0] == "add-nfs":
        host, rest = spec.split(":", 1); exp, path = rest.split(":", 1); src = host + ":" + exp; t = "nfs"
    else:
        src, path = spec.split(":", 1); t = "virtiofs"
    ms = [m for m in ms if m["path"] != path]
    ms.append({"path": path, "source": src, "type": t, "opts": "defaults" + (",ro" if ro else ""),
               "ro": ro, "mounted": True, "real": src, "appdata": False})
    save(); print(f"fstab: {path} now comes from {src}"); sys.exit(0)
if a[0] == "remove":
    ms = [m for m in ms if m["path"] != a[1]]; save(); print(f"{a[1]} is no longer mounted at boot"); sys.exit(0)
print("unknown", a, file=sys.stderr); sys.exit(2)
`, { mode: 0o755 });
writeFileSync(`${DIR}/bin/netplan`, `#!/bin/sh
echo "$*" >> "${DIR}/netplan.log"
`, { mode: 0o755 });
const agentEnv = { ...process.env, BUILDERBOT_NODE_JSON: NODE_JSON,
  BUILDERBOT_SANDBOX_BIN: `${DIR}/bin/bb-sandbox`, BB_SANDBOX_STATE: SANDBOX_STATE,
  BUILDERBOT_NETPLAN_BIN: `${DIR}/bin/netplan`, BUILDERBOT_NETPLAN_DIR: `${DIR}/netplan` };
{
  let out = '';
  try {
    out = execFileSync('python3', [AGENT, 'enroll', '--controller', URL,
      '--token', minted.token, '--user', process.env.USER || 'builder',
      '--store', `data=${DIR}/agentdata`], { env: agentEnv, encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (e) { out = String(e.stdout) + String(e.stderr); }
  ok(/enrolled as node n_/.test(out) && existsSync(NODE_JSON)
     && (statSync(NODE_JSON).mode & 0o777) === 0o600,
     `builderbot-agent enroll writes node.json, mode 0600 (${out.split('\n')[0]})`);
  const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
  ok(st.node_id === minted.id && /^bbn_/.test(st.token)
     && st.capabilities.includes('package-build') && st.stores.data === `${DIR}/agentdata`,
     '...holding the node token, the id it was minted for, and the enrolled capabilities');
  ok(/plain http/.test(out), 'plain http is said plainly at enrollment');
  const n = await nodeById(minted.id);
  ok(n.state === 'online' && n.reported.cpu > 0 && n.reported.hostname
     && n.agent.version === '3' && /^sha256:/.test(n.agent.digest),
     'the row is online with the census, agent version and digest');
  // single use
  let again = '';
  try {
    execFileSync('python3', [AGENT, 'enroll', '--controller', URL,
      '--token', minted.token], { env: { ...agentEnv, BUILDERBOT_NODE_JSON: NODE_JSON + '.2' },
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (e) { again = String(e.stderr); }
  ok(/refused/.test(again) && !existsSync(NODE_JSON + '.2'),
     'the enroll token is single-use: a second enrollment is refused');
}

// ---- the loop: hello, heartbeat, a job ---------------------------------------
const agent = spawn('python3', [AGENT, 'run'], { env: agentEnv, stdio: ['ignore', 'pipe', 'pipe'] });
let agentLog = '';
agent.stderr.on('data', d => { agentLog += d; });
agent.stdout.on('data', d => { agentLog += d; });
try {
  const live = await until(async () => {
    const n = await nodeById(minted.id);
    return n && n.live && n.reported.sample ? n : null;
  });
  ok(live !== null, 'the agent dials in: the row is live and carries a sample');
  const s = live?.reported?.sample || {};
  ok(typeof s.cpu_pct === 'number' && s.mem_mb > 0 && s.mem_used_mb > 0
     && s.stores && 'data' in s.stores && s.running === 0,
     `...with cpu, memory and per-store headroom riding the heartbeat (cpu ${s.cpu_pct}%, ${
       s.mem_used_mb}/${s.mem_mb}MB, data free ${s.stores?.data}MB)`);
  ok(live?.agent?.addr === '127.0.0.1',
     'the address the node dialed in from is on the row');

  // an exec job, end to end
  const j = await api('/api/v1/nodes', { action: 'exec', id: minted.id,
    argv: ['sh', '-c', 'echo hello from $BUILDERBOT_NODE; echo two >&2; exit 3'] });
  ok(j.ok && /^j_/.test(j.job), `exec queues a job (${j.job})`);
  const fin = await until(async () => {
    const r = await api(`/api/v1/jobs?id=${j.job}`);
    return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
  });
  ok(fin && fin.state === 'failed' && fin.exit_code === 3,
     `the agent runs it and reports the exit code (${fin?.state}, exit ${fin?.exit_code})`);
  ok(fin && fin.log.includes(`hello from ${minted.id}`) && fin.log.includes('two'),
     'stdout and stderr both reach the log, in order, with the node id in the env');
  ok(fin && fin.node === minted.id && fin.type === 'exec' && fin.started && fin.ended,
     '...and the job row records where it ran and when');

  // a job needing a capability the node was not enrolled with is refused there
  {
    const forced = await api('/api/v1/nodes', { action: 'exec', id: minted.id,
      argv: ['true'], requires: ['deploy-target'] });
    ok(forced.ok, 'a job requiring deploy-target is queued — the row does not check');
    const ref = await until(async () => {
      const x = await api(`/api/v1/jobs?id=${forced.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
    });
    ok(ref && ref.state === 'failed' && ref.exit_code === 77 && /not enrolled for deploy-target/.test(ref.log),
       'the NODE refuses a job for a capability it did not enroll with (door 7)');
  }

  // cancel: the flag on the row reaches the agent, which kills the job and
  // reports it canceled rather than failed (phase 4)
  {
    const q = await api('/api/v1/nodes', { action: 'exec', id: minted.id,
      argv: ['sh', '-c', 'echo running; sleep 60'] });
    const running = await until(async () => {
      const x = await api(`/api/v1/jobs?id=${q.job}`);
      return x.state === 'running' && /running/.test(x.log) ? x : null;
    });
    ok(running !== null, 'a long job on the agent reaches running with its first line logged');
    const c = await api('/api/v1/jobs', { action: 'cancel', id: q.job });
    ok(c.ok, 'Cancel is accepted while it runs');
    const fin = await until(async () => {
      const x = await api(`/api/v1/jobs?id=${q.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
    }, 40000);
    ok(fin && fin.state === 'canceled' && /stopped by the operator/.test(fin.error)
       && fin.ended - fin.started < 40,
       `the agent kills it and reports canceled (${fin?.state}: ${fin?.error})`);
    const n = await nodeById(minted.id);
    ok(n.os === 'linux' && n.arch === process.arch.replace('x64', 'x86_64').replace('arm64', 'aarch64'),
       `the census reports os and arch as fields the selector can match (${n.os}/${n.arch})`);
  }

  // ---- the configuration plane (phase 5) -----------------------------------
  // Desired config on the record, a system job the agent applies through
  // bb-sandbox, and the census reporting what was applied.
  {
    const before = await nodeById(minted.id);
    ok(before.reported.sandbox === true && Array.isArray(before.reported.mounts)
       && before.reported.network && Array.isArray(before.reported.network.dns),
       'the census says the node is a sandbox and reports its mounts and address');
    const refused = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
    ok(/save a configuration first/.test(refused.error || ''),
       'apply with nothing saved is refused, saying so');
    const badcfg = await api('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { mounts: [{ type: 'nfs', source: 'nas', path: '/mnt/x' }] } });
    ok(/HOST:\/export/.test(badcfg.error || ''), `a malformed mount is refused at the record (${badcfg.error})`);
    const cfg = await api('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { mounts: [{ type: 'nfs', source: 'nas:/mnt/user/appdata', path: '/mnt/appdata' },
                         { type: 'virtiofs', source: 'projects', path: '/workspace', ro: true }],
                stores: { cache: `${DIR}/agentcache` },
                network: { mode: 'static', address: '10.9.9.9/24', gateway: '10.9.9.1', dns: ['10.9.9.1'] } } });
    ok(cfg.ok && cfg.desired.mounts.length === 2 && cfg.desired.network.mode === 'static',
       'a desired config is validated and kept on the record');
    const local = await api('/api/v1/nodes', { action: 'apply', id: 'local', what: 'storage' });
    ok(/only an agent node/.test(local.error || ''), 'the local node has no configuration plane');

    const ap = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
    ok(ap.ok && /^j_/.test(ap.job), `apply storage queues a system job (${ap.job || ap.error})`);
    const twice = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'network' });
    ok(/one at a time/.test(twice.error || ''), '...and a second apply waits for it');
    const fin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${ap.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(fin && fin.state === 'succeeded' && /add-nfs nas:\/mnt\/user\/appdata:\/mnt\/appdata/.test(fin.log)
       && /add-share projects:\/workspace:ro/.test(fin.log) && /cache store/.test(fin.log),
       `the agent applies it through bb-sandbox and the stores, logging each step (${fin?.state})`);
    const stubState = JSON.parse(readFileSync(SANDBOX_STATE, 'utf8'));
    ok(stubState.length === 2 && stubState.some(m => m.path === '/workspace' && m.ro),
       '...and the node now has both mounts, the read-only one read-only');
    const after = await until(async () => {
      const n = await nodeById(minted.id);
      return n.reported.mounts.length === 2 ? n : null;
    });
    ok(after !== null && after.reported.mounts.every(m => m.mounted)
       && after.reported.stores.cache.path === `${DIR}/agentcache`,
       'the census reports the applied mounts and the moved store right away, not at the next hello');
    ok(after && after.applying === null, '...and the row is no longer applying');

    // network: written, applied, dialed back — the stub controller is still here
    const np = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'network' });
    const nfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${np.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    const yaml = readFileSync(`${DIR}/netplan/90-builderbot.yaml`, 'utf8');
    ok(nfin && nfin.state === 'succeeded' && /dialed back in/.test(nfin.log)
       && /addresses: \[10\.9\.9\.9\/24\]/.test(yaml) && /via: 10\.9\.9\.1/.test(yaml)
       && /^apply$/m.test(readFileSync(`${DIR}/netplan.log`, 'utf8')),
       `a network change is written to netplan, applied, and confirmed by dialing back (${nfin?.state})`);
    const again = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'network' });
    const afin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${again.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(afin && afin.state === 'succeeded' && /already applied/.test(afin.log),
       '...and applying the same config again changes nothing');
  }

  // Test on an agent node is a round trip through the channel
  {
    const t = await api('/api/v1/nodes', { action: 'test', id: minted.id });
    ok(t.on === true && /Linux/.test(t.why),
       `Test on an agent node runs uname there and shows the answer (${t.why})`);
  }

  // drain: queued work waits
  {
    await api('/api/v1/nodes', { action: 'drain', id: minted.id });
    const q = await api('/api/v1/nodes', { action: 'exec', id: minted.id, argv: ['true'] });
    ok(q.error && /draining/.test(q.error),
       'a draining node takes no new job — refused at the queue, not left waiting');
    await api('/api/v1/nodes', { action: 'online', id: minted.id });
  }

  // the tab, on a live agent node
  {
    await page.evaluate(() => { const c = document.getElementById('cardTools');
      if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
    await page.click('#bNodes');
    await page.waitForSelector(`.nodestab .ndrow[data-node="${minted.id}"] .ndlive`,
                               { timeout: 15000 });
    const row = await page.$eval(`.nodestab .ndrow[data-node="${minted.id}"]`,
                                 e => e.textContent.replace(/\s+/g, ' '));
    ok(/agentbox/.test(row) && /live/.test(row) && /cpu/.test(row) && /data/.test(row)
       && new RegExp(`jobs run as ${process.env.USER || 'builder'}`).test(row),
       `the row shows the agent live, its numbers and the account jobs run as (${row.slice(0, 160)}…)`);
    ok(await page.$(`.nodestab .ndrow[data-node="${minted.id}"] [data-nd="revoke"]`) !== null,
       '...and offers Revoke, which an ssh node does not have');
    // the enroll form shows the command, once
    await page.click('#ndEnroll');
    await page.fill('#ndEnName', 'second');
    await page.click('#ndEnGo');
    await page.waitForSelector('.nodestab .ndtoken', { timeout: 15000 });
    const shown = await page.$eval('.nodestab .ndtoken', e => e.textContent);
    ok(/bbe_/.test(shown) && /provision\.sh/.test(shown) && /--controller/.test(shown),
       'Enroll node shows the one-time token inside the provisioner command');
    const pend = await page.$$eval('.nodestab .ndrow', rs =>
      rs.filter(r => /second/.test(r.textContent) && /waiting for enrollment/.test(r.textContent)).length);
    ok(pend === 1, 'the pending row says it is waiting for enrollment');
  }

  // revoke: the credential stops working, the agent says so, the row goes quiet
  {
    const r = await api('/api/v1/nodes', { action: 'revoke', id: minted.id });
    ok(r.ok, 'Revoke cuts the credential');
    const said = await until(() => /credential|re-enroll/i.test(agentLog) ? true : null, 40000);
    ok(said, 'the agent is told its credential is gone and says so in its log');
    const n = await nodeById(minted.id);
    ok(n.agent.revoked && n.state === 'online',
       'the row keeps its history; the state is the operator\'s, the liveness is derived');
    const q = await api('/api/v1/nodes', { action: 'exec', id: minted.id, argv: ['true'] });
    ok(q.error, 'a revoked node takes no job');
  }
} finally {
  agent.kill('SIGTERM');
  if (process.env.AGENT_DEBUG) console.log('AGENT LOG:\n' + agentLog);
}

// bb nodes shows liveness
{
  const out = execFileSync('bash', ['scripts/bb', 'nodes'],
    { encoding: 'utf8', cwd: REPO, env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  ok(/agentbox/.test(out) && /agent/.test(out),
     'bb nodes lists the agent node');
}

// Retire what this file made: the rows stay as history (door 1) and leave
// every list, which is what the files after this one expect to find — a
// store holding local and the sandbox and nothing else.
for (const n of (await api('/api/v1/nodes')).nodes)
  if (n.kind === 'agent') await api('/api/v1/nodes', { action: 'retire', id: n.id });
ok((await api('/api/v1/nodes')).nodes.length === 2,
   'retired agent nodes leave the list and the store is as it was');

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
// ---- the network revert, without a network to cut ---------------------------
// The confirm half of commit/confirm: a controller that does not answer from
// the new address puts the old file back and applies it again. Driven on the
// module directly, with hello stubbed to fail, because the real path needs
// an address that goes nowhere.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys, tempfile, time
os.environ['BUILDERBOT_NETPLAN_DIR'] = d = tempfile.mkdtemp()
os.environ['BUILDERBOT_NETPLAN_BIN'] = ${JSON.stringify(`${DIR}/bin/netplan`)}
os.environ['BUILDERBOT_SANDBOX_BIN'] = ${JSON.stringify(`${DIR}/bin/bb-sandbox`)}
log = ${JSON.stringify(`${DIR}/netplan.log`)}
applied_before = open(log).read().count('apply')
spec = importlib.util.spec_from_file_location('agent', ${JSON.stringify(AGENT)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.DIAL_BACK_S = 1
open(d + '/90-builderbot.yaml', 'w').write('network:\\n  version: 2\\n  ethernets:\\n    eth0:\\n      dhcp4: true\\n')
a = m.Agent.__new__(m.Agent)
a.state = {'stores': {}}
a.hello = lambda: (503, {'error': 'unreachable'})
class J:
    lines = []
    def say(self, t): self.lines.append(t)
    def flush(self): pass
j = J()
st, code = a._apply_network(j, {'network': {'mode': 'static', 'address': '10.1.1.5/24', 'gateway': '10.1.1.1', 'interface': 'eth0'}})
print(json.dumps({'state': st, 'code': code, 'log': ''.join(j.lines),
                  'file': open(d + '/90-builderbot.yaml').read(),
                  'applies': open(log).read().count('apply') - applied_before}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(R.state === 'failed' && /reverting/.test(R.log) && /reverted/.test(R.log),
     `a network change the controller cannot confirm is reverted (${R.state})`);
  ok(/dhcp4: true/.test(R.file) && !/10\.1\.1\.5/.test(R.file) && R.applies === 2,
     '...the previous file is back and applied a second time');
}

await done(browser);
