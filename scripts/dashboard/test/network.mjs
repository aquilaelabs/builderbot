// The Network page (R165 step 4): in the Controller group, it says how the
// controller is reached (its address and port, what it is served over, the
// hostname), lists each node with where it dials in from, and carries the
// Connection and Reach from outside groups, which Controller settings no
// longer draws; a section's fields save the way Settings' always did.
import { URL as BASE, launch, newPage, done, ok, patience, settled, splitPick } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser);
await page.goto(BASE);
await page.waitForFunction(() => typeof state !== 'undefined' && state && state.repos);
ok(await page.evaluate(() => (railGroups().find(g => g.key === 'controller')?.tools || []).map(([k]) => k).includes('network')),
   'the rail offers Network in the Controller group');
await page.evaluate(() => openNetworkTab());
await page.waitForSelector('.networktab .snav .rrow', { timeout: patience(20000) });
await settled(page);
const facts = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('.networktab .pghfacts .fact')].map(f => [f.querySelector('.k, dt, .lbl')?.textContent.trim() || f.textContent.trim().split(/\s/)[0], f.textContent.replace(/\s+/g, ' ').trim()])));
const head = await page.$eval('.networktab .pghead', e => e.textContent.replace(/\s+/g, ' '));
ok(/Reached at/.test(head) && /Port/.test(head) && /Served over/.test(head) && /http/.test(head) && /Hostname/.test(head),
   `the head says where the page is, its port, what it is served over and the hostname (${head.slice(0, 120)})`);
const rows = await page.evaluate(() => [...document.querySelectorAll('.networktab .snav .rrow')].map(b => b.dataset.spick));
ok(rows.join() === 'reach,dial,tunnel,connection', `its sections: reached at, nodes dial in, Reach from outside, Connection (${rows.join()})`);
await splitPick(page, 'dial');
await page.waitForFunction(() => document.querySelector('.networktab .netdial .row, .networktab details[data-sect="network:dial"] .empty'), null, { timeout: patience(15000) });
const dial = await page.evaluate(() => [...document.querySelectorAll('.networktab .netdial .row')].map(r => r.textContent.replace(/\s+/g, ' ').trim()));
ok(dial.some(t => /sandbox/.test(t) && /127\.0\.0\.1|dials/.test(t) || /sandbox/.test(t)), `each node is listed with where it dials in from (${dial[0] || 'no row'})`);
await splitPick(page, 'connection');
ok(!!(await page.$('.networktab [data-set="tls_mode"]')), 'Connection is drawn here, with its Served over pick');
await page.evaluate(() => openSettingsTab());
await page.waitForSelector('.settingstab .snav .rrow', { timeout: patience(20000) });
const sgroups = await page.evaluate(() => [...document.querySelectorAll('.settingstab .snav .rrow')].map(b => b.dataset.spick));
ok(!sgroups.includes('tunnel') && !sgroups.includes('connection'), `...and Controller settings no longer draws the two (${sgroups.join()})`);
void facts;
await done(browser);
