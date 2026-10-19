"""The companion app's own settings (R270 step 4): which projects this
machine keeps and in which folders, the controller's address and its
certificate's pin. Not secret: the device token is creds.py's.
"""
import json
import os


def home():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "BuilderBot")
    os.makedirs(d, exist_ok=True)
    return d


def path():
    return os.path.join(home(), "companion.json")


def data_dir():
    """The sync's own records (a project's last-agreed state), apart from
    the folders it keeps in step."""
    return os.path.join(home(), "data")


def load():
    try:
        with open(path()) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("picked", {})
    return d


def save(d):
    with open(path() + ".new", "w") as f:
        json.dump(d, f, indent=1)
    os.replace(path() + ".new", path())
