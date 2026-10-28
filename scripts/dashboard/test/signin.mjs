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
const SE = { up: true, term: true, user: 'bb', workspace: true, writable: true, boot: '4.4', up_s: 5000, claude: '1.0.0 (Claude Code)',
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
// Since R170 a node's sign-in lives on the Library, on the agent's card, opened by the door that names it.
const block = () => page.$eval(`.installedtab .irow.open [data-signin="${box.id}"][data-siagent="claude"]`, e => e.textContent.replace(/\s+/g, ' ').trim());
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
await page.evaluate(id => { instOpen.clear(); openInstalledOn(id); }, sandbox.id);
await page.waitForSelector(`.installedtab [data-instnode="${sandbox.id}"]`, { timeout: 20000 });
const terms = () => page.evaluate(() => tabs.filter(t => t.kind === 'term').length);
const before = await terms();
await page.evaluate(() => openProjectsTab());
await page.click(PC);
await page.waitForSelector('#resumemenu [data-signin-node]', { timeout: 20000 });
const menu = await page.$eval('#resumemenu', m => ({ head: m.querySelector('.rmhead b')?.textContent.trim() || '',
  lines: [...m.querySelectorAll('.rmline')].map(l => `${[...l.querySelector('.rmwho').children].map(e => e.textContent.trim()).join(' ')}: ${
    [...l.querySelectorAll('button')].map(b => b.textContent.trim()).join('/')}`) }));
// Start is one line, the agents installed there a pulldown (the operator,
// 26 Oct): Claude first with its sign-in in place of New, and ChatGPT among
// them, Codex CLI being there too, with its own sign-in once picked.
const startOf = () => page.$eval('#resumemenu', m => { const l = m.querySelector('.rmline:has(#rmAgentSel)');
  return { agents: [...(m.querySelector('#rmAgentSel')?.options || [])].map(o => o.textContent.trim()),
           said: l?.querySelector('.rmsays')?.textContent.trim() || '', press: [...(l?.querySelectorAll('button') || [])].map(b => b.textContent.trim()).join('/'),
           sign: l?.querySelector('[data-signin-node], [data-asignin]')?.dataset.asignin || (l?.querySelector('[data-signin-node]') ? 'claude' : '') }; });
const start = await startOf();
ok(menu.head === 'signbox' && start.agents[0] === 'Claude' && start.said === 'not signed in here' && start.press === 'Sign in' && start.sign === 'claude',
   `pressing it opens the chooser with that node's sign-in as Claude's one press, in place of New (${menu.head}; ${JSON.stringify(start)})`);
await page.selectOption('#resumemenu #rmAgentSel', { label: 'ChatGPT' });
await page.waitForFunction(() => document.querySelector('#resumemenu #rmAgentSel')?.selectedOptions[0]?.textContent.trim() === 'ChatGPT', null, { timeout: 5000 });
const gpt = await startOf();
ok(start.agents.includes('ChatGPT') && gpt.said === 'not signed in here' && gpt.press === 'Sign in' && gpt.sign === 'codex',
   `...and ChatGPT among the agents, Codex CLI being installed there, offering its own sign-in once picked (${JSON.stringify(gpt)})`);
await page.selectOption('#resumemenu #rmAgentSel', { label: 'Claude' });
await page.click('#resumemenu [data-signin-node]');
await page.waitForFunction(id => {
  const s = document.querySelector(`.installedtab [data-instnode="${id}"] .irow.open [data-signin][data-siagent="claude"]`);
  return !!s;
}, box.id, { timeout: 20000 });
ok(await page.$eval('#instNodeSel', s => s.selectedOptions[0].textContent).then(t => /^signbox/.test(t)) && await terms() === before
   && await page.$('#resumemenu') === null && /#\/machines\/installed\//.test(await page.evaluate(() => location.hash)),
   '...which opens the Installed page on that node with Claude Code\'s row open on its sign-in, and starts no session');
// The page holds the coding agents installed on the node, and Claude Code
// whether or not it is, in the table's order, each saying where it stands
// (R95 step 15, R172): here Claude Code and Codex CLI are installed.
const secs = await page.evaluate(id => [...document.querySelectorAll(`.installedtab [data-instnode="${id}"] .irow[data-irow^="agent:"]`)].map(c => {
  const r = inst.rows.find(x => `${x.kind}:${x.name}` === c.dataset.irow);
  return [r.agent, [...c.querySelectorAll('.name .pill')].map(p => p.textContent.trim()).join(', '), c.querySelector('.acts .state')?.textContent.trim() || ''];
}), box.id);
ok(secs.map(s => s[0]).join() === 'claude,codex'
   && /\b1\.0\.0\b/.test(secs[0][1]) && /not signed in/.test(await block()) && /\b0\.163\.0\b/.test(secs[1][1])
   && /installed/.test(secs[0][2]) && /installed/.test(secs[1][2]),
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
await page.evaluate(id => openInstalledOn(id, 'claude'), box.id);   // back to the node's Installed page, Claude's row open

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
  const CX = `.installedtab .irow.open [data-signin="${box.id}"][data-siagent="codex"]`;
  await page.evaluate(id => openInstalledOn(id, 'codex'), box.id);
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

// ---- the agent a project's Start opens (R95 step 4) --------------------------
{
  const set = await call('/api/prefs', { project: 'beta', agent_default: 'codex' });
  await page.evaluate(() => openProjectsTab());
  // One word on every card (the operator, 22 Oct): Start agent, the agent it
  // opens named in its title and first in its chooser.
  await refreshUntil(page, () => (b => !!b && /^ChatGPT:/.test(saidOf(b)))(document.querySelector('.pgrid .pcard[data-row="beta"] [data-c]')));
  ok(!set.error && await page.$eval(PC, b => b.textContent.trim() === 'Start agent' && /^ChatGPT:/.test(saidOf(b))),
     `a project whose settings name ChatGPT says Start agent on its card, its title naming ChatGPT (${set.error || 'saved'})`);
  // Every agent in the table starts a session now (Any model since R144), so
  // the one that cannot is one the table does not have.
  const refused = await call('/api/prefs', { project: 'beta', agent_default: 'nope' });
  ok(refused.status === 400 || /agent_default is one of/.test(refused.error || ''),
     `...and an agent that cannot start a session is refused as the one Start opens (${refused.error})`);
  await call('/api/prefs', { project: 'beta', agent_default: 'claude' });
  await refreshUntil(page, () => (b => !!b && /^Claude:/.test(saidOf(b)))(document.querySelector('.pgrid .pcard[data-row="beta"] [data-c]')));
  // Who may (R95 step 10): an agent a project switches off is offered
  // nowhere there, and its terminal is refused on the server whoever asks.
  await call('/api/prefs', { project: 'beta', agents_off: 'codex' });
  await refreshUntil(page, () => ((state?.projects || []).find(p => p.name === 'beta')?.prefs?.agents_off || []).includes('codex'));
  const term = await page.evaluate(async () => {
    const r = await fetch('/termws?arg=' + encodeURIComponent('codex:beta'), { headers: { Accept: 'application/json' } });
    return { status: r.status, error: (await r.json().catch(() => ({}))).error || '' };
  });
  await page.evaluate(() => openProjectsTab());
  await page.click(PC);
  await page.waitForSelector('#resumemenu', { timeout: 15000 });
  const offeredCodex = await page.$('#resumemenu [data-asignin="codex"], #resumemenu [data-anew="codex"]');
  await page.evaluate(() => { resumeFor = null; drawProjects(state.projects); });
  ok(term.status >= 400 && /do not allow ChatGPT sessions/.test(term.error) && !offeredCodex,
     `an agent the project switches off is refused at its terminal and missing from its chooser (${term.status} ${term.error.slice(0, 60)})`);
  await call('/api/prefs', { project: 'beta', agents_off: '' });
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
  await up.waitForSelector(`.installedtab .irow.open [data-signin="${box.id}"][data-siagent="claude"]`, { timeout: 20000 });
  const seen = await up.evaluate(() => {
    const root = document.querySelector('.installedtab').closest('.doc');
    const all = [...root.querySelectorAll('button, input, select, textarea')];
    const card = root.querySelector('.irow.open[data-irow="agent:claude-code"]');
    return { picker: [...document.querySelectorAll('#instNodeSel option')].map(o => o.textContent.split(':')[0]),
             live: all.filter(c => !c.disabled).map(c => c.id || c.dataset.si || c.dataset.instact || c.textContent.trim().slice(0, 20)),
             installs: root.querySelectorAll('[data-instact]').length,
             said: card?.textContent.replace(/\s+/g, ' ') || '',
             open: !!card };
  });
  const cc = await up.evaluate(async () => (await (await fetch('/api/status')).json()).claude_code || {});
  ok(Object.keys(cc.nodes || {}).join() === box.id && 'latest' in cc,
     `the Claude Code versions it is sent are those nodes' too, so the section reads what an administrator's does (${Object.keys(cc.nodes || {}).length} node)`);
  ok(seen.picker.join() === 'signbox', `its node picker lists the nodes its own projects are on, and no others (${seen.picker.join()})`);
  ok(seen.open && seen.live.includes('in') && seen.live.includes('instNodeSel'),
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
  const denied = await up.evaluate(async id => (await fetch('/api/agents', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'install', node: id, agent: 'claude' }) })).status, box.id);
  ok(denied === 403, `the verbs behind the ghosted controls are an administrator's on the server as well (${denied})`);
  up.errors = [];
  await up.context().close();
}

await call('/api/prefs', { project: 'beta', node: '' });
await call('/api/v1/nodes', { action: 'retire', id: box.id });
ok(page.errors.length === 0, `the administrator's page logged no error through any of it (${page.errors.slice(0, 2).join(' | ')})`);
await done(browser);
