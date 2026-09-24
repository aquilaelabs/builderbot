#!/bin/sh
# The agent's version is the one number in this tree a person moves by hand,
# and a node compares the FILE while the Nodes tab names the NUMBER: when the
# file moved without it, three tabs said "runs 0.6.92 and ships 0.6.92" and
# refused work (B221). So scripts/agent/builderbot-agent.py may not change
# against the branch's base without AGENT_VERSION's patch moving.
#
# The base is origin/main's merge point when there is one (a checkout with
# history), origin/main itself on a shallow checkout that fetched it (CI),
# the previous commit otherwise; a tree with no base to compare is said, not
# passed. Run by `bb lint` and by the lint workflow, so the two agree.
# Exit 0 clean, 1 on a finding, 0 with [skip] when it cannot compare.
set -eu
f=scripts/agent/builderbot-agent.py
if [ ! -f "$f" ] || ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "  [skip] no agent here, or not a git tree"; exit 0
fi
base=""
if git rev-parse --verify -q origin/main >/dev/null 2>&1; then
    base="$(git merge-base origin/main HEAD 2>/dev/null || echo origin/main)"
elif git rev-parse --verify -q HEAD~1 >/dev/null 2>&1; then
    base="HEAD~1"
fi
if [ -z "$base" ]; then
    echo "  [skip] no base to compare the agent against (a shallow checkout with one commit)"; exit 0
fi
short="$(git rev-parse --short "$base" 2>/dev/null || echo "$base")"
if git diff --quiet "$base" -- "$f" 2>/dev/null; then
    echo "  [ok]   the agent file is as it is on $short"; exit 0
fi
now="$(grep '^AGENT_VERSION = ' "$f" | head -n 1)"
# grep reads the whole stream: an early close under git show is SIGPIPE, and
# a pipefail shell then ends the caller without a word.
then_="$(git show "$base:$f" 2>/dev/null | grep '^AGENT_VERSION = ' || true)"
then_="$(printf '%s\n' "$then_" | head -n 1)"
if [ -n "$now" ] && [ "$now" != "$then_" ]; then
    echo "  [ok]   the agent file changed and its version moved with it (${now#AGENT_VERSION = }, was ${then_#AGENT_VERSION = })"; exit 0
fi
echo "  [FAIL] $f changed since $short and AGENT_VERSION (${now#AGENT_VERSION = }) did not: a node compares the file and the row names the number, so bump the patch"
exit 1
