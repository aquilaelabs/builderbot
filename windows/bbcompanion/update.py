"""The app kept current by its controller (R270 step 9): a person's device,
not a machine of the controller's, so nothing pushes to it; the app asks.

At start and once a day it asks its controller's door what the controller
holds of it (the apps verb, R272), and when that is newer than itself it
fetches the file it runs as (the .exe, or the .pyz), checks it against the
controller's sha256 and, where this copy is signed, that the new one is
signed too, and leaves it beside itself. The next start swaps it in
(apply_pending) and starts again from it. Run from a checkout, it is never
replaced: the checkout is somebody's working tree.
"""
import hashlib
import os
import pkgutil
import re
import subprocess
import sys
import urllib.parse

DOOR = 1                # the device door this app speaks (devices.DOOR)


def version():
    """The release this copy was built for (its VERSION, written by the
    build), or 0.0.0 for a checkout."""
    try:
        return (pkgutil.get_data("bbcompanion", "VERSION") or b"").decode().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _parts(v):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", str(v or ""))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def newer(theirs, mine):
    return _parts(theirs) > _parts(mine)


def running_as():
    """("exe" | "pyz", the file) for a packaged copy; ("", "") from a
    checkout, which is never replaced."""
    if getattr(sys, "frozen", False):
        return "exe", os.path.abspath(sys.executable)
    me = os.path.abspath(sys.argv[0] if sys.argv else "")
    if me.endswith(".pyz") and os.path.isfile(me):
        return "pyz", me
    return "", ""


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def signed(path):
    """Whether Windows trusts the file's Authenticode signature; None off
    Windows, where there is none to ask about."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class FileInfo(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pcwszFilePath", wintypes.LPCWSTR),
                    ("hFile", wintypes.HANDLE), ("pgKnownSubject", ctypes.c_void_p)]

    class TrustData(ctypes.Structure):
        _fields_ = [("cbStruct", wintypes.DWORD), ("pPolicyCallbackData", ctypes.c_void_p),
                    ("pSIPClientData", ctypes.c_void_p), ("dwUIChoice", wintypes.DWORD),
                    ("fdwRevocationChecks", wintypes.DWORD), ("dwUnionChoice", wintypes.DWORD),
                    ("pFile", ctypes.POINTER(FileInfo)), ("dwStateAction", wintypes.DWORD),
                    ("hWVTStateData", wintypes.HANDLE), ("pwszURLReference", wintypes.LPCWSTR),
                    ("dwProvFlags", wintypes.DWORD), ("dwUIContext", wintypes.DWORD)]

    class Guid(ctypes.Structure):
        _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]

    # WINTRUST_ACTION_GENERIC_VERIFY_V2
    action = Guid(0xAAC56B, 0xCD44, 0x11D0, (ctypes.c_ubyte * 8)(0x8C, 0xC2, 0x00, 0xC0, 0x4F, 0xC2, 0x95, 0xEE))
    fi = FileInfo(ctypes.sizeof(FileInfo), path, None, None)
    td = TrustData(ctypes.sizeof(TrustData), None, None, 2, 0, 1, ctypes.pointer(fi), 0, None, None, 0, 0)
    return ctypes.windll.wintrust.WinVerifyTrust(None, ctypes.byref(action), ctypes.byref(td)) == 0


def check(ctl):
    """Ask the controller what it holds of this app and fetch it when it is
    newer: {current | pending | said}. `ctl` is the door's connection."""
    kind, me = running_as()
    st, r = ctl.call("apps", {})
    if st != 200:
        return {"said": f"could not ask the controller for updates ({(r or {}).get('error') or st})"}
    app = next((a for a in r.get("apps") or [] if a.get("name") == "companion"), None)
    if not app:
        return {"said": "this controller does not offer the companion: it is not updated from here"}
    mine = version()
    if not newer(app.get("version"), mine):
        return {"current": mine}
    if not kind:
        return {"said": f"{app['version']} is out; this copy runs from a checkout, which is never replaced"}
    f = next((x for x in app.get("files") or [] if x.get("file", "").endswith("." + kind)), None)
    if not f:
        return {"said": f"{app['version']} is out, but not as a .{kind}"}
    dest = me + ".new"
    code, _ = ctl.fetch("app-file?app=companion&file=" + urllib.parse.quote(f["file"]), dest)
    if code != 200:
        return {"said": f"the update did not download ({code})"}
    if _sha256(dest) != f.get("sha256"):
        os.remove(dest)
        return {"said": "the update did not match the controller's sha256: not kept"}
    if signed(me) and not signed(dest):
        os.remove(dest)
        return {"said": "the update is not signed where this copy is: not kept"}
    with open(dest + ".sha256", "w") as w:
        w.write(f["sha256"] + "\n")
    return {"pending": app["version"]}


def apply_pending(argv=None):
    """At start: a fetched update swapped in for this copy and started in
    its place, or nothing. Returns only when nothing was swapped."""
    kind, me = running_as()
    if not kind:
        return
    old, new = me + ".old", me + ".new"
    try:
        os.remove(old)                    # the copy the last swap left
    except OSError:
        pass
    if not os.path.isfile(new):
        return
    try:
        with open(new + ".sha256") as f:
            want = f.read().split()[0]
    except (OSError, IndexError):
        want = ""
    if not want or _sha256(new) != want:
        for p in (new, new + ".sha256"):
            try:
                os.remove(p)
            except OSError:
                pass
        return
    # A running .exe may be renamed on Windows though not replaced, so this
    # copy steps aside and the new one takes its name.
    os.replace(me, old)
    os.replace(new, me)
    os.remove(new + ".sha256")
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = [me] + args if kind == "exe" else [sys.executable, me] + args
    subprocess.Popen(cmd, close_fds=True)                     # noqa: S603 (itself, just checked)
    sys.exit(0)
