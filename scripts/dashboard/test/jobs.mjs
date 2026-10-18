// Phase 4 of the controller design (docs/nodes.md): jobs and the queue. The
// rows ARE the queue; placement is a node or a selector, frozen when the job
// is taken; the controller's own runner executes on local and the agent on
// its node (it used to reach an ssh node from here, but that kind is gone);
// cancel is a flag on the row that the runner reads; and the Jobs tab is the
// operator's window on all of it. Every assertion here goes through the queue
// end to end (a job queued, placed, run, logged, ended), because the queue is
// what this phase exists to prove.
import { URL, launch, newPage, ok, done, ready, sleep, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const base = URL.replace(/\/$/, '');
const api = async (path, body) => {
  const r = await fetch(base + path, body === undefined
    ? { headers: auth }
    : { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' },
        body: JSON.stringify(body) });
  return r.status === 204 ? {} : r.json();
};
const OVER = ['succeeded', 'failed', 'canceled'];
const until = async (fn, ms = 20000, step = 200) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ const v = await fn(); if (v) return v; await sleep(step); }
  return null;
};
const job = id => api(`/api/v1/jobs?id=${id}`);
// The store outlives a suite within one run, so the tab can carry another
// suite's rows: an agent's, on a node with another name. The row checks
// below are about the jobs THIS file queued.
const mine = new Set();
const exec = async body => { const q = await api('/api/v1/nodes', { action: 'exec', ...body }); if (q.job) mine.add(q.job); return q; };
const settled = id => until(async () => { const j = await job(id); return OVER.includes(j.state) ? j : null; });

// ---- a job on the local node, run by the controller itself ----------------
{
  const q = await exec({ id: 'local',
    argv: ['sh', '-c', 'echo hi from $BUILDERBOT_NODE; echo err >&2; exit 0'] });
  ok(q.ok && /^j_/.test(q.job), `exec on local queues a job (${q.job})`);
  const j = await settled(q.job);
  ok(j && j.state === 'succeeded' && j.exit_code === 0 && j.node === 'local',
     `the controller runs it here and records the result (${j?.state}, exit ${j?.exit_code})`);
  ok(j && /hi from local/.test(j.log) && /err/.test(j.log),
     'stdout and stderr both reach the log, with the node id in the env');
  ok(j && j.started && j.ended && j.ended >= j.started && j.error === '',
     'a job that succeeded carries its timings and no error');
}

// ---- a failing one says why, in one line -----------------------------------
{
  const q = await exec({ id: 'local',
    argv: ['sh', '-c', 'echo about to fail; exit 7'] });
  const j = await settled(q.job);
  ok(j && j.state === 'failed' && j.exit_code === 7 && j.error === 'exit 7',
     `a non-zero exit is failed, with the code as the reason (${j?.error})`);
}

// ---- placement by selector: refused up front when nothing fits --------------
{
  const q = await exec({ argv: ['true'],
    select: { arch: 'riscv64' } });
  ok(q.error && /no node fits/.test(q.error) && /arch=riscv64/.test(q.error),
     `a selector nothing fits is refused at the queue, naming the selector (${q.error})`);
  const arch = execFileSync('uname', ['-m'], { encoding: 'utf8' }).trim();
  // The label as well as the arch, because the selector has to be one only
  // LOCAL answers. The harness's docker host is an enrolled agent node now
  // (roadmap #24) and it fits arch just as well, and its agent is
  // long-polling, so it takes an unplaced job before the controller's
  // watcher looks. That is placement working: a selector job is frozen to
  // whichever node takes it. `labels.arch` is on the controller's own seeded
  // row and on nothing else. No capability: local declares none since 10c.
  const q2 = await exec({ argv: ['sh', '-c', 'echo placed on $BUILDERBOT_NODE'],
    select: { arch, labels: { arch } } });
  ok(q2.ok, `a selector only local fits (arch=${arch}, label arch) is taken`);
  const j = await settled(q2.job);
  ok(j && j.state === 'succeeded' && j.node === 'local' && /placed on local/.test(j.log),
     `and the job is placed on local when it is taken, with the node written on the row (${
        j && j.node}, ${j && j.state})`);
  ok(j && j.placement && j.placement.select && j.placement.select.arch === arch,
     'the row keeps the selector it was placed by, not only the answer');
}

// ---- cancel: a running job is stopped, a queued one never starts ------------
{
  // local runs one at a time (concurrency 1): the second waits behind the first.
  const a = await exec({ id: 'local',
    argv: ['sh', '-c', 'echo started; sleep 60'] });
  const running = await until(async () => { const j = await job(a.job); return j.state === 'running' ? j : null; });
  ok(running !== null, 'a long job reaches running');
  const b = await exec({ id: 'local', argv: ['true'] });
  await sleep(600);
  const waiting = await job(b.job);
  ok(waiting.state === 'queued', 'a second job on the same node waits: concurrency is counted from the rows');
  const hz = await (await fetch(base + '/api/v1/healthz')).json();
  ok(hz.ok === true && hz.running >= 1 && hz.queued >= 1,
     `/api/v1/healthz answers without a credential and counts the queue (${JSON.stringify(hz)})`);

  const cb = await api('/api/v1/jobs', { action: 'cancel', id: b.job });
  const bj = await job(b.job);
  ok(cb.ok && bj.state === 'canceled' && /before it started/.test(bj.error),
     `canceling a queued job ends it at once (${bj.error})`);

  const ca = await api('/api/v1/jobs', { action: 'cancel', id: a.job });
  ok(ca.ok, 'canceling a running job is accepted');
  const aj = await settled(a.job);
  ok(aj && aj.state === 'canceled' && aj.ended && /started/.test(aj.log),
     `...and the row moves to canceled when the runner reports it stopped (${aj?.state})`);
  ok(aj && aj.ended - aj.started < 30,
     'the sleep was killed rather than waited out');
}

// ---- /metrics: authenticated, prometheus text --------------------------------
{
  const anon = await fetch(base + '/metrics');
  ok(anon.status === 401, '/metrics wants the dashboard credential');
  const r = await fetch(base + '/metrics', { headers: auth });
  const text = await r.text();
  ok(r.status === 200 && /^text\/plain/.test(r.headers.get('content-type'))
     && /builderbot_jobs\{state="succeeded"\} [1-9]/.test(text)
     && /builderbot_jobs\{state="canceled"\} [1-9]/.test(text)
     && /builderbot_nodes\{state="online"\}/.test(text),
     'it counts jobs by state and nodes by state, in the exposition format');
}

// ---- the list, and its filters ----------------------------------------------
{
  const all = await api('/api/v1/jobs?n=50');
  ok(all.jobs.length >= 5 && all.nodes.local === 'controller'
     && all.jobs.every((j, i) => i === 0 || j.queued <= all.jobs[i - 1].queued),
     'the list is newest first and names the nodes');
  const act = await api('/api/v1/jobs?active=1');
  ok(act.jobs.length === 0, '...and active=1 is empty once everything has ended');
}

// ---- the tab ----------------------------------------------------------------
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);
{
  await page.evaluate(() => { const c = document.getElementById('cardTools');
    if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
  await page.evaluate(() => openJobsTab());
  await page.waitForSelector('.jobstab .jbrow', { timeout: 15000 });
  // The tab at a glance (R216): tiles of what runs, waits, failed and
  // finished of the jobs listed.
  const jtiles = await page.$$eval('.jobstab .tiles .tile .tl', ls => ls.map(l => l.textContent.trim()));
  ok(jtiles.includes('running') && jtiles.includes('succeeded'),
     `the Jobs tab opens on tiles of what runs and what finished (${jtiles.join(', ')})`);
  const rows = (await page.$$eval('.jobstab .jbrow', rs => rs.map(r => ({
    id: r.dataset.job, state: r.dataset.state, text: r.textContent.replace(/\s+/g, ' '),
    node: r.querySelector('.td[data-th="Node"]')?.textContent.trim() }))))
    .filter(r => mine.has(r.id));
  ok(rows.length >= 5 && rows.some(r => r.state === 'canceled' && /before it started/.test(r.text))
     && rows.some(r => r.state === 'failed' && /exit 7/.test(r.text))
     && rows.every(r => r.node === 'controller'),
     `the Jobs tab lists them with their state, node and reason (${rows.length} rows)`);
  ok(rows.every(r => !/Cancel/.test(r.text)), 'an ended job offers no Cancel');

  // unfold a log: ONE THIS FILE QUEUED, by id, not the newest succeeded row.
  // `mine` is the set of job ids these tests submitted; the box runs other
  // jobs, and the newest succeeded row was once an `adb devices` probe whose
  // log says "List of devices attached" (B86). The probe is a forgotten job
  // now and lists nowhere, but a phone push or a build still can be newest.
  const ids = [...mine];
  let logRow = null;
  for (const id of ids){
    const b = await page.$(`.jobstab .jbrow[data-job="${id}"][data-state="succeeded"] > .jbopen > .td:nth-child(3)`);
    if (b){ logRow = { id, b }; break; }
  }
  ok(logRow, `a job this file queued is on the tab with a log to unfold (${ids.length} queued)`);
  await logRow.b.click();
  await page.waitForSelector(`.jobstab .jbrow[data-job="${logRow.id}"] .jblog`, { timeout: 10000 });
  const log = await page.$eval(`.jobstab .jbrow[data-job="${logRow.id}"] .jblog`, e => e.textContent);
  ok(/placed on local|hi from local/.test(log), `a press on the row unfolds what the job wrote (${log.trim().slice(0, 40)})`);
  // The row is what opens (rows-you-open, R218 step 25): no Log button, the
  // line says it is open, and Enter on it folds the log away again.
  const opened = await page.$eval(`.jobstab .jbrow[data-job="${logRow.id}"]`, r => ({
    btn: !!r.querySelector('[data-jb="log"]'), exp: r.querySelector('.jbopen').getAttribute('aria-expanded') }));
  await page.focus(`.jobstab .jbrow[data-job="${logRow.id}"] > .jbopen`);
  await page.keyboard.press('Enter');
  await page.waitForFunction(id => !document.querySelector(`.jobstab .jbrow[data-job="${id}"] .jblog`), logRow.id, { timeout: 10000 })
    .catch(() => {});
  const shut = await page.$(`.jobstab .jbrow[data-job="${logRow.id}"] .jblog`) === null;
  ok(!opened.btn && opened.exp === 'true' && shut,
     `...the row itself opens it, with no Log button, says it is open, and Enter folds it away (${JSON.stringify({ ...opened, shut })})`);
  // ...and on a FAILED row too: the job's own error sentence was read as a
  // failed request and its log kept out, so every failed job read "(this
  // job wrote nothing)" (B658, the operator, 11 Oct).
  let failRow = null;
  for (const id of ids){
    const b = await page.$(`.jobstab .jbrow[data-job="${id}"][data-state="failed"] > .jbopen > .td:nth-child(3)`);
    if (b){ failRow = { id, b }; break; }
  }
  ok(failRow, `a failed job this file queued is on the tab with a log to unfold`);
  if (failRow){
    await failRow.b.click();
    await page.waitForFunction(id => /about to fail/.test(document.querySelector(`.jobstab .jbrow[data-job="${id}"] .jblog`)?.textContent || ''),
                               failRow.id, { timeout: 10000 }).catch(() => {});
    const flog = await page.$eval(`.jobstab .jbrow[data-job="${failRow.id}"] .jblog`, e => e.textContent);
    ok(/about to fail/.test(flog), `a press on a failed row unfolds what it wrote, not "(this job wrote nothing)" (${flog.trim().slice(0, 40)})`);
  }

  // a running job from the tab: Cancel on the row
  const q = await exec({ id: 'local',
    argv: ['sh', '-c', 'echo tick; sleep 60'] });
  await page.waitForSelector(`.jobstab .jbrow[data-job="${q.job}"][data-state="running"] [data-jb="cancel"]`,
                             { timeout: 15000 });
  const bar = await page.$eval('.jobstab .docbarrow', e => e.textContent.replace(/\s+/g, ' '));
  ok(/1 not finished/.test(bar), `the bar counts what is not over (${bar.trim()})`);
  await page.click(`.jobstab .jbrow[data-job="${q.job}"] [data-jb="cancel"]`);
  await page.waitForSelector(`.jobstab .jbrow[data-job="${q.job}"][data-state="canceled"]`,
                             { timeout: 15000 });
  ok(true, 'Cancel on the row stops it, and the row follows the revision to canceled');

  // the filter
  await page.click('#jbActive');
  await page.waitForSelector('.jobstab .empty', { timeout: 10000 });
  const empty = await page.$eval('.jobstab .empty', e => e.textContent);
  ok(/nothing is running or waiting/.test(empty), 'the active-only filter says so when nothing is');
  await page.click('#jbActive');
  await page.waitForSelector('.jobstab .jbrow', { timeout: 10000 });
}

// bb jobs reads the same listing the tab does, through the API as the
// caller: an administrator sees every job, and a session its own project's
// and no other, by name or by id (B317: it read the store directly, which
// on the machine holding the controller's state showed a session every
// project's jobs).
{
  const admin = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_AUTH: 'test:test',
                  BB_CONTROLLER: base, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` };
  const bbj = (...a) => execFileSync('bash', ['scripts/bb', 'jobs', ...a], { encoding: 'utf8', cwd: REPO, env: admin });
  const out = bbj();
  ok(/canceled/.test(out) && /exit 7/.test(out) && /controller/.test(out) && /exec sh -c/.test(out),
     'bb jobs lists the recent jobs with state, node and reason');
  // ...and one job's LOG, which is the half that was missing: a failed job
  // with an exit code and nothing to read is not something anybody can act
  // on. The listing has never been per project (it reads the store, not the
  // API), and this is the same answer one level down.
  const id = (out.match(/\bj_[0-9a-f]{8}\b/) || [])[0];
  ok(!!id, `the listing names ids that can be asked about (${id || "none"})`);
  const one = bbj(id);
  ok(one.split('\n').filter(l => /\bj_[0-9a-f]{8}\b/.test(l)).length === 1,
     'bb jobs ID answers about that job alone, not the whole list');
  ok(/---- log|wrote nothing/.test(one),
     '...and prints what it wrote, or says plainly that it wrote nothing');
  let missing = '';
  try { bbj('j_deadbeef'); } catch (e) { missing = (e.stdout + '' + e.stderr).toString(); }
  ok(/no such job/.test(missing), '...and an id that is not there says so rather than listing everything');
  // As a session of alpha: its project's jobs only, and another project's
  // job by id is "no such job", the same answer a typo gets.
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  // One of beta's, so there is something to keep out of alpha's view.
  await exec({ id: 'local', project: 'beta', argv: ['true'] });
  const all = (await (await fetch(base + '/api/v1/jobs?n=100', { headers: H })).json()).jobs || [];
  const theirs = all.filter(j => j.project && j.project !== 'alpha').map(j => j.id);
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
  const sess = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: base, BB_TOKEN: tok, BB_PROJECT: 'alpha',
                 XDG_CACHE_HOME: `${DIR}/cache-jobs` };
  const bbs = (...a) => { try { return execFileSync('bash', [`${REPO}/scripts/bb`, 'jobs', ...a],
    { encoding: 'utf8', cwd: `${DIR}/ws/alpha`, env: sess, stdio: ['ignore', 'pipe', 'pipe'] }); }
    catch (e) { return (e.stdout || '') + (e.stderr || ''); } };
  const mineOut = bbs();
  ok(!theirs.some(id => mineOut.includes(id)) && (theirs.length ? /no such job/.test(bbs(theirs[0])) : true),
     `a session's bb jobs lists its own project's jobs and answers "no such job" for another project's (${
        theirs.length} of others' kept out; ${mineOut.trim().split('\n')[0].slice(0, 70)})`);
  // A container written for alpha (bb container new --for alpha) carries
  // its own name as its jobs' project, and those are alpha's to see (B321):
  // its record says whose it is. And -n counts what the session sees, not
  // the node's last n before the filter: three of beta's queued after
  // alpha's used to leave bb jobs -n 2 with nothing of alpha's.
  const { readFileSync: rf, writeFileSync: wf } = await import('node:fs');
  const store = `${DIR}/state/devapps.json`;
  let dev = {}; try { dev = JSON.parse(rf(store, 'utf8')); } catch {}
  dev['alpha-box'] = { main: { source: 'file', for: 'alpha', node: 'local' } };
  wf(store, JSON.stringify(dev));
  const box = await exec({ id: 'local', project: 'alpha-box', argv: ['true'] });
  const own = await exec({ id: 'local', project: 'alpha', argv: ['true'] });
  for (let i = 0; i < 3; i++) await exec({ id: 'local', project: 'beta', argv: ['true'] });
  await settled(box.job); await settled(own.job);
  const withBox = bbs();
  ok(withBox.includes(box.job) && /exec true/.test(withBox),
     `a session sees the jobs of a container written for its project (${box.job})`);
  ok(!/no such job/.test(bbs(box.job)), '...and reads one of those by id');
  const two = bbs('-n', '2').trim().split('\n').filter(l => /^\s*j_/.test(l));
  ok(two.length === 2 && two.some(l => l.includes(box.job)) && two.some(l => l.includes(own.job)),
     `bb jobs -n 2 is the session's own last two, whatever else the node ran since (${two.map(l => l.trim().slice(0, 12)).join(', ')})`);
}

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
