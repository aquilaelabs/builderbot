// A project of several repositories (R136): two projects merged into one
// through /api/repos, as the Projects page's Merge asks, and split back.
// What goes by the project: a project that read one of them reads the
// project, and so every repository in it, one added later included; a
// repository's node and dials are its project's; a session cannot merge.
// What is refused, and that everything is as it was after the split. No
// browser.
import { ok, done, DIR, URL, launch, newPage, ready } from './lib.mjs';
import { readFileSync } from 'node:fs';

const base = URL.replace(/\/$/, '');
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const post = async (path, body) => {
  const r = await fetch(base + path, { method: 'POST', headers: ADMIN, body: JSON.stringify(body) });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};
const prefsFile = () => { try { return JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects || {}; } catch { return {}; } };
const reposFile = () => { try { return JSON.parse(readFileSync(`${DIR}/state/project-repos.json`, 'utf8')).projects || {}; } catch { return {}; } };

// beta reads ep.silon to begin with.
const was = await post('/api/prefs', { project: 'beta', reads: ['ep.silon'] });
ok(was.status === 200, `beta reads ep.silon to begin with (${was.status} ${was.error || ''})`);

// Refused: nothing named, a name that is no project, and a session's token.
const none = await post('/api/repos', { action: 'merge', into: 'gamma', add: [] });
ok(none.status === 400 && /name a repository/.test(none.error || ''), `a merge naming no repository is refused (${none.error})`);
const nope = await post('/api/repos', { action: 'merge', into: 'gamma', add: ['nope'] });
ok(nope.status === 400, `a merge naming no project is refused (${nope.status} ${nope.error})`);
const bad = await post('/api/repos', { action: 'shuffle' });
ok(bad.status === 400 && /merge or split/.test(bad.error || ''), `an action that is neither is refused (${bad.error})`);

// delta is locked and archived in the fixture: refused, saying so.
const held = await post('/api/repos', { action: 'merge', into: 'gamma', add: ['delta'] });
ok(held.status === 409 && /delta is locked: unlock it first/.test(held.error || ''), `a locked project is not merged (${held.error})`);

// Merged: gamma and ep.silon, as a project named Shop.
const m = await post('/api/repos', { action: 'merge', into: 'gamma', add: ['ep.silon'], name: 'Shop' });
ok(m.status === 200 && m.ok && m.name === 'Shop' && /^P\d+$/.test(m.id || '') && JSON.stringify(m.members) === '["gamma","ep.silon"]',
   `gamma and ep.silon merge into a project with a name and an id of its own (${JSON.stringify(m)})`);
ok(JSON.stringify(m.readers) === '["beta"]', `...and the answer says which projects now read more (${JSON.stringify(m.readers)})`);
const key = m.key;
ok(JSON.stringify(reposFile()[key]?.members) === '["gamma","ep.silon"]', 'the record keeps its repositories');
ok(JSON.stringify(prefsFile().beta?.reads) === JSON.stringify([key]), `beta reads the project now, not one repository (${JSON.stringify(prefsFile().beta?.reads)})`);

// The Projects page draws the project as one card, its repositories under
// its name, and no card of a repository of its own (step 6).
const browser = await launch();
{
  const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
  await page.goto(URL + '#/projects');
  await ready(page);
  await page.evaluate(() => refresh());
  await page.waitForSelector('.pcard.prepos', { timeout: 15000 }).catch(() => {});
  const drawn = await page.evaluate(() => ({
    cards: [...document.querySelectorAll('.projtab .pcard')].map(c => c.querySelector('.pcname .name')?.textContent.trim()),
    repos: [...document.querySelectorAll('.pcard.prepos .pcrepo > .link')].map(b => b.textContent.trim()),
    start: document.querySelector('.pcard.prepos [data-c]')?.dataset.c,
    takeout: document.querySelectorAll('.pcard.prepos [data-repout]').length }));
  ok(drawn.cards.filter(n => n === 'Shop').length === 1 && !drawn.cards.includes('ep.silon') && !drawn.cards.includes('gamma')
     && JSON.stringify(drawn.repos) === '["gamma","ep.silon"]' && (drawn.start ?? 'gamma') === 'gamma' && drawn.takeout === 2,
     `the project is one card, its repositories under it, its Start (where its first may have one) on its first (${JSON.stringify(drawn)})`);
  // ...and the second repository's own page starts the same one session.
  const at = await page.evaluate(() => { const p = state.projects.find(x => x.name === 'ep.silon');
    const d = document.createElement('div'); d.innerHTML = projectActions(p); return d.querySelector('[data-c]')?.dataset.c; });
  ok(at === 'gamma', `Start on the second repository's page opens the project's session, on its first (${at})`);
  // Colored, its Take out buttons wear the tint its other buttons do (B330).
  await page.evaluate(async () => { await postJSON('/api/project-color', { name: 'gamma', color: 'teal' }); await refresh(); });
  await page.waitForSelector('.pcard.prepos.pc', { timeout: 10000 }).catch(() => {});
  const tint = await page.evaluate(() => {
    const card = document.querySelector('.pcard.prepos'), bg = e => e ? getComputedStyle(e).backgroundColor : '';
    return { out: bg(card?.querySelector('[data-repout]')), more: bg(card?.querySelector('.pcacts .more > button')) };
  });
  ok(tint.out && tint.out === tint.more, `on a colored card, Take out wears the card's tint as its other buttons do (${JSON.stringify(tint)})`);
  await page.evaluate(() => postJSON('/api/project-color', { name: 'gamma', color: '' }));
  await page.screenshot({ path: `${DIR}/repos-card.png` }).catch(() => {});
  await page.close();
}

// One session for the project, on its first repository: one asked for on
// the second is refused, and says where it starts (step 4).
const t = await fetch(base + '/term/?arg=' + encodeURIComponent('claude:ep.silon'), { headers: ADMIN });
const said = await t.text();
ok(t.status === 403 && /repository of Shop, whose sessions start on gamma/.test(said),
   `a session on the project's second repository is refused, naming where it starts (${t.status} ${said.slice(0, 160)})`);

// A dial set through one repository is the project's, and the other has it.
const dial = await post('/api/prefs', { project: 'ep.silon', devbuild: 'auto' });
ok(dial.status === 200 && prefsFile()[key]?.devbuild === 'auto' && !prefsFile()['ep.silon']?.devbuild,
   `a project's dial set from one repository's settings is the project's (${JSON.stringify(prefsFile()[key])})`);

// Merging a repository that is already in it, or the project into another.
const twice = await post('/api/repos', { action: 'merge', into: 'alpha', add: ['ep.silon'] });
ok(twice.status >= 400 && /already in|Shop/.test(twice.error || ''), `a repository in a project is not merged into another (${twice.error})`);

// Split: ep.silon out, which leaves gamma alone, so there is no project of
// repositories any more and both are projects of their own again.
const s = await post('/api/repos', { action: 'split', name: 'ep.silon' });
ok(s.status === 200 && s.dropped && JSON.stringify([...s.out].sort()) === '["ep.silon","gamma"]',
   `splitting ep.silon out leaves a project of one, which is none (${JSON.stringify(s)})`);
ok(!reposFile()[key], 'the record is gone');
ok(JSON.stringify([...(prefsFile().beta?.reads || [])].sort()) === '["ep.silon","gamma"]',
   `beta reads both repositories by name, so the split took nothing away (${JSON.stringify(prefsFile().beta?.reads)})`);
const again = await post('/api/repos', { action: 'split', name: 'ep.silon' });
ok(again.status === 400 && /not in a project/.test(again.error || ''), `a repository on its own is not split (${again.error})`);

// Put back.
await post('/api/prefs', { project: 'beta', reads: [] });
await done(browser);
