"""The controller's half of the sealed sign-ins (R126, tokenkeys.py): the
public key a node seals with, made from the account's own key (R154), and
the keys a person's own terminal carries, wrapped to the agent's boot key,
that open those seals and nothing else; the key each seal names is the one
sent, as |prev when it is not the account's own today (a key before it, or
the install key from before accounts had their own) so the node seals it
again; changing the install key moves nothing on the nodes; and the signed
open still fits in the agent's request."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import accountkeys  # noqa: E402
import signing      # noqa: E402
import termws       # noqa: E402
import tokenkeys    # noqa: E402

AGENT = str(HERE.parent.parent / "agent")
NEW, OLD = b"the install key of today, long enough", b"the install key of before, long enough"


class TokenKeys(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.prev = os.path.join(self.d, "previous")
        os.environ["BB_INSTALL_KEY_PREVIOUS_FILE"] = self.prev
        tokenkeys.configure(agent_dir=AGENT)
        termws.configure(agent_dir=AGENT)
        tokenkeys._pub_cache.clear()
        self.was = signing.MASTER
        signing.MASTER = NEW
        accountkeys.configure(state=Path(self.d))
        self.ts = tokenkeys.ts()

    def tearDown(self):
        signing.MASTER = self.was
        os.environ.pop("BB_INSTALL_KEY_PREVIOUS_FILE", None)

    def node_seals(self, pub, data=b'{"claudeAiOauth": "x"}', named=True):
        blob = self.ts.seal(pub, data, {"agent": "claude"})
        e = self.ts.boot_secret()
        seal = {"R": self.ts.header(blob)["R"], **({"K": self.ts.rid(pub)} if named else {})}
        census = {"E": self.ts.public(e), "sealed": {"u_00000001": {"claude": seal}}}
        return blob, e, census

    def opened(self, blob, e, tk):
        import base64
        keys = self.ts.unwrap(e, tk["C"], base64.urlsafe_b64decode(tk["w"] + "=" * (-len(tk["w"]) % 4)))
        r = self.ts.rid(self.ts.header(blob)["R"])
        for name in (r, r + "|prev"):
            if name in keys:
                try:
                    return self.ts.open_with(keys[name], blob), name.endswith("|prev")
                except self.ts.Refused:
                    continue
        return None, None

    def test_a_persons_terminal_opens_their_seal(self):
        pubs = tokenkeys.pubs("n_1", ["u_00000001", "u_00000002"])
        self.assertEqual(set(pubs), {"u_00000001", "u_00000002"})
        blob, e, census = self.node_seals(pubs["u_00000001"])
        tk = tokenkeys.wrapped_for("n_1", "u_00000001", census)
        self.assertEqual(tk["acct"], "u_00000001")
        self.assertEqual(self.opened(blob, e, tk), (b'{"claudeAiOauth": "x"}', False))

    def test_nobody_else_gets_a_key(self):
        _, _, census = self.node_seals(tokenkeys.public("n_1", "u_00000001"))
        self.assertIsNone(tokenkeys.wrapped_for("n_1", "u_00000002", census))
        self.assertIsNone(tokenkeys.wrapped_for("n_1", "u_00000001", {"sealed": census["sealed"]}))

    def test_no_install_key_seals_nothing(self):
        signing.MASTER = None
        self.assertEqual(tokenkeys.pubs("n_1", ["u_00000001"]), {})

    def test_the_public_half_is_the_accounts_own(self):
        own = accountkeys.key_of("u_00000001")
        self.assertEqual(tokenkeys.public("n_1", "u_00000001"), self.ts.public(self.ts.secret(own, "n_1", "u_00000001")))
        self.assertNotEqual(tokenkeys.public("n_1", "u_00000001"), self.ts.public(self.ts.secret(NEW, "n_1", "u_00000001")))

    def test_an_install_key_change_moves_nothing_on_the_nodes(self):
        blob, e, census = self.node_seals(tokenkeys.public("n_1", "u_00000001"))
        sealed = accountkeys._load()
        signing.MASTER, signing.PREVIOUS = OLD, NEW
        accountkeys.seal_all(again=True)
        signing.PREVIOUS = None
        self.assertNotEqual(accountkeys._load(), sealed)
        tk = tokenkeys.wrapped_for("n_1", "u_00000001", census)
        self.assertEqual(self.opened(blob, e, tk), (b'{"claudeAiOauth": "x"}', False))

    def test_an_account_key_change_opens_with_the_one_before(self):
        blob, e, census = self.node_seals(tokenkeys.public("n_1", "u_00000001"))
        accountkeys.configure(state=Path(self.d), nodes_under=lambda uid, k: 1)
        self.assertEqual(accountkeys.change("u_00000001")[1], 200)
        tk = tokenkeys.wrapped_for("n_1", "u_00000001", census)
        self.assertEqual(self.opened(blob, e, tk), (b'{"claudeAiOauth": "x"}', True))
        self.assertEqual(tokenkeys.under_previous("n_1", census), 1)
        # Another change waits while the one before still opens something...
        self.assertEqual(accountkeys.change("u_00000001")[1], 409)
        # ...and the one before goes once nothing is sealed under it.
        accountkeys.configure(state=Path(self.d), nodes_under=lambda uid, k: 0)
        self.assertFalse(accountkeys.status("u_00000001")["previous"])
        self.assertEqual(self.opened(blob, e, tokenkeys.wrapped_for("n_1", "u_00000001", census)), (None, None))

    def test_a_seal_from_before_account_keys_opens_with_the_install_key(self):
        legacy = self.ts.public(self.ts.secret(NEW, "n_1", "u_00000001"))
        for named in (True, False):
            blob, e, census = self.node_seals(legacy, named=named)
            tk = tokenkeys.wrapped_for("n_1", "u_00000001", census)
            self.assertEqual(self.opened(blob, e, tk), (b'{"claudeAiOauth": "x"}', True), named)

    def test_a_seal_under_the_install_key_before_needs_it_kept(self):
        legacy = self.ts.public(self.ts.secret(NEW, "n_1", "u_00000001"))
        _, _, census = self.node_seals(legacy)
        self.assertEqual(tokenkeys.sealed_under({"n_1": census}, NEW), 1)
        self.assertEqual(tokenkeys.sealed_under({"n_1": census}, OLD), 0)
        self.assertEqual(tokenkeys.sealed_under({"n_1": census}, NEW, "u_00000002"), 0)

    def test_seals_under_the_key_before_are_counted(self):
        pub = tokenkeys.public("n_1", "u_00000001")
        census = {"E": "2", "sealed": {"u_00000001": {"claude": {"R": "2", "K": self.ts.rid(pub)}}}}
        self.assertEqual(tokenkeys.under_previous("n_1", census), 0)
        census["sealed"]["u_00000001"]["claude"]["K"] = self.ts.rid(self.ts.public(self.ts.secret(NEW, "n_1", "u_00000001")))
        self.assertEqual(tokenkeys.under_previous("n_1", census), 1)

    def test_the_signed_open_fits_the_agents_request(self):
        signing.MASTER = OLD
        Path(self.prev).write_bytes(NEW)
        e = self.ts.boot_secret()
        pub = tokenkeys.public("n_1", "u_00000001")
        sealed = {ag: {"R": self.ts.header(self.ts.seal(pub, b"x"))["R"]} for ag in ("claude", "codex")}
        tk = tokenkeys.wrapped_for("n_1", "u_00000001", {"E": self.ts.public(e), "sealed": {"u_00000001": sealed}})
        t = termws.term()
        blob = t.pack({"tk": tk, "kind": "rw", "argv": ["u_00000001~web", "/workspace/web"] * 4, "cols": 200, "rows": 60})
        self.assertEqual(t.unpack(blob)["tk"], tk)
        self.assertLess(len(blob) + 200, 8192)


if __name__ == "__main__":
    unittest.main()
