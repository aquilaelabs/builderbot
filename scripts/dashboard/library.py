"""The Library (R170): everything a BuilderBot installs or runs, as one
list of one shape, for one node. The toolchains the catalog offers with
what the node's store holds (toolchains.payload_for_node), the coding
agents with their version against the latest (agentcode.rows), the tool
packs a person added (among the toolchain rows, by their tier), the apps a
NAS runs (nasapps.catalog), the vetted catalog's entries not yet added
(catalogindex) and the companions a person downloads (apps.view), each a
row: kind, tier, name, label, about, platforms, where it stands on the
node (installed, version, latest, update due, a job in flight), and the
one verb the row takes. The page draws the rows; each verb goes to the
read's own endpoint, so nothing is installed two ways.
"""
import re

KINDS = ("toolchain", "agent", "pack", "app", "companion")
TIER_WORDS = {"official": "Official", "vetted": "Vetted", "url": "Sideloaded", "here": "Sideloaded", "sideloaded": "Sideloaded"}


def _an(w):
    """"a" or "an" before a word, by its sound (Any model, OpenCode, xAI)."""
    return ("an " if w[:1].upper() in "AEIOU" or (w[:1] == "x" and w[1:2].isupper()) else "a ") + w


def repo_of(catalog_url):
    """The catalog repository's page from its index address, for Submit to
    the catalog: a raw.githubusercontent.com address names its owner and
    repository; any other address is given as it is, without the file."""
    u = str(catalog_url or "").strip()
    m = re.match(r"https://raw\.githubusercontent\.com/([^/]+)/([^/]+)/", u)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}"
    return u.rsplit("/", 1)[0] if u.endswith((".json", ".sig")) else u.rstrip("/")


def _tier(t):
    return "official" if t in ("official", "") else "vetted" if t == "vetted" else "sideloaded"


def rows(node_payload, agent_rows, apps, catalog_index, companions):
    """The one list, in the page's order: agents, toolchains, packs, apps,
    the catalog's offers, the companions."""
    out = []
    tc = node_payload or {}
    job = tc.get("job") or {}
    busy_on = job.get("current") if job.get("running") and job.get("action") != "check" else ""
    for r in agent_rows or []:
        out.append({"kind": "agent", "tier": "official", "name": r["name"], "label": r.get("label") or r["name"], "agent": r.get("agent", ""),
                    "about": f"What {_an(r.get('for') or r.get('label') or '')} session runs on the node.", "platforms": [],
                    "installed": bool(r.get("installed")), "version": r.get("installed") or "", "latest": r.get("latest") or "",
                    "update": r.get("state") == "update", "running": bool(r.get("running")), "doing": r.get("action") or "",
                    "error": r.get("error") or "",
                    "verb": "update" if r.get("state") == "update" else ("" if r.get("installed") else "install")})
    # What is the machine's own rather than the store's (R102, step 5): the
    # NVIDIA driver and the container toolkit where the node has the card,
    # as toolchain rows carrying their machine record for the card's lines
    # and the driver's version pick.
    for m in tc.get("machine") or []:
        here = bool(m.get("here"))
        ver = m.get("installed") or m.get("loaded") or ""
        out.append({"kind": "toolchain", "tier": "official", "name": m["name"], "label": m.get("label") or m["name"],
                    "about": ("For " + (f"this machine's {m.get('gpu') or m.get('card')}" if m.get("card") else "an NVIDIA card")
                              + ": CUDA, the hardware video encoder and the emulator's GPU rendering need it. It is this machine's own, not a copy on the store.")
                    if m["name"] == "nvidia-driver" else
                    "Lets a container on this machine use the card. From NVIDIA's own package source, which installing adds and removing takes away. Running containers keep running.",
                    "platforms": [], "terms": [], "installed": here, "unknown": False, "version": ver.split("-")[0] if m["name"] != "nvidia-driver" else ver,
                    "latest": (m.get("newer") or "").split("-")[0], "update": bool(m.get("newer")), "updatable": True,
                    "running": busy_on == m["name"], "doing": job.get("action") or "" if busy_on == m["name"] else "",
                    "size": "", "wrong_platform": "", "pinned": [], "pack": None, "machine": m,
                    "verb": "" if not m.get("managed") else "update" if m.get("newer") else ("" if here else "install")})
    packs_here = set()
    for i in tc.get("items") or []:
        pack = i.get("pack")
        if pack:
            packs_here.add(i["name"])
        t = _tier(pack.get("tier", "url") if pack else "official")
        out.append({"kind": "pack" if pack else "toolchain", "tier": t, "name": i["name"], "label": i.get("label") or i["name"],
                    "about": i.get("about") or "", "platforms": i.get("platforms") or [], "terms": i.get("terms") or [],
                    "installed": bool(i.get("installed")), "unknown": bool(i.get("unknown")), "version": i.get("version") or "",
                    "latest": i.get("latest") or "", "update": i.get("state") == "update", "updatable": bool(i.get("updatable")),
                    "running": busy_on == i["name"], "doing": job.get("action") or "" if busy_on == i["name"] else "",
                    "size": i.get("size") or "", "wrong_platform": i.get("wrong_platform") or "", "pinned": i.get("pinned_by") or i.get("pinned") or [],
                    # The open row's lines, as the Toolchains page draws them (step 2).
                    "tool": i.get("tool") or "", "system": i.get("system"), "needs": i.get("needs") or [], "needed_by": i.get("needed_by") or [],
                    "needs_missing": i.get("needs_missing") or [], "path": i.get("path") or "", "verified": i.get("verified"), "reopen": i.get("reopen") or 0,
                    "pack": {k: pack.get(k) for k in ("url", "commit", "by", "at", "tier", "verbs", "here")} if pack else None,
                    "verb": "update" if i.get("state") == "update" else ("" if i.get("installed") else "install")})
    for a in apps or []:
        out.append({"kind": "app", "tier": _tier(a.get("tier", "official")), "name": a["id"], "label": a["name"], "about": a.get("what") or "", "platforms": ["linux/*"],
                    "by": a.get("by") or "", "at": a.get("at") or 0,
                    "port": a.get("port"), "media": bool(a.get("media")), "secrets": a.get("secrets") or [],
                    # Its compose file as the catalog holds it, and the blanks New container fills (step 2).
                    "compose": a.get("compose") or "", "blanks": sorted(set(re.findall(r"\$\{([A-Z_]+)\}", a.get("compose") or ""))),
                    "installed": False, "version": "", "latest": "", "update": False, "running": False, "verb": "install"})
    # The shipped rows by the names the catalog gives them (a toolchain's
    # colon as a hyphen, an agent by its id): an official entry naming one is
    # that row, listed once (R170 step 6).
    shipped = {i["name"].replace(":", "-") for i in tc.get("items") or []} | {r.get("agent", "") for r in agent_rows or []}
    for e in (catalog_index or {}).get("packs") or []:
        # One added already is among the items with its pack; one the catalog
        # withdrew is not offered (the bell says so to an install that holds it).
        if e["name"] in packs_here or e.get("withdrawn") or (e.get("tier") == "official" and e["name"] in shipped):
            continue
        out.append({"kind": "pack", "tier": _tier(e.get("tier")), "name": e["name"], "label": e["name"], "about": e.get("about") or "",
                    "platforms": e.get("platforms") or [], "installed": False, "version": "", "latest": e.get("commit", "")[:12], "update": False,
                    "running": False, "catalog": {"url": e["url"], "commit": e["commit"], "sha256": e["sha256"], "path": e.get("path", "")}, "verb": "add"})
    for c in (companions or {}).get("apps") or []:
        if not c.get("offered"):
            continue
        first = (c.get("files") or [None])[0]
        out.append({"kind": "companion", "tier": "official", "name": c["name"], "label": c.get("title") or c["name"], "about": c.get("does") or "",
                    "platforms": [], "installed": False, "version": c.get("version") or "", "latest": "", "update": False, "running": False,
                    "dev": bool(c.get("dev")), "download": first, "files": c.get("files") or [], "absent": c.get("absent") or "",
                    "verb": "download" if first else ""})
    return out
