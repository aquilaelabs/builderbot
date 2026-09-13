#!/bin/sh
# No em dash goes into this repository. They read as a tell for generated
# text, and a codebase wearing one on every third line is making a claim
# about itself that nothing else here makes.
#
# Two modes, because the repository is not clean yet and a check that cannot
# pass is a check nobody runs:
#
#   (default) only what this branch ADDS. That has to be zero, and it is what
#             `bb rules check voice` runs before a session hands back.
#   --all     every one still in the tree, worst file first. The sweep's
#             progress bar, not a gate.
set -u
# The character, as its UTF-8 bytes, so this file does not carry the one
# thing it exists to forbid.
em=$(printf '\342\200\224')
mode="${1:-}"

if [ "$mode" = --all ]; then
    git ls-files -z | xargs -0 grep -coI "$em" 2>/dev/null \
        | awk -F: '$2 > 0 {n += $2; print $2 "\t" $1}' \
        | sort -rn | head -40
    total=$(git ls-files -z | xargs -0 grep -oI "$em" 2>/dev/null | wc -l)
    files=$(git ls-files -z | xargs -0 grep -lI "$em" 2>/dev/null | wc -l)
    echo
    echo "$total left, in $files file(s)"
    exit 0
fi

# A dash that is the WHOLE of something is CONTENT, not punctuation, and this
# does not look at those: a code span, an HTML text node holding nothing else
# (the minimize button IS that glyph), a string holding nothing else (a value
# that is not there, printed as a dash). Write one of those that way and both
# a reader and this checker can tell which kind it is.
strip_code () {
    sed -e 's/`[^`]*`//g' -e 's/>[[:space:]]*\xe2\x80\x94[[:space:]]*</></g' \
        -e "s/[\"'][[:space:]]*\xe2\x80\x94[[:space:]]*[\"']//g" \
        -e 's/|[[:space:]]*\xe2\x80\x94[[:space:]]*|/||/g'
}

base=$(git merge-base HEAD origin/main 2>/dev/null) || base=$(git rev-parse HEAD)
bad=0
# Tracked files: only the lines this branch adds. Untracked: all of it, since
# every line of a new file is one this branch adds.
for f in $(git diff --name-only "$base" 2>/dev/null; git ls-files --others --exclude-standard); do
    [ -f "$f" ] || continue
    if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        n=$(git diff -U0 "$base" -- "$f" | grep -I '^+' | grep -Iv '^+++' | strip_code | grep -c "$em" || true)
    else
        n=$(strip_code < "$f" | grep -cI "$em" 2>/dev/null || true)
    fi
    [ "${n:-0}" -gt 0 ] 2>/dev/null || continue
    echo "  $f: $n added line(s) with an em dash"
    bad=$((bad + n))
done
if [ "$bad" -gt 0 ]; then
    echo "no em dash goes into this repository: $bad on lines this branch adds."
    echo "A colon, a comma, a semicolon or brackets say the same thing."
    exit 1
fi
echo "no em dash on any line this branch adds"
