// The document-tab conformance suite: the hard rules every tab kind is held
// to, generically, so a new tab cannot ship its own idea of the chrome.
//
// This file exists because the rules kept being re-broken: three tabs in a
// row landed with browser-default controls, a filter bar flush against the
// edge, or rows on the sidebar's tighter inset — each fixed by inverting a
// mechanism (the global field skin, the band tokens, the doc-tab groups),
// each found by a person noticing. The mechanisms make conformance cheap;
// this makes deviation LOUD. The rules run for every kind registered in
// TABKINDS that renders a document, discovered from the page itself, so:
//
//   - a new tab kind with no driver below FAILS ("no conformance driver"),
//     which is the enforcement hook — the price of a new tab includes making
//     it conform, not just making it exist;
//   - the rules are computed style and geometry, never class names taken on
//     faith, so passing means the pixels agree, not that the markup claims to.
//
// What is deliberately NOT here: per-kind content checks. Those live in each
// kind's own suite. This file only holds the language every kind shares.
import { URL, DIR, launch, newPage, ok, done, ready, sleep } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// How each document kind is opened, and what says its content has arrived.
// A new TABKINDS entry must add a line here or the discovery check fails.
const DRIVERS = {
  findings: {
    open: async () => {
      await page.evaluate(() => { const c = document.getElementById('cardTools');
        if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
      await page.evaluate(() => openFindingsTab());
    },
    readyWhen: '.fxtab .rule',
  },
  docker: {
    open: () => page.evaluate(() => openDocker()),
    readyWhen: '.dmtab .macros',
  },
  packages: {
    open: () => page.evaluate(() => openPackages()),
    readyWhen: '.pkgtab .pkg',
  },
  projects: {
    open: () => page.evaluate(() => openProjectsTab()),
    readyWhen: '.projtab .row',
  },
  todo: {
    open: () => page.evaluate(() => openNotebook('alpha', 'roadmap')),
    readyWhen: '.nb .nbview:not([hidden]) .field',
  },
  nodes: {
    open: () => page.evaluate(() => openNodesTab()),
    readyWhen: '.nodestab .ndrow',
  },
  settings: {
    open: () => page.evaluate(() => openSettingsTab()),
    readyWhen: '.settingstab .logdays',
  },
  jobs: {
    // Whether the queue has anything in it depends on which suites ran
    // before this one; either drawing carries the bar and the foot band.
    open: () => page.evaluate(() => openJobsTab()),
    readyWhen: '.jobstab .jbrow, .jobstab .empty',
  },
  phone: {
    // The fixture's sandbox node carries adb, so the tab draws its rows.
    open: () => page.evaluate(() => openPhoneTab()),
    readyWhen: '.phonetab .row, .phonetab .hint',
  },
  users: {
    // There is always at least one row: the owner, seeded on the first boot,
    // which cannot be deleted and so cannot be absent.
    open: () => page.evaluate(() => openUsersTab()),
    readyWhen: '.userstab .urow',
  },
  profile: {
    open: () => page.evaluate(() => openProfileTab()),
    readyWhen: '.profiletab .setrow',
  },
};

// Every kind that renders a document, from the page's own registry — never a
// hand-kept list here, because a hand-kept list is how a new kind ships
// unmeasured.
const kinds = await page.evaluate(() =>
  Object.entries(TABKINDS).filter(([, v]) => v.render).map(([k]) => k));
const undriven = kinds.filter(k => !DRIVERS[k]);
ok(undriven.length === 0,
   `every document tab kind has a conformance driver${
     undriven.length ? ` — missing: ${undriven.join(', ')} (add it to
     uniform.mjs DRIVERS; the hard rules are the price of a new tab)` : ''}`);

// The band classes the design language names. Content-left must agree across
// every one of them that is visible — this is the rule that was broken three
// different ways before it was a rule. Indented-by-design rows opt out by
// class, and the list of those is deliberately short.
const BANDS = '.field, .row, .rule, .empty, .loading, .fnote, .dmsrc, ' +
              '.macros, .fxproj, .pkghead, .pkg, .sect>summary';
const INDENTED = ['img'];        // .pkg.img — a child row, indented on purpose

async function measure(kind){
  return page.evaluate(({ BANDS, INDENTED }) => {
    // The tab's own box: the doc pane that is showing. The notebook's root is
    // .nb rather than .doctab and predates the scaffold; same rules apply.
    const host = document.querySelector('.doc.on');
    const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div');
    if (!box) return { err: 'no document box found' };
    const cs = getComputedStyle(box);
    const bands = [...box.querySelectorAll(BANDS)]
      .filter(e => e.offsetHeight > 0 && e.textContent.trim())
      .filter(e => !INDENTED.some(c => e.classList.contains(c)))
      // Nested band-in-band measures the outer one; the inner is content.
      .filter(e => !e.parentElement.closest(BANDS));
    const lefts = [...new Set(bands.map(e => Math.round(
      e.getBoundingClientRect().x + parseFloat(getComputedStyle(e).paddingLeft))))];
    const ref = document.getElementById('mName');
    const skin = el => { const c = getComputedStyle(el);
      return [c.backgroundColor, c.borderTopLeftRadius, c.borderTopColor,
              c.fontFamily].join('|'); };
    const controls = [...box.querySelectorAll('input, select, textarea')]
      .filter(e => e.offsetHeight > 0)
      .filter(e => !['checkbox', 'radio', 'range', 'file'].includes(e.type));
    const offskin = controls.filter(e => skin(e) !== skin(ref))
      .map(e => e.id || e.className || e.tagName);
    // Meters (design language, Meters): every track in a stack the same
    // width. A stack is the parent that holds more than one track; the
    // widths are rounded, and a stack whose widths are not all one value
    // is reported with them, so the failure names the ragged row.
    const stacks = new Map();
    for (const t of box.querySelectorAll('.track')){
      if (t.offsetHeight === 0) continue;
      const key = t.parentElement?.parentElement;
      if (!key) continue;
      if (!stacks.has(key)) stacks.set(key, []);
      stacks.get(key).push(Math.round(t.getBoundingClientRect().width));
    }
    const ragged = [...stacks.values()].filter(ws => ws.length > 1 && new Set(ws).size > 1);
    return {
      ragged, stacks: [...stacks.values()].filter(ws => ws.length > 1).length,
      // flush and nbhost are the same treatment in the sheet — the notebook
      // wears the second for its own reasons; both mean "fills the pane".
      flush: host.classList.contains('flush') || host.classList.contains('nbhost'),
      maxw: cs.maxWidth,
      bands: bands.length, lefts,
      controls: controls.length, offskin,
    };
  }, { BANDS, INDENTED });
}

for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await DRIVERS[kind].open();
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  await sleep(150);                       // entrance animation settles
  const m = await measure(kind);
  ok(!m.err, `[${kind}] a document box exists (${m.err || 'ok'})`);
  ok((m.ragged || []).length === 0,
     `[${kind}] every stack of meters has tracks of one width (${m.stacks || 0} stack${m.stacks === 1 ? '' : 's'}${
       m.ragged?.length ? `; ragged: ${m.ragged.map(w => w.join('/')).join('; ')}` : ''})`);
  if (m.err) continue;
  ok(m.flush, `[${kind}] fills its pane flush, like every document`);
  ok(m.maxw === '1080px',
     `[${kind}] caps at the document width (got ${m.maxw})`);
  ok(m.bands > 0 && m.lefts.length === 1,
     `[${kind}] every band starts at one x (${m.bands} bands at ${
       JSON.stringify(m.lefts)})`);
  ok(m.offskin.length === 0,
     `[${kind}] every control wears the field skin${
       m.offskin.length ? ` — not: ${m.offskin.join(', ')}` : ''} (${
       m.controls} checked)`);
}

// ---- the section and action-bar language -----------------------------------
// The other half of the document language, and the half that drifts: it is
// carried by shared classes rather than by a scaffold function, so a tab can
// quietly answer differently and nothing notices. These rules are the things
// that must be the SAME on every tab — which is why they are here and not in
// each kind's own suite. A rule that is genuinely one tab's belongs there.
//
// Measured, never taken on faith: the colours and the layout are computed, so
// a tab that restyles .actbar or .danger locally fails even though its markup
// says the right words.
//
// What this cannot see is a surface that is not on screen when it looks: a
// Docker row needs an instance, a project picker needs to be expanded. Those
// are each tab's own fixture and each tab's own suite. What is here is the
// shape, checked on whatever the tab does render.

// A tab strip is navigation, not actions; the document's own footer has its
// own shape (one verb left, its undo right). Everything else that holds two
// or more TEXT buttons is an action bar — icon clusters are exempt by having
// no text, which is what makes a roadmap row's five pictograms legal and a
// row of Up / Down / Remove not.
const NOT_A_BAR = ['nbtabs', 'foot'];

async function language(){
  return page.evaluate(({ NOT_A_BAR }) => {
    const host = document.querySelector('.doc.on');
    const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div');
    if (!box) return { err: 'no document box found' };
    const vis = e => e.offsetHeight > 0 || e.offsetWidth > 0;
    const isBtn = c => (c.tagName === 'BUTTON'
                        || (c.tagName === 'A' && c.classList.contains('btn'))) && vis(c);
    const named = e => String(e.className || e.tagName).split(/\s+/)[0] || e.tagName;
    const gone = b => b.classList.contains('danger');
    const loose = [], order = [], layout = [], reds = new Set();
    for (const e of box.querySelectorAll('*')){
      const btns = [...e.children].filter(isBtn);
      if (btns.length < 2) continue;
      if (!btns.some(b => b.textContent.trim())) continue;      // an icon cluster
      if (!e.classList.contains('actbar')){
        if (!NOT_A_BAR.some(c => e.classList.contains(c)))
          loose.push(`${named(e)}(${btns.map(b => b.textContent.trim().slice(0, 12)).join('/')})`);
        continue;
      }
      // Destructive last: not "the last button is destructive", but that
      // nothing safe sits after something that cannot be undone — which is
      // the rule a thumb obeys and a two-Remove bar still satisfies.
      const first = btns.findIndex(gone);
      if (first >= 0 && btns.slice(first).some(b => !gone(b)))
        order.push(`${named(e)}(${btns.map(b => (gone(b) ? '!' : '') + b.textContent.trim().slice(0, 10)).join('/')})`);
      const c = getComputedStyle(e);
      layout.push([c.display, c.flexWrap, c.justifyContent].join('|'));
    }
    // ...and a destructive button LOOKS destructive, the same way everywhere.
    for (const b of box.querySelectorAll('button.danger, a.btn.danger')){
      if (!vis(b) || !b.textContent.trim()) continue;
      reds.add(getComputedStyle(b).color);
    }
    const sects = [...box.querySelectorAll('details.sect > summary')].map(s => {
      const c = getComputedStyle(s);
      return { status: s.querySelector('.sst')?.textContent?.trim() || '',
               skin: [c.minHeight, c.fontWeight, c.cursor].join('|') };
    });
    return { loose, order, layout: [...new Set(layout)], reds: [...reds], sects };
  }, { NOT_A_BAR });
}

// Gathered across every kind and compared at the end: "the same on every tab"
// is not a claim any one tab can fail on its own.
const seenBars = new Set(), seenSects = new Set(), seenReds = new Set();
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await page.evaluate(k => { const t = tabs.find(x => x.kind === k);
                             if (t) focusTab(t.id); }, kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  await sleep(200);
  const L = await language();
  ok(!L.err, `[${kind}] measurable for the button language (${L.err || 'ok'})`);
  if (L.err) continue;
  ok(L.loose.length === 0,
     `[${kind}] every set of text buttons is an action bar${
       L.loose.length ? ` — not: ${L.loose.join(', ')}` : ''}`);
  ok(L.order.length === 0,
     `[${kind}] nothing safe sits after a verb that cannot be undone${
       L.order.length ? ` — ${L.order.join(', ')}` : ''}`);
  L.layout.forEach(x => seenBars.add(x));
  L.sects.forEach(x => seenSects.add(x.skin));
  L.reds.forEach(x => seenReds.add(x));
  const wordy = L.sects.filter(x => x.status.length > 24).map(x => x.status);
  ok(wordy.length === 0,
     `[${kind}] a section's status is a word or a number, not a sentence${
       wordy.length ? ` — ${JSON.stringify(wordy)}` : ''}`);
}
ok(seenBars.size <= 1,
   `an action bar lays out the same on every tab (${JSON.stringify([...seenBars])})`);

// ---- a control never spans its container ----------------------------------
// A button, a select, a text field, or a row of them side by side stops
// short of the tab's width at every width (docs/design-language.md,
// Controls). Measured as the union of a row's controls against the box
// holding them, so an action bar whose buttons sit at the right is judged
// on the buttons and not on the bar's own full-width flex box. Terminals
// and logs are not controls; a readonly textarea showing text is a log.
async function spanning(){
  return page.evaluate(() => {
    const host = document.querySelector('.doc.on');
    const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div');
    if (!box) return { err: 'no document box found' };
    const W = box.getBoundingClientRect().width;
    // The rule's own number as well as the surface: a 700px field on a
    // 1080px tab is inside 90% and outside --ctl-w.
    const cap = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ctl-w')) * 16 || 480;
    const LIM = Math.min(W * 0.9, cap + 2);
    const CTL = 'input:not([type=checkbox]):not([type=radio]), select, textarea, button';
    const ROWS = '.actbar, .addbar, .todoadd, .histbar, .logdays, .setrow, .prefrow, .dmroute, .imgadd, .pkgnode, .ndpaths, .ndrunner, .ndconfacts';
    const vis = e => e.offsetHeight > 0 && e.getBoundingClientRect().width > 0;
    const out = [];
    const seen = new Set();
    for (const row of box.querySelectorAll(ROWS)){
      const kids = [...row.querySelectorAll(CTL)].filter(vis);
      kids.forEach(k => seen.add(k));
      if (!kids.length) continue;
      const l = Math.min(...kids.map(k => k.getBoundingClientRect().left));
      const r = Math.max(...kids.map(k => k.getBoundingClientRect().right));
      if (r - l > LIM) out.push(`${row.className.split(' ')[0]} ${Math.round(r - l)}/${Math.round(W)}`);
    }
    for (const e of box.querySelectorAll(CTL)){
      if (seen.has(e) || !vis(e) || e.closest('.term, .dmlog, pre, .dropbox, .sendbox')) continue;
      // A prose editor in the notebook is a page, not a control.
      if (e.tagName === 'TEXTAREA' && (e.readOnly || e.closest('.nb'))) continue;
      const w = e.getBoundingClientRect().width;
      if (w > LIM) out.push(`${e.id || e.className.split(' ')[0] || e.tagName} ${Math.round(w)}/${Math.round(W)}`);
    }
    return { wide: out, w: W };
  });
}
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await page.evaluate(k => { const t = tabs.find(x => x.kind === k);
                             if (t) focusTab(t.id); }, kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  const S = await spanning();
  ok(!S.err && S.wide.length === 0,
     `[${kind}] no control or row of controls spans the tab${
       S.err ? ` (${S.err})` : S.wide.length ? ` — ${S.wide.join(', ')}` : ''}`);
}

// ---- adding goes at the top ------------------------------------------------
// The control that adds to a notebook view is the first band under its head
// row, above the list, at both widths — never at the foot, where a phone
// scrolled past every row to find it. Measured on each view that has one,
// against its head row and the first row of its list.
{
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'todo');
                              if (t) focusTab(t.id); });
  const misplaced = [];
  for (const v of ['roadmap', 'bugs', 'briefing']){
    await page.evaluate(w => getNotebook('alpha').view(w), v);
    await page.waitForFunction(w => document.querySelector(`.nb .nbview[data-view="${w}"] [data-add]`)?.offsetHeight > 0,
                               v, { timeout: 20000 });
    const r = await page.evaluate(w => {
      const view = document.querySelector(`.nb .nbview[data-view="${w}"]`);
      const head = view.querySelector(':scope > .nbhead').getBoundingClientRect();
      return [...view.querySelectorAll('[data-add]')].map(a => {
        const box = a.getBoundingClientRect();
        // The list this control adds to: the nearest following sibling band
        // holding rows, or the section's own list for a rule.
        const list = a.dataset.add === 'rule' ? view.querySelector('#rlList')
                   : a.dataset.add === 'memory' ? view.querySelector('#memList')
                   : a.dataset.add === 'bug' ? view.querySelector('#bugList')
                   : view.querySelector('#todoList');
        const row = list?.firstElementChild?.getBoundingClientRect();
        return { add: a.dataset.add, belowHead: box.top >= head.bottom - 1,
                 aboveList: !row || box.bottom <= row.top + 1,
                 button: !!a.querySelector('button') };
      });
    }, v);
    r.filter(x => !(x.belowHead && x.aboveList && x.button)).forEach(x => misplaced.push(`${v}:${x.add} ${JSON.stringify(x)}`));
  }
  ok(misplaced.length === 0,
     `every add control sits under its head row and above its list, as a button${
       misplaced.length ? ` — not: ${misplaced.join('; ')}` : ''}`);
  // Save and Revert only where something can be staged behind them: a Save
  // under a list that writes through read as a button that did nothing.
  const foots = {};
  for (const v of ['roadmap', 'briefing', 'artifacts', 'bugs', 'analysis', 'tests', 'git']){
    await page.evaluate(w => getNotebook('alpha').view(w), v);
    await page.waitForFunction(w => document.querySelector(`.nb .nbview[data-view="${w}"]`)?.checkVisibility(),
                               v, { timeout: 20000 });
    // The notebook on screen, not the first in the DOM: a second project's
    // notebook may be parked before it.
    foots[v] = await page.evaluate(() => [...document.querySelectorAll('.nb')]
      .find(n => n.checkVisibility())?.querySelector('#nbFoot')?.checkVisibility() || false);
  }
  ok(foots.roadmap && foots.briefing && foots.artifacts && !foots.bugs && !foots.analysis && !foots.tests && !foots.git,
     `the notebook's foot shows on the views that stage and on no other (${JSON.stringify(foots)})`);
}

// ---- the notebook's head row ------------------------------------------------
// Every view opens with the same row: its one-line summary left, its History
// right — and that row is the FIRST band of the view, so the History sits at
// one height whichever tab is open. Measured rather than read from the
// markup, because the Briefing tab once put a section above its head and
// every other rule here still passed.
{
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'todo');
                              if (t) focusTab(t.id); });
  await page.waitForSelector('.nb .nbview:not([hidden]) .field', { timeout: 20000 });
  const views = await page.$$eval('.nb .nbview', vs => vs.map(v => v.dataset.view));
  const heads = {};
  for (const v of views){
    await page.evaluate(w => getNotebook('alpha').view(w), v);
    await page.waitForFunction(w => document.querySelector(`.nb .nbview[data-view="${w}"]`)?.checkVisibility(),
                               v, { timeout: 20000 });
    await sleep(150);
    heads[v] = await page.evaluate(w => {
      const view = document.querySelector(`.nb .nbview[data-view="${w}"]`);
      const shown = [...view.children].filter(e => e.offsetHeight > 0 || e.offsetWidth > 0);
      const first = shown[0];
      const head = view.querySelector(':scope > .nbhead');
      return { first: first ? (first.className || first.tagName).split(/\s+/)[0] : '(nothing)',
               isHead: !!first && first.classList.contains('nbhead'),
               top: head ? Math.round(head.getBoundingClientRect().top) : null,
               // Not every view has a log — Tests and Artifacts open with a
               // summary and nothing else — but where a head has controls
               // they sit right of the summary, after its spacer.
               right: !head || [...head.querySelectorAll('button')].every(b => {
                 const sp = head.querySelector('.sp');
                 return sp && (sp.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
               }) };
    }, v);
  }
  const notFirst = Object.entries(heads).filter(([, h]) => !h.isHead).map(([v, h]) => `${v} opens with ${h.first}`);
  ok(notFirst.length === 0,
     `every notebook view opens with its head row${notFirst.length ? ` — not: ${notFirst.join(', ')}` : ''}`);
  const tops = new Set(Object.values(heads).map(h => h.top));
  ok(tops.size === 1,
     `...and the head row sits at one height on every view (${JSON.stringify(
       Object.fromEntries(Object.entries(heads).map(([v, h]) => [v, h.top])))})`);
  ok(Object.values(heads).every(h => h.right),
     '...with its controls, where it has any, to the right of the summary');
}
ok(seenSects.size <= 1,
   `a section heading wears one skin everywhere (${JSON.stringify([...seenSects])})`);
ok(seenReds.size <= 1,
   `a verb that cannot be undone is the same colour everywhere (${JSON.stringify([...seenReds])})`);

// The fence inside the one page: a renderer that throws must break its own
// tab and nothing else — before renderGuarded, one bug in one kind's render
// took drawPanes down, and with it the poll, the strip and every terminal.
{
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'findings');
                              if (t) focusTab(t.id); });
  const errsBefore = page.errors.length;
  await page.evaluate(() => {
    window.__realFxRender = TABKINDS.findings.render;
    TABKINDS.findings.render = () => { throw new Error('boom (deliberate)'); };
    fxRev++; drawPanes();
  });
  await page.waitForFunction(() => /renderer failed/.test(
    document.querySelector('.doc.on')?.textContent || ''), null, { timeout: 8000 });
  ok(true, 'a throwing renderer becomes an error band in its own tab');
  const alive = await page.evaluate(() => {
    // The page is still a page: another kind renders, the strip answers.
    const t = tabs.find(x => x.kind === 'docker');
    if (t) focusTab(t.id);
    return !!document.querySelector('.dmtab .macros');
  });
  ok(alive, '...and the rest of the dashboard keeps working around it');
  ok(page.errors.length > errsBefore
     && /boom \(deliberate\)/.test(page.errors[page.errors.length - 1]),
     '...while the error still reaches the console, so a caught bug is not a hidden one');
  // Deliberate, asserted, and now removed — the final zero-errors check below
  // is about bugs this suite did not cause on purpose.
  page.errors.length = errsBefore;
  await page.evaluate(() => {
    TABKINDS.findings.render = window.__realFxRender;
    delete window.__realFxRender;
    fxRev++; drawPanes();
  });
  await page.waitForSelector('.fxtab .rule', { timeout: 8000 }).catch(() => {});
}

// The same page, held to the same rules at phone width: nothing may scroll
// the page sideways, and every text control is 16px so iOS does not zoom a
// layout that cannot zoom back.
await page.setViewportSize({ width: 393, height: 851 });
await page.evaluate(() => setView('terminal'));
await sleep(400);
// The same width rule at phone width, on every tab: the cap is min(--ctl-w,
// 88%), and 88% is what bites here.
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await page.evaluate(k => { const t = tabs.find(x => x.kind === k);
                             if (t) focusTab(t.id); }, kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  const S = await spanning();
  ok(!S.err && S.wide.length === 0,
     `[${kind}] no control or row of controls spans the tab at phone width${
       S.err ? ` (${S.err})` : S.wide.length ? ` — ${S.wide.join(', ')}` : ''}`);
}
// The Tests view needs rows to be measured on, and one of them a continuation
// — a "..." name whose "follows:" line is drawn under it — because that line
// is exactly what scrolled the tab sideways once (a 100% flex basis plus a
// margin, unable to shrink). A registry the fixture does not carry, so a
// two-line run is ingested here; the file reset takes it away again.
{
  const { writeFileSync } = await import('node:fs');
  const { execFileSync } = await import('node:child_process');
  const { fileURLToPath } = await import('node:url');
  const { dirname, join } = await import('node:path');
  const HERE = dirname(fileURLToPath(import.meta.url));
  writeFileSync(`${DIR}/ws/alpha/.bb-test-run.log`,
    '[dashboard-test] == shape.mjs ==\nPASS  [+0.1s] a row long enough to wrap on a phone, which most of them are\n'
    + 'PASS  [+0.1s] ...and a continuation of it, whose follows line is drawn under the name\n'
    + '2 passed, 0 failed in 0.2s\n');
  execFileSync(join(HERE, '..', '..', 'bb'), ['tests', 'ingest', '.bb-test-run.log'],
    { cwd: `${DIR}/ws/alpha`, env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
      DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha' } });
}
// Measured on the document AND on the document box, because the box scrolls
// on its own: the page reported no overflow while the Tests tab scrolled
// sideways inside its pane. The widest offender is named, so the failure
// says what to fix rather than that something is wide. The tab strip is
// the one thing allowed past the edge — it scrolls by design.
const sideways = () => page.evaluate(() => {
  const host = document.querySelector('.doc.on');
  const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div') || host;
  const controls = [...(host?.querySelectorAll('input, select, textarea') || [])]
    .filter(e => e.offsetHeight > 0)
    .filter(e => !['checkbox', 'radio'].includes(e.type));
  const edge = (box?.getBoundingClientRect().right || document.documentElement.clientWidth) + 1;
  let widest = null;
  for (const e of box?.querySelectorAll('*') || []){
    if (e.closest('.nbtabs')) continue;
    const r = e.getBoundingClientRect();
    if (r.width && r.right > edge && (!widest || r.right > widest.right)){
      // Named with its text and its parents, so the failure says where to
      // look rather than "a button": a bare `button.` cost a second run.
      // ...and each parent's width, because the element named is only where
      // the overflow ENDS: a button at the right of a row is past the edge
      // because something else made the row wide.
      const chain = [];
      let row = null;
      for (let a = e.parentElement, n = 0; a && n < 5 && !a.classList.contains('doc'); a = a.parentElement, n++){
        chain.push(`${a.tagName.toLowerCase()}${a.id ? '#' + a.id : ''}.${String(a.className || '').split(/\s+/)[0]}=${Math.round(a.getBoundingClientRect().width)}`);
        if (a.classList.contains('row')) row = a;
      }
      widest = { right: Math.round(r.right),
                 what: `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}.${String(e.className || '').split(/\s+/)[0]}`
                   + ` "${(e.textContent || '').trim().slice(0, 20)}" in ${chain.join(' < ')}`
                   + (row ? ` — row: ${row.outerHTML.replace(/\s+/g, ' ').slice(0, 700)}` : '') };
    }
  }
  return {
    overflow: Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth,
                       box ? box.scrollWidth - box.clientWidth : 0),
    widest,
    small: controls.filter(e => parseFloat(getComputedStyle(e).fontSize) < 16)
      .map(e => e.id || e.className || e.tagName),
  };
});
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await page.evaluate(k => { const t = tabs.find(x => x.kind === k);
                             if (t) focusTab(t.id); }, kind);
  await sleep(250);
  // The notebook is six views behind one tab, and each has its own layout;
  // the Tests view is the one that scrolled sideways while the Roadmap, the
  // one this check used to look at, did not.
  const views = kind === 'todo'
    ? await page.$$eval('.nb .nbview', vs => vs.map(v => v.dataset.view)) : [''];
  for (const v of views){
    if (v){
      await page.evaluate(w => getNotebook('alpha').view(w), v);
      await page.waitForFunction(w => document.querySelector(`.nb .nbview[data-view="${w}"]`)?.checkVisibility(),
                                 v, { timeout: 20000 });
      await sleep(250);
    }
    const m = await sideways();
    const tag = v ? `${kind}/${v}` : kind;
    ok(m.overflow <= 0 && !m.widest, `[${tag}] no sideways scroll at phone width (${
      m.overflow}px over${m.widest ? `; ${m.widest.what} reaches ${m.widest.right}px` : ''})`);
    ok(m.small.length === 0, `[${tag}] phone controls are 16px${
      m.small.length ? ` — not: ${m.small.join(', ')}` : ''}`);
  }
}

// ---- the document and the framework are one thing ---------------------------
// docs/design-language.md is what a session reads; this suite is what holds
// the page. The two drift apart the day a helper is renamed and the document
// still names the old one, so every name the document uses is checked to be
// real on the page, and every helper the framework exposes is checked to be
// in the document — a rename without a rewrite fails here by name.
{
  const { readFileSync } = await import('node:fs');
  const { fileURLToPath } = await import('node:url');
  const { dirname, join } = await import('node:path');
  const doc = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'docs', 'design-language.md'), 'utf8');
  const helpers = ['docSurface', 'docSection', 'renderGuarded', 'busy'];
  const missing = helpers.filter(h => !doc.includes(h));
  ok(missing.length === 0,
     `the design language names every helper the framework exposes${missing.length ? ` — not: ${missing.join(', ')}` : ''}`);
  const named = [...doc.matchAll(/`(docSurface|docSection|renderGuarded|busy|wireSections)\b/g)].map(m => m[1]);
  const unreal = await page.evaluate(ns => ns.filter(n => typeof window[n] !== 'function'), [...new Set(named)]);
  ok(unreal.length === 0,
     `...and every helper the document names is a real function on the page${unreal.length ? ` — not: ${unreal.join(', ')}` : ''}`);
  // By name, with or without the dot: the document writes a class as it
  // appears in markup as often as as a selector.
  const classes = ['actbar', 'field', 'histbar', 'danger', 'state'];
  const undocumented = classes.filter(c => !new RegExp(`\\b${c}\\b`).test(doc));
  ok(undocumented.length === 0,
     `...and names the classes the page is measured on${undocumented.length ? ` — not: ${undocumented.join(', ')}` : ''}`);
}

// ---- a fold lasts for the page, and a reload starts it from the default ---
// Open state is kept while the page lives and never stored (the design
// language, Sections): closed by hand on a desktop, where the default is
// open, it stays closed through the repaints and is open again after a
// reload. Measured on the Nodes tab's Health section: a fixed section
// rather than the first one found, because a tab that is still filling in
// (the Docker manager redraws as its rows land) replaces the element
// between the find and the close, and a close on a detached fold records
// nothing — which read as the rule failing when only the sample had moved.
{
  const kind = 'nodes', key = 'nodes:health';
  const sel = `.doc.on details.sect[data-sect="${key}"]`;
  const focus = async () => {
    await page.evaluate(k => { const t = tabs.find(x => x.kind === k);
                               if (t) focusTab(t.id); }, kind);
    await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
    await page.waitForSelector(sel, { timeout: 20000 });
  };
  await focus();
  ok(await page.$eval(sel, d => d.open), `[${kind}] a section opens by default on a desktop (${key})`);
  await page.evaluate(s => { document.querySelector(s).open = false; }, sel);
  await page.waitForFunction(k => sectOpen[k] === false, key, { timeout: 5000 });
  ok(true, `[${kind}] a fold closed by hand stays closed for the page (${key})`);
  await page.reload(); await ready(page);
  await focus();
  ok(await page.$eval(sel, d => d.open),
     `[${kind}] ...and a reload starts it from its default, open on a desktop`);
}

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
