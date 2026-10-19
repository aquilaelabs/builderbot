#!/usr/bin/env node
// The nginx tab (R171): one reverse proxy per node, BuilderBot's own. A
// section per node with its routes and certificate; Save keeps them, Deploy
// writes the container from them on the node and builds it, Remove takes it
// off; and the Enroll dialog's tick puts nginx on a node the moment it
// enrolls. The harness's sandbox node is the node, and its stub docker reads
// the generated compose file the way a daemon would.
import { URL, launch, newPage, ok, done, ready, DIR } from './lib.mjs';
import { readFileSync, writeFileSync } from 'node:fs';
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

// A tab of its own under Containers on the rail, beside the containers
// (the operator, 18 Oct), for an account that reads the Nodes tab.
ok(await page.evaluate(() => railGroups().some(g => g.key === 'containers' && g.tools.map(([k]) => k).join() === 'docker,nginx')
                              && !railGroups().some(g => g.key === 'machines' && g.tools.some(([k]) => k === 'nginx')) && railAllows('nginx')),
   'the rail offers nginx under Containers, beside the containers, and not under Machines');
await page.evaluate(() => openNginxTab());
await page.waitForSelector('.nginxtab [data-ngnode]', { timeout: 15000 });
const sandbox = await page.evaluate(() => (nginxList || []).find(n => n.name === 'sandbox'));
ok(sandbox && !sandbox.deployed && sandbox.routes.length === 0 && !Object.keys(sandbox.certs || {}).length,
   `the tab lists the sandbox node with no nginx on it yet (${JSON.stringify(sandbox && [sandbox.deployed, sandbox.routes])})`);
// One node at a time, picked in the bar like Toolchains (the operator, 11 Oct).
ok(await page.$eval('.nginxtab .docbarrow label.pick select#ngNodeSel', s => [...s.options].some(o => o.textContent === 'sandbox')),
   'the bar picks the node, as Toolchains does');
await page.selectOption('.nginxtab #ngNodeSel', sandbox.node);
const sect = `.nginxtab [data-ngnode="${sandbox.node}"]`;
await page.waitForSelector(sect, { timeout: 10000 });
ok(await page.$eval(sect, s => /not deployed/.test(s.querySelector('.toolstate .pill').textContent)
     && document.querySelector('.nginxtab .docbarrow [data-ngdeploy]') && !s.querySelector('[data-ngremove]')
     && !s.querySelector('[data-ngsave]') && !s.querySelector('[data-ngadd]') && !s.querySelector('#ngCert')),
   '...its state row says so, with Deploy alone, in the bar with every header button: no routes or certificates before nginx is there (R181)');

// Routes kept before Deploy, as the Enroll dialog's tick has them for a node
// that has not said hello yet: the server keeps them, and Deploy brings
// them up.
const kept = await api('/api/nginx', { action: 'save', node: sandbox.node, routes: [{ host: 'www.example.com', path: '/', port: 8080, tls: true }] });
const saved = await api('/api/nginx');
const row = saved.nodes.find(n => n.node === sandbox.node);
ok(kept.ok && row.routes.length === 1 && row.routes[0].host === 'www.example.com' && row.routes[0].port === 8080 && row.routes[0].tls === true
   && !row.deployed,
   `a route saved before Deploy is kept on the controller, with nothing deployed yet (${JSON.stringify(row.routes)})`);
await page.evaluate(() => loadNginx());
await page.waitForFunction(id => /1 route and 0 certificates/.test(document.querySelector(`.nginxtab [data-ngnode="${id}"] .toolstate`)?.textContent || ''), sandbox.node, { timeout: 10000 });
ok(true, '...and the undeployed node says Deploy will bring that route up');
// Written from elsewhere (a Docker row's Add route, bb, another browser),
// the open tab re-reads by the revisions token, not by its Refresh (B714).
{
  const two = [...row.routes, { host: 'two.example.com', path: '/', port: 8081, tls: false }];
  await api('/api/nginx', { action: 'save', node: sandbox.node, routes: two });
  const came = await page.waitForFunction(id => document.querySelectorAll(`.nginxtab [data-ngnode="${id}"] .ngrec`).length === 2
      || /2 routes/.test(document.querySelector(`.nginxtab [data-ngnode="${id}"] .toolstate`)?.textContent || ''),
    sandbox.node, { timeout: 15000 }).then(() => true, () => false);
  ok(came, 'a route saved from elsewhere shows on the open tab within a poll, with no Refresh pressed');
  await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes });
  await page.waitForFunction(id => /1 route/.test(document.querySelector(`.nginxtab [data-ngnode="${id}"] .toolstate`)?.textContent || ''),
    sandbox.node, { timeout: 15000 });
}
// A hostname typed in the route row (the operator, 13 Oct): the last choice
// of the pick turns it into a box, and the name saved joins Hostnames.
{
  const typed = await api('/api/nginx', { action: 'save', node: sandbox.node, routes: [...row.routes, { host: 'typed.example.com', path: '/', port: 8082, tls: false }] });
  ok(typed.ok && (await api('/api/nginx')).hostnames.some(h => h.name === 'typed.example.com'),
     'a route saved with a name not on the list puts it there');
  // Before Deploy the section draws no route rows, so the pick is read as
  // its function draws it.
  ok(await page.evaluate(() => /value="__type"[^>]*>type a hostname/.test(nginxHostPick({ host: '' }))),
     '...and the hostname pick offers to type one');
  // ...and a row typed into is drawn as the box again, with what was typed
  // (B729: a redraw from the poll handed the pulldown back mid-word).
  ok(await page.evaluate(() => /^<input data-ng="host" value="turing"/.test(nginxHostPick({ host: 'turing', typed: true }).trim())),
     '...and draws a row typed into as the box again, carrying the letters so far');
  await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes });
  await api('/api/nginx', { action: 'host-remove', name: 'typed.example.com' });
}
ok(/a port on the node/.test((await api('/api/nginx', { action: 'save', node: sandbox.node, routes: [{ host: 'x.example.com', port: 'eighty' }] })).error || ''),
   'a route with no port is refused by name');
ok(/PEM/.test((await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes, cert: 'not a cert', key: 'nor a key' })).error || ''),
   '...and a certificate that is not one');

// Deploy: the container is written from the routes and built on the node.
await page.click('.nginxtab .docbarrow [data-ngdeploy]');
await page.waitForFunction(id => (nginxList || []).find(n => n.node === id)?.deployed, sandbox.node, { timeout: 20000 });
const rec = JSON.parse(readFileSync(`${DIR}/state/devapps.json`, 'utf8'))['nginx-sandbox'];
const written = await api('/api/container', { action: 'read', name: 'nginx-sandbox' });
ok(rec?.main?.source === 'file' && rec.main.node === sandbox.node && rec.main.for === 'System'
   && /network_mode: host/.test(written.compose || '') && /container_name: nginx-sandbox/.test(written.compose || '') && /www\.example\.com/.test(written.compose || '')
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
     && s.querySelector('[data-ngremove]') && !document.querySelector('.nginxtab [data-ngdeploy]')),
   '...and the state row now says so, with Remove in place of Deploy');
// A Save rebuilds it, and a read between its down and its up said "deployed,
// down" over a container on its way back (B65): while its job runs the
// line says rebuilding, and down only when nothing is bringing it back.
{
  const pills = await page.evaluate(id => {
    const n = (nginxList || []).find(x => x.node === id);
    const pill = st => (nginxBody({ ...n, state: st }).match(/<span class="pill[^"]*">([^<]*)<\/span>/) || [])[1];
    return [pill({ running: false, job: { running: true } }), pill({ running: false, job: null }), pill({ running: true })];
  }, sandbox.node);
  ok(pills.join(' | ') === 'deployed, rebuilding | deployed, down | deployed',
     `the state line says rebuilding while its job runs, and down only when nothing is bringing it back (${pills.join(' | ')})`);
}
ok(/already on the Containers page/.test((await api('/api/nginx', { action: 'deploy', node: sandbox.node })).error || ''),
   'a second Deploy is refused');
// The deployed page in sections (R218 step 29): Hostnames, Routes,
// Certificates and Image, each its state in its head; the routes a table
// of records, each read-only with its Edit, no Save until one is open
// (the record-lists rule); Remove apart at the foot; the certificate form
// rolled up until Add a certificate, its Add asleep until a pair is pasted,
// Cancel rolling it back.
{
  const shape = await page.$eval(sect, s => ({
    sects: [...s.querySelectorAll(':scope > details.sect')].map(d => `${d.querySelector('.t').textContent}:${d.querySelector('.sst')?.textContent || ''}`),
    save: s.querySelectorAll('details[data-sect="nginx:routes"] .ngrecords .ngrec [data-ngedit]').length === 1
      && !s.querySelector('details[data-sect="nginx:routes"] [data-ngsave]') && !s.querySelector('.ngform'),
    foot: !!s.querySelector(':scope > .field .ngfoot [data-ngremove]') && !s.querySelector('details.sect [data-ngremove]'),
    form: s.querySelector('.ngcertform').hidden }));
  ok(shape.sects.map(x => x.split(':')[0]).join() === 'Hostnames,Routes,Certificates,Image' && /1 route/.test(shape.sects[1])
     && shape.save && shape.foot && shape.form,
     `the deployed page is four sections with their states, the route a record with its Edit and no Save, Remove apart, and the certificate form rolled up (${shape.sects.join(' | ')})`);
  await page.click(`${sect} [data-ngcertopen]`);
  await page.waitForFunction(s => !document.querySelector(s + ' .ngcertform').hidden, sect, { timeout: 5000 });
  const asleep = await page.$eval(`${sect} [data-ngcertsave]`, b => b.disabled);
  await page.fill(`${sect} #ngCert`, '-----BEGIN CERTIFICATE-----');
  await page.fill(`${sect} #ngKey`, '-----BEGIN PRIVATE KEY-----');
  const awake = await page.$eval(`${sect} [data-ngcertsave]`, b => !b.disabled);
  const routesQuiet = !(await page.$(`${sect} .ngform`));
  await page.click(`${sect} [data-ngcertcancel]`);
  await page.waitForFunction(s => document.querySelector(s + ' .ngcertform').hidden && !document.querySelector(s + ' #ngCert').value, sect, { timeout: 5000 });
  ok(asleep && awake && routesQuiet,
     `Add a certificate unrolls the form, its Add waking once a pair is pasted and no route's form opening, and Cancel rolls it back empty (${JSON.stringify({ asleep, awake, routesQuiet })})`);
}

// On the deployed form, a route typed: Save wakes, and Save keeps it and
// rebuilds nginx; then the route list is put back as it was.
// The hostname is made once on the shared list, then picked on the route
// (the operator, 12 Oct).
await page.fill(`${sect} [data-nghostnew]`, 'api.example.com');
await page.click(`${sect} [data-nghostadd]`);
await page.waitForFunction(() => (nginxHostnames || []).some(h => h.name === 'api.example.com'), null, { timeout: 15000 });
await page.waitForSelector(`${sect} .nghost [data-nghostrm="api.example.com"]`, { timeout: 15000 });
ok(true, 'a hostname added to the list is on it, with Delete while nothing routes it');
await page.click(`${sect} [data-ngadd]`);
const fresh = `${sect} .ngform[data-i="-1"]`;
await page.waitForSelector(fresh, { timeout: 5000 });
ok(await page.$eval(`${fresh} [data-ng="host"]`, el => el.tagName === 'SELECT'
     && [...el.options].some(o => o.value === 'api.example.com') && [...el.options].some(o => o.value === '*'))
   && await page.$eval(sect, s => s.querySelector('.ngrecords > .row:not(.thead)')?.matches('.ngrec.open[data-i="-1"]') && s.querySelector('[data-ngadd]').disabled),
   '...and Add route opens a form at the table\'s top, its hostname picked from that list, every name (*) beside it');
await page.selectOption(`${fresh} [data-ng="host"]`, 'api.example.com');
const asleepNew = await page.$eval(`${fresh} [data-ngsave]`, b => b.disabled);
await page.fill(`${fresh} [data-ng="port"]`, '8081');
ok(asleepNew && await page.$eval(`${fresh} [data-ngsave]`, b => !b.disabled) && !(await page.$(`${fresh} [data-ngdel]`)),
   'the form\'s Save wakes once it has a hostname and a port, and a new route has no Delete');
await page.click(`${fresh} [data-ngsave]`);
await page.waitForFunction(id => (nginxList || []).find(n => n.node === id)?.routes?.length === 2, sandbox.node, { timeout: 15000 });
ok((await api('/api/nginx')).nodes.find(n => n.node === sandbox.node).routes.some(r => r.host === 'api.example.com' && r.port === 8081),
   '...and Save keeps it on the controller');
await page.waitForFunction(s => !document.querySelector(s + ' .ngform') && document.querySelectorAll(s + ' .ngrec').length === 2, sect, { timeout: 15000 });
ok(await page.$eval(`${sect} .ngrec[data-i="1"]`, r => /api\.example\.com/.test(r.textContent) && /8081/.test(r.textContent)),
   '...and folds back to a row reading the route');
// Edit opens that row in place, Cancel folds it back unchanged, Save
// writes the one route and Delete takes it out.
await page.click(`${sect} [data-ngedit="1"]`);
await page.waitForSelector(`${sect} .ngrec.open[data-i="1"] .ngform [data-ngdel]`, { timeout: 5000 });
ok(await page.$eval(`${sect} .ngform`, f => f.querySelector('[data-ng="port"]').value === '8081'
     && f.closest('.ngrec').dataset.i === '1') && await page.$$eval(`${sect} .ngform`, l => l.length === 1),
   'Edit opens that route in place, one form at a time, with what it holds');
await page.fill(`${sect} .ngform [data-ng="port"]`, '9999');
await page.click(`${sect} .ngform [data-ngcancel]`);
await page.waitForFunction(s => !document.querySelector(s + ' .ngform'), sect, { timeout: 5000 });
ok(await page.$eval(`${sect} .ngrec[data-i="1"]`, r => /8081/.test(r.textContent)), '...and Cancel folds it back as it was');
await page.click(`${sect} [data-ngedit="1"]`);
await page.waitForSelector(`${sect} .ngform`, { timeout: 5000 });
await page.fill(`${sect} .ngform [data-ng="port"]`, '8083');
await page.click(`${sect} .ngform [data-ngsave]`);
await page.waitForFunction(id => (nginxList || []).find(n => n.node === id)?.routes?.some(r => r.port === 8083), sandbox.node, { timeout: 15000 });
ok((await api('/api/nginx')).nodes.find(n => n.node === sandbox.node).routes.map(r => r.port).join() === '8080,8083',
   '...and its Save writes that one route, the other kept');
await page.waitForFunction(s => !document.querySelector(s + ' .ngform'), sect, { timeout: 15000 });
await page.click(`${sect} [data-ngedit="1"]`);
await page.waitForSelector(`${sect} .ngform [data-ngdel]`, { timeout: 5000 });
await page.click(`${sect} .ngform [data-ngdel]`);
await page.waitForFunction(id => (nginxList || []).find(n => n.node === id)?.routes?.length === 1, sandbox.node, { timeout: 15000 });
ok(/Delete the route api\.example\.com to port 8083/.test(page.dialogs.at(-1) || '')
   && (await api('/api/nginx')).nodes.find(n => n.node === sandbox.node).routes.every(r => r.host === 'www.example.com'),
   `...and Delete asks, naming the route, then takes it out (${page.dialogs.at(-1)})`);
await api('/api/nginx', { action: 'save', node: sandbox.node, routes: [...row.routes, { host: 'api.example.com', path: '/', port: 8081, tls: true }] });
{
  const busyName = await api('/api/nginx', { action: 'host-remove', name: 'api.example.com' });
  ok(/routed on sandbox: take those routes off first/.test(busyName.error || ''),
     `a hostname a route uses is not deleted, and the refusal names where (${(busyName.error || 'deleted').slice(0, 70)})`);
  await api('/api/nginx', { action: 'host-add', name: 'spare.example.com' });
  const gone = await api('/api/nginx', { action: 'host-remove', name: 'spare.example.com' });
  ok(gone.ok && !gone.hostnames.some(h => h.name === 'spare.example.com'), '...and one routed nowhere is');
}
const quietRoutes = async () => { for (let i = 0; i < 180; i++){ if (!(((await api('/api/v1/jobs?active=1')).jobs) || []).some(j => j.project === 'nginx-sandbox')) return; await new Promise(r => setTimeout(r, 500)); } };
await quietRoutes();
await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes });
await quietRoutes();
await page.evaluate(() => loadNginx());

// A certificate per domain (R175, R188): one made here with openssl is
// kept under the domain its names say, listed with its names, used by the
// routes its names cover, and taken off again by its key. No default.
{
  execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=www.example.com',
    '-addext', 'subjectAltName=DNS:www.example.com', '-keyout', `${DIR}/ngx-k.pem`, '-out', `${DIR}/ngx-c.pem`], { stdio: 'ignore' });
  const cert = readFileSync(`${DIR}/ngx-c.pem`, 'utf8'), key = readFileSync(`${DIR}/ngx-k.pem`, 'utf8');
  const own = await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes, cert, key });
  const v = (await api('/api/nginx')).nodes.find(n => n.node === sandbox.node);
  ok(own.ok && own.host === 'www.example.com' && v.certs?.['www.example.com']?.set && v.certs['www.example.com'].subject === 'www.example.com'
     && v.resolved?.['www.example.com'] === 'www.example.com',
     `a pasted pair is kept under the domain its names say, and the route for that hostname resolves to it (${JSON.stringify(v.certs)})`);
  await page.evaluate(() => loadNginx());
  await page.waitForFunction(id => document.querySelector(`.nginxtab [data-ngnode="${id}"] .ngcert .name`)?.textContent === 'www.example.com', sandbox.node, { timeout: 10000 });
  await page.click(`${sect} [data-ngedit="0"]`);
  await page.waitForSelector(`${sect} .ngform`, { timeout: 5000 });
  ok(await page.$eval(sect, s => /1 route/.test(s.querySelector('.ngcert .sub').textContent)
       && [...s.querySelectorAll('.ngroute [data-ng="cert"] option')].some(o => o.value === 'www.example.com')
       && /443, www\.example\.com's pair/.test(s.querySelector('.ngroute [data-ng="cert"] option[value=""]').textContent)),
     "...and the section lists it with the route that uses it, and the route's picker names it as the automatic pick");
  await page.click(`${sect} .ngform [data-ngcancel]`);
  await api('/api/nginx', { action: 'save', node: sandbox.node, routes: row.routes, drop_cert: 'www.example.com' });
  ok(!((await api('/api/nginx')).nodes.find(n => n.node === sandbox.node).certs?.['www.example.com']), '...and it can be taken off again by its key');
}


// The image (R192): the registry's tag list read by Check now (a file here,
// BB_NGINX_TAGS_URL), the newest release line's alpine tag kept, and the
// deployed nginx, unpinned since nothing had been read when it was written,
// said to be behind it on the tab, on its Docker row and in the bell;
// Update pins the digest into its compose file and rebuilds.
ok(await page.$eval(`${sect} .ngimgbar .state`, e => /never checked/.test(e.textContent))
   && !(await page.$(`${sect} [data-ngupdate]`))
   && await page.$eval(`${sect} .ngimage`, e => /nginx:1\.27-alpine, not pinned/.test(e.textContent)),
   'before any check the Image field says never checked and unpinned, with no Update');
writeFileSync(`${DIR}/nginx-tags.json`, JSON.stringify({ results: [
  { name: '1.27-alpine', digest: 'sha256:' + 'a'.repeat(64) },
  { name: '1.29-alpine-slim', digest: 'sha256:' + 'c'.repeat(64) },
  { name: '1.29-alpine', digest: 'sha256:' + 'b'.repeat(64) },
  { name: 'stable-alpine', digest: 'sha256:' + 'd'.repeat(64) } ] }));
await page.click(`${sect} [data-ngcheck]`);
await page.waitForFunction(() => nginxLatest?.tag === '1.29-alpine', { timeout: 10000 });
await page.waitForSelector(`${sect} [data-ngupdate]`, { timeout: 10000 });
ok(await page.$eval(sect, s => /Update to 1\.29-alpine/.test(s.querySelector('[data-ngupdate]').textContent)
     && /1\.29-alpine is out/.test(s.querySelector('.ngimgbar').previousElementSibling.textContent)
     && /checked/.test(s.querySelector('.ngimgbar .state').textContent)),
   'Check now reads the registry: the newest line is 1.29-alpine (not -slim or stable-), and the unpinned nginx is behind it, with Update');
// The bell's own note for it, to the nginx tab on that node.
await page.click('#bBell');
await page.waitForSelector('#bellPanel [data-bnginx]', { timeout: 15000 });
ok(await page.$eval('#bellPanel', e => /nginx update on sandbox/.test(e.textContent) && /1\.29-alpine/.test(e.textContent)
     && e.querySelector('[data-bdismiss^="nginx:"]')),
   'the bell carries an nginx note of its own kind, with Dismiss keyed to the digest');
await page.click('#bBell');
// ...and the Docker row says so with Update, the word every row's update uses.
await page.evaluate(() => openDocker());
await page.waitForSelector('.dmtab .row[data-inst="nginx-sandbox|main"] [data-dm="nginx-update"]', { timeout: 20000 });
// System's row keeps what a person needs and loses what the nginx tab owns
// (the operator, 13 Oct; R207): Down, Remove and the update (Up while it is
// stopped: a running row wears none), no Edit, Rebuild or Copy or move, and
// a line saying where its settings are.
const sysBtns = await page.$eval('.dmtab .row[data-inst="nginx-sandbox|main"]', r => ({
  has: [...r.querySelectorAll('.dmacts [data-dm]')].map(b => b.dataset.dm), rel: !!r.querySelector('[data-dmrel]'),
  line: r.querySelector('.dmmanaged')?.textContent || '' }));
ok(['down', 'remove', 'nginx-update'].every(b => sysBtns.has.includes(b)) && !sysBtns.has.includes('edit') && !sysBtns.has.includes('rebuild') && !sysBtns.rel
   && /nginx page/.test(sysBtns.line),
   `BuilderBot's nginx row keeps Down, Remove and the update and loses Edit, Rebuild and Copy or move (${sysBtns.has.join(', ')}; ${sysBtns.rel ? 'copy or move' : 'no copy or move'})`);
ok(await page.$eval('.dmtab .row[data-inst="nginx-sandbox|main"]', r => /1\.29-alpine is out/.test(r.querySelector('.dmnginx').textContent)
     && r.querySelector('[data-dm="nginx-update"]').textContent.trim() === 'Update'),
   'the Containers page\'s row of a node\'s nginx says the line is out, with Update as on every row');
await page.evaluate(() => openNginxTab());
await page.waitForSelector(`${sect} [data-ngupdate]`, { timeout: 10000 });
await page.click(`${sect} [data-ngupdate]`);   // its confirm is accepted by lib.mjs's dialog handler
await page.waitForFunction(id => !(nginxList || []).find(n => n.node === id)?.behind, sandbox.node, { timeout: 20000 });
const pinned = await api('/api/container', { action: 'read', name: 'nginx-sandbox' });
ok(/image: nginx:1\.29-alpine@sha256:b{64}/.test(pinned.compose || '')
   && await page.$eval(`${sect} .ngimage`, e => /nginx:1\.29-alpine \(b{12}\)/.test(e.textContent))
   && !(await page.$(`${sect} [data-ngupdate]`)),
   'Update pins the digest into the compose file and rebuilds, and the node is not behind any more');
ok((await api('/api/nginx', { action: 'update', node: sandbox.node })).same === true, 'a second Update has nothing to move to and says so');
// The same tag built again upstream is a newer build, not the tag named twice (B27).
{
  const tags = d => writeFileSync(`${DIR}/nginx-tags.json`, JSON.stringify({ results: [
    { name: '1.29-alpine', digest: 'sha256:' + d.repeat(64) }] }));
  tags('f');
  await page.click(`${sect} [data-ngcheck]`);
  await page.waitForSelector(`${sect} [data-ngupdate]`, { timeout: 10000 });
  const said = await page.$eval(sect, s => ({ btn: s.querySelector('[data-ngupdate]').textContent.trim(),
    hint: s.querySelector('.ngimgbar').previousElementSibling.textContent }));
  ok(said.btn === 'Update to the newer build' && /a newer build of nginx:1\.29-alpine is out/.test(said.hint),
     `a rebuilt tag is said as a newer build of it (${said.btn} | ${said.hint.trim().slice(0, 60)})`);
  tags('b');
  await page.click(`${sect} [data-ngcheck]`);
  await page.waitForFunction(s => !document.querySelector(s + ' [data-ngupdate]'), sect, { timeout: 10000 });
}
// Its rebuild is a job of the instance, and a compose verb is refused while
// one runs (_submit): the Save and the Remove below wait for quiet.
const quiet = async () => until(async () => ((await api('/api/v1/jobs?active=1')).jobs || []).some(j => j.project === 'nginx-sandbox') ? null : true, 90000, 500);
await quiet();

// Save on a deployed one rewrites the file and rebuilds.
const two = await api('/api/nginx', { action: 'save', node: sandbox.node,
  routes: [...row.routes, { host: 'www.example.com', path: '/relay', port: 8788, tls: false }] });
const again = await api('/api/container', { action: 'read', name: 'nginx-sandbox' });
ok(two.ok && two.deployed && /location \/relay\/ \{ proxy_pass http:\/\/127\.0\.0\.1:8788; \}/.test(again.compose || ''),
   `Save on a deployed nginx rewrites its compose file and rebuilds (${JSON.stringify(two).slice(0, 80)})`);
// The private key goes to the node inside that file and never into a text
// box (B656): the Docker tab's copy carries a line in its place, and saving
// that copy back is refused, since the file is the nginx tab's to write.
{
  const cert = readFileSync(`${DIR}/ngx-c.pem`, 'utf8'), key = readFileSync(`${DIR}/ngx-k.pem`, 'utf8');
  // The routes as saved above, two of them: a save carries the whole list.
  const kept = (await api('/api/nginx')).nodes.find(n => n.node === sandbox.node).routes;
  await api('/api/nginx', { action: 'save', node: sandbox.node, routes: kept, cert, key });
  const shown = await api('/api/container', { action: 'read', name: 'nginx-sandbox' });
  ok(!/PRIVATE KEY/.test(shown.compose || '') && /tls_key_www_example_com:\n    content: \|\n      \(the private key: kept on the controller, never shown\)/.test(shown.compose || '')
     && /BEGIN CERTIFICATE/.test(shown.compose || ''),
     `the Containers page's copy of nginx's compose carries the certificate and a line in place of the key`);
  const back = await api('/api/container', { action: 'save', name: 'nginx-sandbox', compose: shown.compose, env: '' });
  ok(/written from the nginx page/.test(back.error || ''), `...and saving that copy back is refused (${(back.error || 'saved').slice(0, 60)})`);
  // It is managed (the operator, 11 Oct): its env and its name are refused
  // as its compose is, and the Edit dialog is for reading whatever its state.
  const envSet = await api('/api/devapp', { project: 'nginx-sandbox', instance: 'main', action: 'env-set', text: 'X=1\n' });
  const renamed = await api('/api/devapp', { project: 'nginx-sandbox', instance: 'main', action: 'rename', name: 'proxy' });
  ok(/managed/.test(envSet.error || '') && /managed/.test(renamed.error || ''),
     `...and so are its env and its name (${(envSet.error || 'saved').slice(0, 50)})`);
  await page.evaluate(() => openDocker());
  await page.waitForSelector('.dmtab .row[data-inst="nginx-sandbox|main"]', { timeout: 20000 });
  await page.evaluate(() => openEditContainer('nginx-sandbox'));
  await page.waitForSelector('#cmodal:not([hidden])');
  // Locked once its own read has landed, which the dialog opens before: read
  // in the instant it opened, under a whole run's load it was not yet.
  const locked = () => document.getElementById('cName').disabled && document.getElementById('cGo').disabled
    && document.getElementById('cEnv').readOnly && document.getElementById('cYml').readOnly
    && /BuilderBot manages this one/.test(document.getElementById('cNameHint').textContent);
  ok(await page.waitForFunction(locked, null, { timeout: 15000 }).then(() => true, () => false),
     '...and its Edit dialog is for reading: name, compose file and env locked, Save ghosted');
  await page.evaluate(() => { document.getElementById('cmodal').hidden = true; openNginxTab(); });
  await api('/api/nginx', { action: 'save', node: sandbox.node, routes: kept, drop_cert: 'www.example.com' });
}

// Remove: the container goes, the routes stay for a redeploy.
await quiet();
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
   `Remove takes the container off the Containers page, or queues its down on a quiet node, and keeps the routes here (${JSON.stringify([after.deployed, after.routes.length, gone, queued])})`);
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
