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

# Silence advice blocks that only *explain* a state git already reports, so the
# state itself is never hidden: detached HEAD still shows in status/checkout,
# and `git status` still lists every file. Advice that tells you how to resolve
# something — push rejections, merge conflicts — is deliberately left on.
git config --global advice.detachedHead false
git config --global advice.statusHints false
git config --global advice.waitingForEditor false

# Authenticate gh + git-over-https. GIT_PAT is the credential intended for
# this (session-visible by necessity); a session-visible GITHUB_PAT works too
# when shielding is off.
git_token="${GIT_PAT:-${GITHUB_PAT:-}}"
git_token_name="GIT_PAT"
[ -n "${GIT_PAT:-}" ] || git_token_name="GITHUB_PAT"

if [ -n "$git_token" ]; then
    if printf '%s' "$git_token" | gh auth login --with-token >/dev/null 2>&1; then
        gh auth setup-git >/dev/null 2>&1 || true
        log "gh CLI + git-over-https authenticated from ${git_token_name}"
    else
        warn "gh auth login failed — check ${git_token_name} scopes (needs Contents: read/write)"
    fi
elif sudo -n /opt/builderbot/scripts/mint-runner-token --check >/dev/null 2>&1; then
    log "GITHUB_PAT is shielded, so gh/git are NOT authenticated in this session."
    log "For git access pick one: shielded ssh key in /secrets/ssh, or set GIT_PAT"
    log "(a Contents-scoped token, readable by sessions by design), or 'gh auth login'."
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
