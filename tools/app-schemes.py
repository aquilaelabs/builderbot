#!/usr/bin/env python3
"""Write the companion app's color schemes from the design record, both
halves, so the app's twelve are the dashboard's by construction rather than
a copy kept by hand (R50 step 16).

    bb design json | python3 tools/app-schemes.py

rewrites Schemes.all in android/.../ui/Theme.kt in place and says how many
it wrote. A theme without a light half is refused: the app offers Light for
every scheme, as the gear does.
"""
import json
import os
import sys

KEYS = ["bg", "panel", "ink", "dim", "line", "accent", "warn", "bad", "note"]
THEME_KT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "android", "app", "src", "main",
                        "java", "dev", "builderbot", "app", "ui", "Theme.kt")


def half(cols, name, which):
    got = {c["name"]: c["hex"] for c in cols or []}
    missing = [k for k in KEYS if k not in got]
    if missing:
        sys.exit(f"app-schemes: {name}'s {which} half has no {', '.join(missing)}")
    return ", ".join("0xFF" + got[k].lstrip("#").upper() for k in KEYS)


def main():
    record = json.load(sys.stdin)
    rows = []
    for t in record["language"]["themes"]:
        rows.append(f'        Scheme("{t["name"]}",\n'
                    f'            Half({half(t.get("colors"), t["name"], "dark")}),\n'
                    f'            Half({half(t.get("light"), t["name"], "light")}, light = true)),')
    with open(THEME_KT) as f:
        src = f.read()
    start = src.index("    val all = listOf(\n") + len("    val all = listOf(\n")
    end = src.index("    )\n", start)
    with open(THEME_KT, "w") as f:
        f.write(src[:start] + "\n".join(rows) + "\n" + src[end:])
    print(f"app-schemes: wrote {len(rows)} schemes, both halves, into {os.path.relpath(THEME_KT)}")


if __name__ == "__main__":
    main()
