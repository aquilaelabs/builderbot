// One command as root on a node (roadmap R38): the phone's shape applied to
// root. A session asks with a reason and the exact command; the request
// waits on the administrators (on the Nodes tab and in the bell, nobody
// else's), and Allow runs that one command on the node as a system job,
// Deny says no. Not sudo, and not a fake one.
//
// The harness's sandbox node runs agent-stub.py, whose census says sandbox
// and whose system job runs the allowed command as the suite's own user:
// this file proves the asking, the routing and the answering; the real
// agent's own file proves the running and the guest-node refusal.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync, rmSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const base = URL.replace(/\/$/, '');
const asUser = (u, pw) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${pw}`).toString('base64'),
                             'Content-Type': 'application/json' });
const owner = asUser('test', 'test');
const api = async (path, body, headers = owner) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

const sandbox = (await api('/api/v1/nodes')).body.nodes.find(n => n.name === 'sandbox');
ok(sandbox && sandbox.reported?.sandbox === true,
   'the fixture node reports itself provisioned as a sandbox, which is what makes root there askable');
await api('/api/prefs', { project: 'alpha', node: sandbox.id });

// ---- what is refused before anybody is asked -------------------------------
ok((await api('/api/phone', { action: 'ask', kind: 'root', why: '', cmd: ['id'], project: 'alpha' })).body.error,
   'a root ask with no reason is refused: Allow on an unexplained root command is a guess');
ok(/has no node/.test((await api('/api/phone', { action: 'ask', kind: 'root', why: 'look', cmd: ['id'], project: 'beta' })).body.error || ''),
   'a project with no node has no machine to ask for root on, and is told so');
ok((await api('/api/phone', { action: 'ask', kind: 'root', why: 'look', cmd: [], project: 'alpha' })).body.error,
   '...and an ask with nothing to run is refused');
ok(/empty argument/.test((await api('/api/phone', { action: 'ask', kind: 'root', why: 'look', cmd: ['mv', 'a', ''], project: 'alpha' })).body.error || ''),
   '...and one with an empty argument, which the node would drop: the command shown must be the command run');

// ---- a second account, of the kind that is not asked ---------------------------
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'visitor', '--role', 'user'],
  { input: 'visitorpass1\nvisitorpass1\n', encoding: 'utf8',
    env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const other = asUser('visitor', 'visitorpass1');
await api('/api/users', { action: 'projects', name: 'visitor', projects: ['alpha'] });

// ---- the ask, and who sees it ------------------------------------------------
const asked = await api('/api/phone', { action: 'ask', kind: 'root', why: 'load the binder module for the emulator',
                                        cmd: ['sh', '-c', 'echo root-ran-here; id -un'], project: 'alpha' });
ok(asked.body.id > 0 && /test.*your own account/.test(asked.body.to || ''),
   `an administrator's own ask goes to that administrator, and says so (${asked.body.to})`);
ok((await api('/api/phone', undefined, other)).body.asks.filter(a => a.kind === 'root').length === 0,
   'a user account is not asked: a root request waits on administrators alone');
ok((await api('/api/phone')).body.asks.some(a => a.id === asked.body.id && a.kind === 'root' && a.asker === 'test'),
   '...and the administrator is, with the request marked as a root one and naming whose session asked');
// A second administrator is not asked about the first one's own request:
// the answer is routed to the session that asked, when it can be.
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'ops', '--role', 'admin'],
  { input: 'opspassword1\nopspassword1\n', encoding: 'utf8',
    env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const ops = asUser('ops', 'opspassword1');
ok(!(await api('/api/phone', undefined, ops)).body.asks.some(a => a.id === asked.body.id),
   "another administrator is not asked about an administrator's own request: it went to the session that asked");
ok((await api('/api/phone', { action: 'allow', id: asked.body.id }, other)).body.error,
   '...and the user cannot answer it, either way');
ok((await api('/api/phone', { action: 'outcome', id: asked.body.id }, other)).status === 403,
   "...nor read its outcome by id: a root command's output on a shared machine is not a user's to browse");

// ---- where it shows: the Nodes tab and the bell --------------------------------
await page.evaluate(() => openNodesTab());
await page.evaluate(() => phFetch());
await page.waitForSelector('.ndask', { timeout: 15000 });
const askText = await page.$eval('.ndask', e => e.textContent);
ok(/load the binder module/.test(askText) && /alpha asks to run this as root on sandbox/.test(askText)
   && /echo root-ran-here/.test(askText) && /left to answer/.test(askText),
   'the Nodes page shows the request above the node: the reason, the exact command, whose it is, and how long is left');
ok(await page.$('.phask') === null, '...and the Phone page is not where it goes');
await page.waitForFunction(
  () => { const d = document.querySelector('#bBell .dot');
          return d && !d.hidden && d.classList.contains('ask'); }, null, { timeout: 15000 });
await page.click('#bBell');
await page.waitForSelector('#bellPanel .bnote.ask', { timeout: 10000 });
const bell = await page.$eval('#bellPanel .bnote.ask', e => e.textContent);
ok(/root on sandbox/.test(bell) && /echo root-ran-here/.test(bell)
   && await page.$eval('#bellPanel .bnote.ask', e => e.classList.contains('bad')),
   'the bell carries it in red, naming the machine and that it is root there');
await page.keyboard.press('Escape');
await page.waitForFunction(() => document.getElementById('bellPanel').hidden);

// ---- Allow runs that one command on the node, and the session gets the output ------
// The ask leaves the list the moment it is answered, not when the command
// it allowed has finished running (B641): read in the same turn as the
// press, before the request it sent could have come back.
const immediate = await page.evaluate(() => {
  document.querySelector('.ndask [data-rallow]').click();
  return !(ph?.asks || []).some(a => a.kind === 'root');
});
ok(immediate, 'Allow takes the ask off the list in the same moment, before the command it allowed has run');
await page.waitForFunction(() => !document.querySelector('.ndask'), null, { timeout: 30000 });
// Allow answers at once and the command runs on a thread, so the outcome is
// polled the way the session polls it.
let out;
for (let i = 0; i < 80; i++){
  out = await api('/api/phone', { action: 'outcome', id: asked.body.id });
  if (out.body.state === 'done') break;
  await new Promise(r => setTimeout(r, 250));
}
ok(out.body.state === 'done' && /root-ran-here/.test(out.body.out || ''),
   `Allow runs it on the node as a system job and the output comes back (${out.body.state}: ${(out.body.out || '').trim().split('\n').slice(-2).join(' / ')})`);
ok(/^# root on this node, allowed by test: load the binder module/.test(out.body.out || ''),
   `...and the job's log opens with who allowed it and why, so the Jobs page is the record (${(out.body.out || '').split('\n')[0].slice(0, 80)})`);
const jobs = (await api('/api/v1/jobs?n=10')).body.jobs || [];
const sysjob = jobs.find(j => j.type === 'system' && j.node === sandbox.id);
ok(sysjob && sysjob.state === 'succeeded',
   `the run is a system job on that node, finished (${sysjob?.state || 'no system job found'})`);

// ---- a node locked to its console refuses the ask itself -----------------------
{
  await api('/api/v1/nodes', { action: 'lock', id: sandbox.id });
  const lk = await api('/api/phone', { action: 'ask', kind: 'root', why: 'while locked', cmd: ['true'], project: 'alpha' });
  ok(/locked to its own console/.test(lk.body.error || ''),
     `a node whose system changes are locked refuses the ask outright, with the reason (${(lk.body.error || '').slice(0, 60)})`);
  await api('/api/v1/nodes', { action: 'unlock', id: sandbox.id });
}
// ---- ...and a node whose sessions may not ask for root at all ------------------
// The switch in its Sessions section (the operator, 24 Sep): root asks alone,
// where the lock above takes storage and network with them.
{
  const off = await api('/api/v1/nodes', { action: 'root-asks', id: sandbox.id, on: false });
  const no = await api('/api/phone', { action: 'ask', kind: 'root', why: 'while off', cmd: ['true'], project: 'alpha' });
  ok(off.body.ok && off.body.on === false && /root commands from sessions are off on sandbox/.test(no.body.error || ''),
     `with root asks off for the node, the ask is refused and says where it is turned back on (${(no.body.error || '').slice(0, 70)})`);
  await page.evaluate(() => loadNodes());
  await page.waitForFunction(id => document.querySelector(`.nodestab .ndrow[data-node="${id}"] [data-k="rootasks"]`) !== null
                                   || !document.querySelector('.nodestab'), sandbox.id, { timeout: 15000 }).catch(() => {});
  const on = await api('/api/v1/nodes', { action: 'root-asks', id: sandbox.id, on: true });
  const yes = await api('/api/phone', { action: 'ask', kind: 'root', why: 'while on again', cmd: ['true'], project: 'alpha' });
  ok(on.body.on === true && yes.body.id > 0, '...and on again, the ask goes to a person as before');
  await api('/api/phone', { action: 'deny', id: yes.body.id });
}

// ---- Deny says no, once ------------------------------------------------------
const denied = await api('/api/phone', { action: 'ask', kind: 'root', why: 'reboot it',
                                         cmd: ['reboot'], project: 'alpha' });
await page.evaluate(() => phFetch());
await page.waitForSelector('.ndask [data-rdeny]', { timeout: 15000 });
await page.click('.ndask [data-rdeny]');
await page.waitForFunction(() => !document.querySelector('.ndask'), null, { timeout: 20000 });
ok((await api('/api/phone', { action: 'outcome', id: denied.body.id })).body.state === 'denied',
   'Deny stops it, and the session is told no rather than left hanging');
ok((await api('/api/phone', { action: 'allow', id: denied.body.id })).body.error,
   '...and an answered request cannot be answered again: a second command is a second question');

// ---- a session's own token can ask, and reads only its own outcome ----------------
{
  const mint = (proj, who = '') => execFileSync('python3', ['-c', `
import importlib.util, json, os
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
def wj(p, d):
    tmp = str(p) + ".tmp"; open(tmp, "w").write(json.dumps(d, indent=2)); os.replace(tmp, p)
u.configure(state="${DIR}/state", write_json=wj)
uid = u.load()["users"]["${who}"]["uid"] if "${who}" else ""
print(u.mint_session("${proj}", uid=uid))`], { encoding: 'utf8' }).trim();
  const alpha = { Authorization: 'Bearer ' + mint('alpha'), 'Content-Type': 'application/json' };
  // A USER's session asks: they may not allow root on a shared machine, so
  // the request goes to every administrator, and not back to them.
  const vsess = { Authorization: 'Bearer ' + mint('alpha', 'visitor'), 'Content-Type': 'application/json' };
  const vask = await api('/api/phone', { action: 'ask', kind: 'root', why: 'from a user session', cmd: ['true'] }, vsess);
  ok(vask.status === 200 && /administrators/.test(vask.body.to || ''),
     `a user's session may ask, and is told the request went to the administrators (${vask.body.to})`);
  const seenBy = async h => (await api('/api/phone', undefined, h)).body.asks.some(a => a.id === vask.body.id);
  ok(await seenBy(owner) && await seenBy(ops) && !(await seenBy(other)),
     '...every administrator sees it, and the user whose session asked does not');
  ok(/administrator allows it, not a user/.test((await api('/api/phone', { action: 'allow', id: vask.body.id }, other)).body.error || ''),
     '...and the user cannot allow root on a shared sandbox, and is told why');
  await api('/api/phone', { action: 'deny', id: vask.body.id }, ops);
  ok((await api('/api/phone', { action: 'outcome', id: vask.body.id }, vsess)).body.state === 'denied',
     '...while any administrator can answer it');
  const beta = { Authorization: 'Bearer ' + mint('beta'), 'Content-Type': 'application/json' };
  const sess = await api('/api/phone', { action: 'ask', kind: 'root', why: 'from a session', cmd: ['true'] }, alpha);
  ok(sess.status === 200 && sess.body.id > 0, `a session token may ask for root on its project's node (${sess.status})`);
  const mine = (await api('/api/phone', undefined, alpha)).body.asks || [];
  ok(mine.some(a => a.id === sess.body.id) && !mine.some(a => a.project !== 'alpha'),
     "...and reading the list from a session shows its own project's waiting requests and no other's, which is what bb root prints");
  ok((await api('/api/phone', { action: 'allow', id: sess.body.id }, alpha)).status === 403,
     '...but may not answer its own question');
  ok((await api('/api/phone', { action: 'outcome', id: sess.body.id }, beta)).body.error,
     "...and another project's session cannot read its outcome");
  await api('/api/phone', { action: 'deny', id: sess.body.id });
}

// ---- a machine log off the node, which is the same root job ----------------
// `bb logs --node X --agent|--runner|--terminal` and the Debug grant behind
// it. Here rather than in nodes.mjs because the gate is only half of it: past
// the grant this IS root_wait, so proving WHICH command it runs needs a node
// that runs one, and this file's stub is the only one that does.
{
  const set = v => api('/api/settings', { set: { debug_mode: v } });
  const readLog = (stream) => api('/api/nodelog',
    { node: sandbox.name, stream, lines: 5, project: 'alpha' });
  // The argv off the job the read queued, which is the exact question; the
  // output only says what the command happened to print.
  const ranArgv = async r => ((((await api(`/api/v1/jobs?n=20`)).body.jobs || [])
    .find(j => j.id === r.body.job) || {}).spec?.config?.argv || []).join(' ');
  await set(true);
  await api('/api/prefs', { project: 'alpha', log_from: [sandbox.id] });

  // THE RUNNER'S OUTPUT GOES TO ONE OF TWO PLACES and only the node knows
  // which: the journal when svc.sh made it a service, runner.log under the
  // data store when the agent runs run.sh in the foreground instead. This
  // read the file unconditionally, so on every node where the runner is
  // installed properly (which is every node this project provisions),
  // `--runner` answered "No such file or directory".
  //
  // A census is the agent's to send, so the shape is set through the stub's
  // own overlay rather than through an API that should not exist. Waited for
  // by watching the row rather than by sleeping: the stub's poll is a long
  // one, so any fixed number here would be either flaky or five seconds.
  mkdirSync(`${DIR}/sandboxdata`, { recursive: true });
  const census = async (unit) => {
    const f = `${DIR}/sandboxdata/census-extra.json`;
    if (unit === null) rmSync(f, { force: true });
    else writeFileSync(f, JSON.stringify({ services: { runners: [{
      installed: true, active: true, unit }] } }));
    for (let i = 0; i < 120; i++){
      const n = ((await api('/api/v1/nodes')).body.nodes || []).find(x => x.id === sandbox.id);
      if (((n?.reported?.services?.runners || [])[0]?.unit || '') === (unit || '')) return true;
      await new Promise(r => setTimeout(r, 250));
    }
    return false;
  };

  ok(await census('actions.runner.example.sandbox.service'),
     'the node reports which systemd unit its runner is, when it is one');
  let r = await readLog('runner');
  let argv = await ranArgv(r);
  ok(/^journalctl -u actions\.runner\.example\.sandbox\.service/.test(argv),
     `...and the runner log is then read from that unit's journal (${argv || 'nothing ran'})`);
  ok(!/runner\.log/.test(argv),
     '...not from a runner.log that a node with a service never writes');

  // No unit: an agent too old to report the field, or a node with no systemd
  // running run.sh in the foreground. The file, exactly as before.
  ok(await census(''), 'a node whose runner is not a service reports no unit');
  r = await readLog('runner');
  argv = await ranArgv(r);
  ok(/^tail -n 5 .*runner\.log$/.test(argv),
     `...and is read from runner.log under its data store instead (${argv || 'nothing ran'})`);

  // The other two streams are one shape each and have nowhere to differ.
  {
    const a = await ranArgv(await readLog('agent'));
    ok(/journalctl -u builderbot-agent --no-pager -n 5;/.test(a) && /tail -n 5 \/var\/log\/builderbot-agent\.log/.test(a),
       `...the agent's own log is its journal, or the file its service writes where there is none (${a.slice(0, 80)})`);
  }
  ok(/ttyd\.log$/.test(await ranArgv(await readLog('terminal'))),
     '...and the terminal server writes a file under the data store');
  // The node's nginx is a stream too (R182), read with docker logs where the
  // nginx tab put one; on a node without it the refusal names the tab, and
  // never runs a thing.
  r = await readLog('nginx');
  ok(/nginx is not deployed on sandbox: the nginx page puts it there/.test(r.body.error || ''),
     `the nginx stream on a node without nginx says where it comes from (${(r.body.error || 'ran').slice(0, 60)})`);
  // The box itself (R183): the journal of this boot, the kernel ring, and
  // the previous boot's last lines, each one journalctl call.
  ok(/^journalctl --system --no-pager -n 5$/.test(await ranArgv(await readLog('system'))),
     "the system stream is this boot's journal, every unit");
  ok(/^journalctl -k --no-pager -n 5$/.test(await ranArgv(await readLog('kernel'))),
     '...the kernel stream its ring');
  ok(/^journalctl -b -1 --no-pager -n 5$/.test(await ranArgv(await readLog('crash'))),
     "...and the crash stream the previous boot's last lines");

  await census(null);
  await api('/api/prefs', { project: 'alpha', log_from: [] });
  await set(false);
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
if (page.errors.length) console.log(page.errors);
await api('/api/users', { action: 'remove', name: 'visitor' });
await api('/api/users', { action: 'remove', name: 'ops' });
await done(browser);
