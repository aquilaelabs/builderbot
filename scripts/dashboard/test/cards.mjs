// The page's frame and what hangs off it: the doctor's dot and panel, the
// Projects page's cards, the Analysis tab and its gate, which build this is,
// the welcome panel, polls that do not stack, themes, the gear's logs, a
// project on several nodes, and dialogs that scroll.
import { launch, newPage, ok, done, ready, doctorFixture, animatedDuring, refreshUntil,
         holdPoll, freePoll, tmuxNew, tmuxKill, tmuxFmt, nbShown, URL, DIR, unfold, registerProject,
         saveDialog, sectSave } from './lib.mjs';
import { writeFileSync, readFileSync, existsSync, rmSync, utimesSync,
         mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });

// A card's link, lock, pin and the rest sit behind its menu on the Projects
// page (R218 step 3): opened first, the way a thumb does.
const pjMenu = async name => {
  await page.evaluate(n => { const c = document.querySelector(`.doc .projtab .pcard[data-row="${CSS.escape(n)}"]`);
    if (c?.querySelector('.actmenu')?.hidden) c.querySelector('[data-pmore]')?.click(); }, name);
  await page.waitForTimeout(150);
};await page.goto(URL);
await ready(page);
// The Nostromo glass (the operator, 24 Sep): a pane's bar, the dock's line
// and the ground under a document wear one glass, over a pane left open so
// it is the hull that shows through. The ground is the stack's and the
// document box paints none, so the document fading in does not take the
// glass with it (27 Sep).
{
  await page.evaluate(() => document.documentElement.dataset.theme = 'nostromo');
  const glass = await page.evaluate(() => {
    const alpha = c => {
      const m = /\/\s*([0-9.]+)\s*\)$/.exec(c || '') || /^rgba\([^,]+,[^,]+,[^,]+,\s*([0-9.]+)\)$/.exec(c || '');
      return m ? Number(m[1]) : 1;
    };
    const bg = e => e ? getComputedStyle(e).backgroundColor : '';
    // A document on show, as a page draws one, read and taken away again in
    // the same task, so it is never painted.
    const pane = document.querySelector('.pane');
    const st = document.createElement('div'), doc = document.createElement('div');
    st.className = 'stack'; st.style.visibility = 'hidden';
    doc.className = 'doc on';
    st.appendChild(doc);
    pane?.appendChild(st);
    const out = { dock: bg(document.querySelector('#pane1 .bar')), bar: bg(document.querySelector('#pane0 .bar')) || 'no bar',
                  ground: bg(st), doc: bg(doc), pane: bg(pane) };
    st.remove();
    out.alpha = alpha(out.dock);
    return out;
  });
  ok(glass.alpha > 0 && glass.alpha < 0.8 && glass.dock === glass.ground && glass.doc === 'rgba(0, 0, 0, 0)'
     && (glass.bar === 'no bar' || glass.bar === glass.dock) && glass.pane === 'rgba(0, 0, 0, 0)',
     `the bars, the dock and the ground wear one glass, over a pane left open (${JSON.stringify(glass)})`);
  await page.evaluate(() => { delete document.documentElement.dataset.theme; });
}

// The header fits, at every width a phone comes in. It did not: measured at
// 320px it wanted 369px and overflowed by 57, and the uptime (the only item
// there that shrinks, because .meta clips) was squeezed away on the way,
// rendering "up 09:52:…", which is not a truncated number but a different one.
//
// Both halves are asserted, because they fail separately: a header that does
// not overflow can still contain something ellipsised, and that is what the
// operator saw.
{
  const sizes = [320, 344, 360, 390, 412, 430, 768];
  const measured = [];
  for (const w of sizes){
    await page.setViewportSize({ width: w, height: 800 });
    await new Promise(r => setTimeout(r, 200));
    measured.push(await page.evaluate(async () => {
      const h = document.querySelector('header');
      // A realistic value rather than whatever the fixture is up: the point is
      // the width the longest ordinary uptime needs.
      document.getElementById('uptime').textContent = 'up 9h 52m';
      await new Promise(r => requestAnimationFrame(r));
      return {
        w: window.innerWidth,
        over: h.scrollWidth - h.clientWidth,
        jump: Math.round(document.getElementById('jump').getBoundingClientRect().width),
        clipped: [...h.querySelectorAll('*')]
          .filter(e => e.offsetWidth && e.scrollWidth > e.offsetWidth + 1)
          .map(e => e.id || e.className || e.tagName),
      };
    }));
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await new Promise(r => setTimeout(r, 250));
  const over = measured.filter(m => m.over > 0);
  const cut = measured.filter(m => m.clipped.length);
  // ...and the search keeps room to be typed into: six buttons a thumb wide
  // once left it a sliver at 344px, with nothing overflowing (B744).
  const narrow = measured.filter(m => m.jump < 80);
  // The room comes from the gear: on a phone its menu carries Report a bug
  // and Sign out, and the header does not.
  await page.setViewportSize({ width: 344, height: 800 });
  await page.evaluate(() => toggleUiMenu(true));
  await page.waitForSelector('#uiReport', { timeout: 5000 });
  const gearPhone = await page.evaluate(() => ({ menu: ['uiReport', 'uiOut'].every(id => document.getElementById(id).offsetWidth > 0),
    header: ['bReport', 'bOut'].some(id => document.getElementById(id).offsetWidth > 0) }));
  // ...on one row: Profile across it, the two beside it square icons, as the
  // header draws them (the operator, 16 Oct).
  const acct = await page.evaluate(() => ['uiProfile', 'uiReport', 'uiOut'].map(id => {
    const r = document.getElementById(id).getBoundingClientRect(); return [Math.round(r.top), Math.round(r.width), Math.round(r.height)]; }));
  ok(acct.every(a => a[0] === acct[0][0]) && acct.slice(1).every(a => Math.abs(a[1] - a[2]) <= 1) && acct[0][1] > 2 * acct[1][1]
     && await page.evaluate(() => !!document.querySelector('#uiReport svg') && !!document.querySelector('#uiOut svg')),
     `...on one row, Profile across it and the two beside it square icons (${JSON.stringify(acct)})`);
  await page.evaluate(() => toggleUiMenu(false));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.evaluate(() => toggleUiMenu(true));
  await page.waitForSelector('#uiReport', { state: 'attached', timeout: 5000 });
  const gearDesk = await page.evaluate(() => ({ menu: ['uiReport', 'uiOut'].some(id => document.getElementById(id).offsetWidth > 0),
    header: ['bReport', 'bOut'].every(id => document.getElementById(id).offsetWidth > 0) }));
  await page.evaluate(() => toggleUiMenu(false));
  ok(gearPhone.menu && !gearPhone.header && !gearDesk.menu && gearDesk.header,
     `on a phone the gear carries Report a bug and Sign out, at a desk the header does (${JSON.stringify({ gearPhone, gearDesk })})`);
  ok(narrow.length === 0,
     `the search in the header keeps room to type at every phone width${
       narrow.length ? `: ${narrow.map(m => `${m.jump}px at ${m.w}`).join(', ')}` : ` (${measured.map(m => m.jump).join(', ')}px)`}`);
  ok(over.length === 0,
     `the header fits at every phone width${
       over.length ? `: over by ${over.map(m => `${m.over}px at ${m.w}`).join(', ')}` : ''}`);
  ok(cut.length === 0,
     `...with nothing inside it ellipsised${
       cut.length ? `: ${cut.map(m => `${m.clipped.join('/')} at ${m.w}`).join(', ')}` : ''}`);
}

// ---- the doctor: a dot in the top bar, its checks in a panel (R218 step 3) ----
// The column of cards went: the dot wears the worst check's color, and its
// panel lists problems as lines in their level's color, each with the rest
// of what the check said under it, and passing checks as chips.
{
  await page.waitForFunction(() => document.getElementById('docDot').className.includes('ok'), null, { timeout: 15000 });
  const dd = await page.$eval('#bDocDot', b => ({ said: b.getAttribute('aria-label'), w: b.offsetWidth, top: !!b.closest('header') }));
  ok(/all 3 ok/.test(dd.said) && dd.w > 0 && dd.top,
     `the doctor is a dot in the top bar, its verdict all 3 ok (${JSON.stringify(dd)})`);
  ok(await page.$eval('#docPanel', p => p.hidden), '...its panel shut until pressed');
  await page.click('#bDocDot');
  await page.waitForSelector('#docPanel:not([hidden]) #doctor .chips .pill', { timeout: 5000 });
  ok(await page.$eval('#bDocDot', b => b.getAttribute('aria-expanded') === 'true'), '...and a press opens it, its passing checks as chips');
  // One header panel at a time (the operator, 16 Oct): the gear pressed
  // with the doctor open shuts the doctor, and the bell shuts the gear.
  await page.click('#bCards');
  const one = await page.evaluate(() => ({ doc: document.getElementById('docPanel').hidden, gear: !document.getElementById('uiMenu').hidden }));
  await page.click('#bBell');
  const two = await page.evaluate(() => ({ gear: document.getElementById('uiMenu').hidden, bell: bellOpen }));
  await page.click('#bBell');
  await page.click('#bDocDot');
  await page.waitForSelector('#docPanel:not([hidden])', { timeout: 5000 });
  ok(one.doc && one.gear && two.gear && two.bell,
     `...the gear pressed shuts it, and the bell shuts the gear: one header panel at a time (${JSON.stringify({ one, two })})`);
  // A long check wraps inside the panel rather than ending in an ellipsis
  // (B742): no tooltip says the rest.
  const long = await page.evaluate(() => {
    const keep = state.doctor.checks;
    state.doctor.checks = [...keep, { level: 'ok', text: '2 nodes can run a session (bb-dev-sandbox, bb-dev-sandbox-rh, a third node with a long name)' }];
    drawDoctor();
    const pills = [...document.querySelectorAll('#doctor .chips .pill')];
    const panel = document.getElementById('docPanel').getBoundingClientRect();
    const out = { cut: pills.filter(p => p.scrollWidth > p.clientWidth + 1).length,
                  out: pills.filter(p => p.getBoundingClientRect().right > panel.right + 1).length,
                  tall: pills.some(p => p.getBoundingClientRect().height > 30) };
    state.doctor.checks = keep; drawDoctor();
    return out;
  });
  ok(long.cut === 0 && long.out === 0 && long.tall,
     `...a long check wrapping inside the panel rather than cut short (${JSON.stringify(long)})`);
  doctorFixture('fail');
  await page.click('#bDoctor');
  await page.waitForFunction(() => document.getElementById('docDot').className.includes('bad'), null, { timeout: 15000 });
  const probLines = await page.$$eval('#doctor .probs .sub', els => els.map(el => {
    const root = getComputedStyle(document.documentElement);
    const tok = el.classList.contains('bad') ? '--bad' : '--warn';
    const want = document.createElement('i');
    want.style.color = root.getPropertyValue(tok).trim();
    document.body.append(want);
    const same = getComputedStyle(want).color === getComputedStyle(el).color;
    want.remove();
    return { text: el.textContent, same, why: el.querySelector('.why')?.textContent || '' };
  }));
  ok(probLines.length === 2 && probLines.every(l => l.same),
     `↻ runs it again, and a FAIL turns the dot red with each problem in its level's color (${JSON.stringify(probLines.map(l => l.same))})`);
  ok(probLines.some(l => /runner offline/.test(l.text) && /bb logs --runner/.test(l.why)),
     '...and carries the rest of what the check said under it');
  ok(await page.$eval('#docPanel', p => !p.hidden), '...with the panel still open after ↻ redrew it');
  await page.keyboard.press('Escape');
  ok(await page.$eval('#docPanel', p => p.hidden), 'Escape shuts the panel');
  doctorFixture('ok');
  await page.evaluate(() => document.getElementById('bDoctor').click());
  await page.waitForFunction(() => document.getElementById('docDot').className.includes('ok'), null, { timeout: 15000 });
}

// The Analysis tab: the findings, browsable. The sidebar card is gone, since
// its rows were only doors into each notebook, a summary nothing could be
// read through, and the server logic it exercised (valid-project attribution,
// stale-report exclusion, the named aside) is asserted here against the tab
// that replaced it.
await page.evaluate(() => railGo('projects', 'findings'));
await page.waitForSelector('.fxtab #fxProject', { timeout: 15000 });
await page.waitForFunction(() => document.querySelectorAll('.fxtab .rule').length > 0,
                           { timeout: 15000 });
const opts = await page.$$eval('.fxtab #fxProject option',
                               os => os.map(o => o.value).filter(Boolean));
// alpha and beta are the valid projects; delta is locked, not excluded, and a
// locked project's findings are still worth reading. gamma (broken), the
// toolstore and vendored-junk are nobody's: attribution only knows valid
// projects, so everything else is set aside rather than swelling a junk row.
ok(opts.join(',') === 'alpha,beta,delta,unattributed paths',
   `the project picker lists valid projects, locked ones included (${opts.join(',')})`);
ok(/somewhere\/else/.test(await page.$eval('.fxtab', e => e.textContent)),
   'the aside names the paths it could not place, rather than only counting them');

// Narrowing. One project, one level, a search: each redraws the list, and
// the counts on the options are the whole report's, so choosing is informed.
await page.selectOption('.fxtab #fxProject', 'alpha');
await page.waitForFunction(() => !document.querySelector('.fxtab .fxproj'),
                           { timeout: 10000 });
ok(true, 'picking a project drops the per-project headings: the picker already says it');
await page.selectOption('.fxtab .fxLevel', 'error');
// On the condition the assertion is about, not on the row count changing:
// the count is a proxy that need not move at all, and swallowing its timeout
// meant waiting the full ten seconds to find that out.
await page.waitForFunction(() => {
  const ps = [...document.querySelectorAll('.fxtab .rule .pill')];
  return ps.length && ps.every(p => p.textContent.trim().startsWith('error'));
}, null, { timeout: 10000 }).catch(() => {});
ok(await page.$$eval('.fxtab .rule .pill', ps =>
     ps.every(p => p.textContent.trim().startsWith('error'))),
   'the level filter leaves only that level on the page');
await page.selectOption('.fxtab .fxLevel', '');
await page.selectOption('.fxtab #fxProject', '');
await page.waitForFunction(() => document.querySelector('.fxtab .fxproj'),
                           { timeout: 10000 });

// A report a whole cycle behind its siblings is not counted, and the tab says
// so. A scanner that dies leaves its previous report in place (the host
// script does not overwrite a good report with nothing), so without this a
// dead scanner goes on supplying findings about a tree that has since moved.
const before = await page.$$eval('.fxtab .rule', rs => rs.length);
writeFileSync(`${DIR}/reports/old.sarif`, readFileSync(`${DIR}/reports/test.sarif`));
const longAgo = Date.now() / 1000 - 3 * 86400;
execFileSync('touch', ['-d', `@${Math.round(longAgo)}`, `${DIR}/reports/old.sarif`]);
await refreshUntil(page, () => (state?.reports_ages || []).some(r => r.stale),
                   { timeout: 20000 });
await page.waitForFunction(() => /left out/.test(
  document.querySelector('.fxtab')?.textContent || ''), { timeout: 20000 });
ok(await page.$$eval('.fxtab .rule', rs => rs.length) === before,
   'a stale copy of the same report adds nothing: it is not read at all');
const foot = await page.$eval('.fxtab', e => e.textContent);
ok(/old\.sarif left out/.test(foot) && /3d behind/.test(foot),
   '...and the tab names it, so a number that did not move is not a mystery');
ok(/scanned/.test(foot), '...beside when the reports that ARE counted were written');
rmSync(`${DIR}/reports/old.sarif`, { force: true });
await refreshUntil(page, () => !(state?.reports_ages || []).some(r => r.stale),
                   { timeout: 20000 });
// The tab's controls carry the house field skin. They did not at first: the
// skin was an allowlist of container classes the Analysis tab was not on, so
// the same filter bar was styled in a notebook and browser-default here. The
// skin is element-global now; this pins the agreement to a known-styled modal
// field so the next new tab cannot ship native controls unnoticed.
{
  const skin = el => { const c = getComputedStyle(el);
    return [c.backgroundColor, c.borderTopLeftRadius, c.borderTopColor, c.fontFamily].join('|'); };
  const pair = await page.evaluate(`(() => { const skin = ${skin};
    return [skin(document.querySelector('.fxtab .fxFind')),
            skin(document.getElementById('mName'))]; })()`);
  ok(pair[0] === pair[1],
     'the Analysis tab\'s filter field wears the same skin as every other field');
}
// Every band of the tab starts at the same x. It shipped with four different
// left edges: the filter bar flush against the edge (its padding rule named
// an id the markup never had), the rules at 11px, the headings and the footer
// at 14, which is what a retyped inset looks like from a phone.
{
  const xs = await page.evaluate(() => {
    // The content edge, not the box: every band is full width and it is the
    // inset that has to agree.
    const x = sel => { const e = document.querySelector(sel);
      return e ? Math.round(e.getBoundingClientRect().x
                            + parseFloat(getComputedStyle(e).paddingLeft)) : null; };
    return { bar: x('.fxtab .fxbar'), heading: x('.fxtab .fxproj'),
             rule: x('.fxtab .rule'), foot: x('.fxtab .fnote') };
  });
  ok(new Set(Object.values(xs)).size === 1 && !Object.values(xs).includes(null),
     'the tab\'s filter bar, headings, rules and footer all start at one x: '
     + JSON.stringify(xs));
}
// `bb findings sample`: the report a box with no scanner can still work on.
// Every surface above ghosts or empties without one, and a development stack
// has no scanner by design, so this is how they are exercised at all.
{
  const bb = (...a) => {
    try {
      return { code: 0, out: execFileSync('bash', [`${REPO}/scripts/bb`, 'findings', ...a],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, FINDINGS_DIR: `${DIR}/sample-reports`, WORKSPACE: `${DIR}/ws` } }) };
    } catch (e) { return { code: e.status ?? 1, out: String(e.stdout || '') + String(e.stderr || '') }; }
  };
  const made = bb('sample');
  const f = `${DIR}/sample-reports/builderbot-sample.sarif`;
  ok(made.code === 0 && existsSync(f), `a sample report is written where no scanner runs (${
    made.out.trim().split('\n')[0].slice(0, 70)})`);
  const doc = JSON.parse(readFileSync(f, 'utf8'));
  const rows = doc.runs[0].results;
  ok(doc.runs[0].tool.driver.name === 'builderbot-sample'
     && rows.every(r => /sample/i.test(r.message.text)),
     '...named and worded so nobody reads it as a scan');
  // One per project, so the per-project rows have something, plus one the
  // attribution cannot place, so the unattributed label does too.
  const uris = rows.map(r => r.locations[0].physicalLocation.artifactLocation.uri);
  ok(uris.some(u => u.startsWith('alpha/')) && uris.some(u => !u.includes('/ws/'))
     && new Set(rows.map(r => r.level)).size >= 2,
     `...with a finding in a project, one that places nowhere, and more than one level (${uris.join(', ')})`);
  // Never mixed into a true report: two fake rows in a real one would make
  // every number on the card wrong and nothing would say why.
  const beside = (() => {
    try {
      execFileSync('bash', [`${REPO}/scripts/bb`, 'findings', 'sample'],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, FINDINGS_DIR: `${DIR}/reports`, WORKSPACE: `${DIR}/ws` } });
      return '';
    } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); }
  })();
  ok(/already holds a real report/.test(beside) && !existsSync(`${DIR}/reports/builderbot-sample.sarif`),
     `...and refused beside a real one, which is left alone (${beside.trim().slice(-60)})`);
  ok(bb('sample', '--remove').code === 0 && !existsSync(f),
     '...and taken away again by the same verb');

  // `bb findings` from a session, which is what BB_RELAYED marks: the report
  // covers the whole share, so the two lines that used to help are the two
  // that leak. With no findings of its own it listed every project the report
  // covered, by name, and with some it advertised --all, which the relay
  // refuses. The operator still gets both.
  const asSession = (cwd) => {
    try {
      return execFileSync('bash', [`${REPO}/scripts/bb`, 'findings', `${DIR}/reports`],
        { encoding: 'utf8', cwd, stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, BB_RELAYED: '1', WORKSPACE: `${DIR}/ws` } });
    } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); }
  };
  const quiet = asSession(`${DIR}/ws/ep.silon`);
  const named = ['alpha', 'gamma', 'delta', 'toolstore', 'vendored-junk'].filter(w => quiet.includes(w));
  ok(/No findings for ep\.silon/.test(quiet) && named.length === 0,
     `a session with no findings of its own is not handed the list of projects that do have them (${
       named.join(', ') || 'nothing named'})`);
  const loud = asSession(`${DIR}/ws/alpha`);
  ok(/in alpha/.test(loud) && !/--all/.test(loud),
     `...and one with findings is not told to run --all, which the relay refuses (${
       (loud.split('\n').find(l => l.startsWith('# ')) || '').slice(0, 50)})`);
}
// Nothing readable in /reports and the way in says so: three ways to have
// nothing (no mount, nothing in it, nothing that parses) and one sentence for
// which, said when Analysis is pressed. A tab already open on it is closed once, when the page
// first learns: a layout restored from last session can carry an Analysis tab
// for a scanner that has since been unmounted, and one that stays only to say
// "nothing here" is a tab somebody has to close by hand.
{
  const keep = readFileSync(`${DIR}/reports/test.sarif`);
  rmSync(`${DIR}/reports`, { recursive: true, force: true });
  await refreshUntil(page, () => state?.reports_ok === false, { timeout: 20000 });
  ok(/\/reports is not mapped in/.test(await page.evaluate(() => findingsOff())),
     'with no readable report Analysis is off, saying which of the three reasons it is');
  // The tab is open from the tests above; the gate closes it on the next load.
  await page.reload();
  await ready(page);
  await page.waitForFunction(() => state?.reports_ok === false, null, { timeout: 20000 });
  await page.waitForFunction(() => !tabs.some(t => t.kind === 'findings'),
                             null, { timeout: 10000 });
  ok(true, '...and an Analysis tab restored with the layout is closed, once');
  // A directory with nothing readable in it is the second reason, and reads
  // differently from an absent mount.
  mkdirSync(`${DIR}/reports`, { recursive: true });
  writeFileSync(`${DIR}/reports/broken.sarif`, 'not json at all');
  // The mount is back, so waiting on reports_ok alone would pass on the answer
  // from before the directory existed.
  await refreshUntil(page, () => state?.reports === true && state?.reports_ok === false,
                     { timeout: 20000 });
  ok(/nothing readable/.test(await page.evaluate(() => findingsOff())),
     'a report that does not parse is not a report, and Analysis says so');
  rmSync(`${DIR}/reports/broken.sarif`, { force: true });
  writeFileSync(`${DIR}/reports/test.sarif`, keep);
  await refreshUntil(page, () => state?.reports_ok === true, { timeout: 20000 });
  ok(await page.evaluate(() => findingsOff() === ''),
     '...and a readable one turns it on again');
  // A fourth way to have nothing: a mount gone stale under the container.
  // The directory is fine on the host and every read of it here raises
  // (NFS errno 116), and counts() runs on every /api/status, so the whole
  // poll answered with the error and the page never left loading (B326).
  // No NFS in the harness to go stale, so the module is handed a reports
  // path that raises what a stale one does, on the look and on the listing.
  {
    const { execFileSync } = await import('node:child_process');
    const dash = new globalThis.URL('..', import.meta.url).pathname;
    const said = JSON.parse(execFileSync('python3', ['-c', `
import errno, json, os, sys
sys.path.insert(0, ${JSON.stringify(dash)})
import findings
class Stale(type(findings.REPORTS)):
    def is_dir(self, *a, **k): raise OSError(errno.ESTALE, os.strerror(errno.ESTALE), str(self))
    def glob(self, *a, **k): raise OSError(errno.ESTALE, os.strerror(errno.ESTALE), str(self))
class Listless(type(findings.REPORTS)):
    def is_dir(self, *a, **k): return True
    def glob(self, *a, **k): raise OSError(errno.ESTALE, os.strerror(errno.ESTALE), str(self))
out = {}
for name, cls in (("stale", Stale), ("listless", Listless)):
    findings.REPORTS = cls("/reports")
    try:
        out[name] = {"counts": findings.counts([]), "ok": findings.reports_ok(), "mounted": findings.mounted(),
                     "available": findings.payload([]).get("available")}
    except OSError as e:
        out[name] = {"raised": str(e)}
print(json.dumps(out))
`], { encoding: 'utf8' }));
    ok(JSON.stringify(said.stale) === JSON.stringify({ counts: {}, ok: false, mounted: false, available: false })
       && JSON.stringify(said.listless) === JSON.stringify({ counts: {}, ok: false, mounted: true, available: false }),
       `a reports mount gone stale reads as nothing to read rather than raising into every status poll (${JSON.stringify(said)})`);
  }
  await page.evaluate(() => openFindingsTab());
  await page.waitForSelector('.fxtab #fxProject', { timeout: 15000 });
}
// Two projects whose names shorten to one slug are one dev instance: the same
// compose project, env file and data directory, driven by two rows that know
// nothing about each other. Nothing owns the moment a directory appears under
// /workspace, so it cannot be refused; this list is the only place that sees
// every name at once, which makes it the only place that can say so.
{
  // Not empty: an empty directory is a mount point waiting for content and is
  // never listed at all.
  mkdirSync(`${DIR}/ws/My.App`, { recursive: true });
  mkdirSync(`${DIR}/ws/my-app`, { recursive: true });
  writeFileSync(`${DIR}/ws/My.App/README.md`, '#\n');
  writeFileSync(`${DIR}/ws/my-app/README.md`, '#\n');
  registerProject('My.App', 'my-app');   // dropped in, recorded as an import would (R154)
  await refreshUntil(page, () => (state?.projects || []).some(p => p.name === 'my-app'),
                     { timeout: 20000 });
  const said = await page.evaluate(() => (state.projects || [])
    .filter(p => (p.issues || []).some(i => /shorten to/.test(i.text)))
    .map(p => p.name).sort());
  ok(JSON.stringify(said) === JSON.stringify(['My.App', 'my-app']),
     'two projects that shorten to one name are both told so');
  ok(await page.evaluate(() => (state.projects || []).find(p => p.name === 'My.App')
       .issues.find(i => /shorten to/.test(i.text)).level === 'warning'),
     '...as a warning: an error would take them out of findings attribution and '
     + 'off the Claude button, which is a bigger fault than the one being reported');
  rmSync(`${DIR}/ws/My.App`, { recursive: true, force: true });
  rmSync(`${DIR}/ws/my-app`, { recursive: true, force: true });
  await refreshUntil(page, () => !(state?.projects || []).some(p => p.name === 'my-app'),
                     { timeout: 20000 });
}
// ---- a project's card on the Projects page, at a phone and at a desk ------
// The sidebar's row, and its fold, went with R218 step 3: a project is a
// card on the Projects page with Claude and Shell on it and the rest behind
// one menu, at every width.
{
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(400);
  await page.evaluate(() => openProjectsTab());
  await page.waitForSelector('.doc.on .projtab .pcard[data-row="alpha"]', { timeout: 10000 });
  const card = '.doc.on .projtab .pcard[data-row="alpha"]';
  const shown = () => page.$$eval(`${card} .pcacts > button`, bs => bs.filter(b => b.offsetParent !== null).length);
  ok(await shown() === 2 && await page.$eval(`${card} .actmenu`, m => m.hidden),
     `a phone's card shows Claude and Shell, the rest behind its menu (${await shown()})`);
  await page.click(`${card} [data-pmore]`); await page.waitForTimeout(250);
  ok(await page.$eval(`${card} .actmenu`, m => !m.hidden && m.querySelectorAll('button').length >= 5),
     '...and pressing it opens the menu with the rest');
  const menuAnim = await page.$eval(`${card} .actmenu`, m => getComputedStyle(m).animationName);
  ok(menuAnim === 'menuIn', `...on the stylesheet's tween (${menuAnim})`);
  ok(await page.$eval(`${card} [data-pmore]`, b => b.getAttribute('aria-expanded') === 'true'),
     '...saying so, for anything that is not looking at the pixels');
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.waitForTimeout(400);
  const tabShown = await shown();
  ok(tabShown === 2 && await page.$eval(`${card} [data-pmore]`, b => b.offsetParent !== null)
     && await page.$eval(`${card} .actmenu`, m => m.hidden && m.querySelectorAll('button').length >= 5),
     `...and at a desk the card shows the same two, the rest behind its menu (${tabShown} shown)`);
  // The pin is in the card's menu, reading Unpin while it is pinned; a press
  // turns it to Pin, and Home's glance (step 5) is what it decides.
  ok(await page.$eval(`${card} [data-p]`, b => b.textContent.trim() === 'Unpin'),
     "the card's menu carries the pin, reading Unpin");
  await unfold(page, 'alpha');
  await page.click(`${card} [data-p]`);
  await page.waitForFunction(() => document.querySelector('.doc.on .projtab .pcard[data-row="alpha"] [data-p]')?.textContent.trim() === 'Pin', null, { timeout: 15000 });
  ok(true, '...and pressing it unpins the project');
  await page.evaluate(() => setProjectPinned('alpha', true));
  await page.waitForFunction(() => document.querySelector('.doc.on .projtab .pcard[data-row="alpha"] [data-p]')?.textContent.trim() === 'Unpin', null, { timeout: 15000 });
}

// ---- the card's notice: why nobody can be here, and who is ------------
// The card on the Projects page says WHO is here as its state (the dot and a
// word) and WHY nobody can be as its one notice, in red, since a ghosted
// button with no reason is the thing somebody stares at. Never WHICH
// MACHINE as a sentence: the node is a fact beside the branch.
//
// Planted rather than arranged: the fixture has no node, and the four refusals
// worth drawing (offline, no session half, no copy yet, taken off its copy) are
// nodes.mjs's to produce. This is about what the CARD does with one.
{
  await holdPoll(page);
  await page.evaluate(() => openProjectsTab());
  await page.waitForSelector('.pgrid .pcard[data-row="alpha"]', { timeout: 10000 });
  const C = '.pgrid .pcard[data-row="alpha"]';
  const line = () => page.$eval(C, r => ([...r.querySelectorAll('.pnote')].pop()?.textContent || '').trim());
  const stateWord = () => page.$eval(`${C} .pstate`, e => e.textContent.trim());
  const were = await page.evaluate(() => {
    const had = state.claude_with; state.claude_with = {}; return had; });
  const plant = (patch) => page.evaluate(p2 => {
    Object.assign(state.projects.find(x => x.name === 'alpha'), p2);
    drawProjects(state.projects);
  }, patch);
  await plant({ session_at: 'shed', session_why: '', locked: false });
  ok(await line() === '', 'a project whose node takes sessions carries no notice');
  await plant({ session_at: 'shed', locked: false,
                session_why: "alpha's sessions run on shed, which is offline. Sessions run on a "
                           + 'node and nowhere else (this container carries no Claude Code), so '
                           + 'the way on is that machine coming back, or another node in the '
                           + "project's settings." });
  ok(/offline/.test(await line()),
     `a node that cannot take one puts the reason on the card (${await line()})`);
  ok(/Sessions run on a node and nowhere else/.test(await line()),
     '...the whole of it, fix included: there is no tooltip to carry the rest (the operator, 11 Oct)');
  ok(await page.$eval(C, r => [...r.querySelectorAll('.pnote')].pop().classList.contains('bad')),
     '...in red, because a dead button with no reason is what somebody stares at');
  ok(await page.$eval(`${C} [data-c]`, b => /nowhere else/.test(saidOf(b))),
     '...and a screen reader hears the same words on the ghosted button');
  await plant({ session_at: '', locked: false, node_name: '',
                session_why: "no node to run a Claude session on: pick one in the project's settings, or enroll one on the Nodes tab" });
  ok(await line() === "no node to run a Claude session on: pick one in the project's settings, or enroll one on the Nodes tab",
     `a project with no node says so on the card, with what to do (${await line()})`);
  ok(await page.$eval(`${C} [data-c]`, b => /^no node to run a Claude session on: pick one/.test(saidOf(b))),
     '...while the button carries the fix');
  await plant({ session_at: 'shed', node_name: 'shed', session_why: '',
                held: 'shed runs agent 0.5.0 and this controller ships 0.6.93: a different compatibility window, so nothing sent to it is promised to work. Update it from the Nodes tab' });
  ok(/^shed runs agent 0\.5\.0 and this controller ships 0\.6\.93: .*Update it from the Nodes tab$/.test(await line()),
     `a node out of window says so on the card too (${await line()})`);
  await plant({ held: '' });
  await plant({ node_name: 'shed' });
  ok(/shed/.test(await page.$eval(`${C} .pcfacts`, e => e.textContent)),
     '...and the node is a fact beside the branch, not a sentence');
  await plant({ locked: true });
  ok(await line() === '', 'a locked project says nothing: no session there is the decision, not a fault');
  await plant({ locked: false, session_at: '', session_why: '' });
  // Who is here is the card's state: this account's session as the dot
  // and a word, in the session dot's own colors (the operator, 29 Sep).
  await page.evaluate(() => { state.claude_with = { alpha: ['test', 'alice'] }; state.claude_busy = { alpha: ['alice'] };
                              drawProjects(state.projects); });
  ok(/waiting for you/.test(await stateWord()) && await page.$eval(`${C} .pstate .st`, e => e.classList.contains('waiting')),
     `this account's session here is the card's state, its dot the session dot's waiting (${await stateWord()})`);
  await page.evaluate(() => { state.claude_busy = { alpha: ['test'] }; drawProjects(state.projects); });
  ok(/working/.test(await stateWord()) && await page.evaluate(() => {
    const dot = document.querySelector('.pgrid .pcard[data-row="alpha"] .pstate .st.working');
    const tab = document.createElement('span'); tab.className = 'st working'; document.body.appendChild(tab);
    const same = getComputedStyle(dot).backgroundColor === getComputedStyle(tab).backgroundColor
      && getComputedStyle(dot).animationName === getComputedStyle(tab).animationName;
    tab.remove(); return same && !document.querySelector('.sdot');
  }), "the card's dot is drawn by the one rule the session dots share, and no dot of its own is left");
  await page.evaluate(() => { state.claude_with = {}; state.claude_busy = {}; drawProjects(state.projects); });
  await page.evaluate(() => liveRefresh());
  ok(/waiting for you|working/.test(await stateWord()),
     'liveRefresh reads who is here from /api/live and draws the cards again');
  await page.evaluate(w => { state.claude_with = w; state.claude_busy = {}; drawProjects(state.projects); }, were);
  await freePoll(page);
}

await page.evaluate(() => { const t = tabs.find(x => x.kind === 'findings');
                            if (t) hideTab(t.id); });

// Which shares count as "not a project" no longer comes only from what sits
// inside /workspace. That worked while /workspace was the whole development
// share; pointing it at the projects folder took the toolchain store outside it and
// sent 267 findings about downloaded toolchains to the label meant for a path
// that is genuinely wrong. The rule asks the mount table instead.
//
// Driven at findings.py, which is importable, with a mount table written
// here: the case that must not regress cannot be produced by mounting
// something on this box.
const sibOut = execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('findings', ${JSON.stringify(new globalThis.URL('../findings.py', import.meta.url).pathname)})
ns = importlib.util.module_from_spec(spec); spec.loader.exec_module(ns)
mi = """
26 25 0:24 /development/projects /workspace rw - fuse.shfs x rw
27 25 0:24 /development/SDK /sdk rw - fuse.shfs x rw
28 25 0:25 /appdata/BuilderBot /config rw - xfs x rw
29 25 0:26 / /reports ro - xfs x ro
"""
print(json.dumps(sorted(ns.siblings_of(mi, '/workspace'))))
`], { encoding: 'utf8' });
const sib = JSON.parse(sibOut.trim().split('\n').pop());
ok(sib.includes('SDK'),
   'a share mounted beside the projects folder is known to be one');
ok(!sib.includes('BuilderBot'),
   '...while a mount from somewhere else is not, even named after a project');
ok(!sib.includes('reports') && sib.length === 1,
   '...and a whole-filesystem mount names no directory, so it says nothing');

// .bbignore hides a directory from the card entirely: not listed, not
// counted, not folded away under the Excluded/Error toggle either.
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.pgrid .pcard', { timeout: 10000 });
const all = await page.$$eval('.pgrid .pcard .name', ns => ns.map(n => n.textContent.trim()));
ok(!all.includes('toolstore'), 'a directory carrying .bbignore is not a project');
ok(!all.includes('toolstore'), '...not even among the cards with errors, which the page shows');
// An unmarked directory IS still listed, as a project with an error, and that is
// the card doing its job, and how you find out something in the share is not a
// repository. What changed is that its findings no longer count as anybody's.
ok(all.includes('vendored-junk'),
   '...while one with no marker is listed, as the error it is');

// The gear's menu: the color schemes, each swatch rendered in the scheme it
// selects.
await page.click('#bCards');
await page.waitForSelector('#uiMenu:not([hidden])');
ok(await page.$$eval('#uiMenu .sw', s => s.length) === 12,
   'the gear opens a menu of twelve schemes');
ok(await page.$eval('#uiMenu .sw[data-theme="default"]', b => b.classList.contains('on')),
   '...with the one in use marked, which is Default until something says otherwise');
// A swatch is the palette itself at 1cm (the stylesheet defines each scheme
// for .sw[data-theme] as well as for the page), so this reads the computed
// color rather than trusting that two lists match.
const swAccent = t => page.$eval(`#uiMenu .sw[data-theme="${t}"] .swa`,
                                 e => getComputedStyle(e).backgroundColor);
ok(await swAccent('default') !== await swAccent('nostromo'),
   '...and two schemes really do preview differently, not just by label');

await page.click('#uiMenu .sw[data-theme="nostromo"]');
ok(await page.evaluate(() => document.documentElement.dataset.theme) === 'nostromo',
   'picking one applies it to the page');
ok(await page.evaluate(() => { try { return localStorage.getItem('bb.theme'); }
                               catch (e) { return null; } }) === 'nostromo',
   '...and remembers it here rather than on the server: it is about the room, not the work');
// ...for the account that picked it (B491): a browser whose choice was
// another account's takes this account's own scheme on the next poll,
// rather than carrying the first account's colors over.
const switched = await page.evaluate(async () => {
  localStorage.setItem('bb.theme', 'abyss'); localStorage.setItem('bb.theme.who', 'somebody-else');
  document.documentElement.dataset.theme = 'abyss';
  await refresh();
  return { theme: document.documentElement.dataset.theme || 'default', who: localStorage.getItem('bb.theme.who') };
});
ok(switched.theme === 'nostromo' && switched.who === 'test',
   `another account's choice in this browser gives way to this account's own scheme (${JSON.stringify(switched)})`);
// Nostromo's dark half is the ship's hallways (the operator, 16 Oct): a
// steel rail along the header's foot, drawn, and the deck grating and a
// bulkhead on the page's own layer behind everything.
const hall = await page.evaluate(() => ({ rail: /linear-gradient/.test(getComputedStyle(document.querySelector('header'), '::after').backgroundImage),
  deck: /grate\.svg/.test(getComputedStyle(document.body, '::before').backgroundImage),
  frame: /bulkhead\.svg/.test(getComputedStyle(document.body, '::before').backgroundImage) }));
ok(hall.rail && hall.deck && hall.frame, `...and Nostromo brings its hallway: the steel rail, the deck and the bulkhead (${JSON.stringify(hall)})`);
// The deck is on that layer, one viewport, and never on the tall content
// of a notebook (bug #57): a pattern rasterized across a long roadmap's
// whole scroll height is what Firefox for Android painted as striped tiles.
await page.evaluate(() => openNotebook(state.projects[0].name));
await page.waitForSelector('.pane .doc > .nb');
const scan = await page.evaluate(() => {
  const nb = document.querySelector('.pane .doc > .nb');
  const g = e => /url\(|repeating-linear-gradient/.test(getComputedStyle(e).backgroundImage);
  return { content: g(nb) || g(nb.parentElement) };
});
ok(!scan.content, `...and no pattern runs down a notebook's scroll height (${JSON.stringify(scan)})`);
// A surface that stops following the scheme does it silently: the text
// fields, the memory folds and the pane's title bar all sat in the default
// scheme's blue-gray through the first twelve because their color was typed
// in rather than named. A field is the cheapest one to keep honest.
// The notebook's add field, open just above: the sidebar has no text field now that the phone is a tab.
const fieldBg = () => page.$eval('.pane .nb #roadmapText', e => getComputedStyle(e).backgroundColor);
const nosField = await fieldBg();

await page.click('#uiMenu .sw[data-theme="default"]');
ok(await fieldBg() !== nosField,
   '...and a text field is painted from the scheme, not from a hardcoded hex');
ok(await page.evaluate(() => document.documentElement.dataset.theme) === undefined,
   'Default carries no attribute at all, so :root is simply left to stand');
// The scheme's other half (R216): Dark, Light or System beside the swatches,
// applied on the press like a scheme, kept in the browser and on the
// account, and the swatches show the half that is on.
{
  const pageBg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  // Past the crossfade Default's pick above started (320ms of html.theming):
  // read mid-swap, the color to come back to was one no theme paints.
  await page.waitForFunction(() => !document.documentElement.classList.contains('theming'), null, { timeout: 5000 });
  const darkBg = await pageBg();
  ok(await page.$eval('#uiMenu [data-mode="dark"]', b => b.classList.contains('on')),
     'the gear offers Dark, Light and System, on Dark to begin with');
  await page.click('#uiMenu [data-mode="light"]');
  await page.waitForTimeout(400);
  ok(await page.evaluate(() => document.documentElement.dataset.mode) === 'light'
     && await pageBg() !== darkBg,
     'Light repaints the page on the press, the light half of the same scheme');
  ok(await page.evaluate(() => { try { return localStorage.getItem('bb.mode'); } catch (e) { return 'no storage'; } }) === 'light',
     '...and the browser keeps it, as it keeps the scheme');
  const swLight = await page.$eval('#uiMenu .sw[data-theme="moss"]', b => getComputedStyle(b).backgroundColor);
  // The page's sub-nav is the filled accent on show (R218 step 4).
  await page.evaluate(() => railGo('machines', 'nodes'));
  // Waited for, not slept on (B753): the Light crossfade and the button's
  // own color transition were still running 300ms in under a whole run.
  const white = await page.waitForFunction(() => { const e = document.querySelector('.pane .bar .subnav button.on');
    return e && getComputedStyle(e).color === 'rgb(255, 255, 255)'; }, null, { timeout: 5000 }).then(() => true, () => false);
  ok(white, `a filled accent carries white in the light half, where the ink is dark (${
    await page.$eval('.pane .bar .subnav button.on', e => getComputedStyle(e).color).catch(() => 'no button')})`);
  // Nostromo's light half is the ship's white corridors: rounded like the
  // rest, its own wall panels rather than the deck, no steel rail (the
  // operator, 16 Oct); the dark half keeps its hallway.
  await page.click('#uiMenu .sw[data-theme="nostromo"]');
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'nostromo' && document.documentElement.dataset.mode === 'light', null, { timeout: 5000 });
  const ship = () => page.evaluate(() => ({ r: getComputedStyle(document.documentElement).getPropertyValue('--r-control').trim(),
    stripe: getComputedStyle(document.querySelector('header'), '::after').content,
    hull: getComputedStyle(document.body, '::before').backgroundImage.includes('grate'),
    wall: getComputedStyle(document.body, '::before').backgroundImage.includes('panels') }));
  const lightShip = await ship();
  ok(lightShip.r !== '0' && lightShip.r !== '0px' && lightShip.stripe === 'none' && !lightShip.hull && lightShip.wall,
     `Nostromo under Light is the white corridor: rounded, its wall panels and not the deck (${JSON.stringify(lightShip)})`);
  await page.click('#uiMenu [data-mode="dark"]');
  await page.waitForFunction(() => !document.documentElement.dataset.mode, null, { timeout: 5000 });
  const darkShip = await ship();
  ok((darkShip.r === '0' || darkShip.r === '0px') && darkShip.stripe !== 'none' && darkShip.hull,
     `...and its dark half keeps the hallway, square with the rail and the deck (${JSON.stringify(darkShip)})`);
  await page.click('#uiMenu [data-mode="light"]');
  await page.waitForFunction(() => document.documentElement.dataset.mode === 'light', null, { timeout: 5000 });
  await page.click('#uiMenu .sw[data-theme="default"]');
  await page.waitForFunction(() => !document.documentElement.dataset.theme, null, { timeout: 5000 });
  await page.click('#uiMenu [data-mode="dark"]');
  // Past the crossfade, which a loaded box stretches.
  await page.waitForFunction(bg => getComputedStyle(document.body).backgroundColor === bg, darkBg, { timeout: 5000 });
  ok(await page.evaluate(() => document.documentElement.dataset.mode) === undefined && await pageBg() === darkBg,
     '...and Dark puts it back, carrying no attribute at all');
  ok(swLight !== await page.$eval('#uiMenu .sw[data-theme="moss"]', b => getComputedStyle(b).backgroundColor),
     '...the swatches having shown the light half while it was on');
}

// Escape shuts it, like the bell panel it sits beside.
await page.keyboard.press('Escape');
await page.waitForFunction(() => document.getElementById('uiMenu').hidden,
                           null, { timeout: 5000 });
ok(true, 'Escape closes the menu');

// The favicon set: served by the allow-list, linked from the head. Sizes and
// content types matter: a wrong type is a globe in the tab, silently.
const fav = await page.evaluate(async () => {
  const get = async u => { const r = await fetch(u);
    return [r.status, r.headers.get('content-type'), (await r.arrayBuffer()).byteLength]; };
  return { ico: await get('/favicon.ico'), svg: await get('/favicon.svg'),
           touch: await get('/apple-touch-icon.png'),
           links: [...document.querySelectorAll('link[rel*="icon"]')].map(l => l.getAttribute('href')) };
});
ok(fav.ico[0] === 200 && fav.ico[1] === 'image/x-icon' && fav.ico[2] > 1000, 'favicon.ico is served');
ok(fav.svg[0] === 200 && fav.svg[1] === 'image/svg+xml', 'favicon.svg is served');
ok(fav.touch[0] === 200 && fav.touch[1] === 'image/png', 'apple-touch-icon is served');
ok(fav.links.includes('/favicon.svg') && fav.links.includes('/favicon.ico')
   && fav.links.includes('/apple-touch-icon.png'), 'the head links all three');

// ---- which build this is ------------------------------------------------
// Beside the uptime, because an Unraid container keeps serving whatever it
// last pulled: "up two hours" and "has the fix" are different questions, and
// answering the second by inferring from the first is how a published fix and
// a stale container looked identical for a whole afternoon.
const build = await page.$eval('#build', e => ({ text: e.textContent.trim() }));
// The version rather than the commit, because it is the half that can be
// ordered: two shas do not say which came first, which is the question
// anybody reading this is actually asking.
ok(build.text === '0.4.0-dev.390+abc1234',
   'the header carries the ordered version the image was stamped with');
// The detail lives in the About popup now, since a phone cannot hover a tooltip,
// and the truncated string it showed instead answered nothing.
await page.click('#bAbout');
await page.waitForSelector('#aboutModal:not([hidden])');
const about = await page.$eval('#aboutModal', e => e.textContent);
ok(about.includes('abc1234def5678901234567890abcdef12345678')
   && about.includes('2026-08-21T19:30Z') && /An update moves it/.test(about),
   '...and About carries the whole commit, the build time and where to look');
await page.click('#aboutModal >> text=Close');
await page.waitForSelector('#aboutModal', { state: 'hidden' });
// Escape and the backdrop let a person out too (B229): after an update the
// popup opens itself over whatever they came to do.
await page.click('#bAbout');
await page.waitForSelector('#aboutModal:not([hidden])');
await page.keyboard.press('Escape');
await page.waitForSelector('#aboutModal', { state: 'hidden' });
ok(true, 'Escape closes About');
await page.click('#bAbout');
await page.waitForSelector('#aboutModal:not([hidden])');
await page.click('#aboutModal', { position: { x: 4, y: 4 } });
await page.waitForSelector('#aboutModal', { state: 'hidden' });
ok(true, '...and so does a click on the page under it');
// One place for a dialog and the keyboard (R88): focus goes in as it opens,
// Tab and Shift+Tab go round inside it, Escape closes the one on top, and
// the focus comes back to what opened it.
{
  await page.focus('#bAbout');
  await page.keyboard.press('Enter');
  await page.waitForSelector('#aboutModal:not([hidden])');
  await page.waitForFunction(() => document.getElementById('aboutModal').contains(document.activeElement), null, { timeout: 3000 })
    .catch(() => {});
  ok(await page.evaluate(() => document.getElementById('aboutModal').contains(document.activeElement)),
     'a dialog takes the focus as it opens, so a screen reader and Tab start in it');
  let out = 0;
  for (let i = 0; i < 25; i++){
    await page.keyboard.press(i % 5 === 4 ? 'Shift+Tab' : 'Tab');
    if (!(await page.evaluate(() => document.getElementById('aboutModal').contains(document.activeElement)))) out++;
  }
  ok(out === 0, `Tab and Shift+Tab go round inside it, never out to the page behind (${out} of 25 presses left it)`);
  // A second dialog over the first: Escape is the top one's alone.
  await page.evaluate(() => openReport(''));
  await page.waitForSelector('#reportModal:not([hidden])');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#reportModal', { state: 'hidden' });
  ok(await page.evaluate(() => !document.getElementById('aboutModal').hidden),
     'Escape closes the dialog on top, and the one under it stays open');
  await page.keyboard.press('Escape');
  await page.waitForSelector('#aboutModal', { state: 'hidden' });
  ok(await page.evaluate(() => document.activeElement?.id === 'bAbout'),
     `...then that one, and the focus is back on the button that opened it (${await page.evaluate(() => document.activeElement?.id || document.activeElement?.tagName)})`);
  // Every dialog is named by its title: the attribute was spelled
  // aria-labeledby on all of them, which no screen reader reads.
  const names = await page.evaluate(() => ({
    wrong: document.querySelectorAll('[aria-labeledby]').length,
    dangling: [...document.querySelectorAll('[aria-labelledby]')]
      .filter(e => !e.getAttribute('aria-labelledby').split(/\s+/).every(id => document.getElementById(id)))
      .map(e => e.id || e.className) }));
  ok(names.wrong === 0 && names.dangling.length === 0,
     `every dialog names its title by aria-labelledby, and each title is there (${JSON.stringify(names)})`);
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'term'); if (t) dockShow(t.id); });
  const tabs = await page.evaluate(() => ({
    list: document.querySelector('#pane1 .dockline')?.getAttribute('role'),
    on: [...document.querySelectorAll('#pane1 .dockline [role=tab][aria-selected=true]')].map(b => b.dataset.dock),
    cur: panes[1] }));
  ok(tabs.list === 'tablist' && tabs.on.length === 1 && tabs.on[0] === tabs.cur,
     `the dock's line is a tablist, with the terminal showing marked selected (${JSON.stringify(tabs)})`);
}
// ---- the welcome panel: a guide and the changelog behind one switch -------------
// The same popup opens itself twice in an account's life: on the guide the
// first time the account signs in, and on the changelog once after every
// image update. Closing it is the acknowledgement. The fixture owner is
// seeded as having read both, or every file here would open under it.
{
  const prefs = async p => (await fetch(URL + 'api/users', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') },
    body: JSON.stringify({ action: 'prefs', prefs: p }) })).json();
  await prefs({ welcome_seen: false });
  await page.reload(); await ready(page);
  await page.waitForSelector('#aboutModal:not([hidden])', { timeout: 15000 });
  ok(await page.$eval('#abGuide', e => !e.hidden && /Your profile/.test(e.textContent) && /As an administrator/.test(e.textContent)),
     'an account that has not read the guide gets the panel on sign-in, open on the guide: the administrator\'s, for an owner');
  await page.click('.abswitch [data-ab="log"]');
  // Whatever the top section is: Unreleased while entries are accumulating,
  // a dated number the moment somebody bumps. Asserted on the SHAPE (a
  // heading and at least one line under it) rather than on the wording of
  // one of the two, which a bump changes and which reddened this file the
  // day 0.5.0 was cut.
  // Waited on the rendered shape, not on "any text": the panel is filled by
  // a fetch, and a wait that any non-empty content satisfies returns while
  // the list is still being written.
  await page.waitForFunction(() => {
    const e = document.querySelector('#abLog');
    return e && !e.hidden && e.querySelector('h4') && e.querySelector('li');
  }, null, { timeout: 15000 });
  const logShown = await page.$eval('#abLog', e => ({
    hidden: e.hidden, h4: !!e.querySelector('h4'), li: !!e.querySelector('li'),
    text: (e.textContent || '').slice(0, 90) }));
  ok(!logShown.hidden && logShown.h4 && logShown.li,
     `...and the switch shows the changelog, from the file beside the server (${
       JSON.stringify(logShown)})`);
  // What the panel is FOR is "what changed in the build in front of me", and
  // the file behind it grows for the life of the project, and the first bump
  // here put a year of work into one section nobody could read. So it shows
  // what is unreleased plus the newest minor's own releases, and counts what
  // it left out rather than quietly ending. Checked against the real file,
  // which is the one this panel serves.
  const wl = await page.evaluate(async () => await (await fetch('/api/welcome')).json());
  const titles = wl.sections.map(s => s.title);
  ok(wl.series
       ? titles.every(x => x === 'Unreleased' || x.startsWith(wl.series + '.'))
       : (wl.held === 0 && titles.every(x => x === 'Unreleased')),
     `...trimmed to what is unreleased and the ${wl.series || 'no'} releases (${titles.join(', ')})`);
  // The trim itself, on a ladder this repo does not have yet: the newest
  // minor's patches stay, everything under it goes, and Unreleased is never
  // a release to count.
  const trim = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("changelog", ${
  JSON.stringify(new globalThis.URL('../changelog.py', import.meta.url).pathname)})
cl = importlib.util.module_from_spec(spec); spec.loader.exec_module(cl)
secs = [{"title": t, "entries": [{"text": t, "shas": []}]} for t in
        ["Unreleased", "0.7.1 \u2014 2026-10-02", "0.7.0 \u2014 2026-10-01",
         "0.6.3 \u2014 2026-09-20", "0.6.0 \u2014 2026-09-01", "0.5.0 \u2014 2026-08-01"]]
kept, held, series = cl.since_minor(secs)
print(json.dumps({"kept": [s["title"] for s in kept], "held": held, "series": series}))
`], { encoding: 'utf8' }).trim().split('\n').pop());
  ok(trim.series === '0.7' && trim.held === 3
     && trim.kept.join('|') === 'Unreleased|0.7.1 \u2014 2026-10-02|0.7.0 \u2014 2026-10-01',
     `a newer minor takes the older ones off the panel, and they are counted (${
       JSON.stringify(trim)})`);
  // The categories a release was arranged into are shown here too: the panel
  // used to flatten them into one list, which is the arrangement thrown away
  // at the one place most people read it.
  await page.evaluate(() => abDrawLog({ present: true, seen: '', held: 0, series: '0.7',
    sections: [{ title: '0.7.0 \u2014 2026-10-01', entries: [
      { text: 'a loose note', shas: [], cat: '' },
      { text: 'a new tab', shas: [], cat: 'Added' },
      { text: 'a second new tab', shas: [], cat: 'Added' },
      { text: 'pairing works again', shas: [], cat: 'Fixed' }]}]}));
  const grouped = await page.$eval('#abLog', e => ({
    cats: [...e.querySelectorAll('.abcat')].map(c => c.textContent),
    lists: [...e.querySelectorAll('ul')].map(u =>
      [...u.children].map(li => li.textContent)),
    stray: [...e.querySelectorAll('ul > :not(li)')].length }));
  ok(grouped.cats.join('|') === 'Added|Fixed'
     && grouped.lists.length === 3
     && grouped.lists[0].join() === 'a loose note'
     && grouped.lists[1].join() === 'a new tab,a second new tab'
     && grouped.lists[2].join() === 'pairing works again'
     && grouped.stray === 0,
     `a release's categories are shown, each over its own lines (${
       JSON.stringify(grouped.cats)}, ${grouped.lists.length} lists)`);

  // A release the size of the first bump (everything ever logged, dated in
  // one move) is capped with a press to see the rest (B95). Not the section
  // holding the "new since you last looked" line, which is the one thing
  // somebody opening this panel came for.
  await page.evaluate(() => abDrawLog({ present: true, seen: '', held: 0, series: '0.7',
    sections: [{ title: '0.7.0 \u2014 2026-10-01', entries:
      Array.from({ length: 60 }, (_, n) => ({ text: `line ${n}`, shas: [], cat: '' })) }] }));
  const capped = await page.$eval('#abLog', e => ({
    shown: e.querySelectorAll('li').length,
    more: e.querySelector('[data-abmore]')?.textContent.trim() || '' }));
  ok(capped.shown === 25 && /show all 60/.test(capped.more),
     `a release of sixty lines draws twenty-five and offers the rest (${
       capped.shown}, "${capped.more}")`);
  await page.click('#abLog [data-abmore]');
  ok(await page.$$eval('#abLog li', ls => ls.length) === 60
     && await page.$('#abLog [data-abmore]') === null,
     '...and the press draws the whole of it, with nothing left to press');
  // ...while a section carrying the boundary is never cut, whatever its size:
  // the line marking what is new is the panel's whole job on an update.
  await page.evaluate(() => abDrawLog({ present: true, seen: 'deadbee', held: 0, series: '0.7',
    sections: [{ title: '0.7.1 \u2014 2026-10-02', entries:
      Array.from({ length: 60 }, (_, n) => ({ text: `line ${n}`, shas: n === 50 ? ['deadbee'] : [], cat: '' })) }] }));
  ok(await page.$$eval('#abLog li', ls => ls.length) === 60
     && await page.$('#abLog .abnew') !== null,
     '...and a section holding the "new since you last looked" line is drawn whole');

  // ...and the panel says where they went, in a line rather than by stopping.
  await page.evaluate(() => abDrawLog({ present: true, seen: '', held: 4, series: '0.7',
    sections: [{ title: '0.7.0 \u2014 2026-10-01', entries: [{ text: 'a thing', shas: [] }] }] }));
  const held = await page.$eval('#abLog', e => ({
    line: e.querySelector('#abHeld')?.textContent || '',
    words: (e.querySelector('#abHeld')?.textContent || '').trim().split(/\s+/).length }));
  ok(/4 earlier releases are in CHANGELOG\.md\./.test(held.line) && held.words <= 25,
     `...and the panel says so in one line, naming where the rest is (${held.line})`);
  // Put the real answer back under it: the panel opens again below.
  await page.evaluate(() => abLoadLog());
  await page.waitForFunction(
    () => !/a thing/.test(document.querySelector('#abLog')?.textContent || ''),
    null, { timeout: 15000 });

  await page.click('#aboutClose');
  await page.waitForSelector('#aboutModal', { state: 'hidden' });
  await page.waitForFunction(async () => (await (await fetch('/api/status')).json()).welcome.seen === true, null, { timeout: 10000 });
  ok(true, 'closing it marks the guide read, so it does not open again');
  await page.reload(); await ready(page);
  await new Promise(r => setTimeout(r, 800));
  ok(await page.$eval('#aboutModal', e => e.hidden), '...and a reload leaves it shut');
  // An image this account has not seen: the changelog, once.
  await prefs({ image_seen: 'ffffffffffffffffffffffffffffffffffffffff' });
  await page.reload(); await ready(page);
  await page.waitForSelector('#aboutModal:not([hidden])', { timeout: 15000 });
  ok(await page.$eval('#abLog', e => !e.hidden) && await page.$eval('#abGuide', e => e.hidden),
     'an image update opens the panel on the changelog');
  await page.click('#aboutClose');
  await page.waitForSelector('#aboutModal', { state: 'hidden' });
  await page.waitForFunction(async () => (await (await fetch('/api/status')).json()).welcome.image_seen === 'abc1234def5678901234567890abcdef12345678', null, { timeout: 10000 });
  ok(true, '...and closing it acknowledges this image, so the next update is the next time');
}
// An image built before versions existed still has a commit, and the header
// falls back to it rather than going blank.
ok(await page.evaluate(() => { drawBuild({ rev: 'deadbee1234', built: '' });
                               return document.getElementById('build')
                                      .textContent === 'deadbee'; }),
   '...falling back to the commit for an image with no version');
// An image built outside CI carries no stamp, and says so rather than leaving
// a gap that reads as "this dashboard is too old to tell you", in the label
// and in the popup both.
ok(await page.evaluate(() => { drawBuild({ rev: '', built: '' });
                               return document.getElementById('build')
                                        .textContent === 'unstamped'
                                 && /built outside CI/.test(
                                      document.getElementById('aRev').textContent); }),
   'an unstamped image says so, rather than showing nothing');
await page.evaluate(() => refresh());

// The fixture's Claude session ends here: what follows starts from no
// conversation running on alpha, and opens its own where it needs one.
tmuxKill('claude-alpha');
await page.evaluate(() => refresh());

// ---- every node's runner, on the CI runner page ----------------------------
// A view of the NODES' runners: one row each above the chosen node's section
// (the sidebar's Runner card's, until R218 step 3). Drawn directly, because
// each state needs a node to be in a particular one.
const runnerCard = rows => page.evaluate(x => {
  const keep = state.node_runners; state.node_runners = x;
  const box = document.createElement('div');
  box.innerHTML = runnerRows();
  state.node_runners = keep;
  return { body: box.textContent, pills: [...box.querySelectorAll('.sub')].map(e => e.className) };
}, rows);

let rc = await runnerCard([]);
ok(rc.body === '', 'with no runner anywhere there is no list: the node\'s own section says how to add one');
// At a phone's width a row wraps, its state on a line of its own, rather
// than running off the edge (B745).
const narrowRows = await page.evaluate(() => {
  const keep = state.node_runners;
  state.node_runners = [{ id: 'n_x', node: 'bb-dev-sandbox-rh', url: 'http://192.168.1.16:3000/lab/hello', live: true,
                          installed: true, listening: true, busy: false, labels: [] }];
  const box = document.createElement('div'); box.style.width = '300px'; box.style.position = 'absolute';
  box.innerHTML = runnerRows(); document.body.append(box);
  const row = box.querySelector('.row');
  const out = { over: row.scrollWidth - row.clientWidth, lines: row.getBoundingClientRect().height > 50 };
  box.remove(); state.node_runners = keep;
  return out;
});
ok(narrowRows.over <= 1 && narrowRows.lines,
   `at a phone's width a runner row wraps rather than running off the edge (${JSON.stringify(narrowRows)})`);
rc = await runnerCard([{ node: 'bb-sandbox', live: true, installed: true,
  listening: true, busy: false, labels: ['bb-sandbox'] }]);
ok(/bb-sandbox/.test(rc.body) && /listening, idle/.test(rc.body),
   'a listening node runner leads with the node\'s name, which is the label a workflow uses');
rc = await runnerCard([{ node: 'bb-sandbox', live: false, installed: true,
  listening: true, busy: false, labels: [] }]);
ok(/quiet/.test(rc.body) && rc.pills.some(c => /warn/.test(c)),
   '...and a runner on a node nobody has heard from lately is amber, not green');
rc = await runnerCard([{ node: 'bb-sandbox-redhat', live: true, installed: false, listening: false,
  busy: false, labels: [], failed: { id: 'j_1', ended: 1789350000, why: "Libicu's dependencies is missing for Dotnet Core 6.0" } }]);
ok(/install failed (?!: )\S/.test(rc.body) && /Libicu's dependencies is missing/.test(rc.body)
   && rc.pills.some(c => /\bbad\b/.test(c)) && !/not reported yet/.test(rc.body),
   `a runner install that failed says so with its reason and WHEN, in red, not as still waiting (${rc.body.slice(0, 60)})`);
rc = await runnerCard([{ node: 'bb-sandbox-redhat', live: true, installed: true, listening: true,
  busy: false, labels: [], removing: true }]);
ok(/removing now/.test(rc.body) && !/listening/.test(rc.body),
   '...and a runner being removed says that, ahead of the listening it was doing');
rc = await runnerCard([{ node: 'bb-sandbox-redhat', live: true, installed: false, listening: false,
  busy: false, labels: [], installing: true }]);
ok(/installing/.test(rc.body) && !/not reported yet/.test(rc.body),
   '...and one being installed right now says that instead');
await page.evaluate(() => refresh());

// The padlock: a project the operator keeps and runs themselves. Its whole
// point is being the OTHER button: excluding hides a row, this one leaves it
// intact and takes away only the session, so that is what gets asserted.
await page.evaluate(() => { refresh(); openProjectsTab(); });
await page.waitForSelector('.pgrid .pcard[data-row="alpha"] [data-k]', { timeout: 10000, state: 'attached' });
ok(await page.$$eval('.pgrid [data-k]', bs => bs.length > 0),
   "every project's card carries a lock in its menu");
await page.evaluate(() => setLocked('alpha', true));
await page.waitForFunction(
  () => document.querySelector('.pgrid .pcard[data-row="alpha"] [data-c]')?.disabled === true,
  { timeout: 10000 });
const locked = await page.$eval('.pgrid .pcard[data-row="alpha"]', r => ({
  claude: r.querySelector('[data-c="alpha"]')?.disabled,
  shell:  !!r.querySelector('[data-s="alpha"]'),
  note:   r.textContent.replace(/\s+/g, ' '),
}));
ok(locked.claude === true, 'locking a project takes its Claude button away');
ok(locked.shell, '...and leaves the shell, which is the operator\'s own way in');
  // The control moves at once; the padlock beside the NAME comes from the
  // server payload and lands on the next poll. Instant feedback on the thing
  // pressed, and the derived mark a beat behind it rather than the page
  // re-implementing it.
  //
  // The MARK, not a sentence. The row used to carry a whole line under the
  // name restating what the padlock already says, on every locked row forever.
  await page.waitForFunction(
    () => !!document.querySelector('.pgrid .pcard[data-row="alpha"] .lockmark'),
    { timeout: 15000 });
  const note = await page.$eval('.pgrid .pcard[data-row="alpha"]',
    r => r.textContent.replace(/\s+/g, ' '));
  ok(!/read-only/.test(note) && !/no Claude session/.test(note),
     '...marked with the padlock alone, not a sentence under the name as well');
  // ...drawn as a line, as everywhere else, and saying its word: on the card
  // it took the default fill and was a black blob with no word (16 Oct).
  const mark = await page.$eval('.pgrid .pcard[data-row="alpha"] .lockmark', m => {
    const g = getComputedStyle(m.querySelector('svg'));
    return { fill: g.fill, stroke: g.stroke, said: m.textContent.trim() };
  });
  ok(mark.fill === 'none' && mark.stroke !== 'none' && mark.said === 'locked',
     `...the padlock drawn as a line in the dim color, with its word beside it (${JSON.stringify(mark)})`);
await page.evaluate(() => setLocked('alpha', false));
// Unlocking is what is under test, so it is the LOCK that has to stop being
// the reason. The button stays dead here for a different one (alpha has no
// node in this fixture and a Claude session runs on one), and that is the
// row saying one thing at a time rather than two.
await page.waitForFunction(
  () => {
    const b = document.querySelector('.pgrid .pcard[data-row="alpha"] [data-c]');
    return !document.querySelector('.pgrid .pcard[data-row="alpha"] .lockmark')
      && !/locked/.test(saidOf(b));
  },
  { timeout: 15000 });
// Not the disabled state: this fixture has a live claude-alpha session, and
// a button that would take you to a running conversation stays usable
// whatever the node arrangement says.
const backTitle = await page.$eval('.pgrid .pcard[data-row="alpha"] [data-c]',
                                   b => saidOf(b));
ok(!/locked/.test(backTitle) && /no node/.test(backTitle),
   `unlocking gives the row back, and what is left to say is the node it has not got (${
      backTitle.slice(0, 60)})`);

// The Projects tab: every project, pinned or not, and the same controls on
// each. The thumbtack decides only where a project is met, not what it can do.
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.doc .projtab .pcard', { timeout: 15000 });
const inTab = await page.$$eval('.doc .projtab .pcard .name', ns => ns.map(n => n.textContent.trim()));
ok(inTab.length >= 2 && inTab.includes('alpha'),
   'the Projects page lists every project');
ok(await page.$eval('.doc .projtab .pcard', r =>
     !!r.querySelector('[data-open]') && !!r.querySelector('[data-s]')
     && !!r.querySelector('[data-k]') && !!r.querySelector('[data-p]')),
   '...with the same controls on a card: its page, shell, the lock and the pin');

// Unpinning takes a project off the sidebar and leaves it on the tab, whole.
await page.evaluate(() => setProjectPinned('alpha', false));
await page.waitForFunction(
  () => document.querySelector('.doc .projtab [data-p="alpha"]')?.textContent.trim() === 'Pin', { timeout: 15000 });
ok(await page.$$eval('.doc .projtab .pcard .name',
     ns => ns.some(n => n.textContent.trim() === 'alpha')),
   'an unpinned project leaves the sidebar and stays on the page');
ok(await page.$eval('.doc .projtab .pcard[data-row="alpha"]',
     r => !!r.querySelector('[data-c]') && !!r.querySelector('[data-open]')),
   '...still carrying every control, which is the whole promise of the pin');
// The tab is a document, not a card adrift in one. It used to draw itself
// inside .card, rounded, bordered and floating on a darker gutter, while the
// notebook in the pane beside it filled the pane. One language.
ok(await page.$eval('.doc .projtab', e => !e.classList.contains('card'))
   && await page.$eval('.doc:has(.projtab)', e => e.classList.contains('flush')),
   'the Projects tab fills its pane the way the notebook does');
await page.evaluate(() => setProjectPinned('alpha', true));
await page.waitForFunction(
  () => document.querySelector('.doc .projtab [data-p="alpha"]')?.textContent.trim() === 'Unpin', { timeout: 15000 });
ok(true, 'pinning it back reads Unpin again');

// ---- polls do not stack (bug #44) --------------------------------------
// /api/status runs git for every project, and refreshSoon fires three
// refreshes inside four seconds on top of the fifteen-second loop. Stacked,
// each one makes the next slower, which is the shape the stuck-on-"loading…"
// report had. Held open with a route so the overlap is deterministic.
{
  let release, held = 0;
  await page.route('**/api/status*', async route => {
    held++;
    if (held === 1) await new Promise(r => { release = r; });
    await route.continue().catch(() => {});
  });
  const before = held;
  // Five asks while the first is still out. They must coalesce into one more.
  await page.evaluate(() => { refresh(); refresh(); refresh(); refresh(); refresh(); });
  await new Promise(r => setTimeout(r, 400));
  ok(held === before + 1,
     `polls asked while one is out do not stack (${held - before} request in flight)`);
  release();
  // Wait for the deferred poll, do not guess at it: /api/status runs git for
  // every project, so on a loaded box the released request alone can outlast
  // any fixed sleep. A 900ms one failed a full run and passed in isolation.
  const t0 = Date.now();
  while (held < before + 2 && Date.now() - t0 < 15000)
    await new Promise(r => setTimeout(r, 50));
  ok(held >= before + 2,
     `...and the asking is remembered, not dropped: one more goes when it lands (${
        held - before} in ${Date.now() - t0}ms)`);
  await page.unroute('**/api/status*');
}
// ...and the revisions poll the same (R88): the timer, a tab coming back and
// a menu let go each start one, and stacked an older reply landing second
// set the page's revisions back and fired every watch again.
{
  let release, held = 0;
  await page.route('**/api/revs*', async route => {
    held++;
    if (held === 1) await new Promise(r => { release = r; });
    await route.continue().catch(() => {});
  });
  // Started, not awaited: the request it sends is the one held open.
  // Waited on as the held request, not on revsBusy: a poll the page sent
  // before the route went in sets that too, and the test's own then goes
  // later as the remembered one, inside the window below.
  await page.evaluate(() => { pollRevs(); });
  for (const t0 = Date.now(); held < 1 && Date.now() - t0 < 10000;) await new Promise(r => setTimeout(r, 50));
  const before = held;
  await page.evaluate(() => { pollRevs(); pollRevs(); pollRevs(); pollRevs(); });
  await new Promise(r => setTimeout(r, 2000));      // past the 1.5 s timer too
  ok(held === before,
     `revision polls asked while one is out do not stack (${held - before + 1} in flight)`);
  release();
  const t0 = Date.now();
  while (held < before + 1 && Date.now() - t0 < 15000) await new Promise(r => setTimeout(r, 50));
  ok(held >= before + 1, `...and one more goes when it lands (${held - before} after ${Date.now() - t0}ms)`);
  await page.unroute('**/api/revs*');
}


ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);

// Unpinning from the sidebar has to move the Projects TAB too: they render
// the same rows from the same state, and a tab that drew once showed a lit
// thumbtack for a project that was no longer pinned, and then clicking it sent
// the state it was already in, which is what "pinning only works sometimes"
// was. No poll is waited for: the answer to the pin request is the new set.
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.doc .projtab .pcard', { timeout: 15000 });
// The card's menu says Unpin while it is pinned, Pin once it is not.
const tackLit = () => page.$eval('.doc .projtab [data-p="beta"]', b => b.textContent.trim() === 'Unpin');
ok(await tackLit(), 'the Projects page shows beta pinned');
await page.evaluate(() => setProjectPinned('beta', false));
await page.waitForFunction(() =>
  document.querySelector('.doc .projtab [data-p="beta"]')?.textContent.trim() === 'Pin',
  { timeout: 5000 });
ok(true, '...and unpinning it there turns the page\'s menu item to Pin too');
ok(await page.evaluate(() => !(state.projects.find(p => p.name === 'beta') || {}).pinned),
   '...with the project unpinned in the same breath');
await page.evaluate(() => setProjectPinned('beta', true));
await page.waitForFunction(() =>
  document.querySelector('.doc .projtab [data-p="beta"]')?.textContent.trim() === 'Unpin',
  { timeout: 5000 });
ok(true, '...and pinning it back lights it again, first click');
// A project whose name has a dot in it: the row's own selector has to survive
// one, or the change lands without its animation and nothing says why.
await page.evaluate(() => setProjectPinned('ep.silon', false));
await page.waitForFunction(() =>
  document.querySelector('.doc .projtab [data-p="ep.silon"]')?.textContent.trim() === 'Pin', { timeout: 8000 });
ok(true, 'a dotted project name unpins too, animation and all');
// ...and back, which is the direction that used to be a plain redraw: pinning
// is watched from the Projects tab, which on a desktop sits in the column
// beside the sidebar, so the row has to unroll rather than shove the projects
// under it down between two frames. The tween is caught while it runs, since
// the row exists before it and waiting for the row alone would prove nothing.
// Watched at the call rather than caught mid-flight: the tween is 170ms,
// and a poll that evaluates in the page over CDP can take longer than that
// on a loaded box; this passed on the controller and failed three times
// out of four on bb-sandbox with the row rendered, motion allowed and no
// stub in the way. What is asserted is the same: the row was tweened rather
// than snapped in.
await page.evaluate(() => setProjectPinned('ep.silon', true));
await page.waitForFunction(() =>
  document.querySelector('.doc .projtab [data-p="ep.silon"]')?.textContent.trim() === 'Unpin', { timeout: 8000 });

// The docker manager is the Containers page. What it LISTS is asserted in
// devapp.mjs, where a project actually has a compose file and an instance.
// Here there are none, so the only honest assertion is that the tab opens and
// shows the daemon's own containers.
await page.click('#rail [data-rail="containers"]');
await page.waitForSelector('.dmtab', { timeout: 15000 });
// Waited for, not read off the first draw: on an agent node the listing is
// a probe job, so the rows can land a draw after the tab does.
await page.waitForFunction(() => [...document.querySelectorAll('.dmtab .row')]
  .some(r => /someone-elses/.test(r.textContent) && r.classList.contains('off')),
  null, { timeout: 15000 }).catch(() => {});
ok(await page.$$eval('.dmtab .row', rs =>
     rs.some(r => /someone-elses/.test(r.textContent) && r.classList.contains('off'))),
   'the manager shows a container this dashboard did not start, marked not ours');
// Every group on the rail carries an icon, and the Containers item wears the
// Docker tab's own: a page and its tool are one thing in two places.
ok(await page.evaluate(() => [...document.querySelectorAll('#rail [data-rail]')].every(b => b.querySelector('svg'))
     && (() => { const d = document.createElement('div'); d.innerHTML = TOOL_ICONS.docker;
                 return document.querySelector('#rail [data-rail="containers"] svg')?.outerHTML === d.firstElementChild.outerHTML; })()),
   'every group on the rail carries an icon, Containers the Docker tab\'s');
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.doc .projtab .pcard', { timeout: 15000 });

const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [path, body]);

// Renaming is a dialog now, not a prompt. One dialog, two doors: the gear is
// the project's own settings and the chain is GitHub's half of them, so where
// a credential is changed does not depend on whether a remote exists yet.
await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnName', el => el.value) === 'alpha',
   'the rename dialog opens on the current name');
ok(/Folder: \/workspace\/alpha · project #\d+/.test(await page.$eval('#rnHint', e => e.textContent)),
   'the settings say the folder the project lives in, and its id, under the name');
{
  // Sections, every one open by default at every width, with a jump bar
  // over them (the operator, 8 Oct: too much was hidden in folds). One shut
  // stays shut for the page's life; the chain's door shows the repository's
  // alone, open. Read with $eval, which the harness's own fold-opening leaves be.
  const folds = (p = page) => p.$$eval('details.rngroup', ds => ds.map(d => ({
    k: d.dataset.sect, open: d.open, shown: getComputedStyle(d).display !== 'none' })));
  const shut = fs => fs.filter(f => f.shown && !f.open).map(f => f.k).join();
  const gear = await folds();
  ok(!shut(gear) && gear.filter(f => f.shown).length > 3,
     `the settings are sections, every one open (${shut(gear) || 'none shut'})`);
  const jumps = await page.$$eval('#rnmodal .sectjump a', as => as.map(a => a.textContent));
  ok(jumps.includes('The project') && jumps.includes('Claude may'),
     `...with a jump bar naming them (${jumps.join(', ')})`);
  await page.$eval('details[data-sect="rn:claude"] > summary', s => s.click());
  await page.waitForFunction(() => !document.querySelector('details[data-sect="rn:claude"]').open, null, { timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(300);
  ok(shut(await folds()) === 'rn:claude', `...a heading pressed shuts its own section alone (${shut(await folds())})`);
  await page.evaluate(() => { closeRename(); renameProject('alpha', 'git'); });
  const chain = await folds();
  ok(chain.filter(f => f.shown).map(f => f.k).join() === 'rn:repo' && chain.find(f => f.k === 'rn:repo')?.open,
     `...and the chain's door shows the repository's section alone, open (${JSON.stringify(chain.filter(f => f.shown))})`);
  await page.evaluate(() => { closeRename(); renameProject('alpha'); });
  ok(shut(await folds()) === 'rn:claude', `...and the gear opens again with the one this person shut, shut (${shut(await folds())})`);
  await page.$eval('#rnmodal .sectjump a:last-child', a => a.click()).catch(() => {});
  await page.$$eval('#rnmodal .sectjump a', as => as.find(a => a.textContent === 'Claude may')?.click());
  await page.waitForFunction(() => document.querySelector('details[data-sect="rn:claude"]').open, null, { timeout: 5000 }).catch(() => {});
  ok(!shut(await folds()), '...and its name in the jump bar opens it again');
  // A phone: every section open there too.
  const phone = await newPage(browser, { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await phone.goto(URL);
  await ready(phone);
  await phone.evaluate(() => renameProject('alpha'));
  await phone.waitForSelector('#rnmodal:not([hidden])');
  ok(!shut(await folds(phone)), `on a phone every section is open too (${shut(await folds(phone)) || 'none shut'})`);
  await phone.close();
}
ok(await page.evaluate(() => document.activeElement?.tagName) !== 'INPUT',
   '...with the keyboard down, like every other dialog here');
ok(await page.$eval('#rnTokenField', el => el.hidden)
   && await page.$eval('#rnAuthField', el => el.hidden),
   '...and holds no credential: the gear is the project, the chain is its remote');
// Its people (membership.py): the owner, who may hand it on and make it
// invite only, staged until Save, and an Invite that acts on the press.
await page.waitForSelector('#rnPeopleField:not([hidden]) #rnOwner', { timeout: 10000 });
// What Invite only allows is the ? help on People now (R244), not prose
// drawn on every visit; the section itself is the two settings and a facts
// line.
ok(await page.$eval('#rnOwner', s => s.value) === 'test'
   && await page.$('#rnInviteOnly:not([disabled])') !== null
   && /Any administrator can add people/.test(await page.$eval('#rnPeopleLabel .help', e => e.dataset.help))
   && /On it:/.test(await page.$eval('#rnPeople', e => e.textContent)),
   'the gear shows the project\'s owner, to hand on, and Invite only, off, what that allows behind the ? on People');
await page.click('#rnInviteOnly');
ok(await page.$eval('#rnInviteOnly', c => c.checked)
   && (await api('/api/members', { action: 'view', project: 'alpha' })).body.invite_only === false,
   '...ticking Invite only stages it and changes nothing until Save');
// People is a section of its own (R255 step 7): its change wakes its own
// Save, not The project's.
await page.waitForFunction(() => !document.querySelector('.rnbar[data-rnbar="people"] [data-rnsave]')?.disabled, null, { timeout: 5000 });
ok(await page.$eval('#rnPeopleField', f => f.closest('details')?.dataset.sect === 'rn:people')
   && await page.$eval('.rnbar[data-rnbar="project"] [data-rnsave]', b => b.disabled),
   '...in a People section of its own, whose Save it wakes and The project\'s not');
await page.click('#rnInviteOnly');
// ...and Claude may reads the Git view's session dials too, set there.
const gp = await page.evaluate(() => ({ text: document.getElementById('rnGitPol')?.textContent, hidden: document.getElementById('rnGitPolField')?.hidden,
  sect: document.getElementById('rnGitPolField')?.closest('details')?.dataset.sect, pol: (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.gitpol }));
ok(/its branches allow · to main deny · a sensitive push held for you/.test(gp.text || '') && !gp.hidden && gp.sect === 'rn:claude',
   `Claude may shows the Git view's push dials, with the way to where they are set (${JSON.stringify(gp)})`);
// Its Android signing keys (R106), an administrator's: a row per route,
// a picked keystore staged until Save, its password asked for before
// anything is sent, and a key the server will not keep refused in the
// dialog, which stays open.
await page.waitForSelector('#rnSignField:not([hidden]) .rnsign[data-route="sideload"]', { timeout: 10000 });
const signRows = await page.$$eval('#rnSignRows .rnsign[data-key]', rs => rs.map(r => r.firstElementChild.textContent.trim()));
// ...under the backup password's line, the project's owner's to set (the
// fixture's owner owns alpha).
ok(/Backup password: none/.test(await page.$eval('#rnSignRows .rnsignlock', e => e.textContent))
   && /No key can be added or made until it has one: set it first/.test(await page.$eval('#rnSignRows .rnsignlock .sub.bad', e => e.textContent))
   && await page.$('#rnLockOpen') !== null && await page.$('#rnSignRows [data-signopen]') === null,
   'the signing keys open on whether their backups have a password, and with none no key can be added, the owner told to set it first');
// Set, as the owner does it, and the keys can be added.
await page.click('#rnLockOpen');
await page.fill('#rnLockNew', 'a-backup-password');
await page.fill('#rnLockAgain', 'a-backup-password');
await page.click('#rnLockGo');
await page.waitForFunction(() => /Backup password: set/.test(document.querySelector('#rnSignRows .rnsignlock')?.textContent || ''), null, { timeout: 10000 });
await page.waitForSelector('#rnSignRows .rnsign[data-route="sideload"] [data-signopen]', { timeout: 10000 });
ok(true, '...and once the owner sets one, Upload one is offered');
ok(signRows.length === 2 && /^Play upload key: none$/.test(signRows[0]) && /^Sideload signing key: none$/.test(signRows[1]),
   `the gear shows the project's two signing keys, none yet (${signRows.join(' / ')})`);
await page.click('#rnSignRows .rnsign[data-route="sideload"] [data-signopen]');
writeFileSync(`${DIR}/not-a-keystore.p12`, 'not a keystore');
await page.setInputFiles('#rnSignRows .rnsign[data-route="sideload"] [data-signfile]', `${DIR}/not-a-keystore.p12`);
ok(/type the keystore's password/.test(await sectSave(page, 'signing')),
   '...a picked keystore with no password is stopped on its section\'s bar before anything is sent');
await page.fill('#rnSignRows .rnsign[data-route="sideload"] [data-signpass]', 'p');
const signErr = await sectSave(page, 'signing');
ok(!await page.$eval('#rnmodal', e => e.hidden)
   && !(await api('/api/signing', { project: 'alpha', action: 'list' })).body.keys.default?.sideload,
   `...and one the server will not keep is refused in the dialog, which stays open, with nothing kept (${signErr.slice(0, 90)})`);
await api('/api/signing', { action: 'backup-password', project: 'alpha', current: 'a-backup-password', new: '' });
// A rotated key (R106 step 7): the retired one says why it is kept and
// offers no Remove; the one it went to says who still sees the old.
{
  const sd = `${DIR}/state/signing/alpha`;
  for (const [k, rec] of [['default', { retired_for: 'watch' }], ['watch', { rotated_from: 'default' }]]){
    mkdirSync(`${sd}/${k}`, { recursive: true });
    writeFileSync(`${sd}/${k}/sideload.ks`, 'k');
    writeFileSync(`${sd}/${k}/sideload.json`, JSON.stringify({ route: 'sideload', key: k, alias: k, backed_up: 1,
      sha256: 'AB:'.repeat(31) + 'AB', store_pass: 'x', ...rec }));
  }
  await page.evaluate(() => rnLoadSigning('alpha'));
  await page.waitForSelector('.rnsign[data-key="watch"][data-route="sideload"]', { timeout: 10000 });
  const rows = await page.$$eval('.rnsign[data-route="sideload"]', rs => rs.map(r => ({ key: r.dataset.key,
    text: r.textContent.replace(/\s+/g, ' '), remove: !!r.querySelector('[data-signremove]'), rotate: !!r.querySelector('[data-rotate]') })));
  const old = rows.find(r => r.key === 'default'), now = rows.find(r => r.key === 'watch');
  ok(old && /Retired: rotated to watch\. Kept, since the proof and every device before Android 9 still need it/.test(old.text) && !old.remove && !old.rotate
     && now && /Rotated from default: Android 9 and newer see this key, older devices still see default/.test(now.text) && !now.rotate,
     'a retired sideload key says why it is kept and offers no Remove, and the key it went to says who still sees the old one');
  rmSync(sd, { recursive: true, force: true });
  await page.evaluate(() => rnLoadSigning('alpha'));
}
await page.click('#rnCancel');

// An invitation waiting on this account sits in the bell with its answer,
// above the page's own notes, like every other thing waiting on you.
// The poll held for it (B750): one landing between the write and the read
// put the server's empty list back.
await holdPoll(page);
await page.evaluate(() => { state.invites = [{ id: 7, project: 'beta', by: 'ada', at: Math.floor(Date.now() / 1000) }];
  toggleBell(true); drawBell(); });
ok(await page.$eval('#bellPanel', e => /invited to beta/.test(e.textContent) && /ada invited you to work on beta/.test(e.textContent))
   && await page.$('#bellPanel [data-binvite="7"][data-yes="1"]') !== null
   && await page.$('#bellPanel [data-binvite="7"][data-yes="0"]') !== null,
   'an invitation to a project is in the bell with Accept and Decline');
await freePoll(page);
await page.evaluate(() => { state.invites = []; drawBell(); toggleBell(false); });

// The chain, on a project that already has one. alpha can push (the
// retroactive seeding granted it, on the deploy key its remote uses), so it
// is offered a token, and told what setting one does and does not do.
await pjMenu('alpha');
await page.click('.doc .projtab [data-l="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(/GitHub/.test(await page.$eval('#rnTitle', e => e.textContent))
   && await page.$eval('#rnNameField', el => el.hidden)
   && await page.$eval('#rnMineField', el => el.hidden),
   'the chain opens the same dialog on the remote alone, with the rest put away');
ok(!await page.$eval('#rnTokenField', el => el.hidden),
   'a project pushing with a deploy key is offered a token');
const kh = await page.$eval('#rnTokenHint', e => e.textContent);
ok(/deploy key/.test(kh) && /does nothing until the switch below/.test(kh),
   '...told in a line that setting one does not switch anything by itself');
// The switch that makes it take effect. alpha's remote is ssh and it has no
// token, so the choice is real but one-sided until a token exists, and the
// side you cannot take is disabled rather than absent, because a control that
// silently does nothing is worse than one that says why.
await page.waitForSelector('#rnAuthField:not([hidden])', { timeout: 8000 });
ok(await page.$eval('#rnAuthKey', b => b.classList.contains('on') && !b.disabled),
   'the authentication segment opens on the credential the remote actually uses');
ok(await page.$eval('#rnAuthToken', b => b.disabled),
   '...with the token side disabled while no token is stored');
ok(/No token is stored/.test(await page.$eval('#rnAuthHint', e => e.textContent)),
   '...saying so, rather than leaving a dead button to be poked at');
await page.fill('#rnToken', 'ghp_ExampleTokenValue123');
await page.waitForFunction(() => !document.getElementById('rnAuthToken').disabled,
                           { timeout: 5000 });
ok(true, 'typing a token turns the switch on: setting one and using it is one intention');
await page.click('#rnAuthToken');
ok(await page.$eval('#rnAuthToken', b => b.classList.contains('on'))
   && !await page.$eval('#rnAuthKey', b => b.classList.contains('on')),
   '...and picking it moves the segment without touching either credential');
ok(/the key stays|stays stored/.test(await page.$eval('#rnAuthHint', e => e.textContent)),
   '...promising in words that switching removes neither');
await page.fill('#rnToken', '');
// Clearing, which is the other half of a stored token: it cannot be shown and
// must not be typed over blind, so the field is closed and this is the way in.
await page.click('#rnCancel');
await page.evaluate(() => renameProject('alpha', 'git'));
ok(await page.$eval('#rnDelete', e => e.hidden), 'the chain\'s door has no Delete: it is about the remote, not the project');
await page.waitForSelector('#rnAuthField:not([hidden])', { timeout: 8000 });
ok(await page.$eval('#rnTokenClear', b => b.hidden),
   'a project with no token stored is offered nothing to clear');
// The address, for the same repository after its owner is renamed on the
// host: filled from the remote as written, sent only when changed, and a
// refusal said in the dialog with the remote left where it was.
const addrWas = await page.$eval('#rnAddr', e => e.value);
ok(!await page.$eval('#rnAddrField', e => e.hidden) && /alpha/.test(addrWas),
   `the chain's door shows where the remote points, to change after a rename on the host (${addrWas})`);
await page.fill('#rnAddr', 'https://elsewhere.example/someone/alpha.git');
const addrErr = await sectSave(page, 'repo');
ok(/another host/.test(addrErr) && !await page.$eval('#rnmodal', e => e.hidden),
   `...an address on another host is refused in the dialog, which stays open (${addrErr.slice(0, 80)})`);
const addrAfter = await api('/api/project-auth', { name: 'alpha' });
ok(addrAfter.body.url === addrWas, '...and the remote still points where it did');
await page.fill('#rnAddr', addrWas);
await page.evaluate(() => { rnBarSay('repo', ''); rnBars(); });

// Test (the operator, 7 Oct): a press asks the server for a read and a
// dry-run push and draws what is missing in red under the button, a list
// when it is more than one thing; the server's half is unit/test_auth_test.py,
// so its answer is set here and the draw is what is read.
{
  ok(!await page.$eval('#rnTestField', e => e.hidden), 'the chain\'s door offers Test for a project with a remote');
  let asked = null;
  const answer = { using: 'its deploy key', mode: 'ssh', read: true, push: false,
                   missing: ['write access for the deploy key: ERROR: The key you are authenticating with has been marked as read only.',
                             'the workflow scope'],
                   notes: ['This project was set up without push rights.'] };
  await page.route('**/api/project-auth', async route => {
    const b = JSON.parse(route.request().postData() || '{}');
    if (b.action !== 'test') return route.continue();
    asked = b;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(answer) });
  });
  await page.$eval('#rnTest', b => b.click());
  await page.waitForSelector('#rnTestOut:not([hidden])', { timeout: 10000 });
  const out = await page.$eval('#rnTestOut', e => ({ text: e.textContent, bad: e.classList.contains('bad'),
    items: e.querySelectorAll('li').length, label: document.getElementById('rnTest').textContent }));
  ok(asked?.name === 'alpha' && asked.token === '' && out.bad && out.items === 2
     && /With its deploy key it is missing/.test(out.text) && /marked as read only/.test(out.text)
     && /without push rights/.test(out.text) && out.label === 'Test',
     `...and what it is missing is said under it in red, one line each (${out.text.slice(0, 90)})`);
  answer.missing = []; answer.push = true; answer.notes = [];
  await page.$eval('#rnTest', b => b.click());
  await page.waitForFunction(() => /can read and push/.test(document.getElementById('rnTestOut').textContent), null, { timeout: 10000 });
  ok(await page.$eval('#rnTestOut', e => !e.classList.contains('bad')),
     '...and a credential with everything says it can read and push');
  await page.unroute('**/api/project-auth');
}

// The remaining states need a project holding both credentials, which no
// fixture here does, so the answer the dialog was given is set directly and
// the real draw runs against the real DOM. What is being tested is the state
// machine, and it takes exactly this one input.
const authState = (opts, now) => page.evaluate(([o, n]) => {
  rnAuthOpts = o; rnAuthNow = n; rnAuthPick = n; rnClearToken = false;
  document.getElementById('rnToken').value = '';
  rnDrawAuth();
}, [opts, now]);
const seen = () => page.evaluate(() => ({
  closed: document.getElementById('rnToken').disabled,
  clear: !document.getElementById('rnTokenClear').hidden,
  key: document.getElementById('rnAuthKey').disabled,
  token: document.getElementById('rnAuthToken').disabled,
  onKey: document.getElementById('rnAuthKey').classList.contains('on'),
  onToken: document.getElementById('rnAuthToken').classList.contains('on'),
  onNone: document.getElementById('rnAuthNone').classList.contains('on'),
  bad: document.getElementById('rnAuthHint').classList.contains('bad'),
  hint: document.getElementById('rnAuthHint').textContent,
}));

await authState({ now: 'ssh', token: true, ssh: true }, 'ssh');
let v = await seen();
ok(v.closed && v.clear && !v.key && !v.token && v.onKey,
   'a stored token closes the field and offers a way to clear it, both sides live');
await page.click('#rnTokenClear');
v = await seen();
ok(!v.closed && v.token && v.onKey && !v.onToken,
   '...and clearing opens the field, ghosts the token side and puts the pick back on the key');
ok(await page.$eval('#rnTokenClear', b => /Keep the stored token/.test(b.textContent)),
   '...with the way back offered, since nothing has happened to the project yet');

// Only a token, no key: the side that does not exist is the ghosted one, and
// the pick cannot leave the side that does.
await authState({ now: 'https', token: true, ssh: false }, 'https');
v = await seen();
ok(v.closed && v.key && !v.token && v.onToken,
   'with no deploy key the key side is ghosted and the pick stays on the token');
// Clearing does NOT slide the pick somewhere else. It stays where it was put,
// goes invalid, and Save refuses: being corrected without being asked is how
// you end up on a credential you did not choose.
await page.click('#rnTokenClear');
v = await seen();
ok(v.onToken && v.token,
   'clearing the token leaves the pick where it was, and ghosts it');
ok(v.bad && /none will be stored/.test(v.hint),
   '...saying in red that there will be nothing to authenticate with');
ok(/no access token after this save/.test(await sectSave(page, 'repo')),
   '...and Save refuses rather than writing a remote with no credential');
// Disabled is the third answer, and always takeable: it is the absence of a
// credential rather than the presence of one.
ok(!await page.$eval('#rnAuthNone', b => b.disabled),
   'Disabled is always offered: turning pushing off is a real answer');
await page.click('#rnAuthNone');
v = await seen();
ok(v.onNone && !v.bad,
   '...and picking it settles the dialog, because nothing is missing any more');

// File access over FTP (R151): the owner's section, staged until Save. alpha
// has no node here, so turning it on is refused in the dialog by name; an
// account's access saves on its own, and reads back on the next open.
await page.click('#rnCancel');
{
  await page.evaluate(n => renameProject(n), 'alpha');
  await page.waitForSelector('#rnmodal:not([hidden])');
  await page.waitForSelector('#rnFtpField:not([hidden])', { timeout: 10000 });
  await page.evaluate(() => { const d = document.querySelector('details[data-sect="rn:files"]'); d.open = true; });
  const shut = await page.$eval('#rnFtp', e => ({ port: e.querySelector('.logdays').hidden,
    people: e.querySelector('.rnftppeople').hidden }));
  await page.click('#rnFtpOn');
  const open = await page.$eval('#rnFtp', e => ({ port: e.querySelector('.logdays').hidden,
    people: e.querySelectorAll('.rnftprow').length, noNode: /no node to run on/.test(e.textContent),
    value: e.querySelector('#rnFtpPort').value }));
  ok(shut.port && shut.people && !open.port && open.people >= 1 && open.noNode && open.value === '2121',
     `the owner's File access section offers the port and each account once it is ticked, and says alpha has no node (${JSON.stringify(open)})`);
  const err = await sectSave(page, 'files');
  ok(/no node to run its file access on/.test(err) && !await page.$eval('#rnmodal', e => e.hidden),
     `...and Save refuses turning it on with no node, in the dialog (${err.slice(0, 70)})`);
  const uid = await page.$eval('#rnFtp [data-ftpuid]', s => s.dataset.ftpuid);
  await page.selectOption(`#rnFtp [data-ftpuid="${uid}"]`, 'rw');
  const draft = await page.evaluate(() => rnFtpChange());
  ok(draft?.on === true && draft.port === 2121 && draft.access?.[uid] === 'rw',
     `...and what Save sends is the switch, the port and the access picked (${JSON.stringify(draft)})`);
  // The editor's door (R159): its own switch over the same people, with no
  // port, and FTPS left off.
  await page.click('#rnFtpOn');
  await page.click('#rnFtpEditor');
  const ed = await page.$eval('#rnFtp', e => ({ port: e.querySelector('.logdays').hidden,
    people: e.querySelector('.rnftppeople').hidden, noNode: /no node to run on/.test(e.textContent) }));
  const edDraft = await page.evaluate(() => rnFtpChange());
  ok(ed.port && !ed.people && !ed.noNode && edDraft?.editor === true && !edDraft.on,
     `...and opening it in an editor is a switch of its own: the same people, no port, no node needed (${JSON.stringify({ ...ed, ...edDraft })})`);
  await page.click('#rnCancel');
  const set = await api('/api/project-ftp', { action: 'set', project: 'alpha', access: { [uid]: 'r' } });
  const back = await api('/api/project-ftp', { project: 'alpha' });
  ok(set.status === 200 && back.body.on === false && back.body.people.find(p => p.uid === uid)?.access === 'r',
     `...and an account's access is kept while it is off (${JSON.stringify(back.body.people)})`);
  await api('/api/project-ftp', { action: 'set', project: 'alpha', access: { [uid]: '' } });
}

// What Claude runs on here, back through the gear. Per project, and applied
// when a session starts rather than typed into a running one, so the dialog's
// job is to say which of those two you are doing.
await page.evaluate(() => { if (!document.getElementById('rnmodal').hidden) closeRename(); });
await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnTitle', e => e.textContent.trim()) === 'alpha',
   'the dialog is the project\'s settings, not a rename form wearing its name');
ok(await page.$$eval('.rnbar', bs => bs.length >= 5 && bs.every(b => b.querySelector('[data-rnsave]') && b.querySelector('[data-rnrevert]')
     && [...b.querySelectorAll('button')].every(x => x.disabled))),
   '...each section with its own Save and Revert, dead while nothing in it has changed');
// The bin is here too, at the foot of the gear's door: on the All projects
// tab it sits behind the row's fold on a phone, which is where it was not
// being found. It asks first, and a declined ask moves nothing.
ok(!await page.$eval('#rnDelete', e => e.hidden) && /Delete project/.test(await page.$eval('#rnDelete', e => e.textContent)),
   'the settings dialog offers Delete project at its foot');
{
  const auto = page.listeners('dialog')[0];
  page.off('dialog', auto);
  let asked = '';
  page.once('dialog', d => { asked = d.message(); page.dialogs.push(asked); d.dismiss(); });
  await page.click('#rnDelete');
  await page.waitForFunction(() => document.getElementById('rnmodal').hidden, { timeout: 15000 });
  page.on('dialog', auto);
  ok(/moves to \/workspace\/\.trash\/alpha/.test(asked) && existsSync(`${DIR}/ws/alpha/.git`),
     '...which asks, names the bin, and moves nothing when declined');
  await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])');
}
await page.selectOption('#rnAsks', 'fewer');
ok(!await page.$eval('#rnAsks', e => e.disabled) && !(await page.$('#rnModel')) && !(await page.$('#rnEffort'))
   && /next time Claude starts/.test(await page.$eval('#rnPrefHint', e => e.textContent))
   && /picked each time a session starts, in the Claude button's menu/.test(await page.$eval('#rnPrefHint', e => e.textContent)),
   'with no session running it simply applies at the next start; the model and effort are no longer the dialog\'s');
// A color for the project: nine swatches, none by default, and the one
// picked is worn by the row and by the notebook tab once saved.
await page.selectOption('#rnAsks', '');
ok(await page.$$eval('#rnColor [data-color]', bs =>
     bs.length === 9 && bs[0].dataset.color === '' && bs[0].getAttribute('aria-checked') === 'true'),
   'the dialog offers a color, with none picked for a project nobody colored');
await page.click('#rnColor [data-color="teal"]');
// The bars wake on a 0 ms timer after the click (B691): read them after it.
await page.waitForFunction(() => !document.querySelector('.rnbar[data-rnbar="project"] [data-rnsave]')?.disabled, null, { timeout: 5000 });
ok(await page.$eval('.rnbar[data-rnbar="project"] [data-rnsave]', b => !b.disabled)
   && await page.$eval('.rnbar[data-rnbar="runs"] [data-rnsave]', b => b.disabled),
   'a change wakes its own section\'s Save and no other');
ok(!(await sectSave(page, 'project')), '...which saves it');
await page.click('#rnCancel');
await page.waitForFunction(() => document.getElementById('rnmodal').hidden, null, { timeout: 10000 });
await refreshUntil(page, () => (state?.projects || [])
  .find(p => p.name === 'alpha')?.prefs?.color === 'teal', { timeout: 20000 });
ok(await page.$eval('.doc .projtab [data-row="alpha"]', r =>
     r.classList.contains('pc') && /--pc:/.test(r.getAttribute('style') || '')),
   'saving a color puts it on the project\'s row');
await page.evaluate(() => openNotebook('alpha'));
await nbShown(page);
ok(await page.evaluate(() => {
     const b = document.querySelector('#pane0 .bar.proj');
     return !!b && b.classList.contains('pc') && /--pc:/.test(b.getAttribute('style') || '');
   }), "...and on its page's header");
await page.evaluate(async () => {
  await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ project: 'alpha', color: '' }) });
});
await refreshUntil(page, () => !(state?.projects || [])
  .find(p => p.name === 'alpha')?.prefs?.color, { timeout: 20000 });
await page.waitForFunction(() => !document.querySelector('#pane0 .bar.proj')?.classList.contains('pc'), null, { timeout: 20000 });
ok(true, '...and none takes it off again');
// Back to the projects tab, which the notebook pushed out of the pane.
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.doc .projtab .pcard', { timeout: 15000 });
await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
await page.waitForSelector('#rnmodal:not([hidden])');
await page.click('#rnCancel');

// Saving and interrupting are two decisions, and only one of them is asked
// about. Declining the restart used to return before anything was written, so
// somebody who wanted the setting kept and their conversation left alone got
// neither, and restarting the session by hand afterwards changed nothing,
// because there was nothing stored to read (B88).
{
  tmuxNew('claude-alpha', `${DIR}/ws/alpha`);
  await refreshUntil(page, () => liveSessions().has(myClaude('alpha')),
                     { timeout: 20000 });
  await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])');
  await page.selectOption('#rnAsks', 'fewer');
  // Both answers are on the section's bar from the start (the operator,
  // 10 Oct): a first press that only asked saved nothing for whoever pressed
  // it once and moved on.
  const before = page.dialogs.length;
  await page.waitForSelector('.rnbar[data-rnbar="yours"] [data-rnkeep]:not([hidden])', { timeout: 10000 });
  const asked = await page.$eval('.rnbar[data-rnbar="yours"]', b => ({
    state: b.querySelector('.state').textContent, save: b.querySelector('[data-rnsave]').hidden,
    keep: b.querySelector('[data-rnkeep]').textContent, end: b.querySelector('[data-rnend]').textContent,
    others: [...document.querySelectorAll('.rnbar:not([data-rnbar="yours"]) [data-rnsave]')].every(x => x.disabled),
    stored: (state?.projects || []).find(p => p.name === 'alpha')?.yours?.asks || '' }));
  ok(asked.save && asked.keep === 'Save, keep it running' && asked.end === 'Save and end it'
     && /^Questions changed; its running session takes Questions only when it starts$/.test(asked.state)
     && asked.others && asked.stored === '' && page.dialogs.length === before,
     `with a session running, the section's bar names what it takes only at its start and offers both answers at once (${JSON.stringify(asked)})`);
  ok(!(await sectSave(page, 'yours')), '...Save, keep it running saves');
  await refreshUntil(page, () => (state?.projects || [])
    .find(p => p.name === 'alpha')?.yours?.asks === 'fewer', { timeout: 20000 });
  ok(true, '...and keeping it running still saves the setting');
  ok(await page.evaluate(() => liveSessions().has(myClaude('alpha'))),
     '...while the session it declined to restart is still running');
  ok(await page.$eval('.rnbar[data-rnbar="yours"]', b => !b.querySelector('[data-rnsave]').hidden && b.querySelector('[data-rnsave]').disabled
       && !document.getElementById('rnmodal').hidden),
     '...and the bar goes quiet with the form still open');
  // The other answer: saved, and the session ended for the next press of
  // Claude to start on the new setting.
  await page.selectOption('#rnAsks', '');
  await page.waitForFunction(() => /^Questions changed/.test(document.querySelector('.rnbar[data-rnbar="yours"] .state').textContent),
                             null, { timeout: 5000 });
  ok(true, '...and names only what changed this time');
  ok(!(await sectSave(page, 'yours', { end: true })), 'Save and end it saves');
  await page.click('#rnCancel');
  await refreshUntil(page, () => !liveSessions().has(myClaude('alpha')), { timeout: 20000 });
  ok(await page.evaluate(() => ((state?.projects || []).find(p => p.name === 'alpha')?.yours?.asks || '') === ''),
     'Save and end it saves the setting and ends the session');
  tmuxNew('claude-alpha', `${DIR}/ws/alpha`);
  await refreshUntil(page, () => liveSessions().has(myClaude('alpha')), { timeout: 20000 });
  // A change a running session reads when it is used (the build command)
  // asks nothing.
  await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])');
  const wasBuild = await page.$eval('#rnBuildCmd', e => e.value);
  await page.fill('#rnBuildCmd', wasBuild + ' && make all');
  const plain = await page.$eval('.rnbar[data-rnbar="build"]', b => !b.querySelector('[data-rnsave]').hidden && b.querySelector('[data-rnend]').hidden);
  await saveDialog(page);
  ok(plain && await page.evaluate(() => liveSessions().has(myClaude('alpha'))) && page.dialogs.length === before,
     'a change the session reads when it is used (the build command) asks nothing and ends nothing');
  await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])');
  await page.fill('#rnBuildCmd', wasBuild);
  await saveDialog(page);
  // Back to the default, so nothing after this runs against a project whose
  // sessions were left on another mode. The session goes FIRST: with nothing
  // running there is nothing to interrupt, so this save asks nothing and the
  // standing accept-everything dialog handler is not put in the way of it.
  tmuxKill('claude-alpha');
  await refreshUntil(page, () => !liveSessions().has(myClaude('alpha')),
                     { timeout: 20000 });
  await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])');
  await page.click('#rnCancel');
}

// Ghosted where no session can start. Unlike the credential fields above there
// is no typing that brings this back, so the reason is the whole message.
await pjMenu('gamma');
await page.click(`.doc .projtab [data-k="gamma"]`);
await page.waitForFunction(() => (state?.projects || [])
  .some(p => p.name === 'gamma' && p.locked), { timeout: 15000 });
await page.evaluate(() => renameProject('gamma'));
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnReply', e => e.disabled)
   && await page.$eval('#rnAsks', e => e.disabled),
   'a locked project cannot be given session settings: no session starts there to have them');
ok(/Locked/.test(await page.$eval('#rnPrefHint', e => e.textContent)),
   '...and says which of the two reasons it is');
await page.click('#rnCancel');
await pjMenu('gamma');
await page.click(`.doc .projtab [data-k="gamma"]`);
await page.waitForFunction(() => !(state?.projects || [])
  .some(p => p.name === 'gamma' && p.locked), { timeout: 15000 });
// ep.silon is linked and cannot push, which is the third state the chain has
// to have an answer for: not a form to fill in, and not an empty box either.
await pjMenu('ep.silon');
await page.click('.doc .projtab [data-l="ep.silon"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnTokenField', el => el.hidden)
   && !await page.$eval('#rnGitNone', el => el.hidden),
   '...and a read-only project is told there is nothing to set, not shown a blank field');
ok(await page.$$eval('.rnbar', bs => bs.every(b => !b.checkVisibility())),
   '...with no Save to press, since nothing there can be saved');
// Back to alpha's dialog: everything below is about the name field, and a
// collision check run against the wrong project's name proves nothing.
await page.click('#rnCancel');
await page.evaluate(() => renameProject('alpha'));
await page.waitForSelector('#rnmodal:not([hidden])');
await page.fill('#rnName', 'gamma');
ok(await page.$eval('#rnName', el => el.classList.contains('bad')),
   '...and a name already taken is marked red before you press anything');
await page.fill('#rnName', 'alpha');
ok(await page.$eval('#rnName', el => !el.classList.contains('bad')),
   '...its own name is not a collision with itself');
await page.click('#rnCancel');
ok(await page.$eval('#rnmodal', el => el.hidden), 'Cancel closes it');

// Deleting: on the full list only, and it moves rather than destroys.
ok(!await page.$('.pgrid .pcacts > [data-del]'),
   'the sidebar card has no delete: that one is brushed past on a phone');
ok(await page.$('.doc .projtab [data-del]'),
   '...and the Projects tab does');
// The thumbtack is on both since 30 Sep (the operator's ask): unpinning
// from the card it is shown in, pinning back from the tab. It went the
// delete's way once, on the crowded side of a phone's row; the phone folds
// it behind the row's more button now.
ok(await page.$('.doc .projtab [data-p]'),
   'the pin is on the card\'s rows as on the Projects tab\'s');

// Locking, which is now the only gate there is. The eye that excluded a
// project is gone: two buttons that looked alike, sat side by side and both
// ended a session was a finer distinction than it was worth.
ok(!await page.$('.doc .projtab [data-x]'),
   'there is no exclude control anywhere any more');
// delta is the fixture's locked project.
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.pgrid .pcard[data-row="delta"]', { timeout: 10000 });
const dRow = '.pgrid .pcard[data-row="delta"]';
ok(await page.$$eval(`${dRow} .pcname .lockmark`, e => e.length) === 1,
   'a locked project wears a closed padlock after its name');
ok(await page.$eval(`${dRow} [data-c]`, e => e.disabled),
   '...with its Claude button ghosted rather than taken away');
ok(await page.$(`${dRow} [data-open]`) !== null && await page.$(`${dRow} [data-s]`) !== null,
   '...and its page and shell still there, because locking is about who runs it');
// The refusal is the server's. A read-only state enforced by a dimmed button
// is a suggestion, and the endpoint behind it is reachable without the page.
const refused = await page.evaluate(async () => {
  const r = await fetch('/api/roadmap', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'delta', action: 'add', text: 'should not land' }) });
  return { status: r.status, error: (await r.json()).error || '' };
});
ok(refused.status === 409 && /locked/.test(refused.error),
   '...and the server refuses a write into its notebook, not just the button');

// The sidebar fits its column. It stopped doing so because a tooltip is laid
// out even while hidden: a 280px box centered on an icon near the right edge of
// 340px hangs past it, and the column grew a horizontal scrollbar with nothing
// visibly in the way. Invisible until it is enough to move something, which is
// why it went unnoticed until a tooltip got a longer sentence.
ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
   'the page fits its width, with no sideways scroll');
const gone = await api('/api/trash', { name: 'beta' });
ok(gone.status === 200 && gone.body.to === '.trash/beta',
   'deleting names where the files went');
ok(existsSync(`${DIR}/ws/.trash/beta`) && !existsSync(`${DIR}/ws/beta`),
   '...and they are there, moved rather than removed');
// Put it back, then delete again: the second copy is numbered, because the
// first is exactly the one somebody would be trying to recover.
execFileSync('mv', [`${DIR}/ws/.trash/beta`, `${DIR}/ws/beta`]);
execFileSync('mkdir', ['-p', `${DIR}/ws/.trash/beta`]);
const again = await api('/api/trash', { name: 'beta' });
ok(again.status === 200 && again.body.to === '.trash/beta-2',
   'a second delete of the same name is numbered, not an overwrite');
execFileSync('mv', [`${DIR}/ws/.trash/beta-2`, `${DIR}/ws/beta`]);
execFileSync('rm', ['-rf', `${DIR}/ws/.trash`]);

// ---- the theme crossfades ----------------------------------------------
// A color transition that exists only while a swap is happening. A standing
// one on every element would be the easy version and the wrong one: it would
// slow every hover and every state light on the page to make one rare action
// look nicer.
{
  // What "crossfades" means, asserted without racing the 320ms window: the
  // swap turns a color transition ON for its duration. Sampling the color
  // partway through needed the evaluate to land inside that window, which a
  // loaded box does not promise; it read as a cut on the node running the
  // suite, and reading it synchronously instead caught the value before the
  // transition had started. So: the class and the transition it brings are
  // the claim, and the color is checked once the swap has finished.
  const bg = () => page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  const was = await bg();
  const swap = await page.evaluate(() => {
    applyTheme('nostromo');
    return { during: document.documentElement.classList.contains('theming'),
             eased: getComputedStyle(document.body).transitionDuration };
  });
  ok(swap.during && /[1-9]/.test(swap.eased),
     `changing the scheme crossfades rather than cutting to it (${swap.eased} while swapping)`);
  await page.waitForFunction(() =>
    !document.documentElement.classList.contains('theming'), null, { timeout: 5000 });
  const done = await bg();
  ok(done !== was && /^0s?/.test(await page.$eval('body', b => getComputedStyle(b).transitionDuration)),
     '...and the transition is taken back off, so nothing else on the page drags');
  // Reduced motion gets the swap and none of the fade.
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.evaluate(() => applyTheme('default'));
  await page.waitForTimeout(60);
  ok(await bg() === was && !(await page.evaluate(() =>
       document.documentElement.classList.contains('theming'))),
     '...and reduced motion lands on the new scheme at once');
  await page.emulateMedia({ reducedMotion: null });
}

// ---- one field skin, everywhere ----------------------------------------
// Every text control on the page shares its ground, edge and radius from one
// rule, and a site declares only what is its own: font aside, that is the
// whole contract. A field in a context the rule does not list silently wears
// the BROWSER's default instead, which is how the log-retention box ended up
// a 2px gray square in Arial beside a page of sunk monospace fields.
{
  await page.click('#bCards');
  await page.waitForTimeout(400);
  const odd = await page.evaluate(() => {
    // Every dialog at once, so this sees the fields that live inside them.
    // What was hidden is put back hidden afterwards, ALL of it: only the
    // dialogs and the menu were, and the bell's panel stayed open over
    // the header from here on, empty and harmless until the run had two
    // more notes in it, when it covered the Settings tab's Apply button
    // and every click on it was intercepted (29 Sep).
    const shown = [...document.querySelectorAll('[hidden]')];
    shown.forEach(e => { e.hidden = false; });
    const bad = [];
    for (const el of document.querySelectorAll('input,select,textarea')){
      const t = (el.type || el.tagName).toLowerCase();
      if (t === 'checkbox' || t === 'radio' || t === 'hidden' || t === 'file') continue;
      if (!el.getBoundingClientRect().width) continue;
      const c = getComputedStyle(el);
      if (c.borderTopLeftRadius !== '6px' || c.borderTopWidth !== '1px'
          || !/mono/i.test(c.fontFamily))
        bad.push(`${el.id || el.className || t}: r=${c.borderTopLeftRadius} `
                 + `b=${c.borderTopWidth} f=${c.fontFamily.split(',')[0]}`);
    }
    shown.forEach(e => { e.hidden = true; });
    return bad;
  });
  ok(odd.length === 0, `every text field wears the one skin (${odd.join(' | ') || 'all'})`);
}

// ---- one frame, three pieces ------------------------------------------
// The tab strip, the panes and the bottom bar are drawn as one outline: the
// strip owns the top corners and its own bottom edge, the panes carry the
// sides with no top border, the bar owns the bottom corners. .col's 10px gap
// pushed them apart into three boxes with the seams showing, which is what
// this measures, and the pieces have to touch exactly.
{
  await page.evaluate(() => { const b = [...document.querySelectorAll('button')]
    .find(x => /^Terminal$/.test(x.textContent.trim())); b && b.click(); });
  // A terminal in the dock, so the foot bar under it is drawn (R218 step 4).
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'term'); if (t) dockShow(t.id); });
  await page.waitForTimeout(400);
  const seams = await page.evaluate(() => {
    const box = s => { const e = document.querySelector(s);
      if (!e) return null; const r = e.getBoundingClientRect();
      return r.height ? [r.top, r.bottom] : null; };
    const parts = ['.panes', '.keys', '.mobar']
      .map(s => [s, box(s)]).filter(p => p[1]);
    return parts.slice(1).map((p, i) => p[1][0] - parts[i][1][1]);
  });
  ok(seams.length >= 1 && seams.every(g => Math.abs(g) < 0.6),
     `the terminal frame is one outline, not three boxes (seams ${seams})`);
}

// ---- the logs, in the gear menu ---------------------------------------
// The retention policy is days, not boots: a count is the wrong unit for "was
// that this week?", and a crash loop can burn five generations in a minute.
{
  const LD = `${DIR}/state/logs`;
  execFileSync('mkdir', ['-p', LD]);
  const old = Date.now() / 1000 - 90 * 86400;
  for (const [n, age] of [['builderbot.log', 0], ['builderbot.log.1', 0],
                          ['builderbot.log.9', 90], ['docker.log', 0],
                          ['ttyd.log', 0], ['not-ours.log.4', 90]]){
    writeFileSync(`${LD}/${n}`, 'x'.repeat(64));
    if (age) utimesSync(`${LD}/${n}`, old, old);
  }
  const st = await page.evaluate(() => fetch('/api/status').then(r => r.json()));
  ok(st.logs && st.logs.days === 30,
     'the log policy defaults to thirty days, and rides on the status poll');

  const set = await api('/api/logs', { action: 'days', days: 30 });
  ok(set.body.removed >= 1 && !existsSync(`${LD}/builderbot.log.9`),
     'a generation past the policy is pruned when the policy is applied');
  ok(existsSync(`${LD}/not-ours.log.4`),
     '...and a file this container did not write is left alone, however old');
  ok(existsSync(`${LD}/builderbot.log`),
     '...as is the live one, which this session is still writing to');

  // Through the button, because that is the whole point of it: lowering the
  // number CROPS, and a number field fires `change` on its way through every
  // value the keyboard passes, so typing 30 over 300 would have pruned at 3.
  writeFileSync(`${LD}/docker.log.2`, 'x'.repeat(64));
  const week = Date.now() / 1000 - 7 * 86400;
  utimesSync(`${LD}/docker.log.2`, week, week);
  // The control graduated from the gear to the Settings tab with everything
  // controller-scoped (docs/nodes.md §13); the gear keeps this browser's
  // items and the door.
  await page.evaluate(() => toggleUiMenu(true));
  await page.waitForSelector('#uiProfile');
  ok(await page.evaluate(() => !document.querySelector('#uiMenu #logApply')),
     'the gear holds appearance and a door, not the log policy');
  // The door to the controller's settings is the Settings group on the
  // rail; the gear's door is the account's own Profile tab.
  await page.click('#uiProfile');
  await page.waitForSelector('.profiletab .setrow', { timeout: 15000 });
  ok(true, "the gear's door opens the account's Profile tab");
  await page.evaluate(() => railGo('settings', 'settings'));
  await page.waitForSelector('.settingstab #logApply');
  await page.fill('.settingstab #logDays', '3');
  await page.click('.settingstab #logApply');
  await page.waitForFunction(() => !document.querySelector('#logApply')?.disabled,
                             { timeout: 10000 });
  ok(!existsSync(`${LD}/docker.log.2`),
     'Apply crops what the new number already excludes, then and there');
  await page.fill('.settingstab #logDays', '30');
  await page.click('.settingstab #logApply');
  await page.waitForFunction(() => !document.querySelector('#logApply')?.disabled,
                             { timeout: 10000 });
  // The status answer follows the setting within a poll, not the instant
  // Apply re-enables: asked until it says so.
  await page.waitForFunction(async () => (await (await fetch('/api/status')).json()).logs?.days === 30,
                             null, { timeout: 10000, polling: 500 });
  ok(true, '...and raising it again is just a setting, with nothing to crop');
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'settings');
                              if (t) hideTab(t.id); });

  const bad = await api('/api/logs', { action: 'days', days: 'soon' });
  ok(bad.status === 400 && /number/.test(bad.body.error || ''),
     'a policy that is not a number is refused rather than defaulted');

  const cleared = await api('/api/logs', { action: 'clear' });
  ok(cleared.body.removed === 1 && !existsSync(`${LD}/builderbot.log.1`)
     && existsSync(`${LD}/builderbot.log`) && existsSync(`${LD}/not-ours.log.4`),
     'Clear takes the kept generations and nothing else');

  // Downloads are links, because a browser saves a link and this is megabytes
  // of plain text rather than something to paginate into a view.
  const dl = await page.evaluate(async () => {
    const r = await fetch('/logs/download?what=session');
    return { status: r.status, cd: r.headers.get('content-disposition'),
             body: await r.text() };
  });
  ok(dl.status === 200 && /===== builderbot\.log =====/.test(dl.body)
     && /===== docker\.log =====/.test(dl.body),
     'the session download is every stream of this boot in one file');
  ok(/attachment; filename="builderbot-session\.log"/.test(dl.cd || ''),
     '...offered as a download rather than rendered into the tab');
  ok(!/ttyd/.test(dl.body),
     '...without ttyd.log, which is 22k lines of websocket churn around it');
  const arc = await page.evaluate(async () => {
    const r = await fetch('/logs/download?what=archive');
    return { status: r.status, ct: r.headers.get('content-type'),
             len: (await r.arrayBuffer()).byteLength };
  });
  ok(arc.status === 200 && arc.ct === 'application/gzip' && arc.len > 0,
     'and the whole archive comes back as a tarball');
  // ...and the diagnostics, with what sessions reported about BuilderBot in
  // them (the operator, 24 Sep): a zip from a link beside the logs, the
  // report as diagnostics.json and each conversation a report carries as a
  // file of its own beside it (the operator, 2 Oct).
  const dg = await page.evaluate(async () => {
    const r = await fetch('/logs/download?what=diag');
    const b = new Uint8Array(await r.arrayBuffer());
    let s = ''; for (let i = 0; i < b.length; i += 8192) s += String.fromCharCode(...b.subarray(i, i + 8192));
    return { status: r.status, ct: r.headers.get('content-type'),
             cd: r.headers.get('content-disposition'), zip: btoa(s),
             // The section's own markup: the Settings tab is put away above.
             link: /<a class="btnish" href="\/logs\/download\?what=diag" download/.test(logSection()) };
  });
  const inZip = JSON.parse(execFileSync('python3', ['-c', `
import base64, io, json, sys, zipfile
z = zipfile.ZipFile(io.BytesIO(base64.b64decode(sys.stdin.read())))
print(json.dumps({"names": z.namelist(), "diag": json.loads(z.read("diagnostics.json"))}))`], { input: dg.zip, encoding: 'utf8' }));
  ok(dg.status === 200 && dg.ct === 'application/zip' && /builderbot-diagnostics-\d{8}-\d{4}\.zip/.test(dg.cd || '')
     && 'controller' in inZip.diag && Array.isArray(inZip.diag.reports) && dg.link,
     `the diagnostics download beside them as a zip, diagnostics.json with the reports in it (${dg.cd}; ${inZip.names.join(', ')})`);
}

// The command pin and the project pin are different features that spent an
// afternoon sharing four names (/api/pin, _pin, PINS_FILE and setPinned), and
// nothing went red, because pinning a command had no test at all (bug #20).
// This is that test: the two write to their own files and neither can be
// reached through the other's endpoint.
const cmdPin = await api('/api/pin', { name: 'status', pinned: true });
ok(cmdPin.status === 200 && (cmdPin.body.pinned || []).includes('status'),
   'a command can be pinned');
ok(JSON.parse(readFileSync(`${DIR}/state/pinned-commands.json`, 'utf8')).includes('status'),
   '...into pinned-commands.json, which is its own file');
ok(!Object.values(JSON.parse(readFileSync(`${DIR}/state/pinned-projects.json`, 'utf8'))).flat().includes('status'),
   '...and not into the projects one');
ok((await api('/api/pin', { name: 'alpha', pinned: true })).status === 400,
   'a project name is not a command, and the command pin says so');
ok((await api('/api/project-pin', { name: 'status', pinned: true })).status === 400,
   '...and a command name is not a project');

// ---- a project on several nodes: one chooser, a part per node (R82) --------
// The press opens a chooser with each node under its name, what it has and
// how busy it is: Resume and New conversation where this account is signed
// in, that node's sign-in where it is not, and only the reason where a
// session cannot start. A pick opens the terminal on that node, named on
// the tab and stamped with that node's boot. Planted on the row, since the
// fixture has one node.
{
  // The poll held: the rows are planted, and a poll landing between the
  // plant and the read put the server's rows back, which have one node.
  await holdPoll(page);
  const plant = (patch) => page.evaluate(p2 => {
    state.claude_auth = { nodes: { n_ubu: { email: 'tester@example.com', plan: 'max' } } };
    Object.assign(state.projects.find(x => x.name === 'alpha'), p2); drawProjects(state.projects); }, patch);
  await plant({ locked: false, session_at: 'ubu', session_node: 'n_ubu', session_why: '', held: '',
    last_claude: { id: 'abc123', when: Math.floor(Date.now() / 1000) - 7200 },
    session_nodes: [{ id: 'n_ubu', name: 'ubu', where: 'node', why: '', boot: 'b-ubu',
                      sample: { cpu_pct: 7, mem_mb: 8192, mem_used_mb: 2048 }, gpu: 'NVIDIA RTX A2000', tools: ['python'] },
                    { id: 'n_new', name: 'fresh', where: 'node', why: '', boot: 'b-new', sample: {}, gpu: '', tools: [] },
                    { id: 'n_rh', name: 'rh', where: 'refused', boot: '',
                      why: 'rh is offline. Sessions run on a node and nowhere else' }] });
  // Through the function the button calls: by this point in the file the
  // button's own state (the pins) is whatever the blocks above left, and
  // that is not what this block is about.
  // ...with no chooser already open on the row from a block above: a press
  // on a row whose chooser is open closes it, which is right, and not what
  // is under test.
  await page.evaluate(() => { resumeFor = null; openClaude('alpha'); });
  // Read in the one evaluation that waits for it: the card repaints, and a
  // read after a separate wait found the menu mid-rebuild.
  const menu = JSON.parse(await (await page.waitForFunction(() => {
    const m = document.getElementById('resumemenu');
    if (!m || m.querySelectorAll('.sub').length < 4) return null;
    return JSON.stringify({ lines: [...m.querySelectorAll('.sub')].map(e => e.textContent.replace(/\s+/g, ' ').trim()),
      buttons: [...m.querySelectorAll('button')].map(b => ({ text: b.textContent.trim(), node: b.dataset.node || b.dataset.signinNode,
        kind: b.dataset.r ? 'resume' : b.dataset.n ? 'new' : b.dataset.signinNode ? 'signin' : '?', dead: b.disabled })) });
  }, null, { timeout: 10000 })).jsonValue());
  ok(/^ubu cpu 7%/.test(menu.lines[0]) && /RTX A2000/.test(menu.lines[0]) && /^fresh · you are not signed in there$/.test(menu.lines[1])
     && /^rh$/.test(menu.lines[2]) && /rh is offline/.test(menu.lines[3]),
     `pressing Claude on a project with several nodes lists each under its name, with what it has (${menu.lines.join(' | ').slice(0, 120)})`);
  ok(menu.buttons.map(b => `${b.kind}:${b.node}`).join() === 'resume:n_ubu,new:n_ubu,signin:n_new' && menu.buttons.every(b => !b.dead)
     && /^Resume: 2 h ago$/.test(menu.buttons[0].text) && menu.buttons[2].text === 'Sign in on fresh',
     `...Resume and New conversation for the node this account is signed in on, a sign-in for the one it is not, and no press for one that cannot start a session (${
        menu.buttons.map(b => b.text).join(' | ')})`);
  // The last session here answered on Fable: the next step's Model names it
  // on "Claude's default", read from the newest transcript.
  const slug = `${DIR}/ws/alpha`.replace(/\//g, '-');
  const tdir = `${DIR}/home/.claude/projects/${slug}`;
  mkdirSync(tdir, { recursive: true });
  writeFileSync(`${tdir}/aaaaaaaa-0000-4000-8000-000000000001.jsonl`,
    '{"type":"user","message":{"role":"user","content":"hi"}}\n'
    + '{"type":"assistant","message":{"model":"claude-fable-5-1","role":"assistant","content":[]}}\n');
  await page.waitForFunction(() => { const b = document.querySelector('#resumemenu [data-n][data-node="n_ubu"]');
    if (!b) return false; b.click(); return true; }, null, { timeout: 10000 });
  // New conversation picked: the menu turns to the model and effort to start
  // on, with Start (the operator, 12 Oct), and starts nothing yet.
  await page.waitForSelector('#resumemenu #rmModel', { timeout: 10000 });
  await page.waitForFunction(() => /last session: Fable/.test(document.querySelector('#rmModel option[value=""]')?.textContent || ''),
                             null, { timeout: 8000 });
  const step = await page.$eval('#resumemenu', m => ({ text: m.querySelector('.sub').textContent.trim(),
    models: [...m.querySelectorAll('#rmModel option')].map(o => o.value), efforts: [...m.querySelectorAll('#rmEffort option')].map(o => o.value),
    buttons: [...m.querySelectorAll('button')].map(b => b.textContent.trim()) }));
  ok(/^A new conversation on ubu$/.test(step.text) && step.models.includes('opus') && step.models.includes('fable')
     && step.efforts.includes('high') && step.buttons.join() === 'Back,Start'
     && !(await page.evaluate(() => tabs.some(t => t.kind === 'term' && String(t.arg) === 'claude:alpha:n:n_ubu'))),
     `...New conversation turns the menu to Model and Effort with Start, naming the last session's model on the default, and starts nothing yet (${step.text}; ${step.buttons.join(' | ')})`);
  // A poll redraws the card: the step and what was picked stay.
  await page.selectOption('#rmModel', 'sonnet');
  await page.selectOption('#rmEffort', 'high');
  await page.evaluate(() => refresh());
  await page.waitForTimeout(600);
  ok(await page.$eval('#rmModel', e => e.value) === 'sonnet' && await page.$eval('#rmEffort', e => e.value) === 'high',
     '...and a poll redrawing the card keeps the step and the picks');
  await page.click('#resumemenu [data-start]');
  await page.waitForFunction(() => tabs.some(t => t.kind === 'term' && String(t.arg) === 'claude:alpha:n:n_ubu'), null, { timeout: 10000 });
  await refreshUntil(page, () => { const y = (state?.projects || []).find(p => p.name === 'alpha')?.yours || {};
    return y.model === 'sonnet' && y.effort === 'high'; }, { timeout: 20000 });
  ok(true, '...and Start saves them as this account\'s for the project, which the launcher reads, and opens the session');
  await (await fetch(URL.replace(/\/$/, '') + '/api/prefs', { method: 'POST',
    headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', model: '', effort: '' }) })).json();
  rmSync(tdir, { recursive: true, force: true });
  // The row planted again in the same evaluation as the read: a poll that
  // was already on its way when the hold went on lands whenever it lands.
  const tab = await page.evaluate(() => {
    const t = tabs.find(t => t.kind === 'term' && String(t.arg) === 'claude:alpha:n:n_ubu');
    const p = state.projects.find(x => x.name === 'alpha');
    p.session_nodes = [{ id: 'n_ubu', name: 'ubu', where: 'node', why: '', boot: 'b-ubu' }, { id: 'n_rh', name: 'rh', where: 'refused', boot: '' }];
    return { label: t.label, url: ttydUrl(t.arg) }; });
  ok(tab.label === 'Claude: alpha (ubu)' && /%3Ab%3Ab-ubu/.test(tab.url),
     `...and a pick opens the terminal on that node, named on the tab and stamped with that node's boot (${tab.label}; ${tab.url})`);
  // With this account's session running on one node, the press opens the
  // same chooser rather than jumping to the tab: Open tab and End session
  // for that node, and the other nodes still offered beside it.
  const live = JSON.parse(await (await page.waitForFunction(() => {
    state.projects.find(x => x.name === 'alpha').session_nodes = [
      { id: 'n_ubu', name: 'ubu', where: 'node', why: '', boot: 'b-ubu' },
      { id: 'n_new', name: 'fresh', where: 'node', why: '', boot: 'b-new' }];
    state.sessions = [...(state.sessions || []).filter(s => s.name !== myClaude('alpha')),
                      { name: myClaude('alpha'), node_id: 'n_ubu', attached: false }];
    resumeFor = null; openClaude('alpha');
    const m = document.getElementById('resumemenu');
    if (!m || !m.querySelector('[data-end]')) return null;
    return JSON.stringify({ lines: [...m.querySelectorAll('.sub')].map(e => e.textContent.replace(/\s+/g, ' ').trim()),
      buttons: [...m.querySelectorAll('button')].map(b => `${b.textContent.trim()}:${b.dataset.node || b.dataset.restart || b.dataset.end || b.dataset.signinNode || ''}`) });
  }, null, { timeout: 10000 })).jsonValue());
  ok(/your session is running here/.test(live.lines[0]) && live.buttons.join() === 'Open tab:n_ubu,Restart:n_ubu,End session:n_ubu,Sign in on fresh:n_new',
     `with a session running on one node the press opens the chooser: Open tab, Restart and End session there, the other nodes still offered (${live.buttons.join(' | ')})`);
  const ended = await page.evaluate(async () => {
    const real = endSession; let asked = null;
    window.endSession = async (name, node) => { asked = { name, node }; return { ok: true }; };
    const before = tabs.length;
    document.querySelector('#resumemenu [data-end]').click();
    await new Promise(r => setTimeout(r, 300));
    window.endSession = real;
    return { asked, dropped: before - tabs.length, open: !!document.getElementById('resumemenu'),
             tab: tabs.some(t => String(t.arg) === 'claude:alpha:n:n_ubu') };
  });
  ok(/End your Claude session on alpha on ubu\?/.test(page.dialogs.at(-1) || '') && ended.asked?.node === 'n_ubu'
     && ended.asked?.name === await page.evaluate(() => myClaude('alpha')) && ended.dropped === 1 && !ended.tab && !ended.open,
     `End session asks first, ends that node's session and drops its tab (${JSON.stringify(ended)})`);
  // Restart (the operator, 12 Oct): the model and effort first, then the
  // question, and only then the session ended and started again. Asked
  // first and ended at once, it left a person picking a model with no
  // session running, and a start racing the end needed a second press.
  {
    await page.waitForFunction(() => {
      state.projects.find(x => x.name === 'alpha').session_nodes = [
        { id: 'n_ubu', name: 'ubu', where: 'node', why: '', boot: 'b-ubu' }];
      state.sessions = [...(state.sessions || []).filter(s => s.name !== myClaude('alpha')),
                        { name: myClaude('alpha'), node_id: 'n_ubu', attached: false }];
      resumeFor = null; resumePick = null; openClaude('alpha');
      return !!document.querySelector('#resumemenu [data-restart]');
    }, null, { timeout: 10000 });
    const d0 = page.dialogs.length;
    const first = await page.evaluate(async () => {
      window.bbRestartLog = [];
      window.realEnd = endSession; window.realStart = startClaude;
      window.endSession = async (name, node) => {
        bbRestartLog.push(['end', node]);
        state.sessions = (state.sessions || []).filter(s => s.name !== name);
        return { ok: true };
      };
      window.startClaude = (name, sid, node) => { bbRestartLog.push(['start', node]); resumePick = null; resumeFor = null; };
      document.querySelector('#resumemenu [data-restart]').click();
      await new Promise(r => setTimeout(r, 300));
      const go = document.querySelector('#resumemenu [data-start]');
      return { label: go?.textContent.trim(), danger: !!go?.classList.contains('danger'),
               model: !!document.querySelector('#rmModel'), log: [...bbRestartLog] };
    });
    ok(page.dialogs.length === d0 && first.label === 'Restart' && first.danger && first.model && first.log.length === 0,
       `Restart turns the menu to the model and effort first, asking nothing and ending nothing yet (${JSON.stringify(first)})`);
    const done = await page.evaluate(async () => {
      document.querySelector('#resumemenu [data-start]').click();
      for (let i = 0; i < 50 && !bbRestartLog.some(x => x[0] === 'start'); i++) await new Promise(r => setTimeout(r, 100));
      window.endSession = realEnd; window.startClaude = realStart;
      return bbRestartLog;
    });
    ok(/Restart your Claude session on alpha on ubu\?/.test(page.dialogs.at(-1) || '') && page.dialogs.length === d0 + 1
       && JSON.stringify(done) === JSON.stringify([['end', 'n_ubu'], ['start', '']]),
       `...then its Restart asks, ends the session and only then starts it again (${JSON.stringify(done)})`);
  }
  // A project on one node: its chooser names that node with what it has,
  // as each of several gets.
  const one = await page.evaluate(() => {
    const p = state.projects.find(x => x.name === 'alpha');
    Object.assign(p, { session_nodes: [{ id: 'n_ubu', name: 'ubu', where: 'node', why: '', boot: 'b-ubu',
      sample: { cpu_pct: 7, mem_mb: 8192, mem_used_mb: 2048 }, gpu: 'NVIDIA RTX A2000', tools: [] }] });
    resumeFor = 'alpha'; drawProjects(state.projects);
    return [...(document.getElementById('resumemenu')?.querySelectorAll('.sub') || [])].map(e => e.textContent.trim());
  });
  ok(/^ubu cpu 7%/.test(one[0] || '') && /RTX A2000/.test(one[0] || ''),
     `a project on one node gets that node's name and what it has in its chooser too (${one.join(' | ')})`);
  // Who is in a session on a project: one line per account per node, the
  // node in brackets, each with its own working or waiting dot.
  const who = await page.evaluate(() => {
    resumeFor = null;
    state.claude_with = { alpha: ['test', 'w.peer'] };
    state.claude_where = { alpha: [{ who: 'test', node: 'ubu', working: true }, { who: 'test', node: 'fresh', working: false },
                                   { who: 'w.peer', node: 'ubu', working: false }] };
    return [...new DOMParser().parseFromString(`<div>${sessionRows('alpha')}</div>`, 'text/html').querySelectorAll('.sessone')]
      .map(e => `${e.querySelector('.st').classList.contains('working') ? '*' : '-'}${e.textContent.trim()}`);
  });
  ok(who.join(' | ') === '-w.peer (ubu) | -test (you) (fresh) | *test (you) (ubu)',
     `a person with a session on two nodes is two lines, each naming its node and whether it is working there (${who.join(' | ')})`);
  await page.evaluate(() => { tabs = tabs.filter(t => !(t.kind === 'term' && String(t.arg).includes(':n:')));
    state.claude_where = {};
    state.sessions = (state.sessions || []).filter(s => s.name !== myClaude('alpha')); drawPanes(); });
  await freePoll(page);
  page.errors = [];
}
// ---- a dialog that scrolls says so, and opens at its top -------------------
// On a short screen the project's settings dialog is taller than the room:
// its title and its buttons stay put with their hairlines while what is
// between them scrolls (the operator, 16 Oct: no black fades), it still
// knows which edge has more (the classes a list's hairline follows); and
// closed and opened again it is back at its top, however far down it was
// (the operator, 30 Sep).
{
  await page.setViewportSize({ width: 420, height: 560 });
  const box = '#rnmodal > .box';
  const cls = () => page.$eval(box, b => ({ up: b.classList.contains('scrollup'), down: b.classList.contains('scrolldown'),
    top: b.scrollTop, room: b.scrollHeight - b.clientHeight, shadow: getComputedStyle(b).boxShadow,
    pinned: ['h3', '.foot'].map(q => getComputedStyle(b.querySelector(':scope > ' + q)).position).join() }));
  await page.evaluate(() => renameProject('alpha'));
  await page.waitForFunction(s => document.querySelector(s)?.classList.contains('scrolldown'), box, { timeout: 10000 });
  const a = await cls();
  ok(a.room > 50 && a.down && !a.up && a.top === 0 && a.pinned === 'sticky,sticky' && !/inset/.test(a.shadow),
     `a dialog taller than the screen opens at its top, its title and buttons pinned and nothing shaded (${JSON.stringify({ ...a, shadow: a.shadow.slice(0, 40) })})`);
  // ...and a list inside it that scrolls, the project's Reads, says so the
  // same way, on its own edges.
  await page.waitForFunction(() => document.getElementById('rnReads')?.classList.contains('scrolldown'), null, { timeout: 10000 });
  const reads = await page.$eval('#rnReads', l => ({ down: l.classList.contains('scrolldown'), up: l.classList.contains('scrollup'),
    room: l.scrollHeight - l.clientHeight, shadow: getComputedStyle(l).boxShadow }));
  await page.$eval('#rnReads', l => { l.scrollTop = l.scrollHeight; l.dispatchEvent(new Event('scroll')); });
  const readsEnd = await page.$eval('#rnReads', l => [l.classList.contains('scrollup'), l.classList.contains('scrolldown')]);
  ok(reads.room > 0 && reads.down && !reads.up && /inset/.test(reads.shadow) && readsEnd[0] && !readsEnd[1],
     `a list that scrolls, the project's Reads, draws a hairline on the edge with more past it, and the other at its end (${JSON.stringify({ ...reads, shadow: reads.shadow.slice(0, 30), end: readsEnd })})`);
  // To the end once the dialog has stopped growing (B741, B749): its
  // sections fill in after it opens (the Claude section's content is a
  // thousand pixels that land late), so a wait that succeeded at the first
  // height was read after the rest had arrived, with more below. Its height
  // held still across three polls first; then to the end and kept there,
  // the classes following on the next frame.
  await page.waitForFunction(sel => { const l = document.querySelector(sel);
    if (!l) return false;
    const h = l.scrollHeight, w = (window.__rnH = window.__rnH || []);
    w.push(h); if (w.length > 3) w.shift();
    return w.length === 3 && w.every(x => x === h); }, box, { timeout: 15000, polling: 250 }).catch(() => {});
  await page.waitForFunction(sel => { const l = document.querySelector(sel);
    if (!l) return false;
    l.scrollTop = l.scrollHeight; l.dispatchEvent(new Event('scroll'));
    return l.classList.contains('scrollup') && !l.classList.contains('scrolldown'); }, box, { timeout: 5000, polling: 200 }).catch(() => {});
  const b = await cls();
  ok(b.up && !b.down, `...scrolled to its end, it knows the top edge has more and the bottom none (${JSON.stringify({ up: b.up, down: b.down, top: b.top, room: b.room })})`);
  await page.evaluate(() => closeRename());
  await page.waitForFunction(() => document.getElementById('rnmodal').hasAttribute('hidden'), null, { timeout: 5000 });
  await page.evaluate(() => renameProject('alpha'));
  await page.waitForFunction(s => document.querySelector(s)?.classList.contains('scrolldown'), box, { timeout: 10000 });
  await page.waitForTimeout(200);
  const c = await cls();
  ok(c.top === 0 && !c.up, `...and opened again it is back at its top, not where it was left (${c.top})`);
  await page.evaluate(() => closeRename());
  await page.setViewportSize({ width: 1280, height: 900 });
}
await done(browser);
