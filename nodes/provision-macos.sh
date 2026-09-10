#!/bin/bash
#
# Enroll a Mac as a BuilderBot node — a GUEST node (roadmap R23): one
# directory and one launchd agent, and nothing outside them. The Mac stays
# its owner's machine: no accounts made, no daemon, no root, nothing in
# /etc, and --remove takes exactly what this put there back out again.
#
# What a Mac node is for: building what only a Mac builds — iOS, macOS, the
# Apple half of a Flutter app — with Xcode, and a packages store of its own
# scope (darwin-arm64 or darwin-x86_64) under the same share the Linux
# nodes use, so nothing lands on top of theirs (roadmap R19).
#
# Run it as yourself, once:
#
#   bash provision-macos.sh --controller https://builderbot.example --token bbe_…
#
# Written for the bash macOS ships (3.2): no associative arrays, no mapfile,
# nothing newer than 2007. Its own file rather than a branch of
# nodes/provision-linux.sh for that reason and one more — that script provisions a
# machine, and this one only adds a footprint to somebody's.
#
set -eu

FOOT="${BUILDERBOT_HOME:-$HOME/.builderbot}"
PLIST="$HOME/Library/LaunchAgents/dev.builderbot.agent.plist"
LABEL="dev.builderbot.agent"
CONTROLLER=""; TOKEN=""; PACKAGES=""; REMOVE=0; CHECK_ONLY=0

usage() {
    cat <<'EOF'
usage: bash provision-macos.sh --controller URL --token bbe_… [--packages PATH]
       bash provision-macos.sh --check
       bash provision-macos.sh --remove

With no arguments this prints the help and changes nothing. The command to
run is the one the dashboard's Nodes tab gives you: Enroll node mints a
token and prints this line with the address and the token in it.

  --controller URL     the dashboard's address, as you open it in a browser
  --token bbe_…        an enrollment token from the Nodes tab (good once, for a day)
  --packages PATH      where this Mac's packages store is. Point it at the same
                       share the Linux nodes use, mounted over SMB (say
                       /Volumes/SDK): this machine's packages land under
                       <path>/darwin-<arch> and nobody else's are touched.
                       Default: ~/.builderbot/packages, on this disk.
  --check              only the pre-flight: say whether this Mac can be a
                       node, change nothing, exit 0 or 1.
  --remove             take the footprint away: the launchd agent, the
                       directory (stores included — say so if that is not
                       what you want), and nothing else, because nothing
                       else was put there.

The footprint is ~/.builderbot (BUILDERBOT_HOME to move it) and one launchd
agent, ~/Library/LaunchAgents/dev.builderbot.agent.plist, that runs as you
at login. No root is used or asked for.
EOF
}

# No arguments: the help, and nothing changed.
if [ $# -eq 0 ]; then
    usage
    exit 0
fi
while [ $# -gt 0 ]; do
    case "$1" in
        --controller) CONTROLLER="$2"; shift 2 ;;
        --token) TOKEN="$2"; shift 2 ;;
        --packages) PACKAGES="$2"; shift 2 ;;
        --check) CHECK_ONLY=1; shift ;;
        --remove) REMOVE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 1 ;;
    esac
done

say()  { printf '\n== %s\n' "$1"; }
warn() { printf '\n!! %s\n' "$1" >&2; }

# ---- taking it away --------------------------------------------------------
if [ "$REMOVE" = 1 ]; then
    say "removing the BuilderBot footprint"
    if [ -f "$PLIST" ]; then
        launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST" && printf '   removed %s\n' "$PLIST"
    fi
    if [ -d "$FOOT" ]; then
        rm -rf "$FOOT" && printf '   removed %s\n' "$FOOT"
    fi
    printf '   nothing else was here to remove. On the dashboard, Remove the node on its row.\n'
    exit 0
fi

# ---- pre-flight ------------------------------------------------------------
# Before anything is written: what this Mac has, and what it lacks. A FAIL
# stops with the whole list printed; a WARN is something to know.
say "checking this Mac"
FAILED=0
chk() {
    case "$1" in
        ok)   printf '   ok    %s\n' "$2" ;;
        warn) printf '   WARN  %s\n' "$2" ;;
        fail) printf '   FAIL  %s\n' "$2"; FAILED=1 ;;
    esac
}
if [ "$(uname -s)" = Darwin ]; then chk ok "macOS $(sw_vers -productVersion 2>/dev/null || echo '?') on $(uname -m)"
else chk fail "this is $(uname -s), and this script is for macOS — nodes/provision-linux.sh is the one for Linux"; fi
if [ "$(id -u)" = 0 ]; then chk fail "run this as yourself, not root: a guest node is one directory in your home and a launchd agent that runs as you"; fi
if xcode-select -p >/dev/null 2>&1; then chk ok "Xcode command line tools at $(xcode-select -p)"
else chk fail "no Xcode command line tools: run  xcode-select --install  and come back (git and clang live there)"; fi
if command -v python3 >/dev/null 2>&1; then chk ok "python3: $(python3 --version 2>&1)"
else chk fail "no python3 — it comes with the command line tools above"; fi
if command -v brew >/dev/null 2>&1; then chk ok "Homebrew at $(command -v brew)"
else chk warn "no Homebrew: a recipe's system packages (tmux, ttyd for sessions) cannot be installed by the agent; https://brew.sh"; fi
if command -v git >/dev/null 2>&1; then chk ok "git: $(git --version 2>&1)"
else chk fail "no git"; fi
xcode="$(find /Applications -maxdepth 1 -name 'Xcode*.app' 2>/dev/null | head -1)"
if [ -n "$xcode" ]; then chk ok "Xcode: $xcode"
else chk warn "no Xcode.app: iOS and macOS apps need it — the App Store, or the xcodes recipe from the Tools tab once enrolled"; fi
if [ -n "$PACKAGES" ]; then
    if [ -d "$PACKAGES" ] && [ -w "$PACKAGES" ]; then chk ok "packages store at $PACKAGES (this Mac's scope: darwin-$(uname -m))"
    else chk fail "$PACKAGES is not a writable directory — mount the share first (Finder: Go > Connect to Server, smb://…), or use a directory of this Mac's"; fi
fi
avail="$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}')"
if [ -n "$avail" ]; then
    if [ "$avail" -ge 20 ]; then chk ok "${avail}G free in $HOME"
    else chk warn "only ${avail}G free in $HOME — Xcode alone wants 15"; fi
fi
if [ -n "$CONTROLLER" ]; then
    if curl -fsk --max-time 10 -o /dev/null "${CONTROLLER%/}/" 2>/dev/null; then chk ok "controller ${CONTROLLER} answers"
    else chk warn "${CONTROLLER} does not answer from here — enrollment will fail until it does"; fi
fi
if [ "$FAILED" = 1 ]; then
    warn "this Mac is not ready to be a node — nothing was changed"
    exit 1
fi
if [ "$CHECK_ONLY" = 1 ]; then printf '\n   this Mac can be a node.\n'; exit 0; fi
if [ -z "$CONTROLLER" ] || [ -z "$TOKEN" ]; then
    echo "--controller and --token go together, and enrolling needs both" >&2; exit 1
fi

# ---- the footprint ---------------------------------------------------------
say "the footprint: $FOOT"
mkdir -p "$FOOT/bin" "$FOOT/data" "$FOOT/cache" "$FOOT/artifacts" "$FOOT/log"
[ -n "$PACKAGES" ] || { PACKAGES="$FOOT/packages"; mkdir -p "$PACKAGES"; }
AGENT="$FOOT/bin/builderbot-agent"
NODE_JSON="$FOOT/node.json"

say "the agent, from ${CONTROLLER}"
hdr="$(mktemp)"
curl -fsSL -D "$hdr" -H "Authorization: Bearer ${TOKEN}" \
     "${CONTROLLER%/}/api/v1/agent/download" -o "${AGENT}.new" \
    || { warn "could not download the agent from ${CONTROLLER} — is that the dashboard's address, and is the token unused?"; rm -f "$hdr" "${AGENT}.new"; exit 1; }
want="$(tr -d '\r' < "$hdr" | awk 'tolower($1)=="x-agent-digest:"{print $2}')"
got="sha256:$(shasum -a 256 "${AGENT}.new" | cut -d' ' -f1)"
rm -f "$hdr"
if [ -n "$want" ] && [ "$want" != "$got" ]; then
    warn "the agent that arrived does not match the digest the controller sent (${got} vs ${want})"
    rm -f "${AGENT}.new"; exit 1
fi
chmod 755 "${AGENT}.new"; mv -f "${AGENT}.new" "$AGENT"

# Enrolled as this account, with the stores under the footprint (the
# packages store wherever --packages said). The credential it keeps is this
# node's own row and nothing else.
say "enrolling as $(id -un)"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
BUILDERBOT_NODE_JSON="$NODE_JSON" "$AGENT" enroll --controller "$CONTROLLER" --token "$TOKEN" \
    --user "$(id -un)" \
    --store "data=$FOOT/data" --store "packages=$PACKAGES" \
    --store "cache=$FOOT/cache" --store "artifacts=$FOOT/artifacts"

# ---- the launchd agent -----------------------------------------------------
# Runs as you, at login, restarted if it stops; its log beside it. What a
# systemd unit is on the sandbox, in launchd's words.
say "the launchd agent: $LABEL"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array><string>$(command -v python3)</string><string>${AGENT}</string><string>run</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>BUILDERBOT_NODE_JSON</key><string>${NODE_JSON}</string>
    <key>BUILDERBOT_RUNNER_DIR</key><string>${FOOT}/runner</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>HOME</key><string>${HOME}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>${FOOT}/log/agent.log</string>
  <key>StandardErrorPath</key><string>${FOOT}/log/agent.log</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
sleep 2
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
    printf '   running; log at %s/log/agent.log\n' "$FOOT"
else
    warn "the agent did not stay up — read $FOOT/log/agent.log"
fi

cat <<EOF

Done. This Mac is a GUEST node: the dashboard's Nodes tab shows it live
within a minute, with Storage and Network not offered (they are yours), and
the Tools tab installs into its own scope of the packages store,
$PACKAGES/darwin-$(uname -m). Root is never asked for here.

  launchctl print gui/$(id -u)/$LABEL     is it running
  tail -f $FOOT/log/agent.log             what it is doing
  bash provision-macos.sh --remove        take it all away again

Sessions on this Mac (a Claude terminal here rather than on the controller)
need the projects share mounted at /workspace — on macOS that is one line
in /etc/synthetic.conf and an SMB mount — and are not set up by this script.
EOF
