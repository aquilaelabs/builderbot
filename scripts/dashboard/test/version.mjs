// One version identity per project, and who is allowed to move it.
//
// No browser: version.py has no UI yet, and the part worth protecting is the
// policy gate — a session must not be able to bump past what the operator
// allowed, and a bump must not sweep unrelated work into its commit. Both are
// reachable through `bb version`, which is the same module the notebook will
// call, so testing the CLI tests the thing.
import { launch, newPage, ready, ok, done, DIR, URL as DURL } from './lib.mjs';
import { mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// The checkout's bb, not the image's: the running image predates this
// subcommand, which is exactly the case this repo's own CLAUDE.md warns about.
const BB = fileURLToPath(new URL('../../bb', import.meta.url));
const WS = `${DIR}/ws`;
const PROJ = 'versioned';
const ROOT = `${WS}/${PROJ}`;

const env = {
  ...process.env,
  WORKSPACE: WS,
  DASHBOARD_STATE: `${DIR}/state`,
  // A committing test must not depend on the box's git identity being set.
  GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 't@example.invalid',
  GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 't@example.invalid',
};
const git = (...a) => execFileSync('git', ['-C', ROOT, ...a], { env }).toString().trim();
const bb = (...a) => {
  try {
    return { out: execFileSync('bash', [BB, 'version', ...a],
                               { cwd: ROOT, env }).toString().trim(), code: 0 };
  } catch (e) {
    return { out: ((e.stdout || '') + (e.stderr || '')).toString().trim(),
             code: e.status };
  }
};

// A project with three commits and a target of 0.4.0. The ordinal is the
// commit count, so it is knowable rather than guessed at.
rmSync(ROOT, { recursive: true, force: true });
mkdirSync(ROOT, { recursive: true });
execFileSync('git', ['-C', ROOT, 'init', '-q', '.'], { env });
writeFileSync(`${ROOT}/a.txt`, 'one');
git('add', '-A'); git('commit', '-qm', 'one');
writeFileSync(`${ROOT}/VERSION`, '0.4.0\n');
git('add', '-A'); git('commit', '-qm', 'target');
writeFileSync(`${ROOT}/b.txt`, 'two');
git('add', '-A'); git('commit', '-qm', 'two');
const sha = git('rev-parse', '--short=7', 'HEAD');

// ---- the renderings ------------------------------------------------------
// One input, several forms, because the formats genuinely disagree: Android
// needs an integer, a manifest needs dot-separated digits, PEP 440 wants its
// own spelling. A scheme that emitted one string would break on the first
// real artifact.
ok(bb('--semver').out === `0.4.0-dev.3+${sha}`,
   'semver is target, ordinal and commit');
ok(bb('--code').out === '3', 'the Android versionCode is the commit count');
ok(bb('--quad').out === '0.4.0.3', 'the four-integer form is target plus ordinal');
ok(bb('--win').out === bb('--quad').out,
   '--win is the same string: a VERSIONINFO resource and a manifest agree');
// Windows Installer ignores the fourth field when deciding what is an
// upgrade, so the ordinal has to move into a field it actually reads.
ok(bb('--msi').out === '0.4.3', 'the MSI form puts the ordinal in a read field');
ok(bb('--pep440').out === `0.4.0.dev3+${sha}`, 'PEP 440 has its own spelling');
ok(!bb('--file').out.includes('+'), 'the filename form carries no + to lose in a URL');

// An artifact built from uncommitted work must not wear the name of a build
// the sha can reproduce.
writeFileSync(`${ROOT}/scratch.txt`, 'uncommitted');
ok(bb('--file').out.endsWith('-dirty'),
   'a dirty tree marks the filename form');
ok(bb('--semver').out.endsWith('.dirty'), '...and the semver form');
rmSync(`${ROOT}/scratch.txt`);

// ---- who may move it -----------------------------------------------------
// The default is the strongest: a version is a claim about the project, so
// the operator opts into delegating it rather than out of it.
let r = bb('bump', 'patch');
ok(r.code !== 0 && /locked/.test(r.out),
   'locked by default — a session cannot bump at all');
ok(readFileSync(`${ROOT}/VERSION`, 'utf8').trim() === '0.4.0',
   '...and a refused bump leaves the file alone');
ok(/locked/.test(bb('policy').out),
   'a session can read the limit it is held to');

// The operator sets it; there is no CLI verb that does, deliberately.
const setPolicyFor = (proj, v) => {
  const py = fileURLToPath(new URL('../version.py', import.meta.url));
  execFileSync('python3', ['-c', `
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location('v', ${JSON.stringify(py)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(workspace=${JSON.stringify(WS)}, state=${JSON.stringify(`${DIR}/state`)},
            write_json=lambda p, o: open(str(p), 'w').write(json.dumps(o)))
print(m.set_policy(${JSON.stringify(proj)}, ${JSON.stringify(v)}))`], { env });
};
setPolicyFor(PROJ, 'minor');
r = bb('bump', 'major');
ok(r.code !== 0 && /not major/.test(r.out),
   'a policy of minor still keeps major with the operator');

// ---- the bump commits one path -------------------------------------------
// An uncommitted VERSION rides along in whatever a session commits next,
// which is how a version bump ends up inside a commit about something else.
writeFileSync(`${ROOT}/a.txt`, 'edited, and nothing to do with the version');
writeFileSync(`${ROOT}/c.txt`, 'staged elsewhere');
git('add', 'c.txt');
r = bb('bump', 'minor');
ok(r.code === 0 && /0\.4\.0 -> 0\.5\.0/.test(r.out), 'a permitted bump moves the target');
ok(git('show', '--stat', '--format=', 'HEAD').includes('VERSION')
   && !git('show', '--stat', '--format=', 'HEAD').includes('a.txt'),
   '...committing that one path and no other');
ok(/^Set version to 0\.5\.0 \(session\)$/m.test(git('log', '-1', '--format=%s')),
   '...with a message saying a session moved it, not the operator');
ok(git('status', '--porcelain').includes('a.txt'),
   '...and unrelated work is still uncommitted');

// VERSION already staged for something else would be swept into the bump's
// commit by a partial commit, under a message about a version bump.
writeFileSync(`${ROOT}/VERSION`, '9.9.9\n');
git('add', 'VERSION');
r = bb('bump', 'patch');
ok(r.code !== 0 && /already staged/.test(r.out),
   'a VERSION staged for another commit is refused, not quietly taken');
git('reset', '-q', 'HEAD', 'VERSION'); git('checkout', '-q', '--', 'VERSION');

// The unstaged twin is worse: an operator hand edit sitting uncommitted
// would be absorbed into the bump's commit, and the log would then say
// "(session)" over a change the operator made. The log being trustworthy
// about who moved the version is the whole safety story here.
writeFileSync(`${ROOT}/VERSION`, '0.9.0\n');
r = bb('bump', 'patch');
ok(r.code !== 0 && /uncommitted changes/.test(r.out),
   'an uncommitted hand edit to VERSION blocks a bump instead of being swept');
ok(readFileSync(`${ROOT}/VERSION`, 'utf8').trim() === '0.9.0',
   '...and the hand edit survives untouched');
git('checkout', '-q', '--', 'VERSION');

// A VERSION created by hand and never committed is still bumpable: a partial
// commit only knows tracked paths, so without the add this wrote the file
// and then failed, leaving it half-mutated.
const FRESH = `${WS}/fresh-version`;
rmSync(FRESH, { recursive: true, force: true });
mkdirSync(FRESH, { recursive: true });
execFileSync('git', ['-C', FRESH, 'init', '-q', '.'], { env });
writeFileSync(`${FRESH}/f`, 'x');
execFileSync('git', ['-C', FRESH, 'add', '-A'], { env });
execFileSync('git', ['-C', FRESH, 'commit', '-qm', 'init'], { env });
writeFileSync(`${FRESH}/VERSION`, '0.1.0\n');
setPolicyFor('fresh-version', 'open');
let rf;
try {
  rf = { out: execFileSync('bash', [BB, 'version', 'bump', 'patch'],
                           { cwd: FRESH, env }).toString(), code: 0 };
} catch (e) { rf = { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; }
ok(rf.code === 0 && /0\.1\.0 -> 0\.1\.1/.test(rf.out),
   'a never-committed VERSION can still be bumped and committed');
rmSync(FRESH, { recursive: true, force: true });

// ---- degrading honestly --------------------------------------------------
// A malformed file must not hand back a git-describe string that could end up
// baked into an artifact filename.
writeFileSync(`${ROOT}/VERSION`, 'v0.5\n');
r = bb('--file');
ok(r.code !== 0 && /MAJOR\.MINOR\.PATCH/.test(r.out),
   'a malformed VERSION is reported, not guessed around');
git('checkout', '-q', '--', 'VERSION');

// A project that has not adopted this still answers — the point is that every
// project can be asked, not that every project has opted in.
const BARE = `${WS}/unversioned`;
rmSync(BARE, { recursive: true, force: true });
mkdirSync(BARE, { recursive: true });
execFileSync('git', ['-C', BARE, 'init', '-q', '.'], { env });
writeFileSync(`${BARE}/f`, 'x');
execFileSync('git', ['-C', BARE, 'add', '-A'], { env });
execFileSync('git', ['-C', BARE, 'commit', '-qm', 'init'], { env });
const bare = (...a) => {
  try {
    return { out: execFileSync('bash', [BB, 'version', ...a],
                               { cwd: BARE, env }).toString().trim(), code: 0 };
  } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; }
};
ok(bare('--code').out === '1',
   'a project with no VERSION file still has an ordinal — it is pure git');
ok(bare('--msi').code !== 0,
   '...but a format that cannot be produced without one refuses');
ok(/no VERSION file/.test(bare().out), '...and says how to opt in');

rmSync(ROOT, { recursive: true, force: true });
rmSync(BARE, { recursive: true, force: true });

// ---- a repo that ships two products --------------------------------------
// One number cannot state two maturities: an extension at 2.1 beside a new
// app at 0.3. So a directory with its own VERSION file is a component, and
// its ordinal counts only the commits that touched it — otherwise a shipped
// extension appears to change every time the app beside it is edited.
const M = `${WS}/two-products`;
rmSync(M, { recursive: true, force: true });
mkdirSync(`${M}/extension`, { recursive: true });
mkdirSync(`${M}/app`, { recursive: true });
execFileSync('git', ['-C', M, 'init', '-q', '.'], { env });
writeFileSync(`${M}/VERSION`, '0.4.0\n');
writeFileSync(`${M}/extension/VERSION`, '2.1.0\n');
writeFileSync(`${M}/app/main.kt`, 'a');
writeFileSync(`${M}/extension/manifest.json`, '{}');
execFileSync('git', ['-C', M, 'add', '-A'], { env });
execFileSync('git', ['-C', M, 'commit', '-qm', 'both'], { env });
for (const i of [1, 2, 3]) {          // three commits touching only the app
  writeFileSync(`${M}/app/main.kt`, `a${i}`);
  execFileSync('git', ['-C', M, 'add', '-A'], { env });
  execFileSync('git', ['-C', M, 'commit', '-qm', `app ${i}`], { env });
}
const mb = (...a) => {
  try {
    return { out: execFileSync('bash', [BB, 'version', ...a],
                               { cwd: M, env }).toString().trim(), code: 0 };
  } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; }
};
ok(mb('--code').out === '4' && mb('--for', 'extension', '--code').out === '1',
   "a component's ordinal counts only the commits that touched it");
ok(mb('--for', 'extension', '--semver').out.startsWith('2.1.0-dev.1+'),
   '...so an untouched product stops moving when its neighbour is edited');
ok(mb('--semver').out.startsWith('0.4.0-dev.4+'),
   '...while the project keeps its own count');
ok(/two-products\/extension\s+2\.1\.0/.test(mb('--list').out)
   && /two-products\s+0\.4\.0/.test(mb('--list').out),
   '--list shows every version the repo carries');
// `comp` reaches this from a browser, so it must not read arbitrary files.
ok(mb('--for', '../../..', '--code').code !== 0 && mb('--for', 'nope', '--code').code !== 0,
   'a component outside the project is refused, not resolved');
// Bumping one must leave the other alone — that is the entire point.
setPolicyFor('two-products', 'open');
ok(mb('--for', 'extension', 'bump', 'minor').out.includes('2.1.0 -> 2.2.0'),
   'a component bumps on its own');
ok(readFileSync(`${M}/VERSION`, 'utf8').trim() === '0.4.0',
   "...leaving the project's own target untouched");
ok(execFileSync('git', ['-C', M, 'show', '--stat', '--format=', 'HEAD'], { env })
     .toString().includes('extension/VERSION'),
   '...committing the component file, not the root one');
ok(/^Set extension version to 2\.2\.0 \(session\)$/m.test(
     execFileSync('git', ['-C', M, 'log', '-1', '--format=%s'], { env }).toString()),
   '...with a message naming which one moved');
rmSync(M, { recursive: true, force: true });

// ---- the same module, in the Artifacts tab head --------------------------
// The display answers "what is this at" and needs no decision. The buttons
// answer "what next", which is the rare half — and the evidence beside them
// is the point, because by bump time nobody remembers what three weeks of
// prompting contained.
// alpha is a git repo in the fixtures but has no commits, so give it the
// history a version needs. beta gets a commit and no VERSION file — a repo
// with history that never adopted the scheme, which is the case the block has
// to degrade on rather than break. (A repo with NO commits is a third state,
// and it reports that instead: there is nothing to version yet.)
const B = `${WS}/beta`;
writeFileSync(`${B}/readme.txt`, 'beta');
execFileSync('git', ['-C', B, 'add', '-A'], { env });
execFileSync('git', ['-C', B, 'commit', '-qm', 'init'], { env });
const A = `${WS}/alpha`;
writeFileSync(`${A}/a.txt`, 'one');
execFileSync('git', ['-C', A, 'add', '-A'], { env });
execFileSync('git', ['-C', A, 'commit', '-qm', 'one'], { env });
writeFileSync(`${A}/VERSION`, '0.4.0\n');
execFileSync('git', ['-C', A, 'add', '-A'], { env });
execFileSync('git', ['-C', A, 'commit', '-qm', 'set version'], { env });
writeFileSync(`${A}/b.txt`, 'two');
execFileSync('git', ['-C', A, 'add', '-A'], { env });
execFileSync('git', ['-C', A, 'commit', '-qm', 'two'], { env });

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(DURL);
await ready(page);
await page.click(`#projects .row:has(.name:text-is("alpha")) [data-m]`);
await page.waitForSelector('#todoList, .nb', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForSelector('#verBox .verln', { timeout: 20000 });

const rows = () => page.$$eval('#verBox:visible .verln',
  ls => Object.fromEntries(ls.map(l => [l.children[0]?.textContent?.trim(),
                                        l.children[1]?.textContent?.trim()])));
const boxText = () => page.$eval('#verBox:visible', e => e.textContent.replace(/\s+/g, ' '));
let r0 = await rows();
ok(r0['building towards'] === '0.4.0',
   'the tab says what the project is building towards');
ok(/^0\.4\.0-dev\.3\+[0-9a-f]{7}$/.test(r0['a build now'] || ''),
   '...and what a build right now would be called');
ok(/since 0\.4\.0: 1 commit\b/.test(await boxText()),
   '...with the commits since the target last moved, as the case for a bump');

// Buttons, not a text field: a malformed version can never reach a manifest.
const labels = await page.$$eval('#verBox:visible [data-verbump]', bs => bs.map(b => b.textContent.trim()));
ok(labels.some(l => /Patch → 0\.4\.1/.test(l)) && labels.some(l => /Minor → 0\.5\.0/.test(l))
   && labels.some(l => /Major → 1\.0\.0/.test(l)),
   'each button previews the value it would set');

// The operator's bump is allowed regardless of the policy — the policy is
// about sessions. It should also commit, so the tree is not left dirty.
// newPage auto-accepts dialogs and records them, so the confirm is checked
// rather than merely dismissed: a bump is a commit, and should be asked about.
await page.click('#verBox:visible [data-verbump="minor"]');
await page.waitForFunction(() => {
  const l = document.querySelector('.nb:not([hidden]) #verBox .verln')
            || document.querySelector('#verBox .verln');
  return l && l.children[1]?.textContent?.trim() === '0.5.0';
}, { timeout: 20000 });
ok((await rows())['building towards'] === '0.5.0',
   'the operator can bump even while the policy is locked to them');
ok(page.dialogs.some(d => /0\.5\.0/.test(d) && /commits/i.test(d)),
   '...having been asked first, and told it commits');
ok(execFileSync('git', ['-C', A, 'log', '-1', '--format=%s'], { env }).toString().trim()
     === 'Set version to 0.5.0',
   '...and the commit says the operator moved it, with no "(session)" mark');
ok(!execFileSync('git', ['-C', A, 'status', '--porcelain'], { env }).toString().includes('VERSION'),
   '...leaving no dirty VERSION behind');

// The policy control is the answer to "when should this be incremented" for
// a session: the operator decides how much of the decision to delegate.
await page.selectOption('#verPolicy:visible', 'minor');
await page.waitForFunction(async () => {
  const r = await fetch('/api/version?project=alpha');
  return (await r.json()).policy === 'minor';
}, { timeout: 20000 });
const polAfter = execFileSync('bash', [BB, 'version', 'policy'], { cwd: A, env }).toString();
ok(/minor/.test(polAfter),
   'the policy set in the tab is the one bb version reports to a session');

// Every project has this tab, not only the ones that opted in, so a project
// with no VERSION file has to say how to opt in rather than render a broken
// block or a version it invented.
const noVer = await page.evaluate(async () => {
  const r = await fetch('/api/version?project=beta');
  return await r.json();
});
ok(noVer.target === null && noVer.forms.quad === null,
   'a project with no VERSION file reports no target');
ok(noVer.next.patch === null,
   '...and offers no next value to bump to, rather than inventing 0.0.1');

await page.click(`#projects .row:has(.name:text-is("beta")) [data-m]`);
await page.waitForSelector('.nbtabs [data-v="artifacts"]:visible', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForSelector('#verBox:visible .verln', { timeout: 20000 });
const fallback = (await page.$eval('#verBox:visible', e => e.textContent)).replace(/\s+/g, ' ');
ok(/Add a VERSION file/.test(fallback),
   '...and its tab says how to opt in');
ok((await page.$$('#verBox:visible [data-verbump]')).length === 0,
   '...offering no bump buttons for a version that does not exist');

ok((await page.errors).length === 0, 'no console errors from the version block');

// fresh() removes stray projects but does not reach inside a fixture, so the
// commits and the VERSION file this planted in alpha and beta have to go —
// otherwise every later file runs against projects this one changed.
for (const d of [A, B]) rmSync(`${d}/.git`, { recursive: true, force: true });
rmSync(`${A}/VERSION`, { force: true });
rmSync(`${A}/a.txt`, { force: true });
rmSync(`${A}/b.txt`, { force: true });
rmSync(`${B}/readme.txt`, { force: true });
execFileSync('git', ['-C', A, 'init', '-q', '.'], { env });
execFileSync('git', ['-C', B, 'init', '-q', '.'], { env });
execFileSync('git', ['-C', A, 'remote', 'add', 'origin',
                     'git@github.com:owner/alpha.git'], { env });
await done(browser);
