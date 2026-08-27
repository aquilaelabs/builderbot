// New project: the button at the foot of the Projects card, the dialog, and
// /api/create behind it. The local path runs for real — git init in the
// scratch workspace, CLAUDE.md built from the checkout's template — while the
// clone path is tested up to its URL allow-list: the list is the thing under
// test, and a real clone would need GitHub on the other end.
import { launch, newPage, ok, done, ready, URL, DIR, animatedDuring } from './lib.mjs';
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
const idle = () => page.evaluate(() => document.activeElement?.tagName || '');
ok(await idle() !== 'INPUT' && await idle() !== 'TEXTAREA',
   '...with the cursor in none of its fields');
ok(await page.$eval('#pUrlField', el => el.hidden), 'local repo is the default; no URL field');
const cloneSlide = await animatedDuring(page, () => page.click('#pClone'));
ok(await page.$eval('#pUrlField', el => !el.hidden)
   && await page.$eval('#pClone', b => b.classList.contains('on')),
   'clone mode shows the URL field and takes the green');
ok(cloneSlide.some(k => k.includes('pUrlField')),
   '...sliding in from its tab\'s side, like the view switch');
ok(await page.$eval('#pNameField', el => !el.hidden)
   && await page.$eval('#pAboutField', el => el.hidden),
   'clone mode asks for a name as well as the URL — only the notes come from the repo');
// The name follows the address, so the common case is still no typing...
await page.fill('#pUrl', 'https://github.com/owner/radarr.git');
ok(await page.$eval('#pName', el => el.value) === 'radarr',
   '...prefilled from the address, .git and all stripped off');
// ...and stops following the moment somebody wants two of the same repo.
await page.fill('#pName', 'radarr-4k');
await page.fill('#pUrl', 'https://github.com/owner/radarr');
ok(await page.$eval('#pName', el => el.value) === 'radarr-4k',
   '...but a name typed by hand is not overwritten by the next keystroke');
await page.fill('#pUrl', '');
await page.click('#pLocal');
ok(await page.$eval('#pNameField', el => !el.hidden), 'back to local keeps the name field');
// Put the field back as it was found. A mode switch does not clear it — only
// reopening does — and the refusal test below needs the name genuinely empty,
// or it submits a valid one and closes the dialog out from under everything
// after it.
// Set, not filled: page.fill focuses the input, and the very next assertion
// is that switching tabs leaves no cursor anywhere (an on-screen keyboard over
// half the dialog is the thing it guards).
await page.$eval('#pName', el => { el.value = ''; });
// Neither tab puts a cursor anywhere. A focused field brings the on-screen
// keyboard up with it, over half of the dialog that just opened — so the
// field is picked by whoever wants to type in it.
ok(await idle() !== 'INPUT' && await idle() !== 'TEXTAREA',
   'switching to local leaves the keyboard down');
await page.click('#pClone');
ok(await idle() !== 'INPUT' && await idle() !== 'TEXTAREA',
   '...and so does switching to clone');
await page.click('#pLocal');

// Refusals keep the dialog open with the reason in place — nothing typed is
// lost to a mistake.
await page.click('#pCreate');
ok(await page.$eval('#pErr', el => el.textContent.includes('name')),
   'an empty name is refused in place');
// ...and does not outlive a mode switch, where it would sit over a form
// that no longer asks for a name.
await page.click('#pClone');
ok(await page.$eval('#pErrWrap', el => el.hidden), 'switching modes clears the stale error');
await page.click('#pLocal');
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
const post = (body, api = '/api/create') => page.evaluate(async ([b, u]) => {
  const r = await fetch(u, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return r.status;
}, [body, api]);
for (const url of ['https://evil.example/owner/repo', 'ext::sh -c id',
                   'file:///etc', 'https://github.com/owner-only',
                   'git@github.com:owner/repo extra'])
  ok(await post({ mode: 'clone', url }) === 400, `clone refused: ${url}`);
ok(!existsSync(`${DIR}/ws/repo`), 'a refused clone leaves no directory behind');
// The name still comes off the URL when none is given — proven without
// touching the network: a URL naming a repo that already exists here is
// refused by the mkdir claim before git ever runs.
for (const url of ['https://github.com/owner/alpha', 'git@github.com:owner/alpha.git'])
  ok(await post({ mode: 'clone', url }) === 400, `derived name collides, refused: ${url}`);
// ...and a name that IS given wins, which is what makes two checkouts of one
// repository possible. Same proof: it collides where the derived name would not.
ok(await post({ mode: 'clone', url: 'https://github.com/owner/somethingelse',
                name: 'alpha' }) === 400,
   'a supplied name is used instead of the repository\'s own');
// A supplied name is held to the same rule as an init's, rather than being
// trusted because a URL was alongside it.
for (const name of ['../oops', 'a/b', 'a b'])
  ok(await post({ mode: 'clone', url: 'https://github.com/owner/repo', name }) === 400,
     `clone name refused: ${name}`);
for (const name of ['../oops', 'a/b', '.hidden', '_work', 'a b', ''])
  ok(await post({ name, mode: 'init' }) === 400,
     `name refused: ${name || '(empty)'}`);
ok(await post({ name: 'q2', mode: 'sideways' }) === 400, 'unknown mode refused');

// ---- deploy keys -------------------------------------------------------
// The harness agent holds one throwaway key. The endpoint lists its public
// half; the dialog offers it; picking it for a clone writes the .pub selector
// and the per-repo alias into the scratch home. The clone itself then fails —
// the alias resolves against the real HOME's ssh config, which has never
// heard of it — which is exactly what makes this test offline-safe: the
// container-side writes all happen before git runs.
const keys = await page.evaluate(async () =>
  (await (await fetch('/api/pubkeys')).json()).keys);
ok(keys.length === 1 && keys[0].name === 'github_testkey'
   && keys[0].pub.startsWith('ssh-ed25519 '),
   'the agent key is listed with its public half');

await page.click('#bNewProj');
await page.click('#pClone');
await page.waitForFunction(() => !document.getElementById('pKeyField').hidden);
ok(await page.$eval('#pPubWrap', el => el.hidden), 'no key picked, no key shown');
await page.selectOption('#pKey', 'github_testkey');
ok(await page.$eval('#pPub', el => el.value.startsWith('ssh-ed25519 ')),
   'picking the key shows its public half to copy to GitHub');

await page.fill('#pUrl', 'https://github.com/owner/kproj');
await page.click('#pCreate');
// A clone is a background job now: the dialog gets out of the way as soon as
// the job is accepted, and the Projects card carries it from there — which is
// also what happens when the page is closed a second later.
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 20000 });
ok(true, 'the dialog closes once the clone is accepted, rather than holding the request');
ok(await page.$eval('#projects .row.job .name', el => el.textContent === 'kproj'),
   'the Projects card shows the job where its result will appear');
ok(await page.$eval('#projects .row.job .sub', el => /clon|start/.test(el.textContent))
   && await page.$('#projects .row.job .dots') !== null,
   '...saying what it is doing, with an ellipsis rather than a parsed percentage');
ok(await page.$eval('#bNewProj', b => b.disabled),
   '...and New project is dead while it runs — one job at a time');
// The failure lands on the card, not in a toast that is gone in seven
// seconds: the page may not have been open when it happened.
await page.waitForFunction(() => {
  const s = document.querySelector('#projects .row .sub.bad');
  return s && s.textContent.length > 0;
}, { timeout: 60000 });
ok(await page.$('#projects .row.job') === null
   && await page.$eval('#bNewProj', b => !b.disabled),
   'the job ends and the controls come back');
ok(!existsSync(`${DIR}/ws/kproj`), '...and a failed clone leaves no directory');
ok(await page.$('#bJobOk') !== null, 'the failure stays until it is dismissed');
await page.click('#bJobOk');
await page.waitForFunction(() => !document.querySelector('#projects .row .sub.bad'));
ok(true, '...and dismissing clears it');
await page.click('#bNewProj');
await page.click('#pClone');
await page.waitForFunction(() => !document.getElementById('pKeyField').hidden);
const pub = readFileSync(`${DIR}/home/.ssh/bb_github_testkey.pub`, 'utf8');
ok(pub.trim() === keys[0].pub, 'the .pub selector was written from the agent, not the request');
const cfg = readFileSync(`${DIR}/home/.ssh/config`, 'utf8');
ok(cfg.includes('Host bb-github_testkey') && cfg.includes('IdentitiesOnly yes')
   && cfg.includes(`${DIR}/home/.ssh/bb_github_testkey.pub`),
   'the per-repo alias names the .pub and pins IdentitiesOnly');
ok(await post({ mode: 'clone', url: 'https://github.com/owner/kproj',
                key: 'no_such_key' }) === 400, 'an unknown key name is refused');
await page.click('#pCancel');

// ---- a job outlives the page, and can be stopped ------------------------
// The whole reason a clone stopped being an HTTP request. The harness's git
// stalls on this URL, so there is something still running to look at.
await page.click('#bNewProj');
await page.click('#pClone');
await page.fill('#pUrl', 'https://github.com/owner/slowclone');
await page.click('#pCreate');
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 20000 });
await page.waitForFunction(() =>
  document.querySelector('#projects .row.job .name')?.textContent === 'slowclone');
ok(existsSync(`${DIR}/ws/slowclone`),
   'the directory is claimed up front, so a second request cannot take the name');
ok(await page.$$eval('#projects .row .name',
     ns => ns.filter(n => n.textContent === 'slowclone').length === 1),
   '...and the half-made directory is not also listed as a broken project');

await page.reload();
await ready(page);
ok(await page.$eval('#projects .row.job .name', el => el.textContent === 'slowclone'),
   'a reload finds the job still running — it belongs to the server, not the page');
await page.waitForFunction(() => {
  const s = document.querySelector('#projects .row.job .sub');
  return s && /\d+s/.test(s.textContent);
}, { timeout: 15000 });
ok(true, '...and says how long it has been going');

await page.click('#bJobStop');
await page.waitForFunction(() => !document.querySelector('#projects .row.job'),
                           { timeout: 30000 });
ok(!existsSync(`${DIR}/ws/slowclone`),
   'Abort stops it and removes the half-cloned directory');
ok((await page.$eval('#projects .row .sub.bad', el => el.textContent)).includes('stopped'),
   '...and says so rather than looking like a failure of its own');
await page.click('#bJobOk');
await page.waitForFunction(() => !document.querySelector('#projects .row .sub.bad'));

// ---- link to GitHub ----------------------------------------------------
// alpha has a remote, beta does not: the chain button shows on exactly the
// unlinked one. The dialog is the clone form's third mode — URL and key only.
// With the stub gh (never authenticated) a key is mandatory, and the attempt
// stops at the unresolvable bb- alias, before any remote is added — the
// success path needs a live GitHub and stays a manual test, like the clone's.
ok(await page.$('#projects [data-l="beta"]') !== null
   && await page.$('#projects [data-l="alpha"]') === null,
   'the link button shows only on a repo with no remote');
await page.click('#projects [data-l="beta"]');
ok(await page.$eval('#pTitle', el => el.textContent === 'Link beta to GitHub'),
   'the dialog names the project it is linking');
// The deploy-key pick from the clone flow above must not ride along into
// this open — the select starts empty and repopulates from a fresh fetch.
await page.waitForFunction(() => document.querySelectorAll('#pKey option').length > 1);
ok(await page.$eval('#pKey', el => el.value === ''),
   'a new open starts with no key selected, whatever the last one picked');
ok(await page.$eval('#pSrcField', el => el.hidden)
   && await page.$eval('#pNameField', el => el.hidden)
   && await page.$eval('#pAboutField', el => el.hidden)
   && await page.$eval('#pUrlField', el => !el.hidden),
   'link mode asks for the URL and key only');
await page.fill('#pUrl', 'git@github.com:owner/beta-remote.git');
await page.click('#pCreate');
ok(await page.$eval('#pErr', el => el.textContent.includes('deploy key')),
   'no PAT and no key picked is refused before the round-trip');
await page.waitForFunction(() => !document.getElementById('pKeyField').hidden);
await page.selectOption('#pKey', 'github_testkey');
await page.click('#pCreate');
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 20000 });
await page.waitForFunction(() => {
  const s = document.querySelector('#projects .row .sub.bad');
  return s && s.textContent.length > 0;
}, { timeout: 60000 });
ok(true, 'a link runs as a job too, and its failure lands on the card');
ok(!readFileSync(`${DIR}/ws/beta/.git/config`, 'utf8').includes('[remote'),
   '...and no remote was added — the check comes before the configuration');
await page.click('#bJobOk');
ok(await post({ name: 'alpha', url: 'https://github.com/owner/alpha',
                key: 'github_testkey' }, '/api/link') === 400,
   'a repo that already has a remote is refused');
ok(await post({ name: 'gamma', url: 'https://github.com/owner/gamma',
                key: 'github_testkey' }, '/api/link') === 400,
   'a directory that is not a git repository is refused');
ok(await post({ name: 'nosuch', url: 'https://github.com/owner/x',
                key: 'github_testkey' }, '/api/link') === 400,
   'an unknown project is refused');
ok(await post({ name: 'beta', url: 'https://github.com/owner/beta' },
              '/api/link') === 400,
   'no PAT and no key is refused server-side too');

// The refusals above are answered with 400s on purpose — and the deploy-key
// clone is made to fail with a 500 — and the browser logs each as a failed
// resource. Those lines are the tests passing, not a fault. Anything else is
// still a failure.
const errs = page.errors.filter(e => !/status of (400|500)/.test(e));
ok(errs.length === 0, `zero console errors${errs.length ? ' — ' + errs.join(' | ') : ''}`);
await done(browser);
