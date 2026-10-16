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
await page.evaluate(() => openRolesTab());
await page.waitForSelector('.rolestab [data-rwho]', { timeout: 15000 });
await openSect('roles:roles');
// The roles a list beside the one picked (R255 step 9): each row its name,
// its kind and who holds it.
const names = await page.$$eval('.rolestab [data-rpick]', rs => rs.map(r => `${r.querySelector('.name').textContent.trim()} (${r.querySelector('.pill').textContent.trim()})`));
ok(names.includes("BuilderBot's owner (built in)") && names.includes('Administrator (built in)') && !names.some(n => /^user\b/i.test(n)),
   `owner and admin are built in, and there is no user role (${names.join(', ')})`);
await page.click('.rolestab [data-rpick="admin"]');
ok(await page.$eval('.rolestab', t => !t.querySelector('#rolesSave') && t.querySelectorAll('[data-rread]:checked').length === 15
     && [...t.querySelectorAll('[data-rread]')].every(c => c.disabled)),
   '...a built-in one reads as every area, with nothing to change and no Save');

// A role added: its scope, Read and Write per area, Write only with Read.
await page.fill('#rolesNewName', 'deployer');
await page.click('#rolesAdd');
await page.waitForSelector('[data-rread="releases"]');
ok(await page.$eval('[data-rwrite="releases"]', c => c.disabled) && await page.$eval('[data-rread="nodes"]', c => c.disabled),
   'a new role on a project: Write waits for Read, and the global areas are off');
ok(/only an Everywhere role holds them/.test(await page.$eval('#rolesWhyOff', e => e.textContent)),
   '...saying why, once, above them');
await page.check('[data-rread="projects"]');
await page.check('[data-rread="releases"]');
await page.check('[data-rwrite="releases"]');
await page.fill('#rolesNote', 'moves versions');
await page.click('#rolesRevert');
ok(!(await page.$$eval('.rolestab .rrow', rs => rs.map(r => r.textContent))).some(t => /deployer/.test(t)),
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
await page.click('.rolestab [data-rwho="dep"]');
// Holding a role on a project is being on it (R155): no separate box, and
// a project role is not offered among the Everywhere ones.
ok(!(await page.$$('[data-ron]')).length && !(await page.$$('[data-rglobal="deployer"]')).length,
   'a project role is given on a project alone, and there is no separate "on it" box');
// Only the projects an account is on are listed; Add to project puts it on
// one with a role there (R255 step 9).
ok(!(await page.$$('.rolestab [data-rproject]')).length && await page.$eval('#rolesAddProj', s => [...s.options].some(o => o.value === 'alpha')),
   'an account on no project lists none, and Add to project offers them');
await page.selectOption('#rolesAddProj', 'alpha');
await page.selectOption('#rolesAddRole', 'deployer');
await page.click('#rolesAddOn');
await page.waitForSelector('.rolestab [data-rproject="alpha"] [data-rprole="deployer"]:checked');
await page.waitForFunction(() => document.querySelector('[data-rcan="releases"] [data-rcanp="alpha"]')?.textContent === 'Write'
  && document.querySelector('[data-rcan="projects"] [data-rcanp="alpha"]')?.textContent === 'Read');
ok(true, 'What dep can do says it in its grid, alpha writing Releases and reading Projects, before Save');
await page.click('#rolesPeopleSave');
await page.waitForFunction(() => rolesData?.people?.find(p => p.name === 'dep')?.project_roles?.alpha, null, { timeout: 10000 });
const onAlpha = await api('/api/version', { project: 'alpha', action: 'nothing-much' }, depAuth);
const onBeta = await api('/api/version', { project: 'beta', action: 'nothing-much' }, depAuth);
// beta is no project of dep's at all now (R155: on a project is holding a
// role there), so it reads as absent rather than refused.
ok(onAlpha.status !== 403 && (onBeta.status === 403 || (onBeta.status === 400 && /not a project/.test(onBeta.body.error || ''))),
   `People gives the role on alpha and the gate holds it there alone (alpha ${onAlpha.status}, beta ${onBeta.status})`);
{
  const p = (await api('/api/roles')).body.people.find(x => x.name === 'dep');
  ok(JSON.stringify(p.projects) === JSON.stringify(['alpha']), `...and being on alpha follows the role (${JSON.stringify(p.projects)})`);
  const glob = await api('/api/roles', { action: 'assign', name: 'dep', roles: ['deployer'] });
  ok(glob.status === 400 && /on a project: give it on the project/.test(glob.body.error || ''),
     `a project role given among the Everywhere ones is refused by name (${glob.body.error})`);
  const kind = await api('/api/roles', { action: 'set', name: 'deployer', scope: 'global', perms: { projects: 'read' } });
  ok(kind.status === 400 && /dep holds deployer/.test(kind.body.error || ''),
     `...and a held role keeps its kind (${kind.body.error})`);
}
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

// Making projects on one node (the operator, 7 Oct): New projects is its
// own area, and a Global role may hold its node areas on named nodes.
{
  const sandbox = (await api('/api/v1/nodes')).body.nodes.find(n => n.kind !== 'local');
  await page.evaluate(() => loadRoles());
  await openSect('roles:roles');
  await page.fill('#rolesNewName', 'creator');
  await page.click('#rolesAdd');
  await page.waitForSelector('#rolesScope');
  await page.selectOption('#rolesScope', 'global');
  await page.waitForSelector(`[data-rnode="${sandbox.id}"]`);
  await page.check('[data-rread="newprojects"]');
  await page.check('[data-rwrite="newprojects"]');
  await page.check(`[data-rnode="${sandbox.id}"]`);
  await page.click('#rolesSave');
  await page.waitForFunction(() => rolesData?.roles?.creator, null, { timeout: 15000 });
  const cr = (await api('/api/roles')).body.roles.creator;
  ok(cr.scope === 'global' && cr.perms.newprojects === 'write' && JSON.stringify(cr.nodes) === JSON.stringify([sandbox.id]),
     `a Global role saves New projects on the node ticked (${JSON.stringify(cr)})`);
  await api('/api/roles', { action: 'assign', name: 'dep', roles: ['creator'] });
  const elsewhere = await api('/api/create', { name: 'nowhere-made', node: 'n_nowhere' }, depAuth);
  const nowhere = await api('/api/create', { name: 'nowhere-made' }, depAuth);
  ok(elsewhere.status === 403 && /goes on/.test(elsewhere.body.error || '') && nowhere.status === 403,
     `a project on another node, or on none, is refused by name (${elsewhere.status} ${elsewhere.body.error || ''})`);
  const here = await api('/api/create', { name: '', node: sandbox.id }, depAuth);
  ok(here.status !== 403, `...and on the node the role names it passes the gate (${here.status} ${here.body.error || ''})`);
  await api('/api/roles', { action: 'assign', name: 'dep', roles: [] });
  await api('/api/roles', { action: 'remove', name: 'creator' });
}

// An area without Read is refused and hidden (R152 step 3): a role that
// reads Toolchains alone sees that tab and none of the others.
{
  await api('/api/roles', { action: 'set', name: 'tc-viewer', scope: 'global', perms: { toolchains: 'read' } });
  await api('/api/roles', { action: 'assign', name: 'dep', roles: ['tc-viewer'] });
  const tc = await api('/api/toolchains', undefined, depAuth);
  const nd = await api('/api/v1/nodes', undefined, depAuth);
  const us = await api('/api/users', undefined, depAuth);
  ok(tc.status === 200 && us.status === 403 && /no Accounts and roles Read/.test(us.body.error || ''),
     `the server answers the area it may read and refuses one it may not by name (toolchains ${tc.status}, users ${us.status}: ${us.body.error || ''})`);
  ok(nd.status === 200 && (nd.body.nodes || []).length === 0,
     `...and without Nodes Read the nodes answer only for its own projects, here none (${(nd.body.nodes || []).length})`);
  const st = (await api('/api/status', undefined, depAuth)).body.areas || {};
  ok(st.toolchains === 'read' && st.nodes === '' && st.jobs === '', `the status carries each area's level (${JSON.stringify(st)})`);
  const dp = await newPage(browser, { viewport: { width: 1280, height: 900 },
    httpCredentials: { username: 'dep', password: 'deppass11' },
    extraHTTPHeaders: { Authorization: 'Basic ' + Buffer.from('dep:deppass11').toString('base64') } });
  await dp.goto(URL); await ready(dp);
  await dp.waitForFunction(() => state?.areas, null, { timeout: 15000 });
  const shown = await dp.evaluate(() => ({ ...Object.fromEntries(['toolchains', 'jobs', 'nodes', 'settings', 'users', 'roles']
    .map(k => [k, railAllows(k)])), people: !!document.querySelector('#rail [data-rail="people"]'),
    jobsRail: !!document.querySelector('#rail [data-rail="jobs"]') }));
  ok(shown.toolchains && !shown.jobs && !shown.nodes && !shown.settings && !shown.users && !shown.roles && !shown.people && !shown.jobsRail,
     `its rail offers Toolchains and leaves out the pages it may not read (${JSON.stringify(shown)})`);
  // A group opens on its first page this account may open (the operator,
  // 16 Oct: Settings did nothing for an account the Controller page is not
  // drawn for, though Profile is in it).
  await dp.click('#rail [data-rail="settings"]');
  await dp.waitForFunction(() => tabOf(panes[0])?.kind === 'profile', null, { timeout: 10000 });
  ok(await dp.evaluate(() => location.hash === '#/settings/profile'
       && [...document.querySelectorAll('#pane0 > .bar .subnav button')].map(b => b.textContent).join() === 'Profile'),
     'Settings opens on Profile for an account that may not read the controller, its sub-nav Profile alone');
  await dp.close();
  await api('/api/roles', { action: 'assign', name: 'dep', roles: [] });
  await api('/api/roles', { action: 'remove', name: 'tc-viewer' });
}

// Removed, the role goes with it.
await api('/api/roles', { action: 'remove', name: 'deployer' });
ok((await api('/api/version', { project: 'alpha', action: 'nothing-much' }, depAuth)).status === 403,
   'the role removed, what it gave goes with it');
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
