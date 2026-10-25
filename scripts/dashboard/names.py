"""What things are called, written once.

Three rules several modules and a shell script each spelled for themselves
until this file (R60): what a project may be called, what tmux will call a
session, and the name a project's Claude session runs under. No imports
from the rest of the dashboard but agents.py, which has none, so nodes.py
and the doctor's probes can use it standalone.
"""
import re

import agents

# A repo name, near enough: what a project directory may be called.
PROJECT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def tmux_name(s):
    """What tmux will actually call a session asked for under this name.

    tmux rewrites `.` and `:` in a session name to `_` (they are its target
    syntax) and says nothing. A project called `example.com` therefore runs
    as `claude-example_com`, and every place that derives the session name
    from the project name (here, bb-tty, the page) has to make the same
    substitution, or the kill / keys / macro paths look for a session that
    was never called that.
    """
    return re.sub(r"[.:]", "_", s)


def claude_session(project):
    """The tmux session a project's Claude conversation runs in, before the
    account prefix a node puts in front of it: the agent table's name for
    it (R95)."""
    return agents.session_name("claude", project)


def agent_session(agent_id, project, slot=1):
    """The tmux session an agent's conversation on a project runs in, in
    its slot (R143)."""
    return agents.session_name(agent_id, project, slot)


def agent_sessions(project):
    """Every live agent's session name on a project in every slot, Claude's
    first slot first: what a check that must see any agent's session there
    looks for (R95 step 16; R143)."""
    return tuple(agents.session_name(a.id, project, n)
                 for n in range(1, agents.MAX_SLOTS + 1) for a in agents.live())


def running_session(prefix, project, running, want=""):
    """The session a message for this account on this project goes to:
    the one the person picked (`want`, R143: one of several of their own
    sessions there) when it is theirs, on this project and running; else
    the first live agent's that is running (`running`, a set of full
    names), Claude's when several are, or Claude's name when none is, so
    a caller that says "not running" names the usual one."""
    names = [prefix + n for n in agent_sessions(project)]
    if want and want in running and want in names:
        return want
    return next((n for n in names if n in running), names[0])
