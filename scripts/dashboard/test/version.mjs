// One version identity per project, and who is allowed to move it.
//
// No browser: version.py has no UI yet, and the part worth protecting is the
// policy gate — a session must not be able to bump past what the operator
// allowed, and a bump must not sweep unrelated work into its commit. Both are
// reachable through `bb version`, which is the same module the notebook will
// call, so testing the CLI tests the thing.
import { launch, newPage, ready, ok, done, sleep, SLOW, tmuxCapture, DIR, URL as DURL } from './lib.mjs';
import { mkdirSync, writeFileSync, readFileSync, rmSync, existsSync } from 'node:fs';
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
ok(yb('changelog', 'add', 'Worked before any version existed').code === 0,
   'a change can be logged before the project has a VERSION at all');
setPolicyFor('young', 'open');
yb('version', 'init', '0.1.0');
const born = yb('changelog').out;
ok(/## 0\.1\.0 — \d{4}-\d{2}-\d{2}/.test(born) && !/## Unreleased/.test(born),
   '...and init dates the accrued entries as the first version\u2019s section');
rmSync(Y, { recursive: true, force: true });

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
// ---- the changelog: accrued by sessions, dated by the bump ---------------
// The record and the number are decoupled on purpose: entries land under
// Unreleased as work is done, and a bump — whoever presses it — only renames
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
ok(cl('add', 'Pairing works across screen switches').code === 0,
   'a session can log a user-facing change');
cl('add', 'The app no longer forgets its settings', '--for', 'extension');
ok(/Pairing works/.test(cl().out) && !/forgets its settings/.test(cl().out),
   "an entry lands in the changelog it was logged to, not the project's");
ok(/forgets its settings \([0-9a-f]{7}\)/.test(cl('--for', 'extension').out),
   '...stamped with the commit it describes');
ok(cl('add', '').code !== 0, 'an empty entry is refused');

// A change that tweaks something already logged this cycle corrects the
// line rather than adding a second one about the same thing — the reader
// should meet each change once, and the honest record is one line that is
// right. Positional numbers, because the section is short-lived by design.
cl('add', 'Pairing shows the code larger');
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

// The bump dates the section, in the same commit that moves VERSION.
mb('bump', 'patch');
const rolled = cl().out;
ok(/## 2\.2\.1 — \d{4}-\d{2}-\d{2}\n\n- Pairing works/.test(rolled)
   === false && /## 0\.4\.1 — \d{4}-\d{2}-\d{2}/.test(rolled)
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
cl('add', 'Something new after the release');
const reopened = cl().out;
ok(reopened.indexOf('## Unreleased') !== -1
   && reopened.indexOf('## Unreleased') < reopened.indexOf('## 0.4.1'),
   'the next entry reopens Unreleased above the dated history');
// ---- what a review pass caught, kept caught ------------------------------
// A project release tag must not stamp a component: the repo-wide vX.Y.Z
// says nothing about the extension, even when the numbers coincide.
execFileSync('git', ['-C', M, 'tag', '-a', 'v2.2.0', '-m', 'r'], { env });
// the root target is 0.4.x so the root stays -dev; the extension's target IS
// 2.2.0 now, and the trap is that this tag would have released it.
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
// bump dated dissolves into Unreleased with whatever was logged after — so
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
ub('changelog', 'add', 'went into the bump');
ub('version', 'bump', 'minor');
ub('changelog', 'add', 'logged after the bump');
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
// Released numbers are immutable — somebody may have installed one.
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
ok(/CLAUDE\.md/.test(lockedAsk.text),
   '...and points at the protocol rather than restating it');
ok(/propose and ask, do not apply/.test(lockedAsk.text),
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
ok(/is at 0\.4\.0 — is that still right\?/.test(holds.text)
   && /propose and ask, do not apply/.test(holds.text),
   'with a version, the ask becomes "is this still right"');
ok(holds.text.length < 250,
   `...and that one is short too (${holds.text.length} chars)`);
rmSync(AK, { recursive: true, force: true });

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
// :visible nor offsetParent separates them — both are laid out. The title is
// the only thing in the markup that tells them apart.
const nb = name => `.nb:has(#memTitle:text-is("Notebook — ${name}"))`;
let NB = nb('alpha');

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(DURL);
await ready(page);
await page.click(`#projects .row:has(.name:text-is("alpha")) [data-m]`);
await page.waitForSelector('#todoList, .nb', { timeout: 20000 });
await page.click(`${NB} .nbtabs [data-v="artifacts"]`);
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
// bands stacked, which on a phone is one scroll with nothing labelling it.
{
  const sects = await page.$$eval(`${NB} .nbview[data-view="artifacts"] .sect > summary`,
    ss => ss.map(s => [s.querySelector('.t')?.textContent,
                       s.querySelector('.sst')?.textContent]));
  ok(sects.some(([t]) => t === 'Build') && sects.some(([t]) => t === 'Version'),
     'the tab names what it is showing: Build and Version are sections');
  ok(sects.find(([t]) => t === 'Version')?.[1] === '0.4.0',
     '...and the version is the heading\'s status, so a shut one still answers');
}
ok(/^0\.4\.0-dev\.3\+[0-9a-f]{7}$/.test(r0['a build now'] || ''),
   '...and what a build right now would be called');
ok(/since 0\.4\.0: 1 commit\b/.test(await boxText()),
   '...with the commits since the target last moved, as the case for a bump');

// Buttons, not a text field: a malformed version can never reach a manifest.
const labels = await page.$$eval(`${NB} #verBox [data-verbump]`, bs => bs.map(b => b.textContent.trim()));
ok(labels.some(l => /Patch → 0\.4\.1/.test(l)) && labels.some(l => /Minor → 0\.5\.0/.test(l))
   && labels.some(l => /Major → 1\.0\.0/.test(l)),
   'each button previews the value it would set');

// The operator's bump is allowed regardless of the policy — the policy is
// about sessions. And it STAGES: pressing Minor records the intent, git is
// untouched until the notebook's Save — a misclicked "Major → 1.0.0" must
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
// Pressing the same part again clears the stage — the undialog misclick path.
await page.click(`${NB} #verBox [data-verbump="minor"]`);
ok(!/staged:/.test(await page.$eval(`${NB} #verBox`, e => e.textContent)),
   '...and pressing it again unstages, no dialog needed');
await page.click(`${NB} #verBox [data-verbump="minor"]`);
await page.click(`${NB} #todoSaveQuiet`);
await waitTarget('0.5.0');
ok((await rows())['building towards'] === '0.5.0',
   'Save commits the staged bump — the operator can, whatever the policy');
ok(execFileSync('git', ['-C', A, 'log', '-1', '--format=%s'], { env }).toString().trim()
     === 'Set version to 0.5.0',
   '...and the commit says the operator moved it, with no "(session)" mark');
ok(!execFileSync('git', ['-C', A, 'status', '--porcelain'], { env }).toString().includes('VERSION'),
   '...leaving no dirty VERSION behind');

// The policy control is the answer to "when should this be incremented" for
// a session: the operator decides how much of the decision to delegate.
// Staged like a bump: the pick alone writes nothing, and the foot's Save
// is what commits it (docs/design-language.md, Settings).
await page.selectOption(`${NB} #verPolicy`, 'minor');
await page.waitForFunction(() => [...document.querySelectorAll('.nb #verBox .verpol')]
  .some(e => /staged: on Save/.test(e.textContent)), null, { timeout: 10000 });
ok((await page.evaluate(async () => (await (await fetch('/api/version?project=alpha')).json()).policy)) !== 'minor',
   'picking a policy stages it and writes nothing yet');
await page.click(`${NB} #todoSaveQuiet`);
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

// The harness's tab state survives between test files, so an earlier file
// can leave this notebook parked out of a pane: the input then resolves but
// is never visible, and a plain fill waits its timeout out. Re-showing the
// notebook is the fix the operator would make by hand — click the project
// row (which goes to the existing tab) and the view strip again.
// Atomic on purpose: setting the field and pressing the button in two
// round trips leaves a gap a redraw can land in — the box re-renders when a
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
   '...while the changelog stays reachable — entries accrue before a version exists');
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
// already be in — StreamLift proposed 0.2.0 for the app and 0.1.0 for its
// extension while neither file existed — so the component door has to be
// visible before the root version is, not only after.
ok(await page.$(`${NB} #verBox .veradd .vdir`) !== null,
   'the component fold is offered before the project has any version at all');

// A starting number is arbitrary — nothing can derive it — so it is the one
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
   '...with Ask Claude still there — the question changes, the door stays');

// A component is created the same way, from what is actually on disk rather
// than a path typed from memory.
const dirs = await page.$$eval(`${NB} #verBox .vdir option`, os => os.map(o => o.textContent));
ok(dirs.includes('sub'), 'the component control offers directories that exist');
ok(!dirs.includes('.git'), '...and not the ones that are nobody\'s product');

// The changelog pane, on beta which has none: the message says how to start
// one rather than rendering an error, and the button toggles it away.
// NB is a Playwright selector (:has, :text-is), which the page's own
// querySelector cannot parse — so the polling stays on this side.
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
ok(/no CHANGELOG\.md here yet/.test(paneText),
   'the changelog pane says how to opt in when there is no file');
// The flake this suite carried for weeks, as a rule instead. The pane used to
// live in #verBox and be MOVED into the sheet, so a repaint of that box while
// the sheet was open — a version poll, a commit, a dist change — put a second
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
// $eval, not evaluate: NB is a Playwright selector — :text-is() is theirs,
// and querySelector has never heard of it.
const clog = await page.$eval(`${NB} .verlogpane`, (pane) => {
  const slot = pane.closest('.sheetslot');
  return { inSheet: !!slot,
           tall: !!slot && pane.offsetHeight >= slot.clientHeight - 1,
           boxed: getComputedStyle(pane).borderTopWidth !== '0px' };
});
ok(clog.inSheet && clog.tall && !clog.boxed,
   '...filling the window it opens in, with no second box drawn inside it');

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
ok(cleanSoFar.length === 0, `no console errors from the version block${cleanSoFar.length ? ' — got: ' + JSON.stringify(cleanSoFar.slice(0, 3)) : ''}`);

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

// fresh() removes stray projects but does not reach inside a fixture, so the
// commits and the VERSION file this planted in alpha and beta have to go —
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
await done(browser);
