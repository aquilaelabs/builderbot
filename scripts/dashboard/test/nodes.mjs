// Phase 1 of the controller design (docs/nodes.md): the seam, with nothing
// visibly changing. What this file holds is the phase's whole contract:
// the store exists behind the four one-way doors it owns, the local node and
// the DOCKER_HOST mirror are seeded, work stamps the node it belongs to,
// every mutation grows an audit row, and the page the operator sees is
// exactly the page it was.
import { URL, launch, newPage, ok, done, ready, sleep, DIR, tmuxNew, animatedDuring, openFold, closeFold, patience, saveDialog, openSection } from './lib.mjs';
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

// The store the harness server booted with, read through the module itself,
// the way bb nodes reads it, so the test exercises the same path.
const readStore = (py) => JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('nodes',
  ${JSON.stringify(new globalThis.URL('../nodes.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.db.open_readonly(${JSON.stringify(DIR + '/state')})
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
// The docker host, enrolled by the harness with a token (roadmap #24:
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
   'local lists first: the one node every deployment has');

// ---- the default node runs docker, when any node says so (B113) -----------
// node_for() took the newest node with an ADDRESS, and an address is not a
// daemon: a Mac enrolled as a guest, with ssh and no docker, would have become
// the host of every instance nobody bound to a node. The census already says
// which nodes run docker, so those are preferred, with nothing asked on the
// status poll's path. Its own scratch store, so the harness's nodes stay put.
{
  const got = JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, tempfile
spec = importlib.util.spec_from_file_location('nodes',
  ${JSON.stringify(new globalThis.URL('../nodes.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(state=tempfile.mkdtemp())
def node(name, docker, created):
    mint = m.enroll_mint('user:test', name)
    census = {'cpu': 2, 'mem_mb': 4096, 'arch': 'x86_64', 'system': 'linux', 'sshd': True, 'docker': docker}
    m.enroll(m.authenticate(mint['token']), census, '10.0.0.' + str(created), user='bb')
    m._exec('UPDATE nodes SET created = ? WHERE id = ?', (created, mint['id']))
    return mint['id']
older = node('olderbox', '27.1.1', 10)
newer = node('guestmac', '', 20)
out = {'older': older, 'newer': newer, 'pick': m.node_for()}
m._exec("UPDATE nodes SET reported = json_set(reported, '$.docker', '27.1.1') WHERE id = ?", (newer,))
out['both'] = m.node_for()
m._exec("UPDATE nodes SET reported = json_set(reported, '$.docker', '') WHERE id IN (?, ?)", (older, newer))
out['neither'] = m.node_for()
# A job moving is a node row moving: what is applying on it, its last apply
# and its last runner failure are all read off the jobs, so the nodes rev
# has to move with a job's state or an open Nodes tab shows a button dead
# until somebody reloads. A log chunk is not a state and moves only the jobs rev.
r0 = m.rev()
j = m.job_add('user:test', {'node': older}, 'exec', {'argv': ['true']})
r1 = m.rev()
took = m.job_next(older, 0)
r2 = m.rev()
m.job_log(older, j.get('job'), ['hello'])
r2b = m.rev()
m.job_result(older, j.get('job'), 'succeeded', 0)
r3 = m.rev()
# A job handed to a poll whose answer was lost (assigned, and the agent never
# said a word) goes back to the queue once ASSIGN_LOST_S has passed, rather
# than holding a lane until the agent's next hello (B245).
j2 = m.job_add('user:test', {'node': older}, 'exec', {'argv': ['true']})
took2 = m.job_next(older, 0)
none = m.job_next(older, 0)
m._exec("UPDATE jobs SET started = started - 600 WHERE id = ?", (j2.get('job'),))
again = m.job_next(older, 0)
out['requeue'] = {'took': bool(took2 and took2.get('id') == j2.get('job')),
                  'held': not (none and none.get('id')),
                  'again': bool(again and again.get('id') == j2.get('job')),
                  'why': m._no_answer('j_nothing', older, 25)}
m.job_result(older, j2.get('job'), 'succeeded', 0)
# A job running long past its own timeout whose end never came back held
# the node's one slot for good (report #55): failed as lost, and the next
# job is handed out.
j3 = m.job_add('user:test', {'node': older}, 'exec', {'argv': ['true'], 'timeout': 90})
m.job_next(older, 0)
m._exec("UPDATE jobs SET state = 'running', started = started - 1000 WHERE id = ?", (j3.get('job'),))
j4 = m.job_add('user:test', {'node': older}, 'exec', {'argv': ['true']})
after = m.job_next(older, 0)
lost = m.job(j3.get('job'))
out['overdue'] = {'failed': lost['state'] == 'failed' and lost['error'].startswith('lost:'),
                  'next': bool(after and after.get('id') == j4.get('job'))}
m.job_result(older, j4.get('job'), 'succeeded', 0)
out['revs'] = {'queued': r1 > r0, 'taken': r2 > r1, 'chunk': r2b == r2, 'ended': r3 > r2,
               'job': bool(took and took.get('id') == j.get('job')), 'err': j.get('error')}
print(json.dumps(out))
`], { encoding: 'utf8' }).trim());
  ok(got.pick === got.older,
     `the default node is one whose census says docker runs there, not the newest with an address (${got.pick})`);
  ok(got.both === got.newer, '...the newest of those when more than one does');
  ok(got.neither === got.newer, '...and the newest with an address when none says so, as before');
  ok(got.requeue.took && got.requeue.held && got.requeue.again
     && /was handed exec .* ago and has not started it/.test(got.requeue.why || '') && /last dialed in/.test(got.requeue.why || ''),
     `a job handed to a poll that never started it goes back to the queue, and a wait behind it says so (${
        JSON.stringify(got.requeue)})`);
  ok(got.overdue.failed && got.overdue.next,
     `a job running far past its own timeout with no end from the node is failed as lost, and the slot goes to the next (${JSON.stringify(got.overdue)})`);
  ok(got.revs.job && got.revs.queued && got.revs.taken && got.revs.ended && got.revs.chunk,
     `a job being queued, taken and finished moves the nodes rev, and a log chunk does not, so an open Nodes tab follows a job without a reload (${JSON.stringify(got.revs)})`);
}

// ---- the seam: work says which node it belongs to --------------------------
// A compose action claims the job slot; the claim now asks node_for() and
// the answer rides the job the page polls. Fixed in phase 1 (docker work is
// the sandbox record), and the call site is what phase 4's placement slides
// into.
{
  const r = await page.evaluate(async () => (await (await fetch('/api/devapp', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'new', project: 'ep.silon', instance: 'ph1' }),
  })).json()));
  ok(!r.error, `an instance exists to act on (${r.error || 'ok'})`);
  // Read from the job ROW, not from the live slot the manager polls. The
  // first version of this raced the stub daemon: an up finishes in well
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
// parameter digest, and never the parameters, which carry tokens.
{
  await page.evaluate(() => fetch('/api/bugs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'add', project: 'alpha',
                           title: 'audit-canary-sekrit', severity: 'low' }),
  }));
  await sleep(300);
  const tail = readStore('m.db.audit_tail(80)');
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
    `m.db._rows("SELECT principal FROM audit WHERE action = ?", ("node-seed",))`);
  ok(seed.length === 1 && seed[0].principal === 'system',
     'the seed itself is on the record, once, as system');
}

// ---- bb nodes --------------------------------------------------------------
{
  const out = execFileSync('bash', ['scripts/bb', 'nodes'],
    { encoding: 'utf8', cwd: REPO,
      env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  ok(!/\blocal\b/.test(out) && /sandbox · stub/.test(out),
     'bb nodes prints the enrolled machines, read-only. Never the controller, which is registry plumbing');
}

// ---- phase 2: the Nodes tab ------------------------------------------------
{
  await page.evaluate(() => { const c = document.getElementById('cardTools');
    if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
  await page.click('#bNodes');
  await page.waitForSelector('.nodestab .ndrow', { timeout: 15000 });
  ok((await nodeOptions(page)).length === 1,
     'the Nodes tab lists the enrolled machines, and not this container');
  // ...and with nothing enrolled it says so where the rows would be, rather
  // than an empty picker over an empty page. Driven by handing the page a
  // registry holding only the controller's own record, which is what a fresh
  // install has.
  const bare = await page.evaluate(async () => {
    const was = nodesList;
    nodesList = was.filter(n => n.kind === 'local');
    nodesRev++; drawPanes();
    const out = { none: !!document.querySelector('.nodestab .ndnone'),
                  rows: document.querySelectorAll('.nodestab .ndrow').length,
                  picker: !!document.querySelector('.nodestab #ndPick'),
                  enroll: !!document.querySelector('.nodestab #ndEnroll') };
    nodesList = was; nodesRev++; drawPanes();
    return out;
  });
  ok(bare.none && bare.rows === 0 && !bare.picker && bare.enroll,
     `...and with none enrolled it says so, with Enroll node still there (${JSON.stringify(bare)})`);
  await page.waitForSelector('.nodestab .ndrow', { timeout: 10000 });
  // Adding a node by ssh address is retired (roadmap #18): it existed only
  // because compose ran from this container over ssh, so a machine needed a
  // key as well as a token and a token-only node could do everything except
  // docker. Compose is an agent job now, so the tab offers one way in.
  ok(await page.$('#ndAdd') === null && await page.$('#ndEnroll') !== null,
     'the tab offers enrollment and nothing else: no Add ssh node');
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
      census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', sshd: true,
                git: 'git version 2.30.2' } },
      { Authorization: 'Bearer ' + mint.token, 'Content-Type': 'application/json' });
  }
  const added = await page.evaluate(async () => {
    await loadNodes();
    return nodesList.find(n => n.name === 'buildbox');
  });
  ok(added && added.kind === 'agent',
     'a machine is enrolled with a token, and arrives as an agent node');
  // A project on two nodes (R82): the row carries a chooser row per node,
  // each saying whether a session can start there, and a terminal asked
  // for with :n:NODE is judged on that node; a node outside the set falls
  // to the primary. buildbox reports no session half, so it refuses.
  {
    const base = URL.replace(/\/$/, '');
    const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
                'Content-Type': 'application/json' };
    const post = async (path, body) => (await fetch(base + path,
      { method: 'POST', headers: H, body: JSON.stringify(body) })).json();
    const get = async path => (await fetch(base + path, { headers: H })).json();
    const sb = (await get('/api/v1/nodes')).nodes.find(n => n.name === 'sandbox');
    await post('/api/prefs', { project: 'beta', node: sb.id, nodes: [sb.id, added.id] });
    const rows = (await get('/api/status')).projects.find(p => p.name === 'beta').session_nodes || [];
    ok(rows.length === 2 && rows[0].id === sb.id && rows[1].id === added.id && rows[1].where === 'refused'
       && /buildbox/.test(rows[1].why),
       `a project on two nodes carries a row per node for the chooser, each judged (${JSON.stringify(rows.map(r => [r.name, r.where]))})`);
    const t = await fetch(base + '/term/?arg=' + encodeURIComponent('claude:beta:n:' + added.id), { headers: H });
    const body = await t.text();
    ok(t.status === 503 && /buildbox/.test(body), `...and a terminal asked for on the second node is judged there (${t.status})`);
    const t2 = await fetch(base + '/term/?arg=' + encodeURIComponent('claude:beta:n:n_notinset'), { headers: H });
    ok(!/buildbox/.test(await t2.text()), '...while a node outside the set falls to the primary');
    // A build from the dashboard falls over to a node of the set that is
    // up (R82 step 6): buildbox's enrolment counted as a heartbeat, so its
    // last one is aged past the live window first, and put back after, since
    // the docker tests below want it dialing in; then with it as the primary
    // the job runs on the sandbox and its spec says which it stood in for.
    const agentSeen = when => execFileSync('python3', ['-c', `
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("nodes", "${REPO}/scripts/dashboard/nodes.py")
m = importlib.util.module_from_spec(spec); sys.modules["nodes"] = m; spec.loader.exec_module(m)
m.configure(state="${DIR}/state")
ag = m.node("${added.id}")["agent"]; ag["last_seen"] = ${when} or int(time.time())
m._exec("UPDATE nodes SET agent = ? WHERE id = ?", (json.dumps(ag), "${added.id}"))`],
      { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
    agentSeen(1);
    await post('/api/prefs', { project: 'beta', node: added.id, nodes: [added.id, sb.id] });
    const ran = await post('/api/v1/jobs', { action: 'run', project: 'beta', argv: ['true'] });
    const rj = ran.job ? await get('/api/v1/jobs?id=' + ran.job) : {};
    ok(ran.node === sb.id && rj.spec?.fell_over === added.id,
       `a build whose primary is not up runs on the next node of the set that is, and says which it stood in for (${ran.node || ran.error}, ${rj.spec?.fell_over})`);
    if (ran.job) await post('/api/v1/jobs', { action: 'cancel', id: ran.job });
    await post('/api/prefs', { project: 'beta', node: '', nodes: [] });
    agentSeen(0);
    // Why an idle session's token was not kept here, as the agent said it
    // on its hello (B419): on the node's row, in the warning color, with when
    // one was last kept; the node's journal was the only place it went.
    execFileSync('python3', ['-c', `
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("nodes", "${REPO}/scripts/dashboard/nodes.py")
m = importlib.util.module_from_spec(spec); sys.modules["nodes"] = m; spec.loader.exec_module(m)
m.configure(state="${DIR}/state")
ag = m.node("${added.id}")["agent"]
ag["keep"] = m.keep_clean({"said": [{"at": int(time.time()) - 120, "key": "u_1/alpha",
                                     "msg": "bb token keep failed (exit 1): the session token was not kept"}],
                           "ok": int(time.time()) - 7200})
m._exec("UPDATE nodes SET agent = ? WHERE id = ?", (json.dumps(ag), "${added.id}"))`],
      { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
    await page.evaluate(() => typeof loadNodes === 'function' && loadNodes());
    await pickNode(page, added.id);
    const keepRow = await page.waitForFunction(id => document.querySelector(`.nodestab .ndrow[data-node="${id}"] .ndkeep`)?.textContent || '',
      added.id, { timeout: 15000 }).then(h => h.jsonValue()).catch(() => '');
    ok(/session tokens: bb token keep failed \(exit 1\): the session token was not kept, .*ago; one was last kept .*ago/.test(keepRow),
       `why a session's token was not kept is on the node's row, with when one last was (${keepRow})`);
  }
  ok(['docker-host', 'package-build', 'deploy-target'].every(c => added.capabilities.includes(c)),
     '...and it does everything, without anybody being asked which');
  // Nothing keeps the nodes and the controller on one git: it is installed
  // once at enrollment from whatever the distribution packages, and on a
  // guest node the machine is its owner's. So the row SAYS which one is
  // there, and says plainly when it is below the floor the Git view's merge
  // needs, rather than leaving a fleet of them unknowable.
  ok(added.reported?.git === 'git version 2.30.2',
     `a node's git reaches the controller through the census (${added.reported?.git})`);
  const gitRow = await page.evaluate(() => nodeGit(
    { kind: 'agent', reported: { git: 'git version 2.30.2' } }));
  ok(/2\.30\.2/.test(gitRow) && /warn/.test(gitRow) && /older than 2\.38/.test(gitRow),
     `...and one below the floor is flagged, saying whose job the upgrade is (${
       gitRow.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80)})`);
  ok(!/warn/.test(await page.evaluate(() => nodeGit(
       { kind: 'agent', reported: { git: 'git version 2.43.0' } }))),
     '...while one that clears it is just stated');
  // The mechanism underneath is untouched (§15 door 7): a restricted node is
  // still expressible, it is just not something the UI makes.
  await page.evaluate(id => nodeAct({ action: 'update', id,
    fields: { capabilities: ['package-build'] } }), added.id);
  await page.waitForFunction(id => nodesList.find(n => n.id === id)
    ?.capabilities.length === 1, added.id, { timeout: 10000 });
  ok(true, 'a deliberately restricted node can still be written through the API');
  {
    // A deliberate refusal: the server answers 400, and the browser logs
    // every non-2xx as a console error. Asserted, then absolved: the final
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
    `m.db._rows("SELECT action, principal FROM audit WHERE target = ?", ("${added.id}",))`);
  ok(acts.some(r => r.action === 'node-enroll-mint')
     && acts.some(r => r.action === 'node-update')
     && acts.some(r => r.principal === 'user:test'),
     'every node mutation wrote an audit row, naming the account that made it');
}

// ---- phase 2: the docker manager's picker ----------------------------------
{
  // Opened with the node list DELIBERATELY not loaded, because that is the
  // state a fresh page is in: the picker is drawn from that list, and the
  // tab used to watch only its own revision, so the list landed, nothing
  // redrew, and a box with two nodes showed no picker until something else
  // happened to repaint the tab. The tab asks for the list on open now and
  // watches its revision, and this is the case that proves it.
  await page.evaluate(() => { nodesList = null; hideTab((tabs.find(t => t.kind === 'docker') || {}).id); });
  await page.evaluate(() => openDocker());
  await page.waitForSelector('.dmtab .dmpick', { timeout: 15000 });
  // Waited for AND read in one go: the tab redraws from the poll, so a list
  // read in a second round trip can land on the moment between two draws and
  // come back empty (B99's family; this file has had three).
  const opts = await page.waitForFunction(() => {
    const os = [...document.querySelectorAll('.dmtab .dmpick option')];
    return os.length ? os.map(o => o.textContent.trim()) : false;
  }, null, { timeout: 15000 }).then(h => h.jsonValue());
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
  await page.waitForFunction(() => {
    const s = document.querySelector('#dmNode');
    const n = (nodesList || []).find(x => x.name === 'buildbox');
    if (!s || !n) return false;
    s.value = n.id;
    s.dispatchEvent(new Event('change'));
    return true;
  }, null, { timeout: 15000 });
  await page.waitForFunction(() => dockerList && dockerList.blind === true,
                             null, { timeout: 30000 });
  await page.evaluate(() => { dockerRev++; drawPanes(); });
  // Waited for and read in one go: the tab repaints from the poll, and this
  // read used to land between two draws about one run in several.
  const emptyWhy = await page.waitForFunction(() => {
    const e = document.querySelector('.dmtab .empty');
    return e && e.textContent.trim() ? e.textContent : false;
  }, null, { timeout: 15000 }).then(h => h.jsonValue());
  // FOUR refusals, not three. The fixture kills the host, and which of
  // available()'s two probes notices first depends on the box: `docker
  // version` failing gives "does not answer", and `docker version` answering
  // while `docker info` does not gives "answers but will not say what it is".
  // Both are the thing under test (a reason on screen instead of a spinner),
  // and listing only three made the fourth read as a failure in a full run
  // while the file passed alone.
  ok(/not a BuilderBot sandbox|does not answer|will not say what it is/.test(emptyWhy),
     `an unreachable node shows its reason, not a spinner (${emptyWhy.slice(0, 50)})`);
  await page.waitForSelector('.dmtab .dmpick select', { timeout: 15000 });
  ok(await page.$eval('.dmtab .dmpick select', s => !s.disabled),
     '...with the picker still live: the way back is the way in');
  // and back: the sandbox's last-known answer paints instantly from cache.
  // Waited for at the point of USE, not at the assertion above: the picker
  // is drawn only while nodesList holds more than one node, and a reload of
  // that list between the two takes the element with it (B69's sibling).
  // Found and used in ONE evaluate, because the gap between two is the bug
  // this comment is about: the wait said the picker was there and the list
  // reloaded before the next round trip could touch it, so the set threw on
  // null about one run in several (B99's family, a site the report did not
  // name). A predicate with a side effect, deliberately.
  await page.waitForFunction(() => {
    const s = document.querySelector('#dmNode');
    // The bare name, not window's: a top-level `let` in a classic script
    // goes into the global LEXICAL scope and is not a property of window.
    const n = (nodesList || []).find(x => x.name === 'sandbox');
    if (!s || !n) return false;
    s.value = n.id;
    s.dispatchEvent(new Event('change'));
    return true;
  }, null, { timeout: 15000 });
  await page.waitForFunction(() => dockerList && !dockerList.blind,
                             null, { timeout: 30000 });
  ok(true, 'switching back to the live node recovers without a reload');
  // ...and the tab REMEMBERS which node that was. The pick lived in a page
  // variable, so a reload went back to whichever node is the default, not
  // the one anybody chose, and reliably the wrong entry in the picker. It
  // rides in the tab's arg now, which is the part of a tab that is saved,
  // and `identity()` for a kind that is not `multi` is the kind alone, so
  // the arg can move without splitting the tab in two.
  const want = await page.evaluate(() =>
    (nodesList || []).find(x => x.name === 'sandbox')?.id);
  ok(await page.evaluate(() => tabs.find(t => t.kind === 'docker')?.arg) === want,
     'the docker tab carries the node it is on, so it is saved with the layout');
  // The line under the picker names the daemon the PICKER is on, which it
  // read off the status poll, and the poll is the default node's answer, so
  // it named a machine the tab was not talking to, in an address. Read
  // BEFORE the reload below, which throws the answer away on purpose.
  await page.waitForFunction(() => (dockerList?.src?.where || '').length > 0, null, { timeout: 10000 }).catch(() => {});
  ok(await page.evaluate(() => (dockerList?.src?.where || '').length > 0),
     'the manager\'s own answer says which daemon it is about');
  ok(await page.evaluate(w => {
       dockerNode = '';                        // as a fresh page would start
       dockerList = null;
       TABKINDS.docker.open();
       return dockerNode === w;
     }, want),
     '...and the tab\'s first draw picks the saved node up, not the default');
  await page.evaluate(() => { const t = tabs.find(x => x.kind === 'docker');
                              if (t) hideTab(t.id); });
}

// ---- phase 2: the settings graduation ---------------------------------------
{
  await page.evaluate(() => toggleUiMenu(true));
  await page.waitForSelector('#uiProfile', { timeout: 10000 });
  ok(await page.evaluate(() => !document.querySelector('#uiMenu #logDays')),
     'the gear keeps appearance only: the log setting moved out');
  await page.evaluate(() => toggleUiMenu(false));
  await page.evaluate(() => { const c = document.getElementById('cardAdmin');
    if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
  await page.click('#bSettings');
  await page.waitForSelector('.settingstab .logdays #logDays', { timeout: 15000 });
  ok(true, 'Controller settings on the Administration card opens the Settings tab, with the log policy on it');
  ok(await page.$eval('.settingstab', e => !/template|environment|DOCKER_HOST/.test(e.textContent)),
     '...which describes what is on it and nothing about what lives elsewhere');
  // The idle rule for Claude sessions (idle.py): a controller setting the
  // page applies, and this container enforces on its own tmux. The suite's
  // server counts a "minute" as a second (BUILDERBOT_IDLE_UNIT), so a rule
  // of one minute ends an untouched session within a few seconds. Claude
  // sessions only: the shell beside it stays.
  ok(await page.$eval('.settingstab #idleMin', e => e.value === '0'),
     'the Settings tab carries the idle rule, off by default');
  tmuxNew('claude-idletest'); tmuxNew('shell-idletest');
  const set = m => page.evaluate(async m => (await (await fetch('/api/idle', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ minutes: m }) })).json()), m);
  const on = await set(1);
  ok(on.ok && on.minutes === 1, 'a rule of one minute is accepted');
  const alive = n => { try { execFileSync('tmux', ['has-session', '-t', '=' + n], { stdio: 'ignore' }); return true; }
                       catch { return false; } };
  let gone = false;
  for (let i = 0; i < 40 && !gone; i++){ await sleep(300); gone = !alive('claude-idletest'); }
  ok(gone && alive('shell-idletest'),
     'an idle Claude session is ended by the rule, and the shell beside it is left alone');
  const off = await set(0);
  ok(off.ok && off.minutes === 0, '...and 0 turns the rule off again');
  try { execFileSync('tmux', ['kill-session', '-t', '=shell-idletest'], { stdio: 'ignore' }); } catch {}
}

// ---- the configuration plane on the row (phase 5) ---------------------------
// A node that enrolled as a sandbox gets a fold: mounts, stores and network
// as the operator wants them, drawn against what the agent reports, with
// Save keeping the record and Apply queuing the system job. Enrolled here by
// hand (the census is a body) because the real agent has its own suite.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const base = URL.replace(/\/$/, '');
  const napi = async (path, body, headers = H) => (await fetch(base + path, body === undefined
    ? { headers } : { method: 'POST', headers, body: JSON.stringify(body) })).json();
  const minted = await napi('/api/v1/nodes', { action: 'enroll', name: 'shed' });
  // The digest this controller ships, so the fixture node enrolls CURRENT.
  // Everything below drives Apply, the runner and installs, all of which are
  // held while an agent is behind: the stale half is its own block at the
  // end, where it can hold them without breaking the rest.
  const shipped = (await napi('/api/v1/nodes')).agent || {};
  // The census this node reports, kept as one object: a hello REPLACES it,
  // so a later poke that sends a partial one silently takes the node's
  // mounts and address away, which is a confusing way to fail four tests
  // further down.
  const CENSUS = { cpu: 4, mem_mb: 8192, os: 'linux x86_64 Ubuntu', system: 'linux', arch: 'x86_64',
              sandbox: true, administers: true, stores: { data: { path: '/var/lib/builderbot/data', free_mb: 5000, total_mb: 9000 },
                                       toolchains: { path: '/var/lib/builderbot/toolchains', free_mb: 40000, total_mb: 90000 },
                                       artifacts: { path: '/var/lib/builderbot/artifacts', free_mb: 30000, total_mb: 90000 } },
              toolchains: { flutter: '3.24.0', node: 'v22.1.0' },
              // What `bb toolchains versions` says on the node: the controller's
              // own generator, run there. The toolchains dict above is a
              // placement summary and describes the same store differently,
              // which is the disparity this replaces.
              toolchain_versions: { flutter: '6655482e', 'android:ndk': '29.0.14206865' },
              // What the toolchain store actually holds, which is what the
              // Tools tab decides `installed` from; the census summary
              // above is a placement hint, not an inventory.
              store_dirs: { top: ['flutter', 'node'], android: [] },
              // The android system images in the node's own toolchain store,
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
  // A session's token slides forward on every answer it gets, so one that is
  // WORKING never runs out. One idle past twelve hours has nothing to slide
  // it, and a dead token is deliberately never renewed, since that refusal is
  // what makes the life mean anything for one that leaked. So the machine the
  // session runs on is handed a fresh one on the beat it already has (R27).
  {
    const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
    // The tmux sessions ride the heartbeat, so they are reported the way a
    // node reports them and the hello that follows reads them back.
    const beat = sessions => fetch(base + '/api/v1/agent/work', { method: 'POST',
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample: { cpu_pct: 1, mem_mb: 8192, mem_used_mb: 512, sessions },
                             running: [], wait: 0 }) });
    await beat([{ name: `${uid}~claude-alpha` }, { name: `${uid}~shell-3` }]);
    const hello = await napi('/api/v1/agent/hello', {
      census: CENSUS, version: shipped.version, digest: shipped.digest },
      { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' });
    const toks = hello.session_tokens || [];
    ok(toks.length === 1 && toks[0].project === 'alpha' && toks[0].uid === uid,
       `the heartbeat carries a fresh token for each Claude session on the node, and only those (${
         JSON.stringify(toks.map(t => t.project))})`);
    // Worth being a real credential rather than a shape: the whole point is
    // that the session can go on using it.
    const asSession = await (await fetch(URL.replace(/\/$/, '') + '/api/status',
      { headers: { Authorization: 'Bearer ' + toks[0].token } })).json();
    ok(JSON.stringify((asSession.projects || []).map(p => p.name)) === '["alpha"]',
       `...and it is a working token for that project alone (${
         (asSession.projects || []).map(p => p.name).join(',') || 'none'})`);
    await beat([{ name: `${uid}~shell-3` }]);
    const none = await napi('/api/v1/agent/hello', {
      census: CENSUS, version: shipped.version, digest: shipped.digest },
      { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' });
    ok((none.session_tokens || []).length === 0,
       '...while a node running no Claude session is handed none');
  }
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
      gpu_pct: 42, gpu_mem_used_mb: 3072, gpu_mem_mb: 8192,
      stores: { data: { free_mb: 5000, total_mb: 9000 },
                toolchains: { free_mb: 40000, total_mb: 90000 },
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
  // The controller is not on this tab at all now, a stronger version of the
  // claim this used to make by picking it and finding no storage section and
  // no agent to update.
  ok(!(await nodeOptions(page)).includes('local')
     && await page.$('.nodestab .ndrow[data-node="local"]') === null,
     'the controller cannot be picked here: it runs no work and has nothing this tab configures');
  // Nothing to open: the storage and network settings are always shown now,
  // one node at a time, chosen in the bar.
  await openSection(page, 'nodes:storage', ROW);
  await page.waitForSelector(`${ROW} .ndconf [data-madd]`, { timeout: 5000 });
  ok(await page.$eval(`${ROW} .ndconf`, e => /now 10\.0\.0\.40\/24 on ens3 via 10\.0\.0\.1/.test(e.textContent)),
     'it reports the address the node is on');
  // The census's numbers as meters rather than as a sentence: one per store,
  // labeled, with the free space on the right.
  const meters = await page.$$eval(`${ROW} .ndmeter`, ms => ms.map(m => ({
    label: m.querySelector('.lbl').textContent,
    val: m.querySelector('.val').textContent,
    width: m.querySelector('.fill').style.width })));
  ok(meters.some(m => m.label === 'toolchains' && /GB free/.test(m.val))
     && meters.some(m => m.label === 'data') && meters.some(m => m.label === 'artifacts')
     && !meters.some(m => /missing/.test(m.val))
     && meters.some(m => m.label === 'cpu') && meters.some(m => m.label === 'memory')
     && meters.every(m => /^\d+%$/.test(m.width)),
     `each store is a meter with its headroom (${meters.map(m => m.label + ' ' + m.val).join(', ')})`);
  ok(meters.some(m => m.label === 'gpu' && m.val === '42%' && m.width === '42%')
     && meters.some(m => m.label === 'vram' && m.val === '3072MB / 8192MB' && m.width === '38%'),
     'a node whose card answers shows how busy it is and how much of its memory is taken, as two more meters');
  ok(await page.$eval(`${ROW} .ndtools`, e => /flutter/.test(e.textContent) && /node/.test(e.textContent)),
     'the row shows what is installed on the node, which is what a project bound to it can build');
  // The runner is a tool of its own since R121 (the operator, 4 Oct): the same
  // section, drawn and wired on the CI runner tab for the picked node.
  await page.evaluate(id => openRunnerTab(id), minted.id);
  const RROW = `.runnertab .ndrow[data-node="${minted.id}"]`;
  await page.waitForSelector(`${RROW} .ndconf`, { timeout: 15000 });
  const GH = 'github.com-example-org', RUN = `${RROW} .ndrun[data-slot="${GH}"]`;
  ok(await page.$eval(`${RROW} .ndrunnone`, e => /no runner on this node/.test(e.textContent))
     && await page.$(`${RROW} .addbar[data-add="runner"] [data-nrunnershow]`) !== null
     && await page.$(`${RROW} [data-k="runner:url"]`) === null,
     'the CI runners section says there is none and adds one at the top, a button until pressed');
  await page.click(`${RROW} [data-nrunnershow]`);
  await page.waitForSelector(`${RROW} [data-k="runner:url"]`, { timeout: 10000 });
  ok(await page.$eval(`${RROW} [data-k="runner:forge"]`, s => s.value === '' && [...s.options].some(o => o.value === 'gitea'))
     && await page.$(`${RROW} [data-nrunnercancel]`) !== null,
     '...and the form unrolls in the band with the host kind read from the address unless picked, and a Cancel');
  // Adding a runner is its own press, so the token never rides the install:
  // it goes to the root-only store, the row appears with Install awake.
  await page.fill(`${RROW} [data-k="runner:url"]`, 'https://github.com/example-org');
  await page.fill(`${RROW} [data-k="runner:token"]`, 'github_pat_TESTTOKEN1234');
  await page.fill(`${RROW} [data-k="runner:labels"]`, 'gpu');
  await page.click(`${RROW} [data-nrunneradd]`);
  await page.waitForSelector(RUN, { timeout: 10000 });
  ok(await page.$eval(`${RUN} .ndrunstate`, e => /not installed/.test(e.textContent) && !/no token stored/.test(e.textContent))
     && await page.$eval(`${RUN} [data-nrunner="install"]`, b => !b.disabled && /Install runner/.test(b.textContent))
     && !!(await page.$(`${RUN} [data-nrunnerforget]`))
     && await page.$(`${RROW} [data-k="runner:token"]`) === null && await page.$(`${RROW} [data-nrunnershow]`) !== null,
     'Add runner keeps the token root-only, rolls the form up, and lists the runner with Install awake and Forget token beside it');
  // Dead the moment it is pressed, not when the answer comes back. Every
  // action here awaits a POST, then loadNodes(), then a repaint: a second
  // or two in which the button looked untouched, so there was no telling a
  // press that landed from one that missed. Read synchronously after the
  // click dispatches, before any await resolves.
  const pressedState = await page.evaluate(sel => {
    const b = document.querySelector(sel + ' [data-nrunner="install"]');
    b.click();
    return b.disabled;
  }, RUN);
  ok(pressedState === true, 'a node action goes dead the instant it is pressed, not when it answers');
  // On the CI runner tab the runner's own state line is what says it.
  await page.waitForFunction(sel => /installing now/.test(
    document.querySelector(sel + ' .ndrunstate')?.textContent || ''), RUN, { timeout: 10000 });
  // The runner section says so itself, in its own state line, with the
  // buttons it has taken away: the operator pressed Install, then Remove,
  // and read nothing but two dead buttons while the first job ran.
  ok(await page.$eval(`${RUN} .ndrunstate`, e => /installing now/.test(e.textContent))
     && await page.$eval(`${RUN} [data-nrunner="install"]`, b => b.disabled),
     'while the install runs the runner\'s row says installing now, beside the buttons it has disabled');
  const rj = (await napi('/api/v1/jobs?active=1')).jobs.find(j => j.type === 'system' && j.spec.apply === 'runner');
  ok(rj && rj.node === minted.id && rj.spec.config.url === 'https://github.com/example-org'
     && rj.spec.config.labels.includes('shed') && rj.spec.config.labels.includes('gpu') && rj.spec.config.slot === GH,
     `Install runner queues the system job for that runner with the node's name among the labels (${rj?.spec?.config?.labels?.join(',')})`);
  await napi('/api/v1/jobs', { action: 'cancel', id: rj.id });
  // The cancel reaches the runner's own state line on the CI runner tab.
  for (let i = 0; i < 40; i++){
    if (await page.evaluate(sel => !/installing now/.test(document.querySelector(sel + ' .ndrunstate')?.textContent || ''), RUN)) break;
    await page.evaluate(() => loadNodes());
    await page.waitForTimeout(500);
  }
  // A failed install says so on the section, with the reason the server
  // took from its log. Drawn and read in one step, so a poll cannot repaint
  // the row from the real payload in between.
  const failedVerdict = await page.evaluate(({ id, sel }) => {
    const n = nodesList.find(x => x.id === id);
    const keep = { f: n.runner_failed, s: n.services };
    n.runner_failed = { id: 'j_x', slot: 'github.com-example-org', ended: 1789350000, why: "Libicu's dependencies is missing for Dotnet Core 6.0" };
    n.services = { ...(n.services || {}), runners: { 'github.com-example-org': { want: true, labels: [], url: 'https://github.com/example-org' } } };
    nodesRev++; drawPanes();
    const e = document.querySelector(sel + ' .ndrun[data-slot="github.com-example-org"] .ndrunstate');
    const out = { text: e?.textContent || '', bad: !!e?.classList.contains('bad') };
    n.runner_failed = keep.f; n.services = keep.s; nodesRev++; drawPanes();
    return out;
  }, { id: minted.id, sel: RROW });
  ok(/install failed (?!: )\S/.test(failedVerdict.text) && /Libicu/.test(failedVerdict.text) && failedVerdict.bad,
     `the Nodes tab says a runner install failed, when, and why, in red (${failedVerdict.text.slice(0, 80)})`);
  const removingVerdict = await page.evaluate(({ id, sel }) => {
    const n = nodesList.find(x => x.id === id);
    const keep = { a: n.applying, s: n.services };
    n.applying = { id: 'j_y', what: 'runner', slot: 'github.com-example-org' };
    n.services = { ...(n.services || {}), runners: { 'github.com-example-org': { want: false, labels: [], url: 'https://github.com/example-org' } } };
    nodesRev++; drawPanes();
    const e = document.querySelector(sel + ' .ndrun[data-slot="github.com-example-org"] .ndrunstate');
    const out = e?.textContent || '';
    n.applying = keep.a; n.services = keep.s; nodesRev++; drawPanes();
    return out;
  }, { id: minted.id, sel: RROW });
  ok(/removing now/.test(removingVerdict), `...and a remove in flight says removing now (${removingVerdict.slice(0, 60)})`);
  // Installed and listening are different states, and the difference is the
  // one that matters: a registered runner with no listener looks healthy
  // right up until a workflow sits in "Waiting for a runner". The operator's
  // own node was in exactly this state.
  const runnerCensus = svc => fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: { ...CENSUS, services: svc },
                           version: shipped.version, digest: shipped.digest }) });
  // A runner with no slot of its own joins the record's one runner rather
  // than making a second row.
  await runnerCensus({ runners: [{ installed: true, active: false, busy: false,
                                   name: '', labels: ['builderbot', 'shed'] }] });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /NOT listening/.test(
    document.querySelector(sel + ' .ndrunstate')?.textContent || ''), RUN, { timeout: 10000 });
  ok(await page.$eval(`${RUN} .ndrunstate`, e => /no workflow will reach it/.test(e.textContent)
       && /registration may not have finished/.test(e.textContent) && e.classList.contains('bad'))
     && await page.$$eval(`${RROW} .ndrun`, rows => rows.length === 1),
     'a runner that is registered but not listening says so, rather than reading as installed, on the one row');
  await runnerCensus({ runners: [{ slot: GH, installed: true, active: true, busy: true,
                                   name: 'shed', url: 'https://github.com/example-org',
                                   labels: ['builderbot', 'shed'] }] });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => document.querySelector(sel + ' .ndrunbusy'), RUN, { timeout: 10000 });
  ok(await page.$eval(`${RUN} .ndrunstate`, e => /running a job/.test(e.textContent)
       && /registered as shed/.test(e.textContent)),
     '...and one that is working says which job-taking state it is in, by name');
  // The label is the only thing that pins a workflow to THIS machine.
  // `self-hosted` alone matches the controller and every other node, so
  // GitHub sends the job to whichever is idle (roadmap #19).
  ok(await page.$eval(`${RROW} .ndrunpin`, e =>
       /runs-on: \[self-hosted, shed\]/.test(e.textContent)),
     '...and the section prints the exact runs-on line that lands a job here');
  // The runner belongs above the mounts: it is the thing the operator is
  // most often here to check, and it was below three editors. The plane is
  // sections now (one fold per concern, a status on each summary), and
  // the order still holds.
  // ...and the Nodes tab no longer carries it: a line there opens this tab.
  await page.evaluate(() => openNodesTab());
  await page.waitForSelector(`${ROW} .ndconfbody`, { timeout: 15000 });
  ok(await page.$eval(`${ROW} .ndconfbody`, e => ![...e.querySelectorAll(':scope > details.sect > summary .t')]
       .some(t => t.textContent.trim() === 'CI runners'))
     && await page.$(`${ROW} [data-ndrunner]`) !== null,
     '...and the Nodes tab has no runner section, only a line that opens the CI runner tab on this node');
  ok(await page.$eval(`${ROW} .ndconfbody`, e =>
       [...e.querySelectorAll(':scope > details.sect > summary .sst')].every(s => s.textContent.trim())),
     '...every section says its state on its summary, so a phone reads the headings and picks one');
  // Every section open by default, and shutting one leaves the others open
  // (the operator, 8 Oct: too much was hidden in folds).
  {
    const sects = `${ROW} .ndconfbody > details.sect`;
    const before = await page.$$eval(sects, ds => ds.map(d => d.open));
    ok(before.length > 1 && before.every(Boolean), `the Nodes tab has every section open (${before})`);
    await page.$$eval(sects, ds => ds[1].querySelector(':scope > summary').click());
    await page.waitForFunction(s => !document.querySelectorAll(s)[1].open, sects, { timeout: 5000 }).catch(() => {});
    const open = await page.$$eval(sects, ds => ds.filter(d => d.open).length);
    ok(open === before.length - 1, `...and shutting one leaves the rest open (${open} open of ${before.length})`);
    await page.$$eval(sects, ds => ds[1].querySelector(':scope > summary').click());
    await page.waitForFunction(s => document.querySelectorAll(s)[1].open, sects, { timeout: 5000 }).catch(() => {});
  }
  // Every fold on this page is driven rather than left to the browser's
  // instant snap: the memories, the bug reports, the version tab's fold, the
  // Docker manager's wiring. Sections shipped without it and were the one
  // kind that jumped.
  {
    // An open one: every section is open by default (8 Oct).
    const key = await page.$eval(`${ROW} .ndconfbody > details.sect[open]`, d => d.dataset.sect);
    const sel = `${ROW} .ndconfbody > details.sect[data-sect="${key}"]`;
    const moved = await animatedDuring(page, () => closeFold(page, sel));
    ok(moved.some(c => /\bsect\b/.test(c)),
       '...and a section folds with the same tween as every other fold here');
    await openFold(page, sel);          // put it back for what reads inside it
  }
  // The sidebar's Runner card carries every node with a runner, not only
  // this container's: a workflow lands on whichever runner its runs-on
  // matches, and GitHub was the only place that answer existed.
  await runnerCensus({ runners: [{ slot: GH, installed: true, active: true, busy: false,
                                   name: 'shed', url: 'https://github.com/example-org',
                                   labels: ['builderbot', 'shed'] }] });
  // "shed" is not the condition: the card has carried the name since the
  // install press above, on whichever poll landed since, and refresh() asked
  // while the fifteen-second poll is out returns at once and re-polls after
  // it, so the first draw here can be from an answer computed before this
  // hello. Wait for the state the assertion is about (B73).
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => {
    const t = document.getElementById('runner')?.textContent || '';
    return /listening, idle/.test(t) && /runs-on: \[self-hosted, shed\]/.test(t);
  }, null, { timeout: 15000 });
  ok(await page.$eval('#runner', e => /listening, idle/.test(e.textContent)
       && /runs-on: \[self-hosted, shed\]/.test(e.textContent)),
     'the Runner card carries a node runner, with the runs-on that lands a job on it');
  await runnerCensus({});
  // A node with mounts and no saved config opens on the ones it reports.
  // An empty editor for a machine with three shares was the first thing the
  // operator hit.
  const seeded = await page.$$eval(`${ROW} .ndmount [data-k="source"]`, es => es.map(e => e.value));
  ok(seeded.includes('nas:/mnt/user/old'),
     `the mount editor opens on what the node reports, not on an empty list (${seeded.join(', ')})`);
  ok(await page.$eval(`${ROW} .ndconf`, e => /As the node reports them/.test(e.textContent)),
     '...and says they came from the node rather than from anything saved here');
  // The new row lands after the seeded ones.
  const last = seeded.length;
  await openSection(page, 'nodes:storage', ROW);
  await page.click(`${ROW} [data-madd]`);
  await page.waitForSelector(`${ROW} .ndmount[data-i="${last}"] [data-k="source"]`, { timeout: 5000 });
  ok(await page.evaluate(() => document.activeElement?.dataset.k === 'source'),
     '+ mount adds a row and puts the caret in it');
  await page.fill(`${ROW} .ndmount[data-i="${last}"] [data-k="source"]`, 'nas:/mnt/user/appdata');
  await page.fill(`${ROW} .ndmount[data-i="${last}"] [data-k="path"]`, '/mnt/appdata');
  await page.fill(`${ROW} [data-k="store:cache"]`, '/scratch/cache');
  ok(await page.$(`${ROW} [data-k="store:artifacts"]`) !== null,
     'the fold carries the artifacts store: this node\'s copy of what projects built');
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
  // A job's log is the only copy of what a node's job wrote, it lives in the
  // controller's store, and until R17 step 1 nothing deleted one: a build's
  // log runs to megabytes, so a busy project filled the database quietly. The
  // ROW stays and only the chunks go, because a list that forgets a build ran
  // is worse than one that cannot show its output.
  {
    const py = (code) => execFileSync('python3', ['-c', code],
      { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } }).trim();
    const out = py(`
import importlib.util, sys, time
spec = importlib.util.spec_from_file_location("nodes", "${REPO}/scripts/dashboard/nodes.py")
m = importlib.util.module_from_spec(spec); sys.modules["nodes"] = m; spec.loader.exec_module(m)
m.configure(state="${DIR}/state")
now = int(time.time())
# One project, more finished jobs than the policy keeps, each with a log.
for i in range(m.JOB_LOG_KEEP + 6):
    jid = f"j_ret{i:04d}"
    m._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source,"
            " spec, outputs, state, node, exit_code, queued, ended) VALUES"
            " (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (jid, "exec", "retproj", "test", "{}", "{}", "{}", "[]", "succeeded",
             "n_x", 0, now - (200 - i), now - (200 - i)))
    m._exec("INSERT INTO job_logs (job_id, seq, at, chunk) VALUES (?,?,?,?)",
            (jid, 0, now, "x" * 32))
# ...and one on ANOTHER project, old enough to be swept, to prove the sweep is
# per project when it is asked for one.
m._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source,"
        " spec, outputs, state, node, exit_code, queued, ended) VALUES"
        " (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("j_other", "exec", "otherproj", "test", "{}", "{}", "{}", "[]", "succeeded",
         "n_x", 0, now - 99 * 86400, now - 99 * 86400))
m._exec("INSERT INTO job_logs (job_id, seq, at, chunk) VALUES (?,?,?,?)", ("j_other", 0, now, "y"))
before = len(m._rows("SELECT DISTINCT job_id FROM job_logs", ()))
m.prune_job_logs("retproj")
kept = len(m._rows("SELECT DISTINCT job_id FROM job_logs WHERE job_id LIKE 'j_ret%'", ()))
rows = len(m._rows("SELECT id FROM jobs WHERE project = 'retproj'", ()))
other = len(m._rows("SELECT 1 FROM job_logs WHERE job_id = 'j_other'", ()))
m.prune_job_logs()
other_after = len(m._rows("SELECT 1 FROM job_logs WHERE job_id = 'j_other'", ()))
print(f"{before} {kept} {rows} {other} {other_after} {m.JOB_LOG_KEEP}")`);
    const [before, kept, rows, other, otherAfter, keepN] = out.split(/\s+/).map(Number);
    ok(kept === keepN && before > keepN,
       `job logs past the count are dropped, the newest ${keepN} kept (${before} had logs, ${kept} left)`);
    ok(rows === keepN + 6,
       `...and every job ROW stays, so the list still says what ran (${rows} rows)`);
    ok(other === 1 && otherAfter === 0,
       'a sweep for one project leaves another alone, and the sweep for all of them takes the aged one');
  }

  // appdata is a store role like the other four (R17 step 2): where a node
  // keeps a dev instance's databases is a fact about that node, so it is
  // reported with its headroom and edited here, rather than being
  // BB_DEV_DATA_DIR on the controller and an optional mount to go with it.
  {
    const saved = await napi('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { ...rec.config.desired, stores: { ...rec.config.desired.stores,
                                                 appdata: '/scratch/appdata' } } });
    const back = (await napi('/api/v1/nodes')).nodes.find(n => n.id === minted.id);
    ok(!saved.error && back.config.desired.stores.appdata === '/scratch/appdata',
       `appdata is a store the config plane takes, like the other four (${
         saved.error || back.config.desired.stores.appdata})`);
    ok((await napi('/api/v1/nodes', { action: 'config', id: minted.id,
         config: { ...rec.config.desired, stores: { ...rec.config.desired.stores,
                                                    appdata: '/etc' } } })).error,
       '...and refused the same paths the others are, so it cannot be pointed at /etc');
  }
  // A hand-made request's resolver that is not text is told what a resolver
  // is, rather than raising on .strip() (B181).
  {
    const r = await napi('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { ...rec.config.desired, network: { mode: 'static', address: '10.0.0.40/24', dns: [1] } } });
    ok(/a resolver is an address/.test(r.error || ''), `a resolver that is not text is refused in words (${r.error})`);
  }
  // Static routes (the operator, 7 Oct), in either mode: a network with its
  // prefix via a router, given as {to, via} or "TO via VIA", kept once each;
  // what is not one is refused in words. The agent renders them per backend
  // (unit/test_agent_routes.py).
  {
    const r = await napi('/api/v1/nodes', { action: 'config', id: minted.id,
      config: { ...rec.config.desired, network: { mode: 'dhcp', routes: [{ to: '10.20.0.0/24', via: '192.168.1.1' },
        '172.16.5.0/24 via 192.168.1.2', { to: '10.20.0.0/24', via: '192.168.1.1' }] } } });
    const back = (await napi('/api/v1/nodes')).nodes.find(n => n.id === minted.id).config.desired.network.routes;
    ok(!r.error && JSON.stringify(back) === JSON.stringify([{ to: '10.20.0.0/24', via: '192.168.1.1' },
         { to: '172.16.5.0/24', via: '192.168.1.2' }]),
       `a node's static routes are kept with its network, in dhcp mode too, each once (${r.error || JSON.stringify(back)})`);
    const bad = [];
    for (const [route, re] of [[{ to: '10.20.0.0', via: '192.168.1.1' }, /written with its prefix/],
                               [{ to: '0.0.0.0/0', via: '192.168.1.1' }, /the default route is the gateway above/],
                               [{ to: '10.20.0.0/24', via: 'router' }, /via a router's address/]]){
      const x = await napi('/api/v1/nodes', { action: 'config', id: minted.id,
        config: { ...rec.config.desired, network: { mode: 'dhcp', routes: [route] } } });
      if (!re.test(x.error || '')) bad.push(`${JSON.stringify(route)}: ${x.error}`);
    }
    ok(!bad.length, `a network with no prefix, the default route and a router that is not an address are refused in words${bad.length ? ` (not: ${bad.join(' | ')})` : ''}`);
    await napi('/api/v1/nodes', { action: 'config', id: minted.id, config: rec.config.desired });
  }
  // json.loads takes Infinity, and int() of it raised, failing the node's
  // whole hello (B180): a non-finite number in a census is no number.
  {
    const body = JSON.stringify({ census: { ...CENSUS, session: { up: true, up_s: '__INF__' },
        stores: { ...CENSUS.stores, data: { ...CENSUS.stores.data, free_mb: '__INF__' } } },
      version: shipped.version, digest: shipped.digest }).replaceAll('"__INF__"', 'Infinity');
    const r = await fetch(base + '/api/v1/agent/hello', { method: 'POST', body,
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' } });
    const back = (await napi('/api/v1/nodes')).nodes.find(n => n.id === minted.id);
    ok(r.status === 200 && back.reported.session?.up_s === null,
       `a node reporting Infinity is heard, the number taken as absent (${r.status}, up_s ${back.reported.session?.up_s})`);
    await fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: CENSUS, version: shipped.version, digest: shipped.digest }) });
  }
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
  await page.evaluate(() => openToolchains());
  await page.waitForSelector('.tctab #tcNodeSel', { timeout: 15000 });
  ok(await page.$$eval('.tctab #tcNodeSel option', os => os.length > 0 && !os.some(o => o.value === 'local')),
     'the Tools tab picks among nodes and never offers this container (roadmap #26)');
  await page.selectOption('.tctab #tcNodeSel', minted.id);
  await page.waitForFunction(() => /on shed/.test(document.querySelector('.tctab .tchead:not(.tcnode)')?.textContent || ''),
                             null, { timeout: 15000 });
  const tools = await page.$$eval('.tctab .tc', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ')));
  ok(tools.some(t => /6655482e/.test(t)) && tools.some(t => /29\.0\.14206865/.test(t))
     && !tools.some(t => /3\.24\.0/.test(t)),
     'a node\'s versions come from its own bb toolchains versions, not the census summary');
  ok(tools.some(t => /6655482e/.test(t)) && /40 ?GB free|39 ?GB free|39\.\d ?GB free/.test(await page.$eval('.tctab .tchead:not(.tcnode)', e => e.textContent)),
     `picking the node lists what its census says it has, and its store's headroom (${
       await page.$eval('.tctab .tchead:not(.tcnode)', e => e.textContent.replace(/\s+/g, ' ').slice(0, 160))} | ${tools.filter(t => /installed|21\.0/.test(t)).join(' || ').slice(0, 300)})`);
  ok(!/installed at\s*(<|$)/m.test(await page.$eval('.tctab', e => e.textContent)),
     'an installed toolchain on a node reads "installed", not "installed at" with nothing after it');
  // Check for updates is a live control on a node (R67). It used to be
  // disabled whenever a node was picked, and a node is the only thing this
  // tab ever shows, so it could never be pressed: dead furniture with a
  // tooltip explaining why it would stay that way.
  ok(await page.$eval('.tctab [data-tc="check"]', b => !b.disabled && /upstream/.test(b.title || '')),
     'Check for updates can be pressed on a node, and says what it does');

  // ---- system packages a held recipe needs (roadmap R51) ------------------
  // The store is a share, so a recipe installed from one node is on every
  // node, while the libraries it needs are each machine's own. The census
  // says which are missing, the tab says so with one press that installs
  // them without reinstalling the recipe, and the row says so too.
  {
    const pj = (path, body) => page.evaluate(async ([p, b]) => (await (await fetch(p, b
      ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }
      : {})).json()), [path, body]);
    const sysCensus = sd => fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { ...CENSUS, sysdeps: sd },
                             version: shipped.version, digest: shipped.digest }) });
    await sysCensus({ family: 'dnf', unmet: { dotnet: ['libicu'] } });
    await page.evaluate(() => loadToolchains());
    await page.waitForSelector('.tctab .tcsys', { timeout: 15000 });
    const line = await page.$eval('.tctab .tcsys', e => e.textContent.replace(/\s+/g, ' '));
    ok(/lacks for what its store holds \(dnf\): dotnet: libicu/.test(line),
       `the Tools tab names the missing system packages per recipe, for the node's family (${line.slice(0, 120)})`);
    ok(await page.$('.tctab #tcSysdeps') !== null,
       '...with one press to install them on a node the agent administers');
    // What each tool pulls onto this machine is on its own row, named in the
    // node's package manager, before Install rather than in a job log after.
    const dotnetRow = (await page.$$eval('.tctab .tc', rs => rs.map(r => r.textContent.replace(/\s+/g, ' '))))
      .find(t => /\.NET/.test(t)) || '';
    ok(/Installs 1 system package with it here \(dnf\): libicu/.test(dotnetRow),
       `a row names the system packages its tool installs on this node (${(dotnetRow.match(/Installs[^.]*libicu/) || ['none'])[0]})`);
    // Nobody has to press it on a node BuilderBot manages: the census that
    // named them queued the job itself, for exactly those recipes.
    const tcJobs = async () => ((await pj(`/api/v1/jobs?node=${minted.id}&type=toolchain&n=20`)).jobs || []);
    const auto = (await tcJobs()).filter(j => j.spec?.action === 'sysdeps');
    ok(auto.length === 1 && JSON.stringify(auto[0].spec?.names) === '["dotnet"]' && auto[0].requested_by === 'system',
       `a managed node installs what it lacks by itself, for the recipes that need it (${auto.map(j => `${j.requested_by}: ${j.spec?.names}`).join(', ') || 'no job'})`);
    await pj('/api/v1/jobs', { action: 'cancel', id: auto[0]?.id });
    await sysCensus({ family: 'dnf', unmet: { dotnet: ['libicu'] } });
    ok((await tcJobs()).filter(j => j.spec?.action === 'sysdeps').length === 1,
       '...once: the same lack said again is not a job every hello, so a failing install is not retried forever');
    const sj = await pj('/api/toolchains', { action: 'sysdeps', names: [], node: minted.id });
    ok(sj.ok && /^j_/.test(sj.job), `pressing it still queues a toolchain job of the sysdeps kind (${sj.job || sj.error})`);
    const sjob = await pj(`/api/v1/jobs?id=${sj.job}`);
    ok(sjob.type === 'toolchain' && sjob.spec?.action === 'sysdeps',
       '...carrying the action and no recipe names: every held one');
    await pj('/api/v1/jobs', { action: 'cancel', id: sj.job });
    // Locked to its console: its root is its administrator's, so nothing is
    // installed by itself, whatever goes missing.
    await pj('/api/v1/nodes', { action: 'lock', id: minted.id });
    await sysCensus({ family: 'dnf', unmet: { dotnet: ['libicu'], playwright: ['libgbm'] } });
    ok((await tcJobs()).filter(j => j.spec?.action === 'sysdeps').length === 2,
       'a node whose system changes are locked to its console installs nothing by itself');
    await pj('/api/v1/nodes', { action: 'unlock', id: minted.id });
    await page.evaluate(() => openNodesTab());
    await page.waitForFunction(() => /System packages missing for dotnet \(libicu\)/
      .test(document.querySelector('.nodestab')?.textContent || ''), null, { timeout: 15000 });
    ok(true, 'the node\'s row says the same before a build fails on it');
    // Held: the row says which of them are missing here, and who installs them.
    {
      const held = (sd) => fetch(base + '/api/v1/agent/hello', { method: 'POST',
        headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ census: { ...CENSUS, sysdeps: sd, store_dirs: { top: ['flutter', 'node', 'dotnet'], android: [] } },
                               version: shipped.version, digest: shipped.digest }) });
      await held({ family: 'dnf', unmet: { dotnet: ['libicu'] } });
      await page.evaluate(() => openToolchains());
      await page.evaluate(() => loadToolchains());
      await page.waitForFunction(() => /missing here/.test(document.querySelector('.tctab')?.textContent || ''), null, { timeout: 15000 });
      const row = (await page.$$eval('.tctab .tc', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ')))).find(t => /\.NET/.test(t)) || '';
      ok(/1 of its 1 system package missing here \(dnf\), installed by itself: libicu/.test(row),
         `an installed tool's row says which of its system packages this node lacks (${(row.match(/\d of its[^:]*: \S+/) || ['none'])[0]})`);
      await held({ family: 'dnf', unmet: {} });
      await page.evaluate(() => loadToolchains());
      await page.waitForFunction(() => /all installed/.test(document.querySelector('.tctab')?.textContent || ''), null, { timeout: 15000 });
      ok(true, '...and that they are all there once they are');
      await fetch(base + '/api/v1/agent/hello', { method: 'POST',
        headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
        body: JSON.stringify({ census: CENSUS, version: shipped.version, digest: shipped.digest }) });
    }
    await sysCensus({ family: 'dnf', unmet: {} });
    await page.evaluate(() => openToolchains());
    await page.evaluate(() => loadToolchains());
    await page.waitForFunction(() => !document.querySelector('.tctab .tcsys'), null, { timeout: 15000 });
    ok(true, '...and both go quiet once the census says nothing is missing');
  }
  // ---- sessions a fresh install has not reached ---------------------------
  // A toolchain on PATH reaches a session when the session starts, so one open
  // since before the install still says "not found". The row counts them,
  // from when each session started (the agent reports it) and when a job
  // last put the toolchain on the store.
  {
    const now = Math.floor(Date.now() / 1000);
    execFileSync('python3', ['-c', `
import importlib.util, sys, json
spec = importlib.util.spec_from_file_location("nodes", "${REPO}/scripts/dashboard/nodes.py")
m = importlib.util.module_from_spec(spec); sys.modules["nodes"] = m; spec.loader.exec_module(m)
m.configure(state="${DIR}/state")
m._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source,"
        " spec, outputs, state, node, exit_code, queued, ended) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("j_landnode", "toolchain", "", "user:test", "{}", "{}",
         json.dumps({"action": "install", "names": ["node"]}), "[]", "succeeded",
         "${minted.id}", 0, ${now} - 200, ${now} - 100))
`], { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
    const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
    await fetch(base + '/api/v1/agent/work', { method: 'POST',
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ sample: { cpu_pct: 1, sessions: [
        { name: `${uid}~claude-alpha`, created: now - 3600, title: '✳ Claude Code' },
        { name: `${uid}~shell-2`, created: now - 10, title: 'bash' }] }, running: 0, wait: 0 }) });
    await page.evaluate(() => loadToolchains());
    await page.waitForSelector('.tctab .tcreopen', { timeout: 15000 });
    const rows = await page.$$eval('.tctab .tc', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ')));
    const nodeRow = rows.find(t => /Node\.js/.test(t)) || '';
    ok(/1 session open here started before this was installed: reopen it to use it/.test(nodeRow),
       `a row that changes PATH counts the sessions that started before it landed, and only those (${
         (nodeRow.match(/\d+ sessions? open[^:]*/) || ['none'])[0]})`);
    ok(!rows.some(t => /Flutter/.test(t) && /reopen/.test(t)),
       '...and says nothing on a row no job has put there since they started');
  }
  // ---- one store, two machines (roadmap #18) ------------------------------
  // The controller reaches the toolchain store through Unraid's FUSE layer and a
  // node reaches the same bytes over NFS, so neither mount string can be
  // derived from the other and the pair was invisible. A marker file inside
  // the store answers exactly, whatever the transport, and once the pair is
  // visible, two machines of different architectures sharing one store is a
  // thing that can be refused instead of failing later as binaries that will
  // not execute.
  {
    const ID = 's_' + '9'.repeat(16);
    const withId = (arch, token) => fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { ...CENSUS, arch, stores: { ...CENSUS.stores,
          toolchains: { ...CENSUS.stores.toolchains, id: ID } } },
        version: shipped.version, digest: shipped.digest }) });
    await withId('x86_64', en.token);
    // A second machine on the same store, of another architecture.
    const other = await napi('/api/v1/nodes', { action: 'enroll', name: 'armbox' });
    const oen = await napi('/api/v1/agent/enroll', {
      user: 'bb', version: shipped.version, digest: shipped.digest,
      census: { ...CENSUS, arch: 'aarch64', stores: { ...CENSUS.stores,
        toolchains: { ...CENSUS.stores.toolchains, id: ID } } } },
      { Authorization: 'Bearer ' + other.token, 'Content-Type': 'application/json' });
    ok(oen.ok, '(a second node enrolled on the same store)');
    // ...and the catalog says which platform each recipe is for, so an
    // install onto a node of another one is refused by name rather than
    // fetching a couple of hundred megabytes that cannot execute. arm64
    // Linux needs no new agent to reach this (roadmap #18).
    // swift: an x86-64 tarball, and the catalog says so. (jdk used to be
    // the example; Temurin packages arm64 and the recipe resolves it now.)
    const wrong = await napi('/api/toolchains', { action: 'install', names: ['swift'], node: other.id });
    ok(/packaged for linux\/amd64/.test(wrong.error || ''),
       `an install onto the wrong platform is refused by name (${
         (wrong.error || 'no error').slice(0, 100)})`);
    const fine = await napi('/api/toolchains', { action: 'install', names: ['flutter'], node: other.id });
    ok(!/packaged for/.test(fine.error || ''),
       `...while one that resolves its own platform is not refused FOR ITS PLATFORM: this node's refusal is the shared store, a different thing (${String(fine.error).slice(0, 60)})`);
    if (fine.job) await napi('/api/v1/jobs', { action: 'cancel', id: fine.job });
    // Two architectures on one store is the design now, not a clash: each
    // machine installs under its own <os>-<arch> scope (roadmap R19), so
    // the x86_64 node's install is queued while the arm64 node shares the
    // share. Canceled at once, so the one-at-a-time rule below starts clean.
    const clash = await napi('/api/toolchains', { action: 'install', names: ['jdk'], node: minted.id });
    ok(clash.job && !clash.error,
       `a store shared across architectures takes the install: each machine has its own scope in it (${
         clash.job || clash.error})`);
    await napi('/api/v1/jobs', { action: 'cancel', id: clash.job });
    // Same architecture: allowed, but still one at a time across the pair.
    await fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + oen.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { ...CENSUS, arch: 'x86_64', stores: { ...CENSUS.stores,
          toolchains: { ...CENSUS.stores.toolchains, id: ID } } },
        version: shipped.version, digest: shipped.digest }) });
    const first = await napi('/api/toolchains', { action: 'install', names: ['jdk'], node: minted.id });
    const second = await napi('/api/toolchains', { action: 'install', names: ['jdk'], node: other.id });
    ok(first.job && /installing jdk into the toolchain store it shares/.test(second.error || ''),
       `...and the same toolchain is not unpacked by both at once, naming why (${
         (second.error || 'no error').slice(0, 90)})`);
    // It is the directory that clashes, not the share: another toolchain on
    // the other node goes ahead, and so does a check, which writes nothing.
    // Two installs on two nodes used to be refused for sharing a store at all.
    const beside = await napi('/api/toolchains', { action: 'install', names: ['go'], node: other.id });
    ok(beside.job && !beside.error,
       `...while another toolchain installs on the other node at the same time (${beside.job || beside.error})`);
    const again = await napi('/api/toolchains', { action: 'install', names: ['node'], node: minted.id });
    ok(/already running on .*One at a time on a node/.test(again.error || ''),
       `...and one node still runs one toolchain job at a time (${(again.error || 'no error').slice(0, 80)})`);
    if (beside.job) await napi('/api/v1/jobs', { action: 'cancel', id: beside.job });
    const look = await napi('/api/toolchains', { action: 'check', node: other.id });
    ok(look.job && !look.error, `...and a check, which writes no store, is not held by it (${look.job || look.error})`);
    if (look.job) await napi('/api/v1/jobs', { action: 'cancel', id: look.job });
    if (first.job) await napi('/api/v1/jobs', { action: 'cancel', id: first.job });
    // The Android SDK is one tree, whatever part of it each job adds.
    const sdk1 = await napi('/api/toolchains', { action: 'install', names: ['android:ndk'], node: minted.id });
    const sdk2 = await napi('/api/toolchains', { action: 'install', names: ['android:cmake'], node: other.id });
    ok(sdk1.job && /installing [^;]*\bandroid\b[^;]* into the toolchain store/.test(sdk2.error || ''),
       `...and two parts of the Android SDK wait for each other, being one tree (${(sdk2.error || 'no error').slice(0, 80)})`);
    if (sdk1.job) await napi('/api/v1/jobs', { action: 'cancel', id: sdk1.job });
    if (sdk2.job) await napi('/api/v1/jobs', { action: 'cancel', id: sdk2.job });
    await napi('/api/v1/nodes', { action: 'retire', id: other.id });
    await withId('x86_64', en.token);
    // A toolchain that needs another pulls it in, ahead of itself. Before
    // this, android-tools with no jdk failed inside sdkmanager with a
    // message naming neither Java nor the toolchain that supplies it.
    const dep = await napi('/api/toolchains', { action: 'install',
                                              names: ['android-tools'], node: minted.id });
    const depjob = dep.job ? await napi(`/api/v1/jobs?id=${dep.job}`) : null;
    ok(depjob && JSON.stringify(depjob.spec.names) === JSON.stringify(['jdk', 'android-tools'])
       && JSON.stringify(dep.added) === JSON.stringify(['jdk']),
       `a toolchain that needs another installs it first, and says so (${
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
    const hollow = await napi('/api/toolchains', { action: 'install',
                                                 names: ['android:ndk'], node: minted.id });
    const hj = hollow.job ? await napi(`/api/v1/jobs?id=${hollow.job}`) : null;
    ok(hj && (hj.spec.names || []).includes('android-tools'),
       `an empty cmdline-tools directory does not count as android-tools (${
         JSON.stringify(hj?.spec?.names)})`);
    if (hollow.job) await napi('/api/v1/jobs', { action: 'cancel', id: hollow.job });
    await runnerCensus({});     // put the fixture's store listing back
  }

  // What a FINISHED job on a node reports. It used to report nothing: the
  // row vanished the moment the job ended, with done and failed hardcoded
  // empty, so the tab never cleared what the operator had ticked and the
  // next press re-sent toolchains that had already landed.
  {
    const j = await napi('/api/toolchains', { action: 'install', names: ['flutter', 'jdk'], node: minted.id });
    if (j.job) await napi('/api/v1/jobs', { action: 'cancel', id: j.job });
    let seen = null;
    for (let t = 0; t < 60 && !seen; t++){
      const p = await (await fetch(base + '/api/toolchains?node=' + minted.id, { headers: H })).json();
      if (p.job && p.job.running === false && p.job.action) seen = p.job;
      else await sleep(250);
    }
    ok(seen && seen.action === 'install' && seen.done.includes('flutter')
       && seen.failed.includes('jdk'),
       `a finished node job says what actually landed, read from the census (${
         JSON.stringify(seen && {done: seen.done, failed: seen.failed})})`);
  }
  // ---- the Emulator tab: a node's android system images -------------------
  // Not toolchains: one exists at every API level at once. The node walks its
  // own store for the ids and the AVDs built on them; which could be ADDED is
  // Google's index, read here, so a node needs no network of its own.
  {
    const hello = census => fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census, version: shipped.version, digest: shipped.digest }) });
    const emuApi = async () => (await fetch(base + '/api/emulator?node=' + minted.id, { headers: H })).json();
    // The Tools card ghosts the button until some node has sdkmanager and
    // the emulator, and says why on it.
    await page.evaluate(() => refresh());
    await page.waitForFunction(() => document.getElementById('bEmulator')?.disabled === true,
                               null, { timeout: 15000 });
    ok(/command-line tools and the emulator/.test(
         await page.$eval('#bEmulator', b => b.dataset.tip || '')),
       'the Emulator button is ghosted while no node has sdkmanager and the emulator, saying so');
    ok(await page.$eval('#toolsWhy', w => !w.hidden && /^Emulator: .*command-line tools and the emulator/.test(w.textContent)),
       '...and says so on the card too, in a line a phone can read (R119 step 6)');
    // No sdkmanager here yet: the tab says what is missing, and the server
    // refuses an add rather than letting it die inside the job.
    const bare = await emuApi();
    ok(bare.sdkmanager === false && bare.missing.length === 2,
       `a node without them is told which (${JSON.stringify(bare.missing)})`);
    const noSm = await napi('/api/emulator', { action: 'add', node: minted.id,
      image: 'system-images;android-31;google_apis;x86_64' });
    ok(/command-line tools/.test(noSm.error || ''),
       `...and adding an image there is refused, naming them (${noSm.error})`);

    const ANDROID = { ...CENSUS, toolchains: { ...CENSUS.toolchains, 'android-sdk': 'present', emulator: 'present' },
                      store_dirs: { top: ['flutter', 'node'], android: ['cmdline-tools', 'platform-tools', 'emulator'] } };
    await hello(ANDROID);
    await page.evaluate(() => refresh());
    await page.waitForFunction(() => document.getElementById('bEmulator')?.disabled === false,
                               null, { timeout: 15000 });
    ok(await page.$eval('#toolsWhy', w => w.hidden), '...and live once one has, the line gone');

    await page.evaluate(id => { emuNode = id; openEmulator(); }, minted.id);
    // The rows both wait on Google's index (the size is joined from it),
    // which is read off the request.
    await page.waitForFunction(() => document.querySelector('.emutab .tc.emnew input')
      && /GB/.test(document.querySelector('.emutab .tc.emimg')?.textContent || ''),
      null, { timeout: 15000 });
    const imgs = await page.$$eval('.emutab .tc.emimg',
      ls => ls.map(l => l.textContent.replace(/\s+/g, ' ').trim()));
    ok(imgs.length === 1 && /android-30/.test(imgs[0]) && /1\.\d GB/.test(imgs[0])
       && /AVD: fb30-node/.test(imgs[0]),
       `a node's images are listed, with the AVD built on each and the index's size (${imgs[0]})`);
    const apis = await page.$$eval('.emutab .tc.emnew input', o => o.map(x => x.value));
    ok(apis.length === 1 && apis[0] === 'system-images;android-31;google_apis;x86_64',
       `...and the rows to add are what the NODE does not have (${JSON.stringify(apis)})`);
    // Toolchains' gesture (R121 step 5): tick, then Install selected, which
    // with nothing ticked says so rather than sending nothing.
    ok(await page.$eval('.emutab .tc.emimg input', b => b.checked && b.disabled),
       '...ticked like Toolchains: an installed image is a set, dead tick');
    await page.click('.emutab [data-emu="install"]');
    await page.waitForFunction(() => /tick something first/.test(document.body.textContent), null, { timeout: 10000 });
    ok(true, '...and Install selected with nothing ticked says to tick something, in Toolchains\' words');
    ok(await page.evaluate(async id => !('images' in await (await fetch('/api/toolchains?node=' + id)).json()),
                           minted.id),
       'the Toolchains tab no longer carries images: they are the Emulator tab\'s');

    // An add is an `image` job, and it holds the store the way a toolchain
    // job does: the two write into one directory tree.
    const add = await napi('/api/emulator', { action: 'add', node: minted.id,
      images: ['system-images;android-31;google_apis;x86_64'] });
    const aj = add.job ? await napi(`/api/v1/jobs?id=${add.job}`) : null;
    ok(aj && aj.type === 'image' && aj.spec.action === 'add'
       && JSON.stringify(aj.spec.images) === '["system-images;android-31;google_apis;x86_64"]',
       `adding images queues one image job for exactly those ids (${JSON.stringify(aj?.spec)})`);
    const mixed = await napi('/api/emulator', { action: 'add', node: minted.id,
      images: ['system-images;android-31;google_apis;x86_64', 'system-images;android-99;google_apis;x86_64'] });
    ok(/not an image this server offered/.test(mixed.error || ''),
       `...and a list with one id the tab never offered is refused whole (${mixed.error})`);
    const clash = await napi('/api/toolchains', { action: 'install', names: ['zig'], node: minted.id });
    ok(/image job is already running/.test(clash.error || ''),
       `...and a toolchain install waits for it on the same store (${clash.error})`);
    if (add.job) await napi('/api/v1/jobs', { action: 'cancel', id: add.job });
    // What reaches a command line is a string this server handed out: an add
    // names one the picker offered, a removal one THIS node reported.
    const bogus = await fetch(base + '/api/emulator', { method: 'POST', headers: H,
      body: JSON.stringify({ action: 'add', node: minted.id, image: 'system-images;android-99;google_apis;x86_64' }) });
    ok(bogus.status === 400, 'an image id the picker never offered cannot be added');
    const badrm = await fetch(base + '/api/emulator', { method: 'POST', headers: H,
      body: JSON.stringify({ action: 'remove', node: minted.id, image: 'system-images;android-31;google_apis;x86_64' }) });
    ok(badrm.status === 400, 'an image the node never reported cannot be removed from it');
    const rm = await napi('/api/emulator', { action: 'remove', node: minted.id,
      image: 'system-images;android-30;google_apis;x86_64' });
    ok(rm.job, 'one it did report can be');
    if (rm.job) await napi('/api/v1/jobs', { action: 'cancel', id: rm.job });
    // The same in a terminal: bb toolchains says where images went.
    let said = '';
    try { execFileSync('bash', [`${REPO}/scripts/bb`, 'toolchains', 'images'], { stdio: 'pipe' }); }
    catch (e) { said = String(e.stderr); }
    ok(/system images are the emulator's, not a toolchain: bb emu images/.test(said),
       `bb toolchains images points at bb emu images (${said.trim()})`);

    // A node whose platform the Android recipes are not packaged for can
    // never hold an image, which is a different thing from not having the
    // tools yet: it is said, and the add is refused, rather than pointing at
    // a Toolchains tab that keeps both rows behind "Not for this node".
    {
      await hello({ ...ANDROID, system: 'darwin', arch: 'arm64', os: 'macOS 15.1' });
      const mac = await emuApi();
      ok(mac.wrong_platform === 'linux/*' && mac.missing.length === 0,
         `a Mac node says the tools are packaged for linux, rather than offering an install (${
           mac.wrong_platform} / ${JSON.stringify(mac.missing)})`);
      const no = await napi('/api/emulator', { action: 'add', node: minted.id,
        image: 'system-images;android-31;google_apis;x86_64' });
      ok(/no system image can run there/.test(no.error || ''),
         `...and an add there is refused with the platform (${no.error})`);
      await page.evaluate(() => { emu = null; loadEmulator(); });
      await page.waitForFunction(() => /no system image can run there/.test(
        document.querySelector('.emutab .emneed')?.textContent || ''), null, { timeout: 15000 });
      ok(await page.$('.emutab [data-emu="install"]') === null,
         '...and the tab offers no picker at all there, rather than a dead one');
      await hello(ANDROID);
    }

    // An agent too old to report the field at all is not a node with no
    // images: the tab would otherwise say "no image" for a node never asked.
    const noField = { ...ANDROID }; delete noField.images;
    await hello(noField);
    const old = await emuApi();
    ok(old.known === false && old.images.length === 0,
       `an agent that does not report images says so, rather than reporting none (${old.known})`);
    await runnerCensus({});     // put the fixture's census back
    await page.evaluate(() => { const t = tabs.find(t => t.kind === 'emulator'); if (t) dropTab(t.id); });
  }

  const gate = await napi('/api/toolchains', { action: 'install', names: ['android:platform-tools'], node: 'local' });
  ok(gate.ok !== undefined || gate.error, '(local installs still go through the installer here)');

  // ---- the project's nodes, in its settings dialog (phase 6) --------------
  await page.evaluate(() => openProjectsTab());
  // As on the first opening after a page load: the node list has not been
  // fetched yet. The picker used to stay hidden until the dialog was closed
  // and opened again; it has to appear on this opening, when the list lands.
  await page.evaluate(() => { nodesList = null; });
  await page.evaluate(n => renameProject(n), 'alpha');   // the settings form (the row's gear went in R119 step 3)
  await page.waitForSelector('#rnmodal:not([hidden])', { timeout: 10000 });
  await page.waitForSelector('#rnNodeField:not([hidden])', { timeout: 10000 });
  ok(true, 'the node picker appears on the first opening after a load, when the list arrives, not on the next one');
  await page.waitForFunction(id => [...document.querySelectorAll('#rnNode option')].some(o => o.value === id),
                             minted.id, { timeout: 10000 });
  ok(await page.$eval('#rnNode', s => ![...s.options].some(o => o.value === 'local') && [...s.options].some(o => /sandbox/.test(o.textContent))),
     'the project\'s node is any node but this container: the ssh sandbox included');
  await page.selectOption('#rnNode', minted.id);
  await page.fill('#rnBuildCmd', './gradlew assembleDebug');
  await page.fill('#rnOutputs', 'app/build/outputs/apk/**/*.apk, extra/*.xpi');
  await page.fill('#rnCaptureDays', '3');
  await page.fill('#rnDevKeep', '5');
  await saveDialog(page);
  const saved = JSON.parse(readFileSync(`${DIR}/state/claude-prefs.json`, 'utf8')).projects.alpha;
  ok(saved.node === minted.id && saved.build === './gradlew assembleDebug'
     && saved.outputs.length === 2 && saved.outputs[1] === 'extra/*.xpi' && saved.capture_days === 3
     && saved.dev_keep === 5,
     'Save writes the project\'s node, the command, the outputs, the days captures are kept and the dev builds kept of each onto the project record');
  // Whether that node is quiet enough to time on (R108): the agent's
  // heartbeat says its load and what runs there by kind, and the answer
  // joins it with the jobs and sessions there, naming no other project.
  await fetch(base + '/api/v1/agent/work', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ sample: { cpu_pct: 30, load1: 2.6, cores: 4, mem_mb: 8192, mem_used_mb: 2048,
      kinds: { emulator: 1, gradle: 2, made_up: 5 } }, running: 0, wait: 0 }) });
  const busyNow = await page.evaluate(async () => (await fetch('/api/node-busy?project=alpha')).json());
  ok(busyNow.verdict === 'busy' && busyNow.cores === 4 && busyNow.kinds.emulator === 1 && !('made_up' in busyNow.kinds)
     && busyNow.why.some(w => /1 emulator, 2 gradle/.test(w)) && busyNow.why.some(w => /load 2\.6 on 4 cores/.test(w)),
     `the project's node says it is busy and why: its load, and an emulator and Gradle running there (${JSON.stringify(busyNow.why)})`);

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

  // ---- locked to the console: the dashboard applies nothing ------------------
  // The lock is the operator saying this machine's fstab, address and root
  // are managed at the OS level: Apply is refused with the reason, the
  // buttons say so, and Unlock puts it back. The rule is the server's.
  {
    const lk = await napi('/api/v1/nodes', { action: 'lock', id: minted.id });
    ok(lk.ok && lk.lock === true, 'Lock system changes marks the node locked');
    const ref = await napi('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
    ok(/locked to its own console/.test(ref.error || ''),
       `...and Apply storage is refused with the reason (${(ref.error || 'no error').slice(0, 70)})`);
    ok(/locked to its own console/.test((await napi('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'network' })).error || ''),
       '...and Apply network with it');
    await page.evaluate(() => loadNodes());
    await page.waitForFunction(sel => /locked to its own console/.test(
      document.querySelector(sel + ' [data-napply="storage"]')?.title || ''), ROW, { timeout: 10000 });
    ok(await page.$eval(ROW + ' [data-napply="storage"]', b => b.disabled)
       && await page.$eval(ROW + ' [data-napply="network"]', b => b.disabled)
       && await page.$eval(ROW + ' [data-nd="unlock"]', b => /Unlock/.test(b.textContent)),
       '...the tab ghosts both Apply buttons, says why, and offers Unlock under Advanced');
    const ul = await napi('/api/v1/nodes', { action: 'unlock', id: minted.id });
    ok(ul.ok && ul.lock === false, 'Unlock puts it back');
    await page.evaluate(() => loadNodes());
    await page.waitForFunction(sel => !!document.querySelector(sel + ' [data-nd="lock"]'), ROW, { timeout: 10000 });
  }

  // ---- an apply that failed says so, where the button is -------------------
  // A failed apply leaves the drift exactly as it was, so the section went
  // back to "1 change to apply" and mentioned the attempt nowhere, which
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
  // The bell carries it too, pinned above the log: from the poll, so it is
  // there without a press and leaves the moment the agent is current.
  await page.waitForFunction(id => (state?.attention || []).some(a => a.id === id && !a.window),
                             minted.id, { timeout: 30000 });
  await page.click('#bBell');
  await page.waitForSelector('#bellPanel .bnote.ask', { timeout: 10000 });
  const bellText = await page.$eval('#bellPanel', e => e.textContent.replace(/\s+/g, ' '));
  ok(/agent update available/i.test(bellText) && /runs agent 3 and this controller ships/.test(bellText)
     && await page.$('#bellPanel [data-bnode]') !== null,
     `the bell pins "agent update available" for the node, with a way to the Nodes tab (${bellText.slice(0, 160)})`);
  ok(await page.$eval('#bBell .dot', d => d.classList.contains('warn')),
     '...in amber: an update waiting is not work stopped');
  // Its link goes to THIS node, whichever the tab was on, with Update agent
  // brought into view (the operator, 4 Oct).
  const other = await page.evaluate(id => nodesList.find(n => n.id !== id && n.kind === 'agent' && n.state !== 'retired')?.id, minted.id);
  if (other) await page.evaluate(o => { nodesPick = o; nodesRev++; drawPanes(); }, other);
  await page.click(`#bellPanel [data-bnode="${minted.id}"]`);
  await page.waitForFunction(id => nodesPick === id && document.getElementById('bellPanel').hidden
    && document.querySelector('.nodestab [data-nd="update-agent"]'), minted.id, { timeout: 10000 });
  await sleep(700);
  ok(await page.$eval('.nodestab [data-nd="update-agent"]', b => {
       const r = b.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; }),
     `...and its link opens the Nodes tab on that node${other ? ' (from another)' : ''}, Update agent in view`);
  // The runner is on its own tab now (R121), held by the same rule there.
  const runnerOff = await page.evaluate(async id => { openRunnerTab(id); await new Promise(r => setTimeout(r, 400));
    const b = document.querySelector(`.runnertab .ndrow[data-node="${id}"] [data-nrunner="install"]`);
    const was = b?.disabled; openNodesTab(); await new Promise(r => setTimeout(r, 400)); return was; }, minted.id);
  const off = await page.evaluate(sel => ({
    storage: document.querySelector(sel + ' [data-napply="storage"]')?.disabled,
    network: document.querySelector(sel + ' [data-napply="network"]')?.disabled,
    cache: document.querySelector(sel + ' [data-nd="cache-clear"]')?.disabled,
    update: document.querySelector(sel + ' [data-nd="update-agent"]')?.disabled,
    said: document.querySelector(sel + ' .ndconfstate')?.textContent || '',
  }), ROW);
  off.runner = runnerOff;
  ok(off.storage && off.network && off.runner && off.cache && !off.update
     && /runs agent 3 and this controller ships/.test(off.said),
     `everything the agent runs is off while it is behind, and the state line says why (${
       JSON.stringify(off).slice(0, 120)})`);
  // The button is a courtesy; the rule is the server's.
  const refused = await napi('/api/v1/nodes', { action: 'apply', id: minted.id, what: 'storage' });
  const refusedTc = await napi('/api/toolchains', { action: 'install', names: ['jdk'], node: minted.id });
  ok(/runs agent 3/.test(refused.error || '') && /runs agent 3/.test(refusedTc.error || ''),
     `...and the server refuses the same jobs, not only the buttons (${(refused.error || 'no error').slice(0, 60)})`);
  // The same number and a different file: the agent moved without its
  // version constant, and the row said "runs 0.6.92 and ships 0.6.92" on a
  // walk (docs/journeys.md, 23 Sep). It names the files now.
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: CENSUS, version: shipped.version, digest: 'sha256:' + '0'.repeat(64) }) });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /has an older build of agent \S+ \(/.test(document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  const sameTc = await napi('/api/toolchains', { action: 'install', names: ['jdk'], node: minted.id });
  ok(/runs agent \S+ \(00000000\) and this controller ships the same number as a newer file \([0-9a-f]{8}\)/.test(sameTc.error || ''),
     `an agent on the same number but another file is told so, on the row and in the refusal (${(sameTc.error || 'no error').slice(0, 90)})`);
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: CENSUS, version: '3', digest: 'sha256:' + '0'.repeat(64) }) });
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /runs agent 3 /.test(document.querySelector(sel + ' .ndconfstate')?.textContent || ''), ROW, { timeout: 10000 });
  await page.evaluate(() => openToolchains());
  await page.waitForSelector('.tctab #tcNodeSel', { timeout: 15000 });
  await page.selectOption('.tctab #tcNodeSel', minted.id);
  await page.waitForSelector('.tctab .tcstale', { timeout: 15000 });
  ok(await page.$eval('.tctab [data-tc="install"]', b => b.disabled),
     'the Tools tab says so too, and installs nothing onto a node that is behind');
  // Its own update is the way out and is never held.
  const upd = await napi('/api/v1/nodes', { action: 'update-agent', id: minted.id });
  const uj = upd.job ? await napi(`/api/v1/jobs?id=${upd.job}`) : null;
  ok(upd.ok && uj && uj.type === 'self-update' && uj.spec.digest === shipped.digest && uj.node === minted.id,
     `Update agent queues a self-update naming the shipped digest (${upd.job || upd.error})`);
  // ...and it stays grayed while that job is queued, through the repaint
  // that replaces the button. pressing() only covers the round trip; the
  // render is what has to know, and node_list only tracked system jobs, so
  // Update agent came back live the instant it answered.
  // Back to the Nodes tab: the block above left the Tools tab in front.
  await page.evaluate(() => openNodesTab());
  await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
  await pickNode(page, minted.id);
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /Updating/.test(
    document.querySelector(sel + ' [data-nd="update-agent"]')?.textContent || ''),
    ROW, { timeout: 10000 });
  ok(await page.$eval(`${ROW} [data-nd="update-agent"]`, b => b.disabled),
     '...and stays grayed while the update is queued, not only for the round trip');
  // With a job still running there the update waits for it (B516): the node
  // takes no new work meanwhile, and the line says so rather than "Updating"
  // for minutes. The listing is answered with one running job added, since a
  // node behind takes nothing but its update and so cannot be made busy here.
  const busyList = async route => {
    const r = await route.fetch(); const j = await r.json();
    for (const n of j.nodes || []) if (n.id === minted.id)
      n.jobs = [...(n.jobs || []), { id: 'j_busy', type: 'exec', state: 'running' }];
    await route.fulfill({ response: r, json: j });
  };
  await page.route('**/api/v1/nodes', busyList);
  await page.evaluate(id => { delete nodesConf[id]; loadNodes(); }, minted.id);
  await page.waitForFunction(sel => /waits for 1 running job to finish/.test(
    document.querySelector(sel + ' .ndagent .lead')?.textContent || ''), ROW, { timeout: 10000 })
    .then(() => ok(true, '...and while a job still runs there, the row says the update waits for it'),
          () => ok(false, '...and while a job still runs there, the row says the update waits for it'));
  await page.unroute('**/api/v1/nodes', busyList);
  if (upd.job) await napi('/api/v1/jobs', { action: 'cancel', id: upd.job });
  // ---- an agent from ANOTHER window stops work, and says which projects ----
  // Inside a window being behind is routine; across one nothing sent is
  // promised to work, so the alert is red, names the projects on the node,
  // and the Artifacts tab says so before a build is refused.
  await napi('/api/prefs', { project: 'alpha', node: minted.id });
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: CENSUS, version: '0.3.9', digest: 'sha256:' + '1'.repeat(64) }) });
  await page.waitForFunction(id => (state?.attention || []).some(a => a.id === id && a.window
                                     && a.projects.includes('alpha')),
                             minted.id, { timeout: 30000 });
  await page.click('#bBell');
  await page.waitForSelector('#bellPanel .bnote.ask.bad', { timeout: 10000 });
  ok(await page.$eval('#bellPanel .bnote.ask.bad', e => /agent out of window/i.test(e.textContent)
                                                        && /alpha cannot build, test or use the emulator/.test(e.textContent)),
     'an agent from another window is a red pinned alert naming the projects it stops');
  ok(await page.$eval('#bBell .dot', d => d.classList.contains('bad')), '...and the dot is red');
  await page.keyboard.press('Escape');
  await page.waitForFunction(() => document.getElementById('bellPanel').hidden);
  // Waited for rather than read once: the rows and the alerts are two reads
  // of the record in one poll, and a hello landing between them skews one
  // poll's answer; the next agrees.
  await page.waitForFunction(() => /different compatibility window/.test(
    (state.projects || []).find(p => p.name === 'alpha')?.node_gap || ''), null, { timeout: 30000 });
  ok(true, 'the project row carries why nothing routed to its node runs');
  const refusedRun = await napi('/api/v1/jobs', { action: 'run', project: 'alpha', argv: ['sh', '-c', 'true'] });
  ok(/different compatibility window/.test(refusedRun.error || ''),
     `...and a bb verb sent to it is refused with the same sentence (${(refusedRun.error || 'no error').slice(0, 60)})`);
  await napi('/api/prefs', { project: 'alpha', node: '' });
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: CENSUS, version: shipped.version, digest: shipped.digest }) });
  // Current again: the alert is not dismissed, it stops being true.
  await page.waitForFunction(id => !(state?.attention || []).some(a => a.id === id),
                             minted.id, { timeout: 30000 });
  ok(true, 'an agent brought current takes its alert out of the bell by itself');

  // ---- a node that just came up is waited for, not unbound -------------------
  // The agent starts before the network mounts land, so its first census
  // after a boot says /workspace is missing. With the uptime beside it the
  // gate says "came up N seconds ago, not mounted yet" and no more; the
  // same census from a machine up for hours is a missing mount, with the
  // fix and the way out.
  const sessionCensus = se => fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: { ...CENSUS, session: se }, version: shipped.version, digest: shipped.digest }) });
  const SE = { up: true, port: 7681, ro_port: 7682, user: 'bb', workspace: false, writable: false, boot: '12.5', up_s: 40 };
  await napi('/api/prefs', { project: 'alpha', node: minted.id });
  await sessionCensus(SE);
  let why = (await napi('/api/status')).projects.find(p => p.name === 'alpha')?.session_why || '';
  ok(/came up 40 seconds ago/.test(why) && /not mounted the projects share/.test(why) && !/Unbind/.test(why),
     `a node up for a minute with no /workspace is "not mounted yet", and nobody is told to unbind it (${why.slice(0, 70)})`);
  // A mount the server refused is neither: the agent tried it and kept
  // what the server said, and the fix is the export rule on the host,
  // which is what actually happened when the sandbox moved to an address
  // the rule did not name.
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: { ...CENSUS, session: SE, mounts: [...CENSUS.mounts,
      { path: '/workspace', source: 'nas:/mnt/user/development/projects', type: 'nfs', ro: false, mounted: false, real: '',
        error: 'access denied by server while mounting nas:/mnt/user/development/projects' }] },
      version: shipped.version, digest: shipped.digest }) });
  why = (await napi('/api/status')).projects.find(p => p.name === 'alpha')?.session_why || '';
  ok(/access denied by server/.test(why) && /NFS export names another address/.test(why) && !/came up/.test(why),
     `a mount the server refused says what the server said and points at the export rule, boot or no boot (${why.slice(0, 60)})`);
  await sessionCensus({ ...SE, up_s: 5000 });
  why = (await napi('/api/status')).projects.find(p => p.name === 'alpha')?.session_why || '';
  ok(/does not mount the projects share/.test(why) && /add the mount/.test(why)
     && /nowhere else/.test(why),
     `...the same census from a machine up for hours is a missing mount, with the fix and the fact that there is nowhere else (${why.slice(0, 60)})`);
  await sessionCensus({ ...SE, up_s: 5000, workspace: true, writable: true });
  const row = (await napi('/api/status')).projects.find(p => p.name === 'alpha');
  ok(row?.session_at === 'shed' && row?.session_why === '',
     'and once the share is mounted the button is live there');
  // A mount that is there and answers Stale file handle (roadmap R41): every
  // list of mounts calls it fine and every read fails, and remounting on the
  // node does not help when the export was re-created under it on the host.
  // The census says so, the row says so in red with the host-side fix, and
  // nothing treats the path as present.
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: { ...CENSUS, session: SE, mounts: [...CENSUS.mounts,
      { path: '/devdata', source: 'nas:/mnt/user/bb-sandbox/devdata', type: 'nfs', ro: false, mounted: true,
        real: 'nas:/mnt/user/bb-sandbox/devdata', stale: true,
        error: 'mounted, but the handle is stale: the export was re-created under it on the host; re-export it there, then Apply storage here' }] },
      version: shipped.version, digest: shipped.digest }) });
  await page.evaluate(() => { nodesList = null; openNodesTab(); });
  await page.waitForFunction(id => (nodesList || []).find(n => n.id === id)?.reported?.mounts?.some(m => m.path === '/devdata' && m.stale),
                             minted.id, { timeout: 15000 });
  ok(true, 'the census carries that a mounted share answers stale');
  await pickNode(page, minted.id);
  await page.waitForFunction(id => /handle is stale/.test(document.querySelector(`.nodestab .ndrow[data-node="${id}"]`)?.textContent || ''),
                             minted.id, { timeout: 15000 });
  ok(await page.$eval(`.nodestab .ndrow[data-node="${minted.id}"]`, r =>
       /\/devdata: mounted, but the handle is stale/.test(r.textContent) && /re-export it there/.test(r.textContent)),
     'the row says which mount is stale and that the fix is on the host, whether or not the desired list names it');
  // Whether a session there is kept to its own project (R35): on the
  // Sessions section's status when it is not, since a folded section shows
  // nothing else, and why; and said plainly when it is.
  const isoCensus = iso => fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: { ...CENSUS, session: { ...SE, up_s: 5000, workspace: true, writable: true }, isolation: iso },
                           version: shipped.version, digest: shipped.digest }) });
  const rowText = () => page.$eval(`.nodestab .ndrow[data-node="${minted.id}"]`, r => r.textContent.replace(/\s+/g, ' '));
  await isoCensus({ sessions: false, why: 'bb-session is not installed on this machine', extra: 'x'.repeat(500) });
  await page.evaluate(() => { nodesList = null; openNodesTab(); });
  await page.waitForFunction(id => /not isolated/.test(document.querySelector(`.nodestab .ndrow[data-node="${id}"]`)?.textContent || ''),
                             minted.id, { timeout: 15000 }).catch(() => {});
  const shared = await rowText();
  ok(/ready, not isolated/.test(shared) && /Sessions here can read each other's projects: bb-session is not installed on this machine/.test(shared),
     `a node whose sessions are not kept to their project says so on the Sessions status, with the reason (${(shared.match(/Sessions here can read[^.]*/) || [''])[0]})`);
  await isoCensus({ sessions: true, why: '' });
  await page.evaluate(() => { nodesList = null; openNodesTab(); });
  await page.waitForFunction(id => /sees only its own project/.test(document.querySelector(`.nodestab .ndrow[data-node="${id}"]`)?.textContent || ''),
                             minted.id, { timeout: 15000 }).catch(() => {});
  const isolated = await rowText();
  ok(/Each session sees only its own project/.test(isolated) && !/not isolated/.test(isolated),
     '...and one whose sessions are says that instead');
  await napi('/api/prefs', { project: 'alpha', node: '' });
  await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census: CENSUS, version: shipped.version, digest: shipped.digest }) });
}

// ---- a node's path mapping (§11: the record owns it) ------------------------
// What DOCKER_HOST_PATHS was: on the sandbox node's row now, validated to
// pairs, and read by the manager through the node being addressed. It used
// to draw on the ssh row only; with that kind retired (roadmap #24) it draws
// on the agent row, which is the only remote row left; devapp.host_map
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
  await openSection(page, 'nodes:advanced', `.nodestab .ndrow[data-node="${sb.id}"]`);
  await page.waitForSelector(`.nodestab .ndrow[data-node="${sb.id}"] .ndpaths [data-k="paths"]`, { timeout: 15000 });
  ok(await page.$eval(`.nodestab .ndrow[data-node="${sb.id}"] .ndpaths [data-k="paths"]`, e => e.value) === '/workspace:/workspace, /devdata:/mnt/user/bb-dev',
     '...and the node\'s row shows it, editable');
  ok(await page.$('.nodestab .ndrow[data-node="local"] .ndpaths') === null,
     '...while the controller, whose paths are its own, is not a row here at all');

  // ---- renaming a node (the operator's ask, 15 Sep) ------------------------
  // The name is what a node is called everywhere: the pickers, the project
  // rows, the label a runner installed from now on registers with. One word,
  // and not one another node already wears.
  {
    const was = (await papi({ action: 'update', id: sb.id, fields: { name: 'two words' } }));
    ok(/letters, digits/.test(was.error || ''), `a name with a space is refused with the rule (${was.error})`);
    const dup = await papi({ action: 'update', id: sb.id, fields: { name: 'shed' } });
    ok(/already called shed/.test(dup.error || ''), 'a name another live node wears is refused');
    const loc = await papi({ action: 'update', id: 'local', fields: { name: 'box' } });
    ok(/not a node to rename/.test(loc.error || ''), 'the controller\'s own row is not renamed');
    await openSection(page, 'nodes:advanced', `.nodestab .ndrow[data-node="${sb.id}"]`);
    await page.fill(`.nodestab .ndrow[data-node="${sb.id}"] .ndname [data-k="name"]`, 'sandbox-two');
    // A heartbeat repaints the tab; the name being typed survives it (B176).
    await page.evaluate(() => loadNodes());
    await page.waitForTimeout(300);
    ok(await page.$eval(`.nodestab .ndrow[data-node="${sb.id}"] .ndname [data-k="name"]`, e => e.value) === 'sandbox-two',
       'a new name being typed survives the repaint a heartbeat brings');
    await page.click(`.nodestab .ndrow[data-node="${sb.id}"] [data-nd="rename"]`);
    await page.waitForFunction(id => nodesList?.find(n => n.id === id)?.name === 'sandbox-two', sb.id, { timeout: 15000 });
    ok(true, 'Rename on the row renames the node');
    await papi({ action: 'update', id: sb.id, fields: { name: 'sandbox' } });
    await page.waitForFunction(id => nodesList?.find(n => n.id === id)?.name === 'sandbox', sb.id, { timeout: 15000 });
  }

  // ---- Check: the pair nothing else verifies (roadmap #13) ------------------
  // A marker made under the share here, looked for through the node's
  // daemon by the same guarded one-shot container that makes the dev-data
  // directory. The stub answers yes; run.testfail makes it say no the way
  // `test -d` does. The marker never outlives the check.
  const { readFileSync: rf, writeFileSync: wf, unlinkSync: ul, readdirSync: rd } = await import('node:fs');
  const chk = `.nodestab .ndrow[data-node="${sb.id}"] .ndcheck`;
  await page.click(`.nodestab .ndrow[data-node="${sb.id}"] [data-nd="check-paths"]`);
  await page.waitForFunction(s => /same directory/.test(document.querySelector(s)?.textContent || ''),
                             chk, { timeout: 20000 });
  ok(/^the same directory/.test(await page.$eval(chk, e => e.textContent))
     && !(await page.$eval(chk, e => e.classList.contains('warn'))),
     'Check makes a marker under the projects share here and finds it through the daemon: the same directory');
  const dlog = rf(`${DIR}/dockerstate/docker.log`, 'utf8');
  ok(/run --rm -u \d+:\d+ -v \/[^ ]+:\/d alpine test -d \/d\/\S*bb-path-check-[0-9a-f]+/.test(dlog),
     '...as a one-shot test -d through the guarded probe, mounting the share root');
  ok(!rd(`${DIR}/ws`).some(f => f.startsWith('bb-path-check-')),
     '...and the marker is gone afterwards');
  wf(`${DIR}/dockerstate/run.testfail`, '');
  await page.click(`.nodestab .ndrow[data-node="${sb.id}"] [data-nd="check-paths"]`);
  await page.waitForFunction(s => /NOT the same/.test(document.querySelector(s)?.textContent || ''),
                             chk, { timeout: 20000 });
  ok(await page.$eval(chk, e => e.classList.contains('warn'))
     && /would bind an empty tree/.test(await page.$eval(chk, e => e.textContent)),
     'a marker the daemon cannot see is said plainly, with what it would cost');
  ul(`${DIR}/dockerstate/run.testfail`);
  ok(!rd(`${DIR}/ws`).some(f => f.startsWith('bb-path-check-')),
     '...and the marker is gone after a no as well');
}

// ...and put the sandbox's path mapping back: it lives on the node record
// now, which fresh() does not touch, so the mapping this file sets was still
// there for devapp.mjs and changed what its rows complained about.
await page.evaluate(() => nodeAct({ action: 'paths', id: nodesList.find(n => n.name === 'sandbox')?.id, paths: '' }));

// Retire what this file made, the way agent.mjs does: the store outlives a
// suite, and a node left online here becomes the DEFAULT node for the files
// after it, which sent devapp's compose at a machine that does not exist.
for (const n of (await (await fetch(URL.replace(/\/$/, '') + '/api/v1/nodes',
     { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json()).nodes){
  if (n.kind !== 'local' && n.name !== 'sandbox')
    await page.evaluate(id => nodeAct({ action: 'retire', id }), n.id);
}

// ---- a machine to enroll, before there is one -------------------------------
// The Nodes tab renders the domain XML for a sandbox VM rather than asking
// somebody to copy nodes/unraid-vm.xml and remember which three fields belong
// to one machine. What matters is that two renders are two machines: a shared
// uuid points a second VM at the first one's OVMF nvram file, and a shared MAC
// puts them both on the first one's address.
await page.evaluate(() => openNodesTab());
await page.waitForSelector('.nodestab #ndVm', { timeout: 20000 });
// The enroll dialog asks for the account jobs run as, and the command it
// prints carries it: the record follows whatever the agent reports at
// enrollment, and this is what stops the row saying bb in the meantime and
// somebody having to remember the flag.
await page.click('.nodestab #ndEnroll');
await page.waitForSelector('#ndBody #ndEnUser', { timeout: 10000 });
ok(await page.$eval('#ndBody #ndEnUser', i => i.value) === 'bb',
   'Enroll node opens on bb as the account jobs run as');
await page.fill('#ndBody #ndEnName', 'joesbox');
await page.fill('#ndBody #ndEnUser', 'joe');
// Read back before the press: a run under load once minted joesbox for bb
// (B331), and whether the field still held joe at the press is the fact
// that says where to look.
{
  // Said with what was read (B331, 1 Oct): a sighting under load had the
  // account right at Mint and the name apparently not, and this check
  // printed neither.
  const held = await page.$eval('#ndBody', b => ({ name: b.querySelector('#ndEnName')?.value,
    user: b.querySelector('#ndEnUser')?.value, form: [...b.querySelectorAll('input')].map(i => i.id).join(',') }));
  ok(held.user === 'joe' && held.name === 'joesbox',
     `the enroll dialog holds the name and the account typed into it (${JSON.stringify(held)})`);
}
await page.click('#ndBody #ndEnGo');
await page.waitForSelector('#ndBody .ndtoken', { timeout: 15000 });
ok(await page.$eval('#ndBody .ndtoken', el => /--user joe/.test(el.textContent)),
   '...and the provision command it prints carries a account that is not the default');
// Where the provisioner comes from (B133): the dialog's first line fetches
// it from this controller with the same token, and that route serves it.
ok(await page.$eval('#ndBody .ndtoken', el => /curl -fsSL -H 'Authorization: Bearer bbe_[^']+' '[^']*\/api\/v1\/agent\/download\?what=provisioner' -o provision-linux\.sh/.test(el.textContent)),
   '...after a curl that fetches the provisioner from this controller with the token');
{
  const tok = (await page.$eval('#ndBody .ndtoken', el => el.textContent)).match(/Bearer (bbe_[A-Za-z0-9_-]+)/)?.[1];
  const r = await fetch(URL.replace(/\/$/, '') + '/api/v1/agent/download?what=provisioner', { headers: { Authorization: 'Bearer ' + tok } });
  const body = await r.text();
  ok(r.status === 200 && /^#!\/usr\/bin\/env bash/.test(body) && /BBSANDBOX/.test(body) && /x-shellscript/.test(r.headers.get('content-type') || ''),
     `...and the route hands the enroll token the provisioner itself (${r.status}, ${body.length} bytes)`);
  const no = await fetch(URL.replace(/\/$/, '') + '/api/v1/agent/download?what=provisioner');
  ok(no.status === 401, '...and nobody else');
  // A Mac is told to run provision-macos.sh, so it gets a line that fetches
  // that one, and the route serves it (B150).
  const mac = await fetch(URL.replace(/\/$/, '') + '/api/v1/agent/download?what=provisioner-macos', { headers: { Authorization: 'Bearer ' + tok } });
  const macBody = await mac.text();
  ok(await page.$eval('#ndBody .ndtoken', el => /download\?what=provisioner-macos' -o provision-macos\.sh\s+bash provision-macos\.sh/.test(el.textContent))
     && mac.status === 200 && /launchd|LaunchAgents/.test(macBody) && !/BBSANDBOX/.test(macBody),
     `...and a Mac's line fetches the macOS provisioner, which the same route serves (${mac.status}, ${macBody.length} bytes)`);
}
ok(await page.evaluate(async () => { await loadNodes();
     return (nodesList.find(n => n.name === 'joesbox')?.config || {}).user; }) === 'joe',
   '...with the pending row already saying which account, before the machine exists');
await page.click('#ndBody #ndTokDone');
await page.evaluate(async () => {
  const n = nodesList.find(x => x.name === 'joesbox');
  if (n) await nodeAct({ action: 'retire', id: n.id });
});

// What is offered (roadmap R54, step 6): with unvetted features off the
// generator knows one hypervisor, the one every sandbox here was made on,
// and refuses the rest with the sentence that names the switch. The rest
// of this section runs with the switch on, as a dev instance does.
{
  const probe = await page.evaluate(() => nodeAct({ action: 'vm-xml', name: 'probe' }));
  ok((probe.catalog || []).map(h => h.id).join() === 'unraid' && !probe.catalog[0].dev,
     `with unvetted features off the generator offers Unraid alone (${(probe.catalog || []).map(h => h.id).join(', ')})`);
  const no = await page.evaluate(() => nodeAct({ action: 'vm-xml', name: 'probe', hv: 'proxmox' }));
  ok(/Proxmox VE is dev, not yet vetted/.test(no.error || '') && /Offer dev features/.test(no.error || ''),
     `...and refuses another, naming the switch (${no.error})`);
  await page.evaluate(async () => { await fetch('/api/settings', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ set: { offer_unvetted: true } }) }); });
}
// A VM catalog that lands after its dialog closed paints over nothing else
// (B424): Render a VM, closed before the answer, Enroll opened in the same
// box and typed into, then the answer, and the enroll form is still there.
{
  await page.evaluate(() => {
    window.__realNodeAct = nodeAct;
    nodeAct = b => b.action === 'vm-xml' && !b.name
      ? new Promise(res => { window.__vmLand = () => res(window.__realNodeAct(b)); })
      : window.__realNodeAct(b);
  });
  await page.click('.nodestab #ndVm');
  await page.waitForSelector('#ndBody #vmGo', { timeout: 10000 });
  await page.evaluate(() => { document.getElementById('ndmodal').hidden = true; });
  await page.click('.nodestab #ndEnroll');
  await page.waitForSelector('#ndBody #ndEnName', { timeout: 10000 });
  await page.fill('#ndBody #ndEnName', 'racebox');
  await page.evaluate(async () => { window.__vmLand(); await new Promise(r => setTimeout(r, 300)); });
  const after = await page.$eval('#ndBody', b => ({ name: b.querySelector('#ndEnName')?.value, vm: !!b.querySelector('#vmGo') }));
  ok(after.name === 'racebox' && !after.vm,
     `a VM catalog landing after its dialog closed leaves the Enroll form, and what was typed, alone (${JSON.stringify(after)})`);
  await page.evaluate(() => { nodeAct = window.__realNodeAct; document.getElementById('ndmodal').hidden = true;
    document.getElementById('ndBody').innerHTML = ''; });
}
await page.click('.nodestab #ndVm');
await page.waitForSelector('#ndBody .vmform', { timeout: 10000 });
ok(await page.$eval('#ndBody', b => !b.querySelector('.vmmade')),
   'Create sandbox VM opens on the machine\'s sizes, with nothing rendered yet');
// Every hypervisor with a template here is offered, and the list is the
// server's: the templates that actually ship, not a copy of them in the page.
await page.waitForFunction(() => (document.querySelectorAll('#ndBody #vm_hv option') || []).length > 1,
                           null, { timeout: 15000 });
const kinds = await page.$$eval('#ndBody #vm_hv option', os => os.map(o => o.value));
ok(kinds.includes('unraid') && kinds.includes('proxmox') && kinds.length >= 5,
   `the picker offers every hypervisor a template ships for (${kinds.join(', ')})`);
ok(await page.$$eval('#ndBody #vm_hv option', os => os.filter(o => o.value !== 'unraid').every(o => / \(dev\)$/.test(o.textContent))
                                                     && !/dev/.test(os.find(o => o.value === 'unraid').textContent)),
   '...the unproven ones tagged dev and Unraid not');
await page.fill('#ndBody #vm_name', 'bb-sandbox-2');
await page.fill('#ndBody #vm_memory_gb', '24');
await page.click('#ndBody #vmGo');
await page.waitForSelector('#ndBody .vmxml', { timeout: 15000 });
const vm1 = await page.$eval('#ndBody .vmxml', p => p.textContent);
ok(/<name>bb-sandbox-2<\/name>/.test(vm1) && /<memory unit="KiB">25165824<\/memory>/.test(vm1)
   && /<source file="\/mnt\/user\/domains\/bb-sandbox-2\/vdisk1\.qcow2"\/>/.test(vm1),
   'Generate renders the machine with the name, the memory and the vdisk path asked for');
const idOf = x => [ (x.match(/<uuid>([^<]+)<\/uuid>/) || [])[1],
                    (x.match(/<mac address="([^"]+)"/) || [])[1],
                    (x.match(/nvram\/([^_]+)_VARS/) || [])[1] ];
const [u1, m1, n1] = idOf(vm1);
ok(u1 && m1 && n1 === u1,
   `...with a uuid of its own, and the nvram file named after it (${u1})`);
ok(/^52:54:00:/.test(m1), `...and a MAC on QEMU's own prefix (${m1})`);
ok(!/<!--/.test(vm1),
   '...and no comments: they are for whoever reads the repository, and Unraid drops them');
await page.click('#ndBody #vmGo');
await page.waitForFunction(x => document.querySelector('#ndBody .vmxml')?.textContent !== x,
                           vm1, { timeout: 15000 });
const [u2, m2] = idOf(await page.$eval('#ndBody .vmxml', p => p.textContent));
ok(u2 !== u1 && m2 !== m1,
   'a second render is a second machine: neither the uuid nor the MAC is reused');
ok((await page.$$eval('#ndBody .vmsteps li', ls => ls.length)) >= 5
   && await page.$eval('#ndBody .vmsteps', ol => /NFS Security Settings/.test(ol.textContent)),
   '...and the steps say how to get from here to an enrolled node, exports first');
// The CPU topology moves with the count: libvirt refuses a machine whose
// sockets x cores x threads is not its vcpu count, which every count but
// the shipped six tripped (Unraid, 4 vCPUs, 15 Sep).
{
  const four = await page.evaluate(() => nodeAct({ action: 'vm-xml', name: 'bb-four', cores: 4 }));
  const topo = /<topology sockets="(\d+)" cores="(\d+)" threads="(\d+)"\/>/.exec(four.text || '');
  ok(/<vcpu placement="static">4<\/vcpu>/.test(four.text || '') && topo
     && Number(topo[1]) * Number(topo[2]) * Number(topo[3]) === 4,
     `4 vCPUs gives a topology whose product is 4 (${topo ? topo[0] : four.error || 'no topology'})`);
}
const bad = await page.evaluate(() => nodeAct({ action: 'vm-xml', name: '../evil' }));
ok(!!bad.error && !bad.xml, 'a name that is not a name is refused rather than escaped into the file');
// ...and Unraid's own pair goes back in, which is what a VM that already
// exists needs: its nvram file is named after that uuid and its reservation
// was made against that MAC.
await page.fill('#ndBody #vm_uuid', 'B091DB01-CBDD-07B7-C797-79CA40D31A00');
await page.fill('#ndBody #vm_mac', '52:54:00:46:D2:FB');
await page.click('#ndBody #vmGo');
await page.waitForFunction(() => /b091db01/.test(document.querySelector('#ndBody .vmxml')?.textContent || ''),
                           null, { timeout: 15000 });
const kept = await page.$eval('#ndBody .vmxml', p => p.textContent);
ok(/<uuid>b091db01-cbdd-07b7-c797-79ca40d31a00<\/uuid>/.test(kept)
   && /nvram\/b091db01-cbdd-07b7-c797-79ca40d31a00_VARS/.test(kept)
   && /<mac address="52:54:00:46:d2:fb"\/>/.test(kept),
   'Unraid\'s own uuid and MAC are taken as given, and the nvram path follows the uuid');
const badId = await page.evaluate(() => nodeAct({ action: 'vm-xml', uuid: 'nope' }));
ok(!!badId.error && !badId.text, '...and something that is not a uuid is refused');

// ---- and the same machine on somebody else's hypervisor ---------------------
// A node is a machine, not an Unraid machine. The picker switches template,
// and what changes with it is the artifact, the steps, and the MAC range.
// The last is the one nobody gets right by hand: VMware refuses a static
// address outside its own, Hyper-V and VirtualBox hand out their own, and a
// machine wearing the wrong prefix is the one that collides.
await page.selectOption('#ndBody #vm_hv', 'proxmox');
await page.waitForFunction(() => !!document.querySelector('#ndBody #vm_vmid'),
                           null, { timeout: 10000 });
ok(true, 'switching to Proxmox asks for the VM id it numbers machines with');
await page.click('#ndBody #vmGo');
await page.waitForFunction(() => /qm create/.test(document.querySelector('#ndBody .vmxml')?.textContent || ''),
                           null, { timeout: 15000 });
{
  const pve = await page.$eval('#ndBody .vmxml', p => p.textContent);
  ok(/qm create 9000/.test(pve) && /--cores 6/.test(pve) && /--memory 24576/.test(pve)
     && /--smbios1 uuid=[0-9a-f-]{36}/.test(pve),
     'Proxmox comes back as a qm create with the same machine in it');
  ok(/virtio=52:54:00:/.test(pve), '...on QEMU\'s MAC range, which is what Proxmox is');
  ok(await page.$eval('#ndBody .vmsteps', ol => /Proxmox host as root/.test(ol.textContent)),
     '...and the steps are that manager\'s, not Unraid\'s');
}
for (const [hv, want, mark] of [['vmware', /^00:50:56:/, /ethernet0\.address/],
                                ['hyperv', /^00:15:5d:/, /Set-VMNetworkAdapter/],
                                ['virtualbox', /^08:00:27:/, /VBoxManage createvm/]]){
  const r = await page.evaluate(h => nodeAct({ action: 'vm-xml', hv: h, name: 'bb-node' }), hv);
  ok(!r.error && mark.test(r.text) && want.test(r.mac),
     `${hv} renders its own kind of file, with a MAC in its own range (${r.mac})`);
  const wrong = await page.evaluate(h => nodeAct({ action: 'vm-xml', hv: h, mac: '52:54:00:11:22:33' }), hv);
  ok(!!wrong.error && /MAC in/.test(wrong.error),
     `...and refuses one from another vendor's range rather than writing a machine that collides`);
}
ok(!!(await page.evaluate(() => nodeAct({ action: 'vm-xml', hv: 'bhyve' }))).error,
   'a hypervisor with no template here says so rather than guessing');
await page.evaluate(async () => { await fetch('/api/settings', { method: 'POST',
  headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ set: { offer_unvetted: false } }) }); });
page.errors = [];
await page.click('#ndBody #vmCancel');

// ---- debug: whose machine logs a node's sessions may read -------------------
// A session on a node reads the logs of its own WORK (its project's CI runs,
// what its test runs left) and nothing of the machine. The agent's journal
// is root's there: the enrolled account is in neither adm nor
// systemd-journal, so journalctl from a session answers "insufficient
// permissions". This opens that deliberately, per node, and only while the
// controller's debug switch is on.
{
  const n = (await page.evaluate(async () =>
    (await (await fetch('/api/v1/nodes')).json()).nodes))
    .find(x => x.kind === 'agent');
  // The asking node is derived from the session's PROJECT, never from the
  // request and never from a node session's BB_NODE, which is a variable a
  // session can set. So alpha has to be on this node for the question to
  // have an asker at all.
  await page.evaluate(async id => {
    await fetch('/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'alpha', node: id }) });
  }, n.id);
  const read = (node, extra = {}) => page.evaluate(async ([nd, ex]) => {
    const r = await fetch('/api/nodelog', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ node: nd, ...ex }) });
    return { status: r.status, ...(await r.json()) };
  }, [node, extra]);

  // The switch first. Off (the default), nothing is offered to anybody,
  // whatever any node has been granted.
  let r = await read(n.name);
  ok(r.status === 403 && /debug mode is off/.test(r.error || ''),
     `with debug mode off a machine's logs are refused, saying what turns it on (${
       (r.error || '').slice(0, 48)})`);
  await page.evaluate(async () => {
    await fetch('/api/settings', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ set: { debug_mode: true } }) });
  });

  // On, and still refused: the switch grants nothing. The grant is the
  // PROJECT's since 6 Oct (its settings' Debug), not the node's, so another
  // project on the same node is not handed it.
  r = await read(n.name, { project: 'alpha' });
  ok(r.status === 403 && /alpha has not been granted/.test(r.error || ''),
     `...and on, a project still reads nothing until it is granted it (${
       (r.error || '').slice(0, 56)})`);

  const grant = from => page.evaluate(async f => (await (await fetch('/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'alpha', log_from: f }) })).json()), from);
  ok(!(await grant([n.id])).error, 'a project can be granted a node\'s machine logs');
  const back = (await page.evaluate(async () =>
    (await (await fetch('/api/status')).json()).projects)).find(x => x.name === 'alpha');
  ok((back?.prefs?.log_from || []).join() === n.id,
     '...and the grant is on the project\'s settings, where its dialog reads it');
  ok(!(await grant([])).error
     && !((await page.evaluate(async () =>
          (await (await fetch('/api/status')).json()).projects))
          .find(x => x.name === 'alpha')?.prefs?.log_from || []).length,
     'and the grant comes back off, which is the way out');

  // A stream this table does not have is not reachable however it is asked
  // for: what can be read is a lookup, like everything else the web can run.
  await grant([n.id]);
  r = await read(n.name, { project: 'alpha', stream: 'passwd' });
  ok(!!r.error && /no such log/.test(r.error),
     `a log this table does not name is refused, not run (${(r.error || '').slice(0, 40)})`);
  await grant([]);
  await page.evaluate(async () => {
    await fetch('/api/settings', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ set: { debug_mode: false } }) });
    await fetch('/api/prefs', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'alpha', node: '' }) });
  });
  page.errors = [];
}

// ---- the seam stays invisible on the sidebar --------------------------------
ok(await page.evaluate(() => !document.querySelector('[data-card="nodes"]')),
   'still no nodes card: nodes are a tab, not sidebar chrome');
ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
// ---- Uninstall from the row --------------------------------------------------
// Last, because it retires the node it makes. A sandbox node queues the
// system job; a node that was not provisioned as one is refused with the
// command to run on the machine; and the row is retired when the job
// lands, which the fake agent reports the way a real one does.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const base = URL.replace(/\/$/, '');
  const napi = async (path, body, headers = H) => (await fetch(base + path, body === undefined
    ? { headers } : { method: 'POST', headers, body: JSON.stringify(body) })).json();
  const shipped = (await napi('/api/v1/nodes')).agent || {};
  const mint = async (name, census) => {
    const m = await napi('/api/v1/nodes', { action: 'enroll', name });
    const en = await napi('/api/v1/agent/enroll', { census, version: shipped.version, digest: shipped.digest, user: 'bb' },
                          { Authorization: 'Bearer ' + m.token, 'Content-Type': 'application/json' });
    return { id: m.id, token: en.token };
  };
  const plain = await mint('laptop', { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', docker: true });
  const shed = await mint('shed2', { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', docker: true, sandbox: true });
  // Reboot and Shut down from the row (the operator, 25 Sep): a system job
  // the agent runs as root, refused where nothing from here would reach
  // the machine. The controller's own machine is rebooted from its host.
  {
    const lo = await napi('/api/v1/nodes', { action: 'reboot', id: 'local' });
    ok(/controller's own machine/.test(lo.error || ''), `the controller's own machine is not rebooted from here (${lo.error})`);
    const rb = await napi('/api/v1/nodes', { action: 'reboot', id: plain.id });
    ok(rb.ok && /^j_/.test(rb.job || ''), `a live agent node queues the reboot as a system job (${rb.error || rb.job})`);
    const rj = await napi(`/api/v1/jobs?id=${rb.job}`);
    ok(rj.spec?.apply === 'reboot' && rj.node === plain.id, 'the job asks the agent for the reboot');
    const twice = await napi('/api/v1/nodes', { action: 'poweroff', id: plain.id });
    ok(/one at a time/.test(twice.error || ''), '...and a shutdown pressed meanwhile waits for it');
    // The tab shows one node at a time, the picker's; laptop is picked
    // for the row, and the controller's own after it.
    await page.evaluate(() => openNodesTab());
    await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
    await page.evaluate(() => loadNodes());
    await page.waitForFunction(id => [...document.querySelectorAll('.nodestab #ndPick option')].some(o => o.value === id), plain.id, { timeout: 15000 });
    await page.selectOption('.nodestab #ndPick', plain.id);
    await page.waitForSelector(`.ndrow[data-node="${plain.id}"]`, { timeout: 20000 });
    const drawn = await page.evaluate(id => {
      const box = document.querySelector(`.ndrow[data-node="${CSS.escape(id)}"]`);
      return box ? [!!box.querySelector('[data-nd="reboot"]'), !!box.querySelector('[data-nd="poweroff"]'),
                    box.querySelector('[data-nd="reboot"]')?.textContent] : null;
    }, plain.id);
    ok(drawn && drawn[0] && drawn[1] && /Rebooting/.test(drawn[2] || ''),
       `the row carries Reboot and Shut down, and says the reboot is in flight (${JSON.stringify(drawn)})`);
    await napi('/api/v1/jobs', { action: 'cancel', id: rb.job });
    // The controller's own row, drawn as the tab draws it: neither verb.
    const local = await page.evaluate(() => /data-nd="(reboot|poweroff)"/.test(
      nodeAdvancedSection({ id: 'local', kind: 'local', name: 'controller', state: 'online', config: {}, reported: {} },
                          false, () => false)));
    ok(local === false, `...and the controller's own row has neither (${local})`);
  }
  // The GPU display (R20): a node whose census names an NVIDIA card gets the
  // line in Health with Set up GPU display where it is a sandbox; a node
  // that is not one is refused with the command for the machine.
  {
    await fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + shed.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', docker: true, sandbox: true,
                                       gpu_card: 'NVIDIA Corporation GA104 [GeForce RTX 3070 Ti]', gpu_display: '' },
                             version: shipped.version, digest: shipped.digest }) });
    const no = await napi('/api/v1/nodes', { action: 'gpu-display', id: plain.id });
    ok(/sudo bb-sandbox gpu/.test(no.error || ''), `a node that is not a sandbox is refused, and told the command for the machine (${no.error})`);
    const g = await napi('/api/v1/nodes', { action: 'gpu-display', id: shed.id });
    ok(g.ok && /^j_/.test(g.job || ''), `a sandbox node with a card queues the set-up as a system job (${g.error || g.job})`);
    const gj = await napi(`/api/v1/jobs?id=${g.job}`);
    ok(gj.spec?.apply === 'gpu' && gj.node === shed.id, 'the job asks the agent for bb-sandbox gpu');
    await page.evaluate(() => loadNodes());
    await page.waitForFunction(id => [...document.querySelectorAll('.nodestab #ndPick option')].some(o => o.value === id), shed.id, { timeout: 15000 });
    await page.selectOption('.nodestab #ndPick', shed.id);
    await openSection(page, 'nodes:health', `.ndrow[data-node="${shed.id}"]`);
    await page.waitForSelector(`.ndrow[data-node="${shed.id}"] .ndgpu`, { timeout: 20000 });
    const line = await page.$eval(`.ndrow[data-node="${shed.id}"] .ndgpu`, e => e.textContent.replace(/\s+/g, ' ').trim());
    ok(/RTX 3070 Ti/.test(line) && /renders in software/.test(line),
       `the row's Health names the card and says the emulator is on software (${line.slice(0, 90)})`);
    // A change being applied on the machine holds Reboot and Shut down, on
    // the row and, as before, on the server (the operator, 30 Sep).
    const held = await page.$eval(`.ndrow[data-node="${shed.id}"]`, r => ({
      dead: ['reboot', 'poweroff'].map(w => r.querySelector(`[data-nd="${w}"]`)?.disabled),
      why: [...r.querySelectorAll('.state')].map(e => e.textContent).find(t => /Reboot and Shut down wait/.test(t)) || '' }));
    ok(held.dead.every(Boolean) && /a change to this node \(gpu\)/.test(held.why),
       `while a change is applying on the node, Reboot and Shut down are ghosted and say why (${held.why})`);
    await napi('/api/v1/jobs', { action: 'cancel', id: g.job });
    // ...and the tab read again, so the canceled set-up is not what the
    // section below is drawn from.
    await page.evaluate(() => loadNodes());
    await page.waitForFunction(id => !(nodesList || []).find(n => n.id === id)?.jobs?.some(j => j.apply === 'gpu'), shed.id, { timeout: 15000 });
    await page.evaluate(id => { const c = nodesConf[id]; if (c?.draft){ c.draft.gpuEmu = undefined; } nodesRev++; drawPanes(); }, shed.id);
    // What the card is for (R102): a GPU section with two switches and one
    // Apply. Neither writes on the click; Apply sends each only where its
    // tick differs from what the node has.
    const sect = `.ndrow[data-node="${shed.id}"] details[data-sect="nodes:gpu"]`;
    await page.waitForSelector(sect, { state: 'attached', timeout: 20000 });
    await page.evaluate(s => { const d = document.querySelector(s); if (d && !d.open) d.open = true; }, sect);
    const sw = async () => page.$eval(sect, e => ({ emu: e.querySelector('[data-k="gpuemu"]').checked, comp: e.querySelector('[data-k="gpucomp"]').checked,
      emuDead: e.querySelector('[data-k="gpuemu"]').disabled, apply: !!e.querySelector('[data-nd="gpu-apply"]'), status: e.querySelector('.sst')?.textContent.trim() }));
    let s0 = await sw();
    ok(!s0.emu && s0.comp && !s0.emuDead && s0.apply && s0.status === 'compute',
       `the GPU section has the two switches and one Apply: the emulator off the card, compute allowed by default (${JSON.stringify(s0)})`);
    await page.click(`${sect} [data-k="gpucomp"]`);
    const before = ((await napi('/api/v1/nodes')).nodes.find(n => n.id === shed.id).config || {}).no_gpu_compute;
    ok(before === undefined, 'unticking compute writes nothing until Apply');
    await page.click(`${sect} [data-nd="gpu-apply"]`);
    await page.waitForFunction(async id => ((await (await fetch('/api/v1/nodes')).json()).nodes.find(n => n.id === id).config || {}).no_gpu_compute === true,
                               shed.id, { timeout: 15000 });
    ok(true, '...and Apply turns compute off for sessions started on the node from now on');
    await page.waitForFunction(s => document.querySelector(s)?.querySelector('.sst')?.textContent.trim() === 'not used', sect, { timeout: 15000 });
    await openSection(page, 'nodes:gpu', `.ndrow[data-node="${shed.id}"]`);
    await page.click(`${sect} [data-k="gpucomp"]`);
    await page.click(`${sect} [data-k="gpuemu"]`);
    await page.click(`${sect} [data-nd="gpu-apply"]`);
    const ej = await (async () => { for (let i = 0; i < 60; i++){ const n = (await napi('/api/v1/nodes')).nodes.find(x => x.id === shed.id);
      const j = (n.jobs || []).find(x => x.apply === 'gpu'); if (j && !(n.config || {}).no_gpu_compute) return j; await new Promise(r => setTimeout(r, 250)); } return null; })();
    ok(ej !== null, 'ticking both and Apply turns compute back on and queues the emulator set-up as a job on the node');
    // ...and while that job runs the box stays ticked, ghosted, rather than
    // going back to the machine's old state under "Applying".
    await page.evaluate(() => loadNodes());
    await page.waitForFunction(s => document.querySelector(s)?.querySelector('[data-nd="gpu-apply"]')?.disabled, sect, { timeout: 15000 });
    const mid = await sw();
    ok(mid.emu && mid.emuDead, `while the emulator's job runs its box stays ticked and ghosted (${JSON.stringify(mid)})`);
    if (ej?.id) await napi('/api/v1/jobs', { action: 'cancel', id: ej.id });
    // The emulator off the card: its own system job, where the display is up.
    await fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + shed.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', docker: true, sandbox: true,
                                       gpu_card: 'NVIDIA Corporation GA104 [GeForce RTX 3070 Ti]', gpu_display: 'up' },
                             version: shipped.version, digest: shipped.digest }) });
    const off = await napi('/api/v1/nodes', { action: 'gpu-display', id: shed.id, on: false });
    const oj = off.job ? await napi(`/api/v1/jobs?id=${off.job}`) : {};
    ok(off.ok && oj.spec?.apply === 'gpu-off', `taking the emulator off the card is its own system job (${off.error || oj.spec?.apply})`);
    await napi('/api/v1/jobs', { action: 'cancel', id: off.job });
    // The briefing's GPU section reaches a session only where its project's
    // node reports a card: a fact about the machine, not the tree.
    const without = (await napi('/api/preamble?project=delta')).text || '';
    await napi('/api/prefs', { project: 'delta', node: shed.id });
    const withCard = (await napi('/api/preamble?project=delta')).text || '';
    await napi('/api/prefs', { project: 'delta', node: '' });
    ok(!/## The GPU/.test(without) && /## The GPU/.test(withCard) && /bb gpu run \[--mem MB\] -- CMD/.test(withCard),
       'the briefing carries its GPU section for a project whose node has a card, and for no other');
  }
  // The sound a node has (R107): the census's cards and server, cleaned on
  // the way in, and a line on the row in words.
  {
    const hello = census => fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + shed.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', ...census },
                             version: shipped.version, digest: shipped.digest }) });
    await hello({ sound: { cards: ['HDA Intel PCH<b>'], virtual: [], server: 'jack; rm' } });
    const rec = (await napi('/api/v1/nodes')).nodes.find(n => n.id === shed.id);
    ok(rec?.reported?.sound?.cards?.[0] === 'HDA Intel PCHb' && rec.reported.sound.server === '',
       `the census's sound is kept cleaned: a card's name, and only a server it knows (${JSON.stringify(rec?.reported?.sound)})`);
    const words = await page.evaluate(() => [
      nodeSound({ kind: 'agent', reported: { sound: { cards: [], virtual: [], server: '' } } }),
      nodeSound({ kind: 'agent', reported: { sound: { cards: ['HDA Intel PCH'], virtual: [], server: 'pipewire' } } }),
      nodeSound({ kind: 'agent', reported: { sound: { cards: [], virtual: ['Dummy'], server: '' } } }),
      nodeSound({ kind: 'agent', reported: {} })].map(h => h.replace(/<[^>]+>/g, '').trim()));
    ok(words[0] === 'sound: none: no sound card and no sound server'
       && words[1] === 'sound: HDA Intel PCH through pipewire'
       && /Dummy \(virtual\), with no sound server/.test(words[2]) && words[3] === '',
       `the row says the sound in words, and nothing for an agent too old to say (${words.join(' | ')})`);
  }
  // The NVIDIA driver as a row of the Toolchains tab (R102): a row like the
  // store's, ticked into the same Install selected and asked by the same
  // check, with a pulldown of the branches apt offers that is live only
  // while no driver is installed. Its state is the census's; a guest
  // machine's driver is its owner's; and the display no longer installs it.
  {
    const card = 'NVIDIA Corporation GA104 [GeForce RTX 3070 Ti] [10de:2482] (rev a1)';
    const options = [{ pkg: 'nvidia-driver-610', version: '610.57.04', open: false },
                     { pkg: 'nvidia-driver-595', version: '595.91.07', open: false },
                     { pkg: 'nvidia-driver-595-open', version: '595.91.07', open: true }];
    const apt = { recommended: 'nvidia-driver-595', options, package: '', pkg_version: '', candidate: '' };
    const hello = (who, census) => fetch(base + '/api/v1/agent/hello', { method: 'POST',
      headers: { Authorization: 'Bearer ' + who.token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', docker: true, ...census },
                             version: shipped.version, digest: shipped.digest }) });
    const rowOf = async id => ((await napi(`/api/toolchains?node=${id}`)).machine || [])[0];
    const cancel = async r => { if (r?.job) await napi('/api/v1/jobs', { action: 'cancel', id: r.job }); };
    await hello(shed, { sandbox: true, gpu_card: card });
    let r = await rowOf(shed.id);
    ok(r?.state === 'unknown' && r.managed === true, `an agent that does not report the driver reads as unknown (${r?.state})`);
    const early = await napi('/api/toolchains', { action: 'install', names: ['nvidia-driver'], node: shed.id });
    ok(/update it on the Nodes tab/.test(early.error || ''), `...and an install waits for the agent's update (${early.error})`);
    const seen = [];
    for (const [gd, want] of [
      [{ installed: '', loaded: '', bound: 'nouveau' }, 'absent'],
      [{ installed: '595.91.07', loaded: '', bound: 'nouveau' }, 'waiting'],
      [{ installed: '595.91.07', loaded: '595.91.07', bound: 'nvidia' }, 'loaded'],
      [{ installed: '595.95.01', loaded: '595.91.07', bound: 'nvidia' }, 'update'],
      [{ installed: '', loaded: '595.91.07', bound: 'nvidia' }, 'leaving']]){
      await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: { ...apt, ...gd } });
      seen.push([(await rowOf(shed.id))?.state, want]);
    }
    ok(seen.every(([got, want]) => got === want), `the row's state follows the census (${seen.map(x => x[0]).join(', ')})`);
    const absent = { ...apt, installed: '', loaded: '', bound: 'nouveau' };
    await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: absent });
    // The display runs on the driver and no longer installs it: refused
    // until the driver is on the machine, and the Nodes tab's line sends its
    // reader to this row instead of offering the set-up.
    const disp = await napi('/api/v1/nodes', { action: 'gpu-display', id: shed.id });
    ok(/install it on that node's Toolchains tab first/.test(disp.error || ''), `the display is not set up before the driver is installed, and says where that is (${disp.error})`);
    // In a batch with a store toolchain, the driver goes last.
    const mixed = await napi('/api/toolchains', { action: 'install', names: ['nvidia-driver', 'zig'], node: shed.id });
    const mj = mixed.job ? await napi(`/api/v1/jobs?id=${mixed.job}`) : {};
    ok(mixed.ok && mj.type === 'toolchain' && (mj.spec?.names || []).at(-1) === 'nvidia-driver' && mj.spec.names.includes('zig'),
       `the driver is ticked into the same job as the store's toolchains, after them (${mixed.error || (mj.spec?.names || []).join(', ')})`);
    // ...and an install running holds Reboot and Shut down on the server,
    // as the row does.
    const rbw = await napi('/api/v1/nodes', { action: 'reboot', id: shed.id });
    ok(/a toolchain install or removal is running on shed2/.test(rbw.error || ''),
       `a reboot waits for a toolchain install on the node (${rbw.error})`);
    await cancel(mixed);
    const bogus = await napi('/api/toolchains', { action: 'install', names: ['nvidia-driver'], driver: 'nvidia-driver-999', node: shed.id });
    ok(/not a driver apt offers/.test(bogus.error || ''), `a branch apt does not offer there is refused (${bogus.error})`);
    // Drawn on the tab: a tick box, the card by name, the state in words,
    // and the pulldown, the recommended branch first.
    await page.evaluate(() => { nodesList = null; openToolchains(); });
    await page.waitForFunction(id => [...document.querySelectorAll('.doc .tctab #tcNodeSel option')].some(o => o.value === id),
                               shed.id, { timeout: 20000 });
    await page.selectOption('.doc .tctab #tcNodeSel', shed.id);
    await page.waitForSelector('.doc .tctab .tcmachine .tcdrv #tcDrvSel', { timeout: 20000 });
    const drawn = await page.$eval('.doc .tctab .tcdrv', e => ({ text: e.textContent.replace(/\s+/g, ' ').trim(),
      tick: e.querySelector('#tcDrvTick') ? { on: e.querySelector('#tcDrvTick').checked, dead: e.querySelector('#tcDrvTick').disabled } : null,
      opts: [...e.querySelectorAll('#tcDrvSel option')].map(o => o.textContent.trim()), dead: e.querySelector('#tcDrvSel').disabled,
      first: e.closest('.tcs')?.nextElementSibling?.classList.contains('tcs') }));
    ok(/NVIDIA driver/.test(drawn.text) && /GeForce RTX 3070 Ti/.test(drawn.text) && /not installed: nouveau has the card/.test(drawn.text)
       && drawn.tick && !drawn.tick.on && !drawn.tick.dead && drawn.first,
       `the tab draws the driver's row above the store's, with a tick box like theirs (${drawn.text.slice(0, 90)})`);
    ok(!drawn.dead && drawn.opts.length === 3 && /^595\.91\.07 · recommended for this card$/.test(drawn.opts[0])
       && /^610\.57\.04 · newer than recommended$/.test(drawn.opts[1]) && /^595\.91\.07 · open kernel modules$/.test(drawn.opts[2]),
       `its pulldown lists the branches apt offers, the recommended one first (${drawn.opts.join(' | ')})`);
    // Picking a version ticks the row; Install selected asks once, saying it
    // ends at a restart, and queues the picked branch.
    await page.selectOption('.doc .tctab #tcDrvSel', 'nvidia-driver-610');
    ok(await page.$eval('.doc .tctab #tcDrvTick', b => b.checked), 'picking a version ticks the row');
    const nd = page.dialogs.length;
    await page.click('.doc .tctab [data-tc="install"]');
    const qd = await (async () => { for (let i = 0; i < 40; i++){ const d = await napi(`/api/toolchains?node=${shed.id}`); if (d.job?.running) return d.job; await new Promise(res => setTimeout(res, 250)); } return null; })();
    const qj = qd ? await napi(`/api/v1/jobs?id=${qd.id}`) : {};
    ok(page.dialogs.length === nd + 1 && /takes the card only when the machine restarts/.test(page.dialogs[nd] || '')
       && qj.type === 'toolchain' && JSON.stringify(qj.spec?.names) === '["nvidia-driver:nvidia-driver-610"]',
       `Install selected asks first, saying it ends at a restart, and queues the picked branch (${JSON.stringify(qj.spec?.names)})`);
    await napi('/api/v1/jobs', { action: 'cancel', id: qd?.id });
    // Installed: the pulldown is ghosted on the installed branch and says
    // why, the tick is the dead one of an installed row, and Remove is there.
    await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: { ...apt, installed: '595.91.07', loaded: '595.91.07', bound: 'nvidia',
      package: 'nvidia-driver-595', pkg_version: '595.91.07-0ubuntu1', candidate: '595.91.07-0ubuntu1' } });
    await page.evaluate(() => loadToolchains());
    await page.waitForFunction(() => /installed, and running the card/.test(document.querySelector('.doc .tctab .tcdrv')?.textContent || ''), null, { timeout: 20000 });
    const inst = await page.$eval('.doc .tctab .tcdrv', e => ({ dead: e.querySelector('#tcDrvSel').disabled, why: e.querySelector('#tcDrvSel').title,
      val: e.querySelector('#tcDrvSel').value, tick: [e.querySelector('#tcDrvTick').checked, e.querySelector('#tcDrvTick').disabled], rm: !!e.querySelector('[data-tcdrvrm]') }));
    ok(inst.dead && /remove it first to install another version/.test(inst.why) && inst.val === 'nvidia-driver-595' && inst.tick[0] && inst.tick[1] && inst.rm,
       `installed, its pulldown is ghosted on the installed branch and says to remove it first, with Remove beside it (${inst.val}; ${inst.why})`);
    const swap = await napi('/api/toolchains', { action: 'install', names: ['nvidia-driver'], driver: 'nvidia-driver-610', node: shed.id });
    ok(/nvidia-driver-595 is installed.*remove it first/.test(swap.error || ''), `...and the server holds the same rule (${swap.error})`);
    // A newer version of the installed branch: said on the row, and the tick
    // comes alive, as a toolchain's does.
    await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: { ...apt, installed: '595.91.07', loaded: '595.91.07', bound: 'nvidia',
      package: 'nvidia-driver-595', pkg_version: '595.91.07-0ubuntu1', candidate: '595.95.01-0ubuntu1' } });
    await page.evaluate(() => loadToolchains());
    await page.waitForFunction(() => /update available: 595\.95\.01/.test(document.querySelector('.doc .tctab .tcdrv')?.textContent || ''), null, { timeout: 20000 });
    ok(await page.$eval('.doc .tctab #tcDrvTick', b => !b.disabled && !b.checked),
       'a newer version of the installed branch is said on the row, and its tick comes alive');
    const nr = page.dialogs.length;
    await page.click('.doc .tctab .tcdrv [data-tcdrvrm]');
    const rd = await (async () => { for (let i = 0; i < 40; i++){ const d = await napi(`/api/toolchains?node=${shed.id}`); if (d.job?.running) return d.job; await new Promise(res => setTimeout(res, 250)); } return null; })();
    ok(page.dialogs.length === nr + 1 && /nouveau takes the card back/.test(page.dialogs[nr] || '') && rd?.action === 'remove' && (rd.queue || []).includes('nvidia-driver'),
       `Remove asks first, in the driver's own words, and queues the removal (${(page.dialogs[nr] || '').slice(0, 50)})`);
    await napi('/api/v1/jobs', { action: 'cancel', id: rd?.id });
    // The container toolkit (R102): the machine's second row, under the
    // driver it needs. Refused alone where there is no driver and queued
    // after it when both are ticked; its install says first that it adds
    // NVIDIA's package source; and there is no row without Docker.
    {
      const KIT = 'nvidia-container-toolkit';
      const kitOf = async id => ((await napi(`/api/toolchains?node=${id}`)).machine || []).find(m => m.name === KIT);
      const running = async () => { for (let i = 0; i < 40; i++){ const d = await napi(`/api/toolchains?node=${shed.id}`); if (d.job?.running) return d.job; await new Promise(res => setTimeout(res, 250)); } return null; };
      const on = { ...apt, installed: '595.91.07', loaded: '595.91.07', bound: 'nvidia',
        package: 'nvidia-driver-595', pkg_version: '595.91.07-0ubuntu1', candidate: '595.91.07-0ubuntu1' };
      const none = { installed: '', candidate: '', runtime: false };
      await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: on });
      const old = await kitOf(shed.id);
      const kearly = await napi('/api/toolchains', { action: 'install', names: [KIT], node: shed.id });
      ok(old?.state === 'unknown' && /update it on the Nodes tab/.test(kearly.error || ''),
         `an agent that does not report the container toolkit reads as unknown, and an install waits for its update (${old?.state}; ${kearly.error})`);
      await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: absent, gpu_container: none });
      const lone = await napi('/api/toolchains', { action: 'install', names: [KIT], node: shed.id });
      ok(/tick the driver as well/.test(lone.error || ''), `without the driver the toolkit alone is refused, saying what to tick (${lone.error})`);
      const both = await napi('/api/toolchains', { action: 'install', names: [KIT, 'nvidia-driver', 'zig'], node: shed.id });
      const bj = both.job ? await napi(`/api/v1/jobs?id=${both.job}`) : {};
      ok(both.ok && JSON.stringify((bj.spec?.names || []).slice(-2)) === `["nvidia-driver","${KIT}"]` && bj.spec.names.includes('zig'),
         `ticked together they are one job: the store's first, then the driver, then the toolkit (${both.error || (bj.spec?.names || []).join(', ')})`);
      await cancel(both);
      await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: on, gpu_container: none });
      await page.evaluate(() => loadToolchains());
      await page.waitForFunction(() => /a container here cannot reserve the card/.test(document.querySelector('.doc .tctab #tcCtkTick')?.closest('.tcdrv')?.textContent || '')
                                       && !document.querySelector('.doc .tctab #tcCtkTick').disabled, null, { timeout: 20000 });
      const kd = await page.$eval('.doc .tctab #tcCtkTick', b => ({ on: b.checked, text: b.closest('.tcdrv').textContent.replace(/\s+/g, ' ').trim(),
        under: !!b.closest('.tcdrv').previousElementSibling?.querySelector('#tcDrvTick') && !!b.closest('.tcmachine'),
        rm: !!b.closest('.tcdrv').querySelector('[data-tcctkrm]') }));
      ok(!kd.on && kd.under && !kd.rm && /NVIDIA container toolkit/.test(kd.text) && /Running containers keep running/.test(kd.text),
         `the tab draws the toolkit's row under the driver's, with a tick box and what it costs (${kd.text.slice(0, 80)})`);
      await page.click('.doc .tctab #tcCtkTick');
      const ni = page.dialogs.length;
      await page.click('.doc .tctab [data-tc="install"]');
      const ij = await running();
      const ijob = ij ? await napi(`/api/v1/jobs?id=${ij.id}`) : {};
      ok(page.dialogs.length === ni + 1 && /adds NVIDIA's own package source/.test(page.dialogs[ni] || '')
         && JSON.stringify(ijob.spec?.names) === `["${KIT}"]` && ijob.spec?.action === 'install',
         `Install selected asks first, saying whose package source it adds, and queues the toolkit (${(page.dialogs[ni] || '').slice(0, 60)}; ${JSON.stringify(ijob.spec?.names)})`);
      await napi('/api/v1/jobs', { action: 'cancel', id: ij?.id });
      // Installed and known to Docker: the dead tick of an installed row,
      // how a compose file asks for the card, and Remove.
      await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: on, gpu_container: { installed: '1.17.8-1', candidate: '1.17.8-1', runtime: true } });
      await page.evaluate(() => loadToolchains());
      await page.waitForFunction(() => /a compose file reserves the card/.test(document.querySelector('.doc .tctab #tcCtkTick')?.closest('.tcdrv')?.textContent || ''), null, { timeout: 20000 });
      const ki = await page.$eval('.doc .tctab #tcCtkTick', b => ({ tick: [b.checked, b.disabled], pill: b.closest('.tcdrv').querySelector('.pill')?.textContent,
        rm: !!b.closest('.tcdrv').querySelector('[data-tcctkrm]') }));
      ok(ki.tick[0] && ki.tick[1] && ki.pill === '1.17.8' && ki.rm, `installed, its tick is the dead one of an installed row, with its version and Remove (${ki.pill})`);
      const nk = page.dialogs.length;
      await page.click('.doc .tctab [data-tcctkrm]');
      const kr = await running();
      ok(page.dialogs.length === nk + 1 && /no longer starts/.test(page.dialogs[nk] || '') && kr?.action === 'remove' && (kr.queue || []).includes(KIT),
         `Remove asks first, saying what stops working, and queues the removal (${(page.dialogs[nk] || '').slice(0, 60)})`);
      await napi('/api/v1/jobs', { action: 'cancel', id: kr?.id });
      // Installed but unknown to Docker, or with a newer one on offer: the
      // tick is alive, since there is something for an install to do.
      const alive = [];
      for (const [gc, want] of [[{ installed: '1.17.8-1', candidate: '1.17.8-1', runtime: false }, /does not list the nvidia runtime/],
                                [{ installed: '1.17.8-1', candidate: '1.18.0-1', runtime: true }, /update available: 1\.18\.0/]]){
        await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: on, gpu_container: gc });
        await page.evaluate(() => loadToolchains());
        alive.push(await page.waitForFunction(re => { const b = document.querySelector('.doc .tctab #tcCtkTick');
          return !!b && !b.disabled && new RegExp(re).test(b.closest('.tcdrv').textContent); }, want.source, { timeout: 20000 }).then(() => true, () => false));
      }
      ok(alive.every(Boolean), `unknown to Docker, or with a newer one on offer, the row says so and its tick comes alive (${alive.join(', ')})`);
      await hello(shed, { sandbox: true, docker: '', gpu_card: card, gpu_driver: on, gpu_container: none });
      ok(await kitOf(shed.id) === undefined, 'a machine with no Docker has no toolkit row');
      await hello(shed, { sandbox: true, gpu_card: card, gpu_driver: on, gpu_container: none });
    }
    // A guest machine: whose it is, on the row, and no press.
    await hello(plain, { gpu_card: card, gpu_driver: absent });
    const guest = await rowOf(plain.id);
    const gq = await napi('/api/toolchains', { action: 'install', names: ['nvidia-driver'], node: plain.id });
    ok(guest?.managed === false && /owner's machine/.test(gq.error || ''),
       `a guest machine's driver is its owner's: the row says so and an install is refused (${gq.error})`);
    await hello(shed, { sandbox: true, gpu_card: card });
  }
  const no = await napi('/api/v1/nodes', { action: 'uninstall', id: plain.id });
  ok(/only a node provisioned as a BuilderBot sandbox/.test(no.error || '') && /sudo bb-sandbox uninstall/.test(no.error || ''),
     `a node that is not a sandbox is refused, and told the command to run on the machine (${no.error})`);
  const r = await napi('/api/v1/nodes', { action: 'uninstall', id: shed.id });
  ok(r.ok && /^j_/.test(r.job || ''), `a sandbox node queues the uninstall as a system job (${r.error || r.job})`);
  const j = await napi(`/api/v1/jobs?id=${r.job}`);
  ok(j.spec?.apply === 'uninstall' && j.node === shed.id, 'the job asks the agent for the uninstall');
  const again = await napi('/api/v1/nodes', { action: 'uninstall', id: shed.id });
  ok(/one at a time/.test(again.error || ''), '...and a second press waits for the first');
  // The fake agent takes the job and reports it done, the way the real one does.
  const work = await fetch(base + '/api/v1/agent/work', { method: 'POST',
    headers: { Authorization: 'Bearer ' + shed.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ running: 0, wait: 0 }) });
  const got = work.status === 200 ? await work.json() : {};
  ok((got.job?.id || got.id) === r.job, `the agent is handed the job (${work.status})`);
  await napi('/api/v1/agent/result', { job: r.job, state: 'succeeded', exit: 0 },
             { Authorization: 'Bearer ' + shed.token, 'Content-Type': 'application/json' });
  const listed = (await napi('/api/v1/nodes')).nodes.some(n => n.id === shed.id);
  ok(!listed, 'and the node is retired when the job succeeds, so it leaves the list');
  await napi('/api/v1/nodes', { action: 'retire', id: plain.id });
}

// ---- Claude Code on a node: version, check, update (claudecode.py) ------
// The node reports what its session account runs; the controller asks the
// installer's `latest` (a file here) after it starts and on Check. Behind
// is a bell row and a sentence on the section; Update ends the Claude
// sessions there, queues the job, and holds the node's projects until it
// ends. A session's token cannot ask for it, and nothing in bb can.
{
  const base = URL.replace(/\/$/, '');
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const napi = async (path, body, hdrs) => (await fetch(base + path, {
    method: body ? 'POST' : 'GET', headers: { ...H, ...(hdrs || {}) },
    ...(body ? { body: JSON.stringify(body) } : {}) })).json();
  const mint = await napi('/api/v1/nodes', { action: 'enroll', name: 'clbox' });
  const shipped = (await napi('/api/v1/nodes')).agent || {};
  const census = { cpu: 2, mem_mb: 4096, os: 'linux x86_64 Ubuntu', system: 'linux', arch: 'x86_64', sandbox: true,
                   stores: { data: { path: '/var/lib/builderbot/data', free_mb: 5000, total_mb: 9000 } },
                   session: { up: true, port: 7681, ro_port: 7682, user: 'bb', workspace: true, writable: true,
                              boot: '77.1', up_s: 900, claude: '1.0.0 (Claude Code)' } };
  // The enrollment token enrolls and nothing else: the exchange hands the
  // agent its own, which every hello and heartbeat carries.
  const en = await napi('/api/v1/agent/enroll', { census, version: shipped.version, digest: shipped.digest, user: 'bb' },
                        { Authorization: 'Bearer ' + mint.token });
  en.id = en.node_id || mint.id;
  const hello = async () => (await fetch(base + '/api/v1/agent/hello', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({ census, version: shipped.version, digest: shipped.digest }) })).json();
  const hi = await hello();
  writeFileSync(`${DIR}/claude-latest`, '1.2.0\n');
  const me = (await napi('/api/v1/nodes')).nodes.find(n => n.id === en.id);
  ok(!!me?.live && me.reported?.session?.claude === '1.0.0 (Claude Code)',
     `the node dials in reporting its Claude Code (hello: ${JSON.stringify(hi).slice(0, 80)}; row: live=${me?.live} session=${JSON.stringify(me?.reported?.session || null).slice(0, 120)})`);
  // Claude Code is a toolchain of the node (R145): the Toolchains tab's
  // Check for updates asks its latest with the rest, in the same answer.
  const chk = await napi('/api/toolchains', { action: 'check', node: en.id });
  ok(chk.claude?.version === '1.2.0', `Check for updates asks the installer's latest and gets it (${chk.claude?.version || chk.claude?.error || chk.error})`);
  // The node's own toolchain check it queued beside: the fake agent takes it
  // and answers the way bb toolchains versions does, Go behind, so the tab
  // is not busy with it and the agent is handed the update next.
  const tcRowOf = st => (st.attention || []).find(a => a.kind === 'toolchain' && a.id === en.id);
  const claudeIn = st => (tcRowOf(st)?.tools || []).find(t => t.name === 'claude-code');
  if (chk.job) {
    const AH = { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' };
    const w = await fetch(base + '/api/v1/agent/work', { method: 'POST', headers: AH,
      body: JSON.stringify({ running: [], wait: 0 }) });
    const got = w.status === 200 ? await w.json() : {};
    if ((got.job?.id || got.id) === chk.job) {
      await napi('/api/v1/agent/log', { job: chk.job, chunks: [
        { seq: 1, chunk: 'go\t1.27.0\t1.28.0\tupdate\nnode\t22.1.0\t22.1.0\tcurrent\n' }] }, AH);
      await napi('/api/v1/agent/result', { job: chk.job, state: 'succeeded', exit: 0 }, AH);
    } else await napi('/api/v1/jobs', { action: 'cancel', id: chk.job });
  }
  const st = await napi('/api/status');
  const row = tcRowOf(st);
  const cl = claudeIn(st), goRow = (row?.tools || []).find(t => t.name === 'go');
  ok(cl?.from === '1.0.0' && cl.to === '1.2.0' && cl.label === 'Claude Code',
     `a node behind is a bell row naming both versions (${JSON.stringify(row || st.attention)})`);
  ok(goRow?.from === '1.27.0' && goRow.to === '1.28.0' && row.tools.length === 2
     && (st.attention || []).filter(a => a.id === en.id && a.kind === 'toolchain').length === 1,
     `...the same row as a store toolchain's update, one per node, Claude Code first (${JSON.stringify(row?.tools)})`);
  // The row's link opens the node's Toolchains tab, where each is updated
  // (the operator, 9 Oct), from whichever node that tab was on.
  await page.waitForFunction(id => (state?.attention || []).some(a => a.kind === 'toolchain' && a.id === id), en.id, { timeout: 15000 });
  await page.evaluate(() => { tcNode = 'local'; });
  await page.click('#bBell');
  await page.waitForSelector(`#bellPanel [data-btc="${en.id}"]`, { timeout: 10000 });
  const tcBell = await page.$eval(`#bellPanel [data-btc="${en.id}"]`, a => a.closest('.bnote').textContent.replace(/\s+/g, ' '));
  ok(/toolchain updates available/.test(tcBell) && /on clbox: Claude Code 1\.0\.0 → 1\.2\.0, Go 1\.27\.0 → 1\.28\.0/.test(tcBell),
     `the bell says it in words, every toolchain behind on the node in one row (${tcBell.slice(0, 160)})`);
  await page.click(`#bellPanel [data-btc="${en.id}"]`);
  await page.waitForFunction(id => tcNode === id && document.getElementById('bellPanel').hidden, en.id, { timeout: 15000 });
  await page.waitForSelector('#tcClaudeTick', { timeout: 30000 });
  ok(true, '...and its link opens the Toolchains tab on that node, Claude Code\'s row there');
  ok(st.claude_code?.nodes?.[en.id]?.behind === true && st.claude_code.latest === '1.2.0',
     '...and the status payload says which node is behind');
  await page.evaluate(() => openNodesTab());
  await page.waitForSelector('.nodestab #ndPick', { timeout: 15000 });
  await pickNode(page, en.id);
  const ROWC = `.nodestab .ndrow[data-node="${en.id}"]`;
  await page.waitForFunction(sel => /1\.0\.0, 1\.2\.0 is out/.test(document.querySelector(sel)?.textContent || ''), ROWC, { timeout: 15000 });
  ok(!await page.$(`${ROWC} [data-nd="claude-update"]`) && !!await page.$(`${ROWC} [data-ndtc="${en.id}"]`),
     'the Nodes tab says the version against the latest and points at the Toolchains tab, with no update of its own');
  await page.evaluate(id => openToolchainsOn(id), en.id);
  await page.waitForSelector('#tcClaudeTick', { timeout: 15000 });
  const tcRowText = await page.$eval('#tcClaudeTick', i => i.closest('.tc').textContent.replace(/\s+/g, ' '));
  ok(/Claude Code/.test(tcRowText) && /1\.0\.0/.test(tcRowText) && /update available: 1\.2\.0/.test(tcRowText)
     && await page.$eval('#tcClaudeTick', i => !i.disabled),
     `the node's Toolchains tab has a Claude Code row: its version, the update out, and a tick to install it (${tcRowText.slice(0, 120)})`);
  await page.evaluate(() => openNodesTab());
  // A session's token gets nowhere near it.
  const tok = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys
sys.path.insert(0, ${JSON.stringify(new globalThis.URL('..', import.meta.url).pathname)})
spec = importlib.util.spec_from_file_location('u', ${JSON.stringify(new globalThis.URL('../users.py', import.meta.url).pathname)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
def wj(path, d):
    tmp = str(path) + '.new'
    with open(tmp, 'w') as f: json.dump(d, f, indent=2)
    os.replace(tmp, path)
m.configure(state=${JSON.stringify(`${DIR}/state`)}, write_json=wj)
print(m.mint_session('alpha'))
`], { encoding: 'utf8' }).trim();
  const asSession = await fetch(base + '/api/toolchains', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
    body: JSON.stringify({ action: 'install', node: en.id, names: ['claude-code'] }) });
  ok(asSession.status === 403, `a session's token cannot ask for the update (${asSession.status})`);
  // The update: the node's project is bound, a Claude session is reported
  // there, and the press ends it, queues the job and holds the row.
  await napi('/api/prefs', { project: 'beta', node: en.id });
  await fetch(base + '/api/v1/agent/work', { method: 'POST',
    headers: { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' },
    // Named the way bb-tty names it on a node: every account is prefixed
    // there, the owner included; an unprefixed name is nobody's and dropped.
    body: JSON.stringify({ sample: { cpu_pct: 1, mem_mb: 4096, mem_used_mb: 512,
      sessions: [{ name: `${JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid}~claude-beta` }] }, running: [], wait: 0 }) });
  const up = await napi('/api/toolchains', { action: 'install', node: en.id, names: ['claude-code'] });
  const job = up.job ? await napi(`/api/v1/jobs?id=${up.job}`) : null;
  ok(up.ok && job?.type === 'claude-update' && job.node === en.id && job.spec?.to === '1.2.0' && (up.ended || []).length === 1,
     `Update ends the Claude session there and queues the job naming the version (${up.job || up.error}; ended ${JSON.stringify(up.ended)})`);
  const held = (await napi('/api/status')).projects.find(p => p.name === 'beta')?.held || '';
  ok(/Claude Code is updating on clbox/.test(held), `...and the node's project is held with the reason while it runs (${held.slice(0, 60)})`);
  // ...from the press, not from the job: ending the sessions comes first,
  // a round trip each, and the hold used to read nothing until the job
  // existed, so a Claude button pressed in those seconds started a
  // session the update was about to end (the operator, 29 Sep).
  {
    const said = execFileSync('python3', ['-c', `
import sys, json
sys.path.insert(0, ${JSON.stringify(REPO + '/scripts/dashboard')})
import claudecode as m
seen = []
class N:
    def node(self, i): return {"id": i, "name": "clbox", "kind": "agent", "live": True, "reported": {"session": {"up": True}}}
    def jobs_for(self, *a, **k): return []
    def session_kill(self, nid, name):
        seen.append(m.updating(nid)); return {"ok": True}
    def job_add(self, who, sel, typ, spec): return {"ok": True, "job": "j_1"}
m.configure(nodes_module=N(), node_sessions=lambda: [{"node_id": "n1", "name": "u_1~claude-beta"}], tmux_base=lambda s: s.split("~")[-1])
m._latest["version"] = "1.2.0"
r = m.update("test", "n1")
print(json.dumps({"held_while_ending": seen, "after": m.updating("n1"), "ok": r.get("ok")}))
`], { encoding: 'utf8' }).trim();
    const r = JSON.parse(said);
    ok(r.ok && r.held_while_ending.length === 1 && r.held_while_ending[0] === true && r.after === false,
       `the hold is up from the press, while the node's sessions are being ended, and is the job's alone once it is queued (${said})`);
  }
  ok(!claudeIn(await napi('/api/status')),
     '...and Claude Code leaves the bell row while the update is queued');
  const again = await napi('/api/toolchains', { action: 'install', node: en.id, names: ['claude-code'] });
  ok(/already queued/.test(again.error || ''), '...and a second press is refused while one is queued');
  // The fake agent takes the job and finishes it the way the real one does,
  // naming what it installed on its last line. The row and the bell read
  // the new version from that line at once: the census only rides hello,
  // every ten minutes, and the bell kept saying an update was out for that
  // long after it had landed (B249).
  {
    const AH = { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' };
    const work = await fetch(base + '/api/v1/agent/work', { method: 'POST', headers: AH,
      body: JSON.stringify({ running: [], wait: 0 }) });
    const got = work.status === 200 ? await work.json() : {};
    ok((got.job?.id || got.id) === up.job, `the agent is handed the update job (${work.status})`);
    await napi('/api/v1/agent/log', { job: up.job, chunks: [
      { seq: 1, chunk: 'installing Claude Code for bb (1.2.0 is out)\n' },
      { seq: 2, chunk: 'Claude Code 1.2.0 is what a session here runs now\n' }] }, AH);
    await napi('/api/v1/agent/result', { job: up.job, state: 'succeeded', exit: 0 }, AH);
  }
  await sleep(300);
  ok(!(await napi('/api/status')).projects.find(p => p.name === 'beta')?.held, 'the hold lifts when the job ends');
  {
    const cc = (await napi('/api/status')).claude_code?.nodes?.[en.id] || {};
    ok(cc.installed === '1.2.0' && cc.behind === false,
       `...and the row says the version the job installed before the next hello (${cc.installed}, behind ${cc.behind})`);
    ok(!claudeIn(await napi('/api/status')),
       '...so the bell does not keep saying an update is out');
  }
  // Behind again, by the node's own word: a session asked for there starts
  // on what it has, since nothing updates it but Update (the switch that
  // updated it first went on 7 Oct, the operator's).
  await hello();
  ok(!(await napi('/api/status')).settings?.settings?.claude_autoupdate,
     'no setting updates Claude Code before a session starts');
  // Up to date reads as such.
  census.session.claude = '1.2.0 (Claude Code)';
  await hello();
  ok((await napi('/api/status')).claude_code?.nodes?.[en.id]?.behind === false, 'a node on the latest is not behind');
  // None at all: the provisioner no longer installs it, and a session needs
  // it, so the node's projects are held saying where it is installed (R145).
  census.session.claude = '';
  await hello();
  const none = (await napi('/api/status')).projects.find(p => p.name === 'beta')?.held || '';
  ok(/Claude Code is not installed on clbox: its Toolchains tab installs it/.test(none),
     `a node with no Claude Code holds its projects' Claude button, saying where to install it (${none.slice(0, 80)})`);
  await napi('/api/prefs', { project: 'beta', node: '' });
  await napi('/api/v1/nodes', { action: 'retire', id: en.id });
}

// A probe's end never moves the job revisions, however the race with its
// waiter falls. run_wait forgets a probe the moment it sees the end, which
// takes it off the probe list; job_result asked whether the job was quiet
// only after its housekeeping, so the waiter usually won and every probe
// bumped the state revision. The Docker tab refetches on it and its read is
// a probe: a refresh every second or two for as long as it was open (24 Sep).
// Forced here by forgetting the job inside that housekeeping, which is the
// losing order, deterministically.
{
  const out = execFileSync('python3', ['-c', `
import importlib.util, json, sys, time
spec = importlib.util.spec_from_file_location("nodes", "${REPO}/scripts/dashboard/nodes.py")
m = importlib.util.module_from_spec(spec); sys.modules["nodes"] = m; spec.loader.exec_module(m)
m.configure(state="${DIR}/state")
jid, now = "j_quietprobe", int(time.time())
m._exec("INSERT INTO jobs (id, type, project, requested_by, placement, source, spec, outputs,"
        " state, node, exit_code, queued, started) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (jid, "exec", "", "dashboard", json.dumps({"node": "n_quiet"}), "{}",
         json.dumps({"argv": ["true"], "probe": True}), "[]", "running", "n_quiet", None, now, now))
m._probe_ids.add(jid)
before = m.jobs_state_rev()
real = m.prune_job_logs
def racing(*a, **k):
    m.job_forget(jid)          # the waiter saw the end and let the job go
    return real(*a, **k)
m.prune_job_logs = racing
r = m.job_result("n_quiet", jid, "succeeded", 0)
print(json.dumps({"ok": bool(r.get("ok")), "moved": m.jobs_state_rev() - before}))
`], { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  const got = JSON.parse(out.trim().split('\n').pop());
  ok(got.ok && got.moved === 0,
     `a probe's result leaves the job revisions still even when its waiter forgets it first (${JSON.stringify(got)})`);
}

// A node un-enrolled under a project (the operator, 5 Oct): the project's
// Claude button goes dead with the reason on its row, its settings keep
// the node selected as "name (removed)" in italics, and another project's
// picker does not offer it at all.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const base = URL.replace(/\/$/, '');
  const napi = async (path, body) => (await fetch(base + path, { method: 'POST', headers: H, body: JSON.stringify(body) })).json();
  const gone = await napi('/api/v1/nodes', { action: 'enroll', name: 'oldbox' });
  const was = (await (await fetch(`${base}/api/status`, { headers: H })).json()).projects.find(p => p.name === 'delta')?.prefs?.node || '';
  await napi('/api/prefs', { project: 'delta', node: gone.id });
  await napi('/api/v1/nodes', { action: 'retire', id: gone.id });
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => (state?.projects || []).find(p => p.name === 'delta')?.node_removed, null, { timeout: 15000 });
  const row = await page.evaluate(() => {
    const p = state.projects.find(x => x.name === 'delta');
    const r = document.querySelector('#projects .row[data-name="delta"], #projects [data-p="delta"]')?.closest('.row');
    return { why: p.session_why, line: r?.querySelector('.sessline')?.textContent || '', name: p.node_name,
             off: !!document.querySelector('#projects [data-c="delta"]')?.disabled };
  });
  ok(row.name === 'oldbox' && /oldbox was removed from the Nodes tab/.test(row.why || '') && row.off
     && !/coming back/.test(row.why || ''),
     `a project on an un-enrolled node keeps its name and says why Claude is off (${(row.why || '').slice(0, 70)}; row: ${row.line})`);
  const pick = async name => page.evaluate(async n => {
    openProjectSettings(n);
    for (let i = 0; i < 60 && !document.querySelector('#rnNode option'); i++) await new Promise(r => setTimeout(r, 100));
    await new Promise(r => setTimeout(r, 400));
    const s = document.getElementById('rnNode');
    return { value: s.value, cls: s.className, italic: getComputedStyle(s).fontStyle,
             opts: [...s.options].map(o => o.textContent.trim().slice(0, 40)) };
  }, name);
  const mine = await pick('delta');
  ok(mine.value === gone.id && mine.opts.includes('oldbox (removed)') && mine.italic === 'italic',
     `its settings keep the node selected, as "oldbox (removed)" in italics (${JSON.stringify(mine)})`);
  await page.keyboard.press('Escape');
  const theirs = await pick('alpha');
  ok(!theirs.opts.some(o => /oldbox/.test(o)), `another project's picker does not offer it (${JSON.stringify(theirs.opts)})`);
  await page.keyboard.press('Escape');
  await napi('/api/prefs', { project: 'delta', node: was });
}

await done(browser);
