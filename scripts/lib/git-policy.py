"""Behind `bb git policy` (cmd_git in bb): what this project lets a session do
with git's network half, read from the settings record on stdin, as `bb
settings --json` prints it.
"""
import json
import sys


rec = json.load(sys.stdin)
p = rec.get("gitpol") or {}
# Whether a push can happen at all, first (B734): a project with no rights,
# or an https remote with no credential on the controller, has bb git push
# refused, and that is the thing to know before the policy under it.
pu = rec.get("push") or {}
if "rights" in pu:
    print("push at all:    ", "no: this project was given no push rights; the operator grants them with Link to a git host on its Projects page"
          if not pu["rights"]
          else "no: its remote is https and the controller holds no credential for it; the operator links one on its Projects page"
          if pu.get("auth") == "none"
          else "no: it has no origin remote" if not pu.get("auth")
          else f"yes ({'the key its ssh address carries' if pu['auth'] == 'ssh' else 'the token the controller holds'})")
print("push its branch:", p.get("push", "allow"))
print("push to main:   ", p.get("main", "deny"))
print("Its branches are the ones this tree has, one at a time: a name that is only on the")
print("remote, a tag, --all, and deleting a branch there stay with the operator whatever")
print("these say.")
print("A local commit or merge is yours; what reaches the remote is what this governs.")
