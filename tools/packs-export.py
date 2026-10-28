#!/usr/bin/env python3
"""The official packs (R169 step 1): every shipped toolchain
(config/toolchains.json) and every coding agent (agents.py's table) written
as a pack in bbtool.json's format under packs/, tagged official and
bundled with the release for an install with no network. One manifest
for everything: the installer and the agents' adapters still read their
own tables; the packs are those tables in the one format, and this
script's --check holds the two to each other in bb lint.

    tools/packs-export.py --write     write packs/official/*/bbtool.json and packs/agents/*/bbtool.json
    tools/packs-export.py --check     fail when what is written is not what the tables say
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "dashboard"))
import agents    # noqa: E402
import toolpacks  # noqa: E402

PACKS = os.path.join(ROOT, "packs")


def toolchain_packs():
    """[(path, manifest)] for every shipped toolchain."""
    with open(os.path.join(ROOT, "config", "toolchains.json"), encoding="utf-8") as f:
        rows = json.load(f)["toolchains"]
    out = []
    for r in rows:
        shipped = {k: r[k] for k in ("probe", "source", "system", "requires", "updatable", "tool") if k in r}
        m = {"name": r["name"], "label": r["label"], "about": r.get("about", ""), "tier": "official",
             "platforms": r.get("platforms") or ["linux/amd64"], "terms": r.get("terms") or [],
             "layout": {k: v for k, v in (r.get("layout") or {}).items() if k in ("bin", "env", "tool")},
             "shipped": shipped}
        if (r.get("layout") or {}).get("reports"):
            m["shipped"]["reports"] = r["layout"]["reports"]
        # The folder is the name with its colon as a hyphen (android:emulator
        # under android-emulator), a folder name every system takes.
        out.append((os.path.join(PACKS, "official", r["name"].replace(":", "-"), "bbtool.json"), m))
    return out


def agent_packs():
    """[(path, manifest)] for every coding agent the table lists."""
    out = []
    for a in agents.TABLE:
        m = {"name": a.id, "label": a.name, "about": f"{a.product}, run by sessions as {a.command}", "tier": "official",
             "platforms": ["linux/*"], "terms": [],
             "agent": {k: getattr(a, k) for k in toolpacks.AGENT_FIELDS}}
        out.append((os.path.join(PACKS, "agents", a.id, "bbtool.json"), m))
    return out


def text(m):
    return json.dumps(m, indent=1, sort_keys=True) + "\n"


def main(argv):
    want = toolchain_packs() + agent_packs()
    bad = 0
    for path, m in want:
        clean, errors = toolpacks.validate(m, shipped=())
        if errors:
            print(f"  [FAIL] {os.path.relpath(path, ROOT)}: " + "; ".join(errors))
            bad += 1
    if bad:
        return 1
    if "--write" in argv:
        for path, m in want:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text(m))
        print(f"  wrote {len(want)} pack(s) under packs/")
        return 0
    wanted = {os.path.relpath(p, ROOT) for p, _ in want}
    for path, m in want:
        try:
            with open(path, encoding="utf-8") as f:
                have = f.read()
        except OSError:
            have = ""
        if have != text(m):
            print(f"  [FAIL] {os.path.relpath(path, ROOT)} is not what the table says: tools/packs-export.py --write rewrites it")
            bad += 1
    for sub in ("official", "agents"):
        d = os.path.join(PACKS, sub)
        for name in (os.listdir(d) if os.path.isdir(d) else []):
            rel = os.path.join("packs", sub, name, "bbtool.json")
            if rel not in wanted:
                print(f"  [FAIL] {rel} names nothing the tables ship any more: remove it")
                bad += 1
    if not bad:
        print(f"  [ok]   {len(want)} official pack(s) match the tables")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
