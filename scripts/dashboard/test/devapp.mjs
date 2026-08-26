// The dev instance: a project's compose app, built and run through the host's
// daemon, controlled from the Artifacts tab in the file rows' own language.
//
// Everything here drives the stub docker the harness provides — the argv it
// records IS the assertion, because the module's whole safety story is that
// the buttons run table-lookup compose commands and nothing else.
import { launch, newPage, ok, done, ready, sleep, URL, DIR } from './lib.mjs';
import { writeFileSync, readFileSync, rmSync, existsSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

// ep.silon gets the compose file — delta is the harness's EXCLUDED fixture
// and never shows a notebook button. The dot in the name is a bonus: it
// proves the compose project-name sanitizer (bbdev-ep-silon) with the same
// fixture that proves tmux's.
const D = `${DIR}/ws/ep.silon`;
writeFileSync(`${D}/docker-compose.yml`,
  'services:\n  app:\n    image: delta-dev\n    build: .\n');
writeFileSync(`${D}/.env.example`, 'PORT=8080\n');
const env = {
  ...process.env,
  GIT_AUTHOR_NAME: 'T', GIT_AUTHOR_EMAIL: 't@x.invalid',
  GIT_COMMITTER_NAME: 'T', GIT_COMMITTER_EMAIL: 't@x.invalid',
};
execFileSync('git', ['-C', D, 'add', '-A'], { env });
execFileSync('git', ['-C', D, 'commit', '-qm', 'compose'], { env });

const dockerLog = () => {
  try { return readFileSync(`${DIR}/dockerstate/docker.log`, 'utf8'); }
  catch { return ''; }
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
await page.click(`#projects .row:has(.name:text-is("ep.silon")) [data-m]`);
await page.waitForSelector('.nbtabs [data-v="artifacts"]:visible', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForSelector('#devRow', { timeout: 20000 });

const row = () => page.$eval('#devRow', e => ({
  text: e.textContent.replace(/\s+/g, ' ').trim(),
  up: e.querySelector('[data-devact="up"]').disabled,
  down: e.querySelector('[data-devact="down"]').disabled,
  rebuild: e.querySelector('[data-devact="rebuild"]').disabled,
}));

let r = await row();
ok(/never built/.test(r.text), 'a project with a compose file gets the row, unbuilt');
ok(await page.$eval('#devRow [data-devact="rebuild"]',
     e => e.textContent.trim()) === 'Build',
   'the button says Build before a first image exists — nothing auto-builds');
ok(!r.rebuild, '...and it is live for that first build');
ok(r.up, '...and Up is dead: the env is missing PORT, and starting against a '
        + 'known-missing env is a crash with extra steps');
ok(r.down, '...and Down is dead with nothing running');

// Fill the env through the editor.
await page.click('#devRow [data-devact="env"]');
await page.waitForSelector('#devEnvModal:not([hidden])');
ok(/missing against \.env\.example: PORT/.test(
     await page.$eval('#devEnvModal .hint', e => e.textContent)),
   'the env editor says which keys the example declares and this does not');
// An empty env opens on the example rather than on a blank box under a list
// of names the operator would have to type out.
const seeded = await page.$eval('#devEnvModal textarea', e => e.value);
ok(/PORT=8080/.test(seeded) && /Started from this project/.test(seeded),
   '...and opens on the example, seeded, when nothing is stored yet');
ok(/nothing saved yet/.test(await page.$eval('#devEnvModal .hint', e => e.textContent)),
   '...saying it is a draft, since a seeded box has not been written');
await page.fill('#devEnvModal textarea', 'PORT=9090\n');
await page.click('#devEnvModal .primary');
await page.waitForSelector('#devEnvModal', { state: 'hidden' });
await page.waitForFunction(() => {
  const b = document.querySelector('#devRow [data-devact="up"]');
  return b && !b.disabled;
}, { timeout: 20000 });
ok(true, 'saving an env that answers the example brings Up alive');

// First build: build → down → up, and the argv trail proves the shape.
// (newPage auto-accepts dialogs and records them — no handler of our own.)
await page.click('#devRow [data-devact="rebuild"]');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /running/.test(e.textContent) && /built from [0-9a-f]{7}/.test(e.textContent);
}, { timeout: 30000 });
const log = dockerLog();
ok(/compose --project-name bbdev-ep-silon .*build/.test(log)
   && /compose --project-name bbdev-ep-silon .*up -d/.test(log),
   'rebuild runs table-lookup compose commands under the bbdev- namespace');
ok(await page.$eval('#devRow [data-devact="rebuild"]',
     e => e.textContent.trim()) === 'Rebuild',
   '...and the button says Rebuild once an image exists');
ok(/--env-file/.test(log), '...with the dev env handed over as --env-file');
r = await row();
ok(!r.down && r.up, 'running: Down is live, Up is dead');
ok(r.rebuild && /the code has moved since/.test(r.text) === false,
   'Rebuild goes back to sleep once the build matches the code');

// The code moves — Rebuild wakes.
writeFileSync(`${D}/newfile.txt`, 'x');
execFileSync('git', ['-C', D, 'add', '-A'], { env });
execFileSync('git', ['-C', D, 'commit', '-qm', 'more'], { env });
await page.evaluate(() => refresh());
await page.waitForFunction(() => {
  const b = document.querySelector('#devRow [data-devact="rebuild"]');
  return b && !b.disabled;
}, { timeout: 20000 });
ok(true, 'a commit unghosts Rebuild — the code has moved since the build');

// The env gate: the example gains a key, and the rebuild stops after down
// with the old env preserved in comments.
writeFileSync(`${D}/.env.example`, 'PORT=8080\nAPI_KEY=\n');
execFileSync('git', ['-C', D, 'add', '-A'], { env });
execFileSync('git', ['-C', D, 'commit', '-qm', 'needs a key'], { env });
await page.click('#devRow [data-devact="rebuild"]');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /fill in the env/.test(e.textContent);
}, { timeout: 30000 });
r = await row();
ok(/stopped/.test(r.text), 'the gated rebuild stops after down rather than starting broken');
await page.click('#devRow [data-devact="env"]');
await page.waitForSelector('#devEnvModal:not([hidden])');
const gated = await page.$eval('#devEnvModal textarea', e => e.value);
ok(/API_KEY=/.test(gated) && /# old: PORT=9090/.test(gated),
   '...and the editor holds the new example with the old values in comments');
await page.fill('#devEnvModal textarea', 'PORT=9090\nAPI_KEY=abc\n');
await page.click('#devEnvModal .primary');
await page.waitForSelector('#devEnvModal', { state: 'hidden' });
await page.waitForFunction(() => {
  const b = document.querySelector('#devRow [data-devact="up"]');
  return b && !b.disabled;
}, { timeout: 20000 });
await page.click('#devRow [data-devact="up"]');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /running/.test(e.textContent);
}, { timeout: 20000 });
ok(true, '...and Up is manual after the gate, exactly as asked');

// Down, from the row.
await page.click('#devRow [data-devact="down"]');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /stopped/.test(e.textContent);
}, { timeout: 20000 });
ok(/compose --project-name bbdev-ep-silon .*down/.test(dockerLog()),
   'Down runs compose down, nothing else');

// A build in flight when BuilderBot restarts is lost — compose build is a
// subprocess of the dashboard and dies with it. Everything already recovered
// correctly (the last SUCCESSFUL build is still what built_rev says, and
// Rebuild is live because the code moved), but the operator was told nothing
// and saw a button they thought they had pressed. Simulated by leaving the
// on-disk marker behind, which is exactly what a killed process leaves.
const devFile = `${DIR}/state/devapps.json`;
const before = JSON.parse(readFileSync(devFile, 'utf8'));
before['ep.silon'].building_since = Math.floor(Date.now() / 1000);
writeFileSync(devFile, JSON.stringify(before));
await page.evaluate(() => refresh());
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /a build was interrupted/.test(e.textContent);
}, { timeout: 20000 });
ok(/still on [0-9a-f]{7}/.test(await page.$eval('#devRow', e => e.textContent)),
   'an interrupted build says so, and still names the last one that finished');
// And it clears the moment a build reaches any end, rather than sticking.
// The code has to move first: Rebuild is correctly asleep while the last
// build matches HEAD, interrupted marker or not — the marker says what
// happened, it does not invent work to do.
writeFileSync(`${D}/after-interrupt.txt`, 'x');
execFileSync('git', ['-C', D, 'add', '-A'], { env });
execFileSync('git', ['-C', D, 'commit', '-qm', 'moves on'], { env });
// No nudge: the commit moves the project's reflog, and the poll watches it.
// Before that key existed this verdict only refreshed when something else
// happened to move, so Rebuild slept through the commit that should wake it.
await page.waitForFunction(() => {
  const b = document.querySelector('#devRow [data-devact="rebuild"]');
  return b && !b.disabled;
}, { timeout: 20000 });
await page.click('#devRow [data-devact="rebuild"]');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && !/a build was interrupted/.test(e.textContent);
}, { timeout: 30000 });
ok(!JSON.parse(readFileSync(devFile, 'utf8'))['ep.silon'].building_since,
   '...and the marker is gone once a build reaches an end, whichever end');

// A failed build says so and starts nothing.
mkdirSync(`${DIR}/dockerstate`, { recursive: true });
writeFileSync(`${DIR}/dockerstate/build.fail`, '1');
writeFileSync(`${D}/again.txt`, 'x');
execFileSync('git', ['-C', D, 'add', '-A'], { env });
execFileSync('git', ['-C', D, 'commit', '-qm', 'again'], { env });
await page.evaluate(() => refresh());
await page.waitForFunction(() => {
  const b = document.querySelector('#devRow [data-devact="rebuild"]');
  return b && !b.disabled;
}, { timeout: 20000 });
await page.click('#devRow [data-devact="rebuild"]');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /build failed/.test(e.textContent);
}, { timeout: 30000 });
ok(/stub build exploded/.test(await page.$eval('#devRow', e => e.textContent)),
   'a failed build shows its own last words, and nothing was started');
rmSync(`${DIR}/dockerstate/build.fail`, { force: true });

// DOCKER_HOST=auto resolves by asking candidates for /version, caches what
// it found, and re-scans when that stops answering — a bridge-assigned IP
// moves when containers restart in a different order, so an address read
// once at boot goes stale. Driven at the module directly: the scan is
// network behaviour, not something a stub docker binary can show.
const dh = execFileSync('python3', ['-c', `
import importlib.util, os, sys, json
os.environ['DOCKER_HOST'] = 'auto'
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(workspace='/tmp', state='/tmp', write_json=lambda *a: None)
# Nothing answers on a made-up bridge, so this must come back empty rather
# than inventing an address.
m._found.update(addr='', at=0)
found = m.docker_host()
# An explicit address is passed through untouched — an operator who typed
# one means it.
os.environ['DOCKER_HOST'] = 'tcp://example.invalid:2375'
print(json.dumps({'auto': found, 'explicit': m.docker_host()}))
`], { encoding: 'utf8' });
const dhj = JSON.parse(dh.trim().split('\n').pop());
ok(dhj.explicit === 'tcp://example.invalid:2375',
   'an explicit DOCKER_HOST is used verbatim, never second-guessed by a scan');
ok(typeof dhj.auto === 'string',
   'auto resolves to an address or to nothing, never to an error');


ok((await page.errors).length === 0, 'no console errors from the dev row');

// The fixture goes back the way artifacts.mjs leaves alpha.
rmSync(`${D}/docker-compose.yml`, { force: true });
rmSync(`${D}/.env.example`, { force: true });
rmSync(`${D}/newfile.txt`, { force: true });
rmSync(`${D}/again.txt`, { force: true });
rmSync(`${D}/after-interrupt.txt`, { force: true });
rmSync(`${D}/.git`, { recursive: true, force: true });
execFileSync('git', ['-C', D, 'init', '-q', '.'], { env });
await done(browser);
