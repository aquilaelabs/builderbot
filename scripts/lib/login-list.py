"""Behind `bb login --list` (cmd_login in bb): every account this machine is
signed in to Claude as, as JSON, changing nothing. The agent asks for it
and carries the answer up on its heartbeat (B104). Read from the files
rather than from `claude auth status`, for every account on the box at
once.

BB_USERS_DIR is the directory the accounts' homes are under.

Each row carries the other coding agents' sign-ins too (R95 step 3), under
`agents`: Codex CLI's from its auth.json (the account the id token names,
never the token), Copilot CLI's from its config (the GitHub login it last
signed in as). `--forget-copilot HOME` is Copilot's sign-out, which its
1.0.102 has no command for outside a session.
"""
import base64
import json
import os
import re
import sys


def _claims(jwt):
    """The claims of a JSON web token, read and never checked: what it says
    about whose it is, for a row to name. {} when it is not one."""
    try:
        part = str(jwt).split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))) or {}
    except (IndexError, ValueError, TypeError):
        return {}


def codex_of(home):
    """Who this account's Codex CLI is signed in as here, {email, plan}, or
    None. $CODEX_HOME is ~/.codex for a session (bb-tty sets none)."""
    try:
        with open(os.path.join(home, ".codex", "auth.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    toks = d.get("tokens") if isinstance(d.get("tokens"), dict) else {}
    idt = toks.get("id_token")
    claims = idt if isinstance(idt, dict) else _claims(idt) if idt else {}
    email = str(claims.get("email") or "")[:120]
    if email:
        auth = claims.get("https://api.openai.com/auth") if isinstance(claims.get("https://api.openai.com/auth"), dict) else {}
        return {"email": email, "plan": str(auth.get("chatgpt_plan_type") or "")[:40]}
    if d.get("OPENAI_API_KEY"):
        return {"email": "an OpenAI API key", "plan": "API"}
    return None


def _copilot_config(home):
    return os.path.join(home, ".copilot", "config.json")


def copilot_of(home):
    """Who this account's Copilot CLI is signed in as here, {email: the
    GitHub login, plan}, or None."""
    try:
        with open(_copilot_config(home)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    u = d.get("lastLoggedInUser") if isinstance(d, dict) else None
    login = str((u or {}).get("login") or "")[:120] if isinstance(u, dict) else ""
    return {"email": login, "plan": ""} if login else None


def forget_copilot(home):
    """Copilot's sign-out: the logins its config remembers, and a token it
    kept there in plain text, taken out; everything else left as it was."""
    p = _copilot_config(home)
    try:
        with open(p) as f:
            d = json.load(f)
    except FileNotFoundError:
        return 0
    except (OSError, ValueError):
        return 1
    if not isinstance(d, dict):
        return 1
    for k in [k for k in d if k in ("lastLoggedInUser", "loggedInUsers") or "token" in k.lower()]:
        d.pop(k, None)
    tmp = p + ".new"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)
    return 0


if len(sys.argv) == 3 and sys.argv[1] == "--forget-copilot":
    sys.exit(forget_copilot(sys.argv[2]))


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
    agents = {k: v for k, v in (("codex", codex_of(home)), ("copilot", copilot_of(home))) if v}
    out.append({"uid": name, "email": email, "plugins": plugins_of(home), "agents": agents})
print(json.dumps(out))
