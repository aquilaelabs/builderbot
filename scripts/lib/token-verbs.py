"""Behind `bb token keep` (cmd_token in bb): the session token in BB_TOKEN,
stored where this account's sessions on this machine read it
(bbapi.keep_token), for the agent to run for a session that is idle (R27).

Arguments: the verb, keep. HOME is the account's home on this machine.
"""
import os
import sys

import bbapi

if sys.argv[1:] != ["keep"]:
    sys.exit("usage: token-verbs.py keep")
# Said and failed when it was not kept: the agent logs what this prints, and
# a keep that wrote nothing used to exit 0, so an idle session's token ran
# out with nothing anywhere saying why (B419).
why = bbapi.keep_token(os.environ["BB_TOKEN"])
if why:
    sys.exit(f"[builderbot] ERROR: the session token was not kept under {os.environ.get('HOME', '?')}: {why}")
