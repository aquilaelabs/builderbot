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

// The tab shows ONE node, chosen in the bar. Picking is how a test reaches
// a row now, and the option list is how it asserts the registry.
const pickNode = async (page, id) => {
  await page.selectOption('.nodestab #ndPick', id);
  await page.waitForFunction(x => document.querySelector(
    `.nodestab .ndrow[data-node="${x}"]`) !== null, id, { timeout: 10000 });
};
const nodeOptions = page => page.$$eval('.nodestab #ndPick option', os => os.map(o => o.value));

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the registry ----------------------------------------------------------
// Two nodes: the controller, seeded on boot, and the docker host the harness
// enrolls with a token before any file runs. It used to be mirrored from
// DOCKER_HOST into an `ssh` row; both the variable and the kind are gone
// (roadmap #24), so the suite gets its node the way an operator does.
const list = await page.evaluate(async () =>
  (await (await fetch('/api/v1/nodes')).json()).nodes);
ok(Array.isArray(list) && list.length === 2,
   `the store holds two nodes: the controller and the enrolled docker host (${
     (list || []).map(n => n.id).join(', ')})`);
const local = list.find(n => n.id === 'local');
ok(local && local.kind === 'local' && local.state === 'online'
   && local.reported.cpu > 0 && local.reported.mem_mb > 0,
   'local is this container, with a real census');
ok(!local.capabilities.includes('docker-host'),
   '...and no docker-host capability: the local node is not a sandbox');
ok(await page.evaluate(() => !document.querySelector('.nodestab [data-cap], .nodestab [data-encap]')),
   'no capability toggles anywhere: a node does everything for the projects bound to it');
// The docker host, enrolled by the harness with a token (roadmap #24 —
// there is no ssh kind and no DOCKER_HOST seed any more). Its address is
// what it dialed in from, reported by the node rather than written here.
const sandbox = list.find(n => n.name === 'sandbox');
ok(sandbox && /^n_[0-9a-f]{8}$/.test(sandbox.id) && sandbox.kind === 'agent'
   && sandbox.agent.addr === 'stub' && sandbox.config.user === 'bb'
   && ['docker-host', 'package-build', 'deploy-target'].every(c => sandbox.capabilities.includes(c)),
   'the sandbox VM has a minted identity that is not its address, and does everything');
ok(!list.some(n => n.kind === 'ssh'),
   '...and no node is of the retired ssh kind, here or anywhere');
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
  // Read from the job ROW, not from the live slot the manager polls. The
  // first version of this raced the stub daemon — an up finishes in well
  // under a second and a finished job leaves the slot, so the stamp had to
  // be caught mid-flight, and on a loaded box the whole job could pass
  // between two polls. It flaked in full runs and passed in isolation, which
  // is the worst shape a test has. The row keeps the node forever.
  const job = await page.evaluate(async () => {
    await (await fetch('/api/devapp', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'up', project: 'ep.silon', instance: 'ph1' }),
    })).json();
    for (let i = 0; i < 200; i++){
      const j = ((await (await fetch('/api/v1/jobs?type=compose&n=1')).json()).jobs || [])[0];
      if (j) return j;
      await new Promise(r => setTimeout(r, 50));
    }
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
  // The principal names the ACCOUNT now, not the fact that somebody was
  // signed in: `operator` was a placeholder from when only one person could
  // make a mutation, and a log that calls everybody that answers nothing.
  ok(row && row.principal === 'user:test' && row.target === 'alpha',
     `a mutation writes an audit row naming the account: who, what, on what (${row?.principal})`);
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
     && /sandbox · stub/.test(out),
     'bb nodes prints the same registry, read-only');
}

// ---- phase 2: the Nodes tab ------------------------------------------------
{
  await page.evaluate(() => { const c = document.getElementById('cardTools');
    if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
  await page.click('#bNodes');
  await page.waitForSelector('.nodestab .ndrow', { timeout: 15000 });
  ok((await nodeOptions(page)).length === 2,
     'the Nodes tab lists the registry: local and the sandbox');
  // Adding a node by ssh address is retired (roadmap #18): it existed only
  // because compose ran from this container over ssh, so a machine needed a
  // key as well as a token and a token-only node could do everything except
  // docker. Compose is an agent job now, so the tab offers one way in.
  ok(await page.$('#ndAdd') === null && await page.$('#ndEnroll') !== null,
     'the tab offers enrollment and nothing else — no Add ssh node');
  {
    const before = page.errors.length;
    const r = await page.evaluate(() => nodeAct({ action: 'add', name: 'buildbox',
                                                  addr: '10.9.9.9' }));
    ok(/enroll the machine with a token/.test(r.error || ''),
       '...and the endpoint refuses too, saying the way in rather than 404ing');
    page.errors.length = before;
  }
  // A second docker node for the rest of this block, enrolled the one way
  // there is. sshd and the account are what give it an address the manager
  // can send docker to.
  {
    const base = URL.replace(/\/$/, '');
    const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
                'Content-Type': 'application/json' };
    const post = async (path, body, headers = H) => (await fetch(base + path,
      { method: 'POST', headers, body: JSON.stringify(body) })).json();
    const mint = await post('/api/v1/nodes', { action: 'enroll', name: 'buildbox' });
    await post('/api/v1/agent/enroll', {
      user: 'bb', version: '1', digest: 'sha256:' + '1'.repeat(64),
      census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', sshd: true } },
      { Authorization: 'Bearer ' + mint.token, 'Content-Type': 'application/json' });
  }
  const added = await page.evaluate(async () => {
    await loadNodes();
    return nodesList.find(n => n.name === 'buildbox');
  });
  ok(added && added.kind === 'agent',
     'a machine is enrolled with a token, and arrives as an agent node');
  ok(['docker-host', 'package-build', 'deploy-target'].every(c => added.capabilities.includes(c)),
     '...and it does everything, without anybody being asked which');
  // The mechanism underneath is untouched (§15 door 7): a restricted node is
  // still expressible, it is just not something the UI makes.
  await page.evaluate(id => nodeAct({ action: 'update', id,
    fields: { capabilities: ['package-build'] } }), added.id);
  await page.waitForFunction(id => nodesList.find(n => n.id === id)
    ?.capabilities.length === 1, added.id, { timeout: 10000 });
  ok(true, 'a deliberately restricted node can still be written through the API');
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
  ok(acts.some(r => r.action === 'node-enroll-mint')
     && acts.some(r => r.action === 'node-update')
     && acts.some(r => r.principal === 'user:test'),
     'every node mutation wrote an audit row, naming the account that made it');
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
  // The address the node dialed in from, not one written here: an agent node
  // reports where it is on every hello, which is the whole point of it.
  const bbAddr = await page.evaluate(() => {
    const n = nodesList.find(x => x.name === 'buildbox');
    return `ssh://bb@${n.agent.addr}`;
  });
  writeFileSync(`${DIR}/dockerstate/deadhosts`, bbAddr + '\n');
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
  const minted = await napi('/api/v1/nodes', { action: 'enroll', name: 'shed' });
  // The digest this controller ships, so the fixture node enrolls CURRENT.
  // Everything below drives Apply, the runner and installs, all of which are
  // held while an agent is behind — the stale half is its own block at the
  // end, where it can hold them without breaking the rest.
  const shipped = (await napi('/api/v1/nodes')).agent || {};
  // The census this node reports, kept as one object: a hello REPLACES it,
  // so a later poke that sends a partial one silently takes the node's
  // mounts and address away — which is a confusing way to fail four tests
  // further down.
  const CENSUS = { cpu: 4, mem_mb: 8192, os: 'linux x86_64 Ubuntu', system: 'linux', arch: 'x86_64',
              sandbox: true, stores: { data: { path: '/var/lib/builderbot/data', free_mb: 5000, total_mb: 9000 },
                                       packages: { path: '/var/lib/builderbot/packages', free_mb: 40000, total_mb: 90000 },
                                       artifacts: { path: '/var/lib/builderbot/artifacts', free_mb: 30000, total_mb: 90000 } },
              toolchains: { flutter: '3.24.0', node: 'v22.1.0' },
              // What `bb sdk versions` says on the node — the controller's
              // own generator, run there. The toolchains dict above is a
              // placement summary and describes the same store differently,
              // which is the disparity this replaces.
              packages_versions: { flutter: '6655482e', 'android:ndk': '29.0.14206865' },
              // What the packages store actually holds, which is what the
              // Tools tab decides `installed` from — the census summary
              // above is a placement hint, not an inventory.
              store_dirs: { top: ['flutter', 'node'], android: [] },
              // The android system images in the node's own packages store,
              // and the AVDs built on them. Walked there; the size is joined
              // here from Google's index, because an image is a guest
              // artifact and weighs the same on every host (roadmap #20).
              images: [{ id: 'system-images;android-30;google_apis;x86_64', api: 'android-30',
                         kind: 'google_apis', abi: 'x86_64', avds: ['fb30-node'] }],
              mounts: [{ path: '/mnt/old', source: 'nas:/mnt/user/old', type: 'nfs', ro: false, mounted: true, real: 'nas:/mnt/user/old' }],
              network: { interface: 'ens3', addresses: ['10.0.0.40/24'], gateway: '10.0.0.1', dns: ['10.0.0.1'] } };
  const en = await napi('/api/v1/agent/enroll', {
    census: CENSUS,
    version: shipped.version, digest: shipped.digest, user: 'bb' },
    { Authorization: 'Bearer ' + minted.token, 'Content-Type': 'application/json' });
  ok(en.ok && en.node_id === minted.id, 'a sandbox node enrolled with mounts and an address in its census');
  // A heartbeat, in the shape the real one has: the sample flattens each
  // store to a bare free-space number while the census keeps the whole
  // record. Sent here because reading only the sample called four healthy
  // stores "missing" on the operator's own node, and the fixture had no
  // sample at all to catch it.
  // Raw, not napi: work answers 204 with no body when there is no job, and
  // the helper parses every answer as JSON.
  await fetch(base + '/api/v1/agent/work', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ sample: { cpu_pct: 3.5, mem_mb: 8192, mem_used_mb: 2048,
      stores: { data: { free_mb: 5000, total_mb: 9000 },
                packages: { free_mb: 40000, total_mb: 90000 },
                artifacts: { free_mb: 30000, total_mb: 90000 } } }, running: 0, wait: 0 }) });
  const lst = await napi('/api/v1/nodes');
  ok(lst.agent?.digest && lst.agent.digest === shipped.digest,
     'the node list names the agent the controller ships');
  await page.evaluate(() => { nodesList = null; openNodesTab(); });
  await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
  await pickNode(page, minted.id);
  const ROW = `.nodestab .ndrow[data-node="${minted.id}"]`;
  await page.waitForSelector(`${ROW} .ndconf`, { timeout: 15000 });
  ok(await page.$(`${ROW} .ndstale`) === null && await page.$(`${ROW} [data-nd="update-agent"]`) === null,
     'a node running the shipped agent wears no update pill and is offered no update');
  await pickNode(page, 'local');
  ok(await page.$('.nodestab .ndrow[data-node="local"] .ndconf') === null
     && await page.$('.nodestab .ndrow[data-node="local"] [data-nd="update-agent"]') === null,
     'local has neither the storage section nor an agent to update');
  await pickNode(page, minted.id);
  // Nothing to open: the storage and network settings are always shown now,
  // one node at a time, chosen in the bar.
  await page.waitForSelector(`${ROW} .ndconf [data-madd]`, { timeout: 5000 });
  ok(await page.$eval(`${ROW} .ndconf`, e => /now 10\.0\.0\.40\/24 on ens3 via 10\.0\.0\.1/.test(e.textContent)),
     'it reports the address the node is on');
  // The census's numbers as meters rather than as a sentence: one per store,
  // labelled, with the free space on the right.
  const meters = await page.$$eval(`${ROW} .ndmeter`, ms => ms.map(m => ({
    label: m.querySelector('.lbl').textContent,
    val: m.querySelector('.val').textContent,
    width: m.querySelector('.fill').style.width })));
  ok(meters.some(m => m.label === 'packages' && /GB free/.test(m.val))
     && meters.some(m => m.label === 'data') && meters.some(m => m.label === 'artifacts')
     && !meters.some(m => /missing/.test(m.val))
     && meters.some(m => m.label === 'cpu') && meters.some(m => m.label === 'memory')
     && meters.every(m => /^\d+%$/.test(m.width)),
     `each store is a meter with its headroom (${meters.map(m => m.label + ' ' + m.val).join(', ')})`);
  ok(await page.$eval(`${ROW} .ndtools`, e => /flutter/.test(e.textContent) && /node/.test(e.textContent)),
     'the row shows what is installed on the node, which is what a project bound to it can build');
  ok(await page.$eval(`${ROW} .ndrunstate`, e => /no runner on this node/.test(e.textContent))
     && await page.$eval(`${ROW} [data-nrunner="install"]`, b => /Install runner/.test(b.textContent)),
     'the CI runner section says there is none, and offers to install one');
  await page.fill(`${ROW} [data-k="runner:url"]`, 'https://github.com/example-org');
  await page.fill(`${ROW} [data-k="runner:labels"]`, 'gpu');
  // Dead the moment it is pressed, not when the answer comes back. Every
  // action here awaits a POST, then loadNodes(), then a repaint — a second
  // or two in which the button looked untouched, so there was no telling a
  // press that landed from one that missed. Read synchronously after the
  // click dispatches, before any await resolves.
  const pressedState = await page.evaluate(sel => {
    const b = document.querySelector(sel + ' [data-nrunner="install"]');
    b.click();
    return b.disabled;
  }, ROW);
  ok(pressedState === true, 'a node action goes dead the instant it is pressed, not when it answers');
  await page.waitForFunction(sel => /applying runner/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  const rj = (await napi('/api/v1/jobs?active=1')).jobs.find(j => j.type === 'system' && j.spec.apply === 'runner');
  ok(rj && rj.node === minted.id && rj.spec.config.url === 'https://github.com/example-org'
     && rj.spec.config.labels.includes('shed') && rj.spec.config.labels.includes('gpu'),
     `Install runner queues the system job with the node's name among the labels (${rj?.spec?.config?.labels?.join(',')})`);
  await napi('/api/v1/jobs', { action: 'cancel', id: rj.id });
  await page.waitForFunction(sel => !/applying/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  // Installed and listening are different states, and the difference is the
  // one that matters: a registered runner with no listener looks healthy
  // right up until a workflow sits in "Waiting for a runner". The operator's
  // own node was in exactly this state.
  const runnerCensus = svc => fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: { ...CENSUS, services: svc },
                           version: shipped.version, digest: shipped.digest }) });
  await runnerCensus({ 'actions-runner': { installed: true, active: false, busy: false,
                                           name: '', labels: ['builderbot', 'shed'] } });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /NOT listening/.test(
    document.querySelector(sel + ' .ndrunstate')?.textContent || ''), ROW, { timeout: 10000 });
  ok(await page.$eval(`${ROW} .ndrunstate`, e => /no workflow will reach it/.test(e.textContent)
       && /registration may not have finished/.test(e.textContent) && e.classList.contains('bad')),
     'a runner that is registered but not listening says so, rather than reading as installed');
  await runnerCensus({ 'actions-runner': { installed: true, active: true, busy: true,
                                           name: 'shed', url: 'https://github.com/example-org',
                                           labels: ['builderbot', 'shed'] } });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => document.querySelector(sel + ' .ndrunbusy'), ROW, { timeout: 10000 });
  ok(await page.$eval(`${ROW} .ndrunstate`, e => /running a job/.test(e.textContent)
       && /registered as shed/.test(e.textContent)),
     '...and one that is working says which job-taking state it is in, by name');
  // The label is the only thing that pins a workflow to THIS machine —
  // `self-hosted` alone matches the controller and every other node, so
  // GitHub sends the job to whichever is idle (roadmap #19).
  ok(await page.$eval(`${ROW} .ndrunpin`, e =>
       /runs-on: \[self-hosted, shed\]/.test(e.textContent)),
     '...and the section prints the exact runs-on line that lands a job here');
  // The runner belongs above the mounts: it is the thing the operator is
  // most often here to check, and it was below three editors. The plane is
  // sections now — one fold per concern, a status on each summary — and
  // the order still holds.
  ok(await page.$eval(`${ROW} .ndconfbody`, e => {
       const kids = [...e.querySelectorAll(':scope > details.sect > summary .t')].map(t => t.textContent.trim());
       return kids.indexOf('CI runner') >= 0 && kids.indexOf('Storage') >= 0
              && kids.indexOf('CI runner') < kids.indexOf('Storage');
     }), '...and the runner section comes before the mounts, not after the network');
  ok(await page.$eval(`${ROW} .ndconfbody`, e =>
       [...e.querySelectorAll(':scope > details.sect > summary .sst')].every(s => s.textContent.trim())),
     '...every section says its state on its summary, so a phone reads the headings and picks one');
  // The sidebar's Runner card carries every node with a runner, not only
  // this container's — a workflow lands on whichever runner its runs-on
  // matches, and GitHub was the only place that answer existed.
  await runnerCensus({ 'actions-runner': { installed: true, active: true, busy: false,
                                           name: 'shed', url: 'https://github.com/example-org',
                                           labels: ['builderbot', 'shed'] } });
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => /shed/.test(document.getElementById('runner')?.textContent || ''),
                             null, { timeout: 10000 });
  ok(await page.$eval('#runner', e => /listening — idle/.test(e.textContent)
       && /runs-on: \[self-hosted, shed\]/.test(e.textContent)),
     'the Runner card carries a node runner, with the runs-on that lands a job on it');
  await runnerCensus({});
  // A node with mounts and no saved config opens on the ones it reports —
  // an empty editor for a machine with three shares was the first thing the
  // operator hit.
  const seeded = await page.$$eval(`${ROW} .ndmount [data-k="source"]`, es => es.map(e => e.value));
  ok(seeded.includes('nas:/mnt/user/old'),
     `the mount editor opens on what the node reports, not on an empty list (${seeded.join(', ')})`);
  ok(await page.$eval(`${ROW} .ndconf`, e => /the ones the node reports/.test(e.textContent)),
     '...and says they came from the node rather than from anything saved here');
  // The new row lands after the seeded ones.
  const last = seeded.length;
  await page.click(`${ROW} [data-madd]`);
  await page.waitForSelector(`${ROW} .ndmount[data-i="${last}"] [data-k="source"]`, { timeout: 5000 });
  ok(await page.evaluate(() => document.activeElement?.dataset.k === 'source'),
     '+ mount adds a row and puts the caret in it');
  await page.fill(`${ROW} .ndmount[data-i="${last}"] [data-k="source"]`, 'nas:/mnt/user/appdata');
  await page.fill(`${ROW} .ndmount[data-i="${last}"] [data-k="path"]`, '/mnt/appdata');
  await page.fill(`${ROW} [data-k="store:cache"]`, '/scratch/cache');
  ok(await page.$(`${ROW} [data-k="store:artifacts"]`) !== null,
     'the fold carries the artifacts store — this node\'s copy of what projects built');
  // The heartbeat repaints the tab; the draft and the caret survive it.
  await page.evaluate(() => loadNodes());
  await sleep(400);
  const kept = await page.$eval(`${ROW} .ndmount[data-i="${last}"] [data-k="path"]`, e => e.value);
  const caret = await page.evaluate(() => document.activeElement?.dataset?.k || document.activeElement?.tagName);
  ok(kept === '/mnt/appdata' && caret === 'store:cache',
     `a repaint under the editor keeps what was typed and where the caret was (kept ${kept}, caret ${caret})`);
  ok(await page.$eval(`${ROW} .ndmount[data-i="${last}"] .ndmstate`, e => /not applied yet/.test(e.textContent))
     && await page.$eval(`${ROW} [data-napply="storage"]`, b => b.disabled),
     '...the new mount says it is not applied yet, and Apply waits for Save');
  await page.click(`${ROW} [data-nsave]`);
  await page.waitForFunction(sel => !document.querySelector(sel + ' [data-napply="storage"]')?.disabled,
                             ROW, { timeout: 10000 });
  const rec = (await napi('/api/v1/nodes')).nodes.find(n => n.id === minted.id);
  ok(rec.config.desired.mounts.some(m => m.path === '/mnt/appdata')
     && rec.config.desired.mounts.some(m => m.path === '/mnt/old')
     && rec.config.desired.stores.cache === '/scratch/cache' && rec.config.desired.network.mode === 'dhcp',
     'Save puts the desired config on the record, validated');
  // Applying a config that keeps what the node already has asks nothing:
  // the editor was seeded from the node, so this adds a mount rather than
  // taking one away.
  page.dialogs.length = 0;
  await page.click(`${ROW} [data-napply="storage"]`);
  await page.waitForFunction(sel => /applying storage/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  ok(page.dialogs.length === 0, 'applying a config that removes nothing asks nothing');
  const active = (await napi('/api/v1/jobs?active=1')).jobs.find(j => j.type === 'system');
  ok(active && active.node === minted.id && active.spec.apply === 'storage'
     && active.spec.config.mounts.some(m => m.path === '/mnt/appdata')
     && active.spec.config.mounts.some(m => m.path === '/mnt/old'),
     `...and queues the system job on that node carrying both mounts (${active?.id})`);
  ok(await page.$eval(`${ROW} [data-napply="network"]`, b => b.disabled),
     '...while it is in flight the other Apply is off');
  await napi('/api/v1/jobs', { action: 'cancel', id: active.id });
  await page.waitForFunction(sel => !/applying/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  // ...and taking one away does ask, naming what goes: unmounting a share
  // out from under whatever is using it is not a thing to do on one click.
  await page.click(`${ROW} .ndmount[data-i="0"] [data-mrm]`);
  await page.click(`${ROW} [data-nsave]`);
  await page.waitForFunction(sel => !document.querySelector(sel + ' [data-napply="storage"]')?.disabled,
                             ROW, { timeout: 10000 });
  page.dialogs.length = 0;
  await page.click(`${ROW} [data-napply="storage"]`);
  await page.waitForFunction(() => true);
  ok(page.dialogs.length === 1 && /unmounts \/mnt\/old/.test(page.dialogs[0]),
     `Apply storage asks first when it would unmount something the node has (${page.dialogs[0]?.slice(0, 60)})`);
  for (const j of (await napi('/api/v1/jobs?active=1')).jobs)
    await napi('/api/v1/jobs', { action: 'cancel', id: j.id });
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
  ok(tools.some(t => /6655482e/.test(t)) && tools.some(t => /29\.0\.14206865/.test(t))
     && !tools.some(t => /3\.24\.0/.test(t)),
     'a node\'s versions come from its own bb sdk versions, not the census summary');
  ok(tools.some(t => /6655482e/.test(t)) && /40 ?GB free|39 ?GB free|39\.\d ?GB free/.test(await page.$eval('.pkgtab .pkghead:not(.pkgnode)', e => e.textContent)),
     `picking the node lists what its census says it has, and its store's headroom (${
       await page.$eval('.pkgtab .pkghead:not(.pkgnode)', e => e.textContent.replace(/\s+/g, ' ').slice(0, 160))} | ${tools.filter(t => /installed|21\.0/.test(t)).join(' || ').slice(0, 300)})`);
  ok(!/installed at\s*(<|$)/m.test(await page.$eval('.pkgtab', e => e.textContent)),
     'an installed package on a node reads "installed", not "installed at" with nothing after it');
  // ---- one store, two machines (roadmap #18) ------------------------------
  // The controller reaches the SDK share through Unraid's FUSE layer and a
  // node reaches the same bytes over NFS, so neither mount string can be
  // derived from the other and the pair was invisible. A marker file inside
  // the store answers exactly, whatever the transport — and once the pair is
  // visible, two machines of different architectures sharing one store is a
  // thing that can be refused instead of failing later as binaries that will
  // not execute.
  {
    const ID = 's_' + '9'.repeat(16);
    const withId = (arch, token) => fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { ...CENSUS, arch, stores: { ...CENSUS.stores,
          packages: { ...CENSUS.stores.packages, id: ID } } },
        version: shipped.version, digest: shipped.digest }) });
    await withId('x86_64', en.token);
    // A second machine on the same store, of another architecture.
    const other = await napi('/api/v1/nodes', { action: 'enroll', name: 'armbox' });
    const oen = await napi('/api/v1/agent/enroll', {
      user: 'bb', version: shipped.version, digest: shipped.digest,
      census: { ...CENSUS, arch: 'aarch64', stores: { ...CENSUS.stores,
        packages: { ...CENSUS.stores.packages, id: ID } } } },
      { Authorization: 'Bearer ' + other.token, 'Content-Type': 'application/json' });
    ok(oen.ok, '(a second node enrolled on the same store)');
    // ...and the catalog says which platform each recipe is for, so an
    // install onto a node of another one is refused by name rather than
    // fetching a couple of hundred megabytes that cannot execute. arm64
    // Linux needs no new agent to reach this (roadmap #18).
    const wrong = await napi('/api/packages', { action: 'install', names: ['jdk'], node: other.id });
    ok(/packaged for linux\/amd64/.test(wrong.error || ''),
       `an install onto the wrong platform is refused by name (${
         (wrong.error || 'no error').slice(0, 100)})`);
    const fine = await napi('/api/packages', { action: 'install', names: ['flutter'], node: other.id });
    ok(!/packaged for/.test(fine.error || ''),
       `...while one that resolves its own platform is not refused FOR ITS PLATFORM — this node's refusal is the shared store, a different thing (${String(fine.error).slice(0, 60)})`);
    if (fine.job) await napi('/api/v1/jobs', { action: 'cancel', id: fine.job });
    const clash = await napi('/api/packages', { action: 'install', names: ['jdk'], node: minted.id });
    ok(/cannot hold both architectures/.test(clash.error || ''),
       `a store shared across architectures refuses the install (${
         (clash.error || 'no error').slice(0, 100)})`);
    // Same architecture: allowed, but still one at a time across the pair.
    await fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + oen.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { ...CENSUS, arch: 'x86_64', stores: { ...CENSUS.stores,
          packages: { ...CENSUS.stores.packages, id: ID } } },
        version: shipped.version, digest: shipped.digest }) });
    const first = await napi('/api/packages', { action: 'install', names: ['jdk'], node: minted.id });
    const second = await napi('/api/packages', { action: 'install', names: ['jdk'], node: other.id });
    ok(first.job && /shares this packages store/.test(second.error || ''),
       `...and one install at a time across the pair, naming why (${
         (second.error || 'no error').slice(0, 90)})`);
    if (first.job) await napi('/api/v1/jobs', { action: 'cancel', id: first.job });
    await napi('/api/v1/nodes', { action: 'retire', id: other.id });
    await withId('x86_64', en.token);
    // A package that needs another pulls it in, ahead of itself. Before
    // this, android-tools with no jdk failed inside sdkmanager with a
    // message naming neither Java nor the package that supplies it.
    const dep = await napi('/api/packages', { action: 'install',
                                              names: ['android-tools'], node: minted.id });
    const depjob = dep.job ? await napi(`/api/v1/jobs?id=${dep.job}`) : null;
    ok(depjob && JSON.stringify(depjob.spec.names) === JSON.stringify(['jdk', 'android-tools'])
       && JSON.stringify(dep.added) === JSON.stringify(['jdk']),
       `a package that needs another installs it first, and says so (${
         JSON.stringify(depjob?.spec?.names)} added=${JSON.stringify(dep.added)})`);
    if (dep.job) await napi('/api/v1/jobs', { action: 'cancel', id: dep.job });
    // ...and a bare directory does not count as having it. The operator's
    // node had an android/cmdline-tools holding only a symlink to a
    // directory a failed install had removed; android-tools read as
    // installed, so nothing pulled it in, and the android:* package that
    // needed it died on "no sdkmanager".
    await runnerCensus({});
    await fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { ...CENSUS, toolchains: { java: '21' },
        store_dirs: { top: ['jdk'], android: ['cmdline-tools'] } },
        version: shipped.version, digest: shipped.digest }) });
    const hollow = await napi('/api/packages', { action: 'install',
                                                 names: ['android:ndk'], node: minted.id });
    const hj = hollow.job ? await napi(`/api/v1/jobs?id=${hollow.job}`) : null;
    ok(hj && (hj.spec.names || []).includes('android-tools'),
       `an empty cmdline-tools directory does not count as android-tools (${
         JSON.stringify(hj?.spec?.names)})`);
    if (hollow.job) await napi('/api/v1/jobs', { action: 'cancel', id: hollow.job });
    await runnerCensus({});     // put the fixture's store listing back
  }

  // What a FINISHED job on a node reports. It used to report nothing — the
  // row vanished the moment the job ended, with done and failed hardcoded
  // empty — so the tab never cleared what the operator had ticked and the
  // next press re-sent packages that had already landed.
  {
    const j = await napi('/api/packages', { action: 'install', names: ['flutter', 'jdk'], node: minted.id });
    if (j.job) await napi('/api/v1/jobs', { action: 'cancel', id: j.job });
    let seen = null;
    for (let t = 0; t < 60 && !seen; t++){
      const p = await (await fetch(base + '/api/packages?node=' + minted.id, { headers: H })).json();
      if (p.job && p.job.running === false && p.job.action) seen = p.job;
      else await sleep(250);
    }
    ok(seen && seen.action === 'install' && seen.done.includes('flutter')
       && seen.failed.includes('jdk'),
       `a finished node job says what actually landed, read from the census (${
         JSON.stringify(seen && {done: seen.done, failed: seen.failed})})`);
  }
  // ---- android system images on a node (roadmap #20) ---------------------
  // The node walks its own store for the ids and the AVDs built on them.
  // What COULD be added is not a per-node question at all: an image is a
  // guest artifact, identical on every host, so the index is read here and
  // the node needs no network of its own to be offered one.
  {
    await page.evaluate(() => { packages = null; loadPackages(); });
    await page.waitForFunction(() => (packages?.images || []).length > 0,
                               null, { timeout: 15000 });
    const imgs = await page.$$eval('.pkgtab .pkg.img',
      ls => ls.map(l => l.textContent.replace(/\s+/g, ' ').trim()));
    ok(imgs.length === 1 && /android-30/.test(imgs[0]) && /1\.\d GB/.test(imgs[0])
       && /AVD: fb30-node/.test(imgs[0]),
       `a node's images are listed, with the AVD built on each and the index's size (${imgs[0]})`);
    const apis = await page.$$eval('.pkgtab #imgApi option', o => o.map(x => x.value));
    ok(apis.length === 1 && apis[0] === 'system-images;android-31;google_apis;x86_64',
       `...and the picker offers what the NODE does not have (${JSON.stringify(apis)})`);
    ok(/sdkmanager, which is part of/.test(await page.$eval('.pkgtab', e => e.textContent)),
       'a node with no android-tools is told images are installed by sdkmanager');
    // An image is installed BY sdkmanager, so the command-line tools have to
    // be there first — and they need a JDK in turn. with_requires walks the
    // catalog and an image id is not a catalog row, so the head of that chain
    // is named rather than discovered inside a failing job.
    const add = await napi('/api/packages', { action: 'install', node: minted.id,
      names: ['android:system-images;android-31;google_apis;x86_64'] });
    const aj = add.job ? await napi(`/api/v1/jobs?id=${add.job}`) : null;
    ok(aj && JSON.stringify(aj.spec.names) === JSON.stringify(
         ['jdk', 'android-tools', 'android:system-images;android-31;google_apis;x86_64']),
       `installing an image on a node pulls sdkmanager and its jdk in front of it (${
         JSON.stringify(aj?.spec?.names)})`);
    if (add.job) await napi('/api/v1/jobs', { action: 'cancel', id: add.job });
    // The same rule every executing endpoint here follows, asked of the
    // node's own inventory: a removal names an image THIS node reported.
    const badrm = await napi('/api/packages', { action: 'remove', node: minted.id,
      names: ['android:system-images;android-31;google_apis;x86_64'] });
    ok(/nothing selected/.test(badrm.error || ''),
       `an image the node never reported cannot be removed from it (${badrm.error})`);
    const rm = await napi('/api/packages', { action: 'remove', node: minted.id,
      names: ['android:system-images;android-30;google_apis;x86_64'] });
    ok(rm.job, 'one it did report can be');
    if (rm.job) await napi('/api/v1/jobs', { action: 'cancel', id: rm.job });

    // An agent too old to report the field at all is not a node with no
    // images. Without the distinction the tab says "nothing installed" on
    // behalf of a node the controller has not asked.
    const noField = { ...CENSUS }; delete noField.images;
    await fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: noField, version: shipped.version, digest: shipped.digest }) });
    const old = await (await fetch(base + '/api/packages?node=' + minted.id, { headers: H })).json();
    ok(old.images_known === false && old.images.length === 0,
       `an agent that does not report images says so, rather than reporting none (${
         old.images_known})`);
    await runnerCensus({});     // put the fixture's census back
  }

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

  // ---- saved is not applied ----------------------------------------------
  // Apply used to be live whenever anything had been saved, so a node that
  // already matched its record looked exactly like one that had never been
  // applied. The record is compared against the census now, and the state
  // line says which of the two it is.
  await napi('/api/v1/nodes', { action: 'config', id: minted.id, config: {
    mounts: [{ path: '/mnt/old', source: 'nas:/mnt/user/old', type: 'nfs', ro: false }],
    stores: {}, network: { mode: 'dhcp' } } });
  await page.evaluate(() => openNodesTab());
  await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
  await pickNode(page, minted.id);
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /matches what is saved/.test(
    document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  ok(await page.$eval(`${ROW} [data-napply="storage"]`, b => b.disabled),
     'Apply storage is off when the node already has what the record asks for');
  // ...and comes back the moment the record asks for something it has not got.
  await napi('/api/v1/nodes', { action: 'config', id: minted.id, config: {
    mounts: [{ path: '/mnt/old', source: 'nas:/mnt/user/old', type: 'nfs', ro: false },
             { path: '/mnt/new', source: 'nas:/mnt/user/new', type: 'nfs', ro: false }],
    stores: {}, network: { mode: 'dhcp' } } });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => !document.querySelector(sel + ' [data-napply="storage"]')?.disabled,
                             ROW, { timeout: 10000 });
  ok(await page.$eval(`${ROW} .ndconfstate`, e => /1 change to apply.*\/mnt\/new/.test(e.textContent)),
     `...and says how many changes are waiting and what they are (${
       await page.$eval(`${ROW} .ndconfstate`, e => e.textContent.trim().slice(0, 90))})`);

  // ---- an apply that failed says so, where the button is -------------------
  // A failed apply leaves the drift exactly as it was, so the section went
  // back to "1 change to apply" and mentioned the attempt nowhere — which
  // reads as a button that did nothing, and is what the operator saw.
  {
    const ap = await napi('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
    await napi('/api/v1/jobs', { action: 'cancel', id: ap.job });
    await page.waitForFunction(sel => !/applying/.test(
      document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
    await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
    await page.waitForFunction(sel => /last storage apply/.test(
      document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
    ok(await page.$eval(`${ROW} .ndconfstate`, e =>
         /Jobs tab/.test(e.textContent) && e.classList.contains('bad')),
       'an apply that did not work is reported where the button is, and points at its log');
    ok(await page.$eval(`${ROW} .ndconfbody`, e =>
         [...e.querySelectorAll(':scope > details.sect > summary')]
           .some(s => /Storage/.test(s.textContent) && /apply failed/.test(s.textContent))),
       '...and on the section heading, so a shut fold still shows it');
    // Saved since: the failure was about a record that no longer exists, so
    // the changes waiting are the thing to say instead.
    await napi('/api/v1/nodes', { action: 'config', id: minted.id, config: {
      mounts: [{ path: '/mnt/old', source: 'nas:/mnt/user/old', type: 'nfs', ro: false },
               { path: '/mnt/new2', source: 'nas:/mnt/user/new2', type: 'nfs', ro: false }],
      stores: {}, network: { mode: 'dhcp' } } });
    await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
    let said = '';
    for (let i = 0; i < 40; i++){
      said = await page.$eval(`${ROW} .ndconfstate`, e => e.textContent.trim());
      if (!/last storage apply/.test(said)) break;
      await sleep(250);
    }
    ok(!/last storage apply/.test(said),
       `...and a failure the operator has saved past is not reported over the changes that replaced it (${said.slice(0, 90)})`);
  }

  // ---- an agent that is behind takes nothing but its own update -----------
  // A controller is always newer than or equal to its nodes, so a mismatch
  // means the node may not understand a job this version would send it.
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: CENSUS, version: '3', digest: 'sha256:' + '0'.repeat(64) }) });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => document.querySelector(sel + ' .ndstale'), ROW, { timeout: 10000 });
  ok(await page.$eval(`${ROW} .ndstale`, (e, v) => e.textContent.includes(`update available → ${v}`), shipped.version)
     && await page.$(`${ROW} [data-nd="update-agent"]`) !== null,
     'the row wears "update available" with the shipped version and an Update agent button');
  const off = await page.evaluate(sel => ({
    storage: document.querySelector(sel + ' [data-napply="storage"]')?.disabled,
    network: document.querySelector(sel + ' [data-napply="network"]')?.disabled,
    runner: document.querySelector(sel + ' [data-nrunner="install"]')?.disabled,
    cache: document.querySelector(sel + ' [data-nd="cache-clear"]')?.disabled,
    update: document.querySelector(sel + ' [data-nd="update-agent"]')?.disabled,
    said: document.querySelector(sel + ' .ndconfstate')?.textContent || '',
  }), ROW);
  ok(off.storage && off.network && off.runner && off.cache && !off.update
     && /runs agent 3 and this controller ships/.test(off.said),
     `everything the agent runs is off while it is behind, and the state line says why (${
       JSON.stringify(off).slice(0, 120)})`);
  // The button is a courtesy; the rule is the server's.
  const refused = await napi('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
  const refusedPkg = await napi('/api/packages', { action: 'install', names: ['jdk'], node: minted.id });
  ok(/runs agent 3/.test(refused.error || '') && /runs agent 3/.test(refusedPkg.error || ''),
     `...and the server refuses the same jobs, not only the buttons (${(refused.error || 'no error').slice(0, 60)})`);
  await page.evaluate(() => openPackages());
  await page.waitForSelector('.pkgtab #pkgNodeSel', { timeout: 15000 });
  await page.selectOption('.pkgtab #pkgNodeSel', minted.id);
  await page.waitForSelector('.pkgtab .pkgstale', { timeout: 15000 });
  ok(await page.$eval('.pkgtab [data-pkg="install"]', b => b.disabled),
     'the Tools tab says so too, and installs nothing onto a node that is behind');
  // Its own update is the way out and is never held.
  const upd = await napi('/api/v1/nodes', { action: 'update-agent', id: minted.id });
  const uj = upd.job ? await napi(`/api/v1/jobs?id=${upd.job}`) : null;
  ok(upd.ok && uj && uj.type === 'self-update' && uj.spec.digest === shipped.digest && uj.node === minted.id,
     `Update agent queues a self-update naming the shipped digest (${upd.job || upd.error})`);
  // ...and it stays greyed while that job is queued, through the repaint
  // that replaces the button. pressing() only covers the round trip; the
  // render is what has to know, and node_list only tracked system jobs, so
  // Update agent came back live the instant it answered.
  // Back to the Nodes tab — the block above left the Tools tab in front.
  await page.evaluate(() => openNodesTab());
  await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
  await pickNode(page, minted.id);
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /Updating/.test(
    document.querySelector(sel + ' [data-nd="update-agent"]')?.textContent || ''),
    ROW, { timeout: 10000 });
  ok(await page.$eval(`${ROW} [data-nd="update-agent"]`, b => b.disabled),
     '...and stays greyed while the update is queued, not only for the round trip');
  if (upd.job) await napi('/api/v1/jobs', { action: 'cancel', id: upd.job });
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: CENSUS, version: shipped.version, digest: shipped.digest }) });
}

// ---- a node's path mapping (§11: the record owns it) ------------------------
// What DOCKER_HOST_PATHS was: on the sandbox node's row now, validated to
// pairs, and read by the manager through the node being addressed. It used
// to draw on the ssh row only; with that kind retired (roadmap #24) it draws
// on the agent row, which is the only remote row left — devapp.host_map
// still reads it for whichever node is being addressed, so a line that drew
// nowhere would have taken an editable setting out of reach in silence.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const base = URL.replace(/\/$/, '');
  const papi = async (body) => (await fetch(base + '/api/v1/nodes', { method: 'POST', headers: H, body: JSON.stringify(body) })).json();
  const sb = (await (await fetch(base + '/api/v1/nodes', { headers: H })).json()).nodes.find(n => n.name === 'sandbox');
  const bad = await papi({ action: 'paths', id: sb.id, paths: '/workspace:relative' });
  ok(/not a \/container:\/host pair/.test(bad.error || ''), 'a mapping that is not absolute on both sides is refused');
  const local = await papi({ action: 'paths', id: 'local', paths: '/a:/b' });
  ok(/nothing to map/.test(local.error || ''), 'local has no mapping to set');
  const set = await papi({ action: 'paths', id: sb.id, paths: '/workspace:/workspace, /devdata:/mnt/user/bb-dev' });
  ok(set.ok && set.paths['/devdata'] === '/mnt/user/bb-dev',
     'the mapping is saved onto the node record as pairs');
  await page.evaluate(() => { nodesList = null; openNodesTab(); });
  await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
  await pickNode(page, sb.id);
  await page.waitForSelector(`.nodestab .ndrow[data-node="${sb.id}"] .ndpaths [data-k="paths"]`, { timeout: 15000 });
  ok(await page.$eval(`.nodestab .ndrow[data-node="${sb.id}"] .ndpaths [data-k="paths"]`, e => e.value) === '/workspace:/workspace, /devdata:/mnt/user/bb-dev',
     '...and the node\'s row shows it, editable');
  await pickNode(page, 'local');
  ok(await page.$('.nodestab .ndrow[data-node="local"] .ndpaths') === null,
     '...while local, whose paths are its own, has no such line');
}

// ...and put the sandbox's path mapping back: it lives on the node record
// now, which fresh() does not touch, so the mapping this file sets was still
// there for devapp.mjs and changed what its rows complained about.
await page.evaluate(() => nodeAct({ action: 'paths', id: nodesList.find(n => n.name === 'sandbox')?.id, paths: '' }));

// Retire what this file made, the way agent.mjs does: the store outlives a
// suite, and a node left online here becomes the DEFAULT node for the files
// after it — which sent devapp's compose at a machine that does not exist.
for (const n of (await (await fetch(URL.replace(/\/$/, '') + '/api/v1/nodes',
     { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json()).nodes){
  if (n.kind !== 'local' && n.name !== 'sandbox')
    await page.evaluate(id => nodeAct({ action: 'retire', id }), n.id);
}

// ---- the seam stays invisible on the sidebar --------------------------------
ok(await page.evaluate(() => !document.querySelector('[data-card="nodes"]')),
   'still no nodes card — nodes are a tab, not sidebar chrome');
ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
