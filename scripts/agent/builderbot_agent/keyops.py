"""What the controller's signing keys need a jdk or build-tools for, done on
the project's node (R106, the operator 22 Oct: the controller runs nothing).

The sign-key job (work.py's sign_key) runs one of these with this node's own
toolchain store: a keystore checked (inspect), a key made (generate), a key
wrapped under a backup's password (wrap), the proof of a rotation (rotate),
or a release's APK signed (release). The keystore and its passwords arrive
over the agent's channel for that job alone and leave as the answer, never
written anywhere but a 0700 directory of the enrolled account that the job
removes whatever happens; every file in it is 0600, and a password reaches
the tool in its environment (keytool's :env, apksigner's env:), never argv.

Each function takes that directory (`work`), the environment (`env`) and the
Popen keywords that make the child the enrolled account (`who`), and answers
its result and an error, "" when there is none.
"""
import glob
import os
import re
import subprocess

PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+")


def build_tools(store):
    """{zipalign, apksigner, aapt2} from the store's newest build-tools that
    holds all three, or {}."""
    bt = sorted(glob.glob(os.path.join(store or "", "android", "build-tools", "*")),
                key=lambda d: [int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", os.path.basename(d))])
    for d in reversed(bt):
        got = {n: os.path.join(d, n) for n in ("zipalign", "apksigner", "aapt2")}
        if all(os.access(p, os.X_OK) for p in got.values()):
            return got
    return {}


def tools(store, need_build_tools):
    """(tools, missing): the store's keytool, the java it runs on and, when
    asked, its build-tools; `missing` names the toolchain to install, in
    the Library's words, or is ""."""
    jdk = os.path.join(store or "", "jdk")
    out = {"keytool": os.path.join(jdk, "bin", "keytool"),
           "env": {"JAVA_HOME": jdk, "PATH": os.path.join(jdk, "bin") + os.pathsep + os.environ.get("PATH", "")}}
    if not store or not os.access(out["keytool"], os.X_OK):
        return {}, "jdk"
    if need_build_tools:
        bt = build_tools(store)
        if not bt:
            return {}, "android:build-tools"
        out.update(bt)
    return out, ""


def private(work, name, data, who=None):
    """`data` into `work`/`name`, 0600, the enrolled account's."""
    path = os.path.join(work, name)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    if who:
        os.chown(path, who["user"], who["group"])
    return path


def _run(argv, env, work, who, timeout=120):
    """(exit code, what it said) or (None, why it did not run)."""
    try:
        p = subprocess.run(argv, env=env, cwd=work, capture_output=True, text=True,
                           timeout=timeout, check=False, **(who or {}))
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def _last(said, code):
    lines = [ln for ln in (said or "").splitlines() if ln.strip()]
    return lines[-1][:200] if lines else f"exit {code}"


def inspect(kt, blob, store_pass, alias, *, work, env, who=None, name="check"):
    """(alias, store type, SHA-256, error) for a keystore, asked of keytool.
    An empty alias picks the store's only entry; a store holding several
    asks for one by name rather than guessing which key to sign with."""
    ks = private(work, name, blob, who)
    argv = [kt, "-list", "-v", "-keystore", ks, "-storepass:env", "BB_SIGN_PASS"]
    if alias:
        argv += ["-alias", alias]
    code, out = _run(argv, dict(env, BB_SIGN_PASS=store_pass), work, who, 60)
    os.unlink(ks)
    if code is None:
        return "", "", "", f"keytool did not run: {out}"
    if code != 0:
        if re.search(r"password was incorrect|Keystore was tampered|integrity", out, re.I):
            return "", "", "", "the keystore's password is not that"
        if alias and re.search(r"does not exist", out, re.I):
            return "", "", "", f"the keystore holds no key named {alias}"
        return "", "", "", "keytool could not read it: " + _last(out, code)
    names = re.findall(r"^Alias name:\s*(.+)$", out, re.M)
    if not alias:
        if len(names) != 1:
            return "", "", "", (f"the keystore holds {len(names)} keys ({', '.join(names[:6])}): "
                                "name the one to sign with")
        alias = names[0].strip()
    kind = (re.search(r"^Keystore type:\s*(\S+)", out, re.M) or [None, ""])[1]
    sha = (re.search(r"SHA256:\s*([0-9A-F:]{95})", out) or [None, ""])[1]
    if "PrivateKeyEntry" not in out:
        return "", "", "", f"{alias} is a certificate, not a key: it cannot sign anything"
    return alias, kind, sha, ""


def generate(kt, alias, cn, password, *, work, env, who=None):
    """(PKCS12 bytes, error): a new RSA 4096 key good for ten thousand days,
    under `password` as its store and key password both."""
    ks = os.path.join(work, "new.p12")
    code, out = _run([kt, "-genkeypair", "-keystore", ks, "-storetype", "PKCS12",
                      "-storepass:env", "BB_SIGN_PASS", "-alias", alias, "-keyalg", "RSA",
                      "-keysize", "4096", "-validity", "10000", "-dname", f"CN={cn}"],
                     dict(env, BB_SIGN_PASS=password), work, who, 120)
    if code is None:
        return b"", f"keytool did not run: {out}"
    if code != 0 or not os.path.isfile(ks):
        return b"", "keytool could not make it: " + _last(out, code)
    with open(ks, "rb") as f:
        return f.read(), ""


def wrap(kt, blob, store_pass, key_pass, alias, new_pass, *, work, env, who=None):
    """(PKCS12 bytes, error): the keystore's key under `new_pass` as its
    store and key password both, by keytool -importkeystore (R111)."""
    src, dst = private(work, "src", blob, who), os.path.join(work, "dst.p12")
    code, out = _run([kt, "-importkeystore", "-noprompt", "-srckeystore", src, "-srcstorepass:env", "BB_SRC_PASS",
                      "-srckeypass:env", "BB_SRC_KEY", "-srcalias", alias, "-destkeystore", dst,
                      "-deststoretype", "PKCS12", "-deststorepass:env", "BB_NEW_PASS", "-destkeypass:env", "BB_NEW_PASS"],
                     dict(env, BB_SRC_PASS=store_pass, BB_SRC_KEY=key_pass or store_pass, BB_NEW_PASS=new_pass),
                     work, who, 60)
    if code is None:
        return b"", f"keytool did not run: {out}"
    if code != 0 or not os.path.isfile(dst):
        return b"", "keytool could not wrap it: " + _last(out, code)
    with open(dst, "rb") as f:
        return f.read(), ""


def rotate(apksigner, old, new, *, work, env, who=None):
    """(proof bytes, error): apksigner's proof that `new` takes over from
    `old`, each {keystore (bytes), alias, store_pass, key_pass}."""
    o, n = private(work, "old", old["keystore"], who), private(work, "new", new["keystore"], who)
    out = os.path.join(work, "lineage")
    code, said = _run([apksigner, "rotate", "--out", out,
                       "--old-signer", "--ks", o, "--ks-key-alias", old["alias"],
                       "--ks-pass", "env:BB_OLD_KS", "--key-pass", "env:BB_OLD_KEY",
                       "--new-signer", "--ks", n, "--ks-key-alias", new["alias"],
                       "--ks-pass", "env:BB_NEW_KS", "--key-pass", "env:BB_NEW_KEY"],
                      dict(env, BB_OLD_KS=old["store_pass"], BB_OLD_KEY=old.get("key_pass") or old["store_pass"],
                           BB_NEW_KS=new["store_pass"], BB_NEW_KEY=new.get("key_pass") or new["store_pass"]),
                      work, who, 120)
    if code is None:
        return b"", f"apksigner did not run: {said}"
    if code != 0 or not os.path.isfile(out):
        return b"", "apksigner could not make the proof: " + _last(said, code)
    with open(out, "rb") as f:
        return f.read(), ""


def package_of(aapt2, apk, *, env, work, who=None):
    """The package an APK declares, read with aapt2, or ""."""
    code, said = _run([aapt2, "dump", "packagename", apk], env, work, who, 60)
    got = said.splitlines()[0].strip() if code == 0 and said else ""
    return got if PACKAGE.fullmatch(got) else ""


def sign_apk(tl, src, out, key, prev=None, lineage=b"", *, work, env, who=None):
    """({cert, schemes}, error): `src` zipaligned, signed with `key`
    ({keystore, alias, store_pass, key_pass, sha256}) and, for a rotated
    key, the key it replaced first with the proof, verified, and its
    certificate checked against the one kept, into `out`."""
    ks = private(work, "key", key["keystore"], who)
    env = dict(env, BB_KS_PASS=str(key.get("store_pass") or ""),
               BB_KEY_PASS=str(key.get("key_pass") or key.get("store_pass") or ""))
    first, tail = [], []
    if prev and lineage:
        pks, lin = private(work, "previous", prev["keystore"], who), private(work, "lineage", lineage, who)
        env.update(BB_PREV_KS=str(prev.get("store_pass") or ""),
                   BB_PREV_KEY=str(prev.get("key_pass") or prev.get("store_pass") or ""))
        first = ["--ks", pks, "--ks-key-alias", str(prev.get("alias") or ""),
                 "--ks-pass", "env:BB_PREV_KS", "--key-pass", "env:BB_PREV_KEY", "--next-signer"]
        tail = ["--lineage", lin, "--rotation-min-sdk-version", "28"]
    aligned = os.path.join(work, "aligned.apk")
    for argv, what in (([tl["zipalign"], "-p", "-f", "4", src, aligned], "zipalign"),
                       ([tl["apksigner"], "sign", *first, "--ks", ks, "--ks-key-alias", str(key.get("alias") or ""),
                         "--ks-pass", "env:BB_KS_PASS", "--key-pass", "env:BB_KEY_PASS", *tail,
                         "--out", out, aligned], "apksigner sign")):
        code, said = _run(argv, env, work, who, 600)
        if code is None:
            return {}, f"{what} did not run: {said}"
        if code != 0:
            return {}, f"{what} failed: " + _last(said, code)
    code, said = _run([tl["apksigner"], "verify", "--verbose", "--print-certs", out], env, work, who, 600)
    if code != 0:
        return {}, "apksigner verify failed: " + _last(said, code)
    m = re.search(r"SHA-256 digest:\s*([0-9a-fA-F]{64})", said)
    cert = m.group(1).upper() if m else ""
    want = str(key.get("sha256") or "").replace(":", "").upper()
    if not cert or (want and cert != want):
        return {}, "the signed APK carries another certificate than the key that was kept"
    return {"cert": cert, "schemes": re.findall(r"Verified using (v\d(?:\.\d)?) scheme[^:]*:\s*true", said)}, ""
