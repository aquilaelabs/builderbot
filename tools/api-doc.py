#!/usr/bin/env python3
"""docs/api.md, written from server.py (R91 step 7): every /api/ path in the
two route tables, its method and how it is matched, the first sentence of
its handler's docstring, and the permissions the handler refuses on. Read
with ast rather than by running the server, so a route that is added and
not described shows up as a row with no words, which bb lint's check turns
into a failure by holding the page equal to this output. --check compares
and says what differs."""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "scripts" / "dashboard" / "server.py"
OUT = ROOT / "docs" / "api.md"


def routes(tree, name):
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            for el in node.value.elts:
                how, path, fn = (ast.literal_eval(e) for e in el.elts)
                yield how, path, fn


def handlers(tree):
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Handler":
            for fn in node.body:
                if isinstance(fn, ast.FunctionDef):
                    out[fn.name] = fn
    return out


def first_sentence(fn):
    doc = ast.get_docstring(fn) or ""
    doc = " ".join(doc.split())
    m = re.match(r"(.{0,220}?[.!?])(\s|$)", doc)
    return m.group(1) if m else doc[:220]


def refusals(fn):
    seen = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("_refused", "_readonly", "_not_project") and node.args \
                and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            seen.append(f"{node.func.attr[1:]}: {node.args[0].value}" if node.func.attr == "_refused"
                        else node.func.attr[1:])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("_readonly", "_not_project") and not node.args:
            seen.append(node.func.attr[1:])
    out = []
    for s in seen:
        if s not in out:
            out.append(s)
    return out


def render():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fns = handlers(tree)
    lines = ["# The dashboard's API", "",
             "Written from `scripts/dashboard/server.py` by `tools/api-doc.py`; `bb lint` holds this page equal to it.",
             "Every request carries the account's credential (a session's token, or the person's cookie or",
             "basic auth); who may call what is decided in the handler, and the last column names the",
             "permission a handler refuses on (`refused: NAME`), or that it refuses a locked project",
             "(`readonly`) or a name that is not a project the account sees (`not_project`). A `prefix`",
             "route takes every path it prefixes, in the order listed; an `exact` one takes its path alone.",
             "The companion app's own contract is `android/api-surface.json`.", "",
             "| Method | Path | Match | Handler | What it does | Refuses on |", "|---|---|---|---|---|---|"]
    for method, table in (("GET", "GET_ROUTES"), ("POST", "POST_ROUTES")):
        for how, path, fn in routes(tree, table):
            f = fns.get(fn)
            words = first_sentence(f) if f else "(no handler by that name)"
            gates = ", ".join(refusals(f)) if f else ""
            lines.append(f"| {method} | `{path}` | {how} | `{fn}` | {words.replace('|', '\\\\|')} | {gates} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        have = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if have == text:
            print(f"  [ok]   docs/api.md is server.py's {text.count(chr(10)) - 12} routes, word for word")
            sys.exit(0)
        print("  [FAIL] docs/api.md differs from server.py's routes: tools/api-doc.py rewrites it")
        sys.exit(1)
    if "--print" in sys.argv:
        sys.stdout.write(text)
    else:
        OUT.write_text(text, encoding="utf-8")
        print(f"docs/api.md: {text.count(chr(10)) - 12} routes")
