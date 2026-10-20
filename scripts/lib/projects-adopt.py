"""Behind `bb projects adopt FOLDER [--name NAME]` (cmd_projects in bb): a
folder already under the projects share recorded as a project (R84), under
its shown name, as a project BuilderBot made is. Refused for a folder that
is not there, or that the registry already knows (live, trashed or deleted
for good: a directory is never handed out twice).

The argument is the dashboard directory; BB_ADOPT_DIR and BB_ADOPT_NAME are
the folder and the name, DASHBOARD_STATE and WORKSPACE say where.
"""
import json
import os
import re
import sys

sys.path.insert(0, sys.argv[1])
import registry  # noqa: E402


def write_json(path, data):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


ws = os.environ.get("WORKSPACE", "/workspace")
folder, name = os.environ["BB_ADOPT_DIR"].strip().strip("/"), os.environ.get("BB_ADOPT_NAME", "").strip()
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", folder):
    sys.exit(f"[builderbot] ERROR: {folder!r} is not a folder name under {ws}")
if not os.path.isdir(os.path.join(ws, folder)):
    sys.exit(f"[builderbot] ERROR: there is no folder {ws}/{folder}")
registry.configure(state=os.environ.get("DASHBOARD_STATE", "/config"), workspace=ws, write_json=write_json)
if registry.get(folder):
    sys.exit(f"[builderbot] ERROR: {folder} is a project already, or was one: the registry never hands a folder out twice")
r = registry.claim(folder, name or folder)
print(f"{folder} is a project, shown as {r['name']} (P{r['id']})")
