"""The official packs (R169 step 1): every shipped toolchain and every
agent as a pack in bbtool.json's format, validated as such (a shipped
recipe or an agent's adapter standing in for steps and verbs, a shipped
name allowed), an agent that cannot take the guards refused, and the
export's check holding packs/ to the tables."""
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(HERE, ".."))
import toolpacks  # noqa: E402


class Official(unittest.TestCase):
    def test_a_config_block_is_checked_and_a_service_is_official_only(self):
        # R172: what a pack asks for per node, drawn by the Library as Configure.
        good = {"name": "hexkit", "label": "Hexkit", "platforms": ["linux/amd64"], "terms": [], "layout": {"bin": [], "env": {}},
                "verbs": {"dump": {"about": "dump", "usage": "FILE", "run": ["{dir}/bin/hexkit", "{args}"]}},
                "config": [{"name": "api_key", "label": "API key", "kind": "secret", "env": "HEXKIT_KEY", "required": True},
                           {"name": "region", "kind": "choice", "choices": [{"value": "eu"}, {"value": "us", "label": "US"}]},
                           {"name": "hosts", "kind": "list", "fields": [{"name": "name", "kind": "text"}, {"name": "key", "kind": "secret"}]},
                           {"name": "verbose", "kind": "switch"}]}
        clean, errors = toolpacks.validate(good)
        self.assertEqual(errors, [])
        self.assertEqual([f["kind"] for f in clean["config"]], ["secret", "choice", "list", "switch"])
        self.assertEqual((clean["config"][0]["env"], clean["config"][0]["required"], clean["config"][1]["choices"][1]["label"]), ("HEXKIT_KEY", True, "US"))
        self.assertEqual([f["name"] for f in clean["config"][2]["fields"]], ["name", "key"])
        for bad, said in (([{"name": "x", "kind": "magic"}], "kind is one of"), ([{"name": "A", "kind": "text"}], "name is"),
                          ([{"name": "a", "kind": "text"}, {"name": "a", "kind": "text"}], "once"),
                          ([{"name": "l", "kind": "list", "fields": [{"name": "p", "kind": "projects"}]}], "not inside a list"),
                          ([{"name": "c", "kind": "choice"}], "choices lists"), ("no", "config is a list")):
            _c, errors = toolpacks.validate(dict(good, config=bad))
            self.assertTrue(any(said in e for e in errors), (bad, errors))
        _c, errors = toolpacks.validate(dict(good, service={"kind": "router"}))
        self.assertTrue(any("official pack's alone" in e for e in errors))
        import router
        clean, errors = toolpacks.validate(router.pack())
        self.assertEqual(errors, [])
        self.assertEqual((clean["service"], clean["verbs"], [f["name"] for f in clean["config"]][-3:]), ({"kind": "router"}, {}, ["custom", "ollama", "projects"]))
        _c, errors = toolpacks.validate(dict(router.pack(), service={"kind": "nope"}))
        self.assertTrue(any("service.kind is one of" in e for e in errors))

    def test_an_official_pack_stands_in_for_steps_and_verbs(self):
        m = {"name": "jdk", "label": "JDK", "tier": "official", "platforms": ["linux/amd64"], "terms": [],
             "layout": {"bin": ["bin"], "env": {"JAVA_HOME": ""}, "tool": "bin/java"}, "shipped": {"source": {"kind": "tarball"}}}
        clean, errors = toolpacks.validate(m, shipped=("jdk",))
        self.assertEqual(errors, [])
        self.assertEqual((clean["tier"], clean["shipped"]["source"]["kind"], clean["verbs"]), ("official", "tarball", {}))
        clean, errors = toolpacks.validate(dict(m, tier="url"), shipped=("jdk",))
        self.assertTrue(any("a name of its own" in e for e in errors) and any("official pack's alone" in e for e in errors))

    def test_an_agent_pack_is_checked_and_one_without_guards_is_refused(self):
        a = {"product": "Claude Code", "command": "claude", "provider": "Anthropic", "reported": "claude", "update_job": "claude-update",
             "login_job": "claude-login", "logout_job": "claude-logout", "briefing": "system-prompt-file", "guards": "hooks", "state": "hooks",
             "transcripts": ".claude/projects", "latest_url": "", "tool": "claude-code"}
        m = {"name": "claude", "label": "Claude", "tier": "official", "platforms": ["linux/*"], "terms": [], "agent": a}
        clean, errors = toolpacks.validate(m)
        self.assertEqual(errors, [])
        self.assertEqual(clean["agent"]["command"], "claude")
        clean, errors = toolpacks.validate({**m, "agent": {**a, "guards": "none"}})
        self.assertTrue(any("cannot take BuilderBot's guards" in e for e in errors))
        clean, errors = toolpacks.validate({**m, "tier": "url"})
        self.assertTrue(any("official pack's alone" in e for e in errors))

    def test_the_packs_written_match_the_tables(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "packs-export.py"), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(os.path.join(ROOT, "packs", "agents", "claude", "bbtool.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertEqual((m["tier"], m["agent"]["guards"]), ("official", "hooks"))
        with open(os.path.join(ROOT, "packs", "official", "jdk", "bbtool.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertEqual(m["shipped"]["source"]["kind"], "tarball")


if __name__ == "__main__":
    unittest.main()
