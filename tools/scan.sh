#!/bin/sh
# BuilderBot's static analysis stack, run once (docs/scanners.md): Semgrep,
# Trivy and mobsfscan over every project on the share, each in a container
# that lives only while it runs, each writing SARIF into the reports folder
# the controller reads at /reports. Plain `docker run` and nothing else, so it
# runs as it is on any host with Docker: on Unraid, pasted into the User
# Scripts plugin and scheduled weekly; elsewhere, from cron.
#
#   scan.sh                  all three
#   scan.sh semgrep trivy    some of them
#
# Set the three paths below for this host (or in the environment). The
# versions are pinned; move them on purpose, a release at a time.
set -eu

# The projects BuilderBot's /workspace is, read-only to the scanners.
SRC="${SCANNER_SOURCE_PATH:-/mnt/user/appdata/BuilderBot/workspace}"
# BuilderBot's own SCANNER_REPORTS_PATH: the folder it mounts at /reports.
OUT="${SCANNER_REPORTS_PATH:-/mnt/user/appdata/scanners/reports}"
# The scanners' rules and vulnerability database, kept between runs.
CACHE="${SCANNER_CACHE_PATH:-/mnt/user/appdata/scanners}"

SEMGREP_VERSION="${SEMGREP_VERSION:-1.179.0}"
TRIVY_VERSION="${TRIVY_VERSION:-0.75.0}"
MOBSFSCAN_VERSION="${MOBSFSCAN_VERSION:-0.4.5}"

command -v docker >/dev/null 2>&1 || { echo "scan: docker is not on this machine" >&2; exit 1; }
[ -d "$SRC" ] || { echo "scan: no projects at $SRC: set SCANNER_SOURCE_PATH to the share BuilderBot's /workspace is" >&2; exit 1; }
mkdir -p "$OUT" "$CACHE/semgrep" "$CACHE/trivy"

semgrep() {
    # p/default: the registry's curated rules, no account needed. Never
    # --disable-nosem: a `# nosemgrep: RULE` line with its reason is how a
    # project answers a finding, and BuilderBot drops the ones it marks.
    docker run --rm -v "$SRC:/src:ro" -v "$OUT:/reports" -v "$CACHE/semgrep:/root/.semgrep" -w /src \
        "semgrep/semgrep:$SEMGREP_VERSION" \
        semgrep scan --config p/default --metrics off --sarif --output /reports/semgrep.sarif \
            --exclude node_modules --exclude .git --exclude .worktrees --exclude .claude /src
}

trivy() {
    # Vulnerable dependencies in lock files, secrets committed to a tree, and
    # misconfigured Dockerfiles and compose files.
    docker run --rm -v "$SRC:/src:ro" -v "$OUT:/reports" -v "$CACHE/trivy:/cache" \
        "aquasec/trivy:$TRIVY_VERSION" \
        fs --cache-dir /cache --scanners vuln,secret,misconfig --format sarif \
            --output /reports/trivy.sarif --skip-dirs node_modules --skip-dirs .worktrees /src
}

mobsfscan() {
    # The Android and iOS source Semgrep's general rules miss. Its exit 1
    # means it found something, which is not a failed scan.
    docker run --rm -v "$SRC:/src:ro" -v "$OUT:/reports" python:3.12-slim \
        sh -c "pip install --quiet --no-cache-dir mobsfscan==$MOBSFSCAN_VERSION \
               && mobsfscan --sarif -o /reports/mobsfscan.sarif /src; s=\$?; [ \$s -le 1 ]"
}

[ "$#" -gt 0 ] || set -- semgrep trivy mobsfscan
failed=""
for s in "$@"; do
    case "$s" in
        semgrep|trivy|mobsfscan) ;;
        *) echo "scan: $s is not one of semgrep, trivy, mobsfscan" >&2; exit 2 ;;
    esac
    echo "== $s"
    start=$(date +%s)
    # One at a time: each is a few minutes of CPU, and a NAS has other work.
    if "$s"; then
        echo "   $s wrote $OUT/$s.sarif in $(( $(date +%s) - start ))s"
    else
        echo "   $s failed: its report is the one from before, if any" >&2
        failed="$failed $s"
    fi
done
# World-readable: the controller reads them as its own account.
chmod a+r "$OUT"/*.sarif 2>/dev/null || true
[ -z "$failed" ] || { echo "scan: failed:$failed" >&2; exit 1; }
echo "scan: done; the Analysis page reads them on its next look"
