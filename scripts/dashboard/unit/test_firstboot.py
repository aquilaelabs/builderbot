"""A prepared configuration's first boot (R161 step 8): the stick's root
step takes builderbot/firstboot.json off the ESP, sets the hostname and the
time zone, hands the rest over under /run and blanks the file in place; the
controller then makes the owner from a password hash and the people by name
with their SMB hashes, skips the setup page when asked, keeps the shares,
pools, array and apps as waiting, and keeps no hash in what it writes."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
TAKE = os.path.join(ROOT, "image", "mkosi.extra", "usr", "lib", "builderbot-os", "firstboot-take")
import firstboot  # noqa: E402
import settings  # noqa: E402
import users  # noqa: E402

NT = "8846F7EAEE8FB117AD06BDD830B7586C"
CFG = {"format": 1, "first_run": "skip", "hold_first_start": True, "machine": {"hostname": "tower", "timezone": "Europe/Berlin", "network": "dhcp"},
       "owner": {"name": "boss", "password_hash": users.hash_password("correct horse", iterations=1000)},
       "people": [{"name": "ann", "role": "admin", "smb_nt": NT}, {"name": "bad name!", "role": "user"}],
       "shares": [{"name": "media", "purpose": "array"}], "array": {"disks": [{"serial": "WD-1"}]}}


def wj(p, d):
    Path(p).write_text(json.dumps(d))


class Take(unittest.TestCase):
    def test_the_root_step_takes_it_off_the_stick_and_blanks_it_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            esp = Path(d, "esp", "builderbot"); esp.mkdir(parents=True)
            f = esp / "firstboot.json"
            body = b"BB-FIRSTBOOT-1\n" + json.dumps(CFG).encode() + b"\n"
            f.write_bytes(body + b" " * (65535 - len(body)) + b"\n")
            run = Path(d, "run")
            r = subprocess.run([sys.executable, TAKE], capture_output=True, text=True, check=False,
                               env=dict(os.environ, BB_ESP=str(Path(d, "esp")), BB_OS_RUN=str(run),
                                        BB_CONTROLLER_ENV=str(Path(d, "none")), PATH=d))
            self.assertEqual(r.returncode, 0, r.stderr)
            got = f.read_bytes()
            self.assertEqual(len(got), 65536, "its size kept, for the next write to find")
            self.assertTrue(got.startswith(b"BB-FIRSTBOOT-1\n") and not got[15:].strip(), "blanked: no hash left on the stick")
            handed = json.loads((run / "firstboot" / "firstboot.json").read_text())
            self.assertEqual(handed["config"]["owner"]["name"], "boss")
            self.assertIn("hostname", handed["machine"], "the machine's part is tried, and what it said kept")
            self.assertEqual(oct((run / "firstboot" / "firstboot.json").stat().st_mode & 0o777), "0o600")
            # A blank file is a plain stick: nothing handed over.
            shutil.rmtree(run)
            subprocess.run([sys.executable, TAKE], env=dict(os.environ, BB_ESP=str(Path(d, "esp")), BB_OS_RUN=str(run), PATH=d), check=False)
            self.assertFalse(run.exists())


class Apply(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        saved = (users.STATE if hasattr(users, "STATE") else None, settings.FILE, settings.write_json)
        users.configure(state=self.tmp, write_json=wj)
        settings.configure(write_json=wj, state=self.tmp)
        self.addCleanup(lambda: (setattr(settings, "FILE", saved[1]), setattr(settings, "write_json", saved[2])))
        self.holds = []
        firstboot.configure(state=self.tmp, write_json_fn=wj, users_mod=users, settings_mod=settings,
                            hold_first_fn=lambda: self.holds.append(1))
        self.handed = self.tmp / "handed.json"
        self.handed.write_text(json.dumps({"config": CFG, "machine": {"hostname": "applied", "timezone": "'Mars/Base' is not a time zone here"}}))

    def test_the_owner_and_the_people_are_made_and_the_setup_page_skipped(self):
        settings.set_many({"setup_done": False})
        r = firstboot.apply(self.handed)
        d = users.load()["users"]
        self.assertEqual(d["boss"]["role"], "owner")
        self.assertTrue(users.check_password(d["boss"]["password"], "correct horse"))
        self.assertEqual((d["ann"]["role"], d["ann"]["password"], d["ann"]["smb_nt"]), ("admin", "", NT))
        self.assertFalse(users.check_password(d["ann"]["password"], ""), "no password: the owner sets one")
        self.assertNotIn("bad name!", d)
        self.assertTrue(settings.get("setup_done"))
        self.assertFalse(self.handed.exists(), "the handed file goes")
        whats = lambda k: [x["what"] for x in r[k]]  # noqa: E731
        self.assertEqual(whats("done"), ["hostname", "accounts", "first run", "first start"])
        self.assertEqual(self.holds, [1], "the first start held on the disks")
        self.assertEqual(whats("waiting"), ["shares", "array"])
        self.assertIn("timezone", whats("failed"))
        kept = (self.tmp / "firstboot.json").read_text()
        self.assertNotIn("pbkdf2", kept)
        self.assertNotIn(NT, kept)
        self.assertEqual(firstboot.view()["waiting"][0]["what"], "shares")

    def test_it_never_makes_an_owner_on_a_store_that_has_one(self):
        users.claim("first", "a long password")
        r = firstboot.apply(self.handed)
        self.assertIn("accounts", [x["what"] for x in r["failed"]])
        self.assertNotIn("boss", users.load()["users"])

    def test_no_password_leaves_the_owner_to_the_first_run_page(self):
        cfg = dict(CFG, owner={"name": "boss"})
        self.handed.write_text(json.dumps({"config": cfg, "machine": {}}))
        r = firstboot.apply(self.handed)
        self.assertEqual(users.load()["users"], {})
        self.assertIn("accounts", [x["what"] for x in r["waiting"]])
        self.assertIsNone(firstboot.apply(self.handed), "once")


if __name__ == "__main__":
    unittest.main()
