"""Reporting for the controller's own machine (R164 step 4): what every
heartbeat samples (CPU, memory, the network's bytes in and out, the disks'
bytes read and written, the CPU's and the disks' temperature) kept for
weeks at falling resolution, where the samples ring (nodes._samples) holds
an hour. Five-minute means for two days and hourly means for sixty, each
point the mean of what fell in it, written to one small file per node
under the state as a bucket closes; the rates come from the agent's
cumulative counters, so a restart of the agent (a counter back to zero)
is one skipped point, never a spike.
"""
import json
import os
import threading
import time

STATE = None
write_json = None
_lock = threading.RLock()
FIELDS = ("cpu", "mem", "rx", "tx", "read", "write", "temp", "disk_temp")
M5_S, H1_S = 300, 3600
M5_KEEP, H1_KEEP = 48 * 12, 60 * 24
SPANS = {"6h": ("m5", 6 * 12), "day": ("m5", 24 * 12), "week": ("h1", 7 * 24), "month": ("h1", 30 * 24)}
_store = {}        # nid -> {"m5": [[at, *means], ...], "h1": [...]}
_cur = {}          # nid -> {"at": bucket start, "sum": [..], "n": [..]}
_prev = {}         # nid -> (at, net, io) the counters before, for the rates


def configure(*, state, write_json=None):
    globals()["STATE"] = state
    globals()["write_json"] = write_json or _write
    _store.clear(); _cur.clear(); _prev.clear()


def _write(path, data):
    tmp = path + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def _path(nid):
    return os.path.join(STATE, "history", f"{nid}.json")


def _load(nid):
    if nid in _store:
        return _store[nid]
    d = {"m5": [], "h1": []}
    try:
        with open(_path(nid), encoding="utf-8") as f:
            got = json.load(f)
        for k in ("m5", "h1"):
            d[k] = [p for p in (got.get(k) or []) if isinstance(p, list) and len(p) == 1 + len(FIELDS)]
    except (OSError, ValueError):
        pass
    _store[nid] = d
    return d


def _save(nid):
    os.makedirs(os.path.join(STATE, "history"), exist_ok=True)
    write_json(_path(nid), _store[nid])


def _mean(cur):
    return [round(cur["sum"][i] / cur["n"][i], 1) if cur["n"][i] else None for i in range(len(FIELDS))]


def add(nid, sample, disk_temp=None, now=None):
    """One heartbeat's sample into the node's buckets: {at, cpu_pct,
    mem_mb, mem_used_mb, net: [rx, tx], io: [read, write], temp_c}, with
    the disks' hottest reading beside it. A bucket that closes becomes a
    point, and a closed hour folds its twelve into one."""
    if not STATE:
        return
    at = int(sample.get("at") or now or time.time())
    vals = [None] * len(FIELDS)
    if isinstance(sample.get("cpu_pct"), (int, float)):
        vals[0] = float(sample["cpu_pct"])
    if sample.get("mem_mb"):
        vals[1] = 100.0 * float(sample.get("mem_used_mb") or 0) / float(sample["mem_mb"])
    prev = _prev.get(nid)
    net, io = sample.get("net"), sample.get("io")
    if prev and isinstance(net, list) and isinstance(prev[1], list) and at > prev[0]:
        dt = at - prev[0]
        if net[0] >= prev[1][0] and net[1] >= prev[1][1]:
            vals[2], vals[3] = (net[0] - prev[1][0]) / dt, (net[1] - prev[1][1]) / dt
    if prev and isinstance(io, list) and isinstance(prev[2], list) and at > prev[0]:
        dt = at - prev[0]
        if io[0] >= prev[2][0] and io[1] >= prev[2][1]:
            vals[4], vals[5] = (io[0] - prev[2][0]) / dt, (io[1] - prev[2][1]) / dt
    _prev[nid] = (at, net if isinstance(net, list) else None, io if isinstance(io, list) else None)
    if isinstance(sample.get("temp_c"), (int, float)):
        vals[6] = float(sample["temp_c"])
    if isinstance(disk_temp, (int, float)):
        vals[7] = float(disk_temp)
    with _lock:
        d = _load(nid)
        cur = _cur.get(nid)
        bucket = at - at % M5_S
        if cur and cur["at"] != bucket:
            _close(nid, d, cur)
            cur = None
        if not cur:
            cur = _cur[nid] = {"at": bucket, "sum": [0.0] * len(FIELDS), "n": [0] * len(FIELDS)}
        for i, v in enumerate(vals):
            if v is not None:
                cur["sum"][i] += v
                cur["n"][i] += 1


def _close(nid, d, cur):
    """The bucket as a point; the hour it ended folded when it is whole."""
    d["m5"].append([cur["at"], *_mean(cur)])
    del d["m5"][:-M5_KEEP]
    hour = cur["at"] - cur["at"] % H1_S
    if cur["at"] + M5_S >= hour + H1_S:
        mine = [p for p in d["m5"] if hour <= p[0] < hour + H1_S]
        if mine and not any(p[0] == hour for p in d["h1"]):
            folded = []
            for i in range(len(FIELDS)):
                have = [p[1 + i] for p in mine if p[1 + i] is not None]
                folded.append(round(sum(have) / len(have), 1) if have else None)
            d["h1"].append([hour, *folded])
            del d["h1"][:-H1_KEEP]
    try:
        _save(nid)
    except OSError:
        pass


def points(nid, span):
    """{span, step, fields, points: [[at, ...], ...]} for one node over a
    span (6h, day, week, month): the closed points and the bucket still
    open as the last one."""
    ring, count = SPANS.get(span, SPANS["day"])
    with _lock:
        d = _load(nid)
        out = list(d[ring][-count:])
        cur = _cur.get(nid)
        if cur and ring == "m5":
            out.append([cur["at"], *_mean(cur)])
        elif cur and ring == "h1":
            hour = cur["at"] - cur["at"] % H1_S
            mine = [p for p in d["m5"] if p[0] >= hour] + [[cur["at"], *_mean(cur)]]
            folded = []
            for i in range(len(FIELDS)):
                have = [p[1 + i] for p in mine if p[1 + i] is not None]
                folded.append(round(sum(have) / len(have), 1) if have else None)
            if not any(p[0] == hour for p in out):
                out.append([hour, *folded])
    return {"span": span if span in SPANS else "day", "step": M5_S if ring == "m5" else H1_S, "fields": list(FIELDS), "points": out}


def forget(nid):
    """A node gone: its file with it."""
    with _lock:
        _store.pop(nid, None); _cur.pop(nid, None); _prev.pop(nid, None)
    try:
        os.unlink(_path(nid))
    except OSError:
        pass
