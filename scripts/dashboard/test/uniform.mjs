// The document-tab conformance suite: the hard rules every tab kind is held
// to, generically, so a new tab cannot ship its own idea of the chrome.
//
// This file exists because the rules kept being re-broken: three tabs in a
// row landed with browser-default controls, a filter bar flush against the
// edge, or rows on the sidebar's tighter inset, each fixed by inverting a
// mechanism (the global field skin, the band tokens, the doc-tab groups),
// each found by a person noticing. The mechanisms make conformance cheap;
// this makes deviation LOUD. The rules run for every kind registered in
// TABKINDS that renders a document, discovered from the page itself, so:
//
//   - a new tab kind with no driver below FAILS ("no conformance driver"),
//     which is the enforcement hook: the price of a new tab includes making
//     it conform, not just making it exist;
//   - the rules are computed style and geometry, never class names taken on
//     faith, so passing means the pixels agree, not that the markup claims to.
//
// What is deliberately NOT here: per-kind content checks. Those live in each
// kind's own suite. This file only holds the language every kind shares.
import { URL, DIR, launch, newPage, ok, done, ready, sleep, animatedDuring } from './lib.mjs';

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
    readyWhen: '.dmtab .dmpick',
  },
  toolchains: {
    open: () => page.evaluate(() => openToolchains()),
    readyWhen: '.tctab .tc',
  },
  emulator: {
    // The harness's sandbox node reports a store, so the tab draws its head.
    open: () => page.evaluate(() => openEmulator()),
    readyWhen: '.emutab .tchead, .emutab .empty',
  },
  projects: {
    open: () => page.evaluate(() => openProjectsTab()),
    readyWhen: '.projtab .row',
  },
  notebook: {
    open: () => page.evaluate(() => openNotebook('alpha', 'roadmap')),
    readyWhen: '.nb .nbview:not([hidden]) .field',
  },
  nodes: {
    // The config plane, not the row: its editors arrive on the tab's own
    // fetch a moment later, and a rule measured on the row alone was
    // measuring a heading over nothing, which is how a mount row's
    // controls came to sit at three different heights unremarked.
    open: () => page.evaluate(() => openNodesTab()),
    readyWhen: '.nodestab .ndconfbody',
  },
  settings: {
    open: () => page.evaluate(() => openSettingsTab()),
    readyWhen: '.settingstab .logdays',
  },
  // The Phone and the CI runner, tools of their own again (R121).
  phone: {
    open: () => page.evaluate(() => openPhoneTab()),
    readyWhen: '.phonetab .row, .doc.on .hint',
  },
  runner: {
    open: () => page.evaluate(() => openRunnerTab()),
    readyWhen: '.runnertab .ndconf, .runnertab .hint',
  },
  jobs: {
    // Whether the queue has anything in it depends on which suites ran
    // before this one; either drawing carries the bar and the foot band.
    open: () => page.evaluate(() => openJobsTab()),
    readyWhen: '.jobstab .jbrow, .jobstab .empty',
  },
  storage: {
    // A section per node, or the empty band on a box with none (R169).
    open: () => page.evaluate(() => openStorageTab()),
    readyWhen: '.storagetab .sect, .storagetab .empty',
  },
  nginx: {
    // A section per node, or the empty band on a box with none (R171).
    open: () => page.evaluate(() => openNginxTab()),
    readyWhen: '.nginxtab .sect, .nginxtab .empty',
  },
  users: {
    // There is always at least one row: the owner, seeded on the first boot,
    // which cannot be deleted and so cannot be absent.
    open: () => page.evaluate(() => openUsersTab()),
    readyWhen: '.userstab .urow',
  },
  roles: {
    // The built-in roles are always there, each a fold.
    open: () => page.evaluate(() => openRolesTab()),
    readyWhen: '.rolestab .sect',
  },
  profile: {
    open: () => page.evaluate(() => openProfileTab()),
    readyWhen: '.profiletab .setrow',
  },
};

// Every kind that renders a document, from the page's own registry, never a
// hand-kept list here, because a hand-kept list is how a new kind ships
// unmeasured.
const tabKinds = await page.evaluate(() =>
  Object.entries(TABKINDS).filter(([, v]) => v.render).map(([k]) => k));
const undriven = tabKinds.filter(k => !DRIVERS[k]);
// The notebook is one tab kind and EIGHT surfaces, and every loop below
// measured whichever one it happened to be on, which was the Roadmap: the
// driver opens there and bring() focuses a tab it already has. So nine of
// the notebook's views had never been measured for the action-bar language,
// the loose-button rule, destructive-last or the control widths, and six
// words for "delete this row" and 42-word paragraphs grew under a check that
// looked like it covered them (roadmap R70). Each view is a kind of its own
// here, read off the strip the page draws rather than kept as a list, for
// the same reason the tab kinds are.
const NB_VIEWS = await page.evaluate(() =>
  [...document.getElementById('nbTpl').content.querySelectorAll('.nbtabs button[data-v]')]
    .map(b => b.dataset.v));
for (const v of NB_VIEWS)
  DRIVERS[`notebook:${v}`] = {
    open: () => page.evaluate(w => openNotebook('alpha', w), v),
    readyWhen: `.pane .nb .nbview[data-view="${v}"]:not([hidden])`,
  };
const kinds = tabKinds.flatMap(k => k === 'notebook' ? NB_VIEWS.map(v => `notebook:${v}`) : [k]);
ok(undriven.length === 0,
   `every document tab kind has a conformance driver${
     undriven.length ? `; missing: ${undriven.join(', ')} (add it to
     uniform.mjs DRIVERS; the hard rules are the price of a new tab)` : ''}`);

// The band classes the design language names. Content-left must agree across
// every one of them that is visible: this is the rule that was broken three
// different ways before it was a rule. Indented-by-design rows opt out by
// class, and the list of those is deliberately short.
const BANDS = '.field, .row, .rule, .empty, .loading, .fnote, .dmsrc, ' +
              '.macros, .fxproj, .tchead, .tc, .sect>summary';
const INDENTED = [];             // no band is indented on purpose any more

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
    const leftOf = e => Math.round(
      e.getBoundingClientRect().x + parseFloat(getComputedStyle(e).paddingLeft));
    const lefts = [...new Set(bands.map(leftOf))];
    // Which band sits at each x, for the failure: three numbers say a view is
    // ragged and nothing about where, and the fix is in one band's CSS.
    const who = {};
    for (const e of bands){
      const x = leftOf(e);
      who[x] = who[x] || `${e.tagName.toLowerCase()}.${[...e.classList].join('.')}${
        e.id ? '#' + e.id : ''} in ${e.parentElement?.className || e.parentElement?.tagName}`;
    }
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
      // flush and nbhost are the same treatment in the sheet, and the notebook
      // wears the second for its own reasons; both mean "fills the pane".
      flush: host.classList.contains('flush') || host.classList.contains('nbhost'),
      maxw: cs.maxWidth,
      bands: bands.length, lefts, who,
      controls: controls.length, offskin,
    };
  }, { BANDS, INDENTED });
}

// The page holds twelve tabs, and there are more document kinds than that
// with the terminal beside them. So a kind is brought up by focusing its tab
// when one is open, and otherwise opened, after closing the oldest other
// document when the strip is full.
async function bring(kind){
  // `notebook:<view>` is the notebook's tab with that view showing.
  const view = kind.startsWith('notebook:') ? kind.slice('notebook:'.length) : '';
  const had = await page.evaluate(k => {
    const t = tabs.find(x => x.kind === k);
    if (t){ focusTab(t.id); return true; }
    if (tabs.length >= 11){
      const old = tabs.find(x => x.kind !== 'term' && x.kind !== k);
      if (old) dropTab(old.id);
    }
    return false;
  }, view ? 'notebook' : kind);
  if (had){
    if (view){
      await page.evaluate(w => getNotebook('alpha').view(w), view);
      await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
      await sleep(400);                   // the view's own fetch lands
    }
    return;
  }
  // A fresh open settles before it is measured: a proseline sizes itself to
  // its text once the view's data has landed, a beat after the band shows.
  await DRIVERS[kind].open();
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  await sleep(500);
}

for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await bring(kind);
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
       JSON.stringify(m.lefts)}${m.lefts.length > 1 ? ': ' + m.lefts.map(x => `${x} is ${m.who[x]}`).join('; ') : ''})`);
  ok(m.offskin.length === 0,
     `[${kind}] every control wears the field skin${
       m.offskin.length ? `; not: ${m.offskin.join(', ')}` : ''} (${
       m.controls} checked)`);
}

// ---- the section and action-bar language -----------------------------------
// The other half of the document language, and the half that drifts: it is
// carried by shared classes rather than by a scaffold function, so a tab can
// quietly answer differently and nothing notices. These rules are the things
// that must be the SAME on every tab, which is why they are here and not in
// each kind's own suite. A rule that is genuinely one tab's belongs there.
//
// Measured, never taken on faith: the colors and the layout are computed, so
// a tab that restyles .actbar or .danger locally fails even though its markup
// says the right words.
//
// What this cannot see is a surface that is not on screen when it looks: a
// Docker row needs an instance, a project picker needs to be expanded. Those
// are each tab's own fixture and each tab's own suite. What is here is the
// shape, checked on whatever the tab does render.

// A tab strip is navigation, not actions; the document's own footer has its
// own shape (one verb left, its undo right). Everything else that holds two
// or more TEXT buttons is an action bar; icon clusters are exempt by having
// no text, which is what makes a roadmap row's five pictograms legal and a
// row of Up / Down / Remove not.
// `pagemore` joins them: it is the framework's own footer for a long list
// (a count and up to two buttons, drawn by paginate() and nothing else), so
// it is already one bar with one shape everywhere, which is what the rule
// below is for. It reached this check for the first time when the Jobs tab
// was paged, because every other paginated list is in a notebook whose
// fixture is too short to draw one.
const NOT_A_BAR = ['nbtabs', 'foot', 'pagemore'];

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
      // nothing safe sits after something that cannot be undone, which is
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
  await bring(kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  await sleep(200);
  const L = await language();
  ok(!L.err, `[${kind}] measurable for the button language (${L.err || 'ok'})`);
  if (L.err) continue;
  ok(L.loose.length === 0,
     `[${kind}] every set of text buttons is an action bar${
       L.loose.length ? `; not: ${L.loose.join(', ')}` : ''}`);
  ok(L.order.length === 0,
     `[${kind}] nothing safe sits after a verb that cannot be undone${
       L.order.length ? `: ${L.order.join(', ')}` : ''}`);
  L.layout.forEach(x => seenBars.add(x));
  L.sects.forEach(x => seenSects.add(x.skin));
  L.reds.forEach(x => seenReds.add(x));
  const wordy = L.sects.filter(x => x.status.length > 24).map(x => x.status);
  ok(wordy.length === 0,
     `[${kind}] a section's status is a word or a number, not a sentence${
       wordy.length ? `: ${JSON.stringify(wordy)}` : ''}`);
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
    const ROWS = '.actbar, .addbar, .roadmapadd, .histbar, .logdays, .setrow, .prefrow, .dmroute, .dmgrant, .dmref, .imgadd, .tcnode, .ndpaths';
    // A tab strip is navigation, and the phone rule for one is the opposite
    // of a control's: it wraps into rows of equal-width tabs, every one of
    // them visible (the design language, The notebook).
    const NAV = '.nbtabs, .switch, .tabbar';
    const vis = e => e.offsetHeight > 0 && e.getBoundingClientRect().width > 0;
    const out = [];
    const seen = new Set();
    for (const row of box.querySelectorAll(ROWS)){
      // The document bar is a band, not a control row (filters at the left,
      // the action at the tab's right edge), so its union spans by design.
      // Its controls are measured one by one below, like any lone control.
      if (row.classList.contains('docbarrow')) continue;
      const kids = [...row.querySelectorAll(CTL)].filter(vis);
      kids.forEach(k => seen.add(k));
      if (!kids.length) continue;
      const l = Math.min(...kids.map(k => k.getBoundingClientRect().left));
      const r = Math.max(...kids.map(k => k.getBoundingClientRect().right));
      if (r - l > LIM) out.push(`${row.className.split(' ')[0]} ${Math.round(r - l)}/${Math.round(W)}`);
    }
    for (const e of box.querySelectorAll(CTL)){
      // `.slot` is a terminal pane, not `.term`: that is the terminal
      // COLUMN, which every document tab is inside, so the exclusion took
      // every lone control on every tab with it and this half of the rule
      // measured nothing at all.
      if (seen.has(e) || !vis(e) || e.closest('.slot, .dmlog, pre, .dropbox, .sendbox, ' + NAV)) continue;
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
  await bring(kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  const S = await spanning();
  ok(!S.err && S.wide.length === 0,
     `[${kind}] no control or row of controls spans the tab${
       S.err ? ` (${S.err})` : S.wide.length ? `: ${S.wide.join(', ')}` : ''}`);
}

// ---- controls in a row line up ---------------------------------------------
// A row of controls sits on one line, and every control box on that line ends
// at the same height. What breaks it is a row that centers its items while
// some of them carry a label above (the design language, Controls): the
// unlabeled select then floats between its neighbor's label and its field,
// which is what the Nodes tab's mount rows did.
//
// Measured on the boxes, not on the wrappers: controls are grouped into lines
// by vertical overlap, so a row that wrapped is several lines and each is
// judged on its own. A checkbox is text with a box beside it rather than a
// control box, and is left out.
async function lineup(){
  return page.evaluate(() => {
    const host = document.querySelector('.doc.on');
    const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div');
    if (!box) return { err: 'no document box found' };
    const CTL = 'input:not([type=checkbox]):not([type=radio]), select, button, textarea.proseline';
    const name = e => `${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${
      e.className && typeof e.className === 'string' && e.className.trim()
        ? '.' + e.className.trim().split(/\s+/)[0] : ''}`;
    // ...and only what is on screen at its own place: a control scrolled
    // under the notebook's foot inside the view's scroller still has a
    // box, and it grouped with the foot's buttons as one line (29 Sep,
    // when the Design view's board grew and pushed its rows down).
    // ...and nothing inside a shut fold: its content keeps a box in Chrome,
    // and the point under it is its own parent's, so a Save at the foot of
    // a shut section read as on screen beside a shut row of another
    // (one section open at a time, 6 Oct).
    const folded = e => {
      for (let d = e.parentElement?.closest('details'); d; d = d.parentElement?.closest('details'))
        if (!d.open && !d.querySelector(':scope > summary')?.contains(e)) return true;
      return false;
    };
    const shown = e => {
      const r = e.getBoundingClientRect();
      const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return !!at && (at === e || e.contains(at) || at.contains(e));
    };
    const ctls = [...box.querySelectorAll(CTL)]
      .filter(e => e.offsetHeight > 0 && e.getBoundingClientRect().width > 0
                   && !e.closest('.slot, .dmlog, .pagemore') && !folded(e) && shown(e))
      .map(e => ({ e, r: e.getBoundingClientRect() }))
      .sort((a, b) => a.r.top - b.r.top);
    // One line = boxes whose vertical spans overlap by more than half the
    // shorter of the two. Two controls in different bands never do; two in
    // one row always do, however differently they are aligned.
    const lines = [];
    for (const c of ctls){
      const line = lines.find(l => l.some(o => {
        const over = Math.min(o.r.bottom, c.r.bottom) - Math.max(o.r.top, c.r.top);
        return over > Math.min(o.r.height, c.r.height) / 2;
      }));
      if (line) line.push(c); else lines.push([c]);
    }
    const off = [], sizes = [];
    for (const line of lines){
      if (line.length < 2) continue;
      const lo = Math.min(...line.map(c => c.r.bottom));
      const hi = Math.max(...line.map(c => c.r.bottom));
      if (hi - lo > 1.5)
        // Where each one is, so a line that should not be one says why it is.
        off.push(`${line.map(c => `${name(c.e)}@${Math.round(c.r.bottom)}${
          c.e.closest('[data-sect]') ? `[${c.e.closest('[data-sect]').dataset.sect}]` : ''}`).join(' ')}`);
      // ...and one height (the operator, 29 Sep: a field, a pulldown and a
      // button on one row were three sizes). A prose box that has wrapped
      // to a second line is taller by design and left out; a swatch is a
      // circle of its own.
      const one = line.filter(c => !c.e.closest('.pcpick')
        && !(c.e.matches('textarea.proseline') && c.e.scrollHeight > c.r.height + 2 && c.e.value.length));
      const hs = one.map(c => c.r.height);
      if (one.length > 1 && Math.max(...hs) - Math.min(...hs) > 1.5)
        sizes.push(`${one.map(c => `${name(c.e)}:${Math.round(c.r.height)}`).join(' ')}`);
    }
    return { off, sizes };
  });
}

// A select is ONE line high, at any width.
//
// The page draws its own <select> pickers (appearance:base-select in the
// stylesheet, so the list takes the scheme's colors instead of Android's).
// The one thing a base select does worse than a native one is a label that
// does not fit: a native select truncates it, a base one WRAPS, and a picker
// two lines tall drags its whole row out of shape. It cost the Phone tab's
// node picker at phone width once, where the bar's max-width:88% is what
// squeezes it, so this is measured where it bites rather than only at desktop.
//
// One line is computed from the control's own metrics (its line-height,
// padding and border) rather than from a constant, because the tabs run 12px, 13px
// mono and 16px on a phone.
async function unwrapped(){
  return page.evaluate(() => {
    const host = document.querySelector('.doc.on');
    const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div');
    if (!box) return { err: 'no document box found' };
    const tall = [...box.querySelectorAll('select')]
      .filter(e => e.offsetHeight > 0)
      .filter(e => {
        const c = getComputedStyle(e);
        const lh = c.lineHeight === 'normal'
          ? parseFloat(c.fontSize) * 1.4 : parseFloat(c.lineHeight);
        const one = lh + parseFloat(c.paddingTop) + parseFloat(c.paddingBottom)
                  + parseFloat(c.borderTopWidth) + parseFloat(c.borderBottomWidth);
        return e.getBoundingClientRect().height > one + 6;
      })
      .map(e => `${e.id || e.getAttribute('aria-label') || 'select'}@${
        Math.round(e.getBoundingClientRect().height)}px`);
    return { tall };
  });
}
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await bring(kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  await sleep(250);              // the last band to arrive is part of the row
  const L = await lineup();
  ok(!L.err && L.off.length === 0,
     `[${kind}] every control on a line ends at the same height${
       L.err ? ` (${L.err})` : L.off.length ? `: ${L.off.join('; ')}` : ''}`);
  ok(!L.err && L.sizes.length === 0,
     `[${kind}] every control on a line is one height${
       L.err ? ` (${L.err})` : L.sizes.length ? `: ${L.sizes.join('; ')}` : ''}`);
}

// ---- one loading line and one empty state -----------------------------------
// docs/design-language.md, Document tabs: `.loading` while it waits and
// `.empty` when there is nothing, inside the list. Read off the SOURCE, since
// an empty state is only on screen when the data happens to be empty, and the
// fixtures are not. Five classes were doing these two jobs (R70 step 3).
{
  const { readdirSync, readFileSync } = await import('node:fs');
  // Not `new URL`: URL in this file is the dashboard's address, from lib.mjs.
  const here = (await import('node:path')).resolve(import.meta.dirname, '..') + '/';
  const off = [];
  for (const f of readdirSync(here).filter(n => /^(nb-|tab-|page-).*\.js$|^index\.html$/.test(n))){
    readFileSync(here + f, 'utf8').split('\n').forEach((line, i) => {
      if (/<[a-z]+ class="(?!loading)[^"]*">loading…/.test(line)) off.push(`${f}:${i + 1} a loading line not in .loading`);
      if (/class="none"/.test(line)) off.push(`${f}:${i + 1} an empty state in .none`);
      // A <div>: a line of its own. A <span> saying "no AVD uses it" inside a
      // row is a fact about that row, not a list with nothing in it.
      if (/<div class="sub dim">(no |nothing |none )/.test(line)) off.push(`${f}:${i + 1} an empty state in .sub dim`);
    });
  }
  ok(off.length === 0, `a loading line is .loading and an empty state is .empty, in every script${
    off.length ? ': ' + off.join('; ') : ''}`);
}

// ---- colors and corners are tokens -------------------------------------------
// docs/design-language.md, Shape and Color: a hex outside the scheme blocks
// is the default scheme leaking into the other eleven (a danger edge typed
// six times, text on a filled accent in the default's --bg), and a radius
// typed as a number is one a scheme cannot square. Read off the stylesheet.
{
  const { readFileSync } = await import('node:fs');
  const path = await import('node:path');
  const html = readFileSync(path.resolve(import.meta.dirname, '..', 'index.html'), 'utf8');
  const css = html.slice(html.indexOf('<style>'), html.indexOf('</style>'));
  const lines = css.split('\n');
  const schemes = lines.findIndex(l => /^\*\{box-sizing:border-box\}/.test(l));
  const off = [];
  lines.forEach((l, i) => {
    if (i <= schemes) return;                      // the tokens and the schemes define hex
    const t = l.replace(/\/\*.*?\*\//g, '');
    // Black and white inside a color-mix() are not colors of a scheme, and
    // #2b2b2b is the terminal's own ground (see .pane iframe), never a page color.
    const hex = t.replace(/#000000|#ffffff|#2b2b2b/g, '');
    if (/#[0-9a-fA-F]{6}\b/.test(hex)) off.push(`${i + 1}: ${t.trim().slice(0, 60)}`);
    if (/border-radius:(8|6|4|10)px/.test(t)) off.push(`${i + 1}: ${t.trim().slice(0, 60)}`);
  });
  ok(off.length === 0, `no hex color and no numbered corner outside the scheme blocks (${off.length ? off.slice(0, 4).join('; ') : 'none'})`);
}

// ---- a fold stays the way it was left ---------------------------------------
// A redraw rebuilds the markup, so a <details> with nothing behind it goes
// back to however it was first drawn: the Docker manager's Details fold shut
// itself on a phone every time a job took a step. A fold is remembered one of
// two ways: a data-sect key, which the page's one toggle listener records
// (sectAttr and docSection both write it), or a list row that carries its own
// identity and whose view keeps the open set itself.
async function forgetfulFolds(){
  return page.evaluate(() => {
    const host = document.querySelector('.doc.on');
    if (!host) return { err: 'no document box found' };
    const own = 'details[data-file], details[data-key], details[data-id], details[data-i], details[data-path], details[data-branch]';
    return { bare: [...host.querySelectorAll('details')]
      .filter(d => !d.dataset.sect && !d.matches(own))
      .map(d => `details.${d.className || '(no class)'} "${
        (d.querySelector('summary')?.textContent || '').trim().slice(0, 30)}"`) };
  });
}
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await bring(kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  const F = await forgetfulFolds();
  ok(!F.err && F.bare.length === 0,
     `[${kind}] every fold is remembered across a redraw${
       F.err ? ` (${F.err})` : F.bare.length ? `: ${[...new Set(F.bare)].join('; ')}` : ''}`);
}

// ---- a setting is written by Save, never by the pick -----------------------
// docs/design-language.md, Settings: nothing on a tab takes effect until Save
// or Apply is pressed, because a select that writes on the change is a control
// that cannot be reconsidered, and the same section's Save then means two
// different things. The one exception is the color scheme in the gear, which
// is not on a document tab and is not measured here.
//
// Read off the HANDLERS, which is the only place the answer lives: a control
// that writes and one that stages look identical in the markup. The page
// assigns `el.onchange = …` almost everywhere, and a function's own source
// says whether it posts. What this cannot see is a listener added with
// addEventListener, so it is a guard against the easy mistake rather than a
// proof, the easy mistake being the one that shipped: a dial that saved on
// the pick because writing it there was three lines shorter.
//
// Filters and pickers are not settings and are allowed to act at once. They
// give themselves away by calling a LOADER rather than fetching: `loadJobs()`,
// `phFetch(…)`, `loadDocker()`. Only a literal fetch of an /api/ path in the
// handler itself is a write on the pick.
async function writesOnPick(){
  return page.evaluate(() => {
    const host = document.querySelector('.doc.on');
    const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div');
    if (!box) return { err: 'no document box found' };
    const out = [];
    for (const e of box.querySelectorAll('select, input[type=checkbox], input[type=radio]')){
      const src = String(e.onchange || '') + String(e.oninput || '');
      if (/fetch\s*\(\s*["'`]\/api\//.test(src))
        out.push(`${e.tagName.toLowerCase()}${e.id ? '#' + e.id : ''}${
          e.dataset.dmclaude ? '[data-dmclaude]' : ''}`);
    }
    return { wrote: out };
  });
}
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await bring(kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  const W = await writesOnPick();
  ok(!W.err && W.wrote.length === 0,
     `[${kind}] no setting writes itself on the pick${
       W.err ? ` (${W.err})` : W.wrote.length ? `: ${W.wrote.join(', ')}` : ''}`);
}

// ---- adding goes at the top ------------------------------------------------
// The control that adds to a notebook view is the first band under its head
// row, above the list, at both widths, never at the foot, where a phone
// scrolled past every row to find it. Measured on each view that has one,
// against its head row and the first row of its list.
{
  await bring('notebook');
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
                   : view.querySelector('#roadmapList');
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
       misplaced.length ? `; not: ${misplaced.join('; ')}` : ''}`);
  // Save and Revert only where something can be staged behind them: a Save
  // under a list that writes through read as a button that did nothing.
  const foots = {};
  for (const v of ['roadmap', 'briefing', 'artifacts', 'design', 'bugs', 'analysis', 'tests', 'git']){
    await page.evaluate(w => getNotebook('alpha').view(w), v);
    await page.waitForFunction(w => document.querySelector(`.nb .nbview[data-view="${w}"]`)?.checkVisibility(),
                               v, { timeout: 20000 });
    // The notebook on screen, not the first in the DOM: a second project's
    // notebook may be parked before it.
    // Waited on, since a view draws its sections when it is first shown.
    foots[v] = await page.waitForFunction(w => !!([...document.querySelectorAll('.nb')]
      .find(n => n.checkVisibility())?.querySelector(`.nbview[data-view="${w}"] .sectbar[data-bar]`)), v, { timeout: ["bugs", "analysis", "tests", "git"].includes(v) ? 3000 : 15000 })
      .then(() => true, () => false);
  }
  // Artifacts carries one only where a Version can stage a bump, which this
  // fixture's alpha, with no commits, cannot (version.mjs holds that one).
  ok(foots.roadmap && foots.briefing && foots.design && !foots.bugs && !foots.analysis && !foots.tests && !foots.git,
     `a section's own Save and Revert are on the views that stage and on no other (the operator, 5 Oct: there is no foot) (${JSON.stringify(foots)})`);
}

// ---- the notebook's head row ------------------------------------------------
// Every view opens with the same row: its one-line summary left, its History
// right, and that row is the FIRST band of the view, so the History sits at
// one height whichever tab is open. Measured rather than read from the
// markup, because the Briefing tab once put a section above its head and
// every other rule here still passed.
{
  await bring('notebook');
  await page.waitForSelector('.nb .nbview:not([hidden]) .field', { timeout: 20000 });
  const views = await page.$$eval('.nb .nbview', vs => vs.map(v => v.dataset.view));
  const heads = {};
  // Read the ruler when it has STOPPED MOVING, rather than after a fixed
  // pause. 150ms was enough on an idle box and not on a loaded one, so the
  // Bugs view came back two pixels lower than every other about one run in
  // three and this check went red for the suite rather than for the page
  // (B116). Two agreeing reads is the condition; the pause was never the
  // thing being tested.
  const settled = async (w) => {
    let last = null;
    for (let i = 0; i < 80; i++){
      const now = await page.evaluate(x => {
        const h = document.querySelector(`.nb .nbview[data-view="${x}"] > .nbhead`);
        return h ? Math.round(h.getBoundingClientRect().top) : null;
      }, w);
      if (now !== null && now === last) return;
      last = now;
      await sleep(50);
    }
  };
  for (const v of views){
    await page.evaluate(w => getNotebook('alpha').view(w), v);
    await page.waitForFunction(w => document.querySelector(`.nb .nbview[data-view="${w}"]`)?.checkVisibility(),
                               v, { timeout: 20000 });
    await settled(v);
    heads[v] = await page.evaluate(w => {
      const view = document.querySelector(`.nb .nbview[data-view="${w}"]`);
      const shown = [...view.children].filter(e => e.offsetHeight > 0 || e.offsetWidth > 0);
      const first = shown[0];
      const head = view.querySelector(':scope > .nbhead');
      return { first: first ? (first.className || first.tagName).split(/\s+/)[0] : '(nothing)',
               isHead: !!first && first.classList.contains('nbhead'),
               top: head ? Math.round(head.getBoundingClientRect().top) : null,
               // Not every view has a log (Tests and Artifacts open with a
               // summary and nothing else), but where a head has controls
               // they sit right of the summary, after its spacer.
               right: !head || [...head.querySelectorAll('button')].every(b => {
                 const sp = head.querySelector('.sp');
                 return sp && (sp.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
               }) };
    }, v);
  }
  const notFirst = Object.entries(heads).filter(([, h]) => !h.isHead).map(([v, h]) => `${v} opens with ${h.first}`);
  ok(notFirst.length === 0,
     `every notebook view opens with its head row${notFirst.length ? `; not: ${notFirst.join(', ')}` : ''}`);
  const tops = new Set(Object.values(heads).map(h => h.top));
  ok(tops.size === 1,
     `...and the head row sits at one height on every view (${JSON.stringify(
       Object.fromEntries(Object.entries(heads).map(([v, h]) => [v, h.top])))})`);
  ok(Object.values(heads).every(h => h.right),
     '...with its controls, where it has any, to the right of the summary');
}
ok(seenSects.size <= 1,
   `a section heading wears one skin everywhere (${JSON.stringify([...seenSects])})`);
{
  // B495: a password manager offers itself only where a password or an
  // account is asked for; every other field on the page says so, drawn
  // late or not.
  const loud = await page.$$eval('input, textarea', es => es.filter(e => {
    const t = (e.getAttribute('type') || 'text').toLowerCase();
    if (['password', 'hidden', 'checkbox', 'radio', 'file'].includes(t)) return false;
    if (['username', 'current-password', 'new-password', 'one-time-code', 'email'].includes((e.getAttribute('autocomplete') || '').toLowerCase())) return false;
    return e.dataset.bwignore === undefined;
  }).map(e => e.id || e.name || e.className).slice(0, 8));
  ok(loud.length === 0, `every field that is not a password or an account tells password managers to stay away (${JSON.stringify(loud)})`);
  // B533: Bitwarden honors data-bwignore only when its user opts in, and
  // reads one textarea that names a public key as an add-an-SSH-key form,
  // then offers itself on every field labeled name, title or description.
  // So no textarea on the page may read as one, by Bitwarden's own words.
  const sshy = await page.$$eval('textarea', es => es.filter(e => {
    // Each attribute is split on its own, as Bitwarden does: whole, by
    // word, and by word with the spaces taken out ("public key" is publickey).
    const said = [e.id, e.name, e.className, e.title, e.placeholder,
                  e.getAttribute('aria-label'), ...[...(e.labels || [])].map(l => l.textContent)]
      .filter(Boolean).map(v => v.toLowerCase().replace(/-/g, ''));
    const words = new Set(said.flatMap(v => [v, ...v.split(/[^\p{L}\d]+/u),
                                             ...v.replace(/\s/g, '').split(/[^\p{L}\d]+/u)]));
    return ['publickey', 'sshkey'].some(w => words.has(w))
      || said.some(v => /ssh(rsa|ed25519|dss)|ecdsasha2/.test(v));
  }).map(e => e.id || e.className));
  ok(sshy.length === 0, `...and no text box reads to Bitwarden as an SSH public key (${JSON.stringify(sshy)})`);
}
{
  // The header's buttons are one box (the operator, 5 Oct): the bell stood
  // taller and wider than the bug, gear and sign-out beside it on a desk.
  const hb = await page.$$eval('header > button', bs => bs.filter(b => b.offsetParent).map(b => {
    const r = b.getBoundingClientRect();
    return { id: b.id, h: Math.round(r.height), w: Math.round(r.width) };
  }));
  const icons = hb.filter(b => b.id !== 'bAbout');
  ok(new Set(hb.map(b => b.h)).size === 1 && new Set(icons.map(b => b.w)).size === 1,
     `the header's buttons share one height, and its icon buttons one width (${JSON.stringify(hb)})`);
}
ok(seenReds.size <= 1,
   `a verb that cannot be undone is the same color everywhere (${JSON.stringify([...seenReds])})`);

// The fence inside the one page: a renderer that throws must break its own
// tab and nothing else: before renderGuarded, one bug in one kind's render
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
  // The page is still a page: another kind renders, the strip answers. The
  // Docker tab opened early in this file may have left the strip by now
  // (one more document kind, the Roles tab, pushed it out, 5 Oct), so it is
  // opened again where it is gone, and its picker waited for.
  await page.evaluate(() => {
    const t = tabs.find(x => x.kind === 'docker');
    if (t) focusTab(t.id); else openDocker();
  });
  const alive = await page.waitForSelector('.dmtab .dmpick', { timeout: 15000 }).then(() => true, () => false);
  ok(alive, '...and the rest of the dashboard keeps working around it');
  ok(page.errors.length > errsBefore
     && /boom \(deliberate\)/.test(page.errors[page.errors.length - 1]),
     '...while the error still reaches the console, so a caught bug is not a hidden one');
  // Deliberate, asserted, and now removed: the final zero-errors check below
  // is about bugs this suite did not cause on purpose.
  page.errors.length = errsBefore;
  await page.evaluate(() => {
    TABKINDS.findings.render = window.__realFxRender;
    delete window.__realFxRender;
    fxRev++; drawPanes();
  });
  await page.waitForSelector('.fxtab .rule', { timeout: 8000 }).catch(() => {});
}

// A stacked box may not be aligned across its own axis, on every tab, at
// DESKTOP width, which is where it shows.
//
// align-items on a COLUMN flex box is the horizontal axis, so a rule written
// for a line of controls pushes a stacked one to an edge. That is what the
// Settings tab was: three sections in the right third of the surface, each
// starting at a different x, with six hundred pixels of nothing beside them,
// because `.row:has(.setrow){align-items:flex-end}` also matched
// `.row.stack2`. Cheap to measure, and the operator found it rather than
// this suite, which is the reason it is here.
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await bring(kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 }).catch(() => {});
  await sleep(200);
  const skewed = await page.evaluate(() => {
    const surf = document.querySelector('.doc.on .doctab, .doc.on .nb');
    if (!surf) return [];
    const out = [];
    surf.querySelectorAll('.row, .sect, .field, .doclist > *').forEach(e => {
      const cs = getComputedStyle(e);
      if (cs.display !== 'flex' || cs.flexDirection !== 'column') return;
      if (['flex-end', 'end', 'center', 'right'].includes(cs.alignItems))
        out.push(`${e.className || e.tagName} is a column aligned ${cs.alignItems}`);
    });
    return [...new Set(out)].slice(0, 4);
  });
  ok(skewed.length === 0, `[${kind}] no stacked box is aligned across its own axis${
    skewed.length ? `: ${skewed.join('; ')}` : ''}`);
}

// ---- what reads on a filled accent surface, on every scheme -----------------
// Seven places put --ink on --accent-deep: the active tab, a primary button,
// a button that is on, a view bar's current tab, the mobile bar's, an open
// select's chosen row, and the text selection. Twelve schemes swap the accent
// under all of them, and five of those accents were bright enough that the
// text on the fill came out under AA, nostromo worst at 3.56:1, which is the
// one somebody noticed. The active tab is measured because it had BOTH
// failures: the fill was too light, and its name is a `.lbl`, the same class
// as the quiet field-label helper, so it wore that color on top.
//
// Read off the rendered pixels through a canvas rather than computed from the
// tokens: --accent-deep is a relative color now, and the point is what the
// engine actually paints.
{
  const SCHEMES = ['default', 'nostromo', 'slate', 'carbon', 'nocturne', 'moss',
                   'ember', 'abyss', 'plum', 'rust', 'ice', 'sepia', 'ash'];
  const AA = 4.5;
  const bad = [];
  for (const t of SCHEMES) {
    await page.evaluate(th => { document.documentElement.dataset.theme = th; }, t);
    await sleep(120);
    const r = await page.evaluate(() => {
      const el = document.querySelector('.tab.on');
      if (!el) return { err: 'no active tab' };
      const c = document.createElement('canvas'); c.width = c.height = 1;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      const px = v => { ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 1, 1);
                        ctx.fillStyle = v; ctx.fillRect(0, 0, 1, 1);
                        const d = ctx.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2]]; };
      const lin = x => { x /= 255; return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); };
      const lum = a => 0.2126 * lin(a[0]) + 0.7152 * lin(a[1]) + 0.0722 * lin(a[2]);
      const R = (a, b) => { const x = lum(px(a)), y = lum(px(b));
                            const h = Math.max(x, y), l = Math.min(x, y); return (h + 0.05) / (l + 0.05); };
      const bg = getComputedStyle(el).backgroundColor;
      const at = sel => { const k = el.querySelector(sel);
                          return k ? +R(getComputedStyle(k).color, bg).toFixed(2) : null; };
      return { label: at('.lbl'), icon: at('.ic') };
    });
    if (r.err) { bad.push(`${t}: ${r.err}`); continue; }
    if (!(r.label >= AA)) bad.push(`${t} label ${r.label}`);
    if (r.icon !== null && !(r.icon >= AA)) bad.push(`${t} icons ${r.icon}`);
  }
  await page.evaluate(() => { delete document.documentElement.dataset.theme; });
  await sleep(120);
  ok(bad.length === 0,
     `the active tab's words read on the accent fill in all ${SCHEMES.length} schemes${
       bad.length ? `; under ${AA}:1: ${bad.join(', ')}` : ''}`);
}

// ---- a document arrives on its own ground, on every scheme ------------------
// A document tab brought to the front fades in (docIn), and the fade was
// on the document box, which painted its own ground: the ground faded in
// with the content, over the pane's black, so every switch to a notebook
// opened on a black pane for its first frames, and nostromo's on the bare
// hull (the operator, 27 Sep). The ground is the stack's now. Measured on
// the first frame itself: whatever the switch starts is held at its start,
// the pane is photographed and its pixels read through a canvas, and that
// frame has to be the ground the settled tab stands on (its commonest
// color) with no black in it. Every kind in one scheme, the notebook in
// every scheme, the schemes read off the page's own list.
{
  const frame = async () => {
    const box = await page.$eval('.pane .doc.on', e => {
      const r = e.closest('.stack').getBoundingClientRect();
      return { x: r.x, y: r.y, width: r.width, height: r.height };
    });
    const png = await page.screenshot({ clip: box });
    return page.evaluate(async b64 => {
      const img = new Image();
      img.src = 'data:image/png;base64,' + b64;
      await img.decode();
      const c = document.createElement('canvas');
      c.width = img.width; c.height = img.height;
      const g = c.getContext('2d', { willReadFrequently: true });
      g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, c.width, c.height).data;
      let black = 0, n = 0; const count = new Map();
      // Every fourth pixel each way: the ground is most of the pane.
      for (let y = 0; y < c.height; y += 4) for (let x = 0; x < c.width; x += 4){
        const i = (y * c.width + x) * 4; n++;
        if (d[i] < 4 && d[i + 1] < 4 && d[i + 2] < 4) black++;
        const k = (d[i] << 16) | (d[i + 1] << 8) | d[i + 2];
        count.set(k, (count.get(k) || 0) + 1);
      }
      let mode = 0, most = 0;
      for (const [k, m] of count) if (m > most){ most = m; mode = k; }
      return { black: +(black / n).toFixed(3), ground: [mode >> 16, (mode >> 8) & 255, mode & 255] };
    }, png.toString('base64'));
  };
  const atRest = () => page.waitForFunction(() => !document.querySelector('.pane .doc.on')?.getAnimations().length,
                                          null, { timeout: 10000 });
  // The switch and the hold in one task, so no frame is painted between them.
  const switchHeld = id => page.evaluate(id => {
    focusTab(id);
    window.__held = document.getAnimations().filter(a => a.playState === 'running' || a.pending);
    window.__held.forEach(a => { a.pause(); a.currentTime = 0; });
    return window.__held.map(a => a.animationName || '').filter(Boolean);
  }, id);
  const release = () => page.evaluate(() => { (window.__held || []).forEach(a => a.play()); window.__held = []; });
  const tabIdOf = kind => page.evaluate(k => tabs.find(t => t.kind === k)?.id, kind);
  // Only the two document tabs switched between: bring() makes room under
  // the page's tab ceiling by closing one, and the one it closed could be
  // the tab about to be switched to, which then never arrived.
  const onlyDocs = keep => page.evaluate(keep => {
    for (const t of [...tabs]) if (t.kind !== 'term' && !keep.includes(t.kind)) dropTab(t.id);
  }, keep);
  const arrive = async (kind, from) => {
    await onlyDocs([kind, from.split(':')[0]]);
    await bring(kind);
    await bring(from);
    await atRest();
    const id = await tabIdOf(kind);
    if (!id) return { ok: false, said: `no ${kind} tab to switch to` };
    const held = await switchHeld(id);
    const first = await frame();
    await release();
    await atRest();
    await sleep(150);
    const settled = await frame();
    const off = first.ground.some((v, i) => Math.abs(v - settled.ground[i]) > 2);
    return { ok: first.black < 0.005 && !off && held.includes('docIn'),
             said: `first frame ${first.black * 100}% black on rgb(${first.ground}), settled on rgb(${settled.ground}); ${
                   held.includes('docIn') ? 'faded' : 'nothing faded'}` };
  };
  for (const kind of tabKinds){
    if (!DRIVERS[kind]) continue;
    const r = await arrive(kind, kind === 'projects' ? 'notebook:roadmap' : 'projects');
    ok(r.ok, `[${kind}] brought to the front, its first frame is its own ground and only its content fades in (${r.said})`);
  }
  const schemes = await page.evaluate(() => THEMES.map(t => t[0]));
  const bad = [];
  for (const t of schemes){
    await page.evaluate(th => { document.documentElement.dataset.theme = th; }, t);
    await sleep(120);
    const r = await arrive('notebook', 'projects');
    if (!r.ok) bad.push(`${t}: ${r.said}`);
  }
  await page.evaluate(() => { delete document.documentElement.dataset.theme; });
  await sleep(120);
  ok(schemes.length > 1 && bad.length === 0,
     `a notebook brought to the front opens on its scheme's ground in all ${schemes.length} schemes, never black${
       bad.length ? `: ${bad.join('; ')}` : ''}`);
}

// The same page, held to the same rules at phone width: nothing may scroll
// the page sideways, and every text control is 16px so iOS does not zoom a
// layout that cannot zoom back.
// A modal leaves the way it arrived. The arrival is the stylesheet's; the
// leaving is one observer on the hidden attribute, so this is what proves
// every dialog on the page, including one added later, goes out with it.
{
  await page.click('#bAbout');
  await page.waitForSelector('#aboutModal:not([hidden])');
  const left = await animatedDuring(page, async () => {
    await page.click('#aboutModal >> text=Close');
    await page.waitForSelector('#aboutModal', { state: 'hidden' });
  });
  ok(left.some(k => /aboutModal/.test(k)),
     `a modal leaves with a tween rather than vanishing (${left.join(', ') || 'nothing animated'})`);
}
await page.setViewportSize({ width: 393, height: 851 });
// A row folding its controls out on a phone slides over the height that
// takes; six buttons appearing under a name in one frame is a jump the eye
// has to find.
{
  await page.click('#projects');
  await page.waitForSelector('#projects .row .rowmore', { timeout: 10000 });
  const unfolded = await animatedDuring(page, async () => {
    await page.click('#projects .row .rowmore');
    await page.waitForSelector('#projects .row.moreon', { timeout: 5000 });
  });
  ok(unfolded.some(k => /\brow\b/.test(k) || /projects/.test(k)),
     `a project row's controls unfold with a slide on a phone (${unfolded.join(', ') || 'nothing animated'})`);
  await page.click('#projects .row.moreon .rowmore');
}
await page.evaluate(() => setView('terminal'));
await sleep(400);
// The same width rule at phone width, on every tab: the cap is min(--ctl-w,
// 88%), and 88% is what bites here.
//
// A phone starts every fold shut, and a control inside a shut fold has no
// line to be measured on. Opened the way a person's press leaves them, which
// is recorded as well as open, so a redraw between here and the measuring
// does not shut them again. (These used to arrive open by accident: the page
// recorded the desktop's default as a choice, and carried it down here.)
const unfold = () => page.evaluate(() => {
  document.querySelectorAll('.doc.on details[data-sect]').forEach(d => {
    sectOpen[d.dataset.sect] = true; d.open = true; });
});
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await bring(kind);
  await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
  await unfold();
  const S = await spanning();
  ok(!S.err && S.wide.length === 0,
     `[${kind}] no control or row of controls spans the tab at phone width${
       S.err ? ` (${S.err})` : S.wide.length ? `: ${S.wide.join(', ')}` : ''}`);
  await sleep(250);
  const L = await lineup();
  ok(!L.err && L.off.length === 0,
     `[${kind}] every control on a line ends at the same height at phone width${
       L.err ? ` (${L.err})` : L.off.length ? `: ${L.off.join('; ')}` : ''}`);
  ok(!L.err && L.sizes.length === 0,
     `[${kind}] every control on a line is one height at phone width${
       L.err ? ` (${L.err})` : L.sizes.length ? `: ${L.sizes.join('; ')}` : ''}`);
  const W = await unwrapped();
  ok(!W.err && W.tall.length === 0,
     `[${kind}] every select is one line high at phone width${
       W.err ? ` (${W.err})` : W.tall.length ? `; wrapped: ${W.tall.join(', ')}` : ''}`);
  // A sentence is a proseline, not an input. An <input> shows about thirty
  // characters at this width, so a 300-character bug title was a field you
  // could not read what you were editing in. The threshold is the length: a
  // name is 100, a branch is 120, and anything longer than that is prose.
  const P = await page.evaluate(() => {
    const host = document.querySelector('.doc.on');
    const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div');
    if (!box) return { err: 'no document box found' };
    const bad = [...box.querySelectorAll('input[maxlength]')]
      .filter(e => Number(e.getAttribute('maxlength')) > 120)
      .map(e => `${e.id || e.className.split(' ')[0] || 'input'}=${e.getAttribute('maxlength')}`);
    const grew = [...box.querySelectorAll('textarea.proseline')]
      .filter(e => e.offsetHeight > 0 && e.scrollHeight > e.clientHeight + 2)
      .map(e => e.id || e.className.split(' ')[0] || 'proseline');
    return { bad, grew };
  });
  ok(!P.err && P.bad.length === 0,
     `[${kind}] a sentence is a proseline, not an input${
       P.err ? ` (${P.err})` : P.bad.length ? `: ${P.bad.join(', ')}` : ''}`);
  ok(!P.err && P.grew.length === 0,
     `[${kind}] every proseline shows all of itself rather than scrolling inside${
       P.grew.length ? `: ${P.grew.join(', ')}` : ''}`);
}
// ---- a list of choices is alphabetical -----------------------------------
// Each of these was in the order somebody wrote it in. The exceptions are
// named rather than discovered: Default leads the schemes, and the catch-all
// trails the git hosts.
{
  const lists = await page.evaluate(async () => {
    const out = {};
    out.themes = THEMES.map(t => t[1]);
    out.tools = [...document.querySelectorAll('.card[data-card="tools"] .macros button')]
      .map(b => b.textContent.trim());
    out.admin = [...document.querySelectorAll('.card[data-card="admin"] .macros button')]
      .map(b => b.textContent.trim());
    // Both catalogs ride along with something else rather than costing a
    // fetch of their own: the forge list with the deploy keys the same dialog
    // wants, the hypervisors with the template the VM dialog renders.
    const f = await (await fetch('/api/pubkeys')).json().catch(() => null);
    out.forges = (f?.forges || []).map(x => x.name);
    const v = await (await fetch('/api/v1/nodes', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'vm-xml' }) })).json().catch(() => null);
    out.hypervisors = (v?.catalog || []).map(x => x.label);
    return out;
  });
  const sorted = (xs, { head = 0, tail = 0 } = {}) => {
    const mid = xs.slice(head, xs.length - tail);
    return mid.join('|') === [...mid].sort((a, b) =>
      a.toLowerCase().localeCompare(b.toLowerCase())).join('|');
  };
  ok(lists.themes.length > 3 && lists.themes[0] === 'Default'
     && sorted(lists.themes, { head: 1 }),
     `the color schemes are alphabetical after Default (${lists.themes.join(', ')})`);
  ok(sorted(lists.tools) && sorted(lists.admin),
     `the Tools and Administration cards are alphabetical (${lists.tools.join(', ')})`);
  if (lists.forges.length)
    ok(sorted(lists.forges, { tail: 1 })
       && lists.forges[lists.forges.length - 1] === 'Another git host',
       `the git hosts are alphabetical, with the catch-all last (${lists.forges.join(', ')})`);
  if (lists.hypervisors.length)
    ok(sorted(lists.hypervisors),
       `the hypervisors are alphabetical (${lists.hypervisors.join(', ')})`);
}

// The Tests view needs rows to be measured on, and one of them a continuation
// (a "..." name whose "follows:" line is drawn under it), because that line
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
// the one thing allowed past the edge: it scrolls by design.
const sideways = () => page.evaluate(() => {
  const host = document.querySelector('.doc.on');
  const box = host?.querySelector(':scope > .doctab, :scope > .nb, :scope > div') || host;
  const controls = [...(host?.querySelectorAll('input, select, textarea') || [])]
    .filter(e => e.offsetHeight > 0)
    .filter(e => !['checkbox', 'radio'].includes(e.type));
  const edge = (box?.getBoundingClientRect().right || document.documentElement.clientWidth) + 1;
  let widest = null;
  // Inside a box that scrolls sideways by design (a diff's pre), what is
  // wide is that box's to scroll, never the page's: all sections stand open
  // on a phone since 8 Oct, so a diff is measured there now.
  const scrolls = e => {
    for (let a = e.parentElement; a && a !== box; a = a.parentElement)
      if (/(auto|scroll)/.test(getComputedStyle(a).overflowX)
          && a.getBoundingClientRect().right <= edge) return true;
    return false;
  };
  for (const e of box?.querySelectorAll('*') || []){
    if (e.closest('.nbtabs')) continue;
    if (scrolls(e)) continue;
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
                   + (row ? `; row: ${row.outerHTML.replace(/\s+/g, ' ').slice(0, 700)}` : '') };
    }
  }
  return {
    overflow: Math.max(document.documentElement.scrollWidth - document.documentElement.clientWidth,
                       box ? box.scrollWidth - box.clientWidth : 0),
    widest,
    // Every control on a phone is the field size (--f-field, 11px mono): a 16px mono
    // field beside an 11px label is the loudest thing on the tab, and the
    // operator asked for smaller text in every box (25 Sep). The 16px that
    // stops iOS Safari zooming the page into a typed field is iOS's alone,
    // under @supports (-webkit-touch-callout: none), a property only it
    // has, so this browser never sees it and this measures the rule for
    // everything else: nothing inflated, pickers included.
    loud: controls.filter(e => parseFloat(getComputedStyle(e).fontSize) >= 16)
      .map(e => e.id || e.className || e.tagName),
  };
});
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await bring(kind);
  await sleep(250);
  // The notebook is six views behind one tab, and each has its own layout;
  // the Tests view is the one that scrolled sideways while the Roadmap, the
  // one this check used to look at, did not.
  // (Every view is a kind of its own now, so this loop meets each once.)
  const views = [''];
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
    ok(m.loud.length === 0, `[${tag}] no control on a phone is inflated past the field size${
      m.loud.length ? `; inflated: ${m.loud.join(', ')}` : ''}`);
  }
}

// ---- the document and the framework are one thing ---------------------------
// docs/design-language.md is what a session reads; this suite is what holds
// the page. The two drift apart the day a helper is renamed and the document
// still names the old one, so every name the document uses is checked to be
// real on the page, and every helper the framework exposes is checked to be
// in the document: a rename without a rewrite fails here by name.
{
  const { readFileSync } = await import('node:fs');
  const { fileURLToPath } = await import('node:url');
  const { dirname, join } = await import('node:path');
  const doc = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', 'docs', 'design-language.md'), 'utf8');
  const helpers = ['docSurface', 'docSection', 'renderGuarded', 'busy'];
  const missing = helpers.filter(h => !doc.includes(h));
  ok(missing.length === 0,
     `the design language names every helper the framework exposes${missing.length ? `; not: ${missing.join(', ')}` : ''}`);
  const named = [...doc.matchAll(/`(docSurface|docSection|renderGuarded|busy|wireSections)\b/g)].map(m => m[1]);
  const unreal = await page.evaluate(ns => ns.filter(n => typeof window[n] !== 'function'), [...new Set(named)]);
  ok(unreal.length === 0,
     `...and every helper the document names is a real function on the page${unreal.length ? `; not: ${unreal.join(', ')}` : ''}`);
  // By name, with or without the dot: the document writes a class as it
  // appears in markup as often as as a selector.
  const classes = ['actbar', 'field', 'histbar', 'danger', 'state', 'foot', 'modal', 'ndcap', 'setrow', 'prose'];
  const undocumented = classes.filter(c => !new RegExp(`\\b${c}\\b`).test(doc));
  ok(undocumented.length === 0,
     `...and names the classes the page is measured on${undocumented.length ? `; not: ${undocumented.join(', ')}` : ''}`);
}

// ---- a quiet page is quiet, and a tab opens once (R75 step 4) -------------
// What the page asks the server for is measured, not assumed: the phone's
// device probe filled the Jobs tab for weeks, and the Docker tab asked for
// its listing three times per press, and nothing counted either. With
// nothing happening the page issues its two polls and nothing else, and
// opening a tab asks each endpoint at most once, whichever kind it is. The
// polls, the layout save an open makes, and the node list a picker fills
// are the allowed noise.
{
  const POLLS = new Set(['/api/status', '/api/revs', '/api/presence', '/api/layout', '/api/v1/nodes', '/api/live']);
  await page.evaluate(() => { for (const t of [...tabs]) if (t.kind !== 'term') dropTab(t.id); });
  await page.evaluate(() => { window.__f = {}; const f = window.fetch;
    window.fetch = (...a) => { const u = String(a[0]).split('?')[0]; window.__f[u] = (window.__f[u] || 0) + 1; return f(...a); }; });
  await sleep(8000);
  const idle = await page.evaluate(() => window.__f);
  const noise = Object.keys(idle).filter(u => !POLLS.has(u));
  ok(noise.length === 0, `an idle page asks only its polls (${noise.length ? 'also ' + noise.join(', ') : Object.keys(idle).join(', ')})`);
  for (const kind of Object.keys(DRIVERS)){
    if (kind.startsWith('notebook:')) continue;
    await page.evaluate(() => { window.__f = {}; });
    // Attached, not visible: the count is about requests, and a tab that
    // opens behind a switch on a narrow page has still asked for its data.
    // The driver's own way in first; a tab whose button is ghosted right now
    // (Analysis with nothing to analyze) is opened the way a restored layout
    // opens it, since the count is about the open path and not the button.
    let came = true;
    try {
      await DRIVERS[kind].open();
      if (!await page.evaluate(k => tabs.some(t => t.kind === k), kind))
        await page.evaluate(k => openTab({ kind: k, arg: '__' + k, label: k }), kind);
      await page.waitForFunction(k => tabs.some(t => t.kind === k), kind, { timeout: 10000 });
    } catch (e) { came = false; }
    await sleep(1200);
    const f = await page.evaluate(() => window.__f);
    if (!came){ ok(false, `[${kind}] opened for the request count (did not come up: ${Object.keys(f).join(', ') || 'no fetch at all'})`); }
    const twice = Object.entries(f).filter(([u, n]) => !POLLS.has(u) && n > 1);
    ok(twice.length === 0, `[${kind}] opening asks each endpoint once (${twice.length ? twice.map(([u, n]) => `${u} x${n}`).join(', ') : Object.keys(f).filter(u => !POLLS.has(u)).join(', ') || 'nothing'})`);
    // ...and closed again, so the tab cap never refuses the next one.
    await page.evaluate(k => { for (const t of [...tabs]) if (t.kind === k) dropTab(t.id); }, kind);
  }
  await page.evaluate(() => { for (const t of [...tabs]) if (t.kind !== 'term') dropTab(t.id); });
}

// ---- a fold lasts for the page, and a reload starts it from the default ---
// Open state is kept while the page lives and never stored (the design
// language, Sections): closed by hand on a desktop, where the default is
// open, it stays closed through the repaints and is open again after a
// reload. Measured on the Nodes tab's Health section: a fixed section
// rather than the first one found, because a tab that is still filling in
// (the Docker manager redraws as its rows land) replaces the element
// between the find and the close, and a close on a detached fold records
// nothing, which read as the rule failing when only the sample had moved.
{
  const kind = 'nodes', key = 'nodes:health';
  const sel = `.doc.on details.sect[data-sect="${key}"]`;
  // Opened if it is not there: the request-count block above closes every
  // tab, and whether one came back before this ran depended on the layout
  // poll, which is the whole of B219.
  const focus = async () => {
    const had = await page.evaluate(k => { const t = tabs.find(x => x.kind === k);
                                           if (t) focusTab(t.id); return !!t; }, kind);
    if (!had) await DRIVERS[kind].open();
    await page.waitForSelector(DRIVERS[kind].readyWhen, { timeout: 20000 });
    await page.waitForSelector(sel, { timeout: 20000 });
  };
  await focus();
  ok(await page.$eval(sel, d => d.open), `[${kind}] a section opens by default on a desktop (${key})`);
  // A press on the summary, not `open = false`: only a fold somebody pressed
  // is recorded, so that markup arriving open is never mistaken for a choice.
  await page.click(sel + ' > summary');
  await page.waitForFunction(k => sectOpen[k] === false, key, { timeout: 5000 });
  ok(true, `[${kind}] a fold closed by hand stays closed for the page (${key})`);
  await page.reload(); await ready(page);
  await focus();
  ok(await page.$eval(sel, d => d.open),
     `[${kind}] ...and a reload starts it from its default, open on a desktop`);
}

// ---- hidden means hidden (design language, Sections and action bars) -----
// Every element carrying the attribute is out of the layout, whatever class
// it wears. A class with a display once beat it: a fold that never closed.
{
  const shown = await page.evaluate(() => [...document.querySelectorAll('[hidden]')]
    .filter(e => getComputedStyle(e).display !== 'none')
    .map(e => e.id || e.className || e.tagName).slice(0, 5));
  ok(shown.length === 0, `nothing carrying hidden is displayed${shown.length ? ': ' + shown.join(', ') : ''}`);
}

// ---- dialogs (design language, Dialogs) -----------------------------------
// Opened one by one, and each held to the shape every dialog shares: its
// lines in .field bands (text at box level draws flush against the edge),
// groups headed by a label and never an h4, and the buttons in a .foot.
// Discovered, like the tab kinds: every .modal in the page must be opened by
// a driver here, so a new dialog with none FAILS by its id, which is the
// price of adding one.
const DIALOGS = {
  about: () => openAbout(), newproject: () => openNewProject(), trash: () => openTrash(),
  pending: () => openPending('alpha'), report: () => openReport('alpha'),
  phonelend: () => openPhoneLend('alpha'),
  newcontainer: () => openNewContainer(), custom: () => editCustom(),
  // A new project's first session: opened for a project with no brief, which
  // draws the same dialog with an empty text box.
  firstsession: () => openBrief('alpha', ''),
  senddocker: () => openSendToDocker('ep.silon'), devenv: () => openDevEnv('ep.silon', 'main'),
  relocate: () => openRelocate('ep.silon', 'main'),
  projsettings: () => renameProject('alpha'),
  // The Debugging group's dialog. It draws from SETTING_GROUPS rather than
  // from what is on screen, so it opens whether or not the Settings tab is
  // the one showing, and debug mode decides the BUTTON rather than this.
  setdebug: () => openDebugSettings(),
  // One container's log. The stub daemon answers, so the dialog draws its
  // real shape rather than an error band.
  dockerlog: async () => { openDocker(); await new Promise(r => setTimeout(r, 1200));
                           dmLogs('someone-elses'); },
  enroll: async () => { openNodesTab();
    for (let i = 0; i < 40 && !document.querySelector('.nodestab button'); i++) await new Promise(r => setTimeout(r, 250));
    [...document.querySelectorAll('.nodestab button')].find(b => /enroll/i.test(b.textContent))?.click(); },
};
const opened = new Set();
async function dialogShape(pg = page){
  return pg.evaluate(() => {
    const m = [...document.querySelectorAll('.modal')].find(x => !x.hidden);
    if (!m) return { err: 'no dialog opened' };
    const box = m.querySelector('.box');
    const loose = [...box.querySelectorAll('*')].filter(e => {
      // A section's heading is a heading, as the h3 is: a long dialog's
      // groups are sections (the project settings, 7 Oct).
      if (e.offsetHeight === 0 || e.closest('h3, .field, .foot, details.sect > summary')) return false;
      return [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    }).map(e => `${e.tagName.toLowerCase()} "${e.textContent.trim().slice(0, 24)}"`);
    // One scroller, not two: a box that scrolls around a part that scrolls
    // too is the half-a-line wobble About had on every size (18 Sep).
    const scrolls = e => e.scrollHeight > e.clientHeight + 1;
    // A text box scrolling its own text is an editor doing its job, not a
    // second scroller in the dialog's layout; so is a listbox scrolling its
    // rows past four (the design language, Controls), which is what keeps
    // a dialog of forty projects short.
    const inner = [...box.querySelectorAll('*')].filter(e => e.offsetHeight && scrolls(e)
      && e.tagName !== 'TEXTAREA' && !e.classList.contains('lbox') && /auto|scroll/.test(getComputedStyle(e).overflowY));
    const nested = scrolls(box) && inner.length
      ? `the box scrolls ${box.scrollHeight - box.clientHeight}px around ${inner[0].id || inner[0].className || inner[0].tagName}, which scrolls too` : '';
    // A dialog of prose (About) may have headings; one of fields may not.
    return { nested, loose: loose.slice(0, 3), h4: box.classList.contains('prose') ? 0 : box.querySelectorAll('h4').length,
             foot: !!box.querySelector('.foot') && box.querySelector('.foot').offsetHeight > 0 };
  });
}
for (const [name, open] of Object.entries(DIALOGS)) {
  await page.evaluate(open);
  const seen = await page.waitForFunction(() => [...document.querySelectorAll('.modal')].some(m => !m.hidden),
    null, { timeout: 10000 }).then(() => true).catch(() => false);
  await sleep(600);
  const d = seen ? await dialogShape() : { err: 'nothing opened' };
  const id = await page.evaluate(() => [...document.querySelectorAll('.modal')].find(m => !m.hidden)?.id || '');
  if (id) opened.add(id);
  ok(!d.err && d.loose.length === 0 && d.h4 === 0 && d.foot,
     `[dialog ${name}] its lines in .field bands, no h4, buttons in a .foot${
       d.err ? ` (${d.err})` : d.loose.length ? `: loose ${d.loose.join(', ')}` : d.h4 ? `: ${d.h4} h4` : !d.foot ? ': no foot' : ''}`);
  ok(!d.nested, `[dialog ${name}] scrolls in one place${d.nested ? `: ${d.nested}` : ''}`);
  // One rhythm down a form. The sandbox VM dialog measured 0, 0, 10, 10, 0
  // between its fields, because a .prefrow carried a gap and the band's own
  // stacked children carried none, so one form read as three depending on
  // which container a field landed in. The token is --field-gap.
  const rhythm = await page.evaluate(() => {
    const m = [...document.querySelectorAll('.modal')].find(x => !x.hidden);
    const box = m?.querySelector('.box');
    if (!box) return { err: 'no dialog' };
    const css = getComputedStyle(document.documentElement);
    const want = Math.round(parseFloat(css.getPropertyValue('--field-gap')) || 10);
    // A label and the control under it are one thing, so they sit closer.
    const tight = Math.round(parseFloat(css.getPropertyValue('--label-gap')) || 5);
    // Within ONE band, never across two: the gap between bands is their
    // padding twice over and is the band's business, not the form's.
    const odd = [];
    for (const parent of box.querySelectorAll('.field, .field .prefrow')) {
      const rows = [...parent.children].filter(e => e.offsetHeight);
      for (let i = 1; i < rows.length; i++) {
        const a = rows[i - 1].getBoundingClientRect(), b = rows[i].getBoundingClientRect();
        if (b.top < a.bottom - 1) continue;            // side by side, not stacked
        const gap = Math.round(b.top - a.bottom);
        const expect = rows[i - 1].tagName === 'LABEL' ? tight : want;
        if (Math.abs(gap - expect) > 1)
          odd.push(`${gap}px (wanted ${expect}) before ${
            rows[i].className || rows[i].tagName.toLowerCase()}`);
      }
    }
    return { want, tight, odd };
  });
  // A dialog holds the page still. Its overlay is the scroller when the box
  // is taller than the screen, and without these two the flick that reaches
  // the end of a dialog carries on into the page behind it, which is what
  // the operator saw on a phone: the whole page moving under the box.
  const still = await page.evaluate(() => {
    const m = [...document.querySelectorAll('.modal')].find(x => !x.hidden);
    if (!m) return { err: 'no dialog' };
    return { chain: getComputedStyle(m).overscrollBehaviorY,
             locked: getComputedStyle(document.documentElement).overflow };
  });
  ok(!still.err && still.chain === 'contain' && still.locked === 'hidden',
     `[dialog ${name}] holds the page still behind it (overscroll ${still.chain}, page ${still.locked})`);
  ok(!rhythm.err && rhythm.odd.length === 0,
     `[dialog ${name}] one rhythm down the band (${rhythm.want}px, ${rhythm.tight}px under a label)${
       rhythm.err ? ` (${rhythm.err})` : rhythm.odd.length ? `: ${rhythm.odd.join('; ')}` : ''}`);
  await page.evaluate(() => document.querySelectorAll('.modal').forEach(m => { m.hidden = true; }));
}
// ...and again on a small phone, where the room runs out first: every dialog
// still scrolls in one place.
{
  const phone = await newPage(browser, { viewport: { width: 360, height: 740 }, isMobile: true, hasTouch: true });
  await phone.goto(URL); await ready(phone);
  const twice = [];
  for (const [name, open] of Object.entries(DIALOGS)) {
    await phone.evaluate(open);
    await phone.waitForFunction(() => [...document.querySelectorAll('.modal')].some(m => !m.hidden),
      null, { timeout: 10000 }).catch(() => {});
    await sleep(600);
    const d = await dialogShape(phone);
    if (d.nested) twice.push(`${name}: ${d.nested}`);
    await phone.evaluate(() => document.querySelectorAll('.modal').forEach(m => { m.hidden = true; }));
  }
  ok(twice.length === 0, `on a 360px phone every dialog scrolls in one place${twice.length ? ': ' + twice.join(' | ') : ''}`);
  await phone.close();
}
{
  const all = await page.evaluate(() => [...document.querySelectorAll('.modal[id]')].map(m => m.id));
  const undriven = all.filter(x => !opened.has(x));
  ok(undriven.length === 0, `every dialog in the page is measured${undriven.length
    ? `: no driver opens ${undriven.join(', ')} (add one to DIALOGS in uniform.mjs)` : ''}`);
}

// ---- a finger, not a pointer (design language, Both sizes) ---------------
// On a touch phone the controls a thumb meets are a thumb's size, and a bar
// that spans the screen fits it even on a fold's 344px cover.
{
  const phone = await newPage(browser, { viewport: { width: 375, height: 667 }, isMobile: true, hasTouch: true });
  await phone.goto(URL); await ready(phone);
  await phone.evaluate(() => { openNotebook('alpha', 'roadmap'); setView('terminal'); });
  await phone.waitForSelector('.nb .nbview:not([hidden])', { timeout: 20000 });
  await sleep(600);
  const small = await phone.evaluate(() => [...document.querySelectorAll(
      '.tabbar .tab .ic, .tabbar .newtab, .nb button, .mobar button')]
    .filter(e => e.offsetHeight > 0)
    .filter(e => { const r = e.getBoundingClientRect(); return r.height < 30 || r.width < 30; })
    .map(e => `${e.className || e.tagName} "${e.textContent.trim().slice(0, 12)}" ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`));
  ok(small.length === 0, `on a touch phone the tab strip, the notebook and the bar are a thumb's size${small.length ? ': ' + small.slice(0, 4).join(', ') : ''}`);
  await phone.evaluate(() => openNewProject());
  await phone.waitForSelector('.modal:not([hidden]) .foot button', { timeout: 10000 });
  const shortFoot = await phone.$$eval('.modal:not([hidden]) .foot button', bs => bs.filter(b => b.getBoundingClientRect().height < 36).length);
  ok(shortFoot === 0, `...and a dialog's buttons are the tap height (${shortFoot} short)`);
  await phone.setViewportSize({ width: 344, height: 882 });
  await phone.evaluate(() => document.querySelectorAll('.modal').forEach(m => { m.hidden = true; }));
  await sleep(400);
  const cut = await phone.evaluate(() => [...document.querySelectorAll('.mobar button')]
    .filter(b => b.offsetHeight > 0 && b.getBoundingClientRect().right > innerWidth + 1).map(b => b.textContent.trim()));
  ok(cut.length === 0, `...and the bar fits a fold's 344px cover${cut.length ? `: cut off ${cut.join(', ')}` : ''}`);
  await phone.context().close();
}

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
