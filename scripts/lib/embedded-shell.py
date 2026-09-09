#!/usr/bin/env python3
"""Extract shell scripts that live inside quoted heredocs, for shellcheck.

`bb lint` builds its shellcheck list from shebangs rather than filenames, so a
new script is covered the moment it exists. A script written INSIDE another one
escapes that: the body of a `<<'TAG'` heredoc is a string to the shell and a
string to shellcheck, and nothing looks in it.

nodes/provision-linux.sh is why this exists. It embeds bb-sandbox — around 280 lines
installed to a root-only path on the sandbox VM — rather than fetching it,
because provisioning is one file you curl onto a fresh machine. Four bugs sat
in there unlinted, including two that could damage an fstab.

Same rule as the outer list, so this stays a property of the content: a heredoc
whose body opens with a shell shebang is a script. Each is written into the
directory named by the first argument, called `<source>-<TAG>`, and its path
printed — the name is what connects a finding back to the file it came from.
"""
import pathlib
import re
import sys

# Only the QUOTED form. An unquoted heredoc is interpolated by the shell, so
# its body is a template rather than a program and `${x}` in it is not
# something shellcheck can judge.
HEREDOC = re.compile(r"<<-?'([A-Za-z_]\w*)'\n(.*?)\n\1\n", re.DOTALL)
SHEBANG = re.compile(r"#!.*\b(ba)?sh\b")


def main(argv):
    if len(argv) < 2:
        return 0
    out = pathlib.Path(argv[0])
    for src in argv[1:]:
        try:
            text = pathlib.Path(src).read_text(errors="ignore")
        except OSError:
            continue
        # Numbered when a name repeats. One file can hold several `<<'EOF'`
        # blocks — the test harness holds four — and without this the second
        # overwrote the first and went unchecked, which is the exact failure
        # this script exists to end.
        seen = {}
        for tag, body in HEREDOC.findall(text):
            if not SHEBANG.match(body.split("\n", 1)[0]):
                continue
            n = seen[tag] = seen.get(tag, 0) + 1
            stem = f"{pathlib.Path(src).name}-{tag}" + (f"-{n}" if n > 1 else "")
            f = out / stem
            try:
                f.write_text(body + "\n", encoding="utf-8")
            except OSError:
                continue
            print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
