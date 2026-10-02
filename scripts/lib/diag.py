"""Behind `bb diag` (cmd_diag in bb): the controller's diagnostics, printed as
sections or as the JSON they came as.

Arguments: the sections wanted, or none for all of them. BB_DIAG_AUTH is the
auth header and BB_DIAG_JSON is "1" for the JSON.
"""
import json
import os
import sys

import bbapi


body = {"sections": sys.argv[1:]} if sys.argv[1:] else {}
d = bbapi.call("/api/diag", body, auth=os.environ["BB_DIAG_AUTH"], timeout=60)
if d.get("error") and len(d) == 1:
    sys.exit(f"[builderbot] ERROR: {d['error']}")
if os.environ["BB_DIAG_JSON"] == "1":
    print(json.dumps(d, indent=2))
    raise SystemExit(0)


def head(t):
    print(f"\n== {t} ==")


for name, v in d.items():
    if name == "at":
        continue
    head(name)
    if isinstance(v, dict) and set(v) == {"error"}:
        print(f"  could not read: {v['error']}")
    elif name == "controller":
        print(f"  {v.get('version') or v.get('rev')} built {v.get('built')}, up {v.get('uptime')}")
        print(f"  ships agent {v.get('agent_shipped')}, bundle {v.get('bundle')}, {v.get('git')}")
    elif name == "images":
        print("\n".join(f"  {x}" for x in v) or "  none recorded")
    elif name == "settings":
        print("\n".join(f"  {k} = {val}" for k, val in v.items()) or "  none")
    elif name == "doctor":
        print(f"  ran {v.get('when')}")
        for c in v.get("checks") or []:
            print(f"  [{c['level']}] {c['text']}")
            if c["level"] in ("FAIL", "warn") and c.get("detail"):
                print("\n".join(f"         {x}" for x in c["detail"].splitlines()))
    elif name == "nodes":
        for n in v:
            se, vw = n["session"], n["views"]
            print(f"  {n['name']}: {n['state']}{'' if n['live'] else ', not dialing in'}, seen {n['last_seen']}, "
                  f"agent {n['agent']}{'' if n['agent_current'] else ' (not the shipped one)'}, {n['git'] or 'git ?'}")
            print(f"    sessions {'up' if se['up'] else 'down: ' + (se['why'] or '?')}, "
                  f"views {'built' if vw['built'] else 'not built: ' + (vw['why'] or '?')}, bundle {se['bundle'] or '?'}")
            for e in n.get("mount_errors") or []:
                print(f"    mount: {e}")
    elif name == "plugins":
        for r in v:
            print(f"  {r['account']} on {r['node']}: {', '.join(r['plugins'])}")
        if not v:
            print("  none installed by anybody")
    elif name == "jobs":
        print("  last 24h: " + (", ".join(f"{k} {c}" for k, c in sorted(v.get("last_24h", {}).items())) or "none"))
        for j in v.get("failed") or []:
            print(f"  {j['when']:>8}  {j['state']:<9} {j['type']:<6} {j['project'] or '-'} on {j['node'] or '-'}"
                  f"{' exit ' + str(j['exit']) if j['exit'] is not None else ''}{': ' + j['error'] if j['error'] else ''}")
    elif name == "errors":
        print("\n".join(f"  {x}" for x in v) or "  nothing that looks like a fault")
    elif name == "audit":
        for a in v:
            print(f"  {a['when']:>8}  {a['who']:<24} {a['action']}  {a['target']}")
    elif name == "reports":
        # What sessions on other projects said about BuilderBot, unread:
        # bb report file N or close N "why" answers one.
        if not v:
            print("  none open")
        for r in v:
            print(f"  #{r['id']}  {r.get('when') or ''}  {r.get('project') or 'general (no project)'}"
                  + (f", {r['by']}'s session" if r.get("by") else "")
                  + (f" on {r['node']}" if r.get("node") else "")
                  + (f", build {r['build']}" if r.get("build") else ""))
            print(f"      {r.get('text')}")
            if r.get("conversation"):
                c = r["conversation"]
                print(f"      with the reporter's conversation, {round((c.get('bytes') or 0) / 1024)} KB"
                      + (" (its last part)" if c.get("cut") else "") + ": in bb diag --json reports, and the download")
            if r.get("area"):
                print(f"      area: {r['area']}")
            if r.get("repro"):
                print(f"      repro: {r['repro']}")
