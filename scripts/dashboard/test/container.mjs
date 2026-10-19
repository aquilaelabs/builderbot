// A container asked for by a session (roadmap R71): the root shape applied
// to docker. The session writes a compose file and hands it over with a
// reason; the request waits on the administrators, and nobody else, in the
// bell; Allow registers it through the Docker tab's own New container path
// and starts its build; Deny says no. The session never runs docker and
// nothing runs until somebody has read the file.
//
// The harness's stub docker answers `compose config` and the build job, the
// way devapp.mjs's New container tests use it, so this file proves the
// asking, the routing, the reading and the answering.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync, rmSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const base = URL.replace(/\/$/, '');
const asUser = (u, pw) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${pw}`).toString('base64'),
                             'Content-Type': 'application/json' });
const owner = asUser('test', 'test');
const api = async (path, body, headers = owner) => {
  const r = await fetch(base + path, body === undefined ? { headers }
    : { method: 'POST', headers, body: JSON.stringify(body) });
  return { status: r.status, body: await r.json() };
};
const COMPOSE = 'services:\n  app:\n    image: alpine\n    command: sleep 1\n';
const ask = (extra, headers = owner) => api('/api/phone', {
  action: 'ask', kind: 'container', why: 'a sonarr to test the media project against',
  name: 'sonarr-for-alpha', compose: COMPOSE, env: 'PUID=99\nSECRET=hunter2\n',
  project: 'alpha', ...extra }, headers);

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

const sandbox = (await api('/api/v1/nodes')).body.nodes.find(n => n.name === 'sandbox');
await api('/api/prefs', { project: 'alpha', node: sandbox.id });

// ---- what is refused before anybody is asked -------------------------------
ok(/say what the container is for/.test((await ask({ why: '' })).body.error || ''),
   'an ask with no reason is refused: Allow on an unexplained container is a guess');
ok(/needs a name/.test((await ask({ name: '' })).body.error || ''),
   '...and one with no name');
ok(/hand over the compose file/.test((await ask({ compose: '   ' })).body.error || ''),
   '...and one with nothing to build');
ok(/no node called nowhere/.test((await ask({ node: 'nowhere' })).body.error || ''),
   '...and one naming a machine that is not a node, before it reaches anybody');
ok(/not a project: zeta/.test((await ask({ for: 'zeta' })).body.error || ''),
   '...and one for a project the asker cannot see');

// ---- a second account, of the kind that is never asked --------------------
execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', 'visitor', '--role', 'user'],
  { input: 'visitorpass1\nvisitorpass1\n', encoding: 'utf8',
    env: { ...process.env, DASHBOARD_STATE: `${DIR}/state` } });
const other = asUser('visitor', 'visitorpass1');
await api('/api/users', { action: 'projects', name: 'visitor', projects: ['alpha'] });

// ---- the ask, who sees it, and what they see --------------------------------
const asked = await ask({});
ok(asked.body.id > 0 && /administrators/.test(asked.body.to || ''),
   `a container ask goes to the administrators, whoever asks (${asked.body.to})`);
const mine = (await api('/api/phone')).body.asks.find(a => a.id === asked.body.id);
ok(mine && mine.kind === 'container' && mine.name === 'sonarr-for-alpha' && mine.node_name === 'sandbox'
   && mine.detail === COMPOSE,
   'the administrator sees the request with the compose file whole, since the file is the request');
ok(JSON.stringify(mine.env_keys) === JSON.stringify(['PUID', 'SECRET'])
   && !JSON.stringify(mine).includes('hunter2'),
   "...and the env file's keys but never its values, which is where a token would be");
ok(!(await api('/api/phone', undefined, other)).body.asks.some(a => a.id === asked.body.id),
   'a user account is not asked: a container is docker-write on a node, which no user holds');
ok((await api('/api/phone', { action: 'allow', id: asked.body.id }, other)).body.error,
   '...and cannot answer it either way');

// ---- where it shows: the bell, with the file under the reason ----------------
await page.waitForFunction(
  () => { const d = document.querySelector('#bBell .dot');
          return d && !d.hidden && d.classList.contains('ask'); }, null, { timeout: 15000 });
await page.click('#bBell');
await page.waitForSelector('#bellPanel .bnote.ask', { timeout: 10000 });
const bell = await page.$eval('#bellPanel .bnote.ask', e => ({
  text: e.textContent, file: e.querySelector('.bdetail pre')?.textContent || '',
  sum: e.querySelector('.bdetail summary')?.textContent || '' }));
ok(/container sonarr-for-alpha on sandbox/.test(bell.text) && /a sonarr to test/.test(bell.text)
   && bell.file === COMPOSE && /PUID, SECRET/.test(bell.sum) && !/hunter2/.test(bell.text),
   `the bell row names the container and the node, and folds the compose file under the reason (${
     bell.sum})`);
// Approve is read at a glance: its text against its own fill at the
// contrast body text needs (WCAG's 4.5), in every theme (the operator, 5 Oct:
// green on amber).
{
  const low = await page.evaluate(async () => {
    const lum = c => { const [r, g, b] = c.match(/[\d.]+/g).slice(0, 3).map(v => v / 255)
      .map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const out = [];
    const was = document.documentElement.dataset.theme;
    const themes = new Set(['default']);
    for (const sh of document.styleSheets){
      let rules = [];
      try { rules = [...sh.cssRules]; } catch { rules = []; }
      for (const r of rules) for (const m of (r.selectorText || '').matchAll(/html\[data-theme="([a-z]+)"\]/g)) themes.add(m[1]);
    }
    for (const t of themes){
      document.documentElement.dataset.theme = t;
      const a = document.querySelector('#bellPanel .bnote.ask a[data-ballow]');
      const s = getComputedStyle(a), f = lum(s.color), b = lum(s.backgroundColor);
      const ratio = (Math.max(f, b) + 0.05) / (Math.min(f, b) + 0.05);
      if (ratio < 4.5) out.push(`${t} ${ratio.toFixed(2)}`);
    }
    document.documentElement.dataset.theme = was || '';
    return { out, n: themes.size };
  });
  ok(low.n > 1 && low.out.length === 0, `Approve's text stands out from its fill in each of the ${low.n} themes (${low.out.join(', ') || 'all at 4.5 or more'})`);
}

// ---- Allow: registered through the Docker tab's own path, then built -------
const allowed = await api('/api/phone', { action: 'allow', id: asked.body.id });
const out = (await api('/api/phone', { action: 'outcome', id: asked.body.id })).body;
ok(allowed.body.ok && out.state === 'done' && out.code === 0,
   `Allow registers the container and starts its build, and the session's outcome says so (${
     out.state}: ${out.out})`);
ok((await api('/api/docker')).body.instances.some(i => i.project === 'sonarr-for-alpha'),
   '...and the Containers page lists it, written from the file the administrator read');

// ---- a session's ask belongs to its own project -------------------------------
// So the session that asked can see what it asked for once it exists, and
// work on it as its project's settings allow (the operator, 24 Sep).
{
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
  // The dial at ask: the fixture's default is deny, and a session's is
  // under it (below).
  await api('/api/prefs', { project: 'alpha', devbuild: 'ask' });
  const bySession = await ask({ name: 'sonarr-by-session', project: '' },
    { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok });
  const row = (await api('/api/phone')).body.asks.find(a => a.id === bySession.body.id);
  ok(row && row.for === 'alpha', `a session's ask belongs to its own project when it names none (${row?.for})`);
  await api('/api/phone', { action: 'deny', id: bySession.body.id });
  // ...and it is under the project's Claude may: Run its container (B250,
  // the operator, 24 Sep): refused at deny, made at once at auto when it is
  // the project's own on its own node, and asked at auto all the same for
  // another project or a node it names.
  const S = { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok };
  await api('/api/prefs', { project: 'alpha', devbuild: 'deny' });
  const denied = await ask({ name: 'sonarr-denied-by-dial', project: '' }, S);
  ok(denied.status === 403 && /Run its container/.test(denied.body.error || ''),
     `at deny a session's container is refused, naming the setting (${String(denied.body.error).slice(0, 50)})`);
  await api('/api/prefs', { project: 'alpha', devbuild: 'auto' });
  const made = await ask({ name: 'sonarr-auto', project: '' }, S);
  ok(made.status === 200 && !made.body.id && made.body.name === 'sonarr-auto'
     && (await api('/api/docker')).body.instances.some(i => i.project === 'sonarr-auto' && i.owner === 'alpha'),
     `at auto it is made at once, nobody asked, and the Containers page lists it as the project's (${JSON.stringify(made.body).slice(0, 80)})`);
  const forOther = await ask({ name: 'sonarr-for-beta', project: '', for: 'beta' }, S);
  const onNode = await ask({ name: 'sonarr-on-node', project: '', node: 'sandbox' }, S);
  ok(!forOther.body.id && forOther.body.error && onNode.body.id > 0,
     `while one on a node it names is asked at auto all the same, and one for another project is refused, since a session sees only its own (${
       String(forOther.body.error).slice(0, 40)})`);
  await api('/api/phone', { action: 'deny', id: onNode.body.id });
  await api('/api/prefs', { project: 'alpha', devbuild: 'ask' });
  const askedStill = await ask({ name: 'sonarr-asked', project: '' }, S);
  ok(askedStill.body.id > 0, '...and at ask it is asked');
  await api('/api/phone', { action: 'deny', id: askedStill.body.id });
}

// ---- Deny: reported to the session, nothing made -------------------------------
const again = await ask({ name: 'sonarr-denied' });
await api('/api/phone', { action: 'deny', id: again.body.id });
const no = (await api('/api/phone', { action: 'outcome', id: again.body.id })).body;
ok(no.state === 'denied' && !(await api('/api/docker')).body.instances.some(i => i.project === 'sonarr-denied'),
   'Deny is what the session is told, and nothing is registered');

// ---- the same name twice is refused before it reaches anybody's bell ----------
// It used to be queued, sit on the administrators' bell, and fail at Allow
// with "pick another name", so a person was asked to decide on a request no
// answer could build, and told the wrong way out for the case it met (B309).
const dup = await ask({});
const asks = (await api('/api/phone')).body.asks || [];
ok(dup.status === 400 && /sonarr-for-alpha already exists here/.test(dup.body.error || '')
   && /removes it from the Containers page first|env set/.test(dup.body.error || '')
   && !asks.some(a => a.kind === 'container' && a.name === 'sonarr-for-alpha' && a.state === 'pending'),
   `a name the store already has is refused before the bell, naming the ways forward (${dup.status}: ${
      (dup.body.error || '').slice(0, 70)})`);

// ---- a build from nowhere is refused before anybody is asked -----------------
// A container written here has no project tree behind it, and compose
// resolves its relative paths against its own data directory, which is
// empty: a new project's session wrote its compose at docker/ with
// build: . and asked for it this way, and the build ran in an empty
// directory (B329). Refused before the bell, and by create and Edit, with
// the way a project's own code goes in.
{
  const BUILT = 'services:\n  app:\n    build: .\n    ports:\n      - "8080:80"\n';
  const r = await ask({ name: 'd2-armor-web', compose: BUILT });
  const asks = (await api('/api/phone')).body.asks || [];
  ok(r.status === 400 && /builds app from a relative path/.test(r.body.error || '')
     && /own data directory, which is empty/.test(r.body.error || '')
     && /bb devapp new/.test(r.body.error || '') && /docker-compose\.yml or compose\.yml/.test(r.body.error || '')
     && !asks.some(a => a.kind === 'container' && a.name === 'd2-armor-web'),
     `an ask whose compose builds from a relative path is refused before the bell, naming bb devapp new (${
        r.status}: ${(r.body.error || '').slice(0, 90)})`);
  const made = await api('/api/container', { action: 'create', name: 'd2-armor-web', compose: BUILT, env: '' });
  ok(/builds app from a relative path/.test(made.body.error || '')
     && !(await api('/api/docker')).body.instances.some(i => i.project === 'd2-armor-web'),
     `...and so is the Containers page's New container, leaving nothing registered (${(made.body.error || '').slice(0, 60)})`);
  // An absolute path is a tree the daemon has: made, as before. The stub
  // stands in for compose's answer, since it does not read the file.
  writeFileSync(`${DIR}/dockerstate/bb-buildcheck.config`,
                JSON.stringify({ services: { app: { build: { context: '/srv/app' } } } }));
  const abs = await api('/api/container', { action: 'create', name: 'd2-armor-abs',
                                            compose: 'services:\n  app:\n    build: /srv/app\n', env: '' });
  rmSync(`${DIR}/dockerstate/bb-buildcheck.config`, { force: true });
  ok(abs.body.ok, `...while one building from an absolute path is made as before (${JSON.stringify(abs.body).slice(0, 80)})`);
  // Edit: the same words, and the file it had is kept.
  const ed = await api('/api/container', { action: 'save', name: 'd2-armor-abs', compose: BUILT, env: '' });
  const kept = await api('/api/container', { action: 'read', name: 'd2-armor-abs' });
  ok(/builds app from a relative path/.test(ed.body.error || '') && /\/srv\/app/.test(kept.body.compose || ''),
     `...and Edit refuses the same change, keeping the file it had (${(ed.body.error || '').slice(0, 50)})`);
}
// What counts as relative is compose's own answer, measured against the real
// compose where the node has one: every way of writing a path that moves with
// the project directory, and none of the ways that do not.
{
  const real = ['/usr/bin/docker', '/usr/local/bin/docker'].find(f => existsSync(f));
  if (!real) ok(true, 'skipped: no docker CLI here to ask compose what is relative');
  else {
    const dash = new globalThis.URL('..', import.meta.url).pathname;
    const said = JSON.parse(execFileSync('python3', ['-c', `
import json, sys
sys.path.insert(0, ${JSON.stringify(dash)})
import devapp, containers
devapp.DOCKER = ${JSON.stringify(real)}
devapp.docker_host = lambda: ""
devapp.log_dir = None
b = lambda body: "services:\\n  app:\\n" + body
cases = {"dot": b("    build: .\\n"), "context": b("    build:\\n      context: ./web\\n"),
         "default": b("    build:\\n      dockerfile: Dockerfile\\n"), "up": b("    build: ..\\n"),
         "var": b("    build: \${SRC:-.}\\n"), "absolute": b("    build: /srv/app\\n"),
         "url": b("    build: https://github.com/docker/getting-started.git\\n"),
         "inline": b("    build:\\n      dockerfile_inline: |\\n        FROM alpine\\n"),
         "image": b("    image: nginx\\n"), "envfile": b("    build: .\\n    env_file: .env\\n")}
print(json.dumps({k: containers.relative_builds(v) for k, v in cases.items()}))
`], { encoding: 'utf8', env: { ...process.env, PATH: process.env.PATH } }).trim().split('\n').pop());
    const rel = Object.keys(said).filter(k => said[k].length);
    ok(JSON.stringify(rel.sort()) === JSON.stringify(['context', 'default', 'dot', 'envfile', 'up', 'var']),
       `compose's own answer: relative for . ./web .. the default context and a variable, not for an absolute path, a URL, an inline Dockerfile or an image (${JSON.stringify(said)})`);
  }
}

ok(page.errors.length === 0, 'zero console errors');
await done(browser);
