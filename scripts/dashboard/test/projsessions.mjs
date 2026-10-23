// Every account's sessions on a project, at the foot of its settings dialog,
// and an administrator ending one (projsessions.py; the operator, 24 Sep).
// A session is its account's (B172): nobody presses a key or types into
// another person's, administrators included, and that still holds. Ending
// one is the single exception, and an administrator's alone.
import { launch, newPage, ok, done, ready, tmuxNew, tmuxKill, URL, DIR } from './lib.mjs';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
            'Content-Type': 'application/json' };
const call = async (path, body, h = H) => {
  const r = await fetch(base + path, body ? { method: 'POST', headers: h, body: JSON.stringify(body) }
                                          : { headers: h });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};

// w.sess has sessions on alpha; w.watch is a plain account given alpha.
await call('/api/users', { action: 'add', name: 'w.sess', password: 'w.sess-pass-1', role: 'user' });
await call('/api/users', { action: 'add', name: 'w.watch', password: 'w.watch-pass-1', role: 'user' });
await call('/api/users', { action: 'projects', name: 'w.watch', projects: ['alpha'] });
const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users['w.sess'].uid;
const PLAIN = { Authorization: 'Basic ' + Buffer.from('w.watch:w.watch-pass-1').toString('base64'),
                'Content-Type': 'application/json' };

// w.sess's Claude session and a shell on alpha here, a Claude session on beta,
// and a shell on alpha on a node, reported the way an agent reports one.
const here = [`${uid}~claude-alpha`, `${uid}~shell-alpha-1`, `${uid}~claude-beta`];
here.forEach(n => tmuxNew(n));
const box = await call('/api/v1/nodes', { action: 'enroll', name: 'sessbox' });
const SE = { up: true, port: 7681, ro_port: 7682, user: 'bb', workspace: true, writable: true,
             boot: '3.3', up_s: 5000 };
const agent = await call('/api/v1/agent/enroll',
  { user: 'bb', version: 'harness', census: { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux', session: SE } },
  { ...H, Authorization: 'Bearer ' + box.token });
const nodeShell = `${uid}~shell-alpha-2`;
const beat = async () => {
  const r = await fetch(base + '/api/v1/agent/work', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + agent.token },
    body: JSON.stringify({ sample: { cpu_pct: 1, mem_mb: 4096, mem_used_mb: 512,
      sessions: [{ name: nodeShell, attached: false, cwd: '/workspace/alpha', title: '' }],
      // ...with each project's synced copy there (R163), as an agent says.
      sync: { alpha: { ready: true, rev: 1 }, beta: { ready: true, rev: 1 }, gamma: { ready: true, rev: 1 }, delta: { ready: true, rev: 1 } } },
      running: [], wait: 0 }) });
  return r.status === 200 ? r.json() : {};
};
await beat();

// ---- the list: an administrator's, and every account's ----------------------
const rows = (await call('/api/project-sessions?project=alpha')).sessions || [];
const row = n => rows.find(r => r.name === n);
ok(row(here[0]) && row(here[1]) && row(nodeShell)?.node_id === box.id,
   `an administrator sees every account's sessions on the project, here and on a node (${
     rows.map(r => r.name).join(', ')})`);
ok(row(here[0])?.who === 'w.sess' && row(here[0]).kind === 'claude' && row(here[1])?.kind === 'shell'
   && row(nodeShell)?.node === 'sessbox',
   `...each saying whose it is, what it is and where (${JSON.stringify(row(nodeShell))})`);
ok(!rows.some(r => /claude-beta/.test(r.name)), "...and none of another project's");

// ---- nobody else lists or ends them -------------------------------------------
const plainList = await call('/api/project-sessions?project=alpha', null, PLAIN);
const plainEnd = await call('/api/project-sessions', { project: 'alpha', action: 'end', session: here[0] }, PLAIN);
ok(plainList.status === 403 && plainEnd.status === 403,
   `a plain account can neither list them nor end one (${plainList.status}, ${plainEnd.status})`);
// A session's token is never an administrator's, whoever it was minted for.
const stok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
  { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
const asSession = await call('/api/project-sessions', { project: 'alpha', action: 'end', session: here[0] },
  { 'Content-Type': 'application/json', Authorization: 'Bearer ' + stok });
ok(asSession.status === 403, `...and neither can a session, the owner's included (${asSession.status})`);

// ---- ending one: this project's, by an administrator -------------------------
const wrong = await call('/api/project-sessions', { project: 'alpha', action: 'end', session: here[2] });
ok(wrong.status === 400 && /no such session on this project/.test(wrong.error || ''),
   `another project's session cannot be ended from this one (${wrong.error})`);
const keys = await call('/api/keys', { session: here[0], key: 'enter' });
ok(keys.status === 403, `a key in another account's session is still refused, administrator or not (B172, ${keys.status})`);
const ended = await call('/api/project-sessions', { project: 'alpha', action: 'end', session: nodeShell, node: box.id });
const poll = await beat();
ok(ended.ok && ended.who === 'w.sess' && (poll.kill_sessions || []).includes(nodeShell),
   `an administrator ends one on a node, through its agent (${JSON.stringify(poll)})`);
ok(!((await call('/api/project-sessions?project=alpha')).sessions || []).some(r => r.name === nodeShell),
   '...and it leaves the list at once, not at the next heartbeat');

// ---- the owner's Claude on a node is the owner's alone ------------------------
// The owner's node sessions are drawn bare, by this container's rule, and by
// the bare name the status read them as unowned: an account given the
// project listed the owner's Claude as one of its own, on Sessions and in
// Sign out's count (the operator, 16 Oct).
{
  const ustate = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users;
  const ownerUid = Object.values(ustate).find(u => u.role === 'owner').uid;
  const sample = extra => fetch(base + '/api/v1/agent/work', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + agent.token },
    body: JSON.stringify({ sample: { cpu_pct: 1, mem_mb: 4096, mem_used_mb: 512, sessions: extra,
      sync: { alpha: { ready: true, rev: 1 } } }, running: [], wait: 0 }) });
  await sample([{ name: `${ownerUid}~claude-alpha`, attached: false, cwd: '/workspace/alpha', title: '' }]);
  const listed = async h => ((await call('/api/status', null, h)).sessions || [])
    .filter(x => x.node_id === box.id).map(x => x.name);
  const watch = await listed(PLAIN), own = await listed(H);
  ok(!watch.length && own.includes('claude-alpha'),
     `the owner's Claude session on a node is listed for the owner, bare, and for nobody else given the project (owner ${JSON.stringify(own)}, w.watch ${JSON.stringify(watch)})`);
  await sample([]);
}

// ---- the dialog: at its foot, for an administrator -----------------------------
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);
await page.evaluate(() => renameProject('alpha'));
await page.waitForFunction(() => !document.getElementById('rnSessField').hidden
  && document.querySelectorAll('#rnSessList .rnsess').length > 0, null, { timeout: 15000 });
const drawn = await page.$$eval('#rnSessList .rnsess', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ').trim()));
ok(drawn.some(t => /w\.sess/.test(t) && /Claude/.test(t)) && drawn.some(t => /w\.sess/.test(t) && /shell/.test(t)),
   `the project's settings list its sessions, whose and what (${drawn.join(' | ')})`);
// The last field showing, in the dialog's sections since they came (1 Oct).
const last = await page.$eval('#rnmodal .box', b => [...b.querySelectorAll('.field:not([hidden]):not(.rnhead)')]
  .filter(f => f.offsetParent).pop()?.id);
ok(last === 'rnSessField', `...at the foot of the dialog (${last})`);
await page.evaluate(() => [...document.querySelectorAll('#rnSessList .rnsess')]
  .find(r => /w\.sess/.test(r.textContent) && /Claude/.test(r.textContent))
  ?.querySelector('[data-rnsessend]').click());
await page.waitForFunction(() => ![...document.querySelectorAll('#rnSessList .rnsess')]
  .some(r => /w\.sess/.test(r.textContent) && /Claude/.test(r.textContent)), null, { timeout: 15000 });
const gone = (() => { try { execFileSync('tmux', ['has-session', '-t', '=' + here[0]]); return false; }
                      catch { return true; } })();
ok(gone && page.dialogs.some(d => /End w\.sess's Claude session on alpha\?/.test(d)),
   `End asks first, naming whose, and the session is gone (${page.dialogs.join(' | ').slice(0, 90)})`);

// ---- ...and not for anybody else ------------------------------------------------
const plainPage = await newPage(browser, { viewport: { width: 1280, height: 900 },
  httpCredentials: { username: 'w.watch', password: 'w.watch-pass-1' },
  extraHTTPHeaders: { Authorization: PLAIN.Authorization } });
await plainPage.goto(URL);
await ready(plainPage);
await plainPage.evaluate(() => renameProject('alpha'));
await plainPage.waitForTimeout(1000);
// The section is not drawn for it (R255 step 4; the operator, 21 Oct: what
// a role does not give is not shown), so nobody's sessions and no End.
await plainPage.waitForTimeout(1000);
const plainSess = await plainPage.evaluate(() => { const f = document.getElementById('rnSessField');
  return { shown: !!f && !f.hidden, ends: f ? f.querySelectorAll('button').length : 0 }; });
ok(!plainSess.shown && plainSess.ends === 0,
   `a plain account opening the same settings is not shown the sessions section, nor any End (${JSON.stringify(plainSess)})`);

// The administrator's page only: a plain account's settings dialog asks for
// the remote's credentials and is refused by design, which the browser logs.
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
// A project with a session open on a node cannot be deleted from under it
// (B242): Delete read only this container's tmux, where no session runs now.
{
  const onNode = `${uid}~codex-gamma`;
  const r = await fetch(base + '/api/v1/agent/work', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + agent.token },
    body: JSON.stringify({ sample: { cpu_pct: 1, mem_mb: 4096, mem_used_mb: 512,
      sessions: [{ name: onNode, attached: false, cwd: '/workspace/gamma', title: '' }] }, running: [], wait: 0 }) });
  const del = await call('/api/trash', { name: 'gamma' });
  ok(r.ok && del.status === 409 && del.error?.includes(onNode),
     `a project with a session running on a node is refused Delete, naming the session (${del.status} ${del.error})`);
  await beat();
}

// Nothing left for the next file: the sessions, and the node, retired the
// way auth.mjs retires its own.
for (const n of here) { try { tmuxKill(n); } catch { /* ended above */ } }
await call('/api/v1/nodes', { action: 'retire', id: box.id });
await done(browser);
