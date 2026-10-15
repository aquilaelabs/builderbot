// Notifications as a system (R218 step 6, the design's the-dashboard/
// notifications rule): toasts in one stack at a corner, each with its kind's
// icon and its own ×, held while the pointer is over them and each kept on
// the account's record; the bell a short list with See all; and the
// Notifications page, its asks answered on the row with the long part in a
// scrolling box, its history narrowed by chips, deleted and cleared.
import { URL, launch, newPage, ok, done, ready, sleep } from './lib.mjs';

const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const base = URL.replace(/\/$/, '');
const api = async (path, body) => {
  const r = await fetch(base + path, body === undefined ? { headers: auth }
    : { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.status === 204 ? {} : r.json();
};
const until = async (fn, ms = 15000, step = 200) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ const v = await fn(); if (v) return v; await sleep(step); }
  return null;
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);
await api('/api/notices', { action: 'clear' });

// ---- the stack -------------------------------------------------------------
{
  await page.evaluate(() => { for (let i = 1; i <= 6; i++) notify(`stack ${i}`, i === 6 ? true : i === 5 ? 'warn' : false); });
  const st = await page.evaluate(() => [...document.querySelectorAll('#toast .tst')].map(t => ({
    text: t.querySelector('.tmsg').textContent, cls: t.className, icon: !!t.querySelector('.tic svg'), x: !!t.querySelector('.tx') })));
  ok(st.length === 4 && st.at(-1).text === 'stack 6' && st[0].text === 'stack 3',
     `the toasts stack, the newest on top and at most four (${st.map(t => t.text).join(', ')})`);
  ok(/\bbad\b/.test(st.at(-1).cls) && /\bwarn\b/.test(st.at(-2).cls) && st.every(t => t.icon && t.x),
     '...each with its kind\'s icon and its own ×, a failure and a warning in their tones');
  const box = await page.$eval('#toast', el => { const r = el.getBoundingClientRect();
    return { right: innerWidth - r.right, top: r.top, header: document.querySelector('header').getBoundingClientRect().bottom,
             newestTop: [...el.children].at(-1).getBoundingClientRect().top <= el.firstElementChild.getBoundingClientRect().top }; });
  const bar = await page.$eval('.pane .bar', b => b.getBoundingClientRect().bottom);
  ok(box.right < 40 && box.top >= bar && box.top < bar + 30 && box.newestTop,
     `...at the top right, under the top bar and the page's own, the newest on top (${JSON.stringify({ ...box, bar })})`);
  await page.click('#toast .tst:last-child .tx');
  await until(() => page.evaluate(() => ![...document.querySelectorAll('#toast .tmsg')].some(t => t.textContent === 'stack 6')), 3000);
  ok(true, '...and × takes one away');
  // Held under the pointer: an info toast's four seconds stop while it is read.
  await page.evaluate(() => { document.querySelectorAll('#toast .tst').forEach(t => t.remove()); notify('read me slowly'); });
  await page.hover('#toast .tst');
  await sleep(5000);
  ok(await page.evaluate(() => [...document.querySelectorAll('#toast .tmsg')].some(t => t.textContent === 'read me slowly')),
     'a toast under the pointer stays past its time');
  await page.mouse.move(10, 10);
  await until(() => page.evaluate(() => !document.querySelector('#toast .tst')), 8000);
  ok(await page.evaluate(() => !document.querySelector('#toast .tst')), '...and goes once the pointer leaves');
}

// ---- every toast is on the record ------------------------------------------
{
  const kept = await until(async () => {
    const j = await api('/api/notices');
    return (j.notices || []).some(n => n.text === 'read me slowly') && (j.notices || []).some(n => n.text === 'stack 6' && n.level === 'bad') ? j : null;
  });
  ok(kept, 'every toast is kept on the account\'s record, with its level');
}

// ---- the bell: a short list, and See all ------------------------------------
{
  await page.click('#bBell');
  await page.waitForSelector('#bellPanel:not([hidden]) #bellAll', { timeout: 5000 });
  const recent = await page.$$eval('#bellPanel .bnote:not(.ask):not(.att)', ns => ns.length);
  ok(recent <= 5, `the bell shows the latest five of what was said (${recent})`);
  await page.click('#bellAll');
  await page.waitForFunction(() => tabOf(panes[0])?.kind === 'notices' && location.hash === '#/notifications', null, { timeout: 10000 });
  // Hidden when its closing tween lands.
  ok(await page.waitForFunction(() => document.getElementById('bellPanel').hidden, null, { timeout: 3000 }).then(() => true, () => false),
     'See all shuts the bell and opens the Notifications page, at #/notifications');
}

// ---- the page's history: chips, delete, clear --------------------------------
{
  await page.waitForSelector('.noticestab .ntrow', { timeout: 15000 });
  const n0 = await page.$$eval('.noticestab .ntrow', rs => rs.length);
  ok(n0 >= 7, `the history lists what was said (${n0} rows)`);
  await page.click('.noticestab [data-ntchip="bad"]');
  await page.waitForFunction(() => [...document.querySelectorAll('.noticestab .ntrow')].every(r => r.classList.contains('bad')), null, { timeout: 5000 });
  ok(await page.$$eval('.noticestab .ntrow', rs => rs.length === 1 && /stack 6/.test(rs[0].textContent)),
     'the Failures chip narrows it to the failures');
  await page.click('.noticestab [data-ntchip=""]');
  const first = await page.$eval('.noticestab .ntrow', r => r.dataset.nt);
  await page.click(`.noticestab [data-ntdel="${first}"]`);
  await page.waitForFunction(id => !document.querySelector(`.noticestab [data-nt="${id}"]`), first, { timeout: 10000 });
  ok(!(await api('/api/notices')).notices.some(n => n.id === first), 'a row\'s × deletes it, on the record too');
  await page.click('#ntClear');
  await page.waitForFunction(() => !document.querySelector('.noticestab .ntrow'), null, { timeout: 10000 });
  ok((await api('/api/notices')).notices.length === 0, 'Clear all empties the record, asked first');
}

// ---- an ask: answered on the row, its long part in a scrolling box -----------
{
  const answered = await page.evaluate(async () => {
    const calls = [];
    const real = phFetch;
    phFetch = body => { calls.push(body); return Promise.resolve(); };
    ph = { ...(ph || {}), asks: [{ id: 41, kind: 'container', name: 'web', node_name: 'sandbox', why: 'a container to try the site',
      cmd: ['container', 'new', 'web'], left: 300, asker: 'test', detail: 'services:\n' + '  web:\n    image: nginx\n'.repeat(80) }] };
    drawPanes();
    await new Promise(r => setTimeout(r, 300));
    const row = document.querySelector('.noticestab .ntask[data-ask="41"]');
    const onRow = !!row && !!row.querySelector('.actbar [data-ntallow="41"]') && !!row.querySelector('.actbar [data-ntdeny="41"]')
      && !row.querySelector(':scope details [data-ntallow]');
    const box = row?.querySelector('details.ntlong .ntbox');
    row.querySelector('details.ntlong').open = true;
    const scrolls = box && box.scrollHeight > box.clientHeight;
    row.querySelector('[data-ntallow="41"]').click();
    phFetch = real;
    return { onRow, scrolls, calls };
  });
  ok(answered.onRow, 'an ask is a row with Approve and Deny on it, never only inside its fold');
  ok(answered.scrolls, '...its compose file whole in a box that scrolls inside itself');
  ok(answered.calls.length === 1 && answered.calls[0].action === 'allow' && answered.calls[0].id === 41,
     `...and Approve answers it (${JSON.stringify(answered.calls)})`);
  const rec = await until(async () => ((await api('/api/notices')).notices || []).find(n => n.kind === 'ask'));
  ok(rec && /^Approved: container web on sandbox/.test(rec.text), `...an answer kept on the record as an answer (${rec?.text})`);
  await page.evaluate(() => { ph = { ...(ph || {}), asks: [] }; drawPanes(); });
}

// ---- a job's toast follows the job, and its end is kept ---------------------
{
  const q = await api('/api/v1/nodes', { action: 'exec', id: 'local', argv: ['sh', '-c', 'sleep 2; exit 4'] });
  await page.evaluate(id => notifyJob(id, 'a job from the suite'), q.job);
  const live = await page.evaluate(() => [...document.querySelectorAll('#toast .tst.job .tmsg')].map(t => t.textContent));
  ok(live.some(t => /^a job from the suite: /.test(t)), `a job's toast says the job's state as it runs (${live.join(' | ')})`);
  const end = await until(() => page.evaluate(() => [...document.querySelectorAll('#toast .tst.bad .tmsg')]
    .map(t => t.textContent).find(t => /^a job from the suite: failed/.test(t))), 30000);
  ok(end, `...and when it ends, it says how, in the outcome's tone (${end})`);
  const rec = await until(async () => ((await api('/api/notices')).notices || []).find(n => n.kind === 'job' && n.job === q.job));
  ok(rec && rec.level === 'bad', '...and the end is kept on the record as a job\'s, with the job to open');
  await page.evaluate(() => document.querySelectorAll('#toast .tst').forEach(t => t.remove()));
}

// ---- on a phone the stack spans the width under the top bar -----------------
{
  await page.setViewportSize({ width: 393, height: 851 });
  await page.evaluate(() => notify('on a phone'));
  await sleep(300);
  const r = await page.$eval('#toast .tst', t => { const b = t.getBoundingClientRect(); return { l: b.left, r: innerWidth - b.right, top: b.top,
    header: document.querySelector('header').getBoundingClientRect().bottom }; });
  ok(r.l <= 12 && r.r <= 12 && r.top >= r.header, `on a phone a toast spans the width, under the top bar (${JSON.stringify(r)})`);
  // ...and the page there shows one section, History while nothing waits.
  await page.evaluate(() => { openNotices(); notify('one for the phone'); });
  await until(() => page.evaluate(() => !!document.querySelector('.noticestab .ntrow')), 10000);
  const open = await page.$$eval('.noticestab details.sect[open]', ds => ds.map(d => d.dataset.sect));
  ok(open.length === 1 && open[0] === 'notices:history' && !(await page.$('.noticestab details[data-sect="notices:waiting"]')),
     `on a phone, with nothing waiting, the page is its History, open (${open.join(', ')})`);
  await page.setViewportSize({ width: 1280, height: 900 });
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
