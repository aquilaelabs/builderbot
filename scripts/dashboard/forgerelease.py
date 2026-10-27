"""The forge's release beside the tag (R123, the operator 4 Oct): when Release
has pushed a version's tag and the project is on GitHub, Gitea or GitLab
with a token that can write there, the forge's release for that tag, titled
with the version, its notes the changelog's section for it, its builds
attached.

On GitHub it is read and written with the project's own token, else the
shared PAT (the same one cilogs.py reads runs with), and only
api.github.com and uploads.github.com are asked. On Gitea (Forgejo and
Codeberg answer the same API) and on GitLab (R124) it is the project's own
token alone, the one its link stored, asked of the API root forges.py
derives from the remote's host and scheme and nothing else: a Gitea on a
LAN is plain http on a port, and that is the address its token was stored
for. GitLab keeps no files on a release, so a build goes into the
project's generic package registry under the version and the release
links to it there.

A release that exists already is changed only by edit() (R139, the
operator 5 Oct): its notes replaced, files attached to it (one of the same
name replaced), never the release deleted or its tag moved, and only with
files from the project's dist/ or its committed tree, which edit_plan()
checks before anybody is asked. A file comes off a release only by
remove(), its own ask and never part of an edit (the operator, 5 Oct).

A release that exists already for the tag is left as it is and pointed at:
a second press makes nothing twice. What was made, or why nothing was, is
kept per project and tag, so the version row can link to it or say the
reason.

Builds are matched on the released commit: a file in dist/ whose name
carries that commit's short id (every build is named so) and is not a
dirty one, or carries the id of another commit with the same tree. Work
lands through a pull request, so the tag goes on the merge commit while
the builds were made, and signed, from the branch tip it merged: the same
files under another id (Shebang-DevBoard's v0.5.4, 5 Oct, released with
nothing attached). Signed ones are what a release carries when there are any; an
unsigned or debug build only where nothing signed was built.
"""
import json
import mimetypes
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import changelog
import cilogs
import forges

STATE = Path("/config")
WORKSPACE = Path("/workspace")
write_json = None

API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
ASSET_MAX = 1_900_000_000         # GitHub takes 2 GiB a file; this leaves room
SHIPS = re.compile(r"\.(apk|aab|zip|xpi|tar\.gz|tgz|exe|msi|dmg|deb|rpm|AppImage)$")


class Refused(Exception):
    """A release this module will not make, with the sentence to show."""


def configure(*, state, workspace, write_json_fn):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), write_json=write_json_fn)
    import gitcreds                                         # noqa: PLC0415
    gitcreds.configure(state=state)


def _file():
    return STATE / "forge-releases.json"


def kept(project):
    """{tag: {url, error}} of the releases made, or refused, for this project."""
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}
    got = d.get(project) if isinstance(d, dict) else None
    return got if isinstance(got, dict) else {}


def _keep(project, tag, url, error="", forge="GitHub"):
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault(project, {})[tag] = {"url": url, "error": error, "forge": forge}
    if write_json:
        write_json(_file(), d)


# ---- what goes in it ----------------------------------------------------------

def notes(where, version):
    """The changelog's section for `version`, as Markdown, or "" when the
    file has none: its categories as headings and its entries as a list.
    A version cut without a bump has its changes still under Unreleased,
    and those are what it releases (v0.5.0 went out with no notes, B116)."""
    text = changelog.read(where) or ""
    pending = None
    for sec in changelog.sections(text):
        title = sec.get("title") or ""
        if title == version or title.startswith(version + ":") or title.startswith(version + " "):
            return _listed(sec)
        if pending is None and title == "Unreleased":
            pending = sec
    return _listed(pending) if pending else ""


def _listed(sec):
    out, cat = [], None
    for e in sec.get("entries") or []:
        if e.get("cat") != cat:
            cat = e.get("cat")
            if cat:
                out.append(f"\n### {cat}\n")
        out.append(f"- {e.get('text', '')}")
    return "\n".join(out).strip()


def _shown(project):
    """The name the project is shown under, not its folder (B116: a release
    read "builderbot-2 0.5.0")."""
    import roles
    return roles.shown(project)


def assets(project, sha):
    """The builds of commit `sha` in the project's dist/, signed ones when
    there are any: [Path], newest first."""
    d = WORKSPACE / project / "dist"
    if not sha or not d.is_dir():
        return []
    # An unsigned APK installs nowhere and is the controller's to sign
    # (releasesign.py, R106): never one of a release's files.
    ships = [f for f in d.iterdir() if f.is_file() and "-dirty" not in f.name and "-unsigned" not in f.name
             and SHIPS.search(f.name)]
    files = [f for f in ships if sha in f.name]
    if not files:
        same = _same_tree(project, sha, {m.group(1) for f in ships for m in [BUILD_SHA.search(f.name)] if m})
        files = [f for f in ships if (m := BUILD_SHA.search(f.name)) and m.group(1) in same]
    signed = [f for f in files if "-signed" in f.name]
    if signed:
        files = signed
    else:
        real = [f for f in files if "-debug" not in f.name]
        files = real or files
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


BUILD_SHA = re.compile(r"-([0-9a-f]{7,12})(?=[-.])")


def _same_tree(project, sha, others):
    """Those of `others` (short commit ids from build names) whose commit
    holds the same tree as `sha`: the same files, built before a merge."""
    def tree(c):
        try:
            r = subprocess.run(["git", "-C", str(WORKSPACE / project), "rev-parse", "--verify", "--quiet",
                                f"{c}^{{tree}}"], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""
    want = tree(sha)
    return {c for c in others if want and tree(c) == want} if want else set()


# ---- asking GitHub ------------------------------------------------------------

def _req(method, url, token, body=None, data=None, ctype="application/json"):
    if not (url.startswith(API + "/repos/") or url.startswith(UPLOADS + "/repos/")):
        raise Refused("not an address this asks GitHub at")
    payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=payload, method=method,
                                 headers={"User-Agent": "BuilderBot", "Accept": "application/vnd.github+json",
                                          **({"Content-Type": ctype} if payload is not None else {})})
    req.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        # The host is one of the two literals above, checked; the path is the repo's.
        with urllib.request.urlopen(req, timeout=600) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            raw = r.read(2_000_000)
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code == 404 and method == "GET":
            return None
        try:
            why = (json.loads(e.read(20000)) or {}).get("message") or ""
        except (ValueError, OSError):
            why = ""
        if e.code in (401, 403):
            raise Refused("GitHub refused the token for releases: it needs contents write "
                          "on this repository" + (f" ({why})" if why else "")) from e
        raise Refused(f"GitHub answered {e.code}" + (f": {why}" if why else "")) from e
    except (urllib.error.URLError, OSError) as e:
        raise Refused(f"could not reach GitHub: {e}") from e


def publish(project, tag, version, sha, comp=""):
    """The forge's release for `tag`, made if it is not there:
    {url, made, assets, skipped, forge} or {error, forge}."""
    if cilogs.repo_of(project):
        return _github(project, tag, version, sha, comp)
    at = _remote(project)
    entry = forges.forge_of(at["host"]) if at else None
    if not at or not entry or entry["kind"] not in ("gitea", "gitlab"):
        name = entry["name"] if at and entry and entry["id"] != "git" else ""
        why = (f"{project} is on {name}, which has no release this can make, so the tag is its release"
               if name else f"{project} is not on GitHub, Gitea or GitLab, so the tag is its release")
        return {"error": why, "forge": name}
    name = entry["name"]
    token, scheme = _own_token(project, at["host"])
    if not token:
        why = f"the controller has no {name} token for this project, so the tag is its release"
        _keep(project, tag, "", why, name)
        return {"error": why, "forge": name}
    base = forges.api_base(entry, at["host"], scheme or ("https" if at["scheme"] == "ssh" else at["scheme"]))
    where = WORKSPACE / project / comp if comp else WORKSPACE / project
    title = f"{comp + ' ' if comp else ''}{version}"
    body = notes(where, version) or f"{_shown(project)} {version}"
    try:
        made = (_gitlab if entry["kind"] == "gitlab" else _gitea)(
            _Forge(base, entry, token), at, project, tag, version, sha, title, body)
    except Refused as e:
        _keep(project, tag, "", str(e), name)
        return {"error": str(e), "forge": name}
    _keep(project, tag, made["url"], "", name)
    return made | {"forge": name}


def _github(project, tag, version, sha, comp=""):
    repo = cilogs.repo_of(project)
    token = cilogs._token(project)
    if not token:
        why = "the controller has no GitHub token for this project, so the tag is its release"
        _keep(project, tag, "", why)
        return {"error": why, "forge": "GitHub"}
    base = f"{API}/repos/{repo}/releases"
    try:
        have = _req("GET", f"{base}/tags/{urllib.parse.quote(tag)}", token)
        if have:
            _keep(project, tag, have.get("html_url") or "")
            return {"url": have.get("html_url") or "", "made": False, "assets": [], "skipped": [],
                    "forge": "GitHub"}
        where = WORKSPACE / project / comp if comp else WORKSPACE / project
        body = notes(where, version) or f"{_shown(project)} {version}"
        rel = _req("POST", base, token, {"tag_name": tag, "name": f"{comp + ' ' if comp else ''}{version}",
                                         "body": body, "draft": False, "prerelease": False})
        up, skipped = [], []
        for f in assets(project, sha):
            size = f.stat().st_size
            if size > ASSET_MAX:
                skipped.append(f"{f.name} is {size // 1_000_000} MB, over GitHub's limit")
                continue
            url = f"{UPLOADS}/repos/{repo}/releases/{int(rel['id'])}/assets?name={urllib.parse.quote(f.name)}"
            try:
                _req("POST", url, token, data=f.read_bytes(), ctype="application/octet-stream")
                up.append(f.name)
            except Refused as e:
                skipped.append(f"{f.name}: {e}")
        _keep(project, tag, rel.get("html_url") or "")
        return {"url": rel.get("html_url") or "", "made": True, "assets": up, "skipped": skipped,
                "forge": "GitHub"}
    except Refused as e:
        _keep(project, tag, "", str(e))
        return {"error": str(e), "forge": "GitHub"}


# ---- Gitea and GitLab (R124) ---------------------------------------------------

def _remote(project):
    """{scheme, host, path} of the project's forge: the push record its link
    wrote, else the tree's origin. None when it has neither."""
    rec = cilogs.push_record(project) if cilogs.push_record else None
    if isinstance(rec, dict) and rec.get("repo") and rec.get("host"):
        return {"scheme": "", "host": str(rec["host"]), "path": str(rec["repo"]).removesuffix(".git")}
    try:
        cfg = cilogs.read_config(WORKSPACE / project / ".git") if cilogs.read_config else {}
    except Exception:  # noqa: BLE001 (an unreadable config is no remote)
        cfg = {}
    url = ((cfg.get("remote.origin.url") or [""])[-1]) if isinstance(cfg, dict) else ""
    got = forges.parse(url) if url else None
    return got if got and got.get("path") else None


def _own_token(project, host):
    """(token, scheme) from the project's stored credential line when it was
    written for this host, else ("", ""). The scheme is the line's: a token
    stored for http://host:3000 is the address that host answers on."""
    import gitcreds                                         # noqa: PLC0415
    line = gitcreds.read_line(project) if gitcreds.STATE else ""
    m = re.match(r"(https?)://[^:@/]*:([^@/]+)@([A-Za-z0-9.:%-]+)$", line)
    if not m:
        return "", ""
    stored = urllib.parse.unquote(m.group(3)).lower()
    want = host.lower()
    if stored != want and stored.split(":")[0] != want.split(":")[0]:
        return "", ""
    return urllib.parse.unquote(m.group(2)), m.group(1)


class _Forge:
    """One forge's API root and token. Asks nothing outside that root, and
    keeps the token home on a redirect (forges._OPENER)."""

    def __init__(self, base, entry, token):
        self.base, self.entry, self.token = base, entry, token

    def ask(self, method, path, body=None, data=None, ctype="application/json"):
        url = self.base + path
        if not path.startswith("/") or not url.lower().startswith(("https://", "http://")):
            raise Refused(f"not an address this asks {self.entry['name']} at")
        payload = data if data is not None else (json.dumps(body).encode() if body is not None else None)
        auth = ({"PRIVATE-TOKEN": self.token} if self.entry["kind"] == "gitlab"
                else {"Authorization": f"token {self.token}"})
        req = urllib.request.Request(url, data=payload, method=method,
                                     headers={"User-Agent": "BuilderBot", "Accept": "application/json", **auth,
                                              **({"Content-Type": ctype} if payload is not None else {})})
        name = self.entry["name"]
        try:
            # The root is forges.api_base()'s, from a host its URL pattern
            # matched and a scheme of http or https, checked above.
            with forges._OPENER.open(req, timeout=600) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
                raw = r.read(2_000_000)
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code == 404 and method == "GET":
                return None
            try:
                j = json.loads(e.read(20000)) or {}
                why = str(j.get("message") or j.get("error") or "") if isinstance(j, dict) else ""
            except (ValueError, OSError):
                why = ""
            if e.code in (401, 403):
                need = "the api scope" if self.entry["kind"] == "gitlab" else "the repository scope with write"
                raise Refused(f"{name} refused the token for releases: it needs {need} "
                              f"on this repository" + (f" ({why})" if why else "")) from e
            raise Refused(f"{name} answered {e.code}" + (f": {why}" if why else "")) from e
        except (urllib.error.URLError, OSError) as e:
            raise Refused(f"could not reach {name}: {e}") from e


def _gitea(f, at, project, tag, version, sha, title, body):
    """Gitea's API is GitHub's shape: the release by its tag, made if it is
    not there, and each build attached to it as a multipart upload."""
    owner, _, repo = at["path"].partition("/")
    base = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/releases"
    have = f.ask("GET", f"{base}/tags/{urllib.parse.quote(tag)}")
    if have:
        return {"url": have.get("html_url") or "", "made": False, "assets": [], "skipped": []}
    # Gitea takes a pushed tag into its database on a queue, a moment after
    # the push: a release asked for at once is refused as "repo is empty"
    # or its tag not found (measured on 1.24, 5 Oct), so it is asked again
    # for a few seconds before that answer is believed.
    for wait in (1, 2, 3, 4, 0):
        try:
            rel = f.ask("POST", base, {"tag_name": tag, "name": title, "body": body,
                                       "draft": False, "prerelease": False})
            break
        except Refused as e:
            if not wait or not re.search(r"answered (409|422|404)", str(e)):
                raise
            time.sleep(wait)
    up, skipped = [], []
    for p in assets(project, sha):
        size = p.stat().st_size
        if size > ASSET_MAX:
            skipped.append(f"{p.name} is {size // 1_000_000} MB, too big to attach")
            continue
        data, ctype = _multipart("attachment", p.name, p.read_bytes())
        try:
            f.ask("POST", f"{base}/{int(rel['id'])}/assets?name={urllib.parse.quote(p.name)}", data=data, ctype=ctype)
            up.append(p.name)
        except Refused as e:
            skipped.append(f"{p.name}: {e}")
    return {"url": rel.get("html_url") or "", "made": True, "assets": up, "skipped": skipped}


def _gitlab(f, at, project, tag, version, sha, title, body):
    """GitLab names a project by its whole path, encoded, and a release holds
    links rather than files: each build goes into the generic package
    registry under the version, and the release links to it there."""
    pid = urllib.parse.quote(at["path"], safe="")
    web = f"{f.base.split('/api/')[0]}/{at['path']}/-/releases/{urllib.parse.quote(tag)}"
    have = f.ask("GET", f"/projects/{pid}/releases/{urllib.parse.quote(tag)}")
    if have:
        return {"url": ((have.get("_links") or {}).get("self") or web), "made": False, "assets": [], "skipped": []}
    rel = f.ask("POST", f"/projects/{pid}/releases", {"tag_name": tag, "name": title, "description": body})
    # A package's name and version are GitLab's own charset; the project's
    # name and the version already are, and anything else becomes a dash.
    pkg = re.sub(r"[^A-Za-z0-9._-]", "-", project) or "builds"
    ver = re.sub(r"[^A-Za-z0-9._+-]", "-", version) or "0"
    up, skipped = [], []
    for p in assets(project, sha):
        size = p.stat().st_size
        if size > ASSET_MAX:
            skipped.append(f"{p.name} is {size // 1_000_000} MB, too big to attach")
            continue
        path = f"/projects/{pid}/packages/generic/{pkg}/{ver}/{urllib.parse.quote(p.name)}"
        try:
            f.ask("PUT", path, data=p.read_bytes(), ctype="application/octet-stream")
            f.ask("POST", f"/projects/{pid}/releases/{urllib.parse.quote(tag)}/assets/links",
                  {"name": p.name, "url": f.base + path, "link_type": "package"})
            up.append(p.name)
        except Refused as e:
            skipped.append(f"{p.name}: {e}")
    return {"url": ((rel.get("_links") or {}).get("self") or web), "made": True, "assets": up, "skipped": skipped}


def _multipart(field, name, data):
    """One file as multipart/form-data, which is how Gitea takes an asset."""
    boundary = "bb" + os.urandom(12).hex()
    safe = name.replace('"', "_").replace("\r", "_").replace("\n", "_")
    head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; filename=\"{safe}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode()
    return head + data + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


# ---- editing a published release (R139) ----------------------------------------

NOTES_MAX = 100_000
ATTACH_MAX = 20
ATTACHABLE = re.compile(r"\.(apk|aab|zip|xpi|tar\.gz|tgz|exe|msi|dmg|deb|rpm|AppImage|png|jpe?g|gif|webp|pdf|txt|sha256)$",
                        re.I)
TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
ASSET_REF = re.compile(r"\(asset:([^)\s]+)\)")
FILE_REF = re.compile(r"\(file:([^)\s]+)\)")
SHOWABLE = re.compile(r"\.(png|jpe?g|gif|webp|svg)$", re.I)


def _tree_git(project, *args):
    try:
        return subprocess.run(["git", "-C", str(WORKSPACE / project), *args], capture_output=True,
                               text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


def edit_plan(project, tag, notes=None, attach=()):
    """What an edit of the release for `tag` would do, checked before
    anybody is asked: {tag, notes, files: [{path, name, size, signed}]} or
    {error}. A file is the project's own: a build in dist/, or a file its
    git tree tracks (a screenshot under docs/), inside the project and of a
    kind a release carries."""
    if not tag or not TAG.fullmatch(tag) or ".." in tag:
        return {"error": f"not a tag: {tag or '(none)'}"}
    r = _tree_git(project, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}")
    if r is None or r.returncode:
        return {"error": f"{tag} is not a tag here, so it has no release to edit"}
    if notes is not None:
        notes = str(notes).rstrip()
        if not notes.strip():
            return {"error": "the notes are empty: a release's notes are replaced whole, so say them all"}
        if len(notes) > NOTES_MAX:
            return {"error": f"the notes are {len(notes)} characters; a release takes {NOTES_MAX} at most"}
    attach = [str(a) for a in (attach or [])]
    # `(file:PATH)` shows a committed picture from the repository at the
    # pushed commit that has it, so a screenshot is on the page without
    # being one of the release's downloads, which (asset:NAME) makes it.
    root = (WORKSPACE / project).resolve()
    pinned = {}
    for rel in sorted({m.group(1) for m in FILE_REF.finditer(notes or "")}):
        p = (root / rel).resolve()
        if rel.startswith("/") or not p.is_relative_to(root) or not p.is_file() or not SHOWABLE.search(p.name):
            return {"error": f"file:{rel} is not a picture in {project}"}
        r = _tree_git(project, "log", "-1", "--format=%H", "HEAD", "--", rel)
        sha = r.stdout.strip() if r is not None and not r.returncode else ""
        same = _tree_git(project, "diff", "--quiet", "HEAD", "--", rel)
        if not sha or same is None or same.returncode:
            return {"error": f"file:{rel} is not committed as it is now: commit it and push, so the page "
                             "shows what the history has"}
        on = _tree_git(project, "branch", "-r", "--contains", sha)
        if on is None or on.returncode or not on.stdout.strip():
            return {"error": f"file:{rel} is in commit {sha[:8]}, which is not pushed: push it first, or the "
                             "picture is a broken link on the release"}
        pinned[rel] = sha
    if notes is None and not attach:
        return {"error": "say what changes: --notes FILE, --attach FILE, or both"}
    if len(attach) > ATTACH_MAX:
        return {"error": f"{len(attach)} files; one edit attaches {ATTACH_MAX} at most"}
    files, names = [], set()
    for rel in attach:
        p = (root / rel).resolve()
        if rel.startswith("/") or not p.is_relative_to(root) or not p.is_file():
            return {"error": f"{rel} is not a file in {project}"}
        rel = str(p.relative_to(root))
        if not ATTACHABLE.search(p.name):
            return {"error": f"{p.name} is not a kind of file a release carries here: a build, an image, "
                             "a PDF, a text file or a checksum"}
        in_dist = rel.startswith("dist/")
        if in_dist and "-dirty" in p.name:
            return {"error": f"{p.name} was built from uncommitted changes, so it is not what any tag names"}
        if not in_dist:
            t = _tree_git(project, "ls-files", "--error-unmatch", "--", rel)
            if t is None or t.returncode:
                return {"error": f"{rel} is not committed: a release carries a build in dist/ or a file "
                                 "the project's history has, so what it shows can be found again"}
        size = p.stat().st_size
        if size > ASSET_MAX:
            return {"error": f"{p.name} is {size // 1_000_000} MB, too big to attach"}
        if p.name in names:
            return {"error": f"two files are named {p.name}; a release keeps one of each name"}
        names.add(p.name)
        files.append({"path": rel, "name": p.name, "size": size, "signed": "-signed" in p.name})
    return {"tag": tag, "notes": notes, "files": files, "pinned": pinned}


def _with_assets(notes, urls):
    """`(asset:NAME)` in the notes, the address of the file of that name on
    the release: how a screenshot attached by the same edit is shown."""
    return ASSET_REF.sub(lambda m: f"({urls[m.group(1)]})" if urls.get(m.group(1)) else m.group(0), notes)


def _with_files(notes, pinned, raw):
    """`(file:PATH)` in the notes, the forge's address of that committed
    file at the commit edit_plan() pinned it to."""
    return FILE_REF.sub(lambda m: f"({raw(pinned[m.group(1)], m.group(1))})" if m.group(1) in pinned else m.group(0),
                        notes)


def edit(project, plan):
    """Make the edit edit_plan() checked: {url, notes, attached, replaced,
    skipped, forge} or {error, forge}."""
    tag, notes, files = plan["tag"], plan.get("notes"), plan.get("files") or []
    pinned = plan.get("pinned") or {}
    if cilogs.repo_of(project):
        name = "GitHub"
        if notes is not None:
            notes = _with_files(notes, pinned, lambda sha, rel: f"https://github.com/{cilogs.repo_of(project)}/raw/{sha}/{rel}")
        token = cilogs._token(project)
        if not token:
            return {"error": "the controller has no GitHub token for this project", "forge": name}
        try:
            return _github_edit(project, cilogs.repo_of(project), token, tag, notes, files) | {"forge": name}
        except Refused as e:
            return {"error": str(e), "forge": name}
    at = _remote(project)
    entry = forges.forge_of(at["host"]) if at else None
    if not at or not entry or entry["kind"] not in ("gitea", "gitlab"):
        return {"error": f"{project} is not on GitHub, Gitea or GitLab, so it has no release page to edit",
                "forge": ""}
    name = entry["name"]
    token, scheme = _own_token(project, at["host"])
    if not token:
        return {"error": f"the controller has no {name} token for this project", "forge": name}
    f = _Forge(forges.api_base(entry, at["host"], scheme or ("https" if at["scheme"] == "ssh" else at["scheme"])),
               entry, token)
    web = f"{scheme or ('https' if at['scheme'] in ('ssh', '') else at['scheme'])}://{at['host']}/{at['path']}"
    if notes is not None:
        notes = _with_files(notes, pinned, lambda sha, rel: f"{web}/-/raw/{sha}/{rel}" if entry["kind"] == "gitlab"
                            else f"{web}/raw/commit/{sha}/{rel}")
    try:
        run = _gitlab_edit if entry["kind"] == "gitlab" else _gitea_edit
        return run(f, at, project, tag, notes, files) | {"forge": name}
    except Refused as e:
        return {"error": str(e), "forge": name}


def _said(rel, notes, urls, attached, replaced, skipped):
    if notes is not None:
        missing = sorted({m.group(1) for m in ASSET_REF.finditer(notes)} - {n for n, u in urls.items() if u})
        skipped += [f"the notes name asset:{n}, which is not on the release" for n in missing]
    return {"url": rel, "notes": notes is not None, "attached": attached, "replaced": replaced, "skipped": skipped}


def _ctype(name):
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _github_edit(project, repo, token, tag, notes, files):
    base = f"{API}/repos/{repo}/releases"
    rel = _req("GET", f"{base}/tags/{urllib.parse.quote(tag)}", token)
    if not rel:
        raise Refused(f"there is no release for {tag} on GitHub to edit: bb version release makes one")
    have = {a.get("name"): a for a in rel.get("assets") or []}
    urls = {n: a.get("browser_download_url") or "" for n, a in have.items()}
    attached, replaced, skipped = [], [], []
    for x in files:
        p = WORKSPACE / project / x["path"]
        try:
            if x["name"] in have:
                _req("DELETE", f"{base}/assets/{int(have[x['name']]['id'])}", token)
                replaced.append(x["name"])
            got = _req("POST", f"{UPLOADS}/repos/{repo}/releases/{int(rel['id'])}/assets"
                               f"?name={urllib.parse.quote(x['name'])}", token,
                       data=p.read_bytes(), ctype=_ctype(x["name"]))
            urls[x["name"]] = (got or {}).get("browser_download_url") or ""
            attached.append(x["name"])
        except (Refused, OSError) as e:
            skipped.append(f"{x['name']}: {e}")
    if notes is not None:
        _req("PATCH", f"{base}/{int(rel['id'])}", token, {"body": _with_assets(notes, urls)})
    return _said(rel.get("html_url") or "", notes, urls, attached, replaced, skipped)


def _gitea_edit(f, at, project, tag, notes, files):
    owner, _, repo = at["path"].partition("/")
    base = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/releases"
    rel = f.ask("GET", f"{base}/tags/{urllib.parse.quote(tag)}")
    if not rel:
        raise Refused(f"there is no release for {tag} on {f.entry['name']} to edit: bb version release makes one")
    have = {a.get("name"): a for a in rel.get("assets") or []}
    urls = {n: a.get("browser_download_url") or "" for n, a in have.items()}
    attached, replaced, skipped = [], [], []
    for x in files:
        try:
            if x["name"] in have:
                f.ask("DELETE", f"{base}/{int(rel['id'])}/assets/{int(have[x['name']]['id'])}")
                replaced.append(x["name"])
            data, ctype = _multipart("attachment", x["name"], (WORKSPACE / project / x["path"]).read_bytes())
            got = f.ask("POST", f"{base}/{int(rel['id'])}/assets?name={urllib.parse.quote(x['name'])}",
                        data=data, ctype=ctype)
            urls[x["name"]] = (got or {}).get("browser_download_url") or ""
            attached.append(x["name"])
        except (Refused, OSError) as e:
            skipped.append(f"{x['name']}: {e}")
    if notes is not None:
        f.ask("PATCH", f"{base}/{int(rel['id'])}", {"body": _with_assets(notes, urls)})
    return _said(rel.get("html_url") or "", notes, urls, attached, replaced, skipped)


def _gitlab_edit(f, at, project, tag, notes, files):
    pid = urllib.parse.quote(at["path"], safe="")
    t = urllib.parse.quote(tag)
    rel = f.ask("GET", f"/projects/{pid}/releases/{t}")
    if not rel:
        raise Refused(f"there is no release for {tag} on GitLab to edit: bb version release makes one")
    links = {x.get("name"): x for x in ((rel.get("assets") or {}).get("links") or [])}
    urls = {n: x.get("url") or "" for n, x in links.items()}
    pkg = re.sub(r"[^A-Za-z0-9._-]", "-", project) or "builds"
    ver = re.sub(r"[^A-Za-z0-9._+-]", "-", re.sub(r"^(?:.*-)?v(?=\d)", "", tag)) or "0"
    attached, replaced, skipped = [], [], []
    for x in files:
        path = f"/projects/{pid}/packages/generic/{pkg}/{ver}/{urllib.parse.quote(x['name'])}"
        try:
            if x["name"] in links:
                f.ask("DELETE", f"/projects/{pid}/releases/{t}/assets/links/{int(links[x['name']]['id'])}")
                replaced.append(x["name"])
            f.ask("PUT", path, data=(WORKSPACE / project / x["path"]).read_bytes(), ctype="application/octet-stream")
            f.ask("POST", f"/projects/{pid}/releases/{t}/assets/links",
                  {"name": x["name"], "url": f.base + path,
                   "link_type": "image" if re.search(r"\.(png|jpe?g|gif|webp)$", x["name"], re.I) else "package"})
            urls[x["name"]] = f.base + path
            attached.append(x["name"])
        except (Refused, OSError) as e:
            skipped.append(f"{x['name']}: {e}")
    if notes is not None:
        f.ask("PUT", f"/projects/{pid}/releases/{t}", {"description": _with_assets(notes, urls)})
    web = f"{f.base.split('/api/')[0]}/{at['path']}/-/releases/{t}"
    return _said(((rel.get("_links") or {}).get("self") or web), notes, urls, attached, replaced, skipped)


def edit_said(r):
    """One line for what an edit did, for the session and the outcome."""
    if r.get("error"):
        return f"no edit on {r.get('forge') or 'the forge'}: {r['error']}"
    parts = (["the notes replaced"] if r.get("notes") else []) + (
        [f"attached {', '.join(r['attached'])}"] if r.get("attached") else []) + (
        [f"replacing {', '.join(r['replaced'])}"] if r.get("replaced") else [])
    return (f"edited on {r.get('forge')}: {'; '.join(parts) or 'nothing changed'}"
            + (f"; not done: {'; '.join(r['skipped'])}" if r.get("skipped") else "") + f"; {r.get('url')}")


# ---- taking a file off a published release ---------------------------------------
# Its own ask, never part of an edit: a removal is the one change here that
# takes something away from the people downloading, so it is asked as itself
# (the operator, 5 Oct). The release is read first, so the ask names files
# that are really there, with their sizes.

def _handle(project):
    """(kind, name, ctx) for the project's forge, or raises Refused: what
    the listing and the deletion below need, by forge."""
    if cilogs.repo_of(project):
        token = cilogs._token(project)
        if not token:
            raise Refused("the controller has no GitHub token for this project")
        return "github", "GitHub", (cilogs.repo_of(project), token)
    at = _remote(project)
    entry = forges.forge_of(at["host"]) if at else None
    if not at or not entry or entry["kind"] not in ("gitea", "gitlab"):
        raise Refused(f"{project} is not on GitHub, Gitea or GitLab, so it has no release page")
    token, scheme = _own_token(project, at["host"])
    if not token:
        raise Refused(f"the controller has no {entry['name']} token for this project")
    f = _Forge(forges.api_base(entry, at["host"], scheme or ("https" if at["scheme"] == "ssh" else at["scheme"])),
               entry, token)
    return entry["kind"], entry["name"], (f, at)


def _files_on(kind, name, ctx, tag):
    """(release url, {file name: (id, size)}) of the release for `tag`."""
    t = urllib.parse.quote(tag)
    if kind == "github":
        repo, token = ctx
        rel = _req("GET", f"{API}/repos/{repo}/releases/tags/{t}", token)
        if not rel:
            raise Refused(f"there is no release for {tag} on GitHub")
        return rel.get("html_url") or "", {a.get("name"): (int(a["id"]), int(a.get("size") or 0), int(rel["id"]))
                                           for a in rel.get("assets") or []}
    f, at = ctx
    if kind == "gitlab":
        pid = urllib.parse.quote(at["path"], safe="")
        rel = f.ask("GET", f"/projects/{pid}/releases/{t}")
        if not rel:
            raise Refused(f"there is no release for {tag} on GitLab")
        return ((rel.get("_links") or {}).get("self") or "",
                {x.get("name"): (int(x["id"]), 0, 0) for x in ((rel.get("assets") or {}).get("links") or [])})
    owner, _, repo = at["path"].partition("/")
    rel = f.ask("GET", f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/releases/tags/{t}")
    if not rel:
        raise Refused(f"there is no release for {tag} on {name}")
    return rel.get("html_url") or "", {a.get("name"): (int(a["id"]), int(a.get("size") or 0), int(rel["id"]))
                                       for a in rel.get("assets") or []}


def remove_plan(project, tag, names):
    """The files a removal would take off the release for `tag`, read from
    the forge before anybody is asked: {tag, forge, files: [{name, size}]}
    or {error}."""
    if not tag or not TAG.fullmatch(tag) or ".." in tag:
        return {"error": f"not a tag: {tag or '(none)'}"}
    names = [str(n) for n in names or []]
    if not names:
        return {"error": "say which files come off: --remove NAME, once for each"}
    if len(names) > ATTACH_MAX or len(set(names)) != len(names):
        return {"error": f"name each file once, {ATTACH_MAX} at most"}
    try:
        kind, name, ctx = _handle(project)
        _url, have = _files_on(kind, name, ctx, tag)
    except Refused as e:
        return {"error": str(e)}
    missing = [n for n in names if n not in have]
    if missing:
        return {"error": f"the {tag} release on {name} has no {', '.join(missing)}; it has "
                         + (", ".join(sorted(have)) or "no files")}
    return {"tag": tag, "forge": name, "files": [{"name": n, "size": have[n][1]} for n in names]}


def remove(project, plan):
    """Take the planned files off the release, each looked up again by name
    (an id read at the ask may be stale by the Allow): {url, removed,
    skipped, forge} or {error, forge}."""
    try:
        kind, name, ctx = _handle(project)
        url, have = _files_on(kind, name, ctx, plan["tag"])
    except Refused as e:
        return {"error": str(e), "forge": ""}
    removed, skipped = [], []
    for x in plan.get("files") or []:
        got = have.get(x["name"])
        if not got:
            skipped.append(f"{x['name']} was already gone")
            continue
        try:
            if kind == "github":
                repo, token = ctx
                _req("DELETE", f"{API}/repos/{repo}/releases/assets/{got[0]}", token)
            elif kind == "gitlab":
                f, at = ctx
                pid = urllib.parse.quote(at["path"], safe="")
                f.ask("DELETE", f"/projects/{pid}/releases/{urllib.parse.quote(plan['tag'])}/assets/links/{got[0]}")
            else:
                f, at = ctx
                owner, _, repo = at["path"].partition("/")
                f.ask("DELETE", f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}/releases/"
                                f"{got[2]}/assets/{got[0]}")
            removed.append(x["name"])
        except Refused as e:
            skipped.append(f"{x['name']}: {e}")
    return {"url": url, "removed": removed, "skipped": skipped, "forge": name}


def remove_said(r):
    if r.get("error"):
        return f"nothing removed: {r['error']}"
    return (f"removed from the release on {r.get('forge')}: {', '.join(r.get('removed') or []) or 'nothing'}"
            + (f"; not done: {'; '.join(r['skipped'])}" if r.get("skipped") else "") + f"; {r.get('url')}")
