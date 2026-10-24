"""bb-tty reads a node's grant at its top level, before most of its
functions are defined (B329): a function called there that the file defines
further down is 'command not found' and the terminal ends before it starts.
This holds the grant's block to the functions defined above it."""
import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "bb-tty")


class GrantBlock(unittest.TestCase):
    def test_the_grant_block_calls_nothing_defined_below_it(self):
        with open(SRC, encoding="utf-8") as f:
            lines = f.read().split("\n")
        start = next(i for i, l in enumerate(lines) if l.startswith('if on_node && [ -n "${grant:-}" ]; then'))
        end = next(i for i in range(start + 1, len(lines)) if lines[i] == "fi")
        defined = {m.group(1): i for i, l in enumerate(lines) if (m := re.match(r"^([a-z_][a-z0-9_]*)\(\) \{", l))}
        later = {n for n, i in defined.items() if i > end}
        body = "\n".join(l for l in lines[start:end] if not l.lstrip().startswith("#"))
        called = {n for n in later if re.search(rf"(^|[\s$(;|&]){re.escape(n)}(\s|\)|$)", body, re.M)}
        self.assertEqual(called, set(), f"the grant block calls {sorted(called)} before bb-tty defines them")


if __name__ == "__main__":
    unittest.main()
