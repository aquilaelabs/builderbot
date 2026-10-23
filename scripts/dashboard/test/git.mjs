// The notebook's Git view (roadmap R36, step 1). The repository is read out:
// what is changed and not committed, the history as a graph, one commit's
// detail and diff, and the branches with whose worktree sits on which.
// Real git on the fixture repos, read by the checkout's server; nothing
// here writes through the dashboard, because this step has no actions.
import { launch, newPage, ok, done, ready, refreshUntil, tmuxNew, tmuxKill, tmuxCapture, URL, DIR, openFold, member } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdirSync, existsSync, rmSync, readFileSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const B = `${DIR}/ws/beta`;
const git = (...a) => execFileSync('git', ['-C', B, ...a], { encoding: 'utf8' }).trim();
// A history worth a graph: two commits on the main line, a branch off the
// first with one of its own, and a merge back (four lanes' worth of
// edges), plus a session's branch the way session_dir names one, and an
// uncommitted change beside an untracked file.
git('config', 'user.name', 'dashboard test'); git('config', 'user.email', 'test@example.invalid');
const main = git('symbolic-ref', '--short', 'HEAD');
writeFileSync(`${B}/a.txt`, 'one\n'); git('add', 'a.txt'); git('commit', '-q', '-m', 'Add a');
git('checkout', '-q', '-b', 'feature');
writeFileSync(`${B}/f.txt`, 'feature\n'); git('add', 'f.txt'); git('commit', '-q', '-m', 'Feature work');
git('checkout', '-q', main);
writeFileSync(`${B}/a.txt`, 'one\ntwo\n'); git('commit', '-q', '-am', 'Extend a');
git('merge', '-q', '--no-ff', '-m', 'Merge feature', 'feature');
git('branch', 'claude/tabmade');
// ...and one named like a session's for an account that does not exist,
// which is nobody's: the name alone once made it "no-such-account's session".
git('branch', 'claude/no-such-account');
// ...and a branch whose last commit is three days old, because every row of
// the view said "just now" whatever its age: the ms/seconds mix-up below. A
// root commit made with plumbing: --date-order never lists a child before
// its parent, so an old commit on top of today's would still sort first,
// and a checkout would fight the uncommitted a.txt above.
{
  const three = `${Math.floor(Date.now() / 1000) - 3 * 86400} +0000`;
  const blob = execFileSync('git', ['-C', B, 'hash-object', '-w', '--stdin'], { input: 'old\n', encoding: 'utf8' }).trim();
  const tree = execFileSync('git', ['-C', B, 'mktree'], { input: `100644 blob ${blob}\told.txt\n`, encoding: 'utf8' }).trim();
  const old = execFileSync('git', ['-C', B, 'commit-tree', tree, '-m', 'Old work'], { encoding: 'utf8',
    env: { ...process.env, GIT_AUTHOR_DATE: three, GIT_COMMITTER_DATE: three } }).trim();
  git('branch', 'old-work', old);
}
writeFileSync(`${B}/a.txt`, 'one\ntwo\nthree\n');
writeFileSync(`${B}/new.txt`, 'brand new\n');

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);
// claude/tabmade is a session's branch because its account exists (git.py
// branch_owner): made the way the Users tab makes one.
await fetch(URL.replace(/\/$/, '') + '/api/users', { method: 'POST',
  headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' },
  body: JSON.stringify({ action: 'add', name: 'tabmade', password: 'tabmade-pass-1', role: 'user' }) });
await member('tabmade');

// ---- the API, first ---------------------------------------------------------
const api = async q => (await (await fetch(URL.replace(/\/$/, '') + '/api/git?project=beta&' + q,
  { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json());
const st = await api('what=status');
ok(st.branch === main && st.files.some(f => f.path === 'a.txt' && f.state === 'modified')
   && st.files.some(f => f.path === 'new.txt' && f.state === 'untracked'),
   `status names the branch and the uncommitted changes, untracked included (${st.branch}: ${st.files.map(f => f.path).join(',')})`);
const lg = await api('what=log');
ok(lg.commits.length >= 4 && lg.commits[0].subject === 'Merge feature' && lg.commits[0].parents.length === 2,
   `the log is newest first with parents, so a merge shows two (${lg.commits.length} commits)`);
const merge = lg.commits[0];
const sh = await api('what=show&sha=' + merge.sha);
ok(sh.short === merge.short && sh.message.startsWith('Merge feature') && sh.parents.length === 2,
   'one commit answers with its message, author and parents');
const feat = lg.commits.find(c => c.subject === 'Feature work');
const shf = await api('what=show&sha=' + feat.sha);
ok(shf.files.some(f => f.path === 'f.txt' && f.added === 1) && /\+feature/.test(shf.diff),
   '...and its files with counts, and its diff');
ok((await api('what=show&sha=zzz')).error && (await api('what=show&sha=' + 'a'.repeat(41))).error,
   'a sha that is not one is refused, not run');
const df = await api('what=diff&path=a.txt');
ok(/\+three/.test(df.diff), 'a changed file diffs against the last commit');
const dn = await api('what=diff&path=new.txt');
ok(/\+brand new/.test(dn.diff), '...and an untracked file shows whole, as added');
ok((await api('what=diff&path=../../etc/passwd')).error && (await api('what=diff&path=nope.txt')).error,
   'a path the repository does not report is refused');
const br = await api('what=branches');
const names = br.branches.filter(b => !b.remote).map(b => b.name);
ok(br.main === main && names.includes('feature') && names.includes('claude/tabmade')
   && br.branches.find(b => b.name === main)?.head === true,
   `the branches come with which one the tree is on (${names.join(',')})`);
ok(br.branches.find(b => b.name === 'claude/tabmade')?.who === 'tabmade',
   "...and a session's branch says whose");
ok(br.branches.find(b => b.name === 'claude/no-such-account')?.who === '',
   "...and a claude/ branch whose account does not exist is nobody's");
ok(br.branches.find(b => b.name === 'feature')?.main_behind >= 1,
   `...and how far each stands from ${main}`);
ok(br.branches.find(b => b.name === 'feature')?.merged === true && br.branches.find(b => b.name === 'old-work')?.merged === false
   && br.branches.find(b => b.name === main)?.merged === false,
   'a branch says whether main already has everything on it, and main does not claim to be merged into itself');
const cmp = await api('what=compare&branch=old-work');
ok(cmp.commits?.length === 1 && cmp.commits[0].subject === 'Old work' && cmp.files?.some(f => f.path === 'old.txt' && f.added === 1)
   && /\+old/.test(cmp.diff || '') && cmp.main === main,
   `a branch compares against main: the commits main lacks, the files, and the diff main would take (${cmp.error || cmp.commits?.length + ' commit'})`);
ok((await api('what=compare&branch=' + main)).error && (await api('what=compare&branch=nope')).error,
   '...and main itself, or a branch that is not there, is refused');
ok((await api('what=status').then(() => fetch(URL.replace(/\/$/, '') + '/api/git?project=nope&what=status',
  { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } }))).status === 400,
   'a project that is not one is refused');

// ---- the view ---------------------------------------------------------------
await page.evaluate(() => openNotebook('beta', 'git'));
await page.waitForFunction(() => !!document.querySelector('.nb .nbview[data-view="git"] #gitPicker:not([hidden]) .gbpickname')?.textContent,
                           null, { timeout: 20000 });
const NB = '.nb .nbview[data-view="git"]';
ok(new RegExp(`${st.files.length} changes? not committed`).test(await page.$eval(`${NB} #gitHint`, e => e.textContent.replace(/\s+/g, ' '))),
   'the glance counts what is not committed and the branches, the branch the picker beside them');
ok(await page.$eval(`${NB}`, e => e.querySelectorAll('.gfile').length) === st.files.length,
   'Changes lists each uncommitted file as a fold');
// Opened, not clicked: every fold opens by default (d890eda), and a click
// on one the view had already opened shut it, the diff with it (B566).
await openFold(page, `${NB} .gfile[data-path="a.txt"]`);
await page.waitForSelector(`${NB} .gfile[data-path="a.txt"] pre.diff`, { timeout: 10000 });
ok(await page.$eval(`${NB} .gfile[data-path="a.txt"] pre.diff`, e => /three/.test(e.textContent)
     && !!e.querySelector('.d-add')),
   '...and opening one shows its diff, additions marked');
// An open diff is read once, not on every redraw of the view (B833: a
// hundred reads in a few minutes on the controller). The view redraws when
// a commit lands: one of another file asks nothing of this one; one after
// this file changed asks once.
{
  const g = (...a) => execFileSync('git', ['-C', B, '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false', ...a]);
  const landed = subject => page.waitForFunction(([sel, s]) => (document.querySelector(sel)?.textContent || '').includes(s),
    [NB, subject], { timeout: 30000 });
  const asked = [];
  const onReq = r => { if (/what=diff&path=a\.txt/.test(r.url())) asked.push(r.url()); };
  page.on('request', onReq);
  writeFileSync(`${B}/other.txt`, 'another\n'); g('add', 'other.txt'); g('commit', '-qm', 'another file, for the redraw');
  await landed('another file, for the redraw');
  await page.waitForTimeout(500);
  const quiet = asked.length;
  writeFileSync(`${B}/a.txt`, 'one\ntwo\nthree\nfour\n');
  writeFileSync(`${B}/other2.txt`, 'more\n'); g('add', 'other2.txt'); g('commit', '-qm', 'a second file, for the redraw');
  await landed('a second file, for the redraw');
  await page.waitForFunction(s => /four/.test(document.querySelector(s)?.textContent || ''),
    `${NB} .gfile[data-path="a.txt"] pre.diff`, { timeout: 15000 }).catch(() => {});
  page.off('request', onReq);
  const shown = await page.$eval(`${NB} .gfile[data-path="a.txt"] pre.diff`, e => /four/.test(e.textContent)).catch(() => false);
  ok(quiet === 0 && asked.length === 1 && shown,
     `an open diff is read again only when its file changes (${quiet} on another file's commit, ${asked.length - quiet} after its own change, new line shown ${shown})`);
  // As it was: the two commits undone, their files gone, a.txt's change back.
  g('reset', '-q', '--soft', 'HEAD~2'); g('reset', '-q', '--', 'other.txt', 'other2.txt');
  rmSync(`${B}/other.txt`); rmSync(`${B}/other2.txt`);
  writeFileSync(`${B}/a.txt`, 'one\ntwo\nthree\n');
}
// One section open at a time (the operator, 5 Oct): History is opened.
await openFold(page, `${NB} [data-sect="git:history"]`);
const graph = await page.$eval(`${NB} .gitgraph`, g => ({
  rows: g.querySelectorAll('.grow[data-sha]').length, nodes: g.querySelectorAll('circle').length,
  edges: g.querySelectorAll('path').length, lanes: parseInt(getComputedStyle(g).getPropertyValue('--glanes')) }));
ok(graph.rows >= 4 && graph.nodes === graph.rows && graph.edges >= graph.rows - 1 && graph.lanes >= 2,
   `History is a graph: a node per commit, edges to parents, and a second lane for the branch (${JSON.stringify(graph)})`);
// ...and one anybody can see: each lane's line and dot take their color from
// a class built as gl${lane % 5}, which a sweep for unused CSS once removed (B79).
const inked = await page.$eval(`${NB} .gitgraph`, g => {
  const strokes = [...g.querySelectorAll('path, circle')].map(e => getComputedStyle(e).stroke);
  return { strokes: new Set(strokes).size, bare: strokes.filter(s => !s || s === 'none').length };
});
ok(inked.bare === 0 && inked.strokes >= 2,
   `...drawn: every line and dot has a stroke, a color per lane (${JSON.stringify(inked)})`);
await page.click(`${NB} .grow[data-sha="${merge.sha}"]`);
await page.waitForSelector(`${NB} #gitDetail .gcommit`, { timeout: 10000 });
ok(await page.$eval(`${NB} #gitDetail`, e => /Merge feature/.test(e.textContent) && /merge/.test(e.textContent)),
   'picking a commit opens its detail under the list');
await page.click(`${NB} .grow[data-sha="${feat.sha}"]`);
await page.waitForFunction(sel => /Feature work/.test(document.querySelector(sel)?.textContent || ''),
                           `${NB} #gitDetail`, { timeout: 10000 });
ok(await page.$eval(`${NB} #gitDetail`, e => !!e.querySelector('pre.diff .d-add')),
   '...with its diff, and picking another swaps it');
// The detail sits under the whole history, so on a short window a click has
// to take the page down to it rather than leave the change below the fold.
await page.setViewportSize({ width: 1280, height: 360 });
await page.click(`${NB} .grow[data-sha="${merge.sha}"]`);
const landed = await page.waitForFunction(sel => {
  const d = document.querySelector(sel);
  if (!d?.querySelector('.gcommit') || !/Merge feature/.test(d.textContent)) return false;
  let p = d.parentElement;
  while (p && !(p.scrollHeight > p.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(p).overflowY))) p = p.parentElement;
  // At the top of the pane that scrolls, or as far down as the pane goes.
  return !!p && (Math.abs(d.getBoundingClientRect().top - p.getBoundingClientRect().top) < 24
                 || p.scrollTop >= p.scrollHeight - p.clientHeight - 2);
}, `${NB} #gitDetail`, { timeout: 5000 }).then(() => true, () => false);
const at = await page.$eval(`${NB} #gitDetail`, e => {
  let p = e.parentElement;
  while (p && !(p.scrollHeight > p.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(p).overflowY))) p = p.parentElement;
  return p ? `${Math.round(e.getBoundingClientRect().top - p.getBoundingClientRect().top)}px below the pane's top` : 'no pane scrolls';
});
await page.setViewportSize({ width: 1280, height: 900 });
ok(landed, `picking a commit scrolls the page down to its detail (${at}, in a 360px window)`);
ok(await page.$eval(`${NB}`, e => [...e.querySelectorAll('.gbranch')].some(r => /claude\/tabmade/.test(r.textContent) && /tabmade's session/.test(r.textContent))
     && [...e.querySelectorAll('.gbranch')].some(r => /here/.test(r.textContent))),
   'Branches marks the one the tree is on and whose session a branch is');
ok(await page.$eval(`${NB}`, e => { const r = [...e.querySelectorAll('.gbranch')].find(x => /old-work/.test(x.textContent));
                                    return r && /3 days ago/.test(r.textContent) && !/just now/.test(r.textContent); }),
   'a branch row says how old its last commit is, not "just now" for everything');
// A commit made elsewhere reaches the open view on the git revision, not a poll.
writeFileSync(`${B}/a.txt`, 'one\ntwo\nthree\n'); git('commit', '-q', '-am', 'Third line');
await refreshUntil(page, () => /Third line/.test(document.querySelector('.nb .nbview[data-view="git"] .gitgraph')?.textContent || ''),
                   { timeout: 30000 });
ok(true, 'a commit made outside the dashboard arrives on the view by itself');

// ---- the actions (step 2) -------------------------------------------------
// Each a fixed git command on the controller with checked arguments, under
// the acting account's author; the network ones against a bare repository
// standing in for GitHub, with push rights granted the way the clone dialog
// grants them. An account's, never a session's, and not on a locked project.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const act = async (action, args, headers = H) => {
    const r = await fetch(URL.replace(/\/$/, '') + '/api/git', { method: 'POST', headers,
      body: JSON.stringify({ project: 'beta', action, args: args || {} }) });
    return { status: r.status, ...(await r.json()) };
  };
  // On the projects share, hidden so it is not a project: the only place a
  // local remote is reachable through the relay (B148).
  const origin = `${DIR}/ws/.remotes/beta-origin.git`;
  mkdirSync(`${DIR}/ws/.remotes`, { recursive: true });
  execFileSync('git', ['init', '-q', '--bare', origin]);
  git('remote', 'add', 'origin', origin);
  writeFileSync(`${DIR}/state/push-rights.json`, JSON.stringify({ beta: { repo: 'owner/beta', how: 'key' } }));

  // Commit what is changed, under the owner's author.
  const c = await act('commit', { message: 'Dashboard commit' });
  ok(c.status === 200 && c.ok && /^[0-9a-f]{7}$/.test(c.commit || ''),
     `Commit takes every changed file with the message (${c.commit || c.error})`);
  ok(git('log', '-1', '--format=%s') === 'Dashboard commit' && git('log', '-1', '--format=%an') === 'Dashboard Test',
     "...and the commit carries the account's author from its Profile, not the fixture's");
  ok((await api('what=status')).files.length === 0, '...leaving nothing uncommitted');
  ok((await act('commit', { message: '' })).error && (await act('commit', { message: 'x' })).error,
     'an empty message, or nothing to commit, is refused in a sentence');

  // Push sets the upstream the first time; fetch and pull talk to it after.
  const p1 = await act('push');
  ok(p1.status === 200 && p1.ok, `Push sends the branch up with the project's credentials (${p1.out || p1.error})`);
  ok(execFileSync('git', [`--git-dir=${origin}`, 'log', '-1', '--format=%s'], { encoding: 'utf8' }).trim() === 'Dashboard commit',
     '...and the remote has it');
  ok((await api('what=status')).upstream === `origin/${main}`, '...with the upstream set for next time');
  git('remote', 'set-url', 'origin', 'https://github.com/example/beta.git');
  const named = await api('what=all');
  git('remote', 'set-url', 'origin', origin);

  // The credential the CONTROLLER holds, not the one the tree's config names:
  // the mirror copies remote.* and branch.* and nothing else, because a
  // credential helper is a command the tree names (B153), so before this the
  // view could read everything and reach nothing: Fetch on an https remote
  // died on "could not read Username", which is git saying it had no
  // credential and no terminal to ask at. Asked of the composed command
  // rather than of a host: git connects before it authenticates, so an
  // unreachable address fails the same way with a token and without one.
  {
    const argvFor = (withToken) => execFileSync('python3', ['-c', `
import sys, json, subprocess
sys.path.insert(0, ${JSON.stringify(`${DIR}/../scripts/dashboard`)})
sys.path.insert(0, ${JSON.stringify(new globalThis.URL('..', import.meta.url).pathname)})
from pathlib import Path
import projects, git as g
projects.STATE = Path(${JSON.stringify(`${DIR}/state`)})
g.STATE = Path(${JSON.stringify(`${DIR}/state`)})
seen = []
class R:
    returncode, stdout, stderr = 0, "", ""
def fake(argv, **kw):
    seen.append(list(argv))
    return R()
subprocess.run = fake
g._run(${JSON.stringify(`${DIR}/ws/beta`)}, "fetch", "--prune")
# The fetch itself, not the reads the mirror does around it.
print(json.dumps(next((a for a in seen if "fetch" in a), [])))
`], { encoding: 'utf8' }).trim();
    const plain = JSON.parse(argvFor(false));
    ok(!plain.some(a => String(a).startsWith('credential.helper=')),
       `a project with no stored token names no helper (${plain.slice(0, 3).join(' ')})`);
    mkdirSync(`${DIR}/state/gitcreds`, { recursive: true });
    writeFileSync(`${DIR}/state/gitcreds/beta`, 'https://oauth2:tok@example.invalid\n', { mode: 0o600 });
    const withTok = JSON.parse(argvFor(true));
    ok(withTok.includes(`credential.helper=store --file=${DIR}/state/gitcreds/beta`)
       && withTok[withTok.indexOf('-c') + 1].startsWith('credential.helper='),
       `...and one that has it runs git with the controller's own store (${
         withTok.filter(a => String(a).includes('credential')).join(' ') || 'none'})`);
    rmSync(`${DIR}/state/gitcreds/beta`, { force: true });
  }
  // ...and when the host asks for a credential, the refusal names the way
  // out rather than handing over git's own line, which says what happened
  // and nothing a person can do about it. Asked of the translation with
  // git's exact words, because reaching a host that actually demands one
  // needs a host: walked on the dev instance instead, where a project whose
  // token a Reset had taken away answered "could not read Username for
  // http://...: terminal prompts disabled" and left a dead end.
  {
    const why = (token) => execFileSync('python3', ['-c', `
import sys, json
sys.path.insert(0, ${JSON.stringify(new globalThis.URL('..', import.meta.url).pathname)})
from pathlib import Path
import projects, git as g
projects.STATE = Path(${JSON.stringify(`${DIR}/state`)})
g.STATE = Path(${JSON.stringify(`${DIR}/state`)})
said = {"code": 128, "out": "fatal: could not read Username for 'https://gitea.example': terminal prompts disabled"}
print(json.dumps(g._done(said, "fetched", ${JSON.stringify(`${DIR}/ws/beta`)})))
`], { encoding: 'utf8' }).trim();
    const none = JSON.parse(why(false)).error;
    ok(/no access token stored/.test(none) && /Access token/.test(none)
       && /gitea\.example/.test(none) && !/terminal prompts disabled/.test(none),
       `no token: the refusal names the host and where to put one (${none.slice(0, 110)})`);
    mkdirSync(`${DIR}/state/gitcreds`, { recursive: true });
    writeFileSync(`${DIR}/state/gitcreds/beta`, 'https://oauth2:tok@gitea.example\n', { mode: 0o600 });
    const stale = JSON.parse(why(true)).error;
    ok(/rejected the token stored/.test(stale) && /Access token/.test(stale),
       `a token that is there and refused reads as the other thing it is (${stale.slice(0, 110)})`);
    rmSync(`${DIR}/state/gitcreds/beta`, { force: true });
  }
  ok(named.host?.name === 'GitHub' && named.host?.kind === 'github',
     `the payload names the host from the remote's address, so the view can say GitHub and not origin (${JSON.stringify(named.host)})`);
  // origin/HEAD is a pointer, not a branch: its short name is "origin", and
  // the view listed it as a branch called origin at the commit main is on.
  git('remote', 'set-head', 'origin', main);
  const withHead = (await api('what=branches')).branches;
  ok(!withHead.some(x => x.name === 'origin' || /\/HEAD$/.test(x.name)) && withHead.some(x => x.name === `origin/${main}`),
     `origin/HEAD is not listed as a branch called origin (${withHead.filter(x => x.remote).map(x => x.name).join(',')})`);
  ok((await act('fetch')).ok, 'Fetch brings the remote down');
  const clone = `${DIR}/beta-clone`;
  execFileSync('git', ['clone', '-q', origin, clone]);
  execFileSync('git', ['-C', clone, 'config', 'user.name', 'someone']);
  execFileSync('git', ['-C', clone, 'config', 'user.email', 's@example.invalid']);
  writeFileSync(`${clone}/remote.txt`, 'from elsewhere\n');
  execFileSync('git', ['-C', clone, 'add', 'remote.txt']);
  execFileSync('git', ['-C', clone, 'commit', '-q', '-m', 'Pushed from elsewhere']);
  execFileSync('git', ['-C', clone, 'push', '-q', 'origin', 'HEAD']);
  const pl = await act('pull');
  ok(pl.ok && git('log', '-1', '--format=%s') === 'Pushed from elsewhere',
     'Pull fast-forwards to what the remote gained');
  writeFileSync(`${DIR}/state/push-rights.json`, JSON.stringify({}));
  ok(/no push rights/.test((await act('push')).error || ''), 'a project without push rights is told so, not pushed');
  writeFileSync(`${DIR}/state/push-rights.json`, JSON.stringify({ beta: { repo: 'owner/beta', how: 'key' } }));

  // Branches: made, switched to, guarded, deleted.
  const nb = await act('branch', { name: 'topic', switch: true });
  ok(nb.ok && (await api('what=status')).branch === 'topic', 'New branch makes one at the tree and switches to it');
  ok((await act('branch', { name: '-bad name' })).error && (await act('branch', { name: 'topic' })).error,
     'a name that is not one, or one taken, is refused');
  tmuxNew('claude-beta', `${DIR}/ws/beta`);
  const held = await act('switch', { name: main });
  ok(held.status === 409 && /your Claude session is running/.test(held.error),
     "Switch is refused while the owner's session stands in the directory, and says it is theirs");
  // A merge into the tree waits only while that session is WORKING: at its
  // prompt it sees the changed files when it next reads them, and one merely
  // open refused the operator's own merge (24 Sep).
  execFileSync('tmux', ['select-pane', '-t', '=claude-beta:', '-T', '\u25d0 Building the thing']);
  const busyMerge = await act('merge', { name: main });
  ok(busyMerge.status === 409 && /your Claude session is working in this directory/.test(busyMerge.error || ''),
     `a merge into the tree waits while the session there is working (${busyMerge.error})`);
  execFileSync('tmux', ['select-pane', '-t', '=claude-beta:', '-T', '\u2733 Claude Code']);
  const idleMerge = await act('merge', { name: main });
  ok(!/Claude session/.test(idleMerge.error || ''),
     `...and not while it waits at its prompt (${idleMerge.ok ? 'merged' : (idleMerge.error || '').slice(0, 60)})`);
  // Merge INTO main from another branch moves nothing here, so the session
  // is no reason to refuse it: a temporary worktree on main takes the merge,
  // the way a pull request's button merges on a server. Commits made with
  // plumbing, so the tree stays on topic throughout.
  {
    const commitFile = (parent, path, content, msg) => {
      const idx = `${DIR}/tmp-index-${Math.random().toString(36).slice(2)}`;
      const env = { ...process.env, GIT_INDEX_FILE: idx };
      execFileSync('git', ['-C', B, 'read-tree', parent], { env });
      const blob = execFileSync('git', ['-C', B, 'hash-object', '-w', '--stdin'], { input: content, encoding: 'utf8' }).trim();
      execFileSync('git', ['-C', B, 'update-index', '--add', '--cacheinfo', `100644,${blob},${path}`], { env });
      const tree = execFileSync('git', ['-C', B, 'write-tree'], { env, encoding: 'utf8' }).trim();
      rmSync(idx, { force: true });
      return execFileSync('git', ['-C', B, 'commit-tree', tree, '-p', parent, '-m', msg], { encoding: 'utf8' }).trim();
    };
    const tip = git('rev-parse', main);
    git('branch', 'sidework', commitFile(main, 'side.txt', 'side\n', 'Side work'));
    const mm = await act('merge', { name: 'sidework', into: main });
    ok(mm.ok && git('merge-base', '--is-ancestor', 'sidework', main) === '' && (await api('what=status')).branch === 'topic'
       && git('worktree', 'list').split('\n').length === 1 && !existsSync(`${B}/side.txt`),
       `Merge into main lands while the session runs, leaves the tree where it was, and leaves no worktree behind (${mm.out || mm.error})`);
    ok(/Switch to/.test((await act('merge', { name: 'sidework', into: 'feature' })).error || ''),
       '...and only main takes a merge from elsewhere; anything else says to Switch');
    // A clash aborts, cleans up, and names what finishes it: nothing is left
    // half-merged on main, and no conflict lands in this tree's Changes.
    git('update-ref', `refs/heads/${main}`, commitFile(main, 'clash2.txt', 'from main\n', 'Main side'));
    git('branch', 'sideclash', commitFile(tip, 'clash2.txt', 'from side\n', 'Side clash'));
    const before = git('rev-parse', main);
    const cl = await act('merge', { name: 'sideclash', into: main });
    ok(/does not merge/.test(cl.error || '') && /Send to Claude/.test(cl.error || '') && git('rev-parse', main) === before
       && git('worktree', 'list').split('\n').length === 1 && !(await api('what=status')).files.some(f => f.state === 'conflict'),
       `a merge into main that clashes is abandoned whole, with the session named as what finishes it (${String(cl.error).slice(0, 70)})`);
    git('update-ref', `refs/heads/${main}`, tip);
    for (const b of ['sidework', 'sideclash']) git('branch', '-D', b);
  }
  tmuxKill('claude-beta');
  ok((await act('switch', { name: main })).ok && (await api('what=status')).branch === main,
     '...and goes through once it is gone');
  writeFileSync(`${B}/a.txt`, 'dirty\n');
  ok(/uncommitted changes/.test((await act('switch', { name: 'topic' })).error || ''),
     'a switch with uncommitted changes is refused rather than carrying them across');
  const dc = await act('discard', { path: 'a.txt' });
  ok(dc.ok && (await api('what=status')).files.length === 0, 'Discard puts a file back as the last commit has it');
  writeFileSync(`${B}/gone.txt`, 'x\n');
  ok((await act('discard', { path: 'gone.txt' })).ok && !(await api('what=status')).files.some(f => f.path === 'gone.txt'),
     '...and removes an untracked one');
  ok((await act('discard', { path: 'README.md' })).error, 'a file that is not changed cannot be discarded');
  const third = (await api('what=log')).commits.find(x => x.subject === 'Third line');
  const rv = await act('revert', { sha: third.sha });
  ok(rv.ok && /^Revert/.test(git('log', '-1', '--format=%s')) && !/three/.test(git('show', 'HEAD:a.txt')),
     'Revert is a new commit undoing the picked one');
  // Merging is the view's own, not an ask any more: the operator merges a
  // branch here and pushes it themselves, rather than handing it to a session
  // to do. Into the branch the tree is ON: nothing switches for you.
  {
    // Put back exactly, at the end: the assertions after this one read the
    // fixture's own branches and the content of its files, and a merge that
    // landed somebody else's commits on main would move both.
    const was = git('rev-parse', 'HEAD').trim();
    git('checkout', '-q', '-b', 'ready'); writeFileSync(`${B}/r.txt`, 'r\n');
    git('add', 'r.txt'); git('commit', '-q', '-m', 'Ready work');
    // The status poll keeps what git said of a project until its .git
    // moves (R94): a branch switched under it is read at once, never a
    // kept answer from before.
    const statusBranch = async () => ((await (await fetch(URL.replace(/\/$/, '') + '/api/status',
      { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } })).json()).projects || [])
      .find(p => p.name === 'beta')?.git;
    const onReady = await statusBranch();
    git('checkout', '-q', main);
    const onMain = await statusBranch();
    ok(onReady === 'ready' && onMain === main,
       `the status poll reads a branch switched under it at once, never one kept from before (${onReady}, then ${onMain})`);
    ok((await act('merge', { name: main })).error, 'the branch the tree is on cannot be merged into itself');
    const m = await act('merge', { name: 'ready' });
    ok(m.ok && existsSync(`${B}/r.txt`) && (await api('what=status')).branch === main,
       `Merge brings a branch into the one the tree is on (${m.out || m.error})`);
    // A TRACKED file, because untracked is not dirty to git and not to this
    // either: `_dirty` lists everything but untracked, so a stray new file
    // never stands between somebody and a merge.
    writeFileSync(`${B}/a.txt`, 'dirty\n');
    ok(/uncommitted changes/.test((await act('merge', { name: 'topic' })).error || ''),
       '...refused with a dirty tree, so the merge is its own commit');
    git('checkout', '--', 'a.txt');
    ok((await act('merge', { name: 'nope' })).error, '...and a branch that is not there is refused');
    // A conflict is LEFT, not aborted: the Changes section lists the files
    // and offers the merge in progress to the session, which is the only
    // thing that can finish it.
    git('checkout', '-q', '-b', 'clashA'); writeFileSync(`${B}/clash.txt`, 'from A\n');
    git('add', 'clash.txt'); git('commit', '-q', '-m', 'A');
    git('checkout', '-q', main);
    git('checkout', '-q', '-b', 'clashB'); writeFileSync(`${B}/clash.txt`, 'from B\n');
    git('add', 'clash.txt'); git('commit', '-q', '-m', 'B');
    const c = await act('merge', { name: 'clashA' });
    ok(/does not merge/.test(c.error || '') && /hands the merge to Claude/.test(c.error || ''),
       `a conflicting merge says so and names what finishes it (${String(c.error).slice(0, 60)})`);
    ok((await api('what=status')).files.some(f => f.state === 'conflict'),
       '...and leaves the conflict standing, for the Changes section to offer');
    git('merge', '--abort');
    git('checkout', '-q', main);
    git('reset', '--hard', '-q', was);
    for (const b of ['ready', 'clashA', 'clashB']) git('branch', '-D', b);
    rmSync(`${B}/r.txt`, { force: true }); rmSync(`${B}/clash.txt`, { force: true });
  }
  ok((await act('delete', { name: 'feature' })).ok && !git('branch', '--list', 'feature'),
     'Delete removes a branch that is fully merged');
  git('checkout', '-q', '-b', 'lonely'); writeFileSync(`${B}/l.txt`, 'l\n'); git('add', 'l.txt'); git('commit', '-q', '-m', 'Lonely work');
  git('checkout', '-q', main);
  const un = await act('delete', { name: 'lonely' });
  ok(un.error && un.unmerged, '...but refuses one holding commits no other branch has, saying so');
  ok((await act('delete', { name: 'lonely', force: true })).ok, '...unless told to, twice');
  ok((await act('delete', { name: main })).error && (await act('delete', { name: 'nope' })).error,
     'the main branch and a branch that is not there are refused');

  // R69 step 3: commits main lacks, holding nothing main lacks. Work that
  // shipped another way reads exactly like work that is waiting, and the
  // only way to tell them apart was to go and diff it by hand.
  {
    git('checkout', '-q', '-b', 'shipped');
    writeFileSync(`${B}/shipped.txt`, 'a\n'); git('add', 'shipped.txt'); git('commit', '-q', '-m', 'Ship it');
    git('rm', '-q', 'shipped.txt'); git('commit', '-q', '-m', 'Take it back');
    git('checkout', '-q', main);
    const rows = (await api('what=branches')).branches || [];
    const b = rows.find(r => r.name === 'shipped');
    ok(b?.main_ahead === 2 && b?.same === true && rows.find(r => r.name === 'old-work')?.same === false,
       `a branch whose commits change nothing ${main} lacks says so, where ancestry alone calls it ${
         b?.main_ahead} waiting`);
    const no = await act('delete', { name: 'shipped' });
    ok(no.unmerged && no.same === true && /no work/.test(no.error || ''),
       '...and its delete refusal separates the history, which goes, from the work, which does not');
    ok((await act('delete', { name: 'shipped', force: true })).ok, '...and deletes it when told');
  }

  // R69 step 1: a branch that is only on the host. The fold knew nothing
  // about its own rows, so the one delete that cannot lose work was the one
  // thing the view could not do.
  {
    git('push', '-q', 'origin', `${main}:refs/heads/stale`);      // every commit already in main
    git('push', '-q', 'origin', `${main}:refs/heads/gone`);       // ...and one to remove
    git('push', '-q', 'origin', 'old-work:refs/heads/live');      // commits main does not have
    await act('fetch');
    const rows = (await api('what=branches')).branches || [];
    const stale = rows.find(r => r.name === 'origin/stale'), live = rows.find(r => r.name === 'origin/live');
    ok(stale?.merged === true && live?.merged === false,
       `a remote row says whether ${main} already has it (stale ${stale?.merged}, live ${live?.merged})`);
    const gone = await act('delete-remote', { name: 'origin/gone' });
    ok(gone.ok && !execFileSync('git', [`--git-dir=${origin}`, 'branch', '--list', 'gone'], { encoding: 'utf8' }).trim(),
       `...and Delete on the host removes it there (${gone.out || gone.error})`);
    const kept = await act('delete-remote', { name: 'origin/live' });
    ok(kept.error && /merge it first/.test(kept.error)
       && execFileSync('git', [`--git-dir=${origin}`, 'branch', '--list', 'live'], { encoding: 'utf8' }).includes('live'),
       '...while one holding work main does not have is refused, and is still there');
    ok((await act('delete-remote', { name: `origin/${main}` })).error
       && (await act('delete-remote', { name: 'origin/nope' })).error
       && (await act('delete-remote', { name: 'notaremote' })).error,
       'the host\'s main branch, one that is not there, and a name that is not a remote branch are refused');
  }

  // R69 step 2: merging into a main the host has moved past. The merge
  // itself is fine; what it leaves is a main both ahead and behind, which
  // is how the copy on the share drifts 294 commits out of step.
  {
    const other = `${DIR}/beta-behind`;
    const was = execFileSync('git', [`--git-dir=${origin}`, 'rev-parse', main], { encoding: 'utf8' }).trim();
    // Its own author, spelled out: the suite's environment is not somebody's
    // shell and a commit with no author is a crash halfway through a fixture.
    const theirs = { ...process.env, GIT_AUTHOR_NAME: 'Somebody Else', GIT_AUTHOR_EMAIL: 'else@example.invalid',
                     GIT_COMMITTER_NAME: 'Somebody Else', GIT_COMMITTER_EMAIL: 'else@example.invalid' };
    const oth = (...a) => execFileSync('git', ['-C', other, ...a], { encoding: 'utf8', env: theirs });
    execFileSync('git', ['clone', '-q', origin, other], { env: theirs });
    writeFileSync(`${other}/theirs.txt`, 'theirs\n');
    oth('add', 'theirs.txt');
    oth('commit', '-q', '-m', 'Somebody else pushed');
    oth('push', '-q', 'origin', `HEAD:${main}`);
    await act('fetch');
    const held = await act('merge', { name: 'old-work', into: main });
    ok(held.error && /behind origin\//.test(held.error) && /Pull first/.test(held.error),
       `Merge into ${main} waits while the host is ahead of it, naming the pull (${
         (held.error || '').slice(0, 70)})`);
    // The host put back where it was: this test moved somebody else's
    // fixture, and every push and pull after it would meet the surprise.
    execFileSync('git', [`--git-dir=${origin}`, 'update-ref', `refs/heads/${main}`, was]);
    await act('fetch');
    // A branch main already holds: what is being proved is that the check
    // stops refusing, not that git can merge, and this leaves the fixture
    // exactly as the rest of the file expects it.
    // Its own branch at main's tip: claude/tabmade is its account's now,
    // and feature is gone by here.
    git('branch', 'levelcheck', main);
    const done_ = await act('merge', { name: 'levelcheck', into: main });
    ok(done_.ok, `...and stops refusing once ${main} here is level with the host again (${
      (done_.out || done_.error || '').trim().slice(0, 40)})`);
    git('branch', '-D', 'levelcheck');
    rmSync(other, { recursive: true, force: true });
  }

  // B203: a write is not disturbed by the view reading beside it, nor by
  // another write. The write directory is one per tree, rebuilt as each write
  // starts, and the branch list (a read, on the poll path) once went through
  // it to ask whether a branch differs from main: every poll pulled the refs
  // out from under whatever write was in flight, and this suite failed at a
  // different step each time. Forced here rather than waited for.
  {
    let reading = true, reads = 0;
    const reader = (async () => { while (reading){ await api('what=branches'); reads++; } })();
    const bad = [];
    for (let n = 0; n < 6; n++){
      const pair = await Promise.all([act('branch', { name: `race-a${n}` }), act('branch', { name: `race-b${n}` })]);
      const sw = await act('switch', { name: `race-a${n}` });
      const back = await act('switch', { name: main });
      for (const [what, r] of [['branch a', pair[0]], ['branch b', pair[1]], ['switch', sw], ['switch back', back]])
        if (!r.ok) bad.push(`${what} ${n}: ${String(r.error || r.out).slice(0, 80)}`);
    }
    reading = false; await reader;
    const on = git('rev-parse', '--abbrev-ref', 'HEAD');
    ok(!bad.length && on === main && reads > 0,
       `24 writes, two of them at once each round, all land while the branch list is read ${reads} times beside them (${
         bad.length ? bad.slice(0, 3).join(' | ') : 'on ' + on})`);
    for (let n = 0; n < 6; n++){ git('branch', '-D', `race-a${n}`); git('branch', '-D', `race-b${n}`); }
  }

  // The WRITES run none of the programs the tree names either (B153). The
  // reads were the first half; a commit, a switch and a merge are the half
  // that has to move the tree afterwards, and each of them is a hook git
  // would otherwise run here as the dashboard's account.
  {
    const mark = `${DIR}/a-write-ran-a-program`;
    const touch = `#!/bin/sh\ntouch ${mark}\n`;
    const planted = ['pre-commit', 'post-commit', 'prepare-commit-msg', 'post-checkout',
      'post-merge', 'reference-transaction', 'post-index-change'];
    const was = git('rev-parse', 'HEAD').trim();
    // Reading the tree from here on goes through a git with the traps turned
    // off: this test's own commands would otherwise spring them and the mark
    // would say nothing about what the dashboard did.
    const nohooks = `${DIR}/no-hooks-at-all`;
    mkdirSync(nohooks, { recursive: true });
    const plain = (...a) => execFileSync('git', ['-c', 'core.fsmonitor=',
      '-c', `core.hooksPath=${nohooks}`, '-C', B, ...a], { encoding: 'utf8' }).trim();
    for (const h of planted) writeFileSync(`${B}/.git/hooks/${h}`, touch, { mode: 0o755 });
    git('config', 'core.fsmonitor', `touch ${mark}; echo`);
    writeFileSync(`${B}/w.txt`, 'written by the dashboard\n');
    const wc = await act('commit', { message: 'Written through our own git dir' });
    ok(wc.ok && plain('log', '-1', '--format=%s') === 'Written through our own git dir'
       && plain('show', 'HEAD:w.txt') === 'written by the dashboard',
       `a commit moves the tree's own branch and stores the tree's own bytes (${wc.commit || wc.error})`);
    ok(plain('log', '-1', '--format=%an') === 'Dashboard Test' && !plain('status', '--porcelain'),
       '...under the acting account, leaving nothing staged behind it');
    await act('branch', { name: 'traps' });
    const ws = await act('switch', { name: 'traps' });
    ok(ws.ok && plain('rev-parse', '--abbrev-ref', 'HEAD') === 'traps',
       "...and a switch moves the tree's own HEAD, not a copy of it");
    await act('switch', { name: main });
    ok(!existsSync(mark),
       `and not one of ${planted.length} hooks, nor fsmonitor, ran on the way (${
         existsSync(mark) ? 'a mark was made' : 'no mark'})`);
    // Still a repository afterwards, by git's own reckoning rather than ours.
    let fsck = '';
    try { execFileSync('git', ['-C', B, 'fsck', '--no-progress', '--no-dangling'], { encoding: 'utf8' }); }
    catch (e) { fsck = String(e.stdout || '') + String(e.stderr || ''); }
    ok(!fsck.trim(), `...and what it left passes git fsck (${fsck.trim().slice(0, 80) || 'clean'})`);
    for (const h of planted) rmSync(`${B}/.git/hooks/${h}`, { force: true });
    git('config', '--unset-all', 'core.fsmonitor');
    rmSync(mark, { force: true });

    // A filter is the one thing skipping is not free on: it decides the bytes
    // that get stored, so the write is refused rather than quietly storing
    // the unfiltered ones. Only one the TREE defines: git-lfs lives in the
    // system config, outside any tree, and still applies.
    git('config', 'filter.redact.clean', 'sed s/SECRET/xxx/');
    writeFileSync(`${B}/.gitattributes`, '*.txt filter=redact\n');
    writeFileSync(`${B}/w.txt`, 'SECRET\n');
    const refused = await act('commit', { message: 'must not land' });
    ok(/filter\.redact\.clean/.test(refused.error || '') && /terminal/.test(refused.error || '')
       && plain('log', '-1', '--format=%s') === 'Written through our own git dir',
       `a repository whose own config names a content filter is told why the dashboard will not commit it (${
         String(refused.error).slice(0, 60)})`);
    ok(/filter\.redact/.test((await act('switch', { name: 'traps' })).error || '')
       && !/filter\.redact/.test(JSON.stringify(await act('fetch')) || ''),
       '...and the same for a switch, while fetch goes through: it writes no file');
    git('config', '--unset-all', 'filter.redact.clean');
    rmSync(`${B}/.gitattributes`, { force: true });
    rmSync(`${B}/w.txt`, { force: true });
    git('branch', '-D', 'traps');
    git('reset', '--hard', '-q', was);
  }

  // Whose: a session's token cannot press these; it has bb git.
  const tok = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
def wj(p, d):
    tmp = str(p) + ".tmp"; open(tmp, "w").write(json.dumps(d, indent=2)); os.replace(tmp, p)
u.configure(state="${DIR}/state", write_json=wj)
print(u.mint_session("beta"))`], { encoding: 'utf8' }).trim();
  const asSession = await act('fetch', {}, { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' });
  ok(asSession.status === 403 && /bb git/.test(asSession.error), "a session's token is refused the buttons, and told about bb git");
  // Its owner's lock leaves its owner working (R119); an administrator's
  // holds the owner too, written as one here since this account owns beta.
  await page.evaluate(() => fetch('/api/lock', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'beta', locked: true }) }));
  ok((await act('fetch')).status !== 403, "its owner's lock leaves its owner the buttons");
  writeFileSync(`${DIR}/state/locked-projects.json`, JSON.stringify({ beta: { by: 'u_0000aaaa', admin: true } }));
  const held = await act('fetch');
  ok(held.status === 403 && /locked by an administrator/.test(held.error),
     `an administrator's lock takes no action, its owner's included (${held.status} ${held.error})`);
  writeFileSync(`${DIR}/state/locked-projects.json`, '{}');

  // ...and the view offers them: the network bar, the commit form at the
  // top of Changes, Switch and Delete on a branch, Revert on a commit.
  writeFileSync(`${B}/a.txt`, 'one\ntwo\nfour\n');
  await page.evaluate(() => getNotebook('beta').view('git'));
  // Waited for the CHANGED FILE, not just for the view to exist. #gitCommit
  // is there as soon as the form draws, which happens before git status has
  // caught up with the write above, so Discard was missing about one run in
  // two, and the file passed on its own the next time. The wait throws by
  // name if the row never comes, so the assertion below still proves all six.
  await refreshUntil(page, () => !!document.querySelector(
    '.nb .nbview[data-view="git"] #gitCommit')
    && !!document.querySelector('.nb .nbview[data-view="git"] [data-gitdiscard="a.txt"]'),
    { timeout: 20000 });
  const view = await page.$eval('.nb .nbview[data-view="git"]', v => ({
    net: !v.querySelector('#gitNet').hidden, push: !v.querySelector('[data-gitact="push"]').disabled,
    commitBar: !!v.querySelector('.gcommitbar[data-add] #gitMsg'),
    discard: !!v.querySelector('[data-gitdiscard="a.txt"]'),
    sw: v.querySelectorAll('[data-gitswitch]').length, del: v.querySelectorAll('[data-gitdelete]').length,
    newBranch: !!v.querySelector('#gitPicker [data-gitpicknew]') && !v.querySelector('#gitNewBranch') }));
  ok(view.net && view.push && view.commitBar && view.discard && view.sw >= 1 && view.del >= 1 && view.newBranch,
     `the view offers the network bar, the commit form, Discard, Switch, Delete and New branch (${JSON.stringify(view)})`);
  const grouped = await page.$eval('.nb .nbview[data-view="git"]', v => ({
    into: !!v.querySelector('[data-gitmerge="old-work"][data-gitinto]'),
    chips: [...v.querySelectorAll('[data-gbchip].chip')].map(g => `${g.dataset.gbchip}${g.classList.contains('on') ? '*' : ''}`),
    originRows: [...v.querySelectorAll('.gbranch code')].map(c => c.textContent).filter(n => /^origin\//.test(n)),
    merged: !!v.querySelector('[data-gitdeletemerged]'),
    remoteDel: [...v.querySelectorAll('[data-gitdeleteremote]')].map(b => b.dataset.gitdeleteremote),
    words: [...v.querySelectorAll('.gbranch .gab')].map(e => e.getAttribute('aria-label')).join(' | '),
    oneLine: [...v.querySelectorAll('.gbranch:not([hidden]) > .tline')].every(l => l.getBoundingClientRect().height < 60),
    shown: [...v.querySelectorAll('.gbranch:not([hidden])')].map(r => r.dataset.kind) }));
  ok(grouped.into && grouped.chips.includes('active*') && grouped.chips.includes('merged') && grouped.merged
     && !grouped.originRows.some(n => ['origin/' + main, 'origin/old-work'].includes(n))
     && /not yet in/.test(grouped.words) && !/level with/.test(grouped.words)
     && grouped.oneLine && grouped.shown.every(k => k === 'active'),
     `branches are a table a line a branch, Active chosen until another chip is pressed: work not yet in main offers Merge into main, branches already in main are one Delete, and a remote row mirroring a local branch is not repeated (${JSON.stringify(grouped).slice(0, 240)})`);
  // B80: a branch with nothing of its own (level with main) has nothing to
  // merge, rebase or review, so its ⋯ offers none of it.
  git('branch', 'level-b80', main);
  // A branch made beside the tree moves no HEAD log, so the view reads again
  // when it is opened, as a person would.
  await page.evaluate(() => getNotebook('beta').view('git'));
  await page.waitForSelector('.nb .nbview[data-view="git"] .gbranch[data-branch="level-b80"]', { state: 'attached', timeout: 15000 });
  const level = await page.$eval('.nb .nbview[data-view="git"] .gbranch[data-branch="level-b80"]', r => ({
    merge: !!r.querySelector('[data-gitmerge]'), asks: [...r.querySelectorAll('[data-gitaskkind]')].map(o => o.dataset.gitaskkind) }));
  ok(!level.merge && !level.asks.length && grouped.into,
     `...and a branch level with ${main} offers neither Merge into ${main} nor an ask of Claude, while old-work keeps Merge (${JSON.stringify(level)})`);
  git('branch', '-D', 'level-b80');
  // The chips narrow the table in place, and the search beside them by name.
  await page.click('.nb .nbview[data-view="git"] [data-gbchip="remote"]');
  await page.waitForFunction(() => [...document.querySelectorAll('.nb .nbview[data-view="git"] .gbranch:not([hidden])')].every(r => r.dataset.kind === 'remote'), null, { timeout: 5000 });
  await page.click('.nb .nbview[data-view="git"] [data-gbchip=""]');
  await page.fill('.nb .nbview[data-view="git"] #gitBranchFind', 'old-w');
  ok(await page.$$eval('.nb .nbview[data-view="git"] .gbranch:not([hidden])', rs => rs.map(r => r.dataset.branch).join()) === 'old-work',
     'a chip narrows the table to its kind, and the search to the names holding what is typed');
  await page.fill('.nb .nbview[data-view="git"] #gitBranchFind', '');
  await page.click('.nb .nbview[data-view="git"] [data-gbchip="active"]');
  // R69 step 1 in the view: the fold lists what is only on the host, and
  // offers the delete on exactly the rows where it cannot lose work.
  ok(grouped.originRows.includes('origin/stale') && grouped.originRows.includes('origin/live')
     && grouped.remoteDel.includes('origin/stale') && !grouped.remoteDel.includes('origin/live'),
     `the "only on the host" fold offers Delete on a branch main already has and not on one it does not (${
       JSON.stringify(grouped.remoteDel)} of ${JSON.stringify(grouped.originRows)})`);
  // Work not yet in main is a row you open: its commits and diff against
  // main, read here rather than on a pull request page.
  await openFold(page, '.nb .nbview[data-view="git"] [data-sect="git:branches"]');   // one section open at a time
  // ...on a page of its own (R269 step 2), as a pull request's: its address
  // names the branch, Back to branches returns, and the address alone
  // lands on it.
  await page.click('.nb .nbview[data-view="git"] .gbranch[data-branch="old-work"] > .tline .td.lead');   // the line opens it
  await page.waitForSelector('.nb .nbview[data-view="git"] #gitCmp pre.diff', { timeout: 10000 });
  const opened = await page.$eval('.nb .nbview[data-view="git"]', v => { const d = v.querySelector('#gitCmp');
    return { commit: /Old work/.test(d.querySelector('.gcmpcommit')?.textContent || ''),
    files: /old\.txt/.test(d.querySelector('.gcmpfiles')?.textContent || ''), add: !!d.querySelector('pre.diff .d-add'),
    merge: !!d.querySelector('.gcmpfoot [data-gitmerge="old-work"][data-gitinto]'),
    alone: getComputedStyle(v.querySelector('#gitBody')).display === 'none' && getComputedStyle(v.querySelector('#gitNet')).display === 'none',
    hash: location.hash }; });
  ok(opened.commit && opened.files && opened.add && opened.merge && opened.alone && /\/git\/compare\/old-work$/.test(opened.hash),
     `a branch with work not yet in main opens its comparison on a page of its own, its address naming it: its commits, its files and their diffs, Merge into main at its foot (${JSON.stringify(opened)})`);
  await page.click('.nb .nbview[data-view="git"] #gitHint [data-gitcmpback]');
  const backed = await page.waitForFunction(() => /\/git$/.test(location.hash) && getComputedStyle(document.querySelector('.nb .nbview[data-view="git"] #gitCmp')).display === 'none', null, { timeout: 5000 })
    .then(() => true, () => false);
  ok(backed, `Back to branches returns to the view's address and its sections (${await page.evaluate(() => `${location.hash} ${getComputedStyle(document.querySelector('.nb .nbview[data-view="git"] #gitCmp')).display}`)})`);
  await page.evaluate(() => { location.hash = location.hash + '/compare/old-work'; });
  await page.waitForSelector('.nb .nbview[data-view="git"] #gitCmp .gcmpcommit', { timeout: 10000 });
  await page.goBack();
  await page.waitForFunction(() => getComputedStyle(document.querySelector('.nb .nbview[data-view="git"] #gitBody')).display !== 'none', null, { timeout: 5000 });
  ok(true, '...an address naming the comparison lands on it, and the browser\'s Back leaves it');
  // A new branch where the tree is, with changes not committed, is made and
  // switched to with the changes along (B858): it was made, then the switch
  // refused for the changes, a branch left behind.
  {
    const was = git('rev-parse', '--abbrev-ref', 'HEAD'), dirty = git('status', '--porcelain');
    const j = await page.evaluate(async () => (await (await fetch('/api/git', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'beta', action: 'branch', args: { name: 'carry-along', switch: true } }) })).json()));
    const on = git('rev-parse', '--abbrev-ref', 'HEAD'), still = git('status', '--porcelain');
    git('switch', was); git('branch', '-D', 'carry-along');
    ok(!j.error && on === 'carry-along' && dirty && still === dirty,
       `a new branch made and switched to with changes not committed takes them along (${JSON.stringify({ error: j.error, on, dirty, still })})`);
  }
  await openFold(page, '.nb .nbview[data-view="git"] [data-sect="git:changes"]');   // one section open at a time
  await page.fill('.nb .nbview[data-view="git"] #gitMsg', 'From the view');
  await page.click('.nb .nbview[data-view="git"] #gitCommit');
  await refreshUntil(page, () => /From the view/.test(document.querySelector('.nb .nbview[data-view="git"] .gitgraph')?.textContent || ''), { timeout: 20000 });
  ok(git('log', '-1', '--format=%s') === 'From the view', 'Commit from the view commits, and the graph shows it');
  await openFold(page, '.nb .nbview[data-view="git"] [data-sect="git:history"]');   // one section open at a time (the operator, 5 Oct)
  await page.click('.nb .nbview[data-view="git"] .grow[data-sha]');
  await page.waitForSelector('.nb .nbview[data-view="git"] #gitDetail [data-gitrevert]', { timeout: 10000 });
  ok(true, "a picked commit's detail carries Revert and Branch here");
  // The branch picker in the head row (R269 step 3), on a clean tree: the branch the tree is
  // on, opening the local branches under a box; a name nobody has offers
  // Create, which makes it and switches to it, and a press on another
  // switches back.
  {
    const V = '.nb .nbview[data-view="git"]', was = git('rev-parse', '--abbrev-ref', 'HEAD');
    await page.click(`${V} #gitPicker .gbpickb`);
    await page.waitForSelector(`${V} #gitPicker .gbpickmenu:not([hidden])`, { timeout: 5000 });
    const listed = await page.$eval(`${V} #gitPicker`, p => ({ name: p.querySelector('.gbpickname').textContent,
      on: p.querySelector('[data-gitpick].on')?.dataset.gitpick, list: [...p.querySelectorAll('[data-gitpick]')].map(b => b.dataset.gitpick),
      focused: document.activeElement?.id === 'gitPickFind' }));
    ok(listed.name === was && listed.on === was && listed.list.includes('old-work') && listed.focused,
       `the head row names the branch the tree is on, and its picker lists the branches with that one marked and the box focused (${JSON.stringify(listed)})`);
    await page.fill(`${V} #gitPickFind`, 'picked-new');
    const offer = await page.$eval(`${V} #gitPicker`, p => ({ make: p.querySelector('[data-gitpicknew]').hidden ? '' : p.querySelector('[data-gitpicknew]').textContent,
      shown: [...p.querySelectorAll('[data-gitpick]')].filter(b => !b.hidden).length, open: !p.querySelector('.gbpickmenu').hidden }));
    ok(/Create branch picked-new from/.test(offer.make) && offer.shown === 0 && offer.open,
       `...a name nobody has narrows the list to nothing and offers to create it, the menu staying open while it is typed (${JSON.stringify(offer)})`);
    await page.press(`${V} #gitPickFind`, 'Enter');
    let made = false;
    for (let i = 0; i < 40 && !made; i++) { made = git('rev-parse', '--abbrev-ref', 'HEAD') === 'picked-new'; if (!made) await new Promise(r => setTimeout(r, 250)); }
    const said = await refreshUntil(page, () => document.querySelector('.nb .nbview[data-view="git"] #gitPicker .gbpickname')?.textContent === 'picked-new', { timeout: 15000 })
      .then(() => true, () => false);
    ok(made && said, `...Enter makes it from the commit the tree is on and switches to it, and the head row says so (${JSON.stringify({ made, said,
      head: git('rev-parse', '--abbrev-ref', 'HEAD'), label: await page.$eval('.nb .nbview[data-view="git"] #gitPicker', p => p.textContent.trim()),
      toasts: await page.$$eval('.toast, #toasts *', t => t.map(x => x.textContent.trim()).filter(Boolean).slice(-3)) })})`);
    await page.click(`${V} #gitPicker .gbpickb`);
    await page.waitForSelector(`${V} #gitPicker .gbpickmenu:not([hidden])`, { timeout: 5000 });
    await page.click(`${V} #gitPicker [data-gitpick="${was}"]`);
    let back = false;
    for (let i = 0; i < 40 && !back; i++) { back = git('rev-parse', '--abbrev-ref', 'HEAD') === was; if (!back) await new Promise(r => setTimeout(r, 250)); }
    ok(back, `...and a press on another branch in it switches the tree back (${git('rev-parse', '--abbrev-ref', 'HEAD')})`);
    git('branch', '-D', 'picked-new');
    await refreshUntil(page, () => document.querySelector('.nb .nbview[data-view="git"] #gitPicker .gbpickname')?.textContent !== 'picked-new', { timeout: 15000 });
  }
}

// ---- step 3: the policy, and Send to Claude --------------------------------
// What a session may send to the remote is the project's to say, on the Git
// view, and the controller's to enforce where the push runs: the relay. A
// commit, a change or a branch is handed to the session as one line naming
// it and the ask, typed into the session the way a roadmap step arrives.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const post = async (path, body, headers = H) => {
    const r = await fetch(URL.replace(/\/$/, '') + path, { method: 'POST', headers, body: JSON.stringify(body) });
    return { status: r.status, ...(await r.json().catch(() => ({}))) };
  };
  const bbEnv = { ...process.env, BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`,
                  WORKSPACE: `${DIR}/ws`, BB_PROJECT: 'beta' };
  const bb = (...a) => { try { return execFileSync('bash', [`${REPO}/scripts/bb`, ...a], { encoding: 'utf8', env: bbEnv, cwd: B }); }
                         catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; } };
  ok(/push its branch: allow/.test(bb('git', 'policy')) && /push to main:\s+deny/.test(bb('git', 'policy')),
     'bb git policy reads the defaults: a session may push its branch and not main');
  const setPol = await post('/api/prefs', { project: 'beta', gitpol: { push: 'deny' } });
  ok(setPol.status === 200 && setPol.gitpol?.push === 'deny' && setPol.gitpol?.main === 'deny',
     'the Git view saves the policy into the project\'s settings');
  ok(/push its branch: deny/.test(bb('git', 'policy')), '...and bb git policy says so to a session');
  ok((await post('/api/prefs', { project: 'beta', gitpol: { push: 'maybe' } })).error
     && (await post('/api/prefs', { project: 'beta', gitpol: { merge: 'allow' } })).error,
     'a value or a key that is not one is refused');

  // The relay is the door: a session's bb git push is judged there.
  const tok = execFileSync('python3', ['-c', `
import importlib.util, json, os
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
def wj(p, d):
    tmp = str(p) + ".tmp"; open(tmp, "w").write(json.dumps(d, indent=2)); os.replace(tmp, p)
u.configure(state="${DIR}/state", write_json=wj)
print(u.mint_session("beta"))`], { encoding: 'utf8' }).trim();
  const S = { Authorization: 'Bearer ' + tok, 'Content-Type': 'application/json' };
  const origin = `${DIR}/ws/.remotes/beta-origin.git`;
  const relay = (argv) => post('/api/v1/bb', { argv, cwd: B }, S);
  const denied = await relay(['git', 'push', 'origin', 'topic']);
  ok(denied.status === 403 && /does not let a session push/.test(denied.error),
     'with pushing denied, a session\'s bb git push is refused on the relay, naming the policy');
  await post('/api/prefs', { project: 'beta', gitpol: { push: 'allow', main: 'deny' } });
  const toMain = await relay(['git', 'push', 'origin', main]);
  ok(toMain.status === 403 && new RegExp(`push to ${main}`).test(toMain.error),
     `...and pushing to ${main} is refused while that is denied, with what to do instead`);
  const own = await relay(['git', 'push', 'origin', 'topic']);
  ok(own.status === 200 && own.code === 0
     && execFileSync('git', [`--git-dir=${origin}`, 'branch', '--list', 'topic'], { encoding: 'utf8' }).includes('topic'),
     `...while its own branch goes up (${(own.out || own.err || '').trim().slice(0, 40)})`);
  // A branch never pushed goes up on a bare bb git push and is given its
  // upstream there (B220), rather than git's refusal and a hint about
  // push.autoSetupRemote.
  {
    const was = execFileSync('git', ['-C', B, 'rev-parse', '--abbrev-ref', 'HEAD'], { encoding: 'utf8' }).trim();
    execFileSync('git', ['-C', B, 'checkout', '-q', '-b', 'fresh-b220']);
    const first = await relay(['git', 'push']);
    // The relay answers with what the session's own bb applies to its tree:
    // the branch's new upstream among it.
    const up = ((first.apply || {}).upstream || []).find(u => u[0] === 'fresh-b220')?.[2] || '';
    const there = execFileSync('git', [`--git-dir=${origin}`, 'branch', '--list', 'fresh-b220'], { encoding: 'utf8' }).includes('fresh-b220');
    execFileSync('git', ['-C', B, 'checkout', '-q', was]);
    ok(first.status === 200 && first.code === 0 && there && up === 'refs/heads/fresh-b220',
       `a branch never pushed goes up on a bare bb git push, its upstream set (${first.status} code ${first.code} ${there} ${up} ${JSON.stringify((first.err || first.error || '') + ' / ' + (first.out || '')).slice(0, 400)})`);
  }
  // B191: the policy is about REFS, not about the word `main` appearing in
  // the arguments. "Its branch" is the one the tree is on, so everything
  // else on that remote is somebody's, and a setting naming one branch must
  // not hand over all of them.
  const other = await relay(['git', 'push', 'origin', 'HEAD:someone-else']);
  ok(other.status === 403 && /no someone-else in this tree/.test(other.error || ''),
     `writing a branch this tree does not have is refused, which is the one on the remote (${
       (other.error || '').slice(0, 70)})`);
  const gone = await relay(['git', 'push', 'origin', '--delete', 'topic']);
  ok(gone.status === 403 && /does not take work away/.test(gone.error || '')
     && execFileSync('git', [`--git-dir=${origin}`, 'branch', '--list', 'topic'], { encoding: 'utf8' }).includes('topic'),
     'a session deleting a branch on the remote is refused, and the branch is still there');
  const colon = await relay(['git', 'push', 'origin', ':topic']);
  ok(colon.status === 403 && /does not take work away/.test(colon.error || ''),
     '...by the colon spelling of a delete as well as by --delete');
  const every = await relay(['git', 'push', '--all', 'origin']);
  ok(every.status === 403 && /every branch/.test(every.error || ''),
     '...and --all, which writes every branch at once');
  const tags = await relay(['git', 'push', '--tags', 'origin']);
  ok(tags.status === 403 && /^--tags sends tags/.test(tags.error || '')
     && /a release's name/.test(tags.error || ''),
     '...and --tags, named as itself since --follow-tags does a different thing');
  await post('/api/prefs', { project: 'beta', gitpol: { push: 'allow', main: 'allow' } });
  ok((await relay(['git', 'push', 'origin', main])).code === 0, `...and ${main} too once allowed`);
  // Allowing main does not widen anything else: it names one more ref, not
  // every ref.
  const stillNot = await relay(['git', 'push', 'origin', 'HEAD:someone-else']);
  const act = async (action, args) => post('/api/git', { project: 'beta', action, args: args || {} });

  // A push that would send a secret or something private is held (R219):
  // the bell shows the lines whole, Approve pushes from the controller and
  // okays those exact lines, Deny drops it, and a line that changes is
  // asked about again. The Git view's Push asks the same in a confirm.
  const cur = git('rev-parse', '--abbrev-ref', 'HEAD');
  writeFileSync(`${B}/secrets.env`, 'GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz0123456789ABCD\nHOME_IP=192.168.1.16\n');
  git('add', 'secrets.env'); git('commit', '-q', '-m', 'with a token');
  const held = await relay(['git', 'push', 'origin', cur]);
  ok(held.status === 200 && held.held && held.code === 1 && /held: 2 lines look sensitive/.test(held.err || ''),
     `a push that would send a token is held, naming what it saw (${(held.err || held.error || '').slice(0, 90)})`);
  const asks = (await (await fetch(URL.replace(/\/$/, '') + '/api/phone', { headers: H })).json()).asks || [];
  const ask = asks.find(a => a.kind === 'push' && a.id === held.held);
  ok(ask && ask.count === 2 && /secrets\.env:1  \(a GitHub token\)/.test(ask.detail || '')
     && /secrets\.env:2  \(an IP address\)/.test(ask.detail || '') && ask.cmd.join(' ') === `git push origin ${cur}`,
     `...and the bell carries the flagged lines whole, each with its file and line (${(ask?.detail || '').slice(0, 70)})`);
  const allowed = await post('/api/phone', { action: 'allow', id: held.held });
  const outcome = await post('/api/phone', { action: 'outcome', id: held.held }, S);
  const top = () => execFileSync('git', [`--git-dir=${origin}`, 'log', '-1', '--format=%s', cur], { encoding: 'utf8' }).trim();
  ok(allowed.status === 200 && outcome.state === 'done' && outcome.code === 0 && top() === 'with a token',
     `Approve pushes it from the controller, and the waiting session reads the outcome (${JSON.stringify(outcome).slice(0, 80)})`);
  writeFileSync(`${B}/other.txt`, 'nothing here\n'); git('add', 'other.txt'); git('commit', '-q', '-m', 'plain');
  const again = await relay(['git', 'push', 'origin', cur]);
  ok(again.status === 200 && again.code === 0 && !again.held && top() === 'plain',
     'the approved lines pass the next push without asking');
  writeFileSync(`${B}/secrets.env`, 'GITHUB_TOKEN=ghp_zyxwvutsrqponmlkjihgfedcba9876543210DCBA\n');
  git('add', 'secrets.env'); git('commit', '-q', '-m', 'rotated');
  const changed = await relay(['git', 'push', 'origin', cur]);
  ok(changed.held && /1 line looks sensitive/.test(changed.err || ''), 'a changed line is asked about again');
  await post('/api/phone', { action: 'deny', id: changed.held });
  ok((await post('/api/phone', { action: 'outcome', id: changed.held }, S)).state === 'denied' && top() === 'plain',
     '...and Deny leaves the remote as it was');
  const pv = await act('push', {});
  ok(pv.confirm && /1 line looks sensitive/.test(pv.confirm) && /secrets\.env:1/.test(pv.confirm),
     `the Git view's Push shows the same lines in its confirm (${(pv.confirm || pv.error || '').slice(0, 60)})`);
  const pv2 = await act('push', { confirmed: true });
  ok(pv2.ok && top() === 'rotated', `...and confirmed, it pushes and okays them (${JSON.stringify(pv2).slice(0, 60)})`);
  // The project's policy can turn the hold off (the operator, 15 Oct): a
  // session's push then goes without being read. Asked as a dry run and the
  // commit taken back, so no line nobody okayed is left in the history a
  // later push to another remote would send.
  // Put together here so this file's own line is not one the scan holds.
  writeFileSync(`${B}/secrets.env`, `GITHUB_TOKEN=${'ghp' + '_'}${'0123456789abcdef'.repeat(3)}\n`);
  git('add', 'secrets.env'); git('commit', '-q', '-m', 'unheld');
  const heldDry = await relay(['git', 'push', '--dry-run', 'origin', cur]);
  const off = await post('/api/prefs', { project: 'beta', gitpol: { scan: 'off' } });
  const unheld = await relay(['git', 'push', '--dry-run', 'origin', cur]);
  ok(heldDry.held && off.gitpol?.scan === 'off' && off.gitpol?.push === 'allow' && unheld.code === 0 && !unheld.held,
     `with the hold off the same line goes without asking (${JSON.stringify(unheld).slice(0, 70)})`);
  ok(/hold a sensitive push: off/.test(bb('git', 'policy')), '...and bb git policy says the hold is off');
  ok((await post('/api/prefs', { project: 'beta', gitpol: { scan: 'allow' } })).error, '...and the hold takes hold or off, nothing else');
  await post('/api/prefs', { project: 'beta', gitpol: { scan: 'hold' } });
  if (heldDry.held) await post('/api/phone', { action: 'deny', id: heldDry.held });
  git('reset', '-q', '--hard', 'HEAD~1');
  ok(stillNot.status === 403 && /its own branches/.test(stillNot.error || ''),
     '...while a branch that is only on the remote stays refused, since that dial names one ref');
  // Push rights hold on the relay itself: a read-only clone's refusing hook
  // is a file in the tree a session can remove (B149).
  writeFileSync(`${DIR}/state/push-rights.json`, JSON.stringify({}));
  const noRights = await relay(['git', 'push', 'origin', 'topic']);
  writeFileSync(`${DIR}/state/push-rights.json`, JSON.stringify({ beta: { repo: 'owner/beta', how: 'key' } }));
  ok(noRights.status === 403 && /no push rights/.test(noRights.error || ''),
     `a project without push rights is refused on the relay, not left to a hook in its tree (${noRights.error})`);
  await post('/api/prefs', { project: 'beta', gitpol: { push: 'allow', main: 'deny' } });

  // The relay never runs git in the tree a session can write (B148). Every
  // program the tree names, in a hook, in its config or as a local remote's
  // pack program, would leave a mark; the network step still happens.
  {
    const mark = `${DIR}/relay-ran-a-program`;
    const touch = `#!/bin/sh\ntouch ${mark}\n`;
    git('checkout', '-q', '-b', 'planted');
    writeFileSync(`${B}/planted.txt`, 'x\n');
    git('add', 'planted.txt');
    git('commit', '-q', '-m', 'Planted');
    git('checkout', '-q', main);
    // Planted after this test's own git has run, which would trip them.
    const planted = `${DIR}/planted-hooks`;
    mkdirSync(planted, { recursive: true });
    for (const h of ['pre-push', 'reference-transaction', 'post-merge']) {
      writeFileSync(`${B}/.git/hooks/${h}`, touch, { mode: 0o755 });
      writeFileSync(`${planted}/${h}`, touch, { mode: 0o755 });
    }
    const plantedConf = [['core.hooksPath', planted], ['core.fsmonitor', `touch ${mark}`],
      ['core.sshCommand', `touch ${mark}`], ['credential.helper', `!touch ${mark}`],
      ['remote.origin.receivepack', `touch ${mark}; git-receive-pack`],
      ['remote.origin.uploadpack', `touch ${mark}; git-upload-pack`]];
    for (const [k, v] of plantedConf) git('config', k, v);
    const pushed = await relay(['git', 'push', 'origin', 'planted']);
    const fetched = await relay(['git', 'fetch', 'origin']);
    const listed = await relay(['git', 'ls-remote', 'origin']);
    ok(pushed.code === 0 && fetched.code === 0 && listed.code === 0 && /refs\/heads\/planted/.test(listed.out || '')
       && execFileSync('git', [`--git-dir=${origin}`, 'branch', '--list', 'planted'], { encoding: 'utf8' }).includes('planted')
       && !existsSync(mark),
       `a relayed push, fetch and ls-remote run none of the programs the tree names in its hooks, config or remote (${
         [pushed, fetched, listed].map(r => r.code ?? r.error).join(',')}, mark ${existsSync(mark) ? 'made' : 'absent'})`);
    ok(JSON.stringify(pushed.apply?.refs || []).includes('refs/remotes/origin/planted'),
       `...and the push hands the node the remote-tracking ref to move, rather than moving it in the tree (${JSON.stringify(pushed.apply)})`);
    for (const [k] of plantedConf) git('config', '--unset-all', k);
    for (const h of ['pre-push', 'reference-transaction', 'post-merge']) rmSync(`${B}/.git/hooks/${h}`, { force: true });

    // The credentials reach only the repository push rights were granted on.
    writeFileSync(`${DIR}/state/push-rights.json`, JSON.stringify({ beta: { repo: 'owner/beta', host: 'example.invalid', how: 'token' } }));
    git('remote', 'set-url', 'origin', 'https://example.invalid/someone/else.git');
    const elsewhere = await relay(['git', 'fetch', 'origin']);
    // A record naming a repository but no host fails CLOSED. The path here
    // MATCHES the one the rights were granted on, so the only thing left to
    // tell this remote from the real one is the host: without it a session,
    // which owns the address in its own tree, could point origin at the same
    // path on a machine it runs and be handed the project's token. Both
    // places that grant rights record a host, so this is an old record and
    // not a reachable state, but a credential boundary does not get to
    // assume that.
    writeFileSync(`${DIR}/state/push-rights.json`,
                  JSON.stringify({ beta: { repo: 'owner/beta', how: 'token' } }));
    git('remote', 'set-url', 'origin', 'https://example.invalid/owner/beta.git');
    const noHost = await relay(['git', 'fetch', 'origin']);
    ok(noHost.status === 400 && /not a host/.test(noHost.error || '')
       && /remote dialog/.test(noHost.error || ''),
       `push rights with no host are refused, not taken as any host (${
         (noHost.error || '').slice(0, 60)})`);
    git('remote', 'set-url', 'origin', `${DIR}/beta-origin-outside.git`);
    const outside = await relay(['git', 'fetch', 'origin']);
    git('remote', 'set-url', 'origin', origin);
    writeFileSync(`${DIR}/state/push-rights.json`, JSON.stringify({ beta: { repo: 'owner/beta', how: 'key' } }));
    ok(elsewhere.status === 400 && /credentials reach only that repository/.test(elsewhere.error || '')
       && /a private one that is another project here is read by adding that project to beta's Reads/.test(elsewhere.error || '')
       && outside.status === 400 && /not a repository on the projects share/.test(outside.error || ''),
       `a remote pointed at another repository, or at a local path off the share, is refused before git runs (${
         (elsewhere.error || '').slice(0, 50)} | ${(outside.error || '').slice(0, 50)})`);

    // From a node, bb finishes the job in its own tree: the objects a pull
    // fetched, the refs that moved, the merge; an upstream after push -u.
    const nodeEnv = { ...process.env, BUILDERBOT_ROLE: 'node', BB_CONTROLLER: URL.replace(/\/$/, ''),
                      BB_TOKEN: tok, BB_NODE: 'agentbox', BB_PROJECT: 'beta', WORKSPACE: `${DIR}/ws` };
    const onNode = (...a) => { try { return execFileSync('bash', [`${REPO}/scripts/bb`, ...a], { encoding: 'utf8', env: nodeEnv, cwd: B, stdio: ['ignore', 'pipe', 'pipe'] }); }
                               catch (e) { return `FAILED ${e.status}: ${e.stdout || ''}${e.stderr || ''}`; } };
    const clone = `${DIR}/beta-clone`;
    execFileSync('git', ['-C', clone, 'pull', '-q', 'origin', main]);
    writeFileSync(`${clone}/from-the-remote.txt`, 'y\n');
    execFileSync('git', ['-C', clone, 'add', 'from-the-remote.txt']);
    execFileSync('git', ['-C', clone, 'commit', '-q', '-m', 'Waiting on the remote']);
    execFileSync('git', ['-C', clone, 'push', '-q', 'origin', `HEAD:${main}`]);
    const pulled = onNode('git', 'pull', 'origin', main);
    const bundles = existsSync(`${B}/.git/bb-relay`) ? execFileSync('ls', [`${B}/.git/bb-relay`], { encoding: 'utf8' }).trim() : '';
    ok(git('log', '-1', '--format=%s') === 'Waiting on the remote' && existsSync(`${B}/from-the-remote.txt`)
       && git('rev-parse', `refs/remotes/origin/${main}`) === git('rev-parse', 'HEAD') && bundles === '',
       `bb git pull on a node brings the commit into its own tree and moves its remote-tracking ref, leaving no bundle behind (${
         pulled.replace(/\s+/g, ' ').slice(0, 120)})`);
    git('checkout', '-q', '-b', 'fromnode');
    const up = onNode('git', 'push', '-u', 'origin', 'fromnode');
    ok(git('config', 'branch.fromnode.merge') === 'refs/heads/fromnode' && git('rev-parse', 'refs/remotes/origin/fromnode') === git('rev-parse', 'HEAD'),
       `bb git push -u on a node sets the upstream and the remote-tracking ref in its own tree (${up.replace(/\s+/g, ' ').slice(0, 80)})`);
    git('checkout', '-q', main);
  }

  // Send to Claude lands in the project's session as one line naming the
  // thing and the ask; the session reads the rest from the tree itself.
  tmuxNew('claude-beta', B);
  const head = (await api('what=log')).commits[0];
  const sent = await post('/api/git', { project: 'beta', action: 'ask', kind: 'review', args: { sha: head.sha } });
  ok(sent.ok && sent.sent, `a commit is sent to the session and arrives (${sent.text || sent.error})`);
  const pane = tmuxCapture('claude-beta');
  ok(/Git view of beta/.test(pane) && pane.includes(head.sha.slice(0, 7)) && /review it/.test(pane),
     '...as a line naming the commit and the ask, and nothing of the diff');
  writeFileSync(`${B}/a.txt`, 'one\ntwo\nfive\n');
  const sentFile = await post('/api/git', { project: 'beta', action: 'ask', kind: 'diff', args: { path: 'a.txt' } });
  ok(sentFile.ok && /uncommitted change to a.txt/.test(sentFile.text), 'a changed file is sent by its path');
  const sentBranch = await post('/api/git', { project: 'beta', action: 'ask', kind: 'merge', args: { branch: 'topic' } });
  ok(sentBranch.ok && /branch topic/.test(sentBranch.text) && new RegExp(`merge it into ${main}`).test(sentBranch.text),
     'a branch is sent with the ask picked for it');
  ok((await post('/api/git', { project: 'beta', action: 'ask', kind: 'review', args: { sha: 'zzz' } })).error
     && (await post('/api/git', { project: 'beta', action: 'ask', kind: 'dance', args: { sha: head.sha } })).error
     && (await post('/api/git', { project: 'beta', action: 'ask', kind: 'diff', args: { path: 'README.md' } })).error,
     'a commit, a kind or a file that is not one is refused, not sent');
  tmuxKill('claude-beta');
  execFileSync('git', ['-C', B, 'checkout', '-q', '--', 'a.txt']);
  // ...and it is the PRESSER's session (B235). The bare name alone was the
  // owner's, so a second account's press typed into the owner's
  // conversation, or found no session while its own was running.
  {
    const hh = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
    for (const body of [{ action: 'add', name: 'w.asker', password: 'w.asker-pass-1', role: 'user' },
                        { action: 'projects', name: 'w.asker', projects: ['beta'] }])
      await fetch(URL.replace(/\/$/, '') + '/api/users', { method: 'POST', headers: hh, body: JSON.stringify(body) });
    await member('w.asker');
    const auid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users['w.asker'].uid;
    const theirs = `${auid}~claude-beta`;
    tmuxNew(theirs, B);
    const r = await fetch(URL.replace(/\/$/, '') + '/api/git', { method: 'POST',
      headers: { Authorization: 'Basic ' + Buffer.from('w.asker:w.asker-pass-1').toString('base64'), 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: 'beta', action: 'ask', kind: 'review', args: { sha: head.sha } }) });
    const their = await r.json();
    ok(their.ok && their.session === theirs && tmuxCapture(theirs).includes(head.sha.slice(0, 7)),
       `a second account's Send to Claude lands in its own session (${their.session || their.error})`);
    tmuxKill(theirs);
  }

  // ...and the view carries them.
  writeFileSync(`${B}/a.txt`, 'one\ntwo\nsix\n');
  await page.evaluate(() => getNotebook('beta').view('git'));
  await refreshUntil(page, () => !!document.querySelector('.nb .nbview[data-view="git"] [data-gitaskfile]'), { timeout: 20000 });
  // A row that is not already picked: a click on the picked row puts it
  // away, and which row that is depends on what the tests above committed.
  await openFold(page, '.nb .nbview[data-view="git"] [data-sect="git:history"]');   // one section open at a time (the operator, 5 Oct)
  await page.click('.nb .nbview[data-view="git"] .grow[data-sha]:not(.on)');
  // Read in one look, and waited for as one: the view repaints on the poll,
  // and a wait for the commit's button followed by a second read of the
  // view could land either side of a repaint (it did, twice in one run).
  const look = () => page.$eval('.nb .nbview[data-view="git"]', el => ({
    file: !!el.querySelector('[data-gitaskfile]'), commit: !!el.querySelector('#gitDetail [data-gitaskcommit]'),
    branch: el.querySelectorAll('[data-gitaskbranch]').length,
    pol: el.querySelectorAll('[data-gitpol]').length }));
  await page.waitForFunction(() => {
    const el = document.querySelector('.nb .nbview[data-view="git"]');
    return el && el.querySelector('[data-gitaskfile]') && el.querySelector('#gitDetail [data-gitaskcommit]')
      && el.querySelectorAll('[data-gitaskbranch]').length >= 1;
  }, null, { timeout: 10000 }).catch(() => {});
  const v = await look();
  ok(v.file && v.commit && v.branch >= 1 && v.pol === 0,
     `the view offers Send to Claude on a change, a commit and a branch, and no push policy, which is the Permissions view's (${JSON.stringify(v)})`);
  // Every Send to Claude asks first (the operator, 6 Oct): what it sends is
  // a prompt Claude starts on at once. Answered no here, so nothing goes.
  {
    const asks = [];
    const seen = req => { if (req.url().endsWith('/api/git') && /"action":"ask"/.test(req.postData() || '')) asks.push(1); };
    page.on('request', seen);
    await page.evaluate(() => { window.__confirm = window.confirm; window.confirm = m => { window.__asked = m; return false; }; });
    // Pressed from the page: the change sits in a section shut by default.
    await page.$eval('.nb .nbview[data-view="git"] [data-gitaskfile]', b => b.click());
    await page.waitForTimeout(300);
    const asked = await page.evaluate(() => { const m = window.__asked; window.confirm = window.__confirm; delete window.__asked; return m || ''; });
    page.off('request', seen);
    ok(/^Send .* to beta's Claude session\?/.test(asked) && asks.length === 0,
       `Send to Claude asks first, naming the session, and sends nothing when the answer is no (${asked.split('\n')[0]}; ${asks.length} sent)`);
  }
  // What a session may do, in one view of its own beside Overview and
  // Settings (the operator, 22 Oct): the settings form's Agents may section
  // lent to it, and the push policy under it, staged until Apply.
  await page.evaluate(() => openNotebook('beta', 'permissions'));
  await page.waitForSelector('.nb .nbview[data-view="permissions"] [data-gitpol="push"]', { state: 'visible', timeout: 10000 });
  const perm = await page.$eval('.nb .nbview[data-view="permissions"]', el => ({
    dials: !!el.querySelector('details[data-sect="rn:claude"] #rnGateRoadmap'), pol: el.querySelectorAll('[data-gitpol]').length,
    apply: el.querySelector('.permGitApply')?.disabled }));
  ok(perm.dials && perm.pol === 3 && perm.apply === true,
     `Permissions holds Agents may and the push policy, its Apply asleep (${JSON.stringify(perm)})`);
  await page.selectOption('.nb .nbview[data-view="permissions"] [data-gitpol="push"]', 'deny');
  ok(await page.$eval('.nb .nbview[data-view="permissions"] .permGitApply', b => !b.disabled),
     '...picking a policy wakes Apply and saves nothing yet');
  await page.selectOption('.nb .nbview[data-view="permissions"] [data-gitpol="push"]', 'allow');
  // ...and the section goes home: Settings has the form whole, Agents may
  // in it but not in its list.
  await page.evaluate(() => openNotebook('beta', 'settings'));
  await page.waitForSelector('.nb .nbview[data-view="settings"] .nbsettings > .box', { timeout: 10000 });
  const home = await page.$eval('.nb .nbview[data-view="settings"]', el => ({
    inForm: !!el.querySelector('.nbsettings > .box > details[data-sect="rn:claude"]'),
    listed: [...el.querySelectorAll('.snav [data-spick]')].map(b => b.dataset.spick).includes('claude'),
    left: !!document.querySelector('.nb .nbview[data-view="permissions"]:not(.fghost) details[data-sect="rn:claude"]') }));
  ok(home.inForm && !home.listed && !home.left,
     `leaving Permissions hands Agents may back to the form, which Settings does not list (${JSON.stringify(home)})`);
  await page.evaluate(() => openNotebook('beta', 'git'));
  execFileSync('git', ['-C', B, 'checkout', '-q', '--', 'a.txt']);
}

// ---- the strip on a phone -------------------------------------------------
// Five groups in one row (R259, the operator 16 Oct: eleven tabs were too
// many), the open group's views in one row under it, every one on screen.
await page.setViewportSize({ width: 393, height: 851 });
await page.waitForFunction(() => document.querySelector('.nb .nbtabs')?.getBoundingClientRect().width > 0);
const strip = await page.$eval('.nb .nbtabs', el => {
  const row = sel => { const bs = [...el.querySelectorAll(sel)].filter(b => b.offsetWidth).map(b => b.getBoundingClientRect());
    const box = el.getBoundingClientRect();
    return { n: bs.length, rows: new Set(bs.map(b => Math.round(b.top))).size,
             inside: bs.every(b => b.left >= box.left - 1 && b.right <= box.right + 1) }; };
  return { groups: row('.nbgroups button'), views: row('.nbsub button'), over: el.scrollWidth - el.clientWidth };
});
ok(strip.groups.n === 5 && strip.groups.rows === 1 && strip.groups.inside && strip.views.n >= 2 && strip.views.rows === 1
   && strip.views.inside && strip.over <= 0,
   `on a phone the strip is five groups in one row and the open group's views in one row under it, every tab on screen (${JSON.stringify(strip)})`);

// Back goes back (R256 step 3): a view switched to is a history entry, and
// a node page's address names the node it shows.
{
  await page.setViewportSize({ width: 1280, height: 900 });
  const before = await page.evaluate(() => location.hash);
  await page.click('.pane .nb .nbgroups [data-g="plan"] >> visible=true');
  await page.waitForFunction(b => location.hash !== b && /\/roadmap$/.test(location.hash), before, { timeout: 10000 });
  await page.goBack();
  await page.waitForFunction(b => location.hash === b, before, { timeout: 10000 });
  const view = await page.evaluate(() => getNotebook(tabOf(panes[0])?.arg)?.where());
  ok(/\/git$/.test(before) && view === 'git', `a view switched to is a history entry, and Back returns to the one before (${before}, ${view})`);
  await page.evaluate(() => railGo('build', 'toolchains'));
  await page.waitForFunction(() => /^#\/build\/toolchains\/[^/]+$/.test(location.hash), null, { timeout: 15000 });
  const tc = await page.evaluate(() => ({ hash: location.hash, node: tcNode }));
  ok(tc.hash.endsWith('/' + encodeURIComponent(tc.node)), `a node page's address names its node (${tc.hash})`);
}

// bb projects lists what the dashboard lists: a directory carrying .bbignore
// (the fixture's toolchain store) is not a project, and a worktree, whose .git
// is a file naming its repository, is one and has a branch (B122).
{
  git('worktree', 'add', '-q', `${DIR}/ws/beta-wt`, '-b', 'wtcheck');
  const listed = execFileSync('bash', [`${REPO}/scripts/bb`, 'projects'],
    { encoding: 'utf8', env: { ...process.env, WORKSPACE: `${DIR}/ws`, DASHBOARD_STATE: `${DIR}/state` } });
  ok(/beta-wt\s+git: wtcheck/.test(listed) && !/toolstore/.test(listed) && !/beta-wt.*not a git repo/.test(listed),
     `bb projects skips a .bbignore directory and names a worktree's branch (${listed.split('\n').filter(l => /beta-wt|toolstore/.test(l)).join(' | ') || 'neither line'})`);
  git('worktree', 'remove', '--force', `${DIR}/ws/beta-wt`);
  git('branch', '-D', 'wtcheck');
}

// ---- a branch is its session's: its account's, or an administrator's ------
// The operator's rule of 24 Sep. A branch checked out in another account's
// worktree is theirs. A plain account may not merge it, have a session merge
// it, or delete it, and its row offers none of that and says whose it is. An
// administrator may merge it, asked every time with the owner named, and
// never while that account's Claude session there is working. Before the
// fallback check below, so these writes are held to it too.
{
  const H2 = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const PEER = { Authorization: 'Basic ' + Buffer.from('w.peer:w.peer-pass-1').toString('base64'), 'Content-Type': 'application/json' };
  const post = async (body, h = H2) => { const r = await fetch(URL.replace(/\/$/, '') + '/api/git',
    { method: 'POST', headers: h, body: JSON.stringify(body) }); return { status: r.status, ...(await r.json()) }; };
  const users = async body => fetch(URL.replace(/\/$/, '') + '/api/users',
    { method: 'POST', headers: H2, body: JSON.stringify(body) });
  for (const n of ['w.dev', 'w.peer']) {
    await users({ action: 'add', name: n, password: `${n}-pass-1`, role: 'user' });
    await users({ action: 'projects', name: n, projects: ['beta'] });
    await member(n);
  }
  const uid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users['w.dev'].uid;
  const WT = `${DIR}/ws/.worktrees/beta/${uid}`;
  mkdirSync(`${DIR}/ws/.worktrees/beta`, { recursive: true });
  git('worktree', 'add', '-q', '-b', 'claude/w.dev', WT, main);
  writeFileSync(`${WT}/dev.txt`, 'from w.dev\n');
  execFileSync('git', ['-C', WT, 'add', 'dev.txt']);
  execFileSync('git', ['-C', WT, 'commit', '-q', '-m', 'Work by w.dev']);
  ok((await api('what=branches')).branches.find(b => b.name === 'claude/w.dev')?.who === 'w.dev',
     "a branch checked out in an account's worktree is that account's");
  const merge = { project: 'beta', action: 'merge', args: { name: 'claude/w.dev', into: main } };
  const peer = await post(merge, PEER);
  const peerAsk = await post({ project: 'beta', action: 'ask', kind: 'merge', args: { branch: 'claude/w.dev' } }, PEER);
  const peerDel = await post({ project: 'beta', action: 'delete', args: { name: 'claude/w.dev' } }, PEER);
  ok(peer.status === 403 && /claude\/w\.dev is w\.dev's session's branch: only w\.dev merges it/.test(peer.error || '')
     && peerAsk.status === 403 && peerDel.status === 403,
     `a plain account may not merge another account's session's branch, ask a session to, or delete it (${peer.error})`);
  const unasked = await post(merge);
  ok(unasked.status === 409 && /w\.dev's session's branch/.test(unasked.confirm || ''),
     `an administrator is asked first, with the owner named (${(unasked.confirm || '').replace(/\n+/g, ' ')})`);
  // w.dev's session on beta, mid-prompt: the spinner in its pane title is
  // what the dashboard reads a working session by.
  tmuxNew(`${uid}~claude-beta`, WT);
  execFileSync('tmux', ['select-pane', '-t', `=${uid}~claude-beta:`, '-T', '\u25d0 Writing the parser']);
  const busy_ = await post({ ...merge, args: { ...merge.args, confirmed: true } });
  ok(busy_.status === 403 && /w\.dev's Claude session is working right now/.test(busy_.error || ''),
     `...and refused while that account's session is working on it (${busy_.error})`);
  tmuxKill(`${uid}~claude-beta`);
  // The page: an administrator's row keeps Merge, and pressing it asks.
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => getNotebook('beta').view('git'));
  await refreshUntil(page, () => [...document.querySelectorAll('.nb .nbview[data-view="git"] .gbranch')]
    .some(r => r.querySelector('code')?.textContent === 'claude/w.dev'));
  const rowOf = p => p.evaluate(() => {
    const r = [...document.querySelectorAll('.nb .nbview[data-view="git"] .gbranch')]
      .find(x => x.querySelector('code')?.textContent === 'claude/w.dev');
    return { merge: !!r.querySelector('[data-gitmerge][data-gitwho="w.dev"]'),
             acts: r.querySelectorAll('[data-gitmerge], [data-gitswitch], [data-gitdelete]').length,
             asks: [...r.querySelectorAll('[data-gitaskkind]')].map(o => o.dataset.gitaskkind),
             text: r.textContent.replace(/\s+/g, ' ') };
  });
  const adminRow = await rowOf(page);
  ok(adminRow.merge && /w\.dev's session/.test(adminRow.text) && !/only w\.dev/.test(adminRow.text),
     `an administrator's row keeps Merge into ${main} on it, marked whose (${JSON.stringify({ merge: adminRow.merge, asks: adminRow.asks })})`);
  page.dialogs = [];
  await page.evaluate(() => [...document.querySelectorAll('.nb .nbview[data-view="git"] .gbranch')]
    .find(x => x.querySelector('code')?.textContent === 'claude/w.dev')
    ?.querySelector('[data-gitmerge]').click());
  let landed = false;
  for (let i = 0; i < 40 && !landed; i++) {
    try { git('merge-base', '--is-ancestor', 'claude/w.dev', main); landed = true; }
    catch { await new Promise(r => setTimeout(r, 250)); }
  }
  ok(page.dialogs.some(d => /^Merge claude\/w\.dev into /.test(d) && /claude\/w\.dev is w\.dev's session's branch\./.test(d))
     && landed,
     `...and pressing it asks, naming whose, then merges (${page.dialogs.join(' | ').replace(/\n+/g, ' ')})`);
  // A plain account's row offers none of it and says why.
  writeFileSync(`${B}/owner-note.txt`, 'the owner\'s own change\n');
  const peerPage = await newPage(browser, { viewport: { width: 1280, height: 900 },
    httpCredentials: { username: 'w.peer', password: 'w.peer-pass-1' },
    extraHTTPHeaders: { Authorization: PEER.Authorization } });
  await peerPage.goto(URL);
  await ready(peerPage);
  await peerPage.evaluate(() => openNotebook('beta', 'git'));
  await refreshUntil(peerPage, () => [...document.querySelectorAll('.nb .nbview[data-view="git"] .gbranch')]
    .some(r => r.querySelector('code')?.textContent === 'claude/w.dev'));
  const peerRow = await rowOf(peerPage);
  const peerTreeView = await peerPage.evaluate(() => {
    const v = document.querySelector('.nb .nbview[data-view="git"]');
    return { hint: document.querySelector('.nb #gitHint')?.textContent || '',
             writes: v.querySelectorAll('#gitCommit, [data-gitdiscard], [data-gitswitch], #gitPicker .gbpickmenu, [data-gitaskfile]').length,
             note: /only test commits or discards them/.test(v.textContent) };
  });
  ok(/test's working tree/.test(peerTreeView.hint) && peerTreeView.writes === 0 && peerTreeView.note,
     `...and its view says whose working tree it is and offers nothing that changes it (${JSON.stringify(peerTreeView)})`);
  // Review at most: the merge above put the branch in main, and a branch with
  // nothing of its own has nothing to review either (B80).
  ok(peerRow.acts === 0 && peerRow.asks.every(k => k === 'review') && /only w\.dev merges it/.test(peerRow.text),
     `...while a plain account's row offers none of it and says whose it is (${JSON.stringify({ acts: peerRow.acts, asks: peerRow.asks })})`);
  await peerPage.close();
  // B236: the project directory is the owner's working tree. A plain
  // account changes nothing in it; an administrator is asked first.
  const treeWrites = [['commit', { message: 'from w.peer' }], ['discard', { path: 'a.txt' }],
                      ['switch', { name: main }], ['pull', {}], ['revert', { sha: 'zzzz' }],
                      ['branch', { name: 'peer-topic', switch: true }]];
  const peerTree = [];
  for (const [action, args] of treeWrites) peerTree.push(await post({ project: 'beta', action, args }, PEER));
  ok(peerTree.every(r => r.status === 403 && /the project directory is test's working tree: only test can/.test(r.error || '')),
     `a plain account cannot commit, discard, switch, pull, revert or branch-and-switch in the owner's tree (${
       peerTree.map(r => r.status).join(',')}: ${peerTree[0].error})`);
  for (const body of [{ action: 'add', name: 'w.boss', password: 'w.boss-pass-1', role: 'admin' },
                      { action: 'projects', name: 'w.boss', projects: ['beta'] }]) await users(body);
  const BOSS = { Authorization: 'Basic ' + Buffer.from('w.boss:w.boss-pass-1').toString('base64'), 'Content-Type': 'application/json' };
  const bossAsked = await post({ project: 'beta', action: 'revert', args: { sha: 'zzzz' } }, BOSS);
  const bossSure = await post({ project: 'beta', action: 'revert', args: { sha: 'zzzz', confirmed: true } }, BOSS);
  ok(bossAsked.status === 409 && /test's working tree/.test(bossAsked.confirm || '')
     && !/working tree/.test(bossSure.error || '') && bossSure.status !== 409,
     `an administrator is asked first, naming whose tree, and then goes on (${bossSure.error})`);
  const theirs = { Authorization: 'Basic ' + Buffer.from('w.dev:w.dev-pass-1').toString('base64'), 'Content-Type': 'application/json' };
  const own = await post(merge, theirs);
  ok(!/session's branch|asked/.test(own.error || '') && own.status !== 409,
     `...and its own account merges it unasked (${own.ok ? (own.out || 'merged').slice(0, 40) : (own.error || '').slice(0, 60)})`);
  git('worktree', 'remove', '--force', WT);
  git('branch', '-D', 'claude/w.dev');
  rmSync(`${B}/owner-note.txt`, { force: true });
  page.errors = [];                     // the 403s and the 409 above are refusals by design
}

// B153's protection degrades QUIETLY by design: where the controller cannot
// build a git dir of its own it falls back to the tree, because a Git view
// that goes blank is worse than one still doing what it always did. That is
// the right default and a terrible thing to leave untested: the fallback runs
// the tree's hooks, so a transient failure turns every guarantee above into a
// coin toss, and the only trace is a line in the log. Read it here, which is
// how a hook firing in the container was told from a test being wrong (R65).
{
  const log = (() => { try { return readFileSync(`${DIR}/server.log`, 'utf8'); }
                       catch { return ''; } })();
  const fell = log.split('\n').filter(l => /falling back to the tree/.test(l));
  ok(fell.length === 0,
     `the controller never fell back to running git in the tree (${
       fell.length ? fell[0].slice(0, 400) : 'no fallback'})`);
}
// ---- a project with no repository gets one from the view ----------------
// gamma is the fixture's directory-only project. It could be adopted,
// listed and opened, and its Git view said "nothing to show" with no way
// on: no version, no dist/, no push, and a session told not to decide that
// for the person. Init is that way, from the API and from the row.
{
  const H2 = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  const g = async (action) => { const r = await fetch(URL.replace(/\/$/, '') + '/api/git',
    { method: 'POST', headers: H2, body: JSON.stringify({ project: 'gamma', action, args: {} }) });
    return { status: r.status, ...(await r.json()) }; };
  await page.evaluate(() => openNotebook('gamma', 'git'));
  await page.waitForSelector('.nb[data-project="gamma"] .nbview[data-view="git"] [data-gitinit]', { timeout: 20000 });
  ok(/no repository yet/.test(await page.$eval('.nb[data-project="gamma"] #gitHint', e => e.textContent)),
     'a project with no repository says so on the Git view, with an Init button under it');
  await page.click('.nb[data-project="gamma"] .nbview[data-view="git"] [data-gitinit]');
  await page.waitForFunction(() => document.querySelector('.nb[data-project="gamma"] #gitPicker .gbpickname')?.textContent === 'main',
                             null, { timeout: 20000 });
  ok(existsSync(`${DIR}/ws/gamma/.git`) && !existsSync(`${DIR}/ws/gamma/.git/refs/heads/main`),
     '...and Init makes the repository on main with nothing committed, and the view redraws on it');
  const again = await g('init');
  ok(again.status !== 200 || again.error, `...and a second Init is refused (${again.error || '?'})`);
  ok(readFileSync(`${DIR}/ws/gamma/.git/info/exclude`, 'utf8').split('\n').includes('.bb-map/'),
     '...and the repository it makes keeps the code map out, as a created project does');
  // B234: two branches with no commit in common, the shape a project that
  // began without a repository ends up in. Joined only when asked.
  const G = `${DIR}/ws/gamma`;
  const who = { ...process.env, GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 't@example.invalid',
                GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 't@example.invalid' };
  const gg = (...a) => execFileSync('git', ['-C', G, ...a], { encoding: 'utf8', env: who }).trim();
  gg('add', '-A'); gg('commit', '-q', '-m', 'Start');
  const blob = execFileSync('git', ['-C', G, 'hash-object', '-w', '--stdin'], { input: 'the app\n', encoding: 'utf8' }).trim();
  const tree = execFileSync('git', ['-C', G, 'mktree'], { input: `100644 blob ${blob}\tapp.txt\n`, encoding: 'utf8' }).trim();
  gg('branch', 'app', execFileSync('git', ['-C', G, 'commit-tree', tree, '-m', 'The app'], { encoding: 'utf8', env: who }).trim());
  const merge = async extra => { const r = await fetch(URL.replace(/\/$/, '') + '/api/git', { method: 'POST', headers: H2,
    body: JSON.stringify({ project: 'gamma', action: 'merge', args: { name: 'app', ...extra } }) });
    return { status: r.status, ...(await r.json()) }; };
  const asked = await merge({});
  ok(asked.unrelated === true && /app and main share no history/.test(asked.error || '') && !existsSync(`${G}/app.txt`),
     `a merge of two branches with no history in common asks first, and does nothing yet (${asked.error})`);
  const joined = await merge({ unrelated: true });
  ok(joined.ok && existsSync(`${G}/app.txt`) && gg('log', '-1', '--format=%P').split(' ').length === 2,
     `...and joins them into one history when the answer is yes (${joined.out || joined.error})`);
  // The view's first read of a project with no repository is a 400 by
  // design, and the browser logs every one as a failed resource. Cleared,
  // so the check below is about the page.
  page.errors = [];
}

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
// B164: a repository with no main and no master. Merge into main cannot
// mean anything there, and the refusal said "or on :" with the name empty.
{
  const said = execFileSync('python3', ['-c', `
import importlib.util, json, os, subprocess, tempfile
spec = importlib.util.spec_from_file_location("git", "${REPO}/scripts/dashboard/git.py")
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
ws = tempfile.mkdtemp(dir="${DIR}")
g.configure(workspace=ws, state="${DIR}/state")
repo = os.path.join(ws, "nomain")
run = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True)
os.makedirs(repo)
run("init", "-q", "-b", "trunk")
run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one")
run("branch", "feat"); run("checkout", "-q", "feat")
print(json.dumps(g.act(repo, "merge", {"name": "trunk", "into": "main"})))`], { encoding: 'utf8' }).trim();
  const r = JSON.parse(said.split('\n').pop());   // the module may print a line of its own first
  ok(/no main or master branch/.test(r.error || '') && !/or on :/.test(r.error || '') && !/Switch to/.test(r.error || ''),
     `with no main or master, the merge refusal says so rather than naming an empty branch (${r.error})`);
}

// ---- the CI watch (R117) ------------------------------------------------------
// What the daily look found, planted where ciwatch keeps it: a CI section on
// the Git view saying it in rows, a bell row while main is red, and Look now
// replacing it with a fresh look (beta has no workflows, and it says so).
{
  mkdirSync(`${DIR}/state/ciwatch`, { recursive: true });
  writeFileSync(`${DIR}/state/ciwatch/beta.json`, JSON.stringify({
    format: 3, at: Math.floor(Date.now() / 1000) - 3600, repo: 'o/beta', workflows: 1,
    run: { id: 11, name: 'Android CI', branch: 'main', conclusion: 'failure', at: '2026-10-03T00:44:51Z' },
    findings: [
      { kind: 'run', sev: 'bad', where: 'run 11', url: 'https://github.com/o/beta/actions/runs/11',
        text: 'The Android CI check failed on main (3 Oct, 00:44 UTC). A Claude session can read why with bb ci-log 11.' },
      { kind: 'label', sev: 'warn', where: 'android.yml:10', text: 'runs on ubuntu-latest, which GitHub moves to a new release on its own date',
        fix: { from: 'ubuntu-latest', to: 'ubuntu-24.04' } },
      { kind: 'action', sev: 'note', where: 'android.yml:14', text: 'android-actions/setup-android@v3: v4 is out' }],
    error: '' }));
  const ci = await api('what=all').then(j => j.ci || {});
  ok(ci.run?.id === 11 && ci.findings?.length === 3, `the Git view's payload carries what the watch found (${ci.findings?.length})`);
  // Opening the view reads it again.
  await page.evaluate(() => openNotebook('beta', 'git'));
  await page.waitForFunction(sel => document.querySelector(sel)?.textContent === 'failing',
                             `${NB} details.sect[data-sect="git:ci"] .sst`, { timeout: 20000 }).catch(() => {});
  const sect = await page.$eval(`${NB} details.sect[data-sect="git:ci"]`, d => ({
    status: d.querySelector('.sst')?.textContent, bad: d.querySelector('.sst')?.classList.contains('bad'),
    open: d.open, rows: [...d.querySelectorAll('.body .actbar .state')].map(e => e.textContent.replace(/\s+/g, ' ').trim()) }));
  ok(sect.status === 'failing' && sect.bad && sect.open, `a red main branch opens the CI section, marked failing (${sect.status})`);
  ok(sect.rows.some(r => /^Check: The Android CI check failed on main/.test(r))
     && sect.rows.some(r => /^Runner: .*ubuntu-latest.*android\.yml:10/.test(r))
     && sect.rows.some(r => /^Action: .*setup-android.*v4 is out/.test(r)),
     `...each finding a row in words, with where it is (${JSON.stringify(sect.rows)})`);
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => (state?.ci_red || []).some(c => c.project === 'beta'), null, { timeout: 15000 });
  await page.evaluate(() => toggleBell(true));
  const bell = await page.$eval('#bellPanel', p => [...p.querySelectorAll('.bnote')].map(n => n.textContent.replace(/\s+/g, ' ').trim())
    .find(t => /CI failing in beta/.test(t)) || '');
  const link = await page.$eval('#bellPanel', p => [...p.querySelectorAll('.bnote a[target="_blank"]')].map(a => a.href).join());
  ok(/The Android CI check failed on main/.test(bell) && /Git view/.test(bell) && /On GitHub/.test(bell)
     && link === 'https://github.com/o/beta/actions/runs/11',
     `the bell carries a row while main is red, with the way to the Git view (${bell.slice(0, 80)})`);
  await page.evaluate(() => toggleBell(false));
  // R117 step 4: the runner row carries Fix, which writes that one line into
  // the working tree, uncommitted, and Changes shows it; nothing is pushed.
  {
    const GITENV = { ...process.env, GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 't@example.invalid',
                     GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 't@example.invalid' };
    const wf = `${DIR}/ws/beta/.github/workflows`;
    mkdirSync(wf, { recursive: true });
    writeFileSync(`${wf}/android.yml`, Array.from({ length: 12 }, (_, i) => i === 9 ? '    runs-on: ubuntu-latest' : `# line ${i + 1}`).join('\n') + '\n');
    execFileSync('git', ['-C', `${DIR}/ws/beta`, 'add', '.github'], { env: GITENV });
    execFileSync('git', ['-C', `${DIR}/ws/beta`, 'commit', '-qm', 'a workflow'], { env: GITENV });
    await page.evaluate(() => openNotebook('beta', 'git'));
    await page.waitForSelector(`${NB} [data-cifix="android.yml:10"]`, { timeout: 15000 });
    ok(await page.$$eval(`${NB} [data-cifix]`, bs => bs.length) === 1, 'only the finding that carries a fix offers Fix');
    await openFold(page, `${NB} [data-sect="git:ci"]`);   // one section open at a time (the operator, 5 Oct)
    await page.click(`${NB} [data-cifix="android.yml:10"]`);
    await page.waitForFunction(sel => [...document.querySelectorAll(sel)].some(e => /android\.yml/.test(e.textContent)),
                               `${NB} details.gfile summary`, { timeout: 15000 });
    const line = readFileSync(`${wf}/android.yml`, 'utf8').split('\n')[9];
    const head = execFileSync('git', ['-C', `${DIR}/ws/beta`, 'log', '-1', '--format=%s'], { encoding: 'utf8' }).trim();
    ok(line === '    runs-on: ubuntu-24.04' && head === 'a workflow',
       `Fix writes the pinned label on that line and commits nothing; Changes lists the file (${line.trim()}; HEAD ${head})`);
    // Put back as it was: the commit and the file go, so the look below
    // still finds a beta with no workflows.
    execFileSync('git', ['-C', `${DIR}/ws/beta`, 'reset', '-q', '--hard', 'HEAD~1'], { env: GITENV });
    rmSync(`${DIR}/ws/beta/.github`, { recursive: true, force: true });
  }
  await page.click(`${NB} #gitCiLook`);
  await page.waitForFunction(sel => document.querySelector(sel)?.textContent === 'no workflows',
                             `${NB} details.sect[data-sect="git:ci"] .sst`, { timeout: 20000 });
  const fresh = JSON.parse(readFileSync(`${DIR}/state/ciwatch/beta.json`, 'utf8'));
  ok(fresh.findings.length === 0 && fresh.workflows === 0, 'Look now looks again and keeps it: beta has no workflows');
  // B81: and the section says that, not "nothing drifting" in green.
  const bare = await page.$eval(`${NB} details.sect[data-sect="git:ci"]`, d => ({
    ok: d.querySelector('.sst').classList.contains('ok'), said: d.querySelector('.body .sub').textContent }));
  ok(!bare.ok && /no workflow in \.github\/workflows/.test(bare.said),
     `...and the section says there is no CI and where it looked, not "nothing drifting" in green (${bare.said})`);
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => !(state?.ci_red || []).length, null, { timeout: 15000 });
  ok(true, '...and the bell row leaves with the red run');
  rmSync(`${DIR}/state/ciwatch/beta.json`, { force: true });
}

await done(browser);
