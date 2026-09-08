#!/usr/bin/env bash
#
# roles: controller
#
# Git identity, credential helper and SSH known_hosts.
#
set -euo pipefail
. /opt/builderbot/scripts/lib/common.sh

# The commit identity, from the Settings tab (roadmap R29): saved there it is
# applied at once; this makes sure a fresh home has it too. The variables it
# replaced are read for one release.
GIT_USER_NAME="$(bb_setting git_name GIT_USER_NAME "")"
GIT_USER_EMAIL="$(bb_setting git_email GIT_USER_EMAIL "")"
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

# A git token belongs to one project: typed into the clone dialog, stored at
# /config/gitcreds/<project> and named by that repo's own .git/config, so a
# token that opens one repository opens one repository.
#
# A session-visible GITHUB_PAT is still honoured, because that variable exists
# to mint node runner tokens and shielding it is the operator's choice — when
# it is not shielded, refusing to use it would be pretending not to see it.
if [ -n "${GITHUB_PAT:-}" ]; then
    if printf '%s' "$GITHUB_PAT" | gh auth login --with-token >/dev/null 2>&1; then
        gh auth setup-git >/dev/null 2>&1 || true
        log "gh CLI authenticated from GITHUB_PAT"
    else
        warn "gh auth login failed — check GITHUB_PAT scopes"
    fi
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
