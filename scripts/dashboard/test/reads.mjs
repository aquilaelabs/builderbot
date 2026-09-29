// A project reads other projects (prefs.reads): a session on it sees their
// notebooks and trees and changes nothing in them. The setting in the
// dialog as a listbox (and the places on its node it is shown, prefs.sees,
// as a field), the session token widened to the reads on every
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

// ---- the places on its node a project is shown (prefs.sees, B378) ------------------------
// A session's view is built from what it is given, so a share mounted on
// the node is out of it unless the project's settings name it.
{
  const set = await api('/api/prefs', { project: 'alpha', sees: ['/mnt/media/', '/srv/samples', '/mnt/media'] });
  const kept = (await api('/api/status')).projects.find(p => p.name === 'alpha').prefs.sees;
  ok(set.status === 200 && kept.join() === '/mnt/media,/srv/samples',
     `a project's settings keep the places on its node it is shown, each once (${set.status} ${JSON.stringify(kept)})`);
  const bad = [['/etc', /the machine's own or BuilderBot's/], ['/workspace/beta', /the machine's own or BuilderBot's/],
               ['/home/builder/.ssh', /the machine's own or BuilderBot's/], ['/var/lib/builderbot/appdata', /the machine's own/],
               ['/mnt/../etc', /not a place on a node/], ['mnt/media', /not a place on a node/], ['/mnt/my media', /not a place on a node/]];
  const got = [];
  for (const [p, re] of bad){
    const r = await api('/api/prefs', { project: 'alpha', sees: ['/mnt/media', p] });
    if (!(r.status === 400 && re.test(r.error || ''))) got.push(`${p}: ${r.status} ${r.error || ''}`);
  }
  ok(got.length === 0 && (await api('/api/status')).projects.find(p => p.name === 'alpha').prefs.sees.join() === '/mnt/media,/srv/samples',
     `a place that is the system's, the projects share, a home or the agent's is refused by name, as is a path that climbs, is relative or has a space, and the list stays as it was${got.length ? ` (not: ${got.join(' | ')})` : ''}`);
  const many = await api('/api/prefs', { project: 'alpha', sees: Array.from({ length: 9 }, (_, i) => `/mnt/share${i}`) });
  ok(many.status === 400 && /8 places at most, not 9/.test(many.error || ''), `...and more than eight is refused with the number (${many.error})`);
  const mine = await api('/api/prefs', { project: 'alpha', sees: ['/mnt/all'] }, asSession(tok));
  ok(mine.status === 403 && /a project's settings are the operator's/.test(mine.error || ''),
     `a session cannot name a place for itself (${mine.status} ${mine.error})`);
  const g = await api('/api/v1/tty-grant', { arg: 'claude:alpha' }, asSession(tok));
  ok(Array.isArray(g.sees) && g.sees.join() === '/mnt/media,/srv/samples',
     `the terminal's grant names them, for bb-session (${JSON.stringify(g.sees)})`);
  const said = (await api('/api/preamble?project=alpha')).text;
  ok(/Of the shares and disks mounted on its node, this project is shown \/mnt\/media, \/srv\/samples, as the node has each/.test(said)
     && /A share or\s+a disk mounted on the node, another project's build cache or container data,\s+and the home of the account sessions run as are not in its view/.test(said),
     'the briefing says what of the node a session has, that a share is not in its view, and which ones this project is shown');
  const shown = execFileSync('bash', [`${REPO}/scripts/bb`, 'settings'],
    { encoding: 'utf8', env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`,
      WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha' } });
  ok(/^\s+sees\s+\/mnt\/media, \/srv\/samples$/m.test(shown), `bb settings lists them (${(shown.match(/^.*sees.*$/m) || ['nothing'])[0].trim()})`);
  // The dialog: a field beside the node's, there when there is a node to
  // be on, filled with what is stored and read when Save is pressed.
  await refreshUntil(page, () => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.sees?.join() === '/mnt/media,/srv/samples', { timeout: 20000 });
  await page.evaluate(() => { nodesList = [{ id: 'n_0000test', name: 'box', kind: 'agent', state: 'ready', reported: {} }]; renameProject('alpha', 'all'); });
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  await page.waitForSelector('#rnSeesField:not([hidden])', { timeout: 10000 });
  const field = await page.$eval('#rnSees', e => ({ value: e.value, label: document.querySelector('label[for=rnSees]').firstChild.textContent,
    help: document.querySelector('label[for=rnSees] .help')?.dataset.tip || '', hint: !!document.querySelector('#rnSeesField .hint') }));
  ok(field.value === '/mnt/media, /srv/samples' && field.label === 'Also sees' && /share or a disk mounted on the node/.test(field.help) && !field.hint,
     `the project's settings carry the places in a field under the node, labeled above, its one sentence behind the ? (${JSON.stringify(field).slice(0, 140)})`);
  await page.fill('#rnSees', '/mnt/media');
  await page.click('#rnGo');
  await page.waitForSelector('#rnmodal', { state: 'hidden', timeout: 10000 });
  await refreshUntil(page, () => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.sees?.join() === '/mnt/media', { timeout: 20000 });
  ok(JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects.alpha.sees.join() === '/mnt/media',
     '...and Save keeps what the field says');
  await page.evaluate(() => renameProject('alpha', 'all'));
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  await page.fill('#rnSees', '/etc/ssh');
  await page.click('#rnGo');
  await page.waitForSelector('#rnErrWrap:not([hidden])', { timeout: 10000 });
  const err = await page.$eval('#rnErrWrap', e => e.textContent);
  ok(/\/etc\/ssh is the machine's own or BuilderBot's/.test(err) && await page.$eval('#rnmodal', e => !e.hidden),
     `a place it cannot be shown is refused in the dialog, which stays open with the reason (${err.trim().slice(0, 90)})`);
  await page.keyboard.press('Escape');
  // The refusal is the one error the page logged, and it was asked for.
  ok(page.errors.every(e => /400/.test(e) && /api\/prefs/.test(e)), `...and nothing else went wrong on the way (${page.errors.join(' | ').slice(0, 120) || 'none'})`);
  page.errors = [];
  await api('/api/prefs', { project: 'alpha', sees: [] });
  ok(!/this project is shown/.test((await api('/api/preamble?project=alpha')).text)
     && !('sees' in (JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects.alpha || {})
          && JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects.alpha.sees.length),
     '...and with none named the briefing names none');
}

// ---- the briefing names them ------------------------------------------------------------
const pre = await api('/api/preamble?project=alpha');
ok(/This project reads beta: each is at \/workspace\/NAME, read-only, and `bb -p NAME` in front/.test(pre.text)
   && /its containers answer from here on this project's nodes/.test(pre.text) && /Nothing there is yours to change/.test(pre.text) && /read the projects its settings say it reads/.test(pre.text),
   'the briefing says which projects the session reads and that nothing there is its to change, and the shipped rule carries the exception');
await api('/api/prefs', { project: 'alpha', reads: [] });
ok(!/This project reads/.test((await api('/api/preamble?project=alpha')).text),
   '...and says nothing about reads when there are none');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
