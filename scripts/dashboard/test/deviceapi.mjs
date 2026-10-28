// The released apps' contract (R79 step 8). test/device-api.json pins, per
// app, every endpoint the Windows companion and the VS Code extension call
// and the fields each reads, with their types; this drives every pinned
// endpoint on this tree's controller, as the app would, and fails when one
// is gone or a pinned field is missing or changes type. Then the version
// handshake: an app from before the controller's window is refused with the
// way to update, and the controller says the version it speaks for an app
// newer than it to say so. The Android app's surface is
// apps/android/api-surface.json, held by test/appapi.mjs. No browser.
import { ok, done, DIR, URL, pinBreaks as breaks } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const require = createRequire(import.meta.url);
const client = require(`${REPO}/apps/vscode/lib/client.js`);
const base = URL.replace(/\/$/, '');
const pins = JSON.parse(readFileSync(new globalThis.URL('./device-api.json', import.meta.url), 'utf8'));
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

// Which pinned row lists each answer actually had rows in: a pin whose rows
// never came is not a pin held, and says so.
const rowsSeen = (body, reads) => Object.keys(reads || {}).filter(k => k.includes('[]'))
  .every(k => { const h = k.replace(/\?$/, '').split('[]')[0]; return Array.isArray(body?.[h]) && body[h].length > 0; });

// ---- accounts: a person with read and write on alpha through the editor's door ---------
addUser('pin.rw', 'pinrwpass1');
await admin('/api/users', { action: 'projects', name: 'pin.rw', projects: ['alpha'] });
await admin('/api/roles', { action: 'set', name: 'pin-files-w', scope: 'projects', perms: { projects: 'write', files: 'write' } });
await admin('/api/roles', { action: 'assign', name: 'pin.rw', project_roles: { alpha: ['pin-files-w'] } });
const set = await admin('/api/project-ftp', { action: 'set', project: 'alpha', editor: true, access: { [uidOf('pin.rw')]: 'rw' } });
ok(!set.error && set.editor === true, `alpha opens in an editor and on a device for the pinned person (${set.error || 'ok'})`);
writeFileSync(`${tree}/pin-probe.txt`, 'a needle for the search\n');

// ---- the companion, as it calls: its headers, its token --------------------------------
// What apps/windows/bbcompanion/update.py's headers() says, read from the source
// so the test and the app cannot drift on the names.
const updatePy = readFileSync(`${REPO}/apps/windows/bbcompanion/update.py`, 'utf8');
const appDoor = Number((updatePy.match(/^DOOR = (\d+)/m) || [])[1]);
const SAYS_PC = { 'X-BB-Door': String(appDoor), 'X-BB-App': 'companion/0.0.0' };
let token = '';
const dev = async (verb, body, { method = 'POST', query = '', raw = null, headers = {} } = {}) => {
  const h = { ...SAYS_PC, ...(token ? { Authorization: `Bearer ${token}` } : {}), ...headers };
  if (body !== undefined && raw === null) h['Content-Type'] = 'application/json';
  const r = await fetch(`${base}/api/v1/device/${verb}${query}`, { method, headers: h,
    body: raw !== null ? raw : body !== undefined ? JSON.stringify(body) : undefined });
  const buf = Buffer.from(await r.arrayBuffer());
  let json = null;
  try { json = JSON.parse(buf.toString()); } catch { json = null; }
  return { status: r.status, json, bytes: buf.length };
};
const signedIn = await dev('signin', { username: 'pin.rw', password: 'pinrwpass1', name: 'PIN-PC', kind: 'pc' });
token = signedIn.json?.token || '';
const stok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'pin.rw'], { encoding: 'utf8', env }).trim();
const pcApi = async body => (await fetch(`${base}/api/pc`, { method: 'POST',
  headers: { Authorization: `Bearer ${stok}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) })).json();

// One driver per pinned call: the answer the app would get. A pin with no
// driver fails, so a new pinned call cannot go undriven.
let rev = 0;
const COMPANION = {
  'POST /api/v1/device/signin': async () => signedIn,
  'POST /api/v1/device/projects': () => dev('projects', {}),
  'POST /api/v1/device/apps': () => dev('apps', {}),
  'GET /api/v1/device/app-file?app=&file=': () => dev('app-file', undefined, { method: 'GET', query: '?app=companion&file=nothing-held.pyz' }),
  'POST /api/v1/device/sync state': async () => {
    const r = await dev('sync', { action: 'state', project: 'alpha' });
    rev = r.json?.rev || 0;
    return r;
  },
  'POST /api/v1/device/sync since': async () => {
    writeFileSync(`${tree}/pin-moved.txt`, 'moved\n');
    return dev('sync', { action: 'since', project: 'alpha', rev, wait: 5 });
  },
  'GET /api/v1/device/sync-file?project=&path=': () => dev('sync-file', undefined, { method: 'GET', query: '?project=alpha&path=pin-probe.txt' }),
  'GET /api/v1/device/sync-tar?project=': () => dev('sync-tar', undefined, { method: 'GET', query: '?project=alpha' }),
  // A change made from an older version: the conflict answer, the one that
  // carries every field the app reads off sync-put.
  'POST /api/v1/device/sync-put?project=&path=&base=': () => dev('sync-put', undefined,
    { query: `?project=alpha&path=pin-probe.txt&base=${'0'.repeat(64)}`, raw: 'the PC\'s version\n' }),
  'POST /api/v1/device/pc-work': async () => {
    // Lent, then a session's ask under Auto, then the PC's poll hands it over.
    await dev('pc-work', { projects: { alpha: ['build'] }, wait: 0 });
    await admin('/api/prefs', { project: 'alpha', pc: 'auto' });
    const asked = await pcApi({ action: 'run', verb: 'build', why: 'the pin' });
    globalThis.pinAsk = asked.id;
    return dev('pc-work', { projects: { alpha: ['build'] }, wait: 2 });
  },
  'POST /api/v1/device/pc-result': async () => {
    const r = await dev('pc-result', { id: globalThis.pinAsk || 'pc_none', ok: true, text: 'built' });
    await admin('/api/prefs', { project: 'alpha', pc: 'deny' });
    return r;
  },
};

// ---- the extension, through its own client (apps/vscode/lib/client.js) ---------------------
const cookie = await client.signIn(base, 'pin.rw', 'pinrwpass1');
const ed = new client.Client(base, cookie);
const files = async (action, extra = {}) => {
  try { return { status: 200, json: await (action === 'projects' ? ed.post('/api/v1/files', { action }) : ed.files('alpha', action, extra)) }; }
  catch (e) { return { status: e.status || 0, json: e.body || { error: e.message } }; }
};
const VSCODE = {
  'POST /login': async () => ({ status: cookie ? 303 : 0, json: {} }),
  'POST /api/v1/files projects': () => files('projects'),
  'POST /api/v1/files stat': () => files('stat', { path: 'pin-probe.txt' }),
  'POST /api/v1/files list': () => files('list', { path: '' }),
  'POST /api/v1/files read': () => files('read', { path: 'pin-probe.txt' }),
  'POST /api/v1/files write': () => files('write', { path: 'pin-written.txt', data: Buffer.from('saved\n').toString('base64'),
                                                     create: true, overwrite: true }),
  'POST /api/v1/files mkdir': () => files('mkdir', { path: 'pin-dir' }),
  'POST /api/v1/files rename': () => files('rename', { path: 'pin-written.txt', to: 'pin-dir/pin-renamed.txt', overwrite: false }),
  'POST /api/v1/files delete': () => files('delete', { path: 'pin-dir', recursive: true }),
  'POST /api/v1/files search': () => files('search', { path: '', query: 'needle' }),
  // What opening an agent's session asks first (R128): the boot it starts for.
  'GET /api/status': async () => {
    try { return { status: 200, json: await ed.status() }; }
    catch (e) { return { status: e.status || 0, json: e.body || { error: e.message } }; }
  },
  'POST /api/v1/files changes': async () => {
    const first = await files('changes', { since: 0, wait: 0 });
    writeFileSync(`${tree}/pin-change.txt`, 'changed\n');
    return files('changes', { since: first.json?.rev || 0, wait: 10 });
  },
};

// ---- every pin driven, every pinned field present with its type --------------------------
for (const [app, drivers] of [['companion', COMPANION], ['vscode', VSCODE]]) {
  const problems = [], thin = [];
  let n = 0;
  for (const e of pins.apps[app].endpoints) {
    if (e.needs) continue;
    const key = `${e.method} ${e.path}${e.sends?.action ? ' ' + e.sends.action : ''}`;
    const drive = drivers[key];
    if (!drive) { problems.push(`${key}: pinned and not driven here`); continue; }
    const r = await drive();
    n += 1;
    if (e.absent) {
      // Asked for something not there: the endpoint's own refusal, not the
      // door's "no such verb", is what proves it still answers.
      if (!(r.status === 404 && (r.json?.error || '').includes(e.absent))) problems.push(`${key}: HTTP ${r.status} ${r.json?.error || ''}`);
      continue;
    }
    if (e.binary) { if (r.status !== 200 || !r.bytes) problems.push(`${key}: HTTP ${r.status}, ${r.bytes} bytes`); continue; }
    if (e.path === '/login') { if (r.status !== 303) problems.push(`${key}: no session cookie`); continue; }
    if (r.status !== 200) { problems.push(`${key}: HTTP ${r.status} ${r.json?.error || ''}`); continue; }
    problems.push(...breaks(r.json, e.reads, key));
    if (!rowsSeen(r.json, e.reads)) thin.push(key);
  }
  ok(problems.length === 0, `every call the ${app} makes answers with the fields it reads, as typed (${n} driven)${
    problems.length ? ': ' + problems.join('; ') : ''}`);
  ok(thin.length === 0, `...with rows in every pinned list, so each row's fields were held too${thin.length ? ': none in ' + thin.join(', ') : ''}`);
}
ok(pins.apps.android?.contract && existsSync(`${REPO}/${pins.apps.android.contract}`),
   'the Android app is named, with its own contract held by test/appapi.mjs');

// ---- the checker refuses what it should ------------------------------------------------------
// A removed field, a changed type and a row's changed type each fail, so a
// pass above means the fields were looked at.
{
  const reads = { a: 'number', 'b?': 'string', 'rows[].x': 'string', 'tup[]': ['string', 'number'] };
  const good = { a: 1, rows: [{ x: 'y' }], tup: [['p', 2]] };
  ok(breaks(good, reads, 't').length === 0 && breaks({ ...good, a: undefined }, reads, 't').length === 1
     && breaks({ ...good, a: '1' }, reads, 't').length === 1 && breaks({ ...good, b: 3 }, reads, 't').length === 1
     && breaks({ ...good, rows: [{ x: 1 }] }, reads, 't').length === 1 && breaks({ ...good, tup: [['p', 'q']] }, reads, 't').length === 1,
     'the pin check fails on a field gone, a type changed, and a row\'s field or column changed');
}

// ---- the handshake: each side says its version -------------------------------------------------
{
  // An app from before the door's window is refused with the way to update,
  // by its name; what it would update from still answers.
  const old = await dev('projects', {}, { headers: { 'X-BB-Door': '0', 'X-BB-App': 'companion/0.0.1' } });
  const apps = await dev('apps', {}, { headers: { 'X-BB-Door': '0' } });
  ok(old.status === 426 && old.json?.update === true && /companion\/0\.0\.1 speaks the controller's door 0/.test(old.json?.error || '')
     && apps.status === 200,
     `a companion older than the door's window is told to update, by name, and may still ask what to update to (${old.status}: ${old.json?.error})`);
  const proj = await dev('projects', {});
  ok(proj.json?.door >= appDoor && proj.json?.door_min <= appDoor,
     `this tree's companion speaks a door the controller keeps (app ${appDoor}, controller ${proj.json?.door_min} to ${proj.json?.door})`);
  // The extension: its headers on every call, and the same refusal.
  const pkg = JSON.parse(readFileSync(`${REPO}/apps/vscode/package.json`, 'utf8'));
  const h = ed.headers();
  ok(h['X-BB-Api'] === String(client.API) && h['X-BB-App'] === `vscode/${pkg.version}` && pkg.builderbotApi === client.API,
     `the extension says its Files API and its release on every call (${h['X-BB-Api']} ${h['X-BB-App']})`);
  const r = await fetch(`${base}/api/v1/files`, { method: 'POST', body: JSON.stringify({ action: 'projects' }),
    headers: { Cookie: `bb_session=${cookie}`, 'Content-Type': 'application/json', 'X-BB-Api': '0', 'X-BB-App': 'vscode/0.0.1' } });
  const j = await r.json();
  ok(r.status === 426 && /vscode\/0\.0\.1 speaks the Files API 0/.test(j.error || ''),
     `an extension older than the Files API's window is told to update, by name (${r.status}: ${j.error})`);
  const mine = await ed.projects();
  ok(mine.tooOld === '' && /needs 1: update BuilderBot on the controller/.test(client.controllerTooOld({ api: 0 }))
     && client.controllerTooOld({ api: client.API }) === '',
     'the extension says plainly when its controller is too old for it, and nothing when it is not');
}

await done();
