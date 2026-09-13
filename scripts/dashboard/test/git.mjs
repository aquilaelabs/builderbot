// The notebook's Git view (roadmap R36, step 1): the repository read out —
// what is changed and not committed, the history as a graph, one commit's
// detail and diff, and the branches with whose worktree sits on which.
// Real git on the fixture repos, read by the checkout's server; nothing
// here writes through the dashboard, because this step has no actions.
import { launch, newPage, ok, done, ready, refreshUntil, tmuxNew, tmuxKill, tmuxCapture, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdirSync, existsSync, rmSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const B = `${DIR}/ws/beta`;
const git = (...a) => execFileSync('git', ['-C', B, ...a], { encoding: 'utf8' }).trim();
// A history worth a graph: two commits on the main line, a branch off the
// first with one of its own, and a merge back — four lanes' worth of
// edges — plus a session's branch the way session_dir names one, and an
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
writeFileSync(`${B}/a.txt`, 'one\ntwo\nthree\n');
writeFileSync(`${B}/new.txt`, 'brand new\n');

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

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
ok(br.branches.find(b => b.name === 'feature')?.main_behind >= 1,
   `...and how far each stands from ${main}`);
ok((await api('what=status').then(() => fetch(URL.replace(/\/$/, '') + '/api/git?project=nope&what=status',
  { headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') } }))).status === 400,
   'a project that is not one is refused');

// ---- the view ---------------------------------------------------------------
await page.evaluate(() => openNotebook('beta', 'git'));
await page.waitForFunction(() => /on \S+/.test(document.querySelector('.nb .nbview[data-view="git"] #gitHint')?.textContent || ''),
                           null, { timeout: 20000 });
const NB = '.nb .nbview[data-view="git"]';
ok(new RegExp(`${st.files.length} changes not committed`).test(await page.$eval(`${NB} #gitHint`, e => e.textContent)),
   'the head row says the branch, the uncommitted count and the branches');
ok(await page.$eval(`${NB}`, e => e.querySelectorAll('.gfile').length) === st.files.length,
   'Changes lists each uncommitted file as a fold');
await page.click(`${NB} .gfile[data-path="a.txt"] summary`);
await page.waitForSelector(`${NB} .gfile[data-path="a.txt"] pre.diff`, { timeout: 10000 });
ok(await page.$eval(`${NB} .gfile[data-path="a.txt"] pre.diff`, e => /three/.test(e.textContent)
     && !!e.querySelector('.d-add')),
   '...and opening one shows its diff, additions marked');
const graph = await page.$eval(`${NB} .gitgraph`, g => ({
  rows: g.querySelectorAll('.grow[data-sha]').length, nodes: g.querySelectorAll('circle').length,
  edges: g.querySelectorAll('path').length, lanes: parseInt(getComputedStyle(g).getPropertyValue('--glanes')) }));
ok(graph.rows >= 4 && graph.nodes === graph.rows && graph.edges >= graph.rows - 1 && graph.lanes >= 2,
   `History is a graph: a node per commit, edges to parents, and a second lane for the branch (${JSON.stringify(graph)})`);
await page.click(`${NB} .grow[data-sha="${merge.sha}"]`);
await page.waitForSelector(`${NB} #gitDetail .gcommit`, { timeout: 10000 });
ok(await page.$eval(`${NB} #gitDetail`, e => /Merge feature/.test(e.textContent) && /merge/.test(e.textContent)),
   'picking a commit opens its detail under the list');
await page.click(`${NB} .grow[data-sha="${feat.sha}"]`);
await page.waitForFunction(sel => /Feature work/.test(document.querySelector(sel)?.textContent || ''),
                           `${NB} #gitDetail`, { timeout: 10000 });
ok(await page.$eval(`${NB} #gitDetail`, e => !!e.querySelector('pre.diff .d-add')),
   '...with its diff, and picking another swaps it');
ok(await page.$eval(`${NB}`, e => [...e.querySelectorAll('.gbranch')].some(r => /claude\/tabmade/.test(r.textContent) && /tabmade's session/.test(r.textContent))
     && [...e.querySelectorAll('.gbranch')].some(r => /here/.test(r.textContent))),
   'Branches marks the one the tree is on and whose session a branch is');
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
  const origin = `${DIR}/beta-origin.git`;
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
  ok(held.status === 409 && /Claude session is running/.test(held.error),
     "Switch is refused while the owner's session stands in the directory, naming it");
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
  // to do. Into the branch the tree is ON — nothing switches for you.
  {
    // Put back exactly, at the end: the assertions after this one read the
    // fixture's own branches and the content of its files, and a merge that
    // landed somebody else's commits on main would move both.
    const was = git('rev-parse', 'HEAD').trim();
    git('checkout', '-q', '-b', 'ready'); writeFileSync(`${B}/r.txt`, 'r\n');
    git('add', 'r.txt'); git('commit', '-q', '-m', 'Ready work');
    git('checkout', '-q', main);
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

  // Whose: a session's token cannot press these — it has bb git.
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
  await page.evaluate(() => fetch('/api/lock', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'beta', locked: true }) }));
  ok((await act('fetch')).status === 403, 'a locked project takes no action');
  await page.evaluate(() => fetch('/api/lock', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'beta', locked: false }) }));

  // ...and the view offers them: the network bar, the commit form at the
  // top of Changes, Switch and Delete on a branch, Revert on a commit.
  writeFileSync(`${B}/a.txt`, 'one\ntwo\nfour\n');
  await page.evaluate(() => getNotebook('beta').view('git'));
  await refreshUntil(page, () => !!document.querySelector('.nb .nbview[data-view="git"] #gitCommit'), { timeout: 20000 });
  const view = await page.$eval('.nb .nbview[data-view="git"]', v => ({
    net: !v.querySelector('#gitNet').hidden, push: !v.querySelector('[data-gitact="push"]').disabled,
    commitBar: !!v.querySelector('.gcommitbar[data-add] #gitMsg'),
    discard: !!v.querySelector('[data-gitdiscard="a.txt"]'),
    sw: v.querySelectorAll('[data-gitswitch]').length, del: v.querySelectorAll('[data-gitdelete]').length,
    newBranch: !!v.querySelector('.gbranchbar[data-add] #gitNewBranch') }));
  ok(view.net && view.push && view.commitBar && view.discard && view.sw >= 1 && view.del >= 1 && view.newBranch,
     `the view offers the network bar, the commit form, Discard, Switch, Delete and New branch (${JSON.stringify(view)})`);
  await page.fill('.nb .nbview[data-view="git"] #gitMsg', 'From the view');
  await page.click('.nb .nbview[data-view="git"] #gitCommit');
  await refreshUntil(page, () => /From the view/.test(document.querySelector('.nb .nbview[data-view="git"] .gitgraph')?.textContent || ''), { timeout: 20000 });
  ok(git('log', '-1', '--format=%s') === 'From the view', 'Commit from the view commits, and the graph shows it');
  await page.click('.nb .nbview[data-view="git"] .grow[data-sha]');
  await page.waitForSelector('.nb .nbview[data-view="git"] #gitDetail [data-gitrevert]', { timeout: 10000 });
  ok(true, "a picked commit's detail carries Revert and Branch here");
}

// ---- step 3: the policy, and Send to Claude --------------------------------
// What a session may send to the remote is the project's to say, on the Git
// view, and the controller's to enforce where the push runs — the relay. A
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
  const origin = `${DIR}/beta-origin.git`;
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
  await post('/api/prefs', { project: 'beta', gitpol: { push: 'allow', main: 'allow' } });
  ok((await relay(['git', 'push', 'origin', main])).code === 0, `...and ${main} too once allowed`);
  await post('/api/prefs', { project: 'beta', gitpol: { push: 'allow', main: 'deny' } });

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

  // ...and the view carries them.
  writeFileSync(`${B}/a.txt`, 'one\ntwo\nsix\n');
  await page.evaluate(() => getNotebook('beta').view('git'));
  await refreshUntil(page, () => !!document.querySelector('.nb .nbview[data-view="git"] [data-gitaskfile]'), { timeout: 20000 });
  // The second row: the first is still the pick from above, and a click on
  // the picked row puts it away.
  await page.click('.nb .nbview[data-view="git"] .grow[data-sha]:nth-child(2)');
  await page.waitForSelector('.nb .nbview[data-view="git"] #gitDetail [data-gitaskcommit]', { timeout: 10000 });
  const v = await page.$eval('.nb .nbview[data-view="git"]', el => ({
    file: !!el.querySelector('[data-gitaskfile]'), commit: !!el.querySelector('[data-gitaskcommit]'),
    branch: el.querySelectorAll('[data-gitaskbranch]').length,
    pol: el.querySelectorAll('[data-gitpol]').length, apply: el.querySelector('#gitPolApply')?.disabled }));
  ok(v.file && v.commit && v.branch >= 1 && v.pol === 2 && v.apply === true,
     `the view offers Send to Claude on a change, a commit and a branch, and the policy with its Apply asleep (${JSON.stringify(v)})`);
  // The policy is a section shut by default: open it to reach the pickers.
  await page.evaluate(() => { const d = document.querySelector('.nb .nbview[data-view="git"] details[data-sect="git:policy"]'); if (d && !d.open) d.open = true; });
  await page.waitForSelector('.nb .nbview[data-view="git"] [data-gitpol="push"]', { state: 'visible', timeout: 10000 });
  await page.selectOption('.nb .nbview[data-view="git"] [data-gitpol="push"]', 'deny');
  ok(await page.$eval('.nb .nbview[data-view="git"] #gitPolApply', b => !b.disabled),
     '...picking a policy wakes Apply and saves nothing yet');
  await page.selectOption('.nb .nbview[data-view="git"] [data-gitpol="push"]', 'allow');
  execFileSync('git', ['-C', B, 'checkout', '-q', '--', 'a.txt']);
}

// ---- the strip on a phone -------------------------------------------------
// Seven views do not fit 393px in one row: the strip wraps, and every tab
// stays on screen rather than the last two hiding behind an edge.
await page.setViewportSize({ width: 393, height: 851 });
await page.evaluate(() => setView('terminal'));
await page.waitForFunction(() => document.querySelector('.nb .nbtabs')?.getBoundingClientRect().width > 0);
const strip = await page.$eval('.nb .nbtabs', el => {
  const bs = [...el.querySelectorAll('button')].map(b => b.getBoundingClientRect());
  const box = el.getBoundingClientRect();
  return { n: bs.length, rows: new Set(bs.map(b => Math.round(b.top))).size,
           inside: bs.every(b => b.left >= box.left - 1 && b.right <= box.right + 1),
           over: el.scrollWidth - el.clientWidth };
});
ok(strip.n === 7 && strip.rows >= 2 && strip.inside && strip.over <= 0,
   `on a phone the strip wraps into rows and every tab is on screen (${JSON.stringify(strip)})`);

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
