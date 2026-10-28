"""Behind `bb router-key` (R144): the model router's address, this project's
own key and the models it offers, for an Any model session at its start
(bb-tty's launcher writes OpenCode's config from it). Prints the JSON the
controller answers, {} where no router allows the project.

BB_RK_AUTH is the auth header, BB_RK_PROJECT the project.
"""
import json
import os
import sys
import urllib.parse

import bbapi

proj = os.environ.get("BB_RK_PROJECT", "")
if not proj:
    sys.exit("[builderbot] ERROR: no project: run it inside one, or set BB_PROJECT")
d = bbapi.call("/api/router-key?project=" + urllib.parse.quote(proj), auth=os.environ["BB_RK_AUTH"], timeout=20)
print(json.dumps(d))
