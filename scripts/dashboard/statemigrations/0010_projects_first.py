"""State 9 to 10: every repository is in a project (R138, the operator, 25 Oct).

A project is a record of its own (projects.json, state `repos`) and every
repository is in exactly one (project-repos.json). Each repository in none
gets one, named as it is shown and holding it alone, and what was the
repository's as a project moves onto the project's key:

  * its settings kept by project (the fields below, frozen here as they were
    when this ran) move from its claude-prefs.json record to the project's;
  * its owner and its invitations (project-owners.json, invites.json);
  * every account's project list and project roles (users.json): the
    repository's name becomes the project's key;
  * each person's pin, group and color, and its archive and its lock;
  * a read another project granted it names the project instead.

A project of several repositories made before this (R136) keeps its key; its
first repository's marks, list entries and roles move onto it the same way.

Idempotent: a repository already in a project is left as it is.
Never edited once shipped (stateversion.py).
"""
import json
import re
import time
from pathlib import Path

GROUP_FIELDS = ("node", "nodes", "hosts", "reads", "sees", "reaches", "tc_off", "packs_on",
                "agents_off", "agent_default", "gitpol", "color", "devbuild", "makevms", "vm_caps",
                "test_change", "gpu", "report", "sign", "keys", "release", "pc", "log_from", "diag")


def _read(path, empty):
    try:
        v = json.loads(path.read_text())
    except (OSError, ValueError):
        return empty
    return v if isinstance(v, type(empty)) else empty


def _write(path, data):
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(json.dumps(data, indent=1) + "\n")
    tmp.replace(path)


def _slug(name):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip("-")[:100].strip("-")
    return "" if s in (".", "..") else s


def run(ctx):
    state = Path(ctx["state"])
    reg_f, rep_f = state / "projects.json", state / "project-repos.json"
    reg = _read(reg_f, {})
    recs = reg.get("projects") or {}
    if not isinstance(recs, dict):
        recs = {}
    if not recs:
        return
    rep = _read(rep_f, {})
    groups = rep.get("projects") or {}
    if not isinstance(groups, dict):
        groups = {}
    inside = {m for g in groups.values() if isinstance(g, dict) for m in (g.get("members") or [])}
    workspace = Path(ctx.get("workspace") or "/workspace")
    try:
        on_disk = {p.name.lower() for p in workspace.iterdir()} | {p.name.lower() for p in (workspace / ".trash").iterdir()}
    except OSError:
        on_disk = set()
    taken = {k.lower() for k in recs} | on_disk
    names = {str(r.get("name") or k).lower() for k, r in recs.items() if r.get("state") == "repos"}
    nxt = int(reg.get("next") or 1)
    moved = {}                                       # repository dir -> its project's key
    for d, r in sorted(recs.items(), key=lambda kv: int((kv[1] or {}).get("id") or 0)):
        if not isinstance(r, dict) or r.get("state") != "live" or d in inside:
            continue
        shown = str(r.get("name") or d)
        title = shown if shown.lower() not in names else f"{shown} (P{r.get('id')})"
        base = _slug(title) or "project"
        key, n = base, 2
        while key.lower() in taken:
            key, n = f"{base}-{n}", n + 1
        taken.add(key.lower())
        names.add(title.lower())
        recs[key] = {"id": nxt, "name": title, "state": "repos", "at": int(time.time())}
        nxt += 1
        groups[key] = {"members": [d], "at": int(time.time())}
        moved[d] = key
    placed = len(moved)
    # A project of several repositories made before this: its first one's.
    for key, g in groups.items():
        ms = [m for m in (g or {}).get("members") or [] if isinstance(m, str)]
        for m in ms:
            moved.setdefault(m, key)
    if not moved:
        return
    reg["next"] = nxt
    reg["projects"] = recs
    rep["projects"] = groups
    _write(reg_f, reg)
    _write(rep_f, rep)
    firsts = {key: (g.get("members") or [None])[0] for key, g in groups.items() if isinstance(g, dict)}

    # Settings kept by project.
    pf = state / "claude-prefs.json"
    pd = _read(pf, {})
    pp = pd.get("projects") if isinstance(pd.get("projects"), dict) else None
    if pp is not None:
        for key, first in firsts.items():
            src = pp.get(first) if isinstance(pp.get(first), dict) else {}
            dst = pp.setdefault(key, {}) if isinstance(pp.get(key, {}), dict) else {}
            for f in GROUP_FIELDS:
                if f in src and f not in dst:
                    dst[f] = src[f]
            for m in groups[key].get("members") or []:
                rec = pp.get(m)
                if isinstance(rec, dict):
                    for f in GROUP_FIELDS:
                        rec.pop(f, None)
            if dst:
                pp[key] = dst
        # A read names the project.
        for rec in pp.values():
            if isinstance(rec, dict) and isinstance(rec.get("reads"), list):
                rec["reads"] = list(dict.fromkeys(moved.get(x, x) for x in rec["reads"] if isinstance(x, str)))
        _write(pf, pd)

    # The owner and the invitations.
    for name in ("project-owners.json", "invites.json"):
        f = state / name
        d = _read(f, {})
        ps = d.get("projects") if isinstance(d.get("projects"), dict) else None
        if ps is None:
            continue
        for key, first in firsts.items():
            if first in ps and key not in ps:
                ps[key] = ps[first]
            for m in groups[key].get("members") or []:
                ps.pop(m, None)
        _write(f, d)

    # Every account's list and roles.
    uf = state / "users.json"
    ud = _read(uf, {})
    for u in (ud.get("users") or {}).values():
        if not isinstance(u, dict):
            continue
        if isinstance(u.get("projects"), list):
            u["projects"] = list(dict.fromkeys(moved.get(p, p) for p in u["projects"] if isinstance(p, str)))
        pr = u.get("project_roles")
        if isinstance(pr, dict):
            out = {}
            for p, rs in pr.items():
                k = moved.get(p, p)
                out[k] = sorted(set(out.get(k, [])) | set(rs if isinstance(rs, list) else []))
            u["project_roles"] = out
    if ud:
        _write(uf, ud)

    # Each person's pins, groups and colors.
    for name in ("pinned-projects.json", "project-groups.json", "project-colors.json"):
        f = state / name
        d = _read(f, {})
        if not d:
            continue
        for uid, v in d.items():
            if isinstance(v, list):
                d[uid] = sorted({moved.get(x, x) for x in v if isinstance(x, str)})
            elif isinstance(v, dict):
                out = {}
                for p, val in v.items():
                    out.setdefault(moved.get(p, p), val)
                d[uid] = out
        _write(f, d)

    # The archive and the locks.
    f = state / "archived-projects.json"
    v = _read(f, [])
    if v:
        _write(f, sorted({moved.get(x, x) for x in v if isinstance(x, str)}))
    f = state / "locked-projects.json"
    v = _read(f, {})
    if v:
        out = {}
        for p, rec in v.items():
            out.setdefault(moved.get(p, p), rec)
        _write(f, out)
    if placed:
        print(f"dashboard: every repository is in a project now: {placed} placed (R138)", flush=True)
