// New project: the button at the foot of the Projects card, the dialog, and
// /api/create behind it. The local path runs for real — git init in the
// scratch workspace, CLAUDE.md built from the checkout's template — while the
// clone path is tested up to its URL allow-list: the list is the thing under
// test, and a real clone would need GitHub on the other end.
import { launch, newPage, ok, done, ready, URL, DIR, animatedDuring, tmuxNew, tmuxKill,
         refreshUntil } from './lib.mjs';
import { readFileSync, existsSync, mkdirSync, writeFileSync, rmSync, chmodSync, statSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);

// Declared here, not down beside the allow-list tests where they began:
// the rename section above those uses them, and `const` in a module has a
// temporal dead zone rather than being hoisted.
const post = (body, api = '/api/create') => page.evaluate(async ([b, u]) => {
  const r = await fetch(u, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return r.status;
}, [body, api]);
// The same call, keeping the body: sanitizing is asserted on the name that
// comes back, which is the only place the answer actually exists.
const postJson = (body, api = '/api/create') => page.evaluate(async ([b, u]) => {
  const r = await fetch(u, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [body, api]);

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
// The preview says what the directory will be called, and only when that is
// not what was typed.
await page.fill('#pName', 'My New App');
ok(await page.$eval('#pNamePreview', el => !el.hidden && /My-New-App/.test(el.textContent)),
   'a name GitHub would rewrite is previewed as the directory it becomes');
await page.fill('#pName', 'plain');
ok(await page.$eval('#pNamePreview', el => el.hidden),
   '...and stays quiet when there is nothing to say');
// Put the field back as it was found: a mode switch does not clear it, only
// reopening does, and the refusal below needs the name genuinely empty or it
// submits a valid one and closes the dialog out from under everything after.
// Set rather than filled, because page.fill focuses the input and the very
// next assertion is that switching tabs leaves no cursor anywhere.
await page.$eval('#pName', el => { el.value = ''; el.blur(); });
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
// Two files: the render, which git never sees, and the project's own notes,
// which it does (roadmap R50).
ok(readFileSync(`${DIR}/ws/zeta/CLAUDE.local.md`, 'utf8').includes('BUILDERBOT:ENV:END'),
   'it gets the environment block, in the file that is not committed');
ok(readFileSync(`${DIR}/ws/zeta/CLAUDE.md`, 'utf8').includes('A widget frobnicator'),
   '...and CLAUDE.md is the notes that were typed, with no block in it');
ok(!readFileSync(`${DIR}/ws/zeta/CLAUDE.md`, 'utf8').includes('BUILDERBOT:ENV:BEGIN'),
   '...which is what makes it a file worth committing');
ok(readFileSync(`${DIR}/ws/zeta/.git/info/exclude`, 'utf8').includes('/CLAUDE.local.md'),
   '...and the render is excluded in this checkout, not in the project\'s own .gitignore');

// ---- drift inside the window stops nothing ------------------------------
// The block is what a session is briefed with, and it goes stale every time
// the image gains a feature. Inside a compatibility window that is routine
// — the row offers the one-press fix, and a session may start meanwhile,
// the same promise the agent's window makes. Only a block from ANOTHER
// window (below) holds the project.
{
  const mdPath = `${DIR}/ws/zeta/CLAUDE.local.md`;
  const current = readFileSync(mdPath, 'utf8');
  writeFileSync(mdPath, current.replace('BUILDERBOT:ENV:BEGIN -->',
    'BUILDERBOT:ENV:BEGIN -->\nA line the image never wrote.'));
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => (state.projects || []).find(p => p.name === 'zeta')
    ?.issues.some(i => i.action === 'claude-md-update'), { timeout: 20000 });
  const btn = '#projects .row[data-row="zeta"] [data-c="zeta"]';
  await page.waitForSelector(btn, { timeout: 10000 });
  const drifted = await page.$eval(btn, b => ({ off: b.disabled, why: b.dataset.tip || b.title }));
  // Asked about the HOLD and not about `disabled`: these fixture projects
  // have no node, and a project with no node has a dead Claude button
  // whatever its CLAUDE.md says. What must not happen is the window
  // becoming the reason.
  ok(!(await page.evaluate(() => (state.projects || []).find(p => p.name === 'zeta')?.held))
     && !/compatibility window/.test(drifted.why),
     `a block behind inside the window offers the update and does not hold the project (${
       drifted.why.slice(0, 50)})`);
  ok(!(await page.evaluate(() => (state.attention || []).some(a => a.kind === 'md' && a.project === 'zeta'))),
     '...and pins nothing in the bell');
}

// ---- a block from another window holds the project ----------------------
// Across a window the promise was never made: the block describes a
// different BuilderBot, so the button ghosts saying so, the bell pins it in
// red, and a session already running on the project is ended by the sweep
// — the moment after a controller update is exactly when a conversation
// started under the old window is acting on a map that is now wrong. The
// row's own link is the fix, and everything above leaves when it is pressed.
{
  const mdPath = `${DIR}/ws/zeta/CLAUDE.local.md`;
  const current = readFileSync(mdPath, 'utf8');
  const win = /BUILDERBOT:ENV:WINDOW (\d+\.\d+)/.exec(current)?.[1] || '';
  ok(/^\d+\.\d+$/.test(win), `a project made from the template carries its window (${win || 'none'})`);
  tmuxNew('claude-zeta', `${DIR}/ws/zeta`);
  await refreshUntil(page, () => (state.sessions || []).some(s => s.name === 'claude-zeta'));
  writeFileSync(mdPath, current.replace(`BUILDERBOT:ENV:WINDOW ${win} -->`,
    'BUILDERBOT:ENV:WINDOW 0.1 -->'));
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => (state.projects || []).find(p => p.name === 'zeta')?.held,
    { timeout: 20000 });
  const btn = '#projects .row[data-row="zeta"] [data-c="zeta"]';
  const ghosted = await page.$eval(btn, b => ({ off: b.disabled, why: b.dataset.tip || b.title }));
  ok(ghosted.off && /older compatibility window \(0\.1 against/.test(ghosted.why),
     `a block from another window ghosts the Claude button, saying which (${ghosted.why.slice(0, 70)})`);
  ok(await page.$eval('#projects .row[data-row="zeta"] [data-fix="claude-md-update"]',
       a => /older compatibility window/.test(a.textContent)),
     '...and the row\'s update link says the same');
  const alert = await page.evaluate(() => (state.attention || []).find(a => a.kind === 'md' && a.project === 'zeta'));
  ok(alert && alert.project === 'zeta' && alert.window && alert.from === '0.1',
     `...and the bell pins it in red, naming the project and the window (${JSON.stringify(alert)})`);
  await page.click('#bBell');
  await page.waitForSelector('#bellPanel .bnote.bad', { timeout: 10000 });
  ok(await page.$eval('#bellPanel', e => /CLAUDE\.md out of window/.test(e.textContent)
                                          && !!e.querySelector('[data-bmd="zeta"]')),
     '...as a row in the bell with Update on it');
  await page.click('#bBell');
  // The sweep runs every second under the suite: the session it ends is the
  // one on the held project, and nothing else on the box.
  //
  // Waited on both names. claude-zeta may already be gone from `state` here
  // — the sweep fires within a second of the write, and the payload that
  // said `held` lists sessions after the git walk — and refreshUntil looks
  // before it refreshes, so a wait on the absence alone can return without
  // any poll having listed the session just made, which then reads as
  // ended (B78).
  tmuxNew('claude-alpha-keep', `${DIR}/ws/alpha`);
  await refreshUntil(page, () => !(state.sessions || []).some(s => s.name === 'claude-zeta')
                                 && (state.sessions || []).some(s => s.name === 'claude-alpha-keep'),
                     { timeout: 20000 });
  ok(await page.evaluate(() => (state.sessions || []).some(s => s.name === 'claude-alpha-keep')),
     '...and the session running on the held project is ended, while another project\'s is not');
  tmuxKill('claude-alpha-keep');
  // ...and the fix the row offers is what brings it all back.
  await page.click('#projects .row[data-row="zeta"] [data-fix="claude-md-update"]');
  await page.waitForFunction(() => !((state.projects || []).find(p => p.name === 'zeta')
    ?.issues || []).some(i => i.action === 'claude-md-update'), { timeout: 20000 });
  ok(!(await page.evaluate(() => (state.projects || []).find(p => p.name === 'zeta')?.held))
     && !/compatibility window/.test(
          await page.$eval(btn, b => b.dataset.tip || b.title || '')),
     '...and the update link on the row lifts the hold, so a session can start again');
  ok(!(await page.evaluate(() => (state.attention || []).some(a => a.kind === 'md' && a.project === 'zeta'))),
     '...with the bell\'s row gone on its own');
  ok(readFileSync(`${DIR}/ws/zeta/CLAUDE.md`, 'utf8').includes('A widget frobnicator'),
     '...with the project\'s own notes, in their own file, untouched');

  // AHEAD is not the same state and must not be held. It is what this repo's
  // own checkout looks like between a minor bump and the image built from
  // it: the block describes the BuilderBot the container is about to be, the
  // session's own bb comes from the container either way, and the remedy the
  // hold offered made it worse — restamping the block DOWN contradicts the
  // tree it came from, and rebuilding puts it back. The operator hit exactly
  // this and lost a session to it.
  const ahead = String(Number(win) + 0.1).slice(0, 3);
  writeFileSync(mdPath, current.replace(`BUILDERBOT:ENV:WINDOW ${win} -->`,
    `BUILDERBOT:ENV:WINDOW ${ahead} -->`));
  await page.evaluate(() => refresh());
  await refreshUntil(page, () => (state.projects || []).some(p => p.name === 'zeta'),
                     { timeout: 20000 });
  ok(!await page.evaluate(() => (state.projects || []).find(p => p.name === 'zeta')?.held),
     `a block from a LATER window is drift, not a hold (${ahead} against ${win})`);
  ok(!/compatibility window/.test(
       await page.$eval(btn, b => b.dataset.tip || b.title || '')),
     '...so nothing about the window is held against it');
  writeFileSync(mdPath, current);
}

// A project made after anything has been pinned is pinned itself. Without
// that it lands on disk and never reaches the sidebar — created, and to the
// operator indistinguishable from gone. Unpinning first is what brings the
// pins file into existence; while there is none, everything is pinned anyway
// and this would prove nothing.
await page.evaluate(() => setProjectPinned('beta', false));
await page.waitForFunction(
  () => ![...document.querySelectorAll('#projects .row .name')]
          .some(n => n.textContent.trim() === 'beta'), { timeout: 15000 });
await page.click('#bNewProj');           // zeta's create closed the dialog
await page.waitForSelector('#pmodal:not([hidden])');
await page.fill('#pName', 'pinme');
await page.click('#pCreate');
await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
  .some(n => n.textContent === 'pinme'), { timeout: 15000 });
ok(true, 'a project created while a pins file exists still reaches the sidebar');

// ---- starting a local repo from an archive -------------------------------
// A code base somebody already has, dropped into a fresh repo: unpacked
// before git init, the wrapper folder a tarball or a GitHub zip carries
// dropped, desktop junk skipped, and — because an archive is a list of
// paths somebody else wrote — anything reaching outside the directory
// refused whole rather than written.
{
  const fx = `${DIR}/archives`;
  mkdirSync(`${fx}/app/src`, { recursive: true });
  writeFileSync(`${fx}/app/src/main.js`, 'console.log(1)\n');
  writeFileSync(`${fx}/app/README.md`, '# App\n\nA thing that frobnicates widgets. Build with make.\n');
  writeFileSync(`${fx}/app/build.sh`, '#!/bin/sh\nmake\n');
  chmodSync(`${fx}/app/build.sh`, 0o755);
  mkdirSync(`${fx}/app/__MACOSX`, { recursive: true });
  writeFileSync(`${fx}/app/__MACOSX/._main.js`, 'junk');
  execFileSync('tar', ['czf', `${fx}/app.tgz`, '-C', fx, 'app']);
  await page.click('#bNewProj');
  await page.waitForSelector('#pmodal:not([hidden])');
  ok(await page.$eval('#pArchiveField', el => !el.hidden),
     'a new local repo offers an archive to start from');
  await page.click('#pClone');
  ok(await page.$eval('#pArchiveField', el => el.hidden), '...and a clone does not');
  await page.click('#pLocal');
  await page.fill('#pName', 'fromtar');
  await page.setInputFiles('#pArchive', `${fx}/app.tgz`);
  await page.click('#pCreate');
  await page.waitForFunction(() => document.getElementById('pmodal').hidden, { timeout: 20000 });
  await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
    .some(n => n.textContent === 'fromtar'), { timeout: 15000 });
  ok(existsSync(`${DIR}/ws/fromtar/src/main.js`) && existsSync(`${DIR}/ws/fromtar/.git`),
     'a tarball is unpacked into the new repo, its one top-level folder dropped');
  ok(!existsSync(`${DIR}/ws/fromtar/app`) && !existsSync(`${DIR}/ws/fromtar/__MACOSX`),
     '...without the wrapper folder or the desktop junk');
  ok((statSync(`${DIR}/ws/fromtar/build.sh`).mode & 0o111) !== 0,
     '...and a script keeps its executable bit');
  ok(readFileSync(`${DIR}/ws/fromtar/CLAUDE.local.md`, 'utf8').includes('BUILDERBOT:ENV:END')
     && readFileSync(`${DIR}/ws/fromtar/CLAUDE.md`, 'utf8').trim().split('\n').length > 3,
     'with no notes typed, a CLAUDE.md is drafted from the unpacked files');

  // A zip with no wrapper folder lands as it is.
  execFileSync('python3', ['-c', `
import zipfile
with zipfile.ZipFile('${fx}/flat.zip', 'w') as z:
    z.writestr('a/b.txt', 'b')
    z.writestr('c.txt', 'c')
    z.writestr('.DS_Store', 'junk')
`]);
  await page.click('#bNewProj');
  await page.waitForSelector('#pmodal:not([hidden])');
  await page.fill('#pName', 'fromzip');
  await page.setInputFiles('#pArchive', `${fx}/flat.zip`);
  await page.click('#pCreate');
  await page.waitForFunction(() => document.getElementById('pmodal').hidden, { timeout: 20000 });
  await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
    .some(n => n.textContent === 'fromzip'), { timeout: 15000 });
  ok(existsSync(`${DIR}/ws/fromzip/a/b.txt`) && existsSync(`${DIR}/ws/fromzip/c.txt`)
     && !existsSync(`${DIR}/ws/fromzip/.DS_Store`),
     'a zip with more than one thing at the top is unpacked as it is, junk aside');

  // What a desktop makes: Finder's Compress puts a __MACOSX folder BESIDE
  // the tree, and `tar czf x.tgz ./app` writes every member under ./ — both
  // are the ordinary case, and neither is a second folder anybody meant.
  execFileSync('python3', ['-c', `
import zipfile
with zipfile.ZipFile('${fx}/finder.zip', 'w') as z:
    z.writestr('app/src/main.js', 'x')
    z.writestr('__MACOSX/app/._main.js', 'junk')
    z.writestr('.DS_Store', 'junk')
`]);
  await page.click('#bNewProj');
  await page.waitForSelector('#pmodal:not([hidden])');
  await page.fill('#pName', 'finder');
  await page.setInputFiles('#pArchive', `${fx}/finder.zip`);
  await page.click('#pCreate');
  await page.waitForFunction(() => document.getElementById('pmodal').hidden, { timeout: 20000 });
  await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
    .some(n => n.textContent === 'finder'), { timeout: 15000 });
  ok(existsSync(`${DIR}/ws/finder/src/main.js`) && !existsSync(`${DIR}/ws/finder/__MACOSX`),
     "a Finder-made zip, with its __MACOSX beside the tree, unpacks with the tree's folder dropped and the junk left out");
  execFileSync('tar', ['czf', `${fx}/dotted.tgz`, '-C', fx, './app']);
  await page.click('#bNewProj');
  await page.waitForSelector('#pmodal:not([hidden])');
  await page.fill('#pName', 'dotted');
  await page.setInputFiles('#pArchive', `${fx}/dotted.tgz`);
  await page.click('#pCreate');
  await page.waitForFunction(() => document.getElementById('pmodal').hidden, { timeout: 20000 });
  await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
    .some(n => n.textContent === 'dotted'), { timeout: 15000 });
  ok(existsSync(`${DIR}/ws/dotted/src/main.js`) && !existsSync(`${DIR}/ws/dotted/app`),
     'a tarball made under ./ drops its one folder the same way');

  // A member the library cannot read — encrypted — is an answer, never a
  // 500 with a half-written project left behind.
  execFileSync('python3', ['-c', `
import zipfile
with zipfile.ZipFile('${fx}/locked.zip', 'w') as z:
    z.writestr('a.txt', 'a')
    z.writestr('b.txt', 'b')
# Mark b.txt encrypted in both headers: zipfile then refuses to open it
# with a RuntimeError, the way a real password-protected member does.
d = bytearray(open('${fx}/locked.zip', 'rb').read())
for sig, flag_at, len_at, name_at in ((b'PK\\x03\\x04', 6, 26, 30), (b'PK\\x01\\x02', 8, 28, 46)):
    i = 0
    while (i := d.find(sig, i)) != -1:
        n = int.from_bytes(d[i + len_at:i + len_at + 2], 'little')
        if d[i + name_at:i + name_at + n] == b'b.txt':
            d[i + flag_at] |= 1
        i += 4
open('${fx}/locked.zip', 'wb').write(d)
`]);
  await page.click('#bNewProj');
  await page.waitForSelector('#pmodal:not([hidden])');
  await page.fill('#pName', 'locked');
  await page.setInputFiles('#pArchive', `${fx}/locked.zip`);
  await page.click('#pCreate');
  await page.waitForFunction(() => !document.getElementById('pErrWrap').hidden, { timeout: 15000 });
  ok(/could not unpack/.test(await page.$eval('#pErr', e => e.textContent)) && !existsSync(`${DIR}/ws/locked`),
     'an archive the library cannot open is refused in a sentence, with no half-made project left');
  await page.click('#pCancel');
  await page.waitForFunction(() => document.getElementById('pmodal').hidden);

  // The classic: a member named ../something, which would write beside the
  // workspace rather than in it.
  execFileSync('python3', ['-c', `
import zipfile
with zipfile.ZipFile('${fx}/slip.zip', 'w') as z:
    z.writestr('ok.txt', 'fine')
    z.writestr('../evil.txt', 'no')
`]);
  await page.click('#bNewProj');
  await page.waitForSelector('#pmodal:not([hidden])');
  await page.fill('#pName', 'slip');
  await page.setInputFiles('#pArchive', `${fx}/slip.zip`);
  await page.click('#pCreate');
  await page.waitForFunction(() => !document.getElementById('pErrWrap').hidden, { timeout: 15000 });
  ok(/outside the project/.test(await page.$eval('#pErr', e => e.textContent)),
     'an archive with a path escaping the directory is refused, saying so');
  ok(!existsSync(`${DIR}/ws/slip`) && !existsSync(`${DIR}/ws/evil.txt`),
     '...and leaves neither the half-made project nor the escaped file behind');

  // ...and a file that is not an archive at all is refused at upload, with
  // the formats named, before there is a directory to undo.
  writeFileSync(`${fx}/notes.txt`, 'not an archive');
  await page.setInputFiles('#pArchive', `${fx}/notes.txt`);
  await page.click('#pCreate');
  await page.waitForFunction(() => /not an archive/.test(
    document.getElementById('pErr').textContent), { timeout: 15000 });
  ok(/zip, tar/.test(await page.$eval('#pErr', e => e.textContent)) && !existsSync(`${DIR}/ws/slip`),
     'a file that is not an archive is refused at upload, naming the formats');
  await page.click('#pCancel');
  await page.waitForFunction(() => document.getElementById('pmodal').hidden);
}

// ---- renaming ----------------------------------------------------------
// The button is nothing; the migration is the job. A project's name is its key
// in a dozen stores, and every one of them fails the same quiet way when it is
// missed — the directory is there under its new name and its roadmap is not.
// The pins file is the one that is trivial to seed and to read back, so it
// stands in for the table: if the name moved there it moved by the same code
// path everywhere else.
ok(JSON.parse(readFileSync(`${DIR}/state/pinned-projects.json`, 'utf8')).includes('pinme'),
   'the pins file knows the project before the rename');
const rn = await postJson({ name: 'pinme', to: 'pinned-again' }, '/api/rename');
ok(rn.status === 200 && rn.body.name === 'pinned-again',
   'renaming answers with the name it actually made');
ok(existsSync(`${DIR}/ws/pinned-again/.git`) && !existsSync(`${DIR}/ws/pinme`),
   '...the directory moved, and nothing was left behind under the old name');
const pins = JSON.parse(readFileSync(`${DIR}/state/pinned-projects.json`, 'utf8'));
ok(pins.includes('pinned-again') && !pins.includes('pinme'),
   '...and the state keyed to the old name came with it');
ok(Array.isArray(rn.body.moved) && rn.body.moved.length > 0 && !rn.body.failed.length,
   '...reporting what moved rather than only that it worked');
await page.waitForFunction(() => [...document.querySelectorAll('#projects .name')]
  .some(n => n.textContent === 'pinned-again'), { timeout: 15000 });
ok(true, '...and the row is the new name');

// The refusals. A name already taken, a project that is not there, and the
// name it already has — each answered rather than half-done.
ok(await post({ name: 'pinned-again', to: 'alpha' }, '/api/rename') === 400,
   'renaming onto a name already in the workspace is refused');
ok(await post({ name: 'nosuchproject', to: 'whatever' }, '/api/rename') === 400,
   'renaming something that is not a project is refused');
ok(await post({ name: 'pinned-again', to: 'pinned-again' }, '/api/rename') === 400,
   'renaming to the name it already has is refused');
ok(await post({ name: 'pinned-again', to: '///' }, '/api/rename') === 400,
   'a new name with nothing in it is refused');
// ...and a messy one is sanitized on the way through, exactly as creating is.
const rn2 = await postJson({ name: 'pinned-again', to: 'Two Words!' }, '/api/rename');
ok(rn2.status === 200 && rn2.body.name === 'Two-Words',
   'a new name goes through the same sanitizing a created one does');
ok(existsSync(`${DIR}/ws/Two-Words/.git`), '...and that is the directory');

await page.evaluate(() => setProjectPinned('beta', true));

// ---- the allow-lists ---------------------------------------------------
// Straight at the API: git accepts transports (ext:: runs commands) that must
// never get past the server, whatever the page's own form checks. What is
// checked is the SHAPE, not the host — any git server is linkable now — so
// the corpus is transports, paths that are not repositories, and a path too
// deep for the host it names.
for (const url of ['ext::sh -c id', 'file:///etc', 'https://github.com/owner-only',
                   'git@github.com:owner/repo extra', 'https://github.com/a/b/c',
                   'https://gitea.example/onlyone'])
  ok(await post({ mode: 'clone', url }) === 400, `clone refused: ${url}`);
ok(!existsSync(`${DIR}/ws/repo`), 'a refused clone leaves no directory behind');
// The name still comes off the URL when none is given — proven without
// touching the network: a URL naming a repo that already exists here is
// refused by the mkdir claim before git ever runs. Which also proves the
// address was ACCEPTED, since it got as far as claiming a directory: three of
// these are not GitHub, and one is a GitLab subgroup path, which is the one
// place a third segment is a real part of an address.
for (const url of ['https://github.com/owner/alpha', 'git@github.com:owner/alpha.git',
                   'https://gitea.example/owner/alpha',
                   'ssh://git@git.home.lan:2222/owner/alpha.git',
                   'https://gitlab.com/group/sub/alpha'])
  ok(await post({ mode: 'clone', url }) === 400, `derived name collides, refused: ${url}`);
// ...and a name that IS given wins, which is what makes two checkouts of one
// repository possible. Same proof: it collides where the derived name would not.
ok(await post({ mode: 'clone', url: 'https://github.com/owner/somethingelse',
                name: 'alpha' }) === 400,
   'a supplied name is used instead of the repository\'s own');
// A supplied name goes through the same sanitizing an init's does, rather
// than being trusted because a URL was alongside it. Proven by collision
// again: each of these sanitizes to `alpha`, which already exists, so the
// mkdir claim refuses it before git runs — and a name that had NOT been
// sanitized would not have collided.
for (const name of ['../alpha', 'alpha/', 'alpha ', '.alpha', '_alpha'])
  ok(await post({ mode: 'clone', url: 'https://github.com/owner/repo', name }) === 400,
     `clone name sanitized to an existing one, refused: ${name}`);
// Every one of these sanitizes to `alpha`, which exists — so the refusal
// proves the transformation rather than a rejection, and nothing is created.
for (const name of ['../alpha', 'alpha!', '.alpha', '_alpha', 'alpha '])
  ok(await post({ name, mode: 'init' }) === 400,
     `init name sanitized to an existing one, refused: ${name}`);
// ...and the one thing that is still refused outright: a name with nothing in
// it to name a directory after.
for (const name of ['', '   ', '---', '...', '/'])
  ok(await post({ name, mode: 'init' }) === 400,
     `name refused: ${name || '(empty)'}`);
// The positive case, and the only place the sanitized name is observable:
// a messy one is accepted and the directory is what GitHub would have made.
const made = await postJson({ name: 'My New App!', mode: 'init' });
ok(made.status === 200 && made.body.name === 'My-New-App',
   'a name with spaces and punctuation is created as GitHub would spell it');
ok(existsSync(`${DIR}/ws/My-New-App/.git`),
   '...and that is the directory on disk');
ok(await post({ name: 'q2', mode: 'sideways' }) === 400, 'unknown mode refused');

// ---- a name already taken ----------------------------------------------
// Said in the dialog rather than only by the server, because the server can
// only answer after Create — and the case that needs it most is the one with
// the field left EMPTY, where the name comes from the repository and is never
// typed at all.
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
await page.click('#pClone');
await page.fill('#pUrl', 'https://github.com/owner/alpha.git');
await page.fill('#pName', '');
ok(await page.$eval('#pName', el => el.classList.contains('bad'))
   && await page.$eval('#pNamePreview', el => !el.hidden && /already exists/.test(el.textContent)),
   'an empty name whose repository collides is marked red in the dialog');
await page.fill('#pName', 'alpha-two');
ok(await page.$eval('#pName', el => !el.classList.contains('bad')),
   '...and clears the moment the name is free');
await page.fill('#pName', 'beta');
ok(await page.$eval('#pName', el => el.classList.contains('bad')),
   '...a typed name that is taken is marked too');
await page.keyboard.press('Escape');

// ---- push rights -------------------------------------------------------
// Off by default, and the box only exists where pushing could mean anything.
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
ok(await page.$eval('#pPushField', el => el.hidden),
   'a local repo is not asked about push rights');
await page.click('#pClone');
ok(await page.$eval('#pPushField', el => !el.hidden)
   && await page.$eval('#pPush', el => !el.checked),
   'cloning is, and read-only is the default');
await page.keyboard.press('Escape');

// A public clone cannot push, and is told so rather than being given rights
// that would fail at the first attempt.
ok(await post({ mode: 'clone', url: 'https://github.com/owner/pushless',
                push: true }) === 400,
   'asking to push with neither a token nor a key is refused');

// One project per repository. Driven at the module, because claiming the
// second would otherwise need two real clones.
const rights = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys, tempfile
# projects.py imports its peer forges.py, so the directory it lives in has to
# be importable — loading one file by path does not put its neighbours on the
# path for it.
sys.path.insert(0, ${
  JSON.stringify(new globalThis.URL('..', import.meta.url).pathname)})
spec = importlib.util.spec_from_file_location('p', ${
  JSON.stringify(new globalThis.URL('../projects.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
saved = {}
m.configure(run=lambda *a, **k: {'code': 0, 'out': ''}, workspace='/tmp',
            agent_keys=lambda: [], gh_authed=lambda: False,
            ensure_deploy_alias=lambda *a: '',
            build_claude_md=lambda *a, **k: '', project_name=None,
            state=d, home=d,
            write_json=lambda p, o: open(p, 'w').write(json.dumps(o)))
out = {}
# The remote's identity, however it is spelled — a deploy-key alias hides the
# host but the path is still owner/repo, and case does not distinguish repos.
out['ssh_alias'] = m.repo_of_remotes('origin\tgit@bb-thing:Owner/Repo.git (fetch)')
out['https'] = m.repo_of_remotes('origin\thttps://github.com/owner/repo (push)')
# A subgroup path IS a repository — GitLab nests them — so identity keeps all
# of it. What is not a repository is an address with no owner in it at all.
out['nested'] = m.repo_of_remotes('origin\tgit@host:one/two/three.git (fetch)')
out['not_a_repo'] = m.repo_of_remotes('origin\tgit@host:justone (fetch)')
m.grant_push('first', 'github.com', 'owner/repo', 'key')
out['holder'] = m.push_holder('github.com', 'owner/repo')
out['free'] = m.push_holder('github.com', 'owner/other')
# The same path on another server is another repository — mirroring one to the
# other is a reason to link a second project, not a collision to refuse.
out['elsewhere'] = m.push_holder('gitea.home.lan', 'owner/repo')
out['may'] = [m.may_push('first'), m.may_push('second')]
m.drop_push('first')
out['after_drop'] = m.push_holder('github.com', 'owner/repo')
print(json.dumps(out))
`], { encoding: 'utf8' });
const rj = JSON.parse(rights.trim().split('\n').pop());
ok(rj.ssh_alias === 'owner/repo' && rj.https === 'owner/repo',
   'a deploy-key alias and an https remote name the same repository');
ok(rj.nested === 'one/two/three',
   '...and a subgroup path keeps all of itself, because GitLab nests them');
ok(rj.not_a_repo === '',
   '...while an address with no owner in it is not guessed at');
ok(rj.holder === 'first' && rj.free === '',
   'a granted repository names its holder, and an ungranted one names nobody');
ok(rj.elsewhere === '',
   '...and the same owner/repo on another host is a different repository');
ok(rj.may[0] === true && rj.may[1] === false, 'only the granted project may push');
ok(rj.after_drop === '',
   'deleting the project is what frees the repository for another');

// ---- which host a clone is from ----------------------------------------
// Cloning takes any address linking takes. The host is IN the address there,
// so the form does not ask for one — it asks the one thing an address cannot
// say, which is what is running on a server nobody has answered for, and only
// then. A paste of a GitHub URL is never asked; a Gitea is asked once ever.
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
await page.click('#pClone');
await page.waitForFunction(() => document.querySelectorAll('#pForge option').length > 1);
ok(await page.$eval('#pForgeField', el => el.hidden),
   'an empty address asks nothing about a host');
await page.fill('#pUrl', 'https://github.com/owner/thing.git');
ok(await page.$eval('#pForgeField', el => el.hidden),
   '...and a host that names itself is not a question');
await page.fill('#pUrl', 'https://git.home.lan:3000/owner/thing.git');
ok(!await page.$eval('#pForgeField', el => el.hidden)
   && await page.$eval('#pForgeHost', el => el.hidden),
   '...while one nobody has answered for is asked about, without asking for the address twice');
ok(await page.$eval('#pForge', el => el.value) === 'git',
   '...starting on the entry that promises nothing, rather than on GitHub');
ok(/git\.home\.lan:3000/.test(await page.$eval('#pForgeHint', el => el.textContent)),
   '...naming the server it is asking about');
await page.click('#pmodalClose').catch(() => page.keyboard.press('Escape'));
// And the answer is kept against the host: cloning from it declares it, so
// the next address on the same server is not a question again. Refused for
// the name collision, which is after the address has been accepted.
ok(await post({ mode: 'clone', url: 'https://git.home.lan:3000/owner/alpha.git',
                forge: 'gitea' }) === 400,
   'a clone from a self-hosted host is accepted as an address');
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
await page.click('#pClone');
await page.waitForFunction(() => Object.keys(pForgeHosts).length > 0);
await page.fill('#pUrl', 'https://git.home.lan:3000/owner/other.git');
ok(await page.$eval('#pForgeField', el => el.hidden),
   '...and once answered, that server is never asked about again');
ok(/Gitea/.test(await page.$eval('#pToken', el => el.placeholder)),
   '...with the token field asking for the kind of token that host issues');
await page.click('#pmodalClose').catch(() => page.keyboard.press('Escape'));

// ---- a token that belongs to one project -------------------------------
// The dialog offers it only where it means something.
await page.click('#bNewProj');
await page.waitForSelector('#pmodal:not([hidden])');
ok(await page.$eval('#pTokenField', el => el.hidden),
   'a local repo is not asked for an access token');
await page.click('#pClone');
ok(await page.$eval('#pTokenField', el => !el.hidden)
   && await page.$eval('#pToken', el => el.type === 'password'),
   'cloning is, and it is not typed in the clear');
// Bounded: when the close button is not there this waits, and the default
// wait is thirty seconds for a fallback that is one keystroke.
await page.click('#pmodalClose', { timeout: 1500 })
  .catch(() => page.keyboard.press('Escape'));

// Shape is checked before it is written: the store is a one-line format, so a
// token with a space or a newline in it would produce a file git reads as
// something else.
for (const token of ['has space', 'two\nlines', 'sh', '#{}!'])
  ok(await post({ mode: 'clone', url: 'https://github.com/owner/tok', token }) === 400,
     `a token that is not one is refused: ${JSON.stringify(token)}`);

// The store itself, at the module: a real clone would need GitHub on the other
// end, and this is the half that decides whether the token stays this
// project's alone.
const tok = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys, tempfile
# projects.py imports its peer forges.py, so the directory it lives in has to
# be importable — loading one file by path does not put its neighbours on the
# path for it.
sys.path.insert(0, ${
  JSON.stringify(new globalThis.URL('..', import.meta.url).pathname)})
spec = importlib.util.spec_from_file_location('p', ${
  JSON.stringify(new globalThis.URL('../projects.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
m.configure(run=lambda *a, **k: {'code': 0, 'out': ''}, workspace='/tmp',
            agent_keys=lambda: [], gh_authed=lambda: False,
            ensure_deploy_alias=lambda *a: '',
            build_claude_md=lambda *a, **k: '', project_name=None,
            state=d, home=d, write_json=lambda *a: None)
helper = m.write_token('alpha', 'ghp_ExampleTokenValue123', 'github.com')
f = os.path.join(d, 'gitcreds', 'alpha')
out = {'helper': helper,
       'line': open(f).read().strip(),
       'mode': oct(os.stat(f).st_mode & 0o777),
       'dirmode': oct(os.stat(os.path.dirname(f)).st_mode & 0o777),
       'lookup': m.token_helper('alpha'),
       'other': m.token_helper('beta')}
m.forget_token('alpha')
out['gone'] = not os.path.exists(f)
print(json.dumps(out))
`], { encoding: 'utf8' });
const tj = JSON.parse(tok.trim().split('\n').pop());
ok(tj.line === 'https://oauth2:ghp_ExampleTokenValue123@github.com',
   'a token is stored in git\'s own credential-store format');
ok(tj.mode === '0o600' && tj.dirmode === '0o700',
   '...readable only by the user that runs git, in a directory to match');
ok(tj.helper.startsWith('store --file=') && tj.helper.endsWith('/gitcreds/alpha'),
   '...and the helper git is given names that one file');
ok(tj.lookup === tj.helper && tj.other === '',
   'a project with no token gets no helper — it is not shared, it is absent');
ok(tj.gone, 'and forgetting one removes it');

// ---- which credential the remote actually uses -------------------------
// At the module for the same reason as the store above: the interesting half
// is what gets written into `git remote set-url`, and a real remote would put
// GitHub on the other end of a unit test. `run` is stubbed to answer the one
// question set_auth asks and to record the one command it issues.
const authOut = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys, tempfile
# projects.py imports its peer forges.py, so the directory it lives in has to
# be importable — loading one file by path does not put its neighbours on the
# path for it.
sys.path.insert(0, ${
  JSON.stringify(new globalThis.URL('..', import.meta.url).pathname)})
spec = importlib.util.spec_from_file_location('p', ${
  JSON.stringify(new globalThis.URL('../projects.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
d = tempfile.mkdtemp()
state = {'url': 'git@bb-depkey:Owner/Repo.git'}
issued = []
state['helper'] = ''
def fake_run(cmd, **k):
    if cmd[3:5] == ['remote', 'get-url']:
        return {'code': 0, 'out': state['url'], 'err': ''}
    if cmd[3:5] == ['remote', 'set-url']:
        issued.append(cmd[-1]); state['url'] = cmd[-1]
        return {'code': 0, 'out': '', 'err': ''}
    # The credential helper, remembered: whether the repo is pointed at its own
    # token is what tells "access token" from "disabled", so a stub that always
    # answered empty would make every https remote read as disabled.
    if cmd[3:6] == ['config', '--local', '--replace-all']:
        state['helper'] = ''
        return {'code': 0, 'out': '', 'err': ''}
    if cmd[3:6] == ['config', '--local', '--add']:
        state['helper'] = cmd[-1]
        return {'code': 0, 'out': '', 'err': ''}
    if cmd[3:6] == ['config', '--local', '--get-all']:
        return {'code': 0, 'out': state['helper'], 'err': ''}
    # What the deploy-key alias actually stands for. ssh reads it out of
    # ~/.ssh/config with no network, and it is the only way back from
    # bb-depkey to a hostname an https remote can name.
    if cmd[:2] == ['ssh', '-G']:
        return {'code': 0, 'out': 'hostname github.com', 'err': ''}
    return {'code': 0, 'out': '', 'err': ''}
m.configure(run=fake_run, workspace='/tmp',
            agent_keys=lambda: [], gh_authed=lambda: False,
            ensure_deploy_alias=lambda *a: '',
            build_claude_md=lambda *a, **k: '', project_name=None,
            state=d, home=d,
            write_json=lambda p, v: open(p, 'w').write(json.dumps(v)))
out = {}
m.grant_push('alpha', 'github.com', 'owner/repo', 'key')
out['ssh_seen'] = m.remote_auth('/tmp/alpha')
# No token yet: the switch has to refuse rather than write a remote that
# cannot authenticate.
out['no_token'] = m.set_auth('alpha', '/tmp/alpha', 'https')[1]
out['bad_mode'] = m.set_auth('alpha', '/tmp/alpha', 'nonsense')[1]
m.write_token('alpha', 'ghp_ExampleTokenValue123', 'github.com')
out['opts_on_key'] = m.auth_options('alpha', '/tmp/alpha')
out['to_https'] = m.set_auth('alpha', '/tmp/alpha', 'https')
out['now_https'] = m.remote_auth('/tmp/alpha', 'alpha')
out['opts_on_token'] = m.auth_options('alpha', '/tmp/alpha')
out['token_kept'] = bool(m.token_helper('alpha'))
out['back'] = m.set_auth('alpha', '/tmp/alpha', 'ssh')
# ...and off altogether, which is its own answer rather than a broken second
# one: an https remote with the helper taken off it authenticates with nothing.
out['off'] = m.set_auth('alpha', '/tmp/alpha', 'none')
out['now_off'] = m.remote_auth('/tmp/alpha', 'alpha')
out['issued'] = issued
# A credential is filed under the host it is for. git matches a stored line on
# the scheme and the host, so one written against the wrong server is a file it
# reads and ignores — a token that looks stored and authenticates nothing.
m.write_token('gitea', 'abc123def456', 'git.home.lan:3000', 'http', 'sean')
out['gitea_line'] = open(os.path.join(d, 'gitcreds', 'gitea')).read().strip()
print(json.dumps(out))
`], { encoding: 'utf8' });
const aj = JSON.parse(authOut.trim().split('\n').pop());
ok(aj.ssh_seen === 'ssh',
   'a deploy-key alias is read as ssh, host and all — it is the URL form that decides');
ok(/no access token/.test(aj.no_token),
   'switching to a token nobody stored is refused, not written');
ok(aj.opts_on_key.now === 'ssh' && aj.opts_on_key.token && aj.opts_on_key.ssh,
   'with both credentials present the dialog is offered a real choice');
ok(aj.issued[0] === 'https://github.com/Owner/Repo.git',
   'switching to the token rewrites origin to https, with the repository still spelled the way it is spelled');
ok(aj.gitea_line === 'http://sean:abc123def456@git.home.lan:3000',
   'a token is filed under the host, the port and the scheme its remote uses');
ok(aj.now_https === 'https' && aj.token_kept,
   '...and the token file it now uses is still the project\'s own');
ok(aj.opts_on_token.ssh,
   '...with the deploy key still offered, because the ssh URL was remembered');
ok(aj.issued[1] === 'git@bb-depkey:Owner/Repo.git',
   'switching back restores the exact alias, which nothing could have guessed');
ok(/not an authentication mode/.test(aj.bad_mode),
   'a mode nobody offers is refused rather than written');
ok(!aj.off[1] && /nothing/.test(aj.off[0]) && aj.now_off === 'none',
   'and Disabled is a third answer: https with no token, authenticating with nothing');

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
// What a RUNNING row looks like is asserted further down, against the
// harness's stalling git. Not here: this clone is a real one, and it fails
// whenever ssh gives up on an alias no config has heard of — sometimes
// before the page's next poll, which is a row that came and went between two
// frames. Three full runs died on that. So what is checked here is the
// outcome, which is the part this clone is for: the failure lands on the
// card, not in a toast that is gone in seven seconds — the page may not even
// have been open when it happened.
await page.waitForFunction(() => {
  const s = document.querySelector('#projects .row.jobfail .sub.bad');
  return s && s.textContent.length > 0;
}, { timeout: 60000 });
ok(await page.$eval('#projects .row.jobfail .sub.bad',
     s => s.closest('.row').querySelector('.name').textContent === 'kproj'),
   'the failure is carried under the name the project would have had');
ok(await page.$('#projects .row.job') === null
   && await page.$eval('#bNewProj', b => !b.disabled),
   'the job ends and the controls come back');
ok(!existsSync(`${DIR}/ws/kproj`), '...and a failed clone leaves no directory');
ok(await page.$('#bJobOk') !== null, 'the failure stays until it is dismissed');
await page.click('#bJobOk');
await page.waitForFunction(() => !document.querySelector('#projects .row.jobfail .sub.bad'));
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
// stalls on this URL, so there is something still running to look at — which
// is also why every assertion about a job while it runs belongs here rather
// than against a real clone that may already have failed.
await page.click('#bNewProj');
await page.click('#pClone');
await page.fill('#pUrl', 'https://github.com/owner/slowclone');
await page.click('#pCreate');
await page.waitForFunction(() => document.getElementById('pmodal').hidden,
                           { timeout: 20000 });
await page.waitForFunction(() =>
  document.querySelector('#projects .row.job .name')?.textContent === 'slowclone');
ok(true, 'the Projects card shows the job where its result will appear');
ok(await page.$eval('#projects .row.job .sub', el => /clon|start/.test(el.textContent))
   && await page.$('#projects .row.job .dots') !== null,
   '...saying what it is doing, with an ellipsis rather than a parsed percentage');
ok(await page.$eval('#bNewProj', b => b.disabled),
   '...and New project is dead while it runs — one job at a time');
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
ok((await page.$eval('#projects .row.jobfail .sub.bad', el => el.textContent)).includes('stopped'),
   '...and says so rather than looking like a failure of its own');
await page.click('#bJobOk');
await page.waitForFunction(() => !document.querySelector('#projects .row.jobfail .sub.bad'));

// ---- link to GitHub ----------------------------------------------------
// The chain is GitHub whichever state a project is in — the link form for one
// with no remote, its credential settings for one that has. alpha has a
// remote and beta does not, so the two doors are checked on the two of them.
// With the stub gh (never authenticated) a key is mandatory, and the attempt
// stops at the unresolvable bb- alias, before any remote is added — the
// success path needs a live GitHub and stays a manual test, like the clone's.
ok(await page.$('#projects [data-l="beta"]') !== null
   && await page.$('#projects [data-l="alpha"]') !== null,
   'the chain shows on every repo, linked or not');
await page.click('#projects [data-l="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(/GitHub/.test(await page.$eval('#rnTitle', el => el.textContent))
   && await page.$eval('#rnNameField', el => el.hidden),
   '...and on a linked one it opens that project\'s GitHub settings, not the link form');
await page.click('#rnCancel');
await page.click('#projects [data-l="beta"]');
// The dialog draws before its catalog lands — the keys and the git hosts are
// one fetch per open — so every assertion below about the host picker is
// reading a payload that may still be in flight. Waited on the list being in
// hand rather than on a tick going by, which is what made this file red about
// one run in three on a busy box (B99).
await page.waitForFunction(() => !document.getElementById('pmodal').hidden
  && document.getElementById('pForge')?.options.length > 1, null, { timeout: 20000 });
ok(await page.$eval('#pTitle', el => el.textContent === 'Link beta to a git host'),
   'the dialog names the project it is linking');
// Which host, because a hostname does not say what runs on it. GitHub is one
// server and needs no address; a Gitea is whichever one the operator runs, so
// picking it asks for the address and the placeholder follows what is typed.
ok(!await page.$eval('#pForgeField', el => el.hidden)
   && await page.$eval('#pForgeHost', el => el.hidden),
   'linking asks which host, and a public one needs no address');
await page.selectOption('#pForge', 'gitea');
ok(!await page.$eval('#pForgeHost', el => el.hidden),
   '...and picking a self-hosted one asks where it is');
await page.fill('#pForgeHost', 'git.home.lan:3000');
ok(/git\.home\.lan:3000/.test(await page.$eval('#pUrl', el => el.placeholder)),
   '...with the address box showing the shape for that server');
ok(await post({ name: 'beta', url: 'https://github.com/owner/beta', forge: 'gitea' },
              '/api/link') === 400,
   'and github.com cannot be linked as Gitea: the host names itself');
await page.selectOption('#pForge', 'github');
// The deploy-key pick from the clone flow above must not ride along into
// this open — the select starts empty and repopulates from a fresh fetch.
await page.waitForFunction(() => document.querySelectorAll('#pKey option').length > 1);
ok(await page.$eval('#pKey', el => el.value === ''),
   'a new open starts with no key selected, whatever the last one picked');
ok(await page.$eval('#pSrcField', el => el.hidden)
   && await page.$eval('#pNameField', el => el.hidden)
   && await page.$eval('#pAboutField', el => el.hidden)
   && await page.$eval('#pUrlField', el => !el.hidden)
   && await page.$eval('#pLinkAuthField', el => !el.hidden),
   'link mode asks for the URL and how the push authenticates');
// The switch the settings dialog wears: a deploy key the agent holds, or a
// token for this project alone. The token half is checked for its shape
// before GitHub is asked, so a wrong paste is refused here without a network.
await page.click('#pLinkToken');
ok(await page.$eval('#pTokenField', el => !el.hidden) && await page.$eval('#pKeyField', el => el.hidden),
   'Access token shows the token field and puts the key picker away');
await page.fill('#pUrl', 'https://github.com/owner/beta-remote');
await page.click('#pCreate');
ok(await page.$eval('#pErr', el => /access token/.test(el.textContent)),
   '...and an empty token is refused before the round-trip');
await page.fill('#pToken', 'not-a-token');
await page.click('#pCreate');
await page.waitForFunction(() => /not a GitHub token/.test(document.getElementById('pErr').textContent), null, { timeout: 10000 });
ok(true, '...as is a token that is not one, in a sentence');
await page.click('#pLinkKey');
ok(await page.$eval('#pTokenField', el => el.hidden), 'Deploy key puts the token field away again');
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
  const s = document.querySelector('#projects .row.jobfail .sub.bad');
  return s && s.textContent.length > 0;
}, { timeout: 60000 });
ok(true, 'a link runs as a job too, and its failure lands on the card');
ok(!readFileSync(`${DIR}/ws/beta/.git/config`, 'utf8').includes('[remote'),
   '...and no remote was added — the check comes before the configuration');
await page.click('#bJobOk');
ok(await post({ name: 'alpha', url: 'https://github.com/owner/alpha',
                key: 'github_testkey' }, '/api/link') === 400,
   'a repo that already has a remote is refused');
ok(await post({ name: 'oldproj', url: 'https://github.com/owner/oldproj',
                key: 'github_testkey' }, '/api/link') === 400,
   'a directory that is not a git repository is refused');
ok(await post({ name: 'nosuch', url: 'https://github.com/owner/x',
                key: 'github_testkey' }, '/api/link') === 400,
   'an unknown project is refused');
ok(await post({ name: 'beta', url: 'https://github.com/owner/beta' },
              '/api/link') === 400,
   'no PAT and no key is refused server-side too');

// ---- unlinking -----------------------------------------------------------
// The way off a host, and the only way onto another one: link refuses a repo
// that already has a remote, so this is the first half of moving. It is local
// and instant — nothing is asked of the server the project is leaving, which
// is one of the reasons to reach for it.
//
// alpha is the fixture with a remote and a seeded push grant. Its history is
// what the assertions are really about: unlinking must not touch a commit.
{
  const cfg = () => readFileSync(`${DIR}/ws/alpha/.git/config`, 'utf8');
  mkdirSync(`${DIR}/state/gitcreds`, { recursive: true });
  writeFileSync(`${DIR}/state/gitcreds/alpha`,
                'https://oauth2:ghp_ExampleTokenValue123@github.com\n');
  // Every ref and every object, listed. The fixture may or may not carry a
  // commit depending on which file ran before this one, so the invariant is
  // "whatever was here is still here" rather than a particular sha.
  const history = () => {
    try{
      return execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'rev-list', '--all'],
                          { encoding: 'utf8' }).trim()
        + '|' + readFileSync(`${DIR}/ws/alpha/README.md`, 'utf8');
    }catch{ return 'unreadable'; }
  };
  const before = history();
  ok(cfg().includes('[remote "origin"]'), 'alpha starts out linked');
  const u = await page.evaluate(async () => {
    const r = await fetch('/api/unlink', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'alpha' }) });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  });
  ok(u.status === 200 && !cfg().includes('[remote "origin"]'),
     'unlinking takes the remote off');
  ok(!existsSync(`${DIR}/state/gitcreds/alpha`),
     '...and the stored token with it, since it authenticated to a host this no longer talks to');
  ok(/push rights/.test((u.body.removed || []).join(' ')),
     '...and says the push grant went, which is what frees the repository');
  ok(history() === before && before !== 'unreadable',
     '...while every commit and every file is exactly where it was');
  ok(await page.evaluate(async () => {
    const r = await fetch('/api/unlink', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'alpha' }) });
    return r.status;
  }) === 400, 'unlinking twice says there is no remote rather than pretending');
  // ...and now it can be linked somewhere else, which is the whole point: the
  // refusal above was the only thing standing between this project and
  // another host. Refused here for the credential, not for the remote.
  const again = await post({ name: 'alpha', url: 'https://git.home.lan/owner/alpha',
                             forge: 'gitea' }, '/api/link');
  ok(again === 400,
     'an unlinked project is offered to another host — and asked for a credential');
  execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'remote', 'add', 'origin',
                       'git@github.com:owner/alpha.git']);
}

// ---- linking to another host: what can be checked without one ----------
// The Gitea, GitLab and Bitbucket paths cannot be exercised against a live
// server here (roadmap R43 is that proof), so what is checked is the part
// of them that is this code's rather than the host's: the credential line
// git will read, which owner a repository is created under, and a host
// remembered with its port.
{
  const out = execFileSync('python3', ['-c', `
import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, ${JSON.stringify(join(dirname(fileURLToPath(import.meta.url)), '..'))})
import forges, projects
tmp = tempfile.mkdtemp()
forges.configure(run=lambda *a, **k: {"code": 1, "out": ""}, state=tmp,
                 write_json=lambda p, d: Path(p).write_text(json.dumps(d)))
projects.STATE = Path(tmp)
out = {}
# a token with the characters git's store has to see percent-encoded
projects.write_token("p", "ab/cd+ef=@gh", "git.home.lan:3000", "http", "bob")
out["line"] = (Path(tmp) / "gitcreds" / "p").read_text().strip()
out["target"] = projects.token_target("p")
# where a repository is created: an org, or the token's own account, never
# somebody else's
calls = []
def ask(url, kind, token, data=None):
    calls.append(url)
    return (None, "not an org") if "/orgs/" in url else ({"ok": True}, "")
forges._ask = ask
gitea = forges.get("gitea")
out["own"] = forges.create_repo(gitea, "git.home.lan:3000", "t", "bob/app", "http", "bob")
out["own_calls"] = list(calls); calls.clear()
out["other"] = forges.create_repo(gitea, "git.home.lan:3000", "t", "alice/app", "http", "bob")
out["other_calls"] = list(calls)
# a host remembered with its port answers for the same host without one
forges.remember("git.home.lan:3000", "gitea")
out["forge"] = [forges.forge_of("git.home.lan:3000")["id"], forges.forge_of("git.home.lan")["id"]]
print(json.dumps(out))
`], { encoding: 'utf8' });
  const r = JSON.parse(out);
  ok(r.line === 'http://bob:ab%2Fcd%2Bef%3D%40gh@git.home.lan:3000',
     `a stored token is percent-encoded the way git's credential store reads it, under the remote's scheme, host and port (${r.line})`);
  ok(r.target?.scheme === 'http' && r.target?.host === 'git.home.lan:3000',
     '...and the scheme and host it was stored for can be read back, so switching a remote to it spells the URL the same way');
  ok(r.own === '' && r.own_calls.length === 2 && /\/user\/repos$/.test(r.own_calls[1]),
     'a repository under the token\'s own account is created there when the owner is not an organisation');
  ok(/alice is not an organisation/.test(r.other) && r.other_calls.length === 1,
     `...and one under somebody else is refused with the reason, never created under the wrong owner (${r.other})`);
  ok(r.forge[0] === 'gitea' && r.forge[1] === 'gitea',
     'a self-hosted forge remembered with its port is still Gitea when the same host is named without one');
}

// A rename that carries a new token in the same save: the token used to be
// written with no host at all, which was a 500 on every such save. It is
// stored for the remote's host and scheme, as a settings-only save does.
{
  const made = await postJson({ name: 'tokrn', mode: 'init' });
  ok(made.status === 200, `a project to rename (${made.status})`);
  execFileSync('git', ['-C', `${DIR}/ws/tokrn`, 'remote', 'add', 'origin',
                       'http://git.home.lan:3000/owner/tokrn.git']);
  const r = await page.evaluate(async () => {
    const x = await fetch('/api/rename', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: 'tokrn', to: 'tokrn2', token: 'gitea0123456789abcdef0123456789abcdef' }) });
    return { status: x.status, body: await x.json().catch(() => ({})) };
  });
  const line = existsSync(`${DIR}/state/gitcreds/tokrn2`)
    ? readFileSync(`${DIR}/state/gitcreds/tokrn2`, 'utf8').trim() : '';
  ok(r.status === 200 && /a new access token/.test((r.body.moved || []).join(' ')),
     `renaming with a new token in the same save works (${r.status}: ${JSON.stringify(r.body).slice(0, 120)})`);
  ok(/^http:\/\/oauth2:gitea0123456789abcdef0123456789abcdef@git\.home\.lan:3000$/.test(line),
     `...and the token is stored for the remote's host, port and scheme (${line.replace(/:[^@]*@/, ':…@')})`);
  rmSync(`${DIR}/ws/tokrn2`, { recursive: true, force: true });
  rmSync(`${DIR}/state/gitcreds/tokrn2`, { force: true });
}

// The refusals above are answered with 400s on purpose — and the deploy-key
// clone is made to fail with a 500 — and the browser logs each as a failed
// resource. Those lines are the tests passing, not a fault. Anything else is
// still a failure.
// ---- the bin -------------------------------------------------------------
// Deleting a project moves it to /workspace/.trash and every word on the page
// says so. This is the other half of that promise: seeing what is in there,
// putting one back, and — the only irreversible control on the page —
// destroying one.
mkdirSync(`${DIR}/ws/.trash/oldproj`, { recursive: true });
writeFileSync(`${DIR}/ws/.trash/oldproj/keep.txt`, 'still here\n');
// It has to be visible before it can be pressed. Keyed to `.eye` alone, the
// icon rule missed this button (an `.ic`) and its SVG got the browser
// default — fill:black, stroke:none — which draws nothing at all, because
// every path in it is an open stroke.
const binInk = await page.$eval('#bTrash svg', e => {
  const c = getComputedStyle(e);
  return { stroke: c.stroke, fill: c.fill, w: e.getBoundingClientRect().width };
});
ok(binInk.stroke !== 'none' && binInk.fill === 'none' && binInk.w >= 12,
   `the bin button's icon is actually drawn (stroke ${binInk.stroke}, fill ${binInk.fill}, ${binInk.w}px)`);
await page.click('#bTrash');
await page.waitForSelector('#tmodal:not([hidden])', { timeout: 10000 });
await page.waitForFunction(() => document.querySelector('#tList .trow'),
                           { timeout: 10000 });
ok(await page.$eval('#tList .trow', r => r.dataset.t) === 'oldproj',
   'the bin lists what was deleted, which nothing else on the page could show');

// Put back: a move, and the files come with it.
await page.click('#tList .trow[data-t="oldproj"] [data-trestore]');
await page.waitForFunction(() => !document.querySelector('#tList .trow[data-t="oldproj"]'),
                           { timeout: 10000 });
ok(existsSync(`${DIR}/ws/oldproj/keep.txt`) && !existsSync(`${DIR}/ws/.trash/oldproj`),
   '...and Put back is a move, so the files arrive with the name');

// Destroying one asks for the name to be typed. A click is not enough for the
// one control here with nothing behind it.
rmSync(`${DIR}/ws/oldproj`, { recursive: true, force: true });
mkdirSync(`${DIR}/ws/.trash/oldproj`, { recursive: true });
writeFileSync(`${DIR}/ws/.trash/oldproj/keep.txt`, 'still here\n');
await page.evaluate(() => drawTrash());
await page.waitForFunction(() => document.querySelector('#tList .trow[data-t="oldproj"]'),
                           { timeout: 10000 });
await page.click('#tList .trow[data-t="oldproj"] [data-tpurge]');
await page.waitForSelector('#tList .dropbox input', { timeout: 10000 });
ok(await page.$eval('#tList .dropbox .danger', b => b.disabled),
   'Delete for good is dead until the name is typed back');
await page.fill('#tList .dropbox input', 'gamm');
ok(await page.$eval('#tList .dropbox .danger', b => b.disabled),
   '...and stays dead for a near miss');
await page.fill('#tList .dropbox input', 'oldproj');
ok(!await page.$eval('#tList .dropbox .danger', b => b.disabled),
   '...and wakes on the name itself');
await page.click('#tList .dropbox .danger');
await page.waitForFunction(() => !document.querySelector('#tList .trow[data-t="oldproj"]'),
                           { timeout: 10000 });
ok(!existsSync(`${DIR}/ws/.trash/oldproj`),
   'and then it is gone, files and all — the one thing here with nothing after it');
await page.click('#tClose');
await page.waitForFunction(() => document.getElementById('tmodal').hidden);

const errs = page.errors.filter(e => !/status of (400|500)/.test(e));
ok(errs.length === 0, `zero console errors${errs.length ? ' — ' + errs.join(' | ') : ''}`);
await done(browser);
