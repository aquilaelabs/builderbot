// One login for everything: the /login landing page, the cookie it mints,
// the challenge-free 401s that keep the browser's own dialog away, and the
// /term proxy that puts the terminals behind the same sign-in. The proxy's
// upstream is dead in the harness (nothing listens on the ttyd port), which
// pins the 502 path; the live relay is covered by using the dashboard.
import { launch, newPage, ok, done, sleep, URL, DIR } from './lib.mjs';
import http from 'node:http';
import { mkdirSync, writeFileSync, rmSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

// Plain fetches first: no credentials at all, straight from node.
const bare = async (path, opts = {}) =>
  fetch(URL.replace(/\/$/, '') + path, { redirect: 'manual', ...opts });

// ...but not for the page itself, which needs node:http instead of fetch.
// undici's parser asserts (`assert(!this.paused)`) and takes the whole
// process down when a body bigger than its buffer meets a connection close,
// and every response here ends in one: Python's BaseHTTPRequestHandler speaks
// HTTP/1.0 and closes after each. It is latent until the body is large enough,
// so this file died the day the dashboard page crossed 128KiB gzipped, having
// sat 119 bytes under it, and it died by CRASHING, after printing that every
// test passed, so the file's own tally said 21/21 while the suite went red.
//
// The bytes are not in question: curl gets Content-Length and exactly that
// many, gunzipping to the file byte for byte, and browsers are unaffected.
// This is the client, and only in tests.
const bigGet = (path, headers = {}) => new Promise((resolve, reject) => {
  const u = new global.URL(URL.replace(/\/$/, '') + path);
  const req = http.request(
    { hostname: u.hostname, port: u.port, path: u.pathname, headers },
    (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({
        status: res.statusCode,
        headers: { get: (k) => res.headers[k.toLowerCase()] ?? null },
        body: Buffer.concat(chunks),
      }));
    });
  req.on('error', reject);
  req.end();
});

let r = await bare('/');
ok(r.status === 302 && r.headers.get('location').startsWith('/login'),
   'signed out, the page redirects to /login');
ok(!r.headers.get('www-authenticate'), '...with no basic-auth challenge anywhere');
r = await bare('/api/status');
ok(r.status === 401 && !r.headers.get('www-authenticate'),
   'the API answers 401, challenge-free, so nothing pops a dialog');
r = await bare('/term/');
ok(r.status === 302 && r.headers.get('location').startsWith('/login'),
   'the terminal proxy is behind the same sign-in');
r = await bare('/login');
ok(r.status === 200 && (await r.text()).includes('Sign in'), 'the login page is the one open door');

// Wrong credentials re-render the form with the reason; right ones mint the
// cookie and land where the visitor was headed.
r = await bare('/login', { method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: 'username=test&password=nope&next=/' });
ok(r.status === 200 && (await r.text()).includes('Wrong username or password'),
   'a bad password re-renders the form, saying so');
r = await bare('/login', { method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: 'username=test&password=test&next=/' });
const cookie = (r.headers.get('set-cookie') || '').split(';')[0];
ok(r.status === 303 && cookie.startsWith('bb_session=') && cookie.length > 40,
   'the right password answers with a session cookie');
ok(/HttpOnly/i.test(r.headers.get('set-cookie')), '...that scripts cannot read');
r = await bare('/api/status', { headers: { Cookie: cookie } });
ok(r.status === 200, 'the cookie alone opens the API');
r = await bare('/term/', { headers: { Cookie: cookie } });
ok(r.status === 502 && (await r.json()).error.includes('not running'),
   'the proxy answers for a dead ttyd instead of hanging');
r = await bare('/login', { method: 'POST',
  headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  body: 'username=test&password=test&next=//evil.example/' });
ok(r.headers.get('location') === '/', 'a protocol-relative next is not followed');
r = await bare('/logout', { headers: { Cookie: cookie } });
ok(/Max-Age=0/.test(r.headers.get('set-cookie') || ''), 'logout clears the cookie');

// Big answers travel gzipped when the client takes it (the page and the
// status snapshot a phone polls every 15s), and small ones as they are.
const AUTHH = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
r = await bare('/api/status', { headers: { ...AUTHH, 'Accept-Encoding': 'gzip' } });
ok(r.headers.get('content-encoding') === 'gzip', 'the status snapshot travels gzipped');
r = await bigGet('/', { ...AUTHH, 'Accept-Encoding': 'gzip' });
const zipped = +r.headers.get('content-length');
const plain = (await bigGet('/', AUTHH)).body.length;
// A ratio, not a byte count: the point is that the one file is compressed to
// a fraction of itself, and a fixed ceiling set to whatever the page happened
// to weigh becomes a tripwire that the next feature trips. The absolute
// number is loose enough to mean only "something enormous got embedded".
//
// It tripped anyway, exactly as predicted: 150000 was reached with fifteen
// bytes to spare, so the twelve color schemes were the feature that met it.
// Raised to a number the ratio would fail long before, which is the check
// that actually means something.
// 250000 was reached the ordinary way in the end (no blob, just a year of
// features in the one file this page is by design), so it moves again, to a
// number the ratio fails long before. The ratio is the half that means
// something; this one only ever says "an image got pasted in".
ok(r.headers.get('content-encoding') === 'gzip'
   && zipped < plain / 2 && zipped < 400000,
   `the page travels gzipped, at a fraction of its size (${Math.round(zipped/1024)}kB of ${Math.round(plain/1024)}kB)`);
r = await bare('/api/status', { headers: { ...AUTHH, 'Accept-Encoding': 'identity' } });
ok(!r.headers.get('content-encoding'), 'a client that cannot take gzip gets plain bytes');

// A browser with preemptive basic auth (bb capture shot, curl -u, these tests) still
// works exactly as before: the whole page, no login step.
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await page.waitForFunction(() => document.querySelectorAll('#commands [data-m]').length > 0, { timeout: 40000 });
ok(page.url() === URL, 'preemptive basic auth bypasses the login page');

// And a browser with no credentials walks the login flow end to end.
const ctx2 = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page2 = await ctx2.newPage();
await page2.goto(URL);
await page2.waitForURL('**/login**');
await page2.fill('#u', 'test');
await page2.fill('#p', 'test');
await page2.click('button[type=submit]');
await page2.waitForFunction(() => document.getElementById('projects') !== null, { timeout: 20000 });
ok(!page2.url().includes('login'), 'the form signs a fresh browser in');
await page2.reload();
await page2.waitForFunction(() => document.getElementById('projects') !== null, { timeout: 20000 });
ok(true, '...and the cookie survives a reload');
// The header's sign-out button: drawn to its neighbors' size, and it really
// ends the session, landing on the login page and staying out.
ok(await page2.$eval('#bOut', b => {
  const r = b.getBoundingClientRect();
  const c = document.getElementById('bCards').getBoundingClientRect();
  return Math.abs(r.height - c.height) < 2 && Math.abs(r.width - c.width) < 8;
}), "sign out sits in the header at its neighbors' size");
await page2.click('#bOut');
await page2.waitForURL('**/login**');
await page2.goto(URL);
await page2.waitForURL('**/login**');
ok(true, 'the sign-out button ends the session for real');
await ctx2.close();

// ---- accounts, not one env var (roadmap #22 step 1) --------------------
// DASHBOARD_AUTH=test:test seeded the owner on this server's first boot and
// is not consulted again. Nothing is restricted yet (that is step 2), so
// what is checked here is the store standing where the string used to.
//
// Everything below works on a SECOND account. The first version changed the
// owner's password and could not put it back, because `test` is under the
// eight-character floor the store enforces, which would have taken the
// harness credential away from every file that runs after this one.
{
  const { readFileSync, existsSync } = await import('node:fs');
  const { execFileSync } = await import('node:child_process');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const bb = (args, input) => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', ...args],
    { input, encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  const store = `${DIR}/state/users.json`;
  const read = () => JSON.parse(readFileSync(store, 'utf8'));

  ok(existsSync(store), 'the first boot writes an account store');
  const seeded = read().users.test;
  ok(seeded && seeded.role === 'owner'
     && /^pbkdf2_sha256\$\d+\$/.test(seeded.password)
     && !JSON.stringify(read()).includes('test:test'),
     `DASHBOARD_AUTH seeds the owner, hashed and never in the clear (${
       String(seeded?.password).slice(0, 24)}…)`);

  bb(['add', 'alt', '--role', 'user'], 'firstpass1\nfirstpass1\n');
  ok(read().users.alt?.role === 'user', 'bb users add makes an ordinary account');
  const signin = (u, pw) => bare('/login', { method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: `username=${u}&password=${pw}&next=/` });
  let r2 = await signin('alt', 'firstpass1');
  const live = (r2.headers.get('set-cookie') || '').split(';')[0];
  ok(r2.status === 303 && (await bare('/api/status', { headers: { Cookie: live } })).status === 200,
     '...which signs in and opens the API');
  const basic = (u, pw) => bare('/api/status',
    { headers: { Authorization: 'Basic ' + Buffer.from(`${u}:${pw}`).toString('base64') } });
  ok((await basic('alt', 'firstpass1')).status === 200,
     '...and answers Basic auth from the store, as bb sends it');
  ok((await basic('alt', 'wrongpass1')).status === 401, '...but not a wrong password');

  // The property a stateless cookie has to be given deliberately: a password
  // change takes back the sessions it was used for.
  bb(['passwd', 'alt'], 'secondpass2\nsecondpass2\n');
  ok((await bare('/api/status', { headers: { Cookie: live } })).status === 401,
     'changing a password invalidates the cookies already issued for it');
  ok((await signin('alt', 'secondpass2')).status === 303, '...and the new one signs in');

  // ...and so does deleting the account, for the same reason and for free.
  r2 = await signin('alt', 'secondpass2');
  const doomed = (r2.headers.get('set-cookie') || '').split(';')[0];
  execFileSync('python3', ['-c', `
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state="${DIR}/state", write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
print(u.remove("alt"))`], { encoding: 'utf8' });
  ok((await bare('/api/status', { headers: { Cookie: doomed } })).status === 401,
     'deleting an account ends its sessions too');
  ok(read().users.test && !read().users.alt,
     '...and the owner is untouched by all of it');
}

// ---- the first run --------------------------------------------------------
// Nobody owns a fresh container, and that used to be a refusal: the owner came
// from DASHBOARD_AUTH and the dashboard would not start without it, which put
// the one credential that opens a shell on this box into the container's
// environment, readable forever. It is a screen now, and it is the only page
// served until somebody claims it.
//
// Driven against a store of its own rather than this server's, which already
// has an owner: the whole property is what happens when there is none.
{
  const { execFileSync } = await import('node:child_process');
  const { mkdtempSync, readFileSync, existsSync } = await import('node:fs');
  const { tmpdir } = await import('node:os');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const fresh = mkdtempSync(`${tmpdir()}/bbsetup-`);
  const run = code => execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state="${fresh}", write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' });

  ok(run('print(len(u.all_users()))').trim() === '0',
     'a fresh container has no accounts, which is a normal first boot');
  const made = run('print(json.dumps(u.claim("boss", "longenough1")))');
  ok(JSON.parse(made).ok, `claiming it makes the owner (${made.trim()})`);
  const rec = JSON.parse(readFileSync(`${fresh}/users.json`, 'utf8')).users.boss;
  ok(rec.role === 'owner' && rec.projects.includes('*')
     && /^pbkdf2_sha256\$/.test(rec.password) && /^u_[0-9a-f]{8}$/.test(rec.uid),
     '...as an owner, hashed, with every project and an id of its own');
  ok(!JSON.parse(run('print(json.dumps(u.claim("second", "longenough1")))')).ok,
     '...and the second claim is refused, because there is now an account');
  ok(!JSON.parse(run('print(json.dumps(u.claim("x", "short")))')).ok
     && !JSON.parse(run('print(json.dumps(u.claim("", "longenough1")))')).ok,
     'a short password and an empty name are both refused');
  ok(existsSync(`${fresh}/users.json`), 'and the store is written where it will persist');

  // ...and the door is shut on a server that already has an owner, which is
  // this one. A second claim through the form would be a second owner.
  const shut = await bare('/setup', { method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: 'username=usurper&password=longenough1&password2=longenough1' });
  ok(shut.status === 200 && /already has an account/.test(await shut.text()),
     'the first-run form is refused once somebody has claimed the container');
  ok((await bare('/api/status')).status === 401,
     '...and everything else still wants a sign-in, as it did before');
}

// ---- a strip each (roadmap #25) --------------------------------------------
// The tab layout was ONE file for the whole box: written by whichever browser
// saved last and handed to every other one. Fine for one operator, wrong the
// moment there are two: you would watch somebody else's tabs open in front
// of you. It is keyed by the account's minted id now, and the id is minted
// rather than the name because the owner is renameable on purpose.
{
  const { readFileSync } = await import('node:fs');
  const { execFileSync } = await import('node:child_process');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const bb = (args, input) => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', ...args],
    { input, encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  const store = `${DIR}/state/users.json`;
  const read = () => JSON.parse(readFileSync(store, 'utf8'));
  ok(Object.values(read().users).every(u => /^u_[0-9a-f]{8}$/.test(u.uid || '')),
     'every account carries a minted id, backfilled onto ones that predate it');
  const uids = Object.values(read().users).map(u => u.uid);
  ok(new Set(uids).size === uids.length, '...and no two accounts share one');

  bb(['add', 'sharer', '--role', 'user'], 'stripspass1\nstripspass1\n');
  const asUser = (u, pw) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${pw}`).toString('base64'),
                               'Content-Type': 'application/json' });
  const putTabs = (h, tabs) => bare('/api/layout', { method: 'POST', headers: h,
    body: JSON.stringify({ tabs, panes: [tabs[0]?.id || null, null], active: 0 }) });
  const strip = async h => ((await (await bare('/api/status', { headers: h })).json()).layout || {});

  const owner = asUser('test', 'test');
  const other = asUser('sharer', 'stripspass1');
  // Given one project, because a `user` with none can reach nothing at all,
  // which is correct, and would make everything below pass for the wrong
  // reason.
  await bare('/api/users', { method: 'POST', headers: owner,
    body: JSON.stringify({ action: 'projects', name: 'sharer', projects: ['beta'] }) });
  // ...and an author, or no Claude session starts for it (users.git_ready):
  // the checks below are about whose session it is, not about that.
  await bare('/api/users', { method: 'POST', headers: owner,
    body: JSON.stringify({ action: 'edit', name: 'sharer',
      profile: { full_name: 'Sharer', email: 'sharer@example.invalid' } }) });
  await putTabs(owner, [{ id: 't-own', kind: 'term', arg: 'shell-1', label: 'owner shell' }]);
  await putTabs(other, [{ id: 't-oth', kind: 'term', arg: 'shell-2', label: 'their shell' }]);

  const a = await strip(owner), b = await strip(other);
  ok(a.tabs?.length === 1 && a.tabs[0].id === 't-own',
     `the owner keeps the strip they saved (${(a.tabs || []).map(t => t.id).join()})`);
  ok(b.tabs?.length === 1 && b.tabs[0].id === 't-oth',
     `...and the other account has its own, not a copy of it (${(b.tabs || []).map(t => t.id).join()})`);
  const file = JSON.parse(readFileSync(`${DIR}/state/tabs.json`, 'utf8'));
  ok(file.users && Object.keys(file.users).length === 2
     && Object.keys(file.users).every(k => /^u_[0-9a-f]{8}$/.test(k)),
     `...stored one slot per account, keyed by the id rather than the name (${
        Object.keys(file.users || {}).join()})`);

  // The scheme rides the account too, so a browser that has never seen it
  // adopts it after first paint rather than starting on the default. Set
  // through the same endpoint the swatch menu uses.
  const setTheme = (h, theme) => bare('/api/users', { method: 'POST', headers: h,
    body: JSON.stringify({ action: 'prefs', prefs: { theme } }) });
  ok((await setTheme(other, 'nocturne')).status === 200,
     'an account sets its own scheme, without being an administrator');
  ok((await strip(other), (await (await bare('/api/status', { headers: other })).json()).theme) === 'nocturne',
     '...and it comes back in that account\'s state payload');
  ok((await (await bare('/api/status', { headers: owner })).json()).theme !== 'nocturne',
     '...and not in anybody else\'s');
  ok((await bare('/api/users', { method: 'POST', headers: other,
        body: JSON.stringify({ action: 'prefs', prefs: { theme: '../../etc' } }) })).status === 400,
     'a scheme that is not one of the names is refused, not stored');
  ok((await bare('/api/users', { method: 'POST', headers: other,
        body: JSON.stringify({ action: 'role', name: 'test', role: 'user' }) })).status === 403,
     '...and prefs being open to everyone did not open the rest of the tab');

  // ---- a Claude sign-in is one account's, on one node ----------------------
  // A person signs in on each node they work on, and what the controller
  // keeps is what each node reported for each account: no login travels and
  // none is kept here. So two accounts are signed in on a node each for
  // themselves, a sign-out is one account's on one node, and an account that
  // does not administer signs in and out on the nodes its own projects work
  // on and no others. Driven against a node rather than tmux: the sessions
  // are a node's (R47), and its census is what says who has one open.
  {
    const term = (h, arg) => bare('/term/ws?arg=' + encodeURIComponent(arg), { headers: h });
    const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
                'Content-Type': 'application/json' };
    const napi = async (path, body, hdrs) => (await bare(path, {
      method: body ? 'POST' : 'GET', headers: { ...H, ...(hdrs || {}) },
      ...(body ? { body: JSON.stringify(body) } : {}) })).json();
    const as = async (h, path, body) => { const r = await bare(path, { method: body ? 'POST' : 'GET', headers: h,
      ...(body ? { body: JSON.stringify(body) } : {}) }); return { status: r.status, ...(await r.json().catch(() => ({}))) }; };
    const uidOf = n => JSON.parse(readFileSync(store, 'utf8')).users[n].uid;
    const box = await napi('/api/v1/nodes', { action: 'enroll', name: 'talkbox' });
    const SE = { up: true, port: 7681, ro_port: 7682, user: 'bb',
                 workspace: true, writable: true, boot: '3.3', up_s: 5000 };
    // Enrolling with the one-time token mints the node's own, which is what
    // every call after it carries.
    const agent = await napi('/api/v1/agent/enroll',
      { user: 'bb', version: 'harness', census: { cpu: 2, mem_mb: 4096,
        arch: 'x86_64', system: 'linux', session: SE } },
      { Authorization: 'Bearer ' + box.token });
    // The session list rides the HEARTBEAT, not the census (nodes.heartbeat
    // is where it is whitelisted), so this is the shape the agent's poll
    // sends, with no wait so nothing is held.
    // ...and its answer is a 204 when there is no job for the node, so the
    // body is not read.
    const census = sessions => bare('/api/v1/agent/work', { method: 'POST',
      headers: { ...H, Authorization: 'Bearer ' + agent.token },
      body: JSON.stringify({ sample: { cpu_pct: 1, mem_mb: 4096,
        mem_used_mb: 512, sessions }, running: [], wait: 0 }) });
    await census([]);
    await napi('/api/prefs', { project: 'beta', node: box.id });
    const mine = async h => ((await as(h, '/api/status')).claude_auth || {}).nodes || {};
    ok(!(box.id in await mine(owner)) && !(box.id in await mine(other)),
       'a node nobody has signed in on reads as signed out for each account');
    // Reported the way a node reports it (with a session token minted for
    // that account, on the node its project is on) rather than by writing
    // the record, so what is under test is the path that makes one.
    // WORKSPACE too: the verb checks the project is one, off the filesystem.
    const token = who => execFileSync('bash',
      [`${REPO}/scripts/bb`, 'users', 'token', 'beta', who],
      { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`,
                                 WORKSPACE: `${DIR}/ws` } }).trim();
    const report = (who, email) => bare('/api/v1/claude-login', { method: 'POST',
      headers: { 'Content-Type': 'application/json',
                 Authorization: 'Bearer ' + token(who) },
      body: JSON.stringify({ email, plan: 'max', signed_in: true }) });
    ok((await report('test', 'tester@example.com')).status === 200
       && (await mine(owner))[box.id]?.email === 'tester@example.com' && !(box.id in await mine(other)),
       'a node reports the account it signed one account in as, and that is that account\'s alone');
    // Two BuilderBot accounts on one Anthropic login: each signed in for
    // itself, neither refused a session. The Users tab says they share.
    ok((await report('sharer', 'tester@example.com')).status === 200
       && (await mine(other))[box.id]?.email === 'tester@example.com',
       'a second account signs in on the same node for itself, to whichever Anthropic account it chose');
    // Named the way bb-tty would name it on the node: every account is
    // prefixed there. The name is the only record of whose it is.
    await census([{ name: `${uidOf('sharer')}~claude-beta`, attached: false,
                    cwd: '/workspace/beta', title: '' }]);
    ok((await term(other, 'claude:beta')).status !== 409 && (await term(owner, 'claude:beta')).status !== 409,
       'each account has its own session on the project, in a checkout of its own');
    // The list an account that does not administer is shown: the nodes its
    // own projects work on, and its sign-in is refused anywhere else.
    const shown = ((await as(other, '/api/v1/nodes')).nodes || []).map(n => n.name);
    ok(shown.join() === 'talkbox', `an account that does not administer is shown the nodes its own projects are on, and no others (${shown.join()})`);
    const elsewhere = ((await napi('/api/v1/nodes')).nodes || []).find(n => n.kind === 'agent' && n.id !== box.id);
    const stray = await as(other, '/api/signin', { node: elsewhere.id });
    ok(stray.status === 403 && /not a node one of your projects/.test(stray.error || ''),
       `...so it cannot start a sign-in on a node that is not one of them (${stray.error})`);
    const nonode = await as(other, '/api/signin', {});
    ok(nonode.status === 400 && /which node/.test(nonode.error || ''), `a sign-in names its node (${nonode.error})`);
    const theirs = await as(other, '/api/signin', { node: box.id });
    const lj = theirs.job ? await napi(`/api/v1/jobs?id=${theirs.job}`) : {};
    ok(theirs.status === 200 && lj.type === 'claude-login' && lj.node === box.id && lj.spec?.uid === uidOf('sharer')
       && /^bbs_/.test(lj.spec?.token || ''),
       `on its own project's node it starts one: a claude-login job there, for that account (${theirs.error || lj.type})`);
    // The link a flow prints signs somebody in: it is shown to the person
    // the flow was started for and to nobody else, and only they type into it.
    ok((await as(other, '/api/status')).signin?.running === true && (await as(owner, '/api/status')).signin?.running === false,
       'a running sign-in is shown to the account it was started for, and to nobody else');
    const butt = await as(owner, '/api/signin', { node: box.id });
    const code = await as(owner, '/api/login-code', { code: 'abc#def' });
    ok(butt.status === 409 && /another account is signing in/.test(butt.error || '') && code.status === 403,
       `...and another account neither replaces it nor types a code into it (${butt.error})`);
    await as(other, '/api/signin', { action: 'cancel' });
    // Signing out: that account's, on that node. Not while its own session
    // is open there; then a job on the node, and nobody else's sign-in moves.
    const busy = await as(other, '/api/signout', { node: box.id });
    ok(busy.status === 409 && /end your Claude session on beta first/.test(busy.error || ''),
       `signing out on a node waits for that account's own session there to end (${busy.error})`);
    await census([]);
    const out = await as(other, '/api/signout', { node: box.id });
    const oj = out.job ? await napi(`/api/v1/jobs?id=${out.job}`) : {};
    ok(out.status === 200 && oj.type === 'claude-logout' && oj.node === box.id && oj.spec?.uid === uidOf('sharer'),
       `...then it is a claude-logout job on that node, for that account (${out.error || oj.type})`);
    ok(!(box.id in await mine(other)) && (await mine(owner))[box.id]?.email === 'tester@example.com',
       '...and the other account\'s sign-in on the same node is untouched');
    ok((await as(other, '/api/signout', {})).status === 400, 'a sign-out names its node too');
    // ...and beta goes back to having no node, which is how the rest of
    // this file expects to find it.
    await napi('/api/v1/jobs', { action: 'cancel', id: out.job });
    await napi('/api/prefs', { project: 'beta', node: '' });
    await napi('/api/v1/nodes', { action: 'retire', id: box.id });
  }

  // ---- a user role has no shell at all (roadmap #27) -----------------------
  // The rest of the role is enforced by this server, in Python. A terminal is
  // the way around all of it (one uid, one tmux server, Bash covered by no
  // deny list), so an account that may not have one gets its Claude session
  // as a read-only console and nothing else through /term.
  {
    const st = await (await bare('/api/status', { headers: other })).json();
    ok(st.can && st.can.terminal === false && st.can['docker-write'] === false
       && st.can['toolchains-write'] === false && st.can['git-auth'] === false,
       `the payload says what this account may do, by capability (${
          JSON.stringify(st.can)})`);
    const mine = await (await bare('/api/status', { headers: owner })).json();
    ok(mine.can && mine.can.terminal === true,
       '...and an administrator is told the opposite, so nothing is drawn dead');

    const term = (h, arg) => bare('/term/ws?arg=' + encodeURIComponent(arg), { headers: h });
    const shell = await term(other, 'sh:1:');
    ok(shell.status === 403 && /shell is an administrator/.test((await shell.json()).error || ''),
       'a shell is refused at the proxy, not merely hidden on the page');
    ok((await term(other, 'shell:beta')).status === 403,
       '...in every spelling the argument has');
    // The one thing it may ask for, and only on a project it was given.
    ok((await term(other, 'claude:zzz-not-a-project')).status === 403,
       'a Claude session on a project it cannot see is refused the same way');
    ok((await term(owner, 'sh:1:')).status !== 403,
       'an administrator still has a shell');

    // ...and the things a user may not change.
    const post = (h, path, body) => bare(path, { method: 'POST', headers: h,
      body: JSON.stringify(body) });
    ok((await post(other, '/api/create', { name: 'sneaky', token: 'ghp_x' })).status === 403,
       'a user cannot make a project, which is where a git token would be stored');
    ok((await post(other, '/api/rename', { name: 'beta', to: 'beta2', auth: 'https' })).status === 403,
       '...nor change how one authenticates, which travels through rename');
    ok((await post(other, '/api/devapp', { project: 'beta', action: 'up' })).status === 403,
       'a user cannot start or stop a container');
    ok((await post(other, '/api/devapp', { project: 'beta', action: 'remove' })).status === 403,
       '...nor remove one, nor configure it');
    // ...but building what they committed and looking at it is the point of
    // having the project. Not a 403: whatever else it answers, it got past
    // the gate.
    ok((await post(other, '/api/devapp', { project: 'beta', action: 'rebuild' })).status !== 403,
       'a user CAN rebuild: that is how you see what you just committed');
    ok((await post(other, '/api/devapp', { project: 'beta', action: 'abort' })).status !== 403,
       '...and stop one, since whoever may start a build may stop it');
    ok((await post(other, '/api/toolchains', { action: 'install', names: ['jdk'] })).status === 403,
       '...nor install gigabytes onto a shared node');
    // ...but the registry it is shown is its own projects' machines only,
    // because the whole list is otherwise an inventory of the box.
    const theirs = await (await bare('/api/v1/nodes', { headers: other })).json();
    const all = await (await bare('/api/v1/nodes', { headers: owner })).json();
    ok(all.nodes.length > theirs.nodes.length,
       `a user sees only the nodes its own projects build on (${
          theirs.nodes.length} of ${all.nodes.length})`);
    // ...and the scoping is on the ANSWER, not only the picker. `?node=` is a
    // string in a URL, and the answer is what carries the other projects'
    // names. Scoping the picker alone would have been theatre.
    const nodeId = all.nodes.find(n => n.id !== 'local')?.id || 'local';
    const peek = await bare('/api/docker?node=' + encodeURIComponent(nodeId),
                            { headers: other });
    const body = await peek.json();
    ok(/not a node one of your projects builds on|none of your projects/.test(body.error || ''),
       `a node no project of theirs builds on is refused, not listed (${body.error})`);
    const pk = await (await bare('/api/toolchains?node=' + encodeURIComponent(nodeId),
                                 { headers: other })).json();
    ok(/not a node one of your projects builds on|none of your projects/.test(pk.error || ''),
       '...and the same for what that node has installed');
    // ...while a project of theirs with no node is told so in the project's
    // own words, not refused as a node outside their scope (B258): there is
    // no primary docker manager for it to have landed on, so what it has is
    // no containers anywhere, and the way out is its settings.
    const own = await (await bare('/api/docker?project=beta', { headers: other })).json();
    ok(/beta has no node, so it has no containers anywhere/.test(own.error || '') && own.blind === true,
       `a user's project with no node is told it has no node, in its own words (${String(own.error).slice(0, 60)})`);
  }

  // ---- an admin sees everything and works on what it took on (#27) ---------
  // Two different questions. Hiding a project from somebody who administers
  // the box only sends them looking for it, so an admin is shown every one,
  // and the list they keep is a seatbelt against editing the wrong project,
  // not a wall, because an admin has a shell. A `user` is still only shown
  // what it was given, because a project it cannot work on is one it has no
  // reason to know exists.
  {
    bb(['add', 'second', '--role', 'admin'], 'adminpass11\nadminpass11\n');
    const adm = asUser('second', 'adminpass11');
    const post = (h, path, body) => bare(path, { method: 'POST', headers: h,
      body: JSON.stringify(body) });
    const projects = async h => ((await (await bare('/api/status', { headers: h })).json()).projects || []);

    const theirs = await projects(adm);
    const all = await projects(owner);
    ok(theirs.length === all.length && theirs.length > 1,
       `a fresh admin is shown every project (${theirs.length} of ${all.length})`);
    ok(theirs.every(p => p.mine === false),
       '...and none of them marked as theirs to change, having taken none on');
    ok((await projects(other)).every(p => p.name === 'beta'),
       '...while a user is still shown only what it was given');

    // Read-only means it: the writes refuse, by name, with the remedy.
    const r = await post(adm, '/api/roadmap', { project: 'alpha', action: 'add', text: 'x' });
    ok(r.status === 403 && /taken this project on/.test((await r.json()).error || ''),
       'an admin cannot edit the notebook of a project it has not taken on');
    ok((await post(adm, '/api/bugs', { project: 'alpha', action: 'add', title: 'x' })).status === 403,
       '...nor file a bug on it');
    ok((await post(adm, '/api/prefs', { project: 'alpha', build: 'make' })).status === 403,
       '...nor change its settings');
    // What is the box's rather than a project's is an administrator's: the
    // container log, the trash, the daemon's containers, the deploy keys,
    // the command lists that run in terminals.
    for (const [ep, want] of [['/logs/download', 403], ['/api/trash', 403], ['/api/containers', 403],
                              ['/api/pubkeys', 403], ['/api/project-job', 403]])
      ok((await bare(ep, { headers: other })).status === want, `a user is refused ${ep}`);
    ok((await post(other, '/api/custom', { action: 'save', name: 'x', body: 'rm -rf /' })).status === 403,
       'a user cannot write the command lists an administrator\'s terminal runs');
    ok((await bare('/api/v1/jobs?n=50', { headers: other })).status === 200
       && ((await (await bare('/api/v1/jobs?n=50', { headers: other })).json()).jobs || []).every(j => j.project === 'beta'),
       'a user reads only the jobs of projects they were given');
    ok(!((await (await bare('/api/status', { headers: other })).json()).attention || []).length,
       '...and the bell\'s node alerts, which only an administrator can act on, are not theirs');
    // Memories are the reader's own, in the reader's home, not the owner's
    // (bug B67): a user opening the Memory tab must not see what the owner's
    // sessions remembered, and what they write must land where their own
    // sessions read.
    {
      const { mkdirSync: mk, writeFileSync: wf } = await import('node:fs');
      const uid = (await (await bare('/api/users', { headers: owner })).json()).users.find(u => u.name === 'sharer').uid;
      const slug = (`${DIR}/ws/beta`).replaceAll('/', '-');
      const theirs = `${DIR}/home/users/${uid}/.claude/projects/${slug}/memory`;
      const owners = `${DIR}/home/.claude/projects/${slug}/memory`;
      mk(theirs, { recursive: true }); mk(owners, { recursive: true });
      wf(`${theirs}/theirs.md`, '---\nname: theirs\ndescription: a user\'s own\nmetadata:\n  type: project\n---\n\nmine\n');
      wf(`${owners}/owners.md`, '---\nname: owners\ndescription: the owner\'s\nmetadata:\n  type: project\n---\n\nnot yours\n');
      const seenBy = async h => ((await (await bare('/api/memory?project=beta', { headers: h })).json()).memories || []).map(m => m.name);
      const u = await seenBy(other), o = await seenBy(owner);
      ok(u.includes('theirs') && !u.includes('owners'),
         `a user reads their own memories and not the owner's (${u.join(',')})`);
      ok(o.includes('owners') && !o.includes('theirs'),
         `...and the owner reads theirs and not the user's (${o.join(',')})`);
      // Not the fixture's: taken away again so no later file meets a beta
      // memory nobody seeded.
      rmSync(`${theirs}/theirs.md`, { force: true });
      rmSync(`${owners}/owners.md`, { force: true });
    }
    const term = (h, arg) => bare('/term/ws?arg=' + encodeURIComponent(arg), { headers: h });
    ok((await term(adm, 'claude:alpha')).status === 403,
       '...nor start a Claude session in it, which is the most write-shaped thing here');
    ok((await bare('/api/roadmap?project=alpha', { headers: adm })).status === 200,
       '...but reading it is fine, which is what read-only means');

    // ...and the remedy is theirs to apply, which is the whole difference
    // between this and a user's list.
    ok((await post(adm, '/api/users', { action: 'projects', name: 'second',
                                        projects: ['alpha'] })).status === 200,
       'an admin can add a project to its own list: a seatbelt, not a wall');
    ok((await post(adm, '/api/roadmap', { project: 'alpha', action: 'add', text: 'x' })).status === 200,
       '...and then it works on it');
    ok((await post(other, '/api/users', { action: 'projects', name: 'sharer',
                                          projects: ['alpha'] })).status === 403,
       'a user cannot grant itself anything, which is why theirs is a boundary');
    execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state="${DIR}/state", write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
print(u.remove("second"))`], { encoding: 'utf8' });
  }

  // ---- chat, and the project feed ------------------------------------------
  // Two kinds of conversation, one store, and the read rule is the addressing:
  // a direct one belongs to its two ends, a project feed to whoever may see
  // the project.
  {
    const post = (h, path, body) => bare(path, { method: 'POST', headers: h,
      body: JSON.stringify(body) });
    const chat = (h, body) => post(h, '/api/chat', body);
    const uidOf = n => JSON.parse(readFileSync(store, 'utf8')).users[n].uid;

    const sent = await (await chat(owner, { action: 'send', who: 'sharer',
                                            text: 'ready when you are' })).json();
    ok((sent.messages || []).some(m => m.text === 'ready when you are'),
       'a message to another account comes back in the conversation');
    const theirs = await (await chat(other, { action: 'read', who: 'test' })).json();
    ok((theirs.messages || []).some(m => m.text === 'ready when you are'
                                    && m.who === 'test'),
       '...and the other end sees it, named for who sent it');

    // A project feed is the project's rule, not a new one.
    ok((await chat(other, { action: 'send', project: 'beta', text: 'looking at this' })).status === 200,
       'a project they were given takes a message');
    const denied = await chat(other, { action: 'send', project: 'alpha', text: 'x' });
    ok(denied.status === 403,
       '...and one they were not is refused, the same as the project is');
    // An admin is shown every project, so every project's channel is readable
    // to them: a channel is the group chat for the people on it, and saying
    // something in one is not a change to the project. The list marks which
    // are actually theirs; the door does not need to.
    ok((await chat(owner, { action: 'read', project: 'gamma' })).status === 200,
       'an administrator can read a project channel it has not taken on');
    // ...and a user is not even shown that one exists: the channel list is
    // drawn from the projects in their own payload.
    const theirProjects = ((await (await bare('/api/status', { headers: other })).json())
      .projects || []).map(p => p.name);
    ok(theirProjects.length === 1 && theirProjects[0] === 'beta',
       `a user's channel list is only the projects they were given (${theirProjects})`);
    ok((await chat(other, { action: 'read', project: 'gamma' })).status === 403,
       '...and asking for another one directly is refused, not merely undrawn');

    // The status poll carries what is waiting, which is what puts the dot on
    // the button: a chat you have to open to discover is one nobody opens.
    await chat(owner, { action: 'send', who: 'sharer', text: 'and another' });
    const st = await (await bare('/api/status', { headers: other })).json();
    ok(st.chat && (st.chat.unread || {})[`dm:${uidOf('test')}`] >= 1,
       `the poll says what is unread (${JSON.stringify(st.chat?.unread)})`);
    ok((st.chat.people || []).includes('test') && !(st.chat.people || []).includes('sharer'),
       '...and who there is to talk to, without listing yourself');
    // Reading it clears it, which is the only thing "seen" has to mean.
    await chat(other, { action: 'read', who: 'test' });
    const after = await (await bare('/api/status', { headers: other })).json();
    ok(!(after.chat.unread || {})[`dm:${uidOf('test')}`],
       '...and reading a conversation is what marks it seen');

    // The panel keeps a reader's place (the operator, 25 Sep: scrolling up,
    // something kept snapping it to the bottom): the poll repaints only
    // when the conversation changed, and pins to the end only for a reader
    // already there.
    {
      for (let i = 0; i < 40; i++) await chat(owner, { action: 'send', who: 'sharer', text: `an older line ${i}` });
      await page.evaluate(() => { if (!showChat) mobPanel('chat'); chatOpen({ who: 'sharer' }); });
      await page.waitForFunction(() => document.querySelectorAll('#chatlog .chatmsg').length >= 40, null, { timeout: 15000 });
      const up = await page.evaluate(() => { const l = document.getElementById('chatlog'); l.scrollTop = 0;
                                             return { top: l.scrollTop, tall: l.scrollHeight > l.clientHeight }; });
      await page.evaluate(() => loadChat());
      await sleep(800);
      const kept = await page.evaluate(() => document.getElementById('chatlog').scrollTop);
      ok(up.tall && up.top === 0 && kept === 0, `a reader scrolled up stays where they were across a poll (${kept})`);
      await page.evaluate(() => { const l = document.getElementById('chatlog'); l.scrollTop = l.scrollHeight; });
      await chat(other, { action: 'send', who: 'test', text: 'the newest line' });
      await page.evaluate(() => loadChat());
      await page.waitForFunction(() => /the newest line/.test(document.getElementById('chatlog')?.textContent || ''), null, { timeout: 10000 });
      ok(await page.evaluate(() => { const l = document.getElementById('chatlog'); return l.scrollTop + l.clientHeight >= l.scrollHeight - 8; }),
         '...while one at the end is shown the newest message');
      await page.evaluate(() => { chatWith = null; mobPanel('chat'); drawChat(); });
    }

    // The prompt relay, driven the way Claude Code drives it.
    const relay = `${REPO}/scripts/dashboard/bb-prompt-relay`;
    execFileSync('python3', [relay, 'beta', uidOf('sharer')], {
      input: JSON.stringify({ prompt: 'rewrite the parser' }), encoding: 'utf8',
      env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
    const feed = await (await chat(owner, { action: 'read', project: 'beta' })).json();
    ok((feed.messages || []).some(m => /sharer asked: rewrite the parser/.test(m.text)
                                  && m.kind === 'asked'),
       'a prompt on a shared project reaches the others, marked as a prompt');

    // ...but only what a PERSON typed. UserPromptSubmit fires for every turn a
    // session receives, and a background command finishing arrives as one,
    // which filled a channel with task ids and output paths on a real phone.
    const relayed = t => { execFileSync('python3', [relay, 'beta', uidOf('sharer')], {
      input: JSON.stringify({ prompt: t }), encoding: 'utf8',
      env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } }); };
    const count = async () => ((await (await chat(owner,
      { action: 'read', project: 'beta' })).json()).messages || []).length;
    const n0 = await count();
    relayed('<task-notification> <task-id>b1</task-id> </task-notification>');
    relayed('<system-reminder>a file changed</system-reminder>');
    ok(await count() === n0,
       'a turn that is all harness machinery is not relayed at all');
    relayed('fix the login <system-reminder>noise</system-reminder>');
    const last = ((await (await chat(owner, { action: 'read', project: 'beta' })).json())
      .messages || []).slice(-1)[0];
    ok(/asked: fix the login$/.test(last.text),
       `...and a real message keeps only the half somebody typed (${last.text})`);
  }

  // A rename must not lose the strip: the whole reason the key is minted.
  execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state="${DIR}/state", write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
print(u.rename("sharer", "renamed"))`], { encoding: 'utf8' });
  const renamed = asUser('renamed', 'stripspass1');
  const after = await strip(renamed);
  ok(after.tabs?.length === 1 && after.tabs[0].id === 't-oth',
     'renaming an account keeps its strip, because the key was never the name');
  execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state="${DIR}/state", write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
print(u.remove("renamed"))`], { encoding: 'utf8' });
}

// ---- what a `user` sees, and does not (roadmap #22 step 2) --------------
// The property the whole scheme leans on: a project somebody was not given is
// ABSENT, not refused, so the existence check and the permission check are
// the same check, and comparing error messages tells you nothing.
{
  const { readFileSync } = await import('node:fs');
  const { execFileSync } = await import('node:child_process');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const bb = (args, input) => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', ...args],
    { input, encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
  const py = (code) => execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state="${DIR}/state", write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' }).trim();

  bb(['add', 'lim', '--role', 'user'], 'limitedpw1\nlimitedpw1\n');
  py('print(u.set_projects("lim", ["alpha"]))');
  const as = (path, opts = {}) => bare(path, { ...opts, headers: {
    Authorization: 'Basic ' + Buffer.from('lim:limitedpw1').toString('base64'),
    ...(opts.headers || {}) } });
  const post = (path, body) => as(path, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  // Controller settings, and the global rules on it, are an administrator's
  // (R63): a global rule reaches every project, including ones this account
  // cannot see. The card carrying the button is not drawn for them either,
  // which `can.admin` is what decides.
  const asUser = await (await as('/api/status')).json();
  ok(asUser.can?.admin === false,
     'an ordinary account is told it is not an administrator, so the page draws no Administration card');
  const wrote = await post('/api/global-rules',
    { action: 'save', rules: [{ name: 'sneak', text: 'every project, please' }] });
  ok(wrote.status === 403, `...and cannot write a rule for every project (${wrote.status})`);
  const stillNone = await (await bare('/api/global-rules', { headers: {
    Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json();
  ok(!(stillNone.rules || []).some(r => r.name === 'sneak'), '...and nothing was written');

  const mine = await (await as('/api/status')).json();
  const names = (mine.projects || []).map(p => p.name);
  ok(names.includes('alpha') && !names.includes('ep.silon') && names.length === 1,
     `a user's state carries only the projects they were given (${names.join(', ')})`);
  const all = await (await bare('/api/status', { headers: {
    Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json();
  ok((all.projects || []).length > names.length,
     '...while the owner still sees every one of them');

  // A project they were not given does not exist, and says so in the words a
  // typo gets, never "forbidden", which would confirm it is there.
  const hidden = await (await post('/api/roadmap', { action: 'save', project: 'ep.silon', items: [] })).json();
  ok(/not a project/.test(hidden.error || ''),
     `a project they cannot see reads as absent, not refused (${hidden.error})`);

  // ...and on a project they DO have, the verbs that reach past it are an
  // administrator's.
  const renamed = await post('/api/rename', { name: 'alpha', to: 'alpha2' });
  ok(renamed.status === 403 && /administrator/.test((await renamed.json()).error || ''),
     'renaming their own project is refused, and says whose it is');
  const trashed = await post('/api/trash', { name: 'alpha' });
  ok(trashed.status === 403, 'so is deleting it');
  const renoded = await post('/api/prefs', { project: 'alpha', node: 'local' });
  ok(renoded.status === 403 && /node is shared/.test((await renoded.json()).error || ''),
     '...and moving it to another node, because a node is shared');
  const built = await post('/api/prefs', { project: 'alpha', build: './gradlew' });
  ok(built.status === 200, '...while the project\'s own build command is theirs to set');

  // The machinery is not a project and is not theirs at all.
  for (const [path, body] of [['/api/v1/nodes', { action: 'enroll', name: 'zzprobe' }],
                              ['/api/toolchains', { action: 'install', names: ['jdk'] }]]) {
    const r3 = await post(path, body);
    ok(r3.status === 403, `${path} is an administrator's`);
  }
  // A phone is not machinery: whoever connects one owns it, and a user may
  // too, since the ownership is held per connection, not by role. (No node
  // named, so this is refused for that reason and not for who is asking.)
  ok((await post('/api/phone', { action: 'connect' })).status !== 403,
     "/api/phone is any account's: a phone is its owner's, not the administrators'");
  // ...and the refusal REFUSED. Asserting the status alone is what let a
  // guard through that wrote a 403 and then did the thing anyway: _json
  // returns None, so `if (no := self._may(...))` was never true. The nodes
  // suite found it, three files later, as a node nobody had enrolled.
  {
    const own = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
    const ns = await (await bare('/api/v1/nodes', { headers: own })).json();
    const made = (ns.nodes || []).map(n => n.name);
    ok(!made.includes('zzprobe'),
       `...and refusing it did not enroll it anyway (${made.join(', ')})`);
  }
  // ...and the owner is unaffected by every one of those.
  ok((await bare('/api/status', { headers: {
       Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).status === 200,
     'none of it touches the owner');
  py('print(u.remove("lim"))');
}

// ---- the Users tab (roadmap #22 step 3) ---------------------------------
// The surface accounts are actually managed from; bb users is the way back in
// when this cannot be reached, not the way in generally.
{
  await page.evaluate(() => { const c = document.getElementById('cardTools');
    if (c?.classList.contains('closed')) c.querySelector('h2').click(); });
  await page.click('#bUsers');
  await page.waitForSelector('.userstab .urow', { timeout: 15000 });

  const rows = () => page.$$eval('.userstab .urow', rs => rs.map(r => ({
    name: r.dataset.user,
    text: r.textContent.replace(/\s+/g, ' ').trim(),
    remove: !!r.querySelector('[data-uremove]'),
    deadRemove: [...r.querySelectorAll('button')].some(
      b => b.textContent.trim() === 'Remove' && b.disabled),
    role: !!r.querySelector('[data-urole]'),
  })));
  let rs = await rows();
  const owner = rs.find(r => r.name === 'test');
  ok(owner && /owner/.test(owner.text), 'the tab lists the owner');
  ok(owner && !owner.remove && owner.deadRemove && !owner.role,
     '...with no delete and no role picker, because neither is allowed');
  ok(owner && /cannot be deleted/.test(owner.text),
     '...and it says why rather than offering a control that would fail');

  // Adding somebody, from the tab rather than from a shell.
  await page.fill('#uNewName', 'tabmade');
  await page.fill('#uNewPw', 'tabmadepw1');
  await page.selectOption('#uNewRole', 'user');
  // A reload landing between typing and Add repaints the tab; what was
  // typed survives it (B422: it emptied the form, and Add sent nothing).
  await page.evaluate(async () => { await loadUsers(); });
  ok(await page.$eval('#uNewName', e => e.value) === 'tabmade' && await page.$eval('#uNewPw', e => e.value) === 'tabmadepw1',
     'what is typed into Add somebody survives the list being drawn again');
  await page.click('#uAdd');
  await page.waitForFunction(() => !!document.querySelector(
    '.userstab .urow[data-user="tabmade"]'), null, { timeout: 15000 });
  ok(true, 'Add makes an account from the tab');

  // Which Anthropic account each BuilderBot account is signed in as, taken
  // from the record a node reported, since no login lives here (R47), and two
  // on one login said out loud, since Anthropic's terms allow one person per
  // Claude account.
  rs = await rows();
  ok(rs.filter(r => r.name !== 'test').every(r => /no Claude login yet/.test(r.text)),
     'a row says when its account has no Claude login yet');
  const uidOf = (await (await bare('/api/users', { headers: {
      Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json())
    .users.find(u => u.name === 'tabmade').uid;
  const grant = (home, email) => {
    mkdirSync(`${home}/.claude`, { recursive: true });
    writeFileSync(`${home}/.claude/.bb-grant.json`, JSON.stringify({
      nodes: { n_fixture: { email, plan: 'max', at: 1 } } }));
  };
  const seed = readFileSync(`${DIR}/home/.claude/.bb-grant.json`, 'utf8');
  grant(`${DIR}/home/users/${uidOf}`, 'one@example.invalid');
  grant(`${DIR}/home`, 'one@example.invalid');
  await page.evaluate(() => loadUsers());
  await page.waitForFunction(() => /signed in to Claude as one@example.invalid/.test(
    document.querySelector('.userstab .urow[data-user="tabmade"]')?.textContent || ''), null, { timeout: 25000 });
  rs = await rows();
  ok(/same Claude account as tabmade/.test(rs.find(r => r.name === 'test').text)
     && /same Claude account as test/.test(rs.find(r => r.name === 'tabmade').text),
     'two BuilderBot accounts on one Claude login are told so on both rows');
  rmSync(`${DIR}/home/users/${uidOf}/.claude/.bb-grant.json`, { force: true });
  // The owner's seed goes back: the rest of this file reads the fixture
  // node as signed in, and a Claude press on a node that is not goes to its
  // sign-in instead of to a session.
  writeFileSync(`${DIR}/home/.claude/.bb-grant.json`, seed);

  // ...and giving it a project, which is the whole point of the row.
  // Everything about an account is edited in one dialog and saved together:
  // the projects it sees, its role, its name and email, a new password.
  await page.click('.userstab .urow[data-user="tabmade"] [data-uedit]');
  await page.waitForSelector('#umodal:not([hidden])');
  await page.check('#umodal [data-ueproj="alpha"]');
  await page.fill('#umodal #ueFull', 'Tab Made');
  await page.fill('#umodal #ueEmail', 'not-an-email');
  await page.click('#umodal #ueSave');
  await page.waitForFunction(() => !document.getElementById('ueErrWrap').hidden, null, { timeout: 10000 });
  ok(/not an email/.test(await page.$eval('#ueErr', e => e.textContent)),
     'the edit dialog refuses an email that is not one, and stays open');
  await page.fill('#umodal #ueEmail', 'tab@example.invalid');
  await page.click('#umodal #ueSave');
  await page.waitForFunction(() => {
    const r = document.querySelector('.userstab .urow[data-user="tabmade"]');
    return r && /alpha/.test(r.textContent) && document.getElementById('umodal').hidden;
  }, null, { timeout: 15000 });
  ok(true, '...and the project picker in it gives the account one');
  // A role change is the same dialog, the same Save.
  await page.click('.userstab .urow[data-user="tabmade"] [data-uedit]');
  await page.waitForSelector('#umodal:not([hidden])');
  await page.selectOption('#umodal #ueRole', 'admin');
  ok(await page.$eval('.userstab .urow[data-user="tabmade"] .pill', p => p.textContent.trim()) === 'user',
     'picking a role in the dialog writes nothing until Save');
  await page.click('#umodal #ueSave');
  await page.waitForFunction(() => document.querySelector(
    '.userstab .urow[data-user="tabmade"] .pill')?.textContent.trim() === 'admin', null, { timeout: 15000 });
  ok(true, '...and Save is what writes it');
  await page.click('.userstab .urow[data-user="tabmade"] [data-uedit]');
  await page.waitForSelector('#umodal:not([hidden])');
  await page.selectOption('#umodal #ueRole', 'user');
  await page.click('#umodal #ueSave');
  await page.waitForFunction(() => document.querySelector(
    '.userstab .urow[data-user="tabmade"] .pill')?.textContent.trim() === 'user', null, { timeout: 15000 });

  // The account it made is real, and scoped.
  const as = (path) => bare(path, { headers: {
    Authorization: 'Basic ' + Buffer.from('tabmade:tabmadepw1').toString('base64') } });
  const seen = await (await as('/api/status')).json();
  ok(JSON.stringify((seen.projects || []).map(p => p.name)) === '["alpha"]',
     `...and that account signs in seeing only it (${
       (seen.projects || []).map(p => p.name).join(', ')})`);
  // ...on every read, including the one that used to pass the name straight
  // through (bug #68): the memory tab's fetch.
  const memOk = await as('/api/memory?project=alpha');
  const memNo = await as('/api/memory?project=delta');
  ok(memOk.status === 200 && memNo.status === 400,
     `the memory read answers for its project and refuses another (${memOk.status}, ${memNo.status})`);

  // The owner cannot be removed through the door either, not just in the page.
  const refused = await bare('/api/users', { method: 'POST',
    headers: { 'Content-Type': 'application/json',
               Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') },
    body: JSON.stringify({ action: 'remove', name: 'test' }) });
  ok(refused.status === 400 && /cannot be deleted/.test((await refused.json()).error || ''),
     'and the store refuses it too, so bb users is held to the same rule');

  // A `user` cannot reach this tab's verbs at all.
  const notYours = await bare('/api/users', { method: 'POST',
    headers: { 'Content-Type': 'application/json',
               Authorization: 'Basic ' + Buffer.from('tabmade:tabmadepw1').toString('base64') },
    body: JSON.stringify({ action: 'add', name: 'sneaky', password: 'sneakypw1' }) });
  ok(notYours.status === 403, 'accounts are an administrator\'s');

  await page.click('.userstab .urow[data-user="tabmade"] [data-uremove]');
  await page.waitForFunction(() => !document.querySelector(
    '.userstab .urow[data-user="tabmade"]'), null, { timeout: 15000 });
  ok((await as('/api/status')).status === 401,
     'Remove ends it: the account it made can no longer sign in');
}

// ---- what a session holds (roadmap #22 step 4, bug #16) -----------------
// A Claude session used to inherit DASHBOARD_AUTH, so "only the operator may
// install a toolchain" was a rule the code asked nicely about. It gets a token
// scoped to its own project instead.
{
  const { execFileSync } = await import('node:child_process');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const mint = (proj) => execFileSync('python3', ['-c', `
import importlib.util, json, os
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
def wj(p, d):
    tmp = str(p) + ".tmp"; open(tmp, "w").write(json.dumps(d, indent=2)); os.replace(tmp, p)
u.configure(state="${DIR}/state", write_json=wj)
print(u.${proj})`], { encoding: 'utf8' }).trim();

  const tok = mint('mint_session("alpha")');
  const as = (path, opts = {}) => bare(path, { ...opts,
    headers: { Authorization: 'Bearer ' + tok, ...(opts.headers || {}) } });
  const post = (path, body) => as(path, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  const seen = await (await as('/api/status')).json();
  ok(JSON.stringify((seen.projects || []).map(p => p.name)) === '["alpha"]',
     `a session token sees its own project and no other (${
       (seen.projects || []).map(p => p.name).join(', ')})`);
  ok(/not a project/.test(((await (await post('/api/roadmap',
       { action: 'save', project: 'ep.silon', items: [] })).json()).error) || ''),
     '...and another project reads as absent, not refused');

  // Parking a roadmap item is one direction for a session. It knows when
  // something is blocked or waiting on somebody; it does not know why the
  // operator wants one back, so taking it OFF the shelf is theirs. The CLI
  // only ever passed on=true, and this door used to take whatever it was
  // handed.
  {
    const added = await (await post('/api/roadmap',
      { action: 'add', project: 'alpha', text: 'something to park' })).json();
    const id = (added.items || []).slice(-1)[0]?.id ?? added.id;
    const on = await (await post('/api/roadmap',
      { action: 'shelve', project: 'alpha', id, on: true })).json();
    ok(!on.error, `a session may park a roadmap item (${on.error || 'shelved'})`);
    // ...and asking for it back is held for a person on the project (R78),
    // the item still shelved: the door used to refuse outright.
    const off = await post('/api/roadmap', { action: 'shelve', project: 'alpha', id, on: false, why: 'unblocked' });
    const offBody = await off.json();
    ok(off.status === 200 && offBody.held?.verb === 'unshelve' && /unblocked/.test(offBody.held?.summary || '')
       && (offBody.items || []).find(r => r.id === id)?.shelved,
       `...and asking for it back is held for approval, the item still shelved (${(offBody.held?.summary || offBody.error || '').slice(0, 60)})`);
    const still = await (await as('/api/status')).json();
    ok((still.projects || []).length === 1, '...with the refusal leaving the rest answering');
  }

  // The scanner's report covers the whole share, so the Analysis surfaces are
  // the one place a session could read somebody else's code back. The fixture
  // report has a finding in alpha, in beta, in gamma, in delta, in two
  // directories that are not projects, and one whose path places nowhere.
  {
    const fp = await (await as('/api/findings')).json();
    const rows = (fp.reports || []).flatMap(r => r.findings || []);
    ok(rows.length === 1 && rows[0].project === 'alpha' && rows[0].rule === 'A1',
       `a session's findings are its own project's and no other (${
         rows.map(r => `${r.project || '?'}:${r.rule}`).join(', ') || 'none'})`);
    // Said of the whole payload, not just the rows: a project name in a
    // subtitle or a count is the same leak in a smaller font.
    const blob = JSON.stringify(fp);
    const leaked = ['beta', 'gamma', 'delta', 'toolstore', 'vendored-junk', 'entirely.py']
      .filter(w => blob.includes(w));
    ok(leaked.length === 0,
       `...and nothing else on the share is named anywhere in the payload (${
         leaked.join(', ') || 'nothing leaked'})`);
    ok(!('aside' in fp),
       '...not even how many findings were held back, which would move when somebody else edits their code');
    ok(JSON.stringify(fp.projects || []) === '["alpha"]',
       `...and the projects it lists are its own (${JSON.stringify(fp.projects || [])})`);
    // The same question of the poll, which carries its own copy of the counts.
    const stat = await (await as('/api/status')).json();
    ok(Object.keys(stat.findings_counts || {}).join(',') === 'alpha',
       `the poll's finding counts are its project's alone (${
         Object.keys(stat.findings_counts || {}).join(',') || 'none'})`);
  }

  // The whole reason this exists: it is not the operator.
  for (const ep of ['/api/v1/nodes', '/api/toolchains', '/api/users']) {
    ok((await post(ep, { action: 'x' })).status === 403, `${ep} is closed to a session`);
  }
  // A session works on its project and its project's node, and changes
  // neither: the settings that hold its own additions and name its node are
  // the operator's, and a node named in a request is a machine the token
  // was never bound to.
  ok((await post('/api/prefs', { project: 'alpha', gate: { roadmap: 'auto' } })).status === 403,
     'a session cannot change its project\'s settings');
  // Nor queue a job at all (R35): a job runs as the node's enrolled account,
  // outside the session's view, so its own node is no better than another.
  for (const [what, body] of [['on its own node', { action: 'run', project: 'alpha', argv: ['true'] }],
                              ['on another node', { action: 'run', project: 'alpha', node: 'n_elsewhere', argv: ['true'] }],
                              ['for the emulator', { action: 'emu', project: 'alpha', argv: ['emu', 'list'] }]]) {
    const r = await post('/api/v1/jobs', body);
    ok(r.status === 403 && /outside the session's view/.test((await r.json()).error || ''),
       `...nor queue a job ${what}, since a job runs outside the session's view (${r.status})`);
  }
  const jl = await (await as('/api/v1/jobs?n=50')).json();
  ok(Array.isArray(jl.jobs) && jl.jobs.every(j => j.project === 'alpha'),
     `the job list a session reads holds its project's jobs and no other (${jl.jobs?.length ?? '?'})`);
  ok((await as('/api/v1/jobs?id=j_nothing')).status === 404, '...and a job it may not see is absent, not refused');
  // ...but the phone's `ask` is exactly what a session does, and the control
  // on it is that the operator reads the reason and decides.
  const asked = await post('/api/phone', { action: 'ask', why: 'a test', argv: ['devices'] });
  ok(asked.status !== 403, `a session may still ask for the phone (${asked.status})`);
  ok((await post('/api/phone', { action: 'pair' })).status === 403,
     '...while pairing it stays the operator\'s');

  // Rotating the key takes every session token at once, which is the
  // granularity that matters, since they are minted fresh per connection.
  mint('revoke_sessions()');
  ok((await as('/api/status')).status === 401,
     'revoking the session key invalidates a token already handed out');

  // ...and the operator is untouched by any of it.
  ok((await bare('/api/status', { headers: {
       Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).status === 200,
     'none of which touches the owner');
}

// ---- the Profile tab: an account's own settings -----------------------
// Anybody signed in, about themselves only: name and email, the git identity
// their commits carry, and a password change that asks for the current one
// first: a browser left signed in is not enough to lock its owner out. The
// throwaway account, because the suite's own credential must keep working.
{
  // Made here: the tabmade account above was removed by the flow that tests
  // removing one.
  await page.evaluate(async () => (await fetch('/api/users', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'add', name: 'profiled', password: 'tabmadepw1', role: 'user' }) })).json());
  const H = pw => ({ Authorization: 'Basic ' + Buffer.from(`profiled:${pw}`).toString('base64'),
                     'Content-Type': 'application/json' });
  const api = async (pw, body) => {
    const r = await fetch(URL.replace(/\/$/, '') + '/api/profile',
      body ? { method: 'POST', headers: H(pw), body: JSON.stringify(body) } : { headers: H(pw) });
    return { status: r.status, body: await r.json().catch(() => ({})) };
  };
  const me = await api('tabmadepw1');
  ok(me.status === 200 && me.body.name === 'profiled' && me.body.role === 'user',
     'a user reads its own profile, which the admin gate does not cover');
  const saved = await api('tabmadepw1', { action: 'save', profile: { full_name: 'Tab Made', email: 'tab@example.invalid' } });
  ok(saved.status === 200 && saved.body.git.name === 'Tab Made' && saved.body.git.email === 'tab@example.invalid',
     '...and sets its name and email, which its commits then carry');
  const wrong = await api('tabmadepw1', { action: 'password', current: 'nope-nope', password: 'tabmadepw2' });
  ok(wrong.status === 400 && /current password/.test(wrong.body.error || ''),
     'a password change with the wrong current password is refused');
  const right = await api('tabmadepw1', { action: 'password', current: 'tabmadepw1', password: 'tabmadepw2' });
  ok(right.status === 200 && (await api('tabmadepw2')).status === 200 && (await api('tabmadepw1')).status === 401,
     '...and with the right one the new password signs in and the old one does not');
  // The Profile tab itself, on the owner's page, and the Administration card
  // beside it: the card is an administrator's and this page is one.
  await page.evaluate(() => openProfileTab());
  await page.waitForSelector('.profiletab .setrow', { timeout: 15000 });
  ok(await page.$eval('.profiletab', el => /test/.test(el.textContent) && !!el.querySelector('#pfSave')
                                          && !!el.querySelector('#pfPasswd')),
     'the Profile tab names the account and carries Save and Change password');
  ok(await page.$eval('#cardAdmin', el => !el.hidden && !!el.querySelector('#bSettings') && !!el.querySelector('#bUsers')),
     'the Administration card holds Controller settings and Users, and an administrator sees it');
  // The ? beside a label opens on a tap as well as a hover, so a phone reads
  // it: a click toggles it, and a tap anywhere else closes it.
  await page.click('.profiletab .help');
  const tipped = await page.$eval('.profiletab .help.on', el => getComputedStyle(el, '::after').content);
  ok(/at least 8 characters|sign in with/.test(tipped),
     `a tap on the ? shows its tooltip without a hover (${tipped.slice(0, 40)})`);
  await page.click('.profiletab h4');
  ok(!(await page.$('.profiletab .help.on')), '...and a tap elsewhere closes it');
  // ...and on a phone the box stays on the screen: it is placed in viewport
  // coordinates and pushed inside the edge, not centered on an icon at it.
  await page.setViewportSize({ width: 393, height: 851 });
  await page.evaluate(() => setView('terminal'));     // a phone shows one column at a time
  await page.waitForSelector('.profiletab .help', { state: 'visible', timeout: 10000 });
  await page.click('.profiletab .help');
  // Wait for the box to have a width, not for a hundred milliseconds: the
  // ::after is laid out a frame or two after the class lands, and on a busy
  // box it is later than that, which read back as `auto`, came out of
  // parseFloat as NaN, and failed a rule about placement with a number
  // nobody could place.
  // Measured in the same read that waits for it: a second read after the
  // wait could meet a redrawn tooltip with no width yet, and came back NaN
  // in a whole run (B397).
  const fit = await (await page.waitForFunction(() => {
    const el = document.querySelector('.profiletab .help.on');
    if (!el) return null;
    const cs = getComputedStyle(el, '::after');
    const w = parseFloat(cs.width), x = parseFloat(el.style.getPropertyValue('--tipx'));
    return w > 0 && Number.isFinite(x) ? { x, right: x + w, pos: cs.position, vw: innerWidth } : null;
  }, null, { timeout: 10000 })).jsonValue();
  ok(fit.pos === 'fixed' && fit.x >= 0 && fit.right <= fit.vw,
     `on a phone the tooltip is placed inside the screen (${Math.round(fit.x)}..${Math.round(fit.right)} of ${fit.vw})`);
  await page.click('.profiletab h4');
  await page.setViewportSize({ width: 1280, height: 800 });
  // No author, no terminal and no git: an account with no name and email
  // is refused a shell as well as a session at the door, and bb git for it
  // is refused on the relay: every project is a repository, and a shell is
  // where git is typed. The account made above has no author until it is
  // given one; then everything opens.
  {
    const noauthor = { Authorization: 'Basic ' + Buffer.from('noauthor:tabmadepw1').toString('base64') };
    await page.evaluate(async () => (await fetch('/api/users', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'add', name: 'noauthor', password: 'tabmadepw1', role: 'admin' }) })).json());
    const sh = await bare('/term/ws?arg=sh:1:beta', { headers: noauthor });
    ok(sh.status === 409 && /no name and email/.test((await sh.json()).error || ''),
       'an account with no author is refused a shell at the door, and told where to set one');
    // fetch writes with git and wants an author; a policy read and an
    // ls-remote do not, and answer for the same account (B128).
    const git = await bare('/api/v1/bb', { method: 'POST',
      headers: { ...noauthor, 'Content-Type': 'application/json' },
      body: JSON.stringify({ argv: ['git', 'fetch'], cwd: `${DIR}/ws/beta` }) });
    ok(git.status === 403 && /no name and email/.test((await git.json()).error || ''),
       '...and bb git fetch for it is refused on the relay');
    const pol = await bare('/api/v1/bb', { method: 'POST',
      headers: { ...noauthor, 'Content-Type': 'application/json' },
      body: JSON.stringify({ argv: ['git', 'policy'], cwd: `${DIR}/ws/beta` }) });
    ok(pol.status !== 403, `...while bb git policy, a read, answers it (${pol.status})`);
    // The status payload says whether the account administers this
    // controller, which is what words an empty Projects card for a user
    // with nothing granted rather than telling them the share is missing.
    const plain = await bare('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') },
      body: JSON.stringify({ action: 'add', name: 'plainone', password: 'plainonepw1', role: 'user' }) });
    const asUser = await (await bare('/api/status', { headers: { Authorization: 'Basic ' + Buffer.from('plainone:plainonepw1').toString('base64') } })).json();
    const asOwner = await (await bare('/api/status', { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json();
    ok(plain.status === 200 && asUser.admin === false && asOwner.admin === true,
       `the status payload carries admin: ${asUser.admin} for a user, ${asOwner.admin} for the owner`);
    // A plain account cannot queue a job with its password either: a job
    // runs outside every view as the node's own account, in the docker
    // group, which is what a session was already refused (R35).
    for (const body of [{ action: 'run', project: 'alpha', argv: ['true'] },
                        { action: 'emu', project: 'alpha', argv: ['emu', 'list'] }]) {
      const r = await bare('/api/v1/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json',
        Authorization: 'Basic ' + Buffer.from('plainone:plainonepw1').toString('base64') }, body: JSON.stringify(body) });
      const why = r.status === 403 ? ((await r.json()).error || '') : '';
      ok(r.status === 403 && /administrator's/.test(why),
         `a plain account cannot queue a ${body.action} job, which would run outside every view (${r.status}: ${why.slice(0, 50)})`);
    }
    // ...nor stop or clear the project job (B171): a clone or a link is the
    // create dialog's, and so is its Abort and its Dismiss.
    const plainAuth = { 'Content-Type': 'application/json',
      Authorization: 'Basic ' + Buffer.from('plainone:plainonepw1').toString('base64') };
    for (const action of ['abort', 'dismiss']) {
      const r = await bare('/api/project-job', { method: 'POST', headers: plainAuth, body: JSON.stringify({ action }) });
      ok(r.status === 403, `a plain account cannot ${action} the project job somebody else started (${r.status})`);
    }
    ok(JSON.stringify(asUser.project_job) === '{}' && typeof asOwner.project_job?.running === 'boolean',
       `...and its status carries no project job to draw, while an administrator's does (${JSON.stringify(asUser.project_job)})`);
    // B172: a session is its owner's. The name says whose (u_<uid>~...),
    // and the owner's own here keep bare names; nobody ends, keys or types
    // into anybody else's. Decided before the session is looked up, so a
    // name is enough to ask with.
    const ownerAuth = { 'Content-Type': 'application/json', Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
    const act = async (h, path, body) => {
      const r = await bare(path, { method: 'POST', headers: h, body: JSON.stringify(body) });
      return { status: r.status, error: ((await r.json().catch(() => ({}))).error || '') };
    };
    for (const [path, body] of [['/api/keys', { session: 'claude-alpha', key: 'enter' }],
                                ['/api/session', { action: 'kill', session: 'claude-alpha' }],
                                ['/api/send', { session: 'shell-alpha-1', macro: 'status' }]]) {
      const r = await act(plainAuth, path, body);
      ok(r.status === 403 && /not yours/.test(r.error), `a plain account cannot use ${path} on the owner's session (${r.status})`);
    }
    const other = await act(ownerAuth, '/api/keys', { session: 'u_0badf00d~claude-alpha', key: 'enter' });
    ok(other.status === 403, `...nor can the owner press a key in another account's session (${other.status})`);
    const own = await act(ownerAuth, '/api/keys', { session: 'claude-alpha', key: 'enter' });
    ok(own.status !== 403, `...while the owner still reaches their own (${own.status}: ${own.error.slice(0, 40)})`);
    const { execFileSync: ef } = await import('node:child_process');
    const ownerUid = JSON.parse((await import('node:fs')).readFileSync(`${DIR}/state/users.json`, 'utf8')).users.test.uid;
    const stok = ef('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", "${new globalThis.URL('..', import.meta.url).pathname}users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state="${DIR}/state", write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
print(u.mint_session("alpha", uid="${ownerUid}"))`], { encoding: 'utf8' }).trim();
    const sessAuth = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + stok };
    const across = await act(sessAuth, '/api/keys', { session: 'claude-beta', key: 'enter' });
    ok(across.status === 403, `a session's token cannot reach its own account's session on another project (${across.status})`);
    const home = await act(sessAuth, '/api/keys', { session: 'claude-alpha', key: 'enter' });
    ok(home.status !== 403, `...and does reach its own project's (${home.status})`);
    // B173-B175: what acts on a project by name asks the right as well as
    // the name. A plain account given alpha cannot lock it, move the shared
    // pins, read how its remote authenticates, or move its version; the
    // version panel is closed to a session's token outright.
    await act(ownerAuth, '/api/users', { action: 'projects', name: 'plainone', projects: ['alpha'] });
    for (const [path, body, why] of [
        ['/api/lock', { name: 'alpha', locked: true }, /administrator's/],
        ['/api/pin', { name: 'status', pinned: true }, /administrator's/],
        ['/api/project-auth', { name: 'alpha' }, /administrator's|rename/],
        ['/api/version', { project: 'alpha', action: 'bump', part: 'patch' }, /administrator's/],
        ['/api/version', { project: 'alpha', action: 'policy', policy: 'any' }, /administrator's/],
        ['/api/signing', { project: 'alpha', action: 'put', route: 'sideload', keystore: 'eA==', password: 'p' }, /administrator's/]]) {
      const r = await act(plainAuth, path, body);
      ok(r.status === 403 && why.test(r.error), `a plain account cannot ${path} ${body.action || ''} (${r.status}: ${r.error.slice(0, 50)})`);
    }
    // The project pins are a person's own (the operator, 27 Sep): a plain
    // account unpins alpha from its sidebar and the owner's card still shows
    // it; a session, which has no sidebar, pins for nobody.
    {
      const un = await act(plainAuth, '/api/project-pin', { name: 'alpha', pinned: false });
      const rows = async h => ((await (await fetch(URL.replace(/\/$/, '') + '/api/status', { headers: h })).json()).projects || []);
      const plain = (await rows(plainAuth)).find(p => p.name === 'alpha'), owner = (await rows(ownerAuth)).find(p => p.name === 'alpha');
      ok(un.status === 200 && plain && plain.pinned === false && owner && owner.pinned === true,
         `a plain account's unpin is its own: alpha off its sidebar and still on the owner's (${un.status}; ${plain?.pinned}/${owner?.pinned})`);
      const sess = await act(sessAuth, '/api/project-pin', { name: 'alpha', pinned: true });
      ok(sess.status === 403 && /a session has no sidebar/.test(sess.error || ''), `...and a session pins for nobody (${sess.status})`);
      await act(plainAuth, '/api/project-pin', { name: 'alpha', pinned: true });
    }
    // A project's signing keys (R106): a session never reaches them, not
    // even the listing, and never downloads one; a person who sees the
    // project reads which keys exist and nothing secret.
    {
      const sl = await act(sessAuth, '/api/signing', { project: 'alpha', action: 'list' });
      const sb = await bare('/api/signing-backup?project=alpha&route=play', { headers: sessAuth });
      const plr = await bare('/api/signing', { method: 'POST', headers: plainAuth,
                                              body: JSON.stringify({ project: 'alpha', action: 'list' }) });
      const pl = await plr.json().catch(() => ({}));
      ok(sl.status === 403 && /bb sign/.test(sl.error || '') && sb.status === 403
         && plr.status === 200 && pl.keys && typeof pl.map === 'object' && !JSON.stringify(pl).includes('pass'),
         `a session reaches no signing key, not even the list or a backup, and a person reads only which exist (${sl.status}/${sb.status}/${plr.status})`);
    }
    // bb sign (R106 step 3): a session asks only to sign its own project's
    // build, under its dial. A key and a build are put in place for it; the
    // session never reads either back. Ask (the default) waits on the
    // project's owner, Deny names the setting, and nothing it cannot sign
    // is put in front of anybody.
    {
      mkdirSync(`${DIR}/state/signing/alpha`, { recursive: true });
      writeFileSync(`${DIR}/state/signing/alpha/sideload.ks`, 'k');
      writeFileSync(`${DIR}/state/signing/alpha/sideload.json`, JSON.stringify({ alias: 'upload', store_pass: 'pw' }));
      mkdirSync(`${DIR}/ws/alpha/dist`, { recursive: true });
      writeFileSync(`${DIR}/ws/alpha/dist/alpha-release.apk`, 'apk');
      const sign = (body) => bare('/api/signing', { method: 'POST', headers: sessAuth,
        body: JSON.stringify({ action: 'sign', project: 'alpha', ...body }) }).then(async r => ({ status: r.status, body: await r.json().catch(() => ({})) }));
      const noNode = await sign({ file: 'alpha-release.apk', route: 'sideload', why: 'for testers' });
      // A node named, for the ask: nothing is queued before it is answered.
      const setNode = await (await bare('/api/prefs', { method: 'POST', headers: ownerAuth,
        body: JSON.stringify({ project: 'alpha', node: 'n_signtest' }) })).json().catch(() => ({}));
      const noKey = await sign({ file: 'alpha-release.apk', route: 'play', why: 'for Play' });
      const noFile = await sign({ file: 'nope.apk', route: 'sideload', why: 'for testers' });
      const asked = await sign({ file: 'alpha-release.apk', route: 'sideload', why: 'for testers' });
      const ownerAsks = await (await bare('/api/phone', { headers: ownerAuth })).json();
      const ask = (ownerAsks.asks || []).find(a => a.id === asked.body.id);
      ok(/no node to sign on/.test(noNode.body.error || '') && !setNode.error
         && /no Play upload key/.test(noKey.body.error || '') && /bb build/.test(noFile.body.error || '')
         && asked.status === 200 && asked.body.id && ask && ask.kind === 'sign'
         && ask.cmd.join(' ') === 'sign alpha-release.apk --for sideload',
         `a session's bb sign waits on the project's owner, and what it could not sign is refused before anybody is asked (${asked.body.to || JSON.stringify(asked.body)}; ${JSON.stringify(setNode).slice(0, 80)})`);
      await bare('/api/phone', { method: 'POST', headers: ownerAuth, body: JSON.stringify({ action: 'deny', id: asked.body.id }) });
      await bare('/api/prefs', { method: 'POST', headers: ownerAuth, body: JSON.stringify({ project: 'alpha', sign: 'deny' }) });
      const denied = await sign({ file: 'alpha-release.apk', route: 'sideload', why: 'for testers' });
      const other = await bare('/api/signing', { method: 'POST', headers: sessAuth,
        body: JSON.stringify({ action: 'sign', project: 'beta', file: 'x.apk', route: 'sideload', why: 'w' }) });
      ok(denied.status === 403 && /Sign a release/.test(denied.body.error || '') && other.status === 403,
         `...at Deny it is refused naming the setting, and another project's build is never its to sign (${denied.status}/${other.status})`);
      // Managing keys (R106 step 6): at Ask a new key or a mapping waits on
      // the owner too, and a session reads which keys exist but no secret.
      const listed = await sign({ action: 'keys' });
      const newKey = await sign({ action: 'generate', key: 'watch', route: 'sideload', why: 'the watch app' });
      const rot = await sign({ action: 'rotate', from: 'default', to: 'watch', why: 'move the app to the new key' });
      const ownerAsks2 = await (await bare('/api/phone', { headers: ownerAuth })).json();
      const keyAsk = (ownerAsks2.asks || []).find(a => a.id === newKey.body.id);
      const rotAsk = (ownerAsks2.asks || []).find(a => a.id === rot.body.id);
      await bare('/api/prefs', { method: 'POST', headers: ownerAuth, body: JSON.stringify({ project: 'alpha', keys: 'deny' }) });
      const noKeys = await sign({ action: 'map', package: 'com.example.watch', key: 'watch', why: 'w' });
      ok(listed.status === 200 && 'default' in (listed.body.keys || {}) && !JSON.stringify(listed.body).includes('"pw"')
         && keyAsk && keyAsk.kind === 'sign-key' && keyAsk.cmd.join(' ') === 'sign key new watch --for sideload'
         && rotAsk && rotAsk.cmd.join(' ') === 'sign rotate default watch'
         && noKeys.status === 403 && /Manage signing keys/.test(noKeys.body.error || ''),
         `...a session reads the keys without a secret, proposes a new one for the owner to allow, and at Deny is refused naming the setting (${keyAsk?.cmd?.join(' ')})`);
      for (const a of [keyAsk, rotAsk]) if (a) await bare('/api/phone', { method: 'POST', headers: ownerAuth, body: JSON.stringify({ action: 'deny', id: a.id }) });
      await bare('/api/prefs', { method: 'POST', headers: ownerAuth, body: JSON.stringify({ project: 'alpha', sign: 'ask', keys: 'ask', node: '' }) });
      rmSync(`${DIR}/state/signing/alpha`, { recursive: true, force: true });
      // ...and how busy a node is (R108), for its own project only.
      const nb = await bare('/api/node-busy?project=beta', { headers: sessAuth });
      ok(nb.status === 403, `a session asks how busy only its own project's nodes are (${nb.status})`);
    }
    // A project's owner and its people (membership.py, the operator, 1 Oct).
    // Invite only keeps an administrator from adding themselves; BuilderBot's
    // owner is never kept out; people join by accepting an invitation.
    {
      const post = async (h, path, body) => {
        const r = await bare(path, { method: 'POST', headers: h, body: JSON.stringify(body) });
        return { status: r.status, body: await r.json().catch(() => ({})) };
      };
      await post(ownerAuth, '/api/users', { action: 'add', name: 'adminone', password: 'adminonepw1', role: 'admin' });
      const adminAuth = { 'Content-Type': 'application/json',
        Authorization: 'Basic ' + Buffer.from('adminone:adminonepw1').toString('base64') };
      // A key's backup goes to an administrator ON the project (the
      // operator, 1 Oct): adminone sees alpha and is not on it.
      {
        mkdirSync(`${DIR}/state/signing/alpha/default`, { recursive: true });
        writeFileSync(`${DIR}/state/signing/alpha/default/sideload.ks`, 'k');
        writeFileSync(`${DIR}/state/signing/alpha/default/sideload.json`, JSON.stringify({ alias: 'a', store_pass: 'pw', sha256: 'AB' }));
        const off = await bare('/api/signing-backup?project=alpha&route=sideload', { headers: adminAuth });
        const offMsg = await off.json().catch(() => ({}));
        const on = await bare('/api/signing-backup?project=alpha&route=sideload', { headers: ownerAuth });
        const listOff = await post(adminAuth, '/api/signing', { action: 'list', project: 'alpha' });
        const listOn = await post(ownerAuth, '/api/signing', { action: 'list', project: 'alpha' });
        ok(off.status === 403 && /add it to your own projects/.test(offMsg.error || '') && on.status === 200
           && listOff.body.may_backup === false && listOn.body.may_backup === true,
           `a signing key's backup is an administrator's on the project only, and the dialog offers it only to them (${off.status}/${on.status})`);
        rmSync(`${DIR}/state/signing/alpha`, { recursive: true, force: true });
      }
      const view = await post(ownerAuth, '/api/members', { action: 'view', project: 'gamma' });
      const set = await post(ownerAuth, '/api/members', { action: 'set', project: 'gamma', invite_only: true });
      const self = await post(adminAuth, '/api/users', { action: 'projects', name: 'adminone', projects: ['gamma'] });
      const notOwner = await post(adminAuth, '/api/members', { action: 'set', project: 'gamma', invite_only: false });
      ok(view.status === 200 && view.body.owner === 'test' && set.body.invite_only === true
         && /invite only/.test(self.body.error || '') && notOwner.status === 403,
         `gamma belongs to the owner, who makes it invite only, and an administrator then cannot add themselves to it or lift that (${view.body.owner}; ${(self.body.error || '').slice(0, 60)})`);
      const inv = await post(ownerAuth, '/api/members', { action: 'invite', project: 'gamma', name: 'adminone' });
      const st = await (await bare('/api/status', { headers: adminAuth })).json();
      const mine = (st.invites || []).find(i => i.project === 'gamma');
      const acc = mine ? await post(adminAuth, '/api/members', { action: 'accept', id: mine.id }) : { status: 0, body: {} };
      const after = await post(ownerAuth, '/api/members', { action: 'view', project: 'gamma' });
      ok(inv.status === 200 && mine && mine.by === 'test' && acc.body.joined === true
         && after.body.members.includes('adminone') && !after.body.invites.length,
         `...the owner invites them, the invitation waits in their status for the bell, and accepting puts them on it (${after.body.members.join(', ')})`);
      // Handing it on: BuilderBot's owner moves it at once; its own owner
      // offers it, and it changes hands when the other accepts.
      const moved = await post(ownerAuth, '/api/members', { action: 'set', project: 'gamma', owner: 'adminone' });
      const offer = await post(adminAuth, '/api/members', { action: 'set', project: 'gamma', owner: 'plainone' });
      const pst = await (await bare('/api/status', { headers: plainAuth })).json();
      const off = (pst.invites || []).find(i => i.project === 'gamma' && i.kind === 'owner');
      const took = off ? await post(plainAuth, '/api/members', { action: 'accept', id: off.id }) : { body: {} };
      const now = await post(ownerAuth, '/api/members', { action: 'view', project: 'gamma' });
      ok(moved.body.owner === 'adminone' && offer.body.owner === 'adminone' && offer.body.offered === 'plainone'
         && off && off.by === 'adminone' && took.body.owner === true && now.body.owner === 'plainone',
         `BuilderBot's owner hands a project on at once; its own owner offers it, and it moves when accepted (${moved.body.owner} -> offered ${offer.body.offered} -> ${now.body.owner})`);
      await post(ownerAuth, '/api/members', { action: 'set', project: 'gamma', owner: 'test' });
      const sessM = await act(sessAuth, '/api/members', { action: 'view', project: 'alpha' });
      ok(sessM.status === 403, `...and a session has no say in who joins a project (${sessM.status})`);
      await post(ownerAuth, '/api/members', { action: 'set', project: 'gamma', invite_only: false });
    }
    const lockBeta = await act(plainAuth, '/api/lock', { name: 'beta', locked: true });
    ok(lockBeta.status === 400 && /not a project/.test(lockBeta.error),
       `...nor lock a project it was not given, which it is not told exists (${lockBeta.status})`);
    const vs = await act(sessAuth, '/api/version', { project: 'alpha', action: 'policy', policy: 'any' });
    ok(vs.status === 403 && /bb version bump/.test(vs.error),
       `a session's token cannot use the version panel, where it could loosen its own policy (${vs.status})`);
    await bare('/api/profile', { method: 'POST', headers: { ...noauthor, 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'save', profile: { full_name: 'No Author', email: 'na@example.invalid' } }) });
    ok((await bare('/term/ws?arg=sh:1:beta', { headers: noauthor })).status !== 409,
       '...and a name and email on the Profile open the door');
    await page.evaluate(async () => (await fetch('/api/users', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'remove', name: 'noauthor' }) })).json());
  }
  // Made here, removed here: users.json is not reset between files.
  await page.evaluate(async () => (await fetch('/api/users', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'remove', name: 'profiled' }) })).json());
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
// ---- the route tables ------------------------------------------------------
// Routes are matched in order and a prefix route takes every path it
// prefixes, so one listed after a shorter prefix of itself is never reached:
// /api/pin and /api/project-pin were that once, found only because the two
// handlers also shared a name. Read from both tables (R60), with each method
// they name checked to exist, since a typo there is a 500 on first use.
{
  const got = JSON.parse(execFileSync('python3', ['-c', `
import ast, json, re
src = open(${JSON.stringify(new globalThis.URL('../server.py', import.meta.url).pathname)}).read()
out = {}
for table in ("GET_ROUTES", "POST_ROUTES"):
    m = re.search(r'^' + table + r' = (\\(.*?^\\))', src, re.S | re.M)
    routes = ast.literal_eval(m.group(1))
    out[table] = {"routes": routes,
                  "missing": [n for _, _, n in routes if not re.search(r"^    def " + n + r"\\(self", src, re.M)]}
print(json.dumps(out))`], { encoding: 'utf8' }));
  for (const [table, t] of Object.entries(got)){
    const shadowed = [];
    t.routes.forEach(([how, path], i) => t.routes.slice(i + 1).forEach(([, later]) => {
      if (how === 'prefix' && later.startsWith(path)) shadowed.push(`${later} after ${path}`);
    }));
    ok(t.routes.length > 30 && shadowed.length === 0,
       `no ${table} route is taken by an earlier prefix (${t.routes.length} routes${shadowed.length ? ': ' + shadowed.join(', ') : ''})`);
    ok(t.missing.length === 0,
       `...and every method ${table} names is one the handler has (${t.missing.join(', ') || 'all there'})`);
  }
}

await done(browser);
