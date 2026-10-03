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
    # The suites, from the map. The harness's own lib.mjs and run.sh are
    # every suite, which every suite runs on. A changed SUITE is itself
    # and nothing more: what it names is what it asks of the page and the
    # server, which it cannot change, and the map added every suite naming
    # the same endpoint, 27 for one change to roles.mjs (B244). The rest
    # is measured by the covered run when there is one (bb map affected,
    # the operator, 29 Sep): the functions the changed lines fall in and
    # the suites that reached them, so a change to one handler in
    # server.py is that handler's suites and not, as it was, all 49 for
    # 25 minutes; a changed function no covered run has seen falls back
    # to the file's answer, and in server.py to every suite. Without a
    # covered run, the file's answer as before, server.py meaning all.
    local by="" mb_ref="${mb:-HEAD}"
    for f in "${files[@]}"; do
        case "$f" in
            scripts/dashboard/test/lib.mjs|scripts/dashboard/test/run.sh) all_dash=1 ;;
            scripts/dashboard/server.py) [ -f "${BB_REPO:-$PWD}/.bb-map/coverage.json" ] && mapped+=("$f") || all_dash=1 ;;
            scripts/dashboard/test/*.mjs) own+=("$(basename "$f" .mjs)") ;;
            # The unit tier runs every one of these first, whatever changed;
            # handed to the map, a changed one came back as a browser suite
            # the harness has no file for.
            scripts/dashboard/unit/*) ;;
            *) mapped+=("$f") ;;
        esac
    done
    if [ -n "$all_dash" ]; then
        suites=(ALL)
    else
        suites=("${own[@]}")
        if [ "${#mapped[@]}" -gt 0 ]; then
            if [ -f "${BB_REPO:-$PWD}/.bb-map/coverage.json" ]; then
                by=coverage
                while IFS= read -r f; do
                    [ -n "$f" ] && case " ${suites[*]:-} " in *" $f "*) ;; *) suites+=("$f") ;; esac
                done < <(cmd_map affected --base "$mb_ref" --names "${mapped[@]}")
                case " ${suites[*]} " in *" ALL "*) suites=(ALL) ;; esac
            else
                while IFS= read -r f; do
                    [ -n "$f" ] && case " ${suites[*]:-} " in *" $f "*) ;; *) suites+=("$f") ;; esac
                done < <(cmd_map suites "${mapped[@]}" --names)
            fi
        fi
    fi
    # ...and a suite that names a changed file outright, by its name in the
    # suite's own source: the map indexes code, so a file a suite reads
    # (config/toolchains.json, which toolchains.mjs holds bb's tool case
    # against) or a bb library it drives (scripts/lib/sdk.sh) placed no
    # suite, and a change to either went out on a gate that never ran the
    # one suite that checks it (B442: the audio recipe's B441).
    if [ "${suites[*]:-}" != ALL ]; then
        local named
        for f in "${files[@]}"; do
            case "$f" in scripts/dashboard/test/*|scripts/dashboard/unit/*) continue ;; esac
            while IFS= read -r named; do
                [ -n "$named" ] || continue
                named="$(basename "$named" .mjs)"
                case "$named" in lab-*|_*) continue ;; esac
                case " ${suites[*]:-} " in *" $named "*) ;; *) suites+=("$named") ;; esac
            done < <(grep -lF -- "$(basename "$f")" "${BB_REPO:-$PWD}"/scripts/dashboard/test/*.mjs 2>/dev/null || true)
        done
    fi
    # Only what the harness has a file for: the map counts a python unit
    # file (test_x.py) as a test, rightly for other projects, and named
    # unit/test_token_keep.py for a change to bbapi.py, which the harness
    # then failed as a suite it could not find (B420). The unit tier above
    # already runs every one of those.
    if [ "${suites[*]:-}" != ALL ] && [ "${#suites[@]}" -gt 0 ]; then
        local kept=() s
        for s in "${suites[@]}"; do
            [ -f "${BB_REPO:-$PWD}/scripts/dashboard/test/${s}.mjs" ] && kept+=("$s")
        done
        suites=("${kept[@]}")
    fi
    # The checks the house rules ask for before handing back.
    # design is uniform.mjs whole, about four minutes. It runs when a file
    # that carries style changed (the stylesheet lives in index.html, the
    # textures in static/, the language in docs/design-language.md, the
    # measures in uniform.mjs), since no function map sees a CSS rule. For
    # script and python, the covered run already says whether uniform reaches
    # the changed functions and puts it in the suites when it does: 16 of 20
    # commits paid the whole of uniform on top of one suite, 9 of them with
    # no style changed (30 Sep). Without a covered run, as before.
    checks=(lint voice)
    local cov_ok=""; [ -f "${BB_REPO:-$PWD}/.bb-map/coverage.json" ] && cov_ok=1
    for f in "${files[@]}"; do
        case "$f" in
            scripts/dashboard/index.html|scripts/dashboard/static/*|docs/design-language.md|scripts/dashboard/test/uniform.mjs)
                checks+=(design); break ;;
            scripts/dashboard/*) [ -n "$cov_ok" ] || { checks+=(design); break; } ;;
        esac
    done
    printf '  files:   %s\n' "${files[*]}"
    printf '  suites:  %s\n' "${suites[*]:-none}"
    printf '  checks:  %s\n' "${checks[*]}"
    # The account, when the covered run chose: which function and which
    # drawn thing named each suite, and what fell back to a file.
    [ -z "$by" ] || cmd_map affected --base "$mb_ref" "${mapped[@]}" | sed 's/^/  /'
    # Code the map could place with no suite is a hole in the map, not a
    # clean change (B280): named, and the verdict is not clean.
    # ...unless the unit tier runs it: a unit file that names the changed
    # file is one that loads or runs it (the provisioner's helper, a bb
    # library), and that tier runs first below. Said, so the plan shows what
    # stands in for a suite.
    local unplaced=() units="${BB_REPO:-$PWD}/scripts/dashboard/unit" by_unit
    if [ "${#suites[@]}" -eq 0 ]; then
        for f in "${files[@]}"; do
            case "$f" in
                *.md|*.txt|*.json|*.png) ;;
                scripts/dashboard/unit/*) ;;
                scripts/*|nodes/*)
                    by_unit="$(grep -lF -- "$(basename "$f")" "$units"/test_*.py 2>/dev/null | xargs -r -n1 basename | tr '\n' ' ' || true)"
                    if [ -n "$by_unit" ]; then printf '  unit:    %s is run by %s\n' "$f" "${by_unit% }"
                    else unplaced+=("$f"); fi ;;
            esac
        done
    fi
    [ "${#unplaced[@]}" -eq 0 ] || printf '  WARN: no suite reaches %s: the map could not place it, so this is not a clean verdict; bb map suites FILE says what it knows (B280)\n' "${unplaced[*]}"
    [ -z "$dry" ] || return 0
    # Not cmd_dashboard test, which execs the harness and would end this
    # verb before its checks: the harness is run as a child here.
    local rc=0 here="${BB_REPO:-$PWD}/scripts/dashboard/test/run.sh"
    # The unit tier first: seconds, and a failure there is a failure of the
    # rule itself, so it is said before any browser suite starts. A red unit
    # still lets the suites run, so one gate says everything that is wrong.
    local unit="${BB_REPO:-$PWD}/scripts/dashboard/unit"
    if [ -d "$unit" ]; then
        printf '== unit: python3 -m unittest (scripts/dashboard/unit)\n'
        if python3 -m unittest discover -s "$unit" -t "$unit" -q 2>&1; then
            printf '  PASS  unit (exit 0)\n'
        else
            printf '  FAIL  unit\n'; rc=1
        fi
    fi
    [ -x "$here" ] || here=/opt/builderbot/scripts/dashboard/test/run.sh
    # Kept whole in the same log bb tests run writes, so bb tests log prints
    # this run when it was the last: a flake named only in the terminal's
    # scroll was gone with the scroll (B328).
    local rl="${BB_REPO:-$PWD}/.bb-test-run.log"
    printf '[builderbot] preflight over %s, %s: %s\n' "$base" "$(date '+%d %b %H:%M')" "${suites[*]:-nothing}" > "$rl" 2>/dev/null || rl=/dev/null
    # As conditions, so set -e and pipefail read a failed suite as rc=1
    # rather than ending this verb before its checks.
    if [ "${suites[*]:-}" = ALL ]; then
        # A whole run is run with the counters in and merged after, so the
        # covered run the next preflight measures by is never older than
        # the last whole gate.
        if BB_COVERAGE=1 bash "$here" 2>&1 | tee -a "$rl"; then :; else rc=1; fi
        cmd_map coverage 2>&1 | head -1 | tee -a "$rl"
    elif [ "${#suites[@]}" -gt 0 ]; then
        if bash "$here" "${suites[@]}" 2>&1 | tee -a "$rl"; then :; else rc=1; fi
    fi
    [ "${#unplaced[@]}" -eq 0 ] || rc=1
    local c
    for c in "${checks[@]}"; do
        # design is uniform.mjs, already in the run when it is listed
        case "$c" in design) case " ${suites[*]:-} " in *" uniform "*|*" ALL "*) continue ;; esac ;; esac
        if bash "$0" rules check "$c" 2>&1 | tee -a "$rl"; then :; else rc=1; fi
    done
    [ "$rc" = 0 ] && log "preflight: clean" || warn "preflight: something above failed"
    return "$rc"
}
