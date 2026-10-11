// A node's projects as a synced copy instead of a mounted share (R162): two
// REAL agents, each enrolled and running against the harness server in sync
// mode, holding one project in a directory of their own. A save on one
// reaches the controller's copy and the other node over the agent API alone;
// a change on the controller's copy reaches both; the same file changed on
// both keeps both versions and says so in the bell's poll.
import { URL, ok, done, sleep, DIR } from './lib.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync, openSync, readlinkSync, symlinkSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const api = async (path, body) => {
  const r = await fetch(URL.replace(/\/$/, '') + path, body === undefined
    ? { headers: auth }
    : { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.status === 204 ? {} : r.json();
};
const until = async (fn, ms = 20000, step = 200) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ const v = await fn(); if (v) return v; await sleep(step); }
  return null;
};
const read = p => { try { return readFileSync(p, 'utf8'); } catch { return null; } };
const write = (p, t) => { mkdirSync(p.replace(/\/[^/]+$/, ''), { recursive: true }); writeFileSync(p, t); };
const agentZip = () => execFileSync('python3', ['-c', 'import sys; sys.path.insert(0, sys.argv[1]); '
  + 'from builderbot_agent import bundle; sys.stdout.buffer.write(bundle.build(sys.argv[1]))', `${REPO}/scripts/agent`]);

// The project on the controller's share, made the way New project makes
// one, so the account has it on its list.
const P = 'syncwalk';
const CTL = `${DIR}/ws/${P}`;
const made = await api('/api/create', { name: P, mode: 'init' });
ok(!made.error && existsSync(CTL), `${P} is made (${JSON.stringify(made).slice(0, 80)})`);
write(`${CTL}/a.txt`, 'one\n');
write(`${CTL}/src/b.py`, "print('b')\n");
write(`${CTL}/.git/HEAD`, 'ref: refs/heads/main\n');
write(`${CTL}/node_modules/x/index.js`, 'not synced\n');
symlinkSync('src/b.py', `${CTL}/b-link`);
// Enough files that a request a file would be minutes over a slow link: the
// first copy is one download (R163).
for (let i = 0; i < 1500; i++) write(`${CTL}/many/d${i % 30}/f${i}.txt`, `file ${i}\n`);
const copyStart = Date.now();

const RUN = `${DIR}/wssync-agent/builderbot-agent`;
mkdirSync(`${DIR}/wssync-agent`, { recursive: true });
writeFileSync(RUN, agentZip());
const agents = [];
const nodes = {};
for (const name of ['syncone', 'synctwo']){
  const minted = await api('/api/v1/nodes', { action: 'enroll', name, user: process.env.USER || 'builder' });
  const home = `${DIR}/${name}`;
  mkdirSync(`${home}/workspace`, { recursive: true });
  const env = { ...process.env, BUILDERBOT_NODE_JSON: `${home}/node.json`, BUILDERBOT_SHARE: `${home}/workspace`,
    BUILDERBOT_TTYD_BIN: `${DIR}/no-ttyd`, BUILDERBOT_SESSION_PORT: String(20000 + Math.floor(Math.random() * 20000)),
    BUILDERBOT_SESSION_BIND: '127.0.0.1', BUILDERBOT_IDLE_UNIT: '1',
    PATH: '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' };
  execFileSync('python3', [RUN, 'enroll', '--controller', URL, '--token', minted.token,
    '--user', process.env.USER || 'builder', '--store', `data=${home}/data`, '--store', `toolchains=${home}/tc`],
    { env, encoding: 'utf8', stdio: 'pipe' });
  // A node enrolls holding its projects as a synced copy: the one way (R163).
  const conf = (await api('/api/v1/nodes')).nodes.find(n => n.id === minted.id)?.config || {};
  ok(conf.workspace === 'sync', `${name} holds its projects as a synced copy from enrollment (${JSON.stringify(conf.workspace)})`);
  nodes[name] = { id: minted.id, ws: `${home}/workspace/${P}`, log: `${home}/agent.log` };
  agents.push(spawn('python3', [RUN, 'run'], { env, stdio: ['ignore', openSync(nodes[name].log, 'a'), openSync(nodes[name].log, 'a')] }));
}
const logs = () => Object.entries(nodes).map(([k, n]) => `--- ${k}\n${(read(n.log) || '').split('\n').slice(-15).join('\n')}`).join('\n');
try {
  const bound = await api('/api/prefs', { project: P, node: nodes.syncone.id, nodes: [nodes.synctwo.id] });
  ok(!bound.error, `${P} is bound to both nodes (${JSON.stringify(bound).slice(0, 80)})`);

  // The first copy: the project, less what a node rebuilds for itself.
  const first = await until(() => Object.values(nodes).every(n => read(`${n.ws}/a.txt`) === 'one\n'
    && read(`${n.ws}/src/b.py`) === "print('b')\n" && read(`${n.ws}/.git/HEAD`)) ? true : null, 40000);
  ok(first, `both nodes take a first copy of ${P}: files, .git, and the symlink${first ? '' : '\n' + logs()}`);
  // The files are there as soon as they are unpacked; the copy is done once
  // the agent has hashed them and said so.
  const all = await until(() => Object.values(nodes).every(n => read(`${n.ws}/many/d29/f1499.txt`) === 'file 1499\n'
    && /copied \(\d+ files/.test(read(n.log) || '')), 60000);
  ok(all && Object.values(nodes).every(n => /copied \(\d+ files/.test(read(n.log) || '')
                                          && !/file by file/.test(read(n.log) || '')),
     `...1500 more files with it, in one download each, ${((Date.now() - copyStart) / 1000).toFixed(1)}s from the agents starting${
       Object.values(nodes).map(n => (read(n.log) || '').split('\n').filter(l => /file by file/.test(l)).join(' ')).join(' ')}${all ? '' : '\n' + logs()}`);
  ok(Object.values(nodes).every(n => !existsSync(`${n.ws}/node_modules`) && readlinkSync(`${n.ws}/b-link`) === 'src/b.py'),
     '...without node_modules, and with the link as a link');
  const ready = await until(async () => {
    const rows = (await api('/api/v1/nodes')).nodes.filter(n => [nodes.syncone.id, nodes.synctwo.id].includes(n.id));
    return rows.every(n => n.reported?.sync?.[P]?.ready) ? rows : null;
  }, 40000);
  ok(ready, `each node reports the project ready on its heartbeat (${JSON.stringify(ready?.map(n => n.reported.sync))})`);

  // A save on one node: up to the controller, down to the other.
  const t0 = Date.now();
  write(`${nodes.syncone.ws}/a.txt`, 'from syncone\n');
  write(`${nodes.syncone.ws}/src/new.py`, 'new\n');
  const up = await until(() => read(`${CTL}/a.txt`) === 'from syncone\n' && read(`${CTL}/src/new.py`) === 'new\n');
  const upAt = Date.now() - t0;
  const across = await until(() => read(`${nodes.synctwo.ws}/a.txt`) === 'from syncone\n'
    && read(`${nodes.synctwo.ws}/src/new.py`) === 'new\n');
  ok(up && across, `a save on syncone reaches the controller in ${(upAt / 1000).toFixed(1)}s and synctwo in ${
    ((Date.now() - t0) / 1000).toFixed(1)}s${up && across ? '' : '\n' + logs()}`);

  // A change on the controller's copy (VS Code, or the share itself).
  write(`${CTL}/a.txt`, 'from the controller\n');
  const down = await until(() => Object.values(nodes).every(n => read(`${n.ws}/a.txt`) === 'from the controller\n'), 30000);
  ok(down, `a change on the controller's copy reaches both nodes${down ? '' : '\n' + logs()}`);

  // A relayed verb, run by a session's bb on the node: what was saved here a
  // moment ago is on the controller's copy before the verb runs there, and
  // what the verb wrote there is on this copy when bb returns (R163 step 2).
  {
    const relay = args => execFileSync('python3', [`${REPO}/scripts/lib/relay.py`,
      'Basic ' + Buffer.from('test:test').toString('base64'), ...args],
      { cwd: nodes.syncone.ws, encoding: 'utf8', stdio: 'pipe', timeout: 120000,
        env: { ...process.env, BB_CONTROLLER: URL.replace(/\/$/, ''), BB_RELAY_PROJECT: P,
               WORKSPACE: `${DIR}/syncone/workspace` } });
    write(`${nodes.syncone.ws}/notes.txt`, 'saved a moment ago\n');
    const t = Date.now();
    let said = '';
    try { said = relay(['changelog', 'add', 'Synced from a node.', '--cat', 'Added']); }
    catch (e) { said = String(e.stdout || '') + String(e.stderr || ''); }
    const took = Date.now() - t;
    ok(read(`${CTL}/notes.txt`) === 'saved a moment ago\n',
       `a save made just before a relayed verb is on the controller's copy before the verb (${took}ms; ${said.trim().slice(0, 80)})`);
    ok(/Synced from a node/.test(read(`${nodes.syncone.ws}/CHANGELOG.md`) || ''),
       '...and what the verb wrote there is on the node\'s copy when bb returns');
    ok(existsSync(`${nodes.syncone.ws}/.git/.bbsync-state`) && !existsSync(`${CTL}/.git/.bbsync-state`),
       '...which bb reads from the state the agent keeps in the copy, a file that never syncs');
  }

  // A project the synced one reads comes down too, read-only (R163 step 3).
  {
    const R = 'syncread';
    const made2 = await api('/api/create', { name: R, mode: 'init' });
    write(`${DIR}/ws/${R}/shared.txt`, 'read me\n');
    const set = await api('/api/prefs', { project: P, reads: [R] });
    const at = n => `${DIR}/${n}/workspace/${R}/shared.txt`;
    const came = await until(() => Object.keys(nodes).every(n => read(at(n)) === 'read me\n'), 60000);
    ok(!made2.error && !set.error && came,
       `a project ${P} reads comes down to both nodes (${JSON.stringify(set).slice(0, 60)})${came ? '' : '\n' + logs()}`);
    write(at('syncone'), 'changed on a node\n');
    write(`${DIR}/ws/${R}/shared.txt`, 'changed on the controller\n');
    const back = await until(() => Object.keys(nodes).every(n => read(at(n)) === 'changed on the controller\n'), 30000);
    ok(back && read(`${DIR}/ws/${R}/shared.txt`) === 'changed on the controller\n',
       '...read-only: a change there on a node never goes up, and the controller\'s comes down to both');
  }

  // A deletion travels too.
  execFileSync('rm', [`${nodes.synctwo.ws}/src/new.py`]);
  const gone = await until(() => !existsSync(`${CTL}/src/new.py`) && !existsSync(`${nodes.syncone.ws}/src/new.py`));
  ok(gone, 'a file deleted on one node is deleted on the controller and the other node');

  // The same file on both nodes at once: one wins, the other is kept beside
  // it, everywhere, and the bell's poll lists it.
  write(`${nodes.syncone.ws}/c.txt`, 'base\n');
  await until(() => read(`${nodes.synctwo.ws}/c.txt`) === 'base\n');
  write(`${nodes.syncone.ws}/c.txt`, 'one wins?\n');
  write(`${nodes.synctwo.ws}/c.txt`, 'two wins?\n');
  const settled = await until(() => {
    const kept = readdirSync(CTL).filter(f => f.startsWith('c.conflict-'));
    const main = read(`${CTL}/c.txt`);
    return kept.length === 1 && Object.values(nodes).every(n => read(`${n.ws}/c.txt`) === main
      && read(`${n.ws}/${kept[0]}`) === read(`${CTL}/${kept[0]}`)) ? { kept: kept[0], main } : null;
  }, 30000);
  ok(settled && settled.main !== read(`${CTL}/${settled.kept}`),
     `the same file changed on both nodes: one version stays, the other is kept as ${settled?.kept}, on every copy${settled ? '' : '\n' + logs()}`);
  const st = await api('/api/status');
  ok((st.sync_conflicts || []).some(c => c.project === P && c.path === 'c.txt' && c.kept_as === settled?.kept),
     `...and the bell's poll lists it (${JSON.stringify(st.sync_conflicts).slice(0, 160)})`);
  execFileSync('rm', [`${CTL}/${settled?.kept}`]);
  ok(!((await api('/api/status')).sync_conflicts || []).some(c => c.kept_as === settled?.kept),
     '...until the copy kept beside it is deleted');

} finally {
  for (const a of agents) a.kill('SIGTERM');
}
await done();
