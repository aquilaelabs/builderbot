// Sidebar cards: universal collapse with a height tween, header-only
// controls, drag-to-reorder, ▤ reset, doctor's inner fold vs the card fold,
// per-project findings, valid-projects filter, and server-side persistence.
import { launch, newPage, ok, done, ready, doctorFixture, animatedDuring, refreshUntil,
         holdPoll, freePoll, tmuxNew, tmuxKill, tmuxFmt, URL, DIR } from './lib.mjs';
import { writeFileSync, readFileSync, existsSync, rmSync, utimesSync,
         mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);
const order = () => page.$$eval('.side .card[data-card]', els => els.map(e => e.dataset.card));

// headers are title + chevron only; doctor sits first
// A card whose body repaints WHILE it folds. contentIn starts at opacity 0
// and lasts 180ms, the same as the fold, so an entrance animation landing on
// a collapsing card blanked its body at full height and faded it back in as
// the card shut — the flicker seen on Runner and Projects, the two cards
// whose bodies redraw from the poll and so the two a fold can collide with.
{
  const trace = await page.evaluate(async () => {
    const el = document.querySelector('.card[data-card="runner"]');
    const body = el.querySelector('#runner');
    const out = [];
    const sample = () => out.push({
      h: el.offsetHeight,
      op: Number(getComputedStyle(body).opacity).toFixed(2),
      shown: getComputedStyle(body).display,
    });
    // The real order: a poll repaints the body, and the click lands inside
    // the 180ms the entrance animation takes.
    painted.delete(body);            // make the next paint an ARRIVING one
    paint(body, '<div class="row"><span class="pill ok">running a job</span></div>');
    await new Promise(r => requestAnimationFrame(r));
    sample();
    el.querySelector('h2').click();
    for (let i = 0; i < 13; i++){
      await new Promise(r => requestAnimationFrame(r));
      sample();
    }
    return out;
  });
  const mid = trace.slice(1, -2);
  ok(mid.every(f => f.op === '1.00'),
     'a repaint while a card folds does not blank its body — the fold is the motion that matters');
  ok(trace[0].h > trace[trace.length - 1].h
     && mid.some(f => f.shown === 'block' && f.h < trace[0].h && f.h > trace[trace.length - 1].h),
     '...and the body stays visible while the height comes down, rather than after it');
  // Put it back: the tests below this one drag this card and read its folded
  // state, and a card left shut by a probe is a probe changing their subject.
  await page.click('.card[data-card="runner"] h2');
  await page.waitForFunction(() => {
    const c = document.querySelector('.card[data-card="runner"]');
    return !c.classList.contains('closed') && !c.getAnimations().length;
  }, null, { timeout: 8000 });
}

// The nostromo theme's stencil tick is an inset shadow on the card header, and
// an inset shadow is drawn to its own box: square against the card's 8px
// corner, it left a few pixels of amber outside the rounded edge. A notch on a
// still card, and a glitch while one folded — which is when the eye is there.
{
  await page.evaluate(() => document.documentElement.dataset.theme = 'nostromo');
  await page.waitForFunction(() => getComputedStyle(
    document.querySelector('.card[data-card="doctor"] h2')).boxShadow !== 'none',
    null, { timeout: 8000 });
  const radii = await page.evaluate(() => {
    const card = document.querySelector('.card[data-card="doctor"]');
    const h2 = card.querySelector('h2');
    return {open: getComputedStyle(h2).borderTopLeftRadius,
            card: getComputedStyle(card).borderTopLeftRadius};
  });
  // Closed is read after the fold, not after the click: slideCard takes .closed
  // OFF for the tween and puts it back at the end, which is what keeps the body
  // visible on the way down.
  await page.click('.card[data-card="doctor"] h2');
  await page.waitForFunction(() => {
    const c = document.querySelector('.card[data-card="doctor"]');
    return c.classList.contains('closed') && !c.getAnimations().length;
  }, null, { timeout: 8000 });
  radii.shut = await page.$eval('.card[data-card="doctor"] h2',
                                h => getComputedStyle(h).borderBottomLeftRadius);
  ok(parseFloat(radii.open) > 0 && parseFloat(radii.open) < parseFloat(radii.card),
     'the card header rounds its own corner to sit inside the card\'s, so the '
     + 'stencil tick cannot poke out past it');
  ok(parseFloat(radii.shut) > 0,
     '...and rounds the bottom too once the header IS the card, which is what closed means');
  await page.evaluate(() => {
    document.querySelector('.card[data-card="doctor"] h2').click();
    delete document.documentElement.dataset.theme;
  });
  await page.waitForFunction(() => {
    const c = document.querySelector('.card[data-card="doctor"]');
    return !c.classList.contains('closed') && !c.getAnimations().length;
  }, null, { timeout: 8000 });
}

// The header fits, at every width a phone comes in. It did not: measured at
// 320px it wanted 369px and overflowed by 57, and the uptime — the only item
// there that shrinks, because .meta clips — was squeezed away on the way,
// rendering "up 09:52:…", which is not a truncated number but a different one.
//
// Both halves are asserted, because they fail separately: a header that does
// not overflow can still contain something ellipsised, and that is what the
// operator saw.
{
  const sizes = [320, 360, 390, 412, 430, 768];
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
  ok(over.length === 0,
     `the header fits at every phone width${
       over.length ? ` — over by ${over.map(m => `${m.over}px at ${m.w}`).join(', ')}` : ''}`);
  ok(cut.length === 0,
     `...with nothing inside it ellipsised${
       cut.length ? ` — ${cut.map(m => `${m.clipped.join('/')} at ${m.w}`).join(', ')}` : ''}`);
}

const hs = await page.$$eval('.side .card[data-card] h2', hs => hs.map(h => ({
  buttons: h.querySelectorAll('button').length, chev: !!h.querySelector('.chev') })));
ok(hs.length === 5 && hs.every(h => h.buttons === 0 && h.chev),
   `headers are title + chevron only (${hs.length} cards)`);
ok((await order())[0] === 'doctor', 'doctor is first by default');
ok(await page.$eval('#bDocTog', el => el.textContent.trim() === 'all 3 ok'), 'doctor status row folded green');

// collapse animates, persists across reload
const collapsed = await animatedDuring(page,
  () => page.click('.card[data-card="tools"] h2'));
ok(collapsed.some(k => k.includes('tools'))
   && !await page.$eval('.card[data-card="tools"]', el => el.classList.contains('closed')),
   'collapse runs a height tween before the class lands');
await page.waitForFunction(() => document.querySelector('.card[data-card="tools"]').classList.contains('closed'));
await page.reload(); await ready(page);
ok(await page.$eval('.card[data-card="tools"]', el => el.classList.contains('closed')), 'collapsed state survives a reload');

// doctor: card collapse is the operator's; the verdict only drives the inner detail
await page.click('.card[data-card="doctor"] h2');
await page.waitForFunction(() => document.querySelector('.card[data-card="doctor"]').classList.contains('closed'));
doctorFixture('fail');
await page.evaluate(() => document.getElementById('bDoctor').onclick());
await page.waitForFunction(() => document.getElementById('docDot').className.includes('bad'));
ok(await page.$eval('.card[data-card="doctor"]', el => el.classList.contains('closed')), 'a FAIL leaves a collapsed doctor card collapsed');
ok(await page.$eval('#doctor', el => !el.hidden), '...but opens the detail behind it');
ok(await page.$eval('#docBar', el => getComputedStyle(el).display === 'none'), 'collapsed card hides the status row too');
doctorFixture('ok');
await page.evaluate(() => document.getElementById('bDoctor').onclick());
await page.waitForFunction(() => document.getElementById('docDot').className.includes('ok'));

// projects: fold-away toggle at the foot; slides the card. It counts one kind
// now — it used to have to split the number, because half of what it hid was
// excluded, which was a decision rather than a fault. Only faults are folded.
ok(await page.$eval('#projects #bAll', el => el.textContent.trim()) === 'Show Error (2)',
   'the toggle says how many are folded away, and they are all faults');
ok((await animatedDuring(page, () => page.click('#projects #bAll')))
     .some(k => k.includes('projects')),
   'in-card toggle slides the card');
await page.click('#projects #bAll');

// The Analysis tab: the findings, browsable. The sidebar card is gone — its
// rows were only doors into each notebook, a summary nothing could be read
// through — and the server logic it exercised (valid-project attribution,
// stale-report exclusion, the named aside) is asserted here against the tab
// that replaced it.
ok(await page.$('#cardFindings') === null,
   'the findings card is gone from the sidebar');
// The Tools card may be folded by the collapse tests above; the button is
// in its body, and a click cannot land on display:none.
await page.evaluate(() => {
  const c = document.querySelector('.card[data-card="tools"]');
  if (c.classList.contains('closed')) c.querySelector('h2').click();
});
await page.waitForFunction(() => {
  const b = document.getElementById('bFindings');
  return b && b.offsetParent !== null;
}, { timeout: 10000 });
await page.click('#bFindings');
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

// Narrowing. One project, one level, a search — each redraws the list, and
// the counts on the options are the whole report's, so choosing is informed.
await page.selectOption('.fxtab #fxProject', 'alpha');
await page.waitForFunction(() => !document.querySelector('.fxtab .fxproj'),
                           { timeout: 10000 });
ok(true, 'picking a project drops the per-project headings — the picker already says it');
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
// so. A scanner that dies leaves its previous report in place — the host
// script does not overwrite a good report with nothing — so without this a
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
   'a stale copy of the same report adds nothing — it is not read at all');
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
// left edges — the filter bar flush against the edge (its padding rule named
// an id the markup never had), the rules at 11px, the headings and the footer
// at 14 — which is what a retyped inset looks like from a phone.
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
// Nothing readable in /reports and the way in goes quiet — three ways to have
// nothing (no mount, nothing in it, nothing that parses) and one greyed button
// carrying the reason. A tab already open on it is closed once, when the page
// first learns: a layout restored from last session can carry an Analysis tab
// for a scanner that has since been unmounted, and one that stays only to say
// "nothing here" is a tab somebody has to close by hand.
{
  const keep = readFileSync(`${DIR}/reports/test.sarif`);
  rmSync(`${DIR}/reports`, { recursive: true, force: true });
  await refreshUntil(page, () => state?.reports_ok === false, { timeout: 20000 });
  ok(await page.$eval('#bFindings', b => b.disabled),
     'with no readable report the Static analysis button is ghosted');
  ok(/no \/reports mount/.test(await page.$eval('#bFindings', b => b.title)),
     '...carrying which of the three reasons it is');
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
  ok(/nothing readable/.test(await page.$eval('#bFindings', b => b.title)),
     'a report that does not parse is not a report — the button says so');
  rmSync(`${DIR}/reports/broken.sarif`, { force: true });
  writeFileSync(`${DIR}/reports/test.sarif`, keep);
  await refreshUntil(page, () => state?.reports_ok === true, { timeout: 20000 });
  ok(await page.$eval('#bFindings', b => !b.disabled),
     '...and a readable one lights it again');
  await page.click('#bFindings');
  await page.waitForSelector('.fxtab #fxProject', { timeout: 15000 });
}
// Two projects whose names shorten to one slug are one dev instance — the same
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
// ---- a phone folds the rest of a row behind one icon -----------------------
// Three icons beside the name, the rest on demand: a row was 140px against 98
// on a desktop and a third of it was six buttons. What this pins is the
// FOLDING OUT, which shipped broken — the rule that hides the extra icons
// carries three :not()s and outranked the rule that showed them again, so
// pressing … re-stacked the row and produced nothing (the operator found it
// on their phone, which is the only place it renders).
{
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(400);
  const row = '#projects .row:has(.name:text-is("alpha"))';
  const shown = () => page.$$eval(`${row} .acts .eye`,
    bs => bs.filter(b => b.offsetParent !== null).length);
  const folded = await shown();
  ok(folded === 3, `a phone row shows the session, the notebook and the fold (${folded})`);
  await page.click(`${row} [data-more]`);
  await page.waitForTimeout(250);
  const open = await shown();
  ok(open > folded, `...and pressing it shows the rest (${folded} -> ${open})`);
  ok(await page.$eval(`${row} [data-more]`, b => b.getAttribute('aria-expanded') === 'true'),
     '...saying so, for anything that is not looking at the pixels');
  await page.click(`${row} [data-more]`);
  await page.waitForTimeout(250);
  ok(await shown() === folded, '...and pressing it again folds them away');
  await page.setViewportSize({ width: 1280, height: 1000 });
  await page.waitForTimeout(400);
  const desk = await shown();
  ok(desk > 3 && await page.$eval(`${row} [data-more]`, b => b.offsetParent === null),
     `on a desktop every icon is there and the fold is not (${desk} icons)`);
}

// ---- the row's session line: who is here, or why nobody can be -------------
// Never WHICH MACHINE. That is on the project's settings, it is the same for
// every session on the project, and a row that said it spent a line on
// something nobody was asking. What the row owes instead is a red line when
// the Claude button is dead and the project is not locked, since a ghosted
// button with no reason is the thing somebody stares at.
//
// Planted rather than arranged: the fixture has no node, and the four refusals
// worth drawing (offline, no session half, no share, read-only share) are
// nodes.mjs's to produce. This is about what the ROW does with one.
{
  await holdPoll(page);
  const line = () => page.$eval('#projects .row:has(.name:text-is("alpha"))',
    r => (r.querySelector('.sessline')?.textContent || '').trim());
  // WHO is here wins the line, and the fixture has a session open on alpha —
  // so the half being tested here only ever draws with nobody in it. Put back
  // at the end rather than left cleared: the next block reads this fixture.
  const were = await page.evaluate(() => {
    const had = state.claude_with; state.claude_with = {}; return had; });
  const plant = (patch) => page.evaluate(p2 => {
    Object.assign(state.projects.find(x => x.name === 'alpha'), p2);
    drawProjects(state.projects);
  }, patch);
  await plant({ session_at: 'shed', session_why: '', locked: false });
  ok(await line() === '', 'a project whose node takes sessions says nothing about which machine');
  await plant({ session_at: 'shed', locked: false,
                session_why: "alpha's sessions run on shed, which is offline. Sessions run on a "
                           + 'node and nowhere else — this container carries no Claude Code — so '
                           + 'the way on is that machine coming back, or another node in the '
                           + "project's settings." });
  ok(/offline/.test(await line()),
     `a node that cannot take one puts the reason on the row (${await line()})`);
  ok((await line()).split(' ').length <= 14 && !/Sessions run on a node and nowhere else/.test(await line()),
     '...the first clause of it, not the paragraph — the rest is on the button');
  ok(await page.$eval('#projects .row:has(.name:text-is("alpha")) .sessline',
                      e => e.classList.contains('bad')),
     '...in red, because a dead button with no reason is what somebody stares at');
  ok(await page.$eval('#projects .row:has(.name:text-is("alpha")) [data-c]',
       b => /nowhere else/.test(b.dataset.tip || b.title || '')),
     '...and the whole of it, fix included, is on the ghosted button — a tap on a phone, since these rows are tipified');
  // A no-node project is the same answer: it was silent before, which left
  // the operator looking at a ghosted button with nothing anywhere saying why.
  await plant({ session_at: '', locked: false,
                session_why: 'alpha has no node, and a Claude session runs on one. Pick one '
                           + "in the project's settings, or enroll one on the Nodes tab" });
  ok(/has no node/.test(await line()) && !/pick one/.test(await line()),
     `a project with no node says so too, without the instruction (${await line()})`);
  // ...and LOCKED is the one case where no session is the point rather than a
  // fault, so it stays quiet.
  await plant({ locked: true });
  ok(await line() === '', 'a locked project says nothing: no session there is the decision, not a fault');
  await plant({ locked: false, session_at: '', session_why: '' });
  await page.evaluate(w => { state.claude_with = w; drawProjects(state.projects); }, were);
  await freePoll(page);
}

await page.evaluate(() => { const t = tabs.find(x => x.kind === 'findings');
                            if (t) hideTab(t.id); });

// Which shares count as "not a project" no longer comes only from what sits
// inside /workspace. That worked while /workspace was the whole development
// share; pointing it at the projects folder took the package store outside it and
// sent 267 findings about downloaded toolchains to the label meant for a path
// that is genuinely wrong. The rule asks the mount table instead.
//
// Sliced out of server.py rather than imported: server.py is written to be
// run, not imported — it configures modules and seeds state at import — and
// the case that must not regress cannot be produced by mounting something on
// this box.
const sibOut = execFileSync('python3', ['-c', `
import posixpath, re, json
src = open(${JSON.stringify(new globalThis.URL('../server.py', import.meta.url).pathname)}).read()
i = src.index('def siblings_of('); j = src.index('def nonproject_dirs(')
ns = {'posixpath': posixpath}
exec(src[i:j], ns)
mi = """
26 25 0:24 /development/projects /workspace rw - fuse.shfs x rw
27 25 0:24 /development/SDK /sdk rw - fuse.shfs x rw
28 25 0:25 /appdata/BuilderBot /config rw - xfs x rw
29 25 0:26 / /reports ro - xfs x ro
"""
print(json.dumps(sorted(ns['siblings_of'](mi, '/workspace'))))
`], { encoding: 'utf8' });
const sib = JSON.parse(sibOut.trim().split('\n').pop());
ok(sib.includes('SDK'),
   'a share mounted beside the projects folder is known to be one');
ok(!sib.includes('BuilderBot'),
   '...while a mount from somewhere else is not, even named after a project');
ok(!sib.includes('reports') && sib.length === 1,
   '...and a whole-filesystem mount names no directory, so it says nothing');

// .bbignore hides a directory from the card entirely — not listed, not
// counted, not folded away under the Excluded/Error toggle either.
const names = await page.$$eval('#projects .name', ns => ns.map(n => n.textContent.trim()));
ok(!names.includes('toolstore'), 'a directory carrying .bbignore is not a project');
await page.click('#projects #bAll');
const all = await page.$$eval('#projects .name', ns => ns.map(n => n.textContent.trim()));
await page.click('#projects #bAll');
ok(!all.includes('toolstore'), '...not even with the error rows shown');
// An unmarked directory IS still listed, as a project with an error — that is
// the card doing its job, and how you find out something in the share is not a
// repository. What changed is that its findings no longer count as anybody's.
ok(all.includes('vendored-junk'),
   '...while one with no marker is listed, as the error it is');

// drag: reorder + slide + persistence; the click ending a drag is not a toggle
// Into view first: bounding boxes are viewport coordinates, and a section
// above this one may leave the sidebar scrolled — a drag aimed at y=-282
// grabs nothing and the test reads as the FEATURE failing.
await page.$eval('.side', e => e.scrollTo(0, 0));
await new Promise(r => setTimeout(r, 150));
const hb = await (await page.$('.card[data-card="runner"] h2')).boundingBox();
const top = await (await page.$('.side .card[data-card]')).boundingBox();
// Recorded, not sampled. The FLIP tween is 140ms, and asking for it in a
// round trip AFTER the drag only works if that round trip happens to land
// inside those 140ms — true on an idle box, false on a loaded one, which is
// the test timing the browser rather than the behaviour. Wrapping
// Element.animate says whether the displaced card WAS animated, whenever
// that was. Undone straight after, so nothing later in this file is
// measuring through a patched prototype.
await page.evaluate(() => {
  window.__flipped = [];
  window.__realAnimate = Element.prototype.animate;
  Element.prototype.animate = function(...a){
    window.__flipped.push(this.dataset?.card || "");
    return window.__realAnimate.apply(this, a);
  };
});
await page.mouse.move(hb.x + 40, hb.y + 12); await page.mouse.down();
await page.mouse.move(hb.x + 40, top.y + 2, { steps: 10 });
await page.mouse.up();
const sliding = await page.evaluate(() => {
  Element.prototype.animate = window.__realAnimate;
  return window.__flipped.includes("doctor");
});
ok(sliding, 'displaced cards slide during a drag');
ok((await order())[0] === 'runner', `runner dragged to the top (${(await order()).join(',')})`);
ok(!(await page.$eval('.card[data-card="runner"]', el => el.classList.contains('closed'))), 'the drop did not toggle the card');
await page.reload(); await ready(page);
ok((await order())[0] === 'runner', 'order survives a reload');

// ▤ reset, now an item in the menu the gear opens rather than theom's
// own action. The menu is the other half: twelve colour schemes, each swatch
// rendered in the scheme it selects.
await page.click('#bCards');
await page.waitForSelector('#uiMenu:not([hidden])');
ok(await page.$$eval('#uiMenu .sw', s => s.length) === 12,
   'the gear opens a menu of twelve schemes');
ok(await page.$eval('#uiMenu .sw[data-theme="default"]', b => b.classList.contains('on')),
   '...with the one in use marked, which is Default until something says otherwise');
// A swatch is the palette itself at 1cm — the stylesheet defines each scheme
// for .sw[data-theme] as well as for the page — so this reads the computed
// colour rather than trusting that two lists match.
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
// Nostromo's flare is drawn, not fetched — no image files in a repo whose
// image is rebuilt weekly. The header's decal is the visible half.
ok(await page.evaluate(() => {
     const st = getComputedStyle(document.querySelector('header'), '::after');
     return /repeating-linear-gradient/.test(st.backgroundImage);
   }), '...and Nostromo brings its hazard stripe with it, as a gradient');
// The notebook's scanlines sit on the pane's scrolling box, not on the tall
// content inside it (bug #57): a gradient rasterized across a long roadmap's
// whole scroll height is what Firefox for Android was painting as yellow
// striped tiles. One viewport of gradient, on the box that stays put.
await page.evaluate(() => openNotebook(state.projects[0].name));
await page.waitForSelector('.pane .doc > .nb');
const scan = await page.evaluate(() => {
  const nb = document.querySelector('.pane .doc > .nb');
  const g = e => /repeating-linear-gradient/.test(getComputedStyle(e).backgroundImage);
  return { box: g(nb.parentElement), content: g(nb) };
});
ok(scan.box && !scan.content,
   `...and the notebook's scanlines are on the pane's box, not across the scroll height (${JSON.stringify(scan)})`);
// A surface that stops following the scheme does it silently — the text
// fields, the memory folds and the pane's title bar all sat in the default
// scheme's blue-grey through the first twelve because their colour was typed
// in rather than named. A field is the cheapest one to keep honest.
// The notebook's add field, open just above: the sidebar has no text field now that the phone is a tab.
const fieldBg = () => page.$eval('.pane .nb #todoText', e => getComputedStyle(e).backgroundColor);
const nosField = await fieldBg();

await page.click('#uiMenu .sw[data-theme="default"]');
ok(await fieldBg() !== nosField,
   '...and a text field is painted from the scheme, not from a hardcoded hex');
ok(await page.evaluate(() => document.documentElement.dataset.theme) === undefined,
   'Default carries no attribute at all, so :root is simply left to stand');

// Escape shuts it, like the bell panel it sits beside.
await page.keyboard.press('Escape');
await page.waitForFunction(() => document.getElementById('uiMenu').hidden,
                           null, { timeout: 5000 });
ok(true, 'Escape closes the menu');

await page.click('#bCards');
await page.waitForSelector('#uiMenu:not([hidden])');
await page.click('#uiReset');
await page.waitForFunction(() => document.querySelector('.side .card[data-card]').dataset.card === 'doctor'
  && !document.querySelector('.side .card.closed'));
ok(true, 'reset restores default order and expands everything');

// The whole-report tab came back, on purpose and different: the retired one
// was an unfiltered dump, and the Analysis tab is the findings browsable —
// a project picker, a level filter, a search. What this asserts now is that
// reset did not conjure one open: it is opened from Tools, not by default.
ok(await page.evaluate(() => !tabs.some(t => t.kind === 'findings')),
   'the Analysis tab is opened from Tools, not open by default');

// The favicon set: served by the allow-list, linked from the head. Sizes and
// content types matter — a wrong type is a globe in the tab, silently.
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
// The detail lives in the About popup now — a phone cannot hover a tooltip,
// and the truncated string it showed instead answered nothing.
await page.click('#bAbout');
await page.waitForSelector('#aboutModal:not([hidden])');
const about = await page.$eval('#aboutModal', e => e.textContent);
ok(about.includes('abc1234def5678901234567890abcdef12345678')
   && about.includes('2026-08-21T19:30Z') && /bb drift/.test(about),
   '...and About carries the whole commit, the build time and where to look');
await page.click('#aboutModal >> text=Close');
await page.waitForSelector('#aboutModal', { state: 'hidden' });
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
     'an account that has not read the guide gets the panel on sign-in, open on the guide — the administrator\'s, for an owner');
  await page.click('.abswitch [data-ab="log"]');
  // Whatever the top section is: Unreleased while entries are accumulating,
  // a dated number the moment somebody bumps. Asserted on the SHAPE — a
  // heading and at least one line under it — rather than on the wording of
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
  // the file behind it grows for the life of the project — the first bump
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

  // A release the size of the first bump — everything ever logged, dated in
  // one move — is capped with a press to see the rest (B95). Not the section
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
// a gap that reads as "this dashboard is too old to tell you" — in the label
// and in the popup both.
ok(await page.evaluate(() => { drawBuild({ rev: '', built: '' });
                               return document.getElementById('build')
                                        .textContent === 'unstamped'
                                 && /built outside CI/.test(
                                      document.getElementById('aRev').textContent); }),
   'an unstamped image says so, rather than showing nothing');
await page.evaluate(() => refresh());

// ---- signing in and out ------------------------------------------------
// The first thing to get right on a new box, and the last place anybody would
// think to look for it on a command line. Driven against a stub claude: the
// real one would sign this container out for good.
await page.waitForSelector('#docAuth:not([hidden])', { timeout: 25000 });
ok((await page.$eval('#docAuth', e => e.textContent)).includes('tester@example.com'),
   'the doctor card says who this container is signed in as');
ok(await page.$('#bSignOut') !== null && await page.$('#bSignIn') === null,
   '...and offers the way out, not the way in');

// Not while a conversation is running: signing out pulls the ground from
// under every session on the box. The fixture has one.
ok(await page.$eval('#bSignOut', b => b.disabled)
   && (await page.$eval('#bSignOut', b => b.title)).includes('claude-alpha'),
   'signing out is dead while a Claude session is running, and says which');
const blocked = await page.evaluate(async () => {
  const r = await fetch('/api/signout', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: '{}' });
  return r.status;
});
ok(blocked === 409,
   '...and the server refuses it too, because a page can be fifteen seconds stale');
page.errors = [];

tmuxKill('claude-alpha');
await page.evaluate(() => refresh());
await page.waitForFunction(() => !document.getElementById('bSignOut')?.disabled,
                           { timeout: 25000 });
ok(true, 'with the last one ended, it comes alive');

// Signed out. The card reads the RECORD now, not `claude auth status`: the
// controller holds no credential and has no Claude to ask (R47), so what
// "signed in" means here is that some node reports being signed in.
const claudeRecord = (d) => writeFileSync(`${DIR}/home/.claude/.bb-grant.json`,
  JSON.stringify(d));
claudeRecord({ gen: 2, email: '', plan: '', nodes: {} });
// Kept asking rather than asked once: the verdict is cached for 20s and the
// page polls every 15, which together outlast any patience worth calling a
// timeout. See refreshUntil.
await refreshUntil(page, () => document.getElementById('bSignIn') !== null);
ok(await page.$('#bSignOut') === null
   && (await page.$eval('#docAuth', e => e.textContent)).includes('not signed in'),
   'signed out, it says so where the verdict is and offers the way in');
// ...and nothing offers to start a conversation that cannot start.
ok(await page.$$eval('#projects [data-c]', bs => bs.length > 0 && bs.every(b => b.disabled)),
   '...and every project\'s Claude button goes with it');

// And back. There is no credential here to take away: a machine signs in for
// itself and keeps the grant it alone refreshes (R47). Signed in, to this
// card, means SOME NODE reports being signed in — and signing out moves a
// generation, which is the only thing that can reach a node that is not
// listening, because being signed out has no date to compare.
mkdirSync(`${DIR}/home/.claude`, { recursive: true });
claudeRecord({ gen: 4, email: 'you@example.com', plan: 'max',
               nodes: { n_fixture: { email: 'you@example.com', at: 1 } } });
await refreshUntil(page, () => document.getElementById('bSignOut') !== null);
ok((await page.$eval('#docAuth', e => e.textContent)).includes('you@example.com'),
   'the card names the Anthropic account a node reports being signed in as');
page.dialogs = [];
await page.click('#bSignOut');
await page.waitForFunction(() => document.getElementById('bSignIn') !== null,
                           { timeout: 25000 });
ok(page.dialogs.some(d => /signs out every node that holds/.test(d)),
   'signing out says it reaches every node holding the login, not just this box');
const mark = JSON.parse(readFileSync(`${DIR}/home/.claude/.bb-grant.json`, 'utf8'));
ok(mark.gen === 5 && !Object.keys(mark.nodes || {}).length && !mark.email,
   '...moving the generation, clearing the nodes, and releasing the Anthropic account');
ok(!existsSync(`${DIR}/home/.claude/.credentials.json`),
   '...with no credential on the controller at any point, because none is kept here');
claudeRecord({ gen: 6, email: 'tester@example.com', plan: 'max',
               nodes: { n_fixture: { email: 'tester@example.com', at: 1 } } });

// ---- the sign-in runs where Claude IS, which is a node ------------------
// Claude Code is installed for the account that runs sessions, and that is a
// node — so the flow goes there as a job of its own, under a pty on that
// machine, and the grant it makes stays there (R47). The card does not know
// which of the two it is driving: same link, same code field.
{
  const nodeSignin = await page.evaluate(async () => {
    const r = await fetch('/api/signin', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' });
    return { status: r.status, ...(await r.json()) };
  });
  ok(nodeSignin.ok && nodeSignin.job && nodeSignin.on,
     `with a node running sessions, the sign-in is queued there and says which (${
       nodeSignin.on || nodeSignin.error || '?'})`);
  const queued = await page.evaluate(async (id) =>
    (await (await fetch('/api/v1/jobs?id=' + id)).json()), nodeSignin.job);
  ok((queued.job || queued).type === 'claude-login',
     '...as a claude-login job, which is the one job that opens a pty');
  await page.evaluate(async () => { await fetch('/api/signin', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'cancel' }) }); });
}

// ---- ...and nowhere, when no node is running sessions -------------------
// There is no fallback: this container carries no Claude Code, so a sign-in
// has no machine to run on and says so. The local pty flow that used to live
// here went with the binary (R47); what the card does with a flow — the
// link, the code field, the focus across polls — is driven in agent.mjs now,
// where a node's job log can actually be posted to.
await page.evaluate(async () => {
  const ns = (await (await fetch('/api/v1/nodes')).json()).nodes || [];
  for (const n of ns.filter(x => x.kind === 'agent'))
    await fetch('/api/v1/nodes', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'drain', id: n.id }) });
});
{
  const nowhere = await page.evaluate(async () => {
    const r = await fetch('/api/signin', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' });
    return { status: r.status, ...(await r.json()) };
  });
  ok(nowhere.status === 400 && /no node is running sessions/.test(nowhere.error || ''),
     `with no node running sessions there is nowhere to sign in, and it says so (${
       (nowhere.error || '').slice(0, 56)})`);
  // ...and the BUTTON says it, which is the half that was missing: the press
  // used to fire and forget, so a refusal left it reading "Starting…" for
  // ever with nothing on screen. The card repaints only when its html
  // changes and a refusal changes none of it, so the button is put back by
  // the press itself.
  await refreshUntil(page, () => document.getElementById('bSignIn') !== null);
  await page.click('#bSignIn');
  await page.waitForFunction(() => /no node is running sessions/.test(
    document.getElementById('toast')?.textContent || ''), null, { timeout: 15000 });
  ok(true, '...and pressing Sign in says the refusal rather than swallowing it');
  ok(await page.$eval('#bSignIn', b => !b.disabled && b.textContent === 'Sign in'),
     '...with the button live again, not left saying Starting…');
  // That refusal is a 400 by design and the browser logs every one as a
  // failed resource. Cleared, so the check below is about the page.
  page.errors = [];
}

// ---- the runner card -------------------------------------------------------
// A view of the NODES' runners and nothing else: this container ran a runner
// of its own until CI moved to nodes (docs/nodes.md phase 7), and the card
// used to lead with that one's moods. Drawn directly, because each state
// needs a node to be in a particular one.
const runnerCard = rows => page.evaluate(x => {
  const keep = state.node_runners; state.node_runners = x;
  drawRunner();
  const out = { body: document.getElementById('runner').textContent,
                pills: [...document.querySelectorAll('#runner .sub')].map(e => e.className) };
  state.node_runners = keep;
  return out;
}, rows);

let rc = await runnerCard([]);
ok(/no runner on any node/.test(rc.body) && /Nodes tab installs one/.test(rc.body),
   'with no runner anywhere the card says so, and where one is installed');
rc = await runnerCard([{ node: 'bb-sandbox', live: true, installed: true,
  listening: true, busy: false, labels: ['bb-sandbox'] }]);
ok(/bb-sandbox/.test(rc.body) && /listening, idle/.test(rc.body)
   && /runs-on: \[self-hosted, bb-sandbox\]/.test(rc.body),
   'a listening node runner leads with the node\'s name, which is the label a workflow uses');
rc = await runnerCard([{ node: 'bb-sandbox', live: false, installed: true,
  listening: true, busy: false, labels: [] }]);
ok(/quiet/.test(rc.body) && rc.pills.some(c => /warn/.test(c)),
   '...and a runner on a node nobody has heard from lately is amber, not green');
ok(await page.$('#runner [data-m]') === null,
   'the card carries no Start/Stop of its own — those are the Nodes tab\'s');
await page.evaluate(() => refresh());

// The padlock: a project the operator keeps and runs themselves. Its whole
// point is being the OTHER button — excluding hides a row, this one leaves it
// intact and takes away only the session, so that is what gets asserted.
await page.evaluate(() => refresh());
await page.waitForSelector('#projects [data-k="alpha"]', { timeout: 10000 });
ok(await page.$$eval('#projects [data-k]', bs => bs.length > 0),
   'every project row carries a padlock');
await page.evaluate(() => setLocked('alpha', true));
await page.waitForFunction(
  () => document.querySelector('#projects [data-c="alpha"]')?.disabled === true,
  { timeout: 10000 });
const locked = await page.$eval('#projects .row:has([data-k="alpha"])', r => ({
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
    () => !!document.querySelector('#projects .row:has([data-k="alpha"]) .lockmark'),
    { timeout: 15000 });
  const note = await page.$eval('#projects .row:has([data-k="alpha"])',
    r => r.textContent.replace(/\s+/g, ' '));
  ok(!/read-only/.test(note) && !/no Claude session/.test(note),
     '...marked with the padlock alone, not a sentence under the name as well');
await page.evaluate(() => setLocked('alpha', false));
// Unlocking is what is under test, so it is the LOCK that has to stop being
// the reason. The button stays dead here for a different one — alpha has no
// node in this fixture and a Claude session runs on one — and that is the
// row saying one thing at a time rather than two.
await page.waitForFunction(
  () => !document.querySelector('#projects .row:has([data-k="alpha"]) .lockmark')
        && !/locked/.test(document.querySelector('#projects [data-c="alpha"]')?.title || ''),
  { timeout: 15000 });
// Not the disabled state: this fixture has a live claude-alpha session, and
// a button that would take you to a running conversation stays usable
// whatever the node arrangement says.
// title OR data-tip: tipify() moves the native one onto the element as a
// data-tip on this surface, so reading only `title` reads nothing.
const backTitle = await page.$eval('#projects [data-c="alpha"]',
                                   b => b.title || b.dataset.tip || '');
ok(!/locked/.test(backTitle) && /no node/.test(backTitle),
   `unlocking gives the row back, and what is left to say is the node it has not got (${
      backTitle.slice(0, 60)})`);

// The Projects tab: every project, pinned or not, and the same controls on
// each. The thumbtack decides only where a project is met, not what it can do.
await page.click('#projects #bAllProj');
await page.waitForSelector('.doc .projtab .row', { timeout: 15000 });
const inTab = await page.$$eval('.doc .projtab .row .name', ns => ns.map(n => n.textContent.trim()));
const inCard = await page.$$eval('#projects .row .name', ns => ns.map(n => n.textContent.trim()));
ok(inTab.length >= inCard.length && inCard.every(n => inTab.includes(n)),
   'the Projects tab lists at least what the card does');
ok(await page.$eval('.doc .projtab .row', r =>
     !!r.querySelector('[data-m]') && !!r.querySelector('[data-s]')
     && !!r.querySelector('[data-k]') && !!r.querySelector('[data-p]')),
   '...with the same buttons on a row: notebook, shell, padlock, thumbtack');

// Unpinning takes a project off the sidebar and leaves it on the tab, whole.
await page.evaluate(() => setProjectPinned('alpha', false));
await page.waitForFunction(
  () => ![...document.querySelectorAll('#projects .row .name')]
          .some(n => n.textContent.trim() === 'alpha'), { timeout: 15000 });
ok(await page.$$eval('.doc .projtab .row .name',
     ns => ns.some(n => n.textContent.trim() === 'alpha')),
   'an unpinned project leaves the sidebar and stays on the tab');
ok(await page.$eval('.doc .projtab .row:has([data-p="alpha"])',
     r => !!r.querySelector('[data-c]') && !!r.querySelector('[data-m]')),
   '...still carrying every control, which is the whole promise of the pin');
// The tab is a document, not a card adrift in one. It used to draw itself
// inside .card — rounded, bordered, floating on a darker gutter — while the
// notebook in the pane beside it filled the pane. One language.
ok(await page.$eval('.doc .projtab', e => !e.classList.contains('card'))
   && await page.$eval('.doc:has(.projtab)', e => e.classList.contains('flush')),
   'the Projects tab fills its pane the way the notebook does');
await page.evaluate(() => setProjectPinned('alpha', true));
await page.waitForFunction(
  () => [...document.querySelectorAll('#projects .row .name')]
          .some(n => n.textContent.trim() === 'alpha'), { timeout: 15000 });
ok(true, 'pinning it puts it back on the sidebar');

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
     `...and the asking is remembered, not dropped — one more goes when it lands (${
        held - before} in ${Date.now() - t0}ms)`);
  await page.unroute('**/api/status*');
}

// ---- a row's tooltips -----------------------------------------------------
// Two failures that were the same failure, and both were reported as "the
// tooltip gets buried". A tip in a sidebar row is measured against the ROW,
// because 340px of column cannot hold a 280px box centred on anything in it.
{
  // The checkout's template, which is what the server compares against —
  // run.sh points TEMPLATE_MD at it.
  const tpl = readFileSync(new globalThis.URL('../../../config/templates/project-CLAUDE.md',
                                   import.meta.url), 'utf8');
  // From another WINDOW, not merely behind: only that ghosts the button
  // whose tip is measured below — drift inside the window leaves it live.
  writeFileSync(`${DIR}/ws/beta/CLAUDE.md`,
    tpl.replace(/BUILDERBOT:ENV:WINDOW \d+\.\d+ -->/, 'BUILDERBOT:ENV:WINDOW 0.1 -->'));
  await refreshUntil(page, () => ((state.projects || []).find(p => p.name === 'beta')
    ?.issues || []).some(i => i.action === 'claude-md-update'));
  const row = '#projects .row[data-row="beta"]';
  // The issue line is a LINK, and a link that wraps is an inline box whose
  // line boxes are what a centred tip gets measured against — so this one was
  // centred on nothing in particular and slid off the left of the card with
  // its first characters cut off.
  await page.hover(`${row} [data-fix]`);
  const fit = await page.evaluate(sel => {
    const a = document.querySelector(sel + ' [data-fix]');
    const s = getComputedStyle(a, '::after');
    // The content width plus what the box adds — 8px of padding either side
    // and a 1px border — against the row inset 10px either side, which is
    // where the rule puts it.
    return { box: parseFloat(s.width) + 18,
             row: document.querySelector(sel).getBoundingClientRect().width };
  }, row);
  ok(Math.abs(fit.box - (fit.row - 20)) < 2,
     `a row's tooltip is as wide as its row, so nothing can push it off the card (${
       fit.box} in ${fit.row})`);
  // ...and under the LINK, not under the row: with the row as the tip's
  // containing block, the link's tip and the icons' landed in one place.
  const where = await page.evaluate(sel => {
    const a = document.querySelector(sel + ' [data-fix]');
    const row = document.querySelector(sel);
    return { top: parseFloat(getComputedStyle(a, '::after').top),
             want: a.getBoundingClientRect().bottom - row.getBoundingClientRect().top + 6,
             rowH: row.getBoundingClientRect().height };
  }, row);
  ok(Math.abs(where.top - where.want) < 2 && where.top < where.rowH,
     `...and sits under the link it explains, not under the row (${Math.round(where.top)} of ${Math.round(where.rowH)})`);
  // ...and the tip on a DEAD control, which is the one somebody has to read,
  // because it is the sentence saying why the control is dead. The fade on a
  // disabled button is opacity, and opacity below 1 makes a stacking context
  // that traps the button's own ::after inside it — half strength, painted
  // under the next row, that row's text straight through it.
  const btn = `${row} [data-c]`;
  await page.hover(btn);
  // Waited for rather than read at once: the swap from the opacity fade to
  // the colour one rides the same 150ms transition every other button state
  // does, and reading it on the first frame reads the fade it is leaving.
  await page.waitForFunction(sel => getComputedStyle(
    document.querySelector(sel)).opacity === '1', btn, { timeout: 5000 });
  const dead = await page.$eval(btn, b => ({ off: b.disabled,
    op: getComputedStyle(b).opacity,
    tip: b.dataset.tip || '' }));
  ok(dead.off && /compatibility window/.test(dead.tip) && dead.op === '1',
     `a ghosted button reading out its reason is not a layer of its own (${
       dead.op}, ${dead.tip.slice(0, 46)}…)`);
  // Put back: the fixture tree outlives this file, and a project left held
  // here would be held — its sessions ended, its row red in the bell — in
  // every file after it.
  // beta had no CLAUDE.md at fixture time: put back is remove.
  rmSync(`${DIR}/ws/beta/CLAUDE.md`, { force: true });
  await refreshUntil(page, () => !(state.projects || []).find(p => p.name === 'beta')?.held);
}

// The nodes come back: a drained node is this file's doing, not the
// fixture's, and the suites after it expect one that takes work.
await page.evaluate(async () => {
  const ns = (await (await fetch('/api/v1/nodes')).json()).nodes || [];
  for (const n of ns.filter(x => x.kind === 'agent' && x.state === 'draining'))
    await fetch('/api/v1/nodes', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'online', id: n.id }) });
});
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);

// Unpinning from the sidebar has to move the Projects TAB too: they render
// the same rows from the same state, and a tab that drew once showed a lit
// thumbtack for a project that was no longer pinned — then clicking it sent
// the state it was already in, which is what "pinning only works sometimes"
// was. No poll is waited for: the answer to the pin request is the new set.
await page.click('#projects #bAllProj');
await page.waitForSelector('.doc .projtab .row', { timeout: 15000 });
const tackLit = () => page.$eval('.doc .projtab [data-p="beta"]',
                                 b => b.classList.contains('on'));
ok(await tackLit(), 'the Projects tab shows beta pinned');
await page.evaluate(() => setProjectPinned('beta', false));
await page.waitForFunction(() =>
  !document.querySelector('.doc .projtab [data-p="beta"]')?.classList.contains('on'),
  { timeout: 5000 });
ok(true, '...and unpinning it there unlights the tab\'s thumbtack too');
ok(!await page.$$eval('#projects .row .name',
     ns => ns.some(n => n.textContent.trim() === 'beta')),
   '...with the sidebar dropping it in the same breath');
await page.evaluate(() => setProjectPinned('beta', true));
await page.waitForFunction(() =>
  document.querySelector('.doc .projtab [data-p="beta"]')?.classList.contains('on'),
  { timeout: 5000 });
ok(true, '...and pinning it back lights it again, first click');
// A project whose name has a dot in it: the row's own selector has to survive
// one, or the change lands without its animation and nothing says why.
await page.evaluate(() => setProjectPinned('ep.silon', false));
await page.waitForFunction(() =>
  ![...document.querySelectorAll('#projects .row .name')]
    .some(n => n.textContent.trim() === 'ep.silon'), { timeout: 8000 });
ok(true, 'a dotted project name unpins too, animation and all');
// ...and back, which is the direction that used to be a plain redraw: pinning
// is watched from the Projects tab, which on a desktop sits in the column
// beside the sidebar, so the row has to unroll rather than shove the projects
// under it down between two frames. The tween is caught while it runs — the
// row exists before it, so waiting for the row alone would prove nothing.
// Watched at the call rather than caught mid-flight: the tween is 170ms,
// and a poll that evaluates in the page over CDP can take longer than that
// on a loaded box — this passed on the controller and failed three times
// out of four on bb-sandbox with the row rendered, motion allowed and no
// stub in the way. What is asserted is the same: the row was tweened rather
// than snapped in.
await page.evaluate(() => {
  window.__rowAnims = [];
  const real = Element.prototype.animate;
  window.__pinAnimate = real;
  Element.prototype.animate = function(...a){
    if (this.matches && this.matches('.row[data-row="ep.silon"]')) window.__rowAnims.push(a[1]?.duration);
    return real.apply(this, a);
  };
});
await page.evaluate(() => setProjectPinned('ep.silon', true));
await page.waitForFunction(() => window.__rowAnims.length > 0, { timeout: 8000 });
await page.evaluate(() => { Element.prototype.animate = window.__pinAnimate; });
ok(true, '...and pinning it back unrolls the row instead of snapping it in');
await page.waitForFunction(() =>
  [...document.querySelectorAll('#projects .row .name')]
    .some(n => n.textContent.trim() === 'ep.silon'), { timeout: 8000 });

// The docker manager opens from Tools. What it LISTS is asserted in
// devapp.mjs, where a project actually has a compose file and an instance —
// here there are none, so the only honest assertion is that the tab opens and
// shows the daemon's own containers.
await page.click('#bDocker');
await page.waitForSelector('.dmtab', { timeout: 15000 });
ok(await page.$$eval('.dmtab .row', rs =>
     rs.some(r => /someone-elses/.test(r.textContent) && r.classList.contains('off'))),
   'the manager shows a container this dashboard did not start, marked not ours');
await page.click('#projects #bAllProj');
await page.waitForSelector('.doc .projtab .row', { timeout: 15000 });

const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [path, body]);

// Renaming is a dialog now, not a prompt. One dialog, two doors: the gear is
// the project's own settings and the chain is GitHub's half of them, so where
// a credential is changed does not depend on whether a remote exists yet.
await page.click('.doc .projtab [data-rn="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnName', el => el.value) === 'alpha',
   'the rename dialog opens on the current name');
ok(await page.evaluate(() => document.activeElement?.tagName) !== 'INPUT',
   '...with the keyboard down, like every other dialog here');
ok(await page.$eval('#rnTokenField', el => el.hidden)
   && await page.$eval('#rnAuthField', el => el.hidden),
   '...and holds no credential: the gear is the project, the chain is its remote');
await page.click('#rnCancel');

// The chain, on a project that already has one. alpha can push — the
// retroactive seeding granted it, on the deploy key its remote uses — so it
// is offered a token, and told what setting one does and does not do.
await page.click('.doc .projtab [data-l="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(/GitHub/.test(await page.$eval('#rnTitle', e => e.textContent))
   && await page.$eval('#rnNameField', el => el.hidden)
   && await page.$eval('#rnPrefField', el => el.hidden),
   'the chain opens the same dialog on the remote alone, with the rest put away');
ok(!await page.$eval('#rnTokenField', el => el.hidden),
   'a project pushing with a deploy key is offered a token');
const kh = await page.$eval('#rnTokenHint', e => e.textContent);
ok(/deploy key/.test(kh) && /does nothing until the switch below/.test(kh),
   '...told in a line that setting one does not switch anything by itself');
// The switch that makes it take effect. alpha's remote is ssh and it has no
// token, so the choice is real but one-sided until a token exists — and the
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
ok(/stay where they are|stays stored/.test(await page.$eval('#rnAuthHint', e => e.textContent)),
   '...promising in words that switching removes neither');
await page.fill('#rnToken', '');
// Clearing, which is the other half of a stored token: it cannot be shown and
// must not be typed over blind, so the field is closed and this is the way in.
await page.click('#rnCancel');
await page.evaluate(() => renameProject('alpha', 'git'));
await page.waitForSelector('#rnAuthField:not([hidden])', { timeout: 8000 });
ok(await page.$eval('#rnTokenClear', b => b.hidden),
   'a project with no token stored is offered nothing to clear');

// The remaining states need a project holding both credentials, which no
// fixture here does — so the answer the dialog was given is set directly and
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
// goes invalid, and Save refuses — being corrected without being asked is how
// you end up on a credential you did not choose.
await page.click('#rnTokenClear');
v = await seen();
ok(v.onToken && v.token,
   'clearing the token leaves the pick where it was, and ghosts it');
ok(v.bad && /no token to use/.test(v.hint),
   '...saying in red that there will be nothing to authenticate with');
await page.click('#rnGo');
await page.waitForSelector('#rnErrWrap:not([hidden])', { timeout: 8000 });
ok(/no access token after this save/.test(await page.$eval('#rnErr', e => e.textContent)),
   '...and Save refuses rather than writing a remote with no credential');
// Disabled is the third answer, and always takeable: it is the absence of a
// credential rather than the presence of one.
ok(!await page.$eval('#rnAuthNone', b => b.disabled),
   'Disabled is always offered — turning pushing off is a real answer');
await page.click('#rnAuthNone');
v = await seen();
ok(v.onNone && !v.bad,
   '...and picking it settles the dialog, because nothing is missing any more');

// What Claude runs on here, back through the gear. Per project, and applied
// when a session starts rather than typed into a running one — so the dialog's
// job is to say which of those two you are doing.
await page.click('#rnCancel');
await page.click('.doc .projtab [data-rn="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnTitle', e => e.textContent.trim()) === 'alpha',
   'the dialog is the project\'s settings, not a rename form wearing its name');
ok(await page.$eval('#rnGo', e => e.textContent.trim()) === 'Save',
   '...so its button saves rather than renames');
await page.selectOption('#rnModel', 'sonnet');
ok(!await page.$eval('#rnModel', e => e.disabled)
   && /next time Claude starts/.test(await page.$eval('#rnPrefHint', e => e.textContent)),
   'with no session running it simply applies at the next start');
await page.click('#rnCancel');

// Saving and interrupting are two decisions, and only one of them is asked
// about. Declining the restart used to return before anything was written, so
// somebody who wanted the setting kept and their conversation left alone got
// neither — and restarting the session by hand afterwards changed nothing,
// because there was nothing stored to read (B88).
{
  tmuxNew('claude-alpha', `${DIR}/ws/alpha`);
  await refreshUntil(page, () => liveSessions().has(myClaude('alpha')),
                     { timeout: 20000 });
  await page.click('.doc .projtab [data-rn="alpha"]');
  await page.waitForSelector('#rnmodal:not([hidden])');
  await page.selectOption('#rnEdits', 'accept');
  // The harness accepts every dialog; this one has to be refused, which is
  // the whole case. Put the standing handler back afterwards.
  const auto = page.listeners('dialog')[0];
  page.off('dialog', auto);
  let asked = '';
  page.once('dialog', d => { asked = d.message(); page.dialogs.push(asked); d.dismiss(); });
  await page.click('#rnGo');
  await page.waitForFunction(() => document.getElementById('rnmodal').hidden,
                             { timeout: 15000 });
  page.on('dialog', auto);
  ok(/Cancel saves the setting/.test(asked),
     'a running session is asked about, and the question says Cancel still saves');
  await refreshUntil(page, () => (state?.projects || [])
    .find(p => p.name === 'alpha')?.prefs?.edits === 'accept', { timeout: 20000 });
  ok(true, '...and declining the restart still saves the setting');
  ok(await page.evaluate(() => liveSessions().has(myClaude('alpha'))),
     '...while the session it declined to restart is still running');
  // Back to the default, so nothing after this runs against a project whose
  // sessions were left on another mode. The session goes FIRST: with nothing
  // running there is nothing to interrupt, so this save asks nothing and the
  // standing accept-everything dialog handler is not put in the way of it.
  tmuxKill('claude-alpha');
  await refreshUntil(page, () => !liveSessions().has(myClaude('alpha')),
                     { timeout: 20000 });
  await page.click('.doc .projtab [data-rn="alpha"]');
  await page.waitForSelector('#rnmodal:not([hidden])');
  await page.selectOption('#rnEdits', 'ask');
  await page.click('#rnGo');
  await page.waitForFunction(() => document.getElementById('rnmodal').hidden,
                             { timeout: 15000 });
  // `|| 'ask'` because a record back at every default is REMOVED rather than
  // stored — the file says only what somebody chose — so the row carries no
  // edits key at all, which every reader of it defaults the same way.
  await refreshUntil(page, () => ((state?.projects || [])
    .find(p => p.name === 'alpha')?.prefs?.edits || 'ask') === 'ask',
    { timeout: 20000 });
}

// Ghosted where no session can start. Unlike the credential fields above there
// is no typing that brings this back, so the reason is the whole message.
await page.click(`.doc .projtab [data-k="gamma"]`);
await page.waitForFunction(() => (state?.projects || [])
  .some(p => p.name === 'gamma' && p.locked), { timeout: 15000 });
await page.evaluate(() => renameProject('gamma'));
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnModel', e => e.disabled)
   && await page.$eval('#rnEffort', e => e.disabled),
   'a locked project cannot be given a model — no session starts there to have one');
ok(/Locked/.test(await page.$eval('#rnPrefHint', e => e.textContent)),
   '...and says which of the two reasons it is');
await page.click('#rnCancel');
await page.click(`.doc .projtab [data-k="gamma"]`);
await page.waitForFunction(() => !(state?.projects || [])
  .some(p => p.name === 'gamma' && p.locked), { timeout: 15000 });
// ep.silon is linked and cannot push, which is the third state the chain has
// to have an answer for: not a form to fill in, and not an empty box either.
await page.click('.doc .projtab [data-l="ep.silon"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnTokenField', el => el.hidden)
   && !await page.$eval('#rnGitNone', el => el.hidden),
   '...and a read-only project is told there is nothing to set, not shown a blank field');
ok(await page.$eval('#rnGo', el => el.hidden),
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
ok(!await page.$('#projects [data-del]'),
   'the sidebar card has no delete — that one is brushed past on a phone');
ok(await page.$('.doc .projtab [data-del]'),
   '...and the Projects tab does');
// The thumbtack went the same way. The card IS the pinned view, so a control
// on it that takes a row off it is a button whose only effect is to remove
// the thing you pressed — and the row it lived on is now one control shorter
// on the crowded side.
ok(!await page.$('#projects [data-p]') && await page.$('.doc .projtab [data-p]'),
   'pinning is the Projects tab\'s, not the card the pins are shown in');

// Locking, which is now the only gate there is. The eye that excluded a
// project is gone: two buttons that looked alike, sat side by side and both
// ended a session was a finer distinction than it was worth.
ok(!await page.$('#projects [data-x]') && !await page.$('.doc .projtab [data-x]'),
   'there is no exclude control anywhere any more');
// delta is the fixture's locked project.
const dRow = '#projects .row[data-row="delta"]';
ok(await page.$$eval(`${dRow} .name .lockmark`, e => e.length) === 1,
   'a locked project wears a closed padlock after its name');
ok(await page.$eval(`${dRow} [data-c]`, e => e.disabled),
   '...with its Claude button ghosted rather than taken away');
ok(await page.$(`${dRow} [data-m]`) !== null && await page.$(`${dRow} [data-s]`) !== null,
   '...and its notebook and shell still there, because locking is about who runs it');
// The refusal is the server's. A read-only state enforced by a dimmed button
// is a suggestion, and the endpoint behind it is reachable without the page.
const refused = await page.evaluate(async () => {
  const r = await fetch('/api/todo', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'delta', action: 'add', text: 'should not land' }) });
  return { status: r.status, error: (await r.json()).error || '' };
});
ok(refused.status === 409 && /locked/.test(refused.error),
   '...and the server refuses a write into its notebook, not just the button');
const mdRefused = await page.evaluate(async () => {
  const r = await fetch('/api/claude-md', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'delta', action: 'init' }) });
  return r.status;
});
ok(mdRefused === 409, '...including writing a CLAUDE.md into it');

// The sidebar fits its column. It stopped doing so because a tooltip is laid
// out even while hidden: a 280px box centred on an icon near the right edge of
// 340px hangs past it, and the column grew a horizontal scrollbar with nothing
// visibly in the way. Invisible until it is enough to move something, which is
// why it went unnoticed until a tooltip got a longer sentence.
ok(await page.evaluate(() => {
     const s = document.querySelector('.col.side');
     return s.scrollWidth <= s.clientWidth;
   }), 'the sidebar fits its column, with no sideways scroll');
// ...and still fits while a tip is actually up, which is the case that made
// the first fix incomplete: display:none stopped the resting overflow and left
// the hovered one.
// The last VISIBLE one: the row's last child is the fold control now, which
// is display:none at this width, and hovering something hidden waits forever.
const lastTip = page.locator('#projects .row .acts [data-tip]:visible').last();
await lastTip.hover();
await page.waitForTimeout(250);
ok(await lastTip.evaluate(e => getComputedStyle(e, '::after').display) === 'block',
   '...while a tooltip still appears on hover');
ok(await page.evaluate(() => {
     const s = document.querySelector('.col.side');
     return s.scrollWidth <= s.clientWidth;
   }), '...and the sidebar still fits with that tooltip open');

// ...and not while it is pressed. Every button dips a pixel on :active, and a
// transform makes the element the containing block for its own absolutely
// positioned ::after — so a sidebar tip measured against the ROW suddenly
// measures against a 32px button, wraps to one character per line and runs
// down the whole card. Reported as "something crazy with the tooltips".
const tipBtn = '#projects .row .acts [data-tip]';
const tipBox = await page.$(tipBtn);
const tb = await tipBox.boundingBox();
await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2);
await page.mouse.down();
await page.waitForTimeout(300);
const pressed = await page.$eval(tipBtn, e => getComputedStyle(e, '::after').display);
await page.mouse.up();
ok(pressed === 'none',
   '...and goes away while the button is held, where a transform would mis-measure it');
// ...and STAYS away with the pointer still on it. `:active` ends at the
// release and `:hover` does not, so the tip used to come straight back and sit
// over the next control down — the Resume button, in this strip. You have read
// the label and acted on it; it has nothing left to tell you.
const after = [];
for (let i = 0; i < 4; i++){
  await page.waitForTimeout(30);
  after.push(await page.$eval(tipBtn, e => getComputedStyle(e, '::after').display));
}
ok(after.every(d => d === 'none'),
   `...and stays away once clicked, rather than covering what is under it (${after.join(', ')})`);
// Cleared by reaching a different control, not by a timer: this is one button's
// label being finished with, not tooltips being switched off. Its size is the
// other half — the press TRANSITIONS back over 100ms, and while a transform was
// what dipped the button it went on being the containing block for its own
// ::after after :active stopped matching, so the next tip opened one character
// wide and ran down the whole card. Reported as "something crazy with the
// tooltips"; these icons dim instead, so there is nothing left to be caught by.
// The last VISIBLE one again: a hidden last child has no box to move to.
const ob = await lastTip.boundingBox();
await page.mouse.move(ob.x + ob.width / 2, ob.y + ob.height / 2);
await page.waitForTimeout(250);
const moved = await lastTip.evaluate(e => {
  const c = getComputedStyle(e, '::after'); return [c.display, parseFloat(c.width)];
});
ok(moved[0] === 'block' && moved[1] > 100,
   `...and the next control's own tip opens at its own size (${moved.join(', ')})`);
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
// A colour transition that exists only while a swap is happening. A standing
// one on every element would be the easy version and the wrong one: it would
// slow every hover and every state light on the page to make one rare action
// look nicer.
{
  // What "crossfades" means, asserted without racing the 320ms window: the
  // swap turns a colour transition ON for its duration. Sampling the colour
  // partway through needed the evaluate to land inside that window, which a
  // loaded box does not promise — it read as a cut on the node running the
  // suite, and reading it synchronously instead caught the value before the
  // transition had started. So: the class and the transition it brings are
  // the claim, and the colour is checked once the swap has finished.
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
// rule, and a site declares only what is its own — font aside, that is the
// whole contract. A field in a context the rule does not list silently wears
// the BROWSER's default instead, which is how the log-retention box ended up
// a 2px grey square in Arial beside a page of sunk monospace fields.
{
  await page.click('#bCards');
  await page.waitForTimeout(400);
  const odd = await page.evaluate(() => {
    // Every dialog at once, so this sees the fields that live inside them.
    document.querySelectorAll('[hidden]').forEach(e => { e.hidden = false; });
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
    document.querySelectorAll('.modal,.uimenu').forEach(e => { e.hidden = true; });
    return bad;
  });
  ok(odd.length === 0, `every text field wears the one skin (${odd.join(' | ') || 'all'})`);
}

// ---- one frame, three pieces ------------------------------------------
// The tab strip, the panes and the bottom bar are drawn as one outline: the
// strip owns the top corners and its own bottom edge, the panes carry the
// sides with no top border, the bar owns the bottom corners. .col's 10px gap
// pushed them apart into three boxes with the seams showing, which is what
// this measures — the pieces have to touch exactly.
{
  await page.evaluate(() => { const b = [...document.querySelectorAll('button')]
    .find(x => /^Terminal$/.test(x.textContent.trim())); b && b.click(); });
  await page.waitForTimeout(400);
  const seams = await page.evaluate(() => {
    const box = s => { const e = document.querySelector(s);
      if (!e) return null; const r = e.getBoundingClientRect();
      return r.height ? [r.top, r.bottom] : null; };
    const parts = ['.tabstrip', '.panes', '.keys', '.mobar']
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
  // value the keyboard passes — typing 30 over 300 would have pruned at 3.
  writeFileSync(`${LD}/docker.log.2`, 'x'.repeat(64));
  const week = Date.now() / 1000 - 7 * 86400;
  utimesSync(`${LD}/docker.log.2`, week, week);
  // The control graduated from the gear to the Settings tab with everything
  // controller-scoped (docs/nodes.md §13); the gear keeps this browser's
  // items and the door.
  await page.click('#bCards');
  await page.waitForSelector('#uiProfile');
  ok(await page.evaluate(() => !document.querySelector('#uiMenu #logApply')),
     'the gear holds appearance and a door, not the log policy');
  // The door to the controller's settings is the Administration card's
  // now; the gear's door is the account's own Profile tab.
  await page.click('#uiProfile');
  await page.waitForSelector('.profiletab .setrow', { timeout: 15000 });
  ok(true, "the gear's door opens the account's Profile tab");
  await page.evaluate(() => { const c = document.getElementById('cardAdmin');
    if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
  await page.click('#bSettings');
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
  const back = await page.evaluate(() =>
    fetch('/api/status').then(r => r.json()).then(j => j.logs.days));
  ok(back === 30, '...and raising it again is just a setting, with nothing to crop');
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
}

// The command pin and the project pin are different features that spent an
// afternoon sharing four names — /api/pin, _pin, PINS_FILE and setPinned — and
// nothing went red, because pinning a command had no test at all (bug #20).
// This is that test: the two write to their own files and neither can be
// reached through the other's endpoint.
const cmdPin = await api('/api/pin', { name: 'status', pinned: true });
ok(cmdPin.status === 200 && (cmdPin.body.pinned || []).includes('status'),
   'a command can be pinned');
ok(JSON.parse(readFileSync(`${DIR}/state/pinned-commands.json`, 'utf8')).includes('status'),
   '...into pinned-commands.json, which is its own file');
ok(!JSON.parse(readFileSync(`${DIR}/state/pinned-projects.json`, 'utf8')).includes('status'),
   '...and not into the projects one');
ok((await api('/api/pin', { name: 'alpha', pinned: true })).status === 400,
   'a project name is not a command, and the command pin says so');
ok((await api('/api/project-pin', { name: 'status', pinned: true })).status === 400,
   '...and a command name is not a project');
await done(browser);
