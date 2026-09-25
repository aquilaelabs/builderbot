"""Behind `bb logs --node NAME [--agent|--runner|--terminal]` (cmd_logs in bb): a
MACHINE's own log, read through the controller, which decides whether the
asking session may see it.

BB_LOG_AUTH is the auth header, BB_LOG_NODE the node, BB_LOG_STREAM which of
its logs, and BB_LOG_LINES how many lines.
"""
import os
import sys

import bbapi


d = bbapi.call("/api/nodelog",
               {"node": os.environ["BB_LOG_NODE"],
                "stream": os.environ["BB_LOG_STREAM"],
                "lines": int(os.environ["BB_LOG_LINES"])},
               auth=os.environ["BB_LOG_AUTH"], timeout=180)
if d.get("error"):
    sys.exit(f"[builderbot] ERROR: {d['error']}")
sys.stdout.write(d.get("out") or "")
if d.get("state") and d["state"] != "succeeded":
    sys.exit(f"[builderbot] ERROR: the read {d['state']} on the node")
