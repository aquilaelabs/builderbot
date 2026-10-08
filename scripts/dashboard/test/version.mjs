// One version identity per project, and who is allowed to move it.
//
// No browser: version.py has no UI yet, and the part worth protecting is the
// policy gate: a session must not be able to bump past what the operator
// allowed, and a bump must not sweep unrelated work into its commit. Both are
// reachable through `bb version`, which is the same module the notebook will
// call, so testing the CLI tests the thing.
import { launch, newPage, ready, ok, done, sleep, SLOW, tmuxCapture, DIR, URL as DURL, refreshUntil, saveDialog, takeOn, openFold, registerProject } from './lib.mjs';
import { mkdirSync, writeFileSync, readFileSync, rmSync, existsSync, chmodSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

// The checkout's bb, not the image's: the running image predates this
// subcommand, which is exactly the case this repo's own CLAUDE.md warns about.
const BB = fileURLToPath(new URL('../../bb', import.meta.url));
const REPO = fileURLToPath(new URL('../../../', import.meta.url));
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
   'locked by default: a session cannot bump at all');
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
// bb version set: straight to a later version in one commit, asked of the
// policy as the largest part it moves (report #48: 0.1.0 to 0.5.0 took four
// minor bumps or the operator).
r = bb('set', '1.0.0');
ok(r.code !== 0 && /not major/.test(r.out), `set is held to the policy by the part it moves: 1.0.0 is a major (${r.out.trim().slice(0, 80)})`);
r = bb('set', '0.3.0');
ok(r.code !== 0 && /not after/.test(r.out), '...and only moves forward');
r = bb('set', '0.7.0');
ok(r.code === 0 && readFileSync(`${ROOT}/VERSION`, 'utf8').trim() === '0.7.0' && /0\.4\.0 -> 0\.7\.0 +\(minor/.test(r.out),
   `a minor jump lands in one step, as one commit (${r.out.trim().slice(0, 80)})`);
r = bb('unbump');
ok(r.code === 0 && readFileSync(`${ROOT}/VERSION`, 'utf8').trim() === '0.4.0', '...and unbump takes it back as it takes a bump back');

// ---- the release: the second gesture, and the outward-facing one -----------
// A bump decides the number and closes the changelog under it. The tag says
// it HAPPENED, and until it exists a build reads X.Y.Z-dev.<n>, which sorts
// before X.Y.Z. That is the half that was missing: nothing cut the tag, so
// the two ideas of "released" never met.
//
// Its own repository, because a tag is repo-wide state and the shared fixture
// is read by everything after this.
{
  const R = `${WS}/relproj`;
  rmSync(R, { recursive: true, force: true });
  mkdirSync(R, { recursive: true });
  execFileSync('git', ['-C', R, 'init', '-q', '.'], { env });
  writeFileSync(`${R}/f`, 'x');
  writeFileSync(`${R}/VERSION`, '1.2.0\n');
  execFileSync('git', ['-C', R, 'add', '-A'], { env });
  execFileSync('git', ['-C', R, 'commit', '-qm', 'first'], { env });
  const py = fileURLToPath(new URL('../version.py', import.meta.url));
  const relOf = (extra = {}) => JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('v', ${JSON.stringify(py)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(workspace=${JSON.stringify(WS)}, state=${JSON.stringify(`${DIR}/state`)},
            write_json=lambda p, o: open(str(p), 'w').write(json.dumps(o)))
print(json.dumps(m.release('relproj', **json.loads(${
    JSON.stringify(JSON.stringify(extra))}))))`], { env }).toString().trim().split('\n').pop());
  const rb = (...a) => { try {
      return { out: execFileSync('bash', [BB, 'version', ...a], { cwd: R, env }).toString(), code: 0 };
    } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; } };
  {
    const before = rb('--file').out.trim();
    ok(/^1\.2\.0-dev\.\d+/.test(before),
       `before the release a build says it is heading for the number, not at it (${before})`);
  }
  // No remote in the fixture: push is asked for and the answer says what
  // happened rather than pretending. The tag is local either way.
  let rel = relOf({ push: false });
  ok(rel.ok && rel.tag === 'v1.2.0',
     `Release tags the commit with the name parts() looks for (${rel.tag})`);
  const shown = JSON.parse(rb('--json').out);
  ok(shown.released === true && shown.tag === 'v1.2.0' && shown.forms.semver === '1.2.0',
     `...and the build of that commit is the bare number (${shown.forms.semver})`);
  rel = relOf({ push: false });
  ok(!rel.ok && /already exists/.test(rel.error || ''),
     '...and a tag that exists is not moved from here, whatever the reason');
  writeFileSync(`${R}/f`, 'edited and not committed');
  writeFileSync(`${R}/VERSION`, '1.3.0\n');
  rel = relOf({ push: false });
  ok(!rel.ok && /uncommitted changes/.test(rel.error || ''),
     '...and a dirty tree is refused: a tag marks a commit, not what is beside it');
  rmSync(R, { recursive: true, force: true });
}

// ---- the commit that ships is not always the one you are standing on -------
// Work lands through a pull request, so what CI builds and the box runs is
// the MERGE commit on the default branch, while the checkout stays on the
// branch that was merged. Releasing there tags a commit no image was ever
// built from, and leaves the build that did ship reading -dev forever, which
// is what would have happened to 0.5.0, measured (B94).
//
// A real bare remote rather than a stub: the whole question is what
// origin/HEAD points at and whether HEAD is behind it, and a fake answer to
// that would be testing the mock.
{
  const P = `${WS}/shipproj`;
  const REMOTE = `${DIR}/shipproj.git`;
  rmSync(P, { recursive: true, force: true });
  rmSync(REMOTE, { recursive: true, force: true });
  execFileSync('git', ['init', '-q', '--bare', REMOTE], { env });
  mkdirSync(P, { recursive: true });
  execFileSync('git', ['-C', P, 'init', '-q', '-b', 'main', '.'], { env });
  writeFileSync(`${P}/VERSION`, '2.0.0\n');
  writeFileSync(`${P}/f`, 'one');
  execFileSync('git', ['-C', P, 'add', '-A'], { env });
  execFileSync('git', ['-C', P, 'commit', '-qm', 'one'], { env });
  execFileSync('git', ['-C', P, 'remote', 'add', 'origin', REMOTE], { env });
  execFileSync('git', ['-C', P, 'push', '-q', '-u', 'origin', 'main'], { env });
  const head = () => execFileSync('git', ['-C', P, 'rev-parse', '--short=7', 'HEAD'],
                                  { encoding: 'utf8', env }).trim();
  const behindAt = head();
  // main moves on, the way a merged pull request moves it, and this checkout
  // is left standing on the commit before it.
  writeFileSync(`${P}/f`, 'two');
  execFileSync('git', ['-C', P, 'add', '-A'], { env });
  execFileSync('git', ['-C', P, 'commit', '-qm', 'two'], { env });
  execFileSync('git', ['-C', P, 'push', '-q', 'origin', 'main'], { env });
  const tipAt = head();
  execFileSync('git', ['-C', P, 'reset', '--hard', '-q', behindAt], { env });

  const py2 = fileURLToPath(new URL('../version.py', import.meta.url));
  const shipRel = () => JSON.parse(execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('v', ${JSON.stringify(py2)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(workspace=${JSON.stringify(WS)}, state=${JSON.stringify(`${DIR}/state`)},
            write_json=lambda p, o: open(str(p), 'w').write(json.dumps(o)))
print(json.dumps(m.release('shipproj', push=False)))`], { env })
    .toString().trim().split('\n').pop());

  let r = shipRel();
  ok(!r.ok && new RegExp(behindAt).test(r.error || '') && new RegExp(tipAt).test(r.error || ''),
     `a release on a commit the default branch has moved past is refused, naming both (${
       (r.error || 'no error').slice(0, 76)})`);
  ok(/check out main and pull/i.test(r.error || ''),
     '...and says what to do about it rather than only that it will not');
  ok(execFileSync('git', ['-C', P, 'tag'], { encoding: 'utf8', env }).trim() === '',
     '...having made no tag at all: the refusal is the whole of what happened');

  // On the commit that actually ships, it goes through. The guard is about
  // being BEHIND, not about being on a branch with a name somebody likes.
  execFileSync('git', ['-C', P, 'reset', '--hard', '-q', tipAt], { env });
  r = shipRel();
  ok(r.ok && r.tag === 'v2.0.0',
     `...and on the commit the branch is actually at, the release goes through (${
       r.tag || r.error})`);
  rmSync(P, { recursive: true, force: true });
  rmSync(REMOTE, { recursive: true, force: true });
}

// ---- start: the first version, and nothing after ---------------------------
// Creating a version and moving one are different decisions (the first has
// no claim to overwrite), and until this policy existed the only way to let a
// session write the first VERSION was to hand it the bumping too.
{
  const S = `${WS}/startpol`;
  rmSync(S, { recursive: true, force: true });
  mkdirSync(S, { recursive: true });
  execFileSync('git', ['-C', S, 'init', '-q', '.'], { env });
  writeFileSync(`${S}/f`, 'x');
  execFileSync('git', ['-C', S, 'add', '-A'], { env });
  execFileSync('git', ['-C', S, 'commit', '-qm', 'first'], { env });
  const sb = (...a) => { try {
      return { out: execFileSync('bash', [BB, 'version', ...a], { cwd: S, env }).toString(), code: 0 };
    } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; } };
  setPolicyFor('startpol', 'locked');
  let t = sb('init', '0.1.0');
  ok(t.code !== 0 && /locked to the operator/.test(t.out) && !existsSync(`${S}/VERSION`),
     'locked refuses a session the first version, and says where to change that');
  setPolicyFor('startpol', 'start');
  ok(/start/.test(sb('policy').out) && /first version/.test(sb('policy').out),
     'start tells a session what it may do, rather than reading as the operator only');
  t = sb('init', '0.1.0');
  ok(t.code === 0 && readFileSync(`${S}/VERSION`, 'utf8').trim() === '0.1.0',
     '...and a session may give the project its first version');
  t = sb('bump', 'patch');
  ok(t.code !== 0 && /first version and no more/.test(t.out)
     && readFileSync(`${S}/VERSION`, 'utf8').trim() === '0.1.0',
     '...and may not move it afterwards, which is the whole point of the policy');
  rmSync(S, { recursive: true, force: true });
}

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

// The changelog does not wait for a VERSION to exist: entries logged before
// the first version describe the work that BECOMES it, so init dates them as
// its section. Left unreleased they would ride into the next bump and be
// labeled as changes since a release they are part of.
const Y = `${WS}/young`;
rmSync(Y, { recursive: true, force: true });
mkdirSync(Y, { recursive: true });
execFileSync('git', ['-C', Y, 'init', '-q', '.'], { env });
writeFileSync(`${Y}/f`, 'x');
execFileSync('git', ['-C', Y, 'add', '-A'], { env });
execFileSync('git', ['-C', Y, 'commit', '-qm', 'init'], { env });
const yb = (...a) => {
  try {
    return { out: execFileSync('bash', [BB, ...a], { cwd: Y, env }).toString(), code: 0 };
  } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; }
};
ok(yb('changelog', 'add', 'Worked before any version existed', '--cat', 'Added').code === 0,
   'a change can be logged before the project has a VERSION at all');
// An entry goes under a category, and the tool is where a session learns
// which there are: twenty-one of twenty-two unreleased entries in this
// repository's own changelog had none, because nothing anywhere said what the
// categories were or when each applied. Refused with the rules rather than
// filed in a heap above the headings.
{
  const none = yb('changelog', 'add', 'filed nowhere');
  ok(none.code !== 0 && /--cat NAME, one of/.test(none.out) && /Fixed\s+it was wrong, and now it is right/.test(none.out)
     && /a house rule is where a project says so/.test(none.out),
     'an entry with no category is refused, and the refusal is the six names with when each applies');
  ok(!/filed nowhere/.test(yb('changelog', 'unreleased').out), '...and nothing was written');
  ok(yb('changelog', 'add', 'A wrong thing put right', '--cat', 'bugfix').code === 0
     && /### Fixed/.test(readFileSync(`${Y}/CHANGELOG.md`, 'utf8')),
     'a name that means one of the six is spelled the one way: bugfix files under Fixed');
  const own = yb('changelog', 'add', 'Move your config before updating', '--cat', 'Upgrading');
  const body = readFileSync(`${Y}/CHANGELOG.md`, 'utf8');
  ok(own.code === 0 && /### Upgrading/.test(body) && body.indexOf('### Added') < body.indexOf('### Fixed')
     && body.indexOf('### Fixed') < body.indexOf('### Upgrading'),
     "a project's own category is kept as typed and goes on the end, while the six keep their usual order among themselves");
  // The verb stamps HEAD, and an entry that names HEAD itself was written
  // with the hash twice (B336): a stamp typed on the end is the entry's own.
  const head = execFileSync('git', ['-C', Y, 'rev-parse', '--short=7', 'HEAD'], { env }).toString().trim();
  yb('changelog', 'add', `Named its own commit (${head})`, '--cat', 'Fixed');
  const once = readFileSync(`${Y}/CHANGELOG.md`, 'utf8').split('\n').find(l => l.includes('Named its own commit'));
  ok(once === `- Named its own commit (${head})`,
     `an entry that already ends with the commit it is stamped with carries it once (${once})`);
}
setPolicyFor('young', 'open');
yb('version', 'init', '0.1.0');
const born = yb('changelog').out;
ok(/## 0\.1\.0: \d{4}-\d{2}-\d{2}/.test(born) && !/## Unreleased/.test(born),
   '...and init dates the accrued entries as the first version\u2019s section');
rmSync(Y, { recursive: true, force: true });

// A project that has not adopted this still answers: the point is that every
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
   'a project with no VERSION file still has an ordinal: it is pure git');
// Asked from one of the project's worktrees, the answer is that tree's: a
// session building in its worktree was handed the main checkout's commit as
// its package name and shipped nothing rather than a file named after code
// it did not hold (24 Sep).
{
  const WT = `${WS}/.worktrees/unversioned/u_0badf00d`;
  mkdirSync(`${WS}/.worktrees/unversioned`, { recursive: true });
  execFileSync('git', ['-C', BARE, 'worktree', 'add', '-q', '-b', 'claude/side', WT], { env });
  writeFileSync(`${WT}/g`, 'y');
  execFileSync('git', ['-C', WT, 'add', '-A'], { env });
  execFileSync('git', ['-C', WT, 'commit', '-qm', 'side work'], { env });
  const inWt = (...a) => execFileSync('bash', [BB, 'version', ...a], { cwd: WT, env }).toString().trim();
  ok(inWt('--code') === '2' && bare('--code').out === '1',
     `bb version asked from a worktree answers for that tree (${inWt('--code')} there, ${bare('--code').out} in the project directory)`);
  ok(inWt('--file') !== bare('--file').out,
     '...so a package built there is named after the commit it holds');
  execFileSync('git', ['-C', BARE, 'worktree', 'remove', '--force', WT], { env });
}
ok(bare('--msi').code !== 0,
   '...but a format that cannot be produced without one refuses');
ok(/no VERSION file/.test(bare().out), '...and says how to opt in');

rmSync(ROOT, { recursive: true, force: true });
rmSync(BARE, { recursive: true, force: true });

// ---- a repo that ships two products --------------------------------------
// One number cannot state two maturities: an extension at 2.1 beside a new
// app at 0.3. So a directory with its own VERSION file is a component, and
// its ordinal counts only the commits that touched it; otherwise a shipped
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
   '...so an untouched product stops moving when its neighbor is edited');
ok(mb('--semver').out.startsWith('0.4.0-dev.4+'),
   '...while the project keeps its own count');
ok(/two-products\/extension\s+2\.1\.0/.test(mb('--list').out)
   && /two-products\s+0\.4\.0/.test(mb('--list').out),
   '--list shows every version the repo carries');
// `comp` reaches this from a browser, so it must not read arbitrary files.
ok(mb('--for', '../../..', '--code').code !== 0 && mb('--for', 'nope', '--code').code !== 0,
   'a component outside the project is refused, not resolved');
// Bumping one must leave the other alone; that is the entire point.
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
// ---- the changelog: accrued by sessions, dated by the bump ---------------
// The record and the number are decoupled on purpose: entries land under
// Unreleased as work is done, and a bump, whoever presses it, only renames
// that section to the new version with the date. The operator keeping the
// number costs the record nothing.
const cl = (...a) => {
  try {
    return { out: execFileSync('bash', [BB, 'changelog', ...a],
                               { cwd: M, env }).toString(), code: 0 };
  } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; }
};
ok(/no CHANGELOG\.md here yet/.test(cl().out),
   'a project with no changelog says so, and how to start one');
ok(cl('add', 'Pairing works across screen switches', '--cat', 'Changed').code === 0,
   'a session can log a user-facing change');
cl('add', 'The app no longer forgets its settings', '--cat', 'Changed', '--for', 'extension');
ok(/Pairing works/.test(cl().out) && !/forgets its settings/.test(cl().out),
   "an entry lands in the changelog it was logged to, not the project's");
ok(/forgets its settings \([0-9a-f]{7}\)/.test(cl('--for', 'extension').out),
   '...stamped with the commit it describes');
ok(cl('add', '', '--cat', 'Changed').code !== 0, 'an empty entry is refused');

// A change that tweaks something already logged this cycle corrects the
// line rather than adding a second one about the same thing: the reader
// should meet each change once, and the honest record is one line that is
// right. Positional numbers, because the section is short-lived by design.
cl('add', 'Pairing shows the code larger', '--cat', 'Changed');
// A second commit before the edit, so the line has two to name.
execFileSync('git', ['-C', M, 'commit', '--allow-empty', '-q', '-m', 'Another pass over pairing'], { env });
const listed = cl('unreleased').out;
ok(/^\s*1\s+Pairing works across screen switches\s+\([0-9a-f]{7}\)/m.test(listed)
   && /^\s*2\s+Pairing shows the code larger/m.test(listed),
   'bb changelog unreleased numbers the entries waiting for a bump');
ok(cl('edit', '2', 'Pairing shows the code larger, and reads it aloud').code === 0,
   'a session can reword an unreleased entry instead of logging the same thing twice');
const reworded = cl().out;
ok(/- Pairing shows the code larger, and reads it aloud \([0-9a-f]{7}, [0-9a-f]{7}\)/.test(reworded)
   && !/code larger \(/.test(reworded) && /- Pairing works across/.test(reworded),
   '...replacing the line in place, naming the commit it had and the one that reworded it, the others untouched');
const missing = cl('edit', '9', 'Nothing here');
ok(missing.code !== 0 && /no unreleased entry 9/.test(missing.out),
   'an entry that is not there is refused, naming how many there are');

// ---- the section is the operator's to shape ------------------------------
// A cycle's worth of entries is never right the first time: a thing gets
// built across commits that each looked like their own story, and a change
// gets undone by a later one. Merge, split and drop, with the commits
// following the words rather than the other way round.
//
// On entries of its own, added and taken away again, so the lines the bump
// below is about are the ones the cases above left.
{
  const rows = () => (cl('unreleased').out.match(/^\s*\d+\s+.*$/gm) || []);
  const shasOf = line => (line.match(/[0-9a-f]{7}/g) || []);
  const find = (list, word) => list.find(l => l.includes(word)) || '';
  const before = rows().length;

  execFileSync('git', ['-C', M, 'commit', '--allow-empty', '-q', '-m', 'half one'], { env });
  cl('add', 'MERGEME the first half', '--cat', 'Changed');
  execFileSync('git', ['-C', M, 'commit', '--allow-empty', '-q', '-m', 'half two'], { env });
  cl('add', 'MERGEME the second half', '--cat', 'Changed');
  let list = rows();
  const halves = list.filter(l => /MERGEME/.test(l));
  const want = new Set(halves.flatMap(shasOf));
  ok(halves.length === 2 && want.size === 2,
     `two entries, each naming its own commit (${want.size} between them)`);

  const ns = halves.map(l => l.trim().split(/\s/)[0]);
  ok(cl('merge', ...ns, 'MERGEONE both halves, said once').code === 0,
     'two entries fold into one line');
  list = rows();
  const one = find(list, 'MERGEONE');
  ok(list.filter(l => /MERGEME/.test(l)).length === 0
     && new Set(shasOf(one)).size === want.size
     && shasOf(one).every(sh => want.has(sh)),
     `...carrying every commit the two of them named, and no more (${shasOf(one).join(', ')})`);
  ok(cl('merge', '1', 'Only one').code !== 0 && cl('merge', '1', '2').code !== 0,
     '...and refuses one entry, or a merge with no line of its own to replace them');

  const at = find(rows(), 'MERGEONE').trim().split(/\s/)[0];
  ok(cl('split', at).code === 0, 'and one splits back into a line per commit');
  list = rows();
  const parts = list.filter(l => /MERGEONE/.test(l));
  ok(parts.length === want.size && parts.every(l => shasOf(l).length === 1),
     `...one for each, all carrying the text, ready to be reworded (${parts.length})`);
  ok(cl('split', parts[0].trim().split(/\s/)[0]).code !== 0,
     '...and a line with a single commit refuses: there is nothing to split it along');

  ok(cl('rm', parts[0].trim().split(/\s/)[0]).code === 0,
     'and one that stopped being true is dropped');
  ok(rows().filter(l => /MERGEONE/.test(l)).length === parts.length - 1,
     '...leaving the others where they were');
  ok(cl('rm', '99').code !== 0, '...while a number nobody has is refused');

  // ...and the order is nobody's to derive. It used to be sorted by commit
  // date on every write, which quietly moved a line under the reader every
  // time an old entry was reworded; an edit stamps it with a newer commit.
  // Now the file's order IS the order, and a reword leaves the line where
  // somebody put it.
  {
    const first = rows()[0].replace(/^\s*\d+\s+/, '').replace(/\s*\([0-9a-f, ]+\)$/, '');
    execFileSync('git', ['-C', M, 'commit', '--allow-empty', '-q',
                         '-m', 'a much later commit'], { env });
    cl('edit', '1', first + ', reworded much later');
    ok(rows()[0].includes('reworded much later')
       && shasOf(rows()[0]).length > 1,
       'rewording the first entry with a newer commit leaves it first');
  }

  for (const l of rows().filter(x => /MERGEONE/.test(x)))
    cl('rm', l.trim().split(/\s/)[0]);
  ok(rows().length === before,
     `...and the section is back to what the cases above left (${before})`);
}

// ---- categories: the shape a changelog reader already knows ---------------
// A cycle's lines are written one at a time by whoever did the work; what a
// reader meets at a release wants grouping. `### Name` subsections, because
// that is the Keep a Changelog convention anybody who has read one knows,
// and it makes a recategorised entry a moved line in the diff rather than a
// rewritten file.
//
// A session files an entry under a category. It does not get to decide where
// the category SITS: a new one lands at the end, and the arrangement is the
// operator's, on the editor the browser cases below drive.
{
  const rows = () => (cl('unreleased').out.match(/^\s*\d+\s+.*$/gm) || []);
  const numOf = word => (rows().find(l => l.includes(word)) || '').trim().split(/\s/)[0];
  const file = () => readFileSync(`${M}/CHANGELOG.md`, 'utf8');
  const before = rows().length;

  ok(cl('add', 'CATME a fix', '--cat', 'Fixed').code === 0
     && cl('add', 'CATME an addition', '--cat', 'Added').code === 0,
     'a session files an entry under a category');
  ok(/### Fixed\n\n- CATME a fix \([0-9a-f]{7}\)/.test(file())
     && /### Added\n\n- CATME an addition \([0-9a-f]{7}\)/.test(file()),
     '...written as `### Name` subsections, the entry still stamped with its commit');
  // Fixed was filed FIRST and Added still sits above it: the six keep their
  // usual order among themselves, which is a convention and nobody's
  // arrangement. (It used to be "a new category on the end", which filed a
  // changelog in the order a session happened to work in.)
  ok(file().indexOf('### Added') < file().indexOf('### Fixed'),
     '...the six in their usual order, whichever was filed first');
  // A line from before categories were asked for. A session can no longer
  // make one, and files written before this still carry them, so the fixture
  // writes one the way an old file has it: above every heading.
  writeFileSync(`${M}/CHANGELOG.md`, file().replace('## Unreleased\n', '## Unreleased\n\n- LOOSE from before categories were asked for\n'));
  const listed = cl('unreleased').out;
  const nums = rows().map(l => Number(l.trim().split(/\s/)[0]));
  ok(/^\s+\(no category\)$/m.test(listed) && /^\s+Fixed$/m.test(listed)
     && file().indexOf('- LOOSE') < file().indexOf('### ')
     && nums.every((n, i) => n === i + 1),
     'the numbered list names each category, an uncategorised line above them all, and counts straight through');
  cl('rm', numOf('LOOSE'));

  // The limit is on what is being written, not on what the file holds
  // (B352): a line longer than it, there by hand, refused every add after
  // it in words that blamed the new line, and the verbs could not shorten
  // it either, since each of them writes the whole section.
  const long = 'LONGLINE ' + 'a line that ran on '.repeat(20);
  writeFileSync(`${M}/CHANGELOG.md`, file().replace('### Added\n\n', `### Added\n\n- ${long.trim()}\n`));
  ok(cl('add', 'SHORT beside a long one', '--cat', 'Fixed').code === 0 && /SHORT beside a long one/.test(file())
     && file().includes(long.trim()),
     'an entry is filed beside one already over the limit, which stays as it was');
  const over = cl('add', 'TOOLONG ' + 'and on '.repeat(60), '--cat', 'Fixed');
  ok(over.code !== 0 && /this one is \d+, and begins: TOOLONG/.test(over.out) && !/TOOLONG/.test(file()),
     '...a new one over it is refused, and the refusal says which entry and how long');
  ok(cl('edit', numOf('LONGLINE'), 'LONGLINE cut to size').code === 0 && !file().includes(long.trim()),
     '...and the long one is shortened through the verb');
  cl('rm', numOf('LONGLINE')); cl('rm', numOf('SHORT beside'));

  ok(cl('edit', numOf('CATME a fix'), 'CATME a fix, moved', '--cat', 'Added').code === 0,
     'an entry moves between categories with --cat');
  ok(/### Added\n\n- CATME an addition[^\n]*\n- CATME a fix, moved/.test(file()),
     '...filed at the end of it, which is where `add --cat` puts one');
  ok(!/### Fixed/.test(file()),
     '...and the category it emptied is gone, not left as a heading with nothing under it');

  // A session filing one entry must not drag a category to the front of
  // somebody's arrangement. The order used to come off the entries' running
  // order, so moving a category's FIRST line into a later category pulled
  // that category up above it.
  cl('add', 'CATME a later fix', '--cat', 'Fixed');
  ok(file().indexOf('### Added') < file().indexOf('### Fixed'),
     'a second category lands after the first, which is the arrangement to protect');
  cl('edit', numOf('CATME a fix, moved'), 'CATME a fix, moved again', '--cat', 'Fixed');
  ok(file().indexOf('### Added') < file().indexOf('### Fixed')
     && /### Fixed\n\n- CATME a later fix[^\n]*\n- CATME a fix, moved again/.test(file()),
     `...and moving its first line into the second leaves both categories where they were (${
       (file().match(/^### .*$/gm) || []).join(', ')})`);
  cl('rm', numOf('CATME a later fix'));
  cl('edit', numOf('CATME a fix, moved again'), 'CATME a fix, moved', '--cat', 'Added');

  // A move is not a change, and a pass over the wording is not one either.
  // An edit normally names the commit that made the change, which is the
  // whole point of the stamp, so a categorisation pass over a cycle's
  // entries would otherwise leave every line naming the commit that filed it,
  // which is a record of nothing.
  {
    const shasOf2 = word => ((rows().find(l => l.includes(word)) || '')
      .match(/[0-9a-f]{7}/g) || []);
    execFileSync('git', ['-C', M, 'commit', '--allow-empty', '-q',
                         '-m', 'unrelated to any entry'], { env });
    const had = shasOf2('CATME an addition');
    ok(cl('edit', numOf('CATME an addition'), '--cat', 'Added').code === 0
       && /CATME an addition/.test(file()),
       'an entry moves between categories without the words being retyped');
    ok(shasOf2('CATME an addition').join() === had.join(),
       `...and a move on its own claims no commit (${shasOf2('CATME an addition').join(', ')})`);
    ok(cl('edit', numOf('CATME an addition'), 'CATME an addition, said better',
          '--no-stamp').code === 0
       && shasOf2('CATME an addition, said better').join() === had.join(),
       '...and --no-stamp rewords a line without claiming a commit made it');
    ok(cl('edit', numOf('CATME an addition, said better'), 'CATME an addition').code === 0
       && shasOf2('CATME an addition').length === had.length + 1,
       '...while an ordinary reword still names the commit it was made with');
    ok(cl('edit', numOf('CATME an addition')).code !== 0,
       'an edit that neither rewords nor moves is refused, not treated as a blank line');
    // Which gives a session the one ordering gesture it has: re-filing a line
    // into the category it is already in sends it to the bottom of that
    // category, so a pass can put a cycle's entries in a deliberate order.
    ok(cl('edit', numOf('CATME a fix, moved'), '--cat', 'Added').code === 0
       && /- CATME an addition[^\n]*\n- CATME a fix, moved/.test(file()),
       're-filing a line into its own category sends it to the bottom of that category');
  }

  ok(cl('add', 'far too specific', '--cat', 'A'.repeat(41)).code !== 0
     && !/far too specific/.test(file()),
     'a category is a word or two: a longer one is refused and nothing is written');

  cl('rm', numOf('CATME an addition'));
  cl('rm', numOf('CATME a fix, moved'));
  ok(rows().length === before && !/^### (Added|Fixed)$/m.test(file()),
     `...and emptying a category takes its heading with it (${before} left)`);
}

// The bump dates the section, in the same commit that moves VERSION.
mb('bump', 'patch');
const rolled = cl().out;
ok(/## 2\.2\.1: \d{4}-\d{2}-\d{2}\n\n- Pairing works/.test(rolled)
   === false && /## 0\.4\.1: \d{4}-\d{2}-\d{2}/.test(rolled)
   && /- Pairing works/.test(rolled) && !/## Unreleased/.test(rolled),
   "the project's bump dates its Unreleased section");
ok(/## Unreleased/.test(cl('--for', 'extension').out),
   "...and leaves the extension's still accruing");
ok(/nothing unreleased/.test(cl('unreleased').out)
   && cl('edit', '1', 'Rewriting history').code !== 0 && !/Rewriting history/.test(cl().out),
   'a dated section is history: once bumped, the numbered list is empty and nothing is left to edit');
ok(execFileSync('git', ['-C', M, 'show', '--stat', '--format=', 'HEAD'], { env })
     .toString().includes('CHANGELOG.md'),
   '...with VERSION and CHANGELOG.md moving in one commit');

// A cycle with nothing logged writes no empty section.
mb('bump', 'patch');
ok(!/## 0\.4\.2/.test(cl().out),
   'a bump with nothing logged writes no empty section');
// And the next entry reopens Unreleased above the dated history.
cl('add', 'Something new after the release', '--cat', 'Changed');
const reopened = cl().out;
ok(reopened.indexOf('## Unreleased') !== -1
   && reopened.indexOf('## Unreleased') < reopened.indexOf('## 0.4.1'),
   'the next entry reopens Unreleased above the dated history');
// ---- set renumbers a version nobody released (report #49) ---------------
// 0.1.0, bumped to 0.2.0 (which dated every entry under 0.2.0), then set to
// 0.5.0 before anything was released: 0.2.0's notes are 0.5.0's. A tagged
// number keeps its section, and a plain bump keeps the one it leaves.
{
  const R = `${WS}/renumber`;
  rmSync(R, { recursive: true, force: true });
  mkdirSync(R, { recursive: true });
  execFileSync('git', ['-C', R, 'init', '-q', '.'], { env });
  writeFileSync(`${R}/VERSION`, '0.1.0\n');
  execFileSync('git', ['-C', R, 'add', '-A'], { env });
  execFileSync('git', ['-C', R, 'commit', '-qm', 'init'], { env });
  setPolicyFor('renumber', 'open');
  const rb = (...a) => { try {
      return { out: execFileSync('bash', [BB, ...a], { cwd: R, env }).toString(), code: 0 };
    } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; } };
  const file = () => readFileSync(`${R}/CHANGELOG.md`, 'utf8');
  rb('changelog', 'add', 'First feature', '--cat', 'Added');
  rb('version', 'bump', 'minor');
  ok(/## 0\.2\.0/.test(file()), 'a bump dates the section as ever');
  rb('changelog', 'add', 'Second feature', '--cat', 'Added');
  const set = rb('version', 'set', '0.5.0');
  const f = file();
  ok(set.code === 0 && !/## 0\.2\.0/.test(f) && /## 0\.5\.0: [\d-]+\n\n### Added\n\n- First feature[^\n]*\n- Second feature/.test(f),
     `set to 0.5.0 from an unreleased 0.2.0 dates 0.2.0's notes as 0.5.0's, with what came after (${JSON.stringify(f.slice(0, 400))})`);
  ok(/never released/.test(set.out), '...and says so');
  execFileSync('git', ['-C', R, 'tag', '-a', 'v0.5.0', '-m', 'r'], { env });
  rb('changelog', 'add', 'Third feature', '--cat', 'Added');
  rb('version', 'set', '0.6.0');
  ok(/## 0\.5\.0/.test(file()) && /## 0\.6\.0/.test(file()), 'a released number keeps its section when the version is set past it');
}

// ---- what a review pass caught, kept caught ------------------------------
// A project release tag must not stamp a component: the repo-wide vX.Y.Z
// says nothing about the extension, even when the numbers coincide.
execFileSync('git', ['-C', M, 'tag', '-a', 'v2.2.0', '-m', 'r'], { env });
// the root target is 0.4.x so the root stays -dev; the extension's target IS
// 2.2.0 now, and the trap is that this tag would have released it.
// ...and taken back the same way. A repo that ships two products bumps and
// unbumps each on its own: the operator asked whether the CLI could, and the
// answer has to keep being yes.
const repoBefore = mb('--semver').out;
ok(/2\.2\.0 -> 2\.1\.0/.test(mb('--for', 'extension', 'unbump').out)
   && mb('--for', 'extension').out.includes('2.1.0'),
   'a component is taken back on its own too');
const repoAfter = mb('--semver').out;
ok(repoAfter.startsWith(repoBefore.split('-')[0] + '-'),
   `...leaving the repository's own version alone (${repoBefore} then ${repoAfter})`);
ok(mb('--for', 'extension', 'bump', 'minor').out.includes('2.1.0 -> 2.2.0'),
   '...and forward again afterwards');
ok(/2\.2\.0-dev\./.test(mb('--for', 'extension', '--semver').out),
   "a project tag matching a component's number does not release the component");
execFileSync('git', ['-C', M, 'tag', '-a', 'extension-v2.2.0', '-m', 'r'], { env });
// startsWith, not equals: the flow above leaves an uncommitted changelog
// entry in the tree, so the released form honestly carries +dirty.
const relSem = mb('--for', 'extension', '--semver').out;
ok(relSem.startsWith('2.2.0') && !relSem.includes('-dev.'),
   "...its own extension-vX.Y.Z tag does");
// The pathspec is the resolved directory, not the caller's spelling.
ok(mb('--for', './extension', '--code').out === mb('--for', 'extension', '--code').out,
   'a sloppy --for spelling counts the same commits as the clean one');
// A component bump with no VERSION names the component and the sanctioned door.
const noVer2 = mb('--for', 'app', 'bump', 'patch');
ok(noVer2.code !== 0 && /two-products\/app has no VERSION/.test(noVer2.out)
   && /init 0\.1\.0 --for app/.test(noVer2.out),
   'a component bump without a VERSION points at init, not at hand-creation');
// A staged changelog edit refuses the bump before anything mutates.
writeFileSync(`${M}/CHANGELOG.md`,
  '# Changelog\n\n## Unreleased\n\n- pending entry (x)\n');
execFileSync('git', ['-C', M, 'add', 'CHANGELOG.md'], { env });
const swept = mb('bump', 'patch');
ok(swept.code !== 0 && /staged for another commit/.test(swept.out),
   'a staged changelog edit blocks the bump instead of being swept');
execFileSync('git', ['-C', M, 'reset', '-q', 'HEAD', 'CHANGELOG.md'], { env });
rmSync(`${M}/CHANGELOG.md`, { force: true });
// A VERSION two levels down is nobody's component, and cannot become one.
mkdirSync(`${M}/deep/lib`, { recursive: true });
writeFileSync(`${M}/deep/lib/VERSION`, '9.9.9\n');
ok(!/deep/.test(mb('--list').out),
   'a VERSION two levels down is not discovered as a component');
const deep = mb('init', '0.1.0', '--for', 'deep/lib');
ok(deep.code !== 0 && /one level under/.test(deep.out),
   '...and init refuses to create one there');
rmSync(M, { recursive: true, force: true });

// ---- taking a bump back, while it is still nobody's release --------------
// The code never reverts; the number returns and the changelog section the
// bump dated dissolves into Unreleased with whatever was logged after, so
// the next bump dates the whole group as one release.
const U = `${WS}/rethink`;
rmSync(U, { recursive: true, force: true });
mkdirSync(U, { recursive: true });
execFileSync('git', ['-C', U, 'init', '-q', '.'], { env });
writeFileSync(`${U}/f`, 'x');
execFileSync('git', ['-C', U, 'add', '-A'], { env });
execFileSync('git', ['-C', U, 'commit', '-qm', 'one'], { env });
setPolicyFor('rethink', 'open');
const ub = (...a) => {
  try {
    return { out: execFileSync('bash', [BB, ...a], { cwd: U, env }).toString(), code: 0 };
  } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; }
};
ub('version', 'init', '0.2.0');
ub('changelog', 'add', 'went into the bump', '--cat', 'Changed');
ub('version', 'bump', 'minor');
ub('changelog', 'add', 'logged after the bump', '--cat', 'Changed');
ok(/0\.3\.0 -> 0\.2\.0/.test(ub('version', 'unbump').out),
   'an unreleased bump can be taken back without touching the code');
const merged = ub('changelog').out;
ok(!/## 0\.3\.0/.test(merged)
   && merged.indexOf('went into the bump') < merged.indexOf('logged after the bump')
   && /## Unreleased/.test(merged),
   '...its section dissolves into Unreleased, oldest first');
ub('version', 'bump', 'minor');
const redone = ub('changelog').out;
ok(/## 0\.3\.0/.test(redone) && !/## Unreleased/.test(redone),
   '...and the next bump dates the whole group as one release');
// Released numbers are immutable: somebody may have installed one.
execFileSync('git', ['-C', U, 'tag', '-a', 'v0.3.0', '-m', 'r'], { env });
ok(/released/.test(ub('version', 'unbump').out),
   'a released version refuses to be taken back');
execFileSync('git', ['-C', U, 'tag', '-d', 'v0.3.0'], { env });
// An unbump of an unbump would walk UP while claiming to go back.
ub('version', 'unbump');
ok(/already returned/.test(ub('version', 'unbump').out),
   'a second unbump refuses instead of quietly re-bumping');

// The mechanical estimate that used to live here is gone. `bb version
// suggest` counted commits and read a manifest, and the judgment it produced
// was worth less than nothing once Ask Claude existed: a number handed to a
// session ANCHORS it, inviting it to justify 0.2.0 rather than read the code.
const goneVerb = ub('version', 'suggest');
ok(goneVerb.code !== 0, 'the mechanical estimate is gone, not merely unused');

rmSync(U, { recursive: true, force: true });

// ---- putting the question to the session ---------------------------------
// The estimate a function can make is a starting input, not the answer: a
// session can read the code and be argued with. The prompt has to carry the
// policy, because what it may do about the answer differs.
const AK = `${WS}/askme`;
rmSync(AK, { recursive: true, force: true });
mkdirSync(AK, { recursive: true });
execFileSync('git', ['-C', AK, 'init', '-q', '.'], { env });
writeFileSync(`${AK}/f`, 'x');
execFileSync('git', ['-C', AK, 'add', '-A'], { env });
execFileSync('git', ['-C', AK, 'commit', '-qm', 'one'], { env });
const askText = (proj, sessions) => {
  const py = fileURLToPath(new URL('../version.py', import.meta.url));
  return execFileSync('python3', ['-c', `
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location('v', ${JSON.stringify(py)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
sent = {}
m.configure(workspace=${JSON.stringify(WS)}, state=${JSON.stringify(`${DIR}/state`)},
            write_json=lambda p, o: open(str(p), 'w').write(json.dumps(o)),
            tell_fn=lambda s, t, live: (sent.update(t=t), {'sent': True})[1],
            tmux_name_fn=lambda n: n)
r = m.ask(${JSON.stringify(proj)}, ${JSON.stringify(sessions)})
print(json.dumps({'ok': r.get('ok'), 'text': r.get('text', '')}))`], { env }).toString();
};
setPolicyFor('askme', 'locked');
const lockedAsk = JSON.parse(askText('askme', ['claude-askme']));
ok(/what version should askme start at/.test(lockedAsk.text),
   'the ask names the thing it is asking about');
ok(/bb version policy/.test(lockedAsk.text),
   '...and points at the verb that answers, rather than restating the protocol');
ok(/propose a number you derived here and ask; do not apply one/.test(lockedAsk.text),
   '...saying plainly that this is a proposal, not an instruction');
// The length IS the contract. This is typed into a terminal a character at a
// time and the echo has to be seen before Enter can follow; the first cut ran
// to 704 characters and was left sitting in the input box unsent, which read
// to the operator as the button doing nothing. Keep it short.
ok(lockedAsk.text.length < 250,
   `...and stays short enough to type and land (${lockedAsk.text.length} chars)`);

// Once a version exists the question changes: not "what should this start at"
// but "is this still right".
writeFileSync(`${AK}/VERSION`, '0.4.0\n');
execFileSync('git', ['-C', AK, 'add', '-A'], { env });
execFileSync('git', ['-C', AK, 'commit', '-qm', 'v'], { env });
const holds = JSON.parse(askText('askme', ['claude-askme']));
ok(/is at 0\.4\.0: is that still right\?/.test(holds.text)
   && /propose and ask; do not apply/.test(holds.text),
   'with a version, the ask becomes "is this still right"');
ok(holds.text.length < 250,
   `...and that one is short too (${holds.text.length} chars)`);
rmSync(AK, { recursive: true, force: true });

// ---- the same module, in the Artifacts tab head --------------------------
// The display answers "what is this at" and needs no decision. The buttons
// answer "what next", which is the rare half, and the evidence beside them
// is the point, because by bump time nobody remembers what three weeks of
// prompting contained.
// alpha is a git repo in the fixtures but has no commits, so give it the
// history a version needs. beta gets a commit and no VERSION file: a repo
// with history that never adopted the scheme, which is the case the block has
// to degrade on rather than break. (A repo with NO commits is a third state,
// and it reports that instead: there is nothing to version yet.)
const B = `${WS}/beta`;
mkdirSync(`${B}/sub`, { recursive: true });
writeFileSync(`${B}/sub/thing.js`, '1');
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

// The notebook whose title names this project. Two open notebooks are two
// clones of one template, so every id inside exists twice, and neither
// :visible nor offsetParent separates them: both are laid out. The title is
// the only thing in the markup that tells them apart.
const nb = name => `.nb:has(#memTitle:text-is("Notebook: ${name}"))`;
let NB = nb('alpha');

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(DURL);
await ready(page);
await page.click(`#projects .row:has(.name:text-is("alpha")) [data-m]`);
await page.waitForSelector('#roadmapList, .nb', { timeout: 20000 });
await page.click(`${NB} .nbtabs [data-v="artifacts"]`);
// One section open at a time in a notebook (the operator, 5 Oct): Build is
// first, so Version is opened.
await page.waitForSelector(`${NB} [data-sect="artifacts:version"]`, { timeout: 20000 });
await openFold(page, `${NB} [data-sect="artifacts:version"]`);
await page.waitForSelector('#verBox .verln', { timeout: 20000 });

async function waitTarget(want, ms = 20000){
  const until = Date.now() + ms;
  for (;;) {
    const r = await rows().catch(() => ({}));
    if (r['building towards'] === want) return;
    if (Date.now() > until)
      throw new Error(`building towards never became ${want} (saw ${r['building towards']})`);
    await new Promise(r2 => setTimeout(r2, 200));
  }
}
const rows = () => page.$$eval(`${NB} #verBox .verln`,
  ls => Object.fromEntries(ls.map(l => [l.children[0]?.textContent?.trim(),
                                        l.children[1]?.textContent?.trim()])));
const boxText = () => page.$eval(`${NB} #verBox`, e => e.textContent.replace(/\s+/g, ' '));
let r0 = await rows();
ok(r0['building towards'] === '0.4.0',
   'the tab says what the project is building towards');
// Build and Version are sections of this tab, and a shut one still answers:
// the node on the first, the number on the second. They were three unnamed
// bands stacked, which on a phone is one scroll with nothing labeling it.
{
  const sects = await page.$$eval(`${NB} .nbview[data-view="artifacts"] .sect > summary`,
    ss => ss.map(s => [s.querySelector('.t')?.textContent,
                       s.querySelector('.sst')?.textContent]));
  ok(sects.some(([t]) => t === 'Build') && sects.some(([t]) => t === 'Version'),
     'the tab names what it is showing: Build and Version are sections');
  ok(sects.find(([t]) => t === 'Version')?.[1] === '0.4.0',
     '...and the version is the heading\'s status, so a shut one still answers');
}
// The SHAPE, and the ordinal against git rather than against a literal. The
// ordinal is the commit count, and alpha is the shared fixture: an earlier
// file in a full run commits into it, so a hardcoded 3 was right when this
// file ran alone and wrong when it ran after git.mjs (B85). What the
// assertion is actually about is that the line is the version, built from the
// target, the count and the sha.
{
  const n = execFileSync('git', ['-C', A, 'rev-list', '--count', 'HEAD'],
                         { encoding: 'utf8' }).trim();
  ok(new RegExp(`^0\\.4\\.0-dev\\.${n}\\+[0-9a-f]{7}$`).test(r0['a build now'] || ''),
     `...and what a build right now would be called (${r0['a build now']}, ordinal ${n})`);
}
ok(/since 0\.4\.0: 1 commit\b/.test(await boxText()),
   '...with the commits since the target last moved, as the case for a bump');

// Buttons, not a text field: a malformed version can never reach a manifest.
const labels = await page.$$eval(`${NB} #verBox [data-verbump]`, bs => bs.map(b => b.textContent.trim()));
ok(labels.some(l => /Patch → 0\.4\.1/.test(l)) && labels.some(l => /Minor → 0\.5\.0/.test(l))
   && labels.some(l => /Major → 1\.0\.0/.test(l)),
   'each button previews the value it would set');

// The operator's bump is allowed regardless of the policy: the policy is
// about sessions. And it STAGES: pressing Minor records the intent, git is
// untouched until the notebook's Save. A misclicked "Major → 1.0.0" must
// never be a commit before the finger has left the button.
await page.click(`${NB} #verBox [data-verbump="minor"]`);
await page.waitForFunction(sel => {
  const b = document.querySelectorAll(sel);
  return [...b].some(x => x.offsetParent && /staged: 0\.5\.0/.test(x.textContent));
}, `${NB} .vermark`.replace(NB, '.nb'), { timeout: 20000 }).catch(() => {});
ok(/staged: 0\.5\.0 on Save/.test(await page.$eval(`${NB} #verBox`, e => e.textContent)),
   'pressing a bump stages it, saying what Save will do');
ok(execFileSync('git', ['-C', A, 'show', 'HEAD:VERSION'], { env }).toString().trim()
     === '0.4.0',
   '...and git holds the old number until Save');
// Pressing the same part again clears the stage: the undialog misclick path.
await page.click(`${NB} #verBox [data-verbump="minor"]`);
ok(!/staged:/.test(await page.$eval(`${NB} #verBox`, e => e.textContent)),
   '...and pressing it again unstages, no dialog needed');
await page.click(`${NB} #verBox [data-verbump="minor"]`);
await page.click(`${NB} [data-ssave="artifacts:version"]`);
await waitTarget('0.5.0');
ok((await rows())['building towards'] === '0.5.0',
   'Save commits the staged bump: the operator can, whatever the policy');
ok(execFileSync('git', ['-C', A, 'log', '-1', '--format=%s'], { env }).toString().trim()
     === 'Set version to 0.5.0',
   '...and the commit says the operator moved it, with no "(session)" mark');
ok(!execFileSync('git', ['-C', A, 'status', '--porcelain'], { env }).toString().includes('VERSION'),
   '...leaving no dirty VERSION behind');

// The policy control is the answer to "when should this be incremented" for
// a session: the operator decides how much of the decision to delegate.
// Staged like a bump: the pick alone writes nothing, and the Version
// section's own Save is what commits it (docs/design-language.md, Settings).
await page.selectOption(`${NB} #verPolicy`, 'minor');
await page.waitForFunction(() => [...document.querySelectorAll('.nb #verBox .verpol')]
  .some(e => /staged: on Save/.test(e.textContent)), null, { timeout: 10000 });
ok((await page.evaluate(async () => (await (await fetch('/api/version?project=alpha')).json()).policy)) !== 'minor',
   'picking a policy stages it and writes nothing yet');
await page.click(`${NB} [data-ssave="artifacts:version"]`);
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
NB = nb('beta');

// Who may give it one is answerable BEFORE there is one. The picker used to
// be written only into the has-a-version branch, so the tab offered the
// setting exactly when it no longer mattered and withheld it when it did.
//
// Read without requiring visibility, and the view re-shown between tries:
// an earlier file can leave this notebook parked out of a pane, which is the
// same thing initWith below works around.
let polOpts = [];
for (let t = 0; t < 30 && !polOpts.length; t++){
  polOpts = await page.$$eval(`${NB} #verBox #verPolicy option`,
                              os => os.map(o => o.value)).catch(() => []);
  if (polOpts.length) break;
  await page.click(`#projects .row:has(.name:text-is("beta")) [data-m]`).catch(() => {});
  await page.click(`${NB} .nbtabs [data-v="artifacts"]`).catch(() => {});
  await sleep(300);
}
ok(polOpts.join(",") === "locked,start,patch,minor,open",
   `a project with no version still offers the policy, the one that delegates `
   + `the first version and nothing else included (${polOpts.join(", ") || "nothing"})`);

// The harness's tab state survives between test files, so an earlier file
// can leave this notebook parked out of a pane: the input then resolves but
// is never visible, and a plain fill waits its timeout out. Re-showing the
// notebook is the fix the operator would make by hand: click the project
// row (which goes to the existing tab) and the view strip again.
// Atomic on purpose: setting the field and pressing the button in two
// round trips leaves a gap a redraw can land in: the box re-renders when a
// revision key moves, the fresh input comes back holding its default, and
// the click then submits a value the test never typed.
async function initWith(val){
  for (let t = 0; t < 30; t++){
    const okc = await page.$eval(`${NB} #verBox`, (box, v) => {
      const f = box.querySelector(".vstart"), b = box.querySelector("[data-verinit]");
      if (!f || !b || !box.offsetParent) return false;
      f.value = v; b.click();
      return true;
    }, val).catch(() => false);
    if (okc) return;
    await page.click(`#projects .row:has(.name:text-is("beta")) [data-m]`).catch(() => {});
    await page.click(`${NB} .nbtabs [data-v="artifacts"]`).catch(() => {});
    await sleep(300);
  }
  throw new Error("the init control never became usable");
}
await page.waitForSelector(`${NB} .nbtabs [data-v="artifacts"]`, { timeout: 20000 });
await page.click(`${NB} .nbtabs [data-v="artifacts"]`);
await page.waitForSelector(`${NB} #verBox .verln`, { timeout: 20000 });
const fallback = (await page.$eval(`${NB} #verBox`, e => e.textContent)).replace(/\s+/g, ' ');
ok(/No version yet/.test(fallback) && /start at/.test(fallback),
   '...and its tab says so, offering a starting point rather than inventing one');
ok((await page.$$(`${NB} #verBox [data-verlog]`)).length === 1,
   '...while the changelog stays reachable: entries accrue before a version exists');
ok((await page.$$(`${NB} #verBox [data-verbump]`)).length === 0,
   '...offering no bump buttons for a version that does not exist');

// The file tools are denied on VERSION, so if the tab could not create the
// first one there would be no sanctioned path at all and the instruction
// would be to go and do it in a terminal. A guardrail with no way through is
// one people route around.
ok((await page.$$(`${NB} #verBox [data-verinit]`)).length === 1,
   '...but offering to create one, since nothing else can');
ok((await page.$$(`${NB} #verBox [data-verask]:not([data-verask="@fold"])`)).length === 1,
   '...and offering to put the question to the project\u2019s own session');
// Two products with different maturities is a state a fresh project can
// already be in (StreamLift proposed 0.2.0 for the app and 0.1.0 for its
// extension while neither file existed), so the component door has to be
// visible before the root version is, not only after.
ok(await page.$(`${NB} #verBox .veradd .vdir`) !== null,
   'the component fold is offered before the project has any version at all');

// A starting number is arbitrary (nothing can derive it), so it is the one
// value here that is typed. Which means it has to be checked.
await initWith('v1.2');
await page.waitForTimeout(400);
ok(!existsSync(`${B}/VERSION`), 'a malformed starting version is refused, not written');

await initWith('0.2.0');
await waitTarget('0.2.0');
ok(readFileSync(`${B}/VERSION`, 'utf8').trim() === '0.2.0',
   'the tab can give a project its first version');
const lastMsg = execFileSync('git', ['-C', B, 'log', '-1', '--format=%s'], { env }).toString().trim();
ok(lastMsg === 'Add VERSION at 0.2.0',
   `...committing it, with no "(session)" mark since the operator did it (got: ${lastMsg})`);
ok((await page.$$(`${NB} #verBox [data-verbump]`)).length === 3,
   '...and the bump buttons appear once there is something to bump');
ok((await page.$$(`${NB} #verBox [data-verask]:not([data-verask="@fold"])`)).length === 1,
   '...with Ask Claude still there: the question changes, the door stays');

// A component is created the same way, from what is actually on disk rather
// than a path typed from memory.
const dirs = await page.$$eval(`${NB} #verBox .vdir option`, os => os.map(o => o.textContent));
ok(dirs.includes('sub'), 'the component control offers directories that exist');
ok(!dirs.includes('.git'), '...and not the ones that are nobody\'s product');

// The changelog pane, on beta which has none: the message says how to start
// one rather than rendering an error, and the button toggles it away.
// NB is a Playwright selector (:has, :text-is), which the page's own
// querySelector cannot parse, so the polling stays on this side.
await page.click(`${NB} #verBox [data-verlog]`);
let paneText = "";
// Ten seconds of 200ms polls on a quiet box, and BB_TEST_SLOW's multiple of
// that on a busy one: this waits on a fetch the pane makes when it opens, and
// CI runs it beside everything else this machine does (bug #13).
for (let t = 0; t < 50 * SLOW; t++){
  paneText = await page.$eval(`${NB} .verlogpane`, e => e.textContent).catch(() => "");
  if (/no CHANGELOG\.md here yet/.test(paneText)) break;
  await sleep(200);
}
ok(/no CHANGELOG\.md yet/.test(paneText),
   'the changelog pane says how to opt in when there is no file');
// The flake this suite carried for weeks, as a rule instead. The pane used to
// live in #verBox and be MOVED into the sheet, so a repaint of that box while
// the sheet was open (a version poll, a commit, a dist change) put a second
// empty one back in the box, and "the changelog pane" was then whichever came
// first in the document. Repaint under it and count.
await page.evaluate(() => drawPanes());
await sleep(400);
const panes = await page.$$eval('.verlogpane', es => es.map(e => ({
  inSheet: !!e.closest('#sheetSlot'), text: e.textContent.slice(0, 40) })));
ok(panes.length === 1 && panes[0].inSheet && /no CHANGELOG/.test(panes[0].text),
   `...and a repaint under the open sheet leaves exactly one, in the sheet (${
     JSON.stringify(panes)})`);
// It reads in the same window a history does, and fills it: a document in a
// strip at the top of an empty screen is the shape this move was undoing.
// $eval, not evaluate: NB is a Playwright selector, and :text-is() is
// theirs, which querySelector has never heard of.
const clog = await page.$eval(`${NB} .verlogpane`, (pane) => {
  const slot = pane.closest('.sheetslot');
  return { inSheet: !!slot,
           tall: !!slot && pane.offsetHeight >= slot.clientHeight - 1,
           boxed: getComputedStyle(pane).borderTopWidth !== '0px' };
});
ok(clog.inSheet && clog.tall && !clog.boxed,
   '...filling the window it opens in, with no second box drawn inside it');

// ---- the editor: the arrangement is a gesture, not a file to hand-edit ----
// The pane used to be the file as text, which is right for reading and
// useless for what the section is actually for. A cycle's entries arrive one
// at a time from sessions, in the order the work happened; what a reader
// meets at a release wants categories, an order inside them, and words
// somebody chose. All of it here, over one Save.
//
// Unreleased only: everything below it is a release somebody may have read,
// and it renders as the text it is.
{
  const seed = ['# Changelog', '', '## Unreleased', '',
                '- a loose note (aaaaaaa)', '',
                '### Fixed', '',
                '- pairing works again (bbbbbbb)', '- another fix (ccccccc)', '',
                '### Added', '', '- a new tab (ddddddd)', '',
                '## 0.1.0 \u2014 2026-08-01', '', '- something older (eeeeeee)', ''];
  const CL = `${B}/CHANGELOG.md`;
  writeFileSync(CL, seed.join('\n'));
  await page.click(`${NB} #sheetClose`);
  await page.click(`${NB} #verBox [data-verlog]`);
  await page.waitForSelector(`${NB} .clog .clrow`, { timeout: 20000 * SLOW });

  // Read back as text/category/commit per row, which is the whole model: the
  // select carries where a line sits, the sha span carries what it names.
  // Every gesture redraws, so nothing here holds an element between calls.
  const shown = () => page.$$eval(`${NB} .clog .clrow`, rs => rs.map(r => ({
    text: r.querySelector('.cltext').value,
    cat: r.querySelector('.clcat').value,
    sha: r.querySelector('.clsha').textContent.trim() })));
  const cats = () => page.$$eval(`${NB} .clog .clname`, is => is.map(i => i.value));
  const shape = async () => (await shown()).map(r => `${r.text}:${r.cat}`).join('|');
  const at = async word =>
    (await shown()).findIndex(r => r.text.includes(word));
  // .clrow sits inside its category's .clgroup, so an nth-of-type over the
  // section would count per band. Index the handles instead.
  const press = async (i, sel) => (await page.$$(`${NB} .clog .clrow`))[i].$eval(
    sel, el => el.click());
  const settled = async want => {
    for (let n = 0; n < 50 * SLOW; n++){
      if (await shape() === want) return true;
      await sleep(100);
    }
    return false;
  };

  let rs = await shown();
  ok(rs.length === 4
     && rs.map(r => r.text).join('|') === 'a loose note|pairing works again|another fix|a new tab'
     && rs.map(r => r.cat).join('|') === '|Fixed|Fixed|Added'
     && rs[0].sha === 'aaaaaaa',
     `every unreleased line is a row, in the file's order, with its category and its commit (${
       JSON.stringify(rs)})`);
  ok((await cats()).join('|') === 'Fixed|Added',
     '...and each category is a band of its own, to rename and to move');
  const datedText = await page.$eval(`${NB} .clog`,
    e => (e.parentElement.querySelector('.verlogpane') || {}).textContent || '');
  ok(/0\.1\.0/.test(datedText) && /something older/.test(datedText),
     'the dated releases below it are the text they are: a release is not editable');

  // Down off the end of a category lands in the next one. Kept within the
  // group it would be a move that does nothing on the last row, which is not
  // what dragging a list looks like.
  await press(2, '[data-emv="down"]');
  ok(await settled('a loose note:|pairing works again:Fixed|another fix:Added|a new tab:Added'),
     `a line moved off the end of its category lands in the next one (${await shape()})`);

  // The other half of the arrangement: the band itself moves.
  await page.$$eval(`${NB} .clog .clgroup [data-cmv="up"]`, bs => bs[bs.length - 1].click());
  for (let n = 0; n < 50 * SLOW && (await cats()).join('|') !== 'Added|Fixed'; n++)
    await sleep(100);
  ok((await cats()).join('|') === 'Added|Fixed',
     `a category moves up and down the section on its own row (${(await cats()).join(', ')})`);

  // Rename: the entries under it follow, because the name IS where they sit.
  await page.$eval(`${NB} .clog .clname`, i => {
    i.value = 'Shipped'; i.dispatchEvent(new Event('change', { bubbles: true })); });
  for (let n = 0; n < 50 * SLOW && !(await cats()).includes('Shipped'); n++)
    await sleep(100);
  ok((await shown()).filter(r => r.cat === 'Shipped').length === 2,
     `renaming a category carries its entries with it (${(await cats()).join(', ')})`);

  // ...and a line moves between them from its own row, without dragging.
  const loose = await at('loose');
  await (await page.$$(`${NB} .clog .clrow`))[loose].$eval('.clcat', el => {
    el.value = 'Shipped'; el.dispatchEvent(new Event('change', { bubbles: true })); });
  for (let n = 0; n < 50 * SLOW; n++){
    if ((await shown()).every(r => r.cat)) break;
    await sleep(100);
  }
  ok((await shown()).find(r => r.text === 'a loose note')?.cat === 'Shipped',
     `an uncategorised line is filed from its own row (${await shape()})`);

  await press(await at('another fix'), '[data-erm]');
  for (let n = 0; n < 50 * SLOW && (await shown()).length !== 3; n++) await sleep(100);
  ok(!(await shown()).some(r => r.text === 'another fix'),
     `a line that stopped being true is dropped from the section (${await shape()})`);

  // Nothing has touched the file yet. The whole section goes at once, because
  // somebody moving three lines and renaming a category is not making five
  // edits, and half of that applied is a shape nobody asked for.
  ok(readFileSync(CL, 'utf8').includes('- another fix (ccccccc)'),
     '...with the file untouched until Save: the section is applied whole, or not at all');

  const arranged = await shape();
  await page.click(`${NB} .clog #clSave`);
  for (let n = 0; n < 100 * SLOW; n++){
    const s = await page.$eval(`${NB} #clState`, e => e.textContent).catch(() => '');
    if (/saved/.test(s)) break;
    await sleep(100);
  }
  const written = readFileSync(CL, 'utf8');
  ok(/## Unreleased\n\n### Shipped\n\n- a new tab \(ddddddd\)\n- a loose note \(aaaaaaa\)\n\n### Fixed\n\n- pairing works again \(bbbbbbb\)\n/
       .test(written),
     `Save writes the arrangement as \`### Name\` subsections (${
       JSON.stringify(written.split('## 0.1.0')[0].slice(0, 200))})`);
  ok(!/another fix/.test(written) && /aaaaaaa/.test(written) && /bbbbbbb/.test(written),
     '...dropping the line, and never the commits of the lines that stayed');
  ok(/## 0\.1\.0 \u2014 2026-08-01\n\n- something older \(eeeeeee\)/.test(written),
     '...leaving the dated history below it exactly as it was');
  // And the editor is still showing what the file now holds: it redraws from
  // the section the server answers with, not from the one it sent, so a
  // refusal or a tidy-up on the way in cannot leave the two disagreeing.
  ok(await shape() === arranged,
     `the editor redraws from what came back (${await shape()})`);
  const back = written.slice(0, written.indexOf('## 0.1.0'));
  const fromFile = back.split('\n').filter(l => l.startsWith('### ') || l.startsWith('- '))
    .reduce((acc, l) => l.startsWith('### ')
      ? (acc.cat = l.slice(4).trim(), acc)
      : (acc.out.push(l.slice(2).replace(/\s*\([0-9a-f, ]+\)$/, '') + ':' + acc.cat), acc),
      { cat: '', out: [] }).out.join('|');
  ok(fromFile === arranged,
     `...and the file holds that same arrangement (${fromFile} vs ${arranged})`);

  // Whose gesture this is. A session has add, edit, merge, split and rm, each
  // of which says what it is doing to one entry; handing it the whole section
  // would make "the arrangement is the operator's" a convention rather than a
  // rule. Asked from node rather than from the page: a deliberate 403 is a
  // failed resource in the console, and the clean-console assertion below is
  // worth more than the convenience.
  const stok = execFileSync('python3', ['-c', `
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("users", "${REPO}/scripts/dashboard/users.py")
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
def wj(p, d):
    tmp = str(p) + ".tmp"; open(tmp, "w").write(json.dumps(d, indent=2)); os.replace(tmp, p)
u.configure(state="${DIR}/state", write_json=wj)
print(u.mint_session("beta"))`], { encoding: 'utf8' }).trim();
  const res = await fetch(`${DURL}/api/changelog`, { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${stok}` },
    body: JSON.stringify({ project: 'beta', groups: [] }) });
  const refused = await res.json();
  ok(res.status === 403 && /bb changelog add/.test(refused.error || '')
     && /merge/.test(refused.error || ''),
     `a session is refused the whole section, and told the verbs it does have (${
       (refused.error || '').slice(0, 64)})`);
  ok(readFileSync(CL, 'utf8') === written,
     '...with the file it was refused unchanged');
  // On a phone this was a wall: every entry a one-line box showing thirty of
  // its three hundred characters, and a category band drawn the same size and
  // shape as an entry, so the arrangement could not be read at all. The words
  // are a proseline now (wrapping, as tall as they need), and the band is a
  // heading. Measured, because the rule that broke it is one stylesheet line
  // away: `.modal textarea` is white-space:pre at the same specificity, and
  // this editor opens inside a sheet, which is a modal.
  //
  // Last in this block, and nothing is saved after it: it types into a box to
  // have something long enough to wrap.
  {
    await page.setViewportSize({ width: 393, height: 851 });
    await page.evaluate(() => setView('terminal'));
    await sleep(600);
    const long = 'A minor version moves the compatibility window, so every '
      + "project bound to a node is held until that node's agent is updated, "
      + "and the sessions running on it end when the bump lands";
    await page.$eval(`${NB} .clog .clrow textarea.cltext`, (ta, v) => {
      ta.value = v; ta.dispatchEvent(new Event('input', { bubbles: true }));
    }, long);
    await sleep(300);
    const shape = await page.$eval(`${NB} .clog`, el => {
      const ta = el.querySelector('.clrow textarea.cltext');
      const head = el.querySelector('.clhead input.clname');
      const cs = getComputedStyle(ta), hs = head && getComputedStyle(head);
      return { wraps: cs.whiteSpace === 'pre-wrap',
               scrolls: ta.scrollHeight > ta.clientHeight + 2,
               lines: Math.round(ta.getBoundingClientRect().height
                                 / (parseFloat(cs.lineHeight) || 16)),
               inside: ta.getBoundingClientRect().width <= el.getBoundingClientRect().width,
               headBold: hs ? Number(hs.fontWeight) >= 600 : null,
               // Not the border WIDTH: it keeps one, transparent, so the
               // box does not jump when you put a cursor in it. What makes
               // it read as a heading is that neither the border nor the
               // fill is painted until then.
               headPlain: hs ? /,\s*0\)$|transparent/.test(hs.borderTopColor)
                               && /,\s*0\)$|transparent/.test(hs.backgroundColor) : null };
    });
    ok(shape.wraps && !shape.scrolls && shape.lines > 3 && shape.inside,
       `on a phone an entry shows all of itself rather than thirty characters of it (${
         shape.lines} lines, scrolling inside: ${shape.scrolls})`);
    ok(shape.headBold === true && shape.headPlain === true,
       `a category reads as a heading, not as another field the size of an entry (${
         JSON.stringify({bold: shape.headBold, unpainted: shape.headPlain})})`);
    await page.setViewportSize({ width: 1280, height: 1000 });
    await page.evaluate(() => setView('terminal'));
    await sleep(400);
  }
  await page.click(`${NB} #sheetClose`);
}

// The real delivery path, against the harness's own tmux server: alpha has a
// claude-alpha session, so this exercises notify.tell rather than a stub.
// A preference set for the project changes nothing about this path: it is a
// launch flag, so the session is already on it and the ask is only the ask.
await page.evaluate(async () => {
  await fetch('/api/prefs', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({project: 'alpha', model: 'haiku', effort: 'low'})});
});
const askSent = await page.evaluate(async () => {
  const r = await fetch('/api/version', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({project: 'alpha', action: 'ask'})});
  return await r.json();
});
ok(askSent.ok && askSent.sent,
   'the question reaches a running session for real, not just in principle');
const askPane = tmuxCapture('claude-alpha');
ok(askPane.includes("Artifacts tab"),
   '...and the prompt is what actually lands in that pane');
ok(!/\/model/.test(askPane) && !/\/effort/.test(askPane),
   '...with no slash command ahead of it, whatever the project is set to');
await page.evaluate(async () => {
  await fetch('/api/prefs', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({project: 'alpha', model: '', effort: ''})});
});

// Checked before the deliberate refusal below: that one answers 400, which
// the browser logs as a failed resource. An expected refusal is not a defect,
// and folding it into this assertion would blunt the thing it exists to catch.
const cleanSoFar = [...(await page.errors)];
ok(cleanSoFar.length === 0, `no console errors from the version block${cleanSoFar.length ? ', got: ' + JSON.stringify(cleanSoFar.slice(0, 3)) : ''}`);


// ---- a repo's own stamps travel with the number ----------------------------
// A project may carry its version somewhere else, and a bump that moves one
// and not the other commits a lie. BuilderBot is the case: its minor IS the
// compatibility window, written again in the agent, and 0.5.0 only came out
// consistent because a person moved both by hand before pressing Bump (B91).
//
// The hook is generic (an executable tools/version-stamp, run from the repo
// root with the new version and the part), so this exercises the mechanism on
// a repository of its own rather than on BuilderBot's two files, and rather
// than on the shared fixture, whose ordinal everything above depends on.
{
  const S = `${WS}/stampproj`;
  rmSync(S, { recursive: true, force: true });
  mkdirSync(`${S}/tools`, { recursive: true });
  execFileSync('git', ['-C', S, 'init', '-q', '.'], { env });
  writeFileSync(`${S}/VERSION`, '0.4.0\n');
  writeFileSync(`${S}/tools/version-stamp`,
    '#!/usr/bin/env bash\nset -e\n[ "$2" = minor ] || exit 0\n'
    + 'printf "window %s\\n" "${1%.*}" > stamped.txt\necho moved\n');
  chmodSync(`${S}/tools/version-stamp`, 0o755);
  execFileSync('git', ['-C', S, 'add', '-A'], { env });
  execFileSync('git', ['-C', S, 'commit', '-qm', 'first'], { env });
  registerProject('stampproj');      // made here, not by create (R154)
  setPolicyFor('stampproj', 'minor');
  const sb = (...a) => { try {
      return { out: execFileSync('bash', [BB, 'version', ...a], { cwd: S, env }).toString(), code: 0 };
    } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; } };

  let s1 = sb('bump', 'minor');
  ok(s1.code === 0, `the bump runs the repo's own stamp hook (${s1.out.trim().slice(0, 56)})`);
  ok(readFileSync(`${S}/stamped.txt`, 'utf8').trim() === 'window 0.5',
     '...which moved the number it carries elsewhere');
  const inCommit = execFileSync('git', ['-C', S, 'show', '--name-only', '--format=', 'HEAD'],
                                { encoding: 'utf8' }).split('\n').filter(Boolean);
  ok(inCommit.includes('stamped.txt') && inCommit.includes('VERSION'),
     `...and it is in the SAME commit as VERSION, so neither can land alone (${inCommit.join(', ')})`);

  // A hook that fails stops the bump rather than leaving the number moved and
  // its twin behind: the state the whole thing exists to prevent.
  writeFileSync(`${S}/tools/version-stamp`,
    '#!/usr/bin/env bash\necho "no thanks" >&2\nexit 3\n');
  chmodSync(`${S}/tools/version-stamp`, 0o755);
  s1 = sb('bump', 'minor');
  ok(s1.code !== 0 && /version-stamp failed/.test(s1.out),
     `a stamp hook that fails refuses the bump, and says so (${s1.out.trim().slice(0, 56)})`);
  ok(readFileSync(`${S}/VERSION`, 'utf8').trim() === '0.5.0',
     '...leaving VERSION exactly where it was');

  // And the stamps come BACK with the number. Without this, taking a bump
  // back leaves what the bump moved where it was: for BuilderBot, a
  // controller returned to its old version still promising the new
  // compatibility window to every node and every briefing.
  writeFileSync(`${S}/tools/version-stamp`,
    '#!/usr/bin/env bash\nset -e\n[ "$2" = minor ] || exit 0\n'
    + 'printf "window %s\\n" "${1%.*}" > stamped.txt\necho moved\n');
  chmodSync(`${S}/tools/version-stamp`, 0o755);
  execFileSync('git', ['-C', S, 'add', '-A'], { env });
  // A no-op when the working hook is byte-identical to the committed one,
  // which it is: the failing hook above never reached a commit.
  try { execFileSync('git', ['-C', S, 'commit', '-qm', 'hook back'], { env }); } catch { /* clean */ }
  s1 = sb('unbump');
  ok(s1.code === 0, `an unreleased bump can be taken back (${s1.out.trim().slice(0, 56)})`);
  ok(readFileSync(`${S}/VERSION`, 'utf8').trim() === '0.4.0'
     && readFileSync(`${S}/stamped.txt`, 'utf8').trim() === 'window 0.4',
     '...and what the bump stamped elsewhere comes back with it');
  const undone = execFileSync('git', ['-C', S, 'show', '--name-only', '--format=', 'HEAD'],
                              { encoding: 'utf8' }).split('\n').filter(Boolean);
  ok(undone.includes('stamped.txt') && undone.includes('VERSION'),
     `...in one commit, the way it went (${undone.join(', ')})`);

  // ---- what a window move costs, before it is pressed (B92) --------------
  // One project can move the compatibility window: the one whose checkout IS
  // BuilderBot. What that window holds, now a session's briefing is assembled
  // per session and cannot be from another one (R63 step 3), is a node's
  // AGENT: every project bound to a node is held until that node is updated,
  // and the sessions on it end. Nothing said so before the button was pressed.
  // The two files that move the window are the test, rather than a project's
  // name.
  mkdirSync(`${S}/scripts/agent`, { recursive: true });
  writeFileSync(`${S}/scripts/agent/builderbot-agent.py`, 'AGENT_VERSION = "0.5.1"\n');
  // A project on an agent node is what the window holds, so bind one: the
  // harness enrolls `sandbox` for the whole suite.
  const sbox = await page.evaluate(async () =>
    ((await (await fetch('/api/v1/nodes')).json()).nodes || [])
      .find(n => n.kind === 'agent')?.id || '');
  ok(/^n_/.test(sbox), `the harness's agent node is there to bind to (${sbox || 'none'})`);
  await page.evaluate(async id => {
    await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ project: 'alpha', node: id }) });
  }, sbox);
  const cost = await page.evaluate(async () => {
    const one = await (await fetch('/api/version?project=stampproj')).json();
    const other = await (await fetch('/api/version?project=alpha')).json();
    return { one: one.window_cost, other: other.window_cost };
  });
  ok(cost.one && (cost.one.projects || []).includes('alpha'),
     `the project that moves the window says which projects a move would hold (${
       JSON.stringify(cost.one || {}).slice(0, 90)})`);
  ok(cost.one.window && /^\d+\.\d+$/.test(cost.one.window),
     `...and the window they are all on, which is the one that would move (${cost.one.window})`);
  ok(!cost.other,
     '...while a project that moves nobody\'s window says nothing, rather than warning about a cost it has not got');
  await page.evaluate(async () => {
    await fetch('/api/prefs', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ project: 'alpha', node: '' }) });
  });
  rmSync(S, { recursive: true, force: true });
}

// A project with no session says so rather than silently doing nothing.
const askDead = await page.evaluate(async () => {
  const r = await fetch('/api/version', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({project: 'beta', action: 'ask'})});
  return await r.json();
});
ok(/no session is running/.test(askDead.error || ''),
   'asking a project with no session reports it instead of failing quietly');

ok((await page.errors).every(e => /400/.test(e)),
   '...and the only failed request afterwards is the refusal just asked for');

// ---- where a bump lands (B338) -----------------------------------------------
// A bump commits on whatever branch the checkout is on and never pushes, and
// that stays. What a project released from main met was the row not saying
// so: it was bumped to 0.8.0 on a branch already merged into main, unpushed,
// while the tab showed 0.8.0 and main still read 0.7.0. Built here for real,
// with a bare remote, the branch merged the way a pull request merges it.
{
  const L = `${WS}/landproj`, REMOTE = `${DIR}/landproj.git`;
  rmSync(L, { recursive: true, force: true });
  rmSync(REMOTE, { recursive: true, force: true });
  const g = (...a) => execFileSync('git', ['-C', L, ...a], { encoding: 'utf8', env }).trim();
  execFileSync('git', ['init', '-q', '--bare', REMOTE], { env });
  mkdirSync(L, { recursive: true });
  g('init', '-q', '-b', 'main', '.');
  writeFileSync(`${L}/VERSION`, '0.7.0\n');
  writeFileSync(`${L}/f`, 'one');
  g('add', '-A'); g('commit', '-qm', 'one');
  g('remote', 'add', 'origin', REMOTE);
  g('push', '-q', '-u', 'origin', 'main');
  g('checkout', '-q', '-b', 'claude/polish');
  writeFileSync(`${L}/f`, 'two');
  g('commit', '-qam', 'polish');
  g('checkout', '-q', 'main');
  g('merge', '-q', '--no-ff', '-m', 'Merge claude/polish', 'claude/polish');
  g('push', '-q', 'origin', 'main');
  g('checkout', '-q', 'claude/polish');

  const LNB = nb('landproj');
  await takeOn('landproj');            // made by hand here, so the owner takes it on (R135)
  await refreshUntil(page, () => state?.projects?.some(p => p.name === 'landproj'), { timeout: 20000 });
  await page.evaluate(() => openNotebook('landproj', 'artifacts'));
  await page.waitForSelector(`${LNB} #verBox [data-verbump="minor"]`, { timeout: 20000 });
  const marks = () => page.$$eval(`${LNB} #verBox .vermark`, ms => ms.map(m =>
    ({ text: m.textContent.replace(/\s+/g, ' ').trim(), bad: m.classList.contains('bad') })));
  ok(!(await marks()).some(m => /builds come from/i.test(m.text)),
     'a checkout whose number matches the branch builds come from says nothing about it');
  await page.click(`${LNB} #verBox [data-verbump="minor"]`);
  await page.waitForFunction(sel => [...document.querySelectorAll(sel)]
    .some(m => /Save commits it on/.test(m.textContent)), `.nb #verBox .vermark`, { timeout: 20000 }).catch(() => {});
  const staged = (await marks()).find(m => /Save commits it on/.test(m.text));
  ok(staged?.bad && /Save commits it on claude\/polish, which is already in main, where builds come from/.test(staged.text)
     && /switch to main on the Git view and pull first/.test(staged.text),
     `a bump staged on a branch already merged into main says where Save would commit it and how to bump main (${staged?.text})`);
  // Red as an error is everywhere, beside the plain staged line's yellow, and
  // in the value column with it: the class drew nothing until B338, and a
  // long line dropped under the label.
  const look = await page.$$eval(`${LNB} #verBox .vermark`, ms => {
    const probe = document.createElement('span');
    probe.style.color = 'var(--bad)';
    document.body.appendChild(probe);
    const red = getComputedStyle(probe).color;
    probe.remove();
    const of = re => ms.find(m => re.test(m.textContent));
    const [warn, plain] = [of(/Save commits it on/), of(/staged: 0\.8\.0/)];
    return { red, warn: warn && getComputedStyle(warn).color, plain: plain && getComputedStyle(plain).color,
             lefts: [warn, plain].map(m => m && Math.round(m.getBoundingClientRect().left)) };
  });
  ok(look.warn === look.red && look.plain !== look.red && look.lefts[0] === look.lefts[1],
     `...in red beside the staged line's yellow, and in the same column (${JSON.stringify(look)})`);
  await page.click(`${LNB} [data-ssave="artifacts:version"]`);
  await page.waitForFunction(sel => [...document.querySelectorAll(sel)]
    .some(m => /0\.8\.0 is committed on/.test(m.textContent)), `.nb #verBox .vermark`, { timeout: 20000 }).catch(() => {});
  const now = (await marks()).find(m => /is committed on/.test(m.text));
  ok(now?.bad && now.text === '0.8.0 is committed on claude/polish, on top of work main already has, and not pushed. '
                               + 'Builds come from main, which reads 0.7.0 as last fetched, so it reaches them only through another merge.',
     `...and once saved, the row says in red that the number sits unpushed on work main already has, while main still reads the old one (${now?.text})`);
  ok(g('rev-parse', '--abbrev-ref', 'HEAD') === 'claude/polish' && g('show', 'origin/main:VERSION') === '0.7.0',
     '...the bump itself committed where the checkout stands and pushed nothing, as it always has');

  // A session bumping from its terminal reads the same sentence.
  setPolicyFor('landproj', 'open');
  const lb = (...a) => { try {
      return { out: execFileSync('bash', [BB, 'version', ...a], { cwd: L, env }).toString(), code: 0 };
    } catch (e) { return { out: (e.stdout + '' + e.stderr).toString(), code: e.status }; } };
  const bumped = lb('bump', 'patch');
  ok(bumped.code === 0 && bumped.out.includes('0.8.1 is committed on claude/polish and not pushed. '
                                              + 'Builds come from main, which reads 0.7.0 as last fetched.'),
     `bb version bump says the same where a session bumps (${bumped.out.trim().split('\n').pop()})`);
  g('push', '-q', 'origin', 'claude/polish');
  const shown = lb().out;
  ok(/branch\s+0\.8\.1 is committed on claude\/polish\. Builds come from main, which reads 0\.7\.0 as last fetched\./.test(shown),
     `...and bb version, once the branch is pushed, drops "not pushed" and still says what main reads (${
       (shown.match(/branch\s+.*/) || [''])[0].trim()})`);
  g('checkout', '-q', 'main');
  ok(!/branch\s/.test(lb().out), '...and on main, level with the remote, it says nothing');
  await page.evaluate(() => { tabs.filter(t => t.kind === 'notebook' && t.arg === 'landproj').forEach(t => dropTab(t.id)); });
  rmSync(L, { recursive: true, force: true });
  rmSync(REMOTE, { recursive: true, force: true });
}

// The briefing every session is handed. It is read into the prompt of every
// session on every project, so a rendered example version in it is a number
// thousands of conversations see, and one did exactly what a number in a
// briefing does: a session asked to give a new project its first version read
// 0.4.0 out of the file it had been briefed with and proposed it, having
// derived nothing. The file changed under R63 step 3; the trap did not.
{
  const brief = readFileSync(new globalThis.URL(
    '../../../config/templates/briefing.md', import.meta.url), 'utf8');
  const rendered = brief.match(/\b\d+\.\d+\.\d+(-dev\.\d+)?/g) || [];
  ok(rendered.length === 0,
     `the briefing renders no example version${
       rendered.length ? ', got ' + rendered.join(', ') : ''}`);
}

// fresh() removes stray projects but does not reach inside a fixture, so the
// commits and the VERSION file this planted in alpha and beta have to go;
// otherwise every later file runs against projects this one changed.
for (const d of [A, B]) rmSync(`${d}/.git`, { recursive: true, force: true });
rmSync(`${A}/VERSION`, { force: true });
rmSync(`${A}/a.txt`, { force: true });
rmSync(`${A}/b.txt`, { force: true });
rmSync(`${B}/readme.txt`, { force: true });
rmSync(`${B}/VERSION`, { force: true });
rmSync(`${B}/sub`, { recursive: true, force: true });
execFileSync('git', ['-C', A, 'init', '-q', '.'], { env });
execFileSync('git', ['-C', B, 'init', '-q', '.'], { env });
execFileSync('git', ['-C', A, 'remote', 'add', 'origin',
                     'git@github.com:owner/alpha.git'], { env });
// ---- Move the version, with the other Claude may dials (B448) ---------------
// An owner who set every dial on the settings panel to auto still found the
// version locked, since the policy lived on the Artifacts tab alone. The
// panel carries it now and writes the same policy.
{
  await page.evaluate(() => { document.querySelectorAll('.modal:not([hidden])').forEach(m => { m.hidden = true; }); renameProject('alpha'); });
  await page.waitForSelector('#rnmodal:not([hidden]) #rnGateVersion', { timeout: 15000 });
  const was = await page.$eval('#rnGateVersion', e => ({ v: e.value, opts: [...e.options].map(o => o.value).join() }));
  ok(was.opts === 'locked,start,patch,minor,open', `the settings carry Move the version with the policy's five choices (${was.opts}, now ${was.v})`);
  await page.selectOption('#rnGateVersion', 'minor');
  await saveDialog(page);
  await page.waitForFunction(async () => {
    const j = await (await fetch('/api/status')).json();
    return (j.projects || []).find(p => p.name === 'alpha')?.version_policy === 'minor';
  }, null, { timeout: 20000, polling: 500 });
  ok(true, '...and saving the dialog sets the policy the Artifacts tab shows');
  await page.evaluate(() => postJSON('/api/version', { project: 'alpha', action: 'policy', policy: 'locked' }));
}

await done(browser);
