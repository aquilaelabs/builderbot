"""The markup languages BuilderBot reads and writes, in the standard library
alone (R167): JSON, TOML and XML through python's own modules, YAML as the
subset anything here writes (block mappings and sequences, scalars, quoted
strings, `|` text blocks), and Markdown by its headings. One reader for the
notebook's records coming back in (records.py) and for the code map, which
indexes a setting or a key where a file defines it (codemap.py), so a
session asks `bb map find DASHBOARD_PORT` rather than grepping five files.

What is not here: YAML anchors, tags, flow style past a one-line `[a, b]`
or `{}` and multi-document streams. A file that uses them is read as far
as it goes and `yaml_load` says so in its error, which the code map takes as
a file with no keys rather than a crash.
"""
import json
import re
import tomllib
import xml.etree.ElementTree as ET


class MarkupError(ValueError):
    pass


# ---- YAML, the subset ---------------------------------------------------------

_YAML_BOOL = {"true": True, "false": False, "yes": True, "no": False, "on": True, "off": False}


def _yaml_scalar(s):
    """One scalar as YAML reads it: quoted strings as written, numbers,
    booleans, null, else the words."""
    s = s.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if s[0] in "\"'" and s[-1] == s[0] and len(s) >= 2:
        if s[0] == '"':
            try:
                return json.loads(s)
            except ValueError:
                return s[1:-1]
        return s[1:-1].replace("''", "'")
    if s.lower() in _YAML_BOOL and s.lower() in ("true", "false"):
        return _YAML_BOOL[s.lower()]
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [] if not inner else [_yaml_scalar(x) for x in _split_flow(inner)]
    if s.startswith("{") and s.endswith("}"):
        inner = s[1:-1].strip()
        out = {}
        for part in _split_flow(inner) if inner else []:
            k, _, v = part.partition(":")
            out[_yaml_scalar(k)] = _yaml_scalar(v)
        return out
    return s


def _split_flow(s):
    """`a, "b, c", d` at the commas outside quotes."""
    out, cur, q = [], "", ""
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = ""
        elif ch in "\"'":
            q = ch; cur += ch
        elif ch == ",":
            out.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [x.strip() for x in out]


def _strip_comment(line):
    """The line without a trailing ` # comment`, quotes respected."""
    q = ""
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = ""
        elif ch in "\"'":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def yaml_load(text, keys_only=False):
    """The document as python: a dict or a list, or a scalar. `keys_only`
    also returns a list of (key path, line) for every mapping key met, which
    is what the code map indexes."""
    lines = text.splitlines()
    keys = []

    def block(i, indent):
        """The node starting at line i whose lines are indented `indent`
        or deeper; returns (value, next line index)."""
        # Skip blanks and comments to the first real line.
        while i < len(lines) and not _strip_comment(lines[i]).strip():
            i += 1
        if i >= len(lines):
            return None, i
        raw = lines[i]
        ind = len(raw) - len(raw.lstrip(" "))
        if ind < indent:
            return None, i
        body = _strip_comment(raw).strip()
        if body.startswith("- ") or body == "-":
            return seq(i, ind)
        return mapping(i, ind)

    def seq(i, ind, path=()):
        out = []
        while i < len(lines):
            raw = lines[i]
            body = _strip_comment(raw).strip()
            if not body:
                i += 1; continue
            cur = len(raw) - len(raw.lstrip(" "))
            if cur < ind or not (body.startswith("- ") or body == "-"):
                break
            if cur > ind:
                raise MarkupError(f"line {i + 1}: a sequence item deeper than its list")
            item = body[2:].strip() if body != "-" else ""
            if not item:
                v, i = block(i + 1, ind + 1)
                out.append(v)
            elif ":" in item and not item[0] in "\"'[{" and re.match(r"^[^\s:]+\s*:(\s|$)", item):
                # `- key: value` opens a mapping inline on the dash's line.
                lines[i] = " " * (ind + 2) + item
                v, i = mapping(i, ind + 2, path)
                out.append(v)
            elif item in ("|", "|-", "|+", ">", ">-"):
                v, i = text_block(i + 1, ind + 2, fold=item.startswith(">"), keep=item.endswith("+"), chomp=item.endswith("-"))
                out.append(v)
            else:
                out.append(_yaml_scalar(item)); i += 1
        return out, i

    def mapping(i, ind, path=()):
        out = {}
        while i < len(lines):
            raw = lines[i]
            body = _strip_comment(raw).strip()
            if not body:
                i += 1; continue
            cur = len(raw) - len(raw.lstrip(" "))
            if cur < ind:
                break
            if cur > ind:
                raise MarkupError(f"line {i + 1}: indented under nothing")
            if body.startswith("- "):
                break
            m = re.match(r"^(\"[^\"]*\"|'[^']*'|[^\s:][^:]*?)\s*:(?:\s+(.*))?$", body)
            if not m:
                raise MarkupError(f"line {i + 1}: not `key: value`: {body!r}")
            key = _yaml_scalar(m.group(1))
            keys.append(("/".join([*path, str(key)]), i + 1))
            rest = (m.group(2) or "").strip()
            if rest in ("|", "|-", "|+", ">", ">-"):
                v, i = text_block(i + 1, ind + 1, fold=rest.startswith(">"), keep=rest.endswith("+"), chomp=rest.endswith("-"))
            elif rest:
                v = _yaml_scalar(rest); i += 1
            else:
                nxt, j = i + 1, i + 1
                while j < len(lines) and not _strip_comment(lines[j]).strip():
                    j += 1
                if j < len(lines):
                    nraw = lines[j]
                    nind = len(nraw) - len(nraw.lstrip(" "))
                    nbody = _strip_comment(nraw).strip()
                    if nind > ind or (nind == ind and nbody.startswith("- ")):
                        if nbody.startswith("- ") or nbody == "-":
                            v, i = seq(j, nind, (*path, str(key)))
                        else:
                            v, i = mapping(j, nind, (*path, str(key)))
                    else:
                        v, i = None, nxt
                else:
                    v, i = None, nxt
            out[key] = v
        return out, i

    def text_block(i, ind, fold=False, keep=False, chomp=False):
        got, base = [], None
        while i < len(lines):
            raw = lines[i]
            if not raw.strip():
                got.append(""); i += 1; continue
            cur = len(raw) - len(raw.lstrip(" "))
            if base is None:
                if cur < ind:
                    break
                base = cur
            if cur < base:
                break
            got.append(raw[base:]); i += 1
        while got and got[-1] == "" and not keep:
            got.pop()
        s = (" ".join(x for x in got) if fold else "\n".join(got))
        return (s if chomp else s + ("\n" if got and not fold else "")), i

    v, i = block(0, 0)
    while i < len(lines):
        if _strip_comment(lines[i]).strip():
            raise MarkupError(f"line {i + 1}: more than one document, or a line indented under nothing")
        i += 1
    return (v, keys) if keys_only else v


def _yaml_str(s):
    """A string as YAML writes it: plain where it reads back as itself,
    quoted otherwise."""
    if s == "" or s.strip() != s or s.lower() in _YAML_BOOL or s.lower() in ("null", "~") \
            or re.fullmatch(r"-?\d+(\.\d+)?", s) or s[0] in "\"'[{&*!|>%@`#-?:," or ": " in s or " #" in s \
            or s.endswith(":") or "\n" in s or any(ord(c) < 32 for c in s):
        return json.dumps(s, ensure_ascii=False)
    return s


def yaml_dump(value, indent=0):
    """The value as YAML, block style, a text with newlines as a `|` block."""
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        out = []
        for k, v in value.items():
            key = _yaml_str(str(k))
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{key}:\n{yaml_dump(v, indent + 2)}")
            elif isinstance(v, str) and "\n" in v:
                body = "".join(f"{pad}  {ln}\n" if ln else "\n" for ln in v.rstrip("\n").split("\n"))
                out.append(f"{pad}{key}: {'|' if v.endswith(chr(10)) else '|-'}\n{body}")
            else:
                out.append(f"{pad}{key}: {yaml_dump(v).strip()}\n")
        return "".join(out)
    if isinstance(value, list):
        if not value:
            return pad + "[]\n"
        out = []
        for v in value:
            if isinstance(v, dict) and v:
                inner = yaml_dump(v, indent + 2)
                out.append(f"{pad}- {inner[indent + 2:]}")
            elif isinstance(v, (dict, list)):
                out.append(f"{pad}-\n{yaml_dump(v, indent + 2)}")
            elif isinstance(v, str) and "\n" in v:
                body = "".join(f"{pad}  {ln}\n" if ln else "\n" for ln in v.rstrip("\n").split("\n"))
                out.append(f"{pad}- {'|' if v.endswith(chr(10)) else '|-'}\n{body}")
            else:
                out.append(f"{pad}- {yaml_dump(v).strip()}\n")
        return "".join(out)
    if value is None:
        return pad + "null\n"
    if isinstance(value, bool):
        return pad + ("true" if value else "false") + "\n"
    if isinstance(value, (int, float)):
        return pad + str(value) + "\n"
    return pad + _yaml_str(str(value)) + "\n"


# ---- Markdown, by its headings ----------------------------------------------

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")


def md_headings(text):
    """[(level, title, line)] for every ATX heading, fenced code skipped."""
    out, fence = [], None
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if fence:
            if s.startswith(fence):
                fence = None
            continue
        if s.startswith("```") or s.startswith("~~~"):
            fence = s[:3]; continue
        m = _HEADING.match(line)
        if m:
            out.append((len(m.group(1)), m.group(2), n))
    return out


def md_sections(text):
    """The text cut at its headings: [(level, title, line, body)], the body
    the lines under a heading up to the next one of any level."""
    heads = md_headings(text)
    lines = text.splitlines()
    out = []
    for i, (lvl, title, ln) in enumerate(heads):
        end = heads[i + 1][2] - 1 if i + 1 < len(heads) else len(lines)
        out.append((lvl, title, ln, "\n".join(lines[ln:end]).strip("\n")))
    return out


# ---- keys, for the code map ----------------------------------------------------

def _json_keys(text):
    """(key path, line) for every key of a JSON document, read by position:
    json gives no lines, so the keys are found again in the text."""
    doc = json.loads(text)
    keys, seen = [], {}
    lines = text.splitlines()

    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                keys.append(("/".join([*path, str(k)]), _line_of(lines, json.dumps(k), seen)))
                walk(x, [*path, str(k)])
        elif isinstance(v, list):
            for x in v:
                walk(x, path)
    walk(doc, [])
    return keys


def _line_of(lines, needle, seen):
    start = seen.get(needle, 0)
    for n in range(start, len(lines)):
        if needle + ":" in lines[n] or needle + " :" in lines[n]:
            seen[needle] = n + 1
            return n + 1
    return 0


def _toml_keys(text):
    tomllib.loads(text)        # a bad file is an error, as the others are
    keys, table = [], ""
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            table = s.strip("[]").strip()
        elif re.match(r"^[A-Za-z0-9_.\"'-]+\s*=", s):
            k = re.split(r"\s*=", s, maxsplit=1)[0].strip().strip("\"'")
            keys.append((f"{table}/{k}" if table else k, n))
    return keys


def _xml_keys(text):
    """Every element with a Name or Target attribute, and every Config's
    Target (the Unraid template's settings), with its line."""
    ET.fromstring(text)
    keys = []
    for n, line in enumerate(text.splitlines(), 1):
        for m in re.finditer(r"<\w+\b[^>]*>", line):
            tag = m.group(0)
            t = re.search(r"\bTarget=\"([^\"]+)\"", tag) or re.search(r"\bName=\"([^\"]+)\"", tag)
            if t:
                keys.append((t.group(1), n))
    return keys


def _env_keys(text):
    keys = []
    for n, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m:
            keys.append((m.group(1), n))
    return keys


KINDS = {".json": "json", ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".xml": "xml",
         ".md": "markdown", ".env": "env", ".example": "env"}


def keys_of(text, suffix):
    """(key path, line) for a file of this suffix, or [] for one this does
    not read; a file that does not parse raises MarkupError."""
    kind = KINDS.get(suffix)
    try:
        if kind == "json":
            return _json_keys(text)
        if kind == "yaml":
            _, keys = yaml_load(text, keys_only=True)
            return keys
        if kind == "toml":
            return _toml_keys(text)
        if kind == "xml":
            return _xml_keys(text)
        if kind == "env":
            return _env_keys(text)
        if kind == "markdown":
            return [(title, ln) for _, title, ln in md_headings(text)]
    except (ValueError, ET.ParseError) as e:
        raise MarkupError(str(e)) from e
    return []


def load(text, kind=None):
    """The document as python, its kind told or guessed from its first
    character (`{`/`[` JSON, `#` Markdown's headings as sections, else YAML)."""
    if kind is None:
        head = text.lstrip()[:1]
        kind = "json" if head in "{[" else "markdown" if head == "#" else "yaml"
    if kind == "json":
        return json.loads(text)
    if kind == "toml":
        return tomllib.loads(text)
    if kind == "markdown":
        return md_sections(text)
    return yaml_load(text)
