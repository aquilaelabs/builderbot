// bb-tty's Claude launch — the one path the browser files cannot reach, since
// the harness runs no ttyd. This drives the script the way ttyd does (one URL
// argument, one connection) against the same private tmux server, with stubs
// standing in for `bb` and `claude`.
//
// What it is here for: tmux hands `new-session` its command in a single 16KB
// message and answers a longer one with `command too long`. The system prompt
// bb-tty appends carries the project's whole roadmap and open bugs, so it grows
// with the project — and once past that line, every Claude session on that
// project became unstartable, ttyd reconnecting into the same error every five
// seconds. The command goes through a launcher file now, and this is the test
// that says so.
import { ok, done, sleep, URL, DIR, tmuxKill, tmuxNew, tmuxFmt } from './lib.mjs';
import { execFileSync } from 'child_process';
import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, readFileSync, existsSync, lstatSync, readlinkSync, rmSync, statSync, symlinkSync, realpathSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

const BBTTY = join(import.meta.dirname, '..', 'bb-tty');
const LAUNCHER = join(DIR, 'home', '.cache', 'builderbot', 'claude-run-alpha.sh');

// The boot this container is on, from the server rather than computed again
// here: the page reads it from /api/status and puts it in the terminal's URL,
// and bb-tty refuses a session whose URL names a previous run. Asking the same
// source the page asks keeps this test honest about what it is driving.
const status = await (await fetch(new global.URL('api/status', URL), {
  headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') },
})).json();
const boot = status.boot;

// Stubs, ahead of everything on PATH. `claude` has to hold the pane open — a
// command that exits takes the session with it, and the session is the thing
// being asserted — and to record what it was handed.
const bin = mkdtempSync(join(tmpdir(), 'bbtty-'));
const argvOut = join(bin, 'argv');
writeFileSync(join(bin, 'bb'), `#!/usr/bin/env bash
# A roadmap of whatever size the case asks for, in items rather than one long
# line, so the trim has real line boundaries to land on.
case "\${1:-}" in
  roadmap) if [ "\${2:-}" = --prompt ] && [ "\${FAKE_PROMPT:-0}" -gt 0 ]; then
             n=$(( FAKE_PROMPT / 50 ))
             for ((i = 0; i < n; i++)); do
               printf -- "- #%d  an item with enough words in it to be about fifty\\n" "$i"
             done
           fi ;;
  bug)     [ "\${2:-}" = --prompt ] && printf 'the bugs block\\n' ;;
  rules)   [ "\${2:-}" = --prompt ] && printf 'THE HOUSE RULES\\n' ;;
  # What bb-tty actually asks for now: the three blocks already assembled, in
  # the order a session reads them, with the cap applied. The real assembly is
  # preamble.py and is tested against the real stores in preamble.mjs; this
  # stands in for it so the SIZE stays the thing these cases control.
  preamble) [ "\${2:-}" = --json ] && FAKE_PROMPT="\${FAKE_PROMPT:-0}" python3 -c '
import json, os
n = int(os.environ.get("FAKE_PROMPT", "0")) // 50
parts = ["THE HOUSE RULES"]
if n:
    parts.append("\\n".join(
        "- #%d  an item with enough words in it to be about fifty" % i for i in range(n)))
parts.append("the bugs block")
t = "\\n\\n".join(parts)
MAX = 100000
b = t.encode()
capped = len(b) > MAX
if capped:
    c = b[:MAX].decode("utf-8", "ignore")
    t = c[:c.rfind("\\n") + 1] + "[the rest of this list did not fit in the prompt]"
print(json.dumps({"text": t, "bytes": len(b), "max": MAX, "capped": capped, "parts": []}))' ;;
  settings) [ "\${2:-}" = --json ] && printf '{"git_name":"Pat Tester","git_email":"pat@example.invalid","git_ready":%s}\\n' "$([ "\${FAKE_GIT_READY:-1}" = 0 ] && echo false || echo true)" ;;
  # The gate bb-tty asks before starting a session: exit 0 means the
  # environment block is from another compatibility window and no session
  # should start. Answered from an env var the cases below flip, the way the
  # claude stub answers auth from a fixture — and answered HONESTLY by
  # default, because a stub that exits 0 for everything reads as "every
  # project is out of window" and would refuse every session in this file.
  # Only for that flag: a stub answering --is-stale the same way would be
  # testing the gate the page no longer asks.
  claude-md) [ "\${2:-}" = --out-of-window ] && [ "\${FAKE_MD_GAP:-0}" = 1 ] && exit 0; exit 1 ;;
esac
exit 0
`);
writeFileSync(join(bin, 'claude'), `#!/usr/bin/env bash
if [ "\${1:-}" = auth ]; then
  [ "\${2:-}" = status ] && printf '{"loggedIn":true}\\n'
  exit 0
fi
printf '%s\\0' "$@" > "${argvOut}"
sleep 60
`);
chmodSync(join(bin, 'bb'), 0o755);
chmodSync(join(bin, 'claude'), 0o755);

// One connection, the way ttyd makes one. bb-tty ends by exec'ing `tmux
// attach-session`, which fails without a terminal — by then the session either
// exists or does not, which is the whole question.
function connect(promptBytes, env){
  tmuxKill('claude-alpha');
  try {
    return execFileSync('bash', [BBTTY, `claude:alpha:b:${boot}`], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}`,
             WORKSPACE: join(DIR, 'ws'), HOME: join(DIR, 'home'),
             DASHBOARD_STATE: join(DIR, 'state'), FAKE_PROMPT: String(promptBytes),
             ...(env || {}) },
    });
  } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; }
}
const alive = n => { try { return tmuxFmt(n, '#{session_name}') === n; }
                     catch { return false; } };
const paneCmd = () => { try { return tmuxFmt('claude-alpha', '#{pane_start_command}'); }
                        catch { return ''; } };
// Missing is an answer, not a crash: run this against the code before the
// launcher and every one of these should read FAIL, not stop the file.
const launcher = () => existsSync(LAUNCHER) ? readFileSync(LAUNCHER, 'utf8') : '';

// A roadmap of 40KB. Under the old code this was `command too long` and no
// session at all — the operator's report was a pane filling with that line as
// ttyd reconnected into it every five seconds.
let out = connect(40000);
await sleep(400);
ok(!/command too long/.test(out),
   'a roadmap past tmux\'s 16KB command limit does not stop the session starting');
ok(alive('claude-alpha'), '...the session is really there');
// The account's commit identity rides into the session as git's environment
// — GIT_AUTHOR_* and GIT_COMMITTER_*, which outrank any user.name a
// repository carries — from bb settings --json, which the stub answers.
const genv = k => { try { return execFileSync('tmux', ['show-environment', '-t', 'claude-alpha', k], { encoding: 'utf8' }).trim(); } catch { return ''; } };
ok(genv('GIT_AUTHOR_NAME') === 'GIT_AUTHOR_NAME=Pat Tester'
   && genv('GIT_COMMITTER_EMAIL') === 'GIT_COMMITTER_EMAIL=pat@example.invalid',
   `the session carries the account's commit identity as git's environment (${genv('GIT_AUTHOR_NAME') || 'unset'})`);
const cmd = paneCmd();
ok(cmd.length < 200 && /claude-run-alpha\.sh$/.test(cmd),
   '...because tmux was handed a launcher, not the command');
ok(launcher().length > 40000,
   '...and the launcher carries the prompt tmux could not');
// ...and the token beside it, where a session that has ALREADY STARTED can
// pick it up. A session outlives its twelve-hour token; the launcher is
// rewritten on every connection but a running claude keeps the environment
// it started with, so this file is the only way back for one that has been
// going longer than that (bb_token_now prefers it once BB_TOKEN is dead).
const TOKFILE = join(DIR, 'home', '.cache', 'builderbot', 'token-alpha');
const tokWritten = existsSync(TOKFILE) ? readFileSync(TOKFILE, 'utf8').trim() : '';
ok(/^bbs_/.test(tokWritten) && (statSync(TOKFILE).mode & 0o077) === 0,
   `the session's token is written beside the launcher for a running session to pick up, 0600 (${
     tokWritten.slice(0, 12)}…)`);
ok(launcher().includes(tokWritten),
   '...and it is the same one the launcher exports, not a second grant');
{
  // What bb does with it: a BB_TOKEN that has expired falls through to this
  // file, and a live one is left alone.
  const BBBIN = new globalThis.URL('../../bb', import.meta.url).pathname;
  const dead = 'bbs_' + Buffer.from('alpha|1000000000|u_0badf00d|deadbeef')
    .toString('base64url').replace(/=+$/, '');
  const ask = (env) => execFileSync('bash', ['-c',
    'eval "$(sed -n "/^bb_token_exp()/,/^}/p;/^bb_token_dead()/,/^}/p;/^bb_token_now()/,/^}/p" "$1")"; bb_token_now',
    'sh', BBBIN],
    { encoding: 'utf8', env: { ...process.env, HOME: join(DIR, 'home'), BB_PROJECT: 'alpha', ...env } }).trim();
  ok(ask({ BB_TOKEN: dead }) === tokWritten,
     'bb reaches for that file the moment the token it started with has expired');
  ok(ask({ BB_TOKEN: tokWritten }) === tokWritten,
     '...and leaves a live one alone');
}
const argv = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
ok(argv.includes('--append-system-prompt') && argv.length > 40000,
   '...which reaches claude whole, roadmap and all');
// The operator's rules go in front of the list: how they want this worked on
// before what there is to work on. Asserted by ORDER, not presence — the two
// blocks are one argument and either would be "in" it.
ok(argv.indexOf('THE HOUSE RULES') >= 0
   && argv.indexOf('THE HOUSE RULES') < argv.indexOf('the bugs block'),
   '...with the house rules ahead of the roadmap and the bugs');

// The next ceiling up is the kernel's: one argument cannot pass 131072 bytes,
// and exec answers "Argument list too long" — a pane that dies without saying
// why, which is the failure this file exists to keep out. Cut to fit, said out
// loud, and the session still starts.
out = connect(150000);
await sleep(400);
ok(alive('claude-alpha'), 'a roadmap past the kernel\'s argument limit still starts');
ok(/too long to fit/.test(out) && /bb roadmap/.test(out),
   '...saying so, and where to trim it');
ok(launcher().includes('did not fit in the prompt'),
   '...and the prompt itself says it was cut, rather than ending mid-item');

// The ordinary case still goes through the same path, so it is the one that
// gets exercised rather than a fallback nobody reaches until a list grows.
out = connect(0);
await sleep(400);
ok(alive('claude-alpha') && /claude-run-alpha\.sh$/.test(paneCmd()),
   'a project with no roadmap starts the same way');

// A locked project. Enforced HERE rather than by graying the button out,
// because the ttyd URL is reachable directly and a rule only the page honors
// is a suggestion — the same reason `excluded` is checked in this script.
const LOCKS = join(DIR, 'state', 'locked-projects.json');
writeFileSync(LOCKS, JSON.stringify(['alpha']));
const refusedAt = Date.now();
out = connect(0);
const refusedIn = Date.now() - refusedAt;
await sleep(400);
ok(/locked/.test(out) && !alive('claude-alpha'),
   'a locked project refuses a Claude session, whatever the URL asks for');
// A refusal holds the terminal open for ten seconds so the browser can show
// the reason — ttyd closes the connection the moment this exits. Only when
// something is holding one: called from here, with stderr on a pipe, there is
// nobody to show it to, and five tests in this suite were paying it.
ok(refusedIn < 5000,
   `...promptly, rather than pausing for a terminal nobody is holding open (${refusedIn}ms)`);
ok(/Projects card/.test(out),
   '...and says where to undo it, rather than only that it said no');

// A CLAUDE.md whose environment block is from ANOTHER compatibility window
// than this BuilderBot. The block is what a session is briefed with, so
// starting one on that copy is starting it on a wrong map — it reads that
// this container carries an Android SDK, or that builds happen here, and
// acts on it. Refused HERE as well as ghosted on the row, for the same
// reason the lock is: the ttyd URL is reachable directly. Drift inside the
// window is the stub's default answer above, and refuses nothing.
rmSync(LOCKS, { force: true });
out = connect(0, { FAKE_MD_GAP: '1' });
await sleep(400);
ok(/another\s+compatibility window/.test(out) && !alive('claude-alpha'),
   'a CLAUDE.md environment block from another window refuses a Claude session too');
ok(/update/.test(out),
   '...naming the one-press fix on the row rather than only saying no');

// No author, no session: an account with no name and email for commits is
// told to fill in its Profile, here as well as on the ghosted button, for
// the same reason as every other refusal in this file — the URL is reachable.
rmSync(LOCKS, { force: true });
out = connect(0, { FAKE_GIT_READY: '0' });
await sleep(400);
ok(/no name and email for commits/.test(out) && !alive('claude-alpha'),
   'an account with no author for its commits is refused a Claude session, and told where to set one');
// ...and a shell, which is where git is typed.
{
  try { execFileSync('tmux', ['kill-session', '-t', 'shell-1'], { env: { ...process.env, TMUX: '' } }); } catch { /* none */ }
  let shOut;
  try {
    shOut = execFileSync('bash', [BBTTY, 'sh:1:alpha'], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'),
             HOME: join(DIR, 'home'), DASHBOARD_STATE: join(DIR, 'state'), FAKE_GIT_READY: '0' } });
  } catch (e) { shOut = `${e.stdout || ''}${e.stderr || ''}`; }
  ok(/a shell does not start/.test(shOut) && !alive('shell-1'),
     'an account with no author is refused a shell too, in the same words');
}

// And unlocking really lets it back in: a gate that cannot be opened again is
// a different bug, and one nobody notices until they need it.
out = connect(0);
await sleep(400);
ok(alive('claude-alpha'), 'unlocking lets a session start there again');


// ---- what the project is set to run on ----------------------------------
// The setting lives in the dashboard's state and is resolved by the launcher
// at exec time rather than baked in by bb-tty, which is what lets a respawn
// through the same file pick up a change. Asserted on the argv the stub
// records, because that is the only place the answer is real.
writeFileSync(join(DIR, 'state', 'claude-prefs.json'), JSON.stringify(
  { projects: { alpha: { model: 'sonnet', effort: 'xhigh' } } }));
connect(0);
await sleep(400);
let a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
ok(/--model\0sonnet\0/.test(a) && /--effort\0xhigh\0/.test(a),
   "a project's model and effort reach claude as launch flags");
ok(!/--resume/.test(a),
   '...and an ordinary open is a fresh conversation, not a resumed one');

// Junk in the file is not a command line. The launcher matches against the
// same tables the dashboard writes from, so a hand-edited value is dropped
// rather than passed to claude.
writeFileSync(join(DIR, 'state', 'claude-prefs.json'), JSON.stringify(
  { projects: { alpha: { model: '--dangerously-skip-permissions', effort: 'max' } } }));
connect(0);
await sleep(400);
a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
ok(!/dangerously/.test(a) && /--effort\0max\0/.test(a),
   'a model the tables do not know is dropped, and the valid half still goes');

// --respawn is how the dashboard restarts a session onto a changed setting:
// the same launcher, re-reading the file and resuming what was running.
writeFileSync(join(DIR, 'state', 'claude-prefs.json'), JSON.stringify(
  { projects: { alpha: { model: 'opus', effort: 'low' } } }));
const tdir = join(DIR, 'home', '.claude', 'projects',
                  join(DIR, 'ws', 'alpha').replaceAll('/', '-'));
mkdirSync(tdir, { recursive: true });
writeFileSync(join(tdir, 'old-one.jsonl'), '');
await sleep(1100);                       // ls -t sorts by mtime, at 1s here
writeFileSync(join(tdir, 'the-live-one.jsonl'), '');
try {
  execFileSync('timeout', ['5', 'bash', LAUNCHER, '--respawn'], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}` },
  });
} catch { /* the stub holds the pane open; timeout ending it is the success */ }
a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
ok(/--model\0opus\0/.test(a) && /--effort\0low\0/.test(a),
   'a respawn re-reads the setting rather than repeating the one it started on');
ok(/--resume\0the-live-one\0/.test(a),
   '...and resumes the newest transcript, so the conversation continues');
rmSync(join(DIR, 'state', 'claude-prefs.json'), { force: true });

tmuxKill('claude-alpha');
// ---- a home and a shell of one's own (roadmap #26) --------------------------
// The dashboard's /term proxy stamps the argument with the account it
// authenticated (`u:<uid>:…`), and this is the half that acts on it: a shell
// runs in that account's home and under a name nobody else attaches to.
//
// The OWNER is deliberately the exception on both counts — they keep
// /home/builder and the bare session names — because a box with one operator
// is every box until somebody adds a second account, and an upgrade that
// renamed everything under them would be a cost paid by everyone for a case
// most installs never reach.
{
  const HOMEDIR = join(DIR, 'home');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const shell = (arg, extra = {}) => {
    try {
      return execFileSync('bash', [BBTTY, arg], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`,
               WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
               BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'),
               ...extra },
      });
    } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; }
  };
  // The box's own, which a home links to rather than copies.
  mkdirSync(join(HOMEDIR, '.android'), { recursive: true });
  const store = JSON.parse(readFileSync(join(DIR, 'state', 'users.json'), 'utf8'));
  const ownerUid = Object.values(store.users).find(u => u.role === 'owner').uid;
  ok(/^u_[0-9a-f]{8}$/.test(ownerUid || ''), `the owner has a minted id (${ownerUid})`);

  tmuxKill('shell-7'); tmuxKill(`${ownerUid}~shell-7`);
  shell(`u:${ownerUid}:sh:7:`);
  await sleep(300);
  ok(alive('shell-7') && !alive(`${ownerUid}~shell-7`),
     'the owner keeps the bare session name, so an upgrade renames nothing');
  ok(tmuxFmt('shell-7', '#{pane_start_path}') !== '' ,
     '...and it really started');
  tmuxKill('shell-7');

  // Anybody else gets their own name and their own home.
  const other = 'u_00c0ffee';
  tmuxKill(`${other}~shell-7`);
  shell(`u:${other}:sh:7:`);
  await sleep(300);
  ok(alive(`${other}~shell-7`) && !alive('shell-7'),
     `a second account's shell is named for it, so the two never share one (${other}~shell-7)`);
  ok(existsSync(join(HOMEDIR, 'users', other)),
     '...running in a home of its own, made on first use');
  ok(existsSync(join(HOMEDIR, 'users', other, '.android')),
     '...with the box\'s own dotfiles linked in rather than copied');
  ok(lstatSync(join(HOMEDIR, 'users', other, '.android')).isSymbolicLink(),
     '...as symlinks: copying .android would duplicate the AVDs and the pairing key');
  tmuxKill(`${other}~shell-7`);

  // ---- a worktree each (roadmap #24) ---------------------------------------
  // More than one person may work a project at once, and the reason it is safe
  // is that they are not in the same directory: /workspace/<project> is one
  // working tree, so two sessions in it commit each other's half-finished
  // work and delete it with a checkout. The owner keeps the project
  // directory; anybody else gets a worktree on a branch of their own.
  //
  // A repo with no commits has an unborn HEAD and `git worktree add` refuses
  // it, so this makes its own project with one — the fixtures are git init'd
  // and never committed to, and committing into one would be felt by every
  // suite that reads git.
  {
    const proj = 'wtproj', src = join(DIR, 'ws', proj);
    mkdirSync(src, { recursive: true });
    writeFileSync(join(src, 'README.md'), 'x\n');
    const git = a => execFileSync('git', ['-C', src, ...a],
      { encoding: 'utf8', env: { ...process.env, GIT_AUTHOR_NAME: 't',
        GIT_AUTHOR_EMAIL: 't@e', GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@e' } });
    git(['init', '-q']); git(['add', '-A']); git(['commit', '-qm', 'first']);

    tmuxKill(`claude-${proj}`); tmuxKill(`${other}~claude-${proj}`);
    shell(`u:${ownerUid}:claude:${proj}:b:${boot}`);
    await sleep(400);
    ok(alive(`claude-${proj}`),
       'the owner opens a Claude session under the bare project name');
    ok(tmuxFmt(`claude-${proj}`, '#{pane_start_path}') === src,
       '...working in the project directory itself, as it always has');

    shell(`u:${other}:claude:${proj}:b:${boot}`);
    await sleep(400);
    ok(alive(`${other}~claude-${proj}`) && alive(`claude-${proj}`),
       'a second account opens its own alongside it — two at once, not one');
    const wt = join(DIR, 'ws', '.worktrees', proj, other);
    ok(tmuxFmt(`${other}~claude-${proj}`, '#{pane_start_path}') === wt,
       `...in a worktree of its own rather than the same tree (${wt})`);
    ok(existsSync(join(wt, '.git')) && existsSync(join(wt, 'README.md')),
       '...which is a real checkout, sharing the project\'s one .git');
    const branch = git(['worktree', 'list', '--porcelain']);
    ok(/branch refs\/heads\/claude\//.test(branch),
       `...on a branch of its own, so the work merges rather than collides (${
          (branch.match(/branch \S+/g) || []).join(", ")})`);
    // The scope file walls it into ITS tree and names the other one as off
    // limits — two people on one project is exactly when that has to hold.
    const scope = JSON.parse(readFileSync(
      join(HOMEDIR, '.cache', 'builderbot', `claude-scope-${proj}.json`), 'utf8'));
    const deny = scope.permissions.deny.join(' ');
    ok(deny.includes(`Edit(${src}/**)`),
       '...with the project directory itself denied to it, being another tree');
    ok(!deny.includes(`Edit(${wt}/**)`),
       '...and its own not denied, which a blanket rule on .worktrees would have done');
    // The scope file also carries the work hook, which is how the finer half
    // of `bb work` gets anything to report.
    ok(JSON.stringify(scope.hooks?.Stop || {}).includes('bb-check-relay'),
       'the settings file wires the Stop hook that runs a rule\'s check before the session hands back (R31)');
    ok(JSON.stringify(scope.hooks || {}).includes('bb-work-note'),
       '...and the settings carry the hook that records what the session touches');
    // ...and the one that keeps this node's copy of the account's Claude
    // grant in step while the session runs. On UserPromptSubmit and nowhere
    // else: a prompt is the moment a session is about to work, and it is the
    // only thing on a node holding both a token minted for the account and
    // that account's home (B100).
    ok(JSON.stringify(scope.hooks?.UserPromptSubmit || {}).includes('bb-keep-login'),
       '...and the hook that keeps the Claude login in step, on every prompt');
    ok(!JSON.stringify(scope.hooks?.PreToolUse || {}).includes('bb-keep-login'),
       '...and not on every tool call, which would be a process per call for a thing that moves hourly');
    // No permission mode of BuilderBot's: what a session may do without
    // asking is set in Claude Code itself (the operator's call, 15 Sep), and
    // the deny list is the wall, so a sibling project, VERSION and the rules
    // file stay refused whatever mode the app is on.
    ok(scope.permissions.defaultMode === undefined,
       'the settings file sets no permission mode: that is Claude Code\'s own, chosen in the app');
    tmuxKill(`claude-${proj}`); tmuxKill(`${other}~claude-${proj}`);

    // ---- what overlaps (roadmap #24 step 2) --------------------------------
    // Two answers. Git is exact and needs nothing recorded: a file uncommitted
    // in two trees at once is a collision whatever anybody intended. The hook
    // is finer and is a guess, and says so.
    writeFileSync(join(src, 'm.py'), 'def alpha():\n    return 1\n\ndef beta():\n    return 2\n');
    git(['add', '-A']); git(['commit', '-qm', 'a module']);
    execFileSync('git', ['-C', src, 'worktree', 'prune']);
    const wt2 = join(DIR, 'ws', '.worktrees', proj, other);
    execFileSync('git', ['-C', wt2, 'merge', '-q', 'HEAD', '--no-edit'], { encoding: 'utf8' })
      .toString?.();
    writeFileSync(join(src, 'm.py'), 'def alpha():\n    return 9\n\ndef beta():\n    return 2\n');
    writeFileSync(join(wt2, 'm.py'), 'def alpha():\n    return 1\n\ndef beta():\n    return 8\n');
    writeFileSync(join(wt2, 'only-theirs.txt'), 'x\n');
    const work = execFileSync('bash', [`${REPO}/scripts/bb`, 'work'], {
      encoding: 'utf8',
      env: { ...process.env, BB_PROJECT: proj, DASHBOARD_STATE: join(DIR, 'state'),
             WORKSPACE: join(DIR, 'ws') } });
    ok(/2 working trees/.test(work),
       `bb work sees both trees (${work.split('\n')[0]})`);
    ok(/the same file, open in more than one/.test(work) && /m\.py/.test(work),
       '...and names the file both of them have uncommitted');
    ok(!/only-theirs/.test(work),
       '...and not the one only a single tree has, which is not a collision');

    // The hook: recorded, and the second session is told before it edits.
    const note = join(REPO, 'scripts', 'dashboard', 'bb-work-note');
    const hook = (uid, old_string) => execFileSync('python3', [note, proj, uid], {
      input: JSON.stringify({ tool_name: 'Edit',
        tool_input: { file_path: join(src, 'm.py'), old_string } }),
      encoding: 'utf8',
      env: { ...process.env, DASHBOARD_STATE: join(DIR, 'state'),
             WORKSPACE: join(DIR, 'ws'), BB_TREE: src } });
    hook('u_aaaaaaaa', '    return 2');
    const second = execFileSync('python3', [note, proj, 'u_bbbbbbbb'], {
      input: JSON.stringify({ tool_name: 'Edit',
        tool_input: { file_path: join(src, 'm.py'), old_string: '    return 2' } }),
      encoding: 'utf8', stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env, DASHBOARD_STATE: join(DIR, 'state'),
             WORKSPACE: join(DIR, 'ws'), BB_TREE: src } });
    ok(/additionalContext/.test(second) && /u_aaaaaaaa/.test(second),
       'the hook tells the second session who else has that file open');
    ok(!/permissionDecision/.test(second),
       '...and does not refuse it — two worktrees editing one function is two commits, not a corruption');
    const rec = JSON.parse(readFileSync(join(DIR, 'state', 'session-work.json'), 'utf8'));
    ok(rec[proj]['u_aaaaaaaa'].files['m.py'].includes('beta'),
       `...having recorded the enclosing definition, as a guess (${
          JSON.stringify(rec[proj]['u_aaaaaaaa'].files)})`);
  }

  // The id is checked, not trusted: the proxy is what puts it there, and a
  // shape that is not an id must not become a directory name.
  tmuxKill('shell-8');
  shell('u:../../etc:sh:8:');
  await sleep(300);
  ok(alive('shell-8') && !existsSync(join(HOMEDIR, 'users', '..', '..', 'etc', '.bashrc')),
     'an argument that is not an id is nobody, not somebody else');
  tmuxKill('shell-8');

  // ---- the environment reaches the pane (bug #54) ----------------------------
  // A new session gets the tmux SERVER's environment, not the connecting
  // client's — measured on tmux 3.4 — so the HOME bb-tty exported for an
  // account never reached the shell once any session existed: every later
  // account ran with the first one's Claude login. `-e` hands it over.
  {
    tmuxKill(`${other}~shell-9`);
    shell(`u:${other}:sh:9:`);
    await sleep(300);
    const home = (() => { try {
      return execFileSync('tmux', ['show-environment', '-t', `${other}~shell-9`, 'HOME'],
        { encoding: 'utf8', env: process.env }).trim();
    } catch { return ''; } })();
    ok(home === `HOME=${join(HOMEDIR, 'users', other)}`,
       `the session's own HOME is set on the session, not left to the server (${home})`);
    tmuxKill(`${other}~shell-9`);
  }

  // ---- the same script on a NODE (roadmap #24) ------------------------------
  // BUILDERBOT_ROLE=node is what the agent exports into every session it
  // starts, and it changes three answers: there is no owner (nothing on a
  // node is anyone's original, so every account is prefixed and homed under
  // users/, the owner included); the account's name and a session token
  // arrive on the URL, since the node has no users.json to look one up in
  // and no key to mint one with; and a project's directory is never worked
  // in directly — every session gets a worktree.
  {
    const node = { BUILDERBOT_ROLE: 'node', BB_CI_LOG_DIR: '/x/ci-logs' };
    // Another account's transcripts on the share, for the walls below.
    mkdirSync(join(DIR, 'ws', '.claude', 'u_0badf00d', 'projects'), { recursive: true });
    tmuxKill('shell-10'); tmuxKill(`${ownerUid}~shell-10`);
    shell(`u:${ownerUid}:sh:10:`, node);
    await sleep(300);
    ok(alive(`${ownerUid}~shell-10`) && !alive('shell-10'),
       'on a node the owner is prefixed like everybody else — there is no owner there');
    ok(existsSync(join(HOMEDIR, 'users', ownerUid)),
       '...and gets a home under users/ rather than the box\'s own');
    tmuxKill(`${ownerUid}~shell-10`);

    const proj = 'wtproj';
    tmuxKill(`${ownerUid}~claude-${proj}`);
    // The two extra URL arguments the proxy will add (phase 10b): the name
    // and a session token. Passed the way ttyd passes them — one argv each.
    const out = (() => { try {
      return execFileSync('bash', [BBTTY, `u:${ownerUid}:claude:${proj}:b:${boot}`,
        'tok:bbs_abc-DEF_123', 'name:the.owner'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`,
               WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
               BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
      });
    } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; } })();
    await sleep(400);
    ok(alive(`${ownerUid}~claude-${proj}`),
       `on a node the owner's Claude session is prefixed too (${out.split('\n')[0].slice(0, 80)})`);
    const wt = join(DIR, 'ws', '.worktrees', proj, ownerUid);
    ok(tmuxFmt(`${ownerUid}~claude-${proj}`, '#{pane_start_path}') === wt,
       `...and, not told it is the owner, works in a worktree (${wt})`);
    const branches = execFileSync('git', ['-C', join(DIR, 'ws', proj), 'worktree', 'list', '--porcelain'],
      { encoding: 'utf8' });
    ok(/branch refs\/heads\/claude\/the\.owner/.test(branches),
       '...on a branch named for the account name that rode in on the URL');
    // The transcripts directory of the node's home is a link onto the
    // share, so a conversation here is one the controller can resume.
    const nodeHome = join(HOMEDIR, 'users', ownerUid);
    ok(lstatSync(join(nodeHome, '.claude', 'projects')).isSymbolicLink()
       && readlinkSync(join(nodeHome, '.claude', 'projects')) === join(DIR, 'ws', '.claude', ownerUid, 'projects'),
       'the home\'s ~/.claude/projects is a link to the account\'s directory on the projects share');
    // ...and the walls: other accounts' transcripts denied, this one's not.
    const scopeN = JSON.parse(readFileSync(join(nodeHome, '.cache', 'builderbot', `claude-scope-${proj}.json`), 'utf8'));
    const denyN = scopeN.permissions.deny.join(' ');
    ok(denyN.includes(`Edit(${join(DIR, 'ws', '.claude', 'u_0badf00d')}/**)`)
       && !denyN.includes(`Edit(${join(DIR, 'ws', '.claude', ownerUid)}/**)`)
       && !denyN.includes(`Edit(${join(DIR, 'ws', '.claude')}/**)`),
       'another account\'s transcripts are walled off; this account\'s memories are not');
    // Told it is the owner (owner:1 on the URL), it works in the project
    // directory itself — the same tree, and so the same transcript slug,
    // as the controller's own session.
    tmuxKill(`${ownerUid}~claude-${proj}`);
    try {
      execFileSync('bash', [BBTTY, `u:${ownerUid}:claude:${proj}:b:${boot}`,
                            'tok:bbs_abc-DEF_123', 'name:the.owner', 'owner:1'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
               BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
      });
    } catch { /* the attach fails without a terminal */ }
    await sleep(400);
    ok(tmuxFmt(`${ownerUid}~claude-${proj}`, '#{pane_start_path}') === join(DIR, 'ws', proj),
       'told it is the owner, the session works in the project directory itself, as on the controller');
    const envOf = k => { try {
      return execFileSync('tmux', ['show-environment', '-t', `${ownerUid}~claude-${proj}`, k],
        { encoding: 'utf8', env: process.env }).trim();
    } catch { return ''; } };
    ok(envOf('BB_TOKEN') === 'BB_TOKEN=bbs_abc-DEF_123',
       'the session token from the URL is the session\'s BB_TOKEN');
    ok(envOf('BB_ACCOUNT_NAME') === 'BB_ACCOUNT_NAME=the.owner',
       '...and the name is in its environment for bb to use');
    // ...and nowhere ps can show it: a tmux server started by new-session
    // keeps that command's argv, -e list and all, for as long as it runs.
    const serverPid = tmuxFmt(`${ownerUid}~claude-${proj}`, '#{pid}');
    const serverArgs = (() => { try {
      return execFileSync('ps', ['-o', 'args=', '-p', serverPid], { encoding: 'utf8' }).trim();
    } catch { return '?'; } })();
    ok(/tmux/.test(serverArgs) && !/bbs_/.test(serverArgs),
       `...but not on the tmux server's command line, which every account can read (${serverArgs.slice(0, 40)})`);
    // The server's environment follows the session's — a pane inherits it —
    // minus what is one account's: the token stays per session.
    const genv = k => { try {
      return execFileSync('tmux', ['show-environment', '-g', k], { encoding: 'utf8', env: process.env }).trim();
    } catch { return ''; } };
    ok(genv('BB_CI_LOG_DIR') === 'BB_CI_LOG_DIR=/x/ci-logs' && !/bbs_/.test(genv('BB_TOKEN')),
       `the tmux server's environment is brought up to date before each session, the token excepted (${genv('BB_TOKEN') || 'no BB_TOKEN'})`);
    const launcher = readFileSync(join(HOMEDIR, 'users', ownerUid, '.cache', 'builderbot',
                                       `claude-run-${proj}.sh`), 'utf8');
    ok(/bb settings --json/.test(launcher) && /BB_TOKEN=bbs_abc-DEF_123/.test(launcher),
       'the launcher asks bb settings for the model when the prefs file is not here, and carries the token');
    // Claude Code's first-run questions are answered before it asks them:
    // a home this dashboard made has never seen the theme picker, and an
    // account with no shell could not get past it.
    const cj = JSON.parse(readFileSync(join(HOMEDIR, 'users', ownerUid, '.claude.json'), 'utf8'));
    ok(cj.hasCompletedOnboarding === true && cj.theme === 'dark'
       && cj.projects?.[wt]?.hasTrustDialogAccepted === true,
       `a fresh home starts with onboarding done, the dark theme and its own tree trusted (${JSON.stringify(cj).slice(0, 80)})`);
    // ...and a theme somebody chose is not overwritten by the next start.
    writeFileSync(join(HOMEDIR, 'users', ownerUid, '.claude.json'),
                  JSON.stringify({ ...cj, theme: 'light', projects: {} }));
    tmuxKill(`${ownerUid}~claude-${proj}`);
    try {
      execFileSync('bash', [BBTTY, `u:${ownerUid}:claude:${proj}:b:${boot}`, 'name:the.owner'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
               BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
      });
    } catch { /* the attach fails without a terminal */ }
    await sleep(300);
    const cj2 = JSON.parse(readFileSync(join(HOMEDIR, 'users', ownerUid, '.claude.json'), 'utf8'));
    ok(cj2.theme === 'light' && cj2.projects?.[wt]?.hasTrustDialogAccepted === true,
       '...the theme a person set stays theirs, and the trust is put back for the tree');
    tmuxKill(`${ownerUid}~claude-${proj}`);

    // ---- and it says so when that flag does not land ----------------------
    // hasTrustDialogAccepted is the one answer here that is not cosmetic:
    // Claude Code ignores a workspace's own permission rules until it is set
    // ("Ignoring N permissions.allow entry ... this workspace has not been
    // trusted"), so a session without it asks about every command and keeps
    // none of the answers. From the outside that reads as the project's
    // permission setting being ignored, which is exactly how it was reported.
    // Every failure here used to be swallowed.
    {
      const cjf = join(HOMEDIR, 'users', ownerUid, '.claude.json');
      const saved = readFileSync(cjf, 'utf8');
      const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`,
                    WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR, BUILDER_HOME: HOMEDIR,
                    DASHBOARD_STATE: join(DIR, 'state'), ...node };
      const runTty = () => {
        try {
          return String(execFileSync('bash',
            [BBTTY, `u:${ownerUid}:claude:${proj}:b:${boot}`, 'name:the.owner'],
            { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], env }) || '');
        } catch (e) { return String(e.stderr || '') + String(e.stdout || ''); }
      };

      // The file cannot be written: a directory where the file goes, so the
      // read fails, the fallback writes its temp file and the move over it
      // cannot land. Nothing else in the home is disturbed.
      tmuxKill(`${ownerUid}~claude-${proj}`);
      rmSync(cjf, { force: true });
      mkdirSync(cjf, { recursive: true });
      const cried = runTty();
      rmSync(cjf, { recursive: true, force: true });
      ok(/could not record .* as trusted/.test(cried)
         && /ask about every command/.test(cried),
         `the launcher says so when it cannot record the tree as trusted (${
           (cried.split('\n').find(l => /trusted/.test(l)) || 'said nothing').slice(0, 70)})`);

      // ...and when the flag was missing, was put back, and a session is
      // ALREADY running on the old answer — which cannot be told otherwise
      // and will go on asking until it restarts. That is the case somebody
      // actually meets, because /login rewrites this same file.
      writeFileSync(cjf, JSON.stringify({ hasCompletedOnboarding: true, projects: {} }));
      tmuxKill(`${ownerUid}~claude-${proj}`);
      // Started on a stand-in launcher, not a bare shell: a session under a
      // claude name whose pane is not running claude is replaced by the
      // launcher a few lines earlier, and there would be nothing left to
      // warn about.
      const stand = join(HOMEDIR, 'users', ownerUid, '.cache', 'builderbot',
                         `claude-run-${proj}.sh`);
      mkdirSync(join(HOMEDIR, 'users', ownerUid, '.cache', 'builderbot'), { recursive: true });
      writeFileSync(stand, '#!/usr/bin/env bash\nexec sleep 600\n', { mode: 0o755 });
      tmuxNew(`${ownerUid}~claude-${proj}`, join(DIR, 'ws', proj), [stand]);
      const noted = runTty();
      ok(/was not trusted/.test(noted) && /until it is restarted/.test(noted),
         `...and when it puts the flag back under a session already running, it says that session must restart (${
           (noted.split('\n').find(l => /not trusted/.test(l)) || 'said nothing').slice(0, 70)})`);
      ok(JSON.parse(readFileSync(cjf, 'utf8')).projects?.[wt]?.hasTrustDialogAccepted === true,
         '...having put it back');

      // ...and says neither of those things on an ordinary start, where the
      // flag was already there: a line printed every time is a line nobody
      // reads when it matters.
      const quiet = runTty();
      ok(!/was not trusted/.test(quiet) && !/could not record/.test(quiet),
         '...and says nothing at all when the tree was trusted already');
      tmuxKill(`${ownerUid}~claude-${proj}`);
      writeFileSync(cjf, saved);
    }

    // ---- keeping the Claude grant in step while a session runs (B100) --------
// The grant is an OAuth pair and a refresh ROTATES the refresh token, so the
// moment one machine refreshes the server retires every other copy. The sync
// itself was always right; the only thing that ever RAN it was this script,
// on a browser connection, so a session on another node sat holding a retired
// grant for hours and said "Login expired" for no reason anybody could see.
{
  const hk = mkdtempSync(join(tmpdir(), 'keeplogin-'));
  mkdirSync(join(hk, 'dashboard'));
  mkdirSync(join(hk, 'bin'));
  mkdirSync(join(hk, 'home', '.claude'), { recursive: true });
  const HOOK = join(hk, 'dashboard', 'bb-keep-login');
  writeFileSync(HOOK, readFileSync(
    new globalThis.URL('../bb-keep-login', import.meta.url).pathname, 'utf8'));
  chmodSync(HOOK, 0o755);
  // No bb beside it, so it falls back to the one on PATH — which is this
  // stub, recording rather than relaying.
  const calls = join(hk, 'calls');
  writeFileSync(join(hk, 'bin', 'bb'),
    `#!/usr/bin/env bash\nprintf '%s\\n' "$*" >> ${calls}\n`);
  chmodSync(join(hk, 'bin', 'bb'), 0o755);
  const grant = ms => writeFileSync(join(hk, 'home', '.claude', '.credentials.json'),
    JSON.stringify({ claudeAiOauth: { expiresAt: Date.now() + ms } }));
  const ran = () => { try { return readFileSync(calls, 'utf8').trim().split('\n').filter(Boolean); }
                      catch { return []; } };
  const fire = (role) => {
    try {
      execFileSync('python3', [HOOK, 'alpha', 'someone'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${join(hk, 'bin')}:${process.env.PATH}`,
               HOME: join(hk, 'home'), XDG_CACHE_HOME: join(hk, 'cache'),
               BUILDERBOT_ROLE: role },
      });
      return 0;
    } catch (e) { return e.status ?? 1; }
  };

  grant(8 * 3600 * 1000);
  ok(fire('controller') === 0 && ran().length === 0,
     'the login hook does nothing on the controller, which is where the grant already lives');
  ok(fire('node') === 0 && ran().length === 1 && /login --check/.test(ran()[0]),
     `...and on a node it runs the sync (${ran()[0] || 'nothing'})`);
  ok(fire('node') === 0 && ran().length === 1,
     '...once, not on every prompt: an access token lasts hours and this is not free');

  // ...unless the grant is nearly out, which is when being one rotation
  // behind is about to cost the session its next turn.
  grant(10 * 60 * 1000);
  ok(fire('node') === 0 && ran().length === 2,
     '...and the throttle is off entirely inside the grant\'s last half hour');

  // Nothing it can do is worth a turn. No credentials file to read, and a bb
  // that fails the way it does when the controller is away: still silent,
  // still exit 0, and the prompt goes through.
  rmSync(join(hk, 'home', '.claude', '.credentials.json'), { force: true });
  writeFileSync(join(hk, 'bin', 'bb'),
    '#!/usr/bin/env bash\necho "could not reach the controller" >&2\nexit 1\n');
  chmodSync(join(hk, 'bin', 'bb'), 0o755);
  const out = (() => { try {
      return execFileSync('python3', [HOOK, 'alpha', 'someone'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${join(hk, 'bin')}:${process.env.PATH}`,
               HOME: join(hk, 'home'), XDG_CACHE_HOME: join(hk, 'cache2'),
               BUILDERBOT_ROLE: 'node' } }) || '';
    } catch (e) { return `EXIT ${e.status}: ${e.stdout || ''}${e.stderr || ''}`; } })();
  ok(out === '',
     `a sync that could not run is silent and costs the turn nothing (${
       JSON.stringify(out)})`);
  // ...and it is stamped anyway, so a controller that is down does not turn
  // every prompt into a thirty-second wait.
  ok(existsSync(join(hk, 'cache2', 'builderbot', 'login-sync')),
     '...and still stamped, so a controller that is away is asked once, not every turn');
  rmSync(hk, { recursive: true, force: true });
}

// A token or a name in the wrong shape is dropped, not trusted: the
    // session made by this connection carries neither.
    tmuxKill(`${ownerUid}~shell-11`);
    try {
      execFileSync('bash', [BBTTY, `u:${ownerUid}:sh:11:`, 'tok:bbs_x;rm -rf', 'name:../../etc'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'),
               HOME: HOMEDIR, BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
      });
    } catch { /* the attach fails without a terminal, as everywhere in this file */ }
    await sleep(300);
    const envOf11 = k => { try {
      return execFileSync('tmux', ['show-environment', '-t', `${ownerUid}~shell-11`, k],
        { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: process.env }).trim();
    } catch { return ''; } };
    ok(alive(`${ownerUid}~shell-11`) && !/bbs_/.test(envOf11('BB_TOKEN'))
       && !/etc/.test(envOf11('BB_ACCOUNT_NAME')),
       'a token or a name in the wrong shape is dropped rather than exported');
    tmuxKill(`${ownerUid}~shell-11`);

    // The hooks a session is handed name its bundle through .bb/current, not
    // the digest it started from (B120). The settings file is read once, when
    // claude starts, so a resolved path kept an open session on the hooks it
    // began with however many deliveries followed. Run from a real
    // .bb/<digest> directory, the way a node runs it, with current pointing at it.
    {
      const bundles = join(DIR, 'store', '.bb');
      const digest = join(bundles, '0123456789abcdef');
      mkdirSync(digest, { recursive: true });
      execFileSync('cp', ['-r', join(import.meta.dirname, '..', '..'), join(digest, 'scripts')]);
      symlinkSync('0123456789abcdef', join(bundles, 'current'));
      const scopeOf = () => JSON.stringify(JSON.parse(readFileSync(join(HOMEDIR, 'users', ownerUid,
        '.cache', 'builderbot', `claude-scope-${proj}.json`), 'utf8')).hooks);
      const fromCheckout = join(realpathSync(join(import.meta.dirname, '..')), 'bb-gate');
      ok(scopeOf().includes(`${fromCheckout} ${proj} `),
         'run from a checkout, which has no .bb/current, the hooks keep the path they always had');
      tmuxKill(`${ownerUid}~claude-${proj}`);
      try {
        execFileSync('bash', [join(digest, 'scripts', 'dashboard', 'bb-tty'), `u:${ownerUid}:claude:${proj}:b:${boot}`,
                              'tok:bbs_abc-DEF_123', 'name:the.owner', 'owner:1'], {
          encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
                 BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
        });
      } catch { /* the attach fails without a terminal */ }
      await sleep(400);
      const cur = join(realpathSync(bundles), 'current', 'scripts', 'dashboard');
      const hooks = scopeOf();
      ok(hooks.includes(`${cur}/bb-gate ${proj} `) && hooks.includes(`${cur}/bb-work-note ${proj} `)
         && hooks.includes(`${cur}/bb-check-relay ${proj} `) && !hooks.includes('0123456789abcdef'),
         `run from a node's bundle, every hook names .bb/current, so a delivery reaches a session already open (${hooks.slice(0, 100)})`);
      tmuxKill(`${ownerUid}~claude-${proj}`);
      rmSync(join(DIR, 'store'), { recursive: true, force: true });
    }
  }
}

await done();
