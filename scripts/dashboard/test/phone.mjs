// The phone card: wireless adb, and pushing a Firefox extension to a handset.
//
// adb and web-ext are stubbed by the harness (see run.sh). That is not a
// shortcut — the real ones would answer from whatever is actually paired to
// the box the suite runs on, which makes the result a fact about the room
// rather than about the code.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { mkdirSync, writeFileSync, renameSync } from 'node:fs';
import { execSync } from 'node:child_process';

// A project with an extension in it, and a lookalike that must not be listed:
// npm, Android and half the world use the name manifest.json.
mkdirSync(`${DIR}/ws/alpha/webext`, { recursive: true });
writeFileSync(`${DIR}/ws/alpha/webext/manifest.json`,
  JSON.stringify({ manifest_version: 2, name: 'Probe Extension', version: '1.4.2' }));
writeFileSync(`${DIR}/ws/alpha/webext/background.js`, 'console.log(1);');
mkdirSync(`${DIR}/ws/beta/somelib`, { recursive: true });
writeFileSync(`${DIR}/ws/beta/somelib/manifest.json`,
  JSON.stringify({ name: 'not-an-extension', dependencies: {} }));

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
await page.waitForSelector('.card[data-card="phone"]', { timeout: 20000 });

const post = body => page.evaluate(async b => {
  const r = await fetch('/api/phone', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);

// ---- what it can push ------------------------------------------------------
const api = await page.evaluate(async () => (await fetch('/api/phone')).json());
const paths = (api.extensions || []).map(e => e.path);
ok(paths.includes('alpha/webext'),
   `the card finds an extension by its manifest (${paths.join(',') || 'none'})`);
ok(!paths.some(p => p.startsWith('beta/')),
   '...and a manifest.json that is not a WebExtension is not one');
ok(api.extensions.find(e => e.path === 'alpha/webext').name === 'Probe Extension',
   '...listed by the name and version the manifest gives, not by its folder');
ok(typeof api.extensions.find(e => e.path === 'alpha/webext').changed === 'number',
   '...with when it last changed, which is the question when several are listed');

// ---- what the server refuses ----------------------------------------------
// Every argument is checked against something already known. This is one of
// the few places the page causes a program to run.
for (const [what, body] of [
  ['a source outside the workspace', { action: 'push', source: '../etc', serial: '192.168.9.9:5555', apk: 'org.mozilla.firefox_beta' }],
  ['a source with no manifest', { action: 'push', source: 'alpha', serial: '192.168.9.9:5555', apk: 'org.mozilla.firefox_beta' }],
  ['an apk nobody offered', { action: 'push', source: 'alpha/webext', serial: '192.168.9.9:5555', apk: 'com.evil.app' }],
  ['a device that is not attached', { action: 'push', source: 'alpha/webext', serial: '10.0.0.1:1', apk: 'org.mozilla.firefox_beta' }],
  ['an address that is not one', { action: 'connect', ip: 'not-an-ip' }],
  ['a port that is not one', { action: 'connect', ip: '192.168.9.9', port: '99999999' }],
  ['a pairing code that is not six digits', { action: 'pair', ip: '192.168.9.9', port: '5555', code: '12' }],
  ['an action nobody offers', { action: 'reboot' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];

// ---- pushing ---------------------------------------------------------------
ok(await page.$eval('.card[data-card="phone"]', el => /Test Phone/.test(el.textContent)),
   'the card shows the connected phone by model');
await page.click('.row [data-push]');
await page.waitForFunction(() => /live/.test(
  document.querySelector('.row.phjob')?.textContent || ''), null, { timeout: 20000 });
ok(true, 'Push runs web-ext and the card goes live once the add-on is really on');
ok(/temporary/.test(await page.$eval('.row.phjob', el => el.textContent)),
   '...saying out loud that the install is temporary, because it is');
ok(await page.$eval('.row [data-push]', b => b.disabled),
   '...and a second push cannot start on top of the first');
await page.click('#phStop');
await page.waitForFunction(() => !document.querySelector('.row.phjob'),
                           null, { timeout: 20000 });
ok(true, 'Stop ends it');

// ---- browsing from the phone itself ----------------------------------------
// The IP field exists because the number has to be read off the device — and
// when the dashboard is being viewed ON that device, the server already has
// it. Offered only to an Android client: from a desktop the client address is
// the desktop's, which is not the phone, and filling it in would be a
// confident wrong answer.
const asDesktop = await page.evaluate(async () => (await fetch('/api/phone')).json());
ok(asDesktop.you === undefined,
   'from a desktop the card is not told an address — the browser is not the phone');
// From node and over the container's own LAN address, not the page: the page
// is served on loopback, and a loopback client is the container talking to
// itself rather than a handset — which the server rightly refuses to treat as
// one. This is the nearest thing to a real phone the suite can be.
const lan = execSync("hostname -i").toString().trim().split(/\s+/)[0];
const asPhone = await (await fetch(URL.replace('127.0.0.1', lan) + 'api/phone', {
  headers: { 'User-Agent': 'Mozilla/5.0 (Android 17; Mobile; rv:145.0) Firefox/145.0',
             Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') }
})).json();
ok(typeof asPhone.you === 'string' && /^\d+\.\d+\.\d+\.\d+$/.test(asPhone.you),
   `from an Android browser it offers that browser's own address (${asPhone.you})`);

// ---- without web-ext there is nothing to push with -------------------------
// Ghosted with the reason on it, rather than a button that looks alive and
// explains itself only once pressed. The stub is moved aside to get the state
// a fresh container is actually in: web-ext is not in the image.
renameSync(`${DIR}/bin/web-ext`, `${DIR}/bin/web-ext.hidden`);
await page.evaluate(() => phFetch());
await page.waitForFunction(() => document.querySelector('.row [data-push]')?.disabled,
                           null, { timeout: 15000 });
ok((await page.$eval('.row [data-push]', b => b.title)).includes('EXTRA_NPM_PACKAGES'),
   'with no web-ext, Push is dead and says how to fix it');
renameSync(`${DIR}/bin/web-ext.hidden`, `${DIR}/bin/web-ext`);
await page.evaluate(() => phFetch());
await page.waitForFunction(() => !document.querySelector('.row [data-push]')?.disabled,
                           null, { timeout: 15000 });
ok(true, '...and alive again once it is there');

// ---- a session asking to reach it -----------------------------------------
// The point of the whole arrangement: a session does not touch the handset,
// it describes what it wants and waits. The dashboard runs it on Allow, so
// "did Claude touch my phone" is answered on this card and nowhere else.
ok((await post({ action: 'ask', why: '', cmd: ['shell', 'ls'] })).body.error,
   'an ask with no reason is refused — Allow on an unexplained command is a guess');
ok((await post({ action: 'ask', why: 'poke about', cmd: [] })).body.error,
   '...and one with nothing to run is too');
const asked = await post({ action: 'ask', why: 'read the Firefox version',
                           cmd: ['shell', 'getprop', 'ro.build.version.release'] });
ok(asked.body.id > 0, 'a session can ask, and gets a number back');
await page.evaluate(() => phFetch());
await page.waitForSelector('.phask', { timeout: 15000 });
ok(/read the Firefox version/.test(await page.$eval('.phask .name', e => e.textContent)),
   '...and the card shows the reason it gave');
ok(/getprop/.test(await page.$eval('.phask .phcmd', e => e.textContent)),
   '...beside the exact command, so Allow is not a guess');
const pend = await page.evaluate(async () => (await fetch('/api/phone')).json());
ok((pend.asks || []).length === 1, '...and it is pending until answered');
await page.click('.phask [data-allow]');
await page.waitForFunction(() => !document.querySelector('.phask'),
                           null, { timeout: 20000 });
const done1 = await post({ action: 'outcome', id: asked.body.id });
ok(done1.body.state === 'done', 'Allow runs it — on the dashboard, not in the session');
const denied = await post({ action: 'ask', why: 'wipe something',
                            cmd: ['shell', 'rm', '-rf', '/sdcard/x'] });
await page.evaluate(() => phFetch());
await page.waitForSelector('.phask', { timeout: 15000 });
await page.click('.phask [data-deny]');
await page.waitForFunction(() => !document.querySelector('.phask'),
                           null, { timeout: 20000 });
ok((await post({ action: 'outcome', id: denied.body.id })).body.state === 'denied',
   'Deny stops it, and the session is told no rather than left hanging');
ok((await post({ action: 'allow', id: denied.body.id })).body.error,
   '...and an answered request cannot be answered again');
page.errors = [];   // the refusals above are 400s on purpose

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
