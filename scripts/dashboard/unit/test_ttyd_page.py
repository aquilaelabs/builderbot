"""ttyd's page reaches a phone with a viewport and its text size held (B53):
without them a phone's browser boosted the terminal's font and cut each line.
The function, read from server.py and run on its own (importing the server
opens /config)."""
import ast
import gzip
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = open(os.path.join(HERE, "..", "server.py"), encoding="utf-8").read()
TREE = ast.parse(SRC).body
NODES = [n for n in TREE if (isinstance(n, ast.FunctionDef) and n.name == "_ttyd_page")
         or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in ("_TTYD_HEAD", "_TTYD_DPR") for t in n.targets))]
NS = {}
exec(compile(ast.Module(NODES, []), "server.py", "exec"), NS)  # noqa: S102 (our own function)
page, HEAD = NS["_ttyd_page"], NS["_TTYD_HEAD"]

BODY = b'<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>ttyd - Terminal</title></head><body></body></html>'


def answer(body=BODY, *extra, status="HTTP/1.1 200 OK"):
    head = [status, "server: ttyd/1.7.7", "content-type: text/html", f"content-length: {len(body)}", *extra]
    return ("\r\n".join(head) + "\r\n\r\n").encode() + body


class TtydPage(unittest.TestCase):
    def test_the_head_carries_the_viewport_and_the_text_size(self):
        status, hdrs, body = page(answer())
        self.assertEqual(status, "HTTP/1.1 200 OK")
        self.assertIn(b'<head><meta name="viewport" content="width=device-width', body)
        self.assertIn(b"text-size-adjust:100%", body)
        self.assertTrue(body.endswith(b"</html>"))

    def test_the_head_squares_the_device_pixel_box_with_the_ratio(self):
        # B91: the WebGL canvas was sized from a device-pixel box that
        # emulation leaves unscaled while the glyphs were drawn at the ratio.
        _, _, body = page(answer())
        self.assertIn(b'"devicePixelContentBoxSize"', body)
        self.assertIn(b"window.devicePixelRatio", body)
        # Before ttyd's own scripts, so xterm finds it in place.
        self.assertLess(body.find(b"devicePixelContentBoxSize"), body.find(b"<title>"))

    def test_the_old_length_is_dropped_and_the_rest_kept(self):
        _, hdrs, _ = page(answer())
        keys = [k.lower() for k, _ in hdrs]
        self.assertNotIn("content-length", keys)
        self.assertIn("content-type", keys)
        self.assertIn("server", keys)

    def test_a_compressed_page_is_left_alone(self):
        self.assertIsNone(page(answer(gzip.compress(BODY), "content-encoding: gzip")))

    def test_an_error_or_a_chunked_answer_is_left_alone(self):
        self.assertIsNone(page(answer(status="HTTP/1.1 404 Not Found")))
        self.assertIsNone(page(answer(BODY, "transfer-encoding: chunked")))
        self.assertIsNone(page(b"HTTP/1.1 200 OK\r\ncontent-type: text/html"))

    def test_not_html_or_already_carrying_it_is_left_alone(self):
        self.assertIsNone(page(answer(b"{}").replace(b"text/html", b"application/json")))
        self.assertIsNone(page(answer(BODY.replace(b"<head>", b"<head>" + HEAD))))


if __name__ == "__main__":
    unittest.main()
