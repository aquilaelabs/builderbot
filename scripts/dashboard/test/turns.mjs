// How many Claude sessions on one node work on a prompt at once (turns.py):
// the rule on its own, then through the server the way a session's hooks
// reach it, then bb-gate itself holding a prompt and letting it go, then the
// Nodes tab where an administrator sets the number. The node is one this file
// enrolls, with the session half up and a heartbeat whose panes carry the
// spinner a working Claude pane does; the per-file world takes it away after.
import { URL, launch, newPage, ok, done, ready, sleep, DIR, openSection, member } from './lib.mjs';
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const base = URL.replace(/\/$/, '');
const HERE = new globalThis.URL('..', import.meta.url).pathname;
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
                'Content-Type': 'application/json' };
const call = async (path, body, headers = ADMIN) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  const t = await r.text();
  let j = {}; try { j = JSON.parse(t); } catch { /* 204 and friends */ }
  return { status: r.status, ...j };
};
const bearer = t => ({ Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' });
const py = (mod, code) => execFileSync('python3', ['-c', `
import importlib.util, json, time
spec = importlib.util.spec_from_file_location("m", ${JSON.stringify(join(HERE, mod))})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
if hasattr(m, "configure") and ${JSON.stringify(mod)} == "users.py":
    m.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' }).trim().split('\n').pop();

// ---- the rule on its own --------------------------------------------------
{
  const r = JSON.parse(py('turns.py', `
out = {}
now = time.time()
# No limit: everything goes, and nothing is queued.
out["free"] = [m.ask("n", k, 0, set(), now)["go"] for k in "abc"]
for k in "abc": m.done("n", k)
# A limit of two: two go, the third and fourth wait in the order they asked.
a, b = m.ask("n", "a", 2, set(), now), m.ask("n", "b", 2, set(), now)
c = m.ask("n", "c", 2, set(), now); time.sleep(0.01); d = m.ask("n", "d", 2, set(), now)
out["two"] = [a["go"], b["go"], c["go"], d["go"], c["ahead"], d["ahead"]]
# One turn ends: the slot is the one who waited longest's, not whoever asks first.
m.done("n", "a")
d2 = m.ask("n", "d", 2, set(), now); c2 = m.ask("n", "c", 2, set(), now)
out["order"] = [d2["go"], c2["go"]]
# The heartbeat: a pane it shows working counts, and one that said it stopped
# after the heartbeat was taken does not.
for k in "bcd": m.done("n", k)
out["heart"] = [len(m.state("n", {"x"}, time.time())["working"]),
                len(m.state("n", {"b"}, now)["working"])]
# A claim the heartbeat has seen through (a sample well after it, no spinner)
# is dropped: the session was killed, or interrupted, and never said.
m._claims[("n", "old")] = time.time() - m.CLAIM_GRACE - 30
out["seen_through"] = "old" in m.state("n", set(), time.time())["working"]
# ...but one the heartbeat has not had time to see stays counted.
m._claims[("n", "new")] = time.time()
out["young"] = "new" in m.state("n", set(), time.time() - 5)["working"]
# A waiter that stops asking leaves the queue.
m.done("n", "new")
m.ask("n", "p", 1, set(), now); m.ask("n", "q", 1, set(), now)
m._waiting[("n", "q")][1] -= m.WAIT_STALE + 1
out["stale"] = m.state("n", set(), time.time())["waiting"]
# Another node's sessions are not this one's.
out["other"] = m.ask("m", "z", 1, set(), now)["go"]
out["limits"] = [m.limit_of(x) for x in (0, 3, "5", 64, 65, -1, "x", None)]
print(json.dumps(out))`));
  ok(r.free.every(Boolean), 'with no limit every prompt goes');
  ok(JSON.stringify(r.two) === '[true,true,false,false,0,1]',
     `with a limit of two, two go and the next two wait in the order they asked (${r.two})`);
  ok(JSON.stringify(r.order) === '[false,true]',
     `a freed turn goes to whoever waited longest, not whoever asks first (${r.order})`);
  ok(JSON.stringify(r.heart) === '[1,0]',
     `a pane the heartbeat shows working counts, unless it said it stopped since (${r.heart})`);
  ok(r.seen_through === false && r.young === true,
     'a claim the heartbeat has seen through is dropped; one it has not had time to see is kept');
  ok(r.stale === 0, 'a waiter that stops asking leaves the queue');
  ok(r.other === true, "another node's sessions do not count against this one");
  ok(JSON.stringify(r.limits) === '[0,3,5,64,null,null,null,null]',
     `a limit is a whole number from 0 to 64 (${r.limits})`);
}

// ---- through the server ---------------------------------------------------
// A node of this file's own, running sessions, bound to alpha; four people on
// alpha, each with a session token as their node-bound terminal carries.
const shipped = (await call('/api/v1/nodes')).agent || {};
const minted = await call('/api/v1/nodes', { action: 'enroll', name: 'turnbox' });
const CENSUS = { cpu: 4, mem_mb: 8192, arch: 'x86_64', system: 'linux',
                 session: { up: true, port: 7690, ro_port: 7691, user: 'builder', workspace: true,
                            writable: true, claude: '2.1.0', boot: 'b1' } };
const en = await call('/api/v1/agent/enroll', { census: CENSUS, version: shipped.version,
  digest: shipped.digest, user: 'bb' }, bearer(minted.token));
ok(en.ok && en.node_id === minted.id, 'a node that runs sessions enrolled');
// ...with each project's synced copy there (R163), as an agent says.
const beat = sessions => call('/api/v1/agent/work', { sample: { cpu_pct: 1, mem_mb: 8192,
  mem_used_mb: 512, sessions, sync: { alpha: { ready: true, rev: 1 }, beta: { ready: true, rev: 1 }, gamma: { ready: true, rev: 1 }, delta: { ready: true, rev: 1 } } }, running: 0, wait: 0 }, bearer(en.token));
await beat([]);
await call('/api/prefs', { project: 'alpha', node: minted.id });

const make = name => py('users.py', `
d = m.load(); uid = m.mint_uid()
d["users"]["${name}"] = {"uid": uid, "role": "user", "projects": ["alpha"],
    "prefs": {"full_name": "${name}", "email": "${name}@example.invalid"},
    "password": m.hash_password("pw-${name}-1"), "created": 0, "seen": 0}
m._save(d); print(uid)`);
const owner = py('users.py', 'print(next(r["uid"] for r in m.load()["users"].values() if r.get("role") == "owner"))');
const uids = [owner, make('tn.one'), make('tn.two'), make('tn.three')];
await member('tn.one', 'tn.two', 'tn.three');
const toks = uids.map(u => py('users.py', `print(m.mint_session("alpha", uid=${JSON.stringify(u)}))`));
const hook = (i, kind) => call('/api/v1/hook', { kind }, bearer(toks[i]));

// A session told the controller moved (R83): the build it began on is
// kept per session at `started`, and the first `seen` after the build has
// changed carries one line naming both and where to read, once.
{
  const sess = body => call('/api/v1/hook', { kind: 'seen', ...body }, bearer(toks[1]));
  const began = await call('/api/v1/hook', { kind: 'started', node: 'nodeA' }, bearer(toks[1]));
  const quiet = await sess({ node: 'nodeA' });
  ok(began.ok && quiet.ok && !/controller moved/.test(quiet.line || ''),
     `a session that began on this build hears nothing about it (${quiet.line || 'no line'})`);
  const f = `${DIR}/state/session-seen.json`;
  const d = JSON.parse(readFileSync(f, 'utf8'));
  const key = Object.keys(d).find(k => k.endsWith('|nodeA'));
  d[key].build = '0.3.9-dev.1+oldrev1';
  writeFileSync(f, JSON.stringify(d));
  const moved = await sess({ node: 'nodeA' });
  ok(/The controller moved to 0\.4\.0-dev\.390\+abc1234 since this session began \(it was on 0\.3\.9-dev\.1\+oldrev1\)/.test(moved.line || '')
     && /bb catchup/.test(moved.line) && /bb preamble/.test(moved.line),
     `...and once the build has moved, the next prompt says so, naming both builds and where to read (${(moved.line || '').slice(0, 80)})`);
  const again = await sess({ node: 'nodeA' });
  ok(!/controller moved/.test(again.line || ''), '...once: the prompt after it says nothing more');
  // ...and the notebook and the settings the same way: what somebody else
  // changed on this project since the last prompt is named with the verb
  // that reads it, and the session's own writes are not, being seen as
  // they land (the operator, 25 Sep).
  await call('/api/bugs', { project: 'alpha', action: 'add', title: 'the operator found one', severity: 'low' });
  const nb = await sess({ node: 'nodeA' });
  ok(/somebody else changed this project's bugs: read `bb bug`/.test(nb.line || ''),
     `a bug the operator filed is named on the next prompt (${(nb.line || 'no line').slice(0, 90)})`);
  await call('/api/bugs', { project: 'alpha', action: 'add', title: 'the session found one', severity: 'low' }, bearer(toks[1]));
  const own = await sess({ node: 'nodeA' });
  ok(!/somebody else changed/.test(own.line || ''), `...and the session's own bug is not (${(own.line || 'no line').slice(0, 90)})`);
  // ...nor one it filed with bb bug add, which reaches the controller
  // through the relay and not the notebook's route, and was told back to
  // the session that filed it as somebody else's (B375). A read through
  // the relay marks nothing: what the operator did is still news after it.
  const relay = argv => call('/api/v1/bb', { argv }, bearer(toks[1]));
  const filed = await relay(['bug', 'add', 'the session found another', '--sev', 'low', '--here']);
  const ownRelay = await sess({ node: 'nodeA' });
  ok(/filed B\d+/.test(filed.out || '') && !/somebody else changed/.test(ownRelay.line || ''),
     `...nor one it filed with bb bug add (${(filed.out || filed.error || '').trim().slice(0, 40)}; ${(ownRelay.line || 'no line').slice(0, 60)})`);
  await call('/api/bugs', { project: 'alpha', action: 'add', title: 'the operator found a second', severity: 'low' });
  await relay(['bug']);
  const afterRead = await sess({ node: 'nodeA' });
  ok(/somebody else changed this project's bugs/.test(afterRead.line || ''),
     `...while a read of the list by the session hides nothing the operator did (${(afterRead.line || 'no line').slice(0, 90)})`);
  await call('/api/prefs', { project: 'alpha', build: 'make it' });
  const st = await sess({ node: 'nodeA' });
  ok(/somebody else changed this project's settings: read `bb settings`/.test(st.line || ''),
     `a setting the operator changed is named too (${(st.line || 'no line').slice(0, 90)})`);
  await call('/api/prefs', { project: 'alpha', build: '' });
  await sess({ node: 'nodeA' });
  // A setting a session takes when it starts says so, once (report #81).
  await call('/api/prefs', { project: 'alpha', reads: ['beta'] });
  const rd = await sess({ node: 'nodeA' });
  ok(/This project's Reads changed since this session started, and a session takes those when it starts: end it and start a new one/.test(rd.line || ''),
     `a change to Reads says a new session is needed for it (${(rd.line || 'no line').slice(0, 120)})`);
  const rd2 = await sess({ node: 'nodeA' });
  ok(!/since this session started/.test(rd2.line || ''), `...once, not on every prompt after (${(rd2.line || 'no line').slice(0, 80)})`);
  await call('/api/prefs', { project: 'alpha', reads: [] });
  await sess({ node: 'nodeA' });
  // Memories: an edit through the notebook by somebody else is news; the
  // session's own, through the API or its own memory tool on the files,
  // is not, since the half counts notebook edits rather than mtimes (B269).
  await call('/api/memory', { project: 'alpha', action: 'create', name: 'op-note', title: 'the operator wrote one', hook: 'h', type: 'project', body: 'x' });
  const mem = await sess({ node: 'nodeA' });
  ok(/somebody else changed this project's memories: read the notebook's Memory view/.test(mem.line || ''),
     `a memory the operator wrote is named on the next prompt (${(mem.line || 'no line').slice(0, 90)})`);
  await call('/api/memory', { project: 'alpha', action: 'create', name: 'own-note', title: 'the session wrote one', hook: 'h', type: 'project', body: 'x' }, bearer(toks[1]));
  const ownMem = await sess({ node: 'nodeA' });
  ok(!/memories/.test(ownMem.line || ''), `...and the session's own is not (${(ownMem.line || 'no line').slice(0, 90)})`);
  // ...and a person only READING the log is no edit: the history is a POST
  // like the writes, and it was counted as one (B296).
  await call('/api/memory', { project: 'alpha', action: 'history', limit: 5 });
  const histRead = await sess({ node: 'nodeA' });
  ok(!/memories/.test(histRead.line || ''),
     `...nor a person reading the memory history (${(histRead.line || 'no line').slice(0, 90)})`);
  // New diagnostics reports, for a project whose house rule asks its
  // sessions to watch them (watch-diagnostics, the operator, 6 Oct): named
  // once, on the next prompt, only to a project that carries the rule, and
  // only where reading them is allowed: debug mode on, the project granted
  // the diagnostics, an account with the debug grant (the owner here). It
  // named report #68 to a session refused reading it, the same evening.
  const rep = text => call('/api/reports', { action: 'add', text });
  const asOwner = body => call('/api/v1/hook', { kind: 'seen', ...body }, bearer(toks[0]));
  await rep('the first report');
  const noRule = await asOwner({ node: 'nodeA' });
  ok(!/diagnostics/.test(noRule.line || ''), `a project without the rule hears nothing of reports (${(noRule.line || 'no line').slice(0, 60)})`);
  await relay(['rules', 'add', 'watch-diagnostics', 'After each prompt, read bb diag reports for new ones.']);
  await rep('a report while the project may not read them');
  const ungranted = await asOwner({ node: 'nodeA' });
  ok(!/diagnostics/.test(ungranted.line || ''),
     `with the rule but no grant, the notice names nothing (${(ungranted.line || 'no line').slice(0, 60)})`);
  await call('/api/settings', { set: { debug_mode: true } });
  await call('/api/prefs', { project: 'alpha', diag: true });
  await asOwner({ node: 'nodeA' });
  const r2 = await rep('the second report');
  const told = await asOwner({ node: 'nodeA' });
  ok(new RegExp(`report #${r2.id} from the dashboard`).test(told.line || '') && /bb diag reports/.test(told.line || ''),
     `with the rule and the grant, a new report is named on the next prompt (${(told.line || 'no line').slice(0, 100)})`);
  const once = await asOwner({ node: 'nodeA' });
  ok(!/diagnostics/.test(once.line || ''), `...once (${(once.line || 'no line').slice(0, 60)})`);
  await rep('a third report');
  const plain = await sess({ node: 'nodeA' });
  ok(!/diagnostics/.test(plain.line || ''),
     `...and a plain account's session on the same project is told nothing (${(plain.line || 'no line').slice(0, 60)})`);
  await call('/api/prefs', { project: 'alpha', diag: false });
  await call('/api/settings', { set: { debug_mode: false } });
}

{
  const free = await Promise.all([0, 1, 2, 3].map(i => hook(i, 'turn')));
  ok(free.every(r => r.status === 200 && r.go === true), 'with no limit set, four prompts at once all go');
  await Promise.all([0, 1, 2, 3].map(i => hook(i, 'turn-done')));

  // Refused to anybody but an administrator, and to a session outright.
  let r = await call('/api/v1/nodes', { action: 'turns', id: minted.id, limit: 1 }, bearer(toks[1]));
  ok(r.status === 403, `a session cannot set its own node's limit (${r.status})`);
  r = await call('/api/v1/nodes', { action: 'reboot', id: minted.id }, bearer(toks[1]));
  ok(r.status === 403, `...nor reboot or shut down the machine it runs on (${r.status})`);
  // A job is canceled by somebody whose project it is (the review of 26
  // Sep): a session's token for alpha cannot end beta's job, an
  // administrator can, and the code for the controller's own Claude sign-in
  // is not a session's to type.
  await call('/api/prefs', { project: 'beta', node: minted.id });
  const bj = await call('/api/v1/jobs', { action: 'run', project: 'beta', argv: ['true'] });
  ok(bj.ok && /^j_/.test(bj.job || ''), `a job on another project is queued for the check (${bj.job || bj.error})`);
  r = await call('/api/v1/jobs', { action: 'cancel', id: bj.job }, bearer(toks[1]));
  ok(r.status === 403 && /no such job of yours/.test(r.error || ''), `a session cannot cancel another project's job (${r.status}: ${r.error})`);
  r = await call('/api/v1/jobs', { action: 'cancel', id: bj.job });
  ok(r.ok === true || r.status === 200, `...while an administrator can (${JSON.stringify(r).slice(0, 60)})`);
  await call('/api/prefs', { project: 'beta', node: '' });
  r = await call('/api/login-code', { code: 'abc#def' }, bearer(toks[1]));
  ok(r.status === 403, `a session cannot type a code into the controller's sign-in (${r.status})`);
  r = await call('/api/v1/nodes', { action: 'turns', id: minted.id, limit: 1 },
    { Authorization: 'Basic ' + Buffer.from('tn.one:pw-tn.one-1').toString('base64'), 'Content-Type': 'application/json' });
  ok(r.status === 403, `...nor can a plain account (${r.status})`);
  r = await call('/api/v1/nodes', { action: 'turns', id: minted.id, limit: 'lots' });
  ok(/whole number/.test(r.error || ''), `a limit that is not a number is refused, saying what one is (${r.error})`);
  r = await call('/api/v1/nodes', { action: 'turns', id: minted.id, limit: 2 });
  ok(r.ok && r.limit === 2, 'an administrator sets it to two');

  const first = await Promise.all([0, 1].map(i => hook(i, 'turn')));
  const third = await hook(2, 'turn');
  await sleep(20);
  const fourth = await hook(3, 'turn');
  ok(first.every(x => x.go) && third.go === false && fourth.go === false,
     'two prompts go and the next two wait');
  ok(third.ahead === 0 && fourth.ahead === 1 && third.node === 'turnbox' && third.limit === 2
     && third.working.length === 2,
     `...each told its place, the node and who is working (${third.ahead}, ${fourth.ahead}, ${third.node})`);
  const row = (await call('/api/v1/nodes')).nodes.find(n => n.id === minted.id);
  ok(row?.turns?.working === 2 && row.turns.waiting === 2 && row.turns.limit === 2,
     `the node's row says two working of two and two waiting (${JSON.stringify(row?.turns)})`);
  await hook(0, 'turn-done');
  const jump = await hook(3, 'turn');
  const next = await hook(2, 'turn');
  ok(jump.go === false && next.go === true,
     'when one turn ends, the one who waited longest goes, and the later one keeps waiting');

  // The heartbeat: a session that is working without having asked (its
  // settings predate the hook) still counts, by its pane's spinner.
  await Promise.all([1, 2].map(i => hook(i, 'turn-done')));
  // A heartbeat is stamped in whole seconds, and one from the same second as
  // a session saying it stopped is read as older than that: as it should be.
  await sleep(1100);
  await beat([{ name: `${uids[0]}~claude-alpha`, title: '◐ Refactor the parser' },
              { name: `${uids[1]}~claude-alpha`, title: '◓ Fix the tests' }]);
  const held = await hook(3, 'turn');
  ok(held.go === false && held.working.length === 2,
     `two panes the heartbeat shows working hold a third prompt back (${held.working.length})`);
  await beat([{ name: `${uids[0]}~claude-alpha`, title: '✳ Refactor the parser' },
              { name: `${uids[1]}~claude-alpha`, title: '◓ Fix the tests' }]);
  const goes = await hook(3, 'turn');
  ok(goes.go === true, '...and it goes once a pane is waiting at its prompt again');
  await hook(3, 'turn-done');
  await beat([]);
}

// ---- a session on Claude Code's own permission prompt (B52) -----------------
// Its pane title reads as waiting, like an idle one; the Notification hook
// (bb-gate --asking, fed Claude Code's JSON) marks it asking, with Claude's
// words, until its turn ends.
{
  const name = `${uids[0]}~claude-alpha`;
  await beat([{ name, title: '✳ Refactor the parser' }]);
  const rowOf = async () => ((await call('/api/status')).sessions || [])
    .find(s => s.node_name === name || s.name === name)?.claude || {};
  const before = await rowOf();
  const said = execFileSync('python3', [join(HERE, 'bb-gate'), '--asking', 'alpha', uids[0]],
    { encoding: 'utf8', input: JSON.stringify({ hook_event_name: 'Notification', message: 'Claude needs your permission to use Bash' }),
      env: { ...process.env, BB_CONTROLLER: base, BB_TOKEN: toks[0], BB_ACCOUNT_UID: uids[0], BUILDERBOT_ROLE: 'node' } });
  const asking = await rowOf();
  await hook(0, 'turn-done');
  const after = await rowOf();
  ok(before.state === 'waiting' && said.trim() === '' && asking.state === 'asking'
     && /needs your permission to use Bash/.test(asking.task || '') && after.state === 'waiting',
     `a session on its permission prompt reads as asking, with Claude's words, until its turn ends (${before.state}, ${asking.state}: ${asking.task}, ${after.state})`);
  await beat([]);
}

// ---- bb-gate, the hook itself ----------------------------------------------
// The limit at one and somebody working: the prompt waits, and is refused
// with a sentence when its wait runs out; given a longer wait, it goes the
// moment the other turn ends.
{
  await call('/api/v1/nodes', { action: 'turns', id: minted.id, limit: 1 });
  await hook(0, 'turn');
  const cache = join(DIR, 'turncache'); mkdirSync(cache, { recursive: true });
  const env = { ...process.env, BB_CONTROLLER: base, BB_TOKEN: toks[1], BB_ACCOUNT_UID: uids[1],
                XDG_CACHE_HOME: cache, BUILDERBOT_ROLE: 'node' };
  const gate = ['--turn', 'alpha', uids[1]];
  const t0 = Date.now();
  let out;
  try {
    // Five, not less: the gate asks every four seconds (ASK_EVERY), so a
    // shorter wait is no wait at all and the check below has nothing to time.
    execFileSync('python3', [join(HERE, 'bb-gate'), ...gate, '--wait', '5'],
      { input: '{"prompt":"go"}', encoding: 'utf8', env, stdio: ['pipe', 'pipe', 'pipe'] });
    out = { code: 0, err: '' };
  } catch (e) { out = { code: e.status, err: String(e.stderr) }; }
  ok(out.code === 2 && /turnbox lets 1 Claude session work at once/.test(out.err)
     && /waited 5 seconds/.test(out.err) && Date.now() - t0 >= 4000,
     `a prompt that waits out its time is refused, naming the node and the limit (${out.code}: ${out.err.trim().slice(0, 70)})`);
  const after = (await call('/api/v1/nodes')).nodes.find(n => n.id === minted.id);
  ok(after.turns.waiting === 0, '...and gives up its place in the queue when it does');

  const child = spawn('python3', [join(HERE, 'bb-gate'), ...gate, '--wait', '60'], { env, stdio: ['pipe', 'pipe', 'pipe'] });
  child.stdin.end('{"prompt":"go"}');
  const ended = new Promise(res => child.on('exit', code => res({ code, at: Date.now() })));
  // Until the queue holds it, rather than a fixed two and a half seconds.
  let waiting = 0;
  for (let i = 0; i < 50 && !waiting; i++){
    waiting = (await call('/api/v1/nodes')).nodes.find(n => n.id === minted.id).turns.waiting;
    if (!waiting) await sleep(100);
  }
  const freed = Date.now();
  await hook(0, 'turn-done');
  const e = await Promise.race([ended, sleep(15000).then(() => ({ code: 'still waiting' }))]);
  ok(waiting === 1 && e.code === 0 && e.at - freed < 8000,
     `a waiting prompt goes within seconds of a turn ending (${waiting} waiting, exit ${e.code}, ${e.at ? e.at - freed : '?'}ms)`);
  const done2 = execFileSync('python3', [join(HERE, 'bb-gate'), '--turn-done', 'alpha', uids[1]],
    { input: '{}', encoding: 'utf8', env, stdio: ['pipe', 'pipe', 'pipe'] });
  const clear = (await call('/api/v1/nodes')).nodes.find(n => n.id === minted.id).turns;
  ok(done2.trim() === '' && clear.working === 0, `--turn-done on Stop hands it back, silently (${clear.working} working)`);
  const gone = spawn('python3', [join(HERE, 'bb-gate'), ...gate, '--wait', '60'],
    { env: { ...env, BB_CONTROLLER: 'http://127.0.0.1:1' }, stdio: ['pipe', 'pipe', 'pipe'] });
  gone.stdin.end('{"prompt":"go"}');
  const g = await Promise.race([new Promise(res => gone.on('exit', res)), sleep(15000).then(() => 'hung')]);
  ok(g === 0, `a controller that does not answer never holds a prompt (${g})`);
}

// ---- the Nodes tab --------------------------------------------------------
{
  const browser = await launch();
  const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
  await page.goto(URL); await ready(page);
  await call('/api/v1/nodes', { action: 'turns', id: minted.id, limit: 0 });
  await page.evaluate(() => { nodesList = null; openNodesTab(); });
  await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
  await page.selectOption('.nodestab #ndPick', minted.id);
  const row = `.nodestab .ndrow[data-node="${minted.id}"]`;
  await page.waitForSelector(row, { timeout: 10000 });
  const inp = `${row} [data-k="turns"]`;
  await page.waitForSelector(inp, { state: 'attached', timeout: 10000 });
  await openSection(page, 'nodes:sessions', row);
  const line = async () => page.$eval(`${row} [data-nd="sess-save"]`, b => b.parentElement.querySelector('.state').textContent.trim());
  ok(/^0 working now$/.test(await line()), `the Sessions section says what is working now (${await line()})`);
  await page.fill(inp, '3');
  // A heartbeat repaints the tab; the number being typed survives it.
  await beat([{ name: `${uids[0]}~claude-alpha`, title: '◐ Work' }]);
  await page.evaluate(() => loadNodes()); await sleep(300);
  ok(await page.$eval(inp, el => el.value) === '3', '...and a number being typed survives the repaint a heartbeat brings');
  await page.click(`${row} [data-nd="sess-save"]`);
  await page.waitForFunction(r => /of 3/.test(document.querySelector(`${r} [data-nd="sess-save"]`)
    ?.parentElement.querySelector('.state')?.textContent || ''), row, { timeout: 10000 });
  ok(/^1 working now of 3$/.test(await line()), `Save sets it, and the line counts against it (${await line()})`);
  const rec = (await call('/api/v1/nodes')).nodes.find(n => n.id === minted.id);
  ok(rec.config?.turns === 3, 'the limit is on the node\'s record');
  ok(page.errors.length === 0, `no console errors${page.errors.length ? ': ' + page.errors.slice(0, 2).join(' | ') : ''}`);
  await browser.close();
}

await done();
