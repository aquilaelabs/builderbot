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

// ---- the commit identity is a project's -------------------------------------
const who = await post('/api/prefs', { project: 'alpha', git_name: 'Test Person', git_email: 'test@example.invalid' });
ok(who.status === 200 && who.body.git_name === 'Test Person',
   'a project takes its commit identity in its settings dialog');
const gitc = k => { try { return execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'config', k], { encoding: 'utf8' }).trim(); } catch { return ''; } };
ok(gitc('user.name') === 'Test Person' && gitc('user.email') === 'test@example.invalid',
   '...written into that repo\'s own config at once, not the container\'s global one');
const st = JSON.parse(execFileSync('bash', [join(HERE, '..', '..', 'bb'), 'settings', '--json'],
  { encoding: 'utf8', env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
    DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha' } }));
ok(st.git_name === 'Test Person' && st.git_email === 'test@example.invalid',
   '...and bb settings carries it, which is how a session on a node writes it into the tree there');
// The dialog fills from the poll's copy of the project, which follows the
// save on the next poll (the prefs file is on the revision list).
await page.waitForFunction(() => (state?.projects || []).find(p => p.name === 'alpha')?.prefs?.git_name === 'Test Person',
                           null, { timeout: 30000 });
await page.click('#projects [data-rn="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnGitName', e => e.value) === 'Test Person'
   && await page.$eval('#rnGitEmail', e => e.value) === 'test@example.invalid',
   'the dialog shows the project\'s identity');
await page.click('#rnCancel');

await done(browser);
