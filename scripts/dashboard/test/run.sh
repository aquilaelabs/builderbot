#!/usr/bin/env bash
# Run the dashboard's browser tests against an isolated instance.
#
# Nothing here touches the live dashboard: the server under test binds a spare
# port with its own scratch state directory, a fake workspace of four projects
# (one broken, one locked), a crafted SARIF report, a stub `bb` whose doctor
# output the tests can flip, and throwaway tmux sessions on a PRIVATE tmux
# server (TMUX_TMPDIR under the scratch dir) — the live dashboard lists every
# session on the shared server, and a test session showing up there as a
# real tab was the first thing an operator noticed. Everything is torn down by
# PID and by name — never by pattern, which is how a previous session managed
# to kill the real dashboard while trying to stop a test one.
#
#   bb dashboard test            # every *.mjs in this directory
#   bb dashboard test cards      # just cards.mjs
#   BB_TEST_TIMING=1 ...         # seconds between results, to find the slow part
#
# One run at a time: a second one is refused while the first is alive.
#
# Playwright comes from the image (/usr/lib/node_modules); the browsers live
# on the package store and are found the way bb finds them. Missing either, the
# run reports [skip] rather than passing by omission.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DASH="$(dirname "$HERE")"
# shellcheck source=/dev/null
. /opt/builderbot/scripts/lib/common.sh 2>/dev/null || {
    log()  { printf '[dashboard-test] %s\n' "$*"; }
    warn() { printf '[dashboard-test] WARN: %s\n' "$*" >&2; }
    die()  { printf '[dashboard-test] ERROR: %s\n' "$*" >&2; exit 1; }
}

# Missing pieces FAIL, by name. They used to print [skip] and exit 0, and
# on a node — where the runner's jobs had no node or Playwright on PATH —
# every CI run of this suite was green without running a test (bug B74).
# A run that could not start is not a pass.
#
# The same search bb uses, for both: the module and the browsers live on the
# store, and the /opt path is a symlink that only exists once the startup
# hook has run. The checkout's bb, not the one on PATH: this harness tests
# this tree, and the installed copy is whatever the running image shipped.
NODE_PATH="$(bash "$DASH/../bb" shot --print-node-path 2>/dev/null \
            || printf '%s' "${NODE_PATH:-/usr/lib/node_modules}")"
export NODE_PATH
node -e "require.resolve('playwright')" 2>/dev/null \
    || die "node and playwright are not on PATH here (NODE_PATH=$NODE_PATH) — on a node they are the playwright recipe in the packages store, installed from the Tools tab"
CHROME="$(bash "$DASH/../bb" shot --print-chromium 2>/dev/null || true)"
[ -x "${CHROME:-}" ] || die "no Playwright chromium — install it with: bb packages install playwright"
command -v tmux >/dev/null || die "tmux is not installed"

# The port is picked, not fixed. It was 8093 for everybody, which meant a run
# on this box and the CI job for the push that started it fought over one
# number: the second refused to start, and the message's first suggestion —
# kill the pid holding it — would have killed a live CI job. Worse than the
# collision was what it did to the run that DID start, since the two suites
# then shared the box's CPU and the loser went red on timing (bug #13).
#
# So: ask the kernel for a free one. Bound and released, then handed to the
# server — a race in principle, and not one in practice on a box running two
# of these at most, where the alternative is a constant that collides every
# time. DASHBOARD_TEST_PORT still pins it for anyone who needs a known port.
free_port() {
    python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}
PORT="${DASHBOARD_TEST_PORT:-$(free_port)}"
[ -n "$PORT" ] || die "could not find a free port for the test server"
# Refuse a port we do not own, before doing anything else. An interrupted run
# (SIGKILL, or the session that launched it dying) leaves a server holding this
# one with a scratch dir that no longer exists. Ours then exits on EADDRINUSE
# while the old one keeps answering — same port, same test:test credential — so
# the readiness curl below succeeds and the whole suite runs against the wrong
# fixtures. The failures that produces read as real regressions and are not;
# that cost an hour once, and the tell was obscure enough to be worth this check.
#
# Only reachable now when the port was pinned by hand, which is exactly when
# the holder is worth identifying: a copy running out of /workspace/_work is
# the CI runner's, mid-job, and killing it ends a build.
if holder="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)" && [ -n "$holder" ]; then
    where="$(tr '\0' ' ' < "/proc/$holder/cmdline" 2>/dev/null || true)"
    case "$where" in
        */_work/*) die "port $PORT is held by pid $holder, which is a CI run on this box (${where# }) — do NOT kill it; leave DASHBOARD_TEST_PORT unset to get a free port." ;;
    esac
    die "port $PORT is already in use by pid $holder ($(ps -o comm= -p "$holder" 2>/dev/null || echo unknown)${where:+ — $where}) — if that is a test server left behind by an interrupted run, 'kill $holder' and re-run; otherwise leave DASHBOARD_TEST_PORT unset and one will be picked."
fi
# One run at a time on this box. The port used to be fixed, which stopped a
# second run by accident; picking a free one removed that stop, and three
# suites then ran side by side on a box that also serves the live dashboard
# — the contention bug #13 describes, made to order. A pid lock says so
# instead, with how long the other has been going. BB_TEST_CONCURRENT=1
# overrides it for whoever knows what they are doing.
#
# The other run may be ANOTHER ACCOUNT'S: on a node the CI runner shares the
# box with every session, and its run holds this same lock. So liveness is
# /proc, not kill -0 — which answers "no" for a pid that is not yours and
# read a live CI run as a stale lock — and the lock is written world-
# writable, so the next account can take over one a killed run left.
#
# In a directory of its own, NOT a file straight under /tmp. /tmp is sticky,
# and with fs.protected_regular (on by default since Ubuntu 20.04) a file
# there that another account owns cannot be opened for writing whatever its
# mode — so a lock a cancelled CI job left as `bb` could never be taken over
# by a session, or the reverse, and every run died on "cannot take" until
# somebody with that account removed it (measured on bb-sandbox, 9 Sep). A
# world-writable directory that is not sticky has no such rule: anyone can
# overwrite or unlink the lock inside it, which is what a stale lock wants.
LOCKDIR="${TMPDIR:-/tmp}/dashboard-test.d"
( umask 000; mkdir -p "$LOCKDIR" ) 2>/dev/null || true
LOCK="$LOCKDIR/lock"
# A run still on the previous layout holds the old path; for one release
# both are read for a LIVE pid, and only the new one is written.
for l in "$LOCK" "${TMPDIR:-/tmp}/dashboard-test.lock"; do
    [ -z "${BB_TEST_CONCURRENT:-}" ] && [ -f "$l" ] || continue
    other="$(cat "$l" 2>/dev/null || true)"
    if [ -n "$other" ] && [ -d "/proc/$other" ]; then
        owner="$(stat -c %U "$l" 2>/dev/null || echo somebody)"
        die "another dashboard test run is going (pid $other, ${owner}'s, started $(ps -o etime= -p "$other" 2>/dev/null | tr -d ' ') ago) — one at a time on this box, and the CI runner counts; wait for it, or set BB_TEST_CONCURRENT=1"
    fi
done
# Taken over by unlinking first: a stale lock another account wrote is
# unlinkable in a non-sticky directory, and a fresh file is then ours.
rm -f "$LOCK" 2>/dev/null || true
( umask 000; printf '%s' "$$" > "$LOCK" ) 2>/dev/null \
    || die "cannot take $LOCK — $(stat -c %U "$LOCK" 2>/dev/null || echo somebody)'s, and $LOCKDIR is not world-writable; fix the directory's mode (chmod 0777) and re-run"
S="$(mktemp -d "${TMPDIR:-/tmp}/dashboard-test.XXXXXX")"
# Every tmux call from here on — ours and the server's — talks to a private
# server whose socket lives in the scratch dir. Nothing reaches the real one.
#
# TMUX must be unset first. This script is usually run FROM a tmux session
# (a dashboard terminal, a Claude session), and inside one the tmux client
# takes its socket from $TMUX and ignores TMUX_TMPDIR entirely — which is how
# a first version of this file put its test sessions on the real server and,
# on cleanup, killed the real server, the operator's shell and the Claude
# session running the tests along with it. Verified below, not assumed.
unset TMUX
# Same reasoning, for the credential. This script is usually run FROM a Claude
# session, which is given BB_TOKEN — a token scoped to ONE project with `user`
# rights and a twelve-hour life. `bb` prefers it over DASHBOARD_AUTH, so every
# test that shells out to `bb` was quietly using the outer session's
# credential instead of the harness's: it worked while that token was fresh
# and the project happened to match, and stopped the moment it expired. What
# that looked like was agent.mjs dying on "no node called agentbox" — a 401
# the caller reads as an empty node list — hours into a session, with nothing
# in the diff to explain it.
unset BB_TOKEN
# And the role. Run from a session ON A NODE, this script inherits
# BUILDERBOT_ROLE=node, the real controller's address and pin, and the
# account the session runs as — and every `bash scripts/bb` a test makes
# then relays to the real controller with no token, or reads a node's
# home. The suite drives the checkout's bb as the CONTROLLER's, against its
# own server; the tests that mean a node say so in their own env.
unset BUILDERBOT_ROLE BB_CONTROLLER BB_CONTROLLER_PIN BB_NODE BUILDERBOT_NODE \
      BB_ACCOUNT_NAME BB_ACCOUNT_UID BB_PROJECT BB_TREE BB_TREE_OWNER BB_CI_LOG_DIR \
      BB_NODE_PACKAGES BB_EMU_LOCAL   # "already on the node's store": bb emu would run here
export TMUX_TMPDIR="$S/tmux"
mkdir -p "$TMUX_TMPDIR"
tmux new-session -d -s probe -c /tmp
sock="$(tmux display-message -t probe -p '#{socket_path}' 2>/dev/null || true)"
case "$sock" in
    "$S"/*) tmux kill-session -t probe ;;
    *) tmux kill-session -t probe 2>/dev/null
       die "refusing to run: tmux is on '${sock:-?}', not the private test server" ;;
esac
trap 'cleanup' EXIT
pid=""
agent_pid=""
stub_pid=""
cleanup() {
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    [ -n "$agent_pid" ] && kill "$agent_pid" 2>/dev/null || true
    [ -n "$stub_pid" ] && kill "$stub_pid" 2>/dev/null || true
    # The private server only — guarded again, because this is the line that
    # once took the real one down.
    case "$(tmux display-message -p '#{socket_path}' 2>/dev/null)" in
        "$S"/*) tmux kill-server 2>/dev/null || true ;;
    esac
    # BB_TEST_KEEP=1 leaves the scratch dir behind: the server log, the stub
    # agent's log and the state dir are the only account of what a failure
    # inside them looked like, and they used to go with the run that made it.
    [ -n "${BB_TEST_KEEP:-}" ] && log "scratch kept at $S" || rm -rf "$S"
    [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"
}

# ---- fixtures --------------------------------------------------------------
mkdir -p "$S"/{ws,reports,state,bin,sdk,androidsdk,devdata}
# ep.silon: a project whose name tmux would rewrite in a session name (`.` →
# `_`), so the page, the server and bb-tty have to agree on the substitution.
( cd "$S/ws" && mkdir -p alpha beta gamma delta ep.silon \
    && for d in alpha beta gamma delta ep.silon; do echo x > "$d/README.md"; done \
    && for d in alpha beta delta ep.silon; do git init -q "$d"; done \
    && for d in alpha beta delta ep.silon; do
           # The fixture's own identity, so a commit the server makes in one
           # of these (a version bump, VERSION's first commit) does not lean
           # on the ACCOUNT's global config: the node's CI runner has none,
           # and two version tests went red there and green here for exactly
           # that (measured on bb-sandbox's first real run of this suite).
           git -C "$d" config user.name "dashboard test" \
           && git -C "$d" config user.email "test@example.invalid"; done \
    && git -C alpha remote add origin git@github.com:owner/alpha.git \
    && git -C ep.silon remote add origin https://gitlab.example/eps.git )
    # alpha is linked to GitHub and beta to nothing — the link-to-GitHub
    # button must show on exactly one of them. ep.silon is linked to a
    # non-GitHub remote: still "linked", but the GitHub command card must
    # ghost there all the same.
# A directory that carries the marker: the container writes one into paths of
# its own that land in the projects share, and an operator can write one by
# hand. Either way it is not a project.
mkdir -p "$S/ws/toolstore" && : > "$S/ws/toolstore/.bbignore"
# ...and one with no marker at all, the shape the package store actually has when
# somebody maps a share inside the projects folder and nothing has told the
# container about it. It is not a project because the Projects card did not
# accept it, which is the only test that matters now.
mkdir -p "$S/ws/vendored-junk/deep" && echo x > "$S/ws/vendored-junk/deep/thing.py"
# delta is the locked one: kept, run by the operator, and read-only.
echo '["delta"]' > "$S/state/locked-projects.json"
# A git that stalls on one magic URL and is the real git for everything else.
# Cloning is a background job now, and the two properties that matters for —
# it outlives the page, and it can be stopped — can only be checked against a
# clone that is still going when the test looks.
REAL_GIT="$(command -v git)"
cat > "$S/bin/git" <<GEOF
#!/usr/bin/env bash
for a in "\$@"; do
    case "\$a" in *slowclone*) sleep 120; exit 1 ;; esac
done
exec "$REAL_GIT" "\$@"
GEOF
chmod +x "$S/bin/git"
# alpha has a previous Claude conversation, so its Claude button offers the
# Resume / New chooser rather than starting straight away.
mkdir -p "$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)"
echo '{}' > "$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)/abc123.jsonl"
# alpha also has memories, arranged so both kinds of drift between the index
# and the files are on screen: the index names one file that is not there, and
# one file that is there is not in the index. Re-seeded before every test file
# because memory.mjs edits and deletes these for real.
M="$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)/memory"
seed_memories() {
rm -rf "$M"; mkdir -p "$M"
cat > "$M/MEMORY.md" <<'MEOF'
- [Prefers tabs](tabs.md) — spaces are a fight not worth having
- [Something else](vanished.md) — a pointer with nothing behind it
MEOF
cat > "$M/tabs.md" <<'MEOF'
---
name: tabs
description: indent with tabs in this project, always
metadata:
  type: feedback
---

Tabs, not spaces.

**Why:** asked for it twice.
MEOF
cat > "$M/loose.md" <<'MEOF'
---
name: loose
description: a memory that never made it into the index
metadata:
  type: project
---

Only recall will ever surface this one.
MEOF
}
seed_memories
# A scratch ssh-agent holding one throwaway key, so the deploy-key endpoint
# has something deterministic to list. Its socket replaces the real agent's in
# the server's environment — the tests must see this key and no operator key.
ssh-keygen -q -t ed25519 -N '' -C github_testkey -f "$S/testkey"
ssh-agent -a "$S/ssh-agent.sock" > "$S/agent.env"
agent_pid="$(sed -n 's/^SSH_AGENT_PID=\([0-9]*\);.*/\1/p' "$S/agent.env")"
SSH_AUTH_SOCK="$S/ssh-agent.sock" ssh-add -q "$S/testkey" 2>/dev/null
cat > "$S/bin/bb" <<'EOF'
#!/usr/bin/env bash
# Stub: deterministic `bb doctor`, and an `bb packages` that makes and removes
# directories instead of downloading gigabytes — enough for the Tools card to
# watch a package appear and disappear.
if [ "${1:-}" = doctor ]; then cat "${BB_DOCTOR_FIXTURE:?}"; fi
# claude-md is the REAL one, not a stub. It only reads the shipped template
# and rewrites a delimited block in the file it is handed — no network, no
# /config, nothing this harness needs to keep away from — and the dashboard's
# "environment block is out of date — update" link is only worth testing if
# pressing it actually fixes the file. Stubbed, that link was tested to POST
# and nothing more, and a session gate built on the same state had no way to
# prove it clears.
if [ "${1:-}" = claude-md ]; then exec bash "${BB_REAL:?}" "$@"; fi
if [ "${1:-}" = packages ]; then
    # Where this stub pretends a package lives. Shared by every verb, so
    # check and versions answer for what install and remove actually did —
    # a stub that claimed 1.0 for everything let a bug through where the page
    # showed an installed version on a row that had nothing installed.
    _d() {
        local n="${1#android:}"
        if [ "$n" != "$1" ]; then printf '%s/%s' "${ANDROID_HOME:?}" "$n"
        else printf '%s/%s' "${SDK_TEST_ROOT:?}" "$n"; fi
    }
    case "${2:-}" in
        root)    printf '%s\n' "${SDK_TEST_ROOT:?}" ;;
        images)  # --available is the index of what could be installed; bare is
                 # what is on disk. One of each, plus one that is both, so the
                 # picker has something to leave out.
                 if [ "${3:-}" = --available ]; then
                     printf 'system-images;android-31;google_apis;x86_64\t31\tgoogle_apis\t1470822277\n'
                     printf 'system-images;android-30;google_apis;x86_64\t30\tgoogle_apis\t1438186618\n'
                     printf 'system-images;android-30;google_apis_playstore;x86_64\t30\tgoogle_apis_playstore\t1404405641\n'
                 else
                     # ...with the AVD built on it, which is what makes it
                     # answerable whether the image can go.
                     printf 'system-images;android-30;google_apis;x86_64\tandroid-30\tgoogle_apis\t3300000\tfb30\n'
                 fi ;;
        flavors) printf 'google_apis\tx86_64\tGoogle APIs\tPlay services, no Play Store app. Rootable.\n'
                 printf 'google_apis_playstore\tx86_64\tGoogle APIs + Play Store\tThe Play Store app itself; not rootable.\n' ;;
        versions) # local only: installed version, no upstream asked. Called
                  # with no names by the server, which wants the lot.
                 for n in ${3:-playwright flutter dotnet swift go rust zig android:emulator}; do
                     if [ -d "$(_d "$n")" ]; then printf '%s\t1.0\t-\tlocal\n' "$n"
                     else printf '%s\t-\t-\tabsent\n' "$n"; fi
                 done ;;
        check)   # one line per name: installed, latest, status. Absent rows
                 # answer too — what they would install is the other half of
                 # what the button is for.
                 # A fifth column on the absent rows: what an install would
                 # download, which is the only size a package this box has
                 # never had can honestly show.
                 if [ ! -d "$(_d "$3")" ];  then printf '%s\t-\t9.9\tabsent\t123456789\n' "$3"
                 elif [ "$3" = flutter ];   then printf '%s\t1.0\t2.0\tupdate\n' "$3"
                 else                            printf '%s\t1.0\t1.0\tcurrent\n' "$3"; fi ;;
        update)  printf 'updated %s\n' "$3" ;;
        install|remove)
                 d="$(_d "$3")"
                 if [ "${2}" = install ]; then
                     # One package takes its time and draws a bar, with the
                     # carriage returns a real tool uses, so a test can watch
                     # the progress reach the row through the whole path:
                     # streamed output, parser, payload, poll, render. Every
                     # other package installs instantly, as before.
                     # One that fails, loudly and then quietly: a real
                     # install writes pages of progress and one useful line,
                     # and what reaches the operator has to be the line.
                     if [ "$3" = rust ]; then
                         for pct in 10 40 90; do
                             printf '[====] %s%% Downloading rust\r' "$pct"
                         done
                         printf '\ninfo: syncing channel updates\n'
                         # Long enough that a test can see the row mid-attempt:
                         # the last failure is cleared when the next one starts,
                         # and that is a state with a beginning and an end.
                         sleep 1.5
                         printf 'error: could not download file from upstream\n' >&2
                         exit 1
                     fi
                     # A system image takes its time too, so a test can see
                     # where a job started from Add reports itself.
                     case "$3" in *system-images*) sleep 1.5 ;; esac
                     if [ "$3" = go ]; then
                         # Takes a while, and counts loudly while it does —
                         # shaped like sdkmanager, whose meter runs one fraction
                         # across the whole operation and parks part way. None
                         # of it should reach the row; that is the point of the
                         # test that watches this.
                         printf 'Downloading go.tar.gz from https://example\n'
                         printf 'info: downloading installer\n'
                         for pct in 8 31 66 100; do
                             printf '[====] %s%% Downloading go.tar.gz\r' "$pct"; sleep 0.4
                         done
                         printf '\nUnzipping...\n'
                         printf '[====] 55%% Unzipping...\r'; sleep 2
                         printf '[====] 100%% Unzipping...\r\n'; sleep 0.3
                     fi
                     mkdir -p "$d" && : > "$d/marker"
                 else rm -rf "$d"; fi
                 printf '%sed %s\n' "${2%e}" "$3" ;;
    esac
fi
exit 0
EOF
chmod +x "$S/bin/bb"
# Stub claude: `auth status` answers from a fixture the tests flip, and
# `auth logout` rewrites that fixture rather than going anywhere near the
# operator's real credentials — which is the entire reason this stub exists,
# since the real one would sign this container out for good.
cat > "$S/bin/claude" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = auth ]; then
    case "${2:-}" in
        status) cat "${CLAUDE_AUTH_FIXTURE:?}" ;;
        logout) printf '{"loggedIn":false}\n' > "${CLAUDE_AUTH_FIXTURE:?}" ;;
        --help|help) printf 'Manage authentication\n' ;;
        # The flow, shaped like the real one: a URL, a prompt with no newline
        # after it, and a line read back. A code beginning "good" signs in and
        # rewrites the fixture; anything else is refused the way the real one
        # refuses an expired code. This is the half that could never be tested
        # while the sign-in lived in a terminal.
        login)
            printf 'Opening browser to sign in...\n'
            printf 'If the browser did not open, visit: '
            printf 'https://claude.com/cai/oauth/authorize?code=true&state=abc\n'
            printf 'Paste code here if prompted > '
            read -r code
            case "$code" in
                good*) cat "${CLAUDE_AUTH_IN:?}" > "${CLAUDE_AUTH_FIXTURE:?}"
                       printf '\nLogin successful.\n'; exit 0 ;;
                # The code it was handed, echoed back. The dashboard trims
                # what a copy brought along with it — a line break, the URL
                # the code page sets flush against the code — and this is how
                # a test sees what actually arrived rather than assuming.
                *) printf '\nLogin failed: Request failed with status code 400 [got %s]\n' "$code"
                   exit 1 ;;
            esac ;;
        *) exit 1 ;;
    esac
    exit 0
fi
exit 0
EOF
chmod +x "$S/bin/claude"
printf '{"loggedIn":true,"email":"tester@example.com","subscriptionType":"max"}
'     > "$S/auth-in.json"
printf '{"loggedIn":false}
' > "$S/auth-out.json"
cp "$S/auth-in.json" "$S/auth.json"

# Stub adb and web-ext, for the same reason as gh below: the phone card shells
# out to the real ones, and a suite whose answers depend on whether somebody
# has a handset paired right now is not a suite. These answer as a phone that
# is always there, so the card can be exercised on a box with nothing attached
# — and, more to the point, cannot reach a box that has.
cat > "$S/bin/adb" <<'ADBEOF'
#!/usr/bin/env bash
case "$1 $2" in
  "devices -l") printf 'List of devices attached
192.168.9.9:5555	device product:test model:Test_Phone device:test
'; exit 0 ;;
esac
case "$1" in
  devices) printf 'List of devices attached
192.168.9.9:5555	device
'; exit 0 ;;
  pair)    printf 'Successfully paired to %s [guid=adb-TEST]
' "$2"; exit 0 ;;
  connect) printf 'connected to %s
' "$2"; exit 0 ;;
  disconnect) printf 'disconnected
'; exit 0 ;;
esac
# adb -s SERIAL install -r PATH. A file named *-clash.apk fails the way a
# signature mismatch really does, so the test can prove that answer is turned
# into a sentence rather than passed through raw.
if [ "$3" = install ]; then
    case "$5" in
        *-clash.apk) printf 'adb: failed to install %s: Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n' "$5"; exit 1 ;;
        *) printf 'Performing Streamed Install\nSuccess\n'; exit 0 ;;
    esac
fi
# adb -s SERIAL shell pm list packages
if [ "$4 $5 $6" = "pm list packages" ]; then
    printf 'package:org.mozilla.firefox_beta
package:com.android.chrome
'; exit 0
fi
exit 0
ADBEOF
chmod +x "$S/bin/adb"

# docker, stubbed the way adb is: every call lands in docker.log, and a tiny
# state machine under dockerstate/ answers compose ps/up/down/build so the
# dev-instance row can be driven end to end with no daemon anywhere.
mkdir -p "$S/dockerstate"
cat > "$S/bin/docker" <<'DOCKEREOF'
#!/usr/bin/env bash
ST="${DOCKER_STUB_STATE:?}"
echo "$*" >> "$ST/docker.log"
# A host that is not there. The real CLI carries the address in DOCKER_HOST;
# listing one in deadhosts makes every call against it fail the way a powered
# off VM does, so the suite can have one node answering and another not.
if [ -n "${DOCKER_HOST:-}" ] && [ -f "$ST/deadhosts" ] \
   && grep -qF "$DOCKER_HOST" "$ST/deadhosts"; then
  echo "cannot connect to the daemon at $DOCKER_HOST"; exit 1
fi
# The one-shot `run` the dev-data probe makes (mkdir, mv, test -d on one
# share). Answers yes by default; run.testfail is the suite saying the marker
# is NOT over there — a clean exit 1 with nothing said, as `test -d` does.
if [ "$1" = run ] && [ -f "$ST/run.testfail" ]; then exit 1; fi
case "$1" in
  # A daemon that is not there at all — the VM powered off, or an address that
  # is not a sandbox VM. availability is what the page gates every Docker
  # control on, so the suite has to be able to take it away.
  version) [ -f "$ST/version.fail" ] && { echo "cannot connect to the daemon"; exit 1; }
    echo "99.stub"; exit 0 ;;
  # What the daemon says it is. The provisioner's label lives here, and this is
  # how BuilderBot tells the sandbox from any other machine that answers
  # Docker — so the suite can take the stamp away (unlabelled.fail) and can
  # make it a DIFFERENT sandbox (uid file), which is the other question:
  # whether records from the last one are cleared when a new one is plugged in.
  info)
    [ -f "$ST/info.fail" ] && { echo "cannot connect to the daemon"; exit 1; }
    lbl='["builderbot.sandbox=1"]'
    [ -f "$ST/unlabelled" ] && lbl='["com.example.other=1"]'
    uid="STUBDAEMON1"
    [ -f "$ST/uid" ] && uid="$(cat "$ST/uid")"
    printf '{"ID":"%s","Labels":%s,"ServerVersion":"99.stub"}\n' "$uid" "$lbl"
    exit 0 ;;
  ps)
    # The bare `docker ps` the Docker manager reads. Stateful, because the
    # manager derives running/stopped from it: a compose `up` leaves a marker
    # and this turns each marker into the container that `up` would have
    # started. A fixed list made the manager disagree with the compose stub
    # about what was running, which is a test lying in the shape of a bug.
    [ -f "$ST/ps.fail" ] && { echo "cannot connect to the daemon"; exit 1; }
    for f in "$ST"/*.up; do
      [ -e "$f" ] || continue
      pn="$(basename "$f" .up)"
      printf '{"ID":"aaaa%s","Names":"%s-app-1","Image":"%s-img","State":"running","Status":"Up 3 minutes","Ports":"0.0.0.0:7475->7474/tcp, [::]:7475->7474/tcp","Labels":"com.docker.compose.project=%s,com.docker.compose.service=app"}\n' \
        "$pn" "$pn" "$pn" "$pn"
    done
    # An exited container is still THERE — holding its name and its network —
    # which is why Down stays live for one and why the manager has to see it.
    for f in "$ST"/*.exited; do
      [ -e "$f" ] || continue
      pn="$(basename "$f" .exited)"
      [ -e "$ST/$pn.up" ] && continue          # up wins: it is the same one
      printf '{"ID":"bbbb%s","Names":"%s-app-1","Image":"%s-img","State":"exited","Status":"Exited (1) 1 minute ago","Ports":"","Labels":"com.docker.compose.project=%s,com.docker.compose.service=app"}\n' \
        "$pn" "$pn" "$pn" "$pn"
    done
    # And one this dashboard did not start, which is the distinction the
    # listing exists to draw.
    printf '%s\n' '{"ID":"ccccccccccccdddd","Names":"someone-elses","Image":"redis:7","State":"exited","Status":"Exited (0) 2 hours ago","Ports":"","Labels":"com.docker.compose.project=other"}'
    exit 0 ;;
  compose)
    proj=""
    args=("$@")
    for ((i=0;i<${#args[@]};i++)); do
      [ "${args[$i]}" = "--project-name" ] && proj="${args[$((i+1))]}"
    done
    verb=""
    for a in ps build up down config; do
      for x in "$@"; do [ "$x" = "$a" ] && verb="$a"; done
    done
    case "$verb" in
      config)
        # -q is the validation the container-create path runs: no output, just
        # a verdict. A file lets a test ask for a compose that will not parse.
        for x in "$@"; do [ "$x" = "-q" ] && {
          [ -f "$ST/config.fail" ] && { echo "yaml: line 2: mapping values are not allowed"; exit 1; }
          exit 0; }
        done
        # A service that declares a build, which is what the fixture has —
        # unless a test wants a different shape, which it leaves here.
        if [ -f "$ST/$proj.config" ]; then cat "$ST/$proj.config"
        else echo '{"services":{"app":{"build":{"context":"."},"ports":[{"target":7474,"published":"7475","protocol":"tcp"}],"volumes":[{"type":"bind","source":"/mnt/user/plex-media","target":"/library","read_only":true},{"type":"bind","source":"/mnt/user/appdata/x/config","target":"/config"}]}}}'
        fi
        exit 0 ;;
      ps)
        # -a asks "does anything exist here", bare ps asks "what is running":
        # an exited container answers yes to the first and no to the second,
        # and that gap is the whole reason Down has to stay live.
        all=0
        for x in "$@"; do case "$x" in -a|-aq) all=1 ;; esac; done
        if [ -f "$ST/$proj.up" ]; then echo "stubcontainer"
        elif [ "$all" = 1 ] && [ -f "$ST/$proj.exited" ]; then echo "stubexited"
        fi
        exit 0 ;;
      build)
        echo "BUILDKIT=${DOCKER_BUILDKIT:-unset}" >> "$ST/docker.log"
        [ -f "$ST/build.fail" ] && { echo "stub build exploded"; exit 1; }
        # A build that takes its time and says so, for the two properties a
        # fast one cannot show: that its output arrives WHILE it runs, and
        # that it can be interrupted. Line-buffered on purpose — a pull writes
        # a line at a time and the reader is asserting it sees them early.
        if [ -f "$ST/build.slow" ]; then
          # Long enough that a test can see it running, open the manager and
          # press Abort while it still is — the manager repaints on its own
          # fetch, so "the log has a line in it" and "the click lands" are
          # several seconds apart on a loaded box.
          for i in $(seq 1 60); do
            echo "pulling layer $i"
            sleep 0.5
          done
        fi
        echo "stub built ok"; exit 0 ;;
      up)
        # A failing up, for the row that has to survive one: compose creates
        # the container and then cannot start it — the shape of a bind mount
        # landing on a share that squashes root.
        if [ -f "$ST/up.fail" ]; then
          touch "$ST/$proj.exited"
          printf ' Container %s-x-1 Creating \n Container %s-x-1 Created \n' "$proj" "$proj"
          printf ' Container %s-x-1 Starting \n' "$proj"
          echo "Error response from daemon: error while creating mount source path"
          exit 1
        fi
        touch "$ST/$proj.up"; exit 0 ;;
      down) rm -f "$ST/$proj.up" "$ST/$proj.exited"; exit 0 ;;
    esac
    exit 0 ;;
esac
exit 0
DOCKEREOF
chmod +x "$S/bin/docker"
# web-ext that installs and then sits there, the way the real one does.
cat > "$S/bin/web-ext" <<'WEEOF'
#!/usr/bin/env bash
printf 'Running web extension from here
'
sleep 0.3
printf 'Installed /data/local/tmp/probe.xpi as a temporary add-on
'
printf 'The extension will reload if any source file changes
'
while :; do sleep 1; done
WEEOF
chmod +x "$S/bin/web-ext"

# Stub gh: always unauthenticated, so `pat` is deterministically false — the
# real gh would answer from the operator's own login state.
printf '#!/usr/bin/env bash\nexit 1\n' > "$S/bin/gh"
chmod +x "$S/bin/gh"
printf '  [ok]   claude on PATH\n  [ok]   github reachable\n  [ok]   disk space\n  [skip] gpu (no device)\n' > "$S/doctor-ok.txt"
{ cat "$S/doctor-ok.txt"; echo '  [warn] clock skew 3s'; echo '  [FAIL] runner offline'; } > "$S/doctor-fail.txt"
cp "$S/doctor-ok.txt" "$S/doctor.txt"
python3 - "$S/reports/test.sarif" <<'EOF'
import json, sys
def res(rule, level, uri):
    return {"ruleId": rule, "level": level, "message": {"text": "test finding"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri},
                                                "region": {"startLine": 3}}}]}
doc = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "testscan", "rules": []}},
       "results": [res("A1", "error", "scan/alpha/a.sh"), res("B1", "note", "scan/beta/x.py"),
                   res("G1", "error", "scan/gamma/g.c"), res("D1", "warning", "scan/delta/d1.c"),
                   # Two the scanner swept that are not projects: one marked
                   # with .bbignore, one not marked at all. Both must be set
                   # aside rather than counted as unattributed.
                   res("T1", "error", "scan/toolstore/vendor/lib.py"),
                   res("V1", "error", "scan/vendored-junk/deep/thing.py"),
                   # ...and one that genuinely places nowhere, which is what
                   # the unattributed label is actually for.
                   res("U1", "warning", "somewhere/else/entirely.py")]}]}
open(sys.argv[1], "w").write(json.dumps(doc))
EOF
# Each test file starts from the same place: an unwritten layout and both
# throwaway sessions present — a file that minimizes tabs or ends a session
# must not hand that state to the next.
fresh() {
    rm -f "$S/state/tabs.json" "$S/state/cards.json" "$S/state/todos.json" \
          "$S/state/bugs.json"
    # ...nor the rules and the approval queue (roadmap #7, #27): a rule or a
    # held change left by pending.mjs lit the bell and filled the Briefing
    # tab for every file after it.
    rm -f "$S/state/rules.json" "$S/state/pending.json"
    # ...and the test registry: uniform.mjs ingests a run of its own so the
    # Tests view has rows, and testreg.mjs counts what it ingests.
    rm -f "$S/state/tests.json"
    echo '["delta"]' > "$S/state/locked-projects.json"     # a test that locks must not hand that on
    rm -f "$S/state/pinned-projects.json"                  # ...nor one that unpins
    # ...nor one that binds a project to a node. nodes.mjs saves alpha's node
    # from the settings dialog; agent.mjs then asserts that a project with no
    # node is refused, and inherited the binding — a deterministic failure of
    # the pair that neither file showed alone.
    rm -f "$S/state/claude-prefs.json"
    # ...nor one that built a dev instance. agent.mjs runs a compose action
    # on its node now, which records what was built and on which daemon;
    # devapp.mjs then opened on a project that believed it had been built
    # somewhere else. Per-run state, like the rest of this list.
    rm -f "$S/state/devapps.json"
    rm -rf "$S/state/devenv"
    # Projects a test created through /api/create go too — anything that is
    # not one of the five fixtures. Scoped to $S, like every rm in this file.
    # .claude stays: it is where every account's ~/.claude/projects points
    # (roadmap #24), and removing it leaves the home's link dangling — which
    # is what made seed_memories' mkdir fail with "File exists" on the
    # second file of a run. It is per-run state like the home is.
    find "$S/ws" -maxdepth 1 -mindepth 1 -type d \
        ! -name alpha ! -name beta ! -name gamma ! -name delta ! -name ep.silon \
        ! -name toolstore ! -name vendored-junk ! -name .claude -exec rm -rf {} +
    rm -rf "$S/home/.ssh"           # deploy-key selectors a test wrote
    rm -rf "$S/dockerstate"; mkdir -p "$S/dockerstate"
    rm -rf "$S/sdk" "$S/androidsdk"; mkdir -p "$S/sdk" "$S/androidsdk"
    # The phone stub, put back if a test that hid it died before restoring
    # it. artifacts.mjs renames bin/adb aside to prove Push goes dead; when
    # its next wait timed out the rename never reversed, and every suite
    # after it ran with no phone and failed on things that had nothing to do
    # with phones — a cascade that read as five bugs and was one.
    [ -e "$S/bin/adb.hidden" ] && mv -f "$S/bin/adb.hidden" "$S/bin/adb"
    cp "$S/doctor-ok.txt" "$S/doctor.txt"
    cp "$S/auth-in.json" "$S/auth.json"   # a test that signs out must not hand that on
    rm -f "$S/login-finished"
    seed_memories                   # memory.mjs edits and deletes these for real
    for n in shell-9 claude-alpha; do
        tmux has-session -t "$n" 2>/dev/null || tmux new-session -d -s "$n" -c /tmp
        # A test that typed into a pane without pressing Enter — the memory
        # book's note does exactly that — must not hand the half-typed line
        # to the next file. C-u is kill-line, not a signal.
        tmux send-keys -t "$n" C-u 2>/dev/null || true
    done
}
fresh

# ---- server ----------------------------------------------------------------
# BB_DEV_DATA_DIR belongs in here with the rest: devapp.py defaults the
# dev-data root to /devdata, and everything else was redirected while that
# was not — so the ep.silon fixture's instance did an mkdir in the operator's
# REAL /devdata, which this suite's whole story is that it cannot do. It is
# per-command env, deliberately: the node tests further down still see the
# container's own /devdata, which is what the module-level host_map() and
# problems() snippets in devapp.mjs are written against.
#
# DOCKER_HOST names an ssh:// address because that shape is now the feature's
# switch: a sandbox VM is the only daemon the manager drives, so anything else
# greys every control out and the suite would be testing a dead tab. The stub
# docker on PATH answers whatever it is pointed at, so no VM is involved.
#
# DOCKER_HOST_PATHS is cleared for the same reason and was found the same way.
# Unset here, it inherited the REAL container's mapping, so what the dev row
# said about a fixture's compose file depended on how the operator had wired
# their own daemon — a suite that passes on one box and fails on the next with
# nothing in the diff to explain it. Found when a check on an identity pair
# started firing against this box's /workspace:/workspace.
env WORKSPACE="$S/ws" DASHBOARD_PORT="$PORT" DASHBOARD_TTYD_PORT=7999 BUILDER_HOME="$S/home" \
    TEMPLATE_MD="$DASH/../../config/templates/project-CLAUDE.md" \
    BB_BIN="$S/bin/bb" BB_REAL="$DASH/../bb" SDK_TEST_ROOT="$S/sdk" ANDROID_HOME="$S/androidsdk" \
    PKG_AUTOCHECK=0 BB_AUTH_TTL=1 BB_NODE_POLL=3 \
    SSH_AUTH_SOCK="$S/ssh-agent.sock" \
    FINDINGS_DIR="$S/reports" DASHBOARD_STATE="$S/state" \
    BB_DOCTOR_FIXTURE="$S/doctor.txt" CLAUDE_AUTH_FIXTURE="$S/auth.json" \
    BB_IMAGE_REV=abc1234def5678901234567890abcdef12345678 \
    BB_IMAGE_BUILT=2026-08-21T19:30Z \
    BB_VERSION=0.4.0-dev.390+abc1234 \
    CLAUDE_AUTH_IN="$S/auth-in.json" \
    BB_LOGIN_DONE="$S/login-finished" \
    PATH="$S/bin:$PATH" BB_WEBEXT_BIN="$S/bin/web-ext" BB_ADB_BIN="$S/bin/adb" \
    BB_DOCKER_BIN="$S/bin/docker" DOCKER_STUB_STATE="$S/dockerstate" \
    BB_DEV_DATA_DIR="$S/devdata" \
    BB_ARCHIVE_SPOOL="$S/spool" \
    BUILDERBOT_IDLE_UNIT=1 \
    BB_COMPAT_SWEEP=1 \
    python3 "$DASH/server.py" > "$S/server.log" 2>&1 &
pid=$!
for _ in $(seq 40); do
    curl -fs -u test:test -o /dev/null "http://127.0.0.1:$PORT/api/status" && break
    kill -0 "$pid" 2>/dev/null || { cat "$S/server.log"; die "server exited"; }
    sleep 0.25
done

# ---- the owner ---------------------------------------------------------------
# There is no DASHBOARD_AUTH any more: a fresh container serves a first-run
# screen and the person at it makes the owner. The harness cannot use that
# form — its credential is `test:test`, and the form enforces an eight
# character password, which every other file here would then have to know
# about — so it claims the store directly, which is the same call the form
# makes. The form's own path is covered in auth.mjs, against a store of its
# own.
python3 - "$DASH/users.py" "$S/state" <<'PY'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("users", sys.argv[1])
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=sys.argv[2], write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
d = u.load()
d["users"]["test"] = {"uid": u.mint_uid(), "role": "owner", "projects": ["*"],
                      # An author, or no Claude session starts for it (users.git_ready).
                      # ...and the welcome panel read, or it would open over
                      # every page load in the suite (cards.mjs opens it on purpose).
                      "prefs": {"full_name": "Dashboard Test", "email": "test@example.invalid",
                                "welcome_seen": True,
                                "image_seen": "abc1234def5678901234567890abcdef12345678"},
                      "password": u.hash_password("test"), "created": 0,
                      "seen": 0}
u._save(d)
PY

# ---- the docker-host node --------------------------------------------------
# The suite needs one node whose daemon the controller can address, and it
# used to get one from DOCKER_HOST: the server mirrored the variable into an
# `ssh`-kind row at boot. That kind is retired (roadmap #24) and so is the
# seed, so the harness enrolls the node the way an operator now does — mint a
# token, then present it on the agent channel.
#
# Two things are written rather than probed, because this container is not a
# node and cannot pretend to be one:
#   * X-Forwarded-For, so the row records the address the stub docker answers
#     for (`stub`) instead of 127.0.0.1, which is also where every OTHER node
#     a test enrolls dials in from;
#   * sshd in the census, because nodes._addr only hands out an ssh address
#     for a node that reports one, and devapp.available() needs that address.
#     There is no sshd in here and no way to bind port 22 without privileges.
# This is the same shape nodes.mjs already uses for its second docker node.
sandbox_json=$(curl -fs -u test:test -H 'Content-Type: application/json' \
    -d '{"action":"enroll","name":"sandbox","user":"bb"}' \
    "http://127.0.0.1:$PORT/api/v1/nodes") || {
        cat "$S/server.log"; die "could not mint the sandbox node's token"; }
sandbox_tok=$(printf '%s' "$sandbox_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
sandbox_node=$(curl -fs -H "Authorization: Bearer $sandbox_tok" \
    -H 'Content-Type: application/json' -H 'X-Forwarded-For: stub' \
    -d '{"user":"bb","version":"harness","census":{"cpu":4,"mem_mb":8192,
         "arch":"x86_64","system":"linux","sshd":true,"docker":true}}' \
    "http://127.0.0.1:$PORT/api/v1/agent/enroll") || {
        cat "$S/server.log"; die "the sandbox node would not enroll"; }

# ...and something on the node to take its jobs. Compose on an agent node is
# the agent's, so without this every Up and Rebuild in the suite would queue
# and then be reconciled away. agent-stub.py's header says why it is a stub
# and not the shipped agent.
STUB_AGENT_URL="http://127.0.0.1:$PORT" \
STUB_AGENT_DIR="$S/sandboxdata" \
STUB_AGENT_TOKEN="$(printf '%s' "$sandbox_node" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')" \
DOCKER_STUB_STATE="$S/dockerstate" PATH="$S/bin:$PATH" \
    python3 "$HERE/agent-stub.py" > "$S/agent-stub.log" 2>&1 &
stub_pid=$!

# ---- tests -----------------------------------------------------------------
if [ $# -gt 0 ]; then
    tests=()
    for t in "$@"; do tests+=("$HERE/${t%.mjs}.mjs"); done
else
    tests=()
    for t in "$HERE"/*.mjs; do [ "$(basename "$t")" = lib.mjs ] || tests+=("$t"); done
fi
rc=0
for t in "${tests[@]}"; do
    fresh
    log "== $(basename "$t") =="
    DASHBOARD_TEST_URL="http://127.0.0.1:$PORT/" DASHBOARD_TEST_CHROME="$CHROME" \
    DASHBOARD_TEST_DIR="$S" node "$t" || rc=1
done
[ "$rc" = 0 ] && log "dashboard tests: all passed" || warn "dashboard tests: FAILURES above"
exit "$rc"
