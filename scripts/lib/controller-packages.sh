#!/usr/bin/env bash
#
# The controller's package list, read one way (R90 step 2).
#
# config/controller-packages.tsv is the one list of what the controller
# needs installed. The Dockerfile reads it for the image and
# nodes/install-controller.sh for a bare-metal install, both through this, so
# the two cannot read it differently: a row added there is in the next image
# and the next install alike.
#
#   controller-packages.sh FAMILY NEED...    one family's cells for those needs
#
# FAMILY is a column (deb, rhel, arch, suse, alpine, void, gentoo); NEED is
# core, tools, image, vendor, docker or host. What comes out is one entry per line:
# a package, or "a|b" for the first of those the machine's repositories have
# (never in the deb column, which the image installs as it is), or "@docker"
# for what the family's docker_install brings. A "-" cell is none and is
# left out. LIST names another file, for the unit tests.
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
list="${LIST:-}"
if [ -z "$list" ]; then
    # Beside the scripts in a checkout and in the image's /opt/builderbot alike.
    list="$here/../../config/controller-packages.tsv"
fi
[ -r "$list" ] || { echo "controller-packages.sh: no package list at $list" >&2; exit 1; }
[ $# -ge 2 ] || { echo "usage: controller-packages.sh FAMILY NEED..." >&2; exit 2; }
family="$1"; shift

awk -F'\t' -v fam="$family" -v needs=" $* " '
    /^#/ || NF == 0 { next }
    $1 == "what" {
        for (i = 3; i <= NF; i++) if ($i == fam) col = i
        if (!col) { print "controller-packages.sh: no column for family " fam > "/dev/stderr"; bad = 1; exit 1 }
        next
    }
    !col { print "controller-packages.sh: the list has no header line" > "/dev/stderr"; bad = 1; exit 1 }
    index(needs, " " $2 " ") {
        n = split($col, cell, " ")
        for (j = 1; j <= n; j++) if (cell[j] != "-" && cell[j] != "") print cell[j]
    }
    END { exit bad }
' "$list"
