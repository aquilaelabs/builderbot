// Phase 4 of the controller design (docs/nodes.md): jobs and the queue. The
// rows ARE the queue; placement is a node or a selector, frozen when the job
// is taken; the controller's own runner executes on local and over ssh, the
// agent on its node; cancel is a flag on the row that the runner reads; and
// the Jobs tab is the operator's window on all of it. Every assertion here
// goes through the queue end to end — a job queued, placed, run, logged,
// ended — because the queue is what this phase exists to prove.
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
// suite's rows — an agent's, on a node with another name. The row checks
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
  const q2 = await exec({ argv: ['sh', '-c', 'echo placed on $BUILDERBOT_NODE'],
    select: { arch, capability: 'package-build' } });
  ok(q2.ok, `a selector local fits (arch=${arch}, package-build) is taken`);
  const j = await settled(q2.job);
  ok(j && j.state === 'succeeded' && j.node === 'local' && /placed on local/.test(j.log),
     'and the job is placed on local when it is taken — the node written on the row');
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
  ok(waiting.state === 'queued', 'a second job on the same node waits — concurrency is counted from the rows');
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
  await page.click('#bJobs');
  await page.waitForSelector('.jobstab .jbrow', { timeout: 15000 });
  const rows = (await page.$$eval('.jobstab .jbrow', rs => rs.map(r => ({
    id: r.dataset.job, state: r.dataset.state, text: r.textContent.replace(/\s+/g, ' ') }))))
    .filter(r => mine.has(r.id));
  ok(rows.length >= 5 && rows.some(r => r.state === 'canceled' && /before it started/.test(r.text))
     && rows.some(r => r.state === 'failed' && /exit 7/.test(r.text))
     && rows.every(r => /on controller/.test(r.text)),
     `the Jobs tab lists them with their state, node and reason (${rows.length} rows)`);
  ok(rows.every(r => !/Cancel/.test(r.text)), 'an ended job offers no Cancel');

  // unfold a log
  const first = await page.$('.jobstab .jbrow[data-state="succeeded"] [data-jb="log"]');
  await first.click();
  await page.waitForSelector('.jobstab .jbrow .jblog', { timeout: 10000 });
  const log = await page.$eval('.jobstab .jbrow .jblog', e => e.textContent);
  ok(/placed on local|hi from local/.test(log), `Log unfolds what the job wrote (${log.trim().slice(0, 40)})`);

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

// bb jobs reads the same store
{
  const out = execFileSync('bash', ['scripts/bb', 'jobs'],
    { encoding: 'utf8', cwd: REPO, env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  ok(/canceled/.test(out) && /exit 7/.test(out) && /controller/.test(out) && /exec sh -c/.test(out),
     'bb jobs lists the recent jobs with state, node and reason');
}

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
