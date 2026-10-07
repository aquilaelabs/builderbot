"""A node session's git push, fetch, pull and ls-remote, done on the controller
without trusting the session's repository (B148).

The project tree is on the projects share, and a session on a node can write
every file in it, .git/config and .git/hooks included. git runs what those
name: a hook, an ssh command, a credential helper, an fsmonitor, a pack
program. So this never runs git in that tree. Each project has a bare
repository of the controller's own under STATE/gitrelay, whose config only
this file writes. It borrows the tree's objects through alternates, takes the
tree's refs in by reading them as files, and does the network step there,
with the project's own credential helper and nothing the tree says about
programs.

What the tree needs afterwards (its remote-tracking refs, the objects a fetch
brought, the merge for a pull, the upstream a -u sets) comes back as `apply`,
and bb on the node does that as the session, in the session's own tree,
which is nothing the session could not do to it anyway.

The remote's address is still the tree's, read out of .git/config as data.
Two rules keep the controller's credentials where they belong: a project with
push rights reaches only the repository they were granted on, and a local
remote must be a repository on the projects share, which takes no
credentials at all.
"""
import contextlib
import fcntl
import os
import sys
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

# Its own directory on the path, so a test can load this file alone (git.mjs
# does) and still find statefile beside it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statefile  # noqa: E402

# Injected by configure().
STATE = None
WORKSPACE = None
push_record = None      # project -> {"repo", "host", "how"} or None
token_helper = None     # project -> "store --file=..." or ""
parse_url = None        # forges.parse
host_of = None          # forges.host_of: the real host behind an ssh alias
git_env = None          # projects._git_env: the environment every git job gets

VERBS = ("push", "fetch", "pull", "ls-remote")
FLAGS = frozenset({"-u", "--set-upstream", "--tags", "--follow-tags", "--delete", "-d",
                   "--dry-run", "-n", "--prune", "-p", "--all", "--force-with-lease",
                   "--ff-only", "--rebase", "--no-rebase", "--heads", "--porcelain",
                   "-v", "--verbose", "-q", "--quiet"})
# How a pull joins what it fetched to the branch: the node's half, so these
# never reach the controller's git.
PULL_ONLY = frozenset({"--ff-only", "--rebase", "--no-rebase"})
ARG = re.compile(r"[A-Za-z0-9._/:+~^@-]+")
OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
REMOTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
MAX_REFS = 50000
TIMEOUT = 170
# The programs a local remote runs on its side, with that repository's hooks
# and command-running config off: it is on the share, so it may be a
# repository a session made for the purpose.
PACK = ("git -c core.hooksPath=/dev/null -c core.fsmonitor=false -c core.alternateRefsCommand="
        " -c receive.denyCurrentBranch=refuse -c receive.autogc=false -c gc.auto=0 {}")


class Refused(Exception):
    """A sentence for the person who asked: why it did not run."""


def configure(*, state, workspace, push_record, token_helper, parse_url, host_of, git_env):
    globals().update(STATE=Path(state), WORKSPACE=Path(workspace), push_record=push_record,
                     token_helper=token_helper, parse_url=parse_url, host_of=host_of,
                     git_env=git_env)


# ---- reading the tree, as files --------------------------------------------

def ref_ok(name):
    """git check-ref-format's rules, for a name read out of somebody's tree,
    held to ASCII and without a double quote, so it can be written into a
    config file and sorted into packed-refs as bytes."""
    if (not isinstance(name, str) or not name.startswith("refs/") or len(name) > 255
            or not name.isascii() or name.endswith(("/", ".", ".lock"))):
        return False
    if ".." in name or "@{" in name or "//" in name or '"' in name:
        return False
    if any(c in name for c in " ~^:?*[\\\x7f") or any(ord(c) < 32 for c in name):
        return False
    return all(part and not part.startswith(".") and not part.endswith(".lock")
               for part in name.split("/")[1:])


def _wanted(name):
    return name.startswith(("refs/heads/", "refs/tags/", "refs/remotes/")) and ref_ok(name)


def _tree(project, cwd):
    """(common, gitdir) for the working tree `cwd` is in: the project's .git,
    and for a worktree its own directory under .git/worktrees."""
    root = (WORKSPACE / project).resolve()
    common = WORKSPACE / project / ".git"
    if common.is_symlink() or not common.is_dir():
        raise Refused(f"{project} is not a git repository")
    common = common.resolve()
    top = Path(cwd).resolve()
    stop = WORKSPACE.resolve()
    while not (top / ".git").exists() and not (top / ".git").is_symlink():
        if top in (stop, top.parent):
            raise Refused("this directory is not inside a git working tree")
        top = top.parent
    objects = (common / "objects").resolve()
    if objects.parent != common:
        raise Refused(f"{project}'s .git/objects is not a directory of its own")
    if top == root:
        return common, common
    dotgit = top / ".git"
    try:
        line = "" if dotgit.is_symlink() or not dotgit.is_file() else dotgit.read_text(errors="replace").strip()
    except OSError:
        line = ""
    if not line.startswith("gitdir: "):
        raise Refused("this worktree's .git does not name its repository")
    gd = Path(line[len("gitdir: "):].strip())
    gd = (gd if gd.is_absolute() else top / gd).resolve()
    if gd.parent != common / "worktrees" or not gd.is_dir():
        raise Refused(f"this worktree does not belong to {project}'s repository")
    return common, gd


def head(gitdir):
    """The branch HEAD names, as refs/heads/<name>, or the commit it holds."""
    try:
        v = (Path(gitdir) / "HEAD").read_text(errors="replace").strip()
    except OSError:
        raise Refused("the repository has no HEAD") from None
    if v.startswith("ref: ") and v[5:].strip().startswith("refs/heads/") and ref_ok(v[5:].strip()):
        return v[5:].strip()
    if OID.fullmatch(v):
        return v
    raise Refused("the repository's HEAD is neither a branch nor a commit")


def refs(common):
    """{refname: object id} for the branches, tags and remote-tracking refs,
    loose over packed, the way git reads them. Symbolic refs are left out."""
    common = Path(common)
    out = {}
    packed = common / "packed-refs"
    try:
        if packed.is_file() and not packed.is_symlink():
            if packed.stat().st_size > 64 << 20:
                raise Refused("this repository's packed-refs is too large for the relay to read")
            for line in packed.read_text(errors="replace").splitlines():
                if not line or line[0] in "#^":
                    continue
                oid, _, name = line.partition(" ")
                if OID.fullmatch(oid) and _wanted(name):
                    out[name] = oid
    except OSError:
        pass
    for sub in ("heads", "tags", "remotes"):
        for dirpath, _dirs, files in os.walk(common / "refs" / sub):
            for fn in files:
                p = Path(dirpath) / fn
                name = p.relative_to(common).as_posix()
                if p.is_symlink() or not _wanted(name):
                    continue
                try:
                    v = p.read_text(errors="replace").strip()
                except OSError:
                    continue
                if OID.fullmatch(v):
                    out[name] = v
                if len(out) > MAX_REFS:
                    raise Refused("this repository has more refs than the relay reads")
    return out


def _env():
    base = git_env() if git_env else dict(os.environ)
    env = {k: v for k, v in base.items()
           if not k.startswith(("GIT_CONFIG", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX",
                                "GIT_OBJECT", "GIT_ALTERNATE", "GIT_NAMESPACE",
                                "GIT_COMMON_DIR", "GIT_CEILING", "GIT_PROTOCOL"))
           and k not in ("DASHBOARD_AUTH", "GIT_ASKPASS", "SSH_ASKPASS")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def config(common):
    """The tree's .git/config as data, {key: [values]}, read by git's own
    parser in --file mode with includes off: nothing in it is followed or
    run, and only a handful of keys are ever looked at."""
    f = Path(common) / "config"
    if f.is_symlink() or not f.is_file():
        return {}
    try:
        r = subprocess.run(["git", "config", "--file", str(f), "--no-includes", "--null", "--list"],
                           capture_output=True, timeout=20, check=False, cwd=str(STATE), env=_env())
    except (OSError, subprocess.SubprocessError):
        raise Refused("the repository's config cannot be read") from None
    out = {}
    for entry in r.stdout.decode(errors="replace").split("\0"):
        key, _, value = entry.partition("\n")
        if key:
            out.setdefault(key, []).append(value)
    return out


def _last(cfg, key):
    vals = cfg.get(key) or []
    return vals[-1] if vals else ""


# ---- where a remote may point --------------------------------------------

def address(project, name, url):
    """("net", url) for an address that takes credentials, ("local", path)
    for a repository on the projects share; Refused for anything else."""
    url = (url or "").strip()
    if not url or url.startswith("-") or any(c.isspace() or ord(c) < 32 for c in url):
        raise Refused(f"remote {name} has an address the relay will not use")
    got = parse_url(url)
    if got:
        rec = push_record(project)
        if isinstance(rec, dict) and rec.get("repo"):
            host = (host_of(url) or got["host"] or "").lower()
            want = (rec.get("host") or "").lower()
            if not want:
                # Fail CLOSED on a credential boundary. The address in the
                # tree is a session's to rewrite, so the host is half of what
                # says this remote is the one the rights were granted on:
                # without it, a matching path at any host in the world would
                # be handed the project's token. Both places that grant rights
                # record a host, so this is an old record rather than a
                # reachable state, and re-granting is one press.
                raise Refused(
                    f"{project}'s push rights name a repository but not a host, so the relay "
                    "cannot tell this remote from one with the same path somewhere else. "
                    "Re-grant them in the project's remote dialog, which records both")
            if got["path"].lower() != str(rec["repo"]).lower() or host != want:
                raise Refused(
                    f"remote {name} points at {got['host']}/{got['path']}, but {project}'s push rights "
                    f"were granted on {rec.get('host') or 'its host'}/{rec['repo']}, and the controller's "
                    "credentials reach only that repository. A public remote needs none: fetch it with "
                    "plain git on the node; a private one that is another project here is read by "
                    f"adding that project to {project}'s Reads, then from /workspace/NAME in a new session")
        return "net", url
    path = url[len("file://"):] if url.startswith("file://") else url
    if path.startswith("/"):
        p = Path(path).resolve()
        # The caller's own project or a worktree of it, and no other: a
        # local remote naming another project fetched its history into this
        # one and pushed refs into it, as the controller, around the rule
        # that a session sees its own project only (the audit of 26 Sep).
        own = [(WORKSPACE / project).resolve(), (WORKSPACE / ".worktrees" / project).resolve()]
        mine = any(p == o or o in p.parents for o in own)
        root = WORKSPACE.resolve()
        on_share = root in p.parents
        bare = (p / "HEAD").is_file() and not (p / ".git").exists()
        # A bare repository the share hosts (a project's origin with no
        # forge) is anybody's to push to; a working tree is a project's,
        # and so is anything inside one.
        inside_tree = any((a / ".git").exists() for a in [p, *p.parents] if root in a.parents)
        if on_share and (mine or (bare and not inside_tree)):
            return "local", str(p)
        if on_share and inside_tree:
            raise Refused(f"remote {name} is another project's repository on the share: a session reaches "
                          f"its own project and its worktrees only")
        raise Refused(f"remote {name} is a local path that is not a repository on the projects share")
    raise Refused(f"remote {name}'s address is not https, ssh or a repository on the projects share")


# ---- the controller's own repository ---------------------------------------

def _q(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _atomic(path, text):
    """All of `text` or none of it, through statefile.write_text."""
    statefile.write_text(path, text)


def _base():
    base = STATE / "gitrelay"
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o700)
    (base / "no-hooks").mkdir(exist_ok=True)
    return base


def _shadow(project, sha256):
    base = _base()
    d = base / (f"{project}.sha256.git" if sha256 else f"{project}.git")
    if not (d / "HEAD").is_file() or not (d / "objects").is_dir():
        shutil.rmtree(d, ignore_errors=True)
        r = subprocess.run(["git", "init", "--bare", "--quiet",
                            *(["--object-format=sha256"] if sha256 else []), str(d)],
                           capture_output=True, text=True, timeout=30, check=False,
                           cwd=str(base), env=_env())
        if r.returncode:
            raise Refused(f"the controller could not make its copy of {project}'s repository: "
                          f"{(r.stderr or '').strip()[:200]}")
    return d


def _write_config(d, project, sha256, name, kind, url, upstreams):
    lines = ["[core]", f"\trepositoryformatversion = {1 if sha256 else 0}", "\tbare = true",
             f"\thooksPath = {_q(STATE / 'gitrelay' / 'no-hooks')}", "\tfsmonitor = false"]
    if sha256:
        lines += ["[extensions]", "\tobjectformat = sha256"]
    lines += ["[gc]", "\tauto = 0", "[maintenance]", "\tauto = false",
              "[fetch]", "\trecurseSubmodules = false",
              '[protocol "ext"]', "\tallow = never",
              "[credential]", '\thelper = ""']
    helper = token_helper(project) if kind == "net" else ""
    if helper:
        lines.append(f"\thelper = {_q(helper)}")
    lines += [f'[remote "{name}"]', f"\turl = {_q(url)}",
              f"\tfetch = {_q(f'+refs/heads/*:refs/remotes/{name}/*')}",
              "\tfollowRemoteHEAD = never"]
    if kind == "local":
        lines += [f"\tuploadpack = {_q(PACK.format('upload-pack'))}",
                  f"\treceivepack = {_q(PACK.format('receive-pack'))}"]
    for branch, merge in sorted(upstreams.items()):
        lines += [f'[branch "{branch}"]', f"\tremote = {_q(name)}", f"\tmerge = {_q(merge)}"]
    _atomic(d / "config", "\n".join(lines) + "\n")


def _mirror(d, common, tree_refs, head_ref):
    """The tree's refs and HEAD, as the controller's copy's own, and its
    objects borrowed through alternates rather than copied."""
    shutil.rmtree(d / "refs", ignore_errors=True)
    for sub in ("heads", "tags"):
        (d / "refs" / sub).mkdir(parents=True, exist_ok=True)
    # Byte order, which the sorted trait promises: every name is ASCII.
    _atomic(d / "packed-refs", "# pack-refs with: sorted \n"
            + "".join(f"{tree_refs[n]} {n}\n" for n in sorted(tree_refs)))
    _atomic(d / "HEAD", f"ref: {head_ref}\n" if head_ref.startswith("refs/") else f"{head_ref}\n")
    info = d / "objects" / "info"
    info.mkdir(parents=True, exist_ok=True)
    _atomic(info / "alternates", f"{Path(common) / 'objects'}\n")


def _git(d, *args, stdin=None, timeout=TIMEOUT):
    try:
        r = subprocess.run(["git", f"--git-dir={d}", *args], cwd=str(d), input=stdin,
                           capture_output=True, timeout=timeout, check=False, env=_env())
    except subprocess.TimeoutExpired:
        return {"code": 124, "out": "", "err": f"git {args[0]} took longer than {timeout} seconds\n"}
    except OSError as e:
        return {"code": 1, "out": "", "err": f"{e}\n"}
    return {"code": r.returncode, "out": r.stdout.decode(errors="replace"),
            "err": r.stderr.decode(errors="replace")}


def _shadow_refs(d):
    """The copy's refs after git ran, symbolic ones left out as they are in
    refs(): a fetch may point <remote>/HEAD at a branch, and moving that
    through the tree's own symbolic ref would move the branch twice."""
    r = _git(d, "for-each-ref", "--format=%(objectname) %(refname) %(symref)", timeout=60)
    out = {}
    for line in r["out"].splitlines():
        oid, _, rest = line.partition(" ")
        name, _, symref = rest.partition(" ")
        if OID.fullmatch(oid) and _wanted(name) and not symref.strip():
            out[name] = oid
    return out


def _upstreams(cfg, name):
    """{branch: merge ref} for the tree's branches whose upstream is `name`."""
    out = {}
    for key, vals in cfg.items():
        if key.startswith("branch.") and key.endswith(".remote") and vals and vals[-1] == name:
            branch = key[len("branch."):-len(".remote")]
            merge = _last(cfg, f"branch.{branch}.merge")
            if ref_ok(f"refs/heads/{branch}") and ref_ok(merge):
                out[branch] = merge
    return out


@contextlib.contextmanager
def _lock(project):
    f = open(_base() / f"{project}.lock", "w")
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise Refused("another git operation on this project is still running") from None
                time.sleep(0.2)
        yield
    finally:
        f.close()


def _old_bundles(common):
    d = Path(common) / "bb-relay"
    with contextlib.suppress(OSError):
        for p in d.iterdir():
            if p.suffix == ".bundle" and time.time() - p.stat().st_mtime > 3600:
                p.unlink()


def _lfs(root):
    with contextlib.suppress(OSError):
        return "filter=lfs" in (root / ".gitattributes").read_text(errors="replace")
    return False


# ---- the verbs --------------------------------------------------------------

def run(project, cwd, verb, args):
    """{code, out, err, apply?} for one relayed verb, or {error} when it
    was refused before any git ran."""
    try:
        return _run(project, cwd, verb, [str(a) for a in args])
    except Refused as e:
        return {"error": str(e)}


def tree_refs(project, cwd):
    """(head, main, branches) for the working tree a relayed verb would run
    in: the branch it is on, which of main or master this repository has, and
    the branches it holds.

    The tree matters, not the project: a session works in a worktree as
    readily as in the project directory, and its HEAD lives in that
    worktree's own directory. Reading the project's HEAD instead would judge
    a push against a branch nobody was standing on.
    """
    common, gitdir = _tree(project, cwd)
    have = refs(common)
    local = {r[len("refs/heads/"):] for r in have if r.startswith("refs/heads/")}
    here = head(gitdir).removeprefix("refs/heads/")
    return here, next((b for b in ("main", "master") if b in local), "main"), local


def push_plan(args, head):
    """What a push would WRITE on the remote, read off its arguments.

        {"dests": [branch, ...], "deletes": [branch, ...],
         "every": bool, "tags": bool}

    The policy is about refs, not about verbs (B191): "a session may push its
    branch" has to be judged against the ref the push would land on, and until
    this existed the only thing looked at was whether the word `main` appeared
    anywhere in the arguments. Everything else went through, so a session could
    write another branch or delete one while the setting said its own branch.

    git's own reading, kept deliberately narrow: the first positional is the
    remote and the rest are refspecs, a refspec's destination is the half after
    the colon, ":name" and --delete both remove, and no refspec at all means
    the branch HEAD is on, which is what push.default gives for `simple` and
    `current` alike. A leading + forces and is stripped for the comparison,
    since forcing your own branch is a push and forcing somebody else's is the
    thing being refused either way.
    """
    flags = [a for a in args if a in FLAGS]
    pos = [a for a in args if a not in FLAGS]
    specs = pos[1:]                      # pos[0] is the remote
    plan = {"dests": [], "deletes": [], "every": "--all" in flags,
            "tags": bool({"--tags", "--follow-tags"} & set(flags))}
    dashd = bool({"--delete", "-d"} & set(flags))

    def short(r):
        return r.removeprefix("refs/heads/")

    for s in specs:
        s = s[1:] if s.startswith("+") else s
        src, sep, dst = s.partition(":")
        if dashd:
            # `--delete X` takes the ref plainly, and `--delete a:b` is not a
            # thing git accepts, so the source half is the name either way.
            plan["deletes"].append(short(src or dst))
        elif sep and not src:
            plan["deletes"].append(short(dst))               # ":name" removes it
        else:
            d = short(dst if sep else src)
            plan["dests"].append(head if d in ("", "HEAD") else d)
    if not specs and not plan["every"] and not plan["tags"]:
        plan["dests"].append(head)
    return plan


def bad_args(args):
    """Why these arguments are refused, or "" when they are not: remote names
    and refspecs by shape, and a short list of plain flags by name. git takes
    options that run a program, so everything else stops here."""
    for a in args:
        a = str(a)
        if a in FLAGS:
            continue
        if a.startswith("-"):
            return (f"bb git: '{a}' is not accepted: only remote names, refspecs and a few "
                    "plain flags reach the controller's git")
        if not ARG.fullmatch(a):
            return f"bb git: '{a}' is not a remote name or refspec"
    return ""


def _run(project, cwd, verb, args):
    if verb not in VERBS:
        raise Refused(f"bb git takes {', '.join(VERBS)} or policy; plain git does everything else")
    why = bad_args(args)
    if why:
        raise Refused(why)
    flags = [a for a in args if a in FLAGS]
    pos = [a for a in args if a not in FLAGS]
    common, gitdir = _tree(project, cwd)
    if (common / "reftable").exists():
        raise Refused("this repository keeps its refs in reftable, which the relay does not read")
    cfg = config(common)
    head_ref = head(gitdir)
    tree_refs = refs(common)
    sha256 = (_last(cfg, "extensions.objectformat").lower() == "sha256"
              or any(len(v) == 64 for v in tree_refs.values()))
    branch = head_ref[len("refs/heads/"):] if head_ref.startswith("refs/heads/") else ""
    name = pos[0] if pos else (_last(cfg, f"branch.{branch}.remote") if branch else "") or "origin"
    if not REMOTE.fullmatch(name):
        raise Refused(f"'{name}' is not the name of a remote: name one the repository has, such as origin")
    url = _last(cfg, f"remote.{name}.url")
    if not url:
        raise Refused(f"this repository has no remote named {name}")
    kind, where = address(project, name, url)
    if verb == "push" and _lfs(WORKSPACE / project):
        raise Refused("this repository stores files with Git LFS, whose uploads run as a hook the "
                      "relay does not run: push it from the Git view")
    merge_ref = ""
    if verb == "pull":
        if len(pos) > 2:
            raise Refused("bb git pull takes a remote and at most one branch")
        if len(pos) == 2:
            merge_ref = f"refs/remotes/{name}/{pos[1]}"
        elif not branch:
            raise Refused("HEAD is not on a branch: name the one to pull, as in bb git pull origin main")
        else:
            up = _last(cfg, f"branch.{branch}.merge")
            if not up.startswith("refs/heads/"):
                raise Refused(f"{branch} has no upstream to pull: name it, as in bb git pull {name} {branch}")
            merge_ref = f"refs/remotes/{name}/{up[len('refs/heads/'):]}"
        if not ref_ok(merge_ref):
            raise Refused(f"'{merge_ref}' is not a branch name git accepts")
    with _lock(project):
        d = _shadow(project, sha256)
        _write_config(d, project, sha256, name, kind, where, _upstreams(cfg, name))
        _mirror(d, common, tree_refs, head_ref)
        _old_bundles(common)
        net = [f for f in flags if f not in PULL_ONLY]
        if verb == "ls-remote":
            return _git(d, "ls-remote", *net, name, *pos[1:])
        if verb == "push":
            r = _git(d, "push", *net, name, *pos[1:])
        elif verb == "fetch":
            r = _git(d, "fetch", *net, name, *pos[1:])
        else:
            r = _git(d, "fetch", *net, name)
        dry = verb == "push" and ("--dry-run" in flags or "-n" in flags)
        if r["code"] != 0 or dry:
            return r
        after = _shadow_refs(d)
        apply = {}
        changes = [[n, after.get(n, "")] for n in sorted(set(tree_refs) | set(after))
                   if tree_refs.get(n) != after.get(n)]
        # A branch checked out here is the node's to move, with its files:
        # a fetch into it is not carried back.
        kept = [c for c in changes if c[0] != head_ref]
        if len(kept) != len(changes):
            r["err"] += f"not moving {branch}, which is checked out in this tree\n"
        if kept:
            apply["refs"] = kept
        if verb in ("fetch", "pull") and any(v for _, v in kept):
            wanted = [n for n, v in kept if v]
            haves = sorted(set(tree_refs.values()))
            path = common / "bb-relay" / f"{secrets.token_hex(8)}.bundle"
            path.parent.mkdir(exist_ok=True)
            b = _git(d, "bundle", "create", "--quiet", str(path), "--stdin",
                     stdin=("\n".join(wanted + [f"^{h}" for h in haves]) + "\n").encode())
            if b["code"] == 0 and path.is_file():
                apply["bundle"] = str(path)
            elif "empty bundle" not in b["err"]:
                with contextlib.suppress(OSError):
                    path.unlink()
                return {"code": 1, "out": r["out"], "err": r["err"] + b["err"]
                        + "the fetched objects could not be handed to this tree\n"}
        if verb == "push" and ("-u" in flags or "--set-upstream" in flags):
            now = _upstreams(config(d), name)
            before = _upstreams(cfg, name)
            ups = [[b, name, m] for b, m in sorted(now.items()) if before.get(b) != m]
            if ups:
                apply["upstream"] = ups
        if verb == "pull":
            if merge_ref not in after:
                return {"code": 1, "out": r["out"],
                        "err": r["err"] + f"{name} has no branch {merge_ref.split('/', 3)[3]}\n"}
            mode = ("ff-only" if "--ff-only" in flags else "rebase" if "--rebase" in flags
                    else "merge" if "--no-rebase" in flags else "")
            apply["merge"] = {"ref": merge_ref, "mode": mode, "branch": branch}
        if apply:
            r["apply"] = apply
        return r
