// The welcome panel: the guide a new person reads, and the changelog that
// says what moved since they last looked. One classic script beside
// index.html, like a tab's (docs/nodes.md §13), and the first section to
// leave the page's own script whole (R75, moved with bb map sections in
// hand: seven functions, one caller from outside, all covered). Pure
// declarations: the wiring that runs at load (the About button, the
// modal's own close, the welcome on the first poll) stays in index.html
// under the section's header, since it needs the page and its helpers.

"use strict";

// The guide is docs/start-here.md, read through the Help page's docs: one
// text for both, so the two cannot say different things. Its "As an
// administrator" section is left out for an account that is not one.
const AB_GUIDE_DOC = "start-here";
const AB_ADMIN_HEAD = "## As an administrator";
let abGuideDoc = null;       // {text} | {error}, read once
let abGuideTitles = {};      // doc name -> title, from the Help listing

function abGuideText(text, admin){
  let t = wikiUntitled(String(text || ""));
  if (!admin){
    const at = t.indexOf("\n" + AB_ADMIN_HEAD);
    if (at >= 0){
      const next = t.indexOf("\n## ", at + 1 + AB_ADMIN_HEAD.length);
      t = t.slice(0, at) + (next >= 0 ? t.slice(next) : "\n");
    }
  }
  // A link to a file outside the docs (../CONTRIBUTING.md) has nothing to
  // open here, so it is its words, as on the Help page.
  return t.replace(/\[([^\]]*)\]\((?!https?:)([^)#]*\/[^)]*)\)/g, "$1");
}

async function abLoadGuide(){
  const el = $("abGuide");
  if (!abGuideDoc){
    el.innerHTML = skel("lines", 8);
    try{
      const [doc, index] = await Promise.all([fetch("/api/help?doc=" + AB_GUIDE_DOC), fetch("/api/help")]
        .map(p => p.then(r => r.json())));
      abGuideDoc = doc;
      if (!index.error) abGuideTitles = helpTitles(index);
    }
    catch(e){ abGuideDoc = {error: "the guide could not be read: " + e}; }
  }
  if (abPage !== "guide") return;
  if (abGuideDoc.error){ el.innerHTML = `<p class="hint bad">${esc(abGuideDoc.error)}</p>`; return; }
  el.innerHTML = wikiMarkdown(abGuideText(abGuideDoc.text, state?.can?.admin !== false), abGuideTitles);
  // A link to another doc opens it on the Help page.
  el.querySelectorAll("a.wklink[data-page]").forEach(a => a.onclick = e => {
    e.preventDefault();
    closeAbout();
    location.hash = "#/help/" + encodeURIComponent(a.dataset.page.replace(/\.md$/, ""));
  });
}
let abPage = "guide", abLogLoaded = false;
function abShow(which){
  abPage = which;
  document.querySelectorAll(".abswitch button").forEach(b => b.classList.toggle("on", b.dataset.ab === which));
  $("abGuide").hidden = which !== "guide";
  $("abLog").hidden = which !== "log";
  $("abCredits").hidden = which !== "credits";
  $("abBuild").hidden = which !== "log";
  if (which === "credits") abDrawCredits();
  if (which === "guide") abLoadGuide();
  if (which === "log" && !abLogLoaded) abLoadLog();
}
// ---- Credits: what BuilderBot is built on --------------------------------
// The open-source work BuilderBot itself ships and runs, each with what it
// does here and its license: what the controller's image (the Dockerfile),
// the node provisioner, the OS image (image/mkosi.conf), the Android app
// and the official catalog packs put there, which a change to any of those
// updates. Nothing a person adds through the Library (a third-party pack, a
// sideloaded app) is credited here (the operator, 28 Oct).
const AB_CREDITS = [
  ["In the controller's image", [
    ["xterm.js", "every terminal in the dock", "MIT", "https://github.com/xtermjs/xterm.js"],
    ["noVNC and pako", "a VM's Screen in the dock", "MPL-2.0, MIT", "https://github.com/novnc/noVNC"],
    ["Python", "the dashboard's server and the node agent", "PSF-2.0", "https://www.python.org/"],
    ["Node.js", "the page's tests and the projects' JavaScript", "MIT", "https://nodejs.org/"],
    ["Playwright", "the browser that tests the page and takes its pictures", "Apache-2.0", "https://playwright.dev/"],
    ["Docker CLI, Compose and Buildx", "a project's containers, on its node's Docker", "Apache-2.0", "https://www.docker.com/"],
    ["cloudflared", "the controller's own tunnel from home", "Apache-2.0", "https://github.com/cloudflare/cloudflared"],
    ["Git and Git LFS", "every project's history", "GPL-2.0, MIT", "https://git-scm.com/"],
    ["GitHub CLI", "pull requests and CI logs", "MIT", "https://cli.github.com/"],
    ["tmux", "the sessions that outlive a closed tab", "ISC", "https://github.com/tmux/tmux"],
    ["SQLite", "the controller's record of nodes and jobs", "public domain", "https://sqlite.org/"],
    ["cryptography", "every seal the controller and a node keep (ChaCha20-Poly1305, X25519, HKDF)", "Apache-2.0 or BSD-3-Clause", "https://cryptography.io/"],
    ["ShellCheck, hadolint, actionlint, Ruff and yq", "bb lint", "GPL-3.0, GPL-3.0, MIT, MIT, MIT", "https://www.shellcheck.net/"],
    ["uv and mise", "Python and the toolchains' versions", "MIT or Apache-2.0, MIT", "https://github.com/astral-sh/uv"],
    ["ripgrep, fd and fzf", "finding things in a tree", "MIT", "https://github.com/BurntSushi/ripgrep"],
    ["FFmpeg and ImageMagick", "the screen recordings and pictures bb capture makes", "LGPL-2.1+, ImageMagick", "https://ffmpeg.org/"],
    ["Ubuntu", "the image's base", "various, free", "https://ubuntu.com/"],
  ]],
  ["On a node", [
    ["Claude Code", "what a Claude session runs, by Anthropic", "Anthropic's terms", "https://www.anthropic.com/claude-code"],
    ["Codex CLI", "what a ChatGPT session runs, by OpenAI", "Apache-2.0", "https://github.com/openai/codex"],
    ["Docker Engine", "a project's containers and nginx", "Apache-2.0", "https://www.docker.com/"],
    ["QEMU, KVM and libvirt", "the VMs", "GPL-2.0, LGPL-2.1+", "https://libvirt.org/"],
    ["EDK II (OVMF)", "a VM's UEFI firmware", "BSD-2-Clause-Patent", "https://github.com/tianocore/edk2"],
    ["cloud-init", "a cloud image's first boot", "Apache-2.0 or GPL-3.0", "https://cloud-init.io/"],
    ["nftables", "the session, hosting and VM firewalls", "GPL-2.0", "https://netfilter.org/projects/nftables/"],
    ["nginx", "a node's hostnames and certificates", "BSD-2-Clause", "https://nginx.org/"],
    ["Tailscale", "the SSH door, where a node uses it", "BSD-3-Clause", "https://tailscale.com/"],
    ["LiteLLM", "the model router a node runs for any model", "MIT", "https://github.com/BerriAI/litellm"],
    ["Ollama", "local models beside the router, where you turn it on", "MIT", "https://ollama.com/"],
    ["OpenCode", "a session on any model through the router", "MIT", "https://opencode.ai/"],
    ["Semgrep, Trivy and mobsfscan", "the static analysis scanners a node runs over its projects", "LGPL-2.1, Apache-2.0, LGPL-3.0", "https://semgrep.dev/"],
    ["WireGuard", "a node's tunnel to the controller, where it enrolls through one", "GPL-2.0", "https://www.wireguard.com/"],
  ]],
  ["In BuilderBot OS and the bare-metal install", [
    ["Debian", "the image's base, pinned to one dated snapshot", "various, free", "https://www.debian.org/"],
    ["mkosi and systemd", "how the image is built and how it boots", "LGPL-2.1+", "https://github.com/systemd/mkosi"],
    ["GRUB", "the boot menu with its two slots and the fallback", "GPL-3.0", "https://www.gnu.org/software/grub/"],
    ["OpenZFS", "the pools", "CDDL-1.0", "https://openzfs.org/"],
    ["mergerfs and SnapRAID", "the array of mixed disks and its parity", "ISC, GPL-3.0", "https://github.com/trapexit/mergerfs"],
    ["Samba and nfs-utils", "the SMB and NFS shares", "GPL-3.0, GPL-2.0", "https://www.samba.org/"],
    ["smartmontools", "what each disk says of itself", "GPL-2.0", "https://www.smartmontools.org/"],
    ["Network UPS Tools", "the UPS, where there is one", "GPL-2.0+", "https://networkupstools.org/"],
  ]],
  ["The official catalog's toolchains", [
    ["Temurin JDK, Go, Rust, Node.js, Python (uv), .NET, Swift, Zig, Flutter, the Android SDK's tools, Playwright's browsers, PyTorch, FFmpeg, LibreOffice, PlantUML, Mermaid, pandoc, piper and whisper",
     "what the Library installs on a node for a project to build with, each fetched from its publisher", "each its own", ""],
  ]],
  ["Where a VM comes from", [
    ["Ubuntu, Debian, Fedora, Rocky Linux, AlmaLinux, CentOS Stream, Arch Linux, openSUSE, Gentoo and Alpine",
     "the cloud images New VM offers, each from its publisher and checked against its checksums", "each its own", ""],
  ]],
];
function abDrawCredits(){
  const el = $("abCredits");
  if (el.dataset.drawn) return;
  el.dataset.drawn = "1";
  const cols = [{label: "What"}, {label: "Here for"}, {label: "License"}];
  el.innerHTML = `<p>BuilderBot is built on other people's open work. Thank you to everyone behind it.</p>${
    AB_CREDITS.map(([head, rows]) => `<h4>${esc(head)}</h4>${tblWrap(cols, rows.map(([name, what, lic, url]) =>
      tblLine(cols, [url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(name)}</a>` : esc(name), esc(what), esc(lic)])).join(""), "abcred")}`).join("")}
    <p class="dim">The Android app is built with Kotlin and Jetpack Compose (Apache-2.0). BuilderBot itself is Apache-2.0.</p>`;
}

async function abLoadLog(){
  const el = $("abLog");
  el.innerHTML = `${skel("lines")}`;
  let j;
  try{ j = await (await fetch("/api/welcome")).json(); }
  catch(e){ el.innerHTML = `<p class="dim">changelog: ${esc(String(e))}</p>`; return; }
  abLogLoaded = true;
  abDrawLog(j);
}
// The draw, apart from the fetch: what this panel shows is the server's
// answer, and the arrangement of it is worth being able to render from a
// payload rather than only from whatever the image happens to carry.
//
// The server sends what is unreleased plus the newest minor's releases, and
// says how many older ones it held back; this panel is read by somebody
// asking what changed in the build in front of them, and the file behind it
// grows for the life of the project.
// A release the size of a book is one press away from being read, and not
// the first thing in the way of it (B95). The first bump a project ever does
// dates everything ever logged (362 lines here) and this panel opens on an
// image update, so that was the changelog: one scroll nobody finishes.
const AB_CAP = 25;
let abAllOf = new Set();     // sections somebody asked to see whole
let abLogSeen = null;        // the last payload, to redraw from without refetching

function abDrawLog(j){
  const el = $("abLog");
  abLogSeen = j;
  if (!j.present){ el.innerHTML = `<p class="dim">This image carries no changelog.</p>`; return; }
  // Everything above the entry that carries the commit this account last
  // acknowledged is new to it; the line is drawn there. An image whose
  // commit is a logging commit matches no entry, and then nothing is marked
  // rather than everything.
  const seen = j.seen || "";
  let boundary = -1, i = 0;
  const flat = [];
  for (const s of j.sections) for (const e of s.entries) flat.push(e);
  if (seen) boundary = flat.findIndex(e => e.shas.some(sha => seen.startsWith(sha)));
  const rows = [];
  for (const s of j.sections){
    if (!s.entries.length) continue;
    rows.push(`<h4>${esc(s.title)}${s.title === "Unreleased"
      ? ` <span class="dim">· in this image, not yet a numbered release</span>` : ""}</h4>`);
    // How much of it to draw. Never a cut that hides the "new since you last
    // looked" line, because that line is the one thing somebody opening this
    // panel came for; and never "show all 27 of 30", which asks a question
    // worth less than the two rows it saves.
    const holds = boundary >= 0 && boundary >= i && boundary < i + s.entries.length;
    const cut = (s.entries.length > AB_CAP + 5 && !holds && !abAllOf.has(s.title))
      ? AB_CAP : s.entries.length;
    // The categories the section was arranged into, drawn by watching the
    // name change down a flat list: the entries arrive in the file's order
    // and the boundary below is a count through that order, so grouping here
    // costs nothing and nesting would have cost both.
    let cat = null, open = false;
    const shut = () => { if (open){ rows.push(`</ul>`); open = false; } };
    let n = 0;
    for (const e of s.entries){
      if (n++ === cut){
        shut();
        rows.push(`<p class="dim abmore"><a href="#" data-abmore="${esc(s.title)}"
          >show all ${s.entries.length}</a> lines in ${esc(s.title)}</p>`);
        i += s.entries.length - cut;     // the boundary counts through the file
        break;
      }
      const mine = e.cat || "";
      if (mine !== cat){
        shut();
        if (mine) rows.push(`<div class="abcat">${esc(mine)}</div>`);
        cat = mine;
      }
      if (!open){ rows.push(`<ul>`); open = true; }
      if (boundary >= 0 && i === boundary)
        rows.push(`</ul><div class="abnew">everything above is new since you last looked</div><ul>`);
      rows.push(`<li${boundary >= 0 && i >= boundary ? ' class="old"' : ""}>${esc(e.text)}</li>`);
      i++;
    }
    shut();
  }
  if (j.held)
    rows.push(`<p class="dim" id="abHeld">${j.held} earlier release${j.held === 1 ? "" : "s"}`
      + ` ${j.held === 1 ? "is" : "are"} in CHANGELOG.md.</p>`);
  el.innerHTML = rows.join("") || `<p class="dim">Nothing logged yet.</p>`;
  el.querySelectorAll("[data-abmore]").forEach(a => a.onclick = e => {
    e.preventDefault();
    abAllOf.add(a.dataset.abmore);
    if (abLogSeen) abDrawLog(abLogSeen);
  });
}
function openAbout(which){
  // Host and uptime read at open, not at draw: the popup should say what is
  // true now, and uptime in particular moves while the page sits.
  $("aHost").textContent = state?.host || "unknown";
  // As Controller settings says it (1m 39s), never ps's raw 05:54.
  $("aUp").textContent = state?.uptime ? shortUptime(state.uptime) : "unknown";
  abShow(which || abPage);
  $("aboutModal").hidden = false;
}
function closeAbout(){
  $("aboutModal").hidden = true;
  // The page behind it toured now, when Show the tours again was pressed
  // here: no tour stands over a dialog, so none was started under it.
  tourSoon(tabOf(panes[0])?.kind);
  // Read once: closing the panel is the acknowledgement, for both pages.
  const w = state?.welcome, rev = state?.image?.rev || "";
  if (!state?.me || !w) return;
  const patch = {};
  if (!w.seen) patch.welcome_seen = true;
  if (rev && w.image_seen !== rev) patch.image_seen = rev;
  if (!Object.keys(patch).length) return;
  w.seen = true; w.image_seen = rev || w.image_seen;
  fetch("/api/users", {method: "POST", headers: {"Content-Type": "application/json"},
                       body: JSON.stringify({action: "prefs", prefs: patch})}).catch(() => {});
}

// ---- the build this container runs --------------------------------------

// Which build of the image this container is running, beside how long it has
// been running it. The pair is the point: a NAS's container keeps serving
// whatever it last pulled, so "how long has this been up" and "what is this"
// are different questions, and only one of them used to be answerable. The
// stamp is what /opt is serving; bb drift is what a checkout has changed since.
function drawBuild(img){
  const el = $("build"), rev = img?.rev || "", ver = img?.version || "";
  // The version when there is one, because it is the half that can be
  // ordered: two shas do not say which came first, which is the question
  // being asked whenever anybody looks at this. The rest moved from a hover
  // tooltip into the About popup: a phone cannot hover, and the truncated
  // string it showed instead answered nothing.
  setText(el, ver || (rev ? rev.slice(0, 7) : "unstamped"));
  setText($("aVer"), ver || "(no version stamp)");
  setText($("aRev"), rev || "unstamped: built outside CI, or older than the stamp itself");
  setText($("aBuilt"), img?.built || "unknown");
}

// ---- the welcome panel: the guide, and the changelog ----------------------

// Opened by itself, once each: on the guide for an account that has not
// read it, else on the changelog for an image this account has not seen.
// Decided on the first poll, when the account and the image are known.
let welcomed = false;
function welcomeOnce(){
  // Not over the setup page: its steps come first, and the guide waits for
  // the poll after Finish (B839).
  if (welcomed || !state?.me || !state.welcome || setupNeeded()) return;
  welcomed = true;
  const w = state.welcome, rev = state.image?.rev || "";
  // An administrator has Home's Getting started for this (R267), and a
  // guide over it would be two at once; a person invited later has none.
  if (!w.seen){ if (!state?.can?.admin) openAbout("guide"); }
  else if (rev && w.image_seen !== rev) openAbout("log");
}
