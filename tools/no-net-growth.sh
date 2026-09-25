#!/bin/sh
# The everything-files only get smaller. Four files hold what the one-file
# rule says should be many (roadmap R77), and every feature that lands in
# one makes the next land there too. So each carries a ceiling in
# tools/ratchet.txt: this fails when a file is over its ceiling, and a
# change that shrinks a file lowers the ceiling in the same commit.
#
#   (default)  fail if any file is over its ceiling: `bb rules check growth`
#   --tighten  write the current counts as the new ceilings, for a commit
#              that shrank one (a count is never raised by this)
set -u
here="$(cd "$(dirname "$0")/.." && pwd)"
table="$here/tools/ratchet.txt"
mode="${1:-}"
rc=0
tmp="$(mktemp)"
while IFS= read -r line; do
    case "$line" in ''|'#'*) printf '%s\n' "$line" >> "$tmp"; continue ;; esac
    file="${line% *}"; max="${line##* }"
    now="$(wc -l < "$here/$file" | tr -d ' ')"
    if [ "$mode" = --tighten ]; then
        [ "$now" -lt "$max" ] && max="$now"
        printf '%s %s\n' "$file" "$max" >> "$tmp"
        printf '  %-36s %6s lines, ceiling %s\n' "$file" "$now" "$max"
        continue
    fi
    if [ "$now" -gt "$max" ]; then
        printf '  %-36s %6s lines, over its ceiling of %s by %s: move something out (bb map sections) rather than raising it\n' \
            "$file" "$now" "$max" "$((now - max))"
        rc=1
    else
        printf '  %-36s %6s lines, ceiling %s\n' "$file" "$now" "$max"
    fi
done < "$table"
if [ "$mode" = --tighten ]; then mv "$tmp" "$table"; echo "ceilings written to tools/ratchet.txt"; else rm -f "$tmp"; fi
[ "$rc" = 0 ] && echo "no everything-file grew past its ceiling"
exit "$rc"
