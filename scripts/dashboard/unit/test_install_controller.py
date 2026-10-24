"""A controller installed bare metal (R90 steps 4 and 5): nodes/install-controller.sh
is built on the provisioner's core (sourced, not copied), lays a release out
by the Dockerfile's own COPY lines so the image and the install cannot
drift, gives every process the environment the image's ENV gives the
container, writes the env file from a template that carries every setting
compose passes, and updates the way an image pull does: the new release's
own state gate asked first, the one before kept, and a rollback that puts
back the copy the newer build took before it migrated."""
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
INSTALLER = os.path.join(ROOT, "nodes", "install-controller.sh")
DASH = os.path.join(ROOT, "scripts", "dashboard")
SNAPS = os.path.join(DASH, "test", "upgrade")


def sh(body, env=None, root=""):
    """bash with the installer sourced for its functions, under a scratch
    prefix; nothing is root, and nothing outside the prefix is written."""
    pre = f'set -euo pipefail\nBB_CONTROLLER_LIB=1 . "{INSTALLER}"\n'
    e = dict(os.environ, BB_INSTALL_ROOT=root, NO_FETCH="1", **(env or {}))
    return subprocess.run(["bash", "-c", pre + body], capture_output=True, text=True, timeout=120,
                          check=False, env=e)


def dockerfile():
    return open(os.path.join(ROOT, "Dockerfile"), encoding="utf-8").read()


class BuiltOnTheProvisioner(unittest.TestCase):
    def test_its_core_is_sourced_and_nothing_runs(self):
        r = sh('load_core; echo "fam=$FAMILY init=$INIT"; '
               'for f in pkg_refresh pkg pkg_names docker_install svc_install svc_stop svc_restart '
               'preflight in_container ttyd_install docker_suite; do declare -F "$f" >/dev/null || echo "missing $f"; done')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("missing", r.stdout)
        self.assertRegex(r.stdout, r"fam=[a-z]+ init=")
        # Sourced, the provisioner asks nothing and checks nothing: no help
        # printed, no "run this with sudo", no "checking this machine".
        self.assertNotIn("usage:", r.stdout + r.stderr)
        self.assertNotIn("sudo", r.stderr)
        self.assertNotIn("checking this machine", r.stdout)

    def test_the_provisioner_run_is_as_it_was(self):
        r = subprocess.run(["bash", os.path.join(ROOT, "nodes", "provision-linux.sh")], capture_output=True,
                           text=True, timeout=30, check=False)
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage: sudo bash provision-linux.sh", r.stdout)

    def test_the_container_refusal_is_the_provisioners_test(self):
        text = open(INSTALLER, encoding="utf-8").read()
        self.assertIn("if in_container; then", text)
        self.assertIn("in_container() {", open(os.path.join(ROOT, "nodes", "provision-linux.sh"), encoding="utf-8").read())

    def test_with_no_arguments_it_says_how_and_changes_nothing(self):
        r = subprocess.run(["bash", INSTALLER], capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage: sudo bash install-controller.sh ACTION", r.stdout)

    def test_alternatives_take_the_first_that_installs(self):
        r = sh('pkg() { echo "try $1" >&3; [ "$1" = python3 ]; }; entry_install "python3.12|python3" 3>&1 && echo got')
        self.assertEqual(r.stdout.split(), ["try", "python3.12", "try", "python3", "got"])
        r = sh('pkg() { return 1; }; entry_install "a|b" || echo none')
        self.assertEqual(r.stdout.strip(), "none")


class LaidOutAsTheImage(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_every_copy_line_lands_where_the_image_puts_it(self):
        rel = os.path.join(self.root, "opt", "builderbot-releases", "1.2.3")
        os.makedirs(os.path.dirname(rel))
        r = sh(f'lay_out "{ROOT}" "{rel}" 1.2.3 abc123', root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        copies = re.findall(r"^COPY (\S+) (/opt/builderbot\S*)$", dockerfile(), re.M)
        self.assertGreater(len(copies), 10)
        for src, dest in copies:
            where = rel + dest[len("/opt/builderbot"):]
            if src.endswith("/"):
                for name in os.listdir(os.path.join(ROOT, src)):
                    self.assertTrue(os.path.lexists(os.path.join(where, name)), (src, name))
            elif "*" in src:
                self.assertTrue(os.listdir(where), src)
            else:
                self.assertTrue(os.path.isfile(where), (src, dest))
        self.assertTrue(os.access(os.path.join(rel, "scripts", "host-boot.sh"), os.X_OK))
        self.assertTrue(os.access(os.path.join(rel, "scripts", "bb"), os.X_OK))
        for f in ("nodes/install-controller.sh", "config/controller.env", "Dockerfile"):
            self.assertTrue(os.path.isfile(os.path.join(rel, f)), f)
        env = open(os.path.join(rel, "build.env"), encoding="utf-8").read()
        self.assertIn("BB_VERSION=1.2.3\n", env)
        self.assertIn("BB_IMAGE_REV=abc123\n", env)
        self.assertFalse(os.path.exists(rel + ".partial"))

    def test_flip_keeps_the_one_before(self):
        rels = os.path.join(self.root, "opt", "builderbot-releases")
        for v in ("1.0", "1.1", "1.2", "1.3", "1.4"):
            os.makedirs(os.path.join(rels, v))
        r = sh(f'for v in 1.0 1.1 1.2 1.3 1.4; do flip "{rels}/$v"; touch -d "@$((1700000000 + ${{v#1.}}))" "{rels}/$v"; done; '
               f'flip "{rels}/1.0"; prune; readlink "$OPT"; readlink "$RELEASES/.previous"; ls "$RELEASES"',
               root=self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout.split()
        self.assertEqual(out[0], f"{rels}/1.0")
        self.assertEqual(out[1], f"{rels}/1.4")
        # The one in use and the one before, and the newest three, are kept.
        self.assertEqual(sorted(out[2:]), ["1.0", "1.2", "1.3", "1.4"])

    def test_a_checkout_is_stamped_as_ci_stamps_an_image(self):
        r = sh(f'tree_stamp "{ROOT}"')
        ver, rev = r.stdout.split()
        target = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
        self.assertTrue(ver == target or re.fullmatch(re.escape(target) + r"-dev\.\d+\+[0-9a-f]{7}", ver), ver)
        self.assertRegex(rev, r"^[0-9a-f]{40}$")

    def test_a_release_archive_is_stamped_by_its_version_and_header(self):
        t = os.path.join(self.root, "tree")
        os.makedirs(t)
        with open(os.path.join(t, "VERSION"), "w") as f:
            f.write("0.9.0\n")
        with open(os.path.join(t, ".release-rev"), "w") as f:
            f.write("f" * 40 + "\n")
        r = sh(f'tree_stamp "{t}"')
        self.assertEqual(r.stdout.split(), ["0.9.0", "f" * 40])

    def test_the_images_pins_are_read_from_its_dockerfile(self):
        r = sh("dockerfile_arg TTYD_VERSION; dockerfile_arg NOVNC_SHA256")
        ttyd, sha = r.stdout.split()
        self.assertRegex(ttyd, r"^\d+\.\d+\.\d+$")
        self.assertRegex(sha, r"^[0-9a-f]{64}$")


class TheEnvironment(unittest.TestCase):
    # What the image's ENV sets that a machine of its own has no use for:
    # apt's, the container's ids, and the docker-exec wrappers' folder.
    CONTAINER_ALONE = {"DEBIAN_FRONTEND", "PUID", "PGID"}
    # Written per release into build.env, as the image stamps them.
    STAMPED = {"BB_IMAGE_REV", "BB_IMAGE_BUILT", "BB_VERSION"}

    def test_every_env_the_image_sets_is_set_here(self):
        names = set(re.findall(r"(?:^ENV |^\s+)([A-Z_][A-Z0-9_]*)=", dockerfile(), re.M))
        names -= {"PIPX_HOME", "PIPX_BIN_DIR"}           # a RUN line's own, not an ENV
        host = open(os.path.join(ROOT, "scripts", "lib", "host-env.sh"), encoding="utf-8").read()
        exported = set(re.findall(r"\b([A-Z_][A-Z0-9_]*)=", host.split("set +a", 1)[1]))
        missing = names - exported - self.CONTAINER_ALONE - self.STAMPED
        self.assertEqual(missing, set())

    def test_the_settings_reach_every_process(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "controller.env")
            with open(p, "w") as f:
                f.write('DASHBOARD_STATE=/x/config\nDASHBOARD_PORT=7700\nBANNER_TEXT="Back at six"\nBB_INSTALL=bare-metal\n')
            r = subprocess.run(["bash", "-c", f'. "{ROOT}/scripts/lib/host-env.sh"; '
                                'echo "$DASHBOARD_STATE|$DASHBOARD_PORT|$BANNER_TEXT|$BB_INSTALL|$WORKSPACE|$PATH"'],
                               capture_output=True, text=True, timeout=30, check=False,
                               env={"BB_CONTROLLER_ENV": p, "PATH": "/usr/bin:/bin"})
            state, port, banner, kind, ws, path = r.stdout.strip().split("|")
            self.assertEqual((state, port, banner, kind, ws),
                             ("/x/config", "7700", "Back at six", "bare-metal", "/srv/builderbot/projects"))
            self.assertTrue(path.startswith("/usr/local/lib/builderbot-controller/bin:"))

    def test_the_template_carries_every_setting_compose_passes(self):
        compose = open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8").read()
        svc = compose.split("\n  builderbot:", 1)[1]
        passed = {a for a, b in re.findall(r"^\s+([A-Z][A-Z0-9_]+):\s*\$\{([A-Z][A-Z0-9_]+)", svc, re.M) if a == b}
        tmpl = open(os.path.join(ROOT, "config", "controller.env"), encoding="utf-8").read()
        have = set(re.findall(r"^([A-Z][A-Z0-9_]+)=", tmpl, re.M))
        alone = set(re.search(r"Not here, the container's alone: ([A-Z_ ]+)", tmpl).group(1).split())
        self.assertEqual(passed - have - alone, set())
        self.assertEqual(alone & have, set())

    def test_the_env_file_is_written_once_and_kept(self):
        with tempfile.TemporaryDirectory() as d:
            stubs = 'chown() { :; }; id() { echo root; }; '
            r = sh(stubs + 'install -d "$ETC"; WORKSPACE_DIR=/data/projects; PORT=7700; env_file; '
                   'echo "BANNER_TEXT=\\"mine\\"" >> "$ENV_FILE"; env_file; cat "$ENV_FILE"', root=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("WORKSPACE=/data/projects\n", r.stdout)
            self.assertIn("DASHBOARD_PORT=7700\n", r.stdout)
            self.assertIn('BANNER_TEXT="mine"\n', r.stdout)
            self.assertNotIn("Added by an update", r.stdout)

    def test_an_update_adds_what_a_newer_template_has(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "etc", "builderbot-controller"))
            with open(os.path.join(d, "etc", "builderbot-controller", "controller.env"), "w") as f:
                f.write("TZ=Europe/Paris\n")
            r = sh('chown() { :; }; id() { echo root; }; env_file; cat "$ENV_FILE"', root=d)
            self.assertIn("TZ=Europe/Paris\n", r.stdout)
            self.assertIn("# Added by an update, at its default:\n# DASHBOARD_PORT=7680\n", r.stdout)


class TheWall(unittest.TestCase):
    """What the installer writes for bb-session (R90 step 7): every folder of
    the controller's the env file names, each once and none inside another,
    and the loopback ports for the controller's account and root alone."""

    def test_written_from_the_env_file(self):
        with tempfile.TemporaryDirectory() as d:
            etc = os.path.join(d, "etc", "builderbot-controller")
            os.makedirs(etc)
            with open(os.path.join(etc, "controller.env"), "w") as f:
                f.write(f"DASHBOARD_STATE={d}/var/lib/builderbot-controller/config\n"
                        f"BUILDER_HOME={d}/var/lib/builderbot-controller/home\n"
                        "SDK_ROOT=/mnt/sdk/\nWORKSPACE=/srv/builderbot/projects\n"
                        f"BB_SECRETS_DIR={d}/etc/builderbot-controller/secrets\n"
                        "SSH_AUTH_SOCK=/run/builderbot-controller/ssh-agent.sock\n")
            r = sh('id() { echo 990; }; JOBS_USER=bb; wall_write; cat "$WALL_FILE"; cat "$WALL_NFT"', root=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            cover = re.search(r"^COVER=(.*)$", r.stdout, re.M).group(1).split(":")
            self.assertEqual(sorted(cover), sorted([
                f"{d}/var/lib/builderbot-controller", f"{d}/etc/builderbot-controller", "/run/builderbot",
                "/run/builderbot-key",
                "/run/builderbot-controller", "/mnt/sdk", "/srv/builderbot/projects"]))
            self.assertIn("ACCOUNT=builderbot\nJOBS_USER=bb\n", r.stdout)
            self.assertIn("PORTS=7681,7682\n", r.stdout)
            self.assertIn("tcp dport { 7681, 7682 } meta skuid 990 accept", r.stdout)
            self.assertIn("tcp dport { 7681, 7682 } reject with tcp reset", r.stdout)
            self.assertIn("table inet builderbot_wall {", r.stdout)

    def test_the_table_is_the_one_bb_session_asks_for(self):
        text = open(os.path.join(ROOT, "nodes", "bb-session"), encoding="utf-8").read()
        self.assertIn('WALL_TABLE = "builderbot_wall"', text)
        self.assertIn('WALL = "/etc/bb-session.wall"', text)
        inst = open(INSTALLER, encoding="utf-8").read()
        self.assertIn("WALL_TABLE=builderbot_wall", inst)
        self.assertIn('WALL_FILE="$P/etc/bb-session.wall"', inst)

    def test_the_wall_is_up_before_the_node_enrolls(self):
        text = open(INSTALLER, encoding="utf-8").read()
        body = text[text.index("cmd_install() {"):]
        body = body[:body.index("\n}\n")]
        self.assertLess(body.index("wall_write"), body.index("own_node"))


class TheImagesOtherTools(unittest.TestCase):
    def test_everything_the_image_fetches_is_fetched_here_too(self):
        text = open(INSTALLER, encoding="utf-8").read()
        body = text[text.index("extras() {"):text.index("\n}\n", text.index("extras() {"))]
        for tool in ("hadolint", "yq", "actionlint", "ruff", "uv", "mise", "playwright", "web-ext", "cloudflared"):
            self.assertIn(tool, dockerfile(), tool)
            self.assertIn(tool, body, tool)
        self.assertIn('ttyd_install "$(dockerfile_arg TTYD_VERSION)"', text)
        self.assertIn("NOVNC_SHA256", text)


class Updates(unittest.TestCase):
    """The update's gate is the new release's own stateversion.py, asked of
    every release's /config snapshot the upgrade suite starts on."""

    def unpack(self, ver, d):
        with tarfile.open(os.path.join(SNAPS, ver, "config.tar.gz")) as t:
            t.extractall(d, filter="data")
        return os.path.join(d, "config")

    def gate(self, state, d, ver="9.9.9"):
        envf = os.path.join(d, "controller.env")
        with open(envf, "w") as f:
            f.write(f"DASHBOARD_STATE={state}\n")
        return sh(f'ENV_FILE="{envf}"; gate "{ROOT}" {ver}')

    def test_every_supported_release_is_one_an_update_starts_on(self):
        vers = sorted(os.listdir(SNAPS))
        self.assertGreater(len(vers), 3)
        for ver in vers:
            with tempfile.TemporaryDirectory() as d:
                r = self.gate(self.unpack(ver, d), d)
                self.assertEqual(r.returncode, 0, (ver, r.stderr))

    def test_a_state_newer_than_the_release_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            state = self.unpack(sorted(os.listdir(SNAPS))[-1], d)
            with open(os.path.join(state, "state.json"), "w") as f:
                json.dump({"state": 9999, "by": "99.0.0"}, f)
            r = self.gate(state, d)
            self.assertEqual(r.returncode, 78)
            self.assertIn("Downgrades are not supported", r.stderr)

    def test_the_update_asks_the_gate_before_anything_moves(self):
        text = open(INSTALLER, encoding="utf-8").read()
        body = text[text.index("cmd_update() {"):]
        body = body[:body.index("\n}\n")]
        self.assertLess(body.index('gate "$t" "$ver"'), body.index("lay_out "))
        self.assertLess(body.index("lay_out "), body.index("flip "))


class Rollback(unittest.TestCase):
    def run_sv(self, *argv):
        return subprocess.run(["python3", os.path.join(DASH, "stateversion.py"), *argv], capture_output=True,
                              text=True, timeout=60, check=False)

    def test_the_copy_before_the_migration_is_put_back(self):
        with tempfile.TemporaryDirectory() as state:
            # What a newer build left: the state moved on, a record it added,
            # a log, and the copy it took before it migrated.
            for name, text in (("state.json", '{"state": 7, "by": "2.0.0"}'), ("users.json", "new"),
                               ("added-by-2.json", "x"), ("logs/builderbot.log", "log")):
                os.makedirs(os.path.dirname(os.path.join(state, name)), exist_ok=True)
                with open(os.path.join(state, name), "w") as f:
                    f.write(text)
            before = os.path.join(state, "backups", "before-2.0.0")
            os.makedirs(os.path.join(before, "signing"))
            for name, text in (("state.json", '{"state": 3, "by": "1.0.0"}'), ("users.json", "old")):
                with open(os.path.join(before, name), "w") as f:
                    f.write(text)
            with open(os.path.join(before, "NOT-COPIED.txt"), "w") as f:
                f.write("Left out of this copy, unreadable to the dashboard's account:\n  signing/key.jks\n")
            os.makedirs(os.path.join(state, "signing"))
            with open(os.path.join(state, "signing", "key.jks"), "w") as f:
                f.write("root's")
            r = self.run_sv("restore", state, "2.0.0")
            self.assertEqual(r.returncode, 0, r.stderr)
            read = lambda *p: open(os.path.join(state, *p), encoding="utf-8").read()  # noqa: E731
            self.assertEqual(read("users.json"), "old")
            self.assertIn('"state": 3', read("state.json"))
            self.assertFalse(os.path.exists(os.path.join(state, "added-by-2.json")))
            self.assertEqual(read("logs", "builderbot.log"), "log")           # left out on purpose, left
            self.assertEqual(read("signing", "key.jks"), "root's")           # unreadable to the copy, kept
            aside = [d for d in os.listdir(os.path.join(state, "backups")) if d.startswith("rolled-back-")]
            self.assertEqual(len(aside), 1)
            self.assertTrue(os.path.isfile(os.path.join(state, "backups", aside[0], "added-by-2.json")))
            self.assertFalse(os.path.exists(os.path.join(state, "NOT-COPIED.txt")))

    def test_no_copy_moves_nothing(self):
        with tempfile.TemporaryDirectory() as state:
            with open(os.path.join(state, "users.json"), "w") as f:
                f.write("now")
            r = self.run_sv("restore", state, "2.0.0")
            self.assertEqual(r.returncode, 1)
            self.assertIn("no copy", r.stderr)
            self.assertEqual(os.listdir(state), ["users.json"])

    def test_the_rollback_restores_only_when_the_older_build_refuses(self):
        text = open(INSTALLER, encoding="utf-8").read()
        body = text[text.index("cmd_rollback() {"):]
        body = body[:body.index("\n}\n")]
        self.assertIn('if ! gate "$prev" "$oldver"', body)
        self.assertLess(body.index("svc_stop"), body.index("restore"))
        self.assertLess(body.index("restore"), body.index('flip "$prev"'))


if __name__ == "__main__":
    unittest.main()
