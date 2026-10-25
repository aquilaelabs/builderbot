// Problems with BuilderBot itself, reported by a session on any project
// (reports.py, bb report; the operator, 24 Sep). A session files one instead
// of putting it in its own project's tracker, as a shipped rule tells it to;
// the report waits on the controller and is read in the diagnostics behind
// their gate, a log a person clears. Nothing goes back to the session that
// made it: that loop worked only where BuilderBot's own tracker sat beside
// the sessions reporting to it (the operator, 8 Oct).
import { launch, newPage, ready, ok, done, saveDialog, URL, DIR, unfold, splitPick, prefsOf } from './lib.mjs';
import { execFileSync, spawnSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';

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
ok(stored.project === 'alpha' && !('state' in stored) && /redacted/.test(stored.repro)
   && !/bbs_abcdefgh/.test(JSON.stringify(stored)),
   `...stored as the project's, a line in a log, with anything shaped like a credential redacted (${stored.repro})`);
const empty = await call('/api/reports', { action: 'add', text: '   ' }, ALPHA);
ok(empty.status === 400 && /say what happened/.test(empty.error || ''), 'a report with no words is refused');

// ---- who reads it ------------------------------------------------------------------
const listed = await call('/api/reports', { action: 'list' }, BETA);
ok(listed.status === 403, `...nor may a session list everybody's, outside the diagnostics' gate (${listed.error})`);
const diag = await call('/api/diag', { sections: ['reports'] });
const seen = (diag.reports || []).find(r => r.id === made.id);
ok(seen && seen.project === 'alpha' && /inside the dev instance/.test(seen.text) && seen.when,
   `the diagnostics carry the reports, whose and when (${JSON.stringify(seen || diag).slice(0, 120)})`);

// ---- and nothing answers one ---------------------------------------------------------
const gone = await Promise.all(['mine', 'filed', 'close'].map(action =>
  call('/api/reports', { action, id: made.id, bug: 'B9', why: 'x' }, action === 'mine' ? ALPHA : ADMIN)));
ok(gone.every(r => r.status >= 400) && (await call('/api/reports', { action: 'get', id: made.id })).text,
   `no report is read back by its session, filed or closed: it stays in the log as it was (${gone.map(r => r.status)})`);

// ---- the verb ------------------------------------------------------------------------
// As a session on a node runs it: its token, its project, the controller's address.
const node = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: base, BB_TOKEN: token('alpha'),
               BB_PROJECT: 'alpha', XDG_CACHE_HOME: `${DIR}/cache-reports` };
const bb = (args, env, cwd) => spawnSync('bash', [`${REPO}/scripts/bb`, ...args],
  { encoding: 'utf8', env, cwd: cwd || `${DIR}/ws/alpha`, timeout: 60000 });
const said = bb(['report', 'bb map build wrote .bb-map into the tree unignored', '--area', 'bb map'], node);
ok(said.status === 0 && /reported #\d+/.test(said.stdout), `bb report sends one from a session (${(said.stdout + said.stderr).trim()})`);
ok(/nothing more is needed/.test(said.stdout), '...and says nothing more is needed from the session');
const list = bb(['report'], node);
ok(list.status !== 0 && /say what went wrong/.test(list.stderr),
   `bb report alone asks for the words, with no listing of what became of earlier ones (${list.stderr.trim().slice(0, 100)})`);
const admin = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_AUTH: 'test:test',
                BB_CONTROLLER: base, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` };

// ---- where a session is told --------------------------------------------------------
const p = await call('/api/preamble?project=alpha');
const text = p.text || '';
const notebook = (await call('/api/preamble?project=alpha&topic=notebook')).text || '';
ok(/`bb report "\.\.\."` for a problem with BuilderBot itself/.test(text) && !/report-builderbot/.test(text)
   && notebook.split('goes to `bb report').length === 2 && /nothing comes back/.test(notebook),
   'a session is told once, by the briefing\'s core and its notebook topic and not a rule, where BuilderBot\'s problems go and what the verb does');
// ...and stopped when it files one in its own tracker anyway: asked, before
// anything is filed, since a line said afterwards was not enough (24 Sep).
const bugsNow = () => { try { return (JSON.parse(readFileSync(`${DIR}/state/bugs.json`, 'utf8')).projects.alpha || []).length; }
                        catch { return 0; } };   // (none filed yet: no file)
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
// A repro that uses bb is how a project's own bug is shown, not a sign it is
// BuilderBot's: two of MediaReducer's were stopped for one (7 Oct).
const byRepro = bb(['bug', 'add', 'the dashboard repaints after it loads', '--repro', 'record it with bb capture reel', '--reproduces', 'once'],
                   { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(byRepro.status === 0 && /filed B\d+/.test(byRepro.stdout) && bugsNow() === had + 1,
   `...and a repro that uses bb does not make it BuilderBot's (${(byRepro.stdout + byRepro.stderr).trim().slice(0, 80)})`);
const helped = bb(['bug', 'add', '-h'], { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(helped.status === 0 && /bb bug/.test(helped.stdout) && bugsNow() === had + 1,
   '...and bb bug add -h prints the help rather than filing a bug called -h');
const mine2 = bb(['bug', 'add', 'bb build fails because this project pins an old compiler', '--here'],
                 { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(mine2.status === 0 && /filed B\d+/.test(mine2.stdout) && bugsNow() === had + 2,
   `...while --here files one that is the project's own (${mine2.stdout.trim().slice(0, 80)})`);
// ---- off for a project, in its settings -------------------------------------------
// Agents may: Report BuilderBot bugs. BuilderBot's own project has it off:
// its problems go into its own tracker, so its sessions are not sent to
// bb report, not nudged toward it, and refused by it.
const setReport = v => call('/api/prefs', { project: 'alpha', report: v });
await setReport('deny');
const refused = await call('/api/reports', { action: 'add', text: 'something about bb' }, ALPHA);
ok(refused.status === 403 && /Agents may: Report BuilderBot bugs/.test(refused.error || ''),
   `with it off, bb report is refused and says where the setting is (${refused.error})`);
const quiet = (await call('/api/preamble?project=alpha&topic=notebook')).text || '';
ok(/setting Report BuilderBot bugs is deny/.test(quiet) && /`bb bug add --here` files it here/.test(quiet),
   '...and its sessions are told what deny means: the verb refuses, and --here files it in this tracker');
const noNudge = bb(['bug', 'add', 'bb devapp status is wrong about the env'],
                   { ...admin, DASHBOARD_AUTH: '', BB_BUG_PROJECT: 'alpha' });
ok(noNudge.status === 0 && !/not filed yet/.test(noNudge.stderr),
   '...and a bug naming BuilderBot filed there is not pointed at it');
ok(prefsOf('alpha').report === 'deny',
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
   "the project's settings carry it under Agents may, on auto, with nothing to ask");
await page.selectOption('#rnGateReport', 'deny');
await saveDialog(page);
await page.waitForFunction(async () => {
  const j = await (await fetch('/api/status')).json();
  return (j.projects || []).find(p => p.name === 'alpha')?.prefs?.report === 'deny';
}, null, { timeout: 20000, polling: 500 });
ok(true, '...and saving the dialog turns it off');
await setReport('auto');

// ---- cleared from Controller settings --------------------------------------------------
// The operator, 24 Sep: a button there to clear them. Every one goes after a
// confirm that says how many; the numbers carry on, and a session may not.
const bySession = await call('/api/reports', { action: 'clear' }, ALPHA);
ok(bySession.status === 403 && /a person's, from Controller settings/.test(bySession.error || '')
   && (await call('/api/reports', { action: 'count' })).all > 0,
   `a session may not clear them (${bySession.error})`);
await call('/api/reports', { action: 'add', text: 'one nobody has looked at yet' }, ALPHA);
// Read until it answers a number: under an eight-worker load one count came
// back without one (B722), and the check then compared against undefined.
let before = {};
for (let i = 0; i < 10 && typeof before.all !== 'number'; i++) before = await call('/api/reports', { action: 'count' });
ok(typeof before.all === 'number' && before.all > 0, `the reports are counted before the press (${before.all})`);
const lastId = Math.max(...(await call('/api/reports', { action: 'list' })).reports.map(r => r.id));
await page.evaluate(() => openSettingsTab());
await page.waitForSelector('.settingstab .snav [data-spick="reports"]', { timeout: 15000 }); await splitPick(page, 'reports');
await page.waitForSelector('#setReportsClear', { timeout: 15000 });
page.dialogs.length = 0;
await page.click('#setReportsClear');
// The button counts first, then asks: the confirm is waited for in its own
// right, so a slow count under load is a late dialog rather than a missing one.
for (let i = 0; i < 100 && !page.dialogs.length; i++) await page.waitForTimeout(150);
await page.waitForFunction(async () => (await (await fetch('/api/reports', { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'count' }) })).json()).all === 0,
  null, { timeout: 15000, polling: 300 });
ok(page.dialogs.length === 1 && new RegExp(`Delete all ${before.all} reports`).test(page.dialogs[0])
   && !/open/.test(page.dialogs[0]),
   `Clear reports in Controller settings asks first, naming how many (${page.dialogs[0]})`);
// The section opens on what it holds (R218 step 32): its count its status,
// counted again after the Clear.
await page.waitForFunction(() => document.querySelector('.settingstab details[data-sect="settings:reports"] > summary .sst')?.textContent === 'none',
  null, { timeout: 10000 }).catch(() => {});
ok(await page.$eval('.settingstab details[data-sect="settings:reports"] > summary .sst', e => e.textContent).catch(() => '') === 'none',
   '...and the section\'s status says how many it holds: none, after the Clear');
const next = await call('/api/reports', { action: 'add', text: 'the first one after a clear' }, ALPHA);
ok(next.id > lastId, `...clears every one, and the next report does not take a number already used (#${next.id} after #${lastId})`);
page.dialogs.length = 0;
await call('/api/reports', { action: 'clear' });
await page.click('#setReportsClear');
await page.waitForFunction(() => /no reports to clear/.test(document.getElementById('toast').textContent), null, { timeout: 10000 });
ok(page.dialogs.length === 0, '...and with none kept, it says so rather than asking');
// ---- a person's report, from a project's row (the operator, 2 Oct) -------------
// The bug on the row opens a dialog: a category, what happened, how to make
// it happen; Send puts it in the diagnostics under that project, marked as
// from the dashboard, whatever the project's Claude dial says.
{
  await page.evaluate(() => openProjectsTab?.());
  await page.waitForSelector('[data-bug="alpha"]', { timeout: 15000, state: 'attached' });
  await unfold(page, 'alpha');
  await page.click('.pgrid .pcard[data-row="alpha"] [data-bug]');
  await page.waitForSelector('#reportModal:not([hidden]) #reportCat', { timeout: 10000 });
  ok(/alpha/.test(await page.$eval('#reportTitle', e => e.textContent))
     && (await page.$$eval('#reportCat option', os => os.length)) >= 8,
     'the bug on a project\'s row opens Report a bug, for that project, with a category to pick');
  await page.click('#reportSend');
  ok(await page.$eval('#reportErrWrap', e => !e.hidden), '...and Send with nothing said is refused in the dialog');
  await page.selectOption('#reportCat', 'The notebook');
  await page.fill('#reportText', 'the wiki tab lost my edit');
  await page.fill('#reportRepro', 'edit, switch tabs, come back');
  await page.click('#reportSend');
  await page.waitForFunction(() => document.getElementById('reportModal').hidden, null, { timeout: 10000 });
  // What the diagnostics hold, read as they read it (bb diag reports).
  const diag = await page.evaluate(async () => (await (await fetch('/api/reports', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'list' }) })).json()));
  const rows = diag.reports || [];
  const mine = (Array.isArray(rows) ? rows : []).find(r => r.text === 'the wiki tab lost my edit');
  ok(mine && mine.project === 'alpha' && mine.area === 'The notebook' && /from the dashboard/.test(mine.by)
     && mine.repro === 'edit, switch tabs, come back',
     `...and Send puts it in the diagnostics under alpha, with its category, marked as from the dashboard (${JSON.stringify(mine || diag).slice(0, 200)})`);
}

// A project's report can carry the reporter's latest conversation on it
// (the operator, 2 Oct), ticked in the dialog, redacted, and carried by the
// diagnostics and their download.
{
  const dir = `${DIR}/home/.claude/projects/${`${DIR}/ws/alpha`.replace(/\//g, '-')}`;
  mkdirSync(dir, { recursive: true });
  writeFileSync(`${dir}/feedface-0000.jsonl`, [
    { type: 'user', message: { role: 'user', content: 'make the wiki keep my edit' }, timestamp: '2026-10-02T10:00:00Z' },
    { type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text: 'Saving it now. token=ghp_abcdefghijklmnopqrstuvwxyz0123456789' }] }, timestamp: '2026-10-02T10:00:05Z' },
  ].map(x => JSON.stringify(x)).join('\n') + '\n');
  await unfold(page, 'alpha');
  await page.click('.pgrid .pcard[data-row="alpha"] [data-bug]');
  await page.waitForSelector('#reportConvField:not([hidden])', { timeout: 10000 });
  ok(/make the wiki keep my edit/.test(await page.$eval('#reportConvWhich', e => e.textContent))
     && !(await page.$eval('#reportConv', e => e.checked)),
     'a project\'s report offers the latest conversation, named, and off until ticked');
  await page.check('#reportConv');
  await page.fill('#reportText', 'the session lost the edit');
  await page.click('#reportSend');
  await page.waitForFunction(() => document.getElementById('reportModal').hidden, null, { timeout: 15000 });
  // The download is a zip: diagnostics.json names the file, and the file
  // is beside it, so a long conversation never swells the report.
  const zip = await page.evaluate(async () => {
    const b = new Uint8Array(await (await fetch('/logs/download?what=diag')).arrayBuffer());
    let s = ''; for (let i = 0; i < b.length; i += 8192) s += String.fromCharCode(...b.subarray(i, i + 8192));
    return btoa(s);
  });
  const got = JSON.parse(execFileSync('python3', ['-c', `
import base64, io, json, sys, zipfile
z = zipfile.ZipFile(io.BytesIO(base64.b64decode(sys.stdin.read())))
d = json.loads(z.read("diagnostics.json"))
r = next((x for x in d.get("reports") or [] if x.get("text") == "the session lost the edit"), None)
f = (r or {}).get("conversation", {}).get("file")
print(json.dumps({"r": r, "text": z.read(f).decode() if f and f in z.namelist() else ""}))`], { input: zip, encoding: 'utf8' }));
  const r = got.r;
  ok(r && r.conversation?.id === 'feedface-0000' && !('conversation_text' in r)
     && /make the wiki keep my edit/.test(got.text) && /Saving it now/.test(got.text) && !/ghp_abcdefghijklmnop/.test(got.text),
     `...ticked, it goes with the report: the diagnostics name its file and the download carries it beside them, the token taken out (${JSON.stringify(r?.conversation || null)})`);
}

// The header's bug is the same dialog about no project in particular (the
// operator, 2 Oct): any account sends one, and the diagnostics say general.
{
  await page.click('#bReport');
  await page.waitForSelector('#reportModal:not([hidden]) #reportCat', { timeout: 10000 });
  ok(await page.$eval('#reportTitle', e => e.textContent) === 'Report a bug',
     'the header\'s bug opens Report a bug for no project');
  await page.selectOption('#reportCat', 'The dashboard');
  await page.fill('#reportText', 'the header is crowded on a phone');
  await page.click('#reportSend');
  await page.waitForFunction(() => document.getElementById('reportModal').hidden, null, { timeout: 10000 });
  const all = await page.evaluate(async () => (await (await fetch('/api/reports', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'list' }) })).json()));
  const gen = (all.reports || []).find(r => r.text === 'the header is crowded on a phone');
  ok(gen && gen.project === '' && gen.area === 'The dashboard' && /from the dashboard/.test(gen.by),
     `...and Send puts it in the diagnostics with no project, marked as from the dashboard (${JSON.stringify(gen || {}).slice(0, 160)})`);
}

// ...and only from a project the person works on (the operator, 2 Oct): an
// administrator shown every project but not on this one cannot start a
// session there, so has nothing of its to report.
{
  execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'repadmin', '--role', 'admin'],
    { input: 'repadminpass1\nrepadminpass1\n', encoding: 'utf8',
      env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } });
  const as = { Authorization: 'Basic ' + Buffer.from('repadmin:repadminpass1').toString('base64'), 'Content-Type': 'application/json' };
  const send = async p => { const r = await fetch(URL.replace(/\/$/, '') + '/api/reports', { method: 'POST', headers: as,
    body: JSON.stringify({ action: 'add', project: p, text: 'seen from outside', area: 'Something else' }) }); return { status: r.status, body: await r.json() }; };
  await page.evaluate(() => fetch('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'projects', name: 'repadmin', projects: ['beta'] }) }));
  const refused = await send('alpha');
  ok(refused.status === 403 && /not on alpha/.test(refused.body.error || ''),
     `an administrator not on a project is refused a report from it (${refused.status} ${refused.body.error})`);
  const fine = await send('beta');
  ok(fine.status === 200 && fine.body.ok, '...and sends one from a project it is on');
  // The row draws its bug button from the project's `mine`, which says the
  // same thing to the page.
  const st = await (await fetch(URL.replace(/\/$/, '') + '/api/status', { headers: as })).json();
  const row = n => (st.projects || []).find(p => p.name === n);
  ok(row('alpha')?.mine === false && row('beta')?.mine === true,
     `...and the page is told which rows are its own, so a row it is not on draws no bug button (alpha ${row('alpha')?.mine}, beta ${row('beta')?.mine})`);
  await page.evaluate(() => fetch('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'remove', name: 'repadmin' }) }));
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);

await done(browser);
