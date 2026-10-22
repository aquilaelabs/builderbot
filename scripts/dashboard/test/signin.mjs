// The Claude sign-in (signin.py, claudegrant.py, page-signin.js): one
// account's, on one node. A person signs in on each node they work on, from
// that node's Agents page (R95 step 15), and signs out there; a project's Claude
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
// Codex CLI installed beside Claude Code, as its census says it (R95 step 3).
const SE = { up: true, port: 7681, ro_port: 7682, user: 'bb', workspace: true, writable: true, boot: '4.4', up_s: 5000, claude: '1.0.0 (Claude Code)',
             codex: 'codex-cli 0.163.0' };
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
const block = () => page.$eval(`.agentstab [data-signin="${box.id}"]`, e => e.textContent.replace(/\s+/g, ' ').trim());
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
await page.evaluate(id => { sectOpen['agents:claude'] = false; openAgentsOn(id); }, sandbox.id);
await page.waitForSelector(`.agentstab [data-agnode="${sandbox.id}"]`, { timeout: 20000 });
const terms = () => page.evaluate(() => tabs.filter(t => t.kind === 'term').length);
const before = await terms();
await page.evaluate(() => openProjectsTab());
await page.click(PC);
await page.waitForSelector('#resumemenu [data-signin-node]', { timeout: 20000 });
const menu = await page.$eval('#resumemenu', m => ({ text: [...m.querySelectorAll('.rmhead b, .rmfacts, div.rmstate')].map(e => e.textContent.trim()).join(' | '),
  buttons: [...m.querySelectorAll('button:not([data-asignin])')].map(b => b.textContent.trim()),
  // Codex CLI is installed there too (R95 step 4): its own line, its own sign-in.
  codex: [...m.querySelectorAll('[data-asignin="codex"]')].map(b => b.closest('.actbar').textContent.replace(/\s+/g, ' ').trim()) }));
ok(/^signbox \|[\s\S]*You are not signed in to Claude here$/.test(menu.text) && menu.buttons.join() === 'Sign in on signbox',
   `pressing it opens the chooser with that node's sign-in as its one press, in place of Resume and New conversation (${menu.text}; ${menu.buttons.join(' | ')})`);
ok(menu.codex.length === 1 && /^ChatGPT\s*Sign in on signbox$/.test(menu.codex[0]),
   `...and a line for ChatGPT under it, Codex CLI being installed there, offering its own sign-in (${menu.codex.join(' | ')})`);
await page.click('#resumemenu [data-signin-node]');
await page.waitForFunction(id => {
  const s = document.querySelector(`.agentstab [data-agnode="${id}"] [data-sect="agents:claude"]`);
  return !!s && s.open && !!s.querySelector('[data-signin]');
}, box.id, { timeout: 20000 });
ok(await page.$eval('#agNodeSel', s => s.selectedOptions[0].textContent).then(t => /^signbox/.test(t)) && await terms() === before
   && await page.$('#resumemenu') === null && /#\/build\/agents\//.test(await page.evaluate(() => location.hash)),
   '...which opens the Agents page on that node with its Claude section unfolded, and starts no session');
// The page holds every coding agent the table installs, in its order, each
// saying where it stands on this node (R95 step 15).
const secs = await page.$$eval(`.agentstab [data-agnode="${box.id}"] details.sect`, ds => ds.map(d =>
  [d.dataset.sect, d.querySelector('summary .sst')?.textContent.trim() || '']));
ok(secs.map(s => s[0]).join() === 'agents:claude,agents:codex,agents:copilot'
   && /^1\.0\.0/.test(secs[0][1]) && /not signed in/.test(secs[0][1]) && /^0\.163\.0, not signed in/.test(secs[1][1])
   && secs[2][1] === 'not installed',
   `the Agents page has a section per coding agent, Claude first, each with where it stands here (${JSON.stringify(secs)})`);
await page.evaluate(() => startClaude('beta', null, ''));
ok(/sign in to Claude on signbox first/.test(await page.$eval('#toast', e => e.textContent)) && await terms() === before,
   'anything else that would start a session there is sent to the same sign-in, with a line saying why');
ok(/You are not signed in to Claude on signbox: your Claude sessions will not start here/.test(await block())
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
// The page is drawn while it is on show: brought to the front, it reads the
// sign-in that just landed.
await page.evaluate(() => openProjectsTab());
await page.waitForFunction(sel => !/not signed in/.test(saidOf(document.querySelector(sel))), PC, { timeout: 15000 }).catch(() => {});
const tip = await page.$eval(PC, b => saidOf(b));
ok(!/not signed in/.test(tip) && await page.evaluate(id => claudeSigninFirst('beta', id), box.id) === false,
   `the project's Claude button goes to a session again (${tip.slice(0, 50)})`);
await page.evaluate(id => openAgentsOn(id), box.id);   // back to the node's Agents page

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

// ---- another coding agent's sign-in, on this node (R95 step 3) --------------
// ChatGPT's, for Codex CLI: a device flow, so the section shows the link and
// the one-time code the flow printed, for the person to enter on OpenAI's
// page; nothing is pasted back. The node's report names the account.
{
  const CX = `.agentstab [data-signin="${box.id}"][data-siagent="codex"]`;
  await page.evaluate(id => openAgentsOn(id), box.id);
  await page.waitForSelector(`${CX} [data-si="in"]`, { timeout: 20000 });
  ok(/You are not signed in to ChatGPT on signbox/.test(await page.$eval(CX, e => e.textContent)),
     'the ChatGPT section holds its own sign-in, beside Claude\'s, saying this account has none here');
  await page.click(`${CX} [data-si="in"]`);
  await page.waitForFunction(id => state?.signin?.running && state.signin.node === id && state.signin.agent === 'codex', box.id, { timeout: 20000 });
  const cj = await beat();
  ok(cj.type === 'codex-login' && cj.spec?.uid === me && cj.spec?.agent === 'codex',
     `Sign in queues a codex-login job on that node, for this account (${cj.type || cj.error})`);
  await call('/api/v1/agent/log', { job: cj.id, chunks: [{ seq: 1, chunk:
    'Welcome to Codex [v0.163.0]\nFollow these steps to sign in with ChatGPT using device code authorization:\n'
    + '1. Open this link in your browser and sign in to your account\n   https://auth.openai.com/codex/device\n'
    + '2. Enter this one-time code (expires in 15 minutes)\n   ABCD-1234\n' }] }, asNode);
  await page.waitForFunction(sel => document.querySelector(sel + ' .sicode')?.textContent === 'ABCD-1234', CX, { timeout: 20000 });
  ok(await page.$eval(`${CX} a`, a => a.href === 'https://auth.openai.com/codex/device' && a.target === '_blank')
     && !await page.$(`${CX} #authCode`),
     'the section shows the link to OpenAI\'s page and the code to enter there, and no field to paste one back');
  await call('/api/v1/agent/result', { job: cj.id, state: 'succeeded', exit: 0 }, asNode);
  await beat({ logins: [{ uid: me, email: '', agents: { codex: { email: 'me@openai.invalid', plan: 'plus' } } }] });
  await redraw();
  await page.waitForFunction(sel => /You are signed in here as me@openai\.invalid · plus/.test(document.querySelector(sel)?.textContent || ''),
                             CX, { timeout: 20000 });
  ok(await page.evaluate(id => agentOn('codex', id)?.email === 'me@openai.invalid' && !claudeOn(id), box.id),
     '...and the node\'s report names the ChatGPT account, which is no Claude sign-in');
  const n0 = page.dialogs.length;
  await page.click(`${CX} [data-si="out"]`);
  // The press asks first and then queues the job: taken once it is there.
  let xo = {};
  for (let i = 0; i < 40 && !xo?.type; i++){ xo = await beat(); if (!xo?.type) await sleep(250); }
  ok(page.dialogs.length === n0 + 1 && /Sign out of ChatGPT on signbox\?/.test(page.dialogs[n0])
     && xo.type === 'codex-logout' && xo.spec?.uid === me,
     `Sign out asks first and is a codex-logout job there for this account (${xo.type || xo.error})`);
  await call('/api/v1/agent/result', { job: xo.id, state: 'succeeded', exit: 0 }, asNode);
}

// ---- an account that does not administer ------------------------------------
// It is shown the nodes its own projects work on, no install or update, and
// its own sign-in live: the one thing on the page that is its to change.
await call('/api/users', { action: 'add', name: 's.user', password: 's.user-pass-1', role: 'user' });
await call('/api/users', { action: 'projects', name: 's.user', projects: ['beta'] });
// A Claude session is work on the project, so it holds Projects Write there,
// and a terminal to watch it in (B86: Start Claude is dead without them).
await call('/api/roles', { action: 'set', name: 'si-worker', scope: 'projects', perms: { projects: 'write', terminal: 'write' } });
await call('/api/roles', { action: 'assign', name: 's.user', project_roles: { beta: ['si-worker'] } });
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
  await up.waitForSelector(`.agentstab [data-signin="${box.id}"]`, { timeout: 20000 });
  const seen = await up.evaluate(() => {
    const root = document.querySelector('.agentstab').closest('.doc');
    const all = [...root.querySelectorAll('button, input, select, textarea')];
    return { picker: [...document.querySelectorAll('#agNodeSel option')].map(o => o.textContent.split(':')[0]),
             live: all.filter(c => !c.disabled).map(c => c.id || c.dataset.si || c.dataset.agact || c.textContent.trim().slice(0, 20)),
             installs: root.querySelectorAll('[data-agact]').length,
             said: root.querySelector('[data-sect="agents:claude"]')?.textContent.replace(/\s+/g, ' ') || '',
             open: root.querySelector('[data-sect="agents:claude"]')?.open };
  });
  const cc = await up.evaluate(async () => (await (await fetch('/api/status')).json()).claude_code || {});
  ok(Object.keys(cc.nodes || {}).join() === box.id && 'latest' in cc,
     `the Claude Code versions it is sent are those nodes' too, so the section reads what an administrator's does (${Object.keys(cc.nodes || {}).length} node)`);
  ok(seen.picker.join() === 'signbox', `its node picker lists the nodes its own projects are on, and no others (${seen.picker.join()})`);
  ok(seen.open && seen.live.includes('in') && seen.live.includes('agNodeSel'),
     `its chooser's sign-in lands on the same section, where its own Sign in is live (${seen.live.join()})`);
  ok(seen.installs === 0 && !/administrator/i.test(seen.said),
     `it is offered no install, update or removal, and nothing says why (the operator, 21 Oct: a role somebody lacks is not advertised) (${seen.installs})`);
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
