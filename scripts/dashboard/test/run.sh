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
# Playwright and Chromium come from the image (/usr/lib/node_modules and
# /opt/pw-browsers); on an image that predates either, the run reports [skip]
# rather than passing by omission.
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
CHROME=/opt/pw-browsers/chromium          # the image's stable symlink, or an older image's revisioned path
[ -x "$CHROME" ] || CHROME="$(find /opt/pw-browsers -path '*/chromium-*/chrome-linux*/chrome' -type f 2>/dev/null | head -1 || true)"
[ -x "${CHROME:-}" ] || { log "[skip] no Playwright chromium under /opt/pw-browsers"; exit 0; }
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
cleanup() {
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    # The private server only — guarded again, because this is the line that
    # once took the real one down.
    case "$(tmux display-message -p '#{socket_path}' 2>/dev/null)" in
        "$S"/*) tmux kill-server 2>/dev/null || true ;;
    esac
    rm -rf "$S"
}

# ---- fixtures --------------------------------------------------------------
mkdir -p "$S"/{ws,reports,state,bin}
# ep.silon: a project whose name tmux would rewrite in a session name (`.` →
# `_`), so the page, the server and bb-tty have to agree on the substitution.
( cd "$S/ws" && mkdir -p alpha beta gamma delta ep.silon \
    && for d in alpha beta gamma delta ep.silon; do echo x > "$d/README.md"; done \
    && for d in alpha beta delta ep.silon; do git init -q "$d"; done )
echo '["delta"]' > "$S/state/excluded-projects.json"
# alpha has a previous Claude conversation, so its Claude button offers the
# Resume / New chooser rather than starting straight away.
mkdir -p "$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)"
echo '{}' > "$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)/abc123.jsonl"
cat > "$S/bin/bb" <<'EOF'
#!/usr/bin/env bash
# Stub: deterministic `bb doctor`, everything else a cheap no-op.
if [ "${1:-}" = doctor ]; then cat "${BB_DOCTOR_FIXTURE:?}"; fi
exit 0
EOF
chmod +x "$S/bin/bb"
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
    cp "$S/doctor-ok.txt" "$S/doctor.txt"
    for n in shell-9 claude-alpha; do
        tmux has-session -t "$n" 2>/dev/null || tmux new-session -d -s "$n" -c /tmp
    done
}
fresh

# ---- server ----------------------------------------------------------------
env WORKSPACE="$S/ws" DASHBOARD_PORT="$PORT" DASHBOARD_TTYD_PORT=7999 BUILDER_HOME="$S/home" \
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
