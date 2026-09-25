"""Behind `bb token keep` (cmd_token in bb): the session token in BB_TOKEN,
stored where this account's sessions on this machine read it
(bbapi.keep_token), for the agent to run for a session that is idle (R27).

Arguments: the verb, keep. HOME is the account's home on this machine.
"""
import os
import sys

import bbapi

{"keep": lambda: bbapi.keep_token(os.environ["BB_TOKEN"])}[sys.argv[1]]()
