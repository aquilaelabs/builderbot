// Notifications as a system (R218 step 6, the design's the-dashboard/
// notifications rule): toasts in one stack at a corner, each with its kind's
// icon and its own ×, held while the pointer is over them and each kept on
// the account's record; the bell a short list with See all; and the
// Notifications page, its asks answered on the row with the long part in a
// scrolling box, its history narrowed by chips, deleted and cleared.
import { URL, DIR, launch, newPage, ok, done, ready, sleep } from './lib.mjs';
import { writeFileSync, rmSync } from 'node:fs';

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
     `the toasts stack, the newest at the foot and at most four (${st.map(t => t.text).join(', ')})`);
  ok(/\bbad\b/.test(st.at(-1).cls) && /\bwarn\b/.test(st.at(-2).cls) && st.every(t => t.icon && t.x),
     '...each with its kind\'s icon and its own ×, a failure and a warning in their tones');
  const box = await page.$eval('#toast', el => { const r = el.getBoundingClientRect();
    return { left: r.left, rail: document.getElementById('rail').getBoundingClientRect().right,
             bottom: r.bottom, dock: document.querySelector('#pane1 .bar')?.getBoundingClientRect().top ?? innerHeight,
             newestFoot: [...el.children].at(-1).getBoundingClientRect().top >= el.firstElementChild.getBoundingClientRect().top }; });
  ok(box.left >= box.rail && box.left < box.rail + 30 && box.bottom <= box.dock && box.newestFoot,
     `...at the bottom left, beside the rail and above the dock's line, the newest at the foot (${JSON.stringify(box)})`);
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

// ---- a toast never sits on an open dialog ------------------------------------
// No corner is free of controls: the enroll dialog's buttons are at the left
// of its foot, and a refusal there landed on its Go. So with a dialog open
// the stack goes into the gutter beside its box, and where there is none,
// to the top, letting presses through.
const offDialog = () => page.evaluate(() => {
  const b = document.querySelector('#aboutModal > .box').getBoundingClientRect();
  const ts = [...document.querySelectorAll('#toast .tst')].map(t => t.getBoundingClientRect());
  const hit = ts.some(t => t.left < b.right && t.right > b.left && t.top < b.bottom && t.bottom > b.top);
  return { n: ts.length, hit, through: getComputedStyle(document.querySelector('#toast .tst')).pointerEvents === 'none'
    && getComputedStyle(document.querySelector('#toast .tx')).pointerEvents === 'none',
    box: [b.left, b.right].map(Math.round), toast: ts.map(t => [t.left, t.right, t.top].map(Math.round)) };
});
{
  await page.evaluate(() => { openAbout(); notify('said over a dialog', 'warn'); });
  await sleep(300);
  const d = await offDialog();
  ok(d.n === 1 && !d.hit, `with a dialog open a toast stands in the gutter beside its box, not on it (${JSON.stringify(d)})`);
  await page.evaluate(() => { document.querySelectorAll('#toast .tst').forEach(t => t.remove()); closeAbout(); notify('and after it'); });
  ok(await page.$eval('#toast', el => !el.style.cssText && !el.classList.contains('overdlg')),
     '...and with it shut, the stack is back at its corner');
  await page.evaluate(() => document.querySelectorAll('#toast .tst').forEach(t => t.remove()));
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
  // Each row says how long ago, from the seconds the record keeps (B769:
  // handed milliseconds, every row landed in the future and read "just now").
  await page.route('**/api/notices', async r => {
    const res = await r.fetch(); const j = await res.json();
    (j.notices || []).forEach(x => { x.at -= 7200; });
    await r.fulfill({ response: res, json: j });
  });
  await page.evaluate(() => loadNotices());
  const whens = await until(() => page.$$eval('.noticestab .ntrow .sub', rs => rs.map(r => r.textContent))
    .then(t => t.length && t.every(x => /2 h ago/.test(x)) ? t : null), 5000);
  await page.unroute('**/api/notices');
  await page.evaluate(() => loadNotices());
  ok(whens, `a notice said two hours ago reads "2 h ago" (${(whens || []).slice(0, 1).join('')})`);
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

// ---- a session an outage held is offered back -------------------------------
// R251: a session's gate marks it held while the controller is away, its
// node's agent reports the mark, and once the controller answers the bell
// lists it with a Resume that tells it to pick up from its note.
{
  const users = await api('/api/users');
  const uid = (users.users || []).find(u => u.name === 'test')?.uid;
  // As the gate writes it: bb-tty's hook is `bb-gate PROJECT ACCOUNT`, so the
  // mark names the account, and Resume finds its Claude session (B773).
  writeFileSync(`${DIR}/sandboxdata/held.json`, JSON.stringify([{ project: 'alpha', uid, session: uid,
    since: Math.floor(Date.now() / 1000) - 120 }]));
  await page.evaluate(() => toggleBell(true));
  const row = await until(() => page.evaluate(() => {
    refresh();
    const att = [...document.querySelectorAll('#bellPanel .bnote.att')];
    const r = att.find(n => /stopped for the update/.test(n.textContent));
    return r ? `${att.indexOf(r)}: ${r.textContent.replace(/\s+/g, ' ').trim()}` : null;
  }), 30000, 1000);
  ok(row && row.startsWith('0: '), `...first of what needs attention, above the updates (${row})`);
  ok(row && /test's Claude session on sandbox/.test(row) && /Resume/.test(row),
     `a session an outage held is a bell row naming whose it is and where it runs, with Resume (${row})`);
  rmSync(`${DIR}/sandboxdata/held.json`, { force: true });
  await page.click(`#bellPanel [data-bheld][data-session="${uid}"]`);
  const said = await until(() => page.evaluate(() => [...document.querySelectorAll('#toast .tmsg')]
    .map(t => t.textContent).find(t => /claude-alpha/.test(t))), 15000);
  ok(said && !/no session|not yours/.test(said), `...and Resume types the line into that session (${said})`);
  // Read off the bell open again: it draws only while it is on screen, and a
  // row read off a shut one is the one it held when it shut.
  const gone = await until(() => page.evaluate(async () => {
    toggleBell(true); await refresh();
    const p = document.getElementById('bellPanel');
    return !p.hidden && ![...p.querySelectorAll('.bnote')].some(n => /stopped for the update/.test(n.textContent));
  }), 20000, 1000);
  ok(gone, `...and the row goes (${await page.evaluate(() => [...document.querySelectorAll('#bellPanel .bnote')]
    .map(n => n.textContent.replace(/\s+/g, ' ').trim().slice(0, 60)).join(' | '))})`);
  await page.evaluate(() => { toggleBell(false); document.querySelectorAll('#toast .tst').forEach(t => t.remove()); });
}

// ---- on a phone the stack spans the width above the dock's line -------------
{
  await page.setViewportSize({ width: 393, height: 851 });
  await page.evaluate(() => notify('on a phone'));
  await sleep(300);
  const r = await page.$eval('#toast .tst', t => { const b = t.getBoundingClientRect(); return { l: b.left, r: innerWidth - b.right, bottom: b.bottom,
    dock: document.querySelector('#pane1 .bar')?.getBoundingClientRect().top ?? document.getElementById('railbar').getBoundingClientRect().top }; });
  ok(r.l <= 12 && r.r <= 12 && r.bottom <= r.dock, `on a phone a toast spans the width, above the dock's line (${JSON.stringify(r)})`);
  await page.evaluate(() => { document.querySelectorAll('#toast .tst').forEach(t => t.remove()); openAbout(); notify('over a phone dialog', true); });
  await sleep(300);
  const pd = await offDialog();
  const top = await page.$eval('#toast .tst', t => t.getBoundingClientRect().top);
  ok(pd.through && top < 60, `...and over a dialog with no gutter it sits at the top and lets every press through (${JSON.stringify({ ...pd, top })})`);
  await page.evaluate(() => { document.querySelectorAll('#toast .tst').forEach(t => t.remove()); closeAbout(); });
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
