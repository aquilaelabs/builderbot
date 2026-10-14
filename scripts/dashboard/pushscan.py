"""What a push would send, read for secrets and private things before it
goes (R219, the operator, 14 Oct): a token, a key, a password, a private key
block, a connection string with a password in it, an email address, an IP
address. The added lines of the diff the push would land are scanned; a
line that matches is a FINDING, keyed by the file and the line's text, and
the push is held until a person has read the findings on the bell (a
session's `bb git push`) or in a confirm (the Git view's Push). Approving
pushes and okays those exact lines: the same text in the same file passes
from then on, and a line that changes is asked about again.

The patterns err on the side of asking: a false positive costs one Approve,
and a true one that got through costs a credential. What is never flagged:
a placeholder (`${VAR}`, `<your token>`, `changeme`, `example`), a value
read from the environment, a documentation address (example.com,
localhost, 192.0.2.x), and a line okayed before.

The whitelist is STATE/pushok.json: {project: {key: {at, by, path, text}}},
written by okay() and read by fresh(). Nothing here runs git: gitrelay.py
makes the diff in its own repository and hands the text over.
"""
import hashlib
import json
import re
import threading
import time
from pathlib import Path

STATE = None
write_json = None

_lock = threading.Lock()


def configure(*, state, write_json):
    globals().update(STATE=Path(state), write_json=write_json)


# ---- what a line can be --------------------------------------------------------
# (kind, pattern), tried in order; the first that matches names the finding.
# A kind is the word the bell shows, so it is the thing, not the regex.
PATTERNS = [
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY( BLOCK)?-----")),
    ("a GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("a GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("a Slack token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}")),
    ("an AWS key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("a Stripe key", re.compile(r"\b[sr]k_(live|test)_[0-9A-Za-z]{20,}")),
    ("an npm token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("a Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}")),
    ("an Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("an OpenAI key", re.compile(r"\bsk-(proj-)?[A-Za-z0-9_-]{32,}")),
    ("a JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("a password in an address", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:[^\s@/'\"]{3,}@")),
    ("an Authorization header", re.compile(r"(?i)\bauthorization\s*[:=]\s*['\"]?(bearer|basic|token)\s+[A-Za-z0-9._=+/-]{12,}")),
    ("a password or secret", re.compile(
        r"(?i)\b(password|passwd|passphrase|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?token)"
        r"['\"]?\s*[:=]\s*['\"]?(?P<value>[^\s'\",;]{8,})")),
    ("an email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    ("an IP address", re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")),
]

# A value that is a stand-in, not a secret: what documentation and examples
# write where a secret goes.
PLACEHOLDER = re.compile(
    r"^(\$\{?[A-Z_][A-Z0-9_]*\}?|<[^>]*>|\[[^\]]*\]|x{3,}|\*{3,}|\.{3,}|_{3,}|-{3,}|"
    r"(your|my|the|a|an|some|insert|enter|put|replace)[-_ ]?[a-z_-]*|change[-_]?me|changeit|"
    r"example[a-z0-9_-]*|sample[a-z0-9_-]*|placeholder|dummy[a-z0-9_-]*|redacted|secret|password|"
    r"none|null|nil|undefined|true|false|yes|no|required|optional|string|value|"
    r"process\.env\.[A-Za-z0-9_.]*|os\.environ[\[.][^\s]*|env\([^)]*\)|getenv\([^)]*\)|"
    r"\$[A-Za-z_][A-Za-z0-9_]*|%[A-Za-z_]+%|\{\{[^}]*\}\}|\{[A-Za-z_][A-Za-z0-9_]*\}|\?+)$", re.I)
# ...and an address that is nobody's.
DOC_HOST = re.compile(r"(@|\.)(example\.(com|org|net)|localhost|invalid|test|local|noreply\.github\.com)$|"
                      r"^(noreply|no-reply|nobody|root|admin|user|test|you|me|name|someone|somebody|first\.last)@", re.I)
DOC_IP = re.compile(r"^(0\.|127\.|255\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|169\.254\.|224\.|2[3-9]\d\.)|^(\d+\.){3}0$|^(\d+\.){3}255$")
MAX_FINDINGS = 200
MAX_LINE = 300


def _is_placeholder(value):
    v = value.strip().strip("'\"`")
    return not v or PLACEHOLDER.match(v) is not None


def _looks_like_version(text):
    # 1.2.3.4 as a version or a dotted number in prose, not an address.
    return bool(re.search(r"(?i)\b(v|version|release|ver)\W*$", text)) or bool(re.search(r"\d+\.\d+\.\d+\.\d+\.\d", text))


def classify(text):
    """The kind of thing one line holds, or "" when it holds nothing of
    note. Decided on the line alone, so a finding is the same wherever the
    line stands."""
    t = text.strip()
    if not t or len(t) > 4000:
        return ""
    for kind, pat in PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        if kind == "a password or secret":
            if _is_placeholder(m.group("value")):
                continue
            value = m.group("value").strip("'\"`")
            # A word with no digit and no mixed case is a name (secret =
            # mySecret) more often than a secret; a long one of mixed
            # characters is the thing.
            if not re.search(r"\d", value) and not (re.search(r"[a-z]", value) and re.search(r"[A-Z]", value)) and len(value) < 20:
                continue
            if value.startswith(("http://", "https://")) or "(" in value:
                continue
        elif kind == "an email address":
            if DOC_HOST.search(m.group(0)):
                continue
        elif kind == "an IP address":
            ip = m.group(0)
            parts = ip.split(".")
            if any(int(p) > 255 for p in parts) or DOC_IP.match(ip) or _looks_like_version(t[:m.start()]):
                continue
        return kind
    return ""


def key_of(path, text):
    """One line in one file: the same text in the same place is the same
    finding, and a change to either is a new one."""
    return hashlib.sha256(f"{path}\n{text.strip()}".encode()).hexdigest()[:20]


def scan(diff):
    """The findings in a unified diff's added lines: [{path, line, text,
    kind, key}], in the diff's order, at most MAX_FINDINGS."""
    out, path, line = [], "", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            p = raw[4:].strip()
            path = p[2:] if p.startswith("b/") else ("" if p == "/dev/null" else p)
            continue
        if raw.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", raw)
            line = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            text = raw[1:]
            kind = classify(text)
            if kind and path:
                out.append({"path": path, "line": line, "text": text.strip()[:MAX_LINE], "kind": kind,
                            "key": key_of(path, text)})
                if len(out) >= MAX_FINDINGS:
                    break
            line += 1
        elif raw.startswith(" "):
            line += 1
    return out


# ---- the whitelist --------------------------------------------------------------

def _file():
    return STATE / "pushok.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def okayed(project):
    """The keys a person has approved for this project."""
    return set((_load().get(str(project)) or {}).keys())


def fresh(project, findings):
    """The findings nobody has okayed yet."""
    ok = okayed(project)
    return [f for f in findings if f["key"] not in ok]


def okay(project, findings, by=""):
    """Approve these findings: the same line in the same file passes from
    now on, until the line changes."""
    if not findings:
        return
    with _lock:
        d = _load()
        rows = d.setdefault(str(project), {})
        now = int(time.time())
        for f in findings:
            rows[f["key"]] = {"at": now, "by": by or "", "path": f["path"], "text": f["text"][:80], "kind": f["kind"]}
        write_json(_file(), d)


def block(findings, limit=60):
    """The findings as the text a person reads before approving: one line
    each, the file and line first, then what kind of thing it looks like,
    then the line itself."""
    rows = [f"{f['path']}:{f['line']}  ({f['kind']})\n    {f['text']}" for f in findings[:limit]]
    if len(findings) > limit:
        rows.append(f"...and {len(findings) - limit} more")
    return "\n".join(rows)


def summary(findings):
    kinds = {}
    for f in findings:
        kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
    n = len(findings)
    named = ", ".join(f"{k} ({c})" if c > 1 else k for k, c in sorted(kinds.items(), key=lambda kv: -kv[1])[:4])
    return f"{n} line{'s' if n != 1 else ''} look{'s' if n == 1 else ''} sensitive: {named}"
