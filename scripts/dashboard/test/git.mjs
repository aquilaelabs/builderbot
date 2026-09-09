// The notebook's Git view (roadmap R36, step 1): the repository read out —
// what is changed and not committed, the history as a graph, one commit's
// detail and diff, and the branches with whose worktree sits on which.
// Real git on the fixture repos, read by the checkout's server; nothing
// here writes through the dashboard, because this step has no actions.
import { launch, newPage, ok, done, ready, refreshUntil, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { writeFileSync, mkdirSync } from 'node:fs';

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
