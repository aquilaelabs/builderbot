"""Behind three of `bb lint`'s own checks (cmd_lint in bb): whether this
project's workflows pin its node's runner, whether an XML file is
well-formed, and whether the container's settings agree across compose,
.env.example, the Unraid template and docs/reference.md.

The first argument is the check. `runner` takes nodes.py's path and the
project's node, with DASHBOARD_STATE saying where the store is; `xml`
takes the file; `settings` takes nothing and reads the four files from the
current directory. Each prints its lines and exits non-zero on a failure.
"""
import os
import pathlib
import re
import sys
# The XML read here is this repository's own (the Unraid template, the
# workflows): no input from outside, so defusedxml would guard nothing.
import xml.dom.minidom  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
import xml.etree.ElementTree as ET  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml
import xml.parsers.expat  # nosemgrep: python.lang.security.use-defused-xml.use-defused-xml

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


# A hosted runner named by a moving label: GitHub repoints ubuntu-latest at a
# new release on its own date (Ubuntu 26 from 19 Oct 2026), and a workflow
# that built yesterday fails tomorrow with nothing in the repository changed.
# A pinned image moves only when somebody moves it, in a commit (R116).
PINNED = {"ubuntu": "ubuntu-24.04", "windows": "windows-2025", "macos": "macos-15"}


def hosted():
    strict = "--strict" in args
    found = []
    for f in sorted(pathlib.Path(".github/workflows").glob("*.y*ml")):
        for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            m = re.match(r"\s*runs-on:\s*(.+?)\s*(#.*)?$", line)
            if not m or "${{" in m.group(1):
                continue
            for os_ in re.findall(r"\b(ubuntu|windows|macos)-latest\b", m.group(1)):
                found.append((f"{f.name}:{i}", f"{os_}-latest", PINNED[os_]))
    if not found:
        print("  [ok]   every hosted job names a pinned image")
        sys.exit(0)
    tag = "[FAIL]" if strict else "[note]"
    for where, label, pin in found:
        print(f"  {tag} {where} runs on {label}, which GitHub moves to a new release on its own date;"
              f" runs-on: {pin} moves only when a commit moves it")
    sys.exit(1 if strict else 0)


def xml_():
    try:
        xml.dom.minidom.parse(args[0])
    except xml.parsers.expat.ExpatError as e:
        raise SystemExit(f'  {e}') from None


def layout():
    """docs/layout.md names every tracked file (R91): a row is a path, a
    directory (which covers what is under it only when nothing beneath it
    is listed) or a glob, and a tracked file no row names fails. A tree
    that grows a module the page does not name is a newcomer's dead end."""
    import fnmatch
    import subprocess
    try:
        lay = open("docs/layout.md", encoding="utf-8").read().split("```")[1].splitlines()
    except (OSError, IndexError):
        print("  [FAIL] docs/layout.md has no code block to read")
        return 1
    rows, stack = [], []
    for ln in lay:
        m = re.match(r"^(\s*)([A-Za-z0-9_.\-/*]+)", ln)
        if not m or not ln.strip():
            continue
        ind, tok = len(m.group(1)), m.group(2)
        while stack and stack[-1][0] >= ind:
            stack.pop()
        path = (stack[-1][1] if stack else "") + tok
        if tok.endswith("/"):
            stack.append((ind, path))
        rows.append(path)
    leaf_dirs = {r for r in rows if r.endswith("/") and not any(x != r and x.startswith(r) for x in rows)}
    tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=False).stdout.split()
    if not tracked:
        print("  [skip] not a git checkout, so nothing to hold the page to")
        return 0

    def named(f):
        return any(r == f or (r in leaf_dirs and f.startswith(r)) or ("*" in r and fnmatch.fnmatch(f, r))
                   for r in rows)
    miss = [f for f in tracked if not named(f)]
    if miss:
        print(f"  [FAIL] {len(miss)} tracked file(s) docs/layout.md does not name: " + " ".join(miss[:12])
              + (" ..." if len(miss) > 12 else ""))
        return 1
    print(f"  [ok]   docs/layout.md names every one of the {len(tracked)} tracked files")
    return 0


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
    for m in re.finditer(r"^\|\s*((?:`[A-Z][A-Z0-9_]+`(?:\s*/\s*)?)+)\s*\|\s*([^|]*)\|", open("docs/reference.md").read(), re.M):
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
            bad.append(f"{v} is passed by compose and missing from docs/reference.md")
        elif readme[v] != d and not (d == "" and readme[v] in ("*(none)*", "*(empty)*")):
            bad.append(f"{v}: compose defaults to {d!r}, docs/reference.md to {readme[v]!r}")
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
        print(f"  [ok]   {len(env)} settings and {len(paths)} paths agree across compose, .env.example, the template and the reference")
    sys.exit(1 if bad else 0)


def _words(text):
    return re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower())


def _shingles(text, n=8):
    w = _words(text)
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


# History in an instruction: a date, a bug or roadmap number of two digits
# or more (R4 and B7 are the examples the verbs are shown with), "bug 13",
# or an attribution to the operator. The why lives in docs/decisions.md
# and bb rules show; the prompt carries the instruction.
HISTORY = re.compile(r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b"
                     r"|\b[BR]\d{2,4}\b|\b(?:bug|roadmap|issue) #?\d+\b|\(the operator,|\bthe operator, \d")
SHINGLE = 8


def channels():
    """CLAUDE.md describes the tree, the briefing the machine and the shipped
    rules the obligations (R202): a sentence CLAUDE.md shares with the
    briefing or a shipped rule reaches every session twice, and history in
    either is paid for on every conversation."""
    bad = []
    claude = open("CLAUDE.md").read()
    brief = re.sub(r"<!--.*?-->", "", open("config/templates/briefing.md").read(), flags=re.S)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard"))
    import rules                                                    # noqa: E402
    sources = [("the briefing", brief)] + [(f"the shipped rule {r['name']}", r["text"])
                                           for r in rules.BUILTIN + rules.ALWAYS]
    said = {}
    for name, text in sources:
        for s in _shingles(text):
            said.setdefault(s, name)
    seen = set()
    for i, line in enumerate(claude.split("\n"), 1):
        for s in _shingles(line):
            if s in said and i not in seen:
                seen.add(i)
                bad.append(f"CLAUDE.md:{i} says what {said[s]} says: \"{s}...\"")
                break
    for path, text in (("CLAUDE.md", claude), ("config/templates/briefing.md", brief)):
        for i, line in enumerate(text.split("\n"), 1):
            m = HISTORY.search(line)
            if m:
                bad.append(f"{path}:{i} carries history in an instruction ({m.group(0)!r}): it belongs in docs/decisions.md or a rule's why")
    for b in bad:
        print(f"  [FAIL] {b}")
    if not bad:
        print("  [ok]   CLAUDE.md, the briefing and the shipped rules each say their own, with no history in the prompt")
    sys.exit(1 if bad else 0)


{"runner": runner, "xml": xml_, "settings": settings, "layout": layout, "hosted": hosted,
 "channels": channels}[verb]()
