// The Settings tab (roadmap R29, then the operator's cut): what is left after
// asking which settings need to exist at all — whether Claude Code updates at
// boot, and which channel — plus the commit identity, which became a
// project's own setting in its dialog. What is exercised for real: the store
// through the endpoint, the tab's rows, the identity landing in the repo's
// own config through /api/prefs and coming out of bb settings, and
// bb_setting — the boot scripts' read — run as bash against the same file.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
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
await page.waitForSelector('.settingstab [data-set="claude_channel"]', { timeout: 15000 });
const groups = await page.$$eval('.settingstab [data-group]', gs => gs.map(g => g.dataset.group));
ok(groups.join('|') === 'Claude Code',
   `the tab's stored settings are one group — Claude Code — and nothing that should be a constant or a project's (${groups.join(', ')})`);
ok(await page.$eval('.settingstab [data-set="claude_auto_update"]', e => e.checked && e.closest('label') !== null)
   && await page.$eval('.settingstab [data-set="claude_channel"]', e => e.tagName === 'SELECT' && e.value === 'latest'),
   'the update switch sits in its label and the channel is a select, on latest by default');
ok(await page.$eval('.settingstab [data-set="claude_shared_login"]', e => e.type === 'checkbox' && !e.checked),
   'the shared-login switch is a checkbox, off by default');
ok((await page.$$eval('.settingstab [data-set="claude_channel"] option', os => os.map(o => o.value))).join(',') === 'stable,latest,next',
   '...offering the channels the package publishes: stable, latest, next');
ok(await page.$eval('.settingstab [data-group="Claude Code"] .actbar .state', e => /next start/.test(e.textContent)),
   'the section says a change takes at the next start');

// ---- saving ----------------------------------------------------------------
await page.selectOption('.settingstab [data-set="claude_channel"]', 'stable');
await page.uncheck('.settingstab [data-set="claude_auto_update"]');
await page.click('.settingstab [data-group="Claude Code"] .setApply');
await page.waitForFunction(() => state?.settings?.settings?.claude_channel?.value === 'stable', null, { timeout: 30000 });
ok(read().claude_channel === 'stable' && read().claude_auto_update === false,
   'Apply writes both under /config and the poll carries them');
await page.waitForFunction(() => !document.querySelector('.settingstab [data-group="Claude Code"] .pill'), null, { timeout: 30000 });
ok(true, '...and the fields are then the owners: no default pill');
const bad = await post('/api/settings', { set: { claude_channel: 'nightly' } });
ok(bad.status === 400 && /one of stable, latest, next/.test(bad.body.error || ''),
   'a channel the package does not publish is refused, naming the three');
ok((await post('/api/settings', { set: { max_tabs: 5 } })).status === 400,
   '...and a key that stopped being a setting is refused too');

// ---- what the boot script reads ------------------------------------------------
const setting = (key, dflt) => execFileSync('bash', ['-c',
  `. ${JSON.stringify(join(HERE, '..', '..', 'lib', 'common.sh'))}; bb_setting ${key} ${JSON.stringify(dflt)}`],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
ok(setting('claude_channel', 'latest') === 'stable', 'bb_setting hands the boot hook the saved channel');
ok(setting('claude_auto_update', 'true') === 'false', '...and a saved false as the word false, so is_true reads it');
ok(setting('nothing_saved', 'dflt') === 'dflt', '...and the default when nothing is saved — no environment variable is read any more');

// ---- the commit identity is the account's ----------------------------------
// Set on the Profile tab, never in a project: two people on one project are
// two authors. It reaches a session as git's environment, and `bb settings
// --json` is how bb-tty asks for it — for the seat BB_ACCOUNT_UID names.
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
await page.click('#projects [data-rn="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(!(await page.$('#rnGitName')), 'the project dialog no longer asks for one');
await page.click('#rnCancel');

await done(browser);
