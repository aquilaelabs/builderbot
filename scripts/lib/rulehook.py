"""What a session's hooks keep between calls about the house rules (R200).

Two small records, on the machine the session runs on, under the account's
own cache beside bb-check-relay's stamp:

  fired/<conversation id>  the named rules this conversation was told,
                           one name a line, so the SessionStart hook can
                           say them again after a summary drops them
                           (Claude Code keeps the id across a compaction);
  guards.json              what the Bash guard refuses in this project, as
                           the controller last said, kept a minute so a
                           node does not ask on every command.

Here rather than in the hooks themselves because three of them read and
write it (bb-work-note, bb-prompt-relay, bb-rule-hook), and in scripts/lib
because a node carries this directory and not the dashboard's modules.
Every function swallows its own failures: a hook that cannot keep a note
is never worth a turn.
"""
import json
import os
import re
import time

import cmdmatch

GUARDS_FOR = 60                 # seconds a node's copy of the guards is used
FIRED_FOR = 14 * 86400          # a conversation's record kept this long after its last write
_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _uid():
    return os.environ.get("BB_ACCOUNT_UID") or "_none"


def project_dir(project):
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.environ.get("HOME", "/tmp"), ".cache")
    return os.path.join(base, "builderbot", "u", _uid(), "project", project)


def _fired_file(project, conversation):
    if not _ID.match(str(conversation or "")) or not project:
        return ""
    return os.path.join(project_dir(project), "fired", conversation)


def remember(project, conversation, names):
    """Add these rule names to what this conversation was told."""
    f = _fired_file(project, conversation)
    names = [n for n in (names or []) if re.match(r"^[a-z0-9][a-z0-9-]{0,39}$", str(n))]
    if not f or not names:
        return
    try:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        have = set(fired(project, conversation))
        with open(f, "a") as out:
            for n in names:
                if n not in have:
                    out.write(n + "\n")
                    have.add(n)
        _prune(os.path.dirname(f))
    except OSError:
        pass


def fired(project, conversation):
    """The rule names this conversation was told, in the order it heard them."""
    f = _fired_file(project, conversation)
    try:
        with open(f) as src:
            return [ln.strip() for ln in src if ln.strip()]
    except OSError:
        return []


def _prune(d):
    now = time.time()
    try:
        for e in os.scandir(d):
            if e.is_file() and now - e.stat().st_mtime > FIRED_FOR:
                os.unlink(e.path)
    except OSError:
        pass


def cached_guards(project, stale=False):
    """The guards as last fetched, or None when there is no fresh copy;
    `stale` takes any copy, for when the controller does not answer."""
    f = os.path.join(project_dir(project), "guards.json")
    try:
        if not stale and time.time() - os.stat(f).st_mtime > GUARDS_FOR:
            return None
        with open(f) as src:
            got = json.load(src)
        return got if isinstance(got, list) else None
    except (OSError, ValueError):
        return None


def keep_guards(project, guards):
    f = os.path.join(project_dir(project), "guards.json")
    try:
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f + ".new", "w") as out:
            json.dump(guards, out)
        os.replace(f + ".new", f)
    except OSError:
        pass


def refused(guards, command, background=False):
    """(the guard that refuses this shell line, the command as read) or
    None. `guards` is rules.guards()'s list, from the store or the
    controller; one marked `foreground` refuses only a call that is not run
    in the background."""
    for g in guards or []:
        if background and g.get("foreground"):
            continue
        hit = cmdmatch.first_match(command, g.get("refuse") or [])
        if hit:
            return g, hit[0]
    return None


def refusal(g, command):
    """What a refused Bash call is told, in place of running."""
    whose = {"builderbot": "BuilderBot's briefing", "claude": "a note a session left"}.get(
        g.get("by"), "the operator's house rule")
    return (f"Refused by {whose} [{g.get('name', '')}]: `{command[:160]}` is a command it does not "
            f"let run.\n{g.get('text', '')}\n"
            "Do it the way the rule says. If the rule is wrong for what you are doing, say so in "
            "your reply and leave it to the person; do not run it another way.")


# What the person sees of it (the operator, 12 Oct): every hook that hands
# Claude text hands the person the same as a systemMessage, which Claude
# Code shows in the conversation, so what Claude is acting on is on the
# screen and not only in its context.
SHOWN_MAX = 4000


def shown(what, text):
    """`text` as the person is shown it, labeled with what it is."""
    text = str(text or "").strip()
    if len(text) > SHOWN_MAX:
        text = text[:SHOWN_MAX].rstrip() + " ..."
    return f"[BuilderBot {what}] {text}"


# ---- the map first (the operator, 12 Oct) -----------------------------------
# A grep for where something is defined, or where it is called, is a
# question the code map answers in one call with the function's own
# comment (`bb map find`). A session that greps for it anyway is handed
# the map's answer beside its search, so the lookups the map would have
# saved are not spent. The search still runs: this adds, never refuses.

_DEF_WORDS = r"(?:async\s+function|function|def|class|fn|func|fun|interface|struct|enum|const|let|var|type)"
_DEF = re.compile(_DEF_WORDS + r"\s+([A-Za-z_][A-Za-z0-9_]{2,})")
_CALL = re.compile(r"^([A-Za-z_][A-Za-z0-9_]{3,})\($")
MAP_NAMES = 2
MAP_LINES = 6


def _plain(pattern):
    """A regex as the words it looks for: anchors, word edges and the
    escapes a person types around a name taken out."""
    p = str(pattern or "")
    for a, b in (("\\b", ""), ("\\<", ""), ("\\>", ""), ("\\s+", " "), ("\\s*", " "),
                 ("\\(", "("), ("[[:space:]]+", " "), ("[[:space:]]*", " ")):
        p = p.replace(a, b)
    return p.strip().lstrip("^").rstrip("$")


def symbols(pattern):
    """The names a search pattern is looking up: `def NAME`, `function
    NAME`, `class NAME` and the like, or `NAME(` alone. Nothing for a
    search of text."""
    out = []
    for alt in re.split(r"\\?\|", str(pattern or "")):
        p = _plain(alt)
        m = _DEF.search(p) or _CALL.match(p.replace(" ", ""))
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out[:MAP_NAMES]


def search_patterns(command):
    """The patterns of the code searches a shell line runs: grep -r, rg and
    git grep, each's first pattern (or its -e ones)."""
    out = []
    for w in cmdmatch.commands(command):
        if w[:2] == ["git", "grep"]:
            args = w[2:]
        elif w[:1] in (["grep"], ["egrep"], ["rg"]):
            args = w[1:]
        else:
            continue
        pats = [args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-e", "--regexp")]
        if not pats:
            pats = [a for a in args if not a.startswith("-")][:1]
        out += pats
    return out
