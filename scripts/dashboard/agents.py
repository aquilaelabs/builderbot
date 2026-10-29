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
from dataclasses import dataclass, field


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
    tool: str = ""          # its row's name in the Library and on the Installed page, "" when it has none yet
    latest_url: str = ""    # where the newest release is asked (an npm registry `latest`, or a plain version)
    pack: dict = field(default=None, compare=False, hash=False)  # a pack agent's adapter (R169 step 9), None for the shipped

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
    # Grok Build (R95 step 21): xAI's coding agent, checked against its user
    # guide on 25 Oct (xai-org/grok-build, Apache-2.0). Its hooks are
    # Claude's events (PreToolUse, UserPromptSubmit, Stop), its sign-in a
    # device code into ~/.grok/auth.json, its sessions under ~/.grok/sessions.
    Agent(id="grok", name="Grok", product="Grok Build", command="grok",
          provider="xAI", reported="grok", update_job="grok-update",
          login_job="grok-login", logout_job="grok-logout",
          briefing="system-prompt-file", guards="hooks", state="hooks",
          transcripts=".grok/sessions", tool="grok-build", live=True,
          latest_url="https://x.ai/cli/stable"),
    # Any model (R144 step 2): OpenCode, the open agent, pointed at a node's
    # model router (router.py) rather than signed in to anybody: its keys
    # are the router's, handed to a session at its start with the models
    # the router offers; its briefing an instructions file in its config,
    # its guards and its state a plugin of BuilderBot's (bb-tty writes it)
    # calling bb-agent-hook as the others' hooks do, its conversations
    # exported by that plugin at each turn's end. Checked against OpenCode
    # 1.x's docs on 28 Oct.
    Agent(id="open", name="Any model", product="OpenCode", command="opencode",
          provider="", reported="opencode", update_job="opencode-update",
          login_job="", logout_job="",
          briefing="instructions-file", guards="plugin", state="plugin",
          transcripts=".local/share/opencode", tool="opencode", live=True,
          latest_url="https://registry.npmjs.org/opencode-ai/latest"),
)

_BY_ID = {a.id: a for a in TABLE}

# The coding agents installed packs bring (R169 step 9): the server sets this
# to toolpacks.offered_agents, [(name, label, adapter)]; a standalone reader
# (bb-tty, the doctor) has none. Each is an ordinary row, live, installed and
# updated as its pack is, so it has no update or sign-in job of its own.
pack_source = lambda: ()    # noqa: E731
_packs = {"key": None, "rows": ()}


def _pack_rows():
    got = tuple(pack_source() or ())
    if got != _packs["key"]:
        rows = []
        for name, _label, a in got:
            if name in _BY_ID:
                continue
            rows.append(Agent(id=name, name=a.get("name") or name, product=a.get("product") or name, command=a.get("command") or name,
                              provider=a.get("provider") or "", reported=name, update_job="", login_job="", logout_job="",
                              briefing="instructions-file" if (a.get("briefing") or {}).get("how") == "env-file" else "system-prompt-file",
                              guards="hooks", state="hooks", transcripts=(a.get("transcripts") or {}).get("dir") or "",
                              live=True, tool=name, pack=a))
        _packs.update(key=got, rows=tuple(rows))
    return _packs["rows"]


def rows():
    """Every agent: the table's, then the ones installed packs bring."""
    return TABLE + _pack_rows()


def page_rows():
    """The pack agents as the page's table holds an agent (page-agents.js
    AGENTS), with the models Start offers and what holds its guards."""
    out = []
    for a in _pack_rows():
        evs = (a.pack.get("hooks") or {}).get("events") or {}
        lacks = [w for k, w in (("recall", "the house rules' recall after a summary"), ("asking", "the asking mark")) if k not in evs]
        out.append({"id": a.id, "name": a.name, "product": a.product, "command": a.command, "provider": a.provider, "live": True, "pack": True,
                    "models": list(a.pack.get("models") or []),
                    "guards": "the same guards through its own hooks, from its pack's adapter" + (f", but for {' and '.join(lacks)}, which it names no hook for" if lacks else "")})
    return out


# Each agent's own models and reasoning efforts, what Start's model and
# effort step offers for it (R95 step 9) and the only words bb-tty passes on
# (a table lookup, never a word from the URL): read off Codex CLI 0.163.0's
# `codex debug models` and Copilot CLI 1.0.102's `copilot help config` on
# 22 Oct. Claude's are the project dialog's (MODELS, EFFORTS) as before.
# page-agents.js and bb-tty carry the same lists, held to these by
# unit/test_agents.py.
MODELS = {
    "codex": ('gpt-6.1-sol', 'gpt-6-sol', 'gpt-6-astra', 'gpt-6-luna', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5'),
    "copilot": ('auto', 'claude-sonnet-5.5', 'claude-opus-5.5', 'claude-haiku-5.5', 'gpt-6.1-sol', 'gpt-6-sol', 'gpt-5.6-sol', 'gpt-5-mini', 'gemini-4-argon', 'gemini-3.8-flash', 'grok-4.7'),
}
EFFORTS = {
    "codex": ('low', 'medium', 'high', 'xhigh', 'max'),
    "copilot": ('low', 'medium', 'high', 'xhigh', 'max'),
}
# Any model's models are the router's (router.models_for), read per project
# rather than kept here; a pick is held to that list by prefs and bb-tty.
OPEN_MODEL = re.compile(r"^[A-Za-z0-9._:/-]{1,120}$")


def get(agent_id):
    """The adapter called this, or None."""
    k = str(agent_id or "")
    return _BY_ID.get(k) or next((a for a in _pack_rows() if a.id == k), None)


def live():
    """The agents a session may run today, Claude first."""
    return tuple(a for a in rows() if a.live)


def default():
    return TABLE[0]


# A second session of one agent on one project is a slot of its own (R143):
# `claude-alpha` is the first, as every session was named before, and
# `claude-alpha~2` the second. tmux keeps `~` as it is (names.tmux_name
# rewrites `.` and `:` alone), and no project's name carries one.
SLOT_SEP = "~"
_SLOT = re.compile(r"~([2-9])$")


def _split_slot(stem):
    m = _SLOT.search(stem)
    return (stem[:m.start()], int(m.group(1))) if m else (stem, 1)


def of_session(base):
    """(agent, stem) for a session name with its account prefix already off
    (`claude-alpha` -> (Claude, "alpha")), or (None, "") for a shell or
    anything else. Only a live agent's names are read as an agent's. The
    stem is the project's as tmux writes it, whichever slot the session is
    (`claude-alpha~2` -> (Claude, "alpha")): slot_of says which."""
    base = str(base or "")
    for a in live():
        if base.startswith(a.session) and len(base) > len(a.session):
            stem = _split_slot(base[len(a.session):])[0]
            return (a, stem) if stem else (None, "")
    return None, ""


def slot_of(base):
    """Which slot an agent's session name is (R143): 1 for `claude-alpha`,
    2 for `claude-alpha~2`; 0 for a name that is no agent's."""
    a, _stem = of_session(base)
    return _split_slot(str(base)[len(a.session):])[1] if a else 0


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


def slot_of_arg(arg):
    """The slot a terminal argument opens (R143): its `:s:N`, 1 when it
    names none, as every argument from before slots does."""
    a, rest = of_arg(arg)
    m = re.search(r":s:([0-9]{1,2})(?::|$)", rest) if a else None
    n = int(m.group(1)) if m else 1
    return n if 1 <= n <= MAX_SLOTS else 1


def project_of_arg(arg):
    """The project an agent's argument names, or ""."""
    a, rest = of_arg(arg)
    return rest.split(":")[0] if a else ""


# The most slots of one agent a person may have on one project, whatever a
# project's own cap says (R143): what the names can carry.
MAX_SLOTS = 9


def session_name(agent_id, project, slot=1):
    """The tmux session an agent's conversation on a project runs in,
    before the account prefix a node puts in front of it. tmux rewrites
    `.` and `:` to `_` (names.tmux_name). A slot past the first carries its
    number (R143)."""
    a = get(agent_id) or default()
    n = int(slot or 1) if str(slot or 1).isdigit() else 1
    return re.sub(r"[.:]", "_", a.session + str(project)) + (f"{SLOT_SEP}{n}" if 1 < n <= MAX_SLOTS else "")


def installable():
    """The agents the Library installs on a node, Claude first: every
    row with a toolchain row of its own, live or not yet, since an agent
    is installed before a session can start it. A pack's agent is not
    among them: it is installed and updated as its pack is."""
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


def by_tool(name):
    """The agent whose row in the Library is called this, or None."""
    return next((a for a in TABLE if a.tool and a.tool == str(name)), None)


def prefixes():
    """The live agents' session prefixes, for a reader that only needs to
    say whether a name is an agent's (the node agent, idle.py)."""
    return tuple(a.session for a in live())
