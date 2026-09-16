#!/usr/bin/env python3
"""Extract the programs that live inside quoted heredocs, so a linter reads them.

`bb lint` builds its lists from shebangs and extensions, so a new script is
covered the moment it exists. A program written INSIDE another one escapes
that: the body of a `<<'TAG'` heredoc is a string to the shell and a string
to every linter, and nothing looks in it.

Two of those are why this exists. nodes/provision-linux.sh embeds bb-sandbox,
around 280 lines installed to a root-only path on the sandbox VM, rather than
fetching it, because provisioning is one file you curl onto a fresh machine;
four bugs sat in there unlinted, two of which could damage an fstab. And
scripts/bb does most of its reading of the controller's store in python fed
to `python3 -` on stdin: thousands of lines ruff had never seen.

    embedded.py shell  OUTDIR FILE...
        a heredoc whose body opens with a shell shebang, written as
        <source>-<TAG> with the shebang still on line 1, which is how
        shellcheck knows the dialect.

    embedded.py python OUTDIR FILE...
        a heredoc a shell script feeds to python3 on its opening line, written
        as <source>-<TAG>.py behind as many blank lines as sit above it in the
        source, so a finding's line number is the line in the file it came from.

Each file written is printed, one path a line.
"""
import pathlib
import re
import sys

# Only the QUOTED form. An unquoted heredoc is interpolated by the shell, so
# its body is a template rather than a program, and `${x}` in it is not
# something a linter can judge.
SHELL_DOC = re.compile(r"<<-?'([A-Za-z_]\w*)'\n(.*?)\n\1\n", re.DOTALL)
SHEBANG = re.compile(r"#!.*\b(ba)?sh\b")
# Anchored on the line that runs python, so a `<<'X'` quoted inside some
# other program's string cannot start a match that swallows a real heredoc.
# The opening line may carry more after the tag: arguments, a redirect.
PYTHON_DOC = re.compile(r"^[^\n]*\bpython3?\b[^\n]*<<-?'([A-Za-z_]\w*)'[^\n]*\n(.*?)\n\1\n",
                        re.DOTALL | re.MULTILINE)


def is_shell(path, text):
    return path.suffix == ".sh" or bool(SHEBANG.match(text.split("\n", 1)[0]))


def main(argv):
    if len(argv) < 3 or argv[0] not in ("shell", "python"):
        return 0
    kind, out = argv[0], pathlib.Path(argv[1])
    # Numbered when a name repeats, across the whole run: one file can hold
    # several blocks under one tag (scripts/bb feeds python3 from dozens of
    # `<<'PY'`), and a second one overwriting the first would go unchecked,
    # which is the exact failure this script exists to end.
    seen = {}
    for src in argv[2:]:
        path = pathlib.Path(src)
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if kind == "shell":
            found = [(m, m.group(2)) for m in SHELL_DOC.finditer(text)
                     if SHEBANG.match(m.group(2).split("\n", 1)[0])]
        elif is_shell(path, text):
            found = [(m, m.group(2)) for m in PYTHON_DOC.finditer(text)]
        else:
            continue
        for m, body in found:
            stem = f"{path.name}-{m.group(1)}"
            n = seen[stem] = seen.get(stem, 0) + 1
            stem += f"-{n}" if n > 1 else ""
            if kind == "python":
                above = text.count("\n", 0, m.start(2))
                target, content = out / f"{stem}.py", "\n" * above + body + "\n"
            else:
                target, content = out / stem, body + "\n"
            try:
                target.write_text(content, encoding="utf-8")
            except OSError:
                continue
            print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
