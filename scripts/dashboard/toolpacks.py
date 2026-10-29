"""Tool packs (R77): toolchains a person adds from a git repository of their
own choosing, which BuilderBot neither ships nor lists anywhere.

A pack is a repository with a bbtool.json at its root. The manifest says how
the toolchain installs (the catalog's own recipe machinery, its source being
the pack's repository at the commit that was approved), the verbs a session
calls through `bb tool PACK VERB`, and a guidance file a session reads before it
uses them. An administrator adds a pack by its URL: the controller fetches the
repository at its current commit, shows the manifest, and keeps it pinned to
that commit until somebody approves another. The record lives here, in
/config/toolpacks.json, and never in BuilderBot's repository.

What a pack becomes is one catalog row (recipe()), shipped to the nodes in the
bundle beside config/toolchains.json, so it installs, checks and removes the
way every toolchain does, into the store, read-only to sessions.

A pack may also be made here, with no repository of its own: a pasted
bbtool.json, or an uploaded zip or tarball of the pack's files. The
controller keeps it as a repository of its own (/config/toolpacks/NAME.git),
each approved version a commit there, so it is pinned, compared and approved
the same way; the nodes take it as a git bundle that travels in the bundle
beside config/toolpacks.json, and install it with the same pinned fetch.

    configure(state=, write_json=, unpack=)
    validate(manifest)          (clean, [errors])
    fetch(url, commit="")       the repository at a commit: {commit, manifest, guidance} or {error}
    stage(text=, archive=)      a pack made here, checked and held for Add: {staged, manifest, ...}
    add(url, commit, by) / add_staged(staged, by) / remove(name) / source(name)
    packs() / recipes() / hosted_files()
"""
import json
import os
import re
import secrets
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
NAME_OFFICIAL = re.compile(r"^[a-z][a-z0-9:-]{1,39}$")
# A shipped layout may name the pack's own root ("") or a place under the
# store's root (root:android/...), which a person's pack may not.
REL_OFFICIAL = re.compile(r"^(|root:[A-Za-z0-9._/-]{1,200}|(?!/)(?!.*(?:^|/)\.\.?(?:/|$))[A-Za-z0-9._/-]{1,200})$")
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
# A pack made here: its address in the record, and where it is kept. It
# travels to every node in the bundle, so it is held small: a pack made
# here carries scripts and a manifest, and fetches anything big as it
# installs.
HERE = "here:"
HOSTED = None
unpack = None                 # projects.unpack_archive, handed over by configure()
HOSTED_MAX = 8 << 20
HOSTED_FILES = 2000
STAGE_TTL = 30 * 60
STAGE_ID = re.compile(r"^[0-9a-f]{16}$")
AUTHOR = ("-c", "user.name=BuilderBot", "-c", "user.email=builderbot@localhost")


def configure(*, state, write_json, unpack=None):
    globals().update(FILE=Path(state) / "toolpacks.json", write_json=write_json,
                     HOSTED=Path(state) / "toolpacks", unpack=unpack)


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


# One manifest for everything (R169 step 1): a pack's tier, and the two
# blocks the official packs carry beyond a person's pack. `shipped` is a
# toolchain's recipe as config/toolchains.json has it (its source, probe,
# system packages and the rest), which the installer runs; `agent` is a
# coding agent's adapter as agents.py's table has it. Either stands in for
# install steps and verbs, since what they install is the tool itself.
TIERS = ("official", "vetted", "url")
# What a pack asks for per node (R172): each field's kind, drawn by the
# Library as Configure on the card, the answers kept sealed on the
# controller and handed to the node. A `list` field is rows of `fields`.
CONFIG_KINDS = ("secret", "text", "choice", "list", "switch", "projects")
CONFIG_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,40}$")
# A deployed thing an official pack stands for (R172): the model router.
SERVICES = ("router",)
AGENT_FIELDS = ("product", "command", "provider", "reported", "update_job", "login_job", "logout_job",
                "briefing", "guards", "state", "transcripts", "latest_url", "tool")
AGENT_BRIEFING = ("system-prompt-file", "instructions-file")
AGENT_GUARDS = ("hooks", "plugin", "approval")
AGENT_STATES = ("hooks", "plugin", "session-log")


def _agent(a, errors):
    """The agent block checked: an agent that cannot take the guards is
    not listed (R169 step 1)."""
    if not isinstance(a, dict):
        errors.append("agent is an object: product, command, provider, reported, the jobs, briefing, guards, state, transcripts")
        return None
    out = {}
    for k in AGENT_FIELDS:
        v = a.get(k, "")
        if not isinstance(v, str) or len(v) > 200:
            errors.append(f"agent.{k} is a string")
            return None
        out[k] = v
    for k in ("product", "command", "reported", "update_job", "transcripts"):
        if not out[k]:
            errors.append(f"agent.{k} is required")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", out["command"] or "x"):
        errors.append("agent.command is the program's name on PATH")
    if out["briefing"] not in AGENT_BRIEFING:
        errors.append(f"agent.briefing is one of {', '.join(AGENT_BRIEFING)}")
    if out["guards"] not in AGENT_GUARDS:
        errors.append(f"agent.guards is one of {', '.join(AGENT_GUARDS)}: an agent that cannot take BuilderBot's guards is not listed")
    if out["state"] not in AGENT_STATES:
        errors.append(f"agent.state is one of {', '.join(AGENT_STATES)}")
    if out["transcripts"] and not REL.fullmatch(out["transcripts"]):
        errors.append("agent.transcripts is a path under the account's home")
    if out["latest_url"] and not re.fullmatch(r"https://[A-Za-z0-9._~:/@+?=&%-]{3,300}", out["latest_url"]):
        errors.append("agent.latest_url is an https address")
    return out


def _config(c, errors, depth=0):
    """The config block checked: a list of fields, each {name, label, kind,
    help, required, env, choices (choice), fields (list)}; [] with the
    errors said."""
    if not isinstance(c, list) or len(c) > 24:
        errors.append("config is a list of up to 24 fields, each {name, label, kind, help, required}")
        return []
    out, seen = [], set()
    for f in c:
        if not isinstance(f, dict):
            errors.append("a config field is an object")
            continue
        name, kind = str(f.get("name") or ""), str(f.get("kind") or "text")
        if not CONFIG_NAME.fullmatch(name) or name in seen:
            errors.append(f"config field {name or '(unnamed)'}: name is 1 to 40 of a-z, 0-9, - and _, starting with a letter, and once")
            continue
        seen.add(name)
        if kind not in CONFIG_KINDS or (kind in ("list", "projects") and depth):
            errors.append(f"config field {name}: kind is one of {', '.join(CONFIG_KINDS)}" + (" (not inside a list)" if depth else ""))
            continue
        field = {"name": name, "kind": kind, "label": str(f.get("label") or name)[:60], "help": str(f.get("help") or "")[:200],
                 "required": f.get("required") is True}
        # Whose the value is (R172 step 5): the node's (one for everybody
        # there), or each person's own on that node, kept under their key.
        scope = str(f.get("scope") or "node")
        if scope not in ("node", "person") or (depth and scope != "node"):
            errors.append(f"config field {name}: scope is node or person" + (" (a list's rows are the list's)" if depth else ""))
            continue
        if scope == "person":
            field["scope"] = "person"
        env = str(f.get("env") or "")
        if env and not ENV_NAME.fullmatch(env):
            errors.append(f"config field {name}: env is a NAME a verb reads it as")
        elif env:
            field["env"] = env
        if kind == "choice":
            ch = f.get("choices")
            if not isinstance(ch, list) or not ch or not all(isinstance(x, dict) and str(x.get("value") or "") for x in ch):
                errors.append(f"config field {name}: choices lists {{value, label}}")
                continue
            field["choices"] = [{"value": str(x["value"])[:60], "label": str(x.get("label") or x["value"])[:60]} for x in ch[:24]]
        if kind == "list":
            sub_errors = []
            field["fields"] = _config(f.get("fields"), sub_errors, depth + 1)
            if sub_errors or not field["fields"]:
                errors.append(f"config field {name}: a list names the fields of each row: " + "; ".join(sub_errors or ["none"]))
                continue
        out.append(field)
    return out


def validate(m, shipped=()):
    """A manifest checked and cut down to what BuilderBot reads: (clean,
    errors). Nothing in it is run here; the errors say what to fix. An
    official pack (tier official, R169 step 1) may carry a shipped
    toolchain's recipe or an agent's adapter in place of install steps and
    verbs, and may take a shipped name, being the shipped thing itself."""
    errors = []
    if not isinstance(m, dict):
        return None, [f"{MANIFEST} is a JSON object"]
    tier = str(m.get("tier") or "url")
    if tier not in TIERS:
        errors.append(f"tier is one of {', '.join(TIERS)}")
    official = tier == "official"
    name = str(m.get("name") or "")
    # A shipped toolchain's name may carry a colon (android:emulator), the
    # store's own family form; a person's pack never does.
    if not (NAME_OFFICIAL if official else NAME).fullmatch(name):
        errors.append("name is 2 to 40 of a-z, 0-9 and -, starting with a letter")
    elif name in shipped and not official:
        errors.append(f"{name} is a toolchain BuilderBot ships; a pack takes a name of its own")
    out: dict = {"name": name, "tier": tier,
           "label": str(m.get("label") or name)[:80],
           "about": str(m.get("about") or "")[:400]}
    if official and isinstance(m.get("shipped"), dict):
        out["shipped"] = m["shipped"]
    elif m.get("shipped") is not None:
        errors.append("shipped (a toolchain's recipe) is an official pack's alone")
    if m.get("agent") is not None:
        if not official:
            errors.append("agent (a coding agent's adapter) is an official pack's alone")
        else:
            a = _agent(m["agent"], errors)
            if a:
                out["agent"] = a
    # A deployed thing (R172): the model router, deployed and configured
    # from its card; an official pack's alone, like an agent's adapter.
    if m.get("service") is not None:
        sv = m["service"] if isinstance(m["service"], dict) else {}
        if not official:
            errors.append("service (a deployed thing of BuilderBot's) is an official pack's alone")
        elif str(sv.get("kind") or "") not in SERVICES:
            errors.append(f"service.kind is one of {', '.join(SERVICES)}")
        else:
            out["service"] = {"kind": str(sv["kind"])}
    if m.get("config") is not None:
        out["config"] = _config(m["config"], errors)
    stands_in = "shipped" in out or "agent" in out or "service" in out
    plats = m.get("platforms") or []
    if not isinstance(plats, list) or not plats or not all(isinstance(p, str) and PLATFORM.fullmatch(p) for p in plats):
        # The wildcard named too, in the form the rule takes (B111): a bare
        # "*" is refused, since a platform is matched as os/arch on a node.
        errors.append("platforms lists where it works as os/arch, e.g. [\"linux/amd64\", \"linux/arm64\"], "
                      "or linux/* or darwin/* for any architecture of that system")
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
    rel = REL_OFFICIAL if official else REL
    bins = lay.get("bin") or []
    if not isinstance(bins, list) or not all(isinstance(b, str) and rel.fullmatch(b) for b in bins):
        errors.append("layout.bin lists directories inside the pack to put on PATH")
        bins = []
    tool = lay.get("tool") or ""
    if tool and not (isinstance(tool, str) and rel.fullmatch(tool)):
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
    if not isinstance(verbs, dict) or (not verbs and not stands_in):
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


PATH_IN = re.compile(r"[a-z0-9][\w./-]{0,120}")


def fetch(url, commit="", shipped=(), sha256="", path=""):
    """The repository at `commit` (its default branch's head when none):
    {commit, manifest, guidance} with the manifest validated, or {error}.
    Fetched into a scratch directory that is gone when this returns. With
    `sha256` (the catalog's, of the archive at that commit, R169 step 4)
    the archive is made and compared, and a difference refuses the pack:
    git's own hashes pin the commit, this pins what the maintainers saw."""
    url = str(url or "").strip()
    # A suite's pack is a repository on disk (BB_TOOLPACKS_FILE_URLS=1); a
    # controller only ever fetches one over the network.
    local = os.environ.get("BB_TOOLPACKS_FILE_URLS") == "1" and url.startswith("file:///")
    if not (URL.fullmatch(url) or local):
        return {"error": "a pack is a git repository's address: https://host/owner/repo"}
    if commit and not re.fullmatch(r"[0-9a-f]{40}", commit):
        return {"error": "a commit is its full 40-character hash"}
    # A pack in a folder of the repository (R170 step 6): the archive and
    # the manifest are that folder's.
    path = str(path or "").strip("/")
    if path and (not PATH_IN.fullmatch(path) or ".." in path.split("/")):
        return {"error": "a pack's folder is a plain relative path inside the repository"}
    at = f"{path}/" if path else ""
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
        if sha256:
            if not re.fullmatch(r"[0-9a-f]{64}", sha256):
                return {"error": "the catalog's sha256 is 64 hex digits"}
            import hashlib  # noqa: PLC0415
            r = subprocess.run(["git", "-C", tmp, "archive", "--format=tar", "FETCH_HEAD", *([path] if path else [])], capture_output=True, timeout=120, check=False)
            if r.returncode != 0 or hashlib.sha256(r.stdout).hexdigest() != sha256:
                return {"error": f"{url} at {got[:12]} is not what the catalog vetted: its archive's sha256 differs, so it is refused"}

        def read(rel, cap):
            r = subprocess.run(["git", "-C", tmp, "show", f"FETCH_HEAD:{at}{rel}"], capture_output=True,
                               timeout=30, check=False)
            if r.returncode != 0:
                return None
            return r.stdout[:cap + 1]
        got_m = _examine(read, shipped, f"{url} has no {MANIFEST} at {('its ' + path) if path else 'its root'}")
        if got_m.get("error"):
            return {**got_m, "commit": got} if got_m.get("errors") else got_m
        return {"commit": got, **got_m, "plain": url.startswith("http://"), "path": path}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def fetch_folder(url, commit, sha256, path, files, cap=256 << 10):
    """A catalog entry's folder at the commit it pins (R170 step 7: an app's
    bbapp.json and compose.yml), its archive's sha256 checked as a pack's
    is: {files: {name: bytes}} or {error}. Only the files named are read."""
    url = str(url or "").strip()
    local = os.environ.get("BB_TOOLPACKS_FILE_URLS") == "1" and url.startswith("file:///")
    if not (URL.fullmatch(url) or local):
        return {"error": "a catalog entry is a git repository's address: https://host/owner/repo"}
    if not re.fullmatch(r"[0-9a-f]{40}", str(commit or "")) or not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or "")):
        return {"error": "a catalog entry pins a full commit and its archive's sha256"}
    path = str(path or "").strip("/")
    if not path or not PATH_IN.fullmatch(path) or ".." in path.split("/"):
        return {"error": "a catalog entry's folder is a plain relative path inside the repository"}
    tmp = tempfile.mkdtemp(prefix="catalog-")
    try:
        for args in (["init", "-q", tmp], ["-C", tmp, "fetch", "-q", "--depth", "1", url, commit]):
            try:
                r = _git(args)
            except subprocess.TimeoutExpired:
                return {"error": f"{url} did not answer within {FETCH_TIMEOUT}s"}
            if r.returncode != 0:
                said = (r.stderr or r.stdout).strip().splitlines()
                return {"error": f"could not fetch {url}: {said[-1] if said else 'git failed'}"}
        if _git(["-C", tmp, "rev-parse", "FETCH_HEAD"]).stdout.strip() != commit:
            return {"error": f"{url} did not answer with {commit[:12]}"}
        import hashlib  # noqa: PLC0415
        r = subprocess.run(["git", "-C", tmp, "archive", "--format=tar", "FETCH_HEAD", path], capture_output=True, timeout=120, check=False)
        if r.returncode != 0 or hashlib.sha256(r.stdout).hexdigest() != sha256:
            return {"error": f"{url} at {commit[:12]} is not what the catalog vetted: its archive's sha256 differs, so it is refused"}
        out = {}
        for name in files:
            g = subprocess.run(["git", "-C", tmp, "show", f"FETCH_HEAD:{path}/{name}"], capture_output=True, timeout=30, check=False)
            if g.returncode != 0:
                return {"error": f"{url} has no {name} in {path}"}
            if len(g.stdout) > cap:
                return {"error": f"{path}/{name} is over {cap // 1024} KB"}
            out[name] = g.stdout
        return {"files": out}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _examine(read, shipped, missing):
    """The manifest and guidance a pack's files hold, read through `read(rel,
    cap)`: {manifest, guidance} validated, or {error}. One reading for a
    repository and a pack made here."""
    raw = read(MANIFEST, MANIFEST_MAX)
    if raw is None:
        return {"error": missing}
    if len(raw) > MANIFEST_MAX:
        return {"error": f"{MANIFEST} is over {MANIFEST_MAX // 1024} KB"}
    try:
        m = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return {"error": f"{MANIFEST} is not JSON: {e}"}
    clean, errors = validate(m, shipped)
    if errors:
        return {"error": f"{MANIFEST} needs fixing: " + "; ".join(errors), "errors": errors}
    guidance = ""
    if clean["guidance_file"]:
        g = read(clean["guidance_file"], GUIDANCE_MAX)
        if g is None:
            return {"error": f"{MANIFEST} names {clean['guidance_file']} as its guidance, and it is not there"}
        guidance = g[:GUIDANCE_MAX].decode("utf-8", "replace")
    return {"manifest": clean, "guidance": guidance}


# ---- a pack made here ------------------------------------------------------

def _staging():
    return HOSTED / "staging"


def _sweep_staging():
    now = time.time()
    for d in _staging().iterdir() if _staging().is_dir() else []:
        try:
            if now - d.stat().st_mtime > STAGE_TTL:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _files_in(d):
    """Every file under `d` as a relative path, .git left out."""
    return sorted(str(f.relative_to(d)) for f in d.rglob("*")
                  if f.is_file() and ".git" not in f.relative_to(d).parts)


def _read_in(d):
    def read(rel, cap):
        if not REL.fullmatch(rel):
            return None
        f = d / rel
        try:
            with open(f, "rb") as fh:
                return fh.read(cap + 1)
        except OSError:
            return None
    return read


def stage(text=None, archive="", shipped=()):
    """A pack made here, from a pasted manifest or an uploaded archive (the
    New project dialog's upload, spooled by projects.spool_archive): its
    files checked and held for Add, as {staged, manifest, guidance, files},
    or {error}. Nothing is kept as a pack until somebody presses Add."""
    _staging().mkdir(parents=True, exist_ok=True)
    _sweep_staging()
    tok = secrets.token_hex(8)
    d = _staging() / tok
    d.mkdir()
    out = _stage_into(d, text, archive, shipped)
    if out.get("error"):
        shutil.rmtree(d, ignore_errors=True)
        return out
    return {**out, "staged": tok}


def _stage_into(d, text, archive, shipped):
    """The files of a pack made here, put in `d` and checked."""
    if archive:
        if not unpack:
            return {"error": "uploads are not open here"}
        got = unpack(archive, d)
        if got.get("error"):
            return {"error": got["error"]}
        # A repository's own history is not the pack's: what is kept is
        # this version's files, as a commit made here.
        shutil.rmtree(d / ".git", ignore_errors=True)
        where = "the upload"
    else:
        raw = str(text or "")
        if not raw.strip():
            return {"error": f"paste a {MANIFEST}, or upload the pack's files"}
        if len(raw.encode("utf-8")) > MANIFEST_MAX:
            return {"error": f"{MANIFEST} is over {MANIFEST_MAX // 1024} KB"}
        (d / MANIFEST).write_text(raw, encoding="utf-8")
        where = "what was pasted"
    files = _files_in(d)
    size = sum((d / f).stat().st_size for f in files)
    if len(files) > HOSTED_FILES or size > HOSTED_MAX:
        return {"error": f"a pack made here is at most {HOSTED_MAX >> 20} MB in {HOSTED_FILES} files, "
                         "since every node carries it; fetch what is bigger in its install steps"}
    got = _examine(_read_in(d), shipped, f"{where} has no {MANIFEST} at its top")
    if got.get("error"):
        return got
    return {**got, "files": files[:200], "nfiles": len(files), "here": True}


def _git_here(name, *args, work=None):
    repo = HOSTED / f"{name}.git"
    pre = ["--git-dir", str(repo)] + (["--work-tree", str(work)] if work else [])
    return _git([*AUTHOR, *pre, *args])


def add_staged(staged, by, shipped=()):
    """Keep a pack made here, as the version that was looked at: committed
    to its repository on this controller, its bundle written for the nodes.
    A pack of the same name made here is updated; one from a repository is
    not replaced by it."""
    if not STAGE_ID.fullmatch(str(staged or "")) or not (_staging() / staged).is_dir():
        return {"error": "that upload has gone (they are kept for thirty minutes); paste or upload it again"}
    d = _staging() / staged
    try:
        got = _examine(_read_in(d), shipped, f"no {MANIFEST} at the top")
        if got.get("error"):
            return got
        m = got["manifest"]
        name = m["name"]
        with _lock:
            data = _load()
            was = data["packs"].get(name)
            if was and not was.get("hosted"):
                return {"error": f"a pack called {name} is already here from {was.get('url')}; remove it first"}
            repo = HOSTED / f"{name}.git"
            if not repo.is_dir():
                r = _git(["init", "-q", "--bare", "-b", "main", str(repo)])
                if r.returncode != 0:
                    return {"error": f"could not make {name}'s repository: {(r.stderr or '').strip()}"}
            had = _git_here(name, "rev-parse", "-q", "--verify", "refs/heads/main").stdout.strip()
            for args in (["read-tree", "--empty"], ["add", "-A", "."]):
                r = _git_here(name, *args, work=d)
                if r.returncode != 0:
                    return {"error": f"could not keep {name}: {(r.stderr or '').strip()}"}
            same = had and _git_here(name, "diff", "--cached", "--quiet", had, work=d).returncode == 0
            if not same:
                r = _git_here(name, "commit", "-q", "-m", f"{name}, as {by or 'an administrator'} approved it",
                              work=d)
                if r.returncode != 0:
                    return {"error": f"could not keep {name}: {(r.stderr or r.stdout or '').strip()}"}
            commit = _git_here(name, "rev-parse", "refs/heads/main").stdout.strip()
            r = _git_here(name, "bundle", "create", "-q", str(HOSTED / f"{name}.bundle"), "main")
            if r.returncode != 0:
                return {"error": f"could not write {name}'s bundle: {(r.stderr or '').strip()}"}
            rec = {"name": name, "url": HERE + name, "hosted": True, "commit": commit, "manifest": m,
                   "guidance": got["guidance"], "by": str(by or ""), "at": int(time.time())}
            data["packs"][name] = rec
            write_json(FILE, data)
        return {"ok": True, "pack": rec, "replaced": bool(was), "unchanged": bool(same)}
    finally:
        shutil.rmtree(d, ignore_errors=True)


def source(name):
    """A pack made here, as its bbtool.json reads at the kept version: what
    Edit puts in the paste field. {text} or {error}."""
    rec = packs().get(str(name or ""))
    if not rec or not rec.get("hosted"):
        return {"error": f"{name} is not a pack made here"}
    r = _git_here(rec["name"], "show", f"{rec['commit']}:{MANIFEST}")
    if r.returncode != 0:
        return {"error": f"{name}'s {MANIFEST} could not be read"}
    return {"text": r.stdout}


def hosted_files():
    """The packs made here as the bundle carries them, (path in the bundle,
    file here), beside config/toolpacks.json."""
    return [(f"config/toolpacks/{n}.bundle", HOSTED / f"{n}.bundle")
            for n, r in sorted(packs().items())
            if r.get("hosted") and (HOSTED / f"{n}.bundle").is_file()]


def packs():
    with _lock:
        return _load()["packs"]


def add(url, commit, by, shipped=(), sha256="", tier="url", path=""):
    """Keep a pack pinned to `commit`, which the person approving it saw:
    the repository is fetched again at exactly that commit, so what is kept
    is what was shown. A pack of the same name is replaced (an update).
    From the vetted catalog (R169 step 4) it carries the index's sha256,
    checked on the way in, and its tier. A pack in a folder of the
    repository (`path`, R170 step 6) is kept as a pack made here: that
    folder's files at that commit, committed to its repository on this
    controller, so a node fetches the folder and nothing else."""
    got = fetch(url, commit, shipped, sha256, path)
    if got.get("error"):
        return got
    if path:
        return _add_folder(url, got["commit"], path, by, shipped, sha256, tier)
    m = got["manifest"]
    with _lock:
        d = _load()
        rec = {"name": m["name"], "url": url, "commit": got["commit"], "manifest": m,
               "guidance": got["guidance"], "by": str(by or ""), "at": int(time.time()),
               "tier": "vetted" if tier == "vetted" and sha256 else "url", "sha256": sha256 or ""}
        was = d["packs"].get(m["name"])
        if was and was.get("url") != url:
            return {"error": f"a pack called {m['name']} is already here from {was.get('url')}; remove it first"}
        d["packs"][m["name"]] = rec
        write_json(FILE, d)
    return {"ok": True, "pack": rec, "replaced": bool(was)}


def _add_folder(url, commit, path, by, shipped, sha256, tier):
    """A folder of a repository at a commit, staged as a pack made here and
    kept, its record naming where it came from (R170 step 6)."""
    _staging().mkdir(parents=True, exist_ok=True)
    tok = secrets.token_hex(8)
    d = _staging() / tok
    d.mkdir()
    tmp = tempfile.mkdtemp(prefix="toolpack-")
    try:
        for args in (["init", "-q", tmp], ["-C", tmp, "fetch", "-q", "--depth", "1", url, commit]):
            r = _git(args)
            if r.returncode != 0:
                return {"error": f"could not fetch {url}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or 'git failed'}"}
        arc = subprocess.run(["git", "-C", tmp, "archive", "--format=tar", f"FETCH_HEAD:{path}"], capture_output=True, timeout=120, check=False)
        if arc.returncode != 0:
            return {"error": f"{url} at {commit[:12]} has no folder {path}"}
        import io  # noqa: PLC0415
        import tarfile  # noqa: PLC0415
        with tarfile.open(fileobj=io.BytesIO(arc.stdout), mode="r:") as tar:
            for ti in tar.getmembers():
                if not (ti.isfile() or ti.isdir()) or ti.name.startswith(("/", "..")) or ".." in ti.name.split("/"):
                    return {"error": f"{path} holds something a pack cannot: {ti.name}"}
            tar.extractall(d, filter="data")
    except (subprocess.TimeoutExpired, OSError, tarfile.TarError) as e:
        return {"error": f"could not take {path} from {url}: {e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    out = add_staged(tok, by, shipped)
    shutil.rmtree(d, ignore_errors=True)
    if out.get("error"):
        return out
    with _lock:
        data = _load()
        rec = data["packs"].get(out["pack"]["name"])
        if rec:
            rec.update({"url": url, "commit": commit, "path": path, "sha256": sha256 or "",
                        "tier": "vetted" if tier == "vetted" and sha256 else "url"})
            write_json(FILE, data)
            out["pack"] = rec
    return out


def configs():
    """{pack name: its config fields} for every added pack that asks for
    any (R172), what packconfig.for_node reads the node's answers by."""
    with _lock:
        d = _load()
    return {n: r["manifest"]["config"] for n, r in d["packs"].items() if isinstance(r, dict) and (r.get("manifest") or {}).get("config")}


def where_said(name, where):
    """The refusal for removing a pack still installed (B84): its files
    would stay in those stores with no row left to uninstall them from, and
    a pack added back would read as installed with no install run."""
    return {"error": f"{name} is installed on {', '.join(where)}: uninstall it there first "
                     f"(pick that node in the Library and press Remove on its card), "
                     f"then remove the pack", "installed": list(where)}


def remove(name, where=()):
    """Take a pack out of the catalog; refused while `where` (the nodes that
    hold it) names any."""
    if where:
        return where_said(name, where)
    with _lock:
        d = _load()
        if name not in d["packs"]:
            return {"error": f"no tool pack called {name}"}
        rec = d["packs"].pop(name)
        write_json(FILE, d)
        if rec.get("hosted") and HOSTED and NAME.fullmatch(name):
            shutil.rmtree(HOSTED / f"{name}.git", ignore_errors=True)
            (HOSTED / f"{name}.bundle").unlink(missing_ok=True)
    return {"ok": True}


def recipe(rec):
    """A pack as one catalog row: the recipe machinery's own shape, its
    source the pack's repository cloned at the approved commit, then its
    install steps, then its verify. `pack` marks it as added, not shipped."""
    m = rec["manifest"]
    # A pack made here is fetched from the bundle beside the catalog on the
    # node (sdkmeta.packs_at makes the path whole there).
    url = f"bundle:toolpacks/{m['name']}.bundle" if rec.get("hosted") else rec["url"]
    src = {"kind": "git", "url": url, "commit": rec["commit"], "fresh_only": True}
    if m["steps"]:
        src["then"] = [{"run": s} for s in m["steps"]]
    if m.get("verify"):
        src["verify"] = m["verify"]
    # What the install marks executable (B83): a file committed through a
    # forge's web editor has no executable bit, and every run of it was
    # 'Permission denied'. The programs the verbs, the steps and verify run
    # by path, the layout's tool, and whatever is in its bin directories.
    progs = [w[0] for w in [*(v["run"] for v in m["verbs"].values()), *m["steps"], m.get("verify") or [""]]
             if w and w[0].startswith("{dir}/")]
    tool = m["layout"].get("tool")
    if tool and tool != MANIFEST:
        progs.append("{dir}/" + tool)
    src["exec"] = sorted(set(progs))
    src["exec_dirs"] = ["{dir}/" + b for b in m["layout"].get("bin") or []]
    # about is optional in a manifest, and a catalog row without one is not
    # drawn (B106): the label stands in for it.
    row = {"name": m["name"], "label": m["label"], "probe": m["name"], "about": m["about"] or m["label"],
           "platforms": m["platforms"], "layout": m["layout"], "source": src, "terms": m["terms"],
           "verbs": m["verbs"],
           "pack": {"url": rec["url"], "commit": rec["commit"], "path": rec.get("path", ""), "by": rec.get("by", ""), "at": rec.get("at", 0),
                    "tier": rec.get("tier") or ("here" if rec.get("hosted") else "url"),
                    "guidance": rec.get("guidance", ""), "here": bool(rec.get("hosted"))}}
    if m.get("system"):
        row["system"] = m["system"]
    if m.get("config"):
        row["config"] = m["config"]
    return row


def recipes():
    """Every pack as a catalog row, in name order."""
    return [recipe(r) for _, r in sorted(packs().items())]


def catalog_json():
    """What the bundle carries beside config/toolchains.json, for the nodes:
    "" when no pack was added, so the bundle carries no file for none."""
    rows = recipes()
    return json.dumps({"toolchains": rows}, indent=1, sort_keys=True) if rows else ""
