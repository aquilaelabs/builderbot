#!/usr/bin/env python3
"""Which model and effort a project's Claude session runs on.

Per project, set at the bottom of that project's settings dialog. It began as
a pair of pickers inside every send box, became one standing preference on a
sidebar card, and is now per project, because the thing it governs is per
project. Each directory has one long-lived conversation, and which model suits
a Kotlin app is not which model suits a shell script.

**It is applied at launch, not typed into a running session.** bb-tty passes
`--model` and `--effort` when it starts claude. That matters for two reasons
the slash-command route could not manage:

  - `/model` now raises a confirmation, and there is no IPC into a session
    (only tmux send-keys), so the dashboard was typing the next line into a
    dialog. notify.py predicted exactly this: it refuses to recognize dialogs,
    because that means pattern-matching a TUI that changes every release.
  - a slash-command switch is saved as claude's default for NEW sessions too,
    so a per-send switch quietly changed global state. A launch flag is the
    process's own and leaks nowhere.

Empty means what "leave as is" meant: pass no flag, and claude uses its own
default. Changing it for a project with a session already running is the one
case that cannot wait for a launch, so the dialog says so and the session is
respawned onto the same transcript.
"""
import json
import re
import threading
from pathlib import Path

write_json = None
FILE = None
# The canonical tables. roadmap.py and bugs.py carry copies for their own
# switching; a value stored here must satisfy theirs, so keep them equal.
MODELS = ("opus", "sonnet", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# How much the operator wants to be in the loop on what a session ENTERS
# into each notebook tab (roadmap #27): auto lands it, ask holds it for
# approval, deny refuses it. Creation only; see pending.py. Kept here
# because it is a project setting, edited in the same dialog as the rest.
GATE_KINDS = ("roadmap", "bugs", "rules", "settings", "design", "wiki")
# The git policy's two questions, and what they read as when nothing is set:
# a session may push the branch it works on, and may not push to main.
GITPOL_KEYS = ("push", "main")
GITPOL_MODES = ("allow", "deny")
GITPOL_DEFAULT = {"push": "allow", "main": "deny"}
GATE_MODES = ("auto", "ask", "deny")
# The modes a gate takes beyond those three, by kind: the wiki may also be
# hidden, which keeps it from a session altogether, reading included
# (wiki.py; the operator, 2 Oct).
GATE_EXTRA = {"wiki": ("hidden",)}


def gate_ok(kind, mode):
    return mode in GATE_MODES or mode in GATE_EXTRA.get(kind, ())
# ...and the same three words for whether a SESSION may rebuild this
# project's dev instance. One vocabulary: a person who has set a notebook
# tab to "ask me" knows what this one does without being told twice.
DEVBUILD_MODES = ("deny", "ask", "auto")
# Claude may: Sign a release (R106). Ask by default: a signed build is
# something that leaves, and a person reads which build and which key.
SIGN_MODES = ("deny", "ask", "auto")
# Where `bb test` runs a project's tests (roadmap R48, B241): on the node and
# never in its dev instance, which is the default; inside the instance when
# it is up and on the node otherwise; or inside it and nowhere else.
TESTS_IN = ("node", "up", "only")
# What a change asked for during a test run does (Claude settings): waits
# for the run, or ends it, lands, and the run starts again. Two house rules
# used to disagree about this per project; it is a setting now (25 Sep).
TEST_CHANGE = ("wait", "restart")
# Whether this project's sessions, builds and tests may compute on their
# node's NVIDIA card (R102): on unless somebody said otherwise, since an
# unused card costs nothing; off runs them as if the machine had none.
GPU = ("on", "off")
# Whether this project's sessions report BuilderBot's own problems with
# `bb report` (reports.py): on everywhere by default, and off where the
# project IS BuilderBot, whose sessions file those in its own tracker (the
# operator, 24 Sep). Two of the gates' words, since there is nothing to ask.
REPORT_MODES = ("auto", "deny")
# A color for the project, worn by its notebook tab and its row so that
# eight open notebooks can be told apart at a glance. Names, not hex: the
# page maps each to a tone that sits on its palette, and a name survives a
# theme change where a hex value picked against one background does not.
# "" is no color, which is the default and leaves nothing on the file.
COLORS = ("red", "orange", "yellow", "green", "teal", "blue", "violet", "pink")

_lock = threading.Lock()


def _register():
    """The replay for a held settings change, registered with the queue.
    bb loads this module by path (spec_from_file_location) with nothing on
    sys.path, so the directory it sits in is put there first: pending.py is
    beside it, and it imports statefile the same way."""
    import sys                                                  # noqa: PLC0415
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import pending                                              # noqa: PLC0415
    pending.applier("settings", replay)


def configure(*, write_json, state):
    _register()
    globals().update(write_json=write_json)
    globals()["FILE"] = Path(state) / "claude-prefs.json"


# ---- what is the PERSON's rather than the project's ------------------------
#
# The operator's call (17 Sep): the model and the effort a session launches on
# are facts about whoever is at the keyboard, not about the directory. Two
# people on one project want different ones, and the old per-project pair made
# one of them change the other's sessions. The author a commit carries is the
# same kind of fact, and git_identity already says so for the account; this
# adds the per-project override, for somebody who commits to one repository
# under a different name or address.
#
# Kept here, keyed by uid, and NOT in users.json: that file holds password
# hashes and is not a session's to read, while this one is read by the
# launcher at exec time so a respawn picks up a change. Nothing here is a
# secret; a git author is on every commit by design.
# `reply`: how wordy Claude's replies to this person are on this project,
# "" (Claude's own), normal or minimal. Theirs, not the project's: it is what
# they read, and the notebook, commits and files are written as ever.
# `asks`: how often Claude puts a question to this person on this project,
# "" (Claude's own), fewer or rarely. Theirs too: it is their attention.
USER_CHOICES = {"model": MODELS, "effort": EFFORTS, "reply": ("minimal",),
                "asks": ("more", "fewer", "rarely")}
USER_TEXT = {"git_name": 120, "git_email": 200}


def _clean_user(rec):
    """One person's settings on one project; unset and invalid read the same,
    for the reason _clean gives: a hand-edited typo means "leave as is"."""
    rec = rec if isinstance(rec, dict) else {}
    out = {k: (rec.get(k) if rec.get(k) in vals else "") for k, vals in USER_CHOICES.items()}
    out.update({k: str(rec.get(k) or "").strip()[:n] for k, n in USER_TEXT.items()})
    return out


def for_user(uid, project):
    """What this account chose on this project. Empty for anybody with no uid,
    which is a terminal opened before accounts existed."""
    if not uid:
        return _clean_user(None)
    d = _load()
    return _clean_user(((d.get("users") or {}).get(str(uid)) or {}).get(str(project)))


def all_for_user(uid):
    """{project: settings} for one account, in ONE read. project_list resolves
    a row per project on the poll and cannot afford a file read per row."""
    if not uid:
        return {}
    users = _load().get("users") or {}
    mine = users.get(str(uid)) or {}
    return {k: _clean_user(v) for k, v in mine.items()} if isinstance(mine, dict) else {}


def set_for_user(uid, project, patch):
    """Write one person's settings on one project; the cleaned record back.

    A field left out of the patch is left alone, and one set to "" is cleared,
    so the dialog can unset a model without unsetting an email beside it.
    """
    if not uid or not project:
        return _clean_user(None)
    patch = patch if isinstance(patch, dict) else {}
    with _lock:
        d = _load()
        users = d.setdefault("users", {})
        mine = users.setdefault(str(uid), {})
        cur = _clean_user(mine.get(str(project)))
        for k in list(USER_CHOICES) + list(USER_TEXT):
            if k in patch:
                cur[k] = patch[k]
        cur = _clean_user(cur)
        if any(cur.values()):
            mine[str(project)] = cur
        else:
            # Nothing set is no record, so the file does not grow a row per
            # person per project that says "default, default".
            mine.pop(str(project), None)
        if not mine:
            users.pop(str(uid), None)
        write_json(FILE, d)
        return cur


def forget_user_project(project):
    """Drop everybody's settings for a project that is gone."""
    with _lock:
        d = _load()
        users = d.get("users") or {}
        for uid in list(users):
            users[uid].pop(str(project), None)
            if not users[uid]:
                users.pop(uid, None)
        write_json(FILE, d)


def _load():
    """The whole file, in the per-project shape, tolerating the old one.

    Was a single global pair. It moved onto each project because the sessions
    it governs are per project: one long-lived conversation per directory, and
    which model is right for a Kotlin app is not which model is right for a
    shell script. The old global value is not thrown away: `migrate` puts it
    on every project that exists at the time, so nothing changes underfoot for
    an install that had one.
    """
    try:
        with open(FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"projects": {}, "users": {}}
    if not isinstance(d, dict):
        return {"projects": {}, "users": {}}
    p = d.get("projects")
    u = d.get("users")
    p = p if isinstance(p, dict) else {}
    # Where the tests run was a boolean, `devtest`, before it was one of
    # three places: read as tests_in on the way in, and the file follows on
    # the next save of any project, which writes the whole of it back.
    for rec in p.values():
        if isinstance(rec, dict) and "devtest" in rec:
            if rec.pop("devtest") is True and "tests_in" not in rec:
                rec["tests_in"] = "only"
    return {"projects": p, "users": u if isinstance(u, dict) else {}}


def _clean(rec):
    """One project's pair, with anything unrecognized read as "leave as is".

    Unset and invalid deliberately land in the same place: an entry
    hand-edited into nonsense should mean claude's own default, not an error
    every time a session starts.
    """
    rec = rec if isinstance(rec, dict) else {}
    return {
            # Which docker-host node this project's containers default to.
            # A node id, opaque here: prefs stores the choice, the pickers
            # resolve it, and "" means auto, the default docker node.
            # The project's node (docs/nodes.md §6, §13): where EVERYTHING
            # this project does on a node goes: its containers, builds,
            # tests, CI and emulation. One setting, by the operator's
            # decision (1 Sep): per-role pickers were more control than
            # anybody wanted. A node id, "" meaning none.
            "node": str(rec.get("node") or "")[:40],
            # ...and the set it works on (R82): the primary first, then the
            # others, so a project with a Linux node and a Windows one can be
            # worked on from either. Everything that reads one node keeps
            # reading `node`; containers may live on any of these.
            "nodes": _nodes_of(rec),
            # The other projects a session here may READ: their trees, bound
            # read-only into the session's view on a node, and their
            # notebooks through the API and the relayed verbs, every write
            # to them refused. Named here by the operator, never by a
            # session; a project never reads itself.
            "reads": _reads_of(rec),
            # The places on its node a session here is shown besides its own
            # project: a share it works with. A session's view is built from
            # what it is given (bb-session, B378), so a share mounted on the
            # node is out of it unless it is named here, by whoever may set
            # the project's node.
            "sees": _sees_of(rec),
            # What `bb build` / `bb test` run there, and the globs whose
            # matches come back into dist/.
            "build": str(rec.get("build") or "")[:500],
            "test": str(rec.get("test") or "")[:500],
            "outputs": [str(g)[:200] for g in (rec.get("outputs") or [])
                        if str(g)][:16] if isinstance(rec.get("outputs"), list) else [],
            # Anything unrecognized reads as auto, for the same reason an
            # unknown model reads as "leave as is": a hand-edited file must
            # not lock a session out of the notebook by typo.
            # What a session may do with git's network half (roadmap R36):
            # push its own branch, and push to main. Enforced where the
            # controller runs git (the relay) and read by a session with
            # bb git policy; a local commit or merge cannot be forbidden.
            "gitpol": {k: ((rec.get("gitpol") or {}).get(k)
                           if isinstance(rec.get("gitpol"), dict)
                           and (rec.get("gitpol") or {}).get(k) in GITPOL_MODES else GITPOL_DEFAULT[k])
                       for k in GITPOL_KEYS},
            "gate": {k: ((rec.get("gate") or {}).get(k)
                         if isinstance(rec.get("gate"), dict)
                         and gate_ok(k, (rec.get("gate") or {}).get(k)) else "auto")
                     for k in GATE_KINDS},
            "color": rec.get("color") if rec.get("color") in COLORS else "",
            # Whether a SESSION may rebuild this project's dev instance,
            # and it is a real grant rather than a nicety: a rebuild runs the
            # project's own Dockerfile and brings the container up, on the
            # node's daemon. `deny` by default; `auto` for a project whose
            # whole loop is "change it, rebuild it, look at it"; `ask` puts
            # the reason in front of a person, who allows one rebuild.
            # Creating, removing and Up/Down are not on this dial at all:
            # those are docker-write, which a session never has.
            "devbuild": _devbuild(rec.get("devbuild")),
            # Where `bb test` runs the tests, one of TESTS_IN. On the node
            # unless the project says otherwise: an image built to ship
            # carries no tests, and a run inside one found none and reported
            # success (B241). "only" makes a down instance a refusal that
            # names it, with nothing run on the node. Per project because
            # only a project with a compose file has a container to run in.
            "tests_in": _tests_in(rec),
            # During a test run, a change asked for: one of TEST_CHANGE.
            "test_change": rec.get("test_change") if rec.get("test_change") in TEST_CHANGE else "wait",
            # May compute on the node's NVIDIA card: one of GPU.
            "gpu": rec.get("gpu") if rec.get("gpu") in GPU else "on",
            # Claude may: Report BuilderBot bugs. Off takes `bb report` and
            # the rule that points at it away from this project's sessions.
            "report": "deny" if rec.get("report") == "deny" else "auto",
            # Claude may: Sign a release, one of SIGN_MODES (bb sign, R106).
            "sign": rec.get("sign") if rec.get("sign") in SIGN_MODES else "ask",
            # Claude may: Manage signing keys, one of SIGN_MODES: a new
            # generated key or a package mapped to a key (R106 step 6).
            "keys": rec.get("keys") if rec.get("keys") in SIGN_MODES else "ask",
            # How long a capture (a reel's sheet, an emulator shot) stays in
            # dist/ before the Artifacts tab's sweep removes it (R96). By
            # age and never by need: two sessions on one project may each
            # be reading a reel the other made. 0 keeps them.
            "capture_days": _capture_days(rec.get("capture_days")),
            # How many dev builds of each kind the Artifacts tab keeps in
            # dist/ before it removes the older (R105); 0 keeps them all.
            "dev_keep": _dev_keep(rec.get("dev_keep"))}


CAPTURE_DAYS = 7
DEV_KEEP = 3


def _dev_keep(v):
    """A whole number of builds, 0 to 99; anything else is the default."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return DEV_KEEP
    return n if 0 <= n <= 99 else DEV_KEEP


def _capture_days(v):
    """A whole number of days, 0 to 365; anything else is the default."""
    try:
        n = int(v)
    except (TypeError, ValueError):
        return CAPTURE_DAYS
    return n if 0 <= n <= 365 else CAPTURE_DAYS


def _tests_in(rec):
    """One of TESTS_IN, from the file; anything else is the default, "node"."""
    v = rec.get("tests_in")
    return v if v in TESTS_IN else "node"


def _devbuild(v):
    """One of DEVBUILD_MODES; anything else reads as `deny`."""
    return v if v in DEVBUILD_MODES else "deny"


def get(project):
    return _clean(_load()["projects"].get(project))


# How a project of each shape runs its tests, in the order a tree is asked.
# The command is never WRITTEN anywhere: the record stays exactly what the
# operator typed, and this answers when that is empty, so `bb test` on a
# project nobody has configured runs the thing that project obviously runs,
# and the settings field shows it as the placeholder it would use.
#
# Tests only. "Run the tests" has one conventional answer per ecosystem;
# "build" does not (which target, which flavor, which of an Android
# project's four), so `bb build` still refuses and says so rather than
# guessing at somebody's release variant.
def all_projects(workspace=None):
    """Every project's pair, for the status payload. Cheap (one small file,
    no subprocess), which is what lets this ride the poll at all.

    `workspace` is accepted and unused: the status poll passes it.
    """
    d = _load()["projects"]
    return {k: _clean(v) for k, v in d.items() if isinstance(k, str)}


def _reads_of(rec):
    """The projects this one reads, as stored: names that could be a
    project directory, at most 16, in the order given."""
    got = rec.get("reads") if isinstance(rec.get("reads"), list) else []
    out = []
    for n in got:
        n = str(n or "").strip()[:80]
        if n and "/" not in n and not n.startswith(".") and n not in out:
            out.append(n)
    return out[:16]


def sees_changed(project, sees):
    """Whether `sees`, as the dialog sends it, is another list than the one
    stored: the dialog sends every field on every save."""
    got = sees if isinstance(sees, list) else str(sees).split(",")
    got = [str(p).strip().rstrip("/") for p in got if str(p).strip()]
    return got != ((get(project) or {}).get("sees") or [])


def node_changed(project, req):
    """Whether the node fields the dialog sent name another node set than
    the one stored: the dialog sends every field on every save, and a user
    changing their commit name was refused over the node riding along
    unchanged (B488)."""
    cur = get(project) or {}
    want = {"node": req.get("node") if "node" in req else cur.get("node"),
            "nodes": req.get("nodes") if "nodes" in req else cur.get("nodes")}
    # The primary on its own as well as the set: moving the primary onto a
    # node already in the set is a move (seen on the dev instance, 5 Oct).
    return (str(want["node"] or "")[:40] != str(cur.get("node") or "")[:40]
            or _nodes_of(want) != _nodes_of(cur))


def rename_reads(old, new):
    """A project renamed is renamed in every other project's reads list, so
    a session on those keeps reading it. True when anything moved."""
    moved = False
    with _lock:
        d = _load()
        for rec in d["projects"].values():
            reads = rec.get("reads") if isinstance(rec, dict) and isinstance(rec.get("reads"), list) else None
            if reads and old in reads:
                rec["reads"] = [new if r == old else r for r in reads if r != new or r == old]
                moved = True
        if moved:
            write_json(FILE, d)
    return moved


def _nodes_of(rec):
    """The project's node set, primary first, from a record that may carry
    only `node` (from before R82) or a `nodes` list as well."""
    primary = str(rec.get("node") or "")[:40]
    more = rec.get("nodes") if isinstance(rec.get("nodes"), list) else []
    out = [primary] if primary else []
    for n in more:
        n = str(n or "")[:40]
        if n and n not in out:
            out.append(n)
    return out[:16]


# A place on a node, as bb-session takes one: plain characters, from the
# top, and nothing of the system's own, which the helper refuses whatever
# the settings say. The first names here are the ones it keeps.
SEES = re.compile(r"(?:/[A-Za-z0-9._-]{1,80}){1,12}")
SEES_NEVER = ("bin", "boot", "dev", "etc", "home", "lib", "lib32", "lib64", "libx32",
              "lost+found", "nix", "opt", "proc", "root", "run", "sbin", "snap", "sys",
              "tmp", "usr", "var", "workspace")
SEES_MAX = 8


def sees_problem(path):
    """Why `path` is not a place a project could be shown, or ""."""
    if not SEES.fullmatch(path) or ".." in path.split("/"):
        return (f"{path} is not a place on a node: a path from the top, in letters, "
                f"digits, dots, dashes and underscores")
    if path.split("/")[1] in SEES_NEVER:
        return (f"{path} is the machine's own or BuilderBot's: a project is shown a share "
                f"or a disk mounted on its node, like /mnt/media")
    return ""


def _sees_of(rec):
    """The places this project sees, as stored: the ones that could be a
    place, at most SEES_MAX, in the order given."""
    got = rec.get("sees") if isinstance(rec.get("sees"), list) else []
    out = []
    for p in got:
        p = str(p or "").strip().rstrip("/")
        if p and p not in out and not sees_problem(p):
            out.append(p)
    return out[:SEES_MAX]


def set_prefs(project, node=None, nodes=None, build=None, test=None,
              outputs=None, gate=None, gitpol=None,
              devbuild=None, tests_in=None, report=None, color=None, workspace=None, sign=None, keys=None,
              test_change=None, capture_days=None, reads=None, sees=None, gpu=None, dev_keep=None):
    """Change any of one project's settings; None leaves it, "" clears it."""
    if not project:
        return {"error": "no project"}
    with _lock:
        d = _load()
        cur = _clean(d["projects"].get(project))
        if color is not None:
            if color not in COLORS and color != "":
                return {"error": f"color is one of {', '.join(COLORS)}, or none: not {color}"}
            cur["color"] = color
        if nodes is not None:
            got = nodes if isinstance(nodes, list) else str(nodes).split(",")
            cur["nodes"] = [str(n).strip()[:40] for n in got if str(n).strip()][:16]
            # The primary is the first of the set unless `node` says which.
            if node is None and cur["nodes"] and cur["node"] not in cur["nodes"]:
                cur["node"] = cur["nodes"][0]
        if node is not None:
            cur["node"] = str(node)[:40]
            if cur["node"] and cur["node"] not in cur["nodes"]:
                cur["nodes"] = [cur["node"]] + cur["nodes"]
        if reads is not None:
            got = reads if isinstance(reads, list) else str(reads).split(",")
            cur["reads"] = [r for r in _reads_of({"reads": got}) if r != project]
        if sees is not None:
            got = sees if isinstance(sees, list) else str(sees).split(",")
            got = [str(p).strip().rstrip("/") for p in got if str(p).strip()]
            for p in got:
                if sees_problem(p):
                    return {"error": sees_problem(p)}
            if len(set(got)) > SEES_MAX:
                return {"error": f"a project is shown {SEES_MAX} places at most, not {len(set(got))}"}
            cur["sees"] = _sees_of({"sees": got})
        if build is not None:
            cur["build"] = str(build)[:500].strip()
        if test is not None:
            cur["test"] = str(test)[:500].strip()
        if outputs is not None:
            got = outputs if isinstance(outputs, list) else str(outputs).split(",")
            cur["outputs"] = [str(g).strip()[:200] for g in got if str(g).strip()][:16]
        if gitpol is not None:
            if not isinstance(gitpol, dict):
                return {"error": "gitpol is {push|main: allow|deny}"}
            for k, v in gitpol.items():
                if k not in GITPOL_KEYS:
                    return {"error": f"not a git policy: {k}; one of {', '.join(GITPOL_KEYS)}"}
                if v not in GITPOL_MODES:
                    return {"error": f"{k}: allow or deny, not {v}"}
                cur["gitpol"][k] = v
        if gate is not None:
            if not isinstance(gate, dict):
                return {"error": "gate is {roadmap|bugs|rules: auto|ask|deny}"}
            for k, v in gate.items():
                if k not in GATE_KINDS:
                    return {"error": f"not a gate: {k}; one of {', '.join(GATE_KINDS)}"}
                if not gate_ok(k, v):
                    return {"error": f"{k}: one of {', '.join(GATE_MODES + GATE_EXTRA.get(k, ()))}, not {v}"}
                cur["gate"][k] = v
        if devbuild is not None:
            mode = devbuild
            if mode not in DEVBUILD_MODES:
                return {"error": f"devbuild is one of {', '.join(DEVBUILD_MODES)}, "
                                 f"not {devbuild}"}
            cur["devbuild"] = mode
        if sign is not None:
            if sign not in SIGN_MODES:
                return {"error": f"sign is one of {', '.join(SIGN_MODES)}, not {sign}"}
            cur["sign"] = sign
        if keys is not None:
            if keys not in SIGN_MODES:
                return {"error": f"keys is one of {', '.join(SIGN_MODES)}, not {keys}"}
            cur["keys"] = keys
        if report is not None:
            if report not in REPORT_MODES:
                return {"error": f"report is one of {', '.join(REPORT_MODES)}, not {report}"}
            cur["report"] = report
        if tests_in is not None:
            if tests_in not in TESTS_IN:
                return {"error": f"tests_in is one of {', '.join(TESTS_IN)}, not {tests_in}"}
            cur["tests_in"] = tests_in
        if test_change is not None:
            if test_change not in TEST_CHANGE:
                return {"error": f"test_change is one of {', '.join(TEST_CHANGE)}, not {test_change}"}
            cur["test_change"] = test_change
        if gpu is not None:
            if gpu not in GPU:
                return {"error": f"gpu is one of {', '.join(GPU)}, not {gpu}"}
            cur["gpu"] = gpu
        if capture_days is not None:
            try:
                n = int(capture_days)
            except (TypeError, ValueError):
                n = -1
            if not 0 <= n <= 365:
                return {"error": f"captures kept is a number of days, 0 to 365, not {capture_days}"}
            cur["capture_days"] = n
        if dev_keep is not None:
            try:
                n = int(dev_keep)
            except (TypeError, ValueError):
                n = -1
            if not 0 <= n <= 99:
                return {"error": f"dev builds kept is a number of builds, 0 to 99, not {dev_keep}"}
            cur["dev_keep"] = n
        # An empty pair is removed rather than stored: the file then says only
        # what somebody chose, and a project left alone leaves no trace to read
        # past when its directory is renamed or deleted.
        if (cur["node"] or cur["color"] or cur["reads"] or cur["sees"]
                or cur["build"] or cur["test"] or cur["outputs"]
                or any(v != "auto" for v in cur["gate"].values())
                or cur["devbuild"] != "deny" or cur["tests_in"] != "node"
                or cur["test_change"] != "wait" or cur["gpu"] != "on"
                or cur["report"] != "auto" or cur["capture_days"] != CAPTURE_DAYS
                or cur["sign"] != "ask" or cur["keys"] != "ask"
                or cur["dev_keep"] != DEV_KEEP
                or cur["gitpol"] != GITPOL_DEFAULT):
            # Stored without the all-auto gate or the default policy, so the
            # file says only what somebody chose; _clean puts the defaults
            # back on the way out.
            rec = dict(cur)
            if all(v == "auto" for v in cur["gate"].values()):
                rec.pop("gate", None)
            if cur["gitpol"] == GITPOL_DEFAULT:
                rec.pop("gitpol", None)
            if cur["devbuild"] == "deny":
                rec.pop("devbuild", None)
            if cur["tests_in"] == "node":
                rec.pop("tests_in", None)
            if cur["report"] == "auto":
                rec.pop("report", None)
            if cur["sign"] == "ask":
                rec.pop("sign", None)
            if cur["keys"] == "ask":
                rec.pop("keys", None)
            if cur["gpu"] == "on":
                rec.pop("gpu", None)
            if cur["capture_days"] == CAPTURE_DAYS:
                rec.pop("capture_days", None)
            if cur["dev_keep"] == DEV_KEEP:
                rec.pop("dev_keep", None)
            d["projects"][project] = rec
        else:
            d["projects"].pop(project, None)
        write_json(FILE, d)
    # Into the repo's own config at once, so the next commit from any session
    # in it wears the name. Repo-local rather than global: two projects may be
    # two people's, and the tree is what a session's git reads.
    return {"ok": True, "project": project} | cur


def forget(project):
    """Drop a project's pair, for a project being deleted."""
    with _lock:
        d = _load()
        if d["projects"].pop(project, None) is not None:
            write_json(FILE, d)


# ---- a session fills in the build, test and outputs fields ------------------
# The three fields a session can know better than anybody: it has read the
# tree. What it may do with them is the project's fourth gate (roadmap #27's
# shape): auto lands the write, ask holds it for the operator on the notebook,
# deny refuses it with a sentence to quote. Only these three: the node, the
# policy and the gates themselves stay the operator's, since a session that
# could loosen its own gate has no gate.
SESSION_FIELDS = ("build", "test", "outputs")


def session_set(project, **fields):
    """A session's write to build, test or outputs, through the gate."""
    import pending                                              # noqa: PLC0415
    got = {k: v for k, v in fields.items() if k in SESSION_FIELDS and v is not None}
    if not got:
        return {"error": f"nothing to set: one of {', '.join(SESSION_FIELDS)}"}
    if not pending.replaying():
        g = pending.mode(project, "settings")
        if g == "deny":
            return {"error": pending.refusal("settings")}
        if g == "ask":
            words = "; ".join(f"{k}: {v if isinstance(v, str) else ', '.join(v)}" for k, v in got.items())
            return pending.hold(project, "settings", "set", got, summary=words)
    r = set_prefs(project, **got)
    return r if r.get("error") else {"ok": True, "set": sorted(got)}


def replay(project, verb, args):
    if verb != "set":
        return {"error": f"not a settings change that can be replayed: {verb}"}
    return session_set(project, **{k: v for k, v in (args or {}).items() if k in SESSION_FIELDS})


# ---- the settings dialog's save, one call from the dashboard ------------------

# What dialog_save() needs from the server, set by configure_dialog: the
# projects' directory (set_prefs reads a project's files), a dev instance
# pinned to the node it is on before its project moves
# (devapp.pin_to_current_node), a project's Claude session ended
# (end_claude), and the sessions' networks told (R79).
WORKSPACE = None
pin_instances = None
end_claude = None
net_nudge = None


def configure_dialog(**parts):
    globals().update(parts)


def dialog_save(name, req, uid):
    """A project's settings dialog saved, once server.py has let this person
    at the project, its node and its container dial: the project's own
    settings, and what is the asking account's. (payload, status)."""
    # A dev instance with no node of its own follows the project's, so a
    # node change would move its row onto a daemon that has none of it
    # while its containers carry on running where they are. They stay up
    # on purpose: an instance is removed from the Docker manager, never by
    # a setting changed somewhere else. So they keep their row too, pinned
    # to the machine they are actually on, and the manager can still stop
    # or remove them. Before the write, because afterwards the old node is
    # not recorded anywhere.
    moved = []
    moved_node = False
    if "node" in req and str(req.get("node") or "") != (get(name) or {}).get("node", ""):
        moved = pin_instances(name)
        moved_node = True
    r = set_prefs(name, node=req.get("node"), nodes=req.get("nodes"),
                  build=req.get("build"),
                  test=req.get("test"), outputs=req.get("outputs"),
                  gate=req.get("gate"), gitpol=req.get("gitpol"),
                  devbuild=req.get("devbuild"),
                  tests_in=req.get("tests_in"),
                  test_change=req.get("test_change"), gpu=req.get("gpu"),
                  report=req.get("report"), capture_days=req.get("capture_days"),
                  dev_keep=req.get("dev_keep"), sign=req.get("sign"), keys=req.get("keys"),
                  color=req.get("color"), reads=req.get("reads"), sees=req.get("sees"),
                  workspace=WORKSPACE)
    # ...and what is the ASKING ACCOUNT's rather than the project's: the
    # model and effort its sessions launch on, and the author its commits
    # here carry. Same dialog, same request, different store, because two
    # people on one project are two authors on two models and neither
    # should be able to change the other's (17 Sep).
    mine = {k: req[k] for k in ("model", "effort", "git_name", "git_email", "reply", "asks") if k in req}
    if mine and not r.get("error"):
        r = dict(r) | {"yours": set_for_user(uid, name, mine)}
    # The restart is asked for by the dialog, which is where the
    # operator was told what it costs, and never inferred here from the
    # change alone, because the same write happens when nothing is
    # running and there is nothing to interrupt.
    if not r.get("error") and req.get("restart"):
        r |= end_claude(name)
    if moved and not r.get("error"):
        r = dict(r) | {"pinned": moved}
    # A project on another node owns its instances somewhere else now (R79).
    if moved_node and not r.get("error"):
        net_nudge()
    return r, (400 if r.get("error") else 200)
