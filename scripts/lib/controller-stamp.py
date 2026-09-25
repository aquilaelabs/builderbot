"""Behind the build line of `bb status` on a node (bb_controller_stamp in bb):
which image the controller is on, asked over /api/meta, said softly. A
session is always on a node, where BB_IMAGE_REV and BB_VERSION are empty, and
the which-build rule sends it to bb status to learn the build, so this has to
work there. A controller that is down, or a session with no token, is a
state the line reports rather than dies on.

BB_META_AUTH is the auth header. The line is printed with no newline, for bb
to put in its sentence.
"""
import os

import bbapi


# request() rather than call(), because the two failures want different
# answers and call() cannot tell them apart: a refusal the server worded and a
# refused connection both come back as {"error": sentence}. Reporting an
# expired token as "the controller is down" is the mistake bb-gate already
# made once, and the first version of this line made it again.
# Short timeout: bb status is run often, and a controller that is down should
# cost a line rather than a 30-second wait.
try:
    st, m = bbapi.request("/api/meta", auth=os.environ["BB_META_AUTH"], timeout=5)
except Exception:
    st, m = None, {}
if st is None:
    print("unreachable: the controller did not answer", end="")
    raise SystemExit(0)
if st >= 400 or not isinstance(m, dict) or m.get("error"):
    why = (m or {}).get("error") or f"HTTP {st}"
    print(f"the controller refused this session: {why}", end="")
    raise SystemExit(0)
ver = (m.get("version") or "").strip()
rev = (m.get("image") or "").strip()
built = (m.get("built") or "").strip()
if not ver and not rev:
    print("unstamped: the controller's image was built outside CI", end="")
else:
    out = ver or rev[:7]
    if rev and rev[:7] not in out:
        out += f" ({rev[:7]})"
    if built:
        out += f" (built {built})"
    print(out, end="")
