"""Behind `bb login --check` (claude_login_check in bb): is this account
signed in to Claude on this machine, and as whom, told to the controller.

One sentence, going up, and no secret in it: "signed in here as X", or "not
signed in here". The login itself stays on this machine, which signed in
for itself and is the one that signs out. Never fatal, and quiet: bb-tty
runs this on every connection.

The other coding agents' sign-ins go up beside Claude's, read by the same
readers `bb login --list` uses (R95 step 3): the heartbeat carries them too,
but a sign-in made in a job or a terminal is said at once, as Claude's is.

Arguments: `--loud` for the interactive verb, or nothing; then the agent
whose flow just ran (claude, the default, codex or copilot), which is the
one the loud lines are about. BB_LOGIN_AUTH is
the session's auth header; HOME and BB_NODE are the machine's, and BB_NODE_ID its id as bb-tty
was told it.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

import bbapi


loud = len(sys.argv) > 1 and sys.argv[1] == "--loud"
FOR = sys.argv[2] if len(sys.argv) > 2 else "claude"
auth = os.environ["BB_LOGIN_AUTH"]
NODE = os.environ.get("BB_NODE", "this node")
# Which machine this is, by id: a project may work on several nodes, and the
# controller believes the one named only when it is one of the project's.
NODE_ID = os.environ.get("BB_NODE_ID", "")


def say(msg):
    print(f"[builderbot] {msg}")


def warn(msg):
    print(f"[builderbot] WARN: {msg}", file=sys.stderr)


def claude(*args, timeout=30):
    try:
        return subprocess.run(["claude", *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def whoami():
    """Signed in here, and as whom: read from the FILES, not by asking the
    CLI.

    This runs on every connection, and `claude auth status` put a
    THIRD process on the one ~/.claude/.credentials.json an account has.
    Claude Code locks that file to refresh it, because a refresh rotates the
    refresh token; two sessions of one account already contend, and the loser
    is told "another Claude Code process is refreshing it" and its turn fails
    (B112). `bb login --list` has read these same facts out of the files since
    it was written, for exactly this reason, and this is that reader.

    The rule is --list's: .claude.json carries oauthAccount.emailAddress, and
    .credentials.json existing is what makes it a login rather than a leftover
    name. A sign-out keeps the first and removes the second, which is how
    `claude auth logout` here is still noticed. What this CANNOT see is a
    credential the server has since refused, because no file records that; it
    surfaces the moment a session runs, and is a rarer thing than the failed
    turns asking cost.
    """
    # Claude Code being HERE is part of the question, and reading files
    # rather than running it does not answer that by itself: a home kept
    # after an uninstall would otherwise report a login this machine cannot use.
    if not shutil.which("claude"):
        return False, ""
    home = os.environ.get("HOME") or ""
    if not os.path.exists(os.path.join(home, ".claude", ".credentials.json")):
        return False, ""
    try:
        with open(os.path.join(home, ".claude.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return False, ""
    email = str(((d.get("oauthAccount") or {}).get("emailAddress")) or "")[:120]
    return bool(email), email


def plan_now():
    """The subscription, and the one fact no file carries in the form the row
    shows: `claude auth status` says "max" where .claude.json's oauthAccount
    says organizationType "claude_max", and those are not the same field: one
    is the subscription and one is the organization, which coincide for a
    personal account and need not for a seat.

    So it is still asked of the CLI, but only when the CONTROLLER has none
    for this machine, which is once after a sign-in: every prompt in between
    touches no credential. An empty plan never overwrites a stored one
    (claudegrant.report), so a failure here loses nothing.
    """
    r = claude("auth", "status", "--json", timeout=20)
    if not r or r.returncode != 0:
        return ""
    try:
        return str(json.loads(r.stdout).get("subscriptionType") or "")[:40]
    except (ValueError, TypeError):
        return ""


def others():
    """Codex's and Copilot's sign-ins here, each said to the controller,
    signed in or not. login-list.py holds the one reading of their files."""
    spec = importlib.util.spec_from_file_location(
        "login_list", os.path.join(os.path.dirname(os.path.abspath(__file__)), "login-list.py"))
    ll = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ll)
    home = os.environ.get("HOME") or ""
    for agent, read in (("codex", ll.codex_of), ("copilot", ll.copilot_of)):
        got = read(home) if home else None
        if got:
            w = bbapi.call("/api/v1/claude-login", {"agent": agent, "email": got["email"], "plan": got["plan"],
                                                    "signed_in": True, "node": NODE_ID}, auth=auth)
        else:
            w = bbapi.call("/api/v1/claude-login", {"agent": agent, "signed_in": False, "node": NODE_ID}, auth=auth)
        if loud and agent == FOR:
            if w.get("error"):
                warn(f"could not tell the controller about this machine's {agent} login: {w['error']}")
            elif got:
                say(f"{agent} signed in on {NODE} as {got['email']}" + (f" · {got['plan']}" if got["plan"] else ""))
            else:
                say(f"{agent} is not signed in on {NODE}")


others()
if FOR != "claude":
    loud = False
here, mine = whoami()
if not here:
    if loud:
        say(f"not signed in on {NODE}: Sign in under Claude on its Agents page runs the flow here")
    # Tell the controller this machine is not one of the signed-in ones, so
    # its row stops naming it.
    bbapi.call("/api/v1/claude-login", {"signed_in": False, "node": NODE_ID}, auth=auth)
    sys.exit(1)

w = bbapi.call("/api/v1/claude-login",
               {"email": mine, "plan": "", "signed_in": True, "node": NODE_ID}, auth=auth)
if w.get("error"):
    e = str(w["error"])
    if loud:
        warn(f"could not tell the controller about this machine's Claude login: {e}")
    sys.exit(0)
# Asked of the CLI only when the controller has no plan for this machine;
# see plan_now().
plan = str(w.get("plan") or "")
if not plan:
    plan = plan_now()
    if plan:
        bbapi.call("/api/v1/claude-login",
                   {"email": mine, "plan": plan, "signed_in": True, "node": NODE_ID}, auth=auth)
if loud:
    say(f"signed in on {NODE} as {mine}" + (f" · {plan}" if plan else ""))
sys.exit(0)
