// The welcome panel: the guide a new person reads, and the changelog that
// says what moved since they last looked. One classic script beside
// index.html, like a tab's (docs/nodes.md §13), and the first section to
// leave the page's own script whole (R75, moved with bb map sections in
// hand: seven functions, one caller from outside, all covered). Pure
// declarations: the wiring that runs at load (the About button, the
// modal's own close, the welcome on the first poll) stays in index.html
// under the section's header, since it needs the page and its helpers.

"use strict";

const GUIDE_USER = `
  <h4>What this is</h4>
  <p>A Claude Code workstation in a browser. A project is a repository, kept
  and built on a node; a Claude session works on it, and the project's page
  is where you and Claude keep the plan.</p>
  <h4>Finding your way</h4>
  <ul>
    <li><b>The rail</b>, down the left edge: Home, Projects, Build,
      Containers, Machines, Sessions, Jobs and the rest, each a page. On a
      phone it is the bar at the foot, in the same order: Home, Projects,
      Build, Containers, and More for the others.</li>
    <li><b>The search</b> at the top jumps to a page, a project, a container or
      a node by name.</li>
    <li><b>The dock</b> at the foot of every page holds the chat and your
      terminals; a tab pulls it up, and on a phone it is a sheet.</li>
    <li><b>The bell</b> holds what needs your answer, and <b>the dot</b> beside
      it is the doctor's verdict on this controller.</li>
  </ul>
  <h4>Start here</h4>
  <ul>
    <li><b>Your profile</b>, in the gear: your name and email, which your commits
      carry. No Claude session starts without them.</li>
    <li><b>A project</b>: Start Claude opens a session, Shell a terminal, and its
      name opens its page: Overview, Plan (Roadmap, Bugs), Code (Git, Tests,
      Analysis), Ship (Artifacts, Docker) and Docs (Wiki, Design).</li>
    <li><b>Claude Code</b> runs on a node: the first Start Claude takes you to
      its sign-in there.</li>
  </ul>
  <h4>When something says no</h4>
  <p>A refusal names the way out, so read it rather than retry.</p>
  <h4>Something is wrong</h4>
  <p>File it on the project's Bugs: what you pressed and what it said back.
  Sessions read the same tracker.</p>`;
const GUIDE_ADMIN = GUIDE_USER + `
  <h4>As an administrator</h4>
  <ul>
    <li><b>Machines</b>: the nodes where builds, tests, CI, the emulator and
      sessions run, and what their disks hold. Enroll node gives you the
      script to run on a machine.</li>
    <li><b>Build</b>: what each node builds with (Toolchains), its emulator, a
      phone lent to it, and its CI runner.</li>
    <li><b>People</b>: accounts, roles and which projects each sees.</li>
    <li><b>Settings</b>: this controller's, each waiting for its Apply; and a
      project's own, from its page.</li>
  </ul>`;
let abPage = "guide", abLogLoaded = false;
function abShow(which){
  abPage = which;
  document.querySelectorAll(".abswitch button").forEach(b => b.classList.toggle("on", b.dataset.ab === which));
  $("abGuide").hidden = which !== "guide";
  $("abLog").hidden = which !== "log";
  if (which === "guide")
    $("abGuide").innerHTML = state?.can?.admin === false ? GUIDE_USER : GUIDE_ADMIN;
  if (which === "log" && !abLogLoaded) abLoadLog();
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
  $("aUp").textContent = state?.uptime || "unknown";
  abShow(which || abPage);
  $("aboutModal").hidden = false;
}
function closeAbout(){
  $("aboutModal").hidden = true;
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
// been running it. The pair is the point: an Unraid container keeps serving
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
