"""Where the companion app keeps its device token (R270 step 4): Windows'
Credential Manager, through its own API, so the token is the account's on
this machine and no file holds it; elsewhere a file only its owner reads.
The password is never kept anywhere: it is traded once for the token.
"""
import json
import os
import sys

TARGET = "BuilderBot companion"


def _file():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "BuilderBot")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "device.json")


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    _adv = ctypes.WinDLL("advapi32", use_last_error=True)
    _CRED_TYPE_GENERIC, _CRED_PERSIST_LOCAL_MACHINE = 1, 2

    def save(record):
        blob = json.dumps(record).encode("utf-8")
        c = _CREDENTIAL()
        c.Type, c.TargetName, c.Persist = _CRED_TYPE_GENERIC, TARGET, _CRED_PERSIST_LOCAL_MACHINE
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ctypes.cast(ctypes.create_string_buffer(blob, len(blob)), ctypes.POINTER(ctypes.c_byte))
        c.UserName = record.get("account", "")
        if not _adv.CredWriteW(ctypes.byref(c), 0):
            raise OSError(ctypes.get_last_error(), "could not keep the token in Windows' credential store")

    def load():
        p = ctypes.POINTER(_CREDENTIAL)()
        if not _adv.CredReadW(TARGET, _CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
            return {}
        try:
            raw = ctypes.string_at(p.contents.CredentialBlob, p.contents.CredentialBlobSize)
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return {}
        finally:
            _adv.CredFree(p)

    def forget():
        _adv.CredDeleteW(TARGET, _CRED_TYPE_GENERIC, 0)
else:
    def save(record):
        path = _file()
        fd = os.open(path + ".new", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(record, f)
        os.replace(path + ".new", path)

    def load():
        try:
            with open(_file()) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def forget():
        try:
            os.remove(_file())
        except FileNotFoundError:
            pass
