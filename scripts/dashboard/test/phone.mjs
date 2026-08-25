// The phone card: pairing and connecting over wireless adb, and the questions
// a session leaves for the operator. What there is to push moved to the
// notebook's Artifacts view — the card is the connection now.
//
// adb is stubbed by the harness (see run.sh). That is not a shortcut — the
// real one answers from whatever is actually paired to the box the suite runs
// on, which makes the result a fact about the room rather than the code.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { execSync } from 'node:child_process';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
await page.waitForSelector('.card[data-card="phone"] .row', { timeout: 20000 });

const post = body => page.evaluate(async b => {
  const r = await fetch('/api/phone', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);

ok(await page.$eval('.card[data-card="phone"]', el => /Test Phone/.test(el.textContent)),
   'the card shows the connected phone by model');

// ---- what the server refuses ----------------------------------------------
for (const [what, body] of [
  ['an address that is not one', { action: 'connect', ip: 'not-an-ip' }],
  ['a port that is not one', { action: 'connect', ip: '192.168.9.9', port: '99999999' }],
  ['a pairing code that is not six digits', { action: 'pair', ip: '192.168.9.9', port: '5555', code: '12' }],
  ['an action nobody offers', { action: 'reboot' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];

// ---- browsing from the phone itself ----------------------------------------
// The IP field exists because the number has to be read off the device — and
// when the dashboard is being viewed ON that device, the server already has
// it. Offered only to an Android client: from a desktop the client address is
// the desktop's, which is not the phone, and filling it in would be a
// confident wrong answer.
const asDesktop = await page.evaluate(async () => (await fetch('/api/phone')).json());
ok(asDesktop.you === undefined,
   'from a desktop the card is not told an address — the browser is not the phone');
const lan = execSync("hostname -i").toString().trim().split(/\s+/)[0];
const asPhone = await (await fetch(URL.replace('127.0.0.1', lan) + 'api/phone', {
  headers: { 'User-Agent': 'Mozilla/5.0 (Android 17; Mobile; rv:145.0) Firefox/145.0',
             Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') }
})).json();
ok(typeof asPhone.you === 'string' && /^\d+\.\d+\.\d+\.\d+$/.test(asPhone.you),
   `from an Android browser it offers that browser's own address (${asPhone.you})`);

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
// Found on the ordinary status poll, with nothing pressed and no phFetch of
// our own. The card used to poll only when it already knew about an ask,
// which meant it could never learn about the first one: the request sat on
// the server, bb phone could see it, and the card showed nothing.
// Nothing is pressed and no fetch is triggered: the revisions poll is the
// only thing running, which is the whole point. A view says what it depends
// on and is told; it never reasons about when to re-read.
await page.waitForSelector('.phask', { timeout: 20000 });
ok(true, '...and the card finds it on its own, with nothing pressed');
// The tab says so too, for the case this exists for: the request arrives
// while somebody is looking at another tab entirely.
await page.waitForFunction(() => /^\(1\) /.test(document.title),
                           null, { timeout: 15000 });
ok(true, '...and the tab title carries the count, since the tab may not be in front');
ok(await page.evaluate(() => {
     const l = document.querySelector('link[rel="icon"][href^="data:"]');
     return !!l && l.getAttribute('href').includes('f0883e');
   }),
   '...and so does the favicon, for when the strip is too crowded for text');
ok(/read the Firefox version/.test(await page.$eval('.phask .name', e => e.textContent)),
   '...and the card shows the reason it gave');
ok(/getprop/.test(await page.$eval('.phask .phcmd', e => e.textContent)),
   '...beside the exact command, so Allow is not a guess');
ok(/left to answer/.test(await page.$eval('.phask', e => e.textContent)),
   '...and how long is left, since an Allow that has quietly stopped working '
   + 'is worse than one that says it has gone');
await page.click('.phask [data-allow]');
await page.waitForFunction(() => !document.querySelector('.phask'),
                           null, { timeout: 20000 });
await page.waitForFunction(() => document.title === 'BuilderBot',
                           null, { timeout: 15000 });
ok(true, '...and the badge clears when nothing is waiting');
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
