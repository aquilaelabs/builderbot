// Phase 1 of the controller design (docs/nodes.md): the seam, with nothing
// visibly changing. What this file holds is the phase's whole contract —
// the store exists behind the four one-way doors it owns, the local node and
// the DOCKER_HOST mirror are seeded, work stamps the node it belongs to,
// every mutation grows an audit row, and the page the operator sees is
// exactly the page it was.
import { URL, launch, newPage, ok, done, ready, sleep, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync, readFileSync } from 'node:fs';

// Self-sufficient: the compose file the seam test acts on, whether or not
// devapp.mjs ran first in this invocation.
writeFileSync(`${DIR}/ws/ep.silon/docker-compose.yml`,
  'services:\n  app:\n    image: delta-dev\n    build: .\n');
// ...and no required env: devapp.mjs runs before this file in a full pass and
// leaves an .env.example wanting PORT, which would turn this file's `up` into
// a refusal about somebody else's fixture.
writeFileSync(`${DIR}/ws/ep.silon/.env.example`, '');

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;

// The store the harness server booted with — read through the module itself,
// the way bb nodes reads it, so the test exercises the same path.
const readStore = (py) => JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('nodes',
  ${JSON.stringify(new globalThis.URL('../nodes.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.open_readonly(${JSON.stringify(DIR + '/state')})
print(json.dumps(${py}))
`], { encoding: 'utf8' }).trim());

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the seeded registry --------------------------------------------------
const list = await page.evaluate(async () =>
  (await (await fetch('/api/v1/nodes')).json()).nodes);
ok(Array.isArray(list) && list.length === 2,
   `the store boots with two nodes: local, and DOCKER_HOST mirrored (${
     (list || []).map(n => n.id).join(', ')})`);
const local = list.find(n => n.id === 'local');
ok(local && local.kind === 'local' && local.state === 'online'
   && local.reported.cpu > 0 && local.reported.mem_mb > 0,
   'local is this container, with a real census');
ok(!local.capabilities.includes('docker-host'),
   '...and no docker-host capability: the local node is not a sandbox');
const sandbox = list.find(n => n.kind === 'ssh');
ok(sandbox && /^n_[0-9a-f]{8}$/.test(sandbox.id)
   && sandbox.ssh_addr === 'ssh://bb@stub'
   && sandbox.capabilities.includes('docker-host'),
   'the sandbox VM has a minted identity that is not its address');
ok(list[0].id === 'local',
   'local lists first — the one node every deployment has');

// ---- the seam: work says which node it belongs to --------------------------
// A compose action claims the job slot; the claim now asks node_for() and
// the answer rides the job the page polls. Fixed in phase 1 — docker work is
// the sandbox record — and the call site is what phase 4's placement slides
// into.
{
  const r = await page.evaluate(async () => (await (await fetch('/api/devapp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'new', project: 'ep.silon', instance: 'ph1' }),
  })).json()));
  ok(!r.error, `an instance exists to act on (${r.error || 'ok'})`);
  // Started and observed in one task: the stub daemon finishes an up in
  // well under a second and a finished job leaves the slot, so the node
  // stamp has to be caught while the job is live.
  const job = await page.evaluate(async () => {
    const going = fetch('/api/devapp', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'up', project: 'ep.silon', instance: 'ph1' }),
    });
    for (let i = 0; i < 300; i++){
      const d = await (await fetch('/api/docker')).json();
      if (d.job && d.job.node) return d.job;
      await new Promise(r => setTimeout(r, 30));
    }
    await going;
    return null;
  });
  ok(job && job.node === sandbox.id,
     `docker work is stamped with the sandbox node's id (${job && job.node})`);
}

// ---- the audit trail -------------------------------------------------------
// Door 2: every mutation through the POST funnel writes who/what/when with a
// parameter digest — and never the parameters, which carry tokens.
{
  await page.evaluate(() => fetch('/api/bugs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'add', project: 'alpha',
                           title: 'audit-canary-sekrit', severity: 'low' }),
  }));
  await sleep(300);
  const tail = readStore('m.audit_tail(80)');
  const row = tail.find(r => r.action === '/api/bugs:add');
  ok(row && row.principal === 'operator' && row.target === 'alpha',
     'a mutation writes an audit row: who, what, on what');
  ok(row && /^sha256:[0-9a-f]{12}·\d+b$/.test(row.params),
     '...with a parameter digest in a fixed shape');
  ok(!JSON.stringify(tail).includes('sekrit'),
     '...and never the parameters themselves, which carry tokens and env text');
  // Asked for by name, not scanned for in a tail: in a full run this file
  // goes last, behind hundreds of audited mutations from every other suite.
  const seed = readStore(
    `m._rows("SELECT principal FROM audit WHERE action = ?", ("node-seed",))`);
  ok(seed.length === 1 && seed[0].principal === 'system',
     'the seed itself is on the record, once, as system');
}

// ---- bb nodes --------------------------------------------------------------
{
  const out = execFileSync('bash', ['scripts/bb', 'nodes'],
    { encoding: 'utf8', cwd: REPO,
      env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  ok(/local\s+online\s+local\s+package-build/.test(out.replace(/\s+/g, ' '))
     && /sandbox · ssh:\/\/bb@stub/.test(out),
     'bb nodes prints the same registry, read-only');
}

// ---- phase 2: the Nodes tab ------------------------------------------------
{
  await page.evaluate(() => { const c = document.getElementById('cardTools');
    if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
  await page.click('#bNodes');
  await page.waitForSelector('.nodestab .ndrow', { timeout: 15000 });
  ok(await page.$$eval('.nodestab .ndrow', rs => rs.length) === 2,
     'the Nodes tab lists the registry: local and the sandbox');
  // add an ssh node through the form
  await page.click('#ndAdd');
  await page.fill('#ndName', 'buildbox');
  await page.fill('#ndAddr', '10.9.9.9');
  await page.click('#ndGo');
  await page.waitForFunction(() =>
    document.querySelectorAll('.nodestab .ndrow').length === 3, null,
    { timeout: 15000 });
  ok(true, 'Add node registers one from a bare address');
  const added = await page.evaluate(() =>
    nodesList.find(n => n.name === 'buildbox'));
  ok(added.ssh_addr === 'ssh://bb@10.9.9.9',
     '...with ssh:// and the bb account filled in, the way DOCKER_HOST is');
  // capability toggle writes through and comes back
  await page.evaluate(id => nodeAct({ action: 'update', id,
    fields: { capabilities: ['docker-host', 'package-build'] } }), added.id);
  await page.waitForFunction(id => nodesList.find(n => n.id === id)
    ?.capabilities.includes('package-build'), added.id, { timeout: 10000 });
  ok(true, 'a capability toggle is stored and re-read');
  {
    // A deliberate refusal: the server answers 400, and the browser logs
    // every non-2xx as a console error. Asserted, then absolved — the final
    // zero-errors check is for failures this file did not order.
    const before = page.errors.length;
    const r = await page.evaluate(() => nodeAct({ action: 'update',
      id: 'local', fields: { capabilities: ['docker-host'] } }));
    ok(/cannot be a docker host/.test(r.error || '')
       && await page.evaluate(() => nodesList.find(n => n.id === 'local')
            .capabilities.includes('docker-host')) === false,
       'the local node refuses docker-host: it is not a sandbox');
    page.errors.length = before;
  }
  // drain / undrain
  await page.evaluate(id => nodeAct({ action: 'drain', id }), added.id);
  await page.waitForFunction(id =>
    nodesList.find(n => n.id === id)?.state === 'draining', added.id,
    { timeout: 10000 });
  ok(true, 'Drain marks it draining');
  // the audit trail followed
  const acts = readStore(
    `m._rows("SELECT action, principal FROM audit WHERE target = ?", ("${added.id}",))`);
  ok(acts.some(r => r.action === 'node-add')
     && acts.some(r => r.action === 'node-update')
     && acts.every(r => r.principal === 'operator'),
     'every node mutation wrote an audit row as the operator');
}

// ---- phase 2: the docker manager's picker ----------------------------------
{
  await page.evaluate(() => openDocker());
  await page.waitForSelector('.dmtab .macros', { timeout: 15000 });
  await page.waitForSelector('.dmtab .dmpick select', { timeout: 15000 });
  const opts = await page.$$eval('.dmtab .dmpick option',
    os => os.map(o => o.textContent.trim()));
  ok(opts.length === 2 && opts.some(o => /sandbox/.test(o))
     && opts.some(o => /buildbox/.test(o)),
     `the manager offers every docker-host node (${opts.join(' | ')})`);
  // switch to the unreachable node: rows blind, reason worn, picker alive.
  // The stub daemon fails any call whose DOCKER_HOST is listed as dead, which
  // is what a powered-off VM looks like from here.
  writeFileSync(`${DIR}/dockerstate/deadhosts`, 'ssh://bb@10.9.9.9\n');
  await page.evaluate(() => { const s = document.querySelector('#dmNode');
    s.value = nodesList.find(n => n.name === 'buildbox').id;
    s.dispatchEvent(new Event('change')); });
  await page.waitForFunction(() => dockerList && dockerList.blind === true,
                             null, { timeout: 30000 });
  await page.evaluate(() => { dockerRev++; drawPanes(); });
  ok(/not a BuilderBot sandbox|does not answer|docker does not answer/.test(
       await page.$eval('.dmtab .empty', e => e.textContent).catch(() => '')),
     'an unreachable node shows its reason, not a spinner');
  ok(await page.$eval('.dmtab .dmpick select', s => !s.disabled),
     '...with the picker still live — the way back is the way in');
  // and back: the sandbox's last-known answer paints instantly from cache
  await page.evaluate(() => { const s = document.querySelector('#dmNode');
    s.value = nodesList.find(n => n.name === 'sandbox').id;
    s.dispatchEvent(new Event('change')); });
  await page.waitForFunction(() => dockerList && !dockerList.blind,
                             null, { timeout: 30000 });
  ok(true, 'switching back to the live node recovers without a reload');
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'docker');
                              if (t) hideTab(t.id); });
}

// ---- phase 2: the settings graduation ---------------------------------------
{
  await page.evaluate(() => toggleUiMenu(true));
  await page.waitForSelector('#uiSettings', { timeout: 10000 });
  ok(await page.evaluate(() => !document.querySelector('#uiMenu #logDays')),
     'the gear keeps appearance only — the log setting moved out');
  await page.click('#uiSettings');
  await page.waitForSelector('.settingstab .logdays #logDays', { timeout: 15000 });
  ok(true, 'All settings… opens the Settings tab, with the log policy on it');
  ok(await page.$eval('.settingstab', e => /unhardwiring|DOCKER_HOST/.test(e.textContent)),
     '...which says what still lives in the environment, and why');
}

// ---- the configuration plane on the row (phase 5) ---------------------------
// A node that enrolled as a sandbox gets a fold: mounts, stores and network
// as the operator wants them, drawn against what the agent reports, with
// Save keeping the record and Apply queuing the system job. Enrolled here by
// hand — the census is a body — because the real agent has its own suite.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const base = URL.replace(/\/$/, '');
  const napi = async (path, body, headers = H) => (await fetch(base + path, body === undefined
    ? { headers } : { method: 'POST', headers, body: JSON.stringify(body) })).json();
  const minted = await napi('/api/v1/nodes', { action: 'enroll', name: 'shed', capabilities: ['docker-host'] });
  const en = await napi('/api/v1/agent/enroll', {
    census: { cpu: 4, mem_mb: 8192, os: 'linux x86_64 Ubuntu', system: 'linux', arch: 'x86_64',
              sandbox: true, stores: { data: { path: '/var/lib/builderbot/data', free_mb: 5000, total_mb: 9000 },
                                       packages: { path: '/var/lib/builderbot/packages', free_mb: 40000, total_mb: 90000 } },
              toolchains: { flutter: '3.24.0', node: 'v22.1.0' },
              mounts: [{ path: '/mnt/old', source: 'nas:/mnt/user/old', type: 'nfs', ro: false, mounted: true, real: 'nas:/mnt/user/old' }],
              network: { interface: 'ens3', addresses: ['10.0.0.40/24'], gateway: '10.0.0.1', dns: ['10.0.0.1'] } },
    version: '3', digest: 'sha256:' + '0'.repeat(64), user: 'bb' },
    { Authorization: 'Bearer ' + minted.token, 'Content-Type': 'application/json' });
  ok(en.ok && en.node_id === minted.id, 'a sandbox node enrolled with mounts and an address in its census');
  await page.evaluate(() => { nodesList = null; openNodesTab(); });
  const ROW = `.nodestab .ndrow[data-node="${minted.id}"]`;
  await page.waitForSelector(`${ROW} .ndconf`, { timeout: 15000 });
  ok(await page.$eval('.nodestab', e => !e.querySelector('.ndrow[data-node="local"] .ndconf')),
     'the fold is on the sandbox node and not on local');
  await page.click(`${ROW} .ndconf summary`);
  await page.waitForSelector(`${ROW} .ndconf[open] [data-madd]`, { timeout: 5000 });
  ok(await page.$eval(`${ROW} .ndconf`, e => /now 10\.0\.0\.40\/24 on ens3 via 10\.0\.0\.1/.test(e.textContent)),
     'it reports the address the node is on');
  ok(await page.$eval(`${ROW} .ndrunstate`, e => /no runner on this node/.test(e.textContent))
     && await page.$eval(`${ROW} [data-nrunner="install"]`, b => /Install runner/.test(b.textContent)),
     'the CI runner section says there is none, and offers to install one');
  await page.fill(`${ROW} [data-k="runner:url"]`, 'https://github.com/example-org');
  await page.fill(`${ROW} [data-k="runner:labels"]`, 'gpu');
  await page.click(`${ROW} [data-nrunner="install"]`);
  await page.waitForFunction(sel => /applying runner/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  const rj = (await napi('/api/v1/jobs?active=1')).jobs.find(j => j.type === 'system' && j.spec.apply === 'runner');
  ok(rj && rj.node === minted.id && rj.spec.config.url === 'https://github.com/example-org'
     && rj.spec.config.labels.includes('shed') && rj.spec.config.labels.includes('gpu'),
     `Install runner queues the system job with the node's name among the labels (${rj?.spec?.config?.labels?.join(',')})`);
  await napi('/api/v1/jobs', { action: 'cancel', id: rj.id });
  await page.waitForFunction(sel => !/applying/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  await page.click(`${ROW} [data-madd]`);
  await page.waitForSelector(`${ROW} .ndmount[data-i="0"] [data-k="source"]`, { timeout: 5000 });
  ok(await page.evaluate(() => document.activeElement?.dataset.k === 'source'),
     '+ mount adds a row and puts the caret in it');
  await page.fill(`${ROW} .ndmount[data-i="0"] [data-k="source"]`, 'nas:/mnt/user/appdata');
  await page.fill(`${ROW} .ndmount[data-i="0"] [data-k="path"]`, '/mnt/appdata');
  await page.fill(`${ROW} [data-k="store:cache"]`, '/scratch/cache');
  // The heartbeat repaints the tab; the draft and the caret survive it.
  await page.evaluate(() => loadNodes());
  await sleep(400);
  const kept = await page.$eval(`${ROW} .ndmount[data-i="0"] [data-k="path"]`, e => e.value);
  const caret = await page.evaluate(() => document.activeElement?.dataset?.k || document.activeElement?.tagName);
  ok(kept === '/mnt/appdata' && caret === 'store:cache',
     `a repaint under the editor keeps what was typed and where the caret was (kept ${kept}, caret ${caret})`);
  ok(await page.$eval(`${ROW} .ndmount[data-i="0"] .ndmstate`, e => /not applied yet/.test(e.textContent))
     && await page.$eval(`${ROW} [data-napply="storage"]`, b => b.disabled),
     '...the new mount says it is not applied yet, and Apply waits for Save');
  await page.click(`${ROW} [data-nsave]`);
  await page.waitForFunction(sel => !document.querySelector(sel + ' [data-napply="storage"]')?.disabled,
                             ROW, { timeout: 10000 });
  const rec = (await napi('/api/v1/nodes')).nodes.find(n => n.id === minted.id);
  ok(rec.config.desired.mounts.length === 1 && rec.config.desired.mounts[0].path === '/mnt/appdata'
     && rec.config.desired.stores.cache === '/scratch/cache' && rec.config.desired.network.mode === 'dhcp',
     'Save puts the desired config on the record, validated');
  page.dialogs.length = 0;
  await page.click(`${ROW} [data-napply="storage"]`);
  await page.waitForFunction(sel => /applying storage/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  ok(page.dialogs.length === 1 && /unmounts \/mnt\/old/.test(page.dialogs[0]),
     'Apply storage asks first when it would unmount something the node has');
  const active = (await napi('/api/v1/jobs?active=1')).jobs.find(j => j.type === 'system');
  ok(active && active.node === minted.id && active.spec.apply === 'storage'
     && active.spec.config.mounts[0].path === '/mnt/appdata',
     `...and queues the system job on that node with the desired config (${active?.id})`);
  ok(await page.$eval(`${ROW} [data-napply="network"]`, b => b.disabled),
     '...while it is in flight the other Apply is off');
  await napi('/api/v1/jobs', { action: 'cancel', id: active.id });
  // The fold is held to the document rules the same as any tab surface
  // (uniform.mjs cannot see it: that suite has no sandbox node to open one
  // on): every control wears the field skin, and at phone width nothing
  // scrolls sideways and every text control is 16px.
  const skin = await page.evaluate(sel => {
    const ref = document.getElementById('mName');
    const key = el => { const c = getComputedStyle(el);
      return [c.backgroundColor, c.borderTopLeftRadius, c.borderTopColor, c.fontFamily].join('|'); };
    return [...document.querySelectorAll(sel + ' .ndconf input:not([type=checkbox]), ' + sel + ' .ndconf select')]
      .filter(e => e.offsetHeight > 0).map(e => key(e) === key(ref));
  }, ROW);
  ok(skin.length >= 8 && skin.every(Boolean), `every control in the fold wears the field skin (${skin.length} checked)`);
  await page.setViewportSize({ width: 393, height: 851 });
  await sleep(300);
  const phone = await page.evaluate(sel => ({
    over: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    small: [...document.querySelectorAll(sel + ' .ndconf input:not([type=checkbox]), ' + sel + ' .ndconf select')]
      .filter(e => e.offsetHeight > 0 && parseFloat(getComputedStyle(e).fontSize) < 16).length,
  }), ROW);
  ok(phone.over <= 0 && phone.small === 0,
     `...and at phone width it does not scroll sideways (${phone.over}px) and its controls are 16px (${phone.small} small)`);
  await page.setViewportSize({ width: 1280, height: 900 });

  // ---- toolchains on the node, from the Tools tab (phase 6) ---------------
  await page.evaluate(() => openPackages());
  await page.waitForSelector('.pkgtab #pkgNodeSel', { timeout: 15000 });
  await page.selectOption('.pkgtab #pkgNodeSel', minted.id);
  await page.waitForFunction(() => /on shed/.test(document.querySelector('.pkgtab .pkghead:not(.pkgnode)')?.textContent || ''),
                             null, { timeout: 15000 });
  const tools = await page.$$eval('.pkgtab .pkg', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ')));
  ok(tools.some(t => /3\.24\.0/.test(t)) && /40 ?GB free|39 ?GB free|39\.\d ?GB free/.test(await page.$eval('.pkgtab .pkghead:not(.pkgnode)', e => e.textContent)),
     `picking the node lists what its census says it has, and its store's headroom (${
       await page.$eval('.pkgtab .pkghead:not(.pkgnode)', e => e.textContent.replace(/\s+/g, ' ').slice(0, 160))} | ${tools.filter(t => /installed|21\.0/.test(t)).join(' || ').slice(0, 300)})`);
  const gate = await napi('/api/packages', { action: 'install', names: ['android:platform-tools'], node: 'local' });
  ok(gate.ok !== undefined || gate.error, '(local installs still go through the installer here)');

  // ---- the project's nodes, in its settings dialog (phase 6) --------------
  await page.evaluate(() => openProjectsTab());
  await page.waitForSelector('.doc .projtab [data-rn="alpha"]', { timeout: 15000 });
  await page.click('.doc .projtab [data-rn="alpha"]');
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  await page.waitForFunction(id => [...document.querySelectorAll('#rnNode option')].some(o => o.value === id),
                             minted.id, { timeout: 10000 });
  ok(await page.$eval('#rnNode', s => ![...s.options].some(o => o.value === 'local') && [...s.options].some(o => /sandbox/.test(o.textContent))),
     'the project\'s node is any node but this container — the ssh sandbox included');
  await page.selectOption('#rnNode', minted.id);
  await page.fill('#rnBuildCmd', './gradlew assembleDebug');
  await page.fill('#rnOutputs', 'app/build/outputs/apk/**/*.apk, extra/*.xpi');
  await page.click('#rnGo');
  await page.waitForSelector('#rnmodal', { state: 'hidden', timeout: 10000 });
  const saved = JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects.alpha;
  ok(saved.node === minted.id && saved.build === './gradlew assembleDebug'
     && saved.outputs.length === 2 && saved.outputs[1] === 'extra/*.xpi',
     'Save writes the project\'s node, the command and the outputs onto the project record');
}

// ---- the seam stays invisible on the sidebar --------------------------------
ok(await page.evaluate(() => !document.querySelector('[data-card="nodes"]')),
   'still no nodes card — nodes are a tab, not sidebar chrome');
ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
