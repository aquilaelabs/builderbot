// The Claude sign-in (signin.py, claudegrant.py, page-signin.js): one
// account's, on one node. A person signs in on each node they work on, from
// that node's row on the Nodes tab, and signs out there; a project's Claude
// button goes to its node's sign-in when that node has none; and an account
// that does not administer sees a node's settings and changes nothing on it
// but its own sign-in.
//
// Driven against a node this file plays the agent for: it enrolls one, takes
// the sign-in's job the way an agent would, posts the flow's output as that
// job's log and reads the code coming back down. No job here ever runs on a
// real agent, which would find the machine's real Claude Code.
import { launch, newPage, ok, done, ready, sleep, refreshUntil, URL, DIR } from './lib.mjs';
import { readFileSync } from 'node:fs';

const BASE = URL.replace(/\/$/, '');
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const call = async (path, body, hdrs) => {
  const r = await fetch(BASE + path, { method: body ? 'POST' : 'GET', headers: { ...H, ...(hdrs || {}) },
    ...(body ? { body: JSON.stringify(body) } : {}) });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};
const uidOf = n => JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users[n].uid;
const me = uidOf('test');

// ---- a node of this file's own ----------------------------------------------
const box = await call('/api/v1/nodes', { action: 'enroll', name: 'signbox' });
const SE = { up: true, port: 7681, ro_port: 7682, user: 'bb', workspace: true, writable: true, boot: '4.4', up_s: 5000, claude: '1.0.0 (Claude Code)' };
const agent = await call('/api/v1/agent/enroll',
  { user: 'bb', version: 'harness', census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', session: SE } },
  { Authorization: 'Bearer ' + box.token });
const asNode = { Authorization: 'Bearer ' + agent.token };
// The heartbeat, which is also how an agent takes its next job: what it says
// about sessions and logins rides the sample.
// ...with each project's synced copy there (R163), as an agent says.
const beat = (sample = {}) => call('/api/v1/agent/work', { sample: { cpu_pct: 1, mem_mb: 4096, mem_used_mb: 512,
  sync: { alpha: { ready: true, rev: 1 }, beta: { ready: true, rev: 1 }, gamma: { ready: true, rev: 1 }, delta: { ready: true, rev: 1 } }, ...sample }, running: [], wait: 0 }, asNode);
await beat({ sessions: [] });
await call('/api/prefs', { project: 'beta', node: box.id });
const sandbox = ((await call('/api/v1/nodes')).nodes || []).find(n => n.name === 'sandbox');

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
const block = () => page.$eval(`.ndrow[data-node="${box.id}"] [data-signin]`, e => e.textContent.replace(/\s+/g, ' ').trim());
const redraw = () => page.evaluate(async () => { await refresh(); nodesRev++; drawPanes(); });

// ---- a Claude press on a node with no sign-in offers that node's sign-in ----
await refreshUntil(page, () => (state?.projects || []).find(p => p.name === 'beta')?.session_node);
ok(await page.evaluate(([a, b]) => !!claudeOn(a) && !claudeOn(b), [sandbox.id, box.id]),
   'signed in on one node is not signed in on another: each is asked about by itself');
// The project's Claude button is on its card on the Projects page (R218 step 3).
await page.evaluate(() => openProjectsTab());
await page.waitForSelector('.pgrid .pcard[data-row="beta"] [data-c]', { timeout: 15000 });
const PC = '.pgrid .pcard[data-row="beta"] [data-c]';
const btn = await page.$eval(PC, b => ({ dead: b.disabled, tip: saidOf(b) }));
ok(!btn.dead && /not signed in on signbox/.test(btn.tip) && /Press for its sign-in/.test(btn.tip),
   `the Claude button of a project whose node has no sign-in stays live and says what a press offers (${btn.tip})`);
await page.evaluate(id => { openNodesTab(); nodesPick = id; sectOpen['nodes:claude'] = false; nodesRev++; drawPanes(); }, sandbox.id);
await page.waitForSelector(`.ndrow[data-node="${sandbox.id}"]`, { timeout: 20000 });
const terms = () => page.evaluate(() => tabs.filter(t => t.kind === 'term').length);
const before = await terms();
await page.evaluate(() => openProjectsTab());
await page.click(PC);
await page.waitForSelector('#resumemenu [data-signin-node]', { timeout: 20000 });
const menu = await page.$eval('#resumemenu', m => ({ text: m.textContent.replace(/\s+/g, ' ').trim(),
  buttons: [...m.querySelectorAll('button')].map(b => b.textContent.trim()) }));
ok(/^signbox\b[\s\S]*You are not signed in to Claude here\./.test(menu.text) && menu.buttons.join() === 'Sign in on signbox',
   `pressing it opens the chooser with that node's sign-in as its one press, in place of Resume and New conversation (${menu.buttons.join(' | ')})`);
await page.click('#resumemenu [data-signin-node]');
await page.waitForFunction(id => {
  const s = document.querySelector(`.ndrow[data-node="${id}"] [data-sect="nodes:claude"]`);
  return !!s && s.open && !!s.querySelector('[data-signin]');
}, box.id, { timeout: 20000 });
ok(await page.$eval('#ndPick', s => s.selectedOptions[0].textContent).then(t => /^signbox/.test(t)) && await terms() === before
   && await page.$('#resumemenu') === null,
   '...which opens the Nodes tab on that node with its Claude Code section unfolded, and starts no session');
await page.evaluate(() => startClaude('beta', null, ''));
ok(/sign in to Claude on signbox first/.test(await page.$eval('#toast', e => e.textContent)) && await terms() === before,
   'anything else that would start a session there is sent to the same sign-in, with a line saying why');
ok(/You are not signed in to Claude on signbox: your sessions will not start here/.test(await block())
   && await page.$eval(`[data-signin="${box.id}"] [data-si="in"]`, b => !b.disabled && b.classList.contains('primary') && b.textContent.trim() === 'Sign in'),
   'the section says this account is not signed in on this node, with Sign in as its one press');

// ---- signing in, on this node ---------------------------------------------
await page.click(`[data-signin="${box.id}"] [data-si="in"]`);
await page.waitForFunction(id => state?.signin?.running && state.signin.node === id, box.id, { timeout: 20000 });
const job = await beat();          // the agent takes it
ok(job.type === 'claude-login' && job.spec?.uid === me && /^bbs_/.test(job.spec?.token || ''),
   `Sign in queues a claude-login job on that node, for this account, with a token to report with (${job.type || job.error})`);
ok(/Starting the sign-in on signbox/.test(await block())
   && await page.$eval('#authCode', f => f.disabled),
   'until the flow has printed its link the row says it is starting, and the code field waits');
const log = (seq, chunk) => call('/api/v1/agent/log', { job: job.id, chunks: chunk ? [{ seq, chunk }] : [] }, asNode);
await log(1, 'Opening browser to sign in...\nIf the browser did not open, visit: https://claude.com/cai/oauth/authorize?code=true&state=abc\nPaste code here if prompted > ');
await page.waitForFunction(() => !!document.querySelector('[data-signin] a[href^="https://claude.com/"]')
                                 && !document.getElementById('authCode')?.disabled, null, { timeout: 20000 });
ok(await page.$eval('[data-signin] a', a => a.target === '_blank' && /authorize\?code=true/.test(a.href))
   && await page.$eval('#bAuthCode', b => !b.disabled),
   'the link the flow printed is a link to tap, and the code field and Send come alive when it asks');
// What is half typed survives the repaint a heartbeat brings, focus included.
await page.click('#authCode');
await page.keyboard.type('abc#de');
await page.evaluate(() => { nodesRev++; drawPanes(); });
const kept = await page.evaluate(() => ({ value: document.getElementById('authCode').value, active: document.activeElement?.id || document.activeElement?.tagName,
  n: document.querySelectorAll('#authCode').length, held: signinCode }));
ok(kept.value === 'abc#de' && kept.active === 'authCode',
   `a repaint under a half-typed code keeps the text and the focus (${JSON.stringify(kept)})`);
await page.keyboard.type('f');
await page.keyboard.press('Enter');
const down = await (async () => { for (let i = 0; i < 40; i++){ const r = await log(0, ''); if (r.input) return r.input; await sleep(250); } return ''; })();
ok(down === 'abc#def', `Enter sends the code, which goes down to the node on the job's own channel (${down})`);
// The flow ends and the node says who signed in: its heartbeat, the way an
// agent says it after the job.
await call('/api/v1/agent/result', { job: job.id, state: 'succeeded', exit: 0 }, asNode);
await beat({ logins: [{ uid: me, email: 'me@example.invalid' }] });
await redraw();
await page.waitForFunction(id => /You are signed in here as me@example\.invalid/.test(
  document.querySelector(`[data-signin="${id}"]`)?.textContent || ''), box.id, { timeout: 20000 });
ok(await page.$eval(`[data-signin="${box.id}"] [data-si="out"]`, b => !b.disabled)
   && !await page.$('#authCode'),
   'signed in, the row names the Anthropic account this node reported and offers Sign out');
ok(await page.evaluate(([a, b]) => claudeOn(a)?.email === 'tester@example.com' && claudeOn(b)?.email === 'me@example.invalid', [sandbox.id, box.id]),
   '...and another node\'s sign-in is its own: a different Anthropic account there is not this one\'s business');
const tip = await page.$eval(PC, b => saidOf(b));
ok(!/not signed in/.test(tip) && await page.evaluate(id => claudeSigninFirst('beta', id), box.id) === false,
   `the project's Claude button goes to a session again (${tip.slice(0, 50)})`);

// ---- signing out, on this node ----------------------------------------------
// Not while this account's own session is open there, said on the row.
await beat({ sessions: [{ name: `${me}~claude-beta`, attached: false, cwd: '/workspace/beta', title: '' }] });
await redraw();
await page.waitForFunction(id => document.querySelector(`[data-signin="${id}"] [data-si="out"]`)?.disabled, box.id, { timeout: 20000 });
ok(/End your Claude session on beta before signing out here/.test(await block()),
   'Sign out is dead while this account has a Claude session open on the node, and the row says which');
await beat({ sessions: [] });
await redraw();
await page.waitForFunction(id => document.querySelector(`[data-signin="${id}"] [data-si="out"]`)?.disabled === false, box.id, { timeout: 20000 });
const nd = page.dialogs.length;
await page.click(`[data-signin="${box.id}"] [data-si="out"]`);
await page.waitForFunction(id => /You are not signed in to Claude on signbox/.test(
  document.querySelector(`[data-signin="${id}"]`)?.textContent || ''), box.id, { timeout: 20000 });
const oj = await beat();
ok(page.dialogs.length === nd + 1 && /Sign out of Claude on signbox\?/.test(page.dialogs[nd]) && /any other node stays/.test(page.dialogs[nd])
   && oj.type === 'claude-logout' && oj.spec?.uid === me,
   `Sign out asks first, naming the node, and is a claude-logout job there for this account (${oj.type || oj.error})`);
ok(await page.evaluate(([a, b]) => claudeOn(a)?.email === 'tester@example.com' && !claudeOn(b), [sandbox.id, box.id]),
   '...and the sign-in on the other node is untouched');
await call('/api/v1/agent/result', { job: oj.id, state: 'succeeded', exit: 0 }, asNode);

// ---- a sign-in that did not finish, and a node that takes no work -----------
await page.click(`[data-signin="${box.id}"] [data-si="in"]`);
await page.waitForFunction(id => state?.signin?.running && state.signin.node === id, box.id, { timeout: 20000 });
const j2 = await beat();
await call('/api/v1/agent/log', { job: j2.id, chunks: [{ seq: 1, chunk: 'Login failed: Request failed with status code 400\n' }] }, asNode);
await call('/api/v1/agent/result', { job: j2.id, state: 'failed', exit: 1, error: 'exit 1' }, asNode);
await redraw();
await page.waitForFunction(id => /Login failed: Request failed with status code 400/.test(
  document.querySelector(`[data-signin="${id}"]`)?.textContent || ''), box.id, { timeout: 20000 });
ok(await page.$eval(`[data-signin="${box.id}"] [data-si="in"]`, b => b.textContent.trim() === 'Try again' && !b.disabled),
   'a sign-in that ended without signing in says why on the row, in the flow\'s own words, with Try again');
await call('/api/v1/nodes', { action: 'drain', id: box.id });
await page.evaluate(() => loadNodes());
await page.waitForFunction(id => document.querySelector(`[data-signin="${id}"] [data-si="in"]`)?.disabled, box.id, { timeout: 20000 });
const drained = await call('/api/signin', { node: box.id });
ok(/signbox is draining and takes no new work/.test(await block()) && drained.status === 400 && /draining/.test(drained.error || ''),
   `a node that takes no work offers no sign-in, with the reason on the row, and the server says the same (${drained.error})`);
await call('/api/v1/nodes', { action: 'online', id: box.id });

// ---- an account that does not administer ------------------------------------
// It is shown the nodes its own projects work on, their settings ghosted,
// and its own sign-in live: the one thing on the tab that is its to change.
await call('/api/users', { action: 'add', name: 's.user', password: 's.user-pass-1', role: 'user' });
await call('/api/users', { action: 'projects', name: 's.user', projects: ['beta'] });
// ...with the name and email its commits carry, which a session waits for.
await call('/api/users', { action: 'edit', name: 's.user', profile: { full_name: 'S User', email: 's.user@example.invalid' } });
{
  const auth = 'Basic ' + Buffer.from('s.user:s.user-pass-1').toString('base64');
  const up = await newPage(browser, { viewport: { width: 1280, height: 1000 },
    httpCredentials: { username: 's.user', password: 's.user-pass-1' }, extraHTTPHeaders: { Authorization: auth } });
  await up.goto(URL);
  await ready(up);
  // A new account's first page opens the welcome panel over everything.
  await up.waitForSelector('#aboutModal:not([hidden])', { timeout: 15000 }).then(() => up.evaluate(() => closeAbout()), () => {});
  await up.waitForSelector('#aboutModal', { state: 'hidden', timeout: 15000 });
  // A new account pins what it wants (the operator, 7 Oct): beta, here.
  await up.evaluate(() => fetch('/api/project-pin', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'beta', pinned: true }) }));
  await refreshUntil(up, () => (state?.projects || []).some(p => p.name === 'beta' && p.session_node)
                               && document.querySelector('.pgrid .pcard[data-row="beta"] [data-c]')?.disabled === false);
  await up.click('.pgrid .pcard[data-row="beta"] [data-c]');
  await up.click('#resumemenu [data-signin-node]');
  await up.waitForSelector(`.ndrow[data-node="${box.id}"] [data-signin]`, { timeout: 20000 });
  const seen = await up.evaluate(() => {
    const root = document.querySelector('.doc .ndrow').closest('.doc');
    const all = [...root.querySelectorAll('button, input, select, textarea')];
    const mine = c => c.id === 'ndPick' || !!c.closest('[data-signin]');
    return { picker: [...document.querySelectorAll('#ndPick option')].map(o => o.textContent.split(':')[0]),
             live: all.filter(c => !c.disabled).map(c => c.id || c.dataset.si || c.dataset.nd || c.textContent.trim().slice(0, 20)),
             others: all.filter(c => !mine(c)).length, ghosted: all.filter(c => !mine(c) && c.disabled).length,
             toolchains: !!root.querySelector('[data-ndtc]'),
             enroll: root.querySelector('#ndEnroll')?.disabled,
             why: root.querySelector('.ndreadonly')?.textContent || '',
             open: root.querySelector('[data-sect="nodes:claude"]')?.open };
  });
  const cc = await up.evaluate(async () => (await (await fetch('/api/status')).json()).claude_code || {});
  ok(Object.keys(cc.nodes || {}).join() === box.id && 'latest' in cc,
     `the Claude Code versions it is sent are those nodes' too, so the section reads what an administrator's does (${Object.keys(cc.nodes || {}).length} node)`);
  ok(seen.picker.join() === 'signbox', `its node picker lists the nodes its own projects are on, and no others (${seen.picker.join()})`);
  ok(seen.open && seen.live.includes('in') && seen.live.includes('ndPick'),
     `its chooser's sign-in lands on the same section, where its own Sign in is live (${seen.live.join()})`);
  ok(seen.others > 5 && seen.ghosted === seen.others && !seen.toolchains && seen.enroll === true,
     `every other control on the tab is ghosted for it, enrolling included, and no way to the Toolchains tab (${seen.ghosted} of ${seen.others})`);
  ok(/An administrator changes a node's settings/.test(seen.why) && /Your Claude sign-in here/.test(seen.why),
     '...and the row says why, and what is still theirs');
  // Its sign-in works: the job is for that account, on its project's node.
  await up.click(`[data-signin="${box.id}"] [data-si="in"]`);
  await up.waitForFunction(id => state?.signin?.running && state.signin.node === id, box.id, { timeout: 20000 });
  const uj = await beat();
  ok(uj.type === 'claude-login' && uj.spec?.uid === uidOf('s.user'),
     `its Sign in starts the flow on that node for that account (${uj.type || uj.error})`);
  ok(await page.evaluate(async () => (await (await fetch('/api/status')).json()).signin?.running) === false,
     '...and the flow, with the link it will print, is not shown to anybody else');
  await up.click(`[data-signin="${box.id}"] [data-si="cancel"]`);
  await up.waitForFunction(() => !state?.signin?.running, null, { timeout: 20000 });
  const told = await call('/api/v1/agent/log', { job: uj.id, chunks: [] }, asNode);
  ok(told.cancel === true, 'Cancel tells the node to stop the flow, on the job\'s own channel');
  await call('/api/v1/agent/result', { job: uj.id, state: 'canceled', exit: 130 }, asNode);
  ok(/You are not signed in to Claude on signbox/.test(await up.$eval('[data-signin]', e => e.textContent)),
     'Cancel stops the flow and the row is back to where it was');
  // ...and the settings it can see are refused by the server too, not only
  // ghosted on the page.
  const denied = await up.evaluate(async id => (await fetch('/api/toolchains', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'install', node: id, names: ['claude-code'] }) })).status, box.id);
  ok(denied === 403, `the verbs behind the ghosted controls are an administrator's on the server as well (${denied})`);
  up.errors = [];
  await up.context().close();
}

await call('/api/prefs', { project: 'beta', node: '' });
await call('/api/v1/nodes', { action: 'retire', id: box.id });
ok(page.errors.length === 0, `the administrator's page logged no error through any of it (${page.errors.slice(0, 2).join(' | ')})`);
await done(browser);
