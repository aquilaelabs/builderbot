"""Behind `bb tool PACK [VERB ARGS...]` for a tool pack (R77): the verb's
words from the pack's manifest, as the catalog carries them, with the
placeholders filled in, run in place of this process. Nothing here is a
shell: a verb is a list of words a person approved when the pack was added,
and the caller's own words go in where it says {args}, each one a word.

Arguments: the pack's directory in the store (sdk_find's answer), the
project's directory, the pack's name, then the verb and its words. The
catalog is read through sdkmeta, packs and all.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sdkmeta  # noqa: E402

pack_dir, project_dir, name, rest = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]


def die(msg):
    print(f"[builderbot] ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


if name == "--list":
    packs = [p for p in sdkmeta.catalog() if p.get("pack")]
    if packs:
        print("\n  tool packs added here (bb tool PACK lists a pack's verbs):")
    off = set(os.environ.get("BB_TOOLCHAINS_OFF", "").split())
    for p in packs:
        # One this project's settings switch off is said so here, where a
        # session looks first, not only when it is run.
        print(f"  bb tool {p['name']} {'|'.join(sorted(p.get('verbs') or {}))} ..."
              + ("   (switched off for this project: its settings' Toolchains group turns it on)" if p["name"] in off else ""))
    raise SystemExit(0)
row = next((p for p in sdkmeta.catalog() if p.get("name") == name), None)
if not row or not row.get("pack"):
    die(f"no tool called {name}: bb tool lists them")
verbs = row.get("verbs") or {}


def usage():
    print(f"bb tool {name}: {row.get('label') or name}, a tool pack added by "
          f"{(row['pack'].get('by') or 'an administrator')} from {row['pack'].get('url')}")
    for v, spec in sorted(verbs.items()):
        print(f"  bb tool {name} {v} {spec.get('usage') or ''}".rstrip())
        if spec.get("about"):
            print(f"      {spec['about']}")
    print(f"  bb help tool-{name} is how the pack says to use them")


if not rest or rest[0] in ("-h", "--help"):
    usage()
    raise SystemExit(0)
verb, args = rest[0], rest[1:]
if name in os.environ.get("BB_TOOLCHAINS_OFF", "").split():
    die(f"{name} is switched off for this project: its settings' Toolchains group turns it on")
spec = verbs.get(verb)
if not spec:
    die(f"{name} has no verb {verb}: " + ", ".join(sorted(verbs)) + f" (bb tool {name})")
if not pack_dir:
    die(f"{name} is not installed on this node: the Library installs it")
dist = os.path.join(project_dir, "dist") if project_dir else os.path.join(os.getcwd(), "dist")
fill = {"{dir}": pack_dir, "{dist}": dist, "{project}": os.path.basename(project_dir or os.getcwd())}
argv = []
for w in spec["run"]:
    if w == "{args}":
        argv.extend(args)
        continue
    for k, v in fill.items():
        w = w.replace(k, v)
    argv.append(w)
if "{dist}" in " ".join(spec["run"]):
    os.makedirs(dist, exist_ok=True)
# What the pack is configured with on this node (R172): the agent writes
# the fields that name an environment variable into the store, owned by
# the session account, and the verb reads them from there; then this
# person's own answers from their home (R172 step 5), which win.
for conf in (os.path.join(os.path.dirname(pack_dir), ".bb", "config", name + ".env"),
             os.path.join(os.path.expanduser("~"), ".bb", "config", name + ".env")):
    try:
        with open(conf, encoding="utf-8") as f:
            for line in f:
                k, sep, v = line.rstrip("\n").partition("=")
                if sep and re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", k):
                    os.environ[k] = v
    except OSError:
        pass
os.execvp(argv[0], argv)
