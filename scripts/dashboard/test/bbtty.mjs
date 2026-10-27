// bb-tty's Claude launch, driven directly the way a terminal runs it (its
// words as arguments, one connection) against the same private tmux server,
// with stubs standing in for `bb` and `claude`.
//
// What it is here for: tmux hands `new-session` its command in a single 16KB
// message and answers a longer one with `command too long`. The system prompt
// bb-tty appends carries the project's whole roadmap and open bugs, so it grows
// with the project, and once past that line, every Claude session on that
// project became unstartable, its terminal reconnecting into the same error
// every five seconds. The command goes through a launcher file now, and this is the test
// that says so.
import { ok, done, sleep, URL, DIR, tmuxKill, tmuxNew, tmuxFmt, takeOn, member } from './lib.mjs';
import { execFileSync } from 'child_process';
import { mkdtempSync, mkdirSync, writeFileSync, chmodSync, readFileSync, existsSync, lstatSync, readlinkSync, rmSync, statSync, symlinkSync, realpathSync, readdirSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';

// bb-tty leaves git's GIT_CONFIG_n to whoever set them, and a Claude session
// running this suite has set its own: they are not this suite's to inherit
// (B151, as settings.mjs's B146).
for (const k of Object.keys(process.env)) if (/^GIT_CONFIG_(COUNT|KEY_|VALUE_)/.test(k)) delete process.env[k];

const BBTTY = join(import.meta.dirname, '..', 'bb-tty');
// This suite must not pick up the NODE'S OWN bb-session (R35). On a node where
// the agent has installed it, `isolating()` is true, every launch below goes
// through the real helper, and it rightly refuses this file's scratch paths:
// they are not a project on the projects share. So the suite names a helper
// that is not there, and the view section further down installs its own
// stand-in and names that explicitly. Set on process.env because every spawn
// here spreads it.
process.env.BB_SESSION_BIN = join(DIR, 'no-bb-session-here');
const LAUNCHER = join(DIR, 'home', '.cache', 'builderbot', 'u', '_none', 'project', 'alpha', 'claude-run.sh');


// The boot this container is on, from the server rather than computed again
// here: the page reads it from /api/status and puts it in the terminal's URL,
// and bb-tty refuses a session whose URL names a previous run. Asking the same
// source the page asks keeps this test honest about what it is driving.
const status = await (await fetch(new global.URL('api/status', URL), {
  headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') },
})).json();
const boot = status.boot;

// Stubs, ahead of everything on PATH. `claude` has to hold the pane open (a
// command that exits takes the session with it, and the session is the thing
// being asserted) and to record what it was handed.
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
  # the order a session reads them, each kept to its share. The real assembly is
  # preamble.py and is tested against the real stores in preamble.mjs; this
  # stands in for it so the SIZE stays the thing these cases control.
  # Nothing at all when asked for it: what a controller that is not answering
  # looks like from here, which is the case the session must not start silently
  # on (B160).
  preamble) [ "\${FAKE_NO_PREAMBLE:-0}" = 1 ] && exit 0
            [ "\${2:-}" = --json ] && FAKE_PROMPT="\${FAKE_PROMPT:-0}" python3 -c '
import json, os
n = int(os.environ.get("FAKE_PROMPT", "0")) // 50
parts = ["THE HOUSE RULES"]
if n:
    parts.append("\\n".join(
        "- #%d  an item with enough words in it to be about fifty" % i for i in range(n)))
parts.append("the bugs block")
SHARE = 100000
notes = []
if len(parts) == 3 and len(parts[1].encode()) > SHARE:
    rows = parts[1].split("\\n")
    kept = SHARE // 60
    parts[1] = "\\n".join(rows[:kept]) + "\\nand %d more open." % (len(rows) - kept)
    notes = ["the roadmap part is over its share of a session prompt and leaves out %d of its %d open items"
             % (len(rows) - kept, len(rows))]
t = "\\n\\n".join(parts)
print(json.dumps({"text": t, "bytes": len(t.encode()), "parts": [], "notes": notes,
                  "name": "Alpha-Shown", "id": "P7"}))' ;;
  settings) [ "\${2:-}" = --json ] && printf '{"git_name":"Pat Tester","git_email":"pat@example.invalid","toolchains_off":[%s],"git_ready":%s}\\n' "$([ "\${BB_PROJECT:-}" = alpha ] && echo '"hexkit","flutter"')" "$([ "\${FAKE_GIT_READY:-1}" = 0 ] && echo false || echo true)" ;;
  # A brief staged with Build it, taken once, the way the controller hands
  # it over (brief.py): the file is the stage, and taking it clears it.
  brief) if [ "\${2:-}" = take ] && [ -n "\${FAKE_BRIEF:-}" ] && [ -f "$FAKE_BRIEF" ]; then
           cat "$FAKE_BRIEF"; rm -f "$FAKE_BRIEF"
         fi ;;
esac
exit 0
`);
writeFileSync(join(bin, 'claude'), `#!/usr/bin/env bash
if [ "\${1:-}" = auth ]; then
  [ -n "\${FAKE_AUTH_LOG:-}" ] && echo auth >> "\${FAKE_AUTH_LOG}"
  [ "\${2:-}" = status ] && printf '{"loggedIn":true}\\n'
  exit 0
fi
printf '%s\\0' "$@" > "${argvOut}"
# Held open for a pane; a launcher run on its own has its argv and goes.
[ -n "\${FAKE_CLAUDE_QUICK:-}" ] || sleep 60
`);
chmodSync(join(bin, 'bb'), 0o755);
chmodSync(join(bin, 'claude'), 0o755);

// One connection, the way a terminal makes one. bb-tty ends by exec'ing `tmux
// attach-session`, which fails without a terminal; by then the session either
// exists or does not, which is the whole question.
// `as` is the account the /term proxy stamps on the argument. The model and
// the effort are that account's, so the launcher has to be told whose terminal
// this is before it can find them; without one it is a terminal opened before
// accounts existed, and there is nothing of anybody's to apply.
// The pair is the SEAT's, not the project's (17 Sep), and jq is handed the
// seat bb-tty is running on. These connects carry no `u:` prefix, which is a
// terminal nobody is signed in on, so the seat is the empty one and that is
// the key the fixtures below use. A signed-in seat is settings.mjs's, which
// saves through the dialog and reads it back out of `bb settings --json`.
const SEAT = '';
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
// session at all: the operator's report was a pane filling with that line as
// its terminal reconnected into it every five seconds.
let out = connect(40000);
await sleep(400);
ok(!/command too long/.test(out),
   'a roadmap past tmux\'s 16KB command limit does not stop the session starting');
ok(alive('claude-alpha'), '...the session is really there');
// A tab coming back to a session already running attaches at once: the
// sign-in checks, the briefing and the launcher are for starting one, and
// cost every reload of a running Claude tab about two seconds (6 Oct).
{
  const authLog = join(DIR, 'auth.log');
  rmSync(authLog, { force: true });
  const before = launcher();
  try {
    execFileSync('bash', [BBTTY, `claude:alpha:b:${boot}`], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'),
             HOME: join(DIR, 'home'), DASHBOARD_STATE: join(DIR, 'state'), FAKE_AUTH_LOG: authLog } });
  } catch { /* attach needs a terminal, which this is not: it fails AT the attach */ }
  ok(!existsSync(authLog) && alive('claude-alpha') && launcher() === before,
     'a tab coming back to a running Claude session attaches at once: no sign-in check, no briefing, no launcher written');
}
// The account's commit identity rides into the session as git's environment
// (GIT_AUTHOR_* and GIT_COMMITTER_*, which outrank any user.name a
// repository carries) from bb settings --json, which the stub answers.
const genv = k => { try { return execFileSync('tmux', ['show-environment', '-t', 'claude-alpha', k], { encoding: 'utf8' }).trim(); } catch { return ''; } };
ok(genv('GIT_AUTHOR_NAME') === 'GIT_AUTHOR_NAME=Pat Tester'
   && genv('GIT_COMMITTER_EMAIL') === 'GIT_COMMITTER_EMAIL=pat@example.invalid',
   `the session carries the account's commit identity as git's environment (${genv('GIT_AUTHOR_NAME') || 'unset'})`);
// ...and beside it, the wall its own git meets at the network. There is no
// credential on a node by design, and git's answer to that names neither the
// reason nor the way out, so the session carries one that does (R69 step 4).
ok(genv('GIT_CONFIG_KEY_0') === 'GIT_CONFIG_KEY_0=credential.helper'
   && /no git credential is on this machine/.test(genv('GIT_CONFIG_VALUE_0'))
   && /bb git push/.test(genv('GIT_CONFIG_VALUE_0'))
   && genv('GIT_TERMINAL_PROMPT') === 'GIT_TERMINAL_PROMPT=0',
   `...and a credential helper that names bb git rather than asking for a username (${
     (genv('GIT_CONFIG_VALUE_0') || 'unset').slice(0, 60)})`);
// ...and git's own user.name and user.email say the same author (B5), so
// `git config user.name` agrees with the commits whatever a home's
// .gitconfig still holds.
// ...after every tree taken as the session's own (R125 step 7: a tree
// another user owns is otherwise refused as dubious).
ok(genv('GIT_CONFIG_COUNT') === 'GIT_CONFIG_COUNT=4'
   && genv('GIT_CONFIG_KEY_1') === 'GIT_CONFIG_KEY_1=safe.directory' && genv('GIT_CONFIG_VALUE_1') === 'GIT_CONFIG_VALUE_1=*'
   && genv('GIT_CONFIG_KEY_2') === 'GIT_CONFIG_KEY_2=user.name' && genv('GIT_CONFIG_VALUE_2') === 'GIT_CONFIG_VALUE_2=Pat Tester'
   && genv('GIT_CONFIG_KEY_3') === 'GIT_CONFIG_KEY_3=user.email' && genv('GIT_CONFIG_VALUE_3') === 'GIT_CONFIG_VALUE_3=pat@example.invalid',
   `...and git's user.name and user.email are the same author, every tree its own (${genv('GIT_CONFIG_VALUE_2') || 'unset'})`);
// ...and the toolchains its project's settings switch off (R77), which bb
// reads as not there and the view leaves out.
ok(genv('BB_TOOLCHAINS_OFF') === 'BB_TOOLCHAINS_OFF=hexkit flutter',
   `the session carries the toolchains its project switches off (${genv('BB_TOOLCHAINS_OFF') || 'unset'})`);
const cmd = paneCmd();
ok(cmd.length < 200 && /project\/alpha\/claude-run\.sh$/.test(cmd),
   '...because tmux was handed a launcher, not the command');
const PREF = join(DIR, 'home', '.cache', 'builderbot', 'u', '_none', 'project', 'alpha', 'preamble.txt');
const prefFile = () => existsSync(PREF) ? readFileSync(PREF, 'utf8') : '';
ok(launcher().length < 40000 && prefFile().length > 40000,
   `...and the block tmux could not carry is beside it in a file the launcher names (${prefFile().length} bytes)`);
// ...and the token beside it, where a session that has ALREADY STARTED can
// pick it up. A session outlives its twelve-hour token; the launcher is
// rewritten on every connection but a running claude keeps the environment
// it started with, so this file is the only way back for one that has been
// going longer than that (bb_token_now prefers it once BB_TOKEN is dead).
const TOKFILE = join(DIR, 'home', '.cache', 'builderbot', 'u', '_none', 'project', 'alpha', 'token');
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
    'eval "$(sed -n "/^bb_token_exp()/,/^}/p;/^bb_token_project()/,/^}/p;/^bb_token_dead()/,/^}/p;/^bb_token_now()/,/^}/p" "$1")"; bb_token_now',
    'sh', BBBIN],
    { encoding: 'utf8', env: { ...process.env, HOME: join(DIR, 'home'), BB_PROJECT: 'alpha', ...env } }).trim();
  ok(ask({ BB_TOKEN: dead }) === tokWritten,
     'bb reaches for that file the moment the token it started with has expired');
  ok(ask({ BB_TOKEN: tokWritten }) === tokWritten,
     '...and leaves a live one alone');
  // B497: `bb -p NAME` repoints BB_PROJECT at the project being read; the
  // kept copy is still found by the project the token was minted for.
  ok(ask({ BB_TOKEN: dead, BB_PROJECT: 'beta' }) === tokWritten,
     '...and finds it under bb -p too, by the project the token names, not the one being read');
  // ...and `bb token keep` is how a token gets INTO that file for a session
  // nobody is typing in. A session that is talking slides its own forward on
  // every answer it gets; one idle past twelve hours has nothing to slide it,
  // and a dead token is never renewed, so the machine it runs on is handed a
  // fresh one on its heartbeat and stores it here (R27). Both halves of where
  // that goes already live in bb, which is why the agent hands it to bb
  // rather than writing the path itself.
  const keepHome = join(DIR, 'tokkeep');
  const fresh = execFileSync('bash', [BBBIN, 'users', 'token', 'alpha'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: join(DIR, 'state'),
                               WORKSPACE: join(DIR, 'ws') } }).trim();
  execFileSync('bash', [BBBIN, 'token', 'keep'],
    { env: { ...process.env, BUILDER_HOME: keepHome, BB_ACCOUNT_UID: '', BB_TOKEN: fresh } });
  const landed = join(keepHome, '.cache', 'builderbot', 'u', '_none', 'project', 'alpha', 'token');
  ok(existsSync(landed) && readFileSync(landed, 'utf8').trim() === fresh
     && (statSync(landed).mode & 0o077) === 0,
     `bb token keep stores a token where that account's sessions read it, 0600 (${fresh.slice(0, 12)}…)`);
  ok(execFileSync('bash', ['-c',
       'eval "$(sed -n "/^bb_token_exp()/,/^}/p;/^bb_token_project()/,/^}/p;/^bb_token_dead()/,/^}/p;/^bb_token_now()/,/^}/p" "$1")"; bb_token_now',
       'sh', BBBIN],
       { encoding: 'utf8', env: { ...process.env, HOME: keepHome, BB_PROJECT: 'alpha',
                                  BB_TOKEN: dead } }).trim() === fresh,
     '...and a session whose own token has died reaches for exactly that');
}
const argv = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
// In a FILE now, not in the argument: --append-system-prompt-file has no
// MAX_ARG_STRLEN to run into, so what a project keeps is what its sessions
// read. The argument is the path; the block is what that path holds.
const prefPath = (argv.split('\0').find(a => /preamble\.txt$/.test(a)) || '');
const pref = prefPath && existsSync(prefPath) ? readFileSync(prefPath, 'utf8') : '';
ok(argv.includes('--append-system-prompt-file') && prefPath && pref.length > 40000,
   `...which reaches claude whole, roadmap and all, in a file (${pref.length} bytes)`);
// The session is named as the briefing names the project, its shown name
// and its id, never its folder: that is what the Claude app lists it under.
const rcName = argv.split('\0')[argv.split('\0').indexOf('--remote-control') + 1];
ok(rcName === 'Alpha-Shown (P7)', `...and is named for Remote Control as the project is shown, with its id (${rcName})`);
// The operator's rules go in front of the list: how they want this worked on
// before what there is to work on. Asserted by ORDER, not presence, since
// either would be "in" the block.
ok(pref.indexOf('THE HOUSE RULES') >= 0
   && pref.indexOf('THE HOUSE RULES') < pref.indexOf('the bugs block'),
   '...with the house rules ahead of the roadmap and the bugs');

// Every session pays for the whole block, so a part past its share says
// less (share.py), says so, and the session still starts, with the parts
// after it all there.
out = connect(250000);
await sleep(400);
ok(alive('claude-alpha'), 'a roadmap past what a session should be asked to read still starts');
ok(/the roadmap part is over its share/.test(out) && /leaves out \d+ of its \d+ open items/.test(out),
   '...whoever opened the terminal is told what it left out');
ok(/and \d+ more open\./.test(prefFile()) && prefFile().includes('the bugs block'),
   '...and the prompt says so where the list stops, with the bugs after it still there');

// The ordinary case still goes through the same path, so it is the one that
// gets exercised rather than a fallback nobody reaches until a list grows.
out = connect(0);
await sleep(400);
ok(alive('claude-alpha') && /project\/alpha\/claude-run\.sh$/.test(paneCmd()),
   'a project with no roadmap starts the same way');

// A locked project. Enforced HERE rather than by graying the button out,
// because a terminal's URL can be asked for directly and a rule only the page honors
// is a suggestion, the same reason `excluded` is checked in this script.
const LOCKS = join(DIR, 'state', 'locked-projects.json');
// An administrator's lock (R119), which holds everybody out, read from the
// file: this suite's bb does not answer `bb settings`, so the file decides.
writeFileSync(LOCKS, JSON.stringify({ alpha: { by: 'u_0000aaaa', admin: true } }));
const refusedAt = Date.now();
out = connect(0);
const refusedIn = Date.now() - refusedAt;
await sleep(400);
ok(/locked/.test(out) && !alive('claude-alpha'),
   'a locked project refuses a Claude session, whatever the URL asks for');
// A refusal holds the terminal open for ten seconds so the browser can show
// the reason: the terminal closes the moment this exits. Only when
// something is holding one: called from here, with stderr on a pipe, there is
// nobody to show it to, and five tests in this suite were paying it.
ok(refusedIn < 5000,
   `...promptly, rather than pausing for a terminal nobody is holding open (${refusedIn}ms)`);
ok(/card's menu/.test(out) && /locked by its owner/.test(out),
   '...and says whose lock it is and where it is lifted, rather than only that it said no');

// A briefing that could not be fetched is said out loud rather than started on.
// The empty answer used to be an ordinary state, a project with nothing on its
// lists, so it was allowed through in silence; since the briefing joined the
// block, empty means the controller did not answer, and a session that starts
// anyway knows none of the house rules, the roadmap, the open bugs or the
// machine it is on. It still STARTS, because a briefing nobody can fetch is not
// a reason to leave somebody without a terminal (B160).
rmSync(LOCKS, { force: true });
out = connect(0, { FAKE_NO_PREAMBLE: '1' });
await sleep(400);
ok(/could not fetch this session's briefing/.test(out) && /starts with none/.test(out),
   'a briefing the controller did not answer for is said out loud, not passed over');
ok(alive('claude-alpha'),
   '...and the session starts anyway, because that is not a reason to refuse a terminal');
try { execFileSync('tmux', ['kill-session', '-t', 'claude-alpha'], { env: { ...process.env, TMUX: '' } }); } catch { /* none */ }

// No author, no session: an account with no name and email for commits is
// told to fill in its Profile, here as well as on the ghosted button, for
// the same reason as every other refusal in this file: the URL is reachable.
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
  { users: { [SEAT]: { alpha: { model: 'sonnet', effort: 'xhigh' } } } }));
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
  { users: { [SEAT]: { alpha: { model: '--dangerously-skip-permissions', effort: 'max' } } } }));
connect(0);
await sleep(400);
a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
ok(!/dangerously/.test(a) && /--effort\0max\0/.test(a),
   'a model the tables do not know is dropped, and the valid half still goes');

// --respawn is how the dashboard restarts a session onto a changed setting:
// the same launcher, re-reading the file and resuming what was running.
writeFileSync(join(DIR, 'state', 'claude-prefs.json'), JSON.stringify(
  { users: { [SEAT]: { alpha: { model: 'opus', effort: 'low' } } } }));
// Named as Claude Code names a tree's folder, every character that is not a
// letter or a digit a dash: the temp directory's dot made the slashes-only
// name the respawn read a folder Claude never writes (B348).
const tdir = join(DIR, 'home', '.claude', 'projects',
                  join(DIR, 'ws', 'alpha').replace(/[^A-Za-z0-9]/g, '-'));
mkdirSync(tdir, { recursive: true });
writeFileSync(join(tdir, 'old-one.jsonl'), '');
await sleep(1100);                       // ls -t sorts by mtime, at 1s here
writeFileSync(join(tdir, 'the-live-one.jsonl'), '');
try {
  execFileSync('timeout', ['5', 'bash', LAUNCHER, '--respawn'], {
    encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, FAKE_CLAUDE_QUICK: '1' },
  });
} catch { /* a stub that hangs is ended by the timeout, and its argv still read */ }
a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
ok(/--model\0opus\0/.test(a) && /--effort\0low\0/.test(a),
   'a respawn re-reads the setting rather than repeating the one it started on');
ok(/--resume\0the-live-one\0/.test(a),
   '...and resumes the newest transcript, so the conversation continues');
rmSync(join(DIR, 'state', 'claude-prefs.json'), { force: true });

// ---- a new project's brief, handed to its first session once -------------------
// Build it stages the brief; bb-tty takes it as it makes a NEW session and
// leaves it beside the launcher, whose first exec gives it to claude as the
// first prompt, after `--` since a brief can open with a dash, and removes it.
// A respawn onto a changed model never sends it again (brief.py).
{
  const staged = join(DIR, 'brief-staged');
  const BRIEF = '- a planner for armor stats\n\n"quoted" and $HOME, as typed';
  writeFileSync(staged, BRIEF + '\n');
  connect(0, { FAKE_BRIEF: staged });
  await sleep(400);
  a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
  const args = a.split('\0').filter(Boolean);
  ok(args[args.length - 2] === '--' && args[args.length - 1] === BRIEF && !existsSync(staged),
     `a new session is handed the staged brief as its first prompt, after --, verbatim (${JSON.stringify(args.slice(-2)).slice(0, 80)})`);
  ok(!existsSync(join(DIR, 'home', '.cache', 'builderbot', 'u', '_none', 'project', 'alpha', 'first-prompt.txt')),
     '...and the copy the launcher read is gone once it has');
  try {
    execFileSync('timeout', ['5', 'bash', LAUNCHER, '--respawn'], {
      encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, FAKE_CLAUDE_QUICK: '1' },
    });
  } catch { /* a stub that hangs is ended by the timeout, and its argv still read */ }
  a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
  ok(!a.includes('armor stats'), 'a respawn of that session is not handed the brief again');
  connect(0);
  await sleep(400);
  a = existsSync(argvOut) ? readFileSync(argvOut, 'utf8') : '';
  ok(!a.includes('armor stats') && !/\0--\0/.test(a), '...nor is the next session, with nothing staged');
}

tmuxKill('claude-alpha');
// ---- a home and a shell of one's own (roadmap #26) --------------------------
// The dashboard's /term proxy stamps the argument with the account it
// authenticated (`u:<uid>:…`), and this is the half that acts on it: a shell
// runs in that account's home and under a name nobody else attaches to.
//
// The OWNER is deliberately the exception on both counts (they keep
// /home/builder and the bare session names), because a box with one operator
// is every box until somebody adds a second account, and an upgrade that
// renamed everything under them would be a cost paid by everyone for a case
// most installs never reach.
{
  const HOMEDIR = join(DIR, 'home');
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const shell = (arg, extra = {}, more = []) => {
    try {
      return execFileSync('bash', [BBTTY, arg, ...more], {
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
  // it, so this makes its own project with one: the fixtures are git init'd
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
    await takeOn(proj);                  // dropped in by hand, so the owner takes it on (R135)

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
       'a second account opens its own alongside it: two at once, not one');
    const wt = join(DIR, 'ws', '.worktrees', proj, other);
    ok(tmuxFmt(`${other}~claude-${proj}`, '#{pane_start_path}') === wt,
       `...in a worktree of its own rather than the same tree (${wt})`);
    ok(existsSync(join(wt, '.git')) && existsSync(join(wt, 'README.md')),
       '...which is a real checkout, sharing the project\'s one .git');
    const branch = git(['worktree', 'list', '--porcelain']);
    ok(/branch refs\/heads\/claude\//.test(branch),
       `...on a branch of its own, so the work merges rather than collides (${
          (branch.match(/branch \S+/g) || []).join(", ")})`);

    // ---- another coding agent beside Claude (R95 step 4) -------------------
    // Codex CLI and Copilot CLI stood in for: a session of each starts from
    // its own argument, in a tree of its own beside the owner's Claude one,
    // handed the same briefing the way each reads instructions.
    {
      const cxArgv = join(bin, 'codex-argv'), cpArgv = join(bin, 'copilot-argv');
      writeFileSync(join(bin, 'codex'), `#!/usr/bin/env bash
if [ "\${1:-}" = login ] && [ "\${2:-}" = status ]; then
  if [ -n "\${FAKE_CODEX_OUT:-}" ]; then echo "Not logged in"; exit 1; fi
  echo "Logged in using ChatGPT"; exit 0
fi
# Its help, which the launcher reads for the hook-trust flag, as 0.163.0's;
# with codex-164 beside it, as 0.164.0's: --no-daemon too, and an app server
# whose hooks/list names BuilderBot's hook in the account's hooks.json (B284).
if [ "\${1:-}" = --help ]; then
  echo "  --dangerously-bypass-hook-trust  run hooks without review"
  [ -f "${bin}/codex-164" ] && echo "  --no-daemon  run without the shared background server"
  exit 0
fi
if [ "\${1:-}" = app-server ]; then
  [ -f "${bin}/codex-164" ] || exit 2
  h="\${CODEX_HOME:-$HOME/.codex}/hooks.json"
  while read -r l; do case "$l" in *'"id": 2'*|*'"id":2'*)
    printf '{"id":2,"result":{"data":[{"hooks":[{"key":"%s:pre_tool_use:0:0","sourcePath":"%s","command":"/x/bb-agent-hook codex pre","currentHash":"sha256:0abc","trustStatus":"untrusted"},{"key":"%s:session_start:0:0","sourcePath":"%s","command":"echo theirs","currentHash":"sha256:0def","trustStatus":"untrusted"}]}]}}\n' "$h" "$h" "$h" "$h" ;;
  esac; done
  exit 0
fi
printf '%s\\0' "$@" > "${cxArgv}"
sleep 60
`, { mode: 0o755 });
      writeFileSync(join(bin, 'copilot'), `#!/usr/bin/env bash
printf '%s\\0' "$@" > "${cpArgv}"
printf '%s' "\${COPILOT_CUSTOM_INSTRUCTIONS_DIRS:-}" > "${cpArgv}.dirs"
sleep 60
`, { mode: 0o755 });
      tmuxKill(`codex-${proj}`); tmuxKill(`copilot-${proj}`);
      const refused = shell(`u:${ownerUid}:codex:${proj}:b:${boot}`, { FAKE_CODEX_OUT: '1' });
      ok(/not signed in to ChatGPT/.test(refused) && /Agents page/.test(refused) && !alive(`codex-${proj}`),
         `signed out of ChatGPT, a Codex session is refused with where to sign in (${refused.trim().split('\n')[0]})`);
      shell(`u:${ownerUid}:codex:${proj}:b:${boot}`);
      await sleep(400);
      ok(alive(`codex-${proj}`) && alive(`claude-${proj}`),
         'the owner opens a Codex session beside their Claude one on the same project: two agents at once');
      const cwt = join(DIR, 'ws', '.worktrees', proj, `${ownerUid}-codex`);
      ok(tmuxFmt(`codex-${proj}`, '#{pane_start_path}') === cwt && existsSync(join(cwt, 'README.md')),
         `...in a worktree of its own, not the project directory the Claude session is in (${cwt})`);
      ok(/branch refs\/heads\/codex\//.test(git(['worktree', 'list', '--porcelain'])),
         '...on a codex/ branch of its own, so the two meet through git as two people do');
      ok(/project\/wtproj\/codex-run\.sh$/.test(tmuxFmt(`codex-${proj}`, '#{pane_start_command}')),
         '...started through a launcher named for its agent');
      const cx = existsSync(cxArgv) ? readFileSync(cxArgv, 'utf8').split('\0') : [];
      const di = cx.find(a => a.startsWith('developer_instructions=')) || '';
      let said = '';
      try { said = JSON.parse(di.slice('developer_instructions='.length)); } catch { said = ''; }
      ok(cx[0] === '--no-alt-screen' && cx.includes('-c') && cx.includes('--dangerously-bypass-hook-trust') && /THE HOUSE RULES/.test(said),
         `...handed the briefing as developer instructions, added to Codex's own (${cx.slice(0, 2).join(' ')} ${di.slice(0, 40)})`);
      const toml = existsSync(join(HOMEDIR, '.codex', 'config.toml')) ? readFileSync(join(HOMEDIR, '.codex', 'config.toml'), 'utf8') : '';
      ok(toml.includes(`[projects."${cwt}"]`) && /trust_level = "trusted"/.test(toml),
         '...and its tree answered as trusted, so its first run asks nothing a read-only console cannot answer');
      // A tab coming back to it puts the answer back if it went, and says
      // the running session started without it, as Claude's does (R95 step 19).
      const cxToml = join(HOMEDIR, '.codex', 'config.toml');
      writeFileSync(cxToml, toml.replace(`[projects."${cwt}"]\ntrust_level = "trusted"\n`, ''));
      const cxNoted = shell(`u:${ownerUid}:codex:${proj}:b:${boot}`);
      ok(/was not trusted in .*config\.toml/.test(cxNoted) && /until it is restarted/.test(cxNoted)
         && readFileSync(cxToml, 'utf8').includes(`[projects."${cwt}"]`),
         `...and a tab coming back to it puts its trust back and says the running session must restart (${
           (cxNoted.split('\n').find(l => /not trusted/.test(l)) || 'said nothing').slice(0, 70)})`);
      ok(!/was not trusted/.test(shell(`u:${ownerUid}:codex:${proj}:b:${boot}`)),
         '...and says nothing when it was there already');
      // On a Codex that can say which hooks it has (0.164.0), BuilderBot's own
      // are trusted for the launch by the hash it reports, and the bypass
      // flag and its warning are gone, as is the shared server's (B284).
      writeFileSync(join(bin, 'codex-164'), '');
      tmuxKill(`codex-${proj}`);
      shell(`u:${ownerUid}:codex:${proj}:b:${boot}`);
      await sleep(1500);
      const cx164 = existsSync(cxArgv) ? readFileSync(cxArgv, 'utf8').split('\0') : [];
      const hs = cx164.find(x => x.startsWith('hooks.state=')) || '';
      ok(cx164.includes('--no-daemon') && /pre_tool_use:0:0"=\{trusted_hash="sha256:0abc"\}/.test(hs)
         && !hs.includes('session_start') && !cx164.includes('--dangerously-bypass-hook-trust'),
         `...and on a Codex that lists its hooks, BuilderBot's own are trusted by their hash, a person's left alone, with no bypass flag and no shared server (${hs.slice(0, 60)}...)`);
      rmSync(join(bin, 'codex-164'));
      tmuxKill(`codex-${proj}`);
      shell(`u:${ownerUid}:codex:${proj}:b:${boot}`);
      await sleep(400);
      // Its guards are its own hooks (R95 step 6): BuilderBot's, for every
      // event a Claude session has them on, in the account's hooks file.
      const hk = existsSync(join(HOMEDIR, '.codex', 'hooks.json')) ? JSON.parse(readFileSync(join(HOMEDIR, '.codex', 'hooks.json'), 'utf8')) : {};
      const cmdOf = ev => (hk.hooks?.[ev] || []).flatMap(e => e.hooks || []).map(h => h.command).join(' ');
      ok(/bb-agent-hook codex pre$/.test(cmdOf('PreToolUse')) && /bb-agent-hook codex prompt$/.test(cmdOf('UserPromptSubmit'))
         && /bb-agent-hook codex stop$/.test(cmdOf('Stop')) && /bb-agent-hook codex asking$/.test(cmdOf('PermissionRequest')),
         `...its guards are Codex's own hooks, written into the account's hooks.json (${Object.keys(hk.hooks || {}).join(', ')})`);
      const cxRun = readFileSync(join(HOMEDIR, '.cache', 'builderbot', 'u', ownerUid, 'project', proj, 'codex-run.sh'), 'utf8');
      ok(/export BB_AGENT=codex/.test(cxRun) && /export BB_AGENT_WHO=/.test(cxRun),
         '...and the launcher names the agent and the account its hooks act for');
      // The model and effort picked at Start ride the argument, each held
      // to Codex's own list (R95 step 9).
      tmuxKill(`codex-${proj}`);
      shell(`u:${ownerUid}:codex:${proj}:m:gpt-5.5:e:high:b:${boot}`);
      await sleep(400);
      const cx2 = existsSync(cxArgv) ? readFileSync(cxArgv, 'utf8').split('\0') : [];
      const mi = cx2.indexOf('-m');
      ok(alive(`codex-${proj}`) && mi >= 0 && cx2[mi + 1] === 'gpt-5.5' && cx2.includes('model_reasoning_effort="high"'),
         `a model and an effort picked at Start reach Codex as its own flags (${cx2.slice(0, 6).join(' ')})`);
      // A respawn onto a changed setting goes on with the conversation, as
      // Claude's resumes its newest transcript (R95 step 19).
      const respawn = ag => {
        try {
          execFileSync('timeout', ['5', 'bash', join(HOMEDIR, '.cache', 'builderbot', 'u', ownerUid, 'project', proj, `${ag}-run.sh`), '--respawn'],
            { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, HOME: HOMEDIR, PATH: `${bin}:${process.env.PATH}` } });
        } catch { /* the stub sleeps; the timeout ends it and its argv is still read */ }
        return (existsSync(join(bin, `${ag}-argv`)) ? readFileSync(join(bin, `${ag}-argv`), 'utf8') : '').split('\0');
      };
      const rcx = respawn('codex');
      ok(rcx.includes('resume') && rcx[rcx.indexOf('resume') + 1] === '--last',
         `...and a respawn resumes Codex's newest conversation in its folder (${rcx.slice(-4).join(' ')})`);
      // A Codex conversation resumes in Codex (R95 step 8): its kept log is
      // put back where Codex looks for it, and Codex is told to resume it.
      tmuxKill(`codex-${proj}`);
      {
        const sid = '0199aaaa-bbbb-cccc-dddd-eeeeffff0042';
        const kd = join(HOMEDIR, '.claude', 'projects', cwt.replace(/[^A-Za-z0-9]/g, '-'), 'codex');
        mkdirSync(kd, { recursive: true });
        writeFileSync(join(kd, `${sid}.jsonl`), '{"type":"session_meta","payload":{}}\n');
        shell(`u:${ownerUid}:codex:${proj}:r:${sid}:b:${boot}`);
        await sleep(400);
        const rx = existsSync(cxArgv) ? readFileSync(cxArgv, 'utf8').split('\0') : [];
        const back = execFileSync('find', [join(HOMEDIR, '.codex', 'sessions'), '-name', `rollout-*-${sid}.jsonl`], { encoding: 'utf8' }).trim();
        ok(alive(`codex-${proj}`) && rx.includes('resume') && rx[rx.indexOf('resume') + 1] === sid && back,
           `a kept Codex conversation resumes in Codex, put back where Codex keeps its own (${rx.slice(0, 4).join(' ')})`);
        tmuxKill(`codex-${proj}`);
        const none = shell(`u:${ownerUid}:codex:${proj}:r:0199aaaa-0000-0000-0000-000000000000:b:${boot}`);
        ok(/No ChatGPT conversation/.test(none) && !alive(`codex-${proj}`), '...and one not kept here opens nothing, saying so');
      }
      const odd = shell(`u:${ownerUid}:codex:${proj}:m:opus;rm:b:${boot}`);
      ok(/Not a model ChatGPT offers here/.test(odd) && !alive(`codex-${proj}`),
         '...and a model not on its list opens nothing');
      // A second session of one agent on one project is a slot of its own
      // (R143): its own name, launcher, tree and branch, the first untouched;
      // the owner's second Claude is a worktree too, the project directory
      // staying the first's.
      shell(`u:${ownerUid}:codex:${proj}:b:${boot}`);
      shell(`u:${ownerUid}:codex:${proj}:s:2:b:${boot}`);
      shell(`u:${ownerUid}:claude:${proj}:s:2:b:${boot}`);
      await sleep(600);
      const cwt2 = `${cwt}-2`, clt2 = join(DIR, 'ws', '.worktrees', proj, `${ownerUid}-2`);
      const cx2Run = join(HOMEDIR, '.cache', 'builderbot', 'u', ownerUid, 'project', proj, 'codex-2-run.sh');
      const wts = git(['worktree', 'list', '--porcelain']);
      ok(alive(`codex-${proj}`) && alive(`codex-${proj}~2`) && tmuxFmt(`codex-${proj}~2`, '#{pane_start_path}') === cwt2
         && /refs\/heads\/codex\/[^\n]*-2\n/.test(wts + '\n'),
         `a second Codex session on the project is its own slot: codex-${proj}~2 beside the first, in ${cwt2} on a codex/NAME-2 branch`);
      ok(existsSync(cx2Run) && /export BB_SLOT=2/.test(readFileSync(cx2Run, 'utf8'))
         && /export BB_SLOT=1/.test(readFileSync(join(HOMEDIR, '.cache', 'builderbot', 'u', ownerUid, 'project', proj, 'codex-run.sh'), 'utf8'))
         && /codex-2-run\.sh$/.test(tmuxFmt(`codex-${proj}~2`, '#{pane_start_command}')),
         '...through a launcher of its own that names its slot to its hooks, the first slot\'s left as it was');
      ok(alive(`claude-${proj}~2`) && tmuxFmt(`claude-${proj}~2`, '#{pane_start_path}') === clt2
         && tmuxFmt(`claude-${proj}`, '#{pane_start_path}') === join(DIR, 'ws', proj),
         `...and the owner's second Claude works in a worktree (${clt2}), the project directory staying the first's`);
      const noSlot = shell(`u:${ownerUid}:codex:${proj}:s:0:b:${boot}`);
      ok(/Not a slot/.test(noSlot), '...and a slot out of range opens nothing, saying so');
      tmuxKill(`codex-${proj}~2`); tmuxKill(`claude-${proj}~2`);
      // ...put away again, so the trees counted below are the ones they were.
      for (const t of [cwt2, clt2]) try { git(['worktree', 'remove', '--force', t]); } catch { /* not made */ }
      // Copilot: no status verb of its own, so the login its config
      // remembers is what says it is signed in.
      rmSync(join(HOMEDIR, '.copilot'), { recursive: true, force: true });
      const cpRefused = shell(`u:${ownerUid}:copilot:${proj}:b:${boot}`);
      ok(/not signed in to Copilot/.test(cpRefused) && !alive(`copilot-${proj}`),
         'a Copilot session with no GitHub login remembered is refused the same way');
      mkdirSync(join(HOMEDIR, '.copilot'), { recursive: true });
      // As Copilot CLI 1.0.103 writes it: two // lines over the JSON (B282).
      const cpHead = '// User settings belong in settings.json.\n// This file is managed automatically.\n';
      writeFileSync(join(HOMEDIR, '.copilot', 'config.json'), cpHead + JSON.stringify({ lastLoggedInUser: { host: 'https://github.com', login: 'octo' } }));
      shell(`u:${ownerUid}:copilot:${proj}:b:${boot}`);
      await sleep(400);
      const cp = existsSync(cpArgv) ? readFileSync(cpArgv, 'utf8').split('\0') : [];
      const dirs = existsSync(`${cpArgv}.dirs`) ? readFileSync(`${cpArgv}.dirs`, 'utf8') : '';
      ok(alive(`copilot-${proj}`) && cp[0] === '--no-auto-update',
         `signed in, a Copilot session starts, its own updater off (${cp.slice(0, 1).join(' ')})`);
      const rcp = respawn('copilot');
      ok(rcp.includes('--continue'), `...and a respawn continues Copilot's newest session (${rcp.slice(-3).join(' ')})`);
      const cph = existsSync(join(HOMEDIR, '.copilot', 'hooks', 'builderbot.json'))
        ? JSON.parse(readFileSync(join(HOMEDIR, '.copilot', 'hooks', 'builderbot.json'), 'utf8')) : {};
      ok(cph.version === 1 && /bb-agent-hook copilot pre$/.test(cph.hooks?.preToolUse?.[0]?.bash || '')
         && /bb-agent-hook copilot stop$/.test(cph.hooks?.agentStop?.[0]?.bash || ''),
         `...and its guards are Copilot's own hooks, in a file of BuilderBot's in its hooks folder (${Object.keys(cph.hooks || {}).join(', ')})`);
      ok(dirs && existsSync(join(dirs, 'AGENTS.md')) && /THE HOUSE RULES/.test(readFileSync(join(dirs, 'AGENTS.md'), 'utf8'))
         && !dirs.startsWith(src),
         `...handed the briefing as an AGENTS.md in a folder of its own, outside the project's tree (${dirs})`);
      const cpRaw = readFileSync(join(HOMEDIR, '.copilot', 'config.json'), 'utf8');
      const cpConf = cpRaw.startsWith(cpHead) ? JSON.parse(cpRaw.slice(cpHead.length)) : {};
      ok((cpConf.trustedFolders || []).includes(join(DIR, 'ws', '.worktrees', proj, `${ownerUid}-copilot`))
         && cpConf.lastLoggedInUser?.login === 'octo',
         '...its tree trusted in its config, and what was there kept, its // lines too');
      // Grok Build (R95 step 21): its session token or an API key says it
      // is signed in; its briefing is appended to its prompt, Claude's hooks
      // and its own updater are off, and its guards are its own hooks.
      {
        const gkArgv = join(bin, 'grok-argv');
        writeFileSync(join(bin, 'grok'), `#!/usr/bin/env bash
printf '%s\\0' "$@" > "${gkArgv}"
printf '%s %s' "\${GROK_CLAUDE_HOOKS_ENABLED:-}" "\${GROK_DISABLE_AUTOUPDATER:-}" > "${gkArgv}.env"
sleep 60
`, { mode: 0o755 });
        tmuxKill(`grok-${proj}`);
        rmSync(join(HOMEDIR, '.grok'), { recursive: true, force: true });
        const gkRefused = shell(`u:${ownerUid}:grok:${proj}:b:${boot}`);
        ok(/not signed in to Grok/.test(gkRefused) && !alive(`grok-${proj}`),
           'a Grok session with no session token or key is refused the same way');
        mkdirSync(join(HOMEDIR, '.grok'), { recursive: true });
        writeFileSync(join(HOMEDIR, '.grok', 'auth.json'), JSON.stringify({ token: 'not-real' }));
        shell(`u:${ownerUid}:grok:${proj}:b:${boot}`);
        await sleep(400);
        const gk = existsSync(gkArgv) ? readFileSync(gkArgv, 'utf8').split('\0') : [];
        const genv = existsSync(`${gkArgv}.env`) ? readFileSync(`${gkArgv}.env`, 'utf8') : '';
        const ri = gk.indexOf('--rules');
        ok(alive(`grok-${proj}`) && ri >= 0 && /THE HOUSE RULES/.test(gk[ri + 1] || '') && genv === '0 1',
           `signed in, a Grok session starts with the briefing appended to its prompt, Claude's hooks and its own updater off (${genv})`);
        const rgk = respawn('grok');
        ok(rgk.includes('-c'), `...and a respawn goes on with Grok's newest session (${rgk.slice(-2).join(' ')})`);
        const gkh = existsSync(join(HOMEDIR, '.grok', 'hooks', 'builderbot.json'))
          ? JSON.parse(readFileSync(join(HOMEDIR, '.grok', 'hooks', 'builderbot.json'), 'utf8')) : {};
        ok(/bb-agent-hook grok pre$/.test(gkh.hooks?.PreToolUse?.[0]?.hooks?.[0]?.command || '')
           && /bb-agent-hook grok stop$/.test(gkh.hooks?.Stop?.[0]?.hooks?.[0]?.command || '') && !gkh.hooks?.Notification,
           `...its guards Grok's own hooks in a file of BuilderBot's, no asking mark among them (${Object.keys(gkh.hooks || {}).join(', ')})`);
        tmuxKill(`grok-${proj}`);
        // Kept, as its Stop hook keeps it, but never run on this node.
        const gsid = '0199cccc-0000-7000-8000-000000000009';
        const gkd = join(HOMEDIR, '.claude', 'projects', join(DIR, 'ws', '.worktrees', proj, `${ownerUid}-grok`).replace(/[^A-Za-z0-9]/g, '-'), 'grok');
        mkdirSync(gkd, { recursive: true });
        writeFileSync(join(gkd, `${gsid}.jsonl`), '{"sessionUpdate":"user_message_chunk","content":{"type":"text","text":"hi"}}\n');
        const away = shell(`u:${ownerUid}:grok:${proj}:r:${gsid}:b:${boot}`);
        ok(/not on this node/.test(away) && !alive(`grok-${proj}`), '...and a Grok conversation this node never ran opens nothing, saying so');
      }
      tmuxKill(`codex-${proj}`); tmuxKill(`copilot-${proj}`); tmuxKill(`grok-${proj}`);
      // Their trees go, so what follows counts the two people's alone.
      for (const ag of ['codex', 'copilot', 'grok']){
        try { git(['worktree', 'remove', '--force', join(DIR, 'ws', '.worktrees', proj, `${ownerUid}-${ag}`)]); } catch { /* not made */ }
      }
    }
    // TWO ACCOUNTS ON ONE PROJECT KEEP THEIR OWN CACHE (B159). Every session
    // file lives under the account's id, because on a node the cache folder is
    // one folder for everybody: without that level the second session to start
    // wrote over the first's token, and a session would then be acting as
    // another account. Asserted as two separate token files with two values.
    {
      const tok = u => join(HOMEDIR, '.cache', 'builderbot', 'u', u, 'project', proj, 'token');
      const a = existsSync(tok(ownerUid)) ? readFileSync(tok(ownerUid), 'utf8').trim() : '';
      const b = existsSync(tok(other)) ? readFileSync(tok(other), 'utf8').trim() : '';
      // Decoded and compared by the account each names: the head of every
      // token for one project is the same (it is the project's name), so a
      // prefix said nothing, and two minted in one second without an account
      // were the same token (B176).
      const whose = t => { try { return Buffer.from(t.slice(4), 'base64url').toString().split('|')[2] || ''; } catch { return ''; } };
      ok(a && b && a !== b && whose(a) === ownerUid && whose(b) === other,
         `two accounts with a session on one project keep their own token, each naming its account (${
           whose(a) || 'none'} vs ${whose(b) || 'none'})`);
      ok(!existsSync(join(HOMEDIR, '.cache', 'builderbot', 'project', proj, 'token')),
         '...and nothing is left in the shared folder they used to share');
    }

    // The scope file walls it into ITS tree and names the other one as off
    // limits: two people on one project is exactly when that has to hold.
    const scope = JSON.parse(readFileSync(
      join(HOMEDIR, '.cache', 'builderbot', 'u', other, 'project', proj, 'claude-scope.json'), 'utf8'));
    const deny = scope.permissions.deny.join(' ');
    ok(deny.includes(`Edit(${src}/**)`),
       '...with the project directory itself denied to it, being another tree');
    ok(!deny.includes(`Edit(${wt}/**)`),
       '...and its own not denied, which a blanket rule on .worktrees would have done');
    // Edit covers every writing tool, and Claude Code warns at the top of the
    // session for each Write() or NotebookEdit() rule it ignores (B285).
    ok(deny.includes('/rules.json)') && !/(Write|NotebookEdit)\(/.test(deny),
       '...and the rules file is denied by Edit alone, with no spelling Claude Code ignores and warns of');
    // ...and the memory of its own tree allowed, which Claude Code keeps
    // outside the tree: a session asked the person to approve reading a
    // memory it was updating (6 Oct).
    // The rest are the project's other repositories (BB_WORK_DIRS), which
    // this fixture has: they were never seen while the scope failed to be
    // written for a project of several (B380).
    const mem = scope.permissions.additionalDirectories || [];
    ok(mem.filter(d => /\/\.claude\/projects\//.test(d)).length === 1 && mem[0].endsWith(`/.claude/projects/${wt.replace(/[^A-Za-z0-9]/g, '-')}/memory`),
       `...and the memory of its own tree is a directory it may use without asking (${mem.join(', ')})`);
    // The scope file also carries the work hook, which is how the finer half
    // of `bb work` gets anything to report.
    ok(JSON.stringify(scope.hooks?.Stop || {}).includes('bb-check-relay'),
       'the settings file wires the Stop hook that runs a rule\'s check before the session hands back (R31)');
    ok(JSON.stringify(scope.hooks || {}).includes('bb-work-note'),
       '...and the settings carry the hook that records what the session touches');
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
       '...and does not refuse it: two worktrees editing one function is two commits, not a corruption');
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
  // client's (measured on tmux 3.4), so the HOME bb-tty exported for an
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
  // in directly: every session gets a worktree.
  {
    const node = { BUILDERBOT_ROLE: 'node', BB_CI_LOG_DIR: '/x/ci-logs', BB_CONTROLLER: URL };
    // A node's bb-tty asks the controller whose terminal it is (B166), so
    // what rides in on these URLs is real: tokens minted by the harness's own
    // server, for the owner and for two accounts made here and removed at the
    // end of the block, so no file after this one meets them: an administrator
    // (a shell, and not the owner) and a plain user (no shell at all).
    const usersPy = code => execFileSync('python3', ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location("users", ${JSON.stringify(join(REPO, 'scripts', 'dashboard', 'users.py'))})
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=${JSON.stringify(join(DIR, 'state'))}, write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
${code}`], { encoding: 'utf8' }).trim();
    const tok = (project, uid = ownerUid) =>
      usersPy(`print(u.mint_session(${JSON.stringify(project)}, uid=${JSON.stringify(uid)}))`);
    const otherUid = usersPy(`
d = u.load()
uid = u.mint_uid()
d["users"]["wt.user"] = {"uid": uid, "role": "admin", "projects": ["wtproj", "viewproj"],
                         "prefs": {"full_name": "Worktree User", "email": "wt@example.invalid"},
                         "password": u.hash_password("wt-user-pass"), "created": 0, "seen": 0}
u._save(d)
print(uid)`);
    const plainUid = usersPy(`
d = u.load()
uid = u.mint_uid()
d["users"]["plain.user"] = {"uid": uid, "role": "user", "projects": ["wtproj"],
                            "prefs": {"full_name": "Plain User", "email": "plain@example.invalid"},
                            "password": u.hash_password("plain-user-pass"), "created": 0, "seen": 0}
u._save(d)
print(uid)`);
    await member('plain.user');
    const ownerTok = tok('wtproj');
    // Another account's transcripts on the share, for the walls below.
    mkdirSync(join(DIR, 'ws', '.claude', 'u_0badf00d', 'projects'), { recursive: true });
    tmuxKill('shell-wtproj-10'); tmuxKill(`${ownerUid}~shell-wtproj-10`);
    shell(`u:${ownerUid}:sh:10:wtproj`, node, [`tok:${ownerTok}`]);
    await sleep(300);
    ok(alive(`${ownerUid}~shell-wtproj-10`) && !alive('shell-wtproj-10'),
       'on a node the owner is prefixed like everybody else: there is no owner there');
    ok(existsSync(join(HOMEDIR, 'users', ownerUid)),
       '...and gets a home under users/ rather than the box\'s own');
    tmuxKill(`${ownerUid}~shell-wtproj-10`);

    // B166: what the URL claims is not who the terminal is for. A session on
    // a node can start bb-tty itself with any words, so these are the URLs
    // it could type. The account, its name and ownership come from the controller's
    // answer to the token, and a URL the controller will not vouch for opens
    // nothing.
    {
      const shOut = (arg, extras) => shell(arg, node, extras);
      tmuxKill(`${ownerUid}~shell-wtproj-12`); tmuxKill(`${otherUid}~shell-wtproj-12`);
      const bare = shOut(`u:${ownerUid}:sh:12:wtproj`, ['name:the.owner', 'owner:1']);
      await sleep(200);
      ok(/was refused/.test(bare) && /without a session token/.test(bare)
         && !alive(`${ownerUid}~shell-wtproj-12`),
         `on a node, a terminal with no token is refused however much the URL claims (${bare.trim().slice(0, 90)})`);
      const claimed = shOut(`u:${ownerUid}:sh:12:wtproj`,
                            [`tok:${tok('wtproj', otherUid)}`, 'name:the.owner', 'owner:1']);
      await sleep(300);
      const envOf12 = k => { try {
        return execFileSync('tmux', ['show-environment', '-t', `${otherUid}~shell-wtproj-12`, k],
          { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: process.env }).trim();
      } catch { return ''; } };
      ok(alive(`${otherUid}~shell-wtproj-12`) && !alive(`${ownerUid}~shell-wtproj-12`),
         `...and one whose URL names the owner, with another account's token, opens as the token's account (${claimed.trim().slice(0, 60) || 'opened'})`);
      ok(envOf12('BB_ACCOUNT_NAME') === 'BB_ACCOUNT_NAME=wt.user' && !/=1/.test(envOf12('BB_TREE_OWNER')),
         `...named by the controller and not made the owner by owner:1 on the URL (${envOf12('BB_ACCOUNT_NAME')}, ${envOf12('BB_TREE_OWNER') || 'no owner'})`);
      tmuxKill(`${otherUid}~shell-wtproj-12`);
      const across = shOut(`u:${ownerUid}:sh:12:viewproj`, [`tok:${ownerTok}`]);
      ok(/was refused/.test(across) && /this token is for wtproj/.test(across)
         && !alive(`${ownerUid}~shell-viewproj-12`),
         `...a token for one project does not open another (${across.trim().slice(0, 90)})`);
      const nowhere = shOut(`u:${ownerUid}:sh:13:`, [`tok:${ownerTok}`]);
      ok(/was refused/.test(nowhere) && !alive(`${ownerUid}~shell-13`),
         '...and a shell that is no project\'s, which the proxy never sends to a node, is refused there');
      // The server opens an account with no shell read-only; bb-tty started
      // writable by hand does not take it either.
      const plainOut = (() => { try {
        return execFileSync('bash', [BBTTY, `u:${plainUid}:claude:wtproj:b:${boot}`, `tok:${tok('wtproj', plainUid)}`], {
          encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
                 BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node } });
      } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; } })();
      ok(/was refused/.test(plainOut) && /has no shell/.test(plainOut) && !alive(`${plainUid}~claude-wtproj`),
         `...and an account with no shell is refused the writable one, where the proxy would have sent it to the read-only twin (${plainOut.trim().slice(0, 80)})`);
      const forged = shOut(`u:${ownerUid}:sh:12:wtproj`, [`tok:${ownerTok.slice(0, -4)}AAAA`]);
      ok(/was refused/.test(forged) && !alive(`${ownerUid}~shell-wtproj-12`),
         `...as is a token whose signature is not the controller's (${forged.trim().slice(0, 80)})`);
    }

    const proj = 'wtproj';
    tmuxKill(`${otherUid}~claude-${proj}`);
    // The two extra URL arguments the proxy will add (phase 10b): the name
    // and a session token. Passed the way a terminal passes them, one argv each.
    const out = (() => { try {
      return execFileSync('bash', [BBTTY, `u:${otherUid}:claude:${proj}:b:${boot}`,
        `tok:${tok(proj, otherUid)}`, 'name:the.owner'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`,
               WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
               BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
      });
    } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; } })();
    await sleep(400);
    ok(alive(`${otherUid}~claude-${proj}`),
       `on a node an account's Claude session is prefixed (${out.split('\n')[0].slice(0, 80)})`);
    const wt = join(DIR, 'ws', '.worktrees', proj, otherUid);
    ok(tmuxFmt(`${otherUid}~claude-${proj}`, '#{pane_start_path}') === wt,
       `...and, not the owner, works in a worktree (${wt})`);
    const branches = execFileSync('git', ['-C', join(DIR, 'ws', proj), 'worktree', 'list', '--porcelain'],
      { encoding: 'utf8' });
    ok(/branch refs\/heads\/claude\/wt\.user/.test(branches),
       '...on a branch named for the account the controller named, not the URL\'s name');
    // The transcripts directory of the node's home is a link onto the
    // share, so a conversation here is one the controller can resume.
    const nodeHome = join(HOMEDIR, 'users', otherUid);
    ok(lstatSync(join(nodeHome, '.claude', 'projects')).isSymbolicLink()
       && readlinkSync(join(nodeHome, '.claude', 'projects')) === join(DIR, 'ws', '.claude', otherUid, 'projects'),
       'the home\'s ~/.claude/projects is a link to the account\'s directory on the projects share');
    // ...and the walls: other accounts' transcripts denied, this one's not.
    const scopeN = JSON.parse(readFileSync(join(nodeHome, '.cache', 'builderbot', 'u', otherUid, 'project', proj, 'claude-scope.json'), 'utf8'));
    const denyN = scopeN.permissions.deny.join(' ');
    ok(denyN.includes(`Edit(${join(DIR, 'ws', '.claude', 'u_0badf00d')}/**)`)
       && !denyN.includes(`Edit(${join(DIR, 'ws', '.claude', otherUid)}/**)`)
       && !denyN.includes(`Edit(${join(DIR, 'ws', '.claude')}/**)`),
       'another account\'s transcripts are walled off; this account\'s memories are not');
    // The owner (the controller says so; owner:1 on the URL no longer does), works in the project
    // directory itself: the same tree, and so the same transcript slug,
    // as the controller's own session.
    tmuxKill(`${ownerUid}~claude-${proj}`);
    try {
      execFileSync('bash', [BBTTY, `u:${ownerUid}:claude:${proj}:b:${boot}`,
                            `tok:${ownerTok}`, 'name:the.owner', 'owner:1'], {
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
    ok(envOf('BB_TOKEN') === `BB_TOKEN=${ownerTok}`,
       'the session token from the URL is the session\'s BB_TOKEN');
    ok(envOf('BB_ACCOUNT_NAME') === 'BB_ACCOUNT_NAME=test',
       '...and the name in its environment is the controller\'s for that account, not the one the URL said');
    // ...and nowhere ps can show it: a tmux server started by new-session
    // keeps that command's argv, -e list and all, for as long as it runs.
    const serverPid = tmuxFmt(`${ownerUid}~claude-${proj}`, '#{pid}');
    const serverArgs = (() => { try {
      return execFileSync('ps', ['-o', 'args=', '-p', serverPid], { encoding: 'utf8' }).trim();
    } catch { return '?'; } })();
    ok(/tmux/.test(serverArgs) && !/bbs_/.test(serverArgs),
       `...but not on the tmux server's command line, which every account can read (${serverArgs.slice(0, 40)})`);
    // The server's environment follows the session's (a pane inherits it)
    // minus what is one account's: the token stays per session.
    const genv = k => { try {
      return execFileSync('tmux', ['show-environment', '-g', k], { encoding: 'utf8', env: process.env }).trim();
    } catch { return ''; } };
    ok(genv('BB_CI_LOG_DIR') === 'BB_CI_LOG_DIR=/x/ci-logs' && !/bbs_/.test(genv('BB_TOKEN')),
       `the tmux server's environment is brought up to date before each session, the token excepted (${genv('BB_TOKEN') || 'no BB_TOKEN'})`);
    const launcher = readFileSync(join(HOMEDIR, 'users', ownerUid, '.cache', 'builderbot',
                                       'u', ownerUid, 'project', proj, 'claude-run.sh'), 'utf8');
    ok(/bb settings --json/.test(launcher) && launcher.includes(`BB_TOKEN=${ownerTok}`),
       'the launcher asks bb settings for the model when the prefs file is not here, and carries the token');

    // ---- a session's view (R35) ----------------------------------------------
    // Where the node builds one, a project's session starts through sudo and
    // bb-session. Stand-ins for both record the call and run the command,
    // since the suite has no root: what is proved is what bb-tty asks for,
    // what it hands the helper, and that it refuses when the helper does.
    {
      const vb = join(DIR, 'view-bin'); mkdirSync(vb, { recursive: true });
      const calls = join(DIR, 'view-calls');
      writeFileSync(join(vb, 'sudo'), '#!/bin/sh\n[ "$1" = -n ] && shift\nexec "$@"\n', { mode: 0o755 });
      const helper = join(vb, 'bb-session');
      const helperSrc = refuse => `#!/bin/sh\nprintf '%s\\n' "$*" >> ${calls}\n`
        + `case "$1" in check) exit 0 ;; plan) ${refuse ? 'echo "bb-session: not this one" >&2; exit 2' : 'exit 0'} ;; esac\n`
        + 'while [ "$1" != -- ]; do shift; done; shift\nexec "$@"\n';
      writeFileSync(helper, helperSrc(false), { mode: 0o755 });
      const vproj = 'viewproj';
      mkdirSync(join(DIR, 'ws', vproj), { recursive: true });
      writeFileSync(join(DIR, 'ws', vproj, 'README.md'), 'x\n');   // an empty directory is not listed
      await takeOn(vproj);               // dropped in by hand, so the owner takes it on (R135)
      const vhome = join(HOMEDIR, 'users', ownerUid);
      const viewTok = tok(vproj);
      const runView = target => { try {
        return execFileSync('bash', [BBTTY, target, `tok:${viewTok}`, 'name:the.owner'], {
          encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, PATH: `${vb}:${bin}:${process.env.PATH}`, BB_SESSION_BIN: helper,
                 WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR, BUILDER_HOME: HOMEDIR,
                 DASHBOARD_STATE: join(DIR, 'state'), ...node } });
      } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; } };
      tmuxKill(`${ownerUid}~claude-${vproj}`);
      runView(`u:${ownerUid}:claude:${vproj}:b:${boot}`);
      await sleep(400);
      const vcmd = tmuxFmt(`${ownerUid}~claude-${vproj}`, '#{pane_start_command}');
      const vcache = join(vhome, '.cache', 'builderbot', 'u', ownerUid, 'project', vproj);
      const envf = join(vcache, 'session.env');
      ok(alive(`${ownerUid}~claude-${vproj}`)
         && vcmd.startsWith(`sudo -n ${helper} enter --project ${vproj} --account ${ownerUid} --home ${vhome} --cwd ${join(DIR, 'ws', vproj)} --env ${envf} -- `)
         && vcmd.endsWith(`${vcache}/claude-run.sh`),
         `on a node that builds a session's view, the Claude session starts inside it through sudo and bb-session (${vcmd.slice(0, 90)})`);
      const envRaw = existsSync(envf) ? readFileSync(envf, 'utf8') : '';
      ok(envRaw.split('\0').includes(`BB_TOKEN=${viewTok}`) && (statSync(envf).mode & 0o777) === 0o600
         && /^check$/m.test(readFileSync(calls, 'utf8')) && new RegExp(`^plan --project ${vproj} `, 'm').test(readFileSync(calls, 'utf8')),
         '...having asked the helper whether this node builds one and planned it first, with the environment in a file only the account reads');
      // The file is what the session runs with, so the project's own Gradle
      // home has to be in it: tmux's -e is overridden by it (report #54).
      const gh = envRaw.split('\0').find(l => l.startsWith('GRADLE_USER_HOME=')) || '';
      ok(gh === `GRADLE_USER_HOME=${vhome}/.cache/builderbot/u/${ownerUid}/project/${vproj}/gradle-home`,
         `...and in it the project's own Gradle home, not the account's ~/.gradle (${gh.slice(0, 90)})`);
      tmuxKill(`${ownerUid}~claude-${vproj}`);
      // The projects this one reads (prefs.reads) ride the grant: one
      // --reads each for the helper, and Claude's walls let it Read them
      // and not Edit them.
      {
        // Into the store itself: the dialog's endpoint knows a project by
        // the listing, which has not met a directory made a moment ago,
        // and prefs.get reads the file fresh on every grant.
        const prefsFile = join(DIR, 'state', 'claude-prefs.json');
        // What it reads and sees is its project's (R138): kept on the key
        // of the project it is in, where the settings write it.
        const projKey = () => {
          try { return Object.entries(JSON.parse(readFileSync(join(DIR, 'state', 'project-repos.json'), 'utf8')).projects || {})
                  .find(([, r]) => (r.members || []).includes(vproj))?.[0] || vproj; }
          catch { return vproj; }
        };
        const setReads = reads => {
          const d = existsSync(prefsFile) ? JSON.parse(readFileSync(prefsFile, 'utf8')) : { projects: {}, users: {} };
          d.projects = d.projects || {};
          d.projects[projKey()] = { ...(d.projects[projKey()] || {}), reads };
          writeFileSync(prefsFile, JSON.stringify(d));
        };
        setReads(['alpha']);
        runView(`u:${ownerUid}:claude:${vproj}:b:${boot}`);
        await sleep(400);
        const rcmd = tmuxFmt(`${ownerUid}~claude-${vproj}`, '#{pane_start_command}');
        const scope = JSON.parse(readFileSync(join(vcache, 'claude-scope.json'), 'utf8'));
        const deny = scope.permissions.deny;
        ok(rcmd.includes(` --cwd ${join(DIR, 'ws', vproj)} --reads alpha --env `)
           && !deny.includes(`Read(${join(DIR, 'ws', 'alpha')}/**)`) && deny.includes(`Edit(${join(DIR, 'ws', 'alpha')}/**)`)
           && deny.includes(`Read(${join(DIR, 'ws', 'beta')}/**)`),
           `a project the session reads goes to the helper as --reads and stays a wall to Edit alone (${rcmd.slice(rcmd.indexOf('--cwd'), rcmd.indexOf('--cwd') + 160)}; BB_READS ${
             readFileSync(envf, 'utf8').split('\0').find(l => l.startsWith('BB_READS=')) || 'unset'}; deny ${deny.filter(d => /alpha|beta/.test(d)).join(' ')})`);
        tmuxKill(`${ownerUid}~claude-${vproj}`);
        setReads([]);
        // The places on the node it is shown (prefs.sees) ride the grant
        // the same way, one --sees each (B378), to a helper that takes
        // the word: one from before the setting is asked first and gets
        // none, since it would refuse the word and start no session.
        const setSees = sees => {
          const d = existsSync(prefsFile) ? JSON.parse(readFileSync(prefsFile, 'utf8')) : { projects: {}, users: {} };
          d.projects = d.projects || {};
          d.projects[projKey()] = { ...(d.projects[projKey()] || {}), sees };
          writeFileSync(prefsFile, JSON.stringify(d));
        };
        setSees(['/mnt/media', '/srv/samples']);
        runView(`u:${ownerUid}:claude:${vproj}:b:${boot}`);
        await sleep(400);
        const scmd = tmuxFmt(`${ownerUid}~claude-${vproj}`, '#{pane_start_command}');
        ok(scmd.includes(` --cwd ${join(DIR, 'ws', vproj)} --sees /mnt/media --sees /srv/samples --env `),
           `a place the project is set to see goes to the helper as --sees (${scmd.slice(scmd.indexOf('--cwd'), scmd.indexOf('--cwd') + 160)})`);
        tmuxKill(`${ownerUid}~claude-${vproj}`);
        writeFileSync(helper, helperSrc(false), { mode: 0o755 });
        setSees([]);
      }
      writeFileSync(helper, helperSrc(true), { mode: 0o755 });
      tmuxKill(`${ownerUid}~shell-${vproj}`);
      const refused = runView(`u:${ownerUid}:shell:${vproj}`);
      await sleep(300);
      ok(/could not for this one/.test(refused) && /not this one/.test(refused) && !alive(`${ownerUid}~shell-${vproj}`),
         `...and a project shell the helper cannot plan a view for is refused with its reason, never opened without one (${refused.replace(/\s+/g, ' ').slice(0, 90)})`);
    }
    const otherTok = tok(proj, otherUid);
    // Claude Code's first-run questions are answered before it asks them:
    // a home this dashboard made has never seen the theme picker, and an
    // account with no shell could not get past it.
    const cj = JSON.parse(readFileSync(join(HOMEDIR, 'users', otherUid, '.claude.json'), 'utf8'));
    ok(cj.hasCompletedOnboarding === true && cj.theme === 'dark'
       && cj.projects?.[wt]?.hasTrustDialogAccepted === true,
       `a fresh home starts with onboarding done, the dark theme and its own tree trusted (${JSON.stringify(cj).slice(0, 80)})`);
    // ...and a theme somebody chose is not overwritten by the next start.
    writeFileSync(join(HOMEDIR, 'users', otherUid, '.claude.json'),
                  JSON.stringify({ ...cj, theme: 'light', projects: {} }));
    tmuxKill(`${otherUid}~claude-${proj}`);
    try {
      execFileSync('bash', [BBTTY, `u:${otherUid}:claude:${proj}:b:${boot}`, `tok:${otherTok}`, 'name:the.owner'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
               BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
      });
    } catch { /* the attach fails without a terminal */ }
    await sleep(300);
    const cj2 = JSON.parse(readFileSync(join(HOMEDIR, 'users', otherUid, '.claude.json'), 'utf8'));
    ok(cj2.theme === 'light' && cj2.projects?.[wt]?.hasTrustDialogAccepted === true,
       '...the theme a person set stays theirs, and the trust is put back for the tree');
    tmuxKill(`${otherUid}~claude-${proj}`);

    // ---- and it says so when that flag does not land ----------------------
    // hasTrustDialogAccepted is the one answer here that is not cosmetic:
    // Claude Code ignores a workspace's own permission rules until it is set
    // ("Ignoring N permissions.allow entry ... this workspace has not been
    // trusted"), so a session without it asks about every command and keeps
    // none of the answers. From the outside that reads as the project's
    // permission setting being ignored, which is exactly how it was reported.
    // Every failure here used to be swallowed.
    {
      const cjf = join(HOMEDIR, 'users', otherUid, '.claude.json');
      const saved = readFileSync(cjf, 'utf8');
      const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`,
                    WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR, BUILDER_HOME: HOMEDIR,
                    DASHBOARD_STATE: join(DIR, 'state'), ...node };
      const runTty = () => {
        try {
          return String(execFileSync('bash',
            [BBTTY, `u:${otherUid}:claude:${proj}:b:${boot}`, `tok:${otherTok}`, 'name:the.owner'],
            { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], env }) || '');
        } catch (e) { return String(e.stderr || '') + String(e.stdout || ''); }
      };

      // The file cannot be written: a directory where the file goes, so the
      // read fails, the fallback writes its temp file and the move over it
      // cannot land. Nothing else in the home is disturbed.
      tmuxKill(`${otherUid}~claude-${proj}`);
      rmSync(cjf, { force: true });
      mkdirSync(cjf, { recursive: true });
      const cried = runTty();
      rmSync(cjf, { recursive: true, force: true });
      ok(/could not record .* as trusted/.test(cried)
         && /ask about every command/.test(cried),
         `the launcher says so when it cannot record the tree as trusted (${
           (cried.split('\n').find(l => /trusted/.test(l)) || 'said nothing').slice(0, 70)})`);

      // ...and when the flag was missing, was put back, and a session is
      // ALREADY running on the old answer, which cannot be told otherwise
      // and will go on asking until it restarts. That is the case somebody
      // actually meets, because /login rewrites this same file.
      writeFileSync(cjf, JSON.stringify({ hasCompletedOnboarding: true, projects: {} }));
      tmuxKill(`${otherUid}~claude-${proj}`);
      // Started on a stand-in launcher, not a bare shell: a session under a
      // claude name whose pane is not running claude is replaced by the
      // launcher a few lines earlier, and there would be nothing left to
      // warn about.
      const stand = join(HOMEDIR, 'users', otherUid, '.cache', 'builderbot',
                         'u', otherUid, 'project', proj, 'claude-run.sh');
      mkdirSync(join(HOMEDIR, 'users', otherUid, '.cache', 'builderbot', 'u', otherUid, 'project', proj), { recursive: true });
      writeFileSync(stand, '#!/usr/bin/env bash\nexec sleep 600\n', { mode: 0o755 });
      tmuxNew(`${otherUid}~claude-${proj}`, join(DIR, 'ws', proj), [stand]);
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
      tmuxKill(`${otherUid}~claude-${proj}`);
      writeFileSync(cjf, saved);
    }

    // A token or a name in the wrong shape is dropped, not trusted, and on a
    // node a dropped token is no token, so nothing opens.
    tmuxKill(`${ownerUid}~shell-wtproj-11`);
    try {
      execFileSync('bash', [BBTTY, `u:${ownerUid}:sh:11:wtproj`, 'tok:bbs_x;rm -rf', 'name:../../etc'], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'),
               HOME: HOMEDIR, BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
      });
    } catch { /* the attach fails without a terminal, as everywhere in this file */ }
    await sleep(300);
    ok(!alive(`${ownerUid}~shell-wtproj-11`),
       'a token in the wrong shape is dropped, and on a node that leaves no token, so nothing opens');
    // (the name alone cannot open anything any more: it is the controller's to say)
    tmuxKill(`${ownerUid}~shell-wtproj-11`);

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
        '.cache', 'builderbot', 'u', ownerUid, 'project', proj, 'claude-scope.json'), 'utf8')).hooks);
      const fromCheckout = join(realpathSync(join(import.meta.dirname, '..')), 'bb-gate');
      ok(scopeOf().includes(`${fromCheckout} ${proj} `),
         'run from a checkout, which has no .bb/current, the hooks keep the path they always had');
      // A prompt waits for a turn on the node (turns.py) under a timeout of
      // its own, since a UserPromptSubmit hook gets thirty seconds otherwise
      // and one that runs out lets the prompt through uncounted; Stop hands
      // the turn back.
      {
        const h = JSON.parse(scopeOf());
        const prompt = (h.UserPromptSubmit || []).flatMap(g => g.hooks || []).find(x => /bb-gate --turn /.test(x.command));
        const stop = (h.Stop || []).flatMap(g => g.hooks || []).find(x => /bb-gate --turn-done /.test(x.command));
        ok(prompt && prompt.timeout > 840 && / --wait 840$/.test(prompt.command) && prompt.statusMessage
           && stop && stop.command.endsWith(`--turn-done ${proj} ${ownerUid}`),
           `a prompt asks for a turn and waits under its own timeout, and Stop hands it back (${prompt?.timeout}, ${!!stop})`);
      }
      tmuxKill(`${ownerUid}~claude-${proj}`);
      let said = '';
      try {
        execFileSync('bash', [join(digest, 'scripts', 'dashboard', 'bb-tty'), `u:${ownerUid}:claude:${proj}:b:${boot}`,
                              `tok:${ownerTok}`, 'name:the.owner', 'owner:1'], {
          encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
          env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'), HOME: HOMEDIR,
                 BUILDER_HOME: HOMEDIR, DASHBOARD_STATE: join(DIR, 'state'), ...node },
        });
      } catch (e) { said = `${e.stdout || ''}${e.stderr || ''}`; /* the attach fails without a terminal */ }
      await sleep(400);
      const cur = join(realpathSync(bundles), 'current', 'scripts', 'dashboard');
      const hooks = scopeOf();
      ok(hooks.includes(`${cur}/bb-gate ${proj} `) && hooks.includes(`${cur}/bb-work-note ${proj} `)
         && hooks.includes(`${cur}/bb-check-relay ${proj} `) && !hooks.includes('0123456789abcdef'),
         `run from a node's bundle, every hook names .bb/current, so a delivery reaches a session already open (${hooks.slice(0, 100)}; it said: ${said.trim().slice(-300)}; list ${
           JSON.stringify(Object.values(JSON.parse(readFileSync(join(DIR, 'state', 'users.json'), 'utf8')).users || {}).find(u => u.uid === ownerUid)?.projects)}; repos ${
           (() => { try { return readFileSync(join(DIR, 'state', 'project-repos.json'), 'utf8').slice(0, 300); } catch { return 'none'; } })()}; proj ${proj})`);
      tmuxKill(`${ownerUid}~claude-${proj}`);
      rmSync(join(DIR, 'store'), { recursive: true, force: true });
    }
    // B157/B163: on a node an account keeps nothing in common with the base
    // home. A link made before this is taken down so the tool makes the
    // account's own, a launcher in the base home that reached its binary
    // through this account's .local is pointed at the base home's own copy
    // first (B169), the crate cache is the account's, and Claude's updater
    // is off. Staged the way bb-sandbox had it on 18 Sep.
    {
      const ah = join(HOMEDIR, 'users', otherUid);
      mkdirSync(join(HOMEDIR, '.gradle'), { recursive: true });
      mkdirSync(join(HOMEDIR, '.local', 'share', 'claude', 'versions'), { recursive: true });
      writeFileSync(join(HOMEDIR, '.local', 'share', 'claude', 'versions', '9.9.9'), 'BIN\n', { mode: 0o755 });
      mkdirSync(join(HOMEDIR, '.local', 'bin'), { recursive: true });
      rmSync(join(HOMEDIR, '.local', 'bin', 'claude'), { force: true });
      symlinkSync(join(ah, '.local', 'share', 'claude', 'versions', '9.9.9'), join(HOMEDIR, '.local', 'bin', 'claude'));
      rmSync(join(ah, '.gradle'), { recursive: true, force: true }); rmSync(join(ah, '.local'), { recursive: true, force: true });
      symlinkSync(join(HOMEDIR, '.gradle'), join(ah, '.gradle'));
      symlinkSync(join(HOMEDIR, '.local'), join(ah, '.local'));
      tmuxKill(`${otherUid}~shell-wtproj-14`);
      shell(`u:${otherUid}:sh:14:wtproj`, { ...node, CARGO_HOME: '/store/rust/cargo' }, [`tok:${tok('wtproj', otherUid)}`]);
      await sleep(300);
      const env14 = k => { try {
        return execFileSync('tmux', ['show-environment', '-t', `${otherUid}~shell-wtproj-14`, k],
          { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: process.env }).trim();
      } catch { return ''; } };
      const genv14 = k => { try {
        return execFileSync('tmux', ['show-environment', '-g', k], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], env: process.env }).trim();
      } catch { return ''; } };
      // Gone or the account's own directory, never a link: the shell that
      // just started may already have made its own ~/.local.
      const notLinked = d => !lstatSync(join(ah, d), { throwIfNoEntry: false })?.isSymbolicLink();
      ok(notLinked('.gradle') && notLinked('.local'),
         'on a node an account\'s links into the base home are taken down, so its tools make their own (B157)');
      ok(readlinkSync(join(HOMEDIR, '.local', 'bin', 'claude')) === join(HOMEDIR, '.local', 'share', 'claude', 'versions', '9.9.9'),
         `...after the base home's launcher, which reached its binary through that account's link, is pointed at the base home's own copy (${readlinkSync(join(HOMEDIR, '.local', 'bin', 'claude')).replace(DIR, '…')})`);
      ok(env14('CARGO_HOME') === `CARGO_HOME=${join(ah, '.cargo')}` && !genv14('CARGO_HOME').includes(ah),
         `...the crate cache is the account's, and never in the tmux server's shared environment (${env14('CARGO_HOME').replace(DIR, '…')})`);
      // Java takes its home from the passwd entry, the one session user's, so
      // Gradle, the Android tools and the Kotlin daemon are each pointed at the
      // account's home by the variable they read (B182).
      const javaHomes = { GRADLE_USER_HOME: '.gradle', ANDROID_USER_HOME: '.android', XDG_DATA_HOME: '.local/share' };
      const wrong = Object.entries(javaHomes).filter(([k, d]) =>
        env14(k) !== `${k}=${join(ah, d)}` || genv14(k).includes(ah)).map(([k]) => k);
      ok(wrong.length === 0,
         `...and Gradle's, the Android tools' and the Kotlin daemon's folders are the account's too, never shared (${wrong.join(', ') || 'all three'})`);
      ok(env14('DISABLE_AUTOUPDATER') === 'DISABLE_AUTOUPDATER=1' || genv14('DISABLE_AUTOUPDATER') === 'DISABLE_AUTOUPDATER=1',
         '...and Claude\'s own updater is off: updating claude on a node is the provisioner\'s');
      tmuxKill(`${otherUid}~shell-wtproj-14`);
      rmSync(join(HOMEDIR, '.local', 'bin', 'claude'), { force: true });
    }
    // The second account goes, with anything it left running.
    tmuxKill(`${otherUid}~claude-${proj}`);
    usersPy(`
d = u.load()
d["users"].pop("wt.user", None)
d["users"].pop("plain.user", None)
u._save(d)`);
  }
}


// ---- a container's shell (R218 step 4) ----------------------------------------
// ctr:NAME:INSTANCE:CONTAINER runs docker exec in its own tmux session, named
// by the container; on the controller the container is the argument's, which
// the proxy checked (on a node it is tty-grant's answer, never the URL's). A
// name in any other shape, or one docker cannot inspect, opens nothing and
// says why.
{
  const dbin = mkdtempSync(join(tmpdir(), 'bbtty-docker-'));
  const dlog = join(dbin, 'log');
  writeFileSync(join(dbin, 'docker'), `#!/usr/bin/env bash
echo "$*" >> "${dlog}"
case "$1" in
  inspect) [ "$4" = alpha-app-1 ] ;;
  exec) sleep 60 ;;
esac
`);
  chmodSync(join(dbin, 'docker'), 0o755);
  const run = arg => {
    try {
      return execFileSync('bash', [BBTTY, arg], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${dbin}:${bin}:${process.env.PATH}`, WORKSPACE: join(DIR, 'ws'),
               HOME: join(DIR, 'home'), DASHBOARD_STATE: join(DIR, 'state') } });
    } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; }
  };
  tmuxKill('ctr-alpha-app-1');
  run('ctr:alpha:main:alpha-app-1');
  await sleep(400);
  const said = existsSync(dlog) ? readFileSync(dlog, 'utf8') : '';
  ok(alive('ctr-alpha-app-1') && /^exec -it alpha-app-1 sh -c /m.test(said),
     `a container's terminal is docker exec into it, in a session named by the container (${said.trim().split('\n').pop()})`);
  const shape = run('ctr:alpha:main:-oops');
  ok(/Invalid container: -oops/.test(shape) && !alive('ctr--oops'),
     `...a container name in any other shape opens nothing (${shape.trim().slice(0, 50)})`);
  const gone = run('ctr:alpha:main:alpha-db-1');
  ok(/cannot reach docker on this machine, or alpha-db-1 is gone/.test(gone) && !alive('ctr-alpha-db-1'),
     '...and one docker cannot inspect says so rather than opening an empty session');
  tmuxKill('ctr-alpha-app-1');
  // The container terminal's mode (BB_TTY_CTR, the agent's ctr kind, as the
  // docker account): a node's and nowhere else's, and nothing
  // opens there without the controller's grant for the token that came in.
  const ctrMode = (role, arg) => {
    try {
      return execFileSync('bash', [BBTTY, arg], {
        encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'],
        env: { ...process.env, PATH: `${dbin}:${bin}:${process.env.PATH}`, BB_TTY_CTR: '1',
               BUILDERBOT_ROLE: role, BB_CONTROLLER: URL, HOME: join(DIR, 'home'), DASHBOARD_STATE: join(DIR, 'state') } });
    } catch (e) { return `${e.stdout || ''}${e.stderr || ''}`; }
  };
  const here = ctrMode('controller', 'ctr:alpha:main:alpha-app-1');
  ok(/runs on a node and nowhere else/.test(here) && !alive('ctr-alpha-app-1'),
     `the container terminal's mode refuses off a node (${here.trim().slice(0, 60)})`);
  const bare = ctrMode('node', 'ctr:alpha:main:alpha-app-1');
  ok(/came without a session token/.test(bare) && !alive('ctr-alpha-app-1'),
     `...and on a node opens nothing without the controller's grant (${bare.trim().slice(0, 70)})`);
  tmuxKill('ctr-alpha-app-1');
  rmSync(dbin, { recursive: true, force: true });
}

await done();
