#!/usr/bin/env node
// The first-use tour (R94): the first time an account opens a page, its tour
// stands over it with the step's part ringed; Next and Back walk it, Done
// ends it and the page is not toured again, on this browser or another;
// Skip tour with its box ticked skips every page's; Show the tours again in
// About and on Profile brings them back. A phone's is a sheet.
import { URL, launch, newPage, ok, done, ready } from './lib.mjs';

const browser = await launch();
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const base = URL.replace(/\/$/, '');
const prefs = async p => (await fetch(base + '/api/users', { method: 'POST', headers: H, body: JSON.stringify({ action: 'prefs', prefs: p }) })).json();
await prefs({ tour_seen: [], tour_off: false, welcome_seen: true });

const page = await newPage(browser, { tour: true, viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);
// Home, opened at once: whatever page the browser landed on is left before
// its tour can start, and that one waits for its own next visit.
await page.evaluate(() => openHome());
await page.waitForSelector('#tourCard:not([hidden])', { timeout: 15000 });
const first = await page.evaluate(() => ({ step: $('tourCard').querySelector('.tourstep').textContent,
  say: $('tourCard').querySelector('.toursay').textContent, ring: $('tourRing').hidden, back: !!$('tourBack'),
  skip: !!$('tourSkip'), box: !!$('tourAll') }));
ok(/^1 of \d+$/.test(first.step) && /Welcome to BuilderBot/.test(first.say) && first.ring && !first.back && first.skip && first.box,
   `a first visit to Home opens its tour: the first step is the page's whole, no ring, no Back, Skip tour and its box (${first.step})`);
await page.click('#tourNext');
await page.waitForTimeout(400);           // the ring's glide to its part
const second = await page.evaluate(() => {
  const r = $('tourRing').getBoundingClientRect(), rail = ($('rail') || document.querySelector('.railbar')).getBoundingClientRect();
  return { step: $('tourCard').querySelector('.tourstep').textContent, ring: !$('tourRing').hidden,
           over: Math.abs(r.left - rail.left) < 12 && Math.abs(r.top - rail.top) < 12, back: !!$('tourBack') };
});
ok(/^2 of/.test(second.step) && second.ring && second.over && second.back,
   `Next moves to the rail, ringed, with Back now offered (${JSON.stringify(second)})`);
await page.click('#tourBack');
ok(/^1 of/.test(await page.$eval('#tourCard .tourstep', e => e.textContent)), '...and Back goes back');
// Done on the last step ends it, and Home is toured for this account.
for (let i = 0; i < 12 && await page.$('#tourCard:not([hidden])'); i++) await page.click('#tourNext');
await page.waitForFunction(() => $('tourCard').hidden, null, { timeout: 5000 });
const saved = await (await fetch(base + '/api/status', { headers: H })).json();
ok((saved.tour?.seen || []).includes('home') && !saved.tour.off, `Done ends it, and the account keeps that Home was toured (${JSON.stringify(saved.tour)})`);
await page.evaluate(() => drawPanes());
await page.waitForTimeout(1200);
ok(await page.$eval('#tourCard', c => c.hidden), '...so drawing Home again does not tour it again');

// Another page has its own, once; Skip tour with the box skips them all.
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('#tourCard:not([hidden])', { timeout: 15000 });
ok(/Every project you work on/.test(await page.$eval('#tourCard .toursay', e => e.textContent)),
   'the first visit to another page opens that page\'s tour');
await page.check('#tourAll');
await page.click('#tourSkip');
const off = await (await fetch(base + '/api/status', { headers: H })).json();
ok(off.tour?.off === true && off.tour.seen.includes('projects'), `Skip tour with its box ticked skips every page's (${JSON.stringify(off.tour)})`);
await page.evaluate(() => openNodesTab());
await page.waitForTimeout(1500);
ok(await page.$eval('#tourCard', c => c.hidden), '...and a page not toured yet opens with none');

// Show the tours again, from About.
await page.evaluate(() => openAbout('guide'));
await page.waitForSelector('#aboutModal:not([hidden]) #aboutTours', { timeout: 10000 });
await page.click('#aboutTours');
await page.waitForFunction(async () => true);
const back = await (await fetch(base + '/api/status', { headers: H })).json();
ok(!back.tour?.off && !(back.tour?.seen || []).length, `About's Show the tours again clears what was seen and the box (${JSON.stringify(back.tour)})`);
await page.click('#aboutClose');
await page.evaluate(() => { tourAsked.clear(); drawPanes(); });
await page.waitForSelector('#tourCard:not([hidden])', { timeout: 15000 });
ok(/Nodes are the machines/.test(await page.$eval('#tourCard .toursay', e => e.textContent)), '...and the page in front tours again');
await page.click('#tourSkip');

// On a phone the card is a sheet from the bottom edge.
await prefs({ tour_seen: [], tour_off: false });
const phone = await newPage(browser, { tour: true, viewport: { width: 393, height: 852 }, isMobile: true, hasTouch: true });
await phone.goto(URL);
await ready(phone);
await phone.waitForSelector('#tourCard:not([hidden])', { timeout: 15000 });
const sheet = await phone.evaluate(() => { const r = $('tourCard').getBoundingClientRect(); return { sheet: $('tourCard').classList.contains('sheet'), bottom: Math.round(innerHeight - r.bottom), left: Math.round(r.left), width: Math.round(r.width) }; });
ok(sheet.sheet && sheet.bottom <= 1 && sheet.left === 0 && sheet.width === 393, `on a phone the tour is a sheet across the bottom (${JSON.stringify(sheet)})`);
await prefs({ tour_seen: [], tour_off: true });
await done(browser);
