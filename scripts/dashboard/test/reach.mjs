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
await page.waitForFunction(() => document.querySelector('#pfReachKind'), null, { timeout: patience(15000) });
await settled(page);
ok(await page.$eval('.doc details[data-sect="profile:reach"]', d => /Nothing yet/.test(d.textContent)), 'nothing reaches you yet, said in words');

// Add a webhook: the form for its kind, the fields, the kinds, Save.
await page.selectOption('#pfReachKind', 'webhook');
await page.waitForSelector('[data-reachform="webhook"]', { timeout: patience(10000) });
await page.fill('#pfReachName', 'the harness');
await page.fill('#pfReachF_url', HOOK);
await page.evaluate(() => { document.querySelector('[data-reachk="sync"]').checked = false; });
await page.click('[data-reachsave]');
await page.waitForSelector('.pfreach .row[data-reach]', { timeout: patience(15000) });
const row = await page.$eval('.pfreach .row[data-reach]', r => r.textContent.replace(/\s+/g, ' '));
ok(/Webhook: the harness/.test(row) && /session asking/.test(row) && !/two places/.test(row) && /never/.test(row),
   `the destination is listed with what it takes and never sent (${row.slice(0, 120)})`);

// Test: a line arrives at the receiver, and the row says sent.
await page.click('[data-reachtest]');
const arrived = await (async () => { const end = Date.now() + patience(15000); while (Date.now() < end){ if (got.length) return got[0]; await new Promise(r => setTimeout(r, 200)); } return null; })();
ok(!!arrived && /can reach you here/.test(arrived.body) && arrived.path === '/bell', `Test sends a line the receiver gets (${arrived ? arrived.body.slice(0, 60) : 'nothing'})`);
await page.waitForFunction(() => /sent/.test(document.querySelector('.pfreach .row[data-reach]')?.textContent || ''), null, { timeout: patience(15000) });
ok(true, 'the row says it was sent');

// The secret address is kept sealed and listed on the Keys page by name only.
const kept = await page.evaluate(async () => (await (await postJSON('/api/keys', { action: 'status' })).json()).kept || []);
const mine = kept.find(k => k.kind === 'reach');
ok(!!mine && /the harness/.test(mine.name) && mine.sealed === true, `the Keys page lists the destination's address as sealed (${mine ? mine.name : 'none'})`);

// Remove.
await page.click('[data-reachrm]');
await page.waitForSelector('.modal:not([hidden]) button.danger', { timeout: patience(10000) });
await page.click('.modal:not([hidden]) button.danger');
await page.waitForFunction(() => !document.querySelector('.pfreach .row[data-reach]'), null, { timeout: patience(15000) });
ok(true, 'Remove takes it away');
hook.close();
await done(browser);
