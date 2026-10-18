// Phase 3 of the controller design (docs/nodes.md): the agent, enrollment,
// and the numbers. The REAL agent (scripts/agent: the entry and its package) is run
// here as a child process against the harness server, with its node.json
// pointed into the scratch dir: enroll with a token the tab minted, dial in,
// take an exec job, stream its log, report the result, and be cut off. Every
// assertion is a round trip through the channel, which is the thing phase 3
// exists to prove.
import { URL, launch, newPage, ok, done, ready, sleep, refreshUntil, DIR,
         tmuxNew, tmuxKill, tmuxFmt, tmuxCapture, openSection } from './lib.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, existsSync, statSync, lstatSync, readlinkSync, writeFileSync, mkdirSync, readdirSync, openSync, rmSync, appendFileSync, realpathSync, copyFileSync, cpSync, chmodSync, symlinkSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const AGENT = `${REPO}/scripts/agent/builderbot-agent.py`;
// The agent's own modules, in-process: a fresh copy of the package as one
// object (unit/agentpkg.py), the way the single file was loaded by path.
const LOAD_AGENT = `import sys; sys.path.insert(0, ${JSON.stringify(`${REPO}/scripts/dashboard/unit`)}); import agentpkg`;
// What a node runs: the zip the controller ships (builderbot_agent/bundle.py).
const agentZip = () => execFileSync('python3', ['-c', 'import sys; sys.path.insert(0, sys.argv[1]); '
  + 'from builderbot_agent import bundle; sys.stdout.buffer.write(bundle.build(sys.argv[1]))', `${REPO}/scripts/agent`]);
// Under bb tests coverage (R76) every python this file starts, the agent it
// runs and the module it drives in-process alike, counts the agent's
// functions into its own file: PID is each process's own, so a self-update's
// successor and every snippet get a file apiece. Set once, inherited by all.
if (process.env.BB_COVERAGE_DIR){
  process.env.BB_COVERAGE_OUT = `${process.env.BB_COVERAGE_DIR}/agent-PID.json`;
  process.env.BB_COVERAGE_SUITE = 'agent';
  process.env.BB_COVERAGE_AS = 'scripts/agent/builderbot_agent';   // the copy's modules count as the tree's
}
// A node's toolchains live under <store>/<node id> (R196), so every fixture
// written INTO a store goes there, while the store's own path (the setting)
// stays the share. Set once the node's id is minted, below.
let SCOPE = '';
let PK = '';
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
SCOPE = minted.id;
PK = `${DIR}/agenttoolchains/${SCOPE}`;
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
     'the token itself is never on a row: only its hash is stored');
}
// ...and the download the provisioner does, with the enroll token
{
  const r = await fetch(URL.replace(/\/$/, '') + '/api/v1/agent/download',
    { headers: { Authorization: 'Bearer ' + minted.token } });
  const body = Buffer.from(await r.arrayBuffer());
  ok(r.status === 200 && body.equals(agentZip())
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
// A card of its own for the agent to find (R102): a sysfs tree with an
// NVIDIA display device bound to nouveau, and a modinfo that finds a
// module only once the stand-in bb-sandbox has "installed" one, so the
// census reads the same on any box the suite runs on.
{
  const dev = `${DIR}/sys/bus/pci/devices/0000:04:00.0`;
  mkdirSync(dev, { recursive: true });
  mkdirSync(`${DIR}/sys/bus/pci/drivers/nouveau`, { recursive: true });
  writeFileSync(`${dev}/vendor`, '0x10de\n'); writeFileSync(`${dev}/class`, '0x030000\n'); writeFileSync(`${dev}/device`, '0x2482\n');
  try { symlinkSync(`${DIR}/sys/bus/pci/drivers/nouveau`, `${dev}/driver`); } catch {}
  // What apt says about the driver, the same on any box the suite runs on:
  // two branches on offer, 595 recommended, and installed once the stand-in
  // bb-sandbox has "installed" one. Anything else goes to the real tool.
  const real = t => `for d in /usr/bin /bin /usr/sbin /sbin; do [ -x "$d/${t}" ] && exec "$d/${t}" "$@"; done; exit 1`;
  writeFileSync(`${DIR}/bin/apt-cache`, `#!/bin/sh
case "$1 $3" in
  "search ^nvidia-driver"*) printf 'nvidia-driver-590 - NVIDIA driver metapackage (transitional package)\\nnvidia-driver-595 - NVIDIA driver metapackage\\nnvidia-driver-610 - NVIDIA driver metapackage\\n'; exit 0 ;;
esac
case "$1 $2" in
  "policy nvidia-container-toolkit") f="\${BB_CTK_STATE:-/nonexistent}"
    if [ -s "$f" ]; then printf 'nvidia-container-toolkit:\\n  Installed: %s\\n  Candidate: %s\\n' "$(cat "$f")" "$(cat "$f")"
    else printf 'nvidia-container-toolkit:\\n  Installed: (none)\\n  Candidate: (none)\\n'; fi; exit 0 ;;
  "policy nvidia-driver"*) printf 'nvidia-driver-595:\\n  Installed: (none)\\n  Candidate: 595.91.07-0ubuntu1\\nnvidia-driver-610:\\n  Installed: (none)\\n  Candidate: 610.57.04-0ubuntu1\\n'; exit 0 ;;
esac
${real('apt-cache')}
`, { mode: 0o755 });
  writeFileSync(`${DIR}/bin/dpkg-query`, `#!/bin/sh
for a in "$@"; do case "$a" in "nvidia-driver*")
  f="\${BB_NV_STATE:-/nonexistent}"
  [ -s "$f" ] && printf '%s %s-0ubuntu1 ii \\n' "$(sed -n 2p "$f")" "$(sed -n 1p "$f")"
  exit 0 ;;
  nvidia-container-toolkit)
  f="\${BB_CTK_STATE:-/nonexistent}"
  [ -s "$f" ] && printf '%s ii \\n' "$(cat "$f")"
  exit 0 ;; esac; done
${real('dpkg-query')}
`, { mode: 0o755 });
  // ...and the toolkit's own tool, which a node with the real one (bb-sandbox
  // since 30 Sep) would otherwise answer for: installed once the stand-in
  // bb-sandbox has "installed" the toolkit, and not there before.
  writeFileSync(`${DIR}/bin/nvidia-ctk`, `#!/bin/sh
f="\${BB_CTK_STATE:-/nonexistent}"
[ -s "$f" ] || exit 127
echo "NVIDIA Container Toolkit CLI version $(cat "$f")"
`, { mode: 0o755 });
  writeFileSync(`${DIR}/bin/ubuntu-drivers`, `#!/bin/sh
printf 'vendor   : NVIDIA Corporation\\ndriver   : nvidia-driver-595 - distro non-free recommended\\ndriver   : nvidia-driver-610 - distro non-free\\n'
`, { mode: 0o755 });
  writeFileSync(`${DIR}/bin/modinfo`, `#!/bin/sh
f="\${BB_NV_STATE:-/nonexistent}"
if [ -s "$f" ]; then sed -n 1p "$f"; exit 0; fi
echo "modinfo: ERROR: Module nvidia not found." >&2; exit 1
`, { mode: 0o755 });
}
writeFileSync(`${DIR}/bin/bb-sandbox`, `#!/usr/bin/env python3
import json, os, sys
f = os.environ["BB_SANDBOX_STATE"]
try: ms = json.load(open(f))
except Exception: ms = []
a = sys.argv[1:]
def save(): json.dump(ms, open(f, "w"))
if a[:2] == ["list", "--json"]: print(json.dumps(ms)); sys.exit(0)
if a[0] == "gpu-driver":
    # The driver row's verb (R102): "installed" is the version the stand-in
    # modinfo answers with, as a real install puts a module there.
    if a[1] == "refresh": print("reading the package lists again"); sys.exit(0)
    if a[1] == "install":
        pkg = a[2] if len(a) > 2 else "nvidia-driver-595"
        open(os.environ["BB_NV_STATE"], "w").write({"nvidia-driver-610": "610.57.04"}.get(pkg, "595.91.07") + "\\n" + pkg + "\\n")
    elif os.path.exists(os.environ["BB_NV_STATE"]): os.remove(os.environ["BB_NV_STATE"])
    print(f"gpu-driver {' '.join(a[1:])}: done; it takes effect at the next boot"); sys.exit(0)
if a[0] == "gpu-container":
    # The container toolkit's verb (R102): "installed" is what the stand-in
    # dpkg-query answers with, and the docker stub lists the runtime.
    kit, rt = os.environ["BB_CTK_STATE"], os.path.join(os.environ["DOCKER_STUB_STATE"], "nvidia-runtime")
    if a[1] == "install":
        open(kit, "w").write("1.17.8-1"); open(rt, "w").write("1")
    else:
        for x in (kit, rt):
            if os.path.exists(x): os.remove(x)
    print(f"gpu-container {a[1]}: done"); sys.exit(0)
if a[0] == "gpu-off":
    open(os.environ["BB_GPU_STATE"], "w").write("off: switched off on the Nodes tab; an emulator here renders in software\\n")
    print("the GPU display is off"); sys.exit(0)
if a[0] == "gpu":
    open(os.environ["BB_GPU_STATE"], "w").write("reboot: the NVIDIA driver is installed and takes the card at the next boot\\n")
    print("card: NVIDIA Test Card [10de:0000]"); print("the driver is installed and takes the card at the next boot: Reboot on this node's row"); sys.exit(0)
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
if a[0] == "uninstall":
    open(f + ".uninstall", "w").write(" ".join(a)); sys.exit(0)
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
echo "npm: stub; nothing is downloaded in the suite" >&2
exit 1
`, { mode: 0o755 });
// The runner, stood in for: a tarball whose config.sh and svc.sh record
// what they were asked, and a `sudo` on the server's PATH that answers the
// token minter with a fake token, since the real one needs the root-only stash.
mkdirSync(`${DIR}/runner-src/bin`, { recursive: true });
writeFileSync(`${DIR}/runner-src/config.sh`, `#!/bin/sh
echo "config $*" >> "$(dirname "$0")/calls.log"
if [ "$1" = remove ]; then rm -f "$(dirname "$0")/.runner"; exit 0; fi
# What the real one says on a RHEL node with no libicu, and then exits: the
# reason first and GitHub's advice under it.
if [ -f "$(dirname "$0")/../runner-fail" ] || [ -f "$(dirname "$0")/../../runner-fail" ]; then
  echo "Libicu's dependencies is missing for Dotnet Core 6.0"
  echo "Execute sudo ./bin/installdependencies.sh to install any missing Dotnet Core 6.0 dependencies."
  exit 1
fi
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
// act_runner, stood in for: register writes the .runner act_runner writes
// (name, address, labels, id) and records its arguments; daemon stays up as
// a child so the census's pgrep sees `<dir>/act_runner daemon`.
writeFileSync(`${DIR}/bin/act_runner`, `#!/bin/sh
echo "act $*" >> "$(pwd)/act-calls.log"
case "$1" in
  register) name=; inst=; labels=
    while [ $# -gt 0 ]; do case "$1" in --name) name="$2"; shift;; --instance) inst="$2"; shift;; --labels) labels="$2"; shift;; esac; shift; done
    printf '{"id":7,"name":"%s","address":"%s","labels":["%s"]}' "$name" "$inst" "$labels" > "$(pwd)/.runner" ;;
  daemon) sleep 300 ;;
esac
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
// sessions this node runs, and what is under test is that it does: as
// which account, on which ports, running bb-tty from which bundle, not
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
# SIGTERM, and not a minute longer, so a killed agent leaves nothing behind.
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
// daemon the controller's runner does; a real node needs nothing here.
// The fixture node's /workspace: a directory of its own, where its agent
// makes the synced copy of each project bound to it (R163), from this
// harness's controller, as a real node does.
const SHARE = `${DIR}/agentworkspace`;
mkdirSync(SHARE, { recursive: true });
const agentEnv = { ...process.env, BUILDERBOT_NODE_JSON: NODE_JSON,
  BUILDERBOT_SHARE: SHARE,
  BUILDERBOT_TTYD_BIN: `${DIR}/bin/ttyd`, BUILDERBOT_SESSION_PORT: String(SESSION_PORT),
  BUILDERBOT_SESSION_BIND: '127.0.0.1',
  // A PATH of the harness's own. The agent reports what it finds on PATH as
  // the fixture node's toolchains, and run from a session on a node this
  // process inherits that node's PATH: the real store, flutter included,
  // which made the fixture node "have" everything this machine has.
  DOCKER_STUB_STATE: `${DIR}/dockerstate`,
  PATH: `${DIR}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin`,
  BUILDERBOT_DPKG_BIN: `${DIR}/bin/dpkg`, BUILDERBOT_APT_BIN: `${DIR}/bin/apt-get-never`,
  BUILDERBOT_IDLE_UNIT: '1',
  // The Claude Code installer, stood in for: the real one fetches a binary.
  BUILDERBOT_CLAUDE_INSTALLER: `${DIR}/bin/claude-installer`,
  BUILDERBOT_SESSION_RETRY_S: '2',   // the restart cooldown, which a test waits out
  BUILDERBOT_SYSTEMD: '1',      // this agent takes the service path whichever box runs the suite
  BUILDERBOT_TAILSCALE_BIN: `${DIR}/bin/tailscale`,
  BUILDERBOT_RUNNER_DIR: `${DIR}/runner`, BUILDERBOT_RUNNER_TARBALL: `${DIR}/runner.tar.gz`,
  BUILDERBOT_ACT_RUNNER_BIN: `${DIR}/bin/act_runner`,
  BUILDERBOT_SANDBOX_BIN: `${DIR}/bin/bb-sandbox`, BB_SANDBOX_STATE: SANDBOX_STATE,
  BB_GPU_STATE: `${DIR}/gpu-state`, BUILDERBOT_GPU_DISPLAY_STATE: `${DIR}/gpu-state`,
  BUILDERBOT_SYS_ROOT: `${DIR}/sys`, BB_NV_STATE: `${DIR}/nv-installed`, BB_CTK_STATE: `${DIR}/ctk-installed`,
  BUILDERBOT_NETPLAN_BIN: `${DIR}/bin/netplan`, BUILDERBOT_NETPLAN_DIR: `${DIR}/netplan` };
{
  let out = '';
  try {
    // A toolchain store of its own: the default is /var/lib/builderbot, which
    // this container cannot write, and the session half unpacks bb there.
    out = execFileSync('python3', [AGENT, 'enroll', '--controller', URL,
      '--token', minted.token, '--user', process.env.USER || 'builder',
      '--store', `data=${DIR}/agentdata`, '--store', `toolchains=${DIR}/agenttoolchains`,
      // Where a dev instance's data goes on this node (R17 step 2). The same
      // directory the suite blocks a bind in below, because it is now the
      // NODE that says where that is rather than the controller's
      // BB_DEV_DATA_DIR.
      '--store', `appdata=${DIR}/devdata`],
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
  // A store role added AFTER a node enrolled reaches it anyway. The list is
  // written at enrolment and never revisited, so `appdata` would have existed
  // only on the next machine somebody enrolled and every node already out
  // there would have used the controller's fallback forever. Placed beside
  // the data store rather than at the hard-coded default, because a guest
  // node keeps everything in one directory in its owner's home (R23) and has
  // no root to make /var/lib/builderbot.
  {
    const keep = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
    const without = { ...keep, stores: { ...keep.stores } };
    delete without.stores.appdata;
    writeFileSync(NODE_JSON, JSON.stringify(without));
    execFileSync('python3', ['-c',
      'import importlib.util,sys\n' +
      `${LOAD_AGENT}\n` +
      'm=agentpkg.load()\n' +
      'st=m.load_state()\n' +
      'm.fill_default_stores(st)\n' +
      'm.save_state(st)\n'],
      { env: { ...process.env, BUILDERBOT_NODE_JSON: NODE_JSON }, encoding: 'utf8' });
    const after = JSON.parse(readFileSync(NODE_JSON, 'utf8')).stores;
    ok(after.appdata === `${DIR}/appdata`,
       `a store role added since enrolment is adopted beside the data store (${after.appdata})`);
    ok(existsSync(`${DIR}/appdata`),
       '...and the directory is MADE, not just recorded, or the row calls it missing forever');
    writeFileSync(NODE_JSON, JSON.stringify(keep));
  }

  const n = await nodeById(minted.id);
  // The version is read from the controller, not written here: the agent
  // just downloaded from it, so the two must agree, and an assertion naming
  // a number has to be edited on every bump for nothing.
  const ships = (await api('/api/v1/nodes')).agent || {};
  ok(n.state === 'online' && n.reported.cpu > 0 && n.reported.hostname
     && n.agent.version === ships.version && n.agent.digest === ships.digest,
     `the row is online with the census, and runs the agent this controller ships (${n.agent.version})`);
  // Whether a session there sees only its own project (R35), in the
  // helper's own answer: an agent that is not root cannot build a view.
  ok(n.reported.isolation && n.reported.isolation.sessions === false && /root/.test(n.reported.isolation.why || ''),
     `...and says whether its sessions are kept to their own project, and why not (${JSON.stringify(n.reported.isolation)})`);
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

// The agent refuses a system path for a store whatever it is told, which is
// the same rule the controller applies, made at the resource.
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
// with execFileSync, which blocks that loop while it waits for a job that
// needs the agent to keep polling. Once the agent had logged 64KB it blocked
// on a write nobody would ever read, the job never started, and the suite
// sat for an hour at the same assertion. A file needs no reader.
const AGENT_LOG_FILE = `${DIR}/agent.log`;
const agentOut = openSync(AGENT_LOG_FILE, 'a');
// Run from a copy, not from the file the controller ships: the self-update
// below moves the shipped file and has to find the running one behind it,
// which is what every node sees on a controller update.
// The zip, as a node keeps it: one file, run with python3 like the script it was.
const AGENT_RUN = `${DIR}/agent-run/builderbot-agent`;
mkdirSync(`${DIR}/agent-run`, { recursive: true });
writeFileSync(AGENT_RUN, agentZip());
const agent = spawn('python3', [AGENT_RUN, 'run'], { env: agentEnv, stdio: ['ignore', agentOut, agentOut] });
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
  // unpacks it into the toolchain store, and starts two ttyds running bb-tty
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
       '...saying whether /workspace is there and which bb bundle bb-tty runs from');
    // This node's two; the container node enrolled above started its own.
    // Waited for: the census says up once the first is, and the twin's
    // record can land a moment later on a loaded box (two whole gates of
    // 13 Oct read one and passed alone).
    // ...and only the live ones: the agent starts the pair again when its
    // first start is judged down (a loaded box, 13 Oct: four records, the
    // first pair ended), and a record outlives its ttyd.
    const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
    // The session pair, and beside it the container terminal (R218 step 4):
    // a third, writable, under BB_TTY_CTR, as the docker account.
    const all = () => ttydRuns().filter(r => r.env.BUILDERBOT_NODE === minted.id && alive(r.pid));
    const mine = () => all().filter(r => r.env.BB_TTY_CTR !== '1');
    const runs = (await until(async () => { const r = mine(); return r.length >= 2 ? r : null; })) || mine();
    ok(runs.length === 2 && runs.some(r => r.argv.includes('--writable'))
       && runs.some(r => !r.argv.includes('--writable')),
       `two ttyds: the writable one and the read-only twin an account without a shell is shown (${
         runs.length} records: ${runs.map(r => `${r.argv.includes('--writable') ? 'rw' : 'ro'}:${r.pid}`).join(' ')})`);
    {
      const ctr = (await until(async () => { const r = all().filter(x => x.env.BB_TTY_CTR === '1'); return r.length ? r : null; })) || [];
      const at = ctr[0]?.argv || [];
      const back = await until(async () => { const n = await nodeById(minted.id); return n?.reported?.session?.ctr_port ? n.reported.session : null; });
      ok(ctr.length === 1 && at.includes('--writable') && at[at.indexOf('--port') + 1] === String(SESSION_PORT + 2)
         && /\/scripts\/dashboard\/bb-tty$/.test(at.at(-1) || '') && back?.ctr_port === SESSION_PORT + 2,
         `...and a third, the container terminal, writable on ${SESSION_PORT + 2} and named in the census (${
           ctr.length} record(s), census ctr_port ${back?.ctr_port})`);
    }
    const bbtty = runs[0]?.argv.at(-1) || '';
    ok(/\/\.bb\/[0-9a-f]{16}\/scripts\/dashboard\/bb-tty$/.test(bbtty) && existsSync(bbtty),
       `...both running bb-tty out of the bundle unpacked in the toolchain store (${bbtty.replace(DIR, '…')})`);
    ok(runs.every(r => r.argv.includes('--url-arg') && r.argv.includes('--interface')
                       && r.argv[r.argv.indexOf('--interface') + 1] === '127.0.0.1'),
       '...with --url-arg for the target, bound where the agent was told');
    const e = runs[0]?.env || {};
    ok(e.BUILDERBOT_ROLE === 'node' && e.BB_CONTROLLER === URL.replace(/\/$/, '')
       && e.WORKSPACE === '/workspace' && !('BB_TOKEN' in e) && !e.BUILDERBOT_NODE_JSON,
       'the sessions inherit the role and the controller\'s address, never the node\'s token');
    // Through the SYMLINK, not the digest it points at (bug #66). A ttyd
    // restart onto a new bundle only reaches new connections (a tmux
    // session's shell keeps the PATH it was started with), so a session open
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
       `a ttyd that died is started again, and a stray bb-tty ttyd holding its port, an earlier agent's, is ended first (${
         again ? 'up on ' + again.sess.port : 'not up: ' + JSON.stringify((await nodeById(minted.id))?.reported?.session)})`);
    if (!strayGone) stray.kill('SIGKILL');
    // Retried rather than asked once: the census says up when the process
    // is alive and still there a moment later, which is what the agent can
    // know; the stub's own listener binds just after that, so a single
    // fetch races it and fails on a loaded box.
    const answer = await until(async () =>
      fetch(`http://127.0.0.1:${SESSION_PORT}/ws?arg=x`).then(r => r.text()).catch(() => null),
      15000, 300) || 'never answered';
    ok(/^ttyd-stub GET/.test(answer), `...and the port answers as the agent's own again (${answer.slice(0, 30)})`);
    const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
    const store = `${st.stores.toolchains}/${SCOPE}`;   // the node's scope in it (roadmap R19)
    ok(existsSync(`${store}/.bb/current/scripts/bb`)
       && lstatSync(`${store}/.bb/current`).isSymbolicLink(),
       'the toolchain store carries a .bb/current link at the newest bundle, for a shell at the console');
    ok(existsSync(`${store}/.bb/current/scripts/dashboard/bb-work-note`)
       && existsSync(`${store}/.bb/current/scripts/lib/bbapi.py`),
       '...and the bundle carries the hooks bb-tty writes into a session and bb\'s API client');
    // ...and the provisioner, which embeds bb-sandbox: the agent refreshes the
    // machine's copy from it before a system job, so a verb the controller
    // asks for (uninstall) is there on a node provisioned before the verb was.
    ok(existsSync(`${store}/.bb/current/nodes/provision-linux.sh`),
       '...and the provisioner, so the machine\'s bb-sandbox can be refreshed from the bundle');
    {
      const tool = execFileSync('python3', ['-c', `
import importlib.util, sys
${LOAD_AGENT}
m = agentpkg.load()
t = m.extract_sandbox_tool(open(${JSON.stringify(`${REPO}/nodes/provision-linux.sh`)}).read())
print(len(t)); print(t.splitlines()[0]); print('uninstall)' in t)
`], { encoding: 'utf8' }).trim().split('\n');
      ok(Number(tool[0]) > 5000 && /^#!/.test(tool[1]) && tool[2] === 'True',
         `the agent lifts bb-sandbox out of the provisioner's heredoc whole, uninstall verb included (${tool.join(' | ').slice(0, 80)})`);
    }
    // B377: the helper a new bundle carries goes in with the bundle. The
    // loop refreshes it before its hello and the bundle arrives after, so
    // it waited ten minutes for the next hello, and a session restarted in
    // between lost what the new helper keeps. Driven in process: a hello
    // whose answer names a bundle the node does not have, then one that
    // names the one it has.
    {
      const said = execFileSync('python3', ['-c', `
import importlib.util, json
${LOAD_AGENT}
m = agentpkg.load()
m.log = lambda *a, **k: None
m.share_images = lambda *a, **k: None
m.census = lambda state: {}
m.own_digest = lambda: 'sha256:agent'
m.save_state = lambda s: None
def case(have, shipped):
    a = object.__new__(m.Agent)
    a.state, a.warned_caps, a.session_bundle, did = {}, True, have, []
    class Ctl:
        def call(self, verb, body, timeout=30):
            return 200, {'bundle': shipped, 'node': {'id': 'n1', 'name': 'n', 'state': 'online'}}
    a.ctl = Ctl()
    a.running_ids = lambda: []
    a.keep_session_tokens = lambda rows: None
    a.runner_env_sync = lambda: did.append('runners')
    a.refresh_session_tool = lambda: did.append('helper')
    def take(digest):
        did.append('bundle ' + digest)
        a.session_bundle = digest
    a.session_try = take
    a.hello()
    return did
print(json.dumps({'moved': case('sha256:old', 'sha256:new'), 'same': case('sha256:new', 'sha256:new')}))
`], { encoding: 'utf8' }).trim();
      const r = JSON.parse(said);
      ok(r.moved.indexOf('helper') === r.moved.indexOf('bundle sha256:new') + 1,
         `a bundle that moved has its helper installed in the same hello, straight after it is taken (${r.moved.join(', ')})`);
      ok(!r.same.includes('helper'), `...and one that did not move installs nothing (${r.same.join(', ')})`);
    }
    // The loop's hello takes its census beside the loop (B380): the
    // census asks the slow questions right after a full-length work poll,
    // and the loop stood still for it, so a node whose census took longer
    // than fifty seconds read as not answering on every project row for
    // one poll. Driven in process: a slow census, and the step that says
    // hello only once it is there.
    {
      const said = execFileSync('python3', ['-c', `
import importlib.util, json, time, threading
${LOAD_AGENT}
m = agentpkg.load()
m.log = lambda *a, **k: None
a = object.__new__(m.Agent)
a.hello_at, a.census_thread, a.census_next = 1.0, None, None
said = []
a.hello = lambda taken=None: said.append(taken) or (200, {'taken': taken})
def slow():
    time.sleep(0.4)
    return {'slow': True}
a.census_take = slow
first = a.hello_step()
second, turns = None, 0
while second is None and turns < 100:
    time.sleep(0.05); turns += 1
    second = a.hello_step()
# ...and a hello asked for again (the clock zeroed) lets a census still on
# its way go and takes a fresh one beside the loop too, saying hello once
# it is there: taken on the loop, a controller nudging once a minute kept
# the node in census all day and no job was picked up (B644).
a.hello_said, a.hello_at = True, 0
a.census_thread = threading.Thread(target=lambda: time.sleep(0.2)); a.census_thread.start()
a.census_next = {'stale': True}
now = a.hello_step()
fresh, turns = None, 0
while fresh is None and turns < 100:
    time.sleep(0.05); turns += 1
    fresh = a.hello_step()
# ...and one asked for again while that census is on its way lets it go
# and takes a fresh one before the hello: the toolchain census a refusal
# asked for came back without the toolchain just installed (B647).
taken = []
def counted():
    time.sleep(0.3)
    taken.append(len(taken))
    return {'census': len(taken)}
a.census_take = counted
a.hello_said, a.hello_at, a.census_asked = True, 0, False
a.hello_step()                      # the first asked census on its way
a.hello_again('a second ask')
twice, turns = None, 0
while twice is None and turns < 100:
    time.sleep(0.05); turns += 1
    twice = a.hello_step()
# ...while the first hello of a process is said on the loop, at once.
a.hello_said, a.hello_at = False, 0
first_of_process = a.hello_step()
print(json.dumps({'first': first, 'second': second, 'said': said, 'now': now, 'fresh': fresh, 'twice': twice, 'taken': len(taken), 'first_of_process': first_of_process, 'dropped': a.census_next is None and a.census_thread is None}))
`], { encoding: 'utf8' }).trim();
      const r = JSON.parse(said);
      ok(r.twice && r.taken === 2 && r.twice[1].taken && r.twice[1].taken.census === 2,
         `a hello asked for again while its census is on its way lets that one go and takes a fresh one before saying hello (${r.taken} taken, said with ${JSON.stringify(r.twice && r.twice[1].taken)})`);
      ok(r.first === null && r.second && r.second[1].taken && r.second[1].taken.slow && r.said.length === 4
         && r.said[0] && r.said[0].slow && r.now === null && r.fresh && r.said[1] && r.said[1].slow
         && r.first_of_process && r.said[3] === null && r.dropped,
         `the loop's hello waits for a census taken beside it and says hello with it; one asked for again lets a pending census go and takes its own beside the loop; the process's first is said at once (${said})`);
    }
    // B167: the distribution's own root ttyd is switched off by the agent on
    // a managed node, not only by a provisioner run that may never come
    // again; left alone when it is already off, and never on a guest.
    {
      const said = execFileSync('python3', ['-c', `
import importlib.util, json, os, shutil, tempfile
${LOAD_AGENT}
m = agentpkg.load()
m.log = lambda *a, **k: None
m.os.geteuid = lambda: 0
m.shutil.which = lambda n: '/usr/bin/' + n
stamp = tempfile.NamedTemporaryFile(delete=False).name
def case(state, sandbox=True):
    seen = []
    def run(argv, timeout=5):
        seen.append(argv)
        return {'is-enabled': state[0], 'is-active': state[1]}.get(argv[1], '')
    m.SANDBOX_BIN = stamp if sandbox else '/nonexistent/bb-sandbox'
    acted = m.Agent.quiet_distro_ttyd(object.__new__(m.Agent), run)
    return [acted, [a[1:] for a in seen if a[1] == 'disable']]
print(json.dumps({'on': case(('enabled', 'active')), 'running': case(('disabled', 'active')),
                  'off': case(('disabled', 'inactive')), 'guest': case(('enabled', 'active'), False)}))
os.unlink(stamp)
`], { encoding: 'utf8' }).trim();
      const r = JSON.parse(said);
      ok(r.on[0] === true && JSON.stringify(r.on[1]) === JSON.stringify([['disable', '--now', 'ttyd.service']])
         && r.running[0] === true,
         `the agent switches off the distribution's ttyd.service when it is enabled or running (${said.slice(0, 90)})`);
      ok(r.off[0] === false && r.off[1].length === 0 && r.guest[0] === false && r.guest[1].length === 0,
         '...and leaves it alone when it is already off, and on a guest, whose services are its owner\'s');
    }
    // B538: a unit installed before B107 kept systemd's default KillMode, and
    // needrestart's restart of it after an upgrade ended every session. The
    // agent writes the drop-in and needrestart's exception itself, once.
    {
      const said = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
${LOAD_AGENT}
m = agentpkg.load()
m.log = lambda *a, **k: None
m.os.geteuid = lambda: 0
m.shutil.which = lambda n: '/usr/bin/' + n
root = tempfile.mkdtemp()
stamp = os.path.join(root, 'bb-sandbox'); open(stamp, 'w').close()
m.UNIT_DROPIN = os.path.join(root, 'unit.d', 'builderbot.conf')
m.NEEDRESTART_DIR = os.path.join(root, 'needrestart'); os.makedirs(m.NEEDRESTART_DIR)
def case(mode, sandbox=True):
    seen = []
    def run(argv, timeout=5):
        seen.append(argv[1])
        return mode if argv[1] == 'show' else ''
    m.SANDBOX_BIN = stamp if sandbox else '/nonexistent/bb-sandbox'
    return [m.Agent.keep_sessions_through_restart(object.__new__(m.Agent), run), seen]
first = case('control-group')
dropin = open(m.UNIT_DROPIN).read()
conf = open(os.path.join(m.NEEDRESTART_DIR, 'conf.d', 'builderbot.conf')).read()
print(json.dumps({'first': first, 'again': case('process'), 'guest': case('control-group', False),
                  'dropin': dropin, 'conf': conf}))
`], { encoding: 'utf8' }).trim();
      const r = JSON.parse(said);
      ok(JSON.stringify(r.first) === JSON.stringify([['unit', 'needrestart'], ['show', 'daemon-reload']])
         && r.dropin === '[Service]\nKillMode=process\n'
         && r.conf.includes('$nrconf{override_rc}{qr(^builderbot-agent\\.service$)} = 0;'),
         `a unit that would take the sessions on a stop gets KillMode=process in a drop-in, and needrestart is told to leave it alone (${said.slice(0, 120)})`);
      ok(r.again[0].length === 0 && JSON.stringify(r.again[1]) === '["show"]' && r.guest[0].length === 0,
         '...once: a unit that already stops only itself and a needrestart already told are left as they are, and a guest is never touched');
    }
    // R27's refresh, run against the bundle's real layout: bb is at
    // <store>/.bb/current/scripts/bb. The agent looked for .bb/current/bb,
    // which no bundle has, and returned in silence, so no idle session's
    // token was ever refreshed (B335). A stand-in bb records what it was
    // handed, for each live session the controller named.
    {
      const said = execFileSync('python3', ['-c', `
import importlib.util, json, os, stat, tempfile
${LOAD_AGENT}
m = agentpkg.load()
m.log = lambda *a, **k: None
store = tempfile.mkdtemp()
os.makedirs(os.path.join(store, '.bb', 'current', 'scripts'))
seen = os.path.join(store, 'seen')
bb = os.path.join(store, '.bb', 'current', 'scripts', 'bb')
with open(bb, 'w') as f:
    f.write('#!/bin/sh\\nprintf "%s %s %s %s\\\\n" "$1 $2" "$BB_PROJECT" "$BB_ACCOUNT_UID" "$BB_TOKEN" >> ' + seen + '\\n')
os.chmod(bb, 0o755)
m.tc_root = lambda st: store
a = object.__new__(m.Agent)
a.state = {}
a.session_account = lambda: 'whoever'
a.keep_session_tokens([{'project': 'alpha', 'uid': 'u_12345678', 'token': 'bbs_fresh'},
                       {'project': '../x', 'uid': 'u_1', 'token': 'bbs_no'}])
print(json.dumps(open(seen).read().splitlines() if os.path.exists(seen) else []))
`], { encoding: 'utf8' }).trim();
      const rows = JSON.parse(said);
      ok(rows.length === 1 && rows[0] === 'token keep alpha u_12345678 bbs_fresh',
         `the agent hands each live session's fresh token to the bundle's own bb, found where the bundle keeps it (${said})`);
    }
    // ...and a keep that fails is said in the agent's log, once an hour per
    // session: it was silent, so a token ran out with nothing saying why
    // (B419).
    {
      const said = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
${LOAD_AGENT}
m = agentpkg.load()
logged = []
m.log = lambda msg, *a, **k: logged.append(msg)
store = tempfile.mkdtemp()
os.makedirs(os.path.join(store, '.bb', 'current', 'scripts'))
bb = os.path.join(store, '.bb', 'current', 'scripts', 'bb')
with open(bb, 'w') as f:
    f.write('#!/bin/sh\\necho "[builderbot] ERROR: the session token was not kept under /nowhere: PermissionError" >&2\\nexit 1\\n')
os.chmod(bb, 0o755)
m.tc_root = lambda st: store
a = object.__new__(m.Agent)
a.state = {}
a.session_account = lambda: 'whoever'
rows = [{'project': 'alpha', 'uid': 'u_12345678', 'token': 'bbs_fresh'}]
a.keep_session_tokens(rows)
a.keep_session_tokens(rows)
print(json.dumps({"logged": logged, "report": a.keep_report()}))
`], { encoding: 'utf8' }).trim();
      const { logged, report } = JSON.parse(said);
      ok(logged.length === 1 && /session tokens: bb token keep failed \(exit 1\): .*not kept under \/nowhere/.test(logged[0]),
         `...and one it could not keep is said in the agent's log with bb's reason, once, not on every hello (${said.slice(0, 160)})`);
      ok(report.said.length === 1 && report.said[0].key === 'u_12345678/alpha' && /not kept under \/nowhere/.test(report.said[0].msg)
         && report.ok === 0,
         `...and kept for the hello, which carries it to the controller: the journal was the only place it went (B419) (${JSON.stringify(report).slice(0, 160)})`);
    }
    // The session's view (R35): the helper travels in the bundle, and what
    // the agent writes for it is one rule for one command, the layout, and a
    // respawn that runs again only a launcher it recognizes.
    {
      const bin = '/opt/fake/bb-session';
      const out = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, re
${LOAD_AGENT}
m = agentpkg.load()
# An enrolled node's directory in the store, its node id (R196): with none
# there is no toolchain directory at all.
m.use_scope('/p', 'n_0000abcd')
home = '/home/builder/users/u_0000abcd/.cache/builderbot/u/u_0000abcd/project'
ok = lambda c: re.fullmatch(m.RESPAWNABLE, c) is not None
# A launcher line with the projects the session reads, one --reads each
# (prefs.reads), is still a line a respawn may run again.
assert ok('sudo -n /opt/fake/bb-session enter --project alpha --account u_0000abcd --home /home/x --cwd /w/alpha --reads beta --reads gamma --env /e -- ' + home + '/alpha/claude-run.sh'), 'reads'

def respawn(start):
    # tmux_ops against a tmux that records what it was asked and answers the
    # pane's start command, which is all a respawn reads.
    a, seen = object.__new__(m.Agent), []
    a._tmux = lambda argv, timeout=10: seen.append(argv) or (start if argv[0] == 'display-message' else '')
    a.tmux_ops([{'session': 'u_0000abcd~claude-alpha', 'respawn': True}])
    return seen[-1]
print(json.dumps({
  'sudoers': m.session_sudoers('builder'),
  'conf': m.session_conf({'stores': {'data': '/d', 'artifacts': '/a', 'toolchains': '/p'}}, 'builder'),
  'tcroot': m.tc_root({'stores': {'toolchains': '/p'}}),
  'good': [ok(f'sudo -n ${bin} enter --project alpha --account u_0000abcd --home /home/builder/users/u_0000abcd --cwd /workspace/alpha --env {home}/alpha/session.env -- {home}/alpha/claude-run.sh'),
           ok(f'{home}/alpha/claude-run.sh'), ok('/home/builder/.cache/builderbot/claude-run-alpha.sh')],
  'bad': [ok(f'{home}/alpha/claude-run.sh; id'), ok(f'sudo -n /tmp/other enter -- {home}/alpha/claude-run.sh'),
          ok(f'sudo -n ${bin} enter --project a;id -- {home}/alpha/claude-run.sh'), ok("bash -c 'id' /x/builderbot/project/a/claude-run.sh")],
  'iso': m.isolation_now(),
  'respawn': respawn(f'sudo -n ${bin} enter --project alpha --account u_0000abcd --cwd /workspace/alpha -- {home}/alpha/claude-run.sh'),
  'flat': respawn('/home/builder/.cache/builderbot/claude-run-alpha.sh')}))
`], { encoding: 'utf8', env: { ...process.env, BUILDERBOT_SESSION_BIN: bin } }).trim());
      ok(existsSync(`${store}/.bb/current/nodes/bb-session`)
         && out.sudoers.includes(`Defaults!${bin} !use_pty, !lecture`)
         && out.sudoers.includes(`builder ALL=(root) NOPASSWD: ${bin}`)
         && (out.sudoers.match(/NOPASSWD/g) || []).length === 1
         && /SESSION_USER=builder\nWORKSPACE=\/workspace\nDATA_STORE=\/d\nARTIFACTS_STORE=\/a\n/.test(out.conf)
         && out.conf.includes(`TOOLCHAINS_STORE=${out.tcroot}\n`) && out.tcroot.startsWith('/p/'),
         `the bundle carries bb-session, and the agent's sudo rule names that one command for the session account alone (${out.sudoers.split('\n')[3]})`);
      ok(out.good.every(Boolean) && !out.bad.some(Boolean),
         `a respawn runs again a launcher inside the view, a plain one, or one from before the view, and nothing else (${JSON.stringify(out.good)} ${JSON.stringify(out.bad)})`);
      ok(JSON.stringify(out.respawn) === JSON.stringify(['respawn-pane', '-k', '-t', 'u_0000abcd~claude-alpha', 'sudo', '-n', bin, 'enter',
           '--project', 'alpha', '--account', 'u_0000abcd', '--cwd', '/workspace/alpha', '--',
           '/home/builder/users/u_0000abcd/.cache/builderbot/u/u_0000abcd/project/alpha/claude-run.sh', '--respawn'])
         && JSON.stringify(out.flat.slice(4)) === JSON.stringify(['/home/builder/.cache/builderbot/claude-run-alpha.sh', '--respawn']),
         `a respawn hands tmux the view's launcher line word by word, since one string with spaces is a program nobody has (${out.respawn.slice(4, 6).join(' ')})`);
      ok(out.iso.sessions === false && /root/.test(out.iso.why),
         `an agent that is not root says its sessions are not kept to their project, and why (${out.iso.why})`);
    }
    // Each session kept to its own project's network (R79). The halves that
    // need no root, driven directly: the resolvers a session's namespace can
    // reach, the layout file, the addresses each session may reach from what
    // the controller says its project owns, the sets as one transaction, the
    // files bb-session leaves, and Docker's three rules, in their order.
    {
      const sn = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
${LOAD_AGENT}
m = agentpkg.load()
d = tempfile.mkdtemp()
def f(name, text):
    p = os.path.join(d, name); open(p, 'w').write(text); return p
stub = f('stub', 'nameserver 127.0.0.53\\noptions edns0\\n')
up = f('up', 'nameserver 127.0.0.53\\nnameserver fe80::1\\nnameserver 192.168.1.1\\nsearch lan\\n')
sessions = [{'addr': '10.231.0.2', 'if': 'bbs0', 'project': 'alpha'}, {'addr': '10.231.0.6', 'if': 'bbs1', 'project': 'beta'}]
containers = [{'name': 'alpha-app-1', 'compose': 'alpha', 'ips': ['172.18.0.2']},
              {'name': 'plex', 'compose': '', 'ips': ['172.19.0.5']},
              {'name': 'beta-db-1', 'compose': 'beta', 'ips': ['172.20.0.3']},
              {'name': 'stranger', 'compose': 'other', 'ips': ['172.21.0.9']}]
own = {'alpha': {'compose': ['alpha'], 'names': ['plex']}, 'beta': {'compose': ['beta'], 'names': []}}
pairs = m.sessnet_pairs(sessions, own, containers)
# ...and what alpha holds on its other nodes (R82): a container's published
# port on a Linux node, and a Mac reached whole.
own['alpha']['peers'] = [['192.168.1.17', 8088], ['192.168.1.17', 32400], ['bad', 1], ['192.168.1.17', 0]]
own['alpha']['hosts'] = ['192.168.1.40', 'nope']
peers = m.sessnet_peers(sessions, own)
hosts = m.sessnet_hosts(sessions, own)
# The files bb-session leaves: one live, one whose link is gone, one malformed.
reg = tempfile.mkdtemp()
open(os.path.join(reg, 's0.json'), 'w').write(json.dumps({'project': 'alpha', 'addr': '10.231.0.2', 'if': 'bbs0'}))
open(os.path.join(reg, 's1.json'), 'w').write(json.dumps({'project': 'beta', 'addr': '10.231.0.6', 'if': 'bbs1'}))
open(os.path.join(reg, 's2.json'), 'w').write(json.dumps({'project': 'x;id', 'addr': '10.231.0.10', 'if': 'bbs2'}))
real = m.os.path.exists
m.os.path.exists = lambda p: p in ('/sys/class/net/bbs0', '/sys/class/net/bbs2') if p.startswith('/sys/class/net/') else real(p)
live = m.sessnet_sessions(reg)
m.os.path.exists = real
# Docker's rules, against an iptables that records what it was asked and
# answers -S from what it holds: none, the right three, and a drop alone.
class Ipt:
    def __init__(self, held): self.held, self.asked = list(held), []
    def __call__(self, argv, **k):
        a = argv[3:]; self.asked.append(a)
        class R: returncode = 0; stdout = ''; stderr = ''
        if a[0] == '-S': R.stdout = '-N DOCKER-USER\\n' + ''.join('-A DOCKER-USER ' + ' '.join(r) + '\\n' for r in self.held)
        elif a[0] == '-C': R.returncode = 0 if a[2:] in self.held else 1
        elif a[0] == '-D': self.held.remove(a[2:])
        elif a[0] == '-I': self.held.insert(int(a[2]) - 1, a[3:])
        return R
m._have = lambda b: True
rules = [list(r) for r in m.DOCKER_USER_RULES]
def order(held):
    ipt = Ipt(held); m.subprocess.run = ipt; m.docker_user(True)
    return [ipt.held, sum(1 for a in ipt.asked if a[0] in ('-I', '-D'))]
fresh, kept, fixed = order([]), order(rules), order([rules[2]])
off = Ipt(rules); m.subprocess.run = off; m.docker_user(False)
print(json.dumps({
  'ns': m.sessnet_resolvers((stub, up)), 'none': m.sessnet_resolvers((stub,)),
  'resolv': m.sessnet_resolv_text(*m.sessnet_resolvers((stub, up))),
  'on': m.session_conf({'stores': {}}, 'builder', True), 'off': m.session_conf({'stores': {}}, 'builder'),
  'pairs': pairs,
  'fill': m.sessnet_fill([('192.168.1.15', 7680)], ['192.168.1.1'], pairs, peers, hosts),
  'peers': peers, 'hosts': hosts,
  'table': m.sessnet_table(), 'live': live,
  # Each project's containers kept to their own network (R178): the bridge
  # pairs and the (bridge, host port) pairs from the containers' bridges and
  # the controller's map; a compose project the map does not name keeps to
  # its own bridge.
  'ctr': m.ctrnet_reach([{'name': 'alpha-app-1', 'compose': 'alpha', 'ips': ['172.18.0.2'], 'bridges': ['br-aaaaaaaaaaaa'], 'ports': [8080]},
                         {'name': 'beta-db-1', 'compose': 'beta', 'ips': ['172.20.0.3'], 'bridges': ['br-bbbbbbbbbbbb'], 'ports': [5432]},
                         {'name': 'stranger', 'compose': 'other', 'ips': ['172.21.0.9'], 'bridges': ['br-cccccccccccc'], 'ports': [9000]}],
                        {'alpha': {'owner': 'alpha', 'to': ['alpha', 'beta']}, 'beta': {'owner': 'beta', 'to': ['beta']}}),
  # ...and BuilderBot's own (R180): the map's 'all' gives a System-owned
  # compose project every bridge and every published port here, the
  # stranger's included, which the controller never named.
  'ctrsys': m.ctrnet_reach([{'name': 'alpha-app-1', 'compose': 'alpha', 'ips': ['172.18.0.2'], 'bridges': ['br-aaaaaaaaaaaa'], 'ports': [8080]},
                            {'name': 'stranger', 'compose': 'other', 'ips': ['172.21.0.9'], 'bridges': ['br-cccccccccccc'], 'ports': [9000]},
                            {'name': 'monitor-1', 'compose': 'monitor', 'ips': ['172.22.0.2'], 'bridges': ['br-dddddddddddd'], 'ports': [3000]}],
                           {'alpha': {'owner': 'alpha', 'to': ['alpha']}, 'monitor': {'owner': 'System', 'to': ['alpha', 'monitor'], 'all': True}}),
  'ctrfill': m.ctrnet_fill(['br-aaaaaaaaaaaa'], [('br-aaaaaaaaaaaa', 'br-aaaaaaaaaaaa')], [('br-aaaaaaaaaaaa', 8080)], [('192.168.1.15', 7680)], ['192.168.1.1']),
  'ctrtable': m.ctrnet_table(),
  'rules': rules, 'fresh': fresh, 'kept': kept, 'fixed': fixed, 'off': off.held,
  # What the node's own network already has in the range: a LAN, a VPN or a
  # VM bridge in 10.231.x.x, from ip -j; a session's own link does not count.
  'clash': [m.sessnet_clash([{'ifname': 'eth0', 'addr_info': [{'family': 'inet', 'local': '192.168.1.18', 'prefixlen': 24}]},
                             {'ifname': 'bbs3', 'addr_info': [{'family': 'inet', 'local': '10.231.0.13', 'prefixlen': 30}]}],
                            [{'dst': 'default', 'dev': 'eth0'}, {'dst': '10.231.0.12/30', 'dev': 'bbs3'}]),
            m.sessnet_clash([{'ifname': 'virbr0', 'addr_info': [{'family': 'inet', 'local': '10.231.4.1', 'prefixlen': 24}]}], []),
            m.sessnet_clash([], [{'dst': '10.0.0.0/8', 'dev': 'tun0'}])]}))
`], { encoding: 'utf8' }).trim().split('\n').pop());
      ok(JSON.stringify(sn.ns) === JSON.stringify([['192.168.1.1'], 'lan']) && sn.none[0].length === 0
         && /nameserver 192\.168\.1\.1\nsearch lan\n$/.test(sn.resolv),
         `a session's resolvers are the node's upstream ones, IPv4 and off the loopback, and none when the node names only its loopback (${JSON.stringify(sn.ns)})`);
      ok(/\nSESSION_NET=on\nSESSION_NET_CIDR=10\.231\.0\.0\/16\n$/.test(sn.on) && !/SESSION_NET/.test(sn.off),
         '...the layout file says so only when it is on, and an older bb-session reads the file it always read');
      ok(sn.ctrsys[1].some(p => p[0] === 'br-dddddddddddd' && p[1] === 'br-cccccccccccc')
         && sn.ctrsys[2].some(p => p[0] === 'br-dddddddddddd' && p[1] === 9000)
         && !sn.ctrsys[1].some(p => p[0] === 'br-aaaaaaaaaaaa' && p[1] === 'br-dddddddddddd'),
         `a System-owned compose project reaches every bridge and port here, the stranger's included, and nobody reaches it back (${JSON.stringify(sn.ctrsys[1])})`);
      ok(JSON.stringify(sn.ctr[0]) === JSON.stringify(['br-aaaaaaaaaaaa', 'br-bbbbbbbbbbbb', 'br-cccccccccccc'])
         && JSON.stringify(sn.ctr[1]) === JSON.stringify([['br-aaaaaaaaaaaa', 'br-aaaaaaaaaaaa'], ['br-aaaaaaaaaaaa', 'br-bbbbbbbbbbbb'], ['br-bbbbbbbbbbbb', 'br-bbbbbbbbbbbb'], ['br-cccccccccccc', 'br-cccccccccccc']])
         && JSON.stringify(sn.ctr[2]) === JSON.stringify([['br-aaaaaaaaaaaa', 5432], ['br-aaaaaaaaaaaa', 8080], ['br-bbbbbbbbbbbb', 5432], ['br-cccccccccccc', 9000]]),
         `a project's containers reach their own bridge and ports and those of the projects it reads, a stranger its own alone (R178) (${JSON.stringify(sn.ctr)})`);
      ok(/add element inet builderbot_ctrnet pairs \{ "br-aaaaaaaaaaaa" \. "br-aaaaaaaaaaaa" \}/.test(sn.ctrfill) && /ownports \{ "br-aaaaaaaaaaaa" \. 8080 \}/.test(sn.ctrfill)
         && /typeof iifname \. oifname/.test(sn.ctrtable) && /tcp dport \{ 80, 443 \} accept/.test(sn.ctrtable) && /oifname @bridges drop/.test(sn.ctrtable),
         '...the sets are written as nft reads them, and the table drops a bridge to another bridge and lets the node\'s 80 and 443 through');
      ok(JSON.stringify(sn.pairs) === JSON.stringify([['10.231.0.2', '172.18.0.2'], ['10.231.0.2', '172.19.0.5'], ['10.231.0.6', '172.20.0.3']]),
         `each session may reach its own project's containers, by compose project and by the name the operator gave, and no other (${JSON.stringify(sn.pairs)})`);
      ok(/^flush set inet builderbot_sessnet ctl\nflush set inet builderbot_sessnet dns\nflush set inet builderbot_sessnet own\n/.test(sn.fill)
         && sn.fill.includes('add element inet builderbot_sessnet own { 10.231.0.2 . 172.18.0.2, 10.231.0.2 . 172.19.0.5, 10.231.0.6 . 172.20.0.3 }')
         && sn.fill.includes('ctl { 192.168.1.15 . 7680 }'),
         '...written as one transaction that replaces the sets whole, the controller and the resolvers with them');
      ok(JSON.stringify(sn.peers) === JSON.stringify([['10.231.0.2', '192.168.1.17', 8088], ['10.231.0.2', '192.168.1.17', 32400]])
         && JSON.stringify(sn.hosts) === JSON.stringify([['10.231.0.2', '192.168.1.40']]),
         `a session reaches its project's published ports on the project's other nodes, and a Mac there whole; a bad address or port is dropped (${JSON.stringify(sn.peers)})`);
      ok(sn.fill.includes('add element inet builderbot_sessnet peers { 10.231.0.2 . 192.168.1.17 . 8088, 10.231.0.2 . 192.168.1.17 . 32400 }')
         && sn.fill.includes('add element inet builderbot_sessnet hosts { 10.231.0.2 . 192.168.1.40 }')
         && /@peers goto pass/.test(sn.table) && /ip saddr \. ip daddr @hosts goto pass/.test(sn.table)
         && sn.table.indexOf('@hosts goto pass') < sn.table.indexOf('@local reject'),
         '...in two more sets of the same transaction, passed before the private ranges are refused');
      ok(/ip daddr @local reject/.test(sn.table) && /ip saddr \. ip daddr @own goto pass/.test(sn.table)
         && sn.table.indexOf('@own goto pass') < sn.table.indexOf('@local reject')
         && /meta mark set meta mark or 0x10000000 accept/.test(sn.table) && /oifname "bbs\*" drop/.test(sn.table)
         && /iifname "bbs\*" reject/.test(sn.table) && /masquerade/.test(sn.table),
         '...the table lets through what the sets name before it refuses the rest that is not the internet, marks what it passes, and lets nothing start a connection into a session or at the node');
      ok(sn.live.length === 1 && sn.live[0].project === 'alpha',
         `a session whose link is gone is over, and a file that names no real project is nobody's (${JSON.stringify(sn.live)})`);
      ok(sn.clash[0] === '' && /10\.231\.4\.1\/24 on virbr0/.test(sn.clash[1]) && /a route to 10\.0\.0\.0\/8 on tun0/.test(sn.clash[2]),
         `a node whose own network already uses the range is not offered it, and says which address or route (a VM bridge: ${sn.clash[1]}; a VPN: ${sn.clash[2]}), while a session's own link is no clash`);
      ok(/chain output \{[^}]*oifname "bbs\*" meta l4proto \{ tcp, udp \} ct state new reject/.test(sn.table),
         '...and nothing on the node itself, any account\'s program, opens a connection into a session either');
      ok(/chain input \{[^}]*iifname "bbs\*" ip daddr \. tcp dport @ctl accept[^}]*@dns udp dport 53 accept/.test(sn.table)
         && /ct original ip daddr \. ct original proto-dst @ctl goto pass/.test(sn.table),
         '...while the controller and the resolvers are reached even on the node\'s own address, or behind a port Docker publishes on it');
      // The thread that keeps it, one turn at a time against stubs: wanted
      // and not possible is closed (the layout file stays on so bb-session
      // refuses, the ready mark goes, the row hears why); wanted and
      // possible writes the mark last; off with no session takes it down
      // only after a half-minute grace.
      const st = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile, time
${LOAD_AGENT}
m = agentpkg.load()
m.log = lambda *a, **k: None
m.SESSNET_DIR = tempfile.mkdtemp()
ran = []
class R: returncode = 0; stdout = ''; stderr = ''
m.subprocess.run = lambda argv, **k: ran.append(argv[:3]) or R()
m.docker_user = lambda on: ''
m.sessnet_resolvers = lambda paths=None: (['192.168.1.1'], '')
m.sessnet_containers = lambda: []
m.sessnet_ctl = lambda url: [('192.168.1.15', 7680)]
class A:
    state = {'controller': 'http://192.168.1.15:7680', 'session_net': {'on': True, 'own': {}}}
    hello_at = 1
    refreshed = 0
    def refresh_session_tool(self): self.refreshed += 1
a = A(); sn = m.SessionNet(a)
ready = os.path.join(m.SESSNET_DIR, 'ready')
open(ready, 'w').write('x')
m.sessnet_can = lambda: (False, 'the agent does not run as root here')
m.sessnet_sessions = lambda d=None: []
sn.step()
cannot = {'conf_on': sn.conf_on, 'ready': os.path.exists(ready), 'status': dict(m.SESSNET_STATUS),
          'conf': m.session_conf({'stores': {}}, 'builder', sn.conf_on)}
m.sessnet_can = lambda: (True, ''); sn.can_at = 0
sn.step()
can = {'ready': os.path.exists(ready), 'status': dict(m.SESSNET_STATUS), 'nft': [r for r in ran if r[0] == m.NFT_BIN]}
# A step with nothing moved asks for no hello, with the containers' entry
# (ctr) on the stored status beside the session's own keys (B647).
a.hello_at = 1
sn.step()
still = a.hello_at
a.state['session_net'] = {'on': False, 'own': {}}
sn.step()
off1 = {'conf_on': sn.conf_on, 'up': sn.up, 'ready': os.path.exists(ready)}
sn.empty_since -= 60
sn.step()
off2 = {'up': sn.up, 'ready': os.path.exists(ready), 'status': dict(m.SESSNET_STATUS)}
print(json.dumps({'cannot': cannot, 'can': can, 'off1': off1, 'off2': off2, 'refreshed': a.refreshed, 'still': still, 'ctr': 'ctr' in m.SESSNET_STATUS}))
`], { encoding: 'utf8' }).trim().split('\n').pop());
      ok(st.cannot.conf_on === true && /SESSION_NET=on/.test(st.cannot.conf) && st.cannot.ready === false
         && st.cannot.status.active === false && /root/.test(st.cannot.status.why),
         `wanted and not possible is closed: the layout file says on so bb-session refuses, the ready mark is gone, and the row hears why (${JSON.stringify(st.cannot.status)})`);
      ok(st.can.ready === true && st.can.status.active === true && st.can.nft.length >= 2,
         `wanted and possible makes the table and the sets, and writes the mark last (${st.can.nft.length} nft calls)`);
      ok(st.still === 1 && st.ctr === true,
         `a step with nothing moved asks for no hello, the containers' entry on the stored status notwithstanding (B647: clock ${st.still}, ctr ${st.ctr})`);
      ok(st.off1.conf_on === false && st.off1.up === true && st.off2.up === false && st.off2.ready === false
         && st.refreshed === 1,
         'off takes the layout file off at once and the table down only after a half-minute with no session, since one may still be making its link');
      const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
      ok(same(sn.fresh[0], sn.rules) && same(sn.kept, [sn.rules, 0]) && same(sn.fixed[0], sn.rules) && sn.off.length === 0,
         `Docker's forwarding gets its three rules in order (replies in, what the table marked, nothing else from a session), leaves them when they are right, puts a drop that stands alone back behind the other two, and takes all three away (${JSON.stringify(sn.fresh[0].map(r => r[r.length - 1]))})`);
    }
    // ...and the ones before it do not pile up forever. One directory per
    // delivery, one delivery per commit that touches bb: 33 of them in four
    // days on the first node anybody looked at. Driven directly rather than
    // through a run: thirty-three deliveries is not something to wait for.
    const pruned = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile, time
${LOAD_AGENT}
m = agentpkg.load()
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
       `a delivery does not keep every bundle before it; the newest few stay (${pruned.length} left)`);
    ok(pruned.includes('bundle.tar') && pruned.includes('current'),
       '...and nothing that is not a bundle is touched');
    // The node's boot rides with it: a terminal's URL carries the boot of
    // the machine the session runs ON, or bb-tty there refuses every
    // connection as a stale tab, which is what the first real session did.
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
    // The scanner's reports live on the controller and cover the whole share,
    // so a relayed `bb findings --all` is the one verb whose own flag walks
    // out of the project this door keeps a session inside. Measured from a
    // real session before this refusal existed: it listed file paths out of
    // three other projects' trees.
    const everyone = await relay({ argv: ['findings', '--all'], cwd: `${DIR}/ws/alpha` });
    ok(everyone.status === 403 && /its own/.test(everyone.error || ''),
       `a session's bb findings --all is refused, naming what it may read instead (${
         (everyone.error || '').slice(0, 60)})`);
    ok((await relay({ argv: ['findings', '-a'], cwd: `${DIR}/ws/alpha` })).status === 403,
       '...by the short flag too, which is the same door');
    ok((await relay({ argv: ['findings'], cwd: `${DIR}/ws/alpha` })).status === 200,
       '...while its own project\'s findings go through');

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
                    BB_TOKEN: short, BB_PROJECT: 'alpha', XDG_CACHE_HOME: cache,
                    BB_ACCOUNT_UID: 'u_0000abcd' };
      execFileSync('bash', [`${REPO}/scripts/bb`, 'roadmap'], { encoding: 'utf8', env, stdio: ['ignore', 'pipe', 'pipe'] });
      // Under the account's id (B159): the cache folder is shared between
      // accounts on a node, so the uid is what keeps one account's token out
      // of another's session.
      const kept = existsSync(`${cache}/builderbot/u/u_0000abcd/project/alpha/token`)
        ? readFileSync(`${cache}/builderbot/u/u_0000abcd/project/alpha/token`, 'utf8').trim() : '';
      ok(/^bbs_/.test(kept) && expOf(kept) > expOf(short),
         'bb keeps the renewed token in the account\'s cache, where it reads when the environment\'s has expired');
      const again = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', '--now'],
        { encoding: 'utf8', env: { ...env }, stdio: ['ignore', 'pipe', 'pipe'] }).trim();
      ok(again === kept, '...and prefers it over the older one in its environment from then on');
    }
    const settings = await relay({ argv: ['settings', '--json'] });
    ok(settings.code === 0 && JSON.parse(settings.out).project === 'alpha'
       && typeof JSON.parse(settings.out).locked === 'boolean',
       'bb settings --json relays the project\'s settings, lock included: what bb-tty and bb build read on a node');
    const other = await relay({ argv: ['roadmap'], project: 'ep.silon' });
    ok(other.status === 403 && /alpha does not read ep\.silon/.test(other.error),
       `a token for alpha cannot ask about another project, and says it does not read it (${other.error})`);
    const sdk = await relay({ argv: ['sdk'] });
    ok(sdk.status === 400 && /not relayed/.test(sdk.error),
       'bb toolchains is refused: it answers for the machine the session is on');
    const emu = await relay({ argv: ['emu', 'start'] });
    ok(emu.status === 400, '...and so is bb emu');
    const nobody = await relay({ argv: ['roadmap'] }, 'Bearer bbs_nonsense');
    ok(nobody.status === 401, 'a token that does not verify gets nothing');

    // ---- a Claude login belongs to one account on one MACHINE ---------------
  // The grant never travels (R47). Every failure this had came from one
  // OAuth pair living on several machines: a refresh rotates the refresh
  // token, so two copies sign each other out (bug #64), and a machine that
  // was away holds one the server has retired (B100). Each machine is signed
  // in for itself, from its own row, and keeps the grant it alone refreshes.
  //
  // So what crosses the wire is one sentence and no secret: "this account is
  // signed in here as X", or that it is not.
  {
    const seed = readFileSync(`${DIR}/home/.claude/.bb-grant.json`, 'utf8');
    const forMe = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
      { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
    const api = async (body) => { const r = await fetch(URL.replace(/\/$/, '') + '/api/v1/claude-login',
      { method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + forMe },
        body: JSON.stringify(body) });
      return { status: r.status, ...(await r.json()) }; };
    // Where this account is signed in, as the page is told it.
    const where = async () => ((await (await fetch(URL.replace(/\/$/, '') + '/api/status', { headers: auth })).json()).claude_auth || {}).nodes || {};

    // Which node is REPORTING is the node of the session's own project,
    // which the token proves. A session names the node it is on, since a
    // project may work on several, and is believed only when that node is
    // one of the project's: a machine that could name any node could report
    // for another.
    await fetch(URL.replace(/\/$/, '') + '/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') },
      body: JSON.stringify({ project: 'alpha', node: minted.id }) });
    let w = await api({ email: 'tester@example.com', plan: 'max', signed_in: true });
    ok(w.ok && w.plan === 'max' && Object.keys(w).every(k => ['status', 'ok', 'plan'].includes(k)),
       `a node reports which Anthropic account it signed this one in as, and the answer carries no credential (${Object.keys(w).join()})`);
    ok((await where())[minted.id]?.email === 'tester@example.com',
       '...which is what that node\'s row names, for that account');
    await api({ email: 'tester@example.com', plan: 'max', signed_in: true, node: 'n_somebody_elses' });
    ok(!('n_somebody_elses' in await where()), 'a session cannot report for a node that is not one of its project\'s');
    // Another Anthropic account on this node is another sign-in there, not
    // a refusal: the login is the machine's, and the row says which.
    const two = await api({ email: 'two@example.invalid', signed_in: true });
    ok(two.ok && two.plan === '' && (await where())[minted.id]?.email === 'two@example.invalid',
       `a node signed in to a different Anthropic account is recorded as that, without the last one's plan (${two.error || two.plan})`);
    await api({ email: 'tester@example.com', plan: 'max', signed_in: true });

    // The flow itself finds Claude Code where a SESSION finds it: the session
    // account's own ~/.local/bin (the provisioner's install) and the pinned
    // copy, not only the signing-in account's home. The owner's home is the
    // session account's, so a second account was the one told "not
    // installed" on a machine whose sessions ran it fine (24 Sep).
    {
      const base = `${DIR}/flow-home`;
      mkdirSync(`${base}/.local/bin`, { recursive: true });
      writeFileSync(`${base}/.local/bin/claude`, '#!/bin/sh\necho "fake claude $*"\n');
      chmodSync(`${base}/.local/bin/claude`, 0o755);
      const run = (uid) => { try {
        return { code: 0, out: execFileSync('bash', [`${REPO}/scripts/bb`, 'login', '--flow'],
          { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
            env: { ...process.env, BUILDERBOT_ROLE: 'node', BUILDER_HOME: base, HOME: base,
                   BB_ACCOUNT_UID: uid, BB_TOKEN: '', PATH: '/usr/bin:/bin',
                   BB_CLAUDE_PINNED: `${base}/no-pin` } }) };
      } catch (e) { return { code: e.status, out: String(e.stdout) + String(e.stderr) }; } };
      const second = run('u_0badf00d');
      ok(second.code === 0 && /fake claude auth login/.test(second.out),
         `the sign-in flow for a second account runs the session account's Claude Code (${
           second.out.trim().split('\n').pop().slice(0, 70)})`);
      ok(existsSync(`${base}/users/u_0badf00d/.claude`),
         "...with the credential's home the second account's own");
      // ...and the sign-out the node's row asks for is the same shape the
      // other way: `claude auth logout` in that account's home here, and in
      // nobody else's. Run here with a home and a Claude Code of its own: a
      // job on this suite's agent would find the machine's real ones.
      const out = (uid) => { try {
        return { code: 0, out: execFileSync('bash', [`${REPO}/scripts/bb`, 'login', '--out'],
          { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
            env: { ...process.env, BUILDERBOT_ROLE: 'node', BUILDER_HOME: base, HOME: base,
                   BB_ACCOUNT_UID: uid, BB_TOKEN: '', PATH: '/usr/bin:/bin',
                   BB_CLAUDE_PINNED: `${base}/no-pin` } }) };
      } catch (e) { return { code: e.status, out: String(e.stdout) + String(e.stderr) }; } };
      writeFileSync(`${base}/.local/bin/claude`, '#!/bin/sh\necho "fake claude $* in $HOME"\n');
      chmodSync(`${base}/.local/bin/claude`, 0o755);
      const gone = out('u_0badf00d');
      ok(gone.code === 0 && new RegExp(`fake claude auth logout in ${base}/users/u_0badf00d`).test(gone.out),
         `the sign-out runs claude auth logout in that account's home on this machine (${gone.out.trim().split('\n')[0].slice(-60)})`);
      const whose = out('');
      ok(whose.code !== 0 && /names the account/.test(whose.out) && !/fake claude/.test(whose.out),
         '...and with no account named it signs nobody out');
      rmSync(`${base}/.local/bin/claude`);
      const none = run('u_0badf00d');
      ok(none.code !== 0 && /Update in the Nodes tab/.test(none.out),
         '...and with none anywhere the refusal names the Nodes tab as the way out');
    }

    // A token for the project alone (a relayed verb's) is nobody's account,
    // and cannot report for one.
    const anon = await fetch(URL.replace(/\/$/, '') + '/api/v1/claude-login',
      { method: 'POST', headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'x@example.invalid', signed_in: true }) });
    ok(anon.status === 403, 'a token for the project alone cannot speak for an account');

    // ...and the AGENT can say it too, on its heartbeat, without a session
    // having to run (B104): a node signed in with nothing running reads as
    // signed in on its row, and a sign-out made there shows without one.
    const owner = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
    const nodeTok = JSON.parse(readFileSync(NODE_JSON, 'utf8')).token;
    const beat = (logins) => fetch(URL.replace(/\/$/, '') + '/api/v1/agent/work',
      { method: 'POST', headers: { Authorization: 'Bearer ' + nodeTok,
                                   'Content-Type': 'application/json' },
        body: JSON.stringify({ sample: { cpu_pct: 1, logins }, running: [], wait: 0 }) });
    await api({ signed_in: false });
    ok(!(minted.id in await where()), 'a node saying this account is not signed in there takes it off the record');
    await beat([{ uid: owner, email: 'tester@example.com' }]);
    ok((await where())[minted.id]?.email === 'tester@example.com',
       'the node\'s own heartbeat puts its login on the record, with no session in it');
    await beat([{ uid: owner, email: '' }]);
    ok(!(minted.id in await where()),
       '...and a heartbeat saying that home holds no credential takes it off again');
    // The node's sessions, sent the moment one changes rather than on the
    // heartbeat's turn (the operator, 25 Sep): who has a session where and
    // whether it is working, read back cheaply from /api/live, with the
    // revs token `live` moving so the page knows to ask.
    {
      const tell = (title) => fetch(URL.replace(/\/$/, '') + '/api/v1/agent/sessions',
        { method: 'POST', headers: { Authorization: 'Bearer ' + nodeTok, 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessions: [{ name: `${owner}~claude-alpha`, attached: true, cwd: '/workspace/alpha',
                                              created: 1, title }] }) });
      const get = async p => (await fetch(URL.replace(/\/$/, '') + p, { headers: auth })).json();
      const live = () => get('/api/live');
      const tok = async () => (await get('/api/revs?p=')).live;
      // The suite's own agent is running and heartbeats its own report of
      // this node's sessions, which can land between a tell and the reads
      // after it (B427): idle, read, busy, read, and once more when a
      // heartbeat came between, which leaves the token as the agent had it.
      let busy = {}, moved = false;
      for (let tries = 0; tries < 3 && !moved; tries++){
        await tell('Claude Code');
        const t0 = await tok();
        await tell('◐ Reading the tests');
        busy = await live();
        moved = (busy.claude_with.alpha || []).includes('test') && (busy.claude_busy.alpha || []).includes('test')
          && await tok() !== t0;
      }
      ok(moved,
         `a node says its sessions changed and /api/live shows the session working at once, the revs token moving with it (${JSON.stringify(busy).slice(0, 80)})`);
      await tell('Claude Code');
      const idle = await live();
      ok((idle.claude_with.alpha || []).includes('test') && !(idle.claude_busy.alpha || []).includes('test'),
         '...and waiting when its title says so');
      await fetch(URL.replace(/\/$/, '') + '/api/v1/agent/sessions',
        { method: 'POST', headers: { Authorization: 'Bearer ' + nodeTok, 'Content-Type': 'application/json' },
          body: JSON.stringify({ sessions: [] }) });
    }
    // The seed goes back, and alpha to having no node.
    writeFileSync(`${DIR}/home/.claude/.bb-grant.json`, seed);
    await fetch(URL.replace(/\/$/, '') + '/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') },
      body: JSON.stringify({ project: 'alpha', node: '' }) });
  }

    // ---- the hooks post from a node (roadmap #24) ---------------------------
    // Inside a session on a node the two hooks bb-tty writes into its
    // settings have no /config to write: they post to the controller with
    // the session's token, and the same modules record them here: the
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
      // ---- bb-gate: nothing runs while BuilderBot is away --------------
      // A session outlives an update. The gate refuses every tool call while
      // the controller does not answer, and lets the first call after it
      // comes back through without a wait. It used to weigh a second thing,
      // the project's CLAUDE.md block being from another window; that went
      // with the block (R63 step 3), so this is the whole of the rule now.
      {
        const gt = `${DIR}/gatetree`; mkdirSync(gt, { recursive: true });
        const cache = `${DIR}/gatecache`; mkdirSync(cache, { recursive: true });
        const genv = extra => ({ ...nodeEnv, BB_TREE: gt, XDG_CACHE_HOME: cache,
                                 BUILDERBOT_ROLE: 'controller', ...extra });
        const gate = extra => { try {
          execFileSync('python3', [`${REPO}/scripts/dashboard/bb-gate`, 'alpha', 'x'],
            { input: '{"tool_name":"Bash"}', encoding: 'utf8', env: genv(extra), stdio: ['pipe', 'pipe', 'pipe'] });
          return { code: 0, err: '' };
        } catch (e) { return { code: e.status, err: String(e.stderr) }; } };
        // u/_none: this env names no account, and the gate is per account (B159).
        const fresh = () => rmSync(`${cache}/builderbot/u/_none/project/alpha/gate`, { force: true });
        let r = gate({});
        ok(r.code === 0, `with the controller up, a tool call goes through (${r.code} ${r.err.slice(0, 60)})`);
        fresh();
        r = gate({ BB_CONTROLLER: 'http://127.0.0.1:1' });
        ok(r.code === 2 && /not answering/.test(r.err) && /restarting after an update/.test(r.err),
           `a controller that does not answer refuses every call until it is back (${r.code})`);
        r = gate({});
        ok(r.code === 0, '...and answers again the moment it does, with no wait: a refusal is never cached');
        // A controller that answers with a refusal is up. A session idle past
        // its token's twelve hours is refused "not signed in", and the gate
        // used to read any error without "HTTP" in it as no connection at all,
        // so it told that session BuilderBot was restarting after an update.
        fresh();
        rmSync(`${cache}/builderbot/u/_none/project/alpha/token`, { force: true });
        r = gate({ BB_TOKEN: 'bbs_bm90LWEtcmVhbC10b2tlbg' });
        ok(r.code === 0 && !/not answering/.test(r.err),
           `a token the controller refuses is not a controller that is down (${r.code}: ${r.err.slice(0, 50)})`);
        // A controller address typed by hand without its scheme parses with
        // no host at all, and every bb verb died on a TypeError traceback
        // (B179). It is an answer now, naming the setting.
        {
          const said = execFileSync('python3', ['-c', 'import sys; sys.path.insert(0, sys.argv[1]); import bbapi, json; print(json.dumps(bbapi.call("/api/status")))',
            `${REPO}/scripts/lib`], { encoding: 'utf8', env: { ...process.env, BB_CONTROLLER: 'controller.lan:7680' } });
          ok(/BB_CONTROLLER 'controller.lan:7680' is not an address/.test(said),
             `a controller address with no scheme is an error naming the setting, not a traceback (${said.trim().slice(0, 70)})`);
        }
        // --prompt is kept as a no-op: the hook line naming it is written
        // into settings files that outlive this change, so it has to stay
        // callable and has to say nothing.
        const said = execFileSync('python3', [`${REPO}/scripts/dashboard/bb-gate`, '--prompt', 'alpha', 'x'],
          { input: '{"prompt":"go"}', encoding: 'utf8', env: genv({}), stdio: ['pipe', 'pipe', 'pipe'] });
        ok(said.trim() === '',
           `the prompt hook is silent: there is no copy of the briefing left to be behind (${said.trim().slice(0, 40) || 'nothing'})`);
      }
      // bb itself in the node role: a relayed verb is the controller's
      // answer and nothing else; the dispatch used to fall through and run
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
      // ...and a relayed verb that the controller REFUSED exits non-zero, so
      // a script, a hook or a session's `&&` can tell a refusal from a run.
      // The dispatch reads `exit $rc` rather than `exit 0`: it was the second
      // for a long time and still propagated, because bb runs under set -e
      // and the failing relay aborted before reaching it. Pinned here because
      // that is an accident to rely on, and B154 is the report that it might
      // not hold.
      const refused = bbOnNode(['roadmap', 'done', '99999']);
      ok(/^FAILED 1:/.test(refused) && /no item R99999 on this list/.test(refused),
         `a relayed verb the controller refused exits non-zero (${
           refused.replace(/\s+/g, ' ').slice(0, 60)})`);
      const num = (once.match(/added R(\d+)/) || [])[1];
      bbOnNode(['roadmap', 'rm', String(num), 'test']);
      // bb git: git's network half from a node runs on the controller, with
      // the keys that live only there (docs/nodes.md §20, rule 2), in a
      // repository of the controller's own (B148). The fixture's origin is
      // an ssh address nobody holds a key for, so git itself answers, which
      // is the proof that git ran there and not on the "node".
      const ls = bbOnNode(['git', 'ls-remote', 'origin']);
      ok(/fatal:/.test(ls) && !/not relayed|not accepted/.test(ls),
         `bb git ls-remote from a node reaches the controller's git (${ls.replace(/\s+/g, ' ').slice(0, 70)})`);
      const exec = bbOnNode(['git', 'push', '--upload-pack=/bin/sh', 'origin']);
      const conf = bbOnNode(['git', 'fetch', '-c', 'core.sshCommand=id']);
      const other = bbOnNode(['git', 'status']);
      ok(/not accepted/.test(exec) && /not accepted/.test(conf) && /takes push, fetch/.test(other),
         `...and an option that would run a program on the controller, or a verb that is not the network half, is refused before git sees it (${
           [exec, conf, other].map(x => x.replace(/\s+/g, ' ').slice(0, 60)).join(' | ')})`);
      // A rule's check is a command a session may write, so it runs on the
      // machine the session is on and never on the controller (B152). The
      // controller's relayed run carries BB_RELAYED; a local one does not.
      bbOnNode(['rules', 'add', 'relayprobe', 'where a check runs', '--check', 'echo relayed=${BB_RELAYED:-no}']);
      // Run from a BUNDLE-SHAPED copy, not from the checkout: bb beside its
      // library and NO dashboard modules, which is what a node actually has
      // (workspace.BUNDLE_PARTS ships bb, lib and the hooks, and deliberately
      // not the notebook modules, because a node has no /config for them to
      // read). Run from the checkout this passed while `bb rules check` was
      // dead on every real node, because cmd_rules demanded rules.py at its
      // top for verbs that need it and `check` does not: it takes the rules
      // through `bb rules --json`, which a node relays.
      const nb = `${DIR}/nodebundle`;
      rmSync(nb, { recursive: true, force: true });
      mkdirSync(`${nb}/scripts/dashboard`, { recursive: true });
      copyFileSync(`${REPO}/scripts/bb`, `${nb}/scripts/bb`);
      cpSync(`${REPO}/scripts/lib`, `${nb}/scripts/lib`, { recursive: true });
      ok(!existsSync(`${nb}/scripts/dashboard/rules.py`),
         'the bundle a node runs bb from carries no dashboard module, as BUNDLE_PARTS ships it');
      // WORKSPACE as a node has it: the check runs in the project's tree.
      let checked;
      try {
        checked = execFileSync('bash', [`${nb}/scripts/bb`, 'rules', 'check', 'relayprobe'],
          { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: { ...nodeEnv, BB_PROJECT: 'alpha', WORKSPACE: `${DIR}/ws` },
            stdio: ['ignore', 'pipe', 'pipe'] });
      } catch (e) { checked = `FAILED ${e.status}: ${e.stdout}${e.stderr}`; }
      bbOnNode(['rules', 'rm', 'relayprobe', 'test']);
      const sent = await (await fetch(URL.replace(/\/$/, '') + '/api/v1/bb', { method: 'POST',
        headers: { Authorization: 'Bearer ' + forMe, 'Content-Type': 'application/json' },
        body: JSON.stringify({ argv: ['rules', 'check', '--all'], cwd: `${DIR}/ws/alpha` }) })).json();
      ok(/relayed=no/.test(checked) && /runs on the machine the session is on/.test(sent.error || ''),
         `bb rules check on a node runs the rule's command there, and the controller refuses one relayed to it (${
           checked.replace(/\s+/g, ' ').slice(0, 120)} | ${(sent.error || '').slice(0, 50)})`);
      // The identity a node session adopts is the controller's, through the
      // same settings answer bb-tty reads.
      const st = JSON.parse(bbOnNode(['settings', '--json']));
      ok('git_email' in st && 'git_name' in st,
         `bb settings carries the commit identity for a node's session to adopt (${st.git_name || '(none)'} <${st.git_email || '(none)'}>)`);
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
         'the first prompt of a session is told nothing: it was handed the whole list a moment ago');
      await api('/api/roadmap', { project: 'alpha', action: 'add', text: 'something the operator added' });
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
      // ---- the house rules reach a session on a node (B686, R200) -------
      // The note's answer and the prompt's seen carry the named rules the
      // controller's store fires, the hooks remember what this conversation
      // was told so a summary can say it again, and the Bash guard refuses
      // with the controller's list. It used to be silent on a node, which
      // is every session.
      {
        const rcache = `${DIR}/rulecache`; mkdirSync(rcache, { recursive: true });
        const renv = { ...nodeEnv, XDG_CACHE_HOME: rcache };
        const rhook = (name, args, input) => execFileSync('python3', [`${REPO}/scripts/dashboard/${name}`, ...args],
          { input: JSON.stringify(input), encoding: 'utf8', env: renv, stdio: ['pipe', 'pipe', 'pipe'] });
        let kept = null;
        try { kept = readFileSync(`${DIR}/state/rules.json`, 'utf8'); } catch { /* none yet */ }
        const was = (await api('/api/rules', { project: 'alpha', action: 'save', rules: [
          { name: 'zebra', text: 'ZEBRARULE keep the stripes', paths: ['src/striped'], words: ['zebrafish'] }] }));
        const noted = rhook('bb-work-note', ['alpha', 'ignored'],
          { session_id: 'conv-node', tool_input: { file_path: '/workspace/alpha/src/striped/a.py', old_string: 'x' } });
        const asked2 = rhook('bb-prompt-relay', ['alpha', 'ignored'], { session_id: 'conv-node-2', prompt: 'the zebrafish again' });
        const twice = rhook('bb-prompt-relay', ['alpha', 'ignored'], { session_id: 'conv-node-2', prompt: 'and the zebrafish once more' });
        ok(/ZEBRARULE/.test(noted) && /ZEBRARULE/.test(asked2) && !/ZEBRARULE/.test(twice) && !was.error,
           `a named rule reaches a session on a node, on the edit of a file it covers and on a prompt naming its word, once a conversation (${
             noted.slice(0, 80)} | ${asked2.trim().slice(0, 80)})`);
        const again = rhook('bb-rule-hook', ['recall', 'alpha', 'ignored'], { source: 'compact', session_id: 'conv-node' });
        ok(/summarized/.test(again) && /ZEBRARULE/.test(again)
           && rhook('bb-rule-hook', ['recall', 'alpha', 'ignored'], { source: 'compact', session_id: 'conv-other' }) === '',
           '...and after a summary the conversation that was told it is told again, and no other');
        const denied = rhook('bb-rule-hook', ['guard', 'alpha', 'ignored'],
          { tool_name: 'Bash', tool_input: { command: 'sleep 1; pkill -f chromium' } });
        ok(/"permissionDecision": "deny"/.test(denied) && /pkill-by-pid/.test(denied)
           && rhook('bb-rule-hook', ['guard', 'alpha', 'ignored'], { tool_name: 'Bash', tool_input: { command: 'ls -la' } }) === '',
           `the Bash guard on a node refuses what the controller's list refuses, with the reason, and lets the rest run (${denied.slice(0, 90)})`);
        if (kept === null) rmSync(`${DIR}/state/rules.json`, { force: true });
        else writeFileSync(`${DIR}/state/rules.json`, kept);
      }
      const bad = await fetch(URL.replace(/\/$/, '') + '/api/v1/hook', { method: 'POST',
        headers: { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'asked', text: 'hi' }) });
      ok(bad.status === 403, 'a token for the project alone, with no account, may not post as anybody');
    }

    // ---- the node's sessions are on the Sessions card (roadmap #24) --------
    // The agent's heartbeat carries the session account's tmux sessions;
    // the controller lists them beside its own, named by ITS rule (the
    // owner's bare, everybody else's prefixed), each saying which node it
    // is on; and ending one goes back to the agent through its held poll.
    // The agent here is this user, so its tmux is the harness's private
    // server. That is also the controller's, so the same session shows
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
    // reading the pane's start command rather than composing a path: on a
    // node the file is in the home of whichever account owns the session,
    // and tmux already knows which.
    {
      // beta rather than alpha: the block above ends claude-alpha through
      // the agent, and a name just killed is held off the list until the
      // node's own heartbeat confirms it, which would read here as the
      // session not being listed at all.
      const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
      const real = `${uid}~claude-beta`;
      const launcher = `${DIR}/home/.cache/builderbot/project/beta/claude-run.sh`;
      mkdirSync(`${DIR}/home/.cache/builderbot/project/beta`, { recursive: true });
      writeFileSync(launcher, `#!/usr/bin/env bash\nexec sleep 600\n`, { mode: 0o755 });
      tmuxKill(real); tmuxKill('claude-beta');
      tmuxNew(real, `${DIR}/ws/beta`, [launcher]);
      const back = await until(async () =>
        ((await api('/api/status')).sessions || []).find(
          s => s.node === 'agentbox' && s.name === 'claude-beta'), 45000, 500);
      ok(!!back, 'a session started on its launcher is listed on the node');
      // Saving a setting with the box ticked ENDS the session rather than
      // respawning the pane under it (the operator's call, 12 Sep): the
      // change lands when the Claude button starts one, which resumes the
      // conversation, instead of arriving in a tab nobody is looking at.
      const r = await api('/api/prefs', { project: 'beta', restart: true });
      ok(r.ended === true && r.on_node === 'agentbox',
         `saving with the box ticked finds the session on the node rather than reporting none (${
           JSON.stringify(r)})`);
      const gone = await until(async () =>
        ((await api('/api/status')).sessions || []).every(
          s => !(s.node === 'agentbox' && s.name === 'claude-beta')) ? true : null,
        30000, 500);
      ok(gone === true, '...and the session on the node is gone, not restarted under itself');
      tmuxKill(real);
    }
    // Whatever the pane is running. The respawn this replaced would have put
    // the LAUNCHER into a pane running something else, so it checked first;
    // ending a session named for the project needs no such guard, and the
    // path it takes is the Sessions card's kill, which never had one.
    {
      const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
      const real = `${uid}~claude-gamma`;
      tmuxKill(real);
      tmuxNew(real, `${DIR}/ws/gamma`, ['bash', '--norc', '--noprofile']);
      await until(async () =>
        ((await api('/api/status')).sessions || []).find(
          s => s.node === 'agentbox' && s.name === 'claude-gamma'), 45000, 500);
      const r = await api('/api/prefs', { project: 'gamma', restart: true });
      ok(r.ended === true, `...whatever the pane happens to be running (${JSON.stringify(r)})`);
      tmuxKill(real);
    }

    const outside = await relay({ argv: ['version'], cwd: '/etc' });
    ok(outside.status === 200 && outside.code === 0 && !/etc/.test(outside.out),
       'a cwd outside the project\'s trees is ignored: the verb runs in the project directory');
    // The verbs bb relays and the verbs the server accepts are one contract
    // in one file, lib/relay-verbs, and this is what keeps both reading it.
    const verbs = readFileSync(`${REPO}/scripts/lib/relay-verbs`, 'utf8').split(/\s+/).filter(Boolean);
    ok(verbs.includes('roadmap') && verbs.includes('git')
       && /lib\/relay-verbs/.test(readFileSync(`${REPO}/scripts/bb`, 'utf8'))
       && /"lib" \/ "relay-verbs"/.test(readFileSync(`${REPO}/scripts/dashboard/bbrelay.py`, 'utf8')),
       `bb and the server read the relay verbs from one file (${verbs.length} verbs)`);
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
    ok(forced.ok, 'a job requiring something the node lacks is queued; the row does not check');
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
    // system path is refused before anybody presses Apply, and again on the
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
                         { type: 'virtiofs', source: 'projects', path: '/srv/projects', ro: true }],
                stores: { cache: `${DIR}/agentcache`, toolchains: `${DIR}/agenttoolchains`,
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
       && /add-share projects:\/srv\/projects:ro/.test(fin.log) && /cache store/.test(fin.log),
       `the agent applies it through bb-sandbox and the stores, logging each step (${fin?.state})`);
    const stubState = JSON.parse(readFileSync(SANDBOX_STATE, 'utf8'));
    ok(stubState.length === 2 && stubState.some(m => m.path === '/srv/projects' && m.ro),
       '...and the node now has both mounts, the read-only one read-only');
    const after = await until(async () => {
      const n = await nodeById(minted.id);
      return n.reported.mounts.length === 2 ? n : null;
    });
    ok(after !== null && after.reported.mounts.every(m => m.mounted)
       && after.reported.stores.cache.path === `${DIR}/agentcache`,
       'the census reports the applied mounts and the moved store right away, not at the next hello');
    ok(after && after.applying === null, '...and the row is no longer applying');
    // A reboot from the row is root's: this agent runs as an account, so it
    // refuses and names the command, and nothing here reboots the box. Not
    // asked of an agent that IS root, since that one would do it.
    if (process.getuid && process.getuid() !== 0){
      const pw = await api('/api/v1/nodes', { action: 'reboot', id: minted.id });
      ok(pw.ok && /^j_/.test(pw.job), `reboot queues a system job (${pw.job || pw.error})`);
      const fin = await until(async () => {
        const r = await api(`/api/v1/jobs?id=${pw.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 30000);
      ok(fin?.state === 'failed' && /refused: a reboot is root's/.test(fin.log || '') && /sudo reboot/.test(fin.log || ''),
         `...which an agent that is not root refuses, naming the command (${fin?.state}: ${(fin?.log || '').trim().slice(0, 80)})`);
    }
    // The NVIDIA driver row (R102), end to end with the real agent: the
    // census reads the card, where its driver stands and what apt offers;
    // a branch picked on the row is a name of the toolchain job, which the
    // agent runs as bb-sandbox gpu-driver install PACKAGE; the hello after
    // it says the driver is installed and waiting for a restart; another
    // branch is then refused until this one is removed; and a check reads
    // apt's lists again on the node. The waits are long: each state arrives
    // with a census, which under a whole run's load took more than 40 s.
    {
      const drv = async () => ((await api(`/api/toolchains?node=${minted.id}`)).machine || [])[0];
      const job = async id => until(async () => {
        const r = await api(`/api/v1/jobs?id=${id}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 120000);
      const first = await until(async () => { const x = await drv(); return x?.state && x.state !== 'unknown' && x.options?.length ? x : null; }, 120000);
      ok(first?.state === 'absent' && first.managed && /10de:2482/.test(first.card) && first.bound === 'nouveau' && !first.here,
         `the agent reports the card and no driver on it, nouveau holding it (${first?.state}, ${first?.bound})`);
      ok(first?.options.map(o => o.pkg).join(',') === 'nvidia-driver-610,nvidia-driver-595' && first.recommended === 'nvidia-driver-595',
         `...with the branches apt offers, newest first, the transitional one left out, and the recommended one (${first?.options.map(o => o.pkg + ' ' + o.version).join(', ')}; ${first?.recommended})`);
      const nodisp = await api('/api/v1/nodes', { action: 'gpu-display', id: minted.id });
      ok(/install it on that node's Toolchains tab first/.test(nodisp.error || ''),
         `the display is not set up on a machine with no driver: it installs none itself (${nodisp.error})`);
      const q = await api('/api/toolchains', { action: 'install', names: ['nvidia-driver'], driver: 'nvidia-driver-610', node: minted.id });
      ok(q.ok && /^j_/.test(q.job || ''), `a branch picked on the row queues a toolchain job (${q.job || q.error})`);
      const fin = await job(q.job);
      ok(fin?.type === 'toolchain' && fin.state === 'succeeded' && /gpu-driver install nvidia-driver-610: done/.test(fin.log || ''),
         `...which the agent runs as bb-sandbox gpu-driver install nvidia-driver-610 (${fin?.state}: ${(fin?.log || '').trim().slice(-70)})`);
      const after = await until(async () => { const x = await drv(); return x?.state === 'waiting' ? x : null; }, 120000);
      ok(after?.installed === '610.57.04' && after.package === 'nvidia-driver-610' && after.here && !after.newer,
         `...and the hello after it says installed, waiting for a restart (${after?.state} ${after?.installed} ${after?.package})`);
      const other = await api('/api/toolchains', { action: 'install', names: ['nvidia-driver'], driver: 'nvidia-driver-595', node: minted.id });
      ok(/nvidia-driver-610 is installed.*remove it first/.test(other.error || ''), `another branch waits for this one to be removed (${other.error})`);
      // The display, now that the driver is on the machine (it was refused
      // before, above): set up below as its own system job.
      // The GPU display (R20): a system job the agent answers with bb-sandbox
      // gpu, whose words are the job's, and whose state line the next hello
      // carries into the census, so the row says what the machine found.
      {
        const g = await api('/api/v1/nodes', { action: 'gpu-display', id: minted.id });
        ok(g.ok && /^j_/.test(g.job), `Set up GPU display queues a system job on a sandbox node (${g.job || g.error})`);
        const fin = await until(async () => {
          const r = await api(`/api/v1/jobs?id=${g.job}`);
          return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
        }, 30000);
        ok(fin?.state === 'succeeded' && /takes the card at the next boot/.test(fin.log || ''),
           `...bb-sandbox gpu runs and its words are the job's (${fin?.state}: ${(fin?.log || '').trim().slice(-70)})`);
        const told = await until(async () => {
          const n = await nodeById(minted.id);
          return /^reboot/.test(n.reported?.gpu_display || '') ? n : null;
        }, 30000);
        ok(told !== null, `...and the display's state line reaches the row with the hello that follows (${told?.reported?.gpu_display})`);
      }
      // ...and taken off again: bb-sandbox gpu-off, whose state line says
      // it was switched off, which the row then reads.
      {
        const o = await api('/api/v1/nodes', { action: 'gpu-display', id: minted.id, on: false });
        const of = o.ok ? await job(o.job) : null;
        const told = await until(async () => { const n = await nodeById(minted.id); return /^off/.test(n.reported?.gpu_display || '') ? n : null; }, 30000);
        ok(of?.state === 'succeeded' && /gpu-off/.test(of.log || '') && told !== null,
           `the emulator is taken off the card by bb-sandbox gpu-off, and the row reads it as switched off (${o.error || of?.state}; ${told?.reported?.gpu_display})`);
      }
      // The container toolkit, the machine's second row, end to end: the
      // census says it is not there and that the driver it needs is; its
      // install is a name of the toolchain job, run as bb-sandbox
      // gpu-container install; and the hello after it says installed, with
      // Docker listing the runtime.
      const KIT = 'nvidia-container-toolkit';
      const kit = async () => ((await api(`/api/toolchains?node=${minted.id}`)).machine || []).find(m => m.name === KIT);
      {
        const k0 = await until(async () => { const x = await kit(); return x?.state === 'absent' && x.driver ? x : null; }, 120000);
        ok(k0 !== null && k0.managed && !k0.here, `the agent reports no container toolkit beside the driver (${k0?.state})`);
        const kq = await api('/api/toolchains', { action: 'install', names: [KIT], node: minted.id });
        const kf = kq.ok ? await job(kq.job) : null;
        ok(kf?.state === 'succeeded' && /== bb-sandbox gpu-container install/.test(kf.log || '') && /gpu-container install: done/.test(kf.log || ''),
           `its install is a toolchain job the agent runs as bb-sandbox gpu-container install (${kq.error || kf?.state}: ${(kf?.log || '').trim().slice(-60)})`);
        const k1 = await until(async () => { const x = await kit(); return x?.state === 'ready' ? x : null; }, 120000);
        ok(k1?.installed === '1.17.8-1' && k1.here && !k1.newer,
           `...and the hello after it says installed, with Docker listing the runtime (${k1?.state} ${k1?.installed})`);
      }
      const ck = await api('/api/toolchains', { action: 'check', names: ['zig'], node: minted.id });
      const ckf = ck.ok ? await job(ck.job) : null;
      ok(/bb-sandbox gpu-driver refresh/.test(ckf?.log || '') && /reading the package lists again/.test(ckf?.log || ''),
         `Check for updates reads apt's lists again on the node (${ck.error || ckf?.state})`);
      const rm = await api('/api/toolchains', { action: 'remove', names: ['nvidia-driver', KIT], node: minted.id });
      const rmf = rm.ok ? await job(rm.job) : null;
      const gone = await until(async () => { const x = await drv(); return x?.state === 'absent' ? x : null; }, 120000);
      ok(rmf?.state === 'succeeded' && /gpu-driver remove: done/.test(rmf.log || '') && gone !== null,
         `Remove takes it off again, and the row reads not installed (${rm.error || rmf?.state}, ${gone?.state})`);
      const kgone = await until(async () => { const x = await kit(); return x?.state === 'absent' ? x : null; }, 120000);
      ok(/gpu-container remove: done[\s\S]*gpu-driver remove: done/.test(rmf?.log || '') && kgone !== null,
         `removed together, the toolkit comes off before the driver it needs (${kgone?.state})`);
      rmSync(`${DIR}/nv-installed`, { force: true });
      rmSync(`${DIR}/ctk-installed`, { force: true });
    }

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
                    toolchains: `${DIR}/fakeshare/toolchains`, artifacts: `${DIR}/agentartifacts` },
                  network: { mode: 'dhcp' } } });
      const j = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      const r = await until(async () => {
        const x = await api(`/api/v1/jobs?id=${j.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 30000);
      ok(r && r.state === 'failed' && /is NOT mounted/.test(r.log) && /own disk/.test(r.log),
         `a store inside a configured share that is not mounted is refused, and says why (${r?.state})`);
      ok(!existsSync(`${DIR}/fakeshare/toolchains`),
         '...and nothing was created there, so no data can land on the local disk by mistake');
      const n2 = await nodeById(minted.id);
      ok(n2.reported.stores.toolchains.path === `${DIR}/agenttoolchains`,
         '...and the toolchain store still points where it did');
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
                  stores: { cache: `${DIR}/agentcache2`, toolchains: `${DIR}/agenttoolchains2`,
                            artifacts: `${DIR}/agentartifacts` },
                  network: { mode: 'dhcp' } } });
      const j = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      const r = await until(async () => {
        const x = await api(`/api/v1/jobs?id=${j.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 60000);
      ok(r && r.state === 'succeeded'
         && readFileSync(`${DIR}/agenttoolchains2/${SCOPE}/android/marker`, 'utf8') === 'a toolchain lives here',
         `moving a store copies what was in it to the new place (${r?.state})`);
      ok(existsSync(`${PK}/android/marker`) && /left in place/.test(r.log),
         '...and never deletes the source, so a half-finished move still serves');
      ok(/agenttoolchains stays \(Directory not empty\)/.test(r.log) && /remove it yourself/.test(r.log),
         '...so the old directory is not tidied away either, and the log says which one holds it');
      ok(!existsSync(`${DIR}/agentcache2/gradle-blob`) && /a cache is rebuildable/.test(r.log),
         '...while the cache is left behind rather than copied, and the log says why');
      // The copy does not demand ownership it cannot set. A share exported
      // all_squash (which is what the projects and SDK shares here ARE)
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
        return n.reported.stores.toolchains.path === `${DIR}/agenttoolchains2` ? n : null;
      });
      ok(n2 !== null, '...and the census reports the store where it now is');
      // ---- and the empty directories it made ARE taken back ---------------
      // Only the ones it created, only when they are empty. A store
      // configured and never written to otherwise leaves a tree nobody
      // wants, and there is no telling ours from the operator's afterwards,
      // so it is recorded at the moment of creation.
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
      // in, so on a machine where that store had any (which is every node,
      // and not the controller) `art` was not empty and the agent said so,
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
                           { type: 'virtiofs', source: 'projects', path: '/srv/projects', ro: true }],
                  stores: { cache: `${DIR}/agentcache`, toolchains: `${DIR}/agenttoolchains`,
                            artifacts: `${DIR}/agentartifacts` },
                  network: { mode: 'static', address: '10.9.9.9/24', gateway: '10.9.9.1', dns: ['10.9.9.1'] } } });
      const back = await api('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
      await until(async () => {
        const x = await api(`/api/v1/jobs?id=${back.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(x.state) ? x : null;
      }, 60000);
    }

    // network: written, applied, dialed back, with the stub controller still here
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
    ok(/has no node/.test(nonode.error || '') && /notebook Settings/.test(nonode.error || '')
       && /Reading and editing the code needs no node/.test(nonode.error || ''),
       `a project with no node set is refused, and told where to set one (${JSON.stringify(nonode).slice(0, 160)})`);
    const onlocal = await api('/api/v1/jobs', { action: 'run', project: 'alpha', node: 'local', argv: ['true'] });
    ok(/runs no agent/.test(onlocal.error || ''), 'local is not a build node: it has no workspace of its own');
    const pr = await api('/api/prefs', { project: 'alpha', node: minted.id,
      build: 'cat hello.txt && mkdir -p out && echo built > out/app-1.0.apk', outputs: ['out/*.apk'] });
    ok(pr.ok && pr.node === minted.id && /hello/.test(pr.build),
       'the project record takes a build node, a build command and its outputs');

    // ---- the terminal goes to the node (roadmap #24, phase 10b) --------------
    // alpha is bound to agentbox now, whose census says its session half is
    // up, and whose agent makes alpha's synced copy in its own /workspace
    // (R163): once it says the copy is ready, the controller's /term proxy
    // dials agentbox's ttyd (the stub above, which answers with the request
    // line) with the account, its name and a session token stamped into
    // the URL.
    {
      const copied = await until(async () => {
        const p = (await api('/api/status')).projects.find(x => x.name === 'alpha');
        return p?.session_at === 'agentbox' && p?.session_why === '' ? p : null;
      }, 60000);
      ok(copied && existsSync(`${SHARE}/alpha`),
         `the node's agent copies the project it is bound to into its own /workspace, and the button goes live once it has (${
           copied ? 'ready' : ((await api('/api/status')).projects.find(x => x.name === 'alpha')?.session_why || '').slice(0, 80)})`);
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
         'a transcript written on the share, as a node\'s session writes it, is offered here to resume');
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
         `a Claude session on alpha is relayed to agentbox's ttyd (${c.status}: ${c.body.slice(0, 400)})`);
      const args = (c.body.match(/arg=[^& ]+/g) || []).map(x => decodeURIComponent(x.slice(4)));
      ok(args[0] === `u:${uid}:claude:alpha`,
         `...with the account stamped into the argument as it is locally (${args[0]})`);
      ok(/^tok:bbs_[A-Za-z0-9_-]+$/.test(args[1] || '') && args[2] === 'name:test' && args[3] === 'owner:1',
         `...and the node's extras after it: a session token, the account's name, and that it is the owner, so the tree and the transcript slug are the same there (${args.slice(1).map(x => x.slice(0, 12)).join(', ')})`);
      const sh = await term('shell:alpha');
      ok(sh.status === 200 && /arg=u%3A/.test(sh.body) && /tok%3Abbs_/.test(sh.body),
         'a project shell goes there too, with the account and a token, so bb in that shell reaches the notebook with it');
      const root = await term('shell');
      ok(root.status === 502 && /terminal server is not running/.test(root.body),
         'the workspace shell stays on this container (which the harness runs no ttyd for)');
      // A Claude session runs on a node and nowhere else (R47): this
      // container carries no Claude Code, so a project with no node is
      // refused, with the sentence saying what to do rather than opening a
      // conversation that could not build anything.
      const nonode = await term('claude:beta');
      ok(nonode.status === 503 && /no node to run a Claude session on: pick one/.test(nonode.body)
         && /enroll one on the Nodes tab/.test(nonode.body),
         `a project with no node is refused a session, and told why (${
           (nonode.body || '').slice(0, 60)})`);
      // Bound to a node that cannot take one yet: the sandbox's session
      // half is up but it reports no synced copy of the project (R163), so
      // the button waits with the reason and the proxy says the same rather
      // than starting a session on a tree that is not there.
      const sandbox = (await api('/api/v1/nodes')).nodes.find(n => n.name === 'sandbox');
      await api('/api/prefs', { project: 'beta', node: sandbox.id });
      const beta = (await api('/api/status')).projects.find(p => p.name === 'beta');
      ok(beta?.session_at === 'sandbox' && /beta is being copied to sandbox/.test(beta?.session_why || '')
         && /the session starts once the copy is there/.test(beta?.session_why || ''),
         `a project bound to a node that has no copy of it yet carries the reason on its row (${(beta?.session_why || '').slice(0, 60)})`);
      const refused = await term('claude:beta');
      ok(refused.status === 503 && /being copied to sandbox/.test(refused.body),
         '...and one bound to a node that cannot take it yet is refused with that node\'s reason');
      // ...and there is no way to ask for it here. `here=1` was the dead
      // button's escape while this container could still run one; it cannot,
      // so the flag is gone and the same refusal answers whatever is asked.
      const here = await fetch(URL.replace(/\/$/, '') + '/term/ws?arg=' + encodeURIComponent('claude:beta') + '&here=1',
                               { headers: auth, redirect: 'manual' });
      ok(here.status === 503 && /being copied to sandbox/.test(await here.text()),
         '...and asking for it on this container anyway changes nothing');
      // A shell follows the node for the same reason a session does (the
      // tree is that machine's copy), so a node that cannot take one takes
      // neither. That is unchanged; what R47 changed is the NO-node case.
      const shellRefused = await term('shell:beta');
      ok(shellRefused.status === 503 && /being copied to sandbox/.test(shellRefused.body),
         '...and a shell on that project follows the node, so it is refused too');
      await api('/api/prefs', { project: 'beta', node: '' });
      const shellHere = await term('shell:beta');
      ok(shellHere.status === 502 && /terminal server is not running/.test(shellHere.body),
         'a shell on a project with NO node still opens here: only Claude moved');
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
    // B200: a one-second read does not queue behind a long job. This node runs
    // one job at a time, and Test (uname, through the agent) used to wait for
    // that one slot like a build would, time out, and be reported as an agent
    // that "did not report back" on a machine that was healthy and busy.
    {
      const long = await api('/api/v1/jobs', { action: 'run', project: 'alpha', argv: ['sh', '-c', 'sleep 14'] });
      await until(async () => (await api(`/api/v1/jobs?id=${long.job}`)).state === 'running' ? true : null, 20000);
      const t0 = Date.now();
      const probe = await api('/api/v1/nodes', { action: 'test', id: minted.id });
      const took = Date.now() - t0;
      const still = (await api(`/api/v1/jobs?id=${long.job}`)).state;
      ok(still === 'running' && took < 9000 && !probe.error,
         `Test answers beside a job that holds the node's one slot, rather than after it (${took}ms, the long job ${still}: ${
           JSON.stringify(probe).slice(0, 90)})`);
      await api('/api/v1/jobs', { action: 'cancel', id: long.job });
      await until(async () => ['succeeded', 'failed', 'canceled'].includes(
        (await api(`/api/v1/jobs?id=${long.job}`)).state) ? true : null, 20000);
    }
    // The Docker manager's listing, the same way. Its `docker ps` is a read
    // on the node, and the light lane takes it beside a build, so a look
    // during a job is asked of the node and comes back fresh: it used to be
    // the kept listing, marked stale, which on a shared node was most of the
    // time and through every change made from the tab (B664, 11 Oct).
    {
      await api('/api/prefs', { project: 'ep.silon', node: minted.id });
      const first = await api(`/api/docker?node=${minted.id}`);
      const long = await api('/api/v1/jobs', { action: 'run', project: 'alpha', argv: ['sh', '-c', 'sleep 14'] });
      await until(async () => (await api(`/api/v1/jobs?id=${long.job}`)).state === 'running' ? true : null, 20000);
      const t0 = Date.now();
      const again = await api(`/api/docker?node=${minted.id}`);
      const took = Date.now() - t0;
      const still = (await api(`/api/v1/jobs?id=${long.job}`)).state;
      ok(!first.error && !again.error && !again.stale && took < 9000 && still === 'running',
         `the Docker manager's listing during a job is asked of the node, fresh and not marked stale (${took}ms, stale ${
           again.stale}, first ${first.error || 'ok'}, the job ${still})`);
      await api('/api/v1/jobs', { action: 'cancel', id: long.job });
      await until(async () => ['succeeded', 'failed', 'canceled'].includes(
        (await api(`/api/v1/jobs?id=${long.job}`)).state) ? true : null, 20000);
      const fresh = await api(`/api/docker?node=${minted.id}`);
      ok(!fresh.error && !fresh.stale, `...and the look after the job ends is a fresh read (stale ${fresh.stale})`);
    }
    // Bug #45: a plain exec, which is what bb build, bb test and bb run
    // submit, got a bare PATH, because the node's SDK environment was only
    // applied in the bb-verb branch. Measured on a real node: java and go
    // NOT-ON-PATH, JAVA_HOME unset, on a node whose census reported both.
    {
      mkdirSync(`${PK}/jdk/bin`, { recursive: true });
      mkdirSync(`${PK}/go/bin`, { recursive: true });
      // An android system image in the node's own store, and an AVD in the
      // data store built on it (roadmap #20). The agent walks for these
      // rather than running `bb emu images`, which is the same listing plus
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
      ok(/root=.*agenttoolchains/.test(log) && /java=.*agenttoolchains\/n_[0-9a-f]+\/jdk/.test(log)
         && /android=.*agenttoolchains\/n_[0-9a-f]+\/android/.test(log),
         `a build job gets the node's toolchain store root, JAVA_HOME and ANDROID_HOME (${
           (log.match(/root=.*/) || [''])[0].slice(0, 60)})`);
      ok(/cilog=.*agentdata\/ci-logs/.test(log),
         '...and where this node archives CI logs, under the data store both accounts can read');
      // An empty directory is not a toolchain. cmdline-tools existed on the
      // operator's node as an empty folder with no sdkmanager, and
      // platform-tools not at all, and the census called android-sdk present,
      // so a job needing adb was admitted and failed there rather than
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
      // ...and neither is a binary that is there and cannot START. The
      // version probe read stdout-or-stderr and dropped the status, so a
      // toolchain that aborted on launch was read as one that printed
      // something odd and went on the row as "present", which is how
      // bb-sandbox-redhat advertised .NET while dumping core every ten
      // minutes. A tool that dies is not a tool this node has.
      {
        mkdirSync(`${PK}/swift/usr/bin`, { recursive: true });
        // Two lines, in .NET's own shape: the reason is on the SECOND one,
        // which is what the log has to reach. Logging the first line alone
        // carried "Process terminated." and dropped the answer.
        writeFileSync(`${PK}/swift/usr/bin/swift`,
          '#!/bin/sh\necho "Process terminated." >&2\n'
          + 'echo "Couldn\'t find a valid ICU package installed on the system." >&2\n'
          + 'kill -ABRT $$\n',
          { mode: 0o755 });
        // rust's shape beside it, which must NOT change: a non-zero exit
        // with a sentence means installed and awkward, and that is what
        // "present" is for.
        mkdirSync(`${PK}/rust/cargo/bin`, { recursive: true });
        writeFileSync(`${PK}/rust/cargo/bin/cargo`,
          '#!/bin/sh\necho "error: rustup could not choose a version" >&2\nexit 1\n',
          { mode: 0o755 });
        // A census rides hello, which is ten minutes apart, so ask for a
        // fresh one the way the controller does when it refuses a job on a
        // stale answer, rather than waiting out the cadence.
        await api('/api/v1/jobs', { action: 'run', project: 'alpha',
                                    argv: ['sh', '-c', 'command -v adb'] });
        const after = await until(async () => {
          const n = await nodeById(minted.id);
          const tc = n?.reported?.toolchains || {};
          return tc.rust ? tc : null;
        }, 60000);
        ok(after && !after.swift,
           `a toolchain that dies when asked its version is left out of the census (${
              JSON.stringify(after?.swift)})`);
        ok(after && after.rust === 'present',
           `...while one that merely exits non-zero with a sentence is still present (${
              JSON.stringify(after?.rust)})`);
        ok(/swift died on signal 6 .*Process terminated\. Couldn't find a valid ICU package/
             .test(agentLog()),
           `...and the log names the binary, how it died and ALL of what it said: the reason is on its second line (${
              (agentLog().split('\n').find(l => /died on signal/.test(l)) || 'nothing said').slice(-90)})`);
        rmSync(`${PK}/swift`, { recursive: true, force: true });
        rmSync(`${PK}/rust`, { recursive: true, force: true });
      }
      // ...and a job refused on that answer says how old the answer is, and
      // asks the node for a fresh one. The census rides hello every ten
      // minutes, so a refusal can be reasoning about the node as it was nine
      // of them ago. The operator met exactly that: a command refused, the
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
      ok(/path=[^\n]*agenttoolchains\/n_[0-9a-f]+\/jdk\/bin/.test(log)
         && /path=[^\n]*agenttoolchains\/n_[0-9a-f]+\/go\/bin/.test(log),
         '...and every toolchain the store holds is on its PATH, not just the JDK');
      // ...composed from the catalog's layout, sent at hello, rather than
      // from a table in the agent that has to agree with three others.
      const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
      ok(Array.isArray(st.layout) && st.layout.some(e => e.name === 'jdk' && e.tool === 'bin/java')
         && st.layout.some(e => e.name === 'node' && (e.bin || []).includes('bin')),
         `the controller tells the node where toolchains land, and it keeps it (${
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
      // is this container's: java and node are here, flutter is not.
      const gap = await api('/api/v1/jobs', { action: 'run', project: 'alpha',
        argv: ['sh', '-c', 'flutter build apk'] });
      // alpha can push in the fixtures, so the refusal names CI as the way
      // out; the no-push-rights branch says so instead.
      ok(/has no flutter/.test(gap.error || '') && /Toolchains tab/.test(gap.error || '')
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
    // On a node, bb run with no --node (or its own name) runs right here;
    // naming ANOTHER node used to be dropped without a word and run here
    // too, printing this machine's answer to a question about that one.
    {
      const onNode = { ...env, BUILDERBOT_ROLE: 'node', BB_NODE: 'agentbox', BB_CONTROLLER: URL.replace(/\/$/, '') };
      const here = execFileSync('bash', [`${REPO}/scripts/bb`, 'run', '--', 'sh', '-c', 'echo ran on this node'],
        { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: onNode, stdio: 'pipe' });
      let other = '';
      try { other = execFileSync('bash', [`${REPO}/scripts/bb`, 'run', '--node', 'elsewhere', '--', 'sh', '-c', 'echo ran on this node'],
        { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: onNode, stdio: 'pipe' }); }
      catch (e) { other = String(e.stdout) + String(e.stderr); }
      ok(/ran on this node/.test(here) && !/ran on this node/.test(other) && /no node called elsewhere/.test(other),
         `on a node, bb run runs here, and --node naming another machine goes to the controller instead of running here (${other.trim().split('\n').pop().slice(0, 90)})`);
      // ...and bb build there puts what the outputs name into dist/ under
      // the project and its version, the name the briefing asks shipped
      // output to carry, so a session need not copy it by hand (R104).
      // A version needs a repository with a commit, which this fixture's
      // alpha is not: made one for the check and put back after it. Without
      // one the file keeps its own name, which the check below it holds.
      const plain = execFileSync('bash', [`${REPO}/scripts/bb`, 'build'],
        { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: onNode, stdio: 'pipe' });
      ok(/into dist\/: app-1\.0\.apk/.test(plain), 'on a node, a build of a project with no version keeps its file\'s own name');
      const hadGit = existsSync(`${DIR}/ws/alpha/.git`), hadVersion = existsSync(`${DIR}/ws/alpha/VERSION`);
      if (!hadVersion) writeFileSync(`${DIR}/ws/alpha/VERSION`, '1.2.0\n');
      const git = (...a) => execFileSync('git', ['-C', `${DIR}/ws/alpha`, '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', ...a], { stdio: 'pipe' });
      // The fixture's alpha may be a repository with no commit yet, which
      // has no version either: one commit for the check, taken back after.
      if (!hadGit) git('init', '-q');
      let hadHead = true;
      try { git('rev-parse', '-q', '--verify', 'HEAD'); } catch { hadHead = false; }
      if (!hadHead){ git('add', 'VERSION'); git('commit', '-qm', 'v', '--', 'VERSION'); }
      const b = execFileSync('bash', [`${REPO}/scripts/bb`, 'build'],
        { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: onNode, stdio: 'pipe' });
      if (!hadGit) rmSync(`${DIR}/ws/alpha/.git`, { recursive: true, force: true });
      else if (!hadHead){ git('update-ref', '-d', 'HEAD'); git('rm', '-q', '--cached', 'VERSION'); }
      if (!hadVersion) rmSync(`${DIR}/ws/alpha/VERSION`, { force: true });
      rmSync(`${DIR}/ws/alpha/dist/app-1.0.apk`, { force: true });
      const m = /into dist\/: (alpha-[0-9][^\s]*-app-1\.0\.apk)/.exec(b);
      ok(!!m && existsSync(`${DIR}/ws/alpha/dist/${m[1]}`),
         `on a node, bb build names what it puts in dist/ with the project and its version (${m ? m[1] : b.trim().split('\n').pop().slice(0, 90)})`);
      if (m) rmSync(`${DIR}/ws/alpha/dist/${m[1]}`, { force: true });
    }
    const built = execFileSync('bash', [`${REPO}/scripts/bb`, 'build'],
      { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env }).toString();
    ok(/hi from the tree/.test(built) && /into dist\/: app-1.0.apk/.test(built),
       'bb build runs the project\'s build command on its build node and names what came back');
    let failed = '';
    try { execFileSync('bash', [`${REPO}/scripts/bb`, 'test'], { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env, stdio: 'pipe' }); }
    catch (e) { failed = String(e.stderr) + String(e.stdout); }
    ok(/no test command is set/.test(failed) && /bb settings set test/.test(failed),
       'bb test with nothing set refuses, and names the verb that fills the field in');
    // Nothing runs that nobody wrote down: a tree with a go.mod is not a
    // test command, and bb test says so rather than guessing one. The session
    // fills the field in, and from then on it runs.
    writeFileSync(`${DIR}/ws/alpha/go.mod`, 'module alpha\n');
    let still = '';
    try { execFileSync('bash', [`${REPO}/scripts/bb`, 'test'], { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env, stdio: 'pipe' }); }
    catch (e) { still = String(e.stderr) + String(e.stdout); }
    rmSync(`${DIR}/ws/alpha/go.mod`, { force: true });
    ok(/no test command is set/.test(still), 'a go.mod in the tree is not a test command: it still refuses');
    const filled = execFileSync('bash', [`${REPO}/scripts/bb`, 'settings', 'set', 'test', 'echo TEST-SET-RAN'],
      { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env }).toString();
    ok(/set test for alpha: echo TEST-SET-RAN/.test(filled), 'bb settings set test fills the field in under auto');
    const ran = execFileSync('bash', [`${REPO}/scripts/bb`, 'test'], { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env }).toString();
    ok(/TEST-SET-RAN/.test(ran), '...and bb test runs what the session set');
    execFileSync('bash', [`${REPO}/scripts/bb`, 'settings', 'set', 'test', ''], { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env, stdio: 'pipe' });
    const sess = (await api('/api/v1/jobs?project=alpha&n=3')).jobs;
    ok(sess.some(j => j.requested_by === 'session:alpha'), 'a run from a session is attributed to the session');
  }

  // ---- toolchains on a node (phase 6) ----------------------------------------
  // A toolchain install is a job: the bundle (bb, its library, the catalog)
  // travels by digest into the node's toolchain store and runs there. The
  // toolchain asked for is not installed, so this proves the channel and not
  // a download.
  {
    const ttydsBefore = ttydRuns().filter(r => r.env.BUILDERBOT_NODE === minted.id).length;
    const pj = await api('/api/toolchains', { action: 'remove', names: ['flutter'], node: minted.id });
    ok(pj.ok && /^j_/.test(pj.job), `a toolchain job is queued on the node (${pj.job || pj.error})`);
    const pfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${pj.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    // Unpacked by this job, or already there: the session half fetched the
    // same bundle at start (roadmap #24), and a second unpack of the same
    // digest is exactly what the digest is for.
    ok(pfin && pfin.type === 'toolchain'
       && (/bb .* unpacked into .*agenttoolchains\/n_[0-9a-f]+\/\.bb/.test(pfin.log)
           || existsSync(`${PK}/.bb/current/scripts/bb`))
       && /== bb toolchains remove flutter/.test(pfin.log) && /not installed|unknown toolchain/.test(pfin.log),
       `the bundle lands in the toolchain store and bb runs from it there (${pfin?.state}: ${(pfin?.log || '').slice(-500).replace(/\n/g, ' / ')})`);
    ok(existsSync(`${PK}/.bb/bundle.tar`), '...and stays for the next one');
    // The store changed, so the ttyds are started again with an environment
    // built from it, so a session opened now finds the new tool on PATH.
    const renewed = await until(async () => {
      const n = await nodeById(minted.id);
      const now = ttydRuns().filter(r => r.env.BUILDERBOT_NODE === minted.id).length;
      return now > ttydsBefore && n?.reported?.session?.up ? now : null;
    }, 30000, 500);
    ok(renewed !== null, `...and the session ttyds are restarted onto the changed store (${ttydsBefore} -> ${renewed})`);
    // An install that fails on the node says why on its row, as one on the
    // controller does (B211). The reason was only in the job's log before:
    // the row went back to unticked and said nothing, and the graphics
    // recipe's 404 was found with bb jobs rather than on the tab. The
    // fixture node installs everything it is asked for, so the words are
    // proved on the log that install actually left, through the parser the
    // payload uses, and the payload is proved to carry the field.
    {
      const fj = await api('/api/toolchains', { action: 'install', names: ['rust'], node: minted.id });
      ok(fj.ok && /^j_/.test(fj.job), `a toolchain install is queued on the node (${fj.job || fj.error})`);
      await until(async () => {
        const r = await api(`/api/v1/jobs?id=${fj.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 60000);
      // The finished job's view, once nothing on the node is still running:
      // a toolchain job still active there draws the running view instead.
      const tcv = await until(async () => {
        const t = await api(`/api/toolchains?node=${minted.id}`);
        return t.job && !t.job.running && 'errors' in t.job ? t : null;
      }, 30000);
      ok(tcv && typeof tcv.job.errors === 'object',
         `a node's finished toolchain job carries an errors field for the rows (${JSON.stringify(tcv?.job?.errors)})`);
      const log = [
        'toolchain', '== system packages for graphics: fonts-dejavu-core',
        '== bb toolchains install diagrams', '[builderbot] installing diagrams into /mnt/SDK/n_9381e721/diagrams',
        '######################################################################## 100.0%',
        '[builderbot] diagrams ready: new shells pick it up',
        '== bb toolchains install graphics', '[builderbot] installing graphics into /mnt/SDK/n_9381e721/graphics',
        '#=#=#', '##O#-#',
        '##O=#  #                                                   curl: (22) The requested URL returned error: 404',
        '[builderbot] ERROR: could not download https://example.invalid/ImageMagick-gcc-x86_64.AppImage',
        '[builderbot] WARN: install failed (exit 1); removing the partial /mnt/SDK/n_9381e721/graphics',
        '1 of 2 did not install', ''].join('\n');
      const parsed = JSON.parse(execFileSync('python3', ['-c', `
import json, sys, types
sys.path.insert(0, ${JSON.stringify(REPO + 'scripts/dashboard')})
import toolchains as tc
tc.nodes = types.SimpleNamespace(job_tail=lambda jid, n=4000: sys.stdin.read())
print(json.dumps(tc._node_errors("j_x", ["graphics"], "install")))`], { input: log, encoding: 'utf8' }));
      const why = parsed.graphics || '';
      ok(/(^| )curl: \(22\)/.test(why) && /could not download/.test(why) && /exit 1/.test(why)
         && /install failed on the node$/.test(why) && !/diagrams/.test(why) && !/did not install/.test(why)
         && !/#=#|##O/.test(why),
         `...and the reason is that toolchain's own section of the log, with the exit and without the frames (${why.slice(0, 120)})`);
    }
    // The store's own directories decide what is installed there, not the
    // census's placement summary, which named six toolchains and called four
    // installed toolchains missing on the operator's shared toolchain store.
    // With something in each: an empty directory is no toolchain (B674).
    mkdirSync(`${PK}/zig`, { recursive: true });
    writeFileSync(`${PK}/zig/zig`, '');
    mkdirSync(`${PK}/android/ndk/30.0`, { recursive: true });
    // ...except a directory without the file that completes the toolchain:
    // playwright's browsers from before the recipe carried the module.
    mkdirSync(`${PK}/playwright/chromium-1234`, { recursive: true });
    mkdirSync(`${PK}/node/bin`, { recursive: true });   // playwright requires node
    // The store listing rides the census, which refreshes at hello, and a
    // job that touches the node ends in one, which is why installing a
    // toolchain updates this list without waiting ten minutes. Any such job
    // will do here.
    const poke = await api('/api/v1/nodes', { action: 'cache-clear', id: minted.id });
    await until(async () => {
      const r = await api(`/api/v1/jobs?id=${poke.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    const view = await until(async () => {
      const v = await api(`/api/toolchains?node=${minted.id}`);
      return v.items?.some(i => i.name === 'zig' && i.installed) ? v : null;
    }, 30000);
    ok(view && view.node === minted.id && view.root === PK,
       'the Tools tab reads that node\'s own toolchain store');
    ok(view && view.items.find(i => i.name === 'zig')?.installed === true
       && view.items.find(i => i.name === 'android:ndk')?.installed === true,
       'a toolchain present in the store reads as installed, whatever the census summarizes');
    ok(view && view.items.find(i => i.name === 'swift')?.installed === false
       && view.items.every(i => i.unknown === false),
       '...and one that is not there reads as absent, not as unknown');
    ok(view && view.items.find(i => i.name === 'playwright')?.installed === false,
       '...and a playwright directory without its module reads as not installed, so Install is offered (the row said installed and offered nothing)');
    // Check for updates, which is a job on the node rather than a question
    // the controller answers about its own store (R67). Proven end to end
    // because the controller reads the answer out of the job's LOG, which is
    // the one part no unit test can stand in for: the agent runs
    // `bb toolchains check`, bb prints a TSV line per recipe, and the rows
    // on the tab are filled from it.
    {
      const cj = await api('/api/toolchains', { action: 'check', node: minted.id, names: ['zig'] });
      ok(cj.ok && /^j_/.test(cj.job), `a check is queued as a job on the node (${cj.job || cj.error})`);
      const cf = await until(async () => {
        const r = await api(`/api/v1/jobs?id=${cj.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 90000);
      ok(cf && /== bb toolchains check zig/.test(cf.log || ''),
         `...and the agent runs it there (${cf?.state}: ${(cf?.log || '').slice(-160).replace(/\n/g, ' / ')})`);
      const view = await until(async () => {
        const v = await api(`/api/toolchains?node=${minted.id}`);
        return v.checked ? v : null;
      }, 30000);
      ok(view && view.checked > 0,
         `the tab says when this node was last checked (${view?.checked})`);
      const zig = (view?.items || []).find(i => i.name === 'zig');
      ok(zig && (zig.state === 'absent' || zig.state === 'current' || zig.state === 'update'),
         `...and the row carries what the check said (${JSON.stringify(zig && {
           state: zig.state, latest: zig.latest })})`);
    }

    // An Android system image is its own job (the Emulator tab), run as
    // `bb emu image` from the same bundle. sdkmanager is a stub that says
    // what it was asked, so this proves the path and not a download.
    {
      const SM = `${PK}/android/cmdline-tools/latest/bin`;
      mkdirSync(SM, { recursive: true });
      writeFileSync(`${SM}/sdkmanager`, '#!/bin/sh\necho "sdkmanager $*"\n', { mode: 0o755 });
      const poke2 = await api('/api/v1/nodes', { action: 'cache-clear', id: minted.id });
      await until(async () => {
        const r = await api(`/api/v1/jobs?id=${poke2.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 30000);
      const IMG34 = 'system-images;android-34;google_apis;x86_64';
      const em = await until(async () => {
        const v = await api(`/api/emulator?node=${minted.id}`);
        return v.sdkmanager && (v.images || []).some(i => i.id === IMG34) ? v : null;
      }, 30000);
      ok(em && em.images.find(i => i.id === IMG34)?.avds.includes('fbnode'),
         `the Emulator tab reads the node's images and the AVD built on each (${JSON.stringify(em?.images)})`);
      const rj = await api('/api/emulator', { action: 'remove', node: minted.id, image: IMG34 });
      ok(rj.ok && /^j_/.test(rj.job), `removing one queues an image job on the node (${rj.job || rj.error})`);
      const rf = rj.job ? await until(async () => {
        const r = await api(`/api/v1/jobs?id=${rj.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 60000) : null;
      ok(rf && rf.type === 'image' && rf.state === 'succeeded'
         && /== bb emu image remove system-images;android-34;google_apis;x86_64/.test(rf.log)
         && /sdkmanager .*--uninstall system-images;android-34;google_apis;x86_64/.test(rf.log),
         `...which runs bb emu image there, and sdkmanager uninstalls it (${rf?.state}: ${
           (rf?.log || '').slice(-400).replace(/\n/g, ' / ')})`);
      rmSync(`${PK}/android/cmdline-tools`, { recursive: true, force: true });
    }
    // A recipe's system packages (the catalog's `system.apt`). This agent is
    // not root and has no sandbox stamp, so it is not the one to install
    // them: it names them and carries on to the recipe, which the stub npm
    // stops before anything is downloaded.
    const sj = await api('/api/toolchains', { action: 'install', names: ['playwright'], node: minted.id });
    ok(sj.ok && /^j_/.test(sj.job), `installing playwright on the node queues a job (${sj.job || sj.error})`);
    const sfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${sj.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(sfin && /needs system packages this node's owner installs/.test(sfin.log)
       && /libatk1\.0-0t64/.test(sfin.log) && /libnss3/.test(sfin.log),
       `a recipe's system packages are named for the owner on a node the agent does not administer (${
         (sfin?.log || '').match(/needs system packages[^\n]*/)?.[0]?.slice(0, 90)})`);
    // ...and the same libraries reported by the census as unmet for the
    // recipe the store holds (roadmap R51), without a build having to fail
    // on them, and installable on their own by a sysdeps job. This agent
    // does not administer the machine, so the job refuses and names them.
    const unmet = await until(async () => {
      const n = await nodeById(minted.id);
      return n?.reported?.sysdeps?.unmet?.playwright ? n.reported.sysdeps : null;
    }, 30000, 500);
    ok(unmet && unmet.family === 'apt' && unmet.unmet.playwright.includes('libnss3'),
       `the census names the system packages a held recipe lacks here, per family (${JSON.stringify(unmet).slice(0, 100)})`);
    // The fixture carries the sandbox stamp (bb-sandbox is stubbed) but the
    // agent is not root, so the controller queues the job and the agent is
    // the one to refuse: exit 77, naming the owner and the packages.
    // ...and on the Tools tab's own payload, per row: what the row's repair
    // is drawn from. The packages the census says are missing sit on the
    // recipe's row with the node's sandbox flag beside them, and a row whose
    // needed toolchain is not on this node says which, so the link on the
    // row installs exactly that and nothing else.
    const tcp = await api(`/api/toolchains?node=${minted.id}`);
    const pwRow = (tcp.items || []).find(i => i.name === 'playwright');
    // The stubbed npm stops the fixture's install short, so the controller
    // counts the row as not installed and its own missing list stays empty;
    // the census's answer rides the payload whole, which is what the tab's
    // banner draws from, and a row that IS installed carries its share.
    ok((tcp.sysdeps?.unmet?.playwright || []).includes('libnss3') && tcp.sandbox === true
       && (!pwRow?.installed || (pwRow.system?.missing || []).includes('libnss3')),
       `the Tools payload carries the missing packages and the node's sandbox flag (${JSON.stringify(tcp.sysdeps?.unmet?.playwright || []).slice(0, 60)}, sandbox ${tcp.sandbox}, row installed ${!!pwRow?.installed})`);
    const here = new Set((tcp.items || []).filter(i => i.installed).map(i => i.name));
    const wrong = (tcp.items || []).filter(i => i.installed).filter(i =>
      JSON.stringify(i.needs_missing || []) !== JSON.stringify((i.needs || []).filter(n => !here.has(n))));
    ok(wrong.length === 0, `every installed row names the toolchains it needs that this node lacks (${wrong.map(i => i.name).join(', ') || 'all agree'})`);
    const dj = await api('/api/toolchains', { action: 'sysdeps', names: ['playwright'], node: minted.id });
    ok(dj.ok && /^j_/.test(dj.job), `a sysdeps job is queued for the held recipe (${dj.job || dj.error})`);
    const dfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${dj.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(dfin && dfin.state === 'failed' && dfin.exit_code === 77
       && /does not administer the machine, so its owner installs these: playwright: /.test(dfin.log)
       && /libnss3/.test(dfin.log) && !/bb toolchains install/.test(dfin.log),
       `...and refused on the node with the names, without reinstalling the recipe (${dfin?.state} ${dfin?.exit_code}: ${(dfin?.log || '').slice(-160).replace(/\n/g, ' / ')})`);
    ok(sfin && sfin.state === 'failed' && /npm: stub/.test(sfin.log)
       && !existsSync(`${PK}/playwright/node_modules`),
       '...and the recipe then ran as the job account, where the stub npm stopped it before a download');
  }

  // ---- test workers: the node's setting, in every job's environment (R81) --
  // Set on the row, it reaches node.json by the next hello and every job
  // there carries it as BB_TEST_WORKERS; unset, the node's own cores do.
  {
    const cores = (await import('node:os')).cpus().length;
    const runEcho = async () => {
      const j = await api('/api/v1/nodes', { action: 'exec', id: minted.id, argv: ['sh', '-c', 'echo W=$BB_TEST_WORKERS'] });
      const fin = await until(async () => {
        const r = await api(`/api/v1/jobs?id=${j.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 30000);
      return (fin?.log || '').match(/W=(\d+)/)?.[1];
    };
    const set = await api('/api/v1/nodes', { action: 'test-workers', id: minted.id, workers: 3 });
    const kept = await until(() => JSON.parse(readFileSync(NODE_JSON, 'utf8')).test_workers === 3 ? true : null, 30000, 500);
    ok(set.ok && set.workers === 3 && kept && await runEcho() === '3',
       'test workers set on the node reach node.json and every job there as BB_TEST_WORKERS');
    await api('/api/v1/nodes', { action: 'test-workers', id: minted.id, workers: 0 });
    await until(() => JSON.parse(readFileSync(NODE_JSON, 'utf8')).test_workers === 0 ? true : null, 30000, 500);
    ok(await runEcho() === String(cores), `...and 0 means the machine's own cores (${cores})`);
    ok(/whole number/.test((await api('/api/v1/nodes', { action: 'test-workers', id: minted.id, workers: 'lots' })).error || ''),
       '...and a number that is not one is refused');
  }

  // ---- the idle rule reaches the node and stays there (idle.py) -----------
  // The controller's setting rides the hello reply into node.json, where the
  // agent enforces it on its own tmux, controller up or down. A change is
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

  // ---- the CI runners on the node, one per git host (phase 7, R53) ----------
  {
    const GH = 'github.com-example-org', GT = 'git.example.test-3000-example-org';
    const runnerOf = (n, slot) => (n.reported.services?.runners || []).find(r => r.slot === slot);
    const ended = async job => until(async () => {
      const r = await api(`/api/v1/jobs?id=${job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    // The token is the runner's, stored root-only through the helper under
    // the node and the runner's slot, with the address it registers with on
    // the record, and an install cannot start without one. Nothing here
    // ever reads it back.
    const notoken = await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GH, want: true });
    ok(/no such runner/.test(notoken.error || ''), 'installing a runner needs it added to the node first');
    ok(/https address/.test((await api('/api/v1/nodes', { action: 'runner-token', id: minted.id, url: 'ftp://nope', token: 'github_pat_TESTTOKEN1234' })).error || ''),
       '...and adding one needs the https address it registers with');
    const kept = await api('/api/v1/nodes', { action: 'runner-token', id: minted.id, url: 'https://github.com/example-org', token: 'github_pat_TESTTOKEN1234' });
    const recorded = await nodeById(minted.id);
    const rowJson = JSON.stringify(recorded);
    ok(kept.ok && kept.slot === GH && recorded.services?.runners?.[GH]?.url === 'https://github.com/example-org'
       && recorded.services.runners[GH].forge === 'github' && recorded.runner_tokens?.includes(GH)
       && !/TESTTOKEN/.test(rowJson) && /RUNNER_TOKEN=github_pat_TESTTOKEN1234/.test(readFileSync(`${DIR}/runner-store/${minted.id}.${GH}.env`, 'utf8')),
       `the token goes to the root-only store under the node and slot, and only its URL, forge and presence reach the record (${kept.error || kept.slot})`);
    // Forgotten, the runner is off the list and an install says so.
    ok((await api('/api/v1/nodes', { action: 'runner-forget', id: minted.id, slot: GH })).ok
       && !existsSync(`${DIR}/runner-store/${minted.id}.${GH}.env`)
       && !(await nodeById(minted.id)).services?.runners?.[GH]
       && /no such runner/.test((await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GH, want: true })).error || ''),
       'Forget token drops it from the store and the runner from the record');
    await api('/api/v1/nodes', { action: 'runner-token', id: minted.id, url: 'https://github.com/example-org', token: 'github_pat_TESTTOKEN1234' });
    // An install that failed is said, with the reason its log gave, until one
    // works. The census only knows what is installed, so a failed attempt used
    // to read as "install asked for; not reported yet" for as long as nobody
    // pressed Install again: a node sat twelve hours like that behind libicu.
    writeFileSync(`${DIR}/runner-fail`, '');
    const bad = await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GH, want: true });
    const bfin = await ended(bad.job);
    const failedRow = await until(async () => (await nodeById(minted.id)).runner_failed || null, 10000);
    const failedCard = ((await api('/api/status')).node_runners || []).find(x => x.id === minted.id && x.slot === GH);
    ok(bfin?.state === 'failed' && failedRow?.id === bad.job && failedRow.slot === GH
       && /^Libicu's dependencies is missing for Dotnet Core 6\.0/.test(failedRow?.why || '')
       && /Libicu/.test(failedCard?.failed?.why || ''),
       `a failed runner install is reported with the reason its log gave, on its own row (${bfin?.state}: ${
         failedRow?.why || failedCard?.failed?.why || 'nothing'})`);
    rmSync(`${DIR}/runner-fail`, { force: true });
    const inst = await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GH, want: true,
      labels: ['gpu', 'bad label!'] });
    ok(inst.ok && /^j_/.test(inst.job), `Install runner queues a system job (${inst.job || inst.error})`);
    const ifin = await ended(inst.job);
    const calls = existsSync(`${DIR}/runner/${GH}/calls.log`) ? readFileSync(`${DIR}/runner/${GH}/calls.log`, 'utf8') : '';
    ok(ifin && ifin.state === 'succeeded' && /registering agentbox with https:\/\/github.com\/example-org/.test(ifin.log),
       `the agent unpacks the runner into the runner's own directory and registers it (${ifin?.state}: ${(ifin?.log || '').slice(-200).replace(/\n/g, ' / ')})`);
    ok(/config --unattended --replace --url https:\/\/github.com\/example-org --token AAAREGTOKEN --name agentbox --labels builderbot,self-hosted,linux,x64,agentbox,gpu,badlabel --work _work/.test(calls)
       && /svc install/.test(calls) && /svc start/.test(calls)
       && /RUNNER_ROOT_OK/.test(calls),
       'config.sh gets the minted token, the node\'s name, the default labels plus its own name, and svc.sh installs and starts it');
    ok(!/AAAREGTOKEN/.test(ifin?.log || ''), '...and the token never reaches the job log');
    const renv = existsSync(`${DIR}/runner/${GH}/.env`) ? readFileSync(`${DIR}/runner/${GH}/.env`, 'utf8') : '';
    ok(/^BB_CI_LOG_DIR=.*agentdata\/ci-logs$/m.test(renv) && existsSync(`${DIR}/agentdata/ci-logs`),
       'the runner\'s .env points its workflows\' archive step at the data store, and the directory is there');
    // The rest of that file is the node's job environment: without it a CI
    // job's PATH was the bare system's, and the browser suite skipped with
    // exit 0 on every run (bug B74).
    ok(/^SDK_ROOT=.*(agenttoolchains|fakeshare\/toolchains)\/n_[0-9a-f]+$/m.test(renv)
       && /^PATH=.*(agenttoolchains|fakeshare\/toolchains)/m.test(renv)
       && /^ANDROID_HOME=.*\/android$/m.test(renv) && /^BB_CI_LOG_DIR=/m.test(renv),
       '...and carries the same toolchain environment every bb job on the node gets, so CI sees the store');
    const rn = await until(async () => { const n = await nodeById(minted.id);
      return runnerOf(n, GH)?.installed ? n : null; });
    ok(rn && runnerOf(rn, GH).name === 'agentbox' && runnerOf(rn, GH).labels.includes('agentbox')
       && rn.services.runners[GH].want === true
       && (rn.reported.services?.runners || []).some(r => r.slot === GH),
       'the census reports the runner under its slot, with its name and labels; the record keeps the ask');
    ok(rn && !rn.runner_failed, '...and the install that worked clears the failure before it');
    // A reinstall whose registration token cannot be minted (a token
    // lacking the org permission) leaves the runner standing: it used to
    // stop and uninstall the working service, clear the registration, and
    // only then ask for the token, leaving the node with no runner.
    writeFileSync(`${DIR}/runner-store/mint-fail`, '');
    const before = readFileSync(`${DIR}/runner/${GH}/calls.log`, 'utf8');
    const re = await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GH, want: true });
    const refin = await ended(re.job);
    const after = readFileSync(`${DIR}/runner/${GH}/calls.log`, 'utf8');
    const why = (await nodeById(minted.id)).runner_failed?.why || '';
    ok(refin?.state === 'failed' && /left as it was/.test(refin.log) && after === before && existsSync(`${DIR}/runner/${GH}/.runner`)
       && /Self-hosted runners/.test(why),
       `a reinstall whose token cannot mint leaves the working runner untouched and says which permission the token lacks (${refin?.state}: ${why.slice(-90)})`);
    rmSync(`${DIR}/runner-store/mint-fail`, { force: true });
    const labels = execFileSync('bash', [`${REPO}/scripts/bb`, 'ci-labels'],
      { encoding: 'utf8', cwd: REPO, env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
    ok(/^agentbox$/m.test(labels) && /^gpu$/m.test(labels) && /^builderbot$/m.test(labels),
       'bb ci-labels lists the node runner\'s labels beside this box\'s own');
    // A second runner on the same node, for a Gitea (R53): the same fold, a
    // different host. The picker says which when the address is a private
    // host the catalog has never seen; act_runner registers with a token the
    // controller fetches from that host, every label takes :host so a job
    // runs on this machine's own toolchain, and removal is a deletion by id
    // there. Both runners stand at once, each in its own directory.
    const gk = await api('/api/v1/nodes', { action: 'runner-token', id: minted.id,
      url: 'https://git.example.test:3000/example-org', forge: 'gitea', token: 'giteatokenABCDEF' });
    const gr = await nodeById(minted.id);
    ok(gk.ok && gk.slot === GT && gr.services.runners[GT].forge === 'gitea' && gr.services.runners[GH].url === 'https://github.com/example-org'
       && /RUNNER_FORGE=gitea/.test(readFileSync(`${DIR}/runner-store/${minted.id}.${GT}.env`, 'utf8')),
       `a private host is named through the picker and added beside the GitHub runner (${gk.error || 'stored'})`);
    const gi = await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GT, want: true, labels: ['gpu'] });
    const gfin = await ended(gi.job);
    const acts = existsSync(`${DIR}/runner/${GT}/act-calls.log`) ? readFileSync(`${DIR}/runner/${GT}/act-calls.log`, 'utf8') : '';
    ok(gfin?.state === 'succeeded' && /registering agentbox with https:\/\/git\.example\.test:3000\/example-org/.test(gfin.log)
       && /act register --no-interactive --instance https:\/\/git\.example\.test:3000 --token AAAREGTOKEN --name agentbox --labels builderbot:host,self-hosted:host,linux:host,x64:host,agentbox:host,gpu:host/.test(acts)
       && /act daemon/.test(acts) && !/AAAREGTOKEN/.test(gfin.log),
       `act_runner registers with the host from its own directory, every label as :host, and runs as a daemon under the agent (${gfin?.state}: ${(gfin?.log || '').slice(-160).replace(/\n/g, ' / ')})`);
    const gn = await until(async () => { const n = await nodeById(minted.id);
      const a = runnerOf(n, GT); return a?.installed && a.forge === 'gitea' && runnerOf(n, GH)?.installed ? n : null; }, 20000);
    ok(gn && runnerOf(gn, GT).name === 'agentbox' && runnerOf(gn, GT).active === true
       && runnerOf(gn, GT).url === 'https://git.example.test:3000/example-org'
       && gn.reported.services.runners.length === 2,
       "the census reports both runners at once: GitHub's and act_runner as installed, listening and Gitea's");
    const card = ((await api('/api/status')).node_runners || []).filter(x => x.id === minted.id);
    ok(card.length === 2 && card.some(x => x.slot === GH && x.installed) && card.some(x => x.slot === GT && x.listening),
       'the Runner card carries a row per runner on the node');
    // Removed one at a time: GitHub's with a removal token, Gitea's by id.
    const rm = await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GH, want: false });
    const rfin = await ended(rm.job);
    ok(rfin && rfin.state === 'succeeded' && !existsSync(`${DIR}/runner/${GH}`) && existsSync(`${DIR}/runner/${GT}`) && /runner removed/.test(rfin.log),
       "Remove runner deregisters GitHub's with a removal token and takes its directory away, leaving the other runner standing");
    const grm = await api('/api/v1/nodes', { action: 'runner', id: minted.id, slot: GT, want: false });
    const grfin = await ended(grm.job);
    const scalls = existsSync(`${DIR}/runner-store/calls.log`) ? readFileSync(`${DIR}/runner-store/calls.log`, 'utf8') : '';
    ok(grfin?.state === 'succeeded' && !existsSync(`${DIR}/runner/${GT}`) && new RegExp(`^remove \\S+ ${GT} 7$`, 'm').test(scalls),
       `Remove runner deletes the Gitea runner on its host by id and takes its directory away (${grfin?.state}; ${scalls.trim().split('\n').pop() || 'no deletion'})`);
    const rn2 = await until(async () => { const n = await nodeById(minted.id);
      return (n.reported.services?.runners || []).length === 0 ? n : null; });
    ok(rn2 !== null, '...and the census says so: the list is empty');
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
       '...and the next run of the same build fetches nothing: the node uses its copy');
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
  // is inside. The way they are kept in step is structural (bb-sandbox
  // reads the agent's own node.json instead of keeping a list of stores),
  // and this proves they answer the one shared question the same way. It
  // runs the REAL bb-sandbox, pulled out of the provisioner the same way
  // bb lint pulls it out for shellcheck.
  {
    const SBDIR = `${DIR}/sandbox-src`;
    mkdirSync(SBDIR, { recursive: true });
    execFileSync('python3', [`${REPO}/scripts/lib/embedded.py`, 'shell', SBDIR,
                             `${REPO}/nodes/provision-linux.sh`], { stdio: 'pipe' });
    const SB = `${SBDIR}/provision-linux.sh-BBSANDBOX`;
    const NJ = `${DIR}/contract-node.json`;
    writeFileSync(NJ, JSON.stringify({ stores: {
      data: '/var/lib/builderbot/data', toolchains: '/mnt/tank/builderbot/toolchains',
      cache: '/mnt/tank/cache', artifacts: '/mnt/other/art' } }));
    // Both sides, on the same cases. A store is "in" a mount when the mount
    // is its own path or a parent of it, and NOT when the mount's path is
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
      `${LOAD_AGENT}\nm = agentpkg.load()\n` +
      `st = json.loads(sys.argv[3])\n` +
      `print(','.join(sorted(r for r, p in st.items() if m.mount_covering(p, [{'path': sys.argv[2]}]))))`,
      `${REPO}/scripts/agent/builderbot-agent.py`, mp, JSON.stringify(stores)],
      { encoding: 'utf8' }).trim());
    const disagree = CASES.filter((_, i) => sandbox[i] !== agent[i]);
    ok(disagree.length === 0,
       `bb-sandbox and the agent agree on which stores a mount holds, in all ${CASES.length} cases${
         disagree.length ? `, but they differ on ${disagree.join(', ')}: ${
           disagree.map(c => `${c} sandbox[${sandbox[CASES.indexOf(c)]}] agent[${agent[CASES.indexOf(c)]}]`).join('; ')}` : ''}`);
    ok(sandbox[CASES.indexOf('/mnt/tank')] === 'cache,toolchains'
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

    // The update itself, which every node performs on every controller
    // update and no suite had run: the shipped file moves (a comment on
    // its end, here), the row reads behind, Update agent queues the job,
    // the agent downloads the file, checks its digest, writes it over its
    // own, re-executes in place and dials in on the new digest. Then it
    // still takes work, which is the point of it staying the same process.
    appendFileSync(AGENT, '\n# the suite: from here on the controller ships a newer agent\n');
    const shipped = await until(async () => {
      const r = await api('/api/v1/nodes');
      return r.agent?.digest && r.agent.digest !== all.agent.digest ? r.agent : null;
    }, 20000);
    ok(shipped && shipped.version === all.agent.version,
       `the controller ships the file as it is now: a new digest, the same number (${shipped?.digest?.slice(0, 19)})`);
    const behind = await until(async () => { const x = await nodeById(minted.id); return x.agent?.digest !== shipped.digest ? x : null; }, 5000);
    ok(behind !== null, '...and the node, still on the old file, is behind by digest');
    const up = await api('/api/v1/nodes', { action: 'update-agent', id: minted.id });
    ok(up.ok && /^j_/.test(up.job), `Update agent queues the self-update (${up.job || up.error})`);
    const ufin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${up.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(ufin?.state === 'succeeded' && /installed sha256:/.test(ufin.log || '') && /restarting/.test(ufin.log || ''),
       `the agent downloads the file, checks its digest, installs it over its own and restarts (${ufin?.state}: ${(ufin?.log || '').trim().split('\n').pop()?.slice(0, 80)})`);
    const back = await until(async () => {
      const x = await nodeById(minted.id);
      return x.live && x.agent?.digest === shipped.digest ? x : null;
    }, 60000);
    ok(back !== null, `...and dials in again on the shipped digest, live (${back?.agent?.digest?.slice(0, 19)})`);
    ok(/re-executing the new agent/.test(agentLog()), '...having re-executed itself in place, the same process');
    ok(readFileSync(AGENT_RUN, 'latin1').includes('from here on the controller ships a newer agent'),
       '...and the file it runs from is the shipped one now');
    const cur2 = await api('/api/v1/nodes', { action: 'update-agent', id: minted.id });
    ok(cur2.ok && cur2.current === true, '...so it is current again and no job is queued');
    const ej = await api('/api/v1/nodes', { action: 'exec', id: minted.id, argv: ['sh', '-c', 'echo alive after the update'] });
    const efin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${ej.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 30000);
    ok(efin?.state === 'succeeded' && /alive after the update/.test(efin.log || ''),
       `...and the new agent takes a job (${efin?.state})`);
    // The status command, the one the docs tell a person to run on a node.
    const st = execFileSync('python3', [AGENT_RUN, 'status'], { env: agentEnv, encoding: 'utf8' });
    ok(st.length > 0 && new RegExp(minted.id).test(st), `\`builderbot-agent status\` names the node (${st.trim().split('\n')[0].slice(0, 80)})`);
  }

  // ---- one command as root, allowed by a person, run by the real agent -----
  // root.mjs proves the asking and the allowing on the controller; this is
  // the other end: the agent runs the command as given, once, its log
  // opening with the reason and who allowed it, and the output streams
  // back. The fixture agent is not root, so `id -un` names the test user,
  // which is the honest answer here.
  {
    const asked = await api('/api/phone', { action: 'ask', kind: 'root', why: 'prove the root path on the real agent',
                                            cmd: ['sh', '-c', 'echo root job ran; id -un'], project: 'alpha' });
    ok(asked.id > 0, `a root ask for the project on this node is queued (${asked.id || asked.error})`);
    const al = await api('/api/phone', { action: 'allow', id: asked.id });
    ok(!al.error, `an administrator allows it (${al.error || 'ok'})`);
    const rfin = await until(async () => {
      const r = await api('/api/phone', { action: 'outcome', id: asked.id });
      return ['done', 'failed', 'denied', 'expired'].includes(r.state) ? r : null;
    }, 30000);
    ok(rfin?.state === 'done' && /# root on this node, allowed by test: prove the root path/.test(rfin.out || '')
       && /root job ran/.test(rfin.out || ''),
       `the agent runs it once and the log opens with the reason and who allowed it (${rfin?.state}: ${(rfin?.out || '').trim().split('\n')[0]?.slice(0, 90)})`);
    const sysjob = ((await api('/api/v1/jobs?n=10')).jobs || []).find(j => j.type === 'system' && j.node === minted.id);
    ok(sysjob && sysjob.state === 'succeeded', `...as a system job on this node, finished (${sysjob?.state || 'no system job found'})`);
  }

  // ---- Claude Code updated by the real agent (claudecode.py) ---------------
  // The job runs the installer as the session account (the stub here writes
  // nothing real), reads the version back and, not being root in this
  // fixture, keeps the account's own copy; the log says each step.
  {
    writeFileSync(`${DIR}/bin/claude-installer`, `#!/bin/sh
echo "Installing Claude Code (stub) for $USER into $HOME"
echo "stub-installed" >> "${DIR}/claude-installer.log"
`, { mode: 0o755 });
    // The record says the session half is up before Install is pressed: the
    // ttyd restart above asked for a hello, whose census is taken beside the
    // loop now rather than before the next job is taken (B644), so for a few
    // seconds the row is behind the machine.
    await until(async () => (await nodeById(minted.id))?.reported?.session?.up ? true : null, 30000);
    // From the node's Toolchains tab, where Claude Code is a row (R145).
    const cu = await api('/api/toolchains', { action: 'install', node: minted.id, names: ['claude-code'] });
    ok(cu.ok && /^j_/.test(cu.job), `Install on the Toolchains tab queues the claude-update job on this node (${cu.job || cu.error})`);
    const cfin = await until(async () => {
      const r = await api(`/api/v1/jobs?id=${cu.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
    }, 60000);
    ok(/Installing Claude Code \(stub\)/.test(cfin?.log || '') && existsSync(`${DIR}/claude-installer.log`),
       `the agent runs the installer as the session account and streams its words (${cfin?.state})`);
    ok(cfin?.state === 'failed' ? /does not run|no claude in|no claude to run/.test(cfin.log || '') : /is what a session here runs now/.test(cfin?.log || ''),
       `...and says what runs afterwards, or why nothing does (${(cfin?.log || '').trim().split('\n').slice(-1)[0]?.slice(0, 90)})`);
  }

  // ---- Send to Claude reaches a session on a node -------------------------
  // The notebook's send typed into THIS container's tmux and nowhere else,
  // so once sessions moved onto nodes every project was told "no session
  // is running here" while its own row showed one. The line now goes as a
  // `tell` job the agent runs by the same rule notify.tell keeps: Enter
  // only once the pane echoes the line. A plain shell echoes, which is
  // what makes it testable. Here, well after the blocks above ended
  // alpha's: a name just killed is held off the list for a minute.
  {
    const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
    const real = `${uid}~claude-alpha`;
    tmuxKill(real);
    tmuxNew(real, `${DIR}/ws/alpha`, ['bash', '--norc', '--noprofile']);
    const listed = await until(async () =>
      ((await api('/api/status')).sessions || []).find(
        s => s.node === 'agentbox' && s.name === 'claude-alpha'), 45000, 500);
    ok(!!listed, 'a shell standing in for the session is listed on the node');
    const st = await api('/api/roadmap?project=alpha');
    ok(st.session === 'claude-alpha',
       'the roadmap panel sees somewhere to send when the session is on a node');
    const added = await api('/api/roadmap', { action: 'add', project: 'alpha',
                                           text: 'a step handed to the session on the node' });
    const id = Number(added.item?.id);
    const sent = await api('/api/roadmap', { action: 'send', project: 'alpha', id });
    ok(sent.sent === true && !sent.error,
       `Send to Claude hands the step to the session on the node (${JSON.stringify(sent).slice(0, 120)})`);
    const typed = await until(async () =>
      /handed to the session on the node/.test(tmuxCapture(real)) ? true : null, 30000, 500);
    ok(typed === true, '...and the line really went into the pane there');
    ok((sent.items || []).find(i => Number(i.id) === id)?.sent > 0,
       '...and the item is crossed as sent, since it went');
    await api('/api/roadmap', { action: 'remove', project: 'alpha', id, why: 'test' });
    tmuxKill(real);
  }

  // ---- compose runs on the agent, not over ssh (roadmap #18) -----------------
  // The controller sends the plan and the files; the node's own docker runs
  // it. The stub docker records what it was asked, so this proves the argv
  // and the working directory as well as the wiring.
  {
    // agent.mjs runs before devapp.mjs, which is what gives ep.silon its
    // compose file, so this suite writes its own.
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
    // A bind directory the node cannot make is an up that cannot work, and
    // the agent says so and runs nothing, rather than letting docker fail on
    // the same mkdir in worse words ("file exists" over a stale NFS handle,
    // 15 Sep). A file where the instance's data directory would go is the
    // cheapest way to make one unmakeable.
    {
      const made = await api('/api/devapp', { project: 'ep.silon', action: 'new', instance: 'blocked', node: minted.id });
      ok(made.ok && made.instance === 'blocked', `a second instance to block (${made.error || made.instance})`);
      writeFileSync(`${DIR}/devdata/blocked`, 'not a directory\n');
      const up2 = await api('/api/devapp', { project: 'ep.silon', instance: 'blocked', action: 'up' });
      ok(up2.ok || up2.started, `Up on it is queued (${up2.error || 'ok'})`);
      const jb = await until(async () => {
        const r = await api('/api/v1/jobs?project=ep.silon&type=compose&n=1');
        const one = (r.jobs || [])[0];
        if (!one || !['succeeded', 'failed', 'canceled'].includes(one.state) || one.id === j.id) return null;
        return api(`/api/v1/jobs?id=${one.id}`);
      }, 60000);
      ok(jb && jb.state === 'failed' && jb.exit_code === 73 && /could not make .*blocked: (Not a directory|File exists)/.test(jb.log || '')
         && !/\$ .*compose/.test(jb.log || ''),
         `a bind directory the node cannot make fails the job with the machine's reason before the plan runs (${jb?.state} ${jb?.exit_code}; dirs=${JSON.stringify(jb?.spec?.dirs)}: ${(jb?.log || '').replace(/\s+/g, ' ').slice(-300)})`);
      ok(jb && (jb.outputs || []).some(o => o.kind === 'compose' && o.failed_at === 'preparing'),
         '...and names the step, so the row says a directory could not be made rather than that up failed');
      rmSync(`${DIR}/devdata/blocked`, { force: true });
      await api('/api/devapp', { project: 'ep.silon', instance: 'blocked', action: 'remove' });
    }
    // A bind directory that is there already is somebody's (a container's
    // config directory, a tree an administrator chowned on request) and is
    // left as it is: handing every mount source to the agent's account on
    // each rebuild broke the containers that owned them (B315). Only one
    // this step makes is given to the session account.
    {
      const made = await api('/api/devapp', { project: 'ep.silon', action: 'new', instance: 'kept', node: minted.id });
      mkdirSync(`${DIR}/devdata/kept`, { recursive: true });
      const up3 = await api('/api/devapp', { project: 'ep.silon', instance: 'kept', action: 'up' });
      const jk = await until(async () => {
        const r = await api('/api/v1/jobs?project=ep.silon&type=compose&n=1');
        const one = (r.jobs || [])[0];
        if (!one || !['succeeded', 'failed', 'canceled'].includes(one.state) || one.id === j.id) return null;
        return api(`/api/v1/jobs?id=${one.id}`);
      }, 60000);
      ok(made.ok && (up3.ok || up3.started) && jk && /bind directory .*\/kept \(already there, left as it is\)/.test(jk.log || ''),
         `a bind directory that exists already is left as it is, and the job says so (${jk?.state}: ${
            ((jk?.log || '').match(/bind directory [^\n]*/) || [''])[0].slice(0, 90)})`);
      const rm = await api('/api/devapp', { project: 'ep.silon', instance: 'kept', action: 'remove' });
      // Waited for: `main` has no record until something writes one, and
      // instances() offers it only while the project has none, so the
      // env-set on main below met "no instance main" whenever this remove
      // had not yet forgotten kept (a race the step used to win, 12 Oct).
      await until(async () => {
        const r = await api(`/api/v1/jobs?id=${rm.job}`);
        return ['succeeded', 'failed', 'canceled'].includes(r.state) ? r : null;
      }, 60000);
    }
    // A compose file that reads its settings through `env_file: .env`: the
    // project's own .env, which BuilderBot never writes. The instance's env
    // went to compose as --env-file only, which fills ${VAR} and nothing
    // else, so what was typed into Send to Docker never reached the
    // container, and Up failed on the missing file (Is-someone-Listening,
    // 24 Sep). The copy the node runs names the instance's env instead.
    {
      writeFileSync(`${DIR}/ws/ep.silon/docker-compose.yml`,
                    'services:\n  app:\n    image: alpine\n    env_file: .env\n');
      const set = await api('/api/devapp', { project: 'ep.silon', instance: 'main', action: 'env-set',
                                              text: 'GREETING=hello\n' });
      ok(set.ok, `the instance's env is saved (${set.error || 'ok'})`);
      const up3 = await api('/api/devapp', { project: 'ep.silon', instance: 'main', action: 'up' });
      ok(up3.ok || up3.started, `Up is queued (${up3.error || 'ok'})`);
      const je = await until(async () => {
        const r = await api('/api/v1/jobs?project=ep.silon&type=compose&n=1');
        const one = (r.jobs || [])[0];
        if (!one || !['succeeded', 'failed', 'canceled'].includes(one.state) || one.id === j.id) return null;
        const full = await api(`/api/v1/jobs?id=${one.id}`);
        return (full.spec?.files || {})['instance.env'] ? full : null;
      }, 60000);
      const shipped = je?.spec?.files?.['docker-compose.yml'] || '';
      ok(je && /env_file: \$\{BB_INSTANCE_ENV\}/.test(shipped) && !/env_file: \.env/.test(shipped)
         && je.spec.files['instance.env'] === 'GREETING=hello\n'
         && je.spec.plan.every(st => st.env?.BB_INSTANCE_ENV === '{cdir}/instance.env')
         && je.state === 'succeeded',
         `the node gets a compose copy whose env_file names the instance's env, and every step the path (${je?.state}: ${
           JSON.stringify(shipped.split('\n').filter(l => /env_file/.test(l)))})`);
      // ...and the controller's own compose calls (the row reads the file
      // with compose config) run a copy beside the env that names it.
      await api('/api/devapp', { project: 'ep.silon', instance: 'main', action: 'state' });
      const copy = (() => { try { return readFileSync(`${DIR}/state/devenv/ep-silon.compose.yml`, 'utf8'); }
                            catch { return ''; } })();
      ok(copy.includes(`env_file: ${DIR}/state/devenv/ep-silon.env`),
         `...and so do the controller's own compose calls (${copy.split('\n').find(l => /env_file/.test(l)) || 'no copy'})`);
      await api('/api/devapp', { project: 'ep.silon', instance: 'main', action: 'env-set', text: '' });
      rmSync(`${DIR}/state/devenv/ep-silon.env`, { force: true });
      rmSync(`${DIR}/state/devenv/ep-silon.compose.yml`, { force: true });
      writeFileSync(`${DIR}/ws/ep.silon/docker-compose.yml`, 'services:\n  app:\n    image: alpine\n');
    }
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
       'a draining node takes no new job: refused at the queue, not left waiting');
    await api('/api/v1/nodes', { action: 'online', id: minted.id });
  }

  // the tab, on a live agent node
  {
    await page.evaluate(() => { const c = document.getElementById('cardTools');
      if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
    await page.evaluate(() => openNodesTab());
    // The tab shows one node, chosen in the bar, so pick this one before
    // looking for its row.
    await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
    await page.selectOption('.nodestab #ndPick', minted.id);
    await page.waitForSelector(`.nodestab .ndrow[data-node="${minted.id}"] .ndlive`,
                               { timeout: 15000 });
    const row = await page.$eval(`.nodestab .ndrow[data-node="${minted.id}"]`,
                                 e => e.textContent.replace(/\s+/g, ' '));
    // Its facts a grid (R218 step 26): the account jobs run as is one.
    const runsAs = await page.$$eval(`.nodestab .ndrow[data-node="${minted.id}"] .ndfacts .fact`,
      fs => fs.find(f => f.querySelector('dt').textContent === 'Jobs run as')?.querySelector('dd').textContent || '');
    ok(/agentbox/.test(row) && /live/.test(row) && /cpu/.test(row) && /data/.test(row)
       && runsAs === (process.env.USER || 'builder'),
       `the row shows the agent live, its numbers and the account jobs run as (${row.slice(0, 160)}…)`);
    // Each session kept to its own project's network (R79): a switch in the
    // row's Sessions section, a draft until the section's Save (the rule
    // apply-not-onchange: it wrote itself on the click at first, the
    // operator, 24 Sep). The node hears it on its next poll and keeps it in
    // node.json with what each project owns there, and says whether it can,
    // which this agent, not root, cannot: said under the switch in red.
    {
      const sw = `.nodestab .ndrow[data-node="${minted.id}"] [data-k="sessnet"]`;
      const save = `.nodestab .ndrow[data-node="${minted.id}"] [data-nd="sess-save"]`;
      await openSection(page, 'nodes:sessions', `.nodestab .ndrow[data-node="${minted.id}"]`);
      await page.waitForSelector(sw, { timeout: 15000 });
      ok(!(await page.$eval(sw, e => e.checked)), 'the Sessions section offers the switch, off to begin with');
      await page.click(sw);
      await sleep(1500);
      ok(!(await nodeById(minted.id)).config?.session_net && await page.$eval(sw, e => e.checked),
         'ticking it writes nothing by itself, and the tick survives a repaint');
      await page.click(save);
      const kept = await until(() => {
        const st = JSON.parse(readFileSync(NODE_JSON, 'utf8'));
        return st.session_net?.on === true ? st : null;
      }, 30000, 500);
      ok(kept && kept.session_net.own && typeof kept.session_net.own === 'object',
         `the node hears it on its next poll and keeps it in node.json, with what each project owns there (${JSON.stringify(kept?.session_net).slice(0, 90)})`);
      // The census that has heard the switch: the one before it already
      // carries a reason, from the agent's first look, with wanted false.
      // Said at the agent's next turn rather than its next ten-minute hello.
      const said = await until(async () => {
        const n = await nodeById(minted.id);
        return n?.reported?.session_net?.wanted === true ? n.reported.session_net : null;
      }, 45000, 500);
      ok(said && said.can === false && said.wanted === true && /root/.test(said.why),
         `...and says whether it can keep sessions there, and why not (${said?.why})`);
      await page.waitForFunction(id => /Not in force: the agent does not run as root here/.test(
        document.querySelector(`.nodestab .ndrow[data-node="${id}"]`)?.textContent || ''), minted.id, { timeout: 30000 });
      ok(await page.$$eval(`.nodestab .ndrow[data-node="${minted.id}"] .sub.bad`, es => es.some(e => /Not in force/.test(e.textContent))),
         '...which the row says under the switch, in red');
      await page.click(sw);
      await page.click(save);
      const cleared = await until(() => JSON.parse(readFileSync(NODE_JSON, 'utf8')).session_net?.on === false ? true : null,
                                  30000, 500);
      ok(cleared, '...and off, saved the same way, reaches the node the same way');
      // The same Save carries whether a session here may ask for root.
      const ra = `.nodestab .ndrow[data-node="${minted.id}"] [data-k="rootasks"]`;
      ok(await page.$eval(ra, e => e.checked), 'root asks are on by default, beside it');
      await page.click(ra);
      await page.click(save);
      const noRoot = await until(async () => (await nodeById(minted.id)).config?.no_root === true ? true : null, 15000, 300);
      // The row says so once the page has read the node again after the Save.
      const toldOff = noRoot && await page.waitForFunction(id => [...document.querySelectorAll(`.nodestab .ndrow[data-node="${id}"] .sub`)]
        .some(e => /refused and told this is off/.test(e.textContent)), minted.id, { timeout: 15000 }).then(() => true, () => false);
      ok(toldOff, `...and unticking it, then Save, turns them off and says so under the switch (${noRoot ? 'off on the node' : 'still on at the node'})`);
      await page.click(ra);
      await page.click(save);
      await until(async () => (await nodeById(minted.id)).config?.no_root ? null : true, 15000, 300);
    }
    // Enrolling is a dialog, like New project. It used to be a panel at the
    // foot of the tab, below everything about the machine you were looking at.
    await page.click('#ndEnroll');
    await page.waitForSelector('#ndmodal:not([hidden]) #ndEnName', { timeout: 10000 });
    ok(await page.$('.nodestab #ndEnName') === null,
       'Enroll node opens a dialog rather than a panel at the foot of the tab');
    await page.fill('#ndEnName', 'second');
    await page.click('#ndEnTok');
    await page.waitForSelector('#ndmodal .ndtoken', { timeout: 15000 });
    const shown = await page.$eval('#ndmodal .ndtoken', e => e.textContent);
    // Linux; a Mac's is a dev feature, named only with Offer dev features on.
    ok(/bbe_/.test(shown) && /provision-linux\.sh/.test(shown) && !/provision-macos\.sh/.test(shown) && /--controller/.test(shown),
       'Enroll node shows the one-time token inside the provisioner commands, and no Mac while dev features are off');
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

  // ---- uninstall, from the Nodes tab ------------------------------------------
  // Last, because it retires the node: the agent answers the system job by
  // starting `bb-sandbox uninstall --yes` detached (the stub records the
  // call; a real one removes the agent under itself) and the controller
  // retires the row when the job succeeds. Runner deregistration was
  // exercised above; none is left here to deregister.
  {
    // Refused while a session runs there (the operator, 11 Oct): the shell
    // the block above killed in tmux is on the record until the agent's
    // next heartbeat says it is gone, so that is waited for first.
    const left = ((await api('/api/status')).sessions || []).filter(s => s.node === 'agentbox');
    for (const s of left) await api('/api/session', { action: 'kill', session: s.name, node: minted.id });
    // An account's sessions (u_<uid>~name) are the ones that hold it; the
    // harness's own tmux sessions on the same server do not count.
    const quiet = await until(async () =>
      ((await api('/api/v1/nodes')).nodes.find(n => n.id === minted.id)?.reported?.sessions || []).some(s => /^u_[0-9a-f]{8}~/.test(s.name)) ? null : true, 45000, 500);
    ok(quiet === true, `the node reports none of an account's sessions left before it is un-enrolled (ended first: ${left.map(s => s.name).join(', ') || 'none'})`);
    const r = await api('/api/v1/nodes', { action: 'uninstall', id: minted.id });
    ok(r.ok && /^j_/.test(r.job || ''), `Uninstall on a sandbox node queues a system job (${r.error || r.job})`);
    const fin = await until(async () => { const j = await api(`/api/v1/jobs?id=${r.job}`);
      return ['succeeded', 'failed', 'canceled'].includes(j.state) ? j : null; }, 30000);
    ok(fin?.state === 'succeeded' && /the uninstall is running on this machine[\s\S]*it is still running; this agent goes with it/.test(fin.log || ''),
       `the agent starts the uninstall on the machine and says it is its last word (${fin?.state}: ${(fin?.log || '').slice(-120).replace(/\n/g, ' / ')})`);
    ok(existsSync(SANDBOX_STATE + '.uninstall') && readFileSync(SANDBOX_STATE + '.uninstall', 'utf8') === 'uninstall --yes',
       '...through bb-sandbox uninstall --yes, detached from the agent');
    const gone = await until(async () => (await api('/api/v1/nodes')).nodes.some(n => n.id === minted.id) ? null : true, 20000);
    ok(!!gone, 'and the controller retires the node when the job lands, so the row leaves every list');
    // Back to online for what follows: the stub uninstall took nothing
    // off this machine, so the agent is still here.
    await api('/api/v1/nodes', { action: 'online', id: minted.id });
    ok((await api('/api/v1/nodes')).nodes.some(n => n.id === minted.id), '...and Undrain brings a retired row back, for what follows');
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
// every list, which is what the files after this one expect to find: a
// store holding local and the sandbox and nothing else.
//
// BY NAME as well as by kind. The harness's docker host used to be an
// `ssh` row, so "every agent node" could not reach it; since roadmap #24 it
// is an enrolled agent node like any other, and this loop retired it, after
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
${LOAD_AGENT}
m = agentpkg.load()
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
// The job the controller sends is one shape (mode, address, gateway, dns)
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
${LOAD_AGENT}
m = agentpkg.load()
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
  // this test's python sees; the fixture agent must keep the real answer.
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
${LOAD_AGENT}
m = agentpkg.load()
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
# ifupdown: networkd out of the way, an interfaces file with a neighbor to keep
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
     `every distribution lands in its family through ID and ID_LIKE, across ${Object.keys(WANT).length} samples${wrong.length ? ': ' + wrong.join(', ') : ''}`);
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
     `with ifupdown the interface's own stanza is replaced and the neighbors kept (${R.if_backend}, ${R.r3[0]})`);
  ok(R.r4[0] === 'failed' && R.if_after === R.if_text,
     '...and its revert is the whole file as it was before the change');
}

// ---- the last two backends: wicked, and dhcpcd on its own -------------------
// SUSE's wicked is ifcfg and ifroute files plus netconfig's resolver line,
// then ifreload; Void's dhcpcd is a marked block in dhcpcd.conf and a
// restart. Same spec, same revert, driven in process like the two above.
{
  const NB = `${DIR}/nbin2`; mkdirSync(NB, { recursive: true });
  writeFileSync(`${NB}/systemctl`, `#!/bin/sh
echo "systemctl $*" >> "${DIR}/net2.log"
case "$*" in "is-active wicked") echo active ;; *) echo inactive ;; esac
`, { mode: 0o755 });
  for (const b of ['wicked', 'netconfig', 'dhcpcd'])
    writeFileSync(`${NB}/${b}`, `#!/bin/sh\necho "${b} $*" >> "${DIR}/net2.log"\n`, { mode: 0o755 });
  writeFileSync(`${NB}/pgrep`, `#!/bin/sh\necho 4242\n`, { mode: 0o755 });
  const NONE = ['NETPLAN', 'NMCLI', 'NETWORKCTL', 'IFUP']
    .map(k => `os.environ['BUILDERBOT_${k}_BIN'] = '/nonexistent/${k.toLowerCase()}'`).join('\n');
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
${NONE}
os.environ['PATH'] = ${JSON.stringify(NB)} + ':' + os.environ.get('PATH', '')
os.environ['BUILDERBOT_WICKED_BIN'] = ${JSON.stringify(`${NB}/wicked`)}
os.environ['BUILDERBOT_SYSCONFIG_NET_DIR'] = sc = tempfile.mkdtemp()
os.environ['BUILDERBOT_DHCPCD_CONF'] = dc = os.path.join(tempfile.mkdtemp(), 'dhcpcd.conf')
os.environ['BUILDERBOT_SANDBOX_BIN'] = ${JSON.stringify(`${DIR}/bin/bb-sandbox`)}
${LOAD_AGENT}
m = agentpkg.load()
m.DIAL_BACK_S = 1
a = m.Agent.__new__(m.Agent); a.state = {'stores': {}}
class J:
    def __init__(self): self.lines = []
    def say(self, t): self.lines.append(t)
    def flush(self): pass
want = {'network': {'mode': 'static', 'address': '10.3.3.5/24', 'gateway': '10.3.3.1', 'dns': ['10.3.3.1', '10.3.3.2'], 'interface': 'eth0'}}
open(os.path.join(sc, 'config'), 'w').write('NETCONFIG_DNS_POLICY="auto"\\nNETCONFIG_DNS_STATIC_SERVERS="9.9.9.9"\\n')
w_backend = m.net_backend().name
a.hello = lambda: (200, {})
j1 = J(); r1 = a._apply_network(j1, want)
rd = lambda n: open(os.path.join(sc, n)).read() if os.path.exists(os.path.join(sc, n)) else None
w_files = {'ifcfg': rd('ifcfg-eth0'), 'ifroute': rd('ifroute-eth0'), 'config': rd('config')}
a.hello = lambda: (503, {})
j2 = J(); r2 = a._apply_network(j2, {'network': {'mode': 'dhcp', 'interface': 'eth0'}})
w_after = {'ifcfg': rd('ifcfg-eth0'), 'ifroute': rd('ifroute-eth0'), 'config': rd('config')}
# dhcpcd: wicked out of the way, a conf with lines of its own to keep
m.WICKED_BIN = '/nonexistent/wicked'
open(dc, 'w').write('hostname\\nnoipv6\\n')
d_backend = m.net_backend().name
a.hello = lambda: (200, {})
j3 = J(); r3 = a._apply_network(j3, want)
d_text = open(dc).read()
j4 = J(); r4 = a._apply_network(j4, {'network': {'mode': 'dhcp', 'interface': 'eth0'}})
d_after = open(dc).read()
print(json.dumps({'w_backend': w_backend, 'r1': r1, 'w_files': w_files, 'r2': r2, 'w_after': w_after, 'log2': ''.join(j2.lines),
                  'd_backend': d_backend, 'r3': r3, 'd_text': d_text, 'r4': r4, 'd_after': d_after,
                  'calls': open(${JSON.stringify(`${DIR}/net2.log`)}).read()}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(R.w_backend === 'wicked' && R.r1[0] === 'succeeded'
     && R.w_files.ifcfg === "STARTMODE='auto'\nBOOTPROTO='static'\nIPADDR='10.3.3.5/24'\n"
     && R.w_files.ifroute === 'default 10.3.3.1 - eth0\n'
     && /NETCONFIG_DNS_POLICY="auto"\nNETCONFIG_DNS_STATIC_SERVERS="10\.3\.3\.1 10\.3\.3\.2"\n/.test(R.w_files.config)
     && /wicked ifreload eth0/.test(R.calls) && /netconfig update -f/.test(R.calls),
     `with wicked active the spec is ifcfg, ifroute and netconfig's resolver line, then a reload (${R.w_backend}, ${R.r1[0]})`);
  ok(R.r2[0] === 'failed' && /reverting/.test(R.log2) && R.w_after.ifcfg === R.w_files.ifcfg
     && R.w_after.ifroute === R.w_files.ifroute && R.w_after.config === R.w_files.config,
     '...and a change the controller cannot confirm puts all three files back');
  ok(R.d_backend === 'dhcpcd' && R.r3[0] === 'succeeded'
     && /^hostname\nnoipv6\n\n# BuilderBot: eth0\ninterface eth0\nstatic ip_address=10\.3\.3\.5\/24\nstatic routers=10\.3\.3\.1\nstatic domain_name_servers=10\.3\.3\.1 10\.3\.3\.2\n# BuilderBot: end\n$/.test(R.d_text)
     && /systemctl restart dhcpcd/.test(R.calls),
     `with dhcpcd alone the spec is a marked block after the file's own lines, and a restart (${R.d_backend}, ${R.r3[0]})`);
  ok(R.r4[0] === 'succeeded' && R.d_after === 'hostname\nnoipv6\n',
     '...and dhcp takes the block out again, leaving the file as it was');
}

// ---- the toolchain store, scoped by platform; and a Mac ----------------------------
// The layout's standing rule: a scope's Android system images live once
// under <store>/shared with the scope's own directory a link to them, and
// a second run changes nothing. Then the Mac: with platform.system()
// answering Darwin, the agent's family is macos, its packages Homebrew, its
// init launchd, its scope darwin-<arch>.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
os.environ['BUILDERBOT_BREW_BIN'] = '/nonexistent/brew'
${LOAD_AGENT}
m = agentpkg.load()
store = tempfile.mkdtemp()
m.use_scope(store, 'n_00aa11bb')
scope = m.tc_scope()
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
print(json.dumps({'r1': r1, 'r2': r2, 'mac': mac, 'scope': m.tc_scope(), 'root': m.tc_root({'stores': {'toolchains': '/Volumes/SDK'}})}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(R.r1.link && R.r1.shared && /shared\/android\/system-images$/.test(R.r1.target),
     'a scope\'s android system images are moved once under shared/, with the scope\'s directory a link to them');
  ok(R.r1.said.some(t => /shared across platforms/.test(t)) && R.r2.said.length === 0 && R.r2.link,
     `...it says so once, and a second run says and moves nothing (${R.r1.said[0] || ''})`);
  ok(R.mac.family === 'macos' && R.mac.init === 'launchd' && /macOS 15\.1/.test(R.mac.pretty) && R.mac.network === '' && R.mac.pkg === '',
     `a Mac is its own family: macos, launchd, no network backend, and no package manager until Homebrew is there (${JSON.stringify(R.mac)})`);
  ok(R.scope === 'n_00aa11bb' && R.root === '/Volumes/SDK/n_00aa11bb',
     `...with its toolchains under its node id in the store, as every node's are (R196) (${R.root})`);
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
${LOAD_AGENT}
m = agentpkg.load()
m.os.geteuid = lambda: 0
m.use_scope(d, 'n_00aa11cc')
a = m.Agent.__new__(m.Agent)
a.state = {'controller': 'http://127.0.0.1:1', 'stores': {'toolchains': d}}
a.fw_checked = 0.0
a.session_firewall_check()
first = open(nftf).read()
a.fw_checked = 0.0
a.session_firewall_check()
calls = open(${JSON.stringify(`${DIR}/nft.log`)}).read() if os.path.exists(${JSON.stringify(`${DIR}/nft.log`)}) else ''
# the node's own address moving: ttyds bound to the old one are marked for a restart
os.makedirs(os.path.join(d, m.tc_scope(), '.bb', 'current'))
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
// The window is the project's compatibility promise (while BuilderBot is
// 0.4.x, any 0.4 agent works with any 0.4 controller), and it is a constant
// in a file, which means it drifts the moment somebody bumps the minor and
// does not think about the agent. That is the bump this is about, so the
// check is here rather than in anybody's memory.
{
  // the package's sources, the number in its __init__
  const PKG = `${REPO}/scripts/agent/builderbot_agent`;
  const src = readdirSync(PKG).filter(f => f.endsWith('.py')).sort()
    .map(f => readFileSync(`${PKG}/${f}`, 'utf8')).join('\n');
  const av = /^AGENT_VERSION\s*=\s*"([^"]+)"/m.exec(src)?.[1] || '';
  const win = /^(\d+\.\d+)\./.exec(av)?.[1] || '';
  const proj = readFileSync(`${REPO}/VERSION`, 'utf8').trim();
  const minor = proj.split('.').slice(0, 2).join('.');
  ok(/^\d+\.\d+\.\d+$/.test(av),
     `the agent's version is WINDOW.BUILD (${av || 'unset'})`);
  ok(win === minor,
     `...and its window is the project's minor: bump one and you bump both (${
       win} against ${minor} from VERSION ${proj})`);
  // The agent's is the only other copy of the window there is. There used
  // to be a second, the CLAUDE.md template's BUILDERBOT:ENV:WINDOW line, and
  // it went with the block itself (R63 step 3): a session's briefing is
  // assembled per session now, so nothing is copied anywhere to fall out of
  // window. tools/version-stamp moves what is left.

  // ---- the sessions are not the agent's unit to kill (B107) --------------
  // systemd's default KillMode takes every process in the unit's cgroup on a
  // stop, and the agent's cgroup holds the ttyds, the tmux servers under
  // them and the Claude sessions inside those, so Update agent ended every
  // conversation on the machine. Read off the provisioner because that is
  // where the unit is written, and a shell file has no other check that
  // would notice the line going away.
  const prov = readFileSync(`${REPO}/nodes/provision-linux.sh`, 'utf8');
  ok(/AGENT_KILLMODE='KillMode=process'/.test(prov)
     && /svc_install builderbot-agent .*"\$AGENT_KILLMODE"/.test(prov),
     'the agent unit is installed with KillMode=process, so a stop does not take the sessions');
  ok(!/svc_install\s+(?!builderbot-agent)\S+.*AGENT_KILLMODE/.test(prov),
     '...and nothing else is: a runner that kept only its main process would orphan a CI job');
  // ...and the agent ends what IS its own, which the new KillMode makes its
  // responsibility: with control-group systemd killed the job children, and
  // a build left running while the controller re-queues it is the one thing
  // that change could have cost.
  ok(/def bye\(\*_\):[\s\S]{0,400}?j\.cancel\(\)[\s\S]{0,1600}?self\.session_stop\(\)/.test(src),
     'the agent cancels its running jobs on SIGTERM, since systemd no longer does it');
}

// ---- a recipe entry naming alternatives -------------------------------------
// A library renamed between releases (libasound2 became libasound2t64) is one
// entry, "new|old": met by whichever is installed, and when neither is, the
// first this machine's repositories carry is the one to install. A list of
// plain names failed the whole apt install on every release but the one it
// was written for. Stubbed: dpkg knows what is installed, apt-cache what the
// repositories carry.
{
  const alt = `${DIR}/altbin`; mkdirSync(alt, { recursive: true });
  const stub = (name, ok) => writeFileSync(`${alt}/${name}`,
    `#!/bin/sh\nfor a; do last="$a"; done\ncase " ${ok} " in *" $last "*) exit 0 ;; esac\nexit 100\n`, { mode: 0o755 });
  const run = (installed, carried) => {
    stub('dpkg', installed); stub('apt-cache', carried);
    return JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json
${LOAD_AGENT}
m = agentpkg.load()
cat = {"toolchains": [{"name": "r", "system": {"apt": ["libnew|libold", "libplain"]}}]}
print(json.dumps(m.sysdeps_missing(cat, "r", "apt", [m.DPKG_BIN, "-s"])[0]))`],
      { encoding: 'utf8', env: { ...process.env, BUILDERBOT_DPKG_BIN: `${alt}/dpkg`,
                                 BUILDERBOT_APT_CACHE_BIN: `${alt}/apt-cache` } }).trim().split('\n').pop());
  };
  const a = run('libold libplain', 'libold libplain');
  const b = run('', 'libold libplain');
  const c = run('', 'libnew libold libplain');
  ok(a.length === 0, `an entry is met by whichever alternative is installed (${JSON.stringify(a)})`);
  ok(JSON.stringify(b) === '["libold","libplain"]',
     `...and when none is, the one this release's repositories carry is installed (${JSON.stringify(b)})`);
  ok(JSON.stringify(c) === '["libnew","libplain"]',
     `...the first of them when it carries both (${JSON.stringify(c)})`);
}

await done(browser);
