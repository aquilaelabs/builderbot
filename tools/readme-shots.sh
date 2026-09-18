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
# The invented image this staged instance claims to be. One variable, because
# the owner's `image_seen` has to match it exactly or the welcome panel opens
# itself over every picture — which is what it did.
REV="abc1234def5678901234567890abcdef12345678"
BUILT="2026-09-11T09:14Z"
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
ttyd_ro_pid=""
cleanup() {
    [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
    [ -n "$ttyd_pid" ]   && kill "$ttyd_pid"   2>/dev/null || true
    [ -n "$ttyd_ro_pid" ] && kill "$ttyd_ro_pid" 2>/dev/null || true
    case "$(tmux display-message -p '#{socket_path}' 2>/dev/null)" in
        "$S"/*) tmux kill-server 2>/dev/null || true ;;
    esac
    # BB_SHOTS_KEEP leaves the staged instance's logs behind: when a picture
    # comes out wrong the answer is in $S/server.log or $S/ttyd.log, and this
    # script's whole point is that nobody runs it often enough to remember.
    [ -n "${BB_SHOTS_KEEP:-}" ] && { log "kept $S"; return; }
    rm -rf "$S" "$W"
}
trap 'cleanup' EXIT

# ---- a workspace worth photographing ---------------------------------------
# Three invented projects that between them light up what the Projects card
# can show: a clean GitHub-linked repo, a local one with no remote (the link
# chain), and one carrying static-analysis findings.
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
  printf '# meal-planner\n\nFlask and SQLAlchemy. `flask run` for the dev server.\n' > CLAUDE.md
  git add -A && git commit -qm "Note how to run it" )
seed orbit                       # no remote: wears the link-to-GitHub chain
( cd "$W/orbit"
  printf '# orbit\n\nPure python, no dependencies. `pytest` is the suite.\n' > CLAUDE.md
  printf 'import math\n' > src/solver.py
  git add -A && git commit -qm "Add the two-body solver" )
seed blog-engine                 # the one the findings report covers
( cd "$W/blog-engine"
  git remote add origin git@github.com:acme/blog-engine.git )

# ---- the owner -------------------------------------------------------------
# A fresh state directory serves the first-run screen, and without this every
# picture in the README is that form. DASHBOARD_AUTH is the legacy fallback
# and no longer gets past it. Claimed directly rather than through the form,
# the way test/run.sh does it and for the same reason: the form enforces an
# eight-character password and this credential is `shots:shots`.
#
# The account is invented on purpose. These pictures go into a public
# repository, so nothing here may photograph a real name or address.
python3 - "$REPO/scripts/dashboard/users.py" "$S/state" "$REV" <<'EOF'
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("users", sys.argv[1])
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=sys.argv[2], write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
d = u.load()
d["users"]["shots"] = {"uid": u.mint_uid(), "role": "owner", "projects": ["*"],
                       "prefs": {"full_name": "Sam Example", "email": "you@example.com",
                                 # Read, or the welcome panel opens over every
                                 # picture the script takes.
                                 "welcome_seen": True,
                                 "image_seen": sys.argv[3]},
                       "password": u.hash_password("shots"), "created": 0, "seen": 0}
u._save(d)
EOF

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
# No --credential, and the same shape the container's own hook uses: the
# browser reaches a terminal through the dashboard's /term proxy, which does
# not carry one, so ttyd asking for Basic meant a 401 and a blank pane in
# every picture. Loopback only, which is what makes that safe.
env TMUX_TMPDIR="$TMUX_TMPDIR" WORKSPACE="$W" DASHBOARD_STATE="$S/state" \
    ttyd --port "$TTYD_PORT" --interface 127.0.0.1 \
         --url-arg --writable -t reconnect=5 "$REPO/scripts/dashboard/bb-tty" \
    > "$S/ttyd.log" 2>&1 &
ttyd_pid=$!
# A stubbed `claude`, so the Doctor card's sign-in line reads an invented
# account. Without it these pictures carry the operator's real email address
# into the repository — the card did not exist when this script was written,
# and a staged instance that quietly photographs one real thing is worse than
# one that photographs none, because nobody thinks to look.
mkdir -p "$S/bin"
cat > "$S/bin/claude" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = auth ] && [ "${2:-}" = status ]; then
    printf '{"loggedIn":true,"email":"you@example.com","subscriptionType":"max"}\n'
    exit 0
fi
exit 0
STUB
chmod +x "$S/bin/claude"
# A stamp, so the header carries a version rather than `unstamped`: the
# README spends a paragraph on that line being the answer to "which build is
# this", and a picture of it saying nothing teaches the opposite. Invented,
# and obviously so.
env TMUX_TMPDIR="$TMUX_TMPDIR" WORKSPACE="$W" DASHBOARD_PORT="$PORT" \
    BB_IMAGE_REV="$REV" BB_IMAGE_BUILT="$BUILT" \
    DASHBOARD_TTYD_PORT="$TTYD_PORT" BUILDER_HOME="$S/home" \
    FINDINGS_DIR="$S/reports" DASHBOARD_STATE="$S/state" DASHBOARD_AUTH="$AUTH" \
    PATH="$S/bin:$PATH" \
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
# DASHBOARD_PORT, because that is how `bb shot` knows which origin the
# credential belongs to: it sends the Authorization header to that port and
# nowhere else, so that shooting somebody else's page in the same run cannot
# carry it there (bug #49). Without it the staged instance on $PORT is not
# the dashboard as far as the flag is concerned, and every picture is the
# sign-in page.
shot() { DASHBOARD_PORT="$PORT" bash "$REPO/scripts/bb" shot "$@" --auth "$AUTH" --wait "${SHOT_WAIT:-9000}"; }
# Scale 1 wherever a terminal is in frame: ttyd's xterm canvas renders
# blank, at doubled font metrics, under deviceScaleFactor 2 in headless
# Chromium — found by taking these very screenshots. The phone dashboard
# view hides the terminal column, so it alone gets the crisp 2x.
# Tall enough to reach the toolchain cards: the sidebar has nine of them now,
# and a 900px frame cut off the ones this README spends paragraphs on.
shot "$BASE/"               "$OUT/dashboard.png"       --size 1440x1180 --scale 1
# No --resize: 390 at scale 2 is already 780 wide, so the flag only ever ran
# imagemagick to produce the same pixels — and imagemagick is in the
# controller's image and not on a node, which is where sessions are. The flag
# stays on bb shot for a shot that really does downscale.
shot "$BASE/?view=dash"     "$OUT/phone-dashboard.png" --size 390x844 --scale 2
shot "$BASE/?view=terminal" "$OUT/phone-terminal.png"  --size 390x844 --scale 1
log "wrote $OUT/{dashboard,phone-dashboard,phone-terminal}.png"
