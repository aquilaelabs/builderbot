// The Settings tab (roadmap R29, then the operator's cut): what is left after
// asking which settings need to exist at all — two switches, since the Claude
// Code update settings went with the install itself (R47) — plus the commit
// identity, which became a project's own setting in its dialog. What is
// exercised for real: the store through the endpoint, the tab's rows, the
// identity landing in the repo's own config through /api/prefs and coming out
// of bb settings, and bb_setting — the boot scripts' read — run as bash
// against the same file.
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
await page.waitForSelector('.settingstab [data-set="debug_mode"]', { timeout: 15000 });
// One tree, two products (roadmap R54, step 6): the switch that offers the
// unvetted git hosts, hypervisors and OS families sits in its own group,
// off by default, and the header carries the word while it is on.
ok(await page.$eval('.settingstab [data-set="offer_unvetted"]', e => e.type === 'checkbox' && !e.checked
     && e.closest('[data-group]')?.dataset.group === 'What is offered'),
   'the "offer dev features" switch has a group of its own and starts off');
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
dest = m.reset_state(d)
print(json.dumps({"left": sorted(p.name for p in d.iterdir()), "moved": sorted(p.name for p in dest.iterdir()),
                  "old_kept": (d / '.reset-20260101-000000' / 'old').is_file(), "dest": dest.name}))
`], { encoding: 'utf8' });
  const r = JSON.parse(out);
  ok(r.moved.join() === 'logs,users.json' && r.left.length === 2 && r.left.every(n => n.startsWith('.reset-'))
     && r.old_kept && /^\.reset-\d{8}-\d{6}$/.test(r.dest),
     `the reset moves everything into a dated directory beside it and leaves earlier resets alone (${JSON.stringify(r)})`);
}
const groups = await page.$$eval('.settingstab [data-group]', gs => gs.map(g => g.dataset.group));
ok(groups.join('|') === 'What is offered|Debugging|Reset',
   `the tab's stored settings are the two groups that survived the question "does this need to exist", and the reset: nothing that should be a constant or a project's (${groups.join(', ')})`);
// Debug mode grants nothing by itself: it puts the grant on a node's row.
// Off by default, because what it opens is root's on the machine.
ok(await page.$eval('.settingstab [data-set="debug_mode"]', e => !e.checked),
   'debug mode is off until somebody turns it on');
// The settings a developer of BuilderBot reaches for sit behind a Debug
// settings button in the same group, which is a real control only once
// debug mode is saved on: a draft tick is not debug mode.
ok(await page.$eval('.settingstab [data-debugshow]', b => b.disabled && /Debug mode on/.test(b.title)),
   'Debug settings is ghosted while debug mode is off, saying to turn it on first');
ok(await page.$eval('.settingstab [data-debugfold]', f => f.hidden
     && !!f.querySelector('[data-set="claude_shared_login"]')),
   '...and the shared-login switch is folded behind it, out of the way');
await post('/api/settings', { set: { debug_mode: true } });
await page.waitForFunction(() => !document.querySelector('.settingstab [data-debugshow]')?.disabled,
                           null, { timeout: 30000 });
ok(await page.$eval('.settingstab [data-debugfold]', f => f.hidden),
   'debug mode on: the button is live, and the fold stays shut until it is pressed');
await page.click('.settingstab [data-debugshow]');
await page.waitForFunction(() => document.querySelector('.settingstab [data-debugfold]')?.checkVisibility(),
                           null, { timeout: 8000 });
ok(await page.$eval('.settingstab [data-debugshow]', b => b.getAttribute('aria-expanded') === 'true'),
   'pressing it unfolds the debug settings');
ok(await page.$eval('.settingstab [data-set="claude_shared_login"]', e => e.type === 'checkbox'
     && !e.checked && e.closest('label') !== null),
   'the shared-login switch is a checkbox in its label, off by default');
ok(await page.$eval('.settingstab [data-group="Debugging"] .actbar .state', e => /now/.test(e.textContent)),
   'the section says a change takes now, since nothing here waits for a boot');

// ---- saving ----------------------------------------------------------------
await page.check('.settingstab [data-set="claude_shared_login"]');
await page.click('.settingstab [data-group="Debugging"] .setApply');
await page.waitForFunction(() => state?.settings?.settings?.claude_shared_login?.value === true, null, { timeout: 30000 });
ok(read().claude_shared_login === true,
   'Apply writes it under /config and the poll carries it');
await page.waitForFunction(() => !document.querySelector('.settingstab [data-debugfold] .pill'), null, { timeout: 30000 });
ok(true, '...and the field is then the owner: no default pill');
ok(await page.$eval('.settingstab [data-debugfold]', f => !f.hidden),
   '...and the fold is still open after the repaint the save caused');
const bad = await post('/api/settings', { set: { claude_shared_login: 'maybe' } });
ok(bad.status === 400, 'a value that is not the setting\'s shape is refused');
ok((await post('/api/settings', { set: { claude_channel: 'stable' } })).status === 400,
   '...and a key that stopped being a setting is refused too');
// Back off: this is a stored setting and nothing in the harness resets it
// between files, so leaving the refusal stood down would be this file
// changing what every file after it is testing.
await post('/api/settings', { set: { claude_shared_login: false, debug_mode: false } });

// ---- what the boot script reads ------------------------------------------------
const setting = (key, dflt) => execFileSync('bash', ['-c',
  `. ${JSON.stringify(join(HERE, '..', '..', 'lib', 'common.sh'))}; bb_setting ${key} ${JSON.stringify(dflt)}`],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
ok(setting('claude_shared_login', 'true') === 'false',
   'bb_setting hands a boot hook the saved value, a false as the word false so is_true reads it');
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
