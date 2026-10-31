#!/usr/bin/env node
// The first-use tour (R94): the first time an account opens a page, its tour
// stands over it with the step's part ringed; Next and Back walk it, Done
// ends it and the page is not toured again, on this browser or another;
// Skip tour with its box ticked skips every page's; Show the tours again in
// About brings them back. A phone's is a sheet.
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
// Close is all a person does: no reload and no redraw by hand (the
// operator, 26 Oct: the tour waited for a refresh).
await page.click('#aboutClose');
await page.waitForSelector('#tourCard:not([hidden])', { timeout: 15000 });
ok(/Nodes are the machines/.test(await page.$eval('#tourCard .toursay', e => e.textContent)), '...and the page in front tours again');
// Another page opened from the rail with that tour up: it is put away,
// not counted as seen, and the page opened tours (it stood over the next
// page, and that page's own never came).
await page.click('[data-rail="jobs"]');
await page.waitForFunction(() => tourKind === 'jobs' && !$('tourCard').hidden, null, { timeout: 15000 }).catch(() => {});
const moved = await page.evaluate(() => ({ kind: tourKind, card: !$('tourCard').hidden, nodes: tourSeen().has('nodes') }));
ok(moved.kind === 'jobs' && moved.card && !moved.nodes,
   `a tour up when another page is opened gives way to that page's, the one left not counted as seen (${JSON.stringify(moved)})`);
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
  // Up to ten seconds for the tour to come, not a fixed second a loaded
  // gate outran (B384).
  for (let i = 0; i < 100 && $('tourCard')?.hidden !== false; i++) await new Promise(r => setTimeout(r, 100));
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

// The page redrawing itself under the step (its own poll, not the panes'
// draw) puts the example back and the ring around it (B215, the operator,
// 22 Oct: a ring around nothing after Reset tours); a placeholder the page
// keeps hidden does not hold the tour back (B216: Containers had none); and
// a poll answering with the old list after Reset does not undo it (B217).
const tours = await page.evaluate(async () => {
  const seen = state.tour;
  const wait = async f => { for (let i = 0; i < 40 && !f(); i++) await new Promise(r => setTimeout(r, 100)); return f(); };
  state.tour = { seen: [], off: false };
  openVmsTab();
  await new Promise(r => setTimeout(r, 1500));
  tourAsked.clear(); tourSoon('vms');
  await wait(() => tourKind);
  while (tourKind && tourI < tourSteps.length - 1 && !$('tourSample')) tourGo(1);
  $('tourSample')?.remove();
  const back = await wait(() => $('tourSample'));
  const b = $('tourSample')?.getBoundingClientRect(), r = $('tourRing').getBoundingClientRect();
  const ringed = !!b && Math.abs(r.top - (b.top - 4)) < 2 && Math.abs(r.height - (b.height + 8)) < 2;
  tourEnd(false);
  await new Promise(r => setTimeout(r, 1000));
  state.tour = { seen: [], off: false };
  openDocker();
  await new Promise(r => setTimeout(r, 1500));
  const hid = document.createElement('div');
  hid.className = 'loading skel'; hid.hidden = true;
  document.querySelector('.doc.on')?.appendChild(hid);
  tourAsked.clear(); tourSoon('docker');
  const docker = await wait(() => tourKind === 'docker');
  hid.remove();
  tourEnd(false);
  await new Promise(r => setTimeout(r, 1000));
  // A poll that left before the reset, answering after it.
  const poll = refresh();
  await tourReset();
  await poll;
  await new Promise(r => setTimeout(r, 1500));
  const kept = !tourSeen().has('vms') && !tourSeen().has('docker');
  tourEnd(false);
  await new Promise(r => setTimeout(r, 1000));
  state.tour = seen;
  openHome();
  return { back: !!back, ringed, docker, kept };
});
ok(tours.back && tours.ringed, `a page's own redraw under a step puts its example back, and the ring around it (${JSON.stringify(tours)})`);
ok(tours.docker, `...a placeholder the page keeps hidden does not hold the Containers tour back (${tours.docker})`);
ok(tours.kept, `...and a poll with the old list after Show the tours again does not undo it (${tours.kept})`);

// With other pages kept in the pane before it (Home, Containers), the
// example goes into the page on show, not the first kept (B223, the
// operator, 22 Oct: a ring around an empty box on VMs after Home).
const after = await page.evaluate(async () => {
  const seen = state.tour;
  const wait = async f => { for (let i = 0; i < 40 && !f(); i++) await new Promise(r => setTimeout(r, 100)); return f(); };
  state.tour = { seen: ['home', 'docker'], off: false };
  openHome(); await new Promise(r => setTimeout(r, 800));
  openDocker(); await new Promise(r => setTimeout(r, 1200));
  tourEnd(false);
  state.tour = { seen: ['home', 'docker'], off: false };
  openVmsTab(); await new Promise(r => setTimeout(r, 1500));
  tourAsked.clear(); tourSoon('vms');
  await wait(() => tourKind === 'vms');
  while (tourKind && tourI < tourSteps.length - 1 && !$('tourSample')) tourGo(1);
  const sm = $('tourSample');
  const out = { kept: document.querySelectorAll('#pane0 .doctab').length, inVms: !!sm?.closest('.vmtab'), shown: !!sm?.checkVisibility() };
  tourEnd(false);
  await new Promise(r => setTimeout(r, 1000));
  state.tour = seen;
  openHome();
  return out;
});
ok(after.kept >= 2 && after.inVms && after.shown,
   `with Home and Containers kept in the pane, the VMs page's example goes into the VMs page and shows (${JSON.stringify(after)})`);

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

// Projects' tour turns a card over for the steps about its back (the
// operator, 26 Oct): the first card on the page, turned back after; and on a
// page with none, the example card, which turns over in place.
const flips = await page.evaluate(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const ringOn = sel => { const r = $('tourRing').getBoundingClientRect(), t = document.querySelector(sel)?.getBoundingClientRect();
    return !!t && !$('tourRing').hidden && r.left <= t.left + 1 && r.right >= t.right - 1 && r.top <= t.top + 1 && r.bottom >= t.bottom - 1; };
  openProjectsTab(); await sleep(1200);
  tourAsked.clear(); tourStart('projects'); await sleep(300);
  tourGo(1); tourGo(1); tourGo(1); await sleep(900);
  const card = document.querySelector('#pane0 .pgrid .pcard[data-pkey]');
  const real = { steps: tourSteps.length, turned: card.classList.contains('flipped'), ringed: ringOn('#pane0 .pcard.flipped .pcback .pcrepo'),
                 sample: !!$('tourSample') };
  tourEnd(false); await sleep(600);
  real.back = !card.isConnected || !document.querySelector(`#pane0 .pcard[data-pkey="${card.dataset.pkey}"]`).classList.contains('flipped');
  pjQuery = 'no-project-is-called-this'; drawProjects(state.projects); await sleep(300);
  tourAsked.clear(); tourStart('projects'); await sleep(300);
  tourGo(1); tourGo(1); await sleep(300);
  const ex = { front: !!document.querySelector('#tourSample .pcard:not(.flipped)'), ringed: ringOn('#tourSample .pcard .pcfront') };
  tourGo(1); await sleep(900);
  ex.turned = !!document.querySelector('#tourSample .pcard.flipped'); ex.ringedBack = ringOn('#tourSample .pcard .pcback .pcrepo');
  tourGo(1); await sleep(300);
  ex.foot = ringOn('#tourSample .pcard .pcback .pcfoot');
  tourEnd(false); await sleep(300);
  ex.gone = !$('tourSample');
  pjQuery = ''; drawProjects(state.projects);
  return { real, ex };
});
ok(flips.real.steps === 6 && flips.real.turned && flips.real.ringed && !flips.real.sample && flips.real.back,
   `the Projects tour turns the first card over for its back's steps, ringing each part, and turns it back after (${JSON.stringify(flips.real)})`);
ok(flips.ex.front && flips.ex.ringed && flips.ex.turned && flips.ex.ringedBack && flips.ex.foot && flips.ex.gone,
   `...and with no project, an example card, its front then its back as it turns over (${JSON.stringify(flips.ex)})`);

// Every page on the rail has a tour, and each step's part is on the page as
// it is now (R142): a step whose part went with a redesign is left out by
// tourStart, so a tour shrank without anybody seeing it. A step the
// fixture's world cannot show is named here with why.
const UNSHOWN = {
  // the fixture's node has no nginx deployed: one line and Deploy
  nginx: [2],
  // the chips come with jobs in two states or more, which the fixture has not
  jobs: [1],
};
for (const p of [page, phone]){
  const where = p === phone ? 'on a phone' : 'at a desk';
  const kinds = await p.evaluate(() => [...RAIL.flatMap(g => g.tools.map(([k]) => [k, g.key])), ['notebook', '']]);
  // The Debug page excepted: not an advertised feature (the operator, 26 Oct).
  const untoured = await p.evaluate(ks => ks.map(([k]) => k).filter(k => !TOUR_STEPS[k] && k !== 'debug'), kinds);
  ok(!untoured.length, `every page on the rail has a tour ${where}${untoured.length ? `: none for ${untoured.join(', ')}` : ''}`);
  const lost = [];
  // A page this install does not offer (This machine on a container
  // install) lands on its group's first page, which is not it.
  const offered = await p.evaluate(ks => ks.filter(([k]) => k === 'notebook' || railAllows(k)), kinds);
  for (const [k, g] of offered){
    if (k === 'notebook') await p.evaluate(() => openNotebook('alpha', 'overview'));
    else await p.evaluate(([g, k]) => { location.hash = g === k ? `#/${g}` : `#/${g}/${k}`; }, [g, k]);
    await p.waitForFunction(k => tabOf(panes[0])?.kind === k && !tourLoading(), k, { timeout: 15000 }).catch(() => {});
    await p.waitForTimeout(600);
    const miss = await p.evaluate(k => (TOUR_STEPS[k] || []).map((s, j) => s.at && !s.sample && !tourTarget(s.at) ? j : -1).filter(j => j >= 0), k);
    for (const j of miss) if (!(UNSHOWN[k] || []).includes(j)) lost.push(`${k} step ${j + 1}`);
  }
  ok(!lost.length, `each tour step points at a part that is on its page ${where}${lost.length ? `: not found for ${lost.join(', ')}` : ''}`);
}
await done(browser);
