// The companion app's contract. android/api-surface.json names every path
// the app calls and the fields it reads from each answer, and carries the
// number server.py's APP_API and the app's TARGET_API both carry. This file
// holds the running dashboard to that: a path that stops answering, a field
// that is renamed, or a number moved on one side and not the others fails
// here, before the app finds out by drawing blanks. Moving the surface is
// fine; moving it without the app is what this catches.
import { ok, done, URL, DIR } from './lib.mjs';
import { readFileSync, writeFileSync, mkdirSync, rmSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const base = URL.replace(/\/$/, '');
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const get = async p => { const r = await fetch(base + p, { headers: H }); return { status: r.status, body: await r.json() }; };

const surface = JSON.parse(readFileSync(join(REPO, 'android', 'api-surface.json'), 'utf8'));
const gradle = readFileSync(join(REPO, 'android', 'app', 'build.gradle.kts'), 'utf8');
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

// ---- every GET the app makes answers with the fields it reads ------------------------
// Against the fixture project alpha, which has a roadmap, bugs, rules and a
// dist/ from the other files' fixtures, or empty lists, which still carry
// the keys.
let missing = [];
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
  const path = e.path.replace('project=&', 'project=alpha&').replace(/project=$/, 'project=alpha');
  const r = await get(path);
  if (r.status !== 200) { missing.push(`${e.path}: HTTP ${r.status} ${r.body?.error || ''}`); continue; }
  for (const f of e.fields || []) if (!(f in r.body)) missing.push(`${e.path}: no "${f}" in the answer`);
  // The rows' fields, on the first row where there is one.
  for (const [key, want] of Object.entries(e)) {
    if (['method', 'path', 'fields', 'actions', 'binary'].includes(key)) continue;
    const rows = r.body[key];
    if (!Array.isArray(rows) || !rows.length) continue;
    for (const f of want) if (!(f in rows[0])) missing.push(`${e.path}: rows of "${key}" carry no "${f}"`);
  }
}
ok(missing.length === 0, `every path the app reads answers with the fields it draws${missing.length ? ': ' + missing.join('; ') : ''}`);

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
