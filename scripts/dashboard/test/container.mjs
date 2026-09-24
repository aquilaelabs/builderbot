// A container asked for by a session (roadmap R71): the root shape applied
// to docker. The session writes a compose file and hands it over with a
// reason; the request waits on the administrators, and nobody else, in the
// bell; Allow registers it through the Docker tab's own New container path
// and starts its build; Deny says no. The session never runs docker and
// nothing runs until somebody has read the file.
//
// The harness's stub docker answers `compose config` and the build job, the
// way devapp.mjs's New container tests use it, so this file proves the
// asking, the routing, the reading and the answering.
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
const COMPOSE = 'services:\n  app:\n    image: alpine\n    command: sleep 1\n';
const ask = (extra, headers = owner) => api('/api/phone', {
  action: 'ask', kind: 'container', why: 'a sonarr to test the media project against',
  name: 'sonarr-for-alpha', compose: COMPOSE, env: 'PUID=99\nSECRET=hunter2\n',
  project: 'alpha', ...extra }, headers);

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

const sandbox = (await api('/api/v1/nodes')).body.nodes.find(n => n.name === 'sandbox');
await api('/api/prefs', { project: 'alpha', node: sandbox.id });

// ---- what is refused before anybody is asked -------------------------------
ok(/say what the container is for/.test((await ask({ why: '' })).body.error || ''),
   'an ask with no reason is refused: Allow on an unexplained container is a guess');
ok(/needs a name/.test((await ask({ name: '' })).body.error || ''),
   '...and one with no name');
ok(/hand over the compose file/.test((await ask({ compose: '   ' })).body.error || ''),
   '...and one with nothing to build');
ok(/no node called nowhere/.test((await ask({ node: 'nowhere' })).body.error || ''),
   '...and one naming a machine that is not a node, before it reaches anybody');
ok(/not a project: zeta/.test((await ask({ for: 'zeta' })).body.error || ''),
   '...and one for a project the asker cannot see');

// ---- a second account, of the kind that is never asked --------------------
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'visitor', '--role', 'user'],
  { input: 'visitorpass1\nvisitorpass1\n', encoding: 'utf8',
    env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const other = asUser('visitor', 'visitorpass1');
await api('/api/users', { action: 'projects', name: 'visitor', projects: ['alpha'] });

// ---- the ask, who sees it, and what they see --------------------------------
const asked = await ask({});
ok(asked.body.id > 0 && /administrators/.test(asked.body.to || ''),
   `a container ask goes to the administrators, whoever asks (${asked.body.to})`);
const mine = (await api('/api/phone')).body.asks.find(a => a.id === asked.body.id);
ok(mine && mine.kind === 'container' && mine.name === 'sonarr-for-alpha' && mine.node_name === 'sandbox'
   && mine.detail === COMPOSE,
   'the administrator sees the request with the compose file whole, since the file is the request');
ok(JSON.stringify(mine.env_keys) === JSON.stringify(['PUID', 'SECRET'])
   && !JSON.stringify(mine).includes('hunter2'),
   "...and the env file's keys but never its values, which is where a token would be");
ok(!(await api('/api/phone', undefined, other)).body.asks.some(a => a.id === asked.body.id),
   'a user account is not asked: a container is docker-write on a node, which no user holds');
ok((await api('/api/phone', { action: 'allow', id: asked.body.id }, other)).body.error,
   '...and cannot answer it either way');

// ---- where it shows: the bell, with the file under the reason ----------------
await page.waitForFunction(
  () => { const d = document.querySelector('#bBell .dot');
          return d && !d.hidden && d.classList.contains('ask'); }, null, { timeout: 15000 });
await page.click('#bBell');
await page.waitForSelector('#bellPanel .bnote.ask', { timeout: 10000 });
const bell = await page.$eval('#bellPanel .bnote.ask', e => ({
  text: e.textContent, file: e.querySelector('.bdetail pre')?.textContent || '',
  sum: e.querySelector('.bdetail summary')?.textContent || '' }));
ok(/container sonarr-for-alpha on sandbox/.test(bell.text) && /a sonarr to test/.test(bell.text)
   && bell.file === COMPOSE && /PUID, SECRET/.test(bell.sum) && !/hunter2/.test(bell.text),
   `the bell row names the container and the node, and folds the compose file under the reason (${
     bell.sum})`);

// ---- Allow: registered through the Docker tab's own path, then built -------
const allowed = await api('/api/phone', { action: 'allow', id: asked.body.id });
const out = (await api('/api/phone', { action: 'outcome', id: asked.body.id })).body;
ok(allowed.body.ok && out.state === 'done' && out.code === 0,
   `Allow registers the container and starts its build, and the session's outcome says so (${
     out.state}: ${out.out})`);
ok((await api('/api/docker')).body.instances.some(i => i.project === 'sonarr-for-alpha'),
   '...and the Docker tab lists it, written from the file the administrator read');

// ---- a session's ask belongs to its own project -------------------------------
// So the session that asked can see what it asked for once it exists, and
// work on it as its project's settings allow (the operator, 24 Sep).
{
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
  const bySession = await ask({ name: 'sonarr-by-session', project: '' },
    { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok });
  const row = (await api('/api/phone')).body.asks.find(a => a.id === bySession.body.id);
  ok(row && row.for === 'alpha', `a session's ask belongs to its own project when it names none (${row?.for})`);
  await api('/api/phone', { action: 'deny', id: bySession.body.id });
}

// ---- Deny: reported to the session, nothing made -------------------------------
const again = await ask({ name: 'sonarr-denied' });
await api('/api/phone', { action: 'deny', id: again.body.id });
const no = (await api('/api/phone', { action: 'outcome', id: again.body.id })).body;
ok(no.state === 'denied' && !(await api('/api/docker')).body.instances.some(i => i.project === 'sonarr-denied'),
   'Deny is what the session is told, and nothing is registered');

// ---- the same name twice is refused where the tab would refuse it -------------
const dup = await ask({});
await api('/api/phone', { action: 'allow', id: dup.body.id });
const dupOut = (await api('/api/phone', { action: 'outcome', id: dup.body.id })).body;
ok(dupOut.state === 'done' && dupOut.code === 1 && /already exists/.test(dupOut.out || ''),
   `a name the store already has is refused at Allow with the tab's own words (${dupOut.out})`);

ok(page.errors.length === 0, 'zero console errors');
await done(browser);
