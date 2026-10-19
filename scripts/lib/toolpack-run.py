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
    for p in packs:
        print(f"  bb tool {p['name']} {'|'.join(sorted(p.get('verbs') or {}))} ...")
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
spec = verbs.get(verb)
if not spec:
    die(f"{name} has no verb {verb}: " + ", ".join(sorted(verbs)) + f" (bb tool {name})")
if not pack_dir:
    die(f"{name} is not installed on this node: the Toolchains page installs it")
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
os.execvp(argv[0], argv)
