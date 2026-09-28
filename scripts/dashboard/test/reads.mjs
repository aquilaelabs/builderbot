// A project reads other projects (prefs.reads): a session on it sees their
// notebooks and trees and changes nothing in them. The setting in the
// dialog as a listbox, the session token widened to the reads on every
// request, every write refused by name, the relayed words kept to reads,
// the grant carrying the reads for the view, and the briefing naming them.
import { launch, newPage, ok, done, ready, refreshUntil, URL, DIR } from './lib.mjs';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const api = async (path, body, headers = H) => {
  const r = await fetch(base + path, body === undefined ? { headers } : { method: 'POST', headers, body: JSON.stringify(body) });
  let j; try { j = await r.json(); } catch { j = {}; }
  return { status: r.status, ...j };
};
const token = project => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', project, 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const asSession = tok => ({ Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' });

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

// ---- the dialog: two listboxes -----------------------------------------------------
await page.evaluate(() => renameProject('alpha', 'all'));
await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
await page.waitForSelector('#rnReadsField:not([hidden])', { timeout: 10000 });
const rows = await page.$$eval('#rnReads label.lrow', ls => ls.map(l => [l.querySelector('input').value, l.querySelector('input').checked]));
ok(rows.length >= 2 && !rows.some(([n]) => n === 'alpha') && rows.map(([n]) => n).join() === rows.map(([n]) => n).sort().join()
   && rows.every(([, on]) => !on),
   `the project's settings offer every other project as a listbox row, alphabetical, none ticked yet (${rows.map(([n]) => n).join(', ')})`);
const look = await page.$eval('#rnReads', e => ({ overflow: getComputedStyle(e).overflowY, border: getComputedStyle(e).borderTopWidth,
  row: Math.round(e.querySelector('label.lrow').getBoundingClientRect().height), display: getComputedStyle(e.querySelector('label.lrow')).display }));
ok(look.overflow === 'auto' && look.border === '1px' && look.row >= 38 && look.display === 'flex',
   `a listbox is a bordered box that scrolls, its rows a thumb high (${JSON.stringify(look)})`);
await page.check('#rnReads input[value="beta"]');
await page.click('#rnGo');
await page.waitForSelector('#rnmodal', { state: 'hidden', timeout: 10000 });
await refreshUntil(page, () => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.reads?.join() === 'beta', { timeout: 20000 });
ok(JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects.alpha.reads.join() === 'beta',
   'Save keeps the ticked projects as the reads, in the settings store');
await page.evaluate(() => renameProject('alpha', 'all'));
await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
ok(await page.$eval('#rnReads input[value="beta"]', i => i.checked), '...and the dialog opens with it ticked');
await page.keyboard.press('Escape');
const self = await api('/api/prefs', { project: 'alpha', reads: ['alpha', 'beta', 'nowhere/x', 'gamma'] });
ok(self.status === 200 && (await api('/api/status')).projects.find(p => p.name === 'alpha').prefs.reads.join() === 'beta,gamma',
   'a project never reads itself, and a name that is not a project name is dropped');

// ---- the session: reads go through, writes are refused by name -----------------------
const tok = token('alpha');
const seen = await api('/api/status', undefined, asSession(tok));
ok(seen.projects.map(p => p.name).sort().join() === 'alpha,beta,gamma'
   && seen.projects.find(p => p.name === 'beta').mine === false && seen.projects.find(p => p.name === 'alpha').mine === true,
   `a session on alpha sees beta and gamma beside its own, and neither is its to work on (${seen.projects.map(p => `${p.name}:${p.mine}`).join(' ')})`);
const road = await api('/api/roadmap?project=beta', undefined, asSession(tok));
ok(road.status === 200 && Array.isArray(road.items || road.roadmap || road.list || []),
   `...reads beta's roadmap (${road.status})`);
const write = await api('/api/roadmap', { project: 'beta', action: 'add', text: 'from alpha' }, asSession(tok));
ok(write.status === 403 && /beta is read-only from a session on alpha/.test(write.error || ''),
   `...and a write to beta's notebook is refused by name (${write.error})`);
const own = await api('/api/roadmap', { project: 'alpha', action: 'add', text: 'from alpha itself' }, asSession(tok));
ok(own.status === 200, `...while the same write to its own project goes through (${own.status})`);
const stranger = await api('/api/roadmap?project=delta', undefined, asSession(tok));
ok(stranger.status === 400 && /not a project/.test(stranger.error || ''),
   'a project alpha does not read is not a project to its session, as before');
await api('/api/prefs', { project: 'alpha', reads: ['beta'] });
const dropped = await api('/api/roadmap?project=gamma', undefined, asSession(tok));
ok(dropped.status === 400, 'a read taken away in the settings is gone from a running session at once, no new token needed');

// ---- the relay: reading words only ----------------------------------------------------
const relay = (argv, project) => api('/api/v1/bb', { argv, project, cwd: `${DIR}/ws/${project}` }, asSession(tok));
const list = await relay(['roadmap'], 'beta');
ok(list.status === 200 && !list.error, `bb roadmap relayed for beta from alpha's session answers (${list.status} ${(list.error || '').slice(0, 60)})`);
const add = await relay(['roadmap', 'add', 'from alpha'], 'beta');
ok(add.status === 403 && /beta is read-only from a session on alpha: bb roadmap add would change it/.test(add.error || ''),
   `...and bb roadmap add for beta is refused, naming the words (${add.error})`);
const gitp = await relay(['git', 'push'], 'beta');
ok(gitp.status === 403 && /acts on the project's own machines/.test(gitp.error || ''),
   `...as is a verb that acts on beta's machines (${gitp.error})`);

// ---- the grant carries the reads, for the view and the walls ---------------------------
const grant = await api('/api/v1/tty-grant', { arg: 'claude:alpha' }, asSession(tok));
ok(Array.isArray(grant.reads) && grant.reads.join() === 'beta',
   `the terminal's grant names the projects the session reads, for bb-session and Claude's walls (${JSON.stringify(grant).slice(0, 160)})`);

// ---- the briefing names them ------------------------------------------------------------
const pre = await api('/api/preamble?project=alpha');
ok(/This project reads beta: each is at \/workspace\/NAME, read-only/.test(pre.text)
   && /Nothing there is yours to change/.test(pre.text) && /read the projects its settings say it reads/.test(pre.text),
   'the briefing says which projects the session reads and that nothing there is its to change, and the shipped rule carries the exception');
await api('/api/prefs', { project: 'alpha', reads: [] });
ok(!/This project reads/.test((await api('/api/preamble?project=alpha')).text),
   '...and says nothing about reads when there are none');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
