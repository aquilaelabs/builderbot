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
import { readFileSync, existsSync, statSync, lstatSync, readlinkSync, writeFileSync, mkdirSync, readdirSync, openSync, rmSync } from 'node:fs';

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
  DOCKER_STUB_STATE: `${DIR}/dockerstate`, PATH: `${DIR}/bin:${process.env.PATH}`,
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
    try {
      // It ends in `exec ... run`, which never returns — the timeout is how
      // the enrollment half is exercised without the loop being left behind.
      nout = execFileSync('bash', [`${REPO}/scripts/node-agent.sh`],
        { env: nenv, encoding: 'utf8', timeout: 25000, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (e) { nout = String(e.stdout || '') + String(e.stderr || ''); }
    const rec = `${NROOT}/node.json`;
    ok(existsSync(rec), `the node role enrolls from CONTROLLER_URL and NODE_TOKEN (${
      nout.split('\n').filter(Boolean).slice(-2).join(' | ').slice(0, 120)})`);
    const nst = existsSync(rec) ? JSON.parse(readFileSync(rec, 'utf8')) : {};
    ok(nst.node_id === two.id && nst.stores?.data === `${NROOT}/data`
       && nst.stores?.packages === `${DIR}/nodepackages`,
       `...keeping its identity and stores under NODE_STORE_ROOT, and its packages store
        where NODE_PACKAGES_STORE says — the SDK share, in the template (${
         JSON.stringify(nst.stores || {})})`);
    ok((await nodeById(two.id))?.state === 'online',
       '...and the row comes online without systemd, ssh or a provisioner');
    // Second start: the token is spent and the record is what matters. An
    // image update restarts this container, and re-enrolling every time
    // would burn a token it does not have and lose the node's identity.
    let again2 = '';
    try {
      again2 = execFileSync('bash', [`${REPO}/scripts/node-agent.sh`],
        { env: nenv, encoding: 'utf8', timeout: 8000, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (e) { again2 = String(e.stdout || '') + String(e.stderr || ''); }
    ok(/already enrolled/.test(again2) && JSON.parse(readFileSync(rec, 'utf8')).node_id === two.id,
       '...and starting again re-uses the record rather than spending another token');
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
    ok((e.PATH || '').split(':')[0] === bbtty.replace(/\/dashboard\/bb-tty$/, ''),
       '...and bb from that bundle first on PATH');
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
    const answer = await fetch(`http://127.0.0.1:${SESSION_PORT}/ws?arg=x`).then(r => r.text()).catch(e => String(e));
    ok(/^ttyd-stub GET/.test(answer), `...and the port answers as the agent's own again (${answer.slice(0, 30)})`);
    const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
    const store = st.stores.packages;
    ok(existsSync(`${store}/.bb/current/scripts/bb`)
       && lstatSync(`${store}/.bb/current`).isSymbolicLink(),
       'the packages store carries a .bb/current link at the newest bundle, for a shell at the console');
    ok(existsSync(`${store}/.bb/current/scripts/dashboard/bb-work-note`)
       && existsSync(`${store}/.bb/current/scripts/lib/bbapi.py`),
       '...and the bundle carries the hooks bb-tty writes into a session and bb\'s API client');
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
    ok(added.status === 200 && added.code === 0 && /added \d+/.test(added.out),
       `a session's bb roadmap runs on the controller and answers (${(added.out || added.error || '').trim().slice(0, 60)})`);
    const listed = await relay({ argv: ['roadmap'] });
    ok(listed.code === 0 && /relayed from a node/.test(listed.out),
       '...against the project the token was minted for, with no cwd sent at all');
    const settings = await relay({ argv: ['settings', '--json'] });
    ok(settings.code === 0 && JSON.parse(settings.out).project === 'alpha'
       && typeof JSON.parse(settings.out).locked === 'boolean',
       'bb settings --json relays the project\'s settings, lock included — what bb-tty and bb build read on a node');
    const other = await relay({ argv: ['roadmap'], project: 'ep.silon' });
    ok(other.status === 403 && /another project/.test(other.error),
       'a token for alpha cannot ask about another project');
    const sdk = await relay({ argv: ['sdk'] });
    ok(sdk.status === 400 && /not relayed/.test(sdk.error),
       'bb sdk is refused — it answers for the machine the session is on');
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
      writeFileSync(creds, '{"claudeAiOauth": {"accessToken": "fake-for-the-suite"}}\n', { mode: 0o600 });
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
      if (had === null) rmSync(creds); else writeFileSync(creds, had);
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
      const num = (once.match(/added (\d+)/) || [])[1];
      bbOnNode(['roadmap', 'rm', String(num), 'test']);
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
    await relay({ argv: ['roadmap', 'rm', String(((added.out || '').match(/added (\d+)/) || [])[1]), 'test'] });
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
      mkdirSync(`${DIR}/agentpackages/android`, { recursive: true });
      writeFileSync(`${DIR}/agentpackages/android/marker`, 'a toolchain lives here');
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
         && readFileSync(`${DIR}/agentpackages2/android/marker`, 'utf8') === 'a toolchain lives here',
         `moving a store copies what was in it to the new place (${r?.state})`);
      ok(existsSync(`${DIR}/agentpackages/android/marker`) && /left in place/.test(r.log),
         '...and never deletes the source, so a half-finished move still serves');
      ok(/agentpackages stays \(Directory not empty\)/.test(r.log) && /remove it yourself/.test(r.log),
         '...so the old directory is not tidied away either, and the log says which one holds it');
      ok(!existsSync(`${DIR}/agentcache2/gradle-blob`) && /a cache is rebuildable/.test(r.log),
         '...while the cache is left behind rather than copied, and the log says why');
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
      await api('/api/v1/nodes', { action: 'config', id: minted.id,
        config: { mounts: [], stores: { artifacts: `${DIR}/agentartifacts` }, network: { mode: 'dhcp' } } });
      const un = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      const unr = await until(async () => {
        const x = await api(`/api/v1/jobs?id=${un.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 60000);
      ok(unr && unr.state === 'succeeded' && !existsSync(`${DIR}/pre/a1`) && /removed .*\/pre\/a1\/a2\/art/.test(unr.log),
         `moving off an empty store takes back the directories it made for it (${unr?.state})`);
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
      mkdirSync(`${DIR}/agentpackages/jdk/bin`, { recursive: true });
      mkdirSync(`${DIR}/agentpackages/go/bin`, { recursive: true });
      // An android system image in the node's own store, and an AVD in the
      // data store built on it (roadmap #20). The agent walks for these
      // rather than running `bb sdk images`, which is the same listing plus
      // a du over tens of gigabytes of NFS every ten minutes.
      const IMG = `${DIR}/agentpackages/android/system-images`;
      mkdirSync(`${IMG}/android-34/google_apis/x86_64`, { recursive: true });
      writeFileSync(`${IMG}/android-34/google_apis/x86_64/system.img`, 'x');
      mkdirSync(`${IMG}/android-33/google_apis/x86_64`, { recursive: true });
      mkdirSync(`${DIR}/agentdata/avd/fbnode.avd`, { recursive: true });
      writeFileSync(`${DIR}/agentdata/avd/fbnode.avd/config.ini`,
        'abi.type=x86_64\nimage.sysdir.1 = system-images/android-34/google_apis/x86_64/\n');
      const envrun = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', 'echo "root=$SDK_ROOT"; echo "java=$JAVA_HOME"; '
                         + 'echo "android=$ANDROID_HOME"; echo "path=$PATH"'] });
      const ef = await until(async () => {
        const r = await api(`/api/v1/jobs?id=${envrun.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 30000);
      const log = ef?.log || '';
      ok(/root=.*agentpackages/.test(log) && /java=.*agentpackages\/jdk/.test(log)
         && /android=.*agentpackages\/android/.test(log),
         `a build job gets the node's SDK root, JAVA_HOME and ANDROID_HOME (${
           (log.match(/root=.*/) || [''])[0].slice(0, 60)})`);
      // An empty directory is not a toolchain. cmdline-tools existed on the
      // operator's node as an empty folder with no sdkmanager, and
      // platform-tools not at all, and the census called android-sdk present
      // — so a job needing adb was admitted and failed there rather than
      // being refused here.
      mkdirSync(`${DIR}/agentpackages/android/cmdline-tools`, { recursive: true });
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
      ok(/path=[^\n]*agentpackages\/jdk\/bin/.test(log)
         && /path=[^\n]*agentpackages\/go\/bin/.test(log),
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
    // Unpacked by this job, or already there: the session half fetched the
    // same bundle at start (roadmap #24), and a second unpack of the same
    // digest is exactly what the digest is for.
    ok(pfin && pfin.type === 'package'
       && (/bb .* unpacked into .*agentpackages\/\.bb/.test(pfin.log)
           || existsSync(`${DIR}/agentpackages/.bb/current/scripts/bb`))
       && /== bb sdk remove flutter/.test(pfin.log) && /not installed|unknown package/.test(pfin.log),
       `the bundle lands in the packages store and bb runs from it there (${pfin?.state}: ${(pfin?.log || '').slice(-500).replace(/\n/g, ' / ')})`);
    ok(existsSync(`${DIR}/agentpackages/.bb/bundle.tar`), '...and stays for the next one');
    // The store's own directories decide what is installed there — not the
    // census's placement summary, which named six toolchains and called four
    // installed packages missing on the operator's shared SDK store.
    mkdirSync(`${DIR}/agentpackages/zig`, { recursive: true });
    mkdirSync(`${DIR}/agentpackages/android/ndk`, { recursive: true });
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
    ok(view && view.node === minted.id && view.root === `${DIR}/agentpackages`,
       'the Tools tab reads that node\'s own packages store');
    ok(view && view.items.find(i => i.name === 'zig')?.installed === true
       && view.items.find(i => i.name === 'android:ndk')?.installed === true,
       'a package present in the store reads as installed, whatever the census summarises');
    ok(view && view.items.find(i => i.name === 'swift')?.installed === false
       && view.items.every(i => i.unknown === false),
       '...and one that is not there reads as absent, not as unknown');
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
                             `${REPO}/vm/provision.sh`], { stdio: 'pipe' });
    const SB = `${SBDIR}/provision.sh-BBSANDBOX`;
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
    ok(/^sha256:[0-9a-f]{64}$/.test(all.agent?.digest || '') && /^\d+$/.test(all.agent.version || ''),
       'the node list carries the agent this controller ships, digest and version');
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

await done(browser);
