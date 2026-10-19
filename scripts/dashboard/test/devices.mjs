// A person's devices (R272 step 1, R270 step 2): an app signs in with the
// person's name and password once and holds a device token of its own
// (bbd_), which acts as that person on the device door (/api/v1/device/*)
// and nowhere else; through it the app keeps a project folder in step as a
// node's synced copy is kept, as far as the project's editor access lets the
// person: .git never comes down or goes up, a conflict copy is named for the
// device, a read-only person's change is refused, and a device waiting on
// the project wakes when another changes it. The Profile page lists the
// devices and Disconnect signs one out. No browser.
import { ok, done, DIR, URL } from './lib.mjs';
import { execFileSync, spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const admin = async (path, body) => {
  const r = await fetch(base + path, { method: 'POST', headers: ADMIN, body: JSON.stringify(body) });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};
const env = { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` };
const addUser = (name, pw) => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', name, '--role', 'user'],
  { input: `${pw}\n${pw}\n`, encoding: 'utf8', env });
const uidOf = n => JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users[n].uid;
const tree = `${DIR}/ws/alpha`;
// One call on the device door: its status and body, never a throw.
const dev = async (tok, verb, body, { method = 'POST', query = '', raw = null } = {}) => {
  const headers = tok ? { Authorization: `Bearer ${tok}` } : {};
  if (body !== undefined && raw === null) headers['Content-Type'] = 'application/json';
  const r = await fetch(`${base}/api/v1/device/${verb}${query}`, { method, headers,
    body: raw !== null ? raw : body !== undefined ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let json = {};
  try { json = JSON.parse(text); } catch { json = { text }; }
  return { status: r.status, ...json };
};
const signin = (username, password, name = 'TEST-PC') => dev('', 'signin', { username, password, name, kind: 'pc' });

// ---- accounts, and what alpha's editor access gives each --------------------------
const people = { 'dv.rw': 'dvrwpass1', 'dv.r': 'dvrpass12', 'dv.none': 'dvnonepass1' };
for (const [n, pw] of Object.entries(people)) addUser(n, pw);
for (const n of Object.keys(people)) await admin('/api/users', { action: 'projects', name: n, projects: ['alpha'] });
await admin('/api/roles', { action: 'set', name: 'dv-files-w', scope: 'projects', perms: { projects: 'write', files: 'write' } });
for (const n of Object.keys(people)) await admin('/api/roles', { action: 'assign', name: n, project_roles: { alpha: ['dv-files-w'] } });
const set = await admin('/api/project-ftp', { action: 'set', project: 'alpha', editor: true,
  access: { [uidOf('dv.rw')]: 'rw', [uidOf('dv.r')]: 'r' } });
ok(!set.error && set.editor === true, `alpha's editor access set for the devices' people (${set.error || 'ok'})`);
writeFileSync(`${tree}/device-probe.txt`, 'from the controller\n');
mkdirSync(`${tree}/.git`, { recursive: true });
writeFileSync(`${tree}/.git/config`, '[remote "origin"]\n  url = https://x:ghp_secret@example.com/r.git\n');

// ---- signing in --------------------------------------------------------------------
const wrong = await signin('dv.rw', 'not-it');
ok(wrong.status === 401 && /wrong username or password/.test(wrong.error || ''), `a wrong password mints nothing (${wrong.status})`);
const a = await signin('dv.rw', people['dv.rw']);
ok(a.status === 200 && /^bbd_/.test(a.token || '') && a.device?.name === 'TEST-PC' && a.account === 'dv.rw',
   `the app's sign-in mints a device token named for the machine (${JSON.stringify({ status: a.status, device: a.device, account: a.account })})`);
const who = await dev(a.token, 'whoami', {});
ok(who.status === 200 && who.account === 'dv.rw' && who.name === 'TEST-PC', `...and the token says whose it is (${JSON.stringify(who)})`);

// ---- each door stays shut to the other's credential ---------------------------------
const onPage = await fetch(`${base}/api/status`, { headers: { Authorization: `Bearer ${a.token}` } });
const sess = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'], { encoding: 'utf8', env }).trim();
const sessOnDoor = await dev(sess, 'whoami', {});
ok(onPage.status === 401 && sessOnDoor.status === 401,
   `a device token opens nothing on the dashboard, and a session's token nothing on the device door (${onPage.status} ${sessOnDoor.status})`);

// ---- a person's projects --------------------------------------------------------------
const mine = await dev(a.token, 'projects', {});
const rOnly = await signin('dv.r', people['dv.r'], 'READER-PC');
const none = await signin('dv.none', people['dv.none'], 'NONE-PC');
const theirs = await dev(rOnly.token, 'projects', {}), nobody = await dev(none.token, 'projects', {});
ok(mine.projects?.some(p => p.project === 'alpha' && p.access === 'rw') && theirs.projects?.some(p => p.project === 'alpha' && p.access === 'r')
   && !nobody.projects?.length,
   `a device lists the projects its person may edit or read through the editor's door, and no others (${JSON.stringify([mine.projects, theirs.projects, nobody.projects])})`);
const shut = await dev(none.token, 'sync', { action: 'state', project: 'alpha' });
ok(shut.status === 403, `...and a person with no editor access syncs nothing (${shut.status})`);

// ---- the sync: down, with .git hidden ---------------------------------------------------
const st = await dev(a.token, 'sync', { action: 'state', project: 'alpha' });
const paths = (st.files || []).map(f => f[0]);
ok(st.status === 200 && paths.includes('device-probe.txt') && !paths.some(p => p.split('/').includes('.git')),
   `the state lists the project's files with their hashes and no .git (${paths.length} files, rev ${st.rev})`);
const tar = await fetch(`${base}/api/v1/device/sync-tar?project=alpha`, { headers: { Authorization: `Bearer ${a.token}` } });
const tarText = Buffer.from(await tar.arrayBuffer()).toString('latin1');
ok(tar.status === 200 && tarText.includes('device-probe.txt') && !tarText.includes('.git/config') && !tarText.includes('ghp_secret'),
   `the first copy comes down as one archive, .git and its credential left out (${tar.status}, ${tarText.length} bytes)`);
const gitFile = await dev(a.token, 'sync-file', undefined, { method: 'GET', query: '?project=alpha&path=.git/config' });
const oneFile = await fetch(`${base}/api/v1/device/sync-file?project=alpha&path=device-probe.txt`, { headers: { Authorization: `Bearer ${a.token}` } });
ok(gitFile.status === 400 && oneFile.status === 200 && (await oneFile.text()) === 'from the controller\n',
   `one file comes down by its path, and .git/config does not (${gitFile.status} ${oneFile.status})`);

// ---- the sync: up, a conflict, and read-only ---------------------------------------------
const put = (tok, path, body, baseSha = '') => dev(tok, 'sync-put', undefined,
  { method: 'POST', query: `?project=alpha&path=${encodeURIComponent(path)}&base=${baseSha}`, raw: body });
const up = await put(a.token, 'from-device.txt', 'written on the PC\n');
ok(up.status === 200 && up.ok && readFileSync(`${tree}/from-device.txt`, 'utf8') === 'written on the PC\n',
   `a file changed on the device goes up and lands in the project (${JSON.stringify(up)})`);
const clash = await put(a.token, 'device-probe.txt', 'the PC\'s version\n', '0'.repeat(64));
const kept = readdirSync(tree).filter(f => /^device-probe\.conflict-TEST-PC-/.test(f));
ok(clash.status === 200 && clash.conflict && kept.length === 1 && readFileSync(`${tree}/device-probe.txt`, 'utf8') === 'from the controller\n',
   `a change made from an older version is kept beside the project's as a conflict copy named for the device (${JSON.stringify({ conflict: clash.conflict, kept })})`);
const gitUp = await put(a.token, '.git/hooks/post-checkout', '#!/bin/sh\n');
const readOnly = await put(rOnly.token, 'reader.txt', 'no\n');
ok(gitUp.status === 400 && !existsSync(`${tree}/.git/hooks/post-checkout`) && readOnly.status === 403 && !existsSync(`${tree}/reader.txt`),
   `nothing goes up into .git, and a person who may only read changes nothing (${gitUp.status} ${readOnly.status})`);

// ---- a device waiting on the project wakes when another changes it ------------------------
const b = await signin('dv.rw', people['dv.rw'], 'LAPTOP');
const at = (await dev(a.token, 'sync', { action: 'state', project: 'alpha' })).rev;
const t0 = Date.now();
const waiting = dev(a.token, 'sync', { action: 'since', project: 'alpha', rev: at, wait: 15 });
await new Promise(r => setTimeout(r, 400));
await put(b.token, 'from-laptop.txt', 'the laptop\n');
const woke = await waiting;
ok(woke.status === 200 && (woke.changes || []).some(c => c[0] === 'from-laptop.txt') && Date.now() - t0 < 10000,
   `a device's long poll returns with another device's change within seconds (${Date.now() - t0} ms, ${(woke.changes || []).map(c => c[0]).join(', ')})`);

// ---- the app itself (windows/bbcompanion), its own command line against this server -----------
// The agent's sync, shared, on the device door: signed in, a project picked
// into a folder, the first copy made; then a change made in the folder goes
// up and one made elsewhere comes down, with nothing but the app running.
{
  const appEnv = { ...process.env, APPDATA: `${DIR}/appdata`, PYTHONPATH: `${REPO}/windows:${REPO}/scripts/agent`,
                   BB_COMPANION_PASSWORD: people['dv.rw'] };
  const app = (...args) => { try { return { code: 0, out: execFileSync('python3', ['-m', 'bbcompanion', ...args], { env: appEnv, encoding: 'utf8', timeout: 120000 }) }; }
                             catch (e) { return { code: e.status, out: `${e.stdout || ''}${e.stderr || ''}` }; } };
  const folder = `${DIR}/pc/alpha`;
  const si = app('signin', base, 'dv.rw'), ad = app('add', 'alpha', folder), once = app('run', '--once');
  ok(si.code === 0 && ad.code === 0 && once.code === 0 && existsSync(`${folder}/device-probe.txt`)
     && readFileSync(`${folder}/device-probe.txt`, 'utf8') === 'from the controller\n' && !existsSync(`${folder}/.git`),
     `the app signs in, keeps alpha in a folder, and makes the first copy there without .git (${[si.out, ad.out, once.out].join(' | ').replace(/\s+/g, ' ').slice(0, 200)})`);
  const daemon = spawn('python3', ['-m', 'bbcompanion', 'run'], { env: appEnv, stdio: 'ignore' });
  try {
    writeFileSync(`${folder}/made-on-pc.txt`, 'from the folder\n');
    let up = false;
    for (let i = 0; i < 60 && !up; i++) { up = existsSync(`${tree}/made-on-pc.txt`); if (!up) await new Promise(r => setTimeout(r, 500)); }
    ok(up && readFileSync(`${tree}/made-on-pc.txt`, 'utf8') === 'from the folder\n', 'a file made in the folder goes up to the project within seconds');
    const c2 = await signin('dv.rw', people['dv.rw'], 'ELSEWHERE');
    await put(c2.token, 'made-elsewhere.txt', 'from another device\n');
    let down = false;
    for (let i = 0; i < 60 && !down; i++) { down = existsSync(`${folder}/made-elsewhere.txt`); if (!down) await new Promise(r => setTimeout(r, 500)); }
    ok(down && readFileSync(`${folder}/made-elsewhere.txt`, 'utf8') === 'from another device\n',
       '...and one made elsewhere comes down into the folder within seconds, woken by its long poll');
  } finally { daemon.kill(); }
}

// ---- the Profile page lists them, and Disconnect signs one out -------------------------------
const PERSON = { Authorization: 'Basic ' + Buffer.from(`dv.rw:${people['dv.rw']}`).toString('base64'), 'Content-Type': 'application/json' };
const prof = await (await fetch(`${base}/api/profile`, { headers: PERSON })).json();
const listed = (prof.devices || []).map(d => d.name);
ok(['TEST-PC', 'LAPTOP', 'ELSEWHERE'].every(n => listed.includes(n)) && (prof.devices || []).every(d => !('secret_hash' in d) && d.kind === 'pc'),
   `the Profile page lists the person's devices, never their secrets (${JSON.stringify((prof.devices || []).map(d => d.name))})`);
const out = await (await fetch(`${base}/api/profile`, { method: 'POST', headers: PERSON,
  body: JSON.stringify({ action: 'device-signout', device: a.device.id }) })).json();
const after = await dev(a.token, 'whoami', {}), still = await dev(b.token, 'whoami', {});
ok(out.ok && after.status === 401 && /signed out/.test(after.error || '') && still.status === 200,
   `Disconnect signs that device out at once and leaves the other (${after.status} ${still.status})`);
const otherOut = await (await fetch(`${base}/api/profile`, { method: 'POST', headers: { ...ADMIN },
  body: JSON.stringify({ action: 'device-signout', device: b.device.id }) })).json();
ok(otherOut.error && (await dev(b.token, 'whoami', {})).status === 200,
   `another account cannot sign a person's device out (${otherOut.error})`);

done();
