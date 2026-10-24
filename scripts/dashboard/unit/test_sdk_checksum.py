"""What a toolchain's download should be (R137): each row's checksum source
read as its publisher states it, a row that names none refused, and every
tarball and script row of the shipped catalog naming one."""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
import sdkmeta  # noqa: E402

H64 = "ab" * 32
H40 = "cd" * 20


def row(spec, url_kind="tarball"):
    return {"name": "x", "source": {"kind": url_kind, "checksum": spec}}


class Checksum(unittest.TestCase):
    def answer(self, pages):
        return mock.patch.object(sdkmeta, "get", lambda url, decode=True: pages[url] if decode else pages[url].encode())

    def test_github_asset_digest(self):
        rel = {"tag_name": "v1", "assets": [{"name": "Tool-linux-x86_64", "digest": "sha256:" + H64}]}
        with self.answer({"https://api.github.com/repos/o/r/releases/latest": json.dumps(rel)}):
            got = sdkmeta.checksum(row({"from": "github-asset"}),
                                   "https://github.com/o/r/releases/latest/download/tool-linux-x86_64", "")
        self.assertEqual(got[:2], ("sha256", H64))
        self.assertIn("o/r v1", got[2])

    def test_a_checksum_file_names_the_file(self):
        page = f"{'00' * 32}  other.tar.xz\n{H64}  node-v1-linux-x64.tar.xz\n"
        with self.answer({"https://n/dist/v1/SHASUMS256.txt": page}):
            got = sdkmeta.checksum(row({"from": "file", "url": "{base}/SHASUMS256.txt"}),
                                   "https://n/dist/v1/node-v1-linux-x64.tar.xz", "v1")
        self.assertEqual(got[:2], ("sha256", H64))

    def test_a_one_line_file_with_a_star(self):
        with self.answer({"https://r/rustup-init.sha256": f"{H64} *./rustup-init\n"}):
            self.assertEqual(sdkmeta.checksum(row({"from": "file", "url": "{url}.sha256"}), "https://r/rustup-init", "")[1], H64)

    def test_go_and_zig_indexes(self):
        go = [{"files": [{"filename": "go1.tar.gz", "sha256": H64}]}]
        zig = {"master": {}, "0.13.0": {"x86_64-linux": {"tarball": "https://z/zig.tar.xz", "shasum": H64}}}
        with self.answer({"https://go.dev/dl/?mode=json&include=all": json.dumps(go),
                          "https://ziglang.org/download/index.json": json.dumps(zig)}):
            self.assertEqual(sdkmeta.checksum(row({"from": "go-json"}), "https://go.dev/dl/go1.tar.gz", "")[1], H64)
            self.assertEqual(sdkmeta.checksum(row({"from": "zig-index"}), "https://z/zig.tar.xz", "")[1], H64)

    def test_json_path_android_repo_and_zsync(self):
        xml = (f"<archive><complete><checksum type=\"sha1\">{H40}</checksum>"
               "<url>cmdline.zip</url></complete></archive>")
        with self.answer({"https://api/a": json.dumps([{"binary": {"package": {"checksum": H64}}}]),
                          "https://dl.google.com/android/repository/repository2-3.xml": xml,
                          "https://a/lo.AppImage.zsync": f"zsync: 0.6.2\nSHA-1: {H40}\n\n"}):
            self.assertEqual(sdkmeta.checksum(row({"from": "json", "url": "https://api/a", "path": "0.binary.package.checksum"}),
                                              "https://x/jdk", "")[1], H64)
            self.assertEqual(sdkmeta.checksum(row({"from": "android-repo"}), "https://dl/cmdline.zip", "")[:2], ("sha1", H40))
            self.assertEqual(sdkmeta.checksum(row({"from": "zsync"}), "https://a/lo.AppImage", "")[:2], ("sha1", H40))

    def test_none_says_why_and_no_source_is_refused(self):
        self.assertEqual(sdkmeta.checksum(row({"from": "none", "why": "because"}), "https://x/y", ""), ("none", "", "because"))
        with self.assertRaises(SystemExit):
            sdkmeta.checksum({"name": "x", "source": {"kind": "tarball"}}, "https://x/y", "")

    def test_what_is_not_a_digest_is_refused(self):
        with self.answer({"https://x/y.sha256": "<html>not found</html>\n"}):
            with self.assertRaises(SystemExit):
                sdkmeta.checksum(row({"from": "file", "url": "{url}.sha256"}), "https://x/y", "")

    def test_every_downloaded_row_of_the_catalog_names_a_source(self):
        bare = [t["name"] for t in sdkmeta.catalog()
                if (t.get("source") or {}).get("kind") in ("tarball", "script")
                and not ((t.get("source") or {}).get("checksum") or {}).get("from")]
        self.assertEqual(bare, [])


if __name__ == "__main__":
    unittest.main()
