"""Which commands a shell line runs, and whether one of them is refused.

A house rule can refuse commands outright (rules.py, `refuse`), and the
PreToolUse guard on a session's Bash calls (bb-rule-hook) asks this whether
the line about to run starts one. Here, in scripts/lib, because the guard
runs on a node, which carries this directory and not the dashboard's
modules, and rules.py reads it from the controller side the same way.

The line is read as a shell would split it, not as text: a word inside
quotes is an argument, so `grep "apt install" notes.md` runs grep and is
let through, while `sudo apt install jq` runs apt and is not. Each simple
command is cut at `;`, `&&`, `||`, `|`, `&`, a newline and the brackets of
`$(...)` and a subshell; the wrappers that run another command in front of
it (sudo, env, timeout, nohup, `bb run --` and the like) and leading
VAR=value assignments are stepped over; `bash -c '...'` is read again
inside; a heredoc's body is data and is not read at all.

A pattern is the start of a command, as typed: `apt install` refuses
`apt install jq` and `apt install`, not `apt list`; a shell glob in it
matches the way fnmatch does, so `pkill -f *` is the same as `pkill -f`.
The first word is also tried as its basename, so `emulator -avd` refuses
`$ANDROID_HOME/emulator/emulator -avd x` as well.

What this cannot see is said rather than pretended: a command built from a
variable or a script written to a file and run is not read. The guard is
the cheap half (a mistake made by habit is stopped with the reason); the
rule's text in the session's prompt is still the whole of the instruction.
"""
import fnmatch
import os
import re
import shlex

SEPARATORS = {";", ";;", "&&", "||", "|", "|&", "&", "(", ")", "\n"}
# What runs the next word as the command. Each maps to how many of its own
# arguments to skip, counted after its options; options are skipped as long
# as they start with a dash.
WRAPPERS = {"sudo": 0, "doas": 0, "env": 0, "command": 0, "exec": 0, "nohup": 0,
            "time": 0, "nice": 0, "ionice": 0, "stdbuf": 0, "setsid": 0, "xargs": 0,
            "timeout": 1, "chronic": 0}
# Options of a wrapper that take a value, so the value is not read as the
# command: `sudo -u bob apt install`, `timeout -s KILL 30 cmd`.
_VALUED = {"sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U"},
           "doas": {"-u", "-C"},
           "timeout": {"-s", "-k", "--signal", "--kill-after"},
           "nice": {"-n"}, "ionice": {"-c", "-n"}, "env": {"-u", "-C", "-S"},
           "xargs": {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a"}}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
MAX_DEPTH = 3


def _drop_heredocs(text):
    """The line with every heredoc's body removed: what follows `<<WORD` up
    to the line that is WORD is data a command reads, never a command."""
    out, ending = [], []
    for line in text.split("\n"):
        if ending:
            if line.strip() == ending[0]:
                ending.pop(0)
            continue
        out.append(line)
        ending = [m.group(2) for m in _HEREDOC.finditer(line)]
    return "\n".join(out)


def _tokens(text):
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lex.whitespace = " \t\r"          # a newline is a separator, said below
    lex.wordchars += "~-./*?[]{}=:,+%@^!$"
    lex.commenters = "#"
    try:
        return list(lex)
    except ValueError:
        # An unbalanced quote: read the words it does have, plainly. A
        # guard that cannot parse a line lets it through rather than guess.
        return text.replace("\n", " ; ").split()


def _unwrap(words):
    """The words of the command a wrapper runs, with the wrapper, its
    options and any VAR=value in front stepped over."""
    i = 0
    while i < len(words):
        w = words[i]
        if _ASSIGN.match(w):
            i += 1
            continue
        if w == "bb" and words[i + 1:i + 2] == ["run"]:
            # `bb run [--node N] -- CMD`: the command is after the `--`.
            try:
                i = words.index("--", i) + 1
            except ValueError:
                return words[i:]
            continue
        base = os.path.basename(w)
        # `bash scripts/bb tests run` runs the script: read it as the
        # command, the way `bash -c '...'` is read again below.
        if base in ("bash", "sh", "dash", "zsh") and i + 1 < len(words) and not words[i + 1].startswith("-"):
            i += 1
            break
        if base in WRAPPERS:
            i += 1
            valued = _VALUED.get(base, set())
            while i < len(words) and words[i].startswith("-") and words[i] != "--":
                i += 2 if words[i] in valued else 1
            if i < len(words) and words[i] == "--":
                i += 1
            i += WRAPPERS[base]
            continue
        break
    return words[i:]


def commands(text, depth=0):
    """Every simple command the line runs, each as its list of words."""
    toks = _tokens(_drop_heredocs(str(text or "")).replace("\\\n", " ").replace("\n", " \n "))
    out, cur = [], []
    for t in toks + [";"]:
        if t in SEPARATORS or t.strip() == "":
            if cur:
                words = _unwrap(cur)
                if words:
                    out.append(words)
                    # `bash -c 'apt install jq'` runs what is in the quotes.
                    if (depth < MAX_DEPTH and os.path.basename(words[0]) in ("bash", "sh", "zsh", "dash")
                            and "-c" in words[1:]):
                        j = words.index("-c", 1)
                        if j + 1 < len(words):
                            out += commands(words[j + 1], depth + 1)
            cur = []
            continue
        if t.endswith("$") and len(t) > 1:
            t = t[:-1]                # `x=$(` leaves `x=$` before the bracket
        cur.append(t)
    return out


def _fits(words, pattern):
    said = " ".join(words)
    pat = " ".join(str(pattern).split())
    if not pat:
        return False
    # The pattern's first word names the program: it has to fit the command's
    # first word on its own, so a star there cannot cross into the arguments
    # (`*/test/run.sh` once refused `sed -n 1,5p scripts/.../test/run.sh`, B700).
    head = pat.split(" ", 1)[0]
    base = os.path.basename(words[0])
    if not (fnmatch.fnmatchcase(words[0], head) or fnmatch.fnmatchcase(base, head)):
        return False
    if fnmatch.fnmatchcase(said, pat) or fnmatch.fnmatchcase(said, pat + " *"):
        return True
    if base != words[0]:
        said = " ".join([base] + words[1:])
        return fnmatch.fnmatchcase(said, pat) or fnmatch.fnmatchcase(said, pat + " *")
    return False


def first_match(text, patterns):
    """(the command as it was read, the pattern) for the first command in
    the line that a pattern refuses, or None. A pattern that starts with
    `!` is an exception: a command it fits is let through whatever else
    fits it (`!apt-get install* -s*`, a dry run)."""
    pats = [str(p).strip() for p in (patterns or []) if str(p).strip()]
    but = [p[1:].strip() for p in pats if p.startswith("!")]
    pats = [p for p in pats if not p.startswith("!")]
    if not pats:
        return None
    for words in commands(text):
        if any(_fits(words, b) for b in but):
            continue
        for p in pats:
            if _fits(words, p):
                return " ".join(words), p
    return None
