"""A model router as a node feature (R144 step 1, the operator, 26 Oct).

LiteLLM runs as a container on a node the operator picks, with the
provider keys (Anthropic, OpenAI, Google, OpenRouter, xAI, and any
OpenAI-compatible endpoint the operator adds) in its compose file on that
node, root-owned there and never in a session's view; the keys are kept
here sealed under the install key. The node's own Ollama runs beside it
where the operator turns it on (a GPU's memory, or CPU and RAM for small
models), its models pulled and removed from the node's page, as one more
provider behind the router. The router's OpenAI-compatible address is
offered to the projects allowed to use it and to no other: each allowed
project is handed the router node's address and port in its session
network's peers, so a session reaches it and nothing else does, and a
virtual key of the project's own (LiteLLM's /key/generate, under the
master key the controller made) so its spend is its own (/key/info).

  STATE/router.json   {nid: {"deployed": t, "port": 4000, "master": sealed,
                       "providers": {name: sealed key}, "custom": [{name,
                       base, key: sealed}], "ollama": {"on": bool, "models":
                       [...]}, "projects": {project: {"key": sealed,
                       "made": t}}, "models": [...], "models_at": t}}

The compose file (compose_text) is nginx's shape (R171): written through
containers.create_container as a System container, built by a compose job
on the node, so the Containers page lists it with Up, Down and its log.
"""
import base64
import contextlib
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

STATE = None
write_json = None
seal = None
unseal = None
sealing = None
node_list = None
node_name = None
node_addr = None            # nid -> the node's address, as the sessions and this controller reach it
project_names = None        # () -> every project's name
job_add = None
job_get = None              # jid -> the job row with its log
_lock = threading.Lock()
_rev = 0
SEALED = "bbseal:"
PORT = 4000
IMAGE = "ghcr.io/berriai/litellm:main-stable"
OLLAMA_IMAGE = "ollama/ollama:latest"
DB_IMAGE = "postgres:16-alpine"
TIMEOUT = 20
# Each provider: its environment variable in the compose file, the
# wildcard LiteLLM routes to it, and its name on the page.
PROVIDERS = {
    "anthropic": {"env": "ANTHROPIC_API_KEY", "route": "anthropic/*", "label": "Anthropic"},
    "openai": {"env": "OPENAI_API_KEY", "route": "openai/*", "label": "OpenAI"},
    "gemini": {"env": "GEMINI_API_KEY", "route": "gemini/*", "label": "Google (Gemini)"},
    "openrouter": {"env": "OPENROUTER_API_KEY", "route": "openrouter/*", "label": "OpenRouter"},
    "xai": {"env": "XAI_API_KEY", "route": "xai/*", "label": "xAI"},
}
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")


def pack():
    """The router as an official pack (R172): a service a node deploys from
    its Library card, its configuration the fields the Node settings
    section asked before, written to packs/services/model-router by
    tools/packs-export.py and held to this by bb lint."""
    return {"name": "model-router", "label": "Model router", "tier": "official", "platforms": ["linux/amd64", "linux/arm64"], "terms": [],
            "about": "LiteLLM on this node holding your provider keys, Ollama beside it where you turn it on, offered to the projects you allow: "
                     "each is handed its address and a key of its own at a session's start, so its spend is its own. What Start's Any model runs through.",
            "service": {"kind": "router"},
            "config": [{"name": pid, "label": p["label"], "kind": "secret", "help": f"{p['label']}'s API key, written into the router's compose file on this node and never into a session's view"}
                       for pid, p in PROVIDERS.items()]
                      + [{"name": "custom", "label": "Other OpenAI-compatible endpoints", "kind": "list",
                          "help": "each a provider under its own name (NAME/model in the picker)",
                          "fields": [{"name": "name", "label": "Name", "kind": "text"}, {"name": "base", "label": "Address", "kind": "text", "help": "https://host/v1"},
                                     {"name": "key", "label": "API key", "kind": "secret"}]},
                         {"name": "ollama", "label": "Run Ollama beside it", "kind": "switch",
                          "help": "on this node's card where it has one, else its CPU and memory; its models one more provider (ollama/NAME)"},
                         {"name": "projects", "label": "Projects that may use it", "kind": "projects",
                          "help": "each handed the address and its own key at a session's start; a session of any other project cannot reach it"}]}
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,120}$")


def configure(**deps):
    globals().update({k: v for k, v in deps.items() if k in globals()})
    if "state" in deps:
        globals()["STATE"] = Path(deps["state"])


# ---- the record ---------------------------------------------------------------

def _file():
    return STATE / "router.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(d):
    global _rev
    write_json(_file(), d, mode=0o600)
    _rev += 1


def rev():
    return _rev


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


def record(nid):
    return dict(_load().get(str(nid)) or {})


def container_name(nid):
    base = re.sub(r"[^a-z0-9-]", "-", str(node_name(nid) or nid).lower()).strip("-") or "node"
    return f"router-{base}"[:60]


def deployed(devapp, nid):
    name = container_name(nid)
    return bool(devapp.is_file_source(name) and devapp._read_rec(name, devapp.MAIN).get("node") == nid)


def _url(nid, rec=None):
    rec = rec if rec is not None else record(nid)
    addr = node_addr(nid) if node_addr else ""
    return f"http://{addr}:{int(rec.get('port') or PORT)}" if addr else ""


# ---- the compose file -----------------------------------------------------------

def _indent(text, n):
    pad = " " * n
    return "\n".join(pad + ln if ln else ln for ln in text.splitlines())


def litellm_config(rec):
    """LiteLLM's config: one wildcard route per provider with a key, each
    custom endpoint as an OpenAI-compatible route under its name, and the
    node's Ollama where it is on; the master key and the database from the
    environment; what a caller asks for that a provider lacks dropped
    rather than refused."""
    out = ["model_list:"]
    for pid, p in PROVIDERS.items():
        if (rec.get("providers") or {}).get(pid):
            out += [f"  - model_name: \"{p['route']}\"", "    litellm_params:", f"      model: \"{p['route']}\"",
                    f"      api_key: os.environ/{p['env']}"]
    for i, c in enumerate(rec.get("custom") or []):
        out += [f"  - model_name: \"{c['name']}/*\"", "    litellm_params:", "      model: \"openai/*\"",
                f"      api_base: \"{c['base']}\"", f"      api_key: os.environ/CUSTOM_{i}_KEY"]
    if (rec.get("ollama") or {}).get("on"):
        out += ["  - model_name: \"ollama/*\"", "    litellm_params:", "      model: \"ollama_chat/*\"",
                "      api_base: \"http://ollama:11434\""]
    if len(out) == 1:
        out.append("  []")
    out += ["litellm_settings:", "  drop_params: true", "general_settings:",
            "  master_key: os.environ/LITELLM_MASTER_KEY", "  database_url: os.environ/DATABASE_URL", ""]
    return "\n".join(out)


def compose_text(nid, rec, gpu=False):
    """The router's compose file: LiteLLM on the node's address, its
    database beside it, Ollama where it is on (the card given to it where
    the node has one), the keys as the services' environment, the config
    inline."""
    addr = node_addr(nid) if node_addr else ""
    name = container_name(nid)
    port = int(rec.get("port") or PORT)
    env = [f"      LITELLM_MASTER_KEY: \"{_open(rec.get('master'))}\"",
           f"      DATABASE_URL: \"postgresql://litellm:{_open(rec.get('dbpass'))}@db:5432/litellm\""]
    for pid, p in PROVIDERS.items():
        k = _open((rec.get("providers") or {}).get(pid))
        if k:
            env.append(f"      {p['env']}: \"{k}\"")
    for i, c in enumerate(rec.get("custom") or []):
        env.append(f"      CUSTOM_{i}_KEY: \"{_open(c.get('key')) or 'none'}\"")
    out = ["# Written by BuilderBot from a node's Model router section (router.py); Save there rewrites it.",
           "services:",
           "  litellm:",
           f"    image: {IMAGE}",
           f"    container_name: {name}",
           "    restart: unless-stopped",
           "    command: [\"--config\", \"/app/config.yaml\", \"--port\", \"4000\"]",
           "    ports:",
           f"      - \"{addr + ':' if addr else ''}{port}:4000\"",
           "    environment:", *env,
           "    configs:",
           "      - source: litellm_conf",
           "        target: /app/config.yaml",
           "    depends_on:",
           "      - db",
           "  db:",
           f"    image: {DB_IMAGE}",
           "    restart: unless-stopped",
           "    environment:",
           "      POSTGRES_USER: litellm",
           f"      POSTGRES_PASSWORD: \"{_open(rec.get('dbpass'))}\"",
           "      POSTGRES_DB: litellm",
           "    volumes:",
           "      - router_db:/var/lib/postgresql/data"]
    if (rec.get("ollama") or {}).get("on"):
        out += ["  ollama:",
                f"    image: {OLLAMA_IMAGE}",
                "    restart: unless-stopped",
                "    volumes:",
                "      - router_ollama:/root/.ollama"]
        if gpu:
            out += ["    deploy:", "      resources:", "        reservations:", "          devices:",
                    "            - driver: nvidia", "              count: all", "              capabilities: [gpu]"]
    out += ["volumes:", "  router_db:"] + (["  router_ollama:"] if (rec.get("ollama") or {}).get("on") else [])
    out += ["configs:", "  litellm_conf:", "    content: |", _indent(litellm_config(rec).replace("$", "$$"), 6), ""]
    return "\n".join(out)


# ---- the settings a node keeps --------------------------------------------------

def set_keys(nid, req):
    """The provider keys, the custom endpoints, Ollama on or off: kept
    sealed; a key left empty keeps what it had, "clear" takes it out."""
    with _lock:
        d = _load()
        rec = d.setdefault(str(nid), {})
        rec.setdefault("port", PORT)
        if not rec.get("master"):
            rec["master"] = _keep("sk-" + secrets.token_hex(24))
        if not rec.get("dbpass"):
            rec["dbpass"] = _keep(secrets.token_hex(16))
        prov = rec.setdefault("providers", {})
        for pid in PROVIDERS:
            v = str((req.get("providers") or {}).get(pid) or "").strip() if isinstance(req.get("providers"), dict) else ""
            if v == "clear":
                prov.pop(pid, None)
            elif v:
                prov[pid] = _keep(v)
        if isinstance(req.get("custom"), list):
            kept = {c.get("name"): c for c in rec.get("custom") or []}
            out = []
            for c in req["custom"][:8]:
                if not isinstance(c, dict):
                    continue
                name, base = str(c.get("name") or "").strip().lower(), str(c.get("base") or "").strip()
                if not NAME_RE.match(name) or name in PROVIDERS or name == "ollama":
                    return {"error": f"a custom provider's name is letters, digits and dashes, and not one of {', '.join(PROVIDERS)}: {name or 'none'}"}
                if not base.startswith(("http://", "https://")):
                    return {"error": f"{name}'s address must start with http:// or https://"}
                key = str(c.get("key") or "").strip()
                was = kept.get(name) or {}
                out.append({"name": name, "base": base.rstrip("/"), "key": _keep(key) if key else was.get("key", "")})
            rec["custom"] = out
        if "ollama" in req:
            rec.setdefault("ollama", {})["on"] = req.get("ollama") is True
        _save(d)
    return {"ok": True, **status(nid)}


def status(nid):
    rec = record(nid)
    return {"node": nid, "deployed": bool(rec.get("deployed")), "port": int(rec.get("port") or PORT), "url": _url(nid, rec),
            "providers": {pid: bool((rec.get("providers") or {}).get(pid)) for pid in PROVIDERS},
            "custom": [{"name": c["name"], "base": c["base"], "key": bool(c.get("key"))} for c in rec.get("custom") or []],
            "ollama": {"on": bool((rec.get("ollama") or {}).get("on")), "models": (rec.get("ollama") or {}).get("models") or [],
                       "job": (rec.get("ollama") or {}).get("job") or ""},
            "projects": sorted((rec.get("projects") or {}).keys()),
            "models": rec.get("models") or [], "models_at": rec.get("models_at", 0),
            "spend": rec.get("spend") or {}}


# ---- deploy, apply, remove ------------------------------------------------------

def _ready(nid):
    rec = record(nid)
    if not any((rec.get("providers") or {}).values()) and not rec.get("custom") and not (rec.get("ollama") or {}).get("on"):
        return "the router has nothing behind it yet: a provider key, a custom endpoint, or Ollama"
    if not (node_addr(nid) if node_addr else ""):
        return "this node has no address the controller knows, so sessions could not reach the router"
    return ""


def deploy(nid, containers, devactions, devapp, gpu=False):
    """The router made on the node from its compose file, then built."""
    why = _ready(nid)
    if why:
        return {"error": why}
    name = container_name(nid)
    if devapp.is_file_source(name):
        was = devapp._read_rec(name, devapp.MAIN).get("node")
        live = {n["id"] for n in node_list() if n.get("state") != "retired"}
        if was == nid or was in live:
            return {"error": f"{name} is already on the Containers page"}
        devapp.forget_container(name)
    rec = record(nid)
    r = containers.create_container(name, compose_text(nid, rec, gpu), "", node=nid, for_project=devapp.SYSTEM)
    if r.get("error"):
        return r
    with _lock:
        d = _load()
        d.setdefault(str(nid), {})["deployed"] = int(time.time())
        _save(d)
    b = devactions.rebuild(name, devapp.MAIN, gate=False)
    if b.get("error"):
        return {"ok": True, "name": name, "note": f"made, but not built: {b['error']}"}
    return {"ok": True, "name": name, "job": b.get("job")}


def apply(nid, containers, devactions, devapp, gpu=False):
    """A deployed router given its new compose file and rebuilt."""
    name = container_name(nid)
    if not devapp.is_file_source(name):
        return {"ok": True, "deployed": False}
    r = containers.update_container(name, compose_text(nid, record(nid), gpu), "")
    if r.get("error"):
        return r
    b = devactions.rebuild(name, devapp.MAIN, gate=False)
    if b.get("error"):
        return {"ok": True, "deployed": True, "note": f"saved, but not rebuilt: {b['error']}"}
    return {"ok": True, "deployed": True, "job": b.get("job")}


def remove(nid, devactions, devapp):
    name = container_name(nid)
    if not devapp.is_file_source(name):
        return {"error": f"{name} is not on the Containers page"}
    r = devactions.remove_instance(name, devapp.MAIN)
    with _lock:
        d = _load()
        rec = d.get(str(nid)) or {}
        rec.pop("deployed", None)
        rec.pop("projects", None)
        rec.pop("models", None)
        d[str(nid)] = rec
        _save(d)
    return r


# ---- Ollama's models ---------------------------------------------------------------

def ollama_pull(nid, model, by=""):
    """One model pulled into the node's Ollama: an exec job on the node
    through the router's compose project."""
    model = str(model or "").strip()
    if not MODEL_RE.match(model):
        return {"error": "a model is named as Ollama lists it, such as llama3.2 or qwen2.5-coder:7b"}
    rec = record(nid)
    if not rec.get("deployed") or not (rec.get("ollama") or {}).get("on"):
        return {"error": "Ollama is not on for this node's router: turn it on and Save first"}
    r = job_add(f"router:{by or 'page'}", {"node": nid}, "exec",
                {"argv": ["docker", "exec", f"{container_name(nid)}-ollama-1", "ollama", "pull", model], "timeout": 3600,
                 "title": f"ollama pull {model}"[:120]})
    if r.get("job"):
        with _lock:
            d = _load()
            o = d.setdefault(str(nid), {}).setdefault("ollama", {})
            o["job"] = r["job"]
            ms = [m for m in (o.get("models") or []) if m != model]
            o["models"] = ms + [model]
            _save(d)
    return r


def ollama_remove(nid, model, by=""):
    model = str(model or "").strip()
    if not MODEL_RE.match(model):
        return {"error": "not a model name"}
    r = job_add(f"router:{by or 'page'}", {"node": nid}, "exec",
                {"argv": ["docker", "exec", f"{container_name(nid)}-ollama-1", "ollama", "rm", model], "timeout": 600,
                 "title": f"ollama rm {model}"[:120]})
    if r.get("job"):
        with _lock:
            d = _load()
            o = d.setdefault(str(nid), {}).setdefault("ollama", {})
            o["models"] = [m for m in (o.get("models") or []) if m != model]
            _save(d)
    return r


# ---- the projects allowed, each with a key of its own --------------------------------

def _api(nid, path, body=None, method=None):
    rec = record(nid)
    url = _url(nid, rec)
    if not url:
        raise RuntimeError("no address")
    req = urllib.request.Request(url + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method or ("POST" if body is not None else "GET"),
                                 headers={"Authorization": "Bearer " + _open(rec.get("master")), "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read() or b"{}")


def _why(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"the router answered {e.code}"
    if isinstance(e, urllib.error.URLError):
        return f"the router did not answer: {e.reason}"
    return f"{type(e).__name__}: {e}"[:160]


def allow(nid, project, by=""):
    """A project allowed to use this node's router: a virtual key of its
    own made at the router, kept sealed; its sessions reach the router from
    the next hello."""
    project = str(project or "")
    if project_names and project not in set(project_names()):
        return {"error": "no such project"}
    rec = record(nid)
    if not rec.get("deployed"):
        return {"error": "the router is not deployed on this node yet"}
    if project in (rec.get("projects") or {}):
        return {"ok": True, "same": True}
    try:
        got = _api(nid, "/key/generate", {"key_alias": f"builderbot-{project}", "metadata": {"project": project, "by": by}})
    except Exception as e:                                  # noqa: BLE001 (said to the person)
        return {"error": f"no key for {project}: {_why(e)}"}
    key = str(got.get("key") or "")
    if not key:
        return {"error": "the router made no key"}
    with _lock:
        d = _load()
        d.setdefault(str(nid), {}).setdefault("projects", {})[project] = {"key": _keep(key), "made": int(time.time())}
        _save(d)
    return {"ok": True}


def disallow(nid, project):
    rec = record(nid)
    p = (rec.get("projects") or {}).get(str(project))
    if not p:
        return {"error": "not allowed there"}
    with contextlib.suppress(Exception):
        _api(nid, "/key/delete", {"keys": [_open(p.get("key"))]})
    with _lock:
        d = _load()
        (d.get(str(nid)) or {}).get("projects", {}).pop(str(project), None)
        _save(d)
    return {"ok": True}


def for_project(project):
    """{url, key, node} a session of `project` is handed (bb-tty's launcher,
    the open agent's config), from the first router that allows it; {}."""
    for nid, rec in _load().items():
        p = (rec.get("projects") or {}).get(str(project))
        if p and rec.get("deployed"):
            url = _url(nid, rec)
            if url:
                return {"url": url + "/v1", "key": _open(p.get("key")), "node": nid}
    return {}


def peers_for(project):
    """(address, port) of every router the project may use, for its sessions'
    network (the hello's peers)."""
    out = []
    for nid, rec in _load().items():
        if str(project) in (rec.get("projects") or {}) and rec.get("deployed"):
            addr = node_addr(nid) if node_addr else ""
            if addr:
                out.append((addr, int(rec.get("port") or PORT)))
    return out


def with_peers(own):
    """The session network's per-project map with each router a project
    may use added to its peers."""
    for nid, rec in _load().items():
        if not rec.get("deployed"):
            continue
        addr = node_addr(nid) if node_addr else ""
        if not addr:
            continue
        for project in (rec.get("projects") or {}):
            o = own.setdefault(project, {"compose": set(), "names": set(), "peers": set(), "hosts": set()})
            peers = o.setdefault("peers", set())
            pair = (addr, int(rec.get("port") or PORT))
            if isinstance(peers, set):
                peers.add(pair)
            elif pair not in peers and list(pair) not in peers:
                peers.append(pair)
    return own


# ---- the models and the spend, read at the router --------------------------------------

def refresh_models(nid):
    """The models the router offers, with their context and price where it
    knows them (/model/info, /v1/models), kept with the record."""
    rec = record(nid)
    if not rec.get("deployed"):
        return {"error": "not deployed"}
    rows = {}
    try:
        info = _api(nid, "/model/info")
        for m in info.get("data") or []:
            mi = m.get("model_info") or {}
            name = str(m.get("model_name") or "")
            if not name:
                continue
            rows[name] = {"id": name, "provider": name.split("/")[0] if "/" in name else str((m.get("litellm_params") or {}).get("model") or "").split("/")[0],
                          "context": mi.get("max_input_tokens") or mi.get("max_tokens") or 0,
                          "in_cost": mi.get("input_cost_per_token") or 0, "out_cost": mi.get("output_cost_per_token") or 0,
                          "wild": name.endswith("/*")}
    except Exception as e:                                  # noqa: BLE001 (said)
        return {"error": _why(e)}
    with contextlib.suppress(Exception):
        v1 = _api(nid, "/v1/models")
        for m in v1.get("data") or []:
            name = str(m.get("id") or "")
            if name and name not in rows:
                rows[name] = {"id": name, "provider": name.split("/")[0] if "/" in name else "", "context": 0, "in_cost": 0, "out_cost": 0, "wild": False}
    # The Ollama models pulled here, each a model the router routes to.
    for m in (rec.get("ollama") or {}).get("models") or []:
        rows.setdefault(f"ollama/{m}", {"id": f"ollama/{m}", "provider": "ollama", "context": 0, "in_cost": 0, "out_cost": 0, "wild": False})
    models = sorted(rows.values(), key=lambda r: (r["wild"], r["provider"], r["id"]))
    with _lock:
        d = _load()
        d.setdefault(str(nid), {}).update(models=models, models_at=int(time.time()))
        _save(d)
    return {"ok": True, "models": models}


# The models walked with the open agent and BuilderBot's tools (R144 step
# 3): a session on one ran the briefing, bb, the hooks and a transcript
# end to end. One goes here when that walk is done; the picker marks the
# rest untested rather than hiding them, since the router routes to any.
WALKED_MODELS = ()


def refresh_spend(nid):
    """What each allowed project has spent through its key (/key/info), and
    for a local model its tokens per second, read off the router's log of
    the key's last requests (/spend/logs: completion tokens over the call's
    time), kept per project and model."""
    rec = record(nid)
    out, rate = {}, {}
    for project, p in (rec.get("projects") or {}).items():
        key = _open(p.get("key"))
        with contextlib.suppress(Exception):
            got = _api(nid, "/key/info?key=" + urllib.parse.quote(key))
            out[project] = float((got.get("info") or got).get("spend") or 0)
        with contextlib.suppress(Exception):
            rate[project] = tokens_per_second(_api(nid, "/spend/logs?api_key=" + urllib.parse.quote(key)))
    with _lock:
        d = _load()
        d.setdefault(str(nid), {}).update(spend=out, rate=rate)
        _save(d)
    return out


def tokens_per_second(logs):
    """{model: tokens per second} for the local models (ollama/...) among a
    key's last requests: the completion tokens of each over its wall time,
    averaged over the last twenty of each model. A hosted model is left
    out: its speed is the provider's, not this machine's."""
    rows = logs if isinstance(logs, list) else (logs or {}).get("data") or []
    per = {}
    for r in rows[-200:]:
        if not isinstance(r, dict) or not str(r.get("model") or "").startswith("ollama/"):
            continue
        try:
            toks = int(r.get("completion_tokens") or 0)
            t0, t1 = (_ts(r.get("startTime")), _ts(r.get("endTime")))
        except (TypeError, ValueError):
            continue
        if toks > 0 and t1 > t0:
            per.setdefault(str(r["model"]), []).append(toks / (t1 - t0))
    return {m: round(sum(v[-20:]) / len(v[-20:]), 1) for m, v in per.items()}


def _ts(x):
    """A log's time as seconds: ISO text, or a number."""
    if isinstance(x, (int, float)):
        return float(x)
    import datetime
    return datetime.datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()


def rate_for(project):
    """{model: tokens per second} for the project's local models, from the
    first router that allows it."""
    for rec in _load().values():
        if str(project) in (rec.get("projects") or {}) and rec.get("deployed"):
            return (rec.get("rate") or {}).get(str(project)) or {}
    return {}


def models_for(project):
    """The models a project's Any model session may pick, from the first
    router that allows it: [{id, provider, context, in_cost, out_cost}]."""
    for rec in _load().values():
        if str(project) in (rec.get("projects") or {}) and rec.get("deployed"):
            return [dict(m, walked=m["id"] in WALKED_MODELS) for m in (rec.get("models") or []) if not m.get("wild")]
    return []


def spend_for(project):
    """What the project has spent through the routers, in dollars, or None."""
    total, any_ = 0.0, False
    for rec in _load().values():
        if str(project) in (rec.get("projects") or {}) and str(project) in (rec.get("spend") or {}):
            total += float(rec["spend"][str(project)])
            any_ = True
    return total if any_ else None


def seal_all(again=False):
    if not again or not (seal and sealing and sealing()):
        return 0
    n = 0
    with _lock:
        d = _load()
        for rec in d.values():
            for k in ("master", "dbpass"):
                if rec.get(k):
                    rec[k] = _keep(_open(rec[k]))
                    n += 1
            for pid in list(rec.get("providers") or {}):
                rec["providers"][pid] = _keep(_open(rec["providers"][pid]))
                n += 1
            for c in rec.get("custom") or []:
                if c.get("key"):
                    c["key"] = _keep(_open(c["key"]))
                    n += 1
            for p in (rec.get("projects") or {}).values():
                p["key"] = _keep(_open(p.get("key")))
                n += 1
        if n:
            _save(d)
    return n


def at_rest():
    """For the Keys page: each key kept, by node, sealed or not."""
    out = []
    for nid, rec in _load().items():
        for pid in (rec.get("providers") or {}):
            out.append({"node": nid, "name": f"{PROVIDERS[pid]['label']} key" if pid in PROVIDERS else pid,
                        "sealed": str(rec["providers"][pid]).startswith(SEALED)})
        for c in rec.get("custom") or []:
            if c.get("key"):
                out.append({"node": nid, "name": f"{c['name']}'s key", "sealed": str(c["key"]).startswith(SEALED)})
        if rec.get("master"):
            out.append({"node": nid, "name": "the router's master key", "sealed": str(rec["master"]).startswith(SEALED)})
    return out

