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
import { URL, launch, newPage, ok, done, ready, sleep } from './lib.mjs';

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
              '.macros, .fxproj, .pkghead, .pkg';
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
    return {
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
for (const kind of kinds){
  if (!DRIVERS[kind]) continue;
  await page.evaluate(k => { const t = tabs.find(x => x.kind === k);
                             if (t) focusTab(t.id); }, kind);
  await sleep(250);
  const m = await page.evaluate(() => {
    const host = document.querySelector('.doc.on');
    const controls = [...(host?.querySelectorAll('input, select, textarea') || [])]
      .filter(e => e.offsetHeight > 0)
      .filter(e => !['checkbox', 'radio'].includes(e.type));
    return {
      overflow: document.documentElement.scrollWidth
                - document.documentElement.clientWidth,
      small: controls.filter(e => parseFloat(getComputedStyle(e).fontSize) < 16)
        .map(e => e.id || e.className || e.tagName),
    };
  });
  ok(m.overflow <= 0, `[${kind}] no sideways scroll at phone width (${
    m.overflow}px over)`);
  ok(m.small.length === 0, `[${kind}] phone controls are 16px${
    m.small.length ? ` — not: ${m.small.join(', ')}` : ''}`);
}

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
