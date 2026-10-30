"""What an agent may do on a project's git host (R188), and the doing of it.

Three things, each built on the one before:

  * **the abilities**, one table (ABILITIES): reading the code, pushing,
    pull requests, merging, issues, CI runs and their logs, releases, each
    with what it needs from a token on GitHub, GitLab and Gitea. Some are
    named and not offered, with why; docs/git-hosts.md is this table.
  * **the measure**: what the project's own token may do, asked of the
    host without changing anything. A read is a GET; a write is a request
    the host refuses for its content when the token may make it (an issue
    with no title answers 422) and refuses outright when it may not (403),
    so nothing ever lands. Kept per project, with when it was taken.
  * **the relay**: `bb forge VERB`, a table of fixed verbs run here with
    the token, which never reaches a node (the MACROS rule: no command
    strings). Each verb names its ability; one the token lacks is refused
    with what to enable, and the project's own override (Permissions, On
    the git host) may take any ability away whatever the token allows.

The verbs are one set on every host: GitHub's API, which Gitea and Forgejo
speak with a few differences, and GitLab's own words for the same things
(a merge request, a pipeline, a note).
"""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import forges

STATE = None
write_json = None
# projects.forge_target, handed over by the server: name -> {forge, host,
# repo, scheme, token} or {error}.
target_of = None
# prefs.get, for the project's override.
prefs_of = None


def configure(*, state, write_json, target, prefs_get):     # noqa: A002 - injected
    globals().update(STATE=Path(state), write_json=write_json, target_of=target, prefs_of=prefs_get)


# ---- the abilities ---------------------------------------------------------
#
# `gh` is the fine-grained permission and level, `classic` the classic
# token's scope, `gitlab` and `gitea` theirs. `verbs` are bb forge's verbs
# that use it ("" for one used another way, said in `how`). `default` is the
# project's override until somebody changes it: allow, except merging, which
# lands work on a branch somebody else may protect by hand.
ABILITIES = (
    {"id": "code_read", "label": "Read the code and its history",
     "gh": ("Contents", "read"), "classic": "repo, or public_repo for a public repository",
     "gitlab": "read_repository", "gitea": "read:repository", "how": "git fetch and pull (bb git)",
     "verbs": (), "default": "allow"},
    {"id": "push", "label": "Push branches",
     "gh": ("Contents", "write"), "classic": "repo", "gitlab": "write_repository",
     "gitea": "write:repository", "how": "bb git push, under Permissions: Pushing",
     "verbs": (), "default": "allow"},
    {"id": "workflows", "label": "Change CI workflow files",
     "gh": ("Workflows", "write"), "classic": "workflow", "gitlab": "write_repository",
     "gitea": "write:repository", "how": "a push that touches .github/workflows",
     "verbs": (), "default": "allow"},
    {"id": "pr_read", "label": "Read pull requests",
     "gh": ("Pull requests", "read"), "classic": "repo", "gitlab": "read_api", "gitea": "read:repository",
     "how": "", "verbs": ("pr list", "pr view"), "default": "allow"},
    {"id": "pr_write", "label": "Open, update, comment on and review pull requests",
     "gh": ("Pull requests", "write"), "classic": "repo", "gitlab": "api", "gitea": "write:repository",
     "how": "", "verbs": ("pr create", "pr comment", "pr review", "pr close"), "default": "allow"},
    {"id": "merge", "label": "Merge pull requests",
     "gh": ("Pull requests", "write") , "also": ("Contents", "write"), "classic": "repo", "gitlab": "api",
     "gitea": "write:repository", "how": "", "verbs": ("pr merge",), "default": "deny"},
    {"id": "issues_read", "label": "Read issues",
     "gh": ("Issues", "read"), "classic": "repo", "gitlab": "read_api", "gitea": "read:issue",
     "how": "", "verbs": ("issue list", "issue view"), "default": "allow"},
    {"id": "issues_write", "label": "Open, comment on, label and close issues",
     "gh": ("Issues", "write"), "classic": "repo", "gitlab": "api", "gitea": "write:issue",
     "how": "", "verbs": ("issue create", "issue comment", "issue close", "issue label"), "default": "allow"},
    {"id": "actions_read", "label": "Read CI runs and their logs",
     "gh": ("Actions", "read"), "classic": "repo", "gitlab": "read_api", "gitea": "read:repository",
     "how": "", "verbs": ("run list", "run view", "run log"), "default": "allow"},
    {"id": "actions_write", "label": "Rerun and start CI workflows",
     "gh": ("Actions", "write"), "classic": "repo, and workflow to start one", "gitlab": "api",
     "gitea": "write:repository", "how": "", "verbs": ("run rerun", "run dispatch"), "default": "allow"},
    {"id": "releases_read", "label": "Read releases",
     "gh": ("Contents", "read"), "classic": "repo", "gitlab": "read_api", "gitea": "read:repository",
     "how": "", "verbs": ("release list", "release view"), "default": "allow"},
    {"id": "releases_write", "label": "Publish and edit releases",
     "gh": ("Contents", "write"), "classic": "repo", "gitlab": "api", "gitea": "write:repository",
     "how": "bb version release, under Agents may: Tag and publish a release", "verbs": (), "default": "allow"},
)
BY_ID = {a["id"]: a for a in ABILITIES}

# Named so the docs and the dialog can say them, and never offered: each is
# the person's own guard, a credential, or the repository's existence.
NOT_OFFERED = (
    ("Delete, transfer, archive or rename the repository, or change its visibility",
     "Administration: the repository's existence is the person's"),
    ("Branch protection and rulesets", "Administration: the person's guard against the agent itself"),
    ("Collaborators, teams and organization members", "Administration and Members: who may reach the work"),
    ("Secrets, variables, deploy keys and webhooks",
     "a session never handles a credential, and a webhook sends the work elsewhere"),
    ("Billing, the account's settings and its keys", "the account is the person's"),
)


def defaults():
    """{ability: allow|deny}, every ability at its default."""
    return {a["id"]: a["default"] for a in ABILITIES}


def needs(ab, kind):
    """What to enable for one ability on one host, as a sentence."""
    a = BY_ID[ab]
    if kind == "github":
        gh = f"{a['gh'][0]}: {'Read and write' if a['gh'][1] == 'write' else 'Read-only'}"
        if a.get("also"):
            gh += f" and {a['also'][0]}: Read and write"
        return f"{gh} (a fine-grained token; on a classic one, {a['classic']})"
    if kind == "gitlab":
        return f"the {a['gitlab']} scope"
    if kind == "gitea":
        return f"the {a['gitea']} scope"
    return "nothing this host can be asked about"


# ---- talking to the host ---------------------------------------------------

def _call(t, method, path, data=None, raw=False):
    """One request to the project's host: (status, body, headers). Status 0
    is a host that could not be reached. `raw` keeps the body as text (a
    job's log)."""
    base = forges.api_base(t["forge"], t["host"], t["scheme"])
    url = path if path.startswith("https://") else base + path
    headers = {"User-Agent": "BuilderBot", **forges._auth(t["forge"]["kind"], t["token"])}
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with forges._OPENER.open(req, timeout=30) as r:
            got = r.read(4_000_000 if raw else 2_000_000)
            if raw:
                return r.status, got.decode("utf-8", "replace"), dict(r.headers)
            return r.status, (json.loads(got) if got.strip() else {}), dict(r.headers)
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read(20000) or b"{}")
        except (ValueError, OSError):
            j = {}
        return e.code, j, dict(e.headers or {})
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, {"message": f"could not be reached: {e}"}, {}


def _h(headers, name):
    return {k.lower(): v for k, v in (headers or {}).items()}.get(name.lower())


def _write_probe(code):
    """A write probe's answer read: a 422 (or a 404 for a thing that is not
    there) means the token was let through to the content; 401 and 403 mean
    it was not."""
    if code in (401, 403):
        return False
    if code in (404, 409, 422):
        return True
    return None


# ---- the measure -----------------------------------------------------------

def _keep_path(project):
    return STATE / "forge-access" / f"{project}.json"


def kept(project):
    """The last measure for this project, or None."""
    try:
        return json.loads(_keep_path(project).read_text())
    except (OSError, ValueError):
        return None


def measure(project, t=None):
    """What the project's token may do now, asked of the host without
    changing anything, kept, and returned: {at, host, kind, login, token,
    expires, has: {ability: True|False|None}, notes} or {error}."""
    t = t or target_of(project)
    if t.get("error"):
        return {"error": t["error"]}
    kind = t["forge"]["kind"]
    r = t["repo"]
    rq = urllib.parse.quote(r, safe="")
    has: dict = {a["id"]: None for a in ABILITIES}
    notes = []
    out = {"at": int(time.time()), "host": t["host"], "repo": r, "kind": kind, "forge": t["forge"]["name"],
           "login": "", "token": "", "expires": "", "has": has, "notes": notes}
    if kind == "github":
        tok = t["token"]
        out["token"] = ("fine-grained" if tok.startswith("github_pat_") else "classic" if tok.startswith("ghp_")
                        else "app or other")
        code, me, h = _call(t, "GET", "/user")
        if code == 200 and isinstance(me, dict):
            out["login"] = str(me.get("login") or "")
        out["expires"] = _h(h, "github-authentication-token-expiration") or ""
        code, repo, h = _call(t, "GET", f"/repos/{r}")
        if code != 200:
            out["error"] = (f"{t['forge']['name']} will not show {r} to this token ({code}: "
                            f"{(repo or {}).get('message') or 'no answer'})")
            for k in has:
                has[k] = False
            _keep(project, out)
            return out
        has["code_read"] = True
        out["expires"] = out["expires"] or _h(h, "github-authentication-token-expiration") or ""
        role = (repo or {}).get("permissions") or {}
        scopes = _h(h, "x-oauth-scopes")
        if scopes is not None:
            out["scopes"] = sorted(x.strip() for x in scopes.split(",") if x.strip())
            has["workflows"] = "workflow" in out["scopes"]
        else:
            notes.append("A fine-grained token's Workflows permission cannot be read back: a push that "
                         "changes .github/workflows is refused without Read and write.")

        def read(ab, path):
            c, _b, _h2 = _call(t, "GET", path)
            has[ab] = True if c == 200 else (False if c in (401, 403, 404) else None)
            if c == 410:
                has[ab] = None
                notes.append(f"{BY_ID[ab]['label']}: the repository has that feature turned off")

        def write(ab, method, path, data):
            c, _b, _h2 = _call(t, method, path, data)
            has[ab] = _write_probe(c)

        read("pr_read", f"/repos/{r}/pulls?per_page=1")
        read("issues_read", f"/repos/{r}/issues?per_page=1")
        read("actions_read", f"/repos/{r}/actions/runs?per_page=1")
        read("releases_read", f"/repos/{r}/releases?per_page=1")
        if role and not role.get("push"):
            notes.append(f"Its account can read {r} and not write to it, so every write below is refused "
                         "whatever the token says.")
            for k in ("push", "workflows", "pr_write", "merge", "issues_write", "actions_write", "releases_write"):
                has[k] = False
        else:
            # Each refused for its content when allowed: a ref with no sha,
            # a pull request and an issue with no title, a release with no
            # tag, a run of a workflow that is not there.
            write("push", "POST", f"/repos/{r}/git/refs", {"ref": "refs/heads/builderbot-access-probe"})
            write("pr_write", "POST", f"/repos/{r}/pulls", {})
            write("issues_write", "POST", f"/repos/{r}/issues", {})
            write("releases_write", "POST", f"/repos/{r}/releases", {})
            write("actions_write", "POST", f"/repos/{r}/actions/workflows/builderbot-access-probe.yml/dispatches", {})
            has["merge"] = bool(has["pr_write"] and has["push"]) if None not in (has["pr_write"], has["push"]) else None
    elif kind == "gitlab":
        code, proj, _h2 = _call(t, "GET", f"/projects/{rq}")
        if code != 200:
            out["error"] = f"{t['forge']['name']} will not show {r} to this token ({code})"
            _keep(project, out)
            return out
        perms = (proj or {}).get("permissions") or {}
        level = max((perms.get(k) or {}).get("access_level") or 0 for k in ("project_access", "group_access"))
        code, me, _h2 = _call(t, "GET", "/personal_access_tokens/self")
        scopes = set((me or {}).get("scopes") or []) if code == 200 else None
        out["token"] = "personal"
        out["expires"] = str((me or {}).get("expires_at") or "") if code == 200 else ""
        if scopes is None:
            notes.append("GitLab did not say this token's scopes: what it may do is read off its role alone.")
            scopes = {"api"}
        out["scopes"] = sorted(scopes)
        api, rd = "api" in scopes, bool({"api", "read_api"} & scopes)
        has.update(code_read=bool({"api", "read_repository"} & scopes),
                   push=bool({"api", "write_repository"} & scopes) and level >= 30,
                   pr_read=rd, issues_read=rd, actions_read=rd, releases_read=rd,
                   pr_write=api and level >= 30, issues_write=api and level >= 20,
                   actions_write=api and level >= 30, releases_write=api and level >= 30,
                   merge=api and level >= 30)
        has["workflows"] = has["push"]
    else:
        code, repo, _h2 = _call(t, "GET", f"/repos/{r}")
        if code != 200:
            out["error"] = f"{t['forge']['name']} will not show {r} to this token ({code})"
            _keep(project, out)
            return out
        role = (repo or {}).get("permissions") or {}
        has["code_read"] = True
        w = bool(role.get("push"))
        for k in ("pr_read", "issues_read", "actions_read", "releases_read"):
            has[k] = True
        for k in ("push", "workflows", "pr_write", "issues_write", "actions_write", "releases_write", "merge"):
            has[k] = w
        notes.append("Gitea does not say a token's scopes: this is its account's role on the repository, "
                     "and a scope the token lacks is refused when it is used.")
    _keep(project, out)
    return out


def _keep(project, rec):
    p = _keep_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json(p, rec)


def forget(project):
    """The project's measure dropped, with its token."""
    try:
        _keep_path(project).unlink()
    except OSError:
        pass


def token_changed(project, gone=False):
    """A project's token stored or forgotten: measured again beside the
    request that changed it, or its measure dropped."""
    if gone:
        forget(project)
        return
    threading.Thread(target=measure, args=(project,), daemon=True).start()


def fresh(project, max_age=86400):
    """The kept measure while it is younger than a day, else a new one."""
    k = kept(project)
    if k and time.time() - (k.get("at") or 0) < max_age:
        return k
    return measure(project)


def override(project):
    """{ability: allow|deny}: what the project lets an agent do, over what
    the token allows."""
    pol = ((prefs_of(project) or {}).get("forgepol") if prefs_of else None) or {}
    return {k: (pol.get(k) if pol.get(k) in ("allow", "deny") else v) for k, v in defaults().items()}


def may(project, ab, m=None):
    """(True, "") or (False, why): the token's measure and the override."""
    m = m if m is not None else fresh(project)
    if m.get("error") and not m.get("has"):
        return False, m["error"]
    if override(project).get(ab) == "deny":
        return False, (f"{BY_ID[ab]['label']} is turned off for this project (its Permissions, "
                       "On the git host): its owner turns it on")
    got = (m.get("has") or {}).get(ab)
    if got is False:
        return False, (f"this project's token may not: {BY_ID[ab]['label'].lower()} needs "
                       f"{needs(ab, m.get('kind') or '')} (docs/git-hosts.md)")
    return True, ""


def view(project, measure_now=False):
    """The Permissions section's read: each ability with what the token
    says, the override and the result, and the measure's facts."""
    m = measure(project) if measure_now else (kept(project) or {})
    pol = override(project)
    rows = []
    for a in ABILITIES:
        got = (m.get("has") or {}).get(a["id"])
        rows.append({"id": a["id"], "label": a["label"], "token": got, "set": pol[a["id"]],
                     "default": a["default"], "needs": needs(a["id"], m.get("kind") or "github"),
                     "verbs": list(a["verbs"]), "how": a["how"]})
    return {"rows": rows, "measure": {k: m.get(k) for k in ("at", "host", "repo", "forge", "kind", "login",
                                                           "token", "expires", "notes", "error", "scopes")}
            if m else None}


def briefing(project):
    """The lines a session is handed at its start about its git host, or ""."""
    m = kept(project)
    if not m:
        # Never measured: a session's start does not wait on the host, so
        # the measure goes on beside it and the next session has it.
        t = target_of(project) if target_of else {"error": "x"}
        if t.get("error"):
            return ""
        threading.Thread(target=measure, args=(project, t), daemon=True).start()
        return ("Your git host: not measured yet, so what this project's token may do there is unknown; "
                "`bb forge whoami` measures it now.")
    if m.get("error") and not m.get("has"):
        return f"Your git host: {m['error']}."
    pol = override(project)
    yes, no = [], []
    for a in ABILITIES:
        ok = (m.get("has") or {}).get(a["id"]) is not False and pol[a["id"]] != "deny"
        (yes if ok else no).append(a)
    who = f" as {m['login']}" if m.get("login") else ""
    exp = f", expiring {m['expires']}" if m.get("expires") else ""
    lines = [f"Your git host: {m.get('forge') or m.get('host')} {m.get('repo')}{who}, a {m.get('token') or ''} "
             f"token{exp}, measured {time.strftime('%d %b %H:%M', time.localtime(m.get('at') or 0))}. "
             "`bb forge whoami` prints it whole, `bb forge VERB` does it."]
    if yes:
        lines.append("You may: " + "; ".join(a["label"].lower() for a in yes) + ".")
    for a in no:
        if pol[a["id"]] == "deny":
            lines.append(f"Not: {a['label'].lower()} (turned off for this project; its owner turns it on).")
        else:
            lines.append(f"Not: {a['label'].lower()}; ask the person to give the token {needs(a['id'], m.get('kind') or '')}.")
    return "\n".join(lines)


# ---- the verbs -------------------------------------------------------------
#
# Each takes the parsed arguments and the target and returns (payload, code).
# Arguments arrive as {"pos": [...], "flags": {...}} from bb forge; nothing in
# them reaches a path but numbers, refs checked against REF, and the words
# the verb itself names.

NUM = re.compile(r"[0-9]{1,20}")
REF = re.compile(r"[A-Za-z0-9._/-]{1,200}")
WORKFLOW = re.compile(r"[A-Za-z0-9._-]{1,100}\.ya?ml|[0-9]{1,12}")
LABEL = re.compile(r"[^\x00-\x1f]{1,50}")


def _num(a, i, what):
    v = str((a.get("pos") or [None] * (i + 1))[i] if len(a.get("pos") or []) > i else "")
    if not NUM.fullmatch(v):
        raise ValueError(f"{what}: a number")
    return v


def _text(a, k, need=False, cap=65000):
    v = (a.get("flags") or {}).get(k)
    if v is None or v is True:
        if need:
            raise ValueError(f"--{k} \"...\" is needed")
        return None
    return str(v)[:cap]


def _ref(a, k, need=False):
    v = _text(a, k, need)
    if v is not None and not REF.fullmatch(v):
        raise ValueError(f"--{k}: a branch name")
    return v


def _pick(d, keys):
    return {k: d.get(k) for k in keys if k in d}


def _row_pr(p):
    return {"number": p.get("number"), "title": p.get("title"), "state": p.get("state"),
            "draft": p.get("draft"), "head": (p.get("head") or {}).get("ref"), "base": (p.get("base") or {}).get("ref"),
            "by": (p.get("user") or {}).get("login"), "url": p.get("html_url"), "merged": p.get("merged")}


def _row_issue(i):
    return {"number": i.get("number"), "title": i.get("title"), "state": i.get("state"),
            "labels": [x.get("name") for x in i.get("labels") or []], "by": (i.get("user") or {}).get("login"),
            "url": i.get("html_url")}


def _row_run(r):
    return {"id": r.get("id"), "workflow": r.get("name"), "event": r.get("event"), "branch": r.get("head_branch"),
            "sha": (r.get("head_sha") or "")[:7], "status": r.get("status"), "conclusion": r.get("conclusion"),
            "at": r.get("created_at"), "url": r.get("html_url")}


def _ok(code, body, shape=None):
    if 200 <= code < 300:
        return (shape(body) if shape else body), 200
    return {"error": f"the host said {code}: {(body or {}).get('message') or 'no reason given'}"}, 400


def v_pr_list(t, a):
    st = _text(a, "state") or "open"
    if st not in ("open", "closed", "all"):
        raise ValueError("--state: open, closed or all")
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/pulls?state={st}&per_page=30")
    return _ok(c, b, lambda x: [_row_pr(p) for p in x])


def v_pr_view(t, a):
    n = _num(a, 0, "the pull request")
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/pulls/{n}")
    return _ok(c, b, lambda p: _row_pr(p) | {"body": p.get("body"), "mergeable": p.get("mergeable"),
                                            "comments": p.get("comments"), "review_comments": p.get("review_comments")})


def v_pr_create(t, a):
    data = {"title": _text(a, "title", True), "head": _ref(a, "head", True), "base": _ref(a, "base", True),
            "body": _text(a, "body") or "", "draft": bool((a.get("flags") or {}).get("draft"))}
    c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/pulls", data)
    return _ok(c, b, _row_pr)


def v_pr_comment(t, a):
    n = _num(a, 0, "the pull request")
    c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/issues/{n}/comments", {"body": _text(a, "body", True)})
    return _ok(c, b, lambda x: {"url": x.get("html_url")})


def v_pr_review(t, a):
    n = _num(a, 0, "the pull request")
    f = a.get("flags") or {}
    ev = "APPROVE" if f.get("approve") else "REQUEST_CHANGES" if f.get("request-changes") else "COMMENT"
    data = {"event": ev, "body": _text(a, "body", ev != "APPROVE") or ""}
    if t["forge"]["kind"] == "gitea":
        data["event"] = {"APPROVE": "APPROVED"}.get(ev, ev)
    c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/pulls/{n}/reviews", data)
    return _ok(c, b, lambda x: {"state": x.get("state"), "url": x.get("html_url")})


def v_pr_close(t, a):
    n = _num(a, 0, "the pull request")
    c, b, _h = _call(t, "PATCH", f"/repos/{t['repo']}/pulls/{n}", {"state": "closed"})
    return _ok(c, b, _row_pr)


def v_pr_merge(t, a):
    n = _num(a, 0, "the pull request")
    how = _text(a, "method") or "merge"
    if how not in ("merge", "squash", "rebase"):
        raise ValueError("--method: merge, squash or rebase")
    if t["forge"]["kind"] == "gitea":
        # Gitea merges with a POST naming the way in Do, and answers empty.
        c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/pulls/{n}/merge", {"Do": how})
        return _ok(c, b, lambda _x: {"merged": True})
    c, b, _h = _call(t, "PUT", f"/repos/{t['repo']}/pulls/{n}/merge", {"merge_method": how})
    return _ok(c, b, lambda x: {"merged": x.get("merged"), "sha": (x.get("sha") or "")[:7], "said": x.get("message")})


def v_issue_list(t, a):
    st = _text(a, "state") or "open"
    if st not in ("open", "closed", "all"):
        raise ValueError("--state: open, closed or all")
    extra = "&type=issues&limit=30" if t["forge"]["kind"] == "gitea" else "&per_page=30"
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/issues?state={st}{extra}")
    return _ok(c, b, lambda x: [_row_issue(i) for i in x if not i.get("pull_request")])


def v_issue_view(t, a):
    n = _num(a, 0, "the issue")
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/issues/{n}")
    return _ok(c, b, lambda i: _row_issue(i) | {"body": i.get("body"), "comments": i.get("comments")})


def v_issue_create(t, a):
    data = {"title": _text(a, "title", True), "body": _text(a, "body") or ""}
    lab = _text(a, "label")
    if lab and t["forge"]["kind"] == "gitea":
        raise ValueError("Gitea takes labels by their number: create it, then bb forge issue label N NAME")
    if lab:
        data["labels"] = [x.strip() for x in lab.split(",") if LABEL.fullmatch(x.strip())]
    c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/issues", data)
    return _ok(c, b, _row_issue)


def v_issue_comment(t, a):
    n = _num(a, 0, "the issue")
    c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/issues/{n}/comments", {"body": _text(a, "body", True)})
    return _ok(c, b, lambda x: {"url": x.get("html_url")})


def v_issue_close(t, a):
    n = _num(a, 0, "the issue")
    c, b, _h = _call(t, "PATCH", f"/repos/{t['repo']}/issues/{n}", {"state": "closed"})
    return _ok(c, b, _row_issue)


def v_issue_label(t, a):
    n = _num(a, 0, "the issue")
    labs = [str(x) for x in (a.get("pos") or [])[1:] if LABEL.fullmatch(str(x))]
    if not labs:
        raise ValueError("name a label after the issue's number")
    c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/issues/{n}/labels", {"labels": labs})
    return _ok(c, b, lambda x: {"labels": [y.get("name") for y in x]})


def v_run_list(t, a):
    q = "per_page=20"
    br = _ref(a, "branch")
    if br:
        q += "&branch=" + urllib.parse.quote(br, safe="")
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/actions/runs?{q}")
    return _ok(c, b, lambda x: [_row_run(r) for r in x.get("workflow_runs") or []])


def v_run_view(t, a):
    n = _num(a, 0, "the run")
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/actions/runs/{n}")
    if not 200 <= c < 300:
        return _ok(c, b)
    c2, j, _h = _call(t, "GET", f"/repos/{t['repo']}/actions/runs/{n}/jobs?per_page=50")
    jobs = [{"id": x.get("id"), "name": x.get("name"), "conclusion": x.get("conclusion"), "status": x.get("status"),
             "failed_step": next((s.get("name") for s in x.get("steps") or [] if s.get("conclusion") == "failure"), None)}
            for x in (j or {}).get("jobs") or []] if 200 <= c2 < 300 else []
    return _row_run(b) | {"jobs": jobs}, 200


def v_run_log(t, a):
    """A job's log, or every failed job's in a run: the end of each, where
    a failure says why."""
    n = _num(a, 0, "the run")
    lines = int(_text(a, "lines") or 200) if NUM.fullmatch(_text(a, "lines") or "200") else 200
    lines = max(10, min(lines, 2000))
    want = []
    if (a.get("flags") or {}).get("job"):
        want = [n]
    else:
        c, j, _h = _call(t, "GET", f"/repos/{t['repo']}/actions/runs/{n}/jobs?per_page=50")
        if not 200 <= c < 300:
            return _ok(c, j)
        jobs = (j or {}).get("jobs") or []
        want = [str(x["id"]) for x in jobs if x.get("conclusion") == "failure"] or [str(x["id"]) for x in jobs]
    out = []
    for jid in want[:6]:
        c, text, _h = _call(t, "GET", f"/repos/{t['repo']}/actions/jobs/{jid}/logs", raw=True)
        if not 200 <= c < 300:
            out.append({"job": jid, "error": f"the host said {c}"})
            continue
        tail = text.splitlines()[-lines:]
        out.append({"job": jid, "log": "\n".join(tail)})
    return out, 200


def v_run_rerun(t, a):
    n = _num(a, 0, "the run")
    if t["forge"]["kind"] == "gitea":
        raise ValueError("Gitea's API has no rerun: start the workflow again with bb forge run dispatch")
    path = f"/repos/{t['repo']}/actions/runs/{n}/" + ("rerun-failed-jobs" if (a.get("flags") or {}).get("failed") else "rerun")
    c, b, _h = _call(t, "POST", path, {})
    return _ok(c, b, lambda _x: {"rerun": n})


def v_run_dispatch(t, a):
    wf = str((a.get("pos") or [""])[0])
    if not WORKFLOW.fullmatch(wf):
        raise ValueError("name the workflow by its file (build.yml) or its id")
    data = {"ref": _ref(a, "ref", True), "inputs": {}}
    for kv in (a.get("flags") or {}).get("field") or []:
        k, _, v = str(kv).partition("=")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", k):
            raise ValueError(f"-f {kv}: name=value")
        data["inputs"][k] = v[:1000]
    c, b, _h = _call(t, "POST", f"/repos/{t['repo']}/actions/workflows/{wf}/dispatches", data)
    return _ok(c, b, lambda _x: {"dispatched": wf, "ref": data["ref"]})


def v_release_list(t, a):
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/releases?per_page=20")
    return _ok(c, b, lambda x: [{"tag": r.get("tag_name"), "name": r.get("name"), "prerelease": r.get("prerelease"),
                                 "draft": r.get("draft"), "at": r.get("published_at"), "url": r.get("html_url"),
                                 "files": [f.get("name") for f in r.get("assets") or []]} for r in x])


def v_release_view(t, a):
    tag = str((a.get("pos") or [""])[0])
    if not REF.fullmatch(tag):
        raise ValueError("name the release by its tag")
    c, b, _h = _call(t, "GET", f"/repos/{t['repo']}/releases/tags/{urllib.parse.quote(tag, safe='')}")
    return _ok(c, b, lambda r: {"tag": r.get("tag_name"), "name": r.get("name"), "body": r.get("body"),
                                "prerelease": r.get("prerelease"), "url": r.get("html_url"),
                                "files": [{"name": f.get("name"), "size": f.get("size")} for f in r.get("assets") or []]})


# ---- GitLab's own --------------------------------------------------------
#
# The same verbs in GitLab's words: a pull request is a merge request, a
# CI run a pipeline, a comment a note; what GitLab has no word for (asking
# for changes, rebasing a merge) is refused saying so.

def _gl(t):
    return "/projects/" + urllib.parse.quote(t["repo"], safe="")


def _gl_state(a):
    st = _text(a, "state") or "open"
    if st not in ("open", "closed", "all", "merged"):
        raise ValueError("--state: open, closed, merged or all")
    return {"open": "opened"}.get(st, st)


def _gl_mr(m):
    return {"number": m.get("iid"), "title": m.get("title"), "state": m.get("state"), "draft": m.get("draft"),
            "head": m.get("source_branch"), "base": m.get("target_branch"),
            "by": (m.get("author") or {}).get("username"), "url": m.get("web_url"),
            "merged": m.get("state") == "merged"}


def _gl_issue(i):
    return {"number": i.get("iid"), "title": i.get("title"), "state": i.get("state"), "labels": i.get("labels"),
            "by": (i.get("author") or {}).get("username"), "url": i.get("web_url")}


def _gl_run(p):
    return {"id": p.get("id"), "workflow": p.get("source"), "event": p.get("source"), "branch": p.get("ref"),
            "sha": (p.get("sha") or "")[:7], "status": p.get("status"),
            "conclusion": {"success": "success", "failed": "failure", "canceled": "cancelled"}.get(p.get("status")),
            "at": p.get("created_at"), "url": p.get("web_url")}


def gl_pr_list(t, a):
    c, b, _h = _call(t, "GET", f"{_gl(t)}/merge_requests?state={_gl_state(a)}&per_page=30")
    return _ok(c, b, lambda x: [_gl_mr(m) for m in x])


def gl_pr_view(t, a):
    n = _num(a, 0, "the merge request")
    c, b, _h = _call(t, "GET", f"{_gl(t)}/merge_requests/{n}")
    return _ok(c, b, lambda m: _gl_mr(m) | {"body": m.get("description"),
                                            "mergeable": m.get("detailed_merge_status")})


def gl_pr_create(t, a):
    title = _text(a, "title", True)
    if (a.get("flags") or {}).get("draft"):
        title = "Draft: " + title
    data = {"title": title, "source_branch": _ref(a, "head", True), "target_branch": _ref(a, "base", True),
            "description": _text(a, "body") or ""}
    c, b, _h = _call(t, "POST", f"{_gl(t)}/merge_requests", data)
    return _ok(c, b, _gl_mr)


def gl_pr_comment(t, a):
    n = _num(a, 0, "the merge request")
    c, b, _h = _call(t, "POST", f"{_gl(t)}/merge_requests/{n}/notes", {"body": _text(a, "body", True)})
    return _ok(c, b, lambda x: {"note": x.get("id")})


def gl_pr_review(t, a):
    n = _num(a, 0, "the merge request")
    f = a.get("flags") or {}
    if f.get("request-changes"):
        raise ValueError("GitLab has no request for changes: say it with --body as a comment")
    if f.get("approve"):
        c, b, _h = _call(t, "POST", f"{_gl(t)}/merge_requests/{n}/approve", {})
        out = _ok(c, b, lambda _x: {"state": "approved"})
        if out[1] != 200 or not _text(a, "body"):
            return out
    return gl_pr_comment(t, a)


def gl_pr_close(t, a):
    n = _num(a, 0, "the merge request")
    c, b, _h = _call(t, "PUT", f"{_gl(t)}/merge_requests/{n}", {"state_event": "close"})
    return _ok(c, b, _gl_mr)


def gl_pr_merge(t, a):
    n = _num(a, 0, "the merge request")
    how = _text(a, "method") or "merge"
    if how not in ("merge", "squash"):
        raise ValueError("--method: merge or squash (GitLab rebases from its own page)")
    c, b, _h = _call(t, "PUT", f"{_gl(t)}/merge_requests/{n}/merge", {"squash": how == "squash"})
    return _ok(c, b, lambda m: {"merged": m.get("state") == "merged", "sha": (m.get("merge_commit_sha") or "")[:7]})


def gl_issue_list(t, a):
    st = _gl_state(a)
    if st == "merged":
        raise ValueError("--state: open, closed or all")
    c, b, _h = _call(t, "GET", f"{_gl(t)}/issues?state={st}&per_page=30")
    return _ok(c, b, lambda x: [_gl_issue(i) for i in x])


def gl_issue_view(t, a):
    n = _num(a, 0, "the issue")
    c, b, _h = _call(t, "GET", f"{_gl(t)}/issues/{n}")
    return _ok(c, b, lambda i: _gl_issue(i) | {"body": i.get("description")})


def gl_issue_create(t, a):
    data = {"title": _text(a, "title", True), "description": _text(a, "body") or ""}
    lab = _text(a, "label")
    if lab:
        data["labels"] = ",".join(x.strip() for x in lab.split(",") if LABEL.fullmatch(x.strip()))
    c, b, _h = _call(t, "POST", f"{_gl(t)}/issues", data)
    return _ok(c, b, _gl_issue)


def gl_issue_comment(t, a):
    n = _num(a, 0, "the issue")
    c, b, _h = _call(t, "POST", f"{_gl(t)}/issues/{n}/notes", {"body": _text(a, "body", True)})
    return _ok(c, b, lambda x: {"note": x.get("id")})


def gl_issue_close(t, a):
    n = _num(a, 0, "the issue")
    c, b, _h = _call(t, "PUT", f"{_gl(t)}/issues/{n}", {"state_event": "close"})
    return _ok(c, b, _gl_issue)


def gl_issue_label(t, a):
    n = _num(a, 0, "the issue")
    labs = [str(x) for x in (a.get("pos") or [])[1:] if LABEL.fullmatch(str(x))]
    if not labs:
        raise ValueError("name a label after the issue's number")
    c, b, _h = _call(t, "PUT", f"{_gl(t)}/issues/{n}", {"add_labels": ",".join(labs)})
    return _ok(c, b, lambda i: {"labels": i.get("labels")})


def gl_run_list(t, a):
    q = "per_page=20"
    br = _ref(a, "branch")
    if br:
        q += "&ref=" + urllib.parse.quote(br, safe="")
    c, b, _h = _call(t, "GET", f"{_gl(t)}/pipelines?{q}")
    return _ok(c, b, lambda x: [_gl_run(p) for p in x])


def gl_run_view(t, a):
    n = _num(a, 0, "the pipeline")
    c, b, _h = _call(t, "GET", f"{_gl(t)}/pipelines/{n}")
    if not 200 <= c < 300:
        return _ok(c, b)
    c2, j, _h = _call(t, "GET", f"{_gl(t)}/pipelines/{n}/jobs?per_page=50")
    jobs = [{"id": x.get("id"), "name": x.get("name"), "status": x.get("status"),
             "conclusion": "failure" if x.get("status") == "failed" else x.get("status"), "failed_step": x.get("stage")}
            for x in (j or [])] if 200 <= c2 < 300 and isinstance(j, list) else []
    return _gl_run(b) | {"jobs": jobs}, 200


def gl_run_log(t, a):
    n = _num(a, 0, "the pipeline")
    lines = int(_text(a, "lines") or 200) if NUM.fullmatch(_text(a, "lines") or "200") else 200
    lines = max(10, min(lines, 2000))
    if (a.get("flags") or {}).get("job"):
        want = [n]
    else:
        c, j, _h = _call(t, "GET", f"{_gl(t)}/pipelines/{n}/jobs?per_page=50")
        if not 200 <= c < 300:
            return _ok(c, j)
        jobs = j if isinstance(j, list) else []
        want = [str(x["id"]) for x in jobs if x.get("status") == "failed"] or [str(x["id"]) for x in jobs]
    out = []
    for jid in want[:6]:
        c, text, _h = _call(t, "GET", f"{_gl(t)}/jobs/{jid}/trace", raw=True)
        out.append({"job": jid, "log": "\n".join(text.splitlines()[-lines:])} if 200 <= c < 300
                   else {"job": jid, "error": f"the host said {c}"})
    return out, 200


def gl_run_rerun(t, a):
    n = _num(a, 0, "the pipeline")
    c, b, _h = _call(t, "POST", f"{_gl(t)}/pipelines/{n}/retry", {})
    return _ok(c, b, lambda _x: {"rerun": n})


def gl_run_dispatch(t, a):
    data = {"ref": _ref(a, "ref", True), "variables": []}
    for kv in (a.get("flags") or {}).get("field") or []:
        k, _, v = str(kv).partition("=")
        if not re.fullmatch(r"[A-Za-z0-9_]{1,60}", k):
            raise ValueError(f"-f {kv}: NAME=value")
        data["variables"].append({"key": k, "value": v[:1000]})
    c, b, _h = _call(t, "POST", f"{_gl(t)}/pipeline", data)
    return _ok(c, b, _gl_run)


def gl_release_list(t, a):
    c, b, _h = _call(t, "GET", f"{_gl(t)}/releases?per_page=20")
    return _ok(c, b, lambda x: [{"tag": r.get("tag_name"), "name": r.get("name"), "at": r.get("released_at"),
                                 "url": ((r.get("_links") or {}).get("self")),
                                 "files": [f.get("name") for f in (r.get("assets") or {}).get("links") or []]} for r in x])


def gl_release_view(t, a):
    tag = str((a.get("pos") or [""])[0])
    if not REF.fullmatch(tag):
        raise ValueError("name the release by its tag")
    c, b, _h = _call(t, "GET", f"{_gl(t)}/releases/{urllib.parse.quote(tag, safe='')}")
    return _ok(c, b, lambda r: {"tag": r.get("tag_name"), "name": r.get("name"), "body": r.get("description"),
                                "files": [f.get("name") for f in (r.get("assets") or {}).get("links") or []]})


# Each verb in the two dialects: GitHub's, which Gitea and Forgejo speak
# with the differences said inside each, and GitLab's.
VERBS = {
    "pr list": (v_pr_list, gl_pr_list), "pr view": (v_pr_view, gl_pr_view),
    "pr create": (v_pr_create, gl_pr_create), "pr comment": (v_pr_comment, gl_pr_comment),
    "pr review": (v_pr_review, gl_pr_review), "pr close": (v_pr_close, gl_pr_close),
    "pr merge": (v_pr_merge, gl_pr_merge),
    "issue list": (v_issue_list, gl_issue_list), "issue view": (v_issue_view, gl_issue_view),
    "issue create": (v_issue_create, gl_issue_create), "issue comment": (v_issue_comment, gl_issue_comment),
    "issue close": (v_issue_close, gl_issue_close), "issue label": (v_issue_label, gl_issue_label),
    "run list": (v_run_list, gl_run_list), "run view": (v_run_view, gl_run_view),
    "run log": (v_run_log, gl_run_log), "run rerun": (v_run_rerun, gl_run_rerun),
    "run dispatch": (v_run_dispatch, gl_run_dispatch),
    "release list": (v_release_list, gl_release_list), "release view": (v_release_view, gl_release_view),
}
ABILITY_OF = {v: a["id"] for a in ABILITIES for v in a["verbs"]}


def run(project, verb, args):
    """One bb forge verb for this project: (payload, status)."""
    if verb == "whoami":
        m = fresh(project)
        return {"measure": m, "override": override(project), "briefing": briefing(project)}, 200
    if verb == "measure":
        return measure(project), 200
    fn = VERBS.get(verb)
    if fn is None:
        return {"error": f"bb forge has no {verb}: {', '.join(['whoami', 'measure', *VERBS])}"}, 400
    t = target_of(project)
    if t.get("error"):
        return {"error": t["error"]}, 400
    ok, why = may(project, ABILITY_OF[verb])
    if not ok:
        return {"error": why}, 403
    args = args if isinstance(args, dict) else {}
    try:
        return fn[1 if t["forge"]["kind"] == "gitlab" else 0](t, args)
    except ValueError as e:
        return {"error": f"bb forge {verb}: {e}"}, 400
