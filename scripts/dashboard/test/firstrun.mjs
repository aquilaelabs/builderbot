// First run (R199, R267): after the owner is made, the page is the setup
// page until Finish: four step cards at the reading width with nothing
// beside them (no rail, no panes, so no dock, no search), each with its
// state and its own action; the node's buttons open the Nodes page's own
// dialogs; the name and email step saves to the profile; Finish waits for
// a node and lands on Home, whose Getting started card keeps what is left.
// The fixture starts with setup done, so it is put back to first run here,
// as making the owner does, and Finish puts it right again.
import { URL, launch, newPage, ok, done, sleep, DIR, patience } from './lib.mjs';
import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, rmSync, openSync } from 'node:fs';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';

const auth = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const base = URL.replace(/\/$/, '');
const api = async (path, body) => {
  const r = await fetch(base + path, body === undefined ? { headers: auth }
    : { method: 'POST', headers: { ...auth, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  return r.status === 204 ? {} : r.json();
};
const firstRun = async on => api('/api/settings', { set: { setup_done: !on } });

const browser = await launch();
for (const [where, vp] of [['at a desk', { viewport: { width: 1280, height: 900 } }],
                           ['on a phone', { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }]]){
  const r = await firstRun(true);
  ok(!r.error, `first run turned back on for the walk ${where} (${r.error || 'ok'})`);
  const page = await newPage(browser, vp);
  await page.goto(URL);
  await page.waitForFunction(() => typeof state !== 'undefined' && state?.settings && document.body.classList.contains('firstrun'), null, { timeout: 20000 });
  await page.waitForSelector('#setupPanel .setstep', { timeout: 20000 });

  // ---- the page, and nothing beside it ---------------------------------------
  const frame = await page.evaluate(() => {
    const vis = s => { const e = document.querySelector(s); return !!e && e.offsetWidth > 0 && getComputedStyle(e).display !== 'none'; };
    const steps = [...document.querySelectorAll('#setupPanel .setstep')].map(s => ({
      title: s.querySelector('h3')?.textContent.trim(), state: s.querySelector('.setstephead .pill')?.textContent.trim() }));
    const page = document.querySelector('#setupPanel .setuppage').getBoundingClientRect();
    return { steps, rail: vis('#rail'), panes: vis('#panes'), jump: vis('#jump'), bell: vis('#bBell'),
             about: !document.getElementById('aboutModal').hidden, width: Math.round(page.width), inner: innerWidth };
  });
  ok(frame.steps.map(s => s.title).join(' | ') === 'Your first node | Your name and email | Claude Code on your node | A first project',
     `the setup page is four steps, in order, ${where} (${frame.steps.map(s => s.title).join(' | ')})`);
  ok(frame.steps.every(s => /^(to do|waiting|done)$/.test(s.state || '')),
     `...each with its state as a pill (${frame.steps.map(s => s.state).join(', ')})`);
  ok(!frame.rail && !frame.panes && !frame.jump && !frame.bell,
     `...and nothing beside it: no rail, no panes and so no dock, no search, no bell (${JSON.stringify(frame)})`);
  ok(!frame.about, '...and the Getting started guide does not open over it (B839)');
  ok(frame.width <= Math.min(frame.inner, 1100), `...at the reading width (${frame.width} of ${frame.inner})`);

  // ---- the node: the Nodes page's own dialogs, and its state -------------------
  const nodeDone = frame.steps[0].state === 'done';
  if (!nodeDone){
    await page.click('#setupPanel [data-setenroll]');
    await page.waitForFunction(() => !document.getElementById('ndmodal').hidden && document.getElementById('ndBody').textContent.includes('Name'),
      null, { timeout: 10000 });
    ok(true, `Enroll node in the node step opens the Nodes page's own dialog ${where}`);
    await page.keyboard.press('Escape');
    await page.evaluate(() => { document.getElementById('ndmodal').hidden = true; });
  } else {
    ok(await page.evaluate(() => !document.querySelector('#setupPanel [data-setenroll]')),
       `a node answering, the node step is done and offers no Enroll ${where}`);
  }
  ok(await page.evaluate(n => document.getElementById('setupFinish').disabled === !n, nodeDone),
     `Finish ${nodeDone ? 'is live with a node answering' : 'waits for a node'} ${where}`);

  // ---- the name and email: Save wakes on both, and the profile has them --------
  if (frame.steps[1].state !== 'done'){
    const dead0 = await page.evaluate(() => document.querySelector('[data-setgit]').disabled);
    await page.fill('#setName', 'First Runner');
    const dead1 = await page.evaluate(() => document.querySelector('[data-setgit]').disabled);
    await page.fill('#setEmail', 'runner@example.test');
    const dead2 = await page.evaluate(() => document.querySelector('[data-setgit]').disabled);
    ok(dead0 && dead1 && !dead2, `Save sleeps until a name and an email are both typed ${where} (${dead0} ${dead1} ${dead2})`);
    await page.click('[data-setgit]');
    await page.waitForFunction(() => [...document.querySelectorAll('#setupPanel .setstep')][1]?.querySelector('.pill')?.textContent === 'done',
      null, { timeout: 15000 }).catch(() => {});
    const prof = await api('/api/profile');
    ok(prof.git_ready !== false && await page.evaluate(() => [...document.querySelectorAll('#setupPanel .setstep')][1].querySelector('.pill').textContent === 'done'),
       `...and saving it readies the commit author and turns the step to done (${JSON.stringify(prof.git || {})})`);
  } else ok(true, `the name and email step is done for an account that has them ${where}`);

  // ---- Finish: Home, and what is left in its card -----------------------------
  if (nodeDone){
    await page.click('#setupFinish');
    await page.waitForFunction(() => !document.body.classList.contains('firstrun'), null, { timeout: 15000 });
    await page.waitForFunction(() => location.hash === '#/home' && document.querySelector('.doc.on .hometiles'), null, { timeout: 20000 });
    const card = await page.evaluate(() => {
      const c = document.querySelector('.doc.on .hstart');
      return c ? { rows: [...c.querySelectorAll('.hsrow')].map(r => `${r.classList.contains('done') ? '✓' : '·'} ${r.querySelector('.grow').textContent}`),
                   count: c.querySelector('h3 .sst')?.textContent } : null;
    });
    ok(card === null || (card.rows.length >= 2 && /^\d+ of \d+$/.test(card.count || '')),
       `Finish lands on Home, where Getting started keeps what is left ${where} (${card ? card.count + ': ' + card.rows.join('; ') : 'all four done'})`);
    if (card){
      // The coding agent's step sends a person where agents are managed.
      const step = await page.$eval('.doc.on .hstart', c => c.querySelector('[data-hstart="claude"]')?.textContent || '');
      ok(step === '' || step === 'Agents page', `...its coding agent step opens the Agents page, not Toolchains (${step || 'done'})`);
      await page.click('.doc.on .hstart [data-hstart="hide"]');
      await page.waitForFunction(() => !document.querySelector('.doc.on .hstart'), null, { timeout: 10000 });
      ok(true, '...and Put away takes the card off Home');
      await page.evaluate(() => { try{ localStorage.removeItem('bb.gsHidden'); }catch(e){} });
    }
  } else {
    await firstRun(false);
  }
  await page.close();
}
// Left as the fixture had it.
await firstRun(false);

// ---- a bare-metal install's first run (R90) -----------------------------------
// The container's first run needs a node the person enrolls; a controller
// installed bare metal has one already, its own machine, enrolled by the
// installer, and Finish waits for that one and for no other (the operator,
// 22 Oct). Told by the install's marker in its env file, BB_INSTALL. Each
// on a controller of its own, from a fresh state, beside the harness's.
{
  const DASH = fileURLToPath(new globalThis.URL('..', import.meta.url));
  const LIB = fileURLToPath(new globalThis.URL('../../lib', import.meta.url));
  const freePort = () => new Promise(res => {
    const s = createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
  });
  const OWNER = { username: 'firstowner', password: 'longenough1' };
  const H = { Authorization: 'Basic ' + Buffer.from(`${OWNER.username}:${OWNER.password}`).toString('base64'),
              'Content-Type': 'application/json' };
  const controller = async (kind, { noOwner = false } = {}) => {
    const w = `${DIR}/firstrun-${kind}`;
    rmSync(w, { recursive: true, force: true });
    for (const d of ['config', 'workspace', 'home']) mkdirSync(`${w}/${d}`, { recursive: true });
    const env = { ...process.env, DASHBOARD_STATE: `${w}/config`, WORKSPACE: `${w}/workspace` };
    // Nobody's yet when asked (a move's destination, R90 step 12).
    if (!noOwner) execFileSync('python3', [`${LIB}/users-verbs.py`, 'claim', `${DASH}/users.py`, OWNER.username],
                               { env: { ...env, BB_USERS_PW: OWNER.password } });
    const port = await freePort();
    const out = openSync(`${w}/server.log`, 'a');
    const proc = spawn('python3', ['-u', `${DASH}/server.py`], { stdio: ['ignore', out, out], env: {
      ...env, DASHBOARD_PORT: String(port), BUILDER_HOME: `${w}/home`,
      BB_DOCTOR_FIXTURE: `${DIR}/doctor.txt`, TC_AUTOCHECK: '0', BB_NODE_POLL: '3',
      BB_CLAUDE_LATEST_URL: 'file:///nonexistent', BB_CLAUDE_CHECK_DELAY: '3600', BB_NGINX_TAGS_URL: 'file:///nonexistent',
      BB_NGINX_CHECK_DELAY: '3600', BB_APPS_RELEASES_URL: 'file:///nonexistent', BB_APPS_BOOT_DELAY: '3600',
      BB_IMAGE_CHECK_DELAY: '3600', BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', BB_COVERAGE_OUT: '',
      ...(kind === 'bare' ? { BB_INSTALL: 'bare-metal' } : {}) } });
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < patience(120); i++){
      try { if ((await fetch(`${base}/login`)).status === 200) break; } catch { /* not up yet */ }
      await sleep(250);
    }
    const post = async (path, body, h = H) => (await fetch(base + path, { method: 'POST', headers: h, body: JSON.stringify(body) })).json();
    await post('/api/settings', { set: { setup_done: false } });
    // A node of it, minted from a shell as the installer mints its own, and
    // answering by its enrollment.
    const enroll = async (name, own) => {
      const tok = execFileSync('python3', [`${LIB}/nodes-verbs.py`, 'enroll-token', `${DASH}/nodes.py`, name, '--user', 'bb',
                                           ...(own ? ['--own'] : [])], { encoding: 'utf8', env }).trim();
      return { tok, go: () => post('/api/v1/agent/enroll', { user: 'bb', version: '1', digest: 'sha256:' + '1'.repeat(64),
        census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux' } },
        { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' }) };
    };
    const finish = () => post('/api/settings', { set: { setup_done: true } });
    return { base, proc, enroll, finish, stop: () => proc.kill('SIGTERM') };
  };

  const ctr = await controller('container');
  const none = await ctr.finish();
  ok(/enroll a node that runs sessions first/.test(none.error || ''),
     `the container's first run still needs a node enrolled before Finish (${none.error || 'finished'})`);
  await (await ctr.enroll('box1', false)).go();
  const fin = await ctr.finish();
  ok(!fin.error, `...and finishes once one answers (${fin.error || 'ok'})`);
  ctr.stop();

  const bm = await controller('bare');
  const own = await bm.enroll('thismachine', true);
  const pending = await bm.finish();
  ok(/this machine is still being set up as a node/.test(pending.error || ''),
     `a bare-metal first run waits for its own machine while it is being set up (${pending.error || 'finished'})`);
  const page = await newPage(browser, { httpCredentials: OWNER, extraHTTPHeaders: { Authorization: H.Authorization } });
  await page.goto(bm.base);
  await page.waitForSelector('#setupPanel .setstep', { timeout: 20000 });
  const draw = () => page.evaluate(async () => {
    await loadNodes(); setupSig = ''; drawSetup();
    const s = document.querySelector('#setupPanel .setstep');
    return { title: s?.querySelector('h3')?.textContent.trim(), state: s?.querySelector('.pill')?.textContent.trim(),
             text: s?.querySelector('.setstepbody')?.textContent.trim(), more: s?.querySelector('[data-setenroll]')?.textContent.trim(),
             primary: !!s?.querySelector('[data-setenroll].primary'), finish: document.getElementById('setupFinish')?.disabled };
  });
  const before = await draw();
  ok(before.title === 'This machine' && before.state === 'waiting' && /agent is being installed/.test(before.text) && before.finish,
     `its setup page shows this machine as the node being set up, with where it is, and Finish waits (${JSON.stringify(before)})`);
  ok(before.more === 'Enroll another machine' && !before.primary, '...and offers Enroll for more machines, as an option');
  await (await bm.enroll('otherbox', false)).go();
  const other = await bm.finish();
  ok(/still being set up as a node/.test(other.error || ''), `another node answering does not finish it (${other.error || 'finished'})`);
  const en = await own.go();
  ok(en.ok, `this machine enrolls (${en.error || 'ok'})`);
  const after = await draw();
  ok(after.state === 'done' && /the machine this controller runs on, is enrolled and answering/.test(after.text) && !after.finish,
     `...and the step is done with Finish open (${JSON.stringify(after)})`);
  const fin2 = await bm.finish();
  ok(!fin2.error, `a bare-metal first run finishes with only its own node (${fin2.error || 'ok'})`);
  // This machine (R90 step 8): the rail's Controller group opens on it, its
  // page draws the own node's row with the machine's head and the Updates
  // section, the Nodes page's picker leaves it out, and a project's node
  // picker names it This machine.
  await page.evaluate(async () => { await refresh(); await loadNodes(); });
  await page.waitForFunction(() => !!state?.own_node, null, { timeout: 15000 }).catch(() => {});
  const rail = await page.evaluate(() => (railGroups().find(g => g.key === 'controller')?.tools || []).filter(([k]) => railAllows(k)).map(([k]) => k));
  ok(rail[0] === 'machine', `the rail's Controller group offers This machine first on a bare-metal install (${rail.join(',')})`);
  await page.evaluate(() => openMachineTab());
  await page.waitForSelector('.machinetab .ndrow[data-node]', { timeout: 15000 });
  const mp = await page.evaluate(() => ({
    head: document.querySelector('.machinetab .pghead')?.textContent.replace(/\s+/g, ' ') || '',
    tag: !!document.querySelector('.machinetab .ndrow .tag.ndown'),
    updates: !!document.querySelector('.machinetab details[data-sect="nodes:updates"]'),
    sects: [...document.querySelectorAll('.machinetab .ndsections details.sect')].map(d => d.dataset.sect) }));
  ok(/Release/.test(mp.head) && /Wall/.test(mp.head) && mp.tag && mp.updates && mp.sects.includes('nodes:health') && mp.sects.includes('nodes:advanced'),
     `This machine draws the machine's head, the Updates section and the own node's row with its sections (${mp.sects.join(',')})`);
  // A held start (R56 step 9): not held on this first boot, armed for the
  // next by its press, and Start says there was nothing to lift.
  const h0 = await page.evaluate(() => state?.held || null);
  ok(h0 && h0.held === false && h0.armed === false, `a bare-metal install's first start is not held (${JSON.stringify(h0)})`);
  const bmH = { Authorization: 'Basic ' + Buffer.from(`${OWNER.username}:${OWNER.password}`).toString('base64'), 'Content-Type': 'application/json' };
  const bmApi = async (path, body) => (await fetch(bm.base + path, body === undefined ? { headers: bmH } : { method: 'POST', headers: bmH, body: JSON.stringify(body) })).json();
  const armed = await bmApi('/api/v1/nodes', { action: 'hold-next', on: true });
  const h1 = await bmApi('/api/status');
  ok(armed.ok && armed.armed === true && h1.held?.armed === true, `Hold the next start arms the restart after this one (${JSON.stringify(armed)})`);
  await bmApi('/api/v1/nodes', { action: 'hold-next', on: false });
  const started = await bmApi('/api/v1/nodes', { action: 'start-held' });
  ok(started.ok && /not held/.test(started.note || ''), `Start with nothing held says so (${JSON.stringify(started)})`);
  // Name and time (R161 step 3): the own machine's section, Apply asleep
  // until a field moves, and the press a system job on its node.
  const nt = await page.evaluate(() => {
    const sect = document.querySelector('.machinetab details[data-sect="nodes:machine"]');
    const b = sect?.querySelector('[data-nd="machine-apply"]'), tz = sect?.querySelector('[data-k="machinetz"]');
    const before = b?.disabled;
    if (tz){ tz.value = 'Europe/Paris'; tz.dispatchEvent(new Event('input')); }
    return { there: !!sect, before, after: b?.disabled, zones: document.querySelectorAll('#ndZones option').length };
  });
  ok(nt.there && nt.before === true && nt.after === false && nt.zones > 100,
     `This machine carries Name and time, Apply waking when the zone is typed, the browser's zones offered (${JSON.stringify(nt)})`);
  const mj = await bmApi('/api/v1/nodes', { action: 'machine', id: (await bmApi('/api/status')).own_node, timezone: 'Europe/Paris' });
  ok(mj.ok && mj.job, `the press queues the machine job on the own node (${JSON.stringify(mj)})`);
  const mr = await bmApi('/api/v1/nodes', { action: 'machine', id: (await bmApi('/api/status')).own_node, hostname: 'bad name' });
  ok(/letters, digits and hyphens/.test(mr.error || ''), `...and a name that is not one is refused (${mr.error})`);
  await page.evaluate(() => openNodesTab());
  await page.waitForFunction(() => document.querySelector('#ndPick'), null, { timeout: 15000 }).catch(() => {});
  const picks = await page.evaluate(() => [...document.querySelectorAll('#ndPick option')].map(o => o.textContent));
  ok(!picks.some(t => /thismachine/.test(t)) && picks.some(t => /otherbox/.test(t)),
     `...and the Nodes page's picker offers the other node and not this machine (${picks.join(' | ')})`);
  await page.close();
  bm.stop();

  // Moving a controller (R90 step 12): a source with a node prepares a move
  // (the bundle sealed, the token shown once, the node told from its next
  // hello), a destination nobody owns takes the bundle and the token on its
  // first page and restarts on the state, where the node's knock is
  // answered with the challenge it holds; the source marked moved is
  // read-only and tells the node it moved.
  {
    const src = await controller('src');
    const sH = { Authorization: 'Basic ' + Buffer.from(`${OWNER.username}:${OWNER.password}`).toString('base64'), 'Content-Type': 'application/json' };
    const sApi = async (path, body) => (await fetch(src.base + path, body === undefined ? { headers: sH } : { method: 'POST', headers: sH, body: JSON.stringify(body) })).json();
    const mover = await src.enroll('mover', false);
    const en = await mover.go();
    ok(en.ok && en.token, `the source has a node (${en.error || 'enrolled'})`);
    const nH = { Authorization: 'Bearer ' + en.token, 'Content-Type': 'application/json' };
    const prep = await sApi('/api/move', { action: 'prepare', to: 'http://127.0.0.1:1', repos: false });
    ok(prep.ok && prep.token && prep.bundle && prep.counts?.state >= 2, `Prepare to move writes a sealed bundle and shows a token once (${prep.error || prep.bundle})`);
    const told = await (await fetch(src.base + '/api/v1/agent/hello', { method: 'POST', headers: nH,
      body: JSON.stringify({ census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux' }, version: '1', digest: 'sha256:' + '1'.repeat(64) }) })).json();
    ok(told.move?.url === 'http://127.0.0.1:1' && /^[0-9a-f]{64}$/.test(told.move?.expect || ''), `the node hears where it goes and a challenge of its own (${JSON.stringify(told.move)})`);
    const bundle = Buffer.from(await (await fetch(src.base + '/api/move-bundle', { headers: sH })).arrayBuffer());
    ok(bundle.length > 500 && bundle.subarray(0, 8).toString() === 'BBMOVE1\n', `the bundle downloads, sealed (${bundle.length} bytes)`);
    const dst = await controller('dst', { noOwner: true });
    const form = new FormData();
    form.append('bundle', new Blob([bundle]), prep.bundle);
    form.append('token', 'not-the-token');
    const bad = await fetch(dst.base + '/setup/move', { method: 'POST', body: form });
    const badText = await bad.text();
    ok(bad.status === 200 && /not this bundle.{0,8}s move token/.test(badText), `another token is refused on the first page (${bad.status}: ${(badText.match(/<p class="err">([^<]*)/) || [])[1] || badText.slice(0, 120).replace(/\s+/g, ' ')})`);
    form.set('token', prep.token);
    const r = await fetch(dst.base + '/setup/move', { method: 'POST', body: form });
    const html = await r.text();
    ok(r.status === 200 && /The controller is here now/.test(html), `the destination takes the bundle and the token on its first page (${r.status})`);
    // Restarted on the state: the process before it still answered from
    // its own memory for a moment, so the node list is what says it is the
    // new one.
    const nodesThere = await (async () => { const end = Date.now() + patience(90000); while (Date.now() < end){
      try { const ns = ((await (await fetch(dst.base + '/api/v1/nodes', { headers: sH })).json()).nodes || []).map(n => n.name);
        if (ns.includes('mover')) return ns; } catch { /* restarting */ }
      await sleep(1000); } return []; })();
    ok(nodesThere.includes('mover'), `restarted on the state, the destination knows the source's accounts and nodes (${nodesThere.join(',')})`);
    const knock = await (await fetch(dst.base + '/api/v1/agent/moved', { method: 'POST', headers: nH, body: JSON.stringify({ node: en.node_id }) })).json();
    ok(knock.answer === told.move.expect, `the node's knock is answered with the challenge it holds (${(knock.answer || '').slice(0, 12)})`);
    const moved = await sApi('/api/move', { action: 'moved', to: dst.base });
    ok(moved.ok, 'the source is marked moved');
    const ro = await sApi('/api/prefs', { project: 'alpha', gpu: 'off' });
    const gone = await fetch(src.base + '/api/v1/agent/hello', { method: 'POST', headers: nH, body: JSON.stringify({ census: {}, version: '1', digest: 'x' }) });
    ok(/read-only/.test(ro.error || '') && gone.status === 410 && (await gone.json()).to === dst.base,
       `...read-only after, and it tells the node it moved and where (${ro.error} / ${gone.status})`);
    src.stop();
    dst.stop();
  }
}
await done(browser);
