// bb browser: a browser with an extension loaded, Chrome or Firefox, that a
// session drives from one verb (R247).
//
//   bb browser open --ext DIR [--firefox] [--url URL] [--headed]
//   bb browser go ID URL          (ext:popup.html is the extension's own page)
//   bb browser eval ID JS         the value, as JSON
//   bb browser shot ID FILE       a PNG of the page on show
//   bb browser list
//   bb browser stop ID | --all
//
// Each browser runs detached in its own process group, on a debugging port
// of its own and a profile of its own under ~/.cache/builderbot/browser, and
// is ended by that group, never by a pattern: Turing Lens built a harness of
// its own for this (14 Oct), and lost 45 minutes to browsers left from
// earlier runs holding the port and to a cleanup that matched itself.
//
// Chrome is Playwright's Chrome for Testing, which still takes
// --load-extension, driven over the DevTools protocol (Playwright's
// chromium.connectOverCDP takes the same port). Firefox is Playwright's
// build, and the extension is installed over WebDriver BiDi
// (webExtension.install), the same port a BiDi client drives it on.
// Dependency-free: Node's own fetch and WebSocket.
import { spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, openSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { homedir } from 'node:os';
import { join } from 'node:path';

const HOME = join(process.env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'builderbot', 'browser');
const CHROME = process.env.BB_BROWSER_CHROME || '';
const FIREFOX = process.env.BB_BROWSER_FIREFOX || '';
const die = msg => { console.error(`[builderbot] ERROR: ${msg}`); process.exit(1); };
const sleep = ms => new Promise(r => setTimeout(r, ms));

function freePort(){
  return new Promise((resolve, reject) => {
    const s = createServer();
    s.on('error', reject);
    s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)); });
  });
}

// Chrome's id for an unpacked extension: the SHA-256 of its absolute path,
// the first 32 hex digits written a to p.
export function chromeExtId(dir){
  return createHash('sha256').update(realpathSync(dir)).digest('hex').slice(0, 32)
    .split('').map(c => String.fromCharCode(97 + parseInt(c, 16))).join('');
}

const recPath = id => join(HOME, `${id}.json`);
function records(){
  if (!existsSync(HOME)) return [];
  return readdirSync(HOME).filter(f => f.endsWith('.json'))
    .map(f => { try { return JSON.parse(readFileSync(join(HOME, f), 'utf8')); } catch { return null; } })
    .filter(Boolean);
}
const alive = pid => { try { process.kill(pid, 0); return true; } catch (e) { return e.code === 'EPERM'; } };
function record(id){
  const r = records().find(x => x.id === id);
  if (!r) die(`no browser ${id} of yours: bb browser list says which are open`);
  if (!alive(r.pid)) die(`${id} is not running any more (it exited, or was ended): bb browser stop ${id} clears it`);
  return r;
}

// ---- the two protocols -----------------------------------------------------

async function socket(url){
  const ws = new WebSocket(url);
  let n = 0;
  const pend = new Map();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)){ pend.get(m.id)(m); pend.delete(m.id); }
  };
  await new Promise((ok, bad) => { ws.onopen = ok; ws.onerror = () => bad(new Error(`no answer at ${url}`)); });
  const send = (method, params = {}, ms = 30000) => new Promise((ok, bad) => {
    const i = ++n;
    const t = setTimeout(() => { pend.delete(i); bad(new Error(`${method} had no answer in ${ms / 1000}s`)); }, ms);
    pend.set(i, m => { clearTimeout(t); ok(m); });
    ws.send(JSON.stringify({ id: i, method, params }));
  });
  return { ws, send, close: () => ws.close() };
}

async function cdpPage(r){
  const list = await (await fetch(`http://127.0.0.1:${r.port}/json/list`)).json();
  const page = list.find(t => t.type === 'page');
  if (!page) die(`${r.id} has no page open`);
  return socket(page.webSocketDebuggerUrl);
}

async function bidi(r){
  const s = await socket(`ws://127.0.0.1:${r.port}/session`);
  const made = await s.send('session.new', { capabilities: {} });
  if (made.type !== 'success') die(`Firefox would not start a BiDi session: ${made.message || made.error}`);
  const tree = await s.send('browsingContext.getTree', { maxDepth: 0 });
  s.ctx = tree.result?.contexts?.[0]?.context;
  const close = s.close;
  s.close = async () => { await s.send('session.end', {}, 5000).catch(() => {}); close(); };
  return s;
}

// A BiDi remote value as plain JSON.
function plain(v){
  if (!v || typeof v !== 'object') return v;
  switch (v.type){
    case 'undefined': return undefined;
    case 'null': return null;
    case 'string': case 'boolean': return v.value;
    case 'number': return typeof v.value === 'number' ? v.value : Number(v.value);
    case 'array': case 'set': return (v.value || []).map(plain);
    case 'object': case 'map': return Object.fromEntries((v.value || []).map(([k, x]) => [typeof k === 'string' ? k : plain(k), plain(x)]));
    default: return `[${v.type}]`;
  }
}

function extUrl(r, url){
  if (!url.startsWith('ext:')) return url;
  const path = url.slice(4).replace(/^\/+/, '');
  if (r.kind === 'chrome') return `chrome-extension://${r.extId}/${path}`;
  // Firefox's WebDriver BiDi will not navigate a tab to an extension's own
  // page (measured on Playwright's Firefox 157, 14 Oct: "not allowed in this
  // context", from a new tab and from the page as well), so its popup and
  // options pages are Chrome's to look at here; what the extension does on
  // a site, its content scripts, works in both.
  die(`Firefox does not let WebDriver BiDi open an extension's own page (moz-extension://${r.extUuid || '...'}/${path}); `
      + 'open it in Chrome (bb browser open --ext DIR), where ext:PAGE works, or test what it does on a site here');
}

// ---- the verbs -------------------------------------------------------------

async function open(args){
  const want = { kind: 'chrome', ext: '', url: 'about:blank', headed: false };
  for (let i = 0; i < args.length; i++){
    const a = args[i];
    if (a === '--ext') want.ext = args[++i] || '';
    else if (a === '--url') want.url = args[++i] || 'about:blank';
    else if (a === '--firefox') want.kind = 'firefox';
    else if (a === '--chrome') want.kind = 'chrome';
    else if (a === '--headed') want.headed = true;
    else die(`bb browser open takes --ext DIR, --firefox or --chrome, --url URL and --headed, not ${a}`);
  }
  if (!want.ext) die('bb browser open needs --ext DIR: the unpacked extension, the folder its manifest.json is in');
  if (!existsSync(join(want.ext, 'manifest.json'))) die(`${want.ext} holds no manifest.json`);
  const ext = realpathSync(want.ext);
  const exe = want.kind === 'firefox' ? FIREFOX : CHROME;
  if (!exe) die(`no Playwright ${want.kind === 'firefox' ? 'Firefox' : 'Chromium'} in the toolchain store: `
                + 'the playwright toolchain carries both, and installing it is the operator\'s');
  if (want.headed && !process.env.DISPLAY) die('--headed needs a display (DISPLAY is not set); headless is the default');
  mkdirSync(HOME, { recursive: true });
  const id = `b${Date.now().toString(36).slice(-5)}`;
  const profile = join(HOME, id);
  mkdirSync(profile, { recursive: true });
  const port = await freePort();
  const manifest = JSON.parse(readFileSync(join(ext, 'manifest.json'), 'utf8'));
  const geckoId = manifest.browser_specific_settings?.gecko?.id || manifest.applications?.gecko?.id || '';
  const extUuid = want.kind === 'firefox' && geckoId ? randomUUID() : '';
  let argv;
  if (want.kind === 'chrome'){
    argv = [...(want.headed ? [] : ['--headless=new']), `--user-data-dir=${profile}`, `--remote-debugging-port=${port}`,
            `--load-extension=${ext}`, `--disable-extensions-except=${ext}`, '--no-first-run',
            '--no-default-browser-check', '--no-sandbox', want.url];
  } else {
    // The extension's address fixed before it is installed, so its own
    // pages are reachable (extensions.webextensions.uuids is read at install).
    const prefs = [['remote.active-protocols', 1], ['xpinstall.signatures.required', false],
                   ['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false],
                   ['toolkit.telemetry.reportingpolicy.firstRun', false]];
    if (extUuid) prefs.push(['extensions.webextensions.uuids', JSON.stringify({ [geckoId]: extUuid })]);
    writeFileSync(join(profile, 'user.js'), prefs.map(([k, v]) => `user_pref(${JSON.stringify(k)}, ${JSON.stringify(v)});`).join('\n') + '\n');
    argv = ['-profile', profile, ...(want.headed ? [] : ['--headless']), '--remote-debugging-port', String(port), '--no-remote', want.url];
  }
  const log = openSync(join(profile, 'browser.log'), 'a');
  const p = spawn(exe, argv, { detached: true, stdio: ['ignore', log, log] });
  p.unref();
  const rec = { id, kind: want.kind, pid: p.pid, port, profile, ext, extId: want.kind === 'chrome' ? chromeExtId(ext) : geckoId,
                extUuid, started: Math.floor(Date.now() / 1000) };
  writeFileSync(recPath(id), JSON.stringify(rec));
  // Up when its port answers, within a minute: a cold Firefox takes about
  // fifteen seconds on a quiet box, and the old fifteen-second cap ran out on
  // a busy one with the browser still starting (B758). One that dies stops
  // the wait at once.
  let up = false;
  for (let i = 0; i < 240 && !up; i++){
    await sleep(250);
    if (!alive(p.pid)) break;
    try {
      if (want.kind === 'chrome') up = (await fetch(`http://127.0.0.1:${port}/json/version`)).ok;
      else up = readFileSync(join(profile, 'browser.log'), 'utf8').includes('WebDriver BiDi listening');
    } catch { /* not yet */ }
  }
  if (!up){
    await stopOne(rec);
    die(`${want.kind} did not come up on port ${port}; its log was: ${readLog(rec).slice(-400)}`);
  }
  if (want.kind === 'chrome'){
    // The page given at launch can load before the extension is up, and its
    // content scripts miss it: wait for the extension's own target, then
    // load the page again.
    for (let i = 0; i < 40; i++){
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json().catch(() => []);
      if (list.some(t => t.url.startsWith(`chrome-extension://${rec.extId}/`))) break;
      await sleep(250);
    }
    if (want.url !== 'about:blank') await go(id, want.url, true);
  }
  if (want.kind === 'firefox'){
    const s = await bidi(rec);
    const r = await s.send('webExtension.install', { extensionData: { type: 'path', path: ext } });
    if (want.url !== 'about:blank' && s.ctx) await s.send('browsingContext.navigate', { context: s.ctx, url: want.url, wait: 'complete' });
    await s.close();
    if (r.type !== 'success'){ await stopOne(rec); die(`Firefox would not install it: ${r.message || r.error}`); }
    rec.extId = r.result.extension;
    writeFileSync(recPath(id), JSON.stringify(rec));
  }
  console.log(`browser ${id}: ${want.kind} on port ${port} (pid ${p.pid}), ${manifest.name || 'the extension'} loaded as ${rec.extId}`);
  console.log(want.kind === 'chrome'
    ? `  drive it over the DevTools protocol at http://127.0.0.1:${port} (Playwright: chromium.connectOverCDP)`
    : `  drive it over WebDriver BiDi at ws://127.0.0.1:${port}/session, one session at a time`);
  console.log(`  bb browser go ${id} URL (ext:popup.html for its own pages), eval ${id} JS, shot ${id} FILE, stop ${id}`);
}

function readLog(r){ try { return readFileSync(join(r.profile, 'browser.log'), 'utf8'); } catch { return ''; } }

async function go(id, url, quiet = false){
  if (!url) die('bb browser go ID URL');
  const r = record(id);
  const to = extUrl(r, url);
  if (r.kind === 'chrome'){
    const s = await cdpPage(r);
    await s.send('Page.enable');
    const loaded = new Promise(ok => {
      const was = s.ws.onmessage;
      s.ws.onmessage = e => { was(e); if (JSON.parse(e.data).method === 'Page.loadEventFired') ok(); };
    });
    const n = await s.send('Page.navigate', { url: to });
    if (n.result?.errorText) die(`${to}: ${n.result.errorText}`);
    await Promise.race([loaded, sleep(20000)]);
    s.close();
  } else {
    const s = await bidi(r);
    const n = await s.send('browsingContext.navigate', { context: s.ctx, url: to, wait: 'complete' });
    await s.close();
    if (n.type !== 'success') die(`${to}: ${n.message || n.error}`);
  }
  if (!quiet) console.log(`${id} is on ${to}`);
}

async function evaluate(id, js){
  if (!js) die('bb browser eval ID JS');
  const r = record(id);
  let value;
  if (r.kind === 'chrome'){
    const s = await cdpPage(r);
    const e = await s.send('Runtime.evaluate', { expression: js, returnByValue: true, awaitPromise: true });
    s.close();
    if (e.result?.exceptionDetails) die(`it threw: ${e.result.exceptionDetails.exception?.description || e.result.exceptionDetails.text}`);
    value = e.result?.result?.value;
  } else {
    const s = await bidi(r);
    const e = await s.send('script.evaluate', { expression: js, target: { context: s.ctx }, awaitPromise: true });
    await s.close();
    if (e.result?.type === 'exception') die(`it threw: ${e.result.exceptionDetails?.text || 'an exception'}`);
    if (e.type !== 'success') die(e.message || e.error);
    value = plain(e.result.result);
  }
  console.log(JSON.stringify(value === undefined ? null : value));
}

async function shot(id, file){
  if (!file) die('bb browser shot ID FILE');
  const r = record(id);
  let data;
  if (r.kind === 'chrome'){
    const s = await cdpPage(r);
    data = (await s.send('Page.captureScreenshot', { format: 'png' })).result?.data;
    s.close();
  } else {
    const s = await bidi(r);
    data = (await s.send('browsingContext.captureScreenshot', { context: s.ctx })).result?.data;
    await s.close();
  }
  if (!data) die('no picture came back');
  writeFileSync(file, Buffer.from(data, 'base64'));
  console.log(`${id}: ${file}`);
}

async function stopOne(r){
  // Its process group: the browser and every helper it started, and
  // nothing else of this session's.
  try { process.kill(-r.pid, 'SIGTERM'); } catch { /* gone */ }
  for (let i = 0; i < 20 && alive(r.pid); i++) await sleep(100);
  try { process.kill(-r.pid, 'SIGKILL'); } catch { /* gone */ }
  rmSync(r.profile, { recursive: true, force: true });
  rmSync(recPath(r.id), { force: true });
}

async function main(argv){
  const [verb, ...rest] = argv;
  switch (verb){
    case 'open': return open(rest);
    case 'go': return go(rest[0], rest[1]);
    case 'eval': return evaluate(rest[0], rest.slice(1).join(' '));
    case 'shot': return shot(rest[0], rest[1]);
    case 'list': case undefined: {
      const rs = records();
      if (!rs.length){ console.log('[builderbot] no browser of yours is open'); return; }
      for (const r of rs) console.log(`${r.id}  ${r.kind.padEnd(7)}  port ${r.port}  pid ${r.pid}${alive(r.pid) ? '' : ' (exited)'}  ${r.ext}`);
      return;
    }
    case 'stop': {
      const rs = rest[0] === '--all' ? records() : records().filter(r => r.id === rest[0]);
      if (!rest[0]) die('bb browser stop ID, or --all');
      if (!rs.length) die(`no browser ${rest[0]} of yours`);
      for (const r of rs){ await stopOne(r); console.log(`[builderbot] ended ${r.id} (${r.kind}, pid ${r.pid}) and removed its profile`); }
      return;
    }
    case '-h': case '--help': {
      const doc = readFileSync(new URL(import.meta.url), 'utf8').split('\n').slice(0, 10).map(l => l.replace(/^\/\/ ?/, ''));
      console.log(doc.join('\n'));
      return;
    }
    default: die(`bb browser takes open, go, eval, shot, list or stop, not ${verb}`);
  }
}

if (import.meta.url === `file://${process.argv[1]}`){
  main(process.argv.slice(2)).then(() => process.exit(0), e => die(e.message || String(e)));
}
