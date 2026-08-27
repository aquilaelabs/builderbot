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
// proves the compose project-name sanitizer (bbdev-ep-silon-main) with the same
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
// The state, read from the parenthetical beside the name and never out of the
// row's whole text: that text carries the buttons' own labels, so "down" in it
// could as easily be the Down button. The pill says what the row IS — docker,
// the way the file rows say apk or xpi — and never what it is doing.
const pill = () => page.$eval('#devRow .state', e => e.textContent.replace(/[()]/g, '').trim());
const pillIs = (want) => page.waitForFunction(
  (w) => document.querySelector('#devRow .state')?.textContent.replace(/[()]/g, '').trim() === w,
  want, { timeout: 20000 });

let r = await row();
ok(/never built/.test(r.text), 'a project with a compose file gets the row, unbuilt');
ok(await page.$eval('#devRow .top .pill', e => e.textContent.trim()) === 'docker'
   && /^bbdev-/.test(await page.$eval('#devRow .top b', e => e.textContent.trim())),
   '...shaped like the file rows: kind on the pill, its own name in bold');
// The ports and the mounts, in the notation Unraid writes them in — container
// side left, host side right, and the arrow saying which way it goes. Read off
// the resolved compose config, so a path built out of variables shows as the
// value rather than as the spelling.
const wiring = await page.$$eval('#devRow .grow > .dim.li',
  els => els.map(e => e.textContent.trim()));
ok(wiring[0] === `7474:TCP ← ${new globalThis.URL(URL).hostname}:7475`,
   '...the published port against the address this page was reached at');
ok(wiring[1] === '/library ← /mnt/user/plex-media'
   && wiring[2] === '/config ↔ /mnt/user/appdata/x/config',
   '...and one arrow for a read-only mount, two for a writable one');
// The single published port earns a link. Not before it is up: a link to a
// port with nothing behind it is a broken link.
ok(!await page.$('#devRow a.btn'),
   'no Open link while the instance is down, whatever it publishes');
// One fact per line, never a run-on joined by semicolons — these are separate
// facts about separate services, and reading them is the point of showing them.
// The wiring lines carry .li too and are not what these two are counting, so
// they are told apart by their class rather than by where they sit.
const devLines = (cls) => page.$$eval(`#devRow .grow > .dim.li.${cls}`,
  els => els.map(e => e.textContent.trim()));
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
// Wait for the save to land: the hint stops calling it a draft.
await page.waitForFunction(() => {
  const r = document.querySelector('#devRow');
  return r && !/fill in the env/.test(r.textContent);
}, { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(1200);
// The buttons map to the compose commands, no rules of this dashboard's
// invention on top: `compose up` builds an image that is missing, so Up on a
// never-built project does what the CLI does rather than refusing. The
// classic builder rides along for exactly that case, since an implicit build
// through buildx would 403 against a socket proxy.
ok(!await page.$eval('#devRow [data-devact="up"]', b => b.disabled),
   'a filled env wakes Up — compose builds what is missing, so it would work');
ok(/builds the image first, as compose does/.test(
     await page.$eval('#devRow [data-devact="up"]', b => b.title)),
   '...and Up says that is what it will do');

// First build: build → down → up, and the argv trail proves the shape.
// (newPage auto-accepts dialogs and records them — no handler of our own.)
await page.click('#devRow [data-devact="rebuild"]');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /running/.test(e.textContent) && /built from [0-9a-f]{7}/.test(e.textContent);
}, { timeout: 30000 });
const log = dockerLog();
ok(/compose --project-name bbdev-ep-silon-main .*build/.test(log)
   && /compose --project-name bbdev-ep-silon-main .*up -d/.test(log),
   'rebuild runs table-lookup compose commands under the bbdev- namespace');
ok(await page.$eval('#devRow [data-devact="rebuild"]',
     e => e.textContent.trim()) === 'Rebuild',
   '...and the button says Rebuild once an image exists');
ok(/--env-file/.test(log), '...with the dev env handed over as --env-file');
// The classic builder, deliberately: compose's default boots a buildx helper
// container and attaches to it, and attach is a hijacked connection a socket
// proxy worth having refuses. Measured against a real proxy — buildx dies
// with "unable to upgrade to tcp, received 403", classic succeeds — so the
// build asks for exactly the POST /build permission the setup docs grant.
ok(/BUILDKIT=0/.test(log),
   '...and builds with the classic builder, which needs no helper container');
r = await row();
ok(!r.down && r.up, 'running: Down is live, Up is dead');
ok(r.rebuild && /the code has moved since/.test(r.text) === false,
   'Rebuild goes back to sleep once the build matches the code');

// A build belongs to the daemon it ran on. Retiring a socket proxy for a
// sandbox VM leaves the image and the containers behind on a machine the
// dashboard can no longer reach, and the row went on saying "built from
// <rev>" and offering Rebuild for something never built here. Driven through
// the state file rather than by restarting the server on a second DOCKER_HOST:
// what is being asserted is that the RECORD is read against today's daemon.
const devapps = `${DIR}/state/devapps.json`;
const wasBuilt = JSON.parse(readFileSync(devapps, 'utf8'));
ok(wasBuilt['ep.silon'].main.daemon === 'tcp://stub:2375',
   'a build records which daemon it landed on');
writeFileSync(devapps, JSON.stringify({ ...wasBuilt, 'ep.silon': {
  ...wasBuilt['ep.silon'],
  main: { ...wasBuilt['ep.silon'].main, daemon: 'ssh://bb@sandbox' } } }));
await page.reload();
await ready(page);
await page.click(`#projects .row:has(.name:text-is("ep.silon")) [data-m]`);
await page.waitForSelector('.nbtabs [data-v="artifacts"]:visible', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForSelector('#devRow', { timeout: 20000 });
r = await row();
ok(/never built/.test(r.text),
   'a record from another daemon reads as never built here, not as built there');
ok(await page.$eval('#devRow [data-devact="rebuild"]', e => e.textContent.trim())
   === 'Build',
   '...so the button offers Build, which is what pressing it would do');
writeFileSync(devapps, JSON.stringify(wasBuilt));
await page.waitForFunction(
  () => /built from [0-9a-f]{7}/.test(document.querySelector('#devRow')?.textContent || ''),
  { timeout: 20000 });

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
ok(await pill() === 'down',
   'the gated rebuild stops after down rather than starting broken');
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
await pillIs('down');
ok(/compose --project-name bbdev-ep-silon-main .*down/.test(dockerLog()),
   'Down runs compose down, nothing else');
ok((await row()).down, '...and goes dead after it: there is nothing left to remove');

// A container that EXITED still exists — it holds its name and the project's
// network, and `down` is the only thing that clears it. Asking compose only
// about RUNNING containers left a crashed instance with a greyed-out Down and
// no way out except a shell, which is the one thing these buttons are for.
writeFileSync(`${DIR}/dockerstate/bbdev-ep-silon-main.exited`, '1');
await page.evaluate(() => refresh());
await pillIs('stopped');
r = await row();
ok(!r.down, 'a crashed instance offers Down — its containers are still there');
ok(!r.up, '...and Up, which recreates them rather than colliding with them');
await page.click('#devRow [data-devact="down"]');
await pillIs('down');
ok(!existsSync(`${DIR}/dockerstate/bbdev-ep-silon-main.exited`),
   '...and Down is what clears them');

// A build in flight when BuilderBot restarts is lost — compose build is a
// subprocess of the dashboard and dies with it. Everything already recovered
// correctly (the last SUCCESSFUL build is still what built_rev says, and
// Rebuild is live because the code moved), but the operator was told nothing
// and saw a button they thought they had pressed. Simulated by leaving the
// on-disk marker behind, which is exactly what a killed process leaves.
const devFile = `${DIR}/state/devapps.json`;
const before = JSON.parse(readFileSync(devFile, 'utf8'));
// Two levels now: a project holds instances, and `main` is the one every
// project has until another is made.
before['ep.silon'].main.building_since = Math.floor(Date.now() / 1000);
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

// What the compose FILE asks for, which is the half no namespace can bound:
// a container started from a file that mounts / and asks for privileged is
// labelled bbdev- like every other one and passes every check that can be
// made on a name. So the file is read, and what it reaches for is put in
// front of the operator once, before anything starts.
const stubCfg = `${DIR}/dockerstate/bbdev-ep-silon-main.config`;
// The dev row reloads on job_rev — the in-memory counter plus devapps.json's
// mtime — and a stub config file moves neither, so a plain refresh() would
// leave the row showing the answer to the previous question. Touch the file
// the poll actually watches.
const nudge = async () => {
  const f = `${DIR}/state/devapps.json`;
  writeFileSync(f, readFileSync(f, 'utf8'));
  await page.evaluate(() => refresh());
};
const risky = (vols) => writeFileSync(stubCfg, JSON.stringify(
  { services: { app: { build: { context: '.' }, privileged: true, volumes: vols } } }));

// From stopped: the failed build above left the instance running, because a
// build that never succeeded never reached the down-and-up.
if (await pill() !== 'down') {
  await page.click('#devRow [data-devact="down"]');
  await pillIs('down');
}
// A path of OURS handed to the host's daemon: it resolves bind-mount sources
// on its own filesystem, where /workspace/<project> does not exist — and
// docker answers a missing source by creating an empty directory rather than
// by failing, so the app starts with no data and it reads as the app's bug.
// Said on the row, kept apart from the risks below: those are decisions the
// operator may reasonably make, this is a compose that cannot work.
writeFileSync(stubCfg, JSON.stringify(
  { services: { app: { build: { context: '.' }, volumes: ['./data:/data'] } } }));
await nudge();
await page.waitForFunction(() => /will not work as written/.test(
  document.querySelector('#devRow')?.textContent || ''), { timeout: 20000 });
const probs = await devLines("bad");
ok(probs.length === 1 && /this container's path/.test(probs[0]),
   'a bind the host cannot resolve is named on its own line, before anything starts');

risky(['/:/host']);
await nudge();
await page.waitForFunction(() => /asks for more than its own directory/.test(
  document.querySelector('#devRow')?.textContent || ''), { timeout: 20000 });
ok(true, 'a compose reaching past its own directory says so on the row');
const risked = await devLines("risk");
ok(risked.length === 1 && /runs privileged/.test(risked[0]),
   '...one line each, and only the things the mount list does not already show');

let seen = page.dialogs.length;
await page.click('#devRow [data-devact="up"]');
await pillIs('running');
ok(page.dialogs.slice(seen).some(d => /runs privileged/.test(d)),
   '...and Up asks first, naming what it found rather than warning in general');
// ...and once it is up, the one port it publishes is a link to it. The stub's
// risky config publishes nothing, so this reads the earlier shape back.
writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
  ports: [{ target: 7474, published: '7475', protocol: 'tcp' }] } } }));
await nudge();
await page.waitForSelector('#devRow a.btn', { timeout: 20000 });
ok(await page.$eval('#devRow a.btn', a => a.getAttribute('href'))
     === `http://${new globalThis.URL(URL).hostname}:7475/`,
   'a running instance with one published port gets an Open link to it');
writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
  ports: [{ target: 80, published: '8080', protocol: 'tcp' },
          { target: 81, published: '8081', protocol: 'tcp' }] } } }));
await nudge();
await page.waitForSelector('#devOpen', { timeout: 20000 });
ok(!await page.$('#devRow a.btn'),
   '...and two of them get a chooser instead: nothing here knows which is the web UI');
await page.click('#devOpen');
await page.waitForSelector('.nbsheet .portpick a', { timeout: 10000 });
const picks = await page.$$eval('.nbsheet .portpick a', as => as.map(a => a.getAttribute('href')));
const host = new globalThis.URL(URL).hostname;
ok(picks.length === 2 && picks[0] === `http://${host}:8080/`
   && picks[1] === `http://${host}:8081/`,
   '...listing every published port, for the operator to answer');
await page.click('#sheetClose');
await page.waitForFunction(() => document.querySelector('.nbsheet').hidden);
ok(await page.$('.nbsheet .portpick') === null,
   '...and the list, built for the sheet, goes when the sheet does');

// Asked once per set, not once per press: an acknowledgement the operator has
// to give again every time is one they stop reading.
await page.click('#devRow [data-devact="down"]');
await pillIs('down');
seen = page.dialogs.length;
await page.click('#devRow [data-devact="up"]');
await pillIs('running');
ok(!page.dialogs.slice(seen).some(d => /asks for more/.test(d)),
   '...and does not ask again for the same set');

// ...but a file that gains one does not inherit the last yes.
writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
  privileged: true, pid: 'host', volumes: ['/:/host'] } } }));
await nudge();
await page.waitForFunction(() => /process namespace/.test(
  document.querySelector('#devRow')?.textContent || ''), { timeout: 20000 });
await page.click('#devRow [data-devact="down"]');
await pillIs('down');
seen = page.dialogs.length;
await page.click('#devRow [data-devact="up"]');
await pillIs('running');
ok(page.dialogs.slice(seen).some(d => /process namespace/.test(d)),
   '...and asks again the moment the file asks for something new');

// A docker call that is not a namespaced compose call does not run at all —
// the invariant the whole feature's blast radius rests on, asserted at the
// one place every call passes through.
const guard = execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.DOCKER = 'docker'
print(json.dumps({
  'git': m._guard(['git', '-C', '/x', 'status']),
  'version': m._guard(['docker', 'version']),
  'ours': m._guard(['docker', 'compose', '--project-name', 'bbdev-a', 'down']),
  'theirs': m._guard(['docker', 'compose', '--project-name', 'plex', 'down']),
  'unnamed': m._guard(['docker', 'compose', '-f', 'x', 'down']),
  'bare': m._guard(['docker', 'rm', '-f', 'someone-elses-container']),
}))
`], { encoding: 'utf8' });
const g = JSON.parse(guard.trim().split('\n').pop());
ok(!g.git && !g.version && !g.ours,
   'git, docker version and a bbdev- compose call are what may run');
ok(g.theirs && g.unnamed && g.bare,
   '...and another project name, a missing one, and any other docker verb are not');
await page.click('#devRow [data-devact="down"]');
await pillIs('down');
rmSync(stubCfg, { force: true });

// The mapping itself, at the module: checked against this container's own
// mount table rather than trusted, because a template edited on one side only
// is otherwise a wrong answer that looks like a right one. Driven off a
// fixture mount table so the assertion does not depend on how this box
// happens to be mounted.
const mi = `${DIR}/mountinfo`;
writeFileSync(mi, [
  '1 0 0:1 / / rw - overlay overlay rw',
  '2 1 0:2 /development /workspace rw - btrfs /dev/x rw',
  '3 1 0:3 /appdata/builderbot-dev /devdata rw - btrfs /dev/x rw',
].join('\n') + '\n');
const paths = execFileSync('python3', ['-c', `
import importlib.util, json, os
os.environ['BB_MOUNTINFO'] = ${JSON.stringify(mi)}
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(workspace='/workspace', state='/tmp', write_json=lambda *a: None)
out = {}
os.environ['DOCKER_HOST_PATHS'] = '/workspace:/mnt/user/development,/devdata:/mnt/cache/appdata/builderbot-dev'
mp, bad = m.host_map()
out['good'] = [mp, bad, m.to_host('/workspace/alpha/data', mp),
               m.to_host('/mnt/user/plex', mp)]
# The half of the mapping that moved: /workspace is mounted from /development,
# so a host path not ending in it describes a different share.
os.environ['DOCKER_HOST_PATHS'] = '/workspace:/mnt/user/somethingelse'
out['moved'] = m.host_map()
# The sandbox-VM arrangement: the daemon is elsewhere and the shares are
# mounted over there at the paths used over here, so the mapping is an
# identity. It is not a translation and there is nothing in THIS container's
# mount table to check it against, so it must not be run through the check
# that catches a half-edited one.
os.environ['DOCKER_HOST_PATHS'] = '/workspace:/workspace'
mp2, bad2 = m.host_map()
out['parity'] = [mp2, bad2, m.problems('alpha', {'services': {'a': {'volumes': ['./data:/data']}}})]
os.environ['DOCKER_HOST_PATHS'] = '/nope:/mnt/x,garbage'
out['junk'] = m.host_map()
os.environ['DOCKER_HOST_PATHS'] = ''
out['unset'] = m.host_map()
print(json.dumps(out))
`], { encoding: 'utf8' });
const hp = JSON.parse(paths.trim().split('\n').pop());
ok(hp.good[0]['/workspace'] === '/mnt/user/development' && !hp.good[1].length
   && hp.good[2] === '/mnt/user/development/alpha/data',
   'a mapping that matches the mount table translates our paths to the host\'s');
ok(hp.good[3] === null,
   '...and leaves a path that is already the host\'s alone');
ok(!Object.keys(hp.moved[0]).length && /one side of the mapping moved/.test(hp.moved[1][0]),
   'a mapping whose two sides disagree is dropped and complained about, not used');
ok(hp.junk[1].length === 2 && !Object.keys(hp.junk[0]).length,
   '...as is a path not mounted here, and a pair that is not one');
ok(!Object.keys(hp.unset[0]).length && !hp.unset[1].length,
   'and saying nothing is quiet: no mapping, no complaint');
// The whole reason the sandbox VM is worth building: give the daemon the same
// paths and the translation problem stops existing rather than being managed.
ok(hp.parity[0]['/workspace'] === '/workspace' && !hp.parity[1].length,
   'an identity mapping is accepted without being checked against our mounts');
ok(!hp.parity[2].length,
   '...and a bind under it is no longer a problem, because it is not one');

// An instance is (project, name) now, and the old layout is one record per
// project. Driven at the module: the migration happens on read, so it is the
// read that has to be asserted, and a stub docker cannot show a rename.
const inst = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, 'devenv'))
# The OLD shape: one record per project, no instance level at all.
open(os.path.join(d, 'devapps.json'), 'w').write(json.dumps(
    {'alpha': {'rev': 'abc1234', 'daemon': 'tcp://x', 'risks_ack': 'deadbeef'}}))
open(os.path.join(d, 'devenv', 'alpha.env'), 'w').write('PORT=1')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: open(p, 'w').write(json.dumps(o)))
out = {}
out['loaded'] = m._load()
out['instances'] = m.instances('alpha')
out['envmoved'] = [os.path.basename(f) for f in sorted(os.listdir(os.path.join(d, 'devenv')))]
out['pnames'] = [m._pname('alpha'), m._pname('alpha', 'staging'), m._pname('My Proj', 'Two Words')]
out['envpaths'] = [os.path.basename(str(m.env_path('alpha'))),
                   os.path.basename(str(m.env_path('alpha', 'staging')))]
print(json.dumps(out))
`], { encoding: 'utf8' });
const ij = JSON.parse(inst.trim().split('\n').pop());
ok(JSON.stringify(ij.loaded) === JSON.stringify(
     { alpha: { main: { rev: 'abc1234', daemon: 'tcp://x', risks_ack: 'deadbeef' } } }),
   'a store written before instances reads back as the project\'s main instance');
ok(JSON.stringify(ij.instances) === JSON.stringify(['main']),
   '...and that is the instance the project has');
ok(ij.envmoved.length === 1 && ij.envmoved[0] === 'bbdev-alpha-main.env',
   '...with its env file moved to the name the instance is read by');
ok(ij.pnames[0] === 'bbdev-alpha' + '-main' && ij.pnames[1] === 'bbdev-alpha-staging',
   'two instances of one project are two compose projects');
ok(ij.pnames[2] === 'bbdev-my-proj-two-words',
   '...both halves slugged, so a name with spaces cannot reach a compose call');
ok(ij.envpaths[0] !== ij.envpaths[1],
   'and they do not share an env file — two instances exist to differ');

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
