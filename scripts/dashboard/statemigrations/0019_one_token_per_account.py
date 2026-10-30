"""State 18 to 19: one git host token per account and host (the operator,
30 Oct: the current token or its replacement, never a record of the ones
before).

  * in account-secrets.json, each account's forge entries for one host and
    one login are collapsed to the newest (its `at`); the older entries,
    sealed tokens that were replaced, are dropped;
  * each project's gitcreds file that linked one of the dropped entries
    links the kept one instead, so no project is left on a token that is
    gone.

A build before this one files each new token beside the last, and would
show the piles again as they came back; the number moves. Idempotent: an
account with one entry per host and login is left as it is. Never edited
once shipped (stateversion.py).
"""
import json
import os
from pathlib import Path

LINKED = "account:"


def run(ctx):
    state = Path(ctx["state"])
    f = state / "account-secrets.json"
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(d, dict):
        return
    moved = {}                       # (uid, dropped id) -> kept id
    for uid, acct in d.items():
        fs = acct.get("forges") if isinstance(acct, dict) else None
        if not isinstance(fs, dict):
            continue
        groups = {}
        for fid, e in fs.items():
            if isinstance(e, dict):
                groups.setdefault((str(e.get("host", "")).lower(), e.get("login") or ""), []).append(fid)
        for ids in groups.values():
            if len(ids) < 2:
                continue
            ids.sort(key=lambda i: -int(fs[i].get("at") or 0))
            for old in ids[1:]:
                fs.pop(old, None)
                moved[(uid, old)] = ids[0]
    if not moved:
        return
    tmp = f.with_name(f.name + ".new")
    tmp.write_text(json.dumps(d))
    os.chmod(tmp, 0o600)
    tmp.replace(f)
    gd = state / "gitcreds"
    for p in sorted(gd.iterdir()) if gd.is_dir() else []:
        try:
            lines = p.read_text().splitlines()
        except OSError:
            continue
        out, changed = [], False
        for ln in lines:
            if ln.startswith(LINKED):
                uid, _, fid = ln[len(LINKED):].partition(":")
                if (uid, fid) in moved:
                    ln, changed = f"{LINKED}{uid}:{moved[(uid, fid)]}", True
            if ln not in out:
                out.append(ln)
        if changed:
            t = p.with_name(p.name + ".new")
            t.write_text("".join(x + "\n" for x in out))
            os.chmod(t, 0o600)
            t.replace(p)
