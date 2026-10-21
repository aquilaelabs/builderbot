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
// Straight to Home by its address: landing on the account's saved front tab
// (Projects) toured that page first whenever the boot outlasted the tour's
// delay, which is right for a person and a race for this check.
await page.goto(URL.replace(/\/?$/, '/') + '#/home');
await ready(page);
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

// Never over the setup page, which is the whole page until Finish.
const overSetup = await page.evaluate(async () => {
  const was = state.settings.settings.setup_done, seen = state.tour;
  state.settings.settings.setup_done = { value: false };
  state.tour = { seen: [], off: false };     // a page not toured, so only the setup page holds it
  tourAsked.clear(); tourSoon(tabOf(panes[0])?.kind);
  await new Promise(r => setTimeout(r, 1200));
  const shown = !$('tourCard')?.hidden;
  state.settings.settings.setup_done = was; state.tour = seen;
  return shown;
});
ok(!overSetup, 'no tour starts while the setup page is up');

// Nor over a page's placeholder: the draw after its data has landed asks
// again (the operator, 21 Oct).
const overShimmer = await page.evaluate(async () => {
  const seen = state.tour;
  state.tour = { seen: [], off: false };
  const ph = document.createElement('div'); ph.className = 'loading skel';
  document.querySelector('.doc.on')?.appendChild(ph);
  tourAsked.clear(); tourSoon(tabOf(panes[0])?.kind);
  await new Promise(r => setTimeout(r, 1200));
  const during = !$('tourCard')?.hidden;
  ph.remove(); tourSoon(tabOf(panes[0])?.kind);
  await new Promise(r => setTimeout(r, 1200));
  const after = !$('tourCard')?.hidden;
  const shade = getComputedStyle($('tourRing')).boxShadow;
  tourEnd?.(); state.tour = seen;
  return { during, after, shade };
});
ok(!overShimmer.during && overShimmer.after, `no tour over a placeholder, and one once the page has drawn (${JSON.stringify(overShimmer)})`);
ok(/9999px/.test(overShimmer.shade) && /0\.35/.test(overShimmer.shade), `...and the page is shaded around the part a step is about (${overShimmer.shade})`);

// An empty page's step about its rows shows an example of one, inert, and
// takes it away after (the operator, 21 Oct).
const sample = await page.evaluate(async () => {
  const seen = state.tour;
  state.tour = { seen: [], off: false };
  openVmsTab();
  await new Promise(r => setTimeout(r, 1500));
  tourAsked.clear(); tourSoon('vms');
  for (let i = 0; i < 30 && !tourKind; i++) await new Promise(r => setTimeout(r, 100));
  while (tourKind && tourI < tourSteps.length - 1 && !$('tourSample')) tourGo(1);
  const box = $('tourSample');
  const out = { shown: !!box, inert: !!box?.inert, example: /example/.test(box?.textContent || ''),
                row: !!box?.querySelector('[data-vm-key]'), empty: !(vmsData?.vms || []).length };
  tourEnd(false);
  out.gone = !$('tourSample');
  // tourEnd's save goes out unawaited: let it land before the next check
  // resets the account, or it lands after and marks the pages toured.
  await new Promise(r => setTimeout(r, 1000));
  state.tour = seen;
  openHome();
  return out;
});
ok(sample.empty && sample.shown && sample.inert && sample.example && sample.row && sample.gone,
   `an empty VMs page's tour shows an example VM, inert and marked, gone after (${JSON.stringify(sample)})`);

// On a phone the card is a sheet from the bottom edge.
await prefs({ tour_seen: [], tour_off: false });
const phone = await newPage(browser, { tour: true, viewport: { width: 393, height: 852 }, isMobile: true, hasTouch: true });
await phone.goto(URL);
await ready(phone);
await phone.waitForSelector('#tourCard:not([hidden])', { timeout: 15000 });
const sheet = await phone.evaluate(() => { const r = $('tourCard').getBoundingClientRect(); return { sheet: $('tourCard').classList.contains('sheet'), bottom: Math.round(innerHeight - r.bottom), left: Math.round(r.left), width: Math.round(r.width) }; });
ok(sheet.sheet && sheet.bottom <= 1 && sheet.left === 0 && sheet.width === 393, `on a phone the tour is a sheet across the bottom (${JSON.stringify(sheet)})`);
// ...and an empty VMs page there shows its example VM too (the operator, 21
// Oct: the step's broad selector took the page's own notice for a row).
const phoneSample = await phone.evaluate(async () => {
  tourEnd(false);
  await new Promise(r => setTimeout(r, 1000));
  state.tour = { seen: [], off: false };
  openVmsTab();
  for (let i = 0; i < 100 && (!vmsData || tourLoading()); i++) await new Promise(r => setTimeout(r, 100));
  tourAsked.clear(); tourSoon('vms');
  for (let i = 0; i < 50 && !tourKind; i++) await new Promise(r => setTimeout(r, 100));
  while (tourKind && tourI < tourSteps.length - 1) tourGo(1);
  const out = { step: tourI, shown: !!$('tourSample'), row: !!$('tourSample')?.querySelector('[data-vm-key]') };
  tourEnd(false);
  await new Promise(r => setTimeout(r, 1000));
  return out;
});
ok(phoneSample.shown && phoneSample.row, `...and on a phone an empty VMs page's last step shows an example VM (${JSON.stringify(phoneSample)})`);
await prefs({ tour_seen: [], tour_off: true });
await done(browser);
