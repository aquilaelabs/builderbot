// The link path against a REAL forge (roadmap R54, step 3): the lab's Gitea,
// the `gitea` service of BuilderBot's own dev stack under its compose file's
// `lab` profile, brought up from the Docker tab like any project's stack. Everything the harness's
// create.mjs cannot prove with stand-ins is proved here: the token check on
// GET /api/v1/user, a repository created under an organization and under the
// account, a push authenticating on a stored credential line with a port and
// a plain-http scheme, the refusal of a repository that is not empty, and the
// refusal to create under somebody else's name.
//
// Skipped in one line without BB_LAB_GITEA: a lab suite never runs in CI and
// never fails for the service being absent. `bb tests lab` sets it and
// runs this.
//
// What it makes on the forge it removes again (the repositories and the
// token it minted), so it can run twice. The fixture project it links is
// beta (no remote, one commit made here); delta is the second, for the
// refusals.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { readFileSync, existsSync, writeFileSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const GITEA = (process.env.BB_LAB_GITEA || '').replace(/\/$/, '');
if (!GITEA){
  console.log('SKIP  lab-forge: BB_LAB_GITEA is not set (bb tests lab sets it)');
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
    // write:user as well: creating a repository under the ACCOUNT goes
    // through POST /user/repos, which Gitea gates on that scope (measured
    // on 1.24: "required=[write:user]"). The link dialog's hint says so.
    { name: `bb-lab-${stamp}`, scopes: ['write:repository', 'write:organization', 'write:user'] });
  ok(t.status === 201 && t.body?.sha1, `a token is minted for the run by signing in as ${USER} (${t.status})`);
  token = t.body?.sha1 || ''; tokenId = t.body?.id || 0;
  const org = await forge('GET', '/orgs/lab');
  if (org.status !== 200){
    const made = await forge('POST', '/orgs', { username: 'lab', visibility: 'private' });
    ok(made.status === 201, `the lab organization exists (${made.status})`);
  } else ok(true, 'the lab organization exists');
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

// A repository under the organization, created by the link because it does
// not exist yet, then the commit pushed over the stored credential.
{
  const repo = `lab/beta-${stamp}`;
  const r = await api('/api/link', { name: 'beta', url: `${GITEA}/${repo}`, forge: 'gitea', token });
  ok(r.status === 200 && r.body.started, `linking beta to ${repo} starts the job (${r.status}: ${r.body.error || 'ok'})`);
  const j = await jobDone();
  ok(!j.error && /created lab\/beta-.* on Gitea/.test(j.note || '') && /pushed/.test(j.note || ''),
     `...which creates the repository under the organization and pushes (${j.error || j.note})`);
  made.push(repo);
  const got = await forge('GET', `/repos/${repo}`);
  ok(got.status === 200 && got.body?.private === true, 'the forge has it, and it is private');
  // Asked of git, not of the database: Gitea syncs branches into its
  // database after a push on a queue, so for a few seconds /branches answers
  // nothing and /commits says the repository is empty (measured on 1.24).
  const c = await forge('GET', `/repos/${repo}/git/commits/${sha}`);
  ok(c.status === 200 && c.body?.sha === sha,
     `...with the commit that was pushed (${c.status}: ${c.body?.sha?.slice(0, 7) || JSON.stringify(c.body)?.slice(0, 80)})`);
  // git's own credential store rewrites the file after a push that
  // authenticated, in its own spelling (lowercase percent-encoding of the
  // host's colon), so the line is compared decoded.
  const line = existsSync(`${DIR}/state/gitcreds/beta`)
    ? decodeURIComponent(readFileSync(`${DIR}/state/gitcreds/beta`, 'utf8').trim().split('\n')[0]) : '';
  ok(line === `${SCHEME}://${USER}:${token}@${HOST}`,
     `the credential line names the account the forge reported, the scheme and the host with its port (${line.replace(/:[^@]*@/, ':…@')})`);
  const cfg = readFileSync(`${DIR}/ws/beta/.git/config`, 'utf8');
  ok(cfg.includes(`url = ${GITEA}/${repo}.git`) && /credential\]\s*\n\s*helper = \n\s*helper = store --file=/.test(cfg),
     'the remote is spelled as asked and the repository is scoped to its own token and nothing else');
  // Release on the real forge (R124): a version, a changelog section and a
  // build of the commit, then the Artifacts tab's Release. The tag is pushed
  // and Gitea's release is made beside it with the section as its notes and
  // the build attached, all over the token the link stored.
  const v = await api('/api/version', { project: 'beta', action: 'init', value: '0.1.0' });
  ok(v.status === 200, `beta gets its first version (${v.status}: ${v.body.error || 'ok'})`);
  writeFileSync(`${DIR}/ws/beta/CHANGELOG.md`, '# Changelog\n\n## 0.1.0: 2026-10-05\n\n### Added\n\n- The lab release\n');
  writeFileSync(`${DIR}/ws/beta/.gitignore`, 'dist/\n');
  mkdirSync(`${DIR}/ws/beta/docs`, { recursive: true });
  writeFileSync(`${DIR}/ws/beta/docs/shot.png`, Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kAAAAABJRU5ErkJggg==', 'base64'));
  git('beta', 'add', '-A'); git('beta', 'commit', '-q', '-m', 'lab: 0.1.0');
  const short = git('beta', 'rev-parse', '--short=7', 'HEAD');
  mkdirSync(`${DIR}/ws/beta/dist`, { recursive: true });
  const apk = `beta-0.1.0-${short}-release.apk`;
  writeFileSync(`${DIR}/ws/beta/dist/${apk}`, 'lab build');
  const rel = await api('/api/version', { project: 'beta', action: 'release' });
  const fg = rel.body.released?.forge || {};
  ok(rel.status === 200 && rel.body.released?.pushed && fg.made && fg.forge === 'Gitea',
     `Release pushes v0.1.0 and makes Gitea's release beside it (${rel.status}: ${rel.body.error || fg.error || fg.url})`);
  const on = await forge('GET', `/repos/${repo}/releases/tags/v0.1.0`);
  ok(on.status === 200 && on.body?.name === '0.1.0' && /- The lab release/.test(on.body?.body || ''),
     `...titled with the version, its notes the changelog's section (${on.status}: ${JSON.stringify(on.body?.body || on.body)?.slice(0, 80)})`);
  ok((on.body?.assets || []).some(a => a.name === apk && a.size === 9),
     `...and the commit's build attached (${(on.body?.assets || []).map(a => `${a.name} ${a.size}`).join(', ') || 'none'})`);
  ok(fg.url === on.body?.html_url, `the release's address comes back to the page (${fg.url})`);
  // ...and the Artifacts view's version block links to it, though a Gitea
  // on a LAN serves it over plain http (B505: only https was linked).
  await page.evaluate(() => openNotebook('beta', 'artifacts'));
  const link = await page.waitForFunction(() => {
    const ln = [...document.querySelectorAll('.verln')].find(x => /^on Gitea/.test(x.textContent.trim()));
    return ln?.querySelector('a')?.href || '';
  }, null, { timeout: 15000 }).then(h => h.jsonValue()).catch(() => '');
  ok(link === fg.url, `the version block says on Gitea and links to the release (${link || 'no link'})`);
  // ...then edited (R139): the notes replaced, a committed screenshot
  // attached and shown in them by (asset:NAME), and an edit again replaces
  // the file of that name rather than doubling it.
  const notes = '## 0.1.0\n\nThe lab release.\n\n![The screen](asset:shot.png)\n';
  const ed = await api('/api/version', { project: 'beta', action: 'release-edit', notes, attach: ['docs/shot.png'] });
  const after = await forge('GET', `/repos/${repo}/releases/tags/v0.1.0`);
  const shot = (after.body?.assets || []).find(a => a.name === 'shot.png');
  // The address Gitea gave the upload (its /attachments/ one, the same file
  // its listing names under /releases/download/), asked for the picture.
  const shown = ((after.body?.body || '').match(/!\[The screen\]\((http[^)]+)\)/) || [])[1] || '';
  const img = shown ? await fetch(shown, { headers: { Authorization: `token ${token}` } }) : null;
  const bytes = img?.ok ? (await img.arrayBuffer()).byteLength : 0;
  ok(ed.status === 200 && ed.body.edited?.attached?.includes('shot.png') && shot && bytes === 70
     && !/asset:/.test(after.body?.body || '') && (after.body?.assets || []).some(a => a.name === apk),
     `an edit replaces the notes and attaches the screenshot they show, keeping the build (${ed.status}: ${ed.body.error || ed.body.said}; the page says ${JSON.stringify(after.body?.body)}, the file is at ${shot?.browser_download_url}, files ${(after.body?.assets || []).map(a => a.name).join(', ')})`);
  const ed2 = await api('/api/version', { project: 'beta', action: 'release-edit', attach: ['docs/shot.png'] });
  const after2 = await forge('GET', `/repos/${repo}/releases/tags/v0.1.0`);
  ok(ed2.status === 200 && ed2.body.edited?.replaced?.includes('shot.png')
     && (after2.body?.assets || []).filter(a => a.name === 'shot.png').length === 1,
     `...and a second attach of the same name replaces it (${(after2.body?.assets || []).map(a => a.name).join(', ')})`);
  // A file comes off only by its own removal, named as the forge lists it
  // (the operator, 5 Oct); a name the release does not have is refused
  // before anything is asked of it, and the build stays.
  const none = await api('/api/version', { project: 'beta', action: 'release-remove', remove: ['nope.png'] });
  const rm = await api('/api/version', { project: 'beta', action: 'release-remove', remove: ['shot.png'] });
  const after3 = await forge('GET', `/repos/${repo}/releases/tags/v0.1.0`);
  const left = (after3.body?.assets || []).map(a => a.name);
  ok(none.status === 400 && /has no nope\.png; it has/.test(none.body.error || '') && rm.status === 200
     && !left.includes('shot.png') && left.includes(apk),
     `a removal takes the named file off the release and nothing else, and a name it does not have is refused first (${none.body.error}; left ${left.join(', ')})`);
  const twice = await api('/api/version', { project: 'beta', action: 'release' });
  ok(twice.status === 400 && /already exists/.test(twice.body.error || ''),
     'a second Release is refused at the tag, so nothing is made twice');
  // A second link to the same repository is refused: it is not empty now.
  git('delta', 'add', '-A'); git('delta', 'commit', '-q', '-m', 'lab: delta');
  const again = await api('/api/link', { name: 'delta', url: `${GITEA}/${repo}`, forge: 'gitea', token });
  const jj = await jobDone();
  ok(again.status === 200 && /not empty/.test(jj.error || ''),
     `a repository that already holds commits is refused, so nothing is overwritten (${jj.error || jj.note})`);
  ok(!readFileSync(`${DIR}/ws/delta/.git/config`, 'utf8').includes('[remote'),
     '...and no remote was added to the project that asked');
}

// Unlinked, then linked again under the ACCOUNT rather than the organization:
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
  ok(r.status === 200 && /is not an organization this token can create in/.test(j.error || ''),
     `a path under a name that is neither an organization nor the account is refused with the reason (${(j.error || j.note || '').slice(0, 120)})`);
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
