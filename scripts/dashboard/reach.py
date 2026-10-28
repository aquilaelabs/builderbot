"""The bell's rows sent elsewhere, per person and per kind (R149, the
operator, 26 Oct: every NAS system has it).

Each person keeps destinations on their Profile (Where the bell reaches
you): email over SMTP (the server set in Controller settings' Mail
section), a webhook, and ntfy, Gotify, Pushover, Telegram, Discord and
Slack as presets of it. Each destination says which kinds of row it takes
(an ask waiting on you, what a node needs, a red CI run, an invitation, a
file changed in two places) and a quiet window during which nothing is
sent. The minute loop composes each person's bell on the server (the
server's bell_rows), sends each destination the rows it has not sent yet,
one message per tick, holds a repeat while a row's key is unchanged, and
forgets a key once its row has left, so the same thing said again later is
sent again. What a destination holds that is a secret (a token, a webhook
address, the SMTP password) is sealed under the install key.

  STATE/reach.json   {uid: {"dest": [{id, kind, name, on, kinds, quiet,
                      fields}], "sent": {dest id: {row key: at}}}}
"""
import base64
import email.message
import json
import secrets
import smtplib
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
smtp_settings = None         # () -> {host, port, security, user, password, from}
_lock = threading.Lock()
SEALED = "bbseal:"
TIMEOUT = 20
MAX_DEST = 12
MAX_ROWS = 12                # rows in one message
KINDS = ("asks", "needs", "ci", "invites", "sync", "disk", "power", "host", "backup")
KIND_WORDS = {"asks": "a session asking for your answer", "needs": "what a node or a project needs",
              "ci": "a red CI run", "invites": "an invitation to a project", "sync": "a file changed in two places",
              "disk": "a disk failing or hot, a pool or an array slot gone, on this machine",
              "power": "this machine on its UPS battery, or the UPS not answering", "host": "security updates to this machine's own packages, or a restart they need",
              "backup": "a backup of this machine that failed or has not run in two days"}
# Each channel: the fields it takes (name, label, secret?) in the order the
# page draws them.
CHANNELS = {
    "email": {"label": "Email", "fields": [("to", "Address", False)]},
    "webhook": {"label": "Webhook", "fields": [("url", "URL", True), ("header", "Header (optional, Name: value)", True)]},
    "ntfy": {"label": "ntfy", "fields": [("server", "Server", False), ("topic", "Topic", False), ("token", "Access token (optional)", True)]},
    "gotify": {"label": "Gotify", "fields": [("server", "Server", False), ("token", "App token", True)]},
    "pushover": {"label": "Pushover", "fields": [("user", "User key", True), ("token", "App token", True)]},
    "telegram": {"label": "Telegram", "fields": [("token", "Bot token", True), ("chat", "Chat id", False)]},
    "discord": {"label": "Discord", "fields": [("url", "Webhook URL", True)]},
    "slack": {"label": "Slack", "fields": [("url", "Webhook URL", True)]},
}


def configure(**deps):
    globals().update({k: v for k, v in deps.items() if k in globals()})
    if "state" in deps:
        globals()["STATE"] = Path(deps["state"])


# ---- the store ------------------------------------------------------------------

def _file():
    return STATE / "reach.json"


def _load():
    try:
        d = json.loads(_file().read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def _save(d):
    write_json(_file(), d, mode=0o600)


def _keep(v):
    """A secret field sealed under the install key where there is one."""
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


def _secret_names(kind):
    return {n for n, _, s in CHANNELS.get(kind, {}).get("fields", []) if s}


def _dests(uid):
    return [d for d in (_load().get(uid) or {}).get("dest", []) if isinstance(d, dict)]


def list_for(uid):
    """The person's destinations for Profile: a secret field says only
    whether it is set."""
    out = []
    for d in _dests(uid):
        secret = _secret_names(d.get("kind", ""))
        out.append({"id": d["id"], "kind": d.get("kind", ""), "name": d.get("name", ""), "on": d.get("on", True),
                    "kinds": [k for k in d.get("kinds", []) if k in KINDS], "quiet": d.get("quiet") or None,
                    "fields": {k: ("set" if v else "") if k in secret else v for k, v in (d.get("fields") or {}).items()},
                    "last": d.get("last") or {}})
    return out


def _quiet_ok(q):
    if not q:
        return True
    try:
        for k in ("from", "to"):
            h, m = str(q[k]).split(":")
            if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
                return False
    except (KeyError, ValueError, TypeError, AttributeError):
        return False
    return True


def set_dest(uid, req):
    """A destination added or changed: {dest} or {error}. A secret field
    left empty on a change keeps what it had."""
    kind = str(req.get("kind") or "")
    if kind not in CHANNELS:
        return {"error": f"a destination is one of {', '.join(CHANNELS)}"}
    fields = req.get("fields") if isinstance(req.get("fields"), dict) else {}
    kinds = [k for k in (req.get("kinds") or []) if k in KINDS] if isinstance(req.get("kinds"), list) else list(KINDS)
    quiet = req.get("quiet") if isinstance(req.get("quiet"), dict) else None
    if quiet and not _quiet_ok(quiet):
        return {"error": "a quiet window is two times of day, as 22:00 to 07:00"}
    with _lock:
        d = _load()
        mine = d.setdefault(uid, {"dest": [], "sent": {}})
        did = str(req.get("id") or "")
        was = next((x for x in mine["dest"] if x.get("id") == did), None) if did else None
        if did and was is None:
            return {"error": "no such destination"}
        if was is None and len(mine["dest"]) >= MAX_DEST:
            return {"error": f"{MAX_DEST} destinations are the most kept"}
        rec = dict(was or {"id": secrets.token_hex(4), "kind": kind, "made": int(time.time())})
        rec["kind"] = kind
        rec["name"] = str(req.get("name") or rec.get("name") or CHANNELS[kind]["label"])[:60]
        rec["on"] = req.get("on") is not False
        rec["kinds"] = kinds
        rec["quiet"] = {"from": str(quiet["from"]), "to": str(quiet["to"])} if quiet else None
        secret = _secret_names(kind)
        kept = dict(rec.get("fields") or {})
        for name, _label, _s in CHANNELS[kind]["fields"]:
            v = str(fields.get(name) or "").strip()
            if name in secret:
                if v:
                    kept[name] = _keep(v)
            else:
                kept[name] = v[:300]
        rec["fields"] = kept
        missing = [label for name, label, s in CHANNELS[kind]["fields"] if not kept.get(name) and "optional" not in label.lower()]
        if missing:
            return {"error": f"{CHANNELS[kind]['label']} needs {', '.join(missing)}"}
        if was is None:
            mine["dest"].append(rec)
        else:
            mine["dest"] = [rec if x.get("id") == did else x for x in mine["dest"]]
        _save(d)
    return {"ok": True, "dest": next(x for x in list_for(uid) if x["id"] == rec["id"])}


def set_on(uid, did, on):
    """A destination switched on or off, its settings kept (R173): {dest}
    or {error}."""
    with _lock:
        d = _load()
        mine = d.get(uid) or {}
        rec = next((x for x in (mine.get("dest") or []) if x.get("id") == did), None)
        if rec is None:
            return {"error": "no such destination"}
        rec["on"] = on is True
        d[uid] = mine
        _save(d)
    return {"ok": True, "dest": next(x for x in list_for(uid) if x["id"] == did)}


def remove(uid, did):
    with _lock:
        d = _load()
        mine = d.get(uid) or {}
        before = len(mine.get("dest") or [])
        mine["dest"] = [x for x in (mine.get("dest") or []) if x.get("id") != did]
        (mine.get("sent") or {}).pop(did, None)
        if len(mine["dest"]) == before:
            return {"error": "no such destination"}
        d[uid] = mine
        _save(d)
    return {"ok": True}


def forget(uid):
    with _lock:
        d = _load()
        if d.pop(uid, None) is not None:
            _save(d)


# ---- sending --------------------------------------------------------------------

def _post(url, data, headers=None):
    req = urllib.request.Request(url, data=data, method="POST", headers={"User-Agent": "BuilderBot", **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status


def _post_json(url, body, headers=None):
    return _post(url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})


def _send(dest, title, lines, url=""):
    """One message to one destination; raises on failure with its reason."""
    kind = dest.get("kind")
    f = {k: _open(v) for k, v in (dest.get("fields") or {}).items()}
    text = "\n".join(lines)
    if kind == "email":
        s = smtp_settings() if smtp_settings else {}
        if not s.get("host"):
            raise RuntimeError("no mail server is set: Controller settings, Mail")
        msg = email.message.EmailMessage()
        msg["Subject"] = title
        msg["From"] = s.get("from") or s.get("user") or "builderbot@localhost"
        msg["To"] = f.get("to", "")
        msg.set_content(text + (f"\n\n{url}\n" if url else ""))
        port = int(s.get("port") or (465 if s.get("security") == "tls" else 587))
        if s.get("security") == "tls":
            srv = smtplib.SMTP_SSL(s["host"], port, timeout=TIMEOUT)
        else:
            srv = smtplib.SMTP(s["host"], port, timeout=TIMEOUT)
        with srv:
            if s.get("security") == "starttls":
                srv.starttls()
            if s.get("user"):
                srv.login(s["user"], s.get("password") or "")
            srv.send_message(msg)
        return
    if kind == "webhook":
        headers = {}
        if f.get("header") and ":" in f["header"]:
            k, v = f["header"].split(":", 1)
            headers[k.strip()] = v.strip()
        _post_json(f["url"], {"title": title, "text": text, "lines": lines, "url": url}, headers)
    elif kind == "ntfy":
        headers = {"Title": title, "Content-Type": "text/plain; charset=utf-8"}
        if f.get("token"):
            headers["Authorization"] = "Bearer " + f["token"]
        if url:
            headers["Click"] = url
        _post(f["server"].rstrip("/") + "/" + f["topic"].strip("/"), text.encode(), headers)
    elif kind == "gotify":
        _post_json(f["server"].rstrip("/") + "/message", {"title": title, "message": text, "priority": 5},
                   {"X-Gotify-Key": f["token"]})
    elif kind == "pushover":
        _post("https://api.pushover.net/1/messages.json",
              urllib.parse.urlencode({"token": f["token"], "user": f["user"], "title": title, "message": text, **({"url": url} if url else {})}).encode(),
              {"Content-Type": "application/x-www-form-urlencoded"})
    elif kind == "telegram":
        _post_json(f"https://api.telegram.org/bot{f['token']}/sendMessage",
                   {"chat_id": f["chat"], "text": f"{title}\n{text}" + (f"\n{url}" if url else "")})
    elif kind == "discord":
        _post_json(f["url"], {"content": f"**{title}**\n{text}" + (f"\n{url}" if url else "")})
    elif kind == "slack":
        _post_json(f["url"], {"text": f"*{title}*\n{text}" + (f"\n{url}" if url else "")})
    else:
        raise RuntimeError("not a destination here")


def _said(uid, did, ok, why=""):
    with _lock:
        d = _load()
        for x in (d.get(uid) or {}).get("dest", []):
            if x.get("id") == did:
                x["last"] = {"at": int(time.time()), "ok": bool(ok), "why": str(why)[:200]}
        _save(d)


def test(uid, did, who=""):
    """A test message to one destination: {ok} or {error}."""
    dest = next((x for x in _dests(uid) if x.get("id") == did), None)
    if not dest:
        return {"error": "no such destination"}
    try:
        _send(dest, "BuilderBot can reach you here", [f"A test from BuilderBot{(' for ' + who) if who else ''}: the bell's rows you picked arrive this way."])
    except Exception as e:                                  # noqa: BLE001 (said to the person, not raised)
        why = _why(e)
        _said(uid, did, False, why)
        return {"error": f"not sent: {why}"}
    _said(uid, did, True)
    return {"ok": True}


def _why(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return str(e.reason)[:120]
    return f"{type(e).__name__}: {e}"[:160]


# ---- the loop: what is new, held while unchanged, after the quiet window ----------

def _in_quiet(q, now=None):
    """Whether local time is inside the window (from may be past to: a
    window over midnight)."""
    if not q:
        return False
    t = time.localtime(now)
    cur = t.tm_hour * 60 + t.tm_min
    try:
        fh, fm = (int(x) for x in str(q["from"]).split(":"))
        th, tm = (int(x) for x in str(q["to"]).split(":"))
    except (KeyError, ValueError, TypeError):
        return False
    a, b = fh * 60 + fm, th * 60 + tm
    return (a <= cur < b) if a <= b else (cur >= a or cur < b)


def tick(rows_for, people, base_url="", now=None):
    """One pass: for each person with a destination, their bell's rows
    (rows_for(uid) -> [{key, kind, title, text, url}]), and to each
    destination that is on the rows of its kinds not sent to it yet,
    outside its quiet window, one message; the keys sent are kept until
    their rows leave. Returns how many messages went."""
    d = _load()
    sent_n = 0
    for uid in list(d):
        mine = d.get(uid) or {}
        dests = [x for x in mine.get("dest", []) if isinstance(x, dict) and x.get("on", True)]
        if not dests or uid not in people:
            continue
        try:
            rows = [r for r in rows_for(uid) if r.get("key")]
        except Exception:                                   # noqa: BLE001 (one person's rows failing is not the loop's end)
            continue
        keys_now = {r["key"] for r in rows}
        with _lock:
            d = _load()
            sent = (d.get(uid) or {}).setdefault("sent", {})
            for did in list(sent):
                sent[did] = {k: v for k, v in sent[did].items() if k in keys_now}
            _save(d)
        for dest in dests:
            due = [r for r in rows if r.get("kind") in (dest.get("kinds") or KINDS) and r["key"] not in (sent.get(dest["id"]) or {})]
            if not due or _in_quiet(dest.get("quiet"), now):
                continue
            due = due[:MAX_ROWS]
            title = due[0]["title"] if len(due) == 1 else f"BuilderBot: {len(due)} things for you"
            lines = [f"{r['title']}: {r['text']}" if r.get("text") else r["title"] for r in due]
            url = (due[0].get("url") or base_url) if len(due) == 1 else base_url
            try:
                _send(dest, title, lines, url)
            except Exception as e:                          # noqa: BLE001 (said on the destination's row; tried again next tick)
                _said(uid, dest["id"], False, _why(e))
                continue
            sent_n += 1
            with _lock:
                d = _load()
                s = (d.get(uid) or {}).setdefault("sent", {}).setdefault(dest["id"], {})
                s.update({r["key"]: int(time.time()) for r in due})
                for x in (d.get(uid) or {}).get("dest", []):
                    if x.get("id") == dest["id"]:
                        x["last"] = {"at": int(time.time()), "ok": True, "why": "", "rows": len(due)}
                _save(d)
    return sent_n


def seal_all(again=False):
    """After the install key changed: every secret field sealed again."""
    if not again or not (seal and sealing and sealing()):
        return 0
    n = 0
    with _lock:
        d = _load()
        for mine in d.values():
            for x in (mine.get("dest") or []):
                secret = _secret_names(x.get("kind", ""))
                for k in list(x.get("fields") or {}):
                    if k in secret and x["fields"][k]:
                        v = _open(x["fields"][k])
                        if v:
                            x["fields"][k] = _keep(v)
                            n += 1
        if n:
            _save(d)
    return n


def at_rest():
    """For the Keys page: how many secret fields are kept, and whether each
    is sealed."""
    out = []
    for uid, mine in _load().items():
        for x in (mine.get("dest") or []):
            for k in _secret_names(x.get("kind", "")):
                v = (x.get("fields") or {}).get(k)
                if v:
                    out.append({"uid": uid, "name": x.get("name", ""), "sealed": str(v).startswith(SEALED)})
    return out

