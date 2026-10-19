#!/usr/bin/env python3
"""`bb gpu`: this node's NVIDIA card, from where a session stands (R102).

    gpu.py                  what the card is, how much of its memory is free,
                            who is computing on it, whether this session may
    gpu.py line             that in one line, for bb status; nothing with no card
    gpu.py run [--mem MB] [--wait S] -- CMD...
                            CMD with a turn on the card

A program uses a GPU only if it was written to (CUDA, the video encoder),
so nothing here moves work onto the card. What it gives is the three
things a session cannot work out alone: whether the card is there and
this session's to use, how much of its memory is free, and a turn. The
card's memory is one pool for every session on the node, and two jobs that
each fit alone fail together with "out of memory" halfway through; `run`
takes a lease first (one heavy job at a time per node), waits for its turn
and for the memory it says it needs, then runs the command and lets go.

Whether this session may compute on the card is BB_GPU, which bb-tty sets
from the node's switch and the project's setting: "on", or "node" or
"project" for who said no. Off, CUDA_VISIBLE_DEVICES is empty and the
session's view covers the device CUDA needs, so a program finds no card
and takes its CPU path; this only says why.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from typing import NoReturn

SYS_ROOT = os.environ.get("BB_SYS_ROOT", "/sys")
# The lease: a lock every session on the node can reach. /run/lock is the
# machine's own, world-writable and sticky, and the same in every view.
LOCK_DIR = os.environ.get("BB_GPU_LOCK_DIR") or ("/run/lock" if os.access("/run/lock", os.W_OK) else "/tmp")
LOCK = os.path.join(LOCK_DIR, "builderbot-gpu.lock")
NOTE = os.path.join(LOCK_DIR, "builderbot-gpu.holder")


def die(msg) -> NoReturn:
    sys.stderr.write(f"[builderbot] ERROR: {msg}\n")
    sys.exit(1)


def card():
    """Whether the machine has an NVIDIA display device at all."""
    base = os.path.join(SYS_ROOT, "bus", "pci", "devices")
    try:
        for dev in os.listdir(base):
            try:
                with open(os.path.join(base, dev, "vendor")) as f, open(os.path.join(base, dev, "class")) as g:
                    if f.read().strip() == "0x10de" and g.read().strip().startswith("0x03"):
                        return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def smi(*query):
    """One nvidia-smi query's rows, or None when the driver does not answer."""
    tool = shutil.which("nvidia-smi")
    if not tool:
        return None
    try:
        p = subprocess.run([tool, *query, "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    return [[c.strip() for c in line.split(",")] for line in p.stdout.splitlines() if line.strip()]


def may():
    """("" when this session may compute on the card, else why not)."""
    who = os.environ.get("BB_GPU", "on")
    if who == "project":
        return "this project's settings say the node's GPU is not for it (The node's GPU)"
    if who == "node":
        return "this node's GPU is switched off for sessions and jobs (Nodes page, GPU)"
    return ""


def state():
    """{card, name, used, total, free, why} in megabytes; name "" when the
    driver does not have the card."""
    out = {"card": card(), "name": "", "used": 0, "total": 0, "free": 0, "why": may()}
    rows = smi("--query-gpu=name,memory.used,memory.total") if out["card"] else None
    if rows:
        try:
            out["name"], out["used"], out["total"] = rows[0][0], int(rows[0][1]), int(rows[0][2])
            out["free"] = out["total"] - out["used"]
        except (IndexError, ValueError):
            pass
    return out


def gb(mb):
    return f"{mb / 1024:.1f} GB"


def holder():
    """Who holds the lease now, in words, or "" when nobody does."""
    try:
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o666)
    except OSError:
        return ""
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return ""
    except OSError:
        try:
            with open(NOTE, encoding="utf-8", errors="replace") as f:
                h = json.load(f)
            mins = max(0, int(time.time() - int(h.get("since") or 0)) // 60)
            return f"{h.get('project') or 'a session'}, for {mins} min: {str(h.get('cmd') or '')[:80]}"
        except (OSError, ValueError):
            return "another session"
    finally:
        os.close(fd)


def line():
    s = state()
    if not s["card"]:
        return ""
    if not s["name"]:
        return "an NVIDIA card with no driver on it: nothing computes on it until the operator installs one (Toolchains page)"
    if s["why"]:
        return f"{s['name']}, not this session's to compute on: {s['why']}"
    h = holder()
    return (f"{s['name']}, {gb(s['free'])} of {gb(s['total'])} free"
            + (f"; the card's turn is held by {h}" if h else "") + "; bb gpu run -- CMD takes a turn on it")


def status():
    s = state()
    if not s["card"]:
        print("no NVIDIA card on this machine")
        return 0
    if not s["name"]:
        print("an NVIDIA card, and NVIDIA's driver does not have it: nothing can compute on it.")
        print("The operator installs the driver from this node's Toolchains page; bb toolchains says where it stands.")
        return 0
    print(f"card      {s['name']}")
    print(f"memory    {gb(s['free'])} free of {gb(s['total'])} ({s['used']} MB in use)")
    apps = smi("--query-compute-apps=pid,used_memory,process_name") or []
    for a in apps[:8]:
        if len(a) >= 3:
            print(f"  using   {a[1]} MB  {a[2]} (pid {a[0]})")
    h = holder()
    print(f"turn      {'held by ' + h if h else 'free'}")
    if s["why"]:
        print(f"you       may not compute on it: {s['why']}. A program here finds no card and takes its CPU path.")
    else:
        print("you       may compute on it: bb gpu run [--mem MB] -- CMD takes a turn, so two heavy jobs do not run out of memory together")
    return 0


def run(argv):
    mem, wait = 0, 3600
    while argv and argv[0] != "--":
        if argv[0] in ("--mem", "--wait") and len(argv) > 1 and argv[1].isdigit():
            if argv[0] == "--mem":
                mem = int(argv[1])
            else:
                wait = int(argv[1])
            argv = argv[2:]
        else:
            die("bb gpu run [--mem MB] [--wait SECONDS] -- CMD...")
    cmd = argv[1:] if argv and argv[0] == "--" else []
    if not cmd:
        die("bb gpu run [--mem MB] [--wait SECONDS] -- CMD...: the command comes after --")
    s = state()
    if not s["card"]:
        die("no NVIDIA card on this machine: run the command without bb gpu run, on the CPU")
    if s["why"]:
        die(f"{s['why']}: run the command without bb gpu run, and it takes its CPU path")
    if not s["name"]:
        die("the card has no driver on it, so nothing can compute on it: say so in your reply; "
            "the operator installs it from this node's Toolchains page")
    if mem and mem > s["total"]:
        die(f"{mem} MB is more than the card has ({s['total']} MB)")
    try:
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o666)
    except OSError as e:
        die(f"could not open the card's lock at {LOCK}: {e}")
    try:
        os.chmod(LOCK, 0o666)     # another account's session opens it too
    except OSError:
        pass                      # somebody else's file, already open to all
    until = time.time() + wait
    said = False
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() > until:
                die(f"the card's turn did not come free in {wait} s: held by {holder() or 'another session'}")
            if not said:
                sys.stderr.write(f"[builderbot] waiting for the card's turn: held by {holder() or 'another session'}\n")
                said = True
            time.sleep(1)
    try:
        said = False
        while mem and state()["free"] < mem:
            if time.time() > until:
                die(f"{mem} MB of the card's memory did not come free in {wait} s ({state()['free']} MB free)")
            if not said:
                sys.stderr.write(f"[builderbot] waiting for {mem} MB of the card's memory ({state()['free']} MB free now)\n")
                said = True
            time.sleep(5)
        try:
            with open(NOTE, "w", encoding="utf-8") as f:
                json.dump({"project": os.environ.get("BB_PROJECT") or os.path.basename(os.getcwd()),
                           "since": int(time.time()), "cmd": " ".join(cmd)[:200]}, f)
            os.chmod(NOTE, 0o666)
        except OSError:
            pass
        try:
            return subprocess.run(cmd, env=dict(os.environ, BB_GPU_TURN="1"), check=False).returncode
        except FileNotFoundError:
            die(f"no such command: {cmd[0]}")
        except KeyboardInterrupt:
            return 130
    finally:
        try:
            os.remove(NOTE)
        except OSError:
            pass
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def main(argv):
    if not argv:
        return status()
    if argv[0] == "line":
        text = line()
        if text:
            print(text)
        return 0
    if argv[0] == "run":
        return run(argv[1:])
    if argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0
    die("bb gpu [run [--mem MB] [--wait SECONDS] -- CMD...]")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
