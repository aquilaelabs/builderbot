// The Installed page (R172): under Machines beside Nodes and Storage, one
// node picked, what the Library put there by kind, each row opening on
// what the catalog's card does not show: an agent's sign-in, a toolchain's
// path and system packages, a service's Configure from its config block
// (the model router's providers, endpoints, Ollama and projects, saved to
// the router's own record), and Remove.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- on the rail -------------------------------------------------------
ok(await page.evaluate(() => railGroups().some(g => g.key === 'machines' && g.tools.some(([k]) => k === 'installed')) && railAllows('installed')),
   'Installed is a page under Machines, beside Nodes and Storage');

// ---- the page ----------------------------------------------------------
await page.evaluate(() => openInstalledTab());
await page.waitForSelector('.pane .bar #ndPick', { timeout: 20000 });
await page.waitForFunction(() => inst && !inst.nonode && Array.isArray(inst.rows), null, { timeout: 20000 });
ok(await page.waitForFunction(() => location.hash === '#/machines/installed/' + encodeURIComponent(instNode), null, { timeout: 10000 }).then(() => true, () => false),
   `the address names the page and its node (${await page.evaluate(() => location.hash)})`);
const sects = await page.$$eval('.doc .installedtab details.sect', ds => ds.map(d => d.dataset.sect));
ok(sects.includes('installed:agent') && sects.includes('installed:service') && !sects.includes('installed:app'),
   `a section per kind with anything on the node, never apps or companions (${sects.join(', ')})`);
ok(await page.evaluate(() => inst.rows.filter(r => r.kind === 'agent' && !r.installed && r.agent !== 'claude').length > 0
   && [...document.querySelectorAll('.doc .installedtab .irow[data-irow^="agent:"]')].every(e => { const r = inst.rows.find(x => `${x.kind}:${x.name}` === e.dataset.irow); return r.installed || r.agent === 'claude'; })),
   'an agent not installed is not a row, but Claude Code is, so a sign-in has a place');
ok(await page.$$eval('.doc .installedtab [data-instact="install"]', bs => bs.every(b => b.dataset.instkind === 'service')) && await page.$('.doc .installedtab [data-libact]') === null,
   'nothing installs from here but a configured service: the Library installs');

// ---- an agent's row: its sign-in --------------------------------------------
{
  const CL = '.doc .installedtab .irow[data-irow="agent:claude-code"]';
  await page.click(`${CL} [data-instmore]`);
  await page.waitForSelector(`${CL}.open [data-signin][data-siagent="claude"]`, { timeout: 10000 });
  ok(await page.$eval(`${CL}.open`, r => /session account/.test(r.querySelector('.idetail').textContent)),
     "Claude Code's row opens on its facts and this person's sign-in on the node");
  await page.click(`${CL} [data-instmore]`);
}

// ---- the model router's row: Configure, saved to its own record ------------
{
  const RT = '.doc .installedtab .irow[data-irow="service:model-router"]';
  ok(await page.$(RT) !== null && await page.$eval(RT, r => r.querySelector('[data-instact="install"]')?.disabled === true),
     'the model router is a Services row, its Install dead while nothing is behind it');
  await page.click(`${RT} [data-instmore]`);
  await page.waitForSelector(`${RT}.open .icform`, { timeout: 10000 });
  const fields = await page.$$eval(`${RT} .icform [data-icf], ${RT} .icform [data-icadd], ${RT} .icform [data-icproj]`, es => es.map(e => e.dataset.icf || e.dataset.icadd || `proj:${e.value}`));
  ok(fields.includes('anthropic') && fields.includes('openai') && fields.includes('ollama') && fields.includes('custom') && fields.some(f => f.startsWith('proj:')),
     `its Configure form is the pack's config block: the providers' keys, the endpoints, Ollama and the projects (${fields.join(', ')})`);
  await page.fill(`${RT} .icform [data-icf="anthropic"]`, 'sk-ant-test-0000');
  await page.click(`${RT} .icform [data-icadd="custom"]`);
  await page.waitForSelector(`${RT} .icform .icrow[data-iclist="custom"]`, { timeout: 5000 });
  ok(await page.$eval(`${RT} .icform [data-icf="anthropic"]`, i => i.value === 'sk-ant-test-0000'), 'a row added keeps what was typed, as a draft');
  await page.fill(`${RT} .icform .icrow [data-icsub="name"]`, 'groq');
  await page.fill(`${RT} .icform .icrow [data-icsub="base"]`, 'https://api.groq.com/openai/v1');
  await page.fill(`${RT} .icform .icrow [data-icsub="key"]`, 'gsk-test');
  await page.click(`${RT} .icform [data-icsave]`);
  await page.waitForFunction(() => { const r = inst?.rows.find(x => x.kind === 'service'); return r && r.values.anthropic === true && r.values.custom.length === 1; }, null, { timeout: 15000 });
  const saved = await page.evaluate(() => { const r = inst.rows.find(x => x.kind === 'service'); return { anthropic: r.values.anthropic, custom: r.values.custom, ready: r.ready }; });
  ok(saved.anthropic === true && saved.custom[0].name === 'groq' && saved.custom[0].key === true && saved.ready === '',
     `Save keeps the key sealed and shows it only as set, the endpoint with its key as set, and the service is ready to deploy (${JSON.stringify(saved)})`);
  ok(await page.$eval(`${RT} .icform [data-icf="anthropic"]`, i => i.value === '' && /type to replace/.test(i.placeholder))
     && await page.$eval(`${RT} [data-instact="install"]`, b => !b.disabled),
     '...the field empties with "type to replace" in its place, and Install comes live');
  const st = await page.evaluate(async () => (await (await fetch('/api/router?node=' + encodeURIComponent(instNode))).json()));
  ok(st.providers?.anthropic === true && st.custom?.[0]?.name === 'groq', 'what the row saved is the router\'s own record');
  // ...and the Library's card for it says Install is live now, its Details the entry alone.
  await page.evaluate(() => { libNode = instNode; lib = null; openLibrary(); });
  await page.waitForFunction(() => lib && Array.isArray(lib.rows), null, { timeout: 20000 });
  ok(await page.$eval('.doc .librarytab .lcard[data-lrow="service:model-router"]', c => !c.querySelector('[data-libact="install"]').disabled && !c.querySelector('.lcform')),
     'the Library\'s card for it offers Install now and draws no Configure of its own');
}

// ---- no node ---------------------------------------------------------------
await page.evaluate(() => { openInstalledTab(); nodesList = []; instNode = ''; inst = null; loadInstalled(); });
await page.waitForSelector('.doc .installedtab .instnone', { timeout: 20000 });
ok(await page.evaluate(() => !document.querySelector('.doc .installedtab .irow') && !document.querySelector('.pane .bar #ndPick')),
   'with no node enrolled it says to enroll one');
await page.evaluate(() => { nodesList = null; nodesStale = true; instNode = ''; inst = null; loadInstalled(); });
await page.waitForSelector('.pane .bar #ndPick', { timeout: 20000 });

await done(browser);
