// Phase 1 of the controller design (docs/nodes.md): the seam, with nothing
// visibly changing. What this file holds is the phase's whole contract —
// the store exists behind the four one-way doors it owns, the local node and
// the DOCKER_HOST mirror are seeded, work stamps the node it belongs to,
// every mutation grows an audit row, and the page the operator sees is
// exactly the page it was.
import { URL, launch, newPage, ok, done, ready, sleep, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';

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

// ---- the seam stays invisible on the sidebar --------------------------------
ok(await page.evaluate(() => !document.querySelector('[data-card="nodes"]')),
   'still no nodes card — nodes are a tab, not sidebar chrome');
ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
