// The companion app's contract. apps/android/api-surface.json names every path
// the app calls and the fields it reads from each answer, and carries the
// number server.py's APP_API and the app's TARGET_API both carry. This file
// holds the running dashboard to that: a path that stops answering, a field
// that is renamed, or a number moved on one side and not the others fails
// here, before the app finds out by drawing blanks. Moving the surface is
// fine; moving it without the app is what this catches.
import { ok, done, URL, DIR, pinBreaks } from './lib.mjs';
import { readFileSync, writeFileSync, mkdirSync, rmSync, readdirSync, utimesSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const base = URL.replace(/\/$/, '');
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const get = async p => { const r = await fetch(base + p, { headers: H }); return { status: r.status, body: await r.json() }; };

const surface = JSON.parse(readFileSync(join(REPO, 'apps', 'android', 'api-surface.json'), 'utf8'));
const gradle = readFileSync(join(REPO, 'apps', 'android', 'app', 'build.gradle.kts'), 'utf8');
const serverPy = readFileSync(join(REPO, 'scripts', 'dashboard', 'server.py'), 'utf8');

// ---- one number, three places -------------------------------------------------
const meta = await get('/api/meta');
const appApi = Number((gradle.match(/buildConfigField\("int", "TARGET_API", "(\d+)"\)/) || [])[1]);
const srcApi = Number((serverPy.match(/^APP_API = (\d+)/m) || [])[1]);
ok(meta.status === 200 && meta.body.api === surface.api && appApi === surface.api && srcApi === surface.api,
   `the surface number agrees everywhere: server ${meta.body.api}, source ${srcApi}, app ${appApi}, contract ${surface.api}`);
ok(typeof meta.body.version === 'string' && typeof meta.body.apk === 'string',
   '...and /api/meta names the image and where a newer app would be');
// `built` rides the same endpoint for bb status on a node (R62): a session
// there reads the controller's build off /api/meta, since its own env carries
// no image stamp. Not an app field (not in api-surface.json), so it does not
// move APP_API; asserted here because this is where /api/meta's shape is kept.
ok(typeof meta.body.built === 'string',
   '...and carries the build time, which bb status on a node shows for the controller');
// Where a newer app would be is a SIGNED build when there is one, however
// new an unsigned one is: the phone's app was installed signed and Android
// will not update it with a debug build (B507, 5 Oct).
// BuilderBot's own project is the one whose origin is its repository, whatever
// its folder is called (B4): a folder named BuilderBot with no such remote,
// holding a newer signed build, is not where the app is sent.
{
  const self = `${DIR}/ws/bb-public`, d = `${self}/dist`;
  mkdirSync(d, { recursive: true });
  mkdirSync(`${self}/.git`, { recursive: true });
  writeFileSync(`${self}/.git/config`,
    '[core]\n\tbare = false\n[remote "origin"]\n\turl = https://github.com/aquilaelabs/builderbot.git\n'
    + '\tfetch = +refs/heads/*:refs/remotes/origin/*\n');
  const signed = 'builderbot-app-0.7.0-dev.2284-d51d651-signed.apk';
  writeFileSync(`${d}/${signed}`, 'signed');
  writeFileSync(`${d}/builderbot-app-0.7.0-dev.2290-abc1234-dirty.apk`, 'dirty');
  writeFileSync(`${d}/builderbot-app-dev.apk`, 'a debug build');
  const old = new Date(Date.now() - 3600_000);
  utimesSync(`${d}/${signed}`, old, old);
  mkdirSync(`${DIR}/ws/BuilderBot/dist`, { recursive: true });
  writeFileSync(`${DIR}/ws/BuilderBot/dist/builderbot-app-0.7.0-dev.9999-fffffff-signed.apk`, 'not ours');
  const meta = (await get('/api/meta')).body;
  rmSync(self, { recursive: true, force: true });
  rmSync(`${DIR}/ws/BuilderBot`, { recursive: true, force: true });
  ok(meta.apk === signed, `the app is offered the signed build, not a newer unsigned one (${meta.apk})`);
  ok(meta.apk_sha256 === createHash('sha256').update('signed').digest('hex'),
     `...read from the project whose origin is BuilderBot's repository, not a folder named BuilderBot (${meta.apk_sha256})`);
}

// ---- a row in each list the app reads ----------------------------------------------
// A row's types are held only where there is a row, and the fixture leaves
// most of these lists empty, so a type changed on one went unseen (B107).
// Each list the notebook or the tree fills gets a row here, through the verbs
// a session or a person uses; the world is put back before the next file.
{
  const ENV = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`,
                WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha', BB_ROADMAP_PROJECT: 'alpha', BB_BUG_PROJECT: 'alpha',
                BB_TESTS_PROJECT: 'alpha' };
  const bb = (...a) => execFileSync(join(REPO, 'scripts', 'bb'), a, { env: ENV, encoding: 'utf8' });
  const post = async (p, b) => (await fetch(base + p, { method: 'POST', headers: H, body: JSON.stringify(b) })).json();
  bb('roadmap', 'add', 'a row the contract types', '--step', 'and a step');
  bb('bug', 'add', 'a row the contract types', '--area', 'contract');
  bb('rules', 'add', 'contract-row', 'A rule the contract types.', '--words', 'contract');
  // Held for the operator: the gate set to ask, and a session's add.
  await post('/api/prefs', { project: 'alpha', gate: { roadmap: 'ask' } });
  bb('roadmap', 'add', 'a held row the contract types');
  await post('/api/wiki', { project: 'alpha', action: 'save', name: 'Contract row', text: 'A page the contract types.' });
  mkdirSync(`${DIR}/ws/alpha/dist/shot`, { recursive: true });
  writeFileSync(`${DIR}/ws/alpha/dist/contract-row.apk`, 'an artifact');
  writeFileSync(`${DIR}/ws/alpha/dist/shot/contract-row.png`, 'a shot');
  const was = (await get('/api/design?project=alpha')).body;
  await post('/api/design', { project: 'alpha', action: 'save', language: was.language,
    pages: [...(was.pages || []), { name: 'a page the contract types', platform: 'web', frame: 'desktop', template: 'blank', blocks: [] }] });
  writeFileSync(`${DIR}/contract-run.log`, '[dashboard-test] == contract.mjs ==\nPASS  [+0.2s] a test the contract types\n1 passed, 0 failed in 1.0s\n');
  bb('tests', 'ingest', `${DIR}/contract-run.log`);
}

// ---- every GET the app makes answers with the fields it reads ------------------------
// Against the fixture project alpha, which has a roadmap, bugs, rules and a
// dist/ from the other files' fixtures, or empty lists, which still carry
// the keys.
let missing = [], typed = [], rowless = [];
for (const e of surface.endpoints) {
  if (e.method !== 'GET') continue;
  // A download is bytes and has no fields to check: what it owes is that the
  // path still serves the file, which is what the app's own self-update rides
  // on. Asked with a file put there for the purpose rather than whatever the
  // other suites happen to have left in alpha's dist/.
  if (e.binary) {
    mkdirSync(`${DIR}/ws/alpha/dist`, { recursive: true });
    writeFileSync(`${DIR}/ws/alpha/dist/surface-probe.bin`, 'not json\n');
    const r = await fetch(`${URL.replace(/\/$/, '')}/api/artifact?project=alpha&path=`
                          + encodeURIComponent('dist/surface-probe.bin'), { headers: H });
    const body = await r.text();
    if (r.status !== 200 || body !== 'not json\n')
      missing.push(`${e.path}: HTTP ${r.status}, ${body.slice(0, 40)}`);
    rmSync(`${DIR}/ws/alpha/dist/surface-probe.bin`, { force: true });
    continue;
  }
  // One the contract names and another suite asks: it takes an id only a
  // fixture of that suite's has, and the entry says which suite that is.
  if (e.needs) continue;
  const path = e.path.replace('project=&', 'project=alpha&').replace(/project=$/, 'project=alpha');
  const r = await get(path);
  if (r.status !== 200) { missing.push(`${e.path}: HTTP ${r.status} ${r.body?.error || ''}`); continue; }
  for (const f of e.fields || []) if (!(f in r.body)) missing.push(`${e.path}: no "${f}" in the answer`);
  // ...and each as the type the app reads it as (R79 step 8).
  typed.push(...pinBreaks(r.body, (surface.types || {})[e.path], e.path));
  // The rows' fields, on the first row where there is one; a field pinned
  // with ? is one only some rows carry (a kind's own), so it may be absent.
  const pins = (surface.types || {})[e.path] || {};
  for (const [key, want] of Object.entries(e)) {
    if (['method', 'path', 'fields', 'actions', 'binary', 'needs'].includes(key)) continue;
    const rows = r.body[key];
    if (!Array.isArray(rows) || !rows.length) { if (Array.isArray(rows)) rowless.push(`${e.path} ${key}`); continue; }
    for (const f of want)
      if (!(f in rows[0]) && !(`${key}[].${f}?` in pins)) missing.push(`${e.path}: rows of "${key}" carry no "${f}"`);
  }
}
ok(missing.length === 0, `every path the app reads answers with the fields it draws${missing.length ? ': ' + missing.join('; ') : ''}`);
// Every row field the app reads is pinned a type, so a list the fixture
// leaves empty still says what its rows hold, and is held to it wherever a
// row turns up (B107).
const untyped = [];
for (const e of surface.endpoints) {
  if (e.method !== 'GET' || e.needs) continue;
  const pins = (surface.types || {})[e.path] || {};
  for (const [key, want] of Object.entries(e)) {
    if (['method', 'path', 'fields', 'actions', 'binary', 'needs'].includes(key)) continue;
    for (const f of want)
      if (![`${key}[].${f}`, `${key}[].${f}?`, `${key}.${f}`].some(k => k in pins)) untyped.push(`${e.path} ${key}[].${f}`);
  }
}
ok(untyped.length === 0, `...and every row field it reads is pinned a type${untyped.length ? ': not ' + untyped.join(', ') : ''}`);
// The lists seeded above, and those another suite fills (the bell's rows,
// the phone's asks, a node's jobs and instances), held to it here when the
// world has one: which had no row this time is said, not failed.
ok(true, `the row lists with no row to type this run: ${rowless.join(', ') || 'none'}`);
// A field pinned a type is one the app reads: removed or retyped, it fails
// here until the release after the app stopped reading it (api-surface.json).
const unpinned = Object.keys(surface.types || {}).filter(p => !surface.endpoints.some(e => e.path === p && e.method === 'GET'));
ok(typed.length === 0 && unpinned.length === 0,
   `...each as the type the app reads it as${typed.length ? ': ' + typed.join('; ') : ''}${unpinned.length ? '; types for no GET: ' + unpinned.join(', ') : ''}`);

// ---- every POST action the app sends is one the server knows --------------------------
// Read from the source rather than sent: a real send would change the
// fixture. The handler for each path, or the module it calls into (a
// handler is a gate plus one call, R77), names its actions as `act == "x"`
// or a tuple, and each one the contract lists must appear in one of them.
const DASH = join(REPO, 'scripts', 'dashboard');
const serverSrc = readdirSync(DASH).filter(f => f.endsWith('.py'))
  .map(f => readFileSync(join(DASH, f), 'utf8')).join('\n');
let unknown = [];
for (const e of surface.endpoints) {
  if (e.method !== 'POST') continue;
  for (const a of e.actions || []) {
    if (a.startsWith('(')) continue;
    if (!new RegExp(`"${a}"`).test(serverSrc)) unknown.push(`${e.path}: ${a}`);
  }
}
ok(unknown.length === 0, `every action the app posts is one the server names${unknown.length ? ': ' + unknown.join('; ') : ''}`);

await done();
