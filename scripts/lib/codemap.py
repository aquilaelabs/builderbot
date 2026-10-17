#!/usr/bin/env python3
"""bb map: a code map a session asks instead of grepping (roadmap R75).

One index over a project tree: every function a file defines, every call
by name with the function it was made from, every element id and class a
function's markup draws, and which test suite names each of those. Built
from the files themselves with nothing installed: python's own parser for
the .py files, a scanner for C and C++, a brace scanner for the other
C-shaped languages (JavaScript, Kotlin, Java, Go, Rust, PHP and the rest)
and a line pass for shell. `bb map languages` says which files are read.

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
    bb map affected --base REF FILES...   the suites a change touches, by the functions its lines fall in and the covered run (--names for a script)
    bb map covered NAME          which suites ran NAME, and how often: the regression net for touching it
    bb map uncovered [FILE]      the functions no suite reached
    bb map languages             which files are indexed, by extension, and that everything else is not
    bb map build                 rescan everything now (a changed file is rescanned by itself on any question)
    bb map exclude               keep .bb-map/ out of git in this tree's repository; every build does it too

The scanner is deliberately rough: it knows nothing of scope beyond braces
and nothing of types. It answers "where would I look" in one call, which
is the question a session otherwise spends thirty greps on, and it says so
in its output where it is guessing (an anonymous callback is attributed to
the nearest named function around it).

The index lives at .bb-map/map3.json under the tree, the number being its
format. Building it keeps .bb-map/ out of git through the repository's own
exclude file, never the project's .gitignore, which is the project's to write.
"""
import ast
import bisect
import hashlib
import json
import os
import re
import subprocess
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
# The scanners' version: a file indexed by other ones is scanned again
# though it has not changed, so a fix to a scanner reaches every file. It
# is this file's own fingerprint, never a number bumped by hand: a scanner
# changed without a bump left indexes answering from the old reading (the
# operator, 8 Oct), and any edit here costs one rebuild of a few seconds.
try:
    SCANNER = hashlib.sha1(Path(__file__).read_bytes()).hexdigest()[:12]
except OSError:                  # (run from somewhere it cannot read itself)
    SCANNER = "unknown"
EXTS = {".py": "py", ".js": "js", ".mjs": "js", ".cjs": "js", ".ts": "js", ".tsx": "js",
        ".jsx": "js", ".html": "html", ".sh": "sh", ".bash": "sh",
        ".kt": "js", ".kts": "js", ".java": "js", ".cs": "js", ".go": "js", ".rs": "js",
        ".swift": "js", ".dart": "js", ".c": "c", ".h": "c", ".cc": "c", ".cpp": "c",
        ".hpp": "c", ".cxx": "c", ".hh": "c", ".m": "js", ".mm": "js", ".php": "js", ".scala": "js",
        ".groovy": "js", ".astro": "html", ".vue": "html", ".svelte": "html"}
# Source the map does not read, named in an answer that came back empty, so
# "nothing draws .x" is not read as the whole truth (B578)
NOT_READ = {".css", ".scss", ".sass", ".less", ".rb", ".erb", ".lua", ".ex", ".exs", ".erl",
            ".hs", ".ml", ".clj", ".cljs", ".r", ".jl", ".pl", ".pm", ".elm", ".fs", ".vb",
            ".twig", ".hbs", ".ejs", ".njk", ".liquid", ".jinja", ".j2", ".pug", ".haml",
            ".cshtml", ".razor", ".mdx", ".zig", ".nim", ".v", ".sol"}
# The words that open a function or a type in those languages. `def` is
# not here: python has its own parser, and Ruby's `def ... end` has no
# braces to count, so Ruby is not indexed (the one common language that
# is not).
FN_WORDS = {"function", "fun", "func", "fn"}
# ...per language, because `fn` is an ordinary parameter name in JavaScript
# and `func` a variable in Kotlin: a word opens a function only where its
# language says so.
FN_BY_SUFFIX = {".rs": {"fn"}, ".go": {"func"}, ".kt": {"fun"}, ".kts": {"fun"},
                ".swift": {"func"}, ".scala": {"def"}, ".php": {"function", "fn"},
                ".js": {"function"}, ".mjs": {"function"}, ".cjs": {"function"},
                ".ts": {"function"}, ".tsx": {"function"}, ".jsx": {"function"},
                ".html": {"function"}, ".astro": {"function"}, ".vue": {"function"},
                ".svelte": {"function"}}
# Where `name(...) {` with no keyword IS a definition: a JS object method, a
# Java, C#, Dart or C function after its type. In Kotlin, Swift, Go and
# Rust it is a call with a trailing lambda (Row(...) { ... }), and reading
# it as a method put every Compose call inside "Row".
SHAPE_METHODS = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".astro", ".vue",
                 ".svelte", ".java", ".cs",
                 ".dart", ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".mm",
                 ".scala", ".groovy"}
TYPE_WORDS = {"class", "interface", "object", "struct", "enum", "trait", "impl",
              "record", "protocol", "extension", "companion"}
# ...and in JavaScript and TypeScript only these: `object`, `record` and
# `impl` are names there, and `net.interface && rn.interface` read as a
# class called rn.
JS_SUFFIXES = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".html", ".astro", ".vue", ".svelte"}
JS_TYPE_WORDS = {"class", "interface", "enum"}
MAX_BYTES = 3_000_000
# A minified bundle is one line of someone else's code: every name in it is
# a letter, and bootstrap.bundle.min.js answered find w
MINIFIED = re.compile(r"\.min\.(?:js|mjs|cjs)$")

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
# JavaScript's own, which leave `open`, `select`, `when`, `init`, `then`
# and the rest of the other languages' words as the names they are there:
# with the set above a JS `function open(` was no definition and no call
# of `select(` was seen.
JS_OWN_KEYWORDS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof",
                   "else", "do", "try", "finally", "throw", "case", "default", "delete",
                   "void", "in", "instanceof", "await", "yield", "with", "class",
                   "const", "let", "var", "async", "new", "import", "export", "super",
                   "this", "static", "extends", "implements", "public", "private",
                   "protected", "readonly", "abstract", "declare"}


# The words that may stand between `function` and its name, or before a
# method: Kotlin's `open` or `data` is a name in JavaScript, and
# `function open(x)` was indexed as a function called x.
MODIFIERS = {"async", "override", "suspend", "public", "private", "protected",
             "internal", "static", "final", "open", "inline", "pub", "unsafe",
             "operator", "infix", "data", "sealed", "abstract", "export", "default"}
JS_MODIFIERS = {"async", "static", "export", "default", "public", "private", "protected",
                "readonly", "abstract", "declare", "override"}


def keywords_for(suffix):
    if suffix in JS_SUFFIXES:
        return (JS_OWN_KEYWORDS, JS_TYPE_WORDS, JS_MODIFIERS)
    return (JS_KEYWORDS, TYPE_WORDS, MODIFIERS)


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
SECTION_RULE = re.compile(r"^(?://|#)\s*-{20,}\s*$")
SECTION_TITLE = re.compile(r"^(?://|#)\s+(\S.*?)\s*$")


def scan_sections(text, sink):
    """The `// ---- name ----` (or `# ----`) headers a file is written in:
    the units a person reads it by, and the units a cleanup moves."""
    lines = text.split("\n")
    for i, line in enumerate(lines, 1):
        m = SECTION_HEAD.match(line)
        if m and m.group(1):
            sink.sections.append({"name": m.group(1), "line": i})
        elif SECTION_RULE.match(line) and i < len(lines):
            # the agent's form: a bare rule, then `# the name` under it (it
            # read as one section in 7,500 lines)
            t = SECTION_TITLE.match(lines[i])
            if t and not SECTION_RULE.match(lines[i]):
                sink.sections.append({"name": t.group(1), "line": i})


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
                    call_funcs.add(id(f))
            # A name read and not called: passed (runner.register("compose",
            # run_compose_job)), assigned, listed. Located, like the brace
            # languages' (B227), so who-calls can say where.
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load) \
                    and id(child) not in call_funcs:
                sink.add_ref(child.id, child.lineno, enclosing())
            # ...and `module.name` read and not called: a function handed on
            # (node_addr=nodes.ssh_addr_of), which read as never used (B543).
            if isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load) \
                    and id(child) not in call_funcs:
                sink.add_ref(child.attr, child.lineno, enclosing())
            # (a lone ".json" in python is a file's extension, not a class:
            # codemap.py's ".c" had test_codemap_c.py reach every class c)
            if isinstance(child, ast.Constant) and isinstance(child.value, str) \
                    and not re.fullmatch(r"\.[A-Za-z0-9]{1,8}", child.value):
                for what, kind in strings_draw(child.value):
                    sink.add_draw(what, kind, child.lineno, enclosing())
                # a file named whole, as a unit test loads the agent by path
                # (os.path.join(HERE, ..., "builderbot-agent.py")): it names it
                if re.fullmatch(r"[\w.-]+\.(?:py|sh|js|mjs)", child.value):
                    sink.add_draw(child.value, "file", child.lineno, enclosing())
            walk(child, parent_name)

    walk(tree, "")


HTML_TAGS = ("a abbr article aside audio b blockquote body button canvas caption code col dd "
             "details dialog div dl dt em fieldset figure footer form h1 h2 h3 h4 h5 h6 header hr "
             "i iframe img input kbd label legend li main menu meter nav ol optgroup option output "
             "p picture pre progress section select small span strong sub summary sup svg table "
             "tbody td template textarea tfoot th thead tr u ul video").split()
ATTR_ID = re.compile(r"""\bid=["']([A-Za-z][\w:-]*)["']""")
ATTR_CLASS = re.compile(r"""\bclass=["']([^"']+)["']""")
# (but `progress.json` is a file: a tag before a file's extension is no selector)
SEL_TAG = re.compile(r"(?<![\w$#.-])(?:" + "|".join(sorted(HTML_TAGS, key=len, reverse=True))
                     + r")(?=[#.](?!(?:json|[cm]?js|ts|py|html?|css|md|txt|png|svg|jpe?g|gif|webp|xml"
                       r"|ya?ml|sh|log|csv|pdf|zip|apk|db|sqlite|toml|ini|lock)\b)[A-Za-z_])")
SEL_PART = re.compile(r"([#.])([A-Za-z_][\w-]*)")
SEL_COMPOUND = re.compile(r"(?<![\w$.#*/-])(?:[#.][A-Za-z_][\w-]*)+")
# An event attribute's value is JavaScript: every call in
# onclick="jumpToLogSection('errors'); return false" is one (B584)
REL_PATH = re.compile(r"\.{1,2}/[\w./@-]+")
HANDLER_ATTR = re.compile(r"""\bon[a-z]+\s*=\s*(["'])(.*?)\1""")
HANDLER_CALL = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(")
# Where a string is a class list: classList.add('a', 'b'), .toggle('x', on),
# .className = 'a ' + (b ? 'c' : 'd'), setAttribute('class', ...) (B586)
CLASS_CTX = re.compile(r"""(?:\bclassList\.(?:add|remove|toggle|contains|replace)\(\s*"""
                       r"""(?:(['"`])[\w\s-]*\1\s*,\s*)*|\.className\s*\+?=\s*[^;\n]*"""
                       r"""|\bsetAttribute\(\s*['"]class['"]\s*,\s*[^;\n]*)$""")


def handler_calls(text):
    """The functions the event attributes in this text call."""
    return [c.group(1) for m in HANDLER_ATTR.finditer(text) for c in HANDLER_CALL.finditer(m.group(2))
            if c.group(1) not in JS_OWN_KEYWORDS]
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
        # an attribute's value is not a selector (`a[href="#main"]` names
        # no id main), and a tag before a class is no word: `a.al-skip`
        # is the class al-skip (B576)
        s = re.sub(r"\[[^\]]*\]", " ", s)
        s = SEL_TAG.sub(" ", s)
        # a compound whole, `#x.y.z`, each part of it
        parts = [q for comp in SEL_COMPOUND.finditer(s) for q in SEL_PART.finditer(comp.group(0))]
        for m in parts:
            what = m.group(2)
            if m.group(1) == "#" and re.match(r"^[A-Za-z]", what):
                out.append((what, "id"))
            elif m.group(1) == "." and re.match(r"^[A-Za-z]", what) and not what.isdigit():
                out.append((what, "class"))
    return out


LINE_COMMENT = re.compile(r"(?m)(?:^|(?<=\s))//[^\n]*$|/\*(?:(?!\*/).)*\*/\s*$", re.S)


# `{ name: (a) =>` or `, name: x =>`: a key, not the `b : x =>` of a ternary
# An arrow's parameters, and in TypeScript its return type after them:
# `(a: Vec, b: Vec): Vec =>` (generics and unions; no parens in the type)
# (one level of parens inside: `(f: (x: S) => S)` or `(a = f())`)
ARROW_PARAMS = r"(?:\((?:[^()]|\([^()]*\))*\)|[A-Za-z_$][\w$]*)"
TS_ARROW_PARAMS = r"(?:\((?:[^()]|\([^()]*\))*\)(?:\s*:\s*[\w$<>\[\],.|&?'\" ]+?)?|[A-Za-z_$][\w$]*)"
TS_SUFFIXES = {".ts", ".tsx", ".astro", ".vue", ".svelte"}
JSX_SUFFIXES = {".tsx", ".jsx", ".astro"}
OBJ_KEY_ARROW = re.compile(r"(?:^|[{,])\s*([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?"
                           + ARROW_PARAMS + r"\s*\Z", re.M)
TS_OBJ_KEY_ARROW = re.compile(r"(?:^|[{,])\s*([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?"
                              + TS_ARROW_PARAMS + r"\s*\Z", re.M)
METHOD_PREFIX = re.compile(r"(?:(?<![\w$])(?:static|async|get|set|public|private|protected|"
                           r"readonly|override)\s*|[#*]\s*)+$")
# Keywords that are a method's name where a method stands (`delete(uri) {`),
# but not the control words, since `} catch (e) {` stands there too.
METHOD_KEYWORDS = {"delete", "new", "import", "export", "default"}
STATEMENT_WORDS = {"const", "let", "var", "function", "return", "if", "for", "while", "class",
                   "export", "import", "throw", "try", "switch"}


class JSScanner:
    """Comments dropped, strings kept apart from code, braces counted: enough
    to know which function a call or a piece of markup sits in."""

    IDENT = re.compile(r"[A-Za-z_$][\w$]*")
    REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")

    def __init__(self, text, sink, line0=1, top="(top level)", shape_methods=True, base=0,
                 fn_words=None, words=None, ts=False, jsx=False):
        self.s = text
        self.words = words or (JS_KEYWORDS, TYPE_WORDS, MODIFIERS)
        self.ts = ts
        self.jsx = jsx
        self.fn_generic = 0      # inside `fun <T, R : Comparable<R>>`
        self.class_ctx = False   # a template's ${} inside a className
        self.shadow = {}         # id(def) -> names its parameters and locals take
        self.before_fn = ""      # what stood before `function`: `(` makes it an expression
        self.pre_async = ""
        self.params = TS_ARROW_PARAMS if ts else ARROW_PARAMS
        self.obj_key = TS_OBJ_KEY_ARROW if ts else OBJ_KEY_ARROW
        self.mm_close = None     # where a method header's own `)` closed, for `): T {`
        self.kw, self.types, self.modifiers = self.words
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
        # the paren depth at each open brace: an arrow assigned in parens
        # opened since is a parameter's default, not a definition
        self.brace_parens = []
        self.paren_at_pending = 0
        self.maybe_method = None
        self.receiver = False
        self.exprs = []          # [(def, depth, parens + brackets, len(stack))] of open `x => expr`
        self.brackets = 0        # [ ] open, so a comma in an array does not end an arrow
        self.tok_line = line0    # the line of the last token read
        self.blank = None        # a list to collect (start, end) of every string,
                                 # template, regex and comment, for code_only()

    def add_def(self, name, line, kind, parent):
        # a definition is what its name means from here on, not a local
        # that shadows it: `const rowFor = () =>` is the function rowFor
        for k in self.shadow.values():
            k.discard(name)
        return self.sink.add_def(name, line, kind, parent)

    def enclosing(self):
        # an open `x => expr` holds what is called in its expression, unless
        # a body brace opened inside it since
        if self.exprs and self.exprs[-1][3] == len(self.stack):
            return self.exprs[-1][0]["name"]
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
                self.tok_line = self.line
                continue
            if c == "`":
                at = self.i
                self.template()
                self.span(at, self.i)
                self.tok_line = self.line
                continue
            if c == "/" and self.regex_allowed():
                at = self.i
                self.regex()
                self.span(at, self.i)
                self.tok_line = self.line
                continue
            m = self.IDENT.match(s, self.i)
            if m:
                j = m.end()
                while j < n and s[j] in " \t":
                    j += 1
                self.ident(m.group(0), s[j:j + 1], self.last_sig == ".")
                self.i = m.end()
                self.tok_line = self.line
                continue
            self.punct(c)
            self.i += 1
            self.tok_line = self.line

    # -- pieces --------------------------------------------------------------
    def span(self, a, b):
        if self.blank is not None:
            self.blank.append((a, b))

    def regex_allowed(self):
        # `</td>` is a closing tag wherever it stands, and in JSX `/>` ends
        # one: read as a regex either ran to the next slash and took the
        # braces between with it
        if self.last_sig == "<" or (self.jsx and self.s[self.i + 1:self.i + 2] == ">"):
            return False
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
        if j >= n or s[j] == "\n":
            # no closing slash on the line: a division, or JSX's `</span>`,
            # not a regex, and the newline is still to be counted
            self.i += 1
            self.last_sig = "/"
            return
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
        if j >= n or s[j] == "\n":
            # a quote left open at the line's end is no string: JSX text's
            # "isn't</p>}" or Rust's 'a. Taken as the one character it is,
            # so the brace after it and the newline are both still counted.
            self.i += 1
            self.last_sig = q
            return
        body = s[self.i + 1:j]
        self.saw_string(body, self.line, self.class_ctx_at(self.i))
        self.i = j + 1
        self.last_sig = "'s'"

    def template(self):
        s, n = self.s, len(self.s)
        j = self.i + 1
        chunk = []
        start_line = self.line
        cls = self.class_ctx_at(self.i)
        while j < n:
            c = s[j]
            if c == "\\":
                chunk.append(s[j:j + 2])
                j += 2
                continue
            if c == "`":
                break
            if s[j:j + 2] == "${":
                self.saw_string("".join(chunk), start_line, cls)
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
                                self.base + j + 2, self.fn_words, self.words, self.ts, self.jsx)
                sub.stack = [(n, dp, None) for n, dp, _ in self.stack]
                if self.pending is not None and self.parens > self.paren_at_pending:
                    # in a default parameter, `function f(fmt = v => `${g(v)}`)`:
                    # the call is f's, as one outside a template there is (B761)
                    sub.stack.append((self.pending["name"], -1, None))
                elif self.exprs and self.exprs[-1][3] == len(self.stack):
                    # inside `x => `...${f()}...``: the call is the arrow's
                    sub.stack.append((self.exprs[-1][0]["name"], -1, None))
                sub.class_ctx = cls      # `chip ${on ? 'on' : ''}` in a className
                sub.run()
                self.line += inner.count("\n")
                j = k
                start_line = self.line
                continue
            if c == "\n":
                self.line += 1
            chunk.append(c)
            j += 1
        self.saw_string("".join(chunk), start_line, cls)
        self.i = min(j + 1, n)
        self.last_sig = "'s'"

    def saw_string(self, body, line, cls=False):
        fn = self.enclosing()
        if REL_PATH.fullmatch(body):
            # require('../public/engine.js') or import './game': the file it
            # names, relative to this one, so a suite that loads it reaches it
            rel = os.path.normpath(os.path.join(os.path.dirname(self.sink.path), body))
            if not rel.startswith(".."):
                # an "import", matched only against a changed file itself: two
                # files importing the solver are not each other's suites'
                self.sink.add_draw(rel, "import", line, fn)
        for what, kind in strings_draw(body):
            self.sink.add_draw(what, kind, line, fn)
        if cls and re.fullmatch(r"[\w\s-]*", body):
            for tok in body.split():
                if re.fullmatch(r"[A-Za-z_][\w-]*", tok):
                    self.sink.add_draw(tok, "class", line, fn)
        for name in handler_calls(body):
            self.sink.add_call(name, "", line, fn)

    def class_ctx_at(self, at):
        return self.class_ctx or bool(CLASS_CTX.search(self.s[max(0, at - 200):at]))

    def generic_name(self):
        s, k, depth = self.s, self.i - 1, 0
        while k >= 0 and s[k] in " \t":
            k -= 1
        lo = max(0, k - 300)
        while k >= lo:
            ch = s[k]
            if ch == ">":
                depth += 1
            elif ch == "<":
                depth -= 1
                if depth == 0:
                    m = re.search(r"([A-Za-z_$][\w$]*)\s*$", s[max(0, k - 80):k])
                    return m.group(1) if m and m.group(1) not in self.kw else ""
            elif ch in ";{}()":
                return ""
            k -= 1
        return ""

    def code_before(self, pos):
        # the code that stands before pos: the comment lines above
        # `shown(){` are not it, however many there are
        s = self.s
        while True:
            start = s.rfind("\n", 0, pos)
            code = LINE_COMMENT.sub("", s[start + 1:pos]).rstrip()
            if code.endswith("*/"):
                # a JSDoc block over lines: what stands before its /*
                pos = s.rfind("/*", 0, start + 1 + len(code) - 2)
                if pos < 0:
                    return ""
                continue
            # `static`, `async`, `get`, `#`, `*`: a method's own prefix
            code = METHOD_PREFIX.sub("", code).rstrip()
            if code or start < 0:
                return code
            pos = start

    def nest(self):
        return self.parens + self.brackets

    def close_exprs(self, done, end=None):
        # `const f = x =>` and an expression running on for lines: it ends
        # where its expression does, not on its first line, so a change to
        # its fourth line falls inside it
        while self.exprs and done(*self.exprs[-1][1:3]):
            d = self.exprs.pop()[0]
            d["end"] = max(d["line"], self.line if end is None else end)

    def ident(self, word, nxt="", after_dot=False):
        if self.pending is not None and self.pending["kind"] == "class" \
                and self.types is JS_TYPE_WORDS and self.last_sig == self.pending["name"] \
                and word not in ("extends", "implements"):
            # `class items take any...` in JSX text: in JavaScript a class's
            # name is followed by extends, implements, < or its {, never a word
            self.sink.defs.remove(self.pending)
            self.pending = None
        if self.exprs and word in STATEMENT_WORDS and self.line > self.tok_line:
            # a statement on a new line after one with no `;`
            self.close_exprs(lambda dp, pr: dp == self.depth and pr == self.nest(), self.tok_line)
        # `of` is for-of's word after a binding (`x of`, `] of`, `} of`) and
        # a name anywhere else: `const of = s =>` and its calls are real
        self.of_kw = word == "of" and not after_dot and self.last_kw != "function" and (
            self.last_sig in ("]", "}") or bool(self.IDENT.fullmatch(self.last_sig or "")))
        if self.of_kw:
            self.last_sig = "of"
            self.last_ident = ""
            return
        self.prev_ident, self.last_ident = self.last_ident, word
        self.ident_after_dot = after_dot
        # A use by name that is not a call and not a property: passed,
        # assigned, listed. What tells dead code from a handler somebody
        # hands to onclick without calling it.
        # A parameter or a local that takes a function's name is not that
        # function handed on: `fun f(reach: Float)` and its uses named reach
        # five times (B590). Its declaration shadows the name for the rest
        # of the function it is declared in.
        in_params = self.pending is not None and self.parens > getattr(self, "paren_at_pending", 0)
        if not after_dot and nxt != "(" and word not in self.kw and (
                (in_params and nxt in ":,)=" and self.last_sig in ("(", ",", "val", "var"))
                or self.last_sig in ("val", "var", "let", "const")):
            owner = self.pending if in_params else (self.stack[-1][2] if self.stack else None)
            if owner is not None:
                self.shadow.setdefault(id(owner), set()).add(word)
            if not in_params:
                # counted as before, so unused still reads `const f = () =>`
                # as the one use it subtracts, but marked: who-calls does not
                # list a declaration as the function handed on
                self.sink.add_ref(word, self.line, self.enclosing())
                self.sink.passed[-1]["decl"] = True
        elif not after_dot and nxt == "=" and self.parens and self.last_sig in ("(", ",") \
                and self.s[self.i + len(word):].lstrip(" \t")[1:2] != "=":
            pass                     # Kotlin's named argument, add(reach = 0.6f): a name, not a use
        elif nxt != "(" and not after_dot and word not in self.kw \
                and self.last_kw not in ("function", "class") and not word[0].isdigit() \
                and not any(word in self.shadow.get(id(d), ()) for _, _, d in self.stack if d is not None):
            self.sink.add_ref(word, self.line, self.enclosing())
        if self.last_kw == "function" and self.fn_generic:
            self.last_sig = word     # a type parameter: fun <T> name
            return
        if after_dot and self.pending is not None and self.pending.get("recv"):
            # Kotlin's and Swift's extension, `fun <T> List<T>.move(`: the
            # name is the last one before the parameters
            self.pending["name"] = word
            self.last_sig = word
            return
        if word == "async":
            self.pre_async = self.last_sig
        if self.last_kw == "function" and (self.last_sig in self.fn_words or self.last_sig == ">") \
                and word not in self.fn_words and word != "interface":
            # what follows the keyword is the name, whatever other languages
            # make of the word: Kotlin's fun record(, fun delete(, fun open(
            self.begin_def(word, "function")
            # `(function initGuide() {...})()` names nothing outside itself:
            # nothing calls it by that name, and it is not dead (B585)
            self.pending["named_expr"] = self.before_fn in ("(", "=", ",", ":", "!", "?", "&", "|",
                                                            "return", "=>")
            self.pending["recv"] = bool(self.fn_words & {"fun", "func"})
            self.last_kw = ""
            self.last_sig = word
            return
        if word in self.fn_words:
            self.last_kw = "function"
            self.before_fn = self.pre_async if self.last_sig == "async" else self.last_sig
        elif word in self.types and not after_dot and nxt not in ":=,;)?&|.[":
            # a type's keyword, not a property or a key that has its name
            self.last_kw = "class"
        elif word in self.modifiers:
            pass                     # a modifier: the keyword before it still stands
        elif self.last_kw == "function" and self.last_sig == ")" and self.receiver:
            # Go: func (r *T) NAME(  : the receiver came first
            self.receiver = False
            self.begin_def(word, "function")
            self.last_kw = ""
        else:
            if self.last_kw == "function" and word not in self.kw:
                # function NAME(  /  fun NAME(  /  fn NAME(  /  func NAME(
                self.begin_def(word, "function")
                self.last_kw = ""
            elif self.last_kw == "class" and word not in self.kw:
                self.begin_def(word, "class")
                self.last_kw = ""
            elif word not in self.kw:
                self.last_kw = ""
        self.last_sig = word

    def begin_def(self, name, kind):
        if self.stack and self.stack[-1][1] == self.depth and self.pending is None:
            parent = self.stack[-1][0]
        else:
            parent = self.enclosing() if self.stack else ""
        d = self.add_def(name, self.line, kind, "" if parent == self.top else parent)
        self.pending = d
        self.pending_depth = self.depth
        self.pending_anon = self.pending_async = False
        self.pending_close = None
        self.pending_open = False    # its own ( reached
        self.pending_angles = 0      # inside <...> before it: Map<String, Any?>.long(

    def punct(self, c):
        if self.pending is not None and not getattr(self, "pending_open", True) and c in "<>":
            self.pending_angles = max(0, getattr(self, "pending_angles", 0) + (1 if c == "<" else -1))
        if self.last_kw == "function" and c == "<" and (self.fn_generic or self.last_sig in self.fn_words):
            self.fn_generic += 1
            self.last_sig = "<"
            return
        if self.fn_generic and c == ">":
            self.fn_generic -= 1
            self.last_sig = ">"
            return
        mm = getattr(self, "maybe_method", None)
        self._punct(c)
        if c == "(" and mm and self.parens - 1 > mm[2]:
            # a paren inside a method's own parameters, `(number | null)[]`
            # or a default `x = f()`, does not undo the method's header
            self.maybe_method = mm

    def _punct(self, c):
        s = self.s
        if c == "(":
            prev = self.last_sig
            if prev == ">" and self.ts:
                # TypeScript's generic call, `new Map<number, Set<number>>()`:
                # the name before the matching `<`
                g = self.generic_name()
                if g:
                    prev = g
                    if self.pending is not None and self.pending["name"] == g:
                        self.maybe_method = None
                        self.paren_at_pending = self.parens
                        self.parens += 1
                        self.last_sig = "("
                        return
                    self.sink.add_call(g, "", self.line, self.enclosing())
                    self.maybe_method = None
                    self.parens += 1
                    self.last_sig = "("
                    return
            if prev == "." and s[self.i - 2:self.i] == "?." and self.last_ident:
                # an optional call, `TABKINDS[k]?.open?.(t)`: a call of open
                prev = self.last_ident
                self.sink.add_call(prev, "", self.line, self.enclosing())
                self.maybe_method = None
                self.parens += 1
                self.last_sig = "("
                return
            if self.pending is not None and self.pending["name"] == prev \
                    and self.pending["line"] == self.line:
                # the ( of a definition's own parameter list, not a call
                self.maybe_method = None
                self.pending["recv"] = False
                self.pending_open = True
                self.paren_at_pending = self.parens
                self.parens += 1
                self.last_sig = "("
                return
            if prev in METHOD_KEYWORDS and self.shape_methods and self.last_kw != "function" \
                    and not getattr(self, "ident_after_dot", False):
                # `async delete(uri) {` in a class: a keyword is a method's name
                # where a method stands, and is never a call by itself
                w = s[max(0, self.i - 240):self.i]
                code = self.code_before(self.i - (len(w) - len(w.rstrip())) - len(prev))
                self.maybe_method = (prev, self.line, self.parens) \
                    if code.endswith(("{", ",", ";", "}")) or not code else None
                self.parens += 1
                self.last_sig = "("
                return
            if self.IDENT.fullmatch(prev or "") and self.last_kw != "function" \
                    and not (prev == "of" and getattr(self, "of_kw", False)) \
                    and (prev not in self.kw or getattr(self, "ident_after_dot", False)):
                # (a keyword after a dot is a method: `p.catch(`, `m.delete(`)
                # NAME( : a call, unless it is a method definition   name(...){
                before = s[max(0, self.i - 240):self.i]
                code = self.code_before(self.i - (len(before) - len(before.rstrip())) - len(prev))
                before = before.rstrip()
                head = before[:-len(prev)].rstrip()
                if self.shape_methods and (code.endswith(("{", ",", ";", "}")) or not code):
                    # possibly an object/class method: decided at the ) {
                    self.maybe_method = (prev, self.line, self.parens)
                else:
                    self.maybe_method = None
                qual = ""
                if head.endswith("."):
                    qm = re.search(r"([A-Za-z_$][\w$]*)\s*\.$", head)
                    qual = qm.group(1) if qm else ""
                # a call in a default parameter, `f(seed = Date.now())`, is f's
                in_params = self.pending is not None and self.parens > self.paren_at_pending
                self.sink.add_call(prev, qual, self.line,
                                   self.pending["name"] if in_params else self.enclosing())
            elif prev == "func" and self.last_kw == "function":
                # Go: `func (` is a receiver, and the name comes after it
                self.receiver = True
                self.maybe_method = None
            elif prev in self.fn_words or prev == "async":
                # an anonymous function: `function(` or `async (`; body follows.
                # Its own parameter list, so its { is its body even inside a
                # call's parentheses, and the keyword spent, so the first name
                # in the body is not read as the function's (B545).
                # `x.animate = function(` is named for what it is assigned to,
                # as an arrow is; one handed straight to a call stays anonymous
                # (the text before the keyword, whatever space stands between it
                # and its paren: `Module._load = function (req)`)
                w = s[max(0, self.i - 240):self.i]
                kw_at = self.i - (len(w) - len(w.rstrip())) - len(prev)
                head = s[max(0, kw_at - 200):kw_at]
                named = re.search(r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s+)?$", head) \
                    if prev in self.fn_words else None
                if named and named.group(1) not in self.kw:
                    self.pending = self.add_def(named.group(1), self.line, "function",
                                                     self.enclosing_or_blank())
                    self.pending["prop"] = named.start(1) > 0 and head[named.start(1) - 1] == "."
                else:
                    self.pending = self.add_def("(anonymous)", self.line, "function", "")
                self.pending_depth = self.depth
                self.pending_anon = True
                self.pending_async = prev == "async"
                self.paren_at_pending = self.parens
                self.last_kw = ""
                self.maybe_method = None
            else:
                self.maybe_method = None
            self.parens += 1
            self.last_sig = "("
            return
        if c == ")":
            self.parens = max(0, self.parens - 1)
            if self.maybe_method and self.maybe_method[2] == self.parens:
                self.mm_close = self.i + 1
            if self.pending is not None and self.parens == self.paren_at_pending:
                self.pending_close = self.i + 1
            self.close_exprs(lambda dp, pr: pr > self.nest())
            self.last_sig = ")"
            return
        if c == "{" and self.ts and self.pending is not None \
                and getattr(self, "pending_close", None) is not None and self.pending_close <= self.i \
                and re.fullmatch(r"\s*:\s*", s[self.pending_close:self.i]):
            # TypeScript's `function f(): { a: T } {`: the first brace after
            # the colon is the return type's, the next one is the body
            self.depth += 1
            self.brace_parens.append((self.parens, self.in_parens() and self.opens_pattern()))
            self.last_sig = "{"
            return
        if c == "{":
            if self.pending is not None and getattr(self, "pending_async", False) \
                    and self.last_sig == "=>" and self.parens <= self.paren_at_pending:
                # `const send = async () => {`: the arrow is named by what it
                # is assigned to, as one without `async` is, not "(anonymous)"
                name = self.arrow_name()
                if name:
                    self.pending.update(name=name, kind="arrow", prop=self._prop,
                                        parent=self.enclosing_or_blank())
                self.pending_async = False
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
                    d = self.add_def(name, self.line, "arrow", self.enclosing_or_blank())
                    d["at"] = self.base + self.i + 1
                    d["prop"] = getattr(self, "_prop", False)
                    self.stack.append((name, self.depth, d))
                else:
                    self.stack.append((self.enclosing(), self.depth, None))
            elif getattr(self, "maybe_method", None) and self.maybe_method[2] == self.parens \
                    and (self.last_sig == ")" or (self.ts and self.mm_close is not None and re.fullmatch(
                        r"\s*:\s*[\w$<>\[\],.|&?'\" ]+", s[self.mm_close:self.i]))):
                # (TypeScript: `private bound(a: Vec): [number, number] {`)
                # its own `)` just closed: in `if (a(b, c(d))){` the `)` before
                # the brace is the if's, and c is a call
                name, line, _ = self.maybe_method
                d = self.add_def(name, line, "method", self.enclosing_or_blank())
                d["at"] = self.base + self.i + 1
                self.stack.append((name, self.depth, d))
                # the call recorded for `name(` was the header, not a call
                for cl in reversed(self.sink.calls):
                    if cl["name"] == name and cl["line"] == line:
                        self.sink.calls.remove(cl)
                        break
            if not (self.maybe_method and self.parens > self.maybe_method[2]):
                # (a `{` inside its own parameters, `say(a, x = {})` or a
                # destructured `constructor({ now } = {})`, leaves it be)
                self.maybe_method = None
            self.depth += 1
            self.brace_parens.append((self.parens, self.in_parens() and self.opens_pattern()))
            self.last_sig = "{"
            return
        if c == "}":
            self.depth -= 1
            if self.brace_parens:
                self.brace_parens.pop()
            if self.pending is not None and self.pending_depth > self.depth:
                # an interface's `fun f(x: Int)` with no body ends with its scope
                self.pending = None
            self.close_exprs(lambda dp, pr: dp > self.depth)
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
                anon = None
                if self.pending is not None and getattr(self, "pending_anon", False) \
                        and self.parens <= self.paren_at_pending:
                    # `async () => expr` or PHP's `fn() => expr` has no body
                    # brace: the header would otherwise take the next `{` it
                    # meets. Named by an assignment below, or kept anonymous
                    # and over where its expression is.
                    anon, self.pending = self.pending, None
                    self.pending_async = self.pending_anon = False
                m = re.search(r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?" + self.params + r"\s*$",
                              s[max(0, self.i - 200):self.i])
                if m and self.is_default(s[max(0, self.i - 200):self.i], m.start(1)):
                    m = None
                # (the window's first line is cut short unless it is the file's)
                w = s[max(0, self.i - 200):self.i]
                key = None if m else self.obj_key.search(w if self.i <= 200 else w[w.find("\n") + 1:])
                if anon is not None and ((m and m.group(1) not in self.kw) or key):
                    self.sink.defs.remove(anon)
                elif anon is not None:
                    anon["expr"] = True
                    self.exprs.append((anon, self.depth, self.nest(), len(self.stack)))
                if m and m.group(1) not in self.kw and self.last_kw != "function":
                    d = self.add_def(m.group(1), self.line, "arrow", self.enclosing_or_blank())
                    d["expr"] = True
                    self.exprs.append((d, self.depth, self.nest(), len(self.stack)))
                    # A property (`nb.clashResume = () =>`): the object's to
                    # call, so nothing here can see its calls (B271).
                    d["prop"] = m.start(1) > 0 and s[max(0, self.i - 200):self.i][m.start(1) - 1] == "."
                elif key and self.last_kw != "function":
                    # `render: (el, t) => renderProfileInto(el)` in a table:
                    # its calls are its own, not the top level's
                    d = self.add_def(key.group(1), self.line, "arrow", self.enclosing_or_blank())
                    d.update(expr=True, prop=True)
                    self.exprs.append((d, self.depth, self.nest(), len(self.stack)))
            self.i += 1
            self.last_sig = "=>"
            return
        if c == "[":
            self.brackets += 1
        elif c == "]":
            self.brackets = max(0, self.brackets - 1)
            self.close_exprs(lambda dp, pr: pr > self.nest())
        if c in ";,":
            self.close_exprs(lambda dp, pr: dp == self.depth and pr == self.nest())
            # A definition header still waiting for its body is dropped by a
            # `;` at its own level, or a `,` outside its parameter list: the
            # commas INSIDE the list used to drop it, which is every function
            # with two parameters, and their bodies then read as top level.
            if self.pending is not None and self.pending_depth == self.depth \
                    and (c == ";" or self.parens <= getattr(self, "paren_at_pending", 0)) \
                    and not (self.ts and self.brackets) \
                    and not (c == "," and getattr(self, "pending_close", None) is not None) \
                    and not (c == "," and getattr(self, "pending_angles", 0)):
                # (not the comma of a TypeScript tuple, `): [number, number] {`,
                # nor one in a return type after the parameters closed,
                # Kotlin's `): Pair<Uri, String>? {`)
                self.pending = None
            self.last_sig = c
            return
        self.last_sig = c

    def enclosing_or_blank(self, up=0):
        st = self.stack[:-up] if up else self.stack
        # (an anonymous body at the top pushes the top's name: no parent)
        return st[-1][0] if st and st[-1][0] != self.top else ""

    def is_default(self, head, start):
        # A parameter's default, inside parens opened since the innermost
        # brace and right after `(`, `,` or `{`: `function nodePick(id, why
        # = () => "")` gave the map a function `why`, with the next
        # section's comment for what it says. `forEach(b => b.onclick = ()
        # => go())` is a handler, and stays one.
        if not self.in_parens() and not (self.brace_parens and self.brace_parens[-1][1]):
            # (nor in a brace opened in parens: `f({ now = () => 0 } = {})`)
            return False
        return bool(re.search(r"[(,{]\s*$", head[:start]))

    def opens_pattern(self):
        # a brace right after `(` or `,` is a destructured parameter; one
        # after `=>` or `)` is a body, `evaluate(() => { x = () => 0 })`
        return bool(re.search(r"[(,]\s*$", self.s[max(0, self.i - 80):self.i]))

    def in_parens(self):
        # inside parens opened since the innermost brace
        return self.parens > (self.brace_parens[-1][0] if self.brace_parens else 0)

    def arrow_name(self):
        # `const NAME = (...) =>` or `NAME = async x =>` : the identifier
        # before the `=` that precedes the arrow's parameters, on this line
        # or the one before.
        head = self.s[max(0, self.i - 200):self.i]
        m = re.search(r"([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?" + self.params + r"\s*=>\s*$", head)
        if m and self.is_default(head, m.start(1)):
            self._prop = False
            return ""
        # A property (`nb.clashResume = () =>`) is the object's to call:
        # kept as a definition for the attribution of what it draws, marked
        # so `unused` does not name it as never called (B271).
        self._prop = bool(m) and m.start(1) > 0 and head[m.start(1) - 1] == "."
        if m and m.group(1) not in self.kw:
            return m.group(1)
        # `name: (...) =>` in an object
        m = re.search(r"([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?" + self.params + r"\s*=>\s*$", head)
        if m:
            return m.group(1)
        return ""


def code_only(text, suffix=".js"):
    """The text with every string, template literal, regex and comment
    blanked to spaces, newlines kept, so a regex over it reads code and
    only code: `data-state="..."` inside a template is not an assignment
    to state."""
    sc = JSScanner(text, Sink("(code_only)"), shape_methods=suffix in SHAPE_METHODS,
                   fn_words=FN_BY_SUFFIX.get(suffix, set()), words=keywords_for(suffix),
                   ts=suffix in TS_SUFFIXES, jsx=suffix in JSX_SUFFIXES)
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


# ---- C and C++ (B544) -------------------------------------------------------
# Their own scanner, because the brace scanner above read them as JavaScript:
# every `struct X` mention (a parameter, a local, a cast) became a class, no
# C function header was a definition, and a prototype was a call. Here a
# scope is decided by what stands before its `{`, a function is a header
# ending in its parameter list at file, namespace or class level, a type is
# `struct|union|enum|class NAME {` (or a typedef's name after its `}`), a
# declaration ending in `;` is neither, and a call is only made inside a
# function. A JNI implementation (Java_pkg_Class_method) is also indexed
# under its Kotlin or Java method's name, the edge a JNI project needs.
C_CONTROL = {"if", "for", "while", "switch", "catch", "return", "sizeof", "do", "else",
             "alignof", "decltype", "typeof", "defined", "case", "new", "delete", "throw",
             "static_assert", "_Static_assert", "__attribute__", "__declspec", "noexcept",
             "alignas", "_Alignof", "offsetof", "goto", "operator"}
# Words a call can follow: `return f(x)`, `else g()`.
C_DECL_OK = {"return", "else", "case", "do", "throw", "new", "delete", "co_return", "co_yield",
             "co_await", "sizeof", "not", "and", "or", "goto"}
C_TYPE_HEAD = re.compile(r"(?:^|[\s;}])(?:typedef\s+)?(?:struct|union|enum(?:\s+class|\s+struct)?|class)"
                         r"\s+(?:__attribute__\s*\(\([^)]*\)\)\s*|alignas\s*\([^)]*\)\s*|[A-Z_]+_API\s+)*"
                         r"([A-Za-z_]\w*)\s*(?:final\s*)?(?::[^{;]*)?$")
C_FN_TAIL = re.compile(r"(?:\s|const\b|noexcept(?:\s*\([^()]*\))?|override\b|final\b|volatile\b|&&?|"
                       r"->\s*[\w:<>*&,\s]+|throw\s*\([^()]*\)|__attribute__\s*\(\([^)]*\)\)|"
                       r"[A-Z_][A-Z0-9_]*(?:\s*\([^()]*\))?)*$")
# The name inside a function-pointer return type: (*name(params)).
C_FP_RETURNER = re.compile(r"\(\s*[*&]\s*((?:[A-Za-z_]\w*\s*::\s*)*[A-Za-z_]\w*)\s*\([^()]*\)\s*\)\s*$")
# A K&R definition up to its brace: a type, the name, a list of bare
# identifiers, then each parameter's declaration ending in `;`.
C_KR_DEF = re.compile(r"[\w*]\s*\**\s*\b([A-Za-z_]\w*)\s*\(\s*[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*\s*\)"
                      r"\s*(?:[^;{}()=]+;\s*)+$")
C_NAME_BEFORE_PAREN = re.compile(r"((?:[A-Za-z_]\w*\s*::\s*)*~?[A-Za-z_]\w*|operator\s*[^\s(]+)\s*$")


def _c_blank(text):
    """Comments, strings, character literals and preprocessor lines turned
    to spaces, newlines kept, so what is left is the code."""
    out, i, n = list(text), 0, len(text)
    line_start = True
    # Preprocessor conditionals: their lines are noted here and settled in
    # _c_branches once the comments and strings are blanked.
    conds = []
    cond = re.compile(r"#\s*(if|ifdef|ifndef|elif|else|endif)\b")

    def blank(a, b):
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "
    while i < n:
        c = text[i]
        if c == "\n":
            line_start = True
            i += 1
            continue
        if line_start and c in " \t":
            i += 1
            continue
        if line_start and c == "#":
            j = i
            while j < n:
                k = text.find("\n", j)
                k = n if k < 0 else k
                if k > 0 and text[k - 1] == "\\":
                    j = k + 1
                    continue
                j = k
                break
            # a comment opened on a directive line runs on past it
            m = cond.match(text, i)
            if m:
                conds.append((m.group(1), i, j))
            blank(i, j)
            i = j
            continue
        line_start = False
        two = text[i:i + 2]
        if two == "//":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif two == "/*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c == '"' and text[max(0, i - 1)] == "R" and text[i + 1:i + 2] != "\\":
            m = re.match(r'"([^(\s]{0,16})\(', text[i:])
            if m:
                end = text.find(")" + m.group(1) + '"', i)
                j = n if end < 0 else end + len(m.group(1)) + 2
            else:
                j = i + 1
            blank(i, j)
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] != c and text[j] != "\n":
                j += 2 if text[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
        else:
            i += 1
    _c_branches(out, conds, blank)
    return "".join(out)


def _c_branches(out, conds, blank):
    """Which branches of each #if the scanner reads. Every one, when each
    branch's braces balance by themselves: the SIMD paths of ggml, one
    whole function per branch, were missing from the map behind their
    first branch (B805). Only the first, the rest blanked, when any branch
    is out of balance, since two that each open a brace left one unclosed
    and the rest of the file inside the function above it (B554). An inner
    #if is settled before the one around it, so its blanked branches are
    not counted there."""
    def balance(a, b):
        part = "".join(out[a:b])
        return part.count("{") - part.count("}")
    stack = []
    for word, i, j in conds:
        if word in ("if", "ifdef", "ifndef"):
            stack.append([[j, None]])
        elif not stack:
            continue
        elif word in ("elif", "else"):
            stack[-1][-1][1] = i
            stack[-1].append([j, None])
        else:
            group = stack.pop()
            group[-1][1] = i
            if len(group) > 1 and any(balance(a, b) for a, b in group):
                for a, b in group[1:]:
                    blank(a, b)


def _c_untemplate(head):
    """A header with its `template <...>` lists cut out: a default there,
    `int N = 0` or `enable_if<...>::type = 0`, is no assignment, and the
    function under it was dropped as one (B807)."""
    out, i = [], 0
    for m in re.finditer(r"\btemplate\s*<", head):
        if m.start() < i:
            continue
        depth, k = 0, m.end() - 1
        while k < len(head):
            depth += {"<": 1, ">": -1}.get(head[k], 0)
            if depth == 0:
                break
            k += 1
        out.append(head[i:m.start()])
        i = k + 1
    out.append(head[i:])
    return "".join(out)


def _c_params_end(head):
    """Where the `)` closing a function's parameter list is in a header, or
    -1: a `)` followed only by what may follow one (const, noexcept,
    override, `-> type`, an attribute or a macro). Tried from the last few
    `)` back, and matched whole, so a long header costs no backtracking."""
    pos = len(head)
    for _ in range(4):
        pos = head.rfind(")", 0, pos)
        if pos < 0:
            return -1
        if C_FN_TAIL.fullmatch(head[pos + 1:]):
            return pos
    return -1


def _jni_method(name):
    """(Class, method) a JNI symbol implements, or None."""
    if not name.startswith("Java_"):
        return None
    parts = name[5:].replace("_1", "\x01").split("_")
    parts = [p.replace("\x01", "_") for p in parts if p and not p.startswith("_")]
    if len(parts) < 2:
        return None
    return parts[-2], parts[-1]


def scan_c(text, sink):
    scan_sections(text, sink)
    # #define NAME and NAME(...): what a header's API often is (B554).
    for m in re.finditer(r"(?m)^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)", text):
        sink.add_def(m.group(1), text.count("\n", 0, m.start()) + 1, "macro", "")
    code = _c_blank(text)
    n = len(code)
    nl = [m.start() for m in re.finditer("\n", code)]

    class _Lines:
        def __getitem__(self, i):
            return bisect.bisect_left(nl, i) + 1
    line_at = _Lines()
    # Each scope: (kind, name, def-or-None, start of what may precede the
    # next brace). kinds: file, ns (namespace, extern "C"), type, fn, block.
    scopes = [["file", "", None, 0]]
    i = 0
    ident = re.compile(r"[A-Za-z_]\w*")

    def in_fn():
        return any(s[0] == "fn" for s in scopes)

    def fn_name():
        for s in reversed(scopes):
            if s[0] == "fn":
                return s[1]
        return "(top level)"

    def type_parent():
        for s in reversed(scopes):
            if s[0] == "type":
                return s[1]
            if s[0] == "fn":
                return ""
        return ""

    def header(start, end):
        """What stands before a `{`: back to the last ; { } at this level,
        parentheses kept whole."""
        return code[start:end]

    while i < n:
        c = code[i]
        if c == "{":
            top = scopes[-1]
            head = header(top[3], i)
            flat = " ".join(head.split())
            kind, name, d = "block", "", None
            if top[0] in ("file", "ns", "type"):
                tm = C_TYPE_HEAD.search(flat)
                nsm = re.search(r"(?:^|\s)namespace(?:\s+([\w:]+))?\s*$", flat)
                if nsm or re.fullmatch(r"\s*extern\s*", flat):
                    kind = "ns"
                    if nsm and nsm.group(1):
                        nd = sink.add_def(nsm.group(1).split("::")[-1], line_at[top[3] + max(0, head.rfind(nsm.group(1)))],
                                          "namespace", type_parent())
                        nd["end"] = nd["line"]
                elif tm and "(" not in flat.split(tm.group(1))[0][-1:]:
                    kind, name = "type", tm.group(1)
                    d = sink.add_def(name, line_at[top[3] + max(0, head.rfind(name))], "class", type_parent())
                elif re.search(r"(?:^|\s)(?:typedef\s+)?(?:struct|union|enum|class)\s*$", flat):
                    kind = "type"           # anonymous: a typedef names it after the }
                    name = ""
                    d = {"typedef": flat.lstrip().startswith("typedef")}
                elif _c_params_end(head) >= 0:
                    # Cut a constructor's initializer list: `) : a(x), b(y)`
                    depth, cut = 0, len(head)
                    for k, ch in enumerate(head):
                        if ch == "(":
                            depth += 1
                        elif ch == ")":
                            depth -= 1
                        elif ch == ":" and depth == 0 and head[k - 1:k + 1] != "::" \
                                and head[k:k + 2] != "::" and ")" in head[:k]:
                            cut = k
                            break
                    h = head[:cut]
                    # the parameter list: the last balanced (...) before the tail
                    end = _c_params_end(h)
                    body = h[:end + 1] if end >= 0 else ""
                    if body.rstrip().endswith(")"):
                        depth, k = 0, len(body.rstrip()) - 1
                        while k >= 0:
                            if body[k] == ")":
                                depth += 1
                            elif body[k] == "(":
                                depth -= 1
                                if depth == 0:
                                    break
                            k -= 1
                        before = body[:k]
                        # An explicit specialization names its arguments
                        # after the name (template <> int tmax<int>(...)),
                        # which is the name's: report #85, B575.
                        tb = before.rstrip()
                        if tb.endswith(">") and not tb.endswith("operator>") and not tb.endswith("->"):
                            depth_, q = 0, len(tb) - 1
                            while q >= 0:
                                depth_ += {">": 1, "<": -1}.get(tb[q], 0)
                                if depth_ == 0:
                                    break
                                q -= 1
                            if q > 0:
                                before = tb[:q]
                        m = C_NAME_BEFORE_PAREN.search(before)
                        if not m:
                            # A function returning a function pointer:
                            # int (*returns_fp(void))(int, void *) {...}.
                            m = C_FP_RETURNER.search(before)
                        if m and k > 0 and "=" not in _c_untemplate(before).split("operator")[0].replace("==", ""):
                            full = " ".join(m.group(1).split())
                            parts = [p.strip() for p in full.split("::")]
                            nm, qual = parts[-1], (parts[-2] if len(parts) > 1 else "")
                            if nm.split()[0] not in C_CONTROL or nm.startswith("operator"):
                                kind, name = "fn", nm
                                at = top[3] + body.rfind(m.group(1), 0, k)
                                d = sink.add_def(nm, line_at[max(0, at)], "def", qual or type_parent())
                                jni = _jni_method(nm)
                                if jni:
                                    alias = sink.add_def(jni[1], line_at[max(0, at)], "jni", jni[0])
                                    alias["jni"] = nm
                                    d["implements"] = f"{jni[0]}.{jni[1]}"
                elif top[0] == "file":
                    # A K&R definition: the parameters' types between the
                    # list and the brace, each its own `;`, so the header
                    # since the last `;` is only `int b` (report #85).
                    wide = code[max(code.rfind("}", 0, i), code.rfind("{", 0, i)) + 1:i]
                    km = C_KR_DEF.search(wide)
                    if km and km.group(1) not in C_CONTROL:
                        kind, name = "fn", km.group(1)
                        at = i - len(wide) + km.start(1)
                        d = sink.add_def(name, line_at[at], "def", "")
            elif top[0] in ("fn", "block"):
                kind = "block"
            if d is not None and "file" in d:
                d["at"] = i + 1
            scopes.append([kind, name, d, i + 1])
            i += 1
            continue
        if c == "}":
            if len(scopes) > 1:
                kind, name, d, start = scopes.pop()
                if d is not None and "file" in d:
                    d["end"] = line_at[i]
                # A typedef's name after its }: the type of an anonymous one,
                # and an alias of a named one (typedef struct point {} point_t).
                typedef = kind == "type" and ((d and d.get("typedef")) or
                                              re.search(r"(?:^|[\s;}])typedef\s", code[scopes[-1][3]:start]))
                if typedef:
                    m = re.match(r"\s*\*?\s*([A-Za-z_]\w*)\s*[;,\[]", code[i + 1:i + 200])
                    if m and m.group(1) != name:
                        nd = sink.add_def(m.group(1), line_at[i + 1 + m.start(1)],
                                          "class" if not name else "typedef", type_parent())
                        nd["end"] = nd["line"]
            scopes[-1][3] = i + 1
            i += 1
            continue
        if c == ";":
            top = scopes[-1]
            if top[0] in ("file", "ns", "type"):
                stmt = " ".join(code[top[3]:i].split())
                # typedef int (*callback_fn)(int); typedef unsigned long ulong;
                td = re.search(r"(?:^|\s)typedef\s", stmt)
                fp = re.search(r"\(\s*\*\s*([A-Za-z_]\w*)\s*\)\s*\(", stmt) if td else None
                tm = fp or (re.search(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\])?$", stmt) if td else None)
                if tm and "{" not in stmt:
                    nm = tm.group(1)
                    at = top[3] + code[top[3]:i].rfind(nm)
                    nd = sink.add_def(nm, line_at[at], "typedef", type_parent())
                    nd["end"] = nd["line"]
                elif "=" not in stmt and not stmt.startswith(("return", "using", "friend")):
                    # A prototype: a declaration, findable, and never a call.
                    end = _c_params_end(code[top[3]:i])
                    if end >= 0:
                        before = code[top[3]:top[3] + end]
                        depth_, k = 0, end
                        while k >= 0:
                            ch = before[k] if k < len(before) else ")"
                            if ch == ")":
                                depth_ += 1
                            elif ch == "(":
                                depth_ -= 1
                                if depth_ == 0:
                                    break
                            k -= 1
                        pm = C_NAME_BEFORE_PAREN.search(before[:k]) if k > 0 else None
                        if pm and re.search(r"[\w*&>]\s+[*&]*\s*(?:[\w:~]+)\s*$", before[:k]):
                            nm = " ".join(pm.group(1).split()).split("::")[-1]
                            if nm.split()[0] not in C_CONTROL:
                                nd = sink.add_def(nm, line_at[top[3] + before.rfind(pm.group(1), 0, k)],
                                                  "decl", type_parent())
                                nd["end"] = nd["line"]
            scopes[-1][3] = i + 1
            i += 1
            continue
        m = ident.match(code, i)
        if m and (i == 0 or not (code[i - 1].isalnum() or code[i - 1] == "_")):
            word = m.group(0)
            j = m.end()
            while j < n and code[j] in " \t\n":
                j += 1
            if in_fn():
                pre = code[max(0, i - 80):i].rstrip()
                pw = re.search(r"([A-Za-z_]\w*)$", pre)
                # `Widget w(3);`: a name straight after a type name is the
                # variable being made, not a function called (B554).
                declared = bool(pw) and pw.group(1) not in C_DECL_OK
                if code[j:j + 1] == "(" and word not in C_CONTROL and not declared:
                    qm = re.search(r"([A-Za-z_]\w*)\s*(?:\.|->|::)$", pre)
                    # `Type name(args);` is a declaration with a constructor
                    # call; still a call, which is what it is.
                    sink.add_call(word, qm.group(1) if qm else "", line_at[i], fn_name())
                elif code[j:j + 1] != "(":
                    sink.add_ref(word, line_at[i], fn_name())
            elif code[j:j + 1] != "(" and code[max(0, i - 80):i].rstrip()[-1:] in ("=", ",", "{", ")", "&"):
                # At file scope, a name after `=`, `,`, `{`, a cast's `)` or
                # `&` is a value being stored: `.to_float = (fn_t) f,` in a
                # dispatch table is how ggml wires every routine, and C's
                # tables generally (report #83, B569). Only names the tree
                # defines as functions are kept from these.
                sink.add_ref(word, line_at[i], fn_name())
            i = m.end()
            continue
        i += 1


def scan_js(text, sink, line0=1, base=0):
    if line0 == 1 and base == 0:
        scan_sections(text, sink)
    suffix = Path(sink.path).suffix
    JSScanner(text, sink, line0, shape_methods=suffix in SHAPE_METHODS, base=base,
              fn_words=FN_BY_SUFFIX.get(suffix, set()), words=keywords_for(suffix),
              ts=suffix in TS_SUFFIXES, jsx=suffix in JSX_SUFFIXES).run()


SCRIPT = re.compile(r"<script\b[^>]*>(.*?)</script>", re.S | re.I)


def scan_html(text, sink):
    scan_sections(text, sink)
    pos = 0
    # An Astro component's `---` frontmatter is its script (B578)
    fm = re.match(r"---[ \t]*\n(.*?)\n---[ \t]*(?:\n|$)", text, re.S)
    if fm and Path(sink.path).suffix == ".astro":
        scan_js(fm.group(1), sink, 2, fm.start(1))
        pos = fm.end()
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
        for name in handler_calls(line):
            sink.add_call(name, "", ln, "(markup)")


# `name() {`, `function name {` and `function name() {` alike (B279).
SH_DEF = re.compile(r"^\s*(?:function\s+([A-Za-z_][\w-]*)\s*(?:\(\))?|([A-Za-z_][\w-]*)\s*\(\))\s*\{")
SH_COMMENT = re.compile(r"(^|\s)#.*$")
SH_TRAP = re.compile(r"^\s*trap\s")
# `. "$(dirname "$0")/lib/common.sh"` and `source lib/sdk.sh`: the file is
# the last path ending in .sh or .bash on the line
SH_SOURCE = re.compile(r"^\s*(?:\.|source)\s+(.+)$")
SH_SOURCED = re.compile(r"((?:[\w.-]+/)*[\w.-]+\.(?:sh|bash))\b")


def sh_code(ln):
    """One line with its quoted text blanked: nothing in '...' runs, and in
    "..." only a $(...) or `...` does, so `die "run this as root"` calls die
    and not run. Line by line, a quote left open closes at the line's end."""
    out, i, n, q, sub = [], 0, len(ln), "", 0
    while i < n:
        c = ln[i]
        if c == "\\" and q != "'":
            out.append("  " if q and not sub else ln[i:i + 2])
            i += 2
            continue
        if q == "'":
            if c == "'":
                q = ""
            out.append(c if c == "'" else " ")
        elif q == '"' and not sub:
            if c == '"':
                q = ""
                out.append(c)
            elif ln.startswith("$(", i) or c == "`":
                sub = 1
                out.append(ln[i:i + 2] if c == "$" else c)
                i += 2 if c == "$" else 1
                continue
            else:
                out.append(" ")
        else:
            if sub and c == "(":
                sub += 1
            elif sub and c in ")`":
                sub -= 1
            elif not sub and c in "'\"":
                q = c
            out.append(c)
        i += 1
    return "".join(out)


def _sh_name(m):
    return m.group(1) or m.group(2)


def scan_sh(text, sink, known=()):
    """known: the functions of the files this one sources, which it calls
    as its own (bb's 251 calls of die were none, die being common.sh's)."""
    scan_sections(text, sink)
    lines = text.split("\n")
    names = {_sh_name(m): i + 1 for i, ln in enumerate(lines) if (m := SH_DEF.match(ln))}
    names.update((n, 0) for n in known if n not in names)
    sink.sources = sorted({t for ln in lines if (m := SH_SOURCE.match(ln))
                           for t in SH_SOURCED.findall(m.group(1))})
    # [(name, indent, def)]: a function ends at the `}` at its own indent,
    # so one defined inside another (`need() {` in cmd_lint, gitea_api in a
    # script's body) ends where it does and hands its caller back, where
    # only a `}` in column zero used to end anything
    stack = []
    word = re.compile(r"(?<![\w./-])([A-Za-z_][\w-]*)(?![\w-])")
    for i, ln in enumerate(lines, 1):
        # A comment starts at a hash at the start or after a space: the
        # hash of `${#arr[@]}` is not one (B279).
        # (trap's quoted command does run, later: `trap 'cleanup' EXIT`)
        code = "" if ln.lstrip().startswith("#") else \
            SH_COMMENT.sub("", ln if SH_TRAP.match(ln) else sh_code(ln))
        cur = stack[-1][0] if stack else "(top level)"
        indent = len(ln) - len(ln.lstrip())
        m = SH_DEF.match(ln)
        if m:
            name = _sh_name(m)
            d = sink.add_def(name, i, "function", cur if stack else "")
            # `f() { ...; }` on one line: its calls are read here and it is
            # over on this line, so the next brace in column zero is not
            # its end and the function after it is not inside it.
            body = code[m.end():]
            if body.count("}") >= body.count("{") + 1:
                for w in word.finditer(body):
                    if w.group(1) in names and w.group(1) != name:
                        sink.add_call(w.group(1), "", i, name)
                continue
            stack.append((name, indent, d))
            continue
        if stack and ln.lstrip().startswith("}") and indent <= stack[-1][1]:
            while stack and indent <= stack[-1][1]:
                stack.pop()[2]["end"] = i
            continue
        for w in word.finditer(code):
            if w.group(1) in names and w.group(1) != cur:
                sink.add_call(w.group(1), "", i, cur)
    for _, _, d in stack:
        # never closed (a heredoc's `}` or a file cut short): to the end
        d["end"] = len(lines)


# ---- the index ------------------------------------------------------------

def sources(root):
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            p = Path(dp) / fn
            if MINIFIED.search(fn):
                continue
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


def minified(text):
    """Generated rather than written: long, and a thousand characters a
    line or more on average."""
    return len(text) > 20_000 and len(text) / (text.count("\n") + 1) > 1000


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
        if old and old.get("mtime") == mtime and old.get("lang") == lang and "defs" in old \
                and old.get("scan") == SCANNER:
            files[rel] = old
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        sink = Sink(rel)
        if lang in ("js", "html") and minified(text):
            # a bundle nobody wrote by hand, xterm.js at 290 kB on one line:
            # kept as a file the map knows and skips, not as 146 dead names
            text = ""
        try:
            {"py": scan_python, "js": scan_js, "html": scan_html, "sh": scan_sh, "c": scan_c}[lang](text, sink)
        except Exception as e:      # a scanner must never take the map down
            sink.add_def(f"(scan failed: {e})", 1, "error", "")
        files[rel] = {"mtime": mtime, "lang": lang, "scan": SCANNER,
                      "defs": sink.defs, "calls": sink.calls,
                      "draws": sink.draws, "routes": sink.routes, "refs": sink.refs,
                      "sections": sink.sections, "passed": []}
        if lang == "sh":
            files[rel]["sources"] = getattr(sink, "sources", [])
        fresh[rel] = sink
        scanned += 1
    sh_known(root, files, fresh)
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
    # Kept in the tree when the tree takes it. A project this session only
    # READS (prefs.reads) is bound read-only into its view, so the map of
    # one is built here and answers from memory, and the next question
    # builds it again: a second's cost, never a refusal.
    out = root / INDEX_DIR
    try:
        out.mkdir(exist_ok=True)
        exclude(root)
        tmp = out / (INDEX_FILE + ".tmp")
        tmp.write_text(json.dumps(idx))
        tmp.replace(out / INDEX_FILE)
        # The index an older reader wrote stays behind otherwise, and two of
        # them were sitting beside this one at seven megabytes each.
        for old in out.glob("*.json"):
            if old.name != INDEX_FILE and (old.name == "index.json" or re.fullmatch(r"map\d+\.json", old.name)):
                old.unlink(missing_ok=True)
        idx["kept"] = True
    except OSError:
        idx["kept"] = False
    return flat(idx)


def sh_known(root, files, fresh):
    """A shell file calls what the files it sources define: each sh file's
    sourced files are resolved in the tree (by the path they are named by,
    else by basename), their top-level functions and those of what they
    source in turn are its known names, and so are those of the files that
    source it, for a library, and a file is scanned again when
    that set is not the one it was scanned with: a function added to
    common.sh is seen called in bb without bb changing."""
    sh = {rel: e for rel, e in files.items() if e.get("lang") == "sh"}
    by_base = {}
    for rel in sh:
        by_base.setdefault(Path(rel).name, []).append(rel)

    def resolve(tok):
        hits = [rel for rel in sh if rel == tok or rel.endswith("/" + tok)]
        return hits or by_base.get(Path(tok).name, [])

    def closure(rel):
        seen, todo = set(), [rel]
        while todo:
            for tok in sh[todo.pop()].get("sources", []):
                for r in resolve(tok):
                    if r not in seen and r != rel:
                        seen.add(r)
                        todo.append(r)
        return seen

    for rel, e in sh.items():
        if "sources" not in e:
            sink = fresh.get(rel)
            e["sources"] = getattr(sink, "sources", []) if sink else []
    sourced_by = {}
    for rel in sh:
        for r in closure(rel):
            sourced_by.setdefault(r, set()).add(rel)
    for rel, e in sh.items():
        # what it sources, and, for a library, what sources it and what
        # that sources: sdk.sh calls common.sh's die because bb sourced both
        around = closure(rel) | sourced_by.get(rel, set())
        for r in sourced_by.get(rel, set()):
            around |= closure(r)
        around.discard(rel)
        known = sorted({d["name"] for r in around for d in sh[r]["defs"]
                        if d["kind"] == "function" and not d["parent"]})
        if rel not in fresh and e.get("known", []) == known:
            continue
        if not known and rel in fresh:
            e["known"] = known
            continue
        try:
            text = (Path(root) / rel).read_text(errors="replace")
        except OSError:
            continue
        sink = Sink(rel)
        try:
            scan_sh(text, sink, known)
        except Exception as ex:      # a scanner must never take the map down
            sink.add_def(f"(scan failed: {ex})", 1, "error", "")
        e.update(defs=sink.defs, calls=sink.calls, sections=sink.sections,
                 sources=sink.sources, known=known)
        fresh[rel] = sink


def exclude(root):
    """`.bb-map/` into the repository's own exclude file, once, for the tree
    an index is written into. True when git now leaves it alone.

    Here and not only where the dashboard creates a project, which is where
    it used to be written: a project that predated that, or whose map a
    session built, showed .bb-map/ untracked, and `git add -A` took a
    multi-megabyte index into a commit (B247). Found through git, so a
    worktree writes it to the exclude file its repository shares; a tree
    with no repository has nothing to write it into, and the Git view's
    Init runs this when it makes one. Never the project's .gitignore, which
    is the project's to write.
    """
    root = Path(root)
    path = None
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-path", "info/exclude"],
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            path = Path(r.stdout.strip())
            path = path if path.is_absolute() else root / path
    except (OSError, subprocess.SubprocessError):
        pass
    if path is None:
        # git itself refused (a tree another account owns, say): the plain
        # layout still has an answer.
        if not (root / ".git").is_dir():
            return False
        path = root / ".git" / "info" / "exclude"
    try:
        have = path.read_text() if path.exists() else ""
        if f"{INDEX_DIR}/" in have.split("\n"):
            return True
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(("" if have.endswith("\n") or not have else "\n") + f"{INDEX_DIR}/\n")
        return True
    except OSError:
        return False               # the map still builds; only the exclude is lost


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
    now, langs = {}, {}
    for p, lang in sources(root):
        try:
            rel = str(p.relative_to(root))
            now[rel] = p.stat().st_mtime
            langs[rel] = lang
        except OSError:
            continue
    # ...and read by the scanner that would read it now (B553): a file whose
    # language or scanner moved since it was indexed is stale though it has
    # not changed, and build() rescans just those.
    if set(now) != set(have) or any(now[k] != have[k].get("mtime") or "defs" not in have[k]
                                    or have[k].get("lang") != langs[k]
                                    or have[k].get("scan") != SCANNER for k in now):
        return build(root, prior)
    return flat(prior)


# ---- the questions ----------------------------------------------------------

TEST_NAME = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.(go|py|rs)|[^/]+Test\.(kt|java|cs|scala)"
                       r"|[^/]+\.(test|spec)\.[cm]?[jt]sx?|[^/]+_spec\.rb)$")


TEST_DIR = re.compile(r"/(?:tests|__tests__|e2e)/")
TEST_HELPER = re.compile(r"(?:lib|helpers?|utils?|mocks?|fixtures?|setup|harness|support)\b|mock-", re.I)


def is_test(path):
    """A test: an .mjs under a test directory (this repository's suites,
    minus the library beside them), or a file named the way its language
    names tests: test_x.py, x_test.go, XTest.kt, x.test.ts, x.spec.js."""
    if ("/test/" in "/" + path or path.startswith("test/")) and path.endswith(".mjs"):
        return not path.endswith("/lib.mjs")
    # ...and any script under tests/, __tests__/ or e2e/ but the helpers
    # beside them: MediaReducer's tests/e2e/e2e_*.mjs read as page scripts
    if TEST_DIR.search("/" + path) and Path(path).suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx") \
            and not TEST_HELPER.match(Path(path).name):
        return True
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


def said_by(root, d, limit=160):
    """What a definition says about itself: the comment block directly above
    it (`//`, `#`, or a `/* */`), or a python docstring's first line. The
    notes this tree keeps beside every function are what a session reads
    first, so the map hands them over rather than a bare line number; the
    map itself carries none, since it is rebuilt from the tree and lives
    in an ignored directory on whichever machine built it."""
    if not root or not d:
        return ""
    if d["file"] not in _LINES:
        line_of(root, d["file"], 1)
    lines = _LINES.get(d["file"]) or []
    n = d["line"]
    if not (0 < n <= len(lines)):
        return ""
    words = []
    if d["file"].endswith(".py"):
        for k in range(n, min(n + 4, len(lines))):
            t = lines[k].strip()
            if t.startswith(TRIPLES):
                # The docstring to its close or its first blank line: a
                # sentence wraps, and the first line alone stopped mid-way.
                t = t[3:]
                got = []
                for j in range(k, min(k + 12, len(lines))):
                    u = lines[j].strip() if j > k else t
                    done = u.endswith(TRIPLES)
                    u = u[:-3] if done else u
                    if not u.strip() and got:
                        break
                    if u.strip():
                        got.append(u.strip())
                    if done:
                        break
                words = got
                break
            if t and not t.startswith("def ") and not t.startswith(")") and not t.endswith(":"):
                break
    else:
        k = n - 2
        block = []
        while k >= 0:
            t = lines[k].strip()
            if t.startswith("//"):
                block.insert(0, t[2:].strip())
            elif t.startswith("#") and not t.startswith("#!"):
                block.insert(0, t[1:].strip())
            elif t.endswith("*/") or t.startswith("/*") or t.startswith("*"):
                block.insert(0, t.strip("/* ").strip())
                if t.startswith("/*"):
                    break
            else:
                break
            k -= 1
        # A section header is the section's, not this definition's.
        words = [b for b in block if not b.startswith("----")]
    text = " ".join(w for w in words if w).strip()
    if not text:
        return ""
    # The first sentence or two, and never past the limit mid-word.
    m = re.match(r"(.{0,%d}?[.!?])(\s|$)" % limit, text)
    text = m.group(1) if m else text
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def page_bindings(idx, root, name):
    """Where a page script declares `name` at its top level: a `let`, `var`
    or `const` that is not a function, which the defs never carried, so
    `find active` said nothing defines what page-state.js declares on line
    30 (B299). (file, line, kind) per declaration."""
    out = []
    decl = re.compile(r"^(let|var|const)\s+(.*)$")
    for f in page_scripts(idx):
        for lines, l0 in script_bodies(root, f):
            for i, l in enumerate(lines):
                m = decl.match(l)
                if m and name in declarators(m.group(2)):
                    out.append((f, l0 + i, m.group(1)))
    return out


# A name declared as a value rather than a function or a type, by each
# language's own words: what `find` falls back to when no definition has the
# name. A Kotlin table in a companion object (`val ACTIONS = linkedMapOf(`)
# was "nothing defines ACTIONS" (report #66, B527), and a python module's
# constant was the same.
VALUE_DECL = {
    "py": lambda n: rf"^{n}\s*(?::[^=]+)?=(?!=)",
    "sh": lambda n: rf"^\s*(?:export\s+|readonly\s+|local\s+)?{n}=",
    ".kt": lambda n: rf"\b(?:val|var)\s+{n}\b", ".kts": lambda n: rf"\b(?:val|var)\s+{n}\b",
    ".scala": lambda n: rf"\b(?:val|var)\s+{n}\b", ".swift": lambda n: rf"\b(?:let|var)\s+{n}\b",
    ".go": lambda n: rf"\b(?:const|var)\s+{n}\b|^\s+{n}\s+(?:[\w.*\[\]]+\s*)?=",
    ".rs": lambda n: rf"\b(?:const|static)\s+(?:mut\s+)?{n}\s*:",
    ".java": lambda n: rf"\b{n}\s*=[^=]", ".cs": lambda n: rf"\b{n}\s*=[^=]",
    ".dart": lambda n: rf"\b(?:final|const|var)\s+(?:\w+\s+)?{n}\b",
    ".ts": lambda n: rf"\b(?:const|let|var)\s+{n}\b", ".mjs": lambda n: rf"\b(?:const|let|var)\s+{n}\b",
}


def value_decls(idx, root, name, limit=20):
    """Where `name` is declared as a value in a file of the index, by the
    patterns above. (file, line, word) per declaration."""
    if not root or not re.fullmatch(r"[A-Za-z_$][\w$]*", name):
        return []
    out = []
    for f, e in idx["files"].items():
        pat = VALUE_DECL.get(e.get("lang")) or VALUE_DECL.get(Path(f).suffix)
        if not pat:
            continue
        rx = re.compile(pat(re.escape(name)))
        try:
            with open(Path(root) / f, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    if name in line and rx.search(line):
                        out.append((f, i, "value"))
                        if len(out) >= limit:
                            return out
        except OSError:
            continue
    return out


def q_find(idx, name, root=None):
    rows = [d for d in idx["defs"] if d["name"] == name]
    if not rows:
        found = page_bindings(idx, root, name) if root else []
        if not found:
            more = value_decls(idx, root, name)
            if more:
                return [f"{f}:{ln}  declared as a value" for f, ln, _ in more]
            return [f"nothing defines {name}"]
        out = []
        for f, ln, kind in found:
            out.append(f"{f}:{ln}  page-level {kind}"
                       + ("" if kind == "const" else f"; bb map state {Path(f).name} says where it is assigned"))
        return out
    out = []
    for d in rows:
        where = f"{d['file']}:{d['line']}"
        span = f" to {d['end']}" if d["end"] > d["line"] else ""
        parent = f"  in {d['parent']}" if d["parent"] else ""
        out.append(f"{where}{span}  {d['kind']}{parent}")
        said = said_by(root, d)
        if said:
            out.append(f"    says: {said}")
    return out


# Said under every answer that would have a session delete or rename
# something: the map is an index, and a miss there deletes working code
# (MediaReducer's unused was wrong 50 times in 51 before B584).
GREP_FIRST = ("(the map is an index, not a parser: {} before deleting or renaming, since a call "
              "from a string, a template or a file it does not read is not in it)")


def q_who_calls(idx, name, root):
    qual = ""
    if "." in name:
        qual, name = name.rsplit(".", 1)
    rows = [c for c in idx["calls"] if c["name"] == name and (not qual or c["qual"] == qual)]
    # ...and the places it is handed over without a call: to a draw, an
    # onclick, a list. Not a call, and the reason a function nothing calls
    # is not dead; who-calls used to say "nothing calls" and leave it there.
    passed = [] if qual else [p for p in idx.get("passed", []) if p["name"] == name and not p.get("decl")]
    if not rows and not passed:
        return [f"nothing calls {name}" + (f" on {qual}" if qual else "") + ", and nothing passes it by name",
                GREP_FIRST.format(f"grep -rn {name}")]
    out = []
    # What the callee says about itself, first: the reason it exists is the
    # frame every caller below is read in.
    for d in idx["defs"]:
        if d["name"] == name and not qual:
            said = said_by(root, d, 200)
            if said:
                out.append(f"{name}: {said}")
            break
    if not rows:
        out.append(f"nothing calls {name} directly; it is passed by name:")
    by_name = {}
    for d in idx["defs"]:
        by_name.setdefault((d["file"], d["name"]), d)
    for c in sorted(rows, key=lambda c: (is_test(c["file"]), c["file"], c["line"])):
        tag = "test " if is_test(c["file"]) else ""
        # ...and each caller's own first clause, so a list of twenty names
        # reads as twenty reasons rather than twenty addresses.
        cd = by_name.get((c["file"], c["caller"].split(".")[-1]))
        says = said_by(root, cd, 70) if cd and not tag else ""
        out.append(f"{tag}{c['file']}:{c['line']}  from {c['caller']}{f' ({says})' if says else ''}  | {line_of(root, c['file'], c['line'])}")
    for p in sorted(passed, key=lambda p: (is_test(p["file"]), p["file"], p["line"])):
        tag = "test " if is_test(p["file"]) else ""
        out.append(f"{tag}{p['file']}:{p['line']}  passed by name in {p['fn']}  | {line_of(root, p['file'], p['line'])}")
    return out


def q_calls(idx, name):
    rows = [c for c in idx["calls"] if c["caller"] == name or c["caller"].endswith("." + name)]
    # A Kotlin or Java `external fun` is its JNI function in C (B554).
    if not rows:
        for d in idx["defs"]:
            if d["name"] == name and d.get("kind") == "jni" and d.get("jni"):
                rows = [c for c in idx["calls"] if c["caller"] == d["jni"]]
                break
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
        return [f"no definitions in {path} (is it indexed? bb map languages says which files are)"]
    out = []
    named = [d for d in rows if d["name"] != "(anonymous)"]
    anon = [d for d in rows if d["name"] == "(anonymous)"]
    # A file of closures alone (a WordPress plugin's add_action callbacks)
    # lists them, each with what it is handed to; beside named ones they
    # are counted, since every callback of a page would bury them (B577).
    for d in sorted(named if named else anon, key=lambda d: d["line"]):
        indent = "  " if d["parent"] else ""
        span = f"-{d['end']}" if d["end"] > d["line"] else ""
        what = d["name"]
        if what == "(anonymous)":
            to = [c["name"] for c in idx["calls"] if c["file"] == d["file"]
                  and c["line"] == d["line"] and c["caller"] != "(anonymous)"]
            what += f" passed to {to[-1]}" if to else ""
        out.append(f"{indent}{d['line']}{span}  {d['kind']} {what}" + (f"  (in {d['parent']})" if d["parent"] else ""))
    if named and anon:
        out.append(f"and {len(anon)} anonymous function{'s' if len(anon) != 1 else ''}, "
                   "too (callbacks, not listed beside named ones)")
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
    # bare inside page.evaluate. Never a python function by its bare name:
    # `remove()` or `load()` defined in a module matched every suite's DOM
    # and its own helpers; a unit test calls one qualified, below.
    js = {f for f in files if idx["files"].get(f, {}).get("lang") in ("js", "html")}
    # ...and only a top-level one: a suite reaches the page's globals, and a
    # local `const done = () =>` inside a draw, or a table's `open:` arrow,
    # matched every suite that calls its own library's done() (9 Oct).
    names = {d["name"] for d in idx["defs"] if d["file"] in js and not d["name"].startswith("(")
             and len(d["name"]) > 3 and not d.get("parent") and not d.get("prop")}
    things = {(d["what"], d["kind"]) for d in idx["draws"] if d["file"] in files and d["kind"] != "import"}
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
    mark = {"class": ".", "id": "#", "path": "", "file": "", "import": ""}
    paths = {w for w, k in things if k == "path"}
    for d in idx["draws"]:
        if not is_test(d["file"]):
            continue
        if (d["what"], d["kind"]) in things:
            hits.setdefault(d["file"], set()).add(mark[d["kind"]] + d["what"])
        elif d["kind"] == "path" and any(d["what"].startswith(p_ + "/") or d["what"].startswith(p_ + "?")
                                         for p_ in paths):
            hits.setdefault(d["file"], set()).add(d["what"])
        elif d["kind"] in ("file", "import") and any(f == d["what"] or f.endswith("/" + d["what"])
                                                     or os.path.splitext(f)[0] == d["what"] for f in files):
            hits.setdefault(d["file"], set()).add(d["what"])
        elif d["kind"] == "file" and "/" in d["what"].strip("/") \
                and any(f.startswith(d["what"].strip("/") + "/") for f in files):
            # a directory named whole reaches what is in it: agent.mjs names
            # scripts/agent/builderbot_agent, the package it loads and runs,
            # and its modules each read as reached by no suite (9 Oct)
            hits.setdefault(d["file"], set()).add(d["what"] + "/")
    for c in idx["calls"]:
        if is_test(c["file"]) and not c["qual"] and c["name"] in names:
            hits.setdefault(c["file"], set()).add(c["name"] + "()")
    if py:
        # The python unit tier calls a module as itself: `codemap.q_find()`
        # in a test that imported it reaches it, and no other suite does.
        for c in idx["calls"]:
            if c["qual"] in stems and c["name"] in defs and is_test(c["file"]) \
                    and c["file"].endswith(".py"):
                hits.setdefault(c["file"], set()).add(f"{c['qual']}.{c['name']}()")
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


def _decorated(f, line):
    """Whether the python def at `line` carries a decorator: a framework
    reaches it by registration (Flask's @app.route, @app.before_request), never
    by a call the map could see (MediaReducer's app.py, 11 Oct)."""
    try:
        lines = Path(f).read_text(errors="replace").splitlines()
    except OSError:
        return True
    i = line - 2
    while i >= 0 and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i -= 1
    return i >= 0 and lines[i].lstrip().startswith("@")


def q_unused(idx, path=None, root="."):
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
        # browser, which the map cannot see; its name says what it is. And
        # a property of an object (nb.clashResume = ...) is called as the
        # object's, which the map does not follow either (B271).
        # ...and a constructor, which `new` calls by its class's name...
        # ...nor a method, which is called through its object as well, often by
        # a framework the tree only hands it to: VS Code calls a file system's
        # createDirectory, and nothing here does (8 Oct).
        if (n.startswith("on") and n[2:3].islower()) or d.get("prop") or d.get("named_expr") \
                or n == "constructor" or d["kind"] == "method":
            continue
        if called.get(n, 0) == 0 and refs.get(n, 0) - own.get(n, 0) <= 0:
            rows.append(d)
    # ...and the python modules' own functions (top-level, not dunders, not
    # the tests'), which this used to skip while answering "nothing on the
    # page is unused" for a python file as if it had looked (11 Oct, where
    # it hid two dead functions). A python name is reached in more ways than
    # a call the map sees (a route table's string, getattr, a test), so one
    # counts as unused only when its name appears nowhere in the tree but
    # its own definition.
    words = None
    for f, entry in idx["files"].items():
        if Path(f).suffix != ".py" or is_test(f) or "/unit/" in "/" + f or "/test/" in "/" + f:
            continue
        if path and not (f == path or f.endswith("/" + path)):
            continue
        for d in entry["defs"]:
            n = d["name"]
            if d["kind"] != "def" or d.get("parent") or n.startswith("__") \
                    or called.get(n, 0) or refs.get(n, 0) > 1:
                continue
            if words is None:
                words = {}
                for g in idx["files"]:
                    try:
                        for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", (Path(root) / g).read_text(errors="replace")):
                            words[w] = words.get(w, 0) + 1
                    except OSError:
                        pass
            if words.get(n, 0) <= 1 and not _decorated(Path(root) / f, d.get("line") or 0):
                rows.append(d)
    if not rows:
        what = "python module" if path and path.endswith(".py") else "page" if path else "page or python module"
        return [f"nothing in this {what} is unused by this measure" + (f" ({path})" if path else "")]
    out = [f"{len(rows)} function{'s' if len(rows) != 1 else ''} nothing calls and nothing passes by name"
           " (" + GREP_FIRST.format("grep each")[1:-1] + "):"]
    for d in sorted(rows, key=lambda d: (d["file"], d["line"])):
        out.append(f"  {d['file']}:{d['line']}  {d['name']}" + (f"  (in {d['parent']})" if d.get("parent") else ""))
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
            # that joins with one, a symlink the tree sits behind. Normalized
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


# ---- what a change touches, by coverage (the operator, 29 Sep) ---------------
# A whole gate was 25 minutes of wall for a change to one handler, because
# server.py, index.html and the briefing each read as "every suite". The
# covered run already says which suites reach which function, so a change
# is measured by the functions its lines fall in and the suites that
# reached those, and by the ids and classes its lines draw. A changed
# function no covered run has seen falls back to the file's own answer
# (suites_for), and in server.py to every suite, as before.

def changed_ranges(root, base, files):
    """{file: [(start, end)]} of the lines changed against `base`, working
    tree included; a file git cannot diff (untracked) is whole."""
    out = {}
    for f in files:
        try:
            diff = subprocess.run(["git", "-C", str(root), "diff", "-U0", base, "--", f],
                                  capture_output=True, text=True, check=False).stdout
        except OSError:
            diff = ""
        ranges = []
        for m in re.finditer(r"(?m)^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", diff):
            start, n = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            # A pure deletion has n == 0: the lines around it are what moved.
            ranges.append((max(1, start - (1 if n == 0 else 0)), start + max(n, 1) - 1))
        if not diff:
            tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", f],
                                     capture_output=True, text=True, check=False).returncode == 0
            if not tracked:
                ranges = [(1, 10 ** 9)]
        out[f] = ranges
    return out


def affected(idx, cov, ranges, root=None):
    """{suite stem: set of reasons}, plus the account: for each changed file,
    the functions and the drawn things its changed lines fall in, the suites
    coverage or the map say reach them, and what fell back to the file."""
    hit = covered_ids(cov) if cov else {}
    suites, notes, unknown = {}, [], []
    every = False
    # How each changed function was placed, for preflight to say: measured
    # by a covered run, through a caller in the map's call graph, or by its
    # file's answer, which is the map's guess by name when no covered run
    # has seen the file at all
    acct = {"measured": 0, "callers": 0, "file": 0, "by_name": []}
    LAST_ACCOUNT.clear()
    LAST_ACCOUNT.update(acct)
    for f, spans in ranges.items():
        entry = idx["files"].get(f)
        if entry is None:
            notes.append(f"{f}: not indexed")
            continue
        if is_test(f):
            suites.setdefault(Path(f).stem, set()).add("changed itself")
            continue
        def inside(line, spans=spans):
            return any(a <= line <= b for a, b in spans)
        over = [d for d in entry["defs"] if not d["name"].startswith("(")
                and any(a <= d.get("end", d["line"]) and d["line"] <= b for a, b in spans)]
        # The innermost function a changed line falls in is the one that
        # changed. One that merely encloses it is not: a view's factory
        # holds every line of its file and is run by every suite that opens
        # any notebook, which made one change to the Design view forty
        # suites (29 Sep).
        def encloses(d, e):
            return d is not e and d["line"] <= e["line"] and e.get("end", e["line"]) <= d.get("end", d["line"]) \
                and (d["line"], d.get("end", d["line"])) != (e["line"], e.get("end", e["line"]))
        fns = [d for d in over if not any(encloses(d, e) for e in over)]
        found = set()
        by_name = {}
        for d in entry["defs"]:
            by_name.setdefault(d["name"], []).append(d)

        def through_callers(name, hops=3, seen=None, f=f, by_name=by_name, entry=entry):
            """The suites that reached what calls `name` in this file, up to
            three callers up: a function a covered run has not seen yet is
            run by whoever runs its caller."""
            seen = seen if seen is not None else set()
            out = {}
            if hops == 0 or name in seen:
                return out
            seen.add(name)
            callers = {c["caller"].rsplit(".", 1)[-1] for c in idx["calls"]
                       if c["name"] == name and c["file"] == f and c.get("caller")}
            for cn in callers - {name}:
                got = {}
                for cd in by_name.get(cn, []):
                    # never through the file-spanning factory: it is every suite's
                    if cd.get("end", cd["line"]) - cd["line"] >= 0.5 * max(
                            (x.get("end", x["line"]) for x in entry["defs"]), default=1):
                        continue
                    got.update(hit.get(fid(cd)) or {})
                if not got:
                    got = through_callers(cn, hops - 1, seen, f, by_name, entry)
                for s_ in got:
                    out[s_] = f"{cn}() calls {name}()"
            return out
        for d in fns:
            by = hit.get(fid(d))
            if by:
                for s_ in by:
                    suites.setdefault(s_, set()).add(f"{d['name']}()")
                found.add(d["name"])
                LAST_ACCOUNT["measured"] += 1
                continue
            via = through_callers(d["name"])
            if via:
                for s_, why in via.items():
                    suites.setdefault(s_, set()).add(why)
                found.add(d["name"])
                LAST_ACCOUNT["callers"] += 1
                notes.append(f"{f}:{d['line']} {d['name']}: new to the covered run, measured by its caller")
            else:
                unknown.append(f"{f}:{d['line']} {d['name']}")
                LAST_ACCOUNT["file"] += 1
        drawn = {(d["what"], d["kind"]) for d in entry.get("draws", []) if inside(d["line"])}
        for d in idx["draws"]:
            if is_test(d["file"]) and (d["what"], d["kind"]) in drawn:
                mark = {"class": ".", "id": "#"}.get(d["kind"], "")
                suites.setdefault(Path(d["file"]).stem, set()).add(mark + d["what"])
        # Lines in no function at all and drawing nothing a suite names
        # (top-level wiring, a table of constants): the file's own answer.
        # Not a blank line or a comment, which change nothing that runs,
        # and not a rule of the stylesheet, which is the design check's.
        try:
            text = (Path(root) / f).read_text(errors="replace").split("\n") if root else []
        except OSError:
            text = []
        style = (0, -1)
        if text and entry.get("lang") == "html":
            a_ = next((i + 1 for i, ln in enumerate(text) if "<style" in ln), 0)
            b_ = next((i + 1 for i, ln in enumerate(text) if "</style>" in ln), -1)
            style = (a_, b_)

        def says_nothing(ln, text=text):
            t = text[ln - 1].strip() if 0 < ln <= len(text) else "x"
            return not t or t.startswith(("#", "//", "/*", "*", "*/", "<!--"))
        loose = [ln for a, b in spans for ln in range(a, min(b, a + 400) + 1)
                 if not any(d["line"] <= ln <= d.get("end", d["line"]) for d in entry["defs"]
                            if not d["name"].startswith("("))
                 and not any(dd["line"] == ln for dd in entry.get("draws", []))
                 and not says_nothing(ln)]
        css = [ln for ln in loose if style[0] <= ln <= style[1]]
        if css:
            suites.setdefault("uniform", set()).add("the stylesheet")
            loose = [ln for ln in loose if ln not in set(css)]
        fell = bool(unknown and any(u.startswith(f + ":") for u in unknown)) or bool(loose)
        if fell:
            if f == "scripts/dashboard/server.py" and any(u.startswith(f + ":") for u in unknown):
                every = True
                notes.append(f"{f}: a changed function no covered run has seen, so every suite")
                continue
            # The file's own suites: the ones a covered run saw reach a
            # function of this file that is the file's own work, which a
            # function spanning most of the file (a factory) is not. Only a
            # file no covered run has seen at all asks the map by name.
            last = max((d.get("end", d["line"]) for d in entry["defs"]), default=1)
            own = [d for d in entry["defs"] if not d["name"].startswith("(")
                   and d.get("end", d["line"]) - d["line"] < 0.5 * last]
            names = {s_ for d in own for s_ in (hit.get(fid(d)) or {})}
            if not names:
                LAST_ACCOUNT["by_name"].append(f)
                _, byfile = suites_for(idx, [f])
                names = {Path(t).stem for t in byfile if not Path(t).name.startswith("lab-")}
            for s_ in names:
                suites.setdefault(s_, set()).add(f"{Path(f).name} (file)")
            why = "lines outside any function" if loose and not any(u.startswith(f + ":") for u in unknown) else "a function no covered run has seen"
            notes.append(f"{f}: {why}, so the file's {len(names)} suite{'' if len(names) == 1 else 's'}")
    # A lab suite needs a real service and is run by name (bb tests lab),
    # never picked, whichever road reached it: the file's own answer already
    # left them out, and a drawn name did not, so a change posting to a path
    # a lab suite also asks planned that lab suite (B395).
    for s_ in [k for k in suites if k.startswith("lab-")]:
        del suites[s_]
    return suites, notes, unknown, every


LAST_ACCOUNT = {}


def account_line(a, every=False):
    """One line saying how far a plan stands on measurement and how far on
    the map's reading, which can be wrong: a suite the map misses is a
    suite the gate does not run, and the gate still says clean."""
    n = a.get("measured", 0) + a.get("callers", 0) + a.get("file", 0)
    if every:
        return "suites: every one, since a changed server function is new to the covered run"
    if not n and not a.get("by_name"):
        return ""
    parts = [f"{a.get('measured', 0)} of {n} changed function{'' if n == 1 else 's'} placed by what a "
             f"covered run measured"]
    if a.get("callers"):
        parts.append(f"{a['callers']} through their callers in the map")
    if a.get("file"):
        parts.append(f"{a['file']} by their file's suites")
    line = "suites: " + ", ".join(parts)
    if a.get("by_name"):
        line += (f"; {', '.join(a['by_name'][:3])}{' and more' if len(a['by_name']) > 3 else ''} no covered "
                 "run has seen, so planned by the map's reading alone (a whole gate or bb tests coverage measures it)")
    return line


def q_affected(idx, cov, root, base, files, names_only=False, ranges=None):
    ranges = ranges if ranges is not None else changed_ranges(root, base, files)
    suites, notes, unknown, every = affected(idx, cov, ranges, root)
    if names_only:
        said = account_line(LAST_ACCOUNT, every)
        if said:
            print(said, file=sys.stderr)
        return ["ALL"] if every else sorted(suites)
    at = time.strftime("%d %b %H:%M", time.localtime(cov.get("at", 0))) if cov else "none"
    out = [f"by coverage (last covered run {at}): {'every suite' if every else str(len(suites)) + ' suite' + ('' if len(suites) == 1 else 's')}"]
    for s_, why in sorted(suites.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        w = sorted(why)
        out.append(f"  {s_}  ({', '.join(w[:5])}{', ...' if len(w) > 5 else ''})")
    out += [f"  {n}" for n in notes]
    if unknown:
        out.append(f"  unknown to coverage: {', '.join(unknown[:8])}{', ...' if len(unknown) > 8 else ''}"
                   " (bb tests coverage, or a whole gate, refreshes it)")
    return out


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
                   # Every suite, not the top eight: the name was asked for, and
                   # the one suite a reader is looking for is as likely the last.
                   + ", ".join(f"{s} ({n})" for s, n in top))
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
    if minified(text):
        # a bundle the index skips is no page's own code, and code_only over
        # xterm.js's one 290 kB line took fifty seconds (B804)
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
TRIPLES = ('"""', "'''")
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


# Every verb a person asks, in one line: what bare `bb map` ends with, and
# what bb's own usage names (B546: the two had drifted apart).
VERBS = ("bb map find NAME | who-calls NAME | calls NAME | defs FILE | draws ID|.class | suites FILE... | "
         "state [FILE] | sections FILE | unused [FILE] | addresses [FILE...] | coverage | covered NAME | "
         "uncovered [FILE] | affected --base REF FILES... | languages | build; bb map help says what each does")
LANG_WORDS = {"py": "python", "c": "C and C++", "js": "brace scanner (C-shaped languages)",
              "html": "HTML, Astro, Vue and Svelte (markup and scripts)", "sh": "shell"}


def languages():
    """Which files the map reads, by scanner, and what it does not (B546)."""
    by = {}
    for ext, lang in sorted(EXTS.items()):
        by.setdefault(lang, []).append(ext)
    out = [f"  {LANG_WORDS.get(lang, lang)}: {' '.join(exts)}" for lang, exts in by.items()]
    out.insert(0, "indexed, by scanner:")
    out.append("  and a file with no extension whose #! names bash, sh or python")
    out.append("  but never a minified bundle (NAME.min.js, or a script of very long lines)")
    out.append("anything else is not indexed (.css, .json, .yml, .md, .rb and the rest): grep reads those")
    return out


def summary(idx):
    # Counted by extension (B806): the scanner's name said a Kotlin tree
    # was 44 js. A script with none is named by what its #! runs.
    langs = {}
    for name, f in idx["files"].items():
        k = Path(name).suffix.lstrip(".").lower() or f["lang"]
        langs[k] = langs.get(k, 0) + 1
    n_test = sum(1 for f in idx["files"] if is_test(f))
    when = time.strftime('%d %b %H:%M', time.localtime(idx['built']))
    what = (f"{idx.get('scanned', 0)} file{'s' if idx.get('scanned', 0) != 1 else ''} scanned"
            + (f", {idx['dropped']} dropped" if idx.get("dropped") else ""))
    return [f"{len(idx['files'])} files ({', '.join(f'{n} {k}' for k, n in sorted(langs.items(), key=lambda kv: (-kv[1], kv[0])))}; {n_test} test suites), "
            f"{len(idx['defs'])} definitions, {len(idx['calls'])} calls, {len(idx['draws'])} ids and classes drawn",
            (f"last built {when} ({what}) into {INDEX_DIR}/{INDEX_FILE}; a changed file is rescanned by itself, the rest kept"
             if idx.get("kept", True) else
             f"built {when} ({what}) in memory: this tree is read-only here, so the map is not kept "
             "and each question builds it again"),
            "",
            VERBS]


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
    if verb == "languages":
        print("\n".join(languages()))
        return 0
    if verb == "build":
        idx = build(root)
        print("\n".join(summary(idx)))
        return 0
    if verb == "exclude":
        if not exclude(root):
            print(f"{root} is not in a git repository, so there is nothing to keep .bb-map/ out of",
                  file=sys.stderr)
            return 1
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
        print("\n".join(q_unused(idx, rest[0] if rest else None, root)))
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
    if verb == "affected":
        # bb map affected --base REF [--names] [--ranges FILE:A-B ...] FILES...
        base, names_only, ranges, files = "HEAD", False, None, []
        i = 0
        while i < len(rest):
            if rest[i] == "--base" and i + 1 < len(rest):
                base, i = rest[i + 1], i + 2
            elif rest[i] == "--names":
                names_only, i = True, i + 1
            elif rest[i] == "--ranges" and i + 1 < len(rest):
                ranges = ranges or {}
                f_, _, span = rest[i + 1].rpartition(":")
                a_, _, b_ = span.partition("-")
                ranges.setdefault(f_, []).append((int(a_), int(b_ or a_)))
                i += 2
            else:
                files.append(rest[i]); i += 1
        if ranges is not None:
            files = list(ranges)
        print("\n".join(q_affected(idx, coverage_load(root), root, base, files, names_only, ranges)))
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
        lines = q_find(idx, rest[0], root)
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
    if verb in ("find", "who-calls", "draws", "calls") and lines and lines[0].startswith("nothing "):
        lines += not_read_note(root)
    print("\n".join(lines))
    return 0


def not_read_note(root):
    """What the tree holds that the map skips, when an answer was empty."""
    n = {}
    for _dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in fns:
            ext = os.path.splitext(fn)[1].lower()
            if ext in NOT_READ:
                n[ext] = n.get(ext, 0) + 1
    if not n:
        return []
    parts = ", ".join(f"{k} {ext}" for ext, k in sorted(n.items(), key=lambda kv: -kv[1]))
    return [f"(not indexed here, so not in that answer: {parts}; grep them)"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
