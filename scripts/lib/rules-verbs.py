"""Behind `bb rules` (cmd_rules in bb): the house rules, the operator's on
the Briefing tab and a session's own through add, edit and rm here, read
and written through dashboard/rules.py, which holds the ownership and the
log.

Arguments: rules.py's path, the project, then the words of the verb
(list, --prompt, --json, add, edit, rm, history, ...); --global anywhere
asks about the rules that apply to every project. DASHBOARD_STATE says
where the notebook's files are and BB_ACCOUNT_UID which seat this
session sits in.
"""
import json
import os
import sys
import time

import dash

reg = dash.load("rules", dash.beside(sys.argv[1]))
statefile = dash.statefile(dash.beside(sys.argv[1]))

_rules_state = os.environ.get("DASHBOARD_STATE", "/config")
reg.configure(write_json=statefile.write_json, state=_rules_state,
              actor=lambda: dash.account_name(_rules_state))

proj, argv = sys.argv[2], sys.argv[3:]
# `--global` is the rules that apply to EVERY project (R63). Reading one is
# anybody's; writing one is refused by rules.py itself, because the key is the
# global one and everything bb writes is a session's.
if "--global" in argv:
    argv = [a for a in argv if a != "--global"]
    proj = reg.GLOBAL
# `--format json|yaml|markdown` on a list or a show (R167); `--json` stays
# the plain list the page, the briefing and bb rules check read.
if "--json" in argv:
    fmt, argv = "text", ["--json"] + [a for a in argv if a != "--json"]
else:
    fmt, argv = dash.format_flag(argv)
op = argv[0] if argv else "list"
rest = argv[1:]
_records = dash.load("records", dash.beside(sys.argv[1]))


def dump_rules(rs):
    sys.stdout.write(_records.dump(_records.document("rules", rs, proj), fmt))
import pending  # noqa: E402 (rules.py put its directory on sys.path)

# What bb-tty puts in front of a session. Empty output and status 0 when
# there are no rules, so the caller can test it with `[ -z ]`.
if op == "--prompt":
    b = reg.block(proj)
    if b:
        print(b)
elif op == "--json":
    print(json.dumps(reg.effective(proj)))
elif op == "show":
    if not rest:
        sys.exit("usage: bb rules show <name>")
    want = rest[0].strip().lower()
    for r in reg.effective(proj):
        if r["name"] == want:
            if fmt != "text":
                dump_rules([r]); break
            print(r["text"])
            if r.get("doc"):
                print(f"\ndefined in full in {r['doc']}")
            if r.get("check"):
                print(f"checked by: {r['check']}   (bb rules check {r['name']})")
            if r.get("refuse"):
                print("refuses: " + ", ".join(r["refuse"]))
            if r.get("replaces"):
                print(f"in place of the global rule {r['replaces']}")
            if r.get("why"):
                print(f"\nwhy: {r['why']}")
            break
    else:
        for g in reg.ALWAYS:
            if g["name"] == want:
                print(g["text"] + "\nrefuses: " + ", ".join(g["refuse"])
                      + "\n(the briefing's, refused in every project)")
                break
        else:
            names = ", ".join(r["name"] for r in reg.effective(proj)) or "none"
            sys.exit(f"no rule called {want} here; this project has: {names}")
elif op == "add":
    if len(rest) < 2:
        sys.exit('usage: bb rules add <name> "the rule" [--files GLOB,...] [--words W,...] '
                 '[--refuse "CMD, CMD"] [--replaces GLOBAL-RULE] [--why "..."]')
    name, said, paths_, wds_, doc_, chk_, i = rest[0], [], "", "", "", "", 1
    ref_, repl_, why_ = "", "", ""
    while i < len(rest):
        if rest[i] == "--files" and i + 1 < len(rest):
            paths_ = rest[i + 1]; i += 2
        elif rest[i] == "--words" and i + 1 < len(rest):
            wds_ = rest[i + 1]; i += 2
        elif rest[i] == "--doc" and i + 1 < len(rest):
            doc_ = rest[i + 1]; i += 2
        elif rest[i] == "--check" and i + 1 < len(rest):
            chk_ = rest[i + 1]; i += 2
        elif rest[i] == "--refuse" and i + 1 < len(rest):
            ref_ = rest[i + 1]; i += 2
        elif rest[i] == "--replaces" and i + 1 < len(rest):
            repl_ = rest[i + 1]; i += 2
        elif rest[i] == "--why" and i + 1 < len(rest):
            why_ = rest[i + 1]; i += 2
        else:
            said.append(rest[i]); i += 1
    r = reg.add(proj, name, " ".join(said), paths=paths_, words=wds_, by="claude",
                doc=doc_, check=chk_, refuse=ref_, replaces=repl_, why=why_)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    if r.get("held"):
        print(f"held for approval as the rule {r['held']['number']}: it takes "
              "effect when the operator approves it on the notebook. `bb rules "
              "pending` lists what is waiting; you are told on a later turn what "
              "they decided")
        sys.exit(0)
    print(f"added {r['rule']['name']}: yours, marked as a session's on the "
          "Briefing tab, and in front of every session started here")
elif op == "edit":
    if len(rest) < 2:
        sys.exit('usage: bb rules edit <name> "what it should say now"')
    held = pending.held(proj, "rules", rest[0].strip().lower())
    if held is not None:
        # Reworded before it was even approved: the rewording rides behind
        # the held rule, so the operator reads both and the final wording wins.
        r = pending.hold(proj, "rules", "edit",
                         {"name": held["number"], "text": " ".join(rest[1:])},
                         f"reword {held['number']}: {' '.join(rest[1:])}",
                         number=held["number"], after=held["id"])
        if r.get("error"):
            sys.exit(f"[builderbot] ERROR: {r['error']}")
        print(f"held behind the rule {held['number']}: it lands with it when the "
              "operator approves it, and goes if they deny it")
        sys.exit(0)
    # `edit NAME "text"`, or `edit NAME --doc PATH --check CMD --files ... --words ...`
    # leaving the words alone; "" clears a flag.
    said, flags, i = [], {}, 1
    while i < len(rest):
        if rest[i] in ("--doc", "--check", "--files", "--words", "--refuse", "--replaces", "--why") and i + 1 < len(rest):
            flags[{"--files": "paths", "--words": "words"}.get(rest[i], rest[i][2:])] = rest[i + 1]
            i += 2
        else:
            said.append(rest[i]); i += 1
    if not said and not flags:
        sys.exit('usage: bb rules edit <name> "what it should say now" [--doc PATH] [--check CMD] '
                 '[--refuse "CMD, CMD"] [--replaces GLOBAL-RULE] [--why "..."]')
    r = reg.edit(proj, rest[0], text=" ".join(said) if said else None, by="claude", **flags)
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    print(f"reworded {rest[0]}" if said else f"updated {rest[0]}: {', '.join(flags)}")
elif op == "rm":
    if not rest:
        sys.exit('usage: bb rules rm <name> ["why it went"]')
    if pending.held(proj, "rules", rest[0].strip().lower()) is not None:
        sys.exit(f"[builderbot] ERROR: the rule {rest[0]} is still waiting for the "
                 "operator's approval; there is nothing to drop yet. `bb rules pending`")
    r = reg.remove(proj, rest[0], why=" ".join(rest[1:]), by="claude")
    if r.get("error"):
        sys.exit(f"[builderbot] ERROR: {r['error']}")
    print(f"dropped {r['removed']}")
elif op == "pending":
    # The rules' half of what is waiting for the operator (roadmap #27).
    rs = pending.listing(proj, "rules")
    if not rs:
        print(f"no rule is waiting for approval on {proj}")
    for r in rs:
        when = time.strftime("%d %b %H:%M", time.localtime(r.get("at", 0)))
        lead = "  ↳ " if r.get("after") is not None else "  "
        print(f"{lead}{when}  {r.get('summary', '')}")
    print(f"  (this project's setting for new rules from a session: "
          f"{pending.mode(proj, 'rules')})")
elif op == "history":
    rows = reg.history(proj, limit=20)
    if not rows:
        print("nothing has changed the rules here yet")
    for e in rows:
        when = time.strftime("%d %b %H:%M", time.localtime(e.get("at", 0)))
        print(f"  {when}  {dash.wrote(e):>6}  {e.get('act', ''):<7} "
              f"{e.get('name', '')}  {e.get('text', '')[:60]}")
        for k in ("was", "why"):
            if e.get(k):
                print(f"{'':>32}{k}: {e[k][:60]}")
        if e.get("approved"):
            print(f"{'':>32}approved by the operator")
elif op == "list":
    rs = reg.effective(proj)
    if fmt != "text":
        dump_rules(rs); sys.exit(0)
    if not rs:
        print("no house rules on this project yet. The operator writes them on "
              "the notebook's Briefing tab; `bb rules add NAME \"...\"` leaves "
              "one of yours there, marked as a session's.")
        sys.exit(0)
    p = reg.payload(proj)
    print(f"{p['standing']} standing, {p['conditional']} conditional; "
          f"{p['chars']} characters in front of every session here")
    # The name column is as wide as the longest name (B233): a fixed 22 ran
    # no-credentials-in-the-repo straight into its text.
    w = max([22] + [len(r['name']) + 1 for r in rs])
    for r in rs:
        when = ""
        if reg.conditional(r):
            bits = list(r.get("paths") or []) + list(r.get("words") or [])
            when = "  [" + ", ".join(bits[:4]) + ("…" if len(bits) > 4 else "") + "]"
        first = (r["text"].strip().splitlines() or [""])[0]
        mine = "*" if r.get("by") == "claude" else " "
        frame = ((" [global]" if r.get("scope") == "global" else "")
                 + (" [doc]" if r.get("doc") else "") + (" [check]" if r.get("check") else "")
                 + (" [refuses]" if r.get("refuse") else "")
                 + (f" [for {r['replaces']}]" if r.get("replaces") else ""))
        print(f" {mine}{r['name']:<{w}}{first[:60]}{when}{frame}")
    print("\n`bb rules show <name>` for one in full. A * is one a session "
          "wrote: yours to `edit` or `rm`. The rest are the operator's: read "
          "them, and say in your reply if one looks wrong.")
else:
    print(f"[builderbot] ERROR: unknown: bb rules {op}", file=sys.stderr)
    sys.exit(1)
