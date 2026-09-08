// The Settings tab's fields (roadmap R29): what used to be fourteen
// environment variables, edited here, stored under /config, applied at once
// or at the next start. What is exercised for real: the store through the
// endpoint, the tab's rows, the tab cap taking on the next poll, the commit
// identity landing in the builder home's gitconfig, and bb_setting — the
// boot scripts' three-way read — run as bash against the same file.
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
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/settings', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);

// ---- the tab ---------------------------------------------------------------
await page.evaluate(() => openSettingsTab());
await page.waitForSelector('.settingstab [data-set="max_tabs"]', { timeout: 15000 });
const groups = await page.$$eval('.settingstab [data-group]', gs => gs.map(g => g.dataset.group));
ok(groups.join('|') === 'Dashboard|Claude Code|Commit identity|Packages installed at boot|Projects|Unraid',
   `the tab carries a section per group of what used to be an environment variable (${groups.join(', ')})`);
ok(await page.$eval('.settingstab [data-set="max_tabs"]', e => e.value) === '12'
   && await page.$eval('.settingstab [data-set="claude_auto_update"]', e => e.checked)
   && await page.$eval('.settingstab [data-set="unraid_icon_name"]', e => e.value) === 'BuilderBot',
   'with nothing set, each field shows its default');
ok((await page.$$eval('.settingstab .setrow .pill', ps => ps.map(p => p.textContent))).every(t => t === 'default'),
   '...and says so beside it');
ok(await page.$eval('.settingstab [data-group="Packages installed at boot"] .actbar .state', e => /next start/.test(e.textContent))
   && await page.$eval('.settingstab [data-group="Dashboard"] .actbar .state', e => /now/.test(e.textContent)),
   'each section says whether a change takes now or at the next start');

// ---- a live one: the tab cap -------------------------------------------------
await page.fill('.settingstab [data-set="max_tabs"]', '5');
await page.click('.settingstab [data-group="Dashboard"] .setApply');
await page.waitForFunction(() => state?.max_tabs === 5, null, { timeout: 30000 });
ok(read().max_tabs === 5, 'Apply writes the value under /config and the poll carries it at once');
await page.waitForFunction(() => document.querySelector('.settingstab [data-set="max_tabs"]')?.value === '5'
  && !document.querySelector('.settingstab [data-group="Dashboard"] .pill'), null, { timeout: 30000 });
ok(true, '...and the field is then the owner: no source pill');
const bad = await post({ set: { max_tabs: 'lots' } });
ok(bad.status === 400 && /whole number/.test(bad.body.error || ''), 'a value not of the field\'s kind is refused with what it takes');
ok((await post({ set: { nope: 1 } })).status === 400, '...and so is a key that is not a setting');

// ---- one applied at once outside the dashboard: the commit identity ---------
await page.fill('.settingstab [data-set="git_name"]', 'Test Person');
await page.fill('.settingstab [data-set="git_email"]', 'test@example.invalid');
await page.click('.settingstab [data-group="Commit identity"] .setApply');
await page.waitForFunction(() => state?.settings?.settings?.git_name?.value === 'Test Person', null, { timeout: 30000 });
const gitc = k => { try { return execFileSync('git', ['config', '--file', `${DIR}/home/.gitconfig`, k], { encoding: 'utf8' }).trim(); } catch { return ''; } };
ok(gitc('user.name') === 'Test Person' && gitc('user.email') === 'test@example.invalid',
   'the commit identity lands in the builder home\'s gitconfig the moment it is saved');

// ---- what the boot scripts read ------------------------------------------------
await post({ set: { packages_npm: 'web-ext pnpm', claude_auto_update: false } });
const setting = (key, env, dflt, extra = {}) => execFileSync('bash', ['-c',
  `. ${JSON.stringify(join(HERE, '..', '..', 'lib', 'common.sh'))}; bb_setting ${key} ${env} ${JSON.stringify(dflt)}`],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, ...extra } });
ok(setting('packages_npm', 'EXTRA_NPM_PACKAGES', '') === 'web-ext pnpm',
   'bb_setting hands a boot script the saved value');
ok(setting('claude_auto_update', 'AUTO_UPDATE_CLAUDE', 'true') === 'false',
   '...a saved false as the word false, so is_true reads it');
ok(setting('packages_apt', 'EXTRA_APT_PACKAGES', '', { EXTRA_APT_PACKAGES: 'jq ripgrep' }) === 'jq ripgrep',
   '...the variable it replaced when nothing is saved, for one release');
ok(setting('packages_apt', 'EXTRA_APT_PACKAGES', 'nothing') === 'nothing',
   '...and the default when neither is set');
ok(setting('packages_npm', 'EXTRA_NPM_PACKAGES', '', { EXTRA_NPM_PACKAGES: 'old' }) === 'web-ext pnpm',
   '...with the saved value winning over the variable');

await done(browser);
