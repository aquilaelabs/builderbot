// The welcome panel: the guide a new person reads, and the changelog that
// says what moved since they last looked. One classic script beside
// index.html, like a tab's (docs/nodes.md §13), and the first section to
// leave the page's own script whole (R75, moved with bb map sections in
// hand: seven functions, one caller from outside, all covered). Pure
// declarations: the wiring that runs at load (the About button, the
// modal's own close, the welcome on the first poll) stays in index.html
// under the section's header, since it needs the page and its helpers.
const GUIDE_USER = `
  <h4>What this is</h4>
  <p>BuilderBot is a Claude Code workstation in a browser. Each project on the
  left is a repository; a Claude session on it edits that tree, and the
  notebook beside it is where you and Claude keep the plan.</p>
  <h4>Start here</h4>
  <ul>
    <li><b>Your profile</b> (the gear, top right): set your name and email and
      the git identity your commits carry. No session starts until they are
      set, so the first thing to do is this.</li>
    <li><b>Sign in to Claude</b> (the card under Doctor, which says so in red
      until you have): your own Anthropic account, once. The sign-in runs on a
      node and you paste the code back here; the login stays on that machine
      and is yours, not anybody else's. Sessions will not start without
      it.</li>
    <li><b>A project</b>: press its name to open the notebook, <b>Claude</b> to
      start a session on it, and the terminal button for a shell.</li>
    <li><b>The notebook</b>: Briefing (rules and memories), Roadmap (what to
      do next, sent to Claude one step at a time), Bugs, Git (the repository
      read out, with Send to Claude), Artifacts (what it built, the version),
      Tests, Analysis.</li>
    <li><b>The bell</b>: what needs your answer, whether a session asking to reach
      your phone, or a change waiting for approval, and what the page said.</li>
    <li><b>Your phone</b>: Tools → Phone connects a handset on wireless
      debugging to a node; a session then asks you before it touches it.</li>
  </ul>
  <h4>When something says no</h4>
  <p>A refusal here is meant to name the way out, so it is worth reading
  rather than retrying. The usual four: you are not signed in to Claude yet;
  the node a project builds on is away, so nothing runs there until it is
  back; the tool a build wants is not on that node, which is an
  administrator's to install; or this project does not let a session push, so
  the commit is yours to push from the Git view.</p>
  <h4>Telling us something is wrong</h4>
  <p>The Bugs tab of the project's notebook files it where we look, and a
  report that says what you pressed and what it said back is worth ten that
  say it broke. It is the same tracker the sessions read, so what you file is
  what gets picked up.</p>
  <h4>On a phone</h4>
  <p>The same page: the bar at the bottom switches between the sidebar and the
  terminal, and the keys panel stands in for the ones a soft keyboard hides.</p>`;
const GUIDE_ADMIN = GUIDE_USER + `
  <h4>As an administrator</h4>
  <ul>
    <li><b>Nodes</b>: the machines where builds, tests, CI, the emulator and
      sessions run. Enroll one with <b>Enroll node</b> and
      <code>nodes/provision-linux.sh</code> on the machine (any common distribution;
      <code>--check</code> first says whether it can). Each node's row has its
      storage, network, runner and a lock that keeps system changes at its
      own console.</li>
    <li><b>Tools</b>: the toolchains a node carries, the JDK, the Android
      SDK and its system images, Playwright, installed per node from the
      catalog. A project builds with what its node has.</li>
    <li><b>Users</b> (Administration): accounts, roles and which projects each
      may see. A user works on projects; an administrator also runs the
      machinery and answers a session asking for root on a node.</li>
    <li><b>Controller settings</b>: the things that used to be environment
      variables. Everything here waits for Save.</li>
    <li><b>Approvals</b>: a session's roadmap items, bugs and rules can land on
      their own, be held for you, or be refused, per project, per tab.</li>
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
  el.innerHTML = `<div class="loading">loading…</div>`;
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
  $("aHost").textContent = state?.host || "—";
  $("aUp").textContent = state?.uptime || "—";
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
