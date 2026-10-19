#!/usr/bin/env python3
"""Everything behind the dashboard's Emulator page: the Android system images
on each node's toolchain store, which ones could be added, and the job that
adds or removes one.

An image is not a toolchain. A toolchain is one thing at one version; a system
image exists at every API level at once, and which one to have is a question
about what is being tested. It lives on the toolchain store all the same, so
an image job waits for an Android toolchain job on a store (toolchains.store_busy)
and run through the same bundle on the node.

The controller runs no emulator, so this is about nodes only. Which images a
node HAS is its census (the agent walks its store); which images EXIST is
Google's index, read here once an hour: an image is the same bytes on every
host, so a node needs no network of its own to be offered one.
"""
import re
import threading
import time
from typing import Any

import toolchains

nodes: Any = None     # the node store, once the server has opened it

# What a node needs before the tab is worth opening: sdkmanager to install an
# image, and the emulator to boot one. Catalog names, so the Toolchains tab's
# rows are what the reason points at.
NEEDS = ("android-tools", "android:emulator")


# ---- which images exist ----------------------------------------------------

# `reads` counts the index reads that have ended, landed or not: the
# emulator revision is it, so a read's start (which the asking tab already
# knows of, from the answer's "loading") moves nothing and its end does (B757).
_choices = {"at": 0.0, "rows": [], "flavors": [], "loading": False, "reads": 0}
_choices_lock = threading.Lock()
CHOICES_TTL = 3600            # the index changes when Google ships a level


def choices():
    """Every system image that could be installed, and what each flavor is for.

    Two questions the operator cannot answer from here otherwise: which API
    levels exist, and what one weighs before it is fetched. Both come out of
    sdkmanager's own index, which is the only place a download size lives
    before the download; bb reads it, this asks bb.

    An hour's cache, and read off the request: four XML indexes on a cold
    cache is a second or two of network, and the first draw of the tab should
    not wait on Google for a picker most visits never touch. The tab says it
    is reading, and the picker arrives on the next poll.
    """
    if time.monotonic() - _choices["at"] < CHOICES_TTL and _choices["rows"]:
        return _choices
    with _choices_lock:
        if _choices["loading"]:
            return _choices
        _choices["loading"] = True
    threading.Thread(target=_load_choices, daemon=True).start()
    return _choices


def _load_choices():
    rows, flavors = [], []
    r = toolchains.run([toolchains.BB, "emu", "images", "--available"], timeout=120)
    if r["code"] == 0:
        for line in r["out"].splitlines():
            f = line.rstrip().split("\t")
            if len(f) == 4 and f[0].startswith("system-images;") and f[3].isdigit():
                rows.append({"id": f[0], "api": f[1], "kind": f[2],
                             # The rendered size for the picker, and the raw
                             # kilobytes beside it for the headroom check.
                             "kb": int(f[3]) // 1024,
                             "size": toolchains.human_kb(int(f[3]) // 1024)})
    r = toolchains.run([toolchains.BB, "emu", "flavors"], timeout=30)
    if r["code"] == 0:
        for line in r["out"].splitlines():
            f = line.rstrip().split("\t")
            if len(f) >= 3:
                flavors.append({"kind": f[0], "label": f[2],
                                "about": f[3] if len(f) > 3 else ""})
    with _choices_lock:
        if rows:
            _choices.update(at=time.monotonic(), rows=rows, flavors=flavors)
        _choices["loading"] = False
        _choices["reads"] += 1


def image_kb(image_id):
    """What the index says this image weighs, in KB, or 0."""
    for r in choices()["rows"]:
        if r["id"] == image_id:
            return int(r.get("kb") or 0)
    return 0


def is_choosable(image_id):
    """One of the ids the picker was drawn from. The rule every executing
    endpoint here follows: what reaches a command line is a string this
    server handed out."""
    return any(r["id"] == image_id for r in choices()["rows"])


# ---- which images a node has -----------------------------------------------

def node_images(n):
    """The system images a node reports, in the shape the tab draws.

    The node walks its store for the ids and the AVDs built on them; the size
    is joined here, from Google's index. `du` over a tens-of-gigabytes tree on
    an NFS-mounted store is not something to do on every census for a number
    that is already known. It is the DOWNLOAD size rather than the footprint,
    so the row says where it came from.
    """
    idx = {r["id"]: r for r in choices()["rows"]}
    rows = []
    for im in (n.get("reported") or {}).get("images") or []:
        c = idx.get(im.get("id")) or {}
        rows.append({"id": im.get("id", ""), "api": im.get("api", ""),
                     "kind": im.get("kind", ""), "size": c.get("size", ""),
                     "size_from": "the download size, from Google's index: a node does not "
                                  "measure its image tree" if c.get("size") else "",
                     "avds": list(im.get("avds") or [])})
    rows.sort(key=lambda r: (r["kind"], r["api"]))
    return rows


def is_node_image(n, image_id):
    """One of the images THIS node just reported: a removal names one of those."""
    return any(r["id"] == image_id for r in node_images(n))


def wrong_platform(n):
    """What the Android tools are packaged for, when this node is not one of
    them: a machine that can NEVER hold a system image, as against one that
    has simply not been given the tools yet. A Mac node is the live case (the
    recipes are linux/*), and on it Toolchains keeps both rows behind "Not for
    this node", so pointing at that tab would be pointing at nothing."""
    plat = toolchains.platform_of(n)
    by = {p["name"]: p for p in toolchains.TOOLCHAINS}
    for name in NEEDS:
        tc = by.get(name)
        if tc and not toolchains.supports(tc, plat):
            return ", ".join(tc.get("platforms") or ["linux/amd64"])
    return ""


def missing(n):
    """The catalog labels of what this node lacks for the tab: empty when it
    has both, or when it has not reported its store (not evidence of absence)."""
    if wrong_platform(n):
        return []                       # nothing to install there, ever
    have = toolchains.node_has(n)
    if not have:
        return []
    labels = {p["name"]: p["label"] for p in toolchains.TOOLCHAINS}
    return [labels.get(x, x) for x in NEEDS if x not in have]


def _agent_nodes():
    return [n for n in (nodes.node_list() if nodes else [])
            if n["kind"] == "agent" and n.get("state") != "retired"]


def ready():
    """For the Tools card's button: whether any node has what the tab needs,
    the reason when none does (which is what the ghosted button says), and
    which node the tab should open on, so it does not land on a Mac while the
    Linux box beside it is the one with an emulator."""
    agents = _agent_nodes()
    fit = [n for n in agents
           if toolchains.node_has(n) and not missing(n) and not wrong_platform(n)]
    if fit:
        return {"ready": True, "why": "", "node": fit[0]["id"]}
    if not agents:
        return {"ready": False, "why": "no node is enrolled: the Nodes page enrolls one"}
    can = [n for n in agents if not wrong_platform(n)]
    if not can:
        return {"ready": False,
                "why": "no node runs a platform the Android tools are packaged for "
                       f"({wrong_platform(agents[0])}): an emulator needs one that does"}
    return {"ready": False, "node": can[0]["id"],
            "why": "needs Android command-line tools and the emulator on a node: "
                   "install them from Toolchains"}


# ---- the tab ---------------------------------------------------------------

def _job(nid):
    """The image job in flight on this node, else the last finished one, in
    the shape the tab draws."""
    if not nodes:
        return {"running": False}
    for j in nodes.jobs_for(node_id=nid, type="image", active=True, n=1):
        sp = j.get("spec") or {}
        return {"running": True, "action": sp.get("action", ""), "image": sp.get("image", ""),
                "images": sp.get("images") or [sp.get("image", "")], "current": j.get("step") or "",
                "aborting": bool(j.get("cancel")), "id": j["id"]}
    for j in nodes.jobs_for(node_id=nid, type="image", n=1):
        if j.get("state") in ("succeeded", "failed", "canceled"):
            sp = j.get("spec") or {}
            return {"running": False, "action": sp.get("action", ""), "image": sp.get("image", ""),
                    "state": j["state"], "error": j.get("error") or "", "id": j["id"],
                    "at": j.get("ended") or 0}
    return {"running": False}


def level_of(image_id):
    """The API level an image id is of: android-36, android-36.1 and
    android-36-ext18 are all level 36."""
    m = re.match(r"system-images;android-(\d+)", image_id or "")
    return m.group(1) if m else ""


def needed(n, imgs, rows):
    """[{level, projects, pick}]: each level a project on this node compiles
    against (compileSdk) that no image here is of, with the image to pick:
    the index's plain google_apis image of that level (android-N, else the
    newest android-N.x), or "" while the index has none."""
    held = {level_of(i.get("id", "")) for i in imgs}
    out = []
    for level, who in sorted(toolchains.levels_needed(n["id"]).items(), key=lambda kv: -int(kv[0])):
        if level in held:
            continue
        mine = [r["id"] for r in rows
                if level_of(r["id"]) == level and r.get("kind") == "google_apis"
                and re.fullmatch(r"system-images;android-\d+(\.\d+)?;google_apis;x86_64", r["id"])]
        plain = [i for i in mine if "." not in i.split(";")[1]]
        pick = plain[0] if plain else (sorted(mine, key=lambda i: i.split(";")[1])[-1] if mine else "")
        out.append({"level": level, "projects": sorted({p for p, _ in who}), "pick": pick})
    return out


def payload(nid):
    n = nodes.node(nid) if nodes else None
    if not n or n["kind"] != "agent":
        return {"error": "no such node"}
    rep = n.get("reported") or {}
    store = (rep.get("stores") or {}).get("toolchains") or {}
    imgs = node_images(n)
    c = choices()
    here = {i["id"] for i in imgs}
    return {"node": nid, "name": n["name"], "live": bool(n.get("live")),
            "root": (store.get("path") or "") + ("/" + store["scope"] if store.get("scope") else ""),
            "free_mb": store.get("free_mb"),
            "images": imgs,
            # What could be added, minus what is already here.
            "addable": [x for x in c["rows"] if x["id"] not in here],
            "flavors": c["flavors"],
            "loading": bool(c["loading"]),
            # A node that has not reported its images is not a node with none.
            "known": "images" in rep,
            "missing": missing(n),
            # The levels this node's projects compile against with no image
            # of that level here (R215), each with the index's plain image
            # of it in the rootable flavor to pick, where the index has one.
            "needed": needed(n, imgs, c["rows"]),
            # A node that can never have them, and what they are packaged for:
            # said instead of a link to Toolchains, where both rows sit behind
            # "Not for this node".
            "wrong_platform": wrong_platform(n),
            "platform": toolchains.platform_of(n),
            # Adding or removing an image needs sdkmanager and nothing else;
            # the emulator is only for booting one.
            "sdkmanager": "android-tools" in toolchains.node_has(n)
                          or not toolchains.node_has(n),
            "job": _job(nid)}


def node_job(principal, nid, action, image_id):
    """Queue an image add or removal on a node. Refused, with the reason,
    when the node cannot take it: no sdkmanager there, an id this server did
    not hand out, no room, or the store busy with another job. An add may
    name several (a list: the tab's Install selected, R121), one job adding
    each in turn."""
    ids = list(dict.fromkeys(image_id if isinstance(image_id, list) else [image_id]))
    if not ids or len(ids) > 20 or not all(isinstance(i, str) and i for i in ids) \
            or (action == "remove" and len(ids) != 1):
        return {"error": "name the images: one to remove, up to twenty to add"}
    if not nodes:
        return {"error": "no node store"}
    n = nodes.node(nid)
    if not n or n["kind"] != "agent":
        return {"error": "no such node"}
    wrong = wrong_platform(n)
    if wrong:
        return {"error": f"{n['name']} is {toolchains.platform_of(n)}, and the Android "
                         f"command-line tools and the emulator are packaged for {wrong}: "
                         "no system image can run there"}
    have = toolchains.node_has(n)
    if have and "android-tools" not in have:
        return {"error": f"{n['name']} has no Android command-line tools, and sdkmanager "
                         "is what installs an image: install them from Toolchains first"}
    # What reaches a command line is a string this server handed out: an add
    # names one the picker was drawn from, a removal one THIS node reported.
    if not ((action == "add" and all(is_choosable(i) for i in ids))
            or (action == "remove" and is_node_image(n, ids[0]))):
        return {"error": "not an image this server offered for that"}
    store = ((n.get("reported") or {}).get("stores") or {}).get("toolchains") or {}
    if action == "add":
        need_kb = sum(image_kb(i) for i in ids)
        free = store.get("free_mb")
        if need_kb and free is not None and free * 1024 < need_kb * 1.2:
            return {"error": f"{n['name']}'s toolchain store has {toolchains.human_kb(free * 1024)} "
                             f"free and this needs about {toolchains.human_kb(int(need_kb * 1.2))}: "
                             "point the store somewhere bigger first"}
    busy = toolchains.store_busy(nid)
    if busy:
        return {"error": busy}
    return nodes.job_add(principal, {"node": nid}, "image",
                         {"action": action, "image": ids[0], "images": ids, "step_timeout": 3600, "timeout": 3600 * len(ids) + 600})
