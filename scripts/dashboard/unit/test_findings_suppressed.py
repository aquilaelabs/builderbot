"""findings.py: a SARIF result the code itself suppressed is not a finding.
Semgrep keeps a `# nosemgrep:` line in its SARIF with a `suppressions`
entry rather than dropping it, and every line annotated on 2 Oct still
showed on the Static analysis tab (4 Oct)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import findings  # noqa: E402


def run(*results):
    return {"tool": {"driver": {"name": "semgrep", "rules": [{"id": "r1"}]}}, "results": list(results)}


def res(line, **extra):
    return dict({"ruleId": "r1", "message": {"text": "m"},
                 "locations": [{"physicalLocation": {"artifactLocation": {"uri": "/src/app/x.py"},
                                                     "region": {"startLine": line}}}]}, **extra)


class Suppressed(unittest.TestCase):
    def rows(self, *results):
        out = findings._parse_run(run(*results), {"app"})
        return out[1] if isinstance(out, tuple) else out

    def test_an_in_source_suppression_is_dropped_and_a_rejected_one_kept(self):
        rows = self.rows(res(1), res(2, suppressions=[{"kind": "inSource"}]),
                         res(3, suppressions=[{"kind": "inSource", "status": "rejected"}]))
        lines = sorted(r.get("line") for r in rows)
        self.assertEqual(lines, [1, 3])


if __name__ == "__main__":
    unittest.main()
