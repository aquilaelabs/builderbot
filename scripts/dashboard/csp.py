"""The page's Content-Security-Policy (R158 step 4): the page's own scripts
alone. A script written inline into one of the HTML files the server serves
(the dashboard's head script and its wiring, the login card's) is allowed by
its hash, computed from the file as it is served, so nothing inline that
was not shipped runs, and an inline handler is not allowed at all. Styles
are the page's own files and inline: the terminal library and the editor
make style elements and attributes at run time with no nonce to carry, so
style-src keeps 'unsafe-inline' (a style is not a script: it cannot read a
key or ask the server for anything), while the page's templates still write
data-style, applied through the CSSOM, so what the page itself draws inline
stays small. What the browser refuses it reports to /api/csp-report, kept
here for the Doctor.
"""
import base64
import hashlib
import json
import re
import threading
import time
from pathlib import Path

STATE = None
KEEP = 50
_lock = threading.Lock()
_cache = {}

_INLINE = re.compile(rb"<(script|style)(?![^>]*\bsrc=)[^>]*>(.*?)</\1>", re.S)


def configure(*, state):
    globals()["STATE"] = Path(state)


def hashes(html):
    """('sha256-...' for each inline script, the same for each inline
    style) in `html`, by the exact bytes between the tags, which is what
    the browser hashes."""
    key = hashlib.sha256(html).hexdigest()
    hit = _cache.get(key)
    if hit:
        return hit
    scripts, styles = [], []
    for m in _INLINE.finditer(html):
        h = "'sha256-" + base64.b64encode(hashlib.sha256(m.group(2)).digest()).decode() + "'"
        (scripts if m.group(1) == b"script" else styles).append(h)
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = (scripts, styles)
    return _cache[key]


def header(html):
    """The policy for this page: its own origin for everything, the inline
    blocks it ships by hash, images and media it draws itself (data: for
    the icons the page writes), no plugins, no framing by another origin,
    and the browser's reports to /api/csp-report."""
    scripts, _styles = hashes(html)
    return ("default-src 'self'; "
            f"script-src 'self'{(' ' + ' '.join(scripts)) if scripts else ''}; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; "
            "connect-src 'self'; frame-src 'self' data: blob:; worker-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'; "
            "report-uri /api/csp-report")


def integrity(data):
    """A script's Subresource Integrity value, sha384 as browsers prefer."""
    return "sha384-" + base64.b64encode(hashlib.sha384(data).digest()).decode()


def _file():
    return STATE / "csp-reports.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def report(body, who=""):
    """One report the browser sent, kept with the last KEEP: what was
    blocked, where, and by which directive; nothing of the page itself."""
    try:
        d = json.loads(body or b"{}")
    except ValueError:
        return False
    r = d.get("csp-report") if isinstance(d, dict) else None
    r = r if isinstance(r, dict) else d if isinstance(d, dict) else {}
    row = {"at": int(time.time()), "who": str(who or "")[:40],
           "blocked": str(r.get("blocked-uri") or r.get("blockedURL") or "")[:200],
           "directive": str(r.get("violated-directive") or r.get("effectiveDirective") or "")[:60],
           "where": str(r.get("document-uri") or r.get("documentURL") or "")[:200],
           "line": r.get("line-number") or r.get("lineNumber") or 0,
           "source": str(r.get("source-file") or r.get("sourceFile") or "")[:200]}
    with _lock:
        rows = _load()
        rows.insert(0, row)
        rows = rows[:KEEP]
        tmp = _file().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows))
        tmp.replace(_file())
    return True


def reports():
    """The reports kept, newest first, for the Doctor."""
    return _load()


def clear():
    with _lock:
        try:
            _file().unlink()
        except OSError:
            pass
