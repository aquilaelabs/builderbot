// The Library (R170): one page under Build for everything a BuilderBot
// installs or runs on a node, as one list of one shape. Opens on the
// harness's stub node, a section per kind always drawn, the rows read from
// /api/library; the search and the chips narrow the list and save nothing;
// a row opens on its description; the verbs are the pages' own (an install
// is the toolchain job, which the bb stub runs in a second).
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- on the rail -------------------------------------------------------
ok(await page.evaluate(() => railGroups().some(g => g.key === 'build' && g.tools[0][0] === 'library') && railAllows('library')),
   'the Library is the Build group\'s first page');
ok(await page.evaluate(() => !railGroups().some(g => g.tools.some(([k]) => k === 'toolchains' || k === 'agents' || k === 'apps'))),
   '...and Toolchains, Agents and Apps are no longer pages of their own on the rail');

// ---- the page ----------------------------------------------------------
await page.evaluate(() => openLibrary());
await page.waitForSelector('.doc .librarytab #libNodeSel', { timeout: 20000 });
await page.waitForFunction(() => lib && !lib.nonode && Array.isArray(lib.rows), null, { timeout: 20000 });
ok(await page.evaluate(() => location.hash === '#/build/library/' + encodeURIComponent(libNode)),
   `the address names the page and its node (${await page.evaluate(() => location.hash)})`);
const sects = await page.$$eval('.doc .librarytab details.sect', ds => ds.map(d => d.dataset.sect));
ok(['library:agent', 'library:toolchain', 'library:pack', 'library:app', 'library:companion'].every(k => sects.includes(k)),
   `a section per kind, always drawn, in the page's order (${sects.join(', ')})`);
const shape = await page.evaluate(() => lib.rows.map(r => [r.kind, r.tier, typeof r.label, typeof r.about, typeof r.installed, typeof r.verb]));
ok(shape.length > 0 && shape.every(([k, t, l, a, i, v]) => ['agent', 'toolchain', 'pack', 'app', 'companion'].includes(k)
   && ['official', 'vetted', 'sideloaded'].includes(t) && l === 'string' && a === 'string' && i === 'boolean' && v === 'string'),
   `every row is one shape: kind, tier, label, about, installed, verb (${shape.length} rows)`);
ok(await page.evaluate(() => lib.rows.some(r => r.kind === 'toolchain') && document.querySelectorAll('.doc .librarytab .lrow').length === lib.rows.length),
   'the toolchain catalog is among the rows, and every row is drawn');
ok(await page.$$eval('.doc .librarytab .lrow .pill', ps => ps.some(p => /^(official|vetted|sideloaded)$/.test(p.textContent.trim()))),
   'the tier reads on a row as a pill');
ok(await page.evaluate(() => {
  const head = document.querySelector('.doc .librarytab .pghead');
  return !!head && /Installed/.test(head.textContent);
}), 'the head says how many are installed, the way a node\'s head does');

// ---- search and chips ----------------------------------------------------
const firstTc = await page.evaluate(() => lib.rows.find(r => r.kind === 'toolchain')?.label || '');
await page.fill('.doc .librarytab #libFind', firstTc.slice(0, 4).toLowerCase());
await page.waitForFunction(q => libQ === q, firstTc.slice(0, 4).toLowerCase());
ok(await page.evaluate(() => document.querySelectorAll('.doc .librarytab .lrow').length < lib.rows.length
   && document.querySelectorAll('.doc .librarytab .lrow').length > 0
   && document.activeElement?.id === 'libFind'),
   'the search narrows the rows as it is typed and keeps the caret');
await page.fill('.doc .librarytab #libFind', '');
await page.waitForFunction(() => libQ === '');
ok(await page.evaluate(() => document.querySelectorAll('.doc .librarytab .lrow').length === lib.rows.length), '...and emptied puts every row back');
if (await page.$('.doc .librarytab [data-libkind="toolchain"]')){
  await page.click('.doc .librarytab [data-libkind="toolchain"]');
  await page.waitForFunction(() => libKind === 'toolchain');
  ok(await page.evaluate(() => [...document.querySelectorAll('.doc .librarytab details.sect')].every(d => d.dataset.sect === 'library:toolchain')
     && document.querySelector('.doc .librarytab [data-libkind="toolchain"]').classList.contains('on')),
     'a kind chip shows that kind\'s section alone, the chip wearing .on');
  await page.click('.doc .librarytab [data-libkind=""]');
  await page.waitForFunction(() => libKind === '');
  ok(await page.$$eval('.doc .librarytab details.sect', ds => ds.length === 5), '...and All puts the five back');
} else ok(true, 'one kind only here, so no kind chips (chips need two groups)');

// ---- a row opens on its description -----------------------------------
{
  const key = await page.evaluate(() => document.querySelector('.doc .librarytab .lrow[data-lrow^="toolchain:"]')?.dataset.lrow || '');
  ok(!!key, `a toolchain row to open (${key})`);
  const sel = `.doc .librarytab .lrow[data-lrow="${key}"]`;
  ok(await page.$eval(sel, r => !r.classList.contains('open') && getComputedStyle(r.querySelector('.ldetail')).display === 'none'),
     'a row is shut on its one line until Details');
  await page.click(`${sel} [data-libmore]`);
  await page.waitForFunction(k => document.querySelector(`.doc .librarytab .lrow[data-lrow="${k}"]`)?.classList.contains('open'), key);
  ok(await page.$eval(sel, r => getComputedStyle(r.querySelector('.ldetail')).display !== 'none' && r.querySelector('[data-libmore]').textContent === 'Less'),
     '...and Details opens it on the description, the button reading Less');
}

// ---- the whole description (step 2) -----------------------------------------
// An app's row opens on its compose file with the blanks New container
// fills; a toolchain's on what it adds to a session and its terms.
{
  const app = await page.evaluate(() => document.querySelector('.doc .librarytab .lrow[data-lrow^="app:"]')?.dataset.lrow || '');
  if (app){
    await page.click(`.doc .librarytab .lrow[data-lrow="${app}"] [data-libmore]`);
    await page.waitForFunction(k => document.querySelector(`.doc .librarytab .lrow[data-lrow="${k}"]`)?.classList.contains('open'), app);
    ok(await page.$eval(`.doc .librarytab .lrow[data-lrow="${app}"]`, r => /image:/.test(r.querySelector('.libcompose')?.textContent || '')
       && r.querySelector('.ldetail code') && /Install opens New container/.test(r.querySelector('.ldetail').textContent)),
       `an app's row opens on its compose file, its blanks and how Install makes it a container (${app})`);
  } else ok(true, 'no app rows here (the account may not make containers)');
  const tc = await page.evaluate(() => {
    const r = lib.rows.find(x => x.kind === 'toolchain' && (x.tool || x.terms?.length));
    return r ? `toolchain:${r.name}` : '';
  });
  if (tc){
    if (!await page.$eval(`.doc .librarytab .lrow[data-lrow="${tc}"]`, r => r.classList.contains('open')))
      await page.click(`.doc .librarytab .lrow[data-lrow="${tc}"] [data-libmore]`);
    await page.waitForFunction(k => document.querySelector(`.doc .librarytab .lrow[data-lrow="${k}"]`)?.classList.contains('open'), tc);
    ok(await page.$eval(`.doc .librarytab .lrow[data-lrow="${tc}"] .ldetail`, d => /bb tool|Licensed|accept/.test(d.textContent)),
       `a toolchain's row opens on what it adds to a session and its terms (${tc})`);
  }
  const ag = await page.evaluate(() => document.querySelector('.doc .librarytab .lrow[data-lrow="agent:claude-code"]')?.dataset.lrow || '');
  if (ag){
    await page.click(`.doc .librarytab .lrow[data-lrow="${ag}"] [data-libmore]`);
    await page.waitForFunction(k => document.querySelector(`.doc .librarytab .lrow[data-lrow="${k}"]`)?.classList.contains('open'), ag);
    ok(await page.$eval(`.doc .librarytab .lrow[data-lrow="${ag}"] .ldetail`, d => /session account/.test(d.textContent) && !!d.querySelector('[data-signin]')),
       "Claude Code's row opens on its facts and this person's sign-in on the node");
  }
}

// ---- the verbs are the pages' own ------------------------------------------
// Install on a toolchain row that is not installed: the toolchain job on
// the node, which the stub agent answers at once (it fails the install, as
// the Toolchains page's node tests find), and the row then says what the
// job said: installed, or what failed under the row, as that page does.
{
  const name = await page.evaluate(() => lib.rows.find(r => r.kind === 'toolchain' && !r.installed && r.verb === 'install' && !r.wrong_platform)?.name || '');
  if (name){
    await page.click(`.doc .librarytab [data-libact="install"][data-libname="${name}"]`);
    await page.waitForFunction(n => lib.job && !lib.job.running && lib.job.action === 'install'
      && (lib.rows.find(r => r.kind === 'toolchain' && r.name === n)?.installed || lib.job.errors?.[n]), name, { timeout: 60000 });
    const said = await page.evaluate(n => ({installed: !!lib.rows.find(r => r.kind === 'toolchain' && r.name === n)?.installed, err: lib.job.errors?.[n] || ''}), name);
    ok(true, `Install on ${name} ran the toolchain job on the node (${said.installed ? 'installed' : said.err})`);
    ok(await page.$eval(`.doc .librarytab .lrow[data-lrow="toolchain:${name}"]`, (r, s) => s.installed ? !!r.querySelector('[data-libact="remove"]')
       : r.querySelector('.sub.bad')?.textContent === s.err, said),
       said.installed ? '...and an installed row offers Remove' : '...and what failed is said under the row');
  } else ok(true, 'nothing uninstalled to install on the stub');
}
// Install on an app row opens New container with that app picked.
if (await page.$('.doc .librarytab [data-libkind="app"][data-libact="install"]')){
  const id = await page.$eval('.doc .librarytab [data-libkind="app"][data-libact="install"]', b => b.dataset.libname);
  await page.click('.doc .librarytab [data-libkind="app"][data-libact="install"]');
  await page.waitForFunction(() => !document.getElementById('cmodal').hidden, null, { timeout: 10000 });
  await page.waitForFunction(id => document.getElementById('cApp').value === id && !document.getElementById('cAppFields').hidden, id, { timeout: 10000 });
  ok(true, `Install on an app opens New container with ${id} picked and its blanks shown`);
  await page.evaluate(() => { $('cmodal').hidden = true; });
}

// ---- no node ---------------------------------------------------------------
await page.evaluate(() => { nodesList = []; libNode = ''; lib = null; loadLibrary(); });
await page.waitForSelector('.doc .librarytab .libnone', { timeout: 20000 });
ok(await page.evaluate(() => !document.querySelector('.doc .librarytab .lrow') && !document.querySelector('#libNodeSel')),
   'with no node enrolled it says to enroll one, and offers nothing');
await page.evaluate(() => { nodesList = null; nodesStale = true; libNode = ''; lib = null; loadLibrary(); });
await page.waitForSelector('.doc .librarytab #libNodeSel', { timeout: 20000 });

await done(browser);
