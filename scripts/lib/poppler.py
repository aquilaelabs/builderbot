#!/usr/bin/env python3
"""pdftoppm and pdfinfo, as much of them as Claude Code's own PDF reader
uses, drawn with PyMuPDF (R103).

Claude Code reads a PDF by asking `pdfinfo FILE` for its page count and
`pdftoppm -jpeg -r 100 [-f N] [-l M] FILE PREFIX` for pictures of its pages,
which it collects as PREFIX-*.jpg. No node carries poppler, so a session
could not read a PDF it had fetched (Shebang-DevBoard, 30 Sep). The
documents toolchain installs this under both names, run with its own
Python, which has PyMuPDF.

    poppler.py pdftoppm [-v] [-jpeg|-png] [-r DPI] [-f N] [-l M] FILE PREFIX
    poppler.py pdfinfo FILE

What Claude Code reads back is kept to poppler's own: the pages named
PREFIX-N with N zero-padded to the width of the page count, and the errors
worded as poppler words them (an unopenable file, a password, a page range
past the end, a damaged file), since it matches those lines.
"""
import os
import sys
from typing import NoReturn

VERSION = "24.02.0"


def err(msg, code) -> NoReturn:
    sys.stderr.write(msg + "\n")
    sys.exit(code)


def open_pdf(path):
    import pymupdf
    if not os.path.isfile(path):
        err(f"I/O Error: Couldn't open file '{path}': No such file or directory.", 1)
    try:
        doc = pymupdf.open(path)
    except Exception:                                         # noqa: BLE001
        err("Syntax Error: Couldn't read xref table", 1)
    if doc.needs_pass:
        err("Command Line Error: Incorrect password", 1)
    return doc


def pdftoppm(args):
    if args[:1] in (["-v"], ["-version"], ["--version"]):
        err(f"pdftoppm version {VERSION} (PyMuPDF, installed by BuilderBot's documents toolchain)", 0)
    fmt, dpi, first, last, rest = "ppm", 150, None, None, []
    it = iter(args)
    for a in it:
        if a in ("-jpeg", "-png"):
            fmt = a[1:]
        elif a in ("-r", "-f", "-l"):
            v = next(it, "")
            if not v.isdigit():
                err(f"Command Line Error: {a} takes a number", 99)
            if a == "-r":
                dpi = int(v)
            elif a == "-f":
                first = int(v)
            else:
                last = int(v)
        elif a.startswith("-") and len(a) > 1:
            err(f"Command Line Error: {a} is not an option this pdftoppm has "
                "(BuilderBot's, for -jpeg, -png, -r, -f and -l)", 99)
        else:
            rest.append(a)
    if len(rest) != 2:
        err("Usage: pdftoppm [-jpeg|-png] [-r DPI] [-f N] [-l M] PDF-file PPM-root", 99)
    path, prefix = rest
    doc = open_pdf(path)
    total = doc.page_count
    a = first or 1
    b = min(last, total) if last else total
    if a > b:
        err(f"Wrong page range given: the first page ({a}) can not be after the last page ({b}).", 99)
    width = len(str(total))
    ext = {"jpeg": "jpg", "png": "png", "ppm": "ppm"}[fmt]
    for n in range(a, b + 1):
        pix = doc[n - 1].get_pixmap(dpi=dpi)
        pix.save(f"{prefix}-{n:0{width}d}.{ext}")


def pdfinfo(args):
    if args[:1] in (["-v"], ["--version"]):
        err(f"pdfinfo version {VERSION} (PyMuPDF, installed by BuilderBot's documents toolchain)", 0)
    files = [a for a in args if not a.startswith("-")]
    if len(files) != 1:
        err("Usage: pdfinfo PDF-file", 99)
    doc = open_pdf(files[0])
    meta = doc.metadata or {}
    rows = [("Title", meta.get("title")), ("Author", meta.get("author")), ("Creator", meta.get("creator")),
            ("Producer", meta.get("producer")), ("Pages", str(doc.page_count)),
            ("Encrypted", "yes" if doc.is_encrypted else "no")]
    if doc.page_count:
        r = doc[0].rect
        rows.append(("Page size", f"{r.width:g} x {r.height:g} pts"))
    rows.append(("File size", f"{os.path.getsize(files[0])} bytes"))
    for k, v in rows:
        if v:
            print(f"{k + ':':<16}{v}")


def main(argv):
    if not argv or argv[0] not in ("pdftoppm", "pdfinfo"):
        err("poppler.py pdftoppm|pdfinfo ARGS...", 99)
    (pdftoppm if argv[0] == "pdftoppm" else pdfinfo)(argv[1:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
