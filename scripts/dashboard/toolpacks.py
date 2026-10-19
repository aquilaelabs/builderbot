"""Tool packs (R77): toolchains a person adds from a git repository of their
own choosing, which BuilderBot neither ships nor lists anywhere.

A pack is a repository with a bbtool.json at its root. The manifest says how
the toolchain installs (the catalog's own recipe machinery, its source being
the pack's repository at the commit that was approved), the verbs a session
calls through `bb tool PACK VERB`, and a guidance file Claude reads before it
uses them. An administrator adds a pack by its URL: the controller fetches the
repository at its current commit, shows the manifest, and keeps it pinned to
that commit until somebody approves another. The record lives here, in
/config/toolpacks.json, and never in BuilderBot's repository.

What a pack becomes is one catalog row (recipe()), shipped to the nodes in the
bundle beside config/toolchains.json, so it installs, checks and removes the
way every toolchain does, into the store, read-only to sessions.

    configure(state=, write_json=)
    validate(manifest)          (clean, [errors])
    fetch(url, commit="")       the repository at a commit: {commit, manifest, guidance} or {error}
    preview(url) / add(url, commit, by) / remove(name) / packs() / recipes()
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

FILE = None
write_json = None
_lock = threading.RLock()

MANIFEST = "bbtool.json"
NAME = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
VERB = re.compile(r"^[a-z][a-z0-9-]{0,39}$")
# A path inside the pack: no way out of its directory, nothing hidden.
REL = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.?(?:/|$))[A-Za-z0-9._/-]{1,200}$")
PLATFORM = re.compile(r"^(linux|darwin)/(amd64|arm64|\*)$")
# What a verb's words may name besides plain text: the pack's directory, the
# project's dist/, the project's name, and the words the caller gave.
PLACEHOLDERS = ("{dir}", "{dist}", "{project}", "{args}")
GUIDANCE_MAX = 16 * 1024
MANIFEST_MAX = 64 * 1024
# http too, for a git host on the LAN: what is installed is the commit an
# administrator approved, and git checks every object against its hash, so a
# fetch altered on the way is refused rather than installed.
URL = re.compile(r"^(https://|http://|git@|ssh://)[A-Za-z0-9._~:/@+-]{3,300}$")
FETCH_TIMEOUT = 120


def configure(*, state, write_json):
    globals().update(FILE=Path(state) / "toolpacks.json", write_json=write_json)


def _load():
    try:
        d = json.loads(FILE.read_text())
    except (OSError, ValueError, AttributeError):
        d = {}
    packs = d.get("packs") if isinstance(d, dict) and isinstance(d.get("packs"), dict) else {}
    return {"packs": {k: v for k, v in packs.items() if isinstance(v, dict)}}


def _words(v, what, errors, placeholders=PLACEHOLDERS):
    """A command as a list of words, never a string a shell would read."""
    if not isinstance(v, list) or not v or not all(isinstance(w, str) and w for w in v):
        errors.append(f"{what} is a list of words, e.g. [\"{{dir}}/bin/tool\", \"{{args}}\"]")
        return None
    for w in v:
        for m in re.findall(r"\{[a-z]+\}", w):
            if m not in placeholders:
                errors.append(f"{what} names {m}, which is not one of {', '.join(placeholders)}")
    if v.count("{args}") > 1:
        errors.append(f"{what} names {{args}} more than once")
    if any("{args}" in w and w != "{args}" for w in v):
        errors.append(f"{what}: {{args}} is a word of its own, the caller's words in its place")
    return [str(w) for w in v]


def validate(m, shipped=()):
    """A manifest checked and cut down to what BuilderBot reads: (clean,
    errors). Nothing in it is run here; the errors say what to fix."""
    errors = []
    if not isinstance(m, dict):
        return None, [f"{MANIFEST} is a JSON object"]
    name = str(m.get("name") or "")
    if not NAME.fullmatch(name):
        errors.append("name is 2 to 40 of a-z, 0-9 and -, starting with a letter")
    elif name in shipped:
        errors.append(f"{name} is a toolchain BuilderBot ships; a pack takes a name of its own")
    out: dict = {"name": name,
           "label": str(m.get("label") or name)[:80],
           "about": str(m.get("about") or "")[:400]}
    plats = m.get("platforms") or []
    if not isinstance(plats, list) or not plats or not all(isinstance(p, str) and PLATFORM.fullmatch(p) for p in plats):
        errors.append("platforms lists where it works, e.g. [\"linux/amd64\", \"linux/arm64\"]")
    out["platforms"] = [p for p in plats if isinstance(p, str)] if isinstance(plats, list) else []
    terms = m.get("terms") or []
    if not isinstance(terms, list) or not all(isinstance(t, dict) and t.get("label") for t in terms):
        errors.append("terms lists what it is under, each {label, url}")
        terms = []
    out["terms"] = [{"label": str(t["label"])[:120], "url": str(t.get("url") or "")[:300]} for t in terms]
    inst = m.get("install") or {}
    if not isinstance(inst, dict):
        errors.append("install is an object: steps (each a list of words) and verify")
        inst = {}
    steps = []
    for i, s in enumerate(inst.get("steps") or []):
        w = _words(s, f"install step {i + 1}", errors, ("{dir}",))
        if w:
            steps.append(w)
    out["steps"] = steps
    out["verify"] = _words(inst["verify"], "install verify", errors, ("{dir}",)) if inst.get("verify") else None
    lay = m.get("layout") or {}
    if not isinstance(lay, dict):
        errors.append("layout is an object: bin, env and tool")
        lay = {}
    bins = lay.get("bin") or []
    if not isinstance(bins, list) or not all(isinstance(b, str) and REL.fullmatch(b) for b in bins):
        errors.append("layout.bin lists directories inside the pack to put on PATH")
        bins = []
    tool = lay.get("tool") or ""
    if tool and not (isinstance(tool, str) and REL.fullmatch(tool)):
        errors.append("layout.tool is a file inside the pack whose presence says it is installed")
        tool = ""
    env = lay.get("env") or {}
    if not isinstance(env, dict) or not all(re.fullmatch(r"[A-Z][A-Z0-9_]{0,40}", k) and isinstance(v, str)
                                            for k, v in env.items()):
        errors.append("layout.env maps NAME to a path inside the pack (\"\" for the pack itself) or =VALUE")
        env = {}
    out["layout"] = {"bin": bins, "env": env, "tool": tool or MANIFEST}
    apt = (m.get("system") or {}).get("apt") if isinstance(m.get("system"), dict) else None
    if apt is not None and not (isinstance(apt, list) and all(isinstance(a, str) and re.fullmatch(r"[a-z0-9.+|-]{1,80}", a)
                                                              for a in apt)):
        errors.append("system.apt lists Debian package names")
        apt = None
    if apt:
        out["system"] = {"apt": apt}
    verbs = m.get("verbs") or {}
    if not isinstance(verbs, dict) or not verbs:
        errors.append("verbs names at least one command a session calls, each {about, usage, run}")
        verbs = {}
    out["verbs"] = {}
    for v, spec in verbs.items():
        if not VERB.fullmatch(str(v)):
            errors.append(f"verb {v!r}: a-z, 0-9 and -, starting with a letter")
            continue
        if not isinstance(spec, dict):
            errors.append(f"verb {v} is an object: about, usage and run")
            continue
        w = _words(spec.get("run"), f"verb {v}'s run", errors)
        if not w:
            continue
        first = w[0]
        # The program a verb runs is the pack's own: a file inside its
        # directory, or a script the pack carries run by sh or python3.
        inside = first.startswith("{dir}/") and REL.fullmatch(first[6:])
        script = first in ("sh", "bash", "python3") and len(w) > 1 and w[1].startswith("{dir}/") \
            and REL.fullmatch(w[1][6:])
        if not (inside or script):
            errors.append(f"verb {v} runs {first}: a verb runs a file inside the pack ({{dir}}/...), "
                          "or sh, bash or python3 on a script inside it")
            continue
        out["verbs"][v] = {"about": str(spec.get("about") or "")[:300],
                           "usage": str(spec.get("usage") or "")[:200], "run": w}
    g = m.get("guidance") or ""
    if g and not (isinstance(g, str) and REL.fullmatch(g)):
        errors.append("guidance names a Markdown file inside the pack")
        g = ""
    out["guidance_file"] = g
    return (out if not errors else None), errors


def _git(args, cwd=None, timeout=FETCH_TIMEOUT):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env, check=False)


def fetch(url, commit="", shipped=()):
    """The repository at `commit` (its default branch's head when none):
    {commit, manifest, guidance} with the manifest validated, or {error}.
    Fetched into a scratch directory that is gone when this returns."""
    url = str(url or "").strip()
    # A suite's pack is a repository on disk (BB_TOOLPACKS_FILE_URLS=1); a
    # controller only ever fetches one over the network.
    local = os.environ.get("BB_TOOLPACKS_FILE_URLS") == "1" and url.startswith("file:///")
    if not (URL.fullmatch(url) or local):
        return {"error": "a pack is a git repository's address: https://host/owner/repo"}
    if commit and not re.fullmatch(r"[0-9a-f]{40}", commit):
        return {"error": "a commit is its full 40-character hash"}
    tmp = tempfile.mkdtemp(prefix="toolpack-")
    try:
        for args in (["init", "-q", tmp], ["-C", tmp, "fetch", "-q", "--depth", "1", url, commit or "HEAD"]):
            try:
                r = _git(args)
            except subprocess.TimeoutExpired:
                return {"error": f"{url} did not answer within {FETCH_TIMEOUT}s"}
            if r.returncode != 0:
                said = (r.stderr or r.stdout).strip().splitlines()
                return {"error": f"could not fetch {url}: {said[-1] if said else 'git failed'}"}
        got = _git(["-C", tmp, "rev-parse", "FETCH_HEAD"]).stdout.strip()
        if commit and got != commit:
            return {"error": f"{url} answered {got[:12]} where {commit[:12]} was asked"}

        def read(rel, cap):
            r = subprocess.run(["git", "-C", tmp, "show", f"FETCH_HEAD:{rel}"], capture_output=True,
                               timeout=30, check=False)
            if r.returncode != 0:
                return None
            return r.stdout[:cap + 1]
        raw = read(MANIFEST, MANIFEST_MAX)
        if raw is None:
            return {"error": f"{url} has no {MANIFEST} at its root"}
        if len(raw) > MANIFEST_MAX:
            return {"error": f"{MANIFEST} is over {MANIFEST_MAX // 1024} KB"}
        try:
            m = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            return {"error": f"{MANIFEST} is not JSON: {e}"}
        clean, errors = validate(m, shipped)
        if errors:
            return {"error": f"{MANIFEST} needs fixing: " + "; ".join(errors), "errors": errors, "commit": got}
        guidance = ""
        if clean["guidance_file"]:
            g = read(clean["guidance_file"], GUIDANCE_MAX)
            if g is None:
                return {"error": f"{MANIFEST} names {clean['guidance_file']} as its guidance, and it is not there"}
            guidance = g[:GUIDANCE_MAX].decode("utf-8", "replace")
        return {"commit": got, "manifest": clean, "guidance": guidance,
                "plain": url.startswith("http://")}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def packs():
    with _lock:
        return _load()["packs"]


def add(url, commit, by, shipped=()):
    """Keep a pack pinned to `commit`, which the person approving it saw:
    the repository is fetched again at exactly that commit, so what is kept
    is what was shown. A pack of the same name is replaced (an update)."""
    got = fetch(url, commit, shipped)
    if got.get("error"):
        return got
    m = got["manifest"]
    with _lock:
        d = _load()
        rec = {"name": m["name"], "url": url, "commit": got["commit"], "manifest": m,
               "guidance": got["guidance"], "by": str(by or ""), "at": int(time.time())}
        was = d["packs"].get(m["name"])
        if was and was.get("url") != url:
            return {"error": f"a pack called {m['name']} is already here from {was.get('url')}; remove it first"}
        d["packs"][m["name"]] = rec
        write_json(FILE, d)
    return {"ok": True, "pack": rec, "replaced": bool(was)}


def remove(name):
    with _lock:
        d = _load()
        if name not in d["packs"]:
            return {"error": f"no tool pack called {name}"}
        del d["packs"][name]
        write_json(FILE, d)
    return {"ok": True}


def recipe(rec):
    """A pack as one catalog row: the recipe machinery's own shape, its
    source the pack's repository cloned at the approved commit, then its
    install steps, then its verify. `pack` marks it as added, not shipped."""
    m = rec["manifest"]
    src = {"kind": "git", "url": rec["url"], "commit": rec["commit"], "fresh_only": True}
    if m["steps"]:
        src["then"] = [{"run": s} for s in m["steps"]]
    if m.get("verify"):
        src["verify"] = m["verify"]
    row = {"name": m["name"], "label": m["label"], "probe": m["name"], "about": m["about"],
           "platforms": m["platforms"], "layout": m["layout"], "source": src, "terms": m["terms"],
           "verbs": m["verbs"],
           "pack": {"url": rec["url"], "commit": rec["commit"], "by": rec.get("by", ""), "at": rec.get("at", 0),
                    "guidance": rec.get("guidance", "")}}
    if m.get("system"):
        row["system"] = m["system"]
    return row


def recipes():
    """Every pack as a catalog row, in name order."""
    return [recipe(r) for _, r in sorted(packs().items())]


def catalog_json():
    """What the bundle carries beside config/toolchains.json, for the nodes:
    "" when no pack was added, so the bundle carries no file for none."""
    rows = recipes()
    return json.dumps({"toolchains": rows}, indent=1, sort_keys=True) if rows else ""
