#!/usr/bin/env python3
"""Behind `bb tool docs` (tool_docs in bb): a document a session can read.

    docs.py read FILE...                   Markdown on stdout, one file after another
    docs.py pages FILE [--pages A-B] [--dpi N] [--out DIR]
                                           a picture of each page, for layout,
                                           charts and scans

Run with the documents toolchain's own Python (its venv), which carries
markitdown and PyMuPDF. `read` is markitdown: a PDF, a Word document, a
slide deck, a spreadsheet, and HTML, EPUB and plain text beside them.
`pages` draws a PDF's pages with PyMuPDF; anything else is made a PDF first
by LibreOffice (BB_DOCS_SOFFICE, the office toolchain's), with a profile of
its own for the run so two runs do not trip over one. Pages land in
dist/docs/NAME/ by default, where the Artifacts view lists them.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import NoReturn

MAX_PAGES = 20          # drawn when no --pages is given: a long PDF is read, not looked at


def die(msg) -> NoReturn:
    sys.stderr.write(f"[builderbot] ERROR: {msg}\n")
    sys.exit(1)


def say(msg):
    sys.stderr.write(f"[builderbot] {msg}\n")


def read(files):
    if not files:
        die("bb tool docs read FILE...: a PDF, .docx, .pptx, .xlsx, .xls, .html, .epub or text")
    from markitdown import MarkItDown
    md = MarkItDown(enable_plugins=False)
    for i, f in enumerate(files):
        if not os.path.isfile(f):
            die(f"no such file: {f}")
        try:
            text = md.convert(f).text_content or ""
        except Exception as e:                                  # noqa: BLE001
            die(f"{f}: markitdown could not read it: {type(e).__name__}: {str(e)[:200]}")
        if len(files) > 1:
            print(f"{'' if i == 0 else chr(10)}<!-- {f} -->")
        print(text.strip())
        if not text.strip():
            say(f"{f}: no text in it; a scan or a picture of text has none, and bb tool docs pages {f} draws it to look at")


def span(s, total):
    """--pages A-B, A or A-, 1-based, as (first, last) within the document."""
    m = re.fullmatch(r"(\d+)(?:-(\d*))?", s or "")
    if not m:
        die("--pages takes N, N-M or N-: page numbers from 1")
    a = int(m.group(1))
    b = total if m.group(2) == "" else int(m.group(2) or a)
    if a < 1 or b < a:
        die(f"--pages {s}: from 1, and the first no later than the last")
    if a > total:
        die(f"--pages {s}: it has {total} page{'s' if total != 1 else ''}")
    return a, min(b, total)


def as_pdf(f, work):
    """The file as a PDF: itself, or LibreOffice's rendering of it."""
    if f.lower().endswith(".pdf"):
        return f
    so = os.environ.get("BB_DOCS_SOFFICE") or ""
    if not (so and os.access(so, os.X_OK)):
        die(f"{f} is not a PDF, and its pages are drawn from one: LibreOffice makes it, which is the office "
            "toolchain; install it on the Toolchains page with this node picked (bb tool docs read gives its text now)")
    prof = os.path.join(work, "profile")
    r = subprocess.run([so, f"-env:UserInstallation=file://{prof}", "--headless", "--norestore",
                        "--convert-to", "pdf", "--outdir", work, f],
                       capture_output=True, text=True, timeout=300, check=False,
                       env=dict(os.environ, HOME=work))
    out = os.path.join(work, os.path.splitext(os.path.basename(f))[0] + ".pdf")
    if r.returncode or not os.path.isfile(out):
        die(f"LibreOffice could not make a PDF of {f}: {(r.stderr or r.stdout).strip()[-300:]}")
    return out


def pages(args):
    f, rng, dpi, out = None, None, 110, None
    while args:
        a = args.pop(0)
        if a in ("--pages", "--dpi", "--out") and args:
            v = args.pop(0)
            if a == "--pages":
                rng = v
            elif a == "--dpi":
                if not v.isdigit() or not 30 <= int(v) <= 300:
                    die("--dpi takes a number from 30 to 300")
                dpi = int(v)
            else:
                out = v
        elif a.startswith("-"):
            die(f"unknown option: {a}")
        elif f is None:
            f = a
        else:
            die("bb tool docs pages takes one FILE")
    if not f:
        die("bb tool docs pages FILE [--pages N-M] [--dpi N] [--out DIR]")
    if not os.path.isfile(f):
        die(f"no such file: {f}")
    import pymupdf
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.splitext(os.path.basename(f))[0]).strip("-") or "doc"
    out = out or os.path.join("dist", "docs", stem)
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="bb-docs-")
    try:
        doc = pymupdf.open(as_pdf(f, work))
        total = doc.page_count
        if not total:
            die(f"{f} has no pages")
        a, b = span(rng, total) if rng else (1, min(total, MAX_PAGES))
        for n in range(a, b + 1):
            path = os.path.join(out, f"page-{n:03d}.png")
            doc[n - 1].get_pixmap(dpi=dpi).save(path)
            print(path)
        say(f"{b - a + 1} of {total} page{'s' if total != 1 else ''} drawn into {out}"
            + (f"; --pages {b + 1}- draws the rest" if not rng and b < total else ""))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__ or "")
        return 0 if argv else 1
    if argv[0] == "read":
        read(argv[1:])
    elif argv[0] == "pages":
        pages(list(argv[1:]))
    else:
        die("bb tool docs read FILE... | pages FILE [--pages N-M] [--dpi N] [--out DIR]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
