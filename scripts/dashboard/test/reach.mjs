// Where the bell reaches you (R149): the Profile section lists nothing at
// first, Add a webhook with its fields and the kinds it takes, Test sends
// a line the harness's own receiver gets, the row says it was sent, the
// Keys page lists the destination's address as sealed, and Remove takes
// it away. The minute loop itself is unit-tested (reach.tick).
import { URL as BASE, launch, newPage, done, ok, patience, settled } from './lib.mjs';
import { createServer } from 'node:http';

const got = [];
const hook = createServer((req, res) => {
  let body = '';
  req.on('data', c => { body += c; });
  req.on('end', () => { got.push({ path: req.url, body }); res.writeHead(200); res.end('ok'); });
});
await new Promise(r => hook.listen(0, '127.0.0.1', r));
const HOOK = `http://127.0.0.1:${hook.address().port}/bell`;

const browser = await launch();
const page = await newPage(browser);
await page.goto(BASE);
await page.waitForFunction(() => typeof state !== 'undefined' && state && state.repos);
await page.evaluate(() => openProfileTab());
// The Profile is a list of its sections beside the one picked (the
// operator, 16 Oct): the reach section is picked first, then drawn.
await page.waitForSelector('.profiletab .snav [data-spick="reach"]', { timeout: patience(20000) });
await page.click('.profiletab .snav [data-spick="reach"]');
await page.waitForSelector('.doc details[data-sect="profile:reach"]', { timeout: patience(20000) });
await page.waitForFunction(() => document.querySelector('[data-reachadd="webhook"]'), null, { timeout: patience(15000) });
await settled(page);
ok(await page.$eval('.doc details[data-sect="profile:reach"]', d => /Nothing yet/.test(d.textContent)), 'nothing reaches you yet, said in words');

// Add a webhook: the form for its kind, the fields, the kinds, Save.
await page.click('[data-reachadd="webhook"]');
await page.waitForSelector('[data-reachform="webhook"]', { timeout: patience(10000) });
await page.fill('#pfReachName', 'the harness');
await page.fill('#pfReachF_url', HOOK);
await page.evaluate(() => { document.querySelector('[data-reachk="sync"]').checked = false; });
await page.click('[data-reachsave]');
await page.waitForSelector('details[data-sect="profile:reach-webhook"] .row[data-reach]', { timeout: patience(15000) });
const row = await page.$eval('details[data-sect="profile:reach-webhook"] .row[data-reach]', r => r.textContent.replace(/\s+/g, ' '));
ok(/the harness/.test(row) && /session asking/.test(row) && !/two places/.test(row) && !/sent/.test(row),
   `the destination is listed with what it takes and never sent (${row.slice(0, 120)})`);

// The switch (R173): off keeps the destination with its settings and says
// so; on brings it back; more than one kind is on at once, each its own block.
await page.evaluate(() => document.querySelector('details[data-sect="profile:reach-webhook"] [data-reachon]').click());
await page.waitForFunction(() => /\boff\b/.test(document.querySelector('details[data-sect="profile:reach-webhook"] .row[data-reach]')?.textContent || ''), null, { timeout: patience(15000) });
ok(await page.evaluate(() => (pfReach.dest || []).every(d => d.on === false) && pfReach.dest.length === 1), 'switched off, it stays with its settings and reads off');
await page.evaluate(() => document.querySelector('details[data-sect="profile:reach-webhook"] [data-reachon]').click());
await page.waitForFunction(() => (pfReach?.dest || []).some(d => d.on === true), null, { timeout: patience(15000) });
ok(await page.$$eval('details[data-sect^="profile:reach-"]', ds => ds.length >= 8 && ds.every(d => d.querySelector('[data-reachadd]'))),
   `every kind is a block of its own with Set up or Add another, so more than one is on at once (${await page.$$eval('details[data-sect^="profile:reach-"]', ds => ds.length)} blocks)`);

// Test: a line arrives at the receiver, and the row says sent.
await page.click('[data-reachtest]');
const arrived = await (async () => { const end = Date.now() + patience(15000); while (Date.now() < end){ if (got.length) return got[0]; await new Promise(r => setTimeout(r, 200)); } return null; })();
ok(!!arrived && /can reach you here/.test(arrived.body) && arrived.path === '/bell', `Test sends a line the receiver gets (${arrived ? arrived.body.slice(0, 60) : 'nothing'})`);
await page.waitForFunction(() => /sent/.test(document.querySelector('details[data-sect="profile:reach-webhook"] .row[data-reach]')?.textContent || ''), null, { timeout: patience(15000) });
ok(true, 'the row says it was sent');

// The secret address is kept sealed and listed on the Keys page by name only.
const kept = await page.evaluate(async () => (await (await postJSON('/api/keys', { action: 'status' })).json()).kept || []);
const mine = kept.find(k => k.kind === 'reach');
const sealing = !!(await page.evaluate(async () => (await (await postJSON('/api/keys', { action: 'status' })).json()).sealing));
ok(!!mine && /the harness/.test(mine.name) && (mine.sealed === true || !sealing),
   `the Keys page lists the destination's address${sealing ? ' as sealed' : ' (no install key here, so nothing is sealed)'} (${mine ? mine.name : 'none'})`);

// Remove: the row was just drawn again with its sent pill, so the press
// goes to the button that is there now.
await settled(page);
await page.evaluate(() => document.querySelector('details[data-sect="profile:reach-webhook"] .row[data-reach] [data-reachrm]').click());
await page.waitForSelector('.modal.askdlg:not([hidden]) button.danger', { timeout: patience(10000) });
await page.evaluate(() => document.querySelector('.modal.askdlg:not([hidden]) button.danger').click());
await page.waitForFunction(() => !document.querySelector('details[data-sect="profile:reach-webhook"] .row[data-reach]'), null, { timeout: patience(15000) });
ok(true, 'Remove takes it away');
hook.close();
await done(browser);
