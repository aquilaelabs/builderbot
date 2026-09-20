"""One letter per notebook tab, so a number says which list it came from.

A roadmap item is R12 and a bug is B62. Before this both were "#12", and a
reply, a commit message or a log line saying "#12" could be read against
either tab, and #137 in the same sentence was a GitHub pull request. The
operator asked for something that cannot be misread (roadmap #28), and one
letter is the smallest thing that does it: it fits a sentence, survives
`bb history --find B62`, and is not what GitHub uses.

Rules are keyed by name (`agent-compat`), not by number, so they need no
letter, which also keeps R from having to mean two things. A test is keyed
`file#ordinal` already.

The letter is a CHECK on the way in, not only a label on the way out: every
verb accepts the bare number, so nothing a session already knows breaks, but
`bb bug fix R12` stops with a sentence saying R12 is a roadmap item. That
refusal is the whole reason for the letter existing.
"""
import re

LETTERS = {"roadmap": "R", "bugs": "B"}
NAMES = {"roadmap": "a roadmap item", "bugs": "a bug"}
# The lower-case forms and a leading '#' are accepted because they are what
# somebody types from memory; only what is printed is canonical.
_RE = re.compile(r"^#?([A-Za-z]?)0*(\d+)$")


def label(kind, n):
    """The printed form: R12, B62."""
    return f"{LETTERS[kind]}{n}"


def parse(kind, word):
    """(number, error) out of whatever named an item.

    An int passes through: the dashboard sends those, and it never gets a
    letter wrong. A string may be "12", "R12", "r12" or "#12" for the
    roadmap. Another tab's letter is the one refusal, worded so the reader
    learns both letters from it. Anything else is (None, None): the caller
    already says "no such item" for that, and that answer is right.
    """
    if isinstance(word, bool):
        return None, None
    if isinstance(word, int):
        return word, None
    if isinstance(word, float):
        return (int(word), None) if word == int(word) else (None, None)
    if not isinstance(word, str):
        return None, None
    m = _RE.match(word.strip())
    if not m:
        return None, None
    letter, n = m.group(1).upper(), int(m.group(2))
    if letter and letter != LETTERS[kind]:
        other = next((k for k, v in LETTERS.items() if v == letter), None)
        if other is None:
            return None, (f"{word.strip()} is not {NAMES[kind]}'s number; "
                          f"those are {label(kind, n)}")
        return None, (f"{label(other, n)} is {NAMES[other]}; {NAMES[kind]} is "
                      f"{label(kind, n)}")
    return n, None
