#!/usr/bin/env python3
"""bb tidy [--keep KIND]... [--dry]: give back what a task left holding.

After a task or a batch of tasks, a session ends what it started and no
longer needs and clears its scratch out of memory: its emulator (through bb
emu stop, so its state is saved), anything else of its own holding the
NVIDIA card, its Gradle and Kotlin daemons, the headless browsers a test
left running, and its own files in /tmp, which in a session is memory
(a tmpfs). What it keeps is named with --keep and a reason said in the
reply: the next task uses the emulator, a daemon is warm for a build
about to run (the operator, 6 Oct: one verb for every resource a task
holds, not one per resource).

Only this session's own: its view holds only its processes, and only this
account's are counted besides. Never Claude Code itself, its shell, tmux,
the terminal server or anything this command runs under; never Claude
Code's own folder in /tmp (the scratchpad, background commands' output);
never a socket, and never a file a running process still has open.

Kinds: emulator, gpu, gradle, browser, tmp.
"""
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import time

KINDS = ("emulator", "gpu", "gradle", "browser", "tmp")
TMP = os.environ.get("BB_TIDY_TMP", "/tmp")
PROC = os.environ.get("BB_TIDY_PROC", "/proc")
# Never ended, whatever they hold: what this session runs inside of.
SPARE = ("claude", "tmux", "tmux: server", "ttyd", "bb-session", "bash", "sh", "zsh", "sudo", "node")


def proc_info(pid, root=PROC):
    """(comm, args, uid) of a process, or None."""
    base = os.path.join(root, str(pid))
    try:
        with open(os.path.join(base, "comm"), encoding="utf-8", errors="replace") as f:
            comm = f.read().strip()
        with open(os.path.join(base, "cmdline"), "rb") as f:
            args = f.read(4096).replace(b"\0", b" ").decode("utf-8", "replace").strip()
        uid = os.stat(base).st_uid
    except OSError:
        return None
    return comm, args, uid


def ancestors(pid=None, root=PROC):
    """This process and every one above it: never ended."""
    out, pid = set(), pid or os.getpid()
    while pid and pid not in out:
        out.add(pid)
        try:
            with open(os.path.join(root, str(pid), "stat"), encoding="utf-8") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def parent_comm(pid, root=PROC):
    """The command of a process's parent, or "" (init, or gone)."""
    try:
        with open(os.path.join(root, str(pid), "stat"), encoding="utf-8") as f:
            ppid = int(f.read().rsplit(")", 1)[1].split()[1])
    except (OSError, ValueError, IndexError):
        return ""
    if ppid <= 1:
        return ""
    info = proc_info(ppid, root)
    if not info:
        return ""
    # By what it runs, not its name: node names its main thread MainThread.
    head = os.path.basename((info[1].split() or [info[0]])[0])
    return head or info[0]


def kind_of(comm, args, fds, parent=""):
    """Which kind a process is, by what it runs and what it holds, or "".
    A browser counts only once what drove it is gone: a test's Playwright
    (node or python) still running owns its browsers, and a tidy run beside
    a suite would have ended the suite's pages."""
    if comm.startswith("qemu-system") or comm == "emulator":
        return "emulator"
    if any(f.startswith("/dev/nvidia") for f in fds):
        return "gpu"
    if comm == "java" and ("GradleDaemon" in args or "KotlinCompileDaemon" in args or "kotlin-daemon" in args):
        return "gradle"
    if comm.startswith("chrome_crashpad"):
        return "crashpad"    # its browser's helper, reparented to the root: see processes()
    if comm in ("chrome", "chromium", "headless_shell", "firefox") \
            or ("ms-playwright" in args and comm != "node"):
        if parent in ("chrome", "chromium", "headless_shell", "firefox"):
            return ""        # a browser's own helper: it goes with its browser
        return "" if parent.startswith(("node", "python")) else "browser"
    return ""


def fds_of(pid, root=PROC):
    out = []
    d = os.path.join(root, str(pid), "fd")
    with contextlib.suppress(OSError):
        for fd in os.listdir(d):
            with contextlib.suppress(OSError):
                out.append(os.readlink(os.path.join(d, fd)))
    return out


def processes(root=PROC, uid=None, spare=None):
    """[(pid, comm, kind)] of this account's processes a tidy would end."""
    uid = os.getuid() if uid is None else uid
    spare = ancestors(root=root) if spare is None else spare
    out = []
    for pid in os.listdir(root):
        if not pid.isdigit() or int(pid) in spare:
            continue
        info = proc_info(pid, root)
        if not info or info[2] != uid or info[0] in SPARE:
            continue
        k = kind_of(info[0], info[1], fds_of(pid, root), parent_comm(pid, root))
        if k:
            out.append((int(pid), info[0], k))
    # A crash handler goes when no browser of this account's is left running
    # under something alive: it is reparented to the root from the start.
    alive = any(proc_info(p, root) and proc_info(p, root)[0] in ("chrome", "chromium", "headless_shell")
                and parent_comm(p, root).startswith(("node", "python")) for p in os.listdir(root) if p.isdigit())
    return [(p, c, "browser") if k == "crashpad" else (p, c, k) for p, c, k in out
            if k != "crashpad" or not alive]


def open_files(root=PROC):
    """Every path a running process has open or runs in: kept in /tmp."""
    out = set()
    for pid in os.listdir(root):
        if not pid.isdigit():
            continue
        out.update(fds_of(pid, root))
        with contextlib.suppress(OSError):
            out.add(os.readlink(os.path.join(root, pid, "cwd")))
    return out


def tmp_entries(tmp=TMP, uid=None, held=None):
    """The entries of /tmp a tidy would remove: this account's, not Claude
    Code's own folder, not a socket or a directory of sockets, and nothing
    a running process has open or stands in."""
    uid = os.getuid() if uid is None else uid
    held = open_files() if held is None else held
    # ...and the suite's run lock, a directory nothing holds open while a
    # run goes on (one run at a time: the house rule tests).
    keep = {f"claude-{uid}", ".X11-unix", "cc-socks", f"tmux-{uid}", ".ICE-unix", ".font-unix",
            "dashboard-test.d"}
    out = []
    for name in sorted(os.listdir(tmp)):
        path = os.path.join(tmp, name)
        if name in keep or name.startswith("tmux-"):
            continue
        try:
            st = os.lstat(path)
        except OSError:
            continue
        if st.st_uid != uid or (st.st_mode & 0o170000) == 0o140000:
            continue
        if any(h == path or h.startswith(path + "/") for h in held):
            continue
        out.append(path)
    return out


def size_of(path):
    total = 0
    if os.path.isdir(path) and not os.path.islink(path):
        for d, _, files in os.walk(path):
            for f in files:
                with contextlib.suppress(OSError):
                    total += os.lstat(os.path.join(d, f)).st_size
    else:
        with contextlib.suppress(OSError):
            total = os.lstat(path).st_size
    return total


def card_used():
    tool = shutil.which("nvidia-smi")
    if not tool:
        return None
    try:
        p = subprocess.run([tool, "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, check=False)
        return sum(int(x) for x in p.stdout.split() if x.isdigit())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def mb(n):
    return f"{n / 1048576:.0f} MB" if n < 1073741824 else f"{n / 1073741824:.1f} GB"


def main(argv):
    keep, dry = set(), False
    while argv:
        a = argv.pop(0)
        if a == "--keep" and argv:
            k = argv.pop(0)
            if k not in KINDS:
                sys.exit(f"[builderbot] ERROR: bb tidy --keep takes one of {', '.join(KINDS)}, not '{k}'")
            keep.add(k)
        elif a == "--dry":
            dry = True
        elif a in ("-h", "--help"):
            print((__doc__ or "").strip())
            return 0
        else:
            sys.exit(f"[builderbot] ERROR: bb tidy [--keep {'|'.join(KINDS)}]... [--dry]: not '{a}'")
    card0 = card_used()
    procs = [p for p in processes() if p[2] not in keep]
    files = [] if "tmp" in keep else tmp_entries()
    freed_tmp = sum(size_of(f) for f in files)
    if dry:
        for pid, comm, k in procs:
            print(f"would end {k}: {comm} ({pid})")
        for f in files:
            print(f"would remove {f} ({mb(size_of(f))})")
        print(f"kept: {', '.join(sorted(keep)) or 'nothing'}")
        return 0
    if any(k == "emulator" for _, _, k in procs):
        subprocess.run(["bb", "emu", "stop"], check=False)
    for pid, _, _ in procs:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not any(os.path.exists(os.path.join(PROC, str(p))) for p, _, _ in procs):
            break
        time.sleep(0.5)
    for pid, comm, _ in procs:
        if os.path.exists(os.path.join(PROC, str(pid))):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGKILL)
                print(f"{comm} ({pid}) did not stop when asked: killed")
    for f in files:
        with contextlib.suppress(OSError):
            if os.path.isdir(f) and not os.path.islink(f):
                shutil.rmtree(f)
            else:
                os.unlink(f)
    ended = ", ".join(f"{comm} ({k})" for _, comm, k in procs) or "nothing running"
    print(f"ended: {ended}")
    print(f"/tmp: removed {len(files)} entr{'y' if len(files) == 1 else 'ies'}, {mb(freed_tmp)}"
          + (" (kept)" if "tmp" in keep else ""))
    card1 = card_used()
    if card0 is not None and card1 is not None:
        time.sleep(1)
        card1 = card_used() or card1
        print(f"the card: {card0} MB in use before, {card1} MB now")
    if keep:
        print(f"kept: {', '.join(sorted(keep))}: say why in your reply")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
