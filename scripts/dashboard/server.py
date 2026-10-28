#!/usr/bin/env python3
"""BuilderBot dashboard: status, project list and bb macros over HTTP.

Deliberately stdlib-only. This runs inside a container whose whole premise is
that it gets rebuilt often; a dashboard that drags in a web framework would be
one more thing to keep current, and http.server is more than adequate for one
operator on a LAN.

The terminals are BuilderBot's own (R133): a websocket at /termws, a pty
here (termws.local) or carried signed to a node's screen relay (termws.node).
"""
import base64
import contextlib
from html import escape as html_escape
import gzip
import datetime
import hashlib
import hmac
import atexit
import collections
import json
import os
import sys
import re
import selectors
import signal
import shlex
import socket
import sqlite3
import subprocess
import threading
import traceback
import time

# Beside this file. Imported up here rather than with the modules below,
# because write_json is defined from it before any of those load.
import statefile
import agents
from names import PROJECT_NAME, agent_sessions, claude_session, running_session, tmux_name   # noqa: F401 - re-exported to the modules
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
PORT = int(os.environ.get("DASHBOARD_PORT", "7680"))
# A node's screen relay (R99, R133): its terminals and its VMs' screens, on
# the one port its firewall opens to this controller. A node says its own in
# its census; this is what one that has not said listens on.
SCREEN_PORT = 7684

# ---- one login for everything ---------------------------------------------
# One sign-in on a real login page covers the page and its terminals, which
# are websockets on this origin (/termws), so no second port is published.
#
# The cookie is a signed expiry, not a server-side session: the secret lives
# on the /config volume, so a container update does not log every phone out,
# and there is no session table to grow, lock, or clean. Basic auth still
# works on every request (curl, bb capture shot and the tests send it preemptively),
# but no response carries a WWW-Authenticate challenge any more, because the
# challenge is precisely what made browsers pop their own dialog.
SESSION_DAYS = 30
STATE = Path(os.environ.get("DASHBOARD_STATE", "/config"))
# Before anything below writes to it: a /config newer than this build, or
# older than it migrates from, is refused here in one sentence, a fresh one
# is stamped, and one about to migrate is copied first (stateversion.py).
import stateversion                                              # noqa: E402
stateversion.gate(STATE)


def _session_secret():
    """The key the session cookie is signed with, kept on the state volume.

    Every other read of that volume degrades rather than raises, and this one
    has to as well: it runs at import, so a /config that is missing or
    read-only took the whole dashboard down at startup, where the honest
    outcome is a dashboard that runs and forgets its sessions on restart.
    Basic auth is unaffected either way.

    With an install key (R135) it is made from the key and kept nowhere, so
    a copy of /config forges no sign-in; the file an install kept before is
    removed. Taking the key on signs everybody out once.
    """
    p = STATE / "dashboard-secret"
    keyf = Path(os.environ.get("BB_SIGNING_SECRET_FILE") or "/run/builderbot-key")
    try:
        key = keyf.read_bytes().strip()
    except OSError:
        key = b""
    if len(key) >= 16:
        try:
            p.unlink()
        except OSError:
            pass
        return hmac.new(key, b"builderbot session cookies v1", hashlib.sha256).digest()
    try:
        s = p.read_bytes()
        if len(s) >= 32:
            return s
    except OSError:
        pass
    s = os.urandom(32)
    try:
        STATE.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(s)
    except OSError as e:
        print(f"dashboard: cannot keep the session secret in {STATE} ({e}); "
              "sign-ins will not survive a restart", flush=True)
    return s


SECRET = _session_secret()


def make_token(u, lid=""):
    """A cookie for this account: name, expiry, the sign-in's id and a
    signature over those plus the account's password stamp.

    Stateless: there is no token table to keep. What
    the stamp buys is the revocation such a table would have given: changing a
    password or deleting an account moves it, and every cookie signed against
    the old one stops verifying on the next request. The sign-in's id names
    the row logins.py keeps (R159), which says the browser is signed in
    until it signs out or the cookie runs out; a cookie minted again for the
    same browser (a rename) keeps the id it had.
    """
    exp = str(int(time.time()) + SESSION_DAYS * 86400)
    nm = base64.urlsafe_b64encode(u["name"].encode()).decode().rstrip("=")
    lid = lid or logins.mint(u.get("uid") or "")
    sig = hmac.new(SECRET, f"{u['name']}|{exp}|{lid}|{users.stamp(u)}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{nm}.{exp}.{lid}.{sig}"


def purpose_token(u, purpose, secs, extra=""):
    """A short cookie for one step of signing in (R127): the account, an
    expiry, what it is for, and a signature over those and the password
    stamp, as make_token's. `extra` rides along signed (a remembered
    browser's id)."""
    exp = str(int(time.time()) + secs)
    nm = base64.urlsafe_b64encode(u["name"].encode()).decode().rstrip("=")
    sig = hmac.new(SECRET, f"{purpose}|{u['name']}|{exp}|{extra}|{users.stamp(u)}".encode(),
                   hashlib.sha256).hexdigest()
    return f"{nm}.{exp}.{extra}.{sig}"


def purpose_user(tok, purpose):
    """(account, extra) a purpose_token is for, or (None, ""). Fails closed."""
    parts = str(tok or "").split(".")
    if len(parts) != 4 or not parts[1].isdigit() or int(parts[1]) < time.time():
        return None, ""
    nm, exp, extra, sig = parts
    try:
        name = base64.urlsafe_b64decode(nm + "=" * (-len(nm) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None, ""
    u = users.get(name)
    if not u:
        return None, ""
    want = hmac.new(SECRET, f"{purpose}|{name}|{exp}|{extra}|{users.stamp(u)}".encode(),
                    hashlib.sha256).hexdigest()
    return (u, extra) if hmac.compare_digest(want, sig) else (None, "")


def token_user(tok):
    """The account a cookie is for, or None. Fails closed on everything.

    A cookie from before accounts existed has two parts rather than three and
    simply does not verify, which signs those sessions out once. That is the
    honest outcome: there is no way to know who they were.
    """
    parts = str(tok or "").split(".")
    if len(parts) != 4:
        return None
    nm, exp, lid, sig = parts
    if not exp.isdigit() or int(exp) < time.time():
        return None
    try:
        name = base64.urlsafe_b64decode(nm + "=" * (-len(nm) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    u = users.get(name)
    if not u:
        return None
    want = hmac.new(SECRET, f"{name}|{exp}|{lid}|{users.stamp(u)}".encode(),
                    hashlib.sha256).hexdigest()
    return {**u, "lid": lid} if hmac.compare_digest(sig, want) else None


# The landing page. Same palette as the dashboard, one job: turn a credential
# into the cookie. autocomplete names are the standard ones so password
# managers offer to fill and to save, which the browser dialog never did
# well on a phone.
# The first-run screen. Same card as the sign-in, so there is one look and one
# place to change it, with the copy and the fields the first account needs.
#
# It is served ONLY while the store holds no accounts, and creating one closes
# it for good. That window is the honest cost of not putting a password in the
# container's environment: until somebody claims the box, whoever reaches the
# port can. Which is why the page says to do it now rather than leaving it to
# be inferred, and why the dashboard refuses everything else until it is done.
SETUP_FIELDS = """  <p class="note">Nobody owns this container yet. The first account you make
    here is the <b>owner</b>: it cannot be deleted, and it is how you add
    everyone else. Do it now: until you do, anyone who can reach this page
    can claim it.</p>
  <!--ERR-->
  <label for="u">Username</label>
  <input id="u" name="username" autocomplete="username" autocapitalize="none"
    required autofocus>
  <label for="p">Password, at least 8 characters</label>
  <input id="p" name="password" type="password" autocomplete="new-password"
    minlength="8" required>
  <label for="p2">Password again</label>
  <input id="p2" name="password2" type="password" autocomplete="new-password"
    minlength="8" required>
  <button type="submit">Create the owner</button>"""

LOGIN_FIELDS = """  <!--ERR-->
  <input type="hidden" name="next" value="<!--NEXT-->">
  <label for="u">Username</label>
  <input id="u" name="username" value="<!--NAME-->" autocomplete="username" autocapitalize="none" required>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>"""

# The second step of signing in (R127): a code from the authenticator app or
# a recovery code in one field, a passkey by its button where the account has
# one and the browser can, and the browser remembered for 30 days on a tick.
MFA_FIELDS = """  <!--ERR-->
  <input type="hidden" name="next" value="<!--NEXT-->">
  <p class="note">Signing in as <b><!--NAME--></b>: the code your authenticator app shows, or one of your recovery codes.</p>
  <label for="c">Code</label>
  <input id="c" name="code" autocomplete="one-time-code" autocapitalize="none" spellcheck="false" autofocus>
  <label class="tick"><input type="checkbox" name="remember" value="1"> Remember this browser for 30 days</label>
  <button type="submit">Continue</button>
  <button type="button" id="pk" class="alt" data-has="<!--PASSKEYS-->" hidden>Use a passkey</button>
  <p class="note"><a href="/logout">Sign in as someone else</a></p>
  <script data-cfasync="false">
  (() => {
    const b = document.getElementById("pk");
    if (!b || b.dataset.has !== "1" || !window.PublicKeyCredential) return;
    b.hidden = false;
    const u8 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
    const b64 = a => btoa(String.fromCharCode(...new Uint8Array(a))).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/, "");
    const said = t => { let e = document.querySelector(".err"); if (!e) { e = document.createElement("p"); e.className = "err";
      b.form.querySelector("input[name=next]").after(e); } e.textContent = t; };
    const post = body => fetch("/login/passkey", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)}).then(r => r.json());
    b.onclick = async () => {
      try {
        const ch = await post({action: "challenge"});
        if (ch.error) throw new Error(ch.error);
        const c = await navigator.credentials.get({publicKey: {challenge: u8(ch.challenge), rpId: location.hostname,
          allowCredentials: ch.ids.map(id => ({type: "public-key", id: u8(id)})), userVerification: "preferred", timeout: 60000}});
        const r = await post({action: "verify", id: b64(c.rawId), client: b64(c.response.clientDataJSON),
          auth: b64(c.response.authenticatorData), sig: b64(c.response.signature),
          remember: b.form.querySelector("[name=remember]").checked, next: b.form.querySelector("[name=next]").value});
        if (r.error) throw new Error(r.error);
        location.href = r.next || "/";
      } catch (e) { said(e.name === "NotAllowedError" ? "The passkey was not used: try again, or type a code." : String(e.message || e)); }
    };
  })();
  </script>"""

# The page an account whose role requires a second factor meets before
# anything else (R127): the authenticator's QR and secret, its first code, the
# recovery codes once; or a passkey where the browser can make one.
SETUP_2FA_FIELDS = """  <p class="note">A role of yours, <b><!--NAME--></b>, requires a second factor. Scan the code with an authenticator app (or type the secret), then the code it shows.</p>
  <div id="qr" class="qr"></div>
  <p class="note" id="sec"></p>
  <label for="c">Code</label>
  <input id="c" autocomplete="one-time-code" inputmode="numeric" autocapitalize="none">
  <button type="submit">Turn it on</button>
  <button type="button" id="pk" class="alt" hidden>Use a passkey instead</button>
  <div id="rc" hidden><p class="note">Your recovery codes, shown once: each signs you in once if your app or passkey is lost. Keep them somewhere safe.</p><pre id="codes"></pre><a class="go" href="/">Continue</a></div>
  <p class="note"><a href="/logout">Sign out</a></p>
  <script data-cfasync="false">
  (() => {
    const f = document.querySelector("form"), $ = id => document.getElementById(id);
    const api = body => fetch("/api/profile", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)}).then(r => r.json());
    const said = t => { let e = document.querySelector(".err"); if (!e) { e = document.createElement("p"); e.className = "err";
      f.querySelector(".head").after(e); } e.textContent = t; };
    const done = codes => { [...f.children].forEach(el => { if (!el.matches(".head, #rc, script")) el.hidden = true; });
      $("rc").hidden = false; $("codes").textContent = (codes || []).join("\\n"); };
    api({action: "2fa-totp-begin"}).then(r => { $("qr").innerHTML = r.qr || ""; $("sec").textContent = "Secret: " + (r.secret || ""); });
    f.onsubmit = async e => { e.preventDefault();
      const r = await api({action: "2fa-totp-confirm", code: $("c").value});
      r.error ? said(r.error) : done(r.recovery); };
    if (window.PublicKeyCredential) {
      const b = $("pk"); b.hidden = false;
      const u8 = s => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), c => c.charCodeAt(0));
      const b64 = a => btoa(String.fromCharCode(...new Uint8Array(a))).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/, "");
      b.onclick = async () => { try {
        const o = await api({action: "2fa-passkey-begin"});
        const c = await navigator.credentials.create({publicKey: {challenge: u8(o.challenge), rp: {name: "BuilderBot", id: location.hostname},
          user: {id: u8(o.user), name: o.name, displayName: o.name}, pubKeyCredParams: [{type: "public-key", alg: -7}],
          authenticatorSelection: {residentKey: "preferred", userVerification: "preferred"}, attestation: "none", timeout: 60000,
          excludeCredentials: (o.exclude || []).map(id => ({type: "public-key", id: u8(id)}))}});
        const r = await api({action: "2fa-passkey-add", name: "passkey", client: b64(c.response.clientDataJSON), att: b64(c.response.attestationObject)});
        r.error ? said(r.error) : done(r.recovery);
      } catch (e) { said(e.name === "NotAllowedError" ? "The passkey was not made: try again, or use the app." : String(e.message || e)); } };
    }
  })();
  </script>"""

LOGIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#1a1f26">
<title>BuilderBot: <!--TITLE--></title>
<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<style>
  /* The Default scheme's tokens, its dark half, and nothing a person picked:
     nobody is signed in yet, so the page wears BuilderBot's own colors
     whatever this browser kept (the operator, 17 Oct). Derived the way the
     dashboard derives them (index.html :root): the lit fill from the second
     color, the sunk field from the panel. */
  :root{
    --bg:#1a1f26; --panel:#212730; --line:#4d5c6f; --ink:#e6edf3;
    --dim:#9fa9b4; --accent:#3fb950; --bad:#f8524a; --note:#58a6ff;
    --deep:#1a4f8f; --deep:color-mix(in srgb, var(--note), #000000 40%);
    --deep-edge:#1f6feb; --deep-edge:color-mix(in srgb, var(--note), #000000 14%);
    --sunk:#1d2229; --sunk:color-mix(in srgb, var(--panel), #000000 12%);
    --display:"Segoe UI Variable Display","SF Pro Display",Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    --r:6px;
  }
  *{box-sizing:border-box}
  /* dvh, not vh: on a phone `vh` resolves against the LARGE viewport (the
     page as it would be with the URL bar retracted), so min-height:100vh
     made the body taller than the visible area and the page scrolled to
     reach nothing. dvh tracks the bar as it comes and goes; vh stays first
     as the fallback for browsers that do not know dvh.
     `safe center` keeps the top of the card reachable if a soft keyboard
     ever leaves less room than the card needs, the same rule the
     dashboard's own dialogs use.
     The document itself never scrolls (B837: the page still scrolled on the
     operator's phone in Firefox, though it fitted): the body is the one
     scroller, the height of what is on show, and it scrolls only when what
     it holds is taller, a keyboard up over a short screen. */
  html{background:var(--bg);height:100%;overflow:hidden}
  body{margin:0;height:100vh;height:100dvh;padding:16px;position:relative;overflow-x:hidden;overflow-y:auto;overscroll-behavior:contain;
    display:flex;flex-direction:column;align-items:center;justify-content:safe center;gap:18px;
    color:var(--ink);background:var(--bg);
    font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
  /* The ground: a drafting grid in the line color, fading out from the
     middle, under two slow glows, the accent's behind the card and the
     second color's below it. Behind everything and never pressed. */
  body::before,body::after{content:"";position:fixed;inset:0;pointer-events:none;z-index:0}
  body::before{
    background-image:
      linear-gradient(color-mix(in srgb, var(--line) 34%, transparent) 1px, transparent 1px),
      linear-gradient(90deg, color-mix(in srgb, var(--line) 34%, transparent) 1px, transparent 1px),
      linear-gradient(color-mix(in srgb, var(--line) 16%, transparent) 1px, transparent 1px),
      linear-gradient(90deg, color-mix(in srgb, var(--line) 16%, transparent) 1px, transparent 1px);
    background-size:96px 96px,96px 96px,24px 24px,24px 24px;
    background-position:center center;
    -webkit-mask-image:radial-gradient(ellipse 70% 62% at 50% 46%, #000 30%, transparent 100%);
    mask-image:radial-gradient(ellipse 70% 62% at 50% 46%, #000 30%, transparent 100%)}
  body::after{inset:-20%;
    background:
      radial-gradient(34% 30% at 46% 40%, color-mix(in srgb, var(--accent) 17%, transparent), transparent 70%),
      radial-gradient(30% 26% at 60% 66%, color-mix(in srgb, var(--note) 13%, transparent), transparent 70%);
    animation:drift 26s ease-in-out infinite alternate}
  @keyframes drift{from{transform:translate3d(-2%,-1.5%,0) rotate(-2deg)}to{transform:translate3d(2%,1.5%,0) rotate(2deg)}}
  @media(prefers-reduced-motion:reduce){ body::after{animation:none} }
  /* The one panel, a little glass over the grid: its top edge carries the
     two colors the page is drawn in. border-box, or the padding and border
     are added to the width and it wanted 398px on a 390px phone. */
  form{position:relative;z-index:1;width:min(360px,100%);padding:30px 28px 26px;
    display:flex;flex-direction:column;gap:6px;
    background:color-mix(in srgb, var(--panel) 88%, transparent);
    -webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);
    border:1px solid color-mix(in srgb, var(--line) 80%, transparent);border-radius:calc(var(--r) * 2);
    box-shadow:0 1px 0 rgba(255,255,255,.04) inset,0 24px 64px rgba(0,0,0,.45),0 2px 10px rgba(0,0,0,.25);
    animation:rise .5s cubic-bezier(.2,.8,.2,1) both}
  form::before{content:"";position:absolute;left:18px;right:18px;top:-1px;height:2px;border-radius:2px;
    background:linear-gradient(90deg, transparent, var(--accent) 22%, var(--note) 78%, transparent)}
  @keyframes rise{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
  @media(prefers-reduced-motion:reduce){ form{animation:none} }
  .head{display:flex;flex-direction:column;align-items:center;gap:10px;margin:0 0 16px;text-align:center}
  .mark{width:52px;height:52px;display:grid;place-items:center;border-radius:14px;
    background:color-mix(in srgb, var(--accent) 12%, var(--sunk));
    border:1px solid color-mix(in srgb, var(--accent) 35%, transparent);
    box-shadow:0 0 28px color-mix(in srgb, var(--accent) 22%, transparent)}
  .mark svg{width:32px;height:32px;color:var(--accent)}
  h1{margin:0;font:600 22px/1.2 var(--display);letter-spacing:-.01em}
  .said{margin:0;color:var(--dim);font-size:13px}
  label{font-size:12px;color:var(--dim);margin-top:8px}
  /* 16px in the fields: anything smaller and iOS zooms the page into the
     one that has the focus, and this page cannot zoom back. */
  input{width:100%;min-height:42px;padding:9px 12px;background:var(--sunk);color:var(--ink);
    border:1px solid var(--line);border-radius:var(--r);font:16px/1.3 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
    transition:border-color .15s,box-shadow .15s}
  input:focus{outline:none;border-color:var(--note);box-shadow:0 0 0 3px color-mix(in srgb, var(--note) 28%, transparent)}
  /* The one filled button, the deep fill with the ink on it, as every
     filled surface in the dashboard is. */
  button{margin-top:18px;min-height:44px;padding:10px;border-radius:var(--r);cursor:pointer;
    background:var(--deep);border:1px solid var(--deep-edge);color:var(--ink);
    font:600 15px/1.2 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;transition:background .15s,transform .05s}
  button:hover{background:color-mix(in srgb, var(--note), #000000 30%)}
  button:active{transform:translateY(1px)}
  button:focus-visible{outline:none;box-shadow:0 0 0 3px color-mix(in srgb, var(--note) 35%, transparent)}
  .err{margin:0 0 4px;padding:8px 10px;border-radius:var(--r);font-size:13px;color:var(--bad);
    background:color-mix(in srgb, var(--bad) 10%, transparent);border:1px solid color-mix(in srgb, var(--bad) 35%, transparent)}
  .note{color:var(--dim);font-size:13px;margin:0 0 6px}
  .note b{color:var(--ink)}
  .note a{color:var(--note)}
  label.tick{display:flex;gap:8px;align-items:center;margin-top:12px;color:var(--dim);font-size:13px}
  label.tick input{width:auto;margin:0}
  button.alt{background:transparent;border-color:var(--line);color:var(--ink);font-weight:500;margin-top:10px}
  .qr{display:flex;justify-content:center;margin:6px 0}
  .qr svg{width:180px;height:180px;border-radius:4px}
  pre#codes{font:14px/1.6 ui-monospace,monospace;color:var(--ink);background:var(--panel);padding:10px;border-radius:var(--r)}
  a.go{display:block;text-align:center;margin-top:12px;color:var(--note)}
  .banner{position:fixed;top:0;left:0;right:0;padding:6px 12px;font-size:13px;text-align:center;
    color:var(--ink);background:var(--panel);border-bottom:1px solid var(--line)}
  .banner a{color:var(--note)}
</style></head><body>
<!--BANNER-->
<form method="post" action="<!--ACTION-->">
  <div class="head">
    <span class="mark"><svg viewBox="0 0 32 32" aria-hidden="true"><mask id="m">
      <rect width="32" height="32" fill="#000"/>
      <rect x="4" y="8.5" width="24" height="17" rx="5.5" fill="#fff"/>
      <rect x="15" y="3.5" width="2" height="6" rx="1" fill="#fff"/>
      <circle cx="16" cy="3" r="2.3" fill="#fff"/>
      <circle cx="11.4" cy="15.4" r="2.1" fill="#000"/>
      <circle cx="20.6" cy="15.4" r="2.1" fill="#000"/>
      <rect x="10.6" y="19.6" width="10.8" height="2.6" rx="1.3" fill="#000"/>
    </mask><rect width="32" height="32" fill="currentColor" mask="url(#m)"/></svg></span>
    <h1>BuilderBot</h1>
    <p class="said"><!--SAID--></p>
  </div>
  <!--FIELDS-->
</form>
<script data-cfasync="false">
  const n = new URLSearchParams(location.search).get("next");
  const f = document.querySelector('[name=next]');
  if (f && n && n.startsWith("/") && !n.startsWith("//")) f.value = n;
  if (document.getElementById("u")?.value) document.getElementById("p")?.focus();
</script>
</body></html>
"""

# Every command the UI can run and every key it can press, by name, and the
# operator's own command lists: macros.py (R77).



# Where Claude Code keeps transcripts: one directory per working directory,
# with the path's slashes turned into dashes, holding one .jsonl per session.
CLAUDE_PROJECTS = Path(
    os.environ.get("BUILDER_HOME", str(Path.home()))) / ".claude" / "projects"


# Every request body here is a handful of short JSON fields. Anything larger is
# a mistake or a probe, and reading it into memory unbounded helps neither.
MAX_BODY = 64 * 1024
# The one body that is a document: a project's whole design, which its own
# limits let run to megabytes (forty pages, sixty rules of twenty thousand
# characters). At 64 kB a design of forty pages and thirteen themes was
# refused as "body too large" with every part of it inside its limit.
# ...and an agent's log post: it batches chunks up to 40 kB and then adds a
# whole chunk of up to 32 kB, characters json.dumps may spell six bytes each,
# so a post could pass 64 kB, and one refused as too large was retried for
# good, holding its job in the agent's count and refusing every update as
# busy (B520: j_cdcb12b7, a phone screenshot, held from 4 to 6 Oct).
# ...and a file saved from a person's editor (R159): files.MAX_READ as base64.
MAX_BODY_FOR = {"/api/design": 4 * 1024 * 1024, "/api/wiki": 1024 * 1024,
                "/api/v1/files": 28 * 1024 * 1024,
                "/api/v1/agent/log": 512 * 1024,
                # A keystore a node made or wrapped, as base64 (signing.RESULT).
                "/api/v1/agent/signing-result": 3 * 1024 * 1024,
                "/api/vms": 3 * 1024 * 1024}   # a GPU's .rom given on the VMs page (R100)

# One field out of a request body, read the one way here and in every
# module a handler calls into (fields.py).
from fields import field                                         # noqa: E402
# Where a request's time goes, named part by part (timing.py).
import timing                                                    # noqa: E402







# The one implementation, in statefile.py, along with the file lock that makes
# a read-modify-write safe against the OTHER writer, a `bb` invocation, which
# is a different process. Kept as a name here because thirty-odd call sites and
# every configure() injection already say write_json.
write_json = statefile.write_json


# One lock for every read-modify-write of a state file. The revision the
# layout carries is what lets two browsers share a strip without fighting;
# two saves reading the same file and both stamping rev+1 handed both pages
# the same number, and each then took the other's writes for its own and
# skipped them. Coarse on purpose: these are tiny files and rare writes.
_state_lock = threading.Lock()

# ---- what the page keeps here ---------------------------------------------------
# Each account's tab strip and panes, and the sidebar's cards: layout.py.
import layout                                                    # noqa: E402

layout.configure(state=STATE, write_json=write_json, lock=_state_lock)
# ...and what each account has put away from its bell: bellseen.py.
import bellseen                                                  # noqa: E402

bellseen.configure(state=STATE, write_json=write_json)
# ...and what the page has said to each account, kept: notices.py (R218 step 6).
import notices                                                   # noqa: E402
notices.configure(state=STATE, write_json=write_json)
# Scheduled scripts (R117): an administrator's cron, kept in the state and
# never on the share; the built-in scan's script two levels above, as the
# image and a checkout both keep it.
import schedules                                                 # noqa: E402
schedules.configure(state=STATE, write_json=write_json)
# ...and BuilderBot's own docs, read on the Help page: helpdocs.py (R258).
import helpdocs                                                  # noqa: E402








# `bb toolchains install|update|remove` refuses when CLAUDECODE is set, and the
# message it prints tells the session to ask the operator to use this page.
# So this page must never carry that variable, and it can: `bb dashboard dev`
# is normally run *by* a session, and the server it starts inherits whatever
# that session had. One line here, rather than trusting every launcher to
# remember, because the failure looks like the dashboard refusing to obey the
# operator and quoting its own name as the workaround.
os.environ.pop("CLAUDECODE", None)
os.environ.pop("BB_AGENT", None)     # ...and any coding agent's mark (R95)


def run(cmd, cwd=None, timeout=120, env=None, split_err=False, register=None):
    # split_err=True keeps stdout in `out` and stderr in `err`, for the one
    # caller class that must not mistake a warning for real output (the
    # ls-remote emptiness check: ssh's first-contact "Permanently added ..."
    # note lands on stderr and made an empty repo look non-empty). The
    # default stays combined, which is what every log-oriented caller wants.
    # register: hand the caller the process, so a long job can be interrupted.
    # It gets its own process group with it, because stopping an install means
    # stopping the curl or the tar it is waiting on, not only the shell.
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, env=env,
                             start_new_session=register is not None)
    except FileNotFoundError as e:
        return {"cmd": shlex.join(cmd), "code": 127, "out": str(e), "err": ""}
    if register:
        register(p)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return {"cmd": shlex.join(cmd), "code": 124,
                "out": f"timed out after {timeout}s", "err": ""}
    finally:
        if register:
            register(None)
    out, err = out or "", err or ""
    if not split_err:
        out, err = out + err, ""
    return {"cmd": shlex.join(cmd), "code": p.returncode, "out": out, "err": err}


def version_payload(name):
    """The Artifacts view's version block, plus what a window move would cost
    here. One function so every answer the tab gets carries the same warning:
    the staged line is drawn from whichever of them came back last."""
    cost = window_cost(name)
    # {tag: {url, error, forge}} of the forge releases Release made, for the row's link (R123, R124).
    rel = forgerelease.kept(name)
    return (version.payload(name) | ({"window_cost": cost} if cost else {})
            | ({"forge_releases": rel} if rel else {}))


def window_cost(name):
    """What a MINOR bump of this project would cost the others, or {}.

    Only one project can answer yes: the one whose checkout IS BuilderBot,
    because its minor is the compatibility window. What that window still
    holds, now the environment block is assembled per session and cannot be
    from another one (R63 step 3), is a node's AGENT: bump the minor and every
    node running an agent from the old window holds its projects until that
    agent is updated. Sessions on them end. Said before the button is pressed
    rather than after (B92); the test is the two files that move the window,
    not a project's name.
    """
    try:
        here = WORKSPACE / name
        if not ((here / "tools" / "version-stamp").is_file()
                and (here / "scripts" / "agent" / "builderbot-agent.py").is_file()):
            return {}
    except OSError:
        return {}
    # Every project bound to a node that runs an agent: after the bump that
    # agent is from the previous window until it is updated.
    live = {n["id"] for n in nodes.node_list(all=True) if n.get("kind") == "agent"}
    held = []
    try:
        for d in sorted(WORKSPACE.iterdir()):
            if not d.is_dir() or (d / IGNORE_MARKER).exists():
                continue
            if ((prefs.get(d.name) or {}).get("node") or "") in live:
                held.append(d.name)
    except OSError:
        return {}
    if not held:
        return {}
    return {"window": nodes.agent_window(nodes.agent_file()["version"]), "projects": held}


def node_holds(reap=False):
    """{node id: why} for every agent node no Claude session may start on
    right now: its agent is from another compatibility window than this
    controller ships, or its Claude Code is being updated (claudecode.py),
    which ends the sessions there first. The half of a project's hold that
    is its node's. Being merely behind is not here: inside a window an
    older agent takes a job and a session, and the Nodes page's Update is a
    courtesy rather than a gate. reap: only what ends a running session
    (claudecode.holds)."""
    out = {}
    if NODES_OK:
        return out
    for n in nodes.node_list():
        if n["kind"] == "agent" and nodes.agent_gap(n):
            out[n["id"]] = nodes.agent_stale(n)
    out.update(claudecode.holds(reap))
    return out


def compat_holds(reap=False):
    """{project: why} for every project no Claude session may run on right
    now, which since R63 step 3 means one thing: its node's agent is from
    another compatibility window. Per project on purpose, because another
    project's node being out of window is that project's problem and this
    one's button stays live."""
    out = {}
    holds = node_holds(reap)
    pp = prefs.all_projects()
    try:
        dirs = [d for d in WORKSPACE.iterdir() if d.is_dir()]
    except OSError:
        return out
    for d in dirs:
        # The block's window went with the block (R63 step 3): what a session
        # is told is assembled per session now, so there is no copy to be from
        # another window. A node's agent still can be, and that is this.
        why = holds.get((pp.get(d.name) or {}).get("node") or "", "")
        if why:
            out[d.name] = why
    return out


# How often the sweep below runs. Settable only so the suite need not wait
# half a minute to see a session end.
COMPAT_SWEEP_S = float(os.environ.get("BB_COMPAT_SWEEP") or 30)


def compat_reap_once():
    """End the Claude sessions running on a held project (compat_holds), here
    and on the nodes. Returns the names ended.

    This is the other half of the window's promise: a controller that moved
    its minor may have changed what the block says and what the agent
    understands, so a conversation started under the old window is running
    on a map that is now wrong, and it is ended rather than left to act on
    it. Inside a window nothing here fires: an update to the block or the
    agent that keeps the window leaves every session running. Run once at
    start, which is the moment after a controller update, and on a timer
    after that for a window that moves under a running server (a bump
    landing on a `bb dashboard dev` restart, a node enrolled behind)."""
    holds = compat_holds(reap=True)
    if not holds:
        return []
    wanted = {n: why for p, why in holds.items() for n in agent_sessions(p)}
    ended = []
    for s in tmux_sessions():
        why = wanted.get(tmux_base(s["name"]))
        if not why:
            continue
        r = run(["tmux", "kill-session", "-t", "=" + s["name"]], timeout=10)
        if r["code"] == 0:
            ended.append(s["name"])
            print(f"dashboard: compat: ended {s['name']} ({why})", flush=True)
    if not NODES_OK:
        for nid, (nname, sess) in nodes.node_sessions().items():
            for s in sess:
                real = str(s.get("name") or "")
                why = wanted.get(tmux_base(real))
                if not why:
                    continue
                nodes.session_kill(nid, real)
                ended.append(real)
                print(f"dashboard: compat: ending {real} on {nname} ({why})", flush=True)
    return ended


# The log policy on a clock (the operator, 12 Oct): the days were applied at
# boot and at Apply only, so a controller up for weeks kept what had fallen
# past them, and its live files grew without bound. Every hour: the earlier
# generations and the CI runs past the days, a live file past its ceiling,
# the job logs past theirs, the job rows and the audit past theirs.
LOG_SWEEP_EVERY = 3600


def log_sweep_loop():
    while True:
        time.sleep(LOG_SWEEP_EVERY)
        try:
            r = logs.sweep()
            r["job_logs"] = nodes.prune_job_logs()
            r["job_rows"] = nodes.prune_jobs()
            r["audit"] = db.prune_audit()
            unlocks.sweep()
            if any(r.values()):
                print(f"dashboard: log sweep: {', '.join(f'{k} {v}' for k, v in r.items() if v)}", flush=True)
        except Exception as e:                                # noqa: BLE001 (the loop outlives one bad pass)
            print(f"dashboard: log sweep skipped: {type(e).__name__}: {e}", flush=True)


def _compat_loop():
    while True:
        try:
            compat_reap_once()
        except Exception as e:        # noqa: BLE001 (a sweeper must not die)
            print(f"dashboard: compat: {e}", flush=True)
        time.sleep(max(1.0, COMPAT_SWEEP_S))


# What a new project may be called. It becomes a directory under /workspace and
# part of a tmux session name, so it gets the strictest charset here: one path
# segment, starting with a letter or digit, which also rules out dotfiles
# and `..`. Where a clone may come from is forges.URL, next door: the
# same allowlist reasoning (`git clone` accepts transports a browser form must
# never reach, like `ext::`, which runs commands) applied to more than one host.

# The builder user's ssh directory. Overridable through BUILDER_HOME for the
# same reason CLAUDE_PROJECTS is: the tests point it at a scratch home, and
# nothing they write may land in the real one.
SSH_DIR = Path(os.environ.get("BUILDER_HOME", str(Path.home()))) / ".ssh"


def agent_keys():
    """[{name, pub}] for every key the shielded agent holds.

    ssh-add -L prints the *public* halves, the one part of a shielded key
    that is meant to be shown around. The name is the key's comment (the
    filename it was loaded from), sanitized to the same charset as a project
    name because it becomes a filename and a host alias here. A key whose
    comment does not survive that is skipped, not mangled: it cannot be
    addressed unambiguously, and these names face the operator.
    """
    r = run(["ssh-add", "-L"], timeout=10)
    if r["code"] != 0:
        return []                         # no agent, or an empty one
    keys = []
    for line in r["out"].splitlines():
        parts = line.split(None, 2)
        if len(parts) < 2 or not parts[0].startswith(("ssh-", "ecdsa-", "sk-")):
            continue
        name = os.path.basename(parts[2].strip()) if len(parts) > 2 else ""
        if PROJECT_NAME.fullmatch(name) and name not in {k["name"] for k in keys}:
            keys.append({"name": name, "pub": line.strip()})
    return keys


def gh_authed():
    """Whether git-over-https can authenticate, i.e. whether a PAT is wired up.

    Asked of gh rather than the environment, because gh is what actually
    answers the credential prompt (`gh auth setup-git` at startup): this is
    true exactly when an https remote will work, which only a `gh auth login`
    typed in a shell makes so. `gh auth token` is offline and instant;
    `gh auth status` phones home.
    """
    return run(["gh", "auth", "token"], timeout=10)["code"] == 0


def ensure_deploy_alias(name, pub, host):
    """A per-repo ssh alias for one agent key on one host, created
    idempotently; returns the alias.

    Why an alias at all: deploy keys are scoped to a single repository, and
    ssh offers every agent key in order: the host authenticates the first
    valid one and then refuses the repo it does not belong to. The fix is
    IdentitiesOnly plus an IdentityFile naming the *public* half, which acts
    purely as a selector for the agent key (the private half stays shielded).

    The host is in the alias because one key can serve two of them: the same
    ed25519 on GitHub and on the Gitea in the cupboard is two different
    HostName lines, and an alias named after the key alone could only ever
    carry one of them.

    Everything written lives in a namespace of our own (bb_<name>.pub and
    Host bb-<name>-<host>), so a .pub or an alias the operator maintains by
    hand is never touched, and rewriting ours is always safe.

    The lock makes the check-then-append on ~/.ssh/config actually atomic:
    two concurrent requests using the same key would otherwise both miss the
    marker and both append the block. ssh would still behave (first match
    wins), but "idempotent" should not mean "single-threaded".
    """
    alias = f"bb-{name}-{forges.slug(host)}"
    with _ssh_lock:
        return _ensure_deploy_alias(alias, name, pub, host)


_ssh_lock = threading.Lock()


def _ensure_deploy_alias(alias, name, pub, host):
    SSH_DIR.mkdir(mode=0o700, exist_ok=True)
    pub_path = SSH_DIR / f"bb_{name}.pub"
    try:
        current = pub_path.read_text()
    except OSError:
        current = None
    if current != pub + "\n":
        pub_path.write_text(pub + "\n")
    cfg = SSH_DIR / "config"
    # The marker carries the alias, not the key: one key on two hosts is two
    # blocks, and a marker naming only the key would write the first and call
    # the second already done.
    marker = f"# builderbot:deploy-key:{alias}"
    try:
        have = cfg.read_text()
    except OSError:
        have = ""
    if marker not in have:
        hostname, _, port = host.partition(":")
        block = (f"\n{marker}\nHost {alias}\n"
                 f"    HostName {hostname}\n"
                 + (f"    Port {port}\n" if port.isdigit() else "")
                 + f"    IdentityFile {pub_path}\n"
                 f"    IdentitiesOnly yes\n")
        with open(cfg, "a") as f:
            f.write(block)
        os.chmod(cfg, 0o600)
    return alias


def _remote_host(remotes):
    """The real host behind the first remote in `git remote -v` output.

    Not the host as written: the standard multi-deploy-key setup (including
    the bb- aliases this dashboard's own clone and link flows write) hides
    the server behind a ~/.ssh/config Host alias, so the URL says `bb-key-x`
    and only that file knows what it stands for. forges.host_of resolves it
    with `ssh -G`, which reads the config and touches no network.
    """
    for line in remotes.splitlines():
        parts = line.split()
        if len(parts) >= 2 and forges.parse(parts[1]):
            return forges.host_of(parts[1])
    return ""


# A directory holding this file is not a project: not listed, not offered a
# Claude session, not counted. Written by the container into its own paths
# under the projects share, and by hand for anything else.
IGNORE_MARKER = ".bbignore"


def _session_nodes(name):
    """One row per node the project works on, for the chooser a Claude press
    opens when there is more than one (R82): where a session there would
    stand (node or refused, with the why), the node's boot for the tab, and
    what the machine has and how busy it is, so the pick is a read. A
    project on one node gets its one row too, so its chooser says what that
    machine has as well (the operator, 30 Sep); [] for a project on none."""
    p = prefs.get(name) or {}
    set_ = p.get("nodes") or ([p["node"]] if p.get("node") else [])
    if not set_:
        return []
    out = []
    for nid in set_:
        t = session_target(name, claude=True, node=nid)
        n = nodes.node(nid) or {}
        rep = n.get("reported") or {}
        out.append({"id": nid, "name": n.get("name") or t.get("name") or nid,
                    "where": t["where"], "why": t.get("why") or "", "boot": t.get("boot") or "",
                    "sample": rep.get("sample") or {}, "gpu": rep.get("gpu") or "",
                    "tools": sorted((rep.get("toolchains") or {}).keys())[:6],
                    # The coding agents beside Claude installed there, which
                    # the chooser offers a session of (R95 step 4).
                    "agents": [a.id for a in agents.live() if a.id != "claude"
                               and ((rep.get("session") or {}).get(a.reported) or "")]})
    return out


def _session_at(name):
    t = session_target(name, claude=True)
    if t["where"] == "node":
        # The node's boot, for the page to stamp into a terminal's URL in
        # place of this container's: bb-tty on the node compares against the
        # node's own run, and a tab carrying the controller's boot was
        # refused there as "from before the container restarted" on every
        # connection, a loop nobody could end from the Sessions card,
        # because the session never started.
        return {"session_at": t["name"], "session_why": "",
                # ...and its id, which is what the page asks its own Claude
                # sign-ins about: a login is one account's on one node.
                "session_node": t["id"],
                "session_boot": t.get("boot") or ""}
    if t["where"] == "refused":
        return {"session_at": t["name"], "session_why": t["why"], "session_node": "", "session_boot": "",
                # A wait that passes on its own (a node reconnecting after a
                # restart, a mount landing after boot): drawn quietly.
                "session_waiting": bool(t.get("waiting"))}
    return {"session_at": "", "session_why": "", "session_node": "", "session_boot": ""}


def _row_git_ready(base, over):
    """Whether a commit on this project would carry an author, for one row."""
    g = users.identity_over(base, over)
    return bool(g["name"] and g["email"])


# What git says of each project, kept until what it depends on moves (R94):
# three git forks per project on every /api/status, about sixty a poll on a
# controller with twenty projects, and the status poll at 1.3s on average
# (12 Oct). Keyed on what .git/HEAD says, .git/config's size and time and
# .git's time: a branch switch rewrites HEAD and a remote change config, so
# either asks git again; a .git that is a file (a worktree) is asked every
# time, and nothing is kept longer than GIT_FACTS_S.
GIT_FACTS_S = 60.0
_git_facts_kept = {}


def _git_stamp(d):
    # HEAD by its contents, a few bytes that are the branch itself, since a
    # share that keeps times to the second would not tell two switches in
    # one second apart; config by its size and time, and .git's time.
    g = d / ".git"
    try:
        if not g.is_dir():
            return None
        c = (g / "config").stat()
        return ((g / "HEAD").read_bytes()[:512], c.st_size, c.st_mtime_ns, g.stat().st_mtime_ns)
    except OSError:
        return None


def _git_facts(d):
    """(git_ok, linked, fhost, forge, github, branch) for one project."""
    stamp = _git_stamp(d)
    hit = _git_facts_kept.get(str(d))
    if stamp is not None and hit and hit[0] == stamp and time.time() - hit[1] < GIT_FACTS_S:
        return hit[2]
    branch, git_ok, linked, github, fhost, forge = None, False, True, False, "", forges.OTHER
    if (d / ".git").exists():
        # Asking git rather than trusting the directory's existence: a
        # half-copied or corrupt .git looks identical from out here, and a
        # repo git cannot read is not one anything can act on.
        git_ok = run(["git", "-C", str(d), "rev-parse", "--is-inside-work-tree"],
                     timeout=10)["out"].strip() == "true"
    if git_ok:
        # Asked of git, not read out of .git/config: a worktree or a
        # submodule keeps its config elsewhere, and these drive visible
        # controls (the chain on the row; the GitHub command card's
        # ghosting), so a wrong guess here offers an action that cannot
        # work. -v for the URLs, which is what says which host it is on.
        remotes = run(["git", "-C", str(d), "remote", "-v"], timeout=10)["out"]
        linked = bool(remotes.strip())
        # Which forge, for the chain's own words, and `github` still on its
        # own, because the command card runs `gh` and that is GitHub's and
        # nobody else's.
        fhost = _remote_host(remotes) if linked else ""
        forge = forges.forge_of(fhost)
        github = fhost.lower().split(":")[0] == "github.com"
        r = run(["git", "-C", str(d), "symbolic-ref", "--short", "-q", "HEAD"], timeout=10)
        # `out` carries stderr too, so a detached HEAD would otherwise put a
        # `fatal:` line where the branch name goes.
        branch = (r["out"].strip() or "(detached)") if r["code"] == 0 else "(detached)"
    facts = (git_ok, linked, fhost, forge, github, branch)
    if stamp is not None:
        _git_facts_kept[str(d)] = (stamp, time.time(), facts)
    return facts


def _listed(d, cloning):
    """Whether the walk lists directory `d` as a project: the one rule for
    the whole list and for its names alone (project_names)."""
    # Only what BuilderBot made (R154, the operator 8 Oct): a folder made by
    # hand on the share is not a project, and Import is the way one comes in.
    if not registry.is_project(d.name):
        return False
    # Mid-clone: a directory with a .git and not much else, which every
    # check reads as a repository in a strange state. The job row is
    # already saying what it really is.
    if d.name == cloning:
        return False
    # Hidden directories are not projects: the whole projects folder is
    # mounted now, so this list would otherwise open with the share's own
    # furniture (.Recycle.Bin and friends) presented as things to fix.
    #
    # .bbignore is the general form of the same idea, and the one thing
    # here an operator can drive: a directory holding that file is not a
    # project and is not listed. The container drops it into any path of
    # its own that lands inside the projects share (the toolchain store, when
    # someone maps it inside the projects folder rather than beside it),
    # and anyone can create one by hand for a directory they would rather
    # not see. It hides; locking a project is the thing that *blocks*, and
    # that is a different control with a different guarantee.
    if not d.is_dir() or d.name.startswith(".") or (d / IGNORE_MARKER).exists():
        return False
    # An empty directory is the one thing never reported. It is not a
    # problem to fix but a mount point waiting for content, or a leftover,
    # and flagging it would be noise on every boot. One this user cannot
    # read, write or enter is listed, with what is wrong with it.
    if not all(os.access(d, m) for m in (os.R_OK, os.W_OK, os.X_OK)):
        return True
    try:
        return any(d.iterdir())
    except OSError:
        return True


def _place(listed):
    """Every listed repository in a project (R138): one recorded since, by
    an import, a clone or a first run, gets one of its own, its owner,
    settings, reads, people and marks moving onto it as migration 0010 moves
    them; one put back from the trash by hand goes back into its own. Asked
    by the status read and by project_names, so an access check never meets
    a repository in no project."""
    for key, first in repos.place(listed):
        membership.adopt(key, first)
        prefs.adopt(key, first)
        prefs.regrant(key, [first])
        users.rekey(first, key)
        projects.rekey(first, key)


def project_names(who):
    """The names of the projects `who` may see, in the list's order: what
    project_list answers to "is this a project?" (the access check most
    handlers make), without describing each one, which costs the status
    read's half second (the operator, 17 Oct: the Git view asked for the
    whole list five times as it opened)."""
    with timing.timed("project_names"):
        try:
            here = sorted(WORKSPACE.iterdir()) if WORKSPACE.is_dir() else []
        except OSError:
            return []
        cloning = projects.busy_name()
        registry.sync()
        rows = [{"name": d.name} for d in here if _listed(d, cloning)]
        _place({r["name"] for r in rows})
        return [p["name"] for p in _projects_seen_by(who, rows)]


def _projects_on_disk():
    """The directories under /workspace that are projects, each with what is
    wrong with it: the walk, the permissions, and what git says of the
    repository. One dict of facts per project (`dir`, `name`, `issues`,
    `git`, `git_ok`, `linked`, `github`, `fhost`, `forge`), for
    _project_columns to dress into the row the page reads, plus the list
    to hand back as it stands when there is nothing to walk: no workspace,
    or one this user cannot list. Nothing here asks who is looking; that is
    _projects_seen_by, and the split is the point: this stays one
    description of the share.
    """
    out = []
    uid, gid = os.getuid(), os.getgid()
    try:
        if not WORKSPACE.is_dir():
            return out, out
    except OSError:
        pass                    # unreadable: reported by the listing below
    try:
        here = sorted(WORKSPACE.iterdir())
    except OSError:
        # A workspace this user cannot list is a mount to fix, not a reason for
        # the runner card and the terminal to stop working too.
        return out, [{"name": str(WORKSPACE), "git": None,
                      "last_claude": None,
                      "issues": [{"level": "error",
                                  "text": f"cannot list this directory as uid {uid}:{gid}"
                                          "; chown it to PUID:PGID on the host"}]}]
    cloning = projects.busy_name()
    # Only what BuilderBot made (R154, the operator 8 Oct): a folder made by
    # hand on the share is not a project, and Import is the way one comes in.
    with timing.timed("projects:registry"):
        registry.sync()
    for d in here:
        if not _listed(d, cloning):
            continue
        issues = []

        # Permissions first, and reported even when everything after fails.
        # A directory this user cannot read also fails the git check below, so
        # checking git first would file a permissions problem as "not a repo"
        # and hide it under the rule that never shows those.
        missing = [n for n, m in (("read", os.R_OK), ("write", os.W_OK), ("enter", os.X_OK))
                   if not os.access(d, m)]
        if missing:
            issues.append({"level": "error",
                           "text": f"cannot {', '.join(missing)} this directory as "
                                   f"uid {uid}:{gid}; chown it to PUID:PGID on the host"})

        # Path.is_file() only swallows ENOENT/ENOTDIR/EBADF/ELOOP; EACCES is
        # re-raised, so an unreadable project directory took out the whole
        # status endpoint rather than being reported as the one thing wrong.

        # linked defaults to True and github to False: each gates an offered
        # action (the chain on the row; the GitHub command buttons), and a
        # project this loop could not examine must get no offer rather than a
        # broken one, which is the opposite default for the two. The forge
        # defaults with them, and to the entry that promises nothing.
        branch, git_ok, linked, github = None, False, True, False
        fhost, forge = "", forges.OTHER
        if not missing:
            with timing.timed("projects:git"):
                git_ok, linked, fhost, forge, github, branch = _git_facts(d)
            if not git_ok:
                issues.append({"level": "error", "text": "no valid git repository"})

        out.append({"dir": d, "name": d.name, "issues": issues, "git": branch,
                    "git_ok": git_ok, "linked": linked, "github": github,
                    "fhost": fhost, "forge": forge})
    # Two projects whose names slug alike are one dev instance: `My.App` and
    # `my-app` both slug to my-app, which is one compose project name, one env
    # file and one data directory driven by two rows that know nothing about
    # each other. Nothing owns the moment a directory appears under /workspace,
    # so it cannot be refused the way a container's name is, but this is the
    # only place that sees every name at once, which makes it the only place
    # that can say so at all.
    #
    # A warning, not an error: both projects are real and everything except the
    # dev instance works. An error would take them out of findings attribution
    # and off the Claude button, which would be a bigger fault than the one
    # being reported.
    by_slug = {}
    for row in out:
        by_slug.setdefault(devapp._slug(row["name"]), []).append(row)
    for slug, rows in by_slug.items():
        if len(rows) < 2:
            continue
        for row in rows:
            others = ", ".join(r["name"] for r in rows if r is not row)
            row["issues"].append({
                "level": "warning",
                "text": f"this name and {others} both shorten to “{slug}”: a "
                        f"dev instance of either is the same containers, env "
                        f"file and data directory. Rename one before using it"})
    return out, None


def lock_may(name, uid, admin, rec):
    """Whether this account may press the project's Lock or Unlock (R119):
    its owner or an administrator to lock; to unlock, an administrator's
    lock is an administrator's to lift and an owner's lock the owner's."""
    if not uid:
        return False
    mine = membership.owner_of(name) == uid
    if not rec:
        return mine or admin
    return admin if rec.get("admin") else mine


def _project_cards(who, ps):
    """{key: card} for every project this account sees (R138): its name and
    id, its repositories in their order (those it sees), and its marks as
    the account has them (pinned, group, color: a person's own; locked and
    archived: the project's), with what the account may do about each."""
    me_uid = "" if (who or {}).get("session") else users.uid_of(who)
    me_admin = bool(me_uid) and users.is_admin(who)
    locked = projects.load_locks()
    archived = set(projects.load_archived())
    pins = projects.load_project_pins(users.uid_of(who), users.starts_unpinned(who))
    groups = projects.load_project_groups(users.uid_of(who))
    colors = projects.load_marks("color", users.uid_of(who), start=_legacy_colors(prefs.all_projects(WORKSPACE)))
    seen = {p["name"] for p in ps}
    out = {}
    for k, ms in repos.all_members().items():
        if not users.may_see(who, k):
            continue
        owner = membership.owner_of(k)
        out[k] = {"name": registry.label(k), "pid": registry.pid(k),
                  "members": [m for m in ms if m in seen],
                  "may": bool(me_uid) and (me_admin or membership.may_manage(who, k)),
                  "locked": k in locked, "locked_admin": bool(locked.get(k, {}).get("admin")),
                  "locked_me": k in locked and bool(projects.locked_out(k, me_uid)),
                  "may_lock": lock_may(k, me_uid, me_admin, locked.get(k)),
                  "archived": k in archived,
                  "may_archive": me_admin or (bool(me_uid) and owner == me_uid),
                  "owner_name": membership.owner_name(k) or "",
                  "owner_mine": bool(me_uid) and owner == me_uid,
                  "pinned": True if pins is None else k in pins,
                  "group": groups.get(k, ""), "color": colors.get(k, "")}
    return out


def _project_columns(who, facts):
    """The row the page reads for each project _projects_on_disk found: its
    facts, and everything else a row carries. The project's own settings
    and this account's own on it, where its sessions run and why nothing
    runs there right now, the notebook's counts, the newest transcript.
    Every file that serves the whole list is read once here rather than per
    row: this runs on the fifteen-second poll.
    """
    _t0 = time.monotonic()
    locked = projects.load_locks()
    archived = set(projects.load_archived())
    # Who may archive and who may lock (R119): the project's owner or an
    # administrator, never a session. An owner's lock is lifted by the owner,
    # an administrator's by an administrator.
    me_uid = "" if (who or {}).get("session") else users.uid_of(who)
    me_admin = bool(me_uid) and users.is_admin(who)
    # Each directory's id and the name it is shown under (R154): synced with
    # the disk here, two listdirs and no write when nothing moved.
    reg = registry.sync()["projects"]
    # ...and every repository in a project (R138).
    _place({f["name"] for f in facts if f.get("name")})
    pins = projects.load_project_pins(users.uid_of(who), users.starts_unpinned(who))
    groups = projects.load_project_groups(users.uid_of(who))
    # One small file for the whole list, read here rather than per row: this
    # runs on the fifteen-second poll and a per-project read would be a dozen
    # opens for a dozen values that came from the same dictionary.
    # With the workspace, so each row also says what `bb test` would run
    # there with nothing set; the settings field offers it as what an
    # empty box means.
    project_prefs = prefs.all_projects(WORKSPACE)
    # The color this account gives each project (the operator, 18 Oct: a
    # person's own, not the project's), starting from what the projects
    # wore before that, for an account that has not picked one yet.
    colors = projects.load_marks("color", users.uid_of(who), start=_legacy_colors(project_prefs))
    # ...and, in one read each, what the ACCOUNT ASKING chose per project and
    # the author its commits carry with nothing overridden. The model, the
    # effort and the commit identity are the person's, not the directory's
    # (prefs.for_user), so they are resolved against `who` here rather than
    # read off the project.
    mine_prefs = prefs.all_for_user(users.uid_of(who))
    base_git = users.git_identity(who)
    # One answer per node about its agent, for every project row on it.
    node_gaps = {}
    # ...and its name, for the row to wear beside the project's.
    node_names = {}
    # ...and which of them were un-enrolled: a project left on one keeps it,
    # named, so the person can see where it used to run (the operator, 5 Oct).
    removed_nodes = set()
    if not NODES_OK:
        _t1 = time.monotonic()
        for n in nodes.node_list(all=True):
            node_names[n["id"]] = n["name"]
            if n["state"] == "retired":
                removed_nodes.add(n["id"])
                continue
            if n["kind"] == "agent" and n.get("live"):
                why = nodes.agent_stale(n)
                if why:
                    node_gaps[n["id"]] = why
        timing.add("projects:setup:nodes", (time.monotonic() - _t1) * 1000)
    # ...and the phone each node has, from one read (R120): a row's Phone
    # button and the lease line it shows everybody on the project.
    with timing.timed("projects:setup:phones"):
        phones = phone.by_node(users.uid_of(who))
    # ...and the sharper answer for the Claude button: a node from another
    # WINDOW holds this project's sessions; one merely behind does not.
    with timing.timed("projects:setup:holds"):
        held_nodes = node_holds()
        # ...and the nodes with no Claude Code, whose Start Claude is an
        # Install Claude that opens the node's Toolchains (the operator, 21 Oct).
        no_claude = {} if NODES_OK else {i: i for i in claudecode.missing_nodes()}
    _t1 = time.monotonic()
    open_roadmap = roadmap.counts()
    # One batch spans the notebook, so the count the panel shows has to be
    # both halves added up; a banner reporting only the roadmap's would read
    # as "nothing much" while a dozen tracker changes sat unrecorded.
    roadmap_batches = roadmap.batches()
    for name, b in bugs.batches().items():
        if name in roadmap_batches:
            roadmap_batches[name]["changes"] += b.get("changes", 0)
            roadmap_batches[name]["at"] = min(roadmap_batches[name]["at"], b["at"])
        else:
            roadmap_batches[name] = b
    # Counts only. The notebook's six revisions used to ride here, which put
    # half of one tab on this fifteen-second poll while the other half rode
    # /api/revs at a second and a half; they are all on /api/revs now (see
    # revisions()), and this poll stopped paying to compute them.
    bug_counts = bugs.counts()          # open bugs per project, for the row and the app
    test_counts = testreg.counts()
    rule_counts = rules.counts()
    # What a session has waiting for the operator (roadmap #27): the count
    # lights the bell and the notebook band.
    pend_counts = pending.counts()
    timing.add("projects:setup:notebook", (time.monotonic() - _t1) * 1000)
    # The setup above, every file the whole list reads once, as one part.
    timing.add("projects:setup", (time.monotonic() - _t0) * 1000)
    out = []
    for f in facts:
        d, issues = f["dir"], f["issues"]
        branch, git_ok, linked, github = f["git"], f["git_ok"], f["linked"], f["github"]
        fhost, forge = f["fhost"], f["forge"]
        # Every directory is still reported. The dashboard decides what to show,
        # and SARIF paths are attributed by matching these names, so dropping
        # one here would silently orphan its findings.
        # Locking is reported by the boolean below and nothing else. It used to
        # add an issue too, which the row printed under the name: a whole
        # sentence restating what the padlock beside the name already says, on
        # every locked row, forever. It is also not a fault, and the issue list
        # is where faults go.
        with timing.timed("projects:session_at"):
            sa = _session_at(d.name)
        with timing.timed("projects:session_nodes"):
            sa["session_nodes"] = _session_nodes(d.name)
        with timing.timed("projects:memory"):
            mem_census = memory.census(d.name, home=home_for(users.uid_of(who)))
        # Its project's (R138): the marks and the people are kept by project.
        pk = repos.key_of(d.name)
        out.append({"name": d.name, "project": pk, "git": branch, "git_ok": git_ok,
                    # The name people see and the project's id (R154); `name`
                    # stays the directory, which every store keys by.
                    "label": str((reg.get(d.name) or {}).get("name") or d.name),
                    "pid": int((reg.get(d.name) or {}).get("id") or 0),
                    "linked": linked, "github": github,
                    # Which host it is linked to, for the chain to say so in
                    # its own words. "" when there is no remote to be on, and
                    # the ADDRESS rather than the catalog's generic label when
                    # nobody has said what that server runs: "Unlink from
                    # Another git host" names nothing a person could check.
                    "forge": forge["id"] if linked else "",
                    "forge_name": ("" if not linked
                                   else forge["name"] if forge["id"] != forges.OTHER["id"]
                                   else fhost or forge["name"]),
                    "forge_host": fhost,
                    "locked": pk in locked,
                    # ...an administrator's lock, which holds its owner too.
                    "locked_admin": bool(locked.get(pk, {}).get("admin")),
                    # ...and whether it holds this account out, as the server
                    # refuses: what the page shuts on.
                    "locked_me": pk in locked and bool(projects.locked_out(d.name, me_uid or users.uid_of(who))),
                    "archived": pk in archived,
                    "owner_name": membership.owner_name(d.name) or "",
                    "owner_mine": bool(me_uid) and membership.owner_of(d.name) == me_uid,
                    "may_lock": lock_may(d.name, me_uid, me_admin, locked.get(pk)),
                    "may_archive": me_admin or (bool(me_uid) and membership.owner_of(d.name) == me_uid),
                    "pinned": True if pins is None else pk in pins,
                    # The group this account files it under, or "".
                    "group": groups.get(pk, ""),
                    # ...and the color it gives it, or "".
                    "color": colors.get(pk, ""),
                    # Whether it carries its own access token, so the rename
                    # dialog can offer to change one without offering to
                    # invent one for a local repo that never had any.
                    "has_token": (STATE / "gitcreds" / d.name).is_file(),
                    # A brief waiting for the first Claude session: the
                    # Claude button opens its dialog rather than a session.
                    "brief": brief.pending(d.name),
                    "push": projects.may_push(d.name),
                    # The project's own settings: its node, what build and
                    # test run, the gates. NOT the model, the effort or the
                    # commit author, which are whoever is asking's.
                    "prefs": project_prefs.get(d.name, {}),
                    # Who may move its version (version.py's policy), for the
                    # settings panel's Move the version dial.
                    "version_policy": version.policy(d.name),
                    # ...and this account's own, on this project. On the row
                    # because the settings dialog draws from the poll like
                    # every other field it shows, and per account because two
                    # people on one project are two authors on two models.
                    # `yours`, because `mine` on this row is already taken by
                    # may_work: whether the project is this account's to change.
                    "yours": mine_prefs.get(d.name, {"model": "", "effort": "", "reply": "", "asks": "",
                                                     "git_name": "", "git_email": "", "term_scheme": ""}),
                    # Any model through a router (R144): the models the
                    # router allows this project, with their context and
                    # price, and what the project has spent through it.
                    "router": _router_row(d.name),
                    # Whether a commit here would carry an author, asked WITH
                    # the override: somebody whose Profile has no email can
                    # still set one for this project, and then a session may
                    # start and push here even though the global flag is off.
                    "git_ready": _row_git_ready(base_git, mine_prefs.get(d.name))
                                 if users.uid_of(who) else True,
                    "push_how": projects.push_how(d.name),
                    # Whether its settings are this account's to change (B19):
                    # the page locks them, with the reason, where not.
                    "may_settings": not users.may(who, "settings", d.name) if who else True,
                    # ...and the reason where not, which the Snapshots and
                    # Running sessions sections say without asking for what
                    # they would only be refused (B89).
                    "settings_why": users.may(who, "settings", d.name) if who else "",
                    # ...and why its notebook, its tree and the project itself
                    # are not this account's to change, or "" (B86): a role
                    # that gives Projects Read alone sees the page with every
                    # writing control dead and this said under it, rather
                    # than each refused only at the press.
                    "write_why": users.may(who, "write", d.name) if who else "",
                    "trash_why": users.may(who, "trash", d.name) if who else "",
                    # ...and why its version is not this account's to move or
                    # release (Releases and versions Write), for the
                    # Artifacts view's bumps, Release and Set (B101).
                    "release_why": users.may(who, "version", d.name) if who else "",
                    # Whether this project has a compose file, which is the
                    # same question as "could its tests run in a container of
                    # its own": the settings dialog offers that choice only
                    # where there is something to run in (R68 step 6).
                    "has_compose": devapp.project_has_compose(d.name),
                    # The newest transcript, read through the home's link
                    # onto the projects share (lib/common.sh's
                    # claude_projects_link), so a conversation a node's
                    # session had is offered here and continued there.
                    "last_claude": last_claude(d, users.uid_of(who)),
                    # ...and each other coding agent's newest, for its own
                    # Resume in the chooser (the operator, 23 Oct: a ChatGPT
                    # conversation was there and nothing offered it back).
                    "last_agents": last_agents(d, users.uid_of(who)),
                    # Where this project's sessions run (roadmap #24): the
                    # node's name, or "" for here, and why the button is
                    # dead when its node cannot take one. The proxy decides
                    # the same way, so the row and the refusal agree.
                    **sa,
                    # What Claude remembers here. On the row because a memory
                    # nobody knows about is the one that goes wrong quietly.
                    "memories": mem_census["count"],
                    # ...and what is still to do, which is the number on the row
                    # actually worth glancing at.
                    "roadmap": open_roadmap.get(d.name, 0),
                    # So the open notebook learns a session has started one
                    # without waiting for the operator to touch something.
                    "todo_batch": roadmap_batches.get(d.name),
                    "bugs": bug_counts.get(d.name, 0),
                    "tests": test_counts.get(d.name, 0),
                    # The test run going right now, if `bb test` said so:
                    # {since, cmd, by}, or null. The companion app times
                    # its turn note by it and the project's During-a-test-run
                    # setting.
                    "testing": testreg.running(d.name),
                    "rules": rule_counts.get(d.name, 0),
                    "pending": pend_counts.get(d.name, 0),
                    # Why nothing routed to this project's node runs right
                    # now (its agent behind, or from another window), so
                    # the Artifacts tab and the bell say so before a job is
                    # refused. "" is the ordinary state.
                    "node_gap": node_gaps.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    # Which node this project's work runs on, by name, or ""
                    # for none: the row says "(node: X)" beside the name.
                    "node_name": node_names.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    # The project's node was un-enrolled: the settings picker
                    # keeps it, marked, and the row says why Claude is off.
                    "node_removed": (project_prefs.get(d.name, {}).get("node") or "") in removed_nodes,
                    # The phone on its node: whose, whether it is this
                    # account's, and whom it is lent to (R120).
                    "phone": phones.get(project_prefs.get(d.name, {}).get("node") or ""),
                    # Why no Claude session may run here right now, or "":
                    # its own node's agent is from another compatibility
                    # window. The button ghosts on this and bb-tty refuses on
                    # the same fact; the sweep ends what is running. Per
                    # project: another project's node being out of window is
                    # not this row's hold.
                    # The project's node, when it has no Claude Code, or "".
                    "claude_missing": no_claude.get(project_prefs.get(d.name, {}).get("node") or "", ""),
                    "held": held_nodes.get(
                        project_prefs.get(d.name, {}).get("node") or "", "")
                    # ...or its map is still building (mapping.py): the
                    # same ghosting, for the seconds it takes.
                    or mapping.held(d.name),
                    "issues": issues})
    return out


def _legacy_colors(project_prefs):
    """The colors projects wore while a color was the project's, {name:
    color}: where an account that has picked none starts."""
    return {n: (pr or {}).get("color") or "" for n, pr in (project_prefs or {}).items()}


def _projects_seen_by(who, rows):
    """Which of the rows the account asking may see at all, and which of
    those are its to work on (`mine`, users.may_work). The one decision
    about who sees what, made last, over rows that were described without
    regard to it.
    """
    # The last thing, so everything above it stays one description of the
    # share and this stays one decision about who sees it.
    #
    # Two decisions now, and they are different questions. A `user` is shown
    # only what it was given, because a project it cannot work on is one it
    # has no reason to know exists. An ADMINISTRATOR is shown everything and
    # told which of them are theirs to change: hiding a project from somebody
    # who administers the box would only send them looking for it, and the
    # list they keep is a seatbelt against editing the wrong one rather than a
    # wall (users.may_work).
    # By project (R138): an account's list names projects, and a repository
    # is seen when its project is on it.
    if not users.sees_all(who):
        rows = [p for p in rows if users.may_see(who, p["name"])]
    for p in rows:
        p["mine"] = users.may_work(who, p["name"])
    return rows


def project_list(who):
    """_project_list, timed (timing.py): nearly every read asks for it."""
    with timing.timed("project_list"), nodes.held():
        return _project_list(who)


def _project_list(who):
    """Every directory under /workspace that is a project, with what is wrong
    with it. Named _list because `projects` is the module beside this one that
    creates them: one name for the reading and one for the writing.

    `who` is the account asking (Handler._who()), and it is REQUIRED rather
    than defaulted for the reason the whole scheme leans on: this is the one
    function that decides which projects exist, and a call site that forgot to
    say who was asking would quietly show every project to everybody. Missing
    it is a TypeError, which a test finds; defaulting it would be a hole
    nothing finds. The server's own non-request contexts pass users.ALL and
    say so.

    Filtering here is also most of the authorization. Fifteen handlers ask
    "is this a project?" against this list, so a project somebody cannot see
    is not refused to them: it does not exist, which is the same answer a
    typo gets and leaks nothing by comparison.
    """
    facts, fault = _projects_on_disk()
    if fault is not None:
        return fault
    return _projects_seen_by(who, _project_columns(who, facts))


def session_cwds():
    """Session name -> {cwd, title} of its active pane.

    cwd is where a terminal *is* right now, which is not where it was opened:
    the tab is labeled from this, so a `cd` shows up in the strip. The pane
    title rides along because for Claude sessions it is a status report;
    see claude_state below.
    """
    # Title last and split bounded, so a title containing a tab cannot shift
    # the fields before it.
    r = run(["tmux", "list-panes", "-a", "-F",
             "#{session_name}\t#{pane_active}\t#{pane_current_path}\t#{pane_title}"],
            timeout=10)
    out = {}
    if r["code"] != 0:
        return out
    for line in r["out"].splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4 and parts[1] == "1":
            out[parts[0]] = {"cwd": parts[2], "title": parts[3]}
    return out


# Claude Code reports its state through the terminal title, and tmux keeps
# that per pane. Observed lifecycle (verified against a live session, not
# guessed from docs): a working session's title starts with an animated
# spinner glyph and the task summary ("◐ Fix the login flow"); one waiting
# for input starts with ✳ ("✳ Claude Code" fresh, "✳ Fix the login flow"
# after a turn). Before the REPL (trust dialog, theme picker) no title is
# set at all, which the spinner rule correctly reads as "waiting": those
# screens are waiting for input.
#
# Activity timestamps are deliberately NOT the signal here: the TUI goes
# quiet while a long tool call runs, so "no output lately" cannot tell a
# session hard at work from one sitting at the prompt.
SPINNER_GLYPHS = tuple("◐◓◑◒")


def gpu_for(project, node_id=""):
    """Whether a session on `project` may compute on its node's NVIDIA card
    (R102): "on"; "node" when the node's switch is off; "project" when the
    project's own setting is. The project's says no first, being the
    narrower of the two. The node is the one the session was started on,
    else the project's own."""
    p = prefs.get(project) or {}
    if p.get("gpu") == "off":
        return "project"
    if not NODES_OK:
        nid = node_id or p.get("node") or ""
        n = nodes.node(nid) if nid else None
        if n and (n.get("config") or {}).get("no_gpu_compute"):
            return "node"
    return "on"


# What a Resume says to a session an outage held (R251): the gate told it to
# write where it was and stop, so this is where it picks up.
RESUME_LINE = ("BuilderBot is back after an update. Pick up where you stopped: read the note you "
               "left on where you were and what was next, and carry on.")


def _resume_held(who, nid, session):
    """The bell's Resume on a session an outage stopped (R251): the line typed
    into that session (notify.tell, which presses Enter only if it echoed),
    for its own account or an administrator, and the row put away."""
    if NODES_OK:
        return {"error": "the node store did not open"}, 500
    uid = users.uid_of(who)
    row = next((r for r in _held_rows(who) if r["node_id"] == nid and r["session"] == session), None)
    if not row:
        return {"error": "no session held there that is yours to resume"}, 404
    said = notify.tell(row["claude"], RESUME_LINE, sessions_anywhere(), who=who)
    if said.get("error"):
        return said, 409
    # Put away only once it went (B775): a line typed into a session busy in
    # a turn or its Stop hook sits unsent in the box, and the row put away
    # with it left nothing saying the session was still waiting.
    if said.get("sent"):
        bellseen.dismiss(uid, [row["key"]])
    return {"ok": True, **said}, 200


def _att_words(a):
    """One attention row as a title and a line, for the bell sent elsewhere
    (reach.py): the page's words (page-bell.js attRow), said once here."""
    k, node, proj = a.get("kind"), a.get("node") or a.get("node_name") or "", a.get("project") or ""
    label = registry.label(proj) if proj else ""
    if k in ("toolchain", "agents"):
        n = len(a.get("tools") or [])
        return (f"{n} {'coding agent' if k == 'agents' else 'toolchain'} update{'' if n == 1 else 's'} on {node}",
                ", ".join(t.get("label", "") for t in a.get("tools") or []))
    if k == "agent":
        return (f"{node}'s agent is out of window" if a.get("window") else f"Agent update on {node}",
                f"runs agent {a.get('from', '')} and this controller ships {a.get('to', '')}")
    if k == "held":
        return (f"A session in {label} stopped for the update", f"on {node}")
    if k == "relocate":
        return (f"Copying or moving {a.get('name', '')} did not happen", a.get("why", ""))
    if k == "release-sign":
        return (f"{a.get('tag', '')}'s APK in {label} is not signed" if a.get("bad") else f"Signing in {label}", a.get("why", ""))
    if k == "git-unlinked":
        return (f"{label} has no git access", a.get("why", ""))
    if k == "project-leftover":
        return (f"{label} can be deleted", a.get("why", ""))
    if k == "schedule":
        return (f"{a.get('name') or 'A schedule'}: {'its run did not work' if a.get('bad') else 'a run was skipped'}", a.get("why", ""))
    if k == "image":
        n = len(a.get("containers") or [])
        return (f"{n} container update{'' if n == 1 else 's'} on {node}", ", ".join(c.get("name", "") for c in a.get("containers") or []))
    if k == "room":
        return (f"{node} is running short of room", "; ".join(str(x) for x in (a.get("parts") or a.get("short") or [])))
    if k == "two-factor":
        return ("A role of yours requires two-factor sign-in" if a.get("required") else "Turn on two-factor sign-in", "")
    if k == "token-read":
        return (f"A sign-in on {node} was read", f"{a.get('comm') or 'a process'} opened it")
    if k == "token-reuse":
        return (f"{node}'s credential was used from a copy", "every token of that node is revoked")
    if k == "acme":
        return (f"{'no certificate' if a.get('bad') else 'a certificate'} for {a.get('host', '')} on {node}", a.get("why", ""))
    if k == "scan":
        return (f"{'Scan failed' if a.get('what') == 'failed' else 'Scanner update'} on {node}", a.get("said", ""))
    if k == "nginx":
        return (f"nginx update on {node}", f"runs {a.get('from', '')} and {a.get('to', '')} is out")
    return (str(k or "attention"), a.get("why") or a.get("text") or "")


def _ask_words(a):
    """An ask in one line, the page's (page-bell.js askTag)."""
    k, proj = a.get("kind"), a.get("project") or ""
    label = registry.label(proj) if proj else "a project"
    node = a.get("node_name") or "the default node"
    return {"root": f"root on {node}", "rebuild": f"{' '.join(a.get('cmd') or [])[:60]} in {label}",
            "container": f"container {a.get('name') or ''} on {node}", "sign": f"sign a build of {label}",
            "sign-key": f"a signing key change in {label}", "release": f"release {label} {a.get('tag') or ''}",
            "release-edit": f"edit the {a.get('tag') or ''} release of {label}", "release-sign": f"sign the release APKs of {label} again",
            "release-remove": f"remove files from the {a.get('tag') or ''} release of {label}",
            "phone-use": f"your phone, from {label}", "push": f"a push from {label} looks sensitive"}.get(k, "a session") + ": needs your answer"


def _bell_rows_for(who):
    """The bell as the page draws it, composed here for the rows sent
    elsewhere (reach.tick): [{key, kind, title, text, url}], each keyed so
    a repeat is held while unchanged. Kinds: asks, needs, ci, invites,
    sync."""
    if not who:
        return []
    uid = users.uid_of(who)
    out = []
    try:
        for a in phone.requests_open(uid, users.is_admin(who)):
            out.append({"key": f"ask:{a.get('id')}", "kind": "asks", "title": _ask_words(a),
                        "text": " ".join(a.get("cmd") or [])[:200] if a.get("kind") != "rebuild" else "", "url": ""})
    except Exception as e:                                      # noqa: BLE001 (one source failing is not the bell's end)
        print(f"[dashboard] reach: the asks could not be read: {type(e).__name__}: {e}", flush=True)
    att, _hidden = _attention(who)
    for a in att:
        key = a.get("key") or f"{a.get('kind')}:{a.get('id') or a.get('node') or a.get('project') or ''}@{a.get('to') or a.get('at') or ''}"
        t, text = _att_words(a)
        out.append({"key": "need:" + key, "kind": "needs", "title": t, "text": text, "url": ""})
    tf = _two_factor_due(who)
    if tf:
        t, text = _att_words(tf)
        out.append({"key": "need:" + (tf.get("key") or f"2fa:{uid}"), "kind": "needs", "title": t, "text": text, "url": ""})
    for c in bellseen.filter_rows(uid, ciwatch.red(project_names(who)))[0]:
        out.append({"key": c["key"], "kind": "ci", "title": f"CI failing in {registry.label(c['project'])}", "text": c.get("text", ""), "url": c.get("url", "")})
    for i in membership.mine(who):
        out.append({"key": f"invite:{i['id']}", "kind": "invites", "title": f"{i.get('by') or 'Somebody'} invited you to {registry.label(i['project'])}", "text": "", "url": ""})
    for c in wssync.conflicts(lambda p: users.may_see(who, p)):
        out.append({"key": f"sync:{c.get('project')}:{c.get('kept_as')}", "kind": "sync",
                    "title": f"Changed in two places: {registry.label(c.get('project', ''))}", "text": f"{c.get('path', '')}, kept as {c.get('kept_as', '')}", "url": ""})
    return out


def _page_url():
    """Where the page is reached, for a link in a message: the hostname
    the Connection or the tunnel names, else nothing."""
    host = settings.get("tls_host") or settings.get("tunnel_host") or ""
    return f"https://{host}/" if host else ""


def _own_node_id():
    """The controller's own machine's node (R90), or "": where a bare-metal
    install's update runs."""
    return next((n["id"] for n in nodes.node_list() if nodes.own_machine(n) and n.get("state") != "retired"), "")


def _reach_loop():
    """The minute loop (R149): each person's bell to the destinations they
    keep, what is new, outside their quiet window."""
    while True:
        time.sleep(60)
        try:
            people = {u.get("uid") for u in users.all_users() if u.get("uid")}
            by_uid = {u.get("uid"): u for u in users.all_users() if u.get("uid")}
            reach.tick(lambda uid, m=by_uid: _bell_rows_for(m.get(uid)), people, _page_url())
        except Exception as e:                                  # noqa: BLE001 (the loop outlives one bad pass)
            print(f"[dashboard] reach: {type(e).__name__}: {e}", flush=True)


def _two_factor_due(who):
    """The bell's standing notice (R127 step 8), or None: an account with no
    second factor is told to add one, put away for a day at most (its key
    holds the day), gone the moment it has one."""
    uid = users.uid_of(who)
    if not uid or (who or {}).get("session") or mfa.enabled(uid):
        return None
    required = roles.two_factor_required(users.get(who["name"]) or {})
    key = f"2fa:{uid}@{time.strftime('%Y-%m-%d')}"
    if not required and key in bellseen.dismissed(uid):
        return None
    return {"kind": "two-factor", "key": "" if required else key, "required": required}


def _token_rows():
    """nodes.token_attention, each read with its account's name."""
    rows = nodes.token_attention()
    if rows:
        names = {u["uid"]: u["name"] for u in users.all_users()}
        for r in rows:
            r["who"] = names.get(r["account"], "")
    return rows


def _held_rows(who):
    """nodes.held_attention for this account, each row with the account's
    name and its Claude session's name on that project (B773): the gate's
    mark names the ACCOUNT (bb-tty writes `bb-gate PROJECT ACCOUNT`), and
    Resume typed into a session called that, which there never is."""
    names = {u["uid"]: u["name"] for u in users.all_users()}
    rows = nodes.held_attention(users.uid_of(who), users.may(who, "admin") == "")
    running = {s["name"] for s in tmux_sessions() + node_tmux_sessions()} if rows else set()
    for r in rows:
        r["who"] = names.get(r["uid"], "")
        # The agent's that is running, since the mark names the account and
        # the project, not which agent was held (R95 step 16).
        r["claude"] = running_session(users.tmux_prefix({"uid": r["uid"]}), r["project"], running)
    return rows


# A node is short of room under this much free on its root filesystem,
# Docker's or a store, or with this much of its memory used over ten
# minutes (R110): the bell says so before the machine stops. Controller
# settings, Room.
def room_floor_gb():
    return settings.get("room_floor_gb")


def room_mem_pct():
    return settings.get("room_mem_pct")


CACHE_KEEP_DAYS = 14      # a project's build cache no job has used this long goes when its store is short
PHONE_SNAPSHOT_DAYS = 7   # a phone not started this long gives back its quick-boot snapshot when its disk is full


def schedule_queue(s, argv, by):
    """One run of a schedule as a job on its node (R117): an exec job as the
    node's jobs account, or a system job as root on a node provisioned as a
    sandbox, as `bb root run` is (nodes.root_wait's gate), never waited
    for. {job} or {error}."""
    nid = s.get("node") or ""
    n = nodes.node(nid) if nid else None
    if not n:
        return {"error": "its node is not enrolled any more: pick another"}
    t = int(s.get("timeout") or schedules.TIMEOUT_DEFAULT)
    principal = "schedule:" + str(s.get("id") or "")
    if s.get("as") == "root":
        if not (n.get("reported") or {}).get("sandbox"):
            return {"error": f"{n['name']} was not provisioned as a BuilderBot sandbox, so root there is its owner's: "
                             "run it as the jobs account, or on a sandbox node"}
        if nodes.system_job_for(nid):
            return {"error": f"a system job is already running on {n['name']}; one at a time"}
        spec = {"apply": "root", "timeout": t,
                "config": {"argv": argv, "why": f"the schedule {s.get('name', '')}", "by": by, "timeout": t}}
        r = nodes.job_add(principal, {"node": nid}, "system", spec)
    else:
        r = nodes.job_add(principal, {"node": nid}, "exec",
                          {"argv": argv, "timeout": t, "title": f"schedule: {s.get('name', '')}"[:120]})
    if r.get("job"):
        db.audit(by, "schedule-run", nid, {"schedule": s.get("id"), "job": r["job"], "as": s.get("as")})
    return r


def _job_state(jid):
    return ((nodes.job(jid, with_log=False) or {}).get("state") or "") if jid else ""


def _schedules_loop():
    """The schedules' timer (R117): every half minute, what is due fires
    (schedules.tick: one run at a time, a missed one run once and said)."""
    while True:
        time.sleep(30)
        try:
            scanners.tick()
            schedules.tick(schedule_queue, _job_state)
        except Exception as e:  # noqa: BLE001 (a bad schedule never stops the timer)
            print(f"dashboard: schedules: {type(e).__name__}: {e}", flush=True)


def _ci_log_text(got):
    """A CI run as a log tab shows it (R133 step 12): the run, then each job
    with how it ended and the end of its log, the lines above that a failure
    named, as bb ci-log prints them."""
    r = got.get("run") or {}
    out = [f"{r.get('name', '')} #{r.get('id', '')} on {r.get('branch', '')}: {r.get('conclusion', '')}  {r.get('url', '')}", ""]
    for j in got.get("jobs") or []:
        out.append(f"== {j.get('name', '')}: {j.get('conclusion', '')}"
                   + (f", at {j['failed_step']}" if j.get("failed_step") else ""))
        if j.get("earlier"):
            out += ["-- earlier, the lines that named a failure:", j["earlier"], "-- the end of its log:"]
        if j.get("log"):
            out.append(j["log"])
        out.append("")
    return "\n".join(out)


def _room_loop():
    """Every hour, a node whose Docker disk has fallen under twice the floor
    gets its build cache a week old and its images no container has used
    for two weeks pruned (R110 step 3), before the bell's floor is reached;
    what Docker said it freed goes to the controller's log (bb logs), the
    prune itself to the audit log. Nothing a container
    uses is touched, and a node with room is left alone. A node whose cache
    store is as short gets the projects' build caches (Gradle's, npm's,
    pub's: whatever a build keeps under BUILDERBOT_CACHE) that no job has
    used for two weeks cleared by a cache-clear job (R110 step 7), its log
    on the Jobs page. A node whose homes' disk is past 90% gets its idle
    phones' quick-boot snapshots removed by a phones-idle job (R129)."""
    while True:
        time.sleep(3600)
        try:
            for n in nodes.node_list():
                if n["kind"] != "agent" or not n.get("live"):
                    continue
                if nodes.room_short(n["id"], room_floor_gb() * 2, ("cache",)):
                    r = nodes.job_add("operator", {"node": n["id"]}, "cache-clear",
                                      {"older_days": CACHE_KEEP_DAYS})
                    print(f"[room] {n.get('name') or n['id']}: build caches unused for "
                          f"{CACHE_KEEP_DAYS} days: {r.get('error') or 'clearing'}", flush=True)
                # The phones' quick-boot snapshots, where the homes' disk is
                # past 90% (R129): every project's not started for a week, the
                # phones themselves and their data kept.
                if nodes.homes_full(n["id"]):
                    r = nodes.job_add("operator", {"node": n["id"]}, "phones-idle",
                                      {"older_days": PHONE_SNAPSHOT_DAYS})
                    print(f"[room] {n.get('name') or n['id']}: idle phones' quick-boot snapshots: "
                          f"{r.get('error') or 'removing'}", flush=True)
                why = nodes.room_short(n["id"], room_floor_gb() * 2)
                if not why:
                    continue
                with devapp.on_node(n["id"]):
                    said = {k: devapp.prune(k) for k in ("cache", "unused")}
                db.audit("builderbot", "room-prune", n.get("name") or n["id"], {"kinds": sorted(said)})
                for k, v in said.items():
                    print(f"[room] {n.get('name') or n['id']}: pruned {k}: "
                          f"{v.get('error') or (v.get('out') or 'nothing').splitlines()[-1][:200]}", flush=True)
        except Exception as e:                                       # noqa: BLE001 (the loop must live)
            print(f"[room] {type(e).__name__}: {e}", flush=True)


def _tls_issue():
    """A Let's Encrypt certificate for the Connection section's hostname
    asked for now (tls.issue_acme), by a DNS-01 record through the
    Cloudflare API token with nginxproxy's hooks: {ok, started} or {error}."""
    if tls.mode_of(settings.get) != "acme":
        return {"error": "the Connection section is not set to a Let's Encrypt certificate"}
    token = settings.secret("cf_api_token")
    if not token:
        return {"error": "a DNS-01 challenge writes the record through Cloudflare's API: set the Cloudflare API token under Reach from outside first"}
    import acme as acme_mod                                     # noqa: PLC0415

    def present(kind, name, tok, value):
        del kind, tok
        err = nginxproxy._cf_txt(token, f"_acme-challenge.{name}", value)
        if err:
            raise acme_mod.AcmeError(f"Cloudflare refused the record: {err}")
        time.sleep(15)

    def cleanup(kind, name, tok, value):
        del kind, tok
        nginxproxy._cf_txt(token, f"_acme-challenge.{name}", value, delete=True)
    return tls.issue_acme(settings.get, nginxproxy.ACME_DIRECTORY, nginxproxy._acme_account_pem(), present, cleanup)


def _tls_names(host=""):
    """What the install's own certificate names (R158 step 2): the
    Connection section's hostname, the tunnel's, the machine's own name and
    addresses, and the Host the request came to."""
    out = [str(settings.get("tls_host") or ""), str(settings.get("tunnel_host") or ""),
           socket.gethostname(), host.split(":")[0] if host else ""]
    with contextlib.suppress(OSError):
        for info in socket.getaddrinfo(socket.gethostname(), None):
            out.append(info[4][0])
    seen, keep = set(), []
    for n in out:
        n = n.strip().lower()
        if n and n not in seen and not n.startswith("127.") and n != "::1":
            seen.add(n); keep.append(n)
    return keep


def _givers_said(project, me):
    """Who has given this project a token (R159): [{uid, name, login, host,
    mine, live}], never the token."""
    names = {u.get("uid"): u.get("name") for u in users.all_users() if u.get("uid")}
    out = []
    for uid, fid in gitcreds.givers(project):
        fg = accountkeys.forge_of(uid, fid) or {}
        out.append({"uid": uid, "name": names.get(uid) or "an account that is gone", "login": fg.get("login", ""),
                    "host": fg.get("host", ""), "mine": uid == me, "live": logins.live(uid)})
    return out


_BRIEF_TOKENS = {}      # project -> (at, tokens): what the briefing takes, for the picker


def _briefing_tokens(name):
    """About how many tokens the block a session is handed takes (bytes over
    four), assembled at most every two minutes per project: the chooser
    says when a model's context cannot hold it (R144 step 3)."""
    at, n = _BRIEF_TOKENS.get(name) or (0, 0)
    if time.time() - at > 120:
        try:
            n = len(preamble.block(name).encode("utf-8")) // 4
        except Exception:                                          # noqa: BLE001 (a guess, said as one)
            n = 0
        _BRIEF_TOKENS[name] = (time.time(), n)
    return n


def _router_row(name):
    """{models, spend, rate, briefing_tokens} for a project a router allows,
    or None; cheap, since the record is one small file read on every poll
    and the briefing's size is kept for two minutes."""
    models = router.models_for(name)
    if not models:
        return None
    return {"models": [{"id": m["id"], "provider": m.get("provider", ""), "context": m.get("context", 0),
                        "in_cost": m.get("in_cost", 0), "out_cost": m.get("out_cost", 0), "walked": bool(m.get("walked"))} for m in models],
            "spend": router.spend_for(name), "rate": router.rate_for(name), "briefing_tokens": _briefing_tokens(name)}


def _name_of_uid(uid):
    return next((u.get("name") for u in users.all_users() if u.get("uid") == uid), "") or ""


def _token_said(project, me):
    """What git work by `me` on this project runs with (gitcreds.usable),
    the giver named rather than numbered."""
    u = gitcreds.usable(project, me)
    names = {x.get("uid"): x.get("name") for x in users.all_users() if x.get("uid")}
    return {**u, "name": (names.get(u.get("by")) or "") if u.get("by") else ""}


def _attention(who):
    """The bell's rows about nodes: an agent behind or from another window
    (nodes.attention) for whoever manages nodes, and a node with a
    toolchain behind what is out, Claude Code among them
    (toolchains.attention), for whoever may install toolchains on it."""
    # A release's APK the controller could not sign, or would not be able
    # to (releasesign.attention, R106), for whoever sees the project: said
    # before the release, not after it went out without one.
    signs = releasesign.attention([p for p in releasesign.projects_fn() if users.may_see(who, p)])
    # ...and a project whose git access went with an account's key store
    # (R154), for whoever sees it.
    signs += gitcreds.gone_rows([p for p in gitcreds.gone_projects() if users.may_see(who, p)])
    # ...and an empty project 0.8.0's B402 left beside its repository's,
    # for whoever may delete it.
    signs += [{"kind": "project-leftover", "id": key, "key": f"leftover:{key}", "project": key,
               "repo": d, "in": repos.project_of(d),
               "why": f"it is empty: {registry.label(d)} went into {registry.label(repos.project_of(d))} "
                      "when it was made, and this one was left beside it by a bug in 0.8.0"}
              for key, d in repos.leftovers()
              if users.may_see(who, key) and (users.is_admin(who) or membership.may_manage(who, key))]
    if NODES_OK:
        return bellseen.filter_rows(users.uid_of(who), signs)
    where = {p: (pr.get("node") or "") for p, pr in prefs.all_projects().items()}
    # The sessions an outage of this controller held come first (R251), for
    # their own account or an administrator: stopped work waiting on a
    # person, where the rest is an update that can wait (seen fourth, under
    # the fold of the bell, in the walk of 15 Oct).
    rows = (_held_rows(who)
            + ([] if users.may(who, "node") else nodes.attention(where) + _token_rows()
               # ...and a newer release for a bare-metal install (R90 step 5).
               + releasecheck.attention(_own_node_id()))
            # ...and a node short of disk or memory (R110), for whoever
            # manages nodes: what is short, on the Storage page's terms.
            + ([] if users.may(who, "node") else nodes.room_attention(
                room_floor_gb(), room_mem_pct(),
                label=lambda r: {"root": "its root filesystem", "docker": "Docker's images and build cache"}.get(r, f"its {r} store")))
            + [a for a in toolchains.attention(where) + toolchains.agent_attention(where)
               if not users.may_node(who, "toolchains-write", a["id"])]
            # ...and a node's nginx behind the newest line (nginxproxy.attention,
            # R192), for whoever may act on the Docker tab, which Update is.
            + ([] if users.may(who, "docker-write")
               else nginxproxy.attention(lambda nid: nginxproxy.deployed(devapp, nid)) + nginxproxy.acme_rows()
               # ...and a scanner run that failed, or a node behind the
               # newest scanner versions (scanners.attention, R145).
               + scanners.attention()
               # ...and a container whose registry image moved (imagecheck, R195).
               + imagecheck.attention(lambda nid: (nodes.node(nid) or {}).get("name") or nid,
                                      allowed=lambda p: users.may(who, "docker-write", p) == ""
                                      if p and users.may_work(who, p) else users.is_admin(who))
               # ...and a copy or move that did not happen (relocate.py).
               + relocate.attention(lambda nid: (nodes.node(nid) or {}).get("name") or nid))
            # ...and a schedule whose last run failed or was skipped (R117),
            # for whoever may read the Schedules page.
            + ([] if users.may(who, "schedules-read") else schedules.attention(_job_state))
            + signs)
    # ...less what this account has put away (bellseen.py, R144): an update
    # to a version it dismissed, until a newer one is out.
    return bellseen.filter_rows(users.uid_of(who), rows)


def _claude_code_for(who, ps):
    """Claude Code per node against the latest known, for the Nodes page's
    section: the registry's for whoever may manage nodes, and for anybody
    else the nodes their own projects are on, which are the ones that tab
    shows them."""
    cc = claudecode.payload()
    if not users.may(who, "node"):
        return cc
    mine = set()
    for p in ps:
        pr = prefs.get(p["name"])
        mine.update([pr["node"], *(pr.get("nodes") or [])])
    return cc | {"nodes": {k: v for k, v in cc["nodes"].items() if k in mine}}


def gpu_container_why(project, node_id):
    """Why a container of `project` on that node cannot be given its NVIDIA
    card, or "" (R102): the project's setting and the node's switch, which
    speak for containers as they do for sessions, then what the node's
    Toolchains page holds (the driver running the card, the container
    toolkit, Docker's runtime)."""
    who = gpu_for(project, node_id)
    if who == "project":
        return "this project's settings say the node's GPU is not for it (The node's GPU)"
    n = nodes.node(node_id) if node_id and not NODES_OK else None
    if who == "node":
        return f"{n['name'] if n else 'its node'}'s GPU is switched off for sessions and jobs (Nodes page, GPU)"
    return toolchains.container_why(n)


# Sessions sitting on Claude Code's own permission prompt (B52), set by the
# session's Notification hook (hooks.py "asking") under its account and its
# tmux name. The pane title cannot say it: a prompt reads as waiting, like a
# session with nothing to do. Gone once it works again, its turn ends or it
# is sent a prompt; "working" counts only a few seconds after the mark,
# since the title can still carry the spinner as the prompt appears.
ASKING = {}
ASKING_SETTLE = 4


def asking_set(project, uid, text="", agent="claude", slot=1):
    ASKING[(uid, tmux_name(agents.session_name(agent, project, slot)))] = {"at": time.time(), "text": str(text or "")[:300]}


def asking_clear(project, uid, agent="claude", slot=1):
    ASKING.pop((uid, tmux_name(agents.session_name(agent, project, slot))), None)


# What another agent's session is doing (R95 step 7), as its hooks said it:
# working from the prompt its turn began on, waiting once the turn ended.
# Claude's reads its pane title, which no other agent's carries.
AGENT_STATE = {}


def agent_state_set(project, uid, agent, state, slot=1):
    AGENT_STATE[(uid, tmux_name(agents.session_name(agent, project, slot)))] = {"state": state, "at": time.time()}


# Which conversation each agent session is in (R143), as its hooks said with
# the prompt that began a turn: so one live in one slot is not resumed into
# another, and the chooser shows it as running rather than offering it.
AGENT_CONV = {}
_CONV_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,99}")


def agent_conv_set(project, uid, agent, slot, conv):
    if _CONV_ID.fullmatch(str(conv or "")):
        AGENT_CONV[(uid, tmux_name(agents.session_name(agent, project, slot)))] = str(conv)


def session_state(uid, name, title):
    """(state, task) for a Claude session: claude_state's, or "asking" while
    it waits on its permission prompt, the prompt's words as the task.
    Another agent's session says nothing yet (R95 step 7 reads its own
    events): Claude Code's pane title is no other agent's, and a session
    read as waiting when it was working would call a person for nothing."""
    agent, _stem = agents.of_session(tmux_base(name))
    if agent and agent.id != "claude":
        k = (uid, tmux_base(name))
        a = ASKING.get(k)
        if a:
            return "asking", a["text"] or "waiting for you to answer it in its terminal"
        return (AGENT_STATE.get(k) or {}).get("state", "waiting"), ""
    state, task = claude_state(title)
    k = (uid, tmux_base(name))
    a = ASKING.get(k)
    if a:
        if state == "working" and time.time() - a["at"] > ASKING_SETTLE:
            ASKING.pop(k, None)
        else:
            return "asking", a["text"] or "waiting for you to answer it in its terminal"
    return state, task


def claude_state(title):
    """(state, task) for a Claude pane title: "working" or "waiting"."""
    working = title.startswith(SPINNER_GLYPHS)
    task = title.lstrip("".join(SPINNER_GLYPHS) + "✳ ").strip()
    # A title Claude never set (tmux's hostname default) carries no task; a
    # fresh session's "Claude Code" is a name, not a task.
    if not title.startswith(SPINNER_GLYPHS + ("✳",)) or task == "Claude Code":
        task = ""
    return ("working" if working else "waiting"), task


# The `u:<uid>:` a browser may have sent on a terminal argument, which is
# stripped before the real one is put on. Anchored, so it can only ever take
# a prefix off the front.
_ARG_OWNER = re.compile(r"^u:[^:]*:")
# `:n:NODE` on a claude: argument: which of the project's nodes the person
# picked for this session (R82). Read here and taken off before the proxy,
# since bb-tty on the node reads the argument's tail by suffix (:r:, :b:)
# and would take the node for part of the project's name.
_ARG_NODE = re.compile(r":n:([A-Za-z0-9_-]+)")


def _arg_node(arg):
    m = _ARG_NODE.search(arg or "")
    return m.group(1) if m else ""


# `ctr:NAME:INSTANCE:CONTAINER`: a shell inside one container of a dev
# instance (R218 step 4), NAME the project or the container written here
# whose instance it is. Names in the shapes docker and the store allow and
# nothing else, since each reaches docker exec on a node.
_ARG_CTR = re.compile(r"^ctr:([A-Za-z0-9][A-Za-z0-9._-]*):([A-Za-z0-9][A-Za-z0-9._-]*):"
                      r"([A-Za-z0-9][A-Za-z0-9_.-]*)$")


# `log:ctr:NAME:INSTANCE:CONTAINER`: a container's log in a dock tab (R133
# step 12), followed on its node by docker logs as the docker account.
_ARG_LOGCTR = re.compile(r"^log:ctr:([A-Za-z0-9][A-Za-z0-9._-]*):([A-Za-z0-9][A-Za-z0-9._-]*):"
                         r"([A-Za-z0-9][A-Za-z0-9_.-]*)$")


# `vm:PROJECT:NAME`: a VM's serial console (R91), opened on its node's
# container terminal server, as the jobs account, with virsh console.
_ARG_VM = re.compile(r"^vm:([A-Za-z0-9][A-Za-z0-9._-]*):([a-z0-9][a-z0-9-]{0,30})$")


def vm_target(project, name):
    """Where a VM's console opens: its node's container terminal server,
    which runs as the jobs account the VM was made by. A refusal says why,
    in ctr_target's words."""
    rec = next((v for v in vms.view({project}) if v.get("name") == name), None)
    if not rec:
        return {"where": "refused", "name": name, "why": f"{project} has no VM called {name}"}
    if rec.get("state") != "running":
        return {"where": "refused", "name": name, "why": f"{name} is {rec.get('state')}, and a console opens on a running VM"}
    nid = rec["node"]
    n = nodes.node(nid) if not NODES_OK else None
    if not n:
        return {"where": "refused", "name": name, "why": f"{name}'s node is not on record here"}
    nm = n.get("name") or nid
    se = (n.get("reported") or {}).get("session")
    if n.get("state") != "online" or n.get("live") is False:
        why = f"{nm}, where {name} runs, is not answering now"
    elif not isinstance(se, dict) or not se.get("ctr"):
        why = (f"{nm} cannot open a console: {se['ctr_why']}" if isinstance(se, dict) and se.get("ctr_why")
               else f"{nm} has not set up its container terminal yet; try again in a minute")
    else:
        return {"where": "node", "id": nid, "name": nm, "host": nodes.route_host(nid),
                "screen": int(se.get("screen") or SCREEN_PORT),
                "boot": str(se.get("boot") or ""), "domain": rec["domain"], "term": bool(se.get("term"))}
    return {"where": "refused", "name": nm, "why": why}


def _ctr_owner(name, instance):
    """The project a container's terminal is for: the one its instance
    belongs to (devapp.owner_of), "" for nobody's."""
    return devapp.owner_of(name, instance) or ""


def _arg_project(arg):
    """The project a terminal argument is about, or "" (the workspace
    shell, a named scratch session)."""
    m = _ARG_CTR.match(arg or "") or _ARG_LOGCTR.match(arg or "")
    if m:
        return _ctr_owner(m.group(1), m.group(2))
    m = _ARG_VM.match(arg or "")
    if m:
        return m.group(1)
    if agents.of_arg(arg)[0]:
        return agents.project_of_arg(arg)
    if arg.startswith("shell:"):
        return arg[len("shell:"):]
    if arg.startswith("sh:"):
        return arg.split(":", 2)[2] if arg.count(":") >= 2 else ""
    return ""


_hello_asked = {}


def _ask_hello(nid):
    """A fresh census from a node a session was just refused on, at most
    once a minute: the census rides hello every ten minutes, and the retry
    a person makes ten seconds later should reason about the node as it is."""
    now = time.time()
    if now - _hello_asked.get(nid, 0) >= 60:
        _hello_asked[nid] = now
        nodes.ask_hello(nid)


def session_target(project, claude=False, node="", uid=""):
    # `claude` is the question R47 added. A project's SHELL follows its node
    # (the tree is that machine's mount and its toolchains are what a build
    # there uses), and a project with NO node still gets a shell here, on the
    # same share. What it does not get is a Claude session: this container
    # carries no Claude Code, so the answer is a
    # refusal that says what to do rather than a conversation that cannot
    # build anything.
    """Where a session on this project runs (roadmap #24, phase 10b):

        {"where": "local"}                                   (this container)
        {"where": "node", "id", "name", "host", "screen", "boot", "term"}
        {"where": "refused", "name", "why"}                  (bound to a node
                                                              that cannot take one)

    A project bound to a node whose census says the session half is up and
    whose synced copy of the project is there gets its session THERE. One
    bound to a node that is offline, runs no sessions or has no copy yet is
    REFUSED rather than quietly started here: a session started on the
    wrong machine has the wrong toolchains and its transcripts land in the
    wrong home, and switching later splits a conversation across two boxes. The sentence says which
    of the three it was and what fixes it. A project with no node keeps its
    session here, as it always has.

    Two of the refusals are PASSING (the node is rebooting, or it just
    came up and its network mount has not landed), and the sentence for
    those says to wait, not to unbind the node: the operator who rebooted
    the sandbox and met "add the mount... unbind the node" had nothing to
    add and nothing to unbind. The census is asked for again on the
    strength of any refusal it decided, so the next look is current.

    A Claude session has no second place to run: this container carries no
    Claude Code, so a refusal is the whole answer and the sentence has to
    carry what to do about it. A SHELL still falls back here, which is what
    keeps the tree, the linters and git reachable while a node is away.
    """
    with timing.timed("session_target:prefs"):
        pf = prefs.get(project) if project else None
    nid = (pf or {}).get("node") or ""
    # The node the person picked, when it is one the project works on
    # (R82); any other name falls to the primary rather than to a refusal,
    # since the pick came off a list this side drew.
    if node and node in ((pf or {}).get("nodes") or []):
        nid = node
    # ONE SENTENCE, and not a red one on the page: a project with no node is
    # a normal state, not a fault. `name` is what tells the two apart
    # downstream (empty here, the node's name when a node refused), so the
    # row can say this plainly and keep red for the machine that is broken.
    no_node = {"where": "refused", "name": "",
               # The row says it whole, the fact and then what to do about
               # it (no tooltip carries a second half any more).
               "why": "no node to run a coding agent's session on: pick one in the project's settings, or enroll "
                      "one on the Nodes page under Machines"} if claude \
        else {"where": "local"}
    if not nid or NODES_OK:
        return no_node
    with timing.timed("session_target:node"):
        n = nodes.node(nid)
    if not n or n.get("kind") == "local":
        return no_node
    name = n.get("name") or nid
    rep = n.get("reported") or {}
    se = rep.get("session")
    passing = waiting = False
    if nodes.host_only(n):
        # Made hosting-only after the project named it: no session goes
        # there, whatever the settings still say.
        why = (f"{name} hosts containers only, so no session runs there: pick another node in "
               f"{project}'s settings")
    elif n.get("state") == "retired":
        # Un-enrolled (the operator, 5 Oct): the fact first, then what to do
        # about it, both on the row.
        why = (f"{name} was removed from the Nodes page. Pick another node in {project}'s settings, "
               "or enroll it again")
        passing = True          # its own sentence says the way on
    elif n.get("state") == "disabled":
        why = f"{name} is disabled on the Nodes page: Enable it there, or pick another node in {project}'s settings"
    elif n.get("state") != "online":
        why = f"{project}'s sessions run on {name}, which is {n.get('state') or 'not online'}"
    elif n.get("live") is False and _reconnecting(n):
        # The controller has just started and this node was here a moment
        # before: its agent dials in again on its own schedule (two minutes,
        # some days). Said quietly, as a wait, rather than in red as a node
        # that is down (the operator, 7 Oct).
        why = f"{name} is reconnecting after the controller restarted"
        passing = waiting = True
    elif n.get("live") is False:
        # The agent has stopped dialing in: a reboot, an update, a machine
        # that is off. Its tmux sessions are still there when it comes
        # back, and the button comes back with it; nothing to change.
        seen = int((n.get("agent") or {}).get("last_seen") or 0)
        ago = int(time.time() - seen) if seen else 0
        when = (f"{ago // 60} minutes ago" if ago >= 120 else f"{ago} seconds ago") if seen else "never"
        why = (f"{project}'s sessions run on {name}, whose agent is not answering, last heard "
               f"from {when}. If it is restarting, its sessions are back when it dials in")
        passing = True
    elif not isinstance(se, dict):
        why = (f"{project}'s sessions run on {name}, which has not reported a "
               "session half yet; give it a moment, or provision it with "
               "--session-user")
    elif not se.get("up"):
        why = (f"{project}'s sessions run on {name}, which runs none yet"
               + (f": {se['why']}" if se.get("why") else
                  "; provision it with --session-user"))
        _ask_hello(nid)
    elif (n.get("config") or {}).get("leaving") or ((n.get("config") or {}).get("workspace") or "sync") != "sync":
        # Off its synced copy, or on the way off it (R164): nothing to open a
        # session on, and its row on the Nodes tab is the way back.
        why = (f"{project}'s sessions run on {name}, which "
               + ("is leaving its synced copy: what is left there is going up to the controller"
                  if (n.get("config") or {}).get("leaving") else "holds no projects now")
               + ". Its row on the Nodes page moves it to a synced copy again,"
               " or bind the project to another node")
    elif not ((rep.get("sync") or {}).get(project) or {}).get("ready"):
        # A synced copy (R162) that is not there yet: a session started now
        # would open an empty or half-copied tree.
        got = (rep.get("sync") or {}).get(project) or {}
        why = (f"{project} is being copied to {name}"
               + (f" ({got['copying']} files to go)" if got.get("copying") else "")
               + (f": {got['error']}" if got.get("error") else "")
               + "; the session starts once the copy is there")
        passing = waiting = True
    elif uid and (wt := wssync.worktree_unit(project, uid)) \
            and not ((rep.get("sync") or {}).get(wt) or {}).get("ready"):
        # ...and this account's own worktree of it (B615): a session that
        # opened before it arrived made none of its own there and worked in
        # the owner's tree instead.
        why = (f"your worktree of {project} is being copied to {name}; "
               "the session starts once it is there")
        passing = waiting = True
    elif nodes.own_machine(n) and not (rep.get("isolation") or {}).get("sessions"):
        # The controller's own machine (R90): a session there runs inside
        # the wall around the controller or not at all, and bb-session's
        # check, which its census carries, says what keeps the wall down.
        why = (f"{name} is this controller's own machine, and the wall between its sessions and the controller "
               f"is not in force: {((rep.get('isolation') or {}).get('why') or 'not reported yet').rstrip('.')}")
    elif not se.get("boot"):
        # Without the node's boot the page would stamp this container's into
        # the tab, and bb-tty there would refuse every reconnect as a stale
        # tab (bug #56): a loop, not a session. Dead button, plain reason.
        why = (f"{project}'s sessions run on {name}, whose agent could not read that machine's "
               "boot, which a session's terminal there is checked against")
    else:
        return {"where": "node", "id": nid, "name": name, "host": nodes.route_host(nid),
                "screen": int(se.get("screen") or SCREEN_PORT),
                "boot": str(se.get("boot") or ""), "term": bool(se.get("term"))}
    return {"where": "refused", "name": name, "waiting": waiting,
            "why": why + ("." if passing else
                          ". Sessions run on a node and nowhere else (this container "
                          "carries no Claude Code), so the way on is that machine "
                          "coming back, or another node in the project's settings.")}

def ctr_target(name, instance):
    """Where a container's Shell runs (R218 step 4): on the machine its
    instance is on, since docker exec reaches a daemon from its own host.

        {"where": "local"}                         (this container's daemon)
        {"where": "node", "id", "name", "host", "screen", "boot", "term"}
        {"where": "refused", "name", "why"}

    A hosting-only node runs no terminal server, so a container there has no
    Shell, said with the reason (the operator, 14 Oct). Otherwise the node
    has to be up with its session half running, as for a Claude session,
    and the shell is its container terminal kind (ctr): as the docker
    account, which the session account is kept apart from (the operator,
    14 Oct).
    """
    nid = devapp.instance_node(name, instance) or ""
    n = nodes.node(nid) if nid and not NODES_OK else None
    if not n or n.get("kind") == "local":
        return {"where": "local"}
    nm = n.get("name") or nid
    se = (n.get("reported") or {}).get("session")
    if nodes.host_only(n):
        why = f"{nm} hosts containers only and runs no terminal, so a shell in this one opens on a node that runs sessions"
    elif n.get("state") != "online" or n.get("live") is False:
        why = f"{nm}, where this container runs, is not answering now"
    elif not isinstance(se, dict) or not se.get("up"):
        why = f"{nm} runs no terminal server yet" + (f": {se['why']}" if isinstance(se, dict) and se.get("why") else "")
    elif se.get("bundle") and nodes.bundle_digest() and se["bundle"] != nodes.bundle_digest():
        # Its terminals still run the scripts from before this controller's
        # update, which may not know what this one asks of them (B746):
        # asked to check in now, it takes the new ones in a minute or so.
        _ask_hello(nid)
        why = (f"{nm} has not taken this controller's update yet; its terminals move onto it at "
               "its next check-in, asked for now, so try again in a minute")
    elif not se.get("ctr"):
        # The container terminal runs as the docker account; the session
        # ones as an account kept off docker, and it is set up after them.
        why = (f"{nm} cannot open a container's shell: {se['ctr_why']}" if se.get("ctr_why")
               else f"{nm} has not set up its container terminal yet; try again in a minute")
    else:
        # An account without a shell was refused before this: a container
        # terminal has no read-only kind.
        return {"where": "node", "id": nid, "name": nm, "host": nodes.route_host(nid),
                "screen": int(se.get("screen") or SCREEN_PORT),
                "boot": str(se.get("boot") or ""), "term": bool(se.get("term"))}
    return {"where": "refused", "name": nm, "why": why}


# A session name without the account that owns it. Shell sessions are named
# `<uid>~shell-…` since roadmap #26 (two people opening a terminal on one
# project must not land in each other's), and every question of the form
# "does this project still have terminals open" is about the part after the
# `~`, whoever owns it.
_SESS_OWNER = re.compile(r"^u_[0-9a-f]{8}~")


def _chat_summary(who, ps):
    """{online, people, unread, rev} for the chat button, or {} for a
    principal that is not a person."""
    uid = users.uid_of(who)
    if not uid:
        return {}
    store = users.load()["users"]
    mine = (who or {}).get("name", "")
    others = [u.get("uid") for n, u in store.items()
              if u.get("uid") and n != mine]
    seen = users.prefs(who).get("chat_seen") or {}
    return {"online": [n for n in chat.online(_polls) if n != mine],
            "rev": chat.rev(),
            "unread": chat.unread(uid, others, [p["name"] for p in ps], seen),
            # Everybody, not only who is here: a message waiting for somebody
            # who is away is most of what a history is for.
            "people": sorted(n for n in store if n != mine),
            # ...and when each was last here, for the name's "(3h ago)": the
            # newer of this run's polls and the time kept on the record.
            "seen": {n: int(max(_polls.get(n, 0), u.get("seen") or 0)) for n, u in store.items() if n != mine}}


def account_names():
    """{uid: account name} for every account that has an id."""
    return {u.get("uid"): n for n, u in users.load()["users"].items() if u.get("uid")}


def _term_arg(rest):
    """The `arg` a terminal request carries, with any owner stamp a browser sent
    taken off. "" when there is none."""
    _, sep, query = rest.partition("?")
    if not sep:
        return ""
    for kv in query.split("&"):
        k, eq, v = kv.partition("=")
        if k == "arg" and eq:
            return _ARG_OWNER.sub("", urllib.parse.unquote_plus(v))
    return ""


def _runner_level(who, inst):
    """This account's level on one runner: write, read or ""."""
    if users.is_admin(who) or not users.may_instance(who, "runner", inst):
        return "write"
    return "read" if roles.level_of(who, "runner", instance=inst) else ""


def _runners_for(who):
    """The CI runners this account may read, each with `may`, read or write
    (R260: a role holds the CI runner area runner by runner)."""
    who = who or {}
    if not (users.is_admin(who) or roles.level_of(who, "runner")):
        return []
    lim = None if users.is_admin(who) else roles.nodes_for(who, "runner")
    out = []
    for r in runners.listing():
        inst = f"{r['id']}/{r['slot']}"
        if lim is None or inst in lim:
            out.append(dict(r, may=_runner_level(who, inst) or "read"))
    return out


def _session_visible(name, mine, seen, all_of_them):
    owner, base = tmux_owner(name), tmux_base(name)
    if owner:
        return owner == mine            # a shell belongs to exactly one account
    if all_of_them:
        return True
    # Unowned: a Claude session, or a terminal from before accounts. Judged by
    # the project in its name, which is what the account was or was not given.
    for pre in (*agents.prefixes(), "shell-"):
        if base.startswith(pre):
            stem = base[len(pre):]
            return any(tmux_name(p) == stem or stem.startswith(tmux_name(p) + "-")
                       for p in seen)
    return False


_homes = {}


def home_for(uid):
    """Where that account's home is, from lib/common.sh's user_home.

    Shelled out to rather than reimplemented, because bb-tty calls the same
    function to decide where a terminal runs: two implementations of "where
    does this person's Claude login live" would eventually disagree, and the
    way you would find out is somebody signing in and the session not seeing
    it. Empty on any failure, which every caller reads as "the box's own".
    """
    lib = HERE.parent / "lib" / "common.sh"
    if not uid or not lib.is_file():
        return ""
    # Remembered, because this is on the status poll and the answer cannot
    # move: an account's home is derived from an id that never changes. The
    # first call per account also CREATES the directory, which is the other
    # reason not to do it fifteen times a minute per browser.
    if uid in _homes:
        return _homes[uid]
    r = run(["bash", "-c", f'. {shlex.quote(str(lib))}; user_home "$1"',
             "_", str(uid)], timeout=10)
    got = (r.get("out") or "").strip() if r.get("code") == 0 else ""
    if got:
        _homes[uid] = got
    return got


def tmux_base(name):
    return _SESS_OWNER.sub("", str(name))


def tmux_owner(name):
    m = _SESS_OWNER.match(str(name))
    return m.group(0)[:-1] if m else ""


def tmux_sessions():
    r = run(["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}\t#{session_created}"],
            timeout=10)
    if r["code"] != 0:
        return []          # no server running yet is the normal empty case
    panes = session_cwds()
    rows = []
    for line in r["out"].splitlines():
        if "\t" in line:
            name, attached, created = (line.split("\t") + ["", ""])[:3]
            info = panes.get(name, {})
            # When it started, as a node's rows say, for the Sessions page's
            # Started column, which was blank for every one here (B149).
            row = {"name": name, "attached": attached.strip() not in ("", "0"),
                   "cwd": info.get("cwd", ""),
                   "created": int(created) if created.strip().isdigit() else 0}
            # By the unprefixed name, the way node rows are read, so another
            # account's session here says whether it is working too.
            if agents.is_session(tmux_base(name)):
                uid = tmux_owner(name) or (users.uid_of(users.get(users.owner_name() or "")) if users.owner_name() else "")
                state, task = session_state(uid, name, info.get("title", ""))
                row["claude"] = {"state": state, "task": task, "conv": AGENT_CONV.get((uid, tmux_base(name)), "")}
            rows.append(row)
    return rows


def my_agent_sessions(project, uid):
    """[(agent, slot, session row)] for every agent session of this account
    on this project, here and on the nodes (R143)."""
    owner = users.uid_of(users.get(users.owner_name() or "")) if users.owner_name() else ""
    stem = tmux_name(project)
    out = []
    for s in tmux_sessions() + node_tmux_sessions():
        real = s.get("node_name") or s["name"]
        base = tmux_base(real)
        a, st = agents.of_session(base)
        if a and st == stem and (tmux_owner(real) or owner) == uid:
            out.append((a.id, agents.slot_of(base), s))
    return out


_ARG_RESUME = re.compile(r":r:([A-Za-z0-9-]+)")


def slot_held(project, uid, arg):
    """A sentence when this account may not open the agent slot the argument
    names (R143), "" when it may: a slot past the project's cap (unless it
    runs already, a cap lowered since), or a conversation that is running
    in another of its sessions, which two would write over each other."""
    a = agents.of_arg(arg)[0]
    if not a:
        return ""
    slot = agents.slot_of_arg(arg)
    mine = my_agent_sessions(project, uid)
    here = [s for ag, n, s in mine if ag == a.id and n == slot]
    cap = prefs.get(project).get("agent_slots") or prefs.AGENT_SLOTS
    if slot > cap and not here:
        running = sorted(n for ag, n, _s in mine if ag == a.id)
        return (f"{project} lets each person run {cap} {a.name} session{'' if cap == 1 else 's'} at once "
                f"(its settings say how many), and {len(running)} of yours {'is' if len(running) == 1 else 'are'} "
                f"running: end one, or open it, to work here")
    m = _ARG_RESUME.search(arg)
    if m:
        for ag, n, s in mine:
            if (ag, n) != (a.id, slot) and (s.get("claude") or {}).get("conv") == m.group(1):
                said = agents.get(ag).name + (f" {n}" if n > 1 else "")
                return (f"That conversation is running in your {said} session"
                        f"{' on ' + s['node'] if s.get('node') else ''}: open that one, "
                        "or end it first to resume it here")
    return ""


def claude_working(project, uid, agent="claude", slot=1):
    """Whether that account's session of one agent on this project is
    mid-prompt, here or on a node (session_state: Claude's pane title,
    another agent's hooks), in its slot (R143). The owner's is the bare
    name, as everywhere else on the page."""
    want = agents.session_name(agent, project, slot)
    owner = users.uid_of(users.get(users.owner_name() or ""))
    return any(tmux_base(s["name"]) == want and (tmux_owner(s["name"]) or owner) == uid
               and (s.get("claude") or {}).get("state") == "working"
               for s in tmux_sessions() + node_tmux_sessions())


def sessions_anywhere():
    """Every Claude session's page name, here and on the nodes: what the
    notebook's Send to Claude has to choose from. Since sessions moved onto
    nodes (roadmap #24) the local half is the harness's and the node half
    is everybody's, and a list of only the first told every project it had
    no session while its own row showed one."""
    return [s["name"] for s in tmux_sessions()] + [s["name"] for s in node_tmux_sessions()]


def session_tokens_for(nid, sessions):
    """[{project, uid, token}] for the Claude sessions alive on one node.

    A session's token slides forward on every answer it gets, so one that is
    working never runs out. One that sits idle past twelve hours has nothing
    to slide it, and a dead token is deliberately never renewed: that refusal
    is what makes the life mean anything for a token that leaked. So the
    machine the session is running on is told a fresh one on its heartbeat,
    and a token then lives exactly as long as its tmux session does (R27).

    Matched from the PROJECT towards the session name, never the other way:
    tmux rewrites `.` and `:` in a name, so `ep.silon` runs as
    `claude-ep_silon` and the project cannot be read back out of it.
    """
    want = {}
    for name in project_names(users.ALL):
        for n in agent_sessions(name):
            want[n] = name
    out = []
    seen = set()
    for row in sessions if isinstance(sessions, list) else []:
        real = str((row or {}).get("name") or "")
        uid, base = tmux_owner(real), tmux_base(real)
        project = want.get(base)
        if not uid or not project or (uid, project) in seen:
            continue
        seen.add((uid, project))
        out.append({"project": project, "uid": uid,
                    "token": users.mint_session(project, uid=uid)})
        # ...and one for each other repository its project's session works
        # in (R136), kept by the agent under that repository as this is.
        key = repos.project_of(project)
        for m in (repos.members(key) if key else []):
            if m != project and (uid, m) not in seen:
                seen.add((uid, m))
                out.append({"project": m, "uid": uid, "token": users.mint_session(m, uid=uid)})
    return out[:64]


def node_tmux_sessions():
    """The sessions running on nodes (roadmap #24), shaped like this
    container's own so the Sessions card, the project rows and claude_with
    read them the same way, plus `node`, the name of the machine.

    NAMED BY THIS CONTAINER'S RULE. On a node every account is prefixed,
    the owner included; here the owner's sessions are the bare names, and
    everything on the page (the row's "is my session live", the labels,
    the kill dialog) is written against that. So the owner's node sessions
    are shown bare, and `node_name` keeps what the node calls it, which is
    what a kill has to send back. Nothing on a node is unowned, so an
    unprefixed name there is not a session of anybody's and is dropped.
    """
    if NODES_OK:
        return []
    owner = users.uid_of(users.get(users.owner_name() or "")) if users.owner_name() else ""
    rows = []
    for nid, (nname, sess) in nodes.node_sessions().items():
        for s in sess:
            real = s.get("name") or ""
            who = tmux_owner(real)
            if not who:
                continue
            name = tmux_base(real) if who == owner else real
            row = {"name": name, "node_name": real, "node": nname, "node_id": nid,
                   "attached": bool(s.get("attached")), "cwd": s.get("cwd", ""),
                   "created": int(s.get("created") or 0)}
            agent, stem = agents.of_session(tmux_base(real))
            if agent:
                state, task = session_state(who, real, s.get("title", ""))
                # What it was last asked over the title, which Claude names
                # from the first turn and keeps (B59).
                task = projsessions.latest_task(who, stem, row["created"], agent.id,
                                                agents.slot_of(tmux_base(real))) or task
                row["claude"] = {"state": state, "task": task, "conv": AGENT_CONV.get((who, tmux_base(real)), "")}
            rows.append(row)
    return rows


def _image_since():
    """When this controller's image was first seen running here, from the
    ledger the entrypoint keeps (image-log.tsv), or this process's start:
    a session begun before it was briefed by the build before."""
    rev = image_stamp().get("rev") or ""
    try:
        for line in reversed((STATE / "image-log.tsv").read_text().splitlines()):
            f = line.split("\t")
            if len(f) >= 2 and rev and f[1] == rev:
                return int(datetime.datetime.fromisoformat(f[0]).timestamp())
    except (OSError, ValueError):
        pass
    return int(_STARTED)


_STARTED = time.time()
# Read once: the image changes only with a restart of this process.
_IMAGE_SINCE = {}


def session_behind(s):
    """What changed since this session started that it does not see until
    it is started again (the operator, 12 Oct): a toolchain installed on its
    node that puts something on its PATH, and BuilderBot updated, whose
    briefing a session reads once, at its start."""
    started = int(s.get("created") or 0)
    if not started:
        return []
    why = []
    tools = toolchains.landed_since(s.get("node_id") or "", started) if s.get("node_id") else []
    if tools:
        why.append(f"{', '.join(tools[:3])}{' and more' if len(tools) > 3 else ''} installed on "
                   f"{s.get('node') or 'its node'} since it started")
    if _IMAGE_SINCE.setdefault("at", _image_since()) > started:
        why.append("BuilderBot updated since it started: its briefing is the older build's")
    # A repository made in its project since (Add repository): a session
    # works in the ones its project held when it started (bb-tty's works).
    added = _repos_since(s, started)
    if added:
        why.append(f"{', '.join(added[:3])}{' and more' if len(added) > 3 else ''} added to its project since it started")
    return why


def session_behind_of(project, uid, agent, slot):
    """session_behind for the session a hook speaks for: its project, its
    account, its agent and its slot."""
    want = tmux_name(project)
    for s in projsessions.SESSIONS():
        base = tmux_base(s.get("name") or "")
        ag, stem = agents.of_session(base)
        if ag and ag.id == agent and stem == want and agents.slot_of(base) == slot \
                and projsessions.OWNER(s.get("name") or "") == uid:
            return session_behind(s)
    return []


def _repos_since(s, started):
    """The repositories of a session's project made after it started, by
    their shown names (repos.made_since), its own found by its tmux name."""
    _agent, stem = agents.of_session(tmux_base(s.get("name") or ""))
    here = next((m for ms in repos.all_members().values() for m in ms if tmux_name(m) == stem), "") if stem else ""
    return repos.made_since(here, started) if here else []


def project_busy(name, verb):
    """Why a project cannot be trashed right now, or "": its own
    terminals open, since a live session holds the directory as its working
    directory and would carry on writing wherever it went, or its dev
    instance's containers up, bound to paths that would stop existing.
    Refusals rather than things to tidy away: ending either on the
    operator's behalf is a bigger decision than the one being asked for.
    Here rather than in projects.py because these are the two that see
    outside the filesystem: tmux, and the daemon."""
    # ...here and on every node, where sessions run now (B242): the lock
    # reads both the same way.
    live = {s["name"] for s in tmux_sessions()} | {s["name"] for s in node_tmux_sessions()}
    held = sorted(s for s in live
                  if tmux_base(s) in agent_sessions(name)
                  or tmux_base(s).startswith(tmux_name(f"shell-{name}") + "-"))
    if held:
        return ("close its terminals first: " + ", ".join(held[:3])
                + (" …" if len(held) > 3 else ""))
    # No daemon, or no compose file: nothing to protect. Broad because
    # the check reads the daemon, the store and the compose file, and
    # none of those failing is a reason to keep the project; logged, so
    # a trash that went past a fault says so.
    try:
        holds = devactions.state(name).get("exists")
    except Exception as e:                          # noqa: BLE001
        print(f"[dashboard] {verb} {name}: instance check skipped: "
              f"{type(e).__name__}: {e}", flush=True)
        holds = False
    if holds:
        return "its dev instance still has containers; press Down on the Artifacts view first"
    return ""


MAINT_BAND = ('<div class="banner maint" id="maintband" role="status" hidden>Maintenance mode is on: '
              'only you can use BuilderBot. It is switched off under '
              '<a href="#/controller/settings" data-maintgo>Controller settings, Maintenance</a>.</div>')
MAINTENANCE_SAID = "BuilderBot is down for maintenance: only its owner can sign in until it is over."
# A held start's band (R56 step 9): sent hidden on every page of a bare-metal
# install and shown by the poll while the start is held.
HELD_BAND = ('<div class="banner held" id="heldband" role="status" hidden>The start is held: nothing runs until '
             '<a href="#/controller/machine" data-heldgo>Start on This machine</a>. <span data-heldwhy></span></div>')


def kept_out(u):
    """True when maintenance mode is on and `u` is not the owner: a session's
    token counts as the account it was minted for, so the owner's own
    sessions go on working."""
    return bool(u) and bool(settings.get("maintenance_mode")) \
        and (users.account_of(u) or {}).get("role") != "owner"


def owner_session_open(project):
    """Whether the owner's Claude session is open in the project directory,
    here or on a node: every other account's wears its prefix (tmux_owner).
    What a branch switch waits for (git.in_use)."""
    mine = claude_session(project)
    return any(tmux_base(s["name"]) == mine and not tmux_owner(s["name"])
               for s in tmux_sessions() + node_tmux_sessions())


def node_heart(n):
    """(tmux names working, when that was seen) from a node's last heartbeat:
    a Claude pane whose title carries the spinner. A node that has stopped
    answering shows nothing working, since what it said last is not true any
    more."""
    rep = n.get("reported") or {}
    heart = set()
    if n.get("live"):
        for r in rep.get("sessions") or []:
            name = str((r or {}).get("name") or "")
            ag, _stem = agents.of_session(tmux_base(name))
            if not ag:
                continue
            # Claude's by its pane title; another agent's by what its hooks
            # said (R95 step 7): every agent's working session counts.
            if ag.id == "claude":
                busy = claude_state(str((r or {}).get("title") or ""))[0] == "working"
            else:
                busy = (AGENT_STATE.get((tmux_owner(name), tmux_base(name))) or {}).get("state") == "working"
            if busy:
                heart.add(name)
    return heart, float((rep.get("sample") or {}).get("at") or 0)


def turn_scope(project, uid, agent="claude", slot=1):
    """(node id, key, limit, heart, at) for a turn of `uid`'s session on
    `project` (turns.py), or None when there is no node to count on: the
    project runs on no agent node, so nothing here is the machine a session
    works on. The key is the session's tmux name on the node, which is what
    the heartbeat reports it as."""
    if NODES_OK:
        return None
    nid = prefs.get(project)["node"]
    n = nodes.node(nid) if nid else None
    if not n or n["kind"] != "agent":
        return None
    heart, at = node_heart(n)
    return nid, f"{uid}~{agents.session_name(agent, project, slot)}", nodes.turn_limit(nid), heart, at


def node_turns(n):
    """What a node's row says about its sessions' turns: how many are working
    and waiting now, and the limit."""
    st = turns.state(n["id"], *node_heart(n))
    return {"working": len(st["working"]), "waiting": st["waiting"],
            "limit": nodes.turn_limit(n["id"])}


def newest_transcript(project_dir, uid=""):
    """The most recent Claude transcript on a working directory, as its file,
    or None: the asking ACCOUNT's own (its ~/.claude/projects on the share,
    transcripts.dirs), and the container account's where nobody is asking.
    It read the container account's for everybody until B489: a new user's
    Claude button offered the owner's conversation from five days before,
    which bb-tty then could not find under that user's home."""
    if uid:
        dirs = transcripts.dirs(uid, Path(str(project_dir)).name)
    else:
        dirs = [CLAUDE_PROJECTS / str(project_dir).replace("/", "-")]
    files = []
    for d in dirs:
        try:
            files += [(f.stat().st_mtime, f) for f in d.glob("*.jsonl") if f.is_file()]
        except OSError:
            continue
    # The newest with a turn in it: one with nothing said was offered as
    # Resume and refused by bb-tty (B276).
    return next((f for _, f in sorted(files, key=lambda x: x[0], reverse=True) if transcripts.has_turn(f)), None)


def last_claude(project_dir, uid=""):
    """The most recent Claude transcript for a working directory, or None.

    Used to offer "resume" rather than silently starting a fresh conversation
    in a project that already had one: a session's tmux dies with the machine
    it ran on, but the transcript does not: every account's ~/.claude/projects
    is a link onto the projects share (lib/common.sh's claude_projects_link),
    so this reads what a session on a node wrote.
    """
    newest = newest_transcript(project_dir, uid)
    if newest is None:
        return None
    return {"id": newest.stem, "when": int(newest.stat().st_mtime)}


def last_agents(project_dir, uid=""):
    """{agent id: {id, when}}: the newest conversation of each coding agent
    beside Claude on this project, the account's own, from the <agent>/
    folder its Stop hook copies a session's log into (transcripts.py)."""
    if not uid:
        return {}
    out = {}
    for d in transcripts.dirs(uid, Path(str(project_dir)).name):
        for a in transcripts.OTHER_AGENTS:
            try:
                files = [f for f in (d / a).glob("*.jsonl") if f.is_file()]
            except OSError:
                continue
            for f in files:
                when = int(f.stat().st_mtime)
                if when > (out.get(a) or {}).get("when", 0):
                    out[a] = {"id": f.stem, "when": when}
    return out


MODEL_FAMILY = re.compile(r'"model"\s*:\s*"claude-(opus|sonnet|haiku|fable)')


def claude_model_now(project_dir, uid=""):
    """The model family the newest transcript here last answered on, or "".

    Read from the tail of the file when a project's settings dialog opens,
    so with no model set the dialog can say what Claude's default actually
    is rather than "leave as is". The tail, because a transcript runs to
    megabytes and the answer is in its last line.
    """
    f = newest_transcript(project_dir, uid)
    if f is None:
        return ""
    try:
        with open(f, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - 131072))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return ""
    found = MODEL_FAMILY.findall(tail)
    return found[-1] if found else ""


def end_agents(project):
    """End this project's coding-agent sessions, every agent's (R95 step 16:
    Claude's alone was ended, and a ChatGPT or Copilot session kept what it
    started with), so the next Start agent starts one on the setting just
    saved. {ended, on_node?} if any was, else {ended: False, why}."""
    out = {"ended": False, "why": "no session is running here"}
    # Every slot's name is asked of the lists once, not each of the lists
    # once a name (R143: nine slots of each agent).
    live = {s["name"] for s in tmux_sessions()} | {x["name"] for x in node_tmux_sessions()}
    for session in agent_sessions(project):
        if session not in live:
            continue
        r = _end_agent(session)
        if r.get("ended"):
            out = r
        elif not out.get("ended") and r.get("why") != "no session is running here":
            out = r
    return out


def _end_agent(session):
    """End one agent's session on a project, so the next press starts one
    on the setting just saved.

    It used to RESPAWN the pane in place, with `tmux respawn-pane -k` running
    the launcher again with `--respawn`, which kept the session, and the browser
    tab attached to it, and meant the change landed somewhere nobody was
    looking. The operator's call (12 Sep): end it, and let the button start it
    again. Simpler to say and simpler to trust, and it asks nothing of a
    node's agent that killing a session from the Sessions card has not asked
    for months, so the version gate that came with the respawn op is gone
    with it.

    A session ended is not a conversation lost: the transcript is the
    account's own and Start agent resumes it. What it costs is the turn in
    flight, which is what the dialog asking about it says.
    """
    if session not in {s["name"] for s in tmux_sessions()}:
        # On a node, through its agent, under the name that machine knows it
        # by, which is the same path the Sessions card's kill takes.
        on_node = next((x for x in node_tmux_sessions()
                        if x["name"] == session), None)
        if not on_node:
            return {"ended": False, "why": "no session is running here"}
        r = nodes.session_kill(on_node["node_id"], on_node["node_name"])
        if r.get("error"):
            return {"ended": False, "why": r["error"]}
        return {"ended": True, "on_node": on_node["node"]}
    r = run(["tmux", "kill-session", "-t", "=" + session], timeout=10)
    if r["code"] != 0:
        return {"ended": False, "why": (r["out"] or "tmux refused").strip()[:200]}
    return {"ended": True}


def end_session(session, node=""):
    """End one session by its page name, wherever it runs: on a node through
    its agent's held poll, by node id when the caller knows it (one name can
    live here and there), else with this container's tmux. A name that is
    not a live session is already ended and answers {gone} rather than an
    error, because the caller that wants a clean slate (Sign in ending the
    sign-in terminal first) asks for exactly that ordinary case. The
    Sessions card's kill (_session) and an administrator's End in a
    project's settings (projsessions.py) are this one path."""
    here = {s["name"] for s in tmux_sessions()}
    on_node = next((s for s in node_tmux_sessions() if s["name"] == session
                    and (not node or s["node_id"] == node)), None)
    if on_node and (node or session not in here):
        return nodes.session_kill(on_node["node_id"], on_node["node_name"])
    if session not in here:
        return {"code": 0, "out": "", "err": "", "gone": True}
    return run(["tmux", "kill-session", "-t", session], timeout=10)


def others_sessions():
    """Every session and terminal open that is not the owner's, here and on
    the nodes, as maintenance mode's question lists them (the operator, 27
    Oct): whose, which project, which agent or a shell, what it is doing,
    and where. What turning maintenance on ends."""
    owner = users.get(users.owner_name() or "") or {}
    mine = owner.get("uid") or ""
    names = account_names()
    out = []
    for s in tmux_sessions() + node_tmux_sessions():
        uid = tmux_owner(s["name"])
        if not uid or uid == mine:
            continue
        base = tmux_base(s["name"])
        ag, stem = agents.of_session(base)
        if not ag:
            # A terminal's project is in its name: shell-PROJECT-N.
            m = re.match(r"shell-(.+)-\d+$", base)
            stem = m.group(1) if m and registry.is_project(m.group(1)) else ""
        st = (s.get("claude") or {}).get("state") or ""
        out.append({"name": s["name"], "node_id": s.get("node_id") or "", "who": names.get(uid) or uid,
                    "project": registry.label(stem) if stem else "",
                    "what": ag.name if ag else "a terminal",
                    "state": st if ag else "open", "node": s.get("node") or "this controller"})
    return out


def end_others_sessions(rows):
    """Maintenance on: each of those ended, in the background, since a node
    answers through its held poll."""
    def go():
        for r in rows:
            try:
                end_session(r["name"], r["node_id"])
            except Exception as e:                                  # noqa: BLE001
                print(f"dashboard: maintenance could not end {r['name']}: {e}", flush=True)
    threading.Thread(target=go, daemon=True).start()


def uptime():
    # PID 1 started when the container did, so its elapsed time is the
    # container's; /proc/uptime alone is the host's under a shared kernel.
    # Read from /proc in ps's own etime shape ([[dd-]hh:]mm:ss) rather than
    # forking ps on every status poll (R94); ps where /proc does not say.
    try:
        start = int(open("/proc/1/stat").read().rsplit(")", 1)[1].split()[19])
        up = float(open("/proc/uptime").read().split()[0])
        secs = max(0, int(up - start / os.sysconf("SC_CLK_TCK")))
        d, rest = divmod(secs, 86400)
        h, rest = divmod(rest, 3600)
        m, sec = divmod(rest, 60)
        return (f"{d}-{h:02d}:{m:02d}:{sec:02d}" if d else f"{h:02d}:{m:02d}:{sec:02d}" if h
                else f"{m:02d}:{sec:02d}")
    except (OSError, ValueError, IndexError):
        r = run(["ps", "-o", "etime=", "-p", "1"], timeout=10)
        return r["out"].strip() or "?"


# The API surface the companion app is written against (apps/android/). One
# number, moved with the app: apps/android/api-surface.json names every path
# and field the app reads and carries the same number, test/appapi.mjs
# holds the running server to that file, and the app compares this against
# its own TARGET_API to say when it is behind. A change to a path or a
# field listed there bumps all three together: the app, the file, this; a
# field is removed only in the release after a released app stopped
# reading it, with a changelog line (R79 step 8).
APP_API = 9
# How long the app's live connection is held before an empty answer (R125):
# under the app's 60 s read timeout, and long enough to cost little.
PHONE_WAIT_S = 45


# BuilderBot's own repository, as a project's origin names it over https or ssh.
SELF_REPO = re.compile(r"github\.com[:/]aquilaelabs/builderbot(?:\.git)?/?$", re.I)


def self_dist():
    """dist/ of the project whose origin is BuilderBot's own repository, or
    None. Found by the remote and not by the folder (B4), since a project
    renamed on the dashboard keeps its folder. Each project's .git/config is
    read rather than git asked, since the app asks /api/meta on every start."""
    try:
        dirs = sorted(p for p in WORKSPACE.iterdir() if p.is_dir())
    except OSError:
        return None
    for p in dirs:
        try:
            conf = (p / ".git" / "config").read_text(errors="replace")
        except OSError:
            continue
        m = re.search(r'^\[remote "origin"\][^\[]*?^\s*url\s*=\s*(\S+)', conf, re.M)
        if m and SELF_REPO.search(m.group(1)):
            return p / "dist"
    return None


def app_apk():
    """The newest companion APK in BuilderBot's own dist/, if this
    controller has the repository as a project: what the app points at when
    it finds itself behind. Its filename only; the Artifacts view serves it."""
    d = self_dist()
    if d is None:
        return ""
    try:
        apks = sorted((p for p in d.iterdir() if p.suffix == ".apk" and p.is_file()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return ""
    # A signed build first: the app on a phone was installed signed, and
    # Android will not update it with anything signed otherwise. The newest
    # file was offered whatever it was, and on 5 Oct that was a debug build
    # of uncommitted changes, which the operator's phone refused (B507).
    # Without a signed one, a build of a commit; a dirty one never.
    pick = ([p for p in apks if "-signed" in p.name]
            or [p for p in apks if "-dirty" not in p.name and "dirty" not in p.stem.split("-")[-1]])
    return pick[0].name if pick else ""


def app_apk_sha():
    """The newest companion APK's sha256, for the app to check a download
    against before it installs (B273); "" when there is none."""
    name = app_apk()
    d = self_dist()
    if not name or d is None:
        return ""
    try:
        h = hashlib.sha256()
        with open(d / name, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


# The page's own scripts, each named with its version as the page is served.
# `no-cache` makes a browser ask before it uses a copy, but a phone left on
# the page across an update still met the old Global rules dialog after it
# reloaded, and a URL that changes with the file cannot be answered from a
# copy of the file before it. The version is the script's size and mtime,
# the same thing its ETag is; the page's own tag covers them all, so a change
# to one script alone is still a new page.
_SCRIPT_TAG = re.compile(rb'<script src="((?:tab|nb|page)-[a-z-]+\.js)">')
_page_scripts = {"mtime": None, "names": frozenset()}


def page_scripts():
    """The companion scripts index.html loads, by name: the allow-list the
    server serves them from, read off the page's own script tags so a new
    file is added in one place, the page, and nothing else is served. Read
    again when index.html changes. The page-*.js files were missing from the
    versioning pattern above until this read it the same way (R77)."""
    p = HERE / "index.html"
    try:
        m = p.stat().st_mtime_ns
    except OSError:
        return frozenset()
    if _page_scripts["mtime"] != m:
        names = {n.decode() for n in _SCRIPT_TAG.findall(p.read_bytes())}
        _page_scripts.update(mtime=m, names=frozenset(names))
    return _page_scripts["names"]


_sri = {}


def _integrity_of(name, version):
    """csp.integrity of a page script, kept by its version."""
    key = (name, version)
    if key not in _sri:
        try:
            _sri[key] = csp.integrity((HERE / name).read_bytes())
        except OSError:
            return ""
        if len(_sri) > 512:
            _sri.clear()
            _sri[key] = csp.integrity((HERE / name).read_bytes())
    return _sri[key]


def _versioned_page(raw, tag):
    parts = [tag]

    def named(m):
        try:
            st = (HERE / m.group(1).decode()).stat()
        except OSError:
            return m.group(0)
        v = f"{st.st_size:x}-{st.st_mtime_ns:x}"
        parts.append(v)
        # Subresource Integrity (R158 step 4): the file's own digest, so a
        # script that arrives changed is not run.
        return (b'<script src="' + m.group(1) + b"?v=" + v.encode() + b'" integrity="'
                + _integrity_of(m.group(1).decode(), v).encode() + b'">')
    out = _SCRIPT_TAG.sub(named, raw)
    # The install's banner (R88), at its place under the header; part of the
    # page's tag, so a banner changed at a restart is not served from a copy.
    # ...and maintenance mode's, shown to the owner by the page while it is on,
    # and sent showing while it is on, so it is there at the first paint and
    # not only once the first status read lands (the operator, 26 Oct): with
    # it on, the owner is the one account the page is for.
    band = featuresoff.banner_html() + (MAINT_BAND.replace(' hidden>', '>', 1)
                                        if settings.get("maintenance_mode") else MAINT_BAND) \
        + (HELD_BAND.replace(' hidden>', '>', 1) if held.is_held() else HELD_BAND)
    out = out.replace(b"<!--BANNER-->", band.encode())
    parts.append(hashlib.sha256(band.encode()).hexdigest()[:8])
    # Every script runs as written, in order: Cloudflare's Rocket Loader
    # defers the ones that do not say so, and the page then met its own
    # names before they were defined (a ReferenceError, B138).
    out = out.replace(b"<script", b'<script data-cfasync="false"')
    return out, 'W/"' + hashlib.sha256("|".join(parts).encode()).hexdigest()[:24] + '"'


# ---- the request trace (R75 step 4) -----------------------------------------
# Every request this server answered, lately: when, the method, the path with
# its query keys, and who (a person, a session, an agent, the companion app)
# by the user agent and the principal the handler proved. A ring, in memory,
# because the question it answers is "what is the page asking for right
# now": the adb probe that put a row a minute on the Jobs tab and the tab
# that asked for its listing three times were both visible in one such
# window and invisible everywhere else. /api/trace reads it; `bb dashboard
# trace` prints it. Nothing here is persisted.
_TRACE = collections.deque(maxlen=6000)
_trace_lock = threading.Lock()


# The process's CPU clock beside the wall clock, a sample a request: over a
# window, how much of one core the server spent, which tells a server short
# of CPU (every request slow, each mostly waiting) from one slow request.
_CPU = collections.deque(maxlen=6000)


def trace_note(handler, ms=0, cpu=0, parts=None):
    # A note beside the request, never a fault in it: whatever goes wrong
    # here is swallowed, since the answer has already been sent. Broad
    # because it runs on every request and must never become one's 500;
    # the first fault is logged, the rest would only say it again.
    try:
        path, _, query = handler.path.partition("?")
        keys = "&".join(sorted(k for k in urllib.parse.parse_qs(query, keep_blank_values=True)))
        # ...and what a handler chose to add (the devapp action, B717): a
        # POST keyed by its path alone could not say which verb was slow.
        extra = getattr(handler, "trace_extra", "")
        if extra:
            keys = f"{keys}&{extra}" if keys else extra
        ua = (handler.headers.get("User-Agent") or "")[:40]
        who = getattr(_writing, "who", None) or {}
        by = ("session" if who.get("session") else "agent" if path.startswith("/api/v1/agent")
              else "user" if who.get("name") else "anon")
        with _trace_lock:
            _TRACE.append((time.time(), handler.command, path, keys, by, ua, int(ms), int(cpu), parts or {}))
            _CPU.append((time.time(), time.process_time()))
    except Exception as e:                                  # noqa: BLE001
        if not _trace_said:
            _trace_said.append(True)
            print(f"[dashboard] trace: {type(e).__name__}: {e} (said once)", flush=True)


_trace_said = []


def trace_since(since):
    now = time.time()
    with _trace_lock:
        rows = [r for r in _TRACE if r[0] >= since]
    groups = {}
    slow = []
    sections = {}
    for t, method, path, keys, by, ua, ms, cpu, parts in rows:
        agent = ("app" if "BuilderBot" in ua else "curl" if ua.startswith("curl")
                 else "browser" if "Mozilla" in ua else (ua.split("/")[0] or "?"))
        key = (method, path + ("?" + keys if keys else ""), by, agent)
        g = groups.setdefault(key, {"n": 0, "first": t, "last": t, "ms_max": 0, "ms_sum": 0, "cpu_sum": 0})
        g["cpu_sum"] += cpu
        # Where it went (timing.py): each named part's total across the window.
        for name, pm in parts.items():
            sc = sections.setdefault(name, {"n": 0, "sum": 0, "max": 0})
            sc["n"] += 1
            sc["sum"] += pm
            sc["max"] = max(sc["max"], pm)
        g["n"] += 1
        g["first"] = min(g["first"], t)
        g["last"] = max(g["last"], t)
        # How long each took (B245): a tab that loads slowly is one request
        # that took seconds, and a count alone cannot say which.
        g["ms_max"] = max(g["ms_max"], ms)
        g["ms_sum"] += ms
        slow.append((ms, t, method, key[1], by, agent, cpu, parts))
    out = [{"method": k[0], "path": k[1], "by": k[2], "agent": k[3], "n": v["n"],
            "first": v["first"], "last": v["last"], "ms_max": v["ms_max"],
            "ms_avg": v["ms_sum"] // max(1, v["n"]), "cpu_avg": v["cpu_sum"] // max(1, v["n"])}
           for k, v in groups.items()]
    out.sort(key=lambda r: -r["n"])
    # A long poll is slow by design (it waits to be told): not a slow answer.
    slow = [r for r in slow if not r[3].startswith(("/api/phone/wait", "/api/v1/agent/work"))]
    slow.sort(key=lambda r: -r[0])
    with _trace_lock:
        cpus = [c for c in _CPU if c[0] >= since]
    busy = (round((cpus[-1][1] - cpus[0][1]) / (cpus[-1][0] - cpus[0][0]), 2)
            if len(cpus) > 1 and cpus[-1][0] > cpus[0][0] else None)
    return {"since": since, "now": now, "total": len(rows), "rows": out,
            # How much of one core the server spent over the window, and its
            # threads now: near 1.0 is a server short of CPU (Python runs one
            # thread at a time), whatever page is asked for.
            "busy": busy, "threads": threading.active_count(),
            "sections": sorted(({"name": k, "n": v["n"], "avg": v["sum"] // max(1, v["n"]), "max": v["max"],
                                 "sum": v["sum"]} for k, v in sections.items()), key=lambda r: -r["sum"])[:30],
            "slow": [{"ms": r[0], "at": r[1], "method": r[2], "path": r[3], "by": r[4], "agent": r[5],
                      "cpu": r[6], "parts": dict(sorted(r[7].items(), key=lambda x: -x[1])[:4])}
                     for r in slow[:8] if r[0] >= 500]}


# ---- a session told the controller moved (R83) -----------------------------
# A session keeps the briefing it was handed at its start, and nothing
# re-briefs it when the controller is rebuilt within a compatibility window.
# So the build a session began on is kept, per session, and on its next
# prompt after a rebuild the hook's line says the controller moved and where
# to read what changed: once per build, since the file then carries the new
# one. Persisted, because the rebuild that this is about restarts this
# process. Node sessions only: the hook posts from a node, and a session
# runs on one.
SESSION_SEEN = "session-seen.json"
# What the operator can change on a project that a session should be told of
# on its next prompt (the operator, 25 Sep), with the verb that reads it. The
# roadmap is roadmap.catchup's, which says which item moved; these say the
# half. A session's own writes through the API are marked seen as they land
# (session_mark_own), so only somebody else's move is said.
SEEN_HALVES = (("bug", "bugs", "`bb bug`"), ("rules", "rules", "`bb rules`"),
               ("mem", "memories", "the notebook's Memory view"),
               ("prefs", "settings", "`bb settings`"),
               # ...and the design, which the house rules' fingerprint does
               # not cover (B218): a session styling a page went on with the
               # old one, and docs/design-language.md was never written again.
               ("design", "design", "`bb design show`, and write docs/design-language.md again with "
                                    "`bb design file` before committing it"))
OWN_WRITE_ROUTES = ("/api/roadmap", "/api/rules", "/api/bugs", "/api/memory", "/api/prefs", "/api/design")
_seen_lock = threading.Lock()


def _build_now():
    st = image_stamp()
    return st.get("version") or st.get("rev") or ""


def _seen_load():
    path = STATE / SESSION_SEEN
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def _seen_now(project, who):
    """The tokens a session is compared against: the poll's per-project
    revisions, a digest of the project's own settings (the poll's prefs
    token is one mtime for every project), and the count of memory edits
    made through the notebook by somebody who is not a session. Not the
    memory files' mtimes, which the poll's token is: a session's own memory
    tool writes those files without passing through here, and read as
    news to the session that wrote them (B269)."""
    r = revisions(who, [project])
    try:
        pf = json.dumps(prefs.get(project) or {}, sort_keys=True)
    except Exception:                                                     # noqa: BLE001
        pf = ""
    edits = _seen_load().get("_mem_edits")
    edits = edits if isinstance(edits, dict) else {}
    try:
        dz = json.dumps(design.saved(project) or {}, sort_keys=True)
    except Exception:                                                     # noqa: BLE001
        dz = ""
    return {"bug": str(r.get(f"bug:{project}") or ""), "rules": str(r.get(f"rules:{project}") or ""),
            "mem": str(edits.get(project) or 0),
            "prefs": hashlib.sha256(pf.encode()).hexdigest()[:12] if pf else "",
            "design": hashlib.sha256(dz.encode()).hexdigest()[:12] if dz not in ("", "{}") else ""}


def _memory_written(req, held):
    """Whether a POST to /api/memory wrote a memory: one of memory.verb's
    writes, answered without an error. A history read writes nothing, and
    counting it told a project's sessions its memories had changed when a
    person had only read the log (B296); a refusal or a conflict writes
    nothing either. `held` is the reply _post is holding."""
    if field(req, "action") not in memory.WRITES or not held:
        return False
    obj, code, _cookie = held[-1]
    return code == 200 and isinstance(obj, dict) and not obj.get("error")


def _mem_edited(project):
    """One more memory edit on this project through the notebook, by
    somebody who is not a session: the seen note's memory half."""
    if not project:
        return
    try:
        with _seen_lock:
            d = _seen_load()
            edits = d.get("_mem_edits") if isinstance(d.get("_mem_edits"), dict) else {}
            edits[project] = int(edits.get(project) or 0) + 1
            d["_mem_edits"] = edits
            write_json(STATE / SESSION_SEEN, d)
    except Exception as e:                                                # noqa: BLE001
        print(f"[dashboard] session seen: {type(e).__name__}: {e}", flush=True)


def session_mark_own(project, uid, who, since=None):
    """A session's own write to the notebook or the settings is seen by it
    as it lands, so its next prompt does not read it back as news. With
    `since`, the tokens as they stood before the write, only the halves
    that moved across it are marked: a bb verb relayed from a node may be
    a read, and a read must not mark what somebody else changed as seen."""
    if not project or not uid:
        return
    try:
        now = _seen_now(project, who)
        if since is not None:
            now = {k: v for k, v in now.items() if since.get(k) != v}
            if not now:
                return
        with _seen_lock:
            d = _seen_load()
            for key, rec in d.items():
                if key.startswith(f"{project}|{uid}|") and isinstance(rec, dict):
                    rec["revs"] = {**(rec.get("revs") or {}), **now}
            write_json(STATE / SESSION_SEEN, d)
    except Exception as e:                                                # noqa: BLE001
        print(f"[dashboard] session seen: {type(e).__name__}: {e}", flush=True)


# The house rule that asks a project's sessions to watch the diagnostics
# reports (the operator, 6 Oct: check for new ones after every prompt). A
# rule is text read at a session's start; this is what makes it hold: a
# project that carries the rule is told on its next prompt when a report
# newer than any it was told of is open. Keyed by the rule rather than by
# who may read diagnostics, since every project of an administrator's on a
# granted node may, and only BuilderBot's own work answers them.
WATCH_DIAG_RULE = "watch-diagnostics"


def _diag_watch(project, uid):
    """The open reports, newest first, when this project carries the rule
    and its session may read the diagnostics; else None. The same gate as
    _diag_refused (debug mode on, the project granted them, an account with
    the debug grant): the notice named report #68 and its project to a
    session that was refused reading it (the operator, 6 Oct)."""
    try:
        if not any(r.get("name") == WATCH_DIAG_RULE for r in rules.rules(project)):
            return None
        if not settings.get("debug_mode") or not prefs.get(project)["diag"]:
            return None
        me = users.account_of({"session": project, "uid": uid})
        if not me.get("name") or users.may(me, "debug"):
            return None
        return reports.listing()
    except Exception:                                                     # noqa: BLE001
        return None


# The Debug page's switches, the debug grant's (roles.NAMED_ONLY).
DEBUG_SETTINGS = ("debug_mode", "offer_unvetted")


# A Reset that un-enrolls its nodes first: their uninstalls run, and the
# reset follows once each node is retired. Read by GET /api/reset.
_reset_job = {}
_reset_lock = threading.Lock()
RESET_WAIT_S = 20 * 60


def _reset_after(principal):
    """Wait for every node a Reset is un-enrolling to be retired, then reset.
    A node that has not reported in RESET_WAIT_S, or whose uninstall failed,
    stops it with the reason, and nothing is moved."""
    while True:
        rows = _reset_job.get("nodes") or []
        for x in rows:
            n = nodes.node(x["id"]) or {}
            if n.get("state") == "retired" or not n:
                x["done"] = True
            elif x.get("job"):
                j = nodes.job(x["job"], with_log=False) or {}
                if j.get("state") in ("failed", "canceled"):
                    x["error"] = f"its uninstall {j['state']}: {j.get('error') or 'no reason given'}"
        bad = [x for x in rows if x.get("error")]
        if bad or time.time() - _reset_job.get("started", 0) > RESET_WAIT_S:
            _reset_job.update(running=False, error="; ".join(f"{x['name']}: {x['error']}" for x in bad)
                              or "; ".join(f"{x['name']} has not reported its uninstall"
                                           for x in rows if not x.get("done")) + f" in {RESET_WAIT_S // 60} minutes")
            print(f"dashboard: reset stopped: {_reset_job['error']}", flush=True)
            return
        if all(x.get("done") for x in rows):
            break
        time.sleep(3)
    r, status = settings.reset(STATE)
    if status != 200:
        _reset_job.update(running=False, error=r.get("error") or "the reset failed")
        return
    _reset_job.update(running=False, moved_to=r["moved_to"])
    print(f"dashboard: {principal} reset this controller after un-enrolling "
          f"{', '.join(x['name'] for x in _reset_job['nodes'])}; the old state is in {r['moved_to']}", flush=True)
    threading.Timer(1.0, lambda: os.execv(sys.executable, [sys.executable, *sys.argv])).start()


# A controller installed bare metal (R90), by the marker its installer
# writes into the env file it starts from (BB_INSTALL=bare-metal,
# nodes/install-controller.sh), never by guessing from the machine: the
# container install has no such line and is what it always was.
BARE_METAL = os.environ.get("BB_INSTALL", "") == "bare-metal"


def setup_node():
    """The name of a node enrolled, answering and running sessions, for
    Finish on the setup page (R199), or "": a hosting-only one holds no
    code, so a project has nowhere to work or build. On a bare-metal
    install it is this machine's own node (R90), which the installer
    enrolled, and Finish waits for that one and not for another."""
    if nodes is None:
        return ""
    rows = nodes.node_list()
    # ...where the installer made it one (--no-node makes none, and then
    # the first run asks for a node as the container's does).
    own = BARE_METAL and any(nodes.own_machine(n) and n.get("state") != "retired" for n in rows)
    return next((n["name"] for n in rows
                 if n.get("kind") == "agent" and n.get("state") == "online" and n.get("live")
                 and not (n.get("config") or {}).get("host_only")
                 and (not own or nodes.own_machine(n))), "")
# ...and the home tunnel's (R176), applied by tunnel.py when they change.
TUNNEL_SETTINGS = ("tunnel_host", "tunnel_token", "cf_api_token")


# The project's settings a session takes once, when it starts: the trees
# in its view (reads, sees) and the model and effort Claude was started
# with. Changed mid-session they are on the record and not in the session,
# which spent a dozen commands finding that out (report #81, 7 Oct).
START_ONLY = (("reads", "Reads"), ("sees", "Also sees"), ("model", "Model"), ("effort", "Effort"),
              ("tc_off", "Toolchains"), ("packs_on", "Tool packs"), ("works", "repositories"))


def _start_only(project):
    p = prefs.get(project) or {}
    out = {k: p.get(k) for k, _ in START_ONLY}
    # The project's repositories, which a session works in from its start
    # (bb-tty's works): one added or put back since is not in its view.
    key = repos.project_of(project)
    out["works"] = sorted(repos.members(key)) if key else []
    return out


def session_seen_note(project, uid, node, who=None, begin=False):
    """`begin`: record the build and the notebook this session starts from.
    Otherwise what has moved since, in one line, and the record moved on:
    the controller's build (R83) and any half of this project's notebook or
    its settings that somebody else changed."""
    build = _build_now()
    key = f"{project}|{uid}|{node or ''}"
    try:
        revs_now = _seen_now(project, who) if who is not None else {}
        watched = _diag_watch(project, uid)
        top = max((int(r.get("id") or 0) for r in watched or []), default=0)
        with _seen_lock:
            d = _seen_load()
            rec = d.get(key) if isinstance(d.get(key), dict) else {}
            was_build, was_revs = str(rec.get("build") or ""), rec.get("revs") or {}
            was_diag = int(rec.get("diag") or 0)
            start_now = _start_only(project)
            started = start_now if begin or not isinstance(rec.get("start"), dict) else rec["start"]
            # A key the start did not record (a session from before it was
            # one) is not news.
            stale = [label for k, label in START_ONLY if k in started and started.get(k) != start_now.get(k)]
            # Said once for each change, not on every prompt after it.
            new_stale = stale and rec.get("stale_said") != start_now
            d[key] = {"build": build or was_build, "revs": revs_now or was_revs,
                      "diag": max(top, was_diag), "start": started,
                      "stale_said": start_now if new_stale else rec.get("stale_said")}
            write_json(STATE / SESSION_SEEN, d)
        if begin:
            return ""
        said = []
        if build and was_build and was_build != build:
            said.append(f"The controller moved to {build} since this session began (it was on {was_build}): "
                        "`bb catchup` says what changed, and `bb preamble` prints the briefing as "
                        "it is now; this session still holds the one it started with, so where the "
                        "change touches what you are doing, a new session is briefed with it.")
        if was_revs and revs_now:
            # A half with no revision yet (a project with no bug filed) is
            # "" and its first write is a change like any other.
            moved = [(name, verb) for k, name, verb in SEEN_HALVES
                     if k in was_revs and was_revs.get(k, "") != revs_now.get(k, "")]
            if moved:
                said.append("Since your last prompt somebody else changed this project's "
                            + ", ".join(n for n, _ in moved) + ": read "
                            + ", ".join(v for _, v in moved) + " before going on.")
        if new_stale:
            said.append(f"This project's {', '.join(stale)} changed since this session started, and "
                        "a session takes those when it starts: end it and start a new one to have "
                        "them (a project added to Reads answers bb -p already; its tree is mounted "
                        "by the new session).")
        fresh = [r for r in watched or [] if int(r.get("id") or 0) > was_diag]
        if fresh:
            said.append("New in diagnostics since your last prompt: "
                        + ", ".join(f"report #{r['id']} from {r.get('project') or 'the dashboard'}"
                                    for r in reversed(fresh[:5]))
                        + (f" and {len(fresh) - 5} more" if len(fresh) > 5 else "")
                        + f". `bb diag reports` reads them (the house rule {WATCH_DIAG_RULE}).")
        return " ".join(said)
    except Exception as e:                                                # noqa: BLE001
        print(f"[dashboard] session seen: {type(e).__name__}: {e}", flush=True)
        return ""


def image_stamp():
    """Which build of the image this container is running.

    Baked in at the end of the Dockerfile by CI (see BB_IMAGE_REV there).
    Empty when the image was built any other way, which the page reports as
    `unstamped` rather than guessing; the whole point of this is that the
    answer to "is that fix in here?" stops being an inference from uptime.

    Trimmed rather than validated: these come from the image's own build, not
    from anything a request can set, and they are only ever displayed.
    """
    return {"rev": os.environ.get("BB_IMAGE_REV", "").strip()[:40],
            "built": os.environ.get("BB_IMAGE_BUILT", "").strip()[:32],
            # The ordered name for the same build. Derived from the VERSION
            # file at build time, so an image built outside CI has none and
            # the page falls back to the commit, as it always did.
            "version": os.environ.get("BB_VERSION", "").strip()[:64]}


def claude_auth(home=""):
    """{"nodes": {node id: {email, plan}}}: which nodes report this account
    signed in to Claude, and as whom.

    `home` is the asking account's, because the answer is theirs: a login is
    one account's on one node, and the record of what each node reported is
    kept in that account's home (claudegrant.py). The record, and only the
    record: there is no `claude` here to ask, and asking one would answer
    about this container rather than about the machines the account's
    sessions actually run on. One small file, read when asked.
    """
    return {"nodes": {nid: {"email": v["email"], "plan": v["plan"]}
                      for nid, v in claudegrant.nodes_of(home).items()}}


def agent_auth(home=""):
    """{agent id: {"nodes": {node id: {email, plan}}}} for every coding agent
    with a sign-in of its own but Claude's (R95 step 3): what each node
    reported this account is signed in to it as, from the same record."""
    return {a.id: {"nodes": {nid: {"email": v["email"], "plan": v["plan"]}
                             for nid, v in claudegrant.nodes_of(home, a.id).items()}}
            for a in agents.TABLE if a.id != "claude" and a.login_job}


# ---- toolchains ------------------------------------------------------------
# All of it (the catalog, the probes, the sizes, the versions and the worker
# that installs) lives in toolchains.py, which is handed the two helpers it
# needs and otherwise knows nothing about this file.
import toolchains                                                  # noqa: E402

toolchains.configure(run=run, write_json=write_json, state=STATE,
                     project_nodes=lambda: {p: (pr.get("node") or "") for p, pr in prefs.all_projects().items()},
                     workspace=WORKSPACE)
# The tool packs a person added (R77): rows of the same catalog, kept under
# /config, and carried to the nodes in the bundle beside the shipped one.
import toolpacks                                                   # noqa: E402

toolpacks.configure(state=STATE, write_json=write_json,
                    unpack=lambda aid, dest: projects.unpack_archive(aid, dest))
toolchains.packs_rows = toolpacks.recipes
toolchains.refresh_packs()
# The Android system images on each node's store, behind the Emulator tab:
# kept on the toolchain store without being toolchains (emulator.py).
import emulator                                                  # noqa: E402

# ---- reaching a running Claude session -------------------------------------
# One door, one rule about Enter, used by both the to-do list and the memory
# book. See notify.py: it presses Enter only when the line it typed visibly
# arrived, which is the one thing a permission dialog will not do.
import notify                                                    # noqa: E402

notify.configure(run=run,
                 # A session on a node: found by the name the page uses,
                 # told through its agent (roadmap #24). Resolved at call
                 # time: the nodes module is imported further down.
                 on_node=lambda s: next((x for x in node_tmux_sessions() if x["name"] == s), None),
                 node_tell=lambda *a, **k: nodes.tell_wait(*a, **k))

# ---- signing in ------------------------------------------------------------
# The flow runs as a job on a NODE, the machine Claude Code is installed on
# (R47), and the card here carries its link and takes the code back. See
# signin.py for why every part of doing it in a terminal turned out to be
# somewhere it could go wrong.
import signin                                                    # noqa: E402

# ---- who may sign in --------------------------------------------------------
# The dashboard's own accounts (docs/users.md, roadmap #22). Imported here so
# that everything it needs (STATE, write_json) is already built; nothing in
# it reaches back. The FIRST account is made on the first-run screen: there
# is no environment variable behind it.
import users                                                     # noqa: E402

users.configure(state=STATE, write_json=write_json)

# Messages between accounts, and what each project's people are doing. Its own
# module for the same reason nodes and users are: the rules about who may read
# a conversation belong beside the conversation, not scattered through here.
import chat                                                     # noqa: E402
chat.configure(state=STATE, write_json=write_json)

# ---- what each session is changing ------------------------------------------
# Written by the bb-work-note hook inside a session and read by `bb work`;
# the server touches it only for a session on a node, whose hook posts the
# note here because the node has no /config to write (roadmap #24).
import overlap                                                   # noqa: E402
overlap.configure(state=STATE, workspace=WORKSPACE, write_json=write_json)
import plugins                                                   # noqa: E402
plugins.configure(state=STATE, write_json=write_json)


# ---- the test registry ------------------------------------------------------
# The notebook's sixth view: what each test protects, and what it costs. The
# timings are parsed out of a run the operator ingests; nothing here runs a
# suite, and nothing self-reports a duration.
import testreg                                                   # noqa: E402

testreg.configure(write_json=write_json, state=STATE)


# Which PERSON the notebook's logs should name for a change. "you" and
# "claude" answer "a person or a session" and stop there, which was the whole
# answer while there was one person; with several on a project it says
# nothing about which of them dropped an item. The audit trail on the Nodes
# tab has recorded the account since accounts existed, for exactly this
# reason, and this is the same thing for the other four logs.
#
# A thread-local rather than another argument through thirty signatures: the
# modules ask at the moment they write an event. Set on every _who(), which
# every authenticated path calls, so a handler thread reused by the next
# request cannot carry the last one's name. Resolved lazily, so the users
# file is read when something is actually written and not once per request.
_writing = threading.local()


def writer_name():
    u = getattr(_writing, "who", None)
    return str((users.account_of(u) or {}).get("name") or "") if u else ""

# ---- new project, and linking one ------------------------------------------
# Creating and cloning, and the worker that runs the ones that touch the
# network. The credential half stays here (agent_keys and the ssh aliases are
# this box's, not any one project's) and is handed over.
import forges                                                    # noqa: E402
forges.configure(run=run, state=STATE, write_json=write_json)

import projects                                                  # noqa: E402
import mapping                                                   # noqa: E402

# ---- the operator's house rules ---------------------------------------------
# The one thing in the notebook a session reads and cannot write. It rides in
# front of every session started here; claude_scope() in bb-tty denies the
# file tools on the file. Roadmap #7.
import rules                                                     # noqa: E402
# The guard's reading of a shell line, from scripts/lib (rules.py put it on
# the path): `bb rules audit` counts the account's conversations with it.
import rulehook                                                  # noqa: E402
import codebase                                                  # noqa: E402
import pending                                                   # noqa: E402
import settings                                                  # noqa: E402

rules.configure(write_json=write_json, state=STATE, actor=writer_name)
codebase.configure(workspace=WORKSPACE)
# The three stores above configure this one too; done here as well so the
# endpoint works even if none of them has been touched yet this process.
pending.configure(write_json=write_json, state=STATE)
# The Settings tab's own store (roadmap R29): the knobs the operator sets from
# the page rather than the environment. The builder home is where the commit
# identity lands.
settings.configure(write_json=write_json, state=STATE)
settings.forget_runners = lambda: runners.reset()
# What may be offered: the catalogs gate their unvetted entries on this
# one switch (roadmap R54, step 6), read live so a save takes at once.
forges.unvetted_ok = lambda: bool(settings.get("offer_unvetted"))


# ---- who else is in the notebook --------------------------------------------
# The other half of the same question, for a browser rather than a session
# (roadmap #26). Nothing to configure: it holds live seats in memory and
# reads no state, which is the whole of its design; see its header.
import presence                                                  # noqa: E402


# ---- the bug tracker --------------------------------------------------------
# The notebook's third view. Same arrangement again: its own file, handed the
# two helpers it needs, nothing reaching back.
import bugs                                                      # noqa: E402

bugs.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name, workspace=WORKSPACE, actor=writer_name,
               releases=lambda p: roadmap.releases(p),
               changelog_refs=lambda p, k: roadmap.changelog_refs(p, k))

# The notebook's fourth view keeps a log too, and it is the odd one: nothing
# here writes findings, so the entries are derived by comparing one read of
# the report against the last.
import findings                                                  # noqa: E402

findings.configure(write_json=write_json, state=STATE, workspace=WORKSPACE)

# A phone on the end of wireless adb, and pushing an extension to it. Its own
# file for the usual reason; handed the workspace because what it can push is
# derived from the projects rather than browsed for.
import phone                                                     # noqa: E402

phone.configure(write_json=write_json, state=STATE, workspace=WORKSPACE)

# What a project has built, from its dist/ directory: the notebook's fifth
# view. The convention is the module's docstring; the scratch dir is where an
# .xpi is unpacked for web-ext, never dist/ itself.
import artifacts                                                 # noqa: E402
import git as gitview                                            # noqa: E402
import workspace                                                 # noqa: E402

# Each account's git worktree of a project: <this>/<project>/<uid> (common.sh
# session_dir). The Git view and the Artifacts tab both read them.
WORKTREES = Path(os.environ.get("BB_WORKTREES") or str(WORKSPACE / ".worktrees"))
artifacts.configure(workspace=WORKSPACE, worktrees=WORKTREES, state=STATE, write_json=write_json)
# This process is hardened before any key is loaded (R158 step 6): no
# core dump, not dumpable, its memory kept from swap where the limit lets it.
import hardening                                                 # noqa: E402
HARDENED = hardening.apply()
import signing                                                   # noqa: E402

signing.configure(state=STATE, project_name=PROJECT_NAME)
# Keys kept open before the install had an install key, sealed now that it
# has one (R111 step 2); a key that cannot be opened is left as it is and
# said on its project's Signing view.
try:
    if (_sealed := signing.seal_all()):
        print(f"dashboard: sealed {_sealed} signing key(s) under the install's key", flush=True)
except OSError as e:
    print(f"dashboard: signing keys left as they were, not sealed: {e}", flush=True)
# ...the projects' git tokens (R135): gitcreds, and git's helper git-credential-bb...
import gitcreds                                                  # noqa: E402
gitcreds.configure(state=STATE, seal_fn=signing.seal, unseal_fn=signing.unseal,
                   sealing_fn=lambda: signing.MASTER is not None)
# The dashboard's own TLS (R158 step 2): the mode the settings say, the
# certificate's key sealed under the install key.
import tls                                                       # noqa: E402
tls.configure(state=STATE, seal_fn=signing.seal, unseal_fn=signing.unseal,
              sealing_fn=lambda: signing.MASTER is not None)
# The page's Content-Security-Policy and what the browser reports against
# it (R158 step 4, csp.py).
import csp                                                       # noqa: E402
csp.configure(state=STATE)
try:
    if (_sealed := gitcreds.seal_all()):
        print(f"dashboard: sealed {_sealed} git token(s) under the install's key", flush=True)
except OSError as e:
    print(f"dashboard: git tokens left as they were, not sealed: {e}", flush=True)
# ...and the settings' secrets, the tunnel's and Cloudflare's tokens (R135).
settings.seal, settings.unseal = signing.seal, signing.unseal
settings.sealing = lambda: signing.MASTER is not None
try:
    if (_sealed := settings.seal_all()):
        print(f"dashboard: sealed {_sealed} setting(s) under the install's key", flush=True)
except OSError as e:
    print(f"dashboard: settings' secrets left as they were, not sealed: {e}", flush=True)
import membership                                                # noqa: E402
import roles                                                     # noqa: E402
import registry                                                  # noqa: E402
import busy                                                      # noqa: E402
membership.configure(state=STATE, write_json=write_json)
roles.configure(state=STATE, write_json=write_json)
registry.configure(state=STATE, workspace=WORKSPACE, write_json=write_json)
# A project of several repositories (R136): which repositories are in which,
# and prefs laying a project's settings over its repositories'.
import repos                                                     # noqa: E402
repos.configure(state=STATE, write_json=write_json, registry=registry)
gitview.configure(workspace=WORKSPACE,
                  worktrees=WORKTREES,
                  tell=notify.tell, tmux_name=tmux_name, state=STATE,
                  accounts=account_names,
                  owner_uid=lambda: users.uid_of(users.get(users.owner_name() or "")),
                  working=claude_working, owner_name=users.owner_name,
                  session_open=owner_session_open, sessions=sessions_anywhere,
                  git_env=lambda me, name: {k: v for k, v in {**projects._git_env(),
                                                              **users.git_env(me, name)}.items()
                                            if k != "DASHBOARD_AUTH"},
                  may_push=projects.may_push, exclude=mapping.exclude,
                  audit=lambda *row: None if NODES_OK else db.audit(*row),
                  host_of=forges.host_label, ci_of=lambda n: ciwatch.read(n),
                  ci_fix=lambda n, where: ciwatch.fix(n, where))
# Where what grows is kept, as the Settings tab sets it (paths.py): read at
# use by every module below that keeps one of them, so a change applies to
# the next write without a restart.
import paths                                                     # noqa: E402
paths.configure(state=STATE, workspace=WORKSPACE)
workspace.configure(workspace=WORKSPACE, state=STATE)
workspace.packs_json = toolpacks.catalog_json
workspace.packs_files = toolpacks.hosted_files


def no_node_advice(name):
    """What a project with no node can still do, said the same way
    everywhere: a session reads and edits regardless (that is what this
    box is for), and building happens on a node or on GitHub."""
    # Settings is the notebook's view now, and "can push" read as news
    # about a remote beside a repository with no upstream (B456): it is the
    # project's push rights, so it says what to do with them.
    return ("Pick one on the project's notebook Settings"
            + (", or push a commit and let CI build it."
               if projects.may_push(name)
               else ". This project has no push rights either, so CI is not a "
                    "fallback until it does.")
            + " Reading and editing the code needs no node.")


def build_state(name):
    """Where this project's compiling happens, for the Artifacts view: its
    node and what that node carries, or the plain fact that it has none and
    what is left when it does not."""
    if NODES_OK:
        return {"node": "", "name": "", "why": "", "push": projects.may_push(name)}
    nid = prefs.get(name)["node"]
    n = nodes.node(nid) if nid else None
    tc = sorted((n.get("reported") or {}).get("toolchains") or {}) if n else []
    return {"node": nid if n else "", "name": n["name"] if n else "",
            "kind": n["kind"] if n else "", "tools": tc,
            "push": projects.may_push(name),
            "why": "" if n else no_node_advice(name),
            # Its agent behind or out of window: a build is refused until
            # the node is updated, and the tab says so before the refusal.
            "gap": nodes.agent_stale(n) if n else "",
            # What its last build took there, so the next one's room is
            # known before it is refused for it (R110 step 7).
            "took": nodes.last_took(name)}


def artifacts_of(name):
    """dist/ as the tab lists it, each file carrying what built it when a
    job did (docs/nodes.md §6): the chain lives beside the file, and the
    listing is where somebody asks."""
    return [a | {"prov": workspace.provenance(name, a["path"])}
            for a in artifacts.listing(name)]

# ---- the memory book -------------------------------------------------------
# What Claude remembers about each project, read and edited from the projects
# card. Same arrangement as toolchains above: its own file, handed what it needs.
import memory                                                    # noqa: E402

memory.configure(run=run, workspace=WORKSPACE,
                 claude_projects=CLAUDE_PROJECTS, tmux_name=tmux_name,
                 write_json=write_json, state=STATE)
memory.configure_log(write_json=write_json, state=STATE, actor=writer_name)

# ---- the shared to-do list -------------------------------------------------
# The one surface both sides write: the operator adds an item, a session adds
# one and ticks it off. bb-tty puts the open items in front of every Claude
# session it starts, which is the whole reason it is worth having.
import roadmap                                                   # noqa: E402

roadmap.configure(write_json=write_json, state=STATE, tell=notify.tell,
               tmux_name=tmux_name, settle=notify.settle, actor=writer_name)
roadmap.configure_verbs(bugs_mod=bugs)
# A memory edit marks the list's unsaved flag, and presence names the others
# and says when a session last read the list; both are the roadmap's.
memory.mark_unsaved = roadmap.mark_unsaved
chat.users = users
presence.account_names = lambda: {u.get("uid"): n for n, u in users.load()["users"].items()
                                  if u.get("uid")}
presence.readers = roadmap.readers

# ---- what a session is handed ----------------------------------------------
# The three above, assembled in the order a session reads them. bb-tty asks
# for this rather than joining them itself, and the Briefing tab draws the
# same string rather than its own idea of it.
import preamble                                                  # noqa: E402
def live_block():
    """The build this controller is running, for the briefing every session
    starts with (R75 step 5): the fact a session otherwise assumes. Short,
    and pointing at the verbs that answer the rest."""
    st = image_stamp()
    what = st.get("version") or (st.get("rev") or "")[:12] or "an unstamped image"
    when = f", built {st['built']}" if st.get("built") else ""
    return ("## What is live\n\n"
            f"The controller is BuilderBot {what}{when}. A fix pushed since is not "
            "running until the operator rebuilds; `bb status` says what is, `bb catchup` "
            "what changed since, and this line is from the moment this session started.")


preamble.configure(rules_mod=rules, roadmap_mod=roadmap, bugs_mod=bugs, live=live_block)
# ...and a project of several repositories' (R136): its name, id and
# repositories, for the part that briefs a session on all of them.
# Only one of several: since R138 every repository is in a project, and one
# alone was told it was "a project of 1 repositories".
preamble.repos_fn = lambda p: ((registry.label(k), registry.pid(k), [(m, registry.label(m)) for m in repos.members(k)])
                               if (k := repos.project_of(p)) and len(repos.members(k)) > 1 else None)
preamble.project_fn = lambda p: (registry.label(k), registry.pid(k)) if (k := repos.project_of(p)) else None

# ---- a new project's brief -----------------------------------------------------
# What its maker wants built, kept out of CLAUDE.md and handed to the first
# session instead, through a dialog on the first Claude press: brief.py.
import brief                                                     # noqa: E402

brief.configure(workspace=WORKSPACE, state=STATE, write_json=write_json)

# ---- a project's design language and its pages ------------------------------
# What the project looks like, kept: colors as tokens, type, shape, space and
# the operator's rules, and pages laid out as labeled blocks; a prompt a
# session is pointed at and docs/design-language.md written from it: design.py.
import design                                                    # noqa: E402

design.configure(workspace=WORKSPACE, state=STATE, write_json=write_json)
# The notebook's wiki (R112): a repository of the controller's own per
# project, pushed with the project's granted rights and nothing the tree says.
import wiki                                                      # noqa: E402
wiki.configure(state=STATE, workspace=WORKSPACE, write_json=write_json,
               push_record_fn=lambda p: projects.load_push().get(p),
               token_helper_fn=projects.token_helper, parse_fn=forges.parse,
               config_fn=lambda d: gitrelay.config(d), env_fn=projects._git_env)

# A project's CI on GitHub's own runners (R115): its runs and a failed job's
# log, read with the controller's credential for a session that has none.
import cilogs                                                    # noqa: E402
cilogs.configure(state=STATE, workspace=WORKSPACE, push_record_fn=lambda p: projects.load_push().get(p),
                 config_fn=lambda d: gitrelay.config(d), parse_fn=forges.parse)
# ...and watched (R117): once a day per project with workflows, and at once
# when a project is linked; the Git view, bb catchup and the bell read it.
import ciwatch                                                   # noqa: E402
ciwatch.configure(state=STATE, workspace=WORKSPACE, write_json_fn=write_json,
                  projects=lambda: sorted(d.name for d in WORKSPACE.iterdir()
                                          if d.is_dir() and not d.name.startswith(".")))

# ---- the standing model and effort -----------------------------------------
# One preference for every send, on its own card; see the module docstring
# for why it stopped being a question inside each send box.
import logs                                                      # noqa: E402
import idle                                                      # noqa: E402
logs.configure(state=STATE, write_json=write_json)
logs.diag_report = lambda: diag.report()
logs.audit = lambda *row: db.audit(*row)
logs.conversation_text = lambda rid: reports.conversation(rid)
idle.configure(state=STATE, write_json=write_json,
               # A changed rule reaches every node on its next poll rather
               # than its next ten-minute hello.
               changed=lambda: [nodes.ask_hello(n["id"]) for n in nodes.node_list()
                                if n.get("kind") == "agent"])
# On boot, because that is when a generation was just rotated in and the oldest
# one fell off the end of the policy; then every hour (log_sweep_loop below).
logs.prune()

import prefs                                                     # noqa: E402
# Debug and dev options only on a controller started with DEBUG_MODE=1; at a
# start without it every one of them is put back off, so turning it on
# again starts from nothing granted (the operator, 12 Oct).
if not settings.debug_available():
    try:
        if settings.reset_debug() | bool(prefs.reset_debug()):
            print("dashboard: DEBUG_MODE is not 1, so every debug and dev option was turned off", flush=True)
    except Exception as e:                                # noqa: BLE001 (a start must not fail on this)
        print(f"dashboard: debug options not reset: {e}", flush=True)
# The briefing reads a project's own settings for its "While tests run"
# section (what a change asked for during a run does); prefs is imported
# after preamble is configured, so it is handed over here.
preamble.prefs_mod = prefs
preamble.label_of = registry.label
preamble.id_of = registry.pid
preamble.packs_of = lambda: {n: {"label": (r.get("manifest") or {}).get("label") or n, "guidance": r.get("guidance") or ""}
                             for n, r in toolpacks.packs().items()}


def _project_node_gpu(project):
    """Whether the project's own node reports an NVIDIA card: what decides
    the briefing's GPU section."""
    if NODES_OK:
        return False
    nid = (prefs.get(project) or {}).get("node") or ""
    n = nodes.node(nid) if nid else None
    return bool(n and (n.get("reported") or {}).get("gpu_card"))


preamble.node_gpu = _project_node_gpu

prefs.configure(write_json=write_json, state=STATE)
prefs.configure_repos(project_of=repos.project_of, members=repos.members, is_repos=registry.is_repos)
users.home_of = repos.key_of
roles.label_of = registry.label
projects.key_of = repos.key_of
roles.home_of = repos.key_of
# Said again, now that prefs exists: users.git_identity resolves a per-project
# override of the commit author, and that override lives in prefs, which is
# configured after users because the login path must not depend on it.
users.configure(state=STATE, write_json=write_json, project_prefs=prefs.for_user,
                # The nodes of an account's projects: what a node grant's
                # scope "mine" means (R137 step 3).
                # Its list names projects (R138): each read through its
                # repositories, whose settings carry the project's node.
                nodes_of=lambda u: {n for p in (u.get("projects") or []) for r in (repos.members(p) or [p])
                                    for n in prefs._nodes_of(prefs.get(r) or {})})

# ---- the dev instance ------------------------------------------------------
# A project's compose app, built and run on the sandbox VM's daemon. The
# module's docstring carries the security reasoning.
import devapp                                                    # noqa: E402
devapp.label_of = registry.label
import devactions                                                # noqa: E402
import home                                                      # noqa: E402
import containers                                                # noqa: E402
import nginxproxy                                                # noqa: E402
import imagecheck                                                # noqa: E402
import relocate                                                  # noqa: E402
import tunnel                                                    # noqa: E402
import storage                                                   # noqa: E402
import db                                                        # noqa: E402
import nodes                                                     # noqa: E402
import termws                                                    # noqa: E402
termws.configure(agent_dir=nodes.AGENT_DIR)
import tokenkeys                                                 # noqa: E402
tokenkeys.configure(agent_dir=nodes.AGENT_DIR)
# Each account's public key on a node, to seal its sign-ins with (R126).
nodes.token_pubs = lambda nid, old=False: tokenkeys.pubs(nid, [u["uid"] for u in users.all_users() if u.get("uid")], old)
nodes.token_stale = tokenkeys.under_previous
nodes.can_seal = lambda: signing.MASTER is not None
import claudecode                                                # noqa: E402
import agentcode                                                 # noqa: E402
import projsessions                                              # noqa: E402
import turns                                                     # noqa: E402

# The node data plane first, because devapp's job claim asks it which node
# work belongs to. Guarded: a database that will not open (a corrupt file, a
# full disk) must degrade to the dashboard this always was, not take down the
# page that is the operator's way to see what is wrong; nodes.py's readers
# and audit already no-op when it never came up.
try:
    nodes.configure(state=STATE)
    # The registry answers hello; the catalog is toolchains.py's. Joined here
    # rather than by one importing the other, which is the same seam every
    # other module pair uses.
    nodes.layout_of = toolchains.layout_for_node
    # ...and the digest of the bb bundle, so a node can tell from hello alone
    # whether the bb its sessions run is the one this controller ships.
    nodes.bundle_digest = lambda: workspace.bundle()["digest"]
    nodes.idle_minutes = idle.minutes
    nodes.session_tokens_for = session_tokens_for
    # A project born with a starting version commits it the way the
    # Artifacts tab gives a first version (projects._init).
    projects.first_version = lambda name, value, env: version.init(name, value, by="operator", env=env)
    # Each session kept to its own project's network (R79): the setting is
    # the node's, what each project owns there is devapp's.
    # ...and the containers' (R178): whether each project's are kept apart
    # here, and what each compose project may reach, whatever the sessions'
    # switch says.
    nodes.session_net_for = lambda nid: (({"on": True, "own": router.with_peers(_with_vmnets(nid, devapp.session_net_own(nid)))}
                                          if nodes.session_net_on(nid) else {"on": False, "own": {}})
                                         | {"ctr_on": nodes.container_net_on(nid),
                                            "ctr": devapp.container_net_own(nid) if nodes.container_net_on(nid) else {},
                                            # Whether this node's VMs may reach its LAN (R91 step 8).
                                            "vm_lan": bool(((nodes.node(nid) or {}).get("config") or {}).get("vm_lan"))})
    NODES_OK = ""
    # The job logs are the only copy of what a node's job wrote and had no
    # retention at all until R17 step 1. Swept once here for whatever ended
    # while this controller was down; a running one sweeps a project as its
    # own jobs end, which is when it gains a log.
    # The one log policy (the Logs section's days) reaches the job logs,
    # and Clear reaches them too.
    nodes.log_days = logs.days
    logs.clear_job_logs = nodes.clear_job_logs
    try:
        _gone = nodes.prune_job_logs()
        if _gone:
            print(f"[dashboard] job logs: dropped {_gone} past the policy", flush=True)
    except Exception as e:                                # noqa: BLE001
        print(f"[dashboard] job log sweep skipped: {e}", flush=True)
except Exception as e:                                    # noqa: BLE001
    NODES_OK = str(e)
    print(f"[dashboard] node store unavailable: {e}", flush=True)


def net_nudge():
    """Every session-net node says hello again (nodes.session_net_nudge),
    after a write that already succeeded: a container changing hands, an
    instance made or removed. What it reads is the store, so that is the
    one fault it absorbs, logged; the answer the caller sends is unchanged."""
    try:
        nodes.session_net_nudge()
    except sqlite3.Error as e:
        print(f"[dashboard] session network nudge skipped: {e}", flush=True)


# ---- a node's CI runners ----------------------------------------------------
# The root-only helper that keeps each runner's token and mints from it, and
# the list the Runner card draws: runners.py.
import runners                                                   # noqa: E402

runners.configure(run=run, nodes=None if NODES_OK else nodes)

# The controller's own runner (docs/nodes.md §2, phase 4): the thread that
# takes compose and local exec jobs off the queue and runs them here. devactions
# registers its compose runner through configure(), so the queue is the seam
# between the two and neither imports the other.
import jobs                                                      # noqa: E402

if not NODES_OK:
    jobs.configure(nodes_module=nodes)
    toolchains.nodes = nodes
    toolchains.claudecode = claudecode
    toolchains.agentcode = agentcode
    emulator.nodes = nodes
    phone.nodes = nodes            # every adb command is a job on a node
    # A compose action the AGENT ran still has records to write here; this is
    # where the module that queued it finishes it (roadmap #18).
    nodes.on_done("compose", devactions.compose_done)
    nodes.on_done(claudecode.JOB, claudecode.update_done)
    for _a in agentcode.tracked():
        nodes.on_done(_a.update_job, agentcode.update_done)
# What Allow on a rebuild request actually starts (the Docker row's `ask`).
# Outside the block above: the ask has nothing to do with the node registry,
# and a controller without one still has projects whose containers run.
phone.rebuilder = devactions.rebuild
phone.container_maker = containers.create_container
phone.container_free = containers.name_free
phone.container_builds = containers.build_refusal
phone.instance_maker = devactions.make_instance
# What a renamed project is called now, for the name Send offers (R154).
devapp.label_of = registry.label
phone.env_writer = lambda project, text, instance: devapp.write_env(project, text, instance or devapp.MAIN)
phone.ctl_runner = containers.ctl_on
# ---- what the page may type into a terminal -------------------------------------
# The tables, the pins, the operator's own lists and the typing itself:
# macros.py. A node's session is typed into through its agent.
import macros                                                    # noqa: E402

macros.configure(state=STATE, write_json=write_json, lock=_state_lock, run=run,
                 tmux_sessions=tmux_sessions, tmux_base=tmux_base,
                 session_tmux=lambda nid, ops: nodes.session_tmux(nid, ops))
phone.remover = devactions.remove_instance
# ...and what the tab's verbs and the asking need about who is asking
# (phone.verb): the projects an account sees, a project's node and its Run
# its container dial, a container held to its project's node (R79).
phone.users = users
phone.project_names = lambda who: set(project_names(who))
phone.project_node = lambda p: prefs.get(p)["node"]
phone.project_hosts = lambda p: prefs.get(p).get("hosts") or []
phone.dial = lambda p: prefs.get(p)["devbuild"]
phone.on_project_node = devapp.on_project_node
# A phone lent to a project (R113): its sessions drive the project's own app.
import phonelease                                                # noqa: E402
phonelease.configure(workspace=WORKSPACE, project_node_fn=lambda p: prefs.get(p)["node"],
                     may_see_fn=users.may_see)
phone.leasing = phonelease
phone.run_denied = devapp.RUN_DENIED
phone.net_nudge = net_nudge
phone.resolve_artifact = artifacts.resolve
phone.artifact_list = artifacts_of
# ...and what the Artifacts tab's read composes (artifacts.tab_view).
artifacts.listing_of = artifacts_of
artifacts.account_names = account_names
artifacts.build_state = build_state

artifacts.instance_states = devactions.row_states
artifacts.capture_days = lambda name: prefs.get(name)["capture_days"]
artifacts.dev_keep = lambda name: prefs.get(name)["dev_keep"]
artifacts.phone_summary = lambda name, uid: phone.summary(
    prefs.get(name)["node"], uid,
    nodes.node(prefs.get(name)["node"]) if prefs.get(name)["node"] and not NODES_OK else None)
# The settings dialog's save (prefs.dialog_save).
prefs.configure_dialog(WORKSPACE=WORKSPACE, pin_instances=devapp.pin_to_current_node,
                       end_agents=end_agents, net_nudge=net_nudge)

# ---- the Profile tab -------------------------------------------------------------
# An account's own settings, read and saved: profiletab.py.
import profiletab                                                # noqa: E402
# Two-factor sign-in (R127): the authenticator, passkeys and recovery codes.
import mfa                                                       # noqa: E402

mfa.configure(STATE=STATE, seal=signing.seal, unseal=signing.unseal,
              sealing=lambda: signing.MASTER is not None)
try:
    if (_sealed := mfa.seal_all()):
        print(f"dashboard: sealed {_sealed} authenticator secret(s) under the install's key", flush=True)
except OSError as e:
    print(f"dashboard: authenticator secrets left as they were, not sealed: {e}", flush=True)

# The install key made by the install and changed from the page, and each
# account's own key for its sign-ins on the nodes (R154): what the nodes
# report of their seals decides when a key before today's can go.
import accountkeys                                               # noqa: E402
import logins                                                    # noqa: E402
import unlocks                                                   # noqa: E402
import installkey                                                # noqa: E402


def _node_seals():
    return {n["id"]: (n.get("reported") or {}).get("tokseal") for n in nodes.node_list(all=True)}


accountkeys.configure(state=STATE, nodes_under=lambda uid, k: tokenkeys.sealed_under(_node_seals(), k, uid))
# An unlock that gives up less (R158 step 5): a person's tokens opened per
# use for the window they pick, each use logged for them, and a store under
# a key of their own (R157) opened only while they have unlocked it.
unlocks.configure(state=STATE, key_under_install=accountkeys.key_under_install, open_entry=accountkeys.open_entry_with,
                  entry_of=accountkeys._entry, own_of=accountkeys.own_of, set_for=accountkeys.set_unlock_for,
                  live=logins.live, ts=tokenkeys.ts, wipe=hardening.wipe,
                  run_dir=os.environ.get("BB_HANDOUT_DIR") or "")
unlocks.clear_all_handouts()
# Who is signed in now (R159): the rows the cookies name, and a device
# signed in as the account counts the same way.
logins.configure(state=STATE, days=SESSION_DAYS,
                 devices_of=lambda uid: devices.listed({"uid": uid}))
# The bell's rows sent elsewhere, per person (R149, reach.py): the
# destinations each keeps on Profile, the mail server from the settings.
import reach                                                     # noqa: E402
reach.configure(state=STATE, write_json=write_json, seal=signing.seal, unseal=signing.unseal,
                sealing=lambda: signing.MASTER is not None,
                smtp_settings=lambda: {"host": settings.get("smtp_host"), "port": settings.get("smtp_port"),
                                       "security": settings.get("smtp_security") or "starttls", "user": settings.get("smtp_user"),
                                       "password": settings.secret("smtp_password"), "from": settings.get("smtp_from")})
# A model router on a node (R144 step 1, router.py): LiteLLM with the
# provider keys, Ollama beside it, a key per allowed project.
import router                                                    # noqa: E402
router.configure(state=STATE, write_json=write_json, seal=signing.seal, unseal=signing.unseal,
                 sealing=lambda: signing.MASTER is not None, node_list=nodes.node_list,
                 node_name=lambda nid: (nodes.node(nid) or {}).get("name") or nid,
                 node_addr=lambda nid: str((nodes.node(nid) or {}).get("addr") or ((nodes.node(nid) or {}).get("agent") or {}).get("addr") or ""),
                 project_names=lambda: list(prefs.all_projects(WORKSPACE)), job_add=nodes.job_add,
                 job_get=lambda jid: nodes.job(jid, with_log=True))
installkey.configure(passes=(signing.seal_all, gitcreds.seal_all, settings.seal_all, mfa.seal_all,
                             accountkeys.seal_all, reach.seal_all, router.seal_all),
                     nodes_previous=lambda: tokenkeys.sealed_under(_node_seals(), signing.PREVIOUS)
                     if signing.PREVIOUS else 0)
installkey.note_made()
# Every account's own key made at the start that can seal it, a fresh
# install's first and an upgraded one's first alike, rather than when it is
# first needed (the operator, 27 Oct); one added later has its own made then.
for _u in users.all_users():
    if _u.get("uid"):
        accountkeys.key_of(_u["uid"])
# A project's token from before tokens were a person's: into its owner's key
# store, the project linked to it (0011, the operator, 27 Oct).
try:
    if (_moved := gitcreds.adopt(membership.owner_of)):
        print(f"dashboard: {_moved} project token(s) moved into their owners' key stores", flush=True)
except OSError as e:
    print(f"dashboard: project tokens left as they were: {e}", flush=True)

# An account's conversations with Claude as a download: transcripts.py.
import transcripts                                               # noqa: E402

transcripts.configure(workspace=WORKSPACE,
                      root_for=lambda uid: (Path(home_for(uid)) / ".claude" / "projects")
                      if home_for(uid) else CLAUDE_PROJECTS,
                      state=STATE, write_json=write_json)
profiletab.configure(users=users,
                     claude_email=lambda uid: ", ".join(sorted(
                         {v["email"] for v in claudegrant.nodes_of(home_for(uid)).values()}, key=str.lower)),
                     agent_emails=lambda uid: claudegrant.emails_of(home_for(uid)),
                     plugins_of=plugins.of,
                     node_names=lambda: {n["id"]: n["name"]
                                         for n in ([] if NODES_OK else nodes.node_list())},
                     logs_of=lambda me: transcripts.mine(
                         users.uid_of(me), project_names(me)))
devapp.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                 log_dir=logs.log_dir, field=field,
                 node_for=nodes.node_for if not NODES_OK else None,
                 # A hosting-only node has no docker address here: the controller
                 # holds no key to a VPS, and every `docker compose config` and
                 # data-directory mkdir addressed at it waited out a 30s ssh
                 # timeout, twice per nginx Save on a hosting node, holding the server
                 # with it (R85 step 1, the operator, 11 Oct). With no address
                 # the config check runs the compose plugin here, which parses
                 # without a daemon, and the directory is the agent's to make.
                 node_addr=(lambda nid: "" if nodes.host_only(nid) else nodes.ssh_addr_of(nid)) if not NODES_OK else None,
                 queue=nodes if not NODES_OK else None,
                 runner=jobs if not NODES_OK else None,
                 project_node=lambda p: prefs.get(p)["node"],
                 project_nodes=lambda p: prefs.get(p)["nodes"],
                 node_paths=nodes.node_paths if not NODES_OK else None,
                 node_reported=(lambda nid: (nodes.node(nid) or {}).get("reported") or {}) if not NODES_OK else None)
# The layer on top of it: the compose runner is its, so it is the one that
# hands jobs.py the function.
devactions.configure(runner=jobs if not NODES_OK else None)
home.configure(nodes_mod=nodes, devapp_mod=devapp)
devapp.gpu_why = gpu_container_why
devapp.room_why = lambda nid: nodes.room_short(nid, room_floor_gb()) if nid else ""
nodes.room_floor_gb = room_floor_gb
devapp.container_mem_gb = lambda: settings.get("container_mem_gb")
# ...and what its request() needs about who is asking, and who hears.
devactions.users = users
devactions.ask_rebuild = phone.ask_rebuild
devactions.say = chat.event
devactions.net_nudge = net_nudge
# ...and the Docker tab's container verbs (containers.py) the same.
containers.dial = lambda p: prefs.get(p)["devbuild"]
containers.users = users
containers.ask_rebuild = phone.ask_rebuild
containers.net_nudge = net_nudge
containers.ports_local = nodes.ports_local_on
containers.ctr_spark = nodes.ctr_spark
# One nginx per node, from the nginx tab (R171): its records here, the
# container through containers.py, and the node's own view of its ports.
imagecheck.configure(state=STATE, write_json=write_json, devapp_module=devapp)
# The VM manager (R91): its records, the jobs it queues, and what becomes of
# them; a session's ask through the same machinery a container's goes.
import vms                                                       # noqa: E402

vms.configure(state=STATE, write_json=write_json, node=nodes.node, node_list=nodes.node_list,
              job_add=nodes.job_add, audit=db.audit, prefs_get=prefs.get, nodes_rev=nodes.rev,
              enroll_script=nodes.enroll_script,
              node_retire=lambda by, nid: nodes.node_state(by, nid, "retired"),
              node_mark=nodes.node_vm_of, node_discard=nodes.node_discard, job_tail=nodes.job_tail)
nodes.on_done("vm", vms.vm_done)
# ...run as an administrator's, since the asks go to the administrators
# alone and Allow is theirs (R116): a device passed through lands.
phone.vm_runner = lambda project, req, by: _vm_do(f"session:{project} (allowed by {by})", project, dict(req, _admin=True), True)


def _with_vmnets(nid, own):
    """Each project's own reach on a node, with the network its VMs are on
    there (R91 step 8): its sessions reach those and no other project's."""
    own = dict(own or {})
    for project, net in vms.nets_on(nid).items():
        own[project] = dict(own.get(project) or {}, vmnets=[net])
    return own


def _vm_do(principal, project, req, session):
    """One VM verb for `project`: new is vms.create, onto the project's own
    nodes for a session and any VM host for a person; an ISO's fetch or
    removal is vms.iso; the rest vms.act."""
    if field(req, "action") in ("iso-add", "iso-rm"):
        return vms.iso(principal, field(req, "action"), req)
    if field(req, "action") == "vbios":
        return vms.vbios(principal, req, bool(req.get("_admin")))
    if field(req, "action") == "new":
        allowed = devapp.nodes_of(project) or [] if session else [n["id"] for n in vms.hosts()]
        return vms.create(principal, project, req, allowed, session=session, admin=bool(req.get("_admin")))
    return vms.act(principal, project, field(req, "name"), field(req, "action"), dict(req, _session=session))


nginxproxy.configure(state=STATE, write_json=write_json, node_list=nodes.node_list,
                     node_name=lambda nid: (nodes.node(nid) or {}).get("name") or nid,
                     taken_ports=devapp.taken_ports)
# BuilderBot's own scanners on each node (R145, scanners.py): deployed and
# run as compose and scan jobs there, their reports sent up.
import scanners                                                  # noqa: E402
scanners.configure(state=STATE, write_json=write_json, node_list=nodes.node_list,
                   node_name=lambda nid: (nodes.node(nid) or {}).get("name") or nid,
                   project_nodes=lambda: nodes.project_nodes() if nodes.project_nodes else {},
                   project_names=lambda: list(prefs.all_projects(WORKSPACE)),
                   job_add=nodes.job_add, job_state=_job_state,
                   next_after=schedules.next_after, cron_words=schedules.words)
findings.STATE_REPORTS = scanners.report_files
# A DNS-01 challenge's record goes through the Cloudflare API token Settings
# holds (R150).
nginxproxy.cf_token = lambda: settings.secret("cf_api_token")
# ...and put on a node the moment it enrolls when the Enroll dialog asked
# for it (config.nginx), so a box runs the script and nginx appears.
# The home tunnel the controller runs itself (R176, tunnel.py): from the
# settings, started at boot below when they say so.
tunnel.configure(settings_mod=settings, dash_port=PORT)
nodes.ON_ENROLL.append(lambda nid: nginxproxy.deploy(nid, containers, devactions, devapp)
                       if ((nodes.node(nid) or {}).get("config") or {}).get("nginx") else None)

# ---- the version ----------------------------------------------------------
# One identity per project, rendered per target; the module's docstring says
# why one literal string cannot work. Handed the two notebook halves as well:
# the case for a bump is "what has happened since the target last moved", and
# only the roadmap's and the tracker's dated logs know that.
import changelog                                                 # noqa: E402
import claudegrant                                              # noqa: E402
# The Claude sign-in's verbs are signin.py's; the record of what each node
# reported is claudegrant.py's.
signin.nodes = None if NODES_OK else nodes
signin.mint = users.mint_session
claudegrant.home_for = home_for

# ---- the node agent's channel -----------------------------------------------------
# The verbs behind /api/v1/agent/: channel.py.
import channel                                                   # noqa: E402

channel.configure(home_for=home_for)
channel.unvetted_ok = lambda: bool(settings.get("offer_unvetted"))   # a Mac's provisioner is a dev feature
# A signing is a job on the project's node, of a build in its dist/ (R106).
signing.node_of = lambda name: prefs.get(name)["node"]
signing.node_refuses = lambda nid: nodes.agent_stale(nodes.node(nid)) if nid and not NODES_OK else ""
signing.job_add = nodes.job_add
signing.file_path = workspace.file_path
# What needs a jdk or build-tools is a sign-key job on that node too, waited
# for (signing._on_node): the controller runs no keytool or apksigner.
signing.node_get = nodes.node
signing.job_get = nodes.job
signing.job_cancel = nodes.job_cancel
signing.node_tools = toolchains.node_has
phone.signer = signing.start


def _releaser(project, comp, asker_name, principal):
    """A session's release, run as the Artifacts view's Release runs it
    (version.verb's release), under the asking account's commit identity
    and with the project's own credentials (R138)."""
    # The asker's commit identity, else the project's owner's: a relayed bb
    # carries a token minted for the project and no account.
    who = (users.get(asker_name) if asker_name else None) or users.get(membership.owner_name(project) or "") \
        or {"name": asker_name or "claude"}
    return version.verb(project, "release", {"component": comp}, who, principal)


phone.releaser = _releaser


def _release_editor(project, plan, asker_name="", principal=""):
    """An edit of a published release (R139), made here with the project's
    own token, which the session never holds: the notes replaced, the
    files attached that edit_plan() checked."""
    r = forgerelease.edit(project, plan)
    if not NODES_OK:
        db.audit(principal, "version-release-edit", project,
                 {"tag": plan.get("tag"), "notes": plan.get("notes") is not None,
                  "files": [x["name"] for x in plan.get("files") or []], "error": r.get("error") or ""})
    said = forgerelease.edit_said(r)
    return ({"error": said, "forge": r.get("forge") or ""}, 400) if r.get("error") else ({"edited": r, "said": said}, 200)


phone.release_editor = _release_editor


def _release_remover(project, plan, asker_name="", principal=""):
    """Files taken off a published release, its own ask (the operator,
    5 Oct), with the project's own token."""
    r = forgerelease.remove(project, plan)
    if not NODES_OK:
        db.audit(principal, "version-release-remove", project,
                 {"tag": plan.get("tag"), "files": [x["name"] for x in plan.get("files") or []],
                  "removed": r.get("removed") or [], "error": r.get("error") or ""})
    said = forgerelease.remove_said(r)
    return ({"error": said}, 400) if r.get("error") else ({"removed": r, "said": said}, 200)


phone.release_remover = _release_remover


def _keymaker(action, project, args, by=""):
    """A new generated key or a package's key, for a session's auto dial and
    for Allow on its ask (R106 step 6)."""
    if action == "generate":
        return signing.generate(project, str(args.get("route") or ""), str(args.get("key") or "default"), by=by)
    if action == "map":
        return signing.set_map(project, str(args.get("package") or ""), str(args.get("key") or ""))
    if action == "rotate":
        return signing.rotate(project, str(args.get("from") or ""), str(args.get("to") or ""), by=by)
    return {"error": f"not a key change: {action}"}, 400


phone.keymaker = _keymaker


def _release_signer(project):
    """A release's APKs looked for and signed again now (R134 step 5): a
    session's auto dial, and Allow on its ask."""
    started = releasesign.check_soon(project, force=True)
    return {"ok": True, "started": started,
            "said": "looking for unsigned release APKs to sign" if started else "a look is already going"}, 200


phone.release_signer = _release_signer
artifacts.sign_routes = signing.routes_held
import version                                                   # noqa: E402
import vmtemplate                                                # noqa: E402
vmtemplate.unvetted_ok = forges.unvetted_ok          # the same switch (R54, step 6)
# The Nodes tab's verbs are nodes.verb's, and these are what they compose
# with (a runner's forge and token, a daemon probe, Claude Code's update).
nodes.configure_verbs(vmtemplate=vmtemplate, forges=forges, devapp=devapp,
                      runner_store=runners, workspace=workspace,
                      project_prefs=prefs.get, may_push=projects.may_push,
                      no_node_advice=no_node_advice, turns_of=node_turns,
                      working_on=lambda nid: node_turns(nodes.node(nid) or {"id": nid})["working"])

version.configure(workspace=WORKSPACE, state=STATE, write_json=write_json,
                  roadmap_mod=roadmap, bugs_mod=bugs, changelog_mod=changelog,
                  tell_fn=notify.tell, tmux_name_fn=tmux_name,
                  )
changelog.component_dir = version._sub
# Release's forge half (R123; Gitea and GitLab, R124): the release beside a pushed tag.
import forgerelease                                              # noqa: E402
import featuresoff                                               # noqa: E402
forgerelease.configure(state=STATE, workspace=WORKSPACE, write_json_fn=write_json)
# A release's APK, built unsigned in CI and signed on the project's node with
# its sideload key (R106): a release made from the panel is looked for at once.
import releasesign                                               # noqa: E402
releasesign.configure(state=STATE, workspace=WORKSPACE, write_json_fn=write_json,
                      projects=lambda: sorted(d.name for d in WORKSPACE.iterdir()
                                              if d.is_dir() and not d.name.startswith(".")))


def _forge_release(project, tag, version_, sha, comp=""):
    """forgerelease.publish, and the release's unsigned APK expected for
    signing once a release was made (releasesign.expect)."""
    r = forgerelease.publish(project, tag, version_, sha, comp)
    if r.get("url") and not r.get("error"):
        releasesign.expect(project, tag)
    return r


# The briefing says what a session may move the version by, with the rest
# of the project's dials (preamble.dials_line).
preamble.version_policy = version.policy
version.configure_verbs(PANEL=version_payload, GIT_ENV=users.git_env, CREDS_ENV=projects._git_env,
                        MAY_PUSH=projects.may_push, SESSIONS=sessions_anywhere,
                        FORGE=_forge_release,
                        AUDIT=lambda *row: None if NODES_OK else db.audit(*row))



# Claude Code on the nodes (claudecode.py): what each runs against what is
# out, and the one way it is updated, which is an administrator's press.
if not NODES_OK:
    claudecode.configure(nodes_module=nodes, node_sessions=node_tmux_sessions,
                         tmux_base=tmux_base, audit=nodes.audit)
    agentcode.configure(nodes_module=nodes, node_sessions=node_tmux_sessions,
                        tmux_base=tmux_base, audit=nodes.audit, claude=claudecode)

# Every account's sessions on a project, for its settings dialog, and an
# administrator ending one (projsessions.py): the rows the Sessions card is
# made from, and its kill.
projsessions.configure(sessions=lambda: tmux_sessions() + node_tmux_sessions(),
                       base=tmux_base, owner=tmux_owner, accounts=account_names,
                       owner_name=users.owner_name, end=end_session)
projsessions.BEHIND = session_behind

# The code map, built for a project the moment it exists (mapping.py): the
# same command a session runs by hand, started in the background by the
# create paths, and the one thing a Claude session on a new project waits for.
mapping.configure(workspace=WORKSPACE,
                  codemap=Path(__file__).resolve().parent.parent / "lib" / "codemap.py")
# Every project's .bb-map/ out of its git, once, beside the start.
threading.Thread(target=mapping.exclude_all, daemon=True).start()
projects.configure(run=run, workspace=WORKSPACE, agent_keys=agent_keys,
                   gh_authed=gh_authed, ensure_deploy_alias=ensure_deploy_alias,
                   project_name=PROJECT_NAME,
                   state=STATE, home=os.environ.get("BUILDER_HOME", str(Path.home())),
                   write_json=write_json,
                   after_create=mapping.start)
# A checkout still pointed at git's own store, which reads neither a
# sealed token nor one in a person's store, pointed at BuilderBot's helper.
try:
    if (_rescoped := projects.rescope_store_helpers()):
        print(f"dashboard: {', '.join(_rescoped)} now ask BuilderBot's credential helper", flush=True)
except OSError as e:
    print(f"dashboard: checkouts' credential helpers left as they were: {e}", flush=True)
# The session network reaches the containers of the projects a project reads.
devapp.reads_of = prefs.reads_trees
devapp.hosts_of = lambda p: (prefs.get(p) or {}).get("hosts") or []
devapp.reaches_of = prefs.reaches_on
# ...and what the create dialog's follow-ups and the sidebar's pins need.
projects.lock = _state_lock
projects.take_on = users.take_on
projects.set_prefs = lambda name, **kw: prefs.set_prefs(name, workspace=WORKSPACE, **kw)
projects.brief_writer = brief.write
# A create that never took, and a project deleted for good, leave no owner,
# owner role or account entry behind (B93, B95); the first its settings too.
projects.purged = lambda name: membership.forget_project(name, live=registry.live_dirs())
projects.unmade = lambda name: (prefs.forget(name), projects.purged(name), repos.forget(name))

# ---- a node's git, relayed --------------------------------------------------
# Push, fetch, pull and ls-remote from a session on a node, done in a
# repository of the controller's own rather than in the tree the session can
# write: gitrelay.py (B148).
import gitrelay                                                  # noqa: E402

gitrelay.configure(state=STATE, workspace=WORKSPACE,
                   push_record=lambda p: projects.load_push().get(p),
                   token_helper=projects.token_helpers, parse_url=forges.parse,
                   host_of=forges.host_of, git_env=projects._git_env)
# The modules that keep something that grows read where from paths.py.
workspace.paths = gitview.paths = logs.paths = gitrelay.paths = paths

# ---- the bb relay -----------------------------------------------------------
# A bb verb from a session on a node, run here (roadmap #24): which verbs
# travel and what a token may do with them are bbrelay.py's.
import bbrelay                                                   # noqa: E402

import pushscan                                                  # noqa: E402

pushscan.configure(state=STATE, write_json=write_json)
bbrelay.configure(users=users, projects=projects, prefs=prefs, gitrelay=gitrelay, registry=registry,
                  WORKSPACE=WORKSPACE, STATE=STATE, phone=phone, pushscan=pushscan)


def _push_approved(rec, by):
    """A held push approved on the bell (R219): the flagged lines okayed
    for the project, then the push, unscanned, in the relay's own
    repository, as the session's bb would have run it."""
    pushscan.okay(rec.get("project") or "", rec.get("findings") or [], by)
    to = str(rec.get("to") or "")
    return gitrelay.run(rec.get("project") or "", rec.get("cwd") or str(WORKSPACE / (rec.get("project") or "")),
                        "push", rec.get("args") or [], scan=False, uid=to if to.startswith("u_") else "")


phone.pusher = _push_approved
# ...and the Git view's Push reads the same way, asking in a confirm.
gitview.SCAN = lambda project: gitrelay.run(project, str(WORKSPACE / project), "push", [], scan="only")
gitview.OKAY = pushscan.okay

# ---- a session's hooks, from a node -------------------------------------------
# The overlap notes, the chat feed, the catch-up and the turn queue, posted by
# a node's hooks with the session's token (roadmap #24): hooks.py.
import hooks                                                     # noqa: E402

hooks.configure(users=users, rules=rules, preamble=preamble, overlap=overlap, chat=chat, roadmap=roadmap, pending=pending,
                turns=turns, nodes=nodes, seen_note=session_seen_note, turn_scope=turn_scope,
                asking_set=asking_set, asking_clear=asking_clear, asked=projsessions.asked,
                agent_state=agent_state_set, agent_conv=agent_conv_set, behind=session_behind_of)


# Written by entrypoint.sh once every startup hook has finished. Named here as
# well as in lib/common.sh, which is the cost of the marker crossing the
# bash/python line; the comment there carries the reasoning.
BOOT_READY_FILE = Path(os.environ.get("BOOT_READY_FILE", "/run/builderbot-ready"))
BOOT_WAIT = 180
BOOT_GRACE = 300


# When this process started, for the one question only it can answer: which
# nodes have dialed in since.
STARTED = time.time()
NODE_WAIT = 300


_DOWN = []


def _went_down():
    """When the controller last heard any node before this start: when it
    stopped, near enough. A crash an hour long put every node outside a
    quarter hour of the start, so none was waited for and the doctor's
    first run said each one was not dialing in (19 Oct). Read once: a node
    dialing in again takes its stamp out of the reckoning."""
    if not _DOWN:
        seen = [float((n.get("agent") or {}).get("last_seen") or 0)
                for n in nodes.node_list() if n.get("kind") == "agent"]
        _DOWN.append(max([s for s in seen if s < STARTED] or [STARTED]))
    return _DOWN[0]


def _reconnecting(n):
    """Whether a node not dialing in is one this controller heard shortly
    before it went down, and is still inside the start's wait for it: the
    agent reconnects on its own clock, so it is coming back, not down."""
    seen = float((n.get("agent") or {}).get("last_seen") or 0)
    if not time.time() - STARTED < NODE_WAIT or seen >= STARTED:
        return False
    return _went_down() - 900 < seen


def wait_for_nodes(limit=NODE_WAIT):
    """Hold until every node that was alive when this controller went down
    has dialed in again, or give up.

    The same race wait_for_boot closes, one step further out. An update
    restarts the controller and every agent reconnects on its own schedule
    (bb-sandbox-redhat took over two minutes on 18 Sep), so a doctor run in
    that window says "not dialing in" and "no node can run a session" about
    nodes that are fine, and keeps saying it for doctor.EVERY. Only nodes
    heard in the quarter hour before the controller went down are waited
    for: one that had been off for a day is not coming back because the
    controller did.
    """
    if NODES_OK:
        return
    end = time.time() + limit
    while time.time() < end:
        try:
            rows = nodes.node_list()
            down = _went_down()
            owed = [n for n in rows
                    if n.get("kind") == "agent"
                    # Whole seconds: last_seen is stamped as an int, so a node
                    # that dialed in the same second this started (48 against
                    # 48.6) is back, not owed until its next heartbeat.
                    and down - 900 < float((n.get("agent") or {}).get("last_seen") or 0) < int(STARTED)]
        except Exception as e:                                   # noqa: BLE001
            # A wait at startup, not a step of it: the store unreadable or a
            # row malformed means nobody is waited for, said once here.
            print(f"[dashboard] not waiting for nodes: {type(e).__name__}: {e}", flush=True)
            return
        if not owed:
            return
        time.sleep(5)


def wait_for_boot():
    """Hold until the container has finished starting, or give up.

    This dashboard is started BY hook 15 and the hooks after it are still
    running. A `bb doctor` run inside that window does not report an early
    truth, it reports a falsehood; and doctor.EVERY is half an hour, so it
    stuck. Measured when a GPU still booted here: doctor cached at +46s and
    the thing it was asking about came up at +48s, so the card was wrong
    until somebody pressed refresh. The operator's remedy for that message is
    to restart the container, which runs the same race again, so it read as
    the fault
    recurring rather than as a stale answer.

    It does not care whether the wait succeeded: a dashboard started outside the
    entrypoint (`bb dashboard dev`, the test harness, an image whose entrypoint
    predates the marker) has none coming, and checking anyway is the behavior
    this has always had. So the wait ends on the container's own age as well as
    on a clock: mid-boot is the only time a missing marker means anything, and
    at that point pid 1 is under a minute old.
    """
    for _ in range(BOOT_WAIT * 2):
        if BOOT_READY_FILE.exists():
            return True
        if _container_age() > BOOT_GRACE:
            return False
        time.sleep(0.5)
    return False


def _container_age():
    """Seconds since pid 1 started, which is this container's own age.

    Not /proc/uptime: under Docker that is the HOST's, four days here on a
    container three minutes old, so it answers a different question entirely.
    And not the mtime of /proc/1, which this used to read: that is when the
    kernel made the directory's inode, and it makes it again whenever it is
    evicted, so a process twenty minutes old read as two. Then the doctor
    waited out the boot, three minutes, and the suite's first page timed out
    on a Doctor card that had not come (19 Sep, in a session's view, where
    pid 1 is bb-session and there is no ready marker to end the wait early).
    The start time itself: /proc/1/stat's 22nd field, in clock ticks since
    the machine booted, on top of /proc/stat's btime.
    """
    try:
        with open("/proc/1/stat") as f:
            ticks = int(f.read().rsplit(")", 1)[1].split()[19])
        with open("/proc/stat") as f:
            btime = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return max(0.0, time.time() - (btime + ticks / os.sysconf("SC_CLK_TCK")))
    except (OSError, ValueError, IndexError, StopIteration):
        return float("inf")     # cannot tell: treat it as "not booting"


def client_gone(sock):
    """Whether the peer of a held request has closed: readable with nothing
    to read is EOF. Only a positive answer counts: an exception (a socket
    that cannot be peeked) reads as still there, so a held poll is never
    dropped on a guess."""
    try:
        sel = selectors.DefaultSelector()
        try:
            sel.register(sock, selectors.EVENT_READ)
            ready = sel.select(0)
        finally:
            sel.close()
        if not ready:
            return False
        return sock.recv(1, socket.MSG_PEEK) == b""
    except (OSError, ValueError):
        return False


# ---- bb doctor, cached for the Doctor card: doctor.py ----------------------
import doctor                                                    # noqa: E402

doctor.configure(run=run, wait_for_boot=lambda: (wait_for_boot(), wait_for_nodes()),
                 runner_named=lambda nid, slot: (
                     (nodes.node(nid) or {}).get("name") or "",
                     re.sub(r"^[a-z]+://[^/]+/|\.git$|/$", "",
                            ((nodes.runners_of(nodes.node(nid) or {}).get(slot) or {}).get("url") or ""))))
# A node dialing in after silence re-asks the doctor now rather than in up
# to half an hour: after a reboot the card kept saying no node could run a
# session long after they were all back (the operator, 25 Sep).
nodes.came_back = lambda nid: threading.Thread(target=doctor.refresh, name="doctor-after-hello",
                                               daemon=True).start()
# The Docker tab's first pick is derived from where the projects are bound.
# A job of a container written for a project is that project's (B321).
nodes.job_owner = lambda j: devapp.owner_of(j.get("project") or "",
                                           (j.get("spec") or {}).get("instance") or devapp.MAIN)
nodes.project_nodes = lambda: {p: (v or {}).get("node") or ""
                               for p, v in prefs.all_projects(WORKSPACE).items()}
devapp.all_project_nodes = lambda: {p: (v or {}).get("nodes") or []
                                    for p, v in prefs.all_projects(WORKSPACE).items()}

def _ftp_node(nid):
    """What ftp.py asks of a node: its name, the address it dials in from,
    and whether its store has the ftp toolchain (None while it has not
    reported its store)."""
    n = nodes.node(nid)
    if not n:
        return None
    has = toolchains.node_has(n)
    return {"name": n.get("name") or nid, "addr": (n.get("agent") or {}).get("addr") or "",
            "has_ftp": ("ftp" in has) if has else None}


# A project's file access over FTP (R151): the store and its checks are
# ftp.py's, the server is the node's (bb-ftpd from the ftp toolchain), and a
# login is relayed by the agent to channel's ftp-auth.
import ftp                                                       # noqa: E402
ftp.configure(state=STATE, workspace=WORKSPACE, write_json=write_json, users=users,
              audit=lambda who, act, target, params: db.audit(who, act, target, params),
              project_node=lambda p: prefs.get(p)["node"] or "",
              ask_hello=lambda nid: None if NODES_OK else nodes.ask_hello(nid),
              node_info=lambda nid: None if NODES_OK else _ftp_node(nid))
ftp.locked_out = projects.locked_out       # a lock makes the files read-only through every door (B263)
nodes.ftp_for = ftp.for_node
# The node's nginx container, for its log stream (R182): named only where the nginx tab put one.
nodes.nginx_for = lambda nid: nginxproxy.container_name(nid) if nginxproxy.deployed(devapp, nid) else ""

# The controller's diagnostics: read-only, for an administrator and, behind
# the debug switch and a node's tick, an administrator's session (diag.py).
import diag                                                      # noqa: E402
devapp.redact = diag.redact       # docker.log carries argvs and output tails

import reports                                                   # noqa: E402
import files                                                     # noqa: E402
files.configure(workspace=WORKSPACE, audit=db.audit)
# A node's projects as a synced copy (R162): the nodes in sync mode a
# project is bound to, and VS Code's writes reaching them at once.
import wssync                                                    # noqa: E402
import claudesync                                                # noqa: E402


def _sync_bound(project):
    if NODES_OK:
        return []
    pr = prefs.get(project)
    synced = nodes.sync_node_ids()
    return [i for i in dict.fromkeys([pr.get("node") or "", *(pr.get("nodes") or [])]) if i and i in synced]


wssync.configure(workspace=WORKSPACE, nodes_module=nodes, bound_nodes=_sync_bound,
                 changed=files._poke, audit_fn=db.audit)
wssync.configure_projects(lambda: list(prefs.all_projects()))
wssync.configure_reads(prefs.reads_trees)
# Each project's daily snapshots (R165): what a node gone wrong through its
# synced copy is undone from, kept for the days its settings say.
import snapshots                                                 # noqa: E402
snapshots.configure(workspace=WORKSPACE, days=lambda p: prefs.get(p)["snapshot_days"],
                    on=lambda p: prefs.get(p)["snapshots_on"],
                    names=lambda: [p for p in prefs.all_projects() if (WORKSPACE / p).is_dir()],
                    audit_fn=lambda *row: None if NODES_OK else db.audit(*row))
files.on_change = wssync.changed
# A synced node writes the transcripts of the projects it holds and nothing
# else: bound to it, never one it only reads (B613).
claudesync.configure(workspace=WORKSPACE, held=lambda nid: wssync.bound_projects(nid))
reports.configure(write_json=write_json, state=STATE, redact=diag.redact,
                  build=lambda: image_stamp().get("version") or image_stamp().get("rev") or "")
# A report says which node its project builds on, and clearing them all is
# audited like every other mutation.
reports.node_name = lambda p: ((nodes.node(prefs.get(p)["node"]) or {}).get("name", "")
                               if prefs.get(p)["node"] and not NODES_OK else "")
reports.audit = db.audit
diag.configure(image_stamp=image_stamp, uptime=uptime, doctor_payload=doctor.payload,
               settings=settings, nodes=nodes, db=db, log_dir=logs.log_dir,
               plugins=plugins, users=users, reports=reports, state_dir=lambda: STATE)
# A person's devices (R272): their tokens, and the door their apps sync a
# project through as a node does (wssync), as far as the editor's door lets
# that person (ftp.access_for).
import devices                                                   # noqa: E402
devices.configure(users=users.load, access=lambda acct, p: ftp.access_for(acct, p, "editor"),
                  unlock=lambda uid, key: (unlocks.unlock(uid, unlocks.secret_from_hex(key)) if unlocks.secret_from_hex(key)
                                           else {"error": "the key is 64 hex characters"}),
                  projects=lambda acct: project_names(acct),
                  flags=lambda acct, p: projects.app_flags(p, users.uid_of(acct)))
profiletab.configure(devices=devices, logins=logins, reach=reach, smtp_set=lambda: bool(settings.get("smtp_host")), mfa=mfa, audit=db.audit,
                     two_factor_required=lambda u: roles.two_factor_required(u))

# The apps a person installs, fetched from this controller's release and
# served from /apps (R272 step 3); which of them are offered is the
# Settings page's, set first by the seed file (step 4).
import apps                                                      # noqa: E402
# A newer release for a bare-metal install (R90 step 5, releasecheck.py):
# asked of GitHub a while after the start and daily, on the bell and under
# Controller settings, applied as the own node's system job.
import releasecheck                                              # noqa: E402
releasecheck.configure(version=lambda: image_stamp().get("version") or "", bare_metal=lambda: BARE_METAL)
# A held start on a bare-metal install (R56 step 9, held.py): read at the
# start, lifted by Start on This machine, armed for the next restart.
import held                                                      # noqa: E402
held.configure(state=STATE, bare_metal=lambda: BARE_METAL, write_json_fn=write_json)
apps.configure(state=STATE, version=lambda: image_stamp().get("version") or "",
               setting=settings.get, write_json=write_json, audit=db.audit)
apps.unvetted_ok = channel.unvetted_ok      # the Windows companion and the VS Code extension are dev features
devices.configure_apps(apps)

# A person's PC lent to a project (R270 step 6): the companion lends a
# table of verbs, a session asks with bb pc under Agents may: Use a lent PC.
import pcwork                                                    # noqa: E402
pcwork.configure(workspace=WORKSPACE, mode_fn=lambda p: (prefs.get(p) or {}).get("pc") or "deny",
                 notify_fn=lambda uid, text, level: notices.act(uid, {"action": "add", "text": text,
                                                                      "level": level, "kind": "said"}))
devices.configure_pc(pcwork)


# ---- revisions -------------------------------------------------------------
# One token per thing a view can depend on. A view says what it watches and is
# told when that moves; it never writes its own "should I re-read?" rule.
#
# Four bugs in one week came from every view inventing that rule out of
# knowledge it did not have: the roadmap's arrows not noticing a session
# start, the Artifacts tab not noticing a phone connect, and the phone view
# polling only when it ALREADY knew about a request, which meant it could
# never learn of the first one. Each was patched where it hurt. This is the
# shape that stops the fifth.
#
# Everything here must be cheap, because it is asked for every second or two.
# Files answer with their mtime; counters answer from memory. Nothing in this
# function runs git, lists tmux, or shells out; that is what makes it
# affordable to ask often, and it is the whole reason it is not snapshot().
def _mtime(path):
    try:
        return int(Path(path).stat().st_mtime_ns)
    except OSError:
        return 0


# A store's revisions(), recomputed only when its file moves.
#
# Those five functions each read and parse a whole state file, which was
# affordable on the fifteen-second poll they were written for and is not on
# the one-and-a-half-second one they moved to. The key is the file's mtime in
# nanoseconds, so a second write in the same second is still a miss, and a
# write from `bb`, in another process entirely, invalidates this the same way
# the dashboard's own does, because it is the file that is being watched and
# not a counter in here.
_rev_cache = {}


def _cached(path, fn):
    key = str(path)
    m = _mtime(path)
    hit = _rev_cache.get(key)
    if hit is not None and hit[0] == m:
        return hit[1]
    v = fn()
    _rev_cache[key] = (m, v)
    return v


def revisions(who=None, projects=None):
    """Every token a view watches, cheap enough to ask for every second or two.

    `projects` is what the page actually has open: the notebooks, which are
    the only things that watch a per-project key. Without it every project
    pays for every poll, which was affordable while the per-project half was
    three stats and stopped being when the memory stamp joined them. A client
    that sends nothing still gets all of them: `bb` and the tests do.
    """
    names = [d.name for d in WORKSPACE.iterdir()
             if d.is_dir() and not d.name.startswith(".")] \
        if WORKSPACE.is_dir() else []
    if projects is not None:
        want = set(projects)
        names = [n for n in names if n in want]
    # Read once for the whole request, and only when a notebook is open on
    # something: with no per-project work to do these are five files nobody
    # asked about.
    nb_revs = bug_revs = test_revs = rule_revs = pend_revs = {}
    if names:
        nb_revs = _cached(STATE / "roadmap.json", roadmap.revisions)
        bug_revs = _cached(STATE / "bugs.json", bugs.revisions)
        test_revs = _cached(STATE / "tests.json", testreg.revisions)
        rule_revs = _cached(STATE / "rules.json", rules.revisions)
        pend_revs = _cached(STATE / "pending.json", pending.revisions)
    revs = {
        # The container itself. A restart invalidates everything a page holds.
        "boot": layout.boot_id(),
        # One file each, so any write through any path moves the token: the
        # CLI's included, which no in-process counter would catch.
        "findings": _mtime(STATE / "findings-log.json"),
        "reports": findings.reports_mtime(),
        # In memory, free to read.
        "phone.asks": len(phone.requests_open()),
        "phone.dev": phone.device_rev(),
        # A phone lent to a project (R113): the lease and its newest shot.
        "phone.lease": phonelease.rev(),
        "toolchains": toolchains.job_rev(),
        # Google's image index read ending, landed or not; its start is not
        # news to the tab that asked (B757). The images themselves ride the
        # node and job tokens, which the Emulator tab watches as well.
        "emulator": str(emulator._choices["reads"]),
        # Node and job data never joins the status payload (docs/nodes.md
        # §13): the views that show it watch this and fetch their own.
        "nodes": 0 if NODES_OK else nodes.rev(),
        # ...and a heartbeat's numbers alone, which the Nodes page draws and
        # nothing else does (R218 step 10).
        "nodes.sample": 0 if NODES_OK else nodes.sample_rev(),
        # ...and a node's containers changing by themselves or by a shell:
        # the Containers page re-reads on it.
        "containers": 0 if NODES_OK else nodes.ctr_rev(),
        # The chat between accounts, bumped on every message (R218 step 10):
        # an open chat re-reads on it rather than every four seconds.
        "chat": chat.rev(),
        # The nginx tab's record and hostnames (B714): a route written from
        # a Docker row, bb or another browser.
        "nginx": nginxproxy.rev(),
        # The VMs page (R91): a record written, or a node's census of them.
        "vms": vms.rev(),
        # A release's APK being looked for and signed (R106): the Signing
        # view follows a look to its end, and the bell's row goes with it.
        "releasesign": releasesign.rev(),
        "jobs": 0 if NODES_OK else nodes.jobs_rev(),
        # Who has a session where, and whether it is working: the project
        # rows fetch /api/live when this moves.
        "live": projsessions.live_token(),
    }
    # Per project, for the views that are per project.
    for n in names:
        # ...and each account's worktree's, whose builds the tab lists too
        # (B237): a stat per worktree, and a project has a handful.
        wts = WORKTREES / n
        revs[f"dist:{n}"] = max([_mtime(WORKSPACE / n / "dist")]
                                + ([_mtime(d / "dist") for d in wts.iterdir()]
                                   if wts.is_dir() else []))
        # A session may bump while the operator has the tab open, and the
        # policy file moves when they change who may bump. Both are cheap
        # stats; neither shells out to git.
        revs[f"ver:{n}"] = _mtime(WORKSPACE / n / "VERSION")
        # The project's reflog: it moves on every commit, which is what the
        # dev row's "the code has moved since the last build" is derived
        # from. Without it that verdict only refreshed when something else
        # happened to move: a Rebuild button that wakes on the next poll
        # rather than the next time you happen to touch the tab. A stat, not
        # a git call.
        revs[f"git:{n}"] = _mtime(WORKSPACE / n / ".git" / "logs" / "HEAD")
        # The notebook's six halves. COUNTERS, not mtimes, and that is the
        # whole of why this is not three more stats: each of these panels
        # holds the number it last read, so it can tell somebody else's write
        # from the echo of its own. An mtime cannot, and a redraw a panel did
        # not need detaches the send box or the half-typed row under the
        # finger that opened it. testreg is the sharpest case: describing ONE
        # test deliberately does not move its counter, where writing the file
        # obviously moves its mtime.
        #
        # The memories are the one thing here that is not a file in the state
        # directory: they are files in an ACCOUNT's home, so that stamp is a
        # glob of one directory. Which is what `projects` is for: one open
        # notebook's worth rather than the whole share's, every second and a
        # half. home_for is memoised, so none of this shells out.
        revs[f"roadmap:{n}"] = (nb_revs.get(n) or {}).get("roadmap", 0)
        revs[f"bug:{n}"] = bug_revs.get(n, 0)
        revs[f"tests:{n}"] = test_revs.get(n, 0)
        revs[f"rules:{n}"] = rule_revs.get(n, rules.EMPTY_REV)
        revs[f"pending:{n}"] = pend_revs.get(n, 0)
        # The wiki's reflog, which every commit and pull moves: a stat.
        revs[f"wiki:{n}"] = wiki.rev(n)
        if who is not None:
            revs[f"mem:{n}"] = memory.census(
                n, home=home_for(users.uid_of(who)))["rev"]
    revs["vpolicy"] = _mtime(STATE / "versions.json")
    revs["prefs"] = _mtime(STATE / "claude-prefs.json")
    # The Settings tab's store (R29): a save has to reach the next poll, and
    # the payload is rebuilt only when something in this list moves.
    revs["settings"] = _mtime(STATE / "settings.json")
    # The dev-instance job and its files. In-memory counter plus mtimes, so
    # the poll never spawns docker.
    revs["devapp"] = devapp.job_rev()
    return revs


# Who has polled lately, in memory: presence, not a record. See chat.online.
_polls = {}
# ...and when each account's last-seen was last written to its record: at
# most every ten minutes while it polls, so chat can say when somebody was
# last here across a restart, without rewriting the file that holds the
# password hashes four times a minute per open browser.
_seen_written = {}
SEEN_WRITE_S = 600

def _findings_counts(who, ps):
    """Per-project finding counts for the poll, scoped the way the tab is.

    counts() is already narrowed to the projects the caller may see, but it
    buckets a path it could not place under "", and for a session that bucket
    holds every row the attribution refused: the rest of the box. So a session
    gets its own project's number and nothing beside it, and the unplaceable
    `heads` that go with it are dropped at the call site for the same reason.
    """
    c = findings.counts(ps)
    mine = (who or {}).get("session")
    return {k: v for k, v in c.items() if k == mine} if mine else c


def _timed(name, fn):
    """One part of a read, timed by its name (timing.py)."""
    with timing.timed(name):
        return fn()


def snapshot(who):
    """The status read: every node row it asks for read once (nodes.held)."""
    with nodes.held():
        return _snapshot(who)


def _snapshot(who):
    if who and who.get("name") and users.uid_of(who):
        _polls[who["name"]] = time.time()
        if _polls[who["name"]] - _seen_written.get(who["name"], 0) > SEEN_WRITE_S:
            _seen_written[who["name"]] = _polls[who["name"]]
            users.touch(who["name"])
    with timing.timed("status:projects"):
        ps = project_list(who)
    # Sessions this account has any business seeing: its own shells, and
    # anything on a project it was given. Filtered here for the same reason
    # the project list is (roadmap #22): a member restricted to one project
    # could otherwise read every other project's name off the session list,
    # which is exactly what hiding the projects was for. An account that sees
    # everything sees the unowned ones too: terminals opened before accounts,
    # or by something that is not a browser.
    mine, seen = users.uid_of(who), {p["name"] for p in ps}
    # Judged by what the node calls it: the owner's node sessions are shown
    # bare (node_tmux_sessions), and by the bare name they read as unowned,
    # so every account on that project listed the owner's Claude as its own.
    with timing.timed("status:sessions"):
        every = tmux_sessions() + node_tmux_sessions()
        sessions = [s for s in every
                    if _session_visible(s.get("node_name") or s["name"], mine, seen, users.sees_all(who))]
    with timing.timed("status:signin"):
        login = signin.state(mine)
    # Each shell's git context, resolved here where WORKSPACE is known: the
    # git/GitHub command cards ghost against the directory the active shell
    # is actually in, and matching a cwd to a project is this server's
    # knowledge, not something the page should re-derive from path strings.
    by_name = {p["name"]: p for p in ps}
    for s in sessions:
        cwd = s.get("cwd", "")
        top = cwd[len(str(WORKSPACE)) + 1:].split("/")[0] \
            if cwd.startswith(str(WORKSPACE) + "/") else ""
        p = by_name.get(top)
        s["git"] = bool(p and p["git_ok"])
        s["github"] = bool(p and p.get("github"))
    attention, bell_hidden = _timed("status:attention", lambda: _attention(who))
    return {
        "host": os.uname().nodename,
        "uptime": uptime(),
        # How many phone requests are waiting on the operator. A count and not
        # the requests themselves: this rides on every poll, and it exists so
        # the Phone tab knows when to go and fetch the real thing. Reading it
        # is a length() on a list in memory: no adb, nothing to pay for.
        "phone_asks": _timed("status:phone_asks", lambda: len(phone.requests_open(users.uid_of(who), users.is_admin(who)))),
        # The invitations to a project waiting on this account, for its bell
        # (membership.py): Accept and Decline are answered there.
        "invites": _timed("status:invites", lambda: membership.mine(who)),
        # A project this account sees whose main branch's newest CI run
        # failed (ciwatch.red, R117): a bell row while it is true.
        "ci_red": _timed("status:ci_red", lambda: bellseen.filter_rows(
            users.uid_of(who), ciwatch.red([p["name"] for p in ps]))[0]),
        # A file changed on two synced copies at once (R162, wssync.py): the
        # copy kept beside it, listed until it is deleted.
        "sync_conflicts": _timed("status:sync_conflicts", lambda: wssync.conflicts(lambda p: users.may_see(who, p))),
        # What is pinned in the bell about nodes (an agent behind, or from
        # another window), computed here on every poll so an alert clears
        # the moment it stops being true; nothing is stored to dismiss.
        "attention": attention,
        # ...and this account's own standing notice to add a second factor
        # (R127), kept out of `attention`, whose rows are the nodes' and
        # carry what the companion app reads off them.
        "two_factor_due": _timed("status:two_factor", lambda: _two_factor_due(who)),
        # How many of them this account has put away, for the drawer's
        # "show them again".
        "bell_hidden": bell_hidden,
        # Claude Code per node against the latest known, for the Nodes
        # tab's section.
        "claude_code": _timed("status:claude_code", lambda: {} if NODES_OK else _claude_code_for(who, ps)),

        # Whether there is a daemon behind any of the Docker controls, and if
        # not, the sentence saying why. Memoised in devapp, because answering
        # it properly is a subprocess: this rides the poll, and the poll is the
        # page's heartbeat. Every Docker button on the page reads this one
        # answer rather than each finding out by failing.
        "docker": _timed("status:docker", lambda: devapp.available_default()),
        # An administrator's, as the Logs section that reads it is: it
        # walks the log directory and the CI tree, which a session's poll
        # has no use for and every poll would pay.
        "logs": _timed("status:logs", lambda: logs.payload() if users.is_admin(who) else None),
        "idle": _timed("status:idle", lambda: idle.payload()),
        # Which run of the container this is. The page stamps it into the URL
        # of every Claude terminal it opens, so bb-tty can tell a request made
        # now from one a browser carried across a restart.
        "boot": layout.boot_id(),
        "image": _timed("status:image", lambda: image_stamp()),
        # A bare-metal install's release against the newest (R90 step 5),
        # with its own node for the Update press; {} on a container install.
        "release": _timed("status:release", lambda: (dict(releasecheck.status(), node=_own_node_id())
                                                      if BARE_METAL else {})),
        # ...and whether its start is held (R56 step 9), with why.
        "held": held.status(),
        "projects": ps,
        # Every project this account sees (R138), one with no repository in
        # it too: the Projects page draws each as one card, from this.
        "repos": _timed("status:repos", lambda: _project_cards(who, ps)),
        "sessions": sessions,
        # Every node with a runner on it: the Runner card is a view of these
        # and nothing else, since CI left this container (phase 7). Read from
        # the census, which already carries it.
        "node_runners": _timed("status:node_runners", lambda: _runners_for(who)),
        "reports": _timed("status:reports", lambda: findings.mounted()),
        "reports_mtime": _timed("status:reports_mtime", lambda: findings.reports_mtime()),
        "findings_counts": _timed("status:findings_counts", lambda: _findings_counts(who, ps)),
        # ...and, for the row they land on, what those paths actually look
        # like. Order matters: this reads what the call above computed. Empty
        # for a session: a head is a fragment of a path from outside its
        # project, which is the one thing it must not be shown.
        "findings_heads": _timed("status:findings_heads", lambda: [] if (who or {}).get("session") else findings.heads()),
        # ...and whether there is a readable report at all, which is what the
        # Static analysis button and the Analysis tab ghost on.
        "reports_ok": _timed("status:reports_ok", lambda: findings.reports_ok()),
        # ...and when each report was written, so one left behind by a failed
        # scanner is visible rather than silently counted as current.
        "reports_ages": _timed("status:reports_ages", lambda: findings.reports_ages()),
        "doctor": _timed("status:doctor", lambda: doctor.payload()),
        # Which nodes report this account signed in to Claude, and the
        # sign-in of theirs that is running, if one is.
        "claude_auth": _timed("status:claude_auth", lambda: claude_auth(home_for(users.uid_of(who)))),
        # The asker's key store (R158 step 5, R157): whether it is under a
        # key of their own and shut, so the page asks for it before a
        # terminal opens and the Git view says why a push would wait.
        "store": unlocks.status(users.uid_of(who)) if users.uid_of(who) else {},
        # ...and the other coding agents' the same way (R95 step 3).
        "agent_auth": _timed("status:agent_auth", lambda: agent_auth(home_for(users.uid_of(who)))),
        "signin": login,
        # A clone or a first push runs in the background now, so the card can
        # say what it is doing without the dialog being open.
        # The clone or link in flight, for whoever may start one (B171): it
        # names a project the account may not have been given, and its
        # buttons are that account's.
        "project_job": _timed("status:project_job", lambda: {} if users.may(who, "create") else projects.job()),
        # The code maps being built for new projects, and the ones that just
        # finished: the row says "mapping the code" and then how many files.
        "mapping": _timed("status:mapping", lambda: mapping.payload()),
        "max_tabs": layout.max_tabs(),
        # Everything the Settings tab edits, with where each value came from.
        "settings": _timed("status:settings", lambda: settings.payload() | {"tunnel": tunnel.status(), "tls": tls.status(settings.get)}),
        # The features this install switched off (R81), {feature: why}: each
        # draws its controls dead with the sentence under them.
        "off": featuresoff.sentences(),
        # ...and where the controller keeps what grows, an administrator's.
        "paths": _timed("status:paths", lambda: {} if users.may(who, "admin") else paths.view()),
        # The command list is built from the table above rather than spelled out
        # again in the page, so a command added here appears as a button and one
        # removed cannot leave a button that posts a name the server rejects.
        # The Commands panel: the Linux and git lists, the pins and the
        # operator's own lists.
        **macros.cards(),
        # The open tabs, so a phone picks up the desktop's layout rather than
        # starting from scratch. Carried in the status poll because it is small
        # and every client is already asking for that every 15s. THIS
        # account's: the strip follows the person to any browser they sign in
        # on, and stops following them to somebody else's (roadmap #25).
        "layout": _timed("status:layout", lambda: layout.load_layout(users.uid_of(who))),
        # Who this is, so the page can name a shell session the way bb-tty
        # will (index.html's myTmux). Not a secret: it is this account's own
        # id, and it is already the key to everything the page saves.
        "uid": users.uid_of(who),
        # What this account's shell sessions are named with, or "" for the
        # owner, who keeps the bare names (users.tmux_prefix says why). The
        # page has to agree with bb-tty about this exactly, or a tab addresses
        # a session that was never created under that name.
        "tmux_prefix": users.tmux_prefix(who),
        # What this account may do, by capability rather than by role: the
        # page should never branch on "is this a user", because the answer to
        # "may I" is the thing that moves and the role is only how it is
        # decided today. Every one of these is refused again on the server;
        # this is what stops a dead control being drawn, not what stops the
        # action (roadmap #27).
        # Whether any node has what the Emulator tab needs, and why not: the
        # Tools card ghosts its button on this.
        "emulator": {"ready": False, "why": "the node store did not open"} if NODES_OK
                    else emulator.ready(),
        "can": {name: not users.may(who, name) for name in
                ("terminal", "docker-write", "vms-write", "toolchains-write", "git-auth", "admin",
                 # The CI runner tab, a job run and a project's node, by
                 # grant (R137 step 3): the Tools card hides CI runner on it.
                 "runner", "jobs", "node",
                 # ...and what the sidebar and the dialogs offer (step 4):
                 # drawn from the same grants the server refuses on.
                 "lock", "rename", "trash", "version", "create", "command-pin",
                 # ...and the debug options, which a page without the grant
                 # does not show at all (the operator, 6 Oct).
                 "debug",
                 # ...and Controller settings' own writes (deleting a bug
                 # report among them), for a reader who may not.
                 "controller")}
               # ...and what other projects a session may read: the owner's
               # alone (the operator, 6 Oct), whatever the grants say.
               | {"reads": (who or {}).get("role") == "owner",
                  # ...and maintenance mode, the owner's alone, a session of
                  # theirs counting as them.
                  "maintenance": (users.account_of(who) or {}).get("role") == "owner"},
        # ...and, for the page-wide ones a bar offers, the server's own
        # refusal, which is said under the dead control (B87).
        "can_why": {name: users.may(who, name) for name in ("create", "trash")},
        # Each area's level anywhere (R152 step 3), so the page hides a tab
        # whose area this account may not read: "", read or write.
        "areas": {a: ("write" if users.is_admin(who or {}) or (who or {}).get("session")
                      else roles.level_of(who or {}, a)) for a in roles.AREA_KEYS},
        # Projects whose Claude session belongs to somebody else, by NAME:
        # "alice has a session on this" is the whole value of the record, and
        # a bare refusal would tell you nothing you could act on. Only for
        # projects this account can see, and never their own, which is not
        # held against them (roadmap #26).
        # Who has a Claude session on each project: BuilderBot account names,
        # everybody including the asker. More than one may (roadmap #24), each
        # in a worktree of their own, so this is a list and it is information
        # rather than a refusal: the row says who is here and nothing is
        # grayed for it. The page decides how to word "you and alice".
        # claude_with; which of them are working on a prompt right now, for
        # the dot beside each name (the operator, 24 Sep), claude_busy; which
        # are on Claude Code's permission prompt, claude_asking (B104); and
        # one row per account per node, claude_where, for the project row's
        # list: which machine each session is on. Every account's sessions
        # on the projects this account sees, as /api/live gives them.
        **projsessions.maps(every, seen),
        # This account's own name, so the row can say "you and alice" rather
        # than reading your own name back at you.
        "me": (who or {}).get("name", ""),
        # ...and whether it administers this controller, so the page can word
        # an empty Projects card for a user with nothing granted rather than
        # telling them the share is not mounted (16 Sep).
        "admin": bool(who) and users.is_admin(who),
        # A controller installed bare metal (R90): its own machine is the
        # first node, which the setup page shows being set up.
        "bare_metal": BARE_METAL,
        # ...and its own machine's node when it has one (R90 step 8), which
        # the rail's This machine is drawn for.
        "own_node": _own_node_id() if BARE_METAL else "",
        # Whether this account's commits would carry an author: the Claude
        # button ghosts on this, naming the Profile, before bb-tty refuses.
        "git_ready": users.git_ready(who) if users.uid_of(who) else True,
        # The chat panel's headline: who is here, and what has arrived since
        # this account last looked. The messages themselves are fetched when
        # the panel is open. This rides the poll because it is small and it
        # is what decides whether the button wears a dot.
        "chat": _chat_summary(who, ps),
        # This account's color scheme, for a browser that has none stored.
        # index.html's adoptTheme says why localStorage still outranks it.
        "theme": users.prefs(who).get("theme", ""),
        "mode": users.prefs(who).get("mode", ""),
        "motion": users.prefs(who).get("motion", ""),
        # ...and its terminals' look (R133 step 10), which the page applies.
        "term_look": users.prefs(who).get("term") or {},
        # Whether this account has read the getting-started guide, and
        # which image's changelog it acknowledged: the welcome panel opens
        # itself once for each (the guide on a first sign-in, the changelog
        # once per image update), and these are what make it once.
        "welcome": {"seen": bool(users.prefs(who).get("welcome_seen")),
                    "image_seen": str(users.prefs(who).get("image_seen") or "")},
        # ...and the pages it has toured, and whether it skips the tour (R94).
        "tour": {"seen": [str(k) for k in users.prefs(who).get("tour_seen") or []][:64],
                 "off": users.prefs(who).get("tour_off") is True},
    }


# The JSON API's GET routes, in the order they are matched, against the raw
# path: "/api/artifact?" is a different route from "/api/artifacts" because
# the query mark is part of what it matches. A prefix route takes every path
# it prefixes; auth.mjs fails on one an earlier route takes. The doors before
# these (setup, login, the agent, health, the terminal proxy, the page and
# its scripts) stay in _get, in front of the credential check (R60).
GET_ROUTES = (
    ("prefix", "/api/revs", "_get_revs"),
    ("exact", "/api/live", "_get_live"),
    ("exact", "/api/audit", "_get_audit"),
    ("prefix", "/api/trace", "_get_trace"),
    ("prefix", "/api/status", "_get_status"),
    ("exact", "/api/reset", "_get_reset"),
    ("prefix", "/api/findings", "_get_findings"),
    ("prefix", "/api/profile", "_profile"),
    ("prefix", "/api/transcripts", "_get_transcripts"),
    ("prefix", "/api/snapshots", "_get_snapshots"),
    ("prefix", "/api/transcript", "_get_transcript"),
    ("prefix", "/api/git", "_get_git"),
    ("prefix", "/api/project-sessions", "_get_project_sessions"),
    ("prefix", "/api/changelog", "_get_changelog"),
    ("prefix", "/api/version", "_get_version"),
    ("prefix", "/api/tls", "_get_tls"),
    ("prefix", "/api/artifacts", "_get_artifacts"),
    ("prefix", "/api/artifact?", "_get_artifact"),
    ("prefix", "/api/signing-backup?", "_get_signing_backup"),
    ("prefix", "/api/node-busy", "_get_node_busy"),
    ("prefix", "/api/meta", "_get_meta"),
    ("prefix", "/api/welcome", "_get_welcome"),
    ("prefix", "/api/source?", "_get_source"),
    ("prefix", "/logs/download", "_get_logs_download"),
    ("prefix", "/api/phone/wait", "_get_phone_wait"),
    ("prefix", "/api/phone", "_get_phone"),
    ("prefix", "/api/toolchains", "_get_toolchains"),
    ("prefix", "/api/agents", "_get_agents"),
    ("prefix", "/api/emulator", "_get_emulator"),
    ("prefix", "/api/roles", "_get_roles"),
    ("prefix", "/api/users", "_get_users"),
    ("prefix", "/api/nginx", "_get_nginx"),
    ("exact", "/api/scanners", "_get_scanners"),
    ("exact", "/api/router", "_get_router"),
    ("exact", "/api/router-key", "_get_router_key"),
    ("prefix", "/api/storage", "_get_storage"),
    ("exact", "/api/schedules", "_get_schedules"),
    ("prefix", "/api/v1/nodes", "_get_nodes"),
    ("prefix", "/api/v1/jobs", "_get_jobs"),
    ("prefix", "/api/home", "_get_home"),
    ("prefix", "/api/apps", "_get_apps"),
    ("prefix", "/api/notices", "_get_notices"),
    ("prefix", "/api/help", "_get_help"),
    ("prefix", "/api/docker", "_get_docker"),
    ("prefix", "/api/containers", "_get_containers"),
    ("exact", "/api/vms", "_get_vms"),
    ("prefix", "/api/project-job", "_get_project_job"),
    ("prefix", "/api/trash", "_get_trash"),
    ("prefix", "/api/claude-now", "_get_claude_now"),
    ("prefix", "/api/roadmap", "_get_todo"),
    ("prefix", "/api/rules", "_get_rules"),
    ("prefix", "/api/global-rules", "_get_global_rules"),
    ("prefix", "/api/preamble", "_get_preamble"),
    ("prefix", "/api/brief", "_get_brief"),
    ("prefix", "/api/design", "_get_design"),
    ("prefix", "/api/wiki-export", "_get_wiki_export"),
    ("prefix", "/api/wiki", "_get_wiki"),
    ("prefix", "/api/ci-runs", "_get_ci_runs"),
    ("prefix", "/api/ci-watch", "_get_ci_watch"),
    ("prefix", "/api/codebase", "_get_codebase"),
    ("prefix", "/api/pending", "_get_pending"),
    ("prefix", "/api/memory", "_get_memory"),
    ("prefix", "/api/tests", "_get_tests"),
    ("prefix", "/api/bugs", "_get_bugs"),
    ("prefix", "/api/pubkeys", "_get_pubkeys"),
)


# The JSON API's POST routes, in the order they are matched. A prefix route
# takes every path it prefixes, so a longer path sits before a shorter one
# that would take it; auth.mjs fails on one that does not. Each names the
# method that answers, and the method carries its own refusals (R60).
POST_ROUTES = (
    ("prefix", "/api/v1/nodes", "_nodes"),
    ("prefix", "/api/v1/jobs", "_jobs"),
    ("exact", "/api/v1/bb", "_bb_relay"),
    ("exact", "/api/v1/claude-login", "_claude_login"),
    ("exact", "/api/v1/hook", "_hook"),
    ("exact", "/api/v1/tty-grant", "_tty_grant"),
    ("prefix", "/api/lock", "_lock"),
    ("prefix", "/api/archive", "_archive"),
    ("prefix", "/api/repos", "_repos"),
    # NOT /api/pin, which is the command pin and has been since long before
    # this: startswith() means a route added above it silently takes every
    # path it prefixes, and both handlers were called _pin, so the later
    # definition quietly replaced the earlier one in the class body too.
    ("prefix", "/api/project-pin", "_project_pin"),
    ("prefix", "/api/project-group", "_project_group"),
    ("prefix", "/api/apps", "_apps"),
    ("prefix", "/api/pc", "_pc"),
    ("prefix", "/api/project-color", "_project_color"),
    ("prefix", "/api/project-auth", "_project_auth"),
    ("exact", "/api/project-ftp", "_project_ftp"),
    ("prefix", "/api/container", "_container"),
    ("exact", "/api/vms", "_vms"),
    ("prefix", "/api/dockerctl", "_docker_ctl"),
    ("prefix", "/api/rename", "_rename"),
    # These two before the bare prefix, or startswith swallows them.
    ("prefix", "/api/trash-restore", "_trash_restore"),
    ("prefix", "/api/trash-purge", "_trash_purge"),
    ("prefix", "/api/trash", "_trash"),
    ("prefix", "/api/session", "_session"),
    ("prefix", "/api/send", "_send"),
    ("prefix", "/api/say", "_say"),
    ("prefix", "/api/chat", "_chat"),
    ("prefix", "/api/layout", "_layout"),
    ("exact", "/api/bell", "_bell"),
    ("exact", "/api/notices", "_notices"),
    ("exact", "/api/nginx", "_nginx"),
    ("exact", "/api/scanners", "_scanners"),
    ("exact", "/api/router", "_router"),
    ("exact", "/api/images", "_images"),
    ("exact", "/api/storage", "_storage"),
    ("exact", "/api/schedules", "_schedules"),
    ("prefix", "/api/pin", "_pin"),
    ("exact", "/api/reset", "_reset"),
    ("prefix", "/api/create", "_create"),
    ("prefix", "/api/profile", "_profile"),
    ("prefix", "/api/git", "_git_act"),
    ("prefix", "/api/project-sessions", "_project_sessions"),
    ("prefix", "/api/unlink", "_unlink"),
    ("prefix", "/api/link", "_link"),
    ("prefix", "/api/project-job", "_project_job"),
    ("prefix", "/api/roadmap", "_roadmap"),
    ("prefix", "/api/roles", "_roles"),
    ("prefix", "/api/users", "_users"),
    ("prefix", "/api/toolchains", "_toolchains"),
    ("exact", "/api/agents", "_agents"),
    ("exact", "/api/toolpacks", "_toolpacks"),
    ("prefix", "/api/emulator", "_emulator"),
    ("prefix", "/api/logs", "_logs"),
    ("prefix", "/api/idle", "_idle"),
    ("prefix", "/api/paths", "_paths"),
    ("prefix", "/api/snapshots", "_snapshots"),
    ("exact", "/api/transcripts", "_transcripts"),
    ("prefix", "/api/settings", "_settings_post"),
    ("prefix", "/api/rules", "_rules"),
    ("prefix", "/api/global-rules", "_global_rules"),
    ("prefix", "/api/pending", "_pending"),
    ("prefix", "/api/memory", "_memory"),
    ("prefix", "/api/prefs", "_prefs_post"),
    ("prefix", "/api/brief", "_brief"),
    ("prefix", "/api/design", "_design"),
    ("exact", "/api/wiki", "_wiki"),
    ("exact", "/api/ci-watch", "_ci_watch"),
    ("prefix", "/api/devapp", "_devapp"),
    ("prefix", "/api/changelog", "_changelog"),
    ("prefix", "/api/version", "_version"),
    ("prefix", "/api/tls", "_tls"),
    ("exact", "/api/signing", "_signing"),
    ("exact", "/api/keys", "_keys"),
    ("exact", "/api/members", "_members"),
    ("exact", "/api/signing-backup", "_post_signing_backup"),
    ("prefix", "/api/artifacts", "_artifacts"),
    ("prefix", "/api/nodelog", "_nodelog"),
    ("exact", "/api/diag", "_diag"),
    ("exact", "/api/reports", "_reports"),
    ("exact", "/api/v1/files", "_files"),
    ("prefix", "/api/phone", "_phone"),
    ("prefix", "/api/findings", "_findings_log"),
    ("prefix", "/api/tests", "_tests"),
    ("prefix", "/api/presence", "_presence"),
    ("prefix", "/api/bugs", "_bugs"),
    ("prefix", "/api/custom", "_custom"),
    ("prefix", "/api/doctor", "_doctor"),
    ("prefix", "/api/signout", "_signout"),
    ("prefix", "/api/login-code", "_login_code"),
    ("prefix", "/api/signin", "_signin"),
)


class Handler(BaseHTTPRequestHandler):
    server_version = "builderbot-dashboard"

    def log_message(self, fmt, *args):      # quieter than the default
        pass

    def _who(self):
        """The account making this request, or None. Kept for the notebook's
        logs on the way past (writer_name), so an entry can say WHICH person
        wrote it. See _who_raw for how the principal itself is proved."""
        u = self._who_raw()
        # Maintenance mode (kept_out): anybody but the owner is not signed in
        # for now, and _deny says why. Reset per request, as _renewed is.
        self._maint = kept_out(u)
        if self._maint:
            u = None
        _writing.who = u
        # Whose work this request's git is (R159): the person, or the person
        # a session was started for; and their sign-in, seen.
        gitcreds.ACTING.set(users.uid_of(u) if u else "")
        if u and u.get("lid"):
            # Bound to the browser it was made in (R158 step 8): from
            # another, or once ended from Profile, the cookie is nobody's.
            if not logins.seen(users.uid_of(u), u["lid"], self.headers.get("User-Agent", ""), self._client_ip()):
                db.audit(f"user:{u.get('name')}", "sign-in refused", "another browser, or a sign-in ended",
                         {"agent": logins.browser_words(self.headers.get("User-Agent", ""))})
                _writing.who = None
                gitcreds.ACTING.set("")
                return None
        elif u and not u.get("session") and self.headers.get("Authorization", "").startswith("Basic "):
            # The password proved on this request is a sign-in for a while.
            logins.basic(users.uid_of(u))
        return u

    def _client_ip(self):
        """The address this request came from, as the proxy in front says
        where there is one (the tunnel, nginx), else the socket's."""
        fwd = self.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()[:45]
        try:
            return str(self.client_address[0])[:45]
        except (AttributeError, IndexError, TypeError):
            return ""

    def _mint_lid(self, u):
        """A sign-in row for this browser (logins.mint): what the cookie
        names, bound to the browser's User-Agent."""
        return logins.mint(u.get("uid") or "", "", self.headers.get("User-Agent", ""), self._client_ip())

    def _who_raw(self):
        """The account making this request, or None.

        Deliberately NOT remembered on the handler. BaseHTTPRequestHandler
        reuses one instance for the life of a connection, so a principal
        cached on `self` outlives the request that proved it: harmless while
        protocol_version is HTTP/1.0 and every connection carries one request,
        and a cross-request credential leak the day somebody turns keep-alive
        on for the throughput. The cost it would have saved is already saved:
        users.authenticate_pair remembers a verified credential for a minute,
        so repeat calls are a digest and a dict lookup rather than a pbkdf2.

        Basic and the cookie both land here. Basic is what `bb` and the test
        suite send; the cookie is what a browser gets from the login page.
        """
        self._basic_2fa = False
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Bearer "):
            # A session's scoped token: one project, user rights, an expiry.
            # Never a person, so it can do what a user can do on that project
            # and nothing else (bug #16).
            tok = hdr[7:].strip()
            who = users.session_principal(tok)
            # ...widened to the projects its own reads (prefs.reads), read
            # from the settings on every request rather than baked into the
            # token, so a change in the dialog reaches a running session.
            if who:
                who = users.with_reads(who, prefs.reads_trees(who["session"]))
            # Past half its life, the answer to this request carries a fresh
            # one (users.renewal): set here, sent by _json, so a session in
            # use never runs out. Reset per request, because the handler instance
            # outlives one.
            self._renewed = users.renewal(tok) if who else ""
            return who
        if hdr.startswith("Basic "):
            try:
                given = base64.b64decode(hdr[6:]).decode("utf-8", "replace")
            except (ValueError, UnicodeDecodeError):
                return None
            # The whole "user:password" is checked at once, so a correct name
            # with a wrong password is indistinguishable from both being wrong.
            u = users.authenticate_pair(given)
            # A password alone does not open an account with a second factor
            # (R127): bb from a dashboard terminal carries its token instead.
            if u and mfa.enabled(u.get("uid", "")):
                self._basic_2fa = True
                return None
            return u
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "bb_session":
                u = token_user(v.strip())
                if u:
                    return u
        return None

    def _authed(self):
        return self._who() is not None

    def _principal(self):
        """What the audit rows should say this was: the account's name.

        `operator` was a placeholder from before there were accounts, true of
        every mutation because there was only ever one person who could make
        one. Now there can be several, and a log that calls them all the same
        thing is a log that answers no question worth asking.
        """
        u = self._who()
        return f"user:{u['name']}" if u else "anonymous"

    def _readonly(self, name):
        """True, with the 403 already written, when this account may see the
        project but has not taken it on.

        The counterpart to _refused for the handlers whose other check is "is
        this a project you can see". Seeing and working are separate
        questions, so every write that names a project asks this too.
        """
        why = users.may(self._who(), "write", name)
        # ...and a project its owner has locked is nobody else's to change
        # (R119), whoever they are.
        if not why and (bad := projects.locked_out(name, users.uid_of(self._who()))):
            why = bad["error"]
        if not why:
            return False
        self._json({"error": why}, 403)
        return True

    def _not_project(self, name):
        """True, with the 400 already written, when `name` is not a project
        this account sees. The same shape as _refused: a guard that returns
        a bool. Twenty-nine handlers each rebuilt the visible set and wrote
        the same reply before this existed (R60)."""
        if name and name in set(project_names(self._who())):
            return False
        self._json({"error": f"not a project: {name}" if name else "not a project"}, 400)
        return True

    def _not_card(self, name):
        """_not_project, for what is a whole project's (R138: its pin,
        group, color, lock, archive, name and its deletion): a project's key
        this account sees passes too, one with no repository in it as much
        as any."""
        if name and registry.is_repos(name) and users.may_see(self._who(), name):
            return False
        return self._not_project(name)

    def _result(self, r, bad=400):
        """A module's {ok} or {error} answer as the reply: `bad` when it
        carries an error, 200 otherwise."""
        return self._json(r, bad if r.get("error") else 200)

    def _refused(self, action, project=None):
        """True, with the 403 already written, when this account may not.

            if self._refused("rename", name):
                return

        Returns a BOOLEAN, and the name says so. The first version returned
        "the response" and read as `if (no := self._may(...)): return no`,
        which looks exactly like a guard and is not one: _json writes the
        reply and returns None, so the caller got its 403 while the handler
        carried on and did the thing anyway. The NODES suite caught it (a
        refused enrollment that left a node behind) because the assertion on
        the refusal itself passed perfectly. A guard that returns the thing it
        wrote is a guard that can be used wrongly, so it returns a bool.

        The project filter in project_list() does most of the authorizing;
        this is the rest: the verbs a `user` may not use on a project they DO
        have, and the surfaces that are not projects at all. Named actions
        rather than anything derived from the URL, so restricting a verb is a
        decision somebody makes rather than a default they inherit.
        """
        why = users.may(self._who(), action, project)
        if not why:
            return False
        self._json({"error": why}, 403)
        return True

    def _deny(self):
        """Not signed in. A person gets the login page, code gets a plain
        401, never a WWW-Authenticate challenge, which is what summons the
        browser's own dialog. Anything fetching /api/ is the page's JS (or
        curl), and both handle a 401 better than a redirect-to-HTML."""
        # /metrics too: a scraper following a redirect to the login page
        # would parse HTML as an exposition and report the target down.
        api = self.path.split("?")[0].startswith("/api/") or self.path == "/metrics"
        if getattr(self, "_maint", False):
            # Signed in, and kept out while the owner works: told so, and the
            # cookie kept, so the page is back the moment it ends.
            if api:
                return self._json({"error": MAINTENANCE_SAID, "maintenance": True}, 503)
            return self._login_page(MAINTENANCE_SAID, nxt=self.path)
        if api:
            if getattr(self, "_basic_2fa", False):
                self._basic_2fa = False
                return self._json({"error": "this account has two-factor sign-in, so its password alone opens "
                                            "nothing: use bb from a dashboard terminal, which carries its own token"}, 401)
            return self._json({"error": "not signed in"}, 401)
        nxt = urllib.parse.quote(self.path, safe="/?=&")
        self.send_response(302)
        self.send_header("Location", f"/login?next={nxt}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login_page(self, error="", setup=False, name="", nxt="/"):
        """The sign-in card, or the first-run card when nobody owns this box.

        One template: the difference between them is three fields and the
        copy, and two pages would have drifted apart the first time either was
        touched.
        """
        if not error and not setup and settings.get("maintenance_mode"):
            error = MAINTENANCE_SAID
        err = f'<p class="err">{error}</p>' if error else ""
        body = (LOGIN_HTML
                .replace("<!--TITLE-->", "set up" if setup else "sign in")
                .replace("<!--SAID-->", "Make the first account" if setup else "Sign in to continue")
                .replace("<!--ACTION-->", "/setup" if setup else "/login")
                .replace("<!--FIELDS-->", SETUP_FIELDS if setup else LOGIN_FIELDS)
                .replace("<!--ERR-->", err)
                # What was typed comes back with a refusal: a wrong password
                # keeps the username and where it was going (B38).
                .replace("<!--NAME-->", html_escape(name, quote=True))
                .replace("<!--NEXT-->", html_escape(nxt or "/", quote=True))
                .replace("<!--BANNER-->", featuresoff.banner_html())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", csp.header(body))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _setup_post(self):
        """Make the owner, once. Refused the moment there is one.

        Checked against the store rather than a flag: "has anybody claimed
        this box" is a question with an answer already, and a second copy of
        it is one more thing that can disagree.
        """
        if users.all_users():
            return self._login_page("This container already has an account.")
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)
        name = form.get("username", [""])[0]
        pw, pw2 = form.get("password", [""])[0], form.get("password2", [""])[0]
        if pw != pw2:
            return self._login_page("Those two passwords are not the same.",
                                    setup=True)
        # A /config the account cannot write is said on the page with what to
        # do, not answered as a raw error the browser shows as text (B122).
        try:
            r = users.claim(name, pw)
        except OSError as e:
            return self._login_page(
                f"The account could not be saved: {STATE} is not writable here ({e.strerror}). "
                f"On the host, chown the folder mounted at {STATE} to the PUID and PGID the "
                "container runs as, and restart it.", setup=True)
        if r.get("error"):
            return self._login_page(r["error"], setup=True)
        print(f"dashboard: {name} claimed this container as the owner",
              flush=True)
        # Then the rest of the setup page, which ends with a node (R199).
        settings.set_many({"setup_done": False})
        # Straight in, rather than back to a sign-in they just proved: they
        # typed the password twice thirty seconds ago.
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie",
                         f"bb_session={make_token(users.get(name), self._mint_lid(users.get(name)))}; Path=/; "
                         f"Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Strict"
                         + ("; Secure" if tls.over_tls(self.connection) else ""))
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _login_post(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)
        u = users.authenticate(form.get("username", [""])[0],
                               form.get("password", [""])[0])
        if not u:
            # A beat of delay, so guessing costs something; the message does
            # not say which half was wrong for the same reason the store
            # checks name and password together.
            time.sleep(0.5)
            return self._login_page("Wrong username or password.",
                                    name=form.get("username", [""])[0][:200],
                                    nxt=form.get("next", ["/"])[0][:2000])
        if kept_out(u):
            return self._login_page(MAINTENANCE_SAID, name=form.get("username", [""])[0][:200],
                                    nxt=form.get("next", ["/"])[0][:2000])
        nxt = form.get("next", ["/"])[0]
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        # A second factor where the account has one (R127), unless this
        # browser was remembered for it; the password alone opens nothing.
        if mfa.enabled(u["uid"]) and not self._trusted_browser(u):
            return self._mfa_page(u, nxt)
        self._signed_in(u, nxt)

    def _cookie(self, name):
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v.strip()
        return ""

    def _trusted_browser(self, u):
        """Whether this browser was remembered for this account's second
        factor (R127): its cookie verifies and its id is still on the list."""
        who, tid = purpose_user(self._cookie("bb_trust"), "trust")
        return bool(who and who["name"] == u["name"] and tid and mfa.trusted(u["uid"], tid))

    def _signed_in(self, u, nxt, remember=False, json_answer=False):
        """The session cookie, and with `remember` the browser's own for its
        second factor; then on to `nxt`, or a JSON answer for the passkey's
        fetch."""
        users.touch(u["name"])
        sec = "; Secure" if tls.over_tls(self.connection) else ""
        cookies = [f"bb_session={make_token(u, self._mint_lid(u))}; Path=/; Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Strict{sec}",
                   "bb_mfa=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"]
        if remember:
            ua = re.sub(r"[^\w ./();,:-]", "", self.headers.get("User-Agent", ""))[:80]
            tid, _ = mfa.trust_add(u["uid"], ua or "a browser")
            cookies.append(f"bb_trust={purpose_token(u, 'trust', mfa.TRUST_DAYS * 86400, tid)}; Path=/; "
                           f"Max-Age={mfa.TRUST_DAYS * 86400}; HttpOnly; SameSite=Strict{sec}")
        body = json.dumps({"ok": True, "next": nxt}).encode() if json_answer else b""
        self.send_response(200 if json_answer else 303)
        if not json_answer:
            self.send_header("Location", nxt)
        for c in cookies:
            self.send_header("Set-Cookie", c)
        if json_answer:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _mfa_page(self, u, nxt, error="", status=200):
        """The second step of signing in (R127), with the cookie that says
        whose it is for ten minutes."""
        body = (LOGIN_HTML
                .replace("<!--TITLE-->", "sign in")
                .replace("<!--SAID-->", "Your second factor")
                .replace("<!--ACTION-->", "/login/2fa")
                .replace("<!--FIELDS-->", MFA_FIELDS)
                .replace("<!--ERR-->", f'<p class="err">{html_escape(error)}</p>' if error else "")
                .replace("<!--NAME-->", html_escape(u["name"], quote=True))
                .replace("<!--NEXT-->", html_escape(nxt or "/", quote=True))
                .replace("<!--PASSKEYS-->", "1" if mfa.passkey_ids(u["uid"]) else "")
                .replace("<!--BANNER-->", featuresoff.banner_html())).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Set-Cookie", f"bb_mfa={purpose_token(u, 'mfa', 600)}; Path=/; Max-Age=600; HttpOnly; SameSite=Strict")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _two_factor_gate(self, path):
        """True, with the answer written, when a role of this account
        requires a second factor it has not set up (R127): it reaches the
        setup page, its Profile's read and actions, and nothing else."""
        who = self._who() or {}
        uid = users.uid_of(who)
        if who.get("session") or not uid or mfa.enabled(uid):
            return False
        if not roles.two_factor_required(users.get(who["name"]) or {}):
            return False
        if path in ("/login/setup", "/api/profile", "/api/meta", "/logout", "/favicon.ico", "/favicon.svg"):
            return False
        if path.startswith("/api/"):
            self._json({"error": "a role of yours requires two-factor sign-in: set it up first",
                        "two_factor_setup": True}, 403)
            return True
        self.send_response(303)
        self.send_header("Location", "/login/setup")
        self.send_header("Content-Length", "0")
        self.end_headers()
        return True

    def _setup_2fa_page(self):
        """GET /login/setup: an account whose role requires a second factor
        sets one up here before anything else (R127). The page's script
        speaks to /api/profile's two-factor actions, as Profile does."""
        who = self._who() or {}
        body = (LOGIN_HTML
                .replace("<!--TITLE-->", "two-factor sign-in")
                .replace("<!--SAID-->", "Set up two-factor sign-in")
                .replace("<!--ACTION-->", "/login/setup")
                .replace("<!--FIELDS-->", SETUP_2FA_FIELDS)
                .replace("<!--ERR-->", "")
                .replace("<!--NAME-->", html_escape(who.get("name", ""), quote=True))
                .replace("<!--NEXT-->", "/")
                .replace("<!--BANNER-->", featuresoff.banner_html())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", csp.header(body))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _mfa_keys(self, u):
        """What wrong codes are counted against: the account and the address."""
        return (f"acct:{u['uid']}", f"addr:{self.client_address[0]}")

    def _mfa_post(self):
        """POST /login/2fa: a code or a recovery code for the account the
        bb_mfa cookie names (R127)."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        except (ValueError, TypeError):
            return self._json({"error": "bad request"}, 400)
        u, _ = purpose_user(self._cookie("bb_mfa"), "mfa")
        nxt = form.get("next", ["/"])[0]
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        if not u:
            return self._login_page("That sign-in ran out: sign in again.", nxt=nxt)
        if (left := mfa.held(*self._mfa_keys(u))):
            return self._mfa_page(u, nxt, f"Too many wrong codes: try again in {max(1, left // 60)} minutes.", 429)
        code = form.get("code", [""])[0].strip()
        how = ("authenticator" if code and mfa.totp_check(u["uid"], code)
               else "recovery code" if code and mfa.recovery_use(u["uid"], code) else "")
        if not how:
            wait = mfa.missed(*self._mfa_keys(u))
            db.audit(f"user:{u['name']}", "2fa-wrong", u["name"], {"addr": self.client_address[0]})
            time.sleep(0.5 + wait)
            return self._mfa_page(u, nxt, "That code is not right: the one your app shows now, or an unused recovery code.")
        mfa.cleared(f"acct:{u['uid']}")
        db.audit(f"user:{u['name']}", "2fa-signin", u["name"], {"how": how})
        self._signed_in(u, nxt, remember=form.get("remember", [""])[0] == "1")

    def _mfa_passkey(self):
        """POST /login/passkey: the passkey's challenge, then its answer, for
        the account the bb_mfa cookie names (R127)."""
        req = self._read_json()
        if req is None:
            return None
        u, _ = purpose_user(self._cookie("bb_mfa"), "mfa")
        if not u:
            return self._json({"error": "that sign-in ran out: sign in again"}, 401)
        if (left := mfa.held(*self._mfa_keys(u))):
            return self._json({"error": f"too many wrong tries: try again in {max(1, left // 60)} minutes"}, 429)
        if req.get("action") == "challenge":
            return self._json({"challenge": mfa.challenge(u["uid"], "get"), "ids": mfa.passkey_ids(u["uid"])})
        nxt = str(req.get("next") or "/")
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        if not mfa.passkey_check(u["uid"], self._origin(), str(req.get("id") or ""), req.get("client"),
                                 req.get("auth"), req.get("sig")):
            mfa.missed(*self._mfa_keys(u))
            db.audit(f"user:{u['name']}", "2fa-wrong", u["name"], {"addr": self.client_address[0], "how": "passkey"})
            return self._json({"error": "that passkey did not prove this account"}, 403)
        mfa.cleared(f"acct:{u['uid']}")
        db.audit(f"user:{u['name']}", "2fa-signin", u["name"], {"how": "passkey"})
        self._signed_in(u, nxt, remember=req.get("remember") is True, json_answer=True)

    def _origin(self):
        """The page's origin as its browser said it, for a passkey: Origin
        when it names this Host, else the Host the request came to."""
        host = self.headers.get("Host", "")
        o = self.headers.get("Origin", "")
        if o and urllib.parse.urlsplit(o).netloc == host:
            return o
        proto = self.headers.get("X-Forwarded-Proto", "") or (
            "https" if type(self.connection).__name__ == "SSLSocket" else "http")
        return f"{proto}://{host}"

    def _ws_cross_origin(self):
        """Why a websocket asked for from a page of another origin is
        refused, or "". A browser sends the sign-in cookie with a
        websocket from any page of the same site (another of its
        hostnames, an app this install routes), so a terminal's socket is
        opened only by a page of this origin. A client that sends no
        Origin (a tool with a token) is not a page."""
        o = self.headers.get("Origin", "")
        if not o:
            return ""
        hosts = {self.headers.get("Host", ""), self.headers.get("X-Forwarded-Host", "")} - {""}
        if urllib.parse.urlsplit(o).netloc in hosts:
            return ""
        return f"a terminal opens from this dashboard's own page, not from {o}"

    def _logout(self):
        # The browser's sign-in is over (R159): its row goes, so its
        # person's tokens are used no more unless they are signed in
        # elsewhere.
        for part in self.headers.get("Cookie", "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "bb_session":
                u = token_user(v.strip())
                if u and u.get("lid"):
                    logins.drop(users.uid_of(u), u["lid"])
        self.send_response(302)
        self.send_header("Location", "/login")
        self.send_header("Set-Cookie",
                         "bb_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _node_scope(self):
        """Node ids this account may look at, or None for "no restriction".

        An account that may change a node is shown the registry, which is what
        the Nodes page is. One that may not is shown only the machines its own
        projects build on, so every node-shaped surface is a window on its own
        work rather than an inventory of the box.

        Used by the listing AND by the two endpoints that read a node's
        contents. Scoping the picker alone would have been theatre: `?node=`
        is a string in a URL, and the answer is what actually carries the
        other projects' names (roadmap #27).
        """
        me = self._who()
        # Read on every node is the registry too (R260), and Read on named
        # nodes those besides its projects'; an administrator's or a
        # session's answer is as it was.
        lim = None if users.is_admin(me or {}) or (me or {}).get("session") \
            else roles.nodes_for(me or {}, "nodes")
        if lim is None and (not users.may(me, "node") or roles.level_of(me or {}, "nodes")):
            return None
        want = set(lim or ())
        for name in project_names(me):
            pr = prefs.get(name)
            want.update([pr["node"], *(pr.get("nodes") or [])])
        want.discard("")
        return want

    def _node_asked(self, nid):
        """Resolve and check a `?node=` for this account.

        Returns (node_id, error). An account with no restriction gets what it
        asked for, "" included, which is "the default node" and predates the
        picker. A restricted one must land on a node one of its own projects
        builds on, and when it named none, the first of those, because its
        picker only ever offered those anyway.
        """
        scope = self._node_scope()
        if scope is None:
            return nid, None
        if not scope:
            return "", "none of your projects builds on a node"
        if not nid:
            return sorted(scope)[0], None
        if nid not in scope:
            return "", "not a node one of your projects builds on"
        return nid, None

    def _nodes_for(self, rows):
        scope = self._node_scope()
        rows = rows if scope is None else [n for n in rows if n["id"] in scope]
        # Which of each node's runners has a token stored: asked of the
        # helper once, which names slots and never a token.
        tokens = runners.tokens() if any(n.get("kind") == "agent" for n in rows) else {}
        me = self._who() or {}
        for n in rows:
            if n.get("kind") == "agent":
                n["runner_tokens"] = sorted(tokens.get(n["id"], set()))
            # What this account may do to it (R260), so the page leaves a
            # node it may only read without its controls.
            n["may"] = "read" if users.may_instance(me, "nodes-write", n["id"]) else "write"
            n["areas_may"] = {a: "write" if users.is_admin(me) or me.get("session")
                              else roles.level_of(me, a, node=n["id"]) for a in sorted(roles.NODE_AREAS)}
            # ...and to each of its runners, and whether it may add one: ""
            # for a runner it may not read, which the page leaves out.
            if n.get("kind") == "agent":
                slots = set(nodes.runners_of(n)) | {r.get("slot") for r in nodes.runners_reported(n) if r.get("slot")}
                n["runner_may"] = {sl: _runner_level(me, f"{n['id']}/{sl}") for sl in sorted(slots)}
                n["runner_new"] = users.may_instance(me, "runner", "") == ""
        # Whether THIS account's Claude login has been given to each node,
        # answered here rather than by handing the page a uid to compare
        # against: the grant list is every account that has one, which is
        # nobody else's business to read off a row.
        return rows

    def _area_read_why(self, area, project=None, me=None):
        """Why this person may not READ `area` (R152 step 3: an area without
        Read is not shown, and its views are refused), or "". A session sees
        its own project's through its own routes, and the account behind it
        is held by users.may; an administrator reads everything."""
        me = me if me is not None else (self._who() or {})
        if me.get("session") or users.is_admin(me):
            return ""
        if roles.level_of(me, area, project, users.may_work):
            return ""
        label = next((a[1] for a in roles.AREAS if a[0] == area), area)
        return (f"your roles give no {label} Read" + (f" on {project}" if project else "")
                + ": an administrator gives a role that holds it")

    def _term_refused(self, rest, me=None):
        """A sentence when this account may not have the terminal it is asking
        for, and "" when it may.

        Two rules, and they apply to different people.

        A Claude session is a write, the most write-shaped thing on the page,
        so it needs a project the account has actually taken on, whoever
        they are. An administrator is shown every project and works on the
        ones on their own list (users.may_work), so this is where that bites
        for them.

        And an account with no `terminal` right gets nothing else at all: not
        a shell, not somebody else's Claude, and not a project it cannot see.
        A read-only terminal pointed at another session is a way to WATCH one,
        which is the hole this closes rather than opens.

        `me` is the account to ask about when it is not the request's own:
        a node's bb-tty asking for the account a session token was minted
        for (_tty_grant).
        """
        me = me or self._who()
        arg = _term_arg(rest)
        if arg.startswith("ctr:"):
            return self._ctr_refused(arg, me)
        if arg.startswith("log:ctr:"):
            return self._ctr_log_refused(arg, me)
        if arg.startswith("vm:"):
            return self._vm_con_refused(arg, me)
        if agents.of_arg(arg)[0]:
            project = agents.project_of_arg(arg)
            # An agent the project's settings switched off starts nothing
            # there (R95), whoever asks.
            ag = agents.of_arg(arg)[0]
            if ag.id in ((prefs.get(project) or {}).get("agents_off") or []):
                return f"{project}'s settings do not allow {ag.name} sessions: its Agents may section says which agents may run"
            # A project of several repositories has one session, on its
            # first repository, working in all of them (R136): a second on
            # another would share its worktrees.
            key = repos.project_of(project)
            first = (repos.members(key) or [""])[0] if key else ""
            if first and project != first:
                return (f"{registry.label(project)} is a repository of {registry.label(key)}, whose sessions "
                        f"start on {registry.label(first)} and work in every repository of it")
            # Terminal Read is the shielded Claude console; without it there
            # is no terminal on the project at all (R152 (e)).
            return users.may(me, "claude", project) or self._area_read_why("terminal", project, me)
        return users.may(me, "terminal")

    def _vm_con_refused(self, arg, me):
        """A sentence when this account may not open the console of the VM a
        vm: argument names, "" when it may (R91): a person with a shell and
        VMs Write on its project, or an administrator; an administrator alone
        when the project's Make VMs is deny; the VM running now."""
        m = _ARG_VM.match(arg)
        if not m:
            return "not a VM's console: vm:PROJECT:NAME"
        project, name = m.groups()
        no_shell = users.may(me, "terminal")
        if no_shell:
            return no_shell
        if not users.is_admin(me):
            why = users.may(me, "vms-write", project)
            if why:
                return why
            if (prefs.get(project) or {}).get("makevms") == "deny":
                return f"{project}'s Make VMs is deny, so its VMs' consoles are an administrator's"
        t = vm_target(project, name)
        return t["why"] if t["where"] == "refused" else ""

    def _ctr_refused(self, arg, me):
        """A sentence when this account may not open a shell in the container
        a ctr: argument names, and "" when it may (R218 step 4, the operator,
        14 Oct): a person with a shell who may run that container, which is
        its project's account or an administrator, as for Start and Stop on
        the Containers page; an administrator alone when the project's Agents may:
        Run its container is Deny; and the container one of the instance's
        running ones, asked of its daemon now, never taken from the URL."""
        m = _ARG_CTR.match(arg)
        if not m:
            return "not a container's terminal: ctr:NAME:INSTANCE:CONTAINER"
        name, inst, ctr = m.groups()
        no_shell = users.may(me, "terminal")
        if no_shell:
            return no_shell
        if inst not in (devapp.instances(name) or []):
            return f"no instance {inst} of {name} on record here"
        owner = _ctr_owner(name, inst)
        admin = users.is_admin(me)
        if not admin:
            if not owner:
                return f"{name} belongs to no project, so its shell is an administrator's"
            why = users.may(me, "write", owner)
            if why:
                return why
            if (prefs.get(owner) or {}).get("devbuild") == "deny":
                return (f"{owner}'s Agents may: Run its container is Deny, so a shell in its containers "
                        "is an administrator's")
        t = ctr_target(name, inst)
        if t["where"] == "refused":
            return t["why"]
        if ctr not in devactions.running_names(name, inst):
            return f"{ctr} is not a running container of {devapp.pname(name, inst)} now"
        return ""

    def _ctr_log_refused(self, arg, me):
        """A sentence when this account may not follow the log of the
        container a log:ctr: argument names, and "" when it may: as the
        Containers page's Log reads it (docker-write, and the container's
        project on the account's list), the container one of the instance's
        running ones now."""
        m = _ARG_LOGCTR.match(arg)
        if not m:
            return "not a container's log: log:ctr:NAME:INSTANCE:CONTAINER"
        name, inst, ctr = m.groups()
        why = users.may(me, "docker-write")
        if why:
            return why
        if inst not in (devapp.instances(name) or []):
            return f"no instance {inst} of {name} on record here"
        why = self._not_on_list(me, _ctr_owner(name, inst))
        if why:
            return why
        t = ctr_target(name, inst)
        if t["where"] == "refused":
            return t["why"]
        if ctr not in devactions.running_names(name, inst):
            return f"{ctr} is not a running container of {devapp.pname(name, inst)} now"
        return ""

    def _claude_held(self, rest, me=None):
        """A sentence when this account may not open the Claude session it is
        asking for, and "" when it may.

        More than one conversation per project is allowed now (roadmap #24),
        and each works in a tree of its own, so they cannot overwrite each
        other. What is refused instead is a SECOND SESSION ON ONE ANTHROPIC
        ACCOUNT. Two dashboard accounts signed in to the same Anthropic login
        would share its limits and make whose-work-is-whose unanswerable, and
        the check is a real one rather than a guess: the node that signed each
        account in reported which Anthropic account it was, and that record is
        what this compares.

        Enforced HERE and not only in the page, for the reason bb-tty's own
        header gives about the lock file: a rule only the UI honors is a
        suggestion, because a terminal's URL can be asked for directly.
        """
        arg = _term_arg(rest)
        me = me or self._who()
        uid = users.uid_of(me)
        # A held start (R56 step 9): no agent session runs until Start is
        # pressed on This machine; a shell is a person's and still opens.
        if held.is_held() and agents.of_arg(arg)[0]:
            return held.said()
        # No author, no terminal: every project is a repository, a commit
        # with no name and email behind it is one git refuses halfway through
        # the work, and a shell is where git is typed. bb-tty asks the same
        # question on the node, from the same answer (bb settings --json's
        # git_ready). Asked WITH the project this terminal is for, so an
        # author set for one repository alone opens a session there.
        # claude:<project>[:r:<id>] and sh:<n>:<project> put it in different
        # places, so the shape decides rather than a fixed index.
        bits = arg.split(":")
        is_agent = agents.of_arg(arg)[0] is not None
        want = (bits[1] if is_agent and len(bits) > 1
                else bits[2] if arg.startswith("sh:") and len(bits) > 2 else "")
        if uid and (arg == "shell" or arg.startswith("sh:") or is_agent) \
                and not users.git_ready(me, want):
            return (f"{me['name']} has no name and email for commits yet: set them on your "
                    "Profile (the gear in the header), or for one project in its settings "
                    "dialog, and open this again")
        if not is_agent:
            return ""
        project = agents.project_of_arg(arg)
        # A project whose map is still building (mapping.py): its first
        # session waits the few seconds, so its first question about the
        # tree is answered from an index rather than by building one. The
        # button carries the same sentence, and this is the check behind it.
        if mapping.held(project):
            return mapping.held(project)
        if not uid or not project:
            return ""                     # not an account: nothing to scope
        why = slot_held(project, uid, arg)
        if why:
            return why
        t = session_target(project, claude=True, node=_arg_node(arg), uid=uid)
        if t["where"] != "node":
            return ""
        # The agent on that node first (claudecode.py, agentcode.py): an
        # update running there holds the start.
        ag = agents.of_arg(arg)[0]
        if ag and ag.id != "claude":
            return agentcode.start_hold(project, t["id"], ag.id) or ""
        return claudecode.start_hold(project, t["id"]) or ""

    def _scoped_arg(self, rest, node=False):
        """Stamp the terminal's argument with the account that asked for it.

        bb-tty runs with the words `?arg=` carries, so this is where a
        terminal learns whose it is: the account is taken from the credential
        this request already proved and any `u:` the BROWSER sent is thrown
        away first. Trusting the browser's would make the whole thing a
        suggestion: one edited URL and you are in somebody else's home with
        their Claude login (roadmap #26).

        A request with no account behind it is left alone rather than
        refused. bb-tty reads that as the box's own home and the unprefixed
        session names, which is what every terminal got before accounts.
        """
        head, sep, query = rest.partition("?")
        if not sep or "arg=" not in query:
            return rest
        me = self._who()
        uid = users.uid_of(me)
        out = []
        for kv in query.split("&"):
            k, eq, v = kv.partition("=")
            if k == "arg" and eq:
                want = _ARG_NODE.sub("", _ARG_OWNER.sub("", urllib.parse.unquote_plus(v)))
                v = urllib.parse.quote(f"u:{uid}:{want}" if uid else want,
                                       safe="")
                out.append(f"{k}{eq}{v}")
                # Going to a NODE (roadmap #24), two more: the account's
                # name, since the node has no users.json to look one up in,
                # and a session token for the project, since only this
                # container's key can mint one. Each ?arg= is one more of
                # bb-tty's arguments, and bb-tty takes them only
                # in the shapes it expects. The token is the same scoped
                # one the launcher would have minted here (one project,
                # user rights, an expiry), never the account's credential.
                project = _arg_project(want)
                if node and uid and project:
                    out.append("arg=" + urllib.parse.quote(
                        f"tok:{users.mint_session(project, uid=uid)}", safe=""))
                    out.append("arg=" + urllib.parse.quote(
                        f"name:{me.get('name', '')}", safe=""))
                    # The owner keeps the project directory on the node as
                    # here (session_dir in lib/common.sh says why), and the
                    # node has no store to know who that is.
                    if me.get("role") == "owner":
                        out.append("arg=owner%3A1")
                continue
            out.append(f"{k}{eq}{v}")
        return head + "?" + "&".join(out)

    VENDOR = {"xterm.js": "text/javascript; charset=utf-8", "addon-fit.js": "text/javascript; charset=utf-8",
              "xterm.css": "text/css; charset=utf-8"}

    def _vendor(self, name):
        """The page's vendored libraries (R133), by name from a fixed list,
        never a general file server."""
        if name not in self.VENDOR:
            return self._json({"error": "not found"}, 404)
        return self._static("vendor/" + name, self.VENDOR[name])

    def _novnc(self, rest):
        """noVNC's files (the page and the RFB client it imports), as the
        image fetched them; nothing outside its directory."""
        root = Path(os.environ.get("BB_NOVNC_DIR", "/opt/builderbot/novnc")).resolve()
        target = (root / urllib.parse.unquote(rest)).resolve()
        if root not in target.parents or not target.is_file():
            return self._json({"error": "not part of noVNC" if root.is_dir() else
                               "noVNC is not in this image, so a VM's screen cannot open here"}, 404)
        ctype = {".js": "text/javascript", ".html": "text/html", ".css": "text/css", ".svg": "image/svg+xml",
                 ".png": "image/png", ".ico": "image/x-icon"}.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(body)
        return None

    def _screen_proxy(self):
        """/screen/ws?vm=PROJECT/NAME (R99): the browser's noVNC relayed to
        the VM's node, whose agent opens the VM's VNC on its loopback. Seeing
        a screen is driving the machine, so it takes VMs Write on the VM's
        project; the request upstream carries this controller's signature for
        that VM and this minute, keyed with the node's token hash."""
        if (cross := self._ws_cross_origin()):
            return self._json({"error": cross}, 403)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        project, _, name = str((q.get("vm") or [""])[0]).partition("/")
        if not registry.is_project(project):
            return self._json({"error": f"no project called {project}"}, 404)
        if self._refused("vms-write", project):
            return None
        rec = next((v for v in vms.view([project]) if v.get("name") == name), None)
        if not rec:
            return self._json({"error": f"{project} has no VM called {name}"}, 404)
        host, key = nodes.route_host(rec["node"]), nodes.screen_key(rec["node"])
        if not host or not key:
            return self._json({"error": f"{rec.get('node_name')} cannot be reached for a screen"}, 503)
        t = int(time.time())
        sig = hmac.new(key.encode(), f"{rec['domain']}.{t}".encode(), hashlib.sha256).hexdigest()
        try:
            up = socket.create_connection((host, SCREEN_PORT), timeout=5)
        except OSError:
            return self._json({"error": f"{rec.get('node_name')} did not answer on {host}:{SCREEN_PORT}: "
                                        "its agent opens that port to this controller once it is updated"}, 502)
        up.settimeout(None)
        lines = [f"GET /ws?vm={rec['domain']}&t={t}&s={sig} HTTP/1.1", f"Host: {host}:{SCREEN_PORT}"]
        for k, v in self.headers.items():
            if k.lower() in ("upgrade", "connection", "sec-websocket-key", "sec-websocket-version",
                             "sec-websocket-protocol"):
                lines.append(f"{k}: {v}")
        self.close_connection = True
        down = self.connection
        # On its row while it lasts: who else has the Screen (the operator, 21 Oct).
        here = vms.present(f"{project}/{name}", "screen", (self._who() or {}).get("name") or self._principal(),
                           users.uid_of(self._who() or {}) or "")
        try:
            up.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
            self.wfile.flush()
            sel = selectors.DefaultSelector()
            sel.register(up, selectors.EVENT_READ, down)
            sel.register(down, selectors.EVENT_READ, up)
            while True:
                for k, _ in sel.select():
                    data = k.fileobj.recv(65536)
                    if not data:
                        return None
                    k.data.sendall(data)
        except OSError:
            return None
        finally:
            vms.gone(here)
            up.close()

    def _term_decide(self, rest0):
        """Whether this terminal may open and where it runs (R133):
        (target, vm match, None), or (None, None,
        (why, status)). `rest0` is the path after the prefix, ?arg= and all."""
        refused = self._term_refused(rest0)
        if refused:
            return None, None, (refused, 403)
        held = self._claude_held(rest0)
        if held:
            # 409, not 403: nothing is wrong with the credential, the thing
            # asked for is taken. The name is the whole value of the record:
            # "somebody else has it" tells you nothing you can act on.
            return None, None, (held, 409)
        # Where this terminal lives (roadmap #24, phase 10b): a project bound
        # to a node whose session half is up opens on THAT machine (the
        # same bb-tty, with the account and its token stamped into its
        # words), and everything else opens here. session_target says why a node cannot take one, and the
        # row's button carries the same sentence.
        # A SHELL is this container's own and always has been: a tree to look
        # at, the linters, git. Only a CLAUDE session needs a node, because
        # only Claude is the thing this container does not carry, so the
        # question is asked about a claude: argument and about nothing else.
        arg0 = _term_arg(rest0)
        # ...and a container's shell is where its container is (R218 step 4).
        ctr = _ARG_CTR.match(arg0)
        vmm = _ARG_VM.match(arg0)
        target = ctr_target(ctr.group(1), ctr.group(2)) if ctr else vm_target(*vmm.groups()) if vmm else \
            session_target(_arg_project(arg0),
                           claude=agents.of_arg(arg0)[0] is not None,
                           node=_arg_node(arg0),
                           uid=users.uid_of(self._who() or {}) or "")
        if target["where"] == "refused":
            return None, None, (target["why"], 503)
        # A VM's Console is one person's at a time (the operator, 21 Oct):
        # anybody else is refused while it is held, unless the project's
        # owner or an administrator took it over a moment ago.
        if vmm:
            vkey, my_uid = f"{vmm.group(1)}/{vmm.group(2)}", users.uid_of(self._who() or {}) or ""
            held = vms.holders(vkey, "console", but=my_uid)
            if held and not vms.may_take(my_uid, vkey):
                return None, None, (f"{', '.join(w for _, w in held)} has {vmm.group(2)}'s Console open, and it is "
                                    "one person's at a time. Its Screen can be shared, or ask them; the "
                                    "project's owner or an administrator can take it over.", 409)
        # A terminal on the controller itself, switched off for this install
        # (R81): what a node runs is the node's, and stays.
        if target["where"] != "node" and (why := featuresoff.sentences().get("shell")):
            return None, None, (why, 403)
        return target, vmm, None

    def _term_own(self):
        """/termws?arg=...&cols=&rows= (R133): BuilderBot's own terminal, a
        websocket the page, the Android app and the VS Code extension open
        directly. Decided by _term_decide and _scoped_arg; a refusal is the
        socket closing with why. On this controller bb-tty runs in a pty
        here; on a node the socket is carried to its screen relay's /term,
        signed. Every few seconds the decision is asked again, and a
        terminal no longer allowed is ended (step 9)."""
        query = urllib.parse.urlsplit(self.path).query
        q = urllib.parse.parse_qs(query)
        args = "?" + "&".join(f"arg={urllib.parse.quote(a, safe='')}" for a in q.get("arg", []))
        dims = {k: termws.term()._dim((q.get(k) or [""])[0], d) for k, d in (("cols", 80), ("rows", 24))}
        if (cross := self._ws_cross_origin()):
            return self._json({"error": cross}, 403)
        # A log, read-only and followed (R133 step 12): no program runs.
        if _term_arg(args).startswith("log:"):
            return self._log_own(_term_arg(args), args, dims)
        target, vmm, no = self._term_decide(args)
        if not termws.upgrade(self):
            return self._json({"error": no[0] if no else "a websocket is asked for here"}, no[1] if no else 400)
        down = self.connection
        if no:
            return termws.close(down, no[0])
        if target["where"] == "node" and not target.get("term"):
            return termws.close(down, f"{target['name']}'s agent is from before BuilderBot's own terminal: "
                                      "update it on its Nodes row, and this opens")
        node = target["where"] == "node"
        words = [v for k, v in urllib.parse.parse_qsl(urllib.parse.urlsplit(
            self._scoped_arg(args, node=node)).query) if k == "arg"]
        who_raw = self._who_raw()

        def alive():
            if kept_out(who_raw):
                return "the controller is in maintenance mode"
            return (self._term_decide(args)[2] or ("",))[0]
        here = None
        if vmm:
            here = vms.present(f"{vmm.group(1)}/{vmm.group(2)}", "console",
                               (self._who() or {}).get("name") or self._principal(),
                               users.uid_of(self._who() or {}) or "")
        try:
            if node:
                ro = bool(users.may(self._who(), "terminal")) and not (_ARG_CTR.match(_term_arg(args)) or vmm)
                kind = "ctr" if (_ARG_CTR.match(_term_arg(args)) or vmm) else "ro" if ro else "rw"
                # A person's own terminal carries what opens their sealed
                # sign-ins there (R126), wrapped to the agent; a container's
                # or a VM's never does, nor anybody else's.
                tk = None
                if kind != "ctr" and nodes.token_seal_on(target["id"]):
                    tk = tokenkeys.wrapped_for(target["id"], users.uid_of(self._who() or {}),
                                               ((nodes.node(target["id"]) or {}).get("reported") or {}).get("tokseal"))
                return termws.node(down, host=target["host"], port=target["screen"], key=nodes.screen_key(target["id"]),
                                   kind=kind, words=words, alive=alive, extra={"tk": tk} if tk else None, **dims)
            env = {k: v for k, v in os.environ.items() if k != "DASHBOARD_AUTH"}
            return termws.local(down, words, bbtty=str(HERE / "bb-tty"), env=env,
                                cwd=env.get("HOME") or "/", ro=bool(users.may(self._who(), "terminal")),
                                alive=alive, **dims)
        finally:
            if here is not None:
                vms.gone(here)

    def _log_reader(self, arg):
        """(read, None) for a log this account may read, as a log tab
        follows it (termws.follow), or (None, why). Decided as the read it
        stands in for is: a job's as the Jobs page reads it, the
        controller's as Settings' Logs downloads it."""
        kind, _, rest = arg[len("log:"):].partition(":")
        if kind == "job":
            jid = rest
            if not re.fullmatch(r"j_[0-9a-f]{6,16}", jid):
                return None, "no such job"

            def read():
                mine, system = self._jobs_scope()
                body, status = nodes.jobs_view(jid, {}, mine, system, self._jobs_hidden())
                if status != 200 or not body.get("id"):
                    raise ValueError(body.get("error") or "no such job")
                log = body.get("log") or ""
                st = body.get("state") or ""
                done = st in ("succeeded", "failed", "canceled")
                return (log if isinstance(log, str) else "\n".join(log)), (f"the job {st}" if done else "")
            try:
                read()
            except ValueError as e:
                return None, str(e)
            return read, None
        if kind == "controller":
            if users.may(self._who(), "controller-read"):
                return None, "reading the controller's log is an administrator's"
            path = logs.log_dir() / "builderbot.log"

            def read():
                try:
                    data = path.read_bytes()[-512 * 1024:]
                except OSError:
                    data = b""
                return data.decode("utf-8", "replace"), ""
            return read, None
        if kind == "node":
            # A machine's own log (R133 step 12), as a person with the debug
            # grant reads it from the node's row: the stream's last lines,
            # read again every ten seconds (each read is a job on the node,
            # so not every second), the screen drawn afresh when they move.
            nid, _, stream = rest.partition(":")
            who = self._who() or {}
            if who.get("session") or users.may(who, "debug"):
                return None, "a machine's logs are an account's with the debug grant"
            if not nodes.node(nid) or stream not in nodes.LOG_STREAMS:
                return None, "no such node or log"
            held = {"at": 0.0, "text": ""}

            def read():
                if time.time() - held["at"] >= 10:
                    held["at"] = time.time()
                    r = nodes.log_read_named(self._principal(), "", nid, stream, 400, bool(settings.get("debug_mode")))
                    if r.get("error"):
                        raise ValueError(r["error"])
                    held["text"] = str(r.get("out") or "")
                return held["text"], ""
            return read, None
        if kind == "ci":
            # A CI run's jobs and their logs (R133 step 12), as /api/ci-runs
            # reads one for an account that sees the project: fetched from
            # the git host once, since a finished run's log does not move,
            # and the project's visibility asked again as the tab is kept.
            name, _, run = rest.rpartition(":")
            if not name or not run.isdigit():
                return None, "a CI run's log is named by its project and its run"
            if name not in set(project_names(self._who())):
                return None, f"not a project: {name}"
            held = {}

            def read():
                if "text" not in held:
                    try:
                        held["text"] = _ci_log_text(cilogs.log(name, int(run)))
                    except cilogs.Refused as e:
                        held["text"] = f"[builderbot] {e}\n"
                return held["text"], "the run's log as GitHub keeps it"
            return read, None
        if kind == "dm":
            return self._dm_log_reader(rest)
        return None, f"no log of the kind {kind or 'named'} is read here"

    def _dm_log_reader(self, rest):
        """`log:dm:NODE:CONTAINER`: any one container's log in a dock tab,
        as the Containers page reads it (_docker_ctl's logs: docker-write,
        and the container's project on the account's list), running or not,
        on a node or on this controller; its last 400 lines read again every
        five seconds. Where a running container's node serves a terminal its
        log streams instead (log:ctr:, bb-tty)."""
        nid, _, name = rest.partition(":")
        me = self._who() or {}
        if me.get("session"):
            return None, "a container's log tab is a person's"
        if why := users.may(me, "docker-write"):
            return None, why
        if not devapp._CTR_NAME.match(name):
            return None, "no such container"
        nid, why = self._node_asked(nid)
        if why:
            return None, why
        with devapp.on_node(nid or None):
            owner = containers.owner_named(name)
        if why := self._not_on_list(me, owner):
            return None, why
        held = {"at": 0.0, "text": ""}

        def read():
            if time.time() - held["at"] >= 5:
                held["at"] = time.time()
                body, status = containers.admin_verb("logs", name, nid, "")
                if status != 200 or body.get("error"):
                    raise ValueError(body.get("error") or "the log could not be read")
                held["text"] = str(body.get("text") or "")
            return held["text"], ""
        return read, None

    def _log_own(self, arg, args, dims):
        """/termws?arg=log:... (R133 step 12): a log in a dock tab, followed
        as it is written and read-only, its reader asked again every few
        seconds and the tab ended when it may no longer read it. A
        container's is followed on its node (bb-tty's log:ctr:, docker logs
        as the docker account), carried signed as its shell is."""
        if _ARG_LOGCTR.match(arg):
            no = self._ctr_log_refused(arg, self._who())
            if not termws.upgrade(self):
                return self._json({"error": no or "a websocket is asked for here"}, 403 if no else 400)
            if no:
                return termws.close(self.connection, no)
            m = _ARG_LOGCTR.match(arg)
            target = ctr_target(m.group(1), m.group(2))
            # A container on this controller, or on a node whose agent
            # serves no terminal, is read here instead, as log:dm: is.
            if target["where"] != "node" or not target.get("term"):
                read, why = self._dm_log_reader(f"{target.get('id', '') if target['where'] == 'node' else ''}:{m.group(3)}")
                if why:
                    return termws.close(self.connection, why)
                who_raw = self._who_raw()
                return termws.term_follow(self.connection, read, lambda: "the controller is in maintenance mode" if kept_out(who_raw) else "")
            words = [v for k, v in urllib.parse.parse_qsl(urllib.parse.urlsplit(
                self._scoped_arg(args, node=True)).query) if k == "arg"]
            who_raw = self._who_raw()

            def alive():
                if kept_out(who_raw):
                    return "the controller is in maintenance mode"
                return self._ctr_log_refused(arg, self._who())
            return termws.node(self.connection, host=target["host"], port=target["screen"], key=nodes.screen_key(target["id"]),
                               kind="ctr", words=words, alive=alive, **dims)
        read, why = self._log_reader(arg)
        if not termws.upgrade(self):
            return self._json({"error": why or "a websocket is asked for here"}, 403 if why else 400)
        if why:
            return termws.close(self.connection, why)
        who_raw = self._who_raw()

        def alive():
            if kept_out(who_raw):
                return "the controller is in maintenance mode"
            return self._log_reader(arg)[1] or ""
        return termws.term_follow(self.connection, read, alive)

    def _static(self, rel, ctype):
        """A file that IS the app (index.html and the tab scripts), served so
        a browser notices when the image changes.

        They went out with no validator and no cache directive at all, which
        leaves it to the browser's own heuristics: a phone could hold the old
        page across a container update and show yesterday's dashboard against
        today's server, with nothing on screen admitting it. `no-cache` is not
        "do not store", it is "ask me first", so the usual answer stays a 304
        of a few bytes and the new bytes arrive the moment the file changes.
        The tag is the file's own size and mtime, which is what changes when
        an image does, and costs one stat rather than a hash of 700KB.
        """
        try:
            st = (HERE / rel).stat()
            raw = (HERE / rel).read_bytes()
        except OSError:
            return self._json({"error": "not found"}, 404)
        tag = f'W/"{st.st_size:x}-{st.st_mtime_ns:x}"'
        if rel == "index.html":
            raw, tag = _versioned_page(raw, tag)
        body, zipped = self._gzip(raw)
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-cache")
            return self.end_headers()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if ctype.startswith("text/html"):
            # The page's policy (R158 step 4): its own scripts and styles,
            # the inline blocks it ships by their hash.
            self.send_header("Content-Security-Policy", csp.header(raw))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", tag)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        return self.wfile.write(body)

    def _gzip(self, body):
        """The body, compressed when the client takes gzip and it pays.

        The page is ~150KB of inline everything and the status snapshot a
        phone polls every fifteen seconds is tens of KB of JSON, and both shrink
        by roughly four fifths. Below ~1400 bytes (one MTU) the header
        shuffle costs more than it saves, so small answers go as they are.
        """
        if (len(body) >= 1400
                and "gzip" in self.headers.get("Accept-Encoding", "")):
            return gzip.compress(body, 6), True
        return body, False

    def _json(self, obj, code=200, cookie=None):
        # Held while _post records what a write means for the sessions: it
        # sends the reply itself once that is done (B290).
        if getattr(self, "_held", None) is not None:
            self._held.append((obj, code, cookie))
            return None
        body, zipped = self._gzip(json.dumps(obj).encode())
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        # A fresh session cookie, when the answer changed what the old one
        # was signed over, such as an account renaming itself.
        if cookie:
            self.send_header("Set-Cookie", f"bb_session={cookie}; Path=/; "
                             f"Max-Age={SESSION_DAYS * 86400}; HttpOnly; SameSite=Strict"
                             + ("; Secure" if tls.over_tls(self.connection) else ""))
        # A session token's renewal, when _who decided one was due: bb and
        # the hooks read this header and write the token where bb looks.
        fresh = getattr(self, "_renewed", "")
        if fresh:
            self.send_header("X-BB-Session", fresh)
            self._renewed = ""
        # no-store, declared rather than assumed: preloading /api/status made
        # it cache-eligible, and a reload that revived a stale layout snapshot
        # from the browser cache then overwrote the real one on the next save.
        # State answers are for right now, never for later.
        self.send_header("Cache-Control", "no-store")
        if zipped:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _safely(self, fn):
        """Turn a handler blowing up into a 500 the page can show.

        Without this the exception unwinds past handle_one_request and the
        connection just closes, which the browser reports as a network error,
        the one failure mode that looks identical to the container being gone.
        """
        t0 = time.monotonic()
        timing.start()
        try:
            try:
                return fn()
            finally:
                cpu, parts = timing.finish()
                trace_note(self, (time.monotonic() - t0) * 1000, cpu, parts)
        except (BrokenPipeError, ConnectionResetError):
            # The other end went away mid-answer: a download canceled, a tab
            # closed. Nothing failed here and nobody is left to answer, so it
            # is one quiet line, not a traceback that bb diag lists as a fault
            # (B429).
            print(f"[dashboard] {self.command} {self.path.partition('?')[0]}: the client left "
                  "before the answer was sent", flush=True)
        except Exception as e:                          # noqa: BLE001 (last resort)
            # Broad by definition: this is the one place a handler's bug is
            # turned into an answer. The log gets the traceback the answer
            # cannot carry.
            print(f"[dashboard] {self.command} {self.path.partition('?')[0]}: "
                  f"{type(e).__name__}: {e}\n{traceback.format_exc()}", flush=True)
            try:
                self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            except OSError:
                pass                                    # client already left

    def do_GET(self):
        if not self._tunnel_refused():
            self._safely(self._get)

    def do_POST(self):
        if not self._tunnel_refused():
            self._safely(self._post)

    def _tunnel_refused(self):
        """A node's tunnel address asks for the agent's API or nothing
        (nodes.tunnel_refuses, R161): by the socket's own address, and
        through a tunnel from home (R170) by the hostname the node was
        enrolled at, or an edge's own headers, which only narrow their writer."""
        if NODES_OK:
            return False
        host = self.headers.get("Host", "")
        own = settings.get("tunnel_host") if not NODES_OK else ""
        peer = self.client_address[0] if self.client_address else ""
        why = nodes.tunnel_refuses(peer, self.path.partition("?")[0], host=host,
                                   # Cloudflare's own mark on what came through the
                                   # controller's own tunnel, whose cloudflared asks this
                                   # machine's loopback: every request Cloudflare proxies
                                   # carries Cf-Ray, so a dashboard simply put behind
                                   # Cloudflare under its own name was refused everything
                                   # but the agents' API (B137). Other tunnels are known by
                                   # the hostname, and the controller's own public hostname
                                   # (R176) is one whatever rule the tunnel carries, so a rule
                                   # left wide reaches no page (bb.neat.fish, 11 Oct).
                                   edge=nodes.own_tunnel_edge("Cf-Ray" in self.headers, peer)
                                        or bool(own and host.lower().rsplit(":", 1)[0] == own))
        if why:
            self._safely(lambda: self._json({"error": why}, 403))
        return bool(why)

    # The favicon set, generated by `bb tool graphics favicon` from static/favicon.svg (the
    # header robot as a standalone file) and committed. An allow-list by full
    # path (the same shape as everything else the page can ask for), so this
    # never grows into a general file server by accident.
    FAVICONS = {
        "/favicon.ico": ("favicon.ico", "image/x-icon"),
        "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
        # The Nostromo scheme's decals: hand-written SVG, text in the tree
        # like the favicon's source, drawn by the page's CSS and by nothing
        # else. Same allow-list, same rule.
        "/static/nostromo/grate.svg": ("nostromo/grate.svg", "image/svg+xml"),
        "/static/nostromo/pipes.svg": ("nostromo/pipes.svg", "image/svg+xml"),
        "/static/nostromo/bulkhead.svg": ("nostromo/bulkhead.svg", "image/svg+xml"),
        "/static/nostromo/panels.svg": ("nostromo/panels.svg", "image/svg+xml"),
        "/static/nostromo/relief.svg": ("nostromo/relief.svg", "image/svg+xml"),
        "/static/nostromo/vents.svg": ("nostromo/vents.svg", "image/svg+xml"),
    }

    def _get(self):
        path = self.path.split("?")[0]
        # Nobody owns this container yet: everything but the assets the card
        # itself needs is the first-run screen. Not a redirect from /login
        # alone: a bookmark, a phone reopening the app, and the WebUI link
        # all arrive at "/", and each of them should land on the thing that
        # has to happen rather than on a sign-in with nothing to sign in to.
        # The agents' API is not a page and carries its own token: a
        # controller installed bare metal enrolls its own machine as a node
        # before anybody has made the first account (B323), and its agent's
        # download met the first-run card.
        if path.startswith("/api/v1/agent/"):
            return self._agent()
        if not users.all_users() and path not in ("/favicon.ico", "/favicon.svg"):
            return self._login_page(setup=True)
        if path == "/login":
            return self._login_page()
        if path == "/login/setup" and self._authed():
            return self._setup_2fa_page()
        if path == "/logout":
            return self._logout()
        if path.startswith("/api/v1/device/"):
            return self._device()
        if path == "/api/v1/healthz":
            # Open, like the agent door: a monitor asks this without the
            # operator's credential, and it says alive-and-the-store-answers
            # with two counts, nothing that names a machine (docs/nodes.md §9).
            body, code = ((jobs.healthz() if not NODES_OK
                           else ({"ok": False, "error": NODES_OK}, 503)))
            return self._json(body, code)
        if not self._authed():
            return self._deny()
        if self._two_factor_gate(path):
            return None
        if path == "/metrics":
            if NODES_OK:
                return self._json({"error": NODES_OK}, 503)
            body = jobs.metrics_text().encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        # A VM's screen (R99): noVNC's page and client, and the relay to the
        # VM's node.
        if path.startswith("/novnc/"):
            return self._novnc(path[len("/novnc/"):])
        # xterm.js and its fit addon (R133), vendored beside the page.
        if path.startswith("/vendor/"):
            return self._vendor(path[len("/vendor/"):])
        if path == "/screen/ws":
            return self._screen_proxy()
        if path == "/termws":
            return self._term_own()
        # One terminal on a page of its own: a tab popped out of the dock,
        # and the Android app's session screen (R133).
        if path == "/terminal":
            return self._static("terminal.html", "text/html; charset=utf-8")
        if path.startswith("/apps/"):
            return self._app_file(path)
        # The page's companion scripts: a new surface is a new classic-script
        # file beside index.html (docs/nodes.md §13), served by name from the
        # list the page's own script tags make (page_scripts), so it never
        # grows into a general file server by accident.
        if path.startswith("/") and path[1:] in page_scripts():
            return self._static(path[1:], "text/javascript; charset=utf-8")
        if self.path.split("?")[0] in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if fav := self.FAVICONS.get(self.path.split("?")[0]):
            name, ctype = fav
            try:
                body = (HERE / "static" / name).read_bytes()
            except OSError:              # a checkout that predates the assets
                return self._json({"error": "not found"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # A day: the icon changes when the image does, and a stale tab
            # icon for a day is invisible next to re-fetching it every poll.
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            return self.wfile.write(body)
        # A feature this install switched off (R81) answers its sentence.
        if why := featuresoff.refused("GET", path):
            return self._json({"error": why, "off": True}, 403)
        # An exact route is the path without its query (B409): /api/audit?n=50
        # and /api/router?node=N are the exact routes' own reads.
        for how, route, name in GET_ROUTES:
            if (path == route) if how == "exact" else self.path.startswith(route):
                return getattr(self, name)()
        self._json({"error": "not found"}, 404)

    def _get_trace(self):
        """GET /api/trace?since=T: what this server was asked since T,
        grouped by endpoint (R75 step 4). For an admin or a session: the
        page's own behavior is what it describes, and a session diagnosing
        a tab that asks too much is the reader it exists for. Paths and
        query KEYS only, never values: a project's name in a query is the
        one thing here that is somebody's."""
        who = self._who()
        # A session's only with the diagnostics grant: the trace is every
        # request the controller answered, every project's paths among them.
        if not who or not (users.is_admin(who) or (who.get("session") and not self._diag_why())):
            return self._json({"error": "the trace is for an administrator, or a session whose project "
                                        "has the diagnostics grant (the Debug page)"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        try:
            since = float((q.get("since") or ["0"])[0])
        except ValueError:
            since = 0.0
        return self._json(trace_since(since))

    def _get_revs(self):
        """GET /api/revs."""
        # Deliberately tiny and deliberately cheap: this is polled every
        # second or two, where /api/status is polled every fifteen because
        # it runs git for every project. `p` is the projects the page has
        # notebooks open on, so the per-project half is one project's work
        # rather than the whole share's.
        # Absent and empty are different answers: a page with no notebook
        # open sends `p=` and wants none of the per-project tokens, where
        # `bb` and the tests send no `p` at all and want them all.
        # keep_blank_values, or `p=` parses to nothing at all and reads
        # as the absent case, which is the opposite answer.
        q = urllib.parse.parse_qs(self.path.partition("?")[2],
                                  keep_blank_values=True)
        raw = q.get("p")
        ps = None if raw is None else [x for x in (raw[0] or "").split(",") if x]
        return self._json(revisions(self._who(), ps))

    def _get_status(self):
        """GET /api/status."""
        return self._json(snapshot(self._who()))

    def _get_live(self):
        """GET /api/live: who has a Claude session on each project this
        account sees, which of them are working and which asking, the maps
        the status payload also carries (projsessions.maps), alone and
        cheap. Fetched when the revs token `live` moves."""
        who = self._who()
        # ...each project on its list as its repositories (R138), which the
        # sessions are named for.
        seen = None if users.sees_all(who) else [r for p in (who or {}).get("projects") or []
                                                  for r in (repos.members(p) or [p])]
        return self._json(projsessions.maps(tmux_sessions() + node_tmux_sessions(), seen))

    def _get_findings(self):
        """GET /api/findings: findings.view, scoped to the projects this
        account sees, and for a session to its own."""
        me = self._who() or {}
        return self._json(findings.view(project_list(me), me.get("session") or ""))

    def _get_git(self):
        """GET /api/git: the notebook's Git view (gitview.view), for a
        project this account may see."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        try:
            n = int(q.get("n", ["0"])[0])
        except ValueError:
            n = 0
        body = gitview.view(name, q.get("what", [""])[0], sha=q.get("sha", [""])[0],
                            path=q.get("path", [""])[0], n=n,
                            branch=q.get("branch", [""])[0])
        if isinstance(body, dict) and not body.get("error") and q.get("what", [""])[0] in ("", "all", "status"):
            # Whose token a press would use (R159), by name.
            body["token"] = _token_said(name, users.uid_of(self._who()))
        return self._result(body)

    def _get_changelog(self):
        """GET /api/changelog: changelog.reading, for a project this account
        sees."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(*changelog.reading(name, q.get("component", [""])[0]))

    def _get_tls(self):
        """GET /api/tls: what the dashboard is served over (tls.status), for
        an account that reads the controller; with download=1 the
        certificate itself, for a phone or the companion to pin."""
        if self._refused("controller-read"):
            return
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        if q.get("download", [""])[0]:
            pem = tls.certificate_pem().encode()
            if not pem:
                return self._json({"error": "no certificate is in force: the dashboard is served over http"}, 404)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-pem-file")
            self.send_header("Content-Disposition", 'attachment; filename="builderbot.pem"')
            self.send_header("Content-Length", str(len(pem)))
            self.end_headers()
            self.wfile.write(pem)
            return None
        return self._json(tls.status(settings.get))

    def _csp_report(self):
        """POST /api/csp-report: what a browser refused under the page's
        policy (R158 step 4), kept for the Doctor (csp.report). The browser
        sends it on its own, from the login page too, so it is taken before
        the credential check, from anyone, and kept small."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if not 0 <= n <= 8192:
            return self._json({"error": "body too large"}, 413)
        body = self.rfile.read(n)
        who = self._who() or {}
        csp.report(body, who.get("name") or "")
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _tls(self, req):
        """POST /api/tls {action: issue}: a Let's Encrypt certificate for the
        Connection section's hostname asked for now, by DNS-01 through the
        Cloudflare API token (nginxproxy's hooks), for an account that
        changes the controller's settings."""
        if self._refused("controller"):
            return
        if field(req, "action") != "issue":
            return self._json({"error": "unknown action"}, 400)
        return self._json(_tls_issue())

    def _get_audit(self):
        """GET /api/audit: who did what to this install (db.audit_page) for
        the Audit page (R158 step 8), newest first, a page at a time
        (before=TIME), by one person (person=NAME) or one machine
        (machine=NODE_ID); with the people and the machines to pick from.
        For an account that reads the controller's area."""
        if self._refused("controller"):
            return
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        person, machine = q.get("person", [""])[0][:120], q.get("machine", [""])[0][:40]
        try:
            before, n = int(q.get("before", ["0"])[0]), min(500, max(1, int(q.get("n", ["100"])[0])))
        except ValueError:
            before, n = 0, 100
        names = {n_["id"]: n_.get("name") or n_["id"] for n_ in nodes.node_list(all=True)}
        rows, total = db.audit_page(n, before, f"user:{person}" if person else "", machine)
        out = [{"at": r["at"], "who": r["principal"][5:] if str(r["principal"]).startswith("user:") else r["principal"],
                "action": r["action"], "target": r["target"], "machine": names.get(r["target"], ""),
                "params": r["params"]} for r in rows]
        return self._json({"rows": out, "total": total,
                           "people": sorted(u["name"] for u in users.all_users()),
                           "machines": [{"id": k, "name": v} for k, v in sorted(names.items(), key=lambda kv: kv[1])]})

    def _get_version(self):
        """GET /api/version."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # What would keep a release's APK from being signed (R134 step 4),
        # said by Release's confirm before the tag is made.
        rs = releasesign.readiness(name)
        return self._json(version_payload(name) | {"release_sign": rs["why"] if rs["wanted"] else ""})

    def _get_artifacts(self):
        """GET /api/artifacts: artifacts.tab_view, for a project this account
        sees."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(artifacts.tab_view(name, users.uid_of(self._who())))

    def _get_artifact(self):
        """GET /api/artifact: one file of a project's, as a download
        (artifacts.download)."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        got, status = artifacts.download(name, q.get("path", [""])[0], q.get("tree", [""])[0])
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got, "application/octet-stream")

    def _get_apps(self):
        """GET /api/apps: the apps this controller offers and holds
        (apps.view), for the Apps page and the Settings section."""
        return self._json(apps.view())

    def _apps(self, req):
        """POST /api/apps: look at the release again now (apps.check_now).
        An administrator's, as the switches beside it are."""
        if self._refused("controller"):
            return None
        if field(req, "action") != "check":
            return self._json({"error": "the one action is check"}, 400)
        return self._json({"ok": True, "started": apps.check_now(), **apps.view()})

    def _pc(self, req):
        """POST /api/pc: a session's word with a PC lent to its project
        (pcwork.py, bb pc): lent (which PCs lend which verbs), run (ask
        one, under the project's Agents may: Use a lent PC) and result (an
        ask's answer, held a while). A session's alone: its project is the
        one its token was minted for."""
        me = self._who() or {}
        project = me.get("session") or ""
        if not project:
            return self._json({"error": "bb pc is a session's: a person uses their PC themselves"}, 403)
        act = field(req, "action")
        if act == "lent":
            return self._json({"pcs": pcwork.lent(project), "mode": (prefs.get(project) or {}).get("pc") or "deny",
                               "verbs": list(pcwork.VERBS)})
        if act == "run":
            by = f"{me.get('name') or 'a session'}'s session on {project}"
            return self._json(*pcwork.ask(project, field(req, "verb"), req.get("args"), field(req, "why"), by))
        if act == "result":
            return self._json(*pcwork.wait_result(project, field(req, "id"), req.get("wait") or 0))
        return self._json({"error": "lent, run or result"}, 400)

    def _app_file(self, path):
        """GET /apps/NAME/FILE: an app this controller holds, as a download,
        for anybody signed in (apps.path names only what the index holds)."""
        name, _, fname = path[len("/apps/"):].partition("/")
        p = apps.path(name, fname)
        if not p:
            return self._json({"error": f"this controller holds no {fname or name}"}, 404)
        return self._send_file({"path": p, "ctype": "application/octet-stream",
                                "headers": {"Content-Disposition": f'attachment; filename="{p.name}"'}})

    def _get_meta(self):
        """GET /api/meta."""
        # What the companion app asks first: the surface number this
        # dashboard serves, the image it is, and where a newer app is: the
        # one this controller fetched from its release (R272 step 5), else
        # the newest in BuilderBot's own dist/ as before.
        held = next((a["files"][0] for a in apps.view()["apps"] if a["name"] == "android" and a["files"]), None)
        apk = {"apk": held["file"], "apk_sha256": held["sha256"], "apk_url": held["url"]} if held else \
            {"apk": app_apk(), "apk_sha256": app_apk_sha(), "apk_url": ""}
        # ...and, for a session that names its node, the agent there and when
        # it was built (R131): what bb status says beside the controller's.
        agent = {}
        nid = urllib.parse.parse_qs(self.path.partition("?")[2]).get("node", [""])[0]
        if nid and (self._who() or {}).get("session") and not NODES_OK:
            ag = (nodes.node(nid) or {}).get("agent") or {}
            agent = {"version": str(ag.get("version") or ""), "built": str(ag.get("built") or "")}
        return self._json({"api": APP_API, "version": image_stamp().get("version") or "",
                           "image": image_stamp().get("rev") or "",
                           "built": image_stamp().get("built") or "", **apk,
                           **({"agent": agent} if agent else {})})

    def _get_welcome(self):
        """GET /api/welcome: BuilderBot's own changelog for the welcome panel
        (changelog.welcome), and where this account last looked."""
        return self._json(changelog.welcome(str(users.prefs(self._who()).get("image_seen") or "")))

    def _get_source(self):
        """GET /api/source: the code base as a zip, from the Artifacts view
        (artifacts.source_download). A person's download, so a session's
        token is refused: a session has the tree already."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if (self._who() or {}).get("session"):
            return self._json({"error": "a session has the tree already"}, 403)
        if self._not_project(name):
            return
        got, status = artifacts.source_download(name)
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got, "application/zip")

    def _attachment(self, fname, data, ctype):
        """Bytes as a download named `fname`, which the caller has made safe
        for the header."""
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)
        return None

    def _get_logs_download(self):
        """GET /logs/download: the container's own log, every project's
        traffic in it, or the diagnostics whole (logs.download): Controller
        settings' to read, the diagnostics with them, since they hold the bug
        reports a person reads there (the operator, 26 Oct)."""
        if self._refused("controller-read"):
            return None
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        got, status = logs.download((q.get("what") or [""])[0], self._principal())
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got)

    def _get_phone(self):
        """GET /api/phone."""
        # Not on the status poll: a probe is a job on a node, so the tab
        # asks when it is opened or pressed, and reads the cache between.
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        # A probe is a job on the named node, and a session's token is
        # bound to one project's node and no other (the same rule the
        # jobs endpoint keeps): a session reads the cache, an account
        # may ask the node.
        return self._json(self._phone_payload(node=(q.get("node") or [""])[0],
                                              probe=bool(q.get("probe")) and not (self._who() or {}).get("session")))

    def _get_phone_wait(self):
        """GET /api/phone/wait?since=T: the companion app's live connection
        (R125). Answers {token} at once when this account's phone asks,
        lease or grants differ from T, else holds the request until they
        do or about 45 s pass, so an ask reaches the app in a second rather
        than on Android's alarm. A person's, not a session's."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "the live connection is the companion app's"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        since = q.get("since", [""])[0]
        uid, admin = users.uid_of(who), users.is_admin(who)
        end = time.time() + PHONE_WAIT_S
        while True:
            tok = phone.wait_token(uid, admin)
            if tok != since or time.time() >= end:
                return self._json({"token": tok})
            time.sleep(0.5)

    def _get_toolchains(self):
        """GET /api/toolchains."""
        # ?node= asks about another node's toolchain store: what its
        # census says it has, and the toolchain job in flight there. The
        # catalog is the same; the state is the node's (docs/nodes.md §6).
        # Without Toolchains Read the tab is not offered (R152 step 3), and
        # this answers only for the nodes of the person's own projects,
        # which _node_asked keeps it to: what their projects build with.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        nid, why = self._node_asked(q.get("node", [""])[0])
        if why:
            return self._json({"error": why, "toolchains": []})
        if nid and nid != "local" and not NODES_OK:
            d = toolchains.payload_for_node(nid)
            # A toolchain job's output is the node's, read by a session only
            # with its project's diagnostics grant, as bb jobs reads it (the
            # operator, 12 Oct): the rows and what failed stay, the log lines
            # and the error excerpts go, with the reason in their place.
            why = self._diag_why() if (self._who() or {}).get("session") else ""
            if why and isinstance(d.get("job"), dict):
                d["job"] = {k: v for k, v in d["job"].items() if k not in ("log", "errors")}
                d["job"]["hidden"] = why
            return self._json(d)
        return self._json(toolchains.payload())

    def _get_agents(self):
        """GET /api/agents?node=ID: the coding agents on one node (R95, the
        Agents page): each agent's row, the version against the latest and
        any job of its own, and the asking account's own plugins and MCP
        servers there. Answered for the nodes this account may look at."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        nid, why = self._node_asked(q.get("node", [""])[0])
        if why or not nid or nid == "local":
            return self._json({"error": why or "which node?", "rows": []})
        n = nodes.node(nid) if not NODES_OK else None
        if not n:
            return self._json({"error": "no such node", "rows": []}, 404)
        out = {"node": nid, "name": n.get("name") or nid, "live": bool(n.get("live")), "rows": agentcode.rows(n)}
        me = self._who() or {}
        if users.uid_of(me) and not me.get("session"):
            mine = next((x for x in plugins.of(users.uid_of(me)) if x["node"] == nid), {})
            out["yours"] = {"plugins": mine.get("plugins") or [], "mcp": mine.get("mcp") or {}}
        return self._json(out)

    def _agents(self, req):
        """POST /api/agents: install (or update), remove or check one coding
        agent on one node (agentcode.verb), the one way an agent is managed
        (R95, the operator 22 Oct): whoever may install toolchains there."""
        if (why := users.may_node(self._who(), "toolchains-write", field(req, "node"))):
            return self._json({"error": why}, 403)
        return self._json(*agentcode.verb(self._principal(), req))

    def _get_emulator(self):
        """GET /api/emulator?node=ID: that node's system images, what could be
        added, and the image job there. The same node scope as Toolchains."""
        if NODES_OK:
            return self._json({"error": "the node store did not open"})
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        nid, why = self._node_asked(q.get("node", [""])[0])
        if why or not nid:
            return self._json({"error": why or "no node named"})
        got = emulator.payload(nid)
        # ...and each project's phones there, of the projects this account
        # sees (R123): the Emulator page is where a phone is removed.
        if not got.get("error"):
            who = self._who()
            st = ((nodes.node(nid) or {}).get("reported") or {}).get("storage") or {}
            got["phones"] = [p for p in st.get("phones") or []
                             if users.is_admin(who) or users.may_see(who, p.get("project") or "")]
        return self._json(got)

    def _get_users(self):
        """GET /api/users."""
        # The listing never carries a hash; all_users() drops it. Projects
        # come from the same filtered list everything else reads, so an
        # admin cannot hand out what they cannot see themselves. Accounts
        # and roles Read lets one see it (R152 step 3).
        if (why := self._area_read_why("accounts")):
            return self._json({"error": why}, 403)
        with timing.timed("users:tab_view"):
            got = users.tab_view(self._who(), project_names(self._who()),
                                 claudegrant.logins_of)
        # Each account's devices, for an administrator to see and cut off
        # (R272 step 8); seeing and revoking only, never driving one.
        if users.is_admin(self._who() or {}):
            accts = users.load().get("users") or {}
            for u in got.get("users") or []:
                u["devices"] = devices.listed({"name": u.get("name"), **(accts.get(u.get("name")) or {})})
        return self._json(got)

    def _get_roles(self):
        """GET /api/roles: the Roles page (R152): the areas, every role, and
        each account with its Global roles, the roles it holds on each
        project and the projects it is on. An administrator's whole; a
        project's owner sees the people and roles of the projects they own,
        to give those (users.assignable)."""
        me = self._who() or {}
        can = users.assignable(me)
        # Accounts and roles Read with nothing to give sees the whole of it,
        # to read: the page draws it without a control (B34).
        readonly = not can["admin"] and not can["projects"] and not me.get("session") \
            and not self._area_read_why("accounts", me=me)
        if not can["admin"] and not can["projects"] and not readonly:
            return self._json({"error": "the Roles page is an administrator's, a project owner's "
                                        "for their own projects, or for reading, Accounts and roles Read's"}, 403)
        # By project (R138): an entry kept under a repository's name counts
        # for the project it is in, as everywhere roles are read.
        scope = None if can["admin"] or readonly else {repos.key_of(p) for p in can["projects"]}
        people = []
        for u in users.all_users():
            full = users.get(u["name"]) or {}
            pr = {}
            for p, r in (full.get("project_roles") if isinstance(full.get("project_roles"), dict) else {}).items():
                k = repos.key_of(p)
                pr[k] = list(dict.fromkeys([*pr.get(k, []), *(r if isinstance(r, list) else [])]))
            on = list(dict.fromkeys(p if p == "*" else repos.key_of(p) for p in full.get("projects") or []))
            if scope is not None:
                pr = {p: r for p, r in pr.items() if p in scope}
                on = [p for p in on if p in scope]
            people.append({"name": u["name"], "uid": u["uid"], "role": u["role"],
                           "roles": [r for r in roles.roles_of(full) if r not in ("user",)]
                           if can["admin"] or readonly else [],
                           "project_roles": pr, "projects": on})
        all_projects = sorted((k for k in registry.repos_keys() if users.may_see(me, k)) if scope is None else scope,
                              key=lambda k: registry.label(k).lower())
        rs = roles.all_roles()
        if scope is not None:
            rs = {n: r for n, r in rs.items() if r.get("scope") == "projects"}
        # A project's owner role is named after its directory; the tab says
        # whose it is by the name the project is shown under (R154).
        owners_of = {roles.owner_role_name(d): d for d in registry.labels()}
        # One whose project is not live (in the trash) is not listed: it is
        # kept for Put back, and listed it was counted as a project's owner
        # and could share a label with the live one shown under that name
        # (B95). A role of the same cut name a live project holds wins.
        # ...and named by the project it is for (R138), which is what the
        # page's projects are: a live repository's project's key.
        live_owned = set()
        for d in registry.live_dirs():
            owners_of[roles.owner_role_name(d)] = repos.key_of(d)
            live_owned.add(roles.owner_role_name(d))
        # ...and a project's own (R138): its owner role is named for the
        # project as it is shown, which a repository's name need not match,
        # and unmatched it was offered under every project.
        for k in registry.repos_keys():
            owners_of[roles.owner_role_name(k)] = k
            live_owned.add(roles.owner_role_name(k))
        # ...and one named before either of those (a repository's old name,
        # a project's earlier key) by the project its note says it owns: tied
        # to that project while it is live, and left off the lists once it is
        # gone, where unmatched it was offered under every project.
        dirs, keys, gone = set(registry.live_dirs()), set(registry.repos_keys()), set()
        for n, r in rs.items():
            note = str(r.get("note") or "")
            if n in owners_of or not n.endswith("_owner") or not note.startswith("the owner of "):
                continue
            x = note[len("the owner of "):]
            k = repos.key_of(x) if x in dirs else x if x in keys else ""
            if k:
                owners_of[n] = k
                live_owned.add(n)
            else:
                gone.add(n)
        rs = {n: r for n, r in rs.items() if n not in gone and (n not in owners_of or n in live_owned)}
        # ...and which project it is for, so the People section offers it
        # under that project alone (B726).
        rs = {n: (dict(r, label=f"Owner of {registry.label(owners_of[n])}", project=owners_of[n]) if n in owners_of else r)
              for n, r in rs.items()}
        return self._json({"roles": rs, "areas": [list(a) for a in roles.AREAS], "people": people,
                           "projects": all_projects, "admin": can["admin"], "readonly": readonly,
                           "me": me.get("name") or "",
                           "owner": users.owner_name() or "", "node_areas": sorted(roles.NODE_AREAS),
                           # What an area's row opens on (R260): the nodes for
                           # a node area, each runner (NODE_ID/SLOT) for the
                           # CI runner's.
                           "instance_areas": sorted(roles.INSTANCE_AREAS),
                           "nodes": [] if NODES_OK or not can["admin"] else
                           [{"id": n["id"], "name": n["name"]} for n in nodes.node_list()
                            if n.get("kind") != "local" and n.get("state") != "retired"],
                           "runners": [] if NODES_OK or not can["admin"] else
                           # Named by what it serves: its registered name is
                           # its node's, which the line already says.
                           [{"id": f"{r['id']}/{r['slot']}", "node": r["node"],
                             "name": re.sub(r"^https?://", "", r.get("url") or "") or r["slot"]}
                            for r in runners.listing()]})

    def _get_nodes(self):
        """GET /api/v1/nodes: the Nodes page's read (nodes.tab_view), scoped to
        this account."""
        # The versioned surface starts here (docs/nodes.md §3): new
        # endpoints land under /api/v1 with their shapes written down;
        # the unversioned paths above migrate later, never both at once.
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        # Without Nodes Read the tab is not offered (R152 step 3), and this
        # answers with the nodes of the person's own projects alone, which a
        # Claude sign-in on them needs, as below.
        # Scoped for an account that may not change a node: it sees the
        # ones its own projects build on and no others, because the list
        # is otherwise a way to learn what machines exist and what they
        # are called (roadmap #27). An administrator sees the registry.
        return self._json(nodes.tab_view(self._nodes_for(nodes.node_list()),
                                         users.may(self._who(), "admin") == ""))

    def _get_home(self):
        """GET /api/home: home.read, the overview's numbers (R218 step 5).
        The jobs are the ones this account sees on the Jobs page, scoped the
        same way; the machines and their containers only for an account
        that reads the Nodes area."""
        me = self._who()
        rows, names = [], {}
        if not NODES_OK:
            mine = None if users.may(me, "admin") == "" \
                else set(project_names(me))
            if mine is not None and not (me or {}).get("session") and self._area_read_why("jobs"):
                mine = {p for p in mine if roles.level_of(me, "projects", p, users.may_work)}
            with timing.timed("home:jobs"):
                got, _ = nodes.jobs_view("", {"n": ["500"]}, mine, hidden=self._jobs_hidden())
            rows, names = got.get("jobs") or [], got.get("nodes") or {}
        machines = not NODES_OK and not self._area_read_why("nodes")
        light = urllib.parse.parse_qs(self.path.partition("?")[2]).get("light", [""])[0] == "1"
        with timing.timed("home:read"):
            got = home.read(rows, names, machines, light)
        return self._json(*got)

    def _get_jobs(self):
        """GET /api/v1/jobs: nodes.jobs_view, narrowed to the projects this
        account may see unless it administers."""
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        mine, system = self._jobs_scope()
        return self._json(*nodes.jobs_view(q.get("id", [""])[0], q, mine, system, self._jobs_hidden()))

    def _jobs_scope(self):
        """(the projects whose jobs this account reads, None for all; the
        redaction its read of the node's own jobs goes through, or None):
        what the Jobs page and a job's log in the dock (R133 step 12) both
        read by."""
        me = self._who()
        mine = None if users.may(me, "admin") == "" \
            else set(project_names(me))
        # Without Jobs Read a person sees their projects' jobs alone, those
        # they may read (R152 step 3); the Jobs tab is hidden for them.
        if mine is not None and not (me or {}).get("session") and self._area_read_why("jobs"):
            mine = {p for p in mine if roles.level_of(me, "projects", p, users.may_work)}
        # The node's own jobs (a toolchain install, an update) for whoever may
        # read the controller's diagnostics, which list them: a job named
        # there that could not be opened was a dead end (the operator, 7 Oct).
        # Through diag's redaction, as the diagnostics themselves are.
        system = diag.redact if mine is not None and not self._diag_why() else None
        return mine, system

    def _jobs_hidden(self):
        """What of the jobs this reader does not see at all: a schedule's runs
        to a session (the operator, 26 Oct: sessions neither see nor touch
        the schedules), whose scripts and logs are an administrator's."""
        if not (self._who() or {}).get("session"):
            return None
        return lambda j: str(j.get("requested_by") or "").startswith("schedule:")

    def _get_docker(self):
        """GET /api/docker: the manager's whole page, containers.manager_view,
        for the node this account may read."""
        # No node named means the default, which is the arrangement that
        # predates the picker.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        me = self._who() or {}
        sess = me.get("session") or ""
        # A session reads its own project's node, which is where it works,
        # whatever it asks for. Anybody else naming a project and no node
        # reads that project's (bb devapp ls outside a session).
        asked = q.get("node", [""])[0]
        proj = q.get("project", [""])[0]
        if sess or (not asked and proj):
            # A named project reads its own node's daemon, allowed by the
            # project being the account's to see rather than by the node
            # scope (B258); the filter below still keeps the answer to the
            # account's projects. A project with no node has no daemon and
            # no containers anywhere: there is no primary docker manager for
            # it to fall to (the operator, 25 Sep), so that is said.
            if not sess and self._not_project(proj):
                return None
            # A session reads its own project's containers, and those of a
            # project it reads (bb -p NAME devapp, B551/B552): reading them
            # is what reads means. Acting on them stays its own project's.
            name = proj if sess and proj and proj != sess and self._reads(proj) else sess or proj
            # Every node its containers may be on, its own first (B338).
            where = devapp.container_nodes(name)
            nid, why = (where[0] if where else ""), None
            if not nid:
                return self._json({"error": f"{name} has no node, so it has no containers anywhere. "
                                            + no_node_advice(name),
                                   "blind": True, "instances": [], "containers": []})
        else:
            where = None
            nid, why = self._node_asked(asked)
        if why:
            return self._json({"error": why, "blind": True,
                               "instances": [], "containers": []})
        # What an account that is not an administrator sees is what belongs
        # to its projects, a session's to its own one (the operator, 24 Sep).
        seen = None
        if sess or self._node_scope() is not None:
            seen = {name} if sess else set(project_names(me))
        # ...and of those, the projects whose Containers this person may
        # read (R152 step 3).
        if seen is not None and not sess and not users.is_admin(me):
            seen = {p for p in seen if roles.level_of(me, "containers", p, users.may_work)}
        # /api/docker/stats: what the containers are using now, asked
        # beside the list once it has landed (R216), so the list never
        # waits on a sample of the daemon. A path of its own rather than a
        # query, since the page's open-once rule counts endpoints by path.
        sub = self.path.partition("?")[0].rstrip("/").rsplit("/", 1)[-1]
        if sub == "stats" or q.get("stats", [""])[0]:
            return self._json(containers.stats_view(nid, seen))
        # /api/docker/images: the daemon's images and volumes, an
        # administrator's like every daemon-wide thing here (R216).
        if sub == "images" or q.get("images", [""])[0]:
            if sess or not users.is_admin(me):
                return self._json({"error": "an administrator reads the daemon's images and volumes",
                                   "images": [], "volumes": [], "df": []}, 403)
            return self._json(containers.images_view(nid))
        with timing.timed("docker:manager_view"):
            got = containers.manager_view(nid, seen)
            # A project's view across every node its containers are on, each
            # row saying which: an instance put on a hosting node is listed
            # where the session that made it can find it (B338).
            if where and len(where) > 1:
                for row in (got.get("instances") or []) + (got.get("containers") or []):
                    row.setdefault("node_name", devapp.node_name(nid))
                for other in where[1:]:
                    more = containers.manager_view(other, seen)
                    for k in ("instances", "containers"):
                        for row in more.get(k) or []:
                            row.setdefault("node_name", devapp.node_name(other))
                        got[k] = (got.get(k) or []) + (more.get(k) or [])
                    got["blind"] = bool(got.get("blind")) or bool(more.get("blind"))
        return self._json(got)

    def _get_containers(self):
        """GET /api/containers."""
        # A read, and the only one this dashboard makes of the daemon
        # beyond `docker version` (see the guard in devapp.py, which
        # allows it and still refuses anything that would change something).
        # Everything on the daemon, every project's: an administrator's.
        if self._refused("containers-read"):
            return None
        return self._json(devapp.containers())

    def _get_vms(self):
        """GET /api/vms (R91): the VMs of the projects this account may read
        them on (a session: its own), the OS catalog and the VM hosts."""
        me = self._who() or {}
        sess = me.get("session") or ""
        if sess:
            seen = {sess}
        else:
            seen = {p for p in project_names(me) if roles.level_of(me, "vms", p)}
        # A VM whose repository is gone is in no project (the operator, 26
        # Oct): an administrator's to see and act on, under No project.
        gone = set()
        if not sess and users.is_admin(me):
            gone = {v.get("project") or "" for v in vms.view()} - {""}
            gone = {p for p in gone if not registry.is_project(p)}
            seen |= gone
        # Which of them it may change, for the page's buttons: the server
        # refuses the rest whatever is pressed.
        can = {p: "write" if sess or p in gone or roles.level_of(me, "vms", p) == "write" else "read" for p in seen}
        # ...and on which it may take a Console from whoever has it: the
        # project's owner's and the administrators' (the operator, 21 Oct).
        uid = users.uid_of(me) or ""
        take = {p: not sess and can[p] == "write" and (users.is_admin(me) or (uid and membership.owner_of(p) == uid))
                for p in seen}
        return self._json(vms.payload(seen) | {"can": can, "take": take, "me": uid, "unowned": sorted(gone)})

    def _vms(self, req):
        """POST /api/vms (R91): new, start, stop, restart, remove, snapshot,
        revert, snapshot-rm. A person needs VMs Write on the project; a
        session acts on its own project alone, under its Make VMs dial
        (deny refuses, ask holds it for the administrators, auto does it)."""
        me = self._who() or {}
        sess = me.get("session") or ""
        project = field(req, "project") or sess
        action = field(req, "action")
        if action not in ("new", "iso-add", "iso-rm", "console-take", "vbios") + vms.ACTIONS:
            return self._json({"error": f"no such VM action: {action}"}, 400)
        # An installer's ISO onto a node, or off it (R99): a person's, since
        # what it fetches is a whole system to install by hand.
        # Whether the asker administers, which a passthrough and a vBIOS need
        # (R100): the server's word, never what the request says of itself.
        req = dict(req, _admin=bool(users.is_admin(me)) and not sess)
        if action in ("iso-add", "iso-rm", "vbios") and sess:
            return self._json({"error": "fetching an installer ISO onto a node is a person's, on the VMs page"}, 403)
        # One whose repository is gone is in no project, and an
        # administrator's alone; nothing new is made in it.
        orphan = (bool(project) and not registry.is_project(project) and not sess and users.is_admin(me)
                  and action not in ("new", "iso-add", "iso-rm")
                  and any(v.get("project") == project for v in vms.view([project])))
        if not project or not (registry.is_project(project) or orphan):
            return self._json({"error": "which project's VM? name one"}, 400)
        # The address this controller was reached at, which a VM made a node
        # dials (R91 step 14): the asker's own, as Enroll node's script uses.
        req = dict(req, ctl=f"{'https' if self.headers.get('X-Forwarded-Proto') == 'https' else 'http'}://"
                            f"{self.headers.get('Host') or ''}")
        if req.get("node_agent") is True and not sess and self._refused("node"):
            return
        if sess:
            if project != sess:
                return self._json({"error": f"a session works on {sess}'s VMs alone, not {project}'s"}, 403)
            if req.get("node_agent") is True and prefs.get(sess)["makevms"] != "deny":
                # A node is the administrators' to add: asked of them whatever
                # the dial says, and made by whoever allows it.
                return self._result(phone.ask_vm(field(req, "why") or f"new {field(req, 'name')}, made a node", sess, req,
                                                 asker_name=(me.get("name") or "")))
            mode = prefs.get(sess)["makevms"]
            if mode == "deny":
                return self._json({"error": f"{sess}'s settings say an agent may not make or change VMs "
                                            "(Make VMs is deny): a person changes that in the project's settings"}, 403)
            # A USB device to a VM is held for a person whatever the dial
            # says (R116 step 6): a device can be a disk or a key.
            if mode == "ask" or action in ("usb-give", "usb-take"):
                r = phone.ask_vm(field(req, "why") or f"{action} {field(req, 'name')}", sess, req,
                                 asker_name=(me.get("name") or ""))
                return self._result(r)
            return self._result(_vm_do(f"session:{sess}", sess, req, True))
        if self._refused("vms-write", project):
            return
        why = self._not_on_list(me, project)
        if why:
            return self._json({"error": why}, 403)
        if action == "console-take":
            return self._console_take(me, project, field(req, "name"))
        return self._result(_vm_do(self._principal(), project, req, False))

    def _console_take(self, me, project, name):
        """A VM's Console taken from whoever has it, by the project's owner or
        an administrator: a minute's grant the console proxy honors, and a
        notice to each person it is taken from."""
        uid = users.uid_of(me) or ""
        if not (users.is_admin(me) or (uid and membership.owner_of(project) == uid)):
            return self._json({"error": "taking a VM's Console from whoever has it is the project's owner's or an "
                                        "administrator's; its Screen can be shared instead"}, 403)
        key = f"{project}/{name}"
        vms.take(uid, key)
        by = me.get("name") or self._principal()
        for huid, _ in vms.holders(key, "console", but=uid):
            if huid:
                notices.act(huid, {"action": "add", "level": "warn",
                                   "text": f"{by} took {name}'s Console in {project} from you"})
        return self._json({"ok": True})

    def _get_project_job(self):
        """GET /api/project-job."""
        if self._refused("create"):
            return None
        return self._json(projects.job())

    def _get_trash(self):
        """GET /api/trash."""
        if self._refused("trash"):
            return None
        return self._trash_list()

    def _get_claude_now(self):
        """GET /api/claude-now."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json({"model": claude_model_now(WORKSPACE / name, users.uid_of(self._who()))})

    def _get_todo(self):
        """GET /api/roadmap."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json({"project": name} | roadmap.panel(name, sessions_anywhere(),
                                                            users.tmux_prefix(self._who())))

    def _get_rules(self):
        """GET /api/rules."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # With the number a Save is checked against (B195): read in the same
        # answer as the rules, so the two cannot describe different moments.
        who = self._who() or {}
        # Whether this person may change the global rules themselves, which
        # the notebook offers beside the project's own switch for each.
        admin = users.is_admin(who) and not who.get("session")
        return self._json(rules.payload(name) | {"rev": rules.rev(name), "may_global": admin})

    def _get_global_rules(self):
        """GET /api/global-rules."""
        # Readable by anybody signed in, because it is the same text their
        # sessions are already handed. Hiding it would only make the Briefing
        # tab unable to say where a rule came from.
        return self._json({"rules": rules.globals_now(), "max": rules.MAX_RULES})

    def _get_preamble(self):
        """GET /api/preamble."""
        # What a session started here is handed, exactly: the Briefing tab
        # shows it so the block is a thing a person can read rather than
        # something that only exists inside a launcher. Readable by anyone
        # who can see the project: it is their own rules, roadmap and
        # bugs, already on the three tabs beside it.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # The asker's own reply style rides the block, as it does for the
        # session bb-tty starts for them.
        mine = prefs.all_for_user(users.uid_of(self._who())).get(name) or {}
        if q.get("topic"):
            # One topic of the briefing (R202), what bb help TOPIC prints.
            t = preamble.topic(name, q["topic"][0].strip().lower()[:40])
            if t is None:
                return self._json({"error": "no such topic"}, 404)
            return self._json({"project": name, "topic": q["topic"][0], "text": t})
        # The reader's own memories ride it as a Claude session of theirs gets them.
        return self._json(preamble.payload(name, reply=mine.get("reply") or "", asks=mine.get("asks") or "",
                                           uid=users.uid_of(self._who())))

    def _get_brief(self):
        """GET /api/brief: brief.view, the brief waiting in a project's tree
        and the one kept after it left, for a project this account sees."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(brief.view(name, users.uid_of(self._who())))

    def _brief(self, req):
        """POST /api/brief: the first Claude press's Build it and Start
        without it, and a session's take as it starts: brief.verb, behind the
        gates here."""
        name = field(req, "project")
        if self._not_project(name):
            return
        who = self._who() or {}
        # A take is a session starting on its own project; the dialog's two
        # change the project's tree, so they are asked of an account that
        # works on it.
        if field(req, "action") != "take" and self._readonly(name):
            return
        return self._json(*brief.verb(name, req, users.uid_of(who), who.get("name") or "somebody",
                                      bool(who.get("session"))))

    def _get_design(self):
        """GET /api/design: design.view, a project's design language, its
        pages and the vocabulary they are drawn from, for a project this
        account sees; a session reads it too, through bb design."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # ?show= is bb design's: the words rather than the record, so a
        # session prints what the tab shows and nothing is assembled twice.
        show = q.get("show", [""])[0]
        if show:
            text, err = design.text_for(name, show)
            return self._json({"error": err} if err else {"text": text}, 404 if err else 200)
        return self._json(design.view(name))

    def _design(self, req):
        """POST /api/design: a Design section's Save of the language and the
        pages, and the file written into the tree: design.verb, for an
        account that works on the project."""
        name = field(req, "project")
        if self._not_project(name) or self._readonly(name):
            return
        who = self._who() or {}
        req["mine"] = users.tmux_prefix(who)
        return self._json(*design.verb(name, req, who.get("name") or "somebody",
                                       bool(who.get("session"))))

    def _get_wiki(self):
        """GET /api/wiki: the project's wiki (wiki.view), or one page of it
        with ?page=, for an account that sees the project; a session reads
        it too, through bb wiki."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        no = wiki.hidden_for(name, bool((self._who() or {}).get("session")))
        if no:
            return self._json({"error": no}, 403)
        pg = q.get("page", [""])[0]
        if pg:
            try:
                return self._json(wiki.page(name, pg))
            except wiki.Refused as e:
                return self._json({"error": str(e)}, 404)
        return self._json(wiki.view(name))

    def _get_ci_runs(self):
        """GET /api/ci-runs: a project's runs on GitHub's own runners, or
        with ?run=N (0 the newest finished) that run's jobs and the end of
        each failed job's log (cilogs), for an account that sees the
        project; a session reads it through bb ci-log."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        run = q.get("run", [""])[0]
        if run and not run.isdigit():
            return self._json({"error": "a run is named by its number"}, 400)
        try:
            return self._json(cilogs.log(name, int(run)) if run else cilogs.runs(name))
        except cilogs.Refused as e:
            return self._json({"error": str(e)}, 409)

    def _get_ci_watch(self):
        """GET /api/ci-watch: what the last look at a project's CI found
        (ciwatch.read), for an account that sees the project."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(ciwatch.read(name))

    def _ci_watch(self, req):
        """POST /api/ci-watch: look at a project's CI now (ciwatch.look),
        for an account that sees the project; the answer is what it found."""
        name = field(req, "project")
        if self._not_project(name):
            return
        if not ciwatch.claim(name):
            return self._json({"error": "a look at this project's CI is already running"}, 409)
        try:
            return self._json(ciwatch.look(name))
        finally:
            ciwatch.release(name)

    def _get_wiki_export(self):
        """GET /api/wiki-export: the wiki as a zip of its Markdown pages,
        whether or not the project has a remote."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        no = wiki.hidden_for(name, bool((self._who() or {}).get("session")))
        if no:
            return self._json({"error": no}, 403)
        try:
            fname, data = wiki.export_zip(name)
        except wiki.Refused as e:
            return self._json({"error": str(e)}, 404)
        return self._attachment(fname, data, "application/zip")

    def _wiki(self, req):
        """POST /api/wiki: a page saved, removed or renamed, and the wiki
        pushed to or pulled from the forge's (wiki.verb), for an account
        that works on the project. A session's writes go through the
        project's dial, Agents may: Write the wiki."""
        name = field(req, "project")
        if self._not_project(name) or self._readonly(name):
            return
        who = self._who() or {}
        ident = users.git_identity(who, name) or {}
        author = {"name": ident.get("name") or who.get("name") or "somebody", "email": ident.get("email") or ""}
        return self._json(*wiki.verb(name, req, author, bool(who.get("session"))))

    def _get_codebase(self):
        """GET /api/codebase."""
        # What git tracks in the project, by language: the Briefing
        # tab's first section. Tracked files only, cached by commit.
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(codebase.payload(name))

    def _get_pending(self):
        """GET /api/pending."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(pending.payload(name))

    def _get_memory(self):
        """GET /api/memory."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        # Against what this account may see, like every read above it:
        # this one passed the name straight through (bug #68).
        if self._not_project(q.get("project", [""])[0]):
            return
        got = memory.payload(q.get("project", [""])[0], sessions_anywhere(),
                             home=home_for(users.uid_of(self._who())))
        return self._json(got if got is not None
                          else {"error": "not a project"}, 400 if got is None else 200)

    def _get_tests(self):
        """GET /api/tests."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(testreg.payload(name))

    def _get_bugs(self):
        """GET /api/bugs."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        return self._json(bugs.payload(name))

    def _get_pubkeys(self):
        """GET /api/pubkeys."""
        # The shielded agent's public halves, for the New project dialog:
        # picking one selects it for the clone, and showing it is how the
        # operator gets it onto GitHub's deploy-key page in the first
        # place. Public keys are the shareable part: nothing here can
        # reach the private material, by construction. `pat` rides along
        # so the dialogs can say whether a deploy key is optional (a PAT
        # covers https) or the only way a push can authenticate. The
        # dialog is an administrator's, and so is this.
        if self._refused("create"):
            return None
        # The forge catalog rides along rather than costing a fetch of its
        # own: the dialog that wants the keys is the dialog that wants the
        # list of hosts, and it is drawn once from one answer. `hosts` is
        # what the operator has already said their own servers run, so the
        # clone form knows not to ask a question it has the answer to.
        # ...and the directories a new project may not have, so the name
        # field can say before Create when its folder will be numbered (B63).
        return self._json({"keys": agent_keys(), "pat": gh_authed(),
                           "forges": forges.catalog(),
                           "hosts": forges.known(),
                           "dirs": registry.taken_dirs()})

    def _read_json(self):
        """The body, once. Read here rather than in each handler: doing it
        after dispatch is how the request stream ends up consumed twice or
        not at all. None means an answer was already sent."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
            most = MAX_BODY_FOR.get(self.path.partition("?")[0], MAX_BODY)
            if not 0 <= n <= most:
                self._json({"error": f"body too large: {n} bytes, and this takes {most}"}, 413)
                return None
            req = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            self._json({"error": "bad request"}, 400)
            return None
        if not isinstance(req, dict):
            self._json({"error": "bad request"}, 400)
            return None
        return req

    def _post(self):
        # Before the credential check, because there is nothing to check
        # against yet, and closed by its own effect the moment there is.
        if self.path.split("?")[0] == "/setup":
            return self._setup_post()
        if self.path.split("?")[0] == "/login":
            return self._login_post()
        if self.path.split("?")[0] == "/login/2fa":
            return self._mfa_post()
        if self.path.split("?")[0] == "/login/passkey":
            return self._mfa_passkey()
        if self.path.split("?")[0].startswith("/api/v1/agent/"):
            # Its own door, before the operator's: an agent carries a node
            # token, never the dashboard credential (docs/nodes.md §8: the
            # controller holds nothing that logs in anywhere, and a node
            # holds nothing that opens this page).
            return self._agent()
        if self.path.split("?")[0].startswith("/api/v1/device/"):
            # A person's device has a door of its own as an agent does: its
            # token never opens the dashboard, and the dashboard's credential
            # is not what an app carries (R272).
            return self._device()
        if self.path.split("?")[0] == "/api/csp-report":
            return self._csp_report()
        if not self._authed():
            return self._deny()
        if self._two_factor_gate(self.path.split("?")[0]):
            return None
        # The one body that is not JSON: an archive to start a project from,
        # streamed to the spool by projects.spool_archive. Its own door
        # before the JSON read, and its own cap: MAX_BODY is sized for a
        # form, and an upload is not read into memory at all.
        if self.path.split("?")[0] == "/api/upload-archive":
            return self._upload_archive()
        # ...and an installer's ISO for a VM host (R99), streamed the same way.
        if self.path.split("?")[0] == "/api/vms-iso-upload":
            return self._vms_iso_upload()
        req = self._read_json()
        if req is None:
            return None

        path = self.path.split("?")[0]
        # A feature this install switched off (R81): refused here, whatever
        # drew the button, with the install's own sentence.
        if why := featuresoff.refused("POST", path, req):
            return self._json({"error": why, "off": True}, 403)
        # Door 2, at the one funnel every mutation passes: when, who, what,
        # on what, with a parameter digest, never the parameters, which
        # carry tokens and env text. The principal is the signed-in account
        # (`user:<name>`), which is a string rather than a boolean precisely
        # so it could become one: OIDC later is a new way to fill it in, not
        # a new row shape. (Bug #16's caveat still applies, narrowed: anything
        # holding an account's credential writes as that account, because the
        # server cannot tell the person from the session they started.)
        if not NODES_OK:
            act = path + (":" + str(req["action"])[:40]
                          if isinstance(req.get("action"), str) else "")
            db.audit(self._principal(), act,
                        str(req.get("project") or req.get("name")
                            or req.get("id") or "")[:120], req)
        for how, route, name in POST_ROUTES:
            if (path == route) if how == "exact" else path.startswith(route):
                # What a write to the notebook or the settings means for the
                # sessions is recorded before its reply goes, not after: the
                # reply is what lets a session send its next prompt, and one
                # that overtook the record was told about its own write as
                # somebody else's (B290). So the reply is held until then.
                # A design rendered from a record (bb design file --from)
                # writes nothing, so it marks nothing seen.
                own = (any(path.startswith(r) for r in OWN_WRITE_ROUTES)
                       and not (path.startswith("/api/design") and req.get("action") == "render"))
                self._held = [] if own else None
                try:
                    out = getattr(self, name)(req)
                    if own:
                        # A session's own write to its project's notebook or
                        # settings is seen by it as it lands (session_seen_note).
                        # The token's own uid, as the hook reads it: uid_of answers
                        # "" for a session on purpose, and that is the per-account
                        # stores' rule, not this one's.
                        who = self._who() or {}
                        if who.get("session"):
                            session_mark_own(who["session"], who.get("uid") or "", who)
                        elif path.startswith("/api/memory") and _memory_written(req, self._held):
                            _mem_edited(field(req, "project"))
                finally:
                    held, self._held = self._held, None
                for obj, code, cookie in held or ():
                    self._json(obj, code, cookie=cookie)
                return out
        self._json({"error": "not found"}, 404)

    def _reset(self, req):
        """POST /api/reset: start over at onboarding (settings.reset), and the
        dashboard re-executes itself so the next page is Create the owner.
        The confirm word is the whole of the safety: this is an
        administrator typing "reset" into a red box."""
        if self._refused("controller"):
            return None
        if str(req.get("confirm") or "") != "reset":
            return self._json({"error": "type reset to confirm; nothing was changed"}, 400)
        # The nodes to un-enroll first (the operator, 12 Oct): each uninstalled
        # and retired before anything is moved, since the record of them is
        # what moves, and the reset follows once every one has reported.
        ids = [str(x) for x in (req.get("unenroll") or []) if isinstance(x, str)]
        if ids:
            with _reset_lock:
                if _reset_job.get("running"):
                    return self._json({"error": "a reset is already under way"}, 409)
                rows = nodes.reset_unenroll(self._principal(), ids, req.get("stores") is True)
                bad = [x for x in rows if x["error"]]
                if bad:
                    return self._json({"error": "; ".join(f"{x['name']}: {x['error']}" for x in bad),
                                       "nodes": rows}, 409)
                _reset_job.clear()
                _reset_job.update(running=True, nodes=rows, error="", started=time.time())
            threading.Thread(target=_reset_after, args=(self._principal(),), daemon=True).start()
            return self._json({"ok": True, "unenrolling": rows})
        r, status = settings.reset(STATE)
        if status != 200:
            return self._json(r, status)
        print(f"dashboard: {self._principal()} reset this controller; the old state is in "
              f"{r['moved_to']}" + (f"; kept: {', '.join(r['kept'])}" if r["kept"] else ""), flush=True)
        threading.Timer(1.0, lambda: os.execv(sys.executable, [sys.executable, *sys.argv])).start()
        return self._json(r)

    def _settings_post(self, req):
        """POST /api/settings."""
        # The Settings tab's fields (R29): an administrator's, validated
        # and applied by the store; the answer is the tab's next drawing.
        if self._refused("controller"):
            return
        # The Debugging group (debug mode and what it opens) is the debug
        # grant's, named only (the operator, 6 Oct); only a change is asked.
        want = req.get("set") if isinstance(req.get("set"), dict) else {}
        if any(k in DEBUG_SETTINGS and want[k] != settings.get(k) for k in want) and self._refused("debug"):
            return
        # Finish on the setup page (R199): the first node is the one step
        # that cannot wait, so it is checked here and not only on the page.
        # Maintenance mode is the owner's alone: an administrator who switched
        # it on would be kept out by it.
        if ("maintenance_mode" in want and want["maintenance_mode"] != settings.get("maintenance_mode")
                and (users.account_of(self._who()) or {}).get("role") != "owner"):
            return self._json({"error": "only the owner switches maintenance mode"}, 403)
        # Turning it on ends everybody else's sessions and terminals (the
        # operator, 27 Oct): asked first, with each listed and what it is
        # doing, and ended once the owner says yes.
        ending = []
        if want.get("maintenance_mode") is True and not settings.get("maintenance_mode"):
            ending = others_sessions()
            if not req.get("confirmed"):
                return self._json({"error": "maintenance mode asks first", "confirm": "maintenance",
                                   "sessions": [{k: r[k] for k in ("who", "project", "what", "state", "node")}
                                                for r in ending]}, 409)
        if want.get("setup_done") is True and not settings.get("setup_done") and not setup_node():
            own = BARE_METAL and any(nodes.own_machine(n) and n.get("state") != "retired" for n in nodes.node_list())
            return self._json({"error": "this machine is still being set up as a node: Finish waits for it to "
                                        "answer" if own else
                               "enroll a node that runs sessions first: Finish needs one enrolled and "
                               "answering, and not hosting only"}, 409)
        r = settings.set_many(req.get("set") or {})
        if r.get("error"):
            return self._json(r, 400)
        if ending and settings.get("maintenance_mode"):
            end_others_sessions(ending)
            r["ended"] = len(ending)
        # The home tunnel follows its settings at once (R176): the process
        # started, restarted or stopped, and with an API token the hostname's
        # record and the tunnel's rules written; what happened rides back.
        # An app switched on is fetched, and one switched off dropped, now
        # rather than at the next daily look (R272 step 3).
        if any(k.startswith("apps_") for k in want):
            apps.check_now()
        if any(k in ("tls_mode", "tls_host", "tls_email") for k in want):
            # The connection as set now (R158 step 2): the install's own
            # certificate made for the hostname and the addresses the page
            # is reached at, or TLS off.
            r["tls"] = tls.apply(settings.get, names=_tls_names(self.headers.get("Host", "")))
        if any(k in TUNNEL_SETTINGS for k in want):
            r["tunnel"] = tunnel.apply()
            if settings.secret("cf_api_token") and settings.secret("tunnel_token") and settings.get("tunnel_host"):
                r["published"] = tunnel.publish(settings.secret("cf_api_token"))
        return self._json(r | settings.payload())

    def _prefs_post(self, req):
        """POST /api/prefs: a project's settings dialog, saved by
        prefs.dialog_save behind the gates here."""
        name = req.get("project", "")
        # A session may not change the settings of the project it runs
        # in (the gate that holds its own additions, the commands a
        # build runs, the identity its commits carry), and nobody may
        # change a project they cannot see or have not taken on.
        if (self._who() or {}).get("session"):
            return self._json({"error": "a project's settings are the operator's: "
                                        "say what should change in your reply"}, 403)
        if self._not_project(name):
            return
        if self._readonly(name):
            return None
        # Everything else in this dialog is the project's own; the node is
        # not, because a node is shared and moving a project onto one
        # reaches every other project there. Only a CHANGE is asked about
        # (B488): the dialog sends every field on every save.
        if ("node" in req or "nodes" in req) and prefs.node_changed(name, req) \
                and self._refused("node", name):
            return
        # A hosting-only node holds no project: its code and its sessions are
        # what the flag keeps off it (nodes.host_only).
        if ("node" in req or "nodes" in req) and not NODES_OK:
            want = (req.get("nodes") if isinstance(req.get("nodes"), list) else []) + [req.get("node") or ""]
            host = [(nodes.node(n) or {}).get("name") or n for n in want if n and nodes.host_only(n)]
            if host:
                return self._json({"error": f"{', '.join(host)} hosts containers only: no project's code "
                                            "or sessions go there. Send a container to it from the "
                                            "Containers page instead"}, 400)
            # A disabled node is kept but not offered (the operator, 11 Oct).
            off = [(nodes.node(n) or {}).get("name") or n for n in want
                   if n and (nodes.node(n) or {}).get("state") == "disabled"]
            if off:
                return self._json({"error": f"{', '.join(off)} is disabled on the Nodes page: Enable it there first"}, 400)
        # The hosting nodes its containers may also go to (prefs.hosts): a
        # node is shared, so naming one is for whoever may set the project's
        # node, and only a hosting-only node is one: a node that holds the
        # project is in its node set already. Only a change is asked about.
        if req.get("hosts") is not None and prefs.hosts_changed(name, req.get("hosts")):
            if self._refused("node", name):
                return
            if not NODES_OK:
                got = req.get("hosts") if isinstance(req.get("hosts"), list) else str(req.get("hosts")).split(",")
                bad = [(nodes.node(n) or {}).get("name") or n for n in got
                       if str(n).strip() and not nodes.host_only(str(n).strip())]
                if bad:
                    return self._json({"error": f"{', '.join(bad)} is not a hosting-only node: a node the "
                                                "project works on takes its containers already, from Nodes in its settings"}, 400)
        # Which other projects a session here may read is BuilderBot's
        # owner's alone (the operator, 6 Oct): it hands one project's sessions
        # another's code and notebook, which no administrator or user grants
        # on their own say. Only a change is asked about.
        if req.get("reads") is not None and prefs.reads_changed(name, req.get("reads")) \
                and (self._who() or {}).get("role") != "owner":
            return self._json({"error": "which other projects a project's sessions may read is set by "
                                        "BuilderBot's owner alone"}, 403)
        # ...and so are the places on it a session here is shown (sees): a
        # share on a node is every project's there, so naming one is for
        # whoever may set the node. Only a change is asked about.
        if req.get("sees") is not None and prefs.sees_changed(name, req.get("sees")) \
                and self._refused("node", name):
            return
        # ...and the addresses its sessions may still reach where the node
        # filters their network (the operator, 7 Oct): a hole in a shared
        # node's firewall that reaches past the project, so an
        # administrator's. The node hears it at once, since the sets it
        # fills are rebuilt live.
        reach = req.get("reaches") is not None and prefs.reaches_changed(name, req.get("reaches"))
        if reach and self._refused("nodes-write"):
            return
        # The node's own address is not one this opens: a session's traffic
        # to its own node is judged on the way in, where only the controller
        # and the resolvers pass, and its containers are reached as its own.
        if reach and not NODES_OK:
            ids = req.get("nodes") if isinstance(req.get("nodes"), list) else (prefs.get(name) or {}).get("nodes") or []
            addr_of = {n: str(((nodes.node(n) or {}).get("agent") or {}).get("addr") or "") for n in ids}
            got = req.get("reaches") if isinstance(req.get("reaches"), list) else str(req.get("reaches")).split(",")
            for e in (prefs._reach_entry(x) for x in got):
                on = e["nodes"] or ids
                own = [n for n in on if addr_of.get(n) and addr_of[n] == e["addr"].split(":")[0]]
                if own:
                    name_of = (nodes.node(own[0]) or {}).get("name") or own[0]
                    return self._json({"error": f"{e['addr']} is {name_of} itself: a session there reaches its "
                                                "node's containers as its own, and nothing else on its node"}, 400)
        # ...and what its sessions may read for debugging (the machine logs
        # of named nodes, the controller's diagnostics): the debug grant's,
        # per project rather than per node (the operator, 6 Oct).
        # Granted only where debug mode can be on at all (DEBUG_MODE=1); a
        # grant taken off is always allowed.
        if prefs.debug_changed(name, req) and not settings.debug_available() \
                and (req.get("diag") is True or req.get("log_from")):
            return self._json({"error": "the debug options are not available on this controller"}, 403)
        if prefs.debug_changed(name, req) and self._refused("debug"):
            return
        # ...nor is the dial that hands a session this project's container:
        # it lets a session create one and set its env, which is Docker
        # configuration, an administrator's (docker-write). Only a CHANGE is
        # asked about, since the dialog sends every field on every save.
        if req.get("devbuild") is not None \
                and str(req.get("devbuild")) != prefs.get(name)["devbuild"] \
                and self._refused("docker-write"):
            return
        # ...and the same of the VM dial and the VMs' limits (R91): a VM is a
        # machine on a node, the VMs area's to hand a session or to raise.
        if ((req.get("makevms") is not None and str(req.get("makevms")) != prefs.get(name)["makevms"])
                or (req.get("vm_caps") is not None and req.get("vm_caps") != prefs.get(name)["vm_caps"])) \
                and self._refused("vms-write", name):
            return
        held = (("node" in req or "nodes" in req) and prefs.node_changed(name, req)) \
            or (req.get("reads") is not None and prefs.reads_changed(name, req.get("reads")))
        # Then the rest: the project's own settings are the Project settings area's to
        # write (B19, the operator: Settings Write only); what is the asker's
        # own here (prefs.YOURS) is anybody's on the project, and a field
        # sent with the value it has is no change.
        if prefs.project_changes(name, req) and self._refused("settings", name):
            return None
        got = prefs.dialog_save(name, req, users.uid_of(self._who()))
        if reach and not got[0].get("error"):
            net_nudge()
        # A synced node that now holds this project (or stops) hears it at
        # once, so its first copy starts and the Claude button follows it.
        if held and not got[0].get("error") and not NODES_OK:
            wssync.held_changed()
        return self._json(*got)

    def _nodes(self, req):
        """The Nodes page's verbs. Thin on purpose: an administrator's, and
        nodes.verb says what each one means and writes its audit row.

        Each held to the instance it touches (R260): a node's verbs to Nodes
        Write on that node, and making one (add, the VM's XML) to Nodes
        Write on every node; a runner's to CI runner Write on that runner,
        a new one to it on every runner. A runner is a person's to change,
        as the node verbs it used to be gated with are."""
        me, act, nid = self._who() or {}, field(req, "action"), field(req, "id")
        nname = ((nodes.node(nid) or {}).get("name") or nid) if nid and not NODES_OK else nid
        if act in ("runner", "runner-token", "runner-forget"):
            slot = (nodes.runner_slot(field(req, "url").strip()) if act == "runner-token"
                    else re.sub(r"[^a-z0-9.-]", "", field(req, "slot"))[:60])
            have = {r["slot"] for r in runners.listing() if r["id"] == nid} if not NODES_OK else set()
            why = (users.may(me, "nodes-write") if me.get("session") else "") or users.may_instance(
                me, "runner", f"{nid}/{slot}" if slot in have else "", f"{slot} on {nname}")
        else:
            why = users.may_instance(me, "nodes-write", "" if act in ("add", "vm-xml") else nid, nname)
        if why:
            return self._json({"error": why}, 403)
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        # The release check, now (R90 step 5): the newest published release
        # read again, for the Updates section's Check now.
        if act == "release-check":
            return self._json({"ok": True, **releasecheck.check()})
        # A held start lifted, or the next one armed (R56 step 9).
        if act == "start-held":
            r = held.start(self._principal())
            if r.get("ok") and not r.get("note"):
                db.audit(self._principal(), "start-held", "", {})
            return self._json(r, 400 if r.get("error") else 200)
        if act == "hold-next":
            return self._json(held.arm_next(req.get("on") is not False))
        got = nodes.verb(self._principal(), req)
        # A node that left is a node the Doctor's cached verdict may still
        # name, for up to its half hour: the next run starts now, on its own
        # thread, so the card stops saying a daemon nobody can reach (B710).
        if req.get("action") in ("retire", "discard", "uninstall") and isinstance(got[0], dict) and got[0].get("ok"):
            threading.Thread(target=doctor.refresh, name="doctor-after-node", daemon=True).start()
        return self._json(*got)

    def _jobs(self, req):
        """The Jobs page's one verb, and where `bb run`, `bb build`, `bb test`
        and `bb emu` land from the controller (nodes.run_job). A queued job
        is ended; a running one is flagged and its runner told, and the row
        moves when the runner reports that it stopped, which is when it
        did."""
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        act = field(req, "action")
        if act in ("run", "emu"):
            # Never from a session (R35). A session is on its project's node and
            # runs these verbs where it is, inside its view; a job runs as the
            # node's enrolled account, outside every view and in the docker
            # group, so a session token that could queue one would read every
            # project on the machine and be root on it. Measured on
            # bb-dev-sandbox, 16 Sep, before this refusal.
            if (self._who() or {}).get("session"):
                return self._json({"error": "a session runs bb run, build, test and emu where it "
                                            "is, on its project's node; a job would run outside "
                                            "the session's view, so a session cannot queue one"}, 403)
            # ...nor from an account without the right: the same job queued with
            # a password instead of a token is the same command in the same
            # docker group. Nothing on the page queues one for a plain user; bb
            # on the controller does, for an administrator.
            if (why := users.may(self._who(), "jobs")):
                return self._json({"error": why}, 403)
            name = field(req, "project")
            if name not in set(project_names(self._who())):
                return self._json({"error": "not a project"}, 400)
            # ...and by grant on the node the job would run on (R137 step
            # 3): the one named, else the project's primary, as run_job
            # picks it.
            pf = prefs.get(name) or {}
            on = field(req, "node") or pf.get("node") or (pf.get("nodes") or [""])[0]
            if (why := users.may_node(self._who(), "jobs", on)):
                return self._json({"error": why}, 403)
            return self._json(*nodes.run_job(name, req, self._principal()))
        if act != "cancel":
            return self._json({"error": "unknown action"}, 400)
        # Whose it is, the way the read is scoped: an account cancels the
        # jobs of its projects and a session its own project's; a stranger's
        # job and a missing one answer alike.
        me = self._who()
        mine = None if users.may(me, "admin") == "" else set(project_names(me))
        if mine is not None:
            j = nodes.job(field(req, "id"), with_log=False)
            if not j or j.get("project") not in mine:
                return self._json({"error": "no such job of yours"}, 403)
        return self._result(jobs.cancel(self._principal(), field(req, "id")))

    def _claude_login(self, req):
        """A node saying what this account is signed in to Claude, or another
        coding agent, AS there (R47), or that it is not: never the login itself, which stays on the
        machine that made it (claudegrant.py says why).

        Only a session token minted FOR an account speaks here (the one the
        terminal proxy stamps into a node-bound terminal's URL, or the one a
        sign-in job carries), and only for that account: the account is in
        the token, signed, not in a parameter. Which node is reporting is
        not taken from the request either: a sign-in job's token names the
        node it was queued on, and a session's names a project, whose node
        it is on. A machine that could name itself could report for another.
        """
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        uid = me.get("uid") if me.get("session") else ""
        if not uid:
            return self._json({"error": "a Claude sign-in is reported with a session token "
                                        "minted for an account, the one a node-bound "
                                        "terminal carries"}, 403)
        proj = me.get("session") or ""
        if proj.startswith("node:"):
            nid = proj[5:] if nodes.node(proj[5:]) else ""
        else:
            # The node this session was started on, which the project's
            # other nodes make a question (R82): named by the session, and
            # believed only when it is one of the project's own.
            p = prefs.get(proj) or {} if proj else {}
            asked = field(req, "node")
            nid = asked if asked and asked in [p.get("node"), *(p.get("nodes") or [])] else p.get("node") or ""
        if not nid:
            return self._json({"error": "a sign-in is reported by a session on the "
                                        "node it happened on"}, 400)
        # ...and the other coding agents' beside Claude's (R95 step 3): the
        # same report, said from the same check, kept in their own record.
        agent = str(req.get("agent") or "claude")
        if agent != "claude" and not any(a.id == agent and a.login_job for a in agents.TABLE):
            return self._json({"error": f"no coding agent called '{agent[:20]}' signs in"}, 400)
        signed_in = bool(req.get("signed_in", True))
        if not signed_in and claudegrant.on(home_for(uid), nid, agent):
            # Said in the log, as the heartbeat's sign-out is (B236): which
            # session's check took a login away is not on the page.
            print(f"[dashboard] {nid} reports {agent} signed out for {uid}, "
                  f"from a check in {proj or 'no project'}", flush=True)
        r = claudegrant.report(home_for(uid), nid, req.get("email") or "", req.get("plan") or "",
                               signed_in=signed_in, agent=agent)
        return self._json(r, 400 if r.get("error") else 200)

    def _tty_grant(self, req):
        """Whose terminal a node's bb-tty is about to start, answered here
        (B166).

        On this container /termws is the one way in, so the account
        _scoped_arg stamps is the account that proved itself. On a node,
        bb-session tty and bb-tty can be started by any process on the
        machine with whatever words it likes, which bb-tty would have
        believed. So on a node bb-tty asks this, with
        the token that rode in on the URL, and takes the account, its name
        and whether it is the owner from the answer and never from the URL.

        The token is the proof. It is signed with a key only this container
        holds, names one project and one account, and expires; the proxy
        mints a fresh one for every terminal it relays. What is asked of it
        is what the proxy asked before relaying: the project the terminal is
        for is the token's, the account is still there and may open it
        (_term_refused, _claude_held), and a writable terminal is for an
        account with a shell, since the proxy sends everybody else to the
        read-only twin. A session holding its own token can therefore open
        what its own account could open through the proxy, and nothing else.
        """
        who = self._who() or {}
        if not who.get("session") or not users.uid_of(who):
            return self._json({"error": "a terminal on a node is granted to a session token "
                                        "minted for an account, and this is not one"}, 403)
        me = users.account_of(who)
        if me is who or not me.get("uid"):
            return self._json({"error": "the account this token was minted for is gone"}, 403)
        arg = str(req.get("arg") or "")
        if _ARG_OWNER.match(arg):
            return self._json({"error": "the argument names its account, which is this "
                                        "answer's to say"}, 400)
        project = _arg_project(arg)
        if not project or project != who["session"]:
            return self._json({"error": f"this token is for {who['session']}, and the terminal "
                                        f"asked for is {'for ' + project if project else 'not a project'}"},
                              403)
        rest = "/?arg=" + urllib.parse.quote(arg, safe="")
        refused = self._term_refused(rest, me) or self._claude_held(rest, me)
        if refused:
            return self._json({"error": refused}, 403)
        # A log (R133 step 12) runs nothing anybody types into: reading it
        # wants the log's own grant, decided above, not a shell.
        if not req.get("ro") and not arg.startswith("log:") and users.may(me, "terminal"):
            return self._json({"error": f"{me['name']} has no shell, so this terminal is the "
                                        "read-only one"}, 403)
        # A coding agent's session on a repository of a project of several
        # (R136 step 4) works in every repository of it: the others, each
        # with a token of its own for the account, so bb in that tree
        # answers for that repository as it would in a session of its own.
        works, tokens = [], {}
        if agents.of_arg(arg)[0] is not None and repos.project_of(project):
            works = [m for m in repos.members(repos.project_of(project)) if m != project and (WORKSPACE / m).is_dir()]
            tokens = {m: users.mint_session(m, uid=me["uid"]) for m in works}
        # ...and the projects this one reads, for the view bb-session builds
        # (their trees read-only) and the walls bb-tty gives Claude; and the
        # places on its node it is shown, which the view otherwise leaves out.
        return self._json({"uid": me["uid"], "name": me["name"], "project": project,
                           "owner": me.get("role") == "owner",
                           "works": works, "tokens": tokens,
                           "reads": [r for r in prefs.reads_trees(project) if (WORKSPACE / r).is_dir() and r not in works],
                           "sees": (prefs.get(project) or {}).get("sees") or [],
                           # Whether it may compute on its node's NVIDIA card
                           # (R102): "on", or who said no, the node or the
                           # project, which bb gpu then says to the session.
                           "gpu": gpu_for(project, _arg_node(arg)),
                           # Whether its Gradle builds on the node's disk (B439).
                           "build_local": (prefs.get(project) or {}).get("build_local", True),
                           # Which node this terminal is on, by id: what a
                           # session there names when it reports its Claude
                           # sign-in, since a project may work on several.
                           "node": _arg_node(arg) or (prefs.get(project) or {}).get("node") or "",
                           # The container a ctr: terminal goes into, checked
                           # above against its instance's running ones: what
                           # bb-tty execs into, never the URL's word for it.
                           "ctr": (_ARG_CTR.match(arg).group(3) if _ARG_CTR.match(arg)
                                   else _ARG_LOGCTR.match(arg).group(3) if _ARG_LOGCTR.match(arg) else ""),
                           # ...and the VM a vm: console opens (R91): its libvirt
                           # name from the record, never the URL's word for it.
                           "vm": (vm_target(*_ARG_VM.match(arg).groups()).get("domain", "")
                                  if _ARG_VM.match(arg) else "")})

    def _hook(self, req):
        """What a session's hooks have to say, from a NODE (roadmap #24):
        hooks.py says what each kind means. The account is the token's,
        never the request's: a session token minted for a node-bound
        terminal names its account, and that is who the note is filed under
        and who the feed says asked."""
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        uid = me.get("uid") if me.get("session") else ""
        project = me.get("session") or ""
        if not uid or not project:
            return self._json({"error": "a hook posts with a session token minted for an "
                                        "account, the one a node-bound terminal carries"}, 403)
        return self._json(*hooks.verb(field(req, "kind"), req, me, uid, project))

    def _bb_relay(self, req):
        """A bb verb from a session on a NODE, run here (roadmap #24). The
        door: a signed-in caller, and the account's `bb` right on the
        project. Which words travel, whose project a token names and what a
        session may push are bbrelay.py's."""
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        project, no = bbrelay.admit(me, req)
        if no:
            return self._json(*no)
        if self._refused("bb", project):
            return None
        # A session's bb bug add, bb rules add or bb settings set is its own
        # write like one through the notebook's routes, and was told to it
        # on its next prompt as somebody else's (B375): what moved across
        # the verb is marked seen for the session that ran it.
        before = _seen_now(project, me) if me.get("session") else None
        out = bbrelay.run(me, req, project)
        # What a relayed verb changed in the controller's copy reaches the
        # project's synced nodes now, and the session's bb waits for its own
        # copy to reach this revision before it goes on (R163, syncwait.py).
        argv0 = (req.get("argv") or [""])[0] if isinstance(req.get("argv"), list) else ""
        if argv0 in ("git", "version", "changelog") and out[1] == 200 and isinstance(out[0], dict) \
                and _sync_bound(project):
            wssync.changed(project)
            out = (out[0] | {"sync_rev": wssync.rev_of(project)}, out[1])
        if before is not None:
            session_mark_own(project, me.get("uid") or "", me, since=before)
        return self._json(*out)

    def _agent(self):
        """The node agent's door (docs/nodes.md §4): channel.py says what each
        verb means. What stays here is the HTTP: the node's token from the
        Authorization header, a file streamed, a body read, and the
        long-poll's empty answer."""
        if NODES_OK:
            return self._json({"error": "the node store did not open: "
                                        + NODES_OK}, 500)
        verb = self.path.split("?")[0][len("/api/v1/agent/"):]
        hdr = self.headers.get("Authorization", "")
        bearer = hdr[7:] if hdr.startswith("Bearer ") else ""
        auth = nodes.authenticate(bearer) if bearer else {"error": "no token"}
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        # A hosting-only node (nodes.host_only) is held to what running the
        # containers sent to it needs, before any verb is read: nothing of
        # it comes back otherwise, and asking is audited.
        if auth.get("kind") == "node":
            why = nodes.host_refuses(auth["node"], verb, q.get("what", [""])[0] if verb == "download" else "")
            if why:
                # Audited once an hour a node and verb, so a verb asked on a
                # loop does not fill the log.
                said = nodes.host_refused_audit(auth["node"], verb, time.monotonic())
                if said:
                    db.audit(f"node:{auth['node']}", "host-refused", said, {})
                return self._json({"error": why}, 403)
            if nodes.host_only(auth["node"]):
                # A public box's request that stalls is let go rather than
                # holding a thread, and its hellos are counted (R92).
                self.connection.settimeout(120)
                if verb == "hello" and not nodes.host_hello_allowed(auth["node"], time.monotonic()):
                    return self._json({"error": "too many hellos: one in a while is enough"}, 429)
        # The verbs that serve or take a FILE, on any method.
        if verb in ("source", "file", "download", "iso"):
            got, status = channel.fetch(verb, auth, q, authed=self._authed)
            if status != 200:
                return self._json(got, status)
            return self._send_file(got)
        if verb in ("artifact", "sync-put", "claude-put", "devimage-put", "devdata-put", "signing-put", "scan-put"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if verb == "sync-put":
                return self._json(*channel.sync_put(auth, q, self.rfile, length))
            if verb == "claude-put":
                return self._json(*channel.claude_put(auth, q, self.rfile, length))
            if verb == "devimage-put":
                return self._json(*channel.devimage_put(auth, q, self.rfile, length))
            if verb == "devdata-put":
                return self._json(*channel.devdata_put(auth, q, self.rfile, length))
            if verb == "signing-put":
                return self._json(*channel.signing_put(auth, q, self.rfile, length))
            if verb == "scan-put":
                return self._json(*channel.scan_put(auth, q, self.rfile, length))
            return self._json(*channel.artifact(auth, q, self.rfile, length))
        if verb in ("sync-file", "sync-tar", "claude-file", "devimage", "devdata"):
            got, status = {"sync-file": channel.sync_file, "sync-tar": channel.sync_tar,
                           "claude-file": channel.claude_file, "devimage": channel.devimage_file,
                           "devdata": channel.devdata_file}[verb](auth, q)
            if status != 200:
                return self._json(got, status)
            return self._send_file(got)
        if self.command != "POST":
            return self._json({"error": "POST"}, 405)
        req = self._read_json()
        if req is None:
            return None
        if auth.get("error"):
            return self._json({"error": auth["error"]}, 401)
        # Where the node is, as seen from here: informational on the row,
        # and the address docker-over-ssh goes to for an agent node (see
        # nodes._addr). A proxy in front says so in the usual header, whose
        # last hop is the one the proxy wrote: the first is the client's own
        # word, and a node that named a LAN address there was let into it (R92).
        addr = (self.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
                or self.client_address[0])
        if verb == "work":
            got = channel.work(auth, req, addr, alive=lambda: not client_gone(self.connection))
            if got is None:
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            return self._json(*got)
        return self._json(*channel.verb(verb, auth, req, addr))

    def _device(self):
        """A person's device's door (R272, devices.py says what each verb
        means): its token from the Authorization header, or for sign-in the
        person's name and password once, which mints that token. What stays
        here is the HTTP, as for the agent's door."""
        if NODES_OK:
            return self._json({"error": "the store did not open: " + NODES_OK}, 500)
        verb = self.path.split("?")[0][len("/api/v1/device/"):]
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        if why := featuresoff.refused(self.command, "/api/v1/device/" + verb):
            return self._json({"error": why, "off": True}, 403)
        # An app from before a break in the door is told so, whatever it
        # asked; except where it asks what to update to.
        if ((why := devices.door_refused(self.headers.get("X-BB-Door"), self.headers.get("X-BB-App")))
                and verb not in ("apps", "app-file")):
            return self._json({"error": why, "update": True}, 426)
        if verb == "signin":
            if self.command != "POST":
                return self._json({"error": "POST"}, 405)
            req = self._read_json()
            if req is None:
                return None
            u = users.authenticate(str(req.get("username") or ""), str(req.get("password") or ""))
            if not u:
                # As the sign-in page: a beat of delay, and not saying which half.
                time.sleep(0.5)
                return self._json({"error": "wrong username or password"}, 401)
            if kept_out(u):
                return self._json({"error": MAINTENANCE_SAID, "maintenance": True}, 503)
            # An app is signed in past the second factor too (R127): a code
            # from the authenticator or a recovery code beside the password.
            if mfa.enabled(u["uid"]):
                keys = self._mfa_keys(u)
                if (left := mfa.held(*keys)):
                    return self._json({"error": f"too many wrong codes: try again in {max(1, left // 60)} minutes"}, 429)
                code = str(req.get("code") or "").strip()
                if not code:
                    return self._json({"error": "this account has two-factor sign-in: add the code your "
                                                "authenticator app shows, or a recovery code", "second_factor": True}, 401)
                if not (mfa.totp_check(u["uid"], code) or mfa.recovery_use(u["uid"], code)):
                    time.sleep(0.5 + mfa.missed(*keys))
                    db.audit(f"user:{u['name']}", "2fa-wrong", u["name"], {"addr": self.client_address[0], "app": True})
                    return self._json({"error": "that code is not right", "second_factor": True}, 401)
                mfa.cleared(keys[0])
                db.audit(f"user:{u['name']}", "2fa-signin", u["name"], {"app": True})
            row, got = devices.mint_for(u, req.get("name"), str(req.get("kind") or "pc"))
            if not row:
                return self._json(got, 400)
            users.touch(u["name"])
            return self._json({**got, "device": row, "account": u["name"]})
        hdr = self.headers.get("Authorization", "")
        auth = devices.authenticate(hdr[7:]) if hdr.startswith("Bearer ") else {"error": "no token"}
        # A phone or a PC signed in as somebody else waits out maintenance
        # mode; what to update to is still answered.
        if verb not in ("apps", "app-file") and not auth.get("error") and kept_out(auth.get("account")):
            return self._json({"error": MAINTENANCE_SAID, "maintenance": True}, 503)
        if verb in ("sync-file", "sync-tar", "app-file"):
            got, status = devices.file_verb(verb, auth, q)
            return self._send_file(got) if status == 200 else self._json(got, status)
        if verb == "sync-put":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            return self._json(*devices.put(auth, q, self.rfile, length))
        if self.command != "POST":
            return self._json({"error": "POST"}, 405)
        req = self._read_json()
        if req is None:
            return None
        return self._json(*devices.verb(verb, auth, req))

    def _send_file(self, got):
        """A file the agent fetches, from a path or from bytes, never cached:
        channel.fetch's answer."""
        self.send_response(200)
        self.send_header("Content-Type", got["ctype"])
        self.send_header("Cache-Control", "no-store")
        for k, v in got["headers"].items():
            self.send_header(k, v)
        if "stream" in got:
            # Written as it is made, ended by closing the connection: this
            # server speaks HTTP/1.0, one request a connection (a synced
            # project's first copy, R163).
            self.end_headers()
            got["stream"](self.wfile)
        elif "path" in got:
            size = got["path"].stat().st_size
            self.send_header("Content-Length", str(size))
            self.end_headers()
            # Exactly what was promised: a transcript may grow while it is
            # sent (B613), and bytes past the length would be the next
            # response's to a client that reuses nothing but reads them.
            with open(got["path"], "rb") as f:
                while size > 0:
                    chunk = f.read(min(1 << 20, size))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    size -= len(chunk)
        else:
            self.send_header("Content-Length", str(len(got["body"])))
            self.end_headers()
            self.wfile.write(got["body"])
        return None

    def _signin_agent(self, req):
        """The coding agent a sign-in or a sign-out is for (R95 step 3):
        Claude when none is named, and only one with a sign-in of its own."""
        a = agents.get(field(req, "agent") or "claude")
        return a if a and a.login_job else None

    def _signin_node(self, req):
        """(node id, refusal) for a sign-in or a sign-out: a person's, never
        a session's, on a node this account may look at, which for an
        account that does not administer is one its own projects work on."""
        me = self._who() or {}
        if me.get("session"):
            return "", ({"error": "a session does not sign an account in or out"}, 403)
        if not self._signin_agent(req):
            return "", ({"error": "no such coding agent, or one with no sign-in of its own"}, 400)
        nid = field(req, "node")
        if not nid:
            return "", ({"error": "which node? A sign-in is made on one node, "
                                  "from its Agents page"}, 400)
        nid, why = self._node_asked(nid)
        if why:
            return "", ({"error": why}, 403)
        return nid, None

    def _signin(self, req):
        """Start a sign-in on one node, or stop the one that is running:
        signin.verb. Another account's flow is not this one's to replace or
        stop (the review of 26 Sep)."""
        me = self._who() or {}
        uid = users.uid_of(me)
        if signin.owner() not in ("", uid) and signin.state()["running"]:
            return self._json({"error": "another account is signing in right now: "
                                        "one sign-in at a time, so try again in a minute"}, 409)
        if field(req, "action") == "cancel":
            if me.get("session"):
                return self._json({"error": "a session does not sign an account in or out"}, 403)
            return self._json(*signin.verb("cancel", "", uid))
        nid, no = self._signin_node(req)
        if no:
            return self._json(*no)
        return self._json(*signin.verb("", nid, uid, self._signin_agent(req).id))

    def _login_code(self, req):
        """Hand the code from the browser to the sign-in flow: signin.take_code,
        for the person whose flow it is."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session does not sign an account in or out"}, 403)
        if signin.owner() != users.uid_of(me):
            return self._json({"error": "no sign-in of yours is running"}, 403)
        return self._json(*signin.take_code(field(req, "code")))

    def _signout(self, req):
        """Sign this account out of a coding agent on one node
        (signin.sign_out): the login is that machine's, so that machine lets
        go of it."""
        nid, no = self._signin_node(req)
        if no:
            return self._json(*no)
        agent = self._signin_agent(req)
        # Not while a conversation of THIS account's is running there.
        # Signing out pulls the ground from under the sessions it started,
        # and a page that has not polled for fifteen seconds can offer a
        # button the answer has moved past, so the refusal is here as well
        # as on the button. Theirs, and on this node: one person signing out
        # does nothing to somebody else's conversation, or to their own on
        # another machine.
        me = users.uid_of(self._who())
        busy = sorted(x["name"] for x in node_tmux_sessions()
                      if x.get("node_id") == nid
                      and agents.of_session(tmux_base(x["name"]))[0] is agent
                      and (tmux_owner(x["name"]) or users.uid_of(
                          users.get(users.owner_name() or ""))) == me)
        if busy:
            # Said as projects, not tmux names: "u_3deb3420~claude-hello"
            # named nothing a person recognizes, and every one listed is
            # the asker's own.
            projs = sorted({agents.of_session(tmux_base(n))[1] for n in busy})
            return self._json({"error": f"end your {agent.name} session"
                               + ("s" if len(projs) > 1 else "") + " on "
                               + ", ".join(projs) + " first (Sessions, or the tab's Close)"}, 409)
        payload, status = signin.sign_out(nid, me, agent.id)
        if status == 200:
            # The row says so at once; the node's own report, which the job
            # prompts, is what keeps it true.
            claudegrant.report(home_for(me), nid, "", signed_in=False, agent=agent.id)
        return self._json(payload, status)

    def _roadmap(self, req):
        """Add, send, edit or drop one item on a project's list: roadmap.verb
        says what each action means.

        The project is checked against the real list for the same reason every
        other endpoint here does it: a name that came back off the filesystem
        cannot name something that was never there.
        """
        name = field(req, "project")
        if self._not_project(name):
            return
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if field(req, "action") not in ("history", "finished") and self._readonly(name):
            return None
        act = field(req, "action")
        # "send" is a write to the roadmap (it marks a step sent) and starts a
        # session's turn, so it goes with the rest.
        if (bad := projects.locked_out(name, users.uid_of(self._who()))):
            return self._json(bad, 409)
        # Closing a batch its session will never close (B198) is an
        # administrator's, like the other decisions about other people's work.
        if act == "batch-close" and self._refused("settings", name):
            return
        return self._json(*roadmap.verb(name, act, req, self._who() or {}, live=sessions_anywhere(),
                                        prefix=users.tmux_prefix(self._who())))

    def _phone_payload(self, node="", probe=False):
        """The Phone page's data as this request reads it: who is asking, the
        nodes they may see (_node_scope) and this browser's own address and
        kind, which phone.tab_view decides whether to offer."""
        return phone.tab_view(users.uid_of(self._who()), admin=users.is_admin(self._who()),
                              project=(self._who() or {}).get("session") or "",
                              node=node, probe=probe, scope=self._node_scope(),
                              ua=self.headers.get("User-Agent", ""),
                              addr=self.client_address[0] if self.client_address else "",
                              who=self._who())

    def _reads(self, project):
        """Whether this session may read `project`: one its project reads
        (prefs.reads), the same answer the notebook's reads get."""
        me = self._who() or {}
        return bool(me.get("session")) and project in (me.get("reads") or []) \
            and not users.may(me, "read", project)

    def _docker_ctl(self, req):
        """Start, stop, restart or read the log of ONE container on a node.

        Any container on that daemon, which is the point: the operator asked
        for a manager rather than a list of what BuilderBot made, and what
        makes that acceptable is the same thing that makes the rest of this
        acceptable, namely that the daemon belongs to a machine whose only job
        is running containers (R68 steps 1 and 2).

        An administrator's, like every other docker write here, and the log
        with them: a container's log is whatever it decided to print, which
        on somebody else's container is not a thing to hand out by role.

        The one exception is a SESSION, on a container that belongs to its
        project (the operator, 24 Sep): containers.session_verb says what it
        may do with one.
        """
        me = self._who() or {}
        sess = me.get("session") or ""
        act, name = field(req, "action"), field(req, "container")
        if sess:
            # The log of a container that belongs to a project this session
            # reads is a read (B551); everything else is its own project's.
            proj = field(req, "project")
            if act == "logs" and proj and proj != sess and self._reads(proj):
                return self._json(*containers.session_verb(proj, me, act, name, req, read_only=True))
            return self._json(*containers.session_verb(sess, me, act, name, req))
        if self._refused("docker-write"):
            return
        nid, why = self._node_asked(field(req, "node"))
        if why:
            return self._json({"error": why}, 400)
        # Which project it belongs to: one of them, or none.
        under = field(req, "owner")
        if act == "owner" and under and under not in set(project_names(me)):
            return self._json({"error": f"no project called {under}"}, 400)
        # Onto the LAN (R178) opens a way out of the wall around a project's
        # containers: an administrator's, as the node's own switches are.
        if act in containers.LAN_CTL and not users.is_admin(me):
            return self._json({"error": "letting a container reach the network around its node is an administrator's"}, 403)
        # A project's container is worked on by the people on that project,
        # an administrator as much as anyone (R274): one not on it adds it to
        # their own list first. System's and nobody's stay an administrator's.
        # The owner's check and the act read the daemon's list once between
        # them (devapp.one_listing): Start on boot read it twice first.
        with devapp.one_listing():
            if act != "prune":
                with devapp.on_node(nid or None):
                    owner = containers.owner_named(name)
                if why := self._not_on_list(me, owner):
                    return self._json({"error": why}, 403)
            return self._json(*containers.admin_verb(act, name, nid, under))

    def _not_on_list(self, me, owner):
        """Why `me` may not act on a container of project `owner`, or "":
        the project list's seatbelt (users.may_work), which an administrator
        wears too (R274). A container of no project, of System, or of a
        project gone to the trash asks nothing of it."""
        if not owner or owner == devapp.SYSTEM or not registry.is_project(owner) or users.may_work(me, owner):
            return ""
        return (f"{registry.label(owner)} is not on your list of projects: "
                "add it to your own list on the Users page to work on its containers")

    def _container(self, req):
        """A container from a compose file written here, with no project:
        containers.tab_verb.

        Its own endpoint rather than an action on _devapp, because _devapp
        starts by insisting the caller names a project and this one has none:
        that is the whole of what it is.

        An administrator's, like every other write here that is configuration
        rather than a run of the code. It was the page alone that knew that
        (mayDocker hides the buttons), and a hidden button is not a refusal:
        writing a compose file and building from it is root-shaped power on
        the node, so the endpoint says no itself.
        """
        if self._refused("docker-write"):
            return
        return self._json(*containers.tab_verb(
            field(req, "action"), field(req, "name"), req,
            seen=lambda: project_names(self._who())))

    def _logs(self, req):
        """The log policy, and the two things that can be done to the pile:
        logs.verb. An administrator's."""
        if self._refused("controller"):
            return
        return self._json(*logs.verb(field(req, "action"), req))

    def _idle(self, req):
        """The idle rule for every agent's sessions (idle.py): minutes, 0 for never.
        Operator-only, like the log policy beside it."""
        if self._refused("controller"):
            return
        r = idle.set_minutes(req.get("minutes"))
        return self._result(r)

    def _paths(self, req):
        """Where the controller keeps one kind of what grows (paths.py), and
        what is there moved across. An administrator's, never a session's:
        it is this machine's disks."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "the controller's storage is the operator's"}, 403)
        if self._refused("controller"):
            return
        name = field(req, "name")
        r = paths.set_path(name, field(req, "path"))
        if r.get("ok"):
            db.audit(self._principal(), "paths", name, {"path": field(req, "path"), "moving": r.get("moving")})
        return self._result(r)

    def _devapp(self, req):
        """The dev-instance controls: the Containers page's buttons, and `bb devapp`
        from a session. Who may press which is decided below, by the verb, by
        whose the container is and by its project's Run its container."""
        me = self._who() or {}
        sess = me.get("session") or ""
        # Named as the Docker tab lists it, for one that is not the caller's
        # own project's: a container written here, or another project's
        # instance that belongs to this one (bb devapp --container NAME).
        ctr = field(req, "container")
        if ctr:
            row = devapp.row_named(ctr)
            if not row:
                return self._json({"error": f"no container called {ctr} on record here"}, 400)
            req["project"], req["instance"] = row
        name = field(req, "project")
        # A project, OR a container written here, which is not a project and
        # never will be, but carries every one of these controls. Checked
        # against the store rather than waved through: this name reaches a
        # compose call and a data directory either way.
        if name not in set(project_names(me)) \
                and name not in containers.overview_names():
            return self._json({"error": f"not a project or container: {name}"}, 400)
        act = field(req, "action")
        # The verb onto this request's trace row (B717): a POST keyed by its
        # path alone could not say which devapp action was the slow one.
        self.trace_extra = f"action={act}" if isinstance(act, str) and act.replace("-", "").isalnum() else ""
        # WHOSE IT IS, before anything else is asked: an account that is not
        # an administrator reaches what belongs to its projects, and a
        # session what belongs to its own one (the operator, 24 Sep). The
        # same answer a stranger's container gets, whatever the verb, so a
        # session cannot learn by asking what another project runs.
        if not users.is_admin(me):
            want = field(req, "instance") or (devapp.send_name(name, field(req, "compose")) if act == "new"
                                              else devapp.only_instance(name))
            owner = devapp.owner_of(name, want)
            # ...and a session reads what belongs to a project its own reads
            # (B551): the state and the starter env, never a change.
            reads = {owner} if sess and act in ("state", "starter", "probe") and owner and self._reads(owner) else set()
            if owner not in ({sess} | reads if sess else set(project_names(me))):
                return self._json({"error": containers.not_ours(devapp.pname(name, want), sess)}, 403)
        # ...and an administrator sees every project's and changes those on
        # their own list (R274); reading one is everybody's.
        elif act not in ("starter", "state", "probe"):
            want = field(req, "instance") or (devapp.send_name(name, field(req, "compose")) if act == "new"
                                              else devapp.only_instance(name))
            if why := self._not_on_list(me, devapp.owner_of(name, want)):
                return self._json({"error": why}, 403)
        # Reading is everybody's; changing what is running is not (roadmap
        # #27). Named, not derived from the verb: an action that should be
        # restricted and is not on this list is a decision somebody has to
        # make, which is the same rule MACROS follows.
        #
        #   probe: a read too (R248), whether the instance answers on its
        #     node's loopback, from its own published ports only.
        #   starter, state: reads, returning the project's .env.example and
        #     the row.
        #   rebuild, abort: a user's own work, on purpose. Somebody given a
        #     project has to be able to build what they committed and look at
        #     it, or the project is read-only in the way that matters. Rebuild
        #     is build-then-down-then-up, so it is also how a stopped instance
        #     comes back, and the page already ghosts it until the code has
        #     actually moved. Abort follows it: whoever may start a build may
        #     stop one, or a mistake is somebody else's problem to clear.
        #
        # Everything else (new, remove, env, route) is configuration rather
        # than a run of the code, and stays an administrator's: except, for a
        # SESSION, what its project's dial hands over below (its env, and
        # creating and removing the project's own container), which the dial
        # decides rather than this gate, since a session never passes this one.
        session = bool(sess)
        dialed = ("env-get", "env-set", "new", "remove", "override") if session else ()
        if act not in ("starter", "state", "probe", "rebuild", "abort", "test") + dialed \
                and self._refused("docker-write"):
            return None
        # A compose file edited from the Docker tab is a file in the project's
        # tree: a write to the project as well as to its container.
        if act == "compose-set" and self._readonly(name):
            return None
        # Sending, copying or moving a container, or putting it under another
        # project, names only projects on the asker's own list, for an
        # administrator and the owner as for a user (the operator, 10 Oct):
        # they could add any project to their list first, and this is the
        # seatbelt against a container landing under the wrong one.
        if not session and act in ("new", "relocate", "owner", "move"):
            for target in [name if act in ("new", "relocate") else "",
                           field(req, "owner") if act in ("new", "owner") else "",
                           field(req, "to") if act == "move" else ""]:
                # A project, not a container written here: one of those is
                # nobody's list to be on.
                if target and registry.is_project(target) and not users.may_work(me, target):
                    return self._json({"error": f"{registry.label(target)} is not on your list of projects: "
                                                "add it to your own list on the Users page first"}, 403)
        if act == "relocate" and session:
            return self._json({"error": "copying or moving a container to another node is a person's: "
                                        "it puts the project's data on another machine"}, 403)
        # A SESSION is a further question, and the answer is a per-project
        # dial with the notebook's own three words. Rebuild runs the project's
        # own Dockerfile and brings the container up on the node's daemon: for
        # a project whose loop is "change it, rebuild it, look at it" that is
        # exactly what you want a session doing; `ask` puts the reason in
        # front of a person first; `deny`, the default, keeps the button the
        # operator's. The read verbs are nobody's secret.
        #
        # It governs rebuild, abort, the env and creating the project's own
        # container, and NOTHING else: remove and route are docker-write
        # above, which a session's principal never has. A test run is not on
        # it: it runs the project's own test command inside a container that
        # is already up, which a session could run on the node anyway
        # (roadmap R48).
        # ...and before the dial, a session may only touch the instance on its
        # OWN node. A session runs on the project's node; an instance pinned
        # to another one is a container on a machine this session is not on,
        # left behind by a node change and still running on purpose. Using or
        # rebuilding it from here would act on somebody else's box through a
        # row that happens to carry this project's name, and a rebuild would
        # bounce a service still being used. The operator keeps both, through
        # the Docker manager, which is where an instance is removed.
        # The exception is one SENT there on purpose (R166): its image is
        # built on the project's own node and shipped, and the project's
        # sessions are the ones meant to rebuild it.
        # A node named by its name (bb devapp new --node NAME) is its id here.
        if act == "new" and req.get("node") and not NODES_OK and not nodes.node(str(req["node"])):
            hit = [n for n in nodes.node_list() if n.get("name") == str(req["node"]) and n.get("state") != "retired"]
            if hit:
                req["node"] = hit[0]["id"]
        if act == "new" and req.get("ship") is True:
            # A session may make one there when its project names the node
            # under Hosts its containers on (prefs.hosts, the operator, 10
            # Oct), under its Run its container dial below; anywhere else it
            # is a person's.
            if session and (name != sess or str(req.get("node") or "") not in (prefs.get(sess).get("hosts") or [])):
                return self._json({"error": "sending a project's container to a node it is not on is a "
                                            "person's, unless the node is ticked under Also works on in the "
                                            "project's settings (a hosting-only node takes containers alone): "
                                            "it puts the project's image on another machine"}, 403)
            if not session and self._refused("node", name):
                return None
        if act not in ("starter", "state", "probe") and session:
            on = devapp.instance_node(name, field(req, "instance"))
            mine = devapp.project_daemon(sess)
            # A shipped one is the session's while its node is still under the
            # project's Hosts its containers on; taken off, the container stays
            # the project's and the session loses it like any other left behind.
            shipped_there = devapp._read_rec(name, devapp.instance_key(name, field(req, "instance") or devapp.MAIN)).get("ship") \
                and on in (prefs.get(sess).get("hosts") or [])
            if on and mine and on != mine and not shipped_there:
                return self._json({"error": "this dev instance is on another node: it stayed "
                                            "where it was running when this project moved, "
                                            "and a session works on its own node's. The "
                                            "operator uses or removes it from the Docker "
                                            "manager"}, 403)
        if act not in ("starter", "state", "probe", "test") and session:
            # The dial is the project's (Agents may: Run its container, in its
            # settings) and covers rebuilding its containers, changing their
            # env and sending the project to Docker, its own container or
            # another beside it: the operator's widenings of 24 and 26 Sep, so
            # a session can bring a container up by request. What a container
            # IS stays out of reach: `new` from a session is the project's own
            # compose file on its own node, never another project's and never
            # a file it wrote, which is `bb container ask` and an
            # administrator's.
            # The dial of the project it belongs to, which is the session's
            # own: the gate above let nothing else through.
            mode = prefs.get(sess)["devbuild"]
            if mode == "deny":
                return self._json({"error": devapp.RUN_DENIED}, 403)
            if act == "new":
                if "owner" in req and field(req, "owner") != name:
                    return self._json({"error": "a session creates its own project's container, "
                                                "belonging to its own project"}, 403)
                req.pop("owner", None)
                # ...on its own node: the node a session names is dropped,
                # except for one it ships to, which the hosts gate above has
                # already held to the project's Hosts its containers on.
                # Dropped whole, a shipped new passed that gate and then
                # landed, unshipped, on the project's own node (B645).
                if req.get("ship") is not True:
                    req["node"] = ""
        if act not in ("starter", "state") and name in project_names(me) \
                and self._readonly(name):
            return None
        # ...and for a container written here, the project it belongs to,
        # for anybody but an administrator: a session of a locked project
        # does not work on its containers either.
        if act not in ("starter", "state") and not users.is_admin(me) \
                and name not in set(project_names(me)) \
                and self._readonly(devapp.owner_of(name, field(req, "instance") or devapp.MAIN)):
            return None
        # `new` is the one action whose instance does not exist yet, which is
        # what it is for; the project it is made for is checked here, where
        # the account is known, and everything else is the module's: which
        # verb means what is devactions.py's to say (the one-file rule), and
        # this handler holds the gate. `owner` names a project the same way.
        if act == "new":
            under = field(req, "owner")
            if under and self._not_project(under):
                return
        # Moving one between projects crosses two of them: a person's, and
        # only into a project they can see.
        if act == "move":
            if me.get("session"):
                return self._json({"error": "moving a container to another project is a person's, "
                                            "on the Containers page"}, 403)
            if field(req, "to") not in set(project_names(me)):
                return self._json({"error": f"no project called {field(req, 'to')}"}, 400)
        if act == "owner" and field(req, "owner") \
                and field(req, "owner") not in set(project_names(me)):
            return self._json({"error": f"no project called {field(req, 'owner')}"}, 400)
        # Which instance of that project. Absent means the one every project
        # has always had, so a caller that predates instances still works and
        # a request that names a strange one is answered rather than obeyed:
        # the name decides a compose project and a data directory, and those
        # are not places to let an arbitrary string reach.
        # A request naming no instance means the project's only one, when
        # it has exactly one: BuilderBot's own is called builderbot-dev, and
        # bb devapp from a session was answering for a `main` that did not
        # exist (15 Sep). With several, `main`; bb takes --instance for that.
        # A NEW one named by nobody takes the name Send would offer: the
        # project's own while it has none, then one beside it.
        inst = field(req, "instance") or (devapp.send_name(name, field(req, "compose")) if act == "new"
                                          else devapp.only_instance(name))
        # A session at `ask` puts the change in front of a person instead;
        # devactions.request says which changes those are.
        return self._json(*devactions.request(
            name, inst, act, req, me=me, principal=self._principal(),
            dial=prefs.get(sess)["devbuild"] if session else "",
            # The command is the project's own, from its settings.
            test_cmd=prefs.get(name)["test"] if act == "test" else ""))

    def _version(self, req):
        """Move a project's version, or change who is allowed to:
        version.verb, behind the gates here.

        A session's bump goes through `bb version bump`, which asks the same
        policy and passes `by="claude"`.
        """
        name = field(req, "project")
        if self._not_project(name):
            return
        act = field(req, "action")
        # B173: this is the panel's, and `by="operator"` is only true of an
        # administrator at it. A session moves its version with bb version
        # bump, under the project's policy, and never here, where it could
        # also have loosened that policy; a plain account may ask a session
        # to bump and no more.
        who = self._who() or {}
        if who.get("session") and act == "release":
            # bb version release (R138): its own project only, under its
            # dial. The tag and the forge's release are made here, with the
            # project's own credentials, which the session never holds.
            if name != who["session"]:
                return self._json({"error": "a session releases its own project and no other"}, 403)
            mode = (prefs.get(name) or {}).get("release") or "ask"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not release it (Agents may: "
                                            "Tag and publish a release); a person cuts it with Release on "
                                            "the Artifacts view"}, 403)
            comp = field(req, "component") or ""
            plan = version.release_plan(name, comp)
            if plan.get("error"):
                return self._json(plan, 400)
            # Said before the tag, not after it (R134 step 4): 0.7.0 was
            # tagged with no sideload key and its APK never attached.
            rs = releasesign.readiness(name, fresh=True)
            if rs["wanted"] and rs["why"] and not req.get("unsigned"):
                return self._json({"error": f"{plan['tag']}'s Android APK could not be signed: {rs['why']}. "
                                            "Put that right first (bb sign status says when it is), or release "
                                            "with --without-apk and have it signed after with bb sign release "
                                            "within three days, while CI keeps the unsigned APK",
                                   "unsigned": rs["why"]}, 409)
            acct = users.account_of(who) or {}
            if mode == "auto":
                return self._json(*_releaser(name, comp, str(acct.get("name") or ""), self._principal()))
            r = phone.ask_release(field(req, "why"), name, comp, plan, membership.owner_of(name),
                                  membership.owner_name(name) or "the project's owner",
                                  asker_name=str(acct.get("name") or ""), principal=self._principal())
            return self._json(r, 400 if r.get("error") else 200)
        if act == "release-remove":
            # Files off a published release: its own ask, never part of an
            # edit, under the release's dial (the operator, 5 Oct).
            if who.get("session") and name != who["session"]:
                return self._json({"error": "a session changes its own project's release and no other"}, 403)
            if not who.get("session") and self._refused("version", name):
                return None
            comp = field(req, "component") or ""
            tag = field(req, "tag")
            if not tag:
                tag, why = version.current_tag(name, comp)
                if why:
                    return self._json({"error": why}, 400)
            mode = (prefs.get(name) or {}).get("release") or "ask" if who.get("session") else "auto"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not release it (Agents may: "
                                            "Tag and publish a release), which taking a file off its release is "
                                            "part of; a person removes it on the forge"}, 403)
            names = req.get("remove") if isinstance(req.get("remove"), list) else []
            plan = forgerelease.remove_plan(name, tag, names)
            if plan.get("error"):
                return self._json(plan, 400)
            acct = users.account_of(who) or {}
            if mode == "auto":
                return self._json(*_release_remover(name, plan, str(acct.get("name") or ""), self._principal()))
            r = phone.ask_release_remove(field(req, "why"), name, plan, membership.owner_of(name),
                                         membership.owner_name(name) or "the project's owner",
                                         asker_name=str(acct.get("name") or ""), principal=self._principal())
            return self._json(r, 400 if r.get("error") else 200)
        if act == "release-edit":
            # bb version release --edit (R139): the published release's
            # notes and files, under the same dial as the release itself, a
            # session's own project only, every edit its own ask.
            if who.get("session") and name != who["session"]:
                return self._json({"error": "a session edits its own project's release and no other"}, 403)
            if not who.get("session") and self._refused("version", name):
                return None
            comp = field(req, "component") or ""
            tag = field(req, "tag")
            if not tag:
                tag, why = version.current_tag(name, comp)
                if why:
                    return self._json({"error": why}, 400)
            attach = req.get("attach") if isinstance(req.get("attach"), list) else []
            notes = req.get("notes") if isinstance(req.get("notes"), str) else None
            mode = (prefs.get(name) or {}).get("release") or "ask" if who.get("session") else "auto"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not release it (Agents may: "
                                            "Tag and publish a release), which an edit of its release is part of; "
                                            "a person edits it on the forge"}, 403)
            plan = forgerelease.edit_plan(name, tag, notes, attach)
            if plan.get("error"):
                return self._json(plan, 400)
            acct = users.account_of(who) or {}
            if mode == "auto":
                return self._json(*_release_editor(name, plan, str(acct.get("name") or ""), self._principal()))
            r = phone.ask_release_edit(field(req, "why"), name, plan, membership.owner_of(name),
                                       membership.owner_name(name) or "the project's owner",
                                       asker_name=str(acct.get("name") or ""), principal=self._principal())
            return self._json(r, 400 if r.get("error") else 200)
        if who.get("session"):
            return self._json({"error": "a session moves its version with bb version bump, "
                                        "under the project's policy, and releases with bb version release"}, 403)
        if act != "ask" and self._refused("version", name):
            return None
        return self._json(*version.verb(name, act, req, self._who(), self._principal()))

    def _members(self, req):
        """A project's owner, whether it is invite only, its people and its
        invitations, and an invitee's answer (membership.verb). A session
        is refused: who joins a project is a person's decision."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "who joins a project is a person's decision"}, 403)
        if not me:
            return self._json({"error": "not signed in"}, 401)
        name = field(req, "project")
        # An invitee answers about a project it may not see yet.
        if field(req, "action") not in ("accept", "decline", "withdraw") and self._not_project(name):
            return None
        return self._json(*membership.verb(me, req))

    # The settings' secrets as the Keys page names them (R154).
    KEPT_SETTINGS = {"tunnel_token": ("Cloudflare tunnel token", "the tunnel that serves this controller"),
                     "cf_api_token": ("Cloudflare API token", "the tunnel's hostnames and DNS records")}

    def _keys(self, req):
        """POST /api/keys (R154): the install key and everything kept under
        it for an administrator (status, show, saved, change), and the
        account's own key for its sign-ins on the nodes (mine, change-mine).
        A session is refused whatever it asks."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "the keys are a person's to manage"}, 403)
        act = field(req, "action")
        uid = users.uid_of(who) or ""
        if act == "mine":
            # The account's key store as Profile lists it (R154): its key and
            # each forge it linked, with the projects linked to it; never a
            # value, and nothing here hands one out.
            # Each token with the projects linked to it, by their shown names.
            forges = [dict(f, projects=[registry.label(p) for p in gitcreds.linked_projects(uid, f["id"])])
                      for f in accountkeys.forges_of(uid)] if uid else []
            return self._json({**accountkeys.status(uid), "forges": forges})
        if act == "unlink-forge":
            fid = field(req, "id")
            if gitcreds.linked_projects(uid, fid):
                return self._json({"error": "a project uses this token: give it another in its settings first, "
                                            "or purge your key store"}, 409)
            return self._json({"ok": accountkeys.unlink_forge(uid, fid)})
        if act == "purge":
            return self._json(self._keys_purge(uid, who.get("name") or uid))
        if act == "change-mine":
            body, code = accountkeys.change(uid, str(req.get("key") or ""))
            if code == 200:
                print(f"dashboard: {who.get('name') or uid} changed their account key", flush=True)
            return self._json(body, code)
        if act in ("unlock", "lock", "unlock-for", "uses", "own-preview", "own-key", "own-back", "prf-begin"):
            return self._json(*self._store_verb(act, uid, who, req))
        if self._refused("controller"):
            return
        if act == "status":
            return self._json({"install": installkey.status(), "kept": self._keys_kept()})
        if act == "show":
            body, code = installkey.reveal()
            if code == 200:
                print(f"dashboard: {who.get('name')} was shown the install key", flush=True)
            return self._json(body, code)
        if act == "saved":
            return self._json(*installkey.saved(field(req, "fingerprint")))
        if act == "purge-for":
            # An administrator's, for an account that cannot sign in to purge
            # its own (the operator, 27 Oct).
            acct = users.get(field(req, "account")) or {}
            if not acct.get("uid"):
                return self._json({"error": "no such account"}, 404)
            print(f"dashboard: {who.get('name')} purged {acct.get('name')}'s key store", flush=True)
            return self._json(self._keys_purge(acct["uid"], acct.get("name") or acct["uid"]))
        if act == "change":
            body, code = installkey.change(str(req.get("key") or ""))
            if code == 200:
                print(f"dashboard: {who.get('name')} changed the install key; {body['resealed']} sealed again", flush=True)
            return self._json(body, code)
        return self._json({"error": f"unknown action {act!r}"}, 400)

    def _store_secret(self, uid, req):
        """The person's secret for their own key, from the request: a
        passkey's PRF output, proved by the passkey's own assertion
        (mfa.passkey_check), or the key they keep, typed; (secret, how,
        passkey id) or (None, why, "")."""
        pk = req.get("passkey") if isinstance(req.get("passkey"), dict) else None
        if pk:
            if not mfa.passkey_check(uid, self._origin(), str(pk.get("id") or ""), pk.get("client"), pk.get("auth"), pk.get("sig")):
                return None, "the passkey did not prove itself", ""
            try:
                secret = base64.urlsafe_b64decode(str(pk.get("prf") or "") + "=" * (-len(str(pk.get("prf") or "")) % 4))
            except (ValueError, TypeError):
                secret = b""
            if len(secret) < 16:
                return None, "this passkey gave no secret: it does not do PRF, so it cannot hold a key; add one that does, or keep a key yourself", ""
            return secret, "passkey", str(pk.get("id") or "")
        secret = unlocks.secret_from_hex(req.get("key"))
        if secret:
            return secret, "key", ""
        return None, "a passkey's answer or the key you keep (64 hex characters) opens it", ""

    def _store_verb(self, act, uid, who, req):
        """Profile's Your key store presses (R158 step 5, R157): unlock for
        the window picked, lock, the window alone, the uses, and the move
        under a key of the person's own and back."""
        if not uid:
            return {"error": "no such account"}, 404
        name = who.get("name") or uid
        if act == "uses":
            labels = {}
            return {"uses": [{**u, "project": registry.label(u["project"]) if u.get("project") else "",
                              "by": labels.setdefault(u["by"], _name_of_uid(u["by"])) if u.get("by") else ""}
                             for u in unlocks.uses(uid)], **unlocks.status(uid)}, 200
        if act == "lock":
            print(f"dashboard: {name} locked their key store", flush=True)
            return {**unlocks.lock(uid, why="locked"), **unlocks.status(uid)}, 200
        if act == "unlock-for":
            try:
                for_s = int(req.get("for"))
            except (TypeError, ValueError):
                for_s = -1
            if not accountkeys.set_unlock_for(uid, for_s):
                return {"error": "the window is a quarter of an hour, an hour, eight hours, or while signed in"}, 400
            return unlocks.status(uid), 200
        if act == "prf-begin":
            return {"challenge": mfa.challenge(uid, "get"), "ids": mfa.passkey_ids(uid), "salt": unlocks.prf_salt(uid)}, 200
        if act == "unlock":
            for_s = req.get("for") if req.get("for") in unlocks.CHOICES else None
            if unlocks.is_own(uid):
                secret, how, _ = self._store_secret(uid, req)
                if secret is None:
                    return {"error": how}, 400
                got = unlocks.unlock(uid, secret, for_s)
            else:
                got = unlocks.unlock(uid, None, for_s)
            if got.get("error"):
                return got, 400
            db.audit(f"user:{name}", "key store unlocked", uid, {"for": unlocks.unlock_for(uid)})
            return {**got, **unlocks.status(uid)}, 200
        if act == "own-preview":
            # What moving the store under their own key means: each project
            # whose background work runs with a token of theirs.
            rows = []
            for fg in accountkeys.forges_of(uid):
                for p in gitcreds.linked_projects(uid, fg["id"]):
                    rows.append({"project": p, "label": registry.label(p), "host": fg["host"], "login": fg["login"], "id": fg["id"]})
            return {"projects": rows, "passkeys": [k for k in mfa.summary(uid)["passkeys"]], **unlocks.status(uid)}, 200
        if act == "own-key":
            secret, how, pid = self._store_secret(uid, req)
            if secret is None:
                return {"error": how}, 400
            keep = {str(p) for p in (req.get("keep") or []) if isinstance(p, str)}
            # The tokens a project's background work runs with go to the
            # controller's store as that project's own, unless kept.
            moved = []
            for fg in accountkeys.forges_of(uid):
                for p in gitcreds.linked_projects(uid, fg["id"]):
                    if p in keep:
                        continue
                    line = accountkeys.forge_line(uid, fg["id"], why="moved to the project", project=p, by=uid)
                    if line and gitcreds.keep_as_own(p, line):
                        moved.append(p)
            body, code = accountkeys.move_to_own(uid, secret, how, pid)
            if code == 200:
                body["moved"] = moved
                db.audit(f"user:{name}", "key store under own key", uid, {"how": how, "moved": len(moved)})
                print(f"dashboard: {name} moved their key store under a key of their own ({how})", flush=True)
            return body, code
        if act == "own-back":
            body, code = accountkeys.move_back(uid)
            if code == 200:
                db.audit(f"user:{name}", "key store under the install key", uid, {})
            return body, code
        return {"error": f"unknown action {act!r}"}, 400

    def _keys_purge(self, uid, name):
        """An account's key store emptied (R154): its key and what it linked
        gone, and the projects linked to it unlinked; its sign-ins on the
        nodes open no more, and a new key is made the next time one is
        sealed."""
        unlinked = gitcreds.unlink_account(uid, name) if uid else []
        accountkeys.forget(uid)
        print(f"dashboard: {name}'s key store purged; {len(unlinked)} project(s) unlinked", flush=True)
        return {"ok": True, "unlinked": unlinked}

    def _keys_kept(self):
        """What the install keeps under its key, by kind, each row naming
        what uses it and where it is changed; no value, sealed or not."""
        rows = []
        names = {u.get("uid"): u.get("name") for u in users.all_users() if u.get("uid")}
        # Where the bell reaches each person (R149): a destination's token
        # or address, sealed, used by nothing but the send.
        for r in reach.at_rest():
            rows.append({"kind": "reach", "name": f"{names.get(r['uid'], r['uid'])}: {r['name']}",
                         "uses": "the bell sent there", "sealed": r["sealed"], "go": ["profile", ""]})
        # A node's model router (R144): the provider keys and its master key.
        for r in router.at_rest():
            rows.append({"kind": "router", "name": f"{(nodes.node(r['node']) or {}).get('name') or r['node']}: {r['name']}",
                         "uses": "the model router there", "sealed": r["sealed"], "go": ["nodes", r["node"]]})
        for f in sorted((STATE / "gitcreds").iterdir()) if (STATE / "gitcreds").is_dir() else []:
            raw = f.read_text(errors="replace").strip() if f.is_file() else ""
            gv = gitcreds.givers(f.name)
            if gv:
                # Each person's own token (R159): kept in their store, not
                # this one, and used for their own work while signed in.
                who = ", ".join(f"{names.get(u) or 'an account'}'s"
                                + (f" {accountkeys.forge_of(u, fid)['host']}" if accountkeys.forge_of(u, fid) else "")
                                for u, fid in gv)
                rows.append({"kind": "git", "name": f.name, "sealed": True, "go": ["project", f.name],
                             "uses": f"the token{'s' if len(gv) > 1 else ''} {who}, each in their own key store"})
                continue
            rows.append({"kind": "git", "name": f.name, "sealed": raw.startswith(gitcreds.SEALED),
                         "uses": "git push and pull for the project's repositories", "go": ["project", f.name]})
        # The dashboard's own TLS key (R158 step 2), sealed under the install key.
        if tls.certificate_pem():
            rows.append({"kind": "tls", "name": "the dashboard's certificate", "sealed": tls._key_sealed(),
                         "uses": "https on the dashboard's own port (Controller settings, Connection)", "go": ["settings", "connection"]})
        d = settings.load()
        for key, spec in settings.KEYS.items():
            if spec["kind"] == "secret" and d.get(key):
                rows.append({"kind": "setting", "name": self.KEPT_SETTINGS.get(key, (key, ""))[0],
                             "sealed": str(d[key]).startswith(settings.SEALED),
                             "uses": self.KEPT_SETTINGS.get(key, ("", key))[1], "go": ["controller"]})
        for proj in signing._projects():
            for k in signing.key_names(proj):
                rows.append({"kind": "signing", "name": f"{proj}: {k}", "sealed": signing.at_rest(proj) == "sealed",
                             "uses": "signing the project's Android builds", "go": ["project", proj]})
        for uid, r in sorted(mfa.load().items()):
            t = (r or {}).get("totp") or {}
            if t.get("on"):
                rows.append({"kind": "two-factor", "name": names.get(uid) or uid, "sealed": bool(t.get("sealed")),
                             "uses": "the authenticator codes this account signs in with", "go": ["user", names.get(uid) or uid]})
        for uid in sorted(accountkeys._load()):
            rows.append({"kind": "account", "name": names.get(uid) or uid, "sealed": True,
                         "uses": "the key this account's own key store is sealed with", "go": ["user", names.get(uid) or uid]})
            for fg in accountkeys.forges_of(uid):
                rows.append({"kind": "forge", "name": f"{names.get(uid) or uid}: {fg['host']}"
                             + (f" ({', '.join(registry.label(p) for p in gitcreds.linked_projects(uid, fg['id']))})"
                                if gitcreds.linked_projects(uid, fg["id"]) else ""), "sealed": True,
                             "uses": f"their own git work{', as ' + fg['login'] if fg['login'] else ''}, "
                                     "kept under their key", "go": ["user", names.get(uid) or uid]})
        for n in nodes.node_list(all=True):
            for uid, seals in sorted((((n.get("reported") or {}).get("tokseal") or {}).get("sealed") or {}).items()):
                rows.append({"kind": "sign-in", "name": f"{names.get(uid) or uid} on {n['name']}", "sealed": True,
                             "uses": ", ".join(getattr(agents.get(a), "name", a) for a in sorted(seals or {}))
                             + " signed in there",
                             "go": ["agents", n["id"]]})
        return rows

    def _signing(self, req):
        """A project's Android signing keys (signing.verb, R106). A session
        is refused whatever it asks: it signs with bb sign, which never hands
        it the key, and has no reason to learn which keys exist from here.
        Listing is for whoever sees the project (no secret is in it); adding,
        replacing and removing a key are an administrator's."""
        name = field(req, "project")
        who = self._who() or {}
        if who.get("session"):
            # bb sign: its own project's build, under its dial (Agents may:
            # Sign a build). It never receives the key, the list, or a
            # backup; asking to sign is all a session does here.
            act = field(req, "action")
            if act not in ("sign", "keys", "generate", "map", "rotate", "release", "release-sign") \
                    or name != who["session"]:
                return self._json({"error": "a session signs with bb sign, which never hands it the key; "
                                            "the keys are a person's to manage"}, 403)
            owner = membership.owner_of(name)
            acct = users.account_of(who) or {}
            if act == "release":
                # bb sign status (R134): whether its release APKs can be
                # signed and how the newest went, in the bell's words. Read
                # only, and no secret is in it.
                return self._json({"release": releasesign.status(name),
                                   "attention": releasesign.attention([name])})
            if act == "release-sign":
                # bb sign release (R134 step 5): the Signing view's retry,
                # under the Sign a build dial.
                if not releasesign.wants(name):
                    return self._json({"error": f"{name}'s workflows hand over no unsigned APK to sign "
                                                f"(an artifact named {releasesign.MARK}TAG)"}, 400)
                mode = (prefs.get(name) or {}).get("sign") or "ask"
                if mode == "deny":
                    return self._json({"error": f"{name}'s settings say Claude does not sign its builds "
                                                "(Agents may: Sign a build); a person presses Look for unsigned "
                                                "APKs now in the Signing view"}, 403)
                if mode == "auto":
                    return self._json(*_release_signer(name))
                r = phone.ask_release_sign(field(req, "why"), name, owner,
                                           membership.owner_name(name) or "the project's owner",
                                           asker_name=str(acct.get("name") or ""))
                return self._json(r, 400 if r.get("error") else 200)
            if act in ("keys", "generate", "map", "rotate"):
                # Manage signing keys (R106 step 6): which keys there are
                # (names and fingerprints, never a secret), and a new key or
                # a package's key proposed, under its own dial.
                kmode = (prefs.get(name) or {}).get("keys") or "ask"
                if kmode == "deny":
                    return self._json({"error": f"{name}'s settings say Claude does not manage its signing "
                                                "keys (Agents may: Manage signing keys)"}, 403)
                if act == "keys":
                    return self._json(*signing.listing(name))
                # Said before anybody is asked to allow a key that could not
                # be made: no backup password yet.
                if act == "generate" and (no := signing.needs_lock(name)):
                    return self._json(*no)
                args = ({"key": field(req, "key") or "default", "route": field(req, "route")} if act == "generate"
                        else {"from": field(req, "from"), "to": field(req, "to")} if act == "rotate"
                        else {"package": field(req, "package"), "key": field(req, "key")})
                if kmode == "auto":
                    return self._json(*_keymaker(act, name, args, by="claude"))
                r = phone.ask_keys(field(req, "why"), name, act, args, owner,
                                   membership.owner_name(name) or "the project's owner",
                                   asker_name=str(acct.get("name") or ""))
                return self._json(r, 400 if r.get("error") else 200)
            mode = (prefs.get(name) or {}).get("sign") or "ask"
            if mode == "deny":
                return self._json({"error": f"{name}'s settings say Claude does not sign its builds "
                                            "(Agents may: Sign a build); a person signs from the "
                                            "Artifacts view"}, 403)
            file, route, key = field(req, "file"), field(req, "route"), field(req, "key")
            no = signing.refusal(name, file, route, key)
            if no:
                return self._json(*no)
            if mode == "auto":
                return self._json(*signing.start(self._principal(), name, file, route, key))
            r = phone.ask_sign(field(req, "why"), name, file, route, owner,
                               membership.owner_name(name) or "the project's owner",
                               asker_name=str(acct.get("name") or ""), principal=self._principal(), key=key)
            return self._json(r, 400 if r.get("error") else 200)
        if self._not_project(name):
            return None
        if field(req, "action") == "sign":
            # Signing a build with a key already kept is working on the
            # project, not administering it.
            if self._readonly(name):
                return None
            return self._json(*signing.start(self._principal(), name, field(req, "file"), field(req, "route"),
                                             field(req, "key")))
        if field(req, "action") == "backup-password":
            # The project's owner's alone, BuilderBot's owner included only
            # when it owns the project: the point is that the dashboard's
            # accounts are not enough by themselves.
            if users.uid_of(who) != membership.owner_of(name):
                return self._json({"error": f"only {name}'s owner ({membership.owner_name(name) or 'its owner'}) "
                                            "sets its backup password"}, 403)
            return self._json(*signing.set_backup_password(name, str(req.get("current") or ""),
                                                           str(req.get("new") or ""), by=str(who.get("name") or "")))
        if field(req, "action") != "list" and self._refused("signing", name):
            return None
        if field(req, "action") == "release-sign":
            # Look for the project's unsigned release APKs now, and sign a
            # failed one again (releasesign.check, R106), on its own thread.
            if not releasesign.wants(name):
                return self._json({"error": f"{name}'s workflows hand over no unsigned APK to sign "
                                            f"(an artifact named {releasesign.MARK}TAG)"}, 400)
            started = releasesign.check_soon(name, force=True)
            return self._json({"ok": True, "started": started, "release": releasesign.status(name)})
        got, status = signing.verb(req, by=str(who.get("name") or ""))
        # Whether this person may take a backup, so the dialog offers it only
        # where it would be handed over.
        # `why`: what keeps this person from changing them, which the
        # Signing view says in place of the controls it leaves out.
        if field(req, "action") == "list" and status == 200:
            got["why"] = users.may(who, "signing", name)
            got["may_backup"] = not got["why"]
            got["may_lock"] = users.uid_of(who) == membership.owner_of(name)
            # Which key signs the releases, and how the last ones went (R106).
            got["release"] = releasesign.status(name)
        return self._json(got, status)

    def _get_node_busy(self):
        """GET /api/node-busy: whether one of a project's nodes is quiet
        enough to time anything on (busy.report, R108). For a session, its
        own project's nodes; for a person, any project they see. Another
        project's work there is counted, never named."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        who = self._who() or {}
        if who.get("session") and name != who["session"]:
            return self._json({"error": "a session asks about its own project's nodes"}, 403)
        if self._not_project(name):
            return None
        if NODES_OK:
            return self._json({"error": "the node store did not open"}, 500)
        pr = prefs.get(name) or {}
        mine = [pr.get("node")] + list(pr.get("nodes") or []) if pr.get("node") else []
        want = q.get("node", [""])[0]
        nodes_here = [n for n in (nodes.node(i) for i in dict.fromkeys(mine) if i) if n]
        n = next((x for x in nodes_here if want in (x["id"], x["name"])), None) if want \
            else (nodes_here[0] if nodes_here else None)
        if not n:
            return self._json({"error": f"{want} is not one of {name}'s nodes" if want
                                        else f"{name} has no node"}, 404)
        jobs = nodes.jobs_for(node_id=n["id"], active=True, n=100)
        working = sum(1 for s in node_tmux_sessions()
                      if s.get("node_id") == n["id"] and (s.get("claude") or {}).get("state") == "working")
        return self._json(busy.report(n, jobs, working, project=name))

    def _get_signing_backup(self):
        """GET /api/signing-backup: a project's keystore for an administrator's
        own copy (signing.backup), which marks it backed up. Never a session's.
        A project whose owner set a backup password is refused here and
        downloads through the POST, which carries it in the body."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        return self._signing_backup(q.get("project", [""])[0], q.get("route", [""])[0],
                                    q.get("key", ["default"])[0] or "default", None)

    def _post_signing_backup(self, req):
        """POST /api/signing-backup: the same, with the project's backup
        password in the body, never in a URL that lands in a log."""
        return self._signing_backup(field(req, "project"), field(req, "route"),
                                    field(req, "key") or "default", str(req.get("password") or ""))

    def _signing_backup(self, name, route, key, password):
        if (self._who() or {}).get("session"):
            return self._json({"error": "a session never receives a signing key"}, 403)
        # The signing area on the project itself (R255 step 3), which asks
        # for the project on the account's own list too: an administrator
        # sees every project, and a key should not leave with somebody who
        # only sees it (the operator, 1 Oct).
        if self._not_project(name) or self._refused("signing", name):
            return None
        if password is None and signing.backup_locked(name):
            return self._json({"error": f"{name}'s key backups need their password: Download backup in its "
                                        "settings asks for it"}, 403)
        no = signing.backup_refusal(name, password or "")
        if no:
            return self._json(*no)
        got, status = signing.backup(name, route, key, password or "")
        if status != 200:
            return self._json(got, status)
        return self._attachment(*got, "application/zip" if got[0].endswith(".zip") else "application/octet-stream")

    def _artifacts(self, req):
        """Push an .xpi from a project's dist/ to the paired phone, install
        an .apk there, or stop a push: phone.artifact_verb, behind the gates
        here."""
        name = field(req, "project")
        if self._not_project(name):
            return
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if self._readonly(name):
            return None
        who = self._who() or {}
        # A session asks for a phone (bb phone run) and a person answers; it
        # does not push or install by itself, and uid_of answering the
        # session's account made the owner check pass for it (the audit of
        # 26 Sep). A capture it lets go of with bb capture prune, in the tree.
        if who.get("session"):
            return self._json({"error": "a session asks for the phone with bb phone run and lets a "
                                        "capture go with bb capture prune NAME; neither is done from here, "
                                        "and a pin is a person's"}, 403)
        if field(req, "action") == "forget-capture":
            return self._json(*artifacts.forget_capture(name, field(req, "name")))
        # A build named with no version, which no sweep can judge: a person's Remove.
        if field(req, "action") == "forget-unnamed":
            return self._json(*artifacts.forget_unnamed(name, field(req, "path")))
        # A pin keeps an artifact from the dev builds' sweep, a person's.
        if field(req, "action") in ("pin", "unpin"):
            return self._json(*artifacts.pin(name, field(req, "path"), field(req, "action") == "pin",
                                             by=who.get("name") or ""))
        return self._json(*phone.artifact_verb(name, field(req, "action"), req,
                                               uid=users.uid_of(who), me=who.get("name") or "somebody",
                                               by=self._principal()))

    def _phone(self, req):
        """Pair, connect, and push an extension, and the asking: a session's
        ask for adb, root or a container, and a person's answer. phone.verb
        checks every argument against something already known (a discovered
        extension, an attached device, a Firefox that is actually installed)
        rather than taking it as given: this is one of the few places the
        page causes a program to run. Who may use which is here."""
        # NOT one gate for the whole endpoint. `ask` is what a session does
        # (bb phone run --why ...) and `outcome` is it reading the answer;
        # the control on those is that a person sees the reason and decides,
        # one command at a time. Pairing, connecting, disconnecting and
        # deciding are a PERSON's, any account and not only an administrator:
        # a phone is its owner's, and phone.py holds the ownership (only the
        # account that connected one can disconnect it or answer for it,
        # and root on a shared sandbox is an administrator's whoever asks).
        # A session's token may reach none of them.
        if field(req, "action") not in ("ask", "outcome", "use") and (self._who() or {}).get("session"):
            return self._json({"error": "a session asks; a person answers"}, 403)
        # The outcome of a request is the asking session's to read (scoped
        # to its project below) and an administrator's; not any account's
        # by id, since the output of a root command on a shared machine is
        # not a user's to browse.
        if field(req, "action") == "outcome" and not (self._who() or {}).get("session") \
                and not users.is_admin(self._who()):
            return self._json({"error": "an outcome is read by the session that asked, or an administrator"}, 403)
        act, nid = field(req, "action"), field(req, "node")
        return self._json(*phone.verb(act, req, self._who() or {}, fresh=lambda: self._phone_payload(
            node=nid, probe=act in ("connect", "disconnect", "pair"))))

    def _findings_log(self, req):
        """The Analysis view's log. Read-only by nature: the scan runs on the
        host and nothing here can write a finding, so `history` is the only
        action there is: the entries are made by findings.counts noticing the
        report changed."""
        name = field(req, "project")
        if self._not_project(name):
            return
        if field(req, "action") != "history":
            return self._json({"error": "the findings log is read-only"}, 400)
        return self._json({"history": findings.history(
            name, limit=req.get("limit"), since=req.get("since"),
            find=field(req, "find"))})

    def _rules(self, req):
        """The operator's house rules for one project: the whole list, saved
        (rules.verb).

        A SESSION IS REFUSED HERE, by name. `bb rules` having no write verb
        and the file tools being denied on the file cover what a session would
        do in the ordinary course of work; they do not cover a session with a
        shell and its own token, which authenticates as a principal with user
        rights over exactly this project, so without this the endpoint would
        have been the way around the whole arrangement. The only writer is a
        person signed in to this dashboard with the project on their list.
        """
        name = field(req, "project")
        if self._not_project(name):
            return
        if self._refused("rules", name) or self._readonly(name):
            return None
        if (bad := projects.locked_out(name, users.uid_of(self._who()))):
            return self._json(bad, 409)
        return self._json(*rules.verb(name, field(req, "action"), req))

    def _global_rules(self, req):
        """The rules that apply to EVERY project (R63): rules.global_verb.
        An administrator's.

        Per-project rules are the operator's for that project; a global one
        reaches projects the person saving it may not even work on, so this
        asks for admin where /api/rules asks only for the project. A session
        is refused the same way and for the same reason: its own token would
        otherwise be the way around the arrangement.
        """
        if self._refused("controller"):
            return None
        return self._json(*rules.global_verb(field(req, "action"), req))

    def _pending(self, req):
        """Approve or deny what a session has waiting (roadmap #27):
        pending.verb. The operator's, by name: a session's own token is
        refused here the way it is for the rules, because a session approving
        its own additions is the setting not existing."""
        name = field(req, "project")
        if self._not_project(name):
            return
        if self._refused("pending", name) or self._readonly(name):
            return None
        return self._json(*pending.verb(name, field(req, "action"), req))

    def _tests(self, req):
        """The hand-written half of the registry: testreg.verb."""
        name = field(req, "project")
        if self._not_project(name):
            return
        # A run's start and end are not a write to the notebook: a locked
        # project's tests still run, and the record is memory the status
        # poll reads (testreg.running).
        act = field(req, "action")
        if act in ("begin", "end"):
            me = self._who() or {}
            req = dict(req, by=me.get("name") or "")
            return self._json(*testreg.verb(name, act, req))
        if self._readonly(name):
            return None
        if (bad := projects.locked_out(name, users.uid_of(self._who()))):
            return self._json(bad, 409)
        return self._json(*testreg.verb(name, act, req))

    def _presence(self, req):
        """This browser is in a project's notebook, and who else is (roadmap
        #26): presence.heartbeat, for a signed-in account on a project it
        sees."""
        me = self._who()
        if not me:
            return self._json({"error": "not signed in"}, 401)
        name = field(req, "project")
        if name not in set(project_names(me)):
            return self._json({"error": f"not a project: {name}"}, 400)
        return self._json(presence.heartbeat(name, me.get("uid") or "",
                                             str(req.get("client") or "")[:64],
                                             field(req, "where"), leave=bool(req.get("leave"))))

    def _bugs(self, req):
        """Report, edit, or close one bug: bugs.verb, behind the gates here."""
        name = field(req, "project")
        if self._not_project(name):
            return
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if field(req, "action") not in ("history", "finished") and self._readonly(name):
            return None
        if (bad := projects.locked_out(name, users.uid_of(self._who()))):
            return self._json(bad, 409)
        return self._json(*bugs.verb(name, field(req, "action"), req, sessions=sessions_anywhere,
                                     prefix=users.tmux_prefix(self._who())))

    def _memory(self, req):
        """Edit, create or delete one of this project's memories, rewrite
        their index, or read the history: memory.verb, behind the gates
        here."""
        act = field(req, "action")
        proj = field(req, "project")
        # A project this account sees, whatever the action: the history
        # read had no project check at all (the audit of 26 Sep).
        if self._not_project(proj):
            return None
        if (bad := projects.locked_out(proj, users.uid_of(self._who()))):
            return self._json(bad, 409)
        # Seeing a project and being able to change it are different
        # questions now (users.may_work): an administrator is shown every
        # project and works on the ones they took on. The reads are named,
        # so an action added later is a write until somebody says otherwise.
        if act != "history" and self._readonly(proj):
            return None
        # Whose memories: the reader's own home, never the owner's (B67).
        # A session's are the account's that started it.
        return self._json(*memory.verb(proj, act, req, home_for(users.uid_of(self._who()))))

    def _custom(self, req):
        """Save or delete one of the operator's own command lists:
        macros.custom_edit."""
        # They run in terminals, so they are edited by accounts that may have
        # one: a command list a shell-less account could write and an
        # administrator would run is a shell by proxy.
        if self._refused("terminal"):
            return None
        return self._json(*macros.custom_edit(req.get("action"), req))

    def _create(self, req):
        """New project: a fresh local repo, a clone or a link, and what the
        dialog chose besides (projects.create_from_dialog)."""
        # An administrator's, for two reasons that both matter: a project this
        # account made would not be in the list it was given, so it would be
        # created and then invisible; and the clone dialog is one of the two
        # places a git token is stored (roadmap #27).
        if self._refused("create"):
            return None
        me = self._who()
        # Into a project (R138: Add a repository on its card): one this
        # account sees and works on, which is not locked against it; the
        # repository then lives on the project's node.
        into = field(req, "project")
        if into:
            if not registry.is_repos(into) or not users.may_see(me, into):
                return self._json({"error": f"not a project: {into}"}, 400)
            if not users.may_work(me, into):
                return self._json({"error": f"{registry.label(into)} is not on your list of projects: "
                                            "add it to your own list on the Users page first"}, 403)
            if (bad := projects.locked_out(into, users.uid_of(me))):
                return self._json(bad, 403)
            return self._json(*projects.create_from_dialog(
                {**req, "_uid": users.uid_of(me)}, env=users.git_env(me, projects.sanitize_name(field(req, "name"))),
                account=me["name"] if me and users.uid_of(me) else "", may_node=lambda name: False))
        # On the nodes the account's New projects role names, when it names
        # any (R152, the operator, 7 Oct): a project made elsewhere, or on no
        # node, is refused by name. Its node is then the account's to set at
        # making it, though setting a node later is the Nodes area's.
        nid = field(req, "node")
        limited = roles.nodes_for(me, "newprojects", "write")
        if limited is not None and nid not in limited:
            names = [n["name"] for n in ([] if NODES_OK else nodes.node_list()) if n["id"] in limited] or limited
            return self._json({"error": f"a project you make goes on {', '.join(names)}: pick "
                                        + ("that node" if len(names) == 1 else "one of those nodes")}, 403)
        # The token a person gives is kept in their own key store (the
        # operator, 27 Oct): who gave it is the server's to say (`_uid`).
        return self._json(*projects.create_from_dialog(
            {**req, "_uid": users.uid_of(me)}, env=users.git_env(me, projects.sanitize_name(field(req, "name"))),
            account=me["name"] if me and users.uid_of(me) else "",
            may_node=lambda name: (limited is not None and nid in limited)
            or not users.may(self._who(), "node", name)))

    def _profile(self, req=None):
        """The signed-in account's own settings (the Profile page): read on
        GET, saved on POST, by profiletab.py. Anybody signed in, because this
        is about themselves."""
        me = self._who()
        if not me or not users.uid_of(me):
            return self._json({"error": "not an account"}, 403)
        if req is None:
            return self._json(*profiletab.view(me))
        payload, status, renamed = profiletab.verb(me, field(req, "action"), req, origin=self._origin())
        return self._json(payload, status, cookie=make_token(renamed, (self._who() or {}).get("lid", "")) if renamed else None)

    def _get_snapshots(self):
        """GET /api/snapshots?project=NAME: the days kept of the project's
        tree (snapshots.py), newest first, and how many it keeps. An
        administrator's, like a restore."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a project's snapshots are the operator's"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._refused("settings", name) or self._not_project(name):
            return None
        return self._json({"project": name, "keep": prefs.get(name)["snapshot_days"],
                           "on": prefs.get(name)["snapshots_on"], "days": snapshots.days(name)})

    def _snapshots(self, req):
        """POST /api/snapshots: take one now, or restore the whole tree as of a
        day or one file of it (snapshots.restore, which snapshots the tree
        first so it can be undone). Never a session's: a session is what a
        restore may be undoing."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a project's snapshots are the operator's"}, 403)
        name = field(req, "project")
        if self._refused("settings", name) or self._not_project(name):
            return None
        act = field(req, "action")
        if act == "take":
            return self._result(snapshots.take(name))
        if act == "restore":
            return self._result(snapshots.restore(name, field(req, "day"), field(req, "path"),
                                                  who=self._principal()))
        if act in ("pin", "unpin"):
            r = snapshots.pin(name, field(req, "day"), act == "pin")
            if r.get("ok"):
                db.audit(self._principal(), f"snapshot-{act}", name, {"day": r["day"]})
            return self._result(r)
        return self._json({"error": "take, restore, pin or unpin"}, 400)

    def _get_transcripts(self):
        """GET /api/transcripts?project=NAME: the signed-in account's own
        conversations with Claude on that project, newest first
        (transcripts.mine); with audit=DAYS, what they did against the
        house rules that can be counted instead (transcripts.audit). Anybody signed in, their own only, a session
        included: on its own project and on one its project reads, it
        lists the account's conversations there for `bb transcripts`."""
        me = self._who()
        uid = users.uid_of(me) if me else ""
        if not me or not uid:
            return self._json({"error": "not an account"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        if q.get("audit"):
            # `bb rules audit` (R200 step 6): the same conversations,
            # counted against the guards in effect on the project.
            try:
                days = max(1, min(90, int(q["audit"][0])))
            except ValueError:
                days = transcripts.AUDIT_DAYS
            guards = rules.guards(name)

            def judge(cmd, background=False):
                hit = rulehook.refused(guards, cmd, background)
                return hit[0]["name"] if hit else ""
            return self._json({"project": name, "audit": transcripts.audit(uid, name, judge, days)})
        # ...and the ones other accounts made visible to every session on
        # the project, each with whose it is (the Sessions view's Make visible).
        names = {u["uid"]: u["name"] for u in users.all_users()}
        return self._json({"project": name, "rows": transcripts.mine(uid, [name]),
                           "visible": transcripts.visible(uid, name, lambda u: names.get(u, u))})

    def _transcripts(self, req):
        """POST /api/transcripts {project, id, action}: one of the signed-in
        person's own conversations deleted, or made visible to every session
        on the project (share) or private again (unshare). A person's, from
        the notebook's Sessions view: never a session's, which reads them."""
        me = self._who()
        uid = users.uid_of(me) if me else ""
        if not me or not uid:
            return self._json({"error": "not an account"}, 403)
        if me.get("session"):
            return self._json({"error": "a conversation is deleted or shared by its person, from the "
                                        "project's Sessions view, not by a session"}, 403)
        name, sid, act = field(req, "project"), field(req, "id"), field(req, "action")
        if self._not_project(name):
            return
        if act == "delete":
            r, st = transcripts.delete(uid, name, sid)
        elif act in ("share", "unshare"):
            r, st = transcripts.set_shared(uid, name, sid, act == "share")
        else:
            return self._json({"error": "delete, share or unshare"}, 400)
        if st == 200:
            db.audit(me["name"], f"conversation-{act}", name, {"id": sid})
        return self._json(r, st)

    def _get_transcript(self):
        """GET /api/transcript?project=NAME&id=SESSION: one of the signed-in
        account's own conversations with Claude on that project as a text
        file, every command and answer in it (transcripts.render); as JSON
        with as=json, which is what `bb transcripts show` reads, and only its
        newest MB with tail=MB; as turns with as=turns, the dashboard's
        reader's (the newest 32 MB unless tail says). Anybody
        signed in, their own only, a session included on its own project
        and on one its project reads: the file is looked for under the
        account's own transcripts directory and nowhere else, so another
        account's id is simply not found."""
        me = self._who()
        uid = users.uid_of(me) if me else ""
        if not me or not uid:
            return self._json({"error": "not an account"}, 403)
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        # Another account's, made visible to every session on the project,
        # is read as its owner's; anything else of theirs is not found.
        uid = transcripts.owner_of(uid, name, q.get("id", [""])[0]) or uid
        if q.get("as", [""])[0] == "raw":
            # The file as Claude Code wrote it, for bb transcripts fetch: a
            # synced node resuming a conversation it does not have (B613).
            # Nothing when it is no longer than the copy the node has.
            f = transcripts.raw(uid, name, q.get("id", [""])[0])
            if f is None:
                return self._json({"error": "no such conversation of yours"}, 404)
            st = f.stat()
            try:
                have = int(q.get("have", ["-1"])[0])
            except ValueError:
                have = -1
            if st.st_size <= have:
                return self._json({"size": st.st_size}, 200)
            return self._send_file({"path": f, "ctype": "application/octet-stream",
                                    "headers": {"X-Mtime-Ms": str(st.st_mtime_ns // 1_000_000)}})
        try:
            tail = max(0, int(q.get("tail", ["0"])[0])) * 1024 * 1024
        except ValueError:
            tail = 0
        # The dashboard's reader (R83): turns, the newest part of a long one.
        if q.get("as", [""])[0] == "turns":
            return self._json(*transcripts.turns(uid, name, q.get("id", [""])[0],
                                                 transcripts.zone(q.get("tz", [""])[0]), tail=tail or 32 * 1024 * 1024))
        text, fname = transcripts.render(uid, name, q.get("id", [""])[0],
                                         transcripts.zone(q.get("tz", [""])[0]), tail=tail)
        if text is None:
            return self._json({"error": fname}, 404)
        if q.get("as", [""])[0] == "json":
            return self._json({"name": fname, "text": text})
        return self._attachment(fname, text.encode("utf-8"), "text/plain; charset=utf-8")

    def _git_act(self, req):
        """The Git view's actions (roadmap R36 step 2): fixed git commands on
        the project's tree on the controller, under the acting account's
        author and the project's own credentials (gitview.verb). An
        account's, never a session's (a session has bb git), on a project it
        may see and has taken on, and not while the project is locked.
        Switching the tree's branch is refused while the owner's Claude
        session runs in the project directory, because that session is
        standing in it (gitview.in_use)."""
        me = self._who()
        if not me or not users.uid_of(me) or me.get("session"):
            return self._json({"error": "an account's, not a session's: a session uses bb git"}, 403)
        name = field(req, "project")
        if name not in set(project_names(me)):
            return self._json({"error": "not a project"}, 400)
        if self._readonly(name):
            return None
        action = field(req, "action")
        # A branch is its session's (git.py not_yours): another account's is
        # an administrator's to merge, asked each time and never while that
        # session is working, and nobody else's. Before the check below,
        # which is about the tree a session stands in, not the branch.
        mine_ = gitview.not_yours(WORKSPACE / name, action, req.get("args") or {},
                                  users.uid_of(me), field(req, "kind"), admin=users.is_admin(me))
        if mine_.get("error"):
            return self._json(mine_, 403)
        if mine_.get("confirm"):
            return self._json({"error": mine_["confirm"].split("\n\n")[-1], "confirm": mine_["confirm"]}, 409)
        if (busy := gitview.in_use(name, action, req.get("args") or {}, users.uid_of(me))):
            return self._json({"error": busy}, 409)
        # A person's press is their own work: their own token first (R154).
        acting = gitview.ACTING.set(users.uid_of(me))
        try:
            return self._result(gitview.verb(name, action, req, me, prefix=users.tmux_prefix(me),
                                             principal=self._principal()))
        finally:
            gitview.ACTING.reset(acting)

    def _vms_iso_upload(self):
        """An ISO uploaded on the VMs page: VMs Write on the project the dialog
        is for, a person's (never a session's), streamed to the controller's
        spool and fetched from there by the node's job."""
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        project = (q.get("project") or [""])[0]
        if (self._who() or {}).get("session"):
            return self._json({"error": "uploading an installer ISO is a person's, on the VMs page"}, 403)
        if why := featuresoff.refused("POST", "/api/vms", {}):
            return self._json({"error": why, "off": True}, 403)
        if not registry.is_project(project):
            return self._json({"error": "which project's VMs is it for? name one"}, 400)
        if self._refused("vms-write", project):
            return None
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        return self._result(vms.iso_upload(self._principal(), self.rfile, n, (q.get("node") or [""])[0],
                                           (q.get("name") or [""])[0]))

    def _upload_archive(self):
        """Spool an archive for the create dialog; {id, name, size, kind}.
        The same gate as create, because it is the first half of one, and
        an upload that stops short of a project would otherwise be a way
        for a user account to fill the controller's disk."""
        if self._refused("create"):
            return None
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json({"error": "bad request"}, 400)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        r = projects.spool_archive(self.rfile, n, (q.get("name") or [""])[0])
        return self._result(r)

    def _link(self, req):
        """Link an existing local repo to an empty repo on a host. projects.py.

        The create gate, because this is the create dialog's third mode and
        one of the places a git token is written, the same reason that gate
        covers the other two. It went ungated from the day it was added: the
        dialog is only drawn for an administrator, so nothing offered it, and
        nothing refused a request that arrived anyway.
        """
        if self._refused("create"):
            return None
        body, code = projects.link({**req, "_uid": users.uid_of(self._who())})
        # A project linked is a project whose CI is worth a first look now,
        # not at the next round (R117).
        if code == 200:
            ciwatch.look_soon(field(req, "name").strip())
        return self._json(body, code)

    def _unlink(self, req):
        """Take the remote off a project, with the credential and the push
        grant that came with it. See projects.unlink: local, instant, and it
        touches no commit."""
        if self._refused("create"):
            return None
        body, code = projects.unlink(req)
        return self._json(body, code)

    def _project_job(self, req):
        """Stop the running project job, or clear the last one's outcome.

        The create gate, as for starting one (B171): a clone or a link is the
        create dialog's, and without it any account could stop an
        administrator's clone halfway or clear a failure before they read it.
        """
        if self._refused("create"):
            return None
        return self._json(*projects.job_verb(req.get("action", "")))

    def _users(self, req):
        """The Users page's verbs. Thin, like _nodes: users.py owns the rules
        (that the owner cannot be deleted or demoted, that there is only ever
        one, what a password has to be), and this is the door.

        The owner protections live there rather than here on purpose. A rule
        enforced at the door holds for the door; a rule enforced in the store
        holds for `bb users` too, and that is the one an operator reaches for
        when they are locked out.
        """
        act = field(req, "action")
        # Ahead of the admin gate, because this one is nobody else's business:
        # an account setting its OWN appearance. Everything below acts on
        # another account and is an administrator's.
        if act == "prefs":
            me = self._who()
            if not me or not users.uid_of(me):
                return self._json({"error": "not an account"}, 403)
            return self._json(*users.own_prefs(me["name"], req.get("prefs")))
        if self._refused("admin"):
            return None
        me = self._who() or {}
        # An account's device signed out by an administrator (R272 step 8).
        if act == "device-signout":
            target = (users.load().get("users") or {}).get(field(req, "name"))
            if not target:
                return self._json({"error": f"no account called {field(req, 'name')}"}, 400)
            return self._result(devices.revoke({"name": field(req, "name"), **target}, field(req, "device"),
                                               by=me.get("name", "")))
        return self._result(users.verb(act, req, lambda: set(project_names(me)),
                                       may_change=lambda p: membership.member_refusal(
                                           me, p, joining=field(req, "name") == me.get("name"))))

    def _roles(self, req):
        """POST /api/roles: assign (an account's Everywhere roles and its
        roles on each project, as far as the asker may, R152 and R155), set
        (make or change a role: its scope, its areas and note) or remove
        one; owner and admin are built in and refuse both. Roles themselves
        are an administrator's."""
        act = field(req, "action")
        if act == "assign":
            return self._json(*users.assign(self._who(), field(req, "name"),
                                             req.get("roles") if isinstance(req.get("roles"), list) else None,
                                             req.get("project_roles") if isinstance(req.get("project_roles"), dict) else None))
        if self._refused("admin"):
            return None
        if act == "set":
            # A role held by somebody keeps its kind: an Everywhere role is
            # given to the account and a project role on a project, so a
            # change of kind would leave every holder holding it in the
            # wrong place and silently without it (R155).
            was = roles.get(field(req, "name"))
            want = field(req, "scope") or "projects"
            if was and not was.get("builtin") and "perms" in req and was.get("scope") != want:
                held = sorted(u["name"] for u in users.all_users()
                              if field(req, "name") in (users.get(u["name"]) or {}).get("roles", [])
                              or any(field(req, "name") in rs for rs in
                                     ((users.get(u["name"]) or {}).get("project_roles") or {}).values()))
                if held:
                    return self._json({"error": f"{', '.join(held)} {'holds' if len(held) == 1 else 'hold'} "
                                                f"{field(req, 'name')}: take it off first, or make a new role "
                                                "of the other kind"}, 400)
            if "perms" in req:
                return self._result(roles.set_role(field(req, "name"), field(req, "scope") or "projects",
                                                   req.get("perms") if isinstance(req.get("perms"), dict) else {},
                                                   field(req, "note"),
                                                   nodes=req.get("nodes") if isinstance(req.get("nodes"), list) else [],
                                                   only=req.get("only") if isinstance(req.get("only"), dict) else {}))
            return self._result(roles.set_role(field(req, "name"), grants=req.get("grants"), note=field(req, "note")))
        if act == "two-factor":
            # Require a second factor of everybody holding this role (R127).
            r = roles.set_two_factor(field(req, "name"), req.get("on") is True)
            if r.get("ok"):
                db.audit(self._principal(), "role-two-factor", r["name"], {"on": r["two_factor"]})
            return self._result(r)
        if act == "remove":
            r = roles.remove(field(req, "name"))
            if r.get("ok"):
                # ...and off every account that held it (B20).
                r["held_by"] = users.forget_role(r["name"])
            return self._result(r)
        return self._json({"error": "unknown action"}, 400)

    def _toolchains(self, req):
        """Queue installs or removals of the toolchains the Tools card
        offers: an administrator's, and toolchains.verb says what each
        action does with which names."""
        # By grant, on the node named (R137 step 3): an administrator's
        # everywhere, a role of your own where it says.
        if (why := users.may_node(self._who(), "toolchains-write", field(req, "node"))):
            return self._json({"error": why}, 403)
        # An agreement (Google's Android SDK terms, NVIDIA's CUDA license) is
        # a person's to accept, by name, before anything installs under it;
        # the page asks, and the acceptance is on the record.
        if req.get("action") == "install":
            need = toolchains.agreements(req.get("names") or [])
            given = req.get("accept") if isinstance(req.get("accept"), list) else []
            if (missing := [t for t in need if t["label"] not in given]):
                return self._json({"error": "installing this accepts " + " and ".join(t["label"] for t in missing)
                                            + ": accept it on the Toolchains page first",
                                   "accept": missing}, 409)
            if need:
                db.audit(self._principal(), "terms-accepted", ",".join(map(str, req.get("names") or []))[:200],
                         {"terms": [t["label"] for t in need], "node": field(req, "node")})
        return self._json(*toolchains.verb(req.get("action"), req, self._principal()))

    def _toolpacks(self, req):
        """POST /api/toolpacks: look at a tool pack by its repository's
        address, or at one made here from a pasted manifest or an uploaded
        archive (/api/upload-archive's id); add it as it was shown; read a
        pack made here's manifest back for Edit; or remove it (R77).
        An administrator's, since a pack joins every node's catalog."""
        if self._refused("admin"):
            return None
        action = req.get("action")
        shipped = {r["name"] for r in toolchains.load_toolchains()}
        by = (self._who() or {}).get("name") or ""
        if action == "preview" and ("text" in req or field(req, "archive")):
            r = toolpacks.stage(req.get("text") if isinstance(req.get("text"), str) else None,
                                field(req, "archive"), shipped)
        elif action == "preview":
            r = toolpacks.fetch(field(req, "url"), shipped=shipped)
        elif action == "add" and field(req, "staged"):
            r = toolpacks.add_staged(field(req, "staged"), by, shipped)
        elif action == "add":
            r = toolpacks.add(field(req, "url"), field(req, "commit"), by, shipped)
        elif action == "source":
            r = toolpacks.source(field(req, "name"))
        elif action == "where":
            # Asked before Remove's confirm: refused here, saying where, while
            # a node's store holds it (B84).
            w = toolchains.installed_where(field(req, "name"))
            r = toolpacks.where_said(field(req, "name"), w) if w else {"installed": []}
        elif action == "remove":
            r = toolpacks.remove(field(req, "name"), toolchains.installed_where(field(req, "name")))
        else:
            return self._json({"error": "a tool pack is previewed, added, read or removed"}, 400)
        if r.get("error"):
            return self._json(r, 400)
        if action not in ("preview", "source"):
            toolchains.refresh_packs()
        return self._json(r)

    def _emulator(self, req):
        """Add system images to a node, or remove one: a job there, against
        its toolchain store. An id must be one the tab was drawn from (add)
        or one the node reported (remove): what reaches a command line is a
        string this server handed out."""
        if self._refused("toolchains-write"):
            return
        if NODES_OK:
            return self._json({"error": "the node store did not open"}, 500)
        action, nid = req.get("action"), field(req, "node")
        # ...on that node (R260): a role holding Toolchains on named nodes.
        if (why := users.may_node(self._who(), "toolchains-write", nid)):
            return self._json({"error": why}, 403)
        # A project's phone off the node (R123), one this account sees.
        if action == "phone-remove":
            project = field(req, "project")
            if not project or not (users.is_admin(self._who()) or users.may_see(self._who(), project)):
                return self._json({"error": "which of your projects?"}, 400)
            return self._result(nodes.node_avd_remove(self._principal(), nid, project,
                                                      field(req, "uid"), field(req, "name")))
        iid = req.get("images") if isinstance(req.get("images"), list) else field(req, "image")
        if action not in ("add", "remove"):
            return self._json({"error": "an image is added or removed"}, 400)
        return self._result(emulator.node_job(self._principal(), nid, action, iid))

    def _changelog(self, req):
        """Write back the Unreleased section a person rearranged:
        changelog.editor_verb.

        A session does not get this. The CLI verbs it has (add, edit, merge,
        split, rm) each say what they are doing to one entry; handing it the
        whole section would make "the changelog is the operator's arrangement"
        a convention rather than a rule. The refusal names the verbs.
        """
        if (self._who() or {}).get("session"):
            return self._json({"error": "the changelog's arrangement is the "
                                        "operator's: a session writes entries with "
                                        "`bb changelog add`, and corrects one with "
                                        "`edit`, `merge`, `split` or `rm`"}, 403)
        name = req.get("project", "")
        # A role that reads the project does not rearrange its changelog
        # either (B101): the Save was live for it, and went through.
        if self._not_project(name) or self._readonly(name):
            return
        if (bad := projects.locked_out(name, users.uid_of(self._who()))):
            return self._json(bad, 409)
        return self._json(*changelog.editor_verb(name, req))

    def _nodelog(self, req):
        """A machine's own log, for a session that has been granted it.

        Which node is ASKING is not taken from the request and never from the
        session's environment: a node session's BB_NODE is a variable it can
        set. It is the node of the session's own project, which the token
        proves, by the same derivation the phone's ask uses, for the same
        reason.
        """
        if NODES_OK:
            return self._json({"error": "the node store did not open: " + NODES_OK}, 500)
        who = self._who() or {}
        proj = who.get("session") or field(req, "project")
        if proj and not who.get("session") and not users.may_see(who, proj):
            return self._json({"error": "not a project"}, 400)
        asking = prefs.get(proj)["node"] if proj else ""
        # The debug grant's, named only (the operator, 6 Oct): the session's
        # account, or the person asking, must hold it as well as the project
        # its grant for the node.
        if who.get("session"):
            me = users.account_of(who)
            if me is who or users.may(me, "debug"):
                return self._json({"error": "a machine's logs are for an account with the debug "
                                            "grant, and this session's account has not got it: "
                                            "a role with it is picked in their settings on the Users page"}, 403)
        elif self._refused("debug"):
            return None
        r = nodes.log_read_named(self._principal(), asking, field(req, "node"),
                                 field(req, "stream"), req.get("lines"),
                                 bool(settings.get("debug_mode")),
                                 grants=prefs.get(proj)["log_from"] if proj else [],
                                 project=proj)
        # Redacted for a session, as the same text read through the Jobs
        # API already is: a machine's journal names tokens as it goes.
        if (self._who() or {}).get("session") and isinstance(r.get("out"), str):
            r["out"] = diag.redact(r["out"])
        return self._result(r, 403)

    def _diag(self, req):
        """The controller's diagnostics (diag.py). An administrator's, and a
        session's only when the debug switch is on, its project's settings
        grant it the diagnostics, and the session's account holds the debug
        grant (_diag_why). POST, so each read is in the audit trail."""
        if self._diag_refused():
            return None
        want = req.get("sections") if isinstance(req.get("sections"), list) else None
        r = diag.report([str(x) for x in want] if want else None)
        return self._json(r, 400 if r.get("error") else 200)

    def _diag_why(self):
        """Why this caller may not read the controller's diagnostics, or "":
        see _diag. Asked, never written: _diag_refused writes it."""
        who = self._who() or {}
        if who.get("session"):
            if not settings.get("debug_mode"):
                return "debug mode is off, so the controller's diagnostics are not offered to any session"
            me = users.account_of(who)
            if me is who or users.may(me, "debug"):
                return ("the controller's diagnostics are for an account with the debug grant, "
                        "and this session's account has not got it: a role with it is given "
                        "in their settings on the Users page")
            if not prefs.get(who["session"])["diag"]:
                return (f"{who['session']} has not been granted the controller's "
                        "diagnostics: the Debug page grants them")
            return ""
        return users.may(who, "debug")

    def _diag_refused(self):
        """True, with the refusal written, unless this caller may read the
        controller's diagnostics: see _diag. The reports sessions make about
        BuilderBot are read and acted on behind the same gate."""
        who = self._who() or {}
        if who.get("session"):
            why = self._diag_why()
            if why:
                self._json({"error": why}, 403)
                return True
            return False
        return self._refused("debug")

    def _files(self, req):
        """A project's files for a person's own editor (files.py, R159): the
        account this request proved, a project it sees, and the file access
        its settings give it through the editor's door, asked on this request
        (ftp.access_for), so the extension can do nothing the account cannot.
        A session is refused: it has the tree, and it is never a person."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session has its project's tree already: this is a "
                                        "person's editor's"}, 403)
        if why := files.api_refused(self.headers.get("X-BB-Api"), self.headers.get("X-BB-App")):
            return self._json({"error": why, "update": True}, 426)
        if field(req, "action") == "projects":
            # The ones this account may open, each with its access: asked
            # project by project through the same gate as every call after.
            mine = []
            for name in project_names(me):
                a, _ = ftp.access_for(me, name, "editor")
                if a:
                    mine.append({"name": name, "access": a, **projects.app_flags(name, users.uid_of(me))})
            return self._json({"api": files.API, "api_min": files.API_MIN, "projects": mine})
        project = field(req, "project")
        if self._not_project(project):
            return None
        access, why = ftp.access_for(me, project, "editor")
        if not access:
            return self._json({"error": why}, 403)
        return self._json(*files.verb(field(req, "action"), project, req, access,
                                      by=self._principal()))

    def _reports(self, req):
        """Problems with BuilderBot itself, reported by any project's session
        (reports.py, bb report). Anybody signed in adds one for a project they
        may see, and a session only for its own. A person reads, deletes and
        clears them on Controller settings, so its gate is that page's (the
        operator, 26 Oct: not a debug feature); a session reads them behind
        the diagnostics' own gate, since that is where it reads them (bb diag
        reports)."""
        me = self._who() or {}
        sess = me.get("session") or ""
        act = field(req, "action")
        name = str((users.account_of(me) or {}).get("name") or "")
        if act == "add":
            # Only the server attaches a conversation, never the caller.
            req.pop("_conversation", None)
            proj = sess or field(req, "project")
            # A person's report about no project in particular (the header's
            # Report a bug, the operator, 2 Oct): heard from any account, with
            # no project to check.
            if not sess and not proj:
                return self._json(*reports.own_verb(act, "", req, by=f"{name} (from the dashboard)"))
            if not sess and self._not_project(proj):
                return None
            # A person reports from a project they work on (the operator,
            # 2 Oct): an administrator shown every project but not on this
            # one cannot start a session here, so has nothing of its to report.
            if not sess and not users.may_work(me, proj):
                return self._json({"error": f"you are not on {proj}, so a bug from there is not yours to "
                                            "report: ask to be added, or report from a project you work on"}, 403)
            # The dial is Claude's (Agents may: Report BuilderBot bugs): a
            # person reporting from a project's row is always heard.
            if sess and prefs.get(proj)["report"] == "deny":
                return self._json({"error": f"reporting BuilderBot bugs is off for {proj}: its "
                                            "settings, Agents may: Report BuilderBot bugs. A "
                                            "problem goes into this project's tracker"}, 403)
            # The person's latest conversation on the project, when they
            # ticked Include it (the operator, 2 Oct): theirs only, found and
            # rendered here, never named by the page.
            if not sess and req.get("include_conversation"):
                uid = users.uid_of(me)
                rows = transcripts.mine(uid, [proj])
                if rows:
                    text, _ = transcripts.render(uid, proj, rows[0]["id"])
                    if text:
                        req["_conversation"] = {"id": rows[0]["id"], "text": text}
            # A person's report says it came from the dashboard, so the
            # diagnostics tell it from a session's `bb report`.
            return self._json(*reports.own_verb(act, proj, req, by=name if sess else f"{name} (from the dashboard)"))
        # Clearing is a person's, from Controller settings, whatever a
        # session may otherwise read here.
        if act in ("clear", "delete") and sess:
            return self._json({"error": "deleting reports is a person's, from "
                                        "Controller settings"}, 403)
        # A person's are Controller settings' (reading them its read, deleting
        # its write); only a session reading them is debug's (the operator,
        # 26 Oct): debug mode, the debug grant and its project's grant.
        if not sess:
            if self._refused("controller" if act in ("clear", "delete") else "controller-read"):
                return None
        elif self._diag_refused():
            return None
        return self._json(*reports.diag_verb(act, req, by=name, principal=self._principal()))

    def _doctor(self, req):
        """Re-run bb doctor now and answer with the fresh verdict.

        Synchronous on purpose: the caller pressed a button asking for an
        answer, and the threading server keeps everything else responsive
        while this one connection waits the half-minute a bad network takes.
        """
        if self._refused("controller"):
            return None
        if not doctor.refresh():
            return self._json({"error": "doctor is already running"}, 409)
        return self._json(doctor.payload())

    def _pin(self, req):
        """Pin or unpin a command: macros.pin."""
        # One set for everybody, so an administrator's: the project pins
        # beside it are each person's own since 27 Sep, this is not.
        if self._refused("command-pin"):
            return None
        return self._json(*macros.pin(req.get("name", ""), bool(req.get("pinned"))))

    def _get_schedules(self):
        """GET /api/schedules (R117): every schedule, its words, its next run
        and its last run's state, and the nodes it may run on. Read on
        Schedules; never a session's, whatever its token holds."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "schedules are a person's: a session has no say in them"}, 403)
        why = users.may(who, "schedules-read")
        if why:
            return self._json({"error": why}, 403)
        rows = schedules.listing()
        for r in rows:
            last = r.get("last") or {}
            if last.get("job"):
                last["state"] = _job_state(last["job"])
        # The controller first, as itself (its own runner, as the controller's
        # account), then every enrolled node.
        ns = [{"id": n["id"], "name": "the controller" if n.get("kind") == "local" else n["name"],
               "sandbox": bool((n.get("reported") or {}).get("sandbox")), "state": n.get("state", ""),
               "controller": n.get("kind") == "local"}
              for n in (nodes.node_list() if not NODES_OK else []) if n.get("kind") in ("agent", "local")]
        return self._json({"schedules": rows, "nodes": ns, "may": not users.may(who, "schedules")})

    def _schedules(self, req):
        """POST /api/schedules (R117): save (add or change, turning one on or
        off among them), remove, or run now. Write on Schedules; never a
        session's."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "schedules are a person's: a session has no say in them"}, 403)
        why = users.may(who, "schedules")
        if why:
            return self._json({"error": why}, 403)
        act, by = field(req, "action"), self._principal()
        if act == "save":
            r = schedules.save(req, by)
            if r.get("schedule"):
                db.audit(by, "schedule-save", r["schedule"]["id"], {"on": r["schedule"].get("on"),
                                                                 "cron": r["schedule"].get("cron")})
        elif act == "remove":
            r = schedules.remove(field(req, "id"))
            if r.get("ok"):
                db.audit(by, "schedule-remove", field(req, "id"), {})
        elif act == "run":
            s = schedules.get(field(req, "id"))
            if not s:
                return self._json({"error": "no such schedule"}, 404)
            if not s.get("node"):
                return self._json({"error": "pick the node it runs on first"}, 400)
            r = schedules.fire(s, by, schedule_queue)
        else:
            return self._json({"error": "action is save, remove or run"}, 400)
        return self._json(r, 400 if r.get("error") else 200)

    def _get_storage(self):
        """The Storage page (storage.view, R169): every node this account
        holds the Storage area on, what its disks hold, by project where
        the account sees the project and as one line otherwise. Never a
        session's: a session reads its node with bb node busy."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a node's disks are a person's to read here"}, 403)
        if NODES_OK:
            return self._json({"error": "the node store did not open: " + NODES_OK}, 500)
        return self._json(*storage.view(nodes.node_list(), who, is_admin=users.is_admin,
                                        nodes_for=roles.nodes_for, may_see=users.may_see,
                                        level_of=roles.level_of))

    def _storage(self, req):
        """Measure now on the Storage page: a node's disks walked at once
        (nodes.node_storage_measure). Write on Storage for that node."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a node's disks are a person's to read here"}, 403)
        nid = field(req, "node")
        if not nid or not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        if not users.is_admin(who) and roles.level_of(who, "storage", node=nid) != "write":
            return self._json({"error": "measuring a node's disks again is Write on Storage"}, 403)
        return self._result(nodes.node_storage_measure(self._principal(), nid))

    def _get_nginx(self):
        """The nginx page (nginxproxy.view): every node's nginx, for an
        account that may read the Nodes page; never a session's."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a node's proxy is a person's"}, 403)
        if not users.is_admin(who) and not roles.level_of(who, "nodes"):
            return self._json({"error": "the nginx page is the Nodes page's area: ask for Read on Nodes"}, 403)
        return self._json(nginxproxy.view(devapp, devactions.state))

    def _get_router(self):
        """GET /api/router?node=ID: a node's model router (router.status)
        and the projects it may be offered to, for an account that reads the
        Nodes page; never a session's."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a node's router is a person's"}, 403)
        if self._refused("nodes"):
            return
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        nid = q.get("node", [""])[0]
        if not nid or not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        return self._json({**router.status(nid), "providers_known": {k: v["label"] for k, v in router.PROVIDERS.items()},
                           "all_projects": sorted(prefs.all_projects(WORKSPACE)),
                           "gpu": bool(((nodes.node(nid) or {}).get("reported") or {}).get("gpu_card"))})

    def _get_router_key(self):
        """GET /api/router-key?project=NAME: the router address and the
        project's own key, for a session of that project at its start
        (bb-tty's launcher) or a person who may work on it; {} where no
        router allows the project."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._not_project(name):
            return
        who = self._who() or {}
        if who.get("session") and who.get("session") != name and users.key_of(who.get("session") or "") != users.key_of(name):
            return self._json({"error": "a session is handed its own project's key"}, 403)
        got = router.for_project(name)
        if got:
            got["models"] = router.models_for(name)
        return self._json(got)

    def _router(self, req):
        """POST /api/router: a node's model router (router.py): its keys and
        endpoints saved, Deploy, Save and Remove as a written container's
        compose jobs, Ollama's models pulled and removed, a project allowed
        or not, the models and the spend read; docker-write like the
        nginx page, and never a session's."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a node's router is a person's"}, 403)
        if self._refused("docker-write"):
            return
        act, nid = field(req, "action"), field(req, "node")
        if not nid or not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        by = (self._who() or {}).get("name") or ""
        gpu = bool(((nodes.node(nid) or {}).get("reported") or {}).get("gpu_card"))
        if act == "set":
            r = router.set_keys(nid, req)
            if not r.get("error") and router.record(nid).get("deployed"):
                r = router.apply(nid, containers, devactions, devapp, gpu) | {"saved": True}
        elif act == "deploy":
            r = router.deploy(nid, containers, devactions, devapp, gpu)
        elif act == "remove":
            r = router.remove(nid, devactions, devapp)
        elif act == "allow":
            r = router.allow(nid, field(req, "project"), by)
        elif act == "disallow":
            r = router.disallow(nid, field(req, "project"))
        elif act == "ollama-pull":
            r = router.ollama_pull(nid, field(req, "model"), by)
        elif act == "ollama-remove":
            r = router.ollama_remove(nid, field(req, "model"), by)
        elif act == "models":
            r = router.refresh_models(nid)
        elif act == "spend":
            r = {"ok": True, "spend": router.refresh_spend(nid)}
        else:
            return self._json({"error": f"unknown action {act!r}"}, 400)
        if not r.get("error"):
            db.audit(f"user:{by}", f"router-{act}", nid, {"project": field(req, "project")} if act in ("allow", "disallow") else {})
        return self._result(r)

    def _get_scanners(self):
        """The Scanners page (scanners.view): every node's scanners, the
        schedule, the versions and what nothing covers, for an account that
        may read the Nodes page; never a session's."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a node's scanners are a person's"}, 403)
        if self._refused("nodes"):
            return
        return self._json(scanners.view())

    def _scanners(self, req):
        """Deploy, update, remove, run now, the schedule and a version check
        (scanners.py): compose and scan jobs on a node, so docker-write like
        a written container, and never a session's."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a node's scanners are a person's"}, 403)
        if self._refused("docker-write"):
            return
        act, nid = field(req, "action"), field(req, "node")
        by = (self._who() or {}).get("name") or ""
        if act == "deploy-all":
            r = scanners.deploy_all(by)
        elif act == "check":
            r = {"ok": True, "latest": scanners.check_versions()}
        elif act == "run":
            r = scanners.run_now(by, nid)
        elif act == "schedule":
            r = scanners.set_schedule(on=req.get("on") if "on" in req else None,
                                      cron=req.get("cron") if "cron" in req else None)
        elif not nid or not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        elif act == "deploy":
            r = scanners.deploy(nid, by)
        elif act == "update":
            r = scanners.update(nid, by)
        elif act == "remove":
            r = scanners.remove(nid, by)
        else:
            return self._json({"error": f"unknown action {act!r}"}, 400)
        if not r.get("error"):
            db.audit(f"user:{by}", f"scanners-{act}", nid or "all", {})
        return self._result(r)

    def _nginx(self, req):
        """Deploy, save, certificate, remove, check and update on one node's
        nginx (nginxproxy.py): writing a compose file and building it on a
        node, so docker-write like a written container, and never a
        session's. Check reads the registry now; update pins the newest
        line on the node and rebuilds (R192)."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "a node's proxy is a person's"}, 403)
        if self._refused("docker-write"):
            return
        act, nid = field(req, "action"), field(req, "node")
        # The hostname list is every node's (one pull-down on every route).
        if act == "host-add":
            return self._result(nginxproxy.add_hostname(field(req, "name")))
        if act == "host-remove":
            return self._result(nginxproxy.remove_hostname(field(req, "name")))
        if not nid or not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        if act == "deploy":
            r = nginxproxy.deploy(nid, containers, devactions, devapp)
        elif act == "route-add":
            # From a container's row on the Docker tab (R209): a port of the
            # container and the certificate the route serves under.
            r = nginxproxy.add_route(nid, req.get("port"), field(req, "cert"), containers, devactions, devapp,
                                     host=field(req, "host"))
        elif act == "save":
            r = nginxproxy.save_routes(nid, req.get("routes"))
            # The routes as kept go back with the answer, so the row says
            # the saved port at once rather than after a read (B99).
            kept = {"routes": r["routes"]} if isinstance(r.get("routes"), list) else {}
            # The certificate pasted is the node's default, or one
            # hostname's own when cert_for names it (R175).
            saved = {}
            # A pair pasted is kept under the key its names say, or the one
            # cert_for names (R188); drop_cert names the key to take off.
            if not r.get("error") and isinstance(req.get("cert"), str) and req.get("cert").strip():
                r = nginxproxy.set_cert(nid, req.get("cert"), req.get("key"), field(req, "cert_for"))
                if not r.get("error"):
                    saved = {"host": r.get("host", "")}
            drop = req.get("drop_cert")
            if not r.get("error") and drop:
                r = nginxproxy.drop_cert(nid, drop if isinstance(drop, str) else field(req, "cert_for"))
            if not r.get("error"):
                r = nginxproxy.apply(nid, containers, devactions, devapp) | saved | kept
        elif act == "remove":
            r = nginxproxy.remove(nid, devactions, devapp)
        elif act == "check":
            lt = nginxproxy.check_image()
            r = {"error": lt["error"]} if lt.get("error") else {"ok": True, "latest": lt}
        elif act == "update":
            r = nginxproxy.update(nid, containers, devactions, devapp)
        elif act == "acme":
            # A certificate from Let's Encrypt (R150), asked for in the
            # background; the page follows it on the node's row.
            r = nginxproxy.acme_request(nid, field(req, "host"), field(req, "method"), field(req, "email"),
                                        containers, devactions, devapp)
        else:
            return self._json({"error": f"unknown action: {act}"}, 400)
        return self._result(r)

    def _images(self, req):
        """Check for updates on the Containers page (imagecheck.py, R195): every
        container's registry images on one node, or all, asked now. A
        person's, under docker-write, since what it leads to is an Update."""
        if (self._who() or {}).get("session"):
            return self._json({"error": "checking for image updates is a person's"}, 403)
        if self._refused("docker-write"):
            return
        if field(req, "action") != "check":
            return self._json({"error": "unknown action"}, 400)
        nid = field(req, "node")
        if nid and not nodes.node(nid):
            return self._json({"error": "which node?"}, 400)
        return self._result(imagecheck.check(nid or None))

    def _get_help(self):
        """GET /api/help: the docs on the Help page (helpdocs.py, R258): the
        listing, ?doc=NAME one of them, ?q=WORDS a search across them. Any
        account and any session: they are the docs the image ships."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        if "q" in q:
            return self._json(*helpdocs.search((q.get("q") or [""])[0]))
        if "doc" in q:
            return self._json(*helpdocs.read((q.get("doc") or [""])[0]))
        return self._json(*helpdocs.listing())

    def _get_notices(self):
        """GET /api/notices: notices.listing, this account's own (R218 step 6).
        A session has none: what a page said is a person's."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a session has no notices"}, 403)
        return self._json(*notices.listing(users.uid_of(who)))

    def _notices(self, req):
        """Keep, delete or clear what the page said to this account:
        notices.act. The account's own, so no grant; a session has none."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a session has no notices"}, 403)
        return self._json(*notices.act(users.uid_of(who), req))

    def _bell(self, req):
        """Put a bell note away for this account, bring every one back
        (bellseen.py), or resume a session an outage held (R251). The
        account's own, so no grant; a session has no bell."""
        who = self._who() or {}
        if who.get("session"):
            return self._json({"error": "a session has no bell"}, 403)
        uid = users.uid_of(who)
        if field(req, "action") == "restore":
            return self._json(*bellseen.restore(uid))
        if field(req, "action") == "resume":
            return self._json(*_resume_held(who, field(req, "node"), field(req, "session")))
        return self._json(*bellseen.dismiss(uid, req.get("keys")))

    def _layout(self, req):
        """Store this account's open tabs: layout.save_tabs."""
        return self._json(*layout.save_tabs(users.uid_of(self._who()), req))

    def _lock(self, req):
        """Lock or unlock a project (R119), never a session's. Its owner's
        lock holds everybody else; an administrator's holds its owner too
        (projects.locked_out, bb-tty's is_locked). Locking ends every
        session it holds out, here and on every node: all of them under an
        administrator's, all but the owner's under the owner's. Named in the
        answer, so the page can say what went.

        What it does NOT claim: a session in ANOTHER project still reaches this
        directory through Bash. The file tools are denied on every sibling
        already, and that is the whole of the guarantee here too.
        """
        name, on = req.get("name", ""), bool(req.get("locked"))
        if self._not_card(name):
            return None
        name = repos.key_of(name)
        me = self._who()
        owner = membership.owner_of(name)
        uid = "" if not me or me.get("session") else users.uid_of(me)
        admin = bool(uid) and users.is_admin(me)
        if not lock_may(name, uid, admin, projects.load_locks().get(name)):
            return self._json({"error": "an administrator locked it, and an administrator unlocks it"
                                        if projects.load_locks().get(name, {}).get("admin")
                                        else "the project's owner or an administrator locks it, and "
                                             "the one who locked it unlocks it"}, 403)
        # An administrator who is not its owner locks it against its owner
        # too (the operator, 23 Oct); its owner's lock leaves the owner in.
        held = admin and uid != owner
        body, code = projects.lock_verb(name, on, by=uid, admin=held)
        if on and code == 200:
            # Every session it holds out ends (the operator, 23 Oct): under
            # an administrator's lock all of them, under its owner's all but
            # the owner's.
            bb_owner = users.uid_of(users.get(users.owner_name() or "")) if users.owner_name() else ""
            # Every repository's in the project (R138).
            want = set()
            for m in repos.expand([name]) or [name]:
                want |= set(agent_sessions(m))
            ended = []
            for s in [x for x in tmux_sessions() if tmux_base(x["name"]) in want] \
                    + [x for x in node_tmux_sessions() if tmux_base(x["name"]) in want]:
                if not held and (tmux_owner(s["name"]) or bb_owner) == owner:
                    continue
                r = end_session(s["name"], str(s.get("node_id") or ""))
                if not r.get("error") and not r.get("gone") and s["name"] not in ended:
                    ended.append(s["name"])
            body = dict(body) | {"ended": ended}
        return self._json(body, code)

    def _end_agents_on(self, names):
        """End every agent session on these projects, here and on every
        node; the names of the ones that went."""
        want = set()
        for n in names:
            want |= set(agent_sessions(n))
        ended = []
        for s in [x for x in tmux_sessions() if tmux_base(x["name"]) in want] \
                + [x for x in node_tmux_sessions() if tmux_base(x["name"]) in want]:
            r = end_session(s["name"], str(s.get("node_id") or ""))
            if not r.get("error") and not r.get("gone") and s["name"] not in ended:
                ended.append(s["name"])
        return ended

    def _running_on(self, keys):
        """The coding agents' sessions running now on these projects'
        repositories, here and on every node, by name."""
        want = set()
        for k in keys:
            for m in repos.expand([k]):
                want |= set(agent_sessions(m))
        return [x["name"] for x in tmux_sessions() + node_tmux_sessions() if tmux_base(x["name"]) in want]

    def _repos(self, req):
        """Projects and their repositories (R138): create (a project with a
        name and nothing in it), rename, move (a repository into another
        project) with move-check (what it changes, asked first: the nodes,
        containers and VMs it touches and who loses it), delete (a project
        with no repository left, what was given to it left to no project)
        and owned (what a delete would leave with no project). A person's,
        never a session's."""
        me = self._who()
        if not me or me.get("session"):
            return self._json({"error": "a person makes and changes projects, never a session"}, 403)
        act = field(req, "action")
        admin = users.is_admin(me)
        mine = lambda n: admin or membership.may_manage(me, n)          # noqa: E731
        if act == "create":
            if self._refused("create"):
                return None
            got = repos.create(field(req, "name"))
            if got.get("error"):
                return self._json(got, 400)
            if users.uid_of(me):
                users.take_on(me["name"], got["key"])
                membership.on_create(got["key"], me["name"])
            return self._json(got)
        if act == "rename":
            key = field(req, "key")
            if not registry.is_repos(key) or not users.may_see(me, key):
                return self._json({"error": f"not a project: {key}"}, 400)
            if not mine(key):
                return self._json({"error": "the project's owner or an administrator renames it"}, 403)
            return self._result(registry.set_name(key, field(req, "to")))
        if act == "delete":
            key = field(req, "key")
            if not registry.is_repos(key) or not users.may_see(me, key):
                return self._json({"error": f"not a project: {key}"}, 400)
            if not mine(key):
                return self._json({"error": "the project's owner or an administrator deletes it"}, 403)
            got = repos.delete(key)
            if got.get("ok"):
                membership.forget_project(key)
                prefs.forget(key)
                # What was given to it keeps running, given to no project
                # (the operator, 26 Oct).
                got = dict(got, unassigned=devapp.unassign(key))
            return self._result(got, 409)
        # What a delete would leave with no project, for its dialog to say:
        # the containers given to a project or a repository, and a
        # repository's VMs.
        if act == "owned":
            name = field(req, "name")
            if not (registry.is_repos(name) or registry.is_project(name)) or not users.may_see(me, name):
                return self._json({"error": f"not a project: {name}"}, 400)
            return self._json({"containers": devapp.owned_by(name), "vms": sorted(v.get("name") or "" for v in vms.view([name]))})
        if act in ("move", "move-check"):
            name, to = field(req, "name"), field(req, "to")
            if self._not_project(name):
                return None
            if not registry.is_repos(to) or not users.may_see(me, to):
                return self._json({"error": f"not a project: {to}"}, 400)
            was = repos.project_of(name)
            if not all(users.may_work(me, k) for k in (to, was or name)) or not (mine(to) and mine(was or name)):
                return self._json({"error": "the owner of both projects, or an administrator, moves a repository "
                                            "between them"}, 403)
            for k in (to, was or name):
                if (bad := projects.locked_out(k, users.uid_of(me))):
                    return self._json(bad, 403)
            # The check before the move (the operator, 26 Oct): what it changes,
            # asked before it is done, with the nodes to bring along.
            if act == "move-check":
                return self._json(self._move_plan(me, name, to, was))
            # Not from under a session (the operator, 25 Oct): one working
            # across the project would lose a tree, one in the other gain one.
            busy = self._running_on([k for k in (was, to) if k])
            if busy:
                return self._json({"error": f"{', '.join(busy)} running on {registry.label(was) if was else ''}"
                                            f"{' or ' if was else ''}{registry.label(to)}: end "
                                            f"{'it' if len(busy) == 1 else 'them'} first, then move it"}, 409)
            # The nodes the person ticked to bring along, as the check offered
            # them: no other node, and only a node this account may set.
            plan = self._move_plan(me, name, to, was)
            offered = {n["id"]: n["as"] for n in plan["nodes"] if not n["have"]}
            add = [str(x) for x in (req.get("add_nodes") or []) if str(x) in offered]
            if add and users.may(me, "node"):
                return self._json({"error": users.may(me, "node")}, 403)
            got = repos.move(name, to)
            if got.get("error"):
                return self._json(got, 400)
            readers = prefs.regrant(to, [name])
            if add:
                dst = prefs.get(to)
                hosts = list(dst.get("hosts") or []) + [n for n in add if offered[n] == "hosts"]
                nodes_ = list(dst.get("nodes") or []) + [n for n in add if offered[n] != "hosts"]
                prefs.set_prefs(to, nodes=nodes_, hosts=hosts)
            # Each container as the person left its box (the operator, 26
            # Oct): ticked, the project it goes to has it; unticked, the one
            # it leaves keeps it. One on a node the project it goes to has not
            # got, even now, stays where it can be reached.
            give = {str(x) for x in (req.get("give") or [])}
            reach = set(add) | {n["id"] for n in plan["nodes"] if n["have"]} | {prefs.get(to).get("node") or ""}
            kept, given, why = [], [], []
            for t in plan["things"]:
                if t["kind"] != "container":
                    continue
                p, _, inst = t["key"].partition("|")
                want = t["key"] in give and (t["reach"] or t["node"] in reach)
                if want == t["goes"]:
                    continue
                r = devapp.set_owner(p, inst, name if want else was)
                if r.get("error"):
                    why.append(f"{t['name']}: {r['error']}")
                else:
                    (given if want else kept).append(t["name"])
            return self._json(dict(got, name=name, project=registry.label(to), added=add, given=given, kept=kept,
                                   owner_errors=why, readers=[registry.label(r) for r in readers]))
        return self._json({"error": "action is create, rename, move, move-check, delete or owned"}, 400)

    def _move_plan(self, me, name, to, was):
        """What moving the repository `name` from its project `was` into `to`
        changes (the operator, 26 Oct): the nodes `was` has that `to` has not,
        each with what it is to the project (works on it, or hosts its
        containers) and the repository's dev instances running there, and the
        accounts that reach the repository through `was` alone. A session
        running on either, which refuses the move, is said too."""
        src, dst = prefs.get(name), prefs.get(to)
        have = {dst.get("node") or ""} | set(dst.get("nodes") or []) | set(dst.get("hosts") or [])
        runs = devapp.instance_nodes(name)
        out = []
        # Every node the project it leaves has, dev and hosting (the operator,
        # 26 Oct): the ones `to` has already said so, the rest offered.
        for nid, kind in ([(src.get("node") or "", "nodes")] + [(n, "nodes") for n in src.get("nodes") or []]
                          + [(n, "hosts") for n in src.get("hosts") or []]):
            if nid and nid not in {x["id"] for x in out}:
                n = nodes.node(nid) or {}
                out.append({"id": nid, "name": n.get("name") or nid, "as": kind, "have": nid in have,
                            "instances": sorted(i for i, at in runs.items() if at == nid)})
        lose = []
        if was:
            for uname, rec in (users.load().get("users") or {}).items():
                u = {**rec, "name": uname}
                if not users.is_admin(u) and users.may_work(u, was) and not users.may_work(u, to):
                    lose.append(uname)
        busy = self._running_on([k for k in (was, to) if k])
        return {"name": name, "label": registry.label(name), "from": registry.label(was) if was else "",
                "to": registry.label(to), "nodes": out, "lose": sorted(x for x in lose if x),
                "things": self._move_things(name, was, have),
                "busy": busy, "node_why": users.may(me, "node") if any(not n["have"] for n in out) else ""}

    @staticmethod
    def _move_things(name, was, have):
        """The containers and VMs moving `name` out of `was` touches (the
        operator, 26 Oct). A container is the repository's unless it was given
        to a project: the repository's go with it, and stay with `was` only
        when asked; `was`'s own stay, and go to the project it moves to only
        when asked. A VM is its repository's and always goes with it. Each
        with its node and whether the project it goes to has that node."""
        out = []
        for p, insts in (devapp._load() or {}).items():
            for inst, rec in (insts or {}).items():
                own = devapp.owner_of(p, inst, rec)
                if not own or own not in (name, was):
                    continue
                nid = str((rec or {}).get("node") or "")
                out.append({"kind": "container", "key": f"{p}|{inst}", "name": devapp._pname(p, inst),
                            "node": nid, "node_name": (nodes.node(nid) or {}).get("name") or nid,
                            "reach": nid in have, "goes": own == name})
        for v in vms.view([name]):
            nid = str(v.get("node") or "")
            out.append({"kind": "vm", "key": v.get("key") or "", "name": v.get("name") or "",
                        "node": nid, "node_name": v.get("node_name") or nid, "reach": nid in have, "goes": True})
        return out

    def _archive(self, req):
        """Archive or unarchive a project (R119): out of sight, and nothing
        else; the project's owner or an administrator, never a session."""
        name, on = req.get("name", ""), bool(req.get("archived"))
        if self._not_card(name):
            return None
        me = self._who()
        if not me or me.get("session") or not (users.is_admin(me) or users.uid_of(me) == membership.owner_of(name)):
            return self._json({"error": "the project's owner or an administrator archives it"}, 403)
        return self._json(*projects.archive_verb(name, on))

    def _trash(self, req):
        """Move a project out of the workspace: projects.trash, once
        project_busy says nothing holds it (the same guards as renaming)."""
        name = req.get("name", "")
        if self._refused("trash", name):
            return
        if (busy := project_busy(name, "trash")):
            return self._json({"error": busy}, 409)
        body, code = projects.trash(req)
        # Out of its project, which its record keeps (R138): the trash says
        # where it was, and a restore puts it back there.
        if code == 200 and not body.get("error"):
            # Its containers keep running, given to no project until it is
            # put back (the operator, 26 Oct).
            body = dict(body, project=registry.label(repos.detach(name)), unassigned=devapp.unassign(name))
        return self._json(body, code)

    def _trash_list(self):
        return self._json(projects.trash_list())

    def _trash_restore(self, req):
        """A repository out of the bin, back into the project it was in, or
        into the one named (`project`) where that one is gone or another is
        wanted (R138); one from before projects into a project of its own.
        It is never put back into none."""
        if self._refused("trash"):
            return
        into = field(req, "project")
        if into and (not registry.is_repos(into) or not users.may_see(self._who(), into)):
            return self._json({"error": f"not a project: {into}"}, 400)
        was = registry.last_project(projects.restore_dir(field(req, "name")))
        into = into or (was if registry.is_repos(was) else "")
        # Its project deleted since: which one is asked. One deleted before
        # projects came first was in none, and comes back in a project of
        # its own as every repository did then (_place, migration 0010).
        if not into and was:
            return self._json({"error": f"it was in {registry.label(was)}, which is deleted: pick the project "
                                        "to put it back into", "pick": True}, 409)
        body, code = projects.trash_restore(req)
        if code == 200 and not body.get("error"):
            if into:
                repos.add(into, body["name"])
                prefs.regrant(into, [body["name"]])
            else:
                _place({body["name"]})
                into = repos.project_of(body["name"])
            body = dict(body, project=registry.label(into) if into else "", reassigned=devapp.reassign(body["name"]))
        return self._json(body, code)

    def _trash_purge(self, req):
        """Delete a trashed project for good. The guards are in projects.py
        (the path is resolved against the bin and the name has to be typed
        back), and this is only the route to them."""
        if self._refused("trash"):
            return
        return self._json(*projects.trash_purge(req))

    def _rename(self, req):
        """Rename a project: projects.rename. Only the registry's name
        changes, so nothing running holds it back."""
        name = req.get("name", "")
        # Whether it is a project first, then whether this account may: a
        # name that is nothing answered "not taken on" to the owner once
        # their list was explicit (R135), where it is simply not a project.
        if self._not_project(name):
            return
        if self._refused("rename", name):
            return
        # Nothing on disk moves: the name shown is the registry's, so
        # a session, a terminal or a container holding the project is not
        # in the way of it. The account a link names is the asker (R154).
        return self._json(*projects.rename({**req, "_uid": users.uid_of(self._who())}))

    def _project_auth(self, req):
        """What credential this project's remote uses, and what else it
        could: projects.auth_answer."""
        name = req.get("name", "")
        # The rename dialog's question, about a project this account sees
        # (B175): it says how the project's remote authenticates.
        if self._not_project(name) or self._refused("rename", name):
            return None
        # Test (the operator, 7 Oct): a read and a dry-run push with what it
        # authenticates with, or with a token typed and not saved yet.
        if req.get("action") == "test":
            return self._json(*projects.auth_test(name, str(req.get("token") or "")))
        # Its own deploy key, made or pasted beside the token (the operator,
        # 12 Oct): the private half goes to the root-only helper and no
        # further.
        if str(req.get("action") or "").startswith("key-"):
            return self._json(*projects.deploy_key(name, str(req["action"]), str(req.get("key") or "")))
        body, code = projects.auth_answer(name)
        if code == 200:
            # What the asker's own key store keeps, to link the project to
            # (R154), and whose account the project is linked to now.
            body["store"] = accountkeys.forges_of(users.uid_of(self._who()))
            # Who has given the project a token (R159), by name, and
            # whether each is signed in now; what the asker's own press
            # would run with.
            body["givers"] = _givers_said(name, users.uid_of(self._who()))
            body["runs_as"] = _token_said(name, users.uid_of(self._who()))
            lk = body.get("linked") or {}
            if lk.get("uid"):
                # `host` holds the entry's id since entries have ids: its host said.
                fg = accountkeys.forge_of(lk["uid"], lk.get("host")) or {}
                lk["id"], lk["host"] = lk.get("host"), fg.get("host") or lk.get("host")
                acct = next((u for u in users.all_users() if u.get("uid") == lk["uid"]), {})
                lk["name"] = acct.get("name") or "an account that is gone"
                lk["mine"] = lk["uid"] == users.uid_of(self._who())
        return self._json(body, code)

    def _project_ftp(self, req):
        """A project's file access over FTP (ftp.py, R151): what it is, for
        whoever sees the project, and a change, for an account with the ftp
        grant (named only: the owner, until a role names it)."""
        name = field(req, "project")
        if self._not_project(name):
            return None
        me = self._who() or {}
        may_set = not users.may(me, "ftp", name)
        if req.get("action") == "set":
            if self._refused("ftp", name):
                return None
            return self._json(*ftp.save(name, req, me.get("name") or "?"))
        # Who has access, and the port, are the setter's to know: anybody
        # else learns only whether it is on.
        v = ftp.view(name, may_set)
        if not may_set:
            v = {"on": v["on"], "may_set": False, "status": v["status"], "node": v["node"], "port": v["port"]}
        return self._json(v)

    def _project_pin(self, req):
        """Pin or unpin a project: whether the sidebar card shows it
        (projects.pin). No session is touched and nothing is blocked: this is
        the one control of the three that is purely about the view."""
        # A person's own set (the operator, 27 Sep): any signed-in account
        # may pin for itself; a session has no sidebar and pins for nobody.
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session has no sidebar: the pins are a person's own"}, 403)
        return self._json(*projects.pin(users.uid_of(me), req.get("name", ""), bool(req.get("pinned")),
                                        users.starts_unpinned(me)))

    def _project_group(self, req):
        """Put a project in one of this account's groups, take it out, or
        rename a group (projects.set_group, rename_group), or delete one
        (delete_group): a label for the Projects page, nothing more."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session has no Projects page: the groups are a person's own"}, 403)
        if "rename" in req:
            return self._json(*projects.rename_group(users.uid_of(me), field(req, "rename"), field(req, "to")))
        if "delete" in req:
            return self._json(*projects.delete_group(users.uid_of(me), field(req, "delete")))
        name = field(req, "name")
        if self._not_card(name):
            return None
        return self._json(*projects.set_group(users.uid_of(me), name, field(req, "group")))

    def _project_color(self, req):
        """Give a project one of the colors for this account alone, or none
        (projects.set_mark): worn by its card, its tabs and its bar."""
        me = self._who() or {}
        if me.get("session"):
            return self._json({"error": "a session has no Projects page: a project's color is a person's own"}, 403)
        name, color = field(req, "name"), field(req, "color")
        if self._not_card(name):
            return None
        if color and color not in prefs.COLORS:
            return self._json({"error": f"color is one of {', '.join(prefs.COLORS)}, or none: not {color}"}, 400)
        return self._json(*projects.set_mark("color", users.uid_of(me), name, color,
                                             start=_legacy_colors(prefs.all_projects(WORKSPACE))))

    def _session(self, req):
        """Kill a session. Closing a tab that owns a Claude conversation should
        end it, or detached sessions accumulate invisibly behind a tidy UI."""
        session = req.get("session", "")
        if req.get("action") != "kill":
            return self._json({"error": "unknown action"}, 400)
        if self._not_theirs(session):
            return None
        # Wherever it runs, with already gone as ended (end_session). A name
        # that is not a live session never becomes a `-t` argument: nothing
        # runs for it. By node id when the row said which, and by name alone
        # for a caller that only knows the name (a tab closing).
        return self._result(end_session(session, str(req.get("node") or "")))

    def _get_reset(self):
        """GET /api/reset: how a Reset that un-enrolls its nodes first is
        getting on: each node, done or why not, and the error that stopped
        it. An administrator's."""
        if self._refused("controller-read"):
            return None
        return self._json({k: v for k, v in _reset_job.items() if k != "started"})

    def _get_project_sessions(self):
        """GET /api/project-sessions?project=NAME: every account's sessions on
        the project, for its settings dialog. An administrator's."""
        q = urllib.parse.parse_qs(self.path.partition("?")[2])
        name = q.get("project", [""])[0]
        if self._refused("settings", name) or self._not_project(name):
            return None
        return self._json({"sessions": projsessions.of(name)})

    def _project_sessions(self, req):
        """POST /api/project-sessions {project, action: "end", session, node}:
        an administrator ending one of them (projsessions.py)."""
        name = field(req, "project")
        if self._refused("settings", name) or self._not_project(name):
            return None
        if field(req, "action") != "end":
            return self._json({"error": "unknown action"}, 400)
        return self._result(projsessions.end(name, field(req, "session"), field(req, "node")))

    def _not_theirs(self, session):
        """True, with the 403 written, when this account may not act on that
        session: end it or type a macro into it (B172).

        A session is its owner's. Its name says whose (u_<uid>~...), and the
        owner's own on this container keep bare names, so a bare name is the
        owner's. Nobody acts on anybody else's, administrators included: a
        key in another person's Claude session is an answer to a question
        it asked them. A session's token is held to its own project as well,
        the way everything else it does is. The one exception is ending one,
        an administrator's, from a project's settings (projsessions.py, the
        operator's call of 24 Sep); keys and typing stay the account's.
        """
        who = self._who() or {}
        mine = users.uid_of(who)
        owner = tmux_owner(session) or users.uid_of(users.get(users.owner_name() or ""))
        ok = bool(mine) and owner == mine
        if ok and who.get("session"):
            base = tmux_base(session)
            stem = base.split("-", 1)[1] if "-" in base else ""
            proj = tmux_name(who["session"])
            ok = stem == proj or stem.startswith(proj + "-")
        if not ok:
            self._json({"error": "that session is not yours"}, 403)
        return not ok

    def _session_on_node(self, session, node=""):
        """The node session row this page-name means, or None. For the
        three key paths, which type into a node's session through its
        agent exactly as they type into this container's tmux."""
        if session in {s["name"] for s in tmux_sessions()} and not node:
            return None
        return next((s for s in node_tmux_sessions() if s["name"] == session
                     and (not node or s["node_id"] == node)), None)

    def _chat(self, req):
        """Read a conversation, send into one, or mark one seen: chat.converse.

        Who may read what is decided HERE and not in chat.py: a direct
        conversation is its two ends' and a project feed is whoever may see
        the project. The store holds lines; the door decides.
        """
        me = self._who()
        uid = users.uid_of(me)
        if not uid:
            return self._json({"error": "not an account"}, 403)
        act = field(req, "action") or "read"
        store = users.load()["users"]
        by_name = {n: u.get("uid") for n, u in store.items() if u.get("uid")}
        who, proj = field(req, "who"), field(req, "project")
        if proj:
            # may_see, not may_work: a project's channel is the group chat for
            # everybody on it, and saying something in one is not a change to
            # the project. So an administrator, who is shown every project,
            # can read and answer every channel, which is what makes it
            # useful to them, while a user has the channels they were given
            # and no others. The list marks which are actually theirs.
            if not users.may_see(me, proj):
                return self._json({"error": "not a project"}, 403)
            key, box = f"p:{proj}", ("project", proj)
        elif who:
            other = by_name.get(who)
            if not other or other == uid:
                return self._json({"error": "no such account"}, 403)
            key, box = f"dm:{other}", ("dm", other)
        else:
            return self._json({"error": "name a person or a project"}, 400)

        return self._json(*chat.converse(act, me, uid, box, key, req.get("text", ""),
                                         {u: n for n, u in by_name.items()}))

    def _say(self, req):
        """Type a message into a CLAUDE session and press Enter.

        The one place this server types free text into a pane, and every
        restriction on it is load-bearing. /api/send deliberately takes a
        macro name and never a command string, because a pane is usually a
        shell and free text there is arbitrary execution. This is the
        exception an account with no shell needs: its Claude session is a
        read-only terminal, so the only way to say anything is through here,
        and it is narrowed until the exception cannot become the rule:

          * the session has to be a `claude-…` one, matched against a project
            this account can actually see. Not a name from the request: a
            shell session named through here would be exactly the hole;
          * it has to be this account's conversation, by the same holder
            record the proxy checks;
          * control characters are stripped (macros.say), so a message
            cannot move the cursor, clear the screen, or carry an escape
            sequence.

        What is left is text into Claude's own input box, which is what the
        person would have typed if they had a terminal.
        """
        me = self._who()
        want = str(req.get("session", ""))
        # THEIR OWN session on a project they can work on. The name carries the
        # account (roadmap #24), so this is one comparison rather than a
        # lookup: a name that is not the one this account's session would have
        # is somebody else's conversation, and typing into it is the thing a
        # read-only console must not become.
        project = next((name for name in project_names(me)
                        if want in [users.tmux_prefix(me) + n for n in agent_sessions(name)]), "")
        if not project or users.may(me, "claude", project):
            return self._json({"error": "not a session of yours"}, 403)
        on_node = self._session_on_node(want, str(req.get("node") or ""))
        if want not in {x["name"] for x in tmux_sessions()} and not on_node:
            return self._json({"error": "that conversation is not running"}, 409)
        return self._json(*macros.say(want, req.get("text", ""), on_node))

    def _send(self, req):
        """Type a macro's command lines into a shell session of the caller's
        and press Enter: macros.send. Neither kind is a command string from
        the request: a name from the fixed tables, or the id of a list the
        operator saved earlier through /api/custom."""
        session, name, cid = (req.get("session", ""), req.get("macro", ""),
                              req.get("custom", ""))
        if self._not_theirs(session):
            return None
        return self._json(*macros.send(session, name, cid,
                                       self._session_on_node(session, str(req.get("node") or ""))))


class Server(ThreadingHTTPServer):
    """The listen queue a room of people and sessions needs. socketserver's
    default is 5 connections waiting to be accepted: at 129 arriving together
    the kernel reset the rest, and the ones it kept retried on a backoff that
    turned seconds into a minute. Threads are daemons so a stop is not held
    up by a request still being answered."""
    request_queue_size = 128
    daemon_threads = True

    def get_request(self):
        # One port, both ways (R158 step 2, tls.py): a connection that opens
        # a TLS handshake is wrapped in the certificate in force, the rest
        # served as plain http, so a node keeps dialing http while a browser
        # gets https.
        sock, addr = super().get_request()
        return tls.wrap(sock), addr


# ---- function coverage (roadmap R76) ----------------------------------------
# Under `bb tests coverage` the harness names a file, and every function of
# this dashboard's own python that any thread enters is counted and written
# there, every few seconds and on the way out. A profile hook, not a trace
# hook: call and return events only, which is what function coverage needs
# and a tenth of the cost of line events. Nothing here runs otherwise.
_COV_OUT = os.environ.get("BB_COVERAGE_OUT", "")
_cov_counts = {}
_cov_lock = threading.Lock()
_COV_HERE = str(HERE)


def _cov_profile(frame, event, arg):
    if event != "call":
        return
    co = frame.f_code
    if not co.co_filename.startswith(_COV_HERE):
        return
    key = f"{co.co_filename}:{co.co_firstlineno}:{co.co_name}"
    with _cov_lock:
        _cov_counts[key] = _cov_counts.get(key, 0) + 1


def _cov_write():
    with _cov_lock:
        body = json.dumps({"suite": os.environ.get("BB_COVERAGE_SUITE") or "server",
                           "counts": dict(_cov_counts)})
    tmp = _COV_OUT + ".tmp"
    with contextlib.suppress(OSError):
        Path(tmp).write_text(body)
        os.replace(tmp, _COV_OUT)


def _cov_start():
    sys.setprofile(_cov_profile)
    threading.setprofile(_cov_profile)

    def loop():
        while True:
            time.sleep(3)
            _cov_write()
    threading.Thread(target=loop, daemon=True, name="coverage").start()
    atexit.register(_cov_write)


def main():
    if _COV_OUT:
        _cov_start()
    # No accounts is a normal first boot, not a failure. It used to be one:
    # the owner came from DASHBOARD_AUTH and the dashboard refused to start
    # without it, which put a password in the container's environment, where
    # it is visible to anything that can read the template, stays readable
    # forever, and is the one credential that opens a shell on this box.
    #
    # It is the first-run screen instead, and until somebody claims the
    # container that is the only page it serves. Nothing else is reachable
    # unauthenticated, which is the property the old refusal was protecting.
    if not users.all_users():
        print("dashboard: no accounts yet; the first page served will ask "
              "you to make the owner. Do it now: until you do, whoever "
              "reaches this port can.", flush=True)
    layout.prune_claude_tabs()
    # The JSON stores' numbered migrations past /config's stamp (R79), here,
    # once every module is configured: one needs project_list to answer,
    # which at import it could not (B496). The gate at the top took the copy.
    stateversion.migrate(STATE, {"state": STATE, "workspace": WORKSPACE, "project_names": lambda: project_names(users.ALL)})
    # ...and, on every start, the owner roles of projects that are gone for
    # good or never were (a clone that failed before B95, a folder purged by
    # hand), once the migrations have given the ones they give.
    try:
        membership.prune_gone(registry)
    except Exception as e:                                            # noqa: BLE001
        print(f"[dashboard] owner roles of gone projects not pruned: {type(e).__name__}: {e}", flush=True)
    # Daemons: these loops must die with the server, not hold it open.
    doctor.start()
    idle.start()
    if not NODES_OK:
        claudecode.start()        # the first check soon after the start, then every six hours
        agentcode.start()         # ...and the other coding agents' (R95 step 2)
    # The seed file once, before the first look at the release (R272 step 4).
    try:
        if seeded := apps.seed(settings.set_many):
            print(f"dashboard: seed.json applied: {seeded}", flush=True)
    except Exception as e:  # noqa: BLE001 (a seed never keeps the dashboard from starting)
        print(f"dashboard: seed.json not applied: {e}", flush=True)
    if "apps" not in featuresoff.off():
        apps.start()          # the apps from this controller's release, a while after the start, then daily
    threading.Thread(target=_compat_loop, name="compat", daemon=True).start()
    threading.Thread(target=log_sweep_loop, name="log-sweep", daemon=True).start()
    if BARE_METAL and "internet" not in featuresoff.off():
        releasecheck.start()      # a newer release, asked of GitHub a while after the start, then daily
    artifacts.start()         # every project's dist/ to its newest builds, every few minutes
    if not NODES_OK:
        threading.Thread(target=_room_loop, name="room", daemon=True).start()
        threading.Thread(target=_schedules_loop, name="schedules", daemon=True).start()
        threading.Thread(target=_reach_loop, name="reach", daemon=True).start()
    ciwatch.start()           # a project's CI, once a day (R117)
    releasesign.start()       # a release's unsigned APK, signed on its node (R106)
    if "tunnel" not in featuresoff.off():
        tunnel.apply()        # the home tunnel, where the settings say so (R176)
        # ...and the dashboard's own TLS as the settings say (R158 step 2),
        # with a loop that remakes the install's own certificate or asks
        # Let's Encrypt again a month before it ends.
        with contextlib.suppress(Exception):             # noqa: BLE001 (http is the fallback, said on the Doctor)
            tls.apply(settings.get, names=_tls_names())

        def _tls_loop():
            while True:
                time.sleep(6 * 3600)
                with contextlib.suppress(Exception):     # noqa: BLE001
                    if tls.renew_due():
                        if tls.mode_of(settings.get) == "self":
                            tls.apply(settings.get, names=_tls_names())
                        elif tls.mode_of(settings.get) == "acme":
                            _tls_issue()
        threading.Thread(target=_tls_loop, name="tls-renew", daemon=True).start()
    if toolchains.AUTOCHECK:
        threading.Thread(target=toolchains.versions_loop, daemon=True).start()
    # The copies the nodes hold, looked at here on a timer and announced when
    # they moved, so a node need not keep asking (B643).
    threading.Thread(target=wssync.look_loop, name="sync-look", daemon=True).start()
    if imagecheck.AUTOCHECK and "image-updates" not in featuresoff.off():  # every container's registry images, weekly (R195)
        threading.Thread(target=imagecheck.check_loop, name="image-check", daemon=True).start()
    if nginxproxy.AUTOCHECK and "image-updates" not in featuresoff.off():  # the nginx image, weekly (R192)
        threading.Thread(target=nginxproxy.check_loop, name="nginx-check", daemon=True).start()
        threading.Thread(target=scanners.check_loop, name="scanners-check", daemon=True).start()
        # ...and the ACME renewals (R150), thirty days before a pair ends.
        threading.Thread(target=nginxproxy.renew_loop, args=(containers, devactions, devapp),
                         name="nginx-acme", daemon=True).start()
    # A bare-metal install's start held or not (R56 step 9), read now, and
    # the clean-shutdown marker written when the service stops it cleanly.
    if BARE_METAL:
        h = held.boot()
        if h.get("held"):
            print(f"dashboard: the start is held: {'; '.join(h.get('why') or [])}", flush=True)

        def _on_term(signum, frame):
            del signum, frame
            held.shutdown_clean()
            raise SystemExit(0)
        signal.signal(signal.SIGTERM, _on_term)
    Server(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
