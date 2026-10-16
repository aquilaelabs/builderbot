"""BuilderBot's own documentation, read in the dashboard (R258, the operator
16 Oct): the Help page lists the docs, reads one, and searches them all.

The docs are docs/*.md beside scripts/ in this tree, which the image carries
at /opt/builderbot/docs. Which of them are shown, in which groups and with
which line under each, is docs/README.md's: its "## Group" headings and the
"- [name.md](name.md): what it is" lines under them, so the index a reader
on a forge sees is the one the page shows, and a doc not in it (a frozen
changelog) is not offered. README itself is the page Help opens on.

A doc is named by its file's stem and nothing else: a name is checked
against the listed files before it is read, so no path reaches the disk.
"""
import re
from pathlib import Path

DIR = Path(__file__).resolve().parents[2] / "docs"     # the tree's, or /opt/builderbot/docs
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,60}")
SEARCH_MAX = 60


def configure(*, docs=None):
    if docs:
        globals()["DIR"] = Path(docs)


def _text(name):
    try:
        return (DIR / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        return None


def _title(text, name):
    m = re.search(r"^#\s+(.+?)\s*$", text or "", re.M)
    return m.group(1).strip() if m else name


def _index():
    """[{group, docs: [{name, blurb}]}] off README's headings and links."""
    groups, cur = [], None
    for line in (_text("README") or "").splitlines():
        h = re.match(r"^##\s+(.+?)\s*$", line)
        if h:
            cur = {"group": h.group(1), "docs": []}
            groups.append(cur)
            continue
        m = re.match(r"^\s*[-*]\s+\[[^\]]*\]\(([a-z0-9-]+)\.md\)\s*:?\s*(.*)$", line)
        if m and cur is not None and (DIR / f"{m.group(1)}.md").is_file():
            cur["docs"].append({"name": m.group(1), "blurb": m.group(2).strip()})
    return [g for g in groups if g["docs"]]


def _names():
    return ["README"] + [d["name"] for g in _index() for d in g["docs"]]


def listing():
    """The groups with each doc's title: what the page's contents list is."""
    groups = _index()
    for g in groups:
        for d in g["docs"]:
            d["title"] = _title(_text(d["name"]), d["name"])
    readme = _text("README")
    if readme is None:
        return {"error": "the docs are not in this build"}, 404
    return {"home": "README", "title": _title(readme, "Documentation"), "groups": groups}, 200


def read(name):
    """One doc by its stem: {name, title, text}."""
    name = str(name or "")
    if name != "README" and not NAME.fullmatch(name):
        return {"error": "no such doc"}, 404
    if name not in _names():
        return {"error": f"no doc called {name}"}, 404
    text = _text(name)
    if text is None:
        return {"error": f"{name} could not be read"}, 404
    return {"name": name, "title": _title(text, name), "text": text}, 200


def _slug(t):
    """A heading's anchor, as the page's wikiSlug makes it."""
    return "wk-" + re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def search(q):
    """Every line of every listed doc that holds all the words of `q`, with
    the heading it sits under, so a result opens the doc at that section.
    A heading that matches comes first in its doc; at most SEARCH_MAX."""
    words = [w for w in re.split(r"\s+", str(q or "").strip().lower()) if w]
    if not words or len(" ".join(words)) < 2:
        return {"q": q, "results": []}, 200
    out, names = [], _names()
    for name in names:
        text = _text(name) or ""
        title = _title(text, name)
        heading, fence = "", False
        for line in text.splitlines():
            if line.lstrip().startswith("```"):
                fence = not fence
                continue
            h = None if fence else re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line)
            if h:
                heading = re.sub(r"[*_`]", "", h.group(2))
            if not line.strip():
                continue
            # Matched as it reads, not as it is written: a word only in a
            # link's address is not on the page. A table's row reads as its
            # cells, not its bars.
            plain = re.sub(r"[*_`]|\]\([^)]*\)|[\[\]]", "", line.strip())
            plain = re.sub(r"\s*\|\s*", " · ", plain).strip(" ·")
            low = plain.lower()
            if not all(w in low for w in words):
                continue
            # A long line is shown around its first match.
            at = min(low.find(w) for w in words)
            cut = plain if len(plain) <= 240 else ("…" if at > 120 else "") + plain[max(0, at - 120) if at > 120 else 0:][:240]
            out.append({"doc": name, "title": title, "heading": heading if not h or len(h.group(1)) > 1 else "",
                        "anchor": _slug(heading) if heading and (not h or len(h.group(1)) > 1) else "",
                        "text": cut, "head": bool(h)})
    out.sort(key=lambda r: (names.index(r["doc"]), not r["head"]))
    return {"q": q, "results": out[:SEARCH_MAX], "more": max(0, len(out) - SEARCH_MAX)}, 200
