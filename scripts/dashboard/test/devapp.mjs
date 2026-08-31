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
// proves the compose project-name sanitizer (ep-silon) with the same
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
await page.waitForSelector('#devRow', { state: 'attached', timeout: 20000 });

// The controls live on the Docker manager now — the artifact row only sends
// you there — so everything that presses one drives it from that tab.
const DM = '.dmtab .row[data-inst^="ep.silon|"]';
// Unconditional, because openTab focuses a tab that is already open and
// openDocker reloads the list either way. A guard on "is the row already
// there" broke the moment another tab took the pane: the row was absent, the
// guard did not re-open it, and the click waited for something never coming.
async function openManager(){
  await page.click('#bDocker');
  await page.waitForSelector(DM, { timeout: 20000 });
}
async function dmClick(act){
  await openManager();
  await page.click(`${DM} [data-dm="${act}"]`);
}
async function dmDisabled(act){
  await openManager();
  return page.$eval(`${DM} [data-dm="${act}"]`, b => b.disabled);
}
// The manager repaints from its own fetch, not the artifacts poll, so a test
// that acted through the API has to ask it to look again.
// Bring the artifact row's tab back in front. openManager leaves the manager
// there, and anything that CLICKS on the row needs it visible again — reading
// what the row rendered does not, which is why most assertions here wait on
// attachment instead.
async function showRow(){
  await page.click('#projects .row:has(.name:text-is("ep.silon")) [data-m]');
  await page.waitForSelector('#devRow', { timeout: 20000 });
}
async function dmRefresh(){
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  await openManager();
}
// The manager lists what has been SENT to it — a project with a compose file
// no longer gets a phantom row there — so the fixture's instance has to exist
// before anything can be pressed on it. Through the API rather than the modal:
// the modal builds as well as creates, which is its whole point and exactly
// what the tests below want to watch happening for the first time.
await page.evaluate(async () => {
  await fetch('/api/devapp', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'ep.silon', action: 'new', instance: 'main' }) });
});

const row = async () => ({
  text: await page.$eval('#devRow', e => e.textContent.replace(/\s+/g, ' ').trim()),
  up: await dmDisabled('up'),
  down: await dmDisabled('down'),
  rebuild: await dmDisabled('rebuild'),
});
// The state, read from the parenthetical beside the name and never out of the
// row's whole text: that text carries the buttons' own labels, so "down" in it
// could as easily be the Down button. The pill says what the row IS — docker,
// the way the file rows say apk or xpi — and never what it is doing.
const pill = () => page.$eval(`${DM} .state`, e => e.textContent.replace(/[()]/g, '').trim());
const pillIs = async (want) => { await openManager(); return page.waitForFunction(
  ([w, sel]) => document.querySelector(sel + ' .state')?.textContent.replace(/[()]/g, '').trim() === w,
  [want, DM], { timeout: 20000 }); };

let r = await row();
ok(await page.$eval('#devRow .top .pill', e => e.textContent.trim()) === 'docker'
   && await page.$eval('#devRow .top b', e => e.textContent.trim()) === 'ep-silon',
   'a project with a compose file gets the row: kind on the pill, its own name in bold');
// What the row does NOT say any more. The build state and the wiring were here
// while this screen ran the container; building, Up and Down all live in the
// Docker manager now, and a second copy of a container's ports and mounts on
// the tab you send it FROM is a thing to keep in step for no reader.
ok(!/never built/.test(r.text),
   '...and says nothing where it used to name a Build button this screen no longer has');
ok(await page.$$eval('#devRow .grow > .dim.li:not(.warn)', els => els.length) === 0,
   '...nor its ports and mounts, which the manager folds open per container');
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
ok(await page.$eval(`${DM} [data-dm="rebuild"]`,
     e => e.textContent.trim()) === 'Build',
   'the button says Build before a first image exists — nothing auto-builds');
ok(!r.rebuild, '...and it is live for that first build');
ok(r.up, '...and Up is dead: the env is missing PORT, and starting against a '
        + 'known-missing env is a crash with extra steps');
ok(r.down, '...and Down is dead with nothing running');

// Fill the env through the editor.
await dmClick('env');
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
ok(!await page.$eval(`${DM} [data-dm="up"]`, b => b.disabled),
   'a filled env wakes Up — compose builds what is missing, so it would work');
ok(/builds the image first, as compose does/.test(
     // data-tip, not title: the manager's controls carry the page's own
     // tooltip now, which is the same words moved off an attribute that waits
     // a second before showing them.
     await page.$eval(`${DM} [data-dm="up"]`, b => b.dataset.tip)),
   '...and Up says that is what it will do');

// First build: build → down → up, and the argv trail proves the shape.
// (newPage auto-accepts dialogs and records them — no handler of our own.)
await dmClick('rebuild');
// Watched on the MANAGER's row, which is where a container's state lives now.
// The Artifacts row used to carry it and no longer does — building and running
// moved here, and the state moved with them.
// A running instance says so and counts its containers; "built from <sha>" is
// what it says when it is NOT running, so waiting for both at once waits for a
// state that cannot exist. The argv trail below is what proves the build ran.
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /built from [0-9a-f]{7}/.test(e.textContent);
}, { timeout: 30000 });
const log = dockerLog();
ok(/compose --project-name ep-silon .*build/.test(log)
   && /compose --project-name ep-silon .*up -d/.test(log),
   'rebuild runs table-lookup compose commands, named for the instance');
ok(await page.$eval(`${DM} [data-dm="rebuild"]`,
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

// A build belongs to the daemon it ran on. Repointing DOCKER_HOST at another
// VM leaves the image and the containers behind on a machine the dashboard can
// no longer reach, and the row went on saying "built from
// <rev>" and offering Rebuild for something never built here. Driven through
// the state file rather than by restarting the server on a second DOCKER_HOST:
// what is being asserted is that the RECORD is read against today's daemon.
const devapps = `${DIR}/state/devapps.json`;
const wasBuilt = JSON.parse(readFileSync(devapps, 'utf8'));
ok(wasBuilt['ep.silon'].main.daemon === 'ssh://bb@stub',
   'a build records which daemon it landed on');
writeFileSync(devapps, JSON.stringify({ ...wasBuilt, 'ep.silon': {
  ...wasBuilt['ep.silon'],
  main: { ...wasBuilt['ep.silon'].main, daemon: 'ssh://bb@sandbox' } } }));
await page.reload();
await ready(page);
await page.click(`#projects .row:has(.name:text-is("ep.silon")) [data-m]`);
await page.waitForSelector('.nbtabs [data-v="artifacts"]:visible', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForSelector('#devRow', { state: 'attached', timeout: 20000 });
r = await row();
ok(!/built from/.test(r.text),
   'a record from another daemon does not read as built here');
ok(await page.$eval(`${DM} [data-dm="rebuild"]`, e => e.textContent.trim())
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
await dmRefresh();
await page.waitForFunction((SEL) => {
  const b = document.querySelector(SEL + ' [data-dm="rebuild"]');
  return b && !b.disabled;
}, DM, { timeout: 20000 });
ok(true, 'a commit unghosts Rebuild — the code has moved since the build');
// ---- a long build is watchable, and stoppable ---------------------------
// Both were missing. The log was assigned after the command returned, so a
// pull was minutes of nothing and then everything at once — a download that
// looked like a hang — and there was no way to interrupt one at all.
writeFileSync(`${DIR}/dockerstate/build.slow`, '1');
await dmClick('rebuild');
await page.waitForFunction(sel => {
  const e = document.querySelector(sel + ' .dmlog');
  return e && /pulling layer/.test(e.textContent);
}, DM, { timeout: 20000 });
ok(true, "the command's output appears while it is still running, not after");
ok(await page.$(`${DM} [data-dm="abort"]`) !== null,
   '...with an Abort beside it, which a build never had');
await dmClick('abort');
await page.waitForFunction(sel => {
  const e = document.querySelector(sel);
  return e && !e.querySelector('[data-dm="abort"]');
}, DM, { timeout: 25000 });
ok(true, '...and pressing it ends the job');
const stoppedText = await page.$eval(DM, e => e.textContent.replace(/\s+/g, ' '));
ok(/stopped/.test(stoppedText),
   `...saying what was kept, because an abort is not an undo (${stoppedText.slice(0, 90)})`);
rmSync(`${DIR}/dockerstate/build.slow`, { force: true });
// Nothing to restore: an aborted build records no rev and never reaches down
// or up, so it leaves the instance exactly as it found it — which is the
// property being asserted anyway. A tidying rebuild here was worse than
// nothing: it recorded a rev, unset "the code has moved", and the gate test
// below then found Rebuild ghosted and never ran.

// The env gate: the example gains a key, and the rebuild stops after down
// with the old env preserved in comments.
writeFileSync(`${D}/.env.example`, 'PORT=8080\nAPI_KEY=\n');
execFileSync('git', ['-C', D, 'add', '-A'], { env });
execFileSync('git', ['-C', D, 'commit', '-qm', 'needs a key'], { env });
await dmClick('rebuild');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /fill in the env/.test(e.textContent);
}, { timeout: 30000 });
ok(await pill() === 'down',
   'the gated rebuild stops after down rather than starting broken');
await dmClick('env');
await page.waitForSelector('#devEnvModal:not([hidden])');
const gated = await page.$eval('#devEnvModal textarea', e => e.value);
ok(/API_KEY=/.test(gated) && /# old: PORT=9090/.test(gated),
   '...and the editor holds the new example with the old values in comments');
await page.fill('#devEnvModal textarea', 'PORT=9090\nAPI_KEY=abc\n');
await page.click('#devEnvModal .primary');
await page.waitForSelector('#devEnvModal', { state: 'hidden' });
await dmRefresh();
await page.waitForFunction((SEL) => {
  const b = document.querySelector(SEL + ' [data-dm="up"]');
  return b && !b.disabled;
}, DM, { timeout: 20000 });
await dmClick('up');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /running/.test(e.textContent);
}, { timeout: 20000 });
ok(true, '...and Up is manual after the gate, exactly as asked');

// Down, from the row.
await dmClick('down');
await pillIs('down');
ok(/compose --project-name ep-silon .*down/.test(dockerLog()),
   'Down runs compose down, nothing else');
ok((await row()).down, '...and goes dead after it: there is nothing left to remove');

// A container that EXITED still exists — it holds its name and the project's
// network, and `down` is the only thing that clears it. Asking compose only
// about RUNNING containers left a crashed instance with a greyed-out Down and
// no way out except a shell, which is the one thing these buttons are for.
writeFileSync(`${DIR}/dockerstate/ep-silon.exited`, '1');
await page.evaluate(() => refresh());
await pillIs('stopped');
r = await row();
ok(!r.down, 'a crashed instance offers Down — its containers are still there');
ok(!r.up, '...and Up, which recreates them rather than colliding with them');
await dmClick('down');
await pillIs('down');
ok(!existsSync(`${DIR}/dockerstate/ep-silon.exited`),
   '...and Down is what clears them');

// An Up that FAILS. The row used to lose everything about it the moment the
// job released: the reply carried the reason to the one browser that pressed
// the button, and the row — which reads the job — was left saying "stopped"
// with no account of why it had not started, and its tail gone.
writeFileSync(`${DIR}/dockerstate/up.fail`, '1');
await dmClick('up');
await page.waitForFunction(() => dockerList?.job?.error, null, { timeout: 20000 })
  .catch(() => {});
const failed = await page.evaluate(() => dockerList?.job || {});
ok(/up failed/.test(failed.error || ''),
   'an Up that fails leaves the reason on the row, not only in the reply');
ok(!failed.running && /mount source path/.test(failed.log || ''),
   '...with the output that ended it still in the tail');
await openManager();
ok(await page.$eval(`${DM} .dmlog`, e => e.dataset.tail === '1'),
   '...and that tail is pinned to its end, which is where the error is');
// Rebuild has to wake for the retry. A build records itself before the up
// that follows it, so a failed up left the row insisting the build was
// current — true, and not what somebody looking at a red row wants offered.
ok(!(await row()).rebuild,
   '...and Rebuild is live again, because the run failed even though the build did not');
rmSync(`${DIR}/dockerstate/up.fail`);
await dmClick('down');
await pillIs('down');

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
await dmRefresh();
await page.waitForFunction((SEL) => {
  const b = document.querySelector(SEL + ' [data-dm="rebuild"]');
  return b && !b.disabled;
}, DM, { timeout: 20000 });
await dmClick('rebuild');
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
await dmRefresh();
await page.waitForFunction((SEL) => {
  const b = document.querySelector(SEL + ' [data-dm="rebuild"]');
  return b && !b.disabled;
}, DM, { timeout: 20000 });
await dmClick('rebuild');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /build failed/.test(e.textContent);
}, { timeout: 30000 });
ok(/stub build exploded/.test(await page.$eval('#devRow', e => e.textContent)),
   'a failed build shows its own last words, and nothing was started');
rmSync(`${DIR}/dockerstate/build.fail`, { force: true });

// What the compose FILE asks for, which is the half no check on a NAME can
// bound: a container started from a file that mounts / and asks for privileged
// is named as innocently as any other. So the file is read, and what it reaches for is put in
// front of the operator once, before anything starts.
const stubCfg = `${DIR}/dockerstate/ep-silon.config`;
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
  await dmClick('down');
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

// Migrate and Make dirs render at all. Both are drawn on THIS page from
// fields overview() did not set, so neither had ever appeared on it: the row
// asked for d.stale_name and d.mkdirs, got undefined, and drew nothing. Two
// buttons that existed only in the source.
// Its own env moved aside first: an instance that has one is set up under
// its current name, and offering it a "migration" from a leftover — which
// Remove deliberately leaves behind — was how a freshly created container got
// a Migrate button pointing at a dead file.
const ownEnv = `${DIR}/state/devenv/ep-silon.env`;
const keptEnv = readFileSync(ownEnv, 'utf8');
rmSync(ownEnv);
writeFileSync(`${DIR}/state/devenv/bbdev-ep-silon.env`, 'PORT=7475\n');
writeFileSync(stubCfg, JSON.stringify({ services: { app: {
  image: 'x', volumes: ['/nowhere-builderbot-has/data:/data'] } } }));
await nudge();
await openManager();
await page.waitForFunction((sel) => document.querySelector(
  sel + ' [data-dm="migrate-name"]'), DM, { timeout: 20000 }).catch(() => {});
ok(await page.$(`${DM} [data-dm="migrate-name"]`) !== null,
   'an instance with things under an old name gets the Migrate button, on the page that has the buttons');
ok(await page.$(`${DM} [data-dm="mkdirs"]`) !== null,
   '...and a bind under a share only the daemon has gets Make dirs, with nothing declared anywhere');
writeFileSync(ownEnv, keptEnv);
rmSync(`${DIR}/state/devenv/bbdev-ep-silon.env`);
await nudge();
await openManager();
await page.waitForFunction((sel) => !document.querySelector(
  sel + ' [data-dm="migrate-name"]'), DM, { timeout: 20000 }).catch(() => {});
ok(await page.$(`${DM} [data-dm="migrate-name"]`) === null,
   '...and Migrate is gone once the instance has an env of its own — a leftover '
   + "is not this instance's past");


risky(['/:/host']);
await nudge();
await page.waitForFunction(() => /asks for more than its own directory/.test(
  document.querySelector('#devRow')?.textContent || ''), { timeout: 20000 });
ok(true, 'a compose reaching past its own directory says so on the row');
const risked = await devLines("risk");
ok(risked.length === 1 && /runs privileged/.test(risked[0]),
   '...one line each, and only the things the mount list does not already show');

let seen = page.dialogs.length;
await dmClick('up');
await pillIs('running');
ok(page.dialogs.slice(seen).some(d => /runs privileged/.test(d)),
   '...and Up asks first, naming what it found rather than warning in general');
// ...and once it is up, the one port it publishes is a link to it. The stub's
// risky config publishes nothing, so this reads the earlier shape back.
writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
  ports: [{ target: 7474, published: '7475', protocol: 'tcp' }] } } }));
await nudge();
// attached, not visible: the manager tab is in front now, and what is being
// asserted is what the row RENDERS, not which pane is on top.
await page.waitForSelector('#devRow a.btn', { state: 'attached', timeout: 20000 });
ok(await page.$eval('#devRow a.btn', a => a.getAttribute('href'))
     === `http://${new globalThis.URL(URL).hostname}:7475/`,
   'a running instance with one published port gets an Open link to it');
writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
  ports: [{ target: 80, published: '8080', protocol: 'tcp' },
          { target: 81, published: '8081', protocol: 'tcp' }] } } }));
await nudge();
await showRow();
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
await dmClick('down');
await pillIs('down');
seen = page.dialogs.length;
await dmClick('up');
await pillIs('running');
ok(!page.dialogs.slice(seen).some(d => /asks for more/.test(d)),
   '...and does not ask again for the same set');

// ...but a file that gains one does not inherit the last yes.
writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
  privileged: true, pid: 'host', volumes: ['/:/host'] } } }));
await nudge();
await page.waitForFunction(() => /process namespace/.test(
  document.querySelector('#devRow')?.textContent || ''), { timeout: 20000 });
await dmClick('down');
await pillIs('down');
seen = page.dialogs.length;
await dmClick('up');
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
  'ours': m._guard(['docker', 'compose', '--project-name', 'a', 'down']),
  'unnamed': m._guard(['docker', 'compose', '-f', 'x', 'down']),
  'trailing': m._guard(['docker', 'compose', 'down', '--project-name']),
  'bare': m._guard(['docker', 'rm', '-f', 'someone-elses-container']),
}))
`], { encoding: 'utf8' });
const g = JSON.parse(guard.trim().split('\n').pop());
ok(!g.git && !g.version && !g.ours,
   'git, docker version and a named compose call are what may run');
ok(g.unnamed && g.trailing && g.bare,
   '...and a compose call naming no project, or naming it nowhere, or any other '
   + 'docker verb, are not');
await dmClick('down');
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
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
mp2, bad2 = m.host_map()
out['parity'] = [mp2, bad2, m.problems('alpha', {'services': {'a': {'volumes': ['./data:/data']}}})]
# The same pair against a daemon on THIS box, which is the shipped default's
# hazard: an identity skips the mount-table check by design, so nothing else
# can catch a sandbox mapping left behind on a socket proxy — and the daemon
# resolves /workspace on the host, where Unraid does not have one.
os.environ['DOCKER_HOST'] = 'tcp://proxy:2375'
out['falseparity'] = m.host_map()
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
# A bind under a path this container has that the mapping is silent about —
# here the projects share itself, with nothing declared at all. The complaint
# used to say "the daemon does not have it", which is a claim this side cannot
# make: nothing here can see the other machine's filesystem, which is the whole
# reason the mapping is a setting.
os.environ['DOCKER_HOST_PATHS'] = ''
out['unmapped'] = m.problems('alpha', {'services': {'a': {'volumes':
    ['/workspace/alpha/data:/data']}}})

# ...and the dev-data share is never judged that way, whether or not this
# container happens to mount it: the VM owns those directories and makes them
# itself, so calling one of them ours reported every correct compose file as
# broken, on the one path the daemon certainly does have.
os.environ['DOCKER_HOST_PATHS'] = '/workspace:/workspace'
out['devdata'] = m.problems('alpha', {'services': {'a': {'volumes':
    ['/devdata/thing/data:/data']}}})
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
ok(hp.devdata.length === 0,
   'a bind under the dev-data share is the VM\'s business, and is not judged here');
ok(hp.unmapped.length === 1 && !/does not have it/.test(hp.unmapped[0])
   && /\/workspace:\/workspace/.test(hp.unmapped[0]),
   'an unmapped path says the mapping is silent, not that the daemon lacks it — '
   + 'and names the pair to add');
ok(hp.falseparity[0]['/workspace'] === '/workspace'
   && /sandbox-VM mapping/.test(hp.falseparity[1][0] || ''),
   '...but says so when that mapping is pointed at a daemon on this box');

// Who makes the dev-data directory. It has to exist before a bind can use it,
// docker's own attempt fails on a root-squashing share (it makes it, fails the
// chown, fails the run — and leaves it behind, so the second press works), and
// for a long time the only candidate was this container. That is the entire
// reason /devdata had to be mounted here as well as over there.
const dd = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
os.environ['BB_MOUNTINFO'] = ${JSON.stringify(mi)}

# Every docker call goes through the REAL guard and is recorded, so what is
# asserted below is what the daemon would actually have been asked to do.
calls = []
def fake(argv, timeout=60, **kw):
    bad = m._guard(argv)
    calls.append({'argv': argv, 'refused': bad})
    if bad:
        return {'code': 126, 'out': bad}
    # A 'test -d' has to be able to say NO, or every check that asks whether
    # something is already there gets yes and the move it guards never runs.
    # The sandbox holds bbdev-alpha and nothing else.
    if 'test' in argv:
        return {'code': 0 if argv[-1] == '/d/bbdev-alpha' else 1, 'out': ''}
    return {'code': 0, 'out': ''}
m._run = fake

out = {}
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
# The VM makes it, and BB_DEV_DATA is the path on THAT machine — the share is
# not mounted on this side at all, which is the point of doing it over there.
m.DEVDATA = '/devdata-not-here'
out['remote'] = [m._dev_data_env('alpha'), calls[:]]
out['ours'] = m.our_paths({})
# The name of it without a promise it is there. _compose asks this way because
# it is on the poll path, and making it there would be a container launch every
# few seconds for as long as the tab is open.
calls.clear()
out['named'] = [m.dev_data_dir('alpha', make=False), calls[:]]

# Not a sandbox VM: nothing is run at all, and a compose that wanted
# BB_DEV_DATA fails loudly instead of writing to a directory docker invented.
calls.clear()
os.environ['DOCKER_HOST'] = 'tcp://proxy:2375'
out['proxy'] = [m._dev_data_env('alpha'), calls[:]]

# A rename reaches over there too, or the instance's data is orphaned under
# the old name with nothing said about it.
calls.clear()
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
# ...and refused outright when the target is already a directory over there:
# 'mv a b' with b existing does not fail, it buries a inside b.
calls.clear()
out['onto'] = [m.rename_dev_data('bbdev-alpha', 'bbdev-alpha'),
               [[a for a in c['argv'] if a.startswith('/d/')] for c in calls]]
calls.clear()
out['renamed'] = [m.rename_dev_data('bbdev-alpha', 'bbdev-beta'),
                  [[a for a in c['argv'] if a.startswith('/d/')] for c in calls]]

# Bind directories on the DAEMON's side. The shares are mounted over there
# and not here, which is the shipped arrangement — and which shares the VM has
# is the VM's business: nothing is declared on this side, so a share added
# over there next month needs no BuilderBot setting touched. Neither share is
# in the fake mount table above, so nothing goes down the local branch.
m.DEVDATA = '/devdata-vm'
cfg = {'services': {'s': {'volumes': [
  {'type': 'bind', 'source': '/auxiliary/plex-library', 'target': '/m'},
  {'type': 'bind', 'source': '/devdata-vm/sonarr/config', 'target': '/c'},
  {'type': 'bind', 'source': '/devdata-vm/sonarr/data', 'target': '/d2'},
  {'type': 'bind', 'source': '/loneroot', 'target': '/x'}]}}}
out['split'] = m.missing_dirs('sonarr', cfg, 'main')
calls.clear()
m._config = lambda *a, **k: cfg
m._load = lambda: {'sonarr': {'main': {}}}
made = m.make_dirs('sonarr')
out['made'] = [sorted(made['made']), made['failed'], made['unreachable'],
               [[a for a in c['argv'] if a.endswith(':/d') or a.startswith('/d/')]
                for c in calls if not c['refused']]]
# A root nobody declared is refused even in exactly the right shape.
out['slash'] = m._guard(m._devdata_argv('mkdir', 'x', root='/'))
out['nested'] = m._guard(m._devdata_argv('mkdir', 'x', root='/a/b'))
out['anyshare'] = m._guard(m._devdata_argv('mkdir', 'x', root='/undeclared'))
out['climb'] = m._guard(m._devdata_argv('mkdir', '../etc', root='/devdata-vm'))
out['deep'] = m._guard(m._devdata_argv('mkdir', 'a/b/c', root='/devdata-vm'))

# What the guard lets through is these commands, rebuilt and compared — not
# the verb. A run with a bind is root on whatever answers.
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
mk = m._devdata_argv('mkdir', 'bbdev-alpha')
out['guard'] = {
  'ours': m._guard(mk),
  'traversal': m._guard(m._devdata_argv('mkdir', '../../etc')),
  'other mount': m._guard([x.replace(m.DEVDATA + ':/d', '/:/d') for x in mk]),
  'other image': m._guard([x if x != 'alpine' else 'evil' for x in mk]),
  'extra flag': m._guard(mk[:2] + ['--privileged'] + mk[2:]),
  'other command': m._guard([x if x != 'mkdir' else 'rm' for x in mk]),
  'free run': m._guard([m.DOCKER, 'run', '--rm', '-v', '/:/host', 'alpine', 'sh']),
}
os.environ['DOCKER_HOST'] = 'tcp://proxy:2375'
out['guard']['ours, on the proxy'] = m._guard(mk)
print(json.dumps(out))
`], { encoding: 'utf8' });
const DDD = JSON.parse(dd.trim().split('\n').pop());
ok(DDD.remote[0].BB_DEV_DATA === '/devdata-not-here/alpha'
   && DDD.remote[1].length === 1 && !DDD.remote[1][0].refused
   && DDD.remote[1][0].argv.slice(-3).join(' ') === 'mkdir -p /d/alpha',
   'the VM makes the data directory itself, on its own disk, mounted nowhere here');
ok(DDD.named[0] === '/devdata-not-here/alpha' && !DDD.named[1].length,
   '...asked for by name it runs nothing, which is what keeps the poll off it');
ok(!DDD.ours.includes('/devdata-not-here'),
   '...and that path is then the daemon\'s, so a bind under it is not judged here');
ok(!Object.keys(DDD.proxy[0]).length && !DDD.proxy[1].length,
   'a daemon that is not the sandbox VM is never asked to run one, and the compose '
   + 'says so rather than mounting a directory docker invented');
ok(DDD.renamed[0][0] === true && !DDD.renamed[0][1]
   && JSON.stringify(DDD.renamed[1]) === JSON.stringify(
      [['/d/bbdev-alpha'], ['/d/bbdev-beta'], ['/d/bbdev-alpha', '/d/bbdev-beta']]),
   'a rename moves the data over there too, rather than orphaning it');
ok(DDD.onto[0][0] === false && /already has a data directory/.test(DDD.onto[0][1])
   && DDD.onto[1].every(paths => paths.length === 1),
   '...and refuses onto a name the sandbox already has: every call it made names '
   + 'one directory, so the two-path mv that would bury one never ran');
ok(!DDD.guard.ours && Object.entries(DDD.guard).filter(([k]) => k !== 'ours')
     .every(([, v]) => !!v),
   'the guard allows those exact commands and nothing else wearing the same verb');
ok(/sandbox VM/.test(DDD.guard['ours, on the proxy']),
   '...and not even those unless the daemon is the sandbox VM');
ok(JSON.stringify(DDD.split[0]) === JSON.stringify(
     ['/auxiliary/plex-library', '/devdata-vm/sonarr/config', '/devdata-vm/sonarr/data'])
   && JSON.stringify(DDD.split[1]) === JSON.stringify(['/loneroot']),
   "every bind under a share of the daemon's is BuilderBot's to make, with "
   + 'nothing declared anywhere — only a bind AT a share root is not, since '
   + 'docker itself creates that one as root');
ok(DDD.made[0].length === 3 && !DDD.made[1].length
   && JSON.stringify(DDD.made[3]) === JSON.stringify([
        ['/auxiliary:/d', '/d/plex-library'],
        ['/devdata-vm:/d', '/d/sonarr/config', '/d/sonarr/data']]),
   '...made by one container per share rather than one per directory');
ok(/not a share root/.test(DDD.slash) && /not a share root/.test(DDD.nested)
   && !DDD.anyshare && DDD.climb && !DDD.deep,
   'the guard takes the mount out of the argv and checks its shape: / and a '
   + 'nested path are refused, any single share is not, a climbing name still is');

// One thing at a time on the daemon, and it now covers every verb that runs a
// compose call. `up`, `down` and `remove` read the flag and never set it, so a
// thirty-minute implicit build inside `up` was invisible to the guard: a
// rebuild started on top of it, two compose calls ran on one project, and the
// row showed neither. Driven at the module, because the race is between two
// requests and a browser cannot hold one open on purpose.
const slot = execFileSync('python3', ['-c', `
import importlib.util, json, tempfile, threading, time
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)

# A compose call that takes its time, so a second request lands during it.
started = threading.Event()
def slow(argv, timeout=60, **kw):
    started.set(); time.sleep(0.6); return {'code': 0, 'out': ''}
m._run = slow
m._risk_gate = lambda *a, **k: ''
m.missing_env = lambda *a, **k: []
m.compose_file = lambda *a, **k: '/tmp/x.yml'
m._load = lambda: {'alpha': {'main': {}}}

out = {}
t = threading.Thread(target=lambda: m.up('alpha', 'main'), daemon=True)
t.start(); started.wait(2)
out['job_while_up'] = dict(m._job)
out['second_up'] = m.up('alpha', 'main')
out['rebuild_during_up'] = m.rebuild('alpha', 'main')
out['down_during_up'] = m.down('alpha', 'main')
t.join(5)
out['after'] = m._job['running']
out['free_now'] = m._claim('alpha', 'main', 'x'); m._release()
print(json.dumps(out))
`], { encoding: 'utf8' });
const SL = JSON.parse(slot.trim().split('\n').pop());
ok(SL.job_while_up.running && SL.job_while_up.step === 'starting'
   && SL.job_while_up.project === 'alpha',
   'an up takes the job slot, so the row can say what is happening in it');
ok([SL.second_up, SL.rebuild_during_up, SL.down_during_up]
     .every(r => /one at a time/.test(r.error || '')),
   '...and every other verb is refused while it holds it, not only a build');
ok(SL.after === false && SL.free_now === true,
   '...and the slot is given back when it ends, however it ends');

// Abort during the stopping step. It reached nothing — the phase held no
// process to signal, and nothing read the flag again until after `up` — so the
// container came up and the job then reported that it had been stopped. Both
// halves are asserted: that `up` never runs, and that what the row says
// matches what happened.
const ab = execFileSync('python3', ['-c', `
import importlib.util, json, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
m.missing_env = lambda *a, **k: []
m._head = lambda *a, **k: 'abc1234'
m._load = lambda: {'alpha': {'main': {}}}

phases = []
def fake(argv, timeout=60, **kw):
    verb = argv[argv.index('-f') + 2] if '-f' in argv else argv[-1]
    phases.append(verb)
    # Abort lands while the down is in flight, which is the window that was
    # not covered: there is no held process for the signal to reach.
    if verb == 'down':
        m.abort_job()
    return {'code': 0, 'out': ''}
m._run = fake

m._claim('alpha', 'main', 'building')
m._worker('alpha', 'main')
print(json.dumps({'phases': phases, 'error': m._job['error'],
                  'running': m._job['running']}))
`], { encoding: 'utf8' });
const AB = JSON.parse(ab.trim().split('\n').pop());
ok(!AB.phases.includes('up'),
   'an abort during the stopping step stops there, rather than starting it anyway');
ok(/stopped/.test(AB.error) && !AB.running,
   '...and the row says so, which it was already saying with the thing running');

// The tail is a display, not a transcript. Compose with no terminal writes a
// new line per progress tick instead of rewriting one, so a single layer of a
// single image arrives as dozens of near-identical lines — enough to push
// whatever went wrong out of a 4000-character tail entirely.
const tail = execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
out = {}
m._job['log'] = ''
feed = ([' 5a96bc599c67 Extracting 2B'] * 11 + [' 5a96bc599c67 Extracting 3B'] * 10
        + [' 5a96bc599c67 Pull complete 0B', ' Network dev_default Creating ',
           ' Network dev_default Creating ', ' Network dev_default Created ',
           ' Container dev-x-1 Starting ',
           "Error response from daemon: chown /x: operation not permitted"])
for line in feed:
    m._log_line(line + chr(10))
out['pull'] = [len(feed), m._job['log'].strip().split(chr(10))]
# A build transcript is prose, not frames, and must survive intact.
m._job['log'] = ''
for line in ['Step 1/4 : FROM node:22', 'Step 2/4 : RUN npm ci', 'Successfully built abc']:
    m._log_line(line + chr(10))
out['build'] = m._job['log'].strip().split(chr(10))
print(json.dumps(out))
`], { encoding: 'utf8' });
const TL = JSON.parse(tail.trim().split('\n').pop());
ok(TL.pull[0] === 27 && TL.pull[1].length === 5,
   'a line that supersedes the one before it replaces it, so a pull is frames and not a transcript');
ok(/operation not permitted/.test(TL.pull[1][TL.pull[1].length - 1]),
   '...leaving the thing that ended it as the last line, which is the point');
ok(TL.pull[1].some(l => /Extracting 3B/.test(l)) && !TL.pull[1].some(l => /Extracting 2B/.test(l)),
   '...and the frame kept is the latest one, not the first');
ok(TL.build.length === 3,
   'a build transcript is not collapsed — three words in common is a frame, prose is not');

// The address. One arrangement — a sandbox VM over ssh — so the operator
// writes the machine and the rest is filled in; and anything that is NOT that
// arrangement is refused by name here rather than half-working further down,
// where a `docker run` as root would land on somebody's real daemon.
const addr = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp(); os.makedirs(d + '/devenv')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
out = {}
for k, v in [('bare', '10.0.0.9'), ('scheme', 'ssh://10.0.0.9'),
             ('user', 'ssh://someone@10.0.0.9'), ('proxy', 'tcp://p:2375'),
             ('unset', '')]:
    os.environ['DOCKER_HOST'] = v
    out[k] = [m.docker_host(), m.sandbox_daemon(), m.available()['why'],
              m._pname('alpha'), m._pname('alpha', 'dev')]
print(json.dumps(out))
`], { encoding: 'utf8' });
const AD = JSON.parse(addr.trim().split('\n').pop());
ok(AD.bare[0] === 'ssh://bb@10.0.0.9' && AD.scheme[0] === 'ssh://bb@10.0.0.9',
   'the machine is all the operator writes: the scheme and the bb account fill in');
ok(AD.user[0] === 'ssh://someone@10.0.0.9' && AD.user[1] === true,
   '...and writing the account out still means what it says');
ok(AD.proxy[1] === false && /sandbox/.test(AD.proxy[2]) && /tcp:/.test(AD.proxy[2]),
   'anything that is not a sandbox VM is off, and the reason names what was set');
ok(AD.unset[1] === false && /not set/.test(AD.unset[2]),
   '...as is nothing at all, which is the shipped state and not a fault');
ok(AD.bare[3] === 'alpha' && AD.bare[4] === 'dev',
   'a container is called exactly what it was named — no prefix in front of it');

// Container names and project names are separate groups. A project existing
// reserves nothing — an earlier version checked that it did, and refused a
// name the operator had every right to use. What is refused is two INSTANCES
// resolving to one compose project, which is one set of containers with two
// rows driving it.
const nm = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp(); os.makedirs(d + '/devenv')
open(d + '/devapps.json', 'w').write('{}')
m.configure(workspace='/tmp', state=d,
            write_json=lambda p, o: open(p, 'w').write(json.dumps(o)))
m.compose_file = lambda *a, **k: '/tmp/x.yml'
out = {}
# 'ep.silon' is a project in this workspace. Naming a container after it from
# a DIFFERENT project is allowed: the two are not the same kind of thing.
out['after_a_project'] = m.create_instance('alpha', 'ep-silon')
out['twice'] = m.create_instance('beta', 'ep-silon')
out['owner'] = json.load(open(d + '/devapps.json'))
# And the project itself is told who has the name, rather than silently
# sharing the containers.
out['project_told'] = m.name_clash('ep.silon', 'main')
print(json.dumps(out))
`], { encoding: 'utf8' });
const NM = JSON.parse(nm.trim().split('\n').pop());
ok(NM.after_a_project.name === 'ep-silon',
   'a container may be named after a project — they are separate name groups');
ok(/already alpha/.test(NM.twice.error || ''),
   '...but not twice, because that is one compose project with two rows on it');
ok(Object.keys(NM.owner)[0] === 'alpha'
   && Object.keys(NM.owner.alpha)[0] === 'ep-silon',
   '...and the store keeps whose it is, which is what the name never decides');
ok(/already alpha/.test(NM.project_told),
   'a project whose own name was taken is told by whom, not quietly merged into it');

// Making a compose file's bind directories. Docker creates a missing bind
// source itself — as root, then chowning it — which on a share that squashes
// root fails and takes the run down, leaving the directory behind so the
// SECOND press works. So they are made first, by whoever owns them.
const mkd = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp(); os.makedirs(d + '/devenv')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
here = tempfile.mkdtemp()
os.makedirs(here + '/already')
# The mount table this container has, which decides which side makes what.
os.environ['BB_MOUNTINFO'] = d + '/mi'
open(d + '/mi', 'w').write('1 0 0:1 / ' + here + ' rw - x x rw\\n')
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
# Faked, like every sibling block: without this the daemon-side half ran the
# REAL docker CLI against whatever DOCKER_HOST the box has — a test that
# reached out and made a directory on the operator's live VM.
calls = []
def fake(argv, timeout=60, **kw):
    bad = m._guard(argv)
    calls.append({'argv': argv, 'refused': bad})
    return {'code': 126 if bad else 0, 'out': bad}
m._run = fake
m._load = lambda: {'p': {'main': {}}}
cfg = {'services': {'a': {'volumes': [
    here + '/new/data:/data', here + '/already:/x',
    '/vm-share/z:/z', '/lone:/x2']}}}
out = {}
out['split'] = m.missing_dirs('p', cfg)
m._config = lambda *a, **k: cfg
out['made'] = m.make_dirs('p')
out['exists'] = os.path.isdir(here + '/new/data')
out['ran'] = [[a for a in c['argv'] if a.endswith(':/d') or a.startswith('/d/')]
              for c in calls if 'mkdir' in c['argv']]
print(json.dumps(out))
`], { encoding: 'utf8' });
const MK = JSON.parse(mkd.trim().split('\n').pop());
ok(MK.split[0].length === 2 && /new\/data$/.test(MK.split[0][0])
   && MK.split[0][1] === '/vm-share/z',
   'a missing bind directory is offered whichever side can see it');
ok(MK.split[1].length === 1 && MK.split[1][0] === '/lone',
   '...except a bind at a share root itself, which docker creates as root');
ok(!MK.split[0].concat(MK.split[1]).some(p => /already/.test(p)),
   '...and one that exists is not offered at all');
ok(MK.exists && MK.made.made.length === 2 && !MK.made.failed.length
   && JSON.stringify(MK.ran) === JSON.stringify([['/vm-share:/d', '/d/z']]),
   'making them is a local mkdir on this side and one container per share on '
   + 'the VM\'s — with nothing declared to make that allowed');


// Changing the prefix renames what every dev container is CALLED — the name is
// the prefix plus what the thing is called and nothing else, and the
// containers, env file and data directory are all keyed by it. So the row says
// the old name is still holding everything, and offers to move it. Never
// automatically, and never while anything is up: renaming a directory out from
// under a running container leaves it writing somewhere nothing will look
// again.
const mig = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp(); os.makedirs(d + '/devenv')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
m.DEVDATA = d + '/devdata'; os.makedirs(m.DEVDATA)
open(d + '/devenv/bbdev-sonarr.env', 'w').write('PORT=1')
os.makedirs(m.DEVDATA + '/bbdev-sonarr/config')
out = {'now': m._pname('sonarr'), 'stale': m.stale_name('sonarr')}
m.containers = lambda: {'error': '', 'containers': [{'project': 'bbdev-sonarr'}]}
out['while_up'] = m.migrate_name('sonarr')
m.containers = lambda: {'error': '', 'containers': []}
out['moved'] = m.migrate_name('sonarr')
out['after'] = [sorted(os.listdir(d + '/devenv')), sorted(os.listdir(m.DEVDATA)),
                sorted(os.listdir(m.DEVDATA + '/sonarr'))]
out['again'] = m.migrate_name('sonarr')
print(json.dumps(out))
`], { encoding: 'utf8' });
const MG = JSON.parse(mig.trim().split('\n').pop());
ok(MG.now === 'sonarr' && MG.stale === 'bbdev-sonarr',
   'a prefix change is noticed: the old name is found by its tail, not by memory');
ok(/take it down first/.test(MG.while_up.error || ''),
   '...and refused while a container still exists under either name');
ok(MG.moved.moved.length === 2 && !MG.moved.failed.length
   && JSON.stringify(MG.after) === JSON.stringify(
        [['sonarr.env'], ['sonarr'], ['config']]),
   '...then moves the env file and the data directory, contents and all');
ok(/nothing to migrate/.test(MG.again.error || ''),
   '...and has nothing left to say the second time');


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
ok(ij.envmoved.length === 1 && ij.envmoved[0] === 'alpha.env',
   '...with its env file moved to the name the instance is read by');
// The project is no longer spelled into the name. A default instance is
// named for its project because nobody typed a name for it; a named one is
// called what it was called, which is the whole of the change — the old
// scheme rendered MediaReducer-Dev's instance of the same name as
// mediareducer-dev-mediareducer-dev.
ok(ij.pnames[0] === 'alpha' && ij.pnames[1] === 'staging',
   'a default instance is named for its project, a named one for itself');
ok(ij.pnames[2] === 'two-words',
   '...slugged, so a name with spaces cannot reach a compose call');
ok(ij.envpaths[0] !== ij.envpaths[1],
   'and they do not share an env file — two instances exist to differ');



// A row knows its own build is running. The manager used to look for the job
// on the status snapshot, under a key nothing has ever set — so `busy` was
// permanently false: a row said "never built" through its own build, and its
// buttons stayed live for a second click the server then refused.
await openManager();
// Waited for rather than sampled. A revision bump nulls dockerList and
// refetches, and the rows stay on screen through it — so openManager can
// return, on a selector that is still the last paint, while the answer this
// asks about is briefly gone. Sampling it there fails on the harness's timing
// rather than on the code: the same shape as bug #13.
await page.waitForFunction(() => dockerList !== null, null, { timeout: 15000 })
  .catch(() => {});
ok(await page.evaluate(() => typeof dockerList?.job !== "undefined"),
   'the manager is told about the running job with the rest of its page');

// The wiring fold: what the container publishes and what it mounts, fetched
// when it is opened and not before — parsing the compose file is the one thing
// the manager's page deliberately does not do for every row at once.
await openManager();
ok(await page.$eval(`${DM} .dmwire .wire`, e => /reading/.test(e.textContent)),
   'the wiring fold says nothing until it is opened');
await page.click(`${DM} .dmwire summary`);
await page.waitForFunction((sel) => /7475/.test(
  document.querySelector(sel + ' .dmwire .wire')?.textContent || ''), DM,
  { timeout: 15000 });
const wire = await page.$eval(`${DM} .dmwire .wire`, e => e.textContent.replace(/\s+/g, ' '));
ok(/7474.*7475/.test(wire), '...then the port, the container\'s side first');
ok(/\/library/.test(wire) && /←/.test(wire),
   '...and a read-only mount with the arrow that says so');
ok(/\/config/.test(wire) && /↔/.test(wire),
   '...beside a writable one, which gets the other arrow');

// ---- one button, and a second container from one project ---------------
// The artifact row's controls moved to the manager; what is left is a button
// that names a container and sends you there. A project can have several, all
// built from the same codebase, which is the whole reason instances exist.
await showRow();
ok(!await page.$('#devRow [data-devact]'),
   'the artifact row carries no docker controls any more');
await page.click('#devSend');
await page.waitForSelector('#dnmodal:not([hidden])');
// No cursor anywhere: a focused field brings the on-screen keyboard up over
// half the dialog the moment it opens, which is the rule the New project
// dialog already followed and these two did not.
ok(await page.evaluate(() => document.activeElement?.tagName) !== 'INPUT'
   && await page.evaluate(() => document.activeElement?.tagName) !== 'TEXTAREA',
   'the send dialog opens with the keyboard down');
// The env comes with it, seeded from the project's own example, so the first
// build has its values rather than stopping at the gate to ask for them.
await page.waitForSelector('#dnEnvField:not([hidden])', { timeout: 10000 });
ok(/PORT=8080/.test(await page.$eval('#dnEnv', e => e.value)),
   '...carrying the env seeded from .env.example');
await page.fill('#dnName', 'Staging Two');
ok(/Will be created as staging-two\b/.test(
     await page.$eval('#dnPreview', e => e.textContent)),
   'the naming modal previews the container it will make, when the slug differs');
await page.click('#dnGo');
await page.waitForSelector('.dmtab .row[data-inst="ep.silon|staging-two"]',
                           { timeout: 20000 });
ok(true, 'sending one lands you in the manager, with it listed');
// ...as a document filling the pane rather than a rounded card adrift in one.
// It wore .card while the notebook beside it did not, which is the thing this
// is here to stop coming back.
ok(await page.$eval('.dmtab', e => !e.classList.contains('card'))
   && await page.$eval('.doc:has(.dmtab)', e => e.classList.contains('flush')),
   '...laid out like the notebook, not as a box floating in the pane');

// With no daemon reachable, every control that would act on one goes quiet
// and carries the reason. Forced through `state` rather than by taking the
// fake daemon away: what is being tested is the gate, and it takes exactly
// one input.
await page.evaluate(() => {
  state.docker = { on: false, why: 'no DOCKER_HOST set — nothing to talk to' };
  dockerRev++; drawPanes();
});
await page.waitForFunction(() => document.getElementById('bDockerNew')?.disabled === true,
                           null, { timeout: 8000 });
ok(await page.$$eval('.dmtab [data-dm="up"],.dmtab [data-dm="down"]',
                     bs => bs.length > 0 && bs.every(b => b.disabled)),
   'with no daemon, the controls that would drive one are disabled');
// data-tip, not title: tipify() runs after the gate on this surface and turns
// one into the other, which is the point — the reason is worn the way every
// other explanation here is.
ok(await page.$eval('#bDockerNew', b => /no DOCKER_HOST/.test(b.dataset.tip || b.title)),
   '...each carrying the reason rather than just refusing');
ok(/no DOCKER_HOST/.test(await page.$eval('.dmtab .empty', e => e.textContent)),
   '...and the tab says it in words, since a tooltip is unreachable on a phone');
ok(await page.$eval('#bDockerRe', b => !b.disabled),
   'Refresh stays live — it is the retry, and disabling it would strand you');
ok(await page.$$eval('.dmtab [data-dm="edit"],.dmtab [data-dm="env"]',
                     bs => bs.every(b => !b.disabled)),
   '...as do Edit and Env: a compose file is a file whatever can run it');
await page.evaluate(() => { state.docker = { on: true, why: '' };
                            dockerRev++; drawPanes(); });
await page.waitForFunction(() => document.getElementById('bDockerNew')?.disabled === false,
                           null, { timeout: 8000 });
ok(true, '...and a daemon coming back needs no un-gating: the next draw is clean');

// ---- which daemon ------------------------------------------------------
// One arrangement now. The mounted socket and the proxy scan are gone, along
// with the precedence rule that existed to say which of three won.
{
  const one = execFileSync('python3', ['-c', `
import importlib.util, json, os
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(workspace='/tmp', state='/tmp', write_json=lambda *a: None)
out = {}
os.environ['DOCKER_HOST'] = 'ssh://bb@vm'
out['vm'] = m.source()
os.environ['DOCKER_HOST'] = ''
out['off'] = [m.source(), m.available()['why']]
print(json.dumps(out))
`], { encoding: 'utf8' });
  const ONE = JSON.parse(one.trim().split('\n').pop());
  ok(ONE.vm.kind === 'the sandbox VM' && ONE.vm.where === 'ssh://bb@vm',
     'the daemon is the sandbox VM DOCKER_HOST names, and nothing else is looked for');
  ok(!ONE.off[0].kind && /DOCKER_HOST is not set/.test(ONE.off[1]),
     '...and with it unset the feature is off, with the reason said');
}

// Which paths a compose file is judged against. It was a hardcoded pair —
// /workspace and /devdata — which is what the mapping held on the day it was
// written and not what it holds now: a share added to BOTH sides was
// translated by to_host and checked by nothing, so a bind under it could name
// a directory the daemon does not have, and the answer to a missing bind
// source is an empty directory silently mounted in its place.
const pathsOut = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ws = tempfile.mkdtemp(); dd = tempfile.mkdtemp(); aux = tempfile.mkdtemp()
m.configure(workspace=ws, state=dd, write_json=lambda *a: None)
m.DEVDATA = dd
out = {}
# A share on both sides is judged; one only the daemon has is named, not judged.
mp = {ws: ws, dd: dd, aux: aux, '/only-over-there': '/only-over-there'}
out['ours'] = sorted(p in m.our_paths(mp) for p in (ws, dd, aux))
out['aux_judged'] = aux in m.our_paths(mp)
out['ghost_judged'] = '/only-over-there' in m.our_paths(mp)
out['strays'] = m.stray_map_entries(mp)
print(json.dumps(out))
`], { encoding: 'utf8' });
const pj = JSON.parse(pathsOut.trim().split('\n').pop());
ok(pj.aux_judged,
   'a share mounted on both sides is judged, without anyone editing the code for it');
ok(!pj.ghost_judged,
   '...while one only the daemon has is not, because this side can check nothing about it');
ok(pj.strays.join(',') === '/only-over-there',
   '...and it is named instead, so a line of config that does nothing does not look like it does');
// Send BUILDS: the manager lists what exists, so registering alone would send
// you to a page that does not mention what you just made.
// Running, not merely built: the env went in before the build, so the gate
// that used to stop this one short had nothing to ask for. That is the whole
// reason the box is on the send dialog rather than one screen later.
await page.waitForFunction(() => /running/.test(
  document.querySelector('.dmtab .row[data-inst="ep.silon|staging-two"] .state')?.textContent || ''),
  { timeout: 40000 });
ok(true, '...and it comes up, because its env went in before the build');
ok(/--env-file/.test(dockerLog()),
   '...with the env saved before that build, not asked for after it');
const both = await page.$$eval('.dmtab .row[data-inst^="ep.silon|"]',
  rs => rs.map(r => r.dataset.inst));
ok(both.includes('ep.silon|main') && both.includes('ep.silon|staging-two'),
   '...beside the one the project already had');
// The failed Up earlier answers 400, which the browser records as a failed
// resource load. Counted rather than filtered out: "no console errors except
// the ones I expected" is only worth asserting if the number is pinned too.
const errs = await page.errors;
const asked = errs.filter(e => /400 \(Bad Request\)/.test(e));
ok(errs.length === asked.length && asked.length === 1,
   'no console errors from the dev row, beyond the one refusal the failed Up asked for');

// ---- a container with no project behind it ------------------------------
// The shape every other Docker front end uses: a name, a compose file and an
// environment. It has no working copy, so its compose lives in /config and its
// relative binds resolve against its own data directory.
await openManager();
await page.click('#bDockerNew');
await page.waitForSelector('#cmodal:not([hidden])');
ok(await page.evaluate(() => document.activeElement?.tagName) !== 'INPUT',
   'the new-container dialog opens with the keyboard down');
// Empty, with the shape offered as a placeholder. Seeded as a VALUE it was
// a working compose for a radarr nobody asked for, one unread click from
// being created under whatever name was typed — a hint cannot be submitted.
ok(await page.$eval('#cYml', e => e.value) === ''
   && await page.$eval('#cEnv', e => e.value) === '',
   '...with both definitions empty, so nothing can be saved by accident');
ok(/services:/.test(await page.$eval('#cYml', e => e.placeholder))
   && /PUID=/.test(await page.$eval('#cEnv', e => e.placeholder)),
   '...and the shape each wants shown on the field, where it costs nothing to ignore');
ok(await page.$eval('#cEnvField', e => e.hidden)
   && !await page.$eval('#cYmlField', e => e.hidden),
   '...showing one of the two definitions at a time');
// The incoming pane slides in from its own tab's side, the way the New project
// dialog's source picker does. Caught while it runs rather than after: the
// pane is visible either way, and the only thing being claimed here is that it
// arrived moving.
const slides = page.waitForFunction(
  () => document.getElementById('cEnvField').getAnimations().length > 0,
  { timeout: 8000 });
await page.click('#cTabEnv');
await slides;
ok(!await page.$eval('#cEnvField', e => e.hidden),
   '...and the segment swaps them, on the same slide as the project dialog');
// An empty compose is refused rather than written — the placeholder is not
// a value, and nothing here invents one.
await page.click('#cTabYml');
await page.fill('#cName', 'radarr');
await page.click('#cGo');
await page.waitForSelector('#cErrWrap:not([hidden])', { timeout: 15000 });
await page.waitForSelector('#cGo:not([disabled])', { timeout: 15000 });
ok(/compose file is needed/.test(await page.$eval('#cErr', e => e.textContent)),
   'Create with nothing typed is refused, rather than saving the hint');
ok(!existsSync(`${DIR}/state/containers/radarr`),
   '...and writes nothing for the name it refused');

writeFileSync(`${DIR}/dockerstate/config.fail`, '1');
await page.fill('#cYml', 'services:\n  app:\n    image: lscr.io/x:latest\n');
await page.click('#cGo');
await page.waitForFunction(() => /will not read that/.test(
  document.getElementById('cErr')?.textContent || ''), { timeout: 15000 });
await page.waitForSelector('#cGo:not([disabled])', { timeout: 15000 });
ok(true, 'a compose file that does not parse is refused with what compose said');
ok(!existsSync(`${DIR}/state/containers/radarr/docker-compose.yml`),
   '...and nothing is left behind for a name that was refused');
rmSync(`${DIR}/dockerstate/config.fail`, { force: true });
await page.click('#cGo');
await page.waitForSelector('.dmtab .row[data-inst="radarr|main"]', { timeout: 20000 });
ok(existsSync(`${DIR}/state/containers/radarr/docker-compose.yml`),
   'one that parses is written to /config, where no project scan can see it');
ok(/compose written here/.test(await page.$eval(
     '.dmtab .row[data-inst="radarr|main"]', r => r.textContent)),
   '...and the manager says which kind it is');
// Editing one: what it is changes far more often than it is created, and
// without this the only way to move a port was to remove it and retype it.
await page.click('.dmtab .row[data-inst="radarr|main"] [data-dm="edit"]');
await page.waitForSelector('#cmodal:not([hidden])');
await page.waitForFunction(() => /services:/.test(document.getElementById('cYml').value),
                           { timeout: 10000 });
ok(await page.$eval('#cName', e => e.disabled && e.value === 'radarr'),
   'editing opens on the container, and its name is not a field any more');
await page.fill('#cYml', 'services:\n  app:\n    image: alpine:latest\n');
await page.click('#cGo');
await page.waitForFunction(() => document.getElementById('cmodal').hidden,
                           { timeout: 15000 });
ok(/alpine:latest/.test(readFileSync(`${DIR}/state/containers/radarr/docker-compose.yml`, 'utf8')),
   '...and Save writes the new compose file');
// One that will not parse leaves the old file where it was.
writeFileSync(`${DIR}/dockerstate/config.fail`, '1');
await page.click('.dmtab .row[data-inst="radarr|main"] [data-dm="edit"]');
await page.waitForSelector('#cmodal:not([hidden])');
await page.waitForFunction(() => /alpine/.test(document.getElementById('cYml').value),
                           { timeout: 10000 });
await page.fill('#cYml', 'services:\n  broken');
await page.click('#cGo');
await page.waitForSelector('#cErrWrap:not([hidden])', { timeout: 15000 });
ok(/alpine:latest/.test(readFileSync(`${DIR}/state/containers/radarr/docker-compose.yml`, 'utf8')),
   'a save that will not parse puts the old compose file back');
rmSync(`${DIR}/dockerstate/config.fail`, { force: true });
await page.click('#cCancel');

await page.click('#bDockerNew');
await page.waitForSelector('#cmodal:not([hidden])');
await page.fill('#cName', 'alpha');
await page.click('#cGo');
await page.waitForSelector('#cErrWrap:not([hidden])', { timeout: 15000 });
ok(/the project alpha/.test(await page.$eval('#cErr', e => e.textContent)),
   'a name a project already has is refused');
await page.fill('#cName', '');
await page.click('#cCancel');

// ...and one it has only after slugging. The guard compared the typing, and
// everything downstream compares the slug: `ep-silon` is not the project
// `ep.silon` by string and is exactly it by the time _pname has run — same
// compose project name, same env file, same dev-data directory, with nothing
// anywhere saying the two had met.
await page.click('#bDockerNew');
await page.waitForSelector('#cmodal:not([hidden])');
await page.fill('#cName', 'ep-silon');
await page.click('#cGo');
await page.waitForSelector('#cErrWrap:not([hidden])', { timeout: 15000 });
ok(/ep\.silon/.test(await page.$eval('#cErr', e => e.textContent)),
   '...as is one that only collides once it is slugged, naming the project it hit');
ok(!existsSync(`${DIR}/state/containers/ep-silon`),
   '...and nothing is written for it');
await page.click('#cCancel');
await openManager();
await page.click('.dmtab .row[data-inst="radarr|main"] [data-dm="remove"]');
await page.waitForFunction(() =>
  !document.querySelector('.dmtab .row[data-inst="radarr|main"]'), { timeout: 20000 });
ok(!existsSync(`${DIR}/state/containers/radarr`),
   'removing one written here takes its compose file with it');


// The same name twice is refused rather than silently reusing the first.
await showRow();
await page.click('#devSend');
await page.waitForSelector('#dnmodal:not([hidden])');
await page.fill('#dnName', 'staging-two');
await page.click('#dnGo');
await page.waitForSelector('#dnErrWrap:not([hidden])', { timeout: 10000 });
ok(/already has an instance/.test(await page.$eval('#dnErr', e => e.textContent)),
   'a name the project already uses is refused, in place');
await page.click('#dnCancel');

// Removing takes it down and drops it from the list — and the project's
// Artifacts tab is untouched, which is where it comes back from.
await openManager();
await page.click('.dmtab .row[data-inst="ep.silon|staging-two"] [data-dm="remove"]');
await page.waitForFunction(() =>
  !document.querySelector('.dmtab .row[data-inst="ep.silon|staging-two"]'),
  { timeout: 20000 });
ok(true, 'Remove takes a container out of the manager');
ok(/compose --project-name staging-two .*down/.test(dockerLog()),
   '...taking it down first, rather than orphaning its containers');
await showRow();
ok(await page.$('#devSend'),
   '...and the project can still send another: the artifact row persists');



// The fixture goes back the way artifacts.mjs leaves alpha.
rmSync(`${D}/docker-compose.yml`, { force: true });
rmSync(`${D}/.env.example`, { force: true });
rmSync(`${D}/newfile.txt`, { force: true });
rmSync(`${D}/again.txt`, { force: true });
rmSync(`${D}/after-interrupt.txt`, { force: true });
rmSync(`${D}/.git`, { recursive: true, force: true });
execFileSync('git', ['-C', D, 'init', '-q', '.'], { env });
await done(browser);
