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
    bb map who-calls NAME        every call of NAME, with the caller, and every place NAME is
                                 passed by name without a call (handed to a draw, assigned, listed)
    bb map calls NAME            what NAME calls
    bb map defs FILE             the definitions in one file, nested shown
    bb map draws ID|.class       which functions draw it, which suites name it
    bb map suites FILE...        the suites that reach what these files define, draw or name
                                 (--names: one suite name per line, for a script)
    bb map unused [FILE]         page functions nothing calls and nothing passes by name: dead by measurement
    bb map state [FILE]          the page-level `let`s of a page script (all of them with no FILE), each
                                 with where it is assigned and from what: one assigned from `state`
                                 mirrors the poll and drifts from it, which is what to read instead
    bb map addresses [FILE...]   the `file ~line` addresses in these texts (the roadmap on stdin with
                                 no FILE), each checked against where the name beside it is now:
                                 a plan keeps its words and its addresses move under it
    bb map sections FILE         the file by its `// ---- name ----` sections: functions, who reaches in
                                 from outside, what runs at load, what the suite covers. The unit a
                                 cleanup moves.
    bb map coverage              what the last covered run reached, per file (bb tests coverage runs one)
    bb map covered NAME          which suites ran NAME, and how often: the regression net for touching it
    bb map uncovered [FILE]      the functions no suite reached
    bb map build                 rescan everything now (a changed file is rescanned by itself on any question)

The scanner is deliberately rough: it knows nothing of scope beyond braces
and nothing of types. It answers "where would I look" in one call, which
is the question a session otherwise spends thirty greps on, and it says so
in its output where it is guessing (an anonymous callback is attributed to
the nearest named function around it).

The index lives at .bb-map/map2.json under the tree, ignored by git.
"""
import ast
import json
import os
import re
import sys
import time
from pathlib import Path

INDEX_DIR = ".bb-map"
# The index file carries its format, and a reader that meets another
# format rebuilds rather than reads: the first map read a newer per-file
# index as its own flat one and every question raised a KeyError, on the
# bb a session runs while the controller's build lagged the tree. The file
# is named for the format too, so two bb builds on one tree keep to their
# own files during the window when both exist.
FORMAT = 3
INDEX_FILE = f"map{FORMAT}.json"
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", ".bb-map", "scratchpad",
             "_work", "build", ".gradle", ".idea", "venv", ".venv"}
# The brace-counting scanner covers every C-shaped language: what differs
# is the word that opens a function (`fun`, `func`, `fn`, `function`) or
# none at all (Java, C#, Dart, C, where `name(...) {` after a type is the
# definition), which is what the scanner already spots for a JS method.
EXTS = {".py": "py", ".js": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
        ".jsx": "js", ".html": "html", ".sh": "sh", ".bash": "sh",
        ".kt": "js", ".kts": "js", ".java": "js", ".cs": "js", ".go": "js", ".rs": "js",
        ".swift": "js", ".dart": "js", ".c": "js", ".h": "js", ".cc": "js", ".cpp": "js",
        ".hpp": "js", ".m": "js", ".mm": "js", ".php": "js", ".scala": "js", ".groovy": "js"}
# The words that open a function or a type in those languages. `def` is
# not here: python has its own parser, and Ruby's `def ... end` has no
# braces to count, so Ruby is not indexed (the one common language that
# is not).
FN_WORDS = {"function", "fun", "func", "fn"}
# ...per language, because `fn` is an ordinary parameter name in JavaScript
# and `func` a variable in Kotlin: a word opens a function only where its
# language says so.
FN_BY_SUFFIX = {".rs": {"fn"}, ".go": {"func"}, ".kt": {"fun"}, ".kts": {"fun"},
                ".swift": {"func"}, ".scala": {"def"}, ".php": {"function"},
                ".js": {"function"}, ".mjs": {"function"}, ".cjs": {"function"},
                ".ts": {"function"}, ".tsx": {"function"}, ".jsx": {"function"},
                ".html": {"function"}}
# Where `name(...) {` with no keyword IS a definition: a JS object method, a
# Java, C#, Dart or C function after its type. In Kotlin, Swift, Go and
# Rust it is a call with a trailing lambda (Row(...) { ... }), and reading
# it as a method put every Compose call inside "Row".
SHAPE_METHODS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".java", ".cs",
                 ".dart", ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".mm", ".php",
                 ".scala", ".groovy"}
TYPE_WORDS = {"class", "interface", "object", "struct", "enum", "trait", "impl",
              "record", "protocol", "extension", "companion"}
MAX_BYTES = 3_000_000

JS_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof",
               "else", "do", "try", "finally", "throw", "case", "default", "delete",
               "void", "in", "of", "instanceof", "await", "yield", "with", "class",
               "const", "let", "var", "async", "new", "import", "export",
               # the other C-shaped languages' control words, so `when (x) {`
               # or `match x {` is not read as a call or a method
               "when", "match", "loop", "unless", "until", "guard", "defer", "select",
               "foreach", "lock", "using", "synchronized", "sizeof", "assert",
               "fun", "func", "fn", "override", "suspend", "public", "private",
               "protected", "internal", "static", "final", "open", "inline", "pub",
               "unsafe", "mut", "val", "init", "constructor", "super",
               "this", "self", "go", "chan", "range", "then", "elif", "where"}


# ---- the scanners ---------------------------------------------------------

class Sink:
    """Where a scanner puts what it finds, for one file."""

    def __init__(self, path):
        self.path = path
        self.defs = []      # {name, line, end, kind, parent}
        self.calls = []     # {name, qual, line, caller}
        self.draws = []     # {what, kind: id|class|path|file, line, fn}
        self.routes = []    # {path, handler}
        self.refs = {}      # name -> how often it is used without being called
        self.passed = []    # {name, line, fn}: those uses, located; kept for the
                            # names the tree defines as functions (build filters)
        self.sections = []  # {name, line}: the `// ---- name ----` headers

    def add_def(self, name, line, kind, parent):
        self.defs.append({"name": name, "file": self.path, "line": line, "end": line,
                          "kind": kind, "parent": parent})
        return self.defs[-1]

    def add_call(self, name, qual, line, caller):
        self.calls.append({"name": name, "qual": qual, "file": self.path, "line": line,
                           "caller": caller})

    def add_ref(self, name, line=0, fn=""):
        self.refs[name] = self.refs.get(name, 0) + 1
        self.passed.append({"name": name, "line": line, "fn": fn})

    def add_draw(self, what, kind, line, fn):
        self.draws.append({"what": what, "kind": kind, "file": self.path, "line": line,
                           "fn": fn})


SECTION_HEAD = re.compile(r"^\s*(?://|#)\s*----\s*(.*?)\s*-{3,}\s*$")


def scan_sections(text, sink):
    """The `// ---- name ----` (or `# ----`) headers a file is written in:
    the units a person reads it by, and the units a cleanup moves."""
    for i, line in enumerate(text.split("\n"), 1):
        m = SECTION_HEAD.match(line)
        if m and m.group(1):
            sink.sections.append({"name": m.group(1), "line": i})


def scan_python(text, sink):
    scan_sections(text, sink)
    for m in ROUTE.finditer(text):
        sink.routes.append({"path": m.group(1), "handler": m.group(2), "file": sink.path})
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        sink.add_def(f"(unparsable: {e.msg} at line {e.lineno})", e.lineno or 1, "error", "")
        return
    stack = []
    call_funcs = set()      # the Name a call is made through: a call, not a use by name

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
                    call_funcs.add(id(f))
                elif isinstance(f, ast.Attribute):
                    qual = f.value.id if isinstance(f.value, ast.Name) else ""
                    sink.add_call(f.attr, qual, child.lineno, enclosing())
            # A name read and not called: passed (runner.register("compose",
            # run_compose_job)), assigned, listed. Located, like the brace
            # languages' (B227), so who-calls can say where.
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) \
                    and id(child) not in call_funcs:
                sink.add_ref(child.id, child.lineno, enclosing())
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                for what, kind in strings_draw(child.value):
                    sink.add_draw(what, kind, child.lineno, enclosing())
            walk(child, parent_name)

    walk(tree, "")


ATTR_ID = re.compile(r"""\bid=["']([A-Za-z][\w:-]*)["']""")
ATTR_CLASS = re.compile(r"""\bclass=["']([^"']+)["']""")
SEL = re.compile(r"""(?<![\w$])([#.])([A-Za-z_][\w-]*)""")
HANDLER = re.compile(r"""\bon[a-z]+=["']\s*([A-Za-z_$][\w$]*)\s*\(""")
# What a suite and a server share besides names: an API path, and a file
# of the tree named outright (a suite that runs scripts/bb). Both are how
# `suites FILE` reaches a python change, which no suite calls by name.
API_PATH = re.compile(r"(/api/[\w/.-]+)")
TREE_FILE = re.compile(r"(?<![\w/])((?:scripts|config|tools|docs)/[\w./-]+)")
# The server's route table: a kind, an API path and the handler's name, on
# one line. How a python change reaches a suite: the module's functions are
# called from a handler, the handler answers a path, and the suite asks it.
ROUTE = re.compile(r"""\(\s*"\w+"\s*,\s*"(/api/[^"]+)"\s*,\s*"(\w+)"\s*\)""")


def strings_draw(s):
    """The element ids and classes a string carries: markup attributes, and
    the #id / .class of a selector. Only for strings that look like either,
    so a sentence with a full stop in it does not become a class. Plus an
    API path and a file of the tree, for `suites`."""
    out = []
    for m in API_PATH.finditer(s):
        out.append((m.group(1).rstrip("/.").split("?")[0], "path"))
    for m in TREE_FILE.finditer(s):
        out.append((m.group(1).rstrip("."), "file"))
    for m in ATTR_ID.finditer(s):
        out.append((m.group(1), "id"))
    for m in ATTR_CLASS.finditer(s):
        for c in m.group(1).split():
            if c.isidentifier() or "-" in c:
                out.append((c.strip(), "class"))
    # A selector, not a sentence: short, selector characters only, and at
    # most six words, since prose with a full stop in it matched before.
    if "<" not in s and len(s) < 200 and len(s.split()) <= 6 \
            and re.match(r"^[\s\w#.\[\]=\"':>,()*+~^$|-]+$", s):
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

    def __init__(self, text, sink, line0=1, top="(top level)", shape_methods=True, base=0,
                 fn_words=None):
        self.s = text
        self.shape_methods = shape_methods
        self.base = base            # where this text starts in its file
        self.fn_words = FN_WORDS if fn_words is None else fn_words
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
        self.receiver = False
        self.blank = None        # a list to collect (start, end) of every string,
                                 # template, regex and comment, for code_only()

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
                j = n if j < 0 else j
                self.span(self.i, j)
                self.i = j
                continue
            if two == "/*":
                j = s.find("*/", self.i + 2)
                j = n if j < 0 else j + 2
                self.line += s.count("\n", self.i, j)
                self.span(self.i, j)
                self.i = j
                continue
            if c in "'\"":
                at = self.i
                self.string(c)
                self.span(at, self.i)
                continue
            if c == "`":
                at = self.i
                self.template()
                self.span(at, self.i)
                continue
            if c == "/" and self.regex_allowed():
                at = self.i
                self.regex()
                self.span(at, self.i)
                continue
            m = self.IDENT.match(s, self.i)
            if m:
                j = m.end()
                while j < n and s[j] in " \t":
                    j += 1
                self.ident(m.group(0), s[j:j + 1], self.last_sig == ".")
                self.i = m.end()
                continue
            self.punct(c)
            self.i += 1

    # -- pieces --------------------------------------------------------------
    def span(self, a, b):
        if self.blank is not None:
            self.blank.append((a, b))

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
                sub = JSScanner(inner, self.sink, self.line, self.enclosing(), self.shape_methods,
                                self.base + j + 2, self.fn_words)
                sub.stack = [(n, dp, None) for n, dp, _ in self.stack]
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

    def ident(self, word, nxt="", after_dot=False):
        self.prev_ident, self.last_ident = self.last_ident, word
        # A use by name that is not a call and not a property: passed,
        # assigned, listed. What tells dead code from a handler somebody
        # hands to onclick without calling it.
        if nxt != "(" and not after_dot and word not in JS_KEYWORDS \
                and self.last_kw not in ("function", "class") and not word[0].isdigit():
            self.sink.add_ref(word, self.line, self.enclosing())
        if word in self.fn_words:
            self.last_kw = "function"
        elif word in TYPE_WORDS:
            self.last_kw = "class"
        elif word in ("async", "override", "suspend", "public", "private", "protected",
                      "internal", "static", "final", "open", "inline", "pub", "unsafe",
                      "operator", "infix", "data", "sealed", "abstract", "export", "default"):
            pass                     # a modifier: the keyword before it still stands
        elif self.last_kw == "function" and self.last_sig == ")" and self.receiver:
            # Go: func (r *T) NAME(  : the receiver came first
            self.receiver = False
            self.begin_def(word, "function")
            self.last_kw = ""
        else:
            if self.last_kw == "function" and word not in JS_KEYWORDS:
                # function NAME(  /  fun NAME(  /  fn NAME(  /  func NAME(
                self.begin_def(word, "function")
                self.last_kw = ""
            elif self.last_kw == "class" and word not in JS_KEYWORDS:
                self.begin_def(word, "class")
                self.last_kw = ""
            elif word not in JS_KEYWORDS:
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
                if self.shape_methods and (head.endswith(("{", ",", ";", "}")) or not head):
                    # possibly an object/class method: decided at the ) {
                    self.maybe_method = (prev, self.line)
                else:
                    self.maybe_method = None
                qual = ""
                if head.endswith("."):
                    qm = re.search(r"([A-Za-z_$][\w$]*)\s*\.$", head)
                    qual = qm.group(1) if qm else ""
                self.sink.add_call(prev, qual, self.line, self.enclosing())
            elif prev == "func" and self.last_kw == "function":
                # Go: `func (` is a receiver, and the name comes after it
                self.receiver = True
                self.maybe_method = None
            elif prev in self.fn_words or prev == "async":
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
            if self.pending is not None and self.parens <= self.paren_at_pending:
                # the body: not a brace inside the parameter list, which a
                # Kotlin default lambda (`onClick: () -> Unit = {}`) puts there
                self.pending["at"] = self.base + self.i + 1
                self.stack.append((self.pending["name"], self.depth, self.pending))
                self.pending = None
            elif self.last_sig == "=>":
                # an arrow body: attributed to what it was assigned to, if
                # that was `NAME = ... =>`; else it stays with the enclosing
                name = self.arrow_name()
                if name:
                    d = self.sink.add_def(name, self.line, "arrow", self.enclosing_or_blank())
                    d["at"] = self.base + self.i + 1
                    self.stack.append((name, self.depth, d))
                else:
                    self.stack.append((self.enclosing(), self.depth, None))
            elif self.last_sig == ")" and getattr(self, "maybe_method", None):
                name, line = self.maybe_method
                d = self.sink.add_def(name, line, "method", self.enclosing_or_blank())
                d["at"] = self.base + self.i + 1
                self.stack.append((name, self.depth, d))
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
                _, _, d = self.stack.pop()
                if d is not None:
                    d["end"] = self.line
            self.last_sig = "}"
            return
        if c == "=" and s[self.i:self.i + 2] == "=>":
            # `const NAME = x => expr`: a definition with no brace to hang a
            # body on, so it has no `at` for the instrumenter and its end is
            # its line; but it is a function, found, called, passed and
            # counted like one (B224: drawLinux was nowhere in the map).
            j, n = self.i + 2, len(s)
            while j < n and s[j] in " \t":
                j += 1
            if j < n and s[j] != "{":
                m = re.search(r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^()]*\)|[A-Za-z_$][\w$]*)\s*$",
                              s[max(0, self.i - 200):self.i])
                if m and m.group(1) not in JS_KEYWORDS and self.last_kw != "function":
                    d = self.sink.add_def(m.group(1), self.line, "arrow", self.enclosing_or_blank())
                    d["expr"] = True
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


def code_only(text, suffix=".js"):
    """The text with every string, template literal, regex and comment
    blanked to spaces, newlines kept, so a regex over it reads code and
    only code: `data-state="..."` inside a template is not an assignment
    to state."""
    sc = JSScanner(text, Sink("(code_only)"), shape_methods=suffix in SHAPE_METHODS,
                   fn_words=FN_BY_SUFFIX.get(suffix, set()))
    sc.blank = []
    try:
        sc.run()
    except Exception:
        return text
    out = list(text)
    for a, b in sc.blank:
        for i in range(a, min(b, len(out))):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


def scan_js(text, sink, line0=1, base=0):
    if line0 == 1 and base == 0:
        scan_sections(text, sink)
    suffix = Path(sink.path).suffix
    JSScanner(text, sink, line0, shape_methods=suffix in SHAPE_METHODS, base=base,
              fn_words=FN_BY_SUFFIX.get(suffix, set())).run()


SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)


def scan_html(text, sink):
    scan_sections(text, sink)
    pos = 0
    for m in SCRIPT.finditer(text):
        markup = text[pos:m.start()]
        markup_draws(markup, sink, text.count("\n", 0, pos) + 1)
        line0 = text.count("\n", 0, m.start(1)) + 1
        scan_js(m.group(1), sink, line0, m.start(1))
        pos = m.end()
    markup_draws(text[pos:], sink, text.count("\n", 0, pos) + 1)


def markup_draws(markup, sink, line0):
    for ln, line in enumerate(markup.split("\n"), line0):
        for what, kind in strings_draw(line):
            sink.add_draw(what, kind, ln, "(markup)")


SH_DEF = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\)\s*\{")


def scan_sh(text, sink):
    scan_sections(text, sink)
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


def build(root, prior=None):
    """The index, per file: a file whose mtime the prior index already has
    keeps its entry, and only the changed, new and gone files are scanned
    or dropped. Whole-tree rebuilds cost a second and a half on every edit,
    which is every first question after an edit; this is a tenth of that.
    The flat lists the questions read are joined at load and not written."""
    root = Path(root)
    kept = (prior or {}).get("files", {})
    files, scanned, fresh = {}, 0, {}
    for p, lang in sources(root):
        rel = str(p.relative_to(root))
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        old = kept.get(rel)
        if old and old.get("mtime") == mtime and old.get("lang") == lang and "defs" in old:
            files[rel] = old
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        sink = Sink(rel)
        try:
            {"py": scan_python, "js": scan_js, "html": scan_html, "sh": scan_sh}[lang](text, sink)
        except Exception as e:      # a scanner must never take the map down
            sink.add_def(f"(scan failed: {e})", 1, "error", "")
        files[rel] = {"mtime": mtime, "lang": lang, "defs": sink.defs, "calls": sink.calls,
                      "draws": sink.draws, "routes": sink.routes, "refs": sink.refs,
                      "sections": sink.sections, "passed": []}
        fresh[rel] = sink
        scanned += 1
    # A use by name is worth a line only for a name the tree defines as a
    # function: every other identifier is a local, and locating those would
    # be most of the tree again. Filtered against every definition the index
    # holds at this build, so a function added later is seen passed in a
    # file only once that file is rescanned; `bb map build` rescans them all.
    names = {d["name"] for e in files.values() for d in e.get("defs", [])
             if d["kind"] in PASSABLE}
    for rel, sink in fresh.items():
        own = {(d["name"], d["line"]) for d in sink.defs}
        files[rel]["passed"] = [p | {"file": rel} for p in sink.passed
                                if p["name"] in names and (p["name"], p["line"]) not in own]
    idx = {"format": FORMAT, "built": time.time(), "root": str(root), "scanned": scanned,
           "dropped": len(set(kept) - set(files)), "files": files}
    out = root / INDEX_DIR
    out.mkdir(exist_ok=True)
    tmp = out / (INDEX_FILE + ".tmp")
    tmp.write_text(json.dumps(idx))
    tmp.replace(out / INDEX_FILE)
    # The index an older reader wrote stays behind otherwise, and two of
    # them were sitting beside this one at seven megabytes each.
    for old in out.glob("*.json"):
        if old.name != INDEX_FILE and (old.name == "index.json" or re.fullmatch(r"map\d+\.json", old.name)):
            old.unlink(missing_ok=True)
    return flat(idx)


def flat(idx):
    """The per-file index with the lists the questions read joined on, and
    each definition's ordinal among the definitions of its name in its file,
    which is what coverage is keyed on: a line number moves with every edit
    above it, and after one section left the page every count read as
    unreached."""
    for k in ("defs", "calls", "draws", "routes", "passed"):
        idx[k] = [x for f in idx["files"].values() for x in f.get(k, [])]
    for entry in idx["files"].values():
        seen = {}
        for d in entry.get("defs", []):
            seen[d["name"]] = seen.get(d["name"], 0) + 1
            d["k"] = seen[d["name"]]
    return idx


def usable(prior):
    """An index this reader wrote: its format, and every file entry whole."""
    return (isinstance(prior, dict) and prior.get("format") == FORMAT
            and isinstance(prior.get("files"), dict)
            and all(isinstance(v, dict) and "defs" in v and "calls" in v and "mtime" in v
                    for v in prior["files"].values()))


def load(root, force=False):
    root = Path(root)
    f = root / INDEX_DIR / INDEX_FILE
    prior = None
    if not force and f.exists():
        try:
            prior = json.loads(f.read_text())
        except (OSError, ValueError):
            prior = None
    if not usable(prior):
        return build(root)
    have = prior.get("files", {})
    now = {}
    for p, _ in sources(root):
        try:
            now[str(p.relative_to(root))] = p.stat().st_mtime
        except OSError:
            continue
    if set(now) != set(have) or any(now[k] != have[k].get("mtime") or "defs" not in have[k] for k in now):
        return build(root, prior)
    return flat(prior)


# ---- the questions ----------------------------------------------------------

TEST_NAME = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.(go|py|rs)|[^/]+Test\.(kt|java|cs|scala)"
                       r"|[^/]+\.(test|spec)\.[cm]?[jt]sx?|[^/]+_spec\.rb)$")


def is_test(path):
    """A test: an .mjs under a test directory (this repository's suites,
    minus the library beside them), or a file named the way its language
    names tests: test_x.py, x_test.go, XTest.kt, x.test.ts, x.spec.js."""
    if ("/test/" in "/" + path or path.startswith("test/")) and path.endswith(".mjs"):
        return not path.endswith("/lib.mjs")
    return bool(TEST_NAME.search(path)) or "/androidTest/" in path or "/src/test/" in path


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
    # ...and the places it is handed over without a call: to a draw, an
    # onclick, a list. Not a call, and the reason a function nothing calls
    # is not dead; who-calls used to say "nothing calls" and leave it there.
    passed = [] if qual else [p for p in idx.get("passed", []) if p["name"] == name]
    if not rows and not passed:
        return [f"nothing calls {name}" + (f" on {qual}" if qual else "") + ", and nothing passes it by name"]
    out = []
    if not rows:
        out.append(f"nothing calls {name} directly; it is passed by name:")
    for c in sorted(rows, key=lambda c: (is_test(c["file"]), c["file"], c["line"])):
        tag = "test " if is_test(c["file"]) else ""
        out.append(f"{tag}{c['file']}:{c['line']}  from {c['caller']}  | {line_of(root, c['file'], c['line'])}")
    for p in sorted(passed, key=lambda p: (is_test(p["file"]), p["file"], p["line"])):
        tag = "test " if is_test(p["file"]) else ""
        out.append(f"{tag}{p['file']}:{p['line']}  passed by name in {p['fn']}  | {line_of(root, p['file'], p['line'])}")
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


def suites_for(idx, paths):
    """{suite file: set of reasons} for the suites that reach these files:
    a suite that calls a function they define, names an id or class they
    draw, asks an API path they name, or names one of them outright (a
    suite that runs scripts/bb). A changed suite reaches itself. The
    map's half of a preflight (R75 step 3)."""
    files = set()
    for p in paths:
        files |= {f for f in idx["files"] if f == p or f.endswith("/" + p)}
    # Names a suite can call: the page's own functions, which a suite calls
    # bare inside page.evaluate. Never a python function: no suite calls
    # one, and `remove()` or `load()` defined in a module matched every
    # suite's DOM and its own helpers.
    js = {f for f in files if idx["files"].get(f, {}).get("lang") in ("js", "html")}
    names = {d["name"] for d in idx["defs"] if d["file"] in js and not d["name"].startswith("(")
             and len(d["name"]) > 3}
    things = {(d["what"], d["kind"]) for d in idx["draws"] if d["file"] in files}
    # A python change: the paths its functions answer, through the handlers
    # that call them (up to three hops of callers, within the python).
    py = {f for f in files if idx["files"].get(f, {}).get("lang") == "py"}
    if py:
        defs = {d["name"] for d in idx["defs"] if d["file"] in py and not d["name"].startswith("(")}
        stems = {Path(f).stem for f in py}
        # The calls INTO the module: qualified with its name (roadmap.items)
        # or bare from inside it. By name alone, `load` reached every store.
        reached = {c["caller"].rsplit(".", 1)[-1] for c in idx["calls"]
                   if c["name"] in defs and "." in c["caller"]
                   and (c["qual"] in stems or (not c["qual"] and c["file"] in py))}
        frontier = set(reached)
        # Then two hops through the handler's own methods (self.X calls),
        # never through a module-level helper: the status snapshot calls
        # every store, and walking through it reached every route.
        for _ in range(2):
            callers = {c["caller"].rsplit(".", 1)[-1] for c in idx["calls"]
                       if c["name"] in frontier and c["qual"] == "self" and "." in c["caller"]}
            frontier = callers - reached
            reached |= callers
        for r in idx.get("routes", []):
            if r["handler"] in reached:
                things.add((r["path"], "path"))
    hits = {}
    for f in files:
        if is_test(f):
            hits.setdefault(f, set()).add("changed itself")
    mark = {"class": ".", "id": "#", "path": "", "file": ""}
    paths = {w for w, k in things if k == "path"}
    for d in idx["draws"]:
        if not is_test(d["file"]):
            continue
        if (d["what"], d["kind"]) in things:
            hits.setdefault(d["file"], set()).add(mark[d["kind"]] + d["what"])
        elif d["kind"] == "path" and any(d["what"].startswith(p_ + "/") or d["what"].startswith(p_ + "?")
                                         for p_ in paths):
            hits.setdefault(d["file"], set()).add(d["what"])
        elif d["kind"] == "file" and any(f == d["what"] or f.endswith("/" + d["what"]) for f in files):
            hits.setdefault(d["file"], set()).add(d["what"])
    for c in idx["calls"]:
        if is_test(c["file"]) and not c["qual"] and c["name"] in names:
            hits.setdefault(c["file"], set()).add(c["name"] + "()")
    return files, hits


def q_suites(idx, paths, names_only=False):
    files, hits = suites_for(idx, paths)
    if not files:
        return [] if names_only else ["none of those files is indexed"]
    if not hits:
        return [] if names_only else ["no suite names anything these files define or draw"]
    out = []
    for f, why in sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if names_only:
            # For a script that will run them: a lab suite needs a real
            # service and is asked for by name (bb tests lab), never picked.
            if not Path(f).name.startswith("lab-"):
                out.append(Path(f).stem)
            continue
        w = sorted(why)
        out.append(f"{f}  ({len(w)}: {', '.join(w[:5])}{', ...' if len(w) > 5 else ''})")
    return out


INSTRUMENTED = ("function", "arrow", "method")
PASSABLE = ("function", "arrow", "method", "class", "def")


def page_functions(idx):
    """The dashboard's own functions on the page side: what a cleanup and a
    coverage run are about. Not the suites, not the anonymous."""
    return [d for f, entry in idx["files"].items() for d in entry["defs"]
            if Path(f).suffix in (".js", ".mjs", ".html") and not is_test(f)
            and d["kind"] in INSTRUMENTED and not d["name"].startswith("(")
            and "/test/" not in "/" + f]


def q_unused(idx, path=None):
    called = {}
    for c in idx["calls"]:
        called[c["name"]] = called.get(c["name"], 0) + 1
    refs = {}
    for entry in idx["files"].values():
        for n, k in entry.get("refs", {}).items():
            refs[n] = refs.get(n, 0) + k
    own = {}
    for d in idx["defs"]:
        if d["kind"] == "arrow":
            own[d["name"]] = own.get(d["name"], 0) + 1   # `const NAME =` reads as one use
    rows = []
    for d in page_functions(idx):
        if path and not (d["file"] == path or d["file"].endswith("/" + path)):
            continue
        n = d["name"]
        # A handler assigned to an element (el.onclick = ...) is used by the
        # browser, which the map cannot see; its name says what it is.
        if n.startswith("on") and n[2:3].islower():
            continue
        if called.get(n, 0) == 0 and refs.get(n, 0) - own.get(n, 0) <= 0:
            rows.append(d)
    if not rows:
        return ["nothing on the page is unused by this measure" + (f" in {path}" if path else "")]
    out = [f"{len(rows)} page function{'s' if len(rows) != 1 else ''} nothing calls and nothing passes by name:"]
    for d in sorted(rows, key=lambda d: (d["file"], d["line"])):
        out.append(f"  {d['file']}:{d['line']}  {d['name']}" + (f"  (in {d['parent']})" if d["parent"] else ""))
    return out


def fid(d):
    return f"{d['file']}:{d['name']}#{d.get('k', 1)}"


COVERAGE_FORMAT = 1


def coverage_load(root):
    """The merged counts, or None when there are none this reader can use:
    a file of another format is not read (the rule every file two builds
    can meet keeps), and the answer is then "no covered run yet"."""
    f = Path(root) / INDEX_DIR / "coverage.json"
    try:
        cov = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    return cov if isinstance(cov, dict) and cov.get("format") == COVERAGE_FORMAT else None


def coverage_ingest(root, idx, files, strip=""):
    """Merge per-suite counts into .bb-map/coverage.json. A page file holds
    {"suite", "counts": {"file:line:name": n}} with the file relative to
    the copy the run made; the server's holds {"suite": "server",
    "counts": {"abs/path:firstline:name": n}}, matched to the map's own
    definitions by file and name, nearest line."""
    cov = coverage_load(root) or {"format": COVERAGE_FORMAT, "suites": {}}
    py_by = {}
    for d in idx["defs"]:
        if idx["files"][d["file"]]["lang"] == "py" and d["kind"] == "def":
            py_by.setdefault((d["file"], d["name"]), []).append(d)
    for f in files:
        try:
            got = json.loads(Path(f).read_text())
        except (OSError, ValueError):
            continue
        suite = got.get("suite") or Path(f).stem
        counts = cov["suites"].setdefault(suite, {})
        for key, n in (got.get("counts") or {}).items():
            if "#" in key:
                # the page's own key: file:name#k, from the instrumenter
                counts[key] = counts.get(key, 0) + int(n)
                continue
            # the server's: an absolute path, a first line and a name, matched
            # to the map's definition of that name nearest that line
            file, _, rest = key.partition(":")
            # Paths as the process saw them: a doubled slash from a harness
            # that joins with one, a symlink the tree sits behind. Normalised
            # before the prefix comes off, and the prefix the same way.
            file = os.path.normpath(file)
            pre = os.path.normpath(strip) + "/" if strip else ""
            if pre and file.startswith(pre):
                file = file[len(pre):]
            line, _, name = rest.partition(":")
            try:
                line = int(line)
            except ValueError:
                continue
            cands = py_by.get((file, name))
            if not cands:
                continue
            d = min(cands, key=lambda d: abs(d["line"] - line))
            counts[fid(d)] = counts.get(fid(d), 0) + int(n)
    cov["at"] = time.time()
    out = Path(root) / INDEX_DIR
    out.mkdir(exist_ok=True)
    (out / "coverage.json").write_text(json.dumps(cov))
    return cov


def covered_ids(cov):
    out = {}
    for suite, counts in (cov or {}).get("suites", {}).items():
        for k, n in counts.items():
            out.setdefault(k, {})[suite] = n
    return out


def targets(idx):
    """Everything coverage can speak about: the page's functions and the
    python's, outside the suites."""
    rows = [d for d in page_functions(idx) if not d.get("expr")]   # no body to count in
    rows += [d for f, entry in idx["files"].items() for d in entry["defs"]
             if entry["lang"] == "py" and d["kind"] == "def" and not is_test(f)
             and "/test/" not in "/" + f and not d["name"].startswith("(")]
    return rows


def q_coverage(idx, cov):
    if not cov:
        return ["no covered run yet: bb tests coverage runs the suite with the counters in"]
    hit = covered_ids(cov)
    per = {}
    for d in targets(idx):
        t = per.setdefault(d["file"], [0, 0])
        t[1] += 1
        if fid(d) in hit:
            t[0] += 1
    tot_c = sum(v[0] for v in per.values())
    tot = sum(v[1] for v in per.values())
    out = [f"{tot_c} of {tot} functions reached by {len(cov['suites'])} suites "
           f"(last run {time.strftime('%d %b %H:%M', time.localtime(cov.get('at', 0)))})"]
    for f, (c, n) in sorted(per.items(), key=lambda kv: (kv[1][1] - kv[1][0]) * -1)[:25]:
        if n - c:
            out.append(f"  {n - c:4d} unreached of {n:4d}  {f}")
    out.append("bb map uncovered FILE lists them; bb map covered NAME says which suites ran one")
    return out


def q_covered(idx, cov, name):
    if not cov:
        return ["no covered run yet: bb tests coverage runs the suite with the counters in"]
    hit = covered_ids(cov)
    rows = [d for d in targets(idx) if d["name"] == name]
    if not rows:
        return [f"nothing defines {name} on the page or the server"]
    out = []
    for d in rows:
        by = hit.get(fid(d))
        if not by:
            out.append(f"{d['file']}:{d['line']}  {name}: reached by no suite")
            continue
        top = sorted(by.items(), key=lambda kv: -kv[1])
        out.append(f"{d['file']}:{d['line']}  {name}: reached by {len(by)} suite{'s' if len(by) != 1 else ''}: "
                   + ", ".join(f"{s} ({n})" for s, n in top[:8]) + (", ..." if len(top) > 8 else ""))
    return out


def q_uncovered(idx, cov, path=None):
    if not cov:
        return ["no covered run yet: bb tests coverage runs the suite with the counters in"]
    hit = covered_ids(cov)
    rows = [d for d in targets(idx) if fid(d) not in hit
            and (not path or d["file"] == path or d["file"].endswith("/" + path))]
    if not rows:
        return ["every function here was reached" + (f" in {path}" if path else "")]
    out = [f"{len(rows)} function{'s' if len(rows) != 1 else ''} no suite reached" + (f" in {path}" if path else "") + ":"]
    for d in sorted(rows, key=lambda d: (d["file"], d["line"])):
        out.append(f"  {d['file']}:{d['line']}  {d['name']}" + (f"  (in {d['parent']})" if d["parent"] else ""))
    return out


# ---- the instrumenter -------------------------------------------------------

COV_RUNTIME = ("var __bbcovc = Object.create(null);"
               "function __bbcov(k){ __bbcovc[k] = (__bbcovc[k] || 0) + 1; }")


def instrument(dash):
    """Rewrite the dashboard's page files in DIR (the copy a run is made
    from, never the tree) so every function body the map knows the position
    of counts itself: `__bbcov("file:line:name");` after its opening brace,
    and the counter itself at the head of index.html's first script. Class
    bodies are not statements and are left alone."""
    dash = Path(dash)
    root_rel = "scripts/dashboard"
    n_files = n_fns = 0
    for p in sorted(dash.glob("*.js")) + [dash / "index.html"]:
        if not p.is_file():
            continue
        text = p.read_text(errors="replace")
        rel = f"{root_rel}/{p.name}"
        sink = Sink(rel)
        if p.suffix == ".html":
            scan_html(text, sink)
        else:
            scan_js(text, sink)
        seen = {}
        for d in sink.defs:
            seen[d["name"]] = seen.get(d["name"], 0) + 1
            d["k"] = seen[d["name"]]
        marks = sorted(((d["at"], d) for d in sink.defs
                        if d.get("at") is not None and d["kind"] in INSTRUMENTED
                        and not d["name"].startswith("(")), key=lambda x: -x[0])
        for at, d in marks:
            text = text[:at] + f'__bbcov("{rel}:{d["name"]}#{d["k"]}");' + text[at:]
            n_fns += 1
        if p.suffix == ".html":
            text = text.replace("<script>", "<script>" + COV_RUNTIME, 1)
        p.write_text(text)
        n_files += 1
    return n_files, n_fns


DECL = re.compile(r"^(?:let|var)\s+(.*)$")
ASSIGN = r"(?:=(?!=)|\+=|-=|\*=|/=|\|\|=|&&=|\?\?=|\+\+|--)"


def page_scripts(idx):
    """The page and the scripts beside it: not the suites, and not the other
    languages the JS scanner reads (Kotlin, Go) which have no page-level let."""
    return [f for f, e in idx["files"].items()
            if Path(f).suffix in (".js", ".mjs", ".html") and e.get("lang") in ("js", "html") and not is_test(f)]


def script_bodies(root, f):
    """(lines, first line number) for each script body in a file: the file
    itself for a script, the inline blocks for a page."""
    try:
        text = (Path(root) / f).read_text(errors="replace")
    except OSError:
        return []
    if f.endswith(".html"):
        return [(code_only(m.group(1)).split("\n"), text.count("\n", 0, m.start(1)) + 1)
                for m in SCRIPT.finditer(text)]
    return [(code_only(text).split("\n"), 1)]


def declarators(rest):
    """The names on one `let` line: `a = 1, b = null, c;` is three."""
    names, depth, cur, q = [], 0, "", ""
    for ch in rest:
        if q:
            if ch == q:
                q = ""
            continue
        if ch in "\"'`":
            q = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            names.append(cur)
            cur = ""
            continue
        elif ch == ";" and depth == 0:
            break
        cur += ch
    names.append(cur)
    out = []
    for n in names:
        m = re.match(r"\s*([A-Za-z_$][\w$]*)", n)
        if m:
            out.append(m.group(1))
    return out


def q_state(idx, root, path=None):
    """The page-level mutable bindings and what feeds each one. A `let` at
    column 0 of a page script is one; every assignment to it across every
    page script is found, with the function it sits in and whether the right
    side reads `state` (the poll) or a fetch. One fed from `state` is a copy
    of the poll kept by hand, which is how B213 and B215 happened; one fed
    from a fetch is that fetch's cache. Timers, drags and open menus are the
    page's own and read as local."""
    files = page_scripts(idx)
    if path:
        files = [f for f in files if f == path or f.endswith("/" + path)]
        if not files:
            return [f"{path} is not a page script the map knows"]
    bodies = {f: script_bodies(root, f) for f in page_scripts(idx)}
    decls = []
    for f in files:
        for lines, l0 in bodies[f]:
            for i, l in enumerate(lines):
                m = DECL.match(l)
                if m:
                    decls.extend((f, l0 + i, n) for n in declarators(m.group(1)))
    if not decls:
        return [f"no page-level let or var in {', '.join(files)}"]

    def fn_at(f, ln):
        best = None
        for d in idx["files"][f]["defs"]:
            if d["kind"] in INSTRUMENTED and d["line"] <= ln <= d["end"] \
                    and (best is None or d["line"] >= best["line"]):
                best = d
        return best["name"] if best else "(top level)"

    # One pass over every line for every binding, not one per binding: the
    # page has 150 and thirty thousand lines, and the per-binding version
    # took eight seconds to say what this says in one.
    wanted = {}
    for f, ln, n in decls:
        wanted.setdefault(n, []).append((f, ln))
    names = "|".join(sorted(map(re.escape, wanted), key=len, reverse=True))
    pat = re.compile(r"(?<![\w.$])(" + names + r")\s*" + ASSIGN
                     + r"|(?<![\w.$])(?:\+\+|--)(" + names + r")(?![\w$])")
    local = re.compile(r"\b(?:let|const|var)\s+(.*)$")
    sites = {}
    for g, blocks in bodies.items():
        # Another script may write a binding (index.html's wiring writes
        # docOpen, which page-doctor.js declares), but one that declares the
        # name itself has its own: a `timer` local to a function there is not
        # the page's timer. Every declarator on the line counts, since
        # `let on = false, timer = null` is two.
        own = set()
        for lines, _ in blocks:
            for l in lines:
                if (m := local.search(l)):
                    own.update(declarators(m.group(1)))
        for lines, l0 in blocks:
            for i, code in enumerate(lines):     # strings and comments already blank
                for m in pat.finditer(code):
                    n = m.group(1) or m.group(2)
                    # `const state = ` inside a function is that function's
                    # own, not a write to the page's; a for-of the same.
                    if re.search(r"\b(?:const|let|var)\s*$", code[:m.start()]):
                        continue
                    # What is assigned: to the end of the statement, not of
                    # the line, or `x = null; if (state) ...` reads as state.
                    rhs = code[m.end():].split(";")[0]
                    feed = ("state" if re.search(r"\bstate\b", rhs)
                            else "fetch" if re.search(r"\bawait\b|\.json\(|\bfetch\(", rhs)
                            else "local")
                    for f, ln in wanted[n]:
                        if g == f and l0 + i == ln:
                            continue               # the declaration itself
                        if g != f and n in own:
                            continue               # that file's own local
                        sites.setdefault((f, ln, n), []).append((g, l0 + i, fn_at(g, l0 + i), feed))
    rows = [(f, ln, n, sites.get((f, ln, n), [])) for f, ln, n in decls]
    rank = lambda r: (0 if any(s[3] == "state" for s in r[3])   # noqa: E731
                      else 1 if any(s[3] == "fetch" for s in r[3]) else 2, r[0], r[1])
    rows.sort(key=rank)
    n_state = sum(1 for r in rows if rank(r)[0] == 0)
    n_fetch = sum(1 for r in rows if rank(r)[0] == 1)
    out = [f"{len(rows)} page-level binding{'s' if len(rows) != 1 else ''} in "
           f"{', '.join(Path(f).name for f in files) if len(files) < 4 else f'{len(files)} page scripts'}: "
           f"{n_state} assigned from state, {n_fetch} from a fetch, {len(rows) - n_state - n_fetch} local"]
    for f, ln, n, sites in rows:
        k = rank((f, ln, n, sites))[0]
        head = f"  {f}:{ln}  {n}: {len(sites)} assignment{'s' if len(sites) != 1 else ''}"
        if k == 2:
            out.append(head + (", local" if sites else " (never assigned: a const in all but name)"))
            continue
        out.append(head)
        shown = [s for s in sites if s[3] != "local"]
        for g, gl, fn, feed in shown[:6]:
            out.append(f"      {g}:{gl}  in {fn}  from {'state' if feed == 'state' else 'a fetch'}")
        rest = len(sites) - min(len(shown), 6)
        if rest:
            out.append(f"      and {rest} more, local")
    out.append("assigned from state: a copy of the poll, kept in step by hand and drifting from it (B213, B215): "
               "read state where it is used instead. From a fetch: that fetch's own cache, which is fine until "
               "something else holds the same answer. Only a `let` at column 0 is seen, and only the names on its first line.")
    return out


FILE_WORD = re.compile(r"(?<![\w/])([A-Za-z0-9_][\w./-]*\.(?:py|js|mjs|html|sh|kt|kts|yml|yaml|json|toml|xml|md))(?:'s)?\b")
CLAUSE_END = re.compile(r";|\. |\), ")   # where one address's sentence stops and another's starts
ADDR = re.compile(r"~(\d{2,6})")
IDENT_BEFORE = re.compile(r"([A-Za-z_][\w]*)(?:\(\))?")
ITEM = re.compile(r"^\s*~?\s*([RB]\d+)\b")     # `~ R18` is a shelved item in the listing


def _inside(d, n):
    """An address inside the name's own span is right: a line into the
    middle of a long function is still that function's."""
    return d["line"] - 5 <= n <= max(d["line"], d.get("end", d["line"])) + 5


def q_addresses(idx, root, texts):
    """Every `~line` in the texts, read with the file last named before it
    and the name nearest before it that the map defines in that file, and
    compared with where that name is now. A plan's words stay true while
    its addresses move under it (item 7: keep the words, change the
    addresses); this is what finds the ones that moved. Input is the
    roadmap's own listing (one item per line, its id first) or any text."""
    files = list(idx["files"])
    by_file = {}
    for d in idx["defs"]:
        by_file.setdefault(d["file"], {}).setdefault(d["name"], d)

    def resolve(name):
        hits = [f for f in files if f == name or f.endswith("/" + name)]
        if not hits:
            hits = [f for f in files if Path(f).name == Path(name).name]
        return hits

    stale, gone, unanchored, fine = [], [], 0, 0
    for text in texts:
        tag = ""
        for line in text.split("\n"):
            m = ITEM.match(line)
            if m:
                tag = m.group(1)            # the listing puts details under the id's line
            current = None
            # a file named earlier on the line is the file every later ~N is in
            marks = [(fm.start(), "file", fm.group(1)) for fm in FILE_WORD.finditer(line)]
            marks += [(am.start(), "addr", am) for am in ADDR.finditer(line)]
            for _pos, kind, val in sorted(marks, key=lambda x: x[0]):
                if kind == "file":
                    current = val
                    continue
                am = val
                n = int(am.group(1))
                where = f"{tag + ': ' if tag else ''}~{n}"
                if not current:
                    unanchored += 1
                    continue
                hits = resolve(current)
                if len(hits) != 1:
                    unanchored += 1
                    continue
                f = hits[0]
                # the name nearest before the address, the file's own words
                # taken out: `pinTo() in scripts/dashboard/index.html (~4634)`
                # is anchored on pinTo, not on index or html
                start = max(0, am.start() - 160)
                while start > 0 and not line[start - 1].isspace():
                    start -= 1                 # never cut a name in half
                head = line[start:am.start()]
                # One clause: `export_gaps() (agent.py ~1465), called from the
                # pre-flight (~4431)` is two addresses, and the second has no
                # name, not the first one's.
                cuts = [c.end() for c in CLAUSE_END.finditer(head)]
                if cuts:
                    head = head[cuts[-1]:]
                # A file named between a name and the address owns the address:
                # `cmd_tests (the lab subverb), docker-compose.yml's lab profile
                # (~186)` is the compose file's line, and cmd_tests is prose
                # before it. Only a name right up against the file mention
                # (`pinTo() in index.html (~4634)`) reaches across it.
                fms = list(FILE_WORD.finditer(head))
                if fms:
                    after = head[fms[-1].end():]
                    if re.sub(r"[\s(~]", "", after):
                        head = after
                head = FILE_WORD.sub(" ", head)
                # `nodes._census` names its module, which is the file; read
                # after the file words are gone, or `tab-emulator.js (` reads
                # as the module emulator
                qm = re.search(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\s*\(?\s*$", head)
                if qm and len(resolve(qm.group(1) + ".py")) == 1:
                    f = resolve(qm.group(1) + ".py")[0]
                names = [i.group(1) for i in IDENT_BEFORE.finditer(head)]
                # The nearest name that could be a symbol: camelCase, an
                # underscore, or written with its parentheses. A plain word
                # (drawn, list, controller) is prose and skipped; the first
                # symbol-looking name decides, so `imgAdder() in index.html
                # (~8093)` is imgAdder's address and not the one before it.
                anchor = next((x for x in reversed(names)
                               if len(x) > 2 and (any(c.isupper() for c in x[1:]) or "_" in x
                                                  or re.search(re.escape(x) + r"\(\)", head))), None)
                if anchor is None or anchor.isupper():
                    unanchored += 1            # a constant: the map indexes none
                    continue
                d = by_file.get(f, {}).get(anchor)
                if d is None:
                    # defined in another file: the address names the wrong one
                    elsewhere = [fd[anchor] for g, fd in by_file.items() if anchor in fd and not is_test(g)]
                    if len(elsewhere) == 1 and _inside(elsewhere[0], n):
                        fine += 1              # the number is right; the file the line last named is prose
                    elif len(elsewhere) == 1:
                        # the file read for it was the last one the line named,
                        # which may be the plan's slip or this reader's
                        stale.append(f"{where}  {anchor} is {elsewhere[0]['file']}:{elsewhere[0]['line']} now "
                                     f"(the line last named {Path(f).name})")
                    elif elsewhere:
                        stale.append(f"{where}  {anchor} is not in {Path(f).name}; {len(elsewhere)} files define one")
                    else:
                        gone.append(f"{where}  {anchor} is defined nowhere the map looks now (was {Path(f).name}; "
                                    "a field, a setting or a constant is not indexed)")
                    continue
                if _inside(d, n):
                    fine += 1
                else:
                    stale.append(f"{where}  {anchor} is {f}:{d['line']} now")
    out = []
    if stale:
        out.append(f"{len(stale)} address{'es' if len(stale) != 1 else ''} moved:")
        out += ["  " + x for x in stale]
    if gone:
        out.append(f"{len(gone)} name{'s' if len(gone) != 1 else ''} the address was for {'are' if len(gone) != 1 else 'is'} gone:")
        out += ["  " + x for x in gone]
    out.append(f"{fine} address{'es' if fine != 1 else ''} still inside the name beside {'them' if fine != 1 else 'it'}, "
               f"{unanchored} with no name the map can check")
    return out


def q_sections(idx, path, cov=None):
    files = [f for f in idx["files"] if f == path or f.endswith("/" + path)]
    if not files:
        return [f"{path} is not indexed"]
    f = files[0]
    entry = idx["files"][f]
    heads = entry.get("sections") or []
    if not heads:
        return [f"{f} has no `// ---- name ----` sections"]
    top = [d for d in entry["defs"] if not d["parent"] and not d["name"].startswith("(")]
    hit = covered_ids(cov) if cov else {}
    # calls INTO a function, by caller, from anywhere
    callers = {}
    for c in idx["calls"]:
        callers.setdefault(c["name"], []).append(c)
    out = [f"{f}: {len(heads)} sections, {len(top)} top-level definitions"]
    bounds = [(h["line"], heads[i + 1]["line"] if i + 1 < len(heads) else 10**9, h["name"])
              for i, h in enumerate(heads)]
    for start, end, name in bounds:
        mine = [d for d in top if start <= d["line"] < end]
        outside, at_load = set(), set()
        for d in mine:
            for c in callers.get(d["name"], []):
                if c["file"] == f and start <= c["line"] < end:
                    continue
                if is_test(c["file"]):
                    continue
                if c["caller"] == "(top level)":
                    at_load.add(f"{Path(c['file']).name}:{c['line']}")
                outside.add(c["caller"] if c["file"] == f else f"{Path(c['file']).name}:{c['caller']}")
        # The section's own statements that run at load: calls made from
        # the top level inside it (wiring a button, adding a listener). A
        # file loaded before the page cannot carry those, so they are what
        # stays behind when the section's functions move.
        own_load = [c for c in entry["calls"] if c["caller"] == "(top level)" and start <= c["line"] < end]
        covered = sum(1 for d in mine if fid(d) in hit) if hit else None
        cov_s = f", {covered}/{len(mine)} covered" if hit and mine else ""
        out.append(f"  {start:6d}  {name}: {len(mine)} function{'s' if len(mine) != 1 else ''}, "
                   f"{len(outside)} caller{'s' if len(outside) != 1 else ''} from outside"
                   + (f", {len(at_load)} at load" if at_load else "")
                   + (f", runs {len(own_load)} call{'s' if len(own_load) != 1 else ''} at load itself" if own_load else "")
                   + cov_s)
    out.append("bb map defs FILE lists the functions; who-calls NAME each one's callers; a section with few callers from outside that runs nothing at load itself moves whole, and one that does leaves that wiring behind")
    return out


def summary(idx):
    langs = {}
    for f in idx["files"].values():
        langs[f["lang"]] = langs.get(f["lang"], 0) + 1
    n_test = sum(1 for f in idx["files"] if is_test(f))
    when = time.strftime('%d %b %H:%M', time.localtime(idx['built']))
    what = (f"{idx.get('scanned', 0)} file{'s' if idx.get('scanned', 0) != 1 else ''} scanned"
            + (f", {idx['dropped']} dropped" if idx.get("dropped") else ""))
    return [f"{len(idx['files'])} files ({', '.join(f'{n} {k}' for k, n in sorted(langs.items()))}; {n_test} test suites), "
            f"{len(idx['defs'])} definitions, {len(idx['calls'])} calls, {len(idx['draws'])} ids and classes drawn",
            f"last built {when} ({what}) into {INDEX_DIR}/{INDEX_FILE}; a changed file is rescanned by itself, the rest kept",
            "",
            "bb map find NAME | who-calls NAME | calls NAME | defs FILE | draws ID|.class | suites FILE... | "
            "state [FILE] | sections FILE | unused | build"]


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
    if verb == "instrument":
        if not rest:
            print("bb map instrument DIR: the dashboard directory of a run's copy", file=sys.stderr)
            return 2
        nf, nn = instrument(rest[0])
        print(f"instrumented {nn} functions in {nf} files under {rest[0]}")
        return 0
    idx = load(root)
    if not verb:
        print("\n".join(summary(idx)))
        return 0
    if verb == "coverage-ingest":
        strip = ""
        if rest[:1] == ["--strip"]:
            strip, rest = rest[1], rest[2:]
        cov = coverage_ingest(root, idx, rest, strip)
        print(f"coverage: {len(cov['suites'])} suites on record")
        return 0
    if verb == "unused":
        print("\n".join(q_unused(idx, rest[0] if rest else None)))
        return 0
    if verb == "coverage":
        print("\n".join(q_coverage(idx, coverage_load(root))))
        return 0
    if verb == "covered":
        if not rest:
            print("bb map covered NAME", file=sys.stderr)
            return 2
        print("\n".join(q_covered(idx, coverage_load(root), rest[0])))
        return 0
    if verb == "addresses":
        texts = []
        for f in rest or ["-"]:
            texts.append(sys.stdin.read() if f == "-" else Path(f).read_text(errors="replace"))
        print("\n".join(q_addresses(idx, root, texts)))
        return 0
    if verb == "state":
        print("\n".join(q_state(idx, root, rest[0] if rest else None)))
        return 0
    if verb == "sections":
        if not rest:
            print("bb map sections FILE", file=sys.stderr)
            return 2
        print("\n".join(q_sections(idx, rest[0], coverage_load(root))))
        return 0
    if verb == "uncovered":
        print("\n".join(q_uncovered(idx, coverage_load(root), rest[0] if rest else None)))
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
        names_only = "--names" in rest
        lines = q_suites(idx, [r for r in rest if r != "--names"], names_only)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
