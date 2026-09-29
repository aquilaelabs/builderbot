"""A part's share of what a session is sent, and how a part keeps to it.

A project only grows, and the block in front of every session is paid for
on every conversation. The notebook used to protect it by keeping less (a
31st roadmap item was refused) and the block by cutting its own tail at a
fixed size, blind to what the tail was. Both gave up the wrong thing (the
operator, 29 Sep): the record is what must be whole, and the block is an
index into it.

So each part that grows (the rules, the roadmap, the bugs) has a share,
and one over its share says LESS PER ROW before it drops a row: its rows
in full, then their titles, then the titles cut short, then as many as
fit with the rest as a count and the verb that lists them. Every part is
always there, whatever the others hold, and what a part left out is said
in the part, where the session reading it will see it.

No imports from the rest of the dashboard, so a module bb loads by path
can use it too.
"""


def size(text):
    """What a text costs, in the bytes it is sent as."""
    return len((text or "").encode("utf-8"))


def clip(text, cap):
    """One line of `text`, cut at a word where it is longer than `cap`."""
    line = " ".join(str(text or "").split())
    if not cap or len(line) <= cap:
        return line
    cut = line[:cap].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return (cut or line[:cap]) + "..."


def fitted(levels, budget):
    """(text, what it left out) from the first of `levels` that fits.

    `levels` are callables, the one that says most first, each answering
    (text, left): `left` is "" where nothing was left out. With no budget
    the first is the answer. The last is the answer whatever its size: it
    is the one that fills what room there is, and a part is never nothing.
    """
    said = ("", "")
    for make in levels:
        said = make()
        if budget is None or size(said[0]) <= budget:
            return said
    return said


def filled(lines, room):
    """How many of `lines`, from the first, fit in `room` bytes, each with
    the newline that joins it."""
    n = used = 0
    for line in lines:
        used += size(line) + 1
        if used > room:
            break
        n += 1
    return n
