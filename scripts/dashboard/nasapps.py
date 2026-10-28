"""Apps a NAS runs (R164 step 2): a catalog of ready containers (a media
server, the arr stack, photos, files, home automation, a download client,
syncing) each a compose file and an environment with a few blanks (where
its data and media live, who it runs as, the time zone, its port), filled
from the New container dialog and made through the Containers page as any
container is: on the node picked, reached on its port, and put behind a
node's nginx with a certificate from that node's nginx page. Images are
pinned to a tag, never latest, and the registry update check says when
one moves. The catalog is this list; the vetted public catalog is R169's.
"""
import re

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


def catalog():
    """The list the dialog shows: [{id, name, what, port, media, secrets}]."""
    return [{"id": k, "name": v["name"], "what": v["what"], "port": v["port"], "media": v.get("media", False), "secrets": v.get("secrets", [])}
            for k, v in APPS.items()]


def render(app, data, media="", ids="1000:1000", tz="UTC", port=None, secrets=None):
    """The compose and the environment for one app with its blanks filled:
    {name, compose, env} or {error}. The environment is where the choices
    live, so the file stays the catalog's and the Environment tab says what
    was picked; a secret the dialog did not give is made here."""
    import secrets as _secrets
    a = APPS.get(str(app or ""))
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
