"""The toolchain store, scoped by platform (roadmap R19): what is installed, who uses it, and what a session's environment gets from it."""
import contextlib
import json
import os
import re
import shutil
import subprocess
from .base import (
    APK_BIN,
    APT_CACHE_BIN,
    DNF_BIN,
    PACMAN_BIN,
    XBPS_QUERY_BIN,
    ZYPPER_BIN,
    _probe,
    _probe_died,
    log,
)
from .stores import STORE_TOOLS, _lay_path, store_layout, tc_root, tc_scope
from .backends import _have, pkg_backend


def tc_dir(store, name, entry, action):
    """The directory a toolchain job would replace or remove, or "" when it
    replaces nothing in place: a toolchain not installed yet, or a versioned
    Android package, whose new version installs beside the old."""
    src = (entry or {}).get("source") or {}
    if name.startswith("android:"):
        if src.get("versioned") and action == "install":
            return ""
        pkg = str(src.get("package") or name.split(":", 1)[1])
        d = os.path.join(store, "android", *pkg.split(";"))
    else:
        d = os.path.join(store, name)
    return d if os.path.isdir(d) else ""


# The recipes `bb toolchains update` knows (sdk.sh sdk_update); an android:*
# package is updated by sdkmanager. Any other is updated by a remove and an
# install, whatever its catalog says.
UPDATE_VERBS = ("flutter", "dotnet", "swift", "playwright")


def tc_verbs(store, name, entry, action):
    """The bb toolchains verbs a job runs for one name, in order. An install
    of a toolchain that is there already is an update: `update` for a recipe
    that verb knows, and for the rest a remove and then the install (R193,
    the operator, 11 Oct: "have it uninstall and reinstall automatically"),
    where bb toolchains install alone dies with "already installed" on a
    fresh_only recipe. Swift is updatable and fresh_only both, and this
    sent it to `install` on a node, which refused it every time (12 Oct).
    Not installed, or any other action: the one verb."""
    src = (entry or {}).get("source") or {}
    if action != "install" or src.get("versioned") or not tc_dir(store, name, entry, action):
        return [action]
    if name in UPDATE_VERBS or name.startswith("android:"):
        return ["update"]
    if src.get("fresh_only") or not (entry or {}).get("updatable"):
        return ["remove", "install"]
    return ["install"]


def tc_users(path, limit=8):
    """The processes using anything under `path`: as their program, a
    library or a jar they have open, or the directory they run in. Each as
    {pid, what, project}, the project from the BB_PROJECT a session's
    processes carry. Read from /proc, which an agent that is root sees
    whole; one that is not sees its own account's, and says no more than it
    can (the operator, 6 Oct: an update under a running build is refused,
    naming whose it is)."""
    root = os.path.realpath(path).rstrip("/") + "/"
    inside = lambda p: (p or "").startswith(root) or (p or "") + "/" == root  # noqa: E731
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        base = f"/proc/{pid}"
        try:
            hit = inside(os.readlink(f"{base}/exe")) or inside(os.readlink(f"{base}/cwd"))
            if not hit:
                with open(f"{base}/maps", encoding="utf-8", errors="replace") as f:
                    hit = any(inside(ln.split(None, 5)[-1].strip()) for ln in f if "/" in ln)
            if not hit:
                for fd in os.listdir(f"{base}/fd"):
                    with contextlib.suppress(OSError):
                        if inside(os.readlink(f"{base}/fd/{fd}")):
                            hit = True
                            break
            if not hit:
                continue
            with open(f"{base}/comm", encoding="utf-8", errors="replace") as f:
                what = f.read().strip()
            project = ""
            with contextlib.suppress(OSError), open(f"{base}/environ", "rb") as f:
                for kv in f.read().split(b"\0"):
                    if kv.startswith(b"BB_PROJECT="):
                        project = kv[len(b"BB_PROJECT="):].decode("utf-8", "replace")[:80]
                        break
        except (OSError, ValueError):
            continue
        out.append({"pid": int(pid), "what": what, "project": project})
        if len(out) >= limit:
            break
    return out


def tc_users_said(name, users):
    """One sentence naming who is using a toolchain, for the job's log."""
    who = ", ".join(f"{u['what']} (pid {u['pid']}{', ' + u['project'] + chr(39) + 's session' if u['project'] else ''})"
                    for u in users)
    return (f"refused: {name} is in use by {who}. Updating or removing it under them "
            "replaces files they are running from; try again when they have finished, "
            "or stop them first\n")


def share_images(store, say=None):
    """The standing rule of the layout, kept each hello: the Android system
    images live once under <store>/shared/android/system-images, and this
    scope's android/system-images is a symlink to them. A scope whose
    android tree grew a real directory there (a first install on a fresh
    store) has it moved under shared and linked; a scope with an android
    tree and no images gets the link so an install lands in the shared
    copy from the start."""
    say = say or (lambda t: log(t))
    if not store or not os.path.isdir(store):
        return
    scoped = os.path.join(store, tc_scope())
    mine = os.path.join(scoped, "android", "system-images")
    shared = os.path.join(store, "shared", "android", "system-images")
    if os.path.islink(mine):
        return
    if os.path.isdir(mine):
        try:
            if not os.path.isdir(shared):
                os.makedirs(os.path.dirname(shared), exist_ok=True)
                os.rename(mine, shared)
            else:
                # Both exist: fold what is only here into the shared copy.
                for e in os.listdir(mine):
                    if not os.path.exists(os.path.join(shared, e)):
                        os.rename(os.path.join(mine, e), os.path.join(shared, e))
                if os.listdir(mine):
                    say(f"toolchain store: {mine} still holds images the shared copy also has: "
                        "remove it by hand and the link is made on the next start")
                    return
                os.rmdir(mine)
            say("toolchain store: the android system images are shared across platforms")
        except OSError as ex:
            say(f"toolchain store: could not share the system images: {ex}")
            return
    if os.path.isdir(shared) and os.path.isdir(os.path.join(scoped, "android")) and not os.path.lexists(mine):
        with contextlib.suppress(OSError):
            os.symlink(os.path.relpath(shared, os.path.dirname(mine)), mine)


def _toolchains(state):
    """What this node can build with: on PATH, or in its toolchain store.
    The census's `toolchains` is what package-build placement selects on."""
    tc = {}
    store = tc_root(state)
    by_report = {}
    for entry in store_layout(state):
        if entry.get("reports") and entry.get("tool"):
            by_report[entry["reports"]] = entry

    def find(name):
        entry = by_report.get(name)
        if store and entry:
            p = _lay_path(store, entry, entry["tool"])
            if os.path.exists(p):
                return p
        for rel in STORE_TOOLS.get(name, ()):
            p = os.path.join(store, rel)
            if store and os.path.exists(p):
                return p
        return shutil.which(name)
    j = find("java")
    if j:
        out, dead = _probe([j, "-version"])
        if dead:
            _probe_died("java", j, out, dead)
        else:
            m = re.search(r'version "([^"]+)"', out)
            tc["java"] = m.group(1) if m else "present"
    for name in ("flutter", "dotnet", "node", "go", "swift", "cargo"):
        p = find(name)
        if p and os.path.isfile(p):
            arg = "version" if name == "go" else "--version"
            key = "rust" if name == "cargo" else name
            out, dead = _probe([p, arg], timeout=20)
            if dead:
                _probe_died(key, p, out, dead)
            else:
                tc[key] = _clean_version((out.splitlines() or [""])[0])
    p = find("android-sdk")
    if p and os.path.isfile(p):
        tc["android-sdk"] = "present"
    p = find("emulator")
    if p and os.path.isfile(p):
        tc["emulator"] = "present"
    p = find("adb")
    if p and os.path.isfile(p):
        tc["adb"] = "present"
    p = find("web-ext")
    if p and os.path.isfile(p):
        tc["web-ext"] = "present"
    return tc


def _clean_version(text):
    """A version line, or "present" when the tool answered with something
    else. `flutter --version` as root leads with "Woah! You appear to be
    trying to run flu…" and rustup with "error: rustup could not choose a
    version". Both mean the thing is there, and neither is a version, so
    putting them on a row as one is worse than saying nothing."""
    line = (text or "").strip()
    if not line or not re.search(r"\d+\.\d+", line[:80]) or re.match(
            r"(?i)\s*(error|warning|woah|note)\b", line):
        return "present"
    return line[:40]


def extract_sandbox_tool(text):
    """The bb-sandbox script embedded in provision-linux.sh: the body of its
    BBSANDBOX heredoc, or "" when the marker pair is not there."""
    m = re.search(r"<<'BBSANDBOX'\n(.*?)\nBBSANDBOX\n", text, re.S)
    return (m.group(1) + "\n") if m else ""


def read_catalog(into):
    """The catalog the bundle carries, or {} when it cannot be read."""
    try:
        with open(os.path.join(into, "config", "toolchains.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def pkg_available(fam, name):
    """Whether this machine's repositories carry `name`: how a recipe entry
    naming alternatives picks the one this release has. A library renamed
    between releases (libasound2 became libasound2t64 in Ubuntu 24.04 and
    Debian 13) is one entry, "libasound2t64|libasound2", rather than a list
    that fails the whole install on every release but one: apt refuses the
    lot when one name is unknown. True when it cannot tell, so the first
    alternative is tried and its failure is the package manager's to say."""
    argv = {"apt": [APT_CACHE_BIN, "show", "-q", name],
            "dnf": [DNF_BIN, "-q", "info", name],
            "zypper": [ZYPPER_BIN, "-q", "-n", "search", "-x", name],
            "pacman": [PACMAN_BIN, "-Si", name],
            "apk": [APK_BIN, "search", "-x", name],
            "xbps": [XBPS_QUERY_BIN, "-R", name]}.get(fam)
    if not argv or not _have(argv[0]):
        return True
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return True
    if fam == "apk":                    # exits 0 either way; found is output
        return p.returncode == 0 and bool(p.stdout.strip())
    return p.returncode == 0


def sysdeps_missing(cat, name, fam, query):
    """(the recipe's system packages missing on this machine, and (family,
    names) when its recipe lists them for another family only). Asked by
    exit code, never by output: dpkg -s and pacman -Q both print a sentence
    on stderr for a missing package, which read as "installed" when the
    text was the test, and rpm -q prints "not installed" on stdout."""
    recipe = next((p for p in cat.get("toolchains") or [] if p.get("name") == name), {})
    system = recipe.get("system") or {}
    want = [str(x) for x in (system.get(fam) or []) if x][:64] if fam else []
    if not want:
        other = next((k for k in ("apt", "dnf", "pacman", "zypper", "apk", "xbps", "emerge")
                      if k != fam and system.get(k)), "")
        return [], ((other, [str(x) for x in system[other][:64]]) if other else None)
    def installed(x):
        try:
            return subprocess.run(query + [x], capture_output=True, timeout=30,
                                  check=False).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    missing = []
    for entry in want:
        # "a|b": met by whichever is installed, and when neither is, the
        # first this machine's repositories carry is the one to install.
        alts = [a for a in entry.split("|") if a] or [entry]
        if not query:
            missing.append(alts[0])    # emerge: no query, --noreplace skips the installed
            continue
        if any(installed(a) for a in alts):
            continue
        missing.append(next((a for a in alts if pkg_available(fam, a)), alts[0])
                       if len(alts) > 1 else alts[0])
    return missing, None


def held_recipes(state, cat):
    """The catalog recipes with system packages whose directory the store
    holds, complete or not: browsers from before the module still need the
    libraries."""
    store = tc_root(state)
    if not store:
        return []
    lay = {e["name"]: e for e in store_layout(state) if e.get("name")}
    out = []
    for p in cat.get("toolchains") or []:
        name = p.get("name")
        if not name or not p.get("system"):
            continue
        e = lay.get(name) or {}
        # By the recipe's own tool where the layout names one: every
        # android:* recipe shares the directory `android`, so the directory
        # existing said the emulator was held on a node that had installed
        # only the command-line tools, and the Tools tab asked for the
        # emulator's libraries on every such node (B139).
        tool = e.get("tool")
        if tool:
            held = os.path.exists(_lay_path(store, e, tool))
        else:
            held = os.path.isdir(os.path.join(store, e.get("dir") or name))
        if held:
            out.append(name)
    return out


def sysdeps_now(state):
    """The census's answer (roadmap R51): {family, unmet: {recipe: [pkg]}},
    from the bundle the store already holds; nothing until one is there."""
    store = tc_root(state)
    into = os.path.join(store, ".bb", "current") if store else ""
    if not into or not os.path.isdir(into):
        return {}
    cat = read_catalog(into)
    fam, query, _ = pkg_backend()
    if not fam or not cat:
        return {}
    unmet = {}
    for name in held_recipes(state, cat):
        missing, _ = sysdeps_missing(cat, name, fam, query)
        if missing:
            unmet[name] = missing
    return {"family": fam, "unmet": unmet}


def sdk_images(state):
    """The android system images in this node's toolchain store, and which of
    its AVDs are built on each.

    A directory walk, deliberately, and not `bb emu images`, which is the same
    listing plus a `du -sk` per image. The controller's own copy can afford
    that; a node cannot. The toolchain store is commonly an NFS export here
    and the tree runs to tens of gigabytes, so a size measured every census
    would be minutes of stat traffic every ten minutes for a number the
    catalog already knows: an image is a guest artifact, identical on every
    host, and its download size comes from Google's index on the controller.

    The AVD half is not derivable anywhere else, which is why it is here. An
    AVD names one image exactly (`image.sysdir.1=system-images/android-36/
    google_apis/x86_64/`) and will not boot without it, so it is the whole
    of the answer to "can this one go?".
    """
    stores = state.get("stores") or {}
    store = tc_root(state)
    if not store:
        return []
    base = os.path.join(store, "android", "system-images")
    rows = []
    for api in sorted(_listdir(base))[:64]:
        for kind in sorted(_listdir(os.path.join(base, api)))[:16]:
            for abi in sorted(_listdir(os.path.join(base, api, kind)))[:8]:
                d = os.path.join(base, api, kind, abi)
                if not os.path.isdir(d) or not _listdir(d):
                    continue          # an empty directory is not an image
                rows.append({"id": f"system-images;{api};{kind};{abi}",
                             "api": api, "kind": kind, "abi": abi, "avds": []})
    if not rows:
        return rows
    by_id = {r["id"]: r for r in rows}
    home = os.path.join(stores.get("data") or "/tmp", "avd")   # as sdk_env sets it
    for name in sorted(_listdir(home))[:64]:
        if not name.endswith(".avd"):
            continue
        try:
            with open(os.path.join(home, name, "config.ini"), encoding="utf-8",
                      errors="replace") as f:
                text = f.read(65536)
        except OSError:
            continue
        # Spaces around the = are allowed: avdmanager writes them, the
        # emulator's own rewrites do not, and both turn up in one directory.
        m = re.search(r"(?m)^\s*image\.sysdir\.1\s*=\s*(\S+)", text)
        if not m:
            continue
        want = m.group(1).rstrip("/").replace("/", ";")
        if want in by_id:
            by_id[want]["avds"].append(name[:-4])
    return rows


def _listdir(path):
    if not path:
        return []
    try:
        return [x for x in os.listdir(path) if not x.startswith(".")]
    except OSError:
        return []


def sdk_env(state, who=None):
    """The environment a job runs with on this node: the toolchain store as
    the toolchain store root, its android/ directory as ANDROID_HOME, its jdk as
    JAVA_HOME, every toolchain it holds on PATH, and AVDs under the data
    store. What the image gets from its Dockerfile, a node gets from here.

    EVERY job, not only a bb verb. It used to be applied in the bb branch of
    Job.exec alone, so `bb build` and `bb test` (a plain exec) ran with a
    bare PATH: measured on a real node, java and go were both NOT-ON-PATH
    and JAVA_HOME unset, on a node whose census reported java 21.0.12.1 and
    go present. The placement gate said yes and then ./gradlew could not
    find a compiler (bug #45).
    """
    stores = state.get("stores") or {}
    store = tc_root(state)
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"), "LANG": "C.UTF-8"}
    if store:
        android = os.path.join(store, "android")
        env.update({"SDK_ROOT": store, "BUILDER_HOME": store, "BB_NODE_TOOLCHAINS": "1",
                    # The scope bb scopes by (common.sh sdk_scope), so a bb run
                    # here installs into and reads this node's own directory
                    # (R196) rather than the platform's shared one.
                    "BB_SDK_SCOPE": tc_scope(),
                    "ANDROID_HOME": android, "ANDROID_SDK_ROOT": android})
        front = []
        for entry in store_layout(state):
            for rel in entry.get("bin") or []:
                d = _lay_path(store, entry, rel)
                if os.path.isdir(d) and d not in front:
                    front.append(d)
            for k, v in (entry.get("env") or {}).items():
                # `=VALUE` is the value itself, not a path: what a toolchain
                # needs set beside where it is (B548: Playwright told not to
                # sweep browsers another install of it did not ask for).
                if v.startswith("="):
                    env.setdefault(k, v[1:])
                    continue
                d = _lay_path(store, entry, v)
                if os.path.exists(d):
                    env.setdefault(k, d)
        # The store ahead of the system PATH: a node that carries its own JDK
        # is meant to build with that one, not with whatever the distribution
        # happens to have.
        env["PATH"] = ":".join(front + [env["PATH"]])
    env["ANDROID_AVD_HOME"] = os.path.join(stores.get("data") or "/tmp", "avd")
    # Where CI logs are archived on this node (roadmap #24, step 4). The
    # workflows honor BB_CI_LOG_DIR and so does `bb ci-log`; without it the
    # runner kept them under its own home, 0700, where a session on the node
    # (a different account) could not read them. The data store is the
    # one directory both accounts see, and the runner's .env (written by
    # _apply_runner) names the same path, so the archive and the reader
    # agree without either being configured by hand.
    env["BB_CI_LOG_DIR"] = ci_log_dir(state)
    # How many workers a test run here may use (R81): the node's setting,
    # else its cores. A project's test command reads it as it likes;
    # BuilderBot's own harness shards its suites across it.
    env["BB_TEST_WORKERS"] = str(state.get("test_workers") or os.cpu_count() or 1)
    return env


def ci_log_dir(state):
    return os.path.join((state.get("stores") or {}).get("data") or "/tmp", "ci-logs")


def runner_env_text(state):
    """The runner's .env: the SAME environment sdk_env hands every other job
    on this node, one KEY=VALUE per line, which the runner reads into every
    job it runs. It carried only BB_CI_LOG_DIR until 8 Sep, so a CI job's
    PATH was the bare system's, with no node, no Playwright and no store, while a
    session or a bb job on the same machine had the toolchain. The browser
    suite then skipped with exit 0 and every 'dashboard tests' run on
    bb-sandbox was green without running a test (bug B74). Sorted, so the
    text is stable and runner_env_sync can compare it byte for byte.
    """
    return "".join(f"{k}={v}\n" for k, v in sorted(sdk_env(state).items()))


def sdk_versions(state):
    """What `bb toolchains versions` reports on this node: {name: version}.

    The SAME generator the controller runs for its own list, so the two
    describe one store the same way. Before this, a node's versions came
    from _toolchains() (a six-name placement summary with crude parsing),
    and the Tools tab showed "present" beside a toolchain the controller could
    name a version for, an unstripped "go version go1.27.0 linux/amd64", and
    nothing at all for the NDK. One store, two descriptions of it.

    Run from a bundle already cached in the toolchain store, which a
    toolchain job puts there: no round trip, no second copy of the probe
    logic, and nothing reported at all until a job has run, which is the
    honest answer rather than a summary standing in for an inventory.
    """
    store = tc_root(state)
    if not store:
        return {}
    bbdir = os.path.join(store, ".bb")
    try:
        cands = [os.path.join(bbdir, d) for d in os.listdir(bbdir)]
        cands.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except OSError:
        return {}
    env = dict(os.environ)
    env.update(sdk_env(state))
    for c in cands[:3]:
        bb = os.path.join(c, "scripts", "bb")
        if not os.path.isfile(bb):
            continue
        try:
            p = subprocess.run(["bash", bb, "toolchains", "versions"], capture_output=True,
                               text=True, timeout=120, check=False, env=env)
        except (OSError, subprocess.SubprocessError):
            return {}
        out = {}
        for line in (p.stdout or "").splitlines():
            f = line.rstrip().split("\t")
            if len(f) == 4 and f[1] not in ("", "-"):
                out[f[0][:40]] = f[1][:40]
        return out
    return {}
