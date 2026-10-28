"""The notebook's records, whole, in the form a tool wants (R167): one
serializer for every kind (a roadmap item with its steps and details, a bug,
a rule, a wiki page, a design page, a map entry), writing JSON, YAML or
Markdown, and reading each back in. A document is

    {"format": 1, "kind": "roadmap", "project": NAME, "as_of": REV, "records": [...]}

its `format` moving when the shape does, so a reader can tell; `as_of` is
the list's revision when it was printed, which `bb roadmap apply` checks
before writing an edited record back. The text form each verb prints today
is not here: that stays each verb's own, and `--format text` is it.

Stdlib only, through markup.py beside bb's library, which the code map
reads data files with too.
"""
import json
import os
import re
import sys

_lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib")
if os.path.isdir(_lib) and _lib not in sys.path:
    sys.path.insert(0, _lib)
import markup  # noqa: E402

FORMAT = 1
FORMATS = ("json", "yaml", "markdown", "text")
# What each kind's records are called in Markdown, and the field that is
# the record's heading.
KINDS = {"roadmap": ("R", "text"), "bugs": ("B", "title"), "rules": ("", "name"),
         "wiki": ("", "name"), "design": ("", "name"), "map": ("", "name")}


def document(kind, records, project="", as_of=None):
    return {"format": FORMAT, "kind": kind, **({"project": project} if project else {}),
            **({"as_of": as_of} if as_of is not None else {}), "records": list(records)}


def dump(doc, fmt):
    """The document as text in `fmt` (json, yaml or markdown)."""
    if fmt == "json":
        return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if fmt == "yaml":
        return markup.yaml_dump(doc)
    if fmt == "markdown":
        return _md_dump(doc)
    raise ValueError(f"not a format: {fmt}; json, yaml or markdown")


def load(text, fmt=None):
    """A document back from text, its format told or guessed; a bare list of
    records or one record alone is taken as a document of them."""
    head = text.lstrip()[:1]
    if fmt is None:
        fmt = "json" if head in "{[" else "markdown" if head == "#" else "yaml"
    if fmt == "markdown":
        return _md_load(text)
    doc = json.loads(text) if fmt == "json" else markup.yaml_load(text)
    if isinstance(doc, list):
        doc = {"format": FORMAT, "records": doc}
    elif isinstance(doc, dict) and "records" not in doc:
        doc = {"format": FORMAT, "records": [doc]}
    if not isinstance(doc, dict) or not isinstance(doc.get("records"), list):
        raise ValueError("not a document of records: a list, or {records: [...]}")
    if int(doc.get("format") or FORMAT) > FORMAT:
        raise ValueError(f"format {doc.get('format')} is newer than this build reads ({FORMAT})")
    return doc


# ---- Markdown ---------------------------------------------------------------
# One heading per record, its id and title; the plain fields as a list of
# `- key: value`; the long ones (details, repro, the page's text) as a
# paragraph under a `key:` line; a roadmap's steps as a numbered list, each
# step's own fields indented under it.

_LONG = {"roadmap": ("info",), "bugs": ("repro", "expected", "actual", "notes", "status_note"),
         "rules": ("text",), "wiki": ("text",), "design": ("text",), "map": ()}
_SKIP = {"roadmap": ("steps", "text", "id"), "bugs": ("title", "id"), "rules": ("name",),
         "wiki": ("name",), "design": ("name",), "map": ("name",)}


def _md_dump(doc):
    kind = doc.get("kind") or "records"
    tag, head = KINDS.get(kind, ("", "text"))
    out = [f"# {kind}" + (f" of {doc['project']}" if doc.get("project") else "") + f" (format {doc.get('format', FORMAT)}"
           + (f", as of {doc['as_of']}" if doc.get("as_of") is not None else "") + ")", ""]
    for r in doc.get("records") or []:
        rid = r.get("id")
        title = str(r.get(head) or r.get("text") or r.get("title") or r.get("name") or "")
        first, _, rest = title.partition("\n")
        out.append(f"## {tag}{rid} {first}" if rid is not None else f"## {first}")
        if rest.strip():
            out.append(""); out.append(rest.strip())
        out.append("")
        for k, v in r.items():
            if k in _SKIP.get(kind, ()) or k in _LONG.get(kind, ()) or v in (None, "", [], {}) or k == "steps":
                continue
            out.append(f"- {k}: {_md_scalar(v)}")
        for k in _LONG.get(kind, ()):
            if r.get(k):
                out.append(""); out.append(f"{k}:"); out.append(""); out.append(_md_para(str(r[k])))
        if kind == "roadmap" and r.get("steps"):
            out.append("")
            for i, st in enumerate(r["steps"], 1):
                out.append(f"{i}. {_md_para(str(st.get('text') or ''), indent=3).lstrip()}")
                for k, v in st.items():
                    if k in ("text", "info") or v in (None, "", [], {}):
                        continue
                    out.append(f"   - {k}: {_md_scalar(v)}")
                if st.get("info"):
                    out.append("   - info:"); out.append(""); out.append(_md_para(str(st["info"]), indent=5)); out.append("")
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def _md_scalar(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v).replace("\n", " ")


def _md_para(text, indent=0):
    pad = " " * indent
    return "\n".join((pad + ln) if ln.strip() else "" for ln in text.rstrip("\n").split("\n"))


_MD_HEAD = re.compile(r"^#\s+(\w+)(?: of (\S+))?\s*\(format (\d+)(?:, as of (\S+))?\)\s*$")
_MD_REC = re.compile(r"^##\s+(?:([RB])(\d+)\s+)?(.*)$")
_MD_FIELD = re.compile(r"^- ([a-z_]+):\s*(.*)$")
_MD_STEP = re.compile(r"^(\d+)\.\s+(.*)$")
_MD_STEP_FIELD = re.compile(r"^   - ([a-z_]+):\s*(.*)$")


def _md_value(s):
    s = s.strip()
    if s[:1] in "[{":
        try:
            return json.loads(s)
        except ValueError:
            return s
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if s in ("true", "false"):
        return s == "true"
    return s


def _md_load(text):
    doc = {"format": FORMAT, "records": []}
    cur, long_key, long_lines, step, step_long = None, None, [], None, []
    tag_of = {"R": "roadmap", "B": "bugs"}

    def flush_long():
        nonlocal long_key, long_lines
        if cur is not None and long_key:
            target = step if step is not None and long_key == "info" and step_long is not None else cur
            target[long_key] = "\n".join(long_lines).strip("\n")
        long_key, long_lines = None, []

    for line in text.splitlines():
        m = _MD_HEAD.match(line)
        if m and cur is None and not doc["records"]:
            doc["kind"] = m.group(1)
            if m.group(2):
                doc["project"] = m.group(2)
            doc["format"] = int(m.group(3))
            if m.group(4):
                doc["as_of"] = _md_value(m.group(4))
            continue
        m = _MD_REC.match(line)
        if m:
            flush_long()
            kind = doc.get("kind") or tag_of.get(m.group(1) or "", "records")
            doc.setdefault("kind", kind)
            _, head = KINDS.get(kind, ("", "text"))
            cur = {head: m.group(3).strip()}
            if m.group(2):
                cur["id"] = int(m.group(2))
            doc["records"].append(cur); step = None
            continue
        if cur is None:
            continue
        if doc.get("kind") == "roadmap":
            m = _MD_STEP.match(line)
            if m:
                flush_long()
                step = {"text": m.group(2).strip()}
                cur.setdefault("steps", []).append(step); step_long = None
                continue
            m = _MD_STEP_FIELD.match(line) if step is not None else None
            if m:
                flush_long()
                if m.group(1) == "info" and not m.group(2).strip():
                    long_key, long_lines, step_long = "info", [], True
                else:
                    step[m.group(1)] = _md_value(m.group(2))
                continue
        m = _MD_FIELD.match(line)
        if m and long_key is None:
            cur[m.group(1)] = _md_value(m.group(2)); step = None
            continue
        m = re.match(r"^([a-z_]+):\s*$", line)
        if m and step is None:
            flush_long()
            long_key, long_lines, step_long = m.group(1), [], None
            continue
        if long_key is not None:
            long_lines.append(line[5:] if step_long and line.startswith("     ") else line)
        elif step is not None and not line.startswith("   - "):
            # A step's further lines and paragraphs, written three in.
            step["text"] = step["text"] + "\n" + (line[3:] if line.startswith("   ") else line.strip())
        elif line.strip() and step is None and (KINDS.get(doc.get("kind"), ("", "text"))[1] in cur):
            # Words under the heading before any field: the title's rest.
            head = KINDS.get(doc.get("kind"), ("", "text"))[1]
            cur[head] = (cur[head] + "\n" + line).strip()
    flush_long()
    for r in doc["records"]:
        for st in r.get("steps") or []:
            st["text"] = st["text"].strip("\n")
    return doc


# ---- what each verb hands over ------------------------------------------------

def apply_plan(doc, rows):
    """What `bb roadmap apply` would change, record by record, against the
    rows as they stand: [(id, field, step index or None, new value)], and
    the steps to add as (id, text). Nothing is ever removed by an apply."""
    changes, adds = [], []
    by_id = {int(r["id"]): r for r in rows if r.get("id") is not None}
    for rec in doc.get("records") or []:
        rid = rec.get("id")
        row = by_id.get(int(rid)) if rid is not None else None
        if row is None:
            raise ValueError(f"no open item R{rid} to apply to" if rid is not None else "a record with no id: bb roadmap add --from adds new ones")
        for k in ("text", "info", "target"):
            if k in rec and (rec.get(k) or "") != (row.get(k) or ""):
                changes.append((row["id"], k, None, rec.get(k) or ""))
        have = {tuple(st["sid"]): i for i, st in enumerate(row.get("steps") or []) if isinstance(st.get("sid"), list)}
        for st in rec.get("steps") or []:
            sid = tuple(st["sid"]) if isinstance(st.get("sid"), list) and len(st["sid"]) == 2 else None
            if sid is None or sid not in have:
                if st.get("text"):
                    adds.append((row["id"], st["text"]))
                continue
            i = have[sid]
            old = row["steps"][i]
            for k in ("text", "info", "target"):
                if k in st and (st.get(k) or "") != (old.get(k) or ""):
                    changes.append((row["id"], k, i, st.get(k) or ""))
    return changes, adds
