#!/usr/bin/env bash
# The bb reference in docs/reference.md, written from `bb help`: the block
# under "## The `bb` helper" is replaced by what the checkout's bb prints,
# minus its two header lines, so the two cannot drift (R91 step 5). `bb lint`
# fails when they differ and names this. --print prints the block the
# reference holds now.
set -euo pipefail
cd "$(dirname "$0")/.."
REF=docs/reference.md
start=$(grep -n '^## The `bb` helper' "$REF" | head -1 | cut -d: -f1)
[ -n "$start" ] || { echo "$REF has no '## The bb helper' section" >&2; exit 1; }
open=$(awk -v s="$start" 'NR>s && /^```/{print NR; exit}' "$REF")
close=$(awk -v s="$open" 'NR>s && /^```/{print NR; exit}' "$REF")
[ -n "$open" ] && [ -n "$close" ] || { echo "$REF's bb reference has no code block" >&2; exit 1; }
if [ "${1:-}" = --print ]; then
    sed -n "$((open + 1)),$((close - 1))p" "$REF"
    exit 0
fi
{ sed -n "1,${open}p" "$REF"; bash scripts/bb help | sed '1,2d'; sed -n "${close},\$p" "$REF"; } > "$REF.new"
mv "$REF.new" "$REF"
echo "$REF: the bb reference is bb help's $(bash scripts/bb help | sed '1,2d' | wc -l) lines"
