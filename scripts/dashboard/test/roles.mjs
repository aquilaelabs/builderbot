// A walk through BuilderBot as each kind of person, on projects shared in
// each combination: the owner; an administrator with two projects and one
// with one; plain users with two, with one, and with none. Each signs in in
// a browser of their own, sees what they should and no more, opens every tab
// and every notebook view they can, changes the settings that are theirs, is
// refused the ones that are not, and meets the others' changes. Console
// errors and server errors are collected per person across the whole walk.
import { launch, newPage, ok, done, ready, sleep, refreshUntil, URL, DIR, member, splitPick } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

const HERE = new globalThis.URL('..', import.meta.url).pathname;
const usersPy = code => execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", ${JSON.stringify(join(HERE, 'users.py'))})
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' }).trim().split('\n').pop();
const make = (name, role, projects) => usersPy(`
d = u.load(); uid = u.mint_uid()
d["users"]["${name}"] = {"uid": uid, "role": "${role}", "projects": ${JSON.stringify(projects)},
    "prefs": {"full_name": "${name}", "email": "${name}@example.invalid", "welcome_seen": True,
              "image_seen": "abc1234def5678901234567890abcdef12345678"},
    "password": u.hash_password("pw-${name}-1"), "created": 0, "seen": 0}
u._save(d); print(uid)`);

const CAST = [
  { name: 'test', pw: 'test', role: 'owner', projects: ['*'] },
  { name: 'w.admin1', role: 'admin', projects: ['alpha', 'beta'] },
  { name: 'w.admin2', role: 'admin', projects: ['alpha'] },
  { name: 'w.user1', role: 'user', projects: ['alpha', 'beta'] },
  { name: 'w.user2', role: 'user', projects: ['alpha'] },
  { name: 'w.user3', role: 'user', projects: [] },
];
for (const p of CAST.filter(c => c.role !== 'owner')) { p.pw = `pw-${p.name}-1`; make(p.name, p.role, p.projects); }
// What a plain account did before R152 is a role now, given as an
// administrator would (lib.mjs member).
await member('w.user1', 'w.user2', 'w.user3');

const browser = await launch();
const pageFor = async (who) => {
  const auth = 'Basic ' + Buffer.from(`${who.name}:${who.pw}`).toString('base64');
  const page = await newPage(browser, { viewport: { width: 1280, height: 900 },
    httpCredentials: { username: who.name, password: who.pw }, extraHTTPHeaders: { Authorization: auth } });
  page.fivexx = [];
  page.on('response', r => { if (r.status() >= 500 && !r.url().includes('/term')) page.fivexx.push(`${r.status()} ${r.url().replace(/^https?:\/\/[^/]+/, '')}`); });
  await page.goto(URL); await ready(page); await sleep(800);
  return page;
};
// Through the context's own request API, with the person's credentials,
// rather than a fetch inside the page: a refusal probed on purpose is a 4xx
// the browser would log to the console, and the console is where this walk
// looks for what the dashboard itself got wrong.
const api = async (page, path, body) => {
  const base = URL.replace(/\/$/, '');
  const r = body === undefined ? await page.request.get(base + path)
                               : await page.request.post(base + path, { data: body });
  let j = {}; try { j = await r.json(); } catch { /* not JSON */ }
  return { status: r.status(), ...j };
};
const ALL = ['alpha', 'beta', 'delta', 'ep.silon', 'gamma', 'vendored-junk'];
const VIEWS = ['roadmap', 'bugs', 'briefing', 'tests', 'git', 'artifacts', 'analysis', 'docker'];
const ADMIN_TABS = { settings: 'openSettingsTab', users: 'openUsersTab', nodes: 'openNodesTab', jobs: 'openJobsTab',
                     docker: 'openDocker', toolchains: 'openToolchains', findings: 'openFindingsTab' };

for (const who of CAST) {
  const page = await pageFor(who);
  const tag = `[${who.name}]`;
  const isAdmin = who.role !== 'user';
  const st = await page.evaluate(() => ({ projects: (state.projects || []).map(p => p.name).sort(),
                                          admin: state.admin, can: state.can || {} }));
  // What they see. An administrator is shown every project and works on its
  // own list; a user sees exactly what was granted.
  const expect = isAdmin ? null : who.projects.slice().sort();
  ok(isAdmin ? ALL.every(p => st.projects.includes(p)) : JSON.stringify(st.projects) === JSON.stringify(expect),
     `${tag} sees ${isAdmin ? 'every project' : 'exactly the projects granted'} (${st.projects.join(', ') || 'none'})`);
  ok(st.admin === isAdmin && await page.evaluate(() => !!document.querySelector('#rail [data-rail="people"]')) === isAdmin,
     `${tag} People is ${isAdmin ? 'on the rail' : 'not on the rail'}, and state.admin agrees`);
  ok((st.can.terminal !== false) === isAdmin, `${tag} a shell is ${isAdmin ? 'offered' : 'not offered'}`);

  // Every notebook view of every project they work on.
  const mine = who.projects[0] === '*' ? ['alpha', 'beta'] : who.projects;
  for (const proj of mine) {
    for (const v of VIEWS) {
      await page.evaluate(([p, view]) => openNotebook(p, view), [proj, v]);
      await sleep(350);
    }
  }
  ok(true, `${tag} opened all ${VIEWS.length} notebook views of ${mine.length ? mine.join(' and ') : 'no project'}`);
  // A project not granted is not there for a user, by any door.
  if (!isAdmin) {
    const other = ALL.find(p => !who.projects.includes(p));
    const r = await api(page, `/api/roadmap?project=${other}`);
    ok(r.status === 400 && /not a project/.test(r.error || ''), `${tag} ${other}'s notebook answers "not a project", as if it did not exist (${r.status})`);
  }

  // The tabs: an administrator opens each. A user has no door to them (the
  // card that holds them is not drawn, checked above), so the walk does not
  // force one: the server's refusal of what they would fetch is the part
  // below that matters.
  if (isAdmin) for (const fn of Object.values(ADMIN_TABS)) {
    await page.evaluate(f => window[f](), fn);
    await sleep(500);
  }
  await page.evaluate(() => openProfileTab()); await sleep(500);
  ok(true, `${tag} opened Profile and ${isAdmin ? 'every administration tab' : 'what a user can reach'}`);

  // Settings that are theirs.
  const tz = 'Europe/Paris';
  await page.evaluate(() => toggleUiMenu(true));
  await page.waitForSelector('#uiMenu #uiTZ', { timeout: 15000 });
  await page.selectOption('#uiTZ', tz); await page.click('#uiTZApply');
  await page.evaluate(() => toggleUiMenu(false));
  ok(await page.evaluate(() => userTZ()) === tz, `${tag} sets this browser's time zone`);
  const prof = await api(page, '/api/profile', { action: 'save', profile: { full_name: `${who.name} renamed`, email: `${who.name}@example.invalid` } });
  ok(prof.status === 200 && !prof.error, `${tag} saves their own profile (${prof.status}${prof.error ? ': ' + prof.error : ''})`);
  if (mine.length) {
    const yours = await api(page, '/api/prefs', { project: mine[0], model: 'sonnet' });
    ok(yours.status === 200 && !yours.error, `${tag} sets their own model on ${mine[0]} (${yours.status}${yours.error ? ': ' + yours.error.slice(0, 50) : ''})`);
    const added = await api(page, '/api/roadmap', { project: mine[0], action: 'add', text: `walked by ${who.name}` });
    ok(added.status === 200 && !added.error, `${tag} adds to ${mine[0]}'s roadmap from the notebook (${added.status})`);
  }

  // Settings that are not theirs: refused, with a reason, and nothing moved.
  // A real change: the value flipped from what it is now.
  const was = !!(await api(page, '/api/settings')).settings?.offer_unvetted?.value;
  const ctl = await api(page, '/api/settings', { set: { offer_unvetted: !was } });
  if (who.role === 'owner' || isAdmin) {
    // Admin is built in with everything the owner may do since R152 (the
    // operator, 7 Oct), the debug settings included.
    ok(ctl.status === 200, `${tag} changes a controller setting (${ctl.status})`);
    await api(page, '/api/settings', { set: { offer_unvetted: was } });
  } else {
    ok(ctl.status === 403, `${tag} is refused the controller's settings (${ctl.status})`);
    for (const [path, body] of [['/api/users', { action: 'add', name: 'x.nope', password: 'nopenope1', role: 'user' }],
                                ['/api/lock', { name: mine[0] || 'alpha', locked: true }],
                                ['/api/prefs', { project: mine[0] || 'alpha', node: 'n_x' }],
                                ['/api/v1/jobs', { action: 'run', project: mine[0] || 'alpha', argv: ['true'] }],
                                // Writing a compose file and building from it is
                                // root-shaped power on the node. The page hid the
                                // buttons and the endpoint let anybody through.
                                ['/api/container', { action: 'create', name: 'x.nope',
                                                     compose: 'services:\n  a:\n    image: alpine\n' }],
                                ['/api/container', { action: 'save', name: 'x.nope', compose: '', env: '' }],
                                // Starting somebody else's container, and reading
                                // what it printed, are both an administrator's.
                                ['/api/dockerctl', { action: 'stop', container: 'someone-elses' }],
                                ['/api/dockerctl', { action: 'logs', container: 'someone-elses' }]]) {
      const r = await api(page, path, body);
      ok(r.status === 403 || r.status === 400, `${tag} is refused ${path} (${r.status}: ${(r.error || '').slice(0, 50)})`);
    }
  }

  ok(page.errors.length === 0, `${tag} no console errors through the whole walk${page.errors.length ? ': ' + page.errors.slice(0, 2).join(' | ') : ''}`);
  ok(page.fivexx.length === 0, `${tag} no server errors${page.fivexx.length ? ': ' + page.fivexx.slice(0, 3).join(', ') : ''}`);
  who.page = page;
}

// ---- meeting each other ----------------------------------------------------
// An administrator grants a project and the user sees it; what one person
// adds to a shared roadmap the others read; the project's own settings are
// one set for everybody, and each person's own are theirs alone.
{
  const [owner, admin1, , user1, user2, user3] = CAST;
  const g = await api(admin1.page, '/api/users', { action: 'projects', name: 'w.user3', projects: ['alpha'] });
  ok(g.status === 200 && !g.error, `an administrator grants w.user3 alpha (${g.status}${g.error ? ': ' + g.error : ''})`);
  await user3.page.reload(); await ready(user3.page);
  ok(await user3.page.evaluate(() => (state.projects || []).some(p => p.name === 'alpha')),
     '...and w.user3 sees alpha after a reload');
  const road = JSON.stringify(await api(user2.page, '/api/roadmap?project=alpha'));
  ok(['test', 'w.admin1', 'w.admin2', 'w.user1', 'w.user2'].every(n => road.includes(`walked by ${n}`)),
     'everybody on alpha reads the items the others added to its roadmap');
  // A project's color is each person's own (the operator, 18 Oct): the
  // owner's pick is the owner's, and nobody else's view wears it.
  const color = await api(owner.page, '/api/project-color', { name: 'alpha', color: 'teal' });
  ok(color.status === 200, `the owner gives alpha a color of their own (${color.status})`);
  // Waited for, not read after one refresh(): a poll already on its way when
  // it is called makes it queue another and return at once, so one call can
  // read the state from before the write. On a loaded box, the whole run, a
  // poll is on its way often enough that this read undefined (B238).
  const colorOf = () => (state.projects || []).find(p => p.name === 'alpha')?.color || '';
  await refreshUntil(owner.page, () => ((state.projects || []).find(p => p.name === 'alpha')?.color || '') === 'teal',
                     { timeout: 20000 }).catch(() => {});
  await user1.page.evaluate(() => refresh());
  const mine = await owner.page.evaluate(colorOf), theirs = await user1.page.evaluate(colorOf);
  ok(mine === 'teal' && theirs === '', `...which the owner sees and w.user1 does not (${mine} | ${theirs || 'none'})`);
  // The tabs it colors: a shell opened on a project is that project's as
  // much as its Claude session is (the operator, 18 Oct: the dock's boxes
  // too); the workspace's shell is nobody's.
  const tabsOf = await owner.page.evaluate(() => ['claude:alpha:1', 'sh:2:alpha', 'sh:1:', 'shell']
    .map(arg => tabProject({ kind: 'term', arg }) || '-').join(' '));
  ok(tabsOf === 'alpha alpha - -', `a Claude tab and a shell on alpha wear its color, the workspace's shell none (${tabsOf})`);
  // A shell is read by the directory its label names: the workspace's shell
  // cd'd into alpha reads "sh: alpha" and wears alpha's color.
  const moved = await owner.page.evaluate(() => {
    const was = state.sessions;
    state.sessions = [...(was || []), { name: sessionOf('shell'), cwd: '/workspace/alpha' }];
    const r = tabProject({ kind: 'term', arg: 'shell' }) || '-';
    state.sessions = was; return r; });
  ok(moved === 'alpha', `...and the workspace's shell, gone into alpha, wears alpha's (${moved})`);
  await Promise.all([owner, user1, user2].map(p => refreshUntil(p.page,
    () => ((state.projects || []).find(p => p.name === 'alpha')?.yours?.model || '') === 'sonnet',
    { timeout: 20000 }).catch(() => {})));
  const models = await Promise.all([owner, user1, user2].map(p => p.page.evaluate(() =>
    (state.projects || []).find(p => p.name === 'alpha')?.yours?.model || '')));
  ok(models.every(m => m === 'sonnet'), `each person's own model on alpha is their own setting (${models.join(', ')})`);
}

// ---- Accounts and roles Read alone (B34), and a plain account by link (B38)
// Read sees Users and Roles to read: every field dead, no Add, Save or
// Remove, and the reason said on the page; the Roles page is not refused.
// A plain account sent to either by link is told it may not, with no count
// and no Add.
{
  const [owner, , , , , user3] = CAST;
  const who = { name: 'w.acctread', pw: 'pw-w.acctread-1', role: 'user', projects: [] };
  make(who.name, 'user', []);
  const set = await api(owner.page, '/api/roles', { action: 'set', name: 'acct-reader', scope: 'global', perms: { accounts: 'read' } });
  const giv = await api(owner.page, '/api/roles', { action: 'assign', name: who.name, roles: ['acct-reader'], project_roles: {} });
  ok(set.status === 200 && giv.status === 200,
     `an Everywhere role with Accounts and roles Read is given to ${who.name} (${set.status}, ${giv.status}${giv.error ? ': ' + giv.error : ''})`);
  const page = await pageFor(who);
  {
    const rd = await api(page, '/api/roles');
    const mine = await api(owner.page, '/api/roles');
    ok(rd.status === 200 && rd.readonly === true,
       `...who reads /api/roles, to read (${rd.status}${rd.error ? ': ' + rd.error : ''}; holds ${JSON.stringify((mine.people || []).find(p => p.name === who.name)?.roles)})`);
  }
  await page.evaluate(() => openUsersTab());
  await page.waitForSelector('.userstab [data-upick="w.user1"]', { timeout: 15000 });
  await page.click('.userstab [data-upick="w.user1"]');
  await page.waitForSelector('.userstab #ueAccess .setrow', { timeout: 15000 }).catch(() => {});
  const u = await page.evaluate(() => ({
    add: !!document.querySelector('.userstab #uAddOpen'), save: !!document.querySelector('.userstab #ueSave'),
    remove: !!document.querySelector('.userstab #ueRemove'),
    live: [...document.querySelectorAll('.userstab .rdetail input, .userstab .rdetail select, .userstab .rdetail [data-rprojoff]')].filter(i => !i.disabled).length,
    why: document.querySelector('.userstab #ueWhyRo')?.textContent || '',
    access: document.querySelector('.userstab #ueAccess')?.textContent.replace(/\s+/g, ' ') || '' }));
  ok(!u.add && !u.save && !u.remove && u.live === 0 && /Read, not Write/.test(u.why) && !/not yours to give/.test(u.access),
     `Users with Read: no Add, Save or Remove, every field dead, the reason on the page, its roles shown (${JSON.stringify({ ...u, access: u.access.slice(0, 60) })})`);
  await page.evaluate(() => openRolesTab());
  await page.waitForSelector('.rolestab [data-rpick]', { timeout: 15000 }).catch(() => {});
  const r = await page.evaluate(() => ({ bad: document.querySelector('.rolestab .row.bad')?.textContent || '',
    save: !!document.querySelector('.rolestab #rolesSave'), add: !!document.querySelector('.rolestab #rolesNewOpen') }));
  ok(!r.bad && !r.save && !r.add, `...and the Roles page to read, not refused (${JSON.stringify(r)})`);
  ok(page.errors.length === 0, `[${who.name}] no console errors${page.errors.length ? ': ' + page.errors.slice(0, 2).join(' | ') : ''}`);

  // B35: the only roles on a project being other projects' owner roles, the
  // picker is not drawn empty: the line naming the Roles page is.
  const b35 = await owner.page.evaluate(() => {
    const was = [rolesData, rolesWho, rolesPeopleDraft];
    rolesData = { roles: { own_beta: { name: 'own_beta', scope: 'projects', project: 'beta', perms: {} } }, areas: [],
                  people: [{ name: 'x', role: 'user', roles: [], project_roles: { beta: ['own_beta'] } }],
                  projects: ['alpha', 'beta'], admin: true };
    rolesWho = ''; rolesPeopleDraft = null;
    const html = rolesAccessFields('x');
    [rolesData, rolesWho, rolesPeopleDraft] = was;
    return html;
  });
  ok(/No role on a project yet/.test(b35) && !/rolesAddOn/.test(b35),
     'with only another project\'s owner role, Add to project is not drawn dead: the way to a role is named (B35)');

  // B38: a plain account by link.
  await user3.page.evaluate(() => { usersList = null; usersErr = ''; openUsersTab(); });
  await user3.page.waitForSelector('.userstab .row.bad', { timeout: 15000 });
  const p = await user3.page.evaluate(() => ({ add: !!document.querySelector('.userstab #uAddOpen'),
    bar: document.querySelector('.pane .doc.on .docbar, .userstab')?.textContent || '',
    bad: document.querySelector('.userstab .row.bad')?.textContent || '' }));
  ok(!p.add && !/0 people/.test(p.bar) && !/Users page/.test(p.bad),
     `a plain account sent to Users by link is told why, with no count, no Add, and no pointer at the page it cannot use (${p.bad.trim().slice(0, 90)})`);

  // ...and to a project not theirs by link: not a notebook loading forever.
  const seen = await user3.page.evaluate(() => (state.projects || []).map(p => p.name));
  const notTheirs = ALL.find(n => !seen.includes(n)) || 'no-such-project';
  await user3.page.goto(URL.replace(/\/$/, '') + '/#/projects/' + notTheirs);
  await ready(user3.page); await sleep(3000);
  const nb = await user3.page.evaluate(p => ({ project: p, hash: location.hash, kind: tabOf(panes[0])?.kind || '',
    arg: tabOf(panes[0])?.arg || '', loading: !!document.querySelector('#pane0 .loading, #pane0 .skboot'),
    mem: !!document.querySelector(`#pane0 [data-project="${p}"]`) }), notTheirs);
  ok(!nb.loading && !nb.mem && nb.arg !== notTheirs,
     `a plain account sent to a project not theirs by link is not left on a notebook loading forever (${JSON.stringify(nb)})`);
}

await done(browser);
