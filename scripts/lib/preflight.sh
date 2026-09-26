#!/usr/bin/env bash
# bb tests preflight: the suites and checks a change touches, run before a
# push. Sourced by bb, which keeps the rest of the CLI; a file of its own
# under the rule growth (25 Sep), the first verb moved out of bb whole.
#
# Preflight (roadmap R75 step 3): the suites a change touches, picked by
# the code map from the files that changed, run before a push with the
# checks the house rules name. Never picked by hand again: the one
# suite skipped before a push this month was the one that would have
# caught it. The files: the branch against its base, plus the working
# tree; or --files given outright; --dry only prints the plan.

cmd_tests_preflight() {
    local dry="" base="" files=() f suites=() checks=() all_dash="" own=() mapped=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --dry) dry=1; shift ;;
            --base) base="$2"; shift 2 ;;
            --files) shift; while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do files+=("$1"); shift; done ;;
            *) die "bb tests preflight [--dry] [--base REF] [--files F...]" ;;
        esac
    done
    if [ "${#files[@]}" -eq 0 ]; then
        git rev-parse --git-dir >/dev/null 2>&1 || die "not in a git tree: bb tests preflight --files F... names the files instead"
        local defaulted=""
        if [ -z "$base" ]; then
            base="$(git rev-parse --verify -q origin/main >/dev/null 2>&1 && echo origin/main || echo main)"
            defaulted=1
        fi
        local mb; mb="$(git merge-base "$base" HEAD 2>/dev/null || echo "$base")"
        while IFS= read -r f; do [ -n "$f" ] && files+=("$f"); done < <(
            { git diff --name-only "$mb" HEAD; git status --porcelain -z | tr '\0' '\n' | sed -E 's/^.{3}//'; } | sort -u)
        # The base is the branch's by default, which on a long branch is
        # every file it ever touched and the whole suite every time
        # (B225): said here, with the narrower measure beside it, so
        # a session proving one change knows the flag exists.
        log "preflight: $(printf '%s' "${#files[@]}") file(s) changed since $base ($(git rev-parse --short "$mb"))$(
            [ -n "$defaulted" ] && [ "${#files[@]}" -gt 20 ] && printf '%s' "; --base HEAD measures the working tree alone, --base HEAD~1 the last commit with it")"
    fi
    [ "${#files[@]}" -gt 0 ] || { log "nothing changed: nothing to run"; return 0; }
    # The suites, from the map. Python under the dashboard reaches its
    # suites through the API paths it names; server.py names them all,
    # so a change there is the whole suite, said as such, and so do the
    # harness's own lib.mjs and run.sh, which every suite runs on.
    # A changed SUITE is itself and nothing more: what it names is what
    # it asks of the page and the server, which it cannot change, and
    # the map added every suite naming the same endpoint, 27 for one
    # change to roles.mjs (B244).
    for f in "${files[@]}"; do
        case "$f" in
            scripts/dashboard/server.py|scripts/dashboard/test/lib.mjs|scripts/dashboard/test/run.sh) all_dash=1 ;;
            scripts/dashboard/test/*.mjs) own+=("$(basename "$f" .mjs)") ;;
            *) mapped+=("$f") ;;
        esac
    done
    if [ -n "$all_dash" ]; then
        suites=(ALL)
    else
        suites=("${own[@]}")
        if [ "${#mapped[@]}" -gt 0 ]; then
            while IFS= read -r f; do
                [ -n "$f" ] && case " ${suites[*]:-} " in *" $f "*) ;; *) suites+=("$f") ;; esac
            done < <(cmd_map suites "${mapped[@]}" --names)
        fi
    fi
    # The checks the house rules ask for before handing back.
    checks=(lint voice)
    for f in "${files[@]}"; do
        case "$f" in scripts/dashboard/*) checks+=(design); break ;; esac
    done
    printf '  files:   %s\n' "${files[*]}"
    printf '  suites:  %s\n' "${suites[*]:-none}"
    printf '  checks:  %s\n' "${checks[*]}"
    # Code the map could place with no suite is a hole in the map, not a
    # clean change (B280): named, and the verdict is not clean.
    local unplaced=()
    if [ "${#suites[@]}" -eq 0 ]; then
        for f in "${files[@]}"; do
            case "$f" in
                *.md|*.txt|*.json|*.png) ;;
                scripts/*|nodes/*) unplaced+=("$f") ;;
            esac
        done
    fi
    [ "${#unplaced[@]}" -eq 0 ] || printf '  WARN: no suite reaches %s: the map could not place it, so this is not a clean verdict; bb map suites FILE says what it knows (B280)\n' "${unplaced[*]}"
    [ -z "$dry" ] || return 0
    # Not cmd_dashboard test, which execs the harness and would end this
    # verb before its checks: the harness is run as a child here.
    local rc=0 here="${BB_REPO:-$PWD}/scripts/dashboard/test/run.sh"
    [ -x "$here" ] || here=/opt/builderbot/scripts/dashboard/test/run.sh
    if [ "${suites[*]:-}" = ALL ]; then bash "$here" || rc=1
    elif [ "${#suites[@]}" -gt 0 ]; then bash "$here" "${suites[@]}" || rc=1; fi
    [ "${#unplaced[@]}" -eq 0 ] || rc=1
    local c
    for c in "${checks[@]}"; do
        # design is uniform.mjs, already in the run when it is listed
        case "$c" in design) case " ${suites[*]:-} " in *" uniform "*|*" ALL "*) continue ;; esac ;; esac
        bash "$0" rules check "$c" || rc=1
    done
    [ "$rc" = 0 ] && log "preflight: clean" || warn "preflight: something above failed"
    return "$rc"
}
