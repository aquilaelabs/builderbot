// Shared plumbing for the dashboard browser tests. run.sh starts the server
// and hands over the URL, the Chromium binary and the fixture directory in
// the environment; each test file opens its own pages and reports PASS/FAIL
// lines, exiting non-zero on any failure.
import { createRequire } from 'module';
import { writeFileSync, readFileSync } from 'fs';
import { execFileSync } from 'child_process';
// require, not import: ESM resolution ignores NODE_PATH, and the image's
// Playwright is a global install (/usr/lib/node_modules), not a dependency
// of this directory. CJS resolution honours NODE_PATH, which run.sh sets.
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
  const ctx = await browser.newContext({ httpCredentials: CREDS, ...opts });
  const page = await ctx.newPage();
  page.errors = []; page.dialogs = [];
  page.on('console', m => { if (m.type() === 'error') page.errors.push(m.text()); });
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
export function tmuxNew(name){
  if (process.env.TMUX || !process.env.TMUX_TMPDIR)
    throw new Error('tmuxNew: not on the private tmux server — refusing');
  execFileSync('tmux', ['new-session', '-d', '-s', name, '-c', '/tmp']);
}

// Wait until the page has its first doctor verdict — the last thing to land
// on a fresh instance, so a good "page is ready" marker.
export const ready = page => page.waitForFunction(() => {
  const d = document.getElementById('docDot');
  return d && !d.hidden && d.className.includes('ok');
}, { timeout: 40000 });

// A real touch gesture through Chromium's gesture recogniser (not synthetic
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
