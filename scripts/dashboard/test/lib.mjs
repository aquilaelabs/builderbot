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
export async function newPage(browser, opts = {}){
  // The Authorization header is sent preemptively: the server answers 401
  // without a WWW-Authenticate challenge now (the challenge is what popped
  // the browser dialog), and httpCredentials alone only reacts to one.
  const ctx = await browser.newContext({
    httpCredentials: CREDS,
    extraHTTPHeaders: { Authorization: 'Basic '
      + Buffer.from(`${CREDS.username}:${CREDS.password}`).toString('base64') },
    ...opts });
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
  let inFlight = 0;
  page.on("request", () => { inFlight++; });
  for (const ev of ["requestfinished", "requestfailed"]) page.on(ev, () => { inFlight = Math.max(0, inFlight - 1); });
  for (const m of ["waitForFunction", "waitForSelector"]){
    const real = page[m].bind(page);
    page[m] = async (...args) => {
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
});

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
  let last;
  for (let attempt = 0; attempt < 4; attempt++){
    const el = await page.$(sel);
    if (!el) throw new Error(`openFold: nothing matches ${sel}`);
    try{
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
export const nbTab = async (page, v) => {
  await page.click(`.pane .nb .nbtabs [data-v="${v}"]`);
  await page.waitForFunction(
    (w) => document.querySelector(`.pane .nb .nbview[data-view="${w}"]`)?.checkVisibility(),
    v, { timeout: 20000 });
};
export const nbGone = (page) =>
  page.waitForFunction(() => !document.querySelector('.pane .nb'),
                       { timeout: 20000 });
