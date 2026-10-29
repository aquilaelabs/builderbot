"""The Library's one list (R170 step 1): the toolchains and packs a node's
store reads, the coding agents, the apps, the catalog's offers not yet added
and the companions, each a row of one shape with its kind, its tier, where
it stands on the node and the one verb it takes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import library  # noqa: E402

TC = {"name": "box", "live": True, "root": "/mnt/SDK", "free_mb": 2048, "platform": "linux/amd64",
      "job": {"running": True, "action": "install", "current": "jdk"},
      "items": [
          {"name": "jdk", "label": "JDK 21", "about": "Java", "installed": False, "state": "", "latest": "21.0.4", "platforms": ["linux/amd64"]},
          {"name": "node", "label": "Node", "about": "JavaScript", "installed": True, "version": "22.1", "latest": "22.2", "state": "update", "updatable": True,
           "tool": "node", "path": "/mnt/SDK/node", "system": {"manager": "apt", "names": ["libx"], "missing": []}, "needs": [], "needed_by": ["pnpm"],
           "verified": {"algo": "sha256", "where": "its release notes"}, "pinned_by": ["web"], "reopen": 1},
          {"name": "ghidra", "label": "Ghidra", "about": "a decompiler", "installed": True, "version": "11", "state": "current",
           "pack": {"url": "https://example.com/g", "commit": "a" * 40, "tier": "vetted", "by": "ann"}},
          {"name": "mine", "label": "Mine", "about": "my own", "installed": False, "pack": {"url": "", "commit": "b" * 40, "tier": "url", "here": True}},
      ]}
AGENTS = [{"name": "claude-code", "agent": "claude", "label": "Claude Code", "for": "Claude", "installed": "2.1", "latest": "2.2", "state": "update", "running": False},
          {"name": "codex-cli", "agent": "codex", "label": "Codex CLI", "for": "Codex", "installed": "", "latest": "0.9", "state": "absent"}]
APPS = [{"id": "jellyfin", "name": "Jellyfin", "what": "media", "port": 8096, "media": True, "secrets": [],
         "compose": "services:\n  jellyfin:\n    image: jellyfin/jellyfin:10.9\n    ports: ['${PORT}:8096']\n    volumes: ['${DATA}:/config', '${MEDIA}:/media']\n"}]
INDEX = {"packs": [{"name": "ghidra", "url": "https://example.com/g", "commit": "a" * 40, "sha256": "c" * 64, "tier": "vetted", "about": "a decompiler"},
                   {"name": "radare", "url": "https://example.com/r", "commit": "d" * 40, "sha256": "e" * 64, "tier": "vetted", "about": "another", "platforms": ["linux/*"]},
                   {"name": "gone", "url": "https://example.com/x", "commit": "f" * 40, "sha256": "0" * 64, "tier": "vetted", "withdrawn": True}]}
COMP = {"apps": [{"name": "android", "title": "BuilderBot for Android", "does": "the phone app", "offered": True, "version": "0.9.0",
                  "files": [{"file": "a.apk", "sha256": "1" * 64, "size": 1, "url": "/apps/a.apk"}]},
                 {"name": "vscode", "title": "VS Code extension", "does": "the extension", "offered": True, "version": "", "absent": "0.9.0", "files": []},
                 {"name": "companion", "title": "Windows companion", "does": "not offered here", "offered": False, "version": "", "files": []}]}


class Rows(unittest.TestCase):
    def setUp(self):
        self.rows = library.rows(TC, AGENTS, APPS, INDEX, COMP)
        self.by = {(r["kind"], r["name"]): r for r in self.rows}

    def test_one_shape_in_the_pages_order(self):
        kinds = [r["kind"] for r in self.rows]
        self.assertEqual(kinds, ["agent", "agent", "toolchain", "toolchain", "pack", "pack", "app", "pack", "companion", "companion"])
        self.assertIn("service", library.KINDS)
        for r in self.rows:
            for k in ("kind", "tier", "name", "label", "about", "platforms", "installed", "version", "latest", "update", "running", "verb"):
                self.assertIn(k, r, (r["kind"], r["name"], k))
            self.assertIn(r["kind"], library.KINDS)
            self.assertIn(r["tier"], ("official", "vetted", "sideloaded"))

    def test_agents(self):
        c, x = self.by[("agent", "claude-code")], self.by[("agent", "codex-cli")]
        self.assertEqual((c["installed"], c["version"], c["latest"], c["update"], c["verb"]), (True, "2.1", "2.2", True, "update"))
        self.assertEqual((x["installed"], x["verb"], x["agent"]), (False, "install", "codex"))

    def test_toolchains_carry_the_job_in_flight(self):
        jdk, node = self.by[("toolchain", "jdk")], self.by[("toolchain", "node")]
        self.assertTrue(jdk["running"])
        self.assertEqual(jdk["doing"], "install")
        self.assertEqual((jdk["tier"], jdk["verb"], jdk["latest"]), ("official", "install", "21.0.4"))
        self.assertEqual((node["update"], node["verb"], node["running"]), (True, "update", False))

    def test_packs_by_tier_and_the_catalogs_offers_not_yet_added(self):
        g, m = self.by[("pack", "ghidra")], self.by[("pack", "mine")]
        self.assertEqual((g["tier"], g["installed"], g["verb"], g["pack"]["by"]), ("vetted", True, "", "ann"))
        self.assertEqual((m["tier"], m["pack"]["here"], m["verb"]), ("sideloaded", True, "install"))
        offers = [r for r in self.rows if r["kind"] == "pack" and r.get("catalog")]
        self.assertEqual([r["name"] for r in offers], ["radare"], "ghidra is added already, gone is withdrawn")
        r = offers[0]
        self.assertEqual((r["tier"], r["verb"], r["catalog"]["sha256"], r["latest"]), ("vetted", "add", "e" * 64, "d" * 12))

    def test_the_open_rows_lines_ride_along(self):
        # Step 2: what a toolchain's open row says comes with the row.
        node = self.by[("toolchain", "node")]
        self.assertEqual((node["tool"], node["path"], node["needed_by"], node["pinned"], node["reopen"]), ("node", "/mnt/SDK/node", ["pnpm"], ["web"], 1))
        self.assertEqual(node["system"]["manager"], "apt")
        self.assertEqual(node["verified"]["algo"], "sha256")
        self.assertEqual(self.by[("toolchain", "jdk")]["system"], None)

    def test_apps_and_companions(self):
        j = self.by[("app", "jellyfin")]
        self.assertEqual((j["label"], j["port"], j["media"], j["verb"], j["installed"]), ("Jellyfin", 8096, True, "install", False))
        # ...and its compose with the blanks New container fills, sorted (step 2).
        self.assertIn("image: jellyfin/jellyfin:10.9", j["compose"])
        self.assertEqual(j["blanks"], ["DATA", "MEDIA", "PORT"])
        a, v = self.by[("companion", "android")], self.by[("companion", "vscode")]
        self.assertEqual((a["verb"], a["download"]["url"], a["version"]), ("download", "/apps/a.apk", "0.9.0"))
        self.assertEqual((v["verb"], v["absent"], v["download"]), ("", "0.9.0", None))

    def test_a_service_is_a_row_with_its_configuration_as_the_page_sees_it(self):
        # R172: the model router as a card, its values from its own status.
        fields = [{"name": "anthropic", "kind": "secret", "label": "Anthropic"}, {"name": "custom", "kind": "list", "label": "Other", "fields": [{"name": "name", "kind": "text"}, {"name": "base", "kind": "text"}, {"name": "key", "kind": "secret"}]},
                  {"name": "ollama", "kind": "switch", "label": "Ollama"}, {"name": "projects", "kind": "projects", "label": "Projects"}]
        status = {"deployed": True, "url": "http://10.0.0.5:4000", "providers": {"anthropic": True, "openai": False},
                  "custom": [{"name": "groq", "base": "https://api.groq.com/v1", "key": True}], "ollama": {"on": True, "models": ["qwen"]},
                  "projects": ["web"], "models": [{"id": "x"}], "models_at": 5, "spend": {"web": 1.5}}
        rows = library.rows(TC, [], [], None, None, services=[{"manifest": {"name": "model-router", "label": "Model router", "about": "r", "platforms": ["linux/*"],
                                                                            "service": {"kind": "router"}, "config": fields}, "status": status, "ready": "", "all_projects": ["web", "app"]}])
        r = next(x for x in rows if x["kind"] == "service")
        self.assertEqual((r["name"], r["installed"], r["verb"], r["service"], r["all_projects"]), ("model-router", True, "", "router", ["web", "app"]))
        self.assertEqual(r["values"], {"anthropic": True, "custom": [{"name": "groq", "base": "https://api.groq.com/v1", "key": True}], "ollama": True, "projects": ["web"]})
        self.assertEqual((r["status"]["url"], r["status"]["spend"]), ("http://10.0.0.5:4000", {"web": 1.5}))
        # ...and a pack's answers ride its row, only where it asks for any.
        tc = {**TC, "items": [{**TC["items"][0], "config": [{"name": "k", "kind": "secret", "label": "K"}]}, TC["items"][1]]}
        rows = library.rows(tc, [], [], None, None, pack_values={"jdk": {"k": True}})
        self.assertEqual(next(x for x in rows if x["name"] == "jdk")["values"], {"k": True})
        self.assertIsNone(next(x for x in rows if x["name"] == "node")["values"])

    def test_nothing_read_is_nothing_listed(self):
        self.assertEqual(library.rows(None, None, None, None, None), [])
        self.assertEqual(library.rows({"nonode": True}, [], [], {"packs": []}, {"apps": []}), [])



    def test_a_card_not_for_the_node_is_marked(self):
        xcode = {"name": "xcode", "label": "Xcode", "about": "Apple's", "installed": False, "state": "", "latest": "", "platforms": ["darwin/arm64"],
                 "wrong_platform": "needs darwin/arm64"}
        tc = {**TC, "items": TC["items"] + [xcode]}
        index = {"packs": [{"name": "armonly", "url": "https://example.com/a", "commit": "c" * 40, "sha256": "d" * 64, "tier": "vetted", "about": "arm",
                            "platforms": ["linux/arm64"]},
                           {"name": "anylinux", "url": "https://example.com/b", "commit": "c" * 40, "sha256": "d" * 64, "tier": "vetted", "about": "any",
                            "platforms": ["linux/*"]}]}
        by = {r["name"]: r for r in library.rows(tc, [], [], index, None)}
        self.assertEqual(by["xcode"]["wrong_platform"], "needs darwin/arm64", "the toolchain's own verdict stands")
        self.assertIn("not for this node (linux/amd64)", by["armonly"]["wrong_platform"])
        self.assertEqual((by["anylinux"]["wrong_platform"], by["jdk"]["wrong_platform"]), ("", ""))
        by = {r["name"]: r for r in library.rows({**tc, "platform": ""}, [], [], index, None)}
        self.assertEqual((by["armonly"]["wrong_platform"], by["xcode"]["wrong_platform"]), ("", "needs darwin/arm64"),
                         "a node that has not said its platform is not judged")

if __name__ == "__main__":
    unittest.main()
