#!/usr/bin/env bash
#
# Split a long-running process's output: everything into its own file, and the
# lines worth interrupting somebody for onto stdout as well.
#
# The dashboard and ttyd write to files of their own, which is right — a
# dashboard poll is chatty and the boot log is a story with a beginning. But it
# meant the session log ended when the hooks finished: anything that went wrong
# an hour later was in a different file, and nothing in the first file said so.
#
# So this reads the stream, appends all of it where it was always going, and
# copies the warnings and errors to stdout — which, for anything started from a
# startup hook, is the container's own stream and therefore the boot log. One
# file to read, with the detail next door.
#
# Usage:  CMD 2>&1 | log-split.sh /path/to/full.log tag
#
set -uo pipefail          # no -e: a write that fails must not end the split

full="${1:?usage: log-split.sh FULL_LOG [TAG]}"
tag="${2:-}"

# Deliberately broad, and deliberately not anchored. These streams are Python
# tracebacks, compose output and whatever a library decided to print, so there
# is no format to match on — only words that mean somebody should look.
want='WARN|ERROR|Error|Traceback|Exception|CRITICAL|refused|denied|failed|Failed'

while IFS= read -r line; do
    printf '%s\n' "$line" >> "$full" 2>/dev/null || true
    if printf '%s' "$line" | grep -qE "$want"; then
        printf '[builderbot] %s%s\n' "${tag:+$tag: }" "$line"
    fi
done

# The stream ended, which for these processes means the process did. Worth a
# line in both places: a dashboard that exited is the single most confusing
# thing that can happen to somebody looking at a page that stopped updating.
printf '%s exited\n' "${tag:-process}" >> "$full" 2>/dev/null || true
printf '[builderbot] WARN: %s exited — see %s\n' "${tag:-process}" "$full"
