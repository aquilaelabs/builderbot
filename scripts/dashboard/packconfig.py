"""What a pack is configured with on each node (R172): the answers to the
fields its manifest's config block asks for, kept here per node and pack,
a secret sealed under the install key and never read back by the page
(only replaced), the rest plain. A node is handed its own in the hello
(for_node): each pack's values with the secrets opened and the environment
names a verb reads them as, which the agent writes into the store for
that pack's verbs. The model router is not kept here: its service keeps
its own record (router.py), and the Library sends its Configure there.
  STATE/packconfig.json   {nid: {pack: {field: value | "sealed:..." | [rows] | bool | [projects]}}}
  STATE/packconfig-people.json  {nid: {pack: {uid: {field: ...}}}}: the
                          fields a manifest scopes to a person (R172 step 5),
                          each account's own on that node, a secret sealed
                          under the account's own key (accountkeys), so it
                          opens only as that account's sign-ins do. The hello
                          hands each account's to the node, which writes them
                          into that account's home, read by its sessions'
                          verbs over the node's.
"""
import base64
import json
import threading
from pathlib import Path

STATE = None
write_json = None
seal = None
unseal = None
sealing = None
store_root = None          # nid -> the node's toolchain store root, for the hello
account_key = None         # uid -> its own key (32 bytes), or None while it is locked
open_with = None           # signing.open_with(key, blob): a seal under an account's own key opened
SEALED = "sealed:"
_lock = threading.RLock()


def configure(**deps):
    globals().update({k: v for k, v in deps.items() if k in globals()})
    if "state" in deps:
        globals()["STATE"] = Path(deps["state"])


def _file():
    return STATE / "packconfig.json"


def _load():
    try:
        d = json.loads(_file().read_text())
    except (OSError, ValueError, AttributeError):
        return {}
    return d if isinstance(d, dict) else {}


def _save(d):
    write_json(_file(), d)


def _keep(v):
    if seal and sealing and sealing():
        return SEALED + base64.b64encode(seal(str(v).encode())).decode()
    return str(v)


def _open(v):
    v = str(v or "")
    if v.startswith(SEALED):
        try:
            return unseal(base64.b64decode(v[len(SEALED):])).decode() if unseal else ""
        except Exception:                                   # noqa: BLE001 (Locked, or damaged: no value)
            return ""
    return v


def node_fields(fields):
    return [f for f in fields or [] if f.get("scope") != "person"]


def person_fields(fields):
    return [f for f in fields or [] if f.get("scope") == "person"]


def _people_file():
    return STATE / "packconfig-people.json"


def _people():
    try:
        d = json.loads(_people_file().read_text())
    except (OSError, ValueError, AttributeError):
        return {}
    return d if isinstance(d, dict) else {}


def _seal_for(uid, s):
    k = account_key(uid) if account_key else None
    if not k or not seal:
        return None
    return SEALED + base64.b64encode(seal(s.encode(), key=k)).decode()


def _open_for(uid, v):
    v = str(v or "")
    if not v.startswith(SEALED):
        return v
    k = account_key(uid) if account_key else None
    if not k or not open_with:
        return None
    try:
        return open_with(k, base64.b64decode(v[len(SEALED):])).decode()
    except Exception:                                   # noqa: BLE001 (damaged, or another key: no value)
        return ""


def set_mine(nid, pack, fields, values, uid):
    """Keep a person's own answers to a pack's person-scoped fields on a
    node (R172 step 5): {ok, values} or {error}. A secret is sealed under
    the account's own key, refused while that key is locked."""
    fields = person_fields(fields)
    if not fields:
        return {"error": "this pack asks nothing of each person"}
    if not isinstance(values, dict):
        return {"error": "the configuration is an object of field values"}
    with _lock:
        d = _people()
        rec = d.setdefault(str(nid), {}).setdefault(str(pack), {}).setdefault(str(uid), {})
        new = {}
        for f in fields:
            if f["kind"] == "secret":
                s = str(values.get(f["name"]) or "").strip()
                if s == "clear":
                    new[f["name"]] = ""
                elif not s:
                    new[f["name"]] = rec.get(f["name"], "")
                elif "\n" in s or len(s) > 400:
                    return {"error": f"{f['label']} is one line, 400 characters at most"}
                else:
                    kept = _seal_for(uid, s)
                    if kept is None:
                        return {"error": "your key is locked: unlock it on your Profile, then save"}
                    new[f["name"]] = kept
                continue
            val, why = _row_value(dict(f, kind=f["kind"]), values.get(f["name"]), rec.get(f["name"]))
            if why:
                return {"error": why}
            new[f["name"]] = val
        for f in fields:
            if f.get("required") and new.get(f["name"]) in ("", [], None):
                return {"error": f"{f['label']} is required"}
        d[str(nid)][str(pack)][str(uid)] = new
        write_json(_people_file(), d)
    return {"ok": True, "values": get_mine(nid, pack, fields, uid)}


def get_mine(nid, pack, fields, uid):
    """A person's own answers on a node for the page, a secret as set or not."""
    rec = ((_people().get(str(nid)) or {}).get(str(pack)) or {}).get(str(uid)) or {}
    return {f["name"]: _shown(f, rec.get(f["name"], False if f["kind"] == "switch" else [] if f["kind"] in ("list", "projects") else ""))
            for f in person_fields(fields)}


def _env_of(fields, opened):
    env = {}
    for f in fields:
        if f.get("env") and f["name"] in opened:
            v = opened[f["name"]]
            env[f["env"]] = ("1" if v else "") if f["kind"] == "switch" else json.dumps(v) if f["kind"] in ("list", "projects") else str(v or "")
    return env


def for_people(nid, manifests):
    """The hello's rows of each account's own values on a node:
    [{uid, pack, env}], a secret opened under the account's key; an account
    whose key is locked is left out until it is open, as its sign-ins are."""
    out = []
    for pack, people in ((_people().get(str(nid)) or {}).items()):
        fields = person_fields(manifests.get(pack))
        if not fields:
            continue
        for uid, vals in (people or {}).items():
            opened, locked = {}, False
            for f in fields:
                if f["name"] not in vals:
                    continue
                if f["kind"] == "secret":
                    o = _open_for(uid, vals[f["name"]])
                    if o is None:
                        locked = True
                        break
                    opened[f["name"]] = o
                else:
                    opened[f["name"]] = vals[f["name"]]
            if not locked:
                out.append({"uid": str(uid), "pack": pack, "env": _env_of(fields, opened)})
    return out


def _row_value(field, v, was):
    """One field's value checked by its kind, or (None, why). A secret left
    empty keeps what it had, "clear" takes it out."""
    kind = field["kind"]
    if kind == "secret":
        s = str(v or "").strip()
        if s == "clear":
            return "", ""
        if not s:
            return was if was is not None else "", ""
        if "\n" in s or len(s) > 400:
            return None, f"{field['label']} is one line, 400 characters at most"
        return _keep(s), ""
    if kind == "text":
        s = str(v or "").strip()
        if "\n" in s or len(s) > 400:
            return None, f"{field['label']} is one line, 400 characters at most"
        return s, ""
    if kind == "switch":
        return v is True, ""
    if kind == "choice":
        s = str(v or "")
        if s and s not in [c["value"] for c in field.get("choices") or []]:
            return None, f"{field['label']} is one of {', '.join(c['value'] for c in field.get('choices') or [])}"
        return s, ""
    if kind == "projects":
        v = [] if v is None else v
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            return None, f"{field['label']} lists project names"
        return sorted({x for x in v if x})[:200], ""
    if kind == "list":
        v = [] if v is None else v
        if not isinstance(v, list):
            return None, f"{field['label']} is a list of rows"
        rows = []
        kept = was if isinstance(was, list) else []
        for i, r in enumerate(v[:24]):
            if not isinstance(r, dict):
                return None, f"{field['label']}: a row is an object"
            row = {}
            for sub in field.get("fields") or []:
                old = kept[i].get(sub["name"]) if i < len(kept) and isinstance(kept[i], dict) else None
                val, why = _row_value(sub, r.get(sub["name"]), old)
                if why:
                    return None, f"{field['label']}, row {i + 1}: {why}"
                row[sub["name"]] = val
            rows.append(row)
        return rows, ""
    return None, f"{field['label']}: unknown kind"


def set_values(nid, pack, fields, values):
    """Keep a pack's answers on a node, each checked by its field: {ok,
    values: as get() shows them} or {error}. A required field left empty
    is said."""
    if not isinstance(values, dict):
        return {"error": "the configuration is an object of field values"}
    with _lock:
        d = _load()
        rec = d.setdefault(str(nid), {}).setdefault(str(pack), {})
        new = {}
        for f in node_fields(fields):
            val, why = _row_value(f, values.get(f["name"]), rec.get(f["name"]))
            if why:
                return {"error": why}
            if f.get("required") and val in ("", [], None):
                return {"error": f"{f['label']} is required"}
            new[f["name"]] = val
        d[str(nid)][str(pack)] = new
        _save(d)
    return {"ok": True, "values": get(nid, pack, fields)}


def _shown(field, v):
    """A value as the page may see it: a secret as whether it is set."""
    if field["kind"] == "secret":
        return bool(v)
    if field["kind"] == "list":
        return [{sub["name"]: _shown(sub, r.get(sub["name"])) for sub in field.get("fields") or []} for r in (v if isinstance(v, list) else [])]
    return v


def get(nid, pack, fields):
    """A pack's answers on a node for the page: {field: value}, a secret as
    True when one is kept, never its bytes."""
    rec = (_load().get(str(nid)) or {}).get(str(pack)) or {}
    return {f["name"]: _shown(f, rec.get(f["name"], False if f["kind"] == "switch" else [] if f["kind"] in ("list", "projects") else "")) for f in node_fields(fields)}


def forget(nid, pack):
    """A pack's answers on a node dropped (the pack removed there)."""
    with _lock:
        d = _load()
        if str(nid) in d and str(pack) in d[str(nid)]:
            del d[str(nid)][str(pack)]
            _save(d)


def _opened(field, v):
    if field["kind"] == "secret":
        return _open(v)
    if field["kind"] == "list":
        return [{sub["name"]: _opened(sub, r.get(sub["name"])) for sub in field.get("fields") or []} for r in (v if isinstance(v, list) else [])]
    return v


def for_node(nid, manifests):
    """The hello's rows for a node: [{pack, store, values, env}], the secrets
    opened, `env` the {NAME: value} of the fields that name an environment
    variable (a switch as 1 or "", a list as JSON), for the agent to write
    into the store for the pack's verbs. `manifests` maps a pack's name to
    its config fields."""
    rec = _load().get(str(nid)) or {}
    root = str(store_root(nid) or "") if store_root else ""
    out = []
    for pack, vals in rec.items():
        fields = manifests.get(pack)
        if not fields or not root:
            continue
        fields = node_fields(fields)
        opened = {f["name"]: _opened(f, vals.get(f["name"])) for f in fields if f["name"] in vals}
        env = _env_of(fields, opened)
        out.append({"pack": pack, "store": root, "values": opened, "env": env})
    return out


def seal_all(again=False):
    """After the install key changed (`again`): every sealed secret, at the
    top of a pack's answers or in a list's rows, sealed under the new key."""
    if not again or not (seal and sealing and sealing()):
        return 0
    n = 0

    def reseal(m):
        nonlocal n
        for k, v in list(m.items()):
            if isinstance(v, str) and v.startswith(SEALED):
                m[k] = _keep(_open(v))
                n += 1
            elif isinstance(v, list):
                for r in v:
                    if isinstance(r, dict):
                        reseal(r)
    with _lock:
        d = _load()
        for packs in d.values():
            for vals in packs.values():
                reseal(vals)
        if n:
            _save(d)
    return n
