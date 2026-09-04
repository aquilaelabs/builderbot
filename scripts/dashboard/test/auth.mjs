// One login for everything: the /login landing page, the cookie it mints,
// the challenge-free 401s that keep the browser's own dialog away, and the
// /term proxy that puts the terminals behind the same sign-in. The proxy's
// upstream is dead in the harness (nothing listens on the ttyd port), which
// pins the 502 path; the live relay is covered by using the dashboard.
import { launch, newPage, ok, done, URL, DIR } from './lib.mjs';
import http from 'node:http';

// Plain fetches first — no credentials at all, straight from node.
const bare = async (path, opts = {}) =>
  fetch(URL.replace(/\/$/, '') + path, { redirect: 'manual', ...opts });

// ...but not for the page itself, which needs node:http instead of fetch.
// undici's parser asserts — `assert(!this.paused)` — and takes the whole
// process down when a body bigger than its buffer meets a connection close,
// and every response here ends in one: Python's BaseHTTPRequestHandler speaks
// HTTP/1.0 and closes after each. It is latent until the body is large enough,
// so this file died the day the dashboard page crossed 128KiB gzipped, having
// sat 119 bytes under it — and it died by CRASHING, after printing that every
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

// Big answers travel gzipped when the client takes it — the page and the
// status snapshot a phone polls every 15s — and small ones as they are.
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
// bytes to spare, so the twelve colour schemes were the feature that met it.
// Raised to a number the ratio would fail long before — which is the check
// that actually means something.
ok(r.headers.get('content-encoding') === 'gzip'
   && zipped < plain / 2 && zipped < 250000,
   `the page travels gzipped, at a fraction of its size (${Math.round(zipped/1024)}kB of ${Math.round(plain/1024)}kB)`);
r = await bare('/api/status', { headers: { ...AUTHH, 'Accept-Encoding': 'identity' } });
ok(!r.headers.get('content-encoding'), 'a client that cannot take gzip gets plain bytes');

// A browser with preemptive basic auth (bb shot, curl -u, these tests) still
// works exactly as before — the whole page, no login step.
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
// ends the session — landing on the login page and staying out.
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
// is not consulted again. Nothing is restricted yet — that is step 2 — so
// what is checked here is the store standing where the string used to.
//
// Everything below works on a SECOND account. The first version changed the
// owner's password and could not put it back, because `test` is under the
// eight-character floor the store enforces — which would have taken the
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

// ---- a strip each (roadmap #25) --------------------------------------------
// The tab layout was ONE file for the whole box: written by whichever browser
// saved last and handed to every other one. Fine for one operator, wrong the
// moment there are two — you would watch somebody else's tabs open in front
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

  // ---- one Claude session per project, and whose (roadmap #26) -------------
  // bb-tty has always named the session for the project, so there has only
  // ever been one. What accounts made necessary is knowing WHOSE: without it
  // a second person pressing Claude lands inside somebody else's conversation
  // and types into it. Enforced at the /term proxy rather than only in the
  // page, because the ttyd URL is reachable directly.
  {
    const { execFileSync: run } = await import('node:child_process');
    const tmux = a => run('tmux', a, { encoding: 'utf8',
      env: { ...process.env, TMUX_TMPDIR: `${DIR}/tmux`, TMUX: '' } });
    const term = (h, arg) => bare('/term/ws?arg=' + encodeURIComponent(arg), { headers: h });
    // No session yet: nobody holds it, and asking is allowed.
    ok((await term(other, 'claude:beta')).status !== 409,
       'with no session running, the project is nobody\'s');
    try { tmux(['kill-session', '-t', 'claude-beta']); } catch { /* none */ }
    tmux(['new-session', '-d', '-s', 'claude-beta', '-c', '/tmp']);
    // The account that claimed it may come back to it...
    ok((await term(other, 'claude:beta')).status !== 409,
       'the account that opened it can reattach');
    // ...and nobody else may, by name.
    const refused = await term(owner, 'claude:beta');
    const why = refused.status === 409 ? (await refused.json()).error : '';
    ok(refused.status === 409 && /has a Claude session on beta/.test(why),
       `another account is refused, and told who has it (${why.slice(0, 60)}…)`);
    ok(/one conversation per project/.test(why),
       '...and why, since the rule is not obvious from the refusal alone');
    // A shell on the same project is not affected: shells are per account.
    ok((await term(owner, 'sh:1:beta')).status !== 409,
       'a shell on that project is still offered — only the conversation is held');
    // The session ending releases it, with nothing to sweep: the record is
    // only read alongside the live session list.
    tmux(['kill-session', '-t', 'claude-beta']);
    ok((await term(owner, 'claude:beta')).status !== 409,
       'ending the session releases it, because the live session is the truth');
  }

  // A rename must not lose the strip — the whole reason the key is minted.
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
// ABSENT, not refused — so the existence check and the permission check are
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

  const mine = await (await as('/api/status')).json();
  const names = (mine.projects || []).map(p => p.name);
  ok(names.includes('alpha') && !names.includes('ep.silon') && names.length === 1,
     `a user's state carries only the projects they were given (${names.join(', ')})`);
  const all = await (await bare('/api/status', { headers: {
    Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json();
  ok((all.projects || []).length > names.length,
     '...while the owner still sees every one of them');

  // A project they were not given does not exist, and says so in the words a
  // typo gets — never "forbidden", which would confirm it is there.
  const hidden = await (await post('/api/todo', { action: 'save', project: 'ep.silon', items: [] })).json();
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
                              ['/api/packages', { action: 'install', names: ['jdk'] }],
                              ['/api/phone', { action: 'connect' }]]) {
    const r3 = await post(path, body);
    ok(r3.status === 403, `${path} is an administrator's`);
  }
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
  await page.click('#uAdd');
  await page.waitForFunction(() => !!document.querySelector(
    '.userstab .urow[data-user="tabmade"]'), null, { timeout: 15000 });
  ok(true, 'Add makes an account from the tab');

  // ...and giving it a project, which is the whole point of the row.
  await page.click('.userstab .urow[data-user="tabmade"] [data-uprojects]');
  await page.waitForSelector('.userstab .upick [data-uproj]', { timeout: 10000 });
  await page.check('.userstab .upick [data-uproj="alpha"]');
  await page.click('.userstab [data-usave="tabmade"]');
  await page.waitForFunction(() => {
    const r = document.querySelector('.userstab .urow[data-user="tabmade"]');
    return r && /alpha/.test(r.textContent);
  }, null, { timeout: 15000 });
  ok(true, '...and the project picker gives it one');

  // The account it made is real, and scoped.
  const as = (path) => bare(path, { headers: {
    Authorization: 'Basic ' + Buffer.from('tabmade:tabmadepw1').toString('base64') } });
  const seen = await (await as('/api/status')).json();
  ok(JSON.stringify((seen.projects || []).map(p => p.name)) === '["alpha"]',
     `...and that account signs in seeing only it (${
       (seen.projects || []).map(p => p.name).join(', ')})`);

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
// install a package" was a rule the code asked nicely about. It gets a token
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
  ok(/not a project/.test(((await (await post('/api/todo',
       { action: 'save', project: 'ep.silon', items: [] })).json()).error) || ''),
     '...and another project reads as absent, not refused');

  // The whole reason this exists: it is not the operator.
  for (const ep of ['/api/v1/nodes', '/api/packages', '/api/users']) {
    ok((await post(ep, { action: 'x' })).status === 403, `${ep} is closed to a session`);
  }
  // ...but the phone's `ask` is exactly what a session does, and the control
  // on it is that the operator reads the reason and decides.
  const asked = await post('/api/phone', { action: 'ask', why: 'a test', argv: ['devices'] });
  ok(asked.status !== 403, `a session may still ask for the phone (${asked.status})`);
  ok((await post('/api/phone', { action: 'pair' })).status === 403,
     '...while pairing it stays the operator\'s');

  // Rotating the key takes every session token at once — which is the
  // granularity that matters, since they are minted fresh per connection.
  mint('revoke_sessions()');
  ok((await as('/api/status')).status === 401,
     'revoking the session key invalidates a token already handed out');

  // ...and the operator is untouched by any of it.
  ok((await bare('/api/status', { headers: {
       Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).status === 200,
     'none of which touches the owner');
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
