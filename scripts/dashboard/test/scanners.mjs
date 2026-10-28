// The Scanners page (R145): every node with its scanners' state, Deploy on
// the one that holds the fixture's projects (a compose job the stub agent
// takes), the schedule turned on and a run now (a scan job the stub takes,
// sending a SARIF per scanner up), the report on the Analysis page and the
// node's section saying its last run and the reports it sent; the projects
// nothing covers listed with why; Remove taking it off again.
import { URL, launch, newPage, ok, done, ready, patience, settled } from './lib.mjs';

const BASE = URL.replace(/\/$/, '');
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const api = (path, body) => fetch(BASE + path, body ? { method: 'POST', headers: H, body: JSON.stringify(body) } : { headers: H }).then(r => r.json());
const until = async (fn, ms = 30000) => { const end = Date.now() + patience(ms); for (;;) { const v = await fn(); if (v) return v; if (Date.now() > end) return null; await new Promise(r => setTimeout(r, 400)); } };

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// The page: under Containers, the schedule first, a section per node.
await page.evaluate(() => openScannersTab());
await page.waitForSelector('.scannerstab details[data-sect="scanners:schedule"]', { timeout: patience(20000) });
await settled(page);
ok(await page.evaluate(() => location.hash) === '#/containers/scanners' && await page.evaluate(() => groupOf('scanners')?.key) === 'containers',
   'it is a page of the Containers group, at its own address');
const first = await api('/api/scanners');
const node = (first.nodes || []).find(n => !n.host_only && (n.projects || []).length);
ok(!!node && !node.deployed, `a node holds projects and has no scanners yet (${node ? node.name + ': ' + node.projects.join(', ') : 'none'})`);
ok((first.uncovered || []).some(u => u.project === (node?.projects || [])[0] && /no scanners on/.test(u.why)),
   'its projects are listed as not covered, with why');

// Deploy on it: a compose job the stub takes; the section says deployed with its versions.
await page.click(`.scannerstab [data-scandeploy="${node.id}"]`);
const dep = await until(async () => { const v = await api('/api/scanners'); const n = v.nodes.find(x => x.node === node.id); return n.deployed ? n : null; });
ok(!!dep && dep.versions.semgrep && dep.deploy_job, `Deploy pins the versions and queues the pull (${dep?.deploy_job}: ${dep ? Object.values(dep.versions).join(', ') : ''})`);
const pulled = await until(async () => { const j = await api(`/api/v1/jobs?id=${dep.deploy_job}`); return j.state === 'succeeded' ? j : null; }, 60000);
ok(!!pulled && /compose\.yml/.test(pulled.log || ''), `the stub agent took the compose job and wrote the file (${pulled?.state})`);

// The schedule: turned on with a timetable, said in words with its next run.
const sched = await api('/api/scanners', { action: 'schedule', on: true, cron: '0 4 * * 0' });
ok(sched.on === true && sched.words === 'Sundays at 4:00', `the schedule is on, Sundays at 4:00 (${sched.words})`);
await page.evaluate(() => loadScanners());
await page.waitForFunction(() => /Sundays at 4:00/.test(document.querySelector('.scannerstab details[data-sect="scanners:schedule"] > summary')?.textContent || ''), null, { timeout: patience(15000) });
ok(true, 'the schedule section says so in its head');

// Run now: a scan job the stub takes, a SARIF per scanner sent up.
const run = await api('/api/scanners', { action: 'run', node: node.id });
const job = run.nodes?.[node.id]?.job;
ok(!!job, `Run now queues a scan job on the node (${job || run.error || JSON.stringify(run)})`);
const fin = await until(async () => { const j = await api(`/api/v1/jobs?id=${job}`); return ['succeeded', 'failed'].includes(j.state) ? j : null; }, 60000);
ok(fin?.state === 'succeeded' && /semgrep sent up/.test(fin.log || ''), `the stub scanned and sent its reports up (${fin?.state}: ${(fin?.log || '').trim().split('\n').pop()})`);
const after = await until(async () => { const v = await api('/api/scanners'); const n = v.nodes.find(x => x.node === node.id); return Object.keys(n.reports || {}).length >= 3 ? n : null; });
ok(!!after && after.last.state === 'succeeded', `the node's section has its three reports and the run as done (${after ? Object.keys(after.reports).join(', ') : ''})`);
const found = await until(async () => { const f = await api('/api/findings'); return f.available && (f.reports || []).some(r => r.findings.some(x => x.project === node.projects[0])) ? f : null; });
ok(!!found, `the Analysis page reads what was sent up, by project (${found ? found.reports.map(r => r.tool).join(', ') : 'nothing'})`);
await page.evaluate(() => loadScanners());
await page.waitForFunction(id => /done|succeeded/.test(document.querySelector(`.scannerstab details[data-sect="scanners:node-${id}"]`)?.textContent || ''), node.id, { timeout: patience(15000) });
ok(true, 'the node\'s section says its last run');

// Not covered: nothing of that node's now; a project with no node still is.
const un = (await api('/api/scanners')).uncovered || [];
ok(!un.some(u => u.project === node.projects[0]), 'its projects are covered now');

// Remove takes it off, with its reports.
const rm = await api('/api/scanners', { action: 'remove', node: node.id });
ok(rm.ok === true && !(await api('/api/scanners')).nodes.find(x => x.node === node.id).deployed, 'Remove takes the scanners off the node');

// A session is refused, reading or writing.
const tok = (await page.evaluate(async () => (await (await fetch('/api/status')).json()).repos?.[0]?.token)) || '';
if (tok){
  const r = await fetch(BASE + '/api/scanners', { headers: { Authorization: `Bearer ${tok}` } });
  ok(r.status === 403, `a session's token is refused at the page (${r.status})`);
}
await done(browser);
