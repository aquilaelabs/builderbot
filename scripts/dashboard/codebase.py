"""The code base, counted: what git tracks in a project, by language, with
the files and the lines. It is the Briefing tab's first section, above the
rules, the way a repository's front page shows its language bar.

Tracked files only (`git ls-files`), so nothing a build left behind, nothing
ignored and nothing untracked is in the count: dist/, node_modules/, a
stray archive. None of it exists as far as this is concerned. Of the
tracked files, binaries are skipped (a NUL in the first 8KB), as are lock
files, minified bundles and anything under a vendored directory, which are
in the repository without being anybody's code. Lines are counted as a
person would (every line of the file) because "logical lines" is a
different answer per language and this is a breakdown, not a benchmark.

The percentage bar follows GitHub's habit: prose (Markdown, plain text)
and data (JSON, YAML, TOML, lock files) are counted in the totals and
listed beside the bar, but the bar itself is code and markup, so a
repository with a long changelog does not read as "mostly Markdown".

Cached per project for a minute and by commit: a walk of a few thousand
files is a second, which is fine once and wrong on every poll.
"""
import os
import subprocess
import threading
import time

WORKSPACE = None
_cache = {}
_lock = threading.Lock()
TTL = 60
MAX_BYTES = 4 << 20

# By extension, then by filename, then by shebang. The names are GitHub's
# where they have one, so the bar reads like the one people know.
BY_EXT = {
    ".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".kt": "Kotlin", ".kts": "Kotlin", ".java": "Java", ".dart": "Dart", ".swift": "Swift",
    ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".sql": "SQL", ".lua": "Lua", ".zig": "Zig",
    ".xml": "XML", ".svg": "SVG", ".gradle": "Gradle", ".nix": "Nix", ".pro": "Prolog",
    ".md": "Markdown", ".markdown": "Markdown", ".txt": "Text", ".rst": "reStructuredText",
    ".json": "JSON", ".yml": "YAML", ".yaml": "YAML", ".toml": "TOML", ".ini": "INI",
    ".cfg": "INI", ".conf": "Config", ".env": "Dotenv", ".properties": "Properties",
    ".plist": "XML", ".gitignore": "Ignore List", ".dockerignore": "Ignore List",
    ".tsv": "TSV", ".csv": "CSV", ".mk": "Makefile",
}
BY_NAME = {
    "Dockerfile": "Dockerfile", "Makefile": "Makefile", "Justfile": "Just", "CMakeLists.txt": "CMake",
    "gradlew": "Shell", ".gitignore": "Ignore List", ".dockerignore": "Ignore List",
    ".gitattributes": "Git Attributes", ".editorconfig": "EditorConfig", "LICENSE": "Text",
}
BY_SHEBANG = {"python": "Python", "python3": "Python", "bash": "Shell", "sh": "Shell", "node": "JavaScript",
              "env": None}
# In the totals, not in the bar.
PROSE = {"Markdown", "Text", "reStructuredText"}
DATA = {"JSON", "YAML", "TOML", "INI", "Config", "Dotenv", "Properties", "TSV", "CSV",
        "Ignore List", "Git Attributes", "EditorConfig", "XML", "SVG", "Lock"}
VENDORED = ("node_modules/", "vendor/", "third_party/", "third-party/", ".gradle/")
LOCKS = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "Cargo.lock", "poetry.lock",
         "Gemfile.lock", "composer.lock", "go.sum", "gradle.lockfile", "Pipfile.lock"}


def configure(*, workspace):
    globals().update(WORKSPACE=workspace)


def classify(rel, head):
    """The language of one tracked file, or "" for a binary."""
    if b"\0" in head:
        return ""
    name = os.path.basename(rel)
    if name in LOCKS or name.endswith(".lock"):
        return "Lock"
    if name in BY_NAME:
        return BY_NAME[name]
    _, ext = os.path.splitext(name)
    if ext.lower() in BY_EXT:
        return BY_EXT[ext.lower()]
    if name.startswith("Dockerfile"):
        return "Dockerfile"
    if head.startswith(b"#!"):
        line = head.split(b"\n", 1)[0].decode("utf-8", "replace")
        words = line[2:].split()
        tool = os.path.basename(words[-1] if words and words[0].endswith("env") and len(words) > 1 else (words[0] if words else ""))
        lang = BY_SHEBANG.get(tool.rstrip("0123456789.") if tool.startswith("python") else tool)
        if lang:
            return lang
    return "Other"


def _head(repo):
    p = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True,
                       timeout=10, check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def count(repo):
    """{files, lines, code_lines, languages: [...], skipped: {...}} for one
    repository, or {"error"} where git has nothing to list."""
    p = subprocess.run(["git", "-C", repo, "ls-files", "-z"], capture_output=True, timeout=60, check=False)
    if p.returncode != 0:
        return {"error": "not a git repository, so there is nothing tracked to count"}
    files = [f for f in p.stdout.decode("utf-8", "replace").split("\0") if f]
    langs = {}
    total_files = total_lines = 0
    skipped = {"binary": 0, "vendored": 0, "large": 0, "missing": 0}
    for rel in files:
        if any(rel.startswith(v) or ("/" + v) in rel for v in VENDORED) or rel.endswith(".min.js") or rel.endswith(".min.css"):
            skipped["vendored"] += 1
            continue
        path = os.path.join(repo, rel)
        try:
            if os.path.islink(path) or not os.path.isfile(path):
                skipped["missing"] += 1
                continue
            size = os.path.getsize(path)
            if size > MAX_BYTES:
                skipped["large"] += 1
                continue
            with open(path, "rb") as f:
                head = f.read(8192)
                lang = classify(rel, head)
                if not lang:
                    skipped["binary"] += 1
                    continue
                rest = f.read()
        except OSError:
            skipped["missing"] += 1
            continue
        data = head + rest
        lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        entry = langs.setdefault(lang, {"name": lang, "files": 0, "lines": 0})
        entry["files"] += 1
        entry["lines"] += lines
        total_files += 1
        total_lines += lines
    rows = sorted(langs.values(), key=lambda e: (-e["lines"], e["name"]))
    code = [e for e in rows if e["name"] not in PROSE and e["name"] not in DATA and e["name"] != "Other"]
    code_lines = sum(e["lines"] for e in code)
    for e in rows:
        e["kind"] = "prose" if e["name"] in PROSE else "data" if e["name"] in DATA else "other" if e["name"] == "Other" else "code"
        e["pct"] = round(100 * e["lines"] / code_lines, 1) if e["kind"] == "code" and code_lines else 0
    return {"files": total_files, "lines": total_lines, "code_lines": code_lines,
            "code_files": sum(e["files"] for e in code), "languages": rows, "skipped": skipped}


def payload(project):
    repo = os.path.join(str(WORKSPACE), project)
    head = _head(repo)
    now = time.time()
    with _lock:
        c = _cache.get(project)
        if c and c["head"] == head and now - c["at"] < TTL:
            return c["out"]
    out = count(repo)
    out["project"] = project
    out["commit"] = head[:12]
    out["at"] = int(now)
    with _lock:
        _cache[project] = {"head": head, "at": now, "out": out}
    return out
