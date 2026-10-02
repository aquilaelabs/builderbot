"""Behind `bb rules check` (cmd_rules in bb): each rule's check command, run
HERE in this tree on whichever machine the session is on (roadmap R31).
The rules themselves arrive in RULES_JSON, from `bb rules --json`, which
a node relays; this needs neither /config nor rules.py, only git, the
tree and the command.

Arguments: the project's tree, then a rule's name, --all, or nothing for
the rules whose paths this tree has changed under.
"""
import fnmatch
import json
import os
import subprocess
import sys

tree, argv = sys.argv[1], sys.argv[2:]
rules = json.loads(os.environ.get("RULES_JSON") or "[]")
want = argv[0] if argv and argv[0] != "--all" else None
everything = "--all" in argv or want is not None


def changed():
    """What this tree has changed: the diff against HEAD plus untracked files."""
    out = set()
    for cmd in (["git", "diff", "--name-only", "HEAD"],
                ["git", "ls-files", "--others", "--exclude-standard"]):
        try:
            r = subprocess.run(cmd, cwd=tree, capture_output=True, text=True, timeout=30)
            out |= {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
        except (OSError, subprocess.SubprocessError):
            pass
    return sorted(out)


def covers(r, path):
    for pat in r.get("paths") or []:
        pat = pat.strip().rstrip("/")
        if pat and (fnmatch.fnmatch(path, pat) or path == pat or path.startswith(pat + "/")):
            return True
    return False


due = [r for r in rules if r.get("check") and (want is None or r.get("name") == want)]
if want is not None and not due:
    sys.exit(f"[builderbot] ERROR: no rule called {want} carries a check")
if not everything:
    files = changed()
    due = [r for r in due if not r.get("paths") or any(covers(r, f) for f in files)]
    if not due:
        print("nothing changed here that a rule's check covers")
        sys.exit(0)
rc = 0
for r in due:
    print(f"== {r['name']}: {r['check']}")
    sys.stdout.flush()
    try:
        # A rule's check is a shell line its author wrote, run in the session's
        # own tree as the session: a shell is what it asks for.
        res = subprocess.run(r["check"], shell=True, cwd=tree, timeout=3600)  # nosemgrep: python.lang.security.audit.subprocess-shell-true.subprocess-shell-true
        code = res.returncode
    except subprocess.TimeoutExpired:
        print("  timed out after an hour"); code = 124
    except OSError as e:
        print(f"  could not run: {e}"); code = 126
    print(f"  {'PASS' if code == 0 else 'FAIL'}  {r['name']} (exit {code})")
    rc = rc or code
sys.exit(rc)
