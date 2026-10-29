"""A coding agent from a vetted pack (R169 step 8): its adapter is data in
the manifest, held to the shapes BuilderBot already writes for the shipped
agents, and refused when it cannot take the guards or reaches past what a
session may set."""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import toolpacks  # noqa: E402

KITE = {"name": "kite", "label": "Kite", "about": "A coding agent.", "platforms": ["linux/amd64"],
        "install": {"steps": [["sh", "{dir}/install.sh"]]}, "layout": {"bin": ["bin"], "tool": "bin/kite"},
        "agent": {"name": "Kite", "product": "Kite CLI", "provider": "Kite Labs", "command": "kite",
                  "briefing": {"how": "flag-text", "flag": "--rules"},
                  "hooks": {"file": ".kite/hooks/builderbot.json", "shape": "grouped", "payload": "camel",
                            "events": {"pre": "PreToolUse", "prompt": "UserPromptSubmit", "stop": "Stop", "recall": "PostCompact"},
                            "tools": {"shell": ["run_command"]}},
                  "env": {"KITE_DISABLE_AUTOUPDATER": "1"}, "respawn": ["-c"],
                  "first_prompt": {"how": "after-dashdash"},
                  "signin": {"file": ".kite/auth.json", "env": "KITE_API_KEY", "login": ["kite", "login"]},
                  "transcripts": {"dir": ".kite/sessions", "file": "{session}/log.jsonl", "session_key": "sessionId"},
                  "models": ["kite-1", "kite-1-mini"], "model_flag": "--model"}}


def with_agent(**change):
    m = copy.deepcopy(KITE)
    m["agent"].update(change)
    return m


class PackAgent(unittest.TestCase):
    def test_a_whole_adapter_is_kept_and_a_pack_agent_needs_no_verbs(self):
        m, errors = toolpacks.validate(KITE)
        self.assertEqual(errors, [])
        a = m["pack_agent"]
        self.assertEqual((a["command"], a["hooks"]["shape"], a["hooks"]["payload"]), ("kite", "grouped", "camel"))
        self.assertEqual(a["hooks"]["events"]["pre"], "PreToolUse")
        self.assertEqual(a["login"], ["kite", "login"])
        self.assertEqual(a["respawn"], ["-c"])
        self.assertEqual(a["models"], ["kite-1", "kite-1-mini"])
        self.assertNotIn("agent", m, "the official adapter's key is the shipped agents' alone")

    def test_one_that_cannot_take_the_guards_is_refused(self):
        hooks = copy.deepcopy(KITE["agent"]["hooks"])
        del hooks["events"]["stop"]
        _, errors = toolpacks.validate(with_agent(hooks=hooks))
        self.assertTrue(any("names no stop" in e and "guards" in e for e in errors), errors)
        _, errors = toolpacks.validate(with_agent(hooks=None))
        self.assertTrue(any("cannot take BuilderBot's guards" in e for e in errors), errors)
        hooks = dict(KITE["agent"]["hooks"], shape="yaml")
        _, errors = toolpacks.validate(with_agent(hooks=hooks))
        self.assertTrue(any("agent.hooks.shape is one of grouped, flat" in e for e in errors), errors)

    def test_its_name_is_its_sessions_and_never_a_shipped_agents(self):
        for name, said in (("claude", "a coding agent BuilderBot ships"), ("kite-cli", "2 to 16 of a-z and 0-9")):
            _, errors = toolpacks.validate(dict(KITE, name=name))
            self.assertTrue(any(said in e for e in errors), (name, errors))

    def test_what_a_session_may_not_be_handed(self):
        for env in ({"BB_PROJECT": "x"}, {"PATH": "/tmp"}, {"KITE_HOME": "/root/.kite"}):
            _, errors = toolpacks.validate(with_agent(env=env))
            self.assertTrue(any(e.startswith("agent.env") for e in errors), (env, errors))
        _, errors = toolpacks.validate(with_agent(signin={"login": ["sh", "-c", "curl"]}))
        self.assertTrue(any("runs the agent's own command" in e for e in errors), errors)
        _, errors = toolpacks.validate(with_agent(respawn=["-c", "$(rm -rf /)"]))
        self.assertTrue(any("agent.respawn lists up to 6 plain words" in e for e in errors), errors)
        hooks = dict(KITE["agent"]["hooks"], file="/etc/passwd")
        _, errors = toolpacks.validate(with_agent(hooks=hooks))
        self.assertTrue(any("agent.hooks.file" in e for e in errors), errors)
        _, errors = toolpacks.validate(with_agent(transcripts={"dir": ".kite", "file": "../x/{session}"}))
        self.assertTrue(any("agent.transcripts.file" in e for e in errors), errors)

    def test_models_need_their_flag(self):
        a = copy.deepcopy(KITE["agent"])
        del a["model_flag"]
        _, errors = toolpacks.validate(dict(KITE, agent=a))
        self.assertTrue(any("agent.model_flag" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
