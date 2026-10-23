// Two-factor sign-in (R127): an account adds an authenticator on Profile and
// signs in through it, through a recovery code once, through a remembered
// browser and through a passkey (Chrome's virtual authenticator over CDP);
// its password alone opens nothing, Basic auth included; the bell asks an
// account with none to add one; a role can require it, and an account in
// that role meets the setup page before anything else; wrong codes are held.
import { launch, ok, done, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { createHmac } from 'node:crypto';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const BASE = URL.replace(/\/$/, '');
const bbUsers = (args, input) => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', ...args],
  { input, encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const basic = (u, p) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${p}`).toString('base64'), 'Content-Type': 'application/json' });
const owner = basic('test', 'test');
const api = (path, h, body) => fetch(BASE + path, body ? { method: 'POST', headers: h, body: JSON.stringify(body) } : { headers: h });

function b32(s){
  const al = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const ch of s.replace(/[\s=]/g, '').toUpperCase()) bits += al.indexOf(ch).toString(2).padStart(5, '0');
  return Buffer.from(bits.match(/.{8}/g).map(b => parseInt(b, 2)));
}
function totp(key, at = Date.now() / 1000){
  const buf = Buffer.alloc(8);
  buf.writeBigUInt64BE(BigInt(Math.floor(at / 30)));
  const h = createHmac('sha1', key).update(buf).digest();
  const o = h[h.length - 1] & 15;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1e6).padStart(6, '0');
}

bbUsers(['add', 'twofa', '--role', 'admin'], 'twofapass11\ntwofapass11\n');
bbUsers(['add', 'twofb', '--role', 'user'], 'twofbpass22\ntwofbpass22\n');

const browser = await launch();
async function signIn(user, pw, { host = BASE } = {}){
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  await ctx.addInitScript(() => { window.BB_NO_TOUR = true; });
  const page = await ctx.newPage();
  page.dialogs = [];
  await page.goto(host + '/login');
  await page.fill('#u', user);
  await page.fill('#p', pw);
  await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
  return { ctx, page };
}
const onStep2 = page => page.$eval('form', f => f.getAttribute('action')).then(a => a === '/login/2fa', () => false);
const inDashboard = page => page.waitForFunction(() => typeof state !== 'undefined' && state && state.boot, null, { timeout: 30000 })
  .then(() => true, () => false);

// ---- an account with none: the bell asks, and the password opens it ----
let { ctx, page } = await signIn('twofa', 'twofapass11');
ok(await inDashboard(page), 'an account with no second factor signs in with its password, as before');
await page.waitForFunction(() => !!state?.two_factor_due, null, { timeout: 20000 });
ok(true, 'the bell carries a standing notice to turn on two-factor sign-in');

// ---- Profile: add the authenticator by its secret and a first code -----
await page.evaluate(() => openProfileTwoFactor());
await page.waitForSelector('.doc [data-tf="totp-add"]', { timeout: 20000 });
await page.click('.doc [data-tf="totp-add"]');
await page.waitForSelector('.doc .tfqr svg', { timeout: 10000 });
const secret = await page.$eval('.doc .tfadd code', c => c.textContent);
const key = b32(secret);
ok(secret.replace(/\s/g, '').length >= 32 && await page.$('.doc .tfqr svg path'), 'Add shows a QR and the secret in words');
await page.fill('#pfTfCode', totp(key));
await page.click('.doc [data-tf="totp-confirm"]');
await page.waitForSelector('.doc .tfcodes pre', { timeout: 10000 });
const codes = (await page.$eval('.doc .tfcodes pre', p => p.textContent)).trim().split('\n');
ok(codes.length === 10 && codes.every(c => /^[a-z2-9]{5}-[a-z2-9]{5}$/.test(c)), `the first factor shows ten recovery codes once (${codes.length})`);
await page.click('.doc [data-tf="codes-done"]');
await page.waitForFunction(() => !document.querySelector('.doc .tfcodes'), null, { timeout: 5000 });
await page.evaluate(() => refresh());
await page.waitForFunction(() => !state?.two_factor_due, null, { timeout: 20000 });
ok(true, '...and the bell\'s notice goes the moment one is added');
await ctx.close();

// ---- the password alone opens nothing, Basic included ------------------
const b = await api('/api/status', basic('twofa', 'twofapass11'));
ok(b.status === 401 && /two-factor/.test((await b.json()).error), 'Basic auth with the password alone is refused, and says why');

// ---- sign in: a wrong code, then the app's -----------------------------
({ ctx, page } = await signIn('twofa', 'twofapass11'));
ok(await onStep2(page), 'the password leads to the second step, not the dashboard');
ok(!(await api('/api/status', { Cookie: (await ctx.cookies()).map(c => `${c.name}=${c.value}`).join('; ') })).ok,
   '...and the cookie it holds there opens nothing');
await page.fill('#c', totp(key) === '000000' ? '111111' : '000000');
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
ok(await page.$eval('.err', e => /not right/.test(e.textContent)).catch(() => false), 'a wrong code is said so, on the same step');
await page.fill('#c', totp(key, Date.now() / 1000 + 30));
await page.check('input[name=remember]');
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
ok(await inDashboard(page), 'the code the app shows signs in');
// Remembered: signed out and in again, no second step.
await page.goto(BASE + '/logout');
await page.fill('#u', 'twofa'); await page.fill('#p', 'twofapass11');
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
ok(await inDashboard(page), 'a browser remembered for 30 days asks for no second factor');
const prof = await (await page.evaluate(() => fetch('/api/profile').then(r => r.json())));
ok((prof.two_factor?.trusted || []).length === 1, '...and Profile lists it to forget');
await ctx.close();

// ---- a recovery code, once ---------------------------------------------
({ ctx, page } = await signIn('twofa', 'twofapass11'));
await page.fill('#c', codes[0]);
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
ok(await inDashboard(page), 'a recovery code signs in');
await ctx.close();
({ ctx, page } = await signIn('twofa', 'twofapass11'));
await page.fill('#c', codes[0]);
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
ok(await onStep2(page), '...once: the same code a second time does not');
await ctx.close();

// ---- the app's sign-in asks for the code too ---------------------------
const dev = await fetch(BASE + '/api/v1/device/signin', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'twofa', password: 'twofapass11', name: 'suite', kind: 'pc' }) });
ok(dev.status === 401 && (await dev.json()).second_factor === true, 'an app signing in with the password alone is asked for the code');
const dev2 = await fetch(BASE + '/api/v1/device/signin', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'twofa', password: 'twofapass11', name: 'suite', kind: 'pc', code: codes[1] }) });
ok(dev2.ok && (await dev2.json()).token, '...and signs in with it');

// ---- a passkey: added on Profile, used to sign in -----------------------
// WebAuthn takes no IP address for its site, so this part is on localhost.
const LOCAL = BASE.replace('127.0.0.1', 'localhost');
({ ctx, page } = await signIn('twofa', 'twofapass11', { host: LOCAL }));
await page.fill('#c', codes[2]);
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
await inDashboard(page);
const cdp = await ctx.newCDPSession(page);
await cdp.send('WebAuthn.enable');
const { authenticatorId } = await cdp.send('WebAuthn.addVirtualAuthenticator', { options: {
  protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } });
await page.evaluate(() => openProfileTwoFactor());
await page.waitForSelector('.doc [data-tf="passkey-add"]', { timeout: 20000 });
await page.click('.doc [data-tf="passkey-add"]');
await page.waitForSelector('.modal:not([hidden]) input', { timeout: 15000 });
await page.fill('.modal:not([hidden]) input', 'suite key');
await page.click('.modal:not([hidden]) button:has-text("Save")');
await page.waitForFunction(() => (profile?.two_factor?.passkeys || []).some(k => k.name === 'suite key'), null, { timeout: 15000 });
ok(true, 'a passkey is added on Profile by name');
const { credentials } = await cdp.send('WebAuthn.getCredentials', { authenticatorId });
await ctx.close();

({ ctx, page } = await signIn('twofa', 'twofapass11', { host: LOCAL }));
const cdp2 = await ctx.newCDPSession(page);
await cdp2.send('WebAuthn.enable');
const a2 = (await cdp2.send('WebAuthn.addVirtualAuthenticator', { options: {
  protocol: 'ctap2', transport: 'internal', hasResidentKey: true, hasUserVerification: true, isUserVerified: true, automaticPresenceSimulation: true } })).authenticatorId;
for (const c of credentials) await cdp2.send('WebAuthn.addCredential', { authenticatorId: a2, credential: c });
await page.reload();
await page.waitForSelector('#pk:not([hidden])', { timeout: 10000 });
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('#pk')]);
ok(await inDashboard(page), 'the passkey signs in at the second step');
await ctx.close();

// ---- a role that requires it -------------------------------------------
await api('/api/roles', owner, { action: 'set', name: 'twofa-role', scope: 'global', perms: {}, note: 'needs a second factor' });
await api('/api/roles', owner, { action: 'assign', name: 'twofb', roles: ['twofa-role'] });
const req = await (await api('/api/roles', owner, { action: 'two-factor', name: 'twofa-role', on: true })).json();
ok(req.ok && req.two_factor, 'an administrator requires a second factor of a role');
({ ctx, page } = await signIn('twofb', 'twofbpass22'));
await page.waitForURL(/\/login\/setup$/, { timeout: 15000 }).catch(() => {});
ok(new globalThis.URL(page.url()).pathname === '/login/setup', 'an account in that role without one meets the setup page first');
const blocked = await page.evaluate(() => fetch('/api/status').then(r => r.json().then(j => [r.status, j.two_factor_setup])));
ok(blocked[0] === 403 && blocked[1] === true, '...and reaches nothing else meanwhile');
await page.waitForSelector('#sec:not(:empty)', { timeout: 10000 });
const key2 = b32((await page.$eval('#sec', e => e.textContent)).replace(/^Secret:\s*/, ''));
await page.fill('#c', totp(key2));
await page.click('button[type=submit]');
await page.waitForSelector('#rc:not([hidden]) pre', { timeout: 10000 });
ok((await page.$eval('#codes', e => e.textContent.trim().split('\n').length)) === 10, '...where it adds one and is shown its recovery codes');
await Promise.all([page.waitForNavigation().catch(() => {}), page.click('a.go')]);
ok(await inDashboard(page), '...and then reaches the dashboard');
await ctx.close();
await api('/api/roles', owner, { action: 'two-factor', name: 'twofa-role', on: false });

// ---- wrong codes are held ----------------------------------------------
({ ctx, page } = await signIn('twofa', 'twofapass11'));
let held = false;
for (let i = 0; i < 11 && !held; i++){
  await page.fill('#c', '000000');
  await Promise.all([page.waitForNavigation().catch(() => {}), page.click('button[type=submit]')]);
  held = await page.$eval('.err', e => /Too many wrong codes/.test(e.textContent)).catch(() => false);
}
ok(held, 'ten wrong codes hold the account for a while, and say so');
await ctx.close();
await done(browser);
