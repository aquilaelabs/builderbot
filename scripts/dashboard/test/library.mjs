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
await page.waitForSelector('.pane .bar #ndPick', { timeout: 20000 });
await page.waitForFunction(() => lib && !lib.nonode && Array.isArray(lib.rows), null, { timeout: 20000 });
// ...pushed by the draw that follows the read, so waited for.
ok(await page.waitForFunction(() => location.hash === '#/build/library/' + encodeURIComponent(libNode), null, { timeout: 10000 }).then(() => true, () => false),
   `the address names the page and its node (${await page.evaluate(() => location.hash)})`);
const sects = await page.$$eval('.doc .librarytab .libgroup', ds => ds.map(d => d.dataset.libgroup));
const hasPacks = await page.evaluate(() => lib.rows.some(r => libGroup(r) === 'pack'));
ok(['agent', 'toolchain', 'app', 'companion'].every(k => sects.includes(k)) && sects.includes('pack') === hasPacks,
   `a group of cards per kind, in the page's order, Tool packs only when there are any (${sects.join(', ')})`);
// No pack at all is no Tool packs group, its hint and empty line with it
// (the operator, 29 Oct); the Tool packs chip still opens it, empty.
ok(await page.evaluate(async () => {
  const keep = lib.rows;
  lib = {...lib, rows: keep.filter(r => libGroup(r) !== 'pack'), catalog_error: 'no index'};
  libRev++; drawPanes(); await new Promise(r => setTimeout(r, 300));
  const gone = !document.querySelector('.doc .librarytab .libgroup[data-libgroup="pack"]');
  libKind = 'pack'; libRev++; drawPanes(); await new Promise(r => setTimeout(r, 300));
  const chip = !!document.querySelector('.doc .librarytab .libgroup[data-libgroup="pack"] .empty');
  libKind = ''; lib = {...lib, rows: keep, catalog_error: ''}; libRev++; drawPanes(); await new Promise(r => setTimeout(r, 300));
  return gone && chip;
}), 'with no tool pack the Tool packs group is not drawn, and its chip still opens it empty');
const shape = await page.evaluate(() => lib.rows.map(r => [r.kind, r.tier, typeof r.label, typeof r.about, typeof r.installed, typeof r.verb]));
ok(shape.length > 0 && shape.every(([k, t, l, a, i, v]) => ['agent', 'toolchain', 'pack', 'service', 'app', 'companion'].includes(k)
   && ['official', 'vetted', 'sideloaded'].includes(t) && l === 'string' && a === 'string' && i === 'boolean' && v === 'string'),
   `every row is one shape: kind, tier, label, about, installed, verb (${shape.length} rows)`);
ok(await page.evaluate(() => lib.rows.some(r => r.kind === 'toolchain') && document.querySelectorAll('.doc .librarytab .lcard').length === lib.rows.filter(r => !r.wrong_platform).length),
   'the toolchain catalog is among the rows, and every row for this node is drawn');
ok(await page.evaluate(() => {
  const off = lib.rows.filter(r => r.wrong_platform);
  const head = document.querySelector('.doc .librarytab .pghead')?.textContent || '';
  return off.length > 0 && off.every(r => !document.querySelector(`.doc .librarytab .lcard[data-lrow="${r.kind}:${r.name}"]`))
    && new RegExp(`Not for this node\\s*${off.length}\\b`).test(head);
}), 'a card not for this node is not drawn, and the head counts them (R170 step 9)');
ok(await page.$$eval('.doc .librarytab .lcard .lcmeta .pill', ps => ps.some(p => /^(official|vetted|sideloaded)$/.test(p.textContent.trim()))),
   'the tier reads on a card as a pill');
ok(await page.evaluate(() => {
  const head = document.querySelector('.doc .librarytab .pghead');
  return !!head && /Installed/.test(head.textContent);
}), 'the head says how many are installed, the way a node\'s head does');

// ---- search and chips ----------------------------------------------------
const firstTc = await page.evaluate(() => lib.rows.find(r => r.kind === 'toolchain')?.label || '');
await page.fill('.doc .librarytab #libFind', firstTc.slice(0, 4).toLowerCase());
await page.waitForFunction(q => libQ === q, firstTc.slice(0, 4).toLowerCase());
ok(await page.evaluate(() => document.querySelectorAll('.doc .librarytab .lcard').length < lib.rows.length
   && document.querySelectorAll('.doc .librarytab .lcard').length > 0
   && document.activeElement?.id === 'libFind'),
   'the search narrows the rows as it is typed and keeps the caret');
await page.fill('.doc .librarytab #libFind', '');
await page.waitForFunction(() => libQ === '');
ok(await page.evaluate(() => document.querySelectorAll('.doc .librarytab .lcard').length === lib.rows.filter(r => !r.wrong_platform).length), '...and emptied puts every row back');
if (await page.$('.doc .librarytab [data-libkind="toolchain"]')){
  await page.click('.doc .librarytab [data-libkind="toolchain"]');
  await page.waitForFunction(() => libKind === 'toolchain');
  ok(await page.evaluate(() => [...document.querySelectorAll('.doc .librarytab .libgroup')].every(d => d.dataset.libgroup === 'toolchain')
     && document.querySelector('.doc .librarytab [data-libkind="toolchain"]').classList.contains('on')),
     'a kind chip shows that kind\'s group alone, the chip wearing .on');
  await page.click('.doc .librarytab [data-libkind=""]');
  await page.waitForFunction(() => libKind === '');
  ok(await page.$$eval('.doc .librarytab .libgroup', (ds, n) => ds.length === n, sects.length), '...and All puts every group back');
} else ok(true, 'one kind only here, so no kind chips (chips need two groups)');

// Installed, the chip after All (the operator, 29 Oct): the cards
// installed on this node, each in its own kind's section; no chip while
// nothing is.
if (await page.evaluate(() => lib.rows.some(r => r.installed && !r.wrong_platform))){
ok(await page.evaluate(() => {
  const cs = [...document.querySelectorAll('.doc .librarytab [data-chips="libkind"] .chip')];
  return cs[1]?.dataset.libkind === 'installed' && /^Installed/.test(cs[1].textContent.trim());
}), 'Installed is the chip after All');
await page.click('.doc .librarytab [data-libkind="installed"]');
await page.waitForFunction(() => libKind === 'installed');
ok(await page.evaluate(() => {
  const cards = [...document.querySelectorAll('.doc .librarytab .lcard')];
  return cards.length > 0 && cards.length === lib.rows.filter(r => r.installed && !r.wrong_platform).length
    && cards.every(c => lib.rows.find(r => `${r.kind}:${r.name}` === c.dataset.lrow)?.installed);
}), '...and pressed it shows what is installed here and nothing else');
await page.click('.doc .librarytab [data-libkind=""]');
await page.waitForFunction(() => libKind === '');
} else ok(!(await page.$('.doc .librarytab [data-libkind="installed"]')), 'nothing installed here, so no Installed chip');

// Updates, the chip after Installed (the operator, 29 Oct): the cards with an
// update due, each in its own section, and no chip while none is.
if (await page.evaluate(() => lib.rows.some(r => r.update && !r.wrong_platform))){
  ok(await page.evaluate(() => {
    const cs = [...document.querySelectorAll('.doc .librarytab [data-chips="libkind"] .chip')];
    const at = cs.findIndex(c => c.dataset.libkind === 'update');
    return at > 0 && at <= 2 && cs.slice(1, at).every(c => c.dataset.libkind === 'installed') && /^Updates/.test(cs[at].textContent.trim());
  }), 'Updates is the chip after Installed while an update is due');
  await page.click('.doc .librarytab [data-libkind="update"]');
  await page.waitForFunction(() => libKind === 'update');
  ok(await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.doc .librarytab .lcard')];
    return cards.length === lib.rows.filter(r => r.update && !r.wrong_platform).length
      && cards.every(c => lib.rows.find(r => `${r.kind}:${r.name}` === c.dataset.lrow)?.update);
  }), '...and pressed it shows the cards with an update due and no others');
  await page.click('.doc .librarytab [data-libkind=""]');
  await page.waitForFunction(() => libKind === '');
} else ok(!(await page.$('.doc .librarytab [data-libkind="update"]')), 'no update due here, so no Updates chip');

// ---- Details opens the entry's own page (R183) ------------------------------
// A card stays a card; Details opens that entry's page, a page a press opens
// with the small top header's Back to the Library, its body what Details
// says: the catalog's entry alone.
const ENTRY = k => `.doc .entrytab [data-entry="${k}"]`;
const toEntry = async k => {
  await page.evaluate(k => openEntry(libNode, k), k);
  await page.waitForSelector(`${ENTRY(k)} .ldetail`, { timeout: 15000 });
};
const toLibrary = async () => {
  await page.evaluate(() => openLibrary());
  await page.waitForSelector('.doc .librarytab .lcard', { timeout: 15000 });
};
{
  const key = await page.evaluate(() => document.querySelector('.doc .librarytab .lcard[data-lrow^="toolchain:"]')?.dataset.lrow || '');
  ok(!!key, `a toolchain card to open (${key})`);
  const sel = `.doc .librarytab .lcard[data-lrow="${key}"]`;
  ok(await page.$eval(sel, r => !r.querySelector('.ldetail') && r.querySelector('[data-libmore]').textContent === 'Details'),
     'a card is its name and two lines, with Details, and opens nothing in place');
  await page.click(`${sel} [data-libmore]`);
  await page.waitForSelector(`${ENTRY(key)} .ldetail`, { timeout: 15000 });
  const pg = await page.evaluate(k => ({ hash: location.hash, want: '#/build/library/' + encodeURIComponent(libNode) + '/' + encodeURIComponent(k),
    back: document.querySelector('.pane .bar .backhead [data-shellback]')?.textContent.trim() || '',
    name: document.querySelector('.pane .bar .backhead .backof')?.textContent.trim() || '',
    label: lib.rows.find(r => `${r.kind}:${r.name}` === k)?.label || '' }), key);
  ok(pg.hash === pg.want && /Library/.test(pg.back) && pg.name === pg.label,
     `...Details opens the entry's own page at its own address, its top header's Back to the Library and its name (${JSON.stringify(pg)})`);
  await page.click('.pane .bar [data-shellback]');
  await page.waitForFunction(() => tabOf(panes[0])?.kind === 'library', null, { timeout: 10000 });
  ok(true, '...and Back returns to the Library');
}

// ---- the whole description (step 2) -----------------------------------------
// An app's page holds its compose file with the blanks New container fills;
// a toolchain's what it adds to a session and its terms.
{
  const app = await page.evaluate(() => lib.rows.find(r => r.kind === 'app' && !r.wrong_platform) ? `app:${lib.rows.find(r => r.kind === 'app' && !r.wrong_platform).name}` : '');
  if (app){
    await toEntry(app);
    ok(await page.$eval(ENTRY(app), r => /image:/.test(r.querySelector('.libcompose')?.textContent || '')
       && r.querySelector('.ldetail code') && /New container opens the Containers page/.test(r.querySelector('.ldetail').textContent)),
       `an app's page holds its compose file, its blanks and how New container makes it one (${app})`);
  } else ok(true, 'no app rows here (the account may not make containers)');
  const tc = await page.evaluate(() => {
    const r = lib.rows.find(x => x.kind === 'toolchain' && (x.tool || x.terms?.length));
    return r ? `toolchain:${r.name}` : '';
  });
  if (tc){
    await toEntry(tc);
    ok(await page.$eval(`${ENTRY(tc)} .ldetail`, d => /bb tool|Licensed|accept/.test(d.textContent)),
       `a toolchain's page says what it adds to a session and its terms (${tc})`);
  }
  if (await page.evaluate(() => lib.rows.some(r => r.kind === 'agent' && r.name === 'claude-code'))){
    await toEntry('agent:claude-code');
    ok(await page.$eval(`${ENTRY('agent:claude-code')} .ldetail`, d => /session account/.test(d.textContent) && /Installed page/.test(d.textContent) && !d.querySelector('[data-signin]')),
       "Claude Code's page holds its facts, pointing at the Installed page for this person's sign-in (R172: the Library is the catalog)");
  }
  await toLibrary();
}

// ---- the verbs are the pages' own ------------------------------------------
// Install on a toolchain row that is not installed: the toolchain job on
// the node, which the stub agent answers at once (it fails the install, as
// toolchains.mjs's node tests find), and the row then says what the
// job said: installed, or what failed under the row, as that page does.
{
  const name = await page.evaluate(() => lib.rows.find(r => r.kind === 'toolchain' && !r.installed && r.verb === 'install' && !r.wrong_platform)?.name || '');
  if (name){
    await page.click(`.doc .librarytab [data-libact="install"][data-libname="${name}"]`);
    await page.waitForFunction(n => lib.job && !lib.job.running && lib.job.action === 'install'
      && (lib.rows.find(r => r.kind === 'toolchain' && r.name === n)?.installed || lib.job.errors?.[n]), name, { timeout: 60000 });
    const said = await page.evaluate(n => ({installed: !!lib.rows.find(r => r.kind === 'toolchain' && r.name === n)?.installed, err: lib.job.errors?.[n] || ''}), name);
    ok(true, `Install on ${name} ran the toolchain job on the node (${said.installed ? 'installed' : said.err})`);
    ok(await page.$eval(`.doc .librarytab .lcard[data-lrow="toolchain:${name}"]`, (r, s) => s.installed ? !!r.querySelector('[data-libact="remove"]')
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
  ok(await page.$eval('.doc .librarytab [data-libkind="app"][data-libact="install"]', b => b.textContent.trim() === 'New container'),
     `an app's press reads New container, and opens that dialog with ${id} picked and its blanks shown`);
  await page.evaluate(() => { $('cmodal').hidden = true; });
}

// ---- the bar's Check for updates (step 5) ------------------------------------
// The check is the Toolchains job's: the bar says it is checking while it
// runs, and the head says when versions were last checked once it ends.
{
  await page.click('.doc .librarytab [data-libcheck]');
  await page.waitForFunction(() => lib?.job?.action === 'check' && !lib.job.running, null, { timeout: 60000 });
  ok(await page.$eval('.doc .librarytab [data-libcheck]', b => !b.disabled && /check/i.test(b.textContent)),
     'Check for updates runs the check job on the node and the bar comes back');
  // The stub's check leaves no time on the node's record, so the fact is
  // drawn only where the node has one; a fact with nothing to say is left out.
  // ...drawn on the paint after the read lands, so waited for rather than read at once.
  const when = await page.waitForFunction(() => {
    const said = /Versions checked/.test(document.querySelector('.doc .librarytab .pghead')?.textContent || '');
    return said === !!(lib.store?.checked) ? {checked: lib.store?.checked || 0, said} : null;
  }, null, { timeout: 10000 }).then(h => h.jsonValue());
  ok(when.said === !!when.checked, `...and the head says when versions were checked only once the node has a time (${when.checked ? 'said' : 'none yet, not drawn'})`);
}

// ---- Add your own: an app of the person's own (step 3) -----------------------
// The bar's Add your own opens one dialog for a tool pack or an app; an app
// is a compose file with the known blanks, looked at before it is kept,
// offered on an Apps card as sideloaded with Edit, and in New container.
{
  const COMPOSE = 'services:\n  notes:\n    image: ghcr.io/example/notes:2.4.1\n    ports:\n      - "${PORT}:8080"\n    volumes:\n      - ${DATA}/notes:/data\n';
  await page.evaluate(async () => { await postJSON('/api/nasapps', {action: 'remove', app: 'notes'}); });   // a run cut short may have left it
  await page.click('.doc .librarytab [data-libadd]');
  await page.waitForSelector('#tpmodal:not([hidden]) [data-tpwhat="app"]', { timeout: 10000 });
  ok(await page.$eval('#tpmodal h3', h => h.textContent === 'Add your own'), 'Add your own opens the one dialog, asking what is being added');
  await page.click('#tpmodal [data-tpwhat="app"]');
  await page.waitForSelector('#tpmodal #tpAppCompose');
  await page.fill('#tpmodal #tpAppName', 'Notes');
  await page.fill('#tpmodal #tpAppId', 'notes');
  await page.fill('#tpmodal #tpAppWhat', 'a notebook with a web page');
  await page.fill('#tpmodal #tpAppPort', '8080');
  await page.fill('#tpmodal #tpAppCompose', 'services:\n  notes:\n    image: ghcr.io/example/notes:latest\n');
  await page.click('#tpmodal [data-tplook]');
  await page.waitForFunction(() => tpForm.error || tpForm.seen, null, { timeout: 10000 });
  ok(await page.evaluate(() => /not pinned/.test(tpForm.error) && !document.querySelector('#tpmodal [data-tpadd]')),
     'Look refuses an image that is not pinned to a tag, and nothing can be added until it is');
  await page.fill('#tpmodal #tpAppCompose', COMPOSE);
  await page.click('#tpmodal [data-tplook]');
  await page.waitForSelector('#tpmodal [data-tpadd]', { timeout: 10000 });
  ok(await page.$eval('#tpmodal .tpseen', d => /notes/.test(d.textContent) && /ghcr.io\/example\/notes:2.4.1/.test(d.textContent) && /DATA/.test(d.textContent)),
     '...and a good one is shown as what it runs and the blanks it takes before Add');
  await page.click('#tpmodal [data-tpadd]');
  await page.waitForFunction(() => document.getElementById('tpmodal').hidden && lib?.rows.some(r => r.kind === 'app' && r.name === 'notes'), null, { timeout: 15000 });
  ok(await page.$eval('.doc .librarytab .lcard[data-lrow="app:notes"]', c => /sideloaded/.test(c.querySelector('.lcmeta').textContent)
     && !!c.querySelector('[data-libact="edit"]') && !!c.querySelector('[data-libact="install"]')),
     'Add keeps it: an Apps card wearing sideloaded, with Install and Edit');
  const offered = await page.evaluate(async () => { cApps = null; return (await loadNasApps()).some(a => a.id === 'notes' && a.tier === 'sideloaded'); });
  ok(offered, '...and New container offers it among the apps');
  await page.click('.doc .librarytab .lcard[data-lrow="app:notes"] [data-libact="edit"]');
  await page.waitForFunction(() => !document.getElementById('tpmodal').hidden && document.querySelector('#tpmodal #tpAppCompose')?.value.includes('notes:2.4.1'), null, { timeout: 10000 });
  ok(await page.$eval('#tpmodal #tpAppId', i => i.disabled && i.value === 'notes'), 'Edit opens it as kept, its id fixed');
  await page.click('#tpmodal [data-tprmapp]');
  await page.waitForSelector('.modal.askdlg:not([hidden]) [data-ai="0"]', { timeout: 10000 });
  // The ask slides in, so it is pressed by the page rather than by a pointer waiting for it to settle.
  await page.evaluate(() => document.querySelector('.modal.askdlg:not([hidden]) [data-ai="0"]').click());
  await page.waitForFunction(() => document.getElementById('tpmodal').hidden && !lib?.rows.some(r => r.kind === 'app' && r.name === 'notes'), null, { timeout: 15000 });
  ok(true, 'Remove in there takes it off the catalog, and the card goes');
}

// ---- a service's card: the catalog's entry alone (R172) ----------------------
// The model router is a Services card whose Install is dead until something
// is behind it, set on the Installed page; its Details show the entry and
// draw no Configure of their own.
{
  const RT = '.doc .librarytab .lcard[data-lrow="service:model-router"]';
  ok(await page.$(RT) !== null && await page.$eval(RT, c => /official/.test(c.querySelector('.lcmeta').textContent) && c.querySelector('[data-libact="install"]')?.disabled === true),
     'the model router is a Services card, official, its Install dead while nothing is behind it');
  await toEntry('service:model-router');
  ok(await page.$eval(ENTRY('service:model-router'), c => !c.querySelector('.lcform') && !c.querySelector('[data-signin]') && /Installed page/.test(c.querySelector('.ldetail').textContent)),
     '...and its page is the entry alone, pointing at the Installed page for what is set per node');
  await toLibrary();
}

// ---- no node ---------------------------------------------------------------
await page.evaluate(() => { nodesList = []; libNode = ''; lib = null; loadLibrary(); });
await page.waitForSelector('.doc .librarytab .libnone', { timeout: 20000 });
ok(await page.evaluate(() => !document.querySelector('.doc .librarytab .lcard') && !document.querySelector('.pane .bar #ndPick')),
   'with no node enrolled it says to enroll one, and offers nothing');
await page.evaluate(() => { nodesList = null; nodesStale = true; libNode = ''; lib = null; loadLibrary(); });
await page.waitForSelector('.pane .bar #ndPick', { timeout: 20000 });

await done(browser);
