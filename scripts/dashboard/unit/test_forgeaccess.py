"""What an agent may do on a project's git host (R188): the token measured
against a recorded host without changing anything, the project's Allow or
Deny over it, the briefing's lines, and bb forge's verbs in each host's
dialect."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import forgeaccess  # noqa: E402
import prefs  # noqa: E402

GH = {"name": "GitHub", "kind": "github"}
GL = {"name": "GitLab", "kind": "gitlab"}
GT = {"name": "Gitea", "kind": "gitea"}


def target(forge, token="github_pat_x"):
    return {"forge": forge, "host": "example.test", "repo": "o/app", "scheme": "https", "token": token}


class Host:
    """A recorded host: (method, path prefix) -> (status, body, headers);
    every call kept, so a test can say what was asked and that nothing but
    a probe was sent."""
    def __init__(self, answers, default=(404, {}, {})):
        self.answers, self.default, self.asked = answers, default, []

    def __call__(self, t, method, path, data=None, raw=False):
        self.asked.append((method, path, data))
        for (m, p), got in self.answers.items():
            if m == method and path.startswith(p):
                return got
        return self.default


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        self.pol = {}
        self.t = target(GH)
        forgeaccess.configure(state=self.d, write_json=lambda p, v: Path(p).write_text(json.dumps(v)),
                              target=lambda project: self.t, prefs_get=lambda project: {"forgepol": self.pol})
        self.was = forgeaccess._call
        self.addCleanup(setattr, forgeaccess, "_call", self.was)

    def host(self, answers, default=(404, {}, {})):
        h = Host(answers, default)
        forgeaccess._call = h
        return h


class Table(Base):
    def test_the_settings_defaults_are_the_tables(self):
        self.assertEqual(prefs.FORGEPOL_DEFAULT, forgeaccess.defaults())
        self.assertEqual(forgeaccess.defaults()["merge"], "deny", "merging starts off")
        self.assertEqual(set(forgeaccess.VERBS), set(forgeaccess.ABILITY_OF))

    def test_an_override_is_kept_only_when_it_is_allow_or_deny(self):
        got = prefs._clean({"forgepol": {"merge": "allow", "push": "maybe", "nope": "deny"}})["forgepol"]
        self.assertEqual(got["merge"], "allow")
        self.assertEqual(got["push"], "allow", "an unknown word reads as the default")
        self.assertNotIn("nope", got)


def github(case, write=422, role_push=True, scopes=None):
    h = {"github-authentication-token-expiration": "2026-12-01 00:00:00 UTC"}
    if scopes is not None:
        h["X-OAuth-Scopes"] = scopes
    return case.host({
        ("GET", "/user"): (200, {"login": "bot"}, {}),
        ("GET", "/repos/o/app/pulls"): (200, [], {}),
        ("GET", "/repos/o/app/issues"): (200, [], {}),
        ("GET", "/repos/o/app/actions/runs"): (403, {"message": "Resource not accessible"}, {}),
        ("GET", "/repos/o/app/releases"): (200, [], {}),
        ("GET", "/repos/o/app"): (200, {"permissions": {"push": role_push}}, h),
        ("POST", "/repos/o/app/issues"): (403, {}, {}),
        ("POST", "/repos/"): (write, {}, {}),
    })


class Measure(Base):

    def test_reads_are_asked_and_writes_are_probed_with_nothing_landing(self):
        h = github(self)
        m = forgeaccess.measure("app")
        has = m["has"]
        self.assertTrue(has["code_read"] and has["pr_read"] and has["releases_read"])
        self.assertFalse(has["actions_read"], "a 403 on a read is a no")
        self.assertTrue(has["push"] and has["pr_write"] and has["releases_write"], "a 422 means the token got through")
        self.assertFalse(has["issues_write"], "a 403 on a probe is a no")
        self.assertTrue(has["merge"], "merging is writing pull requests and contents")
        self.assertIsNone(has["workflows"], "a fine-grained token's Workflows cannot be read back")
        self.assertEqual((m["login"], m["token"]), ("bot", "fine-grained"))
        self.assertTrue(m["expires"].startswith("2026-12-01"))
        # Every write sent was missing what makes it real.
        for method, path, data in h.asked:
            if method == "POST":
                self.assertFalse((data or {}).get("title") or (data or {}).get("sha") or (data or {}).get("tag_name"),
                                 f"{path} carried what would land")
        self.assertEqual(forgeaccess.kept("app")["has"], has, "the measure is kept")

    def test_an_account_that_cannot_push_writes_nothing_and_nothing_is_probed(self):
        h = github(self, role_push=False)
        has = forgeaccess.measure("app")["has"]
        self.assertFalse(any(has[k] for k in ("push", "pr_write", "merge", "issues_write", "releases_write")))
        self.assertFalse([x for x in h.asked if x[0] == "POST"])

    def test_a_classic_tokens_scopes_say_workflows(self):
        self.t = target(GH, "ghp_x")
        github(self, scopes="repo, workflow")
        m = forgeaccess.measure("app")
        self.assertEqual(m["token"], "classic")
        self.assertTrue(m["has"]["workflows"])

    def test_a_repository_the_token_cannot_see_is_every_no(self):
        self.host({("GET", "/user"): (200, {"login": "bot"}, {})}, default=(404, {"message": "Not Found"}, {}))
        m = forgeaccess.measure("app")
        self.assertIn("will not show o/app", m["error"])
        self.assertFalse(any(m["has"].values()))

    def test_gitlab_reads_its_scopes_and_role(self):
        self.t = target(GL, "glpat-x")
        self.host({("GET", "/projects/o%2Fapp"): (200, {"permissions": {"project_access": {"access_level": 30}}}, {}),
                   ("GET", "/personal_access_tokens/self"): (200, {"scopes": ["read_api", "read_repository"]}, {})})
        has = forgeaccess.measure("app")["has"]
        self.assertTrue(has["code_read"] and has["pr_read"])
        self.assertFalse(has["push"] or has["pr_write"] or has["merge"])


class Override(Base):
    def setUp(self):
        super().setUp()
        github(self)
        forgeaccess.measure("app")

    def test_a_deny_takes_away_what_the_token_allows(self):
        self.assertEqual(forgeaccess.may("app", "pr_write"), (True, ""))
        self.pol = {"pr_write": "deny"}
        ok, why = forgeaccess.may("app", "pr_write")
        self.assertFalse(ok)
        self.assertIn("turned off for this project", why)

    def test_an_allow_never_gives_what_the_token_lacks(self):
        self.pol = {"issues_write": "allow"}
        ok, why = forgeaccess.may("app", "issues_write")
        self.assertFalse(ok)
        self.assertIn("Issues: Read and write", why)

    def test_merging_is_off_until_turned_on(self):
        self.assertFalse(forgeaccess.may("app", "merge")[0])
        self.pol = {"merge": "allow"}
        self.assertTrue(forgeaccess.may("app", "merge")[0])

    def test_the_briefing_says_what_it_may_and_what_to_ask_for(self):
        text = forgeaccess.briefing("app")
        self.assertIn("as bot", text)
        self.assertIn("You may: ", text)
        self.assertIn("Not: open, comment on, label and close issues; ask the person to give the token Issues: Read and write", text)
        self.assertIn("Not: merge pull requests (turned off for this project", text)

    def test_a_verb_is_refused_by_either_and_says_why(self):
        body, code = forgeaccess.run("app", "issue create", {"flags": {"title": "x"}})
        self.assertEqual(code, 403)
        self.assertIn("Issues: Read and write", body["error"])
        body, code = forgeaccess.run("app", "pr merge", {"pos": ["4"]})
        self.assertEqual(code, 403)
        body, code = forgeaccess.run("app", "pr nonsense", {})
        self.assertEqual(code, 400)


class Dialects(Base):
    def setUp(self):
        super().setUp()
        self.pol = {"merge": "allow"}

    def measured(self, forge):
        self.t = target(forge)
        Path(self.d, "forge-access").mkdir(exist_ok=True)
        Path(self.d, "forge-access", "app.json").write_text(json.dumps(
            {"at": 9e12, "kind": forge["kind"], "has": {a["id"]: True for a in forgeaccess.ABILITIES}}))

    def test_github_merges_with_a_put(self):
        self.measured(GH)
        h = self.host({("PUT", "/repos/o/app/pulls/4/merge"): (200, {"merged": True, "sha": "abcdef12"}, {})})
        body, code = forgeaccess.run("app", "pr merge", {"pos": ["4"], "flags": {"method": "squash"}})
        self.assertEqual((code, body["merged"]), (200, True))
        self.assertEqual(h.asked[-1][2], {"merge_method": "squash"})

    def test_gitea_merges_with_a_post_naming_the_way(self):
        self.measured(GT)
        h = self.host({("POST", "/repos/o/app/pulls/4/merge"): (200, {}, {})})
        body, code = forgeaccess.run("app", "pr merge", {"pos": ["4"]})
        self.assertEqual(code, 200)
        self.assertEqual(h.asked[-1][2], {"Do": "merge"})

    def test_gitlab_speaks_merge_requests_and_pipelines(self):
        self.measured(GL)
        h = self.host({("GET", "/projects/o%2Fapp/merge_requests"): (200, [{"iid": 3, "title": "t", "state": "opened",
                                                                          "source_branch": "f", "target_branch": "main"}], {}),
                       ("GET", "/projects/o%2Fapp/pipelines"): (200, [{"id": 9, "status": "failed", "ref": "main"}], {})})
        body, code = forgeaccess.run("app", "pr list", {})
        self.assertEqual((code, body[0]["number"], body[0]["head"]), (200, 3, "f"))
        body, code = forgeaccess.run("app", "run list", {})
        self.assertEqual(body[0]["conclusion"], "failure")
        self.assertTrue(all(p.startswith("/projects/o%2Fapp/") for _m, p, _d in h.asked))

    def test_what_a_host_has_no_word_for_is_refused_saying_so(self):
        self.measured(GL)
        self.host({})
        body, code = forgeaccess.run("app", "pr review", {"pos": ["3"], "flags": {"request-changes": True, "body": "x"}})
        self.assertEqual(code, 400)
        self.assertIn("GitLab has no request for changes", body["error"])
        self.measured(GT)
        body, code = forgeaccess.run("app", "run rerun", {"pos": ["5"]})
        self.assertIn("Gitea's API has no rerun", body["error"])

    def test_a_run_is_named_by_githubs_own_long_id(self):
        # GitHub's run ids are eleven digits and its job ids twelve.
        self.measured(GH)
        self.host({("GET", "/repos/o/app/actions/runs/40996557892/jobs"): (200, {"jobs": []}, {})})
        body, code = forgeaccess.run("app", "run log", {"pos": ["40996557892"]})
        self.assertEqual(code, 200, body)

    def test_only_numbers_and_branch_names_reach_a_path(self):
        self.measured(GH)
        self.host({})
        body, code = forgeaccess.run("app", "pr view", {"pos": ["../../admin"]})
        self.assertEqual(code, 400)
        body, code = forgeaccess.run("app", "pr create", {"flags": {"title": "t", "head": "a b?", "base": "main"}})
        self.assertIn("a branch name", body["error"])


if __name__ == "__main__":
    unittest.main()
