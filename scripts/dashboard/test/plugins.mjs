// Claude Code plugins (plugins.py): what each person installed with /plugin,
// seen from the dashboard. `bb login --list` reads each account's plugins off
// the node's disk, the agent carries its rows up on the heartbeat, and the
// controller shows a person theirs on the Profile tab and every account's in
// bb diag. Then the two recipes that give the language-server plugins what
// they run, since a session cannot npm install -g into the store.
import { URL, launch, newPage, ok, done, ready, sleep, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const base = URL.replace(/\/$/, '');
const HERE = new globalThis.URL('..', import.meta.url).pathname;
const BB = join(HERE, '..', 'bb');
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
                'Content-Type': 'application/json' };
const call = async (path, body, headers = ADMIN) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  const t = await r.text();
  let j = {}; try { j = JSON.parse(t); } catch { /* 204 */ }
  return { status: r.status, ...j };
};
const bearer = t => ({ Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' });
const owner = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;

// ---- bb login --list reads them off the disk --------------------------------
// Staged the way Claude Code leaves them (captured from a real install on 19
// Sep): installed_plugins.json and the account's enabledPlugins.
const homes = join(DIR, 'pluginhomes');
const stage = (uid, installed, enabled) => {
  const c = join(homes, uid, '.claude');
  mkdirSync(join(c, 'plugins'), { recursive: true });
  if (installed) writeFileSync(join(c, 'plugins', 'installed_plugins.json'), JSON.stringify({ version: 2, plugins: installed }));
  if (enabled) writeFileSync(join(c, 'settings.json'), JSON.stringify({ enabledPlugins: enabled }));
};
const inst = (scope, extra = {}) => [{ scope, installPath: '/x', version: '1.0.0',
  installedAt: '2026-09-19T00:17:53.368Z', gitCommitSha: 'c447c32', ...extra }];
stage(owner, {
  'code-simplifier@claude-plugins-official': inst('user'),
  'pyright-lsp@claude-plugins-official': inst('user'),
  'feature-dev@claude-plugins-official': inst('project', { projectPath: '/workspace/alpha' }),
}, { 'code-simplifier@claude-plugins-official': true, 'pyright-lsp@claude-plugins-official': false });
stage('u_0000beef', null, null);
const listed = JSON.parse(execFileSync('bash', [BB, 'login', '--list'],
  { encoding: 'utf8', env: { ...process.env, BUILDER_USERS: homes } }));
const mine = listed.find(r => r.uid === owner), none = listed.find(r => r.uid === 'u_0000beef');
const byId = Object.fromEntries((mine?.plugins || []).map(p => [p.id.split('@')[0], p]));
ok(mine && byId['code-simplifier']?.enabled === true && byId['pyright-lsp']?.enabled === false
   && byId['feature-dev']?.scope === 'project' && byId['feature-dev']?.project === 'alpha'
   && byId['feature-dev']?.enabled === null,
   `bb login --list names each account's plugins, on or off, and a project's by name (${Object.keys(byId).join(', ')})`);
ok(!JSON.stringify(mine).includes('/x') && !JSON.stringify(mine).includes('c447c32'),
   '...and not where they live on the disk or what commit they came from');
ok(none && none.plugins === null, 'an account that never installed one says none');

// ---- up the heartbeat, onto the Profile tab ---------------------------------
const shipped = (await call('/api/v1/nodes')).agent || {};
const minted = await call('/api/v1/nodes', { action: 'enroll', name: 'plugbox' });
const en = await call('/api/v1/agent/enroll', { census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux' },
  version: shipped.version, digest: shipped.digest, user: 'bb' }, bearer(minted.token));
const beat = logins => call('/api/v1/agent/work', { sample: { cpu_pct: 1, logins }, running: 0, wait: 0 }, bearer(en.token));
await beat([{ ...mine, email: '' }]);
let prof = await call('/api/profile');
const here = (prof.plugins || []).find(n => n.name === 'plugbox');
ok(here && here.plugins.length === 3 && here.plugins.some(p => p.id.startsWith('pyright-lsp') && p.enabled === false),
   `the heartbeat puts them on the account's profile, under the node's name (${here?.plugins.length} on ${here?.name})`);
await beat([{ uid: owner, email: '' }]);
prof = await call('/api/profile');
ok((prof.plugins || []).some(n => n.name === 'plugbox'),
   'an agent that does not send the field changes nothing');
const store = () => JSON.parse(readFileSync(`${DIR}/state/claude-plugins.json`, 'utf8'));
const at = store()[owner][minted.id].at;
await sleep(1100);
await beat([{ ...mine, email: '' }]);
ok(store()[owner][minted.id].at === at, 'the same list again is not a write: a heartbeat must not cost one');

// The Profile tab says it, and says where they are changed.
{
  const browser = await launch();
  const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
  await page.goto(URL); await ready(page);
  await page.evaluate(() => { profile = null; openProfileTab(); loadProfile(); });
  // The page itself (its Save), not its template, which names the section
  // too while the profile is on its way.
  await page.waitForFunction(() => document.querySelector('.doc.on #pfSave') && /Claude plugins/.test(document.querySelector('.doc.on')?.textContent || ''), null, { timeout: 15000 });
  const text = await page.evaluate(() => [...document.querySelectorAll('.doc.on h4')]
    .find(h => h.textContent === 'Claude plugins')?.nextElementSibling?.textContent.replace(/\s+/g, ' ').trim() || '');
  ok(/On plugbox: code-simplifier 1\.0\.0, feature-dev 1\.0\.0 \(alpha\), pyright-lsp 1\.0\.0 off/.test(text)
     && /\/plugin in a Claude session/.test(text),
     `Profile lists them per node, a project's with its name and one switched off marked so (${text.slice(0, 110)})`);
  ok(page.errors.length === 0, `no console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);

  // Taken off the node: gone from the profile, and the empty state says how
  // to add one.
  await beat([{ uid: owner, email: '', plugins: null }]);
  await page.evaluate(() => loadProfile()); await sleep(500);
  const empty = await page.evaluate(() => [...document.querySelectorAll('.doc.on h4')]
    .find(h => h.textContent === 'Claude plugins')?.nextElementSibling?.textContent.replace(/\s+/g, ' ').trim() || '');
  ok(/None installed/.test(empty) || !/plugbox/.test(empty),
     `a node that says the account has none takes them off (${empty.slice(0, 60)})`);
  await browser.close();
}

// ---- bb diag, for an administrator ----------------------------------------
await beat([{ ...mine, email: '' }]);
{
  const r = await call('/api/diag', { sections: ['plugins'] });
  const row = (r.plugins || []).find(x => x.node === 'plugbox');
  ok(row && row.account === 'test' && row.plugins.includes('pyright-lsp@claude-plugins-official 1.0.0 (off)')
     && row.plugins.includes('feature-dev@claude-plugins-official 1.0.0 (project alpha)'),
     `bb diag names every account's plugins on every node (${row ? row.plugins.length : 'none'})`);
  const out = execFileSync('bash', [BB, 'diag', 'plugins'], { encoding: 'utf8',
    env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', BB_CONTROLLER: base, DASHBOARD_AUTH: 'test:test' } });
  ok(/== plugins ==/.test(out) && /test on plugbox: .*code-simplifier/.test(out),
     `...and prints them readably (${out.trim().split('\n')[1]?.slice(0, 70)})`);
}

// ---- what the language-server plugins run -----------------------------------
{
  const cat = JSON.parse(readFileSync(join(HERE, '..', '..', 'config', 'toolchains.json'), 'utf8')).toolchains;
  const ls = cat.find(p => p.name === 'language-servers'), kt = cat.find(p => p.name === 'kotlin-lsp');
  const run = ls?.source?.run?.join(' ') || '';
  ok(ls && ls.layout.bin.includes('node_modules/.bin') && ls.requires.includes('node')
     && /pyright@/.test(run) && /typescript-language-server@/.test(run) && /typescript@5/.test(run),
     'the language-servers recipe puts pyright and typescript-language-server on PATH from the store, beside node');
  ok(kt && kt.layout.tool === 'bin/kotlin-lsp' && /ln -sfn \.\.\/server\/bin\/intellij-server/.test(kt.source.run.join(' ')),
     'kotlin-lsp is JetBrains\' server under the name the plugin runs');
  // The version is read out of GitHub's answer for the latest release; a
  // copy of that answer's shape, since the harness has no network.
  const sed = kt.source.run[2].match(/sed -n '([^']+)'/)[1];
  const answer = join(DIR, 'kls-release.json');
  writeFileSync(answer, '{\n  "url": "x",\n  "tag_name": "kotlin-lsp/v263.4702.0",\n  "name": "v263.4702.0"\n}\n');
  const v = execFileSync('sed', ['-n', sed, answer], { encoding: 'utf8' }).trim();
  ok(v === '263.4702.0', `...whose version is read out of GitHub's latest-release answer (${v})`);
  const plan = execFileSync('bash', [BB, 'toolchains', 'plan', 'language-servers'], { encoding: 'utf8' });
  ok(/kind\s+command/.test(plan) && /npm install --prefix/.test(plan), 'bb toolchains plan shows what an install would run');
}

await done();
