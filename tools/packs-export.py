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
    tools/packs-export.py --catalog DIR          write the same folders under DIR/packs/ (the builderbot-catalog checkout)
    tools/packs-export.py --catalog DIR --index  rewrite DIR/index.json's official entries from DIR's HEAD commit
The catalog (R170 step 6, the operator: the shipped toolchains and agents live
in the catalog repository): every official pack is a folder of that repository,
and its index entry pins the catalog's own commit, the folder as `path`, and
the sha256 of `git archive --format=tar COMMIT PATH`. Two commits, since an
index cannot pin the commit that holds it: --catalog writes the folders to
commit first, --index then pins that commit; the maintainer signs the index.
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


def catalog_dir_paths(root):
    """[(path under DIR, manifest, index name)] for every official pack."""
    out = []
    for path, m in toolchain_packs() + agent_packs():
        rel = os.path.relpath(path, PACKS)                     # official/NAME/bbtool.json
        out.append((os.path.join(root, "packs", rel), m, rel.split(os.sep)[1]))
    return out


def catalog_write(root):
    n = 0
    for path, m, _name in catalog_dir_paths(root):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text(m))
        n += 1
    print(f"  wrote {n} official pack(s) under {os.path.join(root, 'packs')}")


def catalog_index(root):
    """DIR/index.json with an official entry per pack, pinned to DIR's HEAD
    and the sha256 of that folder's archive there; other entries kept."""
    import hashlib
    import subprocess
    import time
    head = subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", root, "status", "--porcelain", "packs"], capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        print("  [FAIL] packs/ in the catalog is not committed: commit the folders first, then --index pins that commit")
        return 1
    url = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True, text=True, check=False).stdout.strip() \
        or "https://github.com/aquilaelabs/builderbot-catalog"
    url = url.removesuffix(".git")
    idx_path = os.path.join(root, "index.json")
    try:
        with open(idx_path, encoding="utf-8") as f:
            idx = json.load(f)
    except (OSError, ValueError):
        idx = {"version": 1, "packs": []}
    kept = [p for p in idx.get("packs", []) if p.get("tier") != "official"]
    new = []
    for path, m, name in catalog_dir_paths(root):
        folder = os.path.relpath(os.path.dirname(path), root)
        tar = subprocess.run(["git", "-C", root, "archive", "--format=tar", head, folder], capture_output=True, check=True).stdout
        new.append({"name": name, "url": url, "commit": head, "path": folder, "sha256": hashlib.sha256(tar).hexdigest(),
                    "tier": "official", "withdrawn": False, "about": m["about"] or m["label"], "platforms": m["platforms"]})
    idx = {"version": 1, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "packs": new + kept}
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=1)
        f.write("\n")
    print(f"  wrote {len(new)} official entries pinned to {head[:12]} (and kept {len(kept)} others) in {idx_path}; sign it")
    return 0


def main(argv):
    want = toolchain_packs() + agent_packs()
    if "--catalog" in argv:
        root = argv[argv.index("--catalog") + 1]
        if "--index" in argv:
            return catalog_index(root)
        bad = sum(1 for _p, m in want if toolpacks.validate(m, shipped=())[1])
        if bad:
            return 1
        catalog_write(root)
        return 0
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
