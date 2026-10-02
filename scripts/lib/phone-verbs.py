"""Behind `bb phone` (cmd_phone in bb): what phone each node carries, and one adb
command put in front of the operator with its reason, run when they allow it.

The first argument is the verb (status or run); for run the rest are the adb
arguments. BB_PHONE_AUTH is the auth header, BB_PHONE_WHY the sentence the
operator reads, BB_PHONE_PROJECT the project asking.
"""
import os
import sys

import bbapi
import waits


def status():
    d = bbapi.call("/api/phone", auth=os.environ["BB_PHONE_AUTH"])
    if d.get("error"):
        sys.exit(f"[builderbot] ERROR: could not reach the dashboard at {bbapi.url()}: {d['error']}")
    rows = d.get("nodes") or []
    if not rows:
        print("phone:   no node carries adb; a phone is driven from a node")
    for n in rows:
        p = n.get("phone")
        who = (n.get("owner") or {}).get("name")
        print("{:<16} {}".format(n.get("name", "?") + ":",
              "{} ({}){}".format(p.get("model") or "phone", p.get("serial"), f", connected by {who}" if who else "")
              if p else ("not dialing in" if not n.get("live") else "no phone connected")))
    for a in d.get("asks") or []:
        print("waiting: #{} {} ({} on {})".format(a.get("id"), a.get("why"), a.get("project") or "a session", a.get("node_name")))


def run():
    post = lambda body: bbapi.call("/api/phone", body, auth=os.environ["BB_PHONE_AUTH"])  # noqa: E731


    # The project names the node, and the node's phone names who is asked: a
    # session's token carries its project; a person running this names theirs.
    r = post({"action": "ask", "why": os.environ["BB_PHONE_WHY"], "cmd": sys.argv[2:],
              "project": os.environ.get("BB_PHONE_PROJECT", "")})
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr); sys.exit(1)
    rid = r["id"]
    print(f"[builderbot] asked {r.get('to') or 'the operator'} (#{rid}), waiting up to 15 minutes "
          "for Allow on the dashboard's Phone tab", file=sys.stderr)
    # Polled rather than pushed: this is a shell command waiting on a person, and
    # a person is slow in a way no callback improves.
    o = waits.outcome(os.environ["BB_PHONE_AUTH"], rid, "the operator said no")
    sys.stdout.write(o.get("out") or "")
    sys.exit(o.get("code") or 0)


# ---- a phone lent to this project (R113) -------------------------------------
# No ask per command: the owner lent the phone to this project, and the
# controller allows only the project's own app on it (phonelease.py).

def use(op, args=None, quiet=False):
    r = bbapi.call("/api/phone", {"action": "use", "op": op, "args": args or {},
                                  "project": os.environ.get("BB_PHONE_PROJECT", "")},
                   auth=os.environ["BB_PHONE_AUTH"], timeout=900)
    if r.get("error"):
        print(f"[builderbot] ERROR: {r['error']}", file=sys.stderr)
        sys.exit(1)
    if not quiet and r.get("out"):
        sys.stdout.write(r["out"] if r["out"].endswith("\n") else r["out"] + "\n")
    if r.get("code"):
        sys.exit(r["code"])
    return r


def flag(argv, name, default=None):
    if name in argv:
        i = argv.index(name)
        if i + 1 >= len(argv):
            sys.exit(f"[builderbot] ERROR: {name} takes a value")
        v = argv[i + 1]
        del argv[i:i + 2]
        return v
    return default


def lent():
    argv = sys.argv[1:]
    op = argv[0]
    rest = argv[1:]
    if op == "lease":
        r = use("status", quiet=True)
        left = r.get("left")
        print(f"{r['model']}, lent to {os.environ.get('BB_PHONE_PROJECT')} by {r.get('by') or 'its owner'}"
              + (f", {left // 60} min left" if left is not None else ", until taken back"))
        print("apps: " + (", ".join(r.get("pkgs") or []) or "none yet: bb phone install dist/APP.apk"))
    elif op == "shot":
        print(use("shot", quiet=True)["path"])
    elif op == "record":
        print(use("record", {"seconds": rest[0] if rest else 10}, quiet=True)["path"])
    elif op == "install":
        if not rest:
            sys.exit("usage: bb phone install dist/APP.apk")
        print(f"installed {use('install', {'file': rest[0]}, quiet=True)['pkg']}")
    elif op in ("start", "stop", "ime"):
        use(op, {"pkg": rest[0] if rest else ""})
    elif op == "log":
        lines = flag(rest, "--lines", 500)
        use("log", {"pkg": rest[0] if rest else "", "lines": lines})
    elif op == "ui":
        use("ui")
    elif op == "touch":
        if not rest:
            sys.exit("usage: bb phone touch tap X Y | hold X Y [--ms N] | glide X Y X Y... [--ms N] | text \"...\" | key NAME")
        kind = rest[0]
        ms = flag(rest, "--ms")
        a = {"kind": kind}
        if kind in ("tap", "hold"):
            a.update(x=rest[1] if len(rest) > 1 else None, y=rest[2] if len(rest) > 2 else None)
            if ms:
                a["ms"] = ms
        elif kind == "glide":
            a.update(points=rest[1:], ms=ms or 40)
        elif kind == "text":
            a["text"] = " ".join(rest[1:])
        elif kind == "key":
            a["key"] = rest[1] if len(rest) > 1 else ""
        use("touch", a)


VERBS = {"status": status, "run": run, "lease": lent, "shot": lent, "record": lent, "install": lent,
         "start": lent, "stop": lent, "ime": lent, "log": lent, "ui": lent, "touch": lent}

if __name__ == "__main__":
    VERBS[sys.argv[1]]()
