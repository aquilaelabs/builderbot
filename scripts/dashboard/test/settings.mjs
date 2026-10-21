// The Settings tab (roadmap R29, then the operator's cut): what is left after
// asking which settings need to exist at all. Two switches, since the Claude
// Code update settings went with the install itself (R47), plus the commit
// identity, which became a project's own setting in its dialog. What is
// exercised for real: the store through the endpoint, the tab's rows, the
// identity landing in the repo's own config through /api/prefs and coming out
// of bb settings, and bb_setting (the boot scripts' read) run as bash
// against the same file.
import { launch, newPage, ok, done, ready, saveDialog, sectSave, rnSect, splitPick, refreshUntil, openFold, URL, DIR, unfold, sleep } from './lib.mjs';
import { readFileSync, existsSync, mkdirSync, writeFileSync, rmSync } from 'node:fs';
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
// Controller settings is a page of settings (the operator, 16 Oct): a
// section is picked from its list before its fields are used.
await page.waitForSelector('.settingstab .snav [data-spick="debug"]', { timeout: 15000 }); await splitPick(page, 'debug');
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
await splitPick(page, 'reset');
await page.click('.settingstab #setReset');
await page.waitForSelector('#resetmodal:not([hidden]) #resetGo', { timeout: 10000 });
ok(await page.$eval('#resetGo', b => b.disabled)
   && await page.$eval('#resetBody .hint.bad', h => /Project files stay/.test(h.textContent)),
   '...which opens a dialog with a typed confirmation, the real button asleep, saying project files stay');
await page.fill('#resetWord', 'reset');
ok(await page.$eval('#resetGo', b => !b.disabled), '...and wakes on the word');
await page.click('#resetKeep');
ok(await page.$eval('#resetmodal', m => m.hidden), '...and Keep it closes it with nothing done');
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
ok(groups.join('|') === 'Logs|Claude sessions|Storage|Apps|Reach from outside|Maintenance|Debugging|Reset',
   `the tab's groups are the ones that survived the question "does this need to exist": the logs, the idle rule, where what grows is kept (the operator, 10 Oct), the apps offered (R272), the home tunnel the controller runs itself (R176), maintenance mode (the owner's), debugging, and the reset (${groups.join(', ')})`);
// Sections, and a page of settings (the operator, 16 Oct): a list of them
// beside the one picked, each row saying what is in it, and Revert beside
// each Apply putting the section's fields back to what is saved.
{
  const sects = await page.$$eval('.settingstab details.sect', ds => ds.map(d => d.querySelector('summary .t').textContent));
  const rows = await page.$$eval('.settingstab .snav [data-spick]', bs => bs.map(b => ({ k: b.dataset.spick, said: b.querySelector('.rtags .dim')?.textContent || '' })));
  ok(sects.length >= 6 && rows.length === sects.length && rows.every(r => r.said),
     `the tab is a list of its sections beside the one picked, each saying what is in it (${rows.map(r => r.k).join(', ')})`);
  const was = await page.$eval('#idleMin', i => i.value);
  await splitPick(page, 'idle');
  // Apply and Revert sleep until a field differs from what is saved, and
  // again when it is typed back (R218 step 32, as Profile's do).
  const G = '.settingstab [data-group="Claude sessions"]';
  const awake = () => page.$eval(G, g => [g.querySelector('#idleApply').disabled, g.querySelector('[data-srevert]').disabled].join());
  const atRest = await awake();
  await page.fill('#idleMin', '4321');
  const changed = await awake();
  await page.fill('#idleMin', was);
  const back = await awake();
  ok(atRest === 'true,true' && changed === 'false,false' && back === 'true,true',
     `a section's Apply and Revert sleep until a field differs, and again when it is typed back (${atRest} | ${changed} | ${back})`);
  await page.fill('#idleMin', '4321');
  await page.click('.settingstab [data-group="Claude sessions"] [data-srevert]');
  await page.waitForFunction(w => document.getElementById('idleMin')?.value === w, was, { timeout: 10000 });
  ok(true, 'Revert on a section puts its field back to what is saved');
  ok(await page.$eval('.settingstab [data-group="Reach from outside"] .setsteps', ol => ol.querySelectorAll('li').length === 4 && /localhost:\d+/.test(ol.textContent)),
     'the Reach from outside section carries its own setup steps, with the controller\'s port in them');
}

// The home tunnel (R176): a hostname, two secrets never shown back, and the
// controller running cloudflared itself (the harness's stub) from them, with
// the group's line reading the process. The token is nowhere in the page.
{
  const G = '.settingstab [data-group="Reach from outside"]';
  await splitPick(page, 'tunnel');
  const f = await page.$eval(G, g => ({ host: g.querySelector('[data-set="tunnel_host"]')?.type,
    tok: g.querySelector('[data-set="tunnel_token"]')?.type, api: g.querySelector('[data-set="cf_api_token"]')?.type,
    pills: [...g.querySelectorAll('.pill')].map(p => p.textContent), state: g.querySelector('.actbar .state').textContent }));
  ok(f.host === 'text' && f.tok === 'password' && f.api === 'password' && f.pills.filter(p => p === 'not set').length === 2
     && /off: paste a tunnel token/.test(f.state),
     `the Reach from outside group asks for the hostname and two secrets, typed blind, and says the tunnel is off (${JSON.stringify(f)})`);
  const TOKEN = Buffer.from(JSON.stringify({ a: 'a'.repeat(32), t: '12345678-1234-1234-1234-123456789abc', s: 'x' })).toString('base64');
  await page.fill(`${G} [data-set="tunnel_host"]`, 'not a host');
  await page.click(`${G} .setApply`);
  await page.waitForFunction(() => /hostname like/.test(document.getElementById('toast')?.textContent || ''), null, { timeout: 10000 }).catch(() => {});
  ok(await page.evaluate(() => /hostname like/.test(document.getElementById('toast')?.textContent || '')),
     'a hostname that is not one is refused by name');
  await page.fill(`${G} [data-set="tunnel_host"]`, 'bb.example.com');
  await page.fill(`${G} [data-set="tunnel_token"]`, TOKEN);
  await page.click(`${G} .setApply`);
  await page.waitForFunction(sel => /connected: bb\.example\.com/.test(document.querySelector(sel + ' .actbar .state')?.textContent || ''), G, { timeout: 20000 });
  const after = await page.$eval(G, g => ({ pills: [...g.querySelectorAll('.pill')].map(p => p.textContent),
    tok: g.querySelector('[data-set="tunnel_token"]').value, clear: !!g.querySelector('[data-clear="tunnel_token"]') }));
  ok(after.pills.includes('set') && after.tok === '' && after.clear
     && !(await page.evaluate(t => JSON.stringify(state.settings).includes(t), TOKEN)),
     `Apply runs the tunnel and the line reads connected; the token is set, blank in its box and nowhere in the page (${JSON.stringify(after.pills)})`);
  ok(/registered tunnel connection/i.test((await page.evaluate(() => state.settings.tunnel.tail.join('\n')))),
     '...and the process\'s last lines are what the server read');
  // Enroll node fills the hostname in for a node reaching the controller
  // through it.
  await page.evaluate(() => openNodesTab());
  await page.waitForSelector('.nodestab #ndEnroll', { timeout: 15000 });
  await page.click('.nodestab #ndEnroll');
  await page.waitForSelector('#ndBody #ndEnReach', { timeout: 10000 });
  await page.selectOption('#ndBody #ndEnReach', 'public');
  ok(await page.$eval('#ndBody #ndEnCtl', e => e.value) === 'https://bb.example.com',
     'Enroll node fills the controller\'s own public hostname in');
  // Asked for by its own public hostname, the controller answers the
  // agent's API and nothing else, whatever rule the tunnel carries
  // (bb.neat.fish served its login through a wide rule, 11 Oct).
  const viaHost = (path) => execFileSync('curl', ['-s', '-o', '/dev/null', '-w', '%{http_code}', '-H', 'Host: bb.example.com',
    '-u', 'test:test', URL.replace(/\/$/, '') + path]).toString();
  ok(viaHost('/api/status') === '403' && viaHost('/') === '403' && viaHost('/api/v1/agent/hello') !== '403',
     `by its own hostname the controller refuses its pages and keeps the agent's API (${viaHost('/api/status')}, ${viaHost('/')})`);
  await page.click('#ndBody #ndEnCancel');
  await page.evaluate(() => openSettingsTab());
  await page.waitForSelector(`${G} [data-clear="tunnel_token"]`, { timeout: 15000 });
  await page.check(`${G} [data-clear="tunnel_token"]`);
  await page.click(`${G} .setApply`);
  await page.waitForFunction(sel => /off: paste a tunnel token/.test(document.querySelector(sel + ' .actbar .state')?.textContent || ''), G, { timeout: 20000 });
  ok(true, '...and taking the token off stops the tunnel');
  await post('/api/settings', { set: { tunnel_host: '' } });
}
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
ok(await page.$eval('.settingstab [data-debugshow]', b => b.disabled && /Debug mode on/.test(saidOf(b))),
   'Debug settings is ghosted while debug mode is off, saying to turn it on first');
ok(await page.$('.settingstab [data-set="offer_unvetted"]') === null
   && await page.$eval('#setdbgmodal', m => m.hidden),
   '...and the dev features switch is not in the group at all, nor its dialog open');
await post('/api/settings', { set: { debug_mode: true } });
await page.waitForFunction(() => !document.querySelector('.settingstab [data-debugshow]')?.disabled,
                           null, { timeout: 30000 });
ok(await page.$eval('#setdbgmodal', m => m.hidden),
   'debug mode on: the button is live, and nothing opens until it is pressed');
await splitPick(page, 'debug');
await page.click('.settingstab [data-debugshow]');
await page.waitForFunction(() => document.querySelector('#setdbgmodal')?.checkVisibility(),
                           null, { timeout: 8000 });
ok(await page.$eval('#setdbgBody [data-dbgset="offer_unvetted"]', e => e.type === 'checkbox'
     && !e.checked && e.closest('label') !== null),
   'pressing it opens the dialog, with the dev features switch a checkbox in its label, off by default');
// Gone on 7 Oct (the operator): a node's Claude Code is updated when Update
// is pressed, and never before a session starts.
ok(await page.$('#setdbgBody [data-dbgset="claude_autoupdate"]') === null,
   '...and no switch updates Claude Code before a session starts');
ok(await page.$eval('#setdbgmodal .box .foot', f => !!f.querySelector('.primary')
     && f.querySelectorAll('button').length === 2),
   '...and the dialog saves or cancels on its own foot, rather than riding the group\'s Apply');
ok(await page.$eval('.settingstab [data-group="Debugging"] .actbar .state', e => /applies at once/.test(e.textContent)),
   'the section says a change applies at once, since nothing here waits for a boot');

// ---- saving ----------------------------------------------------------------
await page.check('#setdbgBody [data-dbgset="offer_unvetted"]');
await page.click('#setdbgSave');
await page.waitForFunction(() => state?.settings?.settings?.offer_unvetted?.value === true, null, { timeout: 30000 });
ok(read().offer_unvetted === true,
   'Save writes it under /config and the poll carries it');
await page.waitForFunction(() => document.querySelector('#setdbgmodal')?.hidden, null, { timeout: 8000 });
ok(true, '...and the dialog shuts on the save, the way every dialog here does');
const bad = await post('/api/settings', { set: { offer_unvetted: 'maybe' } });
ok(bad.status === 400, 'a value that is not the setting\'s shape is refused');
ok((await post('/api/settings', { set: { claude_channel: 'stable' } })).status === 400
   && (await post('/api/settings', { set: { claude_autoupdate: true } })).status === 400,
   '...and a key that stopped being a setting is refused too');
// Back off: the rest of this file reads the settings as they started.
await post('/api/settings', { set: { offer_unvetted: false, debug_mode: false } });

// ---- what the boot script reads ------------------------------------------------
const setting = (key, dflt) => execFileSync('bash', ['-c',
  `. ${JSON.stringify(join(HERE, '..', '..', 'lib', 'common.sh'))}; bb_setting ${key} ${JSON.stringify(dflt)}`],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
ok(setting('offer_unvetted', 'true') === 'false',
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
// The repository's own config alone: a session's environment carries its
// identity as GIT_CONFIG_KEY_n, which git config would answer with (B146).
const repoEnv = Object.fromEntries(Object.entries(process.env).filter(([k]) => !/^GIT_CONFIG_(COUNT|KEY_|VALUE_)/.test(k)));
const gitc = k => { try { return execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'config', k], { encoding: 'utf8', env: repoEnv }).trim(); } catch { return ''; } };
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
await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
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
  await page.waitForSelector('.settingstab .snav [data-spick="logs"]', { timeout: 15000 });
  // Reset last, and no section that only linked to the Nodes page (R218 step 32).
  const order = await page.$$eval('.settingstab .snav [data-spick]', bs => bs.map(b => b.dataset.spick));
  ok(!order.includes('nodes') && order.at(-1) === 'reset', `Controller settings ends on Reset, with no Nodes section (${order.join(', ')})`);
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

  // Switched off for this project alone, staged until the rules section's Save.
  const row = '.nb #rlGlobal .grule:has(.btitle:text-is("no-secrets"))';
  await openFold(page, row);
  await page.click(`${row} .grHere`);
  ok(/Never write credentials/.test(await pre('alpha')), '...a switch is staged, not written, until Save');
  await page.click('.nb [data-ssave="briefing:rules"]');
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
  ok(/never write a credential into a repository/.test(await pre('beta')) && /never a success you did not see/.test(await pre('beta')),
     'what nobody would turn off is in the briefing\'s core instead: no credential in a repository, a true report');
  // Put back as they were.
  await fetch(URL.replace(/\/$/, '') + '/api/global-rules', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'save', rules: [], disabled: [] }) });
  await fetch(URL.replace(/\/$/, '') + '/api/rules', { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', action: 'save', rules: (await (await fetch(URL.replace(/\/$/, '') + '/api/rules?project=alpha', { headers: auth })).json()).rules, globals_off: [] }) });
}

// ---- the time zone is this browser's (the gear, R218 step 31) ------------
// A cookie, not the account: a phone abroad and the desk at home each keep
// their own. Every time the page shows goes through fmtTime, so picking a
// zone moves them all, and "This device's own" takes the cookie away again.
// It sits in the gear beside the scheme, the other choice that is this
// browser's, and Profile no longer lists it.
{
  await page.evaluate(() => openProfileTab());
  await page.waitForSelector('.profiletab .snav [data-spick]', { timeout: 15000 });
  ok(await page.$('.profiletab .snav [data-spick="browser"]') === null && await page.$('.profiletab #pfTZ') === null,
     'Profile no longer carries the time zone');
  await page.evaluate(() => toggleUiMenu(true));
  await page.waitForSelector('#uiMenu #uiTZ', { timeout: 15000 });
  const zone = 'Pacific/Chatham';          // +12:45: no browser's own zone by accident
  const asleep = await page.$eval('#uiTZApply', b => b.disabled);
  await page.selectOption('#uiTZ', zone);
  ok(asleep && !await page.$eval('#uiTZApply', b => b.disabled),
     'in the gear, picking a zone wakes its Apply, asleep until then');
  await page.click('#uiTZApply');
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
  await page.waitForSelector('#uiMenu #uiTZ', { timeout: 15000 });
  await page.selectOption('#uiTZ', '');
  await page.click('#uiTZApply');
  ok(await page.evaluate(() => !document.cookie.includes('bb_tz=') && userTZ() === ''),
     'This device\'s own takes the cookie away again');
  await page.evaluate(() => { document.cookie = 'bb_tz=Not%2FAZone; path=/'; });
  ok(await page.evaluate(() => userTZ() === ''), 'a zone this browser does not know is ignored, not trusted');
  await page.evaluate(() => { setUserTZ(''); toggleUiMenu(false); });
}

// ---- a project's settings live in its notebook (R119 step 3) ---------------
// The row's gear went, and the form is the notebook's Settings view: the
// same form, moved there while the view is on screen, each section saving
// itself, and back to the dialog when another view is picked.
{
  await page.evaluate(() => { document.querySelectorAll('.modal:not(.inline)').forEach(m => { m.hidden = true; }); });
  // The sidebar's row carries no gear; the Projects page's card offers
  // Settings in its menu by design (R218 step 3), not as a button on the row.
  ok(!(await page.$('#projects [data-rn]')) && !(await page.$('.doc .projtab .pcacts > [data-rn]')),
     'no project row carries a settings button any more');
  await page.evaluate(() => openProjectSettings('alpha'));
  await page.waitForSelector('.nb .nbview[data-view="settings"]:not([hidden]) .nbsettings #rnName', { timeout: 15000 });
  const inView = await page.evaluate(() => ({ name: $('rnName').value, modal: $('rnmodal').hidden,
    close: $('rnCancel').hidden, shown: $('rnName').checkVisibility(),
    bars: [...document.querySelectorAll('.nbsettings .rnbar')].filter(b => b.checkVisibility()).length }));
  ok(inView.name === 'alpha' && inView.modal && inView.close && inView.shown && inView.bars === 1,
     `the notebook's Settings view holds the form, the dialog shut, the section on show with its own Save and Revert (${JSON.stringify(inView)})`);
  // The sections a list beside the one picked (the operator, 16 Oct: too
  // many open at once to find a setting in): each row names what is in it,
  // a press shows that section alone, and People is on the list.
  // People joins the list when its read lands.
  await page.waitForSelector('.nbsettings .snav [data-spick="people"]', { timeout: 15000 }).catch(() => {});
  const list = await page.evaluate(() => [...document.querySelectorAll('.nbsettings .snav [data-spick]')]
    .map(b => ({ k: b.dataset.spick, on: b.classList.contains('on'), said: b.querySelector('.rtags .dim')?.textContent || '' })));
  ok(list.length >= 8 && list[0].k === 'project' && list[0].on && list.every(r => r.said) && list.some(r => r.k === 'people'),
     `...its sections a list beside the one picked, each saying what is in it, General first, People among them (${list.map(r => r.k).join(', ')})`);
  // Every section listed opens on something: Repository's fields are the
  // remote's door's, and it was listed and opened on an empty pane (B813).
  {
    const blank = [];
    for (const { k } of list){
      await page.click(`.nbsettings .snav [data-spick="${k}"]`);
      const h = await page.evaluate(k => document.querySelector(`.nbsettings details.rngroup[data-sect="rn:${k}"]`)?.getBoundingClientRect().height || 0, k);
      if (h < 40) blank.push(`${k} ${Math.round(h)}px`);
    }
    await rnSect(page, 'repo');
    const repo = await page.evaluate(() => ({ say: $('rnRepoSay').textContent, go: $('rnRepoGo').textContent,
      bar: [...document.querySelectorAll('.nbsettings details[data-sect="rn:repo"] .rnbarf')].some(b => b.checkVisibility()) }));
    ok(!blank.length && /Linked to GitHub/.test(repo.say) && /GitHub settings/.test(repo.go) && !repo.bar,
       `...every section listed opens on something, Repository saying what its remote is with the door to it and no Save of its own (${blank.join(', ') || 'none blank'}; ${repo.say} ${repo.go})`);
  }
  await rnSect(page, 'claude');
  const one = await page.evaluate(() => [...document.querySelectorAll('.nbsettings details.rngroup')]
    .filter(d => d.checkVisibility()).map(d => d.dataset.sect));
  ok(one.join() === 'rn:claude', `...a row pressed shows its section alone (${one.join()})`);
  ok(!(await page.$eval('.nbsettings .sectjump', e => e.checkVisibility()).catch(() => false)),
     '...with no jump bar over it: the list is how a section is found');
  // People stays when the view is asked for again (B: the form was put back
  // and People hidden until its read landed, on every ask).
  await page.evaluate(() => openProjectSettings('alpha'));
  await page.waitForTimeout(300);
  const still = await page.evaluate(() => ({ people: !document.querySelector('details[data-sect="rn:people"]').hidden,
    pick: document.querySelector('.nbsettings .snav .rrow.on')?.dataset.spick }));
  ok(still.people && still.pick === 'claude', `...and asked for again it keeps People and the section picked (${JSON.stringify(still)})`);
  // The box borrowed from the dialog brings no dialog shadow into the view
  // (B702): the scroll-hint class it wore in the dialog is dropped on the way
  // in, and an inline box gets no shadow from that class however it arrives.
  const shade = await page.evaluate(() => {
    const dlg = document.querySelector('#rnmodal > .box') || document.querySelector('.nbsettings > .box');
    dlg.classList.add('scrolldown');
    settingsOut(); settingsInto('alpha', document.querySelector('.nbview[data-view="settings"] .nbsettings'));
    const b = document.querySelector('.nbsettings > .box');
    const moved = { cls: b.className, shadow: getComputedStyle(b).boxShadow };
    b.classList.add('scrolldown');
    return { moved, forced: getComputedStyle(b).boxShadow };
  });
  ok(!/scroll(up|down)/.test(shade.moved.cls) && shade.moved.shadow === 'none' && shade.forced === 'none',
     `...and wears no dialog shadow, with or without the dialog's scroll-hint class (${JSON.stringify(shade)})`);
  // A section's Save writes that section alone, and what is typed in another
  // stays typed (the operator, 10 Oct: one Save for eleven sections).
  await rnSect(page, 'build');
  await page.fill('#rnBuildCmd', 'make one');
  await rnSect(page, 'claude');
  await page.selectOption('#rnGateRoadmap', 'deny');
  const marks = await page.evaluate(() => [...document.querySelectorAll('.nbsettings .snav [data-spick]')]
    .filter(b => !b.querySelector('.sunsaved').hidden).map(b => b.dataset.spick).sort().join());
  ok(marks === 'build,claude', `...each section holding a change says unsaved on its row (${marks})`);
  const err = await sectSave(page, 'build');
  await refreshUntil(page, () => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.build === 'make one', { timeout: 20000 });
  const after = await page.evaluate(() => ({ gate: (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.gate?.roadmap || 'auto',
    typed: $('rnGateRoadmap').value, claude: !document.querySelector('.rnbar[data-rnbar="claude"] [data-rnsave]').disabled,
    build: document.querySelector('.rnbar[data-rnbar="build"] [data-rnsave]').disabled }));
  ok(!err && after.gate === 'auto' && after.typed === 'deny' && after.claude && after.build,
     `...Build and test's Save stores the build command and nothing of Claude may, whose change stays typed and unsaved (${JSON.stringify(after)})`);
  await rnSect(page, 'claude');
  await page.click('.rnbar[data-rnbar="claude"] [data-rnrevert]');
  ok(await page.evaluate(() => $('rnGateRoadmap').value === 'auto'
       && document.querySelector('.rnbar[data-rnbar="claude"] [data-rnrevert]').disabled
       && $('rnBuildCmd').value === 'make one'),
     '...and its Revert puts Claude may back alone');
  // A section's Save is its own fields alone, and refuses one somebody else
  // saved since these settings were opened (the operator, 17 Oct: a save in
  // one section put back another section's change, and a session's change
  // not yet on screen was written over without a word).
  {
    await post('/api/prefs', { project: 'alpha', build: '' });
    await refreshUntil(page, () => !(state?.projects || []).find(p => p.name === 'alpha')?.prefs?.build, { timeout: 20000 });
    await page.evaluate(() => { settingsOut(); openProjectSettings('alpha'); });
    await page.waitForSelector('.nbsettings .snav [data-spick="build"]', { timeout: 15000 });
    // A status read already out, answered before the save below and landing
    // only after Save is pressed, as a loaded box has them (B100): the Save
    // read "what is saved now" from it, and wrote over the other save
    // unseen. Held here, so the order is the one the gate met by chance.
    let release, read = false, caught = false;
    const held = new Promise(r => { release = r; });
    await page.route('**/api/status', async r => {
      if (caught) return r.fallback();
      caught = true;
      const before = await r.fetch();
      read = true;
      await held;
      await r.fulfill({ response: before });
    });
    await page.evaluate(() => { refresh(); });
    for (let i = 0; i < 300 && !read; i++) await sleep(100);
    // Elsewhere, after this window opened: the color (another section) and
    // the build command (this one), as a session or another window would.
    await post('/api/prefs', { project: 'alpha', color: 'teal', build: 'make theirs' });
    await rnSect(page, 'build');
    await page.fill('#rnBuildCmd', 'make mine');
    setTimeout(release, 1500);
    const first = await sectSave(page, 'build');
    await page.unroute('**/api/status');
    ok(read, 'a status read sent before the other save was out when Save was pressed');
    const kept = await page.evaluate(() => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.build);
    ok(/Build changed since these settings were opened/.test(first) && kept === 'make theirs',
       `a field saved elsewhere since the settings opened is not written over unseen: the save is refused, naming it (${first.slice(0, 90)}; saved: ${kept})`);
    const second = await sectSave(page, 'build');
    await refreshUntil(page, () => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.build === 'make mine', { timeout: 20000 });
    const now = await page.evaluate(() => (state?.projects || []).find(p => p.name === 'alpha')?.prefs || {});
    ok(!second && now.build === 'make mine' && now.color === 'teal',
       `...Save again writes this one's, and leaves the color another section saved alone (${JSON.stringify({ build: now.build, color: now.color })})`);
    await post('/api/prefs', { project: 'alpha', build: '', color: '' });
  }
  // Also works on is drawn from what is saved until a draw has had nodes to
  // draw: one made before the node list arrived marked itself drawn, and the
  // real one read its own empty boxes (B796, seen on dev, 16 Oct).
  {
    const ns = await page.evaluate(async () => (await (await fetch('/api/v1/nodes')).json()).nodes);
    const first = ns.find(n => n.kind !== 'local');
    const other = (await post('/api/v1/nodes', { action: 'enroll', name: 'also-works' })).body;
    await post('/api/prefs', { project: 'alpha', node: first.id, nodes: [first.id, other.id] });
    await refreshUntil(page, () => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.nodes?.length === 2, { timeout: 20000 });
    // Opened before the node list is known, as a first open is: the picker
    // draws, reads the nodes, and draws again.
    await page.evaluate(() => { getNotebook('alpha')?.view('roadmap'); nodesList = null; openProjectSettings('alpha'); });
    await page.waitForFunction(() => nodesList !== null, null, { timeout: 15000 });
    await page.waitForTimeout(800);
    const also = await page.evaluate(id => ({ ticked: !!document.querySelector(`#rnNodesMore input[value="${id}"]`)?.checked,
      unsaved: !document.querySelector('.snav [data-spick="runs"] .sunsaved')?.hidden }), other.id);
    ok(also.ticked && !also.unsaved,
       `a project's second node is ticked under Also works on when its settings open before the node list is read, and Nodes holds nothing unsaved (${JSON.stringify(also)})`);
    await post('/api/prefs', { project: 'alpha', node: first.id, nodes: [first.id] });
    await post('/api/v1/nodes', { action: 'retire', id: other.id });
  }
  await page.evaluate(() => getNotebook('alpha').view('roadmap'));
  ok(await page.evaluate(() => !!document.querySelector('#rnmodal > .box') && $('rnmodal').hidden),
     '...and picking another view puts the form back where the dialog keeps it');
}

// ---- a project's daily snapshots (R165) ------------------------------------------
// In the project's settings: how many days are kept, and a Snapshots fold
// listing each day with Restore; a restore of one file puts it back, and the
// line it leaves names the snapshot taken first, which undoes it.
{
  await page.evaluate(() => { document.querySelectorAll('.modal:not(.inline)').forEach(m => { m.hidden = true; }); openProjectSettings('alpha'); });
  await page.waitForSelector('#rnSnapDays', { state: 'attached', timeout: 15000 });
  ok(await page.$eval('#rnSnapDays', i => i.value) === '14', 'a project keeps 14 days of snapshots unless set otherwise');
  // Each number beside its unit, not over it (B51: "days" on a line under
  // its box), at a desk and on a phone.
  {
    await rnSect(page, 'rn:build');
    await openFold(page, 'details.sect[data-sect="rn:build"]');
    const was = page.viewportSize(), apart = [];
    for (const width of [1280, 393]){
      await page.setViewportSize({ width, height: 900 });
      await page.waitForTimeout(200);
      apart.push(...(await page.$$eval('#rnCaptureDays, #rnSnapDays, #rnDevKeep', is => is.map(i => {
        const a = i.getBoundingClientRect(), b = i.nextElementSibling.getBoundingClientRect();
        // On the box's line (the row lines up at the bottom) and after it.
        return b.top < a.bottom && b.bottom > a.top && b.left >= a.right ? ''
          : `${i.id} ${[a.left, a.top, a.width, b.left, b.top].map(Math.round).join('/')} in ${i.closest('.modal, .nb')?.className.split(' ')[0]} ${i.checkVisibility()}`;
      }).filter(Boolean))).map(x => `${width} ${x}`));
    }
    await page.setViewportSize(was);
    ok(apart.length === 0, `Build and test's numbers each have their unit beside them (${apart.join(', ') || 'all beside'})`);
  }
  writeFileSync(`${DIR}/ws/alpha/snapped.txt`, 'as it was\n');
  const took = await post('/api/snapshots', { project: 'alpha', action: 'take' });
  ok(took.status === 200 && took.body.files > 0, `Take one now snapshots the tree (${took.body.files} files)`);
  await page.evaluate(() => { openProjectSettings('alpha'); });
  await openFold(page, 'details.sect[data-sect="rn:snapshots"]');
  await page.waitForSelector('#rnSnapRows .rnsnap', { timeout: 15000 });
  writeFileSync(`${DIR}/ws/alpha/snapped.txt`, 'tampered\n');
  page.dialogs.length = 0;
  await page.fill('#rnSnapRows .rnsnap [data-snapfile]', 'snapped.txt');
  await page.click('#rnSnapRows .rnsnap [data-snapone]');
  await page.waitForFunction(() => /restored: 1 written/.test(document.querySelector('#notify, .notify, .toast')?.textContent || '')
                             || document.querySelectorAll('#rnSnapRows .rnsnap').length >= 2, null, { timeout: 15000 });
  ok(readFileSync(`${DIR}/ws/alpha/snapped.txt`, 'utf8') === 'as it was\n' && page.dialogs.length === 1
     && /Put snapped.txt back/.test(page.dialogs[0]),
     'Restore file asks, then puts the file back as it was that day');
  const kept = (await page.evaluate(async () => (await (await fetch('/api/snapshots?project=alpha')).json()).days));
  ok(kept.some(d => /before-restore/.test(d.day)), '...having snapshotted the tree first, so the restore can be undone');
  // From outside the page, which carries no sign-in: nothing is listed.
  const anon = (await fetch(URL.replace(/\/$/, '') + '/api/snapshots?project=alpha')).status;
  ok(anon === 401 || anon === 403, `...and nothing is listed to a caller who is not signed in (${anon})`);
  rmSync(`${DIR}/ws/alpha/snapped.txt`, { force: true });
}

// ---- where the controller keeps what grows (paths.py, the operator, 10 Oct) ----
// Each kind on its own line of the Storage section with the path in use;
// Apply moves what is there to the new path and switches once it is all
// there; a path in the projects or one with something in it is refused in
// words; and the default comes back with what was moved.
{
  await page.evaluate(() => { document.querySelectorAll('.modal:not(.inline)').forEach(m => { m.hidden = true; }); openSettingsTab(); });
  await page.waitForSelector('.settingstab .snav [data-spick="paths"]', { timeout: 15000 }); await splitPick(page, 'paths');
  await page.waitForSelector('.settingstab [data-group="Storage"] input[data-path="gitview"]', { timeout: 15000 });
  const names = await page.$$eval('.settingstab input[data-path]', l => l.map(i => i.dataset.path));
  ok(['project-snapshots', 'job-snapshots', 'gitrelay', 'gitview', 'logs'].every(n => names.includes(n)),
     `the Storage section lists each kind that grows (${names.join(', ')})`);
  const before = await page.$eval('.settingstab input[data-path="gitview"]', i => i.value);
  ok(before === `${DIR}/state/gitview`, `...each at its default in the state directory (${before})`);
  const inWs = await post('/api/paths', { name: 'gitview', path: `${DIR}/ws/alpha/gv` });
  ok(inWs.status === 400 && /inside the projects/.test(inWs.body.error || ''),
     `a path in the projects is refused: nodes' writes land there (${inWs.body.error})`);
  mkdirSync(`${DIR}/full`, { recursive: true });
  writeFileSync(`${DIR}/full/x`, 'x');
  const full = await post('/api/paths', { name: 'gitview', path: `${DIR}/full` });
  ok(full.status === 400 && /not empty/.test(full.body.error || ''), `...and so is one with something in it (${full.body.error})`);
  mkdirSync(`${DIR}/state/gitview/marker`, { recursive: true });
  writeFileSync(`${DIR}/state/gitview/marker/f`, 'kept');
  const to = `${DIR}/elsewhere/gitview`;
  await page.fill('.settingstab input[data-path="gitview"]', to);
  await page.click('#pathsApply');
  await page.waitForFunction(t => (state?.paths?.paths || []).find(p => p.name === 'gitview' && p.path === t && !p.moving),
                             to, { timeout: 20000 });
  ok(existsSync(`${to}/marker/f`) && !existsSync(`${DIR}/state/gitview/marker`),
     'Apply moves what is there to the new path and switches to it once it has all arrived');
  await page.waitForFunction(() => /default: /.test(document.querySelector('.settingstab [data-group="Storage"]')?.textContent || ''),
                             null, { timeout: 10000 });
  ok(true, '...and the line says what the default was');
  const back = await post('/api/paths', { name: 'gitview', path: '' });
  await page.waitForFunction(d => (state?.paths?.paths || []).find(p => p.name === 'gitview' && p.path === d && !p.moving),
                             `${DIR}/state/gitview`, { timeout: 20000 });
  ok(back.status === 200 && existsSync(`${DIR}/state/gitview/marker/f`),
     '...and an empty path puts it back at its default, with what is there');
}

// ---- Profile's What you may do on a phone (B76) -------------------------------
// One column of facts, every value starting at one line: each began where
// its own label ended, two ragged columns.
{
  const phone = await newPage(browser, { viewport: { width: 360, height: 780 }, isMobile: true, hasTouch: true });
  await phone.goto(URL);
  await ready(phone);
  await phone.evaluate(() => openProfileTab());
  await phone.waitForSelector('.profiletab [data-spick="may"]', { timeout: 15000 });
  await phone.click('.profiletab [data-spick="may"]');
  await phone.waitForSelector('.profiletab dl.facts dd', { timeout: 10000 });
  const xs = await phone.$$eval('.profiletab dl.facts .fact dd', ds => [...new Set(ds.filter(d => d.offsetHeight)
    .map(d => Math.round(d.getBoundingClientRect().left)))]);
  const over = await phone.evaluate(() => document.documentElement.scrollWidth - innerWidth);
  if (process.env.BB_SHOT_DIR) await phone.screenshot({ path: `${process.env.BB_SHOT_DIR}/profile-may-360.png` });
  ok(xs.length === 1 && over <= 0, `on a phone What you may do lines its values up in one column (starts at ${xs.join('/')})`);
  await phone.close();
}

await done(browser);
