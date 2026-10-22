"""The coding agents a session may run, as one table (R95).

A session used to be Claude's by construction: bb-tty's `claude:` argument,
the `claude-` session name, the `claude` census key, the claude-login job,
the ~/.claude/projects transcripts. Each of those is a fact about one agent,
and this table is where each agent's facts are written, so a place that
used to say claude asks here which agent a name or an argument is, and
what that agent's command, job, sign-in or transcript folder is called.

Each row is an adapter: how the agent installs and reports its version
(`command`, `reported`, `version`, `update_job`), signs in and out
(`provider`, `login_job`, `logout_job`), is launched (`arg`, `session`),
takes the briefing (`briefing`), is guarded (`guards`), reports its state
(`state`) and keeps its transcripts (`transcripts`). A row with `live`
False is planned and not wired: nothing parses a session name or an
argument as one of its, and no Start offers it, so the table can carry
the agents a later step wires without anything behaving differently now.

No imports from the rest of the dashboard, like names.py, so bb-tty, the
node's bundle and the doctor can read it standalone. The page's copy is
page-agents.js, held to this one by unit/test_agents.py; the node agent's
prefixes (builderbot_agent/sessions.py AGENT_PREFIXES) by the same test.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Agent:
    id: str                 # the table's key, and the stem of its names
    name: str               # what a person reads: on Start, the dock, a section
    product: str            # the program, as its makers call it
    command: str            # the binary a session runs, on the session account's PATH
    provider: str           # whose account signs it in, "" when it has none of its own
    reported: str           # the census key a node reports its version under
    update_job: str         # the node job that installs, updates or removes it
    login_job: str          # the node job that signs an account in, "" for none
    logout_job: str         # ...and out
    briefing: str           # how it is handed the briefing (BRIEFING below)
    guards: str             # what holds its guards (GUARDS below)
    state: str              # where working, waiting and asking are read from
    transcripts: str        # its conversations, under the account's home
    live: bool = False      # wired end to end: parsed, offered, started
    tool: str = ""          # its row on a node's Toolchains page, "" when it has none yet
    latest_url: str = ""    # where the newest release is asked (an npm registry `latest`)

    @property
    def arg(self):
        """bb-tty's argument prefix: `claude:PROJECT`."""
        return self.id + ":"

    @property
    def session(self):
        """The tmux session prefix, before the account's: `claude-PROJECT`."""
        return self.id + "-"


# What each was checked against when R95 began (22 Oct): Codex CLI 0.163.0,
# Copilot CLI 1.0.102 and OpenCode 1.19.4, their help and docs read. Codex
# and Copilot both carry hooks now (Codex's SessionStart, PreToolUse,
# PermissionRequest, UserPromptSubmit and Stop; Copilot's sessionStart,
# preToolUse, permissionRequest, userPromptSubmitted and agentStop), so
# their guards and their state are hooks as Claude's are; OpenCode's are a
# plugin's.
#
# How each takes the briefing: a system prompt file on its command line
# (Claude's --append-system-prompt-file), or an instructions file in the
# session's view that the agent reads the way it reads a project's own.
BRIEFING = {"system-prompt-file", "instructions-file"}
# What holds the guards: the agent's own hooks (Claude's seven), or its
# approval policy and sandbox with the bb-session view and the bb wrapper
# holding what it has no hook for.
GUARDS = {"hooks", "plugin", "approval"}
STATES = {"hooks", "plugin", "session-log"}

TABLE = (
    Agent(id="claude", name="Claude", product="Claude Code", command="claude",
          provider="Anthropic", reported="claude", update_job="claude-update",
          login_job="claude-login", logout_job="claude-logout",
          briefing="system-prompt-file", guards="hooks", state="hooks",
          transcripts=".claude/projects", live=True, tool="claude-code"),
    Agent(id="codex", name="ChatGPT", product="Codex CLI", command="codex",
          provider="OpenAI", reported="codex", update_job="codex-update",
          login_job="codex-login", logout_job="codex-logout",
          briefing="instructions-file", guards="hooks", state="hooks",
          transcripts=".codex/sessions", tool="codex-cli", live=True,
          latest_url="https://registry.npmjs.org/@openai/codex/latest"),
    Agent(id="copilot", name="Copilot", product="Copilot CLI", command="copilot",
          provider="GitHub", reported="copilot", update_job="copilot-update",
          login_job="copilot-login", logout_job="copilot-logout",
          briefing="instructions-file", guards="hooks", state="hooks",
          transcripts=".copilot/session-state", tool="copilot-cli", live=True,
          latest_url="https://registry.npmjs.org/@github/copilot/latest"),
    Agent(id="open", name="Any model", product="OpenCode", command="opencode",
          provider="", reported="opencode", update_job="opencode-update",
          login_job="", logout_job="",
          briefing="instructions-file", guards="plugin", state="plugin",
          transcripts=".local/share/opencode",
          latest_url="https://registry.npmjs.org/opencode-ai/latest"),
)

_BY_ID = {a.id: a for a in TABLE}


def get(agent_id):
    """The adapter called this, or None."""
    return _BY_ID.get(str(agent_id or ""))


def live():
    """The agents a session may run today, Claude first."""
    return tuple(a for a in TABLE if a.live)


def default():
    return TABLE[0]


def of_session(base):
    """(agent, stem) for a session name with its account prefix already off
    (`claude-alpha` -> (Claude, "alpha")), or (None, "") for a shell or
    anything else. Only a live agent's names are read as an agent's."""
    base = str(base or "")
    for a in live():
        if base.startswith(a.session) and len(base) > len(a.session):
            return a, base[len(a.session):]
    return None, ""


def is_session(base):
    """True when a session name (account prefix off) is an agent's."""
    return of_session(base)[0] is not None


def of_arg(arg):
    """(agent, rest) for a terminal argument (`claude:alpha:r:UUID` ->
    (Claude, "alpha:r:UUID")), or (None, "") for any other."""
    arg = str(arg or "")
    for a in live():
        if arg.startswith(a.arg):
            return a, arg[len(a.arg):]
    return None, ""


def project_of_arg(arg):
    """The project an agent's argument names, or ""."""
    a, rest = of_arg(arg)
    return rest.split(":")[0] if a else ""


def session_name(agent_id, project):
    """The tmux session an agent's conversation on a project runs in,
    before the account prefix a node puts in front of it. tmux rewrites
    `.` and `:` to `_` (names.tmux_name)."""
    a = get(agent_id) or default()
    return re.sub(r"[.:]", "_", a.session + str(project))


def installable():
    """The agents a node's Toolchains page installs, Claude first: every
    row with a toolchain row of its own, live or not yet, since an agent
    is installed before a session can start it."""
    return tuple(a for a in TABLE if a.tool)


def asked_by():
    """The agent whose session is asking, from BB_AGENT, which bb-tty's
    launcher sets for every agent and the relay carries from a node: its
    id, or "" when it is none of the table's. For what a record names as
    its asker, never for whether it may: every gate holds for every agent's
    session alike."""
    import os
    a = get(os.environ.get("BB_AGENT", ""))
    return a.id if a else ""


def asker(by):
    """{"agent": id} for a record made by a session ("claude", the stored
    word for any session's), {} otherwise: added beside `by`, which keeps
    its stored values."""
    a = asked_by() if by == "claude" else ""
    return {"agent": a} if a else {}


def prefixes():
    """The live agents' session prefixes, for a reader that only needs to
    say whether a name is an agent's (the node agent, idle.py)."""
    return tuple(a.session for a in live())
