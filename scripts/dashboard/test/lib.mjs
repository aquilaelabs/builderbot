// Shared plumbing for the dashboard browser tests. run.sh starts the server
// and hands over the URL, the Chromium binary and the fixture directory in
// the environment; each test file opens its own pages and reports PASS/FAIL
// lines, exiting non-zero on any failure.
import { createRequire } from 'module';
import { writeFileSync, readFileSync } from 'fs';
import { execFileSync } from 'child_process';
// require, not import: ESM resolution ignores NODE_PATH, and the image's
// Playwright is a global install (/usr/lib/node_modules), not a dependency
// of this directory. CJS resolution honors NODE_PATH, which run.sh sets.
const { chromium } = createRequire(import.meta.url)('playwright');

export const URL = process.env.DASHBOARD_TEST_URL || 'http://127.0.0.1:8093/';
export const DIR = process.env.DASHBOARD_TEST_DIR;
const CHROME = process.env.DASHBOARD_TEST_CHROME;
const CREDS = { username: 'test', password: 'test' };

let pass = 0, fail = 0;
export const ok = (cond, name) => {
  console.log((cond ? 'PASS' : 'FAIL') + '  ' + name);
  cond ? pass++ : fail++;
};
export const done = async browser => {
  await browser.close();
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
};
export const sleep = ms => new Promise(r => setTimeout(r, ms));

export const launch = () => chromium.launch({ executablePath: CHROME });

// A page with the test credentials, console errors collected on page.errors,
// and dialogs auto-accepted (recorded on page.dialogs) — the confirmations
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
  page.errors = []; page.dialogs = [];
  // The harness runs no ttyd, so every terminal iframe's /term request 502s
  // by design — same-origin now, which puts it in the page console where the
  // old dead-port fetch never appeared. Filtered here, not per test: it is a
  // property of the harness, not of any one scenario.
  page.on('console', m => { if (m.type() === 'error'
    && !(m.location()?.url || '').includes('/term')) page.errors.push(m.text()); });
  page.on('pageerror', e => page.errors.push(String(e)));
  page.on('dialog', d => { page.dialogs.push(d.message()); d.accept(); });
  return page;
}

// Flip the stub `bb doctor` between the ok and failing fixtures.
export const doctorFixture = name =>
  writeFileSync(`${DIR}/doctor.txt`, readFileSync(`${DIR}/doctor-${name}.txt`));

// A throwaway tmux session for a test that has ended the fixture ones. Only
// on the harness's private server: run.sh unsets TMUX and points TMUX_TMPDIR
// at its scratch dir, and this refuses to run unless both are so — a client
// inside a tmux session ignores TMUX_TMPDIR and would create (and later, the
// cleanup would kill) on the real server.
export function tmuxNew(name, dir = '/tmp', cmd = []){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxNew: not on the private tmux server — refusing');
  execFileSync('tmux', ['new-session', '-d', '-s', name, '-c', dir, ...cmd]);
}
// What a pane on that private server currently shows. For checking that
// something was typed into a session without being submitted — the screen is
// the only place text that has not been sent to a program exists.
export function tmuxCapture(name){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxCapture: not on the private tmux server — refusing');
  // -J joins what the pane merely wrapped, so a long line typed into an
  // 80-column pane still reads as the one line it is.
  return execFileSync('tmux', ['capture-pane', '-p', '-J', '-t', name]).toString();
}
// End one on that same private server. `fresh` puts the fixture sessions back
// before the next file, so a test may end one it needs gone.
export function tmuxKill(name){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxKill: not on the private tmux server — refusing');
  try { execFileSync('tmux', ['kill-session', '-t', name]); } catch { /* already gone */ }
}
// A tmux format string evaluated against a session on that same private server.
export function tmuxFmt(name, fmt){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxFmt: not on the private tmux server — refusing');
  return execFileSync('tmux', ['display-message', '-p', '-t', name, fmt]).toString().trim();
}

// Poll the server from node until the stored layout satisfies pred — for
// tests that must not proceed (usually into a reload) before a debounced
// save has actually landed. NOT page.waitForFunction with an async
// predicate: an async function returns a Promise, a Promise is truthy, and
// that wait resolves instantly. Two tests guarded reloads with exactly that
// no-op, and passed only while their other waits happened to outlast the
// 400ms save debounce — the findings preload made a page fast enough to
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

// Wait until the page has its first doctor verdict — the last thing to land
// on a fresh instance, so a good "page is ready" marker.
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
