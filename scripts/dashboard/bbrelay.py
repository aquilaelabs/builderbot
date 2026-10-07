"""The bb relay: a bb verb from a session on a NODE, run here (roadmap #24).

The notebook, the settings, the registry and the version policy all live in
this container's /config, and a node keeps none of it. So a session over
there does not carry copies of the modules that read them: it sends the
words (`roadmap add "..."`, `bug show 3`, `version --file`) with its own
token, and this runs the same bb it would have run here, in the same tree
(the projects share is mounted at /workspace on both sides, which is what
makes `cwd` meaningful), and hands back what it printed. One implementation
of every verb.

WHAT THE TOKEN DECIDES. A session token stands for one project with user
rights; the relay refuses a request naming another, and every verb runs
with that project pinned into the environment, so `bb roadmap` cannot be
pointed elsewhere by a working directory. A person's credential (an
operator at a node's console) is held to the same rule the page holds them
to: a project on their list.

WHAT IT RUNS. Only the verbs bb itself relays (BB_RELAY_VERBS in
scripts/bb, read from the same file as VERBS below): the notebook, the
settings, the registry, the version and changelog, the findings. Not `sdk`,
`emu`, `run`, `build`: those answer for the machine the session is on, and
relaying them would make a node's session act on this container, which is
the very thing roadmap #24 exists to end. Not `users`, `dashboard`, `lint`:
nothing that administers this box. The audit row at the top of POST
records the argv with the principal, like every other mutation.

The server holds the door: a signed-in caller before admit(), and the
account's `bb` right on the project between admit() and run(). Which words
travel, whose project a token names and what a session may push are this
module's; both answer (payload, status).
"""
import os
import subprocess
import threading
from pathlib import Path

from fields import field

HERE = Path(__file__).resolve().parent

# The bb verbs a session on a node may run HERE through /api/v1/bb (roadmap
# #24): the ones whose state is this container's, git's network half among
# them (docs/nodes.md §20: the keys are here and the tree is the share). One
# list, in lib/relay-verbs, read by bb on the node and by this side, so a
# verb cannot be added to one and not the other.
VERBS = frozenset((HERE.parent / "lib" / "relay-verbs").read_text().split())

# How many relayed bb verbs run at once, across every session.
_SLOTS = threading.BoundedSemaphore(8)

# The server's, handed over by configure(): the account store, the
# projects' push rights and settings, git's network half, and where the
# projects and this controller's state are.
users = None
projects = None
prefs = None
gitrelay = None
WORKSPACE = None
STATE = None


def configure(**deps):
    globals().update(deps)


def _argv(req):
    return [str(a) for a in (req.get("argv") or []) if isinstance(a, (str, int))][:64]


# The relayed words a session may send about a project it READS: each verb
# with the forms of it that only look. Anything not listed is a write, or a
# verb that acts on the project's machines, and is refused by name.
READ_FORMS = {
    "roadmap": ("", "show", "history", "pending", "--json"),
    "bug": ("", "all", "show", "find", "history", "pending", "--json"),
    "rules": ("", "show", "history", "pending", "--json"),
    "tests": ("", "show", "drift", "flagged", "projection", "last", "log", "--json"),
    "history": None,                    # every form reads
    "version": ("", "policy", "--list", "--for", "--json", "--semver", "--code", "--quad",
                "--win", "--moz", "--msi", "--pep440", "--file"),
    "changelog": ("", "unreleased", "--for", "--json"),
    "findings": ("", "history", "--level", "--find", "--json"),
    "catchup": None,
    "preamble": None,
    "settings": ("", "--json"),
}


def _not_a_read(argv):
    """Why these words are not a read of a project, or "" when they are."""
    verb = argv[0] if argv else ""
    forms = READ_FORMS.get(verb, ())
    if forms is None:
        return ""
    first = argv[1] if len(argv) > 1 else ""
    if verb in READ_FORMS and first in forms:
        return ""
    if verb in READ_FORMS:
        return (f"bb {verb} {first} would change it, and a session on the project "
                f"that reads it only reads")
    return f"bb {verb} acts on the project's own machines, and reading it does not"


def admit(me, req):
    """(project, None) when the relay's own rules let this caller send these
    words for that project, and (None, (payload, status)) when they do not:
    a verb that is not relayed, a token naming another project, git with no
    author, a name that is not a project."""
    argv = _argv(req)
    if not argv or argv[0] not in VERBS:
        return None, ({"error": f"bb {argv[0] if argv else ''} is not relayed: "
                       "it answers for the machine the session is on"}, 400)
    # A rule's check is a command, and a session may write its own rule's
    # check, so it runs on the machine the session is on and never here
    # (B152). A node's bb keeps it local; this refuses one sent anyway.
    if argv[:2] == ["rules", "check"]:
        return None, ({"error": "bb rules check runs on the machine the session is on, "
                                "not on the controller: run it there"}, 400)
    # `bb findings --all` means every project in the scanner's report, and
    # the report covers the whole share. The rest of this door keeps a
    # session inside its own project; this flag walks straight out of it,
    # and the reports live on the CONTROLLER, so a node's session cannot
    # read them any other way and this is the only place to say no.
    # Measured from a session, not supposed: it listed file paths out of
    # three other projects' trees. Without the flag the same command
    # answers for its own project, which is what a session wants anyway.
    if me.get("session") and argv[:1] == ["findings"] \
            and any(a in ("-a", "--all") for a in argv[1:]):
        return None, ({"error": "bb findings --all reads every project in the report, "
                                "and a session reads its own: run it without --all"}, 403)
    project = field(req, "project") or me.get("session") or ""
    if me.get("session") and project != me["session"]:
        # A project this session's own reads (prefs.reads): the reading
        # words go through and every other refuses by name, here rather
        # than in each verb, because the relayed bb runs on the controller
        # with a token for the project it is asked about.
        if project in (me.get("reads") or []):
            why = _not_a_read(argv)
            if why:
                return None, ({"error": f"{project} is read-only from a session on "
                                        f"{me['session']}: {why}"}, 403)
        else:
            # Said by name (MediaReducer, 7 Oct): "this session's token is
            # for another project" sent a session guessing at spellings, and
            # read the same for a project that does not exist.
            if not project or not (WORKSPACE / project).is_dir():
                return None, ({"error": f"there is no project called {project}"}, 400)
            return None, ({"error": f"{me['session']} does not read {project}: its owner adds it "
                                    f"under Reads in {me['session']}'s settings, and a session "
                                    "started after that sees it"}, 403)
    # git's network half runs under the account's author like everything
    # else it does with a repository: none set, none run. Push, fetch and
    # pull write with git, and git wants an author; a policy read and an
    # ls-remote do not (B128). Asked WITH the project, so an author set for
    # one repository alone is enough even when the Profile has none, and
    # asked BEFORE the project is checked for being one, so a request that
    # names no project still hears the useful half rather than "not a
    # project": having no author is the answer either way.
    if argv and argv[0] == "git" and argv[1:2] not in (["policy"], ["ls-remote"]) \
            and users.uid_of(me) and not users.git_ready(me, project):
        return None, ({"error": "no name and email for commits yet: set them on your "
                                "Profile (the gear in the dashboard's header), or for "
                                "this project alone on its notebook's Settings"}, 403)
    if not project or (WORKSPACE / project).name != project \
            or not (WORKSPACE / project).is_dir():
        return None, ({"error": "not a project"}, 400)
    return project, None


def run(me, req, project):
    """Run the words for the project admit() named, once the server has
    asked the account's `bb` right on it: a git verb's own refusals first
    (no push rights, a session's push against the project's git policy),
    then git's network half through gitrelay or the verb through bb."""
    argv = _argv(req)
    # Push rights first, for everybody: a project cloned without them
    # does not push, whatever its tree says. The refusing pre-push hook
    # in a read-only clone is a file a session can change, so this is
    # the check that holds (B149), the same one the Git view makes.
    if argv[:1] == ["git"] and argv[1:2] and argv[1] in gitrelay.VERBS and gitrelay.bad_args(argv[2:]):
        return {"error": gitrelay.bad_args(argv[2:])}, 400
    if argv[:2] == ["git", "push"] and not projects.may_push(project):
        return {"error": "this project has no push rights: they are granted "
                         "in the clone dialog, once"}, 403
    # The tree the session is in: the project directory, or one of its
    # worktrees. Anything else (a path outside the share, a sibling
    # project) runs in the project directory instead of being trusted.
    cwd = WORKSPACE / project
    want = str(req.get("cwd") or "")
    if want.startswith("/"):
        real = Path(want).resolve()
        mine = (WORKSPACE / project).resolve()
        trees = (WORKSPACE / ".worktrees" / project).resolve()
        if real.is_dir() and (real == mine or mine in real.parents
                              or trees in real.parents):
            cwd = real
    # ...and under the project's git policy (the Git view, roadmap R36):
    # a session may push its own branch unless told not to, and may not
    # push to main unless told it may. Judged here because here is
    # where the push runs; a local commit or merge is not this door's.
    if argv and argv[0] == "git" and argv[1:2] == ["push"] and me.get("session"):
        pol = prefs.get(project)["gitpol"]
        if pol.get("push") == "deny":
            return {"error": "this project's git policy does not let a session "
                             "push; the operator pushes from the Git view"}, 403
        # Read out of the tree's files, never by running git in it (B148),
        # and out of the tree the push would RUN in, which is a worktree
        # as readily as the project directory.
        try:
            head, main, local = gitrelay.tree_refs(project, cwd)
        except gitrelay.Refused as e:
            return {"error": str(e)}, 400
        # Judged against what the push would WRITE, rather than against
        # whether the word `main` appears somewhere in the arguments
        # (B191). Under the old reading everything that was not spelled
        # `main` went through, so "its own branch" also bought a session
        # every other branch on that remote and the right to delete them.
        #
        # A branch THIS TREE HAS is the line, rather than the one branch
        # HEAD is on: a session pushes a branch it is not standing on
        # often enough (after a merge, from a worktree, tidying up) that
        # the stricter reading refuses ordinary work, and it buys little,
        # since a name that is only on the remote is the one a session has
        # no business writing.
        plan = gitrelay.push_plan(argv[2:], head)
        if plan["deletes"]:
            return {"error": "a session pushes work; it does not take work away. "
                             f"Removing {', '.join(plan['deletes'])} from the remote "
                             "is the operator's, from the Git view or the git host"}, 403
        if plan["every"] or plan["tags"]:
            # Named rather than described: --follow-tags sends the
            # annotated tags a push reaches, not every tag, and a refusal
            # that says otherwise is a refusal somebody has to check.
            flag = next((f for f in ("--all", "--tags", "--follow-tags") if f in argv[2:]), "that")
            what = ("writes every branch at once" if plan["every"]
                    else "sends tags, and a tag is a release's name here")
            return {"error": f"{flag} {what}; a session pushes the branches it has, "
                             f"one at a time. Name {head} instead"}, 403
        for dest in plan["dests"]:
            if dest == main:
                if pol.get("main") != "allow":
                    return {"error": f"this project's git policy does not let a session "
                                     f"push to {main}; push your branch and say so, "
                                     "and the operator merges from the Git view"}, 403
            elif dest not in local:
                return {"error": f"this project's git policy lets a session push its own "
                                 f"branches, and there is no {dest} in this tree: that "
                                 "name is on the remote or nowhere, and either way it is "
                                 f"not this session's to write. Push {head} and say what "
                                 "you want done with it"}, 403
    env = {k: v for k, v in os.environ.items() if k != "DASHBOARD_AUTH"}
    env.update({"BB_PROJECT": project, "BB_ROADMAP_PROJECT": project,
                "BB_BUG_PROJECT": project, "BB_VERSION_PROJECT": project,
                "DASHBOARD_STATE": str(STATE), "WORKSPACE": str(WORKSPACE),
                "BB_TOKEN": users.mint_session(project), "BB_RELAYED": "1",
                "BUILDERBOT_ROLE": "controller"})
    # Which seat the caller sits in, so a node's session is the same one
    # here: it is what says whether the roadmap has moved since that
    # session last read it, and whether a change was its own (#26, #27).
    # Only for a session token: a person at a node's console writes as a
    # person, and a person's writes are news to every session.
    if me.get("session") and me.get("uid"):
        env["BB_ACCOUNT_UID"] = me["uid"]
    else:
        env.pop("BB_ACCOUNT_UID", None)
    if field(req, "from") == "session":
        env["CLAUDECODE"] = "1"
    else:
        env.pop("CLAUDECODE", None)
    # git's network half never runs in the tree a session can write
    # (B148): the controller does it in a repository of its own and
    # hands the tree's half back to the node's bb as `apply`.
    if argv[0] == "git" and argv[1:2] and argv[1] in gitrelay.VERBS:
        r = gitrelay.run(project, str(cwd), argv[1], argv[2:])
        if "error" in r:
            return r, 400
        return {"code": r["code"], "out": r["out"][-200000:], "err": r["err"][-20000:],
                **({"apply": r["apply"]} if r.get("apply") else {})}, 200
    # A few at a time: every relayed verb is a process of its own here, and
    # six sessions and two people writing at once was 129 of them started
    # together, each slowing the rest (68s for what took 8). The rest wait
    # their turn in this thread; a wait that long says the box is busy.
    if not _SLOTS.acquire(timeout=120):
        return {"error": "the controller is busy with other sessions' bb; try again",
                "code": 75, "out": "", "err": ""}, 503
    try:
        r = subprocess.run(["bash", str(HERE.parent / "bb"), *argv], cwd=str(cwd),
                           env=env, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return {"error": f"bb {argv[0]} took longer than three minutes",
                "code": 124, "out": "", "err": ""}, 504
    except OSError as e:
        return {"error": str(e), "code": 1, "out": "", "err": ""}, 500
    finally:
        _SLOTS.release()
    return {"code": r.returncode, "out": r.stdout[-200000:],
            "err": r.stderr[-20000:]}, 200
