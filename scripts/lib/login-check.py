"""Behind `bb login --check` (claude_login_check in bb): is this machine signed
in to Claude, and as whom, told to the controller, with the account's
generation coming back.

Two sentences in opposite directions and no secret in either: "I am signed
in as X" going up, and a GENERATION coming back. Behind means the account was
signed out while this machine was not listening, and the answer to that is
`claude auth logout` here. Never fatal, and quiet unless something will not
fix itself: bb runs this on every connection and every prompt.

Argument: `--loud` for the interactive verb, `--why` for the refusals worth
repeating (bb-keep-login), or nothing. BB_LOGIN_AUTH is the session's auth
header; HOME and BB_NODE are the machine's.
"""
import json
import os
import shutil
import subprocess
import sys

import bbapi


loud = sys.argv[1] == "--loud"
why = sys.argv[1] == "--why"
auth = os.environ["BB_LOGIN_AUTH"]
GEN = os.path.join(os.environ["HOME"], ".claude", ".bb-gen")
NODE = os.environ.get("BB_NODE", "this node")


def say(msg):
    print(f"[builderbot] {msg}")


def warn(msg):
    print(f"[builderbot] WARN: {msg}", file=sys.stderr)


def refused(msg):
    """A refusal the next prompt should hear about again, for bb-keep-login.
    Only what will still be true then: not a restart, not a blip."""
    if why or loud:
        print(f"SYNC-REFUSED {msg}", file=sys.stderr)


def claude(*args, timeout=30):
    try:
        return subprocess.run(["claude", *args], capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def whoami():
    """Signed in here, and as whom: read from the FILES, not by asking the
    CLI.

    This runs on every prompt (bb-keep-login), and `claude auth status` put a
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
    """The subscription, and the one fact no file carries in the form the card
    shows: `claude auth status` says "max" where .claude.json's oauthAccount
    says organizationType "claude_max", and those are not the same field: one
    is the subscription and one is the organization, which coincide for a
    personal account and need not for a seat.

    So it is still asked of the CLI, but only when the CONTROLLER has none,
    which is once after a sign-in: sign_out clears the stored plan, so the
    next sign-in learns it again and every prompt in between touches no
    credential. An empty plan never overwrites a stored one (claudegrant's
    `if plan:`), so a failure here loses nothing.
    """
    r = claude("auth", "status", "--json", timeout=20)
    if not r or r.returncode != 0:
        return ""
    try:
        return str(json.loads(r.stdout).get("subscriptionType") or "")[:40]
    except (ValueError, TypeError):
        return ""


def my_gen():
    try:
        with open(GEN) as f:
            return int(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0


def keep_gen(n):
    d = os.path.dirname(GEN)
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd = os.open(GEN + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(str(int(n)))
    os.replace(GEN + ".new", GEN)


here, mine = whoami()
r = bbapi.call("/api/v1/claude-login", auth=auth)
if r.get("error"):
    e = str(r["error"])
    if loud:
        warn(f"could not ask the controller about this account's login: {e}")
    if "Error" in e or "500" in e:
        refused(f"The controller could not answer about your Claude login "
                f"({e[:120]}). This machine cannot be told about a sign-out.")
    sys.exit(1 if not here else 0)

gen = int(r.get("gen") or 0)
# Signed out while this machine was not listening. The generation is the only
# thing that can carry that: being signed out has no date to compare.
if gen > my_gen():
    keep_gen(gen)
    if here and not r.get("email"):
        claude("auth", "logout", timeout=60)
        say(f"signed out on {NODE}: this account was signed out of Claude")
        sys.exit(0)

if not here:
    if loud:
        say(f"not signed in on {NODE}; the Doctor card's sign-in runs the flow here")
    # Tell the controller this machine is not one of the signed-in ones, so
    # the card stops naming it.
    bbapi.call("/api/v1/claude-login", {"signed_in": False}, auth=auth)
    sys.exit(1)

# Asked of the CLI only when the controller has no plan for this account;
# see plan_now(). Every other prompt sends "", which leaves the stored one be.
known = str(r.get("plan") or "")
plan = known or plan_now()
w = bbapi.call("/api/v1/claude-login",
               {"email": mine, "plan": "" if known else plan,
                "signed_in": True}, auth=auth)
if w.get("error"):
    # The one-account rule, and it is the whole reason this call exists.
    refused(w["error"])
    if loud:
        warn(w["error"])
    sys.exit(1)
if w.get("gen"):
    keep_gen(w["gen"])
if loud:
    say(f"signed in on {NODE} as {mine}" + (f" · {plan}" if plan else ""))
sys.exit(0)
