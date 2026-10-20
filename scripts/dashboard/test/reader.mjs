// An account whose only role on a project gives Projects Read, found
// walking the dev pair on 20 Oct: every control on the project's page that
// would change it is dead, with the server's own reason written under it in
// red, rather than live and refused at the press (B86).
// Also: Start Claude says why it is grey (B88); New project and the trash
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
const bar = await page.evaluate(() => ({ np: document.querySelector('.doc.on #bNewProjTab')?.disabled,
  bin: document.querySelector('.doc.on #bTrashTab')?.disabled,
  why: [...document.querySelectorAll('.doc.on #pjWhy .deadwhy')].map(e => e.textContent) }));
ok(bar.np === true && bar.bin === true, 'New project and the trash are dead for an account without them');
ok(bar.why.some(t => /making a project needs New projects Write/.test(t)) && bar.why.some(t => /deleting a project/.test(t)),
   `...each with the server's reason under the bar, in red (${bar.why.join(' | ')})`);
const red = await page.$eval('.doc.on #pjWhy .deadwhy', e => getComputedStyle(e).color);
const bad = await page.evaluate(() => { const d = document.createElement('i'); d.style.color = 'var(--bad)'; document.body.append(d);
  const c = getComputedStyle(d).color; d.remove(); return c; });
ok(red === bad, `...the bad color (${red})`);
// The bin, opened all the same: a refusal is said, not read as empty.
await page.evaluate(() => openTrash());
await page.waitForFunction(() => !document.querySelector('#tList .sk-row') && document.querySelector('#tList').textContent.trim(), null, { timeout: 15000 });
const bin = await page.$eval('#tList', e => e.textContent.trim());
ok(!/nothing deleted/.test(bin) && /deleting a project/.test(bin), `the bin, asked anyway, says the refusal and not 'nothing deleted' (${bin.slice(0, 80)})`);
await page.evaluate(() => { $("tmodal").hidden = true; });
const card = await page.evaluate(() => {
  const c = document.querySelector('.pgrid .pcard[data-row="alpha"]');
  return { dead: c.querySelector('[data-c]')?.disabled, note: [...c.querySelectorAll('.pnote.bad')].map(n => n.textContent).join(' | '),
           del: !!c.querySelector('[data-del]'), mark: c.querySelector('.lockmark')?.textContent.trim() };
});
ok(card.dead && /no Projects Write on alpha/.test(card.note), `Start Claude is dead and the card says why under it, in red (${card.note})`);
ok(!card.del && card.mark === 'read-only', `the card offers no Delete, and its name is marked read-only (${card.mark})`);

// ---- the project's page (B86) ---------------------------------------------
const view = async (v, sel) => {
  await page.evaluate(([p, w]) => openNotebook(p, w), ['alpha', v]);
  await nbShown(page);
  if (sel) await page.waitForSelector(`.pane .nb ${sel}`, { state: 'attached', timeout: 20000 });
  await sleep(400);
};
await view('briefing', '#rlAdd');
await page.waitForSelector('.pane .nb #memAdd button', { state: 'attached', timeout: 20000 });
const head = await page.evaluate(() => {
  const h = document.querySelector('.pane .phead [data-c]'), n = document.querySelector('.pane .pnote.bad');
  return { dead: h?.disabled, note: n?.textContent || '' };
});
ok(head.dead && /no Projects Write/.test(head.note), `the page's header: Start Claude dead, why under it (${head.note})`);
const ov = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb'), add = nb.querySelector('#rlAdd');
  return { add: add.disabled, why: add.closest('.addbar')?.nextElementSibling?.textContent || '',
           switches: [...nb.querySelectorAll('.grHere')].map(c => c.disabled),
           edits: nb.querySelectorAll('.rulerow .rlEdit, .rulerow .rlRm').length,
           mem: nb.querySelector('#memAdd button')?.disabled, memWhy: nb.querySelector('#memAdd .deadwhy')?.textContent || '' };
});
ok(ov.add && /no Projects Write on alpha/.test(ov.why), `Overview: Add a rule dead, why under it (${ov.why})`);
ok(ov.switches.every(Boolean) && ov.edits === 0, `...every global rule's switch dead (${ov.switches.length}) and no Edit or Remove on a rule`);
ok(ov.mem === true && /no Projects Write/.test(ov.memWhy), `...Write a memory dead, why under it (${ov.memWhy})`);

await view('roadmap', '#roadmapShow');
const rm = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { add: nb.querySelector('#roadmapShow').disabled, why: nb.querySelector('#roadmapWhy')?.checkVisibility() ? nb.querySelector('#roadmapWhy').textContent : '',
           order: nb.querySelector('#roadmapOrder').hidden,
           acts: nb.querySelectorAll('#roadmapList .rowacts, #roadmapList .addstep, #roadmapList .go').length };
});
ok(rm.add && /no Projects Write/.test(rm.why) && rm.order, `Plan: Add to roadmap dead with why under it, Reorder gone (${rm.why})`);
ok(rm.acts === 0, `...and no row carries Done, Shelve, Reword, Drop, a step or a send (${rm.acts})`);

await view('bugs', '#bugAdd button');
const bg = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { add: nb.querySelector('#bugAdd button').disabled, why: nb.querySelector('#bugAdd .deadwhy')?.textContent || '',
           acts: nb.querySelectorAll('#bugList .macts').length };
});
ok(bg.add && /no Projects Write/.test(bg.why) && bg.acts === 0, `Bugs: Report a bug dead with why, and no verbs on a report (${bg.why})`);

await view('git', '#gitWhy');
await page.waitForFunction(() => document.querySelector('.pane .nb #gitWhy')?.checkVisibility()
  || /not a git|no repository/.test(document.querySelector('.pane .nb #gitHint')?.textContent || ''), null, { timeout: 20000 });
const gt = await page.evaluate(() => {
  const nb = document.querySelector('.pane .nb');
  return { why: nb.querySelector('#gitWhy')?.checkVisibility() ? nb.querySelector('#gitWhy').textContent : '',
           net: [...nb.querySelectorAll('#gitNet [data-gitact]')].filter(b => b.checkVisibility()).map(b => b.disabled),
           verbs: nb.querySelectorAll('#gitBody [data-gitmerge], #gitBody [data-gitaskbranch], #gitBody [data-gitswitch], #gitBody [data-gitdelete], #gitBody #gitCommit').length,
           hint: nb.querySelector('#gitHint')?.textContent || '' };
});
if (/not a git|no repository/.test(gt.hint)) ok(true, 'Code > Git: alpha has no repository here, nothing to change');
else {
  ok(/no Projects Write/.test(gt.why) && gt.net.every(Boolean), `Code > Git: Fetch and Push dead, why under them (${gt.why})`);
  ok(gt.verbs === 0, `...and no branch carries Merge, Ask Claude, Switch or Delete (${gt.verbs})`);
}

// Settings: Delete project dead with why, and nothing asked to be refused (B89).
const before = asked.length;
await view('settings', '#rnDelete');
await sleep(1500);
const st = await page.evaluate(() => ({ del: document.querySelector('#rnDelete')?.disabled,
  why: document.querySelector('#rnDeleteWhy')?.checkVisibility() ? document.querySelector('#rnDeleteWhy').textContent : '' }));
ok(st.del === true && /deleting a project needs Project settings Write on alpha/.test(st.why), `Settings: Delete project dead, why under it (${st.why})`);
const refusedAsks = asked.slice(before).filter(u => /\/api\/(snapshots|project-sessions)/.test(u));
ok(refusedAsks.length === 0, `...and Snapshots and Running sessions are not asked for (${refusedAsks.join(', ') || 'none'})`);
await splitPick(page, 'snapshots');
const snapSaid = await page.evaluate(() => document.querySelector('#rnSnapRows')?.textContent || '');
ok(/Project settings Write on alpha/.test(snapSaid), `...Snapshots says why, from the row (${snapSaid.slice(0, 80)})`);

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
