// The Roles tab (R137): the built-in roles listed and not editable, a role
// of your own made on the tab and given grants there, carried by an
// account from the Users tab's dialog, and honored by the gate: the account
// may do what the role says where it says, and nothing it did not.
import { launch, newPage, ok, done, ready, sleep, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const base = URL.replace(/\/$/, '');
const asUser = (u, pw) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${pw}`).toString('base64'),
                             'Content-Type': 'application/json' });
const owner = asUser('test', 'test');
const api = async (path, body, headers = owner) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// From a clean slate: a kept fixture may hold the role from a run before.
await api('/api/roles', { action: 'remove', name: 'deployer' });
// The tab, from the Administration card's button.
await page.click('#bRoles');
await page.waitForSelector('.rolestab .sect', { timeout: 15000 });
const builtins = await page.$$eval('.rolestab .sect', ss => ss.map(s => ({
  title: s.querySelector('summary .t')?.textContent.trim(), status: s.querySelector('summary .sst')?.textContent.trim() })));
ok(['owner', 'admin', 'user'].every(n => builtins.some(b => b.title === n && b.status === 'built in')),
   `the three built-in roles are listed as built in (${builtins.map(b => b.title).join(', ')})`);
ok(await page.$eval('.rolestab [data-sect="roles:r-admin"]', s => !s.querySelector('[data-rcap]')
     && /everything/.test(s.textContent) && !!s.querySelector('[data-rcopy]')),
   '...each read as what it grants, with Copy and nothing to edit');

// A role of your own: made from the New role band, then its grants ticked
// and saved in its own fold.
await page.fill('#rNewName', 'deployer');
await page.click('#rNew');
// The fold arrives with the redraw that follows the save; settled before
// anything in it is pressed, or a tick lands on a node the redraw replaces.
await page.waitForFunction(() => rolesList?.deployer && document.querySelector('.rolestab [data-sect="roles:r-deployer"]'), null, { timeout: 15000 });
await sleep(500);
ok(true, 'New role makes one, listed with the rest');
await page.evaluate(() => { document.querySelector('.rolestab [data-sect="roles:r-deployer"]').open = true; });
await page.click('.rolestab [data-sect="roles:r-deployer"] [data-rcap="version"]');
await page.selectOption('.rolestab [data-sect="roles:r-deployer"] [data-rscope="version"]', 'named');
await page.click('.rolestab [data-sect="roles:r-deployer"] .rgrant[data-cap="version"] [data-rproj="alpha"]');
await page.fill('.rolestab [data-sect="roles:r-deployer"] [data-rnote]', 'moves versions on alpha');
await page.click('.rolestab [data-sect="roles:r-deployer"] [data-rsave]');
await page.waitForFunction(() => (rolesList?.deployer?.grants || []).some(g => g.cap === 'version'), null, { timeout: 15000 });
const dep = (await api('/api/roles')).body.roles.deployer;
ok(dep && dep.note === 'moves versions on alpha' && dep.grants.some(g => g.cap === 'version' && Array.isArray(g.scope) && g.scope.includes('alpha')),
   `...and Save keeps its grants and note (${JSON.stringify(dep?.grants)})`);
const builtinEdit = await api('/api/roles', { action: 'set', name: 'admin', grants: [{ cap: 'read', scope: 'all' }] });
ok(builtinEdit.status !== 200 && /built in/.test(builtinEdit.body.error || ''),
   `a built-in role refuses to be changed (${builtinEdit.body.error})`);

// Carried by an account: a user on alpha and beta, given the role.
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'dep', '--role', 'user'],
  { input: 'deppass11\ndeppass11\n', encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
await api('/api/users', { action: 'projects', name: 'dep', projects: ['alpha', 'beta'] });
const given = await api('/api/users', { action: 'edit', name: 'dep', roles: ['deployer'] });
const rec = (await api('/api/users')).body.users.find(u => u.name === 'dep');
ok(given.status === 200 && rec && rec.roles.includes('user') && rec.roles.includes('deployer'),
   `an account carries its role and the one it was given (${JSON.stringify(rec?.roles)})`);

// Honored by the gate: moving a version is version's, which a plain user
// may not; the deployer may on alpha, where the grant names it, and still
// not on beta, where it does not. (An unknown action past the gate is a
// 400, not a 403: the gate is what is measured.)
const depAuth = asUser('dep', 'deppass11');
const onAlpha = await api('/api/version', { project: 'alpha', action: 'nothing-much' }, depAuth);
const onBeta = await api('/api/version', { project: 'beta', action: 'nothing-much' }, depAuth);
ok(onAlpha.status !== 403 && onBeta.status === 403,
   `the gate honors the grant where it names the project and nowhere else (alpha ${onAlpha.status}, beta ${onBeta.status})`);
const stillUser = await api('/api/rename', { name: 'alpha', to: 'alpha2' }, depAuth);
ok(stillUser.status === 403, `...and nothing the role did not say (rename ${stillUser.status})`);

// A capability on a node is scoped over nodes (step 3): installing a
// toolchain where the role names the node, and nowhere else; and the CI
// runner tab is a grant the user role lacks, which the page reads from can.
{
  const sandbox = (await api('/api/v1/nodes')).body.nodes.find(n => n.name === 'sandbox') || (await api('/api/v1/nodes')).body.nodes[0];
  await api('/api/roles', { action: 'set', name: 'installer', grants: [{ cap: 'toolchains-write', scope: [sandbox.id] }] });
  await api('/api/users', { action: 'edit', name: 'dep', roles: ['installer'] });
  const here = await api('/api/toolchains', { action: 'install', node: sandbox.id, names: ['nothing:such'] }, depAuth);
  const there = await api('/api/toolchains', { action: 'install', node: 'n_nowhere', names: ['nothing:such'] }, depAuth);
  ok(here.status !== 403 && there.status === 403,
     `a toolchain install is allowed on the node the role names and refused elsewhere (${here.status}, ${there.status})`);
  const can = (await api('/api/status', undefined, depAuth)).body.can || {};
  const ownerCan = (await api('/api/status')).body.can || {};
  ok(can.runner === false && ownerCan.runner === true && can.jobs === false,
     `the page is told what the account may: no CI runner and no job runs for a user, both for the owner (${JSON.stringify(can)})`);
  await api('/api/roles', { action: 'remove', name: 'installer' });
}

// Removed, the grant goes with it.
await api('/api/roles', { action: 'remove', name: 'deployer' });
const gone = await api('/api/version', { project: 'alpha', action: 'nothing-much' }, depAuth);
ok(gone.status === 403, `the role removed, the account is a user again (${gone.status})`);
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
