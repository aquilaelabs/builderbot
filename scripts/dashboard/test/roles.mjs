// A walk through BuilderBot as each kind of person, on projects shared in
// each combination: the owner; an administrator with two projects and one
// with one; plain users with two, with one, and with none. Each signs in in
// a browser of their own, sees what they should and no more, opens every tab
// and every notebook view they can, changes the settings that are theirs, is
// refused the ones that are not, and meets the others' changes. Console
// errors and server errors are collected per person across the whole walk.
import { launch, newPage, ok, done, ready, sleep, refreshUntil, URL, DIR } from './lib.mjs';
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
                     docker: 'openDocker', toolchains: 'openToolchains', findings: 'openFindingsTab', phone: 'openPhoneTab' };

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
  ok(st.admin === isAdmin && !!await page.$eval('#cardAdmin', c => !c.hidden) === isAdmin,
     `${tag} the Administration card is ${isAdmin ? 'there' : 'not there'}, and state.admin agrees`);
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
  await page.evaluate(() => openProfileTab());
  await page.waitForSelector('#pfTZ', { timeout: 15000 });
  await page.selectOption('#pfTZ', tz); await page.click('#pfTZApply');
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
  const ctl = await api(page, '/api/settings', { set: { offer_unvetted: true } });
  if (isAdmin) {
    ok(ctl.status === 200, `${tag} changes a controller setting (${ctl.status})`);
    await api(page, '/api/settings', { set: { offer_unvetted: false } });
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
  const colour = await api(owner.page, '/api/prefs', { project: 'alpha', color: 'teal' });
  ok(colour.status === 200, `the owner sets alpha's colour (${colour.status})`);
  // Waited for, not read after one refresh(): a poll already on its way when
  // it is called makes it queue another and return at once, so one call can
  // read the state from before the write. On a loaded box, the whole run, a
  // poll is on its way often enough that this read undefined (B238).
  const colourOf = () => (state.projects || []).find(p => p.name === 'alpha')?.prefs?.color;
  await refreshUntil(user1.page, () => (state.projects || []).find(p => p.name === 'alpha')?.prefs?.color === 'teal',
                     { timeout: 20000 }).catch(() => {});
  const seen = await user1.page.evaluate(colourOf);
  ok(seen === 'teal', `...which is alpha's for everybody (${seen})`);
  await Promise.all([owner, user1, user2].map(p => refreshUntil(p.page,
    () => ((state.projects || []).find(p => p.name === 'alpha')?.yours?.model || '') === 'sonnet',
    { timeout: 20000 }).catch(() => {})));
  const models = await Promise.all([owner, user1, user2].map(p => p.page.evaluate(() =>
    (state.projects || []).find(p => p.name === 'alpha')?.yours?.model || '')));
  ok(models.every(m => m === 'sonnet'), `each person's own model on alpha is their own setting (${models.join(', ')})`);
}

await done(browser);
