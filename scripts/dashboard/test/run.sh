#!/usr/bin/env bash
# Run the dashboard's browser tests against an isolated instance.
#
# Nothing here touches the live dashboard: the server under test binds a spare
# port with its own scratch state directory, a fake workspace of four projects
# (one broken, one excluded), a crafted SARIF report, a stub `bb` whose doctor
# output the tests can flip, and throwaway tmux sessions on a PRIVATE tmux
# server (TMUX_TMPDIR under the scratch dir) — the live dashboard lists every
# session on the shared server, and a test session showing up there as a
# real tab was the first thing an operator noticed. Everything is torn down by
# PID and by name — never by pattern, which is how a previous session managed
# to kill the real dashboard while trying to stop a test one.
#
#   bb dashboard test            # every *.mjs in this directory
#   bb dashboard test cards      # just cards.mjs
#
# Playwright comes from the image (/usr/lib/node_modules); the browsers live
# on the SDK share and are found the way bb finds them. Missing either, the
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

export NODE_PATH="${NODE_PATH:-/usr/lib/node_modules}"
node -e "require.resolve('playwright')" 2>/dev/null \
    || { log "[skip] playwright is not installed in this image"; exit 0; }
# The same search bb uses: the browsers live on the SDK share now, and the
# /opt path is a symlink that only exists once the startup hook has run.
# The checkout's bb, not the one on PATH: this harness tests this tree, and
# the installed copy is whatever the running image shipped — which may not
# know the flag yet.
CHROME="$(bash "$DASH/../bb" shot --print-chromium 2>/dev/null || true)"
[ -x "${CHROME:-}" ] || { log "[skip] no Playwright chromium — install it with: bb sdk install playwright"; exit 0; }
command -v tmux >/dev/null || { log "[skip] tmux is not installed"; exit 0; }

PORT="${DASHBOARD_TEST_PORT:-8093}"
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
cleanup() {
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    [ -n "$agent_pid" ] && kill "$agent_pid" 2>/dev/null || true
    # The private server only — guarded again, because this is the line that
    # once took the real one down.
    case "$(tmux display-message -p '#{socket_path}' 2>/dev/null)" in
        "$S"/*) tmux kill-server 2>/dev/null || true ;;
    esac
    rm -rf "$S"
}

# ---- fixtures --------------------------------------------------------------
mkdir -p "$S"/{ws,reports,state,bin,sdk,androidsdk}
# ep.silon: a project whose name tmux would rewrite in a session name (`.` →
# `_`), so the page, the server and bb-tty have to agree on the substitution.
( cd "$S/ws" && mkdir -p alpha beta gamma delta ep.silon \
    && for d in alpha beta gamma delta ep.silon; do echo x > "$d/README.md"; done \
    && for d in alpha beta delta ep.silon; do git init -q "$d"; done \
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
echo '["delta"]' > "$S/state/excluded-projects.json"
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
# Stub: deterministic `bb doctor`, and an `bb sdk` that makes and removes
# directories instead of downloading gigabytes — enough for the Tools card to
# watch a package appear and disappear.
if [ "${1:-}" = doctor ]; then cat "${BB_DOCTOR_FIXTURE:?}"; fi
if [ "${1:-}" = sdk ]; then
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
                     printf 'system-images;android-30;google_apis;x86_64\tandroid-30\tgoogle_apis\t3300000\n'
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
                   res("G1", "error", "scan/gamma/g.c"), res("D1", "warning", "scan/delta/d1.c")]}]}
open(sys.argv[1], "w").write(json.dumps(doc))
EOF
# Each test file starts from the same place: an unwritten layout and both
# throwaway sessions present — a file that minimizes tabs or ends a session
# must not hand that state to the next.
fresh() {
    rm -f "$S/state/tabs.json" "$S/state/cards.json"
    echo '["delta"]' > "$S/state/excluded-projects.json"   # a test that excludes must not hand that on
    # Projects a test created through /api/create go too — anything that is
    # not one of the five fixtures. Scoped to $S, like every rm in this file.
    find "$S/ws" -maxdepth 1 -mindepth 1 -type d \
        ! -name alpha ! -name beta ! -name gamma ! -name delta ! -name ep.silon \
        ! -name toolstore -exec rm -rf {} +
    rm -rf "$S/home/.ssh"           # deploy-key selectors a test wrote
    rm -rf "$S/sdk" "$S/androidsdk"; mkdir -p "$S/sdk" "$S/androidsdk"
    cp "$S/doctor-ok.txt" "$S/doctor.txt"
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
env WORKSPACE="$S/ws" DASHBOARD_PORT="$PORT" DASHBOARD_TTYD_PORT=7999 BUILDER_HOME="$S/home" \
    TEMPLATE_MD="$DASH/../../config/templates/project-CLAUDE.md" \
    BB_BIN="$S/bin/bb" SDK_TEST_ROOT="$S/sdk" ANDROID_HOME="$S/androidsdk" \
    PKG_AUTOCHECK=0 \
    SSH_AUTH_SOCK="$S/ssh-agent.sock" \
    FINDINGS_DIR="$S/reports" DASHBOARD_STATE="$S/state" DASHBOARD_AUTH=test:test \
    BB_DOCTOR_FIXTURE="$S/doctor.txt" PATH="$S/bin:$PATH" \
    python3 "$DASH/server.py" > "$S/server.log" 2>&1 &
pid=$!
for _ in $(seq 40); do
    curl -fs -u test:test -o /dev/null "http://127.0.0.1:$PORT/api/status" && break
    kill -0 "$pid" 2>/dev/null || { cat "$S/server.log"; die "server exited"; }
    sleep 0.25
done

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
