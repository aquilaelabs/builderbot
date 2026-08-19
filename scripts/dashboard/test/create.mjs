// New project: the button at the foot of the Projects card, the dialog, and
// /api/create behind it. The local path runs for real — git init in the
// scratch workspace, CLAUDE.md built from the checkout's template — while the
// clone path is tested up to its URL allow-list: the list is the thing under
// test, and a real clone would need GitHub on the other end.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { readFileSync, existsSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);

// ---- the dialog --------------------------------------------------------
ok(await page.$eval('#projects #bNewProj', b => b.textContent.includes('New project')),
   'New project sits at the foot of the Projects card');
await page.click('#bNewProj');
ok(await page.$eval('#pmodal', el => !el.hidden), 'the dialog opens');
ok(await page.$eval('#pUrlField', el => el.hidden), 'local repo is the default; no URL field');
await page.click('#pClone');
ok(await page.$eval('#pUrlField', el => !el.hidden)
   && await page.$eval('#pClone', b => b.classList.contains('on')),
   'clone mode shows the URL field and takes the green');
ok(await page.$eval('#pNameField', el => el.hidden)
   && await page.$eval('#pAboutField', el => el.hidden),
   'clone mode asks for nothing but the URL — name and notes come from the repo');
await page.click('#pLocal');
ok(await page.$eval('#pNameField', el => !el.hidden), 'back to local brings the name field back');

// Refusals keep the dialog open with the reason in place — nothing typed is
// lost to a mistake.
await page.click('#pCreate');
ok(await page.$eval('#pErr', el => el.textContent.includes('name')),
   'an empty name is refused in place');
await page.fill('#pName', 'alpha');
await page.click('#pCreate');
await page.waitForFunction(() =>
  document.getElementById('pErr').textContent.includes('already exists'));
ok(await page.$eval('#pmodal', el => !el.hidden),
   'a taken name is refused with the reason, dialog still open');

// ---- a real local project ----------------------------------------------
await page.fill('#pName', 'zeta');
await page.fill('#pAbout', 'A widget frobnicator. Build with make.');
await page.click('#pCreate');
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 15000 });
await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
  .some(n => n.textContent === 'zeta'), { timeout: 15000 });
ok(true, 'the new project appears in the card');
ok(existsSync(`${DIR}/ws/zeta/.git`), 'zeta is a git repository');
const md = readFileSync(`${DIR}/ws/zeta/CLAUDE.md`, 'utf8');
const marker = md.indexOf('BUILDERBOT:ENV:END');
ok(marker > 0, 'its CLAUDE.md carries the environment block');
ok(md.indexOf('A widget frobnicator') > marker,
   '...with the given notes below the end marker');

// ---- the allow-lists ---------------------------------------------------
// Straight at the API: git accepts transports (ext:: runs commands) that must
// never get past the server, whatever the page's own form checks.
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/create', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return r.status;
}, body);
for (const url of ['https://evil.example/owner/repo', 'ext::sh -c id',
                   'file:///etc', 'https://github.com/owner-only',
                   'git@github.com:owner/repo extra'])
  ok(await post({ mode: 'clone', url }) === 400, `clone refused: ${url}`);
ok(!existsSync(`${DIR}/ws/repo`), 'a refused clone leaves no directory behind');
// The name comes off the URL, not the request — proven without touching the
// network: a URL naming a repo that already exists here is refused by the
// mkdir claim before git ever runs.
for (const url of ['https://github.com/owner/alpha', 'git@github.com:owner/alpha.git'])
  ok(await post({ mode: 'clone', url }) === 400, `derived name collides, refused: ${url}`);
for (const name of ['../oops', 'a/b', '.hidden', '_work', 'a b', ''])
  ok(await post({ name, mode: 'init' }) === 400,
     `name refused: ${name || '(empty)'}`);
ok(await post({ name: 'q2', mode: 'sideways' }) === 400, 'unknown mode refused');

// The refusals above are answered with 400s on purpose, and the browser logs
// each one as a failed resource — those lines are the test passing, not a
// fault. Anything else is still a failure.
const errs = page.errors.filter(e => !e.includes('status of 400'));
ok(errs.length === 0, `zero console errors${errs.length ? ' — ' + errs.join(' | ') : ''}`);
await done(browser);
