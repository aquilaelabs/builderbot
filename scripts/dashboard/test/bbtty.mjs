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
import { ok, done, sleep, URL, DIR, tmuxKill, tmuxFmt } from './lib.mjs';
import { execFileSync } from 'child_process';
import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, readFileSync, existsSync, lstatSync, rmSync } from 'fs';
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
function connect(promptBytes){
  tmuxKill('claude-alpha');
  try {
    return execFileSync('bash', [BBTTY, `claude:alpha:b:${boot}`], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}`,
             WORKSPACE: join(DIR, 'ws'), HOME: join(DIR, 'home'),
             DASHBOARD_STATE: join(DIR, 'state'), FAKE_PROMPT: String(promptBytes) },
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
const cmd = paneCmd();
ok(cmd.length < 200 && /claude-run-alpha\.sh$/.test(cmd),
   '...because tmux was handed a launcher, not the command');
ok(launcher().length > 40000,
   '...and the launcher carries the prompt tmux could not');
const argv = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
ok(argv.includes('--append-system-prompt') && argv.length > 40000,
   '...which reaches claude whole, roadmap and all');

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
out = connect(0);
await sleep(400);
ok(/locked/.test(out) && !alive('claude-alpha'),
   'a locked project refuses a Claude session, whatever the URL asks for');
ok(/Projects card/.test(out),
   '...and says where to undo it, rather than only that it said no');

// And unlocking really lets it back in: a gate that cannot be opened again is
// a different bug, and one nobody notices until they need it.
rmSync(LOCKS, { force: true });
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
    ok(JSON.stringify(scope.hooks || {}).includes('bb-work-note'),
       '...and the settings carry the hook that records what the session touches');
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
}

await done();
