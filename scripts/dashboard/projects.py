#!/usr/bin/env python3
"""Everything behind New project, and linking one to a git host.

Making a project is two operations that look alike and behave nothing alike.
`git init` is local, bounded, and done before a spinner would render. A clone
or a first push is a network operation that can take minutes, and until this
file existed it ran inside the HTTP request that asked for it. Close the tab,
sleep the phone, walk out of wifi range, and the work carried on with nobody
left to report to; the page's own error text said as much ("check the Projects
card before trying again"), which is a note explaining a design rather than a
bug. Every other long job here (installing an SDK, removing one) is a
background worker with a row on screen and a way to stop it. This makes these
two the same.

The line is drawn at the network, not at the button: `init` stays synchronous,
because a busy row that appears and vanishes within one frame is worse than no
row at all.

What is *checked* stays synchronous either way. A name that is not a name, a
directory that already exists, a project that is not a repo, a repo that
already has a remote: those are instant, and they belong in the dialog the
operator is still looking at, not in a job they have to go and read.

The server imports this and hands it the helpers it needs; nothing here reaches
back into the server.
"""
import contextlib
import json
import os
import re
import secrets
import shutil
import signal
import tarfile
import tempfile
import threading
import time
import urllib.parse
import zipfile
from pathlib import Path

from names import claude_session

# Which git host a remote is on, and the two things a host can be asked that
# git cannot: whether a token is real, and creating an empty repository. A
# peer library rather than an injection: it holds no server state, and the
# alternative was this module carrying a second copy of the URL rules.
import forges
import registry

# A personal access token belonging to ONE project.
#
# What this replaced is a single GIT_PAT in the container's environment, shared
# by every repo and every session: a token minted to reach one private repo
# then reached every repo it was scoped to, from anywhere. That variable is
# gone; this is the only way in. Written in git's own credential-store format
# under /config, named for the project, and referenced from that repository's
# .git/config and nowhere else.
#
# The honest limit, said here because it is said in the UI too: this is not
# shielded the way the ssh keys are. Those are served by a root-owned agent and
# cannot be read; this is a 0600 file owned by the same user a shell runs as.
TOKEN_RE = re.compile(r"[A-Za-z0-9_.-]{8,255}")


def _creds_dir():
    d = STATE / "gitcreds"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    return d


def write_token(project, token, host, scheme="https", user=""):
    """Store one project's token for one host, and return the helper that
    reads it.

    git's credential store is a list of URLs and it matches on the host, so a
    line naming the wrong one is a file git reads and then ignores: a token
    that appears to be stored and authenticates nothing. The host is therefore
    required rather than defaulted; the username is a formality every host
    here accepts, and forges.cred_user picks the one this host wants.
    """
    f = _creds_dir() / project
    # http is a real answer for a Gitea on somebody's own LAN, and git matches
    # the scheme as well as the host: a line written as https would be
    # ignored on an http remote, which is the same silent nothing as the wrong
    # host. link() is where the plaintext hop is said out loud.
    if scheme not in ("https", "http"):
        scheme = "https"
    # Percent-encoded, the way git's own credential-store writes a line: it
    # decodes on the way back, and a token carrying a / or an @ written raw
    # would be read as part of the host, matching nothing.
    q = lambda x: urllib.parse.quote(x, safe="")  # noqa: E731
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(f"{scheme}://{q(user or 'oauth2')}:{q(token)}@{host}\n")
    return f"store --file={f}"


def token_target(project):
    """The scheme and host a project's stored token was written for, or
    None: what an https remote has to be spelled with to use it."""
    f = STATE / "gitcreds" / project
    try:
        line = f.read_text().strip().splitlines()[0]
    except (OSError, IndexError):
        return None
    m = re.match(r"(https?)://[^@/]*@([A-Za-z0-9.:-]+)$", line)
    return {"scheme": m.group(1), "host": m.group(2)} if m else None


def token_helper(project):
    """The helper line for a project that has a token, or "" if it has none."""
    f = STATE / "gitcreds" / project
    return f"store --file={f}" if f.is_file() else ""


def forget_token(project):
    with contextlib.suppress(OSError):
        (STATE / "gitcreds" / project).unlink()


def unscope(dest):
    """Take the credential helper back off a repository.

    The other half of forgetting a token: `store --file=...` naming a file that
    is no longer there does not fail loudly, it finds no credentials and lets
    git fall through to asking, which on a headless box is a push that hangs
    or fails with a message about a terminal. Reset it and https simply has no
    credential, which is the truth being recorded.
    """
    run(["git", "-C", str(dest), "config", "--local",
         "--replace-all", "credential.helper", ""], timeout=15)


def _scope_to_token(dest, helper):
    """Point one repository at one token, and at nothing else.

    The empty value first is git's own way of resetting a multi-valued key:
    without it the helper `gh auth setup-git` installs globally answers first
    and the repository quietly authenticates with the shared PAT instead,
    which is the arrangement this exists to get away from.
    """
    run(["git", "-C", str(dest), "config", "--local",
         "--replace-all", "credential.helper", ""], timeout=15)
    run(["git", "-C", str(dest), "config", "--local",
         "--add", "credential.helper", helper], timeout=15)


def keyname_ok(req):
    """Whether a deploy key was picked, read here because the push check runs
    before the key is resolved, and resolving it first would put a network
    call ahead of a refusal that needs none."""
    return bool(_field(req, "key").strip())


def sanitize_name(raw):
    """A typed name, as the directory it will become: GitHub's own behavior.

    GitHub does not refuse "My New App": it replaces what it cannot use with a
    dash and shows you what you are about to get. This refused it, which is
    friction for nothing: the operator retypes what the machine had already
    worked out. So the same rule, applied here, and the name a repository
    would have had is the name the directory gets.

    Three departures, all because this ends up as a directory rather than a
    repository:

    - a leading dot, dash or underscore is dropped. GitHub is happy with
      `.github`; the project scan skips anything starting with a dot, so such
      a directory would be created and then never appear.
    - runs of dashes collapse. GitHub leaves `my---app` alone; nobody means it.
    - trailing dashes go, which are always an artifact of the replacement
      rather than anything typed on purpose.

    Empty is returned as empty and refused by the caller: there is a
    difference between "that is not a name" and a name this quietly invented.
    """
    s = re.sub(r"[^A-Za-z0-9._-]", "-", (raw or "").strip())
    s = re.sub(r"-{2,}", "-", s)
    return s.lstrip("._-").rstrip("-")[:100]


def _field(req, key):
    """One string field out of a request body. See server.field, which is the
    same rule at the same boundary. JSON carries types, and a name that
    arrives as a number reaches .strip() and takes the handler with it."""
    v = req.get(key)
    return v if isinstance(v, str) else ""


# The server's. Injected rather than imported, because importing the server
# from a module the server imports is a circle. The same shape as toolchains.py.
run = None
WORKSPACE = None
agent_keys = None
gh_authed = None
ensure_deploy_alias = None
PROJECT_NAME = None
# Renaming's own share of the injection: where the state and the home volume
# live.
STATE = None
HOME = None
write_json = None
after_create = None
# (name, value, env) -> version.init's answer: the first VERSION, committed,
# for a project born with a starting version (the operator, 25 Sep).
first_version = None
# What create_from_dialog() and the pins need from the server: the one lock
# every read-edit-write of the server's state files takes, an account taking
# a project on (users.take_on), and a project's settings written the way the
# settings dialog writes them (prefs.set_prefs).
lock = None
take_on = None
set_prefs = None
# ...and a lock's, which ends the project's own Claude session: this
# container's tmux sessions (the server's tmux_sessions).
live_sessions = None
# brief.write: the brief a new project is made with, kept in its tree for the
# first Claude session rather than written into CLAUDE.md.
brief_writer = None


def configure(*, run, workspace, agent_keys, gh_authed, ensure_deploy_alias,
              project_name,
              state, home, write_json, after_create=None):
    """Hand over the server's helpers. `after_create(name)` is called once
    a project's tree is in place (a fresh repo, a clone, an unpacked
    archive): the map build that mapping.py starts in the background."""
    globals().update(
        run=run, WORKSPACE=Path(workspace), agent_keys=agent_keys,
        gh_authed=gh_authed, ensure_deploy_alias=ensure_deploy_alias,
        PROJECT_NAME=project_name,
        STATE=Path(state), HOME=Path(home), write_json=write_json,
        after_create=after_create)
    # The peer library takes the same runner: it shells out to `ssh -G` to
    # resolve a deploy-key alias, and to nothing else.
    forges.configure(run=run, state=state, write_json=write_json)



def rename(req):
    """Rename a project: the name it is shown under, and with it, in the same
    dialog, its remote's credential, authentication and address.

    Since R154 a rename moves nothing on disk. The directory is the
    project's for good and every store, session, container and Claude Code
    path keys by it, so the registry's shown name is all that changes, and
    nothing that holds the project has to be asked to let go first.
    """
    old = _field(req, "name").strip()
    shown = registry.clean_name(_field(req, "to"))
    token = _field(req, "token").strip()
    # "" leaves the remote's spelling alone, which is what every rename that is
    # only a rename sends.
    auth = _field(req, "auth").strip()
    # Ignored when a token came with it: the dialog does not send both, and a
    # request that did would be asking to write a credential and delete it in
    # the same breath. The write is the intention worth honoring.
    clear = bool(req.get("clear_token")) and not token
    # The same repository's new address, after its owner was renamed on the
    # host (set_address); "" leaves the remote where it points.
    address = _field(req, "address").strip()
    if not old or not PROJECT_NAME.fullmatch(old):
        return {"error": "unknown project"}, 400
    if auth and auth not in ("https", "ssh", "none"):
        return {"error": "that is not an authentication mode"}, 400
    src = WORKSPACE / old
    if not src.is_dir():
        return {"error": f"{old} is not a project under the workspace"}, 400
    if _field(req, "to").strip() and not shown:
        return {"error": "a name needs at least one letter or digit in it"}, 400
    if token and not TOKEN_RE.fullmatch(token):
        return {"error": "that does not look like an access token: letters, "
                         "digits, dots, dashes and underscores, no spaces"}, 400
    was = registry.label(old)
    renaming = bool(shown) and shown != was
    if not renaming and not token and not auth and not clear and not address:
        return {"error": f"{was} is already its name"}, 400
    moved, failed = [], []
    if renaming:
        r = registry.set_name(old, shown)
        if r.get("error"):
            return {"error": r["error"]}, 400
        moved.append("its name")
    if token:
        # The remote decides where the credential is filed: git matches a
        # stored line on scheme and host, so a token written against the
        # wrong one is a file it reads and ignores.
        addr = forges.parse(origin_url(src))
        if not addr:
            return {"error": f"{was} has no remote to store a token for"}, 400
        host = forges.host_of(origin_url(src)) or addr["host"]
        forge = forges.forge_of(host)
        # An ssh remote's scheme is not a scheme git stores a credential
        # under; https is where a token would be used if the switch below
        # ever points the remote at one.
        scheme = "http" if addr["scheme"] == "http" else "https"
        write_token(old, token, host, scheme,
                    forges.cred_user(forge, host, token, scheme))
        _scope_to_token(src, token_helper(old))
        moved.append("its access token")
    elif clear:
        forget_token(old)
        unscope(src)
        moved.append("its access token, removed")
    # The address before the switch: set_auth rebuilds an https remote
    # from the path the remote has, which should be the new one.
    if address:
        msg, err = set_address(old, src, address)
        if err:
            return {"error": err}, 400
        if msg:
            moved.append(msg)
    # After the token, always: switching to https needs the token that the
    # same submit may have just written.
    if auth:
        msg, err = set_auth(old, src, auth)
        if err:
            return {"error": err}, 400
        if msg:
            moved.append(msg)
    return {"ok": True, "name": old, "label": registry.label(old), "from": was,
            "moved": moved, "failed": failed}, 200


# ---------------------------------------------------------------------------
# push rights
#
# A clone is read-only unless it was asked for otherwise, and the asking is a
# decision with three properties the operator set out:
#
#   - it cannot be turned off on its own. A repository that could push
#     yesterday and cannot today, with nothing to explain the difference to
#     whoever is standing in it, is the state worth not having. It goes with
#     the remote instead (unlink takes both, so the reason a push now fails
#     is that there is nowhere to push to), and deleting the project takes
#     both as well. Neither touches the host.
#   - exactly one project may push to a given repository. Two working
#     copies both able to push to one remote is how two people's work ends up
#     racing through the same branch, and here both "people" may be the same
#     session on different days.
#   - it is checked before it is granted, where a token can be checked at all.
#
# The enforcement is a pre-push hook and is honest about what it is: a session
# with Bash can delete it, exactly as it can read the token file. What it buys
# is that a push nobody asked for fails with a sentence saying so, instead of
# succeeding.
PUSH_FILE = None            # set in configure(), beside the rest


def load_push():
    try:
        with open(STATE / "push-rights.json") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_push(d):
    write_json(STATE / "push-rights.json", d)


def repo_path_of(url):
    """owner/repo for one remote URL, as written. "" if it is not one.

    The host is not what identifies it here. A deploy-key setup addresses the
    forge through a ~/.ssh/config alias, so the hostname is bb-something and
    the path after it is still the repository's.

    Case is preserved here and folded by the caller that wants it folded. The
    two callers want opposite things: comparing two remotes needs Owner/Repo
    and owner/repo to be equal, and building a URL to write into a remote must
    not quietly rename the repository to its lowercase spelling.
    """
    got = forges.parse(url)
    return got["path"] if got else ""



def push_holder(host, repo):
    """The project that already holds push on this repository, or "".

    Keyed on the host as well as the path, because `sean/app` on GitHub and
    `sean/app` on the Gitea in the cupboard are two repositories: mirroring
    one to the other is a reason somebody links a second project, not a
    collision to refuse.
    """
    if not repo:
        return ""
    h = (host or "").lower()
    for name, rec in load_push().items():
        if not isinstance(rec, dict):
            continue
        if rec.get("repo") == repo and (rec.get("host") or "").lower() == h:
            return name
    return ""


def grant_push(project, host, repo, how):
    d = load_push()
    d[project] = {"repo": repo, "host": host, "how": how, "at": int(time.time())}
    save_push(d)


def may_push(project):
    return isinstance(load_push().get(project), dict)


def push_how(project):
    """"token", "key", or "": what a project's push rights were granted on.

    The rename dialog asks, because the answer changes what setting a token
    there means: for a key-based project it is the first half of moving off
    deploy keys, and the second half is the remote itself.
    """
    rec = load_push().get(project)
    return rec.get("how", "") if isinstance(rec, dict) else ""


# ---------------------------------------------------------------------------
# which credential a project's remote actually uses
#
# Storing a token and using one are different things, and the gap between them
# is where this used to sit: git never asks a credential helper about an ssh
# remote, so a project cloned with a deploy key went on using the key however
# many tokens were saved for it. The rename dialog said so honestly and left it
# there, which meant the only way to move a project onto its token was to know
# `git remote set-url` and type it yourself.
#
# So the remote's spelling becomes a control. Neither credential is removed by
# switching: the token file stays where it is, the ssh alias and the key it
# names stay in ~/.ssh/config, and the helper stays configured on the repo
# (an ssh remote simply never consults it). That is what makes this a switch
# rather than a migration: you can go back, and going back costs nothing.

def origin_url(dest):
    """The origin remote's URL, or "" if there is no origin to ask about."""
    r = run(["git", "-C", str(dest), "remote", "get-url", "origin"], timeout=15)
    return r["out"].strip() if r["code"] == 0 else ""


def scoped_to_token(dest, project):
    """Is this repository actually pointed at its own stored token?

    An https remote with no helper naming that file authenticates with
    nothing, which is a real state and a deliberate one, not a broken version
    of having a token. Telling the two apart is what lets the dialog offer
    "disabled" as its own answer rather than as the absence of an answer.
    """
    f = STATE / "gitcreds" / project
    if not f.is_file():
        return False
    r = run(["git", "-C", str(dest), "config", "--local",
             "--get-all", "credential.helper"], timeout=15)
    return r["code"] == 0 and f"store --file={f}" in r["out"]


def remote_auth(dest, project=""):
    """"ssh", "https", "none", or "": what actually authenticates here.

    The question is not which host: a deploy-key setup addresses the forge
    through a `bb-<key>-<host>` alias, so the hostname in the URL is not the
    server's and it is still ssh.
    What decides it is the URL's form, which is exactly what git looks at when
    it decides whether a credential helper is involved at all.

    "none" is an https remote with no token behind it. It is a third state and
    not a half-broken second one: an operator who wants this project to push
    nowhere for now can say so, and the dialog can then refuse to Save its way
    into that state by accident, which is what clearing a token while the
    switch still said "access token" used to do.
    """
    url = origin_url(dest)
    if not url:
        return ""
    if url.startswith(("https://", "http://")):
        return "https" if (project and scoped_to_token(dest, project)) else "none"
    if url.startswith("ssh://") or (":" in url and "://" not in url):
        return "ssh"
    return ""


def _remembered_ssh(project):
    """The ssh URL this project last pushed with, if it has been switched.

    Kept beside the push grant rather than in a store of its own: it is a fact
    about how this project reaches its repository, the record is already keyed
    by project name, and rename() already carries that record across. Without
    it, switching back to a deploy key would have to guess the alias, and the
    alias is named after the KEY, not the project, so there is nothing here to
    guess it from.
    """
    rec = load_push().get(project)
    return rec.get("ssh_url", "") if isinstance(rec, dict) else ""


def _remember_ssh(project, url):
    d = load_push()
    rec = d.get(project)
    if not isinstance(rec, dict):
        return                  # no grant to hang it on; nothing to remember
    rec["ssh_url"] = url
    save_push(d)


def auth_options(project, dest):
    """What this project could authenticate with, for the settings dialog.

    `now` is what it uses, including "none", an https remote with no token
    behind it. `token` and `ssh` say whether the other answers are even
    available, so the dialog can show a choice that is real: an option nobody
    can take is worse than no option, because it reads as a thing that is
    broken. "Disabled" is always available, being the absence of a credential
    rather than the presence of one.
    """
    now = remote_auth(dest, project)
    return {"now": now,
            # As written, for the address field: a deploy key's alias shows
            # as the alias, which is what the field will keep.
            "url": origin_url(dest),
            "token": bool(token_helper(project)),
            # Either it is on ssh already, or it was and we kept the URL. A
            # project that has only ever been https has no alias and no key
            # picked, and offering "deploy key" would be offering to build
            # one, which is the clone dialog's job, not this one's.
            "ssh": now == "ssh" or bool(_remembered_ssh(project))}


def _same_repository(dest, url):
    """"" when the repository at `url` shares this project's history, else why
    not. Its branch tips are asked for (ls-remote, under the repository's own
    credential config) and one of them has to be a commit this project
    already has: an owner renamed on the host keeps every commit, while a
    typo or another repository has none of them. A fork shares them too,
    which is why this is the operator's control and says what it checked."""
    r = run(["git", "-C", str(dest), "ls-remote", "--heads", "--", url],
            timeout=60, env=_git_env(), split_err=True)
    if r["code"] != 0:
        said = (r["err"] or r["out"]).strip().splitlines()
        return f"could not reach {url}: " + (said[-1][:200] if said else f"git said nothing (exit {r['code']})")
    tips = [ln.split()[0] for ln in r["out"].splitlines() if len(ln.split()) == 2]
    if not tips:
        return (f"{url} has no branches, so nothing shows it is this repository; "
                "an empty repository is linked with Unlink and Link instead")
    for sha in tips:
        if run(["git", "-C", str(dest), "cat-file", "-e", f"{sha}^{{commit}}"], timeout=15)["code"] == 0:
            return ""
    return (f"the repository at {url} shares no commit with this project, so it is not "
            "this repository at a new address; a different repository is linked with "
            "Unlink and Link")


def set_address(project, dest, url):
    """Point origin at the same repository's new address. (message, error).

    For an owner or an organization renamed on the host: the host redirects
    the old address only until somebody claims the old name, and until this
    the only way to move was Unlink, which takes the token and the push
    rights with it, or `git remote set-url`, after which the relay refused
    every push because the rights name the old path. So the path changes and
    nothing else: the remote keeps its form (https, ssh, or a deploy key's
    alias, which is named after the key and still reaches the same host),
    the token stays filed under the host it always was, and the push grant
    and the remembered ssh address move with the path. Refused for another
    host, for a repository another project may push to, and for one that
    shares no commit with this project."""
    now = origin_url(dest)
    if not now:
        return "", "this project has no origin remote to point anywhere else"
    if busy_name() == project:
        return "", f"a job is working on {project}; let it finish first"
    old_path = repo_path_of(now)
    got = forges.parse(url)
    if not got or not old_path:
        return "", ("not a repository address; use https://host/owner/repo, "
                    "git@host:owner/repo.git or ssh://git@host/owner/repo.git")
    new_path = got["path"]
    host = (forges.host_of(now) or "").lower()
    if (forges.host_of(url) or got["host"] or "").lower() != host:
        return "", (f"that address is on another host than {host}: a repository moved to "
                    "another host is linked again with Unlink and Link")
    if new_path == old_path:
        return "", ""
    holder = push_holder(host, new_path.lower())
    if holder and holder != project:
        return "", f"{holder} already pushes to {host}/{new_path}, and one project pushes to a repository"
    # The same remote with its path replaced: the form, the user and an
    # alias stay as they were.
    i = now.rfind(old_path)
    moved_to = now[:i] + new_path + now[i + len(old_path):]
    why = _same_repository(dest, moved_to)
    if why:
        return "", why
    r = run(["git", "-C", str(dest), "remote", "set-url", "origin", moved_to], timeout=15)
    if r["code"] != 0:
        return "", f"could not rewrite the remote: {r['out'].strip()[:200]}"
    d = load_push()
    rec = d.get(project)
    if isinstance(rec, dict):
        rec["repo"] = new_path.lower()
        ssh = rec.get("ssh_url") or ""
        j = ssh.rfind(old_path)
        if j >= 0:
            rec["ssh_url"] = ssh[:j] + new_path + ssh[j + len(old_path):]
        save_push(d)
    return (f"it now points at {host}/{new_path}"
            + ("; its push rights and credentials came with it" if isinstance(rec, dict) else "")), ""


def set_auth(project, dest, mode):
    """Point origin at a credential, or at none. Returns (message, error).

    Three answers, not two. "none" is what an operator picks to turn pushing
    off deliberately: the remote is left in its https form and the helper is
    taken off it, so git has nothing to authenticate with and says so, rather
    than quietly falling back on whatever else it can find.
    """
    now = remote_auth(dest, project)
    if mode not in ("https", "ssh", "none"):
        return "", "that is not an authentication mode"
    if not now:
        return "", "this project has no origin remote to switch"
    if mode == now:
        return "", ""                       # already there; not worth an error
    if mode == "https" and not token_helper(project):
        return "", ("there is no access token stored for this project; "
                    "set one in the same dialog and it can use it")
    if mode == "ssh":
        url = _remembered_ssh(project)
        if not url:
            return "", ("this project has no deploy-key remote to go back to: "
                        "it has only ever used https")
    else:
        # As written, NOT folded: a lowercased path once built the URL here,
        # and that turned Stencil-Projects/BuilderBot into
        # stencil-projects/builderbot in the operator's own remote. The
        # hosts here accept either, so nothing broke; it just no longer said
        # the name of the repository it points at.
        repo = repo_path_of(origin_url(dest))
        # The host the ssh alias stands for, not the alias: `bb-key-github-com`
        # is not a hostname anything can fetch from over https.
        host = forges.host_of(origin_url(dest))
        if not repo or not host:
            return "", "could not read the repository from this project's remote"
        # Remembered BEFORE the rewrite, or switching back has nothing to go on.
        if now == "ssh":
            _remember_ssh(project, origin_url(dest))
        # Spelled the way the token was stored: git matches a credential on
        # scheme and host, port included, so a Gitea on plain http or on
        # :3000 written here as https://host would authenticate with nothing.
        stored = token_target(project) or {}
        url = f"{stored.get('scheme') or 'https'}://{stored.get('host') or host}/{repo}.git"
    r = run(["git", "-C", str(dest), "remote", "set-url", "origin", url],
            timeout=15)
    if r["code"] != 0:
        return "", f"could not rewrite the remote: {r['out'].strip()[:200]}"
    if mode == "https":
        # Only now: scoping the repo to its own token while the remote was
        # still ssh would have looked like it did something and done nothing.
        _scope_to_token(dest, token_helper(project))
        return "it now authenticates with its access token", ""
    if mode == "ssh":
        return "it now authenticates with its deploy key", ""
    unscope(dest)
    return "it authenticates with nothing now; pushing is off", ""


def drop_push(project):
    """Release the grant.

    Two callers and no third: the project is going away, or its remote is.
    Unlink takes the grant with the remote it was about. There is deliberately
    no way to revoke it on a project that keeps its remote, because that
    leaves a repository nobody can explain the refusal of.
    """
    d = load_push()
    if d.pop(project, None) is not None:
        save_push(d)


HOOK = """#!/bin/sh
# Written by BuilderBot. This working copy was cloned read-only: nobody asked
# for push rights on it, so pushing is refused here rather than being allowed
# to surprise somebody.
#
# Push rights are granted once, when a project is cloned, and cannot be turned
# on afterwards: delete this project and clone it again asking for them. Only
# one project at a time may push to a given repository.
echo "refusing to push: this project was cloned without push rights." >&2
echo "Delete it and clone again with push enabled if that is what you want." >&2
exit 1
"""


def set_push_hook(dest, allowed):
    """Install or remove the refusing pre-push hook."""
    h = Path(dest) / ".git" / "hooks" / "pre-push"
    try:
        if allowed:
            if h.is_file() and "Written by BuilderBot" in h.read_text():
                h.unlink()
            return
        h.parent.mkdir(parents=True, exist_ok=True)
        h.write_text(HOOK)
        os.chmod(h, 0o755)
    except OSError:
        pass                    # a hook that could not be written is not a
                                # reason to fail the clone that succeeded


def check_token_push(token, repo):
    """Ask GitHub whether this token can actually push to this repository.

    Before granting, not after: a token missing the scope produces a failure
    at the first push, days later, with nothing connecting it to the box that
    was ticked. The API answers this directly (permissions.push on the repo),
    and answering it costs one request.

    Returns "" when the token is good, and the sentence to show otherwise.
    """
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "BuilderBot"})
    try:
        # The host is the literal above; only the repo path varies, and it is quoted.
        with urllib.request.urlopen(req, timeout=20) as r:  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
            data = json.loads(r.read(200000))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return ("GitHub rejected that token: it is wrong, expired, or "
                    "not authorized for this repository")
        if e.code == 404:
            return (f"that token cannot see {repo}: a fine-grained token has "
                    f"to list this repository explicitly")
        return f"GitHub answered {e.code} when asked about {repo}"
    except (OSError, ValueError) as e:
        return f"could not reach GitHub to check the token: {e}"
    if not data.get("permissions", {}).get("push"):
        return (f"that token can read {repo} but not push to it: it needs "
                f"write access to contents")
    return ""


TRASH = ".trash"


def trash(req):
    """Take a project out of the workspace without destroying it.

    Moved, not deleted, and the wording everywhere says so: the files are still
    there, under /workspace/.trash, and getting one back is a `mv`. The project
    scan skips anything starting with a dot, so the directory stops being a
    project the moment it lands there.

    A second delete of the same name does not overwrite the first. It is
    numbered, because the two are different work and the older one is exactly
    the copy somebody would be trying to get back.

    What is deliberately left alone is /config: the roadmap, the bugs, the
    versions and the memories all stay where they are. Deleting from here is a
    reversible act, and taking the notebook with it would make it the one thing
    that cannot be undone by moving a directory back.
    """
    name = _field(req, "name").strip()
    if not name or not PROJECT_NAME.fullmatch(name):
        return {"error": "unknown project"}, 400
    src = WORKSPACE / name
    if not src.is_dir():
        return {"error": f"{name} is not a project under the workspace"}, 400
    with _lock:
        if _job["running"]:
            return {"error": f"already {DOING.get(_job['kind'], 'working on')} "
                             f"{_job['name']}"}, 409
    bin_ = WORKSPACE / TRASH
    try:
        bin_.mkdir(exist_ok=True)
    except OSError as e:
        return {"error": f"could not make {TRASH}: {e}"}, 500
    dest = bin_ / name
    n = 2
    while dest.exists():
        dest = bin_ / f"{name}-{n}"
        n += 1
        if n > 999:                       # a loop that cannot run away
            return {"error": f"too many deleted copies of {name}"}, 500
    try:
        src.rename(dest)
    except OSError as e:
        return {"error": f"could not move it: {e}"}, 500
    # The grant goes with it. This is the only way push rights are ever
    # released, which is the point: another project can now be cloned with
    # push on this repository, and this copy is still sitting in .trash if it
    # turns out that was a mistake.
    drop_push(name)
    registry.mark(name, "trashed")
    return {"ok": True, "name": name, "label": registry.label(name),
            "to": f"{TRASH}/{dest.name}"}, 200


def _bin_path(name):
    """The one directory a purge or a restore is allowed to touch, or None.

    Everything about this function is the guard. The name comes off a request,
    so it is matched against the same pattern a project name is, then joined
    and RESOLVED and required to still be a direct child of the bin, which is
    what a `..` or a symlink cannot survive. A permanent delete is the one act
    here with nothing behind it, so it gets the one path check that assumes
    the caller is wrong.
    """
    if not name or not PROJECT_NAME.fullmatch(name):
        return None
    bin_ = (WORKSPACE / TRASH)
    try:
        p = (bin_ / name).resolve()
        if p.parent != bin_.resolve() or not p.is_dir():
            return None
    except OSError:
        return None
    return p


def trash_list():
    """What is in the bin, newest first.

    No size: a project tree is thousands of files on a network share, and
    walking every one of them to put a number beside a name nobody is choosing
    between would make opening the bin slower than deleting from it.
    """
    bin_ = WORKSPACE / TRASH
    out = []
    try:
        entries = sorted(bin_.iterdir())
    except OSError:
        return {"items": []}
    for d in entries:
        if not d.is_dir() or d.name.startswith("."):
            continue
        try:
            at = int(d.stat().st_mtime)
        except OSError:
            at = 0
        # `name-2` is the second delete of `name`; the original name is what
        # somebody is looking for, and what a restore would put back.
        # Since R154 the directory is the project's own, never reused, and
        # goes back where it was; the name shown is the registry's.
        out.append({"name": d.name, "was": registry.label(d.name), "at": at,
                    "taken": (WORKSPACE / _restore_dir(d.name)).exists()})
    out.sort(key=lambda e: -e["at"])
    return {"items": out}


def _restore_dir(name):
    """Where a directory in the bin goes back to: the directory it was.
    One deleted before ids (R154) and numbered then (X-2) was X, and goes
    back to X while X is free, its notebook being X's."""
    if (registry.get(name) or {}).get("legacy"):
        base = re.sub(r"-\d+$", "", name)
        if not (WORKSPACE / base).exists():
            return base
    return name


def trash_restore(req):
    """Move one back out of the bin, to the directory it had. A live project
    shown under its name meanwhile makes this one Name (2)."""
    name = _field(req, "name").strip()
    src = _bin_path(name)
    if src is None:
        return {"error": "not something in the bin"}, 400
    back = _restore_dir(name)
    dest = WORKSPACE / back
    if dest.exists():
        return {"error": f"{back} exists again; move it first"}, 409
    try:
        src.rename(dest)
    except OSError as e:
        return {"error": f"could not move it back: {e}"}, 500
    if back != name:
        registry.claim(back, registry.label(name))
        registry.mark(name, "purged")
    else:
        registry.mark(back, "live")
    return {"ok": True, "name": back, "label": registry.label(back)}, 200


def trash_purge(req):
    """Delete one for good, files and all. There is nothing after this.

    Guarded three ways and none of them are decoration: the path is resolved
    and required to be a direct child of the bin, the caller has to send the
    directory's exact name back as confirmation, and the whole thing refuses
    while a clone or a link is running: a job holding a working copy is not a
    tree to pull out from under it.
    """
    name = _field(req, "name").strip()
    if _field(req, "confirm").strip() != name:
        return {"error": "type the name to confirm"}, 400
    src = _bin_path(name)
    if src is None:
        return {"error": "not something in the bin"}, 400
    with _lock:
        if _job["running"]:
            return {"error": f"already {DOING.get(_job['kind'], 'working on')} "
                             f"{_job['name']}"}, 409
    try:
        shutil.rmtree(src)
    except OSError as e:
        return {"error": f"could not delete it: {e}"}, 500
    # Gone for good, its directory still never handed out again (R154).
    registry.mark(name, "purged")
    return {"ok": True, "name": name}, 200


def _git_env():
    return dict(os.environ, GIT_TERMINAL_PROMPT="0",
                GIT_SSH_COMMAND="ssh -o BatchMode=yes "
                                "-o StrictHostKeyChecking=accept-new")


# ---- the one job ----------------------------------------------------------
# One at a time, like the toolchain worker and for the same reason: these are
# minutes long, and a queue that did not survive a page reload would be a
# promise the page could not keep. `step` is a phrase, not a percentage:
# git's progress is a carriage-return animation on stderr, and parsing it to
# redraw it was rejected once already on the toolchains tab. The page draws an
# ellipsis after whatever this says.
# What each kind is called while it is happening, for the one message that
# has to name it. The page has its own copy for the row it draws.
DOING = {"clone": "cloning", "link": "linking"}

_job = {"running": False, "kind": "", "name": "", "step": "", "at": 0.0,
        "error": "", "note": "", "aborting": False}
_lock = threading.Lock()
_proc = None                  # the git process, so an abort can reach it
_dest = None                  # the directory this job made, if it made one


def job():
    """The job record for the status payload."""
    with _lock:
        j = dict(_job)
    j["for"] = int(time.time() - j["at"]) if j["at"] else 0
    return j


def busy_name():
    """The project a running job is writing, so the list can say so.

    A half-finished clone is a directory with a `.git` in it and not much
    else, which the project listing reads as a repo in a strange state and
    reports as a problem. It is not a problem, it is a clone, but only this
    module knows that.
    """
    with _lock:
        return _job["name"] if _job["running"] else ""


def _step(text):
    with _lock:
        _job["step"] = text


def _register(p):
    global _proc
    _proc = p


def dismiss():
    """Clear the last outcome. The record holds it after the job ends so that
    a failure survives the page being closed, but then it has to be possible
    to say it has been read, or the card carries it forever."""
    with _lock:
        if _job["running"]:
            return {"error": "it is still running"}
        _job.update(error="", note="", kind="", name="", at=0.0)
    return {"ok": True}


def abort():
    """Stop the running job and clean up after it."""
    with _lock:
        if not _job["running"]:
            return {"error": "nothing is running"}
        _job["aborting"] = True
    p = _proc
    if p is not None:
        try:
            # The group, not the process: git clone waits on git-remote-https,
            # and killing only the parent leaves the child holding the
            # directory that is about to be removed.
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    return {"ok": True}


def _finish(error="", note=""):
    with _lock:
        _job.update(running=False, step="", error=error, note=note,
                    aborting=False)


def _start(kind, name, fn):
    """Hand one job to a thread. The caller has already validated everything."""
    with _lock:
        if _job["running"]:
            return False
        _job.update(running=True, kind=kind, name=name, step="starting",
                    at=time.time(), error="", note="", aborting=False)
    threading.Thread(target=_wrap, args=(fn,), daemon=True).start()
    return True


def _wrap(fn):
    try:
        error, note = fn()
    except Exception as e:                                  # noqa: BLE001
        # A worker thread that dies silently leaves the job "running" forever
        # and the buttons dead with it. Whatever went wrong, it ends here.
        error, note = f"unexpected failure: {e}", ""
    finally:
        _register(None)
    _finish(error, note)


def _aborted():
    with _lock:
        return _job["aborting"]


# ---- creating -------------------------------------------------------------

def create(req, env=None):
    """Create a project under /workspace, as a (payload, status) pair.
    `env` is the account's git identity, for the commits a starting version
    makes.

    A fresh local repo is done by the time this returns. A clone is validated
    and claimed here (the name checked, the directory made) and then handed
    to the worker, because the fetch is the part that takes minutes.

    mkdir is the claim: it is atomic, so two requests racing on one name get
    one directory and one clean "already exists". On failure the directory
    this request just made is removed, never one that was already there,
    which is the FileExistsError branch returning first.
    """
    mode = _field(req, "mode")
    if mode not in ("init", "clone"):
        return {"error": "unknown mode"}, 400
    url = _field(req, "url").strip()
    about, key_url = "", ""
    if mode == "clone":
        addr = forges.parse(url)
        if not addr:
            return {"error": "not a repository address; use "
                             "https://host/owner/repo, git@host:owner/repo.git "
                             "or ssh://git@host/owner/repo.git"}, 400
        # Which host this is. The address wins wherever it names itself (a
        # catalog host, or one the operator has already answered for), and the
        # picked entry is consulted only for a server nobody has said anything
        # about yet, which is the only case the form asks about.
        named = forges.forge_of(addr["host"])
        forge = (named if named["id"] != forges.OTHER["id"]
                 else (forges.get(_field(req, "forge")) or named))
        if not forges.allowed(forge):
            return {"error": forges.not_offered(forge)}, 400
        if forge["fixed"] and forge["host"] and forge["host"] != addr["host"].split(":")[0].lower():
            return {"error": f"{forge['name']} is {forge['host']}, and that "
                             f"address is on {addr['host']}"}, 400
        bad = forges.path_ok(forge, addr["path"])
        if bad:
            return {"error": bad}, 400
        # Remembered against the host, so this is asked once per server rather
        # than once per project.
        forges.remember(addr["host"], forge["id"])
        # The repository's own name, unless the operator gave one. It used to
        # be derived and nothing else, on the reasoning that the repo already
        # knows what it is called, which is true right up until you want two
        # checkouts of it. Deploying an app from a public repo is exactly that
        # case: three Radarrs are three directories and one repository. So the
        # field is optional and defaults to this, and typing nothing still
        # gets the derived name. Notes are not asked for either way: they
        # are drafted from the code after the clone.
        name = sanitize_name(_field(req, "name"))
        if not name:
            name = sanitize_name(addr["path"].rsplit("/", 1)[-1])
        # An optional deploy key, by name. The name is only ever matched
        # against what the agent actually holds: nothing from the request is
        # written into a file or a config line; the matched key's own public
        # line is. When one is chosen the clone goes through a per-repo alias,
        # which also leaves the remote pointing at that alias, so pushes keep
        # using the right key without anyone re-doing this by hand.
        # A token for this project alone. Checked for shape before it is
        # written: it goes into a file whose format is one line, so whitespace
        # or a newline in it would produce a credential store git reads as
        # something else entirely.
        token = _field(req, "token").strip()
        if token and not TOKEN_RE.fullmatch(token):
            return {"error": "that does not look like an access token: "
                             "letters, digits, dots, dashes and underscores, "
                             "and no spaces"}, 400
        # Push rights, decided here and never again. Checked before the
        # directory is claimed so a refusal leaves nothing behind, and checked
        # in this order: is the repository already spoken for, then can this
        # token actually do it. The second costs a network call and the first
        # does not.
        want_push = bool(req.get("push"))
        repo_id = addr["path"].lower()
        if want_push:
            holder = push_holder(addr["host"], repo_id)
            if holder:
                return {"error": f"{holder} already has push rights on "
                                 f"{addr['host']}/{repo_id}. Only one project "
                                 f"may push to a repository: unlink or delete "
                                 f"that one first, or clone this one without push"}, 409
            # Asked of the host before the right is granted, where the host can
            # be asked at all: a token missing the scope otherwise fails at the
            # first push, days later, with nothing connecting it to the box
            # that was ticked. Where it cannot, the first push is the test,
            # which is the honest answer, not a silently skipped check.
            if token and forge["kind"] == "github":
                bad = check_token_push(token, repo_id)
                if bad:
                    return {"error": bad}, 400
            elif not token and not keyname_ok(req):
                return {"error": "pushing needs either an access token or a "
                                 "deploy key: a public clone cannot push"}, 400
        keyname = _field(req, "key").strip()
        if keyname:
            match = next((k for k in agent_keys() if k["name"] == keyname), None)
            if match is None:
                return {"error": f"the agent holds no key named {keyname}"}, 400
            alias = ensure_deploy_alias(match["name"], match["pub"], addr["host"])
            key_url = f"git@{alias}:{addr['path']}.git"
    else:
        name = sanitize_name(_field(req, "name"))
        about = _field(req, "about").strip()
        # A brief says what to build from nothing; an archive IS the start,
        # so the dialog stops offering one once a file is picked, and a
        # request carrying both is refused rather than half obeyed.
        if about and _field(req, "archive"):
            return {"error": "a project started from an archive has no brief: its code is where it starts"}, 400
    # After sanitizing, the only way to fail this is an empty name: every
    # other shape has already been turned into something legal. Kept as the
    # gate rather than replaced by `if not name`, because it is the invariant
    # the rest of this file and the path handling below rely on, and an
    # assertion that cannot fire is cheaper than one that was removed.
    if not PROJECT_NAME.fullmatch(name):
        return {"error": "a name needs at least one letter or digit in it"}, 400
    # The name as typed is the one shown; the directory is the sanitized one,
    # numbered when any project ever had it (R154), so a new project never
    # takes over an old one's notebook or containers.
    shown = registry.clean_name(_field(req, "name")) or name
    name = registry.new_dir(name)
    # Asked before the directory is claimed, so a refused second job does not
    # leave an empty directory behind it.
    if mode == "clone":
        with _lock:
            if _job["running"]:
                return {"error": f"already {DOING.get(_job['kind'], 'working on')} "
                                 f"{_job['name']}"}, 409
    dest = WORKSPACE / name
    with _mkdir_lock:
        try:
            dest.mkdir()
        except FileExistsError:
            return {"error": f"{name} already exists in the workspace"}, 400
        except OSError as e:
            return {"error": f"cannot create {name}: {e}"}, 500
    registry.claim(name, shown)
    if mode == "init":
        # An archive to start from: unpacked into the directory just claimed,
        # BEFORE git init, so the tree is there for the first status.
        # Anything wrong with it removes that directory, made a moment ago,
        # so nobody else's.
        arch = _field(req, "archive")
        if arch:
            r = unpack_archive(arch, dest)
            if r.get("error"):
                shutil.rmtree(dest, ignore_errors=True)
                return r, 400
            body, code = _init(dest, name, about, _field(req, "version"), env)
            if code == 200:
                body["note"] = f"{r['files']} files from {r['name']}; {body.get('note') or 'ready'}"
            return body, code
        return _init(dest, name, about, _field(req, "version"), env)
    global _dest
    _dest = dest
    cred_scheme = "http" if mode == "clone" and addr["scheme"] == "http" else "https"
    helper = (write_token(name, token, addr["host"], cred_scheme,
                          forges.cred_user(forge, addr["host"], token, cred_scheme))
              if mode == "clone" and token else "")
    if not _start("clone", name,
                  lambda: _clone(dest, key_url or url, helper, want_push)):
        shutil.rmtree(dest, ignore_errors=True)             # made a moment ago
        forget_token(name)                                  # written a moment ago
        return {"error": "another project job is already running"}, 409
    if want_push:
        grant_push(name, addr["host"], repo_id, "token" if token else "key")
    return {"ok": True, "name": name, "started": True}, 200


_mkdir_lock = threading.Lock()


def _init(dest, name, about, version="", env=None):
    r = run(["git", "init", "-b", "main", str(dest)], timeout=30)
    if r["code"] != 0:
        shutil.rmtree(dest, ignore_errors=True)             # made a moment ago
        return {"error": r["out"].strip()[-2000:] or "git init failed"}, 500
    note = brief_writer(dest, about) if brief_writer else ""
    # A starting version (the operator, 25 Sep): the tree as made is the
    # first commit, and VERSION at that number the second, the way the
    # Artifacts tab gives a project its first version, so a new project has
    # a history to count from the moment it exists. Blank asks for neither.
    # The first may be empty: a project started from nothing has no files
    # (its brief is kept out of git), and git refusing an empty commit left
    # it with no history and no version at all.
    version = str(version or "").strip()
    if version and first_version:
        r = run(["git", "-C", str(dest), "add", "-A"], timeout=60)
        if r["code"] == 0:
            r = run(["git", "-C", str(dest), "commit", "-q", "--allow-empty", "-m", f"Start {name}"],
                    timeout=60, env=env)
        if r["code"] != 0:
            note = f"{note or 'ready'}; not committed: {r['out'].strip()[-300:] or 'git commit failed'}"
        else:
            v = first_version(name, version, env)
            note = (f"{note or 'ready'}; version not set: {v['error']}" if v.get("error")
                    else f"{note or 'ready'}; committed at {version}")
    if after_create:
        after_create(name)          # the map, in the background, from here on
    return {"ok": True, "name": name, "note": note}, 200


# ---- starting from an archive ---------------------------------------------
# A code base somebody already has (a zip from a download page, a tarball
# off another machine), dropped into a new local repo. Uploaded first, into
# a spool on this container's own disk, and named by a random id the create
# request then quotes: the two steps keep the JSON API's body cap where it
# is, and an upload nobody follows up on is swept on the next one. The spool
# is container-local on purpose: it holds nothing worth keeping.
SPOOL = Path(os.environ.get("BB_ARCHIVE_SPOOL") or
             os.path.join(tempfile.gettempdir(), "builderbot-archives"))
ARCHIVE_MAX = 512 * 1024 * 1024        # the upload, on the wire
UNPACKED_MAX = 4 * 1024 * 1024 * 1024  # what it may become on disk
MEMBERS_MAX = 200_000
SPOOL_TTL = 30 * 60
ARCHIVE_KINDS = "zip, tar, tar.gz (tgz), tar.bz2, tar.xz"
# Junk that rides along in an archive made on a desktop and never belongs in
# a repository: skipped rather than refused, and not worth a sentence.
_JUNK = ("__MACOSX", ".DS_Store", "Thumbs.db")


def spool_archive(stream, size, filename):
    """Stream an upload into the spool; {id, name, size} or {error}.

    Checked as an archive once it is on disk (zipfile and tarfile each
    read their own signature), so a wrong file is refused now, with the
    formats named, rather than at create time with a directory to undo.
    """
    if not 0 < size <= ARCHIVE_MAX:
        return {"error": f"an archive is at most {ARCHIVE_MAX // (1024 * 1024)}MB here"}
    name = os.path.basename(str(filename or "archive"))[:120] or "archive"
    try:
        SPOOL.mkdir(parents=True, exist_ok=True)
        _sweep_spool()
        aid = secrets.token_hex(8)
        dest = SPOOL / aid
        with open(dest, "wb") as f:
            left = size
            while left > 0:
                chunk = stream.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            dest.unlink(missing_ok=True)
            return {"error": "the upload ended early; try again"}
        kind = _archive_kind(dest)
        if not kind:
            dest.unlink(missing_ok=True)
            return {"error": f"{name} is not an archive this can open: {ARCHIVE_KINDS}"}
        (SPOOL / f"{aid}.name").write_text(name, encoding="utf-8")
    except OSError as e:
        return {"error": f"could not keep the upload: {e}"}
    return {"id": aid, "name": name, "size": size, "kind": kind}


def _sweep_spool():
    now = time.time()
    for f in SPOOL.iterdir():
        with contextlib.suppress(OSError):
            if now - f.stat().st_mtime > SPOOL_TTL:
                f.unlink()


def _archive_kind(path):
    if zipfile.is_zipfile(path):
        return "zip"
    try:
        if tarfile.is_tarfile(path):
            return "tar"
    except (OSError, ValueError):
        pass
    return ""


def _norm(name):
    """A member name with any leading ./ removed: `tar czf x.tgz ./app` writes
    every member that way, and the dot is not a folder anybody meant."""
    n = str(name)
    while n.startswith("./"):
        n = n[2:]
    return n


def _junk(rel):
    return any(p in _JUNK for p in rel.split("/"))


def _strip_root(names):
    """The one top-level directory every member sits under, or "". A zip
    from GitHub or a tarball made with `tar czf app.tgz app/` wraps the tree
    in a folder named after itself; the project directory IS that folder,
    so a second layer would only make every path one deeper than anybody
    expects."""
    roots = set()
    for n in names:
        n = _norm(n)
        first = n.split("/", 1)[0]
        if not first or first == "." or first in _JUNK:
            continue
        roots.add(first)
        if len(roots) > 1:
            return ""
    root = next(iter(roots), "")
    # A single FILE at the top is not a wrapper; only a directory is.
    return root if root and any(_norm(n).startswith(root + "/") for n in names) else ""


def _member_ok(rel):
    """A member path this will write: relative, inside the tree, not junk."""
    if not rel or rel.startswith("/") or "\\" in rel:
        return False
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return False
    return not any(p in _JUNK for p in parts)


def unpack_archive(aid, dest):
    """Unpack a spooled archive into `dest`; {files, name} or {error}.

    Every member path is checked to land inside `dest`: an archive is a
    list of paths somebody else wrote, and `../` or an absolute path in one
    is the classic way to write outside the directory being filled. tar
    goes through the data filter for the same reason (links out of the
    tree, device nodes, setuid bits); zip is walked by hand because zipfile
    has no filter of its own. Sizes are summed before anything is written,
    so a small file that unpacks to a disk's worth is refused rather than
    discovered.
    """
    if not re.fullmatch(r"[0-9a-f]{16}", str(aid or "")):
        return {"error": "no such upload; choose the archive again"}
    src = SPOOL / aid
    if not src.is_file():
        return {"error": "that upload has gone: uploads are kept for thirty minutes; choose the archive again"}
    try:
        name = (SPOOL / f"{aid}.name").read_text(encoding="utf-8").strip() or "archive"
    except OSError:
        name = "archive"
    kind = _archive_kind(src)
    try:
        if kind == "zip":
            n = _unzip(src, dest)
        elif kind == "tar":
            n = _untar(src, dest)
        else:
            return {"error": f"{name} is not an archive this can open: {ARCHIVE_KINDS}"}
    except _Refused as e:
        return {"error": f"{name}: {e}"}
    except Exception as e:                # noqa: BLE001
        # An encrypted member is a RuntimeError, an unknown method
        # NotImplementedError: whatever the library says, the answer is a
        # sentence and the caller removes the directory, never a 500 with a
        # half-written project left behind.
        return {"error": f"could not unpack {name}: {e}"}
    finally:
        with contextlib.suppress(OSError):
            src.unlink()
            (SPOOL / f"{aid}.name").unlink()
    if n == 0:
        return {"error": f"{name} holds no files"}
    return {"files": n, "name": name}


class _Refused(Exception):
    pass


def _check_budget(names, total):
    if len(names) > MEMBERS_MAX:
        raise _Refused(f"more than {MEMBERS_MAX} entries: too many for one project")
    if total > UNPACKED_MAX:
        raise _Refused(f"unpacks to more than {UNPACKED_MAX // (1 << 30)}GB")


def _unzip(src, dest):
    dest = dest.resolve()
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        _check_budget(infos, sum(i.file_size for i in infos))
        root = _strip_root([i.filename for i in infos])
        n = 0
        for i in infos:
            rel = _norm(i.filename)
            if _junk(rel) or rel in ("", "."):
                continue                      # a desktop's leavings, beside the tree or in it
            if root:
                if rel == root or rel == root + "/":
                    continue
                if not rel.startswith(root + "/"):
                    raise _Refused(f"{rel} sits outside {root}/")
                rel = rel[len(root) + 1:]
            if rel.endswith("/"):
                continue                      # directories come with their files
            if not _member_ok(rel):
                raise _Refused(f"{i.filename} would land outside the project")
            out = dest / rel
            if dest not in out.resolve().parents:
                raise _Refused(f"{i.filename} would land outside the project")
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as f, open(out, "wb") as g:
                shutil.copyfileobj(f, g)
            # Keep an executable bit a Unix zip recorded: a build script that
            # arrives unrunnable is a small mystery for the first session.
            mode = (i.external_attr >> 16) & 0o777
            if mode & 0o111:
                with contextlib.suppress(OSError):
                    os.chmod(out, (mode | 0o600) & 0o777)
            n += 1
    return n


def _untar(src, dest):
    dest = dest.resolve()
    with tarfile.open(src) as t:
        members = t.getmembers()
        _check_budget(members, sum(m.size for m in members if m.isfile()))
        root = _strip_root([m.name for m in members])
        keep = []
        for m in members:
            rel = _norm(m.name)
            if _junk(rel) or rel in ("", "."):
                continue
            if root:
                if rel == root:
                    continue
                if not rel.startswith(root + "/"):
                    raise _Refused(f"{rel} sits outside {root}/")
                rel = rel[len(root) + 1:]
            if not (m.isfile() or m.isdir() or m.issym()):
                continue                      # devices, fifos: not source
            if not _member_ok(rel):
                raise _Refused(f"{m.name} would land outside the project")
            m.name = rel
            keep.append(m)
        # The data filter refuses what a repository never holds (links that
        # point out of the tree, absolute names, setuid) and strips owner
        # ids, which are another machine's anyway.
        t.extractall(dest, members=keep, filter="data")
        return sum(1 for m in keep if m.isfile())


def _clone(dest, url, helper="", may_push_=False):
    """The worker half of a clone: the fetch, and the wiring after it.

    With a token, the fetch itself runs under this project's helper and
    nothing else: the empty value ahead of it resets the list, so the
    globally configured one never gets asked. The same pair is then written into the
    repository, so every later fetch and push from a terminal uses it too.
    """
    _step("cloning")
    scope = ["-c", "credential.helper=", "-c", f"credential.helper={helper}"] if helper else []
    r = run(["git", "clone", *scope, "--progress", "--", url, str(dest)],
            timeout=1800, env=_git_env(), register=_register)
    if _aborted():
        shutil.rmtree(dest, ignore_errors=True)             # made by this job
        forget_token(dest.name); drop_push(dest.name)
        return "stopped: the half-cloned directory was removed", ""
    if r["code"] != 0:
        shutil.rmtree(dest, ignore_errors=True)
        forget_token(dest.name); drop_push(dest.name)
        return r["out"].strip()[-2000:] or "git clone failed", ""
    if helper:
        _scope_to_token(dest, helper)
    set_push_hook(dest, may_push_)
    if after_create:
        after_create(dest.name)     # the map, in the background, from here on
    return "", ""


# ---- linking --------------------------------------------------------------

def link(req):
    """Point an existing local repo at an *empty* repository and push.

    Empty-only is the safety property, and it is git's rather than any one
    host's: `git ls-remote` must come back with no refs before anything is
    pushed, so this can never write over a repository that already holds work.
    The one thing it will create is a repo that does not exist at all (always
    private, and only where the host has an API to ask), because "not found"
    is the one answer that proves there is nothing there to harm.

    Auth mirrors the clone: a picked deploy key means an ssh alias, no key
    means the container's PAT answers for https on GitHub, and with neither,
    this refuses up front instead of letting the push discover it.

    Everything above is local and instant, so it is answered here. The
    ls-remote, the create and the push are the network, and go to the worker.
    """
    name = _field(req, "name").strip()
    url = _field(req, "url").strip()
    keyname = _field(req, "key").strip()
    try:
        here = {d.name for d in WORKSPACE.iterdir() if d.is_dir()}
    except OSError:
        here = set()
    if name not in here:
        return {"error": f"unknown project: {name}"}, 400
    dest = str(WORKSPACE / name)
    if run(["git", "-C", dest, "rev-parse", "--is-inside-work-tree"],
           timeout=10)["out"].strip() != "true":
        return {"error": f"{name} is not a git repository"}, 400
    if run(["git", "-C", dest, "remote"], timeout=10)["out"].strip():
        return {"error": f"{name} already has a remote; unlink it first"}, 400
    addr = forges.parse(url)
    if not addr:
        return {"error": "not a repository address; use "
                         "https://host/owner/repo, git@host:owner/repo.git or "
                         "ssh://git@host/owner/repo.git"}, 400
    host, path = addr["host"], addr["path"]
    # The picked host is what the operator says their own server runs, and it
    # only decides the dialect: a public host names itself, and picking the
    # wrong one for it is a contradiction rather than an override.
    forge = forges.get(_field(req, "forge")) or forges.forge_of(host)
    named = forges.forge_of(host)
    if not forges.allowed(forge):
        return {"error": forges.not_offered(forge)}, 400
    if named["id"] != forges.OTHER["id"] and named["id"] != forge["id"]:
        return {"error": f"{host} is {named['name']}, so it cannot be linked "
                         f"as {forge['name']}"}, 400
    if forge["fixed"] and forge["host"] and forge["host"] != host.split(":")[0].lower():
        return {"error": f"{forge['name']} is {forge['host']}, and that "
                         f"address is on {host}"}, 400
    bad = forges.path_ok(forge, path)
    if bad:
        return {"error": bad}, 400
    pat = gh_authed() and forge["id"] == "github"
    token = _field(req, "token").strip()
    helper = ""
    user = ""
    if token:
        # A token for this project alone, the way the clone dialog takes one:
        # checked with the host first where there is an API to ask, then
        # stored under /config and read by git's helper, never typed into a
        # remote URL. Where there is no API the ls-remote below is the check,
        # and it is a real one.
        bad = forges.token_ok(forge, token)
        if bad:
            return {"error": bad}, 400
        user = ""
        if forges.can_create(forge):
            user = forges.whoami(forge, host, token, addr["scheme"])
            if not user:
                return {"error": f"{forge['name']} does not accept that "
                                 f"token"}, 400
        helper = write_token(name, token, host, addr["scheme"],
                             user or forge["user"])
        remote = f"{addr['scheme']}://{host}/{path}.git"
    elif keyname:
        match = next((k for k in agent_keys() if k["name"] == keyname), None)
        if match is None:
            return {"error": f"the agent holds no key named {keyname}"}, 400
        alias = ensure_deploy_alias(match["name"], match["pub"], host)
        remote = f"git@{alias}:{path}.git"
    elif pat:
        # Plain https: gh's credential helper (wired at startup) answers for
        # it, so nothing secret lands in .git/config. GitHub only: it is the
        # only host that PAT was minted for.
        remote = f"https://{host}/{path}.git"
    else:
        return {"error": "no deploy key was picked and no access token given; "
                         "a push has to authenticate somehow"}, 400
    forges.remember(host, forge["id"])
    if not _start("link", name,
                  lambda: _link(dest, name, forge, host, path, remote,
                                bool(keyname), pat, helper=helper, token=token,
                                scheme=addr["scheme"], user=user)):
        return {"error": "another project job is already running"}, 409
    return {"ok": True, "name": name, "started": True}, 200


def unlink(req):
    """Take a project's remote off, and everything the link put there with it.

    Local and instant: no host is contacted and nothing is asked of one, so
    this works on a repository whose server is gone, which is one of the
    reasons to reach for it. Four things go, and the answer names each: the
    origin remote, the stored access token, the credential helper pointing at
    it, and the push grant, which is what frees the repository for another
    project to be linked to it.

    What it does NOT touch is the point. No commit, no branch, no file, no
    reflog: the history that was pushed is still here and can be pushed again
    the moment something is linked. The deploy-key alias in ~/.ssh/config
    stays too: it is named after the key and another project may be using it.
    """
    name = _field(req, "name").strip()
    if not name or not PROJECT_NAME.fullmatch(name):
        return {"error": "unknown project"}, 400
    dest = WORKSPACE / name
    if not dest.is_dir():
        return {"error": f"{name} is not a project under the workspace"}, 400
    if run(["git", "-C", str(dest), "rev-parse", "--is-inside-work-tree"],
           timeout=10)["out"].strip() != "true":
        return {"error": f"{name} is not a git repository"}, 400
    # A clone or a link is writing this tree right now, and the remote it is
    # about to set is the one this would be removing.
    if busy_name() == name:
        return {"error": f"a job is working on {name}; let it finish or stop "
                         f"it first"}, 409
    remotes = run(["git", "-C", str(dest), "remote"], timeout=10)["out"].split()
    if "origin" not in remotes:
        return {"error": f"{name} has no origin remote to unlink"}, 400
    was = origin_url(dest)
    r = run(["git", "-C", str(dest), "remote", "remove", "origin"], timeout=15)
    if r["code"] != 0:
        return {"error": r["out"].strip()[:200] or "could not remove the "
                                                   "remote"}, 500
    gone = [f"the remote, which was {was}"] if was else ["the remote"]
    if token_helper(name):
        forget_token(name)
        gone.append("its access token")
    unscope(dest)
    if may_push(name):
        drop_push(name)
        gone.append("its push rights, so the repository is free for another "
                    "project")
    # The refusing hook goes with the rest: it says a project was cloned
    # without push rights, and after this there is nothing to push to. Leaving
    # it would refuse the first push after the next link.
    set_push_hook(dest, True)
    left = [x for x in remotes if x != "origin"]
    return {"ok": True, "name": name, "removed": gone, "others": left}, 200


# What every host here says when the repository is not there. GitHub and
# Gitea word it one way, GitLab another, and a bare git daemon a third, and
# the difference decides whether this offers to create one or reports a wall.
_ABSENT = ("not found", "does not exist", "repository not exported",
           "could not read from remote repository", "access denied")


def _missing(blame):
    low = blame.lower()
    return any(w in low for w in _ABSENT)


def _link(dest, name, forge, host, path, remote, keyed, pat,
          helper="", token="", scheme="https", user=""):
    """The worker half: prove the remote is empty, then set it and push.

    There is no lock around check-then-add: two racing links resolve at
    `git remote add`, which refuses a duplicate origin, and the loser's error
    says exactly that. With a project token, git runs under that project's
    helper and nothing else, the way a clone does.
    """
    env = _git_env()
    scope = ["-c", "credential.helper=", "-c", f"credential.helper={helper}"] if helper else []
    created = ""
    where = forge["name"]
    _step("checking the repository is empty")
    # split_err: emptiness is judged on stdout alone. ssh's first-contact
    # "Permanently added ..." note arrives on stderr with exit 0, and combined
    # it made a genuinely empty repository look occupied.
    r = run(["git", *scope, "ls-remote", "--", remote], timeout=120, env=env,
            split_err=True, register=_register)
    if _aborted():
        return "stopped: nothing was changed", ""
    if r["code"] != 0:
        blame = (r["err"] + r["out"]).strip()
        if _missing(blame) and keyed:
            # Creating it here would not help: a brand-new repo has no deploy
            # keys, so the push over this alias still fails, and a retry
            # would then trip over the half-done state. Say what the fix
            # actually is instead.
            return (f"{where} reports the repository as not found over ssh. "
                    f"Create it (empty) there and add this deploy key to it "
                    f"first" + (", or leave the key on none to use the PAT"
                                if pat else "") + ".", "")
        if _missing(blame) and token:
            if not forges.can_create(forge):
                return (f"{where} has no repository at {path}, and this "
                        f"cannot create one there; make it empty on "
                        f"{host} and link again."), ""
            _step(f"creating it on {where}")
            why = forges.create_repo(forge, host, token, path, scheme, user)
            if why:
                return why, ""
            created = f"created {path} on {where} (private); "
        elif _missing(blame) and pat:
            _step(f"creating it on {where}")
            c = run(["gh", "repo", "create", path, "--private"], timeout=60,
                    register=_register)
            if c["code"] != 0:
                return c["out"].strip()[-2000:] or "gh repo create failed", ""
            created = f"created {path} on {where} (private); "
        else:
            return blame[-2000:] or "cannot reach that repository", ""
    elif r["out"].strip():
        return ("that repository is not empty: linking only targets empty "
                "repositories, so nothing can be overwritten"), ""

    a = run(["git", "-C", dest, "remote", "add", "origin", remote], timeout=10)
    if a["code"] != 0:
        return a["out"].strip() or "remote add failed", ""
    if helper:
        _scope_to_token(dest, helper)
    # Linked is pushable: the push below is the proof, and the Git view's
    # Push and the Artifacts tab read this record.
    grant_push(name, host, path.lower(), "token" if token else "key")
    if run(["git", "-C", dest, "rev-parse", "-q", "--verify", "HEAD"],
           timeout=10)["code"] != 0:
        return "", created + "remote set; nothing committed yet, so nothing was pushed"
    _step("pushing")
    p = run(["git", "-C", dest, *scope, "push", "-u", "origin", "HEAD"],
            timeout=1800, env=env, register=_register)
    if _aborted():
        # The remote stays either way: it is correct configuration, and a push
        # is the retryable part, from here or from any shell.
        return "stopped: the remote is set; the push did not finish", ""
    if p["code"] != 0:
        return created + "the remote was set, but the push failed:\n" \
            + p["out"].strip()[-2000:], ""
    branch = run(["git", "-C", dest, "symbolic-ref", "--short", "-q", "HEAD"],
                 timeout=10)["out"].strip() or "HEAD"
    return "", f"{created}pushed {branch}"


# ---------------------------------------------------------------------------
# the create dialog's one submit, and the sidebar's pins

def create_from_dialog(req, *, env, account, may_node):
    """The create dialog's one submit, once the server has let an
    administrator make a project: create(), then what the dialog chose
    besides. `account` is who made it (an account's name, or ""), and
    `may_node(name)` whether they may set its node, asked after they have
    taken it on. (payload, status)."""
    body, code = create(req, env=env)
    if code != 200 or not body.get("name"):
        return body, code
    name = body["name"]
    # Taken on by whoever made it (the operator, 24 Sep), before the
    # writes below: they ask whether this account may work on the
    # project, and an administrator's new one was not on their list, so
    # it came out read-only to them and the node the dialog picked was
    # quietly not set. A clone's directory exists from here, while the
    # clone itself runs on; one that fails leaves a name on the list that
    # matches nothing.
    if account:
        take_on(account, name)
        # ...and owns it (membership.py).
        import membership
        membership.on_create(name, account)
    # The node it was made for, when the dialog offered one: the same
    # write the settings dialog makes, so a project is born able to
    # build and start a session rather than needing a second dialog
    # first (16 Sep). Refused the way the settings dialog refuses it.
    nid = str(req.get("node") or "").strip()
    if nid and may_node(name):
        r = set_prefs(name, node=nid)
        if r.get("error"):
            body["note"] = f"{body.get('note') or 'ready'}; node not set: {r['error']}"
    # ...and the gates (roadmap #27), the design's among them, when the dialog offered them:
    # the same write the settings dialog makes, so what a session may
    # enter into the notebook is decided where the project is made.
    gate = req.get("gate")
    if isinstance(gate, dict) and gate:
        r = set_prefs(name, gate=gate)
        if r.get("error"):
            body["note"] = f"{body.get('note') or 'ready'}; gates not set: {r['error']}"
    # ...and whether a session may run its container, the fifth of them
    # on the dialog, so a session can create the first one by request.
    devbuild = req.get("devbuild")
    if devbuild and devbuild != "deny":
        r = set_prefs(name, devbuild=str(devbuild))
        if r.get("error"):
            body["note"] = f"{body.get('note') or 'ready'}; Run its container not set: {r['error']}"
    # ...and the rest of Claude may, each only where it differs from the
    # default a project gets anyway.
    for key, dflt, label in (("sign", "ask", "Sign a build"), ("keys", "ask", "Manage signing keys"),
                             ("release", "ask", "Tag and publish a release"),
                             ("report", "auto", "Report BuilderBot bugs")):
        v = req.get(key)
        if v and v != dflt:
            r = set_prefs(name, **{key: str(v)})
            if r.get("error"):
                body["note"] = f"{body.get('note') or 'ready'}; {label} not set: {r['error']}"
    # Pinned on arrival, once anything has ever been pinned. Without this a
    # project made while a pins file exists is absent from it, so it lands
    # on disk and never reaches the sidebar: created, and apparently gone.
    # No file still means "all of them", so there is nothing to write then
    # and writing one would turn the first create into an unasked-for
    # decision about every other project.
    with lock:
        try:
            pin_new_project(name)
        except OSError:
            pass                  # the project exists; the sidebar is not
                                  # worth failing the create over
    return body, code


# Which projects the sidebar card shows. A THIRD axis, independent of the
# locks and the settings: pinning says nothing about what may run, only about
# what is worth looking at from the sidebar. Everything unpinned is still on
# the Projects tab, whole and with every control.
#
# pinned-projects.json and not pinned-commands.json, which is the command
# pin's (macros.py), as are its load_pins, save_pins, /api/pin and the
# page's setPinned. Taking all five once split this feature across two
# files: the constant resolved to theirs, the functions to mine, and project
# names were written into pinned-commands.json while nothing went red,
# because the command pin had no test (bug #20).
def _pins_file():
    return STATE / "pinned-projects.json"


def _load_pins():
    """Every account's pinned set, {uid: [names]}. The file was one flat list
    for everybody until 27 Sep; read as everyone's default under "*" once,
    and written back keyed by account the first time anybody pins."""
    try:
        v = json.loads(_pins_file().read_text())
    except (OSError, ValueError):
        return {}
    if isinstance(v, list):
        return {"*": sorted({x for x in v if isinstance(x, str)})}
    if not isinstance(v, dict):
        return {}
    return {k: sorted({x for x in names if isinstance(x, str)})
            for k, names in v.items() if isinstance(k, str) and isinstance(names, list)}


def load_project_pins(uid, fresh=False):
    """This account's pinned set, or None when it has never pinned anything
    and nobody's default stands. `fresh` is an account that starts with
    nothing pinned (users.starts_unpinned): its no-entry is the empty set,
    and the old everybody default under "*" is not its.

    None is not the same as empty and the difference decides what a fresh
    install looks like. No entry means this person has not had this thought
    yet, so every project is pinned and the card is what it always was; an
    empty LIST means they unpinned the last one on purpose, and a sidebar that
    quietly refilled itself would be arguing with them. The pins are the
    person's, not the controller's (the operator, 27 Sep): what is worth
    looking at from the sidebar is a question each account answers.
    """
    d = _load_pins()
    if fresh and str(uid or "") not in d:
        return []
    v = d.get(str(uid or ""), d.get("*"))
    return None if v is None else sorted(v)


def save_project_pins(uid, names):
    d = _load_pins()
    d[str(uid or "")] = sorted(set(names))
    write_json(_pins_file(), d)


def pin_new_project(name):
    """A project made after anything has been pinned is pinned for everyone
    who has a set: absent from theirs it would land on disk and never reach
    their sidebar, created and apparently gone. Nothing to write while no
    account has a set, since no file means all of them."""
    d = _load_pins()
    if not d:
        return
    write_json(_pins_file(), {k: sorted(set(v) | {name}) for k, v in d.items()})

def pin(uid, name, on, fresh=False):
    """Pin or unpin a project for one account, once the server has let a
    signed-in person: the pins are theirs. Unpinning something running a
    build leaves it running, and the Projects tab still has every button.

    The first unpin has to write the whole current set, not just remove
    one: until then there is no entry, which means "all of them", and
    saving a single removal would have read as "only this one is pinned".
    (payload, status)."""
    try:
        here = {d.name for d in WORKSPACE.iterdir()
                if d.is_dir() and not d.name.startswith(".")}
    except OSError:
        here = set()
    if name not in here:
        return {"error": f"unknown project: {name}"}, 400
    with lock:
        pins = load_project_pins(uid, fresh)
        names = here.copy() if pins is None else set(pins)
        names.add(name) if on else names.discard(name)
        try:
            save_project_pins(uid, names)
        except OSError as e:
            return {"error": f"could not save: {e}"}, 500
    return {"pinned": sorted(names)}, 200


# ---------------------------------------------------------------------------
# the locks

# Locked projects live on the /config volume so the list survives the image
# updates this container is built to expect. bb-tty reads the same file; a
# rule only the dashboard honored would be advice, since the terminal URL is
# reachable on its own.
#
# There used to be two of these. "Excluded" meant "this is not a project, stop
# showing it work" and locked meant "this one is mine to run", and the operator
# found the distinction too fine to be worth two buttons that looked alike and
# sat next to each other. Locked is the survivor and it carries the whole
# meaning now: no session starts here, the notebook is readable but not
# writable, and nothing may be created in the project on Claude's behalf. What
# it does NOT touch is everything the operator does themselves: the artifacts,
# a dev instance, the findings and their history.
def _locks_file():
    return STATE / "locked-projects.json"


def load_locks():
    try:
        v = json.loads(_locks_file().read_text())
        return sorted({x for x in v if isinstance(x, str)}) if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def save_locks(names):
    write_json(_locks_file(), sorted(set(names)))


# What a locked project refuses, in one place.
#
# The button being hidden is not the rule; this is. The dashboard's own URLs
# are reachable without it, so a lock enforced only by a missing control is
# advice. That is the same reasoning that put the lock file where bb-tty can
# read it rather than keeping it in the page.
#
# READS are never refused, and the list of what stays is the point of the
# feature: the notebook opens, the findings and their history are there, the
# artifacts list and a dev instance still work. What goes is everything that
# writes on Claude's behalf: the notebook's three tabs.
LOCKED_REFUSAL = ("{name} is locked: yours to run. Unlock it to change its "
                  "notebook; everything you read here still works while it "
                  "stays locked.")


def locked_out(name):
    """The refusal for a write into a locked project, or None."""
    if name and name in set(load_locks()):
        return {"error": LOCKED_REFUSAL.format(name=name)}
    return None


def lock_verb(name, on):
    """Lock or unlock a project, once the server has let this person: keep
    it, stop Claude running in it. A name-checked write, and the
    enforcement is deliberately not this function's: bb-tty reads the
    file, because a rule only this UI honors is a suggestion when the ttyd
    URL is reachable directly. (payload, status)."""
    try:
        here = {d.name for d in WORKSPACE.iterdir() if d.is_dir()}
    except OSError:
        here = set()
    if name not in here:
        return {"error": f"unknown project: {name}"}, 400
    with lock:
        names = set(load_locks())
        names.add(name) if on else names.discard(name)
        try:
            save_locks(names)
        except OSError as e:
            return {"error": f"could not save: {e}"}, 500
    # A lock that waits for the current session to end is a lock that
    # did not take, and the button does not say that.
    killed = None
    sess = claude_session(name)
    if on and sess in {x["name"] for x in live_sessions()}:
        run(["tmux", "kill-session", "-t", sess], timeout=10)
        killed = sess
    return {"locked": sorted(names), "killed": killed}, 200


def auth_answer(name):
    """What credential this project's remote uses, and what else it could,
    for the rename dialog of a project the server has let this account
    see. Asked when the dialog opens rather than carried on the status
    poll: answering it means running `git remote get-url` in the project,
    and one subprocess per dialog is nothing where one per project per poll
    is not. (payload, status)."""
    if not PROJECT_NAME.fullmatch(name or ""):
        return {"error": "unknown project"}, 400
    d = WORKSPACE / name
    if not d.is_dir():
        return {"error": "unknown project"}, 400
    return auth_options(name, d), 200


def _stored_token(project):
    """The token this project's credential file holds, decoded, or "". Read
    for the host's API in auth_test and never sent anywhere else."""
    try:
        line = (STATE / "gitcreds" / project).read_text().strip().splitlines()[0]
    except (OSError, IndexError):
        return ""
    m = re.match(r"https?://[^:@/]*:([^@]*)@", line)
    return urllib.parse.unquote(m.group(1)) if m else ""


# What git and ssh print around every refusal, whatever it was: the line
# that says why is the one left (the host's "Permission denied", a key
# "marked as read only", a 403), not "and the repository exists."
_GIT_BOILERPLATE = re.compile(
    r"^(hint:|Warning: Permanently added|fatal: Could not read from remote repository"
    r"|Please make sure you have the correct access rights|and the repository exists"
    r"|To |error: failed to push some refs|Could not create directory .*\.ssh"
    r"|Failed to add the host to the list of known hosts)", re.I)


def _git_said(r):
    """The line of git's that says why, for a sentence."""
    said = [ln.strip() for ln in (r.get("err", "") + "\n" + r.get("out", "")).splitlines()
            if ln.strip() and not _GIT_BOILERPLATE.match(ln.strip())]
    why = [ln for ln in said if re.search(r"denied|read.only|error|not found|could not|unable|refused", ln, re.I)]
    pick = (why or said or [""])[0]
    return pick[:240] if pick else f"git said nothing (exit {r['code']})"


def auth_test(name, typed=""):
    """Can this project read and push with what it authenticates with now
    (the operator, 7 Oct)? (payload, status).

    git answers for every host and both credentials: `ls-remote` is the read
    and `push --dry-run` the write, which the host refuses at the
    receive-pack handshake when the key is read-only or the token cannot
    push, and which sends nothing. The pre-push hook is skipped, since a
    project cloned without push rights refuses there before the host is
    asked. A token is also put to the host's API (forges.token_access) for
    what git cannot see. `typed` is a token typed in the dialog and not
    saved: it is tried in its place, over https, from a file of its own
    that is gone when this returns.
    """
    if not PROJECT_NAME.fullmatch(name or ""):
        return {"error": "unknown project"}, 400
    d = WORKSPACE / name
    if not d.is_dir():
        return {"error": "unknown project"}, 400
    url = origin_url(d)
    if not url:
        return {"error": "this project has no remote to test"}, 400
    # As written, not as get-url rewrites it through a url.insteadOf: the
    # host and the path are the ones a token is filed and asked under.
    written = run(["git", "-C", str(d), "config", "--get", "remote.origin.url"], timeout=15)
    url = written["out"].strip() if written["code"] == 0 and written["out"].strip() else url
    host, repo = forges.host_of(url), repo_path_of(url)
    forge = forges.forge_of(host)
    mode = remote_auth(d, name)
    remote, scope, tmp = "origin", [], None
    stored = token_target(name) or {}
    if typed:
        typed = typed.strip()
        bad = forges.token_ok(forge, typed)
        if bad:
            return {"error": bad}, 400
        if not repo or not host:
            return {"error": "could not read the repository from this project's remote"}, 400
        scheme = stored.get("scheme") or "https"
        fd, tmp = tempfile.mkstemp(prefix="bb-authtest-")
        q = lambda x: urllib.parse.quote(x, safe="")  # noqa: E731
        with os.fdopen(fd, "w") as fh:
            fh.write(f"{scheme}://{q(forge['user'] or 'oauth2')}:{q(typed)}@{stored.get('host') or host}\n")
        scope = ["-c", "credential.helper=", "-c", f"credential.helper=store --file={tmp}"]
        remote = f"{scheme}://{stored.get('host') or host}/{repo}.git"
        mode = "typed"
    what = {"ssh": "its deploy key", "https": "its access token", "typed": "the token typed here",
            "none": "no credential (Authentication is Disabled)"}.get(mode, "what its remote says")
    missing, notes = [], []
    env = _git_env()
    try:
        r = run(["git", "-C", str(d), *scope, "ls-remote", "--heads", "--", remote],
                timeout=60, env=env, split_err=True)
        can_read = r["code"] == 0
        if not can_read:
            said = _git_said(r)
            if mode == "ssh" and re.search(r"denied|not found|not appear", said, re.I):
                missing.append(f"read access for the deploy key: {said.rstrip('.')}. Add its public half under "
                               f"the repository's deploy keys on {forge['name']}")
            elif re.search(r"returned error: 403", said):
                # git's own line says only the number; this is what it means.
                missing.append(f"read access: {forge['name']} accepted the token and refused it this "
                               "repository (403). A fine-grained token has to list the repository with "
                               "Contents: Read and write, and an organization may have to approve it "
                               "under its Personal access tokens settings")
            else:
                missing.append(f"read access: {said}")
        has_head = run(["git", "-C", str(d), "rev-parse", "--verify", "-q", "HEAD"], timeout=15)["code"] == 0
        can_push = None
        if not has_head:
            notes.append("Nothing is committed yet, so a push could not be tried.")
        elif can_read:
            r = run(["git", "-C", str(d), *scope, "push", "--dry-run", "--no-verify", "--porcelain",
                     "--", remote, "HEAD:refs/heads/builderbot-access-check"],
                    timeout=60, env=env, split_err=True)
            can_push = r["code"] == 0
            if not can_push:
                said = _git_said(r)
                if mode == "ssh" and re.search(r"read.only|write access|denied", said, re.I):
                    missing.append(f"write access for the deploy key: {said.rstrip('.')}. On {forge['name']}, "
                                   "edit the key under the repository's deploy keys and allow write access")
                else:
                    missing.append(f"write access: {said}")
        tok = typed or (_stored_token(name) if mode == "https" else "")
        if tok and repo:
            got = forges.token_access(forge, stored.get("host") or host, tok, repo,
                                      stored.get("scheme") or "https")
            # The host's own answer says why a read was refused better than
            # git's line, so it takes that line's place; a refused push is
            # already said by git.
            why = [m for m in got["missing"] if m.startswith(("a token", "access to"))]
            if can_read is False and why:
                missing = [m for m in missing if not m.startswith("read access")]
            missing += [m for m in got["missing"] if not (can_push is False and m.startswith("write access"))]
            notes += got["notes"]
        if not may_push(name):
            notes.append("This project was set up without push rights, so a session's push is "
                         "refused here whatever the credential may do.")
    finally:
        if tmp:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
    return {"using": what, "mode": mode, "read": can_read, "push": can_push,
            "missing": missing, "notes": notes}, 200


def job_verb(act):
    """Stop the running project job, or clear the last one's outcome.
    (payload, status)."""
    if act == "abort":
        return abort(), 200
    if act == "dismiss":
        return dismiss(), 200
    return {"error": f"unknown action: {act}"}, 400
