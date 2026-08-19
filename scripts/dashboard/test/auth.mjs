// One login for everything: the /login landing page, the cookie it mints,
// the challenge-free 401s that keep the browser's own dialog away, and the
// /term proxy that puts the terminals behind the same sign-in. The proxy's
// upstream is dead in the harness (nothing listens on the ttyd port), which
// pins the 502 path; the live relay is covered by using the dashboard.
import { launch, newPage, ok, done, URL } from './lib.mjs';

// Plain fetches first — no credentials at all, straight from node.
const bare = async (path, opts = {}) =>
  fetch(URL.replace(/\/$/, '') + path, { redirect: 'manual', ...opts });

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
await ctx2.close();

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
