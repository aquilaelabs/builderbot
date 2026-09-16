"""A node's CI runners as the controller holds them: the root-only helper that
keeps each runner's token and mints from it, and the list the Runner card draws.

The helper is the builder account's one sudo rule (Dockerfile). Nothing here
ever sees a token: store hands one in on stdin, every other verb prints a
derived answer, and --list says only which runners have one.
"""
import re
import subprocess

# Injected by configure(): the server's subprocess runner, and the nodes
# module, or None when the node store would not open.
run = None
nodes = None

HELPER = "/opt/builderbot/scripts/mint-runner-token"


def configure(*, run, nodes):
    globals().update(run=run, nodes=nodes)


def _why(r):
    why = (r["out"].strip().splitlines() or ["the helper printed nothing"])[-1]
    return re.sub(r"^\[builderbot\] ERROR: ", "", why)[:200]


def mint(kind, node_id, slot, runner_id=""):
    """A registration or removal token for one of a node's runners, minted
    from the token stored for it. `runner_id` is the runner's id on a
    Gitea, where removal is a deletion there rather than a token."""
    argv = ["sudo", "-n", HELPER, kind, node_id, slot]
    if re.fullmatch(r"[0-9]{1,12}", str(runner_id or "")):
        argv.append(str(runner_id))
    r = run(argv, timeout=60)
    if r["code"] == 0 and r["out"].strip():
        return {"token": r["out"].strip().splitlines()[-1]}
    return {"error": f"the controller cannot mint a runner token: {_why(r)}"}


def tokens():
    """{node id: {slot, ...}} for every runner token stored, from one call
    to the helper's --list. Which runners have a token, and nothing else."""
    r = run(["sudo", "-n", HELPER, "--list"], timeout=20)
    out = {}
    if r["code"] == 0:
        for line in r["out"].splitlines():
            parts = line.split()
            if len(parts) == 2:
                out.setdefault(parts[0], set()).add(parts[1])
    return out


def store(node_id, slot, url, forge, token):
    """Hand a runner's token to the helper on stdin: it never rides an argv,
    where every account on the box could read it off ps."""
    try:
        p = subprocess.run(["sudo", "-n", HELPER, "store", node_id, slot],
                           input=f"RUNNER_URL={url}\nRUNNER_FORGE={forge}\nRUNNER_TOKEN={token}\n",
                           capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return {"error": f"could not store the token: {e}"}
    r = {"code": p.returncode, "out": ((p.stdout or "") + (p.stderr or "")).strip()}
    if r["code"]:
        return {"error": _why(r)}
    return {"ok": True}


def forget(node_id, slot):
    r = run(["sudo", "-n", HELPER, "forget", node_id, slot], timeout=20)
    return {"ok": True} if r["code"] == 0 else {"error": _why(r)}


def reset():
    """Forget every stored token, for a controller being reset: the nodes
    they were for are being forgotten too. True when the helper did."""
    return run(["sudo", "-n", HELPER, "--reset"], timeout=20)["code"] == 0


def listing():
    """[{node, name, listening, busy, labels, url}] for every node whose
    census reports a runner, or that has been asked for one. Quiet nodes are
    included and marked: a runner nobody can hear from is a fact worth
    seeing, not a row to hide."""
    if not nodes:
        return []
    out = []
    for n in nodes.node_list():
        if n["kind"] != "agent":
            continue
        asked = nodes.runners_of(n)
        reported = {r.get("slot"): r for r in nodes.runners_reported(n)}
        ap = n.get("applying") or {}
        failed = n.get("runner_failed") or {}
        for slot in sorted(set(asked) | set(reported)):
            want = asked.get(slot) or {}
            rep = reported.get(slot) or {}
            # A runner job in flight keeps the row while it runs: a Remove
            # takes the ask off the record the moment it is pressed, and the
            # row went with it before the node had said a word.
            applying = ap.get("what") == "runner" and (ap.get("slot") or slot) == slot
            if not (rep.get("installed") or want.get("want") or applying):
                continue
            out.append({"node": n["name"], "id": n["id"], "slot": slot, "live": bool(n.get("live")),
                        "installed": bool(rep.get("installed")),
                        "listening": bool(rep.get("active")), "busy": bool(rep.get("busy")),
                        "name": rep.get("name") or "", "url": rep.get("url") or want.get("url") or "",
                        "labels": rep.get("labels") or want.get("labels") or [],
                        # Why a runner that was asked for is not there, and
                        # whether the install that would put it there runs now.
                        "failed": failed if failed and (failed.get("slot") or slot) == slot else None,
                        "installing": applying and bool(want.get("want")),
                        "removing": applying and not want.get("want")})
    return out
