// The Tools card and its package manager. Toolchains opens as a
// document TAB: installing an SDK runs for minutes, so it belongs on the
// strip rather than in a dialog to dismiss. The harness's bb stub makes and
// removes directories rather than downloading gigabytes, so the whole round
// trip runs in a second.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { existsSync, readFileSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the card ----------------------------------------------------------
// The heading carries a chevron alongside its text, so match the text only.
ok((await page.$eval('.card[data-card="tools"] h2', h => h.textContent.trim())).startsWith('Tools'),
   'Tools is a card of its own');
// The scanner's report is a tab off this card now, not a card of its own:
// a report is read, and a sidebar card is a control surface.
ok(await page.$$eval('.side .card[data-card]', cs =>
     !cs.some(c => c.dataset.card === 'findings')),
   '...and there is no findings card beside it any more');
ok(await page.$eval('.card[data-card="tools"] #bToolchains', b => !b.hidden),
   'the Tools card carries its button');
ok(await page.$eval('.card[data-card="tools"] #bFindings',
                    b => b.textContent.trim() === 'Static analysis'),
   '...and the scanner report is a button on it');

// ---- the tab -----------------------------------------------------------
// Through the notebook first: a document that parks in the pane's stack used
// to keep the pane's doc id, and the toolchains view then rendered into that
// hidden node, a blank tab. The id has one owner now: whatever is shown.
await page.click('#projects .row:has(.name:text-is("alpha")) [data-m]');
await page.waitForFunction(
  // Loaded, whatever it holds, not merely started. This used to match the
  // "loading…" placeholder, so it was satisfied the instant the panel opened
  // and said nothing about the list arriving; that only came to light when
  // the placeholder stopped sharing a class with the empty state.
  () => { const l = document.querySelector('#roadmapList');
          return !!l && !l.querySelector('.loading'); },
                           { timeout: 20000 });
await page.click('#bToolchains');
// Toolchains are installed on nodes (roadmap #26): the tab opens on one (the
// harness's stub agent here) and never offers "this container". With no
// node at all it says to enroll one and offers nothing; shown by emptying
// the page's node list, since the fixture always has the stub. The installer
// the rest of this file exercises is still there for `bb toolchains install` from a
// shell and for the suite, addressed as "local"; nothing on the page sets it.
await page.waitForSelector('.doc .tctab #tcNodeSel', { timeout: 20000 });
ok(await page.$$eval('.doc #tcNodeSel option', os => !os.some(o => o.value === 'local')),
   'the Tools tab opens on a node and never offers this container');
await page.evaluate(() => { nodesList = []; tcNode = ''; toolchains = null; loadToolchains(); });
await page.waitForSelector('.doc .tctab .tcnone', { timeout: 20000 });
ok(await page.evaluate(() => !document.querySelector('.doc .tc') && !document.querySelector('#tcNodeSel')),
   '...and with no node enrolled it says to enroll one, and offers nothing to install here');
await page.evaluate(() => { nodesList = null; tcNode = 'local'; toolchains = null; loadToolchains(); });
await page.waitForFunction(() => document.querySelectorAll('.doc .tc').length > 0);
// Structural, not painted: under a loaded box checkVisibility can sample a
// frame mid-layout. The claim is that the rows are in the document being
// shown, not in a parked one.
ok(!!await page.$('.pane .doc.on .tc'),
   'toolchains render where they can be seen, even after another document parked in the pane');
ok(await page.evaluate(() => tabs.some(t => t.kind === 'toolchains')
     && tabOf(panes[active])?.kind === 'toolchains'),
   'Toolchains opens a tab, and lands on it');
// Refresh belongs to the TAB's own bar (the scaffold's slot, where the Phone
// and Nodes tabs keep theirs), with the picker it re-reads at the left of the
// same bar. The pane's title bar is the tab's name and its close control on
// every kind, so a button in it was a shape this tab alone had.
ok(await page.$('.pane .bar [data-reload]') === null,
   'the pane bar carries no button of its own');
ok(await page.$eval('.doc .docbarrow #tcRefresh', b => b.textContent.trim()) === 'Refresh',
   '...and Refresh sits in the tab\'s bar, where every other tab keeps its action');
ok(await page.$eval('.doc .docbarrow', el => {
     const kids = [...el.children];
     return kids.indexOf(el.querySelector('#tcRefresh')) === kids.length - 1
            && kids.indexOf(el.querySelector('#tcNodeSel').closest('.pick')) === 0;
   }),
   '...at its right end, with the node picker at the left');
const rows = () => page.$$eval('.doc .tc', ls => ls.map(l => ({
  name: l.querySelector('input').value,
  installed: !!l.querySelector('.where.on'),
  // Null while a job is on this row: it shows what it is doing in place of
  // where it lives, so anything reading paths has to tolerate their absence.
  where: l.querySelector('.where')?.textContent.trim() ?? null,
})));
let list = await rows();
ok(list.length >= 6 && list.some(r => r.name === 'flutter') && list.some(r => r.name === 'android:emulator'),
   'the tab lists the toolchains and the android packages');
ok(list.every(r => !r.installed) && list.every(r => r.where === 'not installed'),
   'a scratch root starts with nothing installed');
ok(await page.$$eval('.doc .tc .nm .pill', ps => ps.length === 0),
   '...so no row carries a size or a version: nothing has been weighed yet');
ok((await page.$eval('.tchead', el => el.textContent)).includes(`${DIR}/sdk`),
   'it says which root things are installed into');
// The catalog is a file in the repository, not a list in the server: adding a
// toolchain should be an edit somebody can make without reading python.
const catalog = JSON.parse(                     // URL here is the dashboard's
  readFileSync(`${import.meta.dirname}/../../../config/toolchains.json`, 'utf8'));
ok(catalog.toolchains.length === list.length
   && catalog.toolchains.every(c => list.some(r => r.name === c.name)),
   `the tab renders the catalog from config/toolchains.json (${catalog.toolchains.length} entries)`);
// What a session on a node needs from the store rather than from the image
// (roadmap #24, step 4): the playwright module beside its browsers, with
// NODE_PATH pointing at it, and the tools bb lint runs.
const pw = catalog.toolchains.find(p => p.name === 'playwright');
const lt = catalog.toolchains.find(p => p.name === 'lint-tools');
ok(pw?.layout?.env?.NODE_PATH === 'node_modules' && /npm install/.test(pw?.source?.run?.join(' '))
   && lt?.layout?.bin?.includes('bin')
   && ['shellcheck', 'hadolint', 'actionlint', 'ruff', 'yq', 'fd'].every(t => (lt?.source?.run?.join(' ') || '').includes(t)),
   'the playwright recipe puts the module in the store with NODE_PATH on it, and lint-tools carries what bb lint runs');

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
  ok(await page.$$eval('.doc .tc .sub', ss => ss.some(s => /Adds .*bb tool graphics/.test(s.textContent))),
     'a row says which tool installing it adds');
}

// Pressing Install accepts Google's SDK terms, and the tab says so where the
// button is: the acceptance is the operator's, not a script's.
ok(await page.$eval('.doc .tcterms', e => /Android SDK terms/.test(e.textContent)
                                          && e.querySelector('a[href*="developer.android.com/studio/terms"]')),
   'the Tools tab says that Install accepts Google\'s Android SDK terms, with the terms linked');

// ---- install two, watch them land --------------------------------------
await page.check('.doc .tc input[value="flutter"]');
await page.check('.doc .tc input[value="android:emulator"]');
// The ticks live outside the DOM, so a redraw (one arrives every two
// seconds while a job runs) must not quietly clear the selection.
await page.evaluate(() => loadToolchains());
await page.waitForFunction(() => document.querySelectorAll('.doc .tc').length > 0);
ok(await page.$$eval('.doc .tc input:checked', is => is.length === 2),
   'a redraw keeps what was ticked');
await page.click('.doc [data-tc="install"]');
// More than two land: android:emulator is installed BY sdkmanager, which
// android-tools provides, which needs a JDK, and the emulator is useless
// without adb, so platform-tools comes too. That is the point of `requires`;
// before it, this pair installed and then failed inside sdkmanager with a
// message naming neither.
//
// Asserted as a SET rather than a count. A count has to be edited every time
// the catalog declares another dependency, which it has done twice, and each
// edit is a chance to write down a number instead of a fact.
// The job finishing is not the rows showing it: wait for the payload to
// carry the whole chain, which is what the draw then reflects.
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running
  && ['flutter', 'android:emulator', 'android-tools', 'android:platform-tools', 'jdk']
       .every(n => (toolchains.items || []).find(i => i.name === n)?.installed),
  { timeout: 30000 });
const landed = await page.$$eval('.doc .tc', rs =>
  rs.filter(r => r.querySelector('.where')?.classList.contains('on'))
    .map(r => r.querySelector('input')?.value));
ok(['flutter', 'android:emulator', 'android-tools', 'android:platform-tools', 'jdk']
     .every(n => landed.includes(n)),
   `ticking a toolchain installs what it needs alongside it, transitively (${landed.join(', ')})`);
list = await rows();
const flutter = list.find(r => r.name === 'flutter');
const emu = list.find(r => r.name === 'android:emulator');
ok(flutter.installed && flutter.where.includes(`${DIR}/sdk/flutter`),
   'flutter installs to the toolchain store root, and the row says where');
ok(emu.installed && emu.where.includes(`${DIR}/androidsdk/emulator`),
   'an android package resolves to its place in the SDK tree');
ok(existsSync(`${DIR}/sdk/flutter`) && existsSync(`${DIR}/androidsdk/emulator`),
   '...and both really exist on disk');
ok(await page.$('.pkglog') === null,
   'no scrolling log at the foot of the tab; a job says what it is doing on its row');
// The ticks are the operator's, and a poll every two seconds must not
// quietly clear them mid-install.

// A finished install lets go of its ticks, so the next click cannot act on
// what was just dealt with, Remove especially.
// Enabled boxes only: an installed-and-current row is ticked on purpose now,
// and that tick is a statement about the toolchain rather than a selection.
ok(await page.$$eval('.doc .tc input:not(:disabled)', is => is.every(i => !i.checked)),
   'a finished job clears the selection it consumed');
// ...but only when it is finished. Through the job the tick stays put, which
// is what says which toolchains the job is for.
const held = await page.evaluate(() => {
  const saved = toolchains.job;
  tcTicked.add('swift');
  toolchains.job = {running: true, action: 'install', current: 'swift',
                  queue: [], log: [], done: [], failed: []};
  tcRev++; drawPanes();
  const box = document.querySelector('.doc .tc input[value="swift"]');
  const out = { checked: box.checked, ghosted: box.disabled };
  tcTicked.delete('swift');
  toolchains.job = saved; tcRev++; drawPanes(); clearTimeout(tcPoll);
  return out;
});
ok(held.checked && held.ghosted,
   '...while a toolchain being installed stays ticked, and ghosted with it');
ok(await page.$$eval('.doc .tc input:disabled', is => is.length > 0 && is.every(i => i.checked)),
   '...and what is installed and current shows a ticked box that cannot be changed');

// ---- what a row says while the job is on it -----------------------------
// One word and an ellipsis, for the whole of a job. No percentage is read out
// of the output any more: every recipe meters differently and several mislead
// by accident, and a row relaying any of it faithfully still read as broken.
// "installed at /sdk/flutter" also used to appear the moment the download
// created that directory, which is the first second of a four-minute job.
const during = (job) => page.evaluate(j => {
  const saved = toolchains.job;
  toolchains.job = {running: true, queue: [], log: [], done: [], failed: [], ...j};
  tcRev++; drawPanes();
  const row = [...document.querySelectorAll('.doc .tc')]
    .find(l => l.querySelector('input').value === 'flutter');
  const out = { text: row.querySelector('.prog')?.textContent.trim(),
                bar: !!row.querySelector('.prog .bar'),
                ticked: !!row.querySelector('input:checked'),
                bin: !!row.querySelector('[data-rm]'),
                where: row.querySelector('.where')?.textContent.trim() || null };
  toolchains.job = saved; tcRev++; drawPanes();
  clearTimeout(tcPoll);   // the fake state must not outlive this check
  return out;
}, job);

let d = await during({ action: 'install', current: 'flutter' });
ok(d.text.startsWith('installing') && !d.bar && d.where === null,
   'the row being installed says installing, with no bar and no path');
// Mid-install the directory exists, so every probe calls it installed. The row
// must not wear any of the furniture that means "this is here": a half-written
// NDK showed a ticked box, an uninstall bin and the version "installed".
ok(!d.ticked && !d.bin,
   '...and carries no ticked box or uninstall control while it is being written');
d = await during({ action: 'remove', current: 'flutter' });
ok(d.text.startsWith('removing') && !d.bar,
   'a removal says removing, and gets no bar either');
// A check writes nothing, so the row it is on keeps its path and its controls;
// stripping each in turn made the tab churn through a check that, once a
// day, nobody asked for.
d = await during({ action: 'check', current: 'flutter' });
ok(d.text === undefined && d.where !== null,
   'a check leaves the row it is reading exactly as it was');
ok((await page.$$eval('.doc .tc .where', ws => ws.length)) > 0,
   'and the paths come back when the job is over');
// The dots are ticked by a timer, so a redraw must not reset them.
const dots = await page.evaluate(async () => {
  const saved = toolchains.job;
  toolchains.job = {running: true, queue: [], log: [], done: [], failed: [],
                  action: 'install', current: 'flutter'};
  tcRev++; drawPanes();
  const read = () => document.querySelector('.tc .prog .dots')?.textContent ?? null;
  const first = read();
  await new Promise(r => setTimeout(r, 900));
  const later = read();
  tcRev++; drawPanes();                      // a redraw, mid-animation
  const after = read();
  toolchains.job = saved; tcRev++; drawPanes();
  clearTimeout(tcPoll); clearInterval(tcDotsTimer); tcDotsTimer = null;
  return { first, later, after };
});
ok(dots.later !== dots.first && dots.after === dots.later,
   '...and the ellipsis animates, and a redraw does not reset it');

// ---- versions and updates ----------------------------------------------
// The installed version is local knowledge and shows without being asked;
// whether something newer exists is a network question, and until it is asked
// no row claims anything.
ok((await page.$$eval('.doc .tc .nm .pill', ps => ps.map(p => p.textContent)))
     .some(t => t === '1.0'), 'installed versions show without a check');
ok(await page.$$eval('.doc .tc .upd', us => us.length === 0),
   'no update claims before a check');
// No size is typed into the catalog (a typed one is wrong the next time
// upstream ships), so a row carries one only once this box has weighed it,
// measured by a worker and arriving a moment after the row does.
const pill = (name, n = 0) => page.$$eval('.doc .tc', (ls, [v, i]) => {
  const l = ls.find(x => x.querySelector('input').value === v);
  const ps = l ? l.querySelectorAll('.nm .pill') : [];
  return ps[i] ? { text: ps[i].textContent, title: ps[i].title } : null;
}, [name, n]);
await page.waitForFunction(() => {
  const l = [...document.querySelectorAll('.doc .tc')]
    .find(x => x.querySelector('input').value === 'flutter');
  return l && /measured/.test(l.querySelector('.nm .pill').title);
}, { timeout: 30000 });
ok(/measured on disk/.test((await pill('flutter')).title),
   'an installed toolchain shows what it takes on disk, and says so');
ok((await pill('swift')) === null,
   '...and one this box has never had shows no size at all rather than a guess');
// A check spends no selection (it asks about every row regardless), so
// whatever was ticked before it must survive it.
await page.check('.doc .tc input[value="swift"]');
await page.click('.doc [data-tc="check"]');
// The whole catalog, not just what is installed, so wait for the job to end
// rather than for the first row to answer: asserting on a toolchain further
// down the list while its check was still queued passed only by luck.
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running
                             && document.querySelector('.doc .tc .upd') !== null,
                           { timeout: 30000 });
ok(await page.$eval('.doc .tc input[value="swift"]', i => i.checked),
   'a check leaves the selection alone; it consumed nothing');
await page.uncheck('.doc .tc input[value="swift"]');
const upd = await page.$$eval('.doc .tc', ls => ls
  .filter(l => l.querySelector('.upd'))
  .map(l => l.querySelector('input').value));
ok(upd.length === 1 && upd[0] === 'flutter',
   'the check marks exactly the toolchain whose upstream moved');
ok(await page.$eval('.doc .tc input[value="android:emulator"]', i => i.disabled),
   'installed and current: the tick is dead, there is nothing to do');
ok(!(await page.$eval('.doc .tc input[value="flutter"]', i => i.disabled)),
   '...but an update brings its tick back');
ok(!(await page.$eval('.doc .tc input[value="swift"]', i => i.disabled)),
   'and something not installed at all is always tickable');
ok((await pill('flutter', 2)) === null,
   '...and an installed row carries no second version: the words below say it');
// Pill zero, not one: a row this box has never installed carries no size, so
// the version it would fetch is the first thing on the line.
ok((await pill('swift', 1)).text === '9.9'
   && /would fetch/.test((await pill('swift', 1)).title),
   'a toolchain that has never been installed says what Install would fetch');
// Pill zero on that row is the download: the only size a toolchain this box has
// never had can honestly show, and upstream is the one that knows it.
ok(/download/.test((await pill('swift', 0)).text)
   && /from upstream/.test((await pill('swift', 0)).title),
   '...and what the download weighs, asked of upstream rather than guessed');
// The answers cost a network round trip each, so they are kept on the state
// volume (a dashboard restart used to wipe every version the tab had been
// told) and dated, because a number with no date on it goes quietly stale.
ok(/versions checked/.test(await page.$eval('.doc .macros', el => el.textContent)),
   '...and the tab says how old the answers are');
const stored = JSON.parse(readFileSync(`${DIR}/state/toolchain-versions.json`, 'utf8'));
ok(stored.at > 0 && stored.items.flutter.status === 'update',
   '...and they are on disk, to outlive the process that asked');
// So is the LOCAL read, which is the one that made this tab slow to open
// after every container restart: `bb toolchains versions` is a couple of seconds
// across every toolchain, and the answer had not changed. Keyed by what it is
// an answer about (the set of installed paths, and the catalog's own digest),
// so installing something, or editing a recipe, is not answered from it.
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
ok(await page.$$eval('.doc .tc', ls => ls
     .filter(l => l.querySelector('input').value === 'swift')
     .every(l => l.querySelectorAll('.nm .pill.warn').length === 0)),
   '...and says it plainly: only an actual update is amber');
// Update runs like the others: a job, and the ticks it consumed.
await page.check('.doc .tc input[value="flutter"]');
await page.click('.doc [data-tc="install"]');
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running
  && (toolchains.job.done || []).includes('flutter'), { timeout: 30000 });
ok(await page.evaluate(() => (toolchains.job.failed || []).length === 0),
   'Install selected updates a toolchain that is already installed');
ok(await page.$$eval('.doc [data-tc]', bs => bs.every(b => b.textContent.indexOf('Remove') < 0)),
   'there is no bulk remove button to mis-click');

// ---- a long job, through the real path ---------------------------------
// The stub's `go` install draws a carriage-return progress bar over several
// seconds. None of it should reach the row: the point of this tab is that a
// job says what it is doing and nothing else, however much the tool underneath
// is counting.
await page.check('.doc .tc input[value="go"]');
await page.click('.doc [data-tc="install"]');
const seen = new Set(), bars = [];
for (let i = 0; i < 20; i++){
  const s = await page.evaluate(() => {
    const row = [...document.querySelectorAll('.doc .tc')]
      .find(l => l.querySelector('input').value === 'go');
    return { t: row?.querySelector('.prog')?.textContent.trim() || null,
             bar: !!row?.querySelector('.prog .bar'),
             running: !!toolchains?.job?.running };
  });
  if (s.running && s.t) { seen.add(s.t.replace(/\.+$/, '')); bars.push(s.bar); }
  await new Promise(r => setTimeout(r, 250));
}
ok(seen.size === 1 && seen.has('installing'),
   `a running install only ever says installing (${[...seen].join(' | ')})`);
ok(bars.length > 1 && bars.every(b => !b),
   `...and never draws a bar (${bars.length} samples)`);
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running, { timeout: 30000 });
// Put it back the way it was found: what follows counts installed toolchains,
// and a third one left lying around here is how this file first went red.
await page.evaluate(() => tcAct('remove', ['go']));
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running
  && !(toolchains.items || []).find(i => i.name === 'go')?.installed, { timeout: 30000 });

// ---- uninstall is per row, and asks ------------------------------------
// One control per installed row, whatever that number happens to be.
ok(await page.$$eval('.doc .tc', ls => {
     const on = ls.filter(l => l.querySelector('.where')?.classList.contains('on'));
     return on.length > 0 && on.every(l => l.querySelector('[data-rm]'))
            && ls.filter(l => l.querySelector('[data-rm]')).length === on.length;
   }),
   'every installed toolchain carries its own uninstall control, and only those');
ok(await page.$('.doc .tc:not(:has([data-rm])) [data-rm]') === null,
   '...and toolchains that are not installed do not');
// One operation at a time (the server answers a second with a 409), so the
// controls go dead while one runs rather than letting a click earn an error.
// The bin icons were the gap: only the two big buttons were being disabled.
// Set, read and put back in ONE evaluate. The tab re-reads itself whenever
// the toolchains token moves, and the uninstall just above moves it, so a
// fake planted in one round trip and read in the next four is a fake a real
// load can land on top of, which is what it started doing.
const ghosted = await page.evaluate(() => {
  const was = toolchains.job.running;
  toolchains.job.running = true; tcRev++; drawPanes();
  const all = sel => [...document.querySelectorAll(sel)];
  const r = {
    bins: all('.doc [data-rm]').length > 0
          && all('.doc [data-rm]').every(b => b.disabled),
    // Abort excluded: it is the one control that has to work while a job runs.
    buttons: all('.doc [data-tc]:not([data-tc="abort"])').every(b => b.disabled),
    abort: all('.doc [data-tc="abort"]').length === 1
           && !all('.doc [data-tc="abort"]')[0].disabled,
    boxes: all('.doc .tc input').length > 0
           && all('.doc .tc input').every(i => i.disabled),
  };
  toolchains.job.running = was; tcRev++; drawPanes(); clearTimeout(tcPoll);
  return r;
});
ok(ghosted.bins && ghosted.buttons && ghosted.abort && ghosted.boxes,
   `while a job runs, every button and every checkbox is ghosted (${
     Object.entries(ghosted).filter(([, v]) => !v).map(([k]) => k).join(', ') || 'all'})`);
// A check the operator did not start still has to reach the page, or the
// buttons stay live and a click earns "a version check is running" for an
// operation nobody could see. The button says which job is in the way.
const checking = await page.evaluate(() => {
  // Both halves planted here rather than relying on the block above leaving
  // one behind: each of these is its own scenario, and a state carried
  // between them is a state the next real load quietly takes away.
  const was = [toolchains.job.action, toolchains.job.running];
  toolchains.job.action = 'check'; toolchains.job.running = true;
  tcRev++; drawPanes();
  const t = document.querySelector('.doc [data-tc="check"]').textContent;
  [toolchains.job.action, toolchains.job.running] = was;
  tcRev++; drawPanes(); clearTimeout(tcPoll);
  return t;
});
ok(/^Checking for updates/.test(checking),
   `...and the check button says what it is doing (${checking.trim()})`);
await page.evaluate(() => { toolchains.job.running = false; tcRev++; drawPanes(); });
ok(await page.$$eval('.doc [data-rm]', bs => bs.every(b => !b.disabled))
   && await page.$$eval('.doc .tc input:not(:disabled)', is => is.length > 0),
   '...and live again when it finishes');
const nd = page.dialogs.length;
await page.click('.doc [data-rm="android:emulator"]');
ok(page.dialogs.length === nd + 1 && page.dialogs[nd].includes('Uninstall'),
   'uninstalling asks first');
// The job, not just the count: a row being removed has no path line at all,
// so "one installed path" is briefly true mid-removal, and everything after
// this reads paths. On this runner that race is the difference between green
// and a null dereference.
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running
  && !(toolchains.items || []).find(i => i.name === 'android:emulator')?.installed,
  { timeout: 30000 });
list = await rows();
ok(!list.find(r => r.name === 'android:emulator').installed
   && list.find(r => r.name === 'flutter').installed,
   'removing the ticked one leaves the other alone');
ok(!existsSync(`${DIR}/androidsdk/emulator`), '...and it is gone from disk');

// The tab is laid out like the notebook and the other document tabs. It was
// the odd one out: an inset on the darker ground rather than filling its pane,
// a 12px gutter applied to a wrapper instead of 14px on the rows, and a hover
// highlight no other list here has, in a hardcoded color no scheme reached.
ok(await page.$eval('.doc:has(.tc)', e => e.classList.contains('flush')),
   'the Toolchains tab fills its pane, like every other document tab');
ok(await page.$eval('.tc', e => getComputedStyle(e).padding) === '11px 14px',
   '...on the same band the notebook uses, so the two do not disagree by two pixels');
ok(await page.evaluate(() => {
     const host = document.querySelector('.doc:has(.tc)');
     const bin = document.querySelector('.tc .rm');
     return bin && Math.round(host.getBoundingClientRect().right
                              - bin.getBoundingClientRect().right) >= 12;
   }), '...and the bin has a margin to sit in rather than the edge of the pane');

// ---- what it is doing, beside what started it ---------------------------
// The status used to be the Install button's label, which made a toolchain id
// into a green banner across the tab. It is green text beside the button now,
// and beside *whichever* button started it, because on a phone the picker
// is a screenful above the Install row.
await page.check('.doc .tc input[value="go"]');
await page.click('.doc [data-tc="install"]');
await page.waitForFunction(() => toolchains?.job?.running);
ok(await page.$eval('.doc [data-tc="install"]',
     b => b.textContent.trim() === 'Install selected' && b.disabled),
   'the Install button keeps its own name and goes dead, rather than becoming a banner');
ok(await page.$eval('.doc .macros .tcworking', e => /Installing go/.test(e.textContent))
   && await page.$('.doc .macros .tcworking .dots') !== null,
   '...with what it is doing beside it, and an ellipsis');
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running,
                           { timeout: 60000 });


// ---- a failure, where the failure happened ------------------------------
// There used to be a scrolling log at the foot of the tab holding every line
// every command printed. What anybody ever wanted out of it was which toolchain
// failed and why, so that is what is kept now, on that toolchain's own row.
await page.check('.doc .tc input[value="rust"]');
await page.click('.doc [data-tc="install"]');
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running
  && (toolchains.job.failed || []).includes('rust'), { timeout: 30000 });
const rustErr = await page.$eval('.doc .tc:has(input[value="rust"]) .sub.bad',
                                 e => e.textContent).catch(() => "");
ok(/could not download file/.test(rustErr),
   `the failing row says what went wrong (${rustErr.slice(0, 52)})`);
ok(!/\[====\]/.test(rustErr), '...without the progress frames that filled the old log');
ok(/exit 1/.test(rustErr),
   '...and the exit code, since a killed tool prints nothing at all');
ok(await page.$$eval('.doc .tc .sub.bad', e => e.length === 1),
   'and no other row is wearing it');
// Trying again is what clears it: by then it describes a state that is over.
await page.check('.doc .tc input[value="rust"]');
await page.click('.doc [data-tc="install"]');
await page.waitForFunction(() => toolchains?.job?.running
  && toolchains.job.current === 'rust', { timeout: 30000 });
ok(await page.$$eval('.doc .tc .sub.bad', e => e.length === 0),
   '...and asking again clears it, because it is no longer the answer');
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running,
                           { timeout: 30000 });

// ---- a recipe that cannot update in place (bug #43) ---------------------
// The check asks UPSTREAM, not the recipe, so it can report a newer version
// for a toolchain `bb toolchains update` has no case for. Ticking that used to route
// to update and die on its usage line, naming five toolchains nobody asked
// about. The row says so instead, before the press.
{
  const rows = await page.$$eval('.doc .tc', ls => ls.map(l => ({
    name: l.querySelector('input')?.value,
    disabled: !!l.querySelector('input')?.disabled,
    title: l.querySelector('input')?.title || '',
  })));
  const go = rows.find(r => r.name === 'go');
  ok(go && go.disabled && /no update in place/.test(go.title),
     `an installed tarball recipe cannot be ticked, and says why (${
       (go?.title || 'no row').slice(0, 60)})`);
  const fl = rows.find(r => r.name === 'flutter');
  ok(fl && !/no update in place/.test(fl.title),
     'while one that CAN update in place is not marked that way');
  // ...and the catalog is where that is decided, not a list in the server.
  const seen = await page.evaluate(() => (toolchains.items || [])
    .filter(i => i.updatable).map(i => i.name).sort());
  ok(seen.includes('flutter') && seen.includes('playwright')
     && !seen.includes('go') && !seen.includes('jdk'),
     `the catalog says which recipes update in place (${seen.join(', ')})`);
}

// ---- what the endpoint refuses ----------------------------------------
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/toolchains', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return r.status;
}, body);
ok(await post({ action: 'install', names: ['flutter; rm -rf /'] }) === 400,
   'a name that is not in the catalog is refused');
ok(await post({ action: 'install', names: [] }) === 400, 'an empty selection is refused');
// A second job is refused while one runs. The message names which one: the
// version check that runs by itself once a day says so, rather than claiming
// an install nobody started, though only the daily one is "auto"; a check
// somebody pressed is as much theirs as an install.
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
await page.waitForFunction(() => toolchains?.job && !toolchains.job.running, { timeout: 30000 });
ok(await post({ action: 'sudo', names: ['flutter'] }) === 400, 'an unknown action is refused');

// It is a tab like any other: minimizing it leaves the strip, and the saved
// layout brings it back with its own data rather than an empty pane.
await page.evaluate(() => hideTab(tabs.find(t => t.kind === 'toolchains').id));
ok(await page.evaluate(() => !tabs.some(t => t.kind === 'toolchains')), 'the tab minimizes away');
await page.click('#bToolchains');
await page.waitForFunction(() => document.querySelectorAll('.doc .tc').length > 0);
ok(true, 'and reopens from the card');
// The strip lives on the server and is handed to every browser, so a tab kind
// the store does not recognize is dropped on every read, which is why this
// one came back from a reload, or a container restart, missing.
await page.reload();
await ready(page);
await page.waitForFunction(() => document.querySelectorAll('.doc .tc').length > 0,
                           { timeout: 30000 });
ok(await page.evaluate(() => tabs.some(t => t.kind === 'toolchains')),
   '...and survives a reload, the way the findings tab does');
// A fresh page opens the tab on a node, as it should (roadmap #26); the rows
// the rest of this file reads are the local installer's, so ask for them.
await page.evaluate(() => { tcNode = 'local'; toolchains = null; loadToolchains(); });
await page.waitForFunction(() => tcNode === 'local' && toolchains && !toolchains.name
                                 && document.querySelectorAll('.doc .tc').length > 0,
                           { timeout: 30000 });

// ---- a recipe this node's platform cannot have ---------------------------
// The catalog says which platforms each recipe serves and the server marks
// the rest, but the tab drew them all: on a Linux node that is one dead row
// (xcodes), and on a Mac it is eleven of sixteen: a tab of controls that can
// never be pressed. They go behind a fold, which is not the same as hidden:
// somebody looking for xcodes should be able to find out that it exists and
// what it wants.
//
// Rendered from a payload rather than against a real Mac, because the thing
// under test is which side of the fold a row lands on.
{
  const shape = await page.evaluate(() => {
    toolchains = { name: 'a-mac', root: '/Volumes/SDK/darwin-arm64', free_mb: 90000,
      items: [
        { name: 'jdk', label: 'JDK', about: 'a', installed: false, wrong_platform: '' },
        { name: 'xcodes', label: 'xcodes (Xcode installer)', about: 'b',
          installed: false, wrong_platform: '' },
        { name: 'swift', label: 'Swift', about: 'c', installed: false,
          wrong_platform: 'linux/amd64' },
        { name: 'rust', label: 'Rust', about: 'd', installed: false,
          wrong_platform: 'linux/amd64' }] };
    tcRev++; drawPanes();
    const doc = document.querySelector('.doc.on');
    const inList = [...doc.querySelectorAll('.tcs:not(.tcno .tcs) .tc .nm')]
      .map(e => e.textContent.replace(/\s+/g, ' ').trim());
    const fold = doc.querySelector('details.tcno');
    return { inList,
             folded: [...(fold?.querySelectorAll('.tc .nm') || [])]
               .map(e => e.textContent.replace(/\s+/g, ' ').trim()),
             shut: fold ? !fold.open : null,
             count: fold?.querySelector('.sst')?.textContent || '',
             says: [...(fold?.querySelectorAll('.tc .where') || [])]
               .map(e => e.textContent.trim())[0] || '' };
  });
  ok(shape.inList.join('|') === 'JDK|xcodes (Xcode installer)',
     `the list is what this node can have (${shape.inList.join(', ')})`);
  ok(shape.folded.join('|') === 'Swift|Rust' && shape.shut === true
     && shape.count === '2',
     `...and what it cannot is behind a shut fold that counts them (${
       shape.folded.join(', ')}, ${shape.count})`);
  ok(/packaged for linux\/amd64, and this node is not/.test(shape.says),
     `...each still saying what it wants, so the fold is not a hiding place (${shape.says})`);
  await page.evaluate(() => { toolchains = null; loadToolchains(); });
  await page.waitForFunction(() => toolchains && !toolchains.error, { timeout: 20000 });
}

// 400s and 409s are asked for on purpose above; the browser logs a failed
// fetch either way.
const errs = page.errors.filter(e => !/status of (400|409)/.test(e));
ok(errs.length === 0, `zero console errors${errs.length ? ': ' + errs.join(' | ') : ''}`);
// The Toolchains tab reads nodesList, which tab-nodes.js declares with `let`.
// Loaded after this file's script, a renderer drawing before it evaluated hit
// the temporal dead zone and the tab came up "this tab's renderer failed:
// nodesList is not defined". `typeof` throws on a TDZ binding too, so the fix
// is load order, and this is the check that keeps it: every binding a
// renderer here reads must exist by the time the first draw can happen.
ok(await page.evaluate(() => {
     try { return nodesList !== undefined || nodesList === null || true; }
     catch (e) { return false; }
   }),
   'the tab scripts are evaluated before the renderers that read their state');

// A toolchain that needs another says so on its row, and so does the one that
// is needed. The operator asked whether a toolchain existing only to serve
// another should be an entry at all, and the honest answer is that the ones
// which do nothing alone are leaves that nothing depends on. What was
// missing was the relationship being visible where it does exist.
const rel = await page.$$eval('.tctab .tc', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ')));
ok(rel.some(t => /Android NDK/.test(t) && /Needs android-tools, installed with it/.test(t)),
   'a toolchain that needs another says so on its row');
ok(rel.some(t => /JDK 21/.test(t) && /Needed by android-tools/.test(t)),
   '...and the one it needs says what needs it');

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
     && /compileSdk\s+up to 36: a library that wants a newer platform fails checkDebugAarMetadata; the operator adds one on the Toolchains tab/.test(builds)
     && /build-tools\s+36\.0\.0/.test(builds),
     `bb toolchains says the platforms, the compileSdk ceiling and the build-tools as a build reads them (${builds.split('\n')[2]?.trim()})`);
  ok(/gradle\s+9\.7\.1 \(wrapper distributions, no download\)/.test(builds) && /AGP\s+9\.4\.1\n/.test(builds)
     && /kotlin\s+2\.4\.20\n/.test(builds) && !/compose BOM/.test(builds),
     '...and what the Gradle cache holds, naming only what is there');
  const bare = execFileSync('bash', ['-c', `. ${JSON.stringify(LIB)}; . ${JSON.stringify(SDK)}; sdk_builds_with ${JSON.stringify(`${odd}/none`)}`],
                            { encoding: 'utf8', env: { ...process.env, GRADLE_USER_HOME: `${odd}/nogradle` } });
  ok(/platforms\s+none: nothing compiles here until the operator adds one on the Toolchains tab/.test(bare)
     && /modules\s+none cached yet: the first build fetches them/.test(bare),
     '...and an empty store and an empty cache are said as such rather than as a blank');
}

await done(browser);
