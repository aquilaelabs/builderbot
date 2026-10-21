// Shared plumbing for the dashboard browser tests. run.sh starts the server
// and hands over the URL, the Chromium binary and the fixture directory in
// the environment; each test file opens its own pages and reports PASS/FAIL
// lines, exiting non-zero on any failure.
import os from 'node:os';
import { mkdirSync } from 'node:fs';
import { basename } from 'node:path';
import { createRequire } from 'module';
import { writeFileSync, readFileSync } from 'fs';
import { execFileSync } from 'child_process';
// require, not import: ESM resolution ignores NODE_PATH, and the image's
// Playwright is a global install (/usr/lib/node_modules), not a dependency
// of this directory. CJS resolution honors NODE_PATH, which run.sh sets.
const { chromium } = createRequire(import.meta.url)('playwright');

// run.sh hands the URL over; the port in it is picked per run, so there is no
// default worth having: a hardcoded one would run the suite against whatever
// happens to answer there, which is the failure the runner refuses to allow.
export const URL = process.env.DASHBOARD_TEST_URL
  || (() => { throw new Error('DASHBOARD_TEST_URL is not set. Run this through '
                              + '`bb dashboard test`, which starts the server'); })();
export const DIR = process.env.DASHBOARD_TEST_DIR;
const CHROME = process.env.DASHBOARD_TEST_CHROME;
const CREDS = { username: 'test', password: 'test' };

let pass = 0, fail = 0;
// Where a suite spends its time, on request. A file that runs real jobs
// against a real agent is minutes long, and until this existed the only way
// to find the slow part was to guess: BB_TEST_TIMING=1 prefixes each result
// with the seconds since the last one, so the gaps name themselves.
const TIMING = process.env.BB_TEST_TIMING === '1';
const startedAt = Date.now();
let lastAt = startedAt;
export const ok = (cond, name) => {
  const gap = TIMING ? `[+${((Date.now() - lastAt) / 1000).toFixed(1)}s] ` : '';
  lastAt = Date.now();
  console.log((cond ? 'PASS' : 'FAIL') + '  ' + gap + name);
  cond ? pass++ : fail++;
};
// The browser is optional: not every file here drives a page. version.mjs
// exercises a module through the CLI that shares it, and still wants the
// same pass/fail tally and exit code as the browser files.
export const done = async browser => {
  for (const ctx of browser?.contexts() || [])
    for (const p of ctx.pages()){ await leaveNotebooks(p); await flushCoverage(p); }
  await browser?.close();
  console.log(`\n${pass} passed, ${fail} failed`
              + (TIMING ? ` in ${((Date.now() - startedAt) / 1000).toFixed(1)}s` : ''));
  process.exit(fail ? 1 : 0);
};
export const sleep = ms => new Promise(r => setTimeout(r, ms));
// What in an answer breaks a released app's pin (R79 step 8): a field the
// pin names gone or of another type, on the answer or on a row. The
// language is test/device-api.json's: types are string, number, boolean,
// object, array, null, any or a union like string|null; KEY? is checked
// only when present, LIST[].FIELD on every row, LIST[] a row's columns by
// position, and A.B a field of an object. Held by deviceapi.mjs and appapi.mjs.
const pinKind = v => v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v;
const pinFits = (v, want) => want === 'any' || want.split('|').includes(pinKind(v));
export function pinBreaks(body, reads, where){
  const out = [];
  for (const [key, want] of Object.entries(reads || {})){
    const optional = key.endsWith('?');
    const k = optional ? key.slice(0, -1) : key;
    const tuple = k.endsWith('[]');
    const [head, ...rest] = tuple ? [k.slice(0, -2)] : k.split('[].');
    const top = head.split('.').reduce((o, p) => (o && typeof o === 'object' && p in o ? o[p] : undefined), body);
    if (top === undefined){ if (!optional && !rest.length) out.push(`${where}: no "${head}"`); continue; }
    if (tuple){
      for (const row of top){
        if (!Array.isArray(row) || row.length < want.length){ out.push(`${where}: a row of ${head} is not ${want.length} long`); break; }
        const bad = want.findIndex((t, i) => !pinFits(row[i], t));
        if (bad >= 0){ out.push(`${where}: ${head}[][${bad}] is ${pinKind(row[bad])}, pinned ${want[bad]}`); break; }
      }
    } else if (rest.length){
      for (const row of Array.isArray(top) ? top : []){
        if (!(rest[0] in row)){ if (!optional) out.push(`${where}: a row of ${head} has no "${rest[0]}"`); break; }
        if (!pinFits(row[rest[0]], want)){ out.push(`${where}: ${head}[].${rest[0]} is ${pinKind(row[rest[0]])}, pinned ${want}`); break; }
      }
    } else if (!pinFits(top, want)) out.push(`${where}: "${head}" is ${pinKind(top)}, pinned ${want}`);
  }
  return out;
}
// The page's requests have landed and nothing new has been asked for
// `quiet` ms: what a fixed sleep after opening a tab or a view was standing
// in for. A sleep of 400ms paid 400ms whether the fetch took 30ms or 300,
// and uniform.mjs paid it on every one of its 27 kinds in every section
// (R211). Capped, because a page that keeps asking (a poll in flight) is
// still a page to measure.
export async function settled(page, { quiet = 150, cap = 3000 } = {}){
  const t0 = Date.now();
  for (;;){
    const { n, lastDone } = page.inFlight ? page.inFlight() : { n: 0, lastDone: 0 };
    const since = Date.now() - Math.max(lastDone, t0);
    if (n === 0 && since >= quiet) return;
    if (Date.now() - t0 > cap) return;
    await sleep(n ? 40 : Math.max(10, quiet - since));
  }
}

// A window says it has left its notebooks before it goes (B144). A person's
// browser does this itself, on pagehide, with its session cookie; a harness
// page authenticates with an injected header, which a request sent during
// unload does not carry, and Playwright's close runs no pagehide at all. So
// the same call is made here, while the page can still authenticate it:
// without it the next file met this one's windows as "your other window"
// for the seat's fifty seconds.
export async function leaveNotebooks(p){
  await p.evaluate(() => typeof notebooks === 'undefined' ? null
    : Promise.all([...notebooks.values()].map(n => n.leave?.())))
    .catch(() => {});
}

// Function coverage (roadmap R76): under `bb tests coverage` the copy the
// run is made from is instrumented and every page keeps its counts in
// window.__bbcovc; they are written out when a page closes and when a
// suite is done, one file per page, for the run to merge into the tree's
// .bb-map/coverage.json. Nothing here does anything without the directory
// the harness names.
export async function flushCoverage(p){
  const dir = process.env.BB_COVERAGE_DIR;
  if (!dir) return;
  try {
    const counts = await p.evaluate(() => (typeof __bbcovc === 'undefined' ? null : __bbcovc));
    if (!counts) return;
    const suite = basename(process.argv[1] || 'suite').replace(/\.mjs$/, '');
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/${suite}-${process.pid}-${Date.now()}.json`, JSON.stringify({ suite, counts }));
  } catch (e) { /* a page already gone has nothing to say */ }
}

export async function closePage(p){
  await leaveNotebooks(p);
  await flushCoverage(p);
  await p.close();
}

export const launch = () => chromium.launch({ executablePath: CHROME });

// A page with the test credentials, console errors collected on page.errors,
// and dialogs auto-accepted (recorded on page.dialogs): the confirmations
// are part of what the tests check.
export async function newPage(browser, { tour = false, ...opts } = {}){
  // The Authorization header is sent preemptively: the server answers 401
  // without a WWW-Authenticate challenge now (the challenge is what popped
  // the browser dialog), and httpCredentials alone only reacts to one.
  const ctx = await browser.newContext({
    httpCredentials: CREDS,
    extraHTTPHeaders: { Authorization: 'Basic '
      + Buffer.from(`${CREDS.username}:${CREDS.password}`).toString('base64') },
    ...opts });
  // The first-use tour (R94) would stand over every page a suite looks at:
  // off unless the suite asks for it.
  if (!tour) await ctx.addInitScript(() => { window.BB_NO_TOUR = true; });
  const page = await ctx.newPage();
  // Every wait in this suite is a guess about how long a poll, a subprocess and
  // a repaint take on THIS box, and this box also runs CI, the live dashboard
  // and whatever the operator is doing. Rather than re-guess at two hundred
  // call sites, the default is set here and the explicit ones are stretched by
  // the same multiple below: BB_TEST_SLOW=2 doubles them, which is what the CI
  // job sets. A wait that is too long costs seconds on a failure; one that is
  // too short costs a red run that was never about the code (bug #13).
  page.setDefaultTimeout(patience(30000));
  // What the page has in flight, for the wrapper below: a wait that runs
  // out while the page is still asking the server is a slow page, not an
  // absent element.
  let inFlight = 0, lastDone = Date.now();
  page.on("request", () => { inFlight++; });
  for (const ev of ["requestfinished", "requestfailed"]) page.on(ev, () => { inFlight = Math.max(0, inFlight - 1); lastDone = Date.now(); });
  // For settled() below: what is in flight, and when the last answer came.
  page.inFlight = () => ({ n: inFlight, lastDone });
  for (const m of ["waitForFunction", "waitForSelector"]){
    const real = page[m].bind(page);
    page[m] = async (...args) => {
      // waitForFunction(fn, arg, options): options passed second, where the
      // function's argument goes (208 waits did), were the 30s default with
      // the object handed to the page (B556). Moved to where they belong
      // when there is nothing third, never below that default, which every
      // one of them has run on: a 40s wait now waits 40s, and a 10s one
      // keeps the 30s it was proven against.
      if (m === "waitForFunction" && args.length === 2 && args[1] && typeof args[1] === "object"
          && !Array.isArray(args[1]) && Object.keys(args[1]).every(k => k === "timeout" || k === "polling"))
        args = [args[0], null, { ...args[1], ...(typeof args[1].timeout === "number"
          ? { timeout: Math.max(args[1].timeout, 30000) } : {}) }];
      const last = args[args.length - 1];
      if (last && typeof last === "object" && typeof last.timeout === "number")
        args[args.length - 1] = { ...last, timeout: patience(last.timeout) };
      // A timeout is only a timeout on a page that is at rest on a box
      // that is not saturated. Four workers on four cores timed out a
      // dozen checks a day that passed alone every time (27 Sep): the
      // redraw came, after the budget. So a wait that runs out while the
      // page has requests in flight, or while the load average is at the
      // core count, gets the same budget again, three times at most; an
      // element that never comes still fails, with its snapshot, later.
      let tries = 0;
      const budget = () => (typeof args[args.length - 1]?.timeout === "number" ? args[args.length - 1].timeout : patience(30000));
      const busy = () => inFlight > 0 || os.loadavg()[0] >= os.cpus().length;
      try {
        for (;;){
          try { return await real(...args); }
          catch (e) {
            if (!/Timeout .*exceeded/.test(String(e)) || ++tries >= 3 || !busy()) throw e;
            console.log(`[wait] ran out after ${budget()}ms with ${inFlight} request(s) in flight and a load of ${
              os.loadavg()[0].toFixed(1)} on ${os.cpus().length} cores: waiting the same again (${tries} of 2)`);
          }
        }
      } catch (e) {
        // A timeout here says what was waited for and nothing about WHY it
        // never came, which is how the same few files have been rewaited
        // rather than fixed. Measured 18 Sep, and there are two causes, which
        // this dump tells apart. In a full run the server answers /api/status
        // in 10ms first file or last, the box peaks at a load of 2 and a file
        // takes the same seconds as it does alone: those are waits on
        // something another file made untrue, and the dump shows a loaded,
        // healthy page. Right after the machine is disturbed (a session
        // restarting beside the suite) files that pass alone timed out at
        // ready() and passed four times running minutes later: that one is
        // the box, and the dump shows a page that never finished arriving.
        if (e && e.name === "TimeoutError"){
          try {
            const seen = await page.evaluate(() => ({
              tabs: (typeof tabs !== "undefined" ? tabs : []).map(t => t.kind),
              active: typeof active !== "undefined" ? active : null,
              // Which tab each pane shows and which view a shown notebook is
              // on: a wait for something drawn in a panel that is not on
              // screen times out looking exactly like one that never drew
              // (B297).
              panes: (typeof panes !== "undefined" ? panes : []).map(id =>
                id ? ((typeof tabs !== "undefined" ? tabs : []).find(t => t.id === id)?.kind || "?") + ":" + id : null),
              nbView: [...document.querySelectorAll(".nbview:not([hidden])")]
                .filter(v => v.offsetParent !== null).map(v => v.dataset.view),
              projects: (state?.projects || []).map(p => p.name),
              sessions: (state?.sessions || []).map(s => s.name),
              nodes: (state?.node_runners || []).length,
              // What ready() waits on, which is the most common wait there is:
              // the doctor dot going ok. A failing check anywhere keeps it red.
              docDot: (() => { const d = document.getElementById("docDot");
                               return d ? `${d.hidden ? "hidden " : ""}${d.className}` : "absent"; })(),
              doctor: (state?.doctor?.checks || [])
                .filter(c => c.level !== "ok").map(c => `${c.level} ${c.text}`).slice(0, 4),
            }));
            console.log("[wait] timed out; the page at that moment: "
                        + JSON.stringify(seen));
          } catch { /* the page may be gone, which is its own answer */ }
          if (page.errors?.length)
            console.log("[wait] console errors so far: " + page.errors.slice(-3).join(" | "));
        }
        throw e;
      }
    };
  }
  page.errors = []; page.dialogs = [];
  // The harness runs no ttyd, so every terminal iframe's /term request 502s
  // by design: same-origin now, which puts it in the page console where the
  // old dead-port fetch never appeared. Filtered here, not per test: it is a
  // property of the harness, not of any one scenario.
  // With the URL, because "Failed to load resource: 400" names neither what
  // asked nor what was asked for, and a console error nobody can locate is
  // one nobody fixes.
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const url = m.location()?.url || '';
    if (url.includes('/term')) return;
    page.errors.push(url ? `${m.text()} [${url.replace(/^https?:\/\/[^/]+/, '')}]` : m.text());
  });
  page.on('pageerror', e => page.errors.push(String(e)));
  page.on('dialog', d => { page.dialogs.push(d.message()); d.accept(); });
  // The project settings are sections, one open at a time (the operator,
  // 7 Oct). A person opens the section a field is in before using it, and so
  // does a suite: before an action on, or a wait for, a field inside a shut
  // section, its heading is pressed. Only those sections; a check of which
  // one a door opens reads the folds with $eval, which this leaves alone.
  const openRnFor = async (sel, timeout) => {
    if (typeof sel !== 'string' || !/#rn|rnmodal|rngroup/.test(sel)) return;
    // Until the field shows: a section another press is sliding shut still
    // reads open for a third of a second, and pressing it then does nothing
    // before it finishes closing; so it is looked at again until it is shut
    // (and pressed) or the field is on screen.
    const press = () => page.evaluate(s => {
      let el = null;
      try { el = document.querySelector(s); } catch { return 'done'; }
      if (!el) return 'wait';
      const d = el.closest('details.rngroup');
      if (!d) return 'done';
      // Mid-slide either way: wait for it to land (page-motion.js's fold).
      if (d.getAnimations().some(a => a.id === 'fold' && a.playState === 'running')) return 'wait';
      if (!d.open){ d.querySelector(':scope > summary').click(); return 'wait'; }
      if (getComputedStyle(d).display === 'none' || el.closest('[hidden]')) return 'done';
      return el.checkVisibility?.() ?? el.offsetParent !== null ? 'done' : 'wait';
    }, sel).catch(() => 'done');
    const until = Date.now() + Math.min(timeout ?? patience(30000), patience(30000));
    for (;;){
      if (await press() === 'done' || Date.now() > until) return;
      await new Promise(r => setTimeout(r, 100));
    }
  };
  for (const m of ['fill', 'selectOption', 'click', 'check', 'uncheck', 'type', 'press', 'setChecked', 'waitForSelector']){
    const real = page[m].bind(page);
    page[m] = async (sel, ...rest) => {
      const opts = rest[rest.length - 1];
      const hidden = m === 'waitForSelector' && ['hidden', 'detached', 'attached'].includes(opts?.state);
      if (!hidden) await openRnFor(sel, typeof opts?.timeout === 'number' ? opts.timeout : undefined);
      return real(sel, ...rest);
    };
  }
  return page;
}

// Flip the stub `bb doctor` between the ok and failing fixtures.
export const doctorFixture = name =>
  writeFileSync(`${DIR}/doctor.txt`, readFileSync(`${DIR}/doctor-${name}.txt`));

// A throwaway tmux session for a test that has ended the fixture ones. Only
// on the harness's private server: run.sh unsets TMUX and points TMUX_TMPDIR
// at its scratch dir, and this refuses to run unless both are so: a client
// inside a tmux session ignores TMUX_TMPDIR and would create (and later, the
// cleanup would kill) on the real server.
export function tmuxNew(name, dir = '/tmp', cmd = []){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxNew: not on the private tmux server, refusing');
  execFileSync('tmux', ['new-session', '-d', '-s', name, '-c', dir, ...cmd]);
}
// What a pane on that private server currently shows. For checking that
// something was typed into a session without being submitted: the screen is
// the only place text that has not been sent to a program exists.
export function tmuxCapture(name){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxCapture: not on the private tmux server, refusing');
  // -J joins what the pane merely wrapped, so a long line typed into an
  // 80-column pane still reads as the one line it is.
  return execFileSync('tmux', ['capture-pane', '-p', '-J', '-t', name]).toString();
}
// End one on that same private server. `fresh` puts the fixture sessions back
// before the next file, so a test may end one it needs gone.
export function tmuxKill(name){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxKill: not on the private tmux server, refusing');
  try { execFileSync('tmux', ['kill-session', '-t', name]); } catch { /* already gone */ }
}
// A tmux format string evaluated against a session on that same private server.
export function tmuxFmt(name, fmt){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxFmt: not on the private tmux server, refusing');
  return execFileSync('tmux', ['display-message', '-p', '-t', name, fmt]).toString().trim();
}

// Poll the server from node until the stored layout satisfies pred, for
// tests that must not proceed (usually into a reload) before a debounced
// save has actually landed. NOT page.waitForFunction with an async
// predicate: an async function returns a Promise, a Promise is truthy, and
// that wait resolves instantly. Two tests guarded reloads with exactly that
// no-op, and passed only while their other waits happened to outlast the
// 400ms save debounce, until the findings preload made a page fast enough to
// reload inside the window, and the pending save died with it.
export async function layoutSettled(pred, ms = 15000){
  const auth = { Authorization: 'Basic '
    + Buffer.from(`${CREDS.username}:${CREDS.password}`).toString('base64') };
  const t0 = Date.now();
  for (;;){
    const l = (await (await fetch(URL + 'api/status', { headers: auth })).json()).layout;
    if (pred(l)) return l;
    if (Date.now() - t0 > ms)
      throw new Error('layout never settled: ' + JSON.stringify(l));
    await sleep(200);
  }
}

// What animated while `act` ran: recorded, not sampled.
//
// Asking `getAnimations().length > 0` in a round trip after the action only
// works if that round trip lands inside the tween, which is 140-220ms here.
// On an idle box it does; on a loaded one it does not, and the test fails
// with nothing wrong with the page. Wrapping Element.animate answers the
// question that was actually being asked (did this animate) rather than
// the one about whether it still is.
//
// Returns a key per animated element: its id, its data-card, and its classes,
// so a caller can look for whichever of those it knows the element by.
export async function animatedDuring(page, act){
  await page.evaluate(() => {
    window.__anim = [];
    window.__realAnimate = Element.prototype.animate;
    Element.prototype.animate = function(...a){
      // classList rather than className: on an SVG element the latter is an
      // SVGAnimatedString, which joins as "[object SVGAnimatedString]".
      window.__anim.push([this.id, this.dataset?.card,
                          ...(this.classList || [])].filter(Boolean).join(" "));
      return window.__realAnimate.apply(this, a);
    };
  });
  let seen = [];
  try {
    await act();
  } finally {
    // Restored even if the action threw: a patched prototype left behind
    // would follow every later assertion in the file.
    seen = await page.evaluate(() => {
      Element.prototype.animate = window.__realAnimate;
      return window.__anim;
    });
  }
  return seen;
}

// Open a fold and wait for it to stop moving.
//
// The memories and the bug reports slide open now, which means everything
// inside one is in motion for the length of the tween, and Playwright will
// not click a moving target, so a test that reached straight into a freshly
// opened report failed on "element is not stable" under load. Waiting on the
// element's own animations is exact: no sleep to tune, and nothing to
// re-tune when the duration changes.
// Change a fixture out of band, then wait for the page to notice, asking
// again each time instead of asking once and waiting.
//
// The server caches several verdicts behind short TTLs. The Claude auth
// answer is 20 seconds, deliberately: reading it costs a whole node runtime
// (357MB, 0.68s), and bypassing the cache once put the container out of
// memory. The page re-asks on its own fifteen-second poll. So a single
// refresh() straight after rewriting a fixture can be answered from the
// cache, and the next honest answer is up to TTL-plus-a-poll away: a test
// that refreshes once and then waits 25s is waiting on a question it has
// already had answered, and 20 + 15 is more than 25.
//
// Nothing here holds a handle across a repaint either: the condition is
// evaluated in the page on every pass.
// How long a wait gets, stretched when the box is busy. Every timeout in the
// suite is really a guess about how long a poll, a subprocess and a repaint
// take on THIS machine, and this machine also runs CI, an emulator and the
// operator's sessions. A full suite has gone red three times in a day on three
// different waits, each of which passed alone seconds later (bug #13), so the
// honest fix is not another guess but a multiplier: BB_TEST_SLOW=2 doubles
// every wait that goes through here, and a run under load can afford it.
//
// Slow by default is deliberate. A wait that is too long only costs seconds
// on the rare failure; one that is too short costs a red run that is not
// about the code, and then an hour proving that.
export const SLOW = Number(process.env.BB_TEST_SLOW || 1) || 1;
export const patience = ms => Math.round(ms * SLOW);

// A project's settings save a section at a time (the operator, 10 Oct):
// each section's bar has Save, or with a session of this account running and
// a change it takes only at its start (the author, reads, the model) both
// Save, keep it running and Save and end it at once. sectSave presses one
// section's and waits for it to finish: "" when it saved, else what its bar
// says went wrong. `end` picks Save and end it where the bar offers it.
// A page of settings (a project's Settings view, Controller settings,
// Profile) shows one section at a time, picked from the list beside it (the
// operator, 16 Oct); the project's dialog shows them all. A suite picks the
// section before it touches a field there; where there is no list this does
// nothing.
export async function splitPick(page, id){
  await page.evaluate(s => document.querySelector(`.doc.on .ssplit > .snav [data-spick="${s}"], .ssplit > .snav [data-spick="${s}"]`)?.click(), id);
  await faded(page);
}
// A press's fade through over (fadeThrough): the still copy of what went out
// gone and what came in at rest, which is when a person reads it; read
// sooner, a list counts the copy beside its replacement.
export const faded = page => page.waitForFunction(() => !document.querySelector('.fghost')
  && !document.getAnimations().some(a => a.id === 'fadein' && a.playState === 'running'),
  null, { timeout: 5000 });
export const rnSect = splitPick;

export async function sectSave(page, sect, { end = false, timeout = 15000 } = {}){
  timeout = patience(timeout);
  await rnSect(page, sect);
  const bar = `.rnbar[data-rnbar="${sect}"]`;
  const which = await page.$eval(bar, (b, end) => b.querySelector('[data-rnkeep]').hidden ? 'data-rnsave'
                                                   : end ? 'data-rnend' : 'data-rnkeep', end);
  await page.click(`${bar} [${which}]`);
  await page.waitForFunction(sel => { const b = document.querySelector(sel);
    return !b || (!b.dataset.busy && (b.querySelector('.state.bad') || [...b.querySelectorAll('button')].every(x => x.disabled))); },
  bar, { timeout });
  return page.$eval(bar, b => b.querySelector('.state.bad')?.textContent || '').catch(() => '');
}

// Every section holding a change saved in turn, then the dialog closed (a
// notebook's Settings view has nothing to close). Stops at a section that
// says no, leaving its bar's sentence on screen for the suite to read, and
// returns it.
export async function saveDialog(page, { end = false, timeout = 15000 } = {}){
  // The dialog wakes its bars on a 0 ms timer after a change (index.html's
  // rnmodal wiring), and a check that has just resolved is in the same tick:
  // read the bars after the page's own timers have run, or a change made
  // this instant reads as nothing to save (B691).
  await page.evaluate(() => new Promise(r => setTimeout(r, 0)));
  for (let i = 0; i < 12; i++){
    const sect = await page.evaluate(() => [...document.querySelectorAll('.rnbar')]
      .find(b => !b.dataset.busy && [...b.querySelectorAll('button:not([data-rnrevert])')].some(x => !x.hidden && !x.disabled))
      ?.dataset.rnbar || '');
    if (!sect) break;
    const err = await sectSave(page, sect, { end, timeout });
    if (err) return err;
    // A rename closes the form and draws it again under the new name.
    if (await page.$eval('#rnmodal', e => e.hidden) && !(await page.$('.nbsettings .rnbar'))) break;
  }
  if (await page.$eval('#rnmodal', e => !e.hidden) && await page.$eval('#rnCancel', e => !e.hidden)){
    await page.click('#rnCancel');
    await page.waitForFunction(() => document.getElementById('rnmodal').hidden, null, { timeout: patience(timeout) });
  }
  return '';
}

export async function refreshUntil(page, fn, { timeout = 60000, every = 1000 } = {}){
  timeout = patience(timeout);
  const until = Date.now() + timeout;
  for (;;){
    if (await page.evaluate(fn)) return;
    if (Date.now() > until)
      throw new Error(`refreshUntil: the condition never held in ${timeout}ms`);
    await page.evaluate(() => refresh()).catch(() => {});
    await sleep(every);
  }
}

// Hold the poll off while a test drives state it planted itself.
//
// The page refreshes every fifteen seconds and a refresh REPLACES `state`
// from the server. A test that plants something the server does not say
// (state.docker = {on:false}, an attention row, a session that is not there)
// and then makes several assertions about it is racing that timer: usually
// it wins, and about one run in three a tick lands mid-block and the page
// redraws from the truth instead. That is bug B99's whole family, and it
// cost a bisect that blamed a commit.
//
// So: plant, assert, release. `refresh` is a top-level function declaration,
// so the binding can be swapped and put back; nothing in the page has to
// know about this. A poll already out when the hold goes on still lands, so
// the hold waits for it: landing after the caller planted its rows, it put
// the server's back over them (B295).
export const holdPoll = async page => {
  await page.evaluate(() => {
    if (!window.__heldRefresh){ window.__heldRefresh = refresh; refresh = async () => {}; }
  });
  await page.waitForFunction(() => !refreshBusy, null, { timeout: 30000 });
};
export const freePoll = page => page.evaluate(() => {
  if (window.__heldRefresh){ refresh = window.__heldRefresh; window.__heldRefresh = null; }
  // The status poll is a chain each read schedules the next of (R218 step
  // 10): a timer that fired into the held no-op scheduled nothing.
  if (typeof statusLater === 'function') statusLater();
});

// One section is open at a time on a tab and in a notebook view (5 and
// 6 Oct): a check opens the one it works in first, by its key
// (`nodes:advanced`), the way a person does, through its summary.
// `scope` names where: the same key is on every node's row of the Nodes tab.
export async function openSection(page, key, scope = ''){
  const sel = `${scope ? scope + ' ' : ''}details.sect[data-sect="${key}"]`;
  // There first: a node picked a moment ago is still being drawn.
  await page.waitForSelector(sel, { state: 'attached', timeout: 10000 }).catch(() => {});
  await page.evaluate(s => {
    const d = document.querySelector(s);
    if (d && !d.open) d.querySelector(':scope > summary').click();
  }, sel);
  await page.waitForFunction(s => document.querySelector(s)?.open, sel, { timeout: 5000 }).catch(() => {});
}

// The Projects page's Archived fold opened (the operator, 18 Oct: a locked
// project is archived, its card folded away at the page's foot), so an
// archived card can be read and pressed; the fixture's delta is one.
export async function openArchived(page){
  await page.waitForSelector('.projtab details[data-sect="projects:archived"]', { state: 'attached', timeout: 15000 });
  await page.evaluate(() => { document.querySelector('.projtab details[data-sect="projects:archived"]').open = true; });
}

export async function openFold(page, sel){
  // Resolved to a handle first, and the wait done through that rather than
  // through the selector: these are often Playwright's own selector flavor
  // (`:has(.mname:text-is("tabs"))`), which page.$ understands and the page's
  // own querySelector does not.
  //
  // Retried, because the handle can go stale between resolving it and
  // clicking it: these lists repaint whenever their revision token moves, and
  // a test that files or notes a bug moves it legitimately. The row is then
  // replaced by an equal one and the click lands on a detached node. Nothing
  // is wrong with the page when that happens, so re-resolve and go again rather
  // than making the suite's honesty depend on that gap staying narrow.
  // A section on a page of settings is picked from its list rather than
  // unfolded (splitPick).
  const rn = /data-sect="[a-z]+:(\w+)"/.exec(sel);
  if (rn) await splitPick(page, rn[1]);
  let last;
  for (let attempt = 0; attempt < 4; attempt++){
    const el = await page.$(sel);
    if (!el) throw new Error(`openFold: nothing matches ${sel}`);
    try{
      // Open already is done: a click would shut it, which with one section
      // open at a time a suite meets often (5 Oct).
      if (await el.evaluate(d => d.open && !d.getAnimations().length)) return;
      await (await el.$("summary")).click();
      await page.waitForFunction(d => d.open && !d.getAnimations().length,
                                 el, { timeout: 10000 });
      return;
    }catch(e){
      last = e;
      // Only a stale handle is worth another go; a real failure should fail.
      if (!/not attached|not stable|detached/i.test(String(e))) throw e;
      await sleep(120);
    }
  }
  throw last;
}

// Wait until the page has its first doctor verdict, the last thing to land
// on a fresh instance, so a good "page is ready" marker.
// The closing half of openFold, and racy for the same reason: the click can
// land on a row that a repaint is about to replace, and the replacement comes
// back open. Only clicks while it is actually open, so a retry cannot toggle
// a fold that already did close.
export async function closeFold(page, sel){
  let last;
  for (let attempt = 0; attempt < 4; attempt++){
    const isOpen = await page.$eval(sel, d => d.open).catch(() => false);
    if (isOpen) await page.click(`${sel} summary`).catch(e => { last = e; });
    try{
      await page.waitForFunction(s => {
        const d = document.querySelector(s);
        return d && !d.open && !d.getAnimations().length;
      }, sel, { timeout: 3000 });
      return;
    }catch(e){ last = e; await sleep(120); }
  }
  throw last;
}

export const ready = page => page.waitForFunction(() => {
  const d = document.getElementById('docDot');
  return d && !d.hidden && d.className.includes('ok');
}, { timeout: 40000 });

// A real touch gesture through Chromium's gesture recognizer (not synthetic
// pointer events): down at (x,y), optional hold, glide to (x2,y2), lift.
export async function finger(page, x, y, x2, y2, holdMs){
  const cdp = await page.context().newCDPSession(page);
  const touch = (type, tx, ty) =>
    cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x: tx, y: ty }] });
  await touch('touchStart', x, y);
  if (holdMs) await sleep(holdMs);
  const n = 10;
  for (let i = 1; i <= n; i++){
    await touch('touchMove', x + (x2 - x) * i / n, y + (y2 - y) * i / n);
    await sleep(16);
  }
  await touch('touchEnd', 0, 0);
  await sleep(250);
  await cdp.detach();
}

// The notebook is a tab now, not a modal: it is *moved* into whichever pane is
// showing it, so "is it open" is a question about where its node lives.
export const nbShown = (page) =>
  page.waitForFunction(() => !!document.querySelector('.pane .nb'),
                       { timeout: 20000 });
// The notebook opens on its first tab (Memory). A file whose subject is one of
// the others says so once, here, rather than every test in it knowing which
// tab the panel happens to start on.
// A notebook view by its button, its group first when the button is in a
// group that is shut (R259: the strip is five groups, a group's views in a
// row under it). `scope` narrows to one notebook.
export async function nbGo(page, v, scope = '.pane .nb'){
  // Found as Playwright finds it, so a scope in its own selector language
  // (version.mjs's :text-is) works here as it does in a click.
  const el = await page.$(`${scope} .nbtabs [data-v="${v}"]`);
  const g = el ? await el.evaluate(b => b.hidden && b.dataset.in ? b.dataset.in : '') : '';
  if (g) await page.click(`${scope} .nbtabs .nbgroups [data-g="${g}"] >> visible=true`);
  await page.click(`${scope} .nbtabs [data-v="${v}"] >> visible=true`);
}
export const nbTab = async (page, v) => {
  await nbGo(page, v);
  await page.waitForFunction(
    (w) => document.querySelector(`.pane .nb .nbview[data-view="${w}"]`)?.checkVisibility(),
    v, { timeout: 20000 });
};
export const nbGone = (page) =>
  page.waitForFunction(() => !document.querySelector('.pane .nb'),
                       { timeout: 20000 });

// A project row on the sidebar card folds all but Claude and the notebook
// behind … at every width (R119, 4 Oct): a check that presses one of the
// others opens the fold first, the way a person would.
// ...and since R218 step 3 the row is a card on the Projects page, whose
// menu holds the rest: the page is opened and the card's menu pressed open.
export async function unfold(page, project){
  await page.evaluate(() => { if (tabOf(panes[active])?.kind !== 'projects') openProjectsTab(); });
  await page.waitForSelector(`.pgrid .pcard[data-row="${project}"]`, { timeout: 15000 });
  for (let i = 0; i < 3; i++){
    await page.evaluate(name => {
      const c = document.querySelector(`.pgrid .pcard[data-row="${CSS.escape(name)}"]`);
      if (c?.querySelector('.actmenu')?.hidden) c.querySelector('[data-pmore]')?.click();
    }, project);
    const open = await page.waitForFunction(name => !document.querySelector(`.pgrid .pcard[data-row="${CSS.escape(name)}"] .actmenu`)?.hidden,
      project, { timeout: 3000 }).then(() => true, () => false);
    if (open) return;
  }
}

// The owner takes a project on (R135): a suite that drops a project
// directory into the workspace, or makes one outside the create dialog,
// gives it to the owner's own list the way the Users tab does, since "*"
// lists every project and takes none on.
// A folder made by hand is no project since R154 (the operator, 8 Oct): only
// create, clone and import record one. A suite that drops a project directory
// into the workspace records it the way an import would, in projects.json,
// which the server reads again when the file changes.
export function registerProject(...names) {
  const f = `${DIR}/state/projects.json`;
  // Not there yet: the server's first scan records every folder present,
  // this one with them, and a file written first would stop that.
  let d;
  try { d = JSON.parse(readFileSync(f, 'utf8')); } catch { return; }
  d.projects = d.projects || {};
  for (const n of names) {
    const r = d.projects[n];
    if (r) r.state = 'live';
    else d.projects[n] = { id: d.next++, name: n, state: 'live', at: Math.floor(Date.now() / 1000) };
  }
  writeFileSync(f, JSON.stringify(d));
}

export async function takeOn(...names) {
  registerProject(...names);
  const h = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const base = URL.replace(/\/$/, '');
  // Once the listing carries the project: the scan of the workspace is
  // cached briefly, and the verb keeps only names it lists.
  for (let i = 0; i < 40; i++) {
    const listed = ((await (await fetch(`${base}/api/status`, { headers: h })).json()).projects || []).map(p => p.name);
    if (names.every(n => listed.includes(n))) break;
    await new Promise(r => setTimeout(r, 250));
  }
  const me = (await (await fetch(`${base}/api/users`, { headers: h })).json()).users.find(u => u.name === 'test');
  const have = me?.projects || [];
  const want = [...have, ...names.filter(n => !have.includes(n))];
  const r = await fetch(`${base}/api/users`, { method: 'POST', headers: h,
    body: JSON.stringify({ action: 'projects', name: 'test', projects: want }) });
  return (await r.json()).projects || [];
}

// What a plain account could do before R152 (the operator, 7 Oct: there is
// no user role now, and an account holds nothing until given a role), as a
// role a suite gives the accounts it makes, the way an administrator would
// on the Roles tab: work on the projects the account is on, and read their
// settings, releases, credential and containers, with the shielded console.
export const MEMBER = { projects: 'write', settings: 'read', releases: 'read', gitauth: 'read',
                        files: 'write', containers: 'read', terminal: 'read' };
export async function member(...names) {
  const h = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const base = URL.replace(/\/$/, '');
  await fetch(`${base}/api/roles`, { method: 'POST', headers: h,
    body: JSON.stringify({ action: 'set', name: 'member', scope: 'projects', perms: MEMBER, note: 'a suite\'s plain account' }) });
  // A role on a project is given on the project (R155). A suite's plain
  // account holds it on every project, and the projects it is on (set
  // before this or after) decide which it reaches, as its list did before.
  const d = await (await fetch(`${base}/api/roles`, { headers: h })).json();
  for (const name of names) {
    const users = (await (await fetch(`${base}/api/users`, { headers: h })).json()).users || [];
    const was = users.find(u => u.name === name)?.projects || [];
    const project_roles = Object.fromEntries((d.projects || []).map(p => [p, ['member']]));
    await fetch(`${base}/api/roles`, { method: 'POST', headers: h,
      body: JSON.stringify({ action: 'assign', name, project_roles }) });
    await fetch(`${base}/api/users`, { method: 'POST', headers: h,
      body: JSON.stringify({ action: 'projects', name, projects: was }) });
  }
}
