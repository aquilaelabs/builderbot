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


def agent_session(agent_id, project):
    """The tmux session an agent's conversation on a project runs in."""
    return agents.session_name(agent_id, project)
