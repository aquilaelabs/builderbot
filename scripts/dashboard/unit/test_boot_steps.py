"""The controller's boot as steps both installs take (R90 step 3): lib/boot.sh,
sourced by the container's entrypoint and by a bare-metal install's
host-boot.sh, each step the same in both, in the same order; what only the
container does (remapping builder, the timezone, gosu) stays in the
entrypoint. The root helpers reached through sudo take a bare-metal
install's state folder only from an env file root owns."""
import os
import re
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SCRIPTS = os.path.join(ROOT, "scripts")


def sh(body, env=None):
    """bash with common.sh and boot.sh sourced from this tree; log/warn
    print, nothing is root."""
    pre = (f'set -euo pipefail\n. "{SCRIPTS}/lib/common.sh"\n. "{SCRIPTS}/lib/boot.sh"\n')
    return subprocess.run(["bash", "-c", pre + body], capture_output=True, text=True, timeout=60,
                          check=False, env=dict(os.environ, **(env or {})))


def steps(path, fn="main"):
    """The step names a boot's main() calls, in order."""
    text = open(path, encoding="utf-8").read()
    body = text[text.index(f"{fn}() {{"):]
    body = body[: body.index("\n}\n")]
    names = ("stash_secrets", "BOOT_READY_FILE", "state_gate", "setup_logging", "banner",
             "setup_timezone", "remap_user", "seed_home", "sock_dir", "persist_android_downloads",
             "setup_ssh_agent", "record_image", "run_hooks", "boot_ready", "unset", "exec")
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("#"):
            continue
        for n in names:
            if re.search(rf"(^|[\s\"$]){re.escape(n)}\b", line) and n not in out:
                out.append(n)
    return out


class Order(unittest.TestCase):
    def test_the_container_boots_as_it_always_has(self):
        self.assertEqual(steps(os.path.join(SCRIPTS, "entrypoint.sh")), [
            "stash_secrets", "BOOT_READY_FILE", "state_gate", "setup_logging", "banner",
            "setup_timezone", "remap_user", "seed_home", "persist_android_downloads", "setup_ssh_agent",
            "record_image", "run_hooks", "boot_ready", "unset", "exec"])

    def test_a_bare_metal_boot_takes_the_same_steps_without_the_containers_own(self):
        self.assertEqual(steps(os.path.join(SCRIPTS, "host-boot.sh")), [
            "stash_secrets", "BOOT_READY_FILE", "state_gate", "setup_logging", "banner",
            "seed_home", "sock_dir", "setup_ssh_agent", "record_image", "run_hooks", "boot_ready",
            "unset", "exec"])

    def test_the_steps_live_once(self):
        # Defined in boot.sh and nowhere else: a fix to one is a fix to both.
        for fn in ("stash_secrets", "setup_ssh_agent", "seed_home", "run_hooks", "setup_logging",
                   "record_image", "state_gate", "resolve_command"):
            for f in ("entrypoint.sh", "host-boot.sh"):
                self.assertNotIn(f"\n{fn}() {{", open(os.path.join(SCRIPTS, f), encoding="utf-8").read(), (fn, f))
            self.assertIn(f"\n{fn}() {{", open(os.path.join(SCRIPTS, "lib", "boot.sh"), encoding="utf-8").read(), fn)

    def test_only_the_container_remaps_and_uses_gosu(self):
        host = open(os.path.join(SCRIPTS, "host-boot.sh"), encoding="utf-8").read()
        self.assertNotIn("remap_user", host)
        self.assertNotIn("gosu", host.split("set -euo pipefail", 1)[1])
        self.assertIn("setpriv --reuid=", host)


class Steps(unittest.TestCase):
    def test_secrets_stashed_from_the_folder_named_and_shielded(self):
        with tempfile.TemporaryDirectory() as d:
            sec, run = os.path.join(d, "secrets"), os.path.join(d, "run")
            os.mkdir(sec)
            with open(os.path.join(sec, "npm.env"), "w") as f:
                f.write("NPM_TOKEN=npm_abcdefghijklmnopqrstu\n")
            r = sh('stash_secrets; cat "$BB_RUN_DIR/secrets.env"; grep -c REDACTED "$BB_RUN_DIR/redact.sed"; '
                   'stat -c %a "$BB_RUN_DIR" "$BB_RUN_DIR/secrets.env"',
                   {"BB_SECRETS_DIR": sec, "BB_RUN_DIR": run})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("secrets: loaded 1 value(s) [NPM_TOKEN]", r.stdout)
            self.assertIn("NPM_TOKEN=npm_abcdefghijklmnopqrstu", r.stdout)
            self.assertIn("\n700\n600", r.stdout)

    def test_no_folder_is_said(self):
        with tempfile.TemporaryDirectory() as d:
            r = sh("stash_secrets", {"BB_SECRETS_DIR": os.path.join(d, "nope"), "BB_RUN_DIR": d + "/run"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(f"no {d}/nope and no secret variables set", r.stdout)

    def test_hooks_run_from_the_state_named(self):
        with tempfile.TemporaryDirectory() as d:
            hooks = os.path.join(d, "startup.d")
            os.mkdir(hooks)
            for name, body in (("10-mine.sh", "echo ran-mine"), ("20-off.disabled.sh", "echo ran-off"),
                               ("30-root.root.sh", "echo ran-root")):
                with open(os.path.join(hooks, name), "w") as f:
                    f.write(f"#!/bin/sh\n{body}\n")
            r = sh("run_hooks", {"DASHBOARD_STATE": d})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("ran-mine", r.stdout)
            self.assertNotIn("ran-off", r.stdout)
            self.assertIn("skipping 30-root.root.sh (needs root", r.stdout)

    def test_logs_and_ledger_follow_the_state(self):
        r = sh("bb_log_dir; echo; bb_image_log", {"DASHBOARD_STATE": "/var/lib/x/config", "BB_LOG_DIR": ""})
        self.assertEqual(r.stdout.split("\n")[:2], ["/var/lib/x/config/logs", "/var/lib/x/config/image-log.tsv"])
        r = sh("bb_log_dir; echo; bb_image_log", {"DASHBOARD_STATE": ""})
        self.assertEqual(r.stdout.split("\n")[:2], ["/config/logs", "/config/image-log.tsv"])

    def test_as_account_is_setpriv_or_gosu(self):
        stub = 'setpriv() { echo "setpriv $*"; }; gosu() { echo "gosu $*"; }; '
        r = sh(stub + "as_account true", {"BB_DROP": "setpriv", "BB_ACCOUNT": "builderbot", "PGID": "990"})
        self.assertEqual(r.stdout.strip(), "setpriv --reuid=builderbot --regid=990 --init-groups true")
        r = sh(stub + "as_account true", {"BB_DROP": "", "BB_ACCOUNT": ""})
        self.assertEqual(r.stdout.strip(), "gosu builder true")

    def test_the_command_handed_off(self):
        r = sh("resolve_command | tr '\\0' ' '; echo; resolve_command bash | tr '\\0' ' '")
        self.assertEqual(r.stdout.split("\n")[:2], ["/opt/builderbot/scripts/supervisor.sh ", "bash -l "])


class RootState(unittest.TestCase):
    def env_file(self, d, text):
        p = os.path.join(d, "controller.env")
        with open(p, "w") as f:
            f.write(text)
        return p

    def test_the_container_without_an_env_file(self):
        r = sh("bb_root_state", {"BB_CONTROLLER_ENV": "/nonexistent/controller.env"})
        self.assertEqual(r.stdout, "/config")

    def test_an_env_file_root_does_not_own_is_not_believed(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.env_file(d, "DASHBOARD_STATE=/elsewhere\n")
            r = sh("bb_root_state", {"BB_CONTROLLER_ENV": p})
            self.assertEqual(r.stdout, "/config")

    def test_one_root_owns_and_nobody_else_writes(self):
        with tempfile.TemporaryDirectory() as d:
            p = self.env_file(d, "# a comment\nDASHBOARD_STATE=\"/var/lib/builderbot-controller/config\"\n")
            stat = 'stat() { case "$2" in %u) echo 0 ;; %a) echo "${MODE}" ;; esac; }; '
            r = sh(stat + "bb_root_state", {"BB_CONTROLLER_ENV": p, "MODE": "640"})
            self.assertEqual(r.stdout, "/var/lib/builderbot-controller/config")
            r = sh(stat + "bb_root_state", {"BB_CONTROLLER_ENV": p, "MODE": "664"})
            self.assertEqual(r.stdout, "/config")

    def test_the_root_helpers_read_it(self):
        for f in ("deploy-key", "mint-runner-token"):
            text = open(os.path.join(SCRIPTS, f), encoding="utf-8").read()
            self.assertRegex(text, r'\nSTORE="\$\(bb_root_state\)/', f)



class KeyBeforeHooks(unittest.TestCase):
    """The install key is written before the hooks run, in both boots: hook
    15 starts the dashboard, which reads the key as it starts (B388)."""
    def test_the_key_before_the_hooks(self):
        for f in ("entrypoint.sh", "host-boot.sh"):
            text = open(os.path.join(SCRIPTS, f), encoding="utf-8").read()
            body = text[text.index("main() {"):]
            calls = [ln.strip() for ln in body.splitlines() if ln.strip() in ("install_key_file", "run_hooks")]
            self.assertEqual(calls, ["install_key_file", "run_hooks"], f)


class DashboardShielded(unittest.TestCase):
    """The hook that starts the dashboard starts it without the shielded
    secrets the hooks run with (B389): its own lines, run here."""
    def test_the_dashboard_starts_without_them(self):
        hook = open(os.path.join(SCRIPTS, "startup.d", "15-dashboard.sh"), encoding="utf-8").read()
        lines = [ln for ln in hook.splitlines() if ln.startswith(("unset_args=", "for v in ${BB_SHIELDED"))]
        self.assertEqual(len(lines), 2, lines)
        self.assertIn('nohup env "${unset_args[@]}" DASHBOARD_PORT=', hook)
        r = sh("\n".join(lines) + '\nenv "${unset_args[@]}" env', {"NPM_TOKEN": "npm_" + "x" * 20, "INSTALL_KEY": "k" * 32})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("NPM_TOKEN=", r.stdout)
        self.assertNotIn("INSTALL_KEY=", r.stdout)
        self.assertIn("BB_SHIELDED=", r.stdout)


class InstallKey(unittest.TestCase):
    """install_key_file under set -u (the boot's own): an install with a key
    and no previous one starts, and one with both keeps both (R126)."""
    def run_it(self, env):
        d = tempfile.mkdtemp()
        body = (f'eval "$(declare -f install_key_file | sed "s#/run/builderbot-key#{d}/key#")"\n'
                'BB_ACCOUNT=$(id -un); install_key_file; ls ' + d)
        return sh(body, env), d

    def test_a_key_and_no_previous(self):
        r, d = self.run_it({"INSTALL_KEY": "k" * 32})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(os.listdir(d)), ["key"])

    def test_a_key_and_the_one_before(self):
        r, d = self.run_it({"INSTALL_KEY": "k" * 32, "INSTALL_KEY_PREVIOUS": "p" * 32})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(open(os.path.join(d, "key-previous")).read(), "p" * 32)


class MadeKey(unittest.TestCase):
    """No INSTALL_KEY: the install makes its own (R154), in the secrets folder
    when it can write there, else beside the state, and moves it into the
    secrets folder once that can take it; a second start keeps it."""
    def run_it(self, secrets, state):
        body = ('BB_ACCOUNT=$(id -un); install_key_made; '
                'echo "$BB_INSTALL_KEY_IN $BB_INSTALL_KEY_DIR $BB_SIGNING_SECRET_FILE"')
        r = sh(body, {"BB_SECRETS_DIR": secrets, "DASHBOARD_STATE": state})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()[-1].split()

    def test_made_in_the_secrets_folder_and_kept(self):
        d = tempfile.mkdtemp()
        sec, st = os.path.join(d, "secrets"), os.path.join(d, "config")
        os.makedirs(sec)
        os.makedirs(st)
        where, kd, kf = self.run_it(sec, st)
        self.assertEqual((where, kd, kf), ("secrets", os.path.join(sec, "install-key"), os.path.join(sec, "install-key", "key")))
        key = open(kf).read()
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertEqual(os.stat(kd).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(kf).st_mode & 0o777, 0o600)
        self.run_it(sec, st)
        self.assertEqual(open(kf).read(), key)
        self.assertFalse(os.path.exists(os.path.join(st, ".install-key")))

    def test_beside_the_state_with_no_secrets_folder_then_moved(self):
        d = tempfile.mkdtemp()
        sec, st = os.path.join(d, "secrets"), os.path.join(d, "config")
        os.makedirs(st)
        where, kd, kf = self.run_it(sec, st)
        self.assertEqual((where, kd), ("state", os.path.join(st, ".install-key")))
        key = open(kf).read()
        os.makedirs(sec)
        where, kd, kf = self.run_it(sec, st)
        self.assertEqual(where, "secrets")
        self.assertEqual(open(kf).read(), key)
        self.assertFalse(os.path.exists(os.path.join(st, ".install-key")))

    def adopt(self, sec, env):
        d = tempfile.mkdtemp()
        body = (f'eval "$(declare -f install_key_file | sed "s#/run/builderbot-key#{d}/key#")"\n'
                'BB_ACCOUNT=$(id -un); install_key_file; echo "$BB_INSTALL_KEY_IN $BB_INSTALL_KEY_ADOPTED"')
        r = sh(body, {"BB_SECRETS_DIR": sec, "DASHBOARD_STATE": d, **env})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()[-1].split()

    def test_a_set_key_is_copied_into_the_secrets_folder(self):
        sec = tempfile.mkdtemp()
        self.assertEqual(self.adopt(sec, {"INSTALL_KEY": "k" * 32, "INSTALL_KEY_PREVIOUS": "p" * 32}), ["env", "yes"])
        self.assertEqual(open(os.path.join(sec, "install-key", "key")).read(), "k" * 32)
        self.assertEqual(open(os.path.join(sec, "install-key", "key-previous")).read(), "p" * 32)
        # Taken out of the environment, the next start carries on with it.
        r = sh('BB_ACCOUNT=$(id -un); install_key_made; echo "$BB_INSTALL_KEY_IN"',
               {"BB_SECRETS_DIR": sec, "DASHBOARD_STATE": tempfile.mkdtemp()})
        self.assertEqual(r.stdout.splitlines()[-1], "secrets")
        self.assertEqual(open(os.path.join(sec, "install-key", "key")).read(), "k" * 32)

    def test_another_key_in_the_folder_is_said_and_left(self):
        sec = tempfile.mkdtemp()
        os.makedirs(os.path.join(sec, "install-key"))
        open(os.path.join(sec, "install-key", "key"), "w").write("o" * 32)
        self.assertEqual(self.adopt(sec, {"INSTALL_KEY": "k" * 32}), ["env", "other"])
        self.assertEqual(open(os.path.join(sec, "install-key", "key")).read(), "o" * 32)

    def test_never_copied_beside_the_state(self):
        self.assertEqual(self.adopt(os.path.join(tempfile.mkdtemp(), "none"), {"INSTALL_KEY": "k" * 32}), ["env", "no"])

    def test_a_set_key_makes_none(self):
        d = tempfile.mkdtemp()
        body = (f'eval "$(declare -f install_key_file | sed "s#/run/builderbot-key#{d}/key#")"\n'
                'BB_ACCOUNT=$(id -un); install_key_file; echo "$BB_INSTALL_KEY_IN"; ls ' + d)
        r = sh(body, {"INSTALL_KEY": "k" * 32, "BB_SECRETS_DIR": os.path.join(d, "no-secrets"), "DASHBOARD_STATE": d})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split()[-2:], ["env", "key"])

if __name__ == "__main__":
    unittest.main()
