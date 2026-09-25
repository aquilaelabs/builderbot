"""Behind `bb build` and `bb test` (cmd_build_or_test in bb): the project's
settings record on stdin, as `bb settings --json` prints it, and the one
command they name printed as lines bb reads back: the command, whether it is
set, where the tests run, then each output glob.

BB_ROLE_ is build or test.
"""
import json
import os
import sys


try:
    rec = json.load(sys.stdin)
except ValueError:
    rec = {}
# Three things, in order: the command, where the tests run (node, up or
# only), then the output globs. What the settings say and nothing else: a
# command nobody typed must not run as if somebody had.
role = os.environ["BB_ROLE_"]
cmd = rec.get(role) or ""
print(cmd)
print("set" if cmd else "none")
print(rec.get("tests_in") or "node")
for g in rec.get("outputs") or []:
    print(g)
