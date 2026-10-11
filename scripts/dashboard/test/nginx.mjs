#!/usr/bin/env node
// The nginx tab (R171): one reverse proxy per node, BuilderBot's own. A
// section per node with its routes and certificate; Save keeps them, Deploy
// writes the container from them on the node and builds it, Remove takes it
// off; and the Enroll dialog's tick puts nginx on a node the moment it
// enrolls. The harness's sandbox node is the node, and its stub docker reads
// the generated compose file the way a daemon would.
import { URL, launch, newPage, ok, done, ready, DIR } from './lib.mjs';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
// Poll fn until it answers something other than null, or give up.
const until = async (fn, ms = 15000, step = 200) => {
  const end = Date.now() + ms;
  while (Date.now() < end){ const v = await fn(); if (v !== null && v !== undefined) return v; await new Promise(r => setTimeout(r, step)); }
  return null;
};

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const base = URL.replace(/\/$/, '');
const api = async (path, body) => (await fetch(base + path, body === undefined
  ? { headers: H } : { method: 'POST', headers: H, body: JSON.stringify(body) })).json();

// The button, on the Tools card for an account that reads the Nodes tab.
ok(await page.$eval('#bNginx', b => !b.hidden && /nginx/.test(b.textContent)), 'the Tools card offers nginx');
await page.click('#bNginx');
await page.waitForSelector('.nginxtab [data-ngnode]', { timeout: 15000 });
const sandbox = await page.evaluate(() => (nginxList || []).find(n => n.name === 'sandbox'));
ok(sandbox && !sandbox.deployed && sandbox.routes.length === 0 && !sandbox.cert.set,
   `the tab lists the sandbox node with no nginx on it yet (${JSON.stringify(sandbox && [sandbox.deployed, sandbox.routes])})`);
// One node at a time, picked in the bar like Toolchains (the operator, 11 Oct).
ok(await page.$eval('.nginxtab .docbarrow label.pick select#ngNodeSel', s => [...s.options].some(o => o.textContent === 'sandbox')),
   'the bar picks the node, as Toolchains does');
await page.selectOption('.nginxtab #ngNodeSel', sandbox.node);
const sect = `.nginxtab [data-ngnode="${sandbox.node}"]`;
await page.waitForSelector(sect, { timeout: 10000 });
ok(await page.$eval(sect, s => /not deployed/.test(s.querySelector('.toolstate .pill').textContent)
     && s.querySelector('[data-ngdeploy]') && !s.querySelector('[data-ngremove]')
     && s.querySelector('[data-ngsave]').disabled),
   '...its state row says so, with Deploy and a dead Save');

// A route typed: Save wakes, and Save keeps it (not deployed yet, so nothing
// is built).
await page.click(`${sect} [data-ngadd]`);
await page.waitForSelector(`${sect} .ngroute`, { timeout: 5000 });
await page.fill(`${sect} .ngroute [data-ng="host"]`, 'www.example.com');
await page.fill(`${sect} .ngroute [data-ng="port"]`, '8080');
ok(await page.$eval(`${sect} [data-ngsave]`, b => !b.disabled), 'a route typed wakes the section\'s Save');
await page.click(`${sect} [data-ngsave]`);
await page.waitForFunction(id => (nginxList || []).find(n => n.node === id)?.routes?.length === 1, sandbox.node, { timeout: 15000 });
const saved = await api('/api/nginx');
const row = saved.nodes.find(n => n.node === sandbox.node);
ok(row.routes.length === 1 && row.routes[0].host === 'www.example.com' && row.routes[0].port === 8080 && row.routes[0].tls === true
   && !row.deployed,
   `...and Save keeps the route on the controller, with nothing deployed yet (${JSON.stringify(row.routes)})`);
ok(/a port on the node/.test((await api('/api/nginx', { action: 'save', node: sandbox.node, routes: [{ host: 'x.example.com', port: 'eighty' }] })).error || ''),
   'a route with no port is refused by name');
ok(/PEM/.test((await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes, cert: 'not a cert', key: 'nor a key' })).error || ''),
   '...and a certificate that is not one');

// A certificate per hostname (R175): one made here with openssl, saved for
// one of the routes' hostnames, listed beside the default, in the compose
// file under that hostname's path.
{
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=www.example.com',
    '-addext', 'subjectAltName=DNS:www.example.com', '-keyout', `${DIR}/ngx-k.pem`, '-out', `${DIR}/ngx-c.pem`], { stdio: 'ignore' });
  const cert = readFileSync(`${DIR}/ngx-c.pem`, 'utf8'), key = readFileSync(`${DIR}/ngx-k.pem`, 'utf8');
  const own = await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes, cert_for: 'www.example.com', cert, key });
  const v = (await api('/api/nginx')).nodes.find(n => n.node === sandbox.node);
  ok(own.ok && v.certs?.['www.example.com']?.set && v.certs['www.example.com'].subject === 'www.example.com' && !v.cert?.set,
     `a certificate saved for one hostname is that hostname's own, with the default still none (${JSON.stringify(v.certs)})`);
  await page.evaluate(() => loadNginx());
  await page.waitForFunction(id => /www\.example\.com: www\.example\.com/.test(document.querySelector(`.nginxtab [data-ngnode="${id}"]`)?.textContent || ''), sandbox.node, { timeout: 10000 });
  ok(await page.$eval(sect, s => /Default: none/.test(s.textContent) && [...s.querySelectorAll('[data-ng="certfor"] option')].some(o => o.value === 'www.example.com')),
     '...and the section lists it under the default and offers the hostname in the picker');
  await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes, cert_for: 'www.example.com', drop_cert: true });
  ok(!((await api('/api/nginx')).nodes.find(n => n.node === sandbox.node).certs?.['www.example.com']), '...and it can be taken off again');
}

// Deploy: the container is written from the routes and built on the node.
await page.click(`${sect} [data-ngdeploy]`);
await page.waitForFunction(id => (nginxList || []).find(n => n.node === id)?.deployed, sandbox.node, { timeout: 20000 });
const rec = JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'))['nginx-sandbox'];
const written = await api('/api/container', { action: 'read', name: 'nginx-sandbox' });
ok(rec?.main?.source === 'file' && rec.main.node === sandbox.node && rec.main.for === 'System'
   && /network_mode: host/.test(written.compose || '') && /www\.example\.com/.test(written.compose || '')
   && /proxy_pass http:\/\/127\.0\.0\.1:8080/.test(written.compose || ''),
   `Deploy writes nginx-sandbox on the node as System's, BuilderBot's own (R180), its compose carrying the config inline (${JSON.stringify(rec?.main).slice(0, 80)})`);
// System is the deployment's to set and nobody's to pick: the owner verb
// refuses the word however it is asked.
const sysPick = await api('/api/dockerctl', { action: 'owner', container: 'nginx-sandbox', owner: 'System', node: sandbox.node });
ok(/no project called System|BuilderBot's own/.test(sysPick.error || ''),
   `...and no picker puts a container under System (${(sysPick.error || 'allowed').slice(0, 60)})`);
// The section is drawn after the answer lands, so its Remove is waited
// for rather than read the moment the list moved.
await page.waitForSelector(`${sect} [data-ngremove]`, { timeout: 15000 });
ok(await page.$eval(sect, s => /deployed/.test(s.querySelector('.toolstate .pill').textContent) && /1 route/.test(s.querySelector('.toolstate .sub').textContent)
     && s.querySelector('[data-ngremove]') && !s.querySelector('[data-ngdeploy]')),
   '...and the state row now says so, with Remove in place of Deploy');
ok(/already on the Docker tab/.test((await api('/api/nginx', { action: 'deploy', node: sandbox.node })).error || ''),
   'a second Deploy is refused');

// Save on a deployed one rewrites the file and rebuilds.
const two = await api('/api/nginx', { action: 'save', node: sandbox.node,
  routes: [...row.routes, { host: 'www.example.com', path: '/relay', port: 8788, tls: false }] });
const again = await api('/api/container', { action: 'read', name: 'nginx-sandbox' });
ok(two.ok && two.deployed && /location \/relay\/ \{ proxy_pass http:\/\/127\.0\.0\.1:8788; \}/.test(again.compose || ''),
   `Save on a deployed nginx rewrites its compose file and rebuilds (${JSON.stringify(two).slice(0, 80)})`);

// Remove: the container goes, the routes stay for a redeploy.
await page.click(`${sect} [data-ngremove]`);
// A node read as quiet queues the down and keeps the row until it has
// run (B597), which under a whole gate is a while: the record's going is
// waited for, not read at once.
let after = null, gone = false, queued = false;
for (let i = 0; i < 60; i++){
  after = (await api('/api/nginx')).nodes.find(n => n.node === sandbox.node);
  gone = !('nginx-sandbox' in JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8')));
  // On a node read as quiet the down is queued and the row kept until it has
  // run (B597): that job in the queue is the remove having happened here.
  queued = ((await api('/api/v1/jobs?active=1')).jobs || []).some(j => j.type === 'compose' && j.project === 'nginx-sandbox' && j.spec?.action === 'remove');
  if (!after.deployed && (gone || queued)) break;
  await new Promise(r => setTimeout(r, 1000));
}
ok(!after.deployed && after.routes.length === 2 && (gone || queued),
   `Remove takes the container off the Docker tab, or queues its down on a quiet node, and keeps the routes here (${JSON.stringify([after.deployed, after.routes.length, gone, queued])})`);
// The Save's rebuild (two.job) may land after the Remove forgot the row:
// its result must not stamp a record back into being (B633).
await until(async () => ['succeeded', 'failed', 'canceled'].includes((await api(`/api/v1/jobs?id=${two.job}`)).state) ? true : null, 60000, 500);
const ghost = JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'))['nginx-sandbox'];
ok(!ghost || !!(await api('/api/v1/jobs?active=1')).jobs?.some(j => j.project === 'nginx-sandbox'),
   `...and the rebuild landing afterwards does not bring the row back as a ghost (${JSON.stringify(ghost || null)})`);

// The Enroll dialog's tick: a node enrolled with it gets nginx on its first
// hello, with the routes saved for it beforehand.
await page.evaluate(() => openNodesTab());
await page.waitForSelector('.nodestab #ndEnroll', { timeout: 15000 });
await page.click('.nodestab #ndEnroll');
await page.waitForSelector('#ndBody #ndEnNginx', { timeout: 10000 });
await page.fill('#ndBody #ndEnName', 'vpsbox');
await page.check('#ndBody #ndEnNginx');
ok(!(await page.$eval('#ndBody #ndEnNginxHint', e => e.hidden)), 'the Enroll dialog offers nginx on the new node, saying what it means');
await page.click('#ndBody #ndEnTok');
await page.waitForSelector('#ndBody .ndcmd', { timeout: 10000 });
const pending = await page.evaluate(async () => { await loadNodes(); return nodesList.find(n => n.name === 'vpsbox'); });
ok(pending?.config?.nginx === true, `...and the pending row carries the ask (${JSON.stringify(pending?.config)})`);
const tokenLine = await page.$eval('#ndBody .ndcmd', e => e.textContent);
const token = (tokenLine.match(/bbe_[A-Za-z0-9_-]+/) || [])[0];
await api('/api/nginx', { action: 'save', node: pending.id, routes: [{ host: '*', path: '/', port: 3000 }] });
const shipped = (await api('/api/v1/nodes')).agent || {};
const en = await (await fetch(base + '/api/v1/agent/enroll', { method: 'POST',
  headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
  body: JSON.stringify({ census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', docker: '27.0' },
                         version: shipped.version, digest: shipped.digest, user: 'bb' }) })).json();
const vps = JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'))['nginx-vpsbox'];
ok(en.ok && vps?.main?.node === pending.id && vps.main.source === 'file',
   `...and the node enrolling puts nginx on it from the routes saved for it (${JSON.stringify(vps?.main).slice(0, 80)})`);
await api('/api/nginx', { action: 'remove', node: pending.id });
await api('/api/v1/nodes', { action: 'retire', id: pending.id });

await done(browser);
