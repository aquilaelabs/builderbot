// The link path against a REAL forge (roadmap R54, step 3): the lab's Gitea,
// which tools/lab/docker-compose.yml brings up. Everything the harness's
// create.mjs cannot prove with stand-ins is proved here: the token check on
// GET /api/v1/user, a repository created under an organisation and under the
// account, a push authenticating on a stored credential line with a port and
// a plain-http scheme, the refusal of a repository that is not empty, and the
// refusal to create under somebody else's name.
//
// Skipped in one line without BB_LAB_GITEA: a lab suite never runs in CI and
// never fails for the service being absent. `bb lab status` prints the
// environment; `bb tests lab` runs this.
//
// What it makes on the forge it removes again (the repositories and the
// token it minted), so it can run twice. The fixture project it links is
// beta (no remote, one commit made here); delta is the second, for the
// refusals.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const GITEA = (process.env.BB_LAB_GITEA || '').replace(/\/$/, '');
if (!GITEA){
  console.log('SKIP  lab-forge: BB_LAB_GITEA is not set (bb lab up, then bb lab status)');
  process.exit(0);
}
const USER = process.env.BB_LAB_USER || 'labadmin';
const PASS = process.env.BB_LAB_PASS || 'labpassword';
const HOST = GITEA.replace(/^https?:\/\//, '');
const SCHEME = GITEA.startsWith('https://') ? 'https' : 'http';
const stamp = Date.now().toString(36);

// ---- the forge, directly ---------------------------------------------------
const basic = 'Basic ' + Buffer.from(`${USER}:${PASS}`).toString('base64');
let token = '', tokenId = 0;
const forge = async (method, path, body, auth = null) => {
  const r = await fetch(`${GITEA}/api/v1${path}`, {
    method, headers: { 'Content-Type': 'application/json',
                       Authorization: auth || (token ? `token ${token}` : basic) },
    body: body ? JSON.stringify(body) : undefined });
  let j = null;
  try { j = await r.json(); } catch { j = null; }
  return { status: r.status, body: j };
};
{
  const v = await forge('GET', '/version');
  ok(v.status === 200 && v.body?.version, `the lab's Gitea answers at ${GITEA} (${v.body?.version})`);
  const t = await forge('POST', `/users/${USER}/tokens`,
    { name: `bb-lab-${stamp}`, scopes: ['write:repository', 'write:organization', 'read:user'] });
  ok(t.status === 201 && t.body?.sha1, `a token is minted for the run by signing in as ${USER} (${t.status})`);
  token = t.body?.sha1 || ''; tokenId = t.body?.id || 0;
  const org = await forge('GET', '/orgs/lab');
  if (org.status !== 200){
    const made = await forge('POST', '/orgs', { username: 'lab', visibility: 'private' });
    ok(made.status === 201, `the lab organisation exists (${made.status})`);
  } else ok(true, 'the lab organisation exists');
}

// ---- the dashboard ---------------------------------------------------------
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, b ? { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                 body: JSON.stringify(b) } : {});
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [path, body]);
// A project job (link, clone) runs in the background; this is its outcome.
const jobDone = async (ms = 120000) => {
  const until = Date.now() + ms;
  for (;;){
    const j = (await api('/api/project-job')).body;
    if (!j.running) return j;
    if (Date.now() > until) return { ...j, error: 'still running after ' + ms + 'ms' };
    await new Promise(r => setTimeout(r, 500));
  }
};
const git = (dir, ...args) => execFileSync('git', ['-C', `${DIR}/ws/${dir}`, ...args],
  { encoding: 'utf8', env: { ...process.env, GIT_AUTHOR_NAME: 'lab', GIT_AUTHOR_EMAIL: 'lab@example.invalid',
                             GIT_COMMITTER_NAME: 'lab', GIT_COMMITTER_EMAIL: 'lab@example.invalid' } }).trim();
git('beta', 'add', '-A'); git('beta', 'commit', '-q', '-m', 'lab: the commit the link pushes');
const sha = git('beta', 'rev-parse', 'HEAD');
const made = [];   // owner/repo pairs to delete at the end

// A repository under the organisation, created by the link because it does
// not exist yet, then the commit pushed over the stored credential.
{
  const repo = `lab/beta-${stamp}`;
  const r = await api('/api/link', { name: 'beta', url: `${GITEA}/${repo}`, forge: 'gitea', token });
  ok(r.status === 200 && r.body.started, `linking beta to ${repo} starts the job (${r.status}: ${r.body.error || 'ok'})`);
  const j = await jobDone();
  ok(!j.error && /created lab\/beta-.* on Gitea/.test(j.note || '') && /pushed/.test(j.note || ''),
     `...which creates the repository under the organisation and pushes (${j.error || j.note})`);
  made.push(repo);
  const got = await forge('GET', `/repos/${repo}`);
  ok(got.status === 200 && got.body?.private === true, 'the forge has it, and it is private');
  const head = await forge('GET', `/repos/${repo}/commits?limit=1`);
  ok(head.status === 200 && head.body?.[0]?.sha === sha, `...with the commit that was pushed (${head.body?.[0]?.sha?.slice(0, 7)})`);
  const line = existsSync(`${DIR}/state/gitcreds/beta`) ? readFileSync(`${DIR}/state/gitcreds/beta`, 'utf8').trim() : '';
  ok(line === `${SCHEME}://${USER}:${token}@${HOST}`,
     `the credential line names the account the forge reported, the scheme and the host with its port (${line.replace(/:[^@]*@/, ':…@')})`);
  const cfg = readFileSync(`${DIR}/ws/beta/.git/config`, 'utf8');
  ok(cfg.includes(`url = ${GITEA}/${repo}.git`) && /credential\]\s*\n\s*helper = \n\s*helper = store --file=/.test(cfg),
     'the remote is spelled as asked and the repository is scoped to its own token and nothing else');
  // A second link to the same repository is refused: it is not empty now.
  git('delta', 'add', '-A'); git('delta', 'commit', '-q', '-m', 'lab: delta');
  const again = await api('/api/link', { name: 'delta', url: `${GITEA}/${repo}`, forge: 'gitea', token });
  const jj = await jobDone();
  ok(again.status === 200 && /not empty/.test(jj.error || ''),
     `a repository that already holds commits is refused, so nothing is overwritten (${jj.error || jj.note})`);
  ok(!readFileSync(`${DIR}/ws/delta/.git/config`, 'utf8').includes('[remote'),
     '...and no remote was added to the project that asked');
}

// Unlinked, then linked again under the ACCOUNT rather than the organisation:
// the fallback to the token's own account, taken only because the owner is
// that account.
{
  const u = await api('/api/unlink', { name: 'beta' });
  ok(u.status === 200 && !existsSync(`${DIR}/state/gitcreds/beta`),
     'unlinking takes the remote and the stored token off');
  const repo = `${USER}/beta-again-${stamp}`;
  const r = await api('/api/link', { name: 'beta', url: `${GITEA}/${repo}`, forge: 'gitea', token });
  const j = await jobDone();
  ok(r.status === 200 && !j.error && /created/.test(j.note || ''),
     `linking again under the account creates the repository there (${j.error || j.note})`);
  made.push(repo);
  const got = await forge('GET', `/repos/${repo}`);
  ok(got.status === 200, 'the forge has that one too');
  await api('/api/unlink', { name: 'beta' });
}

// Somebody else's name is refused, not silently created under the account.
{
  const repo = `nobody-${stamp}/x`;
  const r = await api('/api/link', { name: 'delta', url: `${GITEA}/${repo}`, forge: 'gitea', token });
  const j = await jobDone();
  ok(r.status === 200 && /is not an organisation this token can create in/.test(j.error || ''),
     `a path under a name that is neither an organisation nor the account is refused with the reason (${(j.error || j.note || '').slice(0, 120)})`);
  const got = await forge('GET', `/repos/${USER}/x`);
  ok(got.status === 404, '...and nothing was created under the account instead');
}

// A token the forge does not accept is refused before anything is written.
{
  const r = await api('/api/link', { name: 'delta', url: `${GITEA}/lab/never-${stamp}`, forge: 'gitea',
                                     token: 'deadbeefdeadbeefdeadbeefdeadbeefdeadbeef' });
  ok(r.status === 400 && /does not accept that token/.test(r.body.error || ''),
     `a token the forge rejects is refused at the press (${r.body.error})`);
}

// ---- what this made, removed ----------------------------------------------
for (const repo of made){
  const d = await forge('DELETE', `/repos/${repo}`);
  ok(d.status === 204, `removed ${repo} from the forge`);
}
if (tokenId){
  const d = await forge('DELETE', `/users/${USER}/tokens/${tokenId}`, null, basic);
  ok(d.status === 204, 'the run\'s token is revoked');
}
await done(browser);
