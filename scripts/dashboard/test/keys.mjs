// The Keys page (R154): an install whose key the install made shows it under
// Controller with where it is kept, its fingerprint and that it is not yet
// saved; Show puts the key on the page with Copy, Download and I saved it;
// Change makes a new key and everything kept under the old one is sealed
// again under it, still opening; what is kept is a table naming each with
// what uses it. Profile's Your key changes the account's own key. A
// session is refused. On a controller of its own, from a fresh state with a
// git token kept plain before its first start, beside the harness's.
import { launch, newPage, ok, done, DIR, patience, sleep } from './lib.mjs';
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, rmSync, openSync, writeFileSync, readFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';

const DASH = fileURLToPath(new globalThis.URL('..', import.meta.url));
const LIB = fileURLToPath(new globalThis.URL('../../lib', import.meta.url));
const freePort = () => new Promise(res => {
  const s = createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
});
const OWNER = { username: 'keyowner', password: 'longenough1' };
const AUTH = 'Basic ' + Buffer.from(`${OWNER.username}:${OWNER.password}`).toString('base64');
const H = { Authorization: AUTH, 'Content-Type': 'application/json' };

const w = `${DIR}/keys-own`;
rmSync(w, { recursive: true, force: true });
for (const d of ['config/gitcreds', 'workspace', 'home', 'secrets/install-key']) mkdirSync(`${w}/${d}`, { recursive: true });
const KEYF = `${w}/secrets/install-key/key`;
const FIRST = 'f'.repeat(64);
writeFileSync(KEYF, FIRST, { mode: 0o600 });
const TOKEN = 'https://x-access-token:plaintoken123@github.com';
writeFileSync(`${w}/config/gitcreds/web`, TOKEN + '\n', { mode: 0o600 });
const env = { ...process.env, DASHBOARD_STATE: `${w}/config`, WORKSPACE: `${w}/workspace`,
              BB_INSTALL_KEY_DIR: `${w}/secrets/install-key`, BB_INSTALL_KEY_IN: 'secrets',
              BB_SIGNING_SECRET_FILE: KEYF, BB_INSTALL_KEY_PREVIOUS_FILE: `${w}/secrets/install-key/key-previous` };
execFileSync('python3', [`${LIB}/users-verbs.py`, 'claim', `${DASH}/users.py`, OWNER.username],
             { env: { ...env, BB_USERS_PW: OWNER.password } });
const port = await freePort();
const out = openSync(`${w}/server.log`, 'a');
const proc = spawn('python3', ['-u', `${DASH}/server.py`], { stdio: ['ignore', out, out], env: {
  ...env, DASHBOARD_PORT: String(port), BUILDER_HOME: `${w}/home`, TC_AUTOCHECK: '0', BB_NODE_POLL: '3',
  BB_CLAUDE_LATEST_URL: 'file:///nonexistent', BB_CLAUDE_CHECK_DELAY: '3600', BB_NGINX_TAGS_URL: 'file:///nonexistent',
  BB_NGINX_CHECK_DELAY: '3600', BB_APPS_RELEASES_URL: 'file:///nonexistent', BB_APPS_BOOT_DELAY: '3600',
  BB_IMAGE_CHECK_DELAY: '3600', BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', BB_COVERAGE_OUT: '' } });
const base = `http://127.0.0.1:${port}`;
for (let i = 0; i < patience(120); i++){
  try { if ((await fetch(`${base}/login`)).status === 200) break; } catch { /* not up yet */ }
  await sleep(250);
}
const keys = async body => (await fetch(base + '/api/keys', { method: 'POST', headers: H, body: JSON.stringify(body) })).json();
await fetch(base + '/api/settings', { method: 'POST', headers: H, body: JSON.stringify({ set: { setup_done: true } }) });

try {
  // ---- what the server says, and what it never says ----------------------------
  const st = await keys({ action: 'status' });
  ok(st.install?.where === 'secrets' && st.install.changeable && !st.install.saved && /^[0-9a-f]{4} [0-9a-f]{4}$/.test(st.install.fingerprint),
     `the made key is in the secrets folder, changeable, not yet saved, named by its fingerprint (${JSON.stringify(st.install)})`);
  ok(!JSON.stringify(st).includes(FIRST) && !JSON.stringify(st).includes('plaintoken123'),
     '...and the status carries neither the key nor any value kept under it');
  const git = (st.kept || []).find(r => r.kind === 'git' && r.name === 'web');
  ok(git?.sealed, `the git token kept plain before the start was sealed at it and is listed (${JSON.stringify(git)})`);
  ok(!readFileSync(`${w}/config/gitcreds/web`, 'utf8').includes('plaintoken123'), '...and the file holds it sealed');

  // ---- the page at a desk --------------------------------------------------------
  const browser = await launch();
  const page = await newPage(browser, { httpCredentials: OWNER, extraHTTPHeaders: { Authorization: AUTH },
                                        viewport: { width: 1280, height: 900 } });
  const errs = [];
  page.on('pageerror', e => errs.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errs.push(m.text()); });
  await page.goto(base + '/#/controller/keys');
  await page.waitForSelector('.doc.on .keystab .keystbl', { timeout: 20000 }).catch(async e => {
    console.log('keys page:', JSON.stringify(await page.evaluate(() => ({ hash: location.hash, tabs: typeof tabs !== 'undefined' ? tabs.map(t => t.kind) : null,
      doc: document.querySelector('.doc.on')?.textContent.slice(0, 300) }))), errs.join(' | '));
    throw e;
  });
  const drawn = await page.evaluate(() => {
    const t = document.querySelector('.doc.on .keystab');
    return { fp: t.querySelector('.keyfp')?.textContent.trim(), warn: [...t.querySelectorAll('.notice.warn')].map(n => n.textContent.trim()),
             rows: [...t.querySelectorAll('.keystbl .tline')].map(l => l.querySelector('.lead')?.textContent.trim()),
             nav: [...document.querySelectorAll('.doc.on .pseg button, .doc.on .docbarrow button')].map(b => b.textContent.trim()) };
  });
  ok(drawn.fp === st.install.fingerprint, `Keys shows the key's fingerprint at its head (${drawn.fp})`);
  ok(drawn.warn.some(t => /Save a copy of this key/.test(t)), `...and asks for it to be saved (${drawn.warn.join(' | ')})`);
  ok(drawn.rows.includes('web'), `...and lists what is kept under it (${drawn.rows.join(', ')})`);

  await page.click('#bKeyShow');
  await page.waitForSelector('.doc.on .keyval', { timeout: 10000 });
  ok(await page.$eval('.doc.on .keyval', e => e.textContent) === FIRST, 'Show puts the key itself on the page');
  ok(await page.evaluate(() => ['bKeyCopy', 'bKeyDown', 'bKeySaved', 'bKeyHide'].every(id => document.getElementById(id))),
     '...with Copy, Download, I saved it and Hide');
  await page.click('#bKeySaved');
  await page.waitForFunction(() => !document.querySelector('.doc.on .keyval') && !document.querySelector('.doc.on .notice.warn'), null, { timeout: 10000 });
  ok((await keys({ action: 'status' })).install.saved, 'I saved it marks it saved, takes it off the page and the warning goes');

  // ---- a change: a new key, and everything under the old one sealed again -----------
  // The harness answers the page's own question with its first choice, Make a new key.
  await page.click('#bKeyChange');
  await page.waitForFunction(fp => document.querySelector('.doc.on .keyfp')?.textContent.trim() !== fp, st.install.fingerprint, { timeout: 15000 });
  const now = readFileSync(KEYF, 'utf8');
  const after = await keys({ action: 'status' });
  ok(now !== FIRST && /^[0-9a-f]{64}$/.test(now), 'Change writes a new key to the key folder');
  ok(!after.install.saved && !after.install.previous, `...not saved yet, and with nothing on the nodes the one before is gone (${JSON.stringify(after.install)})`);
  const resealed = execFileSync('python3', ['-c', `
import os, sys; sys.path.insert(0, ${JSON.stringify(DASH)})
import gitcreds, signing
from pathlib import Path
signing.load_master()
gitcreds.configure(state=Path(${JSON.stringify(`${w}/config`)}), seal_fn=signing.seal, unseal_fn=signing.unseal, sealing_fn=lambda: True)
print(gitcreds.read_line("web"))`], { env, encoding: 'utf8' }).trim();
  ok(resealed === TOKEN, `...and the git token opens under the new key alone (${resealed === TOKEN ? 'it does' : resealed})`);

  // ---- Profile: the account's own key ---------------------------------------------
  const mine0 = await keys({ action: 'change-mine' });
  ok(mine0.ok && /^[0-9a-f]{4} [0-9a-f]{4}$/.test(mine0.fingerprint), `an account changes its own key (${JSON.stringify(mine0)})`);
  await page.goto(base + '/#/settings/profile');
  await page.waitForFunction(() => document.querySelector('.doc.on [data-sect="profile:mykey"]'), null, { timeout: 20000 });
  const prof = await page.evaluate(() => {
    const s = document.querySelector('.doc.on [data-sect="profile:mykey"]');
    s.open = true;
    return { fp: s.querySelector('.keyfp')?.textContent.trim(), change: !!s.querySelector('#bKeyMine') };
  });
  ok(prof.fp === mine0.fingerprint && prof.change, `Profile's Your key shows it with Change (${JSON.stringify(prof)})`);
  ok((await keys({ action: 'change-mine', key: 'zz' })).error, '...and a pasted key that is not 64 hex characters is refused');

  // ---- Profile: the account's key store (a forge with no API to ask, so
  // the suite asks nothing of the network) -------------------------------------
  // Profile shows one section at a time beside its list: Your key store picked.
  await page.evaluate(() => [...document.querySelectorAll('.doc.on .snav [role="tab"], .doc.on .snav button')]
    .find(b => /Your key store/.test(b.textContent))?.click());
  await page.waitForSelector('#ksHost', { state: 'visible', timeout: 10000 });
  await page.fill('#ksHost', 'git.example.test');
  await page.fill('#ksToken', 'storetoken0123456789');
  await page.click('#bKsLink');
  await page.waitForFunction(() => document.querySelector('.doc.on .ksforges'), null, { timeout: 15000 });
  const store = await page.evaluate(() => ({ rows: [...document.querySelectorAll('.doc.on .ksforges .tline')].map(l => l.querySelector('.lead')?.textContent.trim()),
    show: [...document.querySelectorAll('.doc.on [data-sect="profile:mykey"] button')].map(b => b.textContent.trim()) }));
  ok(store.rows.includes('git.example.test'), `Link puts the forge in Your key store (${store.rows.join(', ')})`);
  ok(!store.show.some(w => /show|download|backup/i.test(w)), `...which has no Show, Download or backup (${store.show.join(', ')})`);
  const mine1 = await keys({ action: 'mine' });
  ok(!JSON.stringify(mine1).includes('storetoken0123456789'), '...and nothing the page reads carries the token');
  ok(!readFileSync(`${w}/config/account-secrets.json`, 'utf8').includes('storetoken0123456789'), '...kept sealed on disk');
  const kept2 = (await keys({ action: 'status' })).kept || [];
  ok(kept2.some(r => r.kind === 'forge' && r.name.endsWith('git.example.test')), 'the Keys page lists it, by name only');
  await page.click('[data-ksunlink="git.example.test"]');
  await page.waitForFunction(() => !document.querySelector('.doc.on .ksforges'), null, { timeout: 15000 });
  ok(!(await keys({ action: 'mine' })).forges.length, 'Remove takes it out');
  await keys({ action: 'link-forge', host: 'git.example.test', token: 'storetoken0123456789' });
  await page.evaluate(() => loadKeyMine());
  await page.waitForFunction(() => document.querySelector('.doc.on .ksforges'), null, { timeout: 15000 });
  await page.click('#bKsPurge');
  let purged = {};
  for (let i = 0; i < patience(40); i++){
    purged = await keys({ action: 'mine' });
    if (!(purged.forges || []).length) break;
    await sleep(250);
  }
  ok(!purged.forges.length && !purged.has, `Purge empties it after a plain confirmation, no password or code asked (${JSON.stringify(purged)})`);
  ok(page.dialogs.some(t => /Purge your key store/.test(t)), '...the confirmation it asked');
  await keys({ action: 'link-forge', host: 'git.example.test', token: 'storetoken0123456789' });
  const adm = await keys({ action: 'purge-for', account: OWNER.username });
  ok(adm.ok && !(await keys({ action: 'mine' })).forges.length, 'an administrator purges an account\'s key store from its name');

  // ---- on a phone ------------------------------------------------------------------
  const phone = await newPage(browser, { httpCredentials: OWNER, extraHTTPHeaders: { Authorization: AUTH },
                                         viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  await phone.goto(base + '/#/controller/keys');
  await phone.waitForSelector('.doc.on .keystab .keystbl', { state: 'attached', timeout: 20000 });
  const wide = await phone.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  ok(wide <= 0, `the page fits a phone's width (${wide}px over)`);
  await done(browser);
} finally {
  proc.kill('SIGTERM');
}
