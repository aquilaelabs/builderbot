#!/usr/bin/env bash
#
# Regenerate docs/screenshots/ from a staged dashboard.
#
# Boots the checkout's server.py and a real ttyd against a scratch workspace
# of invented projects, then photographs it with `bb shot` — which is half
# the point: the screenshots document the dashboard, and taking them
# exercises the container's own camera. Staged rather than shot from the
# live instance so the pictures are reproducible and can never carry a real
# terminal's scrollback into the repository.
#
# The tmux isolation below is copied from scripts/dashboard/test/run.sh, and
# the shape is not optional: a throwaway session must never land on — and
# this cleanup must never kill — the real server. TMUX is unset first
# because inside a tmux session the client ignores TMUX_TMPDIR, and the
# private socket is verified before anything else runs.
#
# Run inside the container, from anywhere in the checkout:
#     bash tools/readme-shots.sh
#
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(dirname "$HERE")"
OUT="$REPO/docs/screenshots"
PORT="${README_SHOT_PORT:-8094}"
TTYD_PORT=$((PORT + 1))
AUTH="shots:shots"

. /opt/builderbot/scripts/lib/common.sh 2>/dev/null || {
    log()  { printf '[readme-shots] %s\n' "$*"; }
    die()  { printf '[readme-shots] ERROR: %s\n' "$*" >&2; exit 1; }
}
command -v ttyd >/dev/null || die "ttyd is not installed"
command -v tmux >/dev/null || die "tmux is not installed"

S="$(mktemp -d "${TMPDIR:-/tmp}/readme-shots.XXXXXX")"
# The staged workspace lives at a fixed, short path rather than inside $S:
# the shell prompts in the pictures show the cwd, and a mktemp suffix in
# every prompt reads as noise. Namespaced and recreated from scratch, so the
# rm below only ever eats this script's own leavings.
W=/tmp/workspace
rm -rf "$W"
mkdir -p "$W"
# ---- private tmux server (see the header; verified, not assumed) -----------
unset TMUX
export TMUX_TMPDIR="$S/tmux"
mkdir -p "$TMUX_TMPDIR"
tmux new-session -d -s probe -c /tmp
sock="$(tmux display-message -t probe -p '#{socket_path}' 2>/dev/null || true)"
case "$sock" in
    "$S"/*) tmux kill-session -t probe ;;
    *) tmux kill-session -t probe 2>/dev/null
       die "refusing to run: tmux is on '${sock:-?}', not the private server" ;;
esac
server_pid=""
ttyd_pid=""
cleanup() {
    [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
    [ -n "$ttyd_pid" ]   && kill "$ttyd_pid"   2>/dev/null || true
    case "$(tmux display-message -p '#{socket_path}' 2>/dev/null)" in
        "$S"/*) tmux kill-server 2>/dev/null || true ;;
    esac
    rm -rf "$S" "$W"
}
trap 'cleanup' EXIT

# ---- a workspace worth photographing ---------------------------------------
# Three invented projects that between them light up what the Projects card
# can show: a clean GitHub-linked repo, a local one with no remote (the link
# chain), and one with findings and no CLAUDE.md yet (the amber fix link).
mkdir -p "$S"/{state,reports,home}
seed() { # seed NAME  — a small real repo with a plausible history
    local d="$W/$1"
    git init -q -b main "$d"
    ( cd "$d"
      printf '# %s\n' "$1" > README.md
      mkdir -p src && printf 'def main():\n    pass\n' > src/main.py
      git add -A && git commit -qm "Start the project" )
}
seed meal-planner
( cd "$W/meal-planner"
  printf 'flask\nsqlalchemy\n' > requirements.txt
  git add -A && git commit -qm "Pin the web stack"
  git remote add origin git@github.com:acme/meal-planner.git
  cp "$REPO/config/templates/project-CLAUDE.md" CLAUDE.md )
seed orbit                       # no remote: wears the link-to-GitHub chain
( cd "$W/orbit"
  cp "$REPO/config/templates/project-CLAUDE.md" CLAUDE.md
  printf 'import math\n' > src/solver.py
  git add -A && git commit -qm "Add the two-body solver" )
seed blog-engine                 # findings, and no CLAUDE.md yet
( cd "$W/blog-engine"
  git remote add origin git@github.com:acme/blog-engine.git )

python3 - "$S/reports/scan.sarif" <<'EOF'
import json, sys
def res(rule, level, uri, line, msg):
    return {"ruleId": rule, "level": level, "message": {"text": msg},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri},
                                                "region": {"startLine": line}}}]}
doc = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "bandit", "rules": []}},
       "results": [
           res("B602", "error", "blog-engine/render.py", 41,
               "subprocess call with shell=True identified"),
           res("B105", "warning", "blog-engine/config.py", 12,
               "possible hardcoded password"),
           res("B303", "note", "blog-engine/cache.py", 7,
               "use of insecure MD2/MD4/MD5 hash function"),
       ]}]}
open(sys.argv[1], "w").write(json.dumps(doc))
EOF

# Two shells with something on screen: one in orbit poking at the repo, one
# at the workspace root. Typed now, into tmux; ttyd redraws it on attach.
# Sized close to what the iframe will ask for, so nothing typed now gets
# rewrapped on attach; `clear` first drops the login banner from the frame.
tmux new-session -d -x 200 -y 50 -s shell-orbit -c "$W/orbit"
tmux new-session -d -x 200 -y 50 -s shell -c "$W"
# The look the container actually ships: status style, mouse rules, PgUp.
[ -f "$HOME/.tmux.builderbot.conf" ] && tmux source-file "$HOME/.tmux.builderbot.conf"
tmux send-keys -t shell-orbit "clear" Enter "git log --oneline" Enter
sleep 1
tmux send-keys -t shell-orbit "git status" Enter
tmux send-keys -t shell "clear" Enter "ls" Enter
# A Claude session for the Sessions card. Created BEFORE anything attaches:
# bb-tty's new-session -A only attaches when the name exists, so no real
# claude process is ever launched for a screenshot.
tmux new-session -d -s claude-meal-planner -c "$W/meal-planner"

# The strip the page opens with: the orbit shell front and center. No claude
# tab — a tab means an iframe, an iframe means bb-tty runs the command.
cat > "$S/state/tabs.json" <<EOF
{"rev": 1, "active": 0, "panes": ["t1", null], "tabs": [
  {"id": "t1", "kind": "term", "arg": "shell:orbit", "label": "sh: orbit"},
  {"id": "t2", "kind": "term", "arg": "shell", "label": "workspace"}]}
EOF

# ---- the app: real ttyd, the checkout's server -----------------------------
env TMUX_TMPDIR="$TMUX_TMPDIR" WORKSPACE="$W" DASHBOARD_STATE="$S/state" \
    ttyd --port "$TTYD_PORT" --interface 127.0.0.1 --credential "$AUTH" \
         --url-arg --writable -t reconnect=5 "$REPO/scripts/dashboard/bb-tty" \
    > "$S/ttyd.log" 2>&1 &
ttyd_pid=$!
env TMUX_TMPDIR="$TMUX_TMPDIR" WORKSPACE="$W" DASHBOARD_PORT="$PORT" \
    DASHBOARD_TTYD_PORT="$TTYD_PORT" BUILDER_HOME="$S/home" \
    TEMPLATE_MD="$REPO/config/templates/project-CLAUDE.md" \
    FINDINGS_DIR="$S/reports" DASHBOARD_STATE="$S/state" DASHBOARD_AUTH="$AUTH" \
    python3 "$REPO/scripts/dashboard/server.py" > "$S/server.log" 2>&1 &
server_pid=$!
for _ in $(seq 40); do
    curl -fs -u "$AUTH" -o /dev/null "http://127.0.0.1:$PORT/api/status" && break
    kill -0 "$server_pid" 2>/dev/null || { cat "$S/server.log"; die "server exited"; }
    sleep 0.25
done
sleep 5      # the first doctor run and status poll, so no card says loading

# ---- the photographs -------------------------------------------------------
mkdir -p "$OUT"
BASE="http://127.0.0.1:$PORT"
shot() { bash "$REPO/scripts/bb" shot "$@" --auth "$AUTH" --wait 4000; }
# Scale 1 wherever a terminal is in frame: ttyd's xterm canvas renders
# blank, at doubled font metrics, under deviceScaleFactor 2 in headless
# Chromium — found by taking these very screenshots. The phone dashboard
# view hides the terminal column, so it alone gets the crisp 2x.
# Tall enough to reach the toolchain cards: the sidebar has nine of them now,
# and a 900px frame cut off the ones this README spends paragraphs on.
shot "$BASE/"               "$OUT/dashboard.png"       --size 1440x1180 --scale 1
shot "$BASE/?view=dash"     "$OUT/phone-dashboard.png" --size 390x844 --scale 2 --resize 780
shot "$BASE/?view=terminal" "$OUT/phone-terminal.png"  --size 390x844 --scale 1
log "wrote $OUT/{dashboard,phone-dashboard,phone-terminal}.png"
