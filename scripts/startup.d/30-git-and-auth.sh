#!/usr/bin/env bash
#
# Git identity, credential helper and SSH known_hosts.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

if [ -n "${GIT_USER_NAME:-}" ]; then
    git config --global user.name "$GIT_USER_NAME"
fi
if [ -n "${GIT_USER_EMAIL:-}" ]; then
    git config --global user.email "$GIT_USER_EMAIL"
fi

# Sane defaults for a container that edits shares owned by another uid.
git config --global --add safe.directory '*'
git config --global init.defaultBranch main
git config --global pull.rebase false
git config --global core.editor "${GIT_EDITOR:-nano}"

# Authenticate gh + git-over-https from the PAT, when one is visible.
if [ -n "${GITHUB_PAT:-}" ]; then
    if printf '%s' "$GITHUB_PAT" | gh auth login --with-token >/dev/null 2>&1; then
        gh auth setup-git >/dev/null 2>&1 || true
        log "gh CLI authenticated from GITHUB_PAT"
    else
        warn "gh auth login failed — check GITHUB_PAT scopes"
    fi
elif sudo -n /opt/builderbot/scripts/mint-runner-token --check >/dev/null 2>&1; then
    log "GITHUB_PAT is shielded: the runner uses it via the root helper, but gh/git"
    log "are NOT auto-authenticated in this session — use SSH keys (recommended) or"
    log "run 'gh auth login' manually."
fi

# Pre-trust GitHub's SSH host keys so `git clone git@github.com:...` doesn't
# stall on an interactive prompt inside a non-tty job.
mkdir -p "${HOME}/.ssh"
chmod 700 "${HOME}/.ssh"
if [ ! -s "${HOME}/.ssh/known_hosts" ] || ! grep -q 'github.com' "${HOME}/.ssh/known_hosts" 2>/dev/null; then
    ssh-keyscan -t rsa,ecdsa,ed25519 github.com >> "${HOME}/.ssh/known_hosts" 2>/dev/null \
        && log "added github.com to known_hosts" \
        || warn "ssh-keyscan for github.com failed (offline?)"
fi
chmod 600 "${HOME}/.ssh/known_hosts" 2>/dev/null || true
