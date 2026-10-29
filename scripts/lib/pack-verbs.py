"""Behind `bb tool search` and `bb tool install` (cmd_tool in bb, R169 step
5): the vetted catalog's tool packs looked through, and one asked for by
name, as the project's Install a tool pack dial says (deny refuses, ask
waits for a person on the bell, auto adds it now at the commit the signed
index pins). A session never installs a pack on a node itself: once added,
a person installs it from the Library, or it is there already.

BB_PACK_AUTH is the auth header; the rest is argv: the verb, then its words.
"""
import os
import sys

import bbapi

AUTH = os.environ.get("BB_PACK_AUTH", "")
USAGE = """usage: bb tool search [WORDS...]
       bb tool install NAME --why "what it is for\""""


def main(argv):
    if not argv or argv[0] not in ("search", "install"):
        sys.exit(USAGE)
    if argv[0] == "search":
        import urllib.parse
        d = bbapi.call("/api/catalog/search?q=" + urllib.parse.quote(" ".join(argv[1:])), auth=AUTH)
        if d.get("error") and not d.get("packs"):
            sys.exit(f"[builderbot] ERROR: {d['error']}")
        rows = d.get("packs") or []
        if not rows:
            print("nothing in the vetted catalog matches" + (f" {' '.join(argv[1:])}" if argv[1:] else ""))
            return
        for r in rows:
            mark = " (added here)" if r.get("added") else ""
            print(f"{r['name']:<24} {r.get('kind', 'pack'):<6} {r.get('tier') or '':<9} {r.get('about') or ''}{mark}")
        if d.get("more"):
            print(f"... and {d['more']} more: add words to narrow it")
        print("\nbb tool install NAME --why \"what it is for\" asks for one, as this project's Install a tool pack setting says")
        return
    rest = argv[1:]
    why = ""
    if "--why" in rest:
        i = rest.index("--why")
        why = " ".join(rest[i + 1:i + 2])
        rest = rest[:i] + rest[i + 2:]
    if len(rest) != 1:
        sys.exit(USAGE)
    d = bbapi.call("/api/toolpacks", {"action": "install", "name": rest[0], "why": why}, auth=AUTH)
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: {d['error']}")
    if d.get("request") or d.get("asked") or d.get("id"):
        print(f"asked: {rest[0]} waits for a person on the bell; bb tool search shows it as added once they allow it")
    elif d.get("note"):
        print(d["note"])
    else:
        print(f"{rest[0]} is added to the catalog here: a person installs it on a node from the Library")


if __name__ == "__main__":
    main(sys.argv[1:])
