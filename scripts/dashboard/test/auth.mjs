// One login for everything: the /login landing page, the cookie it mints,
// the challenge-free 401s that keep the browser's own dialog away, and the
// /term proxy that puts the terminals behind the same sign-in. The proxy's
// upstream is dead in the harness (nothing listens on the ttyd port), which
// pins the 502 path; the live relay is covered by using the dashboard.
import { launch, newPage, ok, done, URL } from './lib.mjs';
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

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
