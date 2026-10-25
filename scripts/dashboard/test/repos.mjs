// Projects first (R138): a project made with a name alone through
// /api/repos, repositories moved into it and back out, a repository made
// into it with the create dialog, renamed, refused where it should be, and
// deleted only once it is empty. What goes by the project: a project that
// read one of its repositories reads the project, and so every repository
// in it; a dial set through one repository is the project's. The card's
// front and back, the trash naming the project, and Put back asking where
// when the project is gone.
import { ok, done, DIR, URL, launch, newPage, ready } from './lib.mjs';
import { readFileSync } from 'node:fs';

const base = URL.replace(/\/$/, '');
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const post = async (path, body) => {
  const r = await fetch(base + path, { method: 'POST', headers: ADMIN, body: JSON.stringify(body) });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};
const status = async () => (await fetch(base + '/api/status', { headers: ADMIN })).json();
const prefsFile = () => { try { return JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects || {}; } catch { return {}; } };
const reposFile = () => { try { return JSON.parse(readFileSync(`${DIR}/state/project-repos.json`, 'utf8')).projects || {}; } catch { return {}; } };

// Every repository is in a project of its own to begin with.
const st0 = await status();
const home = name => Object.entries(st0.repos || {}).find(([, r]) => r.members.includes(name))?.[0];
ok(['alpha', 'beta', 'gamma', 'ep.silon'].every(home),
   `every repository is in a project from the start (${JSON.stringify(Object.fromEntries(Object.entries(st0.repos || {}).map(([k, r]) => [k, r.members])))})`);
const gammaWas = home('gamma'), epWas = home('ep.silon');

// beta reads ep.silon to begin with.
const was = await post('/api/prefs', { project: 'beta', reads: ['ep.silon'] });
ok(was.status === 200, `beta reads ep.silon to begin with (${was.status} ${was.error || ''})`);

// Refused: no name, an action that is none of them.
const blank = await post('/api/repos', { action: 'create', name: ' ?! ' });
ok(blank.status === 400 && /letter or digit/.test(blank.error || ''), `a project's name needs a letter or digit (${blank.error})`);
const bad = await post('/api/repos', { action: 'shuffle' });
ok(bad.status === 400 && /create, rename, move or delete/.test(bad.error || ''), `an action that is none of them is refused (${bad.error})`);

// Made with a name alone, spaces and punctuation kept, and nothing in it.
const m = await post('/api/repos', { action: 'create', name: 'Shop & Co' });
ok(m.status === 200 && m.ok && m.name === 'Shop & Co' && /^P\d+$/.test(m.id || '') && JSON.stringify(reposFile()[m.key]?.members) === '[]',
   `a project is made with its name as typed and no repository in it (${JSON.stringify(m)})`);
const key = m.key;
const twin = await post('/api/repos', { action: 'create', name: 'shop & co' });
ok(twin.status === 400 && /already a project's name/.test(twin.error || ''), `a second project of that name is refused (${twin.error})`);

// gamma and then ep.silon moved into it. A repository's git host link is its
// own (its remote, token, deploy key and forge): a move leaves it as it was.
const gitOf = async n => { const p = ((await status()).projects || []).find(x => x.name === n) || {};
  return JSON.stringify(['git', 'linked', 'forge', 'forge_host', 'has_token', 'push', 'push_how'].map(k => p[k] ?? null)); };
const gitBefore = await gitOf('gamma');
const g = await post('/api/repos', { action: 'move', name: 'gamma', to: key });
ok(await gitOf('gamma') === gitBefore, `a moved repository keeps its git host link as it was (${gitBefore})`);
ok(g.status === 200 && g.was === gammaWas && g.project === 'Shop & Co', `gamma moves into Shop & Co (${JSON.stringify(g)})`);
const epGit = await gitOf('ep.silon');
const e = await post('/api/repos', { action: 'move', name: 'ep.silon', to: key });
ok(await gitOf('ep.silon') === epGit, `...ep.silon's too, a repository with a branch (${epGit})`);
ok(e.status === 200 && JSON.stringify(reposFile()[key]?.members) === '["gamma","ep.silon"]',
   `...and ep.silon, after it (${JSON.stringify(reposFile()[key])})`);
// A read goes by the project (the operator, 24 Oct): beta read the project
// ep.silon was in, and still reads that one, not the repository it moved.
const betaReads = () => prefsFile()[home('beta')]?.reads;     // a project's setting, on its key
ok(JSON.stringify(betaReads()) === JSON.stringify([epWas]), `beta still reads the project it was granted (${JSON.stringify(betaReads())})`);
const again = await post('/api/repos', { action: 'move', name: 'gamma', to: key });
ok(again.status === 400 && /already in Shop & Co/.test(again.error || ''), `a repository is not moved where it is (${again.error})`);
// delta is locked in the fixture: it does not move, saying why.
const held = await post('/api/repos', { action: 'move', name: 'delta', to: key });
ok(held.status === 403 && /lock/i.test(held.error || ''), `a locked project's repository does not move (${held.status} ${held.error})`);

// A project with a repository in it is not deleted.
const full = await post('/api/repos', { action: 'delete', key });
ok(full.status === 409 && /move or delete its repositories first/.test(full.error || ''), `a project with repositories in it is not deleted (${full.error})`);

// A repository made into it, with the dialog's own request.
const made = await post('/api/create', { name: 'shopweb', mode: 'init', project: key });
ok(made.status === 200 && JSON.stringify(reposFile()[key]?.members) === '["gamma","ep.silon","shopweb"]',
   `Add repository makes one inside the project (${made.status} ${made.error || ''} ${JSON.stringify(reposFile()[key])})`);

const browser = await launch();
{
  const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
  await page.goto(URL + '#/projects');
  await ready(page);
  await page.evaluate(() => refresh());
  const card = `.pcard[data-pkey="${key}"]`;
  await page.waitForSelector(card, { timeout: 15000 });
  const front = await page.$eval(card, c => ({
    name: c.querySelector('.pcfront .pcname .name')?.textContent.trim(),
    repos: [...c.querySelectorAll('.pcfront .pcrepo > .link')].map(b => b.textContent.trim()),
    start: c.querySelector('.pcfront [data-c]')?.dataset.c,
    acts: [...c.querySelectorAll('.pcfront .pcacts > button')].map(b => b.textContent.trim()),
    menu: c.querySelectorAll('[data-pmore]').length, backInert: c.querySelector('.pcback').inert }));
  ok(front.name === 'Shop & Co' && JSON.stringify(front.repos) === '["gamma","ep.silon","shopweb"]'
     && (front.start ?? 'gamma') === 'gamma' && front.acts.includes('Add repository') && front.acts.includes('Edit')
     && front.menu === 0 && front.backInert,
     `the card's front: its name, its repositories, Start on its first, Add repository and Edit, no menu (${JSON.stringify(front)})`);
  // The projects they left stay, empty, until somebody deletes them.
  const left = await page.$eval(`.pcard[data-pkey="${gammaWas}"]`, c => ({ repos: c.querySelectorAll('.pcfront .pcrepo').length,
    empty: /no repository yet/.test(c.querySelector('.pcfront').textContent) }));
  ok(left.repos === 0 && left.empty, `the project gamma left is empty, and says so (${JSON.stringify(left)})`);
  // A press on the card itself opens nothing.
  const tabs = await page.evaluate(() => tabs.length);
  await page.click(`${card} .pcfront .pcfacts`);
  ok(await page.evaluate(() => tabs.length) === tabs, 'a press on the card opens nothing');
  // Edit turns it over at the size it was.
  const h0 = await page.$eval(card, c => c.getBoundingClientRect().height);
  await page.click(`${card} .pcfront [data-pedit]`);
  await page.waitForSelector(`${card}.flipped`, { timeout: 3000 });
  await page.waitForTimeout(500);
  const back = await page.$eval(card, c => ({
    h: c.getBoundingClientRect().height, frontInert: c.querySelector('.pcfront').inert,
    rows: [...c.querySelectorAll('.pcback .pcrepo')].map(r => [r.querySelector('.name')?.textContent.trim(),
      ...[...r.querySelectorAll('button')].map(b => Object.keys(b.dataset).find(k => k !== 'danger'))]),
    foot: [...c.querySelectorAll('.pcback .pcacts > button')].map(b => b.getAttribute('aria-label')),
    lines: new Set([...c.querySelectorAll('.pcback .pcacts > button')].map(b => Math.round(b.getBoundingClientRect().top))).size,
    frontLines: new Set([...c.querySelectorAll('.pcfront .pcacts > button')].map(b => Math.round(b.getBoundingClientRect().top))).size,
    rename: !!c.querySelector('.pcback .pcname [data-prn]') }));
  ok(Math.abs(back.h - h0) < 1 && back.frontInert, `Edit turns the card over at its size (${h0} then ${back.h})`);
  ok(back.rows.length === 3 && back.rows.every(r => ['rrn', 'rmove', 'del'].every(k => r.includes(k))) && back.rename,
     `each repository on the back has rename, move and delete, and the project's name its pencil (${JSON.stringify(back.rows)})`);
  ok(['Color', 'Group', 'Report bug', 'Settings'].every(w => back.foot.includes(w)) && back.lines === 1 && back.frontLines === 1
     && !back.foot.includes('Delete project'),
     `each face's buttons are one line, the back's the project's controls as icons, Delete project only for an empty one (${JSON.stringify(back)})`);
  // Report bug asks which repository, the first picked.
  await page.click(`${card} .pcback [data-bug]`);
  await page.waitForSelector('#reportModal:not([hidden])', { timeout: 3000 });
  const rep = await page.evaluate(() => ({ shown: !$('reportRepoField').hidden, picked: $('reportRepo').value,
    all: [...$('reportRepo').options].map(o => o.value) }));
  ok(rep.shown && rep.picked === 'gamma' && rep.all.length === 3, `Report bug picks a repository, the first by default (${JSON.stringify(rep)})`);
  await page.evaluate(() => { $('reportModal').hidden = true; });
  await page.click(`${card} .pcback [data-pedit]`);
  await page.waitForFunction(c => !document.querySelector(c).classList.contains('flipped'), card, { timeout: 3000 });
  // A repository's own page names the project, its repositories a switch
  // with this one picked; its Start opens the project's one session.
  const head = await page.evaluate(() => { const d = document.createElement('div'); d.innerHTML = projectHeader({ arg: 'ep.silon' });
    return { name: d.querySelector('.pname')?.textContent.trim(), at: d.querySelector('[data-c]')?.dataset.c ?? 'gamma',
             sw: [...d.querySelectorAll('[data-reposw]')].map(b => b.textContent.trim() + (b.classList.contains('on') ? '*' : '')) }; });
  ok(head.name === 'Shop & Co' && head.at === 'gamma' && JSON.stringify(head.sw) === '["gamma","ep.silon*","shopweb"]',
     `a repository's page names its project, a switch with it picked, Start on the first (${JSON.stringify(head)})`);
  // Its other repositories' open items under one repository's own list.
  await page.evaluate(() => postJSON('/api/roadmap', { project: 'ep.silon', action: 'add', text: 'also-row from ep.silon' }));
  const also = await page.evaluate(async () => { const d = document.createElement('div'); document.body.append(d);
    await reposAlso(d, 'gamma', 'roadmap'); const out = { hidden: d.hidden, head: d.querySelector('.t')?.textContent.trim(),
      rows: [...d.querySelectorAll('.alsorow')].map(r => r.textContent.replace(/\s+/g, ' ').trim()) }; d.remove(); return out; });
  ok(!also.hidden && also.head === 'Also in Shop & Co' && also.rows.some(r => /^ep\.silon ?R\d+ ?also-row from ep\.silon$/.test(r)),
     `a repository's roadmap carries its project's other repositories' items (${JSON.stringify(also)})`);
  // Pinned, Home shows it once, by its name; the pin by the name says so.
  await page.evaluate(k => setProjectPinned(k, true), key);
  await page.waitForSelector(`${card} .pcfront .pcmark.on[data-pmark]`, { timeout: 5000 });
  const glance = await page.evaluate(() => { const d = document.createElement('div'); d.innerHTML = homeGlanceHtml();
    return [...d.querySelectorAll('.hproj .name')].map(b => b.textContent.trim()); });
  ok(glance.filter(n => n === 'Shop & Co').length === 1, `Home shows the project once, by its name (${JSON.stringify(glance)})`);
  await page.evaluate(k => setProjectPinned(k, false), key);
  await page.screenshot({ path: `${DIR}/repos-card.png` }).catch(() => {});
  await page.close();
}

// One session for the project, on its first repository.
const t = await fetch(base + '/termws?arg=' + encodeURIComponent('claude:ep.silon'), { headers: ADMIN });
const said = await t.text();
ok(t.status === 403 && /whose sessions start on gamma/.test(said),
   `a session on the project's second repository is refused, naming where it starts (${t.status} ${said.slice(0, 160)})`);

// A dial set through one repository is the project's.
const dial = await post('/api/prefs', { project: 'ep.silon', devbuild: 'auto' });
ok(dial.status === 200 && prefsFile()[key]?.devbuild === 'auto' && !prefsFile()['ep.silon']?.devbuild,
   `a project's dial set from one repository's settings is the project's (${JSON.stringify(prefsFile()[key])})`);
await post('/api/prefs', { project: 'ep.silon', devbuild: 'deny' });

// Renamed; not to another project's name.
const rn = await post('/api/repos', { action: 'rename', key, to: 'Shop' });
ok(rn.status === 200 && (await status()).repos[key]?.name === 'Shop', `the project is renamed (${JSON.stringify(rn)})`);
const clash = await post('/api/repos', { action: 'rename', key, to: (await status()).repos[gammaWas]?.name || 'gamma' });
ok(clash.status === 400 && /already a project's name/.test(clash.error || ''), `not to another project's name (${clash.error})`);

// The trash names the project; with the project gone, Put back asks where.
const tr = await post('/api/trash', { name: 'shopweb' });
ok(tr.status === 200 && tr.project === 'Shop', `a repository to the trash says which project it was in (${JSON.stringify(tr)})`);
const bin = await (await fetch(base + '/api/trash', { headers: ADMIN })).json();
ok((bin.items || []).some(i => i.name === 'shopweb' && i.project === 'Shop'), 'the trash lists it with its project');
const b1 = await post('/api/repos', { action: 'move', name: 'gamma', to: gammaWas });
const b2 = await post('/api/repos', { action: 'move', name: 'ep.silon', to: epWas });
ok(b1.status === 200 && b2.status === 200, `both move back where they were (${b1.status} ${b1.error || ''} ${b2.status} ${b2.error || ''})`);
const gone = await post('/api/repos', { action: 'delete', key });
ok(gone.status === 200 && !(await status()).repos[key], `an empty project is deleted (${JSON.stringify(gone)})`);
const ask = await post('/api/trash-restore', { name: 'shopweb' });
ok(ask.status === 409 && ask.pick && /Shop, which is deleted/.test(ask.error || ''), `Put back asks where when its project is gone (${ask.error})`);
const back = await post('/api/trash-restore', { name: 'shopweb', project: gammaWas });
ok(back.status === 200 && reposFile()[gammaWas]?.members.includes('shopweb'), `...and puts it back into the project picked (${JSON.stringify(back)})`);
await post('/api/trash', { name: 'shopweb' });

// Put back.
await post('/api/prefs', { project: 'beta', reads: [] });
await done(browser);
