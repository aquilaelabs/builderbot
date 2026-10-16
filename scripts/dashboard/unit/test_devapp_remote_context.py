"""A container written here that builds from a git URL builds the files
committed at that ref (B595): which contexts are such a URL, so the
rebuild's log can say an ignored file of a working tree is not in it."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import devapp  # noqa: E402


class RemoteContexts(unittest.TestCase):
    def test_git_urls_are_found(self):
        text = """services:
  site:
    build:
      context: https://github.com/acme/site.git#main
      dockerfile: Dockerfile.site
  api:
    build: git@github.com:acme/api.git
  web:
    build: "github.com/acme/web"
"""
        self.assertEqual(devapp.remote_contexts(text),
                         ["https://github.com/acme/site.git#main", "git@github.com:acme/api.git", "github.com/acme/web"])

    def test_a_path_on_disk_is_not(self):
        text = "services:\n  site:\n    build:\n      context: /workspace/site\n  db:\n    build: .\n"
        self.assertEqual(devapp.remote_contexts(text), [])

    def test_nothing_is_nothing(self):
        self.assertEqual(devapp.remote_contexts(""), [])
        self.assertEqual(devapp.remote_contexts(None), [])


if __name__ == "__main__":
    unittest.main()
