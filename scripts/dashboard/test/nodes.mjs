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

// ---- nothing visibly changed ----------------------------------------------
// The operator's page: same cards, same tabs on offer, no new chrome. The
// phase's definition of done is that this assertion is boring.
ok(await page.evaluate(() => !document.querySelector('[data-card="nodes"]')
     && !Object.keys(TABKINDS).includes('nodes')),
   'no nodes card, no nodes tab — the seam is invisible from the page');
ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
