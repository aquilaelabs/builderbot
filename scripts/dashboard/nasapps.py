"""Apps a NAS runs (R164 step 2): a catalog of ready containers (a media
server, the arr stack, photos, files, home automation, a download client,
syncing) each a compose file and an environment with a few blanks (where
its data and media live, who it runs as, the time zone, its port), filled
from the New container dialog and made through the Containers page as any
container is: on the node picked, reached on its port, and put behind a
node's nginx with a certificate from that node's nginx page. Images are
pinned to a tag, never latest, and the registry update check says when
one moves. The catalog is this list, and beside it the apps a person
added (R170 step 3, the Library's Add your own): a compose file of their
own with the same blanks, checked before it is kept, held at tier
sideloaded in sideapps.json under the state; the vetted public catalog is
R169's.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

_lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
if os.path.isdir(_lib) and _lib not in sys.path:
    sys.path.insert(0, _lib)
import markup  # noqa: E402

FILE = None
write_json = None
ID_RE = re.compile(r"[a-z][a-z0-9-]{1,31}")
BLANKS = ("DATA", "MEDIA", "PUID", "PGID", "TZ", "PORT")
COMPOSE_MAX = 64 * 1024

TZ_RE = re.compile(r"[A-Za-z0-9_+-]{1,32}(/[A-Za-z0-9_+-]{1,32}){0,2}")
PATH_RE = re.compile(r"/(mnt|srv)/[\w./ +-]{1,180}")
IDS_RE = re.compile(r"[0-9]{1,6}:[0-9]{1,6}")

# Each app: what it is, the blanks it takes (data: its own folder; media:
# a share's folder; port: the one it answers on), and its compose with the
# blanks as ${VARS} the environment fills, so the file reads as compose
# everywhere and the dialog's Environment tab shows what was chosen.
APPS = {
    "jellyfin": {"name": "Jellyfin", "what": "a media server: films, series and music streamed to every screen", "port": 8096, "media": True,
                 "compose": """services:
  jellyfin:
    image: jellyfin/jellyfin:10.10.7
    restart: unless-stopped
    user: "${PUID}:${PGID}"
    environment:
      TZ: ${TZ}
    ports:
      - "${PORT}:8096"
    volumes:
      - ${DATA}/config:/config
      - ${DATA}/cache:/cache
      - ${MEDIA}:/media:ro
"""},
    "plex": {"name": "Plex", "what": "a media server with Plex's apps and account; claim it on its first open", "port": 32400, "media": True,
             "compose": """services:
  plex:
    image: plexinc/pms-docker:1.41.6.9685-d301f511a
    restart: unless-stopped
    environment:
      TZ: ${TZ}
      PLEX_UID: ${PUID}
      PLEX_GID: ${PGID}
    ports:
      - "${PORT}:32400"
    volumes:
      - ${DATA}/config:/config
      - ${DATA}/transcode:/transcode
      - ${MEDIA}:/data:ro
"""},
    "arr": {"name": "The arr stack", "what": "Sonarr, Radarr and Prowlarr: series, films and the indexers they search", "port": 8989, "media": True,
            "compose": """services:
  sonarr:
    image: lscr.io/linuxserver/sonarr:4.0.14
    restart: unless-stopped
    environment:
      PUID: ${PUID}
      PGID: ${PGID}
      TZ: ${TZ}
    ports:
      - "${PORT}:8989"
    volumes:
      - ${DATA}/sonarr:/config
      - ${MEDIA}:/media
  radarr:
    image: lscr.io/linuxserver/radarr:5.21.1
    restart: unless-stopped
    environment:
      PUID: ${PUID}
      PGID: ${PGID}
      TZ: ${TZ}
    ports:
      - "7878:7878"
    volumes:
      - ${DATA}/radarr:/config
      - ${MEDIA}:/media
  prowlarr:
    image: lscr.io/linuxserver/prowlarr:1.33.3
    restart: unless-stopped
    environment:
      PUID: ${PUID}
      PGID: ${PGID}
      TZ: ${TZ}
    ports:
      - "9696:9696"
    volumes:
      - ${DATA}/prowlarr:/config
"""},
    "qbittorrent": {"name": "qBittorrent", "what": "a download client with a web page; its first password is in its log", "port": 8080, "media": True,
                    "compose": """services:
  qbittorrent:
    image: lscr.io/linuxserver/qbittorrent:5.0.4
    restart: unless-stopped
    environment:
      PUID: ${PUID}
      PGID: ${PGID}
      TZ: ${TZ}
      WEBUI_PORT: ${PORT}
    ports:
      - "${PORT}:${PORT}"
      - "6881:6881"
      - "6881:6881/udp"
    volumes:
      - ${DATA}/config:/config
      - ${MEDIA}:/downloads
"""},
    "immich": {"name": "Immich", "what": "photos and videos from every phone, with faces, places and search; its own database beside it", "port": 2283, "media": True,
               "compose": """services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:v1.131.3
    restart: unless-stopped
    environment:
      TZ: ${TZ}
      DB_HOSTNAME: database
      DB_USERNAME: postgres
      DB_PASSWORD: ${DB_PASSWORD}
      DB_DATABASE_NAME: immich
      REDIS_HOSTNAME: redis
    ports:
      - "${PORT}:2283"
    volumes:
      - ${MEDIA}:/usr/src/app/upload
      - /etc/localtime:/etc/localtime:ro
    depends_on:
      - redis
      - database
  immich-machine-learning:
    image: ghcr.io/immich-app/immich-machine-learning:v1.131.3
    restart: unless-stopped
    volumes:
      - ${DATA}/model-cache:/cache
  redis:
    image: docker.io/valkey/valkey:8-bookworm
    restart: unless-stopped
  database:
    image: ghcr.io/immich-app/postgres:14-vectorchord0.3.0-pgvectors0.2.0
    restart: unless-stopped
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_USER: postgres
      POSTGRES_DB: immich
      POSTGRES_INITDB_ARGS: '--data-checksums'
    volumes:
      - ${DATA}/postgres:/var/lib/postgresql/data
""", "secrets": ["DB_PASSWORD"]},
    "nextcloud": {"name": "Nextcloud", "what": "files, calendars and contacts with its apps, on a database of its own", "port": 8081, "media": True,
                  "compose": """services:
  nextcloud:
    image: nextcloud:31.0.5-apache
    restart: unless-stopped
    environment:
      MYSQL_HOST: db
      MYSQL_DATABASE: nextcloud
      MYSQL_USER: nextcloud
      MYSQL_PASSWORD: ${DB_PASSWORD}
      NEXTCLOUD_ADMIN_USER: admin
      NEXTCLOUD_ADMIN_PASSWORD: ${ADMIN_PASSWORD}
      TZ: ${TZ}
    ports:
      - "${PORT}:80"
    volumes:
      - ${DATA}/html:/var/www/html
      - ${MEDIA}:/var/www/html/data
    depends_on:
      - db
  db:
    image: mariadb:11.4
    restart: unless-stopped
    command: --transaction-isolation=READ-COMMITTED --log-bin=binlog --binlog-format=ROW
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_PASSWORD}
      MYSQL_DATABASE: nextcloud
      MYSQL_USER: nextcloud
      MYSQL_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ${DATA}/db:/var/lib/mysql
""", "secrets": ["DB_PASSWORD", "ADMIN_PASSWORD"]},
    "homeassistant": {"name": "Home Assistant", "what": "home automation; on the machine's own network so it finds the devices around it", "port": 8123, "media": False,
                      "compose": """services:
  homeassistant:
    image: ghcr.io/home-assistant/home-assistant:2025.5.3
    restart: unless-stopped
    network_mode: host
    privileged: true
    environment:
      TZ: ${TZ}
    volumes:
      - ${DATA}/config:/config
      - /run/dbus:/run/dbus:ro
"""},
    "syncthing": {"name": "Syncthing", "what": "folders kept the same between this machine and others, with no cloud between", "port": 8384, "media": True,
                  "compose": """services:
  syncthing:
    image: syncthing/syncthing:1.29.6
    restart: unless-stopped
    environment:
      PUID: ${PUID}
      PGID: ${PGID}
      TZ: ${TZ}
    ports:
      - "${PORT}:8384"
      - "22000:22000/tcp"
      - "22000:22000/udp"
      - "21027:21027/udp"
    volumes:
      - ${DATA}/config:/var/syncthing/config
      - ${MEDIA}:/var/syncthing/Sync
"""},
}


def configure(*, state, write_json):
    globals().update(FILE=Path(state) / "sideapps.json", write_json=write_json)


def _load():
    """{id: record} of the apps a person added; {} with no file."""
    try:
        d = json.loads(FILE.read_text()) if FILE else {}
    except (OSError, ValueError):
        return {}
    apps = d.get("apps") if isinstance(d, dict) else None
    return {k: v for k, v in (apps or {}).items() if isinstance(v, dict) and v.get("compose")}


def _save(apps):
    write_json(FILE, {"apps": apps})


def _all():
    """Every app, the shipped ones first with their tier, then the added: a
    person's own as sideloaded, one taken from the catalog at its tier."""
    out = {k: {**v, "tier": "official"} for k, v in APPS.items()}
    for k, v in _load().items():
        out[k] = {**v, "tier": v["tier"] if v.get("pin") and v.get("tier") in ("official", "vetted") else "sideloaded"}
    return out


def catalog():
    """The list the dialog and the Library show: [{id, name, what, port,
    media, secrets, tier, by, at}]."""
    return [{"id": k, "name": v["name"], "what": v["what"], "port": v["port"], "media": v.get("media", False), "secrets": v.get("secrets", []),
             "tier": v.get("tier", "official"), "by": v.get("by", ""), "at": v.get("at", 0)}
            for k, v in _all().items()]


def source(app):
    """One added app as kept, for Edit: {id, name, what, port, media, compose} or {error}."""
    a = _load().get(str(app or ""))
    if not a:
        return {"error": f"no app called {app or 'nothing'} was added here"}
    return {"id": app, "name": a["name"], "what": a["what"], "port": a["port"], "media": bool(a.get("media")), "compose": a["compose"]}


def check(compose):
    """What a compose file of a person's own would run, before it is kept
    (the Look): {services: [{name, image, ports, volumes}], blanks, media}
    or {error}. Held to what the shipped ones are held to: a services
    mapping, every image pinned to a tag that is not latest, and no blank
    but the ones New container fills."""
    text = str(compose or "")
    if not text.strip():
        return {"error": "paste the app's compose file"}
    if len(text.encode("utf-8")) > COMPOSE_MAX:
        return {"error": f"a compose file is {COMPOSE_MAX // 1024} KB at most"}
    try:
        doc = markup.yaml_load(text)
    except Exception as e:  # noqa: BLE001 (the reader's own word is the reason)
        return {"error": f"not a compose file: {e}"}
    services = doc.get("services") if isinstance(doc, dict) else None
    if not isinstance(services, dict) or not services:
        return {"error": "a compose file has a services mapping with at least one service"}
    out = []
    for name, svc in services.items():
        if not isinstance(svc, dict):
            return {"error": f"service {name} is a mapping"}
        image = str(svc.get("image") or "")
        if not image:
            return {"error": f"service {name} names an image"}
        if not re.fullmatch(r"[\w./-]+:[\w.-]+", image) or image.endswith(":latest"):
            return {"error": f"service {name}: {image} is not pinned to a tag (never latest), so an update could change it under you"}
        if "build" in svc or "privileged" in svc:
            return {"error": f"service {name}: an app from the catalog is a pulled image, never built here, and never privileged"}
        ports = svc.get("ports") if isinstance(svc.get("ports"), list) else []
        vols = svc.get("volumes") if isinstance(svc.get("volumes"), list) else []
        out.append({"name": str(name), "image": image, "ports": [str(p) for p in ports], "volumes": [str(v) for v in vols]})
    blanks = sorted(set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)))
    odd = [b for b in blanks if b not in BLANKS]
    if odd:
        return {"error": f"unknown blank {', '.join(odd)}: the blanks New container fills are {', '.join(BLANKS)}"}
    if "PORT" not in blanks:
        return {"error": "the app answers on ${PORT}: New container fills it with the port you pick"}
    return {"services": out, "blanks": blanks, "media": "MEDIA" in blanks}


def add(app, name, what, port, compose, by="", replace=False):
    """Keep an app of a person's own, looked at first (check): {app} or
    {error}. `replace` takes a new version of one added before; a shipped
    app's id is never taken."""
    app = str(app or "").strip().lower()
    if not ID_RE.fullmatch(app):
        return {"error": "an app's id is 2 to 32 lower-case letters, digits and dashes, starting with a letter"}
    if app in APPS:
        return {"error": f"{app} is a shipped app: pick another id"}
    name, what = str(name or "").strip(), str(what or "").strip()
    if not 1 <= len(name) <= 60:
        return {"error": "its name is 1 to 60 characters"}
    if not 1 <= len(what) <= 200:
        return {"error": "what it is, in a line of 200 characters at most"}
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"error": "a port is a number"}
    if not 1 <= port <= 65535:
        return {"error": "a port is 1 to 65535"}
    seen = check(compose)
    if seen.get("error"):
        return seen
    apps = _load()
    if app in apps and not replace:
        return {"error": f"{app} was added already: open it from its row to change it"}
    apps[app] = {"name": name, "what": what, "port": port, "media": seen["media"], "compose": str(compose), "secrets": [],
                 "by": str(by or ""), "at": int(time.time())}
    _save(apps)
    return {"app": app, "replaced": app in apps and replace, **{k: v for k, v in seen.items()}}


def add_catalog(entry, by="", fetch=None):
    """Keep an app the vetted catalog offers (R170 step 7): its folder at the
    commit the signed index pins, bbapp.json and compose.yml read from it and
    the compose held to what a person's own is held to, kept with the
    entry's tier and pin so New container offers it. `entry` is the index's,
    never the page's. {app} or {error}."""
    if not entry or entry.get("kind") != "app":
        return {"error": "no app by that name in the catalog"}
    got = fetch(entry["url"], entry["commit"], entry["sha256"], entry.get("path", ""), ("bbapp.json", "compose.yml"))
    if got.get("error"):
        return got
    try:
        meta = json.loads(got["files"]["bbapp.json"].decode("utf-8"))
        compose = got["files"]["compose.yml"].decode("utf-8")
    except (ValueError, UnicodeDecodeError, KeyError):
        return {"error": f"{entry['name']}'s bbapp.json is not JSON"}
    app = entry["name"]
    if app in APPS:
        return {"error": f"{app} is a shipped app already"}
    seen = check(compose)
    if seen.get("error"):
        return {"error": f"{app}: {seen['error']}"}
    try:
        port = int(meta.get("port"))
    except (TypeError, ValueError):
        return {"error": f"{app}'s bbapp.json names no port"}
    apps = _load()
    apps[app] = {"name": str(meta.get("label") or app)[:60], "what": str(meta.get("about") or entry.get("about") or "")[:200], "port": port,
                 "media": seen["media"], "compose": compose, "secrets": [], "by": str(by or ""), "at": int(time.time()),
                 "tier": "official" if entry.get("tier") == "official" else "vetted",
                 "pin": {k: entry[k] for k in ("url", "commit", "sha256")} | {"path": entry.get("path", "")}}
    _save(apps)
    return {"app": app, **seen}


def remove(app):
    """Drop an added app: {ok} or {error}. A container made from it stays
    what it is, its own compose file kept with it."""
    apps = _load()
    if app not in apps:
        return {"error": f"no app called {app or 'nothing'} was added here"}
    del apps[app]
    _save(apps)
    return {"ok": True}


def render(app, data, media="", ids="1000:1000", tz="UTC", port=None, secrets=None):
    """The compose and the environment for one app with its blanks filled:
    {name, compose, env} or {error}. The environment is where the choices
    live, so the file stays the catalog's and the Environment tab says what
    was picked; a secret the dialog did not give is made here."""
    import secrets as _secrets
    a = _all().get(str(app or ""))
    if not a:
        return {"error": f"no app called {app or 'nothing'} in the catalog"}
    data = str(data or "").rstrip("/")
    media = str(media or "").rstrip("/")
    if not PATH_RE.fullmatch(data) or ".." in data.split("/"):
        return {"error": "the app's data goes in a folder under /mnt (a pool, the array) or /srv"}
    if a.get("media") and (not PATH_RE.fullmatch(media) or ".." in media.split("/")):
        return {"error": "the app takes a media or files folder under /mnt (a share's folder) or /srv"}
    if not IDS_RE.fullmatch(str(ids or "")):
        return {"error": "the user it runs as is uid:gid, two numbers"}
    if not TZ_RE.fullmatch(str(tz or "")):
        return {"error": "a time zone is named as Region/City"}
    try:
        port = int(port if port is not None else a["port"])
    except (TypeError, ValueError):
        return {"error": "a port is a number"}
    if not 1 <= port <= 65535:
        return {"error": "a port is 1 to 65535"}
    uid, gid = ids.split(":")
    env = [f"DATA={data}", f"PUID={uid}", f"PGID={gid}", f"TZ={tz}", f"PORT={port}"]
    if a.get("media"):
        env.append(f"MEDIA={media}")
    for k in a.get("secrets", []):
        v = (secrets or {}).get(k) if isinstance(secrets, dict) else None
        v = str(v) if v else _secrets.token_urlsafe(18)
        if "\n" in v or len(v) > 200:
            return {"error": f"{k} is one line, 200 characters at most"}
        env.append(f"{k}={v}")
    return {"name": app, "compose": a["compose"], "env": "\n".join(env) + "\n"}
