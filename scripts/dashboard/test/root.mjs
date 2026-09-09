// One command as root on a node (roadmap R38): the phone's shape applied to
// root. A session asks with a reason and the exact command; the request
// waits on the administrators — on the Nodes tab and in the bell, nobody
// else's — and Allow runs that one command on the node as a system job,
// Deny says no. Not sudo, and not a fake one.
//
// The harness's sandbox node runs agent-stub.py, whose census says sandbox
// and whose system job runs the allowed command as the suite's own user:
// this file proves the asking, the routing and the answering; the real
// agent's own file proves the running and the guest-node refusal.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
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
   'a root ask with no reason is refused — Allow on an unexplained root command is a guess');
ok(/has no node/.test((await api('/api/phone', { action: 'ask', kind: 'root', why: 'look', cmd: ['id'], project: 'beta' })).body.error || ''),
   'a project with no node has no machine to ask for root on, and is told so');
ok((await api('/api/phone', { action: 'ask', kind: 'root', why: 'look', cmd: [], project: 'alpha' })).body.error,
   '...and an ask with nothing to run is refused');

// ---- a second account, of the kind that is not asked ---------------------------
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'visitor', '--role', 'user'],
  { input: 'visitorpass1\nvisitorpass1\n', encoding: 'utf8',
    env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const other = asUser('visitor', 'visitorpass1');
await api('/api/users', { action: 'projects', name: 'visitor', projects: ['alpha'] });

// ---- the ask, and who sees it ------------------------------------------------
const asked = await api('/api/phone', { action: 'ask', kind: 'root', why: 'load the binder module for the emulator',
                                        cmd: ['sh', '-c', 'echo root-ran-here; id -un'], project: 'alpha' });
ok(asked.body.id > 0 && /administrators/.test(asked.body.to || ''),
   `a session can ask for one root command, and is told it went to the administrators (${JSON.stringify(asked.body).slice(0, 90)})`);
ok((await api('/api/phone', undefined, other)).body.asks.filter(a => a.kind === 'root').length === 0,
   'a user account is not asked — a root request waits on administrators alone');
ok((await api('/api/phone')).body.asks.some(a => a.id === asked.body.id && a.kind === 'root'),
   '...and the administrator is, with the request marked as a root one');
ok((await api('/api/phone', { action: 'allow', id: asked.body.id }, other)).body.error,
   '...and the user cannot answer it, either way');

// ---- where it shows: the Nodes tab and the bell --------------------------------
await page.evaluate(() => openNodesTab());
await page.evaluate(() => phFetch());
await page.waitForSelector('.ndask', { timeout: 15000 });
const askText = await page.$eval('.ndask', e => e.textContent);
ok(/load the binder module/.test(askText) && /alpha asks to run this as root on sandbox/.test(askText)
   && /echo root-ran-here/.test(askText) && /left to answer/.test(askText),
   'the Nodes tab shows the request above the node: the reason, the exact command, whose it is, and how long is left');
ok(await page.$('.phask') === null, '...and the Phone tab is not where it goes');
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
await page.click('.ndask [data-rallow]');
await page.waitForFunction(() => !document.querySelector('.ndask'), null, { timeout: 30000 });
const out = await api('/api/phone', { action: 'outcome', id: asked.body.id });
ok(out.body.state === 'done' && /root-ran-here/.test(out.body.out || ''),
   `Allow runs it on the node as a system job and the output comes back (${out.body.state}: ${(out.body.out || '').trim().split('\n').slice(-2).join(' / ')})`);
ok(/^# root on this node, allowed by test: load the binder module/.test(out.body.out || ''),
   `...and the job's log opens with who allowed it and why, so the Jobs tab is the record (${(out.body.out || '').split('\n')[0].slice(0, 80)})`);
const jobs = (await api('/api/v1/jobs?n=10')).body.jobs || [];
const sysjob = jobs.find(j => j.type === 'system' && j.node === sandbox.id);
ok(sysjob && sysjob.state === 'succeeded',
   `the run is a system job on that node, finished (${sysjob?.state || 'no system job found'})`);

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
   '...and an answered request cannot be answered again — a second command is a second question');

// ---- a session's own token can ask, and reads only its own outcome ----------------
{
  const mint = (proj) => execFileSync('python3', ['-c', `
import importlib.util, json, os
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
def wj(p, d):
    tmp = str(p) + ".tmp"; open(tmp, "w").write(json.dumps(d, indent=2)); os.replace(tmp, p)
u.configure(state="${DIR}/state", write_json=wj)
print(u.mint_session("${proj}"))`], { encoding: 'utf8' }).trim();
  const alpha = { Authorization: 'Bearer ' + mint('alpha'), 'Content-Type': 'application/json' };
  const beta = { Authorization: 'Bearer ' + mint('beta'), 'Content-Type': 'application/json' };
  const sess = await api('/api/phone', { action: 'ask', kind: 'root', why: 'from a session', cmd: ['true'] }, alpha);
  ok(sess.status === 200 && sess.body.id > 0, `a session token may ask for root on its project's node (${sess.status})`);
  ok((await api('/api/phone', { action: 'allow', id: sess.body.id }, alpha)).status === 403,
     '...but may not answer its own question');
  ok((await api('/api/phone', { action: 'outcome', id: sess.body.id }, beta)).body.error,
     "...and another project's session cannot read its outcome");
  await api('/api/phone', { action: 'deny', id: sess.body.id });
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
if (page.errors.length) console.log(page.errors);
await api('/api/users', { action: 'remove', name: 'visitor' });
await done(browser);
