// First run (R199, R267): after the owner is made, the page is the setup
// page until Finish: four step cards at the reading width with nothing
// beside them (no rail, no panes, so no dock, no search), each with its
// state and its own action; the node's buttons open the Nodes page's own
// dialogs; the name and email step saves to the profile; Finish waits for
// a node and lands on Home, whose Getting started card keeps what is left.
// The fixture starts with setup done, so it is put back to first run here,
// as making the owner does, and Finish puts it right again.
import { URL, launch, newPage, ok, done, sleep } from './lib.mjs';

const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const base = URL.replace(/\/$/, '');
const api = async (path, body) => {
  const r = await fetch(base + path, body === undefined ? { headers: auth }
    : { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.status === 204 ? {} : r.json();
};
const firstRun = async on => api('/api/settings', { set: { setup_done: !on } });

const browser = await launch();
for (const [where, vp] of [['at a desk', { viewport: { width: 1280, height: 900 } }],
                           ['on a phone', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }]]){
  const r = await firstRun(true);
  ok(!r.error, `first run turned back on for the walk ${where} (${r.error || 'ok'})`);
  const page = await newPage(browser, vp);
  await page.goto(URL);
  await page.waitForFunction(() => typeof state !== 'undefined' && state?.settings && document.body.classList.contains('firstrun'), null, { timeout: 20000 });
  await page.waitForSelector('#setupPanel .setstep', { timeout: 20000 });

  // ---- the page, and nothing beside it ---------------------------------------
  const frame = await page.evaluate(() => {
    const vis = s => { const e = document.querySelector(s); return !!e && e.offsetWidth > 0 && getComputedStyle(e).display !== 'none'; };
    const steps = [...document.querySelectorAll('#setupPanel .setstep')].map(s => ({
      title: s.querySelector('h3')?.textContent.trim(), state: s.querySelector('.setstephead .pill')?.textContent.trim() }));
    const page = document.querySelector('#setupPanel .setuppage').getBoundingClientRect();
    return { steps, rail: vis('#rail'), panes: vis('#panes'), jump: vis('#jump'), bell: vis('#bBell'),
             about: !document.getElementById('aboutModal').hidden, width: Math.round(page.width), inner: innerWidth };
  });
  ok(frame.steps.map(s => s.title).join(' | ') === 'Your first node | Your name and email | Claude Code on your node | A first project',
     `the setup page is four steps, in order, ${where} (${frame.steps.map(s => s.title).join(' | ')})`);
  ok(frame.steps.every(s => /^(to do|waiting|done)$/.test(s.state || '')),
     `...each with its state as a pill (${frame.steps.map(s => s.state).join(', ')})`);
  ok(!frame.rail && !frame.panes && !frame.jump && !frame.bell,
     `...and nothing beside it: no rail, no panes and so no dock, no search, no bell (${JSON.stringify(frame)})`);
  ok(!frame.about, '...and the Getting started guide does not open over it (B839)');
  ok(frame.width <= Math.min(frame.inner, 1100), `...at the reading width (${frame.width} of ${frame.inner})`);

  // ---- the node: the Nodes page's own dialogs, and its state -------------------
  const nodeDone = frame.steps[0].state === 'done';
  if (!nodeDone){
    await page.click('#setupPanel [data-setenroll]');
    await page.waitForFunction(() => !document.getElementById('ndmodal').hidden && document.getElementById('ndBody').textContent.includes('Name'),
      null, { timeout: 10000 });
    ok(true, `Enroll node in the node step opens the Nodes page's own dialog ${where}`);
    await page.keyboard.press('Escape');
    await page.evaluate(() => { document.getElementById('ndmodal').hidden = true; });
  } else {
    ok(await page.evaluate(() => !document.querySelector('#setupPanel [data-setenroll]')),
       `a node answering, the node step is done and offers no Enroll ${where}`);
  }
  ok(await page.evaluate(n => document.getElementById('setupFinish').disabled === !n, nodeDone),
     `Finish ${nodeDone ? 'is live with a node answering' : 'waits for a node'} ${where}`);

  // ---- the name and email: Save wakes on both, and the profile has them --------
  if (frame.steps[1].state !== 'done'){
    const dead0 = await page.evaluate(() => document.querySelector('[data-setgit]').disabled);
    await page.fill('#setName', 'First Runner');
    const dead1 = await page.evaluate(() => document.querySelector('[data-setgit]').disabled);
    await page.fill('#setEmail', 'runner@example.test');
    const dead2 = await page.evaluate(() => document.querySelector('[data-setgit]').disabled);
    ok(dead0 && dead1 && !dead2, `Save sleeps until a name and an email are both typed ${where} (${dead0} ${dead1} ${dead2})`);
    await page.click('[data-setgit]');
    await page.waitForFunction(() => [...document.querySelectorAll('#setupPanel .setstep')][1]?.querySelector('.pill')?.textContent === 'done',
      null, { timeout: 15000 }).catch(() => {});
    const prof = await api('/api/profile');
    ok(prof.git_ready !== false && await page.evaluate(() => [...document.querySelectorAll('#setupPanel .setstep')][1].querySelector('.pill').textContent === 'done'),
       `...and saving it readies the commit author and turns the step to done (${JSON.stringify(prof.git || {})})`);
  } else ok(true, `the name and email step is done for an account that has them ${where}`);

  // ---- Finish: Home, and what is left in its card -----------------------------
  if (nodeDone){
    await page.click('#setupFinish');
    await page.waitForFunction(() => !document.body.classList.contains('firstrun'), null, { timeout: 15000 });
    await page.waitForFunction(() => location.hash === '#/home' && document.querySelector('.doc.on .hometiles'), null, { timeout: 20000 });
    const card = await page.evaluate(() => {
      const c = document.querySelector('.doc.on .hstart');
      return c ? { rows: [...c.querySelectorAll('.hsrow')].map(r => `${r.classList.contains('done') ? '✓' : '·'} ${r.querySelector('.grow').textContent}`),
                   count: c.querySelector('h3 .sst')?.textContent } : null;
    });
    ok(card === null || (card.rows.length >= 2 && /^\d+ of \d+$/.test(card.count || '')),
       `Finish lands on Home, where Getting started keeps what is left ${where} (${card ? card.count + ': ' + card.rows.join('; ') : 'all four done'})`);
    if (card){
      await page.click('.doc.on .hstart [data-hstart="hide"]');
      await page.waitForFunction(() => !document.querySelector('.doc.on .hstart'), null, { timeout: 10000 });
      ok(true, '...and Put away takes the card off Home');
      await page.evaluate(() => { try{ localStorage.removeItem('bb.gsHidden'); }catch(e){} });
    }
  } else {
    await firstRun(false);
  }
  await page.close();
}
// Left as the fixture had it.
await firstRun(false);
await done(browser);
