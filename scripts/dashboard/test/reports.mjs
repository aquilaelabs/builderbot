// Problems with BuilderBot itself, reported by a session on any project
// (reports.py, bb report; the operator, 24 Sep). A session files one instead
// of putting it in its own project's tracker, as a shipped rule tells it to;
// the report waits on the controller, is read in the diagnostics behind their
// gate, and is filed into a tracker or closed from there; the session that
// made it reads what became of it. No browser: it is an API and a verb.
import { launch, newPage, ready, ok, done, saveDialog, URL, DIR } from './lib.mjs';
import { execFileSync, spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
                'Content-Type': 'application/json' };
const call = async (path, body, headers = ADMIN) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};
const token = project => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', project, 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const as = tok => ({ Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' });
const ALPHA = as(token('alpha'));
const BETA = as(token('beta'));

// ---- a session reports one ---------------------------------------------------
const made = await call('/api/reports', { action: 'add', text: 'bb test ran the tests inside the dev instance',
  area: 'bb test', repro: 'the log said token=bbs_abcdefgh12345678 and found no tests' }, ALPHA);
ok(made.status === 200 && made.ok && made.id > 0, `a session reports a problem with BuilderBot (${JSON.stringify(made)})`);
const stored = JSON.parse(readFileSync(`${DIR}/state/reports.json`, 'utf8')).reports.find(r => r.id === made.id) || {};
ok(stored.project === 'alpha' && stored.state === 'open' && /redacted/.test(stored.repro)
   && !/bbs_abcdefgh/.test(JSON.stringify(stored)),
   `...stored as the project's, open, with anything shaped like a credential redacted (${stored.repro})`);
const empty = await call('/api/reports', { action: 'add', text: '   ' }, ALPHA);
ok(empty.status === 400 && /say what happened/.test(empty.error || ''), 'a report with no words is refused');

// ---- who reads it ------------------------------------------------------------------
const mine = await call('/api/reports', { action: 'mine' }, ALPHA);
const theirs = await call('/api/reports', { action: 'mine' }, BETA);
ok((mine.reports || []).some(r => r.id === made.id) && !(theirs.reports || []).some(r => r.id === made.id),
   'the session that reported it reads it, and another project\'s session does not');
const listed = await call('/api/reports', { action: 'list' }, BETA);
ok(listed.status === 403, `...nor may a session list everybody's, outside the diagnostics' gate (${listed.error})`);
const diag = await call('/api/diag', { sections: ['reports'] });
const seen = (diag.reports || []).find(r => r.id === made.id);
ok(seen && seen.project === 'alpha' && /inside the dev instance/.test(seen.text) && seen.when,
   `the diagnostics carry the open reports, whose and when (${JSON.stringify(seen || diag).slice(0, 120)})`);

// ---- answered from there -------------------------------------------------------------
const filed = await call('/api/reports', { action: 'filed', id: made.id, bug: 'B9' });
const after = (await call('/api/reports', { action: 'mine' }, ALPHA)).reports.find(r => r.id === made.id);
ok(filed.ok && after.state === 'filed' && !('bug' in after) && !('done_by' in after)
   && !((await call('/api/diag', { sections: ['reports'] })).reports || []).some(r => r.id === made.id),
   'filing it records the bug it became; its session reads that it was filed and not the number, which is another notebook\'s (B317), and it leaves the open list');
const second = await call('/api/reports', { action: 'add', text: 'the briefing names a verb that is gone' }, ALPHA);
const closed = await call('/api/reports', { action: 'close', id: second.id, why: 'the verb is there: bb map -h' });
const again = await call('/api/reports', { action: 'close', id: second.id, why: 'twice' });
ok(closed.ok && again.status === 400 && /already closed/.test(again.error || ''),
   `closing one takes a reason, and a closed one stays closed (${again.error})`);
const noWhy = await call('/api/reports', { action: 'close', id: made.id + 100, why: '' });
ok(noWhy.status === 400, 'a close with no reason is refused');

// ---- the verb ------------------------------------------------------------------------
// As a session on a node runs it: its token, its project, the controller's address.
const node = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: base, BB_TOKEN: token('alpha'),
               BB_PROJECT: 'alpha', XDG_CACHE_HOME: `${DIR}/cache-reports` };
const bb = (args, env, cwd) => spawnSync('bash', [`${REPO}/scripts/bb`, ...args],
  { encoding: 'utf8', env, cwd: cwd || `${DIR}/ws/alpha`, timeout: 60000 });
const said = bb(['report', 'bb map build wrote .bb-map into the tree unignored', '--area', 'bb map'], node);
ok(said.status === 0 && /reported #\d+/.test(said.stdout), `bb report sends one from a session (${(said.stdout + said.stderr).trim()})`);
const list = bb(['report'], node);
ok(list.status === 0 && /filed in BuilderBot's tracker/.test(list.stdout) && !/B9/.test(list.stdout) && /bb map build wrote/.test(list.stdout),
   `...and bb report alone says what became of the project's reports (${list.stdout.replace(/\s+/g, ' ').slice(0, 120)})`);
// Filed from BuilderBot's side, through bb bug add, as an administrator.
const id = Number((said.stdout.match(/#(\d+)/) || [])[1]);
const admin = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_AUTH: 'test:test',
                BB_CONTROLLER: base, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` };
const fil = bb(['report', 'file', String(id), '--sev', 'low'], admin);
const bugNo = (fil.stdout.match(/report #\d+ is (B\d+) now/) || [])[1];
const bug = bugNo && JSON.parse(readFileSync(`${DIR}/state/bugs.json`, 'utf8')).projects.alpha
  .find(b => `B${b.id}` === bugNo);
ok(fil.status === 0 && bug && /bb map build wrote/.test(bug.title) && /report #\d+/.test(bug.repro || '')
   && (await call('/api/reports', { action: 'get', id })).bug === bugNo,
   `bb report file N files it through bb bug add and marks it with the bug it became (${(fil.stdout + fil.stderr).trim().slice(-140)})`);

// ---- where a session is told --------------------------------------------------------
const p = await call('/api/preamble?project=alpha');
const text = p.text || '';
ok(text.split('goes to `bb report').length === 2 && /`bb report` alone lists/.test(text) && !/report-builderbot/.test(text),
   'a session is told once, by the briefing\'s own words and not a rule, where BuilderBot\'s problems go and what the verb does');
// ...and stopped when it files one in its own tracker anyway: asked, before
// anything is filed, since a line said afterwards was not enough (24 Sep).
const bugsNow = () => (JSON.parse(readFileSync(`${DIR}/state/bugs.json`, 'utf8')).projects.alpha || []).length;
const had = bugsNow();
const own = bb(['bug', 'add', 'bb devapp status says the env is the operator\'s'],
               { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(own.status !== 0 && /^\[builderbot\] not filed yet\. Send it with bb report .*or add --here/.test(own.stderr)
   && own.stderr.indexOf('bb report') < 60 && own.stderr.indexOf('--here') < 200 && bugsNow() === had,
   `a bug that names BuilderBot, filed in another project, is not filed there, and both ways on are in the first of what it says (${own.stderr.trim().slice(0, 110)})`);
const colon = bb(['bug', 'add', 'bb: tests preflight runs every suite', '--sev', 'high'],
                 { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(colon.status !== 0 && bugsNow() === had,
   '...however the verb is written (bb: ..., `bb`, bb-tty), and the severity is not read as words');
const mine2 = bb(['bug', 'add', 'bb build fails because this project pins an old compiler', '--here'],
                 { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(mine2.status === 0 && /filed B\d+/.test(mine2.stdout) && bugsNow() === had + 1,
   `...while --here files one that is the project's own (${mine2.stdout.trim().slice(0, 80)})`);
// ---- off for a project, in its settings -------------------------------------------
// Claude may: Report BuilderBot bugs. BuilderBot's own project has it off:
// its problems go into its own tracker, so its sessions are not sent to
// bb report, not nudged toward it, and refused by it.
const setReport = v => call('/api/prefs', { project: 'alpha', report: v });
await setReport('deny');
const refused = await call('/api/reports', { action: 'add', text: 'something about bb' }, ALPHA);
ok(refused.status === 403 && /Claude may: Report BuilderBot bugs/.test(refused.error || ''),
   `with it off, bb report is refused and says where the setting is (${refused.error})`);
const quiet = (await call('/api/preamble?project=alpha')).text || '';
ok(/setting Report BuilderBot bugs is deny/.test(quiet) && /`bb bug add --here` files it here/.test(quiet),
   '...and its sessions are told what deny means: the verb refuses, and --here files it in this tracker');
const noNudge = bb(['bug', 'add', 'bb devapp status is wrong about the env'],
                   { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(noNudge.status === 0 && !/not filed yet/.test(noNudge.stderr),
   '...and a bug naming BuilderBot filed there is not pointed at it');
ok(JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects.alpha.report === 'deny',
   '...stored on the project as the one word that differs from the default');
await setReport('auto');

// ...and the setting is in the project's settings dialog, with the others.
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);
await page.evaluate(() => renameProject('alpha'));
await page.waitForSelector('#rnmodal:not([hidden]) #rnGateReport', { timeout: 15000 });
ok(await page.$eval('#rnGateReport', e => e.value === 'auto' && [...e.options].map(o => o.value).join() === 'auto,deny'),
   "the project's settings carry it under Claude may, on auto, with nothing to ask");
await page.selectOption('#rnGateReport', 'deny');
await saveDialog(page);
await page.waitForFunction(async () => {
  const j = await (await fetch('/api/status')).json();
  return (j.projects || []).find(p => p.name === 'alpha')?.prefs?.report === 'deny';
}, null, { timeout: 20000, polling: 500 });
ok(true, '...and saving the dialog turns it off');
await setReport('auto');

// ---- cleared from Controller settings --------------------------------------------------
// The operator, 24 Sep: a button there to clear them. Every one goes, open
// ones included, after a confirm that says how many are still open; the
// numbers carry on, and a session may not do it.
const bySession = await call('/api/reports', { action: 'clear' }, ALPHA);
ok(bySession.status === 403 && /a person's, from Controller settings/.test(bySession.error || '')
   && (await call('/api/reports', { action: 'count' })).all > 0,
   `a session may not clear them (${bySession.error})`);
await call('/api/reports', { action: 'add', text: 'one nobody has looked at yet' }, ALPHA);
const before = await call('/api/reports', { action: 'count' });
const lastId = Math.max(...(await call('/api/reports', { action: 'list', state: 'all' })).reports.map(r => r.id));
await page.evaluate(() => openSettingsTab());
await page.waitForSelector('#setReportsClear', { timeout: 15000 });
page.dialogs.length = 0;
await page.click('#setReportsClear');
await page.waitForFunction(async () => (await (await fetch('/api/reports', { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'count' }) })).json()).all === 0,
  null, { timeout: 15000, polling: 300 });
ok(page.dialogs.length === 1 && new RegExp(`Delete all ${before.all} reports`).test(page.dialogs[0])
   && before.open === 1 && /1 still open: nobody has filed or closed it/.test(page.dialogs[0]),
   `Clear reports in Controller settings asks first, naming how many and how many are open (${page.dialogs[0]})`);
const next = await call('/api/reports', { action: 'add', text: 'the first one after a clear' }, ALPHA);
ok(next.id > lastId, `...clears every one, and the next report does not take a number already used (#${next.id} after #${lastId})`);
// ...and the session whose reports went is told so, with how many and
// when, rather than that it never made any (B343).
const afterClear = await call('/api/reports', { action: 'mine' }, ALPHA);
ok(afterClear.cleared && afterClear.cleared.n >= 1 && afterClear.cleared.at > 0,
   `mine says how many of the project's reports the operator cleared and when (${JSON.stringify(afterClear.cleared)})`);
const clearedSaid = execFileSync('bash', [`${REPO}/scripts/bb`, 'report'], { encoding: 'utf8',
  env: { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''), BB_TOKEN: token('alpha'), BB_PROJECT: 'alpha', XDG_CACHE_HOME: `${DIR}/cache-reports` } });
ok(/earlier reports? from alpha (was|were) cleared by the operator on .* \(Controller settings\)/.test(clearedSaid) && !/no reports from alpha/.test(clearedSaid),
   `bb report says it too (${clearedSaid.split('\n')[0].slice(0, 100)})`);
page.dialogs.length = 0;
await call('/api/reports', { action: 'clear' });
await page.click('#setReportsClear');
await page.waitForFunction(() => /no reports to clear/.test(document.getElementById('toast').textContent), null, { timeout: 10000 });
ok(page.dialogs.length === 0, '...and with none kept, it says so rather than asking');
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);

await done(browser);
