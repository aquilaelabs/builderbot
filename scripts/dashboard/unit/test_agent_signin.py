"""Signing in to the other coding agents on a node (R95 step 3): what the
node reads back about each account (login-list.py), the record the
controller keeps per agent (claudegrant.py), and the device flows' links
and codes as the job's log carries them (signin.py). Against files and logs
shaped as Codex CLI 0.163.0 and Copilot CLI 1.0.102 leave them; never a
real account."""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import claudegrant  # noqa: E402
import signin  # noqa: E402

LIST = os.path.join(HERE, "..", "..", "lib", "login-list.py")
PROBES = os.path.join(HERE, "..", "..", "lib", "doctor-probes.py")


def jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{enc({'alg': 'none'})}.{enc(claims)}.sig"


class Listed(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.home = os.path.join(self.root, "u_0123abcd")
        os.makedirs(self.home)

    def put(self, rel, d):
        p = os.path.join(self.home, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            json.dump(d, f)

    def listed(self):
        p = subprocess.run([sys.executable, "-I", LIST], env={"BB_USERS_DIR": self.root, "PATH": os.environ["PATH"]},
                           capture_output=True, text=True, check=True)
        return json.loads(p.stdout)[0]

    def test_nobody_signed_in_lists_no_agent(self):
        self.assertEqual(self.listed()["agents"], {})

    def test_codex_names_the_chatgpt_account_and_plan_from_the_id_token(self):
        self.put(".codex/auth.json", {"tokens": {"id_token": jwt({
            "email": "me@example.invalid", "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}}),
            "access_token": "never-read"}})
        self.assertEqual(self.listed()["agents"]["codex"], {"email": "me@example.invalid", "plan": "plus"})

    def test_codex_with_an_api_key_says_so_and_not_the_key(self):
        self.put(".codex/auth.json", {"OPENAI_API_KEY": "sk-not-real"})
        got = self.listed()["agents"]["codex"]
        self.assertEqual(got, {"email": "an OpenAI API key", "plan": "API"})
        self.assertNotIn("sk-", json.dumps(got))

    def test_copilot_names_the_github_login(self):
        self.put(".copilot/config.json", {"lastLoggedInUser": {"host": "https://github.com", "login": "octo"}})
        self.assertEqual(self.listed()["agents"]["copilot"], {"email": "octo", "plan": ""})

    def test_grok_names_the_email_its_token_carries_and_never_the_token(self):
        claims = base64.urlsafe_b64encode(json.dumps({"email": "me@example.invalid"}).encode()).decode().rstrip("=")
        self.put(".grok/auth.json", {"session": {"access_token": f"eyJhbGciOiJub25lIn0.{claims}.sig"}})
        got = self.listed()["agents"]["grok"]
        self.assertEqual(got, {"email": "me@example.invalid", "plan": ""})
        self.assertNotIn("eyJ", json.dumps(got))

    def test_grok_signed_in_with_no_email_in_reach_says_its_account(self):
        self.put(".grok/auth.json", {"token": "opaque"})
        self.assertEqual(self.listed()["agents"]["grok"], {"email": "an xAI account", "plan": ""})

    def test_copilot_s_managed_header_is_read_past_and_kept(self):
        # 1.0.103 opens its config with comment lines (B280).
        head = "// User settings belong in settings.json.\n// This file is managed automatically.\n"
        p = os.path.join(self.home, ".copilot", "config.json")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write(head + json.dumps({"lastLoggedInUser": {"login": "octo"}, "theme": "dark"}))
        self.assertEqual(self.listed()["agents"]["copilot"], {"email": "octo", "plan": ""})
        subprocess.run([sys.executable, "-I", LIST, "--forget-copilot", self.home], check=True)
        with open(p) as f:
            got = f.read()
        self.assertTrue(got.startswith(head))
        self.assertEqual(json.loads(got[len(head):]), {"theme": "dark"})

    def test_forgetting_copilot_keeps_the_rest_of_its_config(self):
        self.put(".copilot/config.json", {"lastLoggedInUser": {"login": "octo"}, "loggedInUsers": [{"login": "octo"}],
                                          "copilotTokens": {"x": "y"}, "theme": "dark"})
        subprocess.run([sys.executable, "-I", LIST, "--forget-copilot", self.home], check=True)
        with open(os.path.join(self.home, ".copilot", "config.json")) as f:
            self.assertEqual(json.load(f), {"theme": "dark"})
        self.assertNotIn("copilot", self.listed()["agents"])


class Doctor(unittest.TestCase):
    """bb doctor's line for each other agent reads the same files the list
    does, so it and the Installed page never disagree."""
    setUp, put = Listed.setUp, Listed.put

    def signed(self, agent):
        return subprocess.run([sys.executable, PROBES, "signed", agent],
                              env={"HOME": self.home, "PATH": os.environ["PATH"]}, capture_output=True, text=True)

    def test_doctor_names_each_agent_s_account(self):
        self.put(".codex/auth.json", {"tokens": {"id_token": jwt({"email": "me@example.invalid"})}})
        self.put(".copilot/config.json", {"lastLoggedInUser": {"login": "octo"}})
        self.assertEqual((self.signed("codex").returncode, self.signed("codex").stdout), (0, " (me@example.invalid)"))
        self.assertEqual((self.signed("copilot").returncode, self.signed("copilot").stdout), (0, " (octo)"))

    def test_doctor_says_none_when_an_agent_is_not_signed_in(self):
        self.assertEqual(self.signed("codex").returncode, 1)
        self.assertEqual(self.signed("copilot").returncode, 1)


class Record(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)

    def test_each_agent_s_sign_in_is_its_own_record(self):
        claudegrant.report(self.home, "n1", "me@anthropic.invalid", "max")
        claudegrant.report(self.home, "n1", "me@openai.invalid", "plus", agent="codex")
        self.assertEqual(claudegrant.on(self.home, "n1")["email"], "me@anthropic.invalid")
        self.assertEqual(claudegrant.on(self.home, "n1", "codex")["email"], "me@openai.invalid")
        self.assertEqual(claudegrant.on(self.home, "n1", "copilot"), {})
        claudegrant.report(self.home, "n1", "", signed_in=False, agent="codex")
        self.assertEqual(claudegrant.on(self.home, "n1", "codex"), {})
        self.assertEqual(claudegrant.on(self.home, "n1")["email"], "me@anthropic.invalid")

    def test_every_agent_s_accounts_are_named_for_people_and_profile(self):
        # B296: People and Profile read each agent's, not Claude's alone.
        self.assertEqual(claudegrant.emails_of(self.home), {})
        claudegrant.report(self.home, "n1", "me@openai.invalid", "plus", agent="codex")
        claudegrant.report(self.home, "n2", "octo", "", agent="copilot")
        self.assertEqual(claudegrant.emails_of(self.home), {"codex": "me@openai.invalid", "copilot": "octo"})
        claudegrant.report(self.home, "n1", "me@anthropic.invalid", "max")
        self.assertEqual(claudegrant.emails_of(self.home)["claude"], "me@anthropic.invalid")

    def test_claude_s_record_is_where_it_always_was(self):
        claudegrant.report(self.home, "n1", "me@anthropic.invalid")
        self.assertTrue(os.path.exists(os.path.join(self.home, ".claude", ".bb-grant.json")))


class Flows(unittest.TestCase):
    class Nodes:
        def __init__(self, log, state="running"):
            self.j = {"log": log, "state": state}

        def job(self, jid):
            return self.j

    def flow(self, agent, log, state="running"):
        return signin.NodeFlow(self.Nodes(log, state), "n1", "j_1", "box", uid="u_0123abcd", agent=agent).state()

    def test_codex_s_device_login_shows_its_link_and_code(self):
        log = ("Welcome to Codex [v0.163.0]\nFollow these steps to sign in with ChatGPT using device code authorization:\n"
               "1. Open this link in your browser and sign in to your account\n   https://auth.openai.com/codex/device\n"
               "2. Enter this one-time code (expires in 15 minutes)\n   \x1b[94mABCD-1234\x1b[0m\n")
        st = self.flow("codex", log)
        self.assertEqual((st["url"], st["code"], st["waiting"], st["agent"]),
                         ("https://auth.openai.com/codex/device", "ABCD-1234", False, "codex"))

    def test_copilot_s_device_login_shows_its_link_and_code(self):
        st = self.flow("copilot", "To authenticate, visit https://github.com/login/device and enter code 1A2B-3C4D.\n"
                                  "Waiting for authorization...\n")
        self.assertEqual((st["url"], st["code"]), ("https://github.com/login/device", "1A2B-3C4D"))

    def test_claude_s_flow_still_waits_for_a_pasted_code(self):
        st = self.flow("claude", "visit: https://claude.com/cai/oauth/authorize?code=true&state=abc\nPaste code here if prompted > ")
        self.assertTrue(st["waiting"])
        self.assertEqual(st["code"], "")

    def test_a_failed_device_flow_says_why_in_its_own_words(self):
        st = self.flow("codex", "https://auth.openai.com/codex/device\nError: device auth timed out after 15 minutes\n", "failed")
        self.assertEqual(st["error"], "Error: device auth timed out after 15 minutes")


if __name__ == "__main__":
    unittest.main()
