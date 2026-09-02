// Phase 3 of the controller design (docs/nodes.md): the agent, enrollment,
// and the numbers. The REAL agent — scripts/agent/builderbot-agent.py — is run
// here as a child process against the harness server, with its node.json
// pointed into the scratch dir: enroll with a token the tab minted, dial in,
// take an exec job, stream its log, report the result, and be cut off. Every
// assertion is a round trip through the channel, which is the thing phase 3
// exists to prove.
import { URL, launch, newPage, ok, done, ready, sleep, DIR } from './lib.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, existsSync, statSync, writeFileSync, mkdirSync, readdirSync, openSync } from 'node:fs';

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
const minted = await api('/api/v1/nodes', { action: 'enroll', name: 'agentbox', user: 'nobody' });
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
// The runner, stood in for: a tarball whose config.sh and svc.sh record
// what they were asked, and a `sudo` on the server's PATH that answers the
// token minter with a fake token — the real one needs the root-only stash.
mkdirSync(`${DIR}/runner-src/bin`, { recursive: true });
writeFileSync(`${DIR}/runner-src/config.sh`, `#!/bin/sh
echo "config $*" >> "$(dirname "$0")/calls.log"
if [ "$1" = remove ]; then rm -f "$(dirname "$0")/.runner"; exit 0; fi
name=; url=
while [ $# -gt 0 ]; do case "$1" in --name) name="$2"; shift;; --url) url="$2"; shift;; esac; shift; done
printf '{"agentName":"%s","gitHubUrl":"%s"}' "$name" "$url" > "$(dirname "$0")/.runner"
`, { mode: 0o755 });
writeFileSync(`${DIR}/runner-src/svc.sh`, `#!/bin/sh
# The real svc.sh resolves everything relative to the working directory and
# refuses anywhere but the runner root. Recorded, because running it from
# elsewhere registered a runner that could never take a job.
[ -f ./config.sh ] && echo "RUNNER_ROOT_OK" >> "$(dirname "$0")/calls.log"
echo "svc $*" >> "$(dirname "$0")/calls.log"
`, { mode: 0o755 });
writeFileSync(`${DIR}/runner-src/run.sh`, '#!/bin/sh\nexit 0\n', { mode: 0o755 });
execFileSync('tar', ['-czf', `${DIR}/runner.tar.gz`, '-C', `${DIR}/runner-src`, '.']);
writeFileSync(`${DIR}/bin/sudo`, `#!/bin/sh
case "$*" in *mint-runner-token*registration*) echo AAAREGTOKEN; exit 0 ;;
             *mint-runner-token*remove*) echo AAAREMOVETOKEN; exit 0 ;; esac
echo "sudo: refused" >&2; exit 1
`, { mode: 0o755 });
// Tailscale, stood in for: `funnel` calls are recorded and reflected in the
// serve status the census reads, so the funnel that is reported is the one
// that was asked for.
writeFileSync(`${DIR}/bin/tailscale`, `#!/usr/bin/env python3
import json, os, sys
st = os.environ.get("BB_TS_STATE", "") or "${DIR}/ts.json"
try: d = json.load(open(st))
except Exception: d = {"funnel": {}}
a = sys.argv[1:]
if a[:2] == ["status", "--json"]:
    print(json.dumps({"Self": {"DNSName": "agentbox.tail1234.ts.net."}})); sys.exit(0)
if a[:3] == ["serve", "status", "--json"]:
    web = {f"agentbox.tail1234.ts.net:{k}": {"Handlers": {"/": {"Proxy": v}}} for k, v in d["funnel"].items()}
    print(json.dumps({"AllowFunnel": {k: True for k in web}, "Web": web})); sys.exit(0)
if a[0] == "funnel":
    open("${DIR}/ts-calls.log", "a").write(" ".join(a) + "\\n")
    if a[-1] == "off": d["funnel"].pop("443", None)
    else: d["funnel"]["443"] = a[-1]
    json.dump(d, open(st, "w")); sys.exit(0)
sys.exit(2)
`, { mode: 0o755 });
// The stub docker's own state, so the agent's compose reaches the same fake
// daemon the controller's runner does — a real node needs nothing here.
const agentEnv = { ...process.env, BUILDERBOT_NODE_JSON: NODE_JSON,
  DOCKER_STUB_STATE: `${DIR}/dockerstate`, PATH: `${DIR}/bin:${process.env.PATH}`,
  BUILDERBOT_TAILSCALE_BIN: `${DIR}/bin/tailscale`,
  BUILDERBOT_RUNNER_DIR: `${DIR}/runner`, BUILDERBOT_RUNNER_TARBALL: `${DIR}/runner.tar.gz`,
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
     && st.capabilities.includes('package-build') && st.capabilities.includes('docker-host')
     && st.stores.data === `${DIR}/agentdata`,
     '...holding the node token, the id it was minted for, and the full capability set it enrolled with');
  ok(/plain http/.test(out), 'plain http is said plainly at enrollment');
  const n = await nodeById(minted.id);
  ok(n.state === 'online' && n.reported.cpu > 0 && n.reported.hostname
     && n.agent.version === '10' && /^sha256:/.test(n.agent.digest),
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

// The agent refuses a system path for a store whatever it is told — the
// same rule the controller applies, made at the resource.
{
  let refused = '';
  try {
    execFileSync('python3', [AGENT, 'enroll', '--controller', URL, '--token', 'bbe_x',
      '--store', 'cache=/etc'], { env: agentEnv, encoding: 'utf8', stdio: 'pipe' });
  } catch (e) { refused = String(e.stderr || '') + String(e.stdout || ''); }
  ok(/system directory/.test(refused),
     `the agent refuses --store cache=/etc at enrollment (${refused.trim().slice(0, 70)})`);
}

// ---- the loop: hello, heartbeat, a job ---------------------------------------
// The agent's output goes to a FILE, never a pipe. A pipe has to be drained
// by this process's event loop, and this file also runs `bb run` and friends
// with execFileSync — which blocks that loop while it waits for a job that
// needs the agent to keep polling. Once the agent had logged 64KB it blocked
// on a write nobody would ever read, the job never started, and the suite
// sat for an hour at the same assertion. A file needs no reader.
const AGENT_LOG_FILE = `${DIR}/agent.log`;
const agentOut = openSync(AGENT_LOG_FILE, 'a');
const agent = spawn('python3', [AGENT, 'run'], { env: agentEnv, stdio: ['ignore', agentOut, agentOut] });
const agentLog = () => { try { return readFileSync(AGENT_LOG_FILE, 'utf8'); } catch { return ''; } };
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
    // Every node enrolls with the whole vocabulary now, so the refusal is
    // shown with a capability outside it: what the door protects is "not
    // what this node enrolled with", not any particular name.
    const forced = await api('/api/v1/nodes', { action: 'exec', id: minted.id,
      argv: ['true'], requires: ['gpu-render'] });
    ok(forced.ok, 'a job requiring something the node lacks is queued — the row does not check');
    const ref = await until(async () => {
      const x = await api(`/api/v1/jobs?id=${forced.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
    });
    ok(ref && ref.state === 'failed' && ref.exit_code === 77 && /not enrolled for gpu-render/.test(ref.log),
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
    // A store is a directory this system creates, fills and empties, so a
    // system path is refused before anybody presses Apply — and again on the
    // node whatever it is told.
    const sys = await api('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { stores: { cache: '/etc' } } });
    const bare = await api('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { stores: { artifacts: '/mnt' } } });
    const inside = await api('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { stores: { data: '/usr/local/x' } } });
    ok(/system directory/.test(sys.error || '') && /system directory/.test(bare.error || '')
       && /inside \/usr/.test(inside.error || ''),
       `a store at /etc, at a bare /mnt, or under /usr is refused (${sys.error})`);
    const cfg = await api('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { mounts: [{ type: 'nfs', source: 'nas:/mnt/user/appdata', path: '/mnt/appdata' },
                         { type: 'virtiofs', source: 'projects', path: '/workspace', ro: true }],
                stores: { cache: `${DIR}/agentcache`, packages: `${DIR}/agentpackages`,
                          artifacts: `${DIR}/agentartifacts` },
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

  // ---- the workspace (phase 6) ----------------------------------------------
  // The tree is edited here and built there: a run snapshots alpha's working
  // tree, dirty edits included, the agent materializes it, the command runs
  // in it, and what the outputs globs match comes back into dist/ with its
  // provenance. A failure keeps the workspace on the node for a look.
  {
    writeFileSync(`${DIR}/ws/alpha/hello.txt`, 'hi from the tree\n');
    mkdirSync(`${DIR}/ws/alpha/dist`, { recursive: true });
    writeFileSync(`${DIR}/ws/alpha/dist/stale.apk`, 'should not travel');
    const nonode = await api('/api/v1/jobs', { action: 'run', project: 'alpha', argv: ['true'] });
    // A project with no node is a normal state: the refusal says what is
    // missing and names the fallback, and never suggests building here.
    ok(/has no node/.test(nonode.error || '') && /settings dialog/.test(nonode.error || '')
       && /Reading and editing the code needs no node/.test(nonode.error || ''),
       `a project with no node set is refused, and told where to set one (${JSON.stringify(nonode).slice(0, 160)})`);
    const onlocal = await api('/api/v1/jobs', { action: 'run', project: 'alpha', node: 'local', argv: ['true'] });
    ok(/runs no agent/.test(onlocal.error || ''), 'local is not a build node — it has no workspace of its own');
    const pr = await api('/api/prefs', { project: 'alpha', node: minted.id,
      build: 'cat hello.txt && mkdir -p out && echo built > out/app-1.0.apk', outputs: ['out/*.apk'] });
    ok(pr.ok && pr.node === minted.id && /hello/.test(pr.build),
       'the project record takes a build node, a build command and its outputs');
    const run = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
      argv: ['sh', '-c', 'cat hello.txt; ls dist 2>/dev/null | wc -l; mkdir -p out; echo built > out/app-1.0.apk; echo notes > out/notes.txt; echo cached > "$BUILDERBOT_CACHE/x"'],
      outputs: ['out/*.apk'] });
    ok(run.ok && /^sha256:[0-9a-f]{64}$/.test(run.snapshot) && run.files > 0 && run.node === minted.id,
       `a run snapshots the tree and queues on the build node (${run.files} files, ${run.snapshot?.slice(0, 19)})`);
    const fin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${run.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(fin && fin.state === 'succeeded' && /hi from the tree/.test(fin.log) && /workspace .*jobs\/j_/.test(fin.log),
       `the agent materializes the snapshot and runs there (${fin?.state}${fin?.state === 'succeeded' ? '' : ': ' + (fin?.error || '') + ' | ' + (fin?.log || '').slice(-400).replace(/\n/g, ' / ')})`);
    ok(fin && /\n0\n/.test(fin.log), '...dist/ stays behind: the snapshot carries the tree, not the shelf');
    ok(fin && fin.source.digest === run.snapshot && fin.source.project === 'alpha',
       '...and the row records the source it was built from');
    ok(existsSync(`${DIR}/ws/alpha/dist/app-1.0.apk`) && !existsSync(`${DIR}/ws/alpha/dist/notes.txt`)
       && readFileSync(`${DIR}/ws/alpha/dist/app-1.0.apk`, 'utf8') === 'built\n',
       `what the outputs match lands in dist/, and nothing else does (${
         (() => { try { return readdirSync(`${DIR}/ws/alpha/dist`).join(','); } catch { return 'no dist'; } })()
       } | ${(fin?.log || '').split('\n').filter(l => /artifact|deliver/.test(l)).join(' / ')})`);
    const prov = JSON.parse(readFileSync(`${DIR}/ws/alpha/dist/.provenance/app-1.0.apk.json`, 'utf8'));
    ok(prov.job === run.job && prov.node === minted.id && prov.source.digest === run.snapshot
       && /^[0-9a-f]{64}$/.test(prov.sha256),
       '...with its provenance beside it: job, node, snapshot, sha256');
    ok(fin && fin.outputs.some(o => o.kind === 'artifact' && o.path === 'dist/app-1.0.apk'),
       '...and the job row lists the artifact it delivered');
    const listed = (await api('/api/artifacts?project=alpha')).artifacts || [];
    ok(listed.some(a => a.name === 'app-1.0.apk' && a.prov?.job === run.job) && !listed.some(a => /provenance/.test(a.path)),
       'the Artifacts listing carries the provenance and hides the record itself');
    ok(!existsSync(`${DIR}/agentdata/jobs/${run.job}`) && existsSync(`${DIR}/agentcache/alpha/x`),
       'a finished workspace is gone; the project cache beside it persists');
    // the same tree again transfers nothing
    const again = await api('/api/v1/jobs', { action: 'run', project: 'alpha', argv: ['true'] });
    const afin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${again.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(again.snapshot === run.snapshot && afin && !/fetching snapshot/.test(afin.log),
       'an unchanged tree makes the same digest, and the node uses its cached copy');
    // a failure keeps the workspace
    const bad = await api('/api/v1/jobs', { action: 'run', project: 'alpha', argv: ['sh', '-c', 'echo boom; exit 3'] });
    const bfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${bad.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    const kept = bfin?.outputs?.find(o => o.kind === 'workspace');
    ok(bfin && bfin.state === 'failed' && kept && existsSync(kept.path) && /kept at/.test(bfin.log),
       `a failed build keeps its workspace on the node and says where (${kept?.path})`);
    // cache-clear is a job too
    const cc = await api('/api/v1/nodes', { action: 'cache-clear', id: minted.id });
    const cfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${cc.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(cfin && cfin.state === 'succeeded' && !existsSync(`${DIR}/agentcache/alpha`),
       'Clear cache drops the project caches through a job');
    const n2 = await nodeById(minted.id);
    ok(typeof n2.reported.stores.cache.used_mb === 'number' && typeof n2.reported.toolchains === 'object',
       'the census reports the cache store\'s size and the toolchains it finds');
    // A command that names a toolchain the node does not report is refused
    // before it is queued, and the two ways out are named.
    {
      // A tool this container genuinely lacks, since the test node's census
      // is this container's — java and node are here, flutter is not.
      const gap = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', 'flutter build apk'] });
      // alpha can push in the fixtures, so the refusal names CI as the way
      // out; the no-push-rights branch says so instead.
      ok(/has no flutter/.test(gap.error || '') && /Tools tab/.test(gap.error || '')
         && /let CI build it/.test(gap.error || ''),
         `a build needing a toolchain the node lacks is refused up front (${gap.error})`);
      const have = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', 'java -version'] });
      ok(have.ok, '...and one the node does report is queued as before');
      if (have.job) await api('/api/v1/jobs', { action: 'cancel', id: have.job });
      const unknown = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', './build.sh'] });
      ok(unknown.ok, '...while a build script that names no toolchain is left alone');
      if (unknown.job) await api('/api/v1/jobs', { action: 'cancel', id: unknown.job });
    }

    // bb run and bb build, from a session's shell
    const port = new globalThis.URL(URL).port;
    const env = { ...process.env, DASHBOARD_AUTH: 'test:test', DASHBOARD_PORT: port,
                  DASHBOARD_STATE: `${DIR}/state`, BB_PROJECT: 'alpha', CLAUDECODE: '1' };
    const out = execFileSync('bash', [`${REPO}/scripts/bb`, 'run', '--node', 'agentbox', '--', 'sh', '-c', 'echo hi from bb run'],
      { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env }).toString();
    ok(/queued on agentbox/.test(out) && /hi from bb run/.test(out) && /succeeded/.test(out),
       'bb run queues on the named node, streams the log and says how it ended');
    const built = execFileSync('bash', [`${REPO}/scripts/bb`, 'build'],
      { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env }).toString();
    ok(/hi from the tree/.test(built) && /into dist\/: app-1.0.apk/.test(built),
       'bb build runs the project\'s build command on its build node and names what came back');
    let failed = '';
    try { execFileSync('bash', [`${REPO}/scripts/bb`, 'test'], { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env, stdio: 'pipe' }); }
    catch (e) { failed = String(e.stderr) + String(e.stdout); }
    ok(/no test command is set/.test(failed), 'bb test with nothing set says what to set, and where');
    const sess = (await api('/api/v1/jobs?project=alpha&n=3')).jobs;
    ok(sess.some(j => j.requested_by === 'session:alpha'), 'a run from a session is attributed to the session');
  }

  // ---- toolchains on a node (phase 6) ----------------------------------------
  // A package install is a job: the bundle (bb, its library, the catalog)
  // travels by digest into the node's packages store and runs there. The
  // package asked for is not installed, so this proves the channel and not
  // a download.
  {
    const pj = await api('/api/packages', { action: 'remove', names: ['flutter'], node: minted.id });
    ok(pj.ok && /^j_/.test(pj.job), `a package job is queued on the node (${pj.job || pj.error})`);
    const pfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${pj.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(pfin && pfin.type === 'package' && /bb .* unpacked into .*agentpackages\/\.bb/.test(pfin.log)
       && /== bb sdk remove flutter/.test(pfin.log) && /not installed|unknown package/.test(pfin.log),
       `the bundle lands in the packages store and bb runs from it there (${pfin?.state}: ${(pfin?.log || '').slice(-500).replace(/\n/g, ' / ')})`);
    ok(existsSync(`${DIR}/agentpackages/.bb/bundle.tar`), '...and stays for the next one');
    const view = await api(`/api/packages?node=${minted.id}`);
    ok(view.node === minted.id && view.root === `${DIR}/agentpackages` && Array.isArray(view.items)
       && view.items.every(i => 'installed' in i),
       'the Tools tab reads that node\'s state: its store, and what its census says it has');
  }

  // ---- the Actions runner as a service on the node (phase 7) ----------------
  {
    const nourl = await api('/api/v1/nodes', { action: 'runner', id: minted.id, want: true, url: 'ftp://nope' });
    ok(/GitHub org or repo URL/.test(nourl.error || ''), 'installing a runner needs the URL it registers with');
    const inst = await api('/api/v1/nodes', { action: 'runner', id: minted.id, want: true,
      labels: ['gpu', 'bad label!'], url: 'https://github.com/example-org' });
    ok(inst.ok && /^j_/.test(inst.job), `Install runner queues a system job (${inst.job || inst.error})`);
    const ifin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${inst.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    const calls = existsSync(`${DIR}/runner/calls.log`) ? readFileSync(`${DIR}/runner/calls.log`, 'utf8') : '';
    ok(ifin && ifin.state === 'succeeded' && /registering agentbox with https:\/\/github.com\/example-org/.test(ifin.log),
       `the agent unpacks the runner and registers it (${ifin?.state}: ${(ifin?.log || '').slice(-200).replace(/\n/g, ' / ')})`);
    ok(/config --unattended --replace --url https:\/\/github.com\/example-org --token AAAREGTOKEN --name agentbox --labels builderbot,self-hosted,linux,x64,agentbox,gpu,badlabel --work _work/.test(calls)
       && /svc install/.test(calls) && /svc start/.test(calls)
       && /RUNNER_ROOT_OK/.test(calls),
       'config.sh gets the minted token, the node\'s name, the default labels plus its own name, and svc.sh installs and starts it');
    ok(!/AAAREGTOKEN/.test(ifin?.log || ''), '...and the token never reaches the job log');
    const rn = await until(async () => { const n = await nodeById(minted.id);
      return n.reported.services?.['actions-runner']?.installed ? n : null; });
    ok(rn && rn.reported.services['actions-runner'].name === 'agentbox'
       && rn.reported.services['actions-runner'].labels.includes('agentbox')
       && rn.services['actions-runner'].want === true,
       'the census reports the runner, its name and labels; the record keeps the ask');
    const labels = execFileSync('bash', [`${REPO}/scripts/bb`, 'ci-labels'],
      { encoding: 'utf8', cwd: REPO, env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
    ok(/^agentbox$/m.test(labels) && /^gpu$/m.test(labels) && /^builderbot$/m.test(labels),
       'bb ci-labels lists the node runner\'s labels beside this box\'s own');
    const rm = await api('/api/v1/nodes', { action: 'runner', id: minted.id, want: false });
    const rfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${rm.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(rfin && rfin.state === 'succeeded' && !existsSync(`${DIR}/runner`) && /runner removed/.test(rfin.log),
       'Remove runner deregisters with a removal token and takes the directory away');
    const rn2 = await until(async () => { const n = await nodeById(minted.id);
      return n.reported.services?.['actions-runner']?.installed === false ? n : null; });
    ok(rn2 !== null, '...and the census says so');
  }

  // ---- emulation as a job (phase 9) --------------------------------------------
  // `bb emu` on the project's node is bb from the bundle with the node's
  // store as its SDK; inputs come from dist/ and what it writes comes back.
  // The store here holds no emulator, so `list` is the verb that proves the
  // plumbing without booting anything.
  {
    const nofile = await api('/api/v1/jobs', { action: 'emu', project: 'alpha', argv: ['emu', 'install', 'x.apk'],
      files: ['dist/missing.apk'] });
    ok(/not a file in alpha's dist/.test(nofile.error || ''), 'an input that is not in dist/ is refused up front');
    const ej = await api('/api/v1/jobs', { action: 'emu', project: 'alpha', argv: ['emu', 'list'] });
    ok(ej.ok && ej.node === minted.id, `bb emu list is queued on the project's node (${ej.job || ej.error})`);
    const efin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${ej.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    // Only the plumbing is asserted: this box has the image's avdmanager on
    // PATH, which a node would not, so what `list` finds here is the box's.
    ok(efin && efin.state === 'succeeded' && /configured API levels/.test(efin.log),
       `the node runs it from the bundle with the store as its SDK (${efin?.state}: ${(efin?.log || '').slice(0, 80).replace(/\n/g, ' / ')})`);
    // inputs and outputs without a snapshot: a file from dist/ arrives by
    // name in the job's directory, and what is written there comes back
    const io = await api('/api/v1/jobs', { action: 'emu', project: 'alpha',
      argv: ['version', '--help'], files: ['dist/app-1.0.apk'], outputs: ['*.txt'] });
    const ifin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${io.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(ifin && /fetched dist\/app-1.0.apk \(6 bytes\) into/.test(ifin.log)
       && existsSync(`${DIR}/agentartifacts/alpha/app-1.0.apk`),
       'an input lands in the node\'s artifacts store, under the project it belongs to');
    // ...and a second run of the same build copies nothing: the node has it.
    const io2 = await api('/api/v1/jobs', { action: 'emu', project: 'alpha',
      argv: ['version', '--help'], files: ['dist/app-1.0.apk'] });
    const i2 = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${io2.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(i2 && /already on this node \(6 bytes\)/.test(i2.log),
       '...and the next run of the same build fetches nothing — the node uses its copy');
    const cli = execFileSync('bash', [`${REPO}/scripts/bb`, 'emu', 'list'],
      { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: { ...process.env, DASHBOARD_AUTH: 'test:test',
        DASHBOARD_PORT: new globalThis.URL(URL).port, DASHBOARD_STATE: `${DIR}/state`, BB_PROJECT: 'alpha' } });
    ok(/bb emu list on agentbox/.test(cli) && /configured API levels/.test(cli) && /succeeded/.test(cli),
       'bb emu from a shell goes to the project\'s node and streams the answer back');
  }

  // ---- Tailscale Funnel, the route's second mode (phase 8) ---------------------
  {
    const n0 = await nodeById(minted.id);
    ok(n0.reported.services.tailscale.installed && n0.reported.services.tailscale.dns === 'agentbox.tail1234.ts.net',
       'the census reports tailscale and the node\'s MagicDNS name');
    const bad = await api('/api/v1/nodes', { action: 'funnel', id: minted.id, port: 'x' });
    ok(/port number/.test(bad.error || ''), 'a funnel wants a port');
    const fj = await api('/api/v1/nodes', { action: 'funnel', id: minted.id, port: 8080 });
    const ffin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${fj.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(ffin && ffin.state === 'succeeded' && /funnel on: https:\/\/agentbox\.tail1234\.ts\.net -> 127\.0\.0\.1:8080/.test(ffin.log)
       && /funnel --bg --https=443 http:\/\/127\.0\.0\.1:8080/.test(readFileSync(`${DIR}/ts-calls.log`, 'utf8')),
       `funnel on is tailscale's own CLI, and the job names the URL (${ffin?.state})`);
    const n1 = await until(async () => { const n = await nodeById(minted.id);
      return n.reported.services.tailscale.funnel?.['443'] === 8080 ? n : null; });
    ok(n1 !== null, '...and the census reports 443 forwarding to it');
    const off = await api('/api/v1/nodes', { action: 'funnel', id: minted.id, port: 8080, on: false });
    const ofin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${off.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(ofin && ofin.state === 'succeeded' && /funnel --https=443 off/.test(readFileSync(`${DIR}/ts-calls.log`, 'utf8')),
       'off is off, through the same CLI');
  }

  // ---- the agent's own update, driven from the tab (roadmap #17) ---------------
  {
    const all = await api('/api/v1/nodes');
    ok(/^sha256:[0-9a-f]{64}$/.test(all.agent?.digest || '') && all.agent.version === '10',
       'the node list carries the agent this controller ships, digest and version');
    const lc = await api('/api/v1/nodes', { action: 'update-agent', id: 'local' });
    ok(/only an agent node/.test(lc.error || ''), 'local has no agent to update');
    const cur = await api('/api/v1/nodes', { action: 'update-agent', id: minted.id });
    ok(cur.ok && cur.current === true && cur.version === '10',
       'a node already on the shipped agent is told so, and no job is queued');
    const n = await nodeById(minted.id);
    ok(n.agent.digest === all.agent.digest, '...because the digests the row would compare are the same');
  }

  // ---- compose runs on the agent, not over ssh (roadmap #18) -----------------
  // The controller sends the plan and the files; the node's own docker runs
  // it. The stub docker records what it was asked, so this proves the argv
  // and the working directory as well as the wiring.
  {
    // agent.mjs runs before devapp.mjs, which is what gives ep.silon its
    // compose file — so this suite writes its own.
    writeFileSync(`${DIR}/ws/ep.silon/docker-compose.yml`,
                  'services:\n  app:\n    image: alpine\n');
    await api('/api/prefs', { project: 'ep.silon', node: minted.id });
    const up = await api('/api/devapp', { project: 'ep.silon', instance: 'main', action: 'up' });
    ok(up.ok || up.started, `Up on an agent node is queued (${up.error || up.job || 'ok'})`);
    // By id, not from the list: the list carries no log (jobs_for omits it).
    const j = await until(async () => {
      const r = await api('/api/v1/jobs?project=ep.silon&type=compose&n=1');
      const one = (r.jobs || [])[0];
      if (!one || !['succeeded', 'failed', 'canceled'].includes(one.state)) return null;
      return api(`/api/v1/jobs?id=${one.id}`);
    }, 60000);
    ok(j && j.node === minted.id && j.spec.plan?.length === 1 && j.spec.plan[0].name === 'starting',
       `the job carries the plan and is placed on the agent node (${j?.spec?.plan?.length} step)`);
    ok(j && j.state === 'succeeded' && /wrote docker-compose.yml/.test(j.log)
       && /\$ .*compose --project-name ep-silon/.test(j.log),
       `the agent writes the compose file and runs docker there (${j?.state}: err=${j?.error} log=${JSON.stringify((j?.log || '(empty)').slice(-300))})`);
    ok(j && /compose for ep-silon in .*\/agentdata\/compose\/ep-silon/.test(j.log),
       '...in a directory of its own under the node\'s data store');
    ok(j && (j.outputs || []).some(o => o.kind === 'compose' && o.steps_done === 1),
       '...and reports how far the plan got, which is what the controller records from');
    await api('/api/prefs', { project: 'ep.silon', node: '' });
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
    // The tab shows one node, chosen in the bar — pick this one before
    // looking for its row.
    await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
    await page.selectOption('.nodestab #ndPick', minted.id);
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
    // One node at a time: the new pending one is in the picker, and its own
    // page says what it is waiting for.
    const opt = await page.$$eval('.nodestab #ndPick option',
      os => os.filter(o => /second/.test(o.textContent)).map(o => o.value));
    ok(opt.length === 1, 'the newly minted node joins the picker');
    await page.selectOption('.nodestab #ndPick', opt[0]);
    await page.waitForFunction(id => /waiting for enrollment/.test(
      document.querySelector(`.nodestab .ndrow[data-node="${id}"]`)?.textContent || ''),
      opt[0], { timeout: 10000 });
    ok(true, 'the pending row says it is waiting for enrollment');
  }

  // revoke: the credential stops working, the agent says so, the row goes quiet
  {
    const r = await api('/api/v1/nodes', { action: 'revoke', id: minted.id });
    ok(r.ok, 'Revoke cuts the credential');
    const said = await until(() => /credential|re-enroll/i.test(agentLog()) ? true : null, 40000);
    ok(said, 'the agent is told its credential is gone and says so in its log');
    const n = await nodeById(minted.id);
    ok(n.agent.revoked && n.state === 'online',
       'the row keeps its history; the state is the operator\'s, the liveness is derived');
    const q = await api('/api/v1/nodes', { action: 'exec', id: minted.id, argv: ['true'] });
    ok(q.error, 'a revoked node takes no job');
  }
} finally {
  agent.kill('SIGTERM');
  if (process.env.AGENT_DEBUG) console.log('AGENT LOG:\n' + agentLog());
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
// Agent nodes only: another suite in the same run may have left an ssh
// node of its own, and that is its business.
const left = (await api('/api/v1/nodes')).nodes;
ok(!left.some(n => n.kind === 'agent') && left.some(n => n.id === 'local'),
   `retired agent nodes leave the list and the store is as it was (${left.map(n => n.name + ':' + n.kind + ':' + n.state).join(', ')})`);

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
