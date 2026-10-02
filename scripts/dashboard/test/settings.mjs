// The Settings tab (roadmap R29, then the operator's cut): what is left after
// asking which settings need to exist at all. Two switches, since the Claude
// Code update settings went with the install itself (R47), plus the commit
// identity, which became a project's own setting in its dialog. What is
// exercised for real: the store through the endpoint, the tab's rows, the
// identity landing in the repo's own config through /api/prefs and coming out
// of bb settings, and bb_setting (the boot scripts' read) run as bash
// against the same file.
import { launch, newPage, ok, done, ready, saveDialog, openFold, URL, DIR } from './lib.mjs';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const FILE = `${DIR}/state/settings.json`;
const read = () => existsSync(FILE) ? JSON.parse(readFileSync(FILE, 'utf8')) : {};
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
const post = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, [path, body]);

// ---- the tab ---------------------------------------------------------------
await page.evaluate(() => openSettingsTab());
await page.waitForSelector('.settingstab [data-set="debug_mode"]', { timeout: 15000 });
// One tree, two products (roadmap R54, step 6): the switch that offers the
// unvetted git hosts, hypervisors and OS families is a developer's, so it
// lives in the Debugging dialog and not on the tab, off by default, and the
// header carries the word while it is on.
ok(await page.$('.settingstab [data-set="offer_unvetted"]') === null,
   'the "offer dev features" switch is not on the tab');
await page.evaluate(() => openDebugSettings());
ok(await page.$eval('#setdbgBody [data-dbgset="offer_unvetted"]', e => e.type === 'checkbox' && !e.checked),
   '...it is in the Debugging dialog, and starts off');
await page.click('#setdbgCancel');
ok(await page.$eval('#devtag', e => e.hidden), '...and the header says nothing while it is off');
await post('/api/settings', { set: { offer_unvetted: true } });
await page.waitForFunction(() => !document.querySelector('#devtag')?.hidden, null, { timeout: 30000 });
ok(await page.$eval('#devtag', e => e.textContent.trim() === 'dev'),
   '...and says dev once it is on, so two dashboards are never confused');
await post('/api/settings', { set: { offer_unvetted: false } });
await page.waitForFunction(() => document.querySelector('#devtag')?.hidden, null, { timeout: 30000 });
// Reset BuilderBot: a red verb at the foot of the tab behind a typed word,
// refused without it, and never pressed here, since it re-executes the
// server this whole suite is talking to. The move itself is proved at the
// module below, on a directory of its own.
ok(await page.$eval('.settingstab [data-group="Reset"] #setReset', b => /Reset BuilderBot/.test(b.textContent) && b.classList.contains('danger')),
   'Reset BuilderBot sits in its own section as a red verb');
await page.click('.settingstab #setReset');
ok(await page.$eval('.settingstab #setResetBox .dropbox .danger', b => b.disabled)
   && await page.$eval('.settingstab #setResetBox .dropbox .hint', h => /Project files stay/.test(h.textContent)),
   '...which opens a typed confirmation, the real button asleep, saying project files stay');
await page.fill('.settingstab #setResetBox input', 'reset');
ok(await page.$eval('.settingstab #setResetBox .dropbox .danger', b => !b.disabled), '...and wakes on the word');
await page.click('.settingstab #setResetBox .stop');
ok(await page.$('.settingstab #setResetBox .dropbox') === null, '...and Keep it closes it with nothing done');
const noword = await post('/api/reset', { confirm: 'yes' });
ok(noword.status === 400 && /type reset to confirm; nothing was changed/.test(noword.body.error || ''),
   `the endpoint refuses anything but the word (${noword.body.error})`);
{
  const { execFileSync } = await import('node:child_process');
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, os, tempfile
from pathlib import Path
spec = importlib.util.spec_from_file_location('s', ${JSON.stringify(new globalThis.URL('../settings.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = Path(tempfile.mkdtemp())
(d / 'users.json').write_text('{}'); (d / 'logs').mkdir(); (d / 'logs' / 'a.log').write_text('x')
(d / '.reset-20260101-000000').mkdir(); (d / '.reset-20260101-000000' / 'old').write_text('o')
(d / 'runner-tokens').mkdir()
r = m.reset_state(d); dest = r["dest"]
print(json.dumps({"left": sorted(p.name for p in d.iterdir()), "moved": sorted(p.name for p in dest.iterdir()),
                  "old_kept": (d / '.reset-20260101-000000' / 'old').is_file(), "dest": dest.name, "kept": r["kept"]}))
`], { encoding: 'utf8' });
  const r = JSON.parse(out);
  ok(r.moved.join() === 'logs,users.json' && r.left.join() === '.reset-20260101-000000,' + r.dest + ',runner-tokens'
     && r.old_kept && /^\.reset-\d{8}-\d{6}$/.test(r.dest) && r.kept.join() === 'runner-tokens',
     `the reset moves everything into a dated directory beside it, leaves earlier resets and the root-only token store alone, and says what it kept (${JSON.stringify(r)})`);
}
const groups = await page.$$eval('.settingstab [data-group]', gs => gs.map(g => g.dataset.group));
ok(groups.join('|') === 'Debugging|Reset',
   `the tab's stored settings are the one group that survived the question "does this need to exist", and the reset: nothing that should be a constant or a project's (${groups.join(', ')})`);
// Debug mode grants nothing by itself: it puts the grant on a node's row.
// Off by default, because what it opens is root's on the machine.
ok(await page.$eval('.settingstab [data-set="debug_mode"]', e => !e.checked),
   'debug mode is off until somebody turns it on');
// The settings a developer of BuilderBot reaches for sit behind a Debug
// settings button in the same group, which is a real control only once debug
// mode is saved on: a draft tick is not debug mode. It opens a DIALOG, the
// way the node row's Debug settings does: as a fold inside the group its
// fields were saved by the group's Apply, so ticking one and pressing the
// Apply in front of you saved a debug setting without a word about it.
ok(await page.$eval('.settingstab [data-debugshow]', b => b.disabled && /Debug mode on/.test(b.title)),
   'Debug settings is ghosted while debug mode is off, saying to turn it on first');
ok(await page.$('.settingstab [data-set="claude_autoupdate"]') === null
   && await page.$eval('#setdbgmodal', m => m.hidden),
   '...and the Claude Code update switch is not in the group at all, nor its dialog open');
await post('/api/settings', { set: { debug_mode: true } });
await page.waitForFunction(() => !document.querySelector('.settingstab [data-debugshow]')?.disabled,
                           null, { timeout: 30000 });
ok(await page.$eval('#setdbgmodal', m => m.hidden),
   'debug mode on: the button is live, and nothing opens until it is pressed');
await page.click('.settingstab [data-debugshow]');
await page.waitForFunction(() => document.querySelector('#setdbgmodal')?.checkVisibility(),
                           null, { timeout: 8000 });
ok(await page.$eval('#setdbgBody [data-dbgset="claude_autoupdate"]', e => e.type === 'checkbox'
     && !e.checked && e.closest('label') !== null),
   'pressing it opens the dialog, with the Claude Code update switch a checkbox in its label, off by default');
ok(await page.$eval('#setdbgmodal .box .foot', f => !!f.querySelector('.primary')
     && f.querySelectorAll('button').length === 2),
   '...and the dialog saves or cancels on its own foot, rather than riding the group\'s Apply');
ok(await page.$eval('.settingstab [data-group="Debugging"] .actbar .state', e => /applies at once/.test(e.textContent)),
   'the section says a change applies at once, since nothing here waits for a boot');

// ---- saving ----------------------------------------------------------------
await page.check('#setdbgBody [data-dbgset="claude_autoupdate"]');
await page.click('#setdbgSave');
await page.waitForFunction(() => state?.settings?.settings?.claude_autoupdate?.value === true, null, { timeout: 30000 });
ok(read().claude_autoupdate === true,
   'Save writes it under /config and the poll carries it');
await page.waitForFunction(() => document.querySelector('#setdbgmodal')?.hidden, null, { timeout: 8000 });
ok(true, '...and the dialog shuts on the save, the way every dialog here does');
const bad = await post('/api/settings', { set: { claude_autoupdate: 'maybe' } });
ok(bad.status === 400, 'a value that is not the setting\'s shape is refused');
ok((await post('/api/settings', { set: { claude_channel: 'stable' } })).status === 400,
   '...and a key that stopped being a setting is refused too');
// Back off: the rest of this file reads the settings as they started.
await post('/api/settings', { set: { claude_autoupdate: false, debug_mode: false } });

// ---- what the boot script reads ------------------------------------------------
const setting = (key, dflt) => execFileSync('bash', ['-c',
  `. ${JSON.stringify(join(HERE, '..', '..', 'lib', 'common.sh'))}; bb_setting ${key} ${JSON.stringify(dflt)}`],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
ok(setting('claude_autoupdate', 'true') === 'false',
   'bb_setting hands a boot hook the saved value, a false as the word false so is_true reads it');
ok(setting('nothing_saved', 'dflt') === 'dflt', '...and the default when nothing is saved; no environment variable is read any more');

// ---- the commit identity is the account's ----------------------------------
// Set on the Profile tab, never in a project: two people on one project are
// two authors. It reaches a session as git's environment, and `bb settings
// --json` is how bb-tty asks for it, for the seat BB_ACCOUNT_UID names.
const prof = await post('/api/profile', { action: 'save',
  profile: { full_name: 'Test Person', email: 'test@example.invalid' } });
ok(prof.status === 200 && prof.body.git.name === 'Test Person' && prof.body.git.email === 'test@example.invalid',
   'an account sets its name and email on its profile, and its commits carry them unless a git identity says otherwise');
const prof2 = await post('/api/profile', { action: 'save', profile: { git_name: 'T. Person', git_email: 'tp@users.noreply.invalid' } });
ok(prof2.body.git.name === 'T. Person' && prof2.body.git.email === 'tp@users.noreply.invalid',
   '...and a git identity of its own outranks them');
const gitc = k => { try { return execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'config', k], { encoding: 'utf8' }).trim(); } catch { return ''; } };
ok(gitc('user.name') === 'dashboard test' && gitc('user.email') === 'test@example.invalid',
   '...without writing anything into the repository\'s own config, which keeps the fixture\'s');
const owner = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
const st = JSON.parse(execFileSync('bash', [join(HERE, '..', '..', 'bb'), 'settings', '--json'],
  { encoding: 'utf8', env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
    DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha', BB_ACCOUNT_UID: owner } }));
ok(st.git_name === 'T. Person' && st.git_email === 'tp@users.noreply.invalid',
   '...and bb settings --json carries it for the seat asking, which is how bb-tty puts it in a session');
const bare = JSON.parse(execFileSync('bash', [join(HERE, '..', '..', 'bb'), 'settings', '--json'],
  { encoding: 'utf8', env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
    DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: '', BB_ACCOUNT_UID: owner }, cwd: '/' }));
ok(bare.git_name === 'T. Person', '...for a shell with no project too');
// The projects this one reads (prefs.reads) show in bb settings, so a
// session knows its own list without the briefing.
{
  const envs = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha', BB_ACCOUNT_UID: owner };
  await page.evaluate(async () => (await (await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', reads: ['beta'] }) })).json()));
  const text = execFileSync('bash', [join(HERE, '..', '..', 'bb'), 'settings'], { encoding: 'utf8', env: envs });
  const asJson = JSON.parse(execFileSync('bash', [join(HERE, '..', '..', 'bb'), 'settings', '--json'], { encoding: 'utf8', env: envs }));
  ok(/^  reads\s+beta$/m.test(text) && asJson.reads.join() === 'beta',
     `bb settings names the projects this one reads, as text and as JSON (${(text.match(/^  reads.*$/m) || [''])[0]})`);
  await page.evaluate(async () => (await (await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', reads: [] }) })).json()));
}
await page.click('#projects [data-rn="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
// The dialog asks again (17 Sep), but for a different thing: the old field
// was the PROJECT's identity and wrote user.name into the repository, which
// made two people on it one author. This one is the asking ACCOUNT's, on this
// project, and lives in that account's record. The invariant the removal was
// protecting still holds, and is what is asserted: nothing reaches the tree.
ok(!!(await page.$('#rnGitName')) && !!(await page.$('#rnGitEmail')),
   'the project dialog asks for a commit author again, as this account\'s own');
await page.fill('#rnGitName', 'Alter Ego');
await page.fill('#rnGitEmail', 'alter@example.invalid');
await saveDialog(page);
ok(gitc('user.name') === 'dashboard test' && gitc('user.email') === 'test@example.invalid',
   '...and saving it still writes nothing into the repository, which is what the old one got wrong');
const over = JSON.parse(execFileSync('bash', [join(HERE, '..', '..', 'bb'), 'settings', '--json'],
  { encoding: 'utf8', env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
    DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha', BB_ACCOUNT_UID: owner } }));
ok(over.git_name === 'Alter Ego' && over.git_email === 'alter@example.invalid',
   `...and a session here is handed it instead of the Profile's (${over.git_name} <${over.git_email}>)`);
const elsewhere = JSON.parse(execFileSync('bash', [join(HERE, '..', '..', 'bb'), 'settings', '--json'],
  { encoding: 'utf8', env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
    DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'beta', BB_ACCOUNT_UID: owner } }));
ok(elsewhere.git_name === 'T. Person',
   `...on that project only, with every other one still the Profile's (${elsewhere.git_name})`);

// ---- global rules (R63), in each project's notebook --------------------------
// There is no dialog for them (the operator, 2 Oct): they are listed under a
// project's own rules on the Briefing, each with a switch for THIS project,
// and an administrator adds and edits them there for every project. A rule
// typed in one project's notebook comes back out of every project's preamble.
{
  const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  const pre = async p => (await (await fetch(URL.replace(/\/$/, '') + `/api/preamble?project=${p}`, { headers: auth })).json()).text || '';
  const globals = async () => ((await (await fetch(URL.replace(/\/$/, '') + '/api/global-rules', { headers: auth })).json()).rules || []);
  await page.evaluate(() => openSettingsTab());
  await page.waitForSelector('#setNodes', { timeout: 15000 });
  ok(!(await page.$('#setGlobalRules')) && !(await page.$('#grmodal')),
     'Controller settings has no Global rules dialog any more');

  await page.evaluate(() => openNotebook('alpha', 'briefing'));
  await page.waitForSelector('.nb #rulesBox details.sect[data-sect="briefing:rules"]', { state: 'attached', timeout: 20000 });
  await openFold(page, '.nb #rulesBox details.sect[data-sect="briefing:rules"]');
  await page.waitForSelector('.nb #grAddHere', { timeout: 15000 });
  const shipped = (await globals()).filter(r => r.builtin).map(r => r.name);
  const rows = await page.$$eval('.nb #rlGlobal .grule .btitle', es => es.map(e => e.textContent.trim()));
  ok(shipped.length >= 3 && shipped.every(n => rows.includes(n)),
     `a project's Briefing lists every global rule under its own (${rows.join(', ')})`);

  // An administrator adds one here, for every project.
  await page.click('.nb #grAddHere');
  await page.fill('.nb .grule.editing .grName', 'no-secrets');
  await page.fill('.nb .grule.editing .grText', 'Never write credentials into a repository.');
  await page.click('.nb .grule.editing .grSave');
  await page.waitForFunction(() => [...document.querySelectorAll('.nb #rlGlobal .grule .btitle')].some(e => e.textContent.trim() === 'no-secrets'),
    null, { timeout: 15000 });
  ok((await globals()).some(r => r.name === 'no-secrets' && !r.builtin), 'an administrator adds a global rule from a project\'s notebook, stored once');
  ok(/Never write credentials/.test(await pre('alpha')) && /Never write credentials/.test(await pre('beta')) && /\(global\)/.test(await pre('beta')),
     '...and every project\'s sessions are handed it, marked global');

  // Switched off for this project alone, staged until the notebook's Save.
  const row = '.nb #rlGlobal .grule:has(.btitle:text-is("no-secrets"))';
  await openFold(page, row);
  await page.click(`${row} .grHere`);
  ok(/Never write credentials/.test(await pre('alpha')), '...a switch is staged, not written, until Save');
  await page.click('.nb #roadmapSaveQuiet');
  // Waited on the server, not the row: the row says "off here" as soon as
  // the switch is staged.
  await page.waitForFunction(async () => ((await (await fetch('/api/rules?project=alpha')).json()).global || [])
    .some(g => g.name === 'no-secrets' && g.off_here), null, { timeout: 15000, polling: 300 });
  ok(!/Never write credentials/.test(await pre('alpha')) && /Never write credentials/.test(await pre('beta')),
     'Save turns it off for this project alone: alpha\'s sessions stop being handed it and beta\'s are not touched');

  // A shipped one off for every project, from the same place.
  const first = shipped[0];
  const srow = `.nb #rlGlobal .grule:has(.btitle:text-is("${first}"))`;
  await openFold(page, srow);
  await page.click(`${srow} .grEvery`);
  await page.waitForFunction(n => (document.querySelector(`.nb #rlGlobal`)?.textContent || '').includes('off everywhere'), first, { timeout: 15000 });
  ok((await globals()).find(r => r.name === first)?.disabled === true
     && !(await pre('beta')).includes((await globals()).find(r => r.name === first).text.slice(0, 40)),
     `an administrator turns a shipped rule off for every project from there (${first})`);
  ok(/Never write a credential into a repository/.test(await pre('beta')) && /Report what happened, not what\s+should have/.test(await pre('beta')),
     'what nobody would turn off is in the briefing instead: no credential in a repository, a true report');
  // Put back as they were.
  await fetch(URL.replace(/\/$/, '') + '/api/global-rules', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'save', rules: [], disabled: [] }) });
  await fetch(URL.replace(/\/$/, '') + '/api/rules', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', action: 'save', rules: (await (await fetch(URL.replace(/\/$/, '') + '/api/rules?project=alpha', { headers: auth })).json()).rules, globals_off: [] }) });
}

// ---- the time zone is this browser's (Profile, On this browser) ----------
// A cookie, not the account: a phone abroad and the desk at home each keep
// their own. Every time the page shows goes through fmtTime, so picking a
// zone moves them all, and "This device's own" takes the cookie away again.
{
  await page.evaluate(() => openProfileTab());
  await page.waitForSelector('#pfTZ', { timeout: 15000 });
  const zone = 'Pacific/Chatham';          // +12:45: no browser's own zone by accident
  await page.selectOption('#pfTZ', zone);
  ok(await page.$eval('#pfSave', b => b.disabled) && !await page.$eval('#pfTZApply', b => b.disabled),
     'picking a zone lights its own Apply, not the account\'s Save');
  await page.click('#pfTZApply');
  const after = await page.evaluate(z => ({
    cookie: document.cookie.includes('bb_tz=' + encodeURIComponent(z)),
    tz: userTZ(),
    same: fmtTime(0, { hour: '2-digit', minute: '2-digit' })
      === new Date(0).toLocaleString([], { hour: '2-digit', minute: '2-digit', timeZone: z }),
  }), zone);
  ok(after.cookie && after.tz === zone && after.same,
     `Apply keeps the zone in a cookie on this browser, and the page's times follow it (${JSON.stringify(after)})`);
  const acct = await (await page.evaluate(() => fetch('/api/profile').then(r => r.text())));
  ok(!acct.includes(zone), '...and nothing of it is stored against the account');
  await page.waitForSelector('#pfTZ', { timeout: 15000 });
  await page.selectOption('#pfTZ', '');
  await page.click('#pfTZApply');
  ok(await page.evaluate(() => !document.cookie.includes('bb_tz=') && userTZ() === ''),
     'This device\'s own takes the cookie away again');
  await page.evaluate(() => { document.cookie = 'bb_tz=Not%2FAZone; path=/'; });
  ok(await page.evaluate(() => userTZ() === ''), 'a zone this browser does not know is ignored, not trusted');
  await page.evaluate(() => setUserTZ(''));
}

await done(browser);
