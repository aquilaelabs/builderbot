"""Features switched off for a whole install from its environment (R81).

FEATURES_OFF names them, comma-separated, from the fixed list below, and
FEATURES_OFF_WHY is the sentence a person is shown for each: under every
control the feature draws (the page reads `off()` from the status read), and
as the refusal of every request that would use it, which is the rule; the
page's dead controls are the courtesy. Settings lists what is off.

An install shared with people who should not reach out of it (a classroom, a
locked-down host) is what this is for. A name not on the list is said once at
start and otherwise ignored, so a typo switches nothing off silently.
"""
import os
import re
from html import escape

# Each feature, and what it is in the words Settings lists it by.
FEATURES = {
    "tunnel": "the controller's tunnel from home",
    "ftp": "FTP access to projects",
    "phone": "pairing and lending a phone",
    "devices": "signing in from the apps on a person's own devices",
    "apps": "the apps' downloads",
    "image-updates": "checking for and pulling container image updates",
    "runner": "CI runners on nodes",
    "enroll": "enrolling a node",
    "shell": "a terminal on the controller itself",
    # An install meant to run with no way out (R88): what reaches the
    # internet is off with it, and the Doctor skips asking.
    "internet": "reaching the internet from this install",
}
# What switching the internet off switches off with it.
IMPLIES = {"internet": ("apps", "image-updates", "tunnel", "runner")}
WHY_DEFAULT = "switched off on this install"
TUNNEL_SETTINGS = ("tunnel_host", "tunnel_token", "cf_api_token")
_off = None


def off():
    """{feature: why} for every feature switched off; read once."""
    global _off
    if _off is None:
        names = [n.strip().lower() for n in os.environ.get("FEATURES_OFF", "").split(",") if n.strip()]
        why = os.environ.get("FEATURES_OFF_WHY", "").strip()[:200] or WHY_DEFAULT
        unknown = [n for n in names if n not in FEATURES]
        if unknown:
            print(f"dashboard: FEATURES_OFF names {', '.join(unknown)}, which are not features; "
                  f"the features are {', '.join(FEATURES)}", flush=True)
        _off = {n: why for n in names if n in FEATURES}
        for n in list(_off):
            for m in IMPLIES.get(n, ()):
                _off.setdefault(m, why)
    return _off


def sentences():
    """{feature: the sentence under its dead controls}, for the page."""
    return {n: f"{FEATURES[n][0].upper()}{FEATURES[n][1:]} is off: {w}" for n, w in off().items()}


def listing():
    """What Settings lists: [{name, what, why}] for each feature that is off."""
    return [{"name": n, "what": FEATURES[n], "why": w} for n, w in off().items()]


def _feature(method, path, req):
    """The feature a request would use, or ""."""
    act = str((req or {}).get("action") or "")
    if path == "/api/settings" and method == "POST":
        keys = set(((req or {}).get("set") or {}).keys()) if isinstance((req or {}).get("set"), dict) else set()
        if keys & set(TUNNEL_SETTINGS):
            return "tunnel"
        if any(k.startswith("apps_") for k in keys):
            return "apps"
        return ""
    if path == "/api/project-ftp" and method == "POST" and act not in ("", "view"):
        return "ftp"
    if path == "/api/phone" and method == "POST" and act in ("pair", "connect", "disconnect", "forget"):
        return "phone"
    if path == "/api/artifacts" and method == "POST":
        return "phone"
    if path == "/api/v1/device/signin":
        return "devices"
    if path in ("/api/v1/device/apps", "/api/v1/device/app-file") or path.startswith("/api/apps") \
            or path.startswith("/apps/"):
        return "apps"
    if path == "/api/images" and method == "POST":
        return "image-updates"
    if path in ("/api/devapp", "/api/nginx") and method == "POST" and act == "update":
        return "image-updates"
    if path == "/api/v1/nodes" and method == "POST":
        if act in ("runner", "runner-token", "runner-forget"):
            return "runner"
        if act in ("add", "enroll", "vm-xml"):
            return "enroll"
    return ""


def refused(method, path, req=None):
    """The sentence a request that uses a switched-off feature is refused
    with, or "" when it may go on."""
    if not off():
        return ""
    f = _feature(method, path, req)
    return sentences().get(f, "")


# ---- the install banner (R88) ----------------------------------------------
# One line every visitor sees, on every page and the sign-in page: a shared
# install's word to whoever is on it ("a classroom install: paste no real
# keys", a maintenance notice). Drawn by the page as a band under its
# header, in its own layout, so nothing pinned to the page covers it.

BANNER_MAX = 200
_LINK = re.compile(r"^(https?://[^\s<>\"']+|/[^\s<>\"']*)$")


def banner():
    """{text, link, label} from BANNER_TEXT, BANNER_LINK and
    BANNER_LINK_LABEL, or None when there is no text. A link is http(s) or
    a path on this site, anything else dropped."""
    text = " ".join(os.environ.get("BANNER_TEXT", "").split())[:BANNER_MAX]
    if not text:
        return None
    link = os.environ.get("BANNER_LINK", "").strip()
    link = link if _LINK.match(link) else ""
    label = " ".join(os.environ.get("BANNER_LINK_LABEL", "").split())[:60] or ("more" if link else "")
    return {"text": text, "link": link, "label": label if link else ""}


def banner_html():
    """The band, escaped, or "" when there is none."""
    b = banner()
    if not b:
        return ""
    a = (f' <a href="{escape(b["link"], quote=True)}">{escape(b["label"])}</a>' if b["link"] else "")
    return f'<div class="banner" id="banner" role="status">{escape(b["text"])}{a}</div>'
