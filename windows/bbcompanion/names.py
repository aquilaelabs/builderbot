"""Windows' rules for a file's name, which a project made on Linux need not
keep (R270 step 3): a name Windows cannot hold is left out of the copy and
said, rather than failing the sync on every tick.

Windows refuses the device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9, with or
without an extension), a name ending in a dot or a space, and the characters
< > : " | ? * and the control characters; and it holds Foo and foo as one
file, so of two paths that differ only by case the first (in sorted order)
is kept and the rest said.
"""
import re

RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f\\]')


def part_why(part):
    """Why Windows cannot hold one segment of a path, or ""."""
    if part.split(".")[0].upper() in RESERVED:
        return f"{part} is a name Windows keeps for a device"
    if part.endswith((".", " ")):
        return f"{part} ends in a dot or a space, which Windows drops"
    if BAD_CHARS.search(part):
        return f"{part} has a character Windows refuses in a name"
    return ""


def path_why(rel):
    """Why Windows cannot hold this path, or ""."""
    for part in rel.split("/"):
        why = part_why(part)
        if why:
            return why
    return ""


def held(paths):
    """Of a project's paths: ({path kept}, {path left out: why}). A path
    differing from a kept one only by case is left out, as Windows would
    write one over the other."""
    kept, out, seen = set(), {}, {}
    for rel in sorted(paths):
        why = path_why(rel)
        if why:
            out[rel] = why
            continue
        low = rel.lower()
        if low in seen:
            out[rel] = f"Windows holds it and {seen[low]} as one file: only {seen[low]} is kept"
            continue
        seen[low] = rel
        kept.add(rel)
    return kept, out
