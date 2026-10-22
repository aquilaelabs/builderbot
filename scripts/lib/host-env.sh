#!/usr/bin/env bash
# shellcheck shell=bash
#
# The environment the image's ENV lines give every process in the container,
# given to a controller installed bare metal (R90): sourced by host-boot.sh
# before it starts anything, and by the bb on the machine's PATH that the
# installer writes, so a shell's bb and the service see the same.
#
# Read in order: the release's own stamp (build.env, written when the
# installer laid the release out: the version, the commit, the global node
# modules' folder), then the operator's env file (the paths and settings,
# compose's half), then what the image fixes. Every name the Dockerfile sets
# with ENV is either here or named in unit/test_install_controller.py as the
# container's alone.
#
# Sourced as root by host-boot.sh and as the controller's account by bb; it
# reads two files root owns and writes nothing.

BB_CONTROLLER_ENV="${BB_CONTROLLER_ENV:-/etc/builderbot-controller/controller.env}"

set -a
# shellcheck disable=SC1091
[ -r /opt/builderbot/build.env ] && . /opt/builderbot/build.env
# shellcheck disable=SC1090
[ -r "$BB_CONTROLLER_ENV" ] && . "$BB_CONTROLLER_ENV"
set +a

export BUILDERBOT_INSTALL=bare-metal
export LANG="${LANG:-C.UTF-8}" LC_ALL="${LC_ALL:-C.UTF-8}"
export TZ="${TZ:-Etc/UTC}"
export NPM_CONFIG_FUND=false PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
export NODE_PATH="${NODE_PATH:-/usr/lib/node_modules}"
export BUILDER_HOME="${BUILDER_HOME:-/var/lib/builderbot-controller/home}"
export WORKSPACE="${WORKSPACE:-/srv/builderbot/projects}"
export DASHBOARD_STATE="${DASHBOARD_STATE:-/var/lib/builderbot-controller/config}"
export SDK_ROOT="${SDK_ROOT:-/var/lib/builderbot-controller/sdk}"
export SSH_AUTH_SOCK="${SSH_AUTH_SOCK:-/run/builderbot-controller/ssh-agent.sock}"
export PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers PLAYWRIGHT_SKIP_BROWSER_GC=1
# The image's PATH, with the controller's own home in place of /home/builder,
# and the python the installer picked first where the machine's python3 is
# older than the controller reads (a RHEL 9 rebuild's 3.9, beside its 3.12).
# /opt/builderbot/bin is the image's docker-exec wrappers, which a machine of
# its own has no use for.
export PATH="/usr/local/lib/builderbot-controller/bin:${BUILDER_HOME}/.npm-global/bin:${BUILDER_HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
