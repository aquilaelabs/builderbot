// The Schedules page (R117): an administrator's own cron. The built-in scan
// is there and off; a schedule added on the page says its timetable in
// words, Run now runs it once as a job whose log is on the Jobs page, and
// Turn off and Remove do what they say. A session's token and an account
// without the Schedules area are refused, whatever they ask.
import { launch, newPage, ok, done, ready, sleep, URL, DIR, member } from './lib.mjs';
import { execFileSync } from 'node:child_process';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const api = async (path, body, h = H) => {
  const r = await fetch(base + path, body === undefined ? { headers: h } : { method: 'POST', headers: h, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
};
const until = async (fn, ms = 20000) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ const v = await fn(); if (v) return v; await sleep(250); }
  return null;
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// The page, on the rail beside Jobs, with the scan built in and off.
await page.evaluate(() => openSchedulesTab());
await page.waitForSelector('.schedulestab .schedrow[data-sched="scan"]', { timeout: 15000 });
const scan = await page.$eval('.schedulestab .schedrow[data-sched="scan"]', r => r.textContent.replace(/\s+/g, ' '));
ok(/Static analysis scan/.test(scan) && /\boff\b/.test(scan) && /built in/.test(scan) && /Sundays at 4:00/.test(scan),
   `the Schedules page carries the static analysis scan, built in, off, Sundays at 4:00 (${scan.slice(0, 120)})`);
ok(await page.evaluate(() => location.hash) === '#/jobs/schedules'
   && await page.evaluate(() => groupOf('schedules')?.key) === 'jobs',
   'it is a page of the Jobs group, at its own address');

// Turning the scan on without its node and paths opens its form instead.
await page.click('.schedulestab [data-schedon="scan"]');
await page.waitForSelector('#schedmodal:not([hidden]) [data-schedform="scan"] [data-schedenv="SCANNER_REPORTS_PATH"]', { timeout: 10000 });
ok(true, 'turning the scan on with nothing set opens its dialog for its node and paths');
await page.click('#schedmodal [data-schedcancel]');
await page.waitForFunction(() => document.getElementById('schedmodal').hidden, null, { timeout: 5000 });

// A schedule added on the page: its timetable in words once saved.
await page.click('#bSchedNew');
await page.waitForSelector('#schedmodal:not([hidden]) [data-schedform="new"]', { timeout: 10000 });
// A dialog over the page (the operator, 26 Oct), not a form in its list.
const dlg = await page.evaluate(() => {
  const m = $('schedmodal');
  return { dialog: m.getAttribute('role') === 'dialog' && m.getAttribute('aria-modal') === 'true',
           title: $('schT')?.textContent, inPage: !!document.querySelector('.schedulestab [data-schedform]'),
           foot: [...m.querySelectorAll('.foot button')].map(b => b.textContent.trim()).join(',') };
});
ok(dlg.dialog && dlg.title === 'New schedule' && !dlg.inPage && dlg.foot === 'Cancel,Add',
   `New schedule opens a dialog, its foot Cancel and Add (${JSON.stringify(dlg)})`);
// As few fields as User Scripts (the operator, 26 Oct): a name, When as a
// pick, where it runs (the controller first, and picked), and the script;
// no timeout, and Runs as only for a sandbox node, where root is BuilderBot's.
const form = await page.evaluate(() => {
  const ids = [...$('schedmodal').querySelectorAll('input, select, textarea')].filter(e => e.offsetParent).map(e => e.id);
  const node = $('schNode');
  return { ids, when: $('schWhen').value, on: node.options[node.selectedIndex]?.textContent, first: node.options[0]?.textContent };
});
ok(form.ids.join() === 'schName,schWhen,schNode,schScript' && form.when === '0 4 * * *' && form.on === 'the controller' && form.first === 'the controller',
   `a new schedule asks its name, when, where and its script, daily on the controller to start (${JSON.stringify(form)})`);
const as = await page.evaluate(() => {
  const was = schedData.nodes;
  schedData.nodes = [...was, { id: 'nbox', name: 'box', sandbox: false }, { id: 'nsand', name: 'sand', sandbox: true }];
  const pick = id => { const sel = $('schNode'); if (![...sel.options].some(o => o.value === id)) sel.innerHTML += `<option value="${id}">${id}</option>`;
    sel.value = id; sel.dispatchEvent(new Event('change')); };
  const read = () => !!$('schAs');
  pick('nbox'); const plain = read(); pick('nsand'); const sand = read();
  pick(was.find(n => n.controller).id); const ctl = read();
  schedData.nodes = was; return { plain, sand, ctl };
});
ok(!as.plain && as.sand && !as.ctl, `Runs as is asked only on a sandbox node (${JSON.stringify(as)})`);
await page.selectOption('#schWhen', '');
ok(await page.$eval('#schCronF', f => !f.hidden), "When's Custom shows cron's five fields to type");
await page.fill('#schName', 'Say hello');
await page.fill('#schCron', '0 4 * * 1-5');
await page.fill('#schScript', 'echo scheduled-hello-$((40+2))');
await page.click('#schedmodal [data-schedsave=""]');
const row = await until(() => page.evaluate(() => (schedData?.schedules || []).find(s => s.name === 'Say hello')));
ok(row && row.on && row.words === 'weekdays at 4:00' && row.next_at > Date.now() / 1000,
   `a schedule added on the page is on, its timetable said in words, its next run ahead (${row?.words})`);
ok(await page.evaluate(() => document.getElementById('schedmodal').hidden), '...and Add closes the dialog');
await page.waitForSelector(`.schedulestab [data-schededit="${row.id}"]`, { timeout: 10000 });
await page.click(`.schedulestab [data-schededit="${row.id}"]`);
await page.waitForSelector('#schedmodal:not([hidden]) #schName', { timeout: 10000 });
ok(await page.$eval('#schName', i => i.value) === 'Say hello' && await page.$eval('#schT', h => h.textContent) === 'Say hello',
   "a row's Edit opens the same dialog on it, named for it");
await page.keyboard.press('Escape');
await page.waitForFunction(() => document.getElementById('schedmodal').hidden, null, { timeout: 5000 }).catch(() => {});
ok(await page.evaluate(() => document.getElementById('schedmodal').hidden), '...and Escape closes it');

// Run now: one run, a job whose log says what the script printed.
await page.click(`.schedulestab [data-schedrun="${row.id}"]`);
const ran = await until(async () => {
  const s = (await api('/api/schedules')).body.schedules.find(x => x.id === row.id);
  return s?.last?.job && ['succeeded', 'failed'].includes(s.last.state) ? s : null;
}, 30000);
const log = ran ? (await api(`/api/v1/jobs?id=${ran.last.job}`)).body : {};
ok(ran && ran.last.state === 'succeeded' && /scheduled-hello-42/.test(log.log || ''),
   `Run now runs it once as a job, its log on the Jobs page (${ran?.last?.state}; ${(log.log || '').trim().slice(-40)})`);
await page.waitForSelector(`.schedulestab .schedrow[data-sched="${row.id}"] [data-schedlog]`, { timeout: 15000 });
ok(true, '...and its row links that run\'s log');

// A failed run is on the bell.
await api('/api/schedules', { action: 'save', id: row.id, script: 'echo failing; exit 3' });
await api('/api/schedules', { action: 'run', id: row.id });
const bell = await until(async () => {
  await page.evaluate(() => refresh());
  return page.evaluate(id => (state?.attention || []).find(a => a.kind === 'schedule' && a.id === id && a.bad), row.id);
}, 30000);
ok(bell && /did not work|failed/.test(bell.why), `a failed run is on the bell (${bell?.why})`);

// Turn off and Remove.
await page.evaluate(() => loadSchedules());
await page.waitForSelector(`.schedulestab [data-schedon="${row.id}"][data-on="0"]`, { timeout: 10000 });
await page.click(`.schedulestab [data-schedon="${row.id}"]`);
const off = await until(async () => (await api('/api/schedules')).body.schedules.find(x => x.id === row.id && !x.on));
ok(off && off.next_at === null, 'Turn off takes it off the timetable');
await page.evaluate(id => { const b = document.querySelector(`.schedulestab [data-schedrm="${id}"]`); b?.click(); }, row.id);
const gone = await until(async () => !(await api('/api/schedules')).body.schedules.some(x => x.id === row.id));
ok(!!gone && (await api('/api/schedules', { action: 'remove', id: 'scan' })).status === 400,
   'Remove takes it away, and the built-in scan is turned off, never removed');

// A session's token is refused, reading or writing; so is an account
// without the Schedules area.
{
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
  const SH = { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' };
  const read = await api('/api/schedules', undefined, SH);
  const write = await api('/api/schedules', { action: 'save', name: 'x', cron: '* * * * *', script: 'id', node: 'local' }, SH);
  ok(read.status === 403 && write.status === 403 && /a session has no say/.test(write.body.error || ''),
     `a session's token is refused, reading and writing (${read.status}/${write.status})`);
  // ...nor does it see a schedule's runs among the jobs, or one by its id:
  // the scripts and their logs are an administrator's (the operator, 26 Oct).
  const one = await api(`/api/v1/jobs?id=${ran.last.job}`, undefined, SH);
  const list = await api('/api/v1/jobs?n=500', undefined, SH);
  const mineToo = (await api('/api/v1/jobs?n=500')).body.jobs || [];
  ok(one.status === 404 && !(list.body.jobs || []).some(j => j.id === ran.last.job) && mineToo.some(j => j.id === ran.last.job),
     `a schedule's run is not a session's to read, by its id or in the list, and is the administrator's (${one.status})`);
  await api('/api/users', { action: 'add', name: 'w.sched', password: 'w.sched-pass-1', role: 'user' });
  await member('w.sched');
  const UH = { Authorization: 'Basic ' + Buffer.from('w.sched:w.sched-pass-1').toString('base64'), 'Content-Type': 'application/json' };
  const plain = await api('/api/schedules', undefined, UH);
  ok(plain.status === 403, `an account without the Schedules area is refused (${plain.status} ${plain.body.error || ''})`);
}

await done(browser);
