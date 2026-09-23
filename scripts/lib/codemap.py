#!/usr/bin/env python3
"""bb map: a code map a session asks instead of grepping (roadmap R75).

One index over a project tree: every function a file defines, every call
by name with the function it was made from, every element id and class a
function's markup draws, and which test suite names each of those. Built
from the files themselves with nothing installed: python's own parser for
the .py files, a small scanner for the scripts (index.html's inline
script, tab-*.js, nb-*.js, test/*.mjs) and a line pass for shell.

    bb map                       what is indexed, and the verbs
    bb map find NAME             where NAME is defined
    bb map who-calls NAME        every call of NAME, with the caller
    bb map calls NAME            what NAME calls
    bb map defs FILE             the definitions in one file, nested shown
    bb map draws ID|.class       which functions draw it, which suites name it
    bb map suites FILE...        the suites that name what these files define or draw
    bb map build                 rebuild now (it rebuilds itself when a source is newer)

The scanner is deliberately rough: it knows nothing of scope beyond braces
and nothing of types. It answers "where would I look" in one call, which
is the question a session otherwise spends thirty greps on, and it says so
in its output where it is guessing (an anonymous callback is attributed to
the nearest named function around it).

The index lives at .bb-map/index.json under the tree, ignored by git.
"""
import ast
import json
import os
import re
import sys
import time
from pathlib import Path

INDEX_DIR = ".bb-map"
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".bb-map", "scratchpad",
             "_work", "build", ".gradle", ".idea", "venv", ".venv"}
EXTS = {".py": "py", ".js": "js", ".mjs": "js", ".html": "html", ".sh": "sh"}
MAX_BYTES = 3_000_000

JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof",
               "else", "do", "try", "finally", "throw", "case", "default", "delete",
               "void", "in", "of", "instanceof", "await", "yield", "with", "class",
               "const", "let", "var", "async", "new", "import", "export"}


# ---- the scanners ---------------------------------------------------------

class Sink:
    """Where a scanner puts what it finds, for one file."""

    def __init__(self, path):
        self.path = path
        self.defs = []      # {name, line, end, kind, parent}
        self.calls = []     # {name, qual, line, caller}
        self.draws = []     # {what, kind: id|class, line, fn}

    def add_def(self, name, line, kind, parent):
        self.defs.append({"name": name, "file": self.path, "line": line, "end": line,
                          "kind": kind, "parent": parent})
        return self.defs[-1]

    def add_call(self, name, qual, line, caller):
        self.calls.append({"name": name, "qual": qual, "file": self.path, "line": line,
                           "caller": caller})

    def add_draw(self, what, kind, line, fn):
        self.draws.append({"what": what, "kind": kind, "file": self.path, "line": line,
                           "fn": fn})


def scan_python(text, sink):
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        sink.add_def(f"(unparsable: {e.msg} at line {e.lineno})", e.lineno or 1, "error", "")
        return
    stack = []

    def enclosing():
        return stack[-1] if stack else "(module)"

    def walk(node, parent_name):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                kind = "class" if isinstance(child, ast.ClassDef) else "def"
                d = sink.add_def(child.name, child.lineno, kind, parent_name)
                d["end"] = getattr(child, "end_lineno", child.lineno)
                stack.append(child.name if not parent_name or kind == "class"
                             else f"{parent_name}.{child.name}")
                walk(child, child.name if kind == "class" else stack[-1])
                stack.pop()
                continue
            if isinstance(child, ast.Call):
                f = child.func
                if isinstance(f, ast.Name):
                    sink.add_call(f.id, "", child.lineno, enclosing())
                elif isinstance(f, ast.Attribute):
                    qual = f.value.id if isinstance(f.value, ast.Name) else ""
                    sink.add_call(f.attr, qual, child.lineno, enclosing())
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                for what, kind in strings_draw(child.value):
                    sink.add_draw(what, kind, child.lineno, enclosing())
            walk(child, parent_name)

    walk(tree, "")


ATTR_ID = re.compile(r"""\bid=["']([A-Za-z][\w:-]*)["']""")
ATTR_CLASS = re.compile(r"""\bclass=["']([^"']+)["']""")
SEL = re.compile(r"""(?<![\w$])([#.])([A-Za-z_][\w-]*)""")
HANDLER = re.compile(r"""\bon[a-z]+=["']\s*([A-Za-z_$][\w$]*)\s*\(""")


def strings_draw(s):
    """The element ids and classes a string carries: markup attributes, and
    the #id / .class of a selector. Only for strings that look like either,
    so a sentence with a full stop in it does not become a class."""
    out = []
    for m in ATTR_ID.finditer(s):
        out.append((m.group(1), "id"))
    for m in ATTR_CLASS.finditer(s):
        for c in m.group(1).split():
            if c.isidentifier() or "-" in c:
                out.append((c.strip(), "class"))
    if "<" not in s and len(s) < 200 and re.match(r"^[\s\w#.\[\]=\"':>,()*+~^$|-]+$", s):
        for m in SEL.finditer(s):
            what = m.group(2)
            if m.group(1) == "#" and re.match(r"^[A-Za-z]", what):
                out.append((what, "id"))
            elif m.group(1) == "." and re.match(r"^[A-Za-z]", what) and not what.isdigit():
                out.append((what, "class"))
    return out


class JSScanner:
    """Comments dropped, strings kept apart from code, braces counted: enough
    to know which function a call or a piece of markup sits in."""

    IDENT = re.compile(r"[A-Za-z_$][\w$]*")
    REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")

    def __init__(self, text, sink, line0=1, top="(top level)"):
        self.s = text
        self.sink = sink
        self.line = line0
        self.top = top
        self.i = 0
        self.depth = 0
        self.stack = []          # [(name, depth of its body brace)]
        self.pending = None      # a definition header seen, waiting for its {
        self.pending_depth = 0
        self.last_sig = ""       # last significant token text
        self.last_ident = ""     # last identifier token, for  name(  and  x = function
        self.prev_ident = ""
        self.last_kw = ""
        self.parens = 0
        self.paren_at_pending = 0
        self.maybe_method = None

    def enclosing(self):
        return self.stack[-1][0] if self.stack else self.top

    def run(self):
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c == "\n":
                self.line += 1
                self.i += 1
                continue
            if c in " \t\r":
                self.i += 1
                continue
            two = s[self.i:self.i + 2]
            if two == "//":
                j = s.find("\n", self.i)
                self.i = n if j < 0 else j
                continue
            if two == "/*":
                j = s.find("*/", self.i + 2)
                j = n if j < 0 else j + 2
                self.line += s.count("\n", self.i, j)
                self.i = j
                continue
            if c in "'\"":
                self.string(c)
                continue
            if c == "`":
                self.template()
                continue
            if c == "/" and self.regex_allowed():
                self.regex()
                continue
            m = self.IDENT.match(s, self.i)
            if m:
                self.ident(m.group(0))
                self.i = m.end()
                continue
            self.punct(c)
            self.i += 1

    # -- pieces --------------------------------------------------------------
    def regex_allowed(self):
        if not self.last_sig:
            return True
        if self.last_sig in ("return", "typeof", "case", "=>"):
            return True
        return self.last_sig[-1] in self.REGEX_BEFORE

    def regex(self):
        s, n = self.s, len(self.s)
        j = self.i + 1
        in_class = False
        while j < n and s[j] != "\n":
            if s[j] == "\\":
                j += 2
                continue
            if s[j] == "[":
                in_class = True
            elif s[j] == "]":
                in_class = False
            elif s[j] == "/" and not in_class:
                break
            j += 1
        self.i = j + 1
        while self.i < n and s[self.i].isalpha():
            self.i += 1
        self.last_sig = "/re/"

    def string(self, q):
        s, n = self.s, len(self.s)
        j = self.i + 1
        while j < n and s[j] != q and s[j] != "\n":
            if s[j] == "\\":
                j += 1
            j += 1
        body = s[self.i + 1:j]
        self.saw_string(body, self.line)
        self.i = min(j + 1, n)
        self.last_sig = "'s'"

    def template(self):
        s, n = self.s, len(self.s)
        j = self.i + 1
        chunk = []
        start_line = self.line
        while j < n:
            c = s[j]
            if c == "\\":
                chunk.append(s[j:j + 2])
                j += 2
                continue
            if c == "`":
                break
            if s[j:j + 2] == "${":
                self.saw_string("".join(chunk), start_line)
                chunk = []
                # the expression inside, scanned as code by a nested pass
                k, depth = j + 2, 1
                while k < n and depth:
                    if s[k] == "{":
                        depth += 1
                    elif s[k] == "}":
                        depth -= 1
                    elif s[k] == "`":
                        # a nested template: skip it whole (simple form)
                        k2 = s.find("`", k + 1)
                        k = n if k2 < 0 else k2
                    k += 1
                inner = s[j + 2:k - 1]
                sub = JSScanner(inner, self.sink, self.line, self.enclosing())
                sub.stack = list(self.stack)
                sub.run()
                self.line += inner.count("\n")
                j = k
                start_line = self.line
                continue
            if c == "\n":
                self.line += 1
            chunk.append(c)
            j += 1
        self.saw_string("".join(chunk), start_line)
        self.i = min(j + 1, n)
        self.last_sig = "'s'"

    def saw_string(self, body, line):
        fn = self.enclosing()
        for what, kind in strings_draw(body):
            self.sink.add_draw(what, kind, line, fn)
        for m in HANDLER.finditer(body):
            self.sink.add_call(m.group(1), "", line, fn)

    def ident(self, word):
        self.prev_ident, self.last_ident = self.last_ident, word
        if word in ("function", "class"):
            self.last_kw = word
        elif word == "async":
            pass
        else:
            if self.last_kw == "function" and word not in JS_KEYWORDS:
                # function NAME(
                self.begin_def(word, "function")
                self.last_kw = ""
            elif self.last_kw == "class" and word not in JS_KEYWORDS:
                self.begin_def(word, "class")
                self.last_kw = ""
            elif word not in JS_KEYWORDS and word not in ("function", "class"):
                self.last_kw = ""
        self.last_sig = word

    def begin_def(self, name, kind):
        if self.stack and self.stack[-1][1] == self.depth and self.pending is None:
            parent = self.stack[-1][0]
        else:
            parent = self.enclosing() if self.stack else ""
        d = self.sink.add_def(name, self.line, kind, "" if parent == self.top else parent)
        self.pending = d
        self.pending_depth = self.depth

    def punct(self, c):
        s = self.s
        if c == "(":
            prev = self.last_sig
            if self.pending is not None and self.pending["name"] == prev \
                    and self.pending["line"] == self.line:
                # the ( of a definition's own parameter list, not a call
                self.maybe_method = None
                self.paren_at_pending = self.parens
                self.parens += 1
                self.last_sig = "("
                return
            if self.IDENT.fullmatch(prev or "") and prev not in JS_KEYWORDS \
                    and self.last_kw != "function":
                # NAME( : a call, unless it is a method definition   name(...){
                before = s[max(0, self.i - 240):self.i].rstrip()
                head = before[:-len(prev)].rstrip()
                if head.endswith(("{", ",", ";", "}")) or head.endswith("\n") or not head:
                    # possibly an object/class method: decided at the ) {
                    self.maybe_method = (prev, self.line)
                else:
                    self.maybe_method = None
                qual = ""
                if head.endswith("."):
                    qm = re.search(r"([A-Za-z_$][\w$]*)\s*\.$", head)
                    qual = qm.group(1) if qm else ""
                self.sink.add_call(prev, qual, self.line, self.enclosing())
            elif prev == "function" or prev == "async":
                # an anonymous function: `function(` or `async (`; body follows
                self.pending = self.sink.add_def("(anonymous)", self.line, "function", "")
                self.pending_depth = self.depth
                self.pending_anon = True
            else:
                self.maybe_method = None
            self.parens += 1
            self.last_sig = "("
            return
        if c == ")":
            self.parens = max(0, self.parens - 1)
            self.last_sig = ")"
            return
        if c == "{":
            if self.pending is not None:
                self.stack.append((self.pending["name"], self.depth))
                self.pending["body"] = self.depth
                self.pending = None
            elif self.last_sig == "=>":
                # an arrow body: attributed to what it was assigned to, if
                # that was `NAME = ... =>`; else it stays with the enclosing
                name = self.arrow_name()
                if name:
                    d = self.sink.add_def(name, self.line, "arrow", self.enclosing_or_blank())
                    self.stack.append((name, self.depth))
                    d["body"] = self.depth
                else:
                    self.stack.append((self.enclosing(), self.depth))
            elif self.last_sig == ")" and getattr(self, "maybe_method", None):
                name, line = self.maybe_method
                self.stack.append((name, self.depth))
                d = self.sink.add_def(name, line, "method", self.enclosing_or_blank(1))
                d["body"] = self.depth
                # the call recorded for `name(` was the header, not a call
                for cl in reversed(self.sink.calls):
                    if cl["name"] == name and cl["line"] == line:
                        self.sink.calls.remove(cl)
                        break
            self.maybe_method = None
            self.depth += 1
            self.last_sig = "{"
            return
        if c == "}":
            self.depth -= 1
            while self.stack and self.stack[-1][1] >= self.depth:
                name, _ = self.stack.pop()
                for d in reversed(self.sink.defs):
                    if d["name"] == name and d.get("body") == self.depth and d["end"] == d["line"]:
                        d["end"] = self.line
                        break
            self.last_sig = "}"
            return
        if c == "=" and s[self.i:self.i + 2] == "=>":
            self.i += 1
            self.last_sig = "=>"
            return
        if c in ";,":
            # A definition header still waiting for its body is dropped by a
            # `;` at its own level, or a `,` outside its parameter list: the
            # commas INSIDE the list used to drop it, which is every function
            # with two parameters, and their bodies then read as top level.
            if self.pending is not None and self.pending_depth == self.depth \
                    and (c == ";" or self.parens <= getattr(self, "paren_at_pending", 0)):
                self.pending = None
            self.last_sig = c
            return
        self.last_sig = c

    def enclosing_or_blank(self, up=0):
        st = self.stack[:-up] if up else self.stack
        return st[-1][0] if st else ""

    def arrow_name(self):
        # `const NAME = (...) =>` or `NAME = async x =>` : the identifier
        # before the `=` that precedes the arrow's parameters, on this line
        # or the one before.
        head = self.s[max(0, self.i - 200):self.i]
        m = re.search(r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*=>\s*$", head)
        if m and m.group(1) not in JS_KEYWORDS:
            return m.group(1)
        # `name: (...) =>` in an object
        m = re.search(r"([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*=>\s*$", head)
        if m:
            return m.group(1)
        return ""


def scan_js(text, sink, line0=1):
    JSScanner(text, sink, line0).run()


SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)


def scan_html(text, sink):
    pos = 0
    for m in SCRIPT.finditer(text):
        markup = text[pos:m.start()]
        markup_draws(markup, sink, text.count("\n", 0, pos) + 1)
        line0 = text.count("\n", 0, m.start(1)) + 1
        scan_js(m.group(1), sink, line0)
        pos = m.end()
    markup_draws(text[pos:], sink, text.count("\n", 0, pos) + 1)


def markup_draws(markup, sink, line0):
    for ln, line in enumerate(markup.split("\n"), line0):
        for what, kind in strings_draw(line):
            sink.add_draw(what, kind, ln, "(markup)")


SH_DEF = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{")


def scan_sh(text, sink):
    lines = text.split("\n")
    names = {m.group(1): i + 1 for i, ln in enumerate(lines) if (m := SH_DEF.match(ln))}
    cur = "(top level)"
    word = re.compile(r"(?<![\w./-])([A-Za-z_][\w-]*)(?![\w-])")
    for i, ln in enumerate(lines, 1):
        m = SH_DEF.match(ln)
        if m:
            cur = m.group(1)
            sink.add_def(cur, i, "function", "")
            continue
        if ln.startswith("}") and cur != "(top level)":
            for d in reversed(sink.defs):
                if d["name"] == cur:
                    d["end"] = i
                    break
            cur = "(top level)"
            continue
        code = ln.split("#", 1)[0] if not ln.lstrip().startswith("#") else ""
        for w in word.finditer(code):
            if w.group(1) in names and w.group(1) != cur:
                sink.add_call(w.group(1), "", i, cur)


# ---- the index ------------------------------------------------------------

def sources(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            p = Path(dp) / fn
            lang = EXTS.get(p.suffix)
            if lang is None and not p.suffix:
                try:
                    with open(p, "rb") as f:
                        head = f.read(64)
                    if head.startswith(b"#!") and (b"bash" in head or b"sh\n" in head[:24]):
                        lang = "sh"
                    elif head.startswith(b"#!") and b"python" in head:
                        lang = "py"
                except OSError:
                    continue
            if lang is None:
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            yield p, lang


def build(root):
    root = Path(root)
    idx = {"built": time.time(), "root": str(root), "files": {}, "defs": [], "calls": [],
           "draws": []}
    for p, lang in sources(root):
        rel = str(p.relative_to(root))
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        sink = Sink(rel)
        try:
            {"py": scan_python, "js": scan_js, "html": scan_html, "sh": scan_sh}[lang](text, sink)
        except Exception as e:      # a scanner must never take the map down
            sink.add_def(f"(scan failed: {e})", 1, "error", "")
        idx["files"][rel] = {"mtime": p.stat().st_mtime, "lang": lang}
        for d in sink.defs:
            d.pop("body", None)
        idx["defs"] += sink.defs
        idx["calls"] += sink.calls
        idx["draws"] += sink.draws
    out = root / INDEX_DIR
    out.mkdir(exist_ok=True)
    tmp = out / "index.json.tmp"
    tmp.write_text(json.dumps(idx))
    tmp.replace(out / "index.json")
    return idx


def load(root, force=False):
    root = Path(root)
    f = root / INDEX_DIR / "index.json"
    if force or not f.exists():
        return build(root)
    try:
        idx = json.loads(f.read_text())
    except (OSError, ValueError):
        return build(root)
    have = idx.get("files", {})
    now = {str(p.relative_to(root)): p.stat().st_mtime for p, _ in sources(root)}
    if set(now) != set(have) or any(now[k] > have[k]["mtime"] for k in now):
        return build(root)
    return idx


# ---- the questions ----------------------------------------------------------

def is_test(path):
    return "/test/" in "/" + path or path.startswith("test/")


_LINES = {}


def line_of(root, path, n):
    if path not in _LINES:
        try:
            _LINES[path] = (Path(root) / path).read_text(errors="replace").split("\n")
        except OSError:
            _LINES[path] = []
    lines = _LINES[path]
    return lines[n - 1].strip()[:110] if 0 < n <= len(lines) else ""


def q_find(idx, name):
    rows = [d for d in idx["defs"] if d["name"] == name]
    if not rows:
        return [f"nothing defines {name}"]
    out = []
    for d in rows:
        where = f"{d['file']}:{d['line']}"
        span = f" to {d['end']}" if d["end"] > d["line"] else ""
        parent = f"  in {d['parent']}" if d["parent"] else ""
        out.append(f"{where}{span}  {d['kind']}{parent}")
    return out


def q_who_calls(idx, name, root):
    qual = ""
    if "." in name:
        qual, name = name.rsplit(".", 1)
    rows = [c for c in idx["calls"] if c["name"] == name and (not qual or c["qual"] == qual)]
    if not rows:
        return [f"nothing calls {name}" + (f" on {qual}" if qual else "")]
    out = []
    for c in sorted(rows, key=lambda c: (is_test(c["file"]), c["file"], c["line"])):
        tag = "test " if is_test(c["file"]) else ""
        out.append(f"{tag}{c['file']}:{c['line']}  from {c['caller']}  | {line_of(root, c['file'], c['line'])}")
    return out


def q_calls(idx, name):
    rows = [c for c in idx["calls"] if c["caller"] == name or c["caller"].endswith("." + name)]
    if not rows:
        return [f"{name} calls nothing the map knows, or is not a function it knows"]
    seen, out = set(), []
    for c in sorted(rows, key=lambda c: (c["file"], c["line"])):
        key = (c["qual"], c["name"])
        if key in seen:
            continue
        seen.add(key)
        full = f"{c['qual']}.{c['name']}" if c["qual"] else c["name"]
        defined = any(d["name"] == c["name"] for d in idx["defs"])
        out.append(f"{full}  ({c['file']}:{c['line']})" + ("" if defined else "  [not defined in the tree]"))
    return out


def q_defs(idx, path):
    rows = [d for d in idx["defs"] if d["file"] == path or d["file"].endswith("/" + path)]
    if not rows:
        return [f"no definitions in {path} (is it indexed? bb map lists the languages)"]
    out = []
    for d in sorted(rows, key=lambda d: d["line"]):
        if d["name"] == "(anonymous)":
            continue
        indent = "  " if d["parent"] else ""
        span = f"-{d['end']}" if d["end"] > d["line"] else ""
        out.append(f"{indent}{d['line']}{span}  {d['kind']} {d['name']}" + (f"  (in {d['parent']})" if d["parent"] else ""))
    return out


def q_draws(idx, what):
    kind = "class" if what.startswith(".") else "id"
    what = what.lstrip("#.")
    rows = [d for d in idx["draws"] if d["what"] == what and d["kind"] == kind]
    if not rows:
        return [f"nothing draws or names {'.' if kind == 'class' else '#'}{what}"]
    drawn, named = {}, {}
    for d in rows:
        (named if is_test(d["file"]) else drawn).setdefault((d["file"], d["fn"]), []).append(d["line"])
    out = []
    for (f, fn), lines in sorted(drawn.items()):
        out.append(f"{f}  {fn}  (line {', '.join(map(str, lines[:6]))}{', ...' if len(lines) > 6 else ''})")
    by_file = {}
    for (f, _fn), lines in named.items():
        by_file[f] = by_file.get(f, 0) + len(lines)
    for f, n in sorted(by_file.items()):
        out.append(f"test {f}  ({n} place{'s' if n > 1 else ''})")
    return out


def q_suites(idx, paths):
    """The suites that name anything these files define or draw: the map's
    half of a preflight (R75 step 3)."""
    files = set()
    for p in paths:
        files |= {f for f in idx["files"] if f == p or f.endswith("/" + p)}
    if not files:
        return ["none of those files is indexed"]
    names = {d["name"] for d in idx["defs"] if d["file"] in files and not d["name"].startswith("(")}
    things = {(d["what"], d["kind"]) for d in idx["draws"] if d["file"] in files}
    hits = {}
    for d in idx["draws"]:
        if is_test(d["file"]) and (d["what"], d["kind"]) in things:
            hits.setdefault(d["file"], set()).add(("." if d["kind"] == "class" else "#") + d["what"])
    for c in idx["calls"]:
        if is_test(c["file"]) and c["name"] in names:
            hits.setdefault(c["file"], set()).add(c["name"] + "()")
    if not hits:
        return ["no suite names anything these files define or draw"]
    out = []
    for f, why in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        w = sorted(why)
        out.append(f"{f}  ({len(w)}: {', '.join(w[:5])}{', ...' if len(w) > 5 else ''})")
    return out


def summary(idx):
    langs = {}
    for f in idx["files"].values():
        langs[f["lang"]] = langs.get(f["lang"], 0) + 1
    n_test = sum(1 for f in idx["files"] if is_test(f))
    return [f"{len(idx['files'])} files ({', '.join(f'{n} {k}' for k, n in sorted(langs.items()))}; {n_test} test suites), "
            f"{len(idx['defs'])} definitions, {len(idx['calls'])} calls, {len(idx['draws'])} ids and classes drawn",
            f"built {time.strftime('%d %b %H:%M', time.localtime(idx['built']))} into {INDEX_DIR}/index.json; rebuilt by itself when a source is newer",
            "",
            "bb map find NAME | who-calls NAME | calls NAME | defs FILE | draws ID|.class | suites FILE... | build"]


def main(argv):
    root = os.environ.get("BB_TREE") or os.getcwd()
    args = list(argv)
    if args[:1] == ["--root"]:
        root = args[1]
        args = args[2:]
    verb = args[0] if args else ""
    rest = args[1:]
    if verb in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    if verb == "build":
        idx = build(root)
        print("\n".join(summary(idx)))
        return 0
    idx = load(root)
    if not verb:
        print("\n".join(summary(idx)))
        return 0
    need = {"find": 1, "who-calls": 1, "calls": 1, "defs": 1, "draws": 1, "suites": 1}
    if verb not in need:
        print(f"bb map: no verb called {verb}; bb map -h lists them", file=sys.stderr)
        return 2
    if len(rest) < need[verb]:
        print(f"bb map {verb} needs an argument; bb map -h", file=sys.stderr)
        return 2
    if verb == "find":
        lines = q_find(idx, rest[0])
    elif verb == "who-calls":
        lines = q_who_calls(idx, rest[0], root)
    elif verb == "calls":
        lines = q_calls(idx, rest[0])
    elif verb == "defs":
        lines = q_defs(idx, rest[0])
    elif verb == "draws":
        lines = q_draws(idx, rest[0])
    else:
        lines = q_suites(idx, rest)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
