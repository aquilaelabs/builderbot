#!/usr/bin/env bash
# Run the dashboard's browser tests against an isolated instance.
#
# Nothing here touches the live dashboard: the server under test binds a spare
# port with its own scratch state directory, a fake workspace of four projects
# (one broken, one locked), a crafted SARIF report, a stub `bb` whose doctor
# output the tests can flip, and throwaway tmux sessions on a PRIVATE tmux
# server (TMUX_TMPDIR under the scratch dir): the live dashboard lists every
# session on the shared server, and a test session showing up there as a
# real tab was the first thing an operator noticed. Everything is torn down by
# PID and by name, never by pattern, which is how a previous session managed
# to kill the real dashboard while trying to stop a test one.
#
#   bb dashboard test            # every *.mjs in this directory
#   bb dashboard test cards      # just cards.mjs
#   BB_TEST_TIMING=1 ...         # seconds between results, to find the slow part
#   BB_TEST_WORKERS=3 ...        # three suites at once, each in a world of its own
#
# One run at a time: a second one is refused while the first is alive. The
# workers of one run are that run: they share its lock and none of anything
# else (the section "N workers at once" below).
#
# Playwright comes from the image (/usr/lib/node_modules); the browsers live
# on the toolchain store and are found the way bb finds them. Missing either, the
# run reports [skip] rather than passing by omission.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Its own: the harness sources nothing of bb's, and the sentence a failed copy
# meant to say ended as "die: command not found" (B231).
die() { printf '[dashboard-test] ERROR: %s\n' "$*" >&2; exit 1; }
# Never as root. The suite's premise is an unprivileged runner: the agent it
# starts drops to the account sessions run as, which as root means an
# account the machine may not have (inside BuilderBot's own dev container,
# where tests run as root through compose exec, that was `bb`, and the
# session half never came up). The image's account is builder; the suite
# re-runs itself as that account when it starts as root and builder exists.
if [ "$(id -u)" = 0 ] && id builder >/dev/null 2>&1 && command -v runuser >/dev/null; then
    echo "[dashboard-test] started as root: running as builder instead" >&2
    exec runuser -u builder -- env HOME="$(getent passwd builder | cut -d: -f6)" \
        USER=builder bash "$0" "$@"
fi

# ---- a kept fixture (roadmap R75 step 2) ------------------------------------
# `bb tests keep` runs this script with BB_TEST_HOLD=1: the whole set-up, then
# instead of suites it writes its address to $KEEPF and waits to be stopped.
# Any run after that ATTACHES: no copy, no fixtures, no server, just the
# named suite or probe against the fixture that is up: half the time of a
# fresh run, and the world a suite just left still there for a probe to
# look at, which is what iterating on one failure needs. The trade: the
# world is not put back between runs
# (`bb tests keep` again for a clean one), and the server is the kept copy's,
# so a change to the dashboard's python needs a fresh keep; its .js and
# .html are copied over before every attached run, since the server reads
# those per request. The whole suite is refused here: it wants a clean
# world per file, which is what the ordinary run gives it.
KEEPF="${TMPDIR:-/tmp}/bb-suite.keep"
# A worker never attaches: its parent decided that a fresh world per file is
# what this run gets, and one kept world cannot be three workers' worlds.
if [ -z "${BB_TEST_HOLD:-}" ] && [ -z "${BB_TEST_WORKER:-}" ] && [ -f "$KEEPF" ]; then
    # shellcheck source=/dev/null
    . "$KEEPF"
    if kill -0 "${KEEP_PID:-0}" 2>/dev/null; then
        [ $# -gt 0 ] || { printf '[dashboard-test] ERROR: a fixture is kept (%s): name a suite or a probe to run against it, or bb tests keep stop\n' "$KEEP_URL" >&2; exit 1; }
        # One attached run at a time, as a fresh run is (B240). The keeper
        # holds the harness's lock, so an attached run keeps its own beside
        # it: two pages on the test account in one kept world fight over its
        # tabs, and the hand-back hook's design check, attaching in the
        # middle of a session's own suites, failed both on waits that had
        # nothing to do with the change. The sentence is the fresh run's, so
        # the hook passes it through as a check that could not run (B232).
        ALOCK="${TMPDIR:-/tmp}/dashboard-test.d/attached"
        # Not our own pid: on an NFS tree this script takes the lock, then
        # execs its copy under the same pid, which read the lock back as a
        # competitor that had started 00:00 ago and refused itself (B263).
        if [ -z "${BB_TEST_CONCURRENT:-}" ] && [ -f "$ALOCK" ]; then
            other="$(cat "$ALOCK" 2>/dev/null || true)"
            if [ -n "$other" ] && [ "$other" != "$$" ] && [ -d "/proc/$other" ]; then
                die "another dashboard test run is going (pid $other, attached to the kept fixture, started $(ps -o etime= -p "$other" 2>/dev/null | tr -d ' ') ago). One at a time on this box; wait for it, or set BB_TEST_CONCURRENT=1"
            fi
        fi
        ( umask 000; mkdir -p "${ALOCK%/*}"; rm -f "$ALOCK"; printf '%s' "$$" > "$ALOCK" ) 2>/dev/null \
            || die "cannot take $ALOCK: $(stat -c %U "$ALOCK" 2>/dev/null || echo somebody)'s, and ${ALOCK%/*} is not world-writable; fix the directory's mode (chmod 0777) and re-run"
        trap '[ "$(cat "$ALOCK" 2>/dev/null)" = "$$" ] && rm -f "$ALOCK"' EXIT
        # the dashboard's page and scripts, as they are now
        cp "$HERE"/../*.js "$HERE"/../*.html "$KEEP_HERE/../" 2>/dev/null || true
        cp "$HERE/lib.mjs" "$KEEP_HERE/lib.mjs"
        rc=0
        for t in "$@"; do
            case "$t" in
                /*) f="$KEEP_HERE/_probe-$(basename "${t%.mjs}").mjs"; cp "$t" "$f" ;;
                *)  f="$KEEP_HERE/${t%.mjs}.mjs"; cp "$HERE/${t%.mjs}.mjs" "$f" ;;
            esac
            printf '[dashboard-test] == %s == (attached to the kept fixture at %s)\n' "$(basename "$f")" "$KEEP_URL"
            # The kept world's own environment, the same as a fresh run sets
            # below: its private tmux server, its git config, and none of the
            # node's or the session's own variables. Without it a suite that
            # ends or makes a tmux session refused to run attached (B230).
            env -u TMUX -u BUILDERBOT_ROLE -u BB_CONTROLLER -u BB_CONTROLLER_PIN -u BB_NODE \
                -u BUILDERBOT_NODE -u BB_ACCOUNT_NAME -u BB_ACCOUNT_UID -u BB_PROJECT -u BB_TREE \
                -u BB_TREE_OWNER -u BB_CI_LOG_DIR -u BB_NODE_TOOLCHAINS -u BB_EMU_LOCAL \
                TMUX_TMPDIR="$KEEP_S/tmux" GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$KEEP_S/gitconfig" \
                DASHBOARD_TEST_URL="$KEEP_URL" DASHBOARD_TEST_CHROME="$KEEP_CHROME" \
                DASHBOARD_TEST_DIR="$KEEP_S" timeout --kill-after=10 "${SUITE_TIMEOUT:-1500}" node "$f" || rc=1
            case "$f" in */_probe-*) rm -f "$f" ;; esac
        done
        exit "$rc"
    fi
    rm -f "$KEEPF"
fi
# ...and never straight off the projects share. The server serves its own
# code on every request and the suite reads its files as it goes, and
# /workspace is NFS on every node and on the controller. Measured on an idle
# box (load 0.06), same commit, same file: testreg.mjs takes 22.7s from the
# share and fails its ten-second waits, and 8.9s from local disk and passes.
# Two and a half times, which is the difference between a budget that holds
# and one that does not, and it is why a run here could not be trusted (B124).
#
# So the run happens from a copy on local disk: the same bytes, uncommitted
# work included, with the network out of the way. Left behind: the android
# BUILD output, which is 73MB of the 87 and is nobody's input (appapi.mjs does
# read android/api-surface.json and app/build.gradle.kts, so android itself
# comes along); dist/, for the same reason; and .git, because nothing here runs
# git against this repository, only against the fixtures it makes.
# What a run ended by its process group left behind (B347): its copy of
# the tree, its state dir and its private tmux server. The cleanup below
# runs on a normal exit only, so each is stamped with the pid that made it
# and the next start removes the ones whose maker is gone. A kept fixture's
# maker is alive, so a keep is never swept from under an attached run.
sweep_leftovers() {
    local d p
    for d in "${TMPDIR:-/tmp}"/bb-suite.?????? "${TMPDIR:-/tmp}"/dashboard-test.??????; do
        [ -d "$d" ] || continue
        p="$(cat "$d/.bb-run-pid" 2>/dev/null || true)"
        if [ -z "$p" ] || ! kill -0 "$p" 2>/dev/null; then
            # ...and the tmux server that ran inside it, by its socket, which
            # tmux keeps a level down (tmux/tmux-UID/default): the glob one
            # level up matched a directory and left every server running (B608).
            [ -d "$d/tmux" ] && for sock in "$d"/tmux/*/*; do
                [ -S "$sock" ] && tmux -S "$sock" kill-server 2>/dev/null || true
            done
            # ...and its ssh-agent, by the pid it wrote, once that pid is
            # still an ssh-agent on this run's socket (B608).
            p="$(sed -n 's/^SSH_AGENT_PID=\([0-9]*\);.*/\1/p' "$d/agent.env" 2>/dev/null || true)"
            if [ -n "$p" ] && tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -qF "ssh-agent -a $d/"; then
                kill "$p" 2>/dev/null || true
            fi
            rm -rf "$d"
        fi
    done
}
[ -n "${BB_TEST_WORKER:-}" ] || sweep_leftovers
# Every run is from a copy of the tree, wherever the tree is. A run in place
# serves the page's scripts from disk on every load while its server keeps
# the python it started with, so an edit made during the run (a session
# carrying on while the suite runs) gave a run of neither version, and a
# verdict about nothing. On NFS the copy also spares the suite's own waits
# (B124), and a covered run rewrites the files it runs (B616). Since every
# node holds its projects on its own disk (R163) nothing else made a copy.
# BB_TEST_INPLACE=1 runs from the checkout for anyone debugging this, and
# then nothing under the dashboard is edited until it ends.
if [ -z "${BB_TEST_COPY:-}" ] && [ -z "${BB_TEST_INPLACE:-}" ]; then
    _src="$(cd "$HERE/../../.." && pwd)"
    _dst="$(mktemp -d "${TMPDIR:-/tmp}/bb-suite.XXXXXX")"
    echo $$ > "$_dst/.bb-run-pid"
    # tar exits 1 for a file that changed under it (a CHANGELOG.md write, a
    # session's edit) and the copy is still whole: that is not a failed copy.
    # What git ignores stays behind too, but for the map the plan reads
    # (.bb-map): an ignored folder is a build's output or somebody's scratch,
    # and /tmp is memory on a node. An 11 GB trial install ignored at the
    # root was being copied into it when the run was cut (B433).
    _skip="$_dst/.bb-copy-skip"
    git -C "$_src" -c safe.directory="$_src" ls-files -oi --exclude-standard --directory 2>/dev/null \
        | sed -n 's#/$##; /^\.bb-map$/d; s#^#./#p' > "$_skip" || : > "$_skip"
    { tar -C "$_src" -cf - --warning=no-file-changed --exclude=./.git --exclude=./dist \
        --exclude=./android/app/build --exclude=./android/build -X "$_skip" . || [ $? -eq 1 ]; } \
        | tar -C "$_dst" -xf - || { rm -rf "$_dst"; die "could not copy the tree to $_dst"; }
    rm -f "$_skip"
    printf '[dashboard-test] running from %s, a copy, so an edit to the tree meanwhile does not reach this run\n' "$_dst" >&2
    BB_TEST_COPY="$_dst" BB_TEST_ORIGIN="$_src" exec bash "$_dst/scripts/dashboard/test/run.sh" "$@"
fi
DASH="$(dirname "$HERE")"
# Function coverage (roadmap R76), under `bb tests coverage`: the page files
# of THIS copy are rewritten to count every function body they enter (never
# the tree: with no copy, BB_TEST_INPLACE, it is refused), the server
# records the functions it enters, and the counts are merged into the
# tree's .bb-map/coverage.json when the run ends.
#
# Once: a worker runs from the copy its parent already instrumented, and a
# counter counted twice is a function that ran twice.
if [ -n "${BB_COVERAGE:-}" ] && [ -z "${BB_TEST_WORKER:-}" ]; then
    [ -n "${BB_TEST_COPY:-}" ] || { printf '[dashboard-test] ERROR: coverage instruments the run copy, and BB_TEST_INPLACE runs without one\n' >&2; exit 1; }
    python3 "$DASH/../lib/codemap.py" instrument "$DASH" >&2 || exit 1
fi
# shellcheck source=/dev/null
. /opt/builderbot/scripts/lib/common.sh 2>/dev/null || {
    log()  { printf '[dashboard-test] %s\n' "$*"; }
    warn() { printf '[dashboard-test] WARN: %s\n' "$*" >&2; }
    die()  { printf '[dashboard-test] ERROR: %s\n' "$*" >&2; exit 1; }
}

# Missing pieces FAIL, by name. They used to print [skip] and exit 0, and
# on a node, where the runner's jobs had no node or Playwright on PATH,
# every CI run of this suite was green without running a test (bug B74).
# A run that could not start is not a pass.
#
# The same search bb uses, for both: the module and the browsers live on the
# store, and the /opt path is a symlink that only exists once the startup
# hook has run. The checkout's bb, not the one on PATH: this harness tests
# this tree, and the installed copy is whatever the running image shipped.
NODE_PATH="$(bash "$DASH/../bb" capture shot --print-node-path 2>/dev/null \
            || printf '%s' "${NODE_PATH:-/usr/lib/node_modules}")"
export NODE_PATH
node -e "require.resolve('playwright')" 2>/dev/null \
    || die "node and playwright are not on PATH here (NODE_PATH=$NODE_PATH); on a node they are the playwright recipe in the toolchain store, installed from the Tools tab"
CHROME="$(bash "$DASH/../bb" capture shot --print-chromium 2>/dev/null || true)"
[ -x "${CHROME:-}" ] || die "no Playwright chromium: install it with: bb toolchains install playwright"
command -v tmux >/dev/null || die "tmux is not installed"

# The port is picked, not fixed. It was 8093 for everybody, which meant a run
# on this box and the CI job for the push that started it fought over one
# number: the second refused to start, and the message's first suggestion
# (kill the pid holding it) would have killed a live CI job. Worse than the
# collision was what it did to the run that DID start, since the two suites
# then shared the box's CPU and the loser went red on timing (bug #13).
#
# So: ask the kernel for a free one. Bound and released, then handed to the
# server, a race in principle, and not one in practice on a box running two
# of these at most, where the alternative is a constant that collides every
# time. DASHBOARD_TEST_PORT still pins it for anyone who needs a known port.
free_port() {
    python3 - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}
PORT="${DASHBOARD_TEST_PORT:-$(free_port)}"
[ -n "$PORT" ] || die "could not find a free port for the test server"
# Refuse a port we do not own, before doing anything else. An interrupted run
# (SIGKILL, or the session that launched it dying) leaves a server holding this
# one with a scratch dir that no longer exists. Ours then exits on EADDRINUSE
# while the old one keeps answering (same port, same test:test credential), so
# the readiness curl below succeeds and the whole suite runs against the wrong
# fixtures. The failures that produces read as real regressions and are not;
# that cost an hour once, and the tell was obscure enough to be worth this check.
#
# Only reachable now when the port was pinned by hand, which is exactly when
# the holder is worth identifying: a copy running out of a runner's _work
# directory is a CI job on this node, mid-run, and killing it ends a build.
if holder="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1)" && [ -n "$holder" ]; then
    where="$(tr '\0' ' ' < "/proc/$holder/cmdline" 2>/dev/null || true)"
    case "$where" in
        */_work/*) die "port $PORT is held by pid $holder, which is a CI run on this box (${where# }). Do NOT kill it; leave DASHBOARD_TEST_PORT unset to get a free port." ;;
    esac
    die "port $PORT is already in use by pid $holder ($(ps -o comm= -p "$holder" 2>/dev/null || echo unknown)${where:+: $where}). If that is a test server left behind by an interrupted run, 'kill $holder' and re-run; otherwise leave DASHBOARD_TEST_PORT unset and one will be picked."
fi
# One run at a time on this box. The port used to be fixed, which stopped a
# second run by accident; picking a free one removed that stop, and three
# suites then ran side by side on a box that also serves the live dashboard
# the contention bug #13 describes, made to order. A pid lock says so
# instead, with how long the other has been going. BB_TEST_CONCURRENT=1
# overrides it for whoever knows what they are doing.
#
# The other run may be ANOTHER ACCOUNT'S: on a node the CI runner shares the
# box with every session, and its run holds this same lock. So liveness is
# /proc, not kill -0 (which answers "no" for a pid that is not yours and
# read a live CI run as a stale lock), and the lock is written world-
# writable, so the next account can take over one a killed run left.
#
# In a directory of its own, NOT a file straight under /tmp. /tmp is sticky,
# and with fs.protected_regular (on by default since Ubuntu 20.04) a file
# there that another account owns cannot be opened for writing whatever its
# mode, so a lock a canceled CI job left as `bb` could never be taken over
# by a session, or the reverse, and every run died on "cannot take" until
# somebody with that account removed it (measured on bb-sandbox, 9 Sep). A
# world-writable directory that is not sticky has no such rule: anyone can
# overwrite or unlink the lock inside it, which is what a stale lock wants.
LOCKDIR="${TMPDIR:-/tmp}/dashboard-test.d"
( umask 000; mkdir -p "$LOCKDIR" ) 2>/dev/null || true
LOCK="$LOCKDIR/lock"
# A worker's parent holds this lock for it, and a worker that took it would
# take it FROM the parent: the pid in the file is what the next run reads,
# and a worker's is gone before the parent is. It keeps the path for its
# cleanup, which only ever removes a lock that carries its own pid.
if [ -z "${BB_TEST_WORKER:-}" ]; then
# A run still on the previous layout holds the old path; for one release
# both are read for a LIVE pid, and only the new one is written.
# BB_TEST_WAIT_LOCK=SECONDS waits that long for a run that holds it to end
# rather than refusing at once: a preflight started in the background met
# the hand-back hook's own check run, which ends in minutes, and stopped
# having run nothing (B572).
waited=0
for l in "$LOCK" "${TMPDIR:-/tmp}/dashboard-test.lock"; do
    [ -z "${BB_TEST_CONCURRENT:-}" ] && [ -f "$l" ] || continue
    other="$(cat "$l" 2>/dev/null || true)"
    while [ -n "$other" ] && [ -d "/proc/$other" ] && [ "$waited" -lt "${BB_TEST_WAIT_LOCK:-0}" ]; do
        [ "$waited" -eq 0 ] && echo "[dashboard-test] waiting for the run that holds the lock (pid $other) to end" >&2
        sleep 5; waited=$((waited + 5))
        other="$(cat "$l" 2>/dev/null || true)"
    done
    if [ -n "$other" ] && [ -d "/proc/$other" ]; then
        owner="$(stat -c %U "$l" 2>/dev/null || echo somebody)"
        die "another dashboard test run is going (pid $other, ${owner}'s, started $(ps -o etime= -p "$other" 2>/dev/null | tr -d ' ') ago). One at a time on this box, and the CI runner counts; wait for it, or set BB_TEST_CONCURRENT=1"
    fi
done
# Taken over by unlinking first: a stale lock another account wrote is
# unlinkable in a non-sticky directory, and a fresh file is then ours.
rm -f "$LOCK" 2>/dev/null || true
( umask 000; printf '%s' "$$" > "$LOCK" ) 2>/dev/null \
    || die "cannot take $LOCK: $(stat -c %U "$LOCK" 2>/dev/null || echo somebody)'s, and $LOCKDIR is not world-writable; fix the directory's mode (chmod 0777) and re-run"
fi
S="$(mktemp -d "${TMPDIR:-/tmp}/dashboard-test.XXXXXX")"
# Where each suite's seconds are kept for the worker plan (run_file,
# bucket_plan): beside the code map in the tree the run was made from, which
# is this node's own and gitignored; workers inherit the path.
if [ -z "${SUITE_TIMES:-}" ]; then
    _o="${BB_TEST_ORIGIN:-$(cd "$HERE/../../.." && pwd)}"
    mkdir -p "$_o/.bb-map" 2>/dev/null && export SUITE_TIMES="$_o/.bb-map/suite-times.tsv"
fi
echo $$ > "$S/.bb-run-pid"
if [ -n "${BB_COVERAGE:-}" ]; then
    # A worker counts into its parent's directory, which is where the one
    # merge at the end of the run reads; a directory per worker would be a
    # merge per worker, and one merge into the tree at a time is the rule.
    if [ -z "${BB_TEST_WORKER:-}" ] || [ -z "${BB_COVERAGE_DIR:-}" ]; then
        export BB_COVERAGE_DIR="$S/coverage"
    fi
    mkdir -p "$BB_COVERAGE_DIR"
    # A counted page is a slower page, and the suites' waits are budgets
    # for the real one (B219): every patience() gets twice the time here.
    export BB_TEST_SLOW="${BB_TEST_SLOW:-2}"
fi
coverage_merge() {
    # Into the tree the copy was made from: the counts name the copy's
    # paths, which the merge strips.
    local origin="${BB_TEST_ORIGIN:-$(cd "$HERE/../../.." && pwd)}" n
    n="$(ls "$BB_COVERAGE_DIR"/*.json 2>/dev/null | wc -l)"
    [ "$n" -gt 0 ] || { warn "coverage: no counts were written"; return; }
    python3 "$DASH/../lib/codemap.py" --root "$origin" coverage-ingest \
        --strip "${BB_TEST_COPY:-$origin}/" "$BB_COVERAGE_DIR"/*.json >&2 || warn "coverage: the merge failed"
    log "coverage from $n file(s) merged into $origin/.bb-map/coverage.json; bb map coverage reads it"
}
# Every suite but the library and the lab's: a lab-*.mjs runs against a
# real service (roadmap R54) and is asked for by name, `bb tests lab`.
default_suites() {
    local t
    for t in "$HERE"/*.mjs; do
        case "$(basename "$t")" in lib.mjs|lab-*.mjs|_probe-*) ;; *) printf '%s\n' "$(basename "${t%.mjs}")" ;; esac
    done
}

# ---- N workers at once (roadmap R81) ----------------------------------------
# BB_TEST_WORKERS=N, N above one, runs the suites across N children of this
# process at once. A worker is this same script with BB_TEST_WORKER set: it
# skips what the parent did once (the copy to local disk, the coverage
# instrumentation, the lock, the policy check) and builds everything else
# for itself, because everything else is what suites collide on: the
# scratch dir with the server's state and the workspace of fixtures, the
# docker stub's state and the stub agent's directory under it, the private
# tmux server on a socket under it, the ssh-agent, and the server on a port
# the parent picks for it. The parent holds the one-at-a-time lock for all of
# them, so a worker takes none, and a worker never reruns a failed suite:
# the parent does that, alone, after every worker is done, so "flaky" means
# what it means in a single run, failed under load and passed by itself.
#
# The buckets: the suites known to be slow land in different buckets first,
# then the rest go, longest file first, to whichever bucket holds the fewest
# lines so far. Lines are a fair proxy for minutes here, and the seven named
# are the ones that are minutes each.
#
# The output is the workers' logs in bucket order, each under a header, the
# one being waited on streamed as it grows, so every suite's banner still
# sits above its own results and its own total, which is what bb tests
# ingest, bb tests last and the preflight's flaky verdict read. The one
# combined tally is prefixed like every other line of this script's own,
# because a bare "N passed, M failed" is a suite's total to those readers.
bucket_plan() {
    # $1 workers; $2 a file of "name<TAB>lines" per suite (a file, since the
    # heredoc is python's stdin); $3 the times file run_file appends to;
    # stdout: "bucket<TAB>name", buckets numbered from 0, each bucket's
    # names in the order a single run has.
    #
    # By measured seconds, longest first, each to the emptiest bucket. It
    # was by line count behind a hand-kept list of the slow files, and line
    # count is a poor clock: uniform.mjs is 1471 lines and 227 s, devapp.mjs
    # 4109 lines and 199 s, so one worker carried uniform, roles and cards
    # (about 450 s) while the others idled (30 Sep). A suite never timed on
    # this node is costed from its lines at the tree's own median rate. The
    # median of the last five passes per suite, so one slow run on a busy
    # box does not move the plan, and the file is trimmed to those five.
    python3 - "$1" "$2" "${3:-}" <<'PY'
import os, statistics, sys
n, sizes, times = int(sys.argv[1]), sys.argv[2], sys.argv[3]
base = lambda k: k.rsplit("/", 1)[-1][:-4] if k.endswith(".mjs") else k.rsplit("/", 1)[-1]
size = {}
for line in open(sizes):
    if line.strip():
        name, lines = line.rstrip("\n").split("\t")
        size[name] = int(lines or 0)
seen = {}
if times and os.path.isfile(times):
    for line in open(times, errors="replace"):
        k, _, v = line.rstrip("\n").partition("\t")
        if k and v.isdigit():
            seen.setdefault(k, []).append(int(v))
    seen = {k: v[-5:] for k, v in seen.items()}
    try:
        with open(times + ".tmp", "w") as f:
            for k in sorted(seen):
                f.writelines(f"{k}\t{v}\n" for v in seen[k])
        os.replace(times + ".tmp", times)
    except OSError:
        pass
secs = {k: statistics.median(v) for k, v in seen.items()}
rates = [size[k] / secs[base(k)] for k in size if secs.get(base(k)) and size[k]]
rate = statistics.median(rates) if rates else 12.0
cost = {k: secs.get(base(k), size[k] / rate) for k in size}
buckets, load = [[] for _ in range(n)], [0.0] * n
for name in sorted(cost, key=lambda k: (-cost[k], k)):
    b = load.index(min(load))
    buckets[b].append(name)
    load[b] += cost[name]
for b, names in enumerate(buckets):
    for name in sorted(names):
        print(f"{b}\t{name}")
print(f"planned: {' '.join(f'{x:.0f}s' for x in load)} by {'measured seconds' if secs else 'line count'}"
      f" ({sum(1 for k in size if base(k) in secs)} of {len(size)} suites timed)", file=sys.stderr)
PY
}
free_ports() {
    # N distinct free ports, one per line. Bound all at once and released
    # together, so the kernel cannot hand the same number to two of them,
    # which it could if each worker asked for its own a moment apart.
    python3 - "$1" <<'PY'
import socket, sys
socks = [socket.socket() for _ in range(int(sys.argv[1]))]
for s in socks:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
for s in socks:
    s.close()
PY
}
stream_log() {
    # A worker's log as it grows, until the worker ends, then the rest of it.
    # tail --pid is GNU's and uutils' both; anywhere without it the log is
    # printed whole once the worker is done.
    local f="$1" p="$2"
    if tail --help 2>&1 | grep -q -- '--pid'; then
        tail -n +1 -f --pid="$p" "$f"
    else
        while kill -0 "$p" 2>/dev/null; do sleep 1; done
        cat "$f"
    fi
}
WORKER_PIDS=()
workers_cleanup() {
    local p
    for p in "${WORKER_PIDS[@]}"; do kill "$p" 2>/dev/null || true; done
    # The workers' counts were all written by the time each one exited (its
    # server is stopped and polled dead before it does), so the merge is
    # one, here, into the tree.
    if [ -n "${BB_COVERAGE_DIR:-}" ]; then coverage_merge; fi
    [ -n "${BB_TEST_KEEP:-}" ] && log "workers' logs kept at $S" || rm -rf "$S"
    [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"
    if [ -n "${BB_TEST_COPY:-}" ] && [ -z "${BB_TEST_KEEP:-}" ]; then
        cd / && rm -rf "$BB_TEST_COPY"
    elif [ -n "${BB_TEST_COPY:-}" ]; then
        log "the tree it ran from is kept at $BB_TEST_COPY"
    fi
}
# The machine's load as a run ends (R108), the one-minute and five-minute
# averages and its cores: what a timing in this log was taken under, which
# bb tests ingest keeps with the run so the Tests tab can tell a quiet run's
# seconds from a busy one's.
load_line() {
    printf '[dashboard-test] load: %s on %s cores\n' "$(cut -d' ' -f1,2 /proc/loadavg 2>/dev/null)" \
        "$(nproc 2>/dev/null || echo 1)"
}
run_workers() {
    local n="$1"; shift
    local names=("$@") t f plan i rc=0 wrc tp tf
    local ports=() pids=() logs=() bucket=() failed=() flaky=()
    [ -z "${DASHBOARD_TEST_PORT:-}" ] \
        || die "DASHBOARD_TEST_PORT pins one port and BB_TEST_WORKERS=$n asks for $n servers; unset one of them"
    trap 'workers_cleanup' EXIT
    trap 'exit 130' TERM INT
    for t in "${names[@]}"; do
        case "$t" in /*) f="$t" ;; *) f="$HERE/${t%.mjs}.mjs" ;; esac
        printf '%s\t%s\n' "$t" "$(wc -l < "$f" 2>/dev/null || echo 0)"
    done > "$S/sizes"
    plan="$(bucket_plan "$n" "$S/sizes" "${SUITE_TIMES:-}" 2> "$S/plan.said")"
    log "workers $(cat "$S/plan.said" 2>/dev/null)"
    mapfile -t ports < <(free_ports "$n")
    [ "${#ports[@]}" = "$n" ] || die "could not find $n free ports for the workers' servers"
    for ((i = 0; i < n; i++)); do
        mapfile -t bucket < <(printf '%s\n' "$plan" | awk -F'\t' -v b="$i" '$1 == b { print $2 }')
        logs[i]="$S/worker-$((i + 1)).log"
        : > "${logs[i]}"
        # Its own port, its own account of what failed, and the rest of the
        # environment as this process has it: the copy, the timing flag,
        # the coverage directory, all inherited.
        BB_TEST_WORKER="$((i + 1))" DASHBOARD_TEST_PORT="${ports[i]}" \
        BB_TEST_WORKER_OUT="$S/failed-$((i + 1))" \
            bash "$0" "${bucket[@]}" > "${logs[i]}" 2>&1 &
        pids[i]=$!
        WORKER_PIDS+=("$!")
        log "worker $((i + 1)) of $n (port ${ports[i]}, pid $!): ${bucket[*]}"
    done
    for ((i = 0; i < n; i++)); do
        printf '[dashboard-test] == worker %s of %s ==\n' "$((i + 1))" "$n"
        stream_log "${logs[i]}" "${pids[i]}"
        wrc=0; wait "${pids[i]}" || wrc=$?
        if [ -f "$S/failed-$((i + 1))" ]; then
            mapfile -t bucket < "$S/failed-$((i + 1))"
            failed+=("${bucket[@]}")
        elif [ "$wrc" != 0 ]; then
            # Ended before it could say: a die() in its set-up, most
            # likely, and its log above says which.
            warn "worker $((i + 1)) ended (status $wrc) without running its suites"
            rc=1
        fi
    done
    WORKER_PIDS=()
    read -r tp tf < <(cat "${logs[@]}" \
        | awk '/^[0-9]+ passed, [0-9]+ failed/ { p += $1; f += $3 } END { print p + 0, f + 0 }')
    log "workers: $tp passed, $tf failed across $n workers, ${#names[@]} suites${failed[*]:+; failed in the run: ${failed[*]}}"
    # Once more, alone, for each suite that failed, the way a single run
    # does it below: a worker of its own, one at a time, on a port of its
    # own choosing, with the whole box to itself.
    local again_failed=()
    for t in "${failed[@]}"; do
        if BB_TEST_WORKER=again BB_TEST_AGAIN=1 bash "$0" "$t"; then
            flaky+=("$(basename "${t%.mjs}").mjs")
        else
            again_failed+=("$(basename "${t%.mjs}").mjs")
            rc=1
        fi
    done
    if [ "${#flaky[@]}" -gt 0 ]; then
        warn "flaky: ${flaky[*]} failed in the whole run and passed again alone"
    fi
    # ...and named, the ones that failed again: a suite that ends before its
    # first check (an uncaught timeout in its set-up) prints no FAIL line and
    # adds nothing to the count, so "0 failed" sat above two suites that had
    # run nothing, and they read as flakes (B464).
    if [ "${#again_failed[@]}" -gt 0 ]; then
        warn "failed again alone: ${again_failed[*]} (a suite that ends before its checks finish counts no FAIL: read its output above)"
    fi
    load_line
    [ "$rc" = 0 ] && log "dashboard tests: all passed" || warn "dashboard tests: FAILURES above"
    exit "$rc"
}
if [ "${BB_TEST_WORKERS:-1}" -gt 1 ] 2>/dev/null && [ -z "${BB_TEST_WORKER:-}" ] && [ -z "${BB_TEST_HOLD:-}" ]; then
    if [ $# -gt 0 ]; then _names=("$@"); else mapfile -t _names < <(default_suites); fi
    # No more workers than suites, and one suite is the single path below.
    _n="$BB_TEST_WORKERS"
    [ "$_n" -le "${#_names[@]}" ] || _n="${#_names[@]}"
    # Beside each other the suites get the patience CI gives them: every
    # wait doubled. How many run beside each other is the node's row's
    # (BB_TEST_WORKERS), not this file's to cap: four on four cores ran a
    # suite a third slower than alone and timed out a dozen checks a day
    # that passed alone every time (26 and 27 Sep), which is a fact about
    # the waits, and lib.mjs's wrapper gives a slow page more time.
    [ "$_n" -le 1 ] || export BB_TEST_SLOW="${BB_TEST_SLOW:-2}"
    [ "$_n" -le 1 ] || run_workers "$_n" "${_names[@]}"
fi
# Every tmux call from here on (ours and the server's) talks to a private
# server whose socket lives in the scratch dir. Nothing reaches the real one.
#
# TMUX must be unset first. This script is usually run FROM a tmux session
# (a dashboard terminal, a Claude session), and inside one the tmux client
# takes its socket from $TMUX and ignores TMUX_TMPDIR entirely, which is how
# a first version of this file put its test sessions on the real server and,
# on cleanup, killed the real server, the operator's shell and the Claude
# session running the tests along with it. Verified below, not assumed.
unset TMUX
# Below everything else on the box: the servers, the browsers and node this
# run starts all inherit it, so the emulator, a docker build and a session's
# own work keep the CPU when they want it, and on a quiet box nothing is
# slower (the operator, 27 Sep). Best effort: a shell that may not lower
# its own priority runs as it is.
renice -n 10 -p $$ >/dev/null 2>&1 || true
command -v ionice >/dev/null 2>&1 && ionice -c 2 -n 7 -p $$ >/dev/null 2>&1 || true
# Same reasoning, for the credential. This script is usually run FROM a Claude
# session, which is given BB_TOKEN, a token scoped to ONE project with `user`
# rights and a twelve-hour life. `bb` prefers it over DASHBOARD_AUTH, so every
# test that shells out to `bb` was quietly using the outer session's
# credential instead of the harness's: it worked while that token was fresh
# and the project happened to match, and stopped the moment it expired. What
# that looked like was agent.mjs dying on "no node called agentbox" (a 401
# the caller reads as an empty node list) hours into a session, with nothing
# in the diff to explain it.
# ---- the container is the boundary, where the project says so (R65) --------
#
# `bb test` routes a project's tests into its dev instance and refuses when the
# instance is down and the Docker row says the container is the only place they
# run. Calling this script directly skipped bb entirely, which is the door
# BuilderBot's own suite went through for a day while its dev instance sat
# untouched: the machinery was built and simply not taken.
#
# NOT CI's. The setting is about a SESSION's tests (prefs.devtest), and a
# workflow runs on a node's runner precisely to test the tree the image will be
# built from, where there is no instance to run in.
#
# And best effort: read through bb, which on a node relays to the controller,
# so where the policy cannot be read at all (no token, no controller) this says
# nothing rather than refusing a run it cannot judge.
#
# And once: a worker's parent asked, and a worker that asked again would be
# one relay per worker for an answer that cannot have changed.
if [ -z "${BB_IN_INSTANCE:-}" ] && [ -z "${CI:-}" ] && [ -z "${GITHUB_ACTIONS:-}" ] && [ -z "${BB_TEST_WORKER:-}" ]; then
    _proj="${BB_PROJECT:-$(basename "$(cd "$HERE/../../.." && pwd)")}"
    _only="$(BB_PROJECT="$_proj" BB_SETTINGS_JSON=1 bb settings --json 2>/dev/null         | python3 -c 'import json,sys
try: print("only" if json.load(sys.stdin).get("devtest") else "")
except Exception: print("")' 2>/dev/null || true)"
    if [ "$_only" = only ]; then
        echo "[dashboard-test] ERROR: $_proj's tests run only inside its dev instance, and this is not it." >&2
        echo "[dashboard-test] Run 'bb test' (or 'bb devapp test FILE'), which puts them there and says so if the instance is down." >&2
        exit 1
    fi
fi

unset BB_TOKEN
# And the role. Run from a session ON A NODE, this script inherits
# BUILDERBOT_ROLE=node, the real controller's address and pin, and the
# account the session runs as, and every `bash scripts/bb` a test makes
# then relays to the real controller with no token, or reads a node's
# home. The suite drives the checkout's bb as the CONTROLLER's, against its
# own server; the tests that mean a node say so in their own env.
unset BUILDERBOT_ROLE BB_CONTROLLER BB_CONTROLLER_PIN BB_NODE BUILDERBOT_NODE \
      BB_ACCOUNT_NAME BB_ACCOUNT_UID BB_PROJECT BB_TREE BB_TREE_OWNER BB_CI_LOG_DIR \
      BB_NODE_TOOLCHAINS BB_EMU_LOCAL   # "already on the node's store": bb emu would run here
export TMUX_TMPDIR="$S/tmux"
mkdir -p "$TMUX_TMPDIR"
# git's global and system config are the suite's own, not the machine's. The
# fixtures are `git init` with no branch named, so the branch they start on
# is whatever init.defaultBranch says: nothing on a node, so master; `main`
# in BuilderBot's own image, whose ~/.gitconfig sets it. The relayed-push
# refusals in agent.mjs read the policy on that branch, and went green on the
# node and red inside builderbot-dev with nothing in the diff to explain it
# (15 Sep). Pinned here, so a run says the same thing on every machine.
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$S/gitconfig"
printf '[init]\n\tdefaultBranch = master\n' > "$GIT_CONFIG_GLOBAL"
tmux new-session -d -s probe -c /tmp
sock="$(tmux display-message -t probe -p '#{socket_path}' 2>/dev/null || true)"
case "$sock" in
    "$S"/*) tmux kill-session -t probe ;;
    *) tmux kill-session -t probe 2>/dev/null
       die "refusing to run: tmux is on '${sock:-?}', not the private test server" ;;
esac
trap 'cleanup' EXIT
trap 'exit 0' TERM INT      # so a kept fixture's stop runs the cleanup above
probes=()
pid=""
agent_pid=""
stub_pid=""
cleanup() {
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    [ -n "$stub_pid" ] && kill "$stub_pid" 2>/dev/null || true
    # The server's counts are written on its way out, so the merge waits for
    # it before reading the directory. A worker's parent merges for all of
    # them, once, when the last of them is done.
    if [ -n "${BB_COVERAGE_DIR:-}" ] && [ -z "${BB_TEST_WORKER:-}" ]; then sleep 1; coverage_merge; fi
    [ -n "$agent_pid" ] && kill "$agent_pid" 2>/dev/null || true
    [ -n "$stub_pid" ] && kill "$stub_pid" 2>/dev/null || true
    [ -n "${PIDF:-}" ] && rm -f "$PIDF"
    # The private server only, guarded again, because this is the line that
    # once took the real one down.
    case "$(tmux display-message -p '#{socket_path}' 2>/dev/null)" in
        "$S"/*) tmux kill-server 2>/dev/null || true ;;
    esac
    # ...and by its socket under this run's own directory, which needs no
    # client to answer display-message first (B608).
    for sock in "$S"/tmux/*/*; do
        [ -S "$sock" ] && tmux -S "$sock" kill-server 2>/dev/null || true
    done
    # BB_TEST_KEEP=1 leaves the scratch dir behind: the server log, the stub
    # agent's log and the state dir are the only account of what a failure
    # inside them looked like, and they used to go with the run that made it.
    [ -n "${BB_TEST_KEEP:-}" ] && log "scratch kept at $S" || rm -rf "$S"
    [ "$(cat "$LOCK" 2>/dev/null)" = "$$" ] && rm -f "$LOCK"
    for f in "${probes[@]}"; do rm -f "$f"; done
    [ "${KEEP_MINE:-}" = 1 ] && rm -f "$KEEPF"
    # ...and the local copy this run was made from, if it was made from one.
    # cd out of it first: this script is inside what it is removing. Kept with
    # the scratch dir under BB_TEST_KEEP, since a failure in the copy is read
    # in the copy. A worker leaves it: the others are still running from it,
    # and it is the parent's to remove.
    [ -z "${BB_TEST_WORKER:-}" ] || return 0
    if [ -n "${BB_TEST_COPY:-}" ] && [ -z "${BB_TEST_KEEP:-}" ]; then
        cd / && rm -rf "$BB_TEST_COPY"
    elif [ -n "${BB_TEST_COPY:-}" ]; then
        log "the tree it ran from is kept at $BB_TEST_COPY"
    fi
}

# ---- fixtures --------------------------------------------------------------
mkdir -p "$S"/{ws,reports,state,bin,sdk,androidsdk,devdata}
# ep.silon: a project whose name tmux would rewrite in a session name (`.` →
# `_`), so the page, the server and bb-tty have to agree on the substitution.
( cd "$S/ws" && mkdir -p alpha beta gamma delta ep.silon \
    && for d in alpha beta gamma delta ep.silon; do echo x > "$d/README.md"; done \
    && for d in alpha beta delta ep.silon; do git init -q "$d"; done \
    && for d in alpha beta delta ep.silon; do
           # The fixture's own identity, so a commit the server makes in one
           # of these (a version bump, VERSION's first commit) does not lean
           # on the ACCOUNT's global config: the node's CI runner has none,
           # and two version tests went red there and green here for exactly
           # that (measured on bb-sandbox's first real run of this suite).
           git -C "$d" config user.name "dashboard test" \
           && git -C "$d" config user.email "test@example.invalid"; done \
    && git -C alpha remote add origin git@github.com:owner/alpha.git \
    && git -C ep.silon remote add origin https://gitlab.example/eps.git )
    # alpha is linked to GitHub and beta to nothing: the link-to-GitHub
    # button must show on exactly one of them. ep.silon is linked to a
    # non-GitHub remote: still "linked", but the GitHub command card must
    # ghost there all the same.
# A directory that carries the marker: the container writes one into paths of
# its own that land in the projects share, and an operator can write one by
# hand. Either way it is not a project.
mkdir -p "$S/ws/toolstore" && : > "$S/ws/toolstore/.bbignore"
# ...and one with no marker at all, the shape the toolchain store actually has when
# somebody maps a share inside the projects folder and nothing has told the
# container about it. It is not a project because the Projects card did not
# accept it, which is the only test that matters now.
mkdir -p "$S/ws/vendored-junk/deep" && echo x > "$S/ws/vendored-junk/deep/thing.py"
# delta is the locked one: kept, run by the operator, and read-only.
echo '["delta"]' > "$S/state/locked-projects.json"
# alpha may push, on the deploy key its remote uses. Stated here rather than
# left to a migration: the one-off that used to grant this on first boot went
# at 0.5.0, and a fixture that leans on a migration is a fixture that breaks
# on the day the migration is finally deleted.
printf '{"alpha":{"repo":"owner/alpha","host":"github.com","how":"key","at":1756000000}}\n' \
    > "$S/state/push-rights.json"
# A git that stalls on one magic URL and is the real git for everything else.
# Cloning is a background job now, and the two properties that matters for
# (it outlives the page, and it can be stopped) can only be checked against a
# clone that is still going when the test looks.
REAL_GIT="$(command -v git)"
cat > "$S/bin/git" <<GEOF
#!/usr/bin/env bash
for a in "\$@"; do
    case "\$a" in *slowclone*) sleep 120; exit 1 ;; esac
done
exec "$REAL_GIT" "\$@"
GEOF
chmod +x "$S/bin/git"
# mint-runner-token, stood in for on the server's PATH as `sudo`: the root-only
# store is a directory here and the minted tokens are fixed strings, so a test
# can store, check, mint and forget without root and without GitHub.
mkdir -p "$S/runner-store"
cat > "$S/bin/sudo" <<SEOF
#!/bin/sh
store="$S/runner-store"
SEOF
cat >> "$S/bin/sudo" <<'EOF'
while [ $# -gt 0 ]; do case "$1" in */mint-runner-token) shift; break ;; esac; shift; done
kind="$1"; node="$2"; slot="$3"; f="$store/$node.$slot.env"
case "$kind" in
    --list) for x in "$store"/n_*.*.env; do [ -f "$x" ] || continue; b="${x##*/}"; b="${b%.env}"; echo "${b%%.*} ${b#*.}"; done; exit 0 ;;
    store)  cat > "$f"; echo stored; exit 0 ;;
    forget) rm -f "$f"; echo forgotten; exit 0 ;;
esac
[ -f "$f" ] || { echo "[builderbot] ERROR: no runner token stored for this runner on $node: add it in the runner section of the node's row on the Nodes tab" >&2; exit 1; }
case "$kind" in
    --check)      grep -E '^RUNNER_(URL|FORGE)=' "$f"; exit 0 ;;
    --validate)   echo "token accepted"; exit 0 ;;
    registration) [ -f "$store/mint-fail" ] && { echo "[builderbot] ERROR: GitHub denied the request (403) on /orgs/example-org/actions/runners/registration-token. This is an ORG-level call: the token needs Organization permissions -> 'Self-hosted runners': Read and write" >&2; exit 1; }
                  echo AAAREGTOKEN; exit 0 ;;
    remove)       if grep -q '^RUNNER_FORGE=gitea' "$f"; then echo "remove $node $slot $4" >> "$store/calls.log"; echo removed; else echo AAAREMOVETOKEN; fi; exit 0 ;;
esac
echo "sudo: refused" >&2; exit 1
EOF
chmod +x "$S/bin/sudo"
# alpha has a previous Claude conversation, so its Claude button offers the
# Resume / New chooser rather than starting straight away.
mkdir -p "$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)"
echo '{}' > "$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)/abc123.jsonl"
# alpha also has memories, arranged so both kinds of drift between the index
# and the files are on screen: the index names one file that is not there, and
# one file that is there is not in the index. Re-seeded before every test file
# because memory.mjs edits and deletes these for real.
M="$S/home/.claude/projects/$(echo "$S/ws/alpha" | tr / -)/memory"
seed_memories() {
rm -rf "$M"; mkdir -p "$M"
# The index separator is Claude Code's em dash, written as its bytes (the
# house rule voice): the module parses the real character.
printf -- '- [Prefers tabs](tabs.md) \xe2\x80\x94 spaces are a fight not worth having\n- [Something else](vanished.md) \xe2\x80\x94 a pointer with nothing behind it\n' > "$M/MEMORY.md"
cat > "$M/tabs.md" <<'MEOF'
---
name: tabs
description: indent with tabs in this project, always
metadata:
  type: feedback
---

Tabs, not spaces.

**Why:** asked for it twice.
MEOF
cat > "$M/loose.md" <<'MEOF'
---
name: loose
description: a memory that never made it into the index
metadata:
  type: project
---

Only recall will ever surface this one.
MEOF
}
seed_memories
# A scratch ssh-agent holding one throwaway key, so the deploy-key endpoint
# has something deterministic to list. Its socket replaces the real agent's in
# the server's environment: the tests must see this key and no operator key.
ssh-keygen -q -t ed25519 -N '' -C github_testkey -f "$S/testkey"
ssh-agent -a "$S/ssh-agent.sock" > "$S/agent.env"
agent_pid="$(sed -n 's/^SSH_AGENT_PID=\([0-9]*\);.*/\1/p' "$S/agent.env")"
SSH_AUTH_SOCK="$S/ssh-agent.sock" ssh-add -q "$S/testkey" 2>/dev/null
cat > "$S/bin/bb" <<'EOF'
#!/usr/bin/env bash
# Stub: deterministic `bb doctor`, the emulator's image listings, and a
# `bb toolchains` that makes and removes directories instead of downloading
# gigabytes, which is enough for the Toolchains tab to watch a toolchain
# appear and disappear.
if [ "${1:-}" = doctor ]; then cat "${BB_DOCTOR_FIXTURE:?}"; fi
# The emulator's system images: the index of what could be added (with
# --available) and what is on disk, one of each plus one that is both, so the
# picker has something to leave out.
if [ "${1:-}" = emu ]; then
    case "${2:-}" in
        images)  if [ "${3:-}" = --available ]; then
                     printf 'system-images;android-31;google_apis;x86_64\t31\tgoogle_apis\t1470822277\n'
                     printf 'system-images;android-30;google_apis;x86_64\t30\tgoogle_apis\t1438186618\n'
                     printf 'system-images;android-30;google_apis_playstore;x86_64\t30\tgoogle_apis_playstore\t1404405641\n'
                 else
                     # ...with the AVD built on it, which is what makes it
                     # answerable whether the image can go.
                     printf 'system-images;android-30;google_apis;x86_64\tandroid-30\tgoogle_apis\t3300000\tfb30\n'
                 fi ;;
        flavors) printf 'google_apis\tx86_64\tGoogle APIs\tPlay services, no Play Store app. Rootable.\n'
                 printf 'google_apis_playstore\tx86_64\tGoogle APIs + Play Store\tThe Play Store app itself; not rootable.\n' ;;
    esac
fi
if [ "${1:-}" = toolchains ]; then
    # Where this stub pretends a toolchain lives. Shared by every verb, so
    # check and versions answer for what install and remove actually did:
    # a stub that claimed 1.0 for everything let a bug through where the page
    # showed an installed version on a row that had nothing installed.
    _d() {
        local n="${1#android:}"
        if [ "$n" != "$1" ]; then printf '%s/%s' "${ANDROID_HOME:?}" "$n"
        else printf '%s/%s' "${SDK_TEST_ROOT:?}" "$n"; fi
    }
    case "${2:-}" in
        root)    printf '%s\n' "${SDK_TEST_ROOT:?}" ;;
        versions) # local only: installed version, no upstream asked. Called
                  # with no names by the server, which wants the lot.
                 for n in ${3:-playwright flutter dotnet swift go rust zig android:emulator}; do
                     if [ -d "$(_d "$n")" ]; then printf '%s\t1.0\t-\tlocal\n' "$n"
                     else printf '%s\t-\t-\tabsent\n' "$n"; fi
                 done ;;
        check)   # one line per name: installed, latest, status. Absent rows
                 # answer too: what they would install is the other half of
                 # what the button is for.
                 # A fifth column on the absent rows: what an install would
                 # download, which is the only size a toolchain this box has
                 # never had can honestly show.
                 if [ ! -d "$(_d "$3")" ];  then printf '%s\t-\t9.9\tabsent\t123456789\n' "$3"
                 elif [ "$3" = flutter ];   then printf '%s\t1.0\t2.0\tupdate\n' "$3"
                 else                            printf '%s\t1.0\t1.0\tcurrent\n' "$3"; fi ;;
        update)  printf 'updated %s\n' "$3" ;;
        install|remove)
                 d="$(_d "$3")"
                 if [ "${2}" = install ]; then
                     # One toolchain takes its time and draws a bar, with the
                     # carriage returns a real tool uses, so a test can watch
                     # the progress reach the row through the whole path:
                     # streamed output, parser, payload, poll, render. Every
                     # other toolchain installs instantly, as before.
                     # One that fails, loudly and then quietly: a real
                     # install writes pages of progress and one useful line,
                     # and what reaches the operator has to be the line.
                     if [ "$3" = rust ]; then
                         for pct in 10 40 90; do
                             printf '[====] %s%% Downloading rust\r' "$pct"
                         done
                         printf '\ninfo: syncing channel updates\n'
                         # Long enough that a test can see the row mid-attempt:
                         # the last failure is cleared when the next one starts,
                         # and that is a state with a beginning and an end.
                         sleep 1.5
                         printf 'error: could not download file from upstream\n' >&2
                         exit 1
                     fi
                     if [ "$3" = go ]; then
                         # Takes a while, and counts loudly while it does,
                         # shaped like sdkmanager, whose meter runs one fraction
                         # across the whole operation and parks part way. None
                         # of it should reach the row; that is the point of the
                         # test that watches this.
                         printf 'Downloading go.tar.gz from https://example\n'
                         printf 'info: downloading installer\n'
                         for pct in 8 31 66 100; do
                             printf '[====] %s%% Downloading go.tar.gz\r' "$pct"; sleep 0.4
                         done
                         printf '\nUnzipping...\n'
                         printf '[====] 55%% Unzipping...\r'; sleep 2
                         printf '[====] 100%% Unzipping...\r\n'; sleep 0.3
                     fi
                     mkdir -p "$d" && : > "$d/marker"
                 else rm -rf "$d"; fi
                 printf '%sed %s\n' "${2%e}" "$3" ;;
    esac
fi
exit 0
EOF
chmod +x "$S/bin/bb"
# Stub claude: `auth status` answers from a fixture the tests flip, and
# `auth logout` rewrites that fixture rather than going anywhere near the
# operator's real credentials, which is the entire reason this stub exists,
# since the real one would sign this container out for good.
cat > "$S/bin/claude" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = auth ]; then
    case "${2:-}" in
        status) cat "${CLAUDE_AUTH_FIXTURE:?}" ;;
        logout) printf '{"loggedIn":false}\n' > "${CLAUDE_AUTH_FIXTURE:?}" ;;
        --help|help) printf 'Manage authentication\n' ;;
        # The flow, shaped like the real one: a URL, a prompt with no newline
        # after it, and a line read back. A code beginning "good" signs in and
        # rewrites the fixture; anything else is refused the way the real one
        # refuses an expired code. This is the half that could never be tested
        # while the sign-in lived in a terminal.
        login)
            printf 'Opening browser to sign in...\n'
            printf 'If the browser did not open, visit: '
            printf 'https://claude.com/cai/oauth/authorize?code=true&state=abc\n'
            printf 'Paste code here if prompted > '
            read -r code
            case "$code" in
                good*) cat "${CLAUDE_AUTH_IN:?}" > "${CLAUDE_AUTH_FIXTURE:?}"
                       printf '\nLogin successful.\n'; exit 0 ;;
                # The code it was handed, echoed back. The dashboard trims
                # what a copy brought along with it (a line break, the URL
                # the code page sets flush against the code), and this is how
                # a test sees what actually arrived rather than assuming.
                *) printf '\nLogin failed: Request failed with status code 400 [got %s]\n' "$code"
                   exit 1 ;;
            esac ;;
        *) exit 1 ;;
    esac
    exit 0
fi
exit 0
EOF
chmod +x "$S/bin/claude"
printf '{"loggedIn":true,"email":"tester@example.com","subscriptionType":"max"}
'     > "$S/auth-in.json"
printf '{"loggedIn":false}
' > "$S/auth-out.json"
cp "$S/auth-in.json" "$S/auth.json"

# Stub adb and web-ext, for the same reason as gh below: the phone card shells
# out to the real ones, and a suite whose answers depend on whether somebody
# has a handset paired right now is not a suite. These answer as a phone that
# is always there, so the card can be exercised on a box with nothing attached
# and, more to the point, cannot reach a box that has.
cat > "$S/bin/adb" <<'ADBEOF'
#!/usr/bin/env bash
case "$1 $2" in
  "devices -l") printf 'List of devices attached
192.168.9.9:5555	device product:test model:Test_Phone device:test
'; exit 0 ;;
esac
case "$1" in
  devices) printf 'List of devices attached
192.168.9.9:5555	device
'; exit 0 ;;
  pair)    printf 'Successfully paired to %s [guid=adb-TEST]
' "$2"; exit 0 ;;
  connect) printf 'connected to %s
' "$2"; exit 0 ;;
  disconnect) printf 'disconnected
'; exit 0 ;;
esac
# adb -s SERIAL install -r PATH. A file named *-clash.apk fails the way a
# signature mismatch really does, so the test can prove that answer is turned
# into a sentence rather than passed through raw.
if [ "$3" = install ]; then
    case "$5" in
        *-clash.apk) printf 'adb: failed to install %s: Failure [INSTALL_FAILED_UPDATE_INCOMPATIBLE]\n' "$5"; exit 1 ;;
        *) printf 'Performing Streamed Install\nSuccess\n'; exit 0 ;;
    esac
fi
# adb -s SERIAL shell "a line": a lent phone's (R113). A screenshot is a
# one-pixel PNG in base64, and a guarded touch or a start answers quietly.
if [ "$3" = shell ]; then
    case "$4" in
        *"screencap -p"*) printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='; exit 0 ;;
        *mCurrentFocus*|*"monkey -p"*|*"am force-stop"*) exit 0 ;;
    esac
fi
# adb -s SERIAL exec-out screencap -p: the same one-pixel PNG, as bytes, which
# is how a lent phone's shot comes back now (report #53).
if [ "$3 $4 $5" = "exec-out screencap -p" ]; then
    printf '%s' 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==' | base64 -d; exit 0
fi
# adb -s SERIAL shell screenrecord ... FILE, then pull FILE DEST: a lent
# phone's recording comes back as a pulled file (report #57). The stand-in
# MP4 carries an ftyp and a moov box, which is what a whole one has.
# A recording left running (record start) and interrupted (record stop) too.
if [ "$3" = shell ] && case "$4" in screenrecord*|"nohup screenrecord"*|"pkill -INT screenrecord"*) true ;; *) false ;; esac; then exit 0; fi
if [ "$3" = pull ]; then printf '\0\0\0\x18ftypmp42\0\0\0\0mp42isom\0\0\0\x08moov' > "$5"; exit 0; fi
# adb -s SERIAL shell pm list packages
if [ "$4 $5 $6" = "pm list packages" ]; then
    printf 'package:org.mozilla.firefox_beta
package:com.android.chrome
'; exit 0
fi
exit 0
ADBEOF
chmod +x "$S/bin/adb"

# docker, stubbed the way adb is: every call lands in docker.log, and a tiny
# state machine under dockerstate/ answers compose ps/up/down/build so the
# dev-instance row can be driven end to end with no daemon anywhere.
mkdir -p "$S/dockerstate"
cat > "$S/bin/docker" <<'DOCKEREOF'
#!/usr/bin/env bash
# The state is named in the environment by the harness and the fixture
# agent; a JOB on the fixture node runs with the clean environment the agent
# hands every exec (bug #45), so a `docker ps` read there finds it beside
# this binary instead, the way the harness lays the two out.
ST="${DOCKER_STUB_STATE:-$(dirname "$(dirname "$(readlink -f "$0")")")/dockerstate}"
echo "$*" >> "$ST/docker.log"
# A host that is not there. The real CLI carries the address in DOCKER_HOST;
# listing one in deadhosts makes every call against it fail the way a powered
# off VM does, so the suite can have one node answering and another not.
if [ -n "${DOCKER_HOST:-}" ] && [ -f "$ST/deadhosts" ] \
   && grep -qF "$DOCKER_HOST" "$ST/deadhosts"; then
  echo "cannot connect to the daemon at $DOCKER_HOST"; exit 1
fi
# The one-shot `run` the dev-data probe makes (mkdir, mv, test -d on one
# share). Answers yes by default; run.testfail is the suite saying the marker
# is NOT over there: a clean exit 1 with nothing said, as `test -d` does.
if [ "$1" = run ] && [ -f "$ST/run.testfail" ]; then exit 1; fi
# What a node pulled of an image (imagecheck.py, R195): its RepoDigests from
# a file the suite leaves, named for the image; none is an image never pulled.
if [ "$1" = inspect ] && [ "$2" = --type ] && [ "$3" = image ]; then
  f="$ST/repodigests/$(printf %s "${*: -1}" | tr '/:' '__')"
  [ -f "$f" ] && { cat "$f"; exit 0; }
  echo "Error: No such image: ${*: -1}"; exit 1
fi
case "$1" in
  # A daemon that is not there at all: the VM powered off, or an address that
  # is not a sandbox VM. availability is what the page gates every Docker
  # control on, so the suite has to be able to take it away.
  # Shaped like docker's real connect error, which leads with the command it
  # ran and hides the reason at the end after `stderr=`, the shape the row
  # used to cut the reason off (B106).
  version) [ -f "$ST/version.fail" ] && {
      echo 'error during connect: Get "http://docker.example.com/v1.56/version": command [ssh -l bb -o ConnectTimeout=30 -T -- 10.0.0.9 docker system dial-stdio] has exited with exit status 255, make sure the URL is valid, and Docker 18.09 or later is installed on the remote host: stderr=ssh: connect to host 10.0.0.9 port 22: No route to host'
      exit 1; }
    echo "99.stub"; exit 0 ;;
  # What the daemon says it is. The provisioner's label lives here, and this is
  # how BuilderBot tells the sandbox from any other machine that answers
  # Docker, so the suite can take the stamp away (unlabeled.fail) and can
  # make it a DIFFERENT sandbox (uid file), which is the other question:
  # whether records from the last one are cleared when a new one is plugged in.
  info)
    [ -f "$ST/info.fail" ] && { echo "cannot connect to the daemon"; exit 1; }
    lbl='["builderbot.sandbox=1"]'
    [ -f "$ST/unlabeled" ] && lbl='["com.example.other=1"]'
    uid="STUBDAEMON1"
    [ -f "$ST/uid" ] && uid="$(cat "$ST/uid")"
    # The runtimes the daemon lists: nvidia's once the container toolkit's
    # stand-in has "configured" it (R102).
    rt='{"runc":{}}'
    [ -f "$ST/nvidia-runtime" ] && rt='{"nvidia":{"path":"nvidia-container-runtime"},"runc":{}}'
    printf '{"ID":"%s","Labels":%s,"ServerVersion":"99.stub","Runtimes":%s}\n' "$uid" "$lbl" "$rt"
    exit 0 ;;
  ps)
    # The bare `docker ps` the Docker manager reads. Stateful, because the
    # manager derives running/stopped from it: a compose `up` leaves a marker
    # and this turns each marker into the container that `up` would have
    # started. A fixed list made the manager disagree with the compose stub
    # about what was running, which is a test lying in the shape of a bug.
    # Shaped like docker's real connect error, the same as `version` above:
    # the reason is at the END after `stderr=`, and the manager now shows a
    # failed LISTING on the row (B111 split the listing from availability), so
    # this side has to be cut from the tail too or it says nothing (B106).
    [ -f "$ST/ps.fail" ] && {
      echo 'error during connect: Get "http://docker.example.com/v1.56/containers/json": command [ssh -l bb -o ConnectTimeout=30 -T -- 10.0.0.9 docker system dial-stdio] has exited with exit status 255, make sure the URL is valid, and Docker 18.09 or later is installed on the remote host: stderr=ssh: connect to host 10.0.0.9 port 22: No route to host'
      exit 1; }
    for f in "$ST"/*.up; do
      [ -e "$f" ] || continue
      pn="$(basename "$f" .up)"
      # A stack of more than one container, where a test lays one out in
      # $pn.svcs: a line per published port, "SERVICE HOSTPORT TARGET",
      # and one container per service carrying all of its lines (B252).
      if [ -f "$ST/$pn.svcs" ]; then
        for sv in $(awk '{print $1}' "$ST/$pn.svcs" | sort -u); do
          pp="$(awk -v s="$sv" '$1 == s {printf "%s0.0.0.0:%s->%s/tcp", (n++ ? ", " : ""), $2, $3}' "$ST/$pn.svcs")"
          printf '{"ID":"aaaa%s%s","Names":"%s-%s-1","Image":"%s-img","State":"running","Status":"Up 3 minutes","Ports":"%s","Labels":"com.docker.compose.project=%s,com.docker.compose.service=%s"}\n' \
            "$pn" "$sv" "$pn" "$sv" "$pn" "$pp" "$pn" "$sv"
        done
        continue
      fi
      printf '{"ID":"aaaa%s","Names":"%s-app-1","Image":"%s-img","State":"running","Status":"Up 3 minutes","Ports":"0.0.0.0:7475->7474/tcp, [::]:7475->7474/tcp","Labels":"com.docker.compose.project=%s,com.docker.compose.service=app"}\n' \
        "$pn" "$pn" "$pn" "$pn"
    done
    # An exited container is still THERE, holding its name and its network,
    # which is why Down stays live for one and why the manager has to see it.
    for f in "$ST"/*.exited; do
      [ -e "$f" ] || continue
      pn="$(basename "$f" .exited)"
      [ -e "$ST/$pn.up" ] && continue          # up wins: it is the same one
      printf '{"ID":"bbbb%s","Names":"%s-app-1","Image":"%s-img","State":"exited","Status":"Exited (1) 1 minute ago","Ports":"","Labels":"com.docker.compose.project=%s,com.docker.compose.service=app"}\n' \
        "$pn" "$pn" "$pn" "$pn"
    done
    # And one this dashboard did not start, which is the distinction the
    # listing exists to draw.
    printf '%s\n' '{"ID":"ccccccccccccdddd","Names":"someone-elses","Image":"redis:7","State":"exited","Status":"Exited (0) 2 hours ago","Ports":"","Labels":"com.docker.compose.project=other"}'
    exit 0 ;;
  images)
    # The daemon's images (R216): one in use by the fixture's container and
    # one dangling, in docker's own json shape.
    printf '%s\n' '{"Repository":"ep-silon-img","Tag":"latest","ID":"sha256:1111aaaa2222","Size":"123MB","CreatedSince":"2 days ago"}'
    printf '%s\n' '{"Repository":"<none>","Tag":"<none>","ID":"sha256:3333bbbb4444","Size":"45.6MB","CreatedSince":"3 weeks ago"}'
    exit 0 ;;
  image)
    # image prune -f: what docker says, and a record that it was asked.
    printf '%s\n' "image $2 $3" >> "$ST/ctl.log"
    printf 'Deleted Images:\ndeleted: sha256:3333bbbb4444\n\nTotal reclaimed space: 45.6MB\n'
    exit 0 ;;
  volume)
    case "$2" in
      ls) printf '%s\n' '{"Driver":"local","Name":"ep-silon_data"}' '{"Driver":"local","Name":"orphan-vol"}'; exit 0 ;;
      prune) printf '%s\n' "volume $2 $3" >> "$ST/ctl.log"; printf 'Deleted Volumes:\norphan-vol\n\nTotal reclaimed space: 2.1MB\n'; exit 0 ;;
    esac
    echo "stub: volume $2"; exit 1 ;;
  system)
    [ "$2" = "df" ] || { echo "stub: system $2"; exit 1; }
    printf '%s\n' '{"Type":"Images","TotalCount":"2","Active":"1","Size":"168.6MB","Reclaimable":"45.6MB (27%)"}'
    printf '%s\n' '{"Type":"Containers","TotalCount":"1","Active":"1","Size":"1.2MB","Reclaimable":"0B (0%)"}'
    printf '%s\n' '{"Type":"Local Volumes","TotalCount":"2","Active":"1","Size":"8.4MB","Reclaimable":"2.1MB (25%)"}'
    exit 0 ;;
  stats)
    # What each running container uses now (R216): one line per `up`
    # marker, in docker's own json shape and units, with the service
    # names the ps above gives. Fixed figures: a test reads the row's
    # strip, not the daemon's arithmetic.
    for f in "$ST"/*.up; do
      [ -e "$f" ] || continue
      pn="$(basename "$f" .up)"
      if [ -f "$ST/$pn.svcs" ]; then
        for sv in $(awk '{print $1}' "$ST/$pn.svcs" | sort -u); do
          printf '{"Name":"%s-%s-1","CPUPerc":"1.25%%","MemUsage":"12.7MiB / 21.4MiB","MemPerc":"2.66%%","NetIO":"1.2kB / 648B","PIDs":"11"}\n' "$pn" "$sv"
        done
        continue
      fi
      printf '{"Name":"%s-app-1","CPUPerc":"1.25%%","MemUsage":"12.7MiB / 21.4MiB","MemPerc":"2.66%%","NetIO":"1.2kB / 648B","PIDs":"22"}\n' "$pn"
    done
    exit 0 ;;
  start|stop|restart)
    # One container by name, which is all the guard lets through (R68). The
    # stub records what it was asked so a test can see the verb reached the
    # daemon, and answers the way docker does: the name back.
    printf '%s\n' "$2" >> "$ST/ctl.log"
    printf '%s\n' "$2"
    exit 0 ;;
  logs)
    # --tail N --timestamps NAME, rebuilt by devapp; anything else never
    # reaches here because the guard refuses it first.
    printf '2026-09-21T00:00:01.000000000Z hello from %s\n' "${!#}"
    printf '2026-09-21T00:00:02.000000000Z second line\n'
    exit 0 ;;
  compose)
    proj=""
    args=("$@")
    for ((i=0;i<${#args[@]};i++)); do
      [ "${args[$i]}" = "--project-name" ] && proj="${args[$((i+1))]}"
    done
    verb=""
    for a in ps build up down config exec; do
      for x in "$@"; do [ "$x" = "$a" ] && verb="$a"; done
    done
    case "$verb" in
      exec)
        # `compose exec [-T] [-e K=V]... SERVICE CMD...`: the command runs
        # right here, which is what proves the wiring of a test inside a
        # dev instance (roadmap R48) without a container.
        [ -f "$ST/$proj.up" ] || { echo "service \"app\" is not running"; exit 1; }
        echo "exec $*" >> "$ST/docker.log"
        while [ $# -gt 0 ] && [ "$1" != exec ]; do shift; done; shift
        while [ $# -gt 0 ]; do
          case "$1" in -T) shift ;; -e|-w|--workdir) shift 2 ;; -*) shift ;; *) break ;; esac
        done
        shift   # the service
        exec "$@" ;;
      config)
        # -q is the validation the container-create path runs: no output, just
        # a verdict. A file lets a test ask for a compose that will not parse.
        for x in "$@"; do [ "$x" = "-q" ] && {
          [ -f "$ST/config.fail" ] && { echo "yaml: line 2: mapping values are not allowed"; exit 1; }
          exit 0; }
        done
        # A service that declares a build, which is what the fixture has,
        # unless a test wants a different shape, which it leaves here.
        if [ -f "$ST/$proj.config" ]; then cat "$ST/$proj.config"
        else echo '{"services":{"app":{"build":{"context":"."},"ports":[{"target":7474,"published":"7475","protocol":"tcp"}],"volumes":[{"type":"bind","source":"/mnt/user/plex-media","target":"/library","read_only":true},{"type":"bind","source":"/mnt/user/appdata/x/config","target":"/config"}]}}}'
        fi
        exit 0 ;;
      ps)
        # -a asks "does anything exist here", bare ps asks "what is running":
        # an exited container answers yes to the first and no to the second,
        # and that gap is the whole reason Down has to stay live.
        all=0
        for x in "$@"; do case "$x" in -a|-aq) all=1 ;; esac; done
        if [ -f "$ST/$proj.up" ]; then echo "stubcontainer"
        elif [ "$all" = 1 ] && [ -f "$ST/$proj.exited" ]; then echo "stubexited"
        fi
        exit 0 ;;
      build)
        echo "BUILDKIT=${DOCKER_BUILDKIT:-unset}" >> "$ST/docker.log"
        echo "BB_BUILD_REV=${BB_BUILD_REV:-unset} BB_BUILD_AT=${BB_BUILD_AT:-unset}" >> "$ST/docker.log"
        [ -f "$ST/build.fail" ] && { echo "stub build exploded"; exit 1; }
        # A build that takes its time and says so, for the two properties a
        # fast one cannot show: that its output arrives WHILE it runs, and
        # that it can be interrupted. Line-buffered on purpose: a pull writes
        # a line at a time and the reader is asserting it sees them early.
        if [ -f "$ST/build.slow" ]; then
          # Long enough that a test can see it running, open the manager and
          # press Abort while it still is: the manager repaints on its own
          # fetch, so "the log has a line in it" and "the click lands" are
          # several seconds apart on a loaded box.
          for i in $(seq 1 60); do
            echo "pulling layer $i"
            sleep 0.5
          done
        fi
        echo "stub built ok"; exit 0 ;;
      up)
        # A failing up, for the row that has to survive one: compose creates
        # the container and then cannot start it, the shape of a bind mount
        # landing on a share that squashes root.
        if [ -f "$ST/up.fail" ]; then
          touch "$ST/$proj.exited"
          printf ' Container %s-x-1 Creating \n Container %s-x-1 Created \n' "$proj" "$proj"
          printf ' Container %s-x-1 Starting \n' "$proj"
          echo "Error response from daemon: error while creating mount source path"
          exit 1
        fi
        touch "$ST/$proj.up"; exit 0 ;;
      down) rm -f "$ST/$proj.up" "$ST/$proj.exited"; exit 0 ;;
    esac
    exit 0 ;;
esac
exit 0
DOCKEREOF
chmod +x "$S/bin/docker"
# web-ext that installs and then sits there, the way the real one does.
cat > "$S/bin/web-ext" <<'WEEOF'
#!/usr/bin/env bash
printf 'Running web extension from here
'
sleep 0.3
printf 'Installed /data/local/tmp/probe.xpi as a temporary add-on
'
printf 'The extension will reload if any source file changes
'
while :; do sleep 1; done
WEEOF
chmod +x "$S/bin/web-ext"

# Stub gh: always unauthenticated, so `pat` is deterministically false; the
# real gh would answer from the operator's own login state.
printf '#!/usr/bin/env bash\nexit 1\n' > "$S/bin/gh"
chmod +x "$S/bin/gh"
printf '  [ok]   claude on PATH\n  [ok]   github reachable\n  [ok]   disk space\n  [skip] gpu (no device)\n' > "$S/doctor-ok.txt"
{ cat "$S/doctor-ok.txt"; echo '  [warn] clock skew 3s'; echo '  [FAIL] runner offline'; echo '         diagnose with: bb logs --runner'; } > "$S/doctor-fail.txt"
cp "$S/doctor-ok.txt" "$S/doctor.txt"
python3 - "$S/reports/test.sarif" <<'EOF'
import json, sys
def res(rule, level, uri):
    return {"ruleId": rule, "level": level, "message": {"text": "test finding"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": uri},
                                                "region": {"startLine": 3}}}]}
doc = {"version": "2.1.0", "runs": [{"tool": {"driver": {"name": "testscan", "rules": []}},
       "results": [res("A1", "error", "scan/alpha/a.sh"), res("B1", "note", "scan/beta/x.py"),
                   res("G1", "error", "scan/gamma/g.c"), res("D1", "warning", "scan/delta/d1.c"),
                   # Two the scanner swept that are not projects: one marked
                   # with .bbignore, one not marked at all. Both must be set
                   # aside rather than counted as unattributed.
                   res("T1", "error", "scan/toolstore/vendor/lib.py"),
                   res("V1", "error", "scan/vendored-junk/deep/thing.py"),
                   # ...and one that genuinely places nowhere, which is what
                   # the unattributed label is actually for.
                   res("U1", "warning", "somewhere/else/entirely.py")]}]}
open(sys.argv[1], "w").write(json.dumps(doc))
EOF
# Each test file starts from the same place: an unwritten layout and both
# throwaway sessions present: a file that minimizes tabs or ends a session
# must not hand that state to the next.
# The compose fixture project's binding to the sandbox node, once the node
# exists (sandbox_id, set at enrolment); a no-op before that.
bind_fixture_node() {
    [ -n "${sandbox_id:-}" ] || return 0
    curl -fs -u test:test -H 'Content-Type: application/json' \
        -d "{\"project\":\"ep.silon\",\"node\":\"$sandbox_id\"}" \
        "http://127.0.0.1:$PORT/api/prefs" >/dev/null || die "could not bind ep.silon to the sandbox node"
}

fresh() {
    rm -f "$S/state/tabs.json" "$S/state/cards.json" "$S/state/roadmap.json" \
          "$S/state/bugs.json"
    # ...nor the rules and the approval queue (roadmap #7, #27): a rule or a
    # held change left by pending.mjs lit the bell and filled the Briefing
    # tab for every file after it.
    rm -f "$S/state/rules.json" "$S/state/pending.json"
    # ...and the test registry: uniform.mjs ingests a run of its own so the
    # Tests view has rows, and testreg.mjs counts what it ingests.
    rm -f "$S/state/tests.json"
    echo '["delta"]' > "$S/state/locked-projects.json"     # a test that locks must not hand that on
    rm -f "$S/state/pinned-projects.json"                  # ...nor one that unpins
    # ...nor one that binds a project to a node. nodes.mjs saves alpha's node
    # from the settings dialog; agent.mjs then asserts that a project with no
    # node is refused, and inherited the binding, a deterministic failure of
    # the pair that neither file showed alone.
    rm -f "$S/state/claude-prefs.json"
    # ...and then the one binding every file starts from: the compose
    # fixture project works on the sandbox node, the way an operator binds
    # one, since a project with none has no Docker row at all (R82).
    bind_fixture_node
    # ...nor one that built a dev instance. agent.mjs runs a compose action
    # on its node now, which records what was built and on which daemon;
    # devapp.mjs then opened on a project that believed it had been built
    # somewhere else. Per-run state, like the rest of this list.
    rm -f "$S/state/devapps.json"
    rm -rf "$S/state/devenv"
    # Projects a test created through /api/create go too: anything that is
    # not one of the five fixtures. Scoped to $S, like every rm in this file.
    # .claude stays: it is where every account's ~/.claude/projects points
    # (roadmap #24), and removing it leaves the home's link dangling, which
    # is what made seed_memories' mkdir fail with "File exists" on the
    # second file of a run. It is per-run state like the home is.
    find "$S/ws" -maxdepth 1 -mindepth 1 -type d \
        ! -name alpha ! -name beta ! -name gamma ! -name delta ! -name ep.silon \
        ! -name toolstore ! -name vendored-junk ! -name .claude -exec rm -rf {} +
    # ...nor one that UNLINKED a project. create.mjs unlinks alpha through the
    # real /api/unlink, which is meant to take the remote, the stored token
    # and the push grant all at once, so `run.sh create cards` handed cards
    # an alpha that pushes nowhere, and its chain dialog, which expects a
    # deploy key, failed on two assertions and then timed out. Alphabetical
    # order is why CI never met it: cards runs first in a whole run.
    # Put back, not removed: the grant is seeded above as a literal, the way
    # locked-projects is, so a fixture does not lean on a migration.
    printf '{"alpha":{"repo":"owner/alpha","host":"github.com","how":"key","at":1756000000}}\n' \
        > "$S/state/push-rights.json"
    rm -rf "$S/state/gitcreds"          # ...and a token a link dialog stored
    ( cd "$S/ws" \
      && git -C alpha remote set-url origin git@github.com:owner/alpha.git 2>/dev/null \
         || git -C alpha remote add origin git@github.com:owner/alpha.git
      cd "$S/ws" \
      && git -C ep.silon remote set-url origin https://gitlab.example/eps.git 2>/dev/null \
         || git -C ep.silon remote add origin https://gitlab.example/eps.git ) 2>/dev/null || true
    rm -rf "$S/home/.ssh"           # deploy-key selectors a test wrote
    rm -rf "$S/dockerstate"; mkdir -p "$S/dockerstate"
    rm -rf "$S/sdk" "$S/androidsdk"; mkdir -p "$S/sdk" "$S/androidsdk"
    # The phone stub, put back if a test that hid it died before restoring
    # it. artifacts.mjs renames bin/adb aside to prove Push goes dead; when
    # its next wait timed out the rename never reversed, and every suite
    # after it ran with no phone and failed on things that had nothing to do
    # with phones, a cascade that read as five bugs and was one.
    [ -e "$S/bin/adb.hidden" ] && mv -f "$S/bin/adb.hidden" "$S/bin/adb"
    cp "$S/doctor-ok.txt" "$S/doctor.txt"
    cp "$S/auth-in.json" "$S/auth.json"   # a test that signs out must not hand that on
    rm -f "$S/login-finished"
    seed_memories                   # memory.mjs edits and deletes these for real
    for n in shell-9 claude-alpha; do
        tmux has-session -t "$n" 2>/dev/null || tmux new-session -d -s "$n" -c /tmp
        # A test that typed into a pane without pressing Enter (the memory
        # book's note does exactly that) must not hand the half-typed line
        # to the next file. C-u is kill-line, not a signal.
        tmux send-keys -t "$n" C-u 2>/dev/null || true
    done
}
fresh

# ---- server ----------------------------------------------------------------
# BB_DEV_DATA_DIR belongs in here with the rest: devapp.py defaults the
# dev-data root to /devdata, and everything else was redirected while that
# was not, so the ep.silon fixture's instance did an mkdir in the operator's
# REAL /devdata, which this suite's whole story is that it cannot do. It is
# per-command env, deliberately: the node tests further down still see the
# container's own /devdata, which is what the module-level host_map() and
# problems() snippets in devapp.mjs are written against.
#
# DOCKER_HOST names an ssh:// address because that shape is now the feature's
# switch: a sandbox VM is the only daemon the manager drives, so anything else
# grays every control out and the suite would be testing a dead tab. The stub
# docker on PATH answers whatever it is pointed at, so no VM is involved.
#
# DOCKER_HOST_PATHS is cleared for the same reason and was found the same way.
# Unset here, it inherited the REAL container's mapping, so what the dev row
# said about a fixture's compose file depended on how the operator had wired
# their own daemon, a suite that passes on one box and fails on the next with
# nothing in the diff to explain it. Found when a check on an identity pair
# started firing against this box's /workspace:/workspace.
# The server and the stub are started from a subshell, so init adopts them
# and this shell never has them as children: bash reaping a killed child of
# its own asynchronously was "wait_for: No record of process", which ended
# the whole run now and then. Their pids come back through a file outside $S.
PIDF="$(mktemp "${TMPDIR:-/tmp}/dashboard-test-pid.XXXXXX")"
start_server() {
( env WORKSPACE="$S/ws" DASHBOARD_PORT="$PORT" DASHBOARD_TTYD_PORT=7999 BUILDER_HOME="$S/home" \
    BB_BIN="$S/bin/bb" SDK_TEST_ROOT="$S/sdk" ANDROID_HOME="$S/androidsdk" \
    TC_AUTOCHECK=0 BB_NODE_POLL=3 \
    SSH_AUTH_SOCK="$S/ssh-agent.sock" \
    FINDINGS_DIR="$S/reports" DASHBOARD_STATE="$S/state" \
    BB_DOCTOR_FIXTURE="$S/doctor.txt" CLAUDE_AUTH_FIXTURE="$S/auth.json" \
    BB_IMAGE_REV=abc1234def5678901234567890abcdef12345678 \
    BB_IMAGE_BUILT=2026-08-21T19:30Z \
    BB_VERSION=0.4.0-dev.390+abc1234 \
    CLAUDE_AUTH_IN="$S/auth-in.json" \
    BB_LOGIN_DONE="$S/login-finished" \
    PATH="$S/bin:$PATH" BB_WEBEXT_BIN="$S/bin/web-ext" BB_ADB_BIN="$S/bin/adb" \
    BB_DOCKER_BIN="$S/bin/docker" DOCKER_STUB_STATE="$S/dockerstate" \
    BB_DEV_DATA_DIR="$S/devdata" \
    BB_COVERAGE_OUT="${BB_COVERAGE_DIR:+$BB_COVERAGE_DIR/server-$RANDOM.json}" \
    BB_COVERAGE_SUITE="${BB_COVERAGE_SUITE:-server}" \
    BB_ARCHIVE_SPOOL="$S/spool" \
    BB_CLAUDE_LATEST_URL="file://$S/claude-latest" BB_CLAUDE_CHECK_DELAY=3600 \
    BB_NGINX_TAGS_URL="file://$S/nginx-tags.json" BB_NGINX_CHECK_DELAY=3600 \
    BB_IMAGE_DIGESTS_FILE="$S/image-digests.json" BB_IMAGE_CHECK_DELAY=3600 \
    BUILDERBOT_IDLE_UNIT=1 \
    BB_COMPAT_SWEEP=1 \
    BB_CLOUDFLARED="$DASH/test/cloudflared-stub.sh" \
    BB_TUNNEL_ROUTE_BASE="http://127.0.0.1:$PORT" \
    BUILDERBOT_ROLE=controller BB_TOKEN= \
    DEBUG_MODE=1 \
    python3 "$DASH/server.py" >> "$S/server.log" 2>&1 &
  echo $! > "$PIDF" )
pid="$(cat "$PIDF")"
for _ in $(seq 40); do
    curl -fs -u test:test -o /dev/null "http://127.0.0.1:$PORT/api/status" && break
    kill -0 "$pid" 2>/dev/null || { cat "$S/server.log"; die "server exited"; }
    sleep 0.25
done
}
start_server

# ---- the owner ---------------------------------------------------------------
# There is no DASHBOARD_AUTH any more: a fresh container serves a first-run
# screen and the person at it makes the owner. The harness cannot use that
# form: its credential is `test:test`, and the form enforces an eight
# character password, which every other file here would then have to know
# about. So it claims the store directly, which is the same call the form
# makes. The form's own path is covered in auth.mjs, against a store of its
# own.
python3 - "$DASH/users.py" "$S/state" "$S/ws" <<'PY'
import importlib.util, json, os, sys
spec = importlib.util.spec_from_file_location("users", sys.argv[1])
u = importlib.util.module_from_spec(spec); spec.loader.exec_module(u)
u.configure(state=sys.argv[2], write_json=lambda p, d: open(p, "w").write(json.dumps(d)))
d = u.load()
# The fixture projects by name (R135): "*" lists every project and takes
# none on, and this seed lands after the server started, past the start-time
# migration that turns an existing owner's "*" into names.
fixtures = sorted(n for n in os.listdir(sys.argv[3])
                  if os.path.isdir(os.path.join(sys.argv[3], n)) and not n.startswith("."))
d["users"]["test"] = {"uid": u.mint_uid(), "role": "owner", "projects": fixtures,
                      # An author, or no Claude session starts for it (users.git_ready).
                      # ...and the welcome panel read, or it would open over
                      # every page load in the suite (cards.mjs opens it on purpose).
                      "prefs": {"full_name": "Dashboard Test", "email": "test@example.invalid",
                                "welcome_seen": True,
                                "image_seen": "abc1234def5678901234567890abcdef12345678"},
                      "password": u.hash_password("test"), "created": 0,
                      "seen": 0}
u._save(d)
PY

# ---- the docker-host node --------------------------------------------------
# The suite needs one node whose daemon the controller can address, and it
# used to get one from DOCKER_HOST: the server mirrored the variable into an
# `ssh`-kind row at boot. That kind is retired (roadmap #24) and so is the
# seed, so the harness enrolls the node the way an operator now does: mint a
# token, then present it on the agent channel.
#
# Two things are written rather than probed, because this container is not a
# node and cannot pretend to be one:
#   * X-Forwarded-For, so the row records the address the stub docker answers
#     for (`stub`) instead of 127.0.0.1, which is also where every OTHER node
#     a test enrolls dials in from;
#   * sshd in the census, because nodes._addr only hands out an ssh address
#     for a node that reports one, and devapp.available() needs that address.
#     There is no sshd in here and no way to bind port 22 without privileges.
# This is the same shape nodes.mjs already uses for its second docker node.
sandbox_json=$(curl -fs -u test:test -H 'Content-Type: application/json' \
    -d '{"action":"enroll","name":"sandbox","user":"bb"}' \
    "http://127.0.0.1:$PORT/api/v1/nodes") || {
        cat "$S/server.log"; die "could not mint the sandbox node's token"; }
sandbox_tok=$(printf '%s' "$sandbox_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
sandbox_node=$(curl -fs -H "Authorization: Bearer $sandbox_tok" \
    -H 'Content-Type: application/json' -H 'X-Forwarded-For: stub' \
    -d '{"user":"bb","version":"harness","census":{"cpu":4,"mem_mb":8192,
         "arch":"x86_64","system":"linux","sshd":true,"docker":true}}' \
    "http://127.0.0.1:$PORT/api/v1/agent/enroll") || {
        cat "$S/server.log"; die "the sandbox node would not enroll"; }

# ...and something on the node to take its jobs. Compose on an agent node is
# the agent's, so without this every Up and Rebuild in the suite would queue
# and then be reconciled away. agent-stub.py's header says why it is a stub
# and not the shipped agent.
stub_token="$(printf '%s' "$sandbox_node" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')"
# The compose fixture project works on the sandbox node, the way an operator
# binds one: there is no default node for a project's containers to fall to
# (R82, 25 Sep), so a project with none has no Docker row at all. Bound
# again by fresh() before every file, which wipes the settings first.
sandbox_id="$(printf '%s' "$sandbox_node" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("node_id") or d.get("id") or "")')"
bind_fixture_node
# ...and the tester's Claude sign-in on that node. The controller holds no
# credential (R47): a login is one account's on one node, and what is kept
# here is the RECORD of what each node reported. Without one the fixture
# node reads as not signed in, and every Claude press in the suite would go
# to its sign-in instead of to a session.
mkdir -p "$S/home/.claude"
printf '{"nodes": {"%s": {"email": "tester@example.com", "plan": "max", "at": 1}}}\n' "$sandbox_id" \
    > "$S/home/.claude/.bb-grant.json"
chmod 600 "$S/home/.claude/.bb-grant.json"
start_stub() {
    ( STUB_AGENT_URL="http://127.0.0.1:$PORT" \
    STUB_AGENT_DIR="$S/sandboxdata" \
    STUB_AGENT_TOKEN="$stub_token" \
    DOCKER_STUB_STATE="$S/dockerstate" PATH="$S/bin:$PATH" \
        python3 "$HERE/agent-stub.py" >> "$S/agent-stub.log" 2>&1 &
      echo $! > "$PIDF" )
    stub_pid="$(cat "$PIDF")"
}
start_stub

# ---- one world per file (B124) ---------------------------------------------
# Every file starts from the same world, whatever the one before it did. The
# fixture above is built once and kept whole (everything under $S but the
# private tmux server, the ssh-agent's socket, the logs and the copy itself);
# before each file the server and the stub agent stop, the copy is put back
# and both start again. Before this, fresh() below kept a hand-written list
# of files to reset, and every leak it missed was a failure that showed only
# in a whole run: a node, an account or a setting one file made, in the
# database, in memory, read by the next. A list cannot keep up with that; a
# copy of everything does. It costs a server start per file, about a second.
stop_world() {
    local p _
    for p in "$pid" "$stub_pid"; do [ -z "$p" ] || kill "$p" 2>/dev/null || true; done
    # Polled, not waited for: bash's wait on a child it has already reaped
    # is an internal error that ended the script, and the database has to be
    # closed before its files are copied or put back.
    for p in "$pid" "$stub_pid"; do
        [ -n "$p" ] || continue
        for _ in $(seq 50); do kill -0 "$p" 2>/dev/null || break; sleep 0.1; done
        kill -9 "$p" 2>/dev/null || true
    done
    pid=""; stub_pid=""
}
# ...and the coverage counts, which every suite adds to and a restore must not
# take back to the empty directory the snapshot holds (R76).
WORLD_OUT=(tmux ssh-agent.sock server.log agent-stub.log .world.tar coverage)
snapshot_world() {
    local ex=() n
    for n in "${WORLD_OUT[@]}"; do ex+=("--exclude=./$n"); done
    ( cd "$S" && tar cf .world.tar "${ex[@]}" . )
}
restore_world() {
    local keep=() n
    for n in "${WORLD_OUT[@]}"; do keep+=(! -name "$n"); done
    find "$S" -mindepth 1 -maxdepth 1 "${keep[@]}" -exec rm -rf {} +
    ( cd "$S" && tar xf .world.tar )
}
# Up and dialed in: the stub says hello the moment it starts, and a file that
# opens on the node's row must not meet it still marked as not answering.
wait_stub() {
    local since="$1" _
    for _ in $(seq 40); do
        curl -fs -u test:test "http://127.0.0.1:$PORT/api/v1/nodes" 2>/dev/null \
            | python3 -c 'import json,sys; since=float(sys.argv[1]); d=json.load(sys.stdin)
n=[x for x in d.get("nodes",[]) if x.get("name")=="sandbox"]
sys.exit(0 if n and float((n[0].get("agent") or {}).get("last_seen") or 0) >= since else 1)' "$since" \
            && return 0
        sleep 0.25
    done
    warn "the stub agent did not dial in again within ten seconds"
}
# BB_TEST_PHASES=1 says what each part of a suite's set-up cost, which is
# the time no check measures: a suite's own seconds are its checks', and
# roles and bugs measured 91 s of checks in 182 s of run (30 Sep).
phase() {
    [ -n "${BB_TEST_PHASES:-}" ] || { "$@"; return; }
    local t0 rc=0; t0="$(date +%s%N)"
    "$@" || rc=$?
    log "phase $1: $(( ($(date +%s%N) - t0) / 1000000 )) ms"
    return "$rc"
}
fresh_world() {
    local since
    phase stop_world
    phase restore_world
    since="$(date +%s)"
    phase start_server
    phase start_stub
    phase wait_stub "$since"
}
stop_world
snapshot_world

# ---- kept: the world is up; wait for bb tests keep stop --------------------
if [ -n "${BB_TEST_HOLD:-}" ]; then
    fresh_world
    fresh
    KEEP_MINE=1
    printf 'KEEP_PID=%s\nKEEP_URL=%s\nKEEP_S=%s\nKEEP_HERE=%s\nKEEP_CHROME=%s\nKEEP_SINCE=%s\n' \
        "$$" "http://127.0.0.1:$PORT/" "$S" "$HERE" "$CHROME" "$(date +%s)" > "$KEEPF"
    log "fixture kept at http://127.0.0.1:$PORT/ (test:test); bb dashboard test SUITE and bb tests probe FILE attach to it; bb tests keep stop ends it"
    while :; do sleep 3600 & wait $! || true; done
fi

# ---- tests -----------------------------------------------------------------
# Each suite as a file to run and as the name it was asked for by, which is
# what a worker hands back for a failed one: its parent asks for it again
# by that name, and a probe's copy under $HERE is gone with the worker.
tests=()
names=()
if [ $# -gt 0 ]; then
    for t in "$@"; do
        case "$t" in
            # A probe (`bb tests probe FILE`): a script from anywhere, copied
            # beside lib.mjs so its `./lib.mjs` resolves, and removed after.
            /*) f="$HERE/_probe-$(basename "${t%.mjs}").mjs"; cp "$t" "$f"; probes+=("$f"); tests+=("$f") ;;
            *)  # A name that is no suite is said so before anything runs,
                # not reported later as a suite that "failed again alone".
                [ -f "$HERE/${t%.mjs}.mjs" ] || {
                    echo "[dashboard-test] ERROR: no suite called ${t%.mjs}: the suites are $(cd "$HERE" && ls ./*.mjs | sed 's|^\./||; s|\.mjs$||' | grep -vxE 'lib|surface-list' | tr '\n' ' ')" >&2
                    exit 2; }
                tests+=("$HERE/${t%.mjs}.mjs") ;;
        esac
        names+=("$t")
    done
else
    mapfile -t names < <(default_suites)
    for t in "${names[@]}"; do tests+=("$HERE/$t.mjs"); done
fi
run_file() {
    # The suite's name, for the server's coverage counts to carry (R76):
    # the server is started fresh for every file, so its counts are that
    # file's and the map can say which suite reached a handler.
    BB_COVERAGE_SUITE="$(basename "${1%.mjs}")"
    export BB_COVERAGE_SUITE
    local t0 rc=0
    t0="$(date +%s)"
    fresh_world
    phase fresh
    log "== $(basename "$1")${2:+ $2} =="
    # A time limit per file (B514): a check that awaited a request it held
    # open itself hung cards.mjs for four hours, holding the run's lock, with
    # nothing saying so. SUITE_TIMEOUT seconds (1500: the longest file takes
    # about 230 on this node, doubled waits included many times over).
    DASHBOARD_TEST_URL="http://127.0.0.1:$PORT/" DASHBOARD_TEST_CHROME="$CHROME" \
    DASHBOARD_TEST_DIR="$S" timeout --kill-after=10 "${SUITE_TIMEOUT:-1500}" node "$1" || rc=$?
    [ "$rc" != 124 ] && [ "$rc" != 137 ] \
        || log "FAIL  $(basename "$1") ran out of its ${SUITE_TIMEOUT:-1500} s: something in it waited on nothing"
    # What the suite cost, world and all, for the next run's worker plan
    # (bucket_plan): a pass in a whole run only, since a failure can stop
    # early or wait out a timeout, and a rerun runs on an idle box. One
    # short line appended, so four workers at once do not tear it.
    [ "$rc" = 0 ] && [ -z "${2:-}" ] && [ -n "${SUITE_TIMES:-}" ] \
        && printf '%s\t%s\n' "$BB_COVERAGE_SUITE" "$(( $(date +%s) - t0 ))" >> "$SUITE_TIMES" 2>/dev/null
    return "$rc"
}
rc=0
failed=()
failed_names=()
for i in "${!tests[@]}"; do
    # A worker sent to run one suite again (BB_TEST_AGAIN) banners it as a
    # single run's rerun does, so the readers of the log know it for one.
    run_file "${tests[i]}" ${BB_TEST_AGAIN:+again} \
        || { failed+=("${tests[i]}"); failed_names+=("${names[i]}"); }
done
# A worker stops here: what failed goes to its parent by name, and the
# parent reruns those alone once every worker is done, so the reruns are
# one at a time on an otherwise idle box, as a single run's are.
if [ -n "${BB_TEST_WORKER:-}" ]; then
    stop_world
    [ -z "${BB_TEST_WORKER_OUT:-}" ] \
        || printf '%s\n' "${failed_names[@]}" | sed '/^$/d' > "$BB_TEST_WORKER_OUT"
    [ "${#failed[@]}" = 0 ] && exit 0 || exit 1
fi
# Once more, alone, for each file that failed, in a world of its own like
# every other. A file that passes then is FLAKY: it failed under the whole
# run's load and not on its own, and it is named as that, never folded into
# a pass. A file that fails again is a failure. Only in a run of more than
# one file: asking for one file and getting it twice would be noise.
flaky=()
if [ "${#tests[@]}" -gt 1 ]; then
    for t in "${failed[@]}"; do
        if run_file "$t" again; then flaky+=("$(basename "$t")"); else rc=1; fi
    done
elif [ "${#failed[@]}" -gt 0 ]; then
    rc=1
fi
stop_world
if [ "${#flaky[@]}" -gt 0 ]; then
    warn "flaky: ${flaky[*]} failed in the whole run and passed again alone"
fi
load_line
[ "$rc" = 0 ] && log "dashboard tests: all passed" || warn "dashboard tests: FAILURES above"
exit "$rc"
