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

A release that exists already for the tag is left as it is and pointed at:
a second press makes nothing twice. What was made, or why nothing was, is
kept per project and tag, so the version row can link to it or say the
reason.

Builds are matched on the released commit: a file in dist/ whose name
carries that commit's short id (every build is named so) and is not a
dirty one. Signed ones are what a release carries when there are any; an
unsigned or debug build only where nothing signed was built.
"""
import json
import os
import re
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
    file has none: its categories as headings and its entries as a list."""
    text = changelog.read(where) or ""
    for sec in changelog.sections(text):
        title = sec.get("title") or ""
        if title == version or title.startswith(version + ":") or title.startswith(version + " "):
            out, cat = [], None
            for e in sec.get("entries") or []:
                if e.get("cat") != cat:
                    cat = e.get("cat")
                    if cat:
                        out.append(f"\n### {cat}\n")
                out.append(f"- {e.get('text', '')}")
            return "\n".join(out).strip()
    return ""


def assets(project, sha):
    """The builds of commit `sha` in the project's dist/, signed ones when
    there are any: [Path], newest first."""
    d = WORKSPACE / project / "dist"
    if not sha or not d.is_dir():
        return []
    files = [f for f in d.iterdir()
             if f.is_file() and sha in f.name and "-dirty" not in f.name and SHIPS.search(f.name)]
    signed = [f for f in files if "-signed" in f.name]
    if signed:
        files = signed
    else:
        real = [f for f in files if "-debug" not in f.name]
        files = real or files
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


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
    body = notes(where, version) or f"{project} {version}"
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
        body = notes(where, version) or f"{project} {version}"
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
    try:
        line = (STATE / "gitcreds" / project).read_text().strip().splitlines()[0]
    except (OSError, IndexError):
        return "", ""
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
    rel = f.ask("POST", base, {"tag_name": tag, "name": title, "body": body,
                               "draft": False, "prerelease": False})
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
