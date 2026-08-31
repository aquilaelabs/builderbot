#!/usr/bin/env python3
"""Which docker daemon this container talks to, and whether it answers.

One line on stdout, as `ok|FAIL|skip <sentence>`, for whoever wants to render
it: `bb doctor` as a check row, the startup hook as a boot line.

Shared rather than written twice, for the reason source() itself exists: two
readers each deriving it had already disagreed in public, and a sentence that
contradicts itself is worse than no sentence. The way to not have two is to
not have two.

The probe is devapp.available(), the same call the Artifacts tab makes on its
own poll, so nothing here can drift into disagreeing with the tab about
whether the thing is up.
"""
import importlib.util
import os
import sys


def load(path):
    spec = importlib.util.spec_from_file_location("devapp", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def verdict(m):
    """(state, sentence). state is ok, FAIL or skip."""
    # Off is not a fault to report. A red line on every run of a box that never
    # wanted dev instances is noise, and noise is how a check stops being read.
    if not (os.environ.get("DOCKER_HOST") or "").strip():
        return "skip", ("no docker daemon configured: DOCKER_HOST is unset — "
                        "dev instances are off")
    a = m.available()
    why = " ".join((a["why"] or "").split())      # one line, whatever it said
    return ("ok" if a["on"] else "FAIL"), (
        f"docker daemon: {a['kind']} at {a['where']}"
        + ("" if a["on"] else f" — {why}"))


def mapping_faults(m):
    """Complaints about DOCKER_HOST_PATHS, or an empty list.

    Worth a boot line of its own because it is the failure nothing else
    catches: a pair whose two sides have drifted apart means a bind mount
    resolving to a directory the daemon does not have, and docker answers that
    by creating an empty one rather than by failing.
    """
    try:
        bad = list(m.host_map()[1])
        return bad + [f"{p} is mapped but this container does not have it"
                      for p in m.stray_map_entries(m.host_map()[0])]
    except Exception:                             # noqa: BLE001 - never fatal
        return []


def main(argv):
    path = argv[0] if argv else os.environ.get("BB_DEVAPP", "")
    if not path or not os.path.isfile(path):
        print("skip docker daemon: devapp.py was not found beside this")
        return 0
    try:
        m = load(path)
    except Exception as e:                        # noqa: BLE001
        print(f"skip docker daemon: could not be probed ({e})")
        return 0
    state, line = verdict(m)
    print(f"{state} {line}")
    if state != "skip":
        for fault in mapping_faults(m):
            print(f"warn host path mapping: {fault}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
