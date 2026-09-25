"""Behind `bb git policy` (cmd_git in bb): what this project lets a session do
with git's network half, read from the settings record on stdin, as `bb
settings --json` prints it.
"""
import json
import sys


p = json.load(sys.stdin).get("gitpol") or {}
print("push its branch:", p.get("push", "allow"))
print("push to main:   ", p.get("main", "deny"))
print("Its branches are the ones this tree has, one at a time: a name that is only on the")
print("remote, a tag, --all, and deleting a branch there stay with the operator whatever")
print("these say.")
print("A local commit or merge is yours; what reaches the remote is what this governs.")
