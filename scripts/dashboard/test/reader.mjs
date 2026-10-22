// An account whose only role on a project gives Projects Read, found
// walking the dev pair on 20 Oct: every control on the project's page that
// would change it is dead, with the server's own reason written under it in
// red, rather than live and refused at the press (B86).
// Also: Start Claude says why it is dead (B88); New project and the trash
// are dead for an account without them, and the trash never reads a
// refusal as an empty bin (B87); the settings page does not ask for what
// the role cannot read (B89); the Profile's Password says what is wrong
// under the field it is about (B90).
import { launch, newPage, ok, done, ready, sleep, URL, DIR, nbShown, splitPick } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { join } from 'node:path';

const HERE = new globalThis.URL('..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const owner = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const api = async (path, body, headers = owner) => {
  const r = await fetch(base + path, body === undefined ? { headers } : { method: 'POST', headers, body: JSON.stringify(body) });
  let j = {}; try { j = await r.json(); } catch { /* not JSON */ }
  return { status: r.status, ...j };
};
// Made in the store as roles.mjs makes its cast: the welcome read, a commit
// author set, so nothing but the role stands between it and the page.
const NAME = 'rd.reader', PW = 'pw-rd-reader-1';
execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", ${JSON.stringify(join(HERE, 'users.py'))})
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
d = u.load()
d["users"]["${NAME}"] = {"uid": u.mint_uid(), "role": "user", "projects": [],
    "prefs": {"full_name": "Rd Reader", "email": "rd@example.invalid", "welcome_seen": True,
              "image_seen": "abc1234def5678901234567890abcdef12345678"},
    "password": u.hash_password("${PW}"), "created": 0, "seen": 0}
u._save(d)`], { encoding: 'utf8' });
const made = await api('/api/roles', { action: 'set', name: 'rdread', scope: 'projects', perms: { projects: 'read' }, note: 'reads a project' });
const given = await api('/api/roles', { action: 'assign', name: NAME, project_roles: { alpha: ['rdread'] } });
ok(made.status === 200 && given.status === 200, `a role giving Projects Read alone, held on alpha (${made.status} ${given.status} ${given.error || ''})`);

const browser = await launch();
const auth = 'Basic ' + Buffer.from(`${NAME}:${PW}`).toString('base64');
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 },
  httpCredentials: { username: NAME, password: PW }, extraHTTPHeaders: { Authorization: auth } });
const asked = [];
page.on('request', r => asked.push(r.url().replace(/^https?:\/\/[^/]+/, '')));
await page.goto(URL); await ready(page); await sleep(800);

const row = await page.evaluate(() => (state.projects || []).find(p => p.name === 'alpha') || {});
ok(/no Projects Write on alpha/.test(row.write_why || '') && !!row.trash_why && !!row.settings_why,
   `the row carries why alpha is not this account's to change, delete or set up (${row.write_why})`);

// ---- the Projects page (B86, B87, B88) -----------------------------------
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.pgrid .pcard[data-row="alpha"]', { timeout: 15000 });
// What a role does not give is not drawn, and nothing says why (the
// operator, 21 Oct: a role somebody lacks is not advertised to them).
const bar = await page.evaluate(() => ({ np: document.querySelector('.doc.on #bNewProjTab')?.checkVisibility(),
  bin: document.querySelector('.doc.on #bTrashTab')?.checkVisibility(),
  why: [...document.querySelectorAll('.doc.on .deadwhy, .doc.on .notice.bad')].map(e => e.textContent) }));
ok(bar.np === false && bar.bin === false, 'New project and the trash are not drawn for an account without them');
ok(!bar.why.length, `...and nothing on the page says why (${bar.why.join(' | ')})`);
// The bin, opened all the same: a refusal is said, not read as empty.
await page.evaluate(() => openTrash());
await page.waitForFunction(() => !document.querySelector('#tList .sk-row') && document.querySelector('#tList').textContent.trim(), null, { timeout: 15000 });
const bin = await page.$eval('#tList', e => e.textContent.trim());
ok(!/nothing deleted/.test(bin) && /deleting a project/.test(bin), `the bin, asked anyway, says the refusal and not 'nothing deleted' (${bin.slice(0, 80)})`);
await page.evaluate(() => { $("tmodal").hidden = true; });
const card = await page.evaluate(() => {
  const c = document.querySelector('.pgrid .pcard[data-row="alpha"]');
  return { start: !!c.querySelector('[data-c]'), note: [...c.querySelectorAll('.pnote')].map(n => n.textContent).join(' | '),
           del: !!c.querySelector('[data-del]'), mark: c.querySelector('.lockmark')?.textContent.trim() };
});
ok(!card.start && !card.note, `the card has no Start Claude and no line saying why (${card.note})`);
ok(!card.del && card.mark === 'read-only', `the card offers no Delete, and its name is marked read-only (${card.mark})`);

// ---- the project's page (B86) ---------------------------------------------
const view = async (v, sel) => {
  await page.evaluate(([p, w]) => openNotebook(p, w), ['alpha', v]);
  await nbShown(page);
  if (sel) await page.waitForSelector(`.pane .nb ${sel}`, { state: 'attached', timeout: 20000 });
  await sleep(400);
};
await view('briefing', '#rlList');
await page.waitForSelector('.pane .nb #memAdd', { state: 'attached', timeout: 20000 });
const head = await page.evaluate(() => {
  const h = document.querySelector('.pane .phead [data-c]'), n = document.querySelector('.pane .pnote');
  return { start: !!h, note: n?.textContent || '' };
});
ok(!head.start && !head.note, `the page's header: no Start Claude, nothing said (${head.note})`);
const ov = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb'), add = nb.querySelector('#rlAdd');
  return { add: !!add, why: nb.querySelectorAll('.deadwhy').length,
           switches: [...nb.querySelectorAll('.grHere')].map(c => c.disabled),
           edits: nb.querySelectorAll('.rulerow .rlEdit, .rulerow .rlRm').length,
           mem: !!nb.querySelector('#memAdd button') };
});
ok(!ov.add && !ov.why, `Overview: no Add a rule, and no reason drawn (${ov.why})`);
ok(ov.switches.every(Boolean) && ov.edits === 0, `...every global rule's switch dead (${ov.switches.length}) and no Edit or Remove on a rule`);
ok(!ov.mem, '...and no Write a memory');

await view('roadmap', '#roadmapShow');
const rm = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { add: nb.querySelector('#roadmapShow').checkVisibility(), why: nb.querySelectorAll('.deadwhy').length,
           order: nb.querySelector('#roadmapOrder').hidden,
           acts: nb.querySelectorAll('#roadmapList .rowacts, #roadmapList .addstep, #roadmapList .go').length };
});
ok(!rm.add && !rm.why && rm.order, `Plan: no Add to roadmap and no Reorder, nothing said (${rm.why})`);
ok(rm.acts === 0, `...and no row carries Done, Shelve, Reword, Drop, a step or a send (${rm.acts})`);

await view('bugs', '#bugNew');
const bg = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { add: nb.querySelector('#bugNew').checkVisibility() || !!nb.querySelector('#bugAdd .bugform'), why: nb.querySelectorAll('.deadwhy').length,
           acts: nb.querySelectorAll('#bugList .macts').length };
});
ok(!bg.add && !bg.why && bg.acts === 0, `Bugs: no Report a bug, no verbs on a report, nothing said (${bg.why})`);

await view('git', '#gitHint');
await page.waitForFunction(() => document.querySelector('.pane .nb #gitNet [data-gitact="fetch"]')?.hidden
  || /not a git|no repository/.test(document.querySelector('.pane .nb #gitHint')?.textContent || ''), null, { timeout: 20000 });
const gt = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { why: nb.querySelectorAll('.deadwhy').length,
           net: [...nb.querySelectorAll('#gitNet [data-gitact]')].filter(b => b.checkVisibility()).length,
           verbs: nb.querySelectorAll('#gitBody [data-gitmerge], #gitBody [data-gitaskbranch], #gitBody [data-gitswitch], #gitBody [data-gitdelete], #gitBody #gitCommit').length,
           hint: nb.querySelector('#gitHint')?.textContent || '' };
});
if (/not a git|no repository/.test(gt.hint)) ok(true, 'Code > Git: alpha has no repository here, nothing to change');
else {
  ok(!gt.why && gt.net === 0, `Code > Git: no Fetch, Push or Pull, nothing said (${gt.net})`);
  ok(gt.verbs === 0, `...and no branch carries Merge, Ask Claude, Switch or Delete (${gt.verbs})`);
}

// Settings: no Delete project, and nothing asked to be refused (B89).
const before = asked.length;
await view('settings', '#rnDelete');
await sleep(1500);
const st = await page.evaluate(() => ({ del: document.querySelector('#rnDelete')?.hidden,
  snap: !document.querySelector('#rnSnapField')?.hidden, sess: !document.querySelector('#rnSessField')?.hidden,
  why: document.querySelectorAll('.deadwhy').length }));
ok(st.del === true && !st.why, `Settings: no Delete project, nothing said (${st.why})`);
const refusedAsks = asked.slice(before).filter(u => /\/api\/(snapshots|project-sessions)/.test(u));
ok(refusedAsks.length === 0, `...and Snapshots and Running sessions are not asked for (${refusedAsks.join(', ') || 'none'})`);
ok(!st.snap && !st.sess, '...nor drawn');

// ---- Tests, Wiki, Design, Artifacts and Pending (B101) --------------------
// What each has to show, made by the owner: a test run ingested, a wiki
// page, a build in dist/.
{
  const { writeFileSync, mkdirSync } = await import('node:fs');
  writeFileSync(`${DIR}/ws/alpha/.bb-test-run.log`,
    '[dashboard-test] == shape.mjs ==\nPASS  [+0.1s] a row a reader opens\n1 passed, 0 failed in 0.1s\n');
  execFileSync(join(HERE, '..', 'bb'), ['tests', 'ingest', '.bb-test-run.log'],
    { cwd: `${DIR}/ws/alpha`, env: { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '',
      DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'alpha' } });
  mkdirSync(`${DIR}/ws/alpha/dist`, { recursive: true });
  writeFileSync(`${DIR}/ws/alpha/dist/rd-app-0.1.0.apk`, 'not really an apk');
  const wk = await api('/api/wiki', { project: 'alpha', action: 'save', name: 'Home', text: 'a page a reader reads', base: '' });
  ok(wk.status === 200, `the owner writes a wiki page for the reader to read (${wk.status} ${wk.error || ''})`);
}
await view('tests', '#tstList .tst > summary');
await page.click('.pane .nb #tstList .tst > summary');
await page.waitForSelector('.pane .nb #tstList .tst[open] .bfield', { state: 'attached', timeout: 15000 });
const ts = await page.evaluate(() => {
  const b = document.querySelector('.pane .nb #tstList .tst[open] .tstEdit');
  return { edit: !!b, why: document.querySelectorAll('.pane .nb .deadwhy').length };
});
ok(!ts.edit && !ts.why, `Tests: a test has no Edit, nothing said (${ts.why})`);

await view('wiki', '#wkBody');
await page.waitForSelector('.pane .nb #wkBody .wktabs', { state: 'attached', timeout: 20000 });
const wk = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { add: !!nb.querySelector('#wkNew')?.checkVisibility(), why: nb.querySelectorAll('.deadwhy').length,
           verbs: nb.querySelectorAll('#wkEditTab, #wkRename, #wkRm').length };
});
ok(!wk.add && !wk.why && wk.verbs === 0,
   `Wiki: no New page, and no Edit, Rename or Remove on a page, nothing said (${wk.why})`);

await view('design', '#dsWrite');
await page.waitForFunction(() => document.querySelector('.pane .nb #dsBody [data-sect]'), null, { timeout: 20000 });
const ds = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  const live = [...nb.querySelectorAll('#dsBody input, #dsBody select:not([data-dspick]), #dsBody textarea, #dsBody button')]
    .filter(e => !e.disabled).map(e => e.id || e.className || e.tagName);
  return { write: nb.querySelector('#dsWrite').checkVisibility(), why: nb.querySelectorAll('.deadwhy').length, live };
});
ok(!ds.write && !ds.why && !ds.live.length,
   `Design: no Write the file, every field read-only, nothing said (${ds.why}; live: ${ds.live.join(', ')})`);

// The fixture's alpha has no commit, so no version to move: the version a
// project with one is read as, from the server's own shape, and drawn.
// Routed before the view opens, which reads it.
await page.route('**/api/version?project=alpha*', r => r.fulfill({ contentType: 'application/json', body: JSON.stringify({
  project: 'alpha', target: '0.1.0', tag: 'v0.1.0', released: false, prev: '', ordinal: 3,
  next: { patch: '0.1.1', minor: '0.2.0', major: '1.0.0' }, forms: { semver: '0.1.0-dev.3' },
  since: { commits: 3 }, policy: 'ask', policies: ['ask'], versions: [], candidates: [] }) }));
await view('artifacts', '#artList');
await page.waitForFunction(() => /rd-app-0\.1\.0\.apk/.test(document.querySelector('.pane .nb #artList')?.textContent || '')
  && document.querySelector('.pane .nb #verBox [data-sect]'), null, { timeout: 20000 });
const ar = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { verbs: nb.querySelectorAll('#artList [data-artinstall], #artList [data-artpush], #artList [data-artpin], #artList [data-artunnamed], #artList [data-artsign]').length,
           dl: nb.querySelectorAll('#artList a[download]').length,
           why: nb.querySelectorAll('#artList .deadwhy').length };
});
ok(ar.verbs === 0 && ar.dl > 0 && !ar.why,
   `Artifacts: a build carries Download and no Install, pin, Remove or Sign, nothing said (${ar.why})`);
await page.waitForSelector('.pane .nb #verBox [data-verbump]', { state: 'attached', timeout: 15000 });
Object.assign(ar, await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { ver: [...nb.querySelectorAll('#verBox [data-verbump], #verBox [data-verrelease]')].map(b => b.checkVisibility()),
           policy: nb.querySelector('#verPolicy')?.disabled, verWhy: nb.querySelectorAll('#verBox .deadwhy').length,
           verSaid: (nb.querySelector('#verBox')?.textContent || '').replace(/\s+/g, ' ').slice(0, 120) };
}));
await page.unroute('**/api/version?project=alpha*');
ok(ar.ver.length > 0 && !ar.ver.some(Boolean) && ar.policy !== false && !ar.verWhy,
   `...and no bump or Release on the version, its Claude access read-only, nothing said (${ar.verSaid})`);
const cl = await api('/api/changelog', { project: 'alpha', component: '', groups: [] }, { ...owner, Authorization: auth });
ok(cl.status === 403 && /no Projects Write/.test(cl.error || ''), `...and the changelog's Save is refused it at the server too (${cl.status} ${cl.error || ''})`);

// Pending: what a session left for approval, drawn into the review dialog.
await page.evaluate(() => { pendFor = 'alpha'; $("pendModal").hidden = false;
  drawPendingModal({ pending: [{ id: 1, kind: 'roadmap', verb: 'add', summary: 'something a session added', args: {} }], gate: {} }); });
const pd = await page.evaluate(() => ({ ok: $("pendApprove").hidden, no: $("pendDeny").hidden,
  why: $("pendModal").querySelectorAll('.deadwhy').length }));
ok(pd.ok && pd.no && !pd.why, `Pending: no Approve or Deny, nothing said (${pd.why})`);
await page.evaluate(() => { $("pendModal").hidden = true; pendFor = null; });

// What is left of the reason under a dead control is a feature the install
// switched off (FEATURES_OFF): in the warning's yellow, never the failure's
// red (the operator, 21 Oct).
const tone = await page.evaluate(() => {
  const c = v => { const d = document.createElement('i'); d.style.color = `var(${v})`; document.body.append(d);
    const x = getComputedStyle(d).color; d.remove(); return x; };
  const box = document.createElement('div'); box.innerHTML = deadWhy('switched off here'); document.body.append(box);
  const got = getComputedStyle(box.firstElementChild).color; box.remove();
  return { got, warn: c('--warn'), bad: c('--bad') };
});
ok(tone.got === tone.warn && tone.got !== tone.bad, `a switched-off feature's reason is yellow, not red (${tone.got})`);

// ---- the Profile's Password (B90) -----------------------------------------
await page.evaluate(() => openProfileTab());
await page.waitForSelector('#pfPasswd', { state: 'attached', timeout: 15000 });
await splitPick(page, 'password');
const pwState = () => page.evaluate(() => ({ live: !document.querySelector('#pfPasswd').disabled,
  cur: document.querySelector('#pfCurWhy').hidden ? '' : document.querySelector('#pfCurWhy').textContent,
  nw: document.querySelector('#pfNewWhy').hidden ? '' : document.querySelector('#pfNewWhy').textContent,
  nw2: document.querySelector('#pfNew2Why').hidden ? '' : document.querySelector('#pfNew2Why').textContent }));
ok(!(await pwState()).live, 'Change password is dead with nothing typed');
await page.fill('#pfCur', PW);
await page.fill('#pfNew', 'short');
let s = await pwState();
ok(!s.live && /shorter than 8/.test(s.nw), `a new one under 8 says so under it, the button dead (${s.nw})`);
await page.fill('#pfNew', 'a-new-pass-1');
await page.fill('#pfNew2', 'a-new-pass-2');
s = await pwState();
ok(!s.live && /two new passwords differ/.test(s.nw2), `two that differ say so under the second, the button dead (${s.nw2})`);
await page.fill('#pfNew2', 'a-new-pass-1');
await page.fill('#pfCur', 'not-the-password');
s = await pwState();
ok(s.live && !s.nw && !s.nw2, 'the same twice, 8 or more, and a current one typed: live, nothing said');
const toasts = await page.evaluate(() => document.querySelectorAll('.tst').length);
await page.click('#pfPasswd');
await page.waitForFunction(() => !document.querySelector('#pfCurWhy').hidden, null, { timeout: 15000 });
s = await pwState();
ok(/current password is not right/.test(s.cur) && await page.evaluate(() => document.querySelectorAll('.tst').length) === toasts,
   `a wrong current one is said under Current password, not in a toast (${s.cur})`);
await page.fill('#pfCur', PW);
s = await pwState();
ok(!s.cur, '...and goes as the field is typed into again');

// The bin opened by hand above, and the wrong current password, are the
// two refusals asked for on purpose.
const errs = page.errors.filter(e => !/\/api\/(trash|profile)\b/.test(e));
ok(errs.length === 0, `no console errors through the walk${errs.length ? ': ' + errs.slice(0, 3).join(' | ') : ''}`);
await api('/api/roles', { action: 'remove', name: 'rdread' });
await done(browser);
