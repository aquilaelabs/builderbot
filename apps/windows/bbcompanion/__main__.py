"""The BuilderBot companion app (R270): a folder on this machine kept in step
with a BuilderBot project, as a node's synced copy is.

    python -m bbcompanion                      the window (sign in, pick projects, watch them)
    python -m bbcompanion signin URL USER      sign this machine in (asks the password once)
    python -m bbcompanion add PROJECT FOLDER   keep a project in a folder here
    python -m bbcompanion remove PROJECT       stop keeping it (its folder stays)
    python -m bbcompanion run [--once]         keep them in step; --once stops when each is copied
    python -m bbcompanion update               fetch a newer app from the controller, for the next start
    python -m bbcompanion lend PROJECT VERB [-- COMMAND LINE | FILE | PORT]
                                               lend a verb to a project's sessions ({folder} is its folder);
                                               no value takes it back
    python -m bbcompanion signout              forget this machine's token here
"""
import getpass
import os
import platform
import sys
import time

from . import core, creds, settings, update


def _say(msg):
    print(f"bbcompanion: {msg}", flush=True)


def signin(url, user, password=None, name=None):
    password = password if password is not None else getpass.getpass(f"{user}'s BuilderBot password: ")
    name = name or platform.node() or "a PC"
    r = core.sign_in(url, user, password, name)
    if r.get("error"):
        _say(r["error"])
        return 1
    creds.save({"url": url.rstrip("/"), "token": r["token"], "device": r["device"]["id"], "account": r["account"]})
    s = settings.load()
    s["url"] = url.rstrip("/")
    settings.save(s)
    _say(f"signed in as {r['account']} on {r['device']['name']}")
    return 0


def companion():
    c, s = creds.load(), settings.load()
    if not c.get("token"):
        _say("not signed in: python -m bbcompanion signin URL USER")
        return None
    if not s["picked"]:
        _say("no project picked: python -m bbcompanion add PROJECT FOLDER")
        return None
    return core.Companion(c["url"], c["token"], s["picked"], settings.data_dir(), pin=s.get("pin", ""),
                          lend=s.get("lend"))


def run(once=False, timeout=600):
    comp = companion()
    if not comp:
        return 1
    comp.start()
    end = time.monotonic() + timeout
    while True:
        time.sleep(1)
        st = comp.status()
        if st["error"]:
            _say(st["error"])
        if once and st["projects"] and all(p.get("ready") for p in st["projects"].values()):
            _say("in step: " + ", ".join(sorted(st["projects"])))
            return 0
        if once and time.monotonic() > end:
            _say("not in step before the time ran out")
            return 1


def main(argv):
    if not argv:
        from . import app
        return app.main()
    cmd, rest = argv[0], argv[1:]
    if cmd == "signin" and len(rest) >= 2:
        return signin(rest[0], rest[1], os.environ.get("BB_COMPANION_PASSWORD"))
    if cmd == "add" and len(rest) == 2:
        s = settings.load()
        s["picked"][rest[0]] = os.path.abspath(rest[1])
        settings.save(s)
        _say(f"{rest[0]} is kept in {s['picked'][rest[0]]}")
        return 0
    if cmd == "remove" and len(rest) == 1:
        s = settings.load()
        s["picked"].pop(rest[0], None)
        settings.save(s)
        return 0
    if cmd == "run":
        return run(once="--once" in rest)
    if cmd == "lend" and len(rest) >= 2:
        from . import pc
        project, verb, value = rest[0], rest[1], [a for a in rest[2:] if a != "--"]
        if verb not in pc.VERBS or not pc.VERBS[verb]:
            _say(f"lend one of {', '.join(v for v, k in pc.VERBS.items() if k)} (the stops and a picture come with them)")
            return 2
        s = settings.load()
        conf = s["lend"].setdefault(project, {})
        kind = pc.VERBS[verb]
        if not value:
            conf.pop(verb, None)
        else:
            conf[verb] = value if kind == "argv" else int(value[0]) if kind == "port" else value[0]
        if not conf:
            s["lend"].pop(project, None)
        settings.save(s)
        _say(f"{project} is lent: {', '.join(pc.lent_verbs(conf)) or 'nothing'}")
        return 0
    if cmd == "update":
        c = creds.load()
        if not c.get("token"):
            _say("not signed in: python -m bbcompanion signin URL USER")
            return 1
        got = update.check(core.DeviceDoor(c["url"], c["token"], settings.load().get("pin", "")).ctl)
        _say(f"{got['pending']} is fetched and starts next time" if got.get("pending")
             else f"{got['current']} is the newest this controller holds" if got.get("current") else got.get("said", ""))
        return 0
    if cmd == "signout":
        creds.forget()
        _say("this machine's token is forgotten here; Disconnect it on the Devices list to end it at the controller too")
        return 0
    print(__doc__)
    return 2


def entry():
    """The packaged app's start (a .pyz or an .exe): an update fetched last
    time swapped in first, then the app."""
    update.apply_pending()
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    entry()
