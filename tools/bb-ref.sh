#!/usr/bin/env bash
# The README's bb reference, written from `bb help`: the block under "## The
# `bb` helper" is replaced by what the checkout's bb prints, minus its two
# header lines, so the two cannot drift (R91 step 5). `bb lint` fails when
# they differ and names this. --print prints the block the README holds now.
set -euo pipefail
cd "$(dirname "$0")/.."
start=$(grep -n '^## The `bb` helper' README.md | head -1 | cut -d: -f1)
[ -n "$start" ] || { echo "README.md has no '## The bb helper' section" >&2; exit 1; }
open=$(awk -v s="$start" 'NR>s && /^```/{print NR; exit}' README.md)
close=$(awk -v s="$open" 'NR>s && /^```/{print NR; exit}' README.md)
[ -n "$open" ] && [ -n "$close" ] || { echo "README.md's bb reference has no code block" >&2; exit 1; }
if [ "${1:-}" = --print ]; then
    sed -n "$((open + 1)),$((close - 1))p" README.md
    exit 0
fi
{ sed -n "1,${open}p" README.md; bash scripts/bb help | sed '1,2d'; sed -n "${close},\$p" README.md; } > README.md.new
mv README.md.new README.md
echo "README.md: the bb reference is bb help's $(bash scripts/bb help | sed '1,2d' | wc -l) lines"
