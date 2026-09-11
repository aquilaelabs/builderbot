// Phase 3 of the controller design (docs/nodes.md): the agent, enrollment,
// and the numbers. The REAL agent — scripts/agent/builderbot-agent.py — is run
// here as a child process against the harness server, with its node.json
// pointed into the scratch dir: enroll with a token the tab minted, dial in,
// take an exec job, stream its log, report the result, and be cut off. Every
// assertion is a round trip through the channel, which is the thing phase 3
// exists to prove.
import { URL, launch, newPage, ok, done, ready, sleep, refreshUntil, DIR,
         tmuxNew, tmuxKill, tmuxFmt, tmuxCapture } from './lib.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, existsSync, statSync, lstatSync, readlinkSync, writeFileSync, mkdirSync, readdirSync, openSync, rmSync, realpathSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const AGENT = `${REPO}/scripts/agent/builderbot-agent.py`;
// The packages store is scoped by platform (roadmap R19): a machine's
// packages live under <store>/<os>-<arch>, so every fixture written INTO a
// store goes there, while the store's own path — the setting — stays the
// share. The agent moves a flat store into the scope once; these fixtures
// are written after it starts, so they are written scoped from the start.
const SCOPE = `linux-${execFileSync('uname', ['-m'], { encoding: 'utf8' }).trim()}`;
const PK = `${DIR}/agentpackages/${SCOPE}`;
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
// The node's boot id, once its census reports the session half.
let nodeBoot = '';
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
// nmcli, for the NetworkManager backend: one connection on eth0 whose ipv4
// keys live in a state file, answering the queries the agent makes and
// recording every call. The fixture agent never sees it (netplan is found
// first); the direct-call test below points the agent at it by path.
writeFileSync(`${DIR}/bin/nmcli`, `#!/bin/sh
S="${DIR}/nm.state"; echo "$*" >> "${DIR}/nmcli.log"
[ -f "$S" ] || printf 'ipv4.method=auto\\nipv4.addresses=\\nipv4.gateway=\\nipv4.dns=\\nipv4.ignore-auto-dns=no\\n' > "$S"
case "$*" in
  "-t -g RUNNING general") echo running ;;
  "-t -g GENERAL.CONNECTION device show eth0") echo "Wired connection 1" ;;
  "-t -g GENERAL.CONNECTION device show "*) ;;
  "-t -g "*" con show Wired connection 1") grep "^$3=" "$S" | cut -d= -f2- ;;
  "con mod Wired connection 1 "*) shift 3
    while [ $# -ge 2 ]; do grep -v "^$1=" "$S" > "$S.n"; echo "$1=$2" >> "$S.n"; mv "$S.n" "$S"; shift 2; done ;;
  "con up Wired connection 1") ;;
  *) echo "nmcli stub: unknown: $*" >&2; exit 2 ;;
esac
`, { mode: 0o755 });
// dpkg that has nothing, and an npm that refuses: a recipe's system
// packages are all missing, and the one recipe that would download a
// browser stops at its first command instead.
writeFileSync(`${DIR}/bin/dpkg`, `#!/bin/sh
exit 1
`, { mode: 0o755 });
writeFileSync(`${DIR}/bin/npm`, `#!/bin/sh
echo "npm: stub — nothing is downloaded in the suite" >&2
exit 1
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
# With the BOM the real config.sh writes. Without it here, the census read
# .runner fine in the suite and returned an empty name on a real node.
printf '\\357\\273\\277{"agentName":"%s","gitHubUrl":"%s"}' "$name" "$url" > "$(dirname "$0")/.runner"
`, { mode: 0o755 });
writeFileSync(`${DIR}/runner-src/svc.sh`, `#!/bin/sh
# The real svc.sh resolves everything relative to the working directory and
# refuses anywhere but the runner root. Recorded, because running it from
# elsewhere registered a runner that could never take a job.
[ -f ./config.sh ] && echo "RUNNER_ROOT_OK" >> "$(dirname "$0")/calls.log"
echo "svc $*" >> "$(dirname "$0")/calls.log"
`, { mode: 0o755 });
// run.sh, for the node with no systemd: it stays up under the name the
// census looks for, so a foreground runner reads as listening.
writeFileSync(`${DIR}/runner-src/run.sh`, `#!/bin/sh
exec -a "$(cd "$(dirname "$0")" && pwd)/bin/Runner.Listener" sleep 300
`, { mode: 0o755 });
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
// ttyd, stood in for (roadmap #24): the agent starts two of them for the
// sessions this node runs, and what is under test is that it does — as
// which account, on which ports, running bb-tty from which bundle — not
// ttyd itself. This one records its argv and environment and stays up.
writeFileSync(`${DIR}/bin/ttyd`, `#!/usr/bin/env python3
# ...and answers on its port with the request line, so the controller's
# terminal proxy can be shown dialing this node with the URL it stamped.
import http.server, os, socketserver, sys, threading, time
a = sys.argv[1:]
open(f"${DIR}/ttyd-{os.getpid()}.argv", "w").write("\\n".join(a) + "\\n")
open(f"${DIR}/ttyd-{os.getpid()}.env", "w").write("".join(f"{k}={v}\\n" for k, v in os.environ.items()))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = f"ttyd-stub {self.requestline}".encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)
    def log_message(self, *x): pass
# Up for as long as the agent that started it is, like the real one under
# SIGTERM — and not a minute longer, so a killed agent leaves nothing behind.
def watch():
    while os.getppid() != 1: time.sleep(1)
    os._exit(0)
threading.Thread(target=watch, daemon=True).start()
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", int(a[a.index("--port") + 1])), H) as srv:
    srv.serve_forever()
`, { mode: 0o755 });
const ttydRuns = () => readdirSync(DIR).filter(f => /^ttyd-\d+\.argv$/.test(f))
  .map(f => ({ pid: Number(f.match(/\d+/)[0]),
               argv: readFileSync(`${DIR}/${f}`, 'utf8').trim().split('\n'),
               env: Object.fromEntries(readFileSync(`${DIR}/${f.replace('.argv', '.env')}`, 'utf8')
                 .split('\n').filter(Boolean).map(l => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)])) }));
const SESSION_PORT = 17681 + Math.floor(Math.random() * 1000);
// The stub docker's own state, so the agent's compose reaches the same fake
// daemon the controller's runner does — a real node needs nothing here.
const agentEnv = { ...process.env, BUILDERBOT_NODE_JSON: NODE_JSON,
  BUILDERBOT_TTYD_BIN: `${DIR}/bin/ttyd`, BUILDERBOT_SESSION_PORT: String(SESSION_PORT),
  BUILDERBOT_SESSION_BIND: '127.0.0.1',
  // A PATH of the harness's own. The agent reports what it finds on PATH as
  // the fixture node's toolchains, and run from a session on a node this
  // process inherits that node's PATH — the real store, flutter included,
  // which made the fixture node "have" everything this machine has.
  DOCKER_STUB_STATE: `${DIR}/dockerstate`,
  PATH: `${DIR}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`,
  BUILDERBOT_DPKG_BIN: `${DIR}/bin/dpkg`, BUILDERBOT_APT_BIN: `${DIR}/bin/apt-get-never`,
  BUILDERBOT_IDLE_UNIT: '1',
  BUILDERBOT_SESSION_RETRY_S: '2',   // the restart cooldown, which a test waits out
  BUILDERBOT_SYSTEMD: '1',      // this agent takes the service path whichever box runs the suite
  BUILDERBOT_TAILSCALE_BIN: `${DIR}/bin/tailscale`,
  BUILDERBOT_RUNNER_DIR: `${DIR}/runner`, BUILDERBOT_RUNNER_TARBALL: `${DIR}/runner.tar.gz`,
  BUILDERBOT_SANDBOX_BIN: `${DIR}/bin/bb-sandbox`, BB_SANDBOX_STATE: SANDBOX_STATE,
  BUILDERBOT_NETPLAN_BIN: `${DIR}/bin/netplan`, BUILDERBOT_NETPLAN_DIR: `${DIR}/netplan` };
{
  let out = '';
  try {
    // A packages store of its own: the default is /var/lib/builderbot, which
    // this container cannot write, and the session half unpacks bb there.
    out = execFileSync('python3', [AGENT, 'enroll', '--controller', URL,
      '--token', minted.token, '--user', process.env.USER || 'builder',
      '--store', `data=${DIR}/agentdata`, '--store', `packages=${DIR}/agentpackages`],
      { env: agentEnv, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
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

  // ---- the container node (roadmap #21) ---------------------------------
  // The same image in its `node` role: scripts/node-agent.sh is what the
  // entrypoint execs instead of the supervisor, and it composes the enroll
  // call from the template's variables. Driven here rather than trusted,
  // because it is the only path an operator will ever use to make one, and
  // its arguments are four env vars that nothing else checks.
  {
    const NROOT = `${DIR}/nodecontainer`;
    const two = await api('/api/v1/nodes', { action: 'enroll', name: 'boxnode' });
    const nenv = { ...agentEnv, BUILDERBOT_NODE_JSON: '', NODE_STORE_ROOT: NROOT,
                   CONTROLLER_URL: URL, NODE_TOKEN: two.token,
                   NODE_PACKAGES_STORE: `${DIR}/nodepackages` };
    delete nenv.BUILDERBOT_NODE_JSON;
    let nout = '';
    const rec = `${NROOT}/node.json`;
    {
      // It ends in `exec ... run`, which never returns, so it is killed rather
      // than waited on — and killed on the STATE the two assertions below are
      // about, which is reached in a second or so. It used to be a 25s process
      // timeout, which reached the same place and then sat there: the single
      // slowest interval in the suite.
      // SIGKILL, not the default SIGTERM: the agent's own handler stops its
      // ttyds first and can outlive the call, and one of these left alive
      // took the container node's runner job below before the agent that
      // was meant to have it had said hello.
      const ch = spawn('bash', [`${REPO}/scripts/node-agent.sh`],
        { env: nenv, stdio: ['ignore', 'pipe', 'pipe'] });
      ch.stdout.on('data', d => { nout += d; }); ch.stderr.on('data', d => { nout += d; });
      await until(async () => existsSync(rec)
        && (await nodeById(two.id))?.state === 'online' ? true : null, 25000);
      ch.kill('SIGKILL');
      await new Promise(r => ch.on('exit', r));
    }
    ok(existsSync(rec), `the node role enrolls from CONTROLLER_URL and NODE_TOKEN (${
      nout.split('\n').filter(Boolean).slice(-2).join(' | ').slice(0, 120)})`);
    const nst = existsSync(rec) ? JSON.parse(readFileSync(rec, 'utf8')) : {};
    ok(nst.node_id === two.id && nst.stores?.data === `${NROOT}/data`
       && nst.stores?.packages === `${DIR}/nodepackages`,
       `...keeping its identity and stores under NODE_STORE_ROOT, and its packages store
        where NODE_PACKAGES_STORE says — the package store, in the template (${
         JSON.stringify(nst.stores || {})})`);
    ok((await nodeById(two.id))?.state === 'online',
       '...and the row comes online without systemd, ssh or a provisioner');
    // Second start: the token is spent and the record is what matters. An
    // image update restarts this container, and re-enrolling every time
    // would burn a token it does not have and lose the node's identity.
    let again2 = '';
    {
      // Same again: killed on the sentence being looked for rather than on a
      // clock, since this one also ends in a loop that never returns.
      const ch = spawn('bash', [`${REPO}/scripts/node-agent.sh`],
        { env: nenv, stdio: ['ignore', 'pipe', 'pipe'] });
      ch.stdout.on('data', d => { again2 += d; }); ch.stderr.on('data', d => { again2 += d; });
      await until(() => /already enrolled/.test(again2) || null, 8000);
      ch.kill('SIGKILL');
      await new Promise(r => ch.on('exit', r));
    }
    ok(/already enrolled/.test(again2) && JSON.parse(readFileSync(rec, 'utf8')).node_id === two.id,
       '...and starting again re-uses the record rather than spending another token');
    // A container node has no systemd, so its runner cannot be a service:
    // it runs as run.sh in the foreground under the agent, which supervises
    // it and takes it down with itself. The node is kept running for this,
    // on ports of its own so its ttyds do not collide with agentbox's.
    {
      const fenv = { ...nenv, BUILDERBOT_SYSTEMD: '0', BUILDERBOT_RUNNER_DIR: `${NROOT}/runner`,
                     BUILDERBOT_SESSION_PORT: String(SESSION_PORT + 20) };
      const box = spawn('bash', [`${REPO}/scripts/node-agent.sh`], { env: fenv, stdio: ['ignore', 'pipe', 'pipe'] });
      let boxlog = '';
      box.stdout.on('data', d => { boxlog += d; }); box.stderr.on('data', d => { boxlog += d; });
      box.on('exit', () => { try { writeFileSync(`${NROOT}/agent.log`, boxlog); } catch {} });
      try {
        await until(async () => (await nodeById(two.id))?.state === 'online' ? true : null, 30000);
        const inst = await api('/api/v1/nodes', { action: 'runner', id: two.id, want: true,
          labels: ['box'], url: 'https://github.com/example-org' });
        const ifin = await until(async () => {
          const r = await api(`/api/v1/jobs?id=${inst.job}`);
          return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
        }, 60000);
        const listener = () => { try {
          return execFileSync('pgrep', ['-f', `${NROOT}/runner/bin/Runner.Listener`], { encoding: 'utf8' }).trim();
        } catch { return ''; } };
        ok(ifin?.state === 'succeeded' && /foreground under this agent/.test(ifin.log) && listener() !== '',
           `on a node with no systemd the runner runs as run.sh under the agent (${ifin?.state}: ${
             (ifin?.log || '').split('\n').filter(l => /foreground|svc|refused|error/.test(l)).join(' / ').slice(0, 120)
             } · node: ${boxlog.split('\n').filter(Boolean).slice(-3).join(' | ').slice(0, 200)})`);
        const cen = await until(async () => { const n = await nodeById(two.id);
          return n?.reported?.services?.['actions-runner']?.active ? n : null; }, 30000);
        ok(cen !== null, '...and the census reports it listening, the same as a service');
        box.kill('SIGTERM');
        await until(() => listener() === '' ? true : null, 15000, 300);
        ok(listener() === '', '...and it goes down with the agent, workers and all');
      } finally {
        if (box.exitCode === null) box.kill('SIGKILL');
        try { execFileSync('pkill', ['-f', `${NROOT}/runner/bin/Runner.Listener`], { stdio: 'ignore' }); } catch {}
      }
    }
    await api('/api/v1/nodes', { action: 'retire', id: two.id });
  }
  const n = await nodeById(minted.id);
  // The version is read from the controller, not written here: the agent
  // just downloaded from it, so the two must agree, and an assertion naming
  // a number has to be edited on every bump for nothing.
  const ships = (await api('/api/v1/nodes')).agent || {};
  ok(n.state === 'online' && n.reported.cpu > 0 && n.reported.hostname
     && n.agent.version === ships.version && n.agent.digest === ships.digest,
     `the row is online with the census, and runs the agent this controller ships (${n.agent.version})`);
  // single use
  let again = '';
  try {
    execFileSync('python3', [AGENT, 'enroll', '--controller', URL,
      '--token', minted.token], { env: { ...agentEnv, BUILDERBOT_NODE_JSON: NODE_JSON + '.2' },
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
  } catch (e) { again = String(e.stderr); }
  ok(/refused/.test(again) && !existsSync(NODE_JSON + '.2'),
     `the enroll token is single-use: a second enrollment is refused (${again.trim().split('\n').pop()?.slice(0, 120) || 'no stderr'})`);
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

  // ---- the session half (roadmap #24) ----------------------------------------
  // On its first hello the agent fetches the bb bundle the controller ships,
  // unpacks it into the packages store, and starts two ttyds running bb-tty
  // from it: what the controller's dashboard hook does, done on the node by
  // the process that is already there. The census then says so, which is
  // what the proxy (phase 10b) will relay a session on the strength of.
  {
    const sess = await until(async () => {
      const n = await nodeById(minted.id);
      return n?.reported?.session?.up ? n.reported.session : null;
    });
    ok(sess !== null, 'the census reports the session half: ttyd is up');
    ok(sess?.port === SESSION_PORT && sess?.ro_port === SESSION_PORT + 1
       && sess?.user === execFileSync('id', ['-un'], { encoding: 'utf8' }).trim(),
       `...on the ports it bound and as the account sessions run as (${sess?.port}, ${sess?.user})`);
    ok(typeof sess?.workspace === 'boolean' && /^sha256:/.test(sess?.bundle || ''),
       '...saying whether /workspace is mounted and which bb bundle bb-tty runs from');
    // This node's two — the container node enrolled above started its own.
    const runs = ttydRuns().filter(r => r.env.BUILDERBOT_NODE === minted.id);
    ok(runs.length === 2 && runs.some(r => r.argv.includes('--writable'))
       && runs.some(r => !r.argv.includes('--writable')),
       'two ttyds: the writable one and the read-only twin an account without a shell is shown');
    const bbtty = runs[0]?.argv.at(-1) || '';
    ok(/\/\.bb\/[0-9a-f]{16}\/scripts\/dashboard\/bb-tty$/.test(bbtty) && existsSync(bbtty),
       `...both running bb-tty out of the bundle unpacked in the packages store (${bbtty.replace(DIR, '…')})`);
    ok(runs.every(r => r.argv.includes('--url-arg') && r.argv.includes('--interface')
                       && r.argv[r.argv.indexOf('--interface') + 1] === '127.0.0.1'),
       '...with --url-arg for the target, bound where the agent was told');
    const e = runs[0]?.env || {};
    ok(e.BUILDERBOT_ROLE === 'node' && e.BB_CONTROLLER === URL.replace(/\/$/, '')
       && e.WORKSPACE === '/workspace' && !('BB_TOKEN' in e) && !e.BUILDERBOT_NODE_JSON,
       'the sessions inherit the role and the controller\'s address — never the node\'s token');
    // Through the SYMLINK, not the digest it points at (bug #66). A ttyd
    // restart onto a new bundle only reaches new connections — a tmux
    // session's shell keeps the PATH it was started with — so a session open
    // since before an update went on running the bundle it began with, and a
    // verb the controller had gained printed bb's usage instead of running.
    const first = (e.PATH || '').split(':')[0];
    ok(first.endsWith('/.bb/current/scripts')
       && realpathSync(first) === realpathSync(bbtty.replace(/\/dashboard\/bb-tty$/, '')),
       `...and bb on PATH through .bb/current, so a shell open since before an `
       + `update still runs the bundle delivered last (${first.replace(DIR, '…')})`);
    // A port held by a ttyd of an earlier agent process (bug #58). The
    // agent's self-update re-executes it, which keeps its children and
    // loses every handle to them: the old ttyds stayed on the ports, every
    // later start exited on the bind and the census still said up, so a
    // node served sessions from a bundle four deliveries old. Stood in for
    // here: the writable ttyd is killed and a stray that looks like ours
    // (ttyd … bb-tty on its command line) takes its port; the restart has
    // to end the stray and be up for real, rather than report a start
    // that died.
    const writable = runs.find(r => r.argv.includes('--writable'));
    process.kill(writable.pid, 'SIGKILL');
    await sleep(500);
    const stray = spawn(`${DIR}/bin/ttyd`, ['--port', String(SESSION_PORT), '--interface', '127.0.0.1',
                                            `${DIR}/nowhere/.bb/0000000000000000/scripts/dashboard/bb-tty`],
                        { stdio: 'ignore' });
    let strayGone = false;
    stray.on('exit', () => { strayGone = true; });
    await sleep(500);
    const again = await until(async () => {
      const fresh = ttydRuns().filter(r => r.env.BUILDERBOT_NODE === minted.id
                                        && r.argv.includes('--writable') && r.pid !== writable.pid);
      const n = await nodeById(minted.id);
      return strayGone && fresh.length && n?.reported?.session?.up
        && !n.reported.session.why ? { fresh, sess: n.reported.session } : null;
    }, 75000, 500);
    ok(again !== null && strayGone,
       `a ttyd that died is started again, and a stray bb-tty ttyd holding its port — an earlier agent's — is ended first (${
         again ? 'up on ' + again.sess.port : 'not up: ' + JSON.stringify((await nodeById(minted.id))?.reported?.session)})`);
    if (!strayGone) stray.kill('SIGKILL');
    // Retried rather than asked once: the census says up when the process
    // is alive and still there a moment later, which is what the agent can
    // know — the stub's own listener binds just after that, so a single
    // fetch races it and fails on a loaded box.
    const answer = await until(async () =>
      fetch(`http://127.0.0.1:${SESSION_PORT}/ws?arg=x`).then(r => r.text()).catch(() => null),
      15000, 300) || 'never answered';
    ok(/^ttyd-stub GET/.test(answer), `...and the port answers as the agent's own again (${answer.slice(0, 30)})`);
    const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
    const store = `${st.stores.packages}/${SCOPE}`;   // the node's scope in it (roadmap R19)
    ok(existsSync(`${store}/.bb/current/scripts/bb`)
       && lstatSync(`${store}/.bb/current`).isSymbolicLink(),
       'the packages store carries a .bb/current link at the newest bundle, for a shell at the console');
    ok(existsSync(`${store}/.bb/current/scripts/dashboard/bb-work-note`)
       && existsSync(`${store}/.bb/current/scripts/lib/bbapi.py`),
       '...and the bundle carries the hooks bb-tty writes into a session and bb\'s API client');
    // ...and the ones before it do not pile up forever. One directory per
    // delivery, one delivery per commit that touches bb: 33 of them in four
    // days on the first node anybody looked at. Driven directly rather than
    // through a run — thirty-three deliveries is not something to wait for.
    const pruned = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile, time
spec = importlib.util.spec_from_file_location('agent', ${JSON.stringify(AGENT)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp(); now = time.time(); names = []
for i in range(12):
    n = '%016x' % i
    os.makedirs(os.path.join(d, n, 'scripts')); names.append(n)
    os.utime(os.path.join(d, n), (now - i * 86400, now - i * 86400))
open(os.path.join(d, 'bundle.tar'), 'w').write('x')
os.symlink(names[0], os.path.join(d, 'current'))
m.Agent.prune_bundles(d, os.path.join(d, names[0]))
print(json.dumps(sorted(os.listdir(d))))
`], { encoding: 'utf8' }).trim().split('\n').pop());
    ok(pruned.filter(x => /^[0-9a-f]{16}$/.test(x)).length === 5
       && pruned.includes('0000000000000000') && !pruned.includes('000000000000000b'),
       `a delivery does not keep every bundle before it — the newest few stay (${pruned.length} left)`);
    ok(pruned.includes('bundle.tar') && pruned.includes('current'),
       '...and nothing that is not a bundle is touched');
    // The node's boot rides with it: a terminal's URL carries the boot of
    // the machine the session runs ON, or bb-tty there refuses every
    // connection as a stale tab — which is what the first real session did.
    ok(/^\d+\.\d+$/.test(sess?.boot || ''),
       `...and the node's own boot id, in bb-tty's shape (${sess?.boot})`);
    nodeBoot = sess?.boot || '';
  }

  // ---- the relay (roadmap #24): bb's notebook verbs from a node ---------------
  // A session on a node has no /config, so `bb roadmap`, `bb bug`, `bb
  // version` and the rest send their words to /api/v1/bb with the session's
  // token, and the controller runs its own bb in that project's tree. What
  // is asserted: it runs, its answer comes back, the token pins the project,
  // and the verbs that answer for the machine the session is on are refused.
  {
    const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha'],
      { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
    ok(/^bbs_/.test(tok), `bb users token mints a session token for a project (${tok.slice(0, 8)}…)`);
    const relay = async (body, auth = 'Bearer ' + tok) => {
      const r = await fetch(URL.replace(/\/$/, '') + '/api/v1/bb', { method: 'POST',
        headers: { Authorization: auth, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      return { status: r.status, ...(await r.json()) };
    };
    const added = await relay({ argv: ['roadmap', 'add', 'relayed from a node'], cwd: `${DIR}/ws/alpha` });
    ok(added.status === 200 && added.code === 0 && /added R\d+/.test(added.out),
       `a session's bb roadmap runs on the controller and answers (${(added.out || added.error || '').trim().slice(0, 60)})`);
    const listed = await relay({ argv: ['roadmap'] });
    ok(listed.code === 0 && /relayed from a node/.test(listed.out),
       '...against the project the token was minted for, with no cwd sent at all');

    // ---- renewal: a session in use never runs out ------------------------
    // A token lasts twelve hours and a working session ran past it overnight:
    // every bb verb stopped, and from the remote view there was no tab to
    // open. So past half its life every authenticated answer carries a fresh
    // one (users.renewal, X-BB-Session), bbapi writes it where bb looks, and
    // bb prefers whichever of its two expires later.
    {
      const mint = ttl => execFileSync('python3', ['-c', `
import importlib.util, os, json
spec = importlib.util.spec_from_file_location('users', ${JSON.stringify(`${REPO}/scripts/dashboard/users.py`)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def wj(path, d):
    tmp = str(path) + '.new'
    with open(tmp, 'w') as f: json.dump(d, f, indent=2)
    os.replace(tmp, path)
m.configure(state=${JSON.stringify(`${DIR}/state`)}, write_json=wj)
print(m.mint_session('alpha', ttl=${ttl}))`], { encoding: 'utf8' }).trim();
      const expOf = t => Number(Buffer.from(t.slice(4), 'base64url').toString().split('|')[1]);
      const short = mint(3600);
      const raw = await fetch(URL.replace(/\/$/, '') + '/api/v1/bb', { method: 'POST',
        headers: { Authorization: 'Bearer ' + short, 'Content-Type': 'application/json' },
        body: JSON.stringify({ argv: ['roadmap'] }) });
      const fresh = raw.headers.get('x-bb-session') || '';
      ok(raw.status === 200 && /^bbs_/.test(fresh) && expOf(fresh) - expOf(short) > 6 * 3600
         && Buffer.from(fresh.slice(4), 'base64url').toString().startsWith('alpha|'),
         `an answer to a token past half its life carries a fresh one for the same project (${fresh.slice(0, 8)}…)`);
      const full = await fetch(URL.replace(/\/$/, '') + '/api/v1/bb', { method: 'POST',
        headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
        body: JSON.stringify({ argv: ['roadmap'] }) });
      ok(full.status === 200 && !full.headers.get('x-bb-session'),
         '...and one with most of its life left is left alone');
      // bb itself, on a node, with the short token in its environment: the
      // renewed one lands in the cache file, and the next call sends THAT.
      const cache = `${DIR}/cache-renew`;
      const env = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                    BB_TOKEN: short, BB_PROJECT: 'alpha', XDG_CACHE_HOME: cache };
      execFileSync('bash', [`${REPO}/scripts/bb`, 'roadmap'], { encoding: 'utf8', env, stdio: ['ignore', 'pipe', 'pipe'] });
      const kept = existsSync(`${cache}/builderbot/token-alpha`)
        ? readFileSync(`${cache}/builderbot/token-alpha`, 'utf8').trim() : '';
      ok(/^bbs_/.test(kept) && expOf(kept) > expOf(short),
         'bb keeps the renewed token in the account\'s cache, where it reads when the environment\'s has expired');
      const again = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', '--now'],
        { encoding: 'utf8', env: { ...env }, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
      ok(again === kept, '...and prefers it over the older one in its environment from then on');
    }
    const settings = await relay({ argv: ['settings', '--json'] });
    ok(settings.code === 0 && JSON.parse(settings.out).project === 'alpha'
       && typeof JSON.parse(settings.out).locked === 'boolean',
       'bb settings --json relays the project\'s settings, lock included — what bb-tty and bb build read on a node');
    const other = await relay({ argv: ['roadmap'], project: 'ep.silon' });
    ok(other.status === 403 && /another project/.test(other.error),
       'a token for alpha cannot ask about another project');
    const sdk = await relay({ argv: ['sdk'] });
    ok(sdk.status === 400 && /not relayed/.test(sdk.error),
       'bb packages is refused — it answers for the machine the session is on');
    const emu = await relay({ argv: ['emu', 'start'] });
    ok(emu.status === 400, '...and so is bb emu');
    const nobody = await relay({ argv: ['roadmap'] }, 'Bearer bbs_nonsense');
    ok(nobody.status === 401, 'a token that does not verify gets nothing');

    // ---- the login follows the account to the node (roadmap #24) ----------
    // A node-bound terminal's token is minted for the ACCOUNT as well as the
    // project, and with it `bb login` on the node fetches that account's
    // Claude credentials from the controller into the node's copy of its
    // home — so signing in once, on the Doctor card, signs every node in.
    // Only such a token can, and only for its own account.
    {
      const creds = `${DIR}/home/.claude/.credentials.json`;
      const had = existsSync(creds) ? readFileSync(creds, 'utf8') : null;
      mkdirSync(`${DIR}/home/.claude`, { recursive: true });
      // With an expiresAt, because that is what the two sides compare: a
      // refresh moves it, and the later grant is the one that wins (bug #64).
      writeFileSync(creds, '{"claudeAiOauth": {"accessToken": "fake-for-the-suite", "expiresAt": 2000}}\n', { mode: 0o600 });
      const forMe = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
        { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
      const login = async (t) => { const r = await fetch(URL.replace(/\/$/, '') + '/api/v1/claude-login',
        { headers: { Authorization: 'Bearer ' + t } }); return { status: r.status, ...(await r.json()) }; };
      const mine = await login(forMe);
      ok(mine.status === 200 && /fake-for-the-suite/.test(mine.credentials || ''),
         'a token minted for an account fetches that account\'s Claude login from its home here');
      const anon = await login(tok);
      ok(anon.status === 403 && /minted for an account/.test(anon.error || ''),
         '...and a token for the project alone — a relayed verb\'s — cannot');
      // bb login on the node: the same fetch, into the node's home, 0600.
      const nodeHome = `${DIR}/nodehome`;
      mkdirSync(`${DIR}/bin2`, { recursive: true });
      writeFileSync(`${DIR}/bin2/claude`, '#!/bin/sh\n[ "$1" = auth ] && [ "$2" = status ] && printf \'{"loggedIn":false}\\n\'\nexit 0\n', { mode: 0o755 });
      const out = execFileSync('bash', [`${REPO}/scripts/bb`, 'login'], { encoding: 'utf8',
        env: { ...process.env, PATH: `${DIR}/bin2:${process.env.PATH}`, HOME: nodeHome,
               BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: forMe, BB_NODE: 'agentbox' } });
      ok(/signed in on agentbox/.test(out) && /came from the controller/.test(out)
         && readFileSync(`${nodeHome}/.claude/.credentials.json`, 'utf8').includes('fake-for-the-suite')
         && (statSync(`${nodeHome}/.claude/.credentials.json`).mode & 0o777) === 0o600,
         `bb login on a node takes the controller's login into that home, 0600 (${out.trim().split('\n').pop().slice(0, 60)})`);
      // ...and back the other way, which is the half that was missing. The
      // grant is an OAuth pair whose refresh ROTATES the refresh token, so a
      // node that refreshes leaves the controller holding one the server has
      // retired — the operator came back to a controller that said it was
      // signed out (bug #64). The newer grant goes home.
      writeFileSync(`${nodeHome}/.claude/.credentials.json`,
        '{"claudeAiOauth": {"accessToken": "refreshed-on-the-node", "expiresAt": 3000}}\n', { mode: 0o600 });
      const back = execFileSync('bash', [`${REPO}/scripts/bb`, 'login', '--sync'], { encoding: 'utf8',
        env: { ...process.env, PATH: `${DIR}/bin2:${process.env.PATH}`, HOME: nodeHome,
               BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: forMe, BB_NODE: 'agentbox' } });
      ok(readFileSync(creds, 'utf8').includes('refreshed-on-the-node')
         && existsSync(`${DIR}/home/.claude/.credentials.json.prev`),
         `a grant the node refreshed is handed back to the controller, the one it replaced kept beside it (${
           back.trim() || 'quiet'})`);
      // ...and an older one cannot undo a sign-in that happened while the
      // node was away: newer wins, not last-writer.
      writeFileSync(`${nodeHome}/.claude/.credentials.json`,
        '{"claudeAiOauth": {"accessToken": "stale-node-copy", "expiresAt": 1000}}\n', { mode: 0o600 });
      execFileSync('bash', [`${REPO}/scripts/bb`, 'login', '--sync'], { encoding: 'utf8',
        env: { ...process.env, PATH: `${DIR}/bin2:${process.env.PATH}`, HOME: nodeHome,
               BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: forMe, BB_NODE: 'agentbox' } });
      ok(readFileSync(creds, 'utf8').includes('refreshed-on-the-node')
         && readFileSync(`${nodeHome}/.claude/.credentials.json`, 'utf8').includes('refreshed-on-the-node'),
         '...while an older copy is refused, and the node takes the newer one instead');
      if (had === null) rmSync(creds); else writeFileSync(creds, had);
      rmSync(`${DIR}/home/.claude/.credentials.json.prev`, { force: true });
    }

    // ---- the hooks post from a node (roadmap #24) ---------------------------
    // Inside a session on a node the two hooks bb-tty writes into its
    // settings have no /config to write: they post to the controller with
    // the session's token, and the same modules record them here — the
    // overlap note `bb work` reads, the prompt in the project's feed, and
    // the "started" line the proxy cannot announce for a session it does
    // not see start.
    {
      const forMe = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
        { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
      const nodeEnv = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                        BB_TOKEN: forMe, BB_NODE: 'agentbox', BB_TREE: '/workspace/alpha' };
      const hook = (name, args, input) => execFileSync('python3', [`${REPO}/scripts/dashboard/${name}`, ...args],
        { input, encoding: 'utf8', env: nodeEnv, stdio: ['pipe', 'pipe', 'pipe'] });
      // ---- bb-gate: nothing runs while BuilderBot is away or the block is behind ----
      // A session outlives an update. The gate refuses every tool call
      // while the controller does not answer, or while the project's
      // CLAUDE.md block differs from the shipped template, and lets the
      // first call after the fix through without a wait.
      {
        const gt = `${DIR}/gatetree`; mkdirSync(gt, { recursive: true });
        const tplPath = `${REPO}/config/templates/project-CLAUDE.md`;
        const tpl = readFileSync(tplPath, 'utf8');
        const cache = `${DIR}/gatecache`; mkdirSync(cache, { recursive: true });
        const genv = extra => ({ ...nodeEnv, BB_TREE: gt, TEMPLATE_MD: tplPath, XDG_CACHE_HOME: cache,
                                 BUILDERBOT_ROLE: 'controller', ...extra });
        const gate = extra => { try {
          execFileSync('python3', [`${REPO}/scripts/dashboard/bb-gate`, 'alpha', 'x'],
            { input: '{"tool_name":"Bash"}', encoding: 'utf8', env: genv(extra), stdio: ['pipe', 'pipe', 'pipe'] });
          return { code: 0, err: '' };
        } catch (e) { return { code: e.status, err: String(e.stderr) }; } };
        const fresh = () => rmSync(`${cache}/builderbot/gate-alpha`, { force: true });
        writeFileSync(`${gt}/CLAUDE.md`, tpl + '\n## Notes\n\nours.\n');
        let r = gate({});
        ok(r.code === 0, `with the controller up and the block current, a tool call goes through (${r.code} ${r.err.slice(0, 60)})`);
        // Behind INSIDE the window: the call goes through, and the prompt
        // hook says so once — the window's promise is that drift stops nothing.
        writeFileSync(`${gt}/CLAUDE.md`, tpl.replace('Before anything else in a session:', 'Before anything else in a session, once:') + '\n## Notes\n\nours.\n');
        fresh();
        r = gate({});
        ok(r.code === 0, `a block behind inside the window lets the call through (${r.code} ${r.err.slice(0, 40)})`);
        const said = execFileSync('python3', [`${REPO}/scripts/dashboard/bb-gate`, '--prompt', 'alpha', 'x'],
          { input: '{"prompt":"go"}', encoding: 'utf8', env: genv({}), stdio: ['pipe', 'pipe', 'pipe'] });
        ok(/behind the one the container now ships/.test(said) && /keep working/.test(said),
           '...and the next prompt carries a warning that an update is waiting');
        const again = execFileSync('python3', [`${REPO}/scripts/dashboard/bb-gate`, '--prompt', 'alpha', 'x'],
          { input: '{"prompt":"go"}', encoding: 'utf8', env: genv({}), stdio: ['pipe', 'pipe', 'pipe'] });
        ok(again.trim() === '', '...once, not on every prompt');
        // From ANOTHER window: refused until the operator updates it.
        writeFileSync(`${gt}/CLAUDE.md`, tpl.replace(/BUILDERBOT:ENV:WINDOW \d+\.\d+/, 'BUILDERBOT:ENV:WINDOW 0.1') + '\n## Notes\n\nours.\n');
        fresh();
        r = gate({});
        ok(r.code === 2 && /another compatibility window/.test(r.err) && /operator updates it/.test(r.err),
           `a block from another window refuses the call and says the operator updates it (${r.code}: ${r.err.slice(0, 50)})`);
        writeFileSync(`${gt}/CLAUDE.md`, tpl + '\n## Notes\n\nours.\n');
        r = gate({});
        ok(r.code === 0, '...and the first call after the update goes through, with no wait — a refusal is never cached');
        fresh();
        r = gate({ BB_CONTROLLER: 'http://127.0.0.1:1' });
        ok(r.code === 2 && /not answering/.test(r.err) && /restarting after an update/.test(r.err),
           `a controller that does not answer refuses every call until it is back (${r.code})`);
        r = gate({});
        ok(r.code === 0, '...and answers again the moment it does');
      }
      // bb itself in the node role: a relayed verb is the controller's
      // answer and nothing else — the dispatch used to fall through and run
      // the verb a second time locally, so `bb bug` on bb-sandbox printed
      // the tracker and then died with "bugs.py is missing from this image".
      const bbOnNode = args => { try {
        return execFileSync('bash', [`${REPO}/scripts/bb`, ...args],
          { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: { ...nodeEnv, BB_PROJECT: 'alpha' },
            stdio: ['ignore', 'pipe', 'pipe'] });   // BB_PROJECT: what bb-tty exports into a session
      } catch (e) { return `FAILED ${e.status}: ${e.stderr}`; } };
      const once = bbOnNode(['roadmap', 'add', 'once, from a node']);
      const listing = bbOnNode(['roadmap']);
      ok((listing.match(/once, from a node/g) || []).length === 1 && !/nothing on/.test(listing),
         `a relayed verb run from a node answers once, with the controller's answer (${
           (once + listing).replace(/\s+/g, ' ').slice(0, 160)})`);
      const num = (once.match(/added R(\d+)/) || [])[1];
      bbOnNode(['roadmap', 'rm', String(num), 'test']);
      // bb git: git's network half from a node runs on the controller, in
      // the project's tree, with the keys that live only there (docs/nodes.md
      // §20, rule 2). The fixture has no remote, so git itself answers —
      // which is the proof that git ran here and not on the "node".
      const ls = bbOnNode(['git', 'ls-remote', 'origin']);
      ok(/fatal:/.test(ls) && !/not relayed|not accepted/.test(ls),
         `bb git ls-remote from a node reaches the controller's git in the project's tree (${ls.replace(/\s+/g, ' ').slice(0, 70)})`);
      const exec = bbOnNode(['git', 'push', '--upload-pack=/bin/sh', 'origin']);
      const conf = bbOnNode(['git', 'fetch', '-c', 'core.sshCommand=id']);
      const other = bbOnNode(['git', 'status']);
      ok(/not accepted/.test(exec) && /not accepted/.test(conf) && /takes push, fetch/.test(other),
         '...and an option that would run a program on the controller, or a verb that is not the network half, is refused before git sees it');
      // The identity a node session adopts is the controller's, through the
      // same settings answer bb-tty reads.
      const st = JSON.parse(bbOnNode(['settings', '--json']));
      ok('git_email' in st && 'git_name' in st,
         `bb settings carries the commit identity for a node's session to adopt (${st.git_name || '—'} <${st.git_email || '—'}>)`);
      const feed = async () => ((await api('/api/chat', { action: 'read', project: 'alpha' })).messages || []);
      const n0 = (await feed()).length;
      hook('bb-prompt-relay', ['alpha', 'ignored'], JSON.stringify({ prompt: 'refactor the picker <system-reminder>x</system-reminder>' }));
      const asked = (await feed()).slice(n0);
      ok(asked.length === 1 && asked[0].kind === 'asked' && /test asked: refactor the picker$/.test(asked[0].text),
         `a prompt typed in a session on the node lands in the project's feed, under the token's account (${asked[0]?.text})`);
      hook('bb-prompt-relay', ['--started', 'alpha', 'ignored'], '');
      const started = (await feed()).slice(-1)[0];
      ok(started?.kind === 'did' && /test started a Claude session on alpha \(agentbox\)/.test(started?.text || ''),
         `...and bb-tty's "started" line arrives the same way, naming the node (${started?.text})`);
      // ...and the same hook carries the notebook back the other way, for
      // free (roadmap #27). A session used to hear about a change only when
      // the operator pressed a button that types into its input box, spending
      // a turn and landing mid-task. A UserPromptSubmit hook's stdout is
      // added to the turn as context, so the news rides in on a prompt that
      // was being sent anyway.
      const ask = () => hook('bb-prompt-relay', ['alpha', 'ignored'],
        JSON.stringify({ prompt: 'carry on' }));
      ok(ask().trim() === '',
         'the first prompt of a session is told nothing — it was handed the whole list a moment ago');
      await api('/api/todo', { project: 'alpha', action: 'add', text: 'something the operator added' });
      const told = ask();
      ok(/just changed/.test(told) && /to-do list/.test(told),
         `...and a change made since then arrives on the next prompt, naming which half moved (${told.trim().slice(0, 60)})`);
      ok(ask().trim() === '', '...once, not on every prompt afterwards');
      const noteOut = hook('bb-work-note', ['alpha', 'ignored'],
        JSON.stringify({ tool_input: { file_path: '/workspace/alpha/src/picker.py', old_string: 'def pick():\n  pass' } }));
      const work = execFileSync('bash', [`${REPO}/scripts/bb`, 'work'], { encoding: 'utf8', cwd: `${DIR}/ws/alpha`,
        env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha' } });
      ok(/test\s+src\/picker\.py\s+\[pick\]/.test(work) && noteOut === '',
         `an edit's note from the node is what bb work reads here, symbol guessed and file relative to the tree (${
           (work.split('\n').find(l => /picker/.test(l)) || '').trim()})`);
      const bad = await fetch(URL.replace(/\/$/, '') + '/api/v1/hook', { method: 'POST',
        headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'asked', text: 'hi' }) });
      ok(bad.status === 403, 'a token for the project alone — no account — may not post as anybody');
    }

    // ---- the node's sessions are on the Sessions card (roadmap #24) --------
    // The agent's heartbeat carries the session account's tmux sessions;
    // the controller lists them beside its own, named by ITS rule (the
    // owner's bare, everybody else's prefixed), each saying which node it
    // is on; and ending one goes back to the agent through its held poll.
    // The agent here is this user, so its tmux is the harness's private
    // server — which is also the controller's, so the same session shows
    // up twice: once as this container's, once as agentbox's.
    {
      const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
      const real = `${uid}~claude-alpha`;
      tmuxKill(real); tmuxKill('claude-alpha');       // an earlier file's leftover
      // A shell rather than a sleep, so what the console types can be seen
      // to arrive: the pane runs it and the capture shows the result.
      tmuxNew(real, `${DIR}/ws/alpha`, ['bash', '--norc', '--noprofile']);
      const onNode = await until(async () =>
        ((await api('/api/status')).sessions || []).find(s => s.node === 'agentbox'), 45000, 500);
      ok(onNode && onNode.name === 'claude-alpha' && onNode.node_name === real,
         `a session in the node's tmux is listed within a heartbeat, under this container's name for it (${onNode?.name} on ${onNode?.node})`);
      ok(onNode && onNode.cwd === `${DIR}/ws/alpha` && onNode.claude && 'state' in onNode.claude,
         '...with its directory and its Claude state, like a local one');
      const cw = (await api('/api/status')).claude_with || {};
      ok((cw.alpha || []).includes('test'),
         '...and the project row counts it: the account has a session on alpha');
      // The read-only console's line, and the key row, reach a node's
      // session through the same poll: the agent types them into the pane.
      const said = await api('/api/say', { session: 'claude-alpha', node: onNode?.node_id,
                                           text: 'echo typed-from-the-console' });
      ok(said.ok && said.queued, `a console line for a session on the node is queued for its agent (${JSON.stringify(said)})`);
      const typed = await until(async () => /typed-from-the-console/.test(tmuxCapture(real)) ? true : null, 30000, 500);
      ok(typed === true, '...and the agent types it into the pane, Enter included');
      const paged = await api('/api/keys', { session: 'claude-alpha', node: onNode?.node_id, key: 'pgup' });
      ok(paged.ok && paged.queued, 'the key row\'s PgUp is queued the same way, decided on the node');
      const k = await api('/api/session', { action: 'kill', session: 'claude-alpha', node: onNode?.node_id });
      ok(k.ok && k.queued, `ending it from the card is queued for the agent (${JSON.stringify(k)})`);
      ok(!((await api('/api/status')).sessions || []).some(s => s.node === 'agentbox' && s.name === 'claude-alpha'),
         '...and the row is gone at once, not at the next heartbeat');
      const gone = await until(async () => {
        // display-message on a name tmux cannot find prints nothing and
        // exits 0 (measured), so "gone" is the name no longer echoing back.
        try { return tmuxFmt(real, '#{session_name}') === real ? null : true; } catch { return true; }
      }, 30000, 500);
      ok(gone === true, '...and the agent ends it in the node\'s tmux');
    }

    // ---- restarting a session that is on a node ---------------------------
    // The other half of the same gesture, and the half that was missing:
    // saving a project's model, effort or permission rung with Restart
    // ticked looked only at THIS container's tmux, so a project whose
    // sessions run on a node was always told "no session is running here"
    // while its own row said there was one.
    //
    // The launcher is a real script here, because the agent finds it by
    // reading the pane's start command rather than composing a path — on a
    // node the file is in the home of whichever account owns the session,
    // and tmux already knows which.
    {
      // beta rather than alpha: the block above ends claude-alpha through
      // the agent, and a name just killed is held off the list until the
      // node's own heartbeat confirms it — which would read here as the
      // session not being listed at all.
      const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
      const real = `${uid}~claude-beta`;
      const seen = `${DIR}/respawn-argv.txt`;
      const launcher = `${DIR}/home/.cache/builderbot/claude-run-beta.sh`;
      mkdirSync(`${DIR}/home/.cache/builderbot`, { recursive: true });
      writeFileSync(launcher,
        `#!/usr/bin/env bash\nprintf '%s\\n' "\${1:-none}" >> ${seen}\nexec sleep 600\n`,
        { mode: 0o755 });
      rmSync(seen, { force: true });
      tmuxKill(real); tmuxKill('claude-beta');
      tmuxNew(real, `${DIR}/ws/beta`, [launcher]);
      const back = await until(async () =>
        ((await api('/api/status')).sessions || []).find(
          s => s.node === 'agentbox' && s.name === 'claude-beta'), 45000, 500);
      ok(!!back, 'a session started on its launcher is listed on the node');
      const r = await api('/api/prefs', { project: 'beta', restart: true });
      ok(r.restarted === true && r.on_node === 'agentbox',
         `saving with Restart finds the session on the node rather than reporting none (${
           JSON.stringify(r)})`);
      // Twice: once when the session started, once for the respawn — and the
      // second carries --respawn, which is what tells the launcher to resume
      // the transcript instead of opening a new conversation.
      const ran = await until(async () => {
        const lines = existsSync(seen)
          ? readFileSync(seen, 'utf8').trim().split('\n') : [];
        return lines.length >= 2 ? lines : null;
      }, 30000, 500);
      ok(Array.isArray(ran) && ran[ran.length - 1] === '--respawn',
         `...and the agent runs the launcher again, resuming rather than starting fresh (${
           JSON.stringify(ran)})`);
      tmuxKill(real);
    }
    // ...and only the launcher. The controller asks for a respawn; it does
    // not say what to execute, so a pane running anything else is left alone
    // rather than restarted into whatever happened to be there.
    {
      const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
      const real = `${uid}~claude-gamma`;
      tmuxKill(real);
      tmuxNew(real, `${DIR}/ws/gamma`, ['bash', '--norc', '--noprofile']);
      const back = await until(async () =>
        ((await api('/api/status')).sessions || []).find(
          s => s.node === 'agentbox' && s.name === 'claude-gamma'), 45000, 500);
      const was = back && tmuxFmt(real, '#{pane_pid}');
      await api('/api/prefs', { project: 'gamma', restart: true });
      await sleep(4000);
      ok(was && tmuxFmt(real, '#{pane_pid}') === was,
         'a pane that is not a launcher is left alone, whatever the controller asked for');
      tmuxKill(real);
    }
    const outside = await relay({ argv: ['version'], cwd: '/etc' });
    ok(outside.status === 200 && outside.code === 0 && !/etc/.test(outside.out),
       'a cwd outside the project\'s trees is ignored: the verb runs in the project directory');
    // The two lists — the verbs bb relays and the verbs the server accepts —
    // are one contract kept in two files, and this is what keeps them one.
    const bbList = (readFileSync(`${REPO}/scripts/bb`, 'utf8').match(/^BB_RELAY_VERBS=" (.*) "$/m) || [])[1]
      ?.split(' ').filter(Boolean).sort();
    const srvList = execFileSync('python3', ['-c', `
import ast, re
src = open(${JSON.stringify(REPO + '/scripts/dashboard/server.py')}).read()
m = re.search(r'RELAY_VERBS = frozenset\\(\\((.*?)\\)\\)', src, re.S)
print(' '.join(sorted(ast.literal_eval('(' + m.group(1) + ')'))))`], { encoding: 'utf8' }).trim().split(' ');
    ok(bbList && bbList.join(' ') === srvList.join(' '),
       `bb's BB_RELAY_VERBS and the server's RELAY_VERBS are the same list (${bbList?.length} verbs)`);
    await relay({ argv: ['roadmap', 'rm', String(((added.out || '').match(/added R(\d+)/) || [])[1]), 'test'] });
  }

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
    // The machine's own tools, detected rather than assumed: the fixture
    // has a dpkg and a netplan (both stubs, found by path), so that is
    // what a system job there would go through, and the row can say so.
    ok(before.reported.distro && before.reported.distro.pkg === 'apt'
       && before.reported.distro.network === 'netplan' && typeof before.reported.distro.family === 'string',
       `...and which package manager and network backend it has (${JSON.stringify(before.reported.distro)})`);
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

    // ---- a store under a share that is not mounted ------------------------
    // The silent failure this refuses: a share in fstab but not mounted
    // leaves its mountpoint an ordinary empty directory, mkdir makes the
    // store inside it, and everything lands on the node's own disk while
    // the row reports a healthy store with plenty of room.
    {
      const MOUNTS = [{ type: 'nfs', source: 'nas:/mnt/user/appdata', path: '/mnt/appdata' },
                      { type: 'nfs', source: 'nas:/mnt/user/tank', path: `${DIR}/fakeshare` }];
      await api('/api/v1/nodes', { action: 'config', id: minted.id,
        config: { mounts: MOUNTS, stores: { cache: `${DIR}/agentcache`,
                    packages: `${DIR}/fakeshare/packages`, artifacts: `${DIR}/agentartifacts` },
                  network: { mode: 'dhcp' } } });
      const j = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      const r = await until(async () => {
        const x = await api(`/api/v1/jobs?id=${j.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 30000);
      ok(r && r.state === 'failed' && /is NOT mounted/.test(r.log) && /own disk/.test(r.log),
         `a store inside a configured share that is not mounted is refused, and says why (${r?.state})`);
      ok(!existsSync(`${DIR}/fakeshare/packages`),
         '...and nothing was created there, so no data can land on the local disk by mistake');
      const n2 = await nodeById(minted.id);
      ok(n2.reported.stores.packages.path === `${DIR}/agentpackages`,
         '...and the packages store still points where it did');
    }

    // ---- moving a store brings its contents with it ------------------------
    // It used to just repoint: the node started using an empty directory and
    // the toolchains stayed behind, with nothing saying so.
    {
      mkdirSync(`${PK}/android`, { recursive: true });
      // ...with a JDK in it, so "a toolchain the node reports" is the store's
      // answer and not this machine's: the gap test below turns on java being
      // there and flutter not, whichever box runs the suite.
      mkdirSync(`${PK}/jdk/bin`, { recursive: true });
      writeFileSync(`${PK}/jdk/bin/java`, '#!/bin/sh\necho \'openjdk version "21.0.0"\' >&2\n', { mode: 0o755 });
      writeFileSync(`${PK}/android/marker`, 'a toolchain lives here');
      mkdirSync(`${DIR}/agentcache`, { recursive: true });
      writeFileSync(`${DIR}/agentcache/gradle-blob`, 'rebuildable');
      await api('/api/v1/nodes', { action: 'config', id: minted.id,
        config: { mounts: [{ type: 'nfs', source: 'nas:/mnt/user/appdata', path: '/mnt/appdata' }],
                  stores: { cache: `${DIR}/agentcache2`, packages: `${DIR}/agentpackages2`,
                            artifacts: `${DIR}/agentartifacts` },
                  network: { mode: 'dhcp' } } });
      const j = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      const r = await until(async () => {
        const x = await api(`/api/v1/jobs?id=${j.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 60000);
      ok(r && r.state === 'succeeded'
         && readFileSync(`${DIR}/agentpackages2/${SCOPE}/android/marker`, 'utf8') === 'a toolchain lives here',
         `moving a store copies what was in it to the new place (${r?.state})`);
      ok(existsSync(`${PK}/android/marker`) && /left in place/.test(r.log),
         '...and never deletes the source, so a half-finished move still serves');
      ok(/agentpackages stays \(Directory not empty\)/.test(r.log) && /remove it yourself/.test(r.log),
         '...so the old directory is not tidied away either, and the log says which one holds it');
      ok(!existsSync(`${DIR}/agentcache2/gradle-blob`) && /a cache is rebuildable/.test(r.log),
         '...while the cache is left behind rather than copied, and the log says why');
      // The copy does not demand ownership it cannot set. A share exported
      // all_squash — which is what the projects and SDK shares here ARE —
      // refuses every chown, and `cp -a` then exits non-zero having copied
      // every byte correctly: the move read that as a failed copy, refused
      // to repoint, and left the data in the new place saying it had not
      // moved. This agent asks first, and says which arrangement it found.
      ok(/squashes ownership/.test(r.log) && /--no-preserve=ownership/.test(r.log)
         && !/Operation not permitted/.test(r.log),
         `...and where ownership cannot be set the copy stops asking for it, rather than `
         + `exiting non-zero having copied every byte (${
             (r.log.match(/^.*ownership.*$/m) || ["no line about ownership"])[0].slice(0, 90)})`);
      const n2 = await until(async () => {
        const n = await nodeById(minted.id);
        return n.reported.stores.packages.path === `${DIR}/agentpackages2` ? n : null;
      });
      ok(n2 !== null, '...and the census reports the store where it now is');
      // ---- and the empty directories it made ARE taken back ---------------
      // Only the ones it created, only when they are empty. A store
      // configured and never written to otherwise leaves a tree nobody
      // wants, and there is no telling ours from the operator's afterwards
      // — so it is recorded at the moment of creation.
      mkdirSync(`${DIR}/pre`, { recursive: true });
      writeFileSync(`${DIR}/pre/operators-file`, 'not ours');
      await api('/api/v1/nodes', { action: 'config', id: minted.id,
        config: { mounts: [], stores: { artifacts: `${DIR}/pre/a1/a2/art` }, network: { mode: 'dhcp' } } });
      const mk = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      const mkr = await until(async () => {
        const x = await api(`/api/v1/jobs?id=${mk.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 60000);
      ok(mkr && mkr.state === 'succeeded' && existsSync(`${DIR}/pre/a1/a2/art`)
         && /made .*\/pre\/a1/.test(mkr.log),
         `a store path is created, parents and all, and the log says what it made (${mkr?.state})`);
      // EMPTY, which is what the next assertion is named after and what the
      // agent's rule turns on: it takes back a directory it made only while
      // there is nothing in it, because nothing is ever deleted from a store
      // it is moving off. The move above copied the previous store's contents
      // in, so on a machine where that store had any — which is every node,
      // and not the controller — `art` was not empty and the agent said so,
      // correctly. The test asserted the cleanup without arranging for it
      // (B84).
      rmSync(`${DIR}/pre/a1/a2/art`, { recursive: true, force: true });
      mkdirSync(`${DIR}/pre/a1/a2/art`, { recursive: true });
      await api('/api/v1/nodes', { action: 'config', id: minted.id,
        config: { mounts: [], stores: { artifacts: `${DIR}/agentartifacts` }, network: { mode: 'dhcp' } } });
      const un = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      const unr = await until(async () => {
        const x = await api(`/api/v1/jobs?id=${un.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 60000);
      ok(unr && unr.state === 'succeeded' && !existsSync(`${DIR}/pre/a1`) && /removed .*\/pre\/a1\/a2\/art/.test(unr.log),
         `moving off an empty store takes back the directories it made for it (${
           unr?.state}; a1 still there: ${existsSync(`${DIR}/pre/a1`)}; log: ${
           (unr?.log || '').trim().split('\n').slice(-3).join(' / ').slice(0, 200)})`);
      ok(existsSync(`${DIR}/pre/operators-file`) && existsSync(`${DIR}/pre`),
         '...and stops at the one it did not make, whatever is in it');

      // Put it back, so what follows runs against the stores it expects.
      await api('/api/v1/nodes', { action: 'config', id: minted.id,
        config: { mounts: [{ type: 'nfs', source: 'nas:/mnt/user/appdata', path: '/mnt/appdata' },
                           { type: 'virtiofs', source: 'projects', path: '/workspace', ro: true }],
                  stores: { cache: `${DIR}/agentcache`, packages: `${DIR}/agentpackages`,
                            artifacts: `${DIR}/agentartifacts` },
                  network: { mode: 'static', address: '10.9.9.9/24', gateway: '10.9.9.1', dns: ['10.9.9.1'] } } });
      const back = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      await until(async () => {
        const x = await api(`/api/v1/jobs?id=${back.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 60000);
    }

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

    // ---- the terminal goes to the node (roadmap #24, phase 10b) --------------
    // alpha is bound to agentbox now, whose census says its session half is
    // up and /workspace mounted (the stub reports what the agent measures;
    // the harness runs in a container whose /workspace IS a mount). So the
    // controller's /term proxy dials agentbox's ttyd — the stub above, which
    // answers with the request line — with the account, its name and a
    // session token stamped into the URL.
    {
      const term = async (arg, hdr = auth) => {
        const r = await fetch(URL.replace(/\/$/, '') + '/term/ws?arg=' + encodeURIComponent(arg),
                              { headers: hdr, redirect: 'manual' });
        return { status: r.status, body: await r.text() };
      };
      const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
      const rows = (await api('/api/status')).projects;
      const alpha = rows.find(p => p.name === 'alpha');
      ok(alpha?.session_at === 'agentbox' && alpha?.session_why === '',
         `the project row says where its sessions run (${alpha?.session_at})`);
      // In this harness the "node" is a process in the same container, so
      // its boot id IS this container's; what is asserted is that the row
      // carries the node's own answer, not that the two differ.
      ok(alpha?.session_boot === nodeBoot && nodeBoot !== '',
         '...and carries that node\'s boot for the terminal\'s URL');
      // A transcript is one directory for both machines (roadmap #24 step
      // 3): the home's projects directory is a link onto the projects
      // share, so one a node's session wrote is offered here to resume.
      const slug = `${DIR}/ws/alpha`.replace(/\//g, '-');
      const shared = `${DIR}/ws/.claude/${uid}/projects`;
      ok(lstatSync(`${DIR}/home/.claude/projects`).isSymbolicLink()
         && readlinkSync(`${DIR}/home/.claude/projects`) === shared && existsSync(`${DIR}/ws/.claude/.bbignore`),
         `the owner's ~/.claude/projects is a link onto the share, which carries a .bbignore (${readlinkSync(`${DIR}/home/.claude/projects`).replace(DIR, '…')})`);
      mkdirSync(`${shared}/${slug}`, { recursive: true });
      writeFileSync(`${shared}/${slug}/0123abcd-0000-4000-8000-000000000000.jsonl`, '{}\n');
      ok((await api('/api/status')).projects.find(p => p.name === 'alpha')?.last_claude?.id === '0123abcd-0000-4000-8000-000000000000',
         'a transcript written on the share — as a node\'s session writes it — is offered here to resume');
      await refreshUntil(page, () =>
        ((state?.projects || []).find(p => p.name === 'alpha') || {}).session_at === 'agentbox');
      const url = await page.evaluate(() => ttydUrl('claude:alpha'));
      ok(decodeURIComponent(url).endsWith(`claude:alpha:b:${nodeBoot}`),
         `the page stamps the node's boot into a node-bound terminal's URL (${decodeURIComponent(url)})`);
      const urlHere = await page.evaluate(() => ttydUrl('claude:beta'));
      ok(decodeURIComponent(urlHere).endsWith(`claude:beta:b:${(await api('/api/status')).boot}`),
         '...and this container\'s into everybody else\'s');
      const c = await term('claude:alpha');
      ok(c.status === 200 && /^ttyd-stub GET \/ws\?/.test(c.body),
         `a Claude session on alpha is relayed to agentbox's ttyd (${c.status}: ${c.body.slice(0, 40)})`);
      const args = (c.body.match(/arg=[^& ]+/g) || []).map(x => decodeURIComponent(x.slice(4)));
      ok(args[0] === `u:${uid}:claude:alpha`,
         `...with the account stamped into the argument as it is locally (${args[0]})`);
      ok(/^tok:bbs_[A-Za-z0-9_-]+$/.test(args[1] || '') && args[2] === 'name:test' && args[3] === 'owner:1',
         `...and the node's extras after it: a session token, the account's name, and that it is the owner — so the tree and the transcript slug are the same there (${args.slice(1).map(x => x.slice(0, 12)).join(', ')})`);
      const sh = await term('shell:alpha');
      ok(sh.status === 200 && /arg=u%3A/.test(sh.body) && /tok%3Abbs_/.test(sh.body),
         'a project shell goes there too, with the account and a token — bb in that shell reaches the notebook with it');
      const root = await term('shell');
      ok(root.status === 502 && /terminal server is not running/.test(root.body),
         'the workspace shell stays on this container (which the harness runs no ttyd for)');
      const nonode = await term('claude:beta');
      ok(nonode.status === 502 && /terminal server is not running/.test(nonode.body),
         'a project with no node keeps its session here');
      // Bound to a node that cannot take one: the sandbox row reports its
      // session half up on a READ-ONLY projects share, so the button is
      // dead with the reason and the proxy says the same rather than
      // starting a session that could not save a file.
      const sandbox = (await api('/api/v1/nodes')).nodes.find(n => n.name === 'sandbox');
      await api('/api/prefs', { project: 'beta', node: sandbox.id });
      const beta = (await api('/api/status')).projects.find(p => p.name === 'beta');
      ok(beta?.session_at === 'sandbox' && /read-only/.test(beta?.session_why || '')
         && /bb-sandbox readonly \/workspace off/.test(beta?.session_why || ''),
         `a project bound to a node that mounts the share read-only carries the reason and the fix on its row (${(beta?.session_why || '').slice(0, 60)})`);
      const refused = await term('claude:beta');
      ok(refused.status === 503 && /sessions run on sandbox/.test(refused.body)
         && /Unbind the node/.test(refused.body),
         '...and the proxy refuses with the same sentence rather than starting it here');
      // ...unless asked for here, explicitly: the dead button's menu sends
      // here=1, and the session runs on this container — which the harness
      // runs no ttyd for, so the answer is the local proxy's own 502, not
      // the node's refusal.
      const here = await fetch(URL.replace(/\/$/, '') + '/term/ws?arg=' + encodeURIComponent('claude:beta') + '&here=1',
                               { headers: auth, redirect: 'manual' });
      const hereBody = await here.text();
      ok(here.status === 502 && /terminal server is not running/.test(hereBody),
         'asked for explicitly, a session on a project whose node refuses opens on this container instead');
      await api('/api/prefs', { project: 'beta', node: '' });
    }
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
    // Bug #45: a plain exec — which is what bb build, bb test and bb run
    // submit — got a bare PATH, because the node's SDK environment was only
    // applied in the bb-verb branch. Measured on a real node: java and go
    // NOT-ON-PATH, JAVA_HOME unset, on a node whose census reported both.
    {
      mkdirSync(`${PK}/jdk/bin`, { recursive: true });
      mkdirSync(`${PK}/go/bin`, { recursive: true });
      // An android system image in the node's own store, and an AVD in the
      // data store built on it (roadmap #20). The agent walks for these
      // rather than running `bb packages images`, which is the same listing plus
      // a du over tens of gigabytes of NFS every ten minutes.
      const IMG = `${PK}/android/system-images`;
      mkdirSync(`${IMG}/android-34/google_apis/x86_64`, { recursive: true });
      writeFileSync(`${IMG}/android-34/google_apis/x86_64/system.img`, 'x');
      mkdirSync(`${IMG}/android-33/google_apis/x86_64`, { recursive: true });
      mkdirSync(`${DIR}/agentdata/avd/fbnode.avd`, { recursive: true });
      writeFileSync(`${DIR}/agentdata/avd/fbnode.avd/config.ini`,
        'abi.type=x86_64\nimage.sysdir.1 = system-images/android-34/google_apis/x86_64/\n');
      const envrun = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', 'echo "root=$SDK_ROOT"; echo "java=$JAVA_HOME"; '
                         + 'echo "android=$ANDROID_HOME"; echo "path=$PATH"; echo "cilog=$BB_CI_LOG_DIR"'] });
      const ef = await until(async () => {
        const r = await api(`/api/v1/jobs?id=${envrun.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 30000);
      const log = ef?.log || '';
      ok(/root=.*agentpackages/.test(log) && /java=.*agentpackages\/linux-[a-z0-9_]+\/jdk/.test(log)
         && /android=.*agentpackages\/linux-[a-z0-9_]+\/android/.test(log),
         `a build job gets the node's package store root, JAVA_HOME and ANDROID_HOME (${
           (log.match(/root=.*/) || [''])[0].slice(0, 60)})`);
      ok(/cilog=.*agentdata\/ci-logs/.test(log),
         '...and where this node archives CI logs, under the data store both accounts can read');
      // An empty directory is not a toolchain. cmdline-tools existed on the
      // operator's node as an empty folder with no sdkmanager, and
      // platform-tools not at all, and the census called android-sdk present
      // — so a job needing adb was admitted and failed there rather than
      // being refused here.
      mkdirSync(`${PK}/android/cmdline-tools`, { recursive: true });
      const bare = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', 'true'] });
      if (bare.job) await until(async () => {
        const r = await api(`/api/v1/jobs?id=${bare.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 30000);
      const cens = await until(async () => {
        const n = await nodeById(minted.id);
        return n?.reported?.toolchains ? n : null;
      });
      ok(cens && !(cens.reported.toolchains || {})['android-sdk'],
         'an empty cmdline-tools directory is not reported as an Android SDK');
      // ...and a job refused on that answer says how old the answer is, and
      // asks the node for a fresh one. The census rides hello every ten
      // minutes, so a refusal can be reasoning about the node as it was nine
      // of them ago — the operator met exactly that: a command refused, the
      // identical retry allowed, nothing on screen to explain it.
      const refused = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', 'command -v adb'] });
      ok(/has no android-sdk/.test(refused.error || ''),
         `a command naming adb is refused on a node with none (${
           (refused.error || '').slice(0, 60)})`);
      const fresh = await until(async () => {
        const n = await nodeById(minted.id);
        return n?.reported?.at ? n : null;
      });
      ok(fresh && typeof fresh.reported.at === 'number',
         '...and the census carries when it was taken, which the refusal quotes');
      // The refusal above asked the node for a fresh census; this is the
      // first one taken since the image tree was made, so it is waited for
      // rather than read off whatever was already on the row.
      const withImgs = await until(async () => {
        const n = await nodeById(minted.id);
        return (n?.reported?.images || []).length ? n : null;
      }, 30000);
      const im = (withImgs?.reported?.images || []);
      ok(im.length === 1 && im[0].id === 'system-images;android-34;google_apis;x86_64'
         && JSON.stringify(im[0].avds) === JSON.stringify(['fbnode']),
         `the census reports the store's system images and the AVDs built on them (${
           JSON.stringify(im)})`);
      ok(!im.some(x => /android-33/.test(x.id)),
         '...and an empty image directory is not one: a half-removed tree is not a bootable image');
      ok(/path=[^\n]*agentpackages\/linux-[a-z0-9_]+\/jdk\/bin/.test(log)
         && /path=[^\n]*agentpackages\/linux-[a-z0-9_]+\/go\/bin/.test(log),
         '...and every toolchain the store holds is on its PATH, not just the JDK');
      // ...composed from the catalog's layout, sent at hello, rather than
      // from a table in the agent that has to agree with three others.
      const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
      ok(Array.isArray(st.layout) && st.layout.some(e => e.name === 'jdk' && e.tool === 'bin/java')
         && st.layout.some(e => e.name === 'node' && (e.bin || []).includes('bin')),
         `the controller tells the node where packages land, and it keeps it (${
           (st.layout || []).length} entries)`);
    }
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
    // ...unless the tree says how it is tested. "Run the tests" has one
    // conventional answer per ecosystem, so a project nobody configured
    // still answers — and says once that nothing was set, because a command
    // nobody typed should not look like one somebody did.
    writeFileSync(`${DIR}/ws/alpha/go.mod`, 'module alpha\n');
    let fell = '';
    try { fell = execFileSync('bash', [`${REPO}/scripts/bb`, 'test'],
      { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env, stdio: 'pipe' }).toString(); }
    catch (e) { fell = String(e.stderr) + String(e.stdout); }
    rmSync(`${DIR}/ws/alpha/go.mod`, { force: true });
    ok(/nothing set for tests on alpha, so: go test \.\/\.\.\./.test(fell),
       'a project with a go.mod answers bb test with go test, saying it fell back');
    const sess = (await api('/api/v1/jobs?project=alpha&n=3')).jobs;
    ok(sess.some(j => j.requested_by === 'session:alpha'), 'a run from a session is attributed to the session');
  }

  // ---- toolchains on a node (phase 6) ----------------------------------------
  // A package install is a job: the bundle (bb, its library, the catalog)
  // travels by digest into the node's packages store and runs there. The
  // package asked for is not installed, so this proves the channel and not
  // a download.
  {
    const ttydsBefore = ttydRuns().filter(r => r.env.BUILDERBOT_NODE === minted.id).length;
    const pj = await api('/api/packages', { action: 'remove', names: ['flutter'], node: minted.id });
    ok(pj.ok && /^j_/.test(pj.job), `a package job is queued on the node (${pj.job || pj.error})`);
    const pfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${pj.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    // Unpacked by this job, or already there: the session half fetched the
    // same bundle at start (roadmap #24), and a second unpack of the same
    // digest is exactly what the digest is for.
    ok(pfin && pfin.type === 'package'
       && (/bb .* unpacked into .*agentpackages\/linux-[a-z0-9_]+\/\.bb/.test(pfin.log)
           || existsSync(`${PK}/.bb/current/scripts/bb`))
       && /== bb packages remove flutter/.test(pfin.log) && /not installed|unknown package/.test(pfin.log),
       `the bundle lands in the packages store and bb runs from it there (${pfin?.state}: ${(pfin?.log || '').slice(-500).replace(/\n/g, ' / ')})`);
    ok(existsSync(`${PK}/.bb/bundle.tar`), '...and stays for the next one');
    // The store changed, so the ttyds are started again with an environment
    // built from it — a session opened now finds the new tool on PATH.
    const renewed = await until(async () => {
      const n = await nodeById(minted.id);
      const now = ttydRuns().filter(r => r.env.BUILDERBOT_NODE === minted.id).length;
      return now > ttydsBefore && n?.reported?.session?.up ? now : null;
    }, 30000, 500);
    ok(renewed !== null, `...and the session ttyds are restarted onto the changed store (${ttydsBefore} -> ${renewed})`);
    // The store's own directories decide what is installed there — not the
    // census's placement summary, which named six toolchains and called four
    // installed packages missing on the operator's shared package store.
    mkdirSync(`${PK}/zig`, { recursive: true });
    mkdirSync(`${PK}/android/ndk`, { recursive: true });
    // ...except a directory without the file that completes the package:
    // playwright's browsers from before the recipe carried the module.
    mkdirSync(`${PK}/playwright/chromium-1234`, { recursive: true });
    mkdirSync(`${PK}/node/bin`, { recursive: true });   // playwright requires node
    // The store listing rides the census, which refreshes at hello — and a
    // job that touches the node ends in one, which is why installing a
    // package updates this list without waiting ten minutes. Any such job
    // will do here.
    const poke = await api('/api/v1/nodes', { action: 'cache-clear', id: minted.id });
    await until(async () => {
      const r = await api(`/api/v1/jobs?id=${poke.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    const view = await until(async () => {
      const v = await api(`/api/packages?node=${minted.id}`);
      return v.items?.some(i => i.name === 'zig' && i.installed) ? v : null;
    }, 30000);
    ok(view && view.node === minted.id && view.root === PK,
       'the Tools tab reads that node\'s own packages store');
    ok(view && view.items.find(i => i.name === 'zig')?.installed === true
       && view.items.find(i => i.name === 'android:ndk')?.installed === true,
       'a package present in the store reads as installed, whatever the census summarises');
    ok(view && view.items.find(i => i.name === 'swift')?.installed === false
       && view.items.every(i => i.unknown === false),
       '...and one that is not there reads as absent, not as unknown');
    ok(view && view.items.find(i => i.name === 'playwright')?.installed === false,
       '...and a playwright directory without its module reads as not installed, so Install is offered (the row said installed and offered nothing)');
    // A recipe's system packages (the catalog's `system.apt`). This agent is
    // not root and has no sandbox stamp, so it is not the one to install
    // them: it names them and carries on to the recipe — which the stub npm
    // stops before anything is downloaded.
    const sj = await api('/api/packages', { action: 'install', names: ['playwright'], node: minted.id });
    ok(sj.ok && /^j_/.test(sj.job), `installing playwright on the node queues a job (${sj.job || sj.error})`);
    const sfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${sj.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(sfin && /needs system packages this node's owner installs/.test(sfin.log)
       && /libatk1\.0-0t64/.test(sfin.log) && /libnss3/.test(sfin.log),
       `a recipe's system packages are named for the owner on a node the agent does not administer (${
         (sfin?.log || '').match(/needs system packages[^\n]*/)?.[0]?.slice(0, 90)})`);
    ok(sfin && sfin.state === 'failed' && /npm: stub/.test(sfin.log)
       && !existsSync(`${PK}/playwright/node_modules`),
       '...and the recipe then ran as the job account, where the stub npm stopped it before a download');
  }

  // ---- the idle rule reaches the node and stays there (idle.py) -----------
  // The controller's setting rides the hello reply into node.json, where the
  // agent enforces it on its own tmux — controller up or down. A change is
  // heard on the next poll, not the next ten-minute hello.
  {
    const on = await api('/api/idle', { minutes: 3 });
    ok(on.ok && on.minutes === 3, 'the idle rule is set on the controller');
    const kept = await until(() => {
      const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
      return st.session_idle_minutes === 3 ? st : null;
    }, 30000, 500);
    ok(kept !== null, 'the node hears it on its next poll and keeps it in node.json, to enforce with the controller down');
    const off = await api('/api/idle', { minutes: 0 });
    const cleared = await until(() => JSON.parse(readFileSync(NODE_JSON, 'utf8')).session_idle_minutes === 0 ? true : null, 30000, 500);
    ok(off.ok && cleared, '...and 0 reaches it the same way');
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
    const renv = existsSync(`${DIR}/runner/.env`) ? readFileSync(`${DIR}/runner/.env`, 'utf8') : '';
    ok(/^BB_CI_LOG_DIR=.*agentdata\/ci-logs$/m.test(renv) && existsSync(`${DIR}/agentdata/ci-logs`),
       'the runner\'s .env points its workflows\' archive step at the data store, and the directory is there');
    // The rest of that file is the node's job environment: without it a CI
    // job's PATH was the bare system's, and the browser suite skipped with
    // exit 0 on every run (bug B74).
    ok(/^SDK_ROOT=.*(agentpackages|fakeshare\/packages)\/linux-[a-z0-9_]+$/m.test(renv)
       && /^PATH=.*(agentpackages|fakeshare\/packages)/m.test(renv)
       && /^ANDROID_HOME=.*\/android$/m.test(renv) && /^BB_CI_LOG_DIR=/m.test(renv),
       '...and carries the same toolchain environment every bb job on the node gets, so CI sees the store');
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
    ok(efin && efin.state === 'succeeded' && /API levels with a system image here/.test(efin.log),
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
    ok(/bb emu list on agentbox/.test(cli) && /API levels with a system image here/.test(cli) && /succeeded/.test(cli),
       `bb emu from a shell goes to the project's node and streams the answer back (${cli.replace(/\s+/g, ' ').slice(0, 120)})`);
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

  // ---- the console half does not drift from the agent's -------------------
  // One invariant, two ends: the agent refuses to point a store at a share
  // that is not mounted, and bb-sandbox refuses to unmount a share a store
  // is inside. The way they are kept in step is structural — bb-sandbox
  // reads the agent's own node.json instead of keeping a list of stores —
  // and this proves they answer the one shared question the same way. It
  // runs the REAL bb-sandbox, pulled out of the provisioner the same way
  // bb lint pulls it out for shellcheck.
  {
    const SBDIR = `${DIR}/sandbox-src`;
    mkdirSync(SBDIR, { recursive: true });
    execFileSync('python3', [`${REPO}/scripts/lib/embedded-shell.py`, SBDIR,
                             `${REPO}/nodes/provision-linux.sh`], { stdio: 'pipe' });
    const SB = `${SBDIR}/provision-linux.sh-BBSANDBOX`;
    const NJ = `${DIR}/contract-node.json`;
    writeFileSync(NJ, JSON.stringify({ stores: {
      data: '/var/lib/builderbot/data', packages: '/mnt/tank/builderbot/packages',
      cache: '/mnt/tank/cache', artifacts: '/mnt/other/art' } }));
    // Both sides, on the same cases. A store is "in" a mount when the mount
    // is its own path or a parent of it — and NOT when the mount's path is
    // merely a string prefix (/mnt/tank2 is not inside /mnt/tank).
    // '/mnt/tan' and '/var/lib/builderbot/dat' are the ones that matter: a
    // naive startswith says they hold the stores under /mnt/tank and
    // .../data, and a path parent is not a string prefix. Both sides have
    // to get those wrong the same way to pass, which is the drift this is
    // for. '/mnt/tank2' is the other direction.
    const CASES = ['/mnt/tank', '/mnt/tank/builderbot', '/mnt/tan', '/mnt/tank2', '/mnt',
                   '/mnt/other', '/var/lib/builderbot/data', '/var/lib/builderbot/dat',
                   '/var/lib', '/nowhere'];
    const stores = JSON.parse(readFileSync(NJ, 'utf8')).stores;
    const sandbox = CASES.map(mp => {
      const out = execFileSync('bash', ['-c',
        `NODE_JSON=${JSON.stringify(NJ)}; ` +
        `eval "$(sed -n '/^stores_under() {/,/^}/p' ${JSON.stringify(SB)})"; ` +
        `stores_under ${JSON.stringify(mp)}`], { encoding: 'utf8' });
      return out.split('\n').map(l => l.split(' ')[0]).filter(Boolean).sort().join(',');
    });
    const agent = CASES.map(mp => execFileSync('python3', ['-c',
      `import importlib.util as u, json, sys\n` +
      `s = u.spec_from_file_location('a', sys.argv[1]); m = u.module_from_spec(s); s.loader.exec_module(m)\n` +
      `st = json.loads(sys.argv[3])\n` +
      `print(','.join(sorted(r for r, p in st.items() if m.mount_covering(p, [{'path': sys.argv[2]}]))))`,
      `${REPO}/scripts/agent/builderbot-agent.py`, mp, JSON.stringify(stores)],
      { encoding: 'utf8' }).trim());
    const disagree = CASES.filter((_, i) => sandbox[i] !== agent[i]);
    ok(disagree.length === 0,
       `bb-sandbox and the agent agree on which stores a mount holds, in all ${CASES.length} cases${
         disagree.length ? ` — they differ on ${disagree.join(', ')}: ${
           disagree.map(c => `${c} sandbox[${sandbox[CASES.indexOf(c)]}] agent[${agent[CASES.indexOf(c)]}]`).join('; ')}` : ''}`);
    ok(sandbox[CASES.indexOf('/mnt/tank')] === 'cache,packages'
       && sandbox[CASES.indexOf('/mnt/tan')] === '' && sandbox[CASES.indexOf('/mnt/tank2')] === ''
       && sandbox[CASES.indexOf('/var/lib/builderbot/dat')] === ''
       && sandbox[CASES.indexOf('/nowhere')] === '',
       `...and the answers are the right ones, not merely the same (/mnt/tank holds ${
         sandbox[CASES.indexOf('/mnt/tank')] || 'nothing'})`);
    // And the refusal itself is in the console tool, not only in the agent.
    ok(/bb-sandbox remove %s --force/.test(readFileSync(SB, 'utf8'))
       && /holds \$\(printf/.test(readFileSync(SB, 'utf8')),
       'bb-sandbox refuses to unmount a share a store is inside, and its list marks one that holds them');
  }

  // ---- the agent's own update, driven from the tab (roadmap #17) ---------------
  {
    const all = await api('/api/v1/nodes');
    ok(/^sha256:[0-9a-f]{64}$/.test(all.agent?.digest || '')
       && /^\d+\.\d+\.\d+$/.test(all.agent.version || ''),
       `the node list carries the agent this controller ships, digest and version (${
         all.agent?.version})`);
    const lc = await api('/api/v1/nodes', { action: 'update-agent', id: 'local' });
    ok(/only an agent node/.test(lc.error || ''), 'local has no agent to update');
    const cur = await api('/api/v1/nodes', { action: 'update-agent', id: minted.id });
    ok(cur.ok && cur.current === true && cur.version === all.agent.version,
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
    // Enrolling is a dialog, like New project — it used to be a panel at the
    // foot of the tab, below everything about the machine you were looking at.
    await page.click('#ndEnroll');
    await page.waitForSelector('#ndmodal:not([hidden]) #ndEnName', { timeout: 10000 });
    ok(await page.$('.nodestab #ndEnName') === null,
       'Enroll node opens a dialog rather than a panel at the foot of the tab');
    await page.fill('#ndEnName', 'second');
    await page.click('#ndEnGo');
    await page.waitForSelector('#ndmodal .ndtoken', { timeout: 15000 });
    const shown = await page.$eval('#ndmodal .ndtoken', e => e.textContent);
    ok(/bbe_/.test(shown) && /provision-linux\.sh/.test(shown) && /provision-macos\.sh/.test(shown) && /--controller/.test(shown),
       'Enroll node shows the one-time token inside the provisioner commands, Linux and Mac');
    // The backdrop does not close the one thing here shown once.
    await page.mouse.click(5, 5);
    ok(await page.$('#ndmodal .ndtoken') !== null,
       '...and a stray click on the room around it does not take the command away');
    await page.click('#ndTokDone');
    // waitForFunction, not waitForSelector: the default there is "visible",
    // which a hidden dialog never becomes.
    await page.waitForFunction(() => document.getElementById('ndmodal').hidden,
                               { timeout: 10000 });
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
//
// BY NAME as well as by kind. The harness's docker host used to be an
// `ssh` row, so "every agent node" could not reach it; since roadmap #24 it
// is an enrolled agent node like any other, and this loop retired it — after
// which every file below had no daemon and devapp.mjs died on the first row
// it waited for. nodes.mjs spares it the same way.
for (const n of (await api('/api/v1/nodes')).nodes)
  if (n.kind === 'agent' && n.name !== 'sandbox')
    await api('/api/v1/nodes', { action: 'retire', id: n.id });
const left = (await api('/api/v1/nodes')).nodes;
ok(!left.some(n => n.kind === 'agent' && n.name !== 'sandbox')
   && left.some(n => n.id === 'local') && left.some(n => n.name === 'sandbox'),
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

// ---- the same network spec through NetworkManager ---------------------------
// The job the controller sends is one shape — mode, address, gateway, dns —
// and the agent picks the backend the machine has. With no netplan and an
// nmcli that says it is running, that is NetworkManager: the connection's
// ipv4 keys are modified and brought up, a repeat is "already applied", and
// a change the controller cannot confirm is put back the same way.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys, tempfile
os.environ['BUILDERBOT_NETPLAN_BIN'] = '/nonexistent/netplan'
os.environ['BUILDERBOT_NMCLI_BIN'] = ${JSON.stringify(`${DIR}/bin/nmcli`)}
os.environ['BUILDERBOT_SANDBOX_BIN'] = ${JSON.stringify(`${DIR}/bin/bb-sandbox`)}
spec = importlib.util.spec_from_file_location('agent', ${JSON.stringify(AGENT)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.DIAL_BACK_S = 1
a = m.Agent.__new__(m.Agent)
a.state = {'stores': {}}
class J:
    def __init__(self): self.lines = []
    def say(self, t): self.lines.append(t)
    def flush(self): pass
state = lambda: dict(l.split('=', 1) for l in open(${JSON.stringify(`${DIR}/nm.state`)}).read().splitlines() if '=' in l)
want = {'network': {'mode': 'static', 'address': '10.1.1.5/24', 'gateway': '10.1.1.1', 'dns': ['10.1.1.1', '10.1.1.2'], 'interface': 'eth0'}}
a.hello = lambda: (200, {})
j1 = J(); s1 = a._apply_network(j1, want); st1 = state()
j2 = J(); s2 = a._apply_network(j2, want)
a.hello = lambda: (503, {'error': 'unreachable'})
j3 = J(); s3 = a._apply_network(j3, {'network': {'mode': 'dhcp', 'interface': 'eth0'}}); st3 = state()
print(json.dumps({'distro': m.distro_now(), 'r1': s1, 'log1': ''.join(j1.lines), 'st1': st1,
                  'r2': s2, 'log2': ''.join(j2.lines), 'r3': s3, 'log3': ''.join(j3.lines), 'st3': st3,
                  'calls': open(${JSON.stringify(`${DIR}/nmcli.log`)}).read()}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(R.distro.network === 'networkmanager',
     `with no netplan and a running NetworkManager, that is the backend the agent detects (${JSON.stringify(R.distro)})`);
  ok(R.r1[0] === 'succeeded' && R.st1['ipv4.method'] === 'manual' && R.st1['ipv4.addresses'] === '10.1.1.5/24'
     && R.st1['ipv4.gateway'] === '10.1.1.1' && R.st1['ipv4.dns'] === '10.1.1.1,10.1.1.2'
     && /con up Wired connection 1/.test(R.calls) && /dialed back/.test(R.log1),
     `the same static spec lands as the connection's ipv4 keys, brought up and confirmed (${R.r1[0]}: ${JSON.stringify(R.st1)})`);
  ok(R.r2[0] === 'succeeded' && /already applied/.test(R.log2),
     '...and sending it again is "already applied", read back from the connection');
  ok(R.r3[0] === 'failed' && /reverting/.test(R.log3) && R.st3['ipv4.method'] === 'manual'
     && R.st3['ipv4.addresses'] === '10.1.1.5/24',
     `...and a change the controller cannot confirm is put back the same way (${R.r3[0]}: ${JSON.stringify(R.st3)})`);
}

// ---- the family, from os-release; the file backends, from their files --------
// The job spec is one shape for every distribution; what the agent does with
// it is decided on the machine. Three things proven without one: a
// derivative lands with its parent through ID_LIKE (Mint with Debian, Cachy
// with Arch, ...); systemd-networkd is a .network file plus a reload, put
// back on revert; and ifupdown replaces only the interface's own stanza in
// /etc/network/interfaces, keeping the rest of the file byte for byte.
{
  const NB = `${DIR}/nbin`; mkdirSync(NB, { recursive: true });
  // A systemctl that says networkd and wicked are active, on a PATH only
  // this test's python sees — the fixture agent must keep the real answer.
  writeFileSync(`${NB}/systemctl`, `#!/bin/sh
echo "$*" >> "${DIR}/systemctl.log"
case "$*" in "is-active systemd-networkd") echo active ;; *) echo inactive ;; esac
`, { mode: 0o755 });
  for (const b of ['networkctl', 'ifup', 'ifdown'])
    writeFileSync(`${NB}/${b}`, `#!/bin/sh\necho "${b} $*" >> "${DIR}/netfiles.log"\n`, { mode: 0o755 });
  const SAMPLES = {
    mint: 'NAME="Linux Mint"\nID=linuxmint\nID_LIKE="ubuntu debian"\nPRETTY_NAME="Linux Mint 22"\n',
    pop: 'ID=pop\nID_LIKE="ubuntu debian"\nPRETTY_NAME="Pop!_OS 24.04"\n',
    kali: 'ID=kali\nID_LIKE=debian\nPRETTY_NAME="Kali GNU/Linux Rolling"\n',
    raspbian: 'ID=raspbian\nID_LIKE=debian\nPRETTY_NAME="Raspbian GNU/Linux 12"\n',
    fedora: 'ID=fedora\nPRETTY_NAME="Fedora Linux 42 (Server Edition)"\n',
    centos: 'ID="centos"\nID_LIKE="rhel fedora"\nPRETTY_NAME="CentOS Stream 10"\n',
    rocky: 'ID="rocky"\nID_LIKE="rhel centos fedora"\nPRETTY_NAME="Rocky Linux 9.5"\n',
    alma: 'ID="almalinux"\nID_LIKE="rhel centos fedora"\nPRETTY_NAME="AlmaLinux 9.5"\n',
    manjaro: 'ID=manjaro\nID_LIKE=arch\nPRETTY_NAME="Manjaro Linux"\n',
    endeavour: 'ID=endeavouros\nID_LIKE=arch\nPRETTY_NAME="EndeavourOS"\n',
    cachy: 'ID=cachyos\nID_LIKE=arch\nPRETTY_NAME="CachyOS Linux"\n',
    leap: 'ID="opensuse-leap"\nID_LIKE="suse opensuse"\nPRETTY_NAME="openSUSE Leap 16.0"\n',
    tumbleweed: 'ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\nPRETTY_NAME="openSUSE Tumbleweed"\n',
    alpine: 'ID=alpine\nPRETTY_NAME="Alpine Linux v3.21"\n',
    void: 'ID="void"\nPRETTY_NAME="Void Linux"\n',
    gentoo: 'ID=gentoo\nPRETTY_NAME="Gentoo Linux"\n',
    nixos: 'ID=nixos\nPRETTY_NAME="NixOS 25.05 (Warbler)"\n',
    slackware: 'ID=slackware\nPRETTY_NAME="Slackware 15.0 x86_64"\n',
  };
  const WANT = { mint: 'debian', pop: 'debian', kali: 'debian', raspbian: 'debian', fedora: 'rhel',
    centos: 'rhel', rocky: 'rhel', alma: 'rhel', manjaro: 'arch', endeavour: 'arch', cachy: 'arch',
    leap: 'suse', tumbleweed: 'suse', alpine: 'alpine', void: 'void', gentoo: 'gentoo',
    nixos: 'nixos', slackware: 'slackware' };
  mkdirSync(`${DIR}/osrel`, { recursive: true });
  for (const [k, v] of Object.entries(SAMPLES)) writeFileSync(`${DIR}/osrel/${k}`, v);
  const NONE = ['NETPLAN', 'NMCLI', 'DPKG', 'RPM', 'PACMAN', 'APK', 'XBPS_QUERY', 'EMERGE', 'WICKED']
    .map(k => `os.environ['BUILDERBOT_${k}_BIN'] = '/nonexistent/${k.toLowerCase()}'`).join('\n');
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
${NONE}
os.environ['PATH'] = ${JSON.stringify(NB)} + ':' + os.environ.get('PATH', '')
os.environ['BUILDERBOT_NETWORKCTL_BIN'] = ${JSON.stringify(`${NB}/networkctl`)}
os.environ['BUILDERBOT_NETWORKD_DIR'] = nd = tempfile.mkdtemp()
os.environ['BUILDERBOT_INTERFACES_FILE'] = ifs = os.path.join(tempfile.mkdtemp(), 'interfaces')
os.environ['BUILDERBOT_IFUP_BIN'] = ${JSON.stringify(`${NB}/ifup`)}
os.environ['BUILDERBOT_IFDOWN_BIN'] = ${JSON.stringify(`${NB}/ifdown`)}
os.environ['BUILDERBOT_SANDBOX_BIN'] = ${JSON.stringify(`${DIR}/bin/bb-sandbox`)}
spec = importlib.util.spec_from_file_location('agent', ${JSON.stringify(AGENT)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.DIAL_BACK_S = 1
fam = {}
for k in ${JSON.stringify(Object.keys(SAMPLES))}:
    m.OS_RELEASE = os.path.join(${JSON.stringify(`${DIR}/osrel`)}, k)
    fam[k] = m.distro_now()['family']
a = m.Agent.__new__(m.Agent); a.state = {'stores': {}}
class J:
    def __init__(self): self.lines = []
    def say(self, t): self.lines.append(t)
    def flush(self): pass
want = {'network': {'mode': 'static', 'address': '10.2.2.5/24', 'gateway': '10.2.2.1', 'dns': ['10.2.2.1'], 'interface': 'eth0'}}
# networkd: found (the stub systemctl says active), a file written, reverted
nd_backend = m.net_backend().name
a.hello = lambda: (200, {})
j1 = J(); r1 = a._apply_network(j1, want)
nd_file = os.path.join(nd, '00-builderbot-eth0.network')
nd_text = open(nd_file).read()
a.hello = lambda: (503, {})
j2 = J(); r2 = a._apply_network(j2, {'network': {'mode': 'dhcp', 'interface': 'eth0'}})
nd_after = open(nd_file).read()
# ifupdown: networkd out of the way, an interfaces file with a neighbour to keep
m.NETWORKCTL_BIN = '/nonexistent/networkctl'
orig = 'auto lo\\niface lo inet loopback\\n\\nauto eth0\\niface eth0 inet dhcp\\n\\nauto eth1\\niface eth1 inet static\\n    address 192.168.9.9/24\\n'
open(ifs, 'w').write(orig)
if_backend = m.net_backend().name
a.hello = lambda: (200, {})
j3 = J(); r3 = a._apply_network(j3, want)
if_text = open(ifs).read()
a.hello = lambda: (503, {})
j4 = J(); r4 = a._apply_network(j4, {'network': {'mode': 'dhcp', 'interface': 'eth0'}})
if_after = open(ifs).read()
print(json.dumps({'fam': fam, 'nd_backend': nd_backend, 'r1': r1, 'nd_text': nd_text, 'r2': r2,
                  'nd_after': nd_after, 'log2': ''.join(j2.lines), 'if_backend': if_backend, 'r3': r3,
                  'if_text': if_text, 'r4': r4, 'if_after': if_after, 'orig': orig,
                  'calls': open(${JSON.stringify(`${DIR}/netfiles.log`)}).read()}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  const wrong = Object.entries(WANT).filter(([k, v]) => R.fam[k] !== v).map(([k, v]) => `${k}: ${R.fam[k]} not ${v}`);
  ok(wrong.length === 0,
     `every distribution lands in its family through ID and ID_LIKE — ${Object.keys(WANT).length} samples${wrong.length ? ': ' + wrong.join(', ') : ''}`);
  ok(R.nd_backend === 'systemd-networkd' && R.r1[0] === 'succeeded'
     && /\[Match\]\nName=eth0\n\n\[Network\]\nAddress=10\.2\.2\.5\/24\nGateway=10\.2\.2\.1\nDNS=10\.2\.2\.1\n/.test(R.nd_text)
     && /networkctl reload/.test(R.calls),
     `with networkd active the same spec is a .network file and a reload (${R.nd_backend}, ${R.r1[0]})`);
  ok(R.r2[0] === 'failed' && /reverting/.test(R.log2) && R.nd_after === R.nd_text,
     '...and a change the controller cannot confirm puts the previous file back');
  ok(R.if_backend === 'ifupdown' && R.r3[0] === 'succeeded'
     && /iface eth0 inet static\n    address 10\.2\.2\.5\/24\n    gateway 10\.2\.2\.1\n    dns-nameservers 10\.2\.2\.1\n/.test(R.if_text)
     && /auto lo\niface lo inet loopback/.test(R.if_text) && /iface eth1 inet static\n    address 192\.168\.9\.9\/24/.test(R.if_text)
     && !/iface eth0 inet dhcp/.test(R.if_text) && /ifdown eth0\nifup eth0/.test(R.calls),
     `with ifupdown the interface's own stanza is replaced and the neighbours kept (${R.if_backend}, ${R.r3[0]})`);
  ok(R.r4[0] === 'failed' && R.if_after === R.if_text,
     '...and its revert is the whole file as it was before the change');
}

// ---- the packages store, scoped by platform; and a Mac ----------------------------
// The layout's standing rule: a scope's Android system images live once
// under <store>/shared with the scope's own directory a link to them, and
// a second run changes nothing. Then the Mac: with platform.system()
// answering Darwin, the agent's family is macos, its packages Homebrew, its
// init launchd, its scope darwin-<arch>.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
os.environ['BUILDERBOT_BREW_BIN'] = '/nonexistent/brew'
spec = importlib.util.spec_from_file_location('agent', ${JSON.stringify(AGENT)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
store = tempfile.mkdtemp()
scope = m.pkg_scope()
for d in ('jdk/bin', 'android/system-images/android-30/google_apis/x86_64', 'android/platform-tools'):
    os.makedirs(os.path.join(store, scope, d))
said = []
m.share_images(store, said.append)
img = os.path.join(store, scope, 'android', 'system-images')
r1 = {'link': os.path.islink(img), 'target': os.path.realpath(img),
      'shared': os.path.isdir(os.path.join(store, 'shared/android/system-images/android-30')), 'said': said}
said2 = []
m.share_images(store, said2.append)
r2 = {'said': said2, 'link': os.path.islink(img)}
m.platform.system = lambda: 'Darwin'
m.platform.machine = lambda: 'arm64'
m._run = lambda argv, timeout=5: '15.1' if argv[:1] == ['sw_vers'] else ''
mac = m.distro_now()
print(json.dumps({'r1': r1, 'r2': r2, 'mac': mac, 'scope': m.pkg_scope(), 'root': m.pkg_root({'stores': {'packages': '/Volumes/SDK'}})}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(R.r1.link && R.r1.shared && /shared\/android\/system-images$/.test(R.r1.target),
     'a scope\'s android system images are moved once under shared/, with the scope\'s directory a link to them');
  ok(R.r1.said.some(t => /shared across platforms/.test(t)) && R.r2.said.length === 0 && R.r2.link,
     `...it says so once, and a second run says and moves nothing (${R.r1.said[0] || ''})`);
  ok(R.mac.family === 'macos' && R.mac.init === 'launchd' && /macOS 15\.1/.test(R.mac.pretty) && R.mac.network === '' && R.mac.pkg === '',
     `a Mac is its own family: macos, launchd, no network backend, and no package manager until Homebrew is there (${JSON.stringify(R.mac)})`);
  ok(R.scope === 'darwin-arm64' && R.root === '/Volumes/SDK/darwin-arm64',
     `...with its packages under the store's darwin-arm64 scope (${R.root})`);
}

// ---- addresses that move ---------------------------------------------------
// The node dials out, so a node whose own address moves keeps working and
// the controller follows its hellos. Two things name an address anyway and
// are healed here: the ttyds bound to the node's old address are restarted
// onto the new one, and the session-ports rule that names the controller's
// address is rewritten when that name resolves elsewhere.
{
  const NB = `${DIR}/nbin`; mkdirSync(NB, { recursive: true });
  writeFileSync(`${NB}/nft`, `#!/bin/sh\necho "nft $*" >> "${DIR}/nft.log"\n`, { mode: 0o755 });
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
d = tempfile.mkdtemp()
nftf = os.path.join(d, 'session-ports.nft')
open(nftf, 'w').write('table inet builderbot_session {\\n    chain input {\\n        tcp dport { 7681, 7682 } iifname "lo" accept\\n        tcp dport { 7681, 7682 } ip saddr 10.0.0.9 accept\\n        tcp dport { 7681, 7682 } drop\\n    }\\n}\\n')
os.environ['BUILDERBOT_SESSION_NFT'] = nftf
os.environ['BUILDERBOT_NFT_BIN'] = ${JSON.stringify(`${NB}/nft`)}
os.environ['BUILDERBOT_SESSION_BIND'] = ''
spec = importlib.util.spec_from_file_location('agent', ${JSON.stringify(AGENT)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.os.geteuid = lambda: 0
a = m.Agent.__new__(m.Agent)
a.state = {'controller': 'http://127.0.0.1:1', 'stores': {'packages': d}}
a.fw_checked = 0.0
a.session_firewall_check()
first = open(nftf).read()
a.fw_checked = 0.0
a.session_firewall_check()
calls = open(${JSON.stringify(`${DIR}/nft.log`)}).read() if os.path.exists(${JSON.stringify(`${DIR}/nft.log`)}) else ''
# the node's own address moving: ttyds bound to the old one are marked for a restart
os.makedirs(os.path.join(d, m.pkg_scope(), '.bb', 'current'))
class P:
    def poll(self): return None
a.ttyd = [P()]; a.session_bound = '10.0.0.5'; a.session_stale = ''
m.network_now = lambda: {'addresses': ['10.0.0.77/24'], 'interface': 'eth0', 'gateway': '', 'dns': []}
a.session_start = lambda into, retry=False: setattr(a, 'restarted', into)
a.session_bundle = ''; a.session_digest = ''; a.session_tried = 0
a.session_check()
print(json.dumps({'first': first, 'calls': calls, 'restarted': getattr(a, 'restarted', ''), 'bind': a.session_bind()}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(/ip saddr 127\.0\.0\.1 accept/.test(R.first) && !/10\.0\.0\.9/.test(R.first),
     'when the controller\'s name resolves elsewhere, the session-ports rule is rewritten to the new address');
  ok((R.calls.match(/nft -f/g) || []).length === 1,
     '...applied once, and a second check with nothing changed applies nothing');
  ok(R.bind === '10.0.0.77' && /\.bb\/current$/.test(R.restarted),
     `when the node's own address moves, the ttyds are restarted onto the new one (${R.bind})`);
}

// ---- the agent's version is WINDOW.BUILD ----------------------------------
// The window is the project's compatibility promise — while BuilderBot is
// 0.4.x, any 0.4 agent works with any 0.4 controller — and it is a constant
// in a file, which means it drifts the moment somebody bumps the minor and
// does not think about the agent. That is the bump this is about, so the
// check is here rather than in anybody's memory.
{
  const src = readFileSync(AGENT, 'utf8');
  const av = /^AGENT_VERSION\s*=\s*"([^"]+)"/m.exec(src)?.[1] || '';
  const win = /^(\d+\.\d+)\./.exec(av)?.[1] || '';
  const proj = readFileSync(`${REPO}/VERSION`, 'utf8').trim();
  const minor = proj.split('.').slice(0, 2).join('.');
  ok(/^\d+\.\d+\.\d+$/.test(av),
     `the agent's version is WINDOW.BUILD (${av || 'unset'})`);
  ok(win === minor,
     `...and its window is the project's minor — bump one and you bump both (${
       win} against ${minor} from VERSION ${proj})`);
  // The CLAUDE.md template is in the same window, for the same reason: the
  // block a session is briefed with is a compatibility promise too, and a
  // bump that moves the minor without restamping it would leave every
  // project's copy claiming the window that just ended — or, worse, the
  // template claiming the old one, so nothing is ever held.
  const tmpl = readFileSync(`${REPO}/config/templates/project-CLAUDE.md`, 'utf8');
  const mdWin = /<!-- BUILDERBOT:ENV:WINDOW (\d+\.\d+) -->/.exec(tmpl)?.[1] || '';
  ok(mdWin === minor,
     `...and the CLAUDE.md template's BUILDERBOT:ENV:WINDOW line is the same minor (${
       mdWin || 'unset'} against ${minor})`);
}

await done(browser);
