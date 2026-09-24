"""Which git host a project's remote is on, and what that host can be asked.

Everything BuilderBot does with a remote is plain git except three things, and
those three are the whole of this file:

  * **what an address may look like.** `git clone` accepts transports a web
    form must never reach (`ext::` runs a command), so a URL typed into the
    dashboard is matched against the shapes below and refused otherwise. That
    check used to be "is it github.com", which is why nothing else could be
    linked.
  * **whether a token is real**, asked before the network work starts, so a
    wrong paste fails in the dialog rather than half-way through a job.
  * **creating the repository** when it does not exist yet. Only ever an
    empty private one, and only on a host whose API this knows.

Everything else (proving a repository is empty, pushing, fetching) is git,
and git does not care whose server answers.

**A forge is derived, never stored.** The host in a project's origin URL says
which of these it is, so there is no second record to drift out of step with
the remote, and rewriting the remote by hand from a shell moves the answer
with it. `forge_of()` is that lookup; an address on a host nobody recognises
is the `git` entry, which promises nothing beyond git itself.

The API dialects are three, not seven. Gitea's HTTP API is deliberately
GitHub-shaped, so Forgejo (its fork) and Codeberg (which runs Forgejo) are
the same code; GitLab's is its own. Only GitHub's path is exercised by the
test suite here (there is no Gitea to point it at), so the other two are
written to each project's documented API and fail with the server's own
message rather than a traceback when they are wrong.
"""

import json
import re
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

run = None
STATE = None
write_json = None


def configure(*, run, state=None, write_json=None):      # noqa: A002 - injected
    globals().update(run=run,
                     STATE=None if state is None else Path(state),
                     write_json=write_json)


# ---------------------------------------------------------------------------
# the catalog
#
# `host` is the default, and `fixed` says whether the operator may replace it:
# github.com is one server, Gitea is whichever one they run. `kind` is the API
# dialect, "" for a host this can only reach with git. `nested` allows the
# owner half to carry slashes, which is GitLab's subgroups and nobody else's.
# `user` is the username half of the stored credential when the host cannot be
# asked for the real one: git's credential store is a URL, so a token has to
# go in beside SOME name, and each of these publishes the one it wants.

# Whether unvetted hosts may be offered, from the controller's settings
# (server.py sets it); None reads as no.
unvetted_ok = None

# `vetted` is the evidence an entry has been proven against the real thing,
# the date and what did it, or "" for one written to its documented API and
# never run. With the setting off, only vetted hosts are offered and a link
# or clone naming another is refused; on, the rest are offered tagged dev.
FORGES = (
    {"id": "github", "name": "GitHub", "host": "github.com", "fixed": True,
     "vetted": "in daily use: every project here that pushes, and create.mjs against the harness",
     "user": "x-access-token",
     "kind": "github", "nested": False,
     "token": re.compile(r"[A-Za-z0-9_]{20,255}"),
     "hint": "ghp_… or github_pat_…",
     "about": "Repositories are created for you when the address names one "
              "that does not exist yet."},
    {"id": "gitea", "name": "Gitea", "host": "", "fixed": False,
     "vetted": "2026-09-15: lab-forge.mjs against Gitea 1.24.7, and a runner registered from bb-dev-sandbox",
     "user": "oauth2",
     "kind": "gitea", "nested": False,
     "token": None, "hint": "a Gitea access token",
     # Measured on Gitea 1.24: creating under an organisation needs
     # write:organization, and under the account itself write:user, which
     # is not implied by the repository scope.
     "about": "Your own server. Give it the address you reach Gitea on, and "
              "a token with the repository scope, plus organization to create "
              "a repository under an organisation and user to create one under "
              "your own account."},
    {"id": "forgejo", "name": "Forgejo", "host": "", "fixed": False,
     "vetted": "",
     "user": "oauth2",
     "kind": "gitea", "nested": False,
     "token": None, "hint": "a Forgejo access token",
     "about": "Your own server. Forgejo answers Gitea's API, so this is the "
              "same conversation with a different name on it: a token with the "
              "repository scope, plus organization or user to create a "
              "repository under either."},
    {"id": "codeberg", "name": "Codeberg", "host": "codeberg.org", "fixed": True,
     "vetted": "",
     "user": "oauth2",
     "kind": "gitea", "nested": False,
     "token": None, "hint": "a Codeberg access token",
     "about": "Codeberg runs Forgejo, so it answers the same API."},
    {"id": "gitlab", "name": "GitLab", "host": "gitlab.com", "fixed": False,
     "vetted": "",
     "user": "oauth2",
     "kind": "gitlab", "nested": True,
     "token": None, "hint": "glpat-…",
     "about": "gitlab.com, or your own if you replace the host. Subgroups "
              "are allowed in the path, which no other host here permits."},
    {"id": "bitbucket", "name": "Bitbucket", "host": "bitbucket.org", "fixed": True,
     "vetted": "",
     # The username Bitbucket pairs a repository or workspace ACCESS TOKEN
     # with. An app password is paired with the account's own username
     # instead, which nothing here asks for, so the hint names the token.
     "user": "x-token-auth",
     "kind": "", "nested": False,
     "token": None, "hint": "a repository access token",
     "about": "Reached with git alone, so the repository has to exist "
              "already: create it empty on Bitbucket first, and give it a "
              "repository access token rather than an app password, which "
              "would need your username beside it."},
    {"id": "git", "name": "Another git host", "host": "", "fixed": False,
     "vetted": "plain git, no host API: the same clone and push the vetted hosts use",
     "user": "oauth2",
     "kind": "", "nested": True,
     "token": None, "hint": "an access token, if the host wants one",
     "about": "Any git server over https or ssh. Nothing is asked of it but "
              "git, so the repository has to exist already and be empty."},
)

BY_ID = {f["id"]: f for f in FORGES}
# The default entry for an address on a host none of the named ones claim.
OTHER = BY_ID["git"]


def get(fid):
    return BY_ID.get(fid or "")


def catalog():
    """What the link dialog draws: everything but the compiled regex, and
    only what may be offered; an unvetted host that may be carries `dev`.

    ALPHABETICAL, because a list of choices with no order anybody can name is
    a list you read twice. `git` is the one exception and is last: it is not a
    host, it is "none of the above", and a catch-all sorted under A would be
    read as a product called Another.
    """
    rows = [{"id": f["id"], "name": f["name"], "host": f["host"],
             "fixed": f["fixed"], "hint": f["hint"], "about": f["about"],
             "nested": f["nested"], "creates": bool(f["kind"]),
             "dev": not f.get("vetted")}
            for f in FORGES if allowed(f)]
    return sorted(rows, key=lambda f: (f["id"] == "git", f["name"].lower()))


def allowed(f):
    """May this host be offered and linked: vetted, or unvetted with the
    setting on. A project already linked to an unvetted host keeps
    working either way: this gates what is offered, not what exists."""
    return bool(f.get("vetted")) or bool(unvetted_ok and unvetted_ok())


def not_offered(f):
    """The sentence a refusal carries for an unvetted host."""
    return (f"{f['name']} is dev, not yet vetted, so it is not offered here: "
            "Debug settings on the Settings tab, 'Offer dev features' puts it back, tagged dev")


def slug(host):
    """A host as one ssh-config-safe word, for naming a deploy-key alias."""
    return re.sub(r"[^A-Za-z0-9]+", "-", (host or "").lower()).strip("-")


# What the operator has said their own servers run. A host is not a name: a
# Gitea at git.example.com is indistinguishable from a Forgejo or a bare git
# daemon until somebody says which, and only the person who set it up knows.
# So they say it once, on the first link, and it is remembered PER HOST rather
# than per project: the second project on the same server asks nobody.
#
# The file is a map and nothing else. Every value is checked against the
# catalog on the way out, so an edited file cannot name a dialect this does
# not have.
HOSTS = "forge-hosts.json"


def known():
    if STATE is None:
        return {}
    try:
        with open(STATE / HOSTS) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def remember(host, fid):
    """Note that this host runs this forge. Ignored for a host the catalog
    already names, which cannot be anything else."""
    h = (host or "").lower()
    entry = BY_ID.get(fid or "")
    if not h or entry is None or entry["id"] == OTHER["id"]:
        return
    if any(f["host"] and f["host"].lower() == h.split(":")[0] for f in FORGES):
        return
    d = known()
    if d.get(h) == entry["id"] or write_json is None or STATE is None:
        return
    d[h] = entry["id"]
    write_json(STATE / HOSTS, d)


def forge_of(host):
    """The catalog entry serving this host, falling back to the generic one.

    Read from the host rather than from a field on the project, so a remote
    rewritten from a shell is described correctly on the next poll rather than
    by whatever was true when it was linked. The public hosts are the
    catalog's; a private one is whatever the operator said it was.
    """
    h = (host or "").lower()
    if not h:
        return OTHER
    for f in FORGES:
        if f["host"] and f["host"].lower() == h.split(":")[0]:
            return f
    # With the port, then without it: a Gitea linked over https carries its
    # port in the host and is remembered that way, and the same server
    # reached over ssh afterwards names the host alone.
    told = known().get(h)
    if not told:
        bare = h.split(":")[0]
        told = next((v for k, v in known().items() if k.split(":")[0] == bare), "")
    if told and told in BY_ID:
        return BY_ID[told]
    # Nobody has said what this one runs. `git` is the honest answer: git, and
    # nothing assumed past it.
    return OTHER


# ---------------------------------------------------------------------------
# addresses
#
# Three shapes and no others, because this is what a browser form hands to
# `git`. The path is segments of the project-name charset, so a URL cannot
# carry `..`, a space, or an option-looking leading dash into an argv.

_SEG = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_HOST = r"[A-Za-z0-9][A-Za-z0-9.-]*"
_PORT = r"(?::[0-9]{1,5})?"
_PATH = rf"{_SEG}(?:/{_SEG}){{1,7}}"

# The port travels WITH the host: a self-hosted Gitea on :3000 is a different
# server from one on :443, and both the API root and the https spelling of the
# remote have to carry it. Everything asking which forge a host is strips it.
URL = re.compile(
    rf"(?:(?P<s1>https?)://(?P<h1>{_HOST}{_PORT})/(?P<p1>{_PATH})"
    rf"|ssh://(?:[^@/]+@)?(?P<h2>{_HOST}{_PORT})/(?P<p2>{_PATH})"
    rf"|(?:[^@:/]+@)?(?P<h3>{_HOST}):(?P<p3>{_PATH}))"
    r"(?:\.git)?/?")


def parse(url):
    """{"scheme", "host", "path"} for an address this accepts, else None.

    `scheme` is "ssh" for both ssh spellings, because what decides whether git
    consults a credential helper is ssh-or-not and not which of the two ways
    of writing it was used.
    """
    m = URL.fullmatch((url or "").strip())
    if not m:
        return None
    scheme = m.group("s1") or "ssh"
    host = m.group("h1") or m.group("h2") or m.group("h3")
    path = m.group("p1") or m.group("p2") or m.group("p3")
    return {"scheme": scheme, "host": host, "path": path.removesuffix(".git")}


def path_ok(entry, path):
    """Whether a path's depth suits this forge. "" when it does, else why not.

    Two segments everywhere; more only on GitLab, whose subgroups are a real
    part of an address rather than a typo. Refusing depth elsewhere catches
    the common paste of a URL with a branch or a file on the end of it.
    """
    n = len([b for b in path.split("/") if b])
    if n < 2:
        return "an address needs an owner and a repository: owner/repo"
    if n > 2 and not entry["nested"]:
        return (f"{entry['name']} addresses are owner/repo, and "
                f"{path} has {n} parts, so this is not a repository address")
    return ""


def host_of(url):
    """The real host behind an address, resolving a bb- ssh alias to it.

    A deploy-key setup addresses the forge through a `~/.ssh/config` Host
    alias, so the hostname in the URL is `bb-something` and the server it
    stands for is only in that file. `ssh -G` reads it with no network. The
    alias is charset-checked by the parse above before it reaches an argv.
    """
    got = parse(url)
    if not got:
        return ""
    host = got["host"]
    if got["scheme"] != "ssh" or "." in host or ":" in host:
        return host
    r = run(["ssh", "-G", host], timeout=10)
    if r["code"] != 0:
        return host
    for line in r["out"].splitlines():
        if line.strip().lower().startswith("hostname "):
            return line.split(None, 1)[1].strip()
    return host


def token_ok(entry, token):
    """"" when this could be an access token for that forge, else why not.

    GitHub's rule is the strict one and stays: its tokens have never carried a
    dash or a dot, so a pasted URL or a copied username is caught here rather
    than by an API round trip. Elsewhere the shape varies too much between
    servers and versions to be worth guessing at, so the check is only that it
    could be a credential at all, and the host's own answer is the real test.
    """
    pat = entry["token"]
    if pat is not None:
        return "" if pat.fullmatch(token) else f"that is not a {entry['name']} token"
    return ("" if re.fullmatch(r"[A-Za-z0-9_.~+/=-]{8,512}", token)
            else "that does not look like an access token")


# ---------------------------------------------------------------------------
# the API, for the two things git cannot answer

def api_base(entry, host, scheme="https"):
    """The API root for this forge on this host, or "" when it has none.

    The scheme is the remote's, not a constant: a Gitea brought up from its own
    compose file serves plain http on a LAN, and asking it over https is a
    connection refused reported as a bad token. github.com is the exception in
    both directions (a separate hostname, always https), with `/api/v3` under
    the host itself for GitHub Enterprise Server.
    """
    if not entry["kind"]:
        return ""
    if entry["kind"] == "github" and host.lower() == "github.com":
        return "https://api.github.com"
    if scheme not in ("https", "http"):
        scheme = "https"
    tail = {"github": "v3", "gitlab": "v4"}.get(entry["kind"], "v1")
    return f"{scheme}://{host}/api/{tail}"


def _auth(kind, token):
    if kind == "gitlab":
        return {"PRIVATE-TOKEN": token}
    if kind == "gitea":
        return {"Authorization": f"token {token}"}
    return {"Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json"}


def _ask(url, kind, token, data=None):
    """One API call. (parsed body, "") or (None, why not).

    Every caller wants the same three outcomes (it worked, the host said no
    and here is its sentence, the host could not be reached), so they are
    resolved once here rather than in three copies of the same try block.
    """
    headers = {"User-Agent": "BuilderBot", **_auth(kind, token)}
    if data is not None:
        headers["Content-Type"] = "application/json"
    # api_base() built `url` from a host that matched URL and a scheme this
    # module chose, so nothing but http(s) reaches here; checked anyway,
    # since urlopen would open file:// as readily.
    if not url.lower().startswith(("https://", "http://")):
        return {}, f"not a web address: {url[:60]}"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read(20000)
            return (json.loads(body) if body.strip() else {}), ""
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read(20000)) or {}
            why = j.get("message") or j.get("error") or j.get("error_description") or ""
            if not why and isinstance(j.get("errors"), list):
                why = "; ".join(str(x) for x in j["errors"])[:200]
        except (ValueError, OSError):
            why = ""
        return None, why or f"HTTP {e.code}"
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, f"could not be reached: {e}"


def whoami(entry, host, token, scheme="https"):
    """The account a token belongs to, or "", including when the host has no
    API to ask, which is not the same as a refusal and is why link() proves
    the credential with `git ls-remote` regardless."""
    base = api_base(entry, host, scheme)
    if not base:
        return ""
    j, _why = _ask(f"{base}/user", entry["kind"], token)
    if not isinstance(j, dict):
        return ""
    return str(j.get("login") or j.get("username") or j.get("name") or "")


def can_create(entry):
    return bool(entry["kind"])


def cred_user(entry, host, token, scheme="https"):
    """The username to store a token under.

    Asked of the host when it has an API, because the answer is always right
    and the request has to be made anyway to know the token is real. The
    catalog's own name is the fallback, and it is what every host here accepts
    when it cannot be asked: the password is the credential and the username
    is a formality, except on GitLab, where `oauth2` is the formality it
    insists on.
    """
    return whoami(entry, host, token, scheme) or entry["user"]


def create_repo(entry, host, token, path, scheme="https", user=""):
    """Make an empty private repository. "" on success, else why not.

    Reached only when the host has already answered "not found" for it, which
    is the one answer that proves there is nothing there to harm. `user` is
    the account the token belongs to, when the host said: a repository can
    be made under an organisation or under that account, and nowhere else.
    """
    base = api_base(entry, host, scheme)
    if not base:
        return (f"{entry['name']} is reached with git alone here, so the "
                f"repository has to exist already: create {path} empty on it "
                f"and link again")
    owner, _, repo = path.rpartition("/")
    if entry["kind"] == "gitlab":
        return _create_gitlab(base, entry["kind"], token, owner, repo, entry)
    # GitHub and Gitea both take {name, private} and both keep an
    # organisation's repositories on a path of their own, with the account's
    # as the fallback when the owner turns out to be a person.
    body = json.dumps({"name": repo, "private": True,
                       "auto_init": False}).encode()
    j, why = _ask(f"{base}/orgs/{urllib.parse.quote(owner)}/repos",
                  entry["kind"], token, body)
    if j is not None:
        return ""
    first = why
    # The account's own path is only right when the owner IS the account:
    # falling back to it for anybody else made owner/repo under the token's
    # user, and the push to the address that was asked for then failed on
    # a repository that was never there.
    if user and owner.lower() != user.lower():
        return (f"{entry['name']} would not create {path}: {owner} is not an "
                f"organisation this token can create in ({first}), and the "
                f"token is {user}'s, so it cannot make one under {owner}")
    j, why = _ask(f"{base}/user/repos", entry["kind"], token, body)
    if j is not None:
        return ""
    return f"{entry['name']} would not create {path}: {why or first}"


def _create_gitlab(base, kind, token, owner, repo, entry):
    """GitLab names the owner by id rather than by path, so this is two calls:
    resolve the namespace, then create in it."""
    j, why = _ask(f"{base}/namespaces/{urllib.parse.quote(owner, safe='')}",
                  kind, token)
    if not isinstance(j, dict) or not j.get("id"):
        return f"GitLab does not know the namespace {owner}: {why or 'not found'}"
    body = json.dumps({"name": repo, "path": repo, "namespace_id": j["id"],
                       "visibility": "private", "initialize_with_readme": False}).encode()
    made, why = _ask(f"{base}/projects", kind, token, body)
    if made is not None:
        return ""
    return f"{entry['name']} would not create {owner}/{repo}: {why}"
