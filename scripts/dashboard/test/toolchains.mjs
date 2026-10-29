// The toolchain store, its installer and the Library's cards for them. The
// catalog is config/toolchains.json and bb's dispatch; the installer is the
// controller's own (/api/toolchains with no node, "local"), driven here
// through the API because it is the path that writes real files: the
// harness's bb stub makes and removes directories rather than downloading
// gigabytes, so a whole round trip runs in a second. What a person reads is
// the Library's cards on the harness's sandbox node (a stub agent that
// answers a toolchain job at once, failing it), the Installed page's rows,
// and the tool pack dialog the Library's Add your own and a card's Edit
// open. Then the shell libraries a session on a node reads its store with.
import { launch, newPage, ok, done, ready, sectSave, URL, DIR } from './lib.mjs';
import { existsSync, readFileSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

ok(await page.evaluate(() => railGroups().some(g => g.key === 'projects' && g.tools.some(([k]) => k === 'findings')) && railAllows('findings')),
   'the scanner report, Analysis, is a page under Projects on the rail');

// ---- the API, as the page asks it ---------------------------------------
// {status, ...the answer}: a refusal's status is part of what is checked.
const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, b ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) } : {});
  const j = await r.json().catch(() => ({}));
  return { ...j, status: r.status };
}, [path, body]);
const sleep = ms => new Promise(r => setTimeout(r, ms));
// The controller's own store, which no page draws: read until `until` holds
// of it, the last read handed back either way so a check can say what it saw.
const local = () => api('/api/toolchains');
const waitLocal = async (until, timeout = 30000) => {
  let t = {};
  for (const end = Date.now() + timeout; Date.now() < end; await sleep(300)){
    t = await local();
    if (until(t)) return t;
  }
  return t;
};
const item = (t, n) => (t.items || []).find(i => i.name === n);
// Install as tcAct does: an agreement the server names (Google's Android SDK
// terms) is accepted by name on a second ask, the person's press standing
// for that acceptance on the page.
const tcInstall = async (names, node) => {
  const body = { action: 'install', names, ...(node ? { node } : {}) };
  let j = await api('/api/toolchains', body);
  if (j.status === 409 && Array.isArray(j.accept) && j.accept.length)
    j = await api('/api/toolchains', { ...body, accept: j.accept.map(a => a.label) });
  return j;
};

const sb = (await api('/api/v1/nodes')).nodes.find(n => n.name === 'sandbox');
const toLibrary = async () => {
  await page.evaluate(id => openLibraryOn(id), sb.id);
  await page.waitForFunction(id => libNode === id && lib && Array.isArray(lib.rows)
    && !!document.querySelector(`.pane .doc.on .librarytab [data-libnode="${id}"]`), sb.id, { timeout: 20000 });
};
await toLibrary();

// ---- the catalog ---------------------------------------------------------
// The catalog is a file in the repository, not a list in the server: adding a
// toolchain should be an edit somebody can make without reading python.
const catalog = JSON.parse(
  readFileSync(`${import.meta.dirname}/../../../config/toolchains.json`, 'utf8'));
let tc = await local();
ok(catalog.toolchains.length === (tc.items || []).length
   && catalog.toolchains.every(c => item(tc, c.name)),
   `the store offers the catalog from config/toolchains.json (${catalog.toolchains.length} entries)`);
ok(tc.items.every(i => !i.installed && !i.size && !i.version),
   'a scratch root starts with nothing installed, and nothing weighed or versioned yet');
ok(String(tc.root || '').includes(`${DIR}/sdk`), `the store says which root things are installed into (${tc.root})`);
// What a session on a node needs from the store rather than from the image
// (roadmap #24, step 4): the playwright module beside its browsers, with
// NODE_PATH pointing at it, and the tools bb lint runs.
const pw = catalog.toolchains.find(p => p.name === 'playwright');
const lt = catalog.toolchains.find(p => p.name === 'lint-tools');
ok(pw?.layout?.env?.NODE_PATH === 'node_modules' && /npm install/.test(pw?.source?.run?.join(' '))
   // ...and its command on PATH (B534): which playwright found nothing, and
   // a session hard-coded the module's path into its own scripts.
   && pw?.layout?.bin?.includes('node_modules/.bin')
   && lt?.layout?.bin?.includes('bin')
   && ['shellcheck', 'hadolint', 'actionlint', 'ruff', 'yq', 'fd'].every(t => (lt?.source?.run?.join(' ') || '').includes(t)),
   'the playwright recipe puts the module in the store with NODE_PATH on it and its command on PATH, and lint-tools carries what bb lint runs');

// A recipe that gives a session commands says under which name (`tool`):
// they live under `bb tool NAME`, one name per recipe, so two toolchains may
// both have a `render` and neither can shadow a verb of bb's own. Held to
// the script itself: every declared tool is a label in bb's `tool` case, no
// two recipes claim one, and neither that case nor the dispatch carries a
// duplicate label, since a bash case takes the first match and hides a
// second in silence.
{
  const bb = readFileSync(`${import.meta.dirname}/../../bb`, 'utf8');
  const labels = [...bb.matchAll(/^    ([a-z][a-z0-9|-]*)\)\s+(?:shift; )?cmd_/gm)]
    .flatMap(m => m[1].split('|'));
  const dup = labels.filter((l, i) => labels.indexOf(l) !== i);
  ok(dup.length === 0, `bb's dispatch names each verb once (${dup.join(', ') || 'no duplicates'})`);
  const toolCase = bb.slice(bb.indexOf('\ncmd_tool() {'), bb.indexOf('\n}\n', bb.indexOf('\ncmd_tool() {')));
  const tools = [...toolCase.matchAll(/^        ([a-z][a-z0-9-]*)\)\s+tool_/gm)].map(m => m[1]);
  const tdup = tools.filter((l, i) => tools.indexOf(l) !== i);
  ok(tools.length >= 2 && tdup.length === 0, `bb tool names each tool once (${tools.join(', ')})`);
  const claimed = new Map();
  const missing = [];
  for (const t of catalog.toolchains) if (t.tool) {
    if (!tools.includes(t.tool)) missing.push(`${t.name}: bb tool ${t.tool}`);
    if (claimed.has(t.tool)) missing.push(`${t.tool} is claimed by ${claimed.get(t.tool)} and ${t.name}`);
    if (labels.includes(t.tool)) missing.push(`${t.tool} is also a verb of bb's own`);
    claimed.set(t.tool, t.name);
  }
  ok(missing.length === 0, `every tool a recipe declares is in bb's tool case, and one recipe's only (${missing.join('; ') || 'all agree'})`);
}

// ---- the Library's toolchain cards, on the sandbox node --------------------
// A card's Details says which tool installing it adds to a session, and
// what installing it is under: an agreement Install accepts (Google's
// Android SDK terms, linked: the acceptance is the operator's, not a
// script's), else the licenses (the operator, 7 Oct).
{
  const said = await page.evaluate(() => {
    const keys = lib.rows.filter(r => r.kind === 'toolchain' && !r.machine && !r.wrong_platform).map(r => `toolchain:${r.name}`);
    keys.forEach(k => libOpen.add(k)); libRev++; drawPanes();
    const out = keys.map(k => {
      const c = document.querySelector(`.doc .librarytab .lcard[data-lrow="${k}"]`);
      const r = lib.rows.find(x => `toolchain:${x.name}` === k);
      return { name: r.name, tool: r.tool || '', detail: c?.querySelector('.ldetail')?.textContent.replace(/\s+/g, ' ') || '',
               terms: c?.querySelector('.ldetail .tcterms')?.textContent || '',
               google: !!c?.querySelector('.ldetail .tcterms a[href*="developer.android.com/studio/terms"]') };
    });
    keys.forEach(k => libOpen.delete(k)); libRev++; drawPanes();
    return out;
  });
  const withTool = said.find(s => s.name === 'graphics' && s.tool) || said.find(s => s.tool);
  ok(!!withTool && withTool.detail.includes(`Adds bb tool ${withTool.tool} to a session`),
     `a card's Details says which tool installing it adds (${withTool?.name}: ${withTool?.tool})`);
  const android = said.filter(s => /^android/.test(s.name));
  ok(android.length && android.every(s => s.google && /Installing it asks you to accept Google's Android SDK terms/.test(s.terms)),
     `each Android card's Details says Install accepts Google's Android SDK terms, linked (${android.length} cards)`);
  const bare = said.filter(s => !s.terms);
  ok(said.length > android.length && !bare.length,
     `...and every other toolchain card names its terms (${bare.map(s => s.name).join(', ') || 'none without'})`);
}

// What a card says of where it stands, planted on a row and put back in the
// same evaluate: the page re-reads on the toolchains and nodes revisions,
// and a fake left across two round trips is one a real load lands on.
const card = (name, patch) => page.evaluate(([n, p]) => {
  const r = lib.rows.find(x => x.kind === 'toolchain' && x.name === n);
  const was = { ...r };
  Object.assign(r, p); libRev++; drawPanes();
  const c = document.querySelector(`.doc .librarytab .lcard[data-lrow="toolchain:${n}"]`);
  const st = c?.querySelector('.pcacts .state');
  const out = { state: st?.textContent.trim() || '', cls: st?.className || '', dots: !!st?.querySelector('.dots'),
                bar: !!c?.querySelector('.bar'),
                acts: [...(c?.querySelectorAll('[data-libact]') || [])].map(b => b.textContent.trim()),
                pills: [...(c?.querySelectorAll('.lcmeta .pill') || [])].map(x => x.textContent.trim()) };
  for (const k of Object.keys(p)) delete r[k];
  Object.assign(r, was); libRev++; drawPanes();
  return out;
}, [name, patch]);
{
  // One word and an ellipsis for the whole of a job: no percentage read out
  // of the output (every recipe meters differently, several mislead), no bar,
  // and no verb on the card while it is being written.
  let d = await card('flutter', { running: true, doing: 'install' });
  ok(d.state === 'installing' && d.dots && !d.bar && !d.acts.length,
     `a card being installed says installing with an ellipsis, no bar and no verb (${d.state}; ${d.acts.join(', ')})`);
  d = await card('flutter', { running: true, doing: 'remove', installed: true });
  ok(d.state === 'removing' && d.dots && !d.bar, `...and one being removed says removing (${d.state})`);
  d = await card('flutter', { installed: true, unknown: false, version: '3.0', update: false, latest: '' });
  ok(d.state === 'installed' && /\bok\b/.test(d.cls) && !d.acts.includes('Install') && !d.pills.some(p => /is out/.test(p)),
     `installed and current: it says installed, offers no Install, and claims no update (${d.state}; ${d.acts.join(', ') || 'no verb'})`);
  d = await card('flutter', { installed: true, unknown: false, version: '3.0', update: true, latest: '3.1' });
  ok(d.state === 'update available' && /\bwarn\b/.test(d.cls) && d.acts.includes('Update') && d.pills.includes('3.1 is out'),
     `an update out says update available in amber, with Update and what is out (${d.state}; ${d.pills.join(', ')})`);
  d = await card('flutter', { installed: false, unknown: false, update: false, latest: '' });
  ok(d.state === '' && d.acts.includes('Install') && !d.pills.some(p => /warn/.test(p)),
     '...and one not installed offers Install and says nothing amber');
  // B31: a tool the census calls "present" has no version to show.
  d = await card('flutter', { installed: true, unknown: false, version: 'present', update: false });
  ok(d.state === 'installed' && !d.pills.includes('present'),
     `a toolchain the census calls "present" reads installed, with no "present" pill (B31) (${d.pills.join(', ')})`);
  // The dots are ticked by a timer, so a redraw must not reset them.
  const dots = await page.evaluate(async () => {
    const r = lib.rows.find(x => x.kind === 'toolchain' && x.name === 'flutter');
    const was = { running: r.running, doing: r.doing };
    Object.assign(r, { running: true, doing: 'install' }); libRev++; drawPanes();
    const read = () => document.querySelector('.doc .librarytab .lcard[data-lrow="toolchain:flutter"] .dots')?.textContent ?? null;
    const first = read();
    await new Promise(res => setTimeout(res, 900));
    const later = read();
    libRev++; drawPanes();                      // a redraw, mid-animation
    const after = read();
    Object.assign(r, was); libRev++; drawPanes();
    return { first, later, after };
  });
  ok(dots.later !== null && dots.later !== dots.first && dots.after === dots.later,
     `...and the card's ellipsis animates, and a redraw does not reset it (${JSON.stringify(dots)})`);
}
// What a job said failed, under the card it failed on and no other.
{
  const bad = await page.evaluate(() => {
    const was = lib.job;
    lib.job = { ...(was || {}), running: false, errors: { flutter: 'could not download file · install failed (exit 1)' } };
    libRev++; drawPanes();
    const out = { text: document.querySelector('.doc .librarytab .lcard[data-lrow="toolchain:flutter"] .sub.bad')?.textContent || '',
                  n: document.querySelectorAll('.doc .librarytab .lcard .sub.bad').length };
    lib.job = was; libRev++; drawPanes();
    return out;
  });
  ok(/could not download file/.test(bad.text) && bad.n === 1,
     `a failure is said under the card that failed, and no other card wears it (${bad.text})`);
}
// One operation at a time (the server answers a second with a 409), so the
// verbs go dead while one runs rather than letting a press earn an error.
// Abort is the one control that has to work while a job runs.
{
  const g = await page.evaluate(() => {
    const was = lib.job;
    lib.job = { ...(was || {}), running: true, action: 'install', current: 'swift' };
    libRev++; drawPanes();
    const all = sel => [...document.querySelectorAll(sel)];
    const installs = all('.doc .librarytab [data-libact="install"][data-libkind="toolchain"]');
    const out = {
      check: !!document.querySelector('.doc .librarytab [data-libcheck]')?.disabled,
      abort: all('.doc .librarytab [data-libabort]').length === 1 && !document.querySelector('.doc .librarytab [data-libabort]').disabled,
      install: installs.length > 0 && installs.every(b => b.disabled),
    };
    lib.job = was; libRev++; drawPanes();
    return out;
  });
  ok(g.check && g.abort && g.install,
     `while a job runs, Check for updates and every card's Install are dead and Abort is live (${
       Object.entries(g).filter(([, v]) => !v).map(([k]) => k).join(', ') || 'all'})`);
  // A check the operator did not start still has to reach the page, and the
  // button says which job is in the way; the head keeps to the store (B31).
  const c = await page.evaluate(() => {
    const was = lib.job;
    lib.job = { ...(was || {}), running: true, action: 'check' };
    libRev++; drawPanes();
    const b = document.querySelector('.doc .librarytab [data-libcheck]');
    const out = { t: b?.textContent || '', dots: !!b?.querySelector('.dots'),
                  head: document.querySelector('.doc .librarytab .pghead')?.textContent || '' };
    lib.job = was; libRev++; drawPanes();
    return out;
  });
  ok(/^Checking for updates/.test(c.t) && c.dots && !/Checking/.test(c.head),
     `...and Check for updates says it is checking, once: the head keeps to the store (B31) (${c.t.trim()})`);
  ok(await page.$eval('.doc .librarytab [data-libcheck]', b => !b.disabled),
     '...and the bar is live again when it finishes');
  // The answers are dated, because a number with no date on it goes stale.
  const when = await page.evaluate(() => {
    const was = lib.store;
    const read = () => /Versions checked/.test(document.querySelector('.doc .librarytab .pghead')?.textContent || '');
    lib.store = { ...(was || {}), checked: 0 }; libRev++; drawPanes();
    const none = read();
    lib.store = { ...(was || {}), checked: Math.floor(Date.now() / 1000) - 3600 }; libRev++; drawPanes();
    const some = read();
    lib.store = was; libRev++; drawPanes();
    return { none, some };
  });
  ok(!when.none && when.some, 'the head says when versions were last checked, and nothing while they never were');
}
// A retired node's directory on the store is offered with Remove (R196).
{
  const seen = await page.evaluate(() => {
    const was = lib.cleanable;
    lib.cleanable = [{ dir: 'n_0ldd0ne1', what: "gone's, a node since retired" }]; libRev++; drawPanes();
    const out = { head: (document.querySelector('.doc .librarytab .pghead')?.textContent || '').replace(/\s+/g, ' '),
                  rm: !!document.querySelector('.pane [data-libclean].danger') };
    lib.cleanable = was; libRev++; drawPanes();
    return out;
  });
  ok(/Remove takes\W*n_0ldd0ne1 \(gone's, a node since retired\)/.test(seen.head) && seen.rm,
     `a retired node's directory on the store is in the head's Remove takes, with Remove in the bar (R196) (${seen.head.slice(-70)})`);
}

// ---- install two on the controller's store, watch them land ----------------
// More than two land: android:emulator is installed BY sdkmanager, which
// android-tools provides, which needs a JDK, and the emulator is useless
// without adb, so platform-tools comes too. That is the point of `requires`;
// before it, this pair installed and then failed inside sdkmanager with a
// message naming neither. Asserted as a SET rather than a count: a count has
// to be edited every time the catalog declares another dependency.
const CHAIN = ['flutter', 'android:emulator', 'android-tools', 'android:platform-tools', 'jdk'];
const started = await tcInstall(['flutter', 'android:emulator']);
ok(started.ok !== false && started.status === 200, `Install starts a job on the controller's store (${started.error || 'started'})`);
tc = await waitLocal(t => t.job && !t.job.running && CHAIN.every(n => item(t, n)?.installed));
ok(CHAIN.every(n => item(tc, n)?.installed),
   `installing a toolchain installs what it needs alongside it, transitively (${(tc.items || []).filter(i => i.installed).map(i => i.name).join(', ')})`);
ok(item(tc, 'flutter').path === `${DIR}/sdk/flutter`, `flutter installs to the toolchain store root (${item(tc, 'flutter').path})`);
ok(item(tc, 'android:emulator').path === `${DIR}/androidsdk/emulator`,
   `an android package resolves to its place in the SDK tree (${item(tc, 'android:emulator').path})`);
ok(existsSync(`${DIR}/sdk/flutter`) && existsSync(`${DIR}/androidsdk/emulator`), '...and both really exist on disk');

// ---- versions and updates ----------------------------------------------
// The installed version is local knowledge and shows without being asked;
// whether something newer exists is a network question, and until it is
// asked nothing claims anything.
ok(tc.items.some(i => i.installed && i.version === '1.0'), 'installed versions are known without a check');
ok(tc.items.every(i => i.state !== 'update'), 'no update claims before a check');
// No size is typed into the catalog (a typed one is wrong the next time
// upstream ships), so a toolchain carries one only once this box has
// weighed it, measured by a worker and arriving a moment after the read.
tc = await waitLocal(t => /measured on disk/.test(item(t, 'flutter')?.size_from || ''));
ok(/measured on disk/.test(item(tc, 'flutter').size_from) && !!item(tc, 'flutter').size,
   `an installed toolchain says what it takes on disk, and says so (${item(tc, 'flutter').size})`);
ok(!item(tc, 'swift').size, '...and one this box has never had says no size at all rather than a guess');
// The whole catalog, not just what is installed, so wait for the job to end
// rather than for the first answer.
await api('/api/toolchains', { action: 'check', names: [] });
tc = await waitLocal(t => t.job?.action === 'check' && !t.job.running && t.checked > 0);
const upd = tc.items.filter(i => i.state === 'update').map(i => i.name);
ok(upd.length === 1 && upd[0] === 'flutter', `the check marks exactly the toolchain whose upstream moved (${upd.join(', ')})`);
ok(item(tc, 'swift').latest === '9.9', 'a toolchain that has never been installed says what Install would fetch');
// ...and its size is the download: the only size a toolchain this box has
// never had can honestly say, and upstream is the one that knows it.
ok(/download/.test(item(tc, 'swift').size) && /from upstream/.test(item(tc, 'swift').size_from),
   `...and what the download weighs, asked of upstream rather than guessed (${item(tc, 'swift').size})`);
ok(item(tc, 'swift').state !== 'update', '...and says it plainly: only an actual update is one');
// The answers cost a network round trip each, so they are kept on the state
// volume and dated.
const stored = JSON.parse(readFileSync(`${DIR}/state/toolchain-versions.json`, 'utf8'));
ok(stored.at > 0 && stored.items.flutter.status === 'update',
   '...and they are on disk, to outlive the process that asked');
// So is the local version read: `bb toolchains versions` is a couple of
// seconds across every toolchain, and the answer has not changed. Keyed by
// what it is an answer about (the set of installed paths, and the catalog's
// own digest), so installing something, or editing a recipe, is not answered
// from it.
ok(stored.local && typeof stored.local.key === 'string' && stored.local.key,
   '...as is the local version read, with the key it is an answer for');
ok(stored.catalog && stored.local.key.startsWith(stored.catalog),
   `...and the catalog's digest is in that key, so editing a recipe drops it (${
      stored.catalog})`);
{
  // The module's own view of it, which is where the decision is made: an
  // answer stored against a different catalog is not an answer any more, and
  // zeroing the date is what sends the weekly loop looking again.
  const { execFileSync } = await import('node:child_process');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const ask = extra => execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("pk", "${REPO}/scripts/dashboard/toolchains.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(run=lambda *a, **k: {"code": 1, "out": ""},
            write_json=lambda p, d: None, state="${DIR}/state")
${extra}
print(json.dumps({"at": m._tc_checked, "local": bool(m._tc_local.get("versions"))}))`],
    { encoding: 'utf8' });
  const kept = JSON.parse(ask(''));
  ok(kept.at > 0, 'a restart reads the check date back rather than starting from zero');
  const moved = JSON.parse(ask('m.CATALOG_DIGEST = "0000deadbeef0000"\n'
    + 'm.globals = None\n'
    + 'v = m.load_versions()\n'
    + 'm._tc_checked = v[1]'));
  ok(moved.at === 0,
     '...and an edited catalog resets it, because the answers describe recipes');
}
// Update runs like an install: a job, on what is already installed.
await tcInstall(['flutter']);
tc = await waitLocal(t => t.job?.action === 'install' && !t.job.running && (t.job.done || []).includes('flutter'));
ok((tc.job.done || []).includes('flutter') && !(tc.job.failed || []).length,
   'Install on a toolchain that is already installed updates it');
// The catalog says which recipes update in place (bug #43), not a list in
// the server: a tarball recipe is removed and installed again instead.
{
  const seen = tc.items.filter(i => i.updatable).map(i => i.name).sort();
  ok(seen.includes('flutter') && seen.includes('playwright') && !seen.includes('go') && !seen.includes('jdk'),
     `the catalog says which recipes update in place (${seen.join(', ')})`);
}

// ---- a long job, through the real path ---------------------------------
// The stub's `go` install draws a carriage-return progress bar over several
// seconds; the job record says which toolchain it is on and what it is
// doing, and nothing of the meter.
await tcInstall(['go']);
const samples = [];
for (let i = 0; i < 20; i++){
  const t = await local();
  if (t.job?.running) samples.push({ current: t.job.current, action: t.job.action });
  await sleep(250);
}
ok(samples.length > 1 && samples.every(s => s.current === 'go' && s.action === 'install'),
   `a running install says which toolchain it is on and that it is installing, all through (${samples.length} samples)`);
tc = await waitLocal(t => t.job?.action === 'install' && !t.job.running && (t.job.done || []).includes('go'), 60000);
ok(item(tc, 'go')?.installed, '...and it lands');
// Put it back the way it was found: what follows counts installed toolchains.
await api('/api/toolchains', { action: 'remove', names: ['go'] });
tc = await waitLocal(t => t.job?.action === 'remove' && !t.job.running && !item(t, 'go')?.installed);
ok(!item(tc, 'go')?.installed, 'Remove takes it off the store');

// ---- remove one, the other stays ------------------------------------------
await api('/api/toolchains', { action: 'remove', names: ['android:emulator'] });
tc = await waitLocal(t => t.job?.action === 'remove' && !t.job.running && !item(t, 'android:emulator')?.installed);
ok(!item(tc, 'android:emulator')?.installed && item(tc, 'flutter')?.installed,
   'removing one leaves the other alone');
ok(!existsSync(`${DIR}/androidsdk/emulator`), '...and it is gone from disk');

// ---- a failure, where the failure happened ------------------------------
// What anybody wants out of a job's output is which toolchain failed and
// why, so that is what the job keeps, by name, for the card it failed on.
await tcInstall(['rust']);
tc = await waitLocal(t => t.job && !t.job.running && (t.job.failed || []).includes('rust'));
const rustErr = tc.job?.errors?.rust || '';
ok(/could not download file/.test(rustErr), `the failing toolchain's own line says what went wrong (${rustErr.slice(0, 52)})`);
ok(!/\[====\]/.test(rustErr), '...without the progress frames');
ok(/exit 1/.test(rustErr), '...and the exit code, since a killed tool prints nothing at all');
ok(Object.keys(tc.job.errors || {}).length === 1, 'and no other toolchain is wearing one');
// Trying again is what clears it: by then it describes a state that is over.
await tcInstall(['rust']);
const again = await waitLocal(t => t.job?.running && t.job.current === 'rust', 30000);
ok(again.job?.running && !(again.job.errors || {}).rust, '...and asking again clears it, because it is no longer the answer');
await waitLocal(t => t.job && !t.job.running);

// ---- what the endpoint refuses ----------------------------------------
const post = async body => (await api('/api/toolchains', body)).status;
ok(await post({ action: 'install', names: ['flutter; rm -rf /'] }) === 400,
   'a name that is not in the catalog is refused');
ok(await post({ action: 'install', names: [] }) === 400, 'an empty selection is refused');
// A second job is refused while one runs. The message names which one: the
// version check that runs by itself once a day says so, rather than claiming
// an install nobody started.
const clash = await page.evaluate(async () => {
  const go = b => fetch('/api/toolchains', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  await go({ action: 'check', names: [] });
  const r = await go({ action: 'install', names: ['swift'] });
  const j = await r.json().catch(() => ({}));
  return { status: r.status, error: j.error || '' };
});
ok(clash.status === 409 && /already running/.test(clash.error),
   `...and a second job while one runs is refused (${clash.error})`);
await waitLocal(t => t.job && !t.job.running);
ok(await post({ action: 'sudo', names: ['flutter'] }) === 400, 'an unknown action is refused');

// ---- what needs what --------------------------------------------------------
// A toolchain that needs another says so, and so does the one that is
// needed: the Library's card says what comes with it, the Installed page's
// row what needs it.
{
  const ndk = item(tc, 'android:ndk'), jdk = item(tc, 'jdk');
  ok(ndk?.needs?.includes('android-tools') && jdk?.needed_by?.includes('android-tools'),
     `the store says what each toolchain needs and what needs it (${ndk?.needs} | ${jdk?.needed_by})`);
  const said = await page.evaluate(([n, j]) => ({
    lib: libDetail({ ...n, kind: 'toolchain', tier: 'official' }).replace(/<[^>]+>/g, ''),
    inst: instAboutLines({ ...j, kind: 'toolchain' }).replace(/<[^>]+>/g, ''),
  }), [ndk, jdk]);
  ok(/Needs android-tools, installed with it/.test(said.lib),
     `a toolchain's card says what it needs, installed with it (${ndk?.label})`);
  ok(/Needed by android-tools/.test(said.inst), `...and the one it needs says on its Installed row what needs it (${jdk?.label})`);
}

// ---- Remove on the Installed page --------------------------------------------
// The sandbox's store is what its census says it holds; a toolchain there is
// an Installed row with Remove, which asks first by the name its row shows
// (B65), runs the job on the node, and says under the row what the job said
// failed (the stub fails every toolchain job).
{
  const { writeFileSync, rmSync } = await import('node:fs');
  writeFileSync(`${DIR}/sandboxdata/census-extra.json`, JSON.stringify({ store_dirs: { top: ['flutter'], android: [] } }));
  let held = false;
  for (let i = 0; i < 60 && !held; i++){
    held = !!item(await api(`/api/toolchains?node=${sb.id}`), 'flutter')?.installed;
    if (!held) await sleep(500);
  }
  ok(held, 'the sandbox node reports flutter in its store');
  const ROW = `.installedtab [data-instnode="${sb.id}"] .irow[data-irow="toolchain:flutter"]`;
  await page.evaluate(id => { instNode = ''; inst = null; openInstalledOn(id); }, sb.id);
  await page.waitForSelector(`${ROW} [data-instact="remove"]`, { timeout: 20000 });
  const label = await page.evaluate(() => inst.rows.find(r => r.kind === 'toolchain' && r.name === 'flutter')?.label || '');
  const nd = page.dialogs.length;
  await page.click(`${ROW} [data-instact="remove"]`);
  let ran = false;
  for (let i = 0; i < 60 && !ran; i++){
    await sleep(500);
    ran = await page.evaluate(() => { const ok = inst?.job?.action === 'remove' && !inst.job.running && (inst.job.failed || []).includes('flutter');
      if (!ok) loadInstalled(); return ok; });
  }
  ok(page.dialogs.length === nd + 1 && !!label && page.dialogs[nd].startsWith(`Uninstall ${label} from sandbox?`),
     `Remove on an Installed row asks first, naming it as its row does (${page.dialogs.slice(nd).join(' | ') || 'nothing asked'})`);
  await page.waitForSelector(`${ROW} .sub.bad`, { timeout: 15000 }).catch(() => {});
  const why = await page.$eval(`${ROW} .sub.bad`, e => e.textContent).catch(() => '');
  ok(ran && /remove failed on the node/.test(why),
     `...runs the remove job on the node, and says under the row what failed (${why || 'nothing said'})`);
  rmSync(`${DIR}/sandboxdata/census-extra.json`, { force: true });
}

// ---- the two meanings of SDK_ROOT (B89) ----------------------------------
// On the controller SDK_ROOT is the STORE and bb appends this machine's
// scope to it. On a node the agent exports it as the scope directory
// already, because that is also what BUILDER_HOME and ANDROID_HOME are made
// from and what a CI runner's .env carries. Taken at its word on a node it
// was scoped twice (/mnt/SDK/linux-x86_64/linux-x86_64, a directory that
// does not exist) and every toolchain on that node read as not installed
// while it sat there. Shell-level, because that is where the answer is
// decided and where both machines ask for it.
{
  const { execFileSync } = await import('node:child_process');
  const { mkdtempSync, mkdirSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const { fileURLToPath } = await import('node:url');
  const LIB = fileURLToPath(new globalThis.URL('../../lib/common.sh', import.meta.url));
  const sh = (root) => execFileSync('bash', ['-c',
    `. ${JSON.stringify(LIB)}; printf '%s %s' "$(sdk_store_root)" "$(sdk_root)"`],
    { encoding: 'utf8', env: { ...process.env, SDK_ROOT: root } }).trim();
  const scope = execFileSync('bash', ['-c', `. ${JSON.stringify(LIB)}; sdk_scope`],
                             { encoding: 'utf8' }).trim();
  const store = mkdtempSync(`${tmpdir()}/bbstore-`);
  mkdirSync(`${store}/${scope}`);
  ok(sh(`${store}/${scope}`) === `${store} ${store}/${scope}`,
     `SDK_ROOT naming the scope directory resolves to the store and back to itself (${sh(`${store}/${scope}`)})`);
  ok(sh(store) === `${store} ${store}/${scope}`,
     '...and naming the store still means the store, which is what the controller sets');
  // ...and a store somebody really did call linux-x86_64 is taken at its
  // word, because the scope directory inside it settles which it is.
  const odd = mkdtempSync(`${tmpdir()}/bbodd-`);
  mkdirSync(`${odd}/${scope}/${scope}`, { recursive: true });
  ok(sh(`${odd}/${scope}`) === `${odd}/${scope} ${odd}/${scope}/${scope}`,
     '...while a store whose own name is the scope keeps it, since it holds one');

  // ---- what a build here can use (R100) ------------------------------------
  // The newest platform is the compileSdk ceiling and the Gradle cache is
  // what a build has without fetching: read from the directories, said in
  // one block, so a session does not list platforms/ and ~/.gradle by hand
  // (Shebang-DevBoard, 30 Sep).
  const sdk = `${store}/${scope}/android`, gh = mkdtempSync(`${tmpdir()}/bbgradle-`);
  for (const d of ['platforms/android-35', 'platforms/android-36', 'build-tools/36.0.0']) mkdirSync(`${sdk}/${d}`, { recursive: true });
  for (const d of ['wrapper/dists/gradle-9.7.1-bin', 'caches/modules-2/files-2.1/com.android.tools.build/gradle/9.4.1',
                   'caches/modules-2/files-2.1/org.jetbrains.kotlin/kotlin-gradle-plugin/2.4.20']) mkdirSync(`${gh}/${d}`, { recursive: true });
  const SDK = LIB.replace(/common\.sh$/, 'sdk.sh');
  const builds = execFileSync('bash', ['-c', `. ${JSON.stringify(LIB)}; . ${JSON.stringify(SDK)}; sdk_builds_with ${JSON.stringify(sdk)}`],
                              { encoding: 'utf8', env: { ...process.env, GRADLE_USER_HOME: gh } });
  ok(/== builds with ==/.test(builds) && /platforms\s+35 36\n/.test(builds)
     && /compileSdk\s+up to 36: a library that wants a newer platform fails checkDebugAarMetadata; the operator adds one from the Library/.test(builds)
     && /build-tools\s+36\.0\.0/.test(builds),
     `bb toolchains says the platforms, the compileSdk ceiling and the build-tools as a build reads them (${builds.split('\n')[2]?.trim()})`);
  ok(/gradle\s+9\.7\.1 \(wrapper distributions, no download\)/.test(builds) && /AGP\s+9\.4\.1\n/.test(builds)
     && /kotlin\s+2\.4\.20\n/.test(builds) && !/compose BOM/.test(builds),
     '...and what the Gradle cache holds, naming only what is there');
  const bare = execFileSync('bash', ['-c', `. ${JSON.stringify(LIB)}; . ${JSON.stringify(SDK)}; sdk_builds_with ${JSON.stringify(`${odd}/none`)}`],
                            { encoding: 'utf8', env: { ...process.env, GRADLE_USER_HOME: `${odd}/nogradle` } });
  ok(/platforms\s+none: nothing compiles here until the operator adds one from the Library/.test(bare)
     && /modules\s+none cached yet: the first build fetches them/.test(bare),
     '...and an empty store and an empty cache are said as such rather than as a blank');
  // The NVIDIA driver's line (R102), read from this machine's sysfs and
  // modinfo: none without a card, and each of the states the row has.
  const sysr = mkdtempSync(`${tmpdir()}/bbsys-`), fbin = mkdtempSync(`${tmpdir()}/bbbin-`);
  const devd = `${sysr}/bus/pci/devices/0000:04:00.0`;
  mkdirSync(devd, { recursive: true });
  const { writeFileSync: wf, symlinkSync: ln, rmSync: rm } = await import('node:fs');
  wf(`${devd}/vendor`, '0x10de\n'); wf(`${devd}/class`, '0x030000\n');
  const nv = (bound, inst, loaded) => {
    rm(`${devd}/driver`, { force: true });
    if (bound){ mkdirSync(`${sysr}/bus/pci/drivers/${bound}`, { recursive: true }); ln(`${sysr}/bus/pci/drivers/${bound}`, `${devd}/driver`); }
    rm(`${sysr}/module`, { recursive: true, force: true });
    if (loaded){ mkdirSync(`${sysr}/module/nvidia`, { recursive: true }); wf(`${sysr}/module/nvidia/version`, loaded + '\n'); }
    wf(`${fbin}/modinfo`, inst ? `#!/bin/sh\necho ${inst}\n` : '#!/bin/sh\nexit 1\n', { mode: 0o755 });
    return execFileSync('bash', ['-c', `. ${JSON.stringify(LIB)}; . ${JSON.stringify(SDK)}; sdk_nvidia_line`],
      { encoding: 'utf8', env: { ...process.env, BB_SYS_ROOT: sysr, PATH: `${fbin}:${process.env.PATH}` } }).trim();
  };
  const lines = [nv('nouveau', '', ''), nv('nouveau', '580.95.05', ''), nv('nvidia', '580.95.05', '580.95.05'),
                 nv('nvidia', '580.95.05', '575.64'), nv('nvidia', '', '580.95.05')];
  ok(/^not installed: nouveau has the card/.test(lines[0]) && /^580\.95\.05 installed; it takes the card when the machine restarts$/.test(lines[1])
     && /^580\.95\.05, running the card/.test(lines[2]) && /^575\.64 running the card; 580\.95\.05 takes over/.test(lines[3])
     && /^removed; it keeps the card until the machine restarts$/.test(lines[4]),
     `bb toolchains says where the NVIDIA driver stands, read from the machine (${lines.map(x => x.slice(0, 24)).join(' | ')})`);
  // ...and the container toolkit's line beside it, by its own tool. On a
  // PATH of this check's own, so a machine that really has the toolkit
  // reads the same as one that does not.
  const kbin = mkdtempSync(`${tmpdir()}/bbkit-`);
  for (const t of ['cat', 'sed', 'head', 'readlink', 'dirname'])
    ln(execFileSync('bash', ['-c', `command -v ${t}`], { encoding: 'utf8' }).trim(), `${kbin}/${t}`);
  const bash = execFileSync('bash', ['-c', 'command -v bash'], { encoding: 'utf8' }).trim();
  const kit = () => execFileSync(bash, ['-c', `. ${JSON.stringify(SDK)}; sdk_nvidia_container_line`],
    { encoding: 'utf8', env: { ...process.env, BB_SYS_ROOT: sysr, PATH: kbin } }).trim();
  const nokit = kit();
  wf(`${kbin}/nvidia-ctk`, '#!/bin/sh\necho "NVIDIA Container Toolkit CLI version 1.17.8"\necho "commit: abc"\n', { mode: 0o755 });
  const haskit = kit();
  ok(/^no container toolkit: a container here cannot reserve the card/.test(nokit)
     && /^toolkit 1\.17\.8: a compose file reserves the card with deploy\.resources\.reservations\.devices/.test(haskit),
     `...and whether a container there can be given the card, by the container toolkit's own tool (${nokit.slice(0, 20)} | ${haskit.slice(0, 14)})`);
  wf(`${devd}/vendor`, '0x1234\n');
  ok(nv('', '', '') === '' && kit() === '', '...and nothing at all on a machine with no NVIDIA card');
}

// ---- the versions a project pins are cards on its node's Library (B712) ------
// A store remade at the newest versions only stranded a project pinning
// NDK 29 and build-tools 36: nothing to install. The pins are read off the
// project's Gradle files, each a row named for the project, the store's own
// listing saying whether it is held.
{
  const { writeFileSync, mkdirSync, rmSync } = await import('node:fs');
  await api('/api/prefs', { project: 'alpha', node: sb.id });
  mkdirSync(`${DIR}/ws/alpha/app`, { recursive: true });
  writeFileSync(`${DIR}/ws/alpha/app/build.gradle.kts`,
    'android {\n    compileSdk = 37\n    ndkVersion = "29.0.14206865"\n    buildToolsVersion = "36.0.0"\n}\n');
  writeFileSync(`${DIR}/sandboxdata/census-extra.json`, JSON.stringify({ store_dirs: {
    top: [], android: ['ndk', 'build-tools', 'platforms'],
    versions: { ndk: ['30.0.16248370'], 'build-tools': ['37.0.0'], platforms: ['android-37.0'] } } }));
  let got = {};
  for (let i = 0; i < 60; i++){
    got = await api(`/api/toolchains?node=${sb.id}`);
    if ((got.items || []).some(r => r.name === 'android:ndk;29.0.14206865')) break;
    await sleep(500);
  }
  const by = Object.fromEntries((got.items || []).map(r => [r.name, r]));
  const ndk = by['android:ndk;29.0.14206865'], bt = by['android:build-tools;36.0.0'], plat = by['android:platforms;android-37'];
  ok(ndk && !ndk.installed && /^Needed by alpha \(app\/build\.gradle\.kts\)/.test(ndk.about) && /lacks it/.test(ndk.about)
     && ndk.label === 'Android NDK 29.0.14206865' && ndk.terms.length,
     `an NDK a project pins and the store lacks is a row to install, named for the project (${JSON.stringify(ndk || got).slice(0, 160)})`);
  ok(bt && !bt.installed && bt.label === 'Android SDK Build-Tools 36.0.0',
     `...and so is a build-tools version (${bt?.label})`);
  ok(plat && plat.installed && plat.label === 'Android SDK Platform 37' && /holds it/.test(plat.about),
     `...while a compileSdk the store holds (android-37.0) reads installed (${plat?.about?.slice(-30)})`);
  ok(!Object.keys(by).some(k => /system-images/.test(k)),
     'no image row: the level a project compiles against is the Emulator page\'s question (B720)');
  await toLibrary();
  await page.evaluate(() => loadLibrary());
  const PIN = '.doc .librarytab .lcard[data-lrow="toolchain:android:ndk;29.0.14206865"]';
  const drawn = await page.waitForSelector(`${PIN} [data-libact="install"]`, { timeout: 20000 }).then(() => true, () => false);
  ok(drawn && await page.$('.doc .librarytab .lcard[data-lrow="toolchain:android:build-tools;36.0.0"] [data-libact="install"]') !== null,
     '...and the node\'s Library draws them as cards with Install, like any toolchain');
  // Installed like any row: the versioned id is a name the node's catalog
  // offered, so the handler takes it, where a name off any catalog is
  // refused. Google's terms are a person's to accept, named, before anything
  // installs under them; a pinned version is its row's, and the server keeps
  // who did.
  const unasked = await api('/api/toolchains', { action: 'install', names: ['android:ndk;29.0.14206865'], node: sb.id });
  ok(/accepts Google's Android SDK terms/.test(unasked.error || '') && unasked.accept?.[0]?.url,
     `an install under an agreement is refused until it is accepted, naming it with its link (${unasked.error})`);
  const queued = await api('/api/toolchains', { action: 'install', names: ['android:ndk;29.0.14206865'], node: sb.id, accept: ["Google's Android SDK terms"] });
  ok(queued.ok && /^j_/.test(queued.job || ''), `Install takes a pinned version by its id (${queued.job || queued.error})`);
  const stray = await api('/api/toolchains', { action: 'install', names: ['android:ndk;1.2.3'], node: sb.id, accept: ["Google's Android SDK terms"] });
  ok(/nothing selected/.test(stray.error || ''), `...and a version nobody pins is still refused (${stray.error})`);
  await api('/api/toolchains', { action: 'abort', node: sb.id });
  rmSync(`${DIR}/ws/alpha/app`, { recursive: true, force: true });
  rmSync(`${DIR}/sandboxdata/census-extra.json`, { force: true });
  await api('/api/prefs', { project: 'alpha', node: '' });
}

// ---- tool packs (R77) ------------------------------------------------------
// An administrator looks at a pack by its repository, reads what it would
// download and run, adds it at that commit, finds it among the Library's
// cards as sideloaded, and removes it. The repository is on disk, which the
// harness lets the server fetch (BB_TOOLPACKS_FILE_URLS). The dialog opens
// from the Library's Add your own and from a pack card's Edit.
{
  const { execFileSync } = await import('node:child_process');
  const { mkdirSync, writeFileSync } = await import('node:fs');
  const repo = `${DIR}/packrepo`;
  mkdirSync(`${repo}/bin`, { recursive: true });
  writeFileSync(`${repo}/bin/hexkit`, '#!/bin/sh\necho hexkit\n', { mode: 0o755 });
  writeFileSync(`${repo}/GUIDE.md`, 'Dump before you patch.');
  writeFileSync(`${repo}/bbtool.json`, JSON.stringify({ name: 'hexkit', label: 'Hex kit', about: 'Looks inside binaries.',
    platforms: ['linux/amd64', 'linux/arm64'], layout: { bin: ['bin'], tool: 'bin/hexkit' }, guidance: 'GUIDE.md',
    verbs: { dump: { about: 'A file as hex.', usage: 'FILE', run: ['{dir}/bin/hexkit', 'dump', '{args}'] } } }));
  const g = (...a) => execFileSync('git', a, { cwd: repo, encoding: 'utf8',
    env: { ...process.env, GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@t', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@t' } }).trim();
  g('init', '-q'); g('add', '-A'); g('commit', '-qm', 'pack');
  const commit = g('rev-parse', 'HEAD');
  const ADD = '.pane .doc.on .librarytab [data-libadd], .pane .bar [data-libadd]';
  const EDIT = n => `.doc.on .librarytab .lcard[data-lrow="pack:${n}"] [data-libact="edit"][data-libname="${n}"]`;
  // A pack's card, drawn from a fresh read of the Library.
  const packCard = async n => {
    await page.evaluate(() => loadLibrary());
    await page.waitForSelector(EDIT(n), { timeout: 20000 });
  };
  const addYourOwn = async () => {
    await page.click(ADD);
    await page.waitForSelector('#tpmodal:not([hidden]) [data-tpwhat="pack"]', { timeout: 15000 });
    await page.click('#tpmodal [data-tpwhat="pack"]');
  };
  await toLibrary();
  await addYourOwn();
  await page.fill('#tpmodal #tpUrl', `file://${repo}`);
  await page.click('#tpmodal [data-tplook]');
  await page.waitForSelector('#tpmodal .tpseen', { timeout: 20000 });
  const seen = await page.$eval('#tpmodal .tpseen', e => e.textContent.replace(/\s+/g, ' '));
  ok(/Hex kit hexkit at [0-9a-f]{12}/.test(seen) && /bb tool hexkit dump FILE runs \{dir\}\/bin\/hexkit dump \{args\}/.test(seen)
     && /bb help tool-hexkit/.test(seen),
     `Add your own's Look shows the pack at its commit, each verb's words and its guidance before Add (${seen.slice(0, 160)})`);
  await page.click('#tpmodal [data-tpadd]');
  await page.waitForFunction(() => (toolchains?.items || []).some(i => i.name === 'hexkit' && i.pack), null, { timeout: 20000 });
  const row = await page.evaluate(() => (toolchains.items || []).find(i => i.name === 'hexkit'));
  ok(row.pack.commit === commit && row.pack.verbs.join() === 'dump' && row.pack.by,
     `Add keeps the pack at the commit looked at (${row.pack.commit.slice(0, 12)} by ${row.pack.by})`);
  await packCard('hexkit');
  const hcard = await page.evaluate(() => {
    libOpen.add('pack:hexkit'); libRev++; drawPanes();
    const c = document.querySelector('.doc .librarytab .lcard[data-lrow="pack:hexkit"]');
    const out = { pills: [...c.querySelectorAll('.lcmeta .pill')].map(p => p.textContent.trim()),
                  detail: c.querySelector('.ldetail')?.textContent.replace(/\s+/g, ' ') || '' };
    libOpen.delete('pack:hexkit'); libRev++; drawPanes();
    return out;
  });
  ok(hcard.pills.includes('sideloaded') && /From .*packrepo at [0-9a-f]{12}, added by .*A session has bb tool hexkit/.test(hcard.detail),
     `its card wears sideloaded with Edit, its Details saying where it came from and what a session gets (${hcard.detail.slice(0, 120)})`);
  // A project's Toolchains group (R77 step 5): the pack is offered switched
  // off, since adding a pack hands it to no project, and switched on and
  // saved it is among the packs the project's sessions use.
  await page.evaluate(() => renameProject('alpha', 'all'));
  await page.waitForSelector('#rnTools input[data-pack][value="hexkit"]', { timeout: 20000 });
  ok(!await page.$eval('#rnTools input[data-pack][value="hexkit"]', i => i.checked),
     'a project\'s Toolchains group offers the new pack switched off');
  await page.$eval('#rnTools input[data-pack][value="hexkit"]', i => { i.checked = true; i.dispatchEvent(new Event('change')); });
  const saveErr = await sectSave(page, 'tools');
  const packsOn = ((await api('/api/status')).projects || []).find(p => p.name === 'alpha')?.prefs?.packs_on || [];
  ok(!saveErr && packsOn.join() === 'hexkit', `...and switched on and saved, the project's sessions may use it (${saveErr || packsOn.join() || 'none kept'})`);
  await page.evaluate(() => closeRename());
  await api('/api/prefs', { project: 'alpha', packs_on: '' });
  // An update (R77 step 6): the repository moves on, and Edit looks for a
  // newer commit as it opens and shows what it changes, verb by verb,
  // before Update keeps it.
  writeFileSync(`${repo}/bbtool.json`, JSON.stringify({ name: 'hexkit', label: 'Hex kit', about: 'Looks inside binaries.',
    platforms: ['linux/amd64', 'linux/arm64'], layout: { bin: ['bin'], tool: 'bin/hexkit' }, guidance: 'GUIDE.md',
    verbs: { dump: { about: 'A file as hex.', usage: 'FILE', run: ['{dir}/bin/hexkit', 'dump', '--wide', '{args}'] },
             strings: { about: 'Its strings.', usage: 'FILE', run: ['{dir}/bin/hexkit', 'strings', '{args}'] } } }));
  g('commit', '-qam', 'later');
  const newer = g('rev-parse', 'HEAD');
  await toLibrary();
  await packCard('hexkit');
  await page.click(EDIT('hexkit'));
  await page.waitForSelector('#tpmodal:not([hidden]) .tpseen', { timeout: 20000 });
  const diff = await page.$eval('#tpmodal .tpseen', e => e.textContent.replace(/\s+/g, ' '));
  ok(/dump --wide \{args\} changed was \{dir\}\/bin\/hexkit dump \{args\}/.test(diff) && /strings FILE runs .* new/.test(diff),
     `the card's Edit says what a newer commit changes: a changed verb with what it was, a new one marked (${diff.slice(0, 200)})`);
  await page.click('#tpmodal [data-tpadd]');
  await page.waitForFunction(c => (toolchains?.items || []).find(i => i.name === 'hexkit')?.pack?.commit === c, newer, { timeout: 20000 });
  ok(true, '...and Update keeps the pack at the newer commit');
  // From the vetted catalog (R169 step 4): a pack kept at the index's pin
  // wears vetted, a sha256 the index does not pin is refused (B440), and
  // when the index pins a newer commit the card offers Catalog update: the
  // dialog on that pin with what it changes marked, Update keeping it there
  // with its tier (B442). The catalog's address is a dead one here, so each
  // read falls back to the index kept in the state.
  {
    const { createHash } = await import('node:crypto');
    const { rmSync } = await import('node:fs');
    const sha = c => createHash('sha256').update(execFileSync('git', ['-C', repo, 'archive', '--format=tar', c])).digest('hex');
    const pin = c => writeFileSync(`${DIR}/state/catalog-index.json`, JSON.stringify({ fetched_at: 0, packs: [{ name: 'hexkit',
      url: `file://${repo}`, commit: c, sha256: sha(c), tier: 'vetted', path: '', about: 'Looks inside binaries.', platforms: ['linux/amd64'] }] }));
    await api('/api/settings', { set: { catalog_url: 'http://127.0.0.1:9/' } });
    pin(newer);
    const forged = await api('/api/toolpacks', { action: 'add', url: `file://${repo}`, commit: newer, sha256: '0'.repeat(64) });
    ok(/not the one the vetted catalog pins/.test(forged.error || ''), `a sha256 the index does not pin keeps nothing as vetted (${forged.error})`);
    const kept = await api('/api/toolpacks', { action: 'add', url: `file://${repo}`, commit: newer, sha256: sha(newer) });
    ok(kept.pack?.tier === 'vetted', `the index's own pin is kept as vetted (${kept.pack?.tier || kept.error})`);
    writeFileSync(`${repo}/bbtool.json`, JSON.stringify({ name: 'hexkit', label: 'Hex kit', about: 'Looks inside binaries.',
      platforms: ['linux/amd64', 'linux/arm64'], layout: { bin: ['bin'], tool: 'bin/hexkit' }, guidance: 'GUIDE.md',
      verbs: { dump: { about: 'A file as hex.', usage: 'FILE', run: ['{dir}/bin/hexkit', 'dump', '--wide', '{args}'] },
               strings: { about: 'Its strings.', usage: 'FILE', run: ['{dir}/bin/hexkit', 'strings', '-a', '{args}'] } } }));
    g('commit', '-qam', 'vetted again');
    const next = g('rev-parse', 'HEAD');
    pin(next);
    const REPIN = `.doc.on .librarytab .lcard[data-lrow="pack:hexkit"] [data-libact="repin"]`;
    await page.evaluate(() => { loadToolchains(); loadLibrary(); });
    await page.waitForSelector(REPIN, { timeout: 20000 });
    const vcard = await page.evaluate(() => [...document.querySelectorAll('.doc .librarytab .lcard[data-lrow="pack:hexkit"] .lcmeta .pill')].map(p => p.textContent.trim()));
    ok(vcard.includes('vetted'), `the kept pack's card wears vetted (${vcard.join(', ')})`);
    await page.click(REPIN);
    await page.waitForSelector('#tpmodal:not([hidden]) .tpseen', { timeout: 20000 });
    const upd = await page.$eval('#tpmodal', e => e.textContent.replace(/\s+/g, ' '));
    ok(/strings -a \{args\} changed was \{dir\}\/bin\/hexkit strings \{args\}/.test(upd) && /the vetted catalog's newer pin/.test(upd)
       && upd.includes(next.slice(0, 12)),
       `Catalog update opens the dialog on the index's newer pin, what it changes marked (${upd.slice(0, 240)})`);
    await page.click('#tpmodal [data-tpadd]');
    await page.waitForFunction(c => (toolchains?.items || []).find(i => i.name === 'hexkit')?.pack?.commit === c, next, { timeout: 20000 });
    const after = await page.evaluate(() => (toolchains.items || []).find(i => i.name === 'hexkit').pack.tier);
    ok(after === 'vetted', `...and Update keeps it at that pin, still vetted (${after})`);
    await api('/api/settings', { set: { catalog_url: 'https://raw.githubusercontent.com/aquilaelabs/builderbot-catalog/main/' } });
    rmSync(`${DIR}/state/catalog-index.json`, { force: true });
  }
  const bad = await api('/api/toolpacks', { action: 'preview', url: `file://${DIR}/nowhere` });
  ok(/could not fetch/.test(bad.error || ''), `a repository that is not there is said so (${bad.error})`);
  // B84: installed on a node, Remove is refused on the form, saying where,
  // before anything is asked: its files would stay in that store with no
  // row left to uninstall them from, and the pack added back would read
  // installed.
  await api('/api/prefs', { project: 'alpha', packs_on: 'hexkit' });
  writeFileSync(`${DIR}/sandboxdata/census-extra.json`, JSON.stringify({ store_dirs: { top: ['hexkit'], android: [] } }));
  const heldBy = async want => {
    for (let i = 0; i < 60; i++){
      const t = await api(`/api/toolchains?node=${sb.id}`);
      if (!!item(t, 'hexkit')?.installed === want) return true;
      await sleep(500);
    }
    return false;
  };
  ok(await heldBy(true), 'the sandbox node reports the pack in its store');
  page.dialogs = [];
  await packCard('hexkit');
  await page.click(EDIT('hexkit'));
  await page.waitForSelector('#tpmodal:not([hidden]) [data-tprm="hexkit"]', { timeout: 15000 });
  // Edit looks for a newer commit as it opens; its answer redraws the form.
  await page.waitForFunction(() => !tpForm.busy, null, { timeout: 20000 });
  await page.click('#tpmodal [data-tprm="hexkit"]');
  await page.waitForSelector('#tpmodal .hint.bad', { timeout: 15000 });
  const refused = await page.$eval('#tpmodal .hint.bad', e => e.textContent);
  const kept = await api('/api/toolpacks', { action: 'remove', name: 'hexkit' });
  const still = ((await api(`/api/toolchains?node=${sb.id}`)).items || []).some(i => i.name === 'hexkit');
  ok(/hexkit is installed on sandbox: uninstall it there first/.test(refused) && !page.dialogs.length
     && still && /installed on sandbox/.test(kept.error || ''),
     `Remove is refused while a node holds the pack, saying where, with nothing asked, and the route refuses it too (${refused})`);
  const { rmSync } = await import('node:fs');
  rmSync(`${DIR}/sandboxdata/census-extra.json`, { force: true });
  ok(await heldBy(false), '...and once that store no longer holds it...');
  await page.click('#tpmodal [data-tprm="hexkit"]');
  await page.waitForFunction(() => !(toolchains?.items || []).some(i => i.name === 'hexkit'), null, { timeout: 20000 });
  await page.evaluate(() => loadLibrary());
  await page.waitForFunction(() => lib && !lib.rows.some(r => r.kind === 'pack' && r.name === 'hexkit'), null, { timeout: 20000 });
  ok(!await page.$('.doc .librarytab .lcard[data-lrow="pack:hexkit"]'), '...Remove takes it out of the catalog, and its card goes');
  // B85: a project that had switched it on opens its Toolchains group
  // unchanged: the saved list still names the pack, which the form cannot
  // draw.
  await page.evaluate(() => renameProject('alpha', 'all'));
  await page.waitForFunction(() => rnToolsList !== null, null, { timeout: 20000 });
  const group = await page.evaluate(() => ({ dirty: !document.querySelector('.rnbar[data-rnbar="tools"] [data-rnsave]')?.disabled,
    said: document.querySelector('.rnbar[data-rnbar="tools"]')?.textContent.replace(/\s+/g, ' ').trim() || '' }));
  ok(!group.dirty && !/changed/.test(group.said),
     `...and a project that used it opens its Toolchains group with nothing unsaved (${JSON.stringify(group)})`);
  await page.evaluate(() => closeRename());
  await api('/api/prefs', { project: 'alpha', packs_on: '' });

  // A pack made here, with no repository of its own: a pasted bbtool.json,
  // looked at, added, edited in place as a new version, and an upload of
  // the pack's files. Each is kept as a commit on the controller.
  const pasted = { name: 'wordy', label: 'Wordy', about: 'Counts words.', platforms: ['linux/amd64', 'linux/arm64'],
    install: { steps: [['sh', '-c', 'mkdir -p "$1/bin"', 'x', '{dir}']] },
    verbs: { count: { about: 'Words in a file.', usage: 'FILE', run: ['{dir}/bin/wordy', '{args}'] } } };
  await toLibrary();
  await addYourOwn();
  const tpH = () => page.$eval('#tpmodal .box', b => Math.round(b.getBoundingClientRect().height));
  await page.waitForTimeout(500);              // the dialog's own opening scale
  const repoH = await tpH();
  await page.click('#tpmodal [data-tpfrom="paste"]');
  ok(Math.abs(await tpH() - repoH) <= 1, `the tool pack dialog keeps its size from A repository to Paste (${repoH} then ${await tpH()})`);
  await page.fill('#tpText', JSON.stringify(pasted, null, 1));
  await page.click('#tpmodal [data-tplook]');
  await page.waitForSelector('#tpmodal .tpseen', { timeout: 20000 });
  const pseen = await page.$eval('#tpmodal .tpseen', e => e.textContent.replace(/\s+/g, ' '));
  ok(/Wordy wordy as given here, 1 file/.test(pseen) && /Installs by copying these files to the node/.test(pseen)
     && /bb tool wordy count FILE runs \{dir\}\/bin\/wordy \{args\}/.test(pseen),
     `a pasted bbtool.json is looked at like a repository's: what it installs and what each verb runs (${pseen.slice(0, 160)})`);
  await page.click('#tpmodal [data-tpadd]');
  await page.waitForFunction(() => (toolchains?.items || []).find(i => i.name === 'wordy')?.pack?.here, null, { timeout: 20000 });
  await packCard('wordy');
  const wcard = await page.evaluate(() => {
    libOpen.add('pack:wordy'); libRev++; drawPanes();
    const c = document.querySelector('.doc .librarytab .lcard[data-lrow="pack:wordy"]');
    const out = { pills: [...c.querySelectorAll('.lcmeta .pill')].map(p => p.textContent.trim()),
                  detail: c.querySelector('.ldetail')?.textContent.replace(/\s+/g, ' ') || '' };
    libOpen.delete('pack:wordy'); libRev++; drawPanes();
    return out;
  });
  ok(wcard.pills.includes('sideloaded') && /Made here/.test(wcard.detail),
     `...Add keeps it, its card wearing sideloaded and saying it was made here (${wcard.detail.slice(0, 100)})`);
  const first = await page.evaluate(() => toolchains.items.find(i => i.name === 'wordy').pack.commit);
  // Edit opens on its bbtool.json as kept; a change is a new version.
  await page.click(EDIT('wordy'));
  await page.waitForFunction(() => /"Wordy"/.test(document.getElementById('tpText')?.value || ''), null, { timeout: 20000 });
  await page.fill('#tpText', JSON.stringify({ ...pasted, label: 'Wordy two' }));
  await page.click('#tpmodal [data-tplook]');
  await page.waitForSelector('#tpmodal [data-tpadd]', { timeout: 20000 });
  ok(await page.$eval('#tpmodal [data-tpadd]', e => e.textContent) === 'Update',
     '...the card\'s Edit opens on its bbtool.json, and a changed one is offered as an Update');
  await page.click('#tpmodal [data-tpadd]');
  await page.waitForFunction(c => { const p = (toolchains?.items || []).find(i => i.name === 'wordy');
    return p && p.label === 'Wordy two' && p.pack.commit !== c; }, first, { timeout: 20000 });
  ok(true, '...and Update keeps it as a new commit made here');
  // An upload of the pack's files, a tarball with one top folder.
  const up = `${DIR}/uppack/stamp`;
  mkdirSync(`${up}/bin`, { recursive: true });
  writeFileSync(`${up}/bin/stamp`, '#!/bin/sh\ndate\n', { mode: 0o755 });
  writeFileSync(`${up}/GUIDE.md`, 'Stamp what you build.');
  writeFileSync(`${up}/bbtool.json`, JSON.stringify({ name: 'stamp', platforms: ['linux/amd64', 'linux/arm64'],
    layout: { bin: ['bin'], tool: 'bin/stamp' }, verbs: { now: { run: ['{dir}/bin/stamp'] } }, guidance: 'GUIDE.md' }));
  execFileSync('tar', ['-czf', `${DIR}/uppack.tgz`, '-C', `${DIR}/uppack`, 'stamp']);
  await addYourOwn();
  await page.click('#tpmodal [data-tpfrom="upload"]');
  await page.setInputFiles('#tpFile', `${DIR}/uppack.tgz`);
  await page.click('#tpmodal [data-tplook]');
  await page.waitForSelector('#tpmodal .tpseen', { timeout: 20000 });
  const useen = await page.$eval('#tpmodal .tpseen', e => e.textContent.replace(/\s+/g, ' '));
  ok(/as given here, 3 files/.test(useen) && /bb help tool-stamp/.test(useen),
     `an uploaded archive of the pack's files is looked at the same way, its guidance with it (${useen.slice(0, 160)})`);
  await page.click('#tpmodal [data-tpadd]');
  await page.waitForFunction(() => (toolchains?.items || []).find(i => i.name === 'stamp')?.pack?.here, null, { timeout: 20000 });
  ok(true, '...and Add keeps it made here');
  for (const n of ['wordy', 'stamp']){
    page.dialogs = [];
    await packCard(n);
    await page.click(EDIT(n));
    await page.waitForSelector(`#tpmodal:not([hidden]) [data-tprm="${n}"]`, { timeout: 15000 });
    await page.click(`#tpmodal [data-tprm="${n}"]`);
    await page.waitForFunction(x => !(toolchains?.items || []).some(i => i.name === x), n, { timeout: 20000 });
  }
  ok(true, 'a pack made here is removed from its card\'s Edit like any other');
}

// 400s and 409s are asked for on purpose above; the browser logs a failed
// fetch either way.
const errs = page.errors.filter(e => !/status of (400|409)/.test(e));
ok(errs.length === 0, `zero console errors${errs.length ? ': ' + errs.join(' | ') : ''}`);

await done(browser);
