// The dev instance: a project's compose app, built and run through the host's
// daemon, controlled from the Docker tab in the file rows' own language.
//
// Everything here drives the stub docker the harness provides; the argv it
// records IS the assertion, because the module's whole safety story is that
// the buttons run table-lookup compose commands and nothing else.
import { launch, newPage, ok, done, ready, sleep, patience, holdPoll, freePoll, refreshUntil, URL, DIR, nbShown, nbTab } from './lib.mjs';
import { writeFileSync, readFileSync, rmSync, existsSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// ep.silon gets the compose file, since delta is the harness's EXCLUDED
// fixture and never shows a notebook button. The dot in the name is a bonus: it
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
// The server under test polls git on every project every fifteen seconds,
// and `git status` takes index.lock when it refreshes the index, so a
// commit here can land exactly on one and die with "Unable to create
// index.lock". It is the fixture racing the thing it is testing, not a
// finding about either, so it is waited out rather than reported. Anything
// that is not the lock is thrown at once.
function git(...args){
  const until = Date.now() + 10000;
  for (;;){
    try { return execFileSync('git', ['-C', D, ...args], { env }); }
    catch (e){
      const said = String(e.stderr || '') + String(e.message || '');
      if (!/index\.lock/.test(said) || Date.now() > until) throw e;
      execFileSync('sleep', ['0.2']);
    }
  }
}
git('add', '-A');
git('commit', '-qm', 'compose');

// Every compose action is a job now, and a job goes on writing (its final
// log flush, its result row) for a moment after the row already shows the
// outcome. An assertion about what a job LEFT BEHIND waits for the queue to
// empty first, rather than sampling the row mid-settle (bug #13's shape).
const idle = async (ms = 20000) => {
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  const end = Date.now() + ms;
  while (Date.now() < end){
    const r = await (await fetch(URL.replace(/\/$/, '') + '/api/v1/jobs?active=1', { headers: H })).json();
    if (!(r.jobs || []).length) return;
    await sleep(200);
  }
};

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

// The controls live on the Docker manager now, and the artifact row only
// sends you there, so everything that presses one drives it from that tab.
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
// there, and anything that CLICKS on the row needs it visible again; reading
// what the row rendered does not, which is why most assertions here wait on
// attachment instead.
async function showRow(){
  await page.click('#projects .row:has(.name:text-is("ep.silon")) [data-m]');
  await page.waitForSelector('#devRow', { timeout: 20000 });
}
async function dmRefresh(){
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  await openManager();
  // The rows come back at once from the last answer, marked stale while the
  // new one is on its way (B125); a refresh is done when the mark is gone.
  await page.waitForFunction(() => document.querySelector('.dmtab') && !document.querySelector('.dmtab.dmstale'),
                             null, { timeout: 30000 });
}
// The manager lists what has been SENT to it (a project with a compose file
// no longer gets a phantom row there), so the fixture's instance has to exist
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
// could as easily be the Down button. The pill says what the row IS: docker,
// the way the file rows say apk or xpi. It never says what it is doing.
const pill = () => page.$eval(`${DM} .dmpill`, e => e.textContent.replace(/[()]/g, '').trim());
const pillIs = async (want) => { await openManager(); return page.waitForFunction(
  ([w, sel]) => document.querySelector(sel + ' .dmpill')?.textContent.replace(/[()]/g, '').trim() === w,
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
// One fact per line, never a run-on joined by semicolons: these are separate
// facts about separate services, and reading them is the point of showing them.
// The wiring lines carry .li too and are not what these two are counting, so
// they are told apart by their class rather than by where they sit.
const devLines = (cls) => page.$$eval(`#devRow .grow > .dim.li.${cls}`,
  els => els.map(e => e.textContent.trim()));
ok(await page.$eval(`${DM} [data-dm="rebuild"]`,
     e => e.textContent.trim()) === 'Build',
   'the button says Build before a first image exists; nothing auto-builds');
// Waited for, not read once: the button goes live when the manager has the
// node's answer, and on a server that started a moment ago (every file gets
// its own now, B124) that answer can be a poll away.
await openManager();
const live = await page.waitForFunction(sel => document.querySelector(sel)?.disabled === false,
  `${DM} [data-dm="rebuild"]`, { timeout: 20000 }).then(() => true).catch(() => false);
ok(live, '...and it is live for that first build');
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
   'a filled env wakes Up: compose builds what is missing, so it would work');
ok(/builds the image first, as compose does/.test(
     // data-tip, not title: the manager's controls carry the page's own
     // tooltip now, which is the same words moved off an attribute that waits
     // a second before showing them.
     await page.$eval(`${DM} [data-dm="up"]`, b => b.dataset.tip)),
   '...and Up says that is what it will do');

// First build: build → down → up, and the argv trail proves the shape.
// (newPage auto-accepts dialogs and records them, with no handler of our own.)
await dmClick('rebuild');
// Watched on the MANAGER's row, which is where a container's state lives now.
// The Artifacts row used to carry it and no longer does: building and running
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
// BuildKit, which is compose's own default and what carries the layer cache.
// The classic builder was forced here for a year because buildx boots a
// helper container and ATTACHES to it, and a socket proxy refused that
// attach; there is no proxy now, and no controller-side docker either.
// Measured before it was changed (R12, 21 Sep): on a node's own daemon, as
// the agent's account, buildx builds and the second build of an unchanged
// Dockerfile reports CACHED.
ok(!/BUILDKIT=0/.test(log),
   '...and builds with compose\'s own builder, so the layers cache');
// The stamp: a compose whose build args want the commit and the time gets
// them from the environment, the way BB_DEV_DATA arrives. Full sha, since
// the header shortens it itself; the time in the form CI stamps.
{
  const head = execFileSync('git', ['-C', `${DIR}/ws/ep.silon`, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim();
  ok(new RegExp(`BB_BUILD_REV=${head} BB_BUILD_AT=\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\dZ`).test(log),
     `...with the commit it builds from and the time in the environment, for a compose that stamps its image (${
       (log.match(/BB_BUILD_REV=[^\n]*/) || ['none'])[0].slice(0, 70)})`);
  // ...and the version in the IDENTITY form, the one tools/build-image-here.sh
  // gives a production image, so one commit built either way answers with one
  // string. It used to be the docker-tag-safe `file` form, whose whole job is
  // that it cannot carry `+`, so the same build read `…+sha` on production and
  // `…-sha` on the dev instance and the two read as different builds (B158).
}
// ...and the VERSION it stamps is the identity form, the one
// tools/build-image-here.sh gives a production image, so a commit built either
// way answers with one string. It used to take the docker-tag-safe `file`
// form, whose whole job is that it cannot carry `+`, so the same commit read
// `…-dev.1633+8dfc0b2` on production and `…-dev.1633-8dfc0b2` on the dev
// instance and the two read as different builds (B158). Asked of the function
// against a repo that HAS a version, since the fixture project has none and
// the assertion would pass on an empty string.
{
  const vrepo = `${DIR}/ws/verstamp`;
  rmSync(vrepo, { recursive: true, force: true });
  mkdirSync(vrepo, { recursive: true });
  writeFileSync(`${vrepo}/VERSION`, '1.2.3\n');
  const env = { ...process.env, GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@t',
                GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@t' };
  execFileSync('git', ['-C', vrepo, 'init', '-q', '.'], { env });
  execFileSync('git', ['-C', vrepo, 'add', '-A'], { env });
  execFileSync('git', ['-C', vrepo, 'commit', '-qm', 'v'], { env });
  const got = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, sys, os
sys.path.insert(0, ${JSON.stringify(new globalThis.URL('..', import.meta.url).pathname)})
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
import pathlib, version
m.WORKSPACE = pathlib.Path(${JSON.stringify(`${DIR}/ws`)})
version.configure(workspace=${JSON.stringify(`${DIR}/ws`)}, state=${JSON.stringify(`${DIR}/state`)},
                  write_json=lambda *a, **k: None)
print(json.dumps(m._build_env('verstamp', '')))
`], { encoding: 'utf8', env }));
  ok(/^1\.2\.3-dev\.\d+\+[0-9a-f]+$/.test(got.BB_BUILD_VERSION || ''),
     `the dev build stamps the identity form, with the + a docker tag cannot carry (${
       got.BB_BUILD_VERSION || 'unstamped'})`);
  rmSync(vrepo, { recursive: true, force: true });
}
r = await row();
ok(!r.down && r.up, 'running: Down is live, Up is dead');
// Rebuild does NOT go to sleep when the build matches the code, which it used
// to: a button that refuses is not information, and the operator met it by
// pinning an instance to a branch, pressing Apply, and having nothing to
// press. What "the code has moved" is worth is a sentence (the row's state
// line and the button's own title both carry it), and a rebuild that changed
// nothing is a cached build and a restart, behind a confirm that says so.
ok(!r.rebuild && /the code has moved since/.test(r.text) === false,
   'Rebuild stays live once the build matches the code, and says which it is');

// ---- the route (phase 8) --------------------------------------------------
// The instance is up on the sandbox and publishes 7475: its route is lan on
// that port at the node's address, drawn on the row with the picker beside
// it. funnel is offered only when the node has tailscale (the sandbox is an
// ssh node and has none), and public is named as unbuilt.
{
  await openManager();
  await page.waitForFunction(sel => /http:\/\/stub:7475\//.test(
    document.querySelector(sel + ' .dmroute')?.textContent || ''), DM, { timeout: 20000 });
  const opts = await page.$$eval(`${DM} [data-route="mode"] option`, os => os.map(o => [o.value, o.disabled]));
  ok(opts.some(([v, d]) => v === 'lan' && !d) && opts.some(([v, d]) => v === 'funnel' && d)
     && opts.some(([v, d]) => v === 'public' && d),
     'the route picker offers lan, greys funnel without tailscale, and names public as unbuilt');
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const rapi = async body => (await fetch(URL.replace(/\/$/, '') + '/api/devapp', { method: 'POST', headers: H, body: JSON.stringify(body) })).json();
  const pub = await rapi({ project: 'ep.silon', instance: 'main', action: 'route', mode: 'public' });
  ok(/not built/.test(pub.error || ''), 'public is refused by name');
  const fun = await rapi({ project: 'ep.silon', instance: 'main', action: 'route', mode: 'funnel', port: 7475 });
  // The reason is tailscale, not the sandbox stamp (roadmap #23): a funnel
  // is tailscale's own CLI doing the certificate, the DNS and the firewall,
  // so it is offered to any node that HAS tailscale, a container node or
  // somebody's own machine included. What still needs the stamp is storage
  // and network, which edit fstab and netplan. The harness's node has no
  // tailscale, so that is what it says.
  ok(/no tailscale/.test(fun.error || ''),
     `a funnel says what it actually lacks: tailscale, not a provisioner (${fun.error})`);
  const lan = await rapi({ project: 'ep.silon', instance: 'main', action: 'route', mode: 'lan', port: 7475 });
  ok(lan.ok && lan.state.route.mode === 'lan' && lan.state.route.url === 'http://stub:7475/' && lan.state.route.ready,
     'lan on a published port is a record with the URL that follows from the node');
}

// ---- a row is listed under the node its buttons act on --------------------
// An instance with no node of its own belongs to its PROJECT's node, which
// is what every action on the row resolves, and the LISTING resolved it one
// step short, straight to the default node. So an unbound instance of a
// project bound to one machine was listed under another, offering buttons
// that would act somewhere other than where the row said, and a node nobody
// had sent anything to showed two other projects' containers.
{
  const list = (node) => page.evaluate(async (n) => {
    const r = await fetch('/api/docker' + (n ? '?node=' + encodeURIComponent(n) : ''));
    const j = await r.json();
    return (j.instances || []).map(i => `${i.project}|${i.instance}`);
  }, node);
  const sandboxId = await page.evaluate(
    () => (nodesList || []).find(n => n.name === 'sandbox')?.id || '');
  ok(!!sandboxId, `the harness's node is enrolled (${sandboxId})`);
  await page.evaluate(async (n) => {
    await fetch('/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', node: n }) });
  }, sandboxId);
  const onIts = await list(sandboxId);
  ok(onIts.some(x => x === 'ep.silon|main'),
     `an unbound instance is listed under its project's node (${onIts.join(', ')})`);
  const elsewhere = await list('n_notanodehere');
  ok(!elsewhere.some(x => x === 'ep.silon|main'),
     `...and nowhere else (${elsewhere.join(', ') || 'no rows'})`);
  await page.evaluate(async () => {
    await fetch('/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', node: '' }) });
  });
}

// ---- moving the project leaves a built instance where it is running -------
// The containers on the old node keep running when a project's node changes,
// which is right: an instance is removed from the Docker manager and never by
// a setting changed somewhere else. What used to go with them was the ROW.
// An instance with no node of its own resolves to the project's, so the node
// change pointed the manager at a daemon holding none of it, and the one
// control that could stop or remove what was still running had gone. So a
// BUILT instance is pinned to the machine it is on at the moment the setting
// moves, and only a built one: a record that is settings and nothing else has
// nothing on any daemon to strand.
{
  const store = `${DIR}/state/devapps.json`;
  const nodeOf = (proj, inst) =>
    (JSON.parse(readFileSync(store, 'utf8'))[proj] || {})[inst]?.node || '';
  const setNode = (proj, n) => page.evaluate(async ([p2, n2]) => {
    const r = await fetch('/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: p2, node: n2 }) });
    return r.json();
  }, [proj, n]);
  const sandboxId = await page.evaluate(
    () => (nodesList || []).find(n => n.name === 'sandbox')?.id || '');

  // From a known baseline: blocks above this one move the node too, and a
  // node change is exactly what pins, so the fixture arrives here already
  // pinned by them.
  {
    const d = JSON.parse(readFileSync(store, 'utf8'));
    delete d['ep.silon'].main.node;
    writeFileSync(store, JSON.stringify(d));
  }
  await setNode('ep.silon', sandboxId);
  ok(nodeOf('ep.silon', 'main') === sandboxId,
     `the first node a project is given pins what is already built on the daemon it was built on (${
       nodeOf('ep.silon', 'main') || 'unpinned'})`);
  {
    const d = JSON.parse(readFileSync(store, 'utf8'));
    delete d['ep.silon'].main.node;
    writeFileSync(store, JSON.stringify(d));
  }
  ok(nodeOf('ep.silon', 'main') === '',
     'a built instance with no node of its own follows its project');
  const said = await setNode('ep.silon', 'n_somewhereelse');
  ok(nodeOf('ep.silon', 'main') === sandboxId,
     `moving the project pins its built instance to the node it is on (${
       nodeOf('ep.silon', 'main') || 'unpinned'})`);
  ok((said.pinned || []).includes('main'),
     `...and the answer names what it pinned, rather than doing it silently (${
       JSON.stringify(said.pinned || [])})`);
  // The point of the pin: the manager still lists it where it runs, so Stop
  // and Remove are still there for something that is still up.
  const rows = await page.evaluate(async (n) => {
    const j = await (await fetch('/api/docker?node=' + encodeURIComponent(n))).json();
    return (j.instances || []).map(i => `${i.project}|${i.instance}`);
  }, sandboxId);
  ok(rows.includes('ep.silon|main'),
     `...so the Docker manager still offers it on that node (${rows.join(', ') || 'no rows'})`);
  // An instance that was never built is not pinned: it has nothing anywhere.
  {
    const d = JSON.parse(readFileSync(store, 'utf8'));
    d['ep.silon'] = { ...d['ep.silon'], fresh: { ref: 'main' } };
    delete d['ep.silon'].main.node;
    writeFileSync(store, JSON.stringify(d));
  }
  await setNode('ep.silon', sandboxId);
  await setNode('ep.silon', 'n_somewhereelse');
  ok(nodeOf('ep.silon', 'fresh') === '',
     `an instance that was never built is left to move with the project (${
       nodeOf('ep.silon', 'fresh') || 'unpinned'})`);
  // Put the fixture back, and in this order: clearing the node is itself a
  // change, so it pins all over again. The store is tidied after the last one.
  await setNode('ep.silon', '');
  {
    const d = JSON.parse(readFileSync(store, 'utf8'));
    delete d['ep.silon'].fresh;
    delete d['ep.silon'].main.node;
    writeFileSync(store, JSON.stringify(d));
  }
}

// A build belongs to the daemon it ran on. Repointing the node at another
// VM leaves the image and the containers behind on a machine the dashboard can
// no longer reach, and the row went on saying "built from
// <rev>" and offering Rebuild for something never built here. Driven through
// the state file rather than by enrolling a second node:
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

// The code moves, and Rebuild wakes.
writeFileSync(`${D}/newfile.txt`, 'x');
git('add', '-A');
git('commit', '-qm', 'more');
await page.evaluate(() => refresh());
await dmRefresh();
await page.waitForFunction((SEL) => {
  const b = document.querySelector(SEL + ' [data-dm="rebuild"]');
  return b && !b.disabled;
}, DM, { timeout: 20000 });
ok(true, 'a commit unghosts Rebuild: the code has moved since the build');
// ---- a long build is watchable, and stoppable ---------------------------
// Both were missing. The log was assigned after the command returned, so a
// pull was minutes of nothing and then everything at once (a download that
// looked like a hang), and there was no way to interrupt one at all.
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
// or up, so it leaves the instance exactly as it found it, which is the
// property being asserted anyway. A tidying rebuild here was worse than
// nothing: it recorded a rev, unset "the code has moved", and the gate test
// below then found Rebuild ghosted and never ran.

// The env gate: the example gains a key, and the rebuild stops after down
// with the old env preserved in comments.
writeFileSync(`${D}/.env.example`, 'PORT=8080\nAPI_KEY=\n');
git('add', '-A');
git('commit', '-qm', 'needs a key');
await dmClick('rebuild');
await page.waitForFunction(() => {
  const e = document.querySelector('#devRow');
  return e && /fill in the env/.test(e.textContent);
}, { timeout: 30000 });
// The pill as well as the text: the text lands with the record the job
// wrote, and on an agent node the pill comes from a listing read a moment
// later, so the two can arrive a fetch apart (B143).
await page.waitForFunction(sel => document.querySelector(sel + ' .dmpill')?.textContent.replace(/[()]/g, '').trim() === 'down',
                           DM, { timeout: 20000 }).catch(() => {});
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

// A container that EXITED still exists: it holds its name and the project's
// network, and `down` is the only thing that clears it. Asking compose only
// about RUNNING containers left a crashed instance with a greyed-out Down and
// no way out except a shell, which is the one thing these buttons are for.
writeFileSync(`${DIR}/dockerstate/ep-silon.exited`, '1');
await page.evaluate(() => refresh());
await pillIs('stopped');
r = await row();
ok(!r.down, 'a crashed instance offers Down: its containers are still there');
ok(!r.up, '...and Up, which recreates them rather than colliding with them');
await dmClick('down');
await pillIs('down');
ok(!existsSync(`${DIR}/dockerstate/ep-silon.exited`),
   '...and Down is what clears them');

// An Up that FAILS. The row used to lose everything about it the moment the
// job released: the reply carried the reason to the one browser that pressed
// the button, and the row, which reads the job, was left saying "stopped"
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
await idle();
await openManager();
await page.waitForSelector(`${DM} .dmlog`, { timeout: 20000 });
// The row's one-line summary is the REASON, not the label. A compose failure
// arrives as "up failed:\n<docker's output>" kept from the end, so reading its
// first line put "up failed:" on the row and dropped what docker actually
// said, the same shape as a node reporting ".NET said: Process terminated."
// and losing the sentence that named the missing library.
ok(await page.evaluate(() => [
     jobWhy('up failed:\ncreating network: pool overlaps'),
     jobWhy('build failed; the tail of its output is below'),
     jobWhy(''),
   ].join(' | ')) === 'creating network: pool overlaps | build failed; the tail of its output is below | ',
   'a failed job is summarised by its reason, not by the label above it');
ok(await page.$eval(`${DM} .dmlog`, e => e.dataset.tail === '1'),
   '...and that tail is pinned to its end, which is where the error is');
// Rebuild has to wake for the retry. A build records itself before the up
// that follows it, so a failed up left the row insisting the build was
// current: true, and not what somebody looking at a red row wants offered.
ok(!(await row()).rebuild,
   '...and Rebuild is live again, because the run failed even though the build did not');
rmSync(`${DIR}/dockerstate/up.fail`);
await dmClick('down');
await pillIs('down');

// A build in flight when BuilderBot restarts is lost: compose build is a
// subprocess of the dashboard and dies with it. Everything already recovered
// correctly (the last SUCCESSFUL build is still what built_rev says, and
// Rebuild is live because the code moved), but the operator was told nothing
// and saw a button they thought they had pressed. Simulated by leaving the
// on-disk marker behind, which is exactly what a killed process leaves.
await idle();
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
// build matches HEAD, interrupted marker or not. The marker says what
// happened; it does not invent work to do.
writeFileSync(`${D}/after-interrupt.txt`, 'x');
git('add', '-A');
git('commit', '-qm', 'moves on');
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
git('add', '-A');
git('commit', '-qm', 'again');
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
// The dev row reloads on job_rev (the in-memory counter plus devapps.json's
// mtime), and a stub config file moves neither, so a plain refresh() would
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
// on its own filesystem, where /workspace/<project> does not exist, and
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
// The DAEMON's host, not this page's. They are different machines (the whole
// point of the sandbox VM), and a container publishing 7475 publishes it over
// there. This used to be location.hostname, which on a real box is the Unraid
// server: a link to a port where either nothing answers or something else does.
// The sandbox node dialed in from `stub`, so the answer is `stub`.
ok(await page.$eval('#devRow a.btn', a => a.getAttribute('href'))
     === 'http://stub:7475/',
   'a running instance opens on the machine its daemon runs, not on the one serving this page');
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
ok(picks.length === 2 && picks[0] === 'http://stub:8080/'
   && picks[1] === 'http://stub:8081/',
   '...listing every published port, on that same machine, for the operator to answer');
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

// A docker call that is not a namespaced compose call does not run at all:
// the invariant the whole feature's blast radius rests on, asserted at the
// one place every call passes through.
const guard = execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.DOCKER = 'docker'
# The two things a devdata run depends on, answered here rather than by a
# daemon: this node reports its appdata store three components deep, which is
# what B192 was about, and the guard's first question about a run is whether
# the daemon is a sandbox VM, which has no meaning in a test.
m.appdata_root = lambda *a, **k: '/var/lib/builderbot/appdata'
m.verified_sandbox = lambda: True
print(json.dumps({
  'git': m._guard(['git', '-C', '/x', 'status']),
  'version': m._guard(['docker', 'version']),
  'ours': m._guard(['docker', 'compose', '--project-name', 'a', 'down']),
  'unnamed': m._guard(['docker', 'compose', '-f', 'x', 'down']),
  'trailing': m._guard(['docker', 'compose', 'down', '--project-name']),
  'bare': m._guard(['docker', 'rm', '-f', 'someone-elses-container']),
  'own': m._guard(m._devdata_argv('mkdir', 'builderbot-dev')),
  'share': m._guard(m._devdata_argv('mkdir', 'thing', root='/auxiliary')),
  'elsewhere': m._guard(m._devdata_argv('mkdir', 'x', root='/var/lib/somewhere-else')),
  'slash': m._guard(m._devdata_argv('mkdir', 'x', root='/')),
  'climb': m._guard(m._devdata_argv('mkdir', 'x', root='/var/lib/../etc')),
  'invented': m._guard([m.DOCKER, 'run', '--rm', '-v', '/var/lib/builderbot/appdata:/d',
                        'alpine', 'sh', '-c', 'whoami']),
}))
`], { encoding: 'utf8' });
const g = JSON.parse(guard.trim().split('\n').pop());
ok(!g.git && !g.version && !g.ours,
   'git, docker version and a named compose call are what may run');
ok(g.unnamed && g.trailing && g.bare,
   '...and a compose call naming no project, or naming it nowhere, or any other '
   + 'docker verb, are not');
// B192: the module built a run its own guard refused, on every poll, because
// the mount rule wanted one component and this node reports its appdata store
// three deep. A guard that refuses its own module is a bug in the module,
// which is what the log said, so the invariant is asserted as itself.
ok(!g.own && !g.share,
   `what this module itself builds passes its own guard, at the node's appdata store and at a share root (${
     g.own || 'ok'} / ${g.share || 'ok'})`);
ok(g.elsewhere && g.slash && g.climb && g.invented,
   '...while another deep path, the root of the filesystem, one climbing out with .. '
   + 'and a run this module did not build are all still refused');
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
# The mapping and the daemon address come from the NODE now, not from the two
# environment variables that used to carry them (roadmap #18 retired the ssh
# kind and they left the five places with it). So the two seams are stubbed at
# the module: node_paths is the record, and _node_ctx.addr is the node this
# call is addressed at, which is exactly what on_node() sets.
PAIRS = {}
m.node_paths = lambda nid: PAIRS
m.node_for = lambda cap=None: 'n1'
def setpaths(text):
    global PAIRS
    PAIRS = dict(p.split(':', 1) for p in text.split(',') if ':' in p) if text else {}
def sethost(a):
    m._node_ctx.addr = a
out = {}
setpaths('/workspace:/mnt/user/development,/devdata:/mnt/cache/appdata/builderbot-dev')
mp, bad = m.host_map()
out['good'] = [mp, bad, m.to_host('/workspace/alpha/data', mp),
               m.to_host('/mnt/user/plex', mp)]
# The half of the mapping that moved: /workspace is mounted from /development,
# so a host path not ending in it describes a different share.
setpaths('/workspace:/mnt/user/somethingelse')
out['moved'] = m.host_map()
# The sandbox-VM arrangement: the daemon is elsewhere and the shares are
# mounted over there at the paths used over here, so the mapping is an
# identity. It is not a translation and there is nothing in THIS container's
# mount table to check it against, so it must not be run through the check
# that catches a half-edited one.
setpaths('/workspace:/workspace')
sethost('ssh://bb@vm')
mp2, bad2 = m.host_map()
out['parity'] = [mp2, bad2, m.problems('alpha', {'services': {'a': {'volumes': ['./data:/data']}}})]
# The same pair against a daemon on THIS box, which is the shipped default's
# hazard: an identity skips the mount-table check by design, so nothing else
# can catch a sandbox mapping left behind on a socket proxy, and the daemon
# resolves /workspace on the host, where Unraid does not have one.
sethost('tcp://proxy:2375')
out['falseparity'] = m.host_map()
# ...and the same pair against an agent node that really does have the path,
# which is every node the storage plane mounts the share on (B193). Its own
# census is the evidence: a warning on every start, on a mapping that is
# correct by construction, is how starts stop being read.
class _Q:
    def __init__(self, mounts): self.mounts = mounts
    def node(self, nid): return {'reported': {'mounts': self.mounts}}
m._default_node = lambda: 'n1'
m.queue = _Q([{'path': '/workspace', 'mounted': True}])
out['agentparity'] = m.host_map()
m.queue = _Q([{'path': '/somewhere-else', 'mounted': True}])
out['nomount'] = m.host_map()
m.queue = None
sethost('ssh://bb@vm')
# A bind under a path this container has that the mapping is silent about:
# here the projects share itself, with nothing declared at all. The complaint
# used to say "the daemon does not have it", which is a claim this side cannot
# make: nothing here can see the other machine's filesystem, which is the whole
# reason the mapping is a setting.
setpaths('')
out['unmapped'] = m.problems('alpha', {'services': {'a': {'volumes':
    ['/workspace/alpha/data:/data']}}})

# ...and the dev-data share is never judged that way, whether or not this
# container happens to mount it: the VM owns those directories and makes them
# itself, so calling one of them ours reported every correct compose file as
# broken, on the one path the daemon certainly does have.
setpaths('/workspace:/workspace')
out['devdata'] = m.problems('alpha', {'services': {'a': {'volumes':
    ['/devdata/thing/data:/data']}}})
setpaths('')
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
   'an unmapped path says the mapping is silent, not that the daemon lacks it, '
   + 'and names the pair to add');
ok(hp.falseparity[0]['/workspace'] === '/workspace'
   && /census reports no mount/.test(hp.falseparity[1][0] || ''),
   '...but says so when that mapping is pointed at a daemon on this box');
ok(!hp.agentparity[1].length && hp.agentparity[0]['/workspace'] === '/workspace'
   && /census reports no mount/.test(hp.nomount[1][0] || ''),
   `...and takes the identity from the node's own census rather than from its address, so a node that mounts the share at that path is not warned about and one that does not still is (${
     JSON.stringify(hp.agentparity[1])} / ${(hp.nomount[1][0] || '').slice(0, 40)})`);

// Who makes the dev-data directory. It has to exist before a bind can use it,
// docker's own attempt fails on a root-squashing share (it makes it, fails the
// chown, fails the run, and leaves it behind, so the second press works), and
// for a long time the only candidate was this container. That is the entire
// reason /devdata had to be mounted here as well as over there.
const dd = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile, time
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
# Which daemon this is addressed at. DOCKER_HOST is not read any more
# (roadmap #18); the node record carries it. Both seams are stubbed: the
# per-instance entry points re-enter on_node() themselves, which resolves the
# address through node_addr and would otherwise wipe what was set here.
HOST = ['ssh://bb@vm']          # the sandbox, as every call below assumes
m.node_addr = lambda nid: HOST[0]
m.node_for = lambda cap=None: 'n1'
def sethost(a):
    HOST[0] = a
    m._node_ctx.addr = a
sethost(HOST[0])
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
        # What the sandbox holds: the old project's directories and nothing
        # else, so a move onto an existing name can still be refused and a
        # move of a per-instance directory has a source to find.
        # The literal names the calls above move, plus what a project called
        # alpha actually resolves to (_pname gives the project's slug for the
        # default instance, and the instance's own name for any other).
        there = {'/d/bbdev-alpha', '/d/alpha', '/d/staging'}
        return {'code': 0 if argv[-1] in there else 1, 'out': ''}
    return {'code': 0, 'out': ''}
m._run = fake

# The guard asks whether the daemon is a VERIFIED sandbox (an ssh address and
# a daemon carrying the provisioner's label), and asking costs a docker info,
# which the fake above cannot answer. Primed rather than stubbed out: the memo
# is the real path, so what is tested below is the real check reading a real
# answer, and blanking it is how the proxy case says no.
def verified(on, uid='STUBDAEMON1'):
    val = {'on': True, 'why': '', 'id': uid} if on else {'on': False, 'why': 'no'}
    m._avail.update(when=time.time(), val=val)
    # The per-address memo too: every call below runs inside on_node(), which
    # resolves an address and so reads that one rather than the default.
    m._avail_hosts[HOST[0]] = {'when': time.time(), 'val': val}
verified(True)

out = {}
sethost('ssh://bb@vm')
# The VM makes it, and BB_DEV_DATA is the path on THAT machine: the share is
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
sethost('tcp://proxy:2375')
verified(False)
out['proxy'] = [m._dev_data_env('alpha'), calls[:]]
verified(True)

# A rename reaches over there too, or the instance's data is orphaned under
# the old name with nothing said about it.
calls.clear()
sethost('ssh://bb@vm')
# ...and refused outright when the target is already a directory over there:
# 'mv a b' with b existing does not fail, it buries a inside b.
calls.clear()
out['onto'] = [m.rename_dev_data('bbdev-alpha', 'bbdev-alpha'),
               [[a for a in c['argv'] if a.startswith('/d/')] for c in calls]]
calls.clear()
out['renamed'] = [m.rename_dev_data('bbdev-alpha', 'bbdev-beta'),
                  [[a for a in c['argv'] if a.startswith('/d/')] for c in calls]]

# Renaming a PROJECT, which is asked per project rather than per directory:
# only the default instance's directory is named for the project, so that one
# moves and a named instance's does not, since its name never carried the project.
# Asked as was == now rather than known, so a change to _pname is picked up
# here rather than orphaning what it renames.
calls.clear()
m._load = lambda: {'beta': {'main': {}, 'staging': {}}}
out['project'] = [m.rename_project_data('alpha', 'beta'),
                  [[a for a in c['argv'] if a.startswith('/d/')]
                   for c in calls if 'mv' in c['argv']]]

# Bind directories on the DAEMON's side. The shares are mounted over there
# and not here, which is the shipped arrangement, and which shares the VM has
# is the VM's business: nothing is declared on this side, so a share added
# over there next month needs no BuilderBot setting touched. Neither share is
# in the fake mount table above, so nothing goes down the local branch.
# Names no machine has. missing_dirs skips a bind whose source EXISTS, on the
# real filesystem, so a fixture share called /auxiliary was silently dropped
# from the answer on any box that happens to have one, which every Unraid
# node does (B83). The mount table below is a fixture; these have to be too.
m.DEVDATA = '/bbfix-devdata'
cfg = {'services': {'s': {'volumes': [
  {'type': 'bind', 'source': '/bbfix-aux/plex-library', 'target': '/m'},
  {'type': 'bind', 'source': '/bbfix-devdata/sonarr/config', 'target': '/c'},
  {'type': 'bind', 'source': '/bbfix-devdata/sonarr/data', 'target': '/d2'},
  {'type': 'bind', 'source': '/bbfix-lone', 'target': '/x'}]}}}
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
out['climb'] = m._guard(m._devdata_argv('mkdir', '../etc', root='/bbfix-devdata'))
out['deep'] = m._guard(m._devdata_argv('mkdir', 'a/b/c', root='/bbfix-devdata'))

# What the guard lets through is these commands, rebuilt and compared, not
# the verb. A run with a bind is root on whatever answers.
sethost('ssh://bb@vm')
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
sethost('tcp://proxy:2375')
verified(False)
out['guard']['ours, on the proxy'] = m._guard(mk)
# ...and an ssh address whose daemon does not carry the provisioner's label is
# refused the same way. The address was the whole check once; a machine that
# merely answers Docker on ssh is not the box built to be wrecked.
sethost('ssh://bb@vm')
verified(False)
out['guard']['unstamped sandbox'] = m._guard(mk)
verified(True)
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
ok(JSON.stringify(DDD.project[1]) === JSON.stringify([['/d/alpha', '/d/beta']]),
   'renaming a project moves the data of every instance named after it, which '
   + 'is the default one, and only it');
ok(DDD.project[0][0].length === 1 && !DDD.project[0][1].length,
   '...and a named instance is left alone rather than reported as a failure: '
   + 'its directory never carried the project\'s name');
ok(!DDD.guard.ours && Object.entries(DDD.guard).filter(([k]) => k !== 'ours')
     .every(([, v]) => !!v),
   'the guard allows those exact commands and nothing else wearing the same verb');
ok(/sandbox VM/.test(DDD.guard['ours, on the proxy']),
   '...and not even those unless the daemon is the sandbox VM');
ok(JSON.stringify(DDD.split[0]) === JSON.stringify(
     ['/bbfix-aux/plex-library', '/bbfix-devdata/sonarr/config', '/bbfix-devdata/sonarr/data'])
   && JSON.stringify(DDD.split[1]) === JSON.stringify(['/bbfix-lone']),
   "every bind under a share of the daemon's is BuilderBot's to make, with "
   + 'nothing declared anywhere; only a bind AT a share root is not, since '
   + 'docker itself creates that one as root');
ok(DDD.made[0].length === 3 && !DDD.made[1].length
   && JSON.stringify(DDD.made[3]) === JSON.stringify([
        ['/bbfix-aux:/d', '/d/plex-library'],
        ['/bbfix-devdata:/d', '/d/sonarr/config', '/d/sonarr/data']]),
   '...made by one container per share rather than one per directory');
ok(/appdata store/.test(DDD.slash) && /appdata store/.test(DDD.nested)
   && !DDD.anyshare && DDD.climb && !DDD.deep,
   'the guard takes the mount out of the argv and checks its shape: / is refused, '
   + 'so is a nested path that is not this node\'s appdata store (B192), any single '
   + 'share is not, a climbing name still is');

// One thing at a time on an instance, and it covers every verb that runs a
// compose call. A compose action is a job on the queue now (phase 4): `up`,
// `down`, `rebuild` and `remove` all submit one, and a second on the same
// instance is refused while the first is queued or running, where before
// `up` never set the flag, so a thirty-minute implicit build inside it was
// invisible to the guard. A different instance queues behind it rather than
// being refused: the one-at-a-time is per instance, the queue serialises the
// node. Driven at the module with a stub queue, because the race is between
// two requests and a browser cannot hold one open on purpose.
const slot = execFileSync('python3', ['-c', `
import importlib.util, json, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()

class Queue:
    """Rows are the queue: what job_add wrote is what jobs_for answers."""
    rows = []
    JOB_ACTIVE = ('queued', 'assigned', 'running')
    kind = 'ssh'          # what _submit asks about, to decide whose plan it is
    def node(self, nid):
        return {'id': nid, 'name': nid, 'kind': self.kind} if nid else None
    def job_add(self, principal, placement, type, spec, project=''):
        jid = f'j_{len(self.rows) + 1}'
        self.rows.insert(0, {'id': jid, 'type': type, 'spec': spec, 'project': project,
                             'state': 'queued', 'node': placement.get('node', ''),
                             'placement': placement, 'principal': principal,
                             'step': '', 'error': '', 'cancel': False})
        return {'job': jid}
    def jobs_for(self, project=None, type=None, active=False, n=50, **kw):
        return [r for r in self.rows if (not project or r['project'] == project)
                and (not type or r['type'] == type)
                and (not active or r['state'] in ('queued', 'assigned', 'running'))][:n]
    def jobs_rev(self): return len(self.rows)
    def job_tail(self, jid, n=4000): return ''
q = Queue()
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None, queue=q)
m._risk_gate = lambda *a, **k: ''
m.missing_env = lambda *a, **k: []
m.compose_file = lambda *a, **k: '/tmp/x.yml'
m._load = lambda: {'alpha': {'main': {}, 'staging': {}}}
m._instance_node = lambda *a: 'n_sandbox'

out = {}
out['first_up'] = m.up('alpha', 'main')
out['second_up'] = m.up('alpha', 'main')
out['rebuild_during_up'] = m.rebuild('alpha', 'main')
out['down_during_up'] = m.down('alpha', 'main')
out['other_instance'] = m.up('alpha', 'staging')
out['queued'] = [(r['id'], r['spec']['action'], r['spec']['instance'], r['node'], r['principal']) for r in q.rows]
out['view'] = m.job_view('alpha', 'main')
q.rows[-1]['state'] = 'succeeded'
out['free_now'] = m.up('alpha', 'main')
print(json.dumps(out))
`], { encoding: 'utf8' });
const SL = JSON.parse(slot.trim().split('\n').pop());
ok(SL.first_up.ok && SL.first_up.job === 'j_1' && SL.queued.length === 2
   && SL.queued[1].join() === 'j_1,up,main,n_sandbox,operator',
   'an up is a compose job on the queue, placed on the node the instance is bound to');
ok([SL.second_up, SL.rebuild_during_up, SL.down_during_up]
     .every(r => /one at a time/.test(r.error || '')),
   '...and every other verb on that instance is refused while it is queued or running, not only a build');
ok(SL.other_instance.ok && SL.queued[0].join() === 'j_2,up,staging,n_sandbox,operator',
   '...while another instance of the same project queues behind it: one at a time is per instance');
ok(SL.view && SL.view.running && SL.view.step === 'queued' && SL.view.action === 'up'
   && SL.view.node === 'n_sandbox',
   'the row reads its job from the queue: running, on the step "queued", with the node');
ok(SL.free_now.ok && SL.free_now.job === 'j_3',
   '...and the instance is free again when its job has ended, however it ended');

// Abort during the stopping step. It reached nothing: the phase held no
// process to signal, and nothing read the flag again until after `up`, so the
// container came up and the job then reported that it had been stopped. Both
// halves are asserted: that `up` never runs, and that what the row says
// matches what happened. Driven through _job_rebuild with a run whose cancel
// flag flips mid-down, which is the shape the controller's runner hands it.
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

class Run:
    canceled = False
    steps = []
    def line(self, t): pass
    def step(self, s): self.steps.append(s)
    def hold(self, p): pass
run = Run()
phases = []
def fake(argv, timeout=60, **kw):
    verb = argv[argv.index('-f') + 2] if '-f' in argv else argv[-1]
    phases.append(verb)
    # Abort lands while the down is in flight, which is the window that was
    # not covered: there is no held process for the signal to reach.
    if verb == 'down':
        run.canceled = True
    return {'code': 0, 'out': ''}
m._run = fake

r = m._job_rebuild('alpha', 'main', run)
print(json.dumps({'phases': phases, 'steps': run.steps, 'result': r}))
`], { encoding: 'utf8' });
const AB = JSON.parse(ab.trim().split('\n').pop());
ok(!AB.phases.includes('up') && AB.steps.join() === 'building,stopping',
   'an abort during the stopping step stops there, rather than starting it anyway');
ok(AB.result.state === 'canceled' && /stopped/.test(AB.result.error),
   '...and the result says so, which it was already saying with the thing running');

// The tail is a display, not a transcript. Compose with no terminal writes a
// new line per progress tick instead of rewriting one, so a single layer of a
// single image arrives as dozens of near-identical lines, enough to push
// whatever went wrong out of a 4000-character tail entirely. The fold lives
// in the runner now (jobs.fold), where every job's log goes through it.
const tail = execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('j', ${
  JSON.stringify(new globalThis.URL('../jobs.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
out = {}
buf = []
feed = ([' 5a96bc599c67 Extracting 2B'] * 11 + [' 5a96bc599c67 Extracting 3B'] * 10
        + [' 5a96bc599c67 Pull complete 0B', ' Network dev_default Creating ',
           ' Network dev_default Creating ', ' Network dev_default Created ',
           ' Container dev-x-1 Starting ',
           "Error response from daemon: chown /x: operation not permitted"])
for line in feed:
    m.fold(buf, line + chr(10))
out['pull'] = [len(feed), [l.strip() for l in buf]]
# A build transcript is prose, not frames, and must survive intact.
buf = []
for line in ['Step 1/4 : FROM node:22', 'Step 2/4 : RUN npm ci', 'Successfully built abc']:
    m.fold(buf, line + chr(10))
out['build'] = [l.strip() for l in buf]
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
   'a build transcript is not collapsed: three words in common is a frame, prose is not');

// The address. One arrangement only (a sandbox VM over ssh), so the operator
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
# No daemon is dialled: this is about how an address is composed, and
# available() would otherwise shell out to 'docker version' against each one
# and wait its ten seconds for a host that is not there.
m._run = lambda *a, **k: {'code': 1, 'out': 'no daemon', 'err': ''}
out = {}
for k, v in [('bare', '10.0.0.9'), ('scheme', 'ssh://10.0.0.9'),
             ('user', 'ssh://someone@10.0.0.9'), ('proxy', 'tcp://p:2375'),
             ('unset', '')]:
    # What the node's record says its address is; on_node() puts it here.
    m._node_ctx.addr = v
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
ok(AD.unset[1] === false && /enroll the sandbox VM/.test(AD.unset[2]),
   '...as is no node at all, which is the shipped state and not a fault');
ok(AD.bare[3] === 'alpha' && AD.bare[4] === 'dev',
   'a container is called exactly what it was named, with no prefix in front of it');

// Container names and project names are separate groups. A project existing
// reserves nothing; an earlier version checked that it did, and refused a
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
   'a container may be named after a project: they are separate name groups');
ok(/already alpha/.test(NM.twice.error || ''),
   '...but not twice, because that is one compose project with two rows on it');
ok(Object.keys(NM.owner)[0] === 'alpha'
   && Object.keys(NM.owner.alpha)[0] === 'ep-silon',
   '...and the store keeps whose it is, which is what the name never decides');
ok(/already alpha/.test(NM.project_told),
   'a project whose own name was taken is told by whom, not quietly merged into it');

// Making a compose file's bind directories. Docker creates a missing bind
// source itself (as root, then chowning it), which on a share that squashes
// root fails and takes the run down, leaving the directory behind so the
// SECOND press works. So they are made first, by whoever owns them.
const mkd = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile, time
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

d = tempfile.mkdtemp(); os.makedirs(d + '/devenv')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
# DOCKER_HOST is not read any more (roadmap #18): the address comes from the
# node the call is addressed at, which on_node() puts on _node_ctx.
HOST = ['']
m.node_addr = lambda nid: HOST[0]
m.node_for = lambda cap=None: 'n1'
def sethost(a):
    HOST[0] = a
    m._node_ctx.addr = a

here = tempfile.mkdtemp()
os.makedirs(here + '/already')
# The mount table this container has, which decides which side makes what.
os.environ['BB_MOUNTINFO'] = d + '/mi'
open(d + '/mi', 'w').write('1 0 0:1 / ' + here + ' rw - x x rw\\n')
sethost('ssh://bb@vm')
# Faked, like every sibling block: without this the daemon-side half ran the
# REAL docker CLI against whatever DOCKER_HOST the box has, a test that
# reached out and made a directory on the operator's live VM.
calls = []
def fake(argv, timeout=60, **kw):
    bad = m._guard(argv)
    calls.append({'argv': argv, 'refused': bad})
    return {'code': 126 if bad else 0, 'out': bad}
m._run = fake
# The guard wants a VERIFIED sandbox, and verifying costs a docker info the
# fake above cannot answer. Primed, like the sibling block: the memo is the
# real path this check reads.
m._avail.update(when=time.time(), val={'on': True, 'why': '', 'id': 'STUBDAEMON1'})
# ...and the per-address memo, which is the one a call inside on_node() reads.
m._avail_hosts[HOST[0]] = {'when': time.time(),
                           'val': {'on': True, 'why': '', 'id': 'STUBDAEMON1'}}
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
   + 'the VM\'s, with nothing declared to make that allowed');


// ...and it happens as part of starting, not as a button somebody remembers.
// A control you must press before another control is not a step, it is a
// trap: Up failed, and the reason was a second button sitting unpressed.
const pre = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile, time
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

d = tempfile.mkdtemp(); os.makedirs(d + '/devenv')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
# DOCKER_HOST is not read any more (roadmap #18): the address comes from the
# node the call is addressed at, which on_node() puts on _node_ctx.
HOST = ['']
m.node_addr = lambda nid: HOST[0]
m.node_for = lambda cap=None: 'n1'
def sethost(a):
    HOST[0] = a
    m._node_ctx.addr = a

here = tempfile.mkdtemp()
os.environ['BB_MOUNTINFO'] = d + '/mi'
open(d + '/mi', 'w').write('1 0 0:1 / ' + here + ' rw - x x rw' + chr(10))
sethost('ssh://bb@vm')
cfg = {'services': {'a': {'image': 'x', 'volumes': [
    here + '/wanted/config:/config', '/vm-share/media:/media']}}}
m._config = lambda *a, **k: cfg
m._load = lambda: {'p': {'main': {}}}
m.compose_file = lambda *a, **k: 'docker-compose.yml'
m.missing_env = lambda *a, **k: []
m.name_clash = lambda *a, **k: ''
m._risk_gate = lambda *a, **k: ''
seen = []
def fake(argv, timeout=60, **kw):
    bad = m._guard(argv)
    seen.append({'argv': argv, 'refused': bad})
    return {'code': 126 if bad else 0, 'out': bad}
m._run = fake
# Primed like the sibling blocks: the guard asks whether the daemon is a
# verified sandbox, and the fake cannot answer a docker info. Both memos: a
# call inside on_node() reads the per-address one.
m._avail.update(when=time.time(), val={'on': True, 'why': '', 'id': 'STUBDAEMON1'})
m._avail_hosts[HOST[0]] = {'when': time.time(),
                           'val': {'on': True, 'why': '', 'id': 'STUBDAEMON1'}}
# Up is a job now; this drives the job body the runner would, with a run
# that records nothing, because the order of the calls is the whole test.
class Run:
    canceled = False
    def line(self, t): pass
    def step(self, s): pass
    def hold(self, p): pass
m._job_up('p', 'main', Run())
out = {
  # Ordered: every mkdir has to be finished before the compose that needs it.
  'order': [('up' if 'up' in c['argv'] else 'mkdir') for c in seen
            if 'up' in c['argv'] or 'mkdir' in c['argv']],
  'localmade': os.path.isdir(here + '/wanted/config'),
  'remote': [[a for a in c['argv'] if a.endswith(':/d') or a.startswith('/d/')]
             for c in seen if 'mkdir' in c['argv']],
  'refused': [c['refused'] for c in seen if c['refused']],
}
print(json.dumps(out))
`], { encoding: 'utf8' });
const PRE = JSON.parse(pre.trim().split('\n').pop());
// Two mkdirs: the compose's own bind, and the per-instance dev-data
// directory that BB_DEV_DATA points at. Asserted as "every mkdir before the
// up" rather than as a fixed list, so adding another cannot quietly reorder
// into starting first.
ok(PRE.order[PRE.order.length - 1] === 'up'
   && PRE.order.slice(0, -1).every(x => x === 'mkdir') && PRE.order.length > 1,
   'Up makes the bind directories first and starts second, with nothing to press in between');
ok(PRE.localmade && PRE.remote.some(r =>
     JSON.stringify(r) === JSON.stringify(['/vm-share:/d', '/d/media'])),
   '...on whichever side each one lives, in the same step');
ok(!PRE.refused.length, '...and every call it makes passes the guard');



// An instance is (project, name). Driven at the module: the store's shape
// and the names derived from it, where a stub docker cannot show them.
const inst = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
os.makedirs(os.path.join(d, 'devenv'))
open(os.path.join(d, 'devapps.json'), 'w').write(json.dumps(
    {'alpha': {'main': {'rev': 'abc1234', 'daemon': 'tcp://x', 'risks_ack': 'deadbeef'}}}))
open(os.path.join(d, 'devenv', 'alpha.env'), 'w').write('PORT=1')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: open(p, 'w').write(json.dumps(o)))
out = {}
out['loaded'] = m._load()
out['instances'] = m.instances('alpha')
out['pnames'] = [m._pname('alpha'), m._pname('alpha', 'staging'), m._pname('My Proj', 'Two Words')]
out['envpaths'] = [os.path.basename(str(m.env_path('alpha'))),
                   os.path.basename(str(m.env_path('alpha', 'staging')))]
print(json.dumps(out))
`], { encoding: 'utf8' });
const ij = JSON.parse(inst.trim().split('\n').pop());
ok(JSON.stringify(ij.loaded) === JSON.stringify(
     { alpha: { main: { rev: 'abc1234', daemon: 'tcp://x', risks_ack: 'deadbeef' } } }),
   'the store reads back as {project: {instance: record}}');
ok(JSON.stringify(ij.instances) === JSON.stringify(['main']),
   '...and main is the instance the project has');
// The project is no longer spelled into the name. A default instance is
// named for its project because nobody typed a name for it; a named one is
// called what it was called, which is the whole of the change. The old
// scheme rendered MediaReducer-Dev's instance of the same name as
// mediareducer-dev-mediareducer-dev.
ok(ij.pnames[0] === 'alpha' && ij.pnames[1] === 'staging',
   'a default instance is named for its project, a named one for itself');
ok(ij.pnames[2] === 'two-words',
   '...slugged, so a name with spaces cannot reach a compose call');
ok(ij.envpaths[0] !== ij.envpaths[1],
   'and they do not share an env file: two instances exist to differ');



// A row knows its own build is running. The manager used to look for the job
// on the status snapshot, under a key nothing has ever set, so `busy` was
// permanently false: a row said "never built" through its own build, and its
// buttons stayed live for a second click the server then refused.
await openManager();
// Waited for rather than sampled. A revision bump nulls dockerList and
// refetches, and the rows stay on screen through it, so openManager can
// return, on a selector that is still the last paint, while the answer this
// asks about is briefly gone. Sampling it there fails on the harness's timing
// rather than on the code: the same shape as bug #13.
await page.waitForFunction(() => dockerList !== null, null, { timeout: 15000 })
  .catch(() => {});
ok(await page.evaluate(() => typeof dockerList?.job !== "undefined"),
   'the manager is told about the running job with the rest of its page');

// The wiring fold: what the container publishes and what it mounts, fetched
// when it is opened and not before: parsing the compose file is the one thing
// the manager's page deliberately does not do for every row at once.
await openManager();
ok(await page.$eval(`${DM} .sect .wire`, e => /reading/.test(e.textContent)),
   'the wiring fold says nothing until it is opened');
await page.click(`${DM} .sect > summary`);
// 20s like its neighbours, not 15. The fold fetches, and this is the one
// assertion in this file that has timed out in a full run while passing 3/3
// alone, three times now, always with a CI job or another suite sharing the
// box. See bug #13: the code is not what is slow.
await page.waitForFunction((sel) => /7475/.test(
  document.querySelector(sel + ' .sect .wire')?.textContent || ''), DM,
  { timeout: 20000 });
const wire = await page.$eval(`${DM} .sect .wire`, e => e.textContent.replace(/\s+/g, ' '));
ok(/7474.*7475/.test(wire), '...then the port, the container\'s side first');
ok(/\/library/.test(wire) && /←/.test(wire),
   '...and a read-only mount with the arrow that says so');
ok(/\/config/.test(wire) && /↔/.test(wire),
   '...beside a writable one, which gets the other arrow');

// A published port is a link, and it points at the machine the DAEMON runs on.
// It used to be built from location.hostname (the machine serving this page,
// which is the Unraid box and not the sandbox VM), so every port label and
// every Open link named a host where either nothing answers or something else
// does. The sandbox node dialed in from `stub`, so the answer is `stub`.
ok(await page.$eval(`${DM} .sect .wport a`, a => a.getAttribute('href'))
     === 'http://stub:7475/',
   'a published port is a link, to the machine its daemon runs on');

// Where the row's state sits, asserted by geometry rather than by a
// screenshot. It used to be a third column beside the name; it is the action
// bar's status line now, which is the shared rule: what a thing is doing
// gets a line of its own, and the verbs go under it. Measured because the
// point is the pixels: a status that shared a line with four buttons was the
// layout this framework exists to stop.
const laid = await page.evaluate(() => {
  const bar = document.querySelector('.dmtab .row.stack2 .actbar');
  const st = bar?.querySelector('.state');
  const btn = bar?.querySelector('button');
  if (!bar || !st || !btn) return { err: 'no bar' };
  const r = e => e.getBoundingClientRect();
  return { grid: getComputedStyle(
             document.querySelector('.dmtab .row.stack2 .grow')).display,
           own: Math.round(r(st).width) >= Math.round(r(bar).width) - 2,
           above: r(st).bottom <= r(btn).top + 1 };
});
ok(!laid.err && laid.own && laid.above,
   `...and the row's state is the bar's own line, above the verbs (${
     JSON.stringify(laid)})`);
ok(laid.grid === 'grid',
   '...with the name and the ports still a grid beside each other');

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
//
// ...with the poll held off for the block: a refresh REPLACES state from the
// server, which says the daemon IS reachable, so a tick landing between the
// plant and any assertion below redraws the tab from the truth and every one
// of them fails. That is B99's family, and it is why this file went red one
// run in three with nothing changed.
await holdPoll(page);
// Planted the way the server sends it, `node` included: the poll says which
// daemon it is about and the page gates only that one. A stub without the id
// would be testing a payload the server does not send.
// PLANTED AND READ IN ONE EVALUATE. Every assertion below is about the same
// painted moment, and asking for them one at a time gave the page eight
// chances to repaint between the plant and the last of them, which is how
// this block went red on a loaded box with nothing changed, at a different
// assertion each time (B99's family). holdPoll stops the fifteen-second
// refresh; it does not stop a revision landing, and there is no need to make
// it: drawPanes() is synchronous, so one call reads one frame.
const dead = await page.evaluate(() => {
  state.docker = { on: false, node: dockerNode,
                   why: 'no node with a daemon: nothing to talk to' };
  dockerRev++; drawPanes();
  const q = s2 => [...document.querySelectorAll(s2)];
  const mk = document.getElementById('bDockerNew');
  return {
    newOff: mk?.disabled === true,
    tip: mk?.dataset.tip || mk?.title || '',
    acts: q('.dmtab [data-dm="up"],.dmtab [data-dm="down"]').map(b => b.disabled),
    empty: document.querySelector('.dmtab .empty')?.textContent || '',
    refreshLive: document.getElementById('bDockerRe')?.disabled === false,
    files: q('.dmtab [data-dm="edit"],.dmtab [data-dm="env"]').map(b => b.disabled),
    removes: q('.dmtab [data-dm="remove"]').map(b => b.disabled),
    off: q('.dmtab .row[data-inst]').map(r => r.classList.contains('off')),
    pills: q('.dmtab .row[data-inst] .dmpill').map(e => e.textContent),
  };
});
ok(dead.newOff && dead.acts.length > 0 && dead.acts.every(Boolean),
   'with no daemon, the controls that would drive one are disabled');
// data-tip, not title: tipify() runs after the gate on this surface and turns
// one into the other, which is the point: the reason is worn the way every
// other explanation here is.
ok(/no node with a daemon/.test(dead.tip),
   '...each carrying the reason rather than just refusing');
ok(/no node with a daemon/.test(dead.empty),
   '...and the tab says it in words, since a tooltip is unreachable on a phone');
ok(dead.refreshLive,
   'Refresh stays live: it is the retry, and disabling it would strand you');
ok(dead.files.every(x => !x),
   '...as do Edit and Env: a compose file is a file whatever can run it');
// ...and so does Remove, which is the correction: it is a record on this side
// with a `down` in front of it as a courtesy. Gated with the daemon buttons,
// a row on a machine that had gone away could be removed by nobody, and the
// row is the only control over the thing it names.
ok(dead.removes.length > 0 && dead.removes.every(x => !x),
   '...and so does Remove: the record is this side\'s, and a stranded row must go');
// The rows stay, and stop claiming anything. The tab used to render one error
// line and no rows at all, throwing away everything it could still honestly
// say, which is most of it: what an instance is, and what it was built from,
// live on this side. Only "running" is the daemon's to know, and an
// unreachable daemon is not evidence that anything stopped.
ok(dead.off.length > 0,
   'the rows are still listed with no daemon: the tab shows what is on record');
ok(dead.off.every(Boolean),
   '...greyed, every one of them, so an inert row looks inert before you press');
ok(dead.pills.length > 0 && dead.pills.every(t => /state unknown/.test(t)),
   '...saying the state is unknown rather than reporting one nobody asked for');
ok(await page.$$eval('.dmtab .row[data-inst] .dmpill,.dmtab .row[data-inst] .actbar .state',
                     es => es.every(e => !e.classList.contains('ok'))),
   '...and nothing shows as running: green is a claim about a daemon that is not answering');
// ...and ANOTHER node's silence is not this node's business. This is B109's
// own shape and it came back after the fix: the guard compared the poll's node
// id against the picked one, nothing on the server set that id, and the
// comparison fell back to matching itself. Two nodes and one of them down is
// the ordinary case on a box with a sandbox and a second machine, and it made
// every row on the healthy one say "state unknown" with its buttons off.
await page.evaluate(() => {
  state.docker = { on: false, node: 'n_somebodyelse',
                   why: 'docker does not answer: Connection closed by 10.9.9.9 port 22' };
  dockerRev++; drawPanes();
});
await page.waitForFunction(() => document.getElementById('bDockerNew')?.disabled === false,
                           null, { timeout: 8000 });
ok(await page.$$eval('.dmtab .row[data-inst]',
                     rs => rs.length > 0 && rs.every(r => !r.classList.contains('off'))),
   'a different node being down leaves this node\'s rows alone');
ok(!/state unknown/.test(await page.$eval('.dmtab', e => e.textContent)),
   '...and they still say what is running, rather than state unknown');
// ...and a verdict that names no node gates nothing. This is the shape that
// actually shipped: the field was absent, so `node || dockerNode` matched
// itself and one node's silence greyed them all. Failing open here is safe:
// a row whose own daemon is down is greyed by the tab's own overview.
await page.evaluate(() => {
  state.docker = { on: false, why: 'docker does not answer: no route to host' };
  dockerRev++; drawPanes();
});
await page.waitForFunction(() => document.getElementById('bDockerNew')?.disabled === false,
                           null, { timeout: 8000 });
ok(await page.$$eval('.dmtab .row[data-inst]',
                     rs => rs.length > 0 && rs.every(r => !r.classList.contains('off'))),
   '...and a verdict naming no daemon at all gates nothing either');
// The id the page compares against is one the server actually sends. Without
// this the guard above is a comparison with undefined, which is how it got
// shipped looking correct.
{
  const st = await page.evaluate(async () =>
    (await (await fetch('/api/status')).json()).docker || {});
  ok(typeof st.node === 'string' && st.node.length > 0,
     `...and the poll says which daemon its verdict is about (node ${st.node || '(none)'})`);
}
await freePoll(page);
await page.evaluate(() => { state.docker = { on: true, why: '' };
                            dockerRev++; drawPanes(); });
await page.waitForFunction(() => document.getElementById('bDockerNew')?.disabled === false,
                           null, { timeout: 8000 });
ok(true, '...and a daemon coming back needs no un-gating: the next draw is clean');

// The same again, but for real. TWO different failures now, because they are
// two different questions (B111): whether this node can be ACTED on, which on
// an agent node is whether its agent is dialing in and what it says it
// carries, and whether the controller can SEE what is running, which is still
// a `docker ps` from here. The first switches the buttons off; the second
// only greys what the rows would claim.
//
// This block drives the FIRST: the node's own census stops reporting a
// daemon, which is a docker that died on a machine still talking to us. The
// server must not spend its `ps` timeout finding that out (every row it can
// draw comes from the store on this side), and the tab must come back with
// them rather than with one error line.
{
  writeFileSync(`${DIR}/dockerstate/version.fail`, '');
  const nodeNow = await page.evaluate(() => dockerNode);
  writeFileSync(`${DIR}/sandboxdata/census-extra.json`, JSON.stringify({ docker: '' }));
  // Waited for on THE ANSWER, not on the node record behind it: the census is
  // the agent's to send and rides its own poll, so the row updating and this
  // endpoint saying so are a moment apart, and the record being right is not
  // what the assertions below are about.
  const t0 = Date.now();
  await holdPoll(page);
  const seen = await page.evaluate(async (id) => {
    for (let i = 0; i < 80; i++){
      const raw = await (await fetch('/api/docker?node=' + encodeURIComponent(id))).json();
      if (raw.on === false){
        dockerList = raw; dockerRev++; drawPanes();
        return { on: false, why: raw.why || '(none)', blind: raw.blind,
                 ups: [...document.querySelectorAll('.dmtab [data-dm="up"]')].map(b => b.disabled) };
      }
      await new Promise(r => setTimeout(r, 250));
    }
    return { on: true, why: '(it never went off)', ups: [] };
  }, nodeNow);
  await freePoll(page);
  ok(seen.on === false && Date.now() - t0 < 25000,
     `a daemon the node does not report is asked nothing: no ps timeout to sit through (${
        seen.why.slice(0, 40)})`);
  ok(/reports no daemon|not dialing in/.test(seen.why),
     `...and the reason is the node's own, not the controller's ssh (${seen.why.slice(0, 70)})`);
  ok(seen.ups.length > 0 && seen.ups.every(Boolean),
     `...so every control is off, which is what "cannot act" means (${JSON.stringify(seen.ups)})`);
  // Waited for, not drawn by hand. The build the Send above queued is still
  // moving the devapp revision, and every move nulls dockerList and refetches,
  // so a drawPanes() here can land on the null and paint "loading…" with no
  // rows (B69). loadDocker repaints when its answer lands; that is the draw
  // this asks about.
  await page.waitForFunction(() => dockerList?.blind === true
    && document.querySelectorAll('.dmtab .row[data-inst]').length > 0,
    null, { timeout: 20000 });
  ok(true, '...and the manager still lists what is on record');

  // THE SECOND QUESTION, and the one B111 is about. The node reports its
  // daemon again, so it can be acted on, while the controller's own `docker
  // ps` to it fails, which is exactly the arrangement that ghosted everything:
  // a probe the WORK does not use deciding whether the work may happen.
  rmSync(`${DIR}/sandboxdata/census-extra.json`, { force: true });
  rmSync(`${DIR}/dockerstate/version.fail`, { force: true });
  writeFileSync(`${DIR}/dockerstate/ps.fail`, '');
  await holdPoll(page);
  const live = await page.evaluate(async (id) => {
    for (let i = 0; i < 80; i++){
      const raw = await (await fetch('/api/docker?node=' + encodeURIComponent(id))).json();
      if (raw.on === true && raw.blind === true){
        // The status poll's own copy, which is held still by holdPoll and is
        // about this same node: the tab reads it too, and a stale "docker
        // does not answer" there would gate the row whatever this answer
        // says. Set to what the next poll would fetch.
        state.docker = { on: true, why: '', node: id };
        dockerList = raw; dockerRev++; drawPanes();
        return { ups: [...document.querySelectorAll('.dmtab [data-dm="up"]')].map(b => b.disabled),
                 empty: document.querySelector('.dmtab .empty')?.textContent || '' };
      }
      await new Promise(r => setTimeout(r, 250));
    }
    return { ups: [], empty: '(the node never came back)' };
  }, nodeNow);
  await freePoll(page);
  ok(live.ups.length > 0 && live.ups.some(x => x === false),
     `a listing the controller cannot make does NOT switch off controls that run on the agent (${
        JSON.stringify(live.ups)})`);
  const seenWhy = live.empty;
  ok(/did not answer/.test(seenWhy) && /controls still work/.test(seenWhy),
     `...and the line says both halves: what failed, and that the buttons did not (${
        seenWhy.slice(0, 60)})`);
  // ...in docker's own words, cut from the TAIL. Its connect error leads with
  // the ssh command it ran and hides the reason at the very end, so cutting
  // from the front left "command [ssh -l bb -o Connect…" and nothing else,
  // the half the operator already knew (B106). This line is now the whole
  // account of what is not known, so it is the message.
  ok(/No route to host/.test(seenWhy) && !/ConnectTimeout/.test(seenWhy),
     `...which is the reason and not the command line (${seenWhy.slice(-60)})`);
  rmSync(`${DIR}/dockerstate/ps.fail`, { force: true });

  // Back to the shape where the node CANNOT be acted on, for what follows:
  // Remove's two halves are only a pair when the down cannot happen.
  writeFileSync(`${DIR}/sandboxdata/census-extra.json`, JSON.stringify({ docker: '' }));
  writeFileSync(`${DIR}/dockerstate/version.fail`, '');
  await page.evaluate(async (id) => {
    for (let i = 0; i < 80; i++){
      const raw = await (await fetch('/api/docker?node=' + encodeURIComponent(id))).json();
      if (raw.on === false){ dockerList = raw; dockerRev++; drawPanes(); return; }
      await new Promise(r => setTimeout(r, 250));
    }
  }, nodeNow);
  // And a row on a daemon that is not answering can still be got rid of.
  // Down is the first half of a remove and needs the daemon; forgetting the
  // record is the second and is this side's own file, so the verb does the
  // half it can and says which half that was. Asked through the API rather
  // than the button because the button's confirm() is the browser's.
  {
    const mk = await page.evaluate(async () => {
      const r = await fetch('/api/devapp', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: 'ep.silon', action: 'new', instance: 'stranded' }) });
      return r.json();
    });
    ok(!mk.error, `a second instance to strand (${JSON.stringify(mk).slice(0, 80)})`);
    const rm = await page.evaluate(async () => {
      const r = await fetch('/api/devapp', { method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: 'ep.silon', instance: 'stranded',
                               action: 'remove' }) });
      return r.json();
    });
    ok(rm.ok && rm.forgot && /does not answer/.test(rm.note || ''),
       `...and removing it takes the record and says nothing was taken down (${
         JSON.stringify(rm).slice(0, 90)})`);
    await page.evaluate(() => { dockerList = null; dockerRev++; return loadDocker(); });
    await page.waitForFunction(() => dockerList
      && !(dockerList.instances || []).some(i => i.instance === 'stranded'),
      null, { timeout: 20000 });
    ok(true, '...and the row is gone from the manager');
  }
  // BOTH halves back: the census reporting a daemon again is what lets the
  // node be acted on, and the ssh answering again is what lets it be seen.
  rmSync(`${DIR}/dockerstate/version.fail`, { force: true });
  rmSync(`${DIR}/sandboxdata/census-extra.json`, { force: true });
  await page.evaluate(async (id) => {
    for (let i = 0; i < 80; i++){
      const raw = await (await fetch('/api/docker?node=' + encodeURIComponent(id))).json();
      if (raw.on === true && !raw.blind){ dockerList = raw; dockerRev++; drawPanes(); return; }
      await new Promise(r => setTimeout(r, 250));
    }
  }, nodeNow);
  await page.waitForFunction(() => dockerList && !dockerList.blind,
                             null, { timeout: 20000 });
  // Asked again until it holds rather than sampled once: the status poll can
  // have caught the daemon down inside the window above, and its verdict
  // greys every row until the next poll; the tab repaints only when its own
  // revision moves, so refresh() and a fresh ask go together (B69).
  {
    const until = Date.now() + patience(20000);
    let live = false;
    while (!(live = await page.$$eval('.dmtab .row[data-inst]',
               rs => rs.length > 0 && rs.some(r => !r.classList.contains('off'))))
           && Date.now() < until){
      await page.evaluate(() => { refresh(); return loadDocker(); }).catch(() => {});
      await sleep(500);
    }
    ok(live, '...and it comes back live when the daemon does, with no un-gating to do');
  }
}

// A daemon that answers is not the same thing as the sandbox. Everything the
// manager does beyond compose runs a container as root over there, and the
// whole reason that is acceptable is that the far side is a box built to be
// wrecked, so the daemon has to carry the label nodes/provision-linux.sh puts on the
// one it made, and an unlabelled machine is refused rather than driven.
{
  // Through the CENSUS, because that is where the stamp is read from on an
  // agent node now: the provisioner writes it on the machine and the agent
  // reports it, rather than the controller reading a daemon label over an ssh
  // that has nothing to do with how the work gets there (B111).
  const nodeStamp = await page.evaluate(() => dockerNode);
  writeFileSync(`${DIR}/sandboxdata/census-extra.json`, JSON.stringify({ sandbox: false }));
  await page.evaluate(async (id) => {
    for (let i = 0; i < 80; i++){
      const raw = await (await fetch('/api/docker?node=' + encodeURIComponent(id))).json();
      if (raw.on === false){ dockerList = raw; dockerRev++; drawPanes(); return; }
      await new Promise(r => setTimeout(r, 250));
    }
  }, nodeStamp);
  // Waited for rather than assumed: the repaint is synchronous but the tab
  // has to be the one on screen, and an earlier file leaving another
  // document in the pane is enough to lose the race.
  await page.waitForSelector('.dmtab .empty', { timeout: 15000 });
  ok(/not a BuilderBot sandbox/.test(await page.$eval('.dmtab .empty', e => e.textContent)),
     'a daemon with no provisioner stamp is refused, and named as the reason');
  // The provisioner's own name, which is provision-linux.sh since there is a
  // macos one beside it. `provision\.sh` matched the name it had before that
  // and nothing since.
  ok(/provision-linux\.sh/.test(await page.$eval('.dmtab .empty', e => e.textContent)),
     '...saying what to run on the VM, since re-running it is the whole fix');
  rmSync(`${DIR}/sandboxdata/census-extra.json`, { force: true });
  await page.evaluate(async (id) => {
    for (let i = 0; i < 80; i++){
      const raw = await (await fetch('/api/docker?node=' + encodeURIComponent(id))).json();
      if (raw.on === true && !raw.blind){ dockerList = raw; dockerRev++; drawPanes(); return; }
      await new Promise(r => setTimeout(r, 250));
    }
  }, nodeStamp);
  await page.waitForFunction(() => dockerList && !dockerList.blind,
                             null, { timeout: 20000 });
  ok(true, '...and a stamped one is talked to again');
}

// Plug in a DIFFERENT sandbox and that one becomes the source of truth. Two
// VMs can wear one address (a rebuilt sandbox, a second machine given the old
// one's IP), so what a build was recorded against is checked by the daemon's
// own id as well, and a record from the machine no longer in play is cleared
// rather than left quoting a build that this daemon has never heard of.
{
  const store = () => JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'));
  // Build something, so there is a record to be about a daemon at all.
  await page.evaluate(() => dmAction('ep.silon', 'main', 'rebuild'));
  await page.waitForFunction(() => {
    const d = (dockerList?.instances || []).find(x => x.instance === 'main');
    return d && d.built_rev;
  }, null, { timeout: 60000 }).catch(() => {});
  const rec = () => (store()['ep.silon'] || {}).main || {};
  ok(!!rec().rev && !!rec().daemon_uid,
     'a build records which daemon it landed on, by that daemon\'s own id');
  // Through the CENSUS, for the same reason as the stamp above: the daemon's
  // own id is what the node reports about itself now, not something the
  // controller reads over an ssh the work does not use (B111).
  const nodeUid = await page.evaluate(() => dockerNode);
  writeFileSync(`${DIR}/sandboxdata/census-extra.json`,
                JSON.stringify({ docker_id: 'A-DIFFERENT-VM' }));
  await page.evaluate(async (id) => {
    for (let i = 0; i < 80; i++){
      const raw = await (await fetch('/api/docker?node=' + encodeURIComponent(id))).json();
      if (raw.src && raw.on === true && !raw.blind){
        dockerList = raw; dockerRev++; drawPanes();
        if (!(dockerList.instances || []).some(x => x.built_rev)) return;
      }
      await new Promise(r => setTimeout(r, 250));
    }
  }, nodeUid);
  ok(!rec().rev && !rec().daemon_uid,
     '...and pointing this at another sandbox clears it: the new daemon is the '
     + 'source of truth, not the last one\'s answers');
  ok(!!(store()['ep.silon'] || {}).main,
     '...while the instance itself stays: its compose and its env are this side\'s');
  rmSync(`${DIR}/sandboxdata/census-extra.json`, { force: true });
  await page.evaluate(() => { dockerList = null; dockerRev++; return loadDocker(); });
  await page.waitForFunction(() => dockerList && !dockerList.blind, null, { timeout: 20000 });
}

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
# DOCKER_HOST is not read any more (roadmap #18): the address comes from the
# node the call is addressed at, which on_node() puts on _node_ctx.
HOST = ['']
m.node_addr = lambda nid: HOST[0]
m.node_for = lambda cap=None: 'n1'
def sethost(a):
    HOST[0] = a
    m._node_ctx.addr = a

out = {}
sethost('ssh://bb@vm')
out['vm'] = m.source()
sethost('')
out['off'] = [m.source(), m.available()['why']]
print(json.dumps(out))
`], { encoding: 'utf8' });
  const ONE = JSON.parse(one.trim().split('\n').pop());
  ok(ONE.vm.kind === 'the sandbox VM' && ONE.vm.where === 'ssh://bb@vm',
     'the daemon is the sandbox VM the node record names, and nothing else is looked for');
  ok(!ONE.off[0].kind && /enroll the sandbox VM/.test(ONE.off[1]),
     '...and with no node the feature is off, with the reason said');
}

// Which paths a compose file is judged against. It was a hardcoded pair,
// /workspace and /devdata, which is what the mapping held on the day it was
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
  document.querySelector('.dmtab .row[data-inst="ep.silon|staging-two"] .dmpill')?.textContent || ''),
  { timeout: 40000 });
ok(true, '...and it comes up, because its env went in before the build');
ok(/--env-file/.test(dockerLog()),
   '...with the env saved before that build, not asked for after it');
const both = await page.$$eval('.dmtab .row[data-inst^="ep.silon|"]',
  rs => rs.map(r => r.dataset.inst));
ok(both.includes('ep.silon|main') && both.includes('ep.silon|staging-two'),
   '...beside the one the project already had');
// The failed Up earlier is a JOB that failed: the request that queued it was
// accepted, and the failure landed on the row. Before the queue it answered
// 400, which the browser logged as a failed resource load, and this counted
// that one. Nothing is refused now, so nothing may be logged.
const errs = await page.errors;
ok(errs.length === 0,
   `no console errors from the dev row${errs.length ? ', got: ' + JSON.stringify(errs) : ''}`);

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
// being created under whatever name was typed. A hint cannot be submitted.
ok(await page.$eval('#cYml', e => e.value) === ''
   && await page.$eval('#cEnv', e => e.value) === '',
   '...with both definitions empty, so nothing can be saved by accident');
ok(/services:/.test(await page.$eval('#cYml', e => e.placeholder))
   && /PUID=/.test(await page.$eval('#cEnv', e => e.placeholder)),
   '...and the shape each wants shown on the field, where it costs nothing to ignore');
ok(await page.$eval('#cEnvField', e => e.hidden) && await page.$eval('#cYmlField', e => e.hidden)
   && !await page.$eval('#cFormField', e => e.hidden),
   '...showing one pane at a time, the form first (R68 step 3)');
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
// An empty compose is refused rather than written: the placeholder is not
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
// ---- a row on a phone (R68 step 5) ---------------------------------------
// A project's row carries its ports, its services, its route and three
// settings, which at 390px was most of a screen each: the list stopped being
// a list. The detail is a fold there and open on a desktop, where its
// summary is not drawn at all, so that surface is what it always was.
{
  await openManager();
  const wide = await page.evaluate(() => {
    const d = document.querySelector('.dmtab .dmdet');
    return d ? { open: d.open, sum: getComputedStyle(d.querySelector('.dmsum')).display } : null;
  });
  ok(wide && wide.open && wide.sum === 'none',
     `on a desktop the detail is open with no summary drawn (${JSON.stringify(wide)})`);
  await page.setViewportSize({ width: 390, height: 844 });
  // A phone shows one thing at a time, and the manager is in the pane behind
  // the sidebar: without this the row measures zero and says nothing.
  await page.evaluate(() => { setView('terminal'); dockerList = null; dockerRev++; loadDocker(); });
  await page.waitForFunction(() => document.querySelector('.dmtab .dmdet')?.open === false,
                             null, { timeout: 15000 });
  const narrow = await page.evaluate(() => {
    const t = document.querySelector('.dmtab');
    const d = document.querySelector('.dmtab .dmdet');
    const acts = document.querySelector('.dmtab .dmacts');
    return { open: d.open, sum: getComputedStyle(d.querySelector('.dmsum')).display,
             sideways: t.scrollWidth > t.clientWidth + 2,
             actsVisible: !!acts && acts.getBoundingClientRect().height > 0 };
  });
  ok(!narrow.open && narrow.sum !== 'none',
     `on a phone it is shut, behind a summary that can be pressed (${JSON.stringify(narrow)})`);
  ok(!narrow.sideways && narrow.actsVisible,
     '...nothing scrolls sideways, and the row keeps its buttons whether it is open or shut');
  await page.click('.dmtab .dmsum');
  ok(await page.$eval('.dmtab .dmdet', d => d.open), '...and it opens on a press');
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => { setView('dashboard'); dockerList = null; dockerRev++; loadDocker(); });
  await page.waitForFunction(() => document.querySelector('.dmtab .dmdet')?.open === true,
                             null, { timeout: 15000 });
}

// ---- a manager, not a list (R68 steps 1 and 2) ---------------------------
// Start, stop, restart and the log work on ANY container the daemon
// reported, including the ones BuilderBot did not create. What makes that
// acceptable is the machine: the daemon belongs to a VM whose only job is
// running containers. What keeps it honest is the guard, which lets through
// one verb and one name rebuilt here, and the lookup, which asks the daemon
// again before acting on a name a page remembered.
{
  const ctl = (body) => page.evaluate(async b => {
    const r = await fetch('/api/dockerctl', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: r.status, ...(await r.json()) };
  }, body);
  const started = await ctl({ action: 'start', container: 'someone-elses' });
  ok(started.ok && /someone-elses/.test(started.out || ''),
     `a container this dashboard did not create can be started (${JSON.stringify(started).slice(0, 90)})`);
  ok(readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8').includes('someone-elses'),
     '...and the verb reached the daemon with that name');
  const bad = await ctl({ action: 'start', container: 'no-such-container' });
  ok(/no container called/.test(bad.error || ''),
     `a name the daemon does not report is refused, not passed to docker (${bad.error})`);
  const nonsense = await ctl({ action: 'destroy', container: 'someone-elses' });
  ok(/started, stopped or restarted/.test(nonsense.error || ''),
     `and a verb that is not one of the three is refused (${nonsense.error})`);
  const log = await ctl({ action: 'logs', container: 'someone-elses' });
  ok(log.ok && /hello from someone-elses/.test(log.text || ''),
     `its log comes back, timestamped (${(log.text || '').slice(0, 50).replace(/\n/g, ' / ')})`);
}

// The form that writes the compose file for you (R68 step 3): an image, its
// ports and volumes, and what it produces is the Compose tab beside it, so
// nothing about the container is hidden from the person making it.
{
  await page.evaluate(() => openNewContainer());
  await page.waitForSelector('#cmodal:not([hidden])', { timeout: 10000 });
  ok(await page.$eval('#cFormField', e => !e.hidden) && await page.$eval('#cYmlField', e => e.hidden),
     'New container opens on the form, with the compose file a tab away');
  await page.fill('#cName', 'grafanish');
  await page.fill('#cImage', 'grafana/grafana:11.0.0');
  await page.fill('#cPorts', '3001:3000');
  await page.fill('#cVols', './data:/var/lib/grafana');
  await page.fill('#cEnvLines', 'GF_SECURITY_ADMIN_USER=admin');
  await page.selectOption('#cRestart', 'always');
  const yml = await page.$eval('#cYml', e => e.value);
  ok(/image: "grafana\/grafana:11\.0\.0"/.test(yml) && /restart: always/.test(yml)
     && /- "3001:3000"/.test(yml) && /- "\.\/data:\/var\/lib\/grafana"/.test(yml)
     && /- "GF_SECURITY_ADMIN_USER=admin"/.test(yml),
     'the form writes the compose file as it is filled in, every value quoted');
  await page.click('#cGo');
  await page.waitForSelector('.dmtab .row[data-inst="grafanish|main"]', { timeout: 20000 });
  const onDisk = readFileSync(`${DIR}/state/containers/grafanish/docker-compose.yml`, 'utf8');
  ok(onDisk === yml, '...and what was shown is byte for byte what was written');
  // A port is a base-60 number to a YAML 1.1 parser unless it is quoted, which
  // is why every value the form writes is: 3001:3000 unquoted parses as 10803000.
  ok(/"3001:3000"/.test(onDisk), '...with the ports quoted, since YAML would read one as a number');
}

ok(/written here: this dashboard holds its compose file/.test(await page.$eval(
     '.dmtab .row[data-inst="radarr|main"]', r => r.textContent))
   && /Written here/.test(await page.$eval('.dmtab', t => t.textContent)),
   '...and the manager says which kind it is, on the row and over the group');
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
// `ep.silon` by string and is exactly it by the time _pname has run: same
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

// Removing takes it down and drops it from the list, and the project's
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



// ---- building an instance from another branch -----------------------------
// A project's tree is SHARED (one checkout for every session and every
// person on it), so "build the other branch" cannot mean switching it. An
// instance pinned to a ref builds from a worktree of its own, beside the
// project and carrying a .bbignore, and the project's checkout is untouched.
{
  const G = (...a) => execFileSync('git', ['-C', D, ...a], { env, encoding: 'utf8' });
  G('checkout', '-q', '-b', 'sidebranch');
  writeFileSync(`${D}/ONLY-ON-SIDE.txt`, 'x\n');
  G('add', '-A'); G('commit', '-qm', 'side work');
  const sideSha = G('rev-parse', '--short=7', 'HEAD').trim();
  G('checkout', '-q', '-');
  const api = (body) => page.evaluate(async b => {
    const r = await fetch('/api/devapp', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: r.status, ...(await r.json()) };
  }, body);

  const bad = await api({ project: 'ep.silon', instance: 'main', action: 'ref', ref: 'nope' });
  ok(bad.status === 400 && /no branch or commit/.test(bad.error || ''),
     `a ref the project does not have is refused here, not at build time (${
        String(bad.error).slice(0, 50)})`);
  const set = await api({ project: 'ep.silon', instance: 'main', action: 'ref', ref: 'sidebranch' });
  ok(set.ok && set.ref === 'sidebranch', `an instance can be pinned to a branch (${
     JSON.stringify(set).slice(0, 50)})`);
  // What it is built FROM is that branch's tip, not the checkout's, so the
  // row stops saying "the code has moved" every time the project's own
  // branch does, and says it when the pinned one moves.
  await dmRefresh();
  const refPick = await page.$eval(DM, r => r.querySelector('[data-dmref]')?.value || '');
  ok(refPick === 'sidebranch', `...and the Ref control holds it (${refPick || 'empty'})`);
  const st = await api({ project: 'ep.silon', instance: 'main', action: 'state' });
  ok((st.state || {}).ref === 'sidebranch', 'the state carries the pin for the row');
  // The PIN is not a build. Pressing Apply changes what the next build is made
  // of and moves nothing that already exists, so what is built here still
  // names no branch: the commit is the truth, the branch is the setting, and
  // this is the moment they disagree.
  ok(!(st.state || {}).built_ref,
     `...and what is already built names no branch, because it was built before the pin (${
        JSON.stringify((st.state || {}).built_ref)})`);
  const pinned = await page.evaluate(x => dmBuilt(x), st.state);
  ok(!/sidebranch/.test(pinned),
     `...so the row's built-from line does not claim it (${pinned})`);
  // The build tree is made on demand, beside the project, and is not a
  // project itself.
  // Posted rather than pressed: the button's confirm() is the browser's, and
  // what is under test is the server deciding where the build comes from.
  const built = await api({ project: 'ep.silon', instance: 'main', action: 'rebuild' });
  ok(!built.error, `the rebuild is taken (${JSON.stringify(built).slice(0, 60)})`);
  await idle();
  ok(existsSync(`${DIR}/ws/ep-silon-main-build/ONLY-ON-SIDE.txt`),
     'the build tree is a worktree of that branch, beside the project');
  ok(existsSync(`${DIR}/ws/ep-silon-main-build/.bbignore`),
     '...marked so the projects list does not take it for one');
  ok(new RegExp(`--project-directory ${DIR}/ws/ep-silon-main-build`).test(dockerLog()),
     `...and compose built from it rather than from the project (${
        (dockerLog().match(/--project-directory \S+/g) || []).slice(-1)[0] || 'none'})`);
  ok(sideSha.length === 7, `the branch had its own commit (${sideSha})`);
  // NOW it is true, and the line says it: the ref is stamped by the build that
  // used it, so it names the branch and the commit together. Read off dmBuilt
  // rather than the row, because a running instance's state line says it is
  // running. This is the sentence it falls back to, and the one the blind
  // listing carries.
  const after = await api({ project: 'ep.silon', instance: 'main', action: 'state' });
  ok((after.state || {}).built_ref === 'sidebranch',
     `...and the build stamps which branch it came from (${
        JSON.stringify((after.state || {}).built_ref)})`);
  const line = await page.evaluate(x => dmBuilt(x), after.state);
  ok(/^built from sidebranch [0-9a-f]{7}$/.test(line),
     `...and the row's line names both (${line})`);
  // TWO AT ONCE is the case this is for, and the obstacle is ports: two
  // instances of one project are the same compose file, so the second
  // publishes what the first already has. Said before the press rather than
  // by compose after it, read off the container list the manager already
  // has, so it costs nothing.
  {
    const two = await api({ project: 'ep.silon', action: 'new', instance: 'onbranch',
                            ref: 'sidebranch' });
    ok(!two.error && two.instance === 'onbranch',
       `a second instance can be made on a branch in one gesture (${
          JSON.stringify(two).slice(0, 60)})`);
    const st2 = await api({ project: 'ep.silon', instance: 'onbranch', action: 'state' });
    ok((st2.state || {}).ref === 'sidebranch',
       '...pinned from the moment it exists, so its first build is that branch');
    // In a field of its own, not in `problems`: the manager says it as a
    // fault (Up would fail), the Artifacts view as a note (Send opens the env
    // the port goes in), and one line could not read right on both.
    const clash = ((st2.state || {}).port_clash || []).join(' ');
    ok(!((st2.state || {}).problems || []).some(x => /publish the same ports/.test(x))
       && (!(st2.state || {}).ports?.length || /\d+ \(/.test(clash) || clash === ''),
       `...and a port another container already has is named in its own field, not as a problem (${
          clash.slice(0, 70) || 'nothing published'})`);
    await api({ project: 'ep.silon', instance: 'onbranch', action: 'remove' });
    await idle();
  }
  // THE ARRANGEMENT THE OPERATOR WAS IN: the project's own checkout standing
  // on the branch the instance is pinned to. git allows a branch in one
  // worktree at a time, so a build tree that CLAIMED the name was refused
  // outright ("'rack-drift' is already used by worktree at
  // /workspace/word-jumble") for what is the ordinary arrangement rather
  // than an edge of one.
  {
    // The trap in the OTHER direction, and the one that fails first: a build
    // tree holding a branch is a branch the person's own shell can no longer
    // check out: a button here taking a name hostage. Asserted rather than
    // called, so it reads as a failure with a name on it and not a stack.
    let moved = '';
    try { G('checkout', '-q', 'sidebranch'); }
    catch (e) { moved = String(e.stderr || e).split('\n')[0]; }
    ok(!moved, `the project's own checkout can still move onto the branch a build tree was made from${
       moved ? `: ${moved.slice(0, 90)}` : ''}`);
    const again = await api({ project: 'ep.silon', instance: 'main', action: 'rebuild' });
    ok(!again.error, `a branch the project itself is standing on still builds (${
       JSON.stringify(again).slice(0, 70)})`);
    await idle();
    ok(existsSync(`${DIR}/ws/ep-silon-main-build/ONLY-ON-SIDE.txt`),
       '...from that branch, rather than from whatever else was lying around');
    ok(G('rev-parse', '--abbrev-ref', 'HEAD').trim() === 'sidebranch',
       '...with the project left standing exactly where it was');
    const head = execFileSync('git', ['-C', `${DIR}/ws/ep-silon-main-build`,
                                      'rev-parse', '--abbrev-ref', 'HEAD'],
                              { env, encoding: 'utf8' }).trim();
    ok(head === 'HEAD',
       `...and the build tree claims no branch name, so it blocks nobody's checkout (${head})`);
    G('checkout', '-q', '-');
  }
  const off = await api({ project: 'ep.silon', instance: 'main', action: 'ref', ref: '' });
  ok(off.ok && off.ref === '', '...and clearing it puts the build back on the project itself');
  // The worktree first: git refuses to delete a branch that one has checked
  // out, which is the same protection that makes this design safe at all.
  try { G('worktree', 'remove', '--force', `${DIR}/ws/ep-silon-main-build`); }
  catch (e) { rmSync(`${DIR}/ws/ep-silon-main-build`, { recursive: true, force: true });
              try { G('worktree', 'prune'); } catch (e2) { /* nothing to prune */ } }
  G('branch', '-D', 'sidebranch');
}

// ---- who may rebuild it: the dial on the docker row -----------------------
// Making a container, removing one, Up, Down and Env are the operator's.
// REBUILD is the one a project can hand to its session, because a project
// whose work IS the container has a loop that cannot close without it:
// change it, rebuild it, look at what it did. Three settings, the notebook's
// own words: deny (the default, refused with the sentence that names the
// dial rather than a bare 403), ask (a person reads the reason and allows
// one), auto.
{
  const { fileURLToPath } = await import('node:url');
  const REPO = fileURLToPath(new globalThis.URL('../../../', import.meta.url));
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'ep.silon', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`,
                               WORKSPACE: `${DIR}/ws` } }).trim();
  // From NODE, not from the page: a fetch in the browser carries the
  // operator's cookie as well as the header, and the server answers the
  // cookie, so the call would be the operator's and the gate under test
  // would never be reached. A session has a token and nothing else.
  const asSession = async (body) => {
    const r = await fetch(URL.replace(/\/$/, '') + '/api/devapp',
      { method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
        body: JSON.stringify(body) });
    return { status: r.status, ...(await r.json()) };
  };
  const off = await asSession({ project: 'ep.silon', action: 'rebuild' });
  // The tab is named as well as the switch: the controls moved from the
  // artifact row to the Docker tab and this sentence stayed behind, pointing
  // a session at a tab that no longer has it.
  ok(off.status === 403 && /Docker tab has the dial that hands it over/.test(off.error || ''),
     `a session cannot rebuild until the project says so, and is told where the dial is (${
        JSON.stringify(off).slice(0, 90)})`);
  // The two verbs that make and unmake a container are not on the dial at
  // all: they are docker-write, which a session's principal never has, so
  // the grant cannot reach them however it is set. This is the operator's
  // own line (the user makes them, Claude rebuilds them), and it is checked
  // here rather than trusted to the ordering of two ifs.
  for (const act of ['new', 'remove', 'env-set', 'route']){
    const r = await asSession({ project: 'ep.silon', action: act, instance: 'main' });
    ok(r.status === 403 && /administrator/.test(r.error || ''),
       `...and ${act} is not a session's at any setting (${String(r.error).slice(0, 48)})`);
  }
  // An instance on ANOTHER node is not this session's to touch, whatever the
  // dial says. It is a container still running on a machine this session is
  // not on, left there on purpose when the project moved; using or rebuilding
  // it would act on somebody else's box, and a rebuild would bounce a service
  // somebody may still be using. Refused before the dial is consulted, so
  // turning the dial to auto does not open it.
  {
    const store2 = `${DIR}/state/devapps.json`;
    const before = readFileSync(store2, 'utf8');
    const d = JSON.parse(before);
    d['ep.silon'] = { ...d['ep.silon'],
                      main: { ...(d['ep.silon'] || {}).main, node: 'n_anothernode' } };
    writeFileSync(store2, JSON.stringify(d));
    await page.evaluate(async () => {
      await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ project: 'ep.silon', devbuild: 'auto' }) });
    });
    for (const act of ['rebuild', 'test']){
      const r = await asSession({ project: 'ep.silon', action: act, instance: 'main' });
      ok(r.status === 403 && /on another node/.test(r.error || ''),
         `a session may not ${act} an instance left on the node the project moved off (${
           String(r.error).slice(0, 56)})`);
    }
    // ...and it can still SEE it, which is how it knows to say so rather than
    // reporting the verb as broken.
    const seen = await asSession({ project: 'ep.silon', action: 'state', instance: 'main' });
    ok(seen.status === 200,
       '...while reading it is still allowed, so a session can say where it went');
    writeFileSync(store2, before);
    await page.evaluate(async () => {
      await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ project: 'ep.silon', devbuild: 'deny' }) });
    });
  }
  // Reading is nobody's secret: the state is how a session knows what it is
  // looking at before it asks for anything.
  const read = await asSession({ project: 'ep.silon', action: 'state' });
  ok(read.status === 200 && (read.state || {}).compose === true,
     '...while reading the row is allowed, switch or no switch');
  const dial = (mode) => page.evaluate(async (m) => {
    await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ project: 'ep.silon', devbuild: m }) });
  }, mode);
  // ---- ask: nobody builds until a person says so --------------------------
  await dial('ask');
  const nowhy = await asSession({ project: 'ep.silon', action: 'rebuild' });
  ok(nowhy.status === 400 && /what the rebuild is for/.test(nowhy.error || ''),
     `on ask a rebuild with no reason is refused, since the reason is the point (${
        String(nowhy.error).slice(0, 50)})`);
  const asked = await asSession({ project: 'ep.silon', action: 'rebuild',
                                  why: 'the compose file changed and I want to see it run' });
  ok(asked.status === 200 && asked.id && !asked.started,
     `...and with one it is queued rather than built (${JSON.stringify(asked).slice(0, 70)})`);
  ok(await page.evaluate(async (id) => {
       const j = await (await fetch('/api/phone')).json();
       return (j.asks || []).some(a => a.id === id && a.kind === 'rebuild');
     }, asked.id),
     '...and it is waiting on a person, in the one list of asks');
  // The session sees its own request's outcome and nothing else, the same
  // scoping the phone and root asks have.
  const pend = await (await fetch(URL.replace(/\/$/, '') + '/api/phone',
    { method: 'POST', headers: { 'Content-Type': 'application/json',
                                 Authorization: 'Bearer ' + tok },
      body: JSON.stringify({ action: 'outcome', id: asked.id }) })).json();
  ok(pend.state === 'pending', `...which the session can watch (${pend.state})`);
  await page.evaluate(async (id) => {
    await fetch('/api/phone', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'allow', id }) });
  }, asked.id);
  const done = await (await fetch(URL.replace(/\/$/, '') + '/api/phone',
    { method: 'POST', headers: { 'Content-Type': 'application/json',
                                 Authorization: 'Bearer ' + tok },
      body: JSON.stringify({ action: 'outcome', id: asked.id }) })).json();
  ok(done.state === 'done' && !done.code,
     `...and Allow starts the build the session asked for (${JSON.stringify(done).slice(0, 70)})`);
  await idle();
  // ---- auto: the loop, with nobody in it ----------------------------------
  await dial('auto');
  const on = await asSession({ project: 'ep.silon', action: 'rebuild' });
  ok(on.status === 200 && !on.error && on.started,
     `...and on auto the same call is taken without asking (${JSON.stringify(on).slice(0, 60)})`);
  // The control lives on the DOCKER tab, beside the Rebuild it hands over,
  // and it is NOT gated with the daemon buttons: whose decision this is does
  // not depend on a machine answering. Drawn from the same setting rather
  // than a second copy of it.
  const SW = '.dmtab [data-dmclaude="ep.silon"]';
  // Through the manager's own opener, which waits for the ROWS to be there.
  // A bare openDocker() returns before the list has arrived, so this was a
  // twenty-second bet on a fetch finishing, and it lost in a full run on a
  // loaded box while passing alone straight afterwards (B118). The dial is
  // drawn from that list, so the row being present is the real condition.
  await dmRefresh();
  await page.waitForFunction(s2 => document.querySelector(s2)?.value === 'auto',
                             SW, { timeout: 20000 });
  ok(await page.$eval(SW, e => e.value === 'auto' && !e.disabled
                              && [...e.options].map(o => o.value).join() === 'deny,ask,auto'),
     'the docker tab carries the dial, on auto, with all three settings and live whatever the daemon says');
  // Nothing on a tab takes effect until Apply (docs/design-language.md,
  // Settings). This wrote on the pick when it was a switch, which is the one
  // control on the page that could not be reconsidered.
  ok(await page.$eval('.dmtab [data-dmclaudeapply="ep.silon"]', b => b.disabled),
     '...with its Apply asleep until something is picked');
  ok(await page.$('#devClaude') === null && await page.$('.artrow [data-dmclaude]') === null,
     '...and not on the artifact row, which is where it was asked not to be');
  // Turned off from the row itself, which is the gesture this is for,
  // and waited on the SERVER's own copy of the setting rather than on the
  // checkbox, because the checkbox is redrawn from the poll and its state
  // between the click and the next payload is nobody's answer.
  await page.selectOption(SW, 'deny');
  ok(await page.$eval('.dmtab [data-dmclaudeapply="ep.silon"]', b => !b.disabled),
     '...which wakes on a pick that differs from what is saved');
  // The pick alone changes nothing on the server: read it back before the
  // press, not after, or this proves only that the press works.
  ok((await asSession({ project: 'ep.silon', action: 'rebuild' })).status === 200,
     '...and until it is pressed the grant is exactly what it was');
  await page.click('.dmtab [data-dmclaudeapply="ep.silon"]');
  // Falsy, not `'deny'`: a record with nothing left in it is removed rather
  // than stored, so the row's prefs go back to the thin default and the
  // field is simply absent. Absent and deny are the same answer here.
  await refreshUntil(page, () => !((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.devbuild,
    { timeout: 20000 });
  ok((await asSession({ project: 'ep.silon', action: 'rebuild' })).status === 403,
     '...and turning it back to deny there takes the grant back');
  // ---- where the tests run (R48 step 3, moved by R68 step 6) -------------
  // The setting lives with the project's node and test command now, in its
  // settings dialog: it is the project's, and having it here meant somebody
  // setting a project up had to finish on a machine tab. The row still says
  // what it is set to, because this is where a person wonders, and the words
  // link to where it is changed.
  ok(/Tests run in this container when it is up, else on the node/.test(
       await page.$eval('.dmtab .row[data-inst^="ep.silon|"]', r => r.textContent.replace(/\s+/g, ' '))),
     'the row says where this project\'s tests run, in words');
  ok(await page.$('.dmtab [data-dmtestgo="ep.silon"]') !== null
     && await page.$('.dmtab [data-dmtest="ep.silon"]') === null,
     '...and links to the project settings rather than carrying the control');
  // ...and the control is there, offered only where there is a container to
  // run in: a project with no compose file is not asked the question.
  await page.evaluate(() => { openProjectsTab(); });
  await page.waitForSelector('.doc .projtab [data-rn="ep.silon"]', { timeout: 15000 });
  await page.click('.doc .projtab [data-rn="ep.silon"]');
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  ok(await page.$eval('#rnTestWhere', e => !e.hidden)
     && await page.$eval('#rnDevTest', e => [...e.options].map(o => o.value).join() === 'either,only'),
     'the project settings dialog carries where its tests run, beside its node and command');
  await page.selectOption('#rnDevTest', 'only');
  await page.click('#rnGo');
  await page.waitForSelector('#rnmodal', { state: 'hidden', timeout: 10000 });
  await refreshUntil(page, () => ((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.devtest === true, { timeout: 20000 });
  ok(JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects['ep.silon'].devtest === true,
     '...and saving it there is what writes the setting');
  await page.click('.doc .projtab [data-rn="alpha"]');
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  ok(await page.$eval('#rnTestWhere', e => e.hidden),
     '...while a project with no compose file is not asked the question at all');
  await page.evaluate(() => { document.querySelectorAll('.modal').forEach(m => { m.hidden = true; }); openDocker(); });
  await page.waitForSelector('.dmtab', { timeout: 15000 });
  await page.evaluate(async () => {
    await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ project: 'ep.silon', devtest: true }) });
  });
  await refreshUntil(page, () => ((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.devtest === true, { timeout: 20000 });
  ok(JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects['ep.silon'].devtest === true,
     'it is stored on the project, as the one boolean it is');
  await page.evaluate(() => { dockerList = null; loadDocker(); });
  await page.waitForFunction(() => /only in this container/.test(
    document.querySelector('.dmtab')?.textContent || ''), null, { timeout: 20000 });
  ok(true, '...and the row says the other thing once it is set');
  await page.evaluate(async () => {
    await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ project: 'ep.silon', devtest: false }) });
  });
  await refreshUntil(page, () => !((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.devtest, { timeout: 20000 });
  ok(!('devtest' in (JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects['ep.silon'] || {})),
     '...and off is absent from the record rather than stored as false');
}



// ---- the tests inside the dev instance (roadmap R48, step 1) --------------
// The container is the boundary: a suite that tests BuilderBot must not
// disturb the BuilderBot it runs on. The project's recorded test command,
// and nothing else, runs through `compose exec` in the service the project
// builds, as a compose job; the stub docker runs the command right here,
// which proves the wiring, the log and the exit code without a container.
// Open to a session with the rebuild dial on deny: a test run is not a
// rebuild. A container that is down is said so, never started.
{
  const REPO = fileURLToPath(new globalThis.URL('../../../', import.meta.url));
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'ep.silon', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`,
                               WORKSPACE: `${DIR}/ws` } }).trim();
  const api = (body) => page.evaluate(async b => (await (await fetch('/api/devapp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json()), body);
  const asSession = async (body) => {
    const r = await fetch(URL.replace(/\/$/, '') + '/api/devapp',
      { method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
        body: JSON.stringify(body) });
    return { status: r.status, ...(await r.json()) };
  };
  const setTest = (cmd) => page.evaluate(async (c) => {
    await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ project: 'ep.silon', test: c }) });
  }, cmd);
  const finished = async (jid) => {
    for (let i = 0; i < 120; i++){
      const j = await page.evaluate(async id => (await (await fetch(`/api/v1/jobs?id=${id}`)).json()), jid);
      if (['succeeded', 'failed', 'canceled'].includes(j.state)) return j;
      await new Promise(r => setTimeout(r, 500));
    }
    return { state: 'still running' };
  };
  await api({ project: 'ep.silon', instance: 'main', action: 'up' });
  await refreshUntil(page, () => true, { timeout: 5000 });
  await setTest('printf "TEST-RAN-%s\\n"');
  const nocmd = await asSession({ project: 'ep.silon', action: 'test', args: ['one', 'two'] });
  ok(nocmd.status === 200 && nocmd.started && /^j_/.test(nocmd.job || ''),
     `a session runs the project's tests inside its instance with the dial on deny (${JSON.stringify(nocmd).slice(0, 80)})`);
  const j1 = await finished(nocmd.job);
  ok(j1.state === 'succeeded' && /TEST-RAN-one\n.*TEST-RAN-two/s.test(j1.log || ''),
     `...the recorded command runs there with the arguments as positional parameters (${j1.state}: ${(j1.log || '').replace(/\n/g, ' / ').slice(-160)})`);
  ok(/exec -T -e BB_TEST_TIMING=1 -e BB_IN_INSTANCE=1 app sh -c printf/.test(j1.log || ''),
     '...through compose exec into the service the project builds, with timing on for the registry, and no working directory when nothing mounts the project');
  // A compose that mounts the project (or the whole share it sits in) puts
  // the tests in the project's directory inside the container: the first
  // run of BuilderBot's own suite inside its instance ran at / instead.
  writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
    volumes: [{ type: 'bind', source: `${DIR}/ws`, target: '/workspace' }] } } }));
  const j1b = await finished((await asSession({ project: 'ep.silon', action: 'test', args: ['wd'] })).job);
  ok(/exec -T -e BB_TEST_TIMING=1 -e BB_IN_INSTANCE=1 -w \/workspace\/ep\.silon app sh -c/.test(j1b.log || ''),
     `...and in the project's directory inside the container when the compose mounts it (${(j1b.log || '').match(/exec [^\n]*/)?.[0]?.slice(0, 90)})`);
  // BB_IN_INSTANCE is how run.sh tells "these tests ARE the container's" from
  // "these tests were run around it": a dev instance is a container and so is
  // the controller, so the suite cannot work it out for itself, and without it
  // the container-only setting could only be enforced by asking nicely (R65).
  ok(/-e BB_IN_INSTANCE=1/.test(j1.log || '') && /-e BB_IN_INSTANCE=1/.test(j1b.log || ''),
     '...carrying the mark that says this run is the instance\'s own');
  rmSync(stubCfg, { force: true });
  await setTest('false');
  const j2 = await finished((await asSession({ project: 'ep.silon', action: 'test' })).job);
  ok(j2.state === 'failed' && j2.exit_code === 1,
     `a failing test command is a failed job carrying its exit code (${j2.state} ${j2.exit_code})`);
  // A request naming no instance means the project's only one, whatever it
  // is called: BuilderBot's own is builderbot-dev, and a session's bb devapp
  // answered for a `main` that did not exist.
  const only = await page.evaluate(async () => (await (await fetch('/api/devapp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'ep.silon', action: 'state' }) })).json()));
  ok((only.state || only).name === 'ep-silon' || (only.state || only).instance === 'main',
     `a request naming no instance is answered for the project's only one (${JSON.stringify(only.state || only).slice(0, 60)})`);
  const bad = await asSession({ project: 'ep.silon', action: 'test', args: ['$(rm -rf /)'] });
  ok(bad.status === 400 && /argument the test command cannot take/.test(bad.error || ''),
     'an argument that is not a plain word is refused before anything runs');
  await api({ project: 'ep.silon', instance: 'main', action: 'down' });
  await refreshUntil(page, () => true, { timeout: 5000 });
  const down = await asSession({ project: 'ep.silon', action: 'test' });
  ok(down.status === 400 && /is not running: Up on the Docker tab/.test(down.error || ''),
     `a container that is down is said so and never started behind the operator's back (${down.error})`);
  // The refusal that makes the container the only way (step 3): from a
  // session on a node, with the row set to `only` and the instance down,
  // bb test names the instance and runs nothing on the node. With the row
  // on `either` the same call would queue a job on the node, which the
  // fixture has none of, so that half is the routing step 1 already proves.
  {
    const setWhere = (only) => page.evaluate(async (v) => {
      await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ project: 'ep.silon', devtest: v }) });
    }, only);
    await setWhere(true);
    const nodeEnv = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                      BB_TOKEN: tok, BB_NODE: 'agentbox', BB_PROJECT: 'ep.silon',
                      BB_TREE: '/workspace/ep.silon' };
    let out = '', code = 0;
    try {
      out = execFileSync('bash', [`${REPO}/scripts/bb`, 'test'],
        { encoding: 'utf8', cwd: `${DIR}/ws/ep.silon`, env: nodeEnv, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (e) { code = e.status; out = String(e.stderr || '') + String(e.stdout || ''); }
    ok(code !== 0 && /tests run only inside its dev instance \(ep-silon\), which is not running: Up on the Docker tab/.test(out)
       && /Nothing runs on the node/.test(out),
       `with the row on only and the instance down, bb test from a session refuses, naming the instance (${
         code}: ${out.replace(/\s+/g, ' ').slice(0, 120)})`);
    await setWhere(false);
  }
  await setTest('');
}

// ---- two rules the env gate and the path mapping live by ----------------
// Driven at the module: both are pure reads of a compose file and a node
// record, and the dashboard's rows only carry their answers.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile, types
from pathlib import Path
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
out = {}
# A key with a default in the compose file is not missing; one the file
# never names still is; one it needs with no default is.
d = Path(tempfile.mkdtemp())
(d / 'proj').mkdir(); (d / 'env').mkdir()
m.configure(workspace=str(d), state=str(d), write_json=lambda p, o: None, queue=None)
(d / 'proj' / '.env.example').write_text('NEEDED=\\nDEFAULTED=99\\nUNUSED=\\nBARE=\\nASKED=\\n')
(d / 'proj' / 'docker-compose.yml').write_text(
    'services:\\n  app:\\n    image: x\\n    environment:\\n      A: \${NEEDED}\\n      B: \${DEFAULTED:-99}\\n      C: $BARE\\n      D: \${ASKED:?say}\\n')
m.WORKSPACE = d; m.ENVDIR = d / 'env'
out['required'] = sorted(m.required_vars((d / 'proj' / 'docker-compose.yml').read_text()))
out['missing'] = m.missing_env('proj')
# /workspace maps to itself when the node reports the share mounted there,
# and nowhere without either a pair or the mount.
m.WORKSPACE = Path('/workspace')
m.node_paths = lambda nid: {}
m._default_node = lambda: 'n1'
m._mount_roots = lambda: {'/workspace': 'projects'}
class Q:
    mounts = []
    def node(self, nid): return {'id': nid, 'reported': {'mounts': self.mounts}}
q = Q(); m.queue = q
out['bare'] = m.host_map()[0]
q.mounts = [{'path': '/workspace', 'mounted': True}]
out['mounted'] = m.host_map()[0]
m.node_paths = lambda nid: {'/workspace': '/mnt/user/projects'}
out['written'] = m.host_map()[0]
print(json.dumps(out))
`], { encoding: 'utf8' });
  const r = JSON.parse(out);
  ok(r.required.join(',') === 'ASKED,BARE,NEEDED',
     `a compose file needs the variables it names with no default, bare or with :?, and nothing else (${r.required})`);
  ok(r.missing.join(',') === 'NEEDED,UNUSED,BARE,ASKED',
     `...and the env gate leaves only a key with a default unasked; one the file never names is still the example's to require (${r.missing})`);
  ok(JSON.stringify(r.bare) === '{}' && JSON.stringify(r.mounted) === '{"/workspace":"/workspace"}',
     `/workspace maps to itself on a node that reports the share mounted there, and to nothing on one that does not (${JSON.stringify(r.mounted)})`);
  ok(JSON.stringify(r.written) === '{"/workspace":"/mnt/user/projects"}',
     `...and a written pair still wins (${JSON.stringify(r.written)})`);
}

// ---- a container shown under a project -------------------------------------
// A dev radarr for a media project belongs in that project's notebook, not
// only in the manager: New container takes a project to show it under, the
// record keeps it, the manager's row says so, and the project's Docker view
// lists it beside the project's own instances with the same controls.
{
  const made = await page.evaluate(async () => (await (await fetch('/api/container', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'create', name: 'helper-for-eps', for: 'ep.silon',
                           compose: 'services:\n  app:\n    image: alpine\n', env: '' }) })).json()));
  ok(made.ok && made.project === 'helper-for-eps', `a container written here can name the project it belongs with (${JSON.stringify(made).slice(0, 80)})`);
  const bad = await page.evaluate(async () => (await (await fetch('/api/container', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'create', name: 'helper-for-nobody', for: 'no-such-project',
                           compose: 'services:\n  app:\n    image: alpine\n', env: '' }) })).json()));
  ok(/not a project: no-such-project/.test(bad.error || ''), 'a project nobody can see is refused');
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  await page.waitForFunction(() => (dockerList?.instances || []).some(d => d.project === 'helper-for-eps' && d.for === 'ep.silon'),
                             null, { timeout: 20000 });
  ok(true, 'the manager\'s answer carries which project it is shown under');
  await page.evaluate(() => openNotebook('ep.silon'));
  await nbShown(page);
  await nbTab(page, 'docker');
  await page.waitForFunction(() => document.querySelector('.pane .nb #dkList .row[data-inst="helper-for-eps|main"]'),
                             null, { timeout: 20000 });
  const view = await page.$eval('.pane .nb [data-view="docker"]', v => ({
    hint: v.querySelector('#dkHint').textContent,
    rows: [...v.querySelectorAll('#dkList .row[data-inst]')].map(r => r.dataset.inst),
    forLine: v.querySelector('#dkList .row[data-inst="helper-for-eps|main"] .sub')?.textContent || '',
    buttons: [...v.querySelectorAll('#dkList .row[data-inst="helper-for-eps|main"] [data-dm]')].map(b => b.dataset.dm) }));
  ok(view.rows.includes('helper-for-eps|main') && view.rows.includes('ep.silon|main'),
     `the project's Docker view lists its own instance and the container shown under it (${view.rows.join(' ')})`);
  ok(/for ep\.silon/.test(view.forLine) && view.buttons.includes('up') && view.buttons.includes('rebuild'),
     `...with the manager's own row, saying whose it is, and its controls (${view.buttons.join(' ')})`);
  ok(/2 containers of ep\.silon's on/.test(view.hint), `...and a line counting them (${view.hint.slice(0, 80)})`);
  await page.evaluate(async () => (await (await fetch('/api/devapp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'helper-for-eps', instance: 'main', action: 'remove' }) })).json()));
}

// The fixture goes back the way artifacts.mjs leaves alpha.
rmSync(`${D}/docker-compose.yml`, { force: true });
rmSync(`${D}/.env.example`, { force: true });
rmSync(`${D}/newfile.txt`, { force: true });
rmSync(`${D}/again.txt`, { force: true });
rmSync(`${D}/after-interrupt.txt`, { force: true });
rmSync(`${D}/.git`, { recursive: true, force: true });
git('init', '-q', '.');
// ---- removing a written container takes its env (bug #41) -----------------
// A project's instance keeps its env on Remove, deliberately: the promise is
// that sending it again finds it. A written container has nowhere to come
// back from, so keeping its env left one file per removal in /config/devenv
// with nothing that would ever read it. Its own env and no other: a live
// instance whose name merely ends the same way is somebody else's.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp(); os.makedirs(d + '/devenv')
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None)
for n in ('sonarr', 'my-sonarr', 'notsonarr'):
    open(d + '/devenv/' + n + '.env', 'w').write('PORT=1')
m._load = lambda: {'my-sonarr': {'main': {}}}
gone = m.forget_container('sonarr')
print(json.dumps({'gone': sorted(gone),
                  'left': sorted(x for x in os.listdir(d + '/devenv'))}))
`], { encoding: 'utf8' });
  const FC = JSON.parse(out.trim().split('\n').pop());
  ok(JSON.stringify(FC.gone) === JSON.stringify(['sonarr.env']),
     `removing a written container takes its env (${FC.gone.join(', ')})`);
  ok(FC.left.includes('my-sonarr.env') && FC.left.includes('notsonarr.env'),
     `...and leaves a live instance that merely ends the same way, and a partial match (${FC.left.join(', ')})`);
}

// A one-shot service that ran and exited 0 is finished, not down: the row
// says running and the chip says finished, while a service that exited
// non-zero still makes the row partly up (B147).
{
  const row = svc => ({ project: 'delta', instance: 'delta-dev', name: 'delta-dev', running: true, exists: true,
    source: 'project', ports: [], services: [
      { service: 'app', name: 'app', state: 'running', status: 'Up 5 hours (healthy)' },
      { service: 'db', name: 'db', state: 'running', status: 'Up 5 hours (healthy)' }, svc] });
  const draw = async svc => page.evaluate(r => { const el = document.createElement('div');
    el.innerHTML = dmRowsHtml([r], null, false); return el.textContent.replace(/\s+/g, ' '); }, row(svc));
  const seeded = await draw({ service: 'seed', name: 'seed', state: 'exited', status: 'Exited (0) 5 hours ago' });
  const broken = await draw({ service: 'seed', name: 'seed', state: 'exited', status: 'Exited (1) 5 hours ago' });
  ok(/\(running\)/.test(seeded) && !/partly up/.test(seeded) && /seed: finished/.test(seeded) && /partly up: 2 of 3/.test(broken),
     `a one-shot that exited 0 leaves the row running and reads finished, while one that failed still reads partly up (${
       (seeded.match(/\([^)]*\)/) || [''])[0]} | ${(broken.match(/partly up: \d of \d/) || [''])[0]})`);
}

await done(browser);
