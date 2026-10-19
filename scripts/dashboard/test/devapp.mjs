// The dev instance: a project's compose app, built and run through the host's
// daemon, controlled from the Docker tab in the file rows' own language.
//
// Everything here drives the stub docker the harness provides; the argv it
// records IS the assertion, because the module's whole safety story is that
// the buttons run table-lookup compose commands and nothing else.
import { launch, newPage, ok, done, ready, sleep, patience, holdPoll, freePoll, refreshUntil, saveDialog, URL, DIR, nbShown, nbTab, openFold, nbGo, faded } from './lib.mjs';
import { writeFileSync, readFileSync, rmSync, existsSync, mkdirSync, chmodSync, readdirSync } from 'node:fs';
import { execFileSync, spawnSync } from 'node:child_process';
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

// A compose job still queued or running, asked of the server: the job that
// will move a row, which a wait has to give its time to (B624).
const composeBusy = async () => {
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  try {
    const r = await (await fetch(URL.replace(/\/$/, '') + '/api/v1/jobs?active=1&type=compose', { headers: H })).json();
    return (r.jobs || []).length > 0;
  } catch { return false; }
};

const dockerLog = () => {
  try { return readFileSync(`${DIR}/dockerstate/docker.log`, 'utf8'); }
  catch { return ''; }
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
// The page's own asks of /api/devapp still on their way. A press on Up or
// Rebuild asks for the instance's state first (a compose parse on its node,
// seconds on a busy box) and only then for the action, so for that whole
// stretch no job exists yet, and a wait counted from the press spent its
// budget before the job had begun (B624, B829).
// Kept by the request rather than counted: an answer can land without a
// finished event (a reload cuts what was in flight), and a count that missed
// one stayed busy for good. A response is enough to say it landed.
const devAsks = new Set();
const isDevPost = r => r.method() === 'POST' && /\/api\/devapp(\?|$)/.test(r.url());
page.on('request', r => { if (isDevPost(r)) devAsks.add(r); });
page.on('response', x => devAsks.delete(x.request()));
for (const ev of ['requestfinished', 'requestfailed']) page.on(ev, r => devAsks.delete(r));
page.on('framenavigated', f => { if (f === page.mainFrame()) devAsks.clear(); });
// ...and settled: none of those asks in flight and no compose job queued or
// running, held for a second, since the state ask lands a moment before the
// action's is sent. Bounded, so a job that runs on past it is the caller's to
// judge.
async function settle(ms = 60000){
  const end = Date.now() + patience(ms);
  let quiet = 0, busy = false;
  while (quiet < 4 && Date.now() < end){
    busy = await composeBusy();
    quiet = devAsks.size || busy ? 0 : quiet + 1;
    await sleep(250);
  }
  if (quiet < 4) console.log(`[settle] still busy after ${ms}ms: devapp asks in flight ${
    JSON.stringify([...devAsks].map(r => (r.postData() || '').slice(0, 80)))}, compose job ${busy ? 'active' : 'none'}`);
}
// Asked of the page's own listing until it holds, the listing read again
// between looks: the tab redraws only when its revision moves, so a look
// sampled once read whichever answer happened to be last (B619, B829, B846).
// `fn` returns what it saw, or null to go on waiting; null back means it
// never held.
async function listingUntil(fn, arg, ms = 30000){
  const end = Date.now() + patience(ms);
  for (;;){
    const h = await page.waitForFunction(fn, arg, { timeout: 5000 }).catch(() => null);
    if (h) return h.jsonValue();
    if (Date.now() > end) return null;
    await page.evaluate(() => { loadDocker(); }).catch(() => {});
  }
}
await page.goto(URL);
await ready(page);
await page.evaluate(() => openNotebook('ep.silon'));
await page.waitForSelector('.pane .nb .nbtabs >> visible=true', { timeout: 20000 });
await nbGo(page, 'artifacts');
await page.waitForSelector('#devRow', { state: 'attached', timeout: 20000 });

// The controls live on the Docker manager now, and the artifact row only
// sends you there, so everything that presses one drives it from that tab.
const DM = '.dmtab .row[data-inst^="ep.silon|"]';
// Unconditional, because openTab focuses a tab that is already open and
// openDocker reloads the list either way. A guard on "is the row already
// there" broke the moment another tab took the pane: the row was absent, the
// guard did not re-open it, and the click waited for something never coming.
async function openManager(){
  // A row's settings dialog is modal, so none is left open behind a check
  // that presses something else on the page.
  await page.evaluate(() => {
    for (const d of dockerList?.instances || []) dmDropDrafts(`inst:${d.project}|${d.instance}`);
    for (const c of dockerList?.containers || []) dmDropDrafts(`ctr:${c.name || c.id}`);
    dmEditing.clear(); openDocker(); });
  await page.waitForSelector(DM, { timeout: 20000 });
}
async function dmClick(act){
  await openManager();
  // A button that stays dead is the shape of B477: say what the row showed
  // (its state line, the button's title, the row's own record), so the
  // next failure names whether it read running, busy or short of env.
  const b = `${DM} [data-dm="${act}"]`;
  const live = await page.waitForFunction(sel => { const e = document.querySelector(sel); return e && !e.disabled; },
                                          b, { timeout: 45000 }).then(() => true, () => false);
  if (!live){
    const seen = await page.evaluate(([sel, row]) => {
      const r = document.querySelector(row), e = document.querySelector(sel);
      const list = Array.isArray(dockerList) ? dockerList : (dockerList?.instances || dockerList?.rows || []);
      const d = list.find(x => x.project === 'ep.silon') || {};
      return { state: r?.querySelector('.state')?.textContent.trim(), title: saidOf(e),
               running: d.running, exists: d.exists, missing_env: d.missing_env, job: d.job };
    }, [b, DM]);
    throw new Error(`B477: ${act} stayed disabled 45s: ${JSON.stringify(seen).slice(0, 400)}\n`
      + dockerLog().split('\n').filter(l => /ep-silon /.test(l)).slice(-12).join('\n'));
  }
  await pressIn(b);
}
// A press on a bar's button, behind More when it is there (R210): the menu
// is opened first, as a thumb would.
async function pressIn(sel){
  // Pressed again when a redraw shuts it: a poll landing between the press
  // and the look drew the row again with its menu hidden, and one press
  // then waited out its budget in a loaded whole run (B713).
  for (let i = 0; i < 40; i++){
    const st = await page.$eval(sel, e => {
      const m = e.closest('.actmenu');
      if (!m || !m.hidden) return 'open';
      e.closest('.more').querySelector(':scope > button').click();
      return 'pressed';
    }).catch(() => 'missing');
    if (st === 'open') break;
    await sleep(150);
  }
  await page.click(sel);
}
async function dmDisabled(act){
  await openManager();
  // A button the row does not draw is as dead as a grayed one: a running
  // container wears no Up (the operator's concept, 17 Oct).
  return page.evaluate(sel => { const b = document.querySelector(sel); return !b || b.disabled; }, `${DM} [data-dm="${act}"]`);
}
// A row's settings read as pills until Edit settings, behind its ⋯, opens
// them in a dialog (the operator, 17 Oct): a check that works the fields
// opens the one row's it is about, as a person would; the dialog is modal,
// so openManager closes it before anything else on the page is pressed.
async function dmEditAll(sel = DM){
  await page.waitForFunction(sel => !!document.querySelector(sel), sel, { timeout: 20000 }).catch(() => {});
  await page.evaluate(sel => {
    const r = document.querySelector(sel);
    const key = r?.dataset.inst ? `inst:${r.dataset.inst}` : r?.dataset.ctr ? `ctr:${r.dataset.ctr}` : '';
    if (key) dmEditing.add(key);
    dockerRev++; drawPanes(); }, sel);
  await page.waitForFunction(() => document.querySelector('dialog.dmsetdlg')?.open, null, { timeout: 10000 }).catch(() => {});
}
async function dmEditNone(){
  // ...and what a check staged and left: a row with a draft keeps its dialog.
  await page.evaluate(() => {
    for (const d of dockerList?.instances || []) dmDropDrafts(`inst:${d.project}|${d.instance}`);
    for (const c of dockerList?.containers || []) dmDropDrafts(`ctr:${c.name || c.id}`);
    dmEditing.clear(); dockerRev++; drawPanes(); });
}
// The manager repaints from its own fetch, not the artifacts poll, so a test
// that acted through the API has to ask it to look again.
// Bring the artifact row's tab back in front. openManager leaves the manager
// there, and anything that CLICKS on the row needs it visible again; reading
// what the row rendered does not, which is why most assertions here wait on
// attachment instead.
async function showRow(){
  await page.evaluate(() => openNotebook('ep.silon'));
  await openDev();
  await page.waitForSelector('#devRow', { timeout: 20000 });
}
// The dev instance is a section of the Artifacts view now, and Files is the
// one open when the view shows (the operator, 6 Oct): opened before its row
// is pressed.
async function openDev(){
  await page.waitForSelector('#devRow', { state: 'attached', timeout: 20000 });
  const sel = await page.evaluate(() => { const d = document.getElementById('devRow')?.closest('details.sect');
    return d ? `[data-sect="${d.dataset.sect}"]` : ''; });
  if (sel) await openFold(page, `.nbview:not([hidden]) ${sel}`);
}
async function dmRefresh(){
  // Awaited: loadDocker returns when its answer has been drawn. The rows come
  // back at once from the last answer meanwhile (B125), and the stale mark
  // is no longer a tell, since it is only worn once a fetch has been slow.
  await page.evaluate(() => { dockerList = null; dockerRev++; return loadDocker(); });
  await openManager();
}
// The manager row's words, asked again until they match: a container's
// state is the Docker tab's alone since the Artifacts row stopped following
// it (the operator, 10 Oct), and that tab redraws from its own fetch.
async function dmTextUntil(re, timeout = 20000, not = false){
  const end = Date.now() + patience(timeout);
  let t = '';
  while (Date.now() < end){
    await dmRefresh();
    t = await page.$eval(DM, e => e.textContent.replace(/\s+/g, ' ')).catch(() => '');
    if (re.test(t) !== not) return t;
    // Every refresh is a listing job on the node, in the queue the compose
    // jobs wait in: asked every half second, it pushed their order about
    // and an Up landed after the test's Down (B477's shape).
    await sleep(2000);
  }
  throw new Error(`the manager row never ${not ? 'lost' : 'said'} ${re}: ${t.slice(0, 200)}`);
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

const row = async () => {
  const up = await dmDisabled('up'), down = await dmDisabled('down'), rebuild = await dmDisabled('rebuild');
  return { up, down, rebuild,
           text: await page.$eval(DM, e => e.textContent.replace(/\s+/g, ' ').trim()) };
};
// The state, read from the parenthetical beside the name and never out of the
// row's whole text: that text carries the buttons' own labels, so "down" in it
// could as easily be the Down button. The pill says what the row IS: docker,
// the way the file rows say apk or xpi. It never says what it is doing.
const pill = () => page.$eval(`${DM} .dmpill`, e => e.textContent.replace(/[()]/g, '').trim());
// Asked again every few seconds on the way, the way pressing Refresh would:
// a listing already on its way when the job ended lands after it and is the
// last word until something asks again (B246).
const pillIs = async (want) => {
  await openManager();
  // The budget runs from the last moment something that could still move
  // the pill was under way, not from the press: at a load of 20 on 8 cores
  // the Up's state ask and its job's wait in the queue took the whole of a
  // fixed 25s before the job had run (B624). Capped, so a pill that never
  // comes still fails.
  const cap = Date.now() + patience(150000);
  let t0 = Date.now();
  for (;;){
    try{
      const got = await page.waitForFunction(
        ([w, sel]) => document.querySelector(sel + ' .dmpill')?.textContent.replace(/[()]/g, '').trim() === w,
        [want, DM], { timeout: 5000 });
      // ...and the job that put it there ended: the pill is drawn before the
      // job has written its last, and a step pressed meanwhile was overtaken
      // by it (B477, at :782, :951 and :1014 by turns).
      await idle(30000);
      return got;
    }catch(e){
      if (devAsks.size || await composeBusy()) t0 = Date.now();
      if (Date.now() - t0 > 25000 || Date.now() > cap) throw e;
      await page.evaluate(() => { dockerList = null; loadDocker(); });
    }
  }
};

// The header names the daemon by its node when the node is an agent one:
// nothing dials the address on its record, so saying "at ssh://..." there
// described a path that was not taken (B264).
{
  await openManager();
  // Waited for: the header comes from the manager's own listing, which a
  // whole run can land after the rows the poll drew, or bring back as "the
  // daemon did not answer" once, and a read that did not wait crashed the
  // file at its first check (B334). Asked for again once if it has not come.
  await page.waitForFunction(() => !!dockerList?.src, null, { timeout: 20000 }).catch(async () => {
    await page.evaluate(() => { dockerList = null; loadDocker(); });
    await page.waitForFunction(() => !!dockerList?.src, null, { timeout: 20000 });
  });
  // Through its agent, the ordinary case, says nothing the picker has not
  // (R227 step 1), and never an address it does not dial.
  const src = await page.evaluate(() => ({ agent: !!dockerList.src.agent, line: document.querySelector('.dmtab .dmsrc')?.textContent.replace(/\s+/g, ' ').trim() || '' }));
  ok(src.agent && !/ at |ssh:/.test(src.line),
     `an agent node's daemon is named by the picker alone, never by an address it does not dial (${JSON.stringify(src).slice(0, 80)})`);
}

// The word at the foot is for a fetch that has been slow, not for every
// fetch: a listing reloads once per revision while a job runs, and a word
// that came and went with each one blinked through every build.
{
  await dmRefresh();
  // Per reload: whether the word came, and how long the fetch took. It is
  // right to show on one slower than DM_SLOW_MS, which a busy box makes,
  // so that is not counted against it; one that came on a quick fetch is
  // (B421: the check counted every showing and failed under load).
  const runs = await page.evaluate(async () => {
    const out = [];
    let said = false;
    const mo = new MutationObserver(() => { if (document.querySelector('.dmtab.dmstale')) said = true; });
    mo.observe(document.querySelector('.dmtab').parentElement, { childList: true, subtree: true });
    for (let i = 0; i < 4; i++){
      said = false;
      const t0 = performance.now();
      dockerList = null; dockerRev++; await loadDocker();
      out.push({ ms: Math.round(performance.now() - t0), said });
    }
    mo.disconnect();
    return { out, slow: DM_SLOW_MS };
  });
  const quickSaid = runs.out.filter(r => r.said && r.ms < runs.slow);
  ok(quickSaid.length === 0,
     `four quick reloads in a row never dim the rows on a fetch quicker than ${runs.slow} ms (${
       runs.out.map(r => `${r.ms}ms${r.said ? ' shown' : ''}`).join(', ')})`);
  const slow = await page.evaluate(async () => {
    const f = window.fetch;
    window.fetch = (...a) => String(a[0]).startsWith('/api/docker')
      ? new Promise(r => setTimeout(() => r(f(...a)), DM_SLOW_MS + 400)) : f(...a);
    const p = loadDocker();
    await new Promise(r => setTimeout(r, DM_SLOW_MS + 200));
    const during = { dim: !!document.querySelector('.dmtab.dmstale') };
    await p; window.fetch = f;
    // A revision reload that started under the slowed fetch is itself still
    // slowed and still in flight; the word it is entitled to is not this
    // test's. Wait for the tab to have nothing on its way.
    for (let i = 0; i < 40 && dockerFetching; i++) await new Promise(r => setTimeout(r, 100));
    return { ...during, after: !!document.querySelector('.dmtab.dmstale') };
  });
  ok(slow.dim && !slow.after,
     `...and one that is slow dims the rows until it lands (${JSON.stringify(slow)})`);
}

// A redraw must not take an open menu with it. The manager repaints on every
// step of a job, which made picking from one of its lists during a build a
// race against the next step. The hold is the page's, not this tab's, so this
// is also the test for every other tab: renderDoc is the one place any of
// them is drawn.
{
  await dmRefresh();
  const sel = await page.$('.dmtab select:not([disabled])');
  ok(!!sel, 'the manager has a menu to open');
  if (sel){
    await page.evaluate(() => { window.__heldSel = document.querySelector('.dmtab select:not([disabled])');
                                window.__heldTab = document.querySelector('.dmtab'); });
    await sel.click();
    const open = await page.evaluate(() => window.__heldSel.matches(':open'));
    await page.evaluate(() => { dockerRev++; drawPanes(); });
    const kept = await page.evaluate(() => ({
      same: window.__heldSel.isConnected && document.querySelector('.dmtab') === window.__heldTab,
      open: window.__heldSel.matches(':open') }));
    ok(open && kept.same && kept.open,
       `a redraw that lands while a menu is open leaves the menu alone (opened ${open}, same element ${kept.same}, still open ${kept.open})`);
    // ...and the revisions poll does not start one either.
    const polled = await page.evaluate(async () => {
      let asked = 0; const f = window.fetch;
      window.fetch = (...a) => { if (String(a[0]).startsWith('/api/revs')) asked++; return f(...a); };
      await pollRevs(); window.fetch = f; return asked; });
    ok(polled === 0, `...and the revisions poll waits rather than firing a watch under it (${polled} asked)`);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.querySelector('.dmtab') !== window.__heldTab,
                               null, { timeout: 5000 }).catch(() => {});
    const after = await page.evaluate(() => document.querySelector('.dmtab') !== window.__heldTab);
    ok(after, '...and the redraw it was owed happens once the menu shuts');
  }
}

let r = await row();
ok(await page.$eval('#devRow .top .pill', e => e.textContent.trim()) === 'docker'
   && await page.$eval('#devRow .top b', e => e.textContent.trim()) === 'docker-compose.yml'
   && !!await page.$('#devRow #devSend'),
   'a project with a compose file gets a row for it: kind on the pill, the file in bold, and Send');
// What the row does NOT say: anything about a container made from it. That
// is the Docker tab's, and the row that said "down" read as a second place
// to run it (the operator, 10 Oct): no state, no build, no Open, no ports.
{
  const t = await page.$eval('#devRow', e => e.textContent.replace(/\s+/g, ' '));
  ok(!/\b(down|running|stopped|built from|never built)\b/.test(t) && !await page.$('#devRow a.btn')
     && await page.$$eval('#devRow .grow > .dim.li:not(.warn)', els => els.length) === 0,
     `...and nothing about a container made from it: no state, no build, no Open (${t.slice(0, 80)})`);
}
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

// Edit opens the compose file and the env in one dialog (the operator,
// 9 Oct): the project's own compose file on one tab, the instance's env on
// the other, read once the dialog has them.
async function openEdit(){
  await dmClick('edit');
  await page.waitForSelector('#cmodal:not([hidden])');
  await page.waitForFunction(() => document.getElementById('cYml').value.length > 0
    && !document.getElementById('cEnvHint').hidden, null, { timeout: 15000 });
}
async function saveEdit(){
  await page.click('#cGo');
  await page.waitForSelector('#cmodal', { state: 'hidden', timeout: 15000 });
}
// Fill the env through the editor.
await openEdit();
ok(await page.$eval('#cYml', e => e.value) === readFileSync(`${D}/docker-compose.yml`, 'utf8')
   && await page.$eval('#cTabForm', e => e.hidden),
   'Edit opens on the project\'s own compose file, beside its env, with no form for an image');
// Its name is its own, not the project's (the operator, 11 Oct): live in
// the dialog while it is down, opening on what the row calls it, and the
// boxes and Save live with it.
ok(await page.evaluate(() => {
     const n = document.getElementById('cName'), row = (dockerList?.instances || []).find(d => d.instance === 'main' && d.source !== 'file' && !d.running);
     return !n.disabled && !!row && n.value === row.name && !document.getElementById('cGo').disabled
       && !document.getElementById('cEnv').readOnly && /Its name is its own/.test(document.getElementById('cNameHint').textContent);
   }), 'a project\'s container that is down offers its own name to change, with its boxes and Save live');
// ...and one that runs is for reading: Save ghosted, both boxes read-only
// and still scrollable (the operator, 11 Oct).
ok(await page.evaluate(() => {
     cLock(true);
     const ok = document.getElementById('cGo').disabled && document.getElementById('cYml').readOnly
       && document.getElementById('cEnv').readOnly && getComputedStyle(document.getElementById('cEnv')).overflowY !== 'hidden';
     cLock(false);
     return ok;
   }), '...while one that runs ghosts Save and makes both boxes read-only, still scrollable');
await page.click('#cTabEnv');
ok(/missing against \.env\.example: PORT/.test(await page.$eval('#cEnvHint', e => e.textContent)),
   'the env tab says which keys the example declares and this does not');
// An empty env opens on the example rather than on a blank box under a list
// of names the operator would have to type out.
const seeded = await page.$eval('#cEnv', e => e.value);
ok(/PORT=8080/.test(seeded) && /Started from this project/.test(seeded),
   '...and opens on the example, seeded, when nothing is stored yet');
ok(/nothing saved yet/.test(await page.$eval('#cEnvHint', e => e.textContent)),
   '...saying it is a draft, since a seeded box has not been written');
await page.fill('#cEnv', 'PORT=9090\n');
await saveEdit();
// Wait for the save to land: the hint stops calling it a draft.
await dmTextUntil(/fill in the env/, 20000, true).catch(() => {});
await page.waitForTimeout(1200);
// The buttons map to the compose commands, no rules of this dashboard's
// invention on top: `compose up` builds an image that is missing, so Up on a
// never-built project does what the CLI does rather than refusing. The
// classic builder rides along for exactly that case, since an implicit build
// through buildx would 403 against a socket proxy.
ok(!await page.$eval(`${DM} [data-dm="up"]`, b => b.disabled),
   'a filled env wakes Up: compose builds what is missing, so it would work');
ok(/builds the image first, as compose does/.test(
     await page.$eval(`${DM} [data-dm="up"]`, b => saidOf(b))),
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
// "running" is what the Docker row says once the build is up; "built from"
// is its word for a container that is not running.
await dmTextUntil(/running/, 30000);
const log = dockerLog();
ok(/compose --project-name ep-silon .*build/.test(log)
   && /compose --project-name ep-silon .*up -d/.test(log),
   'rebuild runs table-lookup compose commands, named for the instance');
// Waited for rather than read: the manager row draws from its own
// listing, a fetch behind the artifacts row's, and under a full run it
// had not caught up with the build the line above saw.
await page.waitForFunction(sel => document.querySelector(sel + ' [data-dm="rebuild"]')?.textContent.trim() === 'Rebuild',
                           DM, { timeout: 20000 });
ok(true, '...and the button says Rebuild once an image exists');
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
// Waited for, not read once: the manager's Up and Down follow its own
// listing, a fetch behind the artifacts row's, and under a whole run the
// row still read the state from before the up when this looked (B319).
await page.waitForFunction(sel => (document.querySelector(sel + ' [data-dm="up"]')?.disabled ?? true)
  && document.querySelector(sel + ' [data-dm="down"]')?.disabled === false, DM, { timeout: patience(20000) });
r = await row();
ok(!r.down && r.up, 'running: Down is live, Up is dead (not drawn)');
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
  await dmEditAll();
  await page.waitForFunction(sel => /http:\/\/stub:7475\//.test(
    document.querySelector(sel + ' .dmroute')?.textContent || ''), DM, { timeout: 20000 });
  const opts = await page.$$eval(`${DM} [data-route="mode"] option`, os => os.map(o => [o.value, o.disabled]));
  ok(opts.some(([v, d]) => v === 'lan' && !d) && opts.some(([v, d]) => v === 'funnel' && d)
     && opts.some(([v, d]) => v === 'public' && d),
     'the route picker offers lan, grays funnel without tailscale, and names public as unbuilt');
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

  // From a known baseline: the fixture binds ep.silon to the sandbox from
  // the start (R82: a project's containers live on its nodes, so there is
  // no "first node given" with something already built elsewhere), and the
  // record follows the project until a move pins it.
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
  // Put the fixture back, and in this order: a node change is itself a
  // pin, so the store is tidied after the last one, and the project ends on
  // the sandbox again, which is the fixture's baseline (R82).
  await setNode('ep.silon', '');
  {
    const d = JSON.parse(readFileSync(store, 'utf8'));
    delete d['ep.silon'].fresh;
    delete d['ep.silon'].main.node;
    writeFileSync(store, JSON.stringify(d));
  }
  await setNode('ep.silon', sandboxId);
  {
    const d = JSON.parse(readFileSync(store, 'utf8'));
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
await page.evaluate(() => openNotebook('ep.silon'));
await page.waitForSelector('.pane .nb .nbtabs >> visible=true', { timeout: 20000 });
await nbGo(page, 'artifacts');
await page.waitForSelector('#devRow', { state: 'attached', timeout: 20000 });
r = await row();
ok(!/built from/.test(r.text),
   'a record from another daemon does not read as built here');
ok(await page.$eval(`${DM} [data-dm="rebuild"]`, e => e.textContent.trim())
   === 'Build',
   '...so the button offers Build, which is what pressing it would do');
writeFileSync(devapps, JSON.stringify(wasBuilt));
await dmRefresh();
await page.waitForFunction(sel => document.querySelector(sel + ' [data-dm="rebuild"]')?.textContent.trim() === 'Rebuild',
                           DM, { timeout: patience(20000) });

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
// The row says what phase the job is in and offers Abort while it runs;
// the output itself is the Jobs tab's and the shell's, not a box on the row
// that redrew for every line of it.
writeFileSync(`${DIR}/dockerstate/build.slow`, '1');
// What the press asked and was answered, for the miss below (B684).
const asked = [], tA = Date.now();
const onResp = async r => {
  const u = r.url();
  const at = `${((Date.now() - tA) / 1000).toFixed(1)}s `;
  if (/\/api\/devapp/.test(u)) asked.push(at + `${r.status()} ${(await r.text().catch(() => '')).slice(0, 60)}`);
  else if (/\/api\/docker/.test(u)) asked.push(at + `docker: ${JSON.stringify((await r.json().catch(() => ({}))).job || null).slice(0, 160)}`);
  else if (/\/api\/revs/.test(u)){ const j = await r.json().catch(() => ({})); asked.push(at + `revs.devapp=${JSON.stringify(j.revs?.devapp ?? j.devapp)}`); }
};
page.on('response', onResp);
await dmClick('rebuild');
{
  // Sampled rather than waited for, so a miss says what the row said second
  // by second and what the jobs list held, not only its line (B684).
  const t0 = Date.now(), said = [];
  let seen = false;
  while (Date.now() - t0 < 40000){
    const s = await page.$eval(DM, r => `${r.querySelector('.state')?.textContent.trim()} [${
      [...r.querySelectorAll('[data-dm]')].map(b => `${b.dataset.dm}${b.disabled ? '(off)' : ''}`).join(' ')}]`).catch(() => '(no row)');
    // ...and what the daemon was asked meanwhile, by the second, so a build
    // that ignored its slow marker shows as down and up landing at once.
    const asked = dockerLog().split('\n').filter(l => /ep-silon /.test(l)).map(l => l.replace(/.* (config|build|up|down|ps|exec)\b.*/, '$1'));
    const line = `${s} daemon:${asked.length}:${asked.slice(-3).join(',')}`;
    if (!said.length || said[said.length - 1].slice(said[said.length - 1].indexOf(' ') + 1) !== line)
      said.push(`${((Date.now() - t0) / 1000).toFixed(1)}s ${line}`);
    if (/building|pulling|starting|working|queued/i.test(s)){ seen = true; break; }
    await page.waitForTimeout(250);
  }
  if (!seen){
    const toast = await page.$eval('#toast', e => e.textContent).catch(() => '');
    const jobs = await page.evaluate(async () => { const j = await (await fetch('/api/v1/jobs?project=ep.silon')).json();
      return JSON.stringify((j.jobs || []).slice(0, 4).map(x => ({ id: x.id, type: x.type, state: x.state, project: x.project, node: x.node,
        queued: x.queued, ended: x.ended, sp: `${x.spec?.project}/${x.spec?.instance}/${x.spec?.action}/hold=${x.spec?.hold}` }))); }).catch(e => String(e));

    throw new Error(`the row never said it was building; what it said: ${said.join(' | ')}; dialogs ${JSON.stringify(page.dialogs.slice(-2))}\n`
      + `asked: ${JSON.stringify(asked)}; toast: ${JSON.stringify(toast)}\njobs now: ${jobs}\n`
      + dockerLog().split('\n').filter(l => /ep-silon /.test(l)).slice(-6).join('\n'));
  }
  page.off('response', onResp);
}
ok(await page.$(`${DM} .dmlog`) === null, "the row carries the job's phase and no tail of its output");
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
await dmTextUntil(/fill in the env/, 30000);
// The pill as well as the text: the text lands with the record the job
// wrote, and on an agent node the pill comes from a listing read a moment
// later, so the two can arrive a fetch apart (B143).
await page.waitForFunction(sel => document.querySelector(sel + ' .dmpill')?.textContent.replace(/[()]/g, '').trim() === 'down',
                           DM, { timeout: 20000 }).catch(() => {});
ok(await pill() === 'down',
   'the gated rebuild stops after down rather than starting broken');
await openEdit();
await page.click('#cTabEnv');
const gated = await page.$eval('#cEnv', e => e.value);
ok(/API_KEY=/.test(gated) && /# old: PORT=9090/.test(gated),
   '...and the editor holds the new example with the old values in comments');
await page.fill('#cEnv', 'PORT=9090\nAPI_KEY=abc\n');
await saveEdit();
// ...and the compose half: a change compose reads is written into the
// project's own file, an uncommitted change there; one it refuses leaves the
// file as it was and says compose's words on the compose tab.
{
  const was = readFileSync(`${D}/docker-compose.yml`, 'utf8');
  await openEdit();
  await page.fill('#cYml', was + '# edited on the Containers page\n');
  await saveEdit();
  ok(readFileSync(`${D}/docker-compose.yml`, 'utf8') === was + '# edited on the Containers page\n',
     'a compose file saved from Edit is the project\'s own file, changed in its tree');
  writeFileSync(`${DIR}/dockerstate/config.fail`, '');
  await openEdit();
  await page.fill('#cYml', 'services: [nonsense\n');
  await page.click('#cGo');
  await page.waitForSelector('#cErrWrap:not([hidden])', { timeout: 15000 });
  const said = await page.$eval('#cErr', e => e.textContent);
  ok(/compose will not read that, so the file is as it was/.test(said) && /mapping values/.test(said)
     && readFileSync(`${D}/docker-compose.yml`, 'utf8') === was + '# edited on the Containers page\n'
     && await page.$eval('#cYmlField', e => !e.hidden),
     `...and one compose refuses is put back, its words on the compose tab (${said.slice(0, 80)})`);
  rmSync(`${DIR}/dockerstate/config.fail`, { force: true });
  // The refusal is the server's 400, which the browser logs: asked for here,
  // so it is no console error the dev row made.
  page.errors.splice(0, page.errors.length, ...page.errors.filter(e => !/400 \(Bad Request\) \[\/api\/devapp\]/.test(e)));
  await page.click('#cCancel').catch(() => page.evaluate(() => { document.getElementById('cmodal').hidden = true; }));
  writeFileSync(`${D}/docker-compose.yml`, was);
}
await dmRefresh();
await page.waitForFunction((SEL) => {
  const b = document.querySelector(SEL + ' [data-dm="up"]');
  return b && !b.disabled;
}, DM, { timeout: 20000 });
await dmClick('up');
await dmTextUntil(/running/);
// ...and its job's end, as for a rebuild below (B477): "running" is drawn
// before the job has written its last.
await idle(60000);
ok(true, '...and Up is manual after the gate, exactly as asked');

// Start on boot on an instance's row reads the instance's own containers
// (R122): the listing's top-level containers are the ones that belong to no
// instance, and the switch read those, so it said off whatever docker said
// (found walking the dev instance, 5 Oct).
{
  await page.evaluate(() => openDocker());
  await dmEditAll();
  await page.waitForSelector(`${DM} [data-dmboot]`, { timeout: 20000 }).catch(() => {});
  // ...and the listing itself, which a refresh empties until its answer
  // lands: read in that gap it held no instance at all.
  await page.waitForFunction(() => (dockerList?.instances || []).some(x => x.exists), null,
                             { timeout: patience(20000) }).catch(() => {});
  const drawn = await page.evaluate(sel => {
    const d = (dockerList?.instances || []).find(x => x.exists);
    if (!d) return null;
    d.boot = true; dockerRev++; drawPanes();
    const on = document.querySelector(`.dmtab [data-dmboot="${CSS.escape(d.name)}"]`)?.checked;
    d.boot = false; dockerRev++; drawPanes();
    const off = document.querySelector(`.dmtab [data-dmboot="${CSS.escape(d.name)}"]`)?.checked;
    return { on, off, server: 'boot' in d };
  }, DM);
  ok(drawn && drawn.on === true && drawn.off === false && drawn.server,
     `an instance's Start on boot reads its own row's boot, which the listing carries (${JSON.stringify(drawn)})`);
}


// Down, from the row.
await dmClick('down');
await pillIs('down');
ok(/compose --project-name ep-silon .*down --remove-orphans/.test(dockerLog())
   && /compose --project-name ep-silon .*up -d --remove-orphans/.test(dockerLog()),
   'Down runs compose down, nothing else, and up and down both take the services the file no longer names with them (B592)');
ok((await row()).down, '...and goes dead after it: there is nothing left to remove');

// A container that EXITED still exists: it holds its name and the project's
// network, and `down` is the only thing that clears it. Asking compose only
// about RUNNING containers left a crashed instance with a grayed-out Down and
// no way out except a shell, which is the one thing these buttons are for.
writeFileSync(`${DIR}/dockerstate/ep-silon.exited`, '1');
await page.evaluate(() => refresh());
// Read again, as the steps around this one do: the marker is the daemon's
// state and moves no revision, and a listing already on its way when it was
// written would otherwise be the last word (opening the tab does not ask
// again while one is in flight).
await dmRefresh();
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
// The job first, then the row: the reason reaches the row only once the
// job has released, and a flat wait on the row ran out under load while
// the job was still running (B340). Settled rather than idle: the press asks
// for the state before it asks for the Up, so the queue was still empty when
// idle first looked and it returned at once, and the row was then read
// before the job had failed, or off a listing drawn before it did (B829).
await settle(90000);
await idle(60000);
const failed = await listingUntil(() => /up failed/.test(dockerList?.job?.error || '') ? dockerList.job : null,
                                  undefined, 30000)
  || await page.evaluate(() => dockerList?.job || {});
ok(/up failed/.test(failed.error || ''),
   'an Up that fails leaves the reason on the row, not only in the reply');
ok(!failed.running && !('log' in failed),
   '...and the payload carries no log: the reason is the row\'s, the output is the Jobs page\'s');
await idle();
await openManager();
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
   'a failed job is summarized by its reason, not by the label above it');
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
const cut = await dmTextUntil(/a build was interrupted/);
ok(/still on [0-9a-f]{7}/.test(cut),
   'an interrupted build says so on its Docker row, and still names the last one that finished');
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
await dmTextUntil(/a build was interrupted/, 30000, true);
// The line goes as the rebuild STARTS, not as it ends: its build, down and up
// went on behind the next steps, and its up landed after their Down, which
// was B477 (Up dead at :951, the pill never down at :906). Its end is waited
// for here, where it was pressed.
await idle(90000);
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
const blew = await dmTextUntil(/stub build exploded/, 30000);
await idle(60000);
ok(/stub build exploded/.test(blew),
   'a failed build shows its own last words on its Docker row, and nothing was started');
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
// build that never succeeded never reached the down-and-up. Asked of the
// server, not read off the pill: a listing drawn as the failed job ended
// could still say down, Down was skipped, and Up below stayed dead (B477).
const live0 = await page.evaluate(async () => (await (await fetch('/api/devapp', { method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ project: 'ep.silon', action: 'state' }) })).json()).state || {});
if (live0.running || live0.exists || await pill() !== 'down') {
  await dmClick('down');
  await pillIs('down');
}
// A path of OURS handed to the node's daemon: it resolves bind-mount sources
// on its own filesystem, and the node holds the project there as its synced
// copy at the same path (R163), so a bind into the project is one it has and
// the row says nothing against it. Where the daemon lacks the path (a node
// taken off its copy), docker answers by creating an empty directory, which
// the unit tier holds problems() to naming (test_devapp_synced).
writeFileSync(stubCfg, JSON.stringify(
  { services: { app: { build: { context: '.' }, volumes: ['./data:/data'] } } }));
await nudge();
await sleep(1500);
const probs = await devLines("bad");
ok(probs.length === 0 && !/will not work as written/.test(await page.$eval('#devRow', r => r.textContent)),
   `a bind into the project is one the node's synced copy has, so nothing is said against it (${probs.join(' | ').slice(0, 80)})`);

// A compose that reserves the NVIDIA GPU on a node that cannot hand it to a
// container (R102): Docker's own answer is "could not select device driver
// nvidia", after the build. Said on the row as a compose that cannot start
// as written, with the reason, and a rebuild asked anyway is refused by its
// job in the same words.
{
  writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
    deploy: { resources: { reservations: { devices: [{ driver: 'nvidia', count: 1, capabilities: ['gpu'] }] } } } } } }));
  await nudge();
  await page.waitForFunction(() => /reserves the NVIDIA GPU/.test(
    document.querySelector('#devRow')?.textContent || ''), { timeout: 20000 });
  const held = await devLines("bad");
  ok(held.length === 1 && /^app reserves the NVIDIA GPU in the compose file, and .*NVIDIA card/.test(held[0]),
     `a compose that reserves the GPU where the node cannot give it is named on the row, with why (${(held[0] || '').slice(0, 110)})`);
  const r = await page.evaluate(async () => (await (await fetch('/api/devapp', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'ep.silon', action: 'rebuild', ack: '' }) })).json()));
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  let job = null;
  for (let i = 0; i < 60 && r.job && !(job && ['failed', 'succeeded', 'canceled'].includes(job.state)); i++){
    await sleep(500);
    job = await (await fetch(URL.replace(/\/$/, '') + '/api/v1/jobs?id=' + r.job, { headers: H })).json();
  }
  ok(job?.state === 'failed' && /reserves the NVIDIA GPU/.test(job.error || ''),
     `...and a rebuild asked anyway is refused by its job, in the same words (${r.error || job?.state}: ${String(job?.error).slice(0, 60)})`);
}

risky(['/:/host']);
await nudge();
await page.waitForFunction(() => /asks for more than its own directory/.test(
  document.querySelector('#devRow')?.textContent || ''), { timeout: 20000 });
ok(true, 'a compose reaching past its own directory says so on the row');
const risked = await devLines("risk");
ok(risked.length === 2 && /runs privileged/.test(risked[0]) && /mounts \/ of the host: the node's own system/.test(risked[1]),
   `...one line each: the flag, and the mount that reaches outside the project, which is root on the node for the asking (${risked.join(' | ').slice(0, 100)})`);

let seen = page.dialogs.length;
await dmClick('up');
await pillIs('running');
ok(page.dialogs.slice(seen).some(d => /runs privileged/.test(d)),
   '...and Up asks first, naming what it found rather than warning in general');
// The gate's compose parse runs on the instance's node, up to 30s away, and
// a request that waited on it was dropped by a phone as a NetworkError with
// no reason (B260). So the request answers with the job at once, and a
// refusal is the job's failure, on the row. A mount the acknowledgement did
// not cover is a fresh refusal.
{
  writeFileSync(stubCfg, JSON.stringify({ services: { app: {
    build: { context: '.' }, privileged: true, pid: 'host', volumes: ['/:/host'] } } }));
  const t0 = Date.now();
  const r = await page.evaluate(async () => (await (await fetch('/api/devapp', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'ep.silon', action: 'rebuild', ack: '' }) })).json()));
  ok(r.ok && r.job && Date.now() - t0 < 5000,
     `a rebuild answers with its job before the gate has read the compose (${r.job || r.error})`);
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  let job = null;
  for (let i = 0; i < 60 && !(job && ['failed', 'succeeded', 'canceled'].includes(job.state)); i++){
    await sleep(500);
    job = await (await fetch(URL.replace(/\/$/, '') + '/api/v1/jobs?id=' + r.job, { headers: H })).json();
  }
  ok(job?.state === 'failed' && /asks for more than its own directory/.test(job.error || ''),
     `...and the gate's refusal is the job's failure, with its words (${job?.state}: ${String(job?.error).slice(0, 60)})`);
  risky(['/:/host']);
  await nudge();
}
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

# The sandbox VM's daemon, and a store with a default and a named instance,
# as what follows reads them.
calls.clear()
sethost('ssh://bb@vm')
m._load = lambda: {'beta': {'main': {}, 'staging': {}}}
calls.clear()

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
// being refused: the one-at-a-time is per instance, the queue serializes the
// node. Driven at the module with a stub queue, because the race is between
// two requests and a browser cannot hold one open on purpose.
const slot = execFileSync('python3', ['-c', `
import importlib.util, json, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# The action layer is devactions.py (25 Sep): loaded by path too, with this
# devapp registered as the one it imports, so the stubs above and below land.
import sys; sys.modules['devapp'] = m
spec = importlib.util.spec_from_file_location('devactions', ${
  JSON.stringify(new globalThis.URL('../devactions.py', import.meta.url).pathname)})
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
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
    # What _submit's prepare thread calls once the gate has run (B260): the
    # plan lands on the row, or the refusal fails it.
    def job_release(self, jid, spec):
        for r in self.rows:
            if r['id'] == jid and r['state'] == 'queued':
                r['spec'] = spec
                return True
        return False
    def job_refuse(self, jid, why):
        for r in self.rows:
            if r['id'] == jid and r['state'] == 'queued':
                r['state'] = 'failed'; r['error'] = why
q = Queue()
m.configure(workspace='/tmp', state=d, write_json=lambda p, o: None, queue=q)
m._risk_gate = lambda *a, **k: ''
m.missing_env = lambda *a, **k: []
m.compose_file = lambda *a, **k: '/tmp/x.yml'
m._load = lambda: {'alpha': {'main': {}, 'staging': {}}}
m._instance_node = lambda *a: 'n_sandbox'

out = {}
out['first_up'] = a.up('alpha', 'main')
out['second_up'] = a.up('alpha', 'main')
out['rebuild_during_up'] = a.rebuild('alpha', 'main')
out['down_during_up'] = a.down('alpha', 'main')
out['other_instance'] = a.up('alpha', 'staging')
out['queued'] = [(r['id'], r['spec']['action'], r['spec']['instance'], r['node'], r['principal']) for r in q.rows]
out['view'] = m.job_view('alpha', 'main')
q.rows[-1]['state'] = 'succeeded'
out['free_now'] = a.up('alpha', 'main')
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
# The action layer is devactions.py (25 Sep): loaded by path too, with this
# devapp registered as the one it imports, so the stubs above and below land.
import sys; sys.modules['devapp'] = m
spec = importlib.util.spec_from_file_location('devactions', ${
  JSON.stringify(new globalThis.URL('../devactions.py', import.meta.url).pathname)})
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
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

r = a._job_rebuild('alpha', 'main', run)
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
# The action layer is devactions.py (25 Sep): loaded by path too, with this
# devapp registered as the one it imports, so the stubs above and below land.
import sys; sys.modules['devapp'] = m
spec = importlib.util.spec_from_file_location('devactions', ${
  JSON.stringify(new globalThis.URL('../devactions.py', import.meta.url).pathname)})
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)

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
a._job_up('p', 'main', Run())
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
// ...and waited for the key itself, not for any answer: under a full run
// the answer on screen can be one refetched before the job was told of,
// and sampling it there failed one full run in three (25 Sep).
const toldJob = await page.waitForFunction(() => dockerList && typeof dockerList.job !== "undefined", null, { timeout: 15000 })
  .then(() => true, () => false);
ok(toldJob, 'the manager is told about the running job with the rest of its page');

// The wiring fold: what the container publishes and what it mounts, fetched
// when it is opened and not before: parsing the compose file is the one thing
// the manager's page deliberately does not do for every row at once.
await openManager();
ok(await page.$eval(`${DM} .sect .wire`, e => /reading/.test(e.textContent)),
   'the wiring fold says nothing until it is opened');
await page.click(`${DM} .sect > summary`);
// 20s like its neighbors, not 15. The fold fetches, and this is the one
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

// A stack of more than one container says whose each port is (B252, the
// operator, 24 Sep: "it shows all the ports but I can't see which containers
// they belong to"): the wiring grouped under each service, the ports line
// under Details naming them, and the route's port picker too.
{
  const ST = `${DIR}/dockerstate`;
  const wasUp = existsSync(`${ST}/ep-silon.up`);
  writeFileSync(`${ST}/ep-silon.up`, '');
  writeFileSync(`${ST}/ep-silon.svcs`, 'app 7475 7474\ngitea 3000 3000\ngitea 2222 22\n');
  writeFileSync(`${ST}/ep-silon.config`, JSON.stringify({ services: {
    app: { build: { context: '.' }, ports: [{ target: 7474, published: '7475', protocol: 'tcp' }],
           volumes: [{ type: 'bind', source: '/mnt/user/appdata/x/config', target: '/config' }] },
    gitea: { build: { context: '.' }, ports: [{ target: 3000, published: '3000', protocol: 'tcp' },
                                             { target: 22, published: '2222', protocol: 'tcp' }] } } }));
  await dmRefresh();
  // It loads on opening, so a fold the page kept open is shut first.
  if (await page.$eval(`${DM} details.sect`, d => d.open)) {
    await page.click(`${DM} .sect > summary`);
    await page.waitForFunction(sel => !document.querySelector(sel + ' details.sect').open, DM, { timeout: 10000 });
  }
  await page.click(`${DM} .sect > summary`);
  await page.waitForFunction(sel => document.querySelectorAll(sel + ' .sect .wire .wgrp').length === 2, DM,
                             { timeout: 20000 });
  const groups = await page.$$eval(`${DM} .sect .wire .wgrp`, gs => gs.map(g => ({
    name: g.querySelector('.wsvc')?.textContent,
    ports: [...g.querySelectorAll('.wport')].map(e => e.textContent.replace(/\s+/g, ' ').trim()),
    mounts: g.querySelectorAll('.wmount').length })));
  ok(groups[0].name === 'app' && groups[0].ports.length === 1 && /7474.*7475/.test(groups[0].ports[0])
     && groups[0].mounts === 1 && groups[1].name === 'gitea' && groups[1].ports.length === 2 && groups[1].mounts === 0,
     `a stack's Ports and mounts are grouped under each service (${JSON.stringify(groups)})`);
  // ...and the fold stays read across a redraw (B827): the stats and every
  // job step redraw the list, and an open fold came back as its shapes.
  await page.evaluate(() => { dockerRev++; drawPanes(); });
  ok(await page.waitForFunction(sel => document.querySelectorAll(sel + ' .sect .wire .wgrp').length === 2, DM, { timeout: 15000 })
       .then(() => true, () => false),
     '...and an open Ports and mounts keeps its lines when the list redraws');
  // Its services a table in the card (the operator's concept, 17 Oct): each
  // its own line, its ports in their column.
  const svcs = await page.$$eval(`${DM} .dmsvctbl .tline`, ls => ls.map(l => ({
    name: l.querySelector('.td.lead .name')?.textContent.trim(), ports: l.querySelector('[data-th="Ports"]')?.textContent.replace(/\s+/g, ' ').trim() })));
  ok(svcs.some(x => x.name === 'app' && /7475 → 7474/.test(x.ports)) && svcs.some(x => x.name === 'gitea' && /3000 → 3000/.test(x.ports) && /2222 → 22/.test(x.ports)),
     `...the services table names whose each port is (${JSON.stringify(svcs)})`);
  await dmEditAll();
  const opts = await page.$$eval(`${DM} select[data-route="port"] option`, os => os.map(o => o.textContent));
  ok(opts.includes(':3000 gitea') && opts.includes(':2222 gitea') && opts.includes(':7475 app'),
     `...and so does the route's port picker (${opts.join(' ')})`);
  rmSync(`${ST}/ep-silon.svcs`, { force: true });
  rmSync(`${ST}/ep-silon.config`, { force: true });
  if (!wasUp) rmSync(`${ST}/ep-silon.up`, { force: true });
  await dmRefresh();
}

// ---- a shell inside a container, in the dock (R218 step 4) -------------------
// The row of a running instance carries Shell for its first running container
// and Shell in SERVICE for the rest under More; a press opens a terminal tab in
// the dock whose argument names the container. The proxy checks the account,
// the instance and the container against its daemon before relaying: here,
// where the harness runs no terminal server, a terminal it lets through meets "not
// answering on the node" and one it refuses meets the reason.
{
  const ST = `${DIR}/dockerstate`;
  const wasUp = existsSync(`${ST}/ep-silon.up`);
  writeFileSync(`${ST}/ep-silon.up`, '');
  writeFileSync(`${ST}/ep-silon.svcs`, 'app 7475 7474\ngitea 3000 3000\n');
  await dmRefresh();
  await page.waitForSelector(`${DM} [data-dmshell]`, { timeout: 15000 });
  const offered = await page.evaluate(sel => [...document.querySelectorAll(sel + ' [data-dmshell]')]
    .map(b => ({ ctr: b.dataset.dmshell, text: b.textContent.trim(), dead: b.disabled })), DM);
  ok(offered.length === 2 && offered[0].text === 'Shell' && !offered[0].dead && /^Shell in gitea$/.test(offered[1].text),
     `a running instance offers Shell for its first container and Shell in the rest under More (${JSON.stringify(offered)})`);
  const term = async arg => page.evaluate(async a => {
    const r = await fetch('/term/?arg=' + encodeURIComponent(a), { headers: { Accept: 'application/json' } });
    return { status: r.status, error: (await r.json().catch(() => ({}))).error || '' };
  }, arg);
  const good = await term(`ctr:ep.silon:main:${offered[0].ctr}`);
  // ep.silon's instance is on the stub node: through the gate, the proxy
  // relays to that node's container terminal (the agent's third ttyd, as
  // the docker account), which the harness does not run.
  ok(good.status === 502 && /^sandbox did not answer on stub:7683/.test(good.error),
     `the proxy lets a running container of the instance through, to its node's terminal server (${good.status} ${good.error.slice(0, 60)})`);
  // A node whose terminals still run the scripts from before this
  // controller's update (B746): its bb-tty would not know the argument, so
  // the proxy says so, and asks it to check in, rather than relaying.
  {
    const extra = `${DIR}/sandboxdata/census-extra.json`;
    writeFileSync(extra, JSON.stringify({ session: { bundle: 'from-before-the-update' } }));
    let old = null;
    for (const t0 = Date.now(); Date.now() - t0 < 20000; await sleep(500)){
      old = await term(`ctr:ep.silon:main:${offered[0].ctr}`);
      if (old.status === 403) break;
    }
    rmSync(extra, { force: true });
    ok(old?.status === 403 && /has not taken this controller's update yet/.test(old.error),
       `a node still on the scripts from before an update is said plainly, not relayed (${old?.status} ${(old?.error || '').slice(0, 70)})`);
    for (const t0 = Date.now(); Date.now() - t0 < 20000; await sleep(500))
      if ((await term(`ctr:ep.silon:main:${offered[0].ctr}`)).status === 502) break;
  }
  // ...and an agent from before the container terminal says what to do.
  {
    const extra = `${DIR}/sandboxdata/census-extra.json`;
    writeFileSync(extra, JSON.stringify({ session: { ctr_port: 0 } }));
    let old = null;
    for (const t0 = Date.now(); Date.now() - t0 < 20000; await sleep(500)){
      old = await term(`ctr:ep.silon:main:${offered[0].ctr}`);
      if (old.status === 403) break;
    }
    rmSync(extra, { force: true });
    ok(old?.status === 403 && /agent is from before a container's shell: Update agent on its row/.test(old.error),
       `a node whose agent runs no container terminal says to update it (${(old?.error || '').slice(0, 80)})`);
    for (const t0 = Date.now(); Date.now() - t0 < 20000; await sleep(500))
      if ((await term(`ctr:ep.silon:main:${offered[0].ctr}`)).status === 502) break;
  }
  const wrong = await term('ctr:ep.silon:main:someone-elses');
  ok(wrong.status === 403 && /someone-elses is not a running container of ep-silon/.test(wrong.error),
     `...and refuses a container that is not one of the instance's (${wrong.error})`);
  const noInst = await term(`ctr:ep.silon:nope:${offered[0].ctr}`);
  ok(noInst.status === 403 && /no instance nope of ep\.silon/.test(noInst.error),
     `...an instance that is not on record (${noInst.error})`);
  const shape = await term('ctr:ep.silon:main:-x');
  ok(shape.status === 403 && /not a container's terminal/.test(shape.error),
     `...and an argument in any other shape (${shape.error})`);
  // On a node, bb-tty asks the controller with the token the proxy minted
  // for the container's project, and execs into what the answer names, not
  // what the URL says: the same questions, asked of the token's account.
  {
    const { fileURLToPath } = await import('node:url');
    const REPO = fileURLToPath(new globalThis.URL('../../../', import.meta.url));
    const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'ep.silon', 'test'],
      { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
    const grant = async arg => {
      const r = await fetch(URL.replace(/\/$/, '') + '/api/v1/tty-grant', { method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok }, body: JSON.stringify({ arg }) });
      return { status: r.status, ...(await r.json().catch(() => ({}))) };
    };
    const g = await grant(`ctr:ep.silon:main:${offered[0].ctr}`);
    ok(g.status === 200 && g.ctr === offered[0].ctr && g.project === 'ep.silon',
       `a node's grant for a container's terminal names the container, checked (${g.status} ${g.ctr || g.error})`);
    const gx = await grant('ctr:ep.silon:main:someone-elses');
    ok(gx.status === 403 && /someone-elses is not a running container/.test(gx.error || '') && !gx.ctr,
       `...and refuses one that is not the instance's, naming no container (${gx.error})`);
  }
  // The press: a terminal tab in the dock, named by its container.
  await page.click(`${DM} [data-dmshell="${offered[0].ctr}"]`);
  await page.waitForFunction(c => tabOf(panes[1])?.arg === `ctr:ep.silon:main:${c}` && dockUp, offered[0].ctr, { timeout: 10000 });
  ok(await page.evaluate(c => sessionOf(tabOf(panes[1]).arg) === myTmux(tmuxName('ctr-' + c))
       && /^in /.test(tabLabel(tabOf(panes[1]))), offered[0].ctr),
     'Shell opens a terminal tab in the dock, its session and its label named by the container');
  // Put away, and the dock down again: up, it takes the page's room, and the
  // blocks below this one read the Docker page's own controls.
  await page.evaluate(() => { hideTab(panes[1]); dockToggle(false); });
  // Why it is dead, said under the row: a hosting-only node runs no
  // terminal, and a project whose Run its container is Deny keeps its
  // containers' shells to an administrator.
  const why = await page.evaluate(() => {
    const keepN = nodesList, keepL = dockerList, keepA = state.admin;
    nodesList = [{ id: 'n_host', name: 'draconis', config: { host_only: true } }];
    dockerList = { ...(dockerList || {}), node: 'n_host' };
    const host = dmShellWhy({ project: 'ep.silon', instance: 'main' });
    nodesList = keepN; dockerList = keepL;
    const p = state.projects.find(x => x.name === 'ep.silon'), keepB = p.prefs?.devbuild;
    p.prefs = { ...(p.prefs || {}), devbuild: 'deny' }; state.admin = false;
    const deny = dmShellWhy({ project: 'ep.silon', instance: 'main' });
    state.admin = true; const admin = dmShellWhy({ project: 'ep.silon', instance: 'main' });
    p.prefs.devbuild = keepB; state.admin = keepA;
    return { host, deny, admin };
  });
  ok(/draconis hosts containers only/.test(why.host) && /Run its container is Deny/.test(why.deny) && why.admin === '',
     `a dead Shell says why: a hosting-only node, or Deny for anybody but an administrator (${JSON.stringify(why)})`);
  rmSync(`${ST}/ep-silon.svcs`, { force: true });
  if (!wasUp) rmSync(`${ST}/ep-silon.up`, { force: true });
  await dmRefresh();
}

// Where the row's state sits, asserted by geometry rather than by a
// screenshot (the operator's concept, 17 Oct): in the card's head, by the
// name, and the verbs at the head's right on the same line at a desk, so the
// card spends no line on a bar of its own.
const laid = await page.evaluate(() => {
  const head = document.querySelector('.dmtab .row.stack2 .dmhead');
  const st = head?.querySelector('.state'), bar = head?.querySelector('.actbar');
  if (!head || !st || !bar) return { err: 'no head' };
  const r = e => e.getBoundingClientRect();
  return { grid: getComputedStyle(document.querySelector('.dmtab .row.stack2 .grow')).display,
           beside: r(bar).top < r(st).bottom && r(bar).left >= r(st).right - 1 };
});
ok(!laid.err && laid.beside,
   `...and the row's state is in its head by the name, its verbs beside it on the same line (${
     JSON.stringify(laid)})`);
ok(laid.grid === 'grid',
   "...with the card's parts in its grid");

// ---- what a project's sessions on one node may reach on its others (R82) --
// session_net_own(node) names, per project that can have a session there,
// the published ports of its containers on the project's other Linux nodes
// and the whole address of a Mac, Windows or guest node of the project;
// never a node outside the project's set, never another project's. Driven
// in process with the records and the nodes stubbed, since the harness has
// one node.
{
  const sn = execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('d', ${JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
NODES = {'n1': {'agent': {'addr': '192.168.1.16'}, 'reported': {'sandbox': True, 'published': {'alpha-aux': [9000]}}},
         'n2': {'agent': {'addr': '192.168.1.17'}, 'reported': {'sandbox': True, 'published': {'alpha': [8088, 8443], 'plex': [32400], 'other': [1234]}}},
         'n3': {'agent': {'addr': '192.168.1.40'}, 'reported': {'sandbox': False, 'published': {}}},
         'n4': {'agent': {'addr': '192.168.1.99'}, 'reported': {'sandbox': True, 'published': {'gamma': [5000]}}}}
class Q:
    def node(self, nid): return NODES.get(nid)
m.queue = Q()
m.project_node = lambda p: {'alpha': 'n1', 'beta': 'n1', 'gamma': 'n4'}.get(p, '')
m.project_nodes = lambda p: {'alpha': ['n1', 'n2', 'n3'], 'beta': ['n1'], 'gamma': ['n4']}.get(p, [])
m.all_project_nodes = lambda: {'alpha': ['n1', 'n2', 'n3'], 'beta': ['n1'], 'gamma': ['n4']}
m._load = lambda: {'alpha': {'main': {'node': 'n2'}, 'aux': {}}, 'beta': {'main': {}}, 'gamma': {'main': {}}}
m._owners = lambda: {'n2': {'plex': 'alpha', 'other': 'beta'}}
print(json.dumps(m.session_net_own('n1')))
# ...and with alpha reading beta and gamma (prefs.reads): beta's instance
# here and its container on alpha's other node join alpha's set; gamma's
# node is not alpha's, so gamma stays out.
m.reads_of = lambda p: {'alpha': ['beta', 'gamma']}.get(p, [])
print(json.dumps(m.session_net_own('n1')))
# ...and what a project's settings let its sessions reach besides (Also
# reaches, the operator, 7 Oct): a whole machine, or one port on one.
m.reads_of = None
m.reaches_of = lambda p, nid: {('beta', 'n1'): ['192.168.1.50', '192.168.1.60:8123']}.get((p, nid), [])
print(json.dumps(m.session_net_own('n1')))
`], { encoding: 'utf8' });
  const [own, withReads, withReach] = sn.trim().split('\n').slice(-3).map(l => JSON.parse(l));
  const same = (a, b) => JSON.stringify(Object.keys(a).sort().map(k => [k, a[k]])) === JSON.stringify(Object.keys(b).sort().map(k => [k, b[k]]));
  ok(same(own.alpha, { compose: ['aux'], hosts: ['192.168.1.40'], names: [],
       peers: [['192.168.1.17', 8088], ['192.168.1.17', 8443], ['192.168.1.17', 32400]] }),
     `a project's sessions on one node reach its containers' published ports on its other node and its Mac whole (${JSON.stringify(own.alpha)})`);
  ok(same(withReads.alpha, { compose: ['aux', 'beta'], hosts: ['192.168.1.40'], names: [],
       peers: [['192.168.1.17', 1234], ['192.168.1.17', 8088], ['192.168.1.17', 8443], ['192.168.1.17', 32400]] })
     && same(withReads.beta, own.beta),
     `a project that reads others reaches their containers here and on its own other nodes, never on a node it is not on, and the read project's own set is unchanged (${JSON.stringify(withReads.alpha)})`);
  ok(same(withReach.beta, { compose: ['beta'], hosts: ['192.168.1.50'], names: [], peers: [['192.168.1.60', 8123]] })
     && same(withReach.alpha, own.alpha),
     `Also reaches gives a project's sessions a whole machine or one port on one, and nobody else's (${JSON.stringify(withReach.beta)})`);
  ok(same(own.beta, { compose: ['beta'], hosts: [], names: [], peers: [] }) && !own.gamma,
     `...a project on this node alone reaches nothing else, and one not on this node is not named at all (${JSON.stringify(own.beta)}; gamma ${JSON.stringify(own.gamma)})`);
}

// ---- a refused new leaves nothing behind -----------------------------------
// The env is written after the record is made, so an env the write refuses
// (over 64KB here) left the instance registered, and the retry that fixed
// the env was told it already existed (B259).
{
  const base = URL.replace(/\/$/, '');
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
              'Content-Type': 'application/json' };
  const post = async (body) => (await fetch(base + '/api/devapp',
    { method: 'POST', headers: H, body: JSON.stringify(body) })).json();
  // The env directory made unwritable for one request: the write fails the
  // way a full or read-only state disk would.
  const envDir = `${DIR}/state/devenv`;
  mkdirSync(envDir, { recursive: true });
  chmodSync(envDir, 0o500);
  const big = await post({ project: 'ep.silon', action: 'new', instance: 'halfmade', text: 'X=1' });
  chmodSync(envDir, 0o700);
  ok(/could not write the env file/.test(big.error || ''), `a new with an env the write refuses is refused (${String(big.error).slice(0, 40)})`);
  const retry = await post({ project: 'ep.silon', action: 'new', instance: 'halfmade', text: 'X=1' });
  ok(retry.ok && retry.instance === 'halfmade',
     `...and the retry with a good env is a new instance, not "already exists" (${retry.error || retry.instance})`);
  const bad = await post({ project: 'ep.silon', action: 'new', instance: 'halfmade-two', ref: 'no-such-branch-here' });
  ok(!!bad.error, `a new whose ref is refused is refused (${String(bad.error).slice(0, 50)})`);
  const again = await post({ project: 'ep.silon', action: 'new', instance: 'halfmade-two' });
  ok(again.ok, `...and leaves no record for the retry to trip on (${again.error || 'made'})`);
  for (const i of ['halfmade', 'halfmade-two']) await post({ project: 'ep.silon', action: 'remove', instance: i });
}

// ---- one button, and a second container from one project ---------------
// The artifact row's controls moved to the manager; what is left is a button
// that names a container and sends you there. A project can have several, all
// built from the same codebase, which is the whole reason instances exist.
await showRow();
ok(!await page.$('#devRow [data-devact]'),
   'the artifact row carries no docker controls any more');
await openDev();
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
// The dialog offers the name the next container takes: the project's own
// while it has none, and once it has that, one beside it, so pressing Send
// again makes another container rather than a refusal naming the first (the
// operator, 26 Sep). Its hint says a second needs ports of its own. How many
// it counts is what the tab had when it loaded, which may still include one
// the block above is removing: a remove is a job, and the record goes when
// the job finishes.
{
  const offer = await page.evaluate(() => ({ name: $('dnName').value, hint: $('dnHint').textContent }));
  const have = Object.keys(JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'))['ep.silon'] || {});
  ok(have.includes('main') && offer.name === 'ep-silon-2'
     && /beside the (one|\d+) it already has: give it ports of its own/.test(offer.hint),
     `with its own container made, the send dialog offers one beside it and says so (${offer.name}; ${
        offer.hint.slice(0, 70)}; has ${have.join(', ')})`);
  const fresh = await (await fetch(URL.replace(/\/$/, '') + '/api/artifacts?project=beta',
    { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json();
  ok(fresh.send_as === 'beta', `...and a project with none is offered its own name (${fresh.send_as})`);
}
// The project's own name still means the project's own container: asked for
// when the project already has one, the answer says so and where it is,
// rather than "needs another name" (the operator, 25 Sep, on a project sent
// for the first time).
{
  // Asked from here rather than the page: a 400 the page fetches lands in
  // its console, and the dev row's check below wants that console clean.
  const own = await (await fetch(URL.replace(/\/$/, '') + '/api/devapp', { method: 'POST',
      headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', action: 'new', instance: 'Ep Silon' }) })).json();
  ok(/already has its own container, ep-silon, on the Containers page/.test(own.error || ''),
     `...and that name asked for again names the container it already is (${String(own.error).slice(0, 70)})`);
}
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
    tip: saidOf(mk),
    acts: q('.dmtab [data-dm="up"],.dmtab [data-dm="down"]').map(b => b.disabled),
    empty: document.querySelector('.dmtab .dmnote, .dmtab .empty')?.textContent || '',
    noRefresh: !document.getElementById('bDockerRe'),
    files: q('.dmtab [data-dm="edit"],.dmtab [data-dm="env"]').map(b => b.disabled),
    removes: q('.dmtab [data-dm="remove"]').map(b => b.disabled),
    off: q('.dmtab .row[data-inst]').map(r => r.classList.contains('off')),
    pills: q('.dmtab .row[data-inst] .dmpill').map(e => e.textContent),
  };
});
ok(dead.newOff && dead.acts.length > 0 && dead.acts.every(Boolean),
   'with no daemon, the controls that would drive one are disabled');
ok(/no node with a daemon/.test(dead.tip),
   '...each carrying the reason rather than just refusing');
ok(/no node with a daemon/.test(dead.empty),
   '...and the tab says it in words, since a tooltip is unreachable on a phone');
ok(dead.noRefresh,
   'there is no Refresh to strand: a daemon wired up is read when its node\'s containers fingerprint moves');
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
   '...grayed, every one of them, so an inert row looks inert before you press');
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
// itself and one node's silence grayed them all. Failing open here is safe:
// a row whose own daemon is down is grayed by the tab's own overview.
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
// only grays what the rows would claim.
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
                 empty: document.querySelector('.dmtab .dmnote, .dmtab .empty')?.textContent || '' };
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
  // grays every row until the next poll; the tab repaints only when its own
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
// one it made, and an unlabeled machine is refused rather than driven.
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
  await page.waitForSelector('.dmtab .dmnote', { timeout: 15000 });
  ok(/not a BuilderBot sandbox/.test(await page.$eval('.dmtab .dmnote', e => e.textContent)),
     'a daemon with no provisioner stamp is refused, and named as the reason');
  // The provisioner's own name, which is provision-linux.sh since there is a
  // macos one beside it. `provision\.sh` matched the name it had before that
  // and nothing since.
  ok(/provision-linux\.sh/.test(await page.$eval('.dmtab .dmnote', e => e.textContent)),
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
  // Waited on the RECORD, not on the row: the row carried built_rev from an
  // earlier build in this file, so a wait on it returned at once, before this
  // build had written its daemon's id (the flake noted on B204).
  const rec = () => (store()['ep.silon'] || {}).main || {};
  const at0 = rec().at || 0;
  await page.evaluate(() => dmAction('ep.silon', 'main', 'rebuild'));
  const t0 = Date.now();
  while (Date.now() - t0 < 60000 && !((rec().at || 0) > at0 && rec().daemon_uid)) await sleep(250);
  ok(!!rec().rev && !!rec().daemon_uid && (rec().at || 0) > at0,
     `a build records which daemon it landed on, by that daemon's own id (${
       rec().daemon_uid ? 'uid recorded' : 'no uid'} after ${Date.now() - t0}ms)`);
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
// The tab at a glance (R216): tiles under the bar count what runs of what
// is here, and a container's row carries its facts as a grid with a
// dotted state pill rather than a run-on line.
{
  const tiles = await page.$$eval('.dmtab .tiles:not(.mini) .tile', ts => ts.map(t => ({
    v: t.querySelector('.tv')?.textContent.trim(), l: t.querySelector('.tl')?.textContent.trim(),
    s: t.querySelector('.ts')?.textContent.trim() || '', h: t.getBoundingClientRect().height })));
  const run = tiles.find(t => t.l === 'running');
  ok(run && +run.v >= 1 && /^of \d+ containers?$/.test(run.s) && tiles.every(t => Math.abs(t.h - tiles[0].h) <= 1),
     `tiles say how many run of how many are here, in one row of one height (${JSON.stringify(tiles.map(t => [t.v, t.l, t.s]))})`);
  // What it is, on one mono line under the name (the operator's concept, 17
  // Oct), and its settings as pills.
  const head = await page.$eval('.dmtab .row[data-inst="ep.silon|staging-two"]', r => ({
    origin: r.querySelector('.dmorigin')?.textContent.replace(/\s+/g, ' ').trim() || '',
    pills: [...r.querySelectorAll('.fpill .k')].map(k => k.textContent.trim()) }));
  ok(head.origin.length > 0 && head.pills.includes('Project'),
     `...and a row says what it is on one line under its name, its settings as pills (${head.origin} | ${head.pills.join(', ')})`);
  // The pill on screen, waited for: read once, the first match could be a
  // redraw's fading copy, or a row in a pane not yet drawn, whose dot has no
  // box to measure (B815).
  // `need` makes it a wait (null until the dot is there); without it, it is
  // the report of what was seen.
  const dotOf = need => {
    const all = [...document.querySelectorAll('.dmtab .row[data-inst="ep.silon|staging-two"] .dmpill')];
    const e = all.find(p => !p.closest('.fghost') && p.offsetParent);
    const b = e ? getComputedStyle(e, '::before') : null;
    const d = { content: b?.content || '', width: b?.width || '', cls: e?.className || '',
                text: e?.textContent.trim() || '', found: all.length, shown: !!e };
    return !need || (d.content === '""' && d.width === '6px') ? d : null;
  };
  const dot = await (await page.waitForFunction(dotOf, true, { timeout: patience(15000) }).catch(() => null))?.jsonValue()
    ?? await page.evaluate(dotOf, false);
  ok(dot.content === '""' && dot.width === '6px', `...the state pill wearing a dot of its color (${JSON.stringify(dot)})`);
  // What it uses now, asked beside the list once it landed and drawn as a
  // strip on the running row: the fixture's docker answers stats with
  // fixed figures.
  await page.waitForSelector('.dmtab .row[data-inst="ep.silon|staging-two"] .dmstats .tile', { timeout: 15000 });
  const strip = await page.$$eval('.dmtab .row[data-inst="ep.silon|staging-two"] .dmstats .tile',
    ts => ts.map(t => `${t.querySelector('.tv')?.textContent.trim()} ${t.querySelector('.tl')?.textContent.trim()}`));
  ok(strip.length === 4 && /^1\.3 ?% CPU$/.test(strip[0].replace(/\s+/g, ' ')) && /Memory/.test(strip[1]) && /Process/.test(strip[3]),
     `...and a running row carries a strip of what it uses: CPU, memory, network, processes (${strip.join(' | ')})`);
  // ...with its last half hour under its CPU and memory (R218 step 9): the
  // node's agent sends each container's use once a minute, and the stub
  // forwards what is planted, a poll at a time.
  // The names off a listing that holds the row: read once, a poll's reload
  // in flight left the listing empty and nothing was planted at all (B846).
  const names = await listingUntil(() => {
    const n = ((dockerList?.instances || []).find(d => `${d.project}|${d.instance}` === 'ep.silon|staging-two')?.services || [])
      .map(c => c.name);
    return n.length ? n : null;
  }, undefined, 20000) || [];
  // Each sample waited for where the page reads it, rather than slept for:
  // the stub forwards what is planted once a poll, and in a busy whole run
  // a poll came later than the seven seconds allowed, so the row had one
  // sample or none and drew no line (B801, B846). The second is held until
  // the rings have two moments, since two polls inside one second are one
  // point on the line.
  const rings = () => page.evaluate(async names => {
    const node = dockerList?.node || dockerNode || '';
    try {
      const g = await (await fetch('/api/docker/stats' + (node ? '?node=' + encodeURIComponent(node) : ''))).json();
      return names.map(n => (g.spark || {})[n] || []);
    } catch { return names.map(() => []); }
  }, names).catch(() => []);
  let ringsSeen = [];
  for (const [i, [cpu, mem]] of [[5, 20], [40, 30]].entries()){
    writeFileSync(`${DIR}/sandboxdata/ctr-stats.json`, JSON.stringify(Object.fromEntries(names.map(n => [n, [cpu, mem]]))));
    const until = Date.now() + patience(45000);
    while (Date.now() < until){
      ringsSeen = await rings();
      if (ringsSeen.length === names.length && ringsSeen.every(r => r.some(x => x[1] === cpu)
            && (i === 0 || new Set(r.map(x => x[0])).size >= 2))) break;
      await sleep(1000);
    }
  }
  rmSync(`${DIR}/sandboxdata/ctr-stats.json`, { force: true });
  // ...and the strip asked for again until it draws the line: the stats are
  // read once per listing, so a listing that landed before the samples did
  // is the last word until something asks again.
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  const sparks = await listingUntil(() => {
    const ts = [...document.querySelectorAll('.dmtab .row[data-inst="ep.silon|staging-two"] .dmstats .tile')]
      .filter(t => !t.closest('.fghost'));
    const got = ts.map(t => t.querySelector('svg.spark')).filter(Boolean);
    return got.length === 1 ? got.map(sv => ({ pts: (sv.querySelector('polyline')?.getAttribute('points') || '').split(' ').length,
                                               dot: !!sv.querySelector('circle'), label: sv.getAttribute('aria-label') })) : null;
  }, undefined, 30000);
  if (!sparks) throw new Error(`B846: no sparkline on staging-two's CPU tile (names ${JSON.stringify(names)}; the rings ${
    JSON.stringify(ringsSeen.map(r => r.map(x => x.slice(0, 2)))).slice(0, 300)})`);
  ok(sparks.every(x => x.pts >= 2 && x.dot && /last half hour/.test(x.label)),
     `...its CPU carries the last half hour as a sparkline, the latest a dot, and its memory how full it is (${JSON.stringify(sparks)})`);
  // Its log, in a fold under the row, read when the fold opens, with Follow.
  const logSect = '.dmtab .row[data-inst="ep.silon|staging-two"] details[data-sect="docker:logs:ep.silon|staging-two"]';
  await page.click(`${logSect} > summary`);
  // Read in the same breath as waited for: the list redraws on every
  // revision and a fold read between the two is "reading…" again.
  const logged = await (await page.waitForFunction(sel => {
    const b = document.querySelector(sel + ' .dmlogbox');
    if (!b || /reading…/.test(b.textContent) || !b.querySelector('[data-dmfollow]')) return null;
    return { pre: !!b.querySelector('pre.dmlog'), none: /printed nothing/.test(b.textContent),
             follow: !!b.querySelector('[data-dmfollow]'), again: !!b.querySelector('[data-dmlogagain]') };
  }, logSect, { timeout: 15000 })).jsonValue();
  ok((logged.pre || logged.none) && logged.follow && logged.again,
     `a row's Log fold reads the container's tail when opened, with Follow and Read again (${JSON.stringify(logged)})`);
  await page.click(`${logSect} > summary`);
  // The daemon's images and volumes, in a section at the foot: tiles of
  // what it holds, each image in use or not, each volume, and the two
  // prunes that touch nothing a container uses (the fixture answers all
  // three listings and records a prune).
  const imgSect = '.dmtab details[data-sect="docker:images"]';
  await page.click(`${imgSect} > summary`);
  await page.waitForFunction(sel => document.querySelector(sel + ' .dmimg'), imgSect, { timeout: 60000 });
  const imgs = await page.evaluate(sel => ({
    tiles: [...document.querySelectorAll(sel + ' .tiles:not(.mini) .tile')].map(t => `${t.querySelector('.tv')?.textContent.trim()} ${t.querySelector('.tl')?.textContent.trim()}`),
    rows: [...document.querySelectorAll(sel + ' .dmimg')].map(r => `${r.querySelector('.tline')?.textContent.replace(/\s+/g, ' ').trim()}`),
    vols: [...document.querySelectorAll(sel + ' .dmvol .td.lead')].map(e => e.textContent.trim()),
    heads: [...document.querySelectorAll(sel + ' .tbl > .thead')].map(h => [...h.children].map(c => c.textContent.trim()).join(' ')),
    // Each line's cells under the header's: a plain row once shrank its line.
    off: [...document.querySelectorAll(sel + ' .tbl')].reduce((n, t) => {
      const hx = [...t.querySelector(':scope > .thead').children].map(c => Math.round(c.getBoundingClientRect().left));
      return n + [...t.querySelectorAll(':scope > .row > .tline')].filter(l =>
        [...l.children].some((c, i) => Math.abs(Math.round(c.getBoundingClientRect().left) - hx[i]) > 1)).length; }, 0),
    status: document.querySelector(sel + ' > summary .sst')?.textContent.trim(),
    prunes: document.querySelectorAll(sel + ' [data-dmprune]').length }), imgSect);
  ok(imgs.tiles.some(t => /^2 images/.test(t)) && imgs.rows.some(r => /ep-silon-img:latest.*in use/i.test(r)) && imgs.rows.some(r => /dangling.*unused/i.test(r))
     && imgs.vols.includes('orphan-vol') && /2 images, 2 volumes/.test(imgs.status || '') && imgs.prunes === 2
     && imgs.heads[0] === 'Image State ID Size Created' && imgs.heads[1] === 'Volume Driver' && imgs.off === 0,
     `the Images and volumes section lists the daemon's images in use or not and its volumes, as two tables, and offers the two prunes (${JSON.stringify(imgs)})`);
  // The confirmation is accepted by the page's own dialog handler (lib.mjs).
  await page.click(`${imgSect} [data-dmprune="volumes"]`);
  await page.waitForFunction(() => /pruned volumes/.test(document.body.textContent), null, { timeout: 15000 });
  ok(/volume prune -f/.test(readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8')),
     '...and Prune volumes runs docker volume prune with -f and nothing named, saying what it gave back');
  await page.click(`${imgSect} > summary`);
  // Chips narrow the list to one project, when there is more than one.
  const chips = await page.$$eval('.dmtab .chips .chip', cs => cs.map(c => c.dataset.dmchip));
  if (chips.length){
    const mine = await page.$$eval('.dmtab .chips .chip', cs => cs.find(c => c.dataset.dmchip === 'ep.silon')?.textContent || '');
    ok(chips[0] === '' && /ep\.silon/.test(mine), `the chips start with All and count each project (${chips.join('|')})`);
    await page.click('.dmtab .chips .chip[data-dmchip="ep.silon"]');
    await page.waitForFunction(() => document.querySelector('.dmtab .chip.on')?.dataset.dmchip === 'ep.silon', null, { timeout: 5000 });
    await faded(page);
    const shown = await page.$$eval('.dmtab .dmgroup b', bs => bs.map(b => b.textContent.trim()));
    ok(shown.length === 1 && /ep\.silon|epsilon/i.test(shown[0]),
       `...a chip narrows the list to that project's group alone (${shown.join('|')})`);
    await page.click('.dmtab .chips .chip[data-dmchip=""]');
    await page.waitForFunction(() => document.querySelector('.dmtab .chip.on')?.dataset.dmchip === '', null, { timeout: 5000 });
    ok(await page.$$eval('.dmtab .dmgroup', gs => gs.length) > 1, '...and All puts every group back');
  } else {
    ok(true, 'one project here, so no chips: a chip row of one is not drawn');
  }
  // A published port is the address it answers at (R216): the card's Open,
  // its main action (the operator's concept, 17 Oct), or a stack's service's.
  const portLink = await page.$eval('.dmtab .row[data-inst="ep.silon|staging-two"] :is(a.dmopenb, .dmsvctbl a)', a => a.href);
  ok(/^http:\/\/[^/]+:7475\/$/.test(portLink), `a published port is a link to where it answers (${portLink})`);
  // Docker's health, read off the status and said on the pill: the fixture
  // wears what its marker says.
  const upFile = readdirSync(`${DIR}/dockerstate`).find(f => /staging-two.*\.up$/.test(f));
  const pn = upFile.replace(/\.up$/, '');
  writeFileSync(`${DIR}/dockerstate/${pn}.health`, 'unhealthy');
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  await page.waitForFunction(() => /unhealthy/.test(document.querySelector('.dmtab .row[data-inst="ep.silon|staging-two"] .dmpill')?.textContent || ''), null, { timeout: 20000 });
  ok(await page.$eval('.dmtab .row[data-inst="ep.silon|staging-two"] .dmpill', e => e.classList.contains('bad')),
     'an unhealthy container says so on its state pill, in red');
  writeFileSync(`${DIR}/dockerstate/${pn}.health`, 'healthy');
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  await page.waitForFunction(() => /^healthy/.test(document.querySelector('.dmtab .row[data-inst="ep.silon|staging-two"] .dmpill')?.textContent || ''), null, { timeout: 20000 });
  ok(true, '...and a healthy one says healthy rather than running');
  rmSync(`${DIR}/dockerstate/${pn}.health`, { force: true });
  // The list view (R216): one line per container that opens into its card,
  // this browser's choice, and the search narrows the rows as typed.
  await page.click('.dmtab [data-dmview="list"]');
  await page.waitForSelector('.dmtab details.dmline[data-inst="ep.silon|staging-two"] > summary.dmsum', { timeout: 10000 });
  const line = await page.$eval('.dmtab details.dmline[data-inst="ep.silon|staging-two"]', d => ({
    open: d.open, name: d.querySelector('summary .name')?.textContent.trim(), facts: d.querySelector('summary .td[data-th="Ports"]')?.textContent.replace(/\s+/g, ' ').trim(),
    head: [...(d.closest('.dmtbl')?.querySelectorAll(':scope > .thead .th') || [])].map(t => t.textContent).join('|'),
    body: !!d.querySelector('.dmbody .dmhead') }));
  ok(!line.open && /staging-two/.test(line.name || '') && /7475/.test(line.facts || '') && line.body
     && /^Container\|State\|Project\|Ports\|Address\|Image$/.test(line.head),
     `in list view a container is one line of a table under its project, its name, state and facts in columns, with its card behind it (${JSON.stringify(line)})`);
  // Pressed on its name: the line's middle is its Ports column, and a port
  // there is a link that answers the press itself.
  await page.click('.dmtab details.dmline[data-inst="ep.silon|staging-two"] > summary.dmsum .td.lead');
  await page.waitForFunction(() => document.querySelector('.dmtab details.dmline[data-inst="ep.silon|staging-two"]')?.open, null, { timeout: 5000 });
  ok(await page.$eval('.dmtab details.dmline[data-inst="ep.silon|staging-two"] .dmbody .actbar.dmacts', e => e.getBoundingClientRect().height > 0),
     '...which opens into the card with its settings and its action bar');
  ok(await page.evaluate(() => { try { return localStorage.getItem('bb.dmview'); } catch (e) { return 'no storage'; } }) === 'list',
     '...and the choice is this browser\'s, kept');
  await page.fill('.dmtab #dmSearch', 'staging');
  await page.waitForFunction(() => [...document.querySelectorAll('.dmtab .row[data-inst]')].every(r => /staging/.test(r.dataset.inst)) && document.querySelectorAll('.dmtab .row[data-inst]').length >= 1, null, { timeout: 10000 });
  ok(true, 'the search narrows the rows to what matches as it is typed');
  ok(await page.$$eval('.dmtab .tiles:not(.mini) .tile', ts => ts.length > 0), '...while the tiles still count the whole');
  await page.fill('.dmtab #dmSearch', 'no-such-container-anywhere');
  await page.waitForFunction(() => /nothing here matches/.test(document.querySelector('.dmtab .empty')?.textContent || ''), null, { timeout: 10000 });
  ok(true, '...and nothing matching says so');
  await page.fill('.dmtab #dmSearch', '');
  await page.waitForFunction(() => document.querySelectorAll('.dmtab .row[data-inst]').length > 1, null, { timeout: 10000 });
  await page.click('.dmtab [data-dmview="cards"]');
  await page.waitForSelector('.dmtab div.row[data-inst="ep.silon|staging-two"]', { timeout: 10000 });
  ok(true, 'and Cards puts the full rows back');
}
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
// The dialog closing is the create's own answer. The row is not: the refused
// attempt above can still be on the tab for a poll (B239), and waiting on it
// checked the file before this Create had reached the server.
await page.waitForFunction(() => document.getElementById('cmodal').hidden, null, { timeout: 20000 });
ok(existsSync(`${DIR}/state/containers/radarr/docker-compose.yml`),
   'one that parses is written to /config, where no project scan can see it');
await page.waitForSelector('.dmtab .row[data-inst="radarr|main"]', { timeout: 20000 });
// Its name is editable while it is down (the operator, 11 Oct): the Edit
// dialog's Name field is live for a container with nothing running, and
// the hint says what follows it; a running one keeps the name locked.
{
  await page.evaluate(() => openEditContainer('radarr'));
  await page.waitForSelector('#cmodal:not([hidden])');
  const live = await page.evaluate(() => ({ off: document.getElementById('cName').disabled,
                                            hint: document.getElementById('cNameHint').textContent }));
  ok(!live.off && /while it is down/.test(live.hint),
     `Edit on a container that is down offers its name to change (${live.hint.slice(0, 60)})`);
  await page.click('#cCancel').catch(() => page.evaluate(() => { document.getElementById('cmodal').hidden = true; }));
  await page.waitForFunction(() => document.getElementById('cmodal').hidden, null, { timeout: 10000 });
  const saved = await page.evaluate(async () => (await (await fetch('/api/container', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'save', name: 'radarr', rename: 'radarr', compose: 'services:\n  app:\n    image: lscr.io/x:latest\n', env: '' }) })).json()));
  ok(!saved.error && !saved.job, `a Save with the name as it was renames nothing (${JSON.stringify(saved).slice(0, 60)})`);
}
// ---- a port only nginx reaches, with no route yet -------------------------
// The first-time trap of a container moved to a VPS (11 Oct): its port is on
// 127.0.0.1 there, so it answers nowhere until an nginx route points at it,
// and the row says so with the way to the nginx tab; routed, it says nothing.
{
  const said = await page.evaluate(() => {
    const was = dockerList;
    const row = { owner: 'aquilaeLabs', running: true, ports: ['127.0.0.1:8380->80/tcp', '9000->9000/tcp'] };
    dockerList = { ...(was || {}), node: 'n1', ports_local: true, nginx_ports: [] };
    const bare = dmUnrouted(row);
    dockerList = { ...(was || {}), node: 'n1', ports_local: true, nginx_ports: [8380] };
    const routed = dmUnrouted(row);
    dockerList = { ...(was || {}), node: 'n1', ports_local: false, nginx_ports: [] };
    const elsewhere = dmUnrouted(row);
    dockerList = was;
    return { bare, routed, elsewhere };
  });
  ok(/8380 is reachable only through this node's nginx, and no route points at it yet/.test(said.bare)
     && /data-dmnginx="n1"/.test(said.bare) && !/9000/.test(said.bare) && said.routed === '' && said.elsewhere === '',
     `a loopback port nothing routes to says so with the way to the nginx page, and says nothing once routed or off a hosting node (${said.bare.replace(/<[^>]+>/g, '').slice(0, 70)})`);
}

// ---- a registry image that moved (R195) ---------------------------------
// The operator, 11 Oct: Update on any container whose image comes from a
// registry, not nginx alone. radarr runs one (no build): the node has pulled
// it at one digest, the registry (BB_IMAGE_DIGESTS_FILE) serves another, so
// Check for updates finds it behind, the row says which with Update, the
// bell carries a note of its own, and Update pulls and starts it again.
{
  const img = 'lscr.io/linuxserver/radarr:latest';
  writeFileSync(`${DIR}/dockerstate/radarr.config`, JSON.stringify({ services: { app: { image: img } } }));
  mkdirSync(`${DIR}/dockerstate/repodigests`, { recursive: true });
  writeFileSync(`${DIR}/dockerstate/repodigests/${img.replace(/[/:]/g, '_')}`, JSON.stringify([`lscr.io/linuxserver/radarr@sha256:${'a'.repeat(64)}`]));
  writeFileSync(`${DIR}/image-digests.json`, JSON.stringify({ [img]: `sha256:${'b'.repeat(64)}` }));
  await page.waitForSelector('#bDockerCheck', { timeout: 15000 });
  ok(await page.$eval('.dmimgbar .state', e => /not checked yet|checked/.test(e.textContent)),
     'the Containers page says when its registry images were last checked, beside Check for updates');
  await page.click('#bDockerCheck');
  await page.waitForSelector('.dmtab .row[data-inst="radarr|main"] .dmimages', { timeout: 20000 });
  ok(await page.$eval('.dmtab .row[data-inst="radarr|main"]', r => /a newer lscr\.io\/linuxserver\/radarr:latest is out/.test(r.querySelector('.dmimages').textContent)
       && !!r.querySelector('[data-dm="update"]')),
     'Check for updates finds a registry image the registry has moved: the row says which, with Update');
  ok(!(await page.$('.dmtab .row[data-inst^="ep.silon|"] [data-dm="update"]')),
     '...and a container built from code is not offered it: Rebuild is what moves that');
  await page.evaluate(() => refresh());
  await page.click('#bBell');
  await page.waitForSelector('#bellPanel [data-bdocker]', { timeout: 15000 });
  ok(await page.$eval('#bellPanel', e => /container update/.test(e.textContent) && /radarr \(lscr\.io\/linuxserver\/radarr:latest\)/.test(e.textContent)
       && !!e.querySelector('[data-bdismiss^="image:"]')),
     'the bell carries a container-update note of its own, with Dismiss');
  await page.click('#bBell');
  const before = dockerLog().length;
  await page.click('.dmtab .row[data-inst="radarr|main"] [data-dm="update"]');
  await page.waitForFunction(() => !document.querySelector('.dmtab .row[data-inst="radarr|main"] .dmimages'), null, { timeout: 30000 });
  const said = dockerLog().slice(before);
  ok(/compose .*pull --ignore-buildable/.test(said) && /compose .* up -d/.test(said),
     `Update pulls the registry images and starts it again, and the row stops saying it is behind (${said.split('\n').filter(l => /pull|up -d/.test(l)).length} lines)`);
  rmSync(`${DIR}/dockerstate/radarr.config`, { force: true });
  // Down again: Update started it, and the checks below edit it as it was, down.
  rmSync(`${DIR}/dockerstate/radarr.up`, { force: true });
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  await page.waitForFunction(() => (dockerList?.instances || []).some(d => d.project === 'radarr' && !d.running), null, { timeout: 20000 });
}
// ---- a row on a phone (R68 step 5) ---------------------------------------
// What a row carries is on the row at every width, never behind a fold (the
// operator, 8 Oct: too much was hidden; the Project picker was not found).
{
  await openManager();
  await page.setViewportSize({ width: 390, height: 844 });
  // A phone shows one thing at a time, and the manager is in the pane behind
  // the sidebar: without this the row measures zero and says nothing.
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
  await dmEditAll();
  await page.waitForSelector('.dmtab .dmowner select', { state: 'visible', timeout: 15000 });
  const narrow = await page.evaluate(() => {
    const t = document.querySelector('.dmtab');
    const acts = document.querySelector('.dmtab .dmacts');
    return { fold: !!document.querySelector('.dmtab details.dmdet, .dmtab .dmsum'),
             sideways: t.scrollWidth > t.clientWidth + 2,
             actsVisible: !!acts && acts.getBoundingClientRect().height > 0 };
  });
  ok(!narrow.fold, `on a phone the row's detail and its Project picker are on the row, no fold (${JSON.stringify(narrow)})`);
  ok(!narrow.sideways && narrow.actsVisible, '...nothing scrolls sideways, and the row keeps its buttons');
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => { dockerList = null; dockerRev++; loadDocker(); });
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
  await dmEditNone();
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

ok(/written here/.test(await page.$eval(
     '.dmtab .row[data-inst="radarr|main"]', r => r.textContent))
   && await page.evaluate(() => {
     // The heading a row sits under is the last one before it.
     const row = document.querySelector('.dmtab .row[data-inst="radarr|main"]');
     const heads = [...document.querySelectorAll('.dmtab .dmgroup')]
       .filter(h => h.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING);
     return /No project/.test(heads.pop()?.textContent || '');
   }),
   '...and the manager says which kind it is on the row, under No project, since none was picked');
// Editing one: what it is changes far more often than it is created, and
// without this the only way to move a port was to remove it and retype it.
await pressIn('.dmtab .row[data-inst="radarr|main"] [data-dm="edit"]');
await page.waitForSelector('#cmodal:not([hidden])');
await page.waitForFunction(() => /services:/.test(document.getElementById('cYml').value),
                           { timeout: 10000 });
// Its name stays a field while it is down (the operator, 11 Oct: a rename
// is the Edit dialog's, with the container down); it reads the name as is.
ok(await page.$eval('#cName', e => !e.disabled && e.value === 'radarr'),
   'editing opens on the container, its name in the field as it is');
await page.fill('#cYml', 'services:\n  app:\n    image: alpine:latest\n');
await page.click('#cGo');
await page.waitForFunction(() => document.getElementById('cmodal').hidden,
                           { timeout: 15000 });
ok(/alpine:latest/.test(readFileSync(`${DIR}/state/containers/radarr/docker-compose.yml`, 'utf8')),
   '...and Save writes the new compose file');
// One that will not parse leaves the old file where it was.
writeFileSync(`${DIR}/dockerstate/config.fail`, '1');
await pressIn('.dmtab .row[data-inst="radarr|main"] [data-dm="edit"]');
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
await pressIn('.dmtab .row[data-inst="radarr|main"] [data-dm="remove"]');
await page.waitForFunction(() =>
  !document.querySelector('.dmtab .row[data-inst="radarr|main"]'), { timeout: 20000 });
ok(!existsSync(`${DIR}/state/containers/radarr`),
   'removing one written here takes its compose file with it');


// The same name twice is refused rather than silently reusing the first.
await showRow();
await openDev();
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
await pressIn('.dmtab .row[data-inst="ep.silon|staging-two"] [data-dm="remove"]');
await page.waitForFunction(() =>
  !document.querySelector('.dmtab .row[data-inst="ep.silon|staging-two"]'),
  { timeout: 20000 });
ok(true, 'Remove takes a container out of the manager');
ok(/compose --project-name staging-two .*down/.test(dockerLog()),
   '...taking it down first, rather than orphaning its containers');
await showRow();
ok(await page.$('#devSend'),
   '...and the project can still send another: the artifact row persists');

// Copy or move (the operator, 10 Oct): a row's button opens a dialog with
// the node it is on left out, the project's own nodes grouped first, and its
// env to change on the way. The jobs themselves are the unit tier's
// (test_relocate.py): this harness's docker has volumes enough for them, but
// one node.
{
  await openManager();
  await pressIn(`${DM} [data-dmrel]`);
  await page.waitForSelector('#rlmodal:not([hidden])');
  await page.waitForFunction(() => !/reading/.test(document.getElementById('rlEnvHint').textContent), null,
                             { timeout: patience(10000) }).catch(() => {});
  const dlg = await page.evaluate(() => ({
    groups: [...document.querySelectorAll('#rlNode optgroup')].map(g => g.label),
    here: [...document.querySelectorAll('#rlNode option')].some(o => o.value === (dockerList?.node || dockerNode)),
    env: document.getElementById('rlEnv').value, name: document.getElementById('rlName').value,
    go: document.getElementById('rlGo').textContent }));
  ok(!dlg.here && /PORT=/.test(dlg.env) && dlg.name.endsWith('-copy') && dlg.go === 'Copy',
     `Copy or move opens on a copy, its env to change, never offering the node it is on (${JSON.stringify(dlg).slice(0, 160)})`);
  await page.check('input[name="rlMode"][value="move"]');
  ok(await page.$eval('#rlNameField', e => e.hidden) && await page.$eval('#rlGo', e => e.textContent) === 'Move'
     && /comes? down|come down/.test(await page.$eval('#rlModeHint', e => e.textContent)),
     '...and a move keeps its name and says the old node\'s containers come down once it is up');
  // Its data (the operator, 14 Oct): unpacked on arrival, warned as writing
  // over a volume of the same name, or carried as the archive for later.
  ok(await page.$eval('input[name="rlData"][value="unpack"]', e => e.checked)
     && await page.$eval('#rlDataHint', e => /written over/.test(e.textContent) && e.classList.contains('warn')),
     'its data is unpacked on arrival by default, with the warning that a volume already there is written over');
  await page.check('input[name="rlData"][value="archive"]');
  ok(await page.$eval('#rlDataHint', e => /stays there/.test(e.textContent) && /Unpack/.test(e.textContent) && !e.classList.contains('warn')),
     '...and carried as an archive it says where the file lands and that the row offers Unpack');
  await page.check('input[name="rlData"][value="none"]');
  ok(await page.$eval('#rlDataHint', e => /stay on this node/.test(e.textContent))
     && /empty volumes/.test(await page.$eval('#rlModeHint', e => e.textContent)),
     '...and left here, the move\'s own line says it starts there with empty volumes');
  await page.click('#rlCancel');
  // The grouping itself, on a picker of three nodes: the project's own first
  // and said so, the one a container is on left out.
  const grouped = await page.evaluate(() => {
    const sel = document.createElement('select');
    sel.innerHTML = '<option value="a">a</option><option value="b">b</option><option value="c">c</option>';
    groupNodeOptions(sel, ['b'], 'ep.silon', 'c');
    return [...sel.querySelectorAll('optgroup')].map(g => [g.label.split(':')[0], [...g.children].map(o => o.value)]);
  });
  ok(JSON.stringify(grouped) === '[["ep.silon\'s nodes",["b"]],["Other nodes",["a"]]]',
     `the node picker puts the project's own nodes first and leaves out the one it is on (${JSON.stringify(grouped)})`);
  // The projects a container may be put under, sent from or moved to: the
  // account's own list, whatever its role, and a row's own project kept.
  const picked = await page.evaluate(() => {
    const was = state.projects;
    state.projects = [{ name: 'mine1', mine: true }, { name: 'theirs', mine: false }];
    const r = myProjectNames('rowsown');
    state.projects = was;
    return r;
  });
  ok(JSON.stringify(picked) === '["mine1","rowsown"]',
     `the project pickers offer only the account's own projects, and the row's current one (${JSON.stringify(picked)})`);
}

// Every compose file in the repository is a row with its own Send (the
// operator, 10 Oct): one in a folder, a variant beside the root's, never an
// override, which is half a file. Sent from its row, a container is made
// from that file and its compose calls run in its folder, which is what the
// file's relative paths mean; the manager says which file made it.
{
  mkdirSync(`${D}/site`, { recursive: true });
  writeFileSync(`${D}/site/compose.yml`, 'services:\n  web:\n    build: .\n');
  writeFileSync(`${D}/docker-compose.prod.yml`, 'services:\n  app:\n    image: nginx\n');
  writeFileSync(`${D}/docker-compose.override.yml`, 'services: {}\n');
  const nudge2 = async () => {
    const f = `${DIR}/state/devapps.json`;
    writeFileSync(f, readFileSync(f, 'utf8'));
    await page.evaluate(() => refresh());
  };
  await nudge2();
  await showRow();
  await page.waitForFunction(() => document.querySelectorAll('[data-devsend]').length === 3, null, { timeout: patience(20000) })
    .catch(() => {});
  const files = await page.$$eval('#devRow, [data-devrow]', rs => rs.map(r => r.querySelector('.top b')?.textContent.trim()));
  ok(JSON.stringify(files) === '["docker-compose.yml","docker-compose.prod.yml","site/compose.yml"]',
     `every compose file is a row of its own, the root's first and no override (${JSON.stringify(files)})`);
  const at = files.indexOf('site/compose.yml');
  await page.click(`[data-devsend="${at}"]`);
  await page.waitForSelector('#dnmodal:not([hidden])');
  const named = await page.$eval('#dnName', e => e.value);
  ok(named === 'ep-silon-site' && /site\/compose\.yml/.test(await page.$eval('#dnHint', e => e.textContent)),
     `its Send opens on a name of its own and says which file (${named})`);
  await page.click('#dnGo');
  await page.waitForFunction(() => document.querySelector('.dmtab .row[data-inst="ep.silon|ep-silon-site"]'),
                             null, { timeout: patience(20000) });
  let log = '';
  for (let i = 0; i < 40 && !/--project-name ep-silon-site .*build/.test(log); i++){ await sleep(500); log = dockerLog(); }
  const line = log.split('\n').find(l => /--project-name ep-silon-site .*build/.test(l)) || '';
  // On an agent node the file's text travels with the job and lands in its
  // own folder there: read back, it is the site's.
  const shipped = (line.match(/ -f (\S+)/) || [])[1] || '';
  let text = '';
  try { text = readFileSync(shipped, 'utf8'); } catch {}
  ok(line.includes(`--project-directory ${D}/site `) && /web:/.test(text) && !/app:/.test(text),
     `...and its build runs compose in that file's folder, on that file (${line.slice(0, 120)}; ${text.replace(/\s+/g, ' ').slice(0, 40)})`);
  await dmRefresh();
  ok(await page.$eval('.dmtab .row[data-inst="ep.silon|ep-silon-site"] .dmorigin', e => /site\/compose\.yml/.test(e.textContent)),
     '...and its Docker row says which file made it, on the line under its name');
  const again = await page.evaluate(async () => (await (await fetch('/api/devapp', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'ep.silon', action: 'new', instance: 'stray', compose: 'docker-compose.override.yml' }) })).json()));
  ok(/has no compose file docker-compose\.override\.yml/.test(again.error || ''),
     `a file that is not one of its compose files is refused by name (${again.error})`);
  await idle(60000);
  // Remove is dead while the row's build job runs, and that job outlasts the
  // minute above in a loaded run (B723): wait for the button itself.
  await page.waitForFunction(() => { const b = document.querySelector('.dmtab .row[data-inst="ep.silon|ep-silon-site"] [data-dm="remove"]');
                                     return b && !b.disabled; }, null, { timeout: patience(120000) });
  await pressIn('.dmtab .row[data-inst="ep.silon|ep-silon-site"] [data-dm="remove"]');
  await page.waitForFunction(() => !document.querySelector('.dmtab .row[data-inst="ep.silon|ep-silon-site"]'),
                             null, { timeout: patience(20000) });
  rmSync(`${D}/site`, { recursive: true, force: true });
  rmSync(`${D}/docker-compose.prod.yml`, { force: true });
  rmSync(`${D}/docker-compose.override.yml`, { force: true });
  await nudge2();
  // Left only once its Remove has finished: a job still on the node is a
  // listing the next block reads half-drawn.
  await idle(60000);
}



// ---- building an instance from another branch -----------------------------
// A project's tree is SHARED (one checkout for every session and every
// person on it), so "build the other branch" cannot mean switching it. An
// instance pinned to a ref builds from a worktree of its own, beside the
// project and carrying a .bbignore, and the project's checkout is untouched.
{
  const G = (...a) => execFileSync('git', ['-C', D, ...a], { env, encoding: 'utf8' });
  // The branch list is memoised on .git's mtimes (B205), so the listing read
  // BEFORE the branch exists is what proves the memo lets go: the same
  // question after the commit has to see the new branch, from git, not the
  // kept answer.
  const listing = () => page.evaluate(async () => (await (await fetch('/api/docker')).json()).refs?.['ep.silon'] || []);
  const refsBefore = await listing();
  G('checkout', '-q', '-b', 'sidebranch');
  writeFileSync(`${D}/ONLY-ON-SIDE.txt`, 'x\n');
  G('add', '-A'); G('commit', '-qm', 'side work');
  const sideSha = G('rev-parse', '--short=7', 'HEAD').trim();
  G('checkout', '-q', '-');
  const refsAfter = await listing();
  ok(!refsBefore.includes('sidebranch') && refsAfter.includes('sidebranch'),
     `the branch picker's memo lets go when the repository moves (before: ${refsBefore.join(',')}; after: ${refsAfter.join(',')})`);
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
  // Asked again a few times: once in about ten runs the page's branch list
  // still read ["master"] after the server had listed sidebranch (B619),
  // and one read made that a failure. The listing is waited for first, the
  // page's own answer carrying both the branch and the pin, and only then
  // is the control opened and read, off the row on screen and never a
  // redraw's fading copy.
  await openManager();
  const refListed = await listingUntil(() => {
    const d = (dockerList?.instances || []).find(x => x.project === 'ep.silon' && x.instance === 'main');
    return (dockerList?.refs?.['ep.silon'] || []).includes('sidebranch') && d?.ref === 'sidebranch' ? true : null;
  }, undefined, 30000);
  let refPick = '';
  for (let i = 0; i < 5 && refPick !== 'sidebranch'; i++){
    await dmEditAll();
    refPick = await (await page.waitForFunction(sel => {
      const r = [...document.querySelectorAll(sel)].find(x => !x.closest('.fghost'));
      const v = r?.querySelector('[data-dmref]')?.value || '';
      return v === 'sidebranch' ? v : null;
    }, DM, { timeout: 5000 }).catch(() => null))?.jsonValue() || '';
    if (refPick !== 'sidebranch') await openManager();
  }
  // What the page held and what the server says now, side by side, so a
  // failure names which of the two was behind.
  const refSeen = refPick === 'sidebranch' ? '' : await page.evaluate(async ([sel, was]) => {
    const r = [...document.querySelectorAll(sel)].find(x => !x.closest('.fghost'));
    let server = null;
    try { server = (await (await fetch('/api/docker' + (dockerNode ? '?node=' + encodeURIComponent(dockerNode) : ''))).json()).refs?.['ep.silon']; }
    catch (e) { server = String(e); }
    return JSON.stringify({ inst: r?.dataset.inst, control: !!r?.querySelector('[data-dmref]'),
                            refs: dockerList?.refs?.['ep.silon'], server, node: dockerNode, fetching: dockerFetching,
                            rows: [...document.querySelectorAll(sel)].length, listed: was });
  }, [DM, !!refListed]);
  ok(refPick === 'sidebranch', `...and the Ref control holds it (${refPick || 'empty'} ${refSeen})`);
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
  ok(off.status === 403 && /project's settings, Claude may: Run its container/.test(off.error || ''),
     `a session cannot rebuild until the project says so, and is told where the setting is (${
        JSON.stringify(off).slice(0, 90)})`);
  // The two verbs that make and unmake a container are not on the dial at
  // all: they are docker-write, which a session's principal never has, so
  // the grant cannot reach them however it is set. This is the operator's
  // own line (the user makes them, Claude rebuilds them), and it is checked
  // here rather than trusted to the ordering of two ifs.
  // (Route, where the thing is reached from, stays the operator's.)
  for (const act of ['route']){
    const r = await asSession({ project: 'ep.silon', action: act, instance: 'main' });
    ok(r.status === 403 && /starting and stopping containers needs Container/.test(r.error || ''),
       `...and ${act} is not a session's at any setting (${String(r.error).slice(0, 48)})`);
  }
  // Its env and creating its own container are on the setting now (the
  // operator, 24 Sep), so at deny they are refused by it, naming it.
  for (const act of ['new', 'env-set', 'env-get', 'remove']){
    const r = await asSession({ project: 'ep.silon', action: act, instance: 'main' });
    ok(r.status === 403 && /Run its container/.test(r.error || ''),
       `...and at deny ${act} is refused by the same setting (${String(r.error).slice(0, 48)})`);
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
  await idle();
  // ---- the setting covers its env and a fresh container (24 Sep) -----------
  // So a session can bring a container up by request even where the project
  // has none yet: on auto it sets the env and creates the project's own; on
  // ask one request carries both, the approver sees the env's keys and never
  // its values, and Allow creates, writes and builds.
  {
    const set = await asSession({ project: 'ep.silon', action: 'env-set', instance: 'main', text: 'MODE=session\n' });
    const got = await asSession({ project: 'ep.silon', action: 'env-get', instance: 'main' });
    ok(set.status === 200 && /MODE=session/.test(got.text || ''),
       `on auto a session sets its container's env and reads it back (${set.status}, ${got.status})`);
    const made = await asSession({ project: 'ep.silon', action: 'new', instance: 'fresh' });
    ok(made.status === 200 && made.instance === 'fresh',
       `...and creates its project's own container (${made.error || made.instance})`);
    const under = await asSession({ project: 'ep.silon', action: 'new', instance: 'elsewhere', owner: 'alpha' });
    ok(under.status === 403, `...but not one belonging to another project (${under.status})`);
    // ...nor one sent to a node its project does not name under Hosts its
    // containers on (prefs.hosts, the operator, 10 Oct): that is a person's.
    const away = await asSession({ project: 'ep.silon', action: 'new', instance: 'away', node: 'nowhere-node', ship: true });
    ok(away.status === 403 && /unless the node is ticked under Also works on/.test(away.error || ''),
       `...nor one shipped to a node its project's settings do not name, said with where to name it (${away.status})`);
    // ...and one shipped to a node the settings DO name under Hosts its
    // containers on keeps that node and is marked shipped: the session branch
    // blanked the node after the gate had let it through, so the container
    // was made, unshipped, on the project's own node (B645, 11 Oct).
    const vps = await page.evaluate(async () => {
      const m = await (await fetch('/api/v1/nodes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'enroll', name: 'vps-host', host_only: true }) })).json();
      const h = await (await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: 'ep.silon', hosts: [m.id] }) })).json();
      return { id: m.id, err: m.error || h.error || '' };
    });
    const sent = await asSession({ project: 'ep.silon', action: 'new', instance: 'shipped', node: vps.id, ship: true });
    const shipRec = (JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'))['ep.silon'] || {}).shipped || {};
    ok(!vps.err && sent.status === 200 && shipRec.node === vps.id && shipRec.ship === true,
       `...and one shipped to a node under Hosts its containers on is bound to it and marked shipped (${vps.err || sent.error || JSON.stringify([shipRec.node, shipRec.ship])})`);
    await asSession({ project: 'ep.silon', action: 'remove', instance: 'shipped' });
    // ...and the hosting node goes: the Send dialog below offers every hosting
    // node there is, and counts them.
    await page.evaluate(async (id) => {
      await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project: 'ep.silon', hosts: [] }) });
      await fetch('/api/v1/nodes', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'retire', id }) });
    }, vps.id);
    // ...and removes one, under the same setting (the operator, 24 Sep):
    // the row goes, its env and data stay, as the tab's Remove leaves them.
    const gone = await asSession({ project: 'ep.silon', action: 'remove', instance: 'fresh' });
    await idle();
    const insts = () => Object.keys(JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'))['ep.silon'] || {});
    ok(gone.status === 200 && !insts().includes('fresh'),
       `...and removes its own container on auto (${gone.error || gone.job || 'removed'}; left: ${insts().join(', ')})`);
    await dial('ask');
    const asks = await asSession({ project: 'ep.silon', action: 'new', instance: 'asked',
                                   text: 'KEY=secret-value\n', why: 'a fresh one to try the branch' });
    const seen = await page.evaluate(async (id) =>
      ((await (await fetch('/api/phone')).json()).asks || []).find(a => a.id === id), asks.id);
    ok(asks.status === 200 && asks.id && seen?.create === true && JSON.stringify(seen.env_keys) === '["KEY"]'
       && !JSON.stringify(seen).includes('secret-value'),
       `on ask one request carries the create and the env, showing the env's keys and never its values (${JSON.stringify(seen?.cmd)})`);
    await page.evaluate(async (id) => {
      await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ action: 'allow', id }) });
    }, asks.id);
    await idle();
    const after = await page.evaluate(async () => {
      const r = await fetch('/api/devapp', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                             body: JSON.stringify({ project: 'ep.silon', instance: 'asked', action: 'env-get' }) });
      return r.json();
    });
    ok(/KEY=secret-value/.test(after.text || ''),
       `...and Allow creates it and writes its env before the build (${after.error || 'stored'})`);
    // ...while an env set on one that exists is written and NOT built: the
    // card said "env set", and a build would bounce a container nobody was
    // told would move (the review of 24 Sep).
    const builds = () => (dockerLog().match(/compose[^\n]* build/g) || []).length;
    const b0 = builds();
    const envAsk = await asSession({ project: 'ep.silon', action: 'env-set', instance: 'asked',
                                     text: 'KEY=changed\n', why: 'a new key' });
    await page.evaluate(async (id) => {
      await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ action: 'allow', id }) });
    }, envAsk.id);
    await idle();
    const envOut = await (await fetch(URL.replace(/\/$/, '') + '/api/phone',
      { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
        body: JSON.stringify({ action: 'outcome', id: envAsk.id }) })).json();
    const envAfter = await page.evaluate(async () => (await (await fetch('/api/devapp', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', instance: 'asked', action: 'env-get' }) })).json()).text);
    ok(envAsk.status === 200 && envOut.state === 'done' && /env written/.test(envOut.out || '')
       && /KEY=changed/.test(envAfter || '') && builds() === b0,
       `...and Allow on an env set writes the env and builds nothing (${envOut.out}, ${builds() - b0} builds)`);
    // ...and on ask, Allow removes it: the card says remove and nothing else.
    const rmAsk = await asSession({ project: 'ep.silon', action: 'remove', instance: 'asked', why: 'done with it' });
    const rmSeen = await page.evaluate(async (id) =>
      ((await (await fetch('/api/phone')).json()).asks || []).find(a => a.id === id), rmAsk.id);
    await page.evaluate(async (id) => {
      await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ action: 'allow', id }) });
    }, rmAsk.id);
    await idle();
    ok(rmAsk.status === 200 && rmAsk.id && /"remove"/.test(JSON.stringify(rmSeen?.cmd)) && !insts().includes('asked'),
       `on ask a remove waits for a person, and Allow removes it (${JSON.stringify(rmSeen?.cmd)}; left: ${insts().join(', ')})`);
    for (const inst of ['fresh', 'asked']) await page.evaluate(async (i) => {
      await fetch('/api/devapp', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                   body: JSON.stringify({ project: 'ep.silon', instance: i, action: 'remove' }) });
    }, inst);
    await dial('auto');
    // A compose asking for more than its own directory is confirmed by a
    // person pressing Build; a session's build follows its project's Run its
    // container setting instead, like every other container (the operator,
    // 26 Sep, after a session on auto was stopped there): auto builds it,
    // and at ask the person's Allow is the confirmation. A person's own
    // rebuild without it is still refused, on its job.
    writeFileSync(`${DIR}/dockerstate/riskynew.config`, JSON.stringify(
      { services: { app: { build: { context: '.' }, privileged: true } } }));
    const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
    const jobEnd = async id => {
      let j = null;
      for (let i = 0; i < 60 && id && !(j && ['failed', 'succeeded', 'canceled'].includes(j.state)); i++){
        await sleep(500);
        j = await (await fetch(URL.replace(/\/$/, '') + '/api/v1/jobs?id=' + id, { headers: H })).json();
      }
      return j || {};
    };
    const rn = await asSession({ project: 'ep.silon', action: 'new', instance: 'riskynew' });
    const rr = await asSession({ project: 'ep.silon', action: 'rebuild', instance: 'riskynew' });
    const rj = await jobEnd(rr.job);
    ok(rn.status === 200 && !rn.needs_ack && rr.status === 200 && rj.state === 'succeeded',
       `on auto a session makes and builds a compose that asks for more than its own directory (${
          rn.error || 'made'}; ${rj.state}: ${String(rj.error || '').slice(0, 80)})`);
    const mine = await page.evaluate(async () => (await (await fetch('/api/devapp', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', instance: 'riskynew', action: 'rebuild', ack: '' }) })).json()));
    const mj = await jobEnd(mine.job);
    ok(mj.state === 'failed' && /Build or Rebuild on its row on the Containers page/.test(mj.error || ''),
       `...while a person's own rebuild without the confirmation is still refused, on its job (${mj.state}: ${
          String(mj.error || '').slice(0, 60)})`);
    await dial('ask');
    const ra = await asSession({ project: 'ep.silon', action: 'rebuild', instance: 'riskynew',
                                 why: 'the privileged one again' });
    await page.evaluate(async (id) => {
      await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ action: 'allow', id }) });
    }, ra.id);
    const out = await (await fetch(URL.replace(/\/$/, '') + '/api/phone', { method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
      body: JSON.stringify({ action: 'outcome', id: ra.id }) })).json();
    const aj = await jobEnd(out.out);
    ok(ra.status === 200 && ra.id && out.state === 'done' && aj.state === 'succeeded',
       `...and at ask the person's Allow is the confirmation: the build it starts goes through (${
          out.state}; ${aj.state}: ${String(aj.error || out.out || '').slice(0, 80)})`);
    await dial('auto');
    await idle();
    await page.evaluate(async () => {
      await fetch('/api/devapp', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                   body: JSON.stringify({ project: 'ep.silon', instance: 'riskynew', action: 'remove' }) });
    });
    await idle();
    rmSync(`${DIR}/dockerstate/riskynew.config`, { force: true });
    // ---- sending it again: another container beside the first (26 Sep) --
    // A session sends its project to Docker the way the Artifacts tab's Send
    // does, and sending again makes another container rather than a refusal
    // naming the first: unnamed, a new one is the project's own while it has
    // none and <project>-2, -3 after, which is also the name Send opens on.
    // On ask a name nothing could make is refused before anybody is asked,
    // the card names the container and the branch it builds from, and Allow
    // makes it, pins it and builds it from there.
    {
      const G = (...a) => execFileSync('git', ['-C', D, ...a], { env, encoding: 'utf8' });
      ok(insts().includes('main'), `the project has its own container to send another beside (${insts().join(', ')})`);
      const second = await asSession({ project: 'ep.silon', action: 'new' });
      const third = await asSession({ project: 'ep.silon', action: 'new' });
      ok(second.status === 200 && second.instance === 'ep-silon-2' && third.instance === 'ep-silon-3',
         `unnamed, a session's new makes another container beside the one it has, then another (${
            second.error || second.instance}, ${third.error || third.instance})`);
      const offered = await page.evaluate(async () =>
        (await (await fetch('/api/artifacts?project=ep.silon')).json()).send_as);
      ok(offered === 'ep-silon-4', `...and Send offers the name after them (${offered})`);
      await dial('ask');
      const taken = await asSession({ project: 'ep.silon', action: 'new', instance: 'ep-silon-2', why: 'another' });
      ok(taken.status === 400 && /already has an instance called ep-silon-2/.test(taken.error || '') && !taken.id,
         `on ask a name that is taken is refused before anybody is asked (${String(taken.error).slice(0, 60)})`);
      G('branch', 'sendbranch');
      const sent = await asSession({ project: 'ep.silon', action: 'new', ref: 'sendbranch',
                                     why: 'the branch beside main' });
      const card = await page.evaluate(async (id) =>
        ((await (await fetch('/api/phone')).json()).asks || []).find(a => a.id === id), sent.id);
      ok(sent.status === 200 && sent.instance === 'ep-silon-4' && sent.name === 'ep-silon-4'
         && JSON.stringify(card?.cmd) === '["devapp","new","ep-silon-4","--branch","sendbranch"]',
         `...and a send's card names the container it makes and its branch (${
            sent.error || sent.instance}: ${JSON.stringify(card?.cmd)})`);
      await page.evaluate(async (id) => {
        await fetch('/api/phone', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ action: 'allow', id }) });
      }, sent.id);
      await idle();
      const made4 = (await asSession({ project: 'ep.silon', instance: 'ep-silon-4', action: 'state' })).state || {};
      ok(made4.ref === 'sendbranch' && made4.built_ref === 'sendbranch',
         `...and Allow makes it, pins it to that branch and builds it from there (${
            JSON.stringify([made4.ref, made4.built_ref])})`);
      await dial('auto');
      for (const i of ['ep-silon-2', 'ep-silon-3', 'ep-silon-4'])
        await asSession({ project: 'ep.silon', instance: i, action: 'remove' });
      await idle();
      try { G('worktree', 'remove', '--force', `${DIR}/ws/ep-silon-ep-silon-4-build`); }
      catch (e) { rmSync(`${DIR}/ws/ep-silon-ep-silon-4-build`, { recursive: true, force: true });
                  try { G('worktree', 'prune'); } catch (e2) { /* nothing to prune */ } }
      G('branch', '-D', 'sendbranch');
    }
  }
  // The setting lives in the project's settings with the other Claude may
  // dials (the operator, 24 Sep), because it covers creating the container,
  // which has to be decidable before there is a row. The row says what it is
  // set to and links there, the way the tests-run line does.
  await dmRefresh();
  await dmEditNone();
  const claudePill = () => [...document.querySelectorAll('.dmtab .row[data-inst^="ep.silon|"] .fpill')].find(p => p.querySelector('.k')?.textContent === 'Claude');
  await page.waitForFunction(cp => /rebuild · env · create/.test((0, eval)(cp)()?.textContent || ''), claudePill.toString(), { timeout: 20000 });
  ok(await page.evaluate(cp => !!(0, eval)(cp)()?.querySelector('[data-dmtestgo="ep.silon"]'), claudePill.toString())
     && await page.$('.dmtab [data-dmclaude]') === null,
     'the docker row says what a session may do with it and links to the setting, carrying no control');
  await page.evaluate(() => renameProject('ep.silon'));
  await page.waitForSelector('#rnmodal:not([hidden]) #rnGateDocker', { timeout: 15000 });
  ok(await page.$eval('#rnGateDocker', e => e.value === 'auto' && !e.closest('label').hidden
                        && [...e.options].map(o => o.value).join() === 'auto,ask,deny'),
     "the project's settings carry it, on auto, with the other Claude may dials");
  // The Claude section holds the test-run setting too (25 Sep): what a
  // change asked for during a run does, saved with the rest of the dialog,
  // under the section's heading since the dialog was put in sections (1 Oct).
  ok(await page.$eval('#rnGateField', e => e.closest('.rngroup').querySelector('summary .t').textContent) === 'Claude may'
     && await page.$eval('#rnGateLabel', e => e.textContent) === 'While a test runs'
     && await page.$eval('#rnTestChange', e => e.value === 'wait' && [...e.options].map(o => o.value).join() === 'wait,restart')
     && await page.$eval('#rnReply', e => e.value === ''),
     'the dialog groups what Claude may do under its Claude may heading, with what a change does during a test run; replies are the person\'s own pick');
  await page.selectOption('#rnTestChange', 'restart');
  await page.selectOption('#rnReply', 'minimal');
  await page.selectOption('#rnAsks', 'fewer');
  await page.selectOption('#rnGateDocker', 'deny');
  await saveDialog(page);
  // Read as the setting, not as the record's absence: a project on a node
  // keeps its record even with every gate at its default (R82).
  await refreshUntil(page, () => ((((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs || {}).devbuild || 'deny') === 'deny', { timeout: 20000 });
  ok((await asSession({ project: 'ep.silon', action: 'rebuild' })).status === 403,
     '...and turning it back to deny there takes the grant back');
  ok(await page.evaluate(() => ((state?.projects || []).find(p => p.name === 'ep.silon') || {}).prefs?.test_change) === 'restart',
     'the test-run setting is saved with it');
  ok(await page.evaluate(() => { const p = (state?.projects || []).find(p => p.name === 'ep.silon') || {};
       return p.yours?.reply === 'minimal' && p.yours?.asks === 'fewer'; }),
     '...and the reply and question styles with the person');
  await page.evaluate(async () => { await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'ep.silon', reply: '', asks: '' }) }); });
  // ---- where the tests run (R48 step 3, moved by R68 step 6) -------------
  // The setting lives with the project's node and test command now, in its
  // settings dialog: it is the project's, and having it here meant somebody
  // setting a project up had to finish on a machine tab. The row still says
  // what it is set to, because this is where a person wonders, and the words
  // link to where it is changed.
  ok(/Tests ?on the node/.test(
       await page.$eval('.dmtab .row[data-inst^="ep.silon|"]', r => r.textContent.replace(/\s+/g, ' '))),
     'the row says where this project\'s tests run, in words: on the node unless the project says otherwise (B241)');
  ok(await page.$('.dmtab [data-dmtestgo="ep.silon"]') !== null
     && await page.$('.dmtab [data-dmtest="ep.silon"]') === null,
     '...and links to the project settings rather than carrying the control');
  // ...and the control is there, offered only where there is a container to
  // run in: a project with no compose file is not asked the question.
  await page.evaluate(() => { openProjectsTab(); });
  await page.evaluate(n => renameProject(n), 'ep.silon');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  ok(await page.$eval('#rnTestWhere', e => !e.hidden)
     && await page.$eval('#rnDevTest', e => [...e.options].map(o => o.value).join() === 'node,up,only'
                                          && e.value === 'node'),
     'the project settings dialog carries where its tests run, beside its node and command');
  await page.selectOption('#rnDevTest', 'only');
  await saveDialog(page);
  await refreshUntil(page, () => ((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.tests_in === 'only', { timeout: 20000 });
  ok(JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects['ep.silon'].tests_in === 'only',
     '...and saving it there is what writes the setting');
  await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  ok(await page.$eval('#rnTestWhere', e => e.hidden),
     '...while a project with no compose file is not asked the question at all');
  await page.evaluate(() => { document.querySelectorAll('.modal').forEach(m => { m.hidden = true; }); openDocker(); });
  await page.waitForSelector('.dmtab', { timeout: 15000 });

  // Opening is one ask (B210). show() ran a kind's open hook after the draw
  // had run it, and openDocker() loaded on top of both: three listings of
  // one daemon for one press, each a set of reads on the node, and the tab
  // visibly refreshing three times before it settled. The fetches all fire
  // inside the call itself, so they are counted the moment it returns.
  {
    // Not while the open above still has an answer on its way: an ask in
    // flight is the one case a second open rightly does not add to.
    await page.waitForFunction(() => !dockerFetching, null, { timeout: 15000 });
    const counts = await page.evaluate(() => {
      const f = window.fetch; const seen = { docker: 0, nodes: 0 };
      window.fetch = (...a) => { const u = String(a[0]);
        if (u.startsWith('/api/docker')) seen.docker++;
        if (u.startsWith('/api/v1/nodes')) seen.nodes++; return f(...a); };
      dockerList = null; dockerRev++;
      openDocker();
      const docker = seen.docker;
      const hadNodes = tabs.some(t => t.kind === 'nodes');
      openTab({ kind: 'nodes', arg: '__nodes', label: 'Nodes' });
      const nodes = seen.nodes;
      window.fetch = f;
      if (!hadNodes) dropTab(tabs.find(t => t.kind === 'nodes').id);
      openDocker();
      return { docker, nodes };
    });
    ok(counts.docker === 1, `opening the Containers page asks for its listing once (${counts.docker})`);
    ok(counts.nodes === 1, `...and opening the Nodes page asks for the node list once (${counts.nodes})`);
    await page.waitForSelector('.dmtab', { timeout: 15000 });
    // ...and a heartbeat is not a repaint: the node list moves with every
    // one, and the tab is keyed on the rows its picker draws, not on that.
    const keyed = await page.evaluate(() => {
      const n = (nodesList || []).find(x => x.kind !== 'local');
      if (!n) return { none: true };
      const before = TABKINDS.docker.live();
      const was = n.reported;
      n.reported = { sample: { cpu_pct: 99, mem_used_mb: 1, mem_mb: 2 } };
      nodesRev++;
      const numbers = TABKINDS.docker.live() === before;
      const st = n.state; n.state = st + '-moved';
      const state = TABKINDS.docker.live() !== before;
      n.state = st; n.reported = was;
      return { numbers, state };
    });
    ok(!keyed.none && keyed.numbers, "a heartbeat's numbers moving does not repaint the Containers page");
    ok(keyed.state, '...while a node changing state does');
  }
  const where = v => page.evaluate(async (w) => {
    const r = await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                          body: JSON.stringify({ project: 'ep.silon', tests_in: w }) });
    return r.json();
  }, v);
  const stored = () => JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects['ep.silon'] || {};
  await where('only');
  await refreshUntil(page, () => ((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.tests_in === 'only', { timeout: 20000 });
  ok(stored().tests_in === 'only' && !('devtest' in stored()),
     'only is stored as tests_in, and nothing else');
  await page.evaluate(() => { dockerList = null; loadDocker(); });
  await page.waitForFunction(() => /in its container only/.test(
    document.querySelector('.dmtab')?.textContent || ''), null, { timeout: 20000 });
  ok(true, '...and the row says the other thing once it is set');
  await where('up');
  await refreshUntil(page, () => ((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.tests_in === 'up', { timeout: 20000 });
  ok(stored().tests_in === 'up' && !('devtest' in stored()),
     '...and so is up');
  await where('node');
  // A project left with nothing but defaults has no record at all, and the
  // poll then carries {} for its prefs, which the page reads as the default.
  await refreshUntil(page, () => (((state.projects || [])
    .find(p => p.name === 'ep.silon') || {}).prefs?.tests_in || 'node') === 'node', { timeout: 20000 });
  ok(!('devtest' in stored()) && !('tests_in' in stored()),
     '...and the default, on the node, leaves neither in the record');
  ok(/tests_in is one of node, up, only/.test((await where('sometimes')).error || ''),
     '...and a place that is not one of the three is refused');
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
  ok(/exec -T -e BB_TEST_TIMING=1 -e BB_IN_INSTANCE=1 -e BB_TEST_WORKERS app sh -c printf/.test(j1.log || ''),
     '...through compose exec into the service the project builds, with timing on for the registry, and no working directory when nothing mounts the project');
  // A compose that mounts the project (or the whole share it sits in) puts
  // the tests in the project's directory inside the container: the first
  // run of BuilderBot's own suite inside its instance ran at / instead.
  writeFileSync(stubCfg, JSON.stringify({ services: { app: { build: { context: '.' },
    volumes: [{ type: 'bind', source: `${DIR}/ws`, target: '/workspace' }] } } }));
  const j1b = await finished((await asSession({ project: 'ep.silon', action: 'test', args: ['wd'] })).job);
  ok(/exec -T -e BB_TEST_TIMING=1 -e BB_IN_INSTANCE=1 -e BB_TEST_WORKERS -w \/workspace\/ep\.silon app sh -c/.test(j1b.log || ''),
     `...and in the project's directory inside the container when the compose mounts it (${(j1b.log || '').match(/exec [^\n]*/)?.[0]?.slice(0, 90)})`);
  // BB_IN_INSTANCE is how run.sh tells "these tests ARE the container's" from
  // "these tests were run around it": a dev instance is a container and so is
  // the controller, so the suite cannot work it out for itself, and without it
  // the container-only setting could only be enforced by asking nicely (R65).
  ok(/-e BB_IN_INSTANCE=1/.test(j1.log || '') && /-e BB_IN_INSTANCE=1/.test(j1b.log || ''),
     '...carrying the mark that says this run is the instance\'s own');
  rmSync(stubCfg, { force: true });
  // Where bb test runs, from a session on the node, with the instance UP
  // (B241): on the node by default, never asking about the container, since
  // an image built to ship carries no tests and a run inside one found none
  // and passed; inside it only where the project says so.
  {
    const nodeEnv = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                      BB_TOKEN: tok, BB_NODE: 'agentbox', BB_PROJECT: 'ep.silon',
                      BB_TREE: '/workspace/ep.silon' };
    const { spawnSync } = await import('node:child_process');
    // Both streams: where bb test says it runs is on stderr, the tests' own
    // output on stdout.
    const bbTest = () => {
      const r = spawnSync('bash', [`${REPO}/scripts/bb`, 'test', 'where'],
        { encoding: 'utf8', cwd: `${DIR}/ws/ep.silon`, env: nodeEnv, timeout: 120000 });
      return { code: r.status, out: String(r.stdout || '') + String(r.stderr || '') };
    };
    await page.evaluate(async () => fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', tests_in: 'node' }) }));
    const onNode = bbTest();
    ok(onNode.code === 0 && /TEST-RAN-where/.test(onNode.out) && !/run inside it/.test(onNode.out)
       && /tests run on the node, as its settings say \(Tests run\)/.test(onNode.out),
       `by default bb test runs on the node with the instance up, and says why there (${
         onNode.out.replace(/\s+/g, ' ').slice(0, 140)})`);
    await page.evaluate(async () => fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', tests_in: 'up' }) }));
    const inside = bbTest();
    ok(inside.code === 0 && /the tests run inside it, as its settings say/.test(inside.out)
       && /TEST-RAN-where/.test(inside.out),
       `...and inside the instance where the project says up (${inside.out.replace(/\s+/g, ' ').slice(0, 140)})`);
    await page.evaluate(async () => fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'ep.silon', tests_in: 'node' }) }));
  }
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
  ok(down.status === 400 && /is not running: Up on the Containers page/.test(down.error || ''),
     `a container that is down is said so and never started behind the operator's back (${down.error})`);
  // The refusal that makes the container the only way (step 3): from a
  // session on a node, with the row set to `only` and the instance down,
  // bb test names the instance and runs nothing on the node. With the row
  // on `either` the same call would queue a job on the node, which the
  // fixture has none of, so that half is the routing step 1 already proves.
  {
    const setWhere = (w) => page.evaluate(async (v) => {
      await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ project: 'ep.silon', tests_in: v }) });
    }, w);
    await setWhere('only');
    const nodeEnv = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                      BB_TOKEN: tok, BB_NODE: 'agentbox', BB_PROJECT: 'ep.silon',
                      BB_TREE: '/workspace/ep.silon' };
    let out = '', code = 0;
    try {
      out = execFileSync('bash', [`${REPO}/scripts/bb`, 'test'],
        { encoding: 'utf8', cwd: `${DIR}/ws/ep.silon`, env: nodeEnv, stdio: ['ignore', 'pipe', 'pipe'] });
    } catch (e) { code = e.status; out = String(e.stderr || '') + String(e.stdout || ''); }
    ok(code !== 0 && /tests run only inside its dev instance \(ep-silon\), which is not running: Up on the Containers page/.test(out)
       && /Nothing runs on the node/.test(out),
       `with the row on only and the instance down, bb test from a session refuses, naming the instance (${
         code}: ${out.replace(/\s+/g, ' ').slice(0, 120)})`);
    await setWhere('node');
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

// ---- the project a container belongs to (the operator, 24 Sep) -------------
// Every row belongs to one project or to none. The manager is grouped that
// way, alphabetically with none last; the project's notebook lists what
// belongs to it; and that project's sessions are the only ones that can see
// a row or work on it, under its Run its container setting.
{
  const api = (path, body) => page.evaluate(async ([p, b]) => {
    const r = await fetch(p, b ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                   body: JSON.stringify(b) } : {});
    return { status: r.status, ...(await r.json()) };
  }, [path, body]);
  const made = await api('/api/container', { action: 'create', name: 'helper-for-eps', owner: 'ep.silon',
                                            compose: 'services:\n  app:\n    image: alpine\n', env: '' });
  ok(made.ok && made.project === 'helper-for-eps',
     `a container written here can be made for a project (${JSON.stringify(made).slice(0, 80)})`);
  const bad = await api('/api/container', { action: 'create', name: 'helper-for-nobody', owner: 'no-such-project',
                                           compose: 'services:\n  app:\n    image: alpine\n', env: '' });
  ok(/not a project: no-such-project/.test(bad.error || ''), 'a project nobody can see is refused');
  // Sent with "no project" picked, a project's own container belongs to none,
  // which is not the same as sending it with nothing said.
  const loose = await api('/api/devapp', { project: 'ep.silon', action: 'new', instance: 'loose', owner: '' });
  const listed = await api('/api/docker');
  const row = (p, i) => (listed.instances || []).find(d => d.project === p && d.instance === i) || {};
  ok(loose.ok && row('helper-for-eps', 'main').owner === 'ep.silon' && row('ep.silon', 'main').owner === 'ep.silon'
     && row('ep.silon', 'loose').owner === ''
     && (listed.containers || []).find(c => c.name === 'someone-elses')?.owner === '',
     `the manager's answer says whose each row is: a written one its pick, a project's its own unless sent with no project, another's nobody's (${
       JSON.stringify((listed.instances || []).map(d => [d.name, d.owner]))})`);

  // ---- a project's own container moved to another project (8 Oct) ------------
  // Rekeyed under the other project with the name it had, so its env and
  // data stay; a person's on the Docker tab, never a session's. The two it
  // moves between share ep.silon's node, as a container's project must.
  const epNode = (await api('/api/status')).projects.find(p => p.name === 'ep.silon')?.prefs?.node || '';
  for (const p of ['alpha', 'gamma']) await api('/api/prefs', { project: p, node: epNode, nodes: epNode ? [epNode] : [] });
  writeFileSync(`${DIR}/ws/alpha/docker-compose.yml`, 'services:\n  app:\n    image: alpha-dev\n');
  const nowhere = await api('/api/devapp', { project: 'ep.silon', action: 'move', instance: 'loose', to: 'no-such' });
  ok(nowhere.status === 400 && /no project called no-such/.test(nowhere.error || ''), `a move names a project there is (${nowhere.error})`);
  const moveTok = execFileSync('bash', [fileURLToPath(new globalThis.URL('../../bb', import.meta.url)), 'users', 'token', 'ep.silon', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
  const bySess = await fetch(URL.replace(/\/$/, '') + '/api/devapp', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + moveTok },
    body: JSON.stringify({ project: 'ep.silon', action: 'move', instance: 'main', to: 'alpha' }) })
    .then(async r => ({ status: r.status, ...(await r.json()) }));
  ok(bySess.status === 403 && !(await api('/api/docker')).instances.some(d => d.project === 'alpha'),
     `...and is never a session's (${bySess.error})`);
  const moved = await api('/api/devapp', { project: 'ep.silon', action: 'move', instance: 'loose', to: 'alpha' });
  const after = await api('/api/docker');
  const movedRow = (after.instances || []).find(d => d.project === 'alpha' && d.instance === 'loose');
  ok(moved.ok && movedRow && movedRow.name === 'loose'
     && !(after.instances || []).some(d => d.project === 'ep.silon' && d.instance === 'loose'),
     `Move puts it under alpha with the name it had (${JSON.stringify(moved).slice(0, 160)})`);
  const back = await api('/api/devapp', { project: 'alpha', action: 'move', instance: 'loose', to: 'ep.silon' });
  ok(back.ok, `...and back again (${back.error || 'ok'})`);
  rmSync(`${DIR}/ws/alpha/docker-compose.yml`, { force: true });
  // A deleted project's containers keep its name, drawn "X (deleted)", and
  // come back with it from the trash (8 Oct).
  const zc = await api('/api/container', { action: 'create', name: 'helper-for-gamma', owner: 'gamma',
                                          compose: 'services:\n  app:\n    image: alpine\n', env: '' });
  const zrow = l => (l.instances || []).find(d => d.project === 'helper-for-gamma') || {};
  const gone1 = await api('/api/trash', { name: 'gamma' });
  const whileGone = await api('/api/docker');
  ok(zc.ok && gone1.ok && zrow(whileGone).owner === 'gamma' && zrow(whileGone).owner_gone === true,
     `a deleted project's container is still its, marked gone (${JSON.stringify(zrow(whileGone)).slice(0, 120)} ${zc.error || gone1.error || ''})`);
  await openManager();
  await page.waitForFunction(() => [...document.querySelectorAll('.dmgroup b')].some(b => b.textContent === 'gamma (deleted)'));
  ok(true, '...drawn under "gamma (deleted)" on the Containers page');
  const back2 = await api('/api/trash-restore', { name: (gone1.to || '').split('/').pop() });
  ok(back2.ok && zrow(await api('/api/docker')).owner_gone === false, `...and a restore gives it back (${back2.error || 'ok'})`);
  await api('/api/devapp', { project: 'helper-for-gamma', action: 'remove' });
  for (const p of ['alpha', 'gamma']) await api('/api/prefs', { project: p, node: '', nodes: [] });

  // ---- the manager, grouped by project ---------------------------------------
  await openManager();
  const groups = () => page.evaluate(() => {
    const out = []; let cur = null;
    for (const el of document.querySelectorAll('.dmtab .dmgroup, .dmtab .row[data-inst], .dmtab .row[data-ctr]')) {
      if (el.classList.contains('dmgroup')) out.push(cur = { head: el.querySelector('b').textContent, rows: [] });
      else if (cur) cur.rows.push(el.dataset.inst || el.dataset.ctr);
    }
    return out;
  });
  await page.waitForFunction(() => document.querySelector('.dmtab .row[data-inst="helper-for-eps|main"]')
                                   && document.querySelector('.dmtab .row[data-inst="ep.silon|loose"]'),
                             null, { timeout: 20000 });
  let g = await groups();
  const heads = g.map(x => x.head);
  const named = heads.filter(h => h !== 'No project');
  ok(heads[heads.length - 1] === 'No project'
     && JSON.stringify(named) === JSON.stringify([...named].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))),
     `the manager groups rows by project, alphabetically, with no project last (${heads.join(' | ')})`);
  // Each heading is a band that stands out from the rows under it (the
  // operator, 24 Sep): tinted and barred down its left, in the project's
  // own color when it has one, and plain for No project.
  const bands = () => page.$$eval('.dmtab .dmgroup', hs => hs.map(h => ({
    head: h.querySelector('b')?.textContent, none: h.classList.contains('none'),
    bg: getComputedStyle(h).backgroundColor, bar: getComputedStyle(h).boxShadow })));
  let b = await bands();
  const eps = b.find(x => x.head === 'ep.silon');
  ok(eps && !/rgba\(0, 0, 0, 0\)/.test(eps.bg) && /inset/.test(eps.bar) && b.find(x => x.head === 'No project')?.none,
     `a project's heading is a tinted band with a bar down its left, and No project is marked plain (${JSON.stringify(eps)})`);
  await api('/api/project-color', { name: 'ep.silon', color: 'teal' });
  await refreshUntil(page, () => (state.projects || []).find(p => p.name === 'ep.silon')?.color === 'teal',
                     { timeout: 20000 });
  await page.evaluate(() => { dockerRev++; drawPanes(); });
  await page.waitForFunction(() => /57, 181, 176/.test(getComputedStyle(
    [...document.querySelectorAll('.dmtab .dmgroup')].find(h => h.querySelector('b')?.textContent === 'ep.silon')).boxShadow),
    null, { timeout: 10000 }).catch(() => {});
  b = await bands();
  ok(/57, 181, 176/.test(b.find(x => x.head === 'ep.silon')?.bar || ''),
     `...in the project's own color once it has one (${b.find(x => x.head === 'ep.silon')?.bar})`);
  await api('/api/prefs', { project: 'ep.silon', color: '' });
  const under = h => (g.find(x => x.head === h) || { rows: [] }).rows;
  ok(under('ep.silon').includes('ep.silon|main') && under('ep.silon').includes('helper-for-eps|main')
     && under('No project').includes('ep.silon|loose') && under('No project').includes('someone-elses'),
     `...a project's own container and one written for it together, and the rest under No project (${
       JSON.stringify(g)})`);
  // ...and the project is a setting on the row, staged and applied.
  const R = '.dmtab .row[data-ctr="someone-elses"]';
  await dmEditAll(R);
  await page.waitForSelector(`${R} [data-dmapply]`, { timeout: 15000 });
  ok(await page.$eval(`${R} [data-dmapply]`, b => b.disabled)
     && await page.$eval(`${R} [data-dmown]`, e => e.value === '' && [...e.options].some(o => o.value === 'ep.silon')),
     'a container somebody else started carries a Project setting, on no project, with Apply asleep');
  await page.selectOption(`${R} [data-dmown]`, 'ep.silon');
  ok(!await page.$eval(`${R} [data-dmapply]`, b => b.disabled), '...which a pick wakes');
  await page.click(`${R} [data-dmapply]`);
  await page.waitForFunction(() => {
    const row = document.querySelector('.dmtab .row[data-ctr="someone-elses"]');
    const heads = [...document.querySelectorAll('.dmtab .dmgroup')]
      .filter(h => row && (h.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING));
    return heads.pop()?.querySelector('b')?.textContent === 'ep.silon';
  }, null, { timeout: 20000 });
  // Its Claude pill says what the project's sessions may do with it (the
  // operator's concept, 17 Oct: settings read as pills).
  ok(/Claude\s*(start · stop|asks first|reads its log)/.test(await page.$eval(R, r => r.textContent)),
     "...and Apply moves it under that project, saying what the project's sessions may do with it");
  ok(JSON.parse(readFileSync(`${DIR}/state/docker-owners.json`, 'utf8'))
       && Object.values(JSON.parse(readFileSync(`${DIR}/state/docker-owners.json`, 'utf8')))
         .some(n => n['someone-elses'] === 'ep.silon'),
     '...kept by its name on its node, so the same container recreated keeps it');

  // ---- the project's notebook lists what belongs to it -------------------------
  await page.evaluate(() => openNotebook('ep.silon'));
  await nbShown(page);
  await nbTab(page, 'docker');
  await page.waitForFunction(() => document.querySelector('.pane .nb #dkList .row[data-inst="helper-for-eps|main"]')
                                   && document.querySelector('.pane .nb #dkList .row[data-ctr="someone-elses"]'),
                             null, { timeout: 20000 });
  const view = await page.$eval('.pane .nb [data-view="docker"]', v => ({
    hint: v.querySelector('#dkHint').textContent,
    rows: [...v.querySelectorAll('#dkList .row[data-inst], #dkList .row[data-ctr]')].map(r => r.dataset.inst || r.dataset.ctr),
    buttons: [...v.querySelectorAll('#dkList .row[data-inst="helper-for-eps|main"] [data-dm]')].map(b => b.dataset.dm) }));
  ok(view.rows.includes('helper-for-eps|main') && view.rows.includes('ep.silon|main')
     && view.rows.includes('someone-elses') && !view.rows.includes('ep.silon|loose'),
     `the project's Docker view lists what belongs to it, and not its own container sent to no project (${view.rows.join(' ')})`);
  ok(view.buttons.includes('up') && view.buttons.includes('rebuild'),
     `...with the manager's own rows and controls (${view.buttons.join(' ')})`);
  ok(/3 containers of ep\.silon's on/.test(view.hint), `...and a line counting them (${view.hint.slice(0, 80)})`);
  // Idle, the view re-reads nothing (B727): it followed the status poll, and
  // on an agent node each docker read moved the nodes token, which ran the
  // status poll, which read docker again, 134 requests in 30 s.
  await page.evaluate(() => { window.__dk = 0; const real = window.fetch;
    window.fetch = function(u, ...a){ if (String(u).startsWith('/api/docker')) window.__dk++; return real.call(this, u, ...a); }; });
  await page.waitForTimeout(8000);
  const dkIdle = await page.evaluate(() => window.__dk);
  // At most one: the manager's token may move once in the window (a job from
  // the checks above ending), and that one read is the re-read wanted.
  ok(dkIdle <= 1, `the project's Docker view, left alone for 8 s, reads the manager ${dkIdle} time${dkIdle === 1 ? '' : 's'} (at most 1: it re-reads on the devapp token, never on the status poll)`);

  // ---- what its session can reach ------------------------------------------------
  const tok = execFileSync('bash', [`${fileURLToPath(new globalThis.URL('../../../', import.meta.url))}scripts/bb`,
                                    'users', 'token', 'ep.silon', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
  const as = async (path, body) => {
    const r = await fetch(URL.replace(/\/$/, '') + path, body
      ? { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
          body: JSON.stringify(body) }
      : { headers: { Authorization: 'Bearer ' + tok } });
    return { status: r.status, ...(await r.json().catch(() => ({}))) };
  };
  const dial = m => api('/api/prefs', { project: 'ep.silon', devbuild: m });
  const seen = await as('/api/docker');
  ok((seen.instances || []).length > 0 && (seen.instances || []).every(d => d.owner === 'ep.silon')
     && (seen.instances || []).some(d => d.name === 'helper-for-eps')
     && !(seen.instances || []).some(d => d.instance === 'loose')
     && JSON.stringify((seen.containers || []).map(c => c.name)) === '["someone-elses"]'
     && JSON.stringify(seen.refs) === '{}',
     `a session lists only what belongs to its project, on its node (${JSON.stringify([
       (seen.instances || []).map(d => d.name), (seen.containers || []).map(c => c.name)])})`);
  // Anybody else naming the project reads the same node (bb devapp ls outside a session).
  const byProject = await api('/api/docker?project=ep.silon');
  const noProject = await api('/api/docker?project=no-such-project');
  ok(byProject.node === seen.node && noProject.status === 400,
     `naming the project reads its node, as its session does, and a project that is not one is refused (${
       byProject.node} ${seen.node} ${noProject.status})`);
  const st = await as('/api/devapp', { container: 'helper-for-eps', action: 'state' });
  // A written container has no repository: its row asks no git about a
  // directory that is not there, which warned on every poll (B596).
  const gitWarned = readFileSync(`${DIR}/server.log`, 'utf8').split('\n')
    .filter(l => /git -C \S*\/helper-for-eps/.test(l));
  ok(gitWarned.length === 0, `a written container's row runs no git where it has no tree (${gitWarned.length}: ${gitWarned[0] || ''})`);
  const theirs = await as('/api/devapp', { project: 'ep.silon', instance: 'loose', action: 'state' });
  ok(st.status === 200 && theirs.status === 403 && /does not belong to ep\.silon/.test(theirs.error || ''),
     `...reads one written for it by name, and not its own project's container sent to no project (${st.status}, ${theirs.error})`);
  const log = await as('/api/dockerctl', { action: 'logs', container: 'someone-elses' });
  ok(/hello from someone-elses/.test(log.text || ''), `...reads the log of one somebody else started, put under it (${log.status})`);
  // ...and one of its own by the name bb devapp ls prints, which is the
  // compose name: its containers are named for it and its services, and
  // looked up by container name alone the name found nothing and the
  // project's own instance was refused to its session as not its own, its
  // log with it (B307). The log is each service's, under its name.
  const bare = await as('/api/dockerctl', { action: 'logs', container: 'helper-for-eps' });
  ok(bare.status === 400 && /has no containers on its node now/.test(bare.error || ''),
     `one of its own with nothing running under it is said as that, not refused as a stranger's (${
        bare.status}: ${String(bare.error).slice(0, 50)})`);
  const wasUp = existsSync(`${DIR}/dockerstate/helper-for-eps.up`);
  writeFileSync(`${DIR}/dockerstate/helper-for-eps.up`, '');
  // Read once the node is idle: while a job runs there, a listing is
  // answered from the last one kept, which predates the mark just written.
  await idle();
  // ...and asked again for a while: a job that started meanwhile (another
  // check's, a poll's probe) answers from the listing kept before the mark,
  // which says nothing is running there yet (B620).
  let own = await as('/api/dockerctl', { action: 'logs', container: 'helper-for-eps' });
  for (let i = 0; i < 20 && own.status !== 200; i++) {
    await sleep(500);
    own = await as('/api/dockerctl', { action: 'logs', container: 'helper-for-eps' });
  }
  ok(own.status === 200 && /hello from helper-for-eps-app-1/.test(own.text || ''),
     `...and the log of its own container by the name ls prints, which is its services' (${own.status}: ${
        String(own.error || own.text).trim().slice(0, 60)})`);
  // ...and by the name its compose file gives the service, which is the
  // name a session reaches for: `bb devapp log app` (report #97, B591).
  const bySvc = await as('/api/dockerctl', { action: 'logs', container: 'app' });
  ok(bySvc.status === 200 && /hello from helper-for-eps-app-1/.test(bySvc.text || ''),
     `...and by its service's own name, as the compose file calls it (${bySvc.status}: ${
        String(bySvc.error || bySvc.text).trim().slice(0, 60)})`);
  await dial('auto');
  const ctlWas = readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8').length;
  const ownRestart = await as('/api/dockerctl', { action: 'restart', container: 'helper-for-eps' });
  ok(ownRestart.ok && readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8').slice(ctlWas).includes('helper-for-eps-app-1'),
     `...and restarts it by that name, which restarts its services (${JSON.stringify(ownRestart).slice(0, 70)})`);
  if (!wasUp) rmSync(`${DIR}/dockerstate/helper-for-eps.up`, { force: true });
  await dial('deny');
  const denied = await as('/api/dockerctl', { action: 'restart', container: 'someone-elses' });
  ok(denied.status === 403 && /Claude may: Run its container/.test(denied.error || ''),
     `...and on deny may not restart it, told where the setting is (${String(denied.error).slice(0, 60)})`);
  await dial('auto');
  const was = readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8').length;
  const restarted = await as('/api/dockerctl', { action: 'restart', container: 'someone-elses' });
  ok(restarted.ok && readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8').slice(was).includes('someone-elses'),
     `...on auto restarts it (${JSON.stringify(restarted).slice(0, 60)})`);
  await dial('ask');
  const asked = await as('/api/dockerctl', { action: 'stop', container: 'someone-elses', why: 'it holds the port' });
  const pending = ((await api('/api/phone')).asks || []).find(a => a.id === asked.id);
  ok(asked.id && pending?.ctl === 'stop' && pending.cmd.join(' ') === 'devapp stop someone-elses',
     `...and on ask puts the stop in front of a person (${JSON.stringify(pending?.cmd)})`);
  const before = readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8').length;
  await api('/api/phone', { action: 'allow', id: asked.id });
  const out = await as('/api/phone', { action: 'outcome', id: asked.id });
  ok(out.state === 'done' && !out.code && readFileSync(`${DIR}/dockerstate/ctl.log`, 'utf8').slice(before).includes('someone-elses'),
     `...and Allow stops it, the outcome going back to the session (${JSON.stringify(out).slice(0, 70)})`);
  // bb devapp ls, as a session runs it.
  const cache = `${DIR}/cache-owners`;
  const ls = execFileSync('bash', [`${fileURLToPath(new globalThis.URL('../../../', import.meta.url))}scripts/bb`, 'devapp', 'ls'],
    { encoding: 'utf8', env: { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                               BB_TOKEN: tok, BB_PROJECT: 'ep.silon', XDG_CACHE_HOME: cache },
      stdio: ['ignore', 'pipe', 'pipe'] });
  ok(/helper-for-eps\s+written here/.test(ls) && /someone-elses\s+not ours/.test(ls) && !/loose/.test(ls),
     `bb devapp ls lists what belongs to the project and nothing else (${ls.trim().replace(/\s+/g, ' ').slice(0, 120)})`);
  // Put back under nobody, and the session loses it at once.
  await api('/api/dockerctl', { action: 'owner', container: 'someone-elses', owner: '' });
  await api('/api/devapp', { project: 'helper-for-eps', instance: 'main', action: 'owner', owner: '' });
  const gone = await as('/api/dockerctl', { action: 'logs', container: 'someone-elses' });
  const gone2 = await as('/api/devapp', { container: 'helper-for-eps', action: 'state' });
  ok(gone.status === 403 && gone2.status === 403 && !/someone-elses|helper-for-eps/.test(
       JSON.stringify(await as('/api/docker'))),
     `...and one put under no project is out of its reach and off its list (${gone.status}, ${gone2.status})`);
  const nope = await api('/api/dockerctl', { action: 'owner', container: 'someone-elses', owner: 'no-such-project' });
  ok(nope.status === 400 && /no project called/.test(nope.error || ''), `a project that does not exist is refused (${nope.error})`);
  await dial('deny');
  for (const [p, i] of [['helper-for-eps', 'main'], ['ep.silon', 'loose']])
    await api('/api/devapp', { project: p, instance: i, action: 'remove' });
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

// ---- what a container belongs to ---------------------------------------------
// owner_of reads `for` by presence: none means the default (the project it is
// built from, or no project for a written one), and an empty one is none on
// purpose. A rename moves nothing (R154): the directory is the key.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
def wj(p, o):
    with open(p, 'w') as f:
        json.dump(o, f)
m.configure(workspace='/tmp', state=d, write_json=wj)
wj(d + '/devapps.json', {'media': {'main': {}, 'loose': {'for': ''}},
                         'radarr': {'main': {'source': 'file', 'for': 'media'}},
                         'scratch': {'main': {'source': 'file'}}})
wj(d + '/docker-owners.json', {'n1': {'plex': 'media', 'other': 'alpha'}})
before = [m.owner_of('media'), m.owner_of('media', 'loose'), m.owner_of('radarr'), m.owner_of('scratch')]
print(json.dumps({'before': before}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(JSON.stringify(R.before) === JSON.stringify(['media', '', 'media', '']),
     `a container belongs to its project by default, to none when sent to none, and to its pick when written here (${R.before})`);
}

// ---- a container compose refuses never reaches the list (B239) ----------------
// New container registers the record before compose reads the file, since
// the check finds the file through it; a listing in that window drew a row
// for a container that was then refused. It is not listed until compose has
// read it.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, sys, tempfile
spec = importlib.util.spec_from_file_location('d', ${
  JSON.stringify(new globalThis.URL('../devapp.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
# containers.py reads the store through import devapp: the copy loaded
# above is registered under that name so both see one configure().
sys.modules['devapp'] = m
cspec = importlib.util.spec_from_file_location('c', ${
  JSON.stringify(new globalThis.URL('../containers.py', import.meta.url).pathname)})
c = importlib.util.module_from_spec(cspec); cspec.loader.exec_module(c)
d = tempfile.mkdtemp()
def wj(p, o):
    with open(p, 'w') as f:
        json.dump(o, f)
m.configure(workspace=d, state=d, write_json=wj)
m.available_cached = lambda: {'on': False, 'why': 'no daemon here'}
m.latest_job = lambda: None
m.source = lambda: {}
seen = {'during': []}
def fake_run(argv, timeout=60, **k):
    if 'config' in argv and '-q' in argv:
        seen['during'].append([i['name'] for i in m._overview_here('')['instances']])
        return {'code': seen.pop('fail', 0), 'out': 'yaml: line 2: bad'}
    return {'code': 0, 'out': ''}
m._run = fake_run
seen['fail'] = 1
bad = c.create_container('probecase', 'services:\\n  app:\\n    image: x\\n')
after_bad = [i['name'] for i in m._overview_here('')['instances']]
good = c.create_container('probecase', 'services:\\n  app:\\n    image: x\\n')
print(json.dumps({'bad': bool(bad.get('error')), 'good': bool(good.get('ok')), 'during': seen['during'],
                  'after_bad': after_bad, 'after_good': [i['name'] for i in m._overview_here('')['instances']]}))
`], { encoding: 'utf8' });
  const R = JSON.parse(out.trim().split('\n').pop());
  ok(R.bad && R.good && JSON.stringify(R.during) === '[[],[]]' && JSON.stringify(R.after_bad) === '[]',
     `a container is not listed while compose reads it, and one it refuses never is (${JSON.stringify(R)})`);
  ok(JSON.stringify(R.after_good) === '["probecase"]', '...while one it reads is listed once it has');
}

// A one-shot service that ran and exited 0 is finished, not down: the row
// says running and the chip says finished, while a service that exited
// non-zero still makes the row partly up (B147). Drawn against a listing
// read with the node idle: dmRowsHtml wears the page's own listing's
// staleness, and the restart a block above sends as a job left the kept
// one marked stale, so the row read "(running, as last seen)" (B303).
{
  await idle();
  await page.evaluate(async () => { dockerList = null; await loadDocker(); });
  const row = svc => ({ project: 'delta', instance: 'delta-dev', name: 'delta-dev', running: true, exists: true,
    source: 'project', ports: [], services: [
      { service: 'app', name: 'app', state: 'running', status: 'Up 5 hours (healthy)' },
      { service: 'db', name: 'db', state: 'running', status: 'Up 5 hours (healthy)' }, svc] });
  const draw = async svc => page.evaluate(r => { const el = document.createElement('div');
    el.innerHTML = dmRowsHtml([r], null, false); return el.textContent.replace(/\s+/g, ' '); }, row(svc));
  const seeded = await draw({ service: 'seed', name: 'seed', state: 'exited', status: 'Exited (0) 5 hours ago' });
  const broken = await draw({ service: 'seed', name: 'seed', state: 'exited', status: 'Exited (1) 5 hours ago' });
  // The pill may carry ", as last seen" when the daemon's answer is slow
  // under load (B346); the check is about the one-shot's words, not that.
  // The state is a pill on the name line, read on its own (R210).
  const pillOf = async svc => page.evaluate(r => { const el = document.createElement('div');
    el.innerHTML = dmRowsHtml([r], null, false); return el.querySelector('.dmpill')?.textContent.trim(); }, row(svc));
  const seededPill = await pillOf({ service: 'seed', name: 'seed', state: 'exited', status: 'Exited (0) 5 hours ago' });
  // Its two containers say healthy, so the row does too (R216), rather
  // than running: the one-shot that finished does not count against it.
  ok(/^healthy(, as last seen)?$/.test(seededPill) && !/partly up/.test(seeded) && /seed finished/.test(seeded) && /partly up: 2 of 3/.test(broken),
     `a one-shot that exited 0 leaves the row healthy and reads finished, while one that failed still reads partly up (${
       seededPill} | ${(broken.match(/partly up: \d of \d/) || [''])[0]})`);
}

// ---- where a new container goes: one of its project's nodes -------------
// A project works on a set of nodes (R82), and a container of it lives on
// one of them and nowhere else, since a session reaches only its own
// project's containers on its own node (R79). The pickers offer the set with
// the primary picked, a node outside it is refused, a project with no node
// has nowhere to send, and a container given to a project that does not
// work on its node is refused. A second node is enrolled here so there is a
// set to have; it reports no docker, so the Docker tab's first pick (the
// node most projects use, else the one that runs docker) stays the sandbox.
{
  const base = URL.replace(/\/$/, '');
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
              'Content-Type': 'application/json' };
  const post = async (path, body, headers = H) => (await fetch(base + path,
    { method: 'POST', headers, body: JSON.stringify(body) })).json();
  // The compose fixture, put back for this block: the suite tidied it away
  // above, and a project with none has no container to send.
  writeFileSync(`${D}/docker-compose.yml`, 'services:\n  app:\n    image: delta-dev\n    build: .\n');
  const mint = await post('/api/v1/nodes', { action: 'enroll', name: 'spare' });
  await post('/api/v1/agent/enroll', {
    user: 'bb', version: '1', digest: 'sha256:' + '2'.repeat(64),
    census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', sshd: true } },
    { Authorization: 'Bearer ' + mint.token, 'Content-Type': 'application/json' });
  const ids = await page.evaluate(async () => {
    await loadNodes();
    return { spare: nodesList.find(n => n.name === 'spare')?.id || '',
             sandbox: nodesList.find(n => n.name === 'sandbox')?.id || '', dflt: nodesDefault };
  });
  ok(ids.spare && ids.dflt === ids.sandbox,
     `the node listing names the node the Containers page opens on, derived from the projects (${ids.dflt})`);
  const setNodes = async (proj, list) => {
    await post('/api/prefs', { project: proj, nodes: list, node: list[0] || '' });
    await page.waitForFunction(([p, want]) =>
      ((state?.projects || []).find(x => x.name === p)?.prefs?.nodes || []).join(',') === want,
      [proj, list.join(',')], { timeout: 20000 });
  };
  const sendDialog = async () => {
    await page.evaluate(() => openSendToDocker('ep.silon'));
    await page.waitForSelector('#dnNodeField:not([hidden])', { timeout: 10000 });
    const got = await page.evaluate(() => ({ node: $('dnNode').value, disabled: $('dnNode').disabled,
      options: [...$('dnNode').options].map(o => o.value), hint: $('dnNodeHint').textContent,
      go: $('dnGo').disabled }));
    await page.evaluate(() => closeSendToDocker());
    return got;
  };
  await setNodes('ep.silon', []);
  const none = await sendDialog();
  ok(none.go && /ep\.silon has no node: set one in its settings first/.test(none.hint),
     `a project with no node has nowhere to send: Create is dead and the field says why (${none.hint.slice(0, 50)})`);
  const bare = await post('/api/devapp', { project: 'ep.silon', action: 'new', instance: 'nowhere' });
  ok(/has no node, so there is nowhere to make its container/.test(bare.error || ''),
     `...and the server refuses a new for it (${String(bare.error).slice(0, 60)})`);
  await setNodes('ep.silon', [ids.spare, ids.sandbox]);
  const two = await sendDialog();
  ok(!two.go && two.node === ids.spare && !two.disabled && two.options.slice().sort().join() === [ids.spare, ids.sandbox].sort().join()
     && /One of ep\.silon's nodes/.test(two.hint),
     `...and Send offers exactly its nodes, primary picked (${two.options.length} offered, ${two.node} picked)`);
  const off = await post('/api/devapp', { project: 'ep.silon', action: 'new', instance: 'elsewhere', node: 'n_notanode' });
  ok(/ep\.silon works on spare, sandbox, and a container for it anywhere else/.test(off.error || ''),
     `a node outside the set is refused, naming the set (${String(off.error).slice(0, 70)})`);
  const on = await post('/api/devapp', { project: 'ep.silon', action: 'new', instance: 'reach', node: ids.sandbox });
  const store = JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'));
  ok(on.ok && store['ep.silon']?.reach?.node === ids.sandbox,
     `...and one inside it lands there (${on.error || store['ep.silon']?.reach?.node})`);
  // Given to another project: only one that works on the node it is on.
  await setNodes('alpha', [ids.spare]);
  const give = await post('/api/devapp', { project: 'ep.silon', instance: 'reach', action: 'owner', owner: 'alpha' });
  ok(/reach is on sandbox and alpha works on spare: its sessions could not reach it/.test(give.error || ''),
     `a container is not given to a project that works elsewhere (${String(give.error).slice(0, 70)})`);
  await setNodes('alpha', [ids.spare, ids.sandbox]);
  const given = await post('/api/devapp', { project: 'ep.silon', instance: 'reach', action: 'owner', owner: 'alpha' });
  ok(given.ok, `...and is, once that project works there too (${given.error || 'given'})`);
  await post('/api/devapp', { project: 'ep.silon', instance: 'reach', action: 'remove' });
  // The New container dialog on the Docker tab: any node until a project is
  // picked, and then that project's nodes only, its primary first.
  const picked = await page.evaluate(() => {
    openNewContainer();
    const before = { node: $('cNode').value, n: $('cNode').options.length };
    $('cUnder').value = 'ep.silon';
    $('cUnder').dispatchEvent(new Event('change'));
    const after = { node: $('cNode').value, n: $('cNode').options.length, hint: $('cNodeHint').textContent };
    $('cmodal').hidden = true;
    return { before, after };
  });
  ok(picked.before.node === ids.sandbox && picked.before.n >= 2 && picked.after.node === ids.spare && picked.after.n === 2
     && /One of ep\.silon's nodes/.test(picked.after.hint),
     `New container follows the project picked to that project's nodes (${picked.before.n} then ${picked.after.n}, ${picked.after.node})`);
  // Opened before the page has fetched its nodes, the way the Artifacts
  // tab's Send is: the picker arrives when the list does, filled.
  await page.evaluate(() => { nodesList = null; openSendToDocker('ep.silon'); });
  await page.waitForFunction(() => $('dnNode').options.length === 2, null, { timeout: 10000 });
  const late = await page.evaluate(() => $('dnNode').value);
  await page.evaluate(() => closeSendToDocker());
  ok(late === ids.spare, `...and a dialog opened before the node list landed gets its picker when it does (${late})`);
  await setNodes('alpha', []);
  await setNodes('ep.silon', [ids.sandbox]);
  rmSync(`${D}/docker-compose.yml`, { force: true });
}

// bb devapp rebuild when the controller is slow to answer the rebuild
// request itself (B298): the build went ahead while the verb said "timed
// out" and stopped. Driven in process with the API call replaced, the way
// toolchains.mjs drives its module: the request times out, and the verb says
// the build may have started, watches for it, and reports it built.
{
  const LIB = new globalThis.URL('../../lib', import.meta.url).pathname;
  const run = spawnSync('python3', ['-c', `
import importlib.util, json, os, sys, time
sys.path.insert(0, ${JSON.stringify(LIB)})
spec = importlib.util.spec_from_file_location("dv", ${JSON.stringify(LIB + '/devapp-verbs.py')})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
looks = iter([{"built_rev": "aaa"}, {"job": {"running": True, "step": "building"}},
              {"built_rev": "bbb", "running": True, "name": "alpha-dev"}])
asked = []
def call(path, body=None, auth="", method="", timeout=30):
    asked.append([body.get("action"), timeout])
    if body.get("action") == "rebuild":
        return {"error": "timed out"}
    return {"state": next(looks)}
m.bbapi.call = call
time.sleep = lambda s: None
os.environ.update(BB_DEV_PROJECT="alpha", BB_DEV_AUTH="x")
code = 0
try:
    m.rebuild()
except SystemExit as e:
    code = e.code
print(json.dumps({"asked": asked, "code": code}))`], { encoding: 'utf8' });
  const got = JSON.parse((run.stdout || '').trim().split('\n').pop() || '{}');
  ok(got.code === 0 && (got.asked || []).some(([a, t]) => a === 'rebuild' && t === 180)
     && /may have started it, so this watches for the build/.test(run.stderr || '')
     && /rebuilt from commit bbb; alpha-dev is up/.test(run.stdout || ''),
     `bb devapp rebuild waits three minutes for the controller, and a timeout there watches for the build rather than giving up (${
       JSON.stringify(got).slice(0, 90)} ${(run.stderr || '').split('\n').filter(Boolean).pop() || ''})`);
}

// B537: an empty listing says what the session can do next. With a compose
// file at the root that is its own bb devapp new, not the operator's Docker
// tab, which is what it said to the aquilaeLabs session before its first
// instance existed.
{
  const LIB = new globalThis.URL('../../lib', import.meta.url).pathname;
  const said = compose => spawnSync('python3', ['-c', `
import importlib.util, os, sys
sys.path.insert(0, ${JSON.stringify(LIB)})
spec = importlib.util.spec_from_file_location("dv", ${JSON.stringify(LIB + '/devapp-verbs.py')})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def call(path, body=None, auth="", method="", timeout=30):
    if path.startswith("/api/docker"):
        return {"instances": [], "containers": []}
    return {"state": {"compose": ${compose ? '"docker-compose.yml"' : '""'}}}
m.bbapi.call = call
os.environ.update(BB_DEV_PROJECT="alpha", BB_DEV_AUTH="x")
try:
    m.ls()
except SystemExit:
    pass`], { encoding: 'utf8' }).stdout || '';
  const withFile = said(true), without = said(false);
  ok(/bb devapp new builds its dev instance/.test(withFile) && !/Containers page/.test(withFile)
     && /compose file at its root/.test(without),
     `bb devapp ls with nothing yet points at bb devapp new, and says a compose file is what it needs where there is none (${withFile.trim().slice(0, 70)})`);
}

// bb devapp rebuild follows the job its answer names (B312): a rebuild of an
// unchanged commit that ended between two looks showed the row neither a
// running job nor a new revision, and the verb said no build appeared over
// one that had. Driven in process: the row never changes, the job says
// succeeded, and the verb reports it rebuilt.
{
  const LIB = new globalThis.URL('../../lib', import.meta.url).pathname;
  const run = spawnSync('python3', ['-c', `
import importlib.util, json, os, sys, time
sys.path.insert(0, ${JSON.stringify(LIB)})
spec = importlib.util.spec_from_file_location("dv", ${JSON.stringify(LIB + '/devapp-verbs.py')})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
asked = []
def call(path, body=None, auth="", method="", timeout=30):
    if body is None:
        asked.append(path); return {"state": "succeeded"}
    asked.append(body.get("action"))
    if body.get("action") == "rebuild":
        return {"ok": True, "started": True, "job": "j9"}
    return {"state": {"built_rev": "aaa", "running": True, "name": "alpha-dev"}}
m.bbapi.call = call
time.sleep = lambda s: None
os.environ.update(BB_DEV_PROJECT="alpha", BB_DEV_AUTH="x", BB_DEV_INSTANCE="", BB_DEV_CONTAINER="")
code = 0
try:
    m.rebuild()
except SystemExit as e:
    code = e.code
print(json.dumps({"asked": asked, "code": code}))`], { encoding: 'utf8' });
  const got = JSON.parse((run.stdout || '').trim().split('\n').pop() || '{}');
  ok(got.code === 0 && (got.asked || []).includes('/api/v1/jobs?id=j9') && /rebuilt from commit aaa; alpha-dev is up/.test(run.stdout || ''),
     `bb devapp rebuild follows the job its answer names, so a fast rebuild of the same commit is reported built (${
        JSON.stringify(got).slice(0, 80)})`);
}

// A container's log, start, stop and restart on an agent node run on that
// node through its agent, as the bare reads do (B312): every other docker
// verb fell to DOCKER_HOST=ssh://, the path R85 names, which no controller
// holds a key for. Driven in process with the node and the queue replaced.
{
  const DASH = new globalThis.URL('../', import.meta.url).pathname.replace(/\/$/, '');
  const run = spawnSync('python3', ['-c', `
import importlib.util, json, os, sys, types
sys.path.insert(0, ${JSON.stringify(DASH)})
spec = importlib.util.spec_from_file_location("dvp", ${JSON.stringify(DASH + '/devapp.py')})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
ran = []
m._agent_here = lambda: {"id": "n1", "name": "box"}
m.queue = types.SimpleNamespace(run_wait=lambda who, nid, argv, timeout=0, forget=False: (ran.append([nid, list(argv)]), {"code": 0, "out": "hello"})[1],
                                job_running=lambda nid: 0)
m._docker_log = lambda *a, **k: None
m._docker_result = lambda *a, **k: None
m.docker_host = lambda: (_ for _ in ()).throw(AssertionError("went to DOCKER_HOST"))
out = [m._run([m.DOCKER, "logs", "--tail", "5", "--timestamps", "c1"]), m._run([m.DOCKER, "restart", "c1"])]
print(json.dumps({"ran": ran, "out": out}))`], { encoding: 'utf8' });
  const got = JSON.parse((run.stdout || '').trim().split('\n').pop() || '{}');
  ok(JSON.stringify((got.ran || []).map(r => r[1][1])) === '["logs","restart"]' && (got.out || []).every(o => o.out === 'hello'),
     `a container's log and restart on an agent node run through its agent, never over ssh (${
        (run.stderr || '').split('\n').filter(Boolean).pop() || JSON.stringify(got).slice(0, 80)})`);
}

// bb devapp new sends the project to Docker the way Send does (the operator,
// 26 Sep): on auto it makes the container, then builds that one and waits
// for the verdict; on ask the one request carries the branch, Allow makes
// and builds it, and the verb follows that build rather than asking for
// another. Driven in process the same way, once per dial.
{
  const LIB = new globalThis.URL('../../lib', import.meta.url).pathname;
  const run = spawnSync('python3', ['-c', `
import importlib.util, json, os, sys, time
sys.path.insert(0, ${JSON.stringify(LIB)})
spec = importlib.util.spec_from_file_location("dv", ${JSON.stringify(LIB + '/devapp-verbs.py')})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
time.sleep = lambda s: None
m.waits.outcome = lambda auth, rid, no: {"code": 0, "out": "j1"}
out = {}
for dial in ("auto", "ask"):
    bodies = []
    looks = iter(([{"built_rev": ""}] if dial == "auto" else [])
                 + [{"built_rev": "ccc", "running": True, "name": "alpha-2"}])
    def call(path, body=None, auth="", method="", timeout=30, dial=dial, bodies=bodies, looks=looks):
        if body is None:
            bodies.append({"action": "job", "instance": path.split("=")[-1], "ref": None})
            return {"state": "succeeded"}
        bodies.append({k: body.get(k) for k in ("action", "instance", "ref")})
        if body.get("action") == "new":
            return ({"ok": True, "instance": "alpha-2", "name": "alpha-2"} if dial == "auto"
                    else {"ok": True, "id": 7, "to": "the administrators", "instance": "alpha-2", "name": "alpha-2"})
        if body.get("action") == "rebuild":
            return {"ok": True, "started": True, "job": "j1"}
        return {"state": next(looks)}
    m.bbapi.call = call
    os.environ.update(BB_DEV_PROJECT="alpha", BB_DEV_AUTH="x", BB_DEV_REF="sendbranch",
                      BB_DEV_INSTANCE="", BB_DEV_CONTAINER="")
    code = 0
    try:
        m.new()
    except SystemExit as e:
        code = e.code
    out[dial] = {"code": code, "bodies": bodies}
print(json.dumps(out))`], { encoding: 'utf8' });
  const got = JSON.parse((run.stdout || '').trim().split('\n').pop() || '{}');
  const acts = d => (got[d]?.bodies || []).map(b => b.action + (b.instance ? ':' + b.instance : '')).join(' ');
  ok(got.auto?.code === 0 && got.auto.bodies[0].action === 'new' && !got.auto.bodies[0].instance
     && got.auto.bodies[0].ref === 'sendbranch' && acts('auto') === 'new state:alpha-2 rebuild:alpha-2 job:j1 state:alpha-2'
     && /created alpha-2/.test(run.stderr || '') && /built from commit ccc; alpha-2 is up/.test(run.stdout || ''),
     `bb devapp new on auto makes the container and builds that one, waiting for the verdict (${acts('auto')})`);
  ok(got.ask?.code === 0 && acts('ask') === 'new job:j1 state:alpha-2'
     && /asked the administrators \(#7\) to send it to Docker as alpha-2/.test(run.stderr || ''),
     `...and on ask it follows the build Allow starts instead of asking for another (${acts('ask')})`);
}

// The Docker tab's rows each carry a Ports and mounts fold, and the jump
// bar a long surface gets listed every one of them under one name, a bar of
// identical links in the first row (the operator, 8 Oct). A fold repeated
// per row is the row's, never a section to jump to; four of its own still
// make a bar.
{
  const shape = await page.evaluate(() => {
    const make = titles => {
      const g = document.createElement('div');
      g.className = 'doctab';
      g.innerHTML = titles.map((t, i) => docSection('docker', `probe:${i}`, t, '', '<div>x</div>', { open: false })).join('');
      document.body.append(g);
      sectJump(g);
      const links = [...g.querySelectorAll('.sectjump a')].map(a => a.textContent);
      g.remove();
      return links;
    };
    return { rows: make(['Ports and mounts', 'Ports and mounts', 'Ports and mounts', 'Ports and mounts', 'Ports and mounts']),
             own: make(['One', 'Two', 'Three', 'Four', 'Ports and mounts', 'Ports and mounts']) };
  });
  ok(shape.rows.length === 0 && JSON.stringify(shape.own) === '["One","Two","Three","Four"]',
     `a fold repeated once per row makes no jump bar, and a surface's own sections still do (${JSON.stringify(shape)})`);
}

// ---- a route through the node's nginx, from the row (R209, 13 Oct) ----------
// With BuilderBot's nginx deployed on the node, a container's row offers a
// certificate (none: any hostname on 80) and one of its published ports, and
// Add route writes the route on the nginx tab and applies it; the same port
// again is refused by name, and the port reads as routed in the pulldown.
{
  // The fixture's compose went with the cleanup above, so the container the
  // row is for is put back: a stack with one published port, up on the stub.
  writeFileSync(`${D}/docker-compose.yml`,
    'services:\n  app:\n    image: delta-dev\n    build: .\n    ports:\n      - "7475:7474"\n');
  writeFileSync(`${DIR}/dockerstate/ep-silon.up`, '');
  writeFileSync(`${DIR}/dockerstate/ep-silon.svcs`, 'app 7475 7474\n');
  const api = (body) => page.evaluate(async b => (await (await fetch('/api/devapp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json()), body);
  // Made with `new`, as at the top: the manager lists what was sent to it,
  // and an up or a build on an instance with no record writes none (B633).
  await api({ project: 'ep.silon', instance: 'main', action: 'new' });
  await api({ project: 'ep.silon', instance: 'main', action: 'up' });
  const nodeId = await page.evaluate(() => dockerList?.node || dockerNode || '');
  const dep = await page.evaluate(async n => (await (await fetch('/api/nginx', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'deploy', node: n }) })).json()), nodeId);
  ok(dep.ok === true || /already on the Containers page/.test(dep.error || ''), `nginx is deployed on the node for the row to route through (${JSON.stringify(dep).slice(0, 80)})`);
  await openManager();
  await dmEditAll();
  for (let i = 0; i < 40 && !(await page.$(`${DM} .dmnginxroute [data-dmngadd]`)); i++){ await dmRefresh(); await dmEditAll(); await sleep(1000); }
  await page.waitForSelector(`${DM} .dmnginxroute [data-dmngadd]`, { timeout: 20000 });
  const line = await page.$eval(`${DM} .dmnginxroute`, e => ({ certs: [...e.querySelectorAll('[data-dmngcert] option')].map(o => o.value),
    ports: [...e.querySelectorAll('[data-dmngport] option')].map(o => `${o.value}${o.disabled ? '!' : ''}`), add: !e.querySelector('[data-dmngadd]').disabled }));
  ok(line.certs[0] === '' && line.ports.length >= 1 && !line.ports[0].endsWith('!') && line.add,
     `the row offers a certificate (none first), the container's published ports, and Add route (${JSON.stringify(line)})`);
  // What is typed into the hostname box survives the tab being drawn again
  // (B729: a redraw between the typing and the press sent no hostname).
  // The live box, never the one in a redraw's fading copy (.fghost): that
  // copy has no handlers, so typing there reached no draft ("no box; draft
  // {}", B829) and reading it read a box the page had already replaced.
  const HOSTBOX = `${DM} .dmnginxroute [data-dmnghost]:not(.fghost *)`;
  // Typed until the draft holds it: a poll's redraw landing with the fill
  // can take the box it typed into, and the check then measured a draft that
  // never saw the typing ("no box; draft {}", B829), not the redraw it is for.
  let fillWhy = '';
  for (let i = 0; i < 5; i++){
    await page.waitForSelector(HOSTBOX, { timeout: 10000 });
    await page.fill(HOSTBOX, 'kept.example.test', { timeout: 5000 }).catch(e => { fillWhy = String(e.message || e).split('\n').slice(0, 6).join(' / '); });
    if (await page.evaluate(() => JSON.stringify(dmNginxDraft || {}).includes('kept.example.test'))) break;
    fillWhy += ' :: ' + JSON.stringify(await page.$$eval(`[data-dmnghost]`, es => es.map(b => ({ ghost: !!b.closest('.fghost'), dlg: b.closest('dialog')?.open,
      dis: b.disabled, ro: b.readOnly, vis: b.offsetHeight > 0, wired: typeof b.oninput === 'function', val: b.value,
      row: b.closest('.row')?.dataset.inst, doc: b.closest('.doc')?.className, pane: [...document.querySelectorAll('.pane')].indexOf(b.closest('.pane')),
      inert: !!b.closest('[inert]') || document.activeElement === b, top: b.closest('dialog') === [...document.querySelectorAll('dialog[open]')].pop() }))));
    await sleep(300);
  }
  const typed = await page.evaluate(() => JSON.stringify(dmNginxDraft));
  await page.evaluate(() => { dockerRev++; drawPanes(); });
  // ...and read once the row is drawn again, not in the instant the redraw
  // may still be showing the page's placeholder.
  await page.waitForSelector(HOSTBOX, { timeout: 10000 }).catch(() => {});
  const kept = await page.$$eval(HOSTBOX, es => es.map(e => e.value));
  ok(kept[0] === 'kept.example.test',
     `a hostname typed on the row is still there after the tab is drawn again (${kept.join(' | ') || 'no box'}; draft ${typed}${fillWhy ? `; fill: ${fillWhy.slice(0, 600)}` : ''})`);
  await page.fill(HOSTBOX, '');
  const port = Number(line.ports[0].replace('!', ''));
  await page.click(`${DM} .dmnginxroute [data-dmngadd]`);
  await page.waitForFunction(p => (dockerList?.nginx?.routed || []).includes(p), port, { timeout: 30000 });
  const got = await page.evaluate(async n => (await (await fetch('/api/nginx')).json()).nodes.find(x => x.node === n).routes, nodeId);
  ok(got.some(r => r.port === port && r.host === '*' && r.cert === '' && r.tls === false),
     `Add route wrote the route on the nginx page: any hostname, 80 alone, to port ${port} (${JSON.stringify(got)})`);
  const again = await page.evaluate(async ([n, p]) => (await (await fetch('/api/nginx', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'route-add', node: n, cert: '', port: p }) })).json()), [nodeId, port]);
  ok(/already has a route: \*\//.test(again.error || ''), `the same port again is refused by name (${again.error})`);
  await page.waitForFunction(p => [...document.querySelectorAll('.dmtab [data-dmngport] option')].some(o => Number(o.value) === p && /routed/.test(o.textContent) && !o.disabled), port, { timeout: 15000 });
  ok(true, '...and the pulldown reads that port as routed, still offered for another hostname');
  // ...which lands (B729: a site at its domain and at www, one port): the
  // same port under a hostname typed, beside the any-name route.
  const second = await page.evaluate(async ([n, p]) => (await (await fetch('/api/nginx', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'route-add', node: n, cert: '', host: 'www.second.example', port: p }) })).json()), [nodeId, port]);
  ok(second.route?.host === 'www.second.example' && second.route?.port === port,
     `the same port at another hostname is a second route, not a refusal (${JSON.stringify(second.route || second.error)})`);
  // ...and the row says where nginx answers for it, as a fact with a link (R216).
  await dmEditNone();
  await page.waitForFunction(sel => [...document.querySelectorAll(sel + ' .fpill')].some(p => p.querySelector('.k')?.textContent === 'nginx'), DM, { timeout: 15000 }).catch(() => {});
  const routeFact = await page.evaluate(sel => { const p = [...document.querySelectorAll(sel + ' .fpill')].find(x => x.querySelector('.k')?.textContent === 'nginx');
    const a = p?.querySelector('a'); return a ? { href: a.href, text: a.textContent } : null; }, DM);
  ok(routeFact && /^http:\/\/[^/]+\/$/.test(routeFact.href),
     `...and the row carries the route as a fact, the address it answers at (${JSON.stringify(routeFact)})`);
  const bad = await page.evaluate(async n => (await (await fetch('/api/nginx', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'route-add', node: n, cert: 'nope.example.com', port: 9 }) })).json()), nodeId);
  ok(/holds no certificate filed under nope.example.com/.test(bad.error || ''), `a certificate the node does not hold is refused by name (${bad.error})`);
  // A hostname typed on the row (the operator, 13 Oct): the route serves
  // that name, and the name joins the shared Hostnames list.
  await dmEditAll();
  await page.waitForSelector(`${DM} .dmnginxroute [data-dmnghost]`, { timeout: 15000 }).catch(() => {});
  ok(await page.$(`${DM} .dmnginxroute [data-dmnghost]`) !== null, 'the row offers a hostname box beside the certificate');
  const named = await page.evaluate(async n => (await (await fetch('/api/nginx', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'route-add', node: n, cert: '', host: 'app.example.com', port: 9 }) })).json()), nodeId);
  const hosts = (await page.evaluate(async () => (await (await fetch('/api/nginx')).json()).hostnames)).map(h => h.name);
  ok(named.route?.host === 'app.example.com' && hosts.includes('app.example.com'),
     `a hostname typed on the row is the route's, and is on the Hostnames list after (${named.error || named.route?.host}; ${hosts.join(',')})`);
}

await done(browser);
