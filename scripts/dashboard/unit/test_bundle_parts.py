"""What a node's sessions run from the bundle (workspace.BUNDLE_PARTS): every
bb-* script beside bb-tty is a hook or a relay a session on a node calls, and
one left out is a hooks file naming a path that is not there (B241: every
Codex hook failed because bb-agent-hook did not ride along)."""
import ast
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(HERE, "..")


def bundle_parts():
    # Read off the source rather than imported: workspace.py configures
    # itself against /config at import.
    tree = ast.parse(open(os.path.join(DASH, "workspace.py")).read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "BUNDLE_PARTS" for t in node.targets):
            return set(ast.literal_eval(node.value))
    raise AssertionError("workspace.py has no BUNDLE_PARTS")


class BundleParts(unittest.TestCase):
    def test_every_session_script_rides_in_the_bundle(self):
        parts = bundle_parts()
        scripts = sorted(f for f in os.listdir(DASH) if f.startswith("bb-") and os.path.isfile(os.path.join(DASH, f)))
        self.assertIn("bb-agent-hook", scripts)
        missing = [f for f in scripts if f"scripts/dashboard/{f}" not in parts]
        self.assertEqual(missing, [], f"not in the bundle a node runs sessions from: {missing}")


if __name__ == "__main__":
    unittest.main()
