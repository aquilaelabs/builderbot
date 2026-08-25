// One version identity per project, and who is allowed to move it.
//
// No browser: version.py has no UI yet, and the part worth protecting is the
// policy gate — a session must not be able to bump past what the operator
// allowed, and a bump must not sweep unrelated work into its commit. Both are
// reachable through `bb version`, which is the same module the notebook will
// call, so testing the CLI tests the thing.
import { ok, done, DIR } from './lib.mjs';
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
const setPolicy = v => {
  const py = fileURLToPath(new URL('../version.py', import.meta.url));
  execFileSync('python3', ['-c', `
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location('v', ${JSON.stringify(py)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.configure(workspace=${JSON.stringify(WS)}, state=${JSON.stringify(`${DIR}/state`)},
            write_json=lambda p, o: open(str(p), 'w').write(json.dumps(o)))
print(m.set_policy(${JSON.stringify(PROJ)}, ${JSON.stringify(v)}))`], { env });
};
setPolicy('minor');
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
await done();
