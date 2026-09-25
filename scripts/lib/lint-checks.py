"""Behind three of `bb lint`'s own checks (cmd_lint in bb): whether this
project's workflows pin its node's runner, whether an XML file is
well-formed, and whether the container's settings agree across compose,
.env.example, the Unraid template and the README.

The first argument is the check. `runner` takes nodes.py's path and the
project's node, with DASHBOARD_STATE saying where the store is; `xml`
takes the file; `settings` takes nothing and reads the four files from the
current directory. Each prints its lines and exits non-zero on a failure.
"""
import os
import pathlib
import re
import sys
import xml.dom.minidom
import xml.etree.ElementTree as ET
import xml.parsers.expat

import dash

verb, args = sys.argv[1], sys.argv[2:]


def runner():
    nodes = dash.load("nodes", dash.beside(args[0]))
    try:
        nodes.db.open_readonly(os.environ["DASHBOARD_STATE"])
        label = nodes.node_runner_label(args[1])
    except Exception:
        label = ""
    if label:
        # runs-on lines that name self-hosted and NOT this node. A hosted runner
        # (ubuntu-latest) is a deliberate choice and none of this applies to it.
        loose = []
        for f in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
            for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                m = re.match(r"\s*runs-on:\s*(.+?)\s*$", line)
                if not m:
                    continue
                v = m.group(1)
                # An expression is a deliberate choice of runner made at
                # dispatch (the smoke test does exactly this), so it is not a
                # workflow that forgot to pin.
                if "self-hosted" in v and label not in v and "${{" not in v:
                    loose.append(f"{f.name}:{i}")
        if loose:
            print(f"  [note] this project's node is {label}, and "
                  f"{len(loose)} workflow job{'s' if len(loose) > 1 else ''} "
                  f"do{'' if len(loose) > 1 else 'es'} not pin it "
                  f"({', '.join(loose[:6])}{', …' if len(loose) > 6 else ''})")
            print("         their runs-on matches every BuilderBot runner, so GitHub sends the")
            print("         job to whichever is idle, which may be a machine without the")
            print("         toolchain. To land on this project's node:")
            print(f"           runs-on: [self-hosted, {label}]")


def xml_():
    try:
        xml.dom.minidom.parse(args[0])
    except xml.parsers.expat.ExpatError as e:
        raise SystemExit(f'  {e}') from None


def settings():
    compose = open("docker-compose.yml").read()
    # The builderbot service only: the lab's services carry their own.
    svc = compose.split("\n  builderbot:", 1)[1]
    svc = re.split(r"\n  [a-z][a-z0-9_-]*:\s*\n", svc, maxsplit=1)[0]
    env = {}
    for m in re.finditer(r"^\s+([A-Z][A-Z0-9_]+):\s*\$\{([A-Z][A-Z0-9_]+)(?::?-([^}]*))?\}", svc, re.M):
        if m.group(1) == m.group(2):
            env[m.group(1)] = m.group(3) or ""
    example = {}
    for ln in open(".env.example"):
        m = re.match(r"^#?\s*([A-Z][A-Z0-9_]+)=(.*)$", ln.rstrip("\n"))
        if m:
            example[m.group(1)] = m.group(2).strip()
    root = ET.parse("unraid/builderbot.xml").getroot()
    tmpl = {c.get("Target"): c.get("Default") or "" for c in root.iter("Config") if c.get("Type") == "Variable"}
    paths = {c.get("Target"): c.get("Default") or "" for c in root.iter("Config") if c.get("Type") == "Path"}
    # A row may name two at once, `PUID` / `PGID` | `99` / `100`, paired in order.
    readme = {}
    for m in re.finditer(r"^\|\s*((?:`[A-Z][A-Z0-9_]+`(?:\s*/\s*)?)+)\s*\|\s*([^|]*)\|", open("README.md").read(), re.M):
        names = re.findall(r"`([A-Z][A-Z0-9_]+)`", m.group(1))
        defs = [x.strip().strip("`") for x in m.group(2).split(" / ")] if len(names) > 1 else [m.group(2).strip().strip("`")]
        for i, n in enumerate(names):
            readme[n] = defs[i] if i < len(defs) else ""
    bad = []
    for v, d in sorted(env.items()):
        if v not in example:
            bad.append(f"{v} is passed by compose and missing from .env.example")
        elif example[v] != d:
            bad.append(f"{v}: compose defaults to {d!r}, .env.example says {example[v]!r}")
        if v not in tmpl:
            bad.append(f"{v} is passed by compose and missing from the Unraid template")
        elif tmpl[v] != d:
            bad.append(f"{v}: compose defaults to {d!r}, the Unraid template to {tmpl[v]!r}")
        if v not in readme:
            bad.append(f"{v} is passed by compose and missing from the README's reference")
        elif readme[v] != d and not (d == "" and readme[v] in ("*(none)*", "*(empty)*")):
            bad.append(f"{v}: compose defaults to {d!r}, the README to {readme[v]!r}")
    for v in sorted(set(tmpl) - set(env)):
        bad.append(f"{v} is in the Unraid template and compose does not pass it")
    for target, d in sorted(paths.items()):
        m = re.search(r"^\s*#?\s*-\s*\"?(?:\$\{[A-Z_]+:-([^}]*)\}([^:\"]*)|([^:\"$ ]+)):" + re.escape(target) + r"(?::r[ow])?\"?\s*$",
                      svc, re.M)
        if not m:
            continue
        cd = (m.group(1) + m.group(2)) if m.group(1) is not None else m.group(3)
        if d and cd != d:
            bad.append(f"{target}: the Unraid template mounts {d!r}, compose {cd!r}")
    for b in bad:
        print(f"  [FAIL] {b}")
    if not bad:
        print(f"  [ok]   {len(env)} settings and {len(paths)} paths agree across compose, .env.example, the template and the README")
    sys.exit(1 if bad else 0)


{"runner": runner, "xml": xml_, "settings": settings}[verb]()
