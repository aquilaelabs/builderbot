// The Roles tab (R152, the operator, 7 Oct): two sections with a Save and
// a Revert each. Roles: owner and admin built in and read only, a role
// added, its scope and Read and Write per area, Write needing Read. People:
// an account's Global roles, its projects and the roles it holds on each.
// Honored by the gate where they hold and nowhere else; a project's owner
// gives roles on the projects they own and nothing Global.
import { launch, newPage, ok, done, ready, sleep, URL, DIR, openSection } from './lib.mjs';
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
const page = await newPage(browser, { viewport: { width: 1280, height: 1400 } });
await page.goto(URL);
await ready(page);
const openSect = async id => {
  if (!await page.$eval(`.rolestab [data-sect="${id}"]`, d => d.open)) await page.click(`.rolestab [data-sect="${id}"] > summary`);
};

// From a clean slate: a kept fixture may hold these from a run before.
for (const n of ['deployer', 'installer']) await api('/api/roles', { action: 'remove', name: n });
await page.click('#bRoles');
await page.waitForSelector('.rolestab #rolesWho', { timeout: 15000 });
await openSect('roles:roles');
const names = await page.$$eval('#rolesPick option', os => os.map(o => o.textContent.trim()));
ok(names.includes('owner (built in)') && names.includes('admin (built in)') && !names.some(n => /^user\b/.test(n)),
   `owner and admin are built in, and there is no user role (${names.join(', ')})`);
await page.selectOption('#rolesPick', 'admin');
ok(await page.$eval('.rolestab', t => !t.querySelector('#rolesSave') && t.querySelectorAll('[data-rread]:checked').length === 13
     && [...t.querySelectorAll('[data-rread]')].every(c => c.disabled)),
   '...a built-in one reads as every area, with nothing to change and no Save');

// A role added: its scope, Read and Write per area, Write only with Read.
await page.fill('#rolesNewName', 'deployer');
await page.click('#rolesAdd');
await page.waitForSelector('[data-rread="releases"]');
ok(await page.$eval('[data-rwrite="releases"]', c => c.disabled) && await page.$eval('[data-rread="nodes"]', c => c.disabled),
   'a new role on the user\'s projects: Write waits for Read, and the global areas are off');
await page.check('[data-rread="projects"]');
await page.check('[data-rread="releases"]');
await page.check('[data-rwrite="releases"]');
await page.fill('#rolesNote', 'moves versions');
await page.click('#rolesRevert');
ok(!(await page.$$eval('#rolesPick option', os => os.map(o => o.textContent))).some(t => /deployer/.test(t)),
   'Revert drops a role that was never saved');
await page.fill('#rolesNewName', 'deployer');
await page.click('#rolesAdd');
await page.waitForSelector('[data-rread="releases"]');
await page.check('[data-rread="projects"]');
await page.check('[data-rread="releases"]');
await page.check('[data-rwrite="releases"]');
await page.fill('#rolesNote', 'moves versions');
await page.click('#rolesSave');
await page.waitForFunction(() => rolesData?.roles?.deployer, null, { timeout: 15000 });
const dep = (await api('/api/roles')).body.roles.deployer;
ok(dep && dep.scope === 'projects' && dep.note === 'moves versions'
   && JSON.stringify(dep.perms) === JSON.stringify({ projects: 'read', releases: 'write' }),
   `...and Save keeps its scope, areas and note (${JSON.stringify(dep)})`);
ok((await api('/api/roles', { action: 'set', name: 'admin', scope: 'global', perms: {} })).body.error,
   'a built-in role refuses to be changed');
ok(/project areas only/.test((await api('/api/roles', { action: 'set', name: 'bad', scope: 'projects', perms: { nodes: 'read' } })).body.error || ''),
   '...and a role on the user\'s projects refuses a global area');

// Given on one project: a new account starts with nothing, then holds the
// role on alpha alone.
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'dep', '--role', 'user'],
  { input: 'deppass11\ndeppass11\n', encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const depAuth = asUser('dep', 'deppass11');
{
  const none = await api('/api/version', { project: 'alpha', action: 'nothing-much' }, depAuth);
  ok(none.status === 403 || none.status === 400, `a new account holds no role and may do nothing (${none.status} ${none.body.error || ''})`);
}
await page.evaluate(() => loadRoles());
await page.waitForFunction(() => (rolesData?.people || []).some(p => p.name === 'dep'), null, { timeout: 10000 });
await openSect('roles:people');
await page.selectOption('#rolesWho', 'dep');
await page.check('[data-ron="alpha"]');
await page.check('[data-ron="beta"]');
await page.check('[data-rproject="alpha"] [data-rprole="deployer"]');
await page.click('#rolesPeopleSave');
await page.waitForFunction(() => rolesData?.people?.find(p => p.name === 'dep')?.project_roles?.alpha, null, { timeout: 10000 });
const onAlpha = await api('/api/version', { project: 'alpha', action: 'nothing-much' }, depAuth);
const onBeta = await api('/api/version', { project: 'beta', action: 'nothing-much' }, depAuth);
ok(onAlpha.status !== 403 && onBeta.status === 403,
   `People gives the role on alpha and the gate holds it there alone (alpha ${onAlpha.status}, beta ${onBeta.status})`);
ok((await api('/api/rename', { name: 'alpha', to: 'alpha2' }, depAuth)).status === 403,
   '...and nothing the role did not say');

// A project's owner who is not an administrator: alpha's owner gives roles
// on alpha and nothing else, and no Global role (R152 (c)).
await api('/api/members', { action: 'set', project: 'alpha', owner: 'dep' });
const asOwner = await api('/api/roles', undefined, depAuth);
ok(asOwner.status === 200 && JSON.stringify(asOwner.body.projects) === JSON.stringify(['alpha']) && !asOwner.body.admin,
   `alpha's owner opens the tab with alpha alone (${asOwner.status} ${JSON.stringify(asOwner.body.projects)})`);
ok(Object.keys(asOwner.body.roles).includes('alpha_owner') && !Object.keys(asOwner.body.roles).includes('admin'),
   '...offered the roles on a project, its owner role among them, and no Global one');
const gl = await api('/api/roles', { action: 'assign', name: 'dep', roles: ['admin'] }, depAuth);
ok(gl.status === 403, `...and refused a Global role (${gl.status})`);
const elsewhere = await api('/api/roles', { action: 'assign', name: 'dep', project_roles: { beta: ['deployer'] } }, depAuth);
ok(elsewhere.status === 200 && !(elsewhere.body.project_roles || {}).beta,
   `...and beta, not theirs, is left as it was (${JSON.stringify(elsewhere.body.project_roles)})`);
const ownerRole = (await api('/api/roles')).body.people.find(p => p.name === 'dep').project_roles.alpha || [];
ok(ownerRole.includes('alpha_owner'), `the account that owns alpha holds alpha_owner on it (${ownerRole.join(', ')})`);
await api('/api/members', { action: 'set', project: 'alpha', owner: 'test' });

// Removed, the role goes with it.
await api('/api/roles', { action: 'remove', name: 'deployer' });
ok((await api('/api/version', { project: 'alpha', action: 'nothing-much' }, depAuth)).status === 403,
   'the role removed, what it gave goes with it');
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
