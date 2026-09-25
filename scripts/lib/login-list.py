"""Behind `bb login --list` (cmd_login in bb): every account this machine is
signed in to Claude as, as JSON, changing nothing. The agent asks for it
and carries the answer up on its heartbeat (B104). Read from the files
rather than from `claude auth status`, for every account on the box at
once.

BB_USERS_DIR is the directory the accounts' homes are under.
"""
import json
import os
import re


def plugins_of(home):
    """The Claude Code plugins this account installed here: what `claude
    plugin list --json` prints, read from the same two files it reads, so a
    person's plugins can be seen on their Profile and in bb diag. Only the
    names, versions and scope: a plugin's settings can hold its own secrets,
    and nothing here reads them. None when the account never installed one."""
    try:
        got = json.load(open(os.path.join(home, ".claude", "plugins", "installed_plugins.json")))
    except (OSError, ValueError):
        return None
    try:
        on = json.load(open(os.path.join(home, ".claude", "settings.json"))).get("enabledPlugins") or {}
    except (OSError, ValueError, AttributeError):
        on = {}
    rows = []
    for pid, installs in list(((got or {}).get("plugins") or {}).items())[:64]:
        for i in (installs if isinstance(installs, list) else [])[:4]:
            if not isinstance(i, dict):
                continue
            scope = str(i.get("scope") or "")[:12]
            rows.append({"id": str(pid)[:120], "version": str(i.get("version") or "")[:40],
                         "scope": scope,
                         # Where a project-scoped one lives says which project;
                         # the rest of its path is this machine's business.
                         "project": os.path.basename(str(i.get("projectPath") or ""))[:80],
                         # Enabled is the account's own setting for a user-scoped
                         # one; a project's lives in that project and is unknown here.
                         "enabled": bool(on.get(pid, True)) if scope == "user" else None})
    return rows


# Every account's home on this machine. The owner has no bare directory here:
# on a node every account is prefixed and homed under users/ (common.sh's
# owner_uid says why), so the uid is simply the directory's name.
out = []
root = os.environ.get("BB_USERS_DIR") or ""
try:
    names = sorted(os.listdir(root))
except OSError:
    names = []
for name in names[:64]:
    if not re.fullmatch(r"u_[0-9a-f]{8}", name):
        continue
    home = os.path.join(root, name)
    email = ""
    try:
        d = json.load(open(os.path.join(home, ".claude.json")))
        email = str(((d.get("oauthAccount") or {}).get("emailAddress")) or "")[:120]
    except (OSError, ValueError, AttributeError, TypeError):
        email = ""
    # The credential is what makes it a login rather than a leftover name: a
    # signed-out home keeps .claude.json and loses this file, and reporting
    # the stale name would keep the card claiming a login that is gone.
    if email and not os.path.exists(os.path.join(home, ".claude", ".credentials.json")):
        email = ""
    out.append({"uid": name, "email": email, "plugins": plugins_of(home)})
print(json.dumps(out))
