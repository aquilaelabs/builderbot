#!/bin/sh
# American spelling, everywhere in this repository: the house rule
# `spelling` (the operator's, 29 Sep). This is its check.
#
# Two modes, as tools/no-em-dash.sh has them:
#
#   (default) only what this branch ADDS. That has to be zero, and it is what
#             `bb rules check spelling` runs before a session hands back.
#   --all     every one in the tree, worst file first.
#
# The words are the ones this tree has actually carried, each by the part
# that differs, so an ending (-ed, -ing, -s, -ation) is caught with its
# stem. A name somebody else owns is theirs to spell: put it in a code span
# in prose, which this does not read, or add the line's file to SKIP.
set -u
# Assembled from halves, so this file does not carry what it forbids and
# can be checked like any other.
u=u; s=s; r=re
words="colo${u}r|behavio${u}r|favo${u}r|hono${u}r|labo${u}r|neighbo${u}r|flavo${u}r|rumo${u}r"
words="$words|cent${r}([sd]|\\b)|licen${u:+c}e|defen${u:+c}e|offen${u:+c}e|\\bg${r%e}ey|catalog${u}e|analy${s}e"
words="$words|(organi|recogni|reali|initiali|normali|seriali|synchroni|customi|authori|summari|prioriti|apologi)${s}(e|ing|ation)"
words="$words|(cance|labe|trave|mode)ll(ed|ing|er)|whil${s}t|art${r#r}fact"
# What is somebody else's to spell, or a record of what was: nothing yet.
SKIP='^$'
mode="${1:-}"

# An identifier somebody else spells is theirs: aria-labelledby is the ARIA
# attribute's own name (two l's in the spec), and the British-looking
# "labeledby" is no attribute at all, which is what B499 was.
l=l
strip_code () { sed -e 's/`[^`]*`//g' -e "s/aria-labe${l}${l}edby//gI"; }

if [ "$mode" = --all ]; then
    git ls-files -z | xargs -0 grep -ciIE "$words" 2>/dev/null \
        | awk -F: '$2 > 0 {print $2 "\t" $1}' | grep -vE "$SKIP" | sort -rn | head -40
    total=$(git ls-files -z | xargs -0 grep -oiIE "$words" 2>/dev/null | wc -l)
    echo
    echo "$total left"
    exit 0
fi

base=$(git merge-base HEAD origin/main 2>/dev/null) || base=$(git rev-parse HEAD)
bad=0
renamed=$(git diff -M --name-status "$base" 2>/dev/null | awk -F'\t' '$1 ~ /^R/ {print $3 "\t" $2}')
for f in $(git diff -M --name-only "$base" 2>/dev/null; git ls-files --others --exclude-standard); do
    [ -f "$f" ] || continue
    printf '%s\n' "$f" | grep -qE "$SKIP" && continue
    if git ls-files --error-unmatch "$f" >/dev/null 2>&1; then
        was=$(printf '%s\n' "$renamed" | awk -F'\t' -v f="$f" '$1 == f {print $2; exit}')
        hits=$(git diff -M -U0 "$base" -- ${was:+"$was"} "$f" | grep -I '^+' | grep -Iv '^+++' | strip_code | grep -oiE "$words" || true)
    else
        hits=$(strip_code < "$f" | grep -oiIE "$words" 2>/dev/null || true)
    fi
    [ -n "$hits" ] || continue
    n=$(printf '%s\n' "$hits" | wc -l)
    echo "  $f: $n, such as $(printf '%s\n' "$hits" | sort -u | head -3 | tr '\n' ' ')"
    bad=$((bad + n))
done
if [ "$bad" -gt 0 ]; then
    echo "$bad British spelling(s) on lines this branch adds: the American form, everywhere (bb rules show spelling)"
    exit 1
fi
echo "American spelling on every line this branch adds"
