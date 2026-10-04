"""The forge's release beside the tag (R123, the operator 4 Oct): when Release
has pushed a version's tag and the project is on GitHub with a token that
can write there, a GitHub release for that tag, titled with the version,
its notes the changelog's section for it, its builds attached.

Read and written with the project's own token, else the shared PAT (the
same one cilogs.py reads runs with). Only api.github.com and
uploads.github.com are ever asked, and only on the paths below. A release
that exists already for the tag is left as it is and pointed at: a second
press makes nothing twice. What was made, or why nothing was, is kept per
project and tag, so the version row can link to it or say the reason.

Builds are matched on the released commit: a file in dist/ whose name
carries that commit's short id (every build is named so) and is not a
dirty one. Signed ones are what a release carries when there are any; an
unsigned or debug build only where nothing signed was built.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import changelog
import cilogs

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


def _keep(project, tag, url, error=""):
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault(project, {})[tag] = {"url": url, "error": error}
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
    """The GitHub release for `tag`, made if it is not there:
    {url, made, assets, skipped} or {error}."""
    repo = cilogs.repo_of(project)
    if not repo:
        return {"error": f"{project} is not on GitHub, so the tag is its release"}
    token = cilogs._token(project)
    if not token:
        why = "the controller has no GitHub token for this project, so the tag is its release"
        _keep(project, tag, "", why)
        return {"error": why}
    base = f"{API}/repos/{repo}/releases"
    try:
        have = _req("GET", f"{base}/tags/{urllib.parse.quote(tag)}", token)
        if have:
            _keep(project, tag, have.get("html_url") or "")
            return {"url": have.get("html_url") or "", "made": False, "assets": [], "skipped": []}
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
        return {"url": rel.get("html_url") or "", "made": True, "assets": up, "skipped": skipped}
    except Refused as e:
        _keep(project, tag, "", str(e))
        return {"error": str(e)}
