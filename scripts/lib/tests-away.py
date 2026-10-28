"""Behind `bb tests` when the project's settings name a test node that is not
this machine (R151, tests_node_away in bb): which node, how many workers it
has room for, and its place in that node's queue, printed one per line for
bb to read:

    node id
    node name
    workers (its cores, held to its memory at two gigabytes a worker)
    jobs ahead of a new one there (queued or running)

Nothing when the setting names no node, or names this one; an error on
stderr and exit 1 when it names a node this session cannot see.
"""
import json
import os
import sys

import bbapi

auth = os.environ.get("BB_AUTH_HEADER", "")
project = os.environ.get("BB_PROJECT", "")
want = os.environ.get("BB_TEST_NODE_WANT", "")
here = os.environ.get("BB_NODE", "")
if not want or want == here:
    sys.exit(0)
nodes = bbapi.call("/api/v1/nodes", auth=auth).get("nodes") or []
hit = next((n for n in nodes if n.get("id") == want or n.get("name") == want), None)
if not hit:
    sys.exit(f"[builderbot] ERROR: the test node {want} in {project}'s settings is not one this session may use"
             " (bb nodes lists them); its settings dialog picks another, or none for this machine")
if hit.get("state") not in ("online", "draining") or not hit.get("live", True):
    sys.exit(f"[builderbot] ERROR: the test node {hit.get('name')} is {hit.get('state') or 'not online'}: the suites would wait on it;"
             " its settings dialog picks another, or none for this machine")
rep = hit.get("reported") or {}
cpu = int(rep.get("cpu") or 1)
mem = int(rep.get("mem_mb") or 0)
workers = max(1, min(cpu, mem // 2048 if mem else cpu))
ahead = [j for j in (bbapi.call("/api/v1/jobs?active=1", auth=auth).get("jobs") or [])
         if j.get("node") == hit["id"] and j.get("state") in ("queued", "assigned", "running")]
print(hit["id"])
print(hit.get("name") or hit["id"])
print(workers)
print(len(ahead))
print(json.dumps([j.get("type") for j in ahead]))
